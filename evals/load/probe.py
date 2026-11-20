"""Diagnostics for the load server (harness only, never imported by the app).

Phase marks (AUSCULTA_LOAD_PROBE=1): wrappers around the objects the chat route calls, installed on the load
server's own container, stamp `time.perf_counter()` into a per-request dict (a context variable set by
TimingMiddleware; anyio's worker threads run in a copy of the context, so the precheck's marks land in the
same dict). A rejected (503) chat request is cut into these phases:

  pre_handler     first ASGI call -> route handler entry (middleware, body receive, validation)
  ingress         token check + ingress sanitiser (event loop)
  thread_dispatch handing the precheck to a worker thread (capacity limiter, thread wake-up)
  precheck        the deterministic precheck itself (worker thread, GIL shared with the event loop)
  loop_resume     precheck done -> handler running again on the event loop
  checks          kill switch, rate limits, session load, replay, turn gate, spend cap
  admission       admission.acquire (queue wait; 0 when the queue is full and the request is refused)
  error_response  exception -> 503 response start (error handler, log line, JSON body)
  send            response start -> last body byte

LagMonitor: every LAG_INTERVAL_S a helper thread posts a callback to the loop (`call_soon_threadsafe`, which
wakes the loop like a socket event or a finished worker thread does) and records how long it waited to run:
the delay an arriving request or a returning precheck waits for the event loop (and the GIL). Neither timer
lateness (asyncio's timers on Windows follow a 15.6 ms monotonic clock and often fire early) nor a
`call_soon` from a task (it runs first in the next iteration) shows that delay.
Heap: tracemalloc snapshot diffs (AUSCULTA_LOAD_TRACEMALLOC=<frames>).
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import threading
import time
import tracemalloc
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from typing import Any

PROBE_ENV = "AUSCULTA_LOAD_PROBE"
TRACEMALLOC_ENV = "AUSCULTA_LOAD_TRACEMALLOC"
INLINE_PRECHECK_ENV = "AUSCULTA_LOAD_INLINE_PRECHECK"  # experiment: precheck on the event loop, no thread
LAG_INTERVAL_S = 0.01
LAG_MAX = 200_000  # 100 Hz: ~33 min of history
HEAP_TOP = 40
PHASES: tuple[tuple[str, str, str], ...] = (
    ("pre_handler", "t0", "handler"),
    ("ingress", "handler", "ingress_done"),
    ("thread_dispatch", "ingress_done", "precheck_start"),
    ("precheck", "precheck_start", "precheck_end"),
    ("loop_resume", "precheck_end", "checks"),
    ("checks", "checks", "admission"),
    ("admission", "admission", "admission_exit"),
    ("error_response", "admission_exit", "response_start"),
    ("send", "response_start", "end"),
)

_MARKS: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar("load_marks", default=None)


def probe_enabled() -> bool:
    return os.environ.get(PROBE_ENV, "") == "1"


class _InlineToThread:
    @staticmethod
    async def run_sync(func: Callable[..., Any], *args: Any) -> Any:
        return func(*args)


class _InlineAnyio:
    to_thread = _InlineToThread


def inline_precheck_if_asked() -> bool:
    """Experiment (AUSCULTA_LOAD_INLINE_PRECHECK=1): the chat route runs the precheck on the event loop, not
    in an anyio worker thread (only routes_chat's own `anyio` name is replaced). Returns whether it did."""
    if os.environ.get(INLINE_PRECHECK_ENV, "") != "1":
        return False
    from app.api import routes_chat

    setattr(routes_chat, "anyio", _InlineAnyio)  # noqa: B010 - the module's own binding, harness only
    return True


def mark(name: str) -> None:
    """Stamp `name` into the current request's marks (first stamp wins; no-op outside a probed request)."""
    marks = _MARKS.get()
    if marks is not None and name not in marks:
        marks[name] = time.perf_counter()


def phases_ms(marks: dict[str, float]) -> dict[str, float]:
    """Durations (ms) of the PHASES whose two marks are both present; marks are ms since t0."""
    out: dict[str, float] = {}
    for name, start, stop in PHASES:
        if start in marks and stop in marks:
            out[name] = round(marks[stop] - marks[start], 3)
    return out


def install_probes(container: Any) -> None:
    """Wrap the chat route's collaborators on THIS container (instance attributes shadow the methods)."""
    from app.api import routes_chat

    signer, engine, rate, admission = container.signer, container.engine, container.rate, container.admission
    verify, precheck, check_ip, acquire = signer.verify, engine.precheck, rate.check_ip, admission.acquire
    ingress_name = "process_ingress"  # the route's own binding of app.guardrails.ingress.process_ingress
    ingress = getattr(routes_chat, ingress_name)

    def timed_verify(token: str) -> Any:
        mark("handler")
        return verify(token)

    def timed_ingress(*args: Any, **kwargs: Any) -> Any:
        out = ingress(*args, **kwargs)
        mark("ingress_done")
        return out

    def timed_precheck(message: Any) -> Any:
        mark("precheck_start")
        try:
            return precheck(message)
        finally:
            mark("precheck_end")

    async def timed_check_ip(ip: str) -> None:
        mark("checks")
        await check_ip(ip)

    async def timed_acquire() -> None:
        mark("admission")
        try:
            await acquire()
        finally:
            mark("admission_exit")

    signer.verify = timed_verify
    engine.precheck = timed_precheck
    rate.check_ip = timed_check_ip
    admission.acquire = timed_acquire
    setattr(routes_chat, ingress_name, timed_ingress)


class LagMonitor:
    """Event-loop delay seen from outside the loop (see the module docstring), as (unix time, ms)."""

    def __init__(self, interval_s: float = LAG_INTERVAL_S, maxlen: int = LAG_MAX) -> None:
        self.interval_s = interval_s
        self.lags: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def ensure_started(self) -> None:
        if self._thread is None:
            loop = asyncio.get_running_loop()
            self._thread = threading.Thread(
                target=self._run, args=(loop,), name="load-lag-monitor", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                loop.call_soon_threadsafe(self._hop_done, time.perf_counter())
            except RuntimeError:  # the loop is closed
                return

    def _hop_done(self, t0: float) -> None:
        self.lags.append((time.time(), (time.perf_counter() - t0) * 1000))

    def since(self, t: float) -> list[tuple[float, float]]:
        return [(ts, lag) for ts, lag in self.lags if ts >= t]


def _size(obj: Any, attr: str) -> int | None:
    held = getattr(obj, attr, None)
    return None if held is None else len(held)


def store_sizes(container: Any) -> dict[str, Any]:
    """Entries held by every in-process store of the container (memory backends; None when not present)."""
    c = container
    storage = getattr(c.rate, "_storage", None)
    events = getattr(storage, "events", None) or {}
    out: dict[str, Any] = {
        "sessions": _size(c.sessions, "_data"),
        "replay": _size(c.registry, "_done"),
        "turn_owner": _size(c.registry, "_turn_owner"),
        "gate_locks": _size(c.registry, "_locks"),
        "gate_active": _size(c.registry, "_active"),
        "idempotency": _size(c.idempotency, "_data"),
        "rate_keys_moving": len(events),
        "rate_entries_moving": sum(len(v) for v in events.values()),
        "rate_keys_fixed": _size(storage, "storage"),
        "rate_locks": _size(storage, "locks"),
        "retriever_calls": _size(c.retriever, "calls"),
        "admission_held": c.admission.held,
        "admission_waiting": c.admission.waiting,
    }
    return out


def process_counters() -> dict[str, Any]:
    import psutil

    proc = psutil.Process(os.getpid())
    cpu = proc.cpu_times()
    return {
        "cpu_s": round(cpu.user + cpu.system, 3),
        "threads": proc.num_threads(),
        "wall": round(time.time(), 3),
    }


# ---- tracemalloc ---------------------------------------------------------------------------------
_IGNORED = (tracemalloc.__file__, "<frozen importlib._bootstrap>", "<frozen importlib._bootstrap_external>")


def start_tracemalloc() -> int:
    frames = int(os.environ.get(TRACEMALLOC_ENV, "0") or 0)
    if frames > 0 and not tracemalloc.is_tracing():
        tracemalloc.start(frames)
    return frames


def _snapshot() -> tracemalloc.Snapshot:
    snap = tracemalloc.take_snapshot()
    return snap.filter_traces([tracemalloc.Filter(False, f) for f in _IGNORED])


def heap_mark() -> tracemalloc.Snapshot | None:
    return _snapshot() if tracemalloc.is_tracing() else None


def heap_diff(base: tracemalloc.Snapshot | None, top: int = HEAP_TOP) -> dict[str, Any]:
    """Top allocation sites by growth since `base`, grouped by line and by full traceback."""
    if base is None or not tracemalloc.is_tracing():
        return {"error": "tracemalloc off or no baseline (GET /__load/heap?op=mark first)"}
    now = _snapshot()
    current, peak = tracemalloc.get_traced_memory()
    return {
        "traced_mb": round(current / 2**20, 2),
        "traced_peak_mb": round(peak / 2**20, 2),
        "growth_mb": round(
            (
                sum(s.size for s in now.statistics("filename"))
                - sum(s.size for s in base.statistics("filename"))
            )
            / 2**20,
            3,
        ),
        "by_line": _stats(now.compare_to(base, "lineno")[:top]),
        "by_traceback": _stats(now.compare_to(base, "traceback")[: top // 2]),
    }


def _stats(stats: Iterable[tracemalloc.StatisticDiff]) -> list[dict[str, Any]]:
    return [
        {
            "size_diff_kb": round(s.size_diff / 1024, 1),
            "count_diff": s.count_diff,
            "size_kb": round(s.size / 1024, 1),
            "trace": [f"{f.filename}:{f.lineno}" for f in s.traceback],
        }
        for s in stats
    ]


def summarize_lags(
    lags: Sequence[tuple[float, float]], pct: Callable[[Sequence[float], float], float]
) -> dict[str, float]:
    values = [lag for _, lag in lags]
    return {
        "n": float(len(values)),
        "p50_ms": pct(values, 0.5),
        "p95_ms": pct(values, 0.95),
        "p99_ms": pct(values, 0.99),
        "max_ms": max(values, default=float("nan")),
        "mean_ms": sum(values) / len(values) if values else float("nan"),
    }
