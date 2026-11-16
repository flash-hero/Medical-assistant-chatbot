"""evals.retrieval: metrics, gold schema / sampling, calibration, report and promotion gate."""

import math
import random
from datetime import UTC, datetime

import pytest
from rag_fixtures import make_doc

from evals.retrieval.calibrate import Sample, calibrate, fit, rates
from evals.retrieval.gold import (
    GoldError,
    GoldQuery,
    answer_ids,
    load_gold,
    sample_passages,
    save_gold,
    with_rewrites,
)
from evals.retrieval.metrics import first_hit, ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from evals.retrieval.report import gate_records, latest_report, load_rag_gates, promotion_check, write_report
from rag.chunking import ChunkerConfig, chunk_document

NOW = datetime(2026, 11, 16, 1, 0, tzinfo=UTC)


def gq(qid: str, lang: str = "en", answerable: bool = True, **kw) -> GoldQuery:
    base = {"kind": "passage", "relevant_chunk_ids": ("d#s#0",)} if answerable else {"kind": "ooc_fictional"}
    return GoldQuery(
        qid=qid,
        language=lang,
        question=kw.pop("question", "What is asthma?"),
        answerable=answerable,
        status="llm_generated_unreviewed",
        generator="test",
        created_at=NOW,
        **{**base, **kw},
    )


# ---- metrics -------------------------------------------------------------------------------------
def test_ranking_metrics_treat_gold_ids_as_alternatives():
    ranked = [("x",), ("a", "b"), ("dup",)]
    gold = {"b", "dup"}
    assert first_hit(ranked, gold) == 2
    assert recall_at_k(ranked, gold, 1) == 0.0
    assert recall_at_k(ranked, gold, 2) == 1.0
    assert reciprocal_rank(ranked, gold) == 0.5
    assert ndcg_at_k(ranked, gold, 8) == pytest.approx(1 / math.log2(3))
    assert ndcg_at_k(ranked, {"zzz"}, 8) == 0.0
    with pytest.raises(ValueError):
        recall_at_k(ranked, set(), 5)


def test_percentile_matches_linear_interpolation():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10.0], 95) == 10.0
    assert percentile(list(range(101)), 95) == 95.0
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1], 101)


# ---- gold ----------------------------------------------------------------------------------------
def test_gold_schema_consistency_rules():
    assert gq("a").answerable
    with pytest.raises(ValueError):
        gq("b", answerable=True, relevant_chunk_ids=())
    with pytest.raises(ValueError):
        gq("c", answerable=False, relevant_chunk_ids=("x",))
    with pytest.raises(ValueError):
        gq("d", search_queries=("q",))  # rewrite must say where it came from
    with pytest.raises(ValueError):
        gq("bad id!")


def test_gold_io_rewrites_and_duplicate_detection(tmp_path):
    rows = [
        gq("q1-en"),
        gq("q1-fr", "fr", question="Qu'est-ce que l'asthme ?"),
        gq("o1-ar", "ar", answerable=False),
    ]
    rows = with_rewrites(rows, {"q1-fr": "What is asthma?", "q1-en": "ignored for English"}, "model")
    assert rows[0].search_queries == ()
    assert rows[1].search_queries == ("What is asthma?",)
    assert rows[1].rewrite == "model"
    assert save_gold(tmp_path / "g.jsonl", rows) == 3
    assert {r.qid for r in load_gold(tmp_path)} == {"q1-en", "q1-fr", "o1-ar"}
    save_gold(tmp_path / "h.jsonl", rows[:1])
    with pytest.raises(GoldError, match="duplicate"):
        load_gold(tmp_path)
    (tmp_path / "h.jsonl").write_text('{"qid": "x"}\n', encoding="utf-8")
    with pytest.raises(GoldError, match=r"h\.jsonl:1"):
        load_gold(tmp_path)


def test_passage_sampling_is_seeded_one_per_doc_and_round_robin():
    cfg = ChunkerConfig(small_section_tokens=0, min_tokens=1)
    chunks = []
    for src in ("src_a", "src_b"):
        for i in range(6):
            chunks.extend(chunk_document(make_doc(f"t{i}", source_id=src), publisher="P", config=cfg))
    picked = sample_passages(chunks, 6, seed=3, min_tokens=1)
    assert len(picked) == 6
    assert len({c.doc_id for c in picked}) == 6
    assert sorted(c.source_id for c in picked) == ["src_a"] * 3 + ["src_b"] * 3
    assert picked == sample_passages(chunks, 6, seed=3, min_tokens=1)
    assert sample_passages(chunks, 6, seed=3, min_tokens=10_000) == []
    only_a = sample_passages(chunks, 20, seed=1, min_tokens=1, allowed=lambda c: c.source_id == "src_a")
    assert {c.source_id for c in only_a} == {"src_a"}
    assert len(only_a) == 6


def test_answer_ids_include_exact_duplicates_from_other_documents():
    a = chunk_document(make_doc("asthma", title="Leukemia A"), publisher="P")[0]
    b = chunk_document(make_doc("asthma", source_id="other_src", title="Leukemia A"), publisher="P")[0]
    c = chunk_document(make_doc("measles"), publisher="P")[0]
    assert answer_ids(a, [a, b, c]) == (a.chunk_id, b.chunk_id)


# ---- calibration ---------------------------------------------------------------------------------
def _samples(n: int, seed: int = 5) -> list[Sample]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        lang = ("en", "fr", "ar")[i % 3]
        label = int(i % 2 == 0)
        dense = rng.gauss(0.74 if label else 0.62, 0.03)
        cov = min(1.0, max(0.0, rng.gauss(0.8 if label else 0.3, 0.15)))
        out.append(
            Sample({"dense_top": dense, "lexical_coverage": cov, "sparse_agreement": None}, lang, label)
        )
    return out


def test_fit_separates_classes_and_respects_the_false_abstention_cap():
    data = _samples(300)
    model = fit(data, ("dense_top", "lexical_coverage", "sparse_agreement"), max_false_abstain=0.05)
    assert model.calibrated
    assert model.weights["dense_top"] > 0
    assert model.weights["lexical_coverage"] > 0
    r = rates(model, data)
    assert r.abstain_answerable <= 0.05 + 1e-9
    assert r.abstain_ooc > 0.8
    with pytest.raises(ValueError, match="both"):
        fit([s for s in data if s.label == 1], ("dense_top",))


def test_cross_validated_rates_are_held_out_and_per_language():
    cal = calibrate(_samples(240), ("dense_top", "lexical_coverage"), k=4, max_false_abstain=0.08)
    assert cal.folds == 4
    assert cal.held_out.n_answerable == 120
    assert cal.held_out.n_ooc == 120
    assert set(cal.held_out_by_lang) == {"en", "fr", "ar"}
    assert cal.held_out.abstain_ooc > 0.7
    assert cal.held_out.abstain_answerable < 0.2


# ---- reports and promotion -------------------------------------------------------------------------
def _passing_report(collection: str, when: datetime) -> dict:
    hybrid = {
        "by_language": {lang: {"n_answerable": 30, "recall_at_20": 0.95} for lang in ("en", "fr", "ar")}
    }
    cal = {"held_out": {"abstain_ooc": 0.95, "abstain_answerable": 0.05, "n_ooc": 60, "n_answerable": 90}}
    records = gate_records(hybrid, cal, (120.0, 270), 0, when, free_tier=True, collection=collection)
    return {
        "schema": "ausculta.retrieval_report.v1",
        "collection": collection,
        "measured_at": when.isoformat(),
        "gate_records": records,
    }


def test_gate_records_cover_every_rag_gate_and_promotion_accepts_provisional(tmp_path):
    report = _passing_report("c1", NOW)
    metrics = {r["metric"] for r in report["gate_records"]}
    gates = load_rag_gates()
    assert {g["metric"] for g in gates.values()} == metrics
    write_report(tmp_path, report, NOW)
    check = promotion_check(tmp_path, "c1")
    assert check.ok
    assert {g["verdict"] for g in check.gates} == {"PASS", "PROVISIONAL"}
    assert not promotion_check(tmp_path, "c2").ok


def test_promotion_uses_the_latest_report_and_refuses_failures_or_missing(tmp_path):
    later = NOW.replace(hour=2)
    bad = _passing_report("c1", later)
    bad["gate_records"] = [r for r in bad["gate_records"] if r["metric"] != "recall_at_20"]
    write_report(tmp_path, _passing_report("c1", NOW), NOW)
    write_report(tmp_path, bad, later)
    (tmp_path / "junk.json").write_text("[1, 2]", encoding="utf-8")
    _path, data = latest_report(tmp_path, "c1")
    assert data["measured_at"] == later.isoformat()
    check = promotion_check(tmp_path, "c1")
    assert not check.ok
    assert "rag.recall_at_20_en" in check.reason
    slow = _passing_report("c3", NOW)
    for r in slow["gate_records"]:
        if r["metric"] == "retrieval_latency_p95_ms":
            r["value"] = 900.0
    write_report(tmp_path / "x", slow, NOW)
    assert "rag.retrieval_p95_ms" in promotion_check(tmp_path / "x", "c3").reason
