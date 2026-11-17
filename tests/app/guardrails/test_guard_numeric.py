"""Numeric grounding (app/guardrails/numeric.py)."""

from __future__ import annotations

import pytest

from app.guardrails.numeric import UNPARSED, Quantity, extract_quantities, ungrounded_quantities


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("take 500 mg", (Quantity("500", "mg"),)),
        ("500mg", (Quantity("500", "mg"),)),
        ("500 milligrams", (Quantity("500", "mg"),)),
        ("0,5 g", (Quantity("0.5", "g"),)),
        ("0.50 g", (Quantity("0.5", "g"),)),
        ("٥٠٠ ملغ", (Quantity("500", "mg"),)),
        ("1,000 mg", (Quantity("1000", "mg"),)),
        ("1 000 mg", (Quantity("1000", "mg"),)),
        ("about 10%", (Quantity("10", "%"),)),
        ("10 pour cent", (Quantity("10", "%"),)),
        ("every 4 to 6 hours", (Quantity("4", "h"), Quantity("6", "h"))),
        ("38,5 °C", (Quantity("38.5", "°c"),)),
        ("120 mmHg", (Quantity("120", "mmhg"),)),
        ("2 tablets", (Quantity("2", "tablets"),)),
        ("05 ml", (Quantity("5", "ml"),)),
    ],
)
def test_extract_quantities(text: str, expected: tuple[Quantity, ...]) -> None:
    assert extract_quantities(text) == expected


@pytest.mark.parametrize(
    "text", ["no numbers here", "call 15", "in 2024 the guideline changed", "version 2.1"]
)
def test_numbers_without_units_are_ignored(text: str) -> None:
    assert extract_quantities(text) == ()


def test_grounded_when_quantity_in_a_source() -> None:
    sources = ["Adults: 500 milligrams every 4 to 6 hours."]
    assert ungrounded_quantities("Take 500mg every 4-6 hours [1].", sources) == ()


def test_ungrounded_quantity_reported() -> None:
    sources = ["Adults: 500 mg every 4 to 6 hours."]
    assert ungrounded_quantities("The dose is 1000 mg.", sources) == (Quantity("1000", "mg"),)


def test_sentence_without_quantities_is_grounded() -> None:
    assert ungrounded_quantities("Rest and drink fluids.", []) == ()


def test_quantity_without_any_source_is_ungrounded() -> None:
    assert ungrounded_quantities("about 5 days", []) == (Quantity("5", "d"),)


# ---- review C3 / S13: number words, separators, NxM, rate units, more units, fail closed -------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Take five hundred milligrams", (Quantity("500", "mg"),)),
        ("two hundred and fifty mg", (Quantity("250", "mg"),)),
        ("twenty-five mg", (Quantity("25", "mg"),)),
        ("deux comprimés", (Quantity("2", "tablets"),)),
        ("deux cent cinquante mg", (Quantity("250", "mg"),)),
        ("quatre-vingt-dix mg", (Quantity("90", "mg"),)),
        ("vingt et un jours", (Quantity("21", "d"),)),
        ("خمسة ملغ", (Quantity("5", "mg"),)),
        ("خمسة وعشرون ملغ", (Quantity("25", "mg"),)),
        ("قرصين", (Quantity("2", "tablets"),)),
        ("one tablet", (Quantity("1", "tablets"),)),
        ("half a tablet", (Quantity("0.5", "tablets"),)),
        ("one and a half tablets", (Quantity("1.5", "tablets"),)),
        ("1/2 tablet", (Quantity("0.5", "tablets"),)),
        ("½ tablet", (Quantity("0.5", "tablets"),)),
        ("twice a day", (Quantity("2", "times/d"),)),
        ("four to six hours", (Quantity("4", "h"), Quantity("6", "h"))),
    ],
)
def test_number_words_are_normalised(text: str, expected: tuple[Quantity, ...]) -> None:
    assert extract_quantities(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4x2000mg", (Quantity("2000", "mg"), Quantity("4", "×"))),
        ("2 × 500 mg", (Quantity("500", "mg"), Quantity("2", "×"))),
        ("2 x 500 mg", (Quantity("500", "mg"), Quantity("2", "×"))),
    ],
)
def test_multiplier_forms_are_parsed(text: str, expected: tuple[Quantity, ...]) -> None:
    assert extract_quantities(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10 mg/kg", (Quantity("10", "mg/kg"),)),
        ("10 mg per kg", (Quantity("10", "mg/kg"),)),
        ("15 mg/kg/day", (Quantity("15", "mg/kg/d"),)),
        ("4 g/day", (Quantity("4", "g/d"),)),
        ("4 g per day", (Quantity("4", "g/d"),)),
        ("4 g a day", (Quantity("4", "g/d"),)),
        ("4 g in 24 hours", (Quantity("4", "g/d"),)),
        ("60 mg/m2", (Quantity("60", "mg/m2"),)),
        ("60 mg/m²", (Quantity("60", "mg/m2"),)),
        ("2 ml/h", (Quantity("2", "ml/h"),)),
        ("10 mg par kg", (Quantity("10", "mg/kg"),)),
        ("1 g par jour", (Quantity("1", "g/d"),)),
        ("10 ملغ لكل كغ", (Quantity("10", "mg/kg"),)),
    ],
)
def test_rate_units_stay_in_the_unit(text: str, expected: tuple[Quantity, ...]) -> None:
    assert extract_quantities(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 teaspoons", (Quantity("2", "tsp"),)),
        ("1 tablespoon", (Quantity("1", "tbsp"),)),
        ("3 drops", (Quantity("3", "drops"),)),
        ("2 puffs", (Quantity("2", "puffs"),)),
        ("2 sprays", (Quantity("2", "sprays"),)),
        ("5 cc", (Quantity("5", "ml"),)),
        ("1 sachet", (Quantity("1", "sachets"),)),
        ("20 mEq", (Quantity("20", "meq"),)),
        ("500 mgs", (Quantity("500", "mg"),)),
        ("2 cuillères à café", (Quantity("2", "tsp"),)),
        ("3 gouttes", (Quantity("3", "drops"),)),
        ("ملعقة صغيرة", ()),
        ("2 ملعقة صغيرة", (Quantity("2", "tsp"),)),
    ],
)
def test_more_units(text: str, expected: tuple[Quantity, ...]) -> None:
    assert extract_quantities(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500​mg", (Quantity("500", "mg"),)),
        ("5​00 mg", (Quantity("500", "mg"),)),
        ("0٫5 mg", (Quantity("0.5", "mg"),)),
        ("٠٫٥ ملغ", (Quantity("0.5", "mg"),)),
        ("١٬٠٠٠ ملغ", (Quantity("1000", "mg"),)),
        ("۵۰۰ mg", (Quantity("500", "mg"),)),
        ("５００ｍｇ", (Quantity("500", "mg"),)),
        ("1 000 mg", (Quantity("1000", "mg"),)),
    ],
)
def test_separators_and_invisible_characters(text: str, expected: tuple[Quantity, ...]) -> None:
    assert extract_quantities(text) == expected


def test_rate_unit_is_not_grounded_by_the_bare_unit() -> None:
    assert ungrounded_quantities("Give 10 mg/kg.", ["The dose is 10 mg."]) == (Quantity("10", "mg/kg"),)
    assert ungrounded_quantities("Give 10 mg.", ["The dose is 10 mg/kg."]) == (Quantity("10", "mg"),)


def test_bare_unit_is_grounded_by_a_time_rate() -> None:
    assert ungrounded_quantities("Up to 4 g [1].", ["Adults: up to 4 g per day."]) == ()


def test_multiplier_needs_a_grounded_count() -> None:
    assert ungrounded_quantities("4x2000mg", ["2000 mg up to 4 times a day"]) == ()
    assert ungrounded_quantities("4x2000mg", ["500 mg up to 4 times a day"]) == (Quantity("2000", "mg"),)
    assert ungrounded_quantities("3x500 mg", ["500 mg, 2 tablets"]) == (Quantity("3", "×"),)


def test_number_words_must_be_grounded() -> None:
    sources = ["Adults: 500 mg every 4 to 6 hours."]
    assert ungrounded_quantities("Take five hundred milligrams every four to six hours.", sources) == ()
    assert ungrounded_quantities("Take one thousand milligrams.", sources) == (Quantity("1000", "mg"),)


@pytest.mark.parametrize(
    "sentence",
    [
        "Take 2 every 4 hours.",
        "Give two every four hours.",
        "Take 5OO mg at night.",
        "Prenez 2 le soir.",
        "خذ 2 في الليل.",
        "Take a tablet and a half.",
    ],
)
def test_dosing_verb_with_unparsed_number_fails_closed(sentence: str) -> None:
    sources = ["Adults: 500 mg every 4 hours. 2 tablets. خذ قرص"]
    found = ungrounded_quantities(sentence, sources)
    assert found
    assert any(q.unit == UNPARSED for q in found)


@pytest.mark.parametrize(
    "sentence",
    [
        "Take 500 mg every 4 hours [1].",
        "Fever above 38 °C in 2 out of 3 children [1].",  # no dosing verb: unparsed numbers are not doses
        "In 2024 the guideline changed.",
    ],
)
def test_no_fail_closed_without_dosing_verb_or_unparsed_number(sentence: str) -> None:
    sources = ["Adults: 500 mg every 4 hours. Fever above 38 °C."]
    assert all(q.unit != UNPARSED for q in ungrounded_quantities(sentence, sources))
