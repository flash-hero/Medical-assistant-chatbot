"""`python -m rag eval`: evaluate one collection against the gold set and write the report.

Online (default): pre-embeds every query text once into the persistent query cache (resumable, quota-aware),
runs all ablations, fits the confidence gate, decides on reranking, measures (a) query-embedding API latency
on a small sample and (b) the Qdrant stage on every query, and saves the tuned retrieval config next to the
collection's manifest.
Offline (`--offline`, no Gemini call at all): sparse-only quality numbers plus (b) latency measured through
the full hybrid path with stand-in query vectors (real cached document vectors). Offline reports carry no
recall/abstention gate records, so they can never promote a collection.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient

from core.errors import UpstreamError, UpstreamRateLimited
from core.models import EMBED_DIM
from core.ports import LLMProvider
from evals.retrieval.calibrate import Calibration, Sample, calibrate
from evals.retrieval.evaluate import (
    AblationRun,
    Sleep,
    latency,
    run_ablation,
    standard_ablations,
    summarize,
)
from evals.retrieval.evaluate import paired_ndcg as paired
from evals.retrieval.gold import GoldQuery, load_gold
from evals.retrieval.metrics import percentile
from evals.retrieval.report import (
    REPORT_SCHEMA,
    evaluate_gates,
    gate_records,
    gate_rows,
    load_rag_gates,
    stamp,
)
from evals.retrieval.resume_check import measure_resume
from rag.embed_cache import EmbeddingCache
from rag.embedding import (
    DEFAULT_RATE_LIMIT_WAIT_S,
    DocumentEmbedder,
    QueryEmbedder,
    embed_model_id,
    prefixed_query,
    query_cache_key,
)
from rag.index import DENSE_VECTOR, point_id
from rag.manifest import read_manifest
from rag.offline import StandInLLM
from rag.paths import DRUG_SYNONYMS_PATH, DataPaths
from rag.rerank import DecisionReranker, NoopReranker, Reranker
from rag.retrieval import HybridRetriever
from rag.retrieval_config import RetrievalConfig, load_retrieval_config, save_retrieval_config
from rag.sparse import SparseEncoder
from rag.synonyms import load_synonyms

log = structlog.get_logger(__name__)
RERANK_MIN_GAIN = 0.03  # keep reranking only if nDCG@8 improves by >= 3 points
RERANK_MIN_PAIRED = 10  # answerable queries actually reranked before the rerank decision counts as measured
LATENCY_MAX_FAILURES = 3  # failed latency samples before measurement (a) gives up
CALIBRATION_FEATURES = ("dense_top", "lexical_coverage", "sparse_agreement")


@dataclass(frozen=True)
class EvalOptions:
    collection: str
    gold_dir: Path
    offline: bool = False
    rerank_sample: int = 30
    rerank_pause_s: float = 12.0
    rerank_min_paired: int = RERANK_MIN_PAIRED
    embed_latency_sample: int = 20
    write_config: bool = True
    resume_check: bool = True
    backend: str = "gemini"
    free_tier: bool = True


@dataclass(frozen=True)
class EvalContext:
    client: AsyncQdrantClient
    llm: LLMProvider
    paths: DataPaths
    sparse: SparseEncoder
    when: datetime


async def indexed_chunk_ids(client: AsyncQdrantClient, collection: str) -> set[str]:
    ids: set[str] = set()
    offset: Any = None
    while True:
        records, offset = await client.scroll(
            collection, limit=1024, offset=offset, with_payload=["chunk_id"]
        )
        ids.update(str((r.payload or {}).get("chunk_id", "")) for r in records)
        if offset is None:
            return ids


def evaluable(rows: Sequence[GoldQuery], indexed: set[str]) -> tuple[list[GoldQuery], int]:
    keep = [r for r in rows if not r.answerable or any(c in indexed for c in r.relevant_chunk_ids)]
    return keep, len(rows) - len(keep)


def query_strings(rows: Sequence[GoldQuery]) -> list[str]:
    return list(dict.fromkeys(t for r in rows for t in (r.question, *r.search_queries)))


PRE_EMBED_BATCH = 30  # small batches: on the free tier a batch larger than the day's remaining quota is
# rejected whole, so smaller batches still save progress late in the quota day


async def pre_embed(
    llm: LLMProvider, cache: EmbeddingCache, model: str, texts: Sequence[str]
) -> dict[str, int]:
    """Embed every query once into the persistent query cache (resumable; waits out per-minute 429s)."""
    outcome = await DocumentEmbedder(llm, cache, model_id=model, batch_size=PRE_EMBED_BATCH).embed_texts(
        [(query_cache_key(t), prefixed_query(t)) for t in texts]
    )
    return {"texts": len(texts), "cache_hits": outcome.cache_hits, "embedded": outcome.embedded}


def _failure_wait(exc: UpstreamError, default_s: float) -> float | None:
    """Seconds to wait before the next latency sample, or None to stop sampling (daily quota)."""
    if isinstance(exc, UpstreamRateLimited):
        return None if exc.scope == "day" else (exc.retry_after_s or default_s)
    return default_s


async def embed_api_latency(
    llm: LLMProvider,
    texts: Sequence[str],
    n: int,
    *,
    sleep: Sleep = asyncio.sleep,
    wait_s: float = DEFAULT_RATE_LIMIT_WAIT_S,
) -> dict[str, Any]:
    """(a): wall time of single-query embedding calls on a small sample (costs up to n embedding texts).

    Informational only (no gate). It must never fail the evaluation: the 2026-11-16 10:52 run lost every
    ablation when one of these raw calls hit a per-minute 429 on the shared key. A failed sample is skipped
    (after waiting out a per-minute 429); a daily 429 or LATENCY_MAX_FAILURES failures end the sample."""
    samples: list[float] = []
    failed, stopped = 0, None
    for text in list(texts)[:n]:
        t0 = time.perf_counter()
        try:
            await llm.embed([prefixed_query(text)], dim=EMBED_DIM)
        except UpstreamError as exc:
            failed += 1
            delay = _failure_wait(exc, wait_s)
            log.warning("embed_latency_sample_failed", error=exc.code, failed=failed)
            if delay is None or failed >= LATENCY_MAX_FAILURES:
                stopped = "daily quota" if delay is None else f"{failed} failed calls"
                break
            await sleep(delay)
            continue
        samples.append((time.perf_counter() - t0) * 1000)
    out: dict[str, Any] = {"n": float(len(samples)), "requested": n, "failed": failed, "stopped": stopped}
    if samples:
        out |= {"p50": round(percentile(samples, 50), 2), "p95": round(percentile(samples, 95), 2)}
    return out


def rerank_decision(base: AblationRun, rerank: AblationRun | None, min_paired: int) -> dict[str, Any]:
    """Keep reranking only on a measured gain of >= RERANK_MIN_GAIN nDCG@8, paired on the answerable queries
    the reranker actually scored (a query whose rerank call failed is RRF-only and would dilute the gain)."""
    decision: dict[str, Any] = {
        "measured": False,
        "keep_rerank": False,
        "min_gain": RERANK_MIN_GAIN,
        "min_paired": min_paired,
    }
    if rerank is None:
        return decision
    applied = replace(rerank, outcomes=tuple(o for o in rerank.outcomes if o.reranked))
    cmp = paired(base, applied)
    measured = cmp["n"] >= max(1, min_paired)
    return decision | {
        **cmp,
        "reranked_queries": len(applied.outcomes),
        "sampled_queries": len(rerank.outcomes),
        "stopped": rerank.stopped,
        "measured": measured,
        "keep_rerank": measured and cmp.get("gain", 0.0) >= RERANK_MIN_GAIN,
    }


def _retriever(ctx: EvalContext, collection: str, qe: QueryEmbedder, reranker: Reranker) -> HybridRetriever:
    """Same composition as rag.retrieval.build_retriever (incl. drug-synonym expansion), minus the alias."""
    return HybridRetriever(
        client=ctx.client,
        collection=collection,
        query_embedder=qe,
        sparse=ctx.sparse,
        reranker=reranker,
        synonyms=load_synonyms(DRUG_SYNONYMS_PATH),
    )


def _calibrate(run: AblationRun) -> Calibration:
    samples = [Sample(dict(o.signals), o.language, int(o.answerable)) for o in run.outcomes]
    return calibrate(samples, CALIBRATION_FEATURES)


def _calibration_dict(cal: Calibration) -> dict[str, Any]:
    return {
        "model": cal.model.model_dump(),
        "held_out": asdict(cal.held_out),
        "held_out_by_lang": {k: asdict(v) for k, v in cal.held_out_by_lang.items()},
        "folds": cal.folds,
        "features": list(cal.features),
    }


async def _online(
    ctx: EvalContext, opts: EvalOptions, rows: list[GoldQuery], base: RetrievalConfig
) -> dict[str, Any]:
    model = embed_model_id(opts.backend)
    out: dict[str, Any] = {}
    with EmbeddingCache(ctx.paths.query_cache_db) as qcache:
        out["pre_embed"] = await pre_embed(ctx.llm, qcache, model, query_strings(rows))
        out["embed_api_latency"] = await embed_api_latency(  # before the long ablations: cheap to redo
            ctx.llm, [r.question for r in rows], opts.embed_latency_sample
        )
        qe = QueryEmbedder(ctx.llm, model_id=model, persistent=qcache)
        retriever = _retriever(ctx, opts.collection, qe, DecisionReranker(ctx.llm))
        await retriever.warmup()
        runs = {
            a.name: await run_ablation(retriever, rows, a)
            for a in standard_ablations(
                base, rerank_sample=opts.rerank_sample, rerank_pause_s=opts.rerank_pause_s
            )
        }
    out["runs"] = runs
    cal = _calibrate(runs["hybrid"])
    out["calibration"] = _calibration_dict(cal)
    decision = rerank_decision(runs["hybrid"], runs.get("hybrid_rerank"), opts.rerank_min_paired)
    out["rerank_decision"] = decision
    out["config"] = base.model_copy(
        update={
            "confidence": cal.model,
            "rerank": decision["keep_rerank"],
            "calibrated_on": f"reports/retrieval/{stamp(ctx.when)}.json",
        }
    )
    return out


async def _offline(
    ctx: EvalContext, opts: EvalOptions, rows: list[GoldQuery], base: RetrievalConfig
) -> dict[str, Any]:
    keys = [r.relevant_chunk_ids[0] for r in rows if r.answerable][:200]
    standin = await _standin_llm(ctx, opts.collection, keys)
    retriever = _retriever(ctx, opts.collection, QueryEmbedder(standin, model_id="standin"), NoopReranker())
    await retriever.warmup()
    ablations = {a.name: a for a in standard_ablations(base)}
    timing_only = replace(ablations["hybrid"], name="hybrid_standin", scored=False)
    runs = {
        "sparse": await run_ablation(retriever, rows, ablations["sparse"]),
        "hybrid_standin": await run_ablation(retriever, rows, timing_only),
    }
    return {"runs": runs, "standin_vectors": standin.embedded_texts}


async def _standin_llm(ctx: EvalContext, collection: str, chunk_ids: Sequence[str]) -> StandInLLM:
    """Real gemini-embedding-2 document vectors (from Qdrant) used as query vectors for timing only."""
    records = await ctx.client.retrieve(
        collection, [point_id(c) for c in chunk_ids], with_vectors=[DENSE_VECTOR]
    )
    vectors = [
        r.vector[DENSE_VECTOR] for r in records if isinstance(r.vector, dict) and DENSE_VECTOR in r.vector
    ]
    return StandInLLM(vectors)  # type: ignore[arg-type]


def _latency_gate(runs: dict[str, AblationRun], offline: bool) -> tuple[float, int] | None:
    run = runs.get("hybrid_standin" if offline else "hybrid")
    if run is None or not run.outcomes:
        return None
    stats = latency(run.outcomes)
    return stats["retrieval_ms_p95"], int(stats["n"])


async def run_eval(ctx: EvalContext, opts: EvalOptions) -> dict[str, Any]:
    gold = load_gold(opts.gold_dir)
    indexed = await indexed_chunk_ids(ctx.client, opts.collection)
    rows, skipped = evaluable(gold, indexed)
    base = load_retrieval_config(ctx.paths, opts.collection)
    body = await (_offline if opts.offline else _online)(ctx, opts, rows, base)
    runs: dict[str, AblationRun] = body.pop("runs")
    resume = await measure_resume(ctx.paths.fastembed_dir) if opts.resume_check else None
    if not opts.offline and opts.write_config:
        body["config_path"] = save_retrieval_config(ctx.paths, opts.collection, body["config"])
    config = body.pop("config", None)
    latency_b = _latency_gate(runs, opts.offline)
    records = gate_records(
        None if opts.offline else summarize(runs["hybrid"]),
        body.get("calibration"),
        latency_b,
        resume.repeat_calls if resume else None,
        ctx.when,
        free_tier=opts.free_tier,
        collection=opts.collection,
    )
    manifest = read_manifest(ctx.paths, opts.collection)
    return {
        "schema": REPORT_SCHEMA,
        "measured_at": ctx.when.isoformat(),
        "collection": opts.collection,
        "corpus_version": manifest.corpus_version if manifest else None,
        "manifest_signed": bool(manifest and manifest.signature),
        "indexed_points": len(indexed),
        "mode": "offline" if opts.offline else "online",
        "free_tier": opts.free_tier,
        "gold": _gold_stats(gold, rows, skipped, opts.gold_dir),
        "ablations": [summarize(r) for r in runs.values()],
        "latency_gate_b": {"p95_ms": latency_b[0], "n": latency_b[1]} if latency_b else None,
        "resume_check": asdict(resume) if resume else None,
        "retrieval_config": config.model_dump() if config else None,
        **body,
        "gate_records": records,
        "gates": gate_rows(evaluate_gates(records, load_rag_gates())),
    }


def _gold_stats(
    gold: Sequence[GoldQuery], rows: Sequence[GoldQuery], skipped: int, gold_dir: Path
) -> dict[str, Any]:
    def count(items: Sequence[GoldQuery], **match: Any) -> int:
        return sum(all(getattr(r, k) == v for k, v in match.items()) for r in items)

    return {
        "dir": str(gold_dir),
        "rows": len(gold),
        "evaluated": len(rows),
        "skipped_not_indexed": skipped,
        "answerable": {lang: count(rows, language=lang, answerable=True) for lang in ("en", "fr", "ar")},
        "out_of_corpus": {lang: count(rows, language=lang, answerable=False) for lang in ("en", "fr", "ar")},
        "statuses": sorted({r.status for r in gold}),
        "rewrites": sorted({r.rewrite for r in rows}),
    }
