"""Manifests, build state, active pointer, ActiveState hot reload, index helpers, offline providers."""

from datetime import UTC, datetime

import pytest
from qdrant_client import AsyncQdrantClient
from rag_fixtures import QDRANT_LOCAL_WARNINGS, make_doc

from core.errors import InvalidInput, UpstreamBadRequest, UpstreamRateLimited
from core.models import ModelRole
from core.ports import GenerationRequest
from rag.active import ActiveState
from rag.chunking import chunk_document
from rag.embed_cache import EmbeddingCache
from rag.index import (
    alias_target,
    chunk_from_payload,
    chunk_payload,
    ensure_collection,
    list_collections,
    point_id,
    switch_alias,
)
from rag.manifest import (
    ActivePointer,
    BuildState,
    make_manifest,
    read_active,
    read_build_state,
    read_manifest,
    sign_checksums,
    write_active,
    write_build_state,
    write_manifest,
)
from rag.offline import CacheOnlyLLM, StandInLLM
from rag.paths import DataPaths, collection_name, validate_collection, validate_source_id
from rag.retrieval_config import RetrievalConfig, save_retrieval_config

NOW = datetime(2026, 11, 16, tzinfo=UTC)


def test_signature_depends_on_every_checksum_and_needs_a_secret():
    assert sign_checksums(["b", "a"], "k") == sign_checksums(["a", "b"], "k")
    assert sign_checksums(["a", "b"], "k") != sign_checksums(["a", "c"], "k")
    assert sign_checksums(["a"], "k") != sign_checksums(["a"], "other")
    with pytest.raises(InvalidInput):
        sign_checksums(["a"], "")


def test_manifest_build_state_and_active_pointer_roundtrip(tmp_path):
    paths = DataPaths(tmp_path)
    chunks = chunk_document(make_doc("asthma"), publisher="P")
    m = make_manifest(
        corpus_version="v1",
        collection="ausculta_corpus_v1",
        chunks=chunks,
        embed_model="m",
        embed_dim=768,
        secret="s",
        created_at=NOW,
    )
    write_manifest(paths, m)
    assert read_manifest(paths, "ausculta_corpus_v1") == m
    assert read_manifest(paths, "ausculta_corpus_v2") is None
    state = BuildState(corpus_version="v1", collection="c", sources=("s",), status="indexing", updated_at=NOW)
    write_build_state(paths, state)
    assert read_build_state(paths, "c") == state
    assert read_build_state(paths, "nope") is None
    assert read_active(paths) is None
    pointer = ActivePointer(alias="a", collection="c", corpus_version="v1", promoted_at=NOW)
    write_active(paths, pointer)
    assert read_active(paths) == pointer
    paths.active_pointer.write_text("{broken", encoding="utf-8")
    assert read_active(paths) is None


def test_active_state_reloads_after_a_promotion(tmp_path):
    paths = DataPaths(tmp_path)
    now = [0.0]
    state = ActiveState(paths, min_interval_s=5.0, clock=lambda: now[0])
    assert state.corpus_version() == ""
    assert state.config() == RetrievalConfig()
    write_active(paths, ActivePointer(alias="a", collection="c1", corpus_version="v1", promoted_at=NOW))
    save_retrieval_config(paths, "c1", RetrievalConfig(rerank=True))
    assert state.corpus_version() == ""  # within the refresh interval: cached
    now[0] = 6.0
    assert state.corpus_version() == "v1"
    assert state.config().rerank
    assert state.pointer().collection == "c1"


def test_path_and_name_validation(tmp_path):
    assert collection_name("2026-11-15.1") == "ausculta_corpus_2026_11_15_1"
    with pytest.raises(InvalidInput):
        collection_name("../x")
    with pytest.raises(InvalidInput):
        validate_source_id("Bad-Id")
    with pytest.raises(InvalidInput):
        validate_collection("a/b")
    paths = DataPaths(tmp_path)
    assert paths.chunks_file("v1", "src").name == "src.jsonl"
    assert paths.reports_dir == tmp_path / "reports" / "retrieval"


@pytest.mark.filterwarnings(QDRANT_LOCAL_WARNINGS[0])
async def test_alias_switch_is_atomic_and_reports_the_previous_target():
    client = AsyncQdrantClient(location=":memory:")
    try:
        for name in ("c_old", "c_new"):
            assert await ensure_collection(client, name, dim=8)
        assert not await ensure_collection(client, "c_old", dim=8)  # exists: schema checked, not recreated
        assert await alias_target(client, "live") is None
        assert await switch_alias(client, "live", "c_old") is None
        assert await switch_alias(client, "live", "c_new") == "c_old"
        assert await alias_target(client, "live") == "c_new"
        assert await list_collections(client) == ["c_new", "c_old"]
    finally:
        await client.close()


def test_point_ids_are_deterministic_and_payload_roundtrips():
    chunk = chunk_document(make_doc("measles"), publisher="P")[0]
    assert point_id(chunk.chunk_id) == point_id(chunk.chunk_id)
    assert point_id(chunk.chunk_id) != point_id(chunk.chunk_id + "x")
    assert chunk_from_payload({**chunk_payload(chunk), "extra": 1}) == chunk


async def test_cache_only_llm_refuses_everything():
    llm = CacheOnlyLLM()
    with pytest.raises(UpstreamRateLimited) as info:
        await llm.embed(["x"], dim=8)
    assert info.value.scope == "day"
    request = GenerationRequest(role=ModelRole.REWRITE, system="s", prompt="p")
    with pytest.raises(UpstreamBadRequest):
        await llm.generate(request)
    with pytest.raises(UpstreamBadRequest):
        await llm.decide(ModelRole.RERANK, "x", {})
    with pytest.raises(UpstreamBadRequest):
        async for _ in llm.stream(request):
            pass
    assert llm.refused_calls == 4


async def test_stand_in_llm_serves_cached_document_vectors(tmp_path):
    with EmbeddingCache(tmp_path / "e.sqlite3") as cache:
        cache.put_many("m", 3, {"k1": [1.0, 0.0, 0.0], "k2": [0.0, 1.0, 0.0]})
        llm = StandInLLM.from_cache(cache, "m", 3, ["k1", "k2"])
    first = await llm.embed(["query a", "query b"], dim=3)
    assert first == await llm.embed(["query a", "query b"], dim=3)
    assert all(v in ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) for v in first)
    assert llm.embedded_texts == 4
    with pytest.raises(UpstreamBadRequest):
        await llm.embed(["x"], dim=4)
    with pytest.raises(ValueError):
        StandInLLM([])
