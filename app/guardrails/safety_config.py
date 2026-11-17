"""Typed, validated view of config/safety/thresholds.yaml (loaded once at startup)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.config_files import CONFIG_ROOT, ConfigFileError, load_yaml
from core.schemas.chat import RiskKind

THRESHOLDS_PATH = CONFIG_ROOT / "safety" / "thresholds.yaml"
SAFETY_KINDS: frozenset[RiskKind] = frozenset(
    {RiskKind.EMERGENCY, RiskKind.SELF_HARM, RiskKind.HARM_TO_OTHERS, RiskKind.ABUSE_DISCLOSURE}
)
STRIKE_KINDS: frozenset[RiskKind] = frozenset(
    {RiskKind.INJECTION, RiskKind.HARMFUL_REQUEST, RiskKind.ABUSIVE_USER}
)


@dataclass(frozen=True)
class Timeouts:
    router_s: float = 6.0
    rewrite_s: float = 6.0
    verify_s: float = 8.0
    retrieval_s: float = 8.0


@dataclass(frozen=True)
class GroundednessConfig:
    supported_min: float = 0.5
    min_kept_ratio: float = 0.5
    max_sentences_per_call: int = 20


@dataclass(frozen=True)
class SafetyConfig:
    risk_thresholds: Mapping[RiskKind, float]
    population_threshold: float = 0.5
    intent_min_confidence: float = 0.4
    language_min_confidence: float = 0.5
    fuzzy_min_term_chars: int = 8
    injection_min_score: float = 0.5
    strikes_to_lock: int = 3
    block_medical_after: frozenset[RiskKind] = frozenset({RiskKind.EMERGENCY, RiskKind.SELF_HARM})
    timeouts: Timeouts = field(default_factory=Timeouts)
    groundedness: GroundednessConfig = field(default_factory=GroundednessConfig)

    def threshold(self, kind: RiskKind) -> float:
        return self.risk_thresholds.get(kind, 0.5)


def _prob(value: Any, where: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigFileError(f"thresholds: {where} must be a number") from exc
    if not 0.0 <= out <= 1.0:
        raise ConfigFileError(f"thresholds: {where} must be between 0 and 1")
    return out


def _section(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key) or {}
    if not isinstance(value, Mapping):
        raise ConfigFileError(f"thresholds: '{key}' must be a mapping")
    return value


def _risks(classifier: Mapping[str, Any]) -> Mapping[RiskKind, float]:
    risk = _section(classifier, "risk")
    out: dict[RiskKind, float] = {}
    for key, value in risk.items():
        try:
            kind = RiskKind(key)
        except ValueError as exc:
            raise ConfigFileError(f"thresholds: unknown risk kind {key!r}") from exc
        out[kind] = _prob(value, f"classifier.risk.{key}")
    return MappingProxyType(out)


def parse_safety_config(raw: Mapping[str, Any]) -> SafetyConfig:
    classifier = _section(raw, "classifier")
    lexicon = _section(raw, "lexicon")
    session = _section(raw, "session")
    timeouts = _section(raw, "timeouts")
    ground = _section(raw, "groundedness")
    try:
        block = frozenset(RiskKind(k) for k in session.get("block_medical_after", ["emergency", "self_harm"]))
    except ValueError as exc:
        raise ConfigFileError("thresholds: session.block_medical_after has an unknown kind") from exc
    return SafetyConfig(
        risk_thresholds=_risks(classifier),
        population_threshold=_prob(classifier.get("population", 0.5), "classifier.population"),
        intent_min_confidence=_prob(classifier.get("intent_min_confidence", 0.4), "intent_min_confidence"),
        language_min_confidence=_prob(
            classifier.get("language_min_confidence", 0.5), "language_min_confidence"
        ),
        fuzzy_min_term_chars=int(lexicon.get("fuzzy_min_term_chars", 8)),
        injection_min_score=_prob(_section(raw, "injection").get("heuristic_min_score", 0.5), "injection"),
        strikes_to_lock=max(1, int(session.get("strikes_to_lock", 3))),
        block_medical_after=block,
        timeouts=Timeouts(**{k: float(v) for k, v in timeouts.items() if k in Timeouts.__dataclass_fields__}),
        groundedness=GroundednessConfig(
            supported_min=_prob(ground.get("supported_min", 0.5), "groundedness.supported_min"),
            min_kept_ratio=_prob(ground.get("min_kept_ratio", 0.5), "groundedness.min_kept_ratio"),
            max_sentences_per_call=max(1, int(ground.get("max_sentences_per_call", 20))),
        ),
    )


def load_safety_config(path: Path = THRESHOLDS_PATH) -> SafetyConfig:
    return parse_safety_config(load_yaml(path))
