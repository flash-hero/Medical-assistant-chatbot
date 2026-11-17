"""Text normalisation used by the lexicon matcher (app/guardrails/lexicon_text.py)."""

from __future__ import annotations

import pytest

from app.guardrails.lexicon_text import arabizi_skeleton, normalize, split_clauses, tokens


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("I can't breathe", "i cant breathe"),
        ("I'm dying", "im dying"),
        ("he doesn't wake up", "he doesnt wake up"),
        ("I've been cutting", "ive been cutting"),
        ("CAN'T  Breathe!!", "cant breathe"),
    ],
)
def test_normalize_folds_english_contractions(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_normalize_keeps_french_elisions_as_separate_tokens() -> None:
    # "m'ouvrir" must stay "m ouvrir", not "mouvrir" (French elision, not an English contraction)
    assert normalize("m'ouvrir les veines") == "m ouvrir les veines"
    assert normalize("il s'étouffe") == "il s etouffe"


def test_normalize_folds_arabic_letters_and_diacritics() -> None:
    assert normalize("أُرِيدُ أَنْ أَمُوتَ") == normalize("اريد ان اموت")
    assert normalize("نوبة") == "نوبه"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("chest pain. no fever", ["chest pain", " no fever"]),
        ("ok, but - wait", ["ok", " but", "wait"]),
        ("واش هادي حالة طارئة؟ صدري كيضرني", ["واش هادي حالة طارئة", " صدري كيضرني"]),
        ("line one\nline two", ["line one", "line two"]),
        ("...", []),
    ],
)
def test_split_clauses_on_punctuation(raw: str, expected: list[str]) -> None:
    assert split_clauses(raw) == expected


def test_arabizi_skeleton_folds_digits_vowels_and_digraphs() -> None:
    a = arabizi_skeleton(normalize("ma9dertch netnefes"))
    b = arabizi_skeleton(normalize("ma9dertch ntnfes"))
    c = arabizi_skeleton(normalize("maqdertch ntnafes"))
    assert a == b == c


def test_arabizi_skeleton_maps_digraphs() -> None:
    assert arabizi_skeleton("khoya") == "X"  # "y" is folded like a vowel
    assert arabizi_skeleton("ghadi") == "Rd"
    assert arabizi_skeleton("chhar") == "Shr"
    assert arabizi_skeleton("7bob") == "hb"


def test_arabizi_skeleton_collapses_repeats_and_spaces() -> None:
    assert arabizi_skeleton("  rassi   bzzaf ") == "rs bzf"


def test_tokens_splits_on_whitespace() -> None:
    assert tokens("a  b\tc") == ["a", "b", "c"]
