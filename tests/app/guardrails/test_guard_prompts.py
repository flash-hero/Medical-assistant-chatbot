"""Typed view of config/prompts/guard.v2.yaml (app/guardrails/guard_prompts.py)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.config_files import ConfigFileError, load_yaml
from app.guardrails.guard_prompts import GUARD_PROMPTS_PATH, load_guard_prompts, parse_guard_prompts
from core.schemas.chat import Intent, Population, RiskKind


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return load_yaml(GUARD_PROMPTS_PATH)


def test_real_prompts_load() -> None:
    prompts = load_guard_prompts()
    assert prompts.version
    assert set(prompts.risks) == set(RiskKind)
    assert set(prompts.populations) == set(Population)
    assert set(prompts.intent_options) == {i.value for i in Intent}
    assert set(prompts.language_options) == {"en", "fr", "ar"}
    assert "{sentence}" in prompts.verify.question


def _broken(raw: dict[str, Any], path: tuple[str, ...], value: object) -> dict[str, Any]:
    out = copy.deepcopy(raw)
    node = out
    for key in path[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("preamble",), "  ", "preamble"),
        (("version",), _DELETE, "version"),
        (("risks",), {}, "risks"),
        (("risks", "zombies"), "q?", "unknown"),
        (("risks", "emergency"), _DELETE, "every RiskKind"),
        (("populations", "child"), _DELETE, "every RiskKind"),
        (("intent", "options", "medical_info"), _DELETE, "mismatch"),
        (("language", "options", "de"), "German", "mismatch"),
        (("verify",), _DELETE, "verify"),
        (("verify", "question"), "Is it supported?", "sentence"),
        (("verify", "fallback_system"), "", "fallback_system"),
    ],
)
def test_invalid_prompts_raise(raw: dict[str, Any], path: tuple[str, ...], value: object, match: str) -> None:
    with pytest.raises(ConfigFileError, match=match):
        parse_guard_prompts(_broken(raw, path, value))
