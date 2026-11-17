"""Task: re-run the seed evaluation logic offline with the fake provider (no Qdrant server, no model).

1. evals/retrieval/dense_check.py on synthetic data (CI) and its CLI.
2. When the development data root holds the seed chunks (this machine, not CI): the dense check over all
   720 seed chunks + the gold set, and the full `run_eval` of the seed collection rebuilt in local-mode
   Qdrant with fake vectors. The sparse-only ablation does not depend on the embedding model, so it must
   reproduce the BM25 row of ADR 0002 measured on the real server.
"""

import os
from datetime import UTC, datetime

import pytest
from qdrant_client import AsyncQdrantClient
from rag_fixtures import QDRANT_LOCAL_WARNINGS, TEST_SECRET, fake_embedding, retrieval_docs
from test_rag_eval_runner import gold_rows

from core.config import Settings
from core.models import EMBED_DIM
from evals.fakes.fake_llm import FakeLLMProvider
from evals.retrieval.dense_check import MIN_TOP1, dense_check, main, render, select_seed
from evals.retrieval.gold import load_chunks, load_gold, save_gold
from rag.chunking import chunk_document
from rag.fileio import atomic_write_jsonl
from rag.paths import GOLD_DIR, DataPaths

pytestmark = [pytest.mark.filterwarnings(w) for w in QDRANT_LOCAL_WARNINGS]
SEED_CHUNKS = DataPaths.from_settings(Settings()).chunks_dir("2026-11-16.seed1") / "medlineplus_topics.jsonl"
needs_seed = pytest.mark.skipif(not SEED_CHUNKS.exists(), reason="seed chunks not on this machine")


def _chunks():
    return [c for d in retrieval_docs() for c in chunk_document(d, publisher="DemoPlus")]


def test_select_seed_balances_languages_with_distinct_answer_chunks():
    chunks = _chunks()
    picked_chunks, rows = select_seed(chunks, gold_rows(), questions=3, total_chunks=10)
    assert [r.language for r in rows] == ["en", "fr", "ar"]
    answers = [r.relevant_chunk_ids[0] for r in rows]
    assert len(set(answers)) == len(answers)  # one question per answer chunk
    assert len(picked_chunks) == 10
    assert answers == [c.chunk_id for c in picked_chunks[: len(answers)]]
    assert select_seed(chunks, gold_rows(), questions=3, total_chunks=10) == (picked_chunks, rows)
    few_chunks, few_rows = select_seed(chunks, gold_rows(), questions=99, total_chunks=2)
    assert [r.language for r in few_rows] == ["en", "fr", "ar", "en"]  # 4 distinct answer chunks only
    assert len(few_chunks) == 4  # never fewer chunks than answers


async def test_dense_check_with_the_fake_provider():
    chunks, rows = select_seed(_chunks(), gold_rows(), questions=12, total_chunks=12)
    check = await dense_check(FakeLLMProvider(), chunks, rows, model_id="fake")
    assert check.vectors_ok()
    assert check.dims == frozenset({EMBED_DIM})
    assert check.max_norm_error < 1e-6
    assert check.questions == 4
    assert check.by_language["en"]["top1"] == 1.0  # lexical hash vectors: same-language words match
    assert set(check.by_language) == {"en", "fr", "ar", "all"}
    assert check.by_language["all"]["n"] == 4.0
    lines = render(check)
    assert lines[-1].startswith("PASS" if check.passed() else "FAIL")
    assert sum("rank 1" in line for line in lines) >= 2


async def test_dense_check_flags_vectors_that_are_not_unit_norm():
    class Scaled(FakeLLMProvider):
        async def embed(self, texts, *, dim):
            return [[2 * x for x in v] for v in await super().embed(texts, dim=dim)]

    chunks, rows = select_seed(_chunks(), gold_rows(), questions=3, total_chunks=6)
    check = await dense_check(Scaled(), chunks, rows, model_id="scaled")
    assert not check.vectors_ok()
    assert not check.passed()
    assert render(check)[-1].startswith("FAIL")
    empty = await dense_check(FakeLLMProvider(), [], [], model_id="none")
    assert (empty.top1, empty.max_norm_error, empty.by_language) == (0.0, 0.0, {})
    assert not empty.passed()


def test_dense_check_cli_with_the_fake_backend(tmp_path):
    chunk_file = tmp_path / "chunks.jsonl"
    atomic_write_jsonl(chunk_file, _chunks())
    save_gold(tmp_path / "gold" / "en.jsonl", [r for r in gold_rows() if r.language == "en"])
    lines: list[str] = []
    args = ["--chunks", str(chunk_file), "--gold", str(tmp_path / "gold"), "--backend", "fake"]
    assert main([*args, "--questions", "4", "--total-chunks", "8"], write=lines.append) == 0
    assert lines[0].startswith("model fake-hash-embedding@fmt1: 8 chunks + 4 questions")
    assert lines[-1] == f"PASS (top-1 must exceed {MIN_TOP1:.0%})"


# ---- the real seed (development machine only) -------------------------------------------------------
@needs_seed
async def test_seed_dense_check_offline_with_the_fake_provider():
    chunks = load_chunks([SEED_CHUNKS])
    rows = [r for r in load_gold(GOLD_DIR) if r.answerable]
    check = await dense_check(FakeLLMProvider(), chunks, rows, model_id="fake")
    assert check.chunks == 720
    assert check.questions == len(rows) == 288
    assert check.vectors_ok()
    assert check.by_language["en"]["recall_at_20"] > 0.5  # hash vectors: only same-language words match


async def _index_seed(client: AsyncQdrantClient, paths: DataPaths, collection: str, embedding) -> int:
    """The seed collection rebuilt from its chunk file in local-mode Qdrant (payloads, BM25 and a manifest
    exactly as `rag build` writes them), with the given embedding backend."""
    from rag.build import sparse_text
    from rag.embed_cache import EmbeddingCache
    from rag.index import build_points, ensure_collection, upsert_points
    from rag.manifest import make_manifest, write_manifest
    from rag.sparse import SparseEncoder

    chunks = load_chunks([SEED_CHUNKS])
    with EmbeddingCache(paths.root / "emb.sqlite3") as cache:
        dense = (await embedding.document_embedder(cache).embed_chunks(chunks)).vectors
    sparse = SparseEncoder(DataPaths.from_settings(Settings()).fastembed_dir)
    encoded = sparse.encode_documents([sparse_text(c) for c in chunks], "en")
    vecs = {c.chunk_id: v for c, v in zip(chunks, encoded, strict=True)}
    await ensure_collection(client, collection)
    await upsert_points(client, collection, build_points(chunks, dense, vecs))
    manifest = make_manifest(
        corpus_version="seed-offline",
        collection=collection,
        chunks=chunks,
        embed_model=embedding.model_id,
        embed_dim=EMBED_DIM,
        secret=TEST_SECRET,
        created_at=datetime.now(UTC),
    )
    write_manifest(paths, manifest)
    return len(chunks)


# BM25 is model-independent: ADR 0002 measured sparse-only R@20 on the server (seed1, 2026-11-16)
ADR_0002_SPARSE_R20 = {"en": 0.958, "fr": 0.948, "ar": 0.938}


@pytest.fixture
async def seed_index(tmp_path):
    from rag.verify import verify_collection

    paths = DataPaths(tmp_path / "data")
    collection = "ausculta_corpus_seed_offline"
    llm = FakeLLMProvider()
    embedding = fake_embedding(llm)
    client = AsyncQdrantClient(location=":memory:")
    try:
        assert await _index_seed(client, paths, collection, embedding) == 720
        verified = await verify_collection(
            client, paths, collection, TEST_SECRET, embed_model=embedding.model_id
        )
        assert verified.chunks == 720  # the new signature scheme holds on the real seed payloads
        yield client, paths, collection, llm, embedding
    finally:
        await client.close()


@needs_seed
@pytest.mark.slow
async def test_seed_sparse_ablation_reproduces_adr_0002_offline(seed_index):
    """The seed evaluation's model-independent half, on all 450 gold rows, with production composition
    (drug synonyms, English rewrites, fusion code): BM25 recall@20 must match the server measurement."""
    from evals.retrieval.evaluate import run_ablation, standard_ablations, summarize
    from rag.paths import DRUG_SYNONYMS_PATH
    from rag.rerank import NoopReranker
    from rag.retrieval import HybridRetriever
    from rag.retrieval_config import RetrievalConfig
    from rag.sparse import SparseEncoder
    from rag.synonyms import load_synonyms

    client, _paths, collection, _llm, embedding = seed_index
    retriever = HybridRetriever(
        client=client,
        collection=collection,
        query_embedder=embedding.query_embedder(),
        sparse=SparseEncoder(DataPaths.from_settings(Settings()).fastembed_dir),
        reranker=NoopReranker(),
        synonyms=load_synonyms(DRUG_SYNONYMS_PATH),
    )
    sparse = next(a for a in standard_ablations(RetrievalConfig()) if a.name == "sparse")
    rows = list(load_gold(GOLD_DIR))
    summary = summarize(await run_ablation(retriever, rows, sparse))["by_language"]
    measured = {lang: round(summary[lang]["recall_at_20"], 3) for lang in ADR_0002_SPARSE_R20}
    assert measured == pytest.approx(ADR_0002_SPARSE_R20, abs=0.011), measured  # <= 1 query of 96


@needs_seed
@pytest.mark.skipif(
    not os.environ.get("AUSCULTA_SEED_EVAL"),
    reason="full offline seed eval takes ~2.5 min: AUSCULTA_SEED_EVAL=1",
)
async def test_seed_evaluation_offline_with_the_fake_provider(seed_index):
    """The whole `rag eval` logic (pre-embed, ablations, calibration, gates) on the seed, offline."""
    from evals.retrieval.runner import EvalContext, EvalOptions, run_eval
    from rag.sparse import SparseEncoder

    client, paths, collection, llm, embedding = seed_index
    sparse = SparseEncoder(DataPaths.from_settings(Settings()).fastembed_dir)
    ctx = EvalContext(client, llm, paths, sparse, datetime.now(UTC), embedding)
    opts = EvalOptions(
        collection=collection,
        gold_dir=GOLD_DIR,
        rerank_sample=0,
        embed_latency_sample=2,
        write_config=False,
        resume_check=False,
    )
    report = await run_eval(ctx, opts)
    assert report["gold"]["rows"] == report["gold"]["evaluated"] == 450
    assert report["embed_model"] == report["collection_embed_model"] == "fake-hash-embedding@fmt1"
    by_name = {a["ablation"]: a["by_language"] for a in report["ablations"]}
    assert list(by_name) == ["dense", "sparse", "hybrid", "hybrid_native"]
    for lang, expected in ADR_0002_SPARSE_R20.items():
        assert by_name["sparse"][lang]["recall_at_20"] == pytest.approx(expected, abs=0.011), lang
    assert report["pre_embed"]["embedded"] == report["pre_embed"]["texts"]
    assert {g["gate"] for g in report["gates"]} >= {"rag.recall_at_20_en", "rag.retrieval_p95_ms"}
