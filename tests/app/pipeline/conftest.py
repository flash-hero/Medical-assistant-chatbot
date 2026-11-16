"""Fixtures that run whole turns through TurnEngine with the scripted fake LLM and the fake retriever."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.guardrails.ingress import process_ingress
from app.pipeline.engine import TurnEngine, TurnRequest
from app.pipeline.factory import build_engine
from app.pipeline.record import TurnRecord, TurnTrace
from app.pipeline.session import MemorySessionStore, SessionState
from core.config import Settings
from core.schemas.events import ChatEvent
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.scripted import scripted_provider


@dataclass
class TurnOutcome:
    events: list[ChatEvent]
    record: TurnRecord
    session: SessionState | None

    @property
    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def first(self, kind: str) -> Any:
        return next(e for e in self.events if e.type == kind)

    def all(self, kind: str) -> list[Any]:
        return [e for e in self.events if e.type == kind]


@dataclass
class Harness:
    engine: TurnEngine
    sessions: MemorySessionStore
    llm: Any
    retriever: Any
    settings: Settings
    today: date

    async def new_session(self, locale: str = "en") -> SessionState:
        now = datetime.now(UTC)
        state = SessionState(
            session_id=str(uuid.uuid4()),
            locale=locale,
            created_at=now,
            expires_at=now + timedelta(hours=2),  # type: ignore[arg-type]
        )
        await self.sessions.put(state)
        return state

    async def turn(
        self, message: str, *, locale: str = "en", session: SessionState | None = None
    ) -> TurnOutcome:
        session = session or await self.new_session(locale)
        stored = await self.sessions.get(session.session_id) or session
        ingress = process_ingress(message, max_chars=self.settings.max_message_chars, today=self.today)
        turn_id = str(uuid.uuid4())
        req = TurnRequest(
            turn_id=turn_id,
            client_turn_id=str(uuid.uuid4()),
            session=stored,
            message=ingress,
            locale=locale,  # type: ignore[arg-type]
            precheck=self.engine.precheck(ingress),
        )
        trace = TurnTrace(
            TurnRecord(
                turn_id=turn_id,
                session_id=stored.session_id,
                client_turn_id=req.client_turn_id,
                release=self.engine.release,
            )
        )
        events = [ev async for ev in self.engine.run(req, trace)]
        return TurnOutcome(events, trace.finish("completed"), await self.sessions.get(stored.session_id))


@pytest.fixture
def harness_factory(engine_config: Any, settings: Settings, today: date) -> Callable[..., Harness]:
    def factory(
        llm: Any = None,
        retriever: Any = "default",
        settings_override: Settings | None = None,
        config: Any = None,
    ) -> Harness:
        llm = llm or scripted_provider()
        retriever = FakeRetriever() if retriever == "default" else retriever
        sessions = MemorySessionStore()
        cfg = settings_override or settings
        engine = build_engine(
            config or engine_config,
            llm=llm,
            retriever=retriever,
            sessions=sessions,
            settings=cfg,
            today=lambda: today,
        )
        return Harness(engine, sessions, llm, retriever, cfg, today)

    return factory


@pytest.fixture
def harness(harness_factory: Callable[..., Harness]) -> Harness:
    return harness_factory()


TurnFn = Callable[..., Awaitable[TurnOutcome]]
