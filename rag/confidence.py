"""Confidence gate: decides whether retrieval supports an answer (False -> the engine abstains).

Signals
  dense_top         best dense cosine among the returned passages (semantic match strength)
  lexical_coverage  share of the query's content terms (stemmed, stopwords removed) found in one of the
                    top passages, best over the query and its English search queries; catches confident-
                    looking dense matches for unknown entities ("side effects of zorvalimab")
  sparse_agreement  share of the top-3 passages that BM25 also retrieved
  rerank_top        best rerank score in [0, 1] (only when the reranker ran)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from rag.retrieval_config import ConfidenceModel

DEGRADED_MIN_COVERAGE = 0.75


@dataclass(frozen=True)
class Signals:
    dense_top: float
    lexical_coverage: float
    sparse_agreement: float
    rerank_top: float | None = None
    degraded: bool = False  # dense retrieval unavailable (query embedding failed)

    def features(self) -> dict[str, float | None]:
        data = asdict(self)
        data.pop("degraded")
        return data


@dataclass(frozen=True)
class Verdict:
    confident: bool
    confidence: float


def lexical_coverage(query_terms: Sequence[frozenset[str]], passage_terms: Sequence[frozenset[str]]) -> float:
    best = 0.0
    for q in query_terms:
        if not q:
            continue
        for p in passage_terms:
            best = max(best, len(q & p) / len(q))
    return best


def sparse_agreement(top_ids: Sequence[str], sparse_ids: frozenset[str], n: int = 3) -> float:
    head = list(top_ids[:n])
    if not head:
        return 0.0
    return sum(1 for pid in head if pid in sparse_ids) / len(head)


def decide(model: ConfidenceModel, signals: Signals, language: str, *, has_passages: bool) -> Verdict:
    if not has_passages:
        return Verdict(False, 0.0)
    if signals.degraded:
        # No dense signal: answer only on a strong lexical match, never above 0.8 confidence.
        ok = signals.lexical_coverage >= DEGRADED_MIN_COVERAGE
        return Verdict(ok, round(0.8 * signals.lexical_coverage, 4))
    p = model.probability(signals.features(), language)
    return Verdict(p >= model.threshold, round(p, 4))
