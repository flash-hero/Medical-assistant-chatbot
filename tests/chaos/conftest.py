"""Chaos-test fixtures: the real app (create_app) with injectable failing dependencies.

No autouse fixtures. `chaos_app(...)` is an async context manager yielding a ChaosApp with helpers to open a
session and run one chat turn (SSE parsed and contract-checked by the caller).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from chaos_support import CANARY, DEMO_PROFILE, ChaosApp, chaos_settings

from app.api.container import Overrides
from app.main import create_app
from app.pipeline.factory import load_engine_config
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.scripted import scripted_provider


@pytest.fixture(scope="session")
def chaos_config() -> Any:
    return load_engine_config(DEMO_PROFILE, canary=CANARY)


@pytest.fixture
def chaos_app(tmp_path: Path, chaos_config: Any) -> Callable[..., Any]:
    @asynccontextmanager
    async def factory(
        *, llm: Any = None, retriever: Any = "default", redis_client: Any = None, **env: Any
    ) -> AsyncIterator[ChaosApp]:
        overrides = Overrides(
            llm=llm or scripted_provider(),
            retriever=FakeRetriever() if isinstance(retriever, str) else retriever,
            engine_config=chaos_config,
            redis_client=redis_client,
            turn_deadline_s=env.pop("turn_deadline_s", None),
        )
        app = create_app(chaos_settings(tmp_path, **env), overrides=overrides)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, client=("203.0.113.50", 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=60) as http:
                yield ChaosApp(app, app.state.container, http)

    return factory
