"""Recorded quality exclusions (evals/p4/sets/quality_exclusions.jsonl): loading, metric and diagnosis."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.p4.diagnose import EXCLUDED_GOLD, diagnose
from evals.p4.items import (
    EXCLUSION_RULES,
    GOLD_DIR,
    EvalItem,
    ItemFormatError,
    base_id,
    load_quality_exclusions,
    quality_items,
)
from evals.p4.metrics import Ctx, answered_records
from evals.p4.results import ItemResult, TurnResult
from evals.retrieval.gold import load_gold

CTX = Ctx("2026-11-20T00:00:00Z", free_tier=True)
ABSTAIN = {"type": "answer", "text": "I can't answer.", "mode": "abstain", "intent": "medication"}
ANSWERED = {
    "type": "answer",
    "text": "A [1].",
    "mode": "streamed",
    "intent": "medical_info",
    "citations": [{"n": 1}],
}


def item(suite: str, iid: str, lang: str = "en") -> EvalItem:
    return EvalItem(suite, iid, lang, ("q",), "answerable")


def turn(payload: dict[str, object]) -> TurnResult:
    body = ({"type": "meta"}, payload, {"type": "done"})
    return TurnResult("m", 200, body, (0.0, 0.1, 0.2))


def result(it: EvalItem, t: TurnResult) -> ItemResult:
    return ItemResult(it, (t,), "2026-11-20T00:00:00Z")


def test_the_recorded_exclusions_name_answerable_pool_questions_with_a_rule() -> None:
    exclusions = load_quality_exclusions()
    assert exclusions, "the file exists and is not empty"
    pool = {base_id(i.id) for i in quality_items(60)}
    assert set(exclusions) <= pool
    answerable = {base_id(r.qid) for r in load_gold(GOLD_DIR) if r.answerable}
    assert set(exclusions) <= answerable
    assert all(v.split(":", 1)[0] in EXCLUSION_RULES for v in exclusions.values())


def test_excluded_items_leave_the_gated_rate_but_stay_in_the_all_items_record() -> None:
    results = [
        result(item("quality", "g100-P1-en"), turn(ANSWERED)),
        result(item("quality", "g100-P2-en"), turn(ABSTAIN)),
        result(item("quality", "g100-P3-fr", "fr"), turn(ABSTAIN)),
    ]
    recs = {r["metric"]: r for r in answered_records(results, CTX, {"g100-P2": "rule: reason"})}
    gated = recs["answered_rate_answerable"]
    assert (gated["value"], gated["sample_size"]) == (pytest.approx(0.5), 2)
    assert gated["labels"] == {"excluded_items": "1"}
    every = recs["answered_rate_answerable_all_items"]
    assert (every["value"], every["sample_size"]) == (pytest.approx(1 / 3), 3)


def test_no_exclusions_means_the_plain_rate() -> None:
    results = [result(item("quality", "g100-P1-en"), turn(ABSTAIN))]
    recs = {r["metric"]: r for r in answered_records(results, CTX, {})}
    assert recs["answered_rate_answerable"]["labels"] == {"excluded_items": "0"}


def test_the_diagnosis_names_the_exclusion_first() -> None:
    results = [result(item("quality", "g100-P2-ar", "ar"), turn(ABSTAIN))]
    diags = diagnose(results, {}, exclusions={"g100-P2": "medication_needs_drug_label: why"})
    assert [(d.cause, d.detail) for d in diags] == [(EXCLUDED_GOLD, "medication_needs_drug_label")]


@pytest.mark.parametrize(
    "line",
    [
        '{"base_id": "g1", "rule": "because", "reason": "a reason that is long enough"}',
        '{"base_id": "g1", "rule": "gold_not_in_index", "reason": "short"}',
        '{"base_id": "g1", "rule": "gold_not_in_index"}',
        "not json",
    ],
)
def test_malformed_exclusions_are_rejected(tmp_path: Path, line: str) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ItemFormatError):
        load_quality_exclusions(path)


def test_duplicate_exclusions_are_rejected(tmp_path: Path) -> None:
    line = '{"base_id": "g1", "rule": "gold_not_in_index", "reason": "the gold chunk is gone from the index"}'
    path = tmp_path / "x.jsonl"
    path.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(ItemFormatError):
        load_quality_exclusions(path)
