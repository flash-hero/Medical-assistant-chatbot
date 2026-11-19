"""The load harness (evals/load): realistic fake model timing, the timing middleware, metric computation."""

from __future__ import annotations

import random
from typing import Any

import httpx
import pytest

from core.models import ModelRole
from core.ports import GenerationRequest
from evals.fakes.scripted import scripted_provider
from evals.load.run import (
    mean_streams,
    overload_metrics,
    percentile,
    rss_growth,
    steady_metrics,
    wall_minutes,
)
from evals.load.server import _MODEL_TIME, LatencyProfile, RealisticFakeLLM, TimingMiddleware

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
    assert by["rss_growth_30min"]["value"] == pytest.approx(0.02)
    assert by["rss_growth_30min"]["labels"]["reduced_sample"] == "false"
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
