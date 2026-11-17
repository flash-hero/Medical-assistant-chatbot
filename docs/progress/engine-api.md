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

## Next step
Track complete. For the lead: review/commit (no git state changed here); guardrails owner to look at the
lexicon-combination test failure and the guard flagging a front-desk question as an emergency right after an
emergency message (see deliverable 5).
