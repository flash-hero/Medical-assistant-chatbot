"""Language-aware segmentation of a section's text into atomic units (EN / FR / AR).

A unit is a span [start, end) of the original text, so chunks are exact substrings of the source and
nothing is rewritten. Units are sentences, whole "- " lists (with their ":" lead-in sentence) or whole
tables. Anything longer than `max_unit_tokens` is split at the gentlest boundary available: list items or
table rows first, then soft punctuation (; : , and Arabic ؛ ،), then whitespace.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from rag.tokens import chars_per_token, estimate_tokens

DEFAULT_MAX_UNIT_TOKENS = 500
LEAD_IN_RESERVE_DIVISOR = 5  # oversized lists/tables are split to 80% of max so a lead-in still fits

# Sentence terminators: Latin . ! ? … plus Arabic question mark U+061F and Arabic full stop U+06D4.
_CANDIDATE = re.compile(r"([.!?…؟۔]+)([\"'”’»)\]]*)(\s+)")
_SOFT = re.compile(r"[;؛:,،](?=\s)")
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*•–]|\d{1,3}[.)])[ \t]+\S")
_INITIALISM = re.compile(r"(?:[^\W\d_]\.)+[^\W\d_]")

_ABBREV_COMMON = frozenset({"dr", "st", "no", "etc", "vs", "fig", "vol", "approx", "ca", "cf"})
_ABBREV: dict[str, frozenset[str]] = {
    "en": _ABBREV_COMMON
    | {"e.g", "i.e", "mr", "mrs", "ms", "prof", "inc", "ltd", "jr", "sr", "al", "dept", "min", "max"},
    "fr": _ABBREV_COMMON
    | {"m", "mme", "mlle", "pr", "p", "ex", "env", "art", "chap", "av", "apr", "j.-c", "réf", "tél"},
    "ar": _ABBREV_COMMON | {"e.g", "i.e", "mr", "mrs"},
}


@dataclass(frozen=True, slots=True)
class Unit:
    start: int
    end: int
    kind: str  # "sentence" | "list" | "table" | "fragment"
    tokens: int


Span = tuple[int, int]


def _trim(text: str, start: int, end: int) -> Span:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _tokens(text: str, span: Span, lang: str) -> int:
    return estimate_tokens(text[span[0] : span[1]], lang)


# ---- sentences ---------------------------------------------------------------------------------------
def _is_boundary(text: str, seg_start: int, m: re.Match[str], lang: str) -> bool:
    if text[m.end(3)].islower():
        return False  # "e.g. the", "approx. three" (Arabic letters have no case: always a boundary)
    if m.group(1) != ".":
        return True
    before = text[seg_start : m.start(1)].rsplit(None, 1)
    if not before:
        return False
    word = before[-1].casefold().lstrip("(\"'«“")
    if word in _ABBREV.get(lang, _ABBREV_COMMON):
        return False
    if len(word) == 1 and word.isalpha():
        return False  # initials: "J. Doe", "vitamin D." is the accepted false negative
    return not _INITIALISM.fullmatch(word)  # "U.S", "p.ex"


def split_sentences(text: str, start: int, end: int, lang: str) -> list[Span]:
    spans: list[Span] = []
    seg_start = start
    for m in _CANDIDATE.finditer(text, start, end):
        if m.end(3) >= end or not _is_boundary(text, seg_start, m, lang):
            continue
        spans.append(_trim(text, seg_start, m.end(2)))
        seg_start = m.end(3)
    spans.append(_trim(text, seg_start, end))
    return [s for s in spans if s[1] > s[0]]


# ---- oversized pieces --------------------------------------------------------------------------------
def _pack(text: str, spans: list[Span], max_tokens: int, lang: str) -> list[Span]:
    """Greedily merge consecutive spans while the merged span stays within max_tokens."""
    out: list[Span] = []
    for span in spans:
        if out and _tokens(text, (out[-1][0], span[1]), lang) <= max_tokens:
            out[-1] = (out[-1][0], span[1])
        else:
            out.append(span)
    return out


def _split_words(text: str, span: Span, max_tokens: int, lang: str) -> list[Span]:
    max_chars = max(1, int(max_tokens * chars_per_token(lang)))
    out: list[Span] = []
    start, end = span
    while start < end:
        if end - start <= max_chars:
            out.append((start, end))
            break
        cut = text.rfind(" ", start, start + max_chars + 1)
        if cut <= start:
            cut = start + max_chars
        out.append(_trim(text, start, cut))
        start = _trim(text, cut, end)[0]
    return [s for s in out if s[1] > s[0]]


def split_long(text: str, span: Span, max_tokens: int, lang: str) -> list[Span]:
    """Split one over-long span at soft punctuation, then at whitespace."""
    if _tokens(text, span, lang) <= max_tokens:
        return [span]
    pieces: list[Span] = []
    pos = span[0]
    for m in _SOFT.finditer(text, span[0], span[1]):
        pieces.append(_trim(text, pos, m.end()))
        pos = m.end()
    pieces.append(_trim(text, pos, span[1]))
    fine: list[Span] = []
    for piece in (p for p in pieces if p[1] > p[0]):
        fine.extend(_split_words(text, piece, max_tokens, lang))
    return _pack(text, fine, max_tokens, lang)


# ---- runs: prose / list / table ----------------------------------------------------------------------
def _line_kind(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "blank"
    if stripped.count("|") >= 2 or " | " in stripped or "\t" in stripped:
        return "table"  # data_pipeline renders table rows as "cell | cell"
    if _LIST_ITEM.match(line):
        return "list"
    return "prose"


def _runs(text: str) -> list[tuple[str, list[Span]]]:
    """Group lines into runs of the same kind; list items keep their indented continuation lines."""
    runs: list[tuple[str, list[Span]]] = []
    pos = 0
    for raw in text.split("\n"):
        line_span = (pos, pos + len(raw))
        pos += len(raw) + 1
        kind = _line_kind(raw)
        if kind == "blank":
            runs.append(("blank", []))
            continue
        prev_kind = runs[-1][0] if runs else "blank"
        continuation = kind == "prose" and prev_kind == "list" and raw[:1] in (" ", "\t")
        if continuation:
            last = runs[-1][1]
            last[-1] = (last[-1][0], line_span[1])
        elif kind == prev_kind and kind != "prose":
            runs[-1][1].append(line_span)
        elif kind == prev_kind:
            runs[-1][1][-1] = (runs[-1][1][-1][0], line_span[1])
        else:
            runs.append((kind, [line_span]))
    return [(k, spans) for k, spans in runs if k != "blank"]


def _block_units(text: str, kind: str, items: list[Span], max_tokens: int, lang: str) -> list[Unit]:
    whole = _trim(text, items[0][0], items[-1][1])
    if _tokens(text, whole, lang) <= max_tokens:
        return [Unit(whole[0], whole[1], kind, _tokens(text, whole, lang))]
    budget = max(1, max_tokens - max_tokens // LEAD_IN_RESERVE_DIVISOR)  # room for a ":" lead-in
    pieces: list[Span] = []
    for item in items:
        pieces.extend(split_long(text, _trim(text, *item), budget, lang))
    return [Unit(s, e, kind, _tokens(text, (s, e), lang)) for s, e in _pack(text, pieces, budget, lang)]


def _prose_units(text: str, span: Span, max_tokens: int, lang: str) -> list[Unit]:
    units: list[Unit] = []
    for sent in split_sentences(text, span[0], span[1], lang):
        parts = split_long(text, sent, max_tokens, lang)
        kind = "sentence" if len(parts) == 1 else "fragment"
        units.extend(Unit(s, e, kind, _tokens(text, (s, e), lang)) for s, e in parts)
    return units


def _attach_lead_ins(text: str, units: list[Unit], max_tokens: int, lang: str) -> list[Unit]:
    """'Symptoms include:' followed by a list or table becomes part of that block."""
    out: list[Unit] = []
    for unit in units:
        prev = out[-1] if out else None
        joinable = (
            prev is not None
            and prev.kind in ("sentence", "fragment")
            and unit.kind in ("list", "table")
            and text[prev.start : prev.end].endswith(":")
            and _tokens(text, (prev.start, unit.end), lang) <= max_tokens
        )
        if joinable and prev is not None:
            out[-1] = Unit(prev.start, unit.end, unit.kind, _tokens(text, (prev.start, unit.end), lang))
        else:
            out.append(unit)
    return out


def segment(text: str, lang: str, *, max_unit_tokens: int = DEFAULT_MAX_UNIT_TOKENS) -> tuple[Unit, ...]:
    """Split text into ordered, non-overlapping units separated only by whitespace."""
    builders: dict[str, Callable[[list[Span]], list[Unit]]] = {
        "prose": lambda spans: _prose_units(text, spans[0], max_unit_tokens, lang),
        "list": lambda spans: _block_units(text, "list", spans, max_unit_tokens, lang),
        "table": lambda spans: _block_units(text, "table", spans, max_unit_tokens, lang),
    }
    units: list[Unit] = []
    for kind, spans in _runs(text):
        units.extend(builders[kind](spans))
    return tuple(_attach_lead_ins(text, units, max_unit_tokens, lang))
