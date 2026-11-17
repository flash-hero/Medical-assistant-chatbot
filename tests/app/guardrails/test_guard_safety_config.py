"""Typed view of config/safety/thresholds.yaml (app/guardrails/safety_config.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config_files import ConfigFileError
from app.guardrails.safety_config import (
    SAFETY_KINDS,
    STRIKE_KINDS,
    SafetyConfig,
    load_safety_config,
    parse_safety_config,
)
from core.schemas.chat import RiskKind


def test_real_thresholds_file_loads() -> None:
    cfg = load_safety_config()
    assert cfg.threshold(RiskKind.SELF_HARM) == pytest.approx(0.25)
    assert cfg.threshold(RiskKind.EMERGENCY) == pytest.approx(0.30)
    assert cfg.block_medical_after == frozenset({RiskKind.EMERGENCY, RiskKind.SELF_HARM})
    assert cfg.strikes_to_lock == 3
    assert cfg.timeouts.router_s == pytest.approx(6.0)
    assert cfg.groundedness.max_sentences_per_call == 20


def test_defaults_from_empty_mapping() -> None:
    cfg = parse_safety_config({})
    assert isinstance(cfg, SafetyConfig)
    assert cfg.threshold(RiskKind.INJECTION) == pytest.approx(0.5)  # unknown kind -> 0.5
    assert cfg.injection_min_score == pytest.approx(0.5)
    assert cfg.groundedness.supported_min == pytest.approx(0.5)


def test_risk_thresholds_are_read_only() -> None:
    cfg = parse_safety_config({"classifier": {"risk": {"emergency": 0.2}}})
    with pytest.raises(TypeError):
        cfg.risk_thresholds[RiskKind.EMERGENCY] = 0.9  # type: ignore[index]


def test_timeouts_ignore_unknown_keys() -> None:
    cfg = parse_safety_config({"timeouts": {"router_s": 2, "bogus_s": 9}})
    assert cfg.timeouts.router_s == pytest.approx(2.0)


def test_strikes_to_lock_is_at_least_one() -> None:
    assert parse_safety_config({"session": {"strikes_to_lock": 0}}).strikes_to_lock == 1


@pytest.mark.parametrize(
    "raw",
    [
        {"classifier": {"risk": {"zombies": 0.5}}},
        {"classifier": {"risk": {"emergency": 1.5}}},
        {"classifier": {"risk": {"emergency": "high"}}},
        {"classifier": {"population": -0.1}},
        {"classifier": ["emergency"]},
        {"session": {"block_medical_after": ["zombies"]}},
        {"groundedness": {"supported_min": 2}},
    ],
)
def test_invalid_values_raise(raw: dict[str, object]) -> None:
    with pytest.raises(ConfigFileError):
        parse_safety_config(raw)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError):
        load_safety_config(tmp_path / "nope.yaml")


def test_kind_groups_are_disjoint() -> None:
    assert not SAFETY_KINDS & STRIKE_KINDS
    assert RiskKind.EMERGENCY in SAFETY_KINDS
    assert RiskKind.INJECTION in STRIKE_KINDS
