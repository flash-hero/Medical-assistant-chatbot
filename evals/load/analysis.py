"""Analysis helpers for the load runs: percentiles, the phase breakdown of 503 rejections (probe runs), the
join of client and server timings by request id, CPU use, event-loop lag and store sizes."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from evals.load.probe import PHASES

CHAT = "/api/v1/chat"


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in [0, 1]); nan for an empty list."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, math.ceil(round(q * len(ordered), 9)))
    return ordered[min(len(ordered), rank) - 1]


def _dist(values: Sequence[float]) -> dict[str, float]:
    return {
        "n": float(len(values)),
        "p50": round(percentile(values, 0.5), 2),
        "p95": round(percentile(values, 0.95), 2),
        "mean": round(sum(values) / len(values), 2) if values else float("nan"),
    }


def rejection_phases(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Where the server time of the 503 chat rejections goes: per phase p50 / p95 / mean over all
    rejections, and the mean of each phase over the slowest 5 % (wall >= p95): what the gate percentile is
    made of."""
    rejected = [s for s in samples if s.get("path") == CHAT and s.get("status") == 503 and "phases" in s]
    if not rejected:
        return {}
    walls = [float(s["wall_ms"]) for s in rejected]
    p95 = percentile(walls, 0.95)
    tail = [s for s in rejected if float(s["wall_ms"]) >= p95]
    names = [name for name, _, _ in PHASES]
    return {
        "n": len(rejected),
        "wall_ms": _dist(walls),
        "all": {n: _dist([float(s["phases"][n]) for s in rejected if n in s["phases"]]) for n in names},
        "slowest_5pct_mean_ms": {
            n: round(sum(float(s["phases"].get(n, 0.0)) for s in tail) / len(tail), 2) for n in names
        },
        "slowest_5pct_wall_mean_ms": round(sum(float(s["wall_ms"]) for s in tail) / len(tail), 2),
    }


def client_server_join(rows: Sequence[dict[str, Any]], samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Client-observed minus server-observed time of the same 503 requests (joined by X-Load-Req): the part of
    the gate metric spent outside the server process (client scheduling, sockets, kernel)."""
    server = {s["req"]: float(s["wall_ms"]) for s in samples if s.get("req") and s.get("status") == 503}
    pairs = [
        (float(r["total_ms"]), server[r["req"]])
        for r in rows
        if r.get("kind") == "chat" and r.get("status") == 503 and r.get("req") in server
    ]
    if not pairs:
        return {}
    client = [c for c, _ in pairs]
    return {
        "joined": len(pairs),
        "client_ms": _dist(client),
        "server_ms": _dist([s for _, s in pairs]),
        "outside_server_ms": _dist([c - s for c, s in pairs]),
    }


def cpu_use(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    """Server CPU seconds over wall seconds between two /__load/state snapshots (1.0 = one core busy)."""
    try:
        cpu = float(after["cpu_s"]) - float(before["cpu_s"])
        wall = float(after["wall"]) - float(before["wall"])
    except (KeyError, TypeError, ValueError):
        return {}
    return {
        "cpu_s": round(cpu, 1),
        "wall_s": round(wall, 1),
        "cores_busy": round(cpu / wall, 3) if wall else 0.0,
    }


def lag_summary(lags: Sequence[Sequence[float]]) -> dict[str, float]:
    """Event-loop lag samples [(unix time, ms)] -> distribution."""
    values = [float(lag) for _, lag in lags]
    if not values:
        return {}
    return {
        "n": float(len(values)),
        "p50_ms": round(percentile(values, 0.5), 2),
        "p90_ms": round(percentile(values, 0.9), 2),
        "p99_ms": round(percentile(values, 0.99), 2),
        "max_ms": round(max(values), 2),
        "mean_ms": round(sum(values) / len(values), 2),
    }


def store_growth(states: Sequence[dict[str, Any]], warmup_s: float) -> dict[str, Any]:
    """Each in-process store's size at the first sample after warm-up and at the last sample."""
    after = [s for s in states if float(s.get("t", 0.0)) >= warmup_s]
    if not after:
        return {}
    first, last = after[0], after[-1]
    keys = [k for k, v in last.items() if isinstance(v, int) and k not in ("samples", "threads")]
    return {k: {"after_warmup": first.get(k), "end": last.get(k)} for k in keys}
