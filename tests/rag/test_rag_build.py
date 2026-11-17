import json

import pytest
from qdrant_client import AsyncQdrantClient
from rag_fixtures import QDRANT_LOCAL_WARNINGS, SpyLLM, corpus_docs, make_doc, write_normalized

from core.errors import UpstreamRateLimited
from core.schemas.document import Chunk
from rag.build import BuildRequest, IndexBuilder, load_documents
from rag.embed_cache import EmbeddingCache
from rag.embedding import DocumentEmbedder
from rag.errors import CorpusNotReady, EmbeddingQuotaExhausted, IndexMismatch, SourceNotIndexable
from rag.index import count_points, ensure_collection, switch_alias
from rag.manifest import chunks_digest, read_build_state, read_manifest
from rag.paths import DataPaths
from rag.registry import load_registry
from rag.signing import signature_matches
from rag.sparse import SparseEncoder
from rag.verify import verify_collection

pytestmark = [pytest.mark.filterwarnings(w) for w in QDRANT_LOCAL_WARNINGS]

SECRET = "test-secret-0123456789abcdef"  # secret-scan: allow (test HMAC key)
ALIAS = "test_alias"


@pytest.fixture(scope="module")
def sparse() -> SparseEncoder:
    from core.config import Settings

    return SparseEncoder(DataPaths.from_settings(Settings()).fastembed_dir)


@pytest.fixture
async def client():
    c = AsyncQdrantClient(location=":memory:")
    yield c
    await c.close()


def _builder(tmp_path, registry_path, client, sparse, llm, cache, batch=90, *, quota_limited=False):
    paths = DataPaths(tmp_path / "data")
    embedder = DocumentEmbedder(
        llm, cache, model_id="test-embed", batch_size=batch, quota_limited=quota_limited
    )
    return IndexBuilder(
        paths=paths,
        registry=load_registry(registry_path),
        client=client,
        embedder=embedder,
        sparse=sparse,
        secret=SECRET,
        alias=ALIAS,
    )


async def test_build_indexes_corpus_and_writes_signed_manifest(tmp_path, registry_path, client, sparse):
    write_normalized(tmp_path / "data", "demo_src", corpus_docs())
    with EmbeddingCache(tmp_path / "emb.sqlite3") as cache:
        builder = _builder(tmp_path, registry_path, client, sparse, SpyLLM(), cache)
        report = await builder.build(BuildRequest("2026-11-15.t1", ("demo_src",)))
    paths = DataPaths(tmp_path / "data")
    assert report.status == "indexed"
    assert report.documents == 4
    assert report.chunks == 4
    assert report.collection == "ausculta_corpus_2026_11_15_t1"
    assert await count_points(client, report.collection) == 4
    rows = paths.chunks_file("2026-11-15.t1", "demo_src").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 4
    assert json.loads(rows[0])["context_header"].startswith("DemoPlus | ")
    manifest = read_manifest(paths, report.collection)
    chunks = [Chunk.model_validate_json(r) for r in rows]
    assert manifest.sources == {"demo_src": 4}
    assert manifest.embed_dim == 768
    assert manifest.embed_model == "test-embed"
    assert signature_matches(manifest, chunks_digest(chunks), SECRET)
    assert not signature_matches(manifest, chunks_digest(chunks[:-1]), SECRET)
    assert not signature_matches(manifest, chunks_digest(chunks), "another-secret-0123456789")
    verified = await verify_collection(client, paths, report.collection, SECRET, embed_model="test-embed")
    assert (verified.chunks, verified.corpus_version) == (4, "2026-11-15.t1")
    state = read_build_state(paths, report.collection)
    assert state.status == "indexed"
    assert state.indexed_chunks == 4
    assert (await client.get_aliases()).aliases == []  # building never touches the alias


async def test_inactive_unknown_or_unready_sources_are_refused(tmp_path, registry_path, client, sparse):
    write_normalized(tmp_path / "data", "held_src", corpus_docs())
    with EmbeddingCache(tmp_path / "emb.sqlite3") as cache:
        builder = _builder(tmp_path, registry_path, client, sparse, SpyLLM(), cache)
        with pytest.raises(SourceNotIndexable, match="hold"):
            await builder.build(BuildRequest("v1", ("held_src",)))
        with pytest.raises(SourceNotIndexable, match="not listed"):
            await builder.build(BuildRequest("v1", ("nope_src",)))
        with pytest.raises(CorpusNotReady):
            await builder.build(BuildRequest("v1", ("demo_src",)))
    assert not await client.collection_exists("ausculta_corpus_v1")


def test_bad_lines_and_policy_violations_are_skipped(tmp_path, registry_path):
    good = corpus_docs()
    tampered = make_doc("migraine").model_copy(update={"title": "Changed after checksum"})
    bad = [
        make_doc("x1", source_id="held_src"),
        make_doc("x2", reuse_mode="link_only"),
        make_doc("x3", language="es"),
        make_doc("x4", url="https://www.bad.example.com/page"),
        good[0],
        tampered,
    ]
    write_normalized(tmp_path, "demo_src", good + bad, extra_lines=("{not json",))
    load = load_documents(DataPaths(tmp_path), load_registry(registry_path), "demo_src", None)
    assert [d.doc_id for d in load.documents] == [d.doc_id for d in good]
    assert dict(load.skipped) == {
        "source_mismatch": 1,
        "link_only": 1,
        "language_not_indexed": 1,
        "excluded_domain": 1,
        "duplicate_doc_id": 1,
        "checksum_mismatch": 1,
        "invalid_document": 1,
    }
    limited = load_documents(DataPaths(tmp_path), load_registry(registry_path), "demo_src", 2)
    assert len(limited.documents) == 2


async def test_day_quota_mid_build_then_resume_repeats_zero_embeddings(
    tmp_path, registry_path, client, sparse
):
    """Gate rag.resume_repeat_embeds at the build level (quota stop, then the printed resume command)."""
    docs = [make_doc(f"topic_{i}", title=f"Topic {i}") for i in range(10)]
    write_normalized(tmp_path / "data", "demo_src", docs)
    req = BuildRequest("2026-11-15.r", ("demo_src",), batch_size=3)
    db = tmp_path / "emb.sqlite3"
    first = SpyLLM(fail_on_call=3, failure=UpstreamRateLimited("quota", scope="day", retry_after_s=None))
    with EmbeddingCache(db) as cache:
        builder = _builder(tmp_path, registry_path, client, sparse, first, cache, batch=3, quota_limited=True)
        with pytest.raises(EmbeddingQuotaExhausted):
            await builder.build(req)
    state = read_build_state(DataPaths(tmp_path / "data"), req.collection)
    assert state.status == "quota_exhausted"
    assert state.indexed_chunks == 6
    assert state.resume_command == "python -m rag build --corpus-version 2026-11-15.r --sources demo_src"

    second = SpyLLM()
    with EmbeddingCache(db) as cache:
        builder = _builder(tmp_path, registry_path, client, sparse, second, cache, batch=3)
        report = await builder.build(req)
    assert len(set(first.embedded) & set(second.embedded)) == 0  # repeat_embedding_calls_on_resume == 0
    assert report.cache_hits == 6
    assert report.embedded == report.chunks - 6
    assert await count_points(client, req.collection) == report.chunks


async def test_smaller_rebuild_prunes_stale_points(tmp_path, registry_path, client, sparse):
    write_normalized(tmp_path / "data", "demo_src", corpus_docs())
    with EmbeddingCache(tmp_path / "emb.sqlite3") as cache:
        builder = _builder(tmp_path, registry_path, client, sparse, SpyLLM(), cache)
        await builder.build(BuildRequest("v2", ("demo_src",)))
        report = await builder.build(BuildRequest("v2", ("demo_src",), limit=2))
    assert report.pruned == 2
    assert await count_points(client, "ausculta_corpus_v2") == 2


async def test_live_collection_and_schema_mismatch_are_refused(tmp_path, registry_path, client, sparse):
    write_normalized(tmp_path / "data", "demo_src", corpus_docs())
    with EmbeddingCache(tmp_path / "emb.sqlite3") as cache:
        builder = _builder(tmp_path, registry_path, client, sparse, SpyLLM(), cache)
        await builder.build(BuildRequest("v3", ("demo_src",)))
        await switch_alias(client, ALIAS, "ausculta_corpus_v3")
        with pytest.raises(IndexMismatch, match="live"):
            await builder.build(BuildRequest("v3", ("demo_src",)))
    await ensure_collection(client, "small_dim", dim=8)
    with pytest.raises(IndexMismatch, match="size 768"):
        await ensure_collection(client, "small_dim", dim=768)
    with pytest.raises(IndexMismatch, match="does not exist"):
        await switch_alias(client, ALIAS, "missing_collection")


def test_build_request_validation():
    with pytest.raises(ValueError, match="source"):
        BuildRequest("v1", ())
    with pytest.raises(ValueError, match="limit"):
        BuildRequest("v1", ("demo_src",), limit=0)
    with pytest.raises(Exception, match="invalid corpus version"):
        BuildRequest("../evil", ("demo_src",))
    assert (
        BuildRequest("v1", ("a_b", "c_d"), limit=5).resume_command().endswith("--sources a_b,c_d --limit 5")
    )
