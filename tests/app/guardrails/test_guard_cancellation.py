"""A turn cancellation must reach the guard and verify calls (router.py, groundedness.py).

Regression: Python 3.11 asyncio.wait_for returns the inner result and drops an outer task.cancel() when the
inner awaitable completes in the same loop iteration, so a cancelled turn kept running. Each test parks the
model call on a future, then resolves it and cancels the turn back to back, which is exactly that race.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.guardrails.groundedness import GroundednessVerifier, VerifyPrompts
from app.guardrails.guard_prompts import GuardPrompts
from app.guardrails.lexicon import LexiconMatcher
from app.guardrails.router import GuardRouter, RouterInput
from app.guardrails.safety_config import GroundednessConfig, SafetyConfig
from core.errors import UpstreamTimeout
from core.models import ModelRole
from core.ports import DecisionAnswer, DecisionQuestion, DecisionResult, GenerationRequest, GenerationResult
from evals.fakes.fake_llm import FakeLLMProvider

DECIDE = "decide"
GENERATE = "generate"
PROMPTS = VerifyPrompts(
    preamble="Passages follow.", question="Supported: «{sentence}»?", fallback_system="SYS"
)


@dataclass
class GatedLLM(FakeLLMProvider):
    """FakeLLMProvider whose gated calls park on a future until the test releases them."""

    gated: frozenset[str] = frozenset()
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    gate: asyncio.Future[None] | None = None

    async def _pass_gate(self, kind: str) -> None:
        if kind not in self.gated:
            return
        self.gate = asyncio.get_running_loop().create_future()
        self.entered.set()
        await self.gate

    def release(self) -> None:
        if self.gate is None:
            raise AssertionError("no call is parked on the gate")
        self.gate.set_result(None)

    async def decide(
        self, role: ModelRole, input_text: str, questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        await self._pass_gate(DECIDE)
        return await super().decide(role, input_text, questions)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        await self._pass_gate(GENERATE)
        return await super().generate(request)


async def _cancel_as_call_completes(llm: GatedLLM, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro)
    await llm.entered.wait()
    llm.release()  # the model call completes ...
    task.cancel()  # ... in the same loop iteration as the turn is cancelled
    return task


def _fallback_json(_request: GenerationRequest) -> str:
    return '{"s0": true}'


Decider = Callable[[str, str, DecisionQuestion], DecisionAnswer]


def _gated_llm(kind: str, role_down: ModelRole, decider: Decider) -> GatedLLM:
    """Gate `kind`; when the fallback (generate) is gated, the decide call of `role_down` fails first."""
    failures: dict[ModelRole, Exception] = {role_down: UpstreamTimeout("t")} if kind == GENERATE else {}
    return GatedLLM(gated=frozenset({kind}), failures=failures, decider=decider, responder=_fallback_json)


@pytest.fixture
def decider(decider_factory: Callable[..., Decider]) -> Decider:
    return decider_factory()


@pytest.mark.parametrize("kind", [DECIDE, GENERATE])
async def test_router_propagates_cancellation(
    kind: str,
    decider: Decider,
    lexicon: LexiconMatcher,
    guard_prompts: GuardPrompts,
    safety_config: SafetyConfig,
) -> None:
    llm = _gated_llm(kind, ModelRole.GUARD, decider)
    router = GuardRouter(llm, lexicon, guard_prompts, safety_config)
    inp = RouterInput(text="what are the visiting hours?")
    task = await _cancel_as_call_completes(llm, router.route(inp, router.precheck(inp.text)))
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.parametrize("kind", [DECIDE, GENERATE])
async def test_verifier_propagates_cancellation(kind: str, decider: Decider) -> None:
    llm = _gated_llm(kind, ModelRole.VERIFY, decider)
    verifier = GroundednessVerifier(llm, PROMPTS, GroundednessConfig(), timeout_s=5.0)
    task = await _cancel_as_call_completes(llm, verifier.verify(["fever."], ["passage"]))
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


async def test_gated_call_still_returns_when_not_cancelled(
    decider: Decider, lexicon: LexiconMatcher, guard_prompts: GuardPrompts, safety_config: SafetyConfig
) -> None:
    llm = _gated_llm(DECIDE, ModelRole.GUARD, decider)
    router = GuardRouter(llm, lexicon, guard_prompts, safety_config)
    inp = RouterInput(text="what are the visiting hours?")
    task = asyncio.create_task(router.route(inp, router.precheck(inp.text)))
    await llm.entered.wait()
    llm.release()
    result = await task
    assert result.classifier == "decide"
    assert result.verdict.classifier_available
