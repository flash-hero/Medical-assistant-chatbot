"""Text normalisation used only for lexicon matching (never shown, never sent to a model)."""

from __future__ import annotations

import re

from core.text import detection_form

_CLAUSE_PUNCT = re.compile(r"[.!?;:,\n\r،؛؟…]+|\s[-–—]\s")
# English contractions only ("can t" -> "cant", "i m" -> "im"); French elisions ("m ouvrir", "s etouffe") must stay
# separate tokens, so the left-hand word is restricted to English stems.
_NEG_STEMS = "can|don|doesn|didn|isn|wasn|aren|weren|won|wouldn|shouldn|couldn|haven|hasn|hadn|ain|mustn|needn"
_PRONOUNS = "i|you|we|they|he|she|it|that|there|who|what|here|let"
_CONTRACTION = re.compile(rf"\b(?:({_NEG_STEMS}) (t)|({_PRONOUNS}) (m|s|ll|re|ve|d))\b")
_SKELETON_DIGRAPHS = (("gh", "R"), ("kh", "X"), ("ch", "S"), ("sh", "S"), ("dj", "j"), ("ou", "u"))
_SKELETON_CHARS = str.maketrans({"2": "", "3": "", "5": "X", "6": "t", "7": "h", "8": "R", "9": "k", "q": "k", "g": "k"})
_VOWELS = re.compile(r"[aeiouy]")
_REPEATS = re.compile(r"(.)\1+")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """detection_form + English contraction folding ("can t" -> "cant") so lexicon terms and text agree."""
    return _CONTRACTION.sub(lambda m: "".join(g for g in m.groups() if g), detection_form(text))


def split_clauses(text: str) -> list[str]:
    """Split raw text into clauses on punctuation (before normalisation removes it)."""
    return [c for c in _CLAUSE_PUNCT.split(text) if c.strip()]


def arabizi_skeleton(normalized: str) -> str:
    """Consonant skeleton for Arabizi (Arabic in Latin letters + digits): folds digit letters (3, 7, 9 ...),
    common digraphs and vowels, so "ma9dertch netnefes" and "ma9dertch ntnfes" become the same string."""
    s = normalized
    for digraph, repl in _SKELETON_DIGRAPHS:
        s = s.replace(digraph, repl)
    s = s.translate(_SKELETON_CHARS)
    s = _VOWELS.sub("", s)
    s = _REPEATS.sub(r"\1", s)
    return _WS.sub(" ", s).strip()


def tokens(text: str) -> list[str]:
    return text.split()
