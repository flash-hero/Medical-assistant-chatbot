"""Fixtures that drive the real ASGI app (create_app) in-process through httpx.ASGITransport."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
import pytest

from app.api.container import Container, Overrides
from app.main import create_app
from core.config import Settings
from core.schemas.events import ChatEvent
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.scripted import scripted_provider
from evals.fakes.sse_contract import order_violations, parse_sse

FAST_LIMITS = {"AUSCULTA_RATE_IP_MIN": 100_000, "AUSCULTA_RATE_SESSION_MIN": 100_000}


@dataclass
class ChatResult:
    response: httpx.Response
    events: list[ChatEvent]

    @property
    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def first(self, kind: str) -> Any:
        return next(e for e in self.events if e.type == kind)

    def assert_contract(self) -> None:
        assert self.response.status_code == 200, self.response.text
        assert order_violations(self.events) == [], self.types


@dataclass
class Api:
    client: httpx.AsyncClient
    app: Any
    container: Container
    llm: Any
    retriever: Any

    async def session(self, locale: str = "en") -> dict[str, Any]:
        r = await self.client.post("/api/v1/session", json={"locale": locale})
        assert r.status_code == 201, r.text
        return r.json()  # type: ignore[no-any-return]

    async def token(self, locale: str = "en") -> str:
        return str((await self.session(locale))["session_token"])

    async def chat(
        self, token: str, message: str, *, locale: str = "en", client_turn_id: str | None = None
    ) -> ChatResult:
        r = await self.client.post(
            "/api/v1/chat",
            json={
                "message": message,
                "locale": locale,
                "client_turn_id": client_turn_id or str(uuid.uuid4()),
            },
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        events = parse_sse(r.text) if r.status_code == 200 else []
        return ChatResult(r, events)


@pytest.fixture
def api_factory(
    engine_config: Any, settings_factory: Callable[..., Settings], today: date
) -> Callable[..., Any]:
    """Async context factory: `async with api_factory(llm=..., **env) as api: ...`."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory(
        llm: Any = None,
        retriever: Any = "default",
        keepalive_s: float = 15.0,
        config: Any = None,
        cancel_grace_s: float = 1.0,
        **env: Any,
    ) -> AsyncIterator[Api]:
        llm = llm or scripted_provider()
        retriever = FakeRetriever() if isinstance(retriever, str) and retriever == "default" else retriever
        settings = settings_factory(**{**FAST_LIMITS, **env})
        overrides = Overrides(
            llm=llm,
            retriever=retriever,
            engine_config=config or engine_config,
            keepalive_s=keepalive_s,
            cancel_grace_s=cancel_grace_s,
            today=lambda: today,
        )
        app = create_app(settings, overrides=overrides)
        container: Container = app.state.container
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield Api(client, app, container, llm, retriever)

    return factory


@pytest.fixture
async def api(api_factory: Callable[..., Any]) -> AsyncIterator[Api]:
    async with api_factory() as a:
        yield a
