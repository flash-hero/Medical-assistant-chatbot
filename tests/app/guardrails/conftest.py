"""Shared fixtures for the guardrail tests (no network: evals.fakes.fake_llm only)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest

from app.guardrails.guard_prompts import GuardPrompts, load_guard_prompts
from app.guardrails.lexicon import LexiconMatcher, load_lexicon
from app.guardrails.safety_config import SafetyConfig, load_safety_config
from core.ports import DecisionAnswer, DecisionQuestion
from core.schemas.chat import Intent, Population, RiskKind

Decider = Callable[[str, str, DecisionQuestion], DecisionAnswer]


@pytest.fixture(scope="session")
def guard_prompts() -> GuardPrompts:
    return load_guard_prompts()


@pytest.fixture(scope="session")
def safety_config() -> SafetyConfig:
    return load_safety_config()


@pytest.fixture(scope="session")
def lexicon() -> LexiconMatcher:
    return load_lexicon()


def make_decider(
    risks: Mapping[RiskKind, float] | None = None,
    pops: Mapping[Population, float] | None = None,
    intent: Intent = Intent.MEDICAL_INFO,
    intent_conf: float = 0.9,
    language: str = "en",
    language_conf: float = 0.9,
) -> Decider:
    """A FakeLLMProvider decider that answers the GUARD questions with fixed probabilities."""
    risks = dict(risks or {})
    pops = dict(pops or {})

    def decide(_input: str, key: str, q: DecisionQuestion) -> DecisionAnswer:
        if key.startswith("risk_"):
            return DecisionAnswer(kind="noul", confidence=0.9, noul=risks.get(RiskKind(key[5:]), 0.01))
        if key.startswith("pop_"):
            return DecisionAnswer(kind="noul", confidence=0.9, noul=pops.get(Population(key[4:]), 0.01))
        if key == "intent":
            return DecisionAnswer(
                kind="choice",
                confidence=intent_conf,
                choice=intent.value,
                probabilities={intent.value: intent_conf},
            )
        return DecisionAnswer(
            kind="choice", confidence=language_conf, choice=language, probabilities={language: language_conf}
        )

    return decide


@pytest.fixture(scope="session")
def decider_factory() -> Callable[..., Decider]:
    """Fixture form of make_decider (test modules cannot import conftest directly)."""
    return make_decider
