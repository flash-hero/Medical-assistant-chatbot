"""Index build: registry check -> normalized Documents -> chunks -> embeddings -> Qdrant -> signed manifest.

Resumable by construction: chunks are deterministic, every embedded batch is committed to the embedding
cache before it is upserted, and points have deterministic ids. Re-running the same command after a kill
or a daily-quota stop re-embeds nothing that was already embedded.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

import structlog
from pydantic import ValidationError
from qdrant_client import AsyncQdrantClient

from core.models import EMBED_DIM
from core.schemas.document import Chunk, Document
from rag.chunking import DEFAULT_CONFIG, ChunkerConfig, chunk_document, publisher_label
from rag.embedding import DocumentEmbedder, EmbedOutcome
from rag.errors import CorpusNotReady, EmbeddingQuotaExhausted, IndexMismatch
from rag.fileio import atomic_write_jsonl, iter_jsonl
from rag.index import alias_target, build_points, count_points, ensure_collection, point_id, prune_points
from rag.index import upsert_points as qdrant_upsert
from rag.manifest import BuildState, make_manifest, write_build_state, write_manifest
from rag.paths import DataPaths, collection_name, validate_corpus_version, validate_source_id
from rag.registry import Registry
from rag.sparse import SparseEncoder, SparseVec

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BuildRequest:
    corpus_version: str
    sources: tuple[str, ...]
    limit: int | None = None  # max documents per source (smoke builds)
    batch_size: int = 90  # chunks per embed+upsert step (= one free-tier throttle window)

    def __post_init__(self) -> None:
        validate_corpus_version(self.corpus_version)
        if not self.sources:
            raise ValueError("at least one source is required")
        for s in self.sources:
            validate_source_id(s)
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be >= 1")

    @property
    def collection(self) -> str:
        return collection_name(self.corpus_version)

    def resume_command(self) -> str:
        cmd = f"python -m rag build --corpus-version {self.corpus_version} --sources {','.join(self.sources)}"
        return cmd + (f" --limit {self.limit}" if self.limit else "")


@dataclass(frozen=True)
class SourceLoad:
    source_id: str
    documents: tuple[Document, ...]
    skipped: Mapping[str, int]


@dataclass(frozen=True)
class BuildReport:
    corpus_version: str
    collection: str
    status: str
    documents: int
    chunks: int
    per_source_chunks: Mapping[str, int]
    skipped: Mapping[str, Mapping[str, int]]
    cache_hits: int
    embedded: int
    api_calls: int
    elapsed_s: float
    manifest_path: str | None = None
    pruned: int = 0
    resume_command: str = ""


MAX_SPARSE_SYNONYMS = 12


def sparse_text(chunk: Chunk, synonyms: Sequence[str] = ()) -> str:
    """BM25 document text: header + text, plus the document's alternative names ("also called"), so a
    query using another name of the topic (vestibular schwannoma -> Acoustic Neuroma) still matches
    lexically. Lexical only: the embedding text and the chunk checksum are unchanged."""
    names = [s.strip() for s in synonyms if s.strip()][:MAX_SPARSE_SYNONYMS]
    base = chunk.lexical_text()
    return f"{base}\n{'; '.join(names)}" if names else base


def _parse_document(raw: str) -> Document | None:
    try:
        return Document.model_validate_json(raw)
    except ValidationError:
        return None


def load_documents(paths: DataPaths, registry: Registry, source_id: str, limit: int | None) -> SourceLoad:
    """Validated, policy-checked Documents of one source. Bad lines are counted and skipped."""
    if not paths.ready_marker(source_id).exists():
        raise CorpusNotReady(f"{source_id}: no ready marker at {paths.ready_marker(source_id)}")
    skipped: Counter[str] = Counter()
    docs: list[Document] = []
    seen: set[str] = set()
    for _lineno, raw in iter_jsonl(paths.normalized_file(source_id)):
        doc = _parse_document(raw)
        reason = "invalid_document" if doc is None else registry.refusal_reason(doc, source_id)
        if doc is not None and reason is None:
            if doc.checksum and doc.checksum != doc.with_checksum().checksum:
                reason = "checksum_mismatch"
            elif doc.doc_id in seen:
                reason = "duplicate_doc_id"
        if reason is not None or doc is None:
            skipped[reason or "invalid_document"] += 1
            continue
        seen.add(doc.doc_id)
        docs.append(doc)
        if limit is not None and len(docs) >= limit:
            break
    return SourceLoad(source_id, tuple(docs), MappingProxyType(dict(skipped)))


@dataclass
class _Progress:
    """Mutable accumulator private to one build run (kept so a quota stop can report partial progress)."""

    indexed: int = 0
    hits: int = 0
    embedded: int = 0
    api_calls: int = 0

    def add(self, batch: int, outcome: EmbedOutcome) -> None:
        self.indexed += batch
        self.hits += outcome.cache_hits
        self.embedded += outcome.embedded
        self.api_calls += outcome.api_calls


class IndexBuilder:
    def __init__(
        self,
        *,
        paths: DataPaths,
        registry: Registry,
        client: AsyncQdrantClient,
        embedder: DocumentEmbedder,
        sparse: SparseEncoder,
        secret: str,
        alias: str,
        chunker: ChunkerConfig = DEFAULT_CONFIG,
        dim: int = EMBED_DIM,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._paths, self._registry, self._client = paths, registry, client
        self._embedder, self._sparse, self._secret = embedder, sparse, secret
        self._alias, self._chunker, self._dim, self._clock = alias, chunker, dim, clock

    def _state(self, req: BuildRequest, status: str, docs: int, total: int, prog: _Progress, **kw: object):
        state = BuildState(
            corpus_version=req.corpus_version,
            collection=req.collection,
            sources=req.sources,
            status=status,  # type: ignore[arg-type]
            documents=docs,
            total_chunks=total,
            indexed_chunks=prog.indexed,
            embedded_this_run=prog.embedded,
            cache_hits_this_run=prog.hits,
            updated_at=self._clock(),
            resume_command=req.resume_command(),
            **kw,  # type: ignore[arg-type]
        )
        write_build_state(self._paths, state)
        return state

    def chunk_sources(self, req: BuildRequest) -> tuple[list[SourceLoad], list[Chunk]]:
        loads, chunks = [], []
        for source_id in req.sources:
            record = self._registry.require_indexable(source_id)
            load = load_documents(self._paths, self._registry, source_id, req.limit)
            per_source = [
                c
                for d in load.documents
                for c in chunk_document(
                    d, publisher=publisher_label(d.attribution, record.name), config=self._chunker
                )
            ]
            atomic_write_jsonl(self._paths.chunks_file(req.corpus_version, source_id), per_source)
            loads.append(load)
            chunks.extend(per_source)
            log.info(
                "source_chunked", source=source_id, documents=len(load.documents), chunks=len(per_source)
            )
        return loads, chunks

    def _sparse_for(
        self, chunks: Sequence[Chunk], synonyms: Mapping[str, tuple[str, ...]]
    ) -> dict[str, SparseVec]:
        out: dict[str, SparseVec] = {}
        for lang in sorted({str(c.language) for c in chunks}):
            group = [c for c in chunks if str(c.language) == lang]
            texts = [sparse_text(c, synonyms.get(c.doc_id, ())) for c in group]
            vecs = self._sparse.encode_documents(texts, lang)
            out.update({c.chunk_id: v for c, v in zip(group, vecs, strict=True)})
        return out

    async def _index_batches(
        self,
        req: BuildRequest,
        chunks: Sequence[Chunk],
        synonyms: Mapping[str, tuple[str, ...]],
        docs: int,
        prog: _Progress,
    ) -> None:
        for start in range(0, len(chunks), req.batch_size):
            batch = chunks[start : start + req.batch_size]
            outcome = await self._embedder.embed_chunks(batch)
            points = build_points(batch, outcome.vectors, self._sparse_for(batch, synonyms))
            await qdrant_upsert(self._client, req.collection, points)
            prog.add(len(batch), outcome)
            self._state(req, "indexing", docs, len(chunks), prog)
            log.info("build_progress", indexed=prog.indexed, total=len(chunks), embedded=prog.embedded)

    async def build(self, req: BuildRequest) -> BuildReport:
        t0 = time.perf_counter()
        loads, chunks = self.chunk_sources(req)
        n_docs = sum(len(load.documents) for load in loads)
        if await alias_target(self._client, self._alias) == req.collection:
            raise IndexMismatch(
                f"{req.collection} is live behind {self._alias!r}; build a new corpus version"
            )
        await ensure_collection(self._client, req.collection, dim=self._dim)
        self._state(req, "chunked", n_docs, len(chunks), _Progress())
        prog = _Progress()
        synonyms = {d.doc_id: d.synonyms for load in loads for d in load.documents if d.synonyms}
        try:
            await self._index_batches(req, chunks, synonyms, n_docs, prog)
        except EmbeddingQuotaExhausted as exc:
            prog.embedded += exc.embedded
            self._state(req, "quota_exhausted", n_docs, len(chunks), prog, error=str(exc))
            raise
        pruned = await prune_points(self._client, req.collection, (point_id(c.chunk_id) for c in chunks))
        indexed = await count_points(self._client, req.collection)
        if indexed != len(chunks):
            raise IndexMismatch(f"{req.collection} holds {indexed} points, expected {len(chunks)}")
        manifest = make_manifest(
            corpus_version=req.corpus_version,
            collection=req.collection,
            chunks=chunks,
            embed_model=self._embedder.model_id,
            embed_dim=self._dim,
            secret=self._secret,
            created_at=self._clock(),
        )
        manifest_path = write_manifest(self._paths, manifest)
        self._state(req, "indexed", n_docs, len(chunks), prog)
        return BuildReport(
            corpus_version=req.corpus_version,
            collection=req.collection,
            status="indexed",
            documents=n_docs,
            chunks=len(chunks),
            per_source_chunks=MappingProxyType(dict(manifest.sources)),
            skipped=MappingProxyType({ld.source_id: ld.skipped for ld in loads}),
            cache_hits=prog.hits,
            embedded=prog.embedded,
            api_calls=prog.api_calls,
            elapsed_s=time.perf_counter() - t0,
            manifest_path=manifest_path,
            pruned=pruned,
            resume_command=req.resume_command(),
        )
