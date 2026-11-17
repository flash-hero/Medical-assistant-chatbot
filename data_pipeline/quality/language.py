"""Cheap, dependency-free language check: script ratio for Arabic, stopword profiles for EN / FR / ES.

Returns "unknown" when the text is too short to judge, so short snippets are never rejected on a guess.
"""

from __future__ import annotations

import re
from collections import Counter

_AR_LETTER = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")
_WORD = re.compile(r"[a-zA-ZÀ-ɏ']+")

_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        [
            "the",
            "of",
            "and",
            "to",
            "in",
            "is",
            "are",
            "for",
            "with",
            "that",
            "this",
            "you",
            "your",
            "it",
            "as",
            "on",
            "be",
            "can",
            "or",
            "may",
            "if",
            "from",
            "by",
            "at",
            "an",
            "not",
            "have",
            "has",
            "which",
            "when",
            "will",
            "more",
            "most",
            "also",
            "than",
            "these",
            "those",
            "other",
            "about",
            "into",
            "such",
            "should",
            "would",
            "could",
            "their",
            "they",
            "them",
            "what",
            "who",
            "how",
            "but",
            "was",
            "were",
            "been",
            "being",
            "do",
            "does",
        ]
    ),
    "fr": frozenset(
        [
            "le",
            "la",
            "les",
            "des",
            "du",
            "de",
            "un",
            "une",
            "et",
            "est",
            "sont",
            "pour",
            "avec",
            "que",
            "qui",
            "dans",
            "sur",
            "par",
            "au",
            "aux",
            "ce",
            "cette",
            "ces",
            "vous",
            "votre",
            "vos",
            "il",
            "elle",
            "ils",
            "elles",
            "ne",
            "pas",
            "plus",
            "ou",
            "ainsi",
            "peut",
            "peuvent",
            "etre",
            "être",
            "avoir",
            "ont",
            "a",
            "été",
            "sans",
            "entre",
            "sous",
            "aussi",
            "mais",
            "nous",
            "leur",
            "leurs",
            "son",
            "sa",
            "ses",
            "se",
            "si",
            "en",
            "y",
            "comme",
            "très",
            "tout",
            "tous",
            "toute",
            "toutes",
            "dont",
            "où",
            "lors",
            "quand",
        ]
    ),
    "es": frozenset(
        [
            "el",
            "la",
            "los",
            "las",
            "de",
            "del",
            "un",
            "una",
            "y",
            "es",
            "son",
            "para",
            "con",
            "que",
            "en",
            "por",
            "al",
            "se",
            "su",
            "sus",
            "lo",
            "como",
            "más",
            "pero",
            "sobre",
            "puede",
            "pueden",
            "ser",
            "tiene",
            "tienen",
            "este",
            "esta",
            "estos",
            "estas",
            "muy",
            "también",
            "si",
            "no",
            "hay",
            "entre",
            "sin",
            "cuando",
            "donde",
            "usted",
            "tambien",
            "desde",
            "hasta",
        ]
    ),
}
_MIN_LETTERS = 40
_MIN_WORDS = 8


def arabic_ratio(text: str) -> float:
    ar = len(_AR_LETTER.findall(text))
    latin = len(_LATIN_LETTER.findall(text))
    total = ar + latin
    return ar / total if total else 0.0


def detect_language(text: str) -> str:
    """'ar' | 'en' | 'fr' | 'es' | 'unknown'."""
    letters = len(_AR_LETTER.findall(text)) + len(_LATIN_LETTER.findall(text))
    if letters < _MIN_LETTERS:
        return "unknown"
    if arabic_ratio(text) >= 0.5:
        return "ar"
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < _MIN_WORDS:
        return "unknown"
    counts = Counter(words)
    scores = {lang: sum(counts[w] for w in vocab) / len(words) for lang, vocab in _STOPWORDS.items()}
    best, runner_up = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:2]
    if best[1] < 0.08:
        return "unknown"
    # Drug names and Latin terms are language-neutral, so require a clear margin over the runner-up.
    return best[0] if best[1] >= runner_up[1] * 1.25 else "unknown"


def matches_language(text: str, expected: str) -> bool:
    """True unless the text is confidently a *different* language than expected."""
    detected = detect_language(text)
    return detected in ("unknown", expected)
