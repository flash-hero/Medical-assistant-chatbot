"""Repositories over the async session factory. Every write is its own short transaction."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
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

APPOINTMENT_RETENTION = timedelta(days=30)
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
            row = await db.scalar(select(TurnRow.id).where(TurnRow.id == turn_id, TurnRow.session_id == session_id))
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


class FeedbackRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._s = sessions

    async def add(self, *, session_id: str, turn_id: str, rating: str, reason: str | None, comment: str | None) -> None:
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

    async def create(self, data: AppointmentInput, *, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        purge = now + APPOINTMENT_RETENTION
        code = new_request_code()
        async with self._s.begin() as db:
            db.add(
                AppointmentRequestRow(
                    id=code, created_at=now, session_id=data.session_id, department_id=data.department_id, purge_after=purge
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
        return code

    async def purge_expired(self, now: datetime | None = None) -> PurgeResult:
        """Delete appointment personal data (and the request rows) past their 30-day retention."""
        now = now or datetime.now(UTC)
        async with self._s.begin() as db:
            contacts = await db.execute(delete(AppointmentContactRow).where(AppointmentContactRow.purge_after <= now))
            requests = await db.execute(delete(AppointmentRequestRow).where(AppointmentRequestRow.purge_after <= now))
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

    @classmethod
    def from_factory(cls, factory: async_sessionmaker[AsyncSession]) -> Storage:
        return cls(
            sessions=SessionRepository(factory),
            turns=TurnRepository(factory),
            audit=AuditRepository(factory),
            feedback=FeedbackRepository(factory),
            appointments=AppointmentRepository(factory),
        )
