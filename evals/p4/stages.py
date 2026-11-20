"""Per-stage latency of one P4 turn, from the call and retrieval times recorded on the turn's clock.

A medical turn runs, in order: guard decide (GUARD, plus GUARD_FALLBACK when decide failed) -> rewrite
(REWRITE, skipped for standalone English) -> retrieval (local query embedding + Qdrant search, expansion and
the confidence gate) -> answer (ANSWER, or ANSWER_FALLBACK) -> groundedness verification (VERIFY decide).

Stages, in seconds:
  guard           [Gemini] guard decide (+ fallback) call duration
  rewrite         [Gemini] rewrite call duration (0 when skipped)
  overlap         [saved]  time the rewrite ran concurrently with the guard decide (since 2026-11-20 the
                           engine starts the rewrite with the guard call; 0 for serial turns)
  retrieval       [ours]   retrieve() duration, query embedding included (local CPU + Qdrant)
  embed           [ours]   the query-embedding part of `retrieval` (retriever's own timer)
  answer_ttft     [Gemini] answer stream opened -> first chunk with text (model time to first token)
  first_sentence  [ours]   first chunk -> first `delta` at the client: the sentence buffer waits for a full
                           sentence (Gemini token rate) and runs the inline checks before anything is shown
  generation      [Gemini] answer call duration (whole stream / whole verified answer)
  verify          [Gemini] verifier decide duration
  overhead        [ours]   client-measured time (first delta for streamed, answer event for verified) minus
                           the stages on the path to it: session store, routing glue, SSE, scheduling

TTFT (streamed) = guard + rewrite - overlap + retrieval + answer_ttft + first_sentence + overhead
verified answer = guard + rewrite - overlap + retrieval + generation + verify + overhead
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from evals.p4.results import TurnResult
from evals.retrieval.metrics import percentile

GEMINI_STAGES: tuple[str, ...] = ("guard", "rewrite", "answer_ttft", "generation", "verify")
SAVED_STAGES: tuple[str, ...] = ("overlap",)
OUR_STAGES: tuple[str, ...] = ("retrieval", "embed", "first_sentence", "overhead")
STAGES: tuple[str, ...] = (
    "guard",
    "rewrite",
    "overlap",
    "retrieval",
    "embed",
    "answer_ttft",
    "first_sentence",
    "generation",
    "verify",
    "overhead",
)
GUARD_ROLES = frozenset({"guard", "guard_fallback"})
ANSWER_ROLES = frozenset({"answer", "answer_fallback"})


@dataclass(frozen=True)
class TurnStages:
    mode: str  # "streamed" | "verified"
    total_s: float  # client time to the first delta (streamed) or to the answer event (verified)
    stages: Mapping[str, float]


def _duration(call: Mapping[str, Any]) -> float | None:
    start, end = call.get("start_s"), call.get("end_s")
    if start is None or end is None:
        return None
    return max(0.0, float(end) - float(start))


def _calls(turn: TurnResult, roles: frozenset[str]) -> list[Mapping[str, Any]]:
    return [c for c in turn.calls if c.get("role") in roles and c.get("outcome") != "halted"]


def _sum(calls: Sequence[Mapping[str, Any]]) -> float | None:
    durations = [_duration(c) for c in calls]
    if any(d is None for d in durations):
        return None
    return sum(d for d in durations if d is not None)


def _overlap(first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]) -> float:
    """Seconds during which a call of `first` and a call of `second` were both running."""
    total = 0.0
    for a in first:
        for b in second:
            if None in (a.get("start_s"), a.get("end_s"), b.get("start_s"), b.get("end_s")):
                continue
            lo = max(float(a["start_s"]), float(b["start_s"]))
            hi = min(float(a["end_s"]), float(b["end_s"]))
            total += max(0.0, hi - lo)
    return total


def turn_stages(turn: TurnResult) -> TurnStages | None:
    """Stage split of a released medical answer, or None (other modes, or a turn cached without times)."""
    if turn.mode not in ("streamed", "verified") or not turn.retrievals:
        return None
    guard_calls, rewrite_calls = _calls(turn, GUARD_ROLES), _calls(turn, frozenset({"rewrite"}))
    guard, rewrite = _sum(guard_calls), _sum(rewrite_calls)
    answers = _calls(turn, ANSWER_ROLES)
    verify = _sum(_calls(turn, frozenset({"verify"})))
    generation = _sum(answers)
    if guard is None or rewrite is None or verify is None or generation is None or not answers:
        return None
    ret = turn.retrievals[-1]
    retrieval = float(ret["end_s"]) - float(ret["start_s"])
    embed = float(dict(ret.get("timings_ms", {})).get("embed_ms", 0.0)) / 1000
    stages: dict[str, float] = {
        "guard": guard,
        "rewrite": rewrite,
        "overlap": _overlap(guard_calls, rewrite_calls),
        "retrieval": retrieval,
        "embed": embed,
        "generation": generation,
        "verify": verify,
    }
    gate = guard + rewrite - stages["overlap"]  # wall time before retrieval
    if turn.mode == "streamed":
        total = turn.time_of_first("delta")
        stream = answers[-1]
        if total is None or stream.get("first_s") is None:
            return None
        stages["answer_ttft"] = float(stream["first_s"]) - float(stream["start_s"])
        stages["first_sentence"] = max(0.0, total - float(stream["first_s"]))
        path = gate + retrieval + stages["answer_ttft"] + stages["first_sentence"]
    else:
        answer_at = turn.time_of_first("answer")
        if answer_at is None:
            return None
        total = answer_at
        path = gate + retrieval + generation + verify
    stages["overhead"] = max(0.0, total - path)
    return TurnStages(turn.mode, total, {k: round(v, 4) for k, v in stages.items()})


@dataclass(frozen=True)
class StageRow:
    stage: str
    owner: str  # "gemini" | "ours" | "saved" | "total"
    n: int
    p50: float
    p95: float
    mean: float


def stage_table(turns: Sequence[TurnResult], mode: str) -> list[StageRow]:
    """p50 / p95 / mean of every stage over the released turns of one mode (plus the client total)."""
    split = [s for s in (turn_stages(t) for t in turns) if s is not None and s.mode == mode]
    if not split:
        return []
    rows: list[StageRow] = []
    for stage in (*STAGES, "total"):
        if stage == "total":
            values = [s.total_s for s in split]
            owner = "total"
        else:
            values = [s.stages[stage] for s in split if stage in s.stages]
            owner = "gemini" if stage in GEMINI_STAGES else "saved" if stage in SAVED_STAGES else "ours"
        if not values:
            continue
        rows.append(
            StageRow(
                stage,
                owner,
                len(values),
                round(percentile(values, 50), 3),
                round(percentile(values, 95), 3),
                round(sum(values) / len(values), 3),
            )
        )
    return rows


def format_table(rows: Sequence[StageRow], title: str) -> list[str]:
    lines = [title, f"{'stage':<16}{'owner':<8}{'n':>4}{'p50 s':>9}{'p95 s':>9}{'mean s':>9}"]
    lines += [f"{r.stage:<16}{r.owner:<8}{r.n:>4}{r.p50:>9.3f}{r.p95:>9.3f}{r.mean:>9.3f}" for r in rows]
    return lines


__all__ = ["STAGES", "StageRow", "TurnStages", "format_table", "stage_table", "turn_stages"]
