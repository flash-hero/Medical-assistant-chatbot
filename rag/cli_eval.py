"""CLI handlers for status / gold / eval / promote / rollback (split from cli.py to keep files small)."""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient

from core.config import Settings
from rag.errors import GateFailed, IndexMismatch
from rag.index import alias_target, count_points, list_collections, switch_alias
from rag.manifest import (
    ActivePointer,
    read_active,
    read_build_state,
    read_manifest,
    verify_manifest,
    write_active,
)
from rag.paths import COLLECTION_PREFIX, GOLD_DIR, DataPaths, validate_collection

Handler = Callable[[argparse.Namespace, Settings], Awaitable[int]]


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
    from evals.retrieval.report import write_report
    from evals.retrieval.runner import EvalContext, EvalOptions, run_eval
    from rag.cli import EXIT_GATE, EXIT_OK, close_llm, llm_provider, out, qdrant_client
    from rag.offline import CacheOnlyLLM
    from rag.sparse import SparseEncoder

    paths = DataPaths.from_settings(settings)
    client = qdrant_client(settings)
    llm = CacheOnlyLLM() if args.offline else llm_provider(settings)
    try:
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
            backend=settings.llm_backend,
            free_tier=settings.is_free_tier,
        )
        ctx = EvalContext(client, llm, paths, SparseEncoder(paths.fastembed_dir), _now())
        report = await run_eval(ctx, opts)
    finally:
        await client.close()
        await close_llm(llm)
    full, metrics = write_report(paths.reports_dir, report, ctx.when)
    for line in render_report(report):
        out(line)
    out(f"Report: {full}\nGate records: {metrics}")
    return EXIT_GATE if any(g["verdict"] == "FAIL" for g in report["gates"]) else EXIT_OK


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
async def _payload_checksums(client: AsyncQdrantClient, collection: str) -> list[str]:
    sums: list[str] = []
    offset: Any = None
    while True:
        records, offset = await client.scroll(
            collection, limit=1024, offset=offset, with_payload=["checksum"]
        )
        sums.extend(str((r.payload or {}).get("checksum", "")) for r in records)
        if offset is None:
            return sums


async def verify_collection(client: AsyncQdrantClient, paths: DataPaths, collection: str, secret: str) -> str:
    """The collection must have a manifest whose HMAC matches the checksums actually stored in Qdrant."""
    if not await client.collection_exists(collection):
        raise IndexMismatch(f"collection {collection!r} does not exist")
    manifest = read_manifest(paths, collection)
    if manifest is None:
        raise IndexMismatch(f"{collection} has no manifest (incomplete build?)")
    sums = await _payload_checksums(client, collection)
    if len(sums) != manifest.chunks or not verify_manifest(manifest, sums, secret):
        raise IndexMismatch(f"{collection}: stored chunks do not match the signed manifest")
    return manifest.corpus_version


async def _switch(
    client: AsyncQdrantClient, paths: DataPaths, settings: Settings, collection: str, version: str
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
        ),
    )
    out(f"alias {settings.qdrant_alias!r}: {previous or '(none)'} -> {collection} (corpus {version})")
    if previous and previous != collection:
        out(f"previous collection kept for rollback: python -m rag rollback  (-> {previous})")
    return previous or ""


async def cmd_promote(args: argparse.Namespace, settings: Settings) -> int:
    from evals.retrieval.report import promotion_check
    from rag.cli import EXIT_ERROR, EXIT_OK, out, qdrant_client

    if settings.session_secret is None:
        out("AUSCULTA_SESSION_SECRET is not set: the manifest signature cannot be verified.")
        return EXIT_ERROR
    paths = DataPaths.from_settings(settings)
    collection = validate_collection(args.collection)
    check = promotion_check(paths.reports_dir, collection)
    for gate in check.gates:
        out(f"  {gate['verdict']:<12}{gate['gate']:<28}{gate['measured']}")
    if not check.ok:
        raise GateFailed(f"{collection}: {check.reason}")
    client = qdrant_client(settings, timeout=30)
    try:
        version = await verify_collection(
            client, paths, collection, settings.session_secret.get_secret_value()
        )
        await _switch(client, paths, settings, collection, version)
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
        version = await verify_collection(client, paths, target, settings.session_secret.get_secret_value())
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
    sub.add_parser("rollback", help="switch the alias back to the previously promoted collection")


EVAL_HANDLERS: dict[str, Handler] = {
    "status": cmd_status,
    "gold": cmd_gold,
    "eval": cmd_eval,
    "promote": cmd_promote,
    "rollback": cmd_rollback,
}
