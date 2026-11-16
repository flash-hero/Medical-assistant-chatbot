"""Combinations inside the LexiconMatcher scan: order, judgement, precedence and loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config_files import ConfigFileError, load_yaml
from app.guardrails.lexicon import LEXICON_DIR, LexiconMatcher, load_lexicon
from app.guardrails.lexicon_combos import COMBO_LANGS, parse_combinations
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
    with pytest.raises(ConfigFileError, match=r"emergency\.yaml"):
        _load(tmp_path, combos={"en": [[["chest"]]]})


# ---- the shipped lexicon (engine-api saw test_real_lexicon_has_combinations fail: the combination loader had
# landed before any `combinations` data, so the real lexicon had none) ---------------------------------------
COMBO_KINDS = (RiskKind.EMERGENCY, RiskKind.SELF_HARM)
# Written for these tests (not taken from the eval sets): each one is caught by a combination, not a term.
REAL_COMBO_PROBES = [
    (RiskKind.EMERGENCY, "en", "there is a crushing weight sitting on my chest right now"),
    (RiskKind.EMERGENCY, "fr", "une barre lourde sur la poitrine depuis ce matin"),
    (RiskKind.EMERGENCY, "ar", "صدري فيه ضغط قوي دابا"),
    (RiskKind.EMERGENCY, "arabizi", "sdri fih dagt kbira"),
    (RiskKind.SELF_HARM, "en", "been hoarding my painkillers in a drawer"),
    (RiskKind.SELF_HARM, "fr", "j'ai mis de côté tous mes somnifères"),
    (RiskKind.SELF_HARM, "ar", "جمعت الحبوب ديالي"),
    (RiskKind.SELF_HARM, "arabizi", "bghit nrmi rasi mn sta7"),
]


def test_real_lexicon_has_combinations() -> None:
    assert load_lexicon().combination_count > 0


@pytest.mark.parametrize("kind", COMBO_KINDS, ids=lambda k: k.value)
def test_real_combinations_cover_every_language(kind: RiskKind) -> None:
    name = f"{kind.value}.yaml"
    combos = parse_combinations(load_yaml(LEXICON_DIR / name).get("combinations"), kind, name)
    assert {c.lang for c in combos} == set(COMBO_LANGS)
    assert all(c.kind is kind for c in combos)


def test_real_lexicon_loads_every_combination_of_its_files(lexicon: LexiconMatcher) -> None:
    in_files = 0
    for kind in RiskKind:
        path = LEXICON_DIR / f"{kind.value}.yaml"
        if path.exists():
            in_files += len(parse_combinations(load_yaml(path).get("combinations"), kind, path.name))
    assert lexicon.combination_count == in_files > 0


@pytest.mark.parametrize(("kind", "lang", "text"), REAL_COMBO_PROBES)
def test_real_lexicon_detects_by_combination(
    lexicon: LexiconMatcher, kind: RiskKind, lang: str, text: str
) -> None:
    hits = [h for h in lexicon.scan(text) if h.active and h.kind is kind]
    assert [(h.method, h.lang) for h in hits] == [("combo", lang)]
    assert kind in _kinds(lexicon, text)
