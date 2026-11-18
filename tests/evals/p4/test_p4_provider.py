"""CountingProvider: counting, budget, quota detection, halting; CountingRetryPolicy."""

from __future__ import annotations

import asyncio
import random
from contextlib import aclosing

import pytest

from core.errors import UpstreamRateLimited, UpstreamTimeout
from core.models import ModelRole
from core.ports import DecisionQuestion, GenerationRequest
from evals.fakes.fake_llm import FakeLLMProvider
from evals.p4.provider import (
    DECIDE,
    GENERATE,
    HALT_ROLES,
    BudgetExceeded,
    CountingProvider,
    CountingRetryPolicy,
)

Q = {"q": DecisionQuestion(kind="noul", instructions="yes?")}


def _req(role: ModelRole = ModelRole.ANSWER) -> GenerationRequest:
    return GenerationRequest(role=role, system="s", prompt="p")


async def test_counts_calls_by_kind_and_model() -> None:
    llm = CountingProvider(FakeLLMProvider())
    await llm.generate(_req(ModelRole.REWRITE))
    async with aclosing(llm.stream(_req())) as chunks:  # type: ignore[type-var]
        async for _ in chunks:
            pass
    await llm.decide(ModelRole.GUARD, "x", Q)
    assert llm.totals() == {GENERATE: 2, DECIDE: 1}
    assert llm.by_model() == {"generate:gemini-3.5-flash-lite": 2, "decide:gemini-decision-1": 1}
    assert [c.role for c in llm.calls] == ["rewrite", "answer", "guard"]


async def test_item_window_and_embed_passthrough() -> None:
    llm = CountingProvider(FakeLLMProvider())
    await llm.decide(ModelRole.GUARD, "x", Q)
    llm.begin_item()
    await llm.decide(ModelRole.VERIFY, "x", Q)
    assert [c.role for c in llm.item_calls()] == ["verify"]
    assert len(await llm.embed(["a"], dim=8)) == 1
    assert llm.totals()[DECIDE] == 2


async def test_budget_raises_and_flags() -> None:
    llm = CountingProvider(FakeLLMProvider(), max_generate=1, max_decide=0)
    await llm.generate(_req())
    with pytest.raises(BudgetExceeded):
        await llm.generate(_req())
    assert llm.over_budget
    with pytest.raises(BudgetExceeded):
        await llm.decide(ModelRole.GUARD, "x", Q)
    assert llm.totals() == {GENERATE: 1, DECIDE: 0}


@pytest.mark.parametrize(
    ("scope", "retry_after", "day"),
    [("day", None, True), ("minute", 20.0, False), ("unknown", 600.0, True), ("unknown", 5.0, False)],
)
async def test_rate_limits_are_recorded_and_day_scope_detected(
    scope: str, retry_after: float | None, day: bool
) -> None:
    err = UpstreamRateLimited("429", scope=scope, retry_after_s=retry_after)  # type: ignore[arg-type]
    llm = CountingProvider(FakeLLMProvider(failures={ModelRole.GUARD: err}))
    with pytest.raises(UpstreamRateLimited):
        await llm.decide(ModelRole.GUARD, "x", Q)
    assert llm.rate_limited == ["gemini-decision-1"]
    assert bool(llm.day_quota_hit) is day
    assert llm.calls[0].outcome == "upstream_rate_limited"
    assert llm.calls[0].scope == scope


async def test_other_errors_are_recorded_and_reraised() -> None:
    llm = CountingProvider(FakeLLMProvider(failures={ModelRole.ANSWER: UpstreamTimeout("slow")}))
    with pytest.raises(UpstreamTimeout):
        await llm.generate(_req())
    with pytest.raises(UpstreamTimeout):
        await _drain(llm)
    assert [c.outcome for c in llm.calls] == ["upstream_timeout", "upstream_timeout"]
    assert not llm.rate_limited


async def _drain(llm: CountingProvider) -> None:
    async with aclosing(llm.stream(_req())) as chunks:  # type: ignore[type-var]
        async for _ in chunks:
            pass


async def test_halted_roles_park_until_cancelled_and_are_not_counted() -> None:
    inner = FakeLLMProvider()
    llm = CountingProvider(inner, halt_roles=HALT_ROLES)
    task = asyncio.create_task(llm.generate(_req(ModelRole.REWRITE)))
    await asyncio.sleep(0.01)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inner.calls == []
    assert llm.calls[0].outcome == "halted"
    assert llm.totals()[GENERATE] == 0
    out = await llm.generate(_req(ModelRole.GUARD_FALLBACK))  # the guard fallback is never halted
    assert out.text


async def test_halted_stream_parks_too() -> None:
    llm = CountingProvider(FakeLLMProvider(), halt_roles=HALT_ROLES)

    async def consume() -> None:
        async with aclosing(llm.stream(_req())) as chunks:  # type: ignore[type-var]
            async for _ in chunks:
                pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert llm.calls[0].outcome == "halted"


async def test_aclose_closes_inner() -> None:
    class Closable(FakeLLMProvider):
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    inner = Closable()
    await CountingProvider(inner).aclose()
    assert inner.closed
    await CountingProvider(FakeLLMProvider()).aclose()  # no aclose: nothing to do


def test_retry_policy_logs_every_retry() -> None:
    policy = CountingRetryPolicy()
    rng = random.Random(1)
    assert policy.delay(0, 3.0, rng) == 3.0
    policy.delay(1, None, rng)
    assert len(policy.retries) == 2
    assert policy.attempts == 3  # production policy otherwise unchanged
