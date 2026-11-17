"""Ranking and latency metrics (pure functions, binary relevance, gold chunks as ALTERNATIVES).

A ranked list is a sequence of "covered sets": for each returned passage, the chunk ids whose text it
contains (one id without small-to-big expansion, the window's ids with it). Each gold question has one
answer passage; `gold` holds its chunk id plus the ids of exact duplicates of that text in other documents
(MedlinePlus repeats sections such as "What is leukemia?" across pages). A passage is relevant when it
covers any gold id, so:

  recall@k  share of questions whose answer is covered by the top-k passages (top-k accuracy)
  MRR       1 / rank of the first relevant passage
  nDCG@k    binary gain, single relevant item: 1 / log2(1 + rank of the first relevant passage) within k
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence

Ranked = Sequence[Collection[str]]


def first_hit(ranked: Ranked, gold: Collection[str], k: int | None = None) -> int | None:
    """1-based rank of the first passage covering a gold id (None when absent from the top k)."""
    if not gold:
        raise ValueError("a gold question needs at least one answer chunk")
    head = ranked if k is None else ranked[:k]
    for rank, covered in enumerate(head, start=1):
        if any(cid in gold for cid in covered):
            return rank
    return None


def recall_at_k(ranked: Ranked, gold: Collection[str], k: int) -> float:
    return 0.0 if first_hit(ranked, gold, k) is None else 1.0


def reciprocal_rank(ranked: Ranked, gold: Collection[str], k: int | None = None) -> float:
    rank = first_hit(ranked, gold, k)
    return 0.0 if rank is None else 1.0 / rank


def ndcg_at_k(ranked: Ranked, gold: Collection[str], k: int) -> float:
    rank = first_hit(ranked, gold, k)
    return 0.0 if rank is None else 1.0 / math.log2(rank + 1)


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0, 100]), like numpy's default."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in [0, 100]")
    data = sorted(values)
    pos = (len(data) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
