"""Local embedding provider: EmbeddingGemma-300M (ONNX via fastembed) on this machine's CPU.

Why local (ADR 0003): the Gemini free tier allows 1,000 embedded texts per day, which cannot index the
corpus, and query embeddings would share that budget. The local model is free, unlimited, keeps patient
questions on the server, answers a query in ~28 ms on CPU, and scored recall@20 1.000 (nDCG@8 0.965) on the
EN/FR/AR gold set.

Inference runs in a worker thread (never on the event loop) behind a lock: the ONNX session is shared and
queries are short, so serialising is simpler and safe. Failures surface as UpstreamUnavailable, which the
retriever already treats as "dense unavailable, degrade to sparse".
"""

from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

from core.errors import UpstreamUnavailable

DEFAULT_BATCH_SIZE = 16  # measured sweet spot on an 8-core laptop CPU for ~260-token chunks


class _Model(Protocol):
    def embed(self, documents: Iterable[str], batch_size: int = ...) -> Iterable[Any]: ...


ModelFactory = Callable[[], _Model]


def fastembed_factory(model_id: str, cache_dir: Path, threads: int | None) -> ModelFactory:
    def build() -> _Model:
        from fastembed import TextEmbedding  # heavy import: only when the model is first needed

        return TextEmbedding(model_id, cache_dir=str(cache_dir), threads=threads)

    return build


class LocalEmbeddingProvider:
    def __init__(
        self,
        model_id: str,
        dim: int,
        factory: ModelFactory,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._model_id = model_id
        self._dim = dim
        self._factory = factory
        self._batch_size = batch_size
        self._model: _Model | None = None
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return self._model_id

    async def warmup(self) -> None:
        """Load the model before the first request (first load reads ~1.2 GB from disk)."""
        await asyncio.to_thread(self._ensure_model)

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        if dim != self._dim:
            raise ValueError(f"{self._model_id} produces {self._dim}-dim vectors, {dim} requested")
        if not texts:
            return []
        try:
            return await asyncio.to_thread(self._embed_sync, list(texts))
        except (ValueError, TypeError, UpstreamUnavailable):
            raise
        except Exception as exc:  # onnxruntime / tokenizer / IO errors
            raise UpstreamUnavailable(f"local embedding failed ({type(exc).__name__})") from exc

    # ---- worker-thread side -------------------------------------------------------------------
    def _ensure_model(self) -> _Model:
        with self._lock:
            if self._model is None:
                self._model = self._factory()
            return self._model

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        with self._lock:
            raw = list(model.embed(texts, batch_size=self._batch_size))
        if len(raw) != len(texts):
            raise UpstreamUnavailable(f"local embedding returned {len(raw)} vectors for {len(texts)} texts")
        vectors = [_unit([float(x) for x in v]) for v in raw]
        if any(len(v) != self._dim for v in vectors):
            raise UpstreamUnavailable("local embedding returned vectors of the wrong dimension")
        return vectors


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 or abs(n - 1.0) < 1e-4 else [x / n for x in v]
