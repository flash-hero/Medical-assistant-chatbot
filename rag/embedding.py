"""Embeddings through core.ports.LLMProvider.embed (never the SDK directly).

DocumentEmbedder  bulk, resumable: persistent cache keyed by (model id, dim, chunk checksum), one provider
                  call per batch (<= 90 texts = one free-tier throttle window), each batch committed at once.
                  Per-minute 429: wait retry_after_s (or 60 s) and continue. Daily 429: stop cleanly with
                  EmbeddingQuotaExhausted (progress is already cached; re-running resumes).
QueryEmbedder     online: EMBED_QUERY_PREFIX, in-process LRU+TTL cache, optional persistent cache (evals).
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
from typing import Generic, TypeVar

import structlog

from core.errors import UpstreamError, UpstreamRateLimited, UpstreamTimeout, UpstreamUnavailable
from core.models import EMBED_DIM, EMBED_QUERY_PREFIX, ModelRole, model_for
from core.ports import LLMProvider
from core.schemas.document import Chunk
from core.text import sanitize
from rag.embed_cache import EmbeddingCache
from rag.errors import EmbeddingQuotaExhausted

log = structlog.get_logger(__name__)

K = TypeVar("K")
V = TypeVar("V")
Sleep = Callable[[float], Awaitable[None]]

DEFAULT_BATCH = 90  # one free-tier throttle window (provider budgets 90 texts/min)
DEFAULT_RATE_LIMIT_WAIT_S = 60.0
TRANSIENT_WAIT_S = 15.0


def embed_model_id(backend: str = "gemini") -> str:
    """Model id used as the embedding-cache namespace. The fake backend gets its own namespace so fake
    vectors can never be served as real ones from a shared cache."""
    model = model_for(ModelRole.EMBED).model_id
    return model if backend == "gemini" else f"{backend}/{model}"


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
        llm: LLMProvider,
        cache: EmbeddingCache,
        *,
        model_id: str | None = None,
        dim: int = EMBED_DIM,
        batch_size: int = DEFAULT_BATCH,
        sleep: Sleep = asyncio.sleep,
        max_waits: int = 30,
        default_wait_s: float = DEFAULT_RATE_LIMIT_WAIT_S,
        transient_wait_s: float = TRANSIENT_WAIT_S,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._llm = llm
        self._cache = cache
        self._model = model_id or embed_model_id()
        self._dim = dim
        self._batch = batch_size
        self._sleep = sleep
        self._max_waits = max_waits
        self._default_wait_s = default_wait_s
        self._transient_wait_s = transient_wait_s

    @property
    def model_id(self) -> str:
        return self._model

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
        waits, waited, calls = 0, 0.0, 0
        while True:
            calls += 1
            try:
                vectors = await self._llm.embed(texts, dim=self._dim)
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
        llm: LLMProvider,
        *,
        model_id: str | None = None,
        dim: int = EMBED_DIM,
        maxsize: int = 2048,
        ttl_s: float = 3600.0,
        persistent: EmbeddingCache | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._model = model_id or embed_model_id()
        self._dim = dim
        self._memory: TTLCache[str, tuple[float, ...]] = TTLCache(maxsize, ttl_s, clock=clock)
        self._persistent = persistent

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
            vectors = await self._llm.embed([by_key[k] for k in todo], dim=self._dim)
            api_ms = (time.perf_counter() - t0) * 1000
            _check_vectors(vectors, len(todo), self._dim)
            for k, vec in zip(todo, vectors, strict=True):
                found[k] = tuple(vec)
                self._memory.put(k, found[k])
            if self._persistent is not None:
                self._persistent.put_many(self._model, self._dim, {k: found[k] for k in todo})
        return QueryVectors(tuple(found[k] for k in keys), api_ms, hits, len(keys) - hits)
