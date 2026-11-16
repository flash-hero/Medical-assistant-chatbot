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
| 1b | ruff check + format clean on data_pipeline/ and tests/data_pipeline/ | not started | do after new code is written |
| 2 | registry --check passes; every ACTIVE source has licence record + evidence URL | done (re-verify after new sources) | |
| 3 | report: data_gates.json, data.metrics.json, audit-sample.md, ATTRIBUTION.md, attribution.json | done (first pass) | re-run in step 5 |
| 4a | Wikipedia EN/FR/AR | partial (code + 19 tests done; live fetch BLOCKED) | registry entry wikipedia_medicine (active, CC BY-SA 4.0, tier 3), parsers/wikipedia{,_api,_text}.py, tests/test_dp_wikipedia.py. Live fetch needs AUSCULTA_CRAWLER_CONTACT (Wikimedia returns HTTP 403 to a User-Agent without contact details; contact is the operator's identity so it is not invented). Run: set AUSCULTA_CRAWLER_CONTACT=<email or URL>; python -m data_pipeline run --source wikipedia_medicine |
| 4b | EMA product information (FR) | not started | |
| 4c | BDPM (FR) | done | bdpm: 12,643 FR documents (13,559 parsed, 916 near-duplicate by template); registry entry (Licence Ouverte), parsers/bdpm.py, 16 tests; files hold NO SmPC/leaflet text (administrative, composition, prescription, HAS SMR, generics only) |
| 4d | HAS open data | not started | |
| 5 | Re-run report with new sources | not started | |

## Next step
Step 4d HAS open data, then 4b EMA (site rate-limits our UA: JSON reports return 429), then ruff clean-up and report re-run.
