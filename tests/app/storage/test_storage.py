"""Storage: engine factory, repositories (no message text anywhere), retention purge, Alembic migration."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.pipeline.record import TurnRecord, TurnTrace
from app.pipeline.session import SessionState
from app.storage.db import create_schema, is_sqlite, make_engine, ping, session_factory
from app.storage.models import Base
from app.storage.repositories import AppointmentInput, Storage, new_request_code
from core.schemas.events import ReleaseInfo

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "app" / "storage" / "alembic.ini"
RELEASE = ReleaseInfo(app_version="0.1.0", corpus_version="c1", prompt_hash="abc", models={"answer": "m1"})


@pytest.fixture
async def storage(tmp_path: Path) -> AsyncIterator[Storage]:
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'sub' / 'db.sqlite').as_posix()}")
    await create_schema(engine)
    yield Storage.from_factory(session_factory(engine))
    await engine.dispose()


def _session(sid: str = "11111111-1111-1111-1111-111111111111") -> SessionState:
    now = datetime.now(UTC)
    return SessionState(session_id=sid, locale="fr", created_at=now, expires_at=now + timedelta(hours=2))


def test_is_sqlite() -> None:
    assert is_sqlite("sqlite+aiosqlite:///x.db")
    assert not is_sqlite("postgresql+asyncpg://u@h/db")


async def test_ping_and_memory_database(tmp_path: Path) -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    assert await ping(engine) is True
    await engine.dispose()
    broken = make_engine(f"sqlite+aiosqlite:///{tmp_path.as_posix()}")  # a directory, not a database file
    assert await ping(broken) is False
    await broken.dispose()
    pg = make_engine("postgresql+asyncpg://nobody@127.0.0.1:1/none")  # pooled engine; never connected here
    assert pg.pool.size() == 10  # type: ignore[attr-defined]
    await pg.dispose()


def test_alembic_offline_sql(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    command.upgrade(
        _alembic_config(f"sqlite+aiosqlite:///{(tmp_path / 'o.db').as_posix()}"), "head", sql=True
    )
    out = capsys.readouterr().out
    assert "CREATE TABLE appointment_contacts" in out


async def test_session_and_turn_rows(storage: Storage) -> None:
    state = _session()
    await storage.sessions.create(state, demo_mode=True)
    await storage.sessions.update_counters(state.with_turn("x", window=3).with_strike(1))
    trace = TurnTrace(TurnRecord("t1", state.session_id, "c1", RELEASE))
    trace.update(intent="medical_info", language="fr", risk_kinds=("emergency",), mode="template")
    trace.audit("safety_template", kind="emergency", template_id="emergency.v1")
    trace.degrade("busy")
    await storage.turns.save(trace.finish("completed"))
    assert await storage.turns.belongs_to("t1", state.session_id) is True
    assert await storage.turns.belongs_to("t1", "other") is False
    assert await storage.audit.count("safety_template") == 1
    await storage.audit.add("kill_switch", reason="test")
    assert await storage.audit.count("kill_switch") == 1


async def test_feedback_row(storage: Storage) -> None:
    await storage.feedback.add(session_id="s", turn_id="t", rating="down", reason="unsafe", comment="[EMAIL]")


async def test_appointments_are_purged_after_retention(storage: Storage) -> None:
    long_ago = datetime.now(UTC) - timedelta(days=31)
    data = AppointmentInput(
        "s", "cardiology", "Test Person", "+212 600 000 000", None, "Monday morning", None
    )
    old = await storage.appointments.create(data, now=long_ago)
    fresh = await storage.appointments.create(data)
    assert old != fresh
    assert old.startswith("AR-")
    assert len(old) == 9
    assert await storage.appointments.count() == (2, 2)
    result = await storage.appointments.purge_expired()
    assert (result.contacts, result.requests) == (1, 1)
    assert await storage.appointments.count() == (1, 1)


def test_request_codes_avoid_ambiguous_characters() -> None:
    codes = {new_request_code() for _ in range(200)}
    assert len(codes) > 190
    assert not any(c in code[3:] for code in codes for c in "01IO")


def test_no_column_can_hold_message_text() -> None:
    columns = {c.name for t in Base.metadata.tables.values() for c in t.columns}
    assert not columns & {"message", "text", "answer", "prompt", "content", "transcript"}


def _alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.cmd_opts = argparse.Namespace(x=[f"url={url}"])
    return cfg


def test_alembic_upgrade_matches_the_models(tmp_path: Path) -> None:
    db = (tmp_path / "migrated.db").as_posix()
    command.upgrade(_alembic_config(f"sqlite+aiosqlite:///{db}"), "head")
    sync = create_engine(f"sqlite:///{db}")
    try:
        with sync.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
            tables = set(inspect(conn).get_table_names())
    finally:
        sync.dispose()
    assert diff == []
    assert set(Base.metadata.tables) <= tables


def test_alembic_downgrade_to_base(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'd.db').as_posix()}"
    command.upgrade(_alembic_config(url), "head")
    command.downgrade(_alembic_config(url), "base")
    sync = create_engine(f"sqlite:///{(tmp_path / 'd.db').as_posix()}")
    try:
        with sync.connect() as conn:
            assert set(inspect(conn).get_table_names()) <= {"alembic_version"}
    finally:
        sync.dispose()


def test_event_loop_is_not_left_running() -> None:
    with pytest.raises(RuntimeError):
        asyncio.get_running_loop()
