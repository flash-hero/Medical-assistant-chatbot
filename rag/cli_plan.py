"""`python -m rag plan`: dry-run chunk counts per source and the embedding time a build would need."""

from __future__ import annotations

import argparse
from typing import Any

from core.config import Settings
from core.models import EmbeddingSpec, embedding_spec
from rag.embed_cache import EmbeddingCache
from rag.embedding import embed_model_id
from rag.paths import DataPaths
from rag.plan import (
    FREE_TIER_TEXTS_PER_DAY,
    LOCAL_CPU_CHUNKS_PER_S,
    BuildPlan,
    active_sources,
    default_rate_per_min,
    plan_build,
)
from rag.registry import load_registry


def _table(plan: BuildPlan) -> list[str]:
    head = (
        f"  {'source':<22}{'status':<14}{'docs':>7}{'chunks':>8}{'unique':>8}{'cached':>8}{'to_embed':>9}"
        f"{'Mtok':>7}"
    )
    lines = [head]
    for s in plan.sources:
        lines.append(
            f"  {s.source_id:<22}{s.status:<14}{s.documents:>7}{s.chunks:>8}{s.unique_chunks:>8}"
            f"{s.cached:>8}{s.to_embed:>9}{s.tokens_to_embed / 1e6:>7.2f}"
            + (f"  skipped {dict(s.skipped)}" if s.skipped else "")
            + (f"  ({s.note})" if s.note else "")
        )
    lines.append(
        f"  {'TOTAL (ready only)':<36}{plan.total('documents'):>7}{plan.total('chunks'):>8}"
        f"{plan.total('unique_chunks'):>8}{plan.total('cached'):>8}{plan.total('to_embed'):>9}"
        f"{plan.total('tokens_to_embed') / 1e6:>7.2f}"
    )
    return lines


def _gemini_lines(plan: BuildPlan, spec: EmbeddingSpec) -> list[str]:
    lines = [
        f"Paid-tier cost estimate: ~${plan.cost_usd(spec.usd_per_m_input):,.2f} "
        f"({plan.total('tokens_to_embed') / 1e6:,.1f}M chunk tokens at ${spec.usd_per_m_input:g}/M, "
        "list price)."
    ]
    days = plan.days_at_cap()
    if days is not None:
        lines.append(f"Daily cap of {plan.daily_cap:,} texts/day: about {days:g} day(s) of quota.")
    else:
        lines.append("Daily embedding quota: none assumed (--daily-cap N for a what-if).")
    lines.append(
        "On a day-scope 429 the build stops with exit 3 (progress is in the embedding cache); re-running the "
        "same command resumes with zero repeat embeddings."
    )
    return lines


def render_plan(plan: BuildPlan, spec: EmbeddingSpec) -> list[str]:
    minutes = plan.eta_minutes()
    to_embed = plan.total("to_embed")
    lines = [
        *_table(plan),
        f"Embedding model: {spec.model_id} ({spec.backend} backend, {spec.dim}-d).",
        f"Embedding time at {plan.rate_per_min:g} chunks/min: {minutes:,.0f} min ({minutes / 60:.1f} h) "
        f"for {to_embed:,} new embeddings (~{plan.tokens_per_minute():,.0f} input tokens/min).",
    ]
    if spec.backend == "gemini":
        return [*lines, *_gemini_lines(plan, spec)]
    if spec.backend == "local":
        lines.append(
            f"Local CPU inference: no API cost, no quota; ETA from the measured {LOCAL_CPU_CHUNKS_PER_S:g} "
            "chunks/s on the dev laptop (ADR 0003), --rate N chunks/min to override."
        )
    lines.append(
        "Every embedded batch is committed to the embedding cache: a stopped or killed build re-run with the "
        "same command resumes with zero repeat embeddings."
    )
    return lines


def build_command(plan: BuildPlan, corpus_version: str) -> str:
    sources = ",".join(s.source_id for s in plan.buildable())
    return f"python -m rag build --corpus-version {corpus_version} --sources {sources}"


async def cmd_plan(args: argparse.Namespace, settings: Settings) -> int:
    from rag.cli import EXIT_OK, out

    registry = load_registry()
    excluded = {s.strip() for s in (args.exclude or "").split(",") if s.strip()}
    wanted = tuple(s.strip() for s in args.sources.split(",") if s.strip()) if args.sources else None
    sources = tuple(s for s in (wanted or active_sources(registry)) if s not in excluded)
    paths = DataPaths.from_settings(settings)
    spec = embedding_spec(settings.embed_backend)
    daily_cap = args.daily_cap if args.daily_cap is not None else FREE_TIER_TEXTS_PER_DAY
    with EmbeddingCache(paths.embed_cache_db) as cache:
        plan = plan_build(
            paths,
            registry,
            sources,
            cache,
            model_id=embed_model_id(settings.embed_backend),
            limit=args.limit,
            include_unready=args.include_unready,
            rate_per_min=args.rate or default_rate_per_min(spec.backend),
            daily_cap=(daily_cap or None) if spec.backend == "gemini" else None,
        )
    for line in render_plan(plan, spec):
        out(line)
    if args.corpus_version and plan.buildable():
        out(f"Build command:\n  {build_command(plan, args.corpus_version)}")
    return EXIT_OK


def add_plan_parser(sub: Any) -> None:
    p = sub.add_parser(
        "plan", help="dry run: chunk counts and embedding time per source (no embedding calls)"
    )
    p.add_argument("--sources", default=None, help="comma-separated ids (default: every ACTIVE source)")
    p.add_argument("--exclude", default=None, help="comma-separated ids to leave out")
    p.add_argument("--limit", type=int, default=None, help="max documents per source")
    p.add_argument("--include-unready", action="store_true", help="also count sources without a ready marker")
    p.add_argument(
        "--rate",
        type=float,
        default=None,
        help="embeddings per minute (default: the backend's expected rate)",
    )
    p.add_argument(
        "--daily-cap",
        type=int,
        default=None,
        help=f"gemini backend: daily cap in texts (default {FREE_TIER_TEXTS_PER_DAY}; 0 = none)",
    )
    p.add_argument("--corpus-version", default=None, help="print the build command for this version")
