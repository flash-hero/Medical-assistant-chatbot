"""Combinations inside the LexiconMatcher scan: order, judgement, precedence and loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config_files import ConfigFileError
from app.guardrails.lexicon import LexiconMatcher, load_lexicon
from core.schemas.chat import RiskKind

CUES: dict[str, Any] = {
    "version": "draft-unreviewed",
    "negation_window": 3,
    "negation": {"en": ["no", "not", "doesn't", "never"], "ar": ["ما", "لا"]},
    "historical": {"en": ["years ago"]},
    "informational": {"en": ["what are", "signs of"]},
    "personal": {"en": ["my", "i", "he", "she"]},
    "clause_breaks": {"en": ["but"]},
}


def _files(emergency_combos: Any) -> dict[str, dict[str, Any]]:
    return {
        "emergency": {
            "version": "draft-unreviewed",
            "kind": "emergency",
            "suppress_historical": True,
            "terms": {"en": ["can't breathe"]},
            "combinations": emergency_combos,
        },
        "self_harm": {
            "version": "draft-unreviewed",
            "kind": "self_harm",
            "suppress_historical": False,
            "combinations": {"en": [[["tired", "sick"], ["of living", "of life"]]]},
        },
        "harm_to_others": {"version": "1", "kind": "harm_to_others", "terms": {"en": ["kill my boss"]}},
        "abuse_disclosure": {"version": "1", "kind": "abuse_disclosure", "terms": {"en": ["he hits me"]}},
    }


COMBOS = {
    "en": [
        [["chest"], ["pain", "pressure", "heavy", "crush*"]],
        [["stiff"], ["neck"], ["fever"]],
    ],
    "ar": [[["ما قادرش", "ما نقدرش"], ["*تنفس"]]],
}


def _load(tmp_path: Path, combos: Any = COMBOS) -> LexiconMatcher:
    directory = tmp_path / "lex"
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in _files(combos).items():
        (directory / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    (directory / "context_cues.yaml").write_text(yaml.safe_dump(CUES, allow_unicode=True), encoding="utf-8")
    return load_lexicon(directory)


@pytest.fixture
def lex(tmp_path: Path) -> LexiconMatcher:
    return _load(tmp_path)


def _kinds(lex: LexiconMatcher, text: str) -> set[RiskKind]:
    return {s.kind for s in lex.signals(text)}


def test_combination_generalises_over_word_order(lex: LexiconMatcher) -> None:
    assert RiskKind.EMERGENCY in _kinds(lex, "heavy pressure in the middle of my chest")
    assert RiskKind.EMERGENCY in _kinds(lex, "my chest is being crushed")


def test_combination_spans_clause_punctuation(lex: LexiconMatcher) -> None:
    assert RiskKind.EMERGENCY in _kinds(lex, "my child has a stiff neck, a high fever, and is drowsy")


def test_combination_signal_detail_names_the_method(lex: LexiconMatcher) -> None:
    (signal,) = lex.signals("my chest feels heavy")
    assert signal.detail == "en:combo"
    assert signal.source == "lexicon"


def test_negation_before_the_combination(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "no chest pain at all") == set()


def test_negation_between_the_matched_words(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "my chest doesn't feel heavy anymore") == set()


def test_historical_combination_is_suppressed(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "years ago my chest was heavy") == set()


def test_informational_combination_is_suppressed(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "what are the signs of chest pressure") == set()
    assert RiskKind.EMERGENCY in _kinds(lex, "what are the signs, my chest is heavy")


def test_negation_particle_inside_the_combination_is_not_a_negation(lex: LexiconMatcher) -> None:
    assert RiskKind.EMERGENCY in _kinds(lex, "ما قادرش نتنفس")


def test_exact_hit_wins_and_combination_is_not_needed(lex: LexiconMatcher) -> None:
    hits = [h for h in lex.scan("I can't breathe and my chest is heavy") if h.kind is RiskKind.EMERGENCY]
    assert [h.method for h in hits] == ["exact"]


def test_suppressed_combination_is_reported_by_scan(lex: LexiconMatcher) -> None:
    hits = [h for h in lex.scan("no chest pain") if h.combo]
    assert [(h.kind, h.status) for h in hits] == [(RiskKind.EMERGENCY, "negated")]


def test_self_harm_combination(lex: LexiconMatcher) -> None:
    assert RiskKind.SELF_HARM in _kinds(lex, "I am so tired of living")


def test_combination_count(lex: LexiconMatcher) -> None:
    assert lex.combination_count == 4


def test_lexicon_without_combinations_still_loads(tmp_path: Path) -> None:
    lex = _load(tmp_path, combos=None)
    assert lex.combination_count == 1  # the self-harm one
    assert _kinds(lex, "my chest is heavy") == set()


def test_malformed_combinations_fail_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError, match="emergency.yaml"):
        _load(tmp_path, combos={"en": [[["chest"]]]})


def test_real_lexicon_has_combinations() -> None:
    assert load_lexicon().combination_count > 0
