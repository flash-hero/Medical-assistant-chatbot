"""Pure gate evaluation: gates.yaml specs + metric records -> verdicts.

Metric record (one JSON object; files named *.metrics.json under {data_root}/reports/, each holding a list):
  {"metric": "recall_at_20", "value": 0.93, "labels": {"lang": "en"}, "sample_size": 300,
   "source": "rag.eval", "measured_at": "2026-11-15T20:00:00Z", "free_tier": true}

Verdicts: PASS, FAIL, PROVISIONAL (passes, but on the free tier or a reduced sample, for a gate
that allows it),
MISSING (no record). Only PASS counts as passed; the CLI exits non-zero on FAIL or MISSING.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": lambda a, b: abs(a - b) < 1e-12,
}
LANGS = ("en", "fr", "ar")
SELECTOR_KEYS = ("lang", "scope", "users")  # gate keys that must match record labels
CONTROL_KEYS = {
    "metric",
    "op",
    "value",
    "of",
    "sample",
    "provisional_on_free_tier",
    "per_lang",
    "browsers",
    "duration_min",
    *SELECTOR_KEYS,
}


class Verdict(StrEnum):
    PASS = "PASS"  # noqa: S105 - verdict label, not a password
    FAIL = "FAIL"
    PROVISIONAL = "PROVISIONAL"
    MISSING = "MISSING"


@dataclass(frozen=True)
class MetricRecord:
    metric: str
    value: float
    labels: Mapping[str, str] = field(default_factory=dict)
    sample_size: int | None = None
    source: str = ""
    measured_at: str = ""
    free_tier: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> MetricRecord:
        return cls(
            metric=str(raw["metric"]),
            value=float(raw["value"]),
            labels={str(k): str(v) for k, v in dict(raw.get("labels") or {}).items()},
            sample_size=int(raw["sample_size"]) if raw.get("sample_size") is not None else None,
            source=str(raw.get("source", "")),
            measured_at=str(raw.get("measured_at", "")),
            free_tier=bool(raw.get("free_tier", False)),
        )


@dataclass(frozen=True)
class GateResult:
    gate: str
    verdict: Verdict
    detail: str
    measured: str = ""


def _matches(record: MetricRecord, spec: Mapping[str, Any], lang: str | None) -> bool:
    if record.metric != spec["metric"]:
        return False
    for key in SELECTOR_KEYS:
        wanted = lang if key == "lang" and lang else spec.get(key)
        if wanted is not None and record.labels.get(key) != str(wanted):
            return False
    return True


def _latest(records: Iterable[MetricRecord]) -> MetricRecord | None:
    ordered = sorted(records, key=lambda r: r.measured_at)
    return ordered[-1] if ordered else None


def _evaluate_one(name: str, spec: Mapping[str, Any], rec: MetricRecord | None) -> GateResult:
    if rec is None:
        return GateResult(name, Verdict.MISSING, "no metric record")
    op = OPS[str(spec["op"])]
    target = float(spec["value"])
    value = rec.value
    reduced = False
    of = spec.get("of") or spec.get("sample")
    if spec.get("of") is not None:
        of_n = int(spec["of"])
        n = rec.sample_size or of_n
        reduced = n < of_n
        if target > 1 and n != of_n:
            # count gate ("294 of 300") measured on a different sample size: compare as rates
            value, target = value / n, target / of_n
    elif of is not None and rec.sample_size is not None and rec.sample_size < int(of):
        reduced = True
    measured = f"{rec.value:g}" + (f" (n={rec.sample_size})" if rec.sample_size is not None else "")
    if not op(value, target):
        return GateResult(name, Verdict.FAIL, f"{value:g} {spec['op']} {target:g} is false", measured)
    provisional_ok = bool(spec.get("provisional_on_free_tier"))
    if reduced and not provisional_ok:
        return GateResult(name, Verdict.FAIL, f"sample {rec.sample_size} below required {of}", measured)
    if provisional_ok and (rec.free_tier or reduced):
        why = "free tier" if rec.free_tier else f"reduced sample n={rec.sample_size}"
        return GateResult(name, Verdict.PROVISIONAL, f"meets target on {why}", measured)
    return GateResult(name, Verdict.PASS, f"{value:g} {spec['op']} {target:g}", measured)


def evaluate(gates: Mapping[str, Mapping[str, Any]], records: Iterable[MetricRecord]) -> list[GateResult]:
    recs = list(records)
    results: list[GateResult] = []
    for name, spec in gates.items():
        langs: tuple[str | None, ...] = LANGS if spec.get("per_lang") else (None,)
        for lang in langs:
            label = f"{name}[{lang}]" if lang else name
            rec = _latest(r for r in recs if _matches(r, spec, lang))
            results.append(_evaluate_one(label, spec, rec))
    return results


def exit_code(results: Iterable[GateResult], *, allow_missing: bool = False) -> int:
    bad = {Verdict.FAIL} | (set() if allow_missing else {Verdict.MISSING})
    return 1 if any(r.verdict in bad for r in results) else 0
