"""P4 integration evaluation on the real pipeline (real Gemini provider, live corpus, real guardrails).

  python -m evals.p4 run --suite safety|quality|dose|refusal|judge|judge-refusal [--limit N] [--per-lang N]
  python -m evals.p4 report      # recompute {data_root}/reports/p4.metrics.json from the cache
  python -m evals.p4 status      # cache counts and model calls used so far
  python -m evals.p4 failures    # failing items per metric (ids, excerpts)

The call budget is cumulative over every run (ledger in {data_root}/reports/p4/ledger.json): a run stops
before the totals pass --max-generate / --max-decide. Runs that load the local embedding model (every suite
except safety and judge) refuse to start with less than --min-free-gb of free RAM.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import sys
from collections.abc import Sequence
from typing import Any

from core.config import Settings, get_settings
from evals.p4.items import DEFAULT_QUALITY_PER_LANG, SUITES, suite_items
from evals.p4.metrics import is_answered
from evals.p4.provider import CountingProvider, CountingRetryPolicy
from evals.p4.runner import (
    RunOptions,
    RunSummary,
    run_items,
    run_judge,
    run_refusal_judge,
    write_metrics,
)
from evals.p4.store import Store

DEFAULT_MAX_GENERATE = 400
DEFAULT_MAX_DECIDE = 1500
DEFAULT_PACE_S = {
    "latency": 5.0,
    "safety": 0.5,
    "quality": 5.0,
    "dose": 5.0,
    "refusal": 5.0,
    "judge": 5.0,
    "judge-refusal": 5.0,
}
RESERVE = {
    "latency": (4, 4),
    "safety": (1, 3),
    "quality": (4, 4),
    "dose": (4, 4),
    "refusal": (4, 4),
    "judge": (2, 0),
    "judge-refusal": (2, 0),
}
MIN_FREE_GB = 3.0
EMBEDDING_SUITES = frozenset({"quality", "dose", "refusal", "latency"})


class _MemStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_ram_gb() -> float | None:
    """Free physical memory in GB (Windows), None elsewhere."""
    if sys.platform != "win32":
        return None
    status = _MemStatus()
    status.dwLength = ctypes.sizeof(_MemStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return float(status.ullAvailPhys) / 1024**3


def _out(text: str) -> None:
    sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")
    sys.stdout.flush()


def _caps(store: Store, args: argparse.Namespace) -> tuple[int, int]:
    led = store.ledger()
    return (
        max(0, args.max_generate - int(led.get("generate", 0))),
        max(0, args.max_decide - int(led.get("decide", 0))),
    )


def _options(args: argparse.Namespace) -> RunOptions:
    gen, dec = RESERVE[args.suite]
    pace = args.pace if args.pace is not None else DEFAULT_PACE_S[args.suite]
    return RunOptions(limit=args.limit, pace_s=pace, reserve_generate=gen, reserve_decide=dec)


async def _run_suite(settings: Settings, store: Store, args: argparse.Namespace) -> RunSummary:
    from evals.p4.harness import open_real_harness, real_settings

    run_settings = real_settings(store.db_path)
    gen_left, dec_left = _caps(store, args)
    items = suite_items(args.suite, quality_per_lang=args.per_lang)
    store.root.mkdir(parents=True, exist_ok=True)
    with store.log_path.open("a", encoding="utf-8") as log_file:
        async with open_real_harness(
            run_settings,
            stop_after_guard=args.suite == "safety",
            max_generate=gen_left,
            max_decide=dec_left,
            log_file=log_file,
        ) as harness:
            policy = harness.retry_policy
            return await run_items(
                harness,
                store,
                args.suite,
                items,
                _options(args),
                log=_out,
                retries=lambda: len(policy.retries) if policy else 0,
            )


async def _run_judge(settings: Settings, store: Store, args: argparse.Namespace) -> RunSummary:
    from app.limits.spend import MemorySpendMeter
    from app.llm.gemini_provider import GeminiProvider

    gen_left, dec_left = _caps(store, args)
    inner = GeminiProvider(
        settings, spend=MemorySpendMeter(settings.daily_spend_cap_usd), policy=CountingRetryPolicy()
    )
    llm = CountingProvider(inner, tier=settings.gemini_tier, max_generate=gen_left, max_decide=dec_left)
    try:
        if args.suite == "judge-refusal":
            return await run_refusal_judge(llm, store, _options(args), tier=settings.gemini_tier, log=_out)
        return await run_judge(llm, store, _options(args), tier=settings.gemini_tier, log=_out)
    finally:
        await llm.aclose()


def cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = Store(settings.data_root / "reports")
    if args.suite in EMBEDDING_SUITES and not args.skip_ram_check:
        free = free_ram_gb()
        if free is not None and free < args.min_free_gb:
            _out(f"refusing to start: {free:.1f} GB free RAM < {args.min_free_gb} GB (embedding model)")
            return 3
    runner = _run_judge if args.suite.startswith("judge") else _run_suite
    summary = asyncio.run(runner(settings, store, args))
    store.add_run(summary.to_dict())
    write_metrics(store, free_tier=settings.is_free_tier)
    _out(f"run {summary.suite}: {summary.to_dict()}")
    _out(_status(store))
    return 0


def _status(store: Store) -> str:
    led = store.ledger()
    lines = [
        f"model calls used: generate={led.get('generate', 0)} decide={led.get('decide', 0)} "
        f"retries={led.get('retries', 0)}"
    ]
    lines += [f"  {k}: {v}" for k, v in sorted(dict(led.get("by_model", {})).items())]
    for suite in SUITES:
        results = store.results(suite)
        answered = sum(1 for r in results if is_answered(r.last))
        lines.append(f"cache {suite}: {len(results)} items, {answered} answered")
    return "\n".join(lines)


def cmd_report(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = Store(settings.data_root / "reports")
    records = write_metrics(store, free_tier=settings.is_free_tier)
    for r in records:
        labels = ",".join(f"{k}={v}" for k, v in r["labels"].items())
        _out(f"{r['metric']:<44} {r['value']:<10g} n={r['sample_size']:<5} {labels}")
    _out(f"wrote {len(records)} records to {store.metrics_path}")
    return 0


def cmd_failures(args: argparse.Namespace) -> int:
    from evals.p4.failures import all_failures
    from evals.p4.runner import SUITE_ORDER, verdict_pairs

    store = Store(get_settings().data_root / "reports")
    by_suite = {s: store.results(s) for s in SUITE_ORDER}
    for line in all_failures(by_suite, verdict_pairs(store)):
        _out(line)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    _out(_status(Store(get_settings().data_root / "reports")))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one suite (resumable)")
    run.add_argument("--suite", required=True, choices=[*SUITES, "judge", "judge-refusal"])
    run.add_argument(
        "--limit", type=int, default=None, help="first N items of the suite (round-robin by lang)"
    )
    run.add_argument("--per-lang", type=int, default=DEFAULT_QUALITY_PER_LANG, help="quality sample per lang")
    run.add_argument("--pace", type=float, default=None, help="seconds between items")
    run.add_argument("--max-generate", type=int, default=DEFAULT_MAX_GENERATE, help="cumulative cap")
    run.add_argument("--max-decide", type=int, default=DEFAULT_MAX_DECIDE, help="cumulative cap")
    run.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB)
    run.add_argument("--skip-ram-check", action="store_true")
    run.set_defaults(func=cmd_run)
    sub.add_parser("report", help="rewrite the metric records from the cache").set_defaults(func=cmd_report)
    sub.add_parser("status", help="cache counts and calls used").set_defaults(func=cmd_status)
    sub.add_parser("failures", help="list failing items per metric").set_defaults(func=cmd_failures)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: Any = args.func(args)
    return int(result)


__all__ = ["build_parser", "free_ram_gb", "main"]
