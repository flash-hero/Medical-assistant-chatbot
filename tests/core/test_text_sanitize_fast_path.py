"""sanitize()'s fast path (P5 overload profile): text without a removable character skips the per-character
loop. The fast path is only correct if its character class holds every code point the loop could remove."""

from __future__ import annotations

import random

import pytest

from core import text as text_mod
from core.text import sanitize


def test_suspect_class_matches_exactly_the_removable_code_points() -> None:
    """Exhaustive over the whole code space: in the class <=> _classify flags it, or it is U+FE0F."""
    suspect = text_mod._SUSPECT
    wrong = [
        cp
        for cp in range(0x110000)
        if (suspect.match(chr(cp)) is not None) != (text_mod._classify(cp) is not None or cp == 0xFE0F)
    ]
    assert wrong == []


def _slow(value: str, max_chars: int | None = None) -> text_mod.SanitizeResult:
    """The loop path, forced (the class is replaced by one that matches everything)."""
    original = text_mod._SUSPECT
    text_mod._SUSPECT = text_mod.re.compile(r"[\s\S]")
    try:
        return sanitize(value, max_chars=max_chars)
    finally:
        text_mod._SUSPECT = original


@pytest.mark.parametrize(
    "value",
    [
        "What is a fever and how long does it usually last?",
        "Qu'est-ce que la fièvre ?\r\n\r\n\r\n\tet   ensuite  ",
        "ما هي الحمى وكم تدوم عادة؟ ",
        "emoji ❤️ and ZWJ 👩‍⚕️, LRM ‎ RLM ‏",
        "",
        "  \n\n",
    ],
)
def test_fast_path_equals_the_loop_on_clean_text(value: str) -> None:
    assert sanitize(value) == _slow(value)
    assert sanitize(value, max_chars=10) == _slow(value, max_chars=10)


def test_fast_path_equals_the_loop_on_random_text() -> None:
    rng = random.Random(5)
    alphabet = "ab é\n\t\r؟ح‌‍️​‮\U000e0041\x07﻿ "
    for _ in range(2000):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        assert sanitize(value) == _slow(value)
