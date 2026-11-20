"""Causes of not-answered answerable items (evals/p4/diagnose.py) on synthetic turns and app DB rows."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from evals.p4.diagnose import (
    GOLD_NOT_IN_INDEX,
    MEDICATION_LABEL_FILTER,
    OTHER,
    PROVIDER_BLOCK,
    RETRIEVAL_NOT_CONFIDENT,
    TIMEOUT_OR_503,
    VERIFICATION_REMOVED,
    TurnRecord,
    cause_table,
    classify,
    contended,
    diagnose,
    format_causes,
    load_turn_records,
    missing_gold_chunks,
    turn_id,
)
from evals.p4.items import EvalItem
from evals.p4.results import ItemResult, TurnResult


def _turn(
    mode: str,
    *,
    intent: str = "medical_info",
    confident: bool | None = False,
    calls: tuple[dict[str, Any], ...] = ({"kind": "decide", "role": "guard", "outcome": "ok"},),
    retries: int = 0,
    done: bool = True,
    tid: str = "t1",
    retrievals: tuple[dict[str, Any], ...] = (),
) -> TurnResult:
    payloads: list[dict[str, Any]] = [{"type": "meta", "turn_id": tid}]
    payloads.append({"type": "answer", "mode": mode, "intent": intent, "text": "Some text [1]."})
    if done:
        payloads.append({"type": "done"})
    return TurnResult(
        "q",
        200,
        tuple(payloads),
        tuple(0.1 * i for i in range(len(payloads))),
        calls=calls,
        retries=retries,
        retrieval_confident=confident,
        retrievals=retrievals,
    )


def _result(turn: TurnResult, iid: str = "g1-en", lang: str = "en") -> ItemResult:
    meta = MappingProxyType({"relevant_chunk_ids": "doc:1#s0#0"})
    return ItemResult(EvalItem("quality", iid, lang, ("q",), meta=meta), (turn,), "2026-11-20T00:00:00Z")


REWRITE_OK = (
    {"kind": "decide", "role": "guard", "outcome": "ok"},
    {"kind": "generate", "role": "rewrite", "outcome": "ok"},
)
ANSWERED = (*REWRITE_OK, {"kind": "generate", "role": "answer", "outcome": "ok"})


@pytest.mark.parametrize(
    ("turn", "record", "cause"),
    [
        (_turn("refusal"), None, PROVIDER_BLOCK),
        (_turn("abstain", intent="medication"), None, MEDICATION_LABEL_FILTER),
        (_turn("template"), TurnRecord(degraded=("busy",)), TIMEOUT_OR_503),
        (_turn("abstain", done=False), None, TIMEOUT_OR_503),
        (_turn("abstain", calls=REWRITE_OK), TurnRecord(degraded=("rewrite_failed",)), TIMEOUT_OR_503),
        (
            _turn("abstain", calls=({"kind": "generate", "role": "rewrite", "outcome": "cancelled"},)),
            None,
            TIMEOUT_OR_503,
        ),
        (_turn("abstain", calls=REWRITE_OK), TurnRecord(), RETRIEVAL_NOT_CONFIDENT),
        (
            _turn("abstain", confident=True, calls=ANSWERED),
            TurnRecord(abstain_reasons=("verifier_unavailable",)),
            TIMEOUT_OR_503,
        ),
        (
            _turn("abstain", confident=True, calls=ANSWERED),
            TurnRecord(abstain_reasons=("unsupported",)),
            VERIFICATION_REMOVED,
        ),
        (_turn("abstain", confident=True, calls=ANSWERED), None, VERIFICATION_REMOVED),
        (_turn("none", confident=True), None, OTHER),
    ],
)
def test_classify_each_cause(turn: TurnResult, record: TurnRecord | None, cause: str) -> None:
    diag = classify(_result(turn), record)
    assert diag is not None
    assert diag.cause == cause


def test_answered_items_have_no_cause_and_missing_gold_comes_first() -> None:
    assert classify(_result(_turn("streamed", confident=True, calls=ANSWERED)), None) is None
    medication = _result(_turn("abstain", intent="medication"))
    diag = classify(medication, None, gold_in_index=False)
    assert diag is not None
    assert diag.cause == GOLD_NOT_IN_INDEX
    assert diag.detail == "doc:1#s0#0"


def test_confidence_detail_uses_the_recorded_query() -> None:
    ret = ({"confidence": 0.62, "search_queries": ["q en"]},)
    diag = classify(_result(_turn("abstain", calls=REWRITE_OK, retrievals=ret)), TurnRecord())
    assert diag is not None
    assert diag.detail == "p=0.62 search_queries=1"


def test_diagnose_table_and_contended() -> None:
    results = [
        _result(_turn("abstain", intent="medication", tid="a"), "g1-en", "en"),
        _result(_turn("abstain", calls=REWRITE_OK, tid="b", retries=2), "g1-fr", "fr"),
        _result(_turn("streamed", confident=True, calls=ANSWERED, tid="c", retries=1), "g1-ar", "ar"),
        _result(_turn("abstain", tid="d"), "g2-en", "en"),
    ]
    records = {"b": TurnRecord(degraded=("rewrite_failed",))}
    diags = diagnose(results, records, missing_gold=["g2-en"])
    table = cause_table(diags)
    assert table[MEDICATION_LABEL_FILTER]["en"] == ["g1-en"]
    assert table[TIMEOUT_OR_503]["fr"] == ["g1-fr"]
    assert table[GOLD_NOT_IN_INDEX]["en"] == ["g2-en"]
    assert [r.item.id for r in results if contended(r)] == ["g1-fr", "g1-ar"]
    lines = format_causes(diags, len(results))
    assert lines[0] == "not answered: 3 of 4"
    assert any(line.startswith("timeout_or_503") and line.split()[2] == "1" for line in lines)
    assert turn_id(results[0].last) == "a"


def test_load_turn_records_reads_degraded_flags_and_abstain_reasons(tmp_path: Path) -> None:
    db = tmp_path / "p4.db"
    with sqlite3.connect(db) as conn:
        conn.execute("create table turns (id text, degraded text, latencies_ms text)")
        conn.execute("create table audit_events (turn_id text, event_type text, detail text)")
        conn.execute(
            "insert into turns values ('t1', ?, ?)", (json.dumps(["rewrite_failed"]), '{"route": 1.0}')
        )
        conn.execute("insert into turns values ('t2', '[]', '{}')")
        conn.execute(
            "insert into audit_events values ('t2', 'abstain', ?)", (json.dumps({"reason": "unsupported"}),)
        )
        conn.execute("insert into audit_events values ('t2', 'strike', '{}')")
    records = load_turn_records(db, ["t1", "t2", "t3", ""])
    assert records["t1"].degraded == ("rewrite_failed",)
    assert records["t1"].latencies_ms == {"route": 1.0}
    assert records["t2"].abstain_reasons == ("unsupported",)
    assert "t3" not in records
    assert load_turn_records(tmp_path / "absent.db", ["t1"]) == {}
    assert load_turn_records(db, []) == {}


async def test_missing_gold_chunks_queries_each_chunk_id() -> None:
    class Client:
        def __init__(self) -> None:
            self.asked: list[str] = []

        async def scroll(self, collection: str, **kwargs: Any) -> tuple[list[int], None]:
            cid = kwargs["scroll_filter"].must[0].match.value
            self.asked.append(cid)
            return ([1] if cid == "doc:1#s0#0" else []), None

    present = _result(_turn("abstain"), "g1-en")
    absent = ItemResult(
        EvalItem(
            "quality", "g2-en", "en", ("q",), meta=MappingProxyType({"relevant_chunk_ids": "doc:2#s0#0"})
        ),
        (_turn("abstain"),),
        "2026-11-20T00:00:00Z",
    )
    client = Client()
    assert await missing_gold_chunks(client, "alias", [present, absent]) == ["g2-en"]
    assert client.asked == ["doc:1#s0#0", "doc:2#s0#0"]
