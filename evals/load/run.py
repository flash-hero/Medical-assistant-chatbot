"""Run a P5 load scenario end to end and write the load.* gate metrics.

  python -m evals.load.run steady   --users 50  --minutes 32                    # error rate, app latency
  python -m evals.load.run soak     --users 300 --minutes 40 --warmup-min 10    # RSS growth, steady state
  python -m evals.load.run overload --users 192 --minutes 3                     # 503 + Retry-After latency
  python -m evals.load.run overload --users 192 --minutes 2 --probe --no-write  # where a 503's time goes
  python -m evals.load.run soak --minutes 12 --warmup-min 4 --tracemalloc 8 --no-write   # what grows
  python -m evals.load.run steady   --users 10  --minutes 1 --no-write           # smoke

Steps: refuse to start unless at least --min-free-gb of RAM is free; keep Windows awake for the run (a system
suspend in the middle invalidates every timing); start uvicorn on evals.load.server (fake LLM with realistic
latency, fake embeddings, fake retriever, temp SQLite, in-memory limits); run Locust headless
(evals/load/locustfile.py); sample the server's RSS and in-process store sizes every --rss-every-s seconds;
stop the server; write {data_root}/reports/load.metrics.json (records merged by metric) and a run summary
under {data_root}/reports/load/.

Scenarios:
  steady    50 users, 0.5-1.5 s think time (about 40 streams in flight at any time), a new session every 60
            turns; per-session rate limit raised to 30/min and the turn budget to 100 (the users chat faster
            than a person; rate limits are tested elsewhere), per-IP limit at its production default.
  soak      steady state: a FIXED pool of users (default 300), each keeping ONE session for the whole run
            (no session churn), 15-35 s think time (about 35-40 streams in flight, about the steady load),
            production rate limits, turn budget 100 (the most a session may have; about 80 turns per user in
            40 minutes). RSS growth is measured from the end of the warm-up (--warmup-min, default 10: the
            bounded stores, replay frames and turn owners, are full by then) to the end of the run.
  overload  3 x the 64 model-turn slots (192 users), no think time, 1 s pause after a 503; rate limits off.

Why the soak has no session churn: with the memory backends every new session stays in the session store for
its 2 h lifetime (and its rate-limit and turn-owner entries for theirs), so a soak that opens new sessions
all the time grows by design for 2 hours; the steady run (session churn) reports its RSS growth as
information only (summary.json).

Metrics (evals/gates.yaml):
  error_rate                         steady: failed requests / all requests (sessions + chat turns); an
                                     error is a non-2xx status, a transport error, or an SSE stream without
                                     `done` or with an `error` event. labels.duration_min = real duration.
  app_added_latency_p95_ms           steady: p95 over completed chat turns of server wall time (first ASGI
                                     call to last body byte) minus the fake model's requested time: an
                                     upper bound (it still holds the asyncio timer overshoot of every model
                                     sleep); the lower bound (minus the measured sleeps) is a label.
  rss_growth_30min                   soak: (RSS at the end - RSS after warm-up) / RSS after warm-up.
  overload_rejection_latency_p95_ms  overload: p95 client-observed latency of the 503 rejections (every one
                                     must carry Retry-After).
A run shorter than the gate's duration is labelled reduced_sample=true with its real duration.

Diagnostics: --probe (phase marks per request and an event-loop lag monitor, evals/load/probe.py; the overload
summary then cuts the 503s into phases and joins client and server timings by request id) and --tracemalloc N
(tracemalloc with N frames; snapshot at the end of the warm-up, diff at the end -> heap_diff.json). Both
slow the server down: never write gate metrics from such a run (use --no-write).
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import itertools
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.config import REPO_ROOT, get_settings
from evals.fakes.engine_gates import merge_records, write_metrics
from evals.load.analysis import (
    client_server_join,
    cpu_use,
    lag_summary,
    percentile,
    rejection_phases,
    store_growth,
)
from evals.load.probe import INLINE_PRECHECK_ENV, PROBE_ENV, TRACEMALLOC_ENV

SOURCE = "evals.load.run"
LOCUSTFILE = Path(__file__).resolve().parent / "locustfile.py"
GATE_MINUTES = {"error_rate": 15.0, "rss_growth_30min": 30.0}
CAPACITY: dict[str, float] = {
    "concurrency": 64,
    "queue_max": 32,
    "queue_wait_s": 5.0,
}  # defaults, see --concurrency
STEADY_LIMITS = {"AUSCULTA_RATE_SESSION_MIN": "30", "AUSCULTA_MAX_TURNS": "100"}
SOAK_LIMITS = {"AUSCULTA_MAX_TURNS": "100"}  # rate limits at their production defaults
OVERLOAD_LIMITS = {
    "AUSCULTA_RATE_IP_MIN": "1000000",
    "AUSCULTA_RATE_SESSION_MIN": "1000000",
    "AUSCULTA_MAX_TURNS": "100",
}
LIMITS = {"steady": STEADY_LIMITS, "soak": SOAK_LIMITS, "overload": OVERLOAD_LIMITS}
USERS_ENV = {
    "steady": {"LOAD_THINK_MIN": "0.5", "LOAD_THINK_MAX": "1.5", "LOAD_TURNS_PER_SESSION": "60"},
    "soak": {"LOAD_THINK_MIN": "15", "LOAD_THINK_MAX": "35", "LOAD_TURNS_PER_SESSION": "0"},
    "overload": {"LOAD_THINK_MIN": "0", "LOAD_THINK_MAX": "0", "LOAD_TURNS_PER_SESSION": "60"},
}
SOAK_MODEL = (
    "steady state: fixed pool of {users} users, one session each for the whole run (no session churn)"
)
DEFAULTS: dict[str, tuple[int, float, float]] = {  # users, minutes, warm-up minutes
    "steady": (50, 32.0, 2.0),
    "soak": (300, 40.0, 10.0),
    "overload": (192, 3.0, 0.0),
}
# At 3x the slots most requests must be refused; a run in which the server could not even take requests fast
# enough to fill the admission queue (CPU-starved host: a laptop on battery ran 53 ms of CPU per request, 5x
# the usual, and refused 2 of 3,628) does not measure the rejection path and writes no gate record.
OVERLOAD_MIN_REJECTED_SHARE = 0.25
SUSPEND_GAP_FACTOR = 4  # an RSS sampling gap this many intervals long means the machine was suspended
GB = 1024**3


class LoadRunError(RuntimeError):
    """The run could not be taken (server did not start, too little memory, Locust failed)."""


def free_ram_bytes() -> int:
    import psutil

    return int(psutil.virtual_memory().available)


@contextlib.contextmanager
def keep_awake() -> Iterator[None]:
    """Ask Windows not to suspend while the run lasts (released when the block exits; no-op elsewhere)."""
    if sys.platform != "win32":
        yield
        return
    es_continuous, es_system_required = 0x80000000, 0x00000001
    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState(es_continuous | es_system_required)
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(es_continuous)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- server --------------------------------------------------------------------------------------
def server_env(
    run_dir: Path,
    mode: str,
    capacity: dict[str, float] = CAPACITY,
    *,
    probe: bool = False,
    tracemalloc_frames: int = 0,
    inline_precheck: bool = False,
) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "QDRANT_API_KEY")
    }
    env.update(
        {
            "AUSCULTA_LLM_BACKEND": "fake",
            "AUSCULTA_EMBED_BACKEND": "fake",
            "AUSCULTA_ENV": "test",
            "AUSCULTA_DATA_ROOT": str(run_dir),
            "DATABASE_URL": f"sqlite+aiosqlite:///{(run_dir / 'load.db').as_posix()}",
            "REDIS_URL": "",
            "GEMINI_API_KEY": "",
            "AUSCULTA_SESSION_SECRET": secrets.token_urlsafe(48),
            "AUSCULTA_TRUSTED_PROXY_COUNT": "1",
            "AUSCULTA_LLM_CONCURRENCY": str(int(capacity["concurrency"])),
            "AUSCULTA_QUEUE_MAX": str(int(capacity["queue_max"])),
            "AUSCULTA_QUEUE_WAIT_S": str(capacity["queue_wait_s"]),
            "AUSCULTA_DAILY_SPEND_CAP_USD": "1000",
            "AUSCULTA_LOAD_SAMPLES": str(run_dir / "samples.jsonl"),
            "PYTHONUNBUFFERED": "1",
            PROBE_ENV: "1" if probe else "0",
            TRACEMALLOC_ENV: str(tracemalloc_frames),
            INLINE_PRECHECK_ENV: "1" if inline_precheck else "0",
            **LIMITS[mode],
        }
    )
    return env


@dataclass
class Server:
    proc: subprocess.Popen[bytes]
    base: str
    log_path: Path

    def get(self, path: str, timeout: float = 10.0) -> Any:
        return httpx.get(self.base + path, timeout=timeout).json()

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)


def start_server(
    run_dir: Path,
    mode: str,
    capacity: dict[str, float] = CAPACITY,
    *,
    probe: bool = False,
    tracemalloc_frames: int = 0,
    inline_precheck: bool = False,
) -> Server:
    port = _free_port()
    log_path = run_dir / "server.log"
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "evals.load.server:create_load_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
        "--no-access-log",
        "--timeout-keep-alive",
        "30",
    ]
    log = log_path.open("wb")
    env = server_env(
        run_dir,
        mode,
        capacity,
        probe=probe,
        tracemalloc_frames=tracemalloc_frames,
        inline_precheck=inline_precheck,
    )
    proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=log)  # noqa: S603
    server = Server(proc, f"http://127.0.0.1:{port}", log_path)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise LoadRunError(f"server exited with {proc.returncode}; see {log_path}")
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(server.base + "/api/v1/health", timeout=2).status_code == 200:
                return server
        time.sleep(0.5)
    server.stop()
    raise LoadRunError("server did not become healthy within 90 s")


# ---- RSS and store sampling ----------------------------------------------------------------------
@dataclass
class RssSampler:
    """Every `every_s`: (seconds since start, RSS bytes) and the server's whole /__load/state (store sizes,
    CPU time). With `heap_mark_at_s`, asks the server for a tracemalloc baseline once that time has passed."""

    server: Server
    every_s: float
    heap_mark_at_s: float | None = None
    samples: list[tuple[float, int]] = field(default_factory=list)
    states: list[dict[str, Any]] = field(default_factory=list)
    heap_marked_at_s: float | None = None
    heap_mark_s: float = 0.0  # how long the snapshot took (it runs on the server's event loop)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="rss-sampler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        t0 = time.time()
        while not self._stop.is_set():
            with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
                state = self.server.get("/__load/state")
                t = time.time() - t0
                self.samples.append((t, int(state["rss_bytes"])))
                self.states.append({"t": round(t, 1), **state})
            due = self.heap_mark_at_s is not None and time.time() - t0 >= self.heap_mark_at_s
            if due and self.heap_marked_at_s is None:
                with contextlib.suppress(httpx.HTTPError):
                    started = time.time()
                    self.server.get("/__load/heap?op=mark", timeout=600)
                    self.heap_marked_at_s = round(time.time() - t0, 1)
                    self.heap_mark_s = round(time.time() - started, 1)
            self._stop.wait(self.every_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)

    def suspend_gaps(self) -> list[float]:
        """Sampling gaps (seconds) long enough to mean the machine was suspended (not the gap of the
        tracemalloc baseline, during which the sampler itself waited for the snapshot)."""
        times = [t for t, _ in self.samples]
        mark_end = self.heap_marked_at_s
        mark_start = None if mark_end is None else mark_end - self.heap_mark_s
        return [
            b - a
            for a, b in itertools.pairwise(times)
            if b - a > SUSPEND_GAP_FACTOR * self.every_s
            and not (mark_start is not None and mark_end is not None and a <= mark_end and b >= mark_start)
        ]


# ---- Locust --------------------------------------------------------------------------------------
def run_locust(server: Server, run_dir: Path, *, users: int, minutes: float, mode: str) -> Path:
    records = run_dir / "records.jsonl"
    # soak: about 4 new users (sessions) per second, under the global 300 session creations per minute
    spawn_rate = {"overload": users, "soak": max(1, users // 75)}.get(mode, max(1, users // 10))
    env = {
        **os.environ,
        "LOAD_RECORDS": str(records),
        "LOAD_MODE": mode,
        "LOAD_REJECT_WAIT_S": "1.0",
        **USERS_ENV[mode],
    }
    cmd = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(LOCUSTFILE),
        "--headless",
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "-t",
        f"{int(minutes * 60)}s",
        "--host",
        server.base,
        "--csv",
        str(run_dir / "locust"),
        "--only-summary",
        "--stop-timeout",
        "30",
        "--exit-code-on-error",
        "0",
    ]
    started = time.time()
    with (run_dir / "locust.log").open("wb") as log:
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=log)  # noqa: S603
        cpu = _watch_cpu(proc)
    (run_dir / "locust_cpu.json").write_text(
        json.dumps({"cpu_s": round(cpu, 1), "wall_s": round(time.time() - started, 1)}), encoding="utf-8"
    )
    if proc.returncode != 0:
        raise LoadRunError(f"locust exited with {proc.returncode}; see {run_dir / 'locust.log'}")
    return records


def _watch_cpu(proc: subprocess.Popen[bytes], every_s: float = 2.0) -> float:
    """Wait for `proc`; return the CPU seconds of its process tree (on Windows the venv's python.exe is a
    launcher whose child is the real interpreter), sampled every `every_s` until it exits."""
    import psutil

    seen: dict[int, float] = {}
    while proc.poll() is None:
        with contextlib.suppress(psutil.Error):
            root = psutil.Process(proc.pid)
            for p in (root, *root.children(recursive=True)):
                with contextlib.suppress(psutil.Error):
                    times = p.cpu_times()
                    seen[p.pid] = times.user + times.system
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=every_s)
    return sum(seen.values())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---- metrics -------------------------------------------------------------------------------------
def record(metric: str, value: float, *, sample_size: int, **labels: str) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "labels": dict(labels),
        "sample_size": sample_size,
        "source": SOURCE,
        "measured_at": _now(),
        "free_tier": False,  # fake LLM: no API tier involved
    }


def _duration_labels(minutes: float, gate_minutes: float) -> dict[str, str]:
    return {"duration_min": f"{minutes:.1f}", "reduced_sample": str(minutes < gate_minutes).lower()}


def _errors_by_kind(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        if not r.get("ok"):
            key = str(r.get("error"))
            out[key] = out.get(key, 0) + 1
    return out


def wall_minutes(samples: Sequence[dict[str, Any]]) -> float:
    """Real duration covered by the server's samples (first request start to last request end)."""
    if not samples:
        return 0.0
    first = min(float(s["started"]) for s in samples)
    last = max(float(s["started"]) + float(s["wall_ms"]) / 1000 for s in samples)
    return (last - first) / 60


def mean_streams(samples: Sequence[dict[str, Any]]) -> float:
    """Average number of chat responses in flight (Little's law over the server samples)."""
    chat = [s for s in samples if s["path"] == "/api/v1/chat"]
    minutes = wall_minutes(chat)
    return sum(s["wall_ms"] for s in chat) / 1000 / (minutes * 60) if minutes else 0.0


def rss_growth(rss: Sequence[tuple[float, int]], warmup_s: float) -> tuple[float, int, int, float, int]:
    """(growth, base bytes, end bytes, window minutes, samples after warm-up)."""
    after = [(t, b) for t, b in rss if t >= warmup_s]
    if not after:
        return float("nan"), 0, 0, 0.0, 0
    base, end = after[0][1], after[-1][1]
    return (end - base) / base, base, end, (after[-1][0] - after[0][0]) / 60, len(after)


def latency_summary(samples: Sequence[dict[str, Any]]) -> dict[str, float]:
    chat = [s for s in samples if s["path"] == "/api/v1/chat" and s["status"] == 200]
    upper = [float(s["app_ms_uncorrected"]) for s in chat]
    lower = [float(s["app_ms_lower"]) for s in chat]
    calibrated = [float(s["app_ms"]) for s in chat]
    return {
        "chat_turns_server": float(len(chat)),
        "app_ms_upper_p50": percentile(upper, 0.5),
        "app_ms_upper_p95": percentile(upper, 0.95),
        "app_ms_upper_p99": percentile(upper, 0.99),
        "app_ms_lower_p95": percentile(lower, 0.95),
        "app_ms_calibrated_p95": percentile(calibrated, 0.95),
        "mean_model_sleeps_per_turn": sum(int(s["sleeps"]) for s in chat) / len(chat) if chat else 0.0,
        "mean_streams_in_flight": mean_streams(samples),
    }


def steady_metrics(
    rows: Sequence[dict[str, Any]],
    samples: Sequence[dict[str, Any]],
    rss: Sequence[tuple[float, int]],
    *,
    users: int,
    warmup_s: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """error_rate and app_added_latency_p95_ms. RSS growth is in the summary only: with session churn the
    memory session store keeps every session for its 2 h lifetime, so it grows by design (the soak is the
    gate run)."""
    summary = _run_summary(rows, samples, rss, warmup_s)
    summary["rss_growth_note"] = "informational: session churn (a new session every 60 turns per user)"
    errors, rate, by_kind = summary["errors"], summary["error_rate"], summary["errors_by_kind"]
    minutes, lat = summary["load_minutes"], latency_summary(samples)
    common = _common_labels(users, lat)
    out = [
        record(
            "error_rate",
            round(rate, 6),
            sample_size=len(rows),
            **common,
            **_duration_labels(minutes, GATE_MINUTES["error_rate"]),
            errors=str(errors),
            errors_by_kind=json.dumps(by_kind, sort_keys=True),
        ),
        record(
            "app_added_latency_p95_ms",
            round(lat["app_ms_upper_p95"], 2),
            sample_size=int(lat["chat_turns_server"]),
            **common,
            duration_min=f"{minutes:.1f}",
            bound="upper (wall - requested model time)",
            p50_ms=f"{lat['app_ms_upper_p50']:.2f}",
            p99_ms=f"{lat['app_ms_upper_p99']:.2f}",
            lower_bound_p95_ms=f"{lat['app_ms_lower_p95']:.2f}",
        ),
    ]
    return out, summary


def soak_metrics(
    rows: Sequence[dict[str, Any]],
    samples: Sequence[dict[str, Any]],
    rss: Sequence[tuple[float, int]],
    *,
    users: int,
    warmup_s: float,
    states: Sequence[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """rss_growth_30min of the steady-state soak (fixed pool of users, one session each)."""
    summary = _run_summary(rows, samples, rss, warmup_s)
    summary["stores"] = store_growth(states, warmup_s)
    lat = latency_summary(samples)
    out = [
        record(
            "rss_growth_30min",
            round(summary["rss_growth"], 5),
            sample_size=summary["rss_samples_after_warmup"],
            **_common_labels(users, lat),
            **_duration_labels(summary["rss_window_min"], GATE_MINUTES["rss_growth_30min"]),
            model=SOAK_MODEL.format(users=users),
            think_s=f"{USERS_ENV['soak']['LOAD_THINK_MIN']}-{USERS_ENV['soak']['LOAD_THINK_MAX']}",
            warmup_min=f"{warmup_s / 60:.1f}",
            load_minutes=f"{summary['load_minutes']:.1f}",
            turns=str(int(lat["chat_turns_server"])),
            errors=str(summary["errors"]),
            rss_after_warmup_mb=f"{summary['rss_after_warmup_mb']}",
            rss_end_mb=f"{summary['rss_end_mb']}",
            rss_max_mb=f"{summary['rss_max_mb']}",
        ),
    ]
    return out, summary


def _common_labels(users: int, lat: dict[str, float]) -> dict[str, str]:
    return {
        "users": str(users),
        "streams_in_flight_mean": f"{lat['mean_streams_in_flight']:.1f}",
        "server": "uvicorn x1, fake LLM (ADR 0001 latencies), fake retriever, memory stores",
    }


def _run_summary(
    rows: Sequence[dict[str, Any]],
    samples: Sequence[dict[str, Any]],
    rss: Sequence[tuple[float, int]],
    warmup_s: float,
) -> dict[str, Any]:
    errors = [r for r in rows if not r.get("ok")]
    growth, base, end, window, n_rss = rss_growth(rss, warmup_s)
    return {
        "requests": len(rows),
        "errors": len(errors),
        "error_rate": len(errors) / len(rows) if rows else 1.0,
        "errors_by_kind": _errors_by_kind(rows),
        **latency_summary(samples),
        "client_total_ms_p95": percentile(
            [r["total_ms"] for r in rows if r["kind"] == "chat" and r.get("ok")], 0.95
        ),
        "rss_after_warmup_mb": round(base / 2**20, 1),
        "rss_end_mb": round(end / 2**20, 1),
        "rss_max_mb": round(max((b for _, b in rss), default=0) / 2**20, 1),
        "rss_growth": growth,
        "rss_window_min": round(window, 1),
        "rss_samples_after_warmup": n_rss,
        "load_minutes": round(wall_minutes(samples), 2),
    }


def overload_metrics(
    rows: Sequence[dict[str, Any]],
    samples: Sequence[dict[str, Any]],
    *,
    users: int,
    capacity: dict[str, float] = CAPACITY,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rejected = [r for r in rows if r["kind"] == "chat" and r.get("status") == 503]
    lat = [float(r["total_ms"]) for r in rejected]
    missing_retry = sum(1 for r in rejected if not r.get("retry_after"))
    server_503 = [float(s["wall_ms"]) for s in samples if s["path"] == "/api/v1/chat" and s["status"] == 503]
    other = [r for r in rows if not r.get("ok") and r.get("status") != 503]
    served = [r for r in rows if r["kind"] == "chat" and r.get("ok")]
    minutes = wall_minutes(samples)
    summary = {
        "requests": len(rows),
        "rejected_503": len(rejected),
        "served_ok": len(served),
        "missing_retry_after": missing_retry,
        "client_503_ms_p50": percentile(lat, 0.5),
        "client_503_ms_p95": percentile(lat, 0.95),
        "client_503_ms_max": max(lat, default=float("nan")),
        "server_503_ms_p50": percentile(server_503, 0.5),
        "server_503_ms_p95": percentile(server_503, 0.95),
        "other_errors_by_kind": _errors_by_kind(other),
        "served_client_total_ms_p95": percentile([r["total_ms"] for r in served], 0.95),
        "mean_streams_in_flight": mean_streams(samples),
        "load_minutes": round(minutes, 2),
        "client_vs_server_503": client_server_join(rows, samples),
        "rejection_phases_ms": rejection_phases(samples),  # probe runs only
    }
    chats = sum(1 for r in rows if r["kind"] == "chat")
    if not chats or len(rejected) < OVERLOAD_MIN_REJECTED_SHARE * chats:
        summary["not_written"] = (
            f"only {len(rejected)} of {chats} chat requests were refused: the offered load never reached the "
            "admission queue, so the rejection path was not measured"
        )
        return [], summary
    # a rejection without Retry-After does not meet the contract: count the run as failed
    value = percentile(lat, 0.95) if missing_retry == 0 else 1e9
    out = [
        record(
            overload_metric_name(users, capacity),
            round(value, 2),
            sample_size=len(rejected),
            users=str(users),
            capacity=f"{int(capacity['concurrency'])} slots + {int(capacity['queue_max'])} queued",
            offered_load=f"{users / capacity['concurrency']:.1f}x the model-turn slots, no think time, "
            "1 s pause after a 503",
            queue_wait_s=f"{capacity['queue_wait_s']:g}",
            duration_min=f"{minutes:.1f}",
            server_p95_ms=f"{summary['server_503_ms_p95']:.2f}",
            missing_retry_after=str(missing_retry),
            served_ok=str(len(served)),
            other_errors=json.dumps(summary["other_errors_by_kind"], sort_keys=True),
        ),
    ]
    return out, summary


def overload_metric_name(users: int, capacity: dict[str, float]) -> str:
    """The gate record comes only from the gate scenario (CAPACITY, 3x its slots in users); any other capacity
    is written under its own name, e.g. overload_rejection_latency_p95_ms_8_slots, and never replaces it."""
    if capacity == CAPACITY and users == 3 * int(CAPACITY["concurrency"]):
        return "overload_rejection_latency_p95_ms"
    return f"overload_rejection_latency_p95_ms_{int(capacity['concurrency'])}_slots"


# ---- orchestration -------------------------------------------------------------------------------
@dataclass
class RunData:
    rows: list[dict[str, Any]]
    samples: list[dict[str, Any]]
    rss: list[tuple[float, int]]
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    overshoot_ms: float
    suspend_gaps: list[float]
    states: list[dict[str, Any]] = field(default_factory=list)
    lags: list[list[float]] = field(default_factory=list)
    heap: dict[str, Any] = field(default_factory=dict)
    heap_marked_at_s: float | None = None
    heap_mark_s: float = 0.0


def collect(args: argparse.Namespace, keep: Path) -> RunData:
    with tempfile.TemporaryDirectory(prefix="ausculta-load-") as tmp, keep_awake():
        run_dir = Path(tmp)
        server = start_server(
            run_dir,
            args.mode,
            capacity_of(args),
            probe=args.probe,
            tracemalloc_frames=args.tracemalloc,
            inline_precheck=args.inline_precheck,
        )
        mark_at = args.warmup_min * 60 if args.tracemalloc else None
        sampler = RssSampler(server, args.rss_every_s, heap_mark_at_s=mark_at)
        lags: list[list[float]] = []
        heap: dict[str, Any] = {}
        try:
            overshoot = float(server.get("/__load/calibrate", timeout=60)["overshoot_ms"])
            before = server.get("/__load/state?gc=1", timeout=60)
            sampler.start()
            records = run_locust(server, run_dir, users=args.users, minutes=args.minutes, mode=args.mode)
            sampler.stop()
            after = server.get("/__load/state?gc=1", timeout=60)  # also flushes the samples file
            if args.probe:
                lags = server.get("/__load/lag?since=0", timeout=60)["lags"]
            if args.tracemalloc:
                heap = server.get("/__load/heap?op=diff", timeout=600)
        finally:
            sampler.stop()
            server.stop()
        for name in (
            "server.log",
            "locust.log",
            "locust_stats.csv",
            "locust_failures.csv",
            "locust_cpu.json",
        ):
            if (run_dir / name).exists():
                (keep / name).write_bytes((run_dir / name).read_bytes())
        return RunData(
            read_jsonl(records),
            read_jsonl(run_dir / "samples.jsonl"),
            sampler.samples,
            before,
            after,
            overshoot,
            sampler.suspend_gaps(),
            states=sampler.states,
            lags=lags,
            heap=heap,
            heap_marked_at_s=sampler.heap_marked_at_s,
            heap_mark_s=sampler.heap_mark_s,
        )


def _client_cpu(path: Path) -> dict[str, float]:
    """Locust's CPU seconds over its wall seconds (1.0 = one core busy: the client itself is saturated)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    wall = float(data["wall_s"])
    return {**data, "cores_busy": round(float(data["cpu_s"]) / wall, 3) if wall else 0.0}


def capacity_of(args: argparse.Namespace) -> dict[str, float]:
    return {
        "concurrency": float(args.concurrency or CAPACITY["concurrency"]),
        "queue_max": float(CAPACITY["queue_max"] if args.queue_max is None else args.queue_max),
        "queue_wait_s": float(args.queue_wait_s or CAPACITY["queue_wait_s"]),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if (args.probe or args.tracemalloc or args.inline_precheck) and not args.no_write:
        raise LoadRunError(
            "diagnostic runs (--probe, --tracemalloc, --inline-precheck) must not write gate metrics: "
            "use --no-write"
        )
    free = free_ram_bytes()
    if free < args.min_free_gb * GB:
        raise LoadRunError(f"only {free / GB:.1f} GB RAM free; need {args.min_free_gb} GB")
    reports = get_settings().data_root / "reports"
    keep = reports / "load" / f"{args.mode}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    keep.mkdir(parents=True, exist_ok=True)
    data = collect(args, keep)
    warmup_s = args.warmup_min * 60
    if args.mode == "overload":
        metrics, summary = overload_metrics(
            data.rows, data.samples, users=args.users, capacity=capacity_of(args)
        )
    elif args.mode == "soak":
        metrics, summary = soak_metrics(
            data.rows, data.samples, data.rss, users=args.users, warmup_s=warmup_s, states=data.states
        )
    else:
        metrics, summary = steady_metrics(
            data.rows, data.samples, data.rss, users=args.users, warmup_s=warmup_s
        )
    summary.update(
        mode=args.mode,
        users=args.users,
        diagnostics={
            "probe": args.probe,
            "tracemalloc_frames": args.tracemalloc,
            "inline_precheck": args.inline_precheck,
        },
        free_ram_gb=round(free / GB, 1),
        idle_timer_overshoot_ms=round(data.overshoot_ms, 3),
        suspend_gaps_s=data.suspend_gaps,
        server_cpu=cpu_use(data.state_before, data.state_after),
        client_cpu=_client_cpu(keep / "locust_cpu.json"),
        event_loop_lag=lag_summary(data.lags),
        heap_marked_at_s=data.heap_marked_at_s,
        heap_mark_s=data.heap_mark_s,
        state_before=data.state_before,
        state_after=data.state_after,
    )
    (keep / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (keep / "rss.json").write_text(json.dumps(data.rss), encoding="utf-8")
    (keep / "states.json").write_text(json.dumps(data.states), encoding="utf-8")
    if data.heap:
        (keep / "heap_diff.json").write_text(json.dumps(data.heap, indent=1), encoding="utf-8")
    if data.lags:
        (keep / "lag.json").write_text(json.dumps(data.lags), encoding="utf-8")
    if args.probe:  # the per-request phases and ids are the evidence of a probe run
        (keep / "samples.jsonl").write_text(
            "".join(json.dumps(s) + "\n" for s in data.samples), encoding="utf-8"
        )
        (keep / "records.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in data.rows), encoding="utf-8"
        )
    if data.suspend_gaps:
        raise LoadRunError(f"the machine was suspended during the run ({data.suspend_gaps}); see {keep}")
    if not args.no_write:
        out = reports / "load.metrics.json"
        existing = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
        write_metrics(out, merge_records(existing, metrics))
    return {"summary": summary, "metrics": metrics, "kept": str(keep)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", choices=("steady", "soak", "overload"))
    parser.add_argument("--users", type=int, default=None, help="default: 50 steady, 300 soak, 192 overload")
    parser.add_argument("--minutes", type=float, default=None, help="default: 32 steady, 40 soak, 3 overload")
    parser.add_argument(
        "--warmup-min", type=float, default=None, help="default: 2 steady, 10 soak, 0 overload"
    )
    parser.add_argument("--probe", action="store_true", help="phase marks + event-loop lag (diagnosis only)")
    parser.add_argument("--tracemalloc", type=int, default=0, help="tracemalloc frames (diagnosis only)")
    parser.add_argument(
        "--inline-precheck",
        action="store_true",
        help="experiment: run the precheck on the event loop, not in a worker thread (diagnosis only)",
    )
    parser.add_argument("--rss-every-s", type=float, default=15.0)
    parser.add_argument("--min-free-gb", type=float, default=3.0)
    parser.add_argument("--no-write", action="store_true", help="do not write load.metrics.json")
    parser.add_argument("--concurrency", type=int, default=None, help="AUSCULTA_LLM_CONCURRENCY (default 64)")
    parser.add_argument("--queue-max", type=int, default=None, help="AUSCULTA_QUEUE_MAX (default 32)")
    parser.add_argument("--queue-wait-s", type=float, default=None, help="AUSCULTA_QUEUE_WAIT_S (default 5)")
    args = parser.parse_args(argv)
    users, minutes, warmup = DEFAULTS[args.mode]
    args.users = users if args.users is None else args.users
    args.minutes = minutes if args.minutes is None else args.minutes
    args.warmup_min = warmup if args.warmup_min is None else args.warmup_min
    result = run(args)
    sys.stdout.write(json.dumps(result, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
