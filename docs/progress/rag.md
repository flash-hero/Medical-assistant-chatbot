# P3B RAG track: progress

Owner dirs: `rag/`, `tests/rag/`, `evals/retrieval/`, `docs/decisions/0002-retrieval.md`; data root `chunks/`,
`embed-cache/`, `manifests/`, `reports/retrieval/`, `reports/rag*`; Qdrant collections and the `ausculta_corpus` alias.

## Deliverables (continuation runs, 2026-11-16)

| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | `tests/rag` suite green, coverage >= 80% for `rag/` + `evals/retrieval/` | done (re-run at the end) | Re-verified 10:50 UTC: 126 passed, 0 failed; every `rag/` and `evals/retrieval/` module >= 87%. Root cause of the original 15 FAILED / 12 ERROR: `rag.cli.configure_logging()` bound structlog to pytest's captured `sys.stderr`, closed after the CLI test ("I/O operation on closed file"). Fixed + regression test. |
| 2 | Seed index live behind alias `ausculta_corpus` | done | `ausculta_corpus_2026_11_16_seed1` promoted 06:23 UTC with `--override-gates "<reason>"` (signed-manifest check still enforced; reason in `manifests/active.json`). Live check through `build_retriever(settings, llm)` passed (EN asthma -> MedlinePlus Asthma top 1). |
| 3 | Retrieval evaluation (gold EN/FR/AR + OOC, ablations, calibration, report, metrics, ADR 0002) | in progress | Gold: `gen_20261116T062632Z_{en,fr,ar}.jsonl` generated 06:25 UTC by gemini-3.5-flash-lite (60 passages x 3 langs + 30 OOC x 3, FR/AR English rewrites by the model without the passage; ~11 generation calls, estimated from the file contents since that run's stdout was lost) + `agent_seed1_*` (36 answerable + 24 OOC per lang). Total 450 rows, 599 distinct query texts. 10:50 UTC: per-run gate records renamed `<stamp>.gates.json` (evals.run reads every `*.metrics.json`, newest wins, so an offline or validation-collection eval would have replaced the live numbers); `reports/rag.metrics.json` is now written only by an ONLINE eval of the alias target. Online eval started 10:52 UTC (log `reports/retrieval/run-online-20261116.log`). |
| 4 | Full-build preparation (chunk counts per ACTIVE source, ETA at 90 chunks/min, `--limit 50` validation on 2 non-MedlinePlus sources, exact command for the lead) | not started | `python -m rag plan` exists (dry run, no API). Free-tier DAILY embedding cap (~1,000 texts/day, observed) dominates the ETA. |

## State found at start of this run (10:41 UTC)

- Collections: `ausculta_corpus_2026_11_15_1` (720 of 5,564 chunks, build stopped on daily quota, no manifest) and
  `ausculta_corpus_2026_11_16_seed1` (720 chunks, 327 MedlinePlus topic docs A..Electrical Injuries, signed manifest).
  Alias -> seed1 (override). Query-embedding cache empty.

## Next step

See the first row that is not `done`.
