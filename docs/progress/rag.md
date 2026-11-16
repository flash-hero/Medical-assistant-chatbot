# P3B RAG track: progress

Owner dirs: `rag/`, `tests/rag/`, `evals/retrieval/`, `docs/decisions/0002-retrieval.md`; data root `chunks/`,
`embed-cache/`, `manifests/`, `reports/retrieval/`, `reports/rag*`; Qdrant collections and the `ausculta_corpus` alias.

## Deliverables (continuation runs, 2026-11-16)

| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | `tests/rag` suite green, coverage >= 80% for `rag/` + `evals/retrieval/` | done (re-run at the end) | Re-verified 10:50 UTC: 126 passed, 0 failed; every `rag/` and `evals/retrieval/` module >= 87%. Root cause of the original 15 FAILED / 12 ERROR: `rag.cli.configure_logging()` bound structlog to pytest's captured `sys.stderr`, closed after the CLI test ("I/O operation on closed file"). Fixed + regression test. |
| 2 | Seed index live behind alias `ausculta_corpus` | done | `ausculta_corpus_2026_11_16_seed1` promoted 06:23 UTC with `--override-gates "<reason>"` (signed-manifest check still enforced; reason in `manifests/active.json`). Live check through `build_retriever(settings, llm)` passed (EN asthma -> MedlinePlus Asthma top 1). |
| 3 | Retrieval evaluation (gold EN/FR/AR + OOC, ablations, calibration, report, metrics, ADR 0002) | in progress | Gold: `gen_20261116T062632Z_{en,fr,ar}.jsonl` generated 06:25 UTC by gemini-3.5-flash-lite (60 passages x 3 langs + 30 OOC x 3, FR/AR English rewrites by the model without the passage; ~11 generation calls, estimated from the file contents since that run's stdout was lost) + `agent_seed1_*` (36 answerable + 24 OOC per lang). Total 450 rows, 599 distinct query texts. 10:50 UTC: per-run gate records renamed `<stamp>.gates.json` (evals.run reads every `*.metrics.json`, newest wins, so an offline or validation-collection eval would have replaced the live numbers); `reports/rag.metrics.json` is now written only by an ONLINE eval of the alias target. Online eval started 10:52 UTC (log `reports/retrieval/run-online-20261116.log`). |
| 4 | Full-build preparation (chunk counts per ACTIVE source, ETA at 90 chunks/min, `--limit 50` validation on 2 non-MedlinePlus sources, exact command for the lead) | in progress | `--limit 50` validation done (val50, 291 chunks). Plan run 11:52 UTC (`reports/rag-plan-20261116.txt`, 23 s, no API): 14 ready sources excl. openfda_labels, 22,844 docs, 111,373 chunks, 110,113 new embeddings (1,011 cached), 25.1M tokens, 1,223 min = 20.4 h at 90/min; wikipedia_medicine not ready (being fetched). Daily cap now treated as UNKNOWN in `rag plan` (no default cap). 11:57 UTC: deleted Qdrant collections `ausculta_corpus_2026_11_16_val50` and `ausculta_corpus_2026_11_15_1` (their vectors stay in the embedding cache; manifest/build-state files kept as history); only seed1 (alias target) remains. Left: record the command. |

## Run 3 (started 11:37 UTC)

- Diagnosis of the 10:52 online eval (exit=1): pre-embed completed (query cache holds all 599 query
  vectors, written 10:54-11:00), then the ablations ran until ~11:18. The only unguarded Gemini calls after
  that were the 20 raw single-text `llm.embed` calls of latency measurement (a); a per-minute 429 there (shared
  key; the `--limit 50` validation build was embedding at 90/min 11:10-11:16, with its own 429 at 11:14)
  raised `UpstreamRateLimited`, which `main()` turned into `Error [...]` on STDOUT and exit 1. The log
  captured stderr only, so the message was lost and every ablation result with it.
- Fixes (tests added): latency (a) now skips a failed sample after waiting out a per-minute 429, stops on a
  day-scope 429 or after 3 failures, and runs right after pre-embed (before the long ablations); the rerank
  ablation stops after 5 consecutive failed reranks (quota spent); the rerank decision pairs only queries the
  reranker actually scored and needs >= 10 of them; `main()` also logs `command_failed` to stderr.
- 11:43 UTC smoke online eval of the alias target (`--rerank-sample 2 --embed-latency-sample 3
  --no-write-config --no-resume-check`, log `reports/retrieval/run-smoke-20261116.log`): exit 0 in 110 s,
  0 new query embeddings (599 cache hits). Report `20261116T114328Z.json`. Full run started 11:45 UTC (log
  `reports/retrieval/run-online-20261116-r3.log`).
- Found while checking the smoke report (EN hybrid vs hybrid_native differed although EN rows carry no
  search queries): retrieval was NOT deterministic. Repeating each EN gold query on seed1 gave a different
  fused order for 143 of 150 (30 with a different set at the fused_limit cut); dense results were identical,
  so the cause is Qdrant's arbitrary RRF tie order. Fix in `rag/search.py`: fetch fused_limit + 16, then
  `order_fused()` sorts by (RRF rounded to 9 dp, best dense cosine, point id) and cuts. After: 0 of 150
  differ. The 11:45 full eval ran on the old code, so it is re-run on the fixed code.
- Second fidelity gap: the eval built its retriever WITHOUT the drug-synonym expansion that production
  (`build_retriever`) loads. Measured offline on cached vectors: rankings differ for 4 of 450 gold queries,
  confidence for 0. Fixed in `evals/retrieval/runner.py::_retriever`; the r4 run was stopped and the full
  eval restarted at ~12:00 UTC on the final code (log `reports/retrieval/run-online-20261116-r5.log`).
- `--limit 50` validation build (deliverable 4 item) was done by run 2 at 11:10-11:17 UTC: nichd 141 + nei 150
  = 291 chunks from 100 documents into `ausculta_corpus_2026_11_16_val50`, 8 API calls, 356 s, signed manifest.

## State found at start of run 2 (10:41 UTC)

- Collections: `ausculta_corpus_2026_11_15_1` (720 of 5,564 chunks, build stopped on daily quota, no manifest) and
  `ausculta_corpus_2026_11_16_seed1` (720 chunks, 327 MedlinePlus topic docs A..Electrical Injuries, signed manifest).
  Alias -> seed1 (override). Query-embedding cache empty.

## Next step

See the first row that is not `done`.
