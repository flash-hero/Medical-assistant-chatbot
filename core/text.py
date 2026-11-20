"""Unicode hygiene shared by ingestion (corpus) and ingress (user messages).

Two different operations, never mixed up:
  sanitize(text)       -> the text we keep, store and send to the model. Removes invisible / smuggling
                          characters but preserves what Arabic, French and emoji legitimately need.
  detection_form(text) -> an aggressive normalised COPY used only for matching (lexicons, BM25 query
                          side, dedup). Never shown, never sent to the model.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Characters that are always removed by sanitize().
_TAG_BLOCK = (0xE0000, 0xE007F)  # Unicode tags: ASCII smuggling
_VS_SUPPLEMENT = (0xE0100, 0xE01EF)  # variation selectors supplement: byte smuggling
_PRIVATE_USE = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))
_BIDI_CONTROLS = frozenset({0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069})
_INVISIBLES = frozenset(
    {
        0x00AD,  # soft hyphen
        0x180E,  # mongolian vowel separator
        0x200B,  # zero width space
        0x2060,
        0x2061,
        0x2062,
        0x2063,
        0x2064,  # word joiner, invisible operators
        0xFEFF,  # BOM / ZWNBSP
        0x115F,
        0x1160,
        0x3164,
        0xFFA0,  # hangul fillers
        0xFFF9,
        0xFFFA,
        0xFFFB,  # interlinear annotation
        0x034F,  # combining grapheme joiner
    }
)
# Kept on purpose: ZWNJ U+200C and ZWJ U+200D (Arabic/Persian shaping, emoji), LRM U+200E,
# RLM U+200F, ALM U+061C (legitimate direction marks), U+FE0F (emoji presentation, max one in a row).
_KEEP_CONTROLS = frozenset({0x09, 0x0A})
# Every character sanitize() may remove, plus U+FE0F (removed when repeated). Text without any of them skips
# the per-character loop, which was most of the CPU time of a streamed turn (P5 overload profile: the output
# checks sanitize every released delta). tests/core/test_text_sanitize_fast_path.py checks this class
# against _classify for every code point.
_NONCHARACTERS = "".join(f"{chr((p << 16) | 0xFFFE)}{chr((p << 16) | 0xFFFF)}" for p in range(17))
_SUSPECT = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f­͏ᅟᅠ᠎​‪-‮⁠-⁤"
    "⁦-⁩ㅤ-﷐-﷯︀-️﻿ﾠ￹-￻"
    "\U000e0000-\U000e007f\U000e0100-\U000e01ef\U000f0000-\U000ffffd\U00100000-\U0010fffd"
    + _NONCHARACTERS
    + "]"
)

_MULTI_NEWLINES = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+\n")
_SPACES = re.compile(r"[ \t  -   　]+")


@dataclass(frozen=True)
class SanitizeResult:
    text: str
    removed: int
    flags: frozenset[str] = field(default_factory=frozenset)

    @property
    def suspicious(self) -> bool:
        """True when characters typical of smuggling attacks were present."""
        return bool(self.flags & {"tag_chars", "bidi_override", "vs_supplement", "private_use"})


def _in(cp: int, rng: tuple[int, int]) -> bool:
    return rng[0] <= cp <= rng[1]


def _classify(cp: int) -> str | None:
    """Return the removal flag for a code point, or None to keep it."""
    if _in(cp, _TAG_BLOCK):
        return "tag_chars"
    if _in(cp, _VS_SUPPLEMENT):
        return "vs_supplement"
    if any(_in(cp, r) for r in _PRIVATE_USE):
        return "private_use"
    if cp in _BIDI_CONTROLS:
        return "bidi_override"
    if cp in _INVISIBLES:
        return "invisible"
    if 0xFE00 <= cp <= 0xFE0E:
        return "variation_selector"
    if (cp < 0x20 and cp not in _KEEP_CONTROLS) or cp == 0x7F or 0x80 <= cp <= 0x9F:
        return "control"
    if 0xFDD0 <= cp <= 0xFDEF or (cp & 0xFFFE) == 0xFFFE:
        return "noncharacter"
    return None


def sanitize(text: str, *, max_chars: int | None = None) -> SanitizeResult:
    """Remove invisible/smuggling characters; normalise newlines and whitespace runs.

    Does NOT apply NFKC (that would rewrite Arabic presentation forms and ligatures in stored text).
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if _SUSPECT.search(text) is None:  # nothing to remove: the loop below would keep every character
        return _finish(text, 0, set(), max_chars)
    out: list[str] = []
    flags: set[str] = set()
    removed = 0
    prev_fe0f = False
    for ch in text:
        cp = ord(ch)
        flag = _classify(cp)
        if flag is None and cp == 0xFE0F:
            if prev_fe0f:
                flag = "variation_selector"
            prev_fe0f = True
        else:
            prev_fe0f = False if flag is None else prev_fe0f
        if flag is not None:
            flags.add(flag)
            removed += 1
            continue
        out.append(ch)
    return _finish("".join(out), removed, flags, max_chars)


def _finish(cleaned: str, removed: int, flags: set[str], max_chars: int | None) -> SanitizeResult:
    cleaned = _SPACES.sub(" ", cleaned)
    cleaned = _TRAILING_SPACES.sub("\n", cleaned)
    cleaned = _MULTI_NEWLINES.sub("\n\n", cleaned).strip()
    if max_chars is not None and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
        flags.add("truncated")
    return SanitizeResult(text=cleaned, removed=removed, flags=frozenset(flags))


# ---- detection form ----------------------------------------------------------------------------
_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_AR_TATWEEL = "ـ"
_AR_MAP = str.maketrans(
    {
        "أ": "ا",  # أ -> ا
        "إ": "ا",  # إ -> ا
        "آ": "ا",  # آ -> ا
        "ٱ": "ا",  # ٱ -> ا
        "ى": "ي",  # ى -> ي
        "ة": "ه",  # ة -> ه
        "ؤ": "و",  # ؤ -> و
        "ئ": "ي",  # ئ -> ي
        "ی": "ي",  # Persian yeh -> ي
        "ک": "ك",  # keheh -> ك
    }
)
_DIGITS = str.maketrans(
    {**{chr(0x0660 + i): str(i) for i in range(10)}, **{chr(0x06F0 + i): str(i) for i in range(10)}}
)
_JOINERS = re.compile(r"[‌‍‎‏؜️]")
_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")


def strip_latin_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not (unicodedata.combining(c) and ord(c) < 0x0600))


def detection_form(text: str, *, keep_punct: bool = False) -> str:
    """Aggressive normalisation for matching only: NFKC, casefold, Arabic letter folding, no diacritics,
    Arabic-Indic digits -> ASCII, Latin accents stripped, joiners removed, whitespace collapsed."""
    t = sanitize(text).text
    t = unicodedata.normalize("NFKC", t)  # folds Arabic presentation forms and fullwidth Latin
    t = t.casefold()
    t = _AR_DIACRITICS.sub("", t).replace(_AR_TATWEEL, "")
    t = t.translate(_AR_MAP).translate(_DIGITS)
    t = _JOINERS.sub("", t)
    t = strip_latin_accents(t)
    t = unicodedata.normalize("NFC", t)
    if not keep_punct:
        t = _NON_WORD.sub(" ", t)
    return _WS.sub(" ", t).strip()


_ARABIC_LETTER = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ÿ]")
_FR_HINTS = re.compile(
    r"\b(je|j'|tu|il|elle|nous|vous|est|suis|une|des|les|du|pour|avec|mal|douleur|médecin|quoi|"
    r"pourquoi|comment|bonjour|merci|où|quand|ça|pas|très)\b|[éèêàùçôîœ]",
    re.IGNORECASE,
)


def guess_language(text: str) -> str:
    """Cheap EN/FR/AR guess for routing defaults (the router model makes the final call).
    Arabizi (Arabic in Latin letters) is reported as 'en' here; the router handles it."""
    ar = len(_ARABIC_LETTER.findall(text))
    lat = len(_LATIN_LETTER.findall(text))
    if ar and ar >= lat:
        return "ar"
    if _FR_HINTS.search(text):
        return "fr"
    return "en"
