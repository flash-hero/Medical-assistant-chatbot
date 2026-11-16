import json
from pathlib import Path

import yaml

from evals.gates_eval import MetricRecord, Verdict, evaluate, exit_code
from evals.run import load_records, main

REPO = Path(__file__).resolve().parents[2]


def rec(metric, value, **kw):
    return MetricRecord(metric=metric, value=value, **kw)


def test_pass_fail_missing():
    gates = {
        "a": {"metric": "m1", "op": ">=", "value": 0.9},
        "b": {"metric": "m2", "op": "==", "value": 0},
        "c": {"metric": "m3", "op": "<", "value": 5},
    }
    res = {r.gate: r.verdict for r in evaluate(gates, [rec("m1", 0.95), rec("m2", 1)])}
    assert res == {"a": Verdict.PASS, "b": Verdict.FAIL, "c": Verdict.MISSING}
    assert exit_code(evaluate(gates, [rec("m1", 0.95), rec("m2", 0), rec("m3", 1)])) == 0


def test_label_selection_and_latest_record_wins():
    gates = {"g": {"metric": "recall_at_20", "lang": "fr", "op": ">=", "value": 0.85}}
    records = [
        rec("recall_at_20", 0.99, labels={"lang": "en"}),
        rec("recall_at_20", 0.80, labels={"lang": "fr"}, measured_at="2026-11-15T10:00"),
        rec("recall_at_20", 0.90, labels={"lang": "fr"}, measured_at="2026-11-15T12:00"),
    ]
    assert evaluate(gates, records)[0].verdict is Verdict.PASS


def test_per_lang_count_gate_with_reduced_sample_is_provisional():
    gates = {
        "s": {
            "metric": "emergency_detected",
            "per_lang": True,
            "op": ">=",
            "value": 294,
            "of": 300,
            "provisional_on_free_tier": True,
        }
    }
    records = [
        rec("emergency_detected", 300, labels={"lang": "en"}, sample_size=300),
        rec("emergency_detected", 59, labels={"lang": "fr"}, sample_size=60),  # 98.3% >= 98%
        rec("emergency_detected", 55, labels={"lang": "ar"}, sample_size=60),  # 91.7% < 98%
    ]
    res = {r.gate: r.verdict for r in evaluate(gates, records)}
    assert res == {"s[en]": Verdict.PASS, "s[fr]": Verdict.PROVISIONAL, "s[ar]": Verdict.FAIL}


def test_rate_gate_with_of_is_not_divided_by_sample():
    gates = {
        "r": {
            "metric": "refusal_rate",
            "of": 200,
            "op": ">=",
            "value": 0.98,
            "provisional_on_free_tier": True,
        }
    }
    assert evaluate(gates, [rec("refusal_rate", 0.99, sample_size=200)])[0].verdict is Verdict.PASS
    assert evaluate(gates, [rec("refusal_rate", 0.99, sample_size=50)])[0].verdict is Verdict.PROVISIONAL
    assert evaluate(gates, [rec("refusal_rate", 0.90, sample_size=200)])[0].verdict is Verdict.FAIL


def test_free_tier_marks_provisional_only_when_gate_allows():
    gates = {
        "p": {"metric": "x", "op": ">=", "value": 0.9, "provisional_on_free_tier": True},
        "q": {"metric": "y", "op": ">=", "value": 0.9},
    }
    res = {
        r.gate: r.verdict
        for r in evaluate(gates, [rec("x", 0.95, free_tier=True), rec("y", 0.95, free_tier=True)])
    }
    assert res == {"p": Verdict.PROVISIONAL, "q": Verdict.PASS}


def test_reduced_sample_fails_when_not_provisional():
    gates = {"d": {"metric": "near_duplicate_rate", "op": "<", "value": 0.01, "sample": 1000}}
    assert evaluate(gates, [rec("near_duplicate_rate", 0.0, sample_size=200)])[0].verdict is Verdict.FAIL


def test_real_gates_file_parses_and_cli_runs(tmp_path, capsys):
    gates = yaml.safe_load((REPO / "evals" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
    assert len(gates) >= 30
    for spec in gates.values():
        assert spec["op"] in (">=", "<=", ">", "<", "==")
    (tmp_path / "x.metrics.json").write_text(
        json.dumps([{"metric": "count_docs_from_excluded_sources", "value": 0}]), encoding="utf-8"
    )
    assert len(load_records(tmp_path)) == 1
    code = main(
        ["--gates", str(REPO / "evals" / "gates.yaml"), "--reports", str(tmp_path), "--only", "data."]
    )
    out = capsys.readouterr().out
    assert "PASS  data.excluded_sources" in out
    assert code == 1  # other data gates are MISSING


def test_zero_gates_is_never_a_pass_and_empty_samples_fail():
    assert exit_code(evaluate({}, [])) == 2
    gates = {"c": {"metric": "m", "op": ">=", "value": 294, "of": 300}}
    assert evaluate(gates, [rec("m", 0, sample_size=0)])[0].verdict is Verdict.FAIL
