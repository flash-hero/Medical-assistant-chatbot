"""LLMProvider wrappers for running without the Gemini API (daily quota spent, or no network).

CacheOnlyLLM   every call fails like a spent daily quota, so `rag build --cache-only` succeeds only when all
               embeddings are already in the persistent cache, and otherwise stops cleanly with the usual
               resume message. Guarantees zero API calls.
StandInLLM     returns REAL document vectors from the embedding cache as query vectors (picked by a hash of
               the query text). Only for latency measurements of the Qdrant stage when query embeddings
               cannot be computed: rankings produced with it are meaningless and must never be scored.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping, Sequence

from core.errors import UpstreamBadRequest, UpstreamRateLimited
from core.models import ModelRole
from core.ports import DecisionQuestion, DecisionResult, GenerationChunk, GenerationRequest, GenerationResult
from rag.embed_cache import EmbeddingCache

CACHE_ONLY_MESSAGE = "cache-only mode: the embedding API is disabled"


class CacheOnlyLLM:
    def __init__(self) -> None:
        self.refused_calls = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.refused_calls += 1
        raise UpstreamBadRequest("cache-only mode: generation is disabled")

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        self.refused_calls += 1
        raise UpstreamBadRequest("cache-only mode: generation is disabled")
        yield GenerationChunk(text="")  # pragma: no cover - makes this an async generator

    async def decide(
        self, role: ModelRole, input_text: str, questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        self.refused_calls += 1
        raise UpstreamBadRequest("cache-only mode: decisions are disabled")

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        self.refused_calls += 1
        raise UpstreamRateLimited(CACHE_ONLY_MESSAGE, scope="day", retry_after_s=None)


class StandInLLM(CacheOnlyLLM):
    """Query vectors borrowed from cached document embeddings (latency benchmarks only)."""

    def __init__(self, vectors: Sequence[Sequence[float]]) -> None:
        super().__init__()
        if not vectors:
            raise ValueError("StandInLLM needs at least one cached vector")
        self._vectors = [list(v) for v in vectors]
        self.embedded_texts = 0

    @classmethod
    def from_cache(cls, cache: EmbeddingCache, model: str, dim: int, keys: Sequence[str]) -> StandInLLM:
        return cls(list(cache.get_many(model, dim, keys).values()))

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        out = []
        for text in texts:
            h = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
            vec = self._vectors[h % len(self._vectors)]
            if len(vec) != dim:
                raise UpstreamBadRequest(f"stand-in vector has {len(vec)} dims, expected {dim}")
            out.append(list(vec))
        self.embedded_texts += len(texts)
        return out
