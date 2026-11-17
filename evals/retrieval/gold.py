"""Gold queries for retrieval evaluation: schema, JSONL I/O and passage sampling.

Answerable queries point at the chunk(s) that contain the answer. Out-of-corpus (OOC) queries have none and
measure abstention. Every generated item starts as status "llm_generated_unreviewed"; only a human review
may set "reviewed". FR/AR queries may carry English `search_queries`, as the engine's rewrite step sends:
`rewrite` records where they came from ("model" = a REWRITE-model translation that never saw the passage,
"parallel_en" = the parallel English question written with it, an optimistic stand-in).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.schemas.chat import Locale
from core.schemas.document import Chunk
from rag.fileio import atomic_write_jsonl, iter_jsonl

GoldStatus = Literal["llm_generated_unreviewed", "handwritten_unreviewed", "reviewed"]
GoldKind = Literal["passage", "ooc_fictional", "ooc_offdomain"]
Rewrite = Literal["none", "parallel_en", "model"]


class GoldQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    qid: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")
    language: Locale
    question: str = Field(min_length=3, max_length=600)
    search_queries: tuple[str, ...] = ()
    rewrite: Rewrite = "none"
    answerable: bool
    kind: GoldKind
    relevant_chunk_ids: tuple[str, ...] = ()
    relevant_doc_id: str | None = None
    source_id: str | None = None
    status: GoldStatus
    generator: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def _consistent(self) -> GoldQuery:
        if self.answerable != (self.kind == "passage"):
            raise ValueError("answerable queries are kind 'passage'; out-of-corpus kinds are not answerable")
        if self.answerable != bool(self.relevant_chunk_ids):
            raise ValueError("answerable queries need relevant_chunk_ids; out-of-corpus queries have none")
        if bool(self.search_queries) != (self.rewrite != "none"):
            raise ValueError("search_queries and rewrite must be set together")
        return self


class GoldError(ValueError):
    """A gold file is malformed (bad JSON, schema violation or duplicate qid)."""


def load_gold(directory: Path) -> tuple[GoldQuery, ...]:
    rows: list[GoldQuery] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.jsonl")):
        for lineno, raw in iter_jsonl(path):
            try:
                row = GoldQuery.model_validate_json(raw)
            except ValidationError as exc:
                raise GoldError(f"{path.name}:{lineno}: {exc.errors()[0].get('msg', 'invalid')}") from exc
            if row.qid in seen:
                raise GoldError(f"{path.name}:{lineno}: duplicate qid {row.qid!r}")
            seen.add(row.qid)
            rows.append(row)
    return tuple(rows)


def save_gold(path: Path, rows: Iterable[GoldQuery]) -> int:
    ordered: list[GoldQuery] = sorted(rows, key=lambda r: r.qid)
    return atomic_write_jsonl(path, ordered)


def with_rewrites(rows: Sequence[GoldQuery], rewrites: dict[str, str], how: Rewrite) -> list[GoldQuery]:
    """New rows whose FR/AR questions carry the given English rewrite (qid -> English query)."""
    out = []
    for row in rows:
        text = rewrites.get(row.qid, "").strip()
        if row.language != "en" and text:
            row = row.model_copy(update={"search_queries": (text,), "rewrite": how})
        out.append(row)
    return out


# ---- passages ------------------------------------------------------------------------------------
def load_chunks(files: Sequence[Path]) -> list[Chunk]:
    return [Chunk.model_validate_json(raw) for f in files for _, raw in iter_jsonl(f)]


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def answer_ids(chunk: Chunk, chunks: Sequence[Chunk]) -> tuple[str, ...]:
    """The gold chunk first, then every other chunk with exactly the same text (duplicated sections in
    other documents answer the question equally well)."""
    key = _norm(chunk.text)
    dupes = sorted(c.chunk_id for c in chunks if c.chunk_id != chunk.chunk_id and _norm(c.text) == key)
    return (chunk.chunk_id, *dupes)


def sample_passages(
    chunks: Sequence[Chunk],
    n: int,
    *,
    seed: int,
    min_tokens: int = 120,
    allowed: Callable[[Chunk], bool] | None = None,
) -> list[Chunk]:
    """Up to n chunks, at most one per document, round-robin across sources (seeded, deterministic)."""
    rng = random.Random(seed)
    by_source: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        if chunk.token_estimate >= min_tokens and (allowed is None or allowed(chunk)):
            by_source.setdefault(chunk.source_id, []).append(chunk)
    pools = []
    for source in sorted(by_source):
        pool = by_source[source][:]
        rng.shuffle(pool)
        pools.append(pool)
    picked: list[Chunk] = []
    docs: set[str] = set()
    while len(picked) < n and any(pools):
        for pool in pools:
            while pool and pool[-1].doc_id in docs:
                pool.pop()
            if pool and len(picked) < n:
                chunk = pool.pop()
                docs.add(chunk.doc_id)
                picked.append(chunk)
    return picked
