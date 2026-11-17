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
| 5 | Local embeddings (ADR 0003) + review fixes S8/P6, P19, P3 (readiness), P12 (warmup), P20 | done (code), rebuild pending | Run 5: code + tests; no collection or alias changed. `tests/rag` (2026-11-17 12:50 UTC): 169 passed, 1 skipped (opt-in full seed eval) without `services`, plus 2/2 `services` tests against the real server; coverage 97% for `rag/` + `evals/retrieval/` (lowest `rag/fileio.py` 87%, `rag/cli_eval.py` 93%); ruff + format clean; mypy strict clean on `rag/` + `evals/retrieval/`. Real-model dense check PASS (10/10 top-1). The lead runs the rebuild/eval/promote commands in Run 5. |

## Run 5 (22:00-23:30 UTC): local embeddings + review fixes (code only, Qdrant untouched)

Why: ADR 0003. The free tier embeds 1,000 texts/day and billing cannot be enabled, so documents AND queries
are now embedded by `google/embeddinggemma-300m` (ONNX, CPU) through `app.llm.factory.build_embedding_provider`.
Qdrant was first reported stopped, so tests use qdrant-client local mode; the lead later confirmed it had
kept running (PID 21244) and approved the `services` tests. Only throwaway test collections were created
and deleted there; no real collection or the alias was touched.

Changes (all uncommitted; tests for each):
- `rag/embedding.py`: `DocumentEmbedder` / `QueryEmbedder` take a `core.ports.EmbeddingProvider`;
  `EmbeddingBackend` + `embedding_backend(settings, llm=None)` = the deployment's one model (provider, cache
  namespace, `quota_limited`). Per-minute waits / daily-quota stop only when `quota_limited` (Gemini); the
  local backend never sleeps and its errors propagate (build exit 1 with the resume command; the cache keeps
  every committed 90-chunk batch). `QueryEmbedder.warmup()` loads the model.
- P19: cache namespace `"<model id>@fmt1"` (`EMBED_TEXT_FORMAT`; a test pins the document/query strings and
  says to bump it). Local = `google/embeddinggemma-300m@fmt1`. Old Gemini vectors stay under
  `gemini-embedding-2` (unused).
- `rag/retrieval.py`: `build_retriever(settings, llm)` unchanged signature, embeds queries with
  `embedding_backend(settings, llm=llm)`; `warmup()` = BM25 analysers + embedding model (P12);
  `health()` = real BM25 encode + 1-result sparse search + non-empty count, 3 s bound, never raises (P3).
- S8/P6: `rag/signing.py` (scheme `ausculta-manifest-v1`: HKDF-SHA256 key from `AUSCULTA_SESSION_SECRET`,
  info `ausculta-manifest-v1`; HMAC over all manifest fields + digest of the served fields of every stored
  chunk) and `rag/verify.py` (recomputes `sha256(context_header + "\n" + text)` from stored text, checks
  point ids, count, embed model and HMAC). Promote and rollback use it. New error
  `rag.errors.CorpusUnverified` (code `corpus_unverified`, subclass of `IndexMismatch`). Old manifests
  (seed1, val50) no longer verify (Gemini collections anyway).
- API startup hook (to be wired by the API track):
  `async def rag.verify.verify_live_corpus(settings: Settings, *, client: AsyncQdrantClient | None = None) -> VerifiedCorpus`
  returns `VerifiedCorpus(collection, corpus_version, embed_model, chunks)` or raises `CorpusUnverified`
  (no secret, no alias, no/foreign manifest, other embedding model, edited payload, missing/extra points,
  Qdrant unreachable). It reads every payload once (signed fields only, no vectors).
- `rag eval` (online) refuses a collection built with another embedding model; reports carry `embed_model`
  and `collection_embed_model`. `rag promote` / `rollback` refuse it too.
- `rag plan`: ETA from the backend: local 2.7 chunks/s = 162/min (spike S7); Gemini keeps 90/min, the
  cost line and the daily cap (now 1,000 texts/day by default, confirmed). No embedding call, no model load.
- P20: `rag/build.py::_state` typed (no more `type: ignore`), `rag/cli_plan.py` imports `load_registry` from
  `rag.registry`; also fixed the 7 mypy errors in `evals/retrieval/` (`gold.py`, `generate.py`,
  `resume_check.py`). `rag/` + `evals/retrieval/`: mypy strict clean (40 files).
- `evals/retrieval/dense_check.py`: dense-only check without Qdrant (numpy cosine), used by tests and for
  the one real-model check below.
- Tests: conftest guard makes any attempt to LOAD the real embedding model fail the test (pytest.fail).

Evidence:
- Offline seed re-evaluation (fake provider, local-mode Qdrant, real seed chunks + gold,
  `tests/rag/test_rag_dense_check.py`): the 720 seed chunks re-indexed with production payloads/BM25 give
  sparse-only R@8 0.927 / 0.948 / 0.927 and R@20 0.958 / 0.948 / 0.938 (EN / FR / AR), identical to ADR 0002's
  server row; MRR / nDCG@8 within 0.006. The new manifest signature verifies on those real payloads. The full
  offline `run_eval` of the seed (all 4 ablations, calibration, gates) passed once (154 s) and is opt-in
  (`AUSCULTA_SEED_EVAL=1`).
- Real-model check, 2026-11-17 12:52 UTC, one process, 6.7 GB RAM free:
  `python -m evals.retrieval.dense_check --chunks .../chunks/2026-11-16.seed1/medlineplus_topics.jsonl
  --questions 10 --total-chunks 20 --backend local`: 20 seed chunks + 10 gold questions (4 EN, 3 FR, 3 AR,
  question text only, cross-lingual for FR/AR) embedded in 7.8 s incl. model load; all vectors 768-d,
  finite, max |norm - 1| 6.9e-08; the relevant chunk ranked FIRST for 10 of 10 questions. Exit 0 (PASS).
- Real server (read-only, 2026-11-17 12:54 UTC, after the lead confirmed Qdrant up): `verify_live_corpus`
  on the alias -> `corpus_unverified`: "ausculta_corpus_2026_11_16_seed1 holds gemini-embedding-2 vectors
  but this deployment embeds queries with google/embeddinggemma-300m@fmt1" (correct: rebuild needed);
  seed1 with the model check skipped -> "stored chunks do not match the signed manifest" (old scheme, as
  expected); `build_retriever(...).health()` on the alias -> True (real BM25 encode + sparse search).
  `test_signature_survives_the_real_servers_json_round_trip` (throwaway collection, deleted) passes: the
  signature holds through the server's JSON payload round trip and an edited url is caught.

### Commands for the lead after restarting Qdrant (local embeddings)

Git Bash, from the repo (`.env` supplies `AUSCULTA_SESSION_SECRET`; `AUSCULTA_EMBED_BACKEND` defaults to
`local`). Memory: only ONE process may hold the embedding model (build, eval and the API each load it), so
run these one at a time and stop the API meanwhile; Qdrant must be running. `rag status`, `rag promote`
and the verify one-liner never load the model. The old collections (`..._2026_11_16_seed1`, alias target,
and `..._2026_11_16_1`, a stopped Gemini build with 720 points) hold Gemini vectors and old-scheme manifests:
they no longer verify and must not serve local query vectors.

(a) Seed rebuild with local embeddings, eval + calibration, promote (~5 min build, ~5 min eval):

```
cd /c/dev/ausculta && .venv/Scripts/python.exe -m rag status
.venv/Scripts/python.exe -m rag build --corpus-version 2026-11-17.seed2 --sources medlineplus_topics --limit 327 >> /c/dev/ausculta-data/logs/rag_build_2026-11-17.seed2.log 2>&1; echo "exit=$?" >> /c/dev/ausculta-data/logs/rag_build_2026-11-17.seed2.log
# the gold set references seed1 chunk ids: expect "720 720 True"
.venv/Scripts/python.exe -c "import json,pathlib as p; ids=lambda v: {json.loads(l)['chunk_id'] for l in p.Path(f'C:/dev/ausculta-data/chunks/{v}/medlineplus_topics.jsonl').read_text(encoding='utf-8').splitlines()}; a,b=ids('2026-11-16.seed1'),ids('2026-11-17.seed2'); print(len(a),len(b),a==b)"
# online eval = ablations + confidence-gate calibration (writes manifests/ausculta_corpus_2026_11_17_seed2.retrieval.json);
# --rerank-sample 0 keeps rerank OFF (ADR 0002) and makes ZERO Gemini calls
.venv/Scripts/python.exe -m rag eval --collection ausculta_corpus_2026_11_17_seed2 --rerank-sample 0 > /c/dev/ausculta-data/reports/retrieval/run-online-2026-11-17.seed2.log 2>&1; echo "exit=$?"
.venv/Scripts/python.exe -m rag promote ausculta_corpus_2026_11_17_seed2
# the API startup check (signature, payloads, embedding model of the alias target):
.venv/Scripts/python.exe -c "import asyncio; from core.config import get_settings; from rag.verify import verify_live_corpus; print(asyncio.run(verify_live_corpus(get_settings())))"
.venv/Scripts/python.exe -m pytest tests/rag -m services -q -p no:cacheprovider
```

- eval exit 0 = gates pass, 4 = a gate FAILED (read the log), 1 = error. The report includes
  `embed_model` (`google/embeddinggemma-300m@fmt1`); compare dense vs hybrid and the abstention rates with
  ADR 0002 (false abstention was 0.090 with Gemini, gate 0.10).
- promote refuses (exit 4) unless that collection's newest ONLINE report passes the rag gates; for a
  development seed only: `--override-gates "<reason, >= 10 chars>"`. The signed-manifest and
  embedding-model checks are never overridable.
- Optional cleanup once seed2 is live (rollback to them is impossible anyway):
  `curl -X DELETE http://127.0.0.1:6333/collections/ausculta_corpus_2026_11_16_1` and the same for
  `ausculta_corpus_2026_11_16_seed1`.

(b) Full build of all 15 ready sources (openfda_labels excluded), about 19.4 h on this CPU
(~188,9xx unique chunks to embed at 2.7 chunks/s = 162/min; the 720 seed2 chunks are cache hits; no API
cost, no quota). Plan first (dry run, no model load, no Qdrant), then build:

```
cd /c/dev/ausculta && .venv/Scripts/python.exe -m rag plan --exclude openfda_labels --corpus-version 2026-11-17.1 > /c/dev/ausculta-data/reports/rag-plan-20261117.txt 2>&1
.venv/Scripts/python.exe -m rag build --corpus-version 2026-11-17.1 --sources bdpm,cdc,cdc_vis,has_publications,medlineplus_genetics,medlineplus_topics,nccih,nci_pdq,nei,nhlbi,niams,nichd,niddk,nimh,wikipedia_medicine >> /c/dev/ausculta-data/logs/rag_build_2026-11-17.1.log 2>&1; echo "exit=$?" >> /c/dev/ausculta-data/logs/rag_build_2026-11-17.1.log
```

- Resumable: after a kill, reboot, Windows memory kill or exit 1 ("Embedding failed ... Re-run"), run the
  SAME command again: it re-chunks (~1-2 min) and every committed 90-chunk batch is a cache hit (zero
  repeat embeddings). Progress: `manifests/build-state/ausculta_corpus_2026_11_17_1.json`
  (`indexed_chunks` / `total_chunks`). Exit 3 cannot happen on the local backend.
- Do not change `--corpus-version` or the source list between resumes. Keep the API stopped (memory: all
  ~189k chunks + the model + BM25 in one process). `AUSCULTA_EMBED_THREADS=N` leaves cores free if needed.
- Exit 0 prints `Indexed ... into ausculta_corpus_2026_11_17_1` and writes the signed manifest.

(c) Eval, calibration and promotion of the full build (after (b) exits 0):

```
cd /c/dev/ausculta && .venv/Scripts/python.exe -m rag eval --collection ausculta_corpus_2026_11_17_1 --rerank-sample 0 > /c/dev/ausculta-data/reports/retrieval/run-online-2026-11-17.1.log 2>&1; echo "exit=$?"
.venv/Scripts/python.exe -m rag promote ausculta_corpus_2026_11_17_1
.venv/Scripts/python.exe -c "import asyncio; from core.config import get_settings; from rag.verify import verify_live_corpus; print(asyncio.run(verify_live_corpus(get_settings())))"
```

- Read ADR 0002 "Open points" before promoting (dense-only vs hybrid rule, recalibration, single-relevant
  seed gold on a 189k-chunk index). `python -m rag rollback` returns to the previous verified collection
  (seed2). Restart the API afterwards so its startup verification runs on the new alias target.

## Run 4 (started 16:39 UTC, after the PC restart)

- Qdrant up; only `ausculta_corpus_2026_11_16_seed1` exists, alias -> seed1. The r5 full eval had finished
  before the restart (exit 0, 12:19 UTC); nothing re-run. `evals.run --only rag.`: PASS 4, PROVISIONAL 3, FAIL 0.
- Wrote `docs/decisions/0002-retrieval.md` (numbers, rerank OFF, open points).
- Plan re-run with wikipedia_medicine ready (16:45 UTC). One synthetic single-text embedding probe at 16:48 UTC
  to check for an exhausted daily quota: it succeeded.
- Code: promote/rollback re-sync `reports/rag.metrics.json` (`rag/cli_eval.py::sync_live_metrics`,
  `evals/retrieval/report.py::latest_report(mode=)`), 2 tests. No other code change.

## Full build (for the lead) — prepared 2026-11-16 16:50 UTC, NOT started

SUPERSEDED by Run 5 (local embeddings, ADR 0003): use "Commands for the lead after restarting Qdrant" above.
The Gemini command below would now build with the local model anyway (AUSCULTA_EMBED_BACKEND=local).

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
