"""Deterministic token estimate (no tokenizer download): characters per token by language.

Calibrated loosely on SentencePiece-style tokenizers: English ~4 chars/token, French slightly denser,
Arabic ~3 chars/token. Used for chunk sizing and context budgets, never for billing.
"""

from __future__ import annotations

import math

_CHARS_PER_TOKEN: dict[str, float] = {"en": 4.0, "fr": 3.6, "es": 3.8, "ar": 3.0}
_DEFAULT_CHARS_PER_TOKEN = 3.5


def chars_per_token(language: str) -> float:
    return _CHARS_PER_TOKEN.get(str(language), _DEFAULT_CHARS_PER_TOKEN)


def estimate_tokens(text: str, language: str = "en") -> int:
    return max(1, math.ceil(len(text) / chars_per_token(language)))


def truncate_to_tokens(text: str, max_tokens: int, language: str = "en") -> str:
    """Cut text to about max_tokens, at a word boundary when one is close."""
    limit = int(max_tokens * chars_per_token(language))
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.8:
        cut = cut[:space]
    return cut.rstrip() + " …"
