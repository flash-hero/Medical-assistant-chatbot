# Ausculta API runbook

Operating the API (`app/`): start, check, pause, recover. The HTTP contract is `docs/contracts/api.md`; the
release gates are `evals/gates.yaml`. Nothing here needs the contents of `.env`: never paste or print it.

## 1. What runs

| Component | Dev (Windows, this machine) | Required for |
|---|---|---|
| API | `uvicorn app.main:create_app --factory` (one process) | everything |
| Qdrant 1.20.1 | native binary, `sh scripts/dev/qdrant.sh`, `http://127.0.0.1:6333`, alias `ausculta_corpus` | medical answers (`/ready` = 503 without it) |
| Relational DB | SQLite `C:/dev/ausculta-data/ausculta.db` (WAL) ; Postgres via `DATABASE_URL` in compose | sessions, turns, appointments, feedback |
| Redis (optional) | none in dev (`REDIS_URL` unset: in-memory sessions, limits and spend meter) | multi-instance deployments |
| Gemini API | `GEMINI_API_KEY` from `.env` | every model-backed turn |

With `REDIS_URL` unset the session store, rate limits and daily spend meter live in the process: a restart
forgets them, and two API processes would not share them. Run one process per host in that mode.

## 2. Start and stop (dev)

```sh
# 1. Qdrant (skip if http://127.0.0.1:6333 answers)
sh scripts/dev/qdrant.sh            # run in the background; storage under C:/dev/ausculta-data/qdrant

# 2. API on 127.0.0.1:8000 (reads .env; AUSCULTA_ENV=dev exposes /api/v1/docs)
.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Offline / no-quota mode: `AUSCULTA_LLM_BACKEND=fake` uses the scripted fake model and synthetic passages (no
API call, no Qdrant). Use it for UI work and demos of the flow, never for content review.

Startup does, in order: create the schema (SQLite or dev/test only), purge expired appointment requests,
warm the safety precheck (lexicons, regex caches, thread pool) so the first emergency turn is not slower than
later ones. Stop with Ctrl+C: in-flight turns are cancelled, upstream model streams are closed, the DB pool
and HTTP clients are released.

`AUSCULTA_SESSION_SECRET` (>= 32 chars) is required in staging/prod. Without it (dev/test only) a random
secret is generated and every session token becomes invalid on restart (log event `session_secret_ephemeral`).

## 3. Health checks

| Check | Meaning | Healthy |
|---|---|---|
| `GET /api/v1/health` | process answers; checks nothing | `200 {"status":"ok"}` |
| `GET /api/v1/ready` | database, session store, rate limiter and retriever answer | `200 {"status":"ready","checks":{...},"paused":false}` |
| `GET /api/v1/meta` | release tuple of the next turn | `corpus_version` is not `none`, `demo_mode` as intended |
| `GET /api/v1/hospital?locale=fr` | active hospital profile | `200`; `404` means no valid profile (see 6.4) |

`/ready` returns `503` + `Retry-After: 10` with the failing check set to `false`; `hospital_profile` is
reported but does not fail readiness. `paused: true` means the kill switch is on.

## 4. Pause everything: kill switch

Two ways, either is enough:

```sh
# no restart: create the file (checked at most once per second)
touch C:/dev/ausculta-data/KILL_SWITCH          # pause
rm C:/dev/ausculta-data/KILL_SWITCH             # resume

# with a restart: AUSCULTA_KILL_SWITCH=true
```

While paused every `POST /chat` gets `503 service_paused` with `Retry-After: 300` and the localised text
"The assistant is paused for maintenance. In an emergency, call your local emergency number." This includes
emergency messages: the page must keep showing the emergency number from `/hospital`, which stays up, as do
sessions, appointment requests, feedback and the ops endpoints. Confirm with `/ready` (`"paused": true`).

When to pull it: unsafe or wrong answers reported (feedback `reason=unsafe`), a prompt-injection campaign, a
data or licence problem in the corpus, an API key leak, or spend running away.

## 5. Cost and load limits

| Limit | Setting (default) | Client sees |
|---|---|---|
| Daily spend cap (UTC day) | `AUSCULTA_DAILY_SPEND_CAP_USD` (5.0) | model-backed turns `503 service_paused`, `Retry-After` = seconds to 00:00 UTC |
| Requests per IP / minute | `AUSCULTA_RATE_IP_MIN` (20) | `429 rate_limited` + `Retry-After` |
| Requests per session / minute | `AUSCULTA_RATE_SESSION_MIN` (10) | `429 rate_limited` |
| Turns per session (2 h token) | `AUSCULTA_MAX_TURNS` (20) | `429 session_exhausted` |
| Concurrent model-backed turns | `AUSCULTA_LLM_CONCURRENCY` (8) | waits in the queue |
| Queue length / max wait | `AUSCULTA_QUEUE_MAX` (32) / `AUSCULTA_QUEUE_WAIT_S` (5) | `503 overloaded` + `Retry-After` |
| One running turn per session | fixed | `409 turn_in_progress` |
| Message length | `AUSCULTA_MAX_MESSAGE_CHARS` (2000) | `422 invalid_input` |
| Request body | 32 KiB | `413 payload_too_large` |

Emergency and self-harm turns detected by the deterministic precheck call no model: they skip the spend
cap and the admission queue and are answered from templates even when every model is down or the queue is
full (gate `engine.emergency_latency_ms`). Behind a reverse proxy set `AUSCULTA_TRUSTED_PROXY_COUNT` to the
number of proxies that append to `X-Forwarded-For` (Caddy alone: 1); leave it at 0 when the API is reached
directly, otherwise clients can spoof their address and dodge the IP limit.

## 6. Incidents

### 6.1 Gemini rate limited (429) or down
Symptoms: after the fallback model also fails, medical answers come back as the fixed "I'm very busy right
now ... try again in a few minutes" template (answer mode `template`, turn record degraded `busy`); logs
show `upstream_*` error codes. Emergency templates and front-desk answers from the profile keep working. On the free tier the quota is shared by every tool using the key: stop
batch jobs (embedding builds, evals) first. If it lasts, pull the kill switch rather than serve degraded
answers for hours. Never switch to an unpinned `-latest` model to get around it.

### 6.2 Qdrant unreachable or the alias is missing
`/ready` reports `"retriever": false`; medical questions get a `degraded` notice and the "Medical information
is temporarily unavailable" template (log `retrieval_failed`), front-desk and safety turns keep working. Check `curl http://127.0.0.1:6333/aliases` and restart Qdrant
(`sh scripts/dev/qdrant.sh`). If the API started while the retriever could not be built (log
`retriever_build_failed`), restart the API after Qdrant is back.

### 6.3 Bad corpus release
Answers cite the wrong material or the rag gates regress: roll the alias back with
`.venv/Scripts/python.exe -m rag rollback` (`python -m rag status` shows the alias target). The running API
follows the alias and `manifests/active.json` without a restart; `/meta` shows the `corpus_version` now in
use. Every turn record stores the release tuple, so affected turns can be listed afterwards.

### 6.4 Hospital profile missing, invalid or expired
Log `hospital_profile_loaded` at start shows the profile id and `expires_on`. An invalid or expired profile
never stops the app: receptionist features are disabled, `/hospital` returns `404`, and safety templates fall
back to "call your local emergency number". Fix `config/hospital/<file>.yaml` (or
`AUSCULTA_HOSPITAL_PROFILE`), re-verify it with the hospital, update `verified_by` / `expires_on`, restart.
The demo profile (`config/hospital/demo.yaml`) is fictional and flagged `is_demo`.

### 6.5 Database unavailable
`/ready` reports `"database": false`; `POST /session` returns `503 dependency_unavailable`. For SQLite check
disk space and that no other process holds `ausculta.db` open for writing; restart the API.

### 6.6 Abuse from one client
Lower `AUSCULTA_RATE_IP_MIN` and restart, block at the proxy, or pull the kill switch. Logs carry the
session id and error codes, never message text.

### 6.7 Suspected key leak
Kill switch on, rotate the key in Google AI Studio, update `.env` (never commit it), restart, kill switch off.

## 7. Data and privacy
- Chat messages are never logged. Logs are structured (JSON outside dev/test) and carry ids, codes and timings.
- Appointment requests are never sent to the model, are stored for staff with a 30-day retention, and expired
  ones are purged at every API start (log `appointments_purged`). Restart at least daily in production or run
  the purge from a scheduled job.
- Turn records hold the release tuple (app version, corpus version, prompt hash, model ids), intent, risk
  kinds, answer mode, degradations, per-stage latencies and audit entries, not the message text; they are what
  an audit of a reported answer starts from.

## 8. Verify a build

```sh
.venv/Scripts/python.exe -m pytest tests/app -q                         # unit + contract, fake model, no network
.venv/Scripts/python.exe -m evals.fakes.engine_gates                     # engine gates -> reports/engine.metrics.json
.venv/Scripts/python.exe -m pytest --cov --cov-report=json:cov.json      # then merge coverage into the metrics:
.venv/Scripts/python.exe -m evals.fakes.engine_gates --coverage-only \
    --coverage-json "all=cov.json" --coverage-json "app/guardrails app/pipeline=cov.json"
.venv/Scripts/python.exe -m evals.run --only engine. --allow-missing     # evaluate the engine gates
.venv/Scripts/python.exe -m pytest -m live tests/app/api/test_api_live.py --junitxml=live.xml
```

The live smoke test makes at most 6 real model calls (one medical question through the real retriever when
the `ausculta_corpus` alias exists, plus one emergency message that must make none) and skips on a 429. Its
observations (retriever, event sequence, answer mode, citations, corpus version, model calls) are written as
properties into the junit XML.

The engine gates run against the real ASGI app (and once over a real uvicorn socket) with the scripted fake
model: emergency template latency while every model hangs 2 s and fails, upstream stream closed after a client
disconnect, and admission slots after 1,000 cancelled turns.

Manual smoke against a running server (Git Bash):

```sh
TOKEN=$(curl -s -X POST localhost:8000/api/v1/session -H 'content-type: application/json' \
  -d '{"locale":"en"}' | python -c "import json,sys; print(json.load(sys.stdin)['session_token'])")
curl -N -X POST localhost:8000/api/v1/chat -H "authorization: Bearer $TOKEN" \
  -H 'accept: text/event-stream' -H 'content-type: application/json' \
  -d "{\"message\":\"What are the visiting hours?\",\"locale\":\"en\",\"client_turn_id\":\"$(python -c 'import uuid; print(uuid.uuid4())')\"}"
```

A well-formed stream starts with `event: meta`, carries any `safety` event right after it, and ends with
exactly one `answer` (or `error`) followed by `done`. `evals/fakes/sse_contract.order_violations()` checks this.
