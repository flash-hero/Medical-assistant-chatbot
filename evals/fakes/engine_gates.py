"""Engine release-gate measurements through the real ASGI app (app.main.create_app) and the scripted fake LLM.

  python -m evals.fakes.engine_gates [--out PATH] [--coverage-json SCOPE=PATH ...] [--cycles 1000]

Metrics written (names from evals/gates.yaml, record format from evals/gates_eval.py):
  emergency_template_latency_ms_all_models_failing
      max milliseconds from request start to the complete SSE response (meta .. safety .. answer .. done) over
      emergency and self-harm messages in EN/FR/AR while EVERY model role hangs 2 s and then fails.
  upstream_close_after_disconnect_s
      max seconds from the client disconnect to the upstream model stream being closed
      (FakeLLMProvider.closed_streams), streamed answers, in-process ASGI and a live uvicorn server.
  leaked_slots_after_1000_cancels
      admission slots still held or waiting after 1000 turns cancelled at varied points (client disconnect
      after N frames, after a delay, during off-screen generation, and server-side task cancellation).
  line_coverage (optional)
      from coverage.py JSON reports: --coverage-json "all=cov_all.json" --coverage-json "app=cov_app.json".
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import json
import os
import random
import secrets
import socket
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.api.container import Container, Overrides
from app.main import create_app
from core.config import Settings
from core.errors import UpstreamUnavailable
from evals.fakes.asgi_driver import DriveResult, drive
from evals.fakes.fake_llm import FakeLLMProvider
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.scripted import all_roles_failing, scripted_provider
from evals.fakes.sse_contract import order_violations, parse_sse

SOURCE = "evals.fakes.engine_gates"
DEFAULT_OUT = Path("C:/dev/ausculta-data/reports/engine.metrics.json")
HANG_S = 2.0  # every model call hangs this long before failing (emergency latency gate)
COVERAGE_SCOPES = {"app/guardrails app/pipeline": ("app/guardrails", "app/pipeline"), "all": ()}

# Synthetic messages (from evals/safety/seeds, held fixed here so the latency gate does not move with them).
SAFETY_MESSAGES: dict[str, tuple[str, ...]] = {
    "en": (
        "I have crushing chest pain spreading to my left arm and I'm sweating",
        "my chest hurts really bad and I feel like I'm going to pass out",
        "I can't breathe and my lips are turning blue",
        "my dad collapsed and he is not breathing",
        "I want to kill myself",
        "I'm thinking about ending my life",
    ),
    "fr": (
        "J'ai une douleur dans la poitrine qui descend dans le bras gauche",
        "je crois que je fais une crise cardiaque",
        "j'arrive pas à respirer",
        "mon bébé ne respire plus",
        "je veux me suicider",
        "je pense à mettre fin à mes jours",
    ),
    "ar": (
        "أشعر بألم شديد في صدري يمتد إلى ذراعي اليسرى",
        "لا أستطيع التنفس وشفتاي زرقاوان",
        "أريد أن أنتحر",
        "أفكر في الانتحار كل يوم",
    ),
}
STREAMED_QUESTION = "What is a fever?"
VERIFIED_QUESTION = "Is it safe to have a fever when pregnant?"
LONG_ANSWER = " ".join(["Drinking fluids and resting can help you feel better [1]."] * 40)


class GateMeasurementError(RuntimeError):
    """A measurement could not be taken (the app misbehaved); the gate must not be reported as met."""


# ---- app under test ------------------------------------------------------------------------------
def gate_settings(data_root: Path, **env: Any) -> Settings:
    """Settings isolated from the developer's .env: fake backend, temp SQLite, generous rate limits."""
    values: dict[str, Any] = {
        "AUSCULTA_LLM_BACKEND": "fake",
        "AUSCULTA_ENV": "test",
        "AUSCULTA_DATA_ROOT": str(data_root),
        "DATABASE_URL": f"sqlite+aiosqlite:///{(data_root / 'gates.db').as_posix()}",
        "REDIS_URL": None,
        "AUSCULTA_SESSION_SECRET": secrets.token_urlsafe(48),
        "GEMINI_API_KEY": None,
        "AUSCULTA_RATE_IP_MIN": 1_000_000,
        "AUSCULTA_RATE_SESSION_MIN": 1_000_000,
        "AUSCULTA_MAX_TURNS": 100,
    }
    values.update(env)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@dataclass
class GateApp:
    app: Any
    container: Container
    llm: FakeLLMProvider

    async def token(self, locale: str = "en") -> str:
        r = await drive(self.app, "POST", "/api/v1/session", {"locale": locale})
        if r.status != 201:
            raise GateMeasurementError(f"session creation failed with HTTP {r.status}")
        return str(json.loads(r.body)["session_token"])


@asynccontextmanager
async def running_app(data_root: Path, llm: FakeLLMProvider, **env: Any) -> AsyncIterator[GateApp]:
    app = create_app(gate_settings(data_root, **env), overrides=Overrides(llm=llm, retriever=FakeRetriever()))
    async with app.router.lifespan_context(app):
        yield GateApp(app, app.state.container, llm)


def chat_request(token: str, message: str, locale: str = "en") -> tuple[dict[str, str], dict[str, str]]:
    body = {"message": message, "locale": locale, "client_turn_id": str(uuid.uuid4())}
    headers = {"authorization": f"Bearer {token}", "accept": "text/event-stream"}
    return body, headers


async def _until(probe: Callable[[], float | None], timeout_s: float, what: str) -> float:
    """Busy-wait (yielding to the loop) until probe() returns a value; precise on Windows timers."""
    deadline = time.perf_counter() + timeout_s
    while (value := probe()) is None:
        if time.perf_counter() > deadline:
            raise GateMeasurementError(f"timed out waiting for {what}")
        await asyncio.sleep(0)
    return value


# ---- gate 1: emergency template latency with every model failing --------------------------------
@dataclass(frozen=True)
class LatencyResult:
    max_ms: float
    p95_ms: float
    max_safety_ms: float
    samples: int
    model_calls: int


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


async def _emergency_sample(g: GateApp, message: str, locale: str) -> tuple[float, float]:
    body, headers = chat_request(await g.token(locale), message, locale)
    r = await drive(g.app, "POST", "/api/v1/chat", body, headers)
    events = parse_sse(r.body) if r.status == 200 else []
    if r.status != 200 or "safety" not in [e.type for e in events] or order_violations(events):
        raise GateMeasurementError(f"no valid safety response for a {locale} sample (HTTP {r.status})")
    safety_at = r.first_chunk_at("event: safety")
    if r.finished_at is None or safety_at is None:
        raise GateMeasurementError("response did not complete")
    return (r.finished_at - r.started_at) * 1000, (safety_at - r.started_at) * 1000


async def measure_emergency_latency(data_root: Path, rounds: int = 2) -> LatencyResult:
    llm = FakeLLMProvider(
        failures=all_roles_failing(UpstreamUnavailable("all models down")), latency_s=HANG_S
    )
    totals: list[float] = []
    safety: list[float] = []
    async with running_app(data_root, llm) as g:
        for _ in range(rounds):
            for locale, messages in SAFETY_MESSAGES.items():
                for message in messages:
                    total_ms, safety_ms = await _emergency_sample(g, message, locale)
                    totals.append(total_ms)
                    safety.append(safety_ms)
    return LatencyResult(
        max_ms=max(totals),
        p95_ms=_percentile(totals, 0.95),
        max_safety_ms=max(safety),
        samples=len(totals),
        model_calls=len(llm.calls),
    )


# ---- gate 2: upstream stream closed after a client disconnect ----------------------------------
def _saw_delta(r: DriveResult) -> bool:
    return any(b"event: delta" in c for c in r.chunks)


async def _one_disconnect(g: GateApp) -> float:
    body, headers = chat_request(await g.token(), STREAMED_QUESTION)
    closed_before = g.llm.closed_streams
    result = DriveResult()
    task = asyncio.create_task(
        drive(g.app, "POST", "/api/v1/chat", body, headers, result=result, disconnect_when=_saw_delta)
    )
    try:
        t_disconnect = await _until(lambda: result.disconnected_at, 10.0, "the client disconnect")
        t_closed = await _until(
            lambda: time.perf_counter() if g.llm.closed_streams > closed_before else None,
            5.0,
            "the upstream stream to close",
        )
    finally:
        await task
    if result.finished_at is not None and result.finished_at < t_disconnect:
        raise GateMeasurementError("the answer finished before the disconnect; use a longer answer")
    return t_closed - t_disconnect


async def measure_disconnect_close(data_root: Path, runs: int = 5) -> list[float]:
    llm = scripted_provider(answer=LONG_ANSWER, chunk_chars=24, chunk_delay_s=0.05)
    async with running_app(data_root, llm) as g:
        values = [await _one_disconnect(g) for _ in range(runs)]
        if llm.open_streams:
            raise GateMeasurementError(f"{llm.open_streams} upstream streams still open")
    return values


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_sync(probe: Callable[[], float | None], timeout_s: float, what: str) -> float:
    deadline = time.perf_counter() + timeout_s
    while (value := probe()) is None:
        if time.perf_counter() > deadline:
            raise GateMeasurementError(f"timed out waiting for {what}")
        time.sleep(0.0005)
    return value


def measure_disconnect_close_live(data_root: Path, runs: int = 3) -> list[float]:
    """Same gate over real TCP: uvicorn in a thread, an httpx client that drops the connection mid-answer."""
    import httpx
    import uvicorn

    llm = scripted_provider(answer=LONG_ANSWER, chunk_chars=24, chunk_delay_s=0.05)
    app = create_app(gate_settings(data_root), overrides=Overrides(llm=llm, retriever=FakeRetriever()))
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, name="gate-uvicorn", daemon=True)
    thread.start()
    values: list[float] = []
    try:
        _wait_sync(lambda: 1.0 if server.started else None, 20.0, "uvicorn to start")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10.0) as client:
            for _ in range(runs):
                values.append(_live_disconnect(client, llm))
        _wait_sync(lambda: 1.0 if llm.open_streams == 0 else None, 2.0, "all upstream streams to close")
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
    return values


def _live_disconnect(client: Any, llm: FakeLLMProvider) -> float:
    r = client.post("/api/v1/session", json={"locale": "en"})
    if r.status_code != 201:
        raise GateMeasurementError(f"live session creation failed with HTTP {r.status_code}")
    body, headers = chat_request(r.json()["session_token"], STREAMED_QUESTION)
    closed_before = llm.closed_streams
    with client.stream("POST", "/api/v1/chat", json=body, headers=headers) as resp:
        for line in resp.iter_lines():
            if line.startswith("event: delta"):
                break
        else:
            raise GateMeasurementError("the live stream ended before any delta")
    t_disconnect = time.perf_counter()  # leaving the block closes the half-read response and its connection
    t_closed = _wait_sync(
        lambda: time.perf_counter() if llm.closed_streams > closed_before else None, 5.0, "upstream close"
    )
    return t_closed - t_disconnect


# ---- gate 3: admission slots after 1000 cancelled turns ----------------------------------------
@dataclass
class LeakResult:
    cycles: int
    held: int
    waiting: int
    running_turns: int
    open_streams: int
    statuses: dict[int, int] = field(default_factory=dict)
    held_after_gc: int = 0

    @property
    def leaked(self) -> int:
        return self.held + self.waiting


async def _cancel_cycle(g: GateApp, token: str, i: int, rng: random.Random) -> int:
    mode = i % 4
    message = VERIFIED_QUESTION if mode == 3 else STREAMED_QUESTION
    body, headers = chat_request(token, message)
    if mode == 0:
        r = await drive(
            g.app, "POST", "/api/v1/chat", body, headers, disconnect_after_chunks=rng.randint(1, 6)
        )
        return r.status
    if mode in (1, 3):
        r = await drive(g.app, "POST", "/api/v1/chat", body, headers, disconnect_after_s=rng.uniform(0, 0.03))
        return r.status
    task = asyncio.create_task(drive(g.app, "POST", "/api/v1/chat", body, headers))
    await asyncio.sleep(rng.uniform(0, 0.03))
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        return (await task).status
    return 499  # cancelled server-side (nginx's "client closed request" code, for the stats only)


async def measure_cancel_leaks(data_root: Path, cycles: int = 1000, seed: int = 7) -> LeakResult:
    llm = scripted_provider(chunk_chars=16, chunk_delay_s=0.003)
    llm.latency_s = 0.002
    rng = random.Random(seed)
    statuses: dict[int, int] = {}
    async with running_app(data_root, llm, AUSCULTA_LLM_CONCURRENCY=4, AUSCULTA_QUEUE_MAX=64) as g:
        token = ""
        for i in range(cycles):
            if i % 40 == 0:
                token = await g.token()
            status = await _cancel_cycle(g, token, i, rng)
            statuses[status] = statuses.get(status, 0) + 1
        await asyncio.sleep(0.05)  # let the last shielded cleanups finish
        adm, reg = g.container.admission, g.container.registry
        result = LeakResult(cycles, adm.held, adm.waiting, reg.running, llm.open_streams, statuses)
        gc.collect()
        result.held_after_gc = adm.held
    return result


# ---- records and output -------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(metric: str, value: float, *, sample_size: int | None, **labels: str) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "labels": dict(labels),
        "sample_size": sample_size,
        "source": SOURCE,
        "measured_at": _now(),
        "free_tier": False,  # measured against the fake LLM: no API tier involved
    }


def coverage_ratio(report: dict[str, Any], prefixes: Sequence[str]) -> tuple[float, int]:
    """Line coverage (covered statements / statements) of files under `prefixes` (all files when empty)."""
    statements = covered = 0
    for name, data in report.get("files", {}).items():
        norm = name.replace("\\", "/")
        if prefixes and not any(norm.startswith(p.rstrip("/") + "/") for p in prefixes):
            continue
        statements += int(data["summary"]["num_statements"])
        covered += int(data["summary"]["covered_lines"])
    if statements == 0:
        raise GateMeasurementError(f"no measured files under {list(prefixes) or 'any path'}")
    return covered / statements, statements


def coverage_records(paths: dict[str, Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for scope, path in paths.items():
        if scope not in COVERAGE_SCOPES:
            raise GateMeasurementError(
                f"unknown coverage scope {scope!r}; use one of {sorted(COVERAGE_SCOPES)}"
            )
        report = json.loads(path.read_text(encoding="utf-8"))
        ratio, statements = coverage_ratio(report, COVERAGE_SCOPES[scope])
        out.append(record("line_coverage", round(ratio, 4), sample_size=statements, scope=scope))
    return out


def write_metrics(path: Path, records: Sequence[dict[str, Any]]) -> None:
    """Atomic UTF-8 write (temp file in the same directory + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(list(records), fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


async def _measure_async(root: Path, cycles: int) -> tuple[LatencyResult, list[float], LeakResult]:
    latency = await measure_emergency_latency(root / "latency")
    closes = await measure_disconnect_close(root / "disconnect")
    leaks = await measure_cancel_leaks(root / "leaks", cycles=cycles)
    return latency, closes, leaks


def measure_all(cycles: int = 1000, *, live: bool = True) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="ausculta-gates-") as tmp:
        root = Path(tmp)
        for sub in ("latency", "disconnect", "leaks", "live"):
            (root / sub).mkdir()
        latency, closes, leaks = asyncio.run(_measure_async(root, cycles))
        live_closes = measure_disconnect_close_live(root / "live") if live else []
    return [
        record(
            "emergency_template_latency_ms_all_models_failing",
            round(latency.max_ms, 2),
            sample_size=latency.samples,
            stat="max",
            p95_ms=f"{latency.p95_ms:.2f}",
            max_safety_frame_ms=f"{latency.max_safety_ms:.2f}",
            model_calls=str(latency.model_calls),
        ),
        record(
            "upstream_close_after_disconnect_s",
            round(max(closes + live_closes), 4),
            sample_size=len(closes) + len(live_closes),
            stat="max",
            in_process_max_s=f"{max(closes):.4f}",
            live_uvicorn_max_s=f"{max(live_closes):.4f}" if live_closes else "not run",
        ),
        record(
            "leaked_slots_after_1000_cancels",
            float(leaks.leaked),
            sample_size=leaks.cycles,
            running_turns=str(leaks.running_turns),
            open_streams=str(leaks.open_streams),
            held_after_gc=str(leaks.held_after_gc),
            statuses=",".join(f"{k}:{v}" for k, v in sorted(leaks.statuses.items())),
        ),
    ]


def _parse_coverage(items: Sequence[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for item in items:
        scope, sep, path = item.partition("=")
        if not sep:
            raise SystemExit(f"--coverage-json expects SCOPE=PATH, got {item!r}")
        out[scope] = Path(path)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--coverage-json", action="append", default=[], metavar="SCOPE=PATH")
    parser.add_argument("--coverage-only", action="store_true", help="only merge coverage records")
    parser.add_argument("--no-live", action="store_true", help="skip the live uvicorn disconnect runs")
    args = parser.parse_args(argv)
    fresh = [] if args.coverage_only else measure_all(args.cycles, live=not args.no_live)
    fresh += coverage_records(_parse_coverage(args.coverage_json))
    records = merge_records(_read_records(args.out), fresh)
    write_metrics(args.out, records)
    for r in records:
        sys.stdout.write(f"{r['metric']:<52} {r['value']!s:<10} {r['labels']}\n")
    return 0


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _key(r: dict[str, Any]) -> tuple[str, str]:
    return str(r.get("metric")), str((r.get("labels") or {}).get("scope", ""))


def merge_records(
    existing: Sequence[dict[str, Any]], fresh: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fresh records replace existing ones with the same metric (and coverage scope); others are kept."""
    replaced = {_key(r) for r in fresh}
    return [r for r in existing if _key(r) not in replaced] + list(fresh)


if __name__ == "__main__":
    raise SystemExit(main())
