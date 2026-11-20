"""Review S6/P7 (retention purge of every table), S7 (request-code collision retry) and P15 (appointment and
its audit event in one transaction)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.pipeline.record import TurnRecord, TurnTrace
from app.pipeline.session import SessionState
from app.storage import repositories
from app.storage.db import create_schema, make_engine, session_factory
from app.storage.models import (
    AppointmentContactRow,
    AppointmentRequestRow,
    AuditEventRow,
    FeedbackRow,
    SessionRow,
    TurnRow,
)
from app.storage.repositories import RETENTION, AppointmentInput, Storage
from core.schemas.events import ReleaseInfo

RELEASE = ReleaseInfo(app_version="0.1.0", corpus_version="c1", prompt_hash="abc", models={"answer": "m1"})
NOW = datetime(2027, 6, 1, 12, 0, tzinfo=UTC)
DATA = AppointmentInput(
    session_id="s-appt",
    department_id="cardiology",
    full_name="Test Patient",
    phone="+33 1 00 00 00 99",
    email=None,
    preferred_dates="Monday",
    reason=None,
)


@pytest.fixture
async def storage(tmp_path: Path) -> AsyncIterator[Storage]:
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    await create_schema(engine)
    yield Storage.from_factory(session_factory(engine))
    await engine.dispose()


async def _count(storage: Storage, model) -> int:
    async with storage.appointments._s() as db:
        return int(await db.scalar(select(func.count()).select_from(model)) or 0)


async def _seed(storage: Storage, sid: str, at: datetime) -> None:
    state = SessionState(session_id=sid, locale="en", created_at=at, expires_at=at + timedelta(hours=2))
    await storage.sessions.create(state, demo_mode=True)
    record = TurnRecord(f"t-{sid}", sid, f"c-{sid}", RELEASE, started_at=at)
    trace = TurnTrace(record)
    trace.audit("safety_template", kind="emergency")
    await storage.turns.save(trace.finish("completed"))
    await storage.feedback.add(session_id=sid, turn_id=f"t-{sid}", rating="up", reason=None, comment=None)
    async with storage.appointments._s.begin() as db:  # back-date the feedback row
        row = (await db.scalars(select(FeedbackRow).where(FeedbackRow.session_id == sid))).one()
        row.created_at = at
    await storage.appointments.create(DATA, now=at)


def test_retention_policy_covers_every_table() -> None:
    assert set(RETENTION) == {"appointments", "sessions", "turns", "audit_events", "feedback"}
    assert RETENTION["appointments"] == timedelta(days=30)
    assert all(v >= timedelta(days=30) for v in RETENTION.values())


async def test_purge_expired_applies_each_retention(storage: Storage) -> None:
    old = NOW - max(RETENTION.values()) - timedelta(days=1)
    recent = NOW - timedelta(days=1)
    await _seed(storage, "old", old)
    await _seed(storage, "new", recent)
    result = await storage.purge_expired(NOW)
    assert result == {
        "appointment_contacts": 1,
        "appointment_requests": 1,
        "turns": 1,
        "sessions": 1,
        "audit_events": 1,
        "feedback": 1,
    }
    for model in (
        SessionRow,
        TurnRow,
        AuditEventRow,
        FeedbackRow,
        AppointmentRequestRow,
        AppointmentContactRow,
    ):
        assert await _count(storage, model) == 1, model.__name__
    assert await storage.purge_expired(NOW) == dict.fromkeys(result, 0), "idempotent"


async def test_appointment_and_its_audit_event_commit_together(storage: Storage) -> None:
    code = await storage.appointments.create(DATA, now=NOW, audit={"department": "cardiology"})
    async with storage.appointments._s() as db:
        audit = (await db.scalars(select(AuditEventRow))).one()
    assert (audit.event_type, audit.session_id, audit.detail) == (
        "appointment_request",
        "s-appt",
        {"department": "cardiology"},
    )
    assert code.startswith("AR-")


async def test_audit_failure_rolls_back_the_appointment(storage: Storage) -> None:
    with pytest.raises(Exception):  # noqa: B017 - JSON serialisation error inside the transaction
        await storage.appointments.create(DATA, now=NOW, audit={"bad": object()})
    assert await _count(storage, AppointmentRequestRow) == 0
    assert await _count(storage, AppointmentContactRow) == 0
    assert await _count(storage, AuditEventRow) == 0


async def test_request_code_collision_is_retried(storage: Storage, monkeypatch) -> None:
    codes = iter(["AR-AAAAAA", "AR-AAAAAA", "AR-AAAAAA", "AR-CCCCCC"])
    monkeypatch.setattr(repositories, "new_request_code", lambda: next(codes))
    assert await storage.appointments.create(DATA, now=NOW) == "AR-AAAAAA"
    assert await storage.appointments.create(DATA, now=NOW) == "AR-CCCCCC"


async def test_request_code_collisions_give_up_after_a_few_attempts(storage: Storage, monkeypatch) -> None:
    monkeypatch.setattr(repositories, "new_request_code", lambda: "AR-AAAAAA")
    await storage.appointments.create(DATA, now=NOW)
    with pytest.raises(IntegrityError):
        await storage.appointments.create(DATA, now=NOW)
    assert await _count(storage, AppointmentRequestRow) == 1
