"""Deterministic multilingual risk lexicon (app/guardrails/lexicon.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config_files import ConfigFileError
from app.guardrails.lexicon import LEXICON_KINDS, LexiconMatcher, LexiconSettings, load_lexicon
from core.schemas.chat import RiskKind

CUES: dict[str, Any] = {
    "version": "draft-unreviewed",
    "negation_window": 3,
    "negation": {"en": ["no", "not", "don't"], "fr": ["pas", "sans"], "ar": ["لا", "ما"], "arabizi": ["ma"]},
    "historical": {"en": ["last month", "years ago"]},
    "informational": {"en": ["what is", "what are", "signs of"]},
    "personal": {"en": ["my", "i", "he", "she"]},
    "clause_breaks": {"en": ["but"]},
}
FILES: dict[str, dict[str, Any]] = {
    "emergency": {
        "version": "draft-unreviewed",
        "kind": "emergency",
        "suppress_historical": True,
        "exclusions": ["dying to know"],
        "terms": {
            "en": ["can't breathe", "i'm dying", "worst headache of my life"],
            "ar": ["نوبة قلبية"],
            "arabizi": ["ma9dertch ntnfes"],
        },
        "condition_terms": {"en": ["stroke", "chest pain"]},
    },
    "self_harm": {
        "version": "draft-unreviewed",
        "kind": "self_harm",
        "suppress_historical": False,
        "terms": {"en": ["kill myself"], "fr": ["envie de mourir"]},
    },
    "harm_to_others": {"version": "1", "kind": "harm_to_others", "terms": {"en": ["kill my boss"]}},
    "abuse_disclosure": {"version": "1", "kind": "abuse_disclosure", "terms": {"en": ["he hits me"]}},
}


def _write(directory: Path, files: dict[str, dict[str, Any]], cues: dict[str, Any] = CUES) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (directory / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    (directory / "context_cues.yaml").write_text(yaml.safe_dump(cues, allow_unicode=True), encoding="utf-8")
    return directory


@pytest.fixture
def lex(tmp_path: Path) -> LexiconMatcher:
    return load_lexicon(_write(tmp_path / "lex", FILES))


def _kinds(lex: LexiconMatcher, text: str) -> set[RiskKind]:
    return {s.kind for s in lex.signals(text)}


# ---- exact matching ------------------------------------------------------------------------------
def test_exact_term_matches_case_and_punctuation_insensitively(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "HELP!!! I CAN'T BREATHE") == {RiskKind.EMERGENCY}
    assert _kinds(lex, "i cant breathe") == {RiskKind.EMERGENCY}


def test_matches_are_word_bounded(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "strokes of genius") == set()


def test_each_kind_is_reported_once(lex: LexiconMatcher) -> None:
    signals = lex.signals("I'm dying, I can't breathe, I want to kill myself")
    assert sorted(s.kind.value for s in signals) == ["emergency", "self_harm"]


def test_signal_detail_never_contains_user_text(lex: LexiconMatcher) -> None:
    (sig,) = lex.signals("I can't breathe")
    assert sig.source == "lexicon"
    assert sig.detail == "en:exact"
    assert sig.score == 1.0


def test_arabic_term_with_attached_proclitic(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "أظن أنه مصاب بنوبة قلبية الآن") == {RiskKind.EMERGENCY}
    assert _kinds(lex, "وبنوبة قلبية") == {RiskKind.EMERGENCY}


def test_latin_terms_do_not_accept_arabic_proclitics(lex: LexiconMatcher) -> None:
    # "b" + "stroke" would only be a proclitic in Arabic script
    assert _kinds(lex, "bstroke") == set()


def test_arabizi_skeleton_matches_spelling_variants(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "ma9dertch netnefes") == {RiskKind.EMERGENCY}
    assert _kinds(lex, "maqdertch ntnafess daba") == {RiskKind.EMERGENCY}


def test_arabizi_skeleton_negation_is_language_scoped(lex: LexiconMatcher) -> None:
    hits = lex.scan("ma9dertch netnefes")
    assert any(h.active and h.lang == "arabizi" for h in hits)
    assert lex.hit_languages("ma9dertch netnefes") == frozenset({"arabizi"})


# ---- fuzzy matching ------------------------------------------------------------------------------
def test_fuzzy_match_tolerates_misspelling(lex: LexiconMatcher) -> None:
    (sig,) = lex.signals("worst headach of my life")  # one edit on an 8-character token
    assert sig.kind is RiskKind.EMERGENCY
    assert sig.detail == "en:fuzzy"
    assert sig.score == pytest.approx(0.9)


def test_fuzzy_requires_exact_short_tokens(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "worst headache of my lift") == set()  # 4-character tokens must match exactly
    assert _kinds(lex, "worst headacheee of my life") == set()  # two edits on a 8-character token


def test_fuzzy_ignores_unrelated_text(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "what time does the pharmacy open on sunday") == set()


def test_fuzzy_hit_is_still_judged_for_negation(lex: LexiconMatcher) -> None:
    hits = lex.scan("not the worst headach of my life")
    assert hits
    assert all(not h.active for h in hits)


# ---- context: negation, history, information -------------------------------------------------------
def test_negated_hit_is_suppressed(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "I don't have chest pain") == set()
    statuses = {h.status for h in lex.scan("I don't have chest pain")}
    assert statuses == {"negated"}


def test_negation_does_not_cross_clauses(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "no fever, but chest pain now") == {RiskKind.EMERGENCY}


def test_historical_hit_suppressed_for_emergency(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "my chest pain last month was reflux") == set()
    assert {h.status for h in lex.scan("my chest pain last month was reflux")} == {"historical"}


def test_historical_not_suppressed_when_kind_disables_it(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "years ago I tried to kill myself") == {RiskKind.SELF_HARM}


def test_informational_question_about_condition_is_suppressed(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "what are the signs of a stroke?") == set()
    assert {h.status for h in lex.scan("what are the signs of a stroke?")} == {"informational"}


def test_informational_question_with_personal_cue_triggers(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "what is happening, my dad is having a stroke") == {RiskKind.EMERGENCY}


def test_informational_rule_only_applies_to_condition_terms(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "what is it called when I can't breathe") == {RiskKind.EMERGENCY}


def test_exclusion_idiom_is_masked(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "I'm dying to know the visiting hours") == set()
    assert _kinds(lex, "I'm dying") == {RiskKind.EMERGENCY}


def test_empty_and_whitespace_text(lex: LexiconMatcher) -> None:
    assert lex.signals("") == ()
    assert lex.signals("   ...  ") == ()


# ---- loading ---------------------------------------------------------------------------------------
def test_version_is_draft_when_any_file_is_draft(lex: LexiconMatcher) -> None:
    assert lex.version == "draft-unreviewed"


def test_version_joins_reviewed_versions(tmp_path: Path) -> None:
    files = {k: {**v, "version": "2026-12"} for k, v in FILES.items()}
    assert load_lexicon(_write(tmp_path / "lex", files)).version == "2026-12"


def test_term_count_counts_plain_and_skeleton_entries(lex: LexiconMatcher) -> None:
    # 3 en + 1 ar + 1 arabizi (plain + skeleton) + 2 conditions + 2 self-harm + 1 + 1
    assert lex.term_count == 12


def test_missing_kind_raises(tmp_path: Path) -> None:
    files = {**FILES, "emergency": {k: v for k, v in FILES["emergency"].items() if k != "kind"}}
    with pytest.raises(ConfigFileError, match="kind"):
        load_lexicon(_write(tmp_path / "lex", files))


def test_unknown_kind_raises(tmp_path: Path) -> None:
    files = {**FILES, "emergency": {**FILES["emergency"], "kind": "zombies"}}
    with pytest.raises(ConfigFileError):
        load_lexicon(_write(tmp_path / "lex", files))


def test_terms_must_be_a_mapping(tmp_path: Path) -> None:
    files = {**FILES, "emergency": {**FILES["emergency"], "terms": ["can't breathe"]}}
    with pytest.raises(ConfigFileError, match="terms"):
        load_lexicon(_write(tmp_path / "lex", files))


def test_exclusions_must_be_a_list(tmp_path: Path) -> None:
    files = {**FILES, "emergency": {**FILES["emergency"], "exclusions": "dying to know"}}
    with pytest.raises(ConfigFileError, match="exclusions"):
        load_lexicon(_write(tmp_path / "lex", files))


def test_missing_file_raises(tmp_path: Path) -> None:
    directory = _write(tmp_path / "lex", {k: v for k, v in FILES.items() if k != "abuse_disclosure"})
    with pytest.raises(ConfigFileError):
        load_lexicon(directory)


def test_blank_and_short_arabizi_terms(tmp_path: Path) -> None:
    files = {
        **FILES,
        "harm_to_others": {"kind": "harm_to_others", "terms": {"en": ["  "], "arabizi": ["n9tlo"]}},
    }
    lex = load_lexicon(_write(tmp_path / "lex", files))
    assert _kinds(lex, "n9tlo") == {RiskKind.HARM_TO_OTHERS}  # plain entry only (skeleton too short)


def test_settings_control_fuzzy_eligibility(tmp_path: Path) -> None:
    lex = load_lexicon(_write(tmp_path / "lex", FILES), LexiconSettings(fuzzy_min_term_chars=200))
    assert _kinds(lex, "worst headach of my life") == set()


# ---- real configuration ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real() -> LexiconMatcher:
    return load_lexicon()


def test_real_lexicon_is_marked_draft(real: LexiconMatcher) -> None:
    assert real.version == "draft-unreviewed"
    assert real.term_count > 500


@pytest.mark.parametrize("kind", LEXICON_KINDS)
def test_every_real_lexicon_file_declares_draft_status(kind: RiskKind) -> None:
    data = yaml.safe_load((Path("config/safety/lexicons") / f"{kind.value}.yaml").read_text(encoding="utf-8"))
    assert data["version"] == "draft-unreviewed"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("my dad is clutching his chest and can't talk", RiskKind.EMERGENCY),
        ("j'arrive pas à respirer", RiskKind.EMERGENCY),
        ("صدري كيضرني بزاف", RiskKind.EMERGENCY),
        ("sdri kayderni bzaf", RiskKind.EMERGENCY),
        ("I want to kill myself", RiskKind.SELF_HARM),
        ("je veux mourir", RiskKind.SELF_HARM),
        ("بغيت نموت", RiskKind.SELF_HARM),
        ("bghit nmout", RiskKind.SELF_HARM),
        ("I'm going to kill him when he gets home", RiskKind.HARM_TO_OTHERS),
        ("my husband hits me", RiskKind.ABUSE_DISCLOSURE),
    ],
)
def test_real_lexicon_detects(real: LexiconMatcher, text: str, kind: RiskKind) -> None:
    assert kind in _kinds(real, text)


@pytest.mark.parametrize(
    "text",
    [
        "this traffic is killing me",
        "what are the warning signs of a stroke?",
        "I don't have chest pain, just a dry cough",
        "my chest pain last month was diagnosed as reflux",
        "I'm dying to know if coffee raises blood pressure",
        "ma mère a mal à la tête",
        "ما عنديش ألم في الصدر",
    ],
)
def test_real_lexicon_hard_negatives(real: LexiconMatcher, text: str) -> None:
    assert _kinds(real, text) == set()


def test_assess_returns_signals_and_languages_from_one_scan(lex: LexiconMatcher) -> None:
    res = lex.assess("ma9dertch netnefes, I want to kill myself")
    assert {s.kind for s in res.signals} == {RiskKind.EMERGENCY, RiskKind.SELF_HARM}
    assert res.languages == frozenset({"arabizi", "en"})
    assert lex.signals("ma9dertch netnefes") == lex.assess("ma9dertch netnefes").signals


def test_arabic_proclitic_glued_to_latin_term_is_ignored(lex: LexiconMatcher) -> None:
    assert _kinds(lex, "وstroke") == set()


def test_scan_reports_suppressed_hits(lex: LexiconMatcher) -> None:
    hits = lex.scan("I don't have chest pain. what is a stroke?")
    assert {h.status for h in hits} == {"negated", "informational"}
    assert all(h.condition for h in hits)
    assert lex.assess("I don't have chest pain").signals == ()


def test_long_input_scan_is_bounded(real: LexiconMatcher) -> None:
    import time

    text = ("صدري كيضرني بزاف و ما عرفتش اش ندير، " * 60)[:2000]
    real.assess(text)
    started = time.perf_counter()
    real.assess(text)
    assert time.perf_counter() - started < 1.0  # ~0.1 s on a dev laptop; generous bound for CI
