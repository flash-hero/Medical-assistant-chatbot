"""Qdrant Query API requests for hybrid retrieval.

One query_batch_points round trip carries
  [0]   the fused request: prefetch dense (one per query vector) + bm25 (query language and English
        search queries), each limit >= the final limit, fused with RRF at an EXPLICIT k (server default 2)
  [1..] the same dense / sparse searches alone, without payload, to recover per-stage scores for the
        confidence gate (dense cosine) and the sparse-agreement signal.
Every request carries the payload filter, which always excludes reuse_mode=link_only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from core.errors import InvalidInput
from core.schemas.source import ReuseMode
from rag.index import DENSE_VECTOR, INTEGER_INDEXES, KEYWORD_INDEXES
from rag.retrieval_config import RetrievalConfig
from rag.sparse import SparseVec

FILTERABLE = frozenset(KEYWORD_INDEXES) | frozenset(INTEGER_INDEXES)
MAX_FILTER_VALUES = 50
MAX_FILTER_VALUE_CHARS = 200


@dataclass(frozen=True)
class QueryPlan:
    dense: tuple[tuple[float, ...], ...]
    sparse: tuple[tuple[str, SparseVec], ...]  # (named sparse vector, query vector)
    flt: models.Filter


@dataclass(frozen=True)
class Candidate:
    point_id: str
    payload: Mapping[str, Any]
    rrf: float


@dataclass(frozen=True)
class SearchHits:
    fused: tuple[Candidate, ...] = ()
    dense_scores: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    sparse_ids: frozenset[str] = frozenset()


def _filter_values(key: str, values: object) -> list[Any]:
    if not isinstance(values, list) or not values or len(values) > MAX_FILTER_VALUES:
        raise InvalidInput(f"filter {key!r} needs 1..{MAX_FILTER_VALUES} values")
    if key in INTEGER_INDEXES:
        try:
            return [int(v) for v in values]
        except (TypeError, ValueError) as exc:
            raise InvalidInput(f"filter {key!r} takes integers") from exc
    if any(not isinstance(v, str) or not v or len(v) > MAX_FILTER_VALUE_CHARS for v in values):
        raise InvalidInput(f"filter {key!r} takes non-empty strings")
    return [str(v) for v in values]


def build_filter(filters: Mapping[str, list[str]]) -> models.Filter:
    """Validated payload filter. link_only passages can never be returned, whatever the caller asks."""
    must: list[Any] = []
    for key, values in sorted(filters.items()):
        if key not in FILTERABLE:
            raise InvalidInput(f"unsupported retrieval filter {key!r}")
        must.append(models.FieldCondition(key=key, match=models.MatchAny(any=_filter_values(key, values))))
    link_only = models.FieldCondition(
        key="reuse_mode", match=models.MatchValue(value=ReuseMode.LINK_ONLY.value)
    )
    return models.Filter(must=must or None, must_not=[link_only])


def _params(cfg: RetrievalConfig) -> models.SearchParams:
    return models.SearchParams(
        hnsw_ef=cfg.hnsw_ef,
        quantization=models.QuantizationSearchParams(rescore=True, oversampling=cfg.quant_oversampling),
    )


def build_requests(plan: QueryPlan, cfg: RetrievalConfig) -> list[models.QueryRequest]:
    params = _params(cfg)
    prefetch = [
        models.Prefetch(
            query=list(v), using=DENSE_VECTOR, limit=cfg.dense_limit, filter=plan.flt, params=params
        )
        for v in plan.dense
    ] + [
        models.Prefetch(query=sv.to_qdrant(), using=name, limit=cfg.sparse_limit, filter=plan.flt)
        for name, sv in plan.sparse
    ]
    fused = models.QueryRequest(
        prefetch=prefetch,
        query=models.RrfQuery(rrf=models.Rrf(k=cfg.rrf_k)),
        filter=plan.flt,
        limit=cfg.fused_limit,
        with_payload=True,
    )
    dense = [
        models.QueryRequest(
            query=list(v), using=DENSE_VECTOR, limit=cfg.dense_limit, filter=plan.flt, params=params
        )
        for v in plan.dense
    ]
    sparse = [
        models.QueryRequest(query=sv.to_qdrant(), using=name, limit=cfg.sparse_limit, filter=plan.flt)
        for name, sv in plan.sparse
    ]
    return [fused, *dense, *sparse]


async def run_search(
    client: AsyncQdrantClient, collection: str, plan: QueryPlan, cfg: RetrievalConfig
) -> SearchHits:
    if not plan.dense and not plan.sparse:
        return SearchHits()
    responses = await client.query_batch_points(collection, build_requests(plan, cfg))
    fused = tuple(
        Candidate(str(p.id), MappingProxyType(dict(p.payload or {})), float(p.score))
        for p in responses[0].points
    )
    n_dense = len(plan.dense)
    dense_scores: dict[str, float] = {}
    for resp in responses[1 : 1 + n_dense]:
        for p in resp.points:
            pid = str(p.id)
            dense_scores[pid] = max(dense_scores.get(pid, -1.0), float(p.score))
    sparse_ids = frozenset(str(p.id) for resp in responses[1 + n_dense :] for p in resp.points)
    return SearchHits(fused, MappingProxyType(dense_scores), sparse_ids)


def diversify(
    candidates: Sequence[Candidate], *, max_per_doc: int, one_per_parent: bool, limit: int
) -> list[Candidate]:
    """Keep rank order; at most `max_per_doc` chunks per document and (when expanding to the parent
    section) one chunk per parent, since two hits in one section expand to the same text."""
    per_doc: dict[str, int] = {}
    parents: set[str] = set()
    out: list[Candidate] = []
    for cand in candidates:
        if cand.payload.get("reuse_mode") == ReuseMode.LINK_ONLY.value or "doc_id" not in cand.payload:
            continue
        doc, parent = str(cand.payload["doc_id"]), str(cand.payload.get("parent_id", ""))
        if per_doc.get(doc, 0) >= max_per_doc or (one_per_parent and parent in parents):
            continue
        per_doc[doc] = per_doc.get(doc, 0) + 1
        parents.add(parent)
        out.append(cand)
        if len(out) >= limit:
            break
    return out
