"""Load-test server: the real API (app.main.create_app) on a latency-realistic scripted fake LLM and the fake
retriever. No model weights, no Qdrant, no network.

  AUSCULTA_LLM_BACKEND=fake AUSCULTA_EMBED_BACKEND=fake \
      uvicorn evals.load.server:create_load_app --factory --host 127.0.0.1 --port 8765

The fake model's latency follows ADR 0001 (docs/decisions/0001-model-selection.md): streamed answers have a
time to first token of about 0.9 s and then one chunk every ~40 ms; Decisions API calls (guard, verify) take
about 1.1 s; plain generations (query rewrite) about 0.9 s. Every latency is drawn from a log-normal
distribution around that median (seeded, AUSCULTA_LOAD_SEED).

A pure-ASGI timing wrapper records, per HTTP request: wall time from the first ASGI call to the last body
byte, and the fake model's own time inside it (a context variable that every fake model call adds its sleeps
to; the turn's engine task inherits it). app-added latency = wall - requested model time (an upper bound: it
still holds the asyncio timer overshoot of each model sleep, 1-16 ms on Windows); wall - measured sleeps is
the lower bound (Sample.as_dict). Samples go to the JSONL file named by AUSCULTA_LOAD_SAMPLES, so they do not
grow the measured process. Extra routes exist ONLY in this harness: GET /__load/calibrate,
GET /__load/stats?since=N (the samples), GET /__load/rss (resident memory of this process), GET /__load/state
(store sizes, CPU time; ?gc=1 adds object counts), GET /__load/lag?since=T (event-loop lag, probe only) and
GET /__load/heap?op=mark|diff (tracemalloc snapshot diff, AUSCULTA_LOAD_TRACEMALLOC=<frames> only).

Diagnostics (evals/load/probe.py): AUSCULTA_LOAD_PROBE=1 adds per-request phase marks to the samples and runs
an event-loop lag monitor. A request may carry `X-Load-Req: <id>`; the id is copied into its sample so client
and server timings of the same request can be joined.

The fake retriever keeps no call log here (FakeRetriever.calls would hold every RetrievalQuery of the run:
~16,500 pydantic objects, ~25 MB, after a 30-minute soak; P5 soak finding).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import math
import os
import random
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from app.main import create_app
from core.config import Settings
from core.models import ModelRole
from core.ports import (
    DecisionQuestion,
    DecisionResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
)
from evals.fakes.fake_llm import FakeLLMProvider
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.scripted import scripted_provider
from evals.load.probe import (
    _MARKS,
    LagMonitor,
    heap_diff,
    heap_mark,
    inline_precheck_if_asked,
    install_probes,
    phases_ms,
    probe_enabled,
    process_counters,
    start_tracemalloc,
    store_sizes,
)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

STATS_PATH = "/__load/stats"
RSS_PATH = "/__load/rss"
CALIBRATE_PATH = "/__load/calibrate"
STATE_PATH = "/__load/state"
LAG_PATH = "/__load/lag"
HEAP_PATH = "/__load/heap"
HARNESS_PATHS = (STATS_PATH, RSS_PATH, CALIBRATE_PATH, STATE_PATH, LAG_PATH, HEAP_PATH)
REQ_HEADER = b"x-load-req"
SAMPLES_ENV = "AUSCULTA_LOAD_SAMPLES"  # JSONL file for the samples (kept out of the measured process' memory)
MAX_SAMPLES = 500_000
CALIBRATION_SLEEPS = 60
CALIBRATION_SLEEP_S = 0.04
# [requested seconds, measured seconds, number of sleeps] of the fake model inside the current request
_MODEL_TIME: contextvars.ContextVar[list[float] | None] = contextvars.ContextVar("model_time", default=None)


@dataclass(frozen=True)
class LatencyProfile:
    """Medians (seconds) of the fake model's latencies and the log-normal spread around them."""

    ttft_s: float = 0.9
    chunk_s: float = 0.04
    decide_s: float = 1.1
    generate_s: float = 0.9
    sigma: float = 0.25  # p95 ~ 1.5 x median
    chunk_sigma: float = 0.3

    def draw(self, rng: random.Random, median: float, sigma: float | None = None) -> float:
        return median * math.exp(rng.gauss(0.0, self.sigma if sigma is None else sigma))


async def model_sleep(seconds: float) -> None:
    """Sleep like a model would, and book the time to the current request."""
    t0 = time.perf_counter()
    await asyncio.sleep(seconds)
    acc = _MODEL_TIME.get()
    if acc is not None:
        acc[0] += seconds
        acc[1] += time.perf_counter() - t0
        acc[2] += 1


@dataclass
class RealisticFakeLLM:
    """core.ports.LLMProvider: a scripted FakeLLMProvider (instant) plus realistic, recorded latencies."""

    inner: FakeLLMProvider
    profile: LatencyProfile = field(default_factory=LatencyProfile)
    rng: random.Random = field(default_factory=lambda: random.Random(0))
    chunk_chars: int = 24

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        await model_sleep(self.profile.draw(self.rng, self.profile.generate_s))
        return await self.inner.generate(request)

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        await model_sleep(self.profile.draw(self.rng, self.profile.ttft_s))
        first = True
        async with aclosing(self.inner.stream(request)) as chunks:  # type: ignore[type-var]
            async for chunk in chunks:
                if not first:
                    await model_sleep(
                        self.profile.draw(self.rng, self.profile.chunk_s, self.profile.chunk_sigma)
                    )
                first = False
                yield chunk

    async def decide(
        self, role: ModelRole, input_text: str, questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        await model_sleep(self.profile.draw(self.rng, self.profile.decide_s))
        return await self.inner.decide(role, input_text, questions)

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        return await self.inner.embed(texts, dim=dim)


@dataclass
class Sample:
    method: str
    path: str
    status: int
    started: float  # time.time() at the first ASGI call
    wall_ms: float
    model_ms: float  # what the fake model asked to sleep
    measured_model_ms: float  # what those sleeps really took (timer granularity + event-loop delay)
    sleeps: int
    first_event_ms: float | None  # first SSE "delta" / "answer" / "safety" frame, if any
    marks: dict[str, float] | None = None  # probe marks, ms since the first ASGI call
    req: str | None = None  # X-Load-Req of the request

    def as_dict(self, overshoot_ms: float) -> dict[str, Any]:
        """app_ms_uncorrected = wall - requested model time: an UPPER bound of the app's own time (it still
        contains the asyncio timer overshoot of every model sleep, ~1-16 ms each on Windows).
        app_ms_lower = wall - measured model sleeps: a LOWER bound (event-loop lag at wake-up is booked to
        the model). app_ms = wall - requested - sleeps x idle overshoot (calibrated once; unreliable when the
        Windows timer resolution changes during the run)."""
        return {
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "started": round(self.started, 3),
            "wall_ms": round(self.wall_ms, 2),
            "model_ms": round(self.model_ms, 2),
            "measured_model_ms": round(self.measured_model_ms, 2),
            "sleeps": self.sleeps,
            "app_ms": round(self.wall_ms - self.model_ms - self.sleeps * overshoot_ms, 2),
            "app_ms_uncorrected": round(self.wall_ms - self.model_ms, 2),
            "app_ms_lower": round(self.wall_ms - self.measured_model_ms, 2),
            "first_event_ms": None if self.first_event_ms is None else round(self.first_event_ms, 2),
            **({"req": self.req} if self.req else {}),
            **({"phases": phases_ms(self.marks)} if self.marks is not None else {}),
        }


_FIRST_EVENTS = (b"event: delta", b"event: answer", b"event: safety")


def rss_bytes() -> int:
    import psutil

    return int(psutil.Process(os.getpid()).memory_info().rss)


def _query(scope: Scope) -> dict[str, str]:
    raw = scope.get("query_string", b"").decode()
    return dict(part.split("=", 1) for part in raw.split("&") if "=" in part)


def _req_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name == REQ_HEADER:
            return bytes(value).decode("ascii", errors="replace")[:64]
    return None


class TimingMiddleware:
    """Outermost ASGI wrapper: per-request wall time and fake-model time, plus the harness routes."""

    def __init__(
        self, app: ASGIApp, *, container: Any = None, samples_path: str | None = None, probe: bool = False
    ) -> None:
        self.app = app
        self.container = container
        self.samples: list[Sample] = []  # only without samples_path (tests)
        self.count = 0
        self.overshoot_ms = 0.0
        self.probe = probe
        self.lag = LagMonitor()
        self._heap_base: Any = None
        self._file = open(samples_path, "a", encoding="utf-8", buffering=1 << 16) if samples_path else None  # noqa: SIM115

    def _record(self, sample: Sample) -> None:
        self.count += 1
        if self._file is not None:
            self._file.write(json.dumps(sample.as_dict(self.overshoot_ms)) + "\n")
        elif len(self.samples) < MAX_SAMPLES:
            self.samples.append(sample)

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if path in HARNESS_PATHS:
            await self._harness(scope, send, path)
            return
        acc = [0.0, 0.0, 0.0]
        token = _MODEL_TIME.set(acc)
        marks: dict[str, float] | None = None
        if self.probe:
            self.lag.ensure_started()
            marks = {}
        marks_token = _MARKS.set(marks)
        t0 = time.perf_counter()
        started = time.time()
        status = 0
        first_event: float | None = None
        end: float | None = None

        async def timed_send(message: Message) -> None:
            nonlocal status, first_event, end
            if message["type"] == "http.response.start":
                status = int(message["status"])
                if marks is not None:
                    marks.setdefault("response_start", time.perf_counter())
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if first_event is None and any(e in body for e in _FIRST_EVENTS):
                    first_event = time.perf_counter()
                if not message.get("more_body", False):
                    end = time.perf_counter()
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            _MODEL_TIME.reset(token)
            _MARKS.reset(marks_token)
            stop = end if end is not None else time.perf_counter()
            if marks is not None:
                marks = {k: (v - t0) * 1000 for k, v in {**marks, "t0": t0, "end": stop}.items()}
            self._record(
                Sample(
                    method=str(scope.get("method", "")),
                    path=path,
                    status=status,
                    started=started,
                    wall_ms=(stop - t0) * 1000,
                    model_ms=acc[0] * 1000,
                    measured_model_ms=acc[1] * 1000,
                    sleeps=int(acc[2]),
                    first_event_ms=None if first_event is None else (first_event - t0) * 1000,
                    marks=marks,
                    req=_req_id(scope),
                )
            )

    async def _harness(self, scope: Scope, send: Send, path: str) -> None:
        if path == RSS_PATH:
            payload: Any = {"rss_bytes": rss_bytes(), "pid": os.getpid(), "samples": self.count}
        elif path == STATE_PATH:
            self.flush()
            payload = self.state(with_gc=b"gc=1" in scope.get("query_string", b""))
        elif path == CALIBRATE_PATH:
            self.overshoot_ms = await idle_overshoot_ms()
            payload = {"overshoot_ms": self.overshoot_ms}
        elif path == LAG_PATH:
            since_t = float(_query(scope).get("since", "0") or 0)
            payload = {"interval_s": self.lag.interval_s, "lags": self.lag.since(since_t)}
        elif path == HEAP_PATH:
            payload = self._heap(_query(scope).get("op", "diff"))
        else:
            since = int(_query(scope).get("since", "0") or 0)
            rows = [s.as_dict(self.overshoot_ms) for s in self.samples[since:]]
            payload = {"next": len(self.samples), "overshoot_ms": self.overshoot_ms, "samples": rows}
        body = json.dumps(payload).encode("utf-8")
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _heap(self, op: str) -> dict[str, Any]:
        if op == "mark":
            self._heap_base = heap_mark()
            return {"marked": self._heap_base is not None}
        return heap_diff(self._heap_base)

    def state(self, *, with_gc: bool) -> dict[str, Any]:
        """Sizes of the in-process stores (memory backends), CPU time and, on request, object counts."""
        out: dict[str, Any] = {"samples": self.count, "rss_bytes": rss_bytes(), **process_counters()}
        if self.container is not None:
            out.update(store_sizes(self.container))
        if with_gc:
            import gc
            from collections import Counter

            gc.collect()
            counts = Counter(type(o).__name__ for o in gc.get_objects())
            out["gc_objects"] = sum(counts.values())
            out["top_types"] = dict(counts.most_common(15))
        return out


async def idle_overshoot_ms() -> float:
    """Mean extra time of an asyncio.sleep on this platform with an idle event loop (call before the load)."""
    total = 0.0
    for _ in range(CALIBRATION_SLEEPS):
        t0 = time.perf_counter()
        await asyncio.sleep(CALIBRATION_SLEEP_S)
        total += time.perf_counter() - t0 - CALIBRATION_SLEEP_S
    return total / CALIBRATION_SLEEPS * 1000


def load_llm(seed: int | None = None) -> RealisticFakeLLM:
    """The fake model of the load server. Its call log keeps nothing: FakeLLMProvider.calls holds one tuple
    per model call (~4 per turn, ~100,000 in a 40-minute soak; P5 soak finding, tracemalloc fake_llm.py:82,
    :116)."""
    seed = int(os.environ.get("AUSCULTA_LOAD_SEED", "0")) if seed is None else seed
    inner = scripted_provider()
    inner.calls = _NoCallLog()
    return RealisticFakeLLM(inner=inner, rng=random.Random(seed))


def precise_timers() -> None:
    """Windows only: 1 ms timer resolution for this process (timeBeginPeriod), so the fake model's sleeps
    overshoot by ~1 ms instead of up to 15.6 ms, like on the Linux servers the app runs on."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(1)


class _NoCallLog(list[Any]):
    """A call log (FakeRetriever, FakeLLMProvider) that keeps nothing: the load server must not grow with
    every turn."""

    def append(self, item: Any) -> None:
        return None


def load_retriever() -> FakeRetriever:
    return FakeRetriever(calls=_NoCallLog())


def create_load_app() -> TimingMiddleware:
    """uvicorn factory. Settings come from the environment; the fake backends are required."""
    precise_timers()
    start_tracemalloc()
    settings = Settings()
    if settings.llm_backend != "fake" or settings.embed_backend != "fake":
        raise RuntimeError("the load server needs AUSCULTA_LLM_BACKEND=fake and AUSCULTA_EMBED_BACKEND=fake")
    from app.api.container import Overrides

    app = create_app(settings, overrides=Overrides(llm=load_llm(), retriever=load_retriever()))
    container = app.state.container
    probe = probe_enabled()
    if probe:
        install_probes(container)
    inline_precheck_if_asked()
    return TimingMiddleware(
        app,  # type: ignore[arg-type]
        container=container,
        samples_path=os.environ.get(SAMPLES_ENV),
        probe=probe,
    )
