"""Scripted behaviour for FakeLLMProvider: keyword-driven guard decisions and role-based responses.

Used by the engine/API contract tests, the gate measurements and local runs with AUSCULTA_LLM_BACKEND=fake.

  provider = scripted_provider()                     # sensible defaults for EN/FR/AR demo scenarios
  provider = scripted_provider(answer="... [1].")    # custom answer text for the ANSWER roles

The guard decider reads only the message marked role="current" in the classifier input, so earlier turns never
change the scripted verdict. The VERIFY role answers every "is this sentence supported?" question with
`supported` (default: supported).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from core.models import ModelRole
from core.ports import DecisionAnswer, DecisionQuestion, GenerationRequest
from core.schemas.chat import Intent, Population, RiskKind
from evals.fakes.fake_llm import FakeLLMProvider

_CURRENT = re.compile(r'<user_message role="current"[^>]*>\n(.*?)\n</user_message', re.DOTALL)
_LATEST = re.compile(r"LATEST user message: (.*?)\n</conversation", re.DOTALL)

DEFAULT_ANSWER = (
    "A fever is a body temperature of 38 °C or higher [1]. Most fevers in adults go away within 3 days [1]. "
    "Drinking fluids and resting can help you feel better [1].\n\n"
    "When to seek care: see a doctor if a fever lasts more than 3 days [2]."
)


@dataclass(frozen=True)
class GuardScript:
    """What the scripted GUARD classifier answers for a message."""

    intent: Intent = Intent.MEDICAL_INFO
    language: str = "en"
    risks: Mapping[RiskKind, float] = field(default_factory=lambda: MappingProxyType({}))
    populations: Mapping[Population, float] = field(default_factory=lambda: MappingProxyType({}))
    intent_confidence: float = 0.9


# (substring in the casefolded current message, script). First match wins.
DEFAULT_RULES: tuple[tuple[str, GuardScript], ...] = (
    ("appointment", GuardScript(intent=Intent.APPOINTMENT)),
    ("rendez-vous", GuardScript(intent=Intent.APPOINTMENT, language="fr")),
    ("موعد", GuardScript(intent=Intent.APPOINTMENT, language="ar")),
    ("visiting hours", GuardScript(intent=Intent.HOSPITAL_ADMIN)),
    ("cardiology", GuardScript(intent=Intent.HOSPITAL_ADMIN)),
    ("heures de visite", GuardScript(intent=Intent.HOSPITAL_ADMIN, language="fr")),
    ("paracetamol", GuardScript(intent=Intent.MEDICATION)),
    (
        "pregnant",
        GuardScript(intent=Intent.MEDICAL_INFO, populations=MappingProxyType({Population.PREGNANCY: 0.9})),
    ),
    ("hello", GuardScript(intent=Intent.SMALLTALK)),
    ("who are you", GuardScript(intent=Intent.META)),
    ("football", GuardScript(intent=Intent.OUT_OF_SCOPE)),
    ("pretend you are", GuardScript(risks=MappingProxyType({RiskKind.INJECTION: 0.95}))),
    (
        "you are useless",
        GuardScript(intent=Intent.SMALLTALK, risks=MappingProxyType({RiskKind.ABUSIVE_USER: 0.95})),
    ),
    ("fièvre", GuardScript(language="fr")),
    ("الحمى", GuardScript(language="ar")),
    # language only: the router makes creator questions META deterministically (classifier says medical_info)
    ("qui t'a", GuardScript(language="fr")),
    ("صنعك", GuardScript(language="ar")),
)


def current_message(input_text: str) -> str:
    found = _CURRENT.search(input_text)
    return found.group(1) if found else input_text


def guard_decider(
    rules: Sequence[tuple[str, GuardScript]] = DEFAULT_RULES,
    default: GuardScript = GuardScript(),
    *,
    supported: float = 0.99,
) -> Callable[[str, str, DecisionQuestion], DecisionAnswer]:
    def script_for(input_text: str) -> GuardScript:
        text = current_message(input_text).casefold()
        return next((s for needle, s in rules if needle.casefold() in text), default)

    def decide(input_text: str, key: str, question: DecisionQuestion) -> DecisionAnswer:
        if re.fullmatch(r"s\d+", key):  # VERIFY: one noul question per answer sentence
            return DecisionAnswer(kind="noul", confidence=0.95, noul=supported)
        script = script_for(input_text)
        if key.startswith("risk_"):
            prob = script.risks.get(RiskKind(key.removeprefix("risk_")), 0.01)
            return DecisionAnswer(kind="noul", confidence=0.95, noul=prob)
        if key.startswith("pop_"):
            prob = script.populations.get(Population(key.removeprefix("pop_")), 0.01)
            return DecisionAnswer(kind="noul", confidence=0.95, noul=prob)
        if key == "intent":
            value, conf = script.intent.value, script.intent_confidence
        else:
            value, conf = script.language, 0.95
        return DecisionAnswer(kind="choice", confidence=conf, choice=value, probabilities={value: conf})

    return decide


def role_responder(
    answer: str = DEFAULT_ANSWER, *, rewrite: Mapping[str, object] | None = None
) -> Callable[[GenerationRequest], str]:
    """ANSWER / ANSWER_FALLBACK -> `answer`; REWRITE -> a JSON query built from the latest message;
    anything else with a JSON schema -> "{}" (forces the caller's own fallback)."""

    def respond(request: GenerationRequest) -> str:
        if request.role in (ModelRole.ANSWER, ModelRole.ANSWER_FALLBACK):
            return answer
        if request.role is ModelRole.REWRITE:
            if rewrite is not None:
                return json.dumps(rewrite, ensure_ascii=False)
            found = _LATEST.search(request.prompt)
            latest = found.group(1).strip() if found else "health question"
            return json.dumps(
                {"standalone_query": latest, "search_queries_en": [latest[:80]], "content_types": []},
                ensure_ascii=False,
            )
        return "{}" if request.json_schema is not None else answer

    return respond


def scripted_provider(
    *,
    answer: str = DEFAULT_ANSWER,
    rules: Sequence[tuple[str, GuardScript]] = DEFAULT_RULES,
    supported: float = 0.99,
    chunk_chars: int = 24,
    chunk_delay_s: float = 0.0,
) -> FakeLLMProvider:
    return FakeLLMProvider(
        responder=role_responder(answer),
        decider=guard_decider(rules, supported=supported),
        chunk_chars=chunk_chars,
        chunk_delay_s=chunk_delay_s,
    )


def all_roles_failing(error: Exception) -> dict[ModelRole, Exception]:
    """A FakeLLMProvider.failures mapping that makes every model role raise `error`."""
    return dict.fromkeys(ModelRole, error)
