"""P4 integration evaluation on the real pipeline (real Gemini provider, live corpus, real guardrails).

  python -m evals.p4 run --suite safety|quality|dose|refusal|latency|judge|judge-refusal [--limit N]
                         [--per-lang N] [--ids ID,ID --replace] [--judge-model ID]
  python -m evals.p4 report      # recompute {data_root}/reports/p4.metrics.json from the cache
  python -m evals.p4 status      # cache counts and model calls used so far
  python -m evals.p4 failures    # failing items per metric (ids, excerpts)
  python -m evals.p4 causes      # why answerable quality items were not answered (+ contended ids)
  python -m evals.p4 stages      # per-stage latency table (latency suite, else quality)

The call budget is cumulative over every run (ledger in {data_root}/reports/p4/ledger.json): a run stops
before the totals pass --max-generate / --max-decide. Runs that load the local embedding model (every suite
except safety and judge) refuse to start with less than --min-free-gb of free RAM. The latency suite refuses
to start while another eval or load-test process runs on this machine (it would share the Gemini quota).
`--ids ... --replace` archives the cached results of those items (reports/p4/archive/) and runs them again.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import os
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
from evals.p4.store import Store, utc_now

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
QUIET_SUITES = frozenset({"latency"})
# module runs that share the Gemini quota or the CPU (shell wrappers and `python -c` helpers are not runs)
BUSY_MARKERS = ("-m evals.p4", "-m evals.load", "-m evals.redteam", "evals.load.server", "locust")
BUSY_EXECUTABLES = ("python", "locust")


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


def busy_processes(markers: Sequence[str] = BUSY_MARKERS) -> list[str]:
    """Other Python / Locust processes on this machine that run an eval or a load test (this process and its
    ancestors, i.e. the venv launcher and the shell that started it, excluded): they would share the Gemini
    quota and the CPU with a latency measurement."""
    import psutil

    own = {os.getpid(), os.getppid()}
    with contextlib.suppress(psutil.Error, OSError):
        own |= {p.pid for p in psutil.Process().parents()}
    out = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            cmd = " ".join(proc.info.get("cmdline") or [])
        except (psutil.Error, OSError):
            continue
        if proc.info.get("pid") in own or not name.startswith(BUSY_EXECUTABLES):
            continue
        if any(m in cmd for m in markers):
            out.append(f"{proc.info.get('pid')}: {cmd[:160]}")
    return out


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
    items = select_items(suite_items(args.suite, quality_per_lang=args.per_lang), args.ids)
    if args.ids and args.replace:
        tag = "replaced-" + utc_now().replace(":", "")
        for item in items:
            if store.archive(args.suite, item.id, tag) is not None:
                _out(f"{item.id}: cached result archived ({tag})")
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


def select_items(items: Sequence[Any], ids: str | None) -> list[Any]:
    """The items named in `ids` (comma separated, suite order kept); every item when `ids` is empty."""
    if not ids:
        return list(items)
    wanted = {i.strip() for i in ids.split(",") if i.strip()}
    chosen = [i for i in items if i.id in wanted]
    unknown = wanted - {i.id for i in chosen}
    if unknown:
        raise SystemExit(f"unknown item ids: {sorted(unknown)}")
    return chosen


def _judge_provider(settings: Settings, judge_model: str | None) -> Any:
    """The Gemini provider; with `judge_model`, its JUDGE role served by that model (P4 substitute judge)."""
    from app.limits.spend import MemorySpendMeter
    from app.llm.gemini_provider import GeminiProvider
    from core.models import ModelRole, ModelSpec
    from evals.p4.judge import judge_spec

    spec = judge_spec(settings.gemini_tier, judge_model)

    class _JudgeProvider(GeminiProvider):
        def _spec(self, role: ModelRole) -> ModelSpec:
            return spec if role is ModelRole.JUDGE else super()._spec(role)

    meter = MemorySpendMeter(settings.daily_spend_cap_usd)
    return _JudgeProvider(settings, spend=meter, policy=CountingRetryPolicy())


async def _run_judge(settings: Settings, store: Store, args: argparse.Namespace) -> RunSummary:
    from core.models import ModelRole
    from evals.p4.judge import judge_model_id

    gen_left, dec_left = _caps(store, args)
    tier = settings.gemini_tier
    llm = CountingProvider(
        _judge_provider(settings, args.judge_model),
        tier=tier,
        max_generate=gen_left,
        max_decide=dec_left,
        model_ids={ModelRole.JUDGE: judge_model_id(tier, args.judge_model)},
    )
    model = args.judge_model
    try:
        if args.suite == "judge-refusal":
            return await run_refusal_judge(llm, store, _options(args), tier=tier, log=_out, judge_model=model)
        return await run_judge(llm, store, _options(args), tier=tier, log=_out, judge_model=model)
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
    if args.suite in QUIET_SUITES and not args.allow_busy:
        busy = busy_processes()
        if busy:
            _out("refusing to start: not a quiet window, other eval / load processes run:")
            for line in busy:
                _out(f"  {line}")
            return 4
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


def cmd_causes(args: argparse.Namespace) -> int:
    from evals.p4.diagnose import contended, diagnose, format_causes, load_turn_records, turn_id

    settings = get_settings()
    store = Store(settings.data_root / "reports")
    results = store.results(args.suite)
    records = load_turn_records(store.db_path, (turn_id(r.last) for r in results))
    missing: list[str] = []
    if not args.no_index_check:
        missing = asyncio.run(_missing_gold(settings, results))
    from evals.p4.items import load_quality_exclusions

    exclusions = load_quality_exclusions()
    for line in format_causes(diagnose(results, records, missing, exclusions), len(results)):
        _out(line)
    busy = [r.item.id for r in results if contended(r)]
    _out("")
    _out(f"contended (provider retries in the turn): {len(busy)}: {','.join(busy)}")
    return 0


async def _missing_gold(settings: Settings, results: Sequence[Any]) -> list[str]:
    from qdrant_client import AsyncQdrantClient

    from evals.p4.diagnose import missing_gold_chunks

    key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=key, timeout=30)
    try:
        return await missing_gold_chunks(client, settings.qdrant_alias, results)
    finally:
        await client.close()


def cmd_stages(args: argparse.Namespace) -> int:
    from evals.p4.stages import format_table, stage_table

    store = Store(get_settings().data_root / "reports")
    suite = args.suite or ("latency" if store.results("latency") else "quality")
    turns = [r.last for r in store.results(suite)]
    for mode in ("streamed", "verified"):
        for line in format_table(stage_table(turns, mode), f"{suite} / {mode}"):
            _out(line)
        _out("")
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
    run.add_argument("--ids", default=None, help="only these item ids (comma separated)")
    run.add_argument("--replace", action="store_true", help="with --ids: archive their cached results first")
    run.add_argument("--judge-model", default=None, help="judge suites: serve the JUDGE role by this model")
    run.add_argument("--allow-busy", action="store_true", help="latency: skip the quiet-window check")
    run.set_defaults(func=cmd_run)
    sub.add_parser("report", help="rewrite the metric records from the cache").set_defaults(func=cmd_report)
    sub.add_parser("status", help="cache counts and calls used").set_defaults(func=cmd_status)
    sub.add_parser("failures", help="list failing items per metric").set_defaults(func=cmd_failures)
    causes = sub.add_parser("causes", help="causes of not-answered answerable items")
    causes.add_argument("--suite", default="quality", choices=["quality", "latency"])
    causes.add_argument("--no-index-check", action="store_true", help="skip the gold-chunk check in Qdrant")
    causes.set_defaults(func=cmd_causes)
    stages = sub.add_parser("stages", help="per-stage latency table")
    stages.add_argument("--suite", default=None, choices=["quality", "dose", "latency"])
    stages.set_defaults(func=cmd_stages)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: Any = args.func(args)
    return int(result)


__all__ = ["build_parser", "busy_processes", "free_ram_gb", "main", "select_items"]
