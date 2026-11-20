"""Fixtures for the P4 runner tests: the real ASGI app with the scripted fake LLM and the fake retriever."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from core.config import REPO_ROOT, Settings
from evals.fakes.fake_llm import FakeLLMProvider
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.scripted import scripted_provider
from evals.p4.harness import Harness, open_harness
from evals.p4.provider import HALT_ROLES, CountingProvider
from evals.p4.retrievers import HaltingRetriever, RecordingRetriever
from evals.p4.store import Store

TEST_SECRET = "p4-test-session-secret-0123456789abcdef-0123456789"  # secret-scan: allow
DEMO_PROFILE = REPO_ROOT / "config" / "hospital" / "demo.yaml"
TODAY = date(2026, 12, 1)


def fake_settings(root: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        AUSCULTA_LLM_BACKEND="fake",
        AUSCULTA_ENV="test",
        AUSCULTA_DATA_ROOT=root,
        DATABASE_URL=f"sqlite+aiosqlite:///{(root / 'p4.db').as_posix()}",
        REDIS_URL=None,
        AUSCULTA_SESSION_SECRET=SecretStr(TEST_SECRET),
        AUSCULTA_HOSPITAL_PROFILE=DEMO_PROFILE,
        GEMINI_API_KEY=None,
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "reports")


@pytest.fixture
def harness_factory(tmp_path: Path) -> Callable[..., Any]:
    @asynccontextmanager
    async def factory(
        llm: FakeLLMProvider | None = None,
        retriever: Any = None,
        *,
        stop_after_guard: bool = False,
        max_generate: int | None = None,
        max_decide: int | None = None,
    ) -> AsyncIterator[Harness]:
        counting = CountingProvider(
            llm or scripted_provider(),
            max_generate=max_generate,
            max_decide=max_decide,
            halt_roles=HALT_ROLES if stop_after_guard else frozenset(),
        )
        if retriever is None:
            retriever = HaltingRetriever() if stop_after_guard else RecordingRetriever(FakeRetriever())
        async with open_harness(
            fake_settings(tmp_path),
            counting,
            retriever,
            stop_after_guard=stop_after_guard,
            today=lambda: TODAY,
        ) as harness:
            yield harness

    return factory
