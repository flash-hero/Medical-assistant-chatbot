"""Failing items per P4 metric, for the report (`python -m evals.p4 failures`)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from evals.p4.judge import JudgeVerdict
from evals.p4.metrics import (
    SAFETY_EVENT_KINDS,
    citation_valid,
    dose_answers,
    forbidden_claims,
    is_answered,
    numeric_violations,
    safety_before_content,
    shown_texts,
)
from evals.p4.results import ItemResult
from evals.safety.sets import HARD_NEGATIVE

EXCERPT = 160


def _short(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= EXCERPT else flat[: EXCERPT - 1] + "..."


def safety_failures(results: Sequence[ItemResult]) -> Iterator[str]:
    for r in results:
        if r.item.category == HARD_NEGATIVE:
            fp = r.detected_kinds & SAFETY_EVENT_KINDS
            if fp:
                yield f"hard-negative FP {r.item.id} [{','.join(sorted(fp))}] {_short(r.item.turns[-1])}"
            continue
        for kind in sorted(r.item.expected_kinds & {"emergency", "self_harm"}):
            if kind not in r.detected_kinds:
                got = ",".join(sorted(r.detected_kinds)) or "none"
                yield f"missed {kind} {r.item.id} ({r.item.split}, got {got}) {_short(r.item.turns[-1])}"


def answer_failures(by_suite: Mapping[str, Sequence[ItemResult]]) -> Iterator[str]:
    for r in by_suite.get("quality", []):
        if not is_answered(r.last):
            yield f"not answered {r.item.id} mode={r.last.mode} intent={(r.last.answer or {}).get('intent')}"
    for suite in ("quality", "dose", "refusal"):
        for r in by_suite.get(suite, []):
            if is_answered(r.last) and not citation_valid(r.last):
                yield f"invalid citation {r.item.id}: {_short(str((r.last.answer or {}).get('text', '')))}"
    for turn in dose_answers(by_suite):
        for bad in numeric_violations(turn):
            yield f"numeric {turn.message[:60]!r}: {_short(bad)}"
    every = [r for results in by_suite.values() for r in results]
    for r in every:
        for i, t in enumerate(r.turns):
            if t.of_type("safety") and not safety_before_content(t):
                yield f"safety after content {r.item.id} turn {i}"


def refusal_failures(results: Sequence[ItemResult]) -> Iterator[str]:
    for r in results:
        for t in r.turns:
            for text in shown_texts(t):
                cats = forbidden_claims(text)
                if cats:
                    yield f"refusal {r.item.id} ({r.item.category}) {sorted(set(cats))}: {_short(text)}"


def judge_failures(pairs: Sequence[tuple[ItemResult, JudgeVerdict]]) -> Iterator[str]:
    for r, v in pairs:
        for label, sentence in zip(v.labels, v.sentences, strict=True):
            if label == "unsupported":
                yield f"unsupported {r.item.id}: {_short(sentence)}"


def all_failures(
    by_suite: Mapping[str, Sequence[ItemResult]], pairs: Sequence[tuple[ItemResult, JudgeVerdict]]
) -> Iterator[str]:
    yield from safety_failures(by_suite.get("safety", []))
    yield from answer_failures(by_suite)
    yield from refusal_failures(by_suite.get("refusal", []))
    yield from judge_failures(pairs)
