"""Number normalisation for matching copies (app/guardrails/numbers.py, review C3 / S3 / C4)."""

from __future__ import annotations

import pytest

from app.guardrails.numbers import ascii_digits, normalise_numbers, strip_format


def test_ascii_digits_is_length_preserving() -> None:
    for raw in ("٩١١", "۰۶۱۲", "０６１２", "call 15"):
        out = ascii_digits(raw)
        assert len(out) == len(raw)
        assert not any(c.isdigit() and not c.isascii() for c in out)
    assert ascii_digits("اتصل ب ٩١١") == "اتصل ب 911"


def test_strip_format_removes_invisible_characters() -> None:
    assert strip_format("5​00‎mg﻿") == "500mg"
    assert strip_format("plain") == "plain"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("two thousand five hundred mg", "2500 mg"),
        ("two thousand and five mg", "2005 mg"),
        ("between two and three days", "between 2 and 3 days"),  # "and" kept between two numbers
        ("deux et trois jours", "2 et 3 jours"),
        ("soixante-quinze mg", "75 mg"),
        ("mille mg", "1000 mg"),
        ("خمسة عشر يوما", "15 يوما"),
        ("ثلاثة وأربعة", "3 و4"),
        ("مائتين وخمسين ملغ", "250 ملغ"),
        ("no one knows", "no one knows"),  # a lone "one" is a pronoun
        ("une semaine", "une semaine"),  # "une" is an article unless a dose unit follows
        ("une gélule", "1 gélule"),
        ("قرص واحد", "1 قرص"),
        ("10 pour cent", "10 %"),
        ("3/2 tablets", "3/2 tablets"),  # not a simple fraction below one
        ("120/80 mmHg", "120/80 mmHg"),
        ("twice daily, thrice weekly", "2 times daily, 3 times weekly"),
        ("نصف قرص", "0.5 قرص"),
        ("demi-comprimé", "0.5 comprimé"),
    ],
)
def test_normalise_numbers(raw: str, expected: str) -> None:
    assert normalise_numbers(raw) == expected
