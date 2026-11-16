"""Numeric grounding (app/guardrails/numeric.py)."""

from __future__ import annotations

import pytest

from app.guardrails.numeric import Quantity, extract_quantities, ungrounded_quantities


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
