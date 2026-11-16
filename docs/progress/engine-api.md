# ENGINE-API track progress

Updated after every deliverable. Status: done / in progress / not started.

## State at resume (2026-11-16, second resume)
- Deliverable 1 was done by the previous run (148 tests pass in tests/app/{pipeline,limits,storage,hospital}
  + tests/evals). The API layer (app/main.py, app/api/*) was written but had NO tests.
- Smoke check through httpx.ASGITransport: session, chat (medical streamed / verified, emergency,
  self-harm, injection, front desk, appointment form, smalltalk), health, ready, meta, hospital all answer
  and every SSE body satisfies evals/fakes/sse_contract.order_violations().

## Deliverables
| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | Tests for app/pipeline, app/limits, app/storage, app/hospital (+ bug fixes) | done | 148 tests pass (incl. tests/evals); app/pipeline ~99% line coverage |
| 2 | API layer (app/main.py create_app, composition root, routes, SSE, tokens, idempotency, errors, headers, CORS, body limit, proxy IP) | done | tests/app/api: test_api_ops (27), test_api_chat (59), test_api_forms (25), test_api_units (41) all pass |
| 3 | Contract + gate tests through the real ASGI app; engine.metrics.json | in progress | tests/app/api/test_api_gates.py (9) pass; runner evals/fakes/engine_gates.py; metrics file not yet written |

## Bugs found and fixed while testing (this resume)
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
| 4 | docs/runbook.md + live smoke test (<= 6 model calls) | not started | |
| 5 | Local uvicorn + curl exercise | not started | |

## Gate numbers
(none measured yet)

## Next step
Write tests/app/api (session/ops/errors/headers/CORS/body limit/tokens/proxy IP, chat SSE contract scenarios,
forms), then the gate runner (evals/fakes/engine_gates.py) and its tests.
