"""The load harness (evals/load): realistic fake model timing, the timing middleware, metric computation."""

from __future__ import annotations

import random
from typing import Any

import httpx
import pytest

from core.models import ModelRole
from core.ports import GenerationRequest
from core.schemas.chat import RetrievalQuery
from evals.fakes.scripted import scripted_provider
from evals.load.analysis import client_server_join, cpu_use, percentile, rejection_phases, store_growth
from evals.load.probe import PHASES, install_probes, mark, phases_ms
from evals.load.run import (
    mean_streams,
    overload_metrics,
    rss_growth,
    soak_metrics,
    steady_metrics,
    wall_minutes,
)
from evals.load.server import (
    _MODEL_TIME,
    LatencyProfile,
    RealisticFakeLLM,
    TimingMiddleware,
    load_llm,
    load_retriever,
)

FAST = LatencyProfile(ttft_s=0.01, chunk_s=0.002, decide_s=0.01, generate_s=0.01, sigma=0.0, chunk_sigma=0.0)


def test_percentile_is_nearest_rank() -> None:
    assert percentile([5, 1, 3, 2, 4], 0.5) == 3
    assert percentile(list(range(1, 101)), 0.95) == 95
    assert percentile([7], 0.99) == 7


async def test_realistic_fake_model_books_its_time_to_the_request() -> None:
    llm = RealisticFakeLLM(inner=scripted_provider(), profile=FAST, rng=random.Random(1))
    acc = [0.0, 0.0, 0.0]
    token = _MODEL_TIME.set(acc)
    try:
        req = GenerationRequest(role=ModelRole.ANSWER, system="s", prompt="p")
        chunks = [c async for c in llm.stream(req)]
    finally:
        _MODEL_TIME.reset(token)
    assert len(chunks) > 1
    assert acc[2] == len(chunks)  # TTFT + one sleep between consecutive chunks
    assert acc[0] == pytest.approx(0.01 + 0.002 * (len(chunks) - 1))
    assert acc[1] >= acc[0]


async def test_timing_middleware_records_requests_and_serves_harness_routes() -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"event: answer\n\n", "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    mw = TimingMiddleware(app)
    transport = httpx.ASGITransport(app=mw)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/api/v1/health")).status_code == 200
        rss = (await client.get("/__load/rss")).json()
        stats = (await client.get("/__load/stats?since=0")).json()
    assert rss["samples"] == 1
    assert rss["rss_bytes"] > 0
    [sample] = stats["samples"]
    assert sample["status"] == 200
    assert sample["first_event_ms"] is not None
    assert sample["app_ms_uncorrected"] == pytest.approx(sample["wall_ms"])


def _sample(
    started: float, wall_ms: float, status: int = 200, model_ms: float = 0.0
) -> dict[str, float | str]:
    return {
        "path": "/api/v1/chat",
        "status": status,
        "started": started,
        "wall_ms": wall_ms,
        "app_ms_uncorrected": wall_ms - model_ms,
        "app_ms_lower": wall_ms - model_ms - 1,
        "app_ms": wall_ms,
        "sleeps": 3,
    }


def test_steady_metrics() -> None:
    samples = [_sample(1000.0 + i, 2000.0, model_ms=1990.0) for i in range(60)]
    rows = [{"kind": "chat", "ok": True, "total_ms": 2000.0}] * 99 + [
        {"kind": "chat", "ok": False, "error": "x"}
    ]
    rss = [(0.0, 100), (120.0, 100), (1920.0, 102)]
    records, summary = steady_metrics(rows, samples, rss, users=50, warmup_s=120)
    by = {r["metric"]: r for r in records}
    assert by["error_rate"]["value"] == pytest.approx(0.01)
    assert by["error_rate"]["labels"]["users"] == "50"
    assert by["app_added_latency_p95_ms"]["value"] == pytest.approx(10.0)
    # with session churn the RSS growth is informational: the soak (fixed pool of sessions) owns the gate
    assert "rss_growth_30min" not in by
    assert summary["rss_growth"] == pytest.approx(0.02)
    assert summary["load_minutes"] == pytest.approx(wall_minutes(samples), abs=0.01)
    assert mean_streams(samples) == pytest.approx(60 * 2.0 / (61.0), rel=0.01)


def test_rss_growth_without_samples_after_warmup_is_nan() -> None:
    growth, *_ = rss_growth([(0.0, 100)], warmup_s=60)
    assert growth != growth  # nan


def test_overload_metrics_requires_retry_after_on_every_rejection() -> None:
    samples = [_sample(1.0, 5.0, status=503), _sample(2.0, 9.0, status=503)]
    ok: list[dict[str, Any]] = [
        {"kind": "chat", "status": 503, "ok": False, "total_ms": 12.0, "retry_after": "5"}
    ] * 20
    records, summary = overload_metrics(ok, samples, users=192)
    assert records[0]["value"] == pytest.approx(12.0)
    assert summary["missing_retry_after"] == 0
    missing = [*ok, {"kind": "chat", "status": 503, "ok": False, "total_ms": 3.0, "retry_after": None}]
    records, _ = overload_metrics(missing, samples, users=192)
    assert records[0]["value"] >= 1e9


def test_overload_run_that_never_filled_the_queue_writes_no_gate_record() -> None:
    """A CPU-starved host served almost everything and refused 2 of 3,628 requests: not a rejection test."""
    samples = [_sample(1.0, 60.0, status=503)]
    rows: list[dict[str, Any]] = [{"kind": "chat", "ok": True, "status": 200, "total_ms": 9000.0}] * 98 + [
        {"kind": "chat", "status": 503, "ok": False, "total_ms": 150.0, "retry_after": "5"}
    ] * 2
    records, summary = overload_metrics(rows, samples, users=192)
    assert records == []
    assert "never reached the admission queue" in summary["not_written"]


def test_soak_metrics_measure_rss_after_the_warm_up_and_label_the_steady_state_model() -> None:
    samples = [_sample(1000.0 + i * 30, 2000.0, model_ms=1990.0) for i in range(80)]
    rows = [{"kind": "chat", "ok": True, "total_ms": 2000.0}] * 100
    rss = [(0.0, 50), (300.0, 100), (600.0, 101), (2400.0, 103)]
    states = [{"t": 0.0, "sessions": 10}, {"t": 600.0, "sessions": 300}, {"t": 2400.0, "sessions": 300}]
    records, summary = soak_metrics(rows, samples, rss, users=300, warmup_s=600, states=states)
    [rec] = records
    assert rec["metric"] == "rss_growth_30min"
    assert rec["value"] == pytest.approx(0.0198, abs=1e-4)  # from 101 at the end of the warm-up, not 50
    assert rec["labels"]["reduced_sample"] == "false"  # 30-minute window after the warm-up
    assert "fixed pool of 300 users" in rec["labels"]["model"]
    assert rec["labels"]["warmup_min"] == "10.0"
    assert summary["stores"]["sessions"] == {"after_warmup": 300, "end": 300}


def test_overload_summary_joins_client_and_server_timings_by_request_id() -> None:
    samples = [{**_sample(1.0, 40.0, status=503), "req": "a"}, {**_sample(2.0, 60.0, status=503), "req": "b"}]
    rows: list[dict[str, Any]] = [
        {"kind": "chat", "status": 503, "ok": False, "total_ms": 50.0, "retry_after": "5", "req": "a"},
        {"kind": "chat", "status": 503, "ok": False, "total_ms": 90.0, "retry_after": "5", "req": "b"},
    ]
    _, summary = overload_metrics(rows, samples, users=192)
    joined = client_server_join(rows, samples)
    assert joined["joined"] == 2
    assert joined["outside_server_ms"]["p95"] == pytest.approx(30.0)
    assert summary["client_vs_server_503"] == joined


def test_rejection_phases_cut_the_server_time_into_named_phases() -> None:
    marks = {"t0": 0.0, "handler": 2.0, "ingress_done": 3.0, "precheck_start": 10.0, "precheck_end": 14.0}
    marks |= {"checks": 30.0, "admission": 31.0, "admission_exit": 31.0, "response_start": 35.0, "end": 36.0}
    phases = phases_ms(marks)
    assert [name for name, _, _ in PHASES] == list(phases)
    assert phases["thread_dispatch"] == pytest.approx(7.0)
    assert phases["loop_resume"] == pytest.approx(16.0)
    assert sum(phases.values()) == pytest.approx(36.0)  # the phases tile the whole request
    out = rejection_phases([{**_sample(1.0, 36.0, status=503), "phases": phases}])
    assert out["n"] == 1
    assert out["slowest_5pct_mean_ms"]["loop_resume"] == pytest.approx(16.0)


def test_cpu_use_and_store_growth() -> None:
    assert cpu_use({"cpu_s": 10.0, "wall": 100.0}, {"cpu_s": 70.0, "wall": 160.0})["cores_busy"] == 1.0
    assert cpu_use({}, {}) == {}
    states = [{"t": 0.0, "replay": 0}, {"t": 120.0, "replay": 2000}, {"t": 900.0, "replay": 2000}]
    assert store_growth(states, 100.0) == {"replay": {"after_warmup": 2000, "end": 2000}}


async def test_probe_marks_reach_worker_threads_and_land_in_the_sample() -> None:
    """The precheck runs in an anyio worker thread: its marks must land in the request's own sample."""
    import anyio

    async def app(scope: Any, receive: Any, send: Any) -> None:
        mark("handler")
        await anyio.to_thread.run_sync(mark, "precheck_start")
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})

    mw = TimingMiddleware(app, probe=True)
    transport = httpx.ASGITransport(app=mw)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        await client.post("/api/v1/chat", headers={"X-Load-Req": "r1"})
        lag = (await client.get("/__load/lag?since=0")).json()
    [sample] = mw.samples
    row = sample.as_dict(0.0)
    assert row["req"] == "r1"
    assert sample.marks is not None
    assert {"t0", "handler", "precheck_start", "response_start", "end"} <= set(sample.marks)
    assert row["phases"]["send"] >= 0.0
    assert lag["interval_s"] > 0


async def test_install_probes_keeps_the_wrapped_behaviour() -> None:
    from types import SimpleNamespace

    from app.api import routes_chat

    calls: list[str] = []

    async def acquire() -> None:
        calls.append("acquire")

    async def check_ip(ip: str) -> None:
        calls.append(ip)

    container = SimpleNamespace(
        signer=SimpleNamespace(verify=lambda token: token.upper()),
        engine=SimpleNamespace(precheck=lambda message: ("pre", message)),
        rate=SimpleNamespace(check_ip=check_ip),
        admission=SimpleNamespace(acquire=acquire),
    )
    original = routes_chat.__dict__["process_ingress"]
    try:
        install_probes(container)
        assert container.signer.verify("t") == "T"
        assert container.engine.precheck("m") == ("pre", "m")
        await container.rate.check_ip("10.0.0.1")
        await container.admission.acquire()
        assert calls == ["10.0.0.1", "acquire"]
        assert routes_chat.__dict__["process_ingress"] is not original
    finally:
        routes_chat.__dict__["process_ingress"] = original


def test_load_retriever_keeps_no_call_log() -> None:
    """P5 soak finding: FakeRetriever.calls held every RetrievalQuery of the run (~16,500 after 30 min)."""
    retriever = load_retriever()
    for _ in range(100):
        retriever.calls.append(RetrievalQuery(standalone_query="fever", language="en"))
    assert len(retriever.calls) == 0


async def test_load_llm_keeps_no_call_log() -> None:
    """P5 soak finding: FakeLLMProvider.calls held one tuple per model call (~100,000 in a 40-minute soak)."""
    llm = load_llm(seed=1)
    llm.profile = FAST
    for _ in range(5):
        await llm.generate(GenerationRequest(role=ModelRole.REWRITE, system="s", prompt="p"))
    assert len(llm.inner.calls) == 0


def test_suspend_gaps_ignore_the_tracemalloc_baseline() -> None:
    """The heap snapshot runs on the server's event loop: the sampler waits for it, which is no suspend."""
    from evals.load.run import RssSampler

    sampler = RssSampler(server=None, every_s=15.0)  # type: ignore[arg-type]
    sampler.samples = [(0.0, 1), (15.0, 1), (320.0, 1), (335.0, 1), (700.0, 1)]
    sampler.heap_marked_at_s, sampler.heap_mark_s = 318.0, 300.0
    assert sampler.suspend_gaps() == [365.0]  # the gap 15 -> 320 is the snapshot, 335 -> 700 is not
