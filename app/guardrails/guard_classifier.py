"""The two model-backed classifiers behind the guard: GUARD decide call, then GUARD_FALLBACK JSON generation.

run_classifier() returns None when neither could run, and re-raises UpstreamBlocked (a risk signal).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.guardrails.guard_prompts import GuardPrompts
from core.errors import UpstreamBlocked, UpstreamError
from core.models import ModelRole
from core.ports import DecisionQuestion, DecisionResult, GenerationRequest, LLMProvider
from core.schemas.chat import Intent, Locale, Population, RiskKind

log = structlog.get_logger(__name__)

# Every risk and population question asks about the LATEST message only. Earlier messages are context (who
# "he" is, what "it" refers to) but must not re-raise a risk that only an earlier message described: the
# pipeline keeps that one visible as a sticky session flag. Without this, a live guard model classified
# "What are the visiting hours?" as an emergency because the previous message was one.
LATEST_MESSAGE_SCOPE = (
    'Judge only the latest message (the one marked role="current"). Earlier messages only help to '
    "understand what it refers to: a risk described only in earlier messages does not count unless the "
    'latest message itself describes it, adds to it or asks about it (for example "he is still not '
    'breathing" or "what should I do now?").'
)
POPULATION_SCOPE = (
    'Judge the latest message (the one marked role="current"); earlier messages may say who it is about.'
)


@dataclass(frozen=True)
class ClassifierOutput:
    risks: Mapping[RiskKind, float]
    populations: Mapping[Population, float]
    intent: Intent
    intent_confidence: float
    language: Locale
    language_confidence: float
    source: Literal["decide", "fallback"]
    model_id: str


def decision_questions(prompts: GuardPrompts) -> dict[str, DecisionQuestion]:
    questions: dict[str, DecisionQuestion] = {
        f"risk_{k.value}": DecisionQuestion(kind="noul", instructions=f"{q} {LATEST_MESSAGE_SCOPE}")
        for k, q in prompts.risks.items()
    }
    questions.update(
        {
            f"pop_{p.value}": DecisionQuestion(kind="noul", instructions=f"{q} {POPULATION_SCOPE}")
            for p, q in prompts.populations.items()
        }
    )
    questions["intent"] = DecisionQuestion(
        kind="choice", instructions=prompts.intent_instructions, criteria=dict(prompts.intent_options)
    )
    questions["language"] = DecisionQuestion(
        kind="choice", instructions=prompts.language_instructions, criteria=dict(prompts.language_options)
    )
    return questions


def _clamp(x: float | None) -> float:
    return max(0.0, min(1.0, float(x or 0.0)))


def _choice(res: DecisionResult, key: str) -> tuple[str, float]:
    ans = res.answers[key]
    choice = str(ans.choice or "")
    conf = ans.probabilities.get(choice, ans.confidence) if ans.probabilities else ans.confidence
    return choice, _clamp(conf)


def parse_decision(res: DecisionResult) -> ClassifierOutput:
    """Raises KeyError / ValueError on a malformed response."""
    risks = {k: _clamp(res.answers[f"risk_{k.value}"].noul) for k in RiskKind}
    pops = {p: _clamp(res.answers[f"pop_{p.value}"].noul) for p in Population}
    intent, intent_conf = _choice(res, "intent")
    language, lang_conf = _choice(res, "language")
    if language not in ("en", "fr", "ar"):
        raise ValueError("unknown language choice")
    return ClassifierOutput(
        risks=MappingProxyType(risks),
        populations=MappingProxyType(pops),
        intent=Intent(intent),
        intent_confidence=intent_conf,
        language=language,  # type: ignore[arg-type]
        language_confidence=lang_conf,
        source="decide",
        model_id=res.model_id,
    )


class _FallbackJSON(BaseModel):
    model_config = ConfigDict(extra="ignore")

    risks: dict[RiskKind, float]
    populations: dict[Population, float] = Field(default_factory=dict)
    intent: Intent
    language: Literal["en", "fr", "ar"]


def fallback_schema() -> dict[str, Any]:
    prob = {"type": "number", "minimum": 0, "maximum": 1}
    return {
        "type": "object",
        "properties": {
            "risks": {
                "type": "object",
                "properties": {k.value: prob for k in RiskKind},
                "required": [k.value for k in RiskKind],
            },
            "populations": {
                "type": "object",
                "properties": {p.value: prob for p in Population},
                "required": [p.value for p in Population],
            },
            "intent": {"type": "string", "enum": [i.value for i in Intent]},
            "language": {"type": "string", "enum": ["en", "fr", "ar"]},
        },
        "required": ["risks", "populations", "intent", "language"],
    }


def fallback_system(prompts: GuardPrompts) -> str:
    definitions = "\n".join(f"- {k.value}: {q}" for k, q in prompts.risks.items())
    definitions += "\n" + "\n".join(f"- {p.value}: {q}" for p, q in prompts.populations.items())
    definitions += f"\nRisks: {LATEST_MESSAGE_SCOPE}\nPopulations: {POPULATION_SCOPE}"
    intents = ", ".join(f"{k} ({v})" for k, v in prompts.intent_options.items())
    return prompts.fallback_system.replace("{definitions}", definitions).replace("{intents}", intents)


def parse_fallback(text: str, model_id: str) -> ClassifierOutput:
    """Raises ValueError / ValidationError on malformed output."""
    data = _FallbackJSON.model_validate(json.loads(text))
    return ClassifierOutput(
        risks=MappingProxyType({k: _clamp(data.risks.get(k)) for k in RiskKind}),
        populations=MappingProxyType({p: _clamp(data.populations.get(p)) for p in Population}),
        intent=data.intent,
        intent_confidence=0.75,  # JSON classifiers report no calibrated confidence
        language=data.language,
        language_confidence=0.75,
        source="fallback",
        model_id=model_id,
    )


async def run_classifier(llm: LLMProvider, prompts: GuardPrompts, payload: str) -> ClassifierOutput | None:
    try:
        res = await llm.decide(ModelRole.GUARD, payload, decision_questions(prompts))
        return parse_decision(res)
    except UpstreamBlocked:
        raise
    except (UpstreamError, KeyError, ValueError) as exc:
        log.warning("guard_decide_failed", error=type(exc).__name__)
    request = GenerationRequest(
        role=ModelRole.GUARD_FALLBACK,
        system=fallback_system(prompts),
        prompt=payload,
        json_schema=fallback_schema(),
    )
    try:
        out = await llm.generate(request)
        return parse_fallback(out.text, out.model_id)
    except UpstreamBlocked:
        raise
    except (UpstreamError, ValueError, ValidationError) as exc:
        log.warning("guard_fallback_failed", error=type(exc).__name__)
        return None
