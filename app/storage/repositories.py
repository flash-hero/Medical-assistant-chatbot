"""Repositories over the async session factory. Every write is its own short transaction.

Retention (review S6/P7): `Storage.purge_expired()` deletes every row older than its table's retention and is
idempotent; the API runs it at startup and then hourly. Appointment personal data keeps the contract's 30 days
(`purge_after`); the other periods are engineering defaults to be confirmed by the DPIA (docs/runbook.md)."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.pipeline.record import TurnRecord
from app.pipeline.session import SessionState
from app.storage.models import (
    AppointmentContactRow,
    AppointmentRequestRow,
    AuditEventRow,
    FeedbackRow,
    SessionRow,
    TurnRow,
)

log = structlog.get_logger(__name__)
APPOINTMENT_RETENTION = timedelta(days=30)
RETENTION: Mapping[str, timedelta] = MappingProxyType(
    {
        "appointments": APPOINTMENT_RETENTION,
        "sessions": timedelta(days=90),  # == turns: deleting a session cascades to its turns
        "turns": timedelta(days=90),
        "feedback": timedelta(days=180),
        "audit_events": timedelta(days=365),
    }
)
CODE_ATTEMPTS = 5  # request-code collisions (32^6 codes) are retried with a fresh code
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def new_request_code() -> str:
    return "AR-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


@dataclass(frozen=True)
class AppointmentInput:
    session_id: str
    department_id: str
    full_name: str
    phone: str
    email: str | None
    preferred_dates: str
    reason: str | None


@dataclass(frozen=True)
class PurgeResult:
    contacts: int
    requests: int


class SessionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._s = sessions

    async def create(self, state: SessionState, *, demo_mode: bool) -> None:
        async with self._s.begin() as db:
            db.add(
                SessionRow(
                    id=state.session_id,
                    created_at=state.created_at,
                    expires_at=state.expires_at,
                    locale=state.locale,
                    demo_mode=demo_mode,
                )
            )

    async def update_counters(self, state: SessionState) -> None:
        async with self._s.begin() as db:
            await db.execute(
                update(SessionRow)
                .where(SessionRow.id == state.session_id)
                .values(turns_used=state.turns_used, strikes=state.strikes, locked=state.locked)
            )


class TurnRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._s = sessions

    async def save(self, r: TurnRecord) -> None:
        """Insert the turn metadata and its audit events (one transaction)."""
        async with self._s.begin() as db:
            db.add(
                TurnRow(
                    id=r.turn_id,
                    session_id=r.session_id,
                    client_turn_id=r.client_turn_id,
                    created_at=r.started_at,
                    status=r.status,
                    intent=r.intent,
                    language=r.language,
                    risk_kinds=list(r.risk_kinds),
                    mode=r.mode,
                    classifier=r.classifier,
                    verified=r.verified,
                    degraded=list(r.degraded),
                    latencies_ms=dict(r.latencies_ms),
                    total_ms=r.latencies_ms.get("total"),
                    redactions=r.redactions,
                    error_code=r.error_code,
                    app_version=r.release.app_version,
                    corpus_version=r.release.corpus_version,
                    prompt_hash=r.release.prompt_hash,
                    models=dict(r.release.models),
                )
            )
            for a in r.audit:
                db.add(
                    AuditEventRow(
                        created_at=r.started_at,
                        session_id=r.session_id,
                        turn_id=r.turn_id,
                        event_type=a.event_type,
                        detail=dict(a.detail),
                    )
                )

    async def belongs_to(self, turn_id: str, session_id: str) -> bool:
        async with self._s() as db:
            row = await db.scalar(
                select(TurnRow.id).where(TurnRow.id == turn_id, TurnRow.session_id == session_id)
            )
            return row is not None


class AuditRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._s = sessions

    async def add(self, event_type: str, *, session_id: str | None = None, **detail: object) -> None:
        async with self._s.begin() as db:
            db.add(
                AuditEventRow(
                    created_at=datetime.now(UTC), session_id=session_id, event_type=event_type, detail=detail
                )
            )

    async def count(self, event_type: str) -> int:
        async with self._s() as db:
            rows = await db.scalars(select(AuditEventRow.id).where(AuditEventRow.event_type == event_type))
            return len(rows.all())


async def _delete_older(db: AsyncSession, model: Any, column: Any, cutoff: datetime) -> int:
    result = await db.execute(delete(model).where(column < cutoff))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


class FeedbackRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._s = sessions

    async def add(
        self, *, session_id: str, turn_id: str, rating: str, reason: str | None, comment: str | None
    ) -> None:
        async with self._s.begin() as db:
            db.add(
                FeedbackRow(
                    created_at=datetime.now(UTC),
                    session_id=session_id,
                    turn_id=turn_id,
                    rating=rating,
                    reason=reason,
                    comment=comment,
                )
            )


class AppointmentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._s = sessions

    async def create(
        self,
        data: AppointmentInput,
        *,
        now: datetime | None = None,
        audit: Mapping[str, object] | None = None,
    ) -> str:
        """Store the request and (when `audit` is given) its audit event in ONE transaction (review P15).
        A request-code collision is retried with a fresh code (review S7); after CODE_ATTEMPTS it raises."""
        now = now or datetime.now(UTC)
        for attempt in range(1, CODE_ATTEMPTS + 1):
            code = new_request_code()
            try:
                await self._insert(code, data, now, audit)
            except IntegrityError:
                if attempt == CODE_ATTEMPTS:
                    raise
                log.warning("appointment_code_collision", attempt=attempt)
                continue
            return code
        raise AssertionError("unreachable")  # pragma: no cover

    async def _insert(
        self, code: str, data: AppointmentInput, now: datetime, audit: Mapping[str, object] | None
    ) -> None:
        purge = now + APPOINTMENT_RETENTION
        async with self._s.begin() as db:
            db.add(
                AppointmentRequestRow(
                    id=code,
                    created_at=now,
                    session_id=data.session_id,
                    department_id=data.department_id,
                    purge_after=purge,
                )
            )
            await db.flush()
            db.add(
                AppointmentContactRow(
                    request_id=code,
                    full_name=data.full_name,
                    phone=data.phone,
                    email=data.email,
                    preferred_dates=data.preferred_dates,
                    reason=data.reason,
                    purge_after=purge,
                )
            )
            if audit is not None:
                db.add(
                    AuditEventRow(
                        created_at=now,
                        session_id=data.session_id,
                        event_type="appointment_request",
                        detail=dict(audit),
                    )
                )

    async def purge_expired(self, now: datetime | None = None) -> PurgeResult:
        """Delete appointment personal data (and the request rows) past their 30-day retention."""
        now = now or datetime.now(UTC)
        async with self._s.begin() as db:
            contacts = await db.execute(
                delete(AppointmentContactRow).where(AppointmentContactRow.purge_after <= now)
            )
            requests = await db.execute(
                delete(AppointmentRequestRow).where(AppointmentRequestRow.purge_after <= now)
            )
        return PurgeResult(contacts=contacts.rowcount or 0, requests=requests.rowcount or 0)  # type: ignore[attr-defined]

    async def count(self) -> tuple[int, int]:
        async with self._s() as db:
            reqs = len((await db.scalars(select(AppointmentRequestRow.id))).all())
            contacts = len((await db.scalars(select(AppointmentContactRow.request_id))).all())
            return reqs, contacts


@dataclass(frozen=True)
class Storage:
    sessions: SessionRepository
    turns: TurnRepository
    audit: AuditRepository
    feedback: FeedbackRepository
    appointments: AppointmentRepository

    async def purge_expired(self, now: datetime | None = None) -> dict[str, int]:
        """Delete every row past its retention (RETENTION). Idempotent; safe to run from several workers."""
        now = now or datetime.now(UTC)
        appointments = await self.appointments.purge_expired(now)
        counts = {"appointment_contacts": appointments.contacts, "appointment_requests": appointments.requests}
        async with self.appointments._s.begin() as db:
            counts["turns"] = await _delete_older(db, TurnRow, TurnRow.created_at, now - RETENTION["turns"])
            counts["sessions"] = await _delete_older(
                db, SessionRow, SessionRow.created_at, now - RETENTION["sessions"]
            )
            counts["audit_events"] = await _delete_older(
                db, AuditEventRow, AuditEventRow.created_at, now - RETENTION["audit_events"]
            )
            counts["feedback"] = await _delete_older(
                db, FeedbackRow, FeedbackRow.created_at, now - RETENTION["feedback"]
            )
        return counts

    @classmethod
    def from_factory(cls, factory: async_sessionmaker[AsyncSession]) -> Storage:
        return cls(
            sessions=SessionRepository(factory),
            turns=TurnRepository(factory),
            audit=AuditRepository(factory),
            feedback=FeedbackRepository(factory),
            appointments=AppointmentRepository(factory),
        )
