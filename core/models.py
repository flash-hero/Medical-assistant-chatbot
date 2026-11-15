"""Pinned model IDs per role. The ONLY place in the codebase where a model ID may appear.

See docs/decisions/0001-model-selection.md for the measurements behind these choices.
Never use `-latest` aliases or deprecated families (gemini-2.5-*, gemini-3.1-flash-lite, *-preview).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ModelRole(StrEnum):
    ANSWER = "answer"
    ANSWER_FALLBACK = "answer_fallback"
    GUARD = "guard"
    GUARD_FALLBACK = "guard_fallback"
    REWRITE = "rewrite"
    RERANK = "rerank"
    VERIFY = "verify"
    JUDGE = "judge"
    EMBED = "embed"


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    thinking_level: str | None = None  # None = model default; only set where measured useful
    max_output_tokens: int | None = None  # includes thinking tokens
    timeout_s: float = 30.0
    usd_per_m_input: float = 0.0
    usd_per_m_output: float = 0.0
    paid_only: bool = False


EMBED_DIM = 768
EMBED_QUERY_PREFIX = "task: search result | query: "
EMBED_MAX_BATCH = 100  # API limit, measured in spike S1

# Prices are standard-tier list prices (USD per 1M tokens) as of 2026-11-15; used for spend estimates only.
_FREE_TIER: dict[ModelRole, ModelSpec] = {
    ModelRole.ANSWER: ModelSpec("gemini-3.5-flash-lite", None, 1200, 20.0, 0.30, 2.50),
    ModelRole.ANSWER_FALLBACK: ModelSpec("gemini-3.6-flash", "low", 2400, 30.0, 0.75, 3.75),
    ModelRole.GUARD: ModelSpec("gemini-decision-1", None, None, 4.0, 0.10, 0.0),
    ModelRole.GUARD_FALLBACK: ModelSpec("gemini-3.5-flash-lite", None, 400, 6.0, 0.30, 2.50),
    ModelRole.REWRITE: ModelSpec("gemini-3.5-flash-lite", None, 400, 6.0, 0.30, 2.50),
    ModelRole.RERANK: ModelSpec("gemini-decision-1", None, None, 5.0, 0.10, 0.0),
    ModelRole.VERIFY: ModelSpec("gemini-decision-1", None, None, 6.0, 0.10, 0.0),
    ModelRole.JUDGE: ModelSpec("gemini-3.6-flash", "low", 4000, 60.0, 0.75, 3.75),
    ModelRole.EMBED: ModelSpec("gemini-embedding-2", None, None, 30.0, 0.20, 0.0),
}

_PAID_OVERRIDES: dict[ModelRole, ModelSpec] = {
    ModelRole.JUDGE: ModelSpec("gemini-4-argon", "low", 4000, 90.0, 4.00, 20.00, paid_only=True),
}


def model_for(role: ModelRole, tier: str = "free") -> ModelSpec:
    """Return the pinned model for a role on the given billing tier ("free" | "paid")."""
    if tier == "paid" and role in _PAID_OVERRIDES:
        return _PAID_OVERRIDES[role]
    return _FREE_TIER[role]


def all_model_ids(tier: str = "free") -> frozenset[str]:
    return frozenset(model_for(r, tier).model_id for r in ModelRole)
