"""Why an answerable gold question was not answered (P4 quality.answer_answerable), from the cached turn and
the app's own turn record (degraded flags, audit reasons) in the eval SQLite file.

Causes, first match wins:
  gold_not_in_index        the gold chunk is not in the live collection (gold-set problem: excluded)
  provider_block           a provider block ended the turn with the refusal template
  medication_label_filter  medication intent: the medical path searches and answers from drug labels only
                           (review C7) and the live index has none
  timeout_or_503           an upstream call failed or timed out and the pipeline degraded: busy template, a
                           failed rewrite (the raw message, with no English search query, cannot pass the
                           confidence gate in FR / AR), an unavailable verifier, a turn deadline
  retrieval_not_confident  the calibrated confidence gate abstained on a clean retrieval
  verification_removed     the answer was generated, then the output checks or the groundedness verifier
                           removed too much (empty / no citation / unsupported)
  other                    anything else (listed with its mode for a manual look)

`contended(result)` marks turns whose provider calls were retried (429 / 5xx absorbed by the retry policy):
measured under quota contention, they are re-run in a quiet window whatever their outcome.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.p4.items import LANGS
from evals.p4.metrics import is_answered
from evals.p4.results import ItemResult, TurnResult

GOLD_NOT_IN_INDEX = "gold_not_in_index"
PROVIDER_BLOCK = "provider_block"
MEDICATION_LABEL_FILTER = "medication_label_filter"
TIMEOUT_OR_503 = "timeout_or_503"
RETRIEVAL_NOT_CONFIDENT = "retrieval_not_confident"
VERIFICATION_REMOVED = "verification_removed"
OTHER = "other"
CAUSES: tuple[str, ...] = (
    GOLD_NOT_IN_INDEX,
    PROVIDER_BLOCK,
    MEDICATION_LABEL_FILTER,
    TIMEOUT_OR_503,
    RETRIEVAL_NOT_CONFIDENT,
    VERIFICATION_REMOVED,
    OTHER,
)
FAILED_CALL_OUTCOMES = frozenset(
    {"upstream_timeout", "upstream_unavailable", "upstream_rate_limited", "cancelled", "TimeoutError"}
)
UPSTREAM_DEGRADES = frozenset({"rewrite_failed", "deadline", "busy", "retrieval_failed", "fallback_model"})
VERIFY_REMOVED_REASONS = frozenset({"unsupported", "empty_after_checks", "no_citation"})


@dataclass(frozen=True)
class TurnRecord:
    """What the app persisted for the turn (no message text): degraded flags and audit reasons."""

    degraded: tuple[str, ...] = ()
    abstain_reasons: tuple[str, ...] = ()
    latencies_ms: Mapping[str, float] | None = None


@dataclass(frozen=True)
class Diagnosis:
    item_id: str
    lang: str
    cause: str
    detail: str


def turn_id(turn: TurnResult) -> str:
    meta = next((p for p in turn.payloads if p.get("type") == "meta"), {})
    return str(meta.get("turn_id", ""))


def load_turn_records(db_path: Path, turn_ids: Iterable[str]) -> dict[str, TurnRecord]:
    """Read-only lookup of the app's turn rows and abstain audits (an absent file gives no records)."""
    wanted = [t for t in dict.fromkeys(turn_ids) if t]
    if not wanted or not db_path.exists():
        return {}
    out: dict[str, TurnRecord] = {}
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
        marks = ",".join("?" * len(wanted))
        audits: dict[str, list[str]] = {}
        for tid, detail in conn.execute(
            f"select turn_id, detail from audit_events where event_type = 'abstain' and turn_id in ({marks})",  # noqa: S608
            wanted,
        ):
            audits.setdefault(str(tid), []).append(str(json.loads(detail).get("reason", "")))
        for tid, degraded, latencies in conn.execute(
            f"select id, degraded, latencies_ms from turns where id in ({marks})",  # noqa: S608
            wanted,
        ):
            out[str(tid)] = TurnRecord(
                degraded=tuple(json.loads(degraded or "[]")),
                abstain_reasons=tuple(audits.get(str(tid), [])),
                latencies_ms=json.loads(latencies or "{}"),
            )
    return out


def contended(result: ItemResult) -> bool:
    return any(t.retries for t in result.turns)


def _failed_calls(turn: TurnResult) -> list[str]:
    return [
        f"{c.get('role')}:{c.get('outcome')}" for c in turn.calls if c.get("outcome") in FAILED_CALL_OUTCOMES
    ]


def _rewrite_failed(turn: TurnResult, record: TurnRecord | None) -> bool:
    if record is not None and "rewrite_failed" in record.degraded:
        return True
    return any(c.get("role") == "rewrite" and c.get("outcome") != "ok" for c in turn.calls)


def classify(
    result: ItemResult, record: TurnRecord | None, *, gold_in_index: bool = True
) -> Diagnosis | None:
    """The cause of a not-answered item, or None when the item was answered."""
    turn = result.last
    if is_answered(turn):
        return None
    item = result.item

    def diag(cause: str, detail: str) -> Diagnosis:
        return Diagnosis(item.id, item.lang, cause, detail)

    answer = turn.answer or {}
    mode, intent = turn.mode, str(answer.get("intent", "-"))
    degraded = record.degraded if record is not None else ()
    reasons = record.abstain_reasons if record is not None else ()
    if not gold_in_index:
        return diag(GOLD_NOT_IN_INDEX, str(item.meta.get("relevant_chunk_ids", "")))
    if mode == "refusal":
        return diag(PROVIDER_BLOCK, f"mode=refusal degraded={','.join(degraded) or '-'}")
    if intent == "medication" and mode == "abstain":
        return diag(MEDICATION_LABEL_FILTER, "medication intent, no drug-label passage in the index")
    failed = _failed_calls(turn)
    if mode == "template" or turn.error or not turn.complete:
        return diag(TIMEOUT_OR_503, f"mode={mode} error={turn.error or '-'} calls={','.join(failed) or '-'}")
    if mode == "abstain" and turn.retrieval_confident is False:
        if _rewrite_failed(turn, record):
            detail = f"rewrite failed ({','.join(failed) or 'timeout'}), retries={turn.retries}"
            return diag(TIMEOUT_OR_503, detail)
        return diag(RETRIEVAL_NOT_CONFIDENT, _confidence_detail(turn))
    if "verifier_unavailable" in reasons or set(degraded) & UPSTREAM_DEGRADES:
        return diag(TIMEOUT_OR_503, f"degraded={','.join(degraded)} reasons={','.join(reasons) or '-'}")
    if mode == "abstain" and (set(reasons) & VERIFY_REMOVED_REASONS or "answer" in turn.generation_roles()):
        return diag(VERIFICATION_REMOVED, f"reasons={','.join(reasons) or '-'}")
    return diag(OTHER, f"mode={mode} intent={intent} degraded={','.join(degraded) or '-'}")


def _confidence_detail(turn: TurnResult) -> str:
    if not turn.retrievals:
        return f"passages={len(turn.passages)}"
    last = turn.retrievals[-1]
    return f"p={last.get('confidence')} search_queries={len(last.get('search_queries', []))}"


def diagnose(
    results: Sequence[ItemResult],
    records: Mapping[str, TurnRecord],
    missing_gold: Iterable[str] = (),
) -> list[Diagnosis]:
    missing = set(missing_gold)
    out = []
    for r in results:
        d = classify(r, records.get(turn_id(r.last)), gold_in_index=r.item.id not in missing)
        if d is not None:
            out.append(d)
    return out


def cause_table(diags: Sequence[Diagnosis]) -> dict[str, dict[str, list[str]]]:
    """cause -> lang -> item ids (every cause and language present, possibly empty)."""
    table: dict[str, dict[str, list[str]]] = {c: {lang: [] for lang in LANGS} for c in CAUSES}
    for d in diags:
        table[d.cause].setdefault(d.lang, []).append(d.item_id)
    return table


def format_causes(diags: Sequence[Diagnosis], total: int) -> list[str]:
    table = cause_table(diags)
    lines = [f"not answered: {len(diags)} of {total}", f"{'cause':<26}" + "".join(f"{x:>5}" for x in LANGS)]
    for cause, by_lang in table.items():
        counts = "".join(f"{len(by_lang.get(lang, [])):>5}" for lang in LANGS)
        lines.append(f"{cause:<26}{counts}")
    lines.append("")
    lines += [f"{d.item_id:<14} {d.cause:<24} {d.detail}" for d in diags]
    return lines


async def missing_gold_chunks(client: Any, collection: str, results: Sequence[ItemResult]) -> list[str]:
    """Items whose gold chunk ids are not all in the live collection (Qdrant payload `chunk_id`)."""
    from qdrant_client.http import models as qm

    out = []
    for r in results:
        for cid in [c for c in str(r.item.meta.get("relevant_chunk_ids", "")).split(",") if c]:
            flt = qm.Filter(must=[qm.FieldCondition(key="chunk_id", match=qm.MatchValue(value=cid))])
            points, _ = await client.scroll(collection, scroll_filter=flt, limit=1, with_payload=False)
            if not points:
                out.append(r.item.id)
                break
    return out


__all__ = [
    "CAUSES",
    "Diagnosis",
    "TurnRecord",
    "cause_table",
    "classify",
    "contended",
    "diagnose",
    "format_causes",
    "load_turn_records",
    "missing_gold_chunks",
    "turn_id",
]
