"""Chaos: the model provider misbehaves, through the REAL GeminiProvider (fake SDK client, no network).

429 storm: every generate / stream / decide call returns HTTP 429. Expected: every turn ends with the fixed
"busy" answer (emergency number included), nothing hangs, no admission slot leaks, and every spend
reservation is settled (nothing billed). Emergency turns never touch the model.
Provider safety block: the guard input, the answer stream or the prompt is blocked. Expected: the
refusal_blocked template with the emergency and crisis numbers, a valid SSE stream, no crash.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from chaos_support import EMERGENCY, FEVER, ChaosApp, Turn

from app.limits.spend import MemorySpendMeter
from app.llm.gemini_provider import GeminiProvider
from app.llm.retry import RetryPolicy
from core.config import Settings
from evals.fakes.sse_contract import parse_sse

PER_MINUTE = "429 RESOURCE_EXHAUSTED: Quota exceeded for metric generate_content_requests_per_minute"
LONG_RETRY = PER_MINUTE + " 'retryDelay': '37s'"
STORM_TURNS = 20
STORM_BUDGET_S = 20.0


class FakeAPIError(Exception):
    """Shape of google.genai errors as app/llm/errors.map_exception reads them (code + details)."""

    def __init__(self, code: int, details: str) -> None:
        super().__init__(f"{code} {details}")
        self.code = code
        self.details = details


def _chunk(text: str, finish: str | None = None, block: str | None = None) -> Any:
    part = SimpleNamespace(text=text, thought=False)
    cand = SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason=finish)
    feedback = SimpleNamespace(block_reason=block) if block else None
    return SimpleNamespace(candidates=[cand], prompt_feedback=feedback, usage_metadata=None)


def _benign_answers(questions: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, q in questions.items():
        if q["type"] == "noul":
            out[key] = SimpleNamespace(type="noul", noul=0.01 if key.startswith(("risk_", "pop_")) else 0.99,
                                       confidence=0.95)
        else:
            options = list(q.get("criteria") or {})
            choice = next((o for o in ("medical_info", "en") if o in options), options[0])
            out[key] = SimpleNamespace(type="choice", choice=choice, confidence=0.95, probabilities={})
    return out


class FakeModels:
    def __init__(self, *, error: Exception | None = None, chunks: list[Any] | None = None) -> None:
        self.error, self.chunks, self.calls = error, chunks or [], 0

    async def generate_content(self, **_: Any) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return _chunk("{}", "STOP")

    async def generate_content_stream(self, **_: Any) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error

        async def stream() -> Any:
            for c in self.chunks:
                yield c

        return stream()


class FakeDecisions:
    def __init__(self, *, error: Exception | None = None, block: str | None = None) -> None:
        self.error, self.block, self.calls = error, block, 0

    async def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        feedback = SimpleNamespace(block_reason=self.block) if self.block else None
        answers = {} if self.block else _benign_answers(kwargs["questions"])
        return SimpleNamespace(answers=answers, usage=SimpleNamespace(total_input_tokens=200), prompt_feedback=feedback)


def provider(models: FakeModels, decisions: FakeDecisions, meter: MemorySpendMeter) -> GeminiProvider:
    client = SimpleNamespace(aio=SimpleNamespace(models=models, decisions=decisions))
    settings = Settings(_env_file=None, GEMINI_API_KEY="unused-test-key", GEMINI_TIER="free")  # type: ignore[call-arg]  # secret-scan: allow
    policy = RetryPolicy(attempts=3, base_delay_s=0.01, max_delay_s=0.05)
    return GeminiProvider(settings, spend=meter, client=client, policy=policy)  # type: ignore[arg-type]


async def _turn_from(api: ChaosApp, ip: str, message: str) -> Turn:
    transport = httpx.ASGITransport(app=api.app, client=(ip, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=60) as http:
        r = await http.post("/api/v1/session", json={"locale": "en"})
        token = r.json()["session_token"]
        res = await http.post(
            "/api/v1/chat",
            json={"message": message, "locale": "en", "client_turn_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        return Turn(res, parse_sse(res.text) if res.status_code == 200 else [])


@pytest.mark.parametrize("details", [PER_MINUTE, LONG_RETRY], ids=["retry-and-backoff", "long-retry-after"])
async def test_429_storm_gives_busy_answers_fast_and_settles_spend(chaos_app, details) -> None:
    meter = MemorySpendMeter(cap_usd=5.0)
    models, decisions = FakeModels(error=FakeAPIError(429, details)), FakeDecisions(error=FakeAPIError(429, details))
    async with chaos_app(llm=provider(models, decisions, meter)) as api:
        profile = api.container.profile()
        busy = api.container.texts.response("busy", "en", profile)
        t0 = time.perf_counter()
        turns = await asyncio.gather(*(_turn_from(api, f"198.51.100.{i + 10}", FEVER) for i in range(STORM_TURNS)))
        elapsed = time.perf_counter() - t0
        for turn in turns:
            turn.assert_contract()
            assert turn.answer().mode == "template"
            assert turn.answer().text == busy
            assert profile.emergency.number in turn.answer().text
        assert elapsed < STORM_BUDGET_S
        assert api.container.admission.held == 0
        assert api.container.admission.waiting == 0
        assert await meter.spent_today() == pytest.approx(0.0, abs=1e-12)
        assert models.calls + decisions.calls > 0
        emergency = await api.chat(await api.token(), EMERGENCY)
        emergency.assert_contract()
        assert any(e.type == "safety" and e.kind == "emergency" for e in emergency.events)


async def test_day_scope_429_is_not_retried(chaos_app) -> None:
    meter = MemorySpendMeter(cap_usd=5.0)
    day = FakeAPIError(429, "Quota exceeded for metric generate_content_requests_per_day, limit: 0")
    models, decisions = FakeModels(error=day), FakeDecisions(error=day)
    async with chaos_app(llm=provider(models, decisions, meter)) as api:
        turn = await api.chat(await api.token(), FEVER)
        turn.assert_contract()
        assert turn.answer().mode == "template"
        # guard decide + guard fallback + answer + answer fallback, each tried exactly once
        assert decisions.calls == 1
        assert models.calls <= 3
        assert await meter.spent_today() == pytest.approx(0.0, abs=1e-12)


def _assert_blocked_refusal(api: ChaosApp, turn: Turn) -> None:
    turn.assert_contract()
    answer = turn.answer()
    profile = api.container.profile()
    assert answer.mode == "refusal"
    assert answer.text == api.container.texts.response("refusal_blocked", "en", profile)
    assert profile.emergency.number in answer.text
    assert any(c.number in answer.text for c in profile.crisis_lines)


async def test_provider_blocks_the_guard_input(chaos_app) -> None:
    meter = MemorySpendMeter(cap_usd=5.0)
    llm = provider(FakeModels(), FakeDecisions(block="SAFETY"), meter)
    async with chaos_app(llm=llm) as api:
        _assert_blocked_refusal(api, await api.chat(await api.token(), FEVER))
        assert api.container.admission.held == 0


async def test_provider_blocks_the_streamed_answer(chaos_app) -> None:
    meter = MemorySpendMeter(cap_usd=5.0)
    chunks = [_chunk("A fever is a body temperature of 38 °C or higher [1]. "), _chunk("", "SAFETY")]
    models = FakeModels(chunks=chunks)
    async with chaos_app(llm=provider(models, FakeDecisions(), meter)) as api:
        turn = await api.chat(await api.token(), FEVER)
        _assert_blocked_refusal(api, turn)
        assert models.calls == 1
        assert await meter.spent_today() >= 0.0  # settled (estimated input tokens), never left reserved


async def test_provider_rejects_the_prompt_as_prohibited(chaos_app) -> None:
    meter = MemorySpendMeter(cap_usd=5.0)
    models = FakeModels(error=FakeAPIError(400, "{'error': {'status': 'prohibited_content'}}"))
    async with chaos_app(llm=provider(models, FakeDecisions(), meter)) as api:
        _assert_blocked_refusal(api, await api.chat(await api.token(), FEVER))
