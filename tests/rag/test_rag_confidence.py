import pytest

from rag.confidence import Signals, decide, lexical_coverage, sparse_agreement
from rag.paths import DataPaths
from rag.retrieval_config import (
    ConfidenceModel,
    RetrievalConfig,
    load_retrieval_config,
    save_retrieval_config,
)


def test_lexical_coverage_is_the_best_query_passage_overlap():
    q = [frozenset({"asthma", "wheez"}), frozenset()]
    p = [frozenset({"asthma"}), frozenset({"asthma", "wheez", "cough"})]
    assert lexical_coverage(q, p) == 1.0
    assert lexical_coverage([frozenset({"zorvalimab", "dose"})], p) == 0.0
    assert lexical_coverage([], p) == 0.0


def test_sparse_agreement_counts_top_three():
    assert sparse_agreement(["a", "b", "c", "d"], frozenset({"a", "d"})) == pytest.approx(1 / 3)
    assert sparse_agreement([], frozenset({"a"})) == 0.0


def test_default_model_is_a_dense_threshold_rule():
    model = ConfidenceModel()
    assert decide(model, Signals(0.70, 0.0, 0.0), "en", has_passages=True).confident
    assert not decide(model, Signals(0.55, 1.0, 1.0), "en", has_passages=True).confident
    assert decide(model, Signals(0.9, 1.0, 1.0), "en", has_passages=False).confidence == 0.0


def test_degraded_mode_needs_strong_lexical_match_and_caps_confidence():
    strong = decide(ConfidenceModel(), Signals(0.0, 0.8, 0.0, degraded=True), "fr", has_passages=True)
    weak = decide(ConfidenceModel(), Signals(0.0, 0.5, 0.0, degraded=True), "fr", has_passages=True)
    assert strong.confident
    assert strong.confidence == pytest.approx(0.64)
    assert not weak.confident


def test_calibrated_model_uses_language_bias_and_imputes_missing_features():
    model = ConfidenceModel(
        weights={"dense_top": 10.0, "rerank_top": 4.0},
        bias=-7.0,
        lang_bias={"ar": 1.0},
        feature_means={"rerank_top": 0.5},
        threshold=0.5,
        calibrated=True,
    )
    feats = {"dense_top": 0.5, "rerank_top": None}
    assert model.probability(feats, "ar") > model.probability(feats, "en")
    assert model.probability(feats, "en") == pytest.approx(1 / (1 + 2.718281828**0))
    with pytest.raises(ValueError, match="unknown"):
        ConfidenceModel(weights={"vibes": 1.0})
    with pytest.raises(ValueError, match="threshold"):
        ConfidenceModel(threshold=1.0)


def test_retrieval_config_roundtrip_and_safe_defaults(tmp_path):
    paths = DataPaths(tmp_path)
    cfg = RetrievalConfig(rerank=True, confidence=ConfidenceModel(bias=-3.0))
    save_retrieval_config(paths, "c1", cfg)
    assert load_retrieval_config(paths, "c1") == cfg
    assert load_retrieval_config(paths, None) == RetrievalConfig()
    assert load_retrieval_config(paths, "missing") == RetrievalConfig()
    paths.retrieval_config_file("broken").write_text("{not json", encoding="utf-8")
    assert load_retrieval_config(paths, "broken") == RetrievalConfig()
