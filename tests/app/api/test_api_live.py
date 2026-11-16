"""Live smoke test of the whole API against the real Gemini API (free tier, synthetic text only).

  pytest -m live tests/app/api/test_api_live.py

At most 6 model calls in total (enforced by CallBudget; retries disabled so one logical call = one HTTP call):
one medical question through the real retriever when the Qdrant alias exists (else the fake retriever) and
one emergency message (0 model calls by design). Skips, never fails, on HTTP 429.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.api.container import Overrides
from app.main import create_app
from core.config import Settings
from core.errors import UpstreamRateLimited, UpstreamUnavailable
from core.models import ModelRole
from core.ports import (
    DecisionQuestion,
    DecisionResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    LLMProvider,
)
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.sse_contract import order_violations, parse_sse

pytestmark = pytest.mark.live
MAX_MODEL_CALLS = 6
MEDICAL_QUESTION = "What is angina and when should I see a doctor about chest discomfort?"
EMERGENCY = "my dad collapsed and he is not breathing"


@dataclass
class CallBudget:
    """Wraps an LLMProvider: counts calls, refuses (UpstreamUnavailable) past `limit`, records 429s."""

    inner: LLMProvider
    limit: int = MAX_MODEL_CALLS
    calls: list[str] = field(default_factory=list)
    rate_limited: list[UpstreamRateLimited] = field(default_factory=list)

    def _spend(self, what: str) -> None:
        if len(self.calls) >= self.limit:
            raise UpstreamUnavailable(f"live smoke budget of {self.limit} model calls used")
        self.calls.append(what)

    async def _guard(self, coro: Any) -> Any:
        try:
            return await coro
        except UpstreamRateLimited as exc:
            self.rate_limited.append(exc)
            raise

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._spend(f"generate:{request.role.value}")
        return await self._guard(self.inner.generate(request))  # type: ignore[no-any-return]

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        self._spend(f"stream:{request.role.value}")
        try:
            async with aclosing(self.inner.stream(request)) as chunks:  # type: ignore[type-var]
                async for chunk in chunks:
                    yield chunk
        except UpstreamRateLimited as exc:
            self.rate_limited.append(exc)
            raise

    async def decide(
        self, role: ModelRole, input_text: str, questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        self._spend(f"decide:{role.value}")
        return await self._guard(self.inner.decide(role, input_text, questions))  # type: ignore[no-any-return]

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        self._spend(f"embed:{len(texts)}")
        return await self._guard(self.inner.embed(texts, dim=dim))  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        closer = getattr(self.inner, "aclose", None)
        if closer is not None:
            await closer()


def _live_settings(tmp_path: Path) -> Settings:
    settings = Settings(  # reads GEMINI_API_KEY from .env; everything stateful goes to tmp_path
        AUSCULTA_ENV="test",
        AUSCULTA_LLM_BACKEND="gemini",
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'live.db').as_posix()}",
        AUSCULTA_SESSION_SECRET=SecretStr(secrets.token_urlsafe(48)),
        REDIS_URL=None,
        AUSCULTA_KILL_SWITCH=False,
    )
    if settings.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY not configured")
    return settings


async def _alias_exists(settings: Settings) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{settings.qdrant_url}/aliases")
        aliases = {a["alias_name"] for a in r.json()["result"]["aliases"]}
    except (httpx.HTTPError, KeyError, ValueError):
        return False
    return settings.qdrant_alias in aliases


async def _build(settings: Settings) -> tuple[CallBudget, Any, str]:
    from app.llm.gemini_provider import GeminiProvider
    from app.llm.retry import RetryPolicy

    llm = CallBudget(GeminiProvider(settings, policy=RetryPolicy(attempts=1)))
    if await _alias_exists(settings):
        from rag.retrieval import build_retriever

        return llm, build_retriever(settings, llm), "real"
    return llm, FakeRetriever(), "fake"


async def _chat(client: httpx.AsyncClient, token: str, message: str) -> list[Any]:
    r = await client.post(
        "/api/v1/chat",
        json={"message": message, "locale": "en", "client_turn_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    events = parse_sse(r.text)
    assert order_violations(events) == [], [e.type for e in events]
    return events


def _skip_if_rate_limited(llm: CallBudget) -> None:
    if llm.rate_limited:
        scope = llm.rate_limited[0].scope
        pytest.skip(f"Gemini API rate limited (scope={scope}); live smoke not run")


def _record_summary(node: pytest.Item, kind: str, medical: list[Any], llm: CallBudget) -> None:
    """Observations for the junit report (`--junitxml`), so a run can be documented without re-running it.
    Appends to user_properties directly: the record_property fixture warns under the default xunit2 family."""
    answer = next((e for e in medical if e.type == "answer"), None)
    meta = next((e for e in medical if e.type == "meta"), None)
    node.user_properties.extend(
        [
            ("retriever", kind),
            ("medical_events", ",".join(e.type for e in medical)),
            ("answer_mode", answer.mode if answer else "none"),
            ("citations", len(answer.citations) if answer else 0),
            ("corpus_version", meta.release.corpus_version if meta else "none"),
            ("model_calls", ",".join(llm.calls)),
        ]
    )


async def test_live_medical_question_and_emergency(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    settings = _live_settings(tmp_path)
    llm, retriever, kind = await _build(settings)
    app = create_app(settings, overrides=Overrides(llm=llm, retriever=retriever))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://live") as client:
            session = await client.post("/api/v1/session", json={"locale": "en"})
            token = session.json()["session_token"]
            medical = await _chat(client, token, MEDICAL_QUESTION)
            _skip_if_rate_limited(llm)
            calls_before = len(llm.calls)
            emergency = await _chat(client, token, EMERGENCY)
    _record_summary(request.node, kind, medical, llm)
    assert len(llm.calls) <= MAX_MODEL_CALLS, llm.calls
    assert len(llm.calls) == calls_before, "the emergency turn must not call any model"
    answer = next(e for e in medical if e.type == "answer")
    assert answer.mode in ("streamed", "verified", "abstain"), (kind, answer.mode, llm.calls)
    if answer.mode != "abstain":
        assert answer.citations, "a released medical answer always carries citations"
        assert all(f"[{c.n}]" in answer.text for c in answer.citations)
    if kind == "real":
        meta = next(e for e in medical if e.type == "meta")
        assert meta.release.corpus_version != "none"
    types = [e.type for e in emergency]
    assert types[:2] == ["meta", "safety"]
    assert next(e for e in emergency if e.type == "safety").kind == "emergency"
