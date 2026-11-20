"""Query rewrite (REWRITE role, JSON schema): standalone query in the user's language, English search queries
and content-type filters. Skipped (no model call) when the message is already standalone English, to save
quota.

The engine may start the rewrite call before the guard verdict (`prefetch`, P4 latency): the call needs only
the message and the history, so it runs concurrently with the guard decide. `rewrite(..., pending=...)` then
consumes it; the engine cancels it whenever the medical path does not use it (safety / strike / block verdict,
another intent, deadline, disconnect). The intent-dependent part (filters) is applied after the verdict.

A provider block on the rewrite call (UpstreamBlocked) is a risk signal about the user's message and is
re-raised, never downgraded to "rewrite failed" (review C8). Medication questions always search drug labels
only (review C7)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.pipeline.prompts import build_rewrite_prompt
from core.errors import UpstreamBlocked, UpstreamError
from core.models import ModelRole
from core.ports import GenerationRequest, LLMProvider
from core.schemas.chat import Intent, Locale, RetrievalQuery
from core.schemas.source import ContentType

log = structlog.get_logger(__name__)
_ANAPHORA = re.compile(
    r"\b(?:it|its|this|that|these|those|they|them|their|he|she|him|her|the same|what about|and for|also)\b",
    re.IGNORECASE,
)
_ALLOWED_TYPES = frozenset(t.value for t in ContentType) - {
    ContentType.HOSPITAL.value,
    ContentType.TEXTBOOK.value,
}
MAX_QUERY_CHARS = 500
DRUG_LABEL_FILTER: dict[str, list[str]] = {"content_type": [ContentType.DRUG_LABEL.value]}


class _RewriteJSON(BaseModel):
    model_config = ConfigDict(extra="ignore")

    standalone_query: str = Field(min_length=1, max_length=1000)
    search_queries_en: list[str] = Field(default_factory=list, max_length=5)
    content_types: list[str] = Field(default_factory=list, max_length=6)


REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "standalone_query": {"type": "string"},
        "search_queries_en": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "content_types": {"type": "array", "items": {"type": "string", "enum": sorted(_ALLOWED_TYPES)}},
    },
    "required": ["standalone_query", "search_queries_en", "content_types"],
}


@dataclass(frozen=True)
class RewriteOutcome:
    query: RetrievalQuery
    used_model: bool
    error: str | None = None


@dataclass(frozen=True)
class PendingRewrite:
    """A rewrite call started before the guard verdict. Whoever does not consume it must cancel() it."""

    message: str
    history: tuple[str, ...]
    task: asyncio.Task[_RewriteJSON] = field(compare=False)

    def matches(self, message: str, history: Sequence[str]) -> bool:
        return self.message == message and self.history == tuple(history) and not self.task.cancelled()

    def cancel(self) -> None:
        """Cancel the call, or mark a finished call's exception as retrieved (no asyncio warning)."""
        if not self.task.done():
            self.task.cancel()
        elif not self.task.cancelled():
            self.task.exception()


def is_standalone_english(message: str, language: Locale, history: Sequence[str]) -> bool:
    words = message.split()
    if language != "en" or len(words) < 3:
        return False
    return not history or not _ANAPHORA.search(message)


def intent_filters(intent: Intent) -> dict[str, list[str]]:
    """Filters every query of this intent must carry (medication -> drug labels only)."""
    return {k: list(v) for k, v in DRUG_LABEL_FILTER.items()} if intent is Intent.MEDICATION else {}


def _filters(types: Sequence[str], intent: Intent) -> dict[str, list[str]]:
    if intent is Intent.MEDICATION:
        return intent_filters(intent)
    allowed = [t for t in dict.fromkeys(types) if t in _ALLOWED_TYPES]
    return {"content_type": allowed} if allowed else {}


class QueryRewriter:
    def __init__(
        self, llm: LLMProvider, system_prompt: str, *, timeout_s: float = 6.0, top_k: int = 8
    ) -> None:
        self._llm = llm
        self._system = system_prompt
        self._timeout = timeout_s
        self._top_k = top_k

    def plain(self, message: str, language: Locale) -> RetrievalQuery:
        return RetrievalQuery(
            standalone_query=message[:MAX_QUERY_CHARS], language=language, top_k=self._top_k
        )

    def prefetch(self, message: str, history: Sequence[str], language: Locale) -> PendingRewrite | None:
        """Start the rewrite call now (before the guard verdict); None when no call would be made."""
        if is_standalone_english(message, language, history):
            return None
        hist = tuple(history)
        task = asyncio.create_task(self._call(message, hist), name="rewrite-prefetch")
        return PendingRewrite(message, hist, task)

    async def _call(self, message: str, history: Sequence[str]) -> _RewriteJSON:
        request = GenerationRequest(
            role=ModelRole.REWRITE,
            system=self._system,
            prompt=build_rewrite_prompt(message, history[-3:]),
            json_schema=REWRITE_SCHEMA,
            timeout_s=self._timeout,
        )
        # asyncio.timeout, not wait_for: on 3.11 wait_for can swallow a turn cancellation
        async with asyncio.timeout(self._timeout + 1):
            out = await self._llm.generate(request)
        return _RewriteJSON.model_validate(json.loads(out.text))

    async def rewrite(
        self,
        message: str,
        history: Sequence[str],
        language: Locale,
        intent: Intent,
        *,
        pending: PendingRewrite | None = None,
    ) -> RewriteOutcome:
        if is_standalone_english(message, language, history):
            if pending is not None:
                pending.cancel()
            return RewriteOutcome(query=self.plain(message, language), used_model=False)
        try:
            if pending is not None and pending.matches(message, history):
                data = await pending.task
            else:
                if pending is not None:
                    pending.cancel()
                data = await self._call(message, history)
        except UpstreamBlocked:
            raise
        except (UpstreamError, TimeoutError, ValueError, ValidationError) as exc:
            log.warning("rewrite_failed", error=type(exc).__name__)
            return RewriteOutcome(
                query=self.plain(message, language), used_model=True, error=type(exc).__name__
            )
        extra = tuple(q.strip()[:200] for q in data.search_queries_en if q.strip())[:3]
        query = RetrievalQuery(
            standalone_query=data.standalone_query.strip()[:MAX_QUERY_CHARS] or message[:MAX_QUERY_CHARS],
            search_queries=extra,
            language=language,
            filters=_filters(data.content_types, intent),
            top_k=self._top_k,
        )
        return RewriteOutcome(query=query, used_model=True)
