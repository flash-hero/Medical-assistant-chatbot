"""Spike S7: local EmbeddingGemma-300M (ONNX, CPU) vs the Gemini embedding baseline.

Same 720 seed chunks and the same gold set (EN/FR/AR) the RAG eval used for gemini-embedding-2.
Dense-only, exact cosine in numpy (no Qdrant), question text only (pure cross-lingual for FR/AR).
Run: .venv/Scripts/python.exe -m spikes.s7_local_embeddings [model_name]
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from qdrant_client import QdrantClient

from core.models import EMBED_QUERY_PREFIX
from core.schemas.document import Chunk

DATA = Path("C:/dev/ausculta-data")
REPO = Path(__file__).resolve().parents[1]
SEED = "ausculta_corpus_2026_11_16_seed1"


def seed_chunks() -> list[Chunk]:
    client = QdrantClient(url="http://127.0.0.1:6333", timeout=60)
    ids: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(SEED, limit=256, offset=offset, with_payload=["chunk_id"])
        ids.update(p.payload["chunk_id"] for p in points)
        if offset is None:
            break
    chunks = []
    for line in (DATA / "chunks/2026-11-16.1/medlineplus_topics.jsonl").read_text(encoding="utf-8").splitlines():
        c = Chunk.model_validate_json(line)
        if c.chunk_id in ids:
            chunks.append(c)
    print(f"seed ids {len(ids)}, matched chunks {len(chunks)}")
    return chunks


def gold_rows() -> list[dict]:
    rows = []
    for path in sorted((REPO / "evals/retrieval/gold").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("answerable") and row.get("relevant_chunk_ids"):
                rows.append(row)
    return rows


def metrics(ranked: list[str], relevant: set[str]) -> tuple[float, float, float]:
    hit20 = float(any(c in relevant for c in ranked[:20]))
    dcg = sum(1 / math.log2(i + 2) for i, c in enumerate(ranked[:8]) if c in relevant)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), 8)))
    rr = next((1 / (i + 1) for i, c in enumerate(ranked) if c in relevant), 0.0)
    return hit20, dcg / idcg if idcg else 0.0, rr


def main() -> None:
    model_name = sys.argv[1] if len(sys.argv) > 1 else "google/embeddinggemma-300m"
    model = TextEmbedding(model_name, cache_dir=str(DATA / "models"))
    chunks = seed_chunks()
    docs = [c.embedding_text() for c in chunks]
    tok_est = sum(len(d) for d in docs) / len(docs) / 4
    t0 = time.perf_counter()
    doc_vecs = np.array(list(model.embed(docs, batch_size=16)))
    dt = time.perf_counter() - t0
    print(f"docs: {len(docs)} in {dt:.1f}s -> {len(docs) / dt:.1f} chunks/s (avg ~{tok_est:.0f} tokens/chunk)")
    print(f"full corpus 187,909 chunks at this rate: {187909 / (len(docs) / dt) / 3600:.1f} h")

    rows = gold_rows()
    queries = [EMBED_QUERY_PREFIX + r["question"] for r in rows]
    t0 = time.perf_counter()
    q_vecs = np.array(list(model.embed(queries, batch_size=32)))
    qdt = time.perf_counter() - t0
    one = time.perf_counter()
    list(model.embed([queries[0]]))
    single_ms = (time.perf_counter() - one) * 1000
    print(f"queries: {len(queries)} in {qdt:.1f}s; single query latency {single_ms:.0f} ms")

    ids = [c.chunk_id for c in chunks]
    sims = q_vecs @ doc_vecs.T
    by_lang: dict[str, list[tuple[float, float, float]]] = {}
    for row, s in zip(rows, sims, strict=True):
        ranked = [ids[i] for i in np.argsort(-s)[:50]]
        by_lang.setdefault(row["language"], []).append(metrics(ranked, set(row["relevant_chunk_ids"])))
    print(f"\nmodel {model_name} (dense only, question text only)")
    print("lang  n    recall@20  nDCG@8  MRR")
    for lang, vals in sorted(by_lang.items()):
        arr = np.array(vals)
        print(f"{lang:4s} {len(vals):4d}  {arr[:, 0].mean():.3f}      {arr[:, 1].mean():.3f}   {arr[:, 2].mean():.3f}")
    allv = np.array([v for vals in by_lang.values() for v in vals])
    print(f"all  {len(allv):4d}  {allv[:, 0].mean():.3f}      {allv[:, 1].mean():.3f}   {allv[:, 2].mean():.3f}")
    print("gemini-embedding-2 baseline (RAG eval, dense only, all langs): recall@20 1.000, nDCG@8 0.987")


if __name__ == "__main__":
    main()
