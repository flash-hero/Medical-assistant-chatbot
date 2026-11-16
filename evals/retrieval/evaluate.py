"""Run the retriever over the gold set for each ablation and aggregate per-language metrics.

Ablations: dense only, sparse only, hybrid (production), hybrid without the English rewrite for FR/AR
("hybrid_native", pure cross-lingual), hybrid + rerank (on a per-language sample: one Decisions call per
query). Latency is split into (a) `embed_api_ms`, the query-embedding API call, and (b) `retrieval_ms`,
Qdrant search + fusion + expansion + local CPU work: gate rag.retrieval_p95_ms applies to (b).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from core.schemas.chat import RetrievalQuery
from evals.retrieval.gold import GoldQuery
from evals.retrieval.metrics import mean, ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from rag.confidence import DEGRADED_MIN_COVERAGE
from rag.retrieval import HybridRetriever, RetrievalTrace
from rag.retrieval_config import RetrievalConfig

Sleep = Callable[[float], Awaitable[None]]
TOP_K = 20
K_VALUES = (8, 20)
RERANK_STOP_STREAK = 5  # consecutive failed reranks (~1 min at the default pacing): quota spent or outage


@dataclass(frozen=True)
class Ablation:
    name: str
    config: RetrievalConfig
    use_search_queries: bool = True
    per_language_sample: int | None = None  # costly ablations (rerank) run on a sample
    pause_s: float = 0.0  # pacing between queries (free-tier Decisions TPM)
    scored: bool = True  # False: latency-only run (stand-in query vectors), rankings are meaningless
    max_unreranked_streak: int = 0  # rerank ablations: stop after this many consecutive unreranked queries


@dataclass(frozen=True)
class Outcome:
    qid: str
    language: str
    kind: str
    answerable: bool
    ablation: str
    gold: tuple[str, ...]
    covered: tuple[tuple[str, ...], ...]
    confident: bool
    confidence: float
    signals: Mapping[str, float | None]
    timings: Mapping[str, float]
    reranked: bool = False


@dataclass(frozen=True)
class AblationRun:
    ablation: Ablation
    outcomes: tuple[Outcome, ...]
    errors: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    stopped: str | None = None  # why the run ended before its last query (e.g. reranking unavailable)


def standard_ablations(
    base: RetrievalConfig, *, rerank_sample: int = 0, rerank_pause_s: float = 12.0
) -> list[Ablation]:
    plain = base.model_copy(update={"rerank": False})
    out = [
        Ablation("dense", plain.model_copy(update={"mode": "dense"})),
        Ablation("sparse", plain.model_copy(update={"mode": "sparse"})),
        Ablation("hybrid", plain),
        Ablation("hybrid_native", plain, use_search_queries=False),
    ]
    if rerank_sample > 0:
        rr = plain.model_copy(update={"rerank": True})
        out.append(
            Ablation(
                "hybrid_rerank",
                rr,
                per_language_sample=rerank_sample,
                pause_s=rerank_pause_s,
                max_unreranked_streak=RERANK_STOP_STREAK,
            )
        )
    return out


def sample_rows(rows: Sequence[GoldQuery], per_language: int | None) -> list[GoldQuery]:
    """Deterministic per-language sample (by a hash of the qid), answerable and out-of-corpus alike."""
    ordered = sorted(rows, key=lambda r: hashlib.sha256(r.qid.encode("utf-8")).hexdigest())
    if per_language is None:
        return sorted(rows, key=lambda r: r.qid)
    picked: list[GoldQuery] = []
    for lang in ("en", "fr", "ar"):
        picked.extend([r for r in ordered if r.language == lang][:per_language])
    return sorted(picked, key=lambda r: r.qid)


def to_query(row: GoldQuery, *, use_search_queries: bool, top_k: int = TOP_K) -> RetrievalQuery:
    sq = row.search_queries if use_search_queries else ()
    return RetrievalQuery(
        standalone_query=row.question, search_queries=sq, language=row.language, top_k=top_k
    )


def _outcome(row: GoldQuery, ablation: Ablation, tr: RetrievalTrace) -> Outcome:
    return Outcome(
        qid=row.qid,
        language=row.language,
        kind=row.kind,
        answerable=row.answerable,
        ablation=ablation.name,
        gold=row.relevant_chunk_ids,
        covered=tr.covered_chunk_ids,
        confident=tr.result.confident,
        confidence=tr.result.confidence,
        signals=MappingProxyType({**tr.signals.features(), "degraded": float(tr.signals.degraded)}),
        timings=MappingProxyType(dict(tr.result.timings_ms)),
        reranked=tr.result.reranked,
    )


async def run_ablation(
    retriever: HybridRetriever, rows: Sequence[GoldQuery], ablation: Ablation, *, sleep: Sleep = asyncio.sleep
) -> AblationRun:
    """Per-query failures are recorded and skipped. A rerank ablation whose reranker keeps failing (daily
    Decisions quota, outage) stops early instead of spending the rest of its paced sample on RRF-only runs."""
    outcomes: list[Outcome] = []
    errors: dict[str, str] = {}
    streak, stopped = 0, None
    for i, row in enumerate(sample_rows(rows, ablation.per_language_sample)):
        if i and ablation.pause_s:
            await sleep(ablation.pause_s)
        query = to_query(row, use_search_queries=ablation.use_search_queries)
        try:
            tr = await retriever.trace(query, ablation.config)
        except Exception as exc:
            errors[row.qid] = type(exc).__name__
            continue
        outcomes.append(_outcome(row, ablation, tr))
        streak = 0 if tr.result.reranked or not ablation.config.rerank else streak + 1
        if ablation.max_unreranked_streak and streak >= ablation.max_unreranked_streak:
            stopped = f"reranking failed on {streak} consecutive queries"
            break
    return AblationRun(ablation, tuple(outcomes), MappingProxyType(errors), stopped)


# ---- aggregation ---------------------------------------------------------------------------------
def _ranking(answerable: Sequence[Outcome]) -> dict[str, float]:
    out: dict[str, float] = {"n_answerable": float(len(answerable))}
    if not answerable:
        return out
    for k in K_VALUES:
        out[f"recall_at_{k}"] = mean([recall_at_k(o.covered, o.gold, k) for o in answerable])
    out["mrr"] = mean([reciprocal_rank(o.covered, o.gold, TOP_K) for o in answerable])
    out["ndcg_at_8"] = mean([ndcg_at_k(o.covered, o.gold, 8) for o in answerable])
    return out


MAX_LISTED_MISSES = 50


def missed(outcomes: Iterable[Outcome]) -> list[str]:
    """Answerable questions whose answer is not in the top 20 (for manual review of the gold set)."""
    return sorted(o.qid for o in outcomes if o.answerable and recall_at_k(o.covered, o.gold, TOP_K) == 0.0)[
        :MAX_LISTED_MISSES
    ]


def _abstention(answerable: Sequence[Outcome], ooc: Sequence[Outcome]) -> dict[str, float]:
    out: dict[str, float] = {"n_out_of_corpus": float(len(ooc))}
    if ooc:
        out["abstain_rate_out_of_corpus"] = mean([0.0 if o.confident else 1.0 for o in ooc])
        out["degraded_rule_abstain_ooc"] = mean([_lexical_abstain(o) for o in ooc])
    if answerable:
        out["abstain_rate_answerable"] = mean([0.0 if o.confident else 1.0 for o in answerable])
        out["degraded_rule_abstain_answerable"] = mean([_lexical_abstain(o) for o in answerable])
    return out


def _lexical_abstain(o: Outcome) -> float:
    """What the dense-unavailable fallback rule (lexical coverage) would decide for this query."""
    return 0.0 if (o.signals.get("lexical_coverage") or 0.0) >= DEGRADED_MIN_COVERAGE else 1.0


def latency(outcomes: Iterable[Outcome]) -> dict[str, float]:
    rows = list(outcomes)
    out: dict[str, float] = {"n": float(len(rows))}
    for key in ("retrieval_ms", "search_ms", "expand_ms", "embed_api_ms", "rerank_ms"):
        values = [
            o.timings[key] for o in rows if key in o.timings and (key == "retrieval_ms" or o.timings[key] > 0)
        ]
        if values:
            out[f"{key}_p50"] = round(percentile(values, 50), 2)
            out[f"{key}_p95"] = round(percentile(values, 95), 2)
    return out


def summarize(run: AblationRun) -> dict[str, Any]:
    by_lang: dict[str, Any] = {}
    langs = sorted({o.language for o in run.outcomes})
    for lang in [*langs, "all"]:
        group = [o for o in run.outcomes if lang in ("all", o.language)]
        answerable = [o for o in group if o.answerable]
        ooc = [o for o in group if not o.answerable]
        stats: dict[str, Any] = {"latency": latency(group)}
        if run.ablation.scored:
            stats |= _ranking(answerable) | _abstention(answerable, ooc)
        by_lang[lang] = stats
    return {
        "ablation": run.ablation.name,
        "mode": run.ablation.config.mode,
        "rerank": run.ablation.config.rerank,
        "use_search_queries": run.ablation.use_search_queries,
        "per_language_sample": run.ablation.per_language_sample,
        "scored": run.ablation.scored,
        "queries": len(run.outcomes),
        "errors": dict(run.errors),
        "stopped": run.stopped,
        "reranked_queries": sum(o.reranked for o in run.outcomes),
        "missed_at_20": missed(run.outcomes) if run.ablation.scored else [],
        "by_language": by_lang,
    }


def paired_ndcg(a: AblationRun, b: AblationRun) -> dict[str, float]:
    """nDCG@8 of two ablations on the queries both scored (answerable only), e.g. rerank vs RRF-only."""
    left = {o.qid: o for o in a.outcomes if o.answerable}
    right = {o.qid: o for o in b.outcomes if o.answerable}
    common = sorted(set(left) & set(right))
    if not common:
        return {"n": 0.0}
    na = mean([ndcg_at_k(left[q].covered, left[q].gold, 8) for q in common])
    nb = mean([ndcg_at_k(right[q].covered, right[q].gold, 8) for q in common])
    return {
        "n": float(len(common)),
        f"{a.ablation.name}_ndcg_at_8": na,
        f"{b.ablation.name}_ndcg_at_8": nb,
        "gain": nb - na,
    }
