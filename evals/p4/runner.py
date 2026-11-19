"""Runs P4 suites item by item, resumably, inside the call budget.

Per item: a new session in the item's language, then every user turn of the item through POST /chat. The
item is cached only when no model call was rate limited (a rate-limited turn degrades the pipeline, which
would measure our pacing rather than the product): after a minute-scope 429 the runner cools down and retries
the item; a day-scope 429 or the budget stops the run cleanly, keeping everything cached so far.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from evals.p4.items import EvalItem
from evals.p4.judge import (
    JudgeError,
    JudgeVerdict,
    answer_hash,
    check_independent,
    judge_answer,
    judge_model_id,
    judge_refusal,
)
from evals.p4.metrics import Ctx, all_records, is_answered, refusal_judge_records
from evals.p4.provider import DECIDE, GENERATE, CountingProvider
from evals.p4.results import ItemResult, TurnResult
from evals.p4.store import Store, utc_now

Sleep = Callable[[float], Awaitable[None]]
Log = Callable[[str], None]
COOLDOWN_S = 65.0
MAX_ATTEMPTS = 3
MAX_JUDGE_FAILURES = 2  # consecutive upstream failures (e.g. 503 "high demand") that end a judge pass
SUITE_ORDER = ("safety", "quality", "dose", "refusal", "latency")


class TurnDriver(Protocol):
    llm: CountingProvider

    async def new_session(self, locale: str) -> str: ...

    async def turn(self, token: str, message: str, locale: str) -> TurnResult: ...


@dataclass(frozen=True)
class RunOptions:
    limit: int | None = None
    pace_s: float = 0.0
    cooldown_s: float = COOLDOWN_S
    max_attempts: int = MAX_ATTEMPTS
    reserve_generate: int = 0  # stop before an item when fewer generation calls than this remain
    reserve_decide: int = 0


@dataclass
class RunSummary:
    suite: str
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""
    considered: int = 0
    cached: int = 0
    completed: int = 0
    discarded_attempts: int = 0
    given_up: list[str] = field(default_factory=list)
    stopped: str = ""
    calls: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "considered": self.considered,
            "cached": self.cached,
            "completed": self.completed,
            "discarded_attempts": self.discarded_attempts,
            "given_up": list(self.given_up),
            "stopped": self.stopped,
            "calls": dict(self.calls),
        }


def call_delta(calls: Sequence[Any], retries: int = 0) -> dict[str, Any]:
    real = [c for c in calls if c.outcome != "halted"]
    return {
        GENERATE: sum(1 for c in real if c.kind == GENERATE),
        DECIDE: sum(1 for c in real if c.kind == DECIDE),
        "retries": retries,
        "by_model": dict(Counter(f"{c.kind}:{c.model_id}" for c in real)),
    }


def _remaining(llm: CountingProvider, kind: str) -> int | None:
    cap = llm.max_generate if kind == GENERATE else llm.max_decide
    return None if cap is None else cap - llm.count(kind)


def _budget_short(llm: CountingProvider, opts: RunOptions) -> str:
    for kind, reserve in ((GENERATE, opts.reserve_generate), (DECIDE, opts.reserve_decide)):
        left = _remaining(llm, kind)
        if left is not None and left < max(1, reserve):
            return f"budget: {left} {kind} calls left (reserve {reserve})"
    return ""


async def run_item(driver: TurnDriver, item: EvalItem) -> ItemResult:
    token = await driver.new_session(item.lang)
    turns: list[TurnResult] = []
    for message in item.turns:
        turns.append(await driver.turn(token, message, item.lang))
    meta = next((p for t in turns for p in t.payloads if p.get("type") == "meta"), {})
    return ItemResult(
        item=item, turns=tuple(turns), finished_at=utc_now(), release=dict(meta.get("release", {}))
    )


def _line(item: EvalItem, result: ItemResult) -> str:
    last = result.last
    intent = (last.answer or {}).get("intent", "-")
    kinds = ",".join(sorted(result.detected_kinds)) or "-"
    gen = sum(1 for t in result.turns for _ in t.generation_roles())
    return (
        f"{item.id:<16} mode={last.mode:<9} intent={intent:<13} safety={kinds:<20} "
        f"gen={gen} t={last.elapsed_s:.1f}s"
    )


async def _attempt(
    driver: TurnDriver,
    store: Store,
    item: EvalItem,
    summary: RunSummary,
    log: Log,
    retries: Callable[[], int],
    *,
    last_attempt: bool = False,
) -> tuple[ItemResult | None, str]:
    """One attempt at an item. Returns (result to cache or None, stop reason). A stream that ended without
    `done` although the runner did not halt it (client-side timeout, e.g. after the machine slept) is retried;
    on the last attempt it is kept, so a turn that really never finishes counts as a failure."""
    llm = driver.llm
    llm.begin_item()
    before = retries()
    result = await run_item(driver, item)
    store.add_calls(call_delta(llm.item_calls(), retries() - before))
    if llm.day_quota_hit:
        return None, f"day quota exhausted ({llm.day_quota_hit})"
    if llm.over_budget:
        return None, "budget exhausted during the item"
    if llm.rate_limited:
        summary.discarded_attempts += 1
        log(f"{item.id}: rate limited ({','.join(llm.rate_limited)}), discarded")
        return None, ""
    if not last_attempt and any(not t.complete and not t.halted for t in result.turns):
        summary.discarded_attempts += 1
        log(f"{item.id}: stream ended without done, retried")
        return None, ""
    return result, ""


async def run_items(
    driver: TurnDriver,
    store: Store,
    suite: str,
    items: Sequence[EvalItem],
    opts: RunOptions,
    *,
    sleep: Sleep = asyncio.sleep,
    log: Log = print,
    retries: Callable[[], int] = lambda: 0,
) -> RunSummary:
    summary = RunSummary(suite=suite)
    chosen = list(items)[: opts.limit] if opts.limit is not None else list(items)
    for item in chosen:
        summary.considered += 1
        if store.has(suite, item.id):
            summary.cached += 1
            continue
        short = _budget_short(driver.llm, opts)
        if short:
            summary.stopped = short
            break
        for attempt in range(opts.max_attempts):
            last = attempt + 1 == opts.max_attempts
            result, stop = await _attempt(driver, store, item, summary, log, retries, last_attempt=last)
            if stop:
                summary.stopped = stop
                break
            if result is not None:
                store.put(result)
                summary.completed += 1
                log(_line(item, result))
                break
            if attempt + 1 < opts.max_attempts:
                await sleep(opts.cooldown_s)
        else:
            summary.given_up.append(item.id)
        if summary.stopped:
            break
        if opts.pace_s:
            await sleep(opts.pace_s)
    summary.finished_at = utc_now()
    summary.calls = driver.llm.totals()
    return summary


# ---- judge -----------------------------------------------------------------------------------------------
JUDGED_SUITES = ("quality", "dose")


def fallback_generated(turn: TurnResult) -> bool:
    return "answer_fallback" in turn.generation_roles()


def current_verdict(store: Store, result: ItemResult) -> JudgeVerdict | None:
    raw = store.get_judgement(result.item.suite, result.item.id)
    if raw is None:
        return None
    verdict = JudgeVerdict.from_dict(raw)
    text = str((result.last.answer or {}).get("text", ""))
    return verdict if verdict.answer_hash == answer_hash(text) else None


async def run_judge(
    llm: CountingProvider,
    store: Store,
    opts: RunOptions,
    *,
    tier: str = "free",
    suites: Sequence[str] = JUDGED_SUITES,
    sleep: Sleep = asyncio.sleep,
    log: Log = print,
) -> RunSummary:
    check_independent(tier)
    judge_id = judge_model_id(tier)
    summary = RunSummary(suite="judge")
    failures = 0
    todo = [r for s in suites for r in store.results(s) if is_answered(r.last)]
    for result in todo[: opts.limit] if opts.limit is not None else todo:
        summary.considered += 1
        if current_verdict(store, result) is not None:
            summary.cached += 1
            continue
        text = str((result.last.answer or {}).get("text", ""))
        if fallback_generated(result.last):
            store.put_judgement(result.item.suite, result.item.id, _skipped(text, judge_id))
            log(f"{result.item.id}: answer from the fallback model, not judged")
            continue
        short = _budget_short(llm, opts)
        if short:
            summary.stopped = short
            break
        llm.begin_item()
        try:
            verdict = await judge_answer(llm, text, result.last.passages)
        except JudgeError as exc:
            log(f"{result.item.id}: judge output unusable ({exc})")
            summary.given_up.append(result.item.id)
            continue
        except Exception as exc:
            log(f"{result.item.id}: judge call failed ({type(exc).__name__})")
            failures += 1
            stop = _judge_stop(llm, failures)
            if stop:
                summary.stopped = stop
                break
            summary.given_up.append(result.item.id)
            await sleep(opts.cooldown_s)
            continue
        finally:
            store.add_calls(call_delta(llm.item_calls()))
        failures = 0
        store.put_judgement(result.item.suite, result.item.id, verdict.to_dict())
        summary.completed += 1
        claims = verdict.supported + verdict.unsupported
        log(f"{result.item.id:<16} judged {verdict.supported}/{claims} supported")
        if opts.pace_s:
            await sleep(opts.pace_s)
    summary.finished_at = utc_now()
    summary.calls = llm.totals()
    return summary


async def run_refusal_judge(
    llm: CountingProvider,
    store: Store,
    opts: RunOptions,
    *,
    tier: str = "free",
    sleep: Sleep = asyncio.sleep,
    log: Log = print,
) -> RunSummary:
    """Extra (not gated) LLM check of released refusal answers: diagnosis, personal dose, triage verdict."""
    check_independent(tier)
    summary = RunSummary(suite="judge-refusal")
    failures = 0
    for result in [r for r in store.results("refusal") if is_answered(r.last)]:
        summary.considered += 1
        text = str((result.last.answer or {}).get("text", ""))
        cached = store.get_judgement("refusal", result.item.id)
        if cached is not None and cached.get("answer_hash") == answer_hash(text):
            summary.cached += 1
            continue
        short = _budget_short(llm, opts)
        if short:
            summary.stopped = short
            break
        llm.begin_item()
        try:
            verdict = await judge_refusal(llm, result.item.turns[-1], text)
        except Exception as exc:
            log(f"{result.item.id}: refusal judge failed ({type(exc).__name__})")
            failures += 1
            stop = _judge_stop(llm, failures)
            if stop:
                summary.stopped = stop
                break
            summary.given_up.append(result.item.id)
            await sleep(opts.cooldown_s)
            continue
        finally:
            store.add_calls(call_delta(llm.item_calls()))
        failures = 0
        store.put_judgement("refusal", result.item.id, verdict)
        summary.completed += 1
        flagged = sorted(k for k, v in verdict["flags"].items() if v)
        log(f"{result.item.id:<16} refusal judge: {','.join(flagged) or 'clean'}")
        if opts.pace_s:
            await sleep(opts.pace_s)
    summary.finished_at = utc_now()
    summary.calls = llm.totals()
    return summary


def refusal_judgements(store: Store) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for result in store.results("refusal"):
        raw = store.get_judgement("refusal", result.item.id)
        text = str((result.last.answer or {}).get("text", ""))
        if raw is not None and raw.get("answer_hash") == answer_hash(text):
            out[result.item.id] = raw
    return out


def _judge_stop(llm: CountingProvider, failures: int) -> str:
    if llm.day_quota_hit or llm.over_budget:
        return llm.day_quota_hit or "budget exhausted"
    if failures >= MAX_JUDGE_FAILURES:
        return f"judge model unavailable ({failures} consecutive failures)"
    return ""


def _skipped(text: str, judge_id: str) -> dict[str, Any]:
    verdict = JudgeVerdict((), (), judge_id, answer_hash(text))
    return {**verdict.to_dict(), "skipped": "fallback model is the judge model"}


# ---- metrics ---------------------------------------------------------------------------------------------
def verdict_pairs(store: Store) -> list[tuple[ItemResult, JudgeVerdict]]:
    pairs = []
    for suite in JUDGED_SUITES:
        for result in store.results(suite):
            if not is_answered(result.last):
                continue
            verdict = current_verdict(store, result)
            if verdict is not None:
                pairs.append((result, verdict))
    return pairs


def write_metrics(store: Store, *, free_tier: bool, measured_at: str | None = None) -> list[dict[str, Any]]:
    by_suite = {s: store.results(s) for s in SUITE_ORDER}
    ctx = Ctx(measured_at or utc_now(), free_tier)
    records = all_records(by_suite, verdict_pairs(store), ctx)
    records += refusal_judge_records(by_suite["refusal"], refusal_judgements(store), ctx)
    store.write_metrics(records)
    return records
