"""Load-test server: the real API (app.main.create_app) on a latency-realistic scripted fake LLM and the fake
retriever. No model weights, no Qdrant, no network.

  AUSCULTA_LLM_BACKEND=fake AUSCULTA_EMBED_BACKEND=fake \
      uvicorn evals.load.server:create_load_app --factory --host 127.0.0.1 --port 8765

The fake model's latency follows ADR 0001 (docs/decisions/0001-model-selection.md): streamed answers have a
time to first token of about 0.9 s and then one chunk every ~40 ms; Decisions API calls (guard, verify) take
about 1.1 s; plain generations (query rewrite) about 0.9 s. Every latency is drawn from a log-normal
distribution around that median (seeded, AUSCULTA_LOAD_SEED).

A pure-ASGI timing wrapper records, per HTTP request: wall time from the first ASGI call to the last body byte,
and the fake model's own time inside it (a context variable that every fake model call adds its sleeps to; the
turn's engine task inherits it). app-added latency = wall - model time - (number of model sleeps x the idle
asyncio timer overshoot, measured once by GET /__load/calibrate before the load: ~7 ms per sleep on Windows,
a platform constant, not app work). Extra routes exist ONLY in this harness: GET /__load/calibrate,
GET /__load/stats?since=N (the samples) and GET /__load/rss (resident memory of this process).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import math
import os
import random
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

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

STATS_PATH = "/__load/stats"
RSS_PATH = "/__load/rss"
CALIBRATE_PATH = "/__load/calibrate"
HARNESS_PATHS = (STATS_PATH, RSS_PATH, CALIBRATE_PATH)
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

    def as_dict(self, overshoot_ms: float) -> dict[str, Any]:
        """app_ms = wall - model time - sleeps x the IDLE timer overshoot (a platform constant: ~7 ms per
        asyncio.sleep on Windows). Event-loop delay caused by load stays in app_ms."""
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
            "first_event_ms": None if self.first_event_ms is None else round(self.first_event_ms, 2),
        }


_FIRST_EVENTS = (b"event: delta", b"event: answer", b"event: safety")


def rss_bytes() -> int:
    import psutil

    return int(psutil.Process(os.getpid()).memory_info().rss)


class TimingMiddleware:
    """Outermost ASGI wrapper: per-request wall time and fake-model time, plus the two harness routes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.samples: list[Sample] = []
        self.overshoot_ms = 0.0

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
        t0 = time.perf_counter()
        started = time.time()
        status = 0
        first_event: float | None = None
        end: float | None = None

        async def timed_send(message: Message) -> None:
            nonlocal status, first_event, end
            if message["type"] == "http.response.start":
                status = int(message["status"])
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
            stop = end if end is not None else time.perf_counter()
            if len(self.samples) < MAX_SAMPLES:
                self.samples.append(
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
                    )
                )

    async def _harness(self, scope: Scope, send: Send, path: str) -> None:
        if path == RSS_PATH:
            payload: Any = {"rss_bytes": rss_bytes(), "pid": os.getpid(), "samples": len(self.samples)}
        elif path == CALIBRATE_PATH:
            self.overshoot_ms = await idle_overshoot_ms()
            payload = {"overshoot_ms": self.overshoot_ms}
        else:
            query = dict(
                part.split("=", 1) for part in scope.get("query_string", b"").decode().split("&") if "=" in part
            )
            since = int(query.get("since", "0") or 0)
            rows = [s.as_dict(self.overshoot_ms) for s in self.samples[since:]]
            payload = {"next": len(self.samples), "overshoot_ms": self.overshoot_ms, "samples": rows}
        body = json.dumps(payload).encode("utf-8")
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body})


async def idle_overshoot_ms() -> float:
    """Mean extra time of an asyncio.sleep on this platform with an idle event loop (call before the load)."""
    total = 0.0
    for _ in range(CALIBRATION_SLEEPS):
        t0 = time.perf_counter()
        await asyncio.sleep(CALIBRATION_SLEEP_S)
        total += time.perf_counter() - t0 - CALIBRATION_SLEEP_S
    return total / CALIBRATION_SLEEPS * 1000


def load_llm(seed: int | None = None) -> RealisticFakeLLM:
    seed = int(os.environ.get("AUSCULTA_LOAD_SEED", "0")) if seed is None else seed
    return RealisticFakeLLM(inner=scripted_provider(), rng=random.Random(seed))


def create_load_app() -> TimingMiddleware:
    """uvicorn factory. Settings come from the environment; the fake backends are required."""
    settings = Settings()
    if settings.llm_backend != "fake" or settings.embed_backend != "fake":
        raise RuntimeError("the load server needs AUSCULTA_LLM_BACKEND=fake and AUSCULTA_EMBED_BACKEND=fake")
    from app.api.container import Overrides

    app = create_app(settings, overrides=Overrides(llm=load_llm(), retriever=FakeRetriever()))
    return TimingMiddleware(app)  # type: ignore[arg-type]
