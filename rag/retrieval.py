"""HybridRetriever (core.ports.Retriever) and its composition root build_retriever(settings, llm).

Flow per query: embed standalone_query + search_queries (LRU+TTL cache) -> one Qdrant batch: dense and
BM25 prefetches fused with RRF(k=60) + per-stage score lookups -> drop link_only, <= 2 chunks per document,
one per parent section -> optional rerank (top 30) -> small-to-big expansion within a token budget ->
calibrated confidence gate. Per-stage timings are reported in RetrievalResult.timings_ms; `retrieval_ms`
(everything except the query-embedding call and the optional rerank call) is the rag.retrieval_p95_ms gate.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import httpx
import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from core.config import Settings
from core.errors import DependencyUnavailable, InvalidInput, UpstreamError
from core.ports import LLMProvider, Retriever
from core.schemas.chat import RetrievalQuery, RetrievalResult, RetrievedPassage
from core.text import guess_language
from rag.active import ActiveState
from rag.confidence import Signals, decide, lexical_coverage, sparse_agreement
from rag.embedding import QueryEmbedder, QueryVectors, embed_model_id, normalize_query
from rag.expansion import Sibling, expand_window, fetch_siblings
from rag.paths import DRUG_SYNONYMS_PATH, DataPaths
from rag.rerank import DecisionReranker, Reranker, RerankItem
from rag.retrieval_config import RetrievalConfig
from rag.search import Candidate, QueryPlan, SearchHits, build_filter, diversify, run_search
from rag.sparse import SparseEncoder, SparseVec
from rag.synonyms import SynonymIndex, load_synonyms

log = structlog.get_logger(__name__)

MAX_QUERY_CHARS = 1000
DEFAULT_CONFIG = RetrievalConfig()
_QDRANT_ERRORS = (UnexpectedResponse, ResponseHandlingException, httpx.HTTPError, OSError, ValueError)


@dataclass(frozen=True)
class RetrievalTrace:
    """RetrievalResult plus the internals evaluations need (signals for calibration, ranked ids)."""

    result: RetrievalResult
    signals: Signals
    ranked_chunk_ids: tuple[str, ...] = ()
    covered_chunk_ids: tuple[tuple[str, ...], ...] = ()  # per passage: chunks whose text it contains
    rerank_scores: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Expanded:
    text: str
    ordinals: tuple[int, ...]  # chunk ordinals of the parent section included in `text`


def query_texts(query: RetrievalQuery, cfg: RetrievalConfig) -> tuple[str, ...]:
    """Standalone query first, then distinct search queries (sanitised, capped)."""
    standalone = normalize_query(query.standalone_query)[:MAX_QUERY_CHARS]
    if not standalone:
        raise InvalidInput("standalone_query is empty")
    texts = [standalone]
    seen = {standalone.casefold()}
    for raw in query.search_queries:
        text = normalize_query(raw)[:MAX_QUERY_CHARS]
        if text and text.casefold() not in seen and len(texts) <= cfg.max_search_queries:
            seen.add(text.casefold())
            texts.append(text)
    return tuple(texts)


def _text_language(text: str, index: int, query_language: str) -> str:
    return query_language if index == 0 else guess_language(text)


def _covered(c: Candidate, exp: Expanded) -> tuple[str, ...]:
    parent = str(c.payload.get("parent_id", ""))
    return tuple(f"{parent}#{o}" for o in exp.ordinals) if parent else (str(c.payload.get("chunk_id", "")),)


class _Clock:
    """Stage timer. `retrieval_ms` = everything except the query-embedding stage and the rerank call: the
    part the rag.retrieval_p95_ms gate measures (Qdrant search + fusion + expansion + local CPU work)."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self._marks: dict[str, float] = {}
        self._last = self._t0

    def mark(self, stage: str) -> None:
        now = time.perf_counter()
        self._marks[stage] = (now - self._last) * 1000
        self._last = now

    def timings(self, embed_api_ms: float, rerank_ms: float, *, degraded: bool) -> dict[str, float]:
        total = (time.perf_counter() - self._t0) * 1000
        embed_ms = self._marks.get("embed", 0.0)
        out = {
            "embed_api_ms": round(embed_api_ms, 2),
            "embed_ms": round(embed_ms, 2),
            "search_ms": round(self._marks.get("search", 0.0), 2),
            "rerank_ms": round(rerank_ms, 2),
            "expand_ms": round(self._marks.get("expand", 0.0), 2),
            "retrieval_ms": round(max(0.0, total - embed_ms - rerank_ms), 2),
            "total_ms": round(total, 2),
        }
        if degraded:
            out["dense_degraded"] = 1.0
        return out


class HybridRetriever:
    def __init__(
        self,
        *,
        client: AsyncQdrantClient,
        collection: str,
        query_embedder: QueryEmbedder,
        sparse: SparseEncoder,
        reranker: Reranker,
        config: RetrievalConfig | Callable[[], RetrievalConfig] = DEFAULT_CONFIG,
        synonyms: SynonymIndex | None = None,
        version: str | Callable[[], str] = "",
    ) -> None:
        self._client, self._collection = client, collection
        self._qe, self._sparse, self._reranker = query_embedder, sparse, reranker
        self._config = config if callable(config) else (lambda: config)
        self._synonyms = synonyms or SynonymIndex()
        self._version = version if callable(version) else (lambda: version)

    @property
    def corpus_version(self) -> str:
        return self._version()

    async def health(self) -> bool:
        try:
            await self._client.get_collection(self._collection)
        except Exception:
            return False
        return True

    async def warmup(self) -> None:
        """Load the BM25 analysers off the event loop (first load scans the Unicode tables)."""
        await asyncio.to_thread(self._sparse.warmup)

    async def aclose(self) -> None:
        await self._client.close()

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        return (await self.trace(query)).result

    # ---- stages ----------------------------------------------------------------------------------
    async def _dense(self, texts: Sequence[str], cfg: RetrievalConfig) -> tuple[QueryVectors | None, bool]:
        if cfg.mode == "sparse":
            return None, False
        try:
            return await self._qe.embed(texts), False
        except UpstreamError as exc:
            if cfg.mode == "dense":
                raise
            log.warning("query_embedding_failed_sparse_only", error=exc.code)
            return None, True

    def _sparse_plan(self, texts: Sequence[str], language: str, cfg: RetrievalConfig) -> tuple[Any, ...]:
        if cfg.mode == "dense":
            return ()
        items = [(_text_language(t, i, language), t) for i, t in enumerate(texts)]
        if cfg.synonyms:
            items += [("en", exp) for exp in self._synonyms.expansions(texts)]
        plan: list[tuple[str, SparseVec]] = []
        seen: set[tuple[str, tuple[int, ...]]] = set()
        for lang, text in items:
            if not self._sparse.supports(lang):
                continue
            vec = self._sparse.encode_query(text, lang)
            key = (self._sparse.vector_name(lang), vec.indices)
            if not vec.empty and key not in seen:
                seen.add(key)
                plan.append((key[0], vec))
        return tuple(plan)

    async def _search(self, plan: QueryPlan, cfg: RetrievalConfig) -> SearchHits:
        try:
            return await run_search(self._client, self._collection, plan, cfg)
        except _QDRANT_ERRORS as exc:
            log.error("qdrant_search_failed", error=type(exc).__name__)
            raise DependencyUnavailable("vector store unavailable") from exc

    async def _rerank(
        self, query: RetrievalQuery, cands: list[Candidate], cfg: RetrievalConfig
    ) -> tuple[list[Candidate], dict[str, float], float]:
        if not (cfg.rerank and self._reranker.enabled) or not cands:
            return cands, {}, 0.0
        head = cands[: cfg.rerank_candidates]
        items = [
            RerankItem(
                title=str(c.payload.get("title", "")),
                heading=" > ".join(c.payload.get("heading_path") or [])[-200:],
                text=str(c.payload.get("text", "")),
                language=str(c.payload.get("language", "en")),
            )
            for c in head
        ]
        res = await self._reranker.rerank(query.standalone_query, items)
        if not res.applied:
            return cands, {}, res.latency_ms
        order = sorted(range(len(head)), key=lambda i: (-res.scores[i], i))
        scores = {head[i].point_id: res.scores[i] for i in range(len(head))}
        return [head[i] for i in order] + cands[len(head) :], scores, res.latency_ms

    async def _expand(self, top: Sequence[Candidate], cfg: RetrievalConfig) -> dict[str, Expanded]:
        """Small-to-big: replace each hit by a window of its parent section, within the token budgets."""
        out = {
            c.point_id: Expanded(str(c.payload.get("text", "")), (int(c.payload.get("ordinal", 0)),))
            for c in top
        }
        if not cfg.expand or not top:
            return out
        try:
            siblings = await fetch_siblings(
                self._client, self._collection, [str(c.payload.get("parent_id", "")) for c in top]
            )
        except _QDRANT_ERRORS as exc:
            log.warning("expansion_failed", error=type(exc).__name__)
            return out
        remaining = cfg.expand_total_tokens
        for c in top:
            own = int(c.payload.get("token_estimate", 1))
            budget = min(cfg.expand_passage_tokens, remaining)
            sibs: list[Sibling] = siblings.get(str(c.payload.get("parent_id", "")), [])
            ordinal = int(c.payload.get("ordinal", 0))
            if budget >= own and any(s.ordinal == ordinal for s in sibs):
                window = expand_window(sibs, ordinal, budget)
                out[c.point_id] = Expanded(window.text, window.ordinals)
                remaining -= window.tokens
            else:
                remaining -= own
        return out

    def _signals(
        self,
        texts: Sequence[str],
        language: str,
        top: Sequence[Candidate],
        hits: SearchHits,
        extra: dict[str, Any],
    ) -> Signals:
        dense = [hits.dense_scores[c.point_id] for c in top if c.point_id in hits.dense_scores]
        q_terms = [
            self._sparse.terms(t, lang)
            for i, t in enumerate(texts)
            if self._sparse.supports(lang := _text_language(t, i, language))
        ]
        p_terms = [
            self._sparse.terms(f"{c.payload.get('context_header', '')}\n{c.payload.get('text', '')}", lang)
            for c in top[:3]
            if self._sparse.supports(lang := str(c.payload.get("language", "en")))
        ]
        rerank = [extra["rerank"][c.point_id] for c in top if c.point_id in extra["rerank"]]
        return Signals(
            dense_top=max(dense) if dense else 0.0,
            lexical_coverage=round(lexical_coverage(q_terms, p_terms), 4),
            sparse_agreement=sparse_agreement([c.point_id for c in top], hits.sparse_ids),
            rerank_top=max(rerank) if rerank else None,
            degraded=extra["degraded"],
        )

    # ---- orchestration ---------------------------------------------------------------------------
    async def trace(self, query: RetrievalQuery, config: RetrievalConfig | None = None) -> RetrievalTrace:
        cfg = config or self._config()
        clock = _Clock()
        texts = query_texts(query, cfg)
        flt = build_filter(query.filters)
        qv, degraded = await self._dense(texts, cfg)
        clock.mark("embed")
        plan = QueryPlan(qv.vectors if qv else (), self._sparse_plan(texts, query.language, cfg), flt)
        hits = await self._search(plan, cfg)
        clock.mark("search")
        pool = max(query.top_k, cfg.rerank_candidates if cfg.rerank else 0)
        cands = diversify(
            hits.fused,
            max_per_doc=cfg.max_per_doc,
            one_per_parent=cfg.expand and cfg.one_per_parent,
            limit=pool,
        )
        cands, rerank_scores, rerank_ms = await self._rerank(query, cands, cfg)
        top = cands[: query.top_k]
        clock.mark("rerank")
        expanded = await self._expand(top, cfg)
        clock.mark("expand")
        no_dense = degraded or qv is None  # failed embedding, or a sparse-only ablation: lexical rule decides
        signals = self._signals(
            texts, query.language, top, hits, {"rerank": rerank_scores, "degraded": no_dense}
        )
        verdict = decide(cfg.confidence, signals, query.language, has_passages=bool(top))
        passages = tuple(self._passage(c, expanded[c.point_id].text, hits, rerank_scores) for c in top)
        result = RetrievalResult(
            passages=passages,
            confident=verdict.confident,
            confidence=verdict.confidence,
            reranked=bool(rerank_scores),
            timings_ms=clock.timings(qv.api_ms if qv else 0.0, rerank_ms, degraded=degraded),
            corpus_version=self.corpus_version,
        )
        return RetrievalTrace(
            result=result,
            signals=signals,
            ranked_chunk_ids=tuple(str(c.payload.get("chunk_id", "")) for c in top),
            covered_chunk_ids=tuple(_covered(c, expanded[c.point_id]) for c in top),
            rerank_scores=MappingProxyType(rerank_scores),
        )

    @staticmethod
    def _passage(c: Candidate, text: str, hits: SearchHits, rerank: Mapping[str, float]) -> RetrievedPassage:
        pl = c.payload
        scores = {"rrf": round(c.rrf, 6), "dense": round(hits.dense_scores.get(c.point_id, 0.0), 6)}
        scores["sparse_hit"] = 1.0 if c.point_id in hits.sparse_ids else 0.0
        if c.point_id in rerank:
            scores["rerank"] = round(rerank[c.point_id], 6)
        return RetrievedPassage(
            chunk_id=pl["chunk_id"],
            doc_id=pl["doc_id"],
            source_id=pl["source_id"],
            title=pl["title"],
            url=pl["url"],
            heading_path=tuple(pl.get("heading_path") or ()),
            text=text,
            language=pl["language"],
            content_type=pl["content_type"],
            trust_tier=int(pl["trust_tier"]),
            reuse_mode=pl["reuse_mode"],
            attribution=pl["attribution"],
            reviewed_on=pl.get("reviewed_on"),
            score=scores.get("rerank", scores["rrf"]),
            scores=scores,
        )


def build_retriever(settings: Settings, llm: LLMProvider) -> Retriever:
    """Composition root for the engine: queries the alias, follows promotions via manifests/active.json."""
    paths = DataPaths.from_settings(settings)
    key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    state = ActiveState(paths)
    return HybridRetriever(
        client=AsyncQdrantClient(url=settings.qdrant_url, api_key=key, timeout=5),
        collection=settings.qdrant_alias,
        query_embedder=QueryEmbedder(llm, model_id=embed_model_id(settings.llm_backend)),
        sparse=SparseEncoder(paths.fastembed_dir),
        reranker=DecisionReranker(llm),
        config=state.config,
        synonyms=load_synonyms(DRUG_SYNONYMS_PATH),
        version=state.corpus_version,
    )
