"""Locust users for the P5 load, overload and soak runs (driven by evals/load/run.py).

Each simulated user is one patient behind the reverse proxy: its own X-Forwarded-For address (the server runs
with AUSCULTA_TRUSTED_PROXY_COUNT=1), its own session (rotated every LOAD_TURNS_PER_SESSION turns, as the web
client does when a session is used up; 0 = never rotated: a fixed pool of users, one session each, for the
steady-state soak), and a realistic EN/FR/AR message mix: streamed medical answers, verify-then-release
medication answers, front-desk and appointment turns, small talk and emergencies.

Every request is also written as one JSON line to LOAD_RECORDS (the run script computes the gate metrics from
these lines, not from Locust's own statistics):
  {"t", "kind": "session"|"chat", "msg", "status", "ok", "error", "headers_ms", "total_ms", "first_event_ms",
   "retry_after", "req"}
Chat requests carry `X-Load-Req: <req>`; the load server copies it into its own sample of the request.

Environment: LOAD_RECORDS (path), LOAD_THINK_MIN / LOAD_THINK_MAX (s), LOAD_TURNS_PER_SESSION,
LOAD_MODE ("steady" | "overload"), LOAD_REJECT_WAIT_S (pause after a 503 in overload mode).
"""

from __future__ import annotations

import itertools
import json
import os
import random
import time
import uuid
from typing import Any

from locust import HttpUser, between, events, task

RECORDS_PATH = os.environ.get("LOAD_RECORDS", "load-records.jsonl")
THINK_MIN = float(os.environ.get("LOAD_THINK_MIN", "1.0"))
THINK_MAX = float(os.environ.get("LOAD_THINK_MAX", "3.0"))
TURNS_PER_SESSION = int(os.environ.get("LOAD_TURNS_PER_SESSION", "6"))
MODE = os.environ.get("LOAD_MODE", "steady")
REJECT_WAIT_S = float(os.environ.get("LOAD_REJECT_WAIT_S", "1.0"))

# (weight, kind, locale, message): synthetic messages only.
MESSAGES: tuple[tuple[int, str, str, str], ...] = (
    (30, "medical_en", "en", "What is a fever and how long does it usually last?"),
    (15, "medical_fr", "fr", "Qu'est-ce que la fièvre et combien de temps dure-t-elle ?"),
    (15, "medical_ar", "ar", "ما هي الحمى وكم تدوم عادة؟"),
    (12, "medication_en", "en", "What does the paracetamol label say about the maximum daily amount?"),
    (10, "frontdesk_en", "en", "What are the visiting hours?"),
    (6, "appointment_en", "en", "I would like to book an appointment"),
    (6, "smalltalk_en", "en", "hello"),
    (6, "emergency_en", "en", "I have crushing chest pain spreading to my left arm and I'm sweating"),
)
_WEIGHTS = [m[0] for m in MESSAGES]
_ip_counter = itertools.count(1)
_records = open(RECORDS_PATH, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - closed on quit


@events.quitting.add_listener  # type: ignore[untyped-decorator]
def _close_records(**_: Any) -> None:
    _records.close()


def _write(record: dict[str, Any]) -> None:
    _records.write(json.dumps(record, ensure_ascii=False) + "\n")


def _ip(n: int) -> str:
    return f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}"


def _error_code(text: str) -> str:
    try:
        return str(json.loads(text)["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return "unparsed"


def _sse_problem(body: str) -> str | None:
    """None when the stream is complete and carries no error event."""
    if "event: done" not in body:
        return "no_done"
    if "event: error" in body:
        for block in body.split("\n\n"):
            if block.startswith("event: error"):
                data = block.split("data: ", 1)[-1]
                try:
                    return "error_event:" + str(json.loads(data).get("code"))
                except ValueError:
                    return "error_event:unparsed"
    if "event: meta" not in body:
        return "no_meta"
    return None


class Patient(HttpUser):
    wait_time = between(THINK_MIN, THINK_MAX)

    def on_start(self) -> None:
        self.ip = _ip(next(_ip_counter))
        self.rng = random.Random(self.ip)
        self.token: str | None = None
        self.turns = 0

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return {"X-Forwarded-For": self.ip, "Content-Type": "application/json", **(extra or {})}

    def _new_session(self, locale: str) -> bool:
        t0 = time.perf_counter()
        record: dict[str, Any] = {"t": time.time(), "kind": "session", "msg": "", "first_event_ms": None}
        try:
            with self.client.post(
                "/api/v1/session",
                json={"locale": locale},
                headers=self._headers(),
                name="session",
                catch_response=True,
            ) as resp:
                ms = (time.perf_counter() - t0) * 1000
                record.update(status=resp.status_code, headers_ms=ms, total_ms=ms)
                record["retry_after"] = resp.headers.get("Retry-After")
                if resp.status_code == 201:
                    self.token = resp.json()["session_token"]
                    self.turns = 0
                    record.update(ok=True, error=None)
                    resp.success()
                else:
                    record.update(ok=False, error=f"http_{resp.status_code}:{_error_code(resp.text)}")
                    resp.failure(record["error"])
        except Exception as exc:
            record.update(status=0, ok=False, error=f"exception:{type(exc).__name__}", headers_ms=None)
            record["total_ms"] = (time.perf_counter() - t0) * 1000
        _write(record)
        return self.token is not None and bool(record["ok"])

    @task
    def chat(self) -> None:
        _, kind, locale, message = self.rng.choices(MESSAGES, weights=_WEIGHTS)[0]
        if self.token is None or (TURNS_PER_SESSION and self.turns >= TURNS_PER_SESSION):
            self.token = None
            if not self._new_session(locale):
                return
        self.turns += 1
        payload = {"message": message, "locale": locale, "client_turn_id": str(uuid.uuid4())}
        req = uuid.uuid4().hex
        headers = self._headers(
            {"Authorization": f"Bearer {self.token}", "Accept": "text/event-stream", "X-Load-Req": req}
        )
        record: dict[str, Any] = {"t": time.time(), "kind": "chat", "msg": kind, "req": req}
        t0 = time.perf_counter()
        try:
            with self.client.post(
                "/api/v1/chat", json=payload, headers=headers, stream=True, name="chat", catch_response=True
            ) as resp:
                record["headers_ms"] = (time.perf_counter() - t0) * 1000
                record["status"] = resp.status_code
                record["retry_after"] = resp.headers.get("Retry-After")
                first_event: float | None = None
                parts: list[bytes] = []
                if resp.status_code == 200:
                    for chunk in resp.iter_content(chunk_size=None):
                        if first_event is None and any(
                            e in chunk for e in (b"event: delta", b"event: answer", b"event: safety")
                        ):
                            first_event = time.perf_counter()
                        parts.append(chunk)
                total = time.perf_counter()
                record["total_ms"] = (total - t0) * 1000
                record["first_event_ms"] = None if first_event is None else (first_event - t0) * 1000
                if resp.status_code == 200:
                    problem = _sse_problem(b"".join(parts).decode("utf-8", errors="replace"))
                else:
                    problem = f"http_{resp.status_code}:{_error_code(resp.text)}"
                record.update(ok=problem is None, error=problem)
                if problem is None:
                    resp.success()
                else:
                    resp.failure(problem)
        except Exception as exc:
            record.update(status=0, ok=False, error=f"exception:{type(exc).__name__}")
            record["total_ms"] = (time.perf_counter() - t0) * 1000
            record.setdefault("headers_ms", None)
            record.setdefault("first_event_ms", None)
            record.setdefault("retry_after", None)
        _write(record)
        if MODE == "overload" and record.get("status") == 503:
            time.sleep(REJECT_WAIT_S)  # gevent-patched: yields to the other users
        if record.get("status") in (401, 429):
            self.token = None  # session gone or used up: start a new one next time
