"""Engine release gates measured through the real ASGI app (evals/gates.yaml, engine.*):

  engine.emergency_latency_ms   emergency / self-harm template < 300 ms with EVERY model role failing
  engine.disconnect_close_s     upstream model stream closed <= 1 s after the client disconnects
  engine.cancel_slot_leaks      1,000 cancelled turns leave 0 admission slots held

The same functions write C:/dev/ausculta-data/reports/engine.metrics.json via
`python -m evals.fakes.engine_gates`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.models import ModelRole
from core.ports import GenerationRequest, GenerationResult
from evals.fakes import engine_gates as eg
from evals.fakes.asgi_driver import DriveResult, drive
from evals.fakes.fake_llm import FakeLLMProvider
from evals.fakes.scripted import guard_decider, role_responder

EMERGENCY_BUDGET_MS = 300.0
CLOSE_BUDGET_S = 1.0


async def test_gate_emergency_latency_with_all_models_failing(tmp_path: Path) -> None:
    result = await eg.measure_emergency_latency(tmp_path, rounds=1)
    assert result.samples == sum(len(m) for m in eg.SAFETY_MESSAGES.values())
    assert result.model_calls == 0, "the emergency path must not call any model"
    assert result.max_ms < EMERGENCY_BUDGET_MS, result


async def test_gate_upstream_closed_after_client_disconnect(tmp_path: Path) -> None:
    closes = await eg.measure_disconnect_close(tmp_path, runs=3)
    assert max(closes) <= CLOSE_BUDGET_S, closes


def test_gate_upstream_closed_after_disconnect_over_real_tcp(tmp_path: Path) -> None:
    closes = eg.measure_disconnect_close_live(tmp_path, runs=2)
    assert max(closes) <= CLOSE_BUDGET_S, closes


class SlowAnswers(FakeLLMProvider):
    """Answer generation takes 5 s; every other role answers at once."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        if request.role in (ModelRole.ANSWER, ModelRole.ANSWER_FALLBACK):
            self.calls.append(("slow-generate-started", request.role, 1))
            await asyncio.sleep(5.0)
        return await super().generate(request)


async def test_verified_turn_is_cancelled_during_offscreen_generation(tmp_path: Path) -> None:
    llm = SlowAnswers(responder=role_responder(), decider=guard_decider())
    async with eg.running_app(tmp_path, llm) as g:
        body, headers = eg.chat_request(await g.token(), eg.VERIFIED_QUESTION)
        result = DriveResult()
        task = asyncio.create_task(
            drive(
                g.app,
                "POST",
                "/api/v1/chat",
                body,
                headers,
                result=result,
                disconnect_when=lambda r: b"verifying" in b"".join(r.chunks),
            )
        )
        await task
        assert result.disconnected_at is not None
        assert result.elapsed_s - (result.disconnected_at - result.started_at) < CLOSE_BUDGET_S
        assert b"event: answer" not in b"".join(result.chunks)
        assert llm.count("slow-generate-started") == 1
        answers_done = [c for c in llm.calls if c[0] == "generate" and c[1] is ModelRole.ANSWER]
        assert answers_done == [], "the answer generation was cancelled, not completed"
        assert g.container.admission.held == 0
        assert g.container.registry.running == 0


@pytest.mark.slow
async def test_gate_1000_cancel_cycles_leak_no_admission_slot(tmp_path: Path) -> None:
    result = await eg.measure_cancel_leaks(tmp_path, cycles=1000)
    assert result.leaked == 0, result
    assert result.running_turns == 0
    assert result.open_streams == 0
    assert sum(result.statuses.values()) == 1000
    assert set(result.statuses) <= {200, 499}, result.statuses  # never 409 / 503: nothing stayed claimed


# ---- gate runner helpers ---------------------------------------------------------------------------
def _coverage_report(tmp_path: Path) -> Path:
    report = {
        "files": {
            "app\\pipeline\\engine.py": {"summary": {"num_statements": 100, "covered_lines": 95}},
            "app/guardrails/router.py": {"summary": {"num_statements": 100, "covered_lines": 85}},
            "app/api/routes_chat.py": {"summary": {"num_statements": 50, "covered_lines": 10}},
        }
    }
    path = tmp_path / "cov.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_coverage_records_per_scope(tmp_path: Path) -> None:
    path = _coverage_report(tmp_path)
    records = eg.coverage_records({"app/guardrails app/pipeline": path, "all": path})
    by_scope = {r["labels"]["scope"]: r for r in records}
    assert by_scope["app/guardrails app/pipeline"]["value"] == 0.9
    assert by_scope["app/guardrails app/pipeline"]["sample_size"] == 200
    assert by_scope["all"]["value"] == round(190 / 250, 4)
    assert {r["metric"] for r in records} == {"line_coverage"}
    with pytest.raises(eg.GateMeasurementError):
        eg.coverage_records({"bogus": path})
    with pytest.raises(eg.GateMeasurementError):
        eg.coverage_ratio({"files": {}}, ("app/pipeline",))


def test_records_match_the_gates_eval_format() -> None:
    from evals.gates_eval import MetricRecord

    rec = eg.record("leaked_slots_after_1000_cancels", 0.0, sample_size=1000, open_streams="0")
    parsed = MetricRecord.from_dict(rec)
    assert (parsed.metric, parsed.value, parsed.sample_size) == ("leaked_slots_after_1000_cancels", 0.0, 1000)
    assert set(rec) == {"metric", "value", "labels", "sample_size", "source", "measured_at", "free_tier"}


def test_merge_and_atomic_write(tmp_path: Path) -> None:
    out = tmp_path / "reports" / "engine.metrics.json"
    old = [
        eg.record("line_coverage", 0.5, sample_size=1, scope="all"),
        eg.record("upstream_close_after_disconnect_s", 0.9, sample_size=1),
    ]
    eg.write_metrics(out, old)
    fresh = [eg.record("line_coverage", 0.8, sample_size=2, scope="all")]
    merged = eg.merge_records(eg._read_records(out), fresh)
    assert [(r["metric"], r["value"]) for r in merged] == [
        ("upstream_close_after_disconnect_s", 0.9),
        ("line_coverage", 0.8),
    ]
    assert not list(out.parent.glob("*.tmp"))


def test_cli_coverage_only_merges_into_the_metrics_file(tmp_path: Path, capsys) -> None:
    out = tmp_path / "engine.metrics.json"
    eg.write_metrics(out, [eg.record("leaked_slots_after_1000_cancels", 0.0, sample_size=1000)])
    cov = _coverage_report(tmp_path)
    assert eg.main(["--out", str(out), "--coverage-only", "--coverage-json", f"all={cov}"]) == 0
    metrics = {r["metric"] for r in json.loads(out.read_text(encoding="utf-8"))}
    assert metrics == {"leaked_slots_after_1000_cancels", "line_coverage"}
    assert "line_coverage" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        eg.main(["--out", str(out), "--coverage-only", "--coverage-json", "no-equals-sign"])
    assert eg._read_records(tmp_path / "missing.json") == []
