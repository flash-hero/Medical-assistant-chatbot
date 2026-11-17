"""Dense-only seed check without Qdrant: embed seed chunks and gold questions with the deployment's embedding
backend, rank by exact cosine (numpy) and report vector sanity plus per-language top-1 / recall@k / MRR.

It answers "does this embedding backend produce sane vectors that put the right chunk first?" before an
index is rebuilt with it. Questions are the plain question text (FR/AR fully cross-lingual against English
chunks), as in spike S7. Used by a unit test (fake backend) and for a one-off real-model check:

  python -m evals.retrieval.dense_check --chunks <data root>/chunks/2026-11-16.seed1/medlineplus_topics.jsonl

AUSCULTA_EMBED_BACKEND (or --backend) selects the model; the local backend loads EmbeddingGemma once in this
process. Exit 0 when every vector is finite, of the expected dimension and unit-norm, and the relevant chunk
ranks first for most questions (> MIN_TOP1); exit 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from core.config import get_settings
from core.models import EMBED_DIM
from core.ports import EmbeddingProvider
from core.schemas.document import Chunk
from evals.retrieval.gold import GoldQuery, load_chunks, load_gold
from evals.retrieval.metrics import first_hit, mean
from rag.embedding import embedding_backend, prefixed_query
from rag.paths import GOLD_DIR

MIN_TOP1 = 0.5  # "most questions": strictly more than half rank their chunk first
NORM_TOLERANCE = 1e-3
LANGS = ("en", "fr", "ar")


@dataclass(frozen=True)
class DenseCheck:
    model_id: str
    chunks: int
    questions: int
    dims: frozenset[int]
    max_norm_error: float
    finite: bool
    embed_s: float
    ranks: tuple[tuple[str, str, int], ...]  # (qid, language, 1-based rank of the first relevant chunk)
    by_language: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def top1(self) -> float:
        return mean([float(rank == 1) for _, _, rank in self.ranks])

    def vectors_ok(self, dim: int = EMBED_DIM) -> bool:
        return self.finite and self.dims == frozenset({dim}) and self.max_norm_error <= NORM_TOLERANCE

    def passed(self, dim: int = EMBED_DIM) -> bool:
        return self.vectors_ok(dim) and self.top1 > MIN_TOP1


def select_seed(
    chunks: Sequence[Chunk], rows: Sequence[GoldQuery], *, questions: int, total_chunks: int, seed: int = 7
) -> tuple[list[Chunk], list[GoldQuery]]:
    """`questions` answerable rows (languages in turn, each with a distinct relevant chunk present in
    `chunks`), their relevant chunks, and seeded distractors up to `total_chunks` chunks."""
    by_id = {c.chunk_id: c for c in chunks}
    pools = {
        lang: sorted(
            (r for r in rows if r.answerable and r.language == lang and r.relevant_chunk_ids[0] in by_id),
            key=lambda r: r.qid,
        )
        for lang in LANGS
    }
    picked: list[GoldQuery] = []
    used: set[str] = set()
    while len(picked) < questions and any(pools.values()):
        for lang in LANGS:
            while pools[lang] and len(picked) < questions:
                row = pools[lang].pop(0)
                if row.relevant_chunk_ids[0] not in used:
                    used.add(row.relevant_chunk_ids[0])
                    picked.append(row)
                    break
    relevant = [by_id[r.relevant_chunk_ids[0]] for r in picked]
    others = [c for c in chunks if c.chunk_id not in used]
    distractors = random.Random(seed).sample(others, min(len(others), max(0, total_chunks - len(relevant))))
    return relevant + distractors, picked


async def dense_check(
    provider: EmbeddingProvider,
    chunks: Sequence[Chunk],
    rows: Sequence[GoldQuery],
    *,
    model_id: str,
    dim: int = EMBED_DIM,
    k: int = 20,
) -> DenseCheck:
    t0 = time.perf_counter()
    doc_vecs = await provider.embed([c.embedding_text() for c in chunks], dim=dim)
    q_vecs = await provider.embed([prefixed_query(r.question) for r in rows], dim=dim)
    embed_s = time.perf_counter() - t0
    every = [*doc_vecs, *q_vecs]
    matrix = np.asarray(every, dtype=np.float64) if every else np.zeros((0, dim))
    norms = np.linalg.norm(matrix, axis=1) if len(every) else np.zeros(0)
    sims = (
        np.asarray(q_vecs, dtype=np.float64) @ np.asarray(doc_vecs, dtype=np.float64).T
        if q_vecs and doc_vecs
        else np.zeros((len(rows), len(chunks)))
    )
    ids = [c.chunk_id for c in chunks]
    ranks: list[tuple[str, str, int]] = []
    for row, scores in zip(rows, sims, strict=True):
        ranked = [(ids[int(j)],) for j in np.argsort(-scores, kind="stable")]
        ranks.append((row.qid, row.language, first_hit(ranked, row.relevant_chunk_ids) or len(ids) + 1))
    return DenseCheck(
        model_id=model_id,
        chunks=len(chunks),
        questions=len(rows),
        dims=frozenset(len(v) for v in every),
        max_norm_error=float(np.max(np.abs(norms - 1.0))) if len(every) else 0.0,
        finite=bool(np.all(np.isfinite(matrix))),
        embed_s=round(embed_s, 3),
        ranks=tuple(ranks),
        by_language=_by_language(ranks, k),
    )


def _by_language(ranks: Sequence[tuple[str, str, int]], k: int) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for lang in (*LANGS, "all"):
        mine = [r for _, lg, r in ranks if lang in ("all", lg)]
        if mine:
            out[lang] = {
                "n": float(len(mine)),
                "top1": mean([float(r == 1) for r in mine]),
                f"recall_at_{k}": mean([float(r <= k) for r in mine]),
                "mrr": mean([1.0 / r for r in mine]),
            }
    return out


def render(check: DenseCheck, dim: int = EMBED_DIM) -> list[str]:
    lines = [
        f"model {check.model_id}: {check.chunks} chunks + {check.questions} questions embedded in "
        f"{check.embed_s:.1f} s",
        f"vectors: dims {sorted(check.dims)} (expected {dim}), finite {check.finite}, "
        f"max |norm - 1| {check.max_norm_error:.2e}",
    ]
    for lang, s in check.by_language.items():
        lines.append(
            f"  {lang:<4} n={int(s['n']):<3} top1 {s['top1']:.3f}  "
            + "  ".join(f"{name} {value:.3f}" for name, value in s.items() if name not in ("n", "top1"))
        )
    lines.extend(f"  {qid:<24} {lang}  rank {rank}" for qid, lang, rank in check.ranks)
    lines.append(f"{'PASS' if check.passed(dim) else 'FAIL'} (top-1 must exceed {MIN_TOP1:.0%})")
    return lines


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m evals.retrieval.dense_check", description=__doc__)
    p.add_argument("--chunks", required=True, type=Path, help="chunk JSONL file (e.g. the seed chunks)")
    p.add_argument("--gold", type=Path, default=GOLD_DIR)
    p.add_argument("--questions", type=int, default=10)
    p.add_argument("--total-chunks", type=int, default=20)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--backend", choices=("local", "gemini", "fake"), default=None)
    return p


async def run(args: argparse.Namespace) -> tuple[DenseCheck, int]:
    settings = get_settings()
    if args.backend:
        settings = settings.model_copy(update={"embed_backend": args.backend})
    chunks, rows = select_seed(
        load_chunks([args.chunks]),
        load_gold(args.gold),
        questions=args.questions,
        total_chunks=args.total_chunks,
        seed=args.seed,
    )
    backend = embedding_backend(settings)
    try:
        check = await dense_check(backend.provider, chunks, rows, model_id=backend.model_id, dim=backend.dim)
    finally:
        await backend.aclose()
    return check, backend.dim


def main(argv: Sequence[str] | None = None, *, write: Any = None) -> int:
    emit = write or (lambda line: sys.stdout.write(f"{line}\n"))
    check, dim = asyncio.run(run(_parser().parse_args(argv)))
    for line in render(check, dim):
        emit(line)
    return 0 if check.passed(dim) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
