"""Turn gates: who may start a chat turn now, and what a retried client_turn_id gets back.

  - one running model turn per session (a second concurrent one gets 409 turn_in_progress)
  - at most `ip_cap` running model turns per client key (IPv4 address or IPv6 /64), else 429 (review S1)
  - a completed turn's SSE frames are kept for `ttl_s`, keyed by (session_id, client_turn_id), so a client retry
    replays the answer instead of running (and paying for) the turn again

Model-free safety turns (emergency / self-harm precheck) take a non-exclusive claim: they never wait for, or
are refused by, the session lock or the IP cap (review C9).

MemoryTurnGate holds all of this in process memory (dev, single worker). RedisTurnGate shares it between workers
(review P2/S5): the session lock is `SET NX EX` released by a compare-and-delete script, the IP count is
INCR/DECR with a TTL, and the replay frames are a JSON string with a TTL. Lock and counter TTLs bound what a
crashed worker can leave behind. Every gate also remembers, in process, which session owns which turn (a fast
path for feedback; the database is the fallback).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from redis.exceptions import RedisError

from app.api.errors import TurnInProgress
from core.errors import DependencyUnavailable, RateLimited

log = structlog.get_logger(__name__)
REPLAY_TTL_S = 10 * 60
REPLAY_MAX = 2000
REPLAY_MAX_BYTES = 64 * 1024
IP_CONCURRENT_TURNS = 2
CONCURRENT_RETRY_AFTER_S = 5.0
LOCK_TTL_S = 120  # > turn deadline (45 s) + cancel grace: a live turn never loses its lock
OWNER_MAX = REPLAY_MAX * 4

RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


@dataclass(frozen=True)
class TurnClaim:
    session_id: str
    client_turn_id: str
    ip_key: str
    exclusive: bool = True  # holds the session lock and an IP slot (False for model-free safety turns)


class TurnGate(Protocol):
    @property
    def running(self) -> int: ...

    async def replay(self, session_id: str, client_turn_id: str) -> tuple[str, ...] | None: ...

    async def begin(self, claim: TurnClaim) -> None: ...

    async def finish(self, claim: TurnClaim, turn_id: str, frames: tuple[str, ...] | None) -> None: ...

    def release_nowait(self, claim: TurnClaim) -> None: ...

    def owns(self, turn_id: str, session_id: str) -> bool: ...


def _concurrent() -> RateLimited:
    return RateLimited(
        "too many concurrent turns from this client", retry_after_s=CONCURRENT_RETRY_AFTER_S, scope="concurrent"
    )


class _LocalClaims:
    """Claims held by this process (the `running` count) and the turn -> session owner map."""

    def __init__(self) -> None:
        self._active: dict[TurnClaim, int] = {}
        self._turn_owner: OrderedDict[str, str] = OrderedDict()

    @property
    def running(self) -> int:
        return sum(self._active.values())

    def _hold(self, claim: TurnClaim) -> None:
        self._active[claim] = self._active.get(claim, 0) + 1

    def _drop(self, claim: TurnClaim) -> bool:
        """Forget one hold of `claim`; False when it was not held (release is idempotent)."""
        count = self._active.get(claim, 0)
        if count == 0:
            return False
        if count == 1:
            del self._active[claim]
        else:
            self._active[claim] = count - 1
        return True

    def _own(self, turn_id: str, session_id: str) -> None:
        self._turn_owner[turn_id] = session_id
        while len(self._turn_owner) > OWNER_MAX:
            self._turn_owner.popitem(last=False)

    def owns(self, turn_id: str, session_id: str) -> bool:
        return self._turn_owner.get(turn_id) == session_id


@dataclass(frozen=True)
class _Completed:
    frames: tuple[str, ...]
    at: float


class MemoryTurnGate(_LocalClaims):
    def __init__(
        self,
        *,
        ip_cap: int = IP_CONCURRENT_TURNS,
        ttl_s: float = REPLAY_TTL_S,
        max_entries: int = REPLAY_MAX,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._locks: dict[str, str] = {}
        self._per_ip: dict[str, int] = {}
        self._done: OrderedDict[tuple[str, str], _Completed] = OrderedDict()
        self._ip_cap = ip_cap
        self._ttl = ttl_s
        self._max = max_entries
        self._clock = clock

    def _expire(self) -> None:
        now = self._clock()
        while self._done:
            item = next(iter(self._done.values()))
            if now - item.at <= self._ttl and len(self._done) <= self._max:
                break
            self._done.popitem(last=False)

    async def replay(self, session_id: str, client_turn_id: str) -> tuple[str, ...] | None:
        self._expire()
        done = self._done.get((session_id, client_turn_id))
        return done.frames if done else None

    async def begin(self, claim: TurnClaim) -> None:
        if claim.exclusive:
            if claim.session_id in self._locks:
                raise TurnInProgress("a turn of this session is still running")
            if self._per_ip.get(claim.ip_key, 0) >= self._ip_cap:
                raise _concurrent()
            self._locks[claim.session_id] = claim.client_turn_id
            self._per_ip[claim.ip_key] = self._per_ip.get(claim.ip_key, 0) + 1
        self._hold(claim)

    def release_nowait(self, claim: TurnClaim) -> None:
        if not self._drop(claim) or not claim.exclusive:
            return
        if self._locks.get(claim.session_id) == claim.client_turn_id:
            del self._locks[claim.session_id]
        left = self._per_ip.get(claim.ip_key, 0) - 1
        if left > 0:
            self._per_ip[claim.ip_key] = left
        else:
            self._per_ip.pop(claim.ip_key, None)

    async def finish(self, claim: TurnClaim, turn_id: str, frames: tuple[str, ...] | None) -> None:
        self.release_nowait(claim)
        self._own(turn_id, claim.session_id)
        if frames is not None:
            self._done[(claim.session_id, claim.client_turn_id)] = _Completed(frames, self._clock())
        self._expire()


class RedisTurnGate(_LocalClaims):
    def __init__(
        self,
        client: Any,
        *,
        ip_cap: int = IP_CONCURRENT_TURNS,
        lock_ttl_s: int = LOCK_TTL_S,
        replay_ttl_s: int = REPLAY_TTL_S,
        replay_max_bytes: int = REPLAY_MAX_BYTES,
        prefix: str = "ausculta:turn:",
    ) -> None:
        super().__init__()
        self._r = client
        self._release_lock = client.register_script(RELEASE_LOCK_LUA)
        self._ip_cap = ip_cap
        self._lock_ttl = lock_ttl_s
        self._replay_ttl = replay_ttl_s
        self._replay_max = replay_max_bytes
        self._prefix = prefix
        self._tasks: set[asyncio.Task[None]] = set()

    def _lock_key(self, session_id: str) -> str:
        return f"{self._prefix}lock:{session_id}"

    def _ip_key(self, ip_key: str) -> str:
        return f"{self._prefix}inflight:{ip_key}"

    def _replay_key(self, session_id: str, client_turn_id: str) -> str:
        return f"{self._prefix}replay:{session_id}:{client_turn_id}"

    async def replay(self, session_id: str, client_turn_id: str) -> tuple[str, ...] | None:
        try:
            raw = await self._r.get(self._replay_key(session_id, client_turn_id))
        except RedisError as exc:
            raise DependencyUnavailable("turn store unavailable") from exc
        if raw is None:
            return None
        frames = json.loads(raw)
        return tuple(str(f) for f in frames)

    async def begin(self, claim: TurnClaim) -> None:
        if claim.exclusive:
            try:
                await self._claim(claim)
            except RedisError as exc:
                raise DependencyUnavailable("turn store unavailable") from exc
        self._hold(claim)

    async def _claim(self, claim: TurnClaim) -> None:
        lock = self._lock_key(claim.session_id)
        if not await self._r.set(lock, claim.client_turn_id, nx=True, ex=self._lock_ttl):
            raise TurnInProgress("a turn of this session is still running")
        inflight = self._ip_key(claim.ip_key)
        count = int(await self._r.incr(inflight))
        await self._r.expire(inflight, self._lock_ttl)
        if count > self._ip_cap:
            await self._r.decr(inflight)
            await self._release_lock(keys=[lock], args=[claim.client_turn_id])
            raise _concurrent()

    async def _release(self, claim: TurnClaim) -> None:
        try:
            await self._release_lock(keys=[self._lock_key(claim.session_id)], args=[claim.client_turn_id])
            inflight = self._ip_key(claim.ip_key)
            if int(await self._r.decr(inflight)) <= 0:
                await self._r.delete(inflight)
        except RedisError as exc:  # the TTLs free what we could not
            log.warning("turn_gate_release_failed", error=type(exc).__name__)

    def release_nowait(self, claim: TurnClaim) -> None:
        """Best effort from a finalizer: schedule the release on the running loop, else rely on the TTLs."""
        if not self._drop(claim) or not claim.exclusive:
            return
        try:
            task = asyncio.get_running_loop().create_task(self._release(claim))
        except RuntimeError:
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def finish(self, claim: TurnClaim, turn_id: str, frames: tuple[str, ...] | None) -> None:
        if self._drop(claim) and claim.exclusive:
            await self._release(claim)
        self._own(turn_id, claim.session_id)
        if frames is None:
            return
        payload = json.dumps(list(frames), ensure_ascii=False)
        if len(payload.encode("utf-8")) > self._replay_max:
            log.info("turn_replay_not_stored", reason="too_large")
            return
        try:
            key = self._replay_key(claim.session_id, claim.client_turn_id)
            await self._r.set(key, payload, ex=self._replay_ttl)
        except RedisError as exc:
            log.warning("turn_replay_store_failed", error=type(exc).__name__)


__all__ = [
    "IP_CONCURRENT_TURNS",
    "RELEASE_LOCK_LUA",
    "MemoryTurnGate",
    "RedisTurnGate",
    "TurnClaim",
    "TurnGate",
]
