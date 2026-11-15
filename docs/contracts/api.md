# HTTP API contract (v1)

Base path `/api/v1`. JSON bodies, UTF-8. All errors use the envelope
`{"error": {"code": "<stable code from core/errors.py>", "message": "<localised, user-safe>", "retry_after_s": <number|null>}}`
and the matching HTTP status; 429 and 503 also set the `Retry-After` header (integer seconds).
The browser talks to the API through the web app's same-origin proxy (`/api/*` rewrite), so no CORS is needed in prod.

## Sessions

`POST /api/v1/session` body `{"locale": "en"|"fr"|"ar"}`
-> `201 {"session_token": "<opaque signed token>", "session_id": "<uuid>", "expires_at": "<ISO8601>", "turns_left": 20,
"hospital": <PublicHospital>, "demo_mode": true}`

Token: HMAC-signed, 2 h lifetime, bound to nothing personal. Sent as `Authorization: Bearer <token>`.
Rate-limited per IP (session creation is the cheapest abuse vector).

## Chat (SSE)

`POST /api/v1/chat` headers `Authorization: Bearer <token>`, `Accept: text/event-stream`
body `{"message": "<1..2000 chars>", "locale": "en"|"fr"|"ar", "client_turn_id": "<uuid, idempotency>"}`
-> `200 text/event-stream` with events defined in `core/schemas/events.py` (JSON Schema: `chat-events.schema.json`).
Pre-stream failures (invalid token, rate limit, overload, kill switch) return a normal JSON error, not a stream.
Response headers: `Cache-Control: no-store`, `X-Accel-Buffering: no`, keep-alive comment every 15 s.
Client disconnect cancels the turn and closes the upstream model stream within 1 s.

## Appointment request

`POST /api/v1/appointments` (Bearer token) body
`{"full_name", "phone", "email"?, "department_id", "preferred_dates": "<free text>", "reason"?: "<<=500 chars>", "consent": true}`
-> `201 {"request_id": "<short code>", "message": "<localised confirmation>"}`.
Never sent to the language model. Stored for staff with a 30-day retention; validated server-side.

## Feedback

`POST /api/v1/feedback` (Bearer) body `{"turn_id", "rating": "up"|"down", "reason"?: "incorrect"|"unsafe"|"unhelpful"|"other", "comment"?: "<<=500 chars>"}` -> `204`.

## Public hospital info

`GET /api/v1/hospital` -> `PublicHospital`: `{id, name, is_demo, address, main_phone, emergency, crisis_lines, handoff,
visiting_hours, departments: [{id, name, location, hours, accepts_appointments}]}` (all L10n objects resolved to the
requested `?locale=`).

## Operations

`GET /api/v1/health` (liveness, no dependencies) · `GET /api/v1/ready` (Qdrant, DB, limiter reachable; 503 if not)
`GET /api/v1/meta` -> `{"app_version", "corpus_version", "prompt_hash", "models": {...}, "demo_mode"}`
