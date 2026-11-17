"""Per-session conversation state: turn count, strikes, lock, sticky risk flags and the last few REDACTED
user turns (needed for the router context and query rewriting). Kept in memory (dev) or Redis (prod) with
the session lifetime as TTL; never written to the relational database (no transcript text is persisted).

Turns change the state only through `SessionStore.apply(state, SessionUpdate)`: an atomic delta (increment the
turn count and strikes, add sticky risks, append to the history window). Two workers, or a model turn and a
concurrent safety turn of the same session, therefore never overwrite each other's updates (review P2/S5).
`put` (whole-state write) is only used when a session is created."""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from redis.exceptions import RedisError

from core.errors import DependencyUnavailable
from core.schemas.chat import HistoryTurn, Locale, RiskKind

SESSION_TTL_S = 2 * 60 * 60


@dataclass(frozen=True)
class SessionUpdate:
    """One atomic change of a session (all parts optional)."""

    turn_text: str | None = None  # count one more turn and keep this (redacted) user text in the history
    window: int = 0  # history window (user turns) when turn_text is set
    risks: frozenset[RiskKind] = frozenset()  # sticky risk flags to add
    strike: bool = False  # add one strike (locks the session at strikes_to_lock)
    strikes_to_lock: int = 3

    @property
    def is_empty(self) -> bool:
        return self.turn_text is None and not self.risks and not self.strike


@dataclass(frozen=True)
class SessionState:
    session_id: str
    locale: Locale
    created_at: datetime
    expires_at: datetime
    turns_used: int = 0
    strikes: int = 0
    locked: bool = False
    sticky_risks: frozenset[RiskKind] = frozenset()
    history: tuple[HistoryTurn, ...] = field(default=())

    def with_turn(self, user_text: str, *, window: int) -> SessionState:
        history = (*self.history, HistoryTurn(role="user", text=user_text))[-window:] if window else ()
        return replace(self, turns_used=self.turns_used + 1, history=history)

    def with_risks(self, kinds: frozenset[RiskKind]) -> SessionState:
        return replace(self, sticky_risks=self.sticky_risks | kinds)

    def with_strike(self, strikes_to_lock: int) -> SessionState:
        strikes = self.strikes + 1
        return replace(self, strikes=strikes, locked=self.locked or strikes >= strikes_to_lock)

    def applied(self, update: SessionUpdate) -> SessionState:
        """The pure form of SessionStore.apply (used by the memory store and as a fallback)."""
        state = self
        if update.turn_text is not None:
            state = state.with_turn(update.turn_text, window=update.window)
        if update.risks:
            state = state.with_risks(update.risks)
        if update.strike:
            state = state.with_strike(update.strikes_to_lock)
        return state

    def user_history(self) -> tuple[str, ...]:
        return tuple(t.text for t in self.history if t.role == "user")

    def to_json(self) -> str:
        return json.dumps(
            {
                "session_id": self.session_id,
                "locale": self.locale,
                "created_at": self.created_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
                "turns_used": self.turns_used,
                "strikes": self.strikes,
                "locked": self.locked,
                "sticky_risks": sorted(k.value for k in self.sticky_risks),
                "history": [t.model_dump() for t in self.history],
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> SessionState:
        d: dict[str, Any] = json.loads(raw)
        return cls(
            session_id=str(d["session_id"]),
            locale=d["locale"],
            created_at=datetime.fromisoformat(d["created_at"]),
            expires_at=datetime.fromisoformat(d["expires_at"]),
            turns_used=int(d["turns_used"]),
            strikes=int(d["strikes"]),
            locked=bool(d["locked"]),
            sticky_risks=frozenset(RiskKind(k) for k in d.get("sticky_risks", [])),
            history=tuple(HistoryTurn.model_validate(t) for t in d.get("history", [])),
        )


class SessionStore(Protocol):
    async def get(self, session_id: str) -> SessionState | None: ...

    async def put(self, state: SessionState) -> None: ...

    async def apply(self, state: SessionState, update: SessionUpdate) -> SessionState | None:
        """Apply `update` atomically to the stored session; returns the fresh state (None when it is gone)."""
        ...

    async def ping(self) -> bool: ...


class MemorySessionStore:
    """In-process store with TTL and a size bound (dev / tests / single-instance deployments)."""

    def __init__(self, *, max_sessions: int = 50_000, clock: Callable[[], float] = time.monotonic) -> None:
        self._data: OrderedDict[str, tuple[float, SessionState]] = OrderedDict()
        self._max = max_sessions
        self._clock = clock
        self._lock = asyncio.Lock()

    def _live(self, session_id: str) -> SessionState | None:
        item = self._data.get(session_id)
        if item is None:
            return None
        deadline, state = item
        if self._clock() > deadline or state.expires_at <= datetime.now(UTC):
            del self._data[session_id]
            return None
        return state

    def _store(self, state: SessionState) -> None:
        self._data[state.session_id] = (self._clock() + SESSION_TTL_S, state)
        self._data.move_to_end(state.session_id)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    async def get(self, session_id: str) -> SessionState | None:
        async with self._lock:
            return self._live(session_id)

    async def put(self, state: SessionState) -> None:
        async with self._lock:
            self._store(state)

    async def apply(self, state: SessionState, update: SessionUpdate) -> SessionState | None:
        async with self._lock:
            current = self._live(state.session_id)
            if current is None:
                return None
            fresh = current.applied(update)
            self._store(fresh)
            return fresh

    async def ping(self) -> bool:
        return True


def _text(raw: Any) -> str:
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


class RedisSessionStore:
    """Redis-backed store shared by every worker. One session = three keys with the session TTL:
    `{prefix}{sid}` hash (meta JSON, turns_used, strikes, locked), `{prefix}{sid}:risks` set and
    `{prefix}{sid}:history` list. Updates are HINCRBY / SADD / RPUSH+LTRIM inside one MULTI/EXEC, so they
    commute and never lose a concurrent update. Redis failures surface as DependencyUnavailable (503)."""

    def __init__(self, client: Any, *, prefix: str = "ausculta:s2:") -> None:
        self._r = client
        self._prefix = prefix

    def _keys(self, session_id: str) -> tuple[str, str, str]:
        base = self._prefix + session_id
        return base, base + ":risks", base + ":history"

    @staticmethod
    def _ttl(state: SessionState) -> int:
        return max(1, int((state.expires_at - datetime.now(UTC)).total_seconds()))

    async def get(self, session_id: str) -> SessionState | None:
        main, risks, history = self._keys(session_id)
        try:
            pipe = self._r.pipeline(transaction=True)
            pipe.hgetall(main)
            pipe.smembers(risks)
            pipe.lrange(history, 0, -1)
            fields, members, turns = await pipe.execute()
        except RedisError as exc:
            raise DependencyUnavailable("session store unavailable") from exc
        return _decode(fields, members, turns)

    async def put(self, state: SessionState) -> None:
        main, risks, history = self._keys(state.session_id)
        ttl = self._ttl(state)
        meta = json.dumps(
            {
                "session_id": state.session_id,
                "locale": state.locale,
                "created_at": state.created_at.isoformat(),
                "expires_at": state.expires_at.isoformat(),
            }
        )
        try:
            pipe = self._r.pipeline(transaction=True)
            pipe.delete(main, risks, history)
            pipe.hset(
                main,
                mapping={
                    "meta": meta,
                    "turns_used": state.turns_used,
                    "strikes": state.strikes,
                    "locked": int(state.locked),
                },
            )
            if state.sticky_risks:
                pipe.sadd(risks, *sorted(k.value for k in state.sticky_risks))
            if state.history:
                pipe.rpush(history, *(t.model_dump_json() for t in state.history))
            for key in (main, risks, history):
                pipe.expire(key, ttl)
            await pipe.execute()
        except RedisError as exc:
            raise DependencyUnavailable("session store unavailable") from exc

    async def apply(self, state: SessionState, update: SessionUpdate) -> SessionState | None:
        main, risks, history = self._keys(state.session_id)
        try:
            pipe = self._r.pipeline(transaction=True)
            pipe.exists(main)
            if update.turn_text is not None:
                pipe.hincrby(main, "turns_used", 1)
                if update.window > 0:
                    pipe.rpush(history, HistoryTurn(role="user", text=update.turn_text).model_dump_json())
                    pipe.ltrim(history, -update.window, -1)
                else:
                    pipe.delete(history)
            if update.risks:
                pipe.sadd(risks, *sorted(k.value for k in update.risks))
            if update.strike:
                pipe.hincrby(main, "strikes", 1)
            for key in (main, risks, history):
                pipe.expire(key, self._ttl(state))
            results = await pipe.execute()
            if not results[0]:
                await self._r.delete(main, risks, history)  # the session had expired: drop the stray deltas
                return None
            if update.strike and int(results[_strike_index(update)]) >= update.strikes_to_lock:
                await self._r.hset(main, "locked", 1)  # monotonic: safe outside the transaction
        except RedisError as exc:
            raise DependencyUnavailable("session store unavailable") from exc
        return await self.get(state.session_id)

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:
            return False


def _strike_index(update: SessionUpdate) -> int:
    """Position of the strikes HINCRBY result in the apply() pipeline (after EXISTS)."""
    index = 1
    if update.turn_text is not None:
        index += 3 if update.window > 0 else 2
    if update.risks:
        index += 1
    return index


def _decode(fields: dict[Any, Any], members: set[Any], turns: list[Any]) -> SessionState | None:
    data = {_text(k): _text(v) for k, v in fields.items()}
    if "meta" not in data:
        return None
    meta = json.loads(data["meta"])
    return SessionState(
        session_id=str(meta["session_id"]),
        locale=meta["locale"],
        created_at=datetime.fromisoformat(meta["created_at"]),
        expires_at=datetime.fromisoformat(meta["expires_at"]),
        turns_used=int(data.get("turns_used", 0)),
        strikes=int(data.get("strikes", 0)),
        locked=data.get("locked", "0") not in ("0", ""),
        sticky_risks=frozenset(RiskKind(_text(m)) for m in members),
        history=tuple(HistoryTurn.model_validate_json(_text(t)) for t in turns),
    )
