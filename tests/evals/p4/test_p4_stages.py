"""Per-stage latency split (evals/p4/stages.py) and the latency records built from it."""

from __future__ import annotations

from typing import Any

import pytest

from evals.p4.items import EvalItem
from evals.p4.metrics import Ctx, all_records
from evals.p4.results import ItemResult, TurnResult
from evals.p4.stages import format_table, stage_table, turn_stages

CTX = Ctx("2026-11-20T00:00:00Z", free_tier=True)
RETRIEVAL = {"start_s": 1.2, "end_s": 1.3, "timings_ms": {"embed_ms": 30.0}, "confident": True}


def call(
    role: str, start: float, end: float, first: float | None = None, kind: str = "generate"
) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind, "role": role, "model_id": "m", "outcome": "ok", "start_s": start}
    out["end_s"] = end
    if first is not None:
        out["first_s"] = first
    return out


def streamed_turn(*, delta_at: float = 2.5, retrievals: Any = (RETRIEVAL,)) -> TurnResult:
    payloads = (
        {"type": "meta"},
        {"type": "delta", "text": "A."},
        {"type": "answer", "mode": "streamed", "text": "A. [1]"},
        {"type": "done"},
    )
    calls = (
        call("guard", 0.1, 0.5, kind="decide"),
        call("rewrite", 0.5, 1.2),
        call("answer", 1.35, 3.0, first=2.0),
        call("verify", 3.0, 3.4, kind="decide"),
    )
    return TurnResult(
        "m", 200, payloads, (0.0, delta_at, 3.5, 3.6), calls=calls, retrievals=tuple(retrievals)
    )


def verified_turn() -> TurnResult:
    payloads = ({"type": "meta"}, {"type": "answer", "mode": "verified", "text": "A. [1]"}, {"type": "done"})
    calls = (
        call("guard", 0.1, 0.5, kind="decide"),
        call("answer", 0.65, 2.65),
        call("verify", 2.7, 3.2, kind="decide"),
    )
    retrieval = {**RETRIEVAL, "start_s": 0.5, "end_s": 0.6}
    return TurnResult("m", 200, payloads, (0.0, 3.4, 3.5), calls=calls, retrievals=(retrieval,))


def test_streamed_turn_splits_ttft_into_its_stages() -> None:
    split = turn_stages(streamed_turn())
    assert split is not None
    assert split.mode == "streamed"
    assert split.total_s == 2.5
    s = split.stages
    assert s["guard"] == pytest.approx(0.4)
    assert s["rewrite"] == pytest.approx(0.7)
    assert s["retrieval"] == pytest.approx(0.1)
    assert s["embed"] == pytest.approx(0.03)
    assert s["answer_ttft"] == pytest.approx(0.65)  # stream opened at 1.35, first chunk at 2.0
    assert s["first_sentence"] == pytest.approx(0.5)  # first chunk 2.0 -> first delta 2.5
    path = s["guard"] + s["rewrite"] + s["retrieval"] + s["answer_ttft"] + s["first_sentence"]
    assert s["overhead"] == pytest.approx(2.5 - path)


def test_verified_turn_splits_the_answer_time() -> None:
    split = turn_stages(verified_turn())
    assert split is not None
    assert split.mode == "verified"
    assert split.stages["rewrite"] == 0.0  # standalone English: no rewrite call
    assert split.stages["generation"] == pytest.approx(2.0)
    assert split.stages["verify"] == pytest.approx(0.5)
    assert split.stages["overhead"] == pytest.approx(3.4 - (0.4 + 0.1 + 2.0 + 0.5))
    assert "answer_ttft" not in split.stages


def test_turns_without_times_or_answers_have_no_split() -> None:
    assert turn_stages(streamed_turn(retrievals=())) is None  # cached before the timing fields existed
    abstain = TurnResult("m", 200, ({"type": "answer", "mode": "abstain", "text": "No."},), (1.0,))
    assert turn_stages(abstain) is None
    untimed = streamed_turn()
    untimed = TurnResult(
        untimed.message,
        200,
        untimed.payloads,
        untimed.times_s,
        calls=tuple({k: v for k, v in c.items() if k != "end_s"} for c in untimed.calls),
        retrievals=untimed.retrievals,
    )
    assert turn_stages(untimed) is None


def test_stage_table_aggregates_by_mode_and_labels_owners() -> None:
    turns = [streamed_turn(delta_at=2.5), streamed_turn(delta_at=3.5), verified_turn()]
    rows = {r.stage: r for r in stage_table(turns, "streamed")}
    assert rows["total"].n == 2
    assert rows["total"].p50 == pytest.approx(3.0)
    assert rows["guard"].owner == "gemini"
    assert rows["retrieval"].owner == "ours"
    assert rows["first_sentence"].owner == "ours"
    assert stage_table(turns, "verified")[0].n == 1
    assert stage_table([], "streamed") == []
    lines = format_table(stage_table(turns, "streamed"), "title")
    assert lines[0] == "title"
    assert any(line.startswith("answer_ttft") for line in lines)


def _result(suite: str, iid: str, turn: TurnResult) -> ItemResult:
    return ItemResult(EvalItem(suite, iid, "en", ("q",)), (turn,), "2026-11-20T00:00:00Z")


def test_quiet_latency_suite_is_gated_and_quality_is_a_breakdown() -> None:
    by_suite = {
        "quality": [_result("quality", "q1", streamed_turn(delta_at=9.0))],
        "latency": [_result("latency", "q1", streamed_turn(delta_at=2.5))],
    }
    recs = {(r["metric"], r["labels"].get("stage")): r for r in all_records(by_suite, [], CTX)}
    gated = recs[("ttft_p95_s_streamed", None)]
    assert gated["value"] == 2.5
    assert gated["labels"] == {"suite": "latency", "window": "quiet"}
    assert recs[("ttft_p95_s_streamed_quality", None)]["value"] == 9.0
    assert recs[("latency_stage_p95_s", "guard")]["labels"]["owner"] == "gemini"
    assert recs[("latency_stage_p50_s", "total")]["value"] == 2.5


def test_quality_turns_are_gated_without_a_quiet_rerun() -> None:
    recs = {
        r["metric"]: r for r in all_records({"quality": [_result("quality", "q1", streamed_turn())]}, [], CTX)
    }
    assert recs["ttft_p95_s_streamed"]["labels"] == {"suite": "quality", "window": "shared"}
    assert "ttft_p95_s_streamed_quality" not in recs
