"""Small-to-big expansion: rebuild a window of a parent section from its overlapping chunks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

MIN_OVERLAP_CHARS = 12
SCROLL_PAGE = 256
_GAP = "\n"


def _overlap(a: str, b: str) -> int:
    """Length of the longest suffix of `a` that is a prefix of `b`, aligned on whitespace boundaries.

    Chunk overlaps are whole sentences, so a real seam always starts after whitespace in `a` and ends
    before whitespace (or the end) in `b`; tiny accidental matches are ignored."""
    for k in range(min(len(a), len(b)), MIN_OVERLAP_CHARS - 1, -1):
        if not a.endswith(b[:k]):
            continue
        starts_clean = k == len(a) or a[-k - 1].isspace()
        ends_clean = k == len(b) or b[k].isspace()
        if starts_clean and ends_clean:
            return k
    return 0


def merge_overlapping(texts: Sequence[str]) -> str:
    """Join consecutive chunk texts of one section, dropping the duplicated overlap at each seam."""
    if not texts:
        return ""
    merged = texts[0]
    for nxt in texts[1:]:
        k = _overlap(merged[-len(nxt) - 1 :] if len(merged) > len(nxt) else merged, nxt)
        merged = merged + nxt[k:] if k else merged + _GAP + nxt
    return merged


@dataclass(frozen=True)
class Sibling:
    ordinal: int
    text: str
    tokens: int


@dataclass(frozen=True)
class Expansion:
    text: str
    ordinals: tuple[int, ...]
    tokens: int


def expand_window(siblings: Sequence[Sibling], hit_ordinal: int, budget_tokens: int) -> Expansion:
    """Grow a window around the hit chunk (next, then previous, alternating) while it fits the budget.
    The hit chunk itself is always included, even when it alone exceeds the budget."""
    by_ord = {s.ordinal: s for s in siblings}
    hit = by_ord.get(hit_ordinal)
    if hit is None:
        raise ValueError(f"hit ordinal {hit_ordinal} not among siblings")
    lo = hi = hit_ordinal
    used = hit.tokens
    grew = True
    while grew:
        grew = False
        for cand in (hi + 1, lo - 1):
            sib = by_ord.get(cand)
            if sib is None or used + sib.tokens > budget_tokens:
                continue
            used += sib.tokens
            lo, hi = min(lo, cand), max(hi, cand)
            grew = True
    ordinals = tuple(o for o in range(lo, hi + 1) if o in by_ord)
    text = merge_overlapping([by_ord[o].text for o in ordinals])
    return Expansion(text=text, ordinals=ordinals, tokens=used)


async def fetch_siblings(
    client: AsyncQdrantClient, collection: str, parent_ids: Sequence[str]
) -> dict[str, list[Sibling]]:
    """All chunks of the given parent sections (one filtered scroll, paginated), ordered by ordinal."""
    if not parent_ids:
        return {}
    flt = models.Filter(
        must=[
            models.FieldCondition(key="parent_id", match=models.MatchAny(any=list(dict.fromkeys(parent_ids))))
        ]
    )
    found: dict[str, list[Sibling]] = {}
    offset: Any = None
    while True:
        records, offset = await client.scroll(
            collection,
            scroll_filter=flt,
            limit=SCROLL_PAGE,
            offset=offset,
            with_payload=["parent_id", "ordinal", "text", "token_estimate"],
            with_vectors=False,
        )
        for rec in records:
            pl = rec.payload or {}
            sib = Sibling(int(pl["ordinal"]), str(pl["text"]), int(pl["token_estimate"]))
            found.setdefault(str(pl["parent_id"]), []).append(sib)
        if offset is None:
            return {k: sorted(v, key=lambda s: s.ordinal) for k, v in found.items()}
