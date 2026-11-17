"""Async engine / session factory. SQLite (aiosqlite) in dev and tests, Postgres (asyncpg) in prod.

Dev and tests create the schema directly (create_all); prod runs `alembic upgrade head`
(config: app/storage/alembic.ini, migrations: app/storage/migrations).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession as SASession

from app.storage.models import Base


def is_sqlite(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def make_engine(url: str) -> AsyncEngine:
    if is_sqlite(url):
        db = make_url(url).database
        if db and db != ":memory:":
            Path(db).parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(url, connect_args={"timeout": 15})
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
        return engine
    return create_async_engine(url, pool_size=10, max_overflow=10, pool_pre_ping=True)


def _sqlite_pragmas(dbapi_conn: object, _record: object) -> None:
    cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
    cur.execute("PRAGMA journal_mode=WAL")
    # WAL + NORMAL: no fsync per commit (a power cut may drop the last commits, never corrupts the file).
    # Dev/test only; production uses Postgres.
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def session_factory(engine: AsyncEngine) -> async_sessionmaker[SASession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ping(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


__all__ = ["Engine", "create_schema", "is_sqlite", "make_engine", "ping", "session_factory"]
