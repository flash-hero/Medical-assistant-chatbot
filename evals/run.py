"""Evaluate release gates.

  python -m evals.run --gates evals/gates.yaml [--reports DIR] [--only rag.,safety.]
                      [--allow-missing] [--json OUT]

Collects every *.metrics.json under the reports directory (default {AUSCULTA_DATA_ROOT}/reports), evaluates
each gate and prints one line per gate. Exit code 1 on any FAIL (or MISSING unless --allow-missing).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from core.config import get_settings
from evals.gates_eval import GateResult, MetricRecord, Verdict, evaluate, exit_code

_MARK = {Verdict.PASS: "PASS ", Verdict.FAIL: "FAIL ", Verdict.PROVISIONAL: "PROV ", Verdict.MISSING: "MISS "}


def load_records(reports_dir: Path) -> list[MetricRecord]:
    records: list[MetricRecord] = []
    for path in sorted(reports_dir.rglob("*.metrics.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else [raw]
        records.extend(MetricRecord.from_dict(item) for item in items)
    return records


def render(results: list[GateResult]) -> str:
    width = max((len(r.gate) for r in results), default=10)
    lines = [f"{_MARK[r.verdict]} {r.gate:<{width}}  {r.measured:<18} {r.detail}" for r in results]
    counts = {v: sum(1 for r in results if r.verdict is v) for v in Verdict}
    lines.append(" | ".join(f"{v.value}: {n}" for v, n in counts.items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--gates", type=Path, default=Path("evals/gates.yaml"))
    parser.add_argument("--reports", type=Path, default=None)
    parser.add_argument("--only", default="", help="comma-separated gate-name prefixes")
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--json", type=Path, default=None, help="write results as JSON")
    args = parser.parse_args(argv)

    gates = yaml.safe_load(args.gates.read_text(encoding="utf-8"))["gates"]
    prefixes = tuple(p for p in args.only.split(",") if p)
    if prefixes:
        gates = {k: v for k, v in gates.items() if k.startswith(prefixes)}
    reports = args.reports or (get_settings().data_root / "reports")
    results = evaluate(gates, load_records(reports) if reports.exists() else [])
    sys.stdout.write(render(results) + "\n")
    if args.json:
        payload = [
            {"gate": r.gate, "verdict": r.verdict.value, "measured": r.measured, "detail": r.detail}
            for r in results
        ]
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return exit_code(results, allow_missing=args.allow_missing)


if __name__ == "__main__":
    raise SystemExit(main())
