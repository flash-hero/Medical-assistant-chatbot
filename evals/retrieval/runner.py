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

import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient

from core.models import EMBED_DIM
from core.ports import LLMProvider
from evals.retrieval.calibrate import Calibration, Sample, calibrate
from evals.retrieval.evaluate import AblationRun, latency, run_ablation, standard_ablations, summarize
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
from rag.embedding import DocumentEmbedder, QueryEmbedder, embed_model_id, prefixed_query, query_cache_key
from rag.index import DENSE_VECTOR, point_id
from rag.manifest import read_manifest
from rag.offline import StandInLLM
from rag.paths import DataPaths
from rag.rerank import DecisionReranker, NoopReranker, Reranker
from rag.retrieval import HybridRetriever
from rag.retrieval_config import RetrievalConfig, load_retrieval_config, save_retrieval_config
from rag.sparse import SparseEncoder

log = structlog.get_logger(__name__)
RERANK_MIN_GAIN = 0.03  # keep reranking only if nDCG@8 improves by >= 3 points
CALIBRATION_FEATURES = ("dense_top", "lexical_coverage", "sparse_agreement")


@dataclass(frozen=True)
class EvalOptions:
    collection: str
    gold_dir: Path
    offline: bool = False
    rerank_sample: int = 30
    rerank_pause_s: float = 12.0
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


async def embed_api_latency(llm: LLMProvider, texts: Sequence[str], n: int) -> dict[str, float]:
    """(a): wall time of single-query embedding calls on a small sample (costs n embedding texts)."""
    samples = []
    for text in list(texts)[:n]:
        t0 = time.perf_counter()
        await llm.embed([prefixed_query(text)], dim=EMBED_DIM)
        samples.append((time.perf_counter() - t0) * 1000)
    if not samples:
        return {"n": 0.0}
    return {
        "n": float(len(samples)),
        "p50": round(percentile(samples, 50), 2),
        "p95": round(percentile(samples, 95), 2),
    }


def _retriever(ctx: EvalContext, collection: str, qe: QueryEmbedder, reranker: Reranker) -> HybridRetriever:
    return HybridRetriever(
        client=ctx.client, collection=collection, query_embedder=qe, sparse=ctx.sparse, reranker=reranker
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
    decision: dict[str, Any] = {"measured": False, "keep_rerank": False, "min_gain": RERANK_MIN_GAIN}
    if "hybrid_rerank" in runs:
        cmp = paired(runs["hybrid"], runs["hybrid_rerank"])
        decision |= {"measured": cmp["n"] > 0, "keep_rerank": cmp.get("gain", 0.0) >= RERANK_MIN_GAIN, **cmp}
    out["rerank_decision"] = decision
    out["config"] = base.model_copy(
        update={
            "confidence": cal.model,
            "rerank": decision["keep_rerank"],
            "calibrated_on": f"reports/retrieval/{stamp(ctx.when)}.json",
        }
    )
    out["embed_api_latency"] = await embed_api_latency(
        ctx.llm, [r.question for r in rows], opts.embed_latency_sample
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
