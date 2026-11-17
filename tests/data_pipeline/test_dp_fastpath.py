"""fast_sanitize / fast_detection_form must be indistinguishable from the core.text functions."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.text import detection_form, sanitize
from data_pipeline.quality.fastpath import fast_detection_form, fast_sanitize

SPECIAL = "​‌‍‮⁦﻿­\U000e0041️\x00\x07\r\t 　"
ALPHABET = st.one_of(
    st.characters(codec="utf-8", exclude_categories=("Cs",)),
    st.sampled_from(list(SPECIAL) + list("aeé ïç\n  -.,") + list("ءأإآةىيكَُِّـ٠١٢٣")),
)
TEXTS = st.text(alphabet=ALPHABET, max_size=80)


@given(TEXTS)
@settings(max_examples=300, deadline=None)
def test_fast_sanitize_matches_core(text: str) -> None:
    assert fast_sanitize(text) == sanitize(text)


@given(TEXTS, st.booleans())
@settings(max_examples=300, deadline=None)
def test_fast_detection_form_matches_core(text: str, keep_punct: bool) -> None:
    assert fast_detection_form(text, keep_punct=keep_punct) == detection_form(text, keep_punct=keep_punct)


@pytest.mark.parametrize(
    "text",
    [
        "Plain ASCII text with  double  spaces\r\nand\ttabs.",
        "Café déjà vu: ÉCOLE, œuvre, naïve",
        "السَّكَّري مرضٌ مزمن ـــ أإآ ى ة",
        "tag \U000e0049\U000e0067 smuggle ‮ rlo",
        "",
        "   \n\n\n\n  x  ",
    ],
)
def test_known_inputs_match_core(text: str) -> None:
    assert fast_sanitize(text) == sanitize(text)
    assert fast_detection_form(text) == detection_form(text)
    assert fast_detection_form(text, keep_punct=True) == detection_form(text, keep_punct=True)
