"""LLMProvider wrapper for the P4 runs: counts every model call, enforces the call budget, notices quota
exhaustion, and can halt the turn before generation.

- Counting: one record per provider call (generate / stream / decide) with role and model id. HTTP retries
  inside the Gemini provider are counted separately by CountingRetryPolicy (each retry = one more request).
- Budget: past `max_generate` / `max_decide` calls the wrapper raises BudgetExceeded (an UpstreamUnavailable,
  so the pipeline degrades instead of crashing) and sets `over_budget`; the runner then discards that item.
- Quota: every UpstreamRateLimited is recorded. `day_quota_hit` is set for a day-scope 429 (or a retry hint
  of five minutes or more); the runner stops cleanly and keeps the partial results.
- Halt: generation calls of the roles in `halt_roles` (rewrite / answer) park until the turn is cancelled.
  The safety suite uses it: the safety decision is complete before any of those calls, so it costs only the
  guard's decide call (plus the guard fallback when decide fails, which is never halted).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from app.llm.retry import RetryPolicy
from core.errors import UpstreamRateLimited, UpstreamUnavailable
from core.models import ModelRole, model_for
from core.ports import (
    DecisionQuestion,
    DecisionResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    LLMProvider,
)

GENERATE = "generate"
DECIDE = "decide"
DAY_HINT_S = 300.0
HALT_ROLES: frozenset[ModelRole] = frozenset({ModelRole.REWRITE, ModelRole.ANSWER, ModelRole.ANSWER_FALLBACK})


class BudgetExceeded(UpstreamUnavailable):
    code = "p4_budget_exceeded"


@dataclass(frozen=True)
class CallRecord:
    kind: str  # GENERATE | DECIDE
    role: str
    model_id: str
    outcome: str = "ok"  # "ok" | error code | "halted"
    scope: str = ""  # rate-limit scope, when rate limited

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "role": self.role,
            "model_id": self.model_id,
            "outcome": self.outcome,
            "scope": self.scope,
        }


@dataclass(frozen=True)
class CountingRetryPolicy(RetryPolicy):
    """The production retry policy, plus a log of every retry (each one is one more HTTP request)."""

    retries: list[float] = field(default_factory=list, compare=False)

    def delay(self, attempt: int, retry_after_s: float | None, rng: Any) -> float:
        wait = super().delay(attempt, retry_after_s, rng)
        self.retries.append(wait)
        return wait


@dataclass
class CountingProvider:
    inner: LLMProvider
    tier: str = "free"
    max_generate: int | None = None
    max_decide: int | None = None
    halt_roles: frozenset[ModelRole] = frozenset()
    calls: list[CallRecord] = field(default_factory=list)
    item_start: int = 0
    over_budget: bool = False
    day_quota_hit: str = ""  # "<model_id>: <scope>" when a day-scope quota was exhausted
    rate_limited: list[str] = field(default_factory=list)  # model ids, one per rate-limited call

    # ---- bookkeeping -----------------------------------------------------------------------------
    def begin_item(self) -> None:
        self.item_start = len(self.calls)
        self.rate_limited = []

    def item_calls(self) -> list[CallRecord]:
        return self.calls[self.item_start :]

    def count(self, kind: str) -> int:
        return sum(1 for c in self.calls if c.kind == kind and c.outcome != "halted")

    def totals(self) -> dict[str, int]:
        return {GENERATE: self.count(GENERATE), DECIDE: self.count(DECIDE)}

    def by_model(self) -> dict[str, int]:
        return dict(Counter(f"{c.kind}:{c.model_id}" for c in self.calls if c.outcome != "halted"))

    def _model(self, role: ModelRole) -> str:
        return model_for(role, self.tier).model_id

    def _admit(self, kind: str, role: ModelRole) -> int:
        cap = self.max_generate if kind == GENERATE else self.max_decide
        if cap is not None and self.count(kind) >= cap:
            self.over_budget = True
            raise BudgetExceeded(f"P4 {kind} budget of {cap} calls used")
        self.calls.append(CallRecord(kind, role.value, self._model(role)))
        return len(self.calls) - 1

    def _mark(self, index: int, outcome: str, scope: str = "") -> None:
        old = self.calls[index]
        self.calls[index] = CallRecord(old.kind, old.role, old.model_id, outcome, scope)

    def _failed(self, index: int, exc: BaseException) -> None:
        code = getattr(exc, "code", type(exc).__name__)
        if isinstance(exc, UpstreamRateLimited):
            self._mark(index, code, exc.scope)
            self.rate_limited.append(self.calls[index].model_id)
            long_hint = (exc.retry_after_s or 0.0) >= DAY_HINT_S
            if exc.scope == "day" or long_hint:
                self.day_quota_hit = f"{self.calls[index].model_id}: {exc.scope}"
            return
        self._mark(index, str(code))

    async def _park(self, index: int) -> None:
        self._mark(index, "halted")
        await asyncio.Event().wait()  # until the turn is cancelled (client disconnect)

    # ---- LLMProvider -----------------------------------------------------------------------------
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        index = self._admit(GENERATE, request.role)
        if request.role in self.halt_roles:
            await self._park(index)
        try:
            return await self.inner.generate(request)
        except Exception as exc:
            self._failed(index, exc)
            raise

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        index = self._admit(GENERATE, request.role)
        if request.role in self.halt_roles:
            await self._park(index)
        try:
            async with aclosing(self.inner.stream(request)) as chunks:  # type: ignore[type-var]
                async for chunk in chunks:
                    yield chunk
        except Exception as exc:
            self._failed(index, exc)
            raise

    async def decide(
        self, role: ModelRole, input_text: str, questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        index = self._admit(DECIDE, role)
        try:
            return await self.inner.decide(role, input_text, questions)
        except Exception as exc:
            self._failed(index, exc)
            raise

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        return await self.inner.embed(texts, dim=dim)

    async def aclose(self) -> None:
        closer = getattr(self.inner, "aclose", None)
        if closer is not None:
            result = closer()
            if hasattr(result, "__await__"):
                await result
