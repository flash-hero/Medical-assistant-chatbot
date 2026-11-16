"""Dry-run build planning (`python -m rag plan`): chunk counts, cache awareness, ETA; no API, no Qdrant."""

import io
import sys

import pytest
import structlog
from rag_fixtures import make_doc, retrieval_docs, write_normalized

from core.config import Settings
from rag.build import load_documents
from rag.chunking import chunk_document
from rag.cli import configure_logging, main
from rag.embed_cache import EmbeddingCache
from rag.errors import CorpusNotReady
from rag.paths import DataPaths
from rag.plan import BuildPlan, SourcePlan, active_sources, plan_build, plan_source
from rag.registry import load_registry

MODEL = "plan-test-model"


@pytest.fixture
def setup(tmp_path, registry_path):
    root = tmp_path / "data"
    docs = retrieval_docs()
    write_normalized(root, "demo_src", docs)
    paths = DataPaths(root)
    with EmbeddingCache(tmp_path / "emb.sqlite3") as cache:
        yield paths, load_registry(registry_path), cache, docs


def test_counts_match_the_chunker_and_cached_chunks_are_not_re_embedded(setup):
    paths, registry, cache, docs = setup
    chunks = [c for d in docs for c in chunk_document(d)]
    first = plan_source(paths, registry, "demo_src", cache, model_id=MODEL)
    assert (first.status, first.documents, first.chunks) == ("ready", len(docs), len(chunks))
    assert first.cached == 0
    assert first.to_embed == first.unique_chunks == len({c.checksum for c in chunks})
    assert first.tokens == sum(c.token_estimate for c in chunks)

    cache.put_many(MODEL, 768, {chunks[0].checksum: [0.1] * 768, chunks[1].checksum: [0.2] * 768})
    second = plan_source(paths, registry, "demo_src", cache, model_id=MODEL)
    assert second.cached == 2
    assert second.to_embed == first.to_embed - 2
    assert plan_source(paths, registry, "demo_src", cache, model_id="other-model").cached == 0
    assert plan_source(paths, registry, "demo_src", cache, model_id=MODEL, limit=1).documents == 1


def test_duplicate_texts_are_embedded_once(tmp_path, registry_path):
    same = [("s1", ("Shared", "Overview"), "Wash your hands often with soap and water for twenty seconds.")]
    docs = [make_doc("a", sections=same, title="Shared"), make_doc("b", sections=same, title="Shared")]
    write_normalized(tmp_path / "data", "demo_src", docs)
    with EmbeddingCache(tmp_path / "emb.sqlite3") as cache:
        plan = plan_source(
            DataPaths(tmp_path / "data"), load_registry(registry_path), "demo_src", cache, model_id=MODEL
        )
    assert plan.chunks == 2
    assert plan.unique_chunks == plan.to_embed == 1


def test_unready_missing_and_non_indexable_sources(setup, tmp_path):
    paths, registry, cache, _ = setup
    (paths.ready_dir / "demo_src.json").unlink()
    skipped = plan_source(paths, registry, "demo_src", cache, model_id=MODEL)
    assert (skipped.status, skipped.chunks, skipped.note) == ("not_ready", 0, "not counted")
    counted = plan_source(paths, registry, "demo_src", cache, model_id=MODEL, include_unready=True)
    assert counted.status == "not_ready"
    assert counted.chunks > 0
    assert plan_source(paths, registry, "held_src", cache, model_id=MODEL).status == "not_indexable"
    assert plan_source(paths, registry, "unknown_src", cache, model_id=MODEL).status == "not_indexable"
    paths.normalized_file("demo_src").unlink()
    assert plan_source(paths, registry, "demo_src", cache, model_id=MODEL).status == "missing"
    with pytest.raises(CorpusNotReady):
        load_documents(paths, registry, "demo_src", None, require_ready=False)


def test_totals_eta_and_daily_cap():
    plan = BuildPlan(
        (
            SourcePlan("a", "ready", documents=10, chunks=200, unique_chunks=190, cached=10),
            SourcePlan("b", "ready", documents=5, chunks=100, unique_chunks=100, cached=0),
            SourcePlan("c", "not_ready", documents=99, chunks=999, unique_chunks=999, cached=0),
        ),
        rate_per_min=90.0,
        daily_cap=100,
    )
    assert [s.source_id for s in plan.buildable()] == ["a", "b"]
    assert plan.total("to_embed") == 280
    assert plan.total("chunks", buildable_only=False) == 1299
    assert plan.eta_minutes() == pytest.approx(280 / 90)
    assert plan.days_at_cap() == 2.8
    assert BuildPlan(plan.sources, daily_cap=None).days_at_cap() is None


def test_token_estimates_scale_with_missing_embeddings_and_price():
    a = SourcePlan("a", "ready", chunks=100, unique_chunks=100, cached=25, tokens=40_000)
    b = SourcePlan("b", "ready", chunks=0, unique_chunks=0, cached=0, tokens=0)
    assert a.tokens_to_embed == 30_000
    assert b.tokens_to_embed == 0
    plan = BuildPlan((a, b), rate_per_min=90.0)
    assert plan.tokens_per_minute() == pytest.approx(400 * 90)
    assert plan.cost_usd(0.20) == pytest.approx(0.006)
    assert BuildPlan((b,)).tokens_per_minute() == 0.0


def test_active_sources_and_plan_build(setup):
    paths, registry, cache, _ = setup
    assert active_sources(registry) == ("demo_src",)
    plan = plan_build(paths, registry, ["demo_src", "held_src"], cache, model_id=MODEL, rate_per_min=60.0)
    assert [s.status for s in plan.sources] == ["ready", "not_indexable"]
    assert plan.rate_per_min == 60.0


def test_cli_plan_prints_counts_eta_and_the_build_command(tmp_path, registry_path, monkeypatch, capsys):
    root = tmp_path / "data"
    write_normalized(root, "demo_src", retrieval_docs())
    settings = Settings(AUSCULTA_DATA_ROOT=str(root), AUSCULTA_LLM_BACKEND="fake")
    monkeypatch.setattr("rag.cli.get_settings", lambda: settings)
    monkeypatch.setattr("rag.cli.load_registry", lambda: load_registry(registry_path))
    assert main(["plan", "--corpus-version", "v9", "--daily-cap", "50"]) == 0
    printed = capsys.readouterr().out
    assert "demo_src" in printed
    assert "chunks/min" in printed
    assert "input tokens/min" in printed
    assert "Paid-tier cost estimate" in printed
    assert "day(s) of quota" in printed
    assert "python -m rag build --corpus-version v9 --sources demo_src" in printed
    assert main(["plan", "--sources", "demo_src,held_src", "--exclude", "demo_src", "--daily-cap", "0"]) == 0
    printed = capsys.readouterr().out
    assert "not_indexable" in printed
    assert "day(s) of quota" not in printed
    assert "Build command" not in printed


def test_cli_logging_survives_a_replaced_and_closed_stderr(monkeypatch):
    """Regression: the CLI logger used to keep pytest's captured stderr and fail after it was closed."""
    first = io.StringIO()
    monkeypatch.setattr(sys, "stderr", first)
    configure_logging()
    first.close()
    second = io.StringIO()
    monkeypatch.setattr(sys, "stderr", second)
    try:
        structlog.get_logger("plan-test").warning("still_logging", n=1)
    finally:
        structlog.reset_defaults()
    assert "still_logging" in second.getvalue()
