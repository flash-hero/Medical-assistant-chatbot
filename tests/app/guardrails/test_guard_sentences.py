"""Sentence segmentation and the streaming sentence buffer (app/guardrails/sentences.py)."""

from __future__ import annotations

import pytest

from app.guardrails.sentences import Sentence, SentenceBuffer, split_sentences


def _texts(text: str) -> list[str]:
    return [s.text for s in split_sentences(text)]


def test_split_simple() -> None:
    assert _texts("Fever is common. Rest helps! Is it serious?") == [
        "Fever is common.",
        "Rest helps!",
        "Is it serious?",
    ]


def test_citation_markers_stay_with_their_sentence() -> None:
    assert _texts("Fever is common. [1] Rest helps [2]. Drink water.") == [
        "Fever is common. [1]",
        "Rest helps [2].",
        "Drink water.",
    ]


def test_abbreviations_and_decimals_do_not_split() -> None:
    assert _texts("See Dr. Smith, e.g. on Monday. The dose is 2.5 mg.") == [
        "See Dr. Smith, e.g. on Monday.",
        "The dose is 2.5 mg.",
    ]


def test_newlines_end_sentences_and_separators_are_kept() -> None:
    sentences = split_sentences("Title\n\n- item one\n- item two")
    assert [s.text for s in sentences] == ["Title", "- item one", "- item two"]
    assert [s.separator for s in sentences] == ["\n\n", "\n", ""]
    assert "".join(s.rendered for s in sentences) == "Title\n\n- item one\n- item two"


def test_arabic_and_french_punctuation() -> None:
    assert _texts("ما هي الحمى؟ الحمى شائعة. « Bien sûr » dit-il.") == [
        "ما هي الحمى؟",
        "الحمى شائعة.",
        "« Bien sûr » dit-il.",
    ]


def test_closing_quote_stays_with_sentence() -> None:
    assert _texts('He said "stop." Then left.') == ['He said "stop."', "Then left."]


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_empty(text: str) -> None:
    assert split_sentences(text) == []


def test_text_without_terminal_punctuation() -> None:
    assert split_sentences("no full stop here") == [Sentence("no full stop here", "")]


def test_buffer_releases_complete_sentences_only() -> None:
    buf = SentenceBuffer()
    assert buf.feed("Fever is com") == []
    assert buf.feed("mon.") == []  # the separator has not arrived yet
    assert buf.feed(" ") == []  # the separator may continue in the next chunk
    assert buf.feed("Rest") == [Sentence("Fever is common.", " ")]
    out = buf.feed(" helps. Drink")
    assert [s.text for s in out] == ["Rest helps."]
    assert buf.flush() == [Sentence("Drink", "")]
    assert buf.flush() == []


def test_buffer_matches_split_on_any_chunking() -> None:
    text = "One fact [1]. Two facts!\n\nThree? Four is 2.5 mg. Five"
    for size in (1, 3, 7, 50):
        buf = SentenceBuffer()
        got: list[Sentence] = []
        for i in range(0, len(text), size):
            got.extend(buf.feed(text[i : i + size]))
        got.extend(buf.flush())
        assert [s.text for s in got] == _texts(text), size


def test_buffer_releases_runaway_sentence() -> None:
    buf = SentenceBuffer(max_pending_chars=20)
    out = buf.feed("a" * 30)
    assert out == [Sentence("a" * 30, " ")]
    assert buf.flush() == []
