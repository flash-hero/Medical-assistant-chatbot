"""Typed view of config/prompts/guard.v1.yaml: decision questions for the GUARD role, the GUARD_FALLBACK JSON
classifier prompt and the VERIFY prompts. Validated at startup."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.config_files import CONFIG_ROOT, ConfigFileError, load_yaml
from app.guardrails.groundedness import VerifyPrompts
from core.schemas.chat import Intent, Population, RiskKind

GUARD_PROMPTS_PATH = CONFIG_ROOT / "prompts" / "guard.v1.yaml"


@dataclass(frozen=True)
class GuardPrompts:
    version: str
    preamble: str
    risks: Mapping[RiskKind, str]
    populations: Mapping[Population, str]
    intent_instructions: str
    intent_options: Mapping[str, str]
    language_instructions: str
    language_options: Mapping[str, str]
    fallback_system: str
    verify: VerifyPrompts


def _text(raw: Mapping[str, Any], key: str, where: str = "guard prompts") -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigFileError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping) or not value:
        raise ConfigFileError(f"guard prompts: '{key}' must be a non-empty mapping")
    return value


def _choice(raw: Mapping[str, Any], key: str, allowed: set[str]) -> tuple[str, Mapping[str, str]]:
    section = _mapping(raw, key)
    options = _mapping(section, "options")
    unknown = set(options) - allowed
    missing = allowed - set(options)
    if unknown or missing:
        raise ConfigFileError(
            f"guard prompts: '{key}.options' mismatch (unknown={unknown}, missing={missing})"
        )
    return _text(section, "instructions"), MappingProxyType({str(k): str(v) for k, v in options.items()})


def parse_guard_prompts(raw: Mapping[str, Any]) -> GuardPrompts:
    risks_raw = _mapping(raw, "risks")
    pops_raw = _mapping(raw, "populations")
    try:
        risks = {RiskKind(k): str(v).strip() for k, v in risks_raw.items()}
        pops = {Population(k): str(v).strip() for k, v in pops_raw.items()}
    except ValueError as exc:
        raise ConfigFileError("guard prompts: unknown risk kind or population") from exc
    if set(risks) != set(RiskKind) or set(pops) != set(Population):
        raise ConfigFileError("guard prompts: every RiskKind and Population needs a question")
    intent_instr, intent_opts = _choice(raw, "intent", {i.value for i in Intent})
    lang_instr, lang_opts = _choice(raw, "language", {"en", "fr", "ar"})
    verify = _mapping(raw, "verify")
    question = _text(verify, "question", "verify prompts")
    if "{sentence}" not in question:
        raise ConfigFileError("verify prompts: 'question' must contain {sentence}")
    return GuardPrompts(
        version=_text(raw, "version"),
        preamble=_text(raw, "preamble"),
        risks=MappingProxyType(risks),
        populations=MappingProxyType(pops),
        intent_instructions=intent_instr,
        intent_options=intent_opts,
        language_instructions=lang_instr,
        language_options=lang_opts,
        fallback_system=_text(raw, "fallback_system"),
        verify=VerifyPrompts(
            preamble=_text(verify, "preamble", "verify prompts"),
            question=question,
            fallback_system=_text(verify, "fallback_system", "verify prompts"),
        ),
    )


def load_guard_prompts(path: Path = GUARD_PROMPTS_PATH) -> GuardPrompts:
    return parse_guard_prompts(load_yaml(path))
