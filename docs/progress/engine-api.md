# ENGINE-API track progress

Updated after every deliverable. Status: done / in progress / not started.

## Deliverables
| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | Tests for app/pipeline, app/limits, app/storage, app/hospital (+ bug fixes) | done | 148 tests pass (incl. tests/evals); app/pipeline ~99% line coverage |
| 2 | API layer (app/main.py create_app, composition root, routes, SSE, tokens, idempotency, errors, headers, CORS, body limit, proxy IP) | done | tests/app/api: test_api_ops (27), test_api_chat (59), test_api_forms (25), test_api_units (41) all pass |
| 3 | Contract + gate tests through the real ASGI app; engine.metrics.json | done | tests/app/api/test_api_gates.py (9) pass; `python -m evals.fakes.engine_gates` + `--coverage-only` wrote all 5 engine records; `evals.run --only engine. --allow-missing`: PASS 5, FAIL 0, MISSING 0 |
| 4 | docs/runbook.md + live smoke test (<= 6 model calls) | done | runbook: components, start/stop, health checks, kill switch, limits, incident playbooks, data/privacy, verify commands. Live smoke passed (see below) |
| 5 | Local uvicorn + curl exercise | done | two runs, every SSE body well-formed (0 order violations); run 1 exposed a false prompt-leak withdrawal, fixed (answer_policy.v2), run 2 clean. Details below |

## Gate numbers (reports/engine.metrics.json, final run 2026-11-16, scripted fake LLM, after all code changes)
| Gate | Value | Budget | Notes |
|---|---|---|---|
| engine.emergency_latency_ms | 4.1 ms max (p95 2.68 ms, n=32, 0 model calls) | < 300 | EN/FR/AR emergency + self-harm, every model role hangs 2 s then fails |
| engine.disconnect_close_s | 0.0021 s max (n=8) | <= 1.0 | in-process ASGI max 0.0003 s (5 runs), live uvicorn socket max 0.0021 s (3 runs) |
| engine.cancel_slot_leaks | 0 (n=1000) | == 0 | 0 running turns, 0 open upstream streams; statuses 200:760, 499:240 (499 = cancelled server-side) |
| engine.coverage_guardrails | 0.9927 (2200 statements) | >= 0.90 | final full suite `pytest --cov` (line ratio = covered_lines / num_statements) |
| engine.coverage_overall | 0.9624 (11476 statements) | >= 0.80 | source = core, data_pipeline, rag, app, evals |

`evals.run --only engine. --allow-missing`: PASS 5, FAIL 0, PROVISIONAL 0, MISSING 0.
(First measurement earlier the same day: 4.2 ms, 0.0027 s, 0 leaks, coverage 0.9745 / 0.9214.)

Final full suite (`pytest --cov`, not live): 1292 passed, 1 failed, 6 deselected in 223 s. The failure is
tests/app/guardrails/test_guard_lexicon_combo_scan.py::test_real_lexicon_has_combinations (guardrails track;
its lexicon files were being edited by that agent during the run), not this track.
Track tests alone (tests/app/{api,pipeline,limits,storage,hospital} + tests/evals): 315 passed, 1 deselected (live).
Per-directory line coverage (final run): app/api 0.980, app/pipeline 0.996, app/limits 1.000, app/storage 0.985,
app/hospital 0.964, app/main.py 1.000, app/config_files.py 0.844, evals/fakes 0.937.
ruff check + ruff format --check clean on the track directories; mypy (strict) clean on app/api, app/main.py,
app/pipeline, app/limits, app/storage, app/hospital, app/config_files.py, evals/fakes.

## Live smoke test (deliverable 4, 2026-11-16)
`pytest -m live tests/app/api/test_api_live.py --junitxml=...`: 1 passed, run 3 times (4 model calls each, 12 total).
Last run: retriever = real (Qdrant alias ausculta_corpus, corpus_version 2026-11-16.seed1); medical question
events meta, notice, status x3, delta x5, answer, done; answer mode streamed with 3 citations, every [n] marker
present in the text; model calls decide:guard, embed:1, stream:answer, decide:verify; emergency message 0 model
calls, events start meta, safety(kind=emergency). Test now records these as junit properties.

## Local uvicorn + curl exercise (deliverable 5, 2026-11-16)
`uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000` (settings from .env = real Gemini backend,
real retriever; DATABASE_URL overridden to a scratch SQLite file so the shared dev DB was not touched). A curl
script exercised health, ready, meta, session, 4 chat turns, the appointment form and two error cases; every
.sse body was parsed with evals/fakes/sse_contract (parse_sse + order_violations). Server stopped afterwards.

| Request | Run 1 | Run 2 (after the prompt fix) |
|---|---|---|
| GET /health, /ready, /meta | 200; ready: all 5 checks true, paused false; corpus 2026-11-16.seed1 | same; prompt_hash 636aaf29.. -> 00343a6b.. |
| POST /session | 201 (11 ms) | 201 (14 ms) |
| chat "What is asthma and how is it treated?" | 200, 4.25 s; meta, notice(demo_mode), status x3, delta x10, answer(mode=refusal, replaces_stream), done; log `output_leak_detected` | 200, 5.98 s; meta, notice, status x3, delta x13, answer(mode=streamed, 2 citations), done |
| chat "my dad collapsed and he is not breathing" | 200, 11 ms total; meta, safety(emergency), answer(template), done | 200, 15 ms; same events |
| chat "What are the visiting hours?" | 200, 0.59 s; meta, status, answer(template: visiting hours 13:00-20:00), done | 200, 0.49 s; meta, status, safety(emergency), answer(emergency template), done (see open issue) |
| chat "I would like to book an appointment with cardiology" | 200, 0.32 s; meta, status, answer(template), form(appointment_request), done | same |
| POST /appointments (consent true) | 201 request_id AR-N3DZB2 | 201 |
| POST /appointments (consent false) | 422 invalid_input envelope | 422 |
| POST /chat without token | 401 unauthorized envelope | 401 |

SSE headers: content-type text/event-stream; charset=utf-8, cache-control no-store, x-accel-buffering no, nosniff,
x-frame-options DENY, referrer-policy no-referrer, CSP default-src 'none'. Server log: no message text.

Open issue (guardrails / guard prompt owner): in run 2 the guard model flagged "What are the visiting hours?" as an
emergency because the previous user message (2 s earlier) was one; guard.v1.yaml asks about emergencies "happening
now or very recently" with earlier messages as context. Conservative, but the visiting-hours question went
unanswered. Run 1 with the same messages did not do this (model-dependent).

## Bugs found and fixed while testing (second resume)
- False "prompt leak" withdrew good medical answers (seen in deliverable 5, run 1): answer_policy.v1 rule 8 told the
  model to say "that a possible emergency needs the local emergency number now"; a compliant closing sentence
  repeating it shares 2 word 8-grams with the system prompt, which output_checks treats as a system-prompt echo
  (fatal: whole answer replaced by the refusal template). The withheld sentence is not logged, so this cause is
  inferred, but that sentence reproduces it offline. Fix: config/prompts/answer_policy.v2.txt (rule 8 abstract)
  and the closing guidance moved into the per-turn request (prompts.CLOSING_GUIDANCE); PROMPT_VERSION
  answer_policy.v2+rewrite.v1+guard.v1; v1 kept for the audit trail. Tests:
  tests/app/pipeline/test_pipeline_prompt_echo.py (6). Re-run on the live server: streamed answer, 2 citations.
- mypy (strict, pyproject) on the track directories: 14 errors -> 0 (type-only changes: AsyncGenerator return
  type of TurnEngine.run, cast for LLMProvider.stream in aclosing, TurnStatus literal, functools.partial instead
  of default-arg lambdas in frontdesk, unused ignores removed).
- Turn cancellation could be swallowed: Python 3.11 `asyncio.wait_for` drops an outer `task.cancel()` when its inner
  awaitable completes in the same loop iteration (router/groundedness use wait_for). One `task.cancel()` in
  `TurnStream._stop_task` was lost and the whole turn ran on (~230 ms with the fake; with a real model it could
  exceed the 1 s grace and leave the upstream stream open). Fix: level-triggered cancel (re-cancel every 10 ms
  until the task exits) in app/api/turns.py; `asyncio.timeout` instead of `wait_for` in turns.py, rewrite.py,
  medical.py. Reported to the guardrails/llm owners (router.py, groundedness.py, gemini_provider.py use wait_for).
- First chat turn after start paid a 170 ms one-time import (anyio thread backend) before the emergency template:
  Container.startup now warms the thread pool + lexicon (`warm_up`). Emergency max 204 ms -> ~34 ms.
- Turn persistence ran before the HTTP terminator; now after it (SSEResponse on_close). SQLite dev DB uses
  `synchronous=NORMAL` with WAL.
- Safety events now come right after `meta`, before the demo notice.
- build_engine crashed at startup when the retriever's corpus_version raised; now degrades to "none".

## P3 review fixes (2026-11-17, docs/reviews/2026-11-16-p3-review.md)
21 findings fixed test-first; every fix has a regression test that failed before the change.

| ID | Change | Proving tests |
|---|---|---|
| C9/P8 | Chat route runs the deterministic precheck right after the token and length check; emergency / self-harm turns bypass kill switch, rate limits, turn budget, 409, per-client cap, spend cap and admission (own 60/min bucket) | tests/app/api/test_api_review_fixes.py `test_c9_*` (5) |
| S1 | Clients keyed by IPv4 or IPv6 /64 (IPv4-mapped -> IPv4); global session-creation cap 300/min; 2 running model turns per client (429 scope `concurrent`) | `test_s1_*` (4), tests/app/limits/test_limits_review_fixes.py, tests/app/api/test_api_gate.py |
| P2/S5 | New app/api/gate.py: MemoryTurnGate / RedisTurnGate (SET NX EX lock + compare-and-delete, INCR/DECR per-client count, shared replay frames <= 64 KiB, TTLs); SessionStore.apply(state, SessionUpdate) atomic deltas (Redis: HINCRBY/SADD/RPUSH+LTRIM in MULTI) | tests/app/pipeline/test_pipeline_session_atomic.py, test_api_gate.py, `test_p2_*` (two apps on one FakeRedis) |
| C6 | high_risk = model verdict OR classifier down OR sticky OR heuristic medication/symptom intent OR population regex (app/pipeline/heuristics.py, EN/FR/AR/Darija); population threshold capped at 0.3 | test_pipeline_review_fixes.py `test_c6_*` |
| C7 | MEDICATION: drug_label filter on every query, non-label passages dropped, abstain (`no_drug_label`) without one; citation publisher tagged with the label jurisdiction (US FDA / ANSM / EMA / unknown, localised) | `test_c7_*` |
| C8 | Rewriter re-raises UpstreamBlocked -> refusal + sticky flag; guard block -> sticky flag (no strike); refusal_blocked names the crisis line | `test_c8_*` |
| C10 | enforce_demo_policy: a demo profile is refused unless demo mode in dev/test (profile None, error log, API keeps running) | `test_c10_*` (pipeline + API) |
| C11 | `call_fallback` phrases that follow each call verb; sentences needing handoff/switchboard dropped without a profile; neutral `safety_followup_no_contacts` | `test_c11_*` |
| C13 | Turn count, history, precheck sticky risks and precheck strike saved before the guard call (strike counted once) | `test_c13_*` |
| C14 | Classifier down + Latin text without English cues -> UI locale | `test_c14_*` |
| C15 | Engine and TurnStream send a replacing busy answer before the error when deltas were streamed | `test_c15_*` (pipeline + stream level) |
| P5 | 45 s per-turn deadline -> busy template (degraded `deadline`) | `test_p5_*` |
| P10/S9 | Non-ASCII bearer token -> 401 (bearer_token + signer.verify) | `test_p10_*` |
| P12 | Container.warm_up awaits retriever.warmup(); failure logged | `test_p12_*` |
| P16/P17 | RedisError / limits StorageError / SQLAlchemyError -> 503 dependency_unavailable (+ store wrappers); Redis client closed on shutdown | `test_p16_*`, `test_p17_*`, test_limits_review_fixes.py |
| S6/P7 | Storage.purge_expired with RETENTION (appointments 30 d, sessions/turns 90 d, feedback 180 d, audit 365 d); purge task at startup + hourly | tests/app/storage/test_storage_review_fixes.py, `test_s6_*` |
| S7 | Appointment caps 3/session, 10/client/day, 500/day; feedback 40/session, 200/client/day, 5000/day; request-code collision retried 5x | `test_s7_*`, storage tests |
| S17 | History window capped at 3 user turns | `test_s17_*` |
| S18 | Appointment e-mail sanitised, quotes / angle brackets / backticks rejected | `test_s18_*` |
| S8/P6 (api side) | Real retriever wrapped in app/api/corpus.py VerifiedRetriever; startup task runs rag.verify.verify_live_corpus; fail closed (no retrieval, /ready 503) until it passes | tests/app/api/test_api_corpus.py (7) |
| P15 | Appointment, contact and audit rows in one transaction | storage `test_appointment_and_its_audit_event_commit_together`, `test_audit_failure_rolls_back_the_appointment` |

Also: every AnswerEvent / SafetyEvent now carries `language`; the two tests broken by the stricter
core/config.py (HSTS staging, session secret) supply the required fields / assert the ValidationError.

Gates after the fixes (evals.fakes.engine_gates, 2026-11-17): emergency template 10.78 ms max (p95 9.53,
0 model calls), upstream close after disconnect 0.0019 s, 0 leaked slots after 1000 cancels (200:750, 499:250).

## Next step
For the lead: review/commit (no git state changed here). Open items are listed in the review file and the
final report of the review-fix run (Settings fields for the new caps, Caddy rate limit, Redis memory alert,
guardrails root cause of C14).
