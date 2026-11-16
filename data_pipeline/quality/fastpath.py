"""Fast, behaviour-identical versions of core.text.sanitize() and core.text.detection_form().

core.text walks the text one character at a time in Python, roughly 150 KB/s: far too slow for the hundreds of
MB of corpus text the quality gates scan. The results below are identical to core.text for every input
(tests/data_pipeline/test_dp_fastpath.py checks this with Hypothesis); only the strategy differs:

  * sanitize: if the text contains none of the code points the core removes, the per-character walk is a no-
  op,
    so only the whitespace regexes run. Otherwise the call is delegated to core.text.sanitize().
  * detection_form: the same pipeline as the core, but accent stripping touches only the non-ASCII runs.
"""

from __future__ import annotations

import re
import unicodedata

from core.text import (
    _AR_DIACRITICS,
    _AR_MAP,
    _AR_TATWEEL,
    _DIGITS,
    _JOINERS,
    _MULTI_NEWLINES,
    _NON_WORD,
    _SPACES,
    _TRAILING_SPACES,
    _WS,
    SanitizeResult,
    sanitize,
    strip_latin_accents,
)

_NONCHARACTERS = "".join(chr(plane * 0x10000 + low) for plane in range(17) for low in (0xFFFE, 0xFFFF))
_SPECIAL = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"  # controls (tab and newline are kept; carriage returns are folded first)  # noqa: E501
    "­͏ᅟᅠ᠎​⁠-⁤‪-‮⁦-⁩"  # invisibles, bidi controls
    "︀-️﻿ㅤﾠ￹-￻﷐-﷯"  # variation selectors, fillers, annotations
    "-\U000e0000-\U000e007f\U000e0100-\U000e01ef\U000f0000-\U000ffffd\U00100000-\U0010fffd"
    f"{_NONCHARACTERS}]"
)
_NON_ASCII_RUN = re.compile(r"[^\x00-\x7f]+")


def fast_sanitize(text: str) -> SanitizeResult:
    """Same result as core.text.sanitize(text)."""
    folded = text.replace("\r\n", "\n").replace("\r", "\n")
    if _SPECIAL.search(folded):
        return sanitize(text)
    cleaned = _SPACES.sub(" ", folded)
    cleaned = _TRAILING_SPACES.sub("\n", cleaned)
    cleaned = _MULTI_NEWLINES.sub("\n\n", cleaned).strip()
    return SanitizeResult(text=cleaned, removed=0, flags=frozenset())


def _strip_accents(text: str) -> str:
    if text.isascii():
        return text
    return _NON_ASCII_RUN.sub(lambda m: strip_latin_accents(m.group()), text)


def fast_detection_form(text: str, *, keep_punct: bool = False) -> str:
    """Same result as core.text.detection_form(text, keep_punct=keep_punct)."""
    t = fast_sanitize(text).text
    if not t.isascii():
        t = unicodedata.normalize("NFKC", t)
    t = t.casefold()
    if not t.isascii():
        t = _AR_DIACRITICS.sub("", t).replace(_AR_TATWEEL, "")
        t = t.translate(_AR_MAP).translate(_DIGITS)
        t = _JOINERS.sub("", t)
        t = _strip_accents(t)
        t = unicodedata.normalize("NFC", t)
    if not keep_punct:
        t = _NON_WORD.sub(" ", t)
    return _WS.sub(" ", t).strip()
