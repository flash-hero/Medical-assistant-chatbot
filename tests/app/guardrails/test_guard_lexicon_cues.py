"""Context cues: negation, historical, informational and personal markers (app/guardrails/lexicon_cues.py)."""

from __future__ import annotations

from typing import Any

import pytest

from app.config_files import ConfigFileError
from app.guardrails.lexicon_cues import CueSet, build_cue_set, plain_form, skeleton_form

RAW: dict[str, Any] = {
    "negation_window": 3,
    "negation": {"en": ["no", "don't"], "fr": ["pas"], "ar": ["لا"], "arabizi": ["ma", "la"]},
    "negation_exceptions": {"en": ["no doubt"], "ar": ["ما زال"]},
    "historical": {"en": ["last month", "in \\d{4}"], "fr": ["le mois dernier"]},
    "informational": {"en": ["what is", "signs of"], "fr": ["est ce que"]},
    "personal": {"en": ["my", "i"], "fr": ["mon", "il"]},
    "clause_breaks": {"en": ["but"], "fr": ["mais"]},
}


@pytest.fixture
def cues() -> CueSet:
    return build_cue_set(RAW, plain_form)


def _before(text: str) -> list[str]:
    return plain_form(text).split()


def test_negation_within_window(cues: CueSet) -> None:
    assert cues.is_negated(_before("i don't have"), "en")
    assert cues.is_negated(_before("no"), "en")


def test_negation_outside_window(cues: CueSet) -> None:
    assert not cues.is_negated(_before("no fever at all and then"), "en")


def test_negation_is_scoped_by_entry_language(cues: CueSet) -> None:
    # Arabizi "ma" must not negate a French hit ("ma poitrine")
    assert not cues.is_negated(_before("ma"), "fr")
    assert cues.is_negated(_before("ma"), "arabizi")


def test_new_subject_pronoun_breaks_negation(cues: CueSet) -> None:
    assert not cues.is_negated(_before("no i"), "en")


def test_negation_exception_is_not_a_negation(cues: CueSet) -> None:
    assert not cues.is_negated(_before("no doubt"), "en")
    assert not cues.is_negated(_before("ما زال"), "ar")


def test_darija_negation_circumfix(cues: CueSet) -> None:
    assert cues.is_negated(["ماعنديش"], "ar")
    assert not cues.is_negated(["ماعنديش"], "en")
    assert not cues.is_negated(["مش"], "ar")  # too short for the circumfix rule and not a listed cue


def test_skeleton_cue_set_has_no_affix_rule() -> None:
    skel = build_cue_set(RAW, skeleton_form, skeleton=True)
    assert not skel.is_negated(["ماعنديش"], "ar")


def test_historical(cues: CueSet) -> None:
    assert cues.is_historical(plain_form("i had chest pain last month"))
    assert cues.is_historical(plain_form("heart attack in 2015"))
    assert not cues.is_historical(plain_form("chest pain right now"))


def test_informational_without_personal_cue(cues: CueSet) -> None:
    clause = plain_form("what is a stroke")
    assert cues.is_informational(clause, clause.index("stroke"))


def test_informational_with_personal_cue_is_not_informational(cues: CueSet) -> None:
    clause = plain_form("what is happening to my dad stroke")
    assert not cues.is_informational(clause, clause.index("stroke"))


def test_informational_cue_must_precede_hit(cues: CueSet) -> None:
    clause = plain_form("stroke signs of")
    assert not cues.is_informational(clause, 0)


def test_french_inversion_is_not_personal(cues: CueSet) -> None:
    clause = plain_form("est ce que l avc abime t il le cerveau")
    assert cues.is_informational(clause, clause.index("avc"))


def test_french_inversion_after_the_hit_makes_a_question(cues: CueSet) -> None:
    clause = plain_form("une surdose de paracetamol abime-t-elle le foie")
    assert cues.is_informational(clause, clause.index("surdose"))


def test_french_inversion_with_personal_cue_is_not_informational(cues: CueSet) -> None:
    clause = plain_form("mon fils a pris une surdose doit-il aller aux urgences")
    assert not cues.is_informational(clause, clause.index("surdose"))


def test_inversion_rule_works_without_informational_cues() -> None:
    bare = build_cue_set({"personal": {"fr": ["mon"]}}, plain_form)
    clause = plain_form("une surdose abime-t-elle le foie")
    assert bare.is_informational(clause, clause.index("surdose"))
    assert not bare.is_informational(plain_form("une surdose grave"), 4)


def test_split_on_clause_breaks(cues: CueSet) -> None:
    assert cues.split(plain_form("no fever but chest pain")) == ["no fever", "chest pain"]


def test_split_without_breaks_returns_clause() -> None:
    bare = build_cue_set({}, plain_form)
    assert bare.split("a b") == ["a b"]
    assert bare.historical is None
    assert not bare.is_historical("last month")
    assert not bare.is_informational("what is", 7)


def test_bad_section_type_raises() -> None:
    with pytest.raises(ConfigFileError):
        build_cue_set({"negation": ["no"]}, plain_form)


def test_bad_language_list_raises() -> None:
    with pytest.raises(ConfigFileError):
        build_cue_set({"negation": {"en": "no"}}, plain_form)
