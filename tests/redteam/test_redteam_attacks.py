"""The templated red-team attack set (evals/redteam/attacks.py): size, determinism, coverage, encodings."""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Any

import pytest

from evals.redteam.attacks import (
    FAMILIES,
    GENERATED_FAMILIES,
    TARGET_PER_LANG,
    between_letters,
    build_attacks,
    fullwidth,
    presentation_forms,
    tag_encode,
    vs_encode,
)
from evals.redteam.banks import LANGS

ATTACKS = build_attacks()


def test_six_hundred_attacks_two_hundred_per_language() -> None:
    assert len(ATTACKS) == 600
    assert Counter(a.lang for a in ATTACKS) == dict.fromkeys(LANGS, TARGET_PER_LANG)
    assert len({a.id for a in ATTACKS}) == len(ATTACKS)


def test_the_set_is_deterministic() -> None:
    assert build_attacks() == ATTACKS


def test_every_family_is_present_in_every_language() -> None:
    for lang in LANGS:
        families = {a.family for a in ATTACKS if a.lang == lang}
        assert families == set(FAMILIES), lang
        for family in GENERATED_FAMILIES:
            assert sum(1 for a in ATTACKS if a.lang == lang and a.family == family) >= 9


def test_seed_set_is_reused_whole() -> None:
    seeds = [a for a in ATTACKS if a.family == "seed_set"]
    assert len(seeds) == 184
    assert all(a.source.startswith("evals/safety/sets/") for a in seeds)


def test_multi_turn_attacks_have_four_turns_and_planted_attacks_a_passage() -> None:
    for a in ATTACKS:
        if a.family == "multi_turn":
            assert len(a.turns) == 4
        if a.family == "planted_chunk":
            assert a.planted
            assert len(a.turns) == 1
        else:
            assert a.planted is None
        assert all(t.strip() for t in a.turns)
        assert "{goal}" not in a.message
        assert "{Goal}" not in a.message


@pytest.mark.parametrize(
    ("family", "predicate"),
    [
        ("unicode_tags", lambda s: any(0xE0020 <= ord(c) <= 0xE007E for c in s)),
        ("bidi", lambda s: any(c in s for c in "\u202d\u202e\u2067")),
        ("zero_width", lambda s: any(c in s for c in "\u200b\u200c\u2060\u00ad")),
        (
            "variation_selector",
            lambda s: any(0xFE00 <= ord(c) <= 0xFE0F or 0xE0100 <= ord(c) <= 0xE01EF for c in s),
        ),
    ],
)
def test_smuggling_families_carry_their_characters(family: Any, predicate: Any) -> None:
    items = [a for a in ATTACKS if a.family == family]
    assert items
    assert all(predicate(a.message) for a in items)


def test_presentation_forms_fold_back_to_the_attack() -> None:
    ar = [a for a in ATTACKS if a.family == "presentation_forms" and a.lang == "ar"]
    assert all(any(0xFE70 <= ord(c) <= 0xFEFF for c in a.message) for a in ar)
    latin = [a for a in ATTACKS if a.family == "presentation_forms" and a.lang != "ar"]
    assert all(any(0xFF01 <= ord(c) <= 0xFF5E for c in a.message) for a in latin)
    assert unicodedata.normalize("NFKC", presentation_forms("تجاهل التعليمات")) == "تجاهل التعليمات"
    assert unicodedata.normalize("NFKC", fullwidth("Ignore all")).replace("\u3000", " ") == "Ignore all"


def test_encoders() -> None:
    assert "".join(chr(ord(c) - 0xE0000) for c in tag_encode("hi!")) == "hi!"
    assert tag_encode("é") == ""  # the tag block only carries ASCII
    assert vs_encode(b"\x00\x10\xff") == "\ufe00\U000e0100\U000e01ef"
    assert between_letters("ab c", "|") == "a|b c"
