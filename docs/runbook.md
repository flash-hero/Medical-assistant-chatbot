# Ausculta API runbook

Operating the API (`app/`): start, check, pause, recover. The HTTP contract is `docs/contracts/api.md`; the
release gates are `evals/gates.yaml`. Nothing here needs the contents of `.env`: never paste or print it.

## 1. What runs

| Component | Dev (Windows, this machine) | Required for |
|---|---|---|
| API | `uvicorn app.main:create_app --factory` (one process) | everything |
| Qdrant 1.20.1 | native binary, `sh scripts/dev/qdrant.sh`, `http://127.0.0.1:6333`, alias `ausculta_corpus` | medical answers (`/ready` = 503 without it) |
| Relational DB | SQLite `C:/dev/ausculta-data/ausculta.db` (WAL) ; Postgres via `DATABASE_URL` in compose | sessions, turns, appointments, feedback |
| Redis | none in dev (`REDIS_URL` unset: in-memory sessions, turn gate, limits and spend meter); required in staging/prod | sessions, turn lock, replay, limits, spend shared by every worker |
| Gemini API | `GEMINI_API_KEY` from `.env` | every model-backed turn |

With `REDIS_URL` unset the session store, the turn gate (one running turn per session, per-client concurrent
turns, replay of a retried `client_turn_id`), the rate limits and the daily spend meter live in the process: a
restart forgets them, and two API processes would not share them. Run one process per host in that mode.

With `REDIS_URL` set every worker shares them (review P2/S5). Keys: `ausculta:s2:{session}` (hash, plus
`:risks` set and `:history` list, session TTL 2 h, at most 3 redacted user turns), `ausculta:turn:lock:*`
(`SET NX EX 120`, released by compare-and-delete), `ausculta:turn:inflight:*` (per-client running turns, TTL
120 s), `ausculta:turn:replay:*` (SSE frames of a completed turn, at most 64 KiB, TTL 10 min, answer text only,
never the user's message), `ausculta:spend:*` and the `LIMITS*` keys of the rate limiter. Redis runs with
`noeviction`: alert at 70 % of `maxmemory` (`used_memory`), because a full Redis turns every request into
`503 dependency_unavailable`. Admission control (`AUSCULTA_LLM_CONCURRENCY`) stays per process: the global
model concurrency is workers x that value.

## 2. Start and stop (dev)

```sh
# 1. Qdrant (skip if http://127.0.0.1:6333 answers)
sh scripts/dev/qdrant.sh            # run in the background; storage under C:/dev/ausculta-data/qdrant

# 2. API on 127.0.0.1:8000 (reads .env; AUSCULTA_ENV=dev exposes /api/v1/docs)
.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Offline / no-quota mode: `AUSCULTA_LLM_BACKEND=fake` uses the scripted fake model and synthetic passages (no
API call, no Qdrant). Use it for UI work and demos of the flow, never for content review.

Startup does, in order: create the schema (SQLite or dev/test only), warm the safety precheck (lexicons,
regex caches, thread pool) so the first emergency turn is not slower than later ones, warm the retriever (BM25
analysers and the local query-embedding model; a failure is logged as `retriever_warmup_failed` and only makes
the first answer slower), then start the retention purge task (section 7) and the corpus check: the
collection behind `QDRANT_ALIAS` is verified against its signed manifest (`rag.verify.verify_live_corpus`:
checksums, point ids, count, HMAC, embedding model). Until it passes, medical questions get the "temporarily
unavailable" template and `/ready` reports `"retriever": false`; emergency, self-harm and front-desk turns
work from the first second. Logs: `corpus_verified` (collection, corpus_version, chunks) or
`corpus_unverified` (reason). A failed check is final for that process: fix the collection (`rag rollback`
to the last good one) and restart. Stop with Ctrl+C: in-flight turns
are cancelled, upstream model streams are closed, the purge task stops, the DB pool, HTTP clients and the Redis
client are released.

A demo hospital profile (`is_demo: true`) is only served with `AUSCULTA_DEMO_MODE=true` (in any
environment; the UI then shows the demo banner). Without demo mode it is refused at startup (log
`hospital_profile_demo_refused`, error level) and the API runs without a profile (section 6.4), so fictional
phone numbers are never presented as real ones.

`AUSCULTA_SESSION_SECRET` (>= 32 chars) is required in staging/prod. Without it (dev/test only) a random
secret is generated and every session token becomes invalid on restart (log event `session_secret_ephemeral`).

## 2b. Production stack (Docker Compose)

Services (`deploy/compose.yaml`): `caddy` (the only published port, TLS for `SITE_ADDRESS`), `web` (Next.js),
`api` (FastAPI, one uvicorn worker, embedding model baked into the image), `migrate` (one-shot
`alembic upgrade head`; the API waits for it to complete), `qdrant`, `postgres`, `redis` (internal network only).
Secrets and passwords live in `deploy/.env.prod` (gitignored; never commit or print it).

```sh
# from the repo root; Git Bash on Windows needs MSYS_NO_PATHCONV=1 for container paths
C="docker compose -f deploy/compose.yaml --env-file deploy/.env.prod"
$C build                 # api image: deps from deploy/requirements.lock (hash-pinned), model download cached
$C up -d --wait          # migrate runs first; api, web, qdrant, postgres, redis report healthy
$C ps -a                 # migrate: exited (0); everything else: running (healthy)
$C down                  # stop (volumes kept: api_data, qdrant, postgres, redis)
```

First start, and every new corpus version: the stack's Qdrant starts empty, so the API reports
`corpus_unverified` and medical questions get the "temporarily unavailable" template (emergency, crisis and
front-desk turns work). Build, evaluate and promote the corpus on the build machine (`python -m rag build`,
`rag eval`, `rag promote`), then load it into the stack:

```sh
.venv/Scripts/python.exe deploy/load_corpus.py ausculta_corpus_2026_11_20_en2
```

It snapshots the collection from the build machine's Qdrant, recovers it in the stack, switches the
`ausculta_corpus` alias, copies the signed manifest, retrieval config and `active.json` into the API volume
(`/data/manifests`), restarts the API and fails unless the API logs `corpus_verified` for that collection.
The previous collection stays in the stack; to roll back, run the script again with it (its manifest,
retrieval config and an `active.json` naming it must be in `manifests/`, e.g. after `python -m rag rollback`).

Code or template changes: `$C build api && $C up -d` (the model download layer is reused; the `api_data`
volume keeps the model, BM25 files and manifests across rebuilds). Schema changes ship as Alembic migrations in
`app/storage/migrations/versions/`; `migrate` applies them on the next `up`.

Smoke test through Caddy: `POST http://localhost/api/v1/session` then `POST /api/v1/chat` (section 8, with
port 80 instead of 8000). `/api/v1/ready` and `/api/v1/meta` answer 404 through Caddy by design (internal
checks only): use `$C exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready').read())"`.

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

While paused every model `POST /chat` gets `503 service_paused` with `Retry-After: 300` and the localised
text "The assistant is paused for maintenance. In an emergency, call your local emergency number." Messages
that the deterministic precheck classifies as an emergency or self-harm are NOT paused: they are answered from
the safety templates with no model call (review C9). `/hospital`, sessions, appointment requests, feedback and
the ops endpoints stay up. Confirm with `/ready` (`"paused": true`).

When to pull it: unsafe or wrong answers reported (feedback `reason=unsafe`), a prompt-injection campaign, a
data or licence problem in the corpus, an API key leak, or spend running away.

## 5. Cost and load limits

| Limit | Setting (default) | Client sees |
|---|---|---|
| Daily spend cap (UTC day) | `AUSCULTA_DAILY_SPEND_CAP_USD` (5.0) | model-backed turns `503 service_paused`, `Retry-After` = seconds to 00:00 UTC |
| Requests per client / minute | `AUSCULTA_RATE_IP_MIN` (20) | `429 rate_limited` + `Retry-After` |
| Sessions created per client / minute | half of `AUSCULTA_RATE_IP_MIN` (10) | `429 rate_limited` |
| Sessions created, all clients / minute | `app/limits/rate.py` `SESSION_CREATE_GLOBAL_PER_MIN` (300) | `429 rate_limited` |
| Requests per session / minute | `AUSCULTA_RATE_SESSION_MIN` (10) | `429 rate_limited` |
| Turns per session (2 h token) | `AUSCULTA_MAX_TURNS` (20) | `429 session_exhausted` |
| Running model turns per client | `app/api/gate.py` `IP_CONCURRENT_TURNS` (2) | `429 rate_limited` + `Retry-After: 5` |
| Per-turn deadline | `app/pipeline/engine.py` `TURN_DEADLINE_S` (45 s) | the "busy" template (turn degraded `deadline`) |
| Concurrent model-backed turns | `AUSCULTA_LLM_CONCURRENCY` (8, per process) | waits in the queue |
| Queue length / max wait | `AUSCULTA_QUEUE_MAX` (32) / `AUSCULTA_QUEUE_WAIT_S` (5) | `503 overloaded` + `Retry-After` |
| One running turn per session | fixed | `409 turn_in_progress` |
| Appointment requests | 3 per session, 10 per client per day, 500 per day in total (`app/limits/rate.py`) | `429 rate_limited` |
| Feedback | 40 per session, 200 per client per day, 5,000 per day in total | `429 rate_limited` |
| Safety turns (emergency / self-harm) | 60 per client / minute, separate bucket | `429 rate_limited` |
| Message length | `AUSCULTA_MAX_MESSAGE_CHARS` (2000) | `422 invalid_input` |
| Request body | 32 KiB | `413 payload_too_large` |

A "client" is an IPv4 address, or an IPv6 /64 (one subscriber usually holds a whole /64; IPv4-mapped IPv6 is
the IPv4 address). The caps without a Settings field are code constants for now. Add the edge limit too:
Caddy `rate_limit` per remote IP on `/api/v1/session` and `/api/v1/chat`, so floods are dropped before Python.

Emergency and self-harm turns detected by the deterministic precheck call no model. The precheck runs before
every limit (review C9): those turns skip the kill switch, the ordinary rate limits, the turn budget, the
one-turn-per-session lock, the per-client concurrency cap, the spend cap and the admission queue, and are
answered from templates even when every model is down or the queue is full (gate
`engine.emergency_latency_ms`). Their only limit is the separate safety bucket above. Behind a reverse proxy set `AUSCULTA_TRUSTED_PROXY_COUNT` to the
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

### 6.5 Database or Redis unavailable
`/ready` reports `"database": false` (or `"sessions"` / `"rate_limiter": false` for Redis). Requests that need
the missing store get `503 dependency_unavailable` with `Retry-After` (log `dependency_failed`), never a 500;
that includes safety turns, because the session cannot be loaded: the web page keeps the emergency number
from `/hospital` on screen. For SQLite check disk space and that no other process holds `ausculta.db` open for
writing; restart the API. For Redis check `maxmemory` (noeviction) and the connection; the API reconnects by
itself.

### 6.6 Abuse from one client
Lower `AUSCULTA_RATE_IP_MIN` and restart, block at the proxy (a whole IPv6 /64), or pull the kill switch.
Logs carry the session id and error codes, never message text.

### 6.7 Suspected key leak
Kill switch on, rotate the key in Google AI Studio, update `.env` (never commit it), restart, kill switch off.

## 7. Data and privacy
- Chat messages are never logged. Logs are structured (JSON outside dev/test) and carry ids, codes and timings.
- Appointment requests are never sent to the model and are stored for staff with a 30-day retention. Each
  request and its audit event are written in one transaction; a request-code collision is retried.
- Retention (review S6/P7), applied by a purge task that runs at startup and then every hour in every worker
  (idempotent; log `retention_purged` with per-table counts, `retention_purge_failed` on error):
  appointment requests and contacts 30 days, sessions and turn records 90 days, feedback 180 days, audit
  events 365 days (`app/storage/repositories.py` `RETENTION`; engineering defaults, to be confirmed by the
  DPIA).
- Redis holds at most the last 3 redacted user turns of a session, for the 2-hour session lifetime.
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
