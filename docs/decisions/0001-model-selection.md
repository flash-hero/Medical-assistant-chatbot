# ADR 0001: Model selection (spike S1, 2026-11-15, free tier, synthetic prompts)

## Measurements

Same RAG-style prompt (system policy + 2 sources + question, ~160-195 input tokens), streamed, `google-genai==3.3.0`, `v1beta`.

| Model | thinking | TTFT | Total | Thought tokens | Result |
|---|---|---|---|---|---|
| gemini-3.5-flash-lite | default (none) | 872 ms | 1,076 ms | 0 | Correct, cited [1][2] |
| gemini-3.5-flash-lite | low | 932 ms | 1,124 ms | 0 | Identical; level has no effect |
| gemini-3.6-flash | low | 2,753 ms | 3,073 ms | 446 | Correct, cited |
| gemini-4-hydrogen | low | 16,815 ms | 17,213 ms | 815 | Correct, cited; too slow for chat |
| gemini-4-hydrogen | medium | 10,052 ms | 10,325 ms | 936 | Hit MAX_TOKENS at 1,024 |
| gemini-3.8-flash | low | n/a | > 120 s | n/a | ReadTimeout (and 504 at 58 s in S1) |
| gemini-4-argon / carbon | n/a | n/a | n/a | n/a | 429, free-tier limit 0 |

Decisions API (`gemini-decision-1`): 7 questions (3 noul, 1 choice, 3 score) over 621 input tokens in 1,116 ms, 0 output tokens.
Relevance scores separated a directly relevant passage (2.93/3), an irrelevant one (0.11) and a related one (1.41).

Embeddings (`gemini-embedding-2`): outputs at 768/1536/3072 are unit-norm (no manual normalisation).
Max 100 contents per request (`at most 100 requests can be in one batch`); 100 texts in 1.9 s.
A list of plain strings returns ONE aggregated vector: always wrap each text in its own `types.Content`.
Cross-lingual cosine to an English document: EN query 0.720, FR 0.707, AR 0.713 (768 dims). 1536 and 3072 gave no gain.

Thinking tokens count against `max_output_tokens`: budgets must include thinking headroom.

## Decision

| Role | Model | Notes |
|---|---|---|
| Answer (stream and verify-then-release) | `gemini-3.5-flash-lite` | Sub-second TTFT, faithful citations |
| Answer fallback | `gemini-3.6-flash`, thinking `low` | Used on upstream errors/timeouts |
| Guard + router | `gemini-decision-1` | Flash-lite JSON classifier as fallback |
| Query rewrite / entities | `gemini-3.5-flash-lite` | JSON schema output |
| Rerank | `gemini-decision-1` score questions | Kept only if +3 nDCG@8 over RRF-only (P3B) |
| Groundedness verify | `gemini-decision-1` noul per sentence | |
| Offline judge | `gemini-3.6-flash` now (provisional); `gemini-4-argon` once billed | Must differ from the generator |
| Embeddings | `gemini-embedding-2`, 768 dims | |

Re-run this bake-off when billing is enabled: hydrogen latency on a paid tier is unknown.
All IDs live in `core/models.py`; nothing else may hard-code a model ID.
