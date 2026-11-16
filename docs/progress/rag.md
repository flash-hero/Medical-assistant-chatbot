# P3B RAG track: progress

Owner dirs: `rag/`, `tests/rag/`, `evals/retrieval/`, `docs/decisions/0002-retrieval.md`; data root `chunks/`,
`embed-cache/`, `manifests/`, `reports/retrieval/`, `reports/rag*`; Qdrant collections and the `ausculta_corpus` alias.

## Deliverables (continuation runs, 2026-11-16)

| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | `tests/rag` suite green, coverage >= 80% for `rag/` + `evals/retrieval/` | done | Run 4 final, 16:57 UTC: 134 passed, 0 failed (120 s); coverage 97% total for `rag/` + `evals/retrieval/`, lowest module `rag/fileio.py` 87%; ruff check + format clean (57 files). Log `C:\dev\ausculta-data\logs\rag-pytest-20261116T1655.log`. Re-verified 10:50 UTC: 126 passed, 0 failed; every `rag/` and `evals/retrieval/` module >= 87%. Root cause of the original 15 FAILED / 12 ERROR: `rag.cli.configure_logging()` bound structlog to pytest's captured `sys.stderr`, closed after the CLI test ("I/O operation on closed file"). Fixed + regression test. |
| 2 | Seed index live behind alias `ausculta_corpus` | done | `ausculta_corpus_2026_11_16_seed1` promoted 06:23 UTC with `--override-gates "<reason>"` (signed-manifest check still enforced; reason in `manifests/active.json`). Live check through `build_retriever(settings, llm)` passed (EN asthma -> MedlinePlus Asthma top 1). |
| 3 | Retrieval evaluation (gold EN/FR/AR + OOC, ablations, calibration, report, metrics, ADR 0002) | done | Run 4 (16:40 UTC) found the r5 full online eval had COMPLETED before the restart: exit 0 at 12:19 UTC after 20 min (log `reports/retrieval/run-online-20261116-r5.log`), report `20261116T115912Z.json`, calibrated config `manifests/ausculta_corpus_2026_11_16_seed1.retrieval.json`, `reports/rag.metrics.json` (7 records, free_tier). `evals.run --only rag.`: PASS 4, PROVISIONAL 3 (recall@20 0.990 EN/FR/AR), FAIL 0. Rerank OFF (-0.39 nDCG@8 points on 61 paired queries). `docs/decisions/0002-retrieval.md` written with all numbers. Earlier history: Gold: `gen_20261116T062632Z_{en,fr,ar}.jsonl` generated 06:25 UTC by gemini-3.5-flash-lite (60 passages x 3 langs + 30 OOC x 3, FR/AR English rewrites by the model without the passage; ~11 generation calls, estimated from the file contents since that run's stdout was lost) + `agent_seed1_*` (36 answerable + 24 OOC per lang). Total 450 rows, 599 distinct query texts. 10:50 UTC: per-run gate records renamed `<stamp>.gates.json` (evals.run reads every `*.metrics.json`, newest wins, so an offline or validation-collection eval would have replaced the live numbers); `reports/rag.metrics.json` is now written only by an ONLINE eval of the alias target. Online eval started 10:52 UTC (log `reports/retrieval/run-online-20261116.log`). |
| 4 | Full-build preparation (chunk counts per ACTIVE source, ETA at 90 chunks/min, `--limit 50` validation on 2 non-MedlinePlus sources, exact command for the lead) | done | Run 4: plan re-run 16:45 UTC right after `wikipedia_medicine` got its ready marker (16:45:00): `reports/rag-plan-20261116T1650.txt` (no API calls). 15 ready sources excl. openfda_labels, 26,766 docs, 189,169 chunks, 187,909 new embeddings (1,011 cached), 50.5M tokens, 2,088 min = 34.8 h at 90/min; ~$10.10 at paid list price. Per-source table, daily-quota caveat and the exact command: section "Full build (for the lead)" below. Collections: only `ausculta_corpus_2026_11_16_seed1` (alias target) remains; nothing else to delete. Earlier history: `--limit 50` validation done (val50, 291 chunks). Plan run 11:52 UTC (`reports/rag-plan-20261116.txt`, 23 s, no API): 14 ready sources excl. openfda_labels, 22,844 docs, 111,373 chunks, 110,113 new embeddings (1,011 cached), 25.1M tokens, 1,223 min = 20.4 h at 90/min; wikipedia_medicine not ready (being fetched). Daily cap now treated as UNKNOWN in `rag plan` (no default cap). 11:57 UTC: deleted Qdrant collections `ausculta_corpus_2026_11_16_val50` and `ausculta_corpus_2026_11_15_1` (their vectors stay in the embedding cache; manifest/build-state files kept as history); only seed1 (alias target) remains. Left: record the command. |

## Run 4 (started 16:39 UTC, after the PC restart)

- Qdrant up; only `ausculta_corpus_2026_11_16_seed1` exists, alias -> seed1. The r5 full eval had finished
  before the restart (exit 0, 12:19 UTC); nothing re-run. `evals.run --only rag.`: PASS 4, PROVISIONAL 3, FAIL 0.
- Wrote `docs/decisions/0002-retrieval.md` (numbers, rerank OFF, open points).
- Plan re-run with wikipedia_medicine ready (16:45 UTC). One synthetic single-text embedding probe at 16:48 UTC
  to check for an exhausted daily quota: it succeeded.
- Code: promote/rollback re-sync `reports/rag.metrics.json` (`rag/cli_eval.py::sync_live_metrics`,
  `evals/retrieval/report.py::latest_report(mode=)`), 2 tests. No other code change.

## Full build (for the lead) — prepared 2026-11-16 16:50 UTC, NOT started

Plan `reports/rag-plan-20261116T1650.txt` (`python -m rag plan --exclude openfda_labels --corpus-version
2026-11-16.1 --daily-cap 1000`). ETA = new embeddings / 90 per minute (the provider's free-tier throttle).

| Source | Lang | Docs | Chunks | New embeddings | Mtok | ETA at 90/min |
|---|---|---|---|---|---|---|
| bdpm | fr | 12,643 | 46,706 | 46,473 | 3.37 | 516 min (8.6 h) |
| cdc | en | 1,618 | 7,622 | 7,606 | 2.29 | 85 min |
| cdc_vis | en | 34 | 180 | 180 | 0.05 | 2 min |
| has_publications | fr | 2,593 | 60,403 | 60,403 | 22.57 | 671 min (11.2 h) |
| medlineplus_genetics | en | 2,795 | 3,405 | 3,405 | 1.04 | 38 min |
| medlineplus_topics | en | 1,014 | 2,159 | 1,439 (720 cached) | 0.35 | 16 min |
| nccih | en | 176 | 1,711 | 1,711 | 0.50 | 19 min |
| nci_pdq | en | 88 | 1,961 | 1,961 | 0.51 | 22 min |
| nei | en | 213 | 470 | 320 (150 cached) | 0.07 | 4 min |
| nhlbi | en | 455 | 1,645 | 1,645 | 0.46 | 18 min |
| niams | en | 136 | 577 | 577 | 0.16 | 6 min |
| nichd | en | 881 | 2,575 | 2,434 (141 cached) | 0.75 | 27 min |
| niddk | en | 799 | 3,390 | 3,390 | 1.00 | 38 min |
| nimh | en | 85 | 435 | 435 | 0.12 | 5 min |
| wikipedia_medicine | ar / fr / en | 1,100 / 955 / 1,181 | 13,747 / 15,867 / 26,316 (55,930) | 55,930 | 17.28 | 621 min (10.4 h) |
| **total (15 sources)** | | **26,766** | **189,169** | **187,909** | **50.51** | **2,088 min (34.8 h)** |

Excluded: openfda_labels (lead's instruction). bdpm has 233 duplicate chunk texts (46,706 chunks, 46,473 unique).

Daily quota caveat (UNKNOWN cap): the 2026-11-15.1 build hit a day-scope 429 at 00:47 UTC on 2026-11-16 after
720 of our chunk embeddings that Pacific day (plus spike/other-agent usage that was not logged). On the
current Pacific day this track has made ~914 embedding calls (599 query texts, 291 val50 chunks, 23
latency samples, 1 quota probe at 16:48 UTC that succeeded) without a day-scope 429. If the cap is near
1,000 texts/day, the build needs ~188 days of free-tier quota (the `--daily-cap 1000` what-if in the plan);
with billing enabled it is ~$10.10 at list price and limited only by the throttle. Recommendation: enable
billing before starting, or expect many exit-3 stops. Also: has_publications chunks average ~374 tokens, so
90 chunks/min is ~33.6k input tokens/min; if the free tier enforces a per-minute token cap the build will
hit minute-scope 429s there (handled by wait-and-retry, slower).

Command (Git Bash; run from the repo so `.env` supplies GEMINI_API_KEY and AUSCULTA_SESSION_SECRET; the log is
appended so resumed runs accumulate):

```
cd /c/dev/ausculta && .venv/Scripts/python.exe -m rag build --corpus-version 2026-11-16.1 --sources bdpm,cdc,cdc_vis,has_publications,medlineplus_genetics,medlineplus_topics,nccih,nci_pdq,nei,nhlbi,niams,nichd,niddk,nimh,wikipedia_medicine >> /c/dev/ausculta-data/logs/rag_build_2026-11-16.1.log 2>&1; echo "exit=$?" >> /c/dev/ausculta-data/logs/rag_build_2026-11-16.1.log
```

- Exit 0: collection `ausculta_corpus_2026_11_16_1` indexed with a signed manifest.
- Exit 3: embedding quota exhausted. Re-run the SAME command later; it re-chunks (~1 min) and resumes from the
  embedding cache with zero repeat embeddings. Progress: `manifests/build-state/ausculta_corpus_2026_11_16_1.json`.
- Exit 1: read the log (stderr carries `command_failed`).
- Do not change `--corpus-version` or the source list between resumes (a different version is a new collection).

After exit 0 (not before): `.venv/Scripts/python.exe -m rag eval --collection ausculta_corpus_2026_11_16_1`
(recalibrates the confidence gate for the new collection, ~20 min, 90 Decisions calls for the rerank sample),
then `.venv/Scripts/python.exe -m rag promote ausculta_corpus_2026_11_16_1` (refuses unless the rag gates pass;
`python -m rag rollback` returns to seed1). See ADR 0002 "Open points" before promoting. Run 4 change: promote
and rollback now re-sync `reports/rag.metrics.json` from the newest ONLINE report of the collection that
becomes live (or remove it, so the rag gates show MISSING, when that collection has none). Before this,
promoting the full build would have left seed1's numbers as the live gate metrics. Tests:
`test_promote_and_rollback_keep_the_live_gate_metrics_on_the_live_collection`,
`test_promote_without_an_online_report_removes_the_previous_collections_metrics`.

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
