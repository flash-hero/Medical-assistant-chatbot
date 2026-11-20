"""Retriever wrappers for the P4 runs.

RecordingRetriever passes every call to the real retriever and keeps the queries, results and time spans
(time.perf_counter() at start and end, query embedding included) of the current turn, so the metrics can
re-check the final answer against the exact passages the model saw (numeric grounding, judge), see what the
rewriter produced, and time the retrieval stage.
HaltingRetriever parks until the turn is cancelled: the safety suite never needs retrieval, and with it the
safety run does not load the local embedding model at all.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from core.ports import Retriever
from core.schemas.chat import RetrievalQuery, RetrievalResult


@dataclass
class RecordingRetriever:
    inner: Retriever
    results: list[RetrievalResult] = field(default_factory=list)
    queries: list[RetrievalQuery] = field(default_factory=list)
    finished: list[tuple[RetrievalQuery, RetrievalResult, float, float]] = field(default_factory=list)

    def begin_turn(self) -> None:
        self.results = []
        self.queries = []
        self.finished = []

    @property
    def corpus_version(self) -> str:
        return self.inner.corpus_version

    async def health(self) -> bool:
        return await self.inner.health()

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        started = time.perf_counter()
        result = await self.inner.retrieve(query)
        self.finished.append((query, result, started, time.perf_counter()))
        self.results.append(result)
        return result

    def turn_record(self, base: float) -> tuple[dict[str, Any], ...]:
        """Every finished retrieval of the turn: the query (as rewritten), the gate's verdict and the
        timings (`start_s` / `end_s` relative to `base`, the turn's start; the retriever's own, in ms)."""
        return tuple(
            {
                "start_s": round(start - base, 4),
                "end_s": round(end - base, 4),
                "standalone_query": query.standalone_query,
                "search_queries": list(query.search_queries),
                "language": query.language,
                "filters": {k: list(v) for k, v in query.filters.items()},
                "confident": result.confident,
                "confidence": result.confidence,
                "passages": len(result.passages),
                "timings_ms": dict(result.timings_ms),
            }
            for query, result, start, end in self.finished
        )

    async def warmup(self) -> None:
        warmup = getattr(self.inner, "warmup", None)
        if warmup is not None:
            await warmup()

    async def aclose(self) -> None:
        closer: Any = getattr(self.inner, "aclose", None) or getattr(self.inner, "close", None)
        if closer is None:
            return
        result = closer()
        if hasattr(result, "__await__"):
            await result


@dataclass
class HaltingRetriever:
    version: str = "not-loaded"
    calls: int = 0

    def begin_turn(self) -> None:
        return None

    @property
    def corpus_version(self) -> str:
        return self.version

    async def health(self) -> bool:
        return True

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.calls += 1
        await asyncio.Event().wait()  # until the turn is cancelled
        raise AssertionError("unreachable")
