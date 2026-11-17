"""python -m data_pipeline fetch|parse|run --source <id> | --wave <n>, and python -m data_pipeline report"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence

import structlog

from data_pipeline import catalog
from data_pipeline.paths import default_paths
from data_pipeline.registry import load_registry


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING, stream=sys.stderr, format="%(message)s"
    )
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO if verbose else logging.WARNING)
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m data_pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "parse", "run"):
        cmd = sub.add_parser(name, help=f"{name} one source or a wave")
        target = cmd.add_mutually_exclusive_group(required=True)
        target.add_argument("--source", help="source id from the registry")
        target.add_argument("--wave", type=int, help="every active source of this wave that has a module")
        cmd.add_argument(
            "--limit", type=int, default=None, help="cap documents/pages (smoke runs; no ready marker)"
        )
        cmd.add_argument("--rps", type=float, default=None, help="requests per second per host (default 1)")
        cmd.add_argument("-v", "--verbose", action="store_true")
    report = sub.add_parser("report", help="write reports/data_gates.json, audit sample and attribution")
    report.add_argument("--audit-size", type=int, default=200)
    report.add_argument("-v", "--verbose", action="store_true")
    return parser


def _targets(args: argparse.Namespace) -> list[str]:
    if args.source:
        return [args.source]
    return catalog.sources_for_wave(args.wave, load_registry())


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _configure_logging(args.verbose)
    paths = default_paths().ensure()
    if args.command == "report":
        from data_pipeline.report import write_reports

        gates = write_reports(paths, audit_size=args.audit_size)
        sys.stdout.write(f"wrote {paths.reports / 'data_gates.json'} ({len(gates['per_source'])} sources)\n")
        return 0
    status = 0
    for source_id in _targets(args):
        try:
            if args.command in ("fetch", "run"):
                asyncio.run(catalog.run_fetch(source_id, paths, limit=args.limit, rps=args.rps))
            if args.command in ("parse", "run"):
                report = catalog.run_parse(source_id, paths, limit=args.limit)
                sys.stdout.write(
                    f"{source_id}: parsed={report.parsed} kept={report.kept} quarantined={report.quarantined} "  # noqa: E501
                    f"dropped={report.dropped}\n"
                )
        except Exception as exc:
            sys.stderr.write(f"{source_id}: FAILED {type(exc).__name__}: {exc}\n")
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
