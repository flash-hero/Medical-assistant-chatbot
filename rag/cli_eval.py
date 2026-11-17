"""CLI handlers for status / gold / eval / promote / rollback (split from cli.py to keep files small)."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient

from core.config import Settings
from rag.embedding import embed_model_id
from rag.errors import EmbeddingQuotaExhausted, GateFailed, IndexMismatch
from rag.index import alias_target, count_points, list_collections, switch_alias
from rag.manifest import ActivePointer, read_active, read_build_state, read_manifest, write_active
from rag.paths import COLLECTION_PREFIX, GOLD_DIR, DataPaths, validate_collection
from rag.verify import verify_collection

Handler = Callable[[argparse.Namespace, Settings], Coroutine[Any, Any, int]]
MIN_OVERRIDE_REASON = 10


def _now() -> datetime:
    return datetime.now(UTC)


# ---- status ------------------------------------------------------------------------------------------
async def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    from rag.cli import EXIT_OK, out, qdrant_client
    from rag.embed_cache import EmbeddingCache

    paths = DataPaths.from_settings(settings)
    client = qdrant_client(settings, timeout=10)
    try:
        target = await alias_target(client, settings.qdrant_alias)
        out(f"alias {settings.qdrant_alias!r} -> {target or '(none)'}")
        active = read_active(paths)
        if active is not None:
            out(f"active pointer: {active.collection} (corpus {active.corpus_version}, {active.promoted_at})")
            if active.gate_override:
                out(f"  promoted WITHOUT passing gates: {active.gate_override}")
        for name in await list_collections(client):
            if name.startswith(COLLECTION_PREFIX):
                out(await _collection_line(client, paths, name))
    finally:
        await client.close()
    if paths.embed_cache_db.exists():
        with EmbeddingCache(paths.embed_cache_db) as cache:
            out(f"embedding cache: {cache.count()} vectors in {paths.embed_cache_db}")
    return EXIT_OK


async def _collection_line(client: AsyncQdrantClient, paths: DataPaths, name: str) -> str:
    state = read_build_state(paths, name)
    manifest = read_manifest(paths, name)
    line = f"  {name}: {await count_points(client, name)} points"
    if state is not None:
        line += f", build {state.status} {state.indexed_chunks}/{state.total_chunks}"
    if manifest is not None:
        line += f", manifest {manifest.chunks} chunks signed={bool(manifest.signature)}"
    return line


async def default_collection(client: AsyncQdrantClient, settings: Settings) -> str:
    target = await alias_target(client, settings.qdrant_alias)
    if target:
        return target
    names = [n for n in await list_collections(client) if n.startswith(COLLECTION_PREFIX)]
    if not names:
        raise IndexMismatch("no ausculta collection exists; run `python -m rag build` first")
    return names[-1]


# ---- gold --------------------------------------------------------------------------------------------
async def cmd_gold(args: argparse.Namespace, settings: Settings) -> int:
    from evals.retrieval.generate import GoldGenerator, generate_gold
    from evals.retrieval.gold import load_chunks, sample_passages, save_gold, with_rewrites
    from evals.retrieval.runner import indexed_chunk_ids
    from rag.cli import EXIT_ERROR, EXIT_OK, close_llm, llm_provider, out, qdrant_client

    paths = DataPaths.from_settings(settings)
    client = qdrant_client(settings)
    llm = llm_provider(settings)
    try:
        collection = validate_collection(args.collection or await default_collection(client, settings))
        version = _corpus_version(paths, collection)
        indexed = await indexed_chunk_ids(client, collection)
        chunks = load_chunks(sorted(paths.chunks_dir(version).glob("*.jsonl")))
        passages = sample_passages(
            chunks,
            args.passages,
            seed=args.seed,
            min_tokens=args.min_tokens,
            allowed=lambda c: c.chunk_id in indexed,
        )
        gen = GoldGenerator(llm, created_at=_now(), max_calls=args.max_calls, corpus=chunks)
        rows, rewrites, stopped = await generate_gold(
            gen, passages, batch_size=args.batch, ooc=args.ooc, rewrite=not args.no_rewrite
        )
    finally:
        await client.close()
        await close_llm(llm)
    rows = with_rewrites(rows, rewrites, "model")
    prefix = f"gen_{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    for lang in ("en", "fr", "ar"):
        written = save_gold(
            Path(args.out) / f"{prefix}_{lang}.jsonl", [r for r in rows if r.language == lang]
        )
        out(f"  {lang}: {written} gold queries")
    out(f"Generation calls used: {gen.calls}/{args.max_calls}; skipped items: {gen.skipped}")
    if stopped:
        out(f"Stopped early: {stopped}. Partial output was saved.")
        return EXIT_ERROR
    return EXIT_OK


def _corpus_version(paths: DataPaths, collection: str) -> str:
    manifest = read_manifest(paths, collection)
    if manifest is not None:
        return manifest.corpus_version
    state = read_build_state(paths, collection)
    if state is None:
        raise IndexMismatch(f"no manifest or build state for {collection}")
    return state.corpus_version


# ---- eval --------------------------------------------------------------------------------------------
async def cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    from evals.retrieval.runner import EvalContext, EvalOptions, run_eval
    from rag.cli import EXIT_GATE, EXIT_OK, close_llm, embedding_for, llm_provider, out, qdrant_client
    from rag.offline import CacheOnlyLLM
    from rag.sparse import SparseEncoder

    paths = DataPaths.from_settings(settings)
    client = qdrant_client(settings)
    llm = CacheOnlyLLM() if args.offline else llm_provider(settings)
    # queries are embedded with the deployment's backend (offline: never called, so no model is loaded)
    embedding = embedding_for(settings, llm=llm, cache_only=args.offline)
    try:
        live = await alias_target(client, settings.qdrant_alias)
        collection = validate_collection(args.collection or await default_collection(client, settings))
        opts = EvalOptions(
            collection=collection,
            gold_dir=Path(args.gold),
            offline=args.offline,
            rerank_sample=args.rerank_sample,
            rerank_pause_s=max(0.0, args.rerank_pause_s),
            embed_latency_sample=args.embed_latency_sample,
            write_config=not args.no_write_config,
            resume_check=not args.no_resume_check,
            free_tier=settings.is_free_tier,
        )
        ctx = EvalContext(client, llm, paths, SparseEncoder(paths.fastembed_dir), _now(), embedding)
        report = await run_eval(ctx, opts)
    except EmbeddingQuotaExhausted as exc:
        from rag.cli import EXIT_QUOTA

        out(f"Embedding quota exhausted ({exc.scope}) after {exc.embedded} new query embedding(s).")
        out(f"They are saved in {paths.query_cache_db}; re-run the same command later (no repeats).")
        return EXIT_QUOTA
    finally:
        await client.close()
        await close_llm(llm)
        if embedding.provider is not llm:
            await embedding.aclose()
    for line in save_eval_report(paths, report, ctx.when, live_collection=live):
        out(line)
    return EXIT_GATE if any(g["verdict"] == "FAIL" for g in report["gates"]) else EXIT_OK


def save_eval_report(
    paths: DataPaths, report: dict[str, Any], when: datetime, *, live_collection: str | None
) -> list[str]:
    """Write the run's report; publish its gate records as reports/rag.metrics.json only when it is an online
    evaluation of the collection the alias serves. Returns the lines to print."""
    from evals.retrieval.report import publish_metrics, write_report

    full, records = write_report(paths.reports_dir, report, when)
    lines = [*render_report(report), f"Report: {full}", f"Run gate records: {records}"]
    if report.get("mode") == "online" and report.get("collection") == live_collection:
        published = publish_metrics(paths.rag_metrics_file, report)
        lines.append(f"Published as the live rag gate metrics: {published}")
    else:
        lines.append(
            f"Not published to {paths.rag_metrics_file.name}: only an online eval of the live collection "
            f"({live_collection or 'no alias'}) is."
        )
    return lines


def render_report(report: dict[str, Any]) -> list[str]:
    lines = [f"{report['collection']} ({report['mode']}, {report['indexed_points']} points)"]
    head = f"  {'ablation':<16}{'lang':<5}{'n':>5}{'R@8':>7}{'R@20':>7}{'MRR':>7}{'nDCG8':>7}{'p95 b':>9}"
    lines.append(head)
    for abl in report["ablations"]:
        for lang, s in abl["by_language"].items():
            if not s.get("n_answerable") and abl["scored"]:
                continue
            lines.append(
                f"  {abl['ablation']:<16}{lang:<5}{int(s.get('n_answerable', s['latency']['n'])):>5}"
                f"{s.get('recall_at_8', float('nan')):>7.3f}{s.get('recall_at_20', float('nan')):>7.3f}"
                f"{s.get('mrr', float('nan')):>7.3f}{s.get('ndcg_at_8', float('nan')):>7.3f}"
                f"{s['latency'].get('retrieval_ms_p95', float('nan')):>9.1f}"
            )
    lines.extend(
        f"  {g['verdict']:<12}{g['gate']:<28}{g['measured']:<18}{g['detail']}" for g in report["gates"]
    )
    return lines


# ---- promote / rollback ------------------------------------------------------------------------------
async def _verified_version(
    client: AsyncQdrantClient, paths: DataPaths, settings: Settings, collection: str, secret: str
) -> str:
    """Signed-manifest check (rag/verify.py), incl. the deployment's embedding model; never overridable."""
    verified = await verify_collection(
        client, paths, collection, secret, embed_model=embed_model_id(settings.embed_backend)
    )
    return verified.corpus_version


async def _switch(
    client: AsyncQdrantClient,
    paths: DataPaths,
    settings: Settings,
    collection: str,
    version: str,
    *,
    override: str | None = None,
) -> str:
    from rag.cli import out

    previous = await switch_alias(client, settings.qdrant_alias, collection)
    write_active(
        paths,
        ActivePointer(
            alias=settings.qdrant_alias,
            collection=collection,
            corpus_version=version,
            promoted_at=_now(),
            previous_collection=previous if previous != collection else None,
            gate_override=override,
        ),
    )
    out(f"alias {settings.qdrant_alias!r}: {previous or '(none)'} -> {collection} (corpus {version})")
    if previous and previous != collection:
        out(f"previous collection kept for rollback: python -m rag rollback  (-> {previous})")
    out(sync_live_metrics(paths, collection))
    return previous or ""


def sync_live_metrics(paths: DataPaths, collection: str) -> str:
    """The alias now serves `collection`, so reports/rag.metrics.json must describe it: publish its newest
    online report, or remove the file when there is none (MISSING is truer than another collection's numbers).
    Returns the line to print."""
    from evals.retrieval.report import latest_report, publish_metrics

    latest = latest_report(paths.reports_dir, collection, mode="online")
    if latest is not None:
        published = publish_metrics(paths.rag_metrics_file, latest[1])
        return f"live rag gate metrics: {published} (from {latest[0].name})"
    paths.rag_metrics_file.unlink(missing_ok=True)
    return (
        f"no online report for {collection}: {paths.rag_metrics_file.name} removed "
        f"(rag gates show MISSING); measure it with: python -m rag eval"
    )


async def cmd_promote(args: argparse.Namespace, settings: Settings) -> int:
    from evals.retrieval.report import promotion_check
    from rag.cli import EXIT_ERROR, EXIT_OK, out, qdrant_client

    if settings.session_secret is None:
        out("AUSCULTA_SESSION_SECRET is not set: the manifest signature cannot be verified.")
        return EXIT_ERROR
    paths = DataPaths.from_settings(settings)
    collection = validate_collection(args.collection)
    override = " ".join((args.override_gates or "").split()) or None
    if override is not None and len(override) < MIN_OVERRIDE_REASON:
        out(f"--override-gates needs a reason of at least {MIN_OVERRIDE_REASON} characters.")
        return EXIT_ERROR
    check = promotion_check(paths.reports_dir, collection)
    for gate in check.gates:
        out(f"  {gate['verdict']:<12}{gate['gate']:<28}{gate['measured']}")
    if check.ok:
        override = None  # gates pass: a normal promotion, nothing to record
    elif override is None:
        raise GateFailed(f"{collection}: {check.reason}")
    else:
        out(f"WARNING: promoting despite '{check.reason}'. Override recorded in {paths.active_pointer}")
    client = qdrant_client(settings, timeout=30)
    try:  # the signed-manifest check is never overridable
        secret = settings.session_secret.get_secret_value()
        version = await _verified_version(client, paths, settings, collection, secret)
        await _switch(client, paths, settings, collection, version, override=override)
    finally:
        await client.close()
    return EXIT_OK


async def cmd_rollback(args: argparse.Namespace, settings: Settings) -> int:
    """Point the alias back at the previously promoted collection (signature re-verified, gates not rerun)."""
    from rag.cli import EXIT_ERROR, EXIT_OK, out, qdrant_client

    paths = DataPaths.from_settings(settings)
    active = read_active(paths)
    if active is None or not active.previous_collection or settings.session_secret is None:
        out("Nothing to roll back to (no previous collection recorded, or no session secret).")
        return EXIT_ERROR
    client = qdrant_client(settings, timeout=30)
    try:
        target = active.previous_collection
        secret = settings.session_secret.get_secret_value()
        version = await _verified_version(client, paths, settings, target, secret)
        await _switch(client, paths, settings, target, version)
    finally:
        await client.close()
    return EXIT_OK


# ---- parsers -----------------------------------------------------------------------------------------
def add_eval_parsers(sub: Any) -> None:
    sub.add_parser("status", help="alias target, collections, build progress, cache size")
    g = sub.add_parser("gold", help="generate gold queries with the REWRITE model (uses generation quota)")
    g.add_argument("--collection", default=None)
    g.add_argument("--passages", type=int, default=200)
    g.add_argument("--batch", type=int, default=10)
    g.add_argument("--ooc", type=int, default=30, help="out-of-corpus items (x3 languages)")
    g.add_argument("--no-rewrite", action="store_true", help="skip English rewrites of FR/AR questions")
    g.add_argument("--max-calls", type=int, default=120)
    g.add_argument("--min-tokens", type=int, default=120)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--out", default=str(GOLD_DIR))
    e = sub.add_parser("eval", help="evaluate a collection on the gold set; writes reports/retrieval/")
    e.add_argument("--collection", default=None, help="default: the alias target, else the newest collection")
    e.add_argument("--gold", default=str(GOLD_DIR))
    e.add_argument(
        "--offline", action="store_true", help="no Gemini calls: sparse quality + stand-in latency"
    )
    e.add_argument(
        "--rerank-sample", type=int, default=30, help="queries per language for the rerank ablation"
    )
    e.add_argument(
        "--rerank-pause-s", type=float, default=12.0, help="pause between rerank queries (free-tier TPM)"
    )
    e.add_argument("--embed-latency-sample", type=int, default=20)
    e.add_argument("--no-write-config", action="store_true")
    e.add_argument("--no-resume-check", action="store_true")
    p = sub.add_parser("promote", help="switch the alias to a collection whose rag gates pass")
    p.add_argument("collection")
    p.add_argument(
        "--override-gates",
        default=None,
        metavar="REASON",
        help="go live without a passing gate report (development seed only); the reason is recorded",
    )
    sub.add_parser("rollback", help="switch the alias back to the previously promoted collection")


EVAL_HANDLERS: dict[str, Handler] = {
    "status": cmd_status,
    "gold": cmd_gold,
    "eval": cmd_eval,
    "promote": cmd_promote,
    "rollback": cmd_rollback,
}
