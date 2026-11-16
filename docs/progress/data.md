# DATA track progress

Updated after every deliverable. Status: done / in progress / not started.

## State at resume (2026-11-16, second run)
- 13 sources normalised and ready (15,971 documents).
- Verified by running (not assumed): `pytest tests/data_pipeline` = 249 passed; package coverage `data_pipeline` = 93 % (only the
  new `parsers/wikipedia_api.py` was at 0 %); `python -m data_pipeline.registry --check` = 34 sources, 13 active, 0 violations;
  `python -m evals.run --only data. --allow-missing` = 4 PASS, 1 MISSING (manual audit, stays not_run by design).
- Outstanding at resume: ruff check/format not clean on the track directories (E501, PT018, ASYNC240, RUF005/043, I001).

## Deliverables
| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | Tests for 0%-coverage modules | done | 249 tests, 93 % coverage at resume; wikipedia_api tests added in step 4a |
| 1b | ruff check + format clean on data_pipeline/ and tests/data_pipeline/ | done | ruff check: All checks passed; ruff format --check: 57 files formatted. Long regex/fixture lines carry inline noqa E501; 302 tests pass |
| 2 | registry --check passes; every ACTIVE source has licence record + evidence URL | done (re-verify after new sources) | |
| 3 | report: data_gates.json, data.metrics.json, audit-sample.md, ATTRIBUTION.md, attribution.json | done (first pass) | re-run in step 5 |
| 4a | Wikipedia EN/FR/AR | done | Fetch was already complete in the cache when the PC restarted (manifest: 3,367 requests, all HTTP 200: ar 1,148, fr 980, en 1,239 incl. listing/langlink calls; 1,185 English source titles). Resume run (log C:\devusculta-data\logs\wiki_fetch.log) served everything from cache, no new request. Parsed: 3,308 pages -> 3,257 documents (en 1,181, ar 1,121, fr 955); 45 dropped (36 too_short, 8 duplicate_doc_id, 1 language_mismatch), 6 quarantined (genuine pattern hits in benign prose: en_ignore_previous x2, en_pretend, en_ai_address, ar_pretend, ar_ai_address x1; left quarantined, 0.2 %, conservative). Fix: ar_ai_address / ar_roleplay_mode lacked a trailing word boundary and quarantined 21 Arabic articles (and one via ar_roleplay_mode) because of the phrase 'الي مساعده' ("to the assistance of"); added (?!\w) + regression case in test_dp_quality.py, re-parsed. _ready marker written. Registry entry wikipedia_medicine (CC BY-SA 4.0, tier 3). |
| 4b | EMA product information (FR) | skipped (hold) | re-probed 2026-11-16: robots.txt 200, JSON report still HTTP 429 (CloudFront). Not worked around; reason recorded in registry notes; source stays status hold. |
| 4c | BDPM (FR) | done | bdpm: 12,643 FR documents (13,559 parsed, 916 near-duplicate by template); registry entry (Licence Ouverte), parsers/bdpm.py, 16 tests; files hold NO SmPC/leaflet text (administrative, composition, prescription, HAS SMR, generics only) |
| 4d | HAS open data | done | has_publications: 2,593 FR documents kept (2,967 parsed, 5 quarantined for real injection-like patterns, 369 dropped: dup/short/language). PDF symbol-font glyphs (U+F0xx) mapped to bullets in parsers/has_publications.py (before the fix 764 were quarantined for unicode_private_use). 18 tests in test_dp_has.py. Ready marker written. |
| 5 | Re-run report with all sources | done | `python -m data_pipeline report` (log logs/data_report.log): 16 sources, 34,464 documents. data_gates.json, data.metrics.json, docs/sources/{audit-sample.md, ATTRIBUTION.md, attribution.json} regenerated. Gates: licence_coverage 1.0 PASS, excluded_sources 0 PASS, near_duplicates 0.0 (sample 1000) PASS, injection_quarantine 1.0 PASS, manual_audit NOT_RUN by design. |
| 6 | Final checks | done | pytest tests/data_pipeline: 303 passed, coverage data_pipeline 96 % (2,762 stmts); registry --check: 38 sources, 16 active, 0 violations; ruff check + format --check clean (57 files) |

## Next step (updated)
DATA track complete except 4b EMA (held: HTTP 429, not worked around) and the manual audit (human). Wikipedia fetch is complete (no resume needed); if a refresh is ever wanted: `set AUSCULTA_CRAWLER_CONTACT=...` then `python -m data_pipeline run --source wikipedia_medicine -v` (cached requests are not repeated).
