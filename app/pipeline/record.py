"""Turn metadata and audit entries produced by the engine and persisted by the API layer. NO message text."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal

from core.schemas.events import ReleaseInfo

TurnStatus = Literal["running", "completed", "cancelled", "error"]
DetailValue = str | int | float | bool


@dataclass(frozen=True)
class AuditEntry:
    event_type: (
        str  # safety_template | refusal | strike | session_locked | upstream_blocked | output_violation ...
    )
    detail: Mapping[str, DetailValue] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    session_id: str
    client_turn_id: str
    release: ReleaseInfo
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: TurnStatus = "running"
    intent: str | None = None
    language: str | None = None
    risk_kinds: tuple[str, ...] = ()
    mode: str | None = None
    classifier: str = "none"
    verified: bool = False
    degraded: tuple[str, ...] = ()
    latencies_ms: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    redactions: int = 0
    audit: tuple[AuditEntry, ...] = ()
    error_code: str | None = None


class TurnTrace:
    """Holds the evolving (immutable) TurnRecord of one turn; owned by the task that runs the turn."""

    def __init__(self, record: TurnRecord) -> None:
        self._record = record
        self._t0 = time.perf_counter()

    @property
    def record(self) -> TurnRecord:
        return self._record

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000

    def update(self, **changes: object) -> None:
        self._record = replace(self._record, **changes)  # type: ignore[arg-type]

    def mark(self, name: str) -> None:
        if name not in self._record.latencies_ms:
            lat = {**self._record.latencies_ms, name: round(self.elapsed_ms(), 2)}
            self._record = replace(self._record, latencies_ms=MappingProxyType(lat))

    def audit(self, event_type: str, **detail: DetailValue) -> None:
        entry = AuditEntry(event_type=event_type, detail=MappingProxyType(dict(detail)))
        self._record = replace(self._record, audit=(*self._record.audit, entry))

    def degrade(self, reason: str) -> None:
        if reason not in self._record.degraded:
            self._record = replace(self._record, degraded=(*self._record.degraded, reason))

    def finish(self, status: TurnStatus, error_code: str | None = None) -> TurnRecord:
        self.mark("total")
        self._record = replace(self._record, status=status, error_code=error_code or self._record.error_code)
        return self._record
