"""Embeddings through core.ports.EmbeddingProvider (never an SDK directly). ADR 0003: ONE model embeds both
documents and queries; by default google/embeddinggemma-300m on this machine's CPU (AUSCULTA_EMBED_BACKEND).

EmbeddingBackend  the deployment's embedding model: provider + cache namespace + whether it is quota-limited.
                  Built by embedding_backend(settings) through app.llm.factory.build_embedding_provider.
DocumentEmbedder  bulk, resumable: persistent cache keyed by (namespace, dim, chunk checksum), one provider
                  call per batch, each batch committed at once (a killed build resumes with zero repeats).
                  Quota-limited backends (Gemini API) only: per-minute 429 -> wait retry_after_s (or 60 s) and
                  continue; daily 429 -> stop cleanly with EmbeddingQuotaExhausted. The local backend has no
                  quota and no throttle: its errors propagate at once (re-running resumes from the cache).
QueryEmbedder     online: EMBED_QUERY_PREFIX, in-process LRU+TTL cache, optional persistent cache (evals).

Cache namespace (review P19): "<model id>@<EMBED_TEXT_FORMAT>". Vectors of different models never mix, and
changing what is sent to the model (Chunk.embedding_text() template, EMBED_QUERY_PREFIX, query
normalisation) must bump EMBED_TEXT_FORMAT so vectors of the old text are never served for the new one.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Generic, TypeVar

import structlog

from core.errors import UpstreamError, UpstreamRateLimited, UpstreamTimeout, UpstreamUnavailable
from core.models import EMBED_DIM, EMBED_QUERY_PREFIX, embedding_spec
from core.ports import EmbeddingProvider
from core.schemas.document import Chunk
from core.text import sanitize
from rag.embed_cache import EmbeddingCache
from rag.errors import EmbeddingQuotaExhausted

if TYPE_CHECKING:
    from core.config import Settings
    from core.ports import LLMProvider

log = structlog.get_logger(__name__)

K = TypeVar("K")
V = TypeVar("V")
Sleep = Callable[[float], Awaitable[None]]

DEFAULT_BATCH = 90  # texts per provider call and per committed cache batch (= one Gemini free-tier window)
DEFAULT_RATE_LIMIT_WAIT_S = 60.0
TRANSIENT_WAIT_S = 15.0
# Version of the text sent to the embedding model; part of the cache namespace (review P19). Bump it when
# Chunk.embedding_text(), EMBED_QUERY_PREFIX or normalize_query() change what a model receives.
# fmt1 = documents "title: {title} | text: {context_header}\n{text}", queries EMBED_QUERY_PREFIX + query.
EMBED_TEXT_FORMAT = "fmt1"
QUOTA_LIMITED_BACKENDS = frozenset({"gemini"})


def embed_model_id(backend: str) -> str:
    """Embedding-cache namespace and manifest `embed_model` of a backend: "<model id>@<text format>".

    The model id comes from core.models.embedding_spec, so the local, Gemini and fake backends each have
    their own namespace and fake or other-model vectors can never be served from a shared cache."""
    return f"{embedding_spec(backend).model_id}@{EMBED_TEXT_FORMAT}"


@dataclass(frozen=True)
class EmbeddingBackend:
    """The deployment's single embedding model (documents AND queries, ADR 0003)."""

    name: str  # "local" | "gemini" | "fake"
    provider: EmbeddingProvider
    model_id: str  # cache namespace / manifest embed_model, see embed_model_id()
    quota_limited: bool  # True only for the Gemini API (per-minute and daily quotas)
    dim: int = EMBED_DIM

    def document_embedder(
        self, cache: EmbeddingCache, *, batch_size: int = DEFAULT_BATCH
    ) -> DocumentEmbedder:
        return DocumentEmbedder(
            self.provider,
            cache,
            model_id=self.model_id,
            dim=self.dim,
            batch_size=batch_size,
            quota_limited=self.quota_limited,
        )

    def query_embedder(self, *, persistent: EmbeddingCache | None = None) -> QueryEmbedder:
        return QueryEmbedder(self.provider, model_id=self.model_id, dim=self.dim, persistent=persistent)

    async def aclose(self) -> None:
        closer = getattr(self.provider, "aclose", None)
        if closer is not None:
            await closer()


def embedding_backend(
    settings: Settings, *, llm: LLMProvider | None = None, provider: EmbeddingProvider | None = None
) -> EmbeddingBackend:
    """The backend selected by AUSCULTA_EMBED_BACKEND. `provider` replaces the real one (cache-only builds,
    tests); otherwise app.llm.factory.build_embedding_provider builds it (`llm` is reused for "gemini")."""
    name = settings.embed_backend
    if provider is None:
        from app.llm.factory import build_embedding_provider

        provider = build_embedding_provider(settings, llm=llm)
    return EmbeddingBackend(
        name=name,
        provider=provider,
        model_id=embed_model_id(name),
        quota_limited=name in QUOTA_LIMITED_BACKENDS,
        dim=embedding_spec(name).dim,
    )


def _check_vectors(vectors: Sequence[Sequence[float]], expected: int, dim: int) -> None:
    if len(vectors) != expected or any(len(v) != dim for v in vectors):
        raise UpstreamError(f"embedding count/dim mismatch: got {len(vectors)} for {expected} at dim {dim}")
    if any(not math.isfinite(x) for v in vectors for x in v):
        raise UpstreamError("embedding contains non-finite values")


@dataclass(frozen=True)
class EmbedOutcome:
    vectors: Mapping[str, list[float]]  # key -> unit vector
    cache_hits: int
    embedded: int
    api_calls: int
    waited_s: float


class DocumentEmbedder:
    def __init__(
        self,
        provider: EmbeddingProvider,
        cache: EmbeddingCache,
        *,
        model_id: str,
        dim: int = EMBED_DIM,
        batch_size: int = DEFAULT_BATCH,
        quota_limited: bool = False,
        sleep: Sleep = asyncio.sleep,
        max_waits: int = 30,
        default_wait_s: float = DEFAULT_RATE_LIMIT_WAIT_S,
        transient_wait_s: float = TRANSIENT_WAIT_S,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if not model_id:
            raise ValueError("model_id (the embedding-cache namespace) is required")
        self._provider = provider
        self._cache = cache
        self._model = model_id
        self._dim = dim
        self._batch = batch_size
        self._quota_limited = quota_limited
        self._sleep = sleep
        self._max_waits = max_waits
        self._default_wait_s = default_wait_s
        self._transient_wait_s = transient_wait_s

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def quota_limited(self) -> bool:
        return self._quota_limited

    async def embed_chunks(self, chunks: Sequence[Chunk]) -> EmbedOutcome:
        return await self.embed_texts([(c.checksum, c.embedding_text()) for c in chunks])

    async def embed_texts(self, items: Sequence[tuple[str, str]]) -> EmbedOutcome:
        """Embed (key, text) pairs, reusing cached vectors. Keys must identify the text exactly."""
        unique = dict(items)
        vectors = dict(self._cache.get_many(self._model, self._dim, unique))
        hits = len(vectors)
        missing = [(k, t) for k, t in unique.items() if k not in vectors]
        api_calls, embedded, waited = 0, 0, 0.0
        for start in range(0, len(missing), self._batch):
            batch = missing[start : start + self._batch]
            try:
                fresh, calls, slept = await self._call([t for _, t in batch])
            except EmbeddingQuotaExhausted as exc:
                raise EmbeddingQuotaExhausted(
                    str(exc), embedded=embedded, remaining=len(missing) - embedded, scope=exc.scope
                ) from exc
            api_calls, waited = api_calls + calls, waited + slept
            new = {k: v for (k, _), v in zip(batch, fresh, strict=True)}
            self._cache.put_many(self._model, self._dim, new)  # committed: survives a kill
            vectors.update(new)
            embedded += len(new)
        return EmbedOutcome(MappingProxyType(vectors), hits, embedded, api_calls, waited)

    async def _call(self, texts: list[str]) -> tuple[list[list[float]], int, float]:
        if not self._quota_limited:  # local inference: no quota, no throttle, nothing worth waiting for
            vectors = await self._provider.embed(texts, dim=self._dim)
            _check_vectors(vectors, len(texts), self._dim)
            return vectors, 1, 0.0
        waits, waited, calls = 0, 0.0, 0
        while True:
            calls += 1
            try:
                vectors = await self._provider.embed(texts, dim=self._dim)
                _check_vectors(vectors, len(texts), self._dim)
                return vectors, calls, waited
            except UpstreamRateLimited as exc:
                if exc.scope == "day":
                    raise EmbeddingQuotaExhausted(
                        "daily embedding quota exhausted", embedded=0, remaining=len(texts), scope="day"
                    ) from exc
                delay = exc.retry_after_s or self._default_wait_s
            except (UpstreamTimeout, UpstreamUnavailable):
                delay = self._transient_wait_s
            waits += 1
            if waits > self._max_waits:
                raise EmbeddingQuotaExhausted(
                    "embedding rate limit did not clear", embedded=0, remaining=len(texts), scope="minute"
                )
            log.warning("embed_wait", delay_s=delay, attempt=waits, batch=len(texts))
            await self._sleep(delay)
            waited += delay


# ---- queries -----------------------------------------------------------------------------------------
class TTLCache(Generic[K, V]):
    """Small LRU cache with per-entry time-to-live (in-process, single event loop)."""

    def __init__(self, maxsize: int, ttl_s: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._max = maxsize
        self._ttl = ttl_s
        self._clock = clock
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K) -> V | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if self._clock() >= expires:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: K, value: V) -> None:
        self._data[key] = (self._clock() + self._ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


def normalize_query(query: str) -> str:
    return " ".join(sanitize(query).text.split())


def prefixed_query(query: str) -> str:
    return f"{EMBED_QUERY_PREFIX}{normalize_query(query)}"


def query_cache_key(query: str) -> str:
    return hashlib.sha256(prefixed_query(query).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QueryVectors:
    vectors: tuple[tuple[float, ...], ...]
    api_ms: float  # wall time of the provider call; 0.0 when everything came from a cache
    cache_hits: int
    misses: int


class QueryEmbedder:
    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        model_id: str,
        dim: int = EMBED_DIM,
        maxsize: int = 2048,
        ttl_s: float = 3600.0,
        persistent: EmbeddingCache | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not model_id:
            raise ValueError("model_id (the embedding-cache namespace) is required")
        self._provider = provider
        self._model = model_id
        self._dim = dim
        self._memory: TTLCache[str, tuple[float, ...]] = TTLCache(maxsize, ttl_s, clock=clock)
        self._persistent = persistent

    @property
    def model_id(self) -> str:
        return self._model

    async def warmup(self) -> None:
        """Load the embedding model now (local backend: ~1.2 GB read once) instead of on the first query."""
        warm = getattr(self._provider, "warmup", None)
        if warm is not None:
            await warm()

    def _lookup(self, keys: Sequence[str]) -> dict[str, tuple[float, ...]]:
        found = {k: v for k in keys if (v := self._memory.get(k)) is not None}
        rest = [k for k in keys if k not in found]
        if rest and self._persistent is not None:
            for k, vec in self._persistent.get_many(self._model, self._dim, rest).items():
                found[k] = tuple(vec)
                self._memory.put(k, found[k])
        return found

    async def embed(self, queries: Sequence[str]) -> QueryVectors:
        texts = [prefixed_query(q) for q in queries]
        if any(t == EMBED_QUERY_PREFIX for t in texts):
            raise ValueError("cannot embed an empty query")
        keys = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
        found = self._lookup(list(dict.fromkeys(keys)))
        hits = sum(1 for k in keys if k in found)
        todo = list(dict.fromkeys(k for k in keys if k not in found))
        api_ms = 0.0
        if todo:
            by_key = dict(zip(keys, texts, strict=True))
            t0 = time.perf_counter()
            vectors = await self._provider.embed([by_key[k] for k in todo], dim=self._dim)
            api_ms = (time.perf_counter() - t0) * 1000
            _check_vectors(vectors, len(todo), self._dim)
            for k, vec in zip(todo, vectors, strict=True):
                found[k] = tuple(vec)
                self._memory.put(k, found[k])
            if self._persistent is not None:
                self._persistent.put_many(self._model, self._dim, {k: found[k] for k in todo})
        return QueryVectors(tuple(found[k] for k in keys), api_ms, hits, len(keys) - hits)
