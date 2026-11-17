from types import MappingProxyType

import pytest
from qdrant_client import models

from core.errors import InvalidInput
from rag.retrieval_config import RetrievalConfig
from rag.search import (
    FUSED_TIE_MARGIN,
    Candidate,
    QueryPlan,
    build_filter,
    build_requests,
    diversify,
    order_fused,
)
from rag.sparse import SparseVec


def test_fused_order_breaks_rrf_ties_deterministically_then_cuts():
    def c(pid: str, rrf: float) -> Candidate:
        return Candidate(pid, MappingProxyType({}), rrf)

    tie = 1 / 61 + 1 / 70
    server_order_1 = [c("b", tie), c("a", tie + 1e-17), c("top", 0.5), c("d", tie), c("low", 0.001)]
    server_order_2 = list(reversed(server_order_1))
    dense = {"a": 0.71, "b": 0.74, "top": 0.8}  # "d" has no dense score: ranked after tied dense hits
    first = order_fused(server_order_1, dense, limit=4)
    assert [x.point_id for x in first] == ["top", "b", "a", "d"]
    assert order_fused(server_order_2, dense, limit=4) == first
    assert [x.point_id for x in order_fused(server_order_1, {}, limit=3)] == ["top", "a", "b"]  # id breaks


def cand(pid: str, doc: str, parent: str, reuse: str = "paraphrase_ok") -> Candidate:
    payload = {"doc_id": doc, "parent_id": parent, "reuse_mode": reuse, "chunk_id": pid}
    return Candidate(pid, MappingProxyType(payload), 0.1)


def test_filter_always_excludes_link_only_and_validates_keys():
    flt = build_filter({})
    assert flt.must is None
    assert flt.must_not[0].key == "reuse_mode"
    assert flt.must_not[0].match.value == "link_only"
    flt = build_filter({"language": ["en", "fr"], "trust_tier": ["1", 2]})
    keys = {c.key: c.match.any for c in flt.must}
    assert keys == {"language": ["en", "fr"], "trust_tier": [1, 2]}
    with pytest.raises(InvalidInput, match="unsupported"):
        build_filter({"text": ["x"]})
    with pytest.raises(InvalidInput):
        build_filter({"language": ["x" * 201]})
    with pytest.raises(InvalidInput):
        build_filter({"language": "en"})  # not a list
    with pytest.raises(InvalidInput):
        build_filter({"language": ["en"] * 51})


def test_requests_use_explicit_rrf_k_and_prefetch_limits_at_least_the_final_limit():
    plan = QueryPlan(
        dense=((0.1,) * 4, (0.2,) * 4),
        sparse=(("bm25_fr", SparseVec((1, 5), (1.0, 1.0))), ("bm25_en", SparseVec((2,), (1.0,)))),
        flt=build_filter({}),
    )
    cfg = RetrievalConfig()
    fused, *singles = build_requests(plan, cfg)
    assert isinstance(fused.query, models.RrfQuery)
    assert fused.query.rrf.k == 60
    assert len(fused.prefetch) == 4
    assert [p.using for p in fused.prefetch] == ["dense", "dense", "bm25_fr", "bm25_en"]
    assert fused.limit == cfg.fused_limit + FUSED_TIE_MARGIN  # margin so RRF ties at the cut resolve locally
    assert all(p.limit >= cfg.fused_limit for p in fused.prefetch)
    assert all(p.filter == plan.flt for p in fused.prefetch)
    assert fused.prefetch[0].params.quantization.rescore is True
    assert len(singles) == 4
    assert all(r.with_payload in (None, False) for r in singles)


def test_config_refuses_prefetch_limits_below_max_top_k():
    with pytest.raises(ValueError):
        RetrievalConfig(dense_limit=10)
    with pytest.raises(ValueError):
        RetrievalConfig(fused_limit=5)


def test_diversify_caps_per_document_one_per_parent_and_drops_link_only():
    cands = [
        cand("a1", "A", "A#s1"),
        cand("a2", "A", "A#s1"),  # same parent as a1
        cand("a3", "A", "A#s2"),
        cand("a4", "A", "A#s3"),  # third chunk of doc A
        cand("x1", "X", "X#s1", reuse="link_only"),
        cand("b1", "B", "B#s1"),
    ]
    kept = diversify(cands, max_per_doc=2, one_per_parent=True, limit=10)
    assert [c.point_id for c in kept] == ["a1", "a3", "b1"]
    loose = diversify(cands, max_per_doc=2, one_per_parent=False, limit=10)
    assert [c.point_id for c in loose] == ["a1", "a2", "b1"]
    assert len(diversify(cands, max_per_doc=5, one_per_parent=False, limit=2)) == 2
    no_doc = Candidate("z", MappingProxyType({}), 0.1)
    assert diversify([no_doc], max_per_doc=2, one_per_parent=True, limit=5) == []
