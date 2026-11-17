"""Deterministic, lexicon-only safety evaluation over evals/safety/sets (no network, no model call).

Every user turn of an item (its history, then the current message) goes through the engine's own
deterministic path: process_ingress (sanitise, cap, redact) then GuardRouter.precheck (risk lexicon +
injection heuristics with the ingress smuggling flags). An item's detected kinds are the union over its
turns, because the engine prechecks every message on arrival and safety flags are sticky for the session.

  python -m evals.safety.lexicon_eval [--out PATH] [--no-write] [--show-failures {none,tune,all}]

Writes metric records (evals/gates_eval.py format, source "lexicon_only") to
{data_root}/reports/engine-guardrails.metrics.json. Failures are listed for the tune split only by default:
held-out items are reported as numbers and are never inspected one by one while tuning the lexicons.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.guardrails.guard_prompts import load_guard_prompts
from app.guardrails.ingress import process_ingress
from app.guardrails.lexicon import LexiconSettings, load_lexicon
from app.guardrails.router import GuardRouter
from app.guardrails.safety_config import load_safety_config
from core.config import get_settings
from core.errors import InvalidInput
from evals.fakes.fake_llm import FakeLLMProvider
from evals.safety.sets import (
    HARD_NEGATIVE,
    HELDOUT,
    INJECTION,
    LANGS,
    RISK_CATEGORIES,
    SETS_DIR,
    TUNE,
    SafetyItem,
    SetFormatError,
    load_heldout,
    load_sets,
    split_of,
    write_json_atomic,
)

SOURCE = "lexicon_only"
METRICS_FILE = "engine-guardrails.metrics.json"
EVAL_TODAY = date(2026, 1, 1)  # fixed "today" for date redaction: results must not depend on the clock
ALL = "all"
SPLITS: tuple[str, ...] = (ALL, TUNE, HELDOUT)
SAFETY_KINDS: frozenset[str] = frozenset(RISK_CATEGORIES)
GATE_KINDS: tuple[str, ...] = RISK_CATEGORIES  # emergency_detected / self_harm_detected are release gates
INGRESS_REJECTED = "ingress_rejected"  # marker kind: the engine would have refused the message at ingress
_TEXT_PREVIEW = 110

ItemDetector = Callable[[SafetyItem], frozenset[str]]


@dataclass(frozen=True)
class ItemResult:
    item: SafetyItem
    split: str
    detected: frozenset[str]

    @property
    def ok(self) -> bool:
        """Positive: every lexicon-detectable expected kind fired. Hard negative: no safety/injection kind."""
        if self.item.category == HARD_NEGATIVE:
            return not (self.detected & (SAFETY_KINDS | {INJECTION}))
        wanted = self.item.expected_kinds & (SAFETY_KINDS | {INJECTION})
        return wanted <= self.detected


@dataclass(frozen=True)
class Rate:
    hits: int
    n: int

    @property
    def value(self) -> float:
        return self.hits / self.n if self.n else 0.0


class Detector:
    """The engine's deterministic precheck, turn by turn (built as app/pipeline/factory.py builds it)."""

    def __init__(self, router: GuardRouter, *, max_chars: int) -> None:
        self._router = router
        self._max_chars = max_chars

    @classmethod
    def from_config(cls, *, max_chars: int | None = None) -> Detector:
        safety = load_safety_config()
        lexicon = load_lexicon(settings=LexiconSettings(fuzzy_min_term_chars=safety.fuzzy_min_term_chars))
        router = GuardRouter(FakeLLMProvider(), lexicon, load_guard_prompts(), safety)
        return cls(router, max_chars=max_chars or get_settings().max_message_chars)

    def detect_turn(self, text: str) -> frozenset[str]:
        try:
            message = process_ingress(text, max_chars=self._max_chars, today=EVAL_TODAY)
        except InvalidInput:
            return frozenset({INGRESS_REJECTED})
        pre = self._router.precheck(message.text, message.sanitize_flags)
        return frozenset(s.kind.value for s in pre.signals)

    def __call__(self, item: SafetyItem) -> frozenset[str]:
        return frozenset().union(*(self.detect_turn(turn) for turn in item.turns))


def evaluate_items(
    items: Iterable[SafetyItem], heldout: frozenset[str], detect: ItemDetector
) -> tuple[ItemResult, ...]:
    return tuple(ItemResult(item, split_of(item, heldout), detect(item)) for item in items)


# ---- metrics ------------------------------------------------------------------------------------------
def subset(results: Iterable[ItemResult], *, lang: str | None = None, split: str = ALL) -> list[ItemResult]:
    return [
        r for r in results if (lang is None or r.item.lang == lang) and (split == ALL or r.split == split)
    ]


def recall(results: Iterable[ItemResult], kind: str) -> Rate:
    positives = [r for r in results if kind in r.item.expected_kinds]
    return Rate(sum(kind in r.detected for r in positives), len(positives))


def false_positive_rate(results: Iterable[ItemResult], kinds: frozenset[str] = SAFETY_KINDS) -> Rate:
    negatives = [r for r in results if r.item.category == HARD_NEGATIVE]
    return Rate(sum(bool(r.detected & kinds) for r in negatives), len(negatives))


def _record(metric: str, value: float, labels: dict[str, str], n: int, measured_at: str) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": round(value, 4),
        "labels": labels,
        "sample_size": n,
        "source": SOURCE,
        "measured_at": measured_at,
        "free_tier": False,  # deterministic, no API call involved
    }


def _lang_records(results: Sequence[ItemResult], lang: str, measured_at: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    full = subset(results, lang=lang)
    for kind in GATE_KINDS:  # count form, full set: what the safety.* gates read (294 of 300 -> as a rate)
        rate = recall(full, kind)
        records.append(
            _record(f"{kind}_detected", rate.hits, {"lang": lang, "split": ALL}, rate.n, measured_at)
        )
    for split in SPLITS:
        part = subset(results, lang=lang, split=split)
        for kind in (*RISK_CATEGORIES, INJECTION):
            rate = recall(part, kind)
            labels = {"lang": lang, "kind": kind, "split": split}
            records.append(_record("lexicon_recall", rate.value, labels, rate.n, measured_at))
        for metric, rate in (
            ("hard_negative_false_positive_rate", false_positive_rate(part)),
            ("injection_detection_rate", recall(part, INJECTION)),
            ("injection_false_positive_rate", false_positive_rate(part, frozenset({INJECTION}))),
        ):
            records.append(_record(metric, rate.value, {"lang": lang, "split": split}, rate.n, measured_at))
    return records


def _variety_records(results: Sequence[ItemResult], measured_at: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    varieties = sorted({r.item.variety for r in results if r.item.lang == "ar"})
    for variety in varieties:
        part = [r for r in results if r.item.lang == "ar" and r.item.variety == variety]
        for kind in ("emergency", "self_harm"):
            rate = recall(part, kind)
            if rate.n:
                labels = {"lang": "ar", "variety": variety, "kind": kind, "split": ALL}
                records.append(_record("lexicon_recall_by_variety", rate.value, labels, rate.n, measured_at))
    return records


def build_records(results: Sequence[ItemResult], measured_at: str) -> list[dict[str, Any]]:
    langs = [lang for lang in LANGS if any(r.item.lang == lang for r in results)]
    records = [rec for lang in langs for rec in _lang_records(results, lang, measured_at)]
    return records + _variety_records(results, measured_at)


# ---- reporting ------------------------------------------------------------------------------------------
def _pct(rate: Rate) -> str:
    return f"{rate.hits}/{rate.n} {100 * rate.value:5.1f}%" if rate.n else "-"


def render_summary(results: Sequence[ItemResult]) -> str:
    head = ["lang", "split", *RISK_CATEGORIES, INJECTION, "neg_fp", "neg_inj_fp"]
    rows = [head]
    for lang in LANGS:
        for split in SPLITS:
            part = subset(results, lang=lang, split=split)
            if not part:
                continue
            cells = [_pct(recall(part, kind)) for kind in (*RISK_CATEGORIES, INJECTION)]
            fps = [_pct(false_positive_rate(part)), _pct(false_positive_rate(part, frozenset({INJECTION})))]
            rows.append([lang, split, *cells, *fps])
    widths = [max(len(row[i]) for row in rows) for i in range(len(head))]
    return "\n".join("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)) for row in rows)


def render_failures(results: Sequence[ItemResult], show: str) -> str:
    if show == "none":
        return ""
    lines = []
    for r in results:
        if r.ok or (show == TUNE and r.split != TUNE):
            continue
        expected = ",".join(sorted(r.item.expected_kinds)) or "-"
        detected = ",".join(sorted(r.detected)) or "-"
        preview = (
            r.item.text.encode("unicode_escape").decode("ascii")
            if not r.item.text.isprintable()
            else r.item.text
        )
        lines.append(f"{r.item.id:<16} want={expected:<28} got={detected:<28} {preview[:_TEXT_PREVIEW]}")
    return "\n".join(lines)


def default_out() -> Path:
    return get_settings().data_root / "reports" / METRICS_FILE


def console_safe(stream: Any) -> None:
    """Escape what the console cannot encode: an Arabic failure preview on a cp1252 Windows console used to
    raise UnicodeEncodeError before the metric records were written."""
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    console_safe(sys.stdout)
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sets", type=Path, default=SETS_DIR)
    parser.add_argument("--out", type=Path, default=None, help=f"default: <data_root>/reports/{METRICS_FILE}")
    parser.add_argument("--no-write", action="store_true", help="print only, do not write metric records")
    parser.add_argument("--show-failures", choices=("none", TUNE, ALL), default=TUNE)
    args = parser.parse_args(argv)
    try:
        items = load_sets(args.sets)
        heldout = load_heldout(args.sets)
    except SetFormatError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    results = evaluate_items(items, heldout, Detector.from_config())
    sys.stdout.write(render_summary(results) + "\n")
    failures = render_failures(results, args.show_failures)
    if failures:
        sys.stdout.write(f"\nfailures ({args.show_failures} split):\n{failures}\n")
    if not args.no_write:
        out = args.out or default_out()
        measured_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_json_atomic(out, build_records(results, measured_at))
        sys.stdout.write(f"\nwrote {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
