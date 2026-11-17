"""Dry-run build planning (`python -m rag plan`): chunk sources exactly as a build would, then count how many
embeddings are still missing from the persistent cache. No embedding call (the model is not even loaded), no
Qdrant call, nothing written. The ETA uses the configured backend's rate (local CPU or Gemini throttle).

The embedding cache is keyed by chunk checksum, so identical chunk texts (repeated sections across pages)
are embedded once; `to_embed` counts unique missing checksums, which is what a build actually sends.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from core.models import EMBED_DIM
from rag.build import load_documents
from rag.chunking import DEFAULT_CONFIG, ChunkerConfig, chunk_document, publisher_label
from rag.embed_cache import EmbeddingCache
from rag.errors import CorpusNotReady, SourceNotIndexable
from rag.paths import DataPaths
from rag.registry import Registry

FREE_TIER_TEXTS_PER_MIN = 90.0  # provider throttle (app/llm/throttle.py; quota 100/min, counted per text)
# Gemini free-tier DAILY embedding quota: 1,000 texts/day (embed_content_free_tier_requests, confirmed
# 2026-11-16, ADR 0003). A build stops cleanly with exit 3 on a day-scope 429 and resumes with zero repeats.
FREE_TIER_TEXTS_PER_DAY = 1000
# Local EmbeddingGemma-300M on the dev laptop CPU (i7-11800H, batch 16, ~260-token chunks): spike S7,
# ADR 0003.
LOCAL_CPU_CHUNKS_PER_S = 2.7


def default_rate_per_min(backend: str) -> float:
    """Expected embeddings per minute: the Gemini throttle, or measured local CPU throughput."""
    return FREE_TIER_TEXTS_PER_MIN if backend == "gemini" else LOCAL_CPU_CHUNKS_PER_S * 60


@dataclass(frozen=True)
class SourcePlan:
    source_id: str
    # "ready" | "not_ready" (no ready marker; counted only on request) | "missing" | "not_indexable"
    status: str
    documents: int = 0
    chunks: int = 0
    unique_chunks: int = 0
    cached: int = 0
    tokens: int = 0
    skipped: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    note: str = ""

    @property
    def to_embed(self) -> int:
        return self.unique_chunks - self.cached

    @property
    def tokens_to_embed(self) -> int:
        """Estimated chunk-text tokens of the missing embeddings (pro rata over this source's chunks)."""
        return round(self.tokens * self.to_embed / self.chunks) if self.chunks else 0


@dataclass(frozen=True)
class BuildPlan:
    sources: tuple[SourcePlan, ...]
    rate_per_min: float = FREE_TIER_TEXTS_PER_MIN
    daily_cap: int | None = None  # quota-limited backends only (Gemini free tier)

    def buildable(self) -> tuple[SourcePlan, ...]:
        return tuple(s for s in self.sources if s.status == "ready")

    def total(self, attr: str, *, buildable_only: bool = True) -> int:
        group = self.buildable() if buildable_only else self.sources
        return sum(int(getattr(s, attr)) for s in group)

    def eta_minutes(self) -> float:
        return self.total("to_embed") / self.rate_per_min

    def tokens_per_minute(self) -> float:
        """Average embedding input tokens per minute at `rate_per_min` (to compare with a TPM quota)."""
        to_embed = self.total("to_embed")
        return self.total("tokens_to_embed") / to_embed * self.rate_per_min if to_embed else 0.0

    def cost_usd(self, usd_per_m_tokens: float) -> float:
        return self.total("tokens_to_embed") / 1_000_000 * usd_per_m_tokens

    def days_at_cap(self) -> float | None:
        if not self.daily_cap:
            return None
        return math.ceil(self.total("to_embed") / self.daily_cap * 10) / 10


def _status(paths: DataPaths, registry: Registry, source_id: str) -> str:
    try:
        registry.require_indexable(source_id)
    except SourceNotIndexable:
        return "not_indexable"
    if not paths.normalized_file(source_id).exists():
        return "missing"
    return "ready" if paths.ready_marker(source_id).exists() else "not_ready"


def plan_source(
    paths: DataPaths,
    registry: Registry,
    source_id: str,
    cache: EmbeddingCache,
    *,
    model_id: str,
    dim: int = EMBED_DIM,
    limit: int | None = None,
    include_unready: bool = False,
    chunker: ChunkerConfig = DEFAULT_CONFIG,
) -> SourcePlan:
    status = _status(paths, registry, source_id)
    if status in ("missing", "not_indexable") or (status == "not_ready" and not include_unready):
        return SourcePlan(source_id, status, note="not counted")
    record = registry.require_indexable(source_id)
    try:
        load = load_documents(paths, registry, source_id, limit, require_ready=status == "ready")
    except CorpusNotReady as exc:  # file vanished between the check and the read
        return SourcePlan(source_id, "missing", note=str(exc))
    chunks = [
        c
        for d in load.documents
        for c in chunk_document(d, publisher=publisher_label(d.attribution, record.name), config=chunker)
    ]
    unique = list(dict.fromkeys(c.checksum for c in chunks))
    cached = len(cache.get_many(model_id, dim, unique))
    return SourcePlan(
        source_id=source_id,
        status=status,
        documents=len(load.documents),
        chunks=len(chunks),
        unique_chunks=len(unique),
        cached=cached,
        tokens=sum(c.token_estimate for c in chunks),
        skipped=load.skipped,
    )


def plan_build(
    paths: DataPaths,
    registry: Registry,
    sources: Sequence[str],
    cache: EmbeddingCache,
    *,
    model_id: str,
    limit: int | None = None,
    include_unready: bool = False,
    rate_per_min: float = FREE_TIER_TEXTS_PER_MIN,
    daily_cap: int | None = None,
) -> BuildPlan:
    plans = tuple(
        plan_source(
            paths, registry, s, cache, model_id=model_id, limit=limit, include_unready=include_unready
        )
        for s in sources
    )
    return BuildPlan(plans, rate_per_min=rate_per_min, daily_cap=daily_cap)


def active_sources(registry: Registry) -> tuple[str, ...]:
    return tuple(sorted(sid for sid, rec in registry.records.items() if rec.indexable))
