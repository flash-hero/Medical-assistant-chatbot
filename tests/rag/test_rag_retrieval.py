from collections import Counter

import pytest
from qdrant_client import AsyncQdrantClient
from rag_fixtures import (
    QDRANT_LOCAL_WARNINGS,
    build_index,
    make_doc,
    qdrant_server_up,
    retrieval_docs,
)

from core.config import Settings
from core.errors import DependencyUnavailable, InvalidInput, UpstreamUnavailable
from core.models import EMBED_DIM, ModelRole
from core.ports import DecisionAnswer, Retriever
from core.schemas.chat import RetrievalQuery
from evals.fakes.fake_llm import FakeLLMProvider, hash_embed
from rag.chunking import chunk_document
from rag.embedding import QueryEmbedder
from rag.index import build_points, upsert_points
from rag.manifest import ActivePointer, write_active
from rag.paths import DataPaths
from rag.rerank import DecisionReranker, NoopReranker
from rag.retrieval import HybridRetriever, build_retriever, query_texts
from rag.retrieval_config import ConfidenceModel, RetrievalConfig
from rag.sparse import SparseEncoder
from rag.synonyms import SynonymIndex

pytestmark = [
    pytest.mark.filterwarnings(w)
    for w in (*QDRANT_LOCAL_WARNINGS, "ignore:Failed to obtain server version:UserWarning")
]

LEXICAL_GATE = ConfidenceModel(weights={"lexical_coverage": 12.0}, bias=-6.0)
CFG = RetrievalConfig(confidence=LEXICAL_GATE)


@pytest.fixture(scope="module")
def sparse() -> SparseEncoder:
    return SparseEncoder(DataPaths.from_settings(Settings()).fastembed_dir)


@pytest.fixture
async def indexed(tmp_path, registry_path):
    client = AsyncQdrantClient(location=":memory:")
    collection = await build_index(tmp_path, registry_path, client, retrieval_docs())
    yield client, collection
    await client.close()


def make_retriever(client, collection, sparse, *, llm=None, reranker=None, config=CFG, synonyms=None):
    return HybridRetriever(
        client=client,
        collection=collection,
        query_embedder=QueryEmbedder(llm or FakeLLMProvider(), model_id="q"),
        sparse=sparse,
        reranker=reranker or NoopReranker(),
        config=config,
        synonyms=synonyms,
        version="t1",
    )


def q(text: str, **kw) -> RetrievalQuery:
    return RetrievalQuery(standalone_query=text, language=kw.pop("language", "en"), **kw)


async def test_hybrid_retrieval_ranks_the_right_document_and_reports_timings(indexed, sparse):
    client, collection = indexed
    r = make_retriever(client, collection, sparse)
    assert isinstance(r, Retriever)
    result = await r.retrieve(q("What causes wheezing and chest tightness in asthma?", top_k=5))
    top = result.passages[0]
    assert top.doc_id == "demo_src:asthma"
    assert result.confident
    assert result.corpus_version == "t1"
    assert str(top.url) == "https://example.gov/asthma"
    assert top.attribution.startswith("Source: DemoPlus")
    assert {"rrf", "dense", "sparse_hit"} <= set(top.scores)
    assert top.scores["sparse_hit"] == 1.0
    t = result.timings_ms
    assert {"embed_api_ms", "embed_ms", "search_ms", "expand_ms", "retrieval_ms", "total_ms"} <= set(t)
    assert t["retrieval_ms"] <= t["total_ms"]
    assert [p.score for p in result.passages] == sorted((p.score for p in result.passages), reverse=True)


async def test_at_most_two_chunks_per_document(indexed, sparse):
    client, collection = indexed
    result = await make_retriever(client, collection, sparse).retrieve(q("metformin side effects", top_k=10))
    per_doc = Counter(p.doc_id for p in result.passages)
    assert per_doc["demo_src:metformin"] == 2
    assert max(per_doc.values()) <= 2


async def test_link_only_points_are_never_returned_even_when_asked_for(indexed, sparse):
    client, collection = indexed
    doc = make_doc("secret_page", reuse_mode="link_only", title="Zebracorn Fever")
    chunks = chunk_document(doc, publisher="P")
    dense = {c.checksum: hash_embed(c.embedding_text(), EMBED_DIM) for c in chunks}
    sv = sparse.encode_documents([c.lexical_text() for c in chunks], "en")
    await upsert_points(
        client,
        collection,
        build_points(chunks, dense, {c.chunk_id: v for c, v in zip(chunks, sv, strict=True)}),
    )
    r = make_retriever(client, collection, sparse)
    result = await r.retrieve(q("Zebracorn fever", top_k=20))
    assert all(p.reuse_mode != "link_only" for p in result.passages)
    asked = await r.retrieve(q("Zebracorn fever", filters={"reuse_mode": ["link_only"]}))
    assert asked.passages == ()
    assert not asked.confident


async def test_payload_filters_and_filter_validation(indexed, sparse):
    client, collection = indexed
    r = make_retriever(client, collection, sparse)
    result = await r.retrieve(q("metformin", filters={"content_type": ["drug_label"]}, top_k=10))
    assert result.passages
    assert {p.content_type for p in result.passages} == {"drug_label"}
    tiers = await r.retrieve(q("asthma", filters={"trust_tier": ["1"]}))
    assert tiers.passages
    for bad in ({"bogus": ["x"]}, {"trust_tier": ["one"]}, {"language": []}, {"doc_id": [""]}):
        with pytest.raises(InvalidInput):
            await r.retrieve(q("asthma", filters=bad))


async def test_small_to_big_expansion_returns_the_parent_window(indexed, sparse):
    client, collection = indexed
    r = make_retriever(client, collection, sparse)
    tr = await r.trace(q("Sentence 45 kidney stones calcium oxalate", top_k=3))
    assert tr.result.passages[0].doc_id == "demo_src:kidney_stones"
    covered = tr.covered_chunk_ids[0]
    assert len(covered) > 1
    assert tr.ranked_chunk_ids[0] in covered
    assert all(c.startswith("demo_src:kidney_stones#s1#") for c in covered)
    flat = await r.trace(
        q("Sentence 45 kidney stones calcium oxalate", top_k=3), CFG.model_copy(update={"expand": False})
    )
    assert flat.covered_chunk_ids[0] == (flat.ranked_chunk_ids[0],)
    assert len(tr.result.passages[0].text) > len(flat.result.passages[0].text)


async def test_unrelated_query_is_not_confident(indexed, sparse):
    client, collection = indexed
    result = await make_retriever(client, collection, sparse).retrieve(q("zorvalimab dosage for racehorses"))
    assert not result.confident
    assert result.confidence < 0.5


async def test_embedding_failure_degrades_to_sparse_only(indexed, sparse):
    client, collection = indexed
    down = FakeLLMProvider(failures={ModelRole.EMBED: UpstreamUnavailable("down")})
    r = make_retriever(client, collection, sparse, llm=down)
    tr = await r.trace(q("measles rash vaccine"))
    assert tr.signals.degraded
    assert tr.result.timings_ms["dense_degraded"] == 1.0
    assert tr.result.passages[0].doc_id == "demo_src:measles"
    with pytest.raises(UpstreamUnavailable):
        await r.trace(q("measles"), CFG.model_copy(update={"mode": "dense"}))


async def test_dense_and_sparse_only_modes(indexed, sparse):
    client, collection = indexed
    r = make_retriever(client, collection, sparse)
    dense = await r.trace(q("migraine aura flashing lights"), CFG.model_copy(update={"mode": "dense"}))
    only_sparse = await r.trace(q("migraine aura flashing lights"), CFG.model_copy(update={"mode": "sparse"}))
    assert dense.result.passages[0].doc_id == "demo_src:migraine"
    assert only_sparse.result.passages[0].doc_id == "demo_src:migraine"
    assert only_sparse.result.timings_ms["embed_api_ms"] == 0.0


async def test_vector_store_errors_become_dependency_unavailable(indexed, sparse):
    client, collection = indexed
    missing = make_retriever(client, "no_such_collection", sparse)
    with pytest.raises(DependencyUnavailable):
        await missing.retrieve(q("asthma"))
    assert not await missing.health()
    assert await make_retriever(client, collection, sparse).health()


def test_sparse_plan_languages_english_search_queries_and_synonyms(sparse):
    syn = SynonymIndex.from_groups([["paracetamol", "acetaminophen", "Tylenol"]])
    r = make_retriever(None, "c", sparse, synonyms=syn)
    plan = r._sparse_plan(("Les symptômes de l'asthme", "asthma symptoms"), "fr", CFG)
    assert [name for name, _ in plan] == ["bm25_fr", "bm25_en"]
    with_syn = r._sparse_plan(("paracetamol fever",), "en", CFG)
    assert [name for name, _ in with_syn] == ["bm25_en", "bm25_en"]
    assert r._sparse_plan(("asthma",), "en", CFG.model_copy(update={"mode": "dense"})) == ()
    assert r._sparse_plan(("asma",), "es", CFG) == ()  # no analyser: skipped, never an error


async def test_reranker_reorders_and_a_failing_reranker_falls_back(indexed, sparse):
    client, collection = indexed

    def prefer_second(_input, key, question):
        return DecisionAnswer(kind="score", confidence=0.9, score=3.0 if key == "p2" else 0.0)

    cfg = CFG.model_copy(update={"rerank": True})
    base = await make_retriever(client, collection, sparse).trace(q("diabetes glucose insulin", top_k=4), cfg)
    good = DecisionReranker(FakeLLMProvider(decider=prefer_second))
    tr = await make_retriever(client, collection, sparse, reranker=good).trace(
        q("diabetes glucose insulin", top_k=4), cfg
    )
    assert tr.result.reranked
    assert tr.ranked_chunk_ids[0] == base.ranked_chunk_ids[1]
    assert tr.result.passages[0].scores["rerank"] == 1.0
    assert tr.signals.rerank_top == 1.0
    failing = DecisionReranker(FakeLLMProvider(failures={ModelRole.RERANK: UpstreamUnavailable("x")}))
    fb = await make_retriever(client, collection, sparse, reranker=failing).trace(
        q("diabetes glucose insulin", top_k=4), cfg
    )
    assert not fb.result.reranked
    assert fb.ranked_chunk_ids == base.ranked_chunk_ids


def test_query_texts_dedupes_caps_and_rejects_empty():
    cfg = RetrievalConfig(max_search_queries=2)
    query = RetrievalQuery(
        standalone_query=" Asthma  triggers ",
        search_queries=("asthma triggers", "a", "b", "c"),
        language="en",
    )
    assert query_texts(query, cfg) == ("Asthma triggers", "a", "b")
    with pytest.raises(InvalidInput):
        query_texts(RetrievalQuery(standalone_query="​ ", language="en"), cfg)


async def test_build_retriever_composition_root_follows_the_active_pointer(tmp_path):
    import shutil
    from datetime import UTC, datetime

    from app.llm.local_embedder import LocalEmbeddingProvider
    from rag.embedding import embed_model_id

    shared = DataPaths.from_settings(Settings()).fastembed_dir  # BM25 assets: health() must not download
    shutil.copytree(shared, DataPaths(tmp_path).fastembed_dir, ignore=shutil.ignore_patterns(".locks"))
    settings = Settings(
        AUSCULTA_DATA_ROOT=str(tmp_path),
        AUSCULTA_LLM_BACKEND="fake",
        AUSCULTA_EMBED_BACKEND="local",
        QDRANT_URL="http://127.0.0.1:9",
    )
    llm = FakeLLMProvider()
    empty = build_retriever(settings, llm)
    assert isinstance(empty, Retriever)
    assert empty.corpus_version == ""
    # queries are embedded by the local model (ADR 0003), never by the LLM provider; nothing loaded yet
    assert isinstance(empty._qe._provider, LocalEmbeddingProvider)
    assert empty._qe.model_id == embed_model_id("local")
    assert empty._reranker._llm is llm
    await empty.aclose()
    pointer = ActivePointer(
        alias="ausculta_corpus", collection="c1", corpus_version="v9", promoted_at=datetime.now(UTC)
    )
    write_active(DataPaths(tmp_path), pointer)
    retriever = build_retriever(settings, FakeLLMProvider())
    try:
        assert retriever.corpus_version == "v9"
        assert not await retriever.health()
    finally:
        await retriever.aclose()


async def test_health_runs_a_real_sparse_encode_and_search(indexed, sparse, tmp_path):
    """Review P3: readiness is more than get_collection: the BM25 analyser must encode and the collection
    must answer a search with at least one point."""
    from rag.index import ensure_collection

    client, collection = indexed
    assert await make_retriever(client, collection, sparse).health()
    await ensure_collection(client, "empty_collection")
    assert not await make_retriever(client, "empty_collection", sparse).health()

    class BrokenSparse(SparseEncoder):
        def encode_query(self, text, language):
            raise OSError("read-only file system: fastembed cache")

    broken = BrokenSparse(tmp_path / "nowhere")
    assert not await make_retriever(client, collection, broken).health()

    class StopwordsOnly(SparseEncoder):
        def encode_query(self, text, language):
            from rag.sparse import SparseVec

            return SparseVec((), ())

    assert not await make_retriever(client, collection, StopwordsOnly(tmp_path)).health()


async def test_warmup_loads_the_sparse_analysers_and_the_embedding_model(sparse):
    calls: list[str] = []

    class Warm(FakeLLMProvider):
        async def warmup(self):
            calls.append("embedding")

    class Sparse(SparseEncoder):
        def warmup(self, languages=("en", "fr", "ar")):
            calls.append("sparse")

    r = HybridRetriever(
        client=None,
        collection="c",
        query_embedder=QueryEmbedder(Warm(), model_id="q"),
        sparse=Sparse(sparse._cache_dir),
        reranker=NoopReranker(),
    )
    await r.warmup()
    assert calls == ["sparse", "embedding"]


@pytest.mark.services
@pytest.mark.skipif(not qdrant_server_up(), reason="Qdrant server not running")
async def test_hybrid_retrieval_against_the_real_server(tmp_path, registry_path, sparse):
    client = AsyncQdrantClient(url="http://127.0.0.1:6333", timeout=30)
    collection = None
    try:
        collection = await build_index(
            tmp_path, registry_path, client, retrieval_docs(), version="pytest-svc"
        )
        r = make_retriever(client, collection, sparse)
        result = await r.retrieve(q("What causes wheezing and chest tightness in asthma?", top_k=5))
        assert result.passages[0].doc_id == "demo_src:asthma"
        per_doc = Counter(
            p.doc_id for p in (await r.retrieve(q("metformin side effects", top_k=10))).passages
        )
        assert max(per_doc.values()) <= 2
        assert result.timings_ms["retrieval_ms"] < 2000
    finally:
        if collection:
            await client.delete_collection(collection)
        await client.close()
