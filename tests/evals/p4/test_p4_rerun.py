"""Call / retrieval timing, the substitute judge, item re-runs and the quiet-window check (P4 open items)."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from contextlib import aclosing
from pathlib import Path
from typing import Any

import pytest

from core.models import ModelRole, model_for
from core.ports import DecisionQuestion, GenerationRequest
from core.schemas.chat import RetrievalQuery
from evals.fakes.fake_llm import FakeLLMProvider
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.scripted import role_responder, scripted_provider
from evals.p4 import cli
from evals.p4.items import EvalItem
from evals.p4.judge import OVERRIDE_TIMEOUT_S, check_independent, judge_model_id, judge_spec
from evals.p4.provider import CANCELLED, CountingProvider
from evals.p4.retrievers import RecordingRetriever
from evals.p4.runner import RunOptions, run_items, run_judge
from evals.p4.stages import turn_stages
from evals.p4.store import Store

Q = {"q": DecisionQuestion(kind="noul", instructions="yes?")}
MEDICAL = EvalItem("quality", "q-en-1", "en", ("What is a fever and how long does it usually last?",))


async def _no_sleep(_: float) -> None:
    return None


def _quiet(_: str) -> None:
    return None


def _judge_responder(label: str) -> Callable[[Any], str]:
    answer = role_responder()

    def respond(request: Any) -> str:
        if request.role is ModelRole.JUDGE:
            return json.dumps(dict.fromkeys(request.json_schema["properties"], label))
        return answer(request)

    return respond


# ---- timing ----------------------------------------------------------------------------------------------
async def test_calls_record_start_end_and_first_chunk() -> None:
    llm = CountingProvider(FakeLLMProvider(latency_s=0.01))
    await llm.decide(ModelRole.GUARD, "x", Q)
    async with aclosing(llm.stream(GenerationRequest(ModelRole.ANSWER, "s", "p"))) as chunks:  # type: ignore[type-var]
        async for _ in chunks:
            pass
    guard, answer = llm.calls
    assert 0 < guard.started <= guard.ended
    assert guard.first == 0.0
    assert answer.started <= answer.first <= answer.ended
    timed = answer.to_dict(base=guard.started)
    assert timed["start_s"] >= 0.0
    assert timed["start_s"] <= timed["first_s"] <= timed["end_s"]
    assert "start_s" not in answer.to_dict()


async def test_a_call_cancelled_by_the_callers_timeout_is_recorded_as_cancelled() -> None:
    llm = CountingProvider(FakeLLMProvider(latency_s=5.0))
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await llm.generate(GenerationRequest(ModelRole.REWRITE, "s", "p"))
    (rewrite,) = llm.calls
    assert rewrite.outcome == CANCELLED
    assert rewrite.ended >= rewrite.started
    assert llm.count("generate") == 1  # it used quota


async def test_model_ids_override_names_the_serving_model() -> None:
    llm = CountingProvider(FakeLLMProvider(), model_ids={ModelRole.JUDGE: "judge-substitute"})
    await llm.generate(GenerationRequest(ModelRole.JUDGE, "s", "p"))
    await llm.generate(GenerationRequest(ModelRole.ANSWER, "s", "p"))
    assert [c.model_id for c in llm.calls] == ["judge-substitute", model_for(ModelRole.ANSWER).model_id]


async def test_recording_retriever_keeps_query_verdict_and_span() -> None:
    rec = RecordingRetriever(FakeRetriever())
    query = RetrievalQuery(standalone_query="fever in adults", search_queries=("fever",), language="en")
    await rec.retrieve(query)
    (row,) = rec.turn_record(base=0.0)
    assert row["standalone_query"] == "fever in adults"
    assert row["search_queries"] == ["fever"]
    assert 0.0 < row["start_s"] <= row["end_s"]
    assert isinstance(row["confident"], bool)
    rec.begin_turn()
    assert rec.turn_record(base=0.0) == ()


async def test_harness_turns_carry_timed_calls_and_retrievals(
    harness_factory: Callable[..., Any], store: Store
) -> None:
    async with harness_factory() as harness:
        await run_items(harness, store, "quality", [MEDICAL], RunOptions(), sleep=_no_sleep, log=_quiet)
    result = store.get("quality", MEDICAL.id)
    assert result is not None
    turn = result.last
    assert all("start_s" in c and "end_s" in c for c in turn.calls)
    (ret,) = turn.retrievals
    assert ret["standalone_query"] == MEDICAL.turns[0]
    assert ret["start_s"] <= ret["end_s"]
    split = turn_stages(turn)
    assert split is not None
    assert split.mode == "streamed"
    assert split.total_s == turn.time_of_first("delta")


# ---- substitute judge ------------------------------------------------------------------------------------
def test_judge_spec_substitute_keeps_the_judge_settings() -> None:
    pinned = model_for(ModelRole.JUDGE)
    assert judge_spec() == pinned
    assert judge_spec(model_id=pinned.model_id) == pinned
    sub = judge_spec(model_id="judge-substitute")
    assert sub.model_id == "judge-substitute"
    assert sub.thinking_level == pinned.thinking_level
    assert sub.max_output_tokens == pinned.max_output_tokens
    assert sub.timeout_s == max(pinned.timeout_s, OVERRIDE_TIMEOUT_S)
    assert judge_model_id(model_id="judge-substitute") == "judge-substitute"
    check_independent(model_id="judge-substitute")
    with pytest.raises(ValueError, match="answer model"):
        check_independent(model_id=model_for(ModelRole.ANSWER).model_id)


async def test_a_substitute_judge_also_judges_fallback_model_answers(
    harness_factory: Callable[..., Any], store: Store
) -> None:
    from core.errors import UpstreamTimeout

    llm = scripted_provider()
    llm.responder = _judge_responder("supported")
    llm.failures[ModelRole.ANSWER] = UpstreamTimeout("slow")
    async with harness_factory(llm) as harness:
        await run_items(harness, store, "quality", [MEDICAL], RunOptions(), sleep=_no_sleep, log=_quiet)
        summary = await run_judge(
            harness.llm, store, RunOptions(), sleep=_no_sleep, log=_quiet, judge_model="judge-substitute"
        )
    result = store.get("quality", MEDICAL.id)
    assert result is not None
    assert "answer_fallback" in result.last.generation_roles()
    assert summary.completed == 1
    judgement = store.get_judgement("quality", MEDICAL.id)
    assert judgement is not None
    assert judgement["labels"]


# ---- re-runs and the quiet window -------------------------------------------------------------------------
def test_select_items_keeps_suite_order_and_rejects_unknown_ids() -> None:
    items = [EvalItem("quality", f"q{i}", "en", ("q",)) for i in range(4)]
    assert cli.select_items(items, None) == items
    assert [i.id for i in cli.select_items(items, "q3, q1")] == ["q1", "q3"]
    with pytest.raises(SystemExit, match="unknown item ids"):
        cli.select_items(items, "q1,nope")


async def test_archive_moves_the_cached_result_so_the_item_runs_again(
    harness_factory: Callable[..., Any], store: Store
) -> None:
    async with harness_factory() as harness:
        await run_items(harness, store, "quality", [MEDICAL], RunOptions(), sleep=_no_sleep, log=_quiet)
        moved = store.archive("quality", MEDICAL.id, "replaced-1")
        assert moved is not None
        assert moved.exists()
        assert moved.parent == store.root / "archive" / "quality"
        assert not store.has("quality", MEDICAL.id)
        again = await run_items(
            harness, store, "quality", [MEDICAL], RunOptions(), sleep=_no_sleep, log=_quiet
        )
    assert again.completed == 1
    assert store.archive("quality", "absent", "x") is None


def test_busy_processes_lists_other_eval_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    import psutil

    class Proc:
        def __init__(self, pid: int, cmd: list[str], name: str = "python.exe") -> None:
            self.info = {"pid": pid, "name": name, "cmdline": cmd}

    procs = [
        Proc(os.getpid(), ["python", "-m", "evals.p4", "run"]),  # this process
        Proc(4242, ["python", "-m", "evals.load.run", "overload"]),
        Proc(4343, ["locust", "-f", "x.py"], name="locust.exe"),
        Proc(4444, ["python", "-m", "http.server"]),
        Proc(4545, []),
        Proc(4646, ["bash", "-c", "python -m evals.p4 run"], name="bash.exe"),  # a shell wrapper, not a run
        Proc(4747, ["python", "-c", "from evals.p4.cli import busy_processes"]),  # a helper, not a run
        Proc(4848, ["python", "-m", "uvicorn", "evals.load.server:create_load_app"]),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter(procs))
    busy = cli.busy_processes()
    assert [line.split(":")[0] for line in busy] == ["4242", "4343", "4848"]


def test_latency_run_refuses_to_start_in_a_busy_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class S:
        data_root = tmp_path
        is_free_tier = True

    monkeypatch.setattr(cli, "get_settings", lambda: S())
    monkeypatch.setattr(cli, "free_ram_gb", lambda: 8.0)
    monkeypatch.setattr(cli, "busy_processes", lambda: ["4242: python -m evals.load run"])
    assert cli.main(["run", "--suite", "latency", "--limit", "1"]) == 4
    assert "not a quiet window" in capsys.readouterr().out


def test_judge_record_states_how_many_answers_were_judged() -> None:
    from evals.p4.judge import JudgeVerdict
    from evals.p4.metrics import Ctx, all_records
    from evals.p4.results import ItemResult, TurnResult

    def answered(iid: str) -> ItemResult:
        ans = {"type": "answer", "mode": "streamed", "text": "Fact [1].", "citations": [{"n": 1}]}
        turn = TurnResult("m", 200, ({"type": "meta"}, ans, {"type": "done"}), (0.0, 1.0, 1.1))
        return ItemResult(EvalItem("quality", iid, "en", ("q",)), (turn,), "2026-11-20T00:00:00Z")

    results = [answered("q1"), answered("q2")]
    verdict = JudgeVerdict(("supported",), ("Fact [1].",), "judge-x", "h")
    recs = all_records({"quality": results}, [(results[0], verdict)], Ctx("2026-11-20T00:00:00Z"))
    rate = next(r for r in recs if r["metric"] == "supported_claim_rate")
    assert rate["labels"]["judge_model"] == "judge-x"
    assert (rate["labels"]["answers"], rate["labels"]["eligible_answers"]) == ("1", "2")
