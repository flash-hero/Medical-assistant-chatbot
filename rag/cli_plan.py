"""`python -m rag plan`: dry-run chunk counts per source and the embedding time a build would need."""

from __future__ import annotations

import argparse
from typing import Any

from core.config import Settings
from core.models import ModelRole, model_for
from rag.embed_cache import EmbeddingCache
from rag.embedding import embed_model_id
from rag.paths import DataPaths
from rag.plan import FREE_TIER_TEXTS_PER_DAY, FREE_TIER_TEXTS_PER_MIN, BuildPlan, active_sources, plan_build


def render_plan(plan: BuildPlan) -> list[str]:
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
    to_embed = plan.total("to_embed")
    lines.append(
        f"  {'TOTAL (ready only)':<36}{plan.total('documents'):>7}{plan.total('chunks'):>8}"
        f"{plan.total('unique_chunks'):>8}{plan.total('cached'):>8}{to_embed:>9}"
        f"{plan.total('tokens_to_embed') / 1e6:>7.2f}"
    )
    minutes = plan.eta_minutes()
    price = model_for(ModelRole.EMBED).usd_per_m_input
    lines.append(
        f"Embedding time at {plan.rate_per_min:g} chunks/min: {minutes:,.0f} min ({minutes / 60:.1f} h) "
        f"for {to_embed:,} new embeddings (~{plan.tokens_per_minute():,.0f} input tokens/min)."
    )
    lines.append(
        f"Paid-tier cost estimate: ~${plan.cost_usd(price):,.2f} "
        f"({plan.total('tokens_to_embed') / 1e6:,.1f}M chunk tokens at ${price:g}/M, list price)."
    )
    days = plan.days_at_cap()
    if days is not None:
        lines.append(f"What-if daily cap of {plan.daily_cap:,} texts/day: about {days:g} day(s) of quota.")
    else:
        lines.append(
            "Free-tier daily embedding quota: unknown (no cap assumed; --daily-cap N for a what-if)."
        )
    lines.append(
        "On a day-scope 429 the build stops with exit 3 (progress is in the embedding cache); re-running the "
        "same command resumes with zero repeat embeddings."
    )
    return lines


def build_command(plan: BuildPlan, corpus_version: str) -> str:
    sources = ",".join(s.source_id for s in plan.buildable())
    return f"python -m rag build --corpus-version {corpus_version} --sources {sources}"


async def cmd_plan(args: argparse.Namespace, settings: Settings) -> int:
    from rag.cli import EXIT_OK, load_registry, out

    registry = load_registry()
    excluded = {s.strip() for s in (args.exclude or "").split(",") if s.strip()}
    wanted = tuple(s.strip() for s in args.sources.split(",") if s.strip()) if args.sources else None
    sources = tuple(s for s in (wanted or active_sources(registry)) if s not in excluded)
    paths = DataPaths.from_settings(settings)
    with EmbeddingCache(paths.embed_cache_db) as cache:
        plan = plan_build(
            paths,
            registry,
            sources,
            cache,
            model_id=embed_model_id(settings.llm_backend),
            limit=args.limit,
            include_unready=args.include_unready,
            rate_per_min=args.rate,
            daily_cap=args.daily_cap or None,
        )
    for line in render_plan(plan):
        out(line)
    if args.corpus_version and plan.buildable():
        out(f"Build command:\n  {build_command(plan, args.corpus_version)}")
    return EXIT_OK


def add_plan_parser(sub: Any) -> None:
    p = sub.add_parser("plan", help="dry run: chunk counts and embedding time per source (no API calls)")
    p.add_argument("--sources", default=None, help="comma-separated ids (default: every ACTIVE source)")
    p.add_argument("--exclude", default=None, help="comma-separated ids to leave out")
    p.add_argument("--limit", type=int, default=None, help="max documents per source")
    p.add_argument("--include-unready", action="store_true", help="also count sources without a ready marker")
    p.add_argument("--rate", type=float, default=FREE_TIER_TEXTS_PER_MIN, help="embeddings per minute")
    p.add_argument(
        "--daily-cap", type=int, default=FREE_TIER_TEXTS_PER_DAY, help="what-if daily cap (default: unknown)"
    )
    p.add_argument("--corpus-version", default=None, help="print the build command for this version")
