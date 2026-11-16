"""Retrieval report files and the promotion gate.

reports/retrieval/<stamp>.json          full report (ablations, calibration, rerank decision, latency)
reports/retrieval/<stamp>.gates.json    that run's gate records (evals.run format, deliberately NOT named
                                        *.metrics.json: `python -m evals.run` reads every *.metrics.json and
                                        keeps the newest record per gate, so an offline run or an eval of a
                                        validation collection would otherwise replace the live numbers)
reports/rag.metrics.json                gate records of the LIVE collection: written only by an online eval
                                        of the alias target (publish_metrics)

Promotion (`python -m rag promote`) requires the collection's latest report to have every rag.* gate PASS or
PROVISIONAL (free tier). Offline reports (no query embeddings) cannot promote: their recall and abstention
records are missing on purpose, because sparse-only numbers do not describe the production retriever.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from evals.gates_eval import GateResult, MetricRecord, Verdict, evaluate
from rag.fileio import atomic_write_json, read_json
from rag.paths import GATES_PATH

REPORT_SCHEMA = "ausculta.retrieval_report.v1"
RAG_GATE_PREFIX = "rag."
SOURCE = "rag.eval"
RUN_RECORDS_SUFFIX = ".gates.json"


def stamp(when: datetime) -> str:
    return when.strftime("%Y%m%dT%H%M%SZ")


def record(
    metric: str, value: float, when: datetime, *, free_tier: bool, n: int | None = None, **labels: str
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": round(float(value), 6),
        "labels": dict(labels),
        "sample_size": n,
        "source": SOURCE,
        "measured_at": when.isoformat(),
        "free_tier": free_tier,
    }


def gate_records(
    hybrid: Mapping[str, Any] | None,
    calibration: Mapping[str, Any] | None,
    latency_p95: tuple[float, int] | None,
    repeat_calls: int | None,
    when: datetime,
    *,
    free_tier: bool,
    collection: str,
) -> list[dict[str, Any]]:
    """Records for the rag.* gates. Recall comes from the production (hybrid) ablation, abstention from
    held-out calibration rates, latency from stage (b)."""
    out: list[dict[str, Any]] = []
    if hybrid is not None:
        for lang in ("en", "fr", "ar"):
            stats = hybrid["by_language"].get(lang, {})
            if "recall_at_20" in stats:
                n = int(stats["n_answerable"])
                out.append(
                    record("recall_at_20", stats["recall_at_20"], when, free_tier=free_tier, n=n, lang=lang)
                )
    if calibration is not None:
        held = calibration["held_out"]
        out.append(
            record(
                "abstain_rate_out_of_corpus", held["abstain_ooc"], when, free_tier=free_tier, n=held["n_ooc"]
            )
        )
        out.append(
            record(
                "abstain_rate_answerable",
                held["abstain_answerable"],
                when,
                free_tier=free_tier,
                n=held["n_answerable"],
            )
        )
    if latency_p95 is not None:
        out.append(
            record("retrieval_latency_p95_ms", latency_p95[0], when, free_tier=free_tier, n=latency_p95[1])
        )
    if repeat_calls is not None:
        out.append(record("repeat_embedding_calls_on_resume", repeat_calls, when, free_tier=free_tier))
    for rec in out:
        rec["labels"]["collection"] = collection
    return out


def load_rag_gates(path: Path = GATES_PATH) -> dict[str, Any]:
    gates = yaml.safe_load(path.read_text(encoding="utf-8"))["gates"]
    return {k: v for k, v in gates.items() if k.startswith(RAG_GATE_PREFIX)}


def evaluate_gates(records: Sequence[Mapping[str, Any]], gates: Mapping[str, Any]) -> list[GateResult]:
    return evaluate(gates, [MetricRecord.from_dict(r) for r in records])


def gate_rows(results: Sequence[GateResult]) -> list[dict[str, str]]:
    return [
        {"gate": r.gate, "verdict": r.verdict.value, "measured": r.measured, "detail": r.detail}
        for r in results
    ]


def write_report(reports_dir: Path, report: Mapping[str, Any], when: datetime) -> tuple[Path, Path]:
    base = reports_dir / stamp(when)
    full = atomic_write_json(base.with_suffix(".json"), dict(report))
    records = atomic_write_json(Path(f"{base}{RUN_RECORDS_SUFFIX}"), list(report.get("gate_records", [])))
    return full, records


def publish_metrics(path: Path, report: Mapping[str, Any]) -> Path:
    """Write the report's gate records as the live rag.* metrics. Only an online report qualifies: an offline
    report has no recall or abstention records and describes a stand-in retriever."""
    if report.get("mode") != "online":
        raise ValueError("only an online retrieval report can be published as the rag gate metrics")
    return atomic_write_json(path, list(report.get("gate_records", [])))


@dataclass(frozen=True)
class PromotionCheck:
    ok: bool
    report_path: Path | None
    gates: tuple[dict[str, str], ...]
    reason: str


def latest_report(reports_dir: Path, collection: str) -> tuple[Path, dict[str, Any]] | None:
    found: list[tuple[str, Path, dict[str, Any]]] = []
    for path in reports_dir.glob("*.json"):
        if path.name.endswith((".metrics.json", RUN_RECORDS_SUFFIX)):
            continue
        try:
            data = read_json(path)
        except (OSError, ValueError):
            continue
        if (
            isinstance(data, dict)
            and data.get("schema") == REPORT_SCHEMA
            and data.get("collection") == collection
        ):
            found.append((str(data.get("measured_at", "")), path, data))
    if not found:
        return None
    _, path, data = max(found, key=lambda t: t[0])
    return path, data


def promotion_check(
    reports_dir: Path, collection: str, gates: Mapping[str, Any] | None = None
) -> PromotionCheck:
    latest = latest_report(reports_dir, collection)
    if latest is None:
        return PromotionCheck(
            False, None, (), f"no retrieval report for {collection}; run `python -m rag eval`"
        )
    path, data = latest
    results = evaluate_gates(data.get("gate_records", []), gates if gates is not None else load_rag_gates())
    rows = tuple(gate_rows(results))
    bad = [r.gate for r in results if r.verdict in (Verdict.FAIL, Verdict.MISSING)]
    if bad:
        return PromotionCheck(False, path, rows, f"gates not met: {', '.join(bad)}")
    return PromotionCheck(True, path, rows, "all rag gates pass (or are provisional on the free tier)")
