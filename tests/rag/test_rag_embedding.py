import math

import pytest
from rag_fixtures import SpyLLM, make_doc

from core.errors import UpstreamRateLimited, UpstreamUnavailable
from core.models import EMBED_DIM, EMBED_QUERY_PREFIX
from evals.fakes.fake_llm import FakeLLMProvider
from rag.chunking import ChunkerConfig, chunk_document
from rag.embed_cache import EmbeddingCache
from rag.embedding import DocumentEmbedder, QueryEmbedder, TTLCache, query_cache_key
from rag.errors import EmbeddingQuotaExhausted

MODEL = "test-embed-model"


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _chunks(n_docs: int = 6):
    cfg = ChunkerConfig(small_section_tokens=0)  # one chunk per section -> 3 chunks per doc
    out = []
    for i in range(n_docs):
        out.extend(chunk_document(make_doc(f"topic_{i}", title=f"Topic {i}"), publisher="P", config=cfg))
    return out


@pytest.fixture
def cache(tmp_path):
    with EmbeddingCache(tmp_path / "emb.sqlite3") as c:
        yield c


def test_cache_roundtrip_and_validation(cache):
    cache.put_many(MODEL, 3, {"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    assert cache.get_many(MODEL, 3, ["a", "b", "c"]) == {"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]}
    assert cache.get_many(MODEL, 4, ["a"]) == {}
    assert cache.get_many("other", 3, ["a"]) == {}
    assert cache.count(MODEL, 3) == 2
    assert cache.count() == 2
    with pytest.raises(ValueError, match="dims"):
        cache.put_many(MODEL, 3, {"x": [1.0]})
    with pytest.raises(ValueError, match="NaN"):
        cache.put_many(MODEL, 3, {"x": [math.nan, 0.0, 0.0]})


async def test_second_build_makes_zero_embedding_calls(cache):
    chunks = _chunks()
    spy = SpyLLM()
    emb = DocumentEmbedder(spy, cache, model_id=MODEL, batch_size=5)
    first = await emb.embed_chunks(chunks)
    assert first.embedded == len(chunks)
    assert first.cache_hits == 0
    assert spy.embed_calls == math.ceil(len(chunks) / 5)
    assert all(len(v) == EMBED_DIM for v in first.vectors.values())

    spy2 = SpyLLM()
    second = await DocumentEmbedder(spy2, cache, model_id=MODEL, batch_size=5).embed_chunks(chunks)
    assert spy2.embed_calls == 0
    assert second.cache_hits == len(chunks)
    assert second.vectors.keys() == first.vectors.keys()


async def test_killed_build_resumes_with_zero_repeat_embedding_calls(tmp_path):
    """Gate rag.resume_repeat_embeds: texts embedded before a kill are never sent again on resume."""
    chunks = _chunks()
    db = tmp_path / "resume.sqlite3"
    killed = SpyLLM(fail_on_call=4, failure=KeyboardInterrupt())
    with EmbeddingCache(db) as c1, pytest.raises(KeyboardInterrupt):
        await DocumentEmbedder(killed, c1, model_id=MODEL, batch_size=4).embed_chunks(chunks)
    assert len(killed.embedded) == 12  # three committed batches before the kill

    resumed = SpyLLM()
    with EmbeddingCache(db) as c2:  # fresh connection, as after a process restart
        out = await DocumentEmbedder(resumed, c2, model_id=MODEL, batch_size=4).embed_chunks(chunks)
    repeat_calls = len(set(killed.embedded) & set(resumed.embedded))
    assert repeat_calls == 0
    assert len(resumed.embedded) == len(chunks) - 12
    assert out.cache_hits == 12
    assert len(out.vectors) == len(chunks)


async def test_minute_rate_limit_waits_retry_after_then_continues(cache):
    fake = FakeLLMProvider(
        embed_failures_remaining=2,
        embed_error=UpstreamRateLimited("rl", scope="minute", retry_after_s=47.0),
    )
    sleep = FakeSleep()
    out = await DocumentEmbedder(fake, cache, model_id=MODEL, batch_size=50, sleep=sleep).embed_chunks(
        _chunks(2)
    )
    assert sleep.calls == [47.0, 47.0]
    assert out.embedded == 6
    assert out.waited_s == 94.0


async def test_rate_limit_without_hint_waits_default_and_transient_errors_wait(cache):
    fake = FakeLLMProvider(
        embed_failures_remaining=1, embed_error=UpstreamRateLimited("rl", scope="unknown", retry_after_s=None)
    )
    sleep = FakeSleep()
    await DocumentEmbedder(fake, cache, model_id=MODEL, sleep=sleep).embed_chunks(_chunks(1))
    assert sleep.calls == [60.0]
    fake2 = FakeLLMProvider(embed_failures_remaining=1, embed_error=UpstreamUnavailable("503"))
    sleep2 = FakeSleep()
    await DocumentEmbedder(fake2, cache, model_id=MODEL + "2", sleep=sleep2).embed_chunks(_chunks(1))
    assert sleep2.calls == [15.0]


async def test_day_quota_stops_cleanly_with_progress_saved(cache):
    chunks = _chunks()
    spy = SpyLLM(fail_on_call=3, failure=UpstreamRateLimited("day", scope="day", retry_after_s=None))
    with pytest.raises(EmbeddingQuotaExhausted) as info:
        await DocumentEmbedder(spy, cache, model_id=MODEL, batch_size=4).embed_chunks(chunks)
    assert info.value.embedded == 8
    assert info.value.remaining == len(chunks) - 8
    assert info.value.scope == "day"
    assert cache.count(MODEL, EMBED_DIM) == 8


async def test_persistent_minute_limit_gives_up_after_max_waits(cache):
    fake = FakeLLMProvider(
        embed_failures_remaining=100, embed_error=UpstreamRateLimited("rl", scope="minute", retry_after_s=1.0)
    )
    sleep = FakeSleep()
    emb = DocumentEmbedder(fake, cache, model_id=MODEL, sleep=sleep, max_waits=3)
    with pytest.raises(EmbeddingQuotaExhausted) as info:
        await emb.embed_chunks(_chunks(1))
    assert info.value.scope == "minute"
    assert len(sleep.calls) == 3


async def test_bad_vector_shape_from_provider_is_rejected(cache):
    class Broken(FakeLLMProvider):
        async def embed(self, texts, *, dim):
            return [[0.0] * (dim - 1) for _ in texts]

    with pytest.raises(Exception, match="mismatch"):
        await DocumentEmbedder(Broken(), cache, model_id=MODEL).embed_chunks(_chunks(1))


def test_ttl_cache_lru_and_expiry():
    now = [0.0]
    c: TTLCache[str, int] = TTLCache(maxsize=2, ttl_s=10, clock=lambda: now[0])
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1  # a becomes most recent
    c.put("c", 3)  # evicts b
    assert c.get("b") is None
    assert len(c) == 2
    now[0] = 11
    assert c.get("a") is None
    assert c.get("c") is None


async def test_query_embedder_prefixes_batches_and_caches(tmp_path):
    spy = SpyLLM()
    now = [0.0]
    with EmbeddingCache(tmp_path / "q.sqlite3") as persistent:
        qe = QueryEmbedder(spy, model_id=MODEL, ttl_s=100, persistent=persistent, clock=lambda: now[0])
        first = await qe.embed(["What is  asthma?", "asthma symptoms"])
        assert spy.embedded == [
            f"{EMBED_QUERY_PREFIX}What is asthma?",
            f"{EMBED_QUERY_PREFIX}asthma symptoms",
        ]
        assert spy.embed_calls == 1
        assert first.misses == 2
        assert first.api_ms >= 0
        again = await qe.embed(["What is asthma?"])
        assert spy.embed_calls == 1
        assert again.cache_hits == 1
        assert again.api_ms == 0
        now[0] = 1000  # memory entry expired -> persistent cache answers
        third = await qe.embed(["What is asthma?"])
        assert spy.embed_calls == 1
        assert third.cache_hits == 1
        assert third.vectors[0] == pytest.approx(first.vectors[0], abs=1e-6)
        assert query_cache_key("What is  asthma?") == query_cache_key("What is asthma?")


async def test_query_embedder_rejects_empty_query():
    qe = QueryEmbedder(SpyLLM(), model_id=MODEL)
    with pytest.raises(ValueError, match="empty"):
        await qe.embed(["   "])


def test_fake_backend_uses_a_separate_cache_namespace():
    from rag.embedding import embed_model_id

    assert embed_model_id("gemini") == "gemini-embedding-2"
    assert embed_model_id("fake") == "fake/gemini-embedding-2"
