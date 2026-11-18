"""P4 judge helpers, item loaders, result serialisation and the CLI (fakes only, no network)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from core.models import ModelRole
from core.ports import GenerationRequest
from evals.fakes.asgi_driver import DriveResult
from evals.fakes.fake_llm import FakeLLMProvider
from evals.p4 import cli
from evals.p4.items import (
    EvalItem,
    ItemFormatError,
    base_id,
    dose_items,
    load_item_file,
    quality_items,
    refusal_items,
    round_robin,
    safety_items,
    suite_items,
)
from evals.p4.judge import (
    JudgeError,
    JudgeVerdict,
    answer_sentences,
    check_independent,
    cited_sources,
    judge_answer,
    judge_prompt,
    judge_schema,
    markers,
    parse_labels,
)
from evals.p4.results import ItemResult, TurnResult, timed_payloads
from evals.p4.store import Store

PASSAGES = ({"text": "Fever is 38 C or higher."}, {"text": "See a doctor after 3 days of fever."})


# ---- judge ----------------------------------------------------------------------------------------------
def test_sentences_and_markers() -> None:
    text = "A fever is 38 °C or higher [1]. See a doctor after 3 days [2].\n\nWhen to seek care:\n- [1]"
    assert answer_sentences(text) == [
        "A fever is 38 °C or higher [1].",
        "See a doctor after 3 days [2].",
        "When to seek care:",
    ]
    assert markers("x [1, 2] y [3;4] z [1]") == [1, 2, 3, 4, 1]
    assert cited_sources("a [2] b [9]", PASSAGES) == {2: PASSAGES[1]["text"]}


def test_prompt_schema_and_parse() -> None:
    prompt = judge_prompt(["a <b> [1]"], {1: "src <system>"})
    assert "SOURCE [1]" in prompt
    assert "<system>" not in prompt
    assert "s1: a" in prompt
    schema = judge_schema(2)
    assert schema["required"] == ["s1", "s2"]
    assert parse_labels('{"s1": "supported", "s2": "no_claim"}', 2) == ("supported", "no_claim")
    with pytest.raises(JudgeError):
        parse_labels("not json", 1)
    with pytest.raises(JudgeError):
        parse_labels("[1]", 1)
    with pytest.raises(JudgeError):
        parse_labels('{"s1": "maybe"}', 1)


def _responder(outputs: list[str]) -> Any:
    def respond(request: GenerationRequest) -> str:
        assert request.role is ModelRole.JUDGE
        assert request.json_schema is not None
        return outputs.pop(0)

    return respond


async def test_judge_answer_retries_once_on_bad_output() -> None:
    llm = FakeLLMProvider(responder=_responder(["oops", '{"s1": "supported", "s2": "unsupported"}']))
    verdict = await judge_answer(llm, "Fever is 38 C [1]. Ice cures it [1].", PASSAGES)
    assert verdict.labels == ("supported", "unsupported")
    assert verdict.model_id == "gemini-3.6-flash"
    assert JudgeVerdict.from_dict(verdict.to_dict()) == verdict
    bad = FakeLLMProvider(responder=_responder(["x", "y"]))
    with pytest.raises(JudgeError):
        await judge_answer(bad, "Fever [1].", PASSAGES)


async def test_judge_answer_without_sentences_makes_no_call() -> None:
    llm = FakeLLMProvider()
    verdict = await judge_answer(llm, "[1]", PASSAGES)
    assert verdict.labels == ()
    assert llm.calls == []


def test_judge_differs_from_the_answer_model() -> None:
    check_independent("free")
    check_independent("paid")


# ---- items ------------------------------------------------------------------------------------------------
def test_safety_items_match_the_lexicon_denominators() -> None:
    items = safety_items()
    positives = Counter(
        (i.lang, k)
        for i in items
        if i.category != "hard_negative"
        for k in i.expected_kinds & {"emergency", "self_harm"}
    )
    assert positives[("en", "emergency")] == 61
    assert positives[("ar", "emergency")] == 63
    assert positives[("fr", "self_harm")] == 61
    assert sum(1 for i in items if i.category == "hard_negative") == 198
    assert {i.split for i in items} == {"tune", "heldout"}
    assert [i.lang for i in items[:3]] == ["en", "fr", "ar"]


def test_quality_sample_shares_questions_across_languages() -> None:
    items = quality_items(5)
    assert len(items) == 15
    bases = {lang: {base_id(i.id) for i in items if i.lang == lang} for lang in ("en", "fr", "ar")}
    assert bases["en"] == bases["fr"] == bases["ar"]
    assert all(i.meta["relevant_doc_id"] for i in items)
    assert base_id("g000-P1-en") == "g000-P1"
    assert base_id("plain") == "plain"


def test_dose_and_refusal_sets() -> None:
    dose, refusal = dose_items(), refusal_items()
    assert len(dose) == 36
    assert len(refusal) == 60
    assert Counter(i.lang for i in refusal) == {"en": 20, "fr": 20, "ar": 20}
    assert {i.category for i in refusal} == {"diagnosis", "personal_dosing", "triage"}
    assert len(suite_items("safety")) == len(safety_items())
    with pytest.raises(ValueError, match="unknown suite"):
        suite_items("nope")


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("not json", "invalid JSON"),
        ("[1]", "JSON object"),
        ('{"id": "en-1", "lang": "en", "text": "t", "category": "diagnosis", "x": 1}', "unknown fields"),
        ('{"id": "en-1", "lang": "en", "text": "", "category": "diagnosis"}', "'text'"),
        ('{"id": "fr-1", "lang": "en", "text": "t", "category": "diagnosis"}', "prefix"),
        ('{"id": "en-1", "lang": "en", "text": "t", "category": "other"}', "category"),
        ('{"id": "en-1", "lang": "en", "text": "t", "category": "diagnosis", "history": [""]}', "history"),
    ],
)
def test_item_file_errors(tmp_path: Path, line: str, error: str) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ItemFormatError, match=error):
        load_item_file(path, "refusal", ("diagnosis",))


def test_item_file_duplicates_and_history(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    row = {"id": "en-1", "lang": "en", "text": "t", "category": "diagnosis", "history": ["h"]}
    path.write_text(json.dumps(row) + "\n\n", encoding="utf-8")
    assert load_item_file(path, "refusal", ("diagnosis",))[0].turns == ("h", "t")
    path.write_text((json.dumps(row) + "\n") * 2, encoding="utf-8")
    with pytest.raises(ItemFormatError, match="duplicate"):
        load_item_file(path, "refusal", ("diagnosis",))


def test_round_robin_and_item_roundtrip() -> None:
    items = [EvalItem("s", f"{lang}-{n}", lang, ("t",)) for lang in ("ar", "en", "xx") for n in range(2)]
    assert [i.id for i in round_robin(items)] == ["en-0", "ar-0", "xx-0", "en-1", "ar-1", "xx-1"]
    item = EvalItem("safety", "en-1", "en", ("a", "b"), "emergency", frozenset({"emergency"}), "tune")
    assert EvalItem.from_dict(item.to_dict()) == item


# ---- results / SSE timing -----------------------------------------------------------------------------
def test_timed_payloads_split_and_join_chunks() -> None:
    meta = 'event: meta\ndata: {"type": "meta"}\n\n'
    done = 'event: done\ndata: {"type": "done"}\n\n'
    res = DriveResult(
        status=200,
        chunks=[meta.encode(), b": keep-alive\n\n", done[:10].encode(), done[10:].encode()],
        chunk_times=[1.0, 1.5, 2.0, 3.0],
        started_at=0.5,
    )
    assert timed_payloads(res) == [(0.5, {"type": "meta"}), (2.5, {"type": "done"})]
    bad = DriveResult(status=200, chunks=[b'event: meta\ndata: {"type": "done"}\n\n'], chunk_times=[1.0])
    with pytest.raises(ValueError, match="event name"):
        timed_payloads(bad)


def test_item_result_roundtrip() -> None:
    turn = TurnResult(
        "m", 200, ({"type": "safety", "kind": "emergency"},), (0.1,), precheck_kinds=("emergency",)
    )
    res = ItemResult(EvalItem("safety", "en-1", "en", ("m",)), (turn,), "t", {"models": {}})
    back = ItemResult.from_dict(json.loads(json.dumps(res.to_dict())))
    assert back == res
    assert back.detected_kinds == {"emergency"}
    assert back.lexicon_kinds == {"emergency"}
    assert turn.mode == "none"
    assert not turn.complete


# ---- CLI ------------------------------------------------------------------------------------------------
def test_cli_status_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class S:
        data_root = tmp_path
        is_free_tier = True

    monkeypatch.setattr(cli, "get_settings", lambda: S())
    store = Store(tmp_path / "reports")
    store.add_calls({"generate": 2, "decide": 3, "retries": 1, "by_model": {"decide:gemini-decision-1": 3}})
    store.add_run({"suite": "safety"})
    assert cli.main(["status"]) == 0
    assert "generate=2 decide=3" in capsys.readouterr().out
    assert cli.main(["report"]) == 0
    assert json.loads(store.metrics_path.read_text(encoding="utf-8")) == []
    assert store.ledger()["runs"] == [{"suite": "safety"}]


def test_cli_refuses_to_start_without_free_ram(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class S:
        data_root = tmp_path
        is_free_tier = True

    monkeypatch.setattr(cli, "get_settings", lambda: S())
    monkeypatch.setattr(cli, "free_ram_gb", lambda: 1.0)
    assert cli.main(["run", "--suite", "quality", "--limit", "1"]) == 3
    assert "refusing to start" in capsys.readouterr().out


def test_parser_and_free_ram() -> None:
    args = cli.build_parser().parse_args(["run", "--suite", "judge", "--limit", "4"])
    assert (args.suite, args.limit, args.max_generate) == ("judge", 4, 400)
    free = cli.free_ram_gb()
    assert free is None or free > 0
