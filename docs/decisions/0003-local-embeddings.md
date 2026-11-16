# ADR 0003: Local embeddings (EmbeddingGemma-300M) instead of the Gemini embedding API

Date: 2026-11-16. Status: accepted. Supersedes the embedding row of ADR 0001.

## Context

- The Gemini free tier allows **1,000 embedded texts per day** (`embed_content_free_tier_requests`, confirmed
  2026-11-16). The licence-checked corpus is 187,909 chunks: about 188 days on the free tier.
- The owner cannot enable billing, so the paid route (about $10 for the whole corpus) is unavailable.
- Query embeddings share the same daily budget, so live chat and indexing would starve each other.

## Measurements (spike S7, `spikes/s7_local_embeddings.py`)

Same 720 MedlinePlus seed chunks and the same LLM-generated, unreviewed gold set (96 answerable questions per
language) as the Gemini evaluation. Dense retrieval only, exact cosine, question text only (FR/AR are fully
cross-lingual against English documents).

| Model | recall@20 en / fr / ar | nDCG@8 all (en / fr / ar) | MRR all | Query latency | Cost / limits |
|---|---|---|---|---|---|
| gemini-embedding-2 (API) | 1.000 / 1.000 / 1.000 | 0.987 | n/a | 354 ms p50, 912 ms p95 | 1,000 texts/day free |
| **google/embeddinggemma-300m (local ONNX, CPU)** | **1.000 / 1.000 / 1.000** | **0.965** (0.983 / 0.976 / 0.936) | 0.954 | **28 ms** | none |

CPU indexing throughput on the dev laptop (i7-11800H, fastembed 0.9.1, batch 16, ~260-token chunks):
**2.7 chunks/s**, i.e. about 19 h for the full corpus. A GPU path (RTX 3050 Ti) can shorten this.

## Decision

Embed documents and queries locally with `google/embeddinggemma-300m` (768 dimensions, the same as before,
so the Qdrant schema does not change). `AUSCULTA_EMBED_BACKEND=local` is the default. `gemini` stays available
for a future paid deployment and `fake` for tests. Documents and queries must always use the same model; the
embedding cache is keyed by model id, so the two never mix.

Prompts are unchanged because EmbeddingGemma uses the same format the code already sends:
`task: search result | query: {q}` for queries and `title: {title} | text: {content}` for documents.

## Consequences

- No embedding quota, no API cost, and patient questions are never sent to a third party for embedding.
- The query embedding is about 30x faster, which removes the largest retrieval latency term.
- About 2.2 points lower nDCG@8 than Gemini on the seed gold set (largest gap in Arabic: 0.936). Re-measure on
  the full index; if Arabic ranking falls short, consider `Qwen/Qwen3-Embedding-0.6B` (Apache-2.0, 1024 dims,
  roughly 2x slower) in a follow-up spike.
- Each API process holds the model in memory (about 1.2 GB on disk, ONNX). Production runs one worker per
  container and scales with containers; the model files live on the `/data` volume or are baked into the image.
- Licence: Gemma Terms of Use. Commercial use is allowed, subject to the Gemma prohibited-use policy; record it
  in the third-party notices.
- Every existing collection was built with Gemini vectors and must be rebuilt (new corpus version). The
  confidence gate must be recalibrated, because similarity distributions differ between models.
