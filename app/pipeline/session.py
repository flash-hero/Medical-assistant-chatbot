"""Per-session conversation state: turn count, strikes, lock, sticky risk flags and the last few REDACTED user
turns (needed for the router context and query rewriting). Kept in memory (dev) or Redis (prod) with the session
lifetime as TTL; never written to the relational database (no transcript text is persisted).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from core.schemas.chat import HistoryTurn, Locale, RiskKind

SESSION_TTL_S = 2 * 60 * 60


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

    async def ping(self) -> bool: ...


class MemorySessionStore:
    """In-process store with TTL and a size bound (dev / tests / single-instance deployments)."""

    def __init__(self, *, max_sessions: int = 50_000, clock: Callable[[], float] = time.monotonic) -> None:
        self._data: OrderedDict[str, tuple[float, SessionState]] = OrderedDict()
        self._max = max_sessions
        self._clock = clock
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> SessionState | None:
        async with self._lock:
            item = self._data.get(session_id)
            if item is None:
                return None
            deadline, state = item
            if self._clock() > deadline or state.expires_at <= datetime.now(UTC):
                del self._data[session_id]
                return None
            return state

    async def put(self, state: SessionState) -> None:
        async with self._lock:
            self._data[state.session_id] = (self._clock() + SESSION_TTL_S, state)
            self._data.move_to_end(state.session_id)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    async def ping(self) -> bool:
        return True


class RedisSessionStore:
    """Redis-backed store for multi-instance deployments (tested against a real Redis in CI)."""

    def __init__(self, client: Any, *, prefix: str = "ausculta:session:") -> None:
        self._r = client
        self._prefix = prefix

    async def get(self, session_id: str) -> SessionState | None:
        raw = await self._r.get(self._prefix + session_id)
        if raw is None:
            return None
        return SessionState.from_json(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))

    async def put(self, state: SessionState) -> None:
        ttl = max(1, int((state.expires_at - datetime.now(UTC)).total_seconds()))
        await self._r.set(self._prefix + state.session_id, state.to_json(), ex=ttl)

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:  # noqa: BLE001 - readiness probes report, never raise
            return False
