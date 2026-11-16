"""GUARD decide classifier and GUARD_FALLBACK JSON classifier (app/guardrails/guard_classifier.py)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from app.guardrails.guard_classifier import (
    decision_questions,
    fallback_schema,
    fallback_system,
    parse_decision,
    parse_fallback,
    run_classifier,
)
from app.guardrails.guard_prompts import GuardPrompts
from core.errors import UpstreamBlocked, UpstreamTimeout, UpstreamUnavailable
from core.models import ModelRole
from core.ports import DecisionAnswer, DecisionResult, GenerationRequest
from core.schemas.chat import Intent, Population, RiskKind
from evals.fakes.fake_llm import FakeLLMProvider

FALLBACK_JSON = {
    "risks": {k.value: 0.0 for k in RiskKind} | {"emergency": 0.8},
    "populations": {p.value: 0.0 for p in Population} | {"child": 0.9},
    "intent": "symptom_info",
    "language": "fr",
}


def test_decision_questions_cover_every_risk_population_intent_and_language(
    guard_prompts: GuardPrompts,
) -> None:
    qs = decision_questions(guard_prompts)
    assert {f"risk_{k.value}" for k in RiskKind} <= set(qs)
    assert {f"pop_{p.value}" for p in Population} <= set(qs)
    assert qs["intent"].kind == "choice"
    assert set(qs["intent"].criteria or {}) == {i.value for i in Intent}
    assert qs["language"].kind == "choice"
    assert all(qs[f"risk_{k.value}"].kind == "noul" for k in RiskKind)


def test_parse_decision(guard_prompts: GuardPrompts, decider_factory: Callable[..., Any]) -> None:
    decide = decider_factory(
        risks={RiskKind.SELF_HARM: 0.7},
        pops={Population.PREGNANCY: 0.6},
        intent=Intent.MEDICATION,
        language="ar",
    )
    answers = {k: decide("", k, q) for k, q in decision_questions(guard_prompts).items()}
    out = parse_decision(DecisionResult(answers=answers, model_id="m"))
    assert out.risks[RiskKind.SELF_HARM] == pytest.approx(0.7)
    assert out.populations[Population.PREGNANCY] == pytest.approx(0.6)
    assert out.intent is Intent.MEDICATION
    assert out.language == "ar"
    assert out.source == "decide"
    assert out.model_id == "m"


def test_parse_decision_clamps_and_uses_confidence_without_probabilities(guard_prompts: GuardPrompts) -> None:
    answers: dict[str, DecisionAnswer] = {}
    for key, q in decision_questions(guard_prompts).items():
        if q.kind == "noul":
            answers[key] = DecisionAnswer(kind="noul", confidence=1.0, noul=1.7)
        else:
            choice = "en" if key == "language" else "meta"
            answers[key] = DecisionAnswer(kind="choice", confidence=0.66, choice=choice)
    out = parse_decision(DecisionResult(answers=answers, model_id="m"))
    assert out.risks[RiskKind.INJECTION] == 1.0
    assert out.intent_confidence == pytest.approx(0.66)


def test_parse_decision_rejects_unknown_language(guard_prompts: GuardPrompts, decider_factory: Any) -> None:
    decide = decider_factory(language="de")
    answers = {k: decide("", k, q) for k, q in decision_questions(guard_prompts).items()}
    with pytest.raises(ValueError, match="language"):
        parse_decision(DecisionResult(answers=answers, model_id="m"))


def test_parse_decision_rejects_missing_answer() -> None:
    with pytest.raises(KeyError):
        parse_decision(DecisionResult(answers={}, model_id="m"))


def test_fallback_schema_and_system(guard_prompts: GuardPrompts) -> None:
    schema = fallback_schema()
    assert set(schema["required"]) == {"risks", "populations", "intent", "language"}
    assert set(schema["properties"]["risks"]["required"]) == {k.value for k in RiskKind}
    system = fallback_system(guard_prompts)
    assert "{definitions}" not in system
    assert "{intents}" not in system
    assert "emergency:" in system


def test_parse_fallback() -> None:
    out = parse_fallback(json.dumps(FALLBACK_JSON), "fb")
    assert out.source == "fallback"
    assert out.risks[RiskKind.EMERGENCY] == pytest.approx(0.8)
    assert out.populations[Population.CHILD] == pytest.approx(0.9)
    assert out.intent is Intent.SYMPTOM_INFO
    assert out.language == "fr"


@pytest.mark.parametrize("text", ["not json", "{}", json.dumps({**FALLBACK_JSON, "intent": "nope"})])
def test_parse_fallback_rejects_malformed(text: str) -> None:
    with pytest.raises(ValueError):  # pydantic.ValidationError is a ValueError
        parse_fallback(text, "fb")


async def test_run_classifier_uses_decide(guard_prompts: GuardPrompts, decider_factory: Any) -> None:
    llm = FakeLLMProvider(decider=decider_factory(risks={RiskKind.EMERGENCY: 0.9}))
    out = await run_classifier(llm, guard_prompts, "payload")
    assert out is not None
    assert out.source == "decide"
    assert out.risks[RiskKind.EMERGENCY] == pytest.approx(0.9)
    assert llm.count("generate") == 0


def _fallback_responder(request: GenerationRequest) -> str:
    assert request.role is ModelRole.GUARD_FALLBACK
    assert request.json_schema is not None
    return json.dumps(FALLBACK_JSON)


async def test_run_classifier_falls_back_on_decide_error(guard_prompts: GuardPrompts) -> None:
    llm = FakeLLMProvider(
        responder=_fallback_responder, failures={ModelRole.GUARD: UpstreamUnavailable("down")}
    )
    out = await run_classifier(llm, guard_prompts, "payload")
    assert out is not None
    assert out.source == "fallback"
    assert out.language == "fr"


async def test_run_classifier_falls_back_on_malformed_decision(
    guard_prompts: GuardPrompts, decider_factory: Any
) -> None:
    llm = FakeLLMProvider(responder=_fallback_responder, decider=decider_factory(language="xx"))
    out = await run_classifier(llm, guard_prompts, "payload")
    assert out is not None
    assert out.source == "fallback"


async def test_run_classifier_returns_none_when_both_fail(guard_prompts: GuardPrompts) -> None:
    llm = FakeLLMProvider(
        failures={ModelRole.GUARD: UpstreamTimeout("t"), ModelRole.GUARD_FALLBACK: UpstreamTimeout("t")}
    )
    assert await run_classifier(llm, guard_prompts, "payload") is None


async def test_run_classifier_returns_none_on_malformed_fallback(guard_prompts: GuardPrompts) -> None:
    llm = FakeLLMProvider(responder=lambda r: "{oops", failures={ModelRole.GUARD: UpstreamTimeout("t")})
    assert await run_classifier(llm, guard_prompts, "payload") is None


@pytest.mark.parametrize("role", [ModelRole.GUARD, ModelRole.GUARD_FALLBACK])
async def test_run_classifier_reraises_blocks(guard_prompts: GuardPrompts, role: ModelRole) -> None:
    failures: dict[ModelRole, Exception] = {role: UpstreamBlocked(reason="SAFETY", stage="prompt")}
    if role is ModelRole.GUARD_FALLBACK:
        failures[ModelRole.GUARD] = UpstreamTimeout("t")
    llm = FakeLLMProvider(failures=failures)
    with pytest.raises(UpstreamBlocked):
        await run_classifier(llm, guard_prompts, "payload")
