"""Query rewrite (REWRITE role, JSON schema): standalone query in the user's language, English search queries and
content-type filters. Skipped (no model call) when the message is already standalone English, to save quota."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.pipeline.prompts import build_rewrite_prompt
from core.errors import UpstreamError
from core.models import ModelRole
from core.ports import GenerationRequest, LLMProvider
from core.schemas.chat import Intent, Locale, RetrievalQuery
from core.schemas.source import ContentType

log = structlog.get_logger(__name__)
_ANAPHORA = re.compile(
    r"\b(?:it|its|this|that|these|those|they|them|their|he|she|him|her|the same|what about|and for|also)\b",
    re.IGNORECASE,
)
_ALLOWED_TYPES = frozenset(t.value for t in ContentType) - {ContentType.HOSPITAL.value, ContentType.TEXTBOOK.value}
MAX_QUERY_CHARS = 500


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


def is_standalone_english(message: str, language: Locale, history: Sequence[str]) -> bool:
    words = message.split()
    if language != "en" or len(words) < 3:
        return False
    return not history or not _ANAPHORA.search(message)


def _filters(types: Sequence[str], intent: Intent) -> dict[str, list[str]]:
    allowed = [t for t in dict.fromkeys(types) if t in _ALLOWED_TYPES]
    if not allowed or (intent is Intent.MEDICATION and ContentType.DRUG_LABEL.value not in allowed):
        return {}
    return {"content_type": allowed}


class QueryRewriter:
    def __init__(self, llm: LLMProvider, system_prompt: str, *, timeout_s: float = 6.0, top_k: int = 8) -> None:
        self._llm = llm
        self._system = system_prompt
        self._timeout = timeout_s
        self._top_k = top_k

    def plain(self, message: str, language: Locale) -> RetrievalQuery:
        return RetrievalQuery(standalone_query=message[:MAX_QUERY_CHARS], language=language, top_k=self._top_k)

    async def rewrite(
        self, message: str, history: Sequence[str], language: Locale, intent: Intent
    ) -> RewriteOutcome:
        if is_standalone_english(message, language, history):
            return RewriteOutcome(query=self.plain(message, language), used_model=False)
        request = GenerationRequest(
            role=ModelRole.REWRITE,
            system=self._system,
            prompt=build_rewrite_prompt(message, history[-3:]),
            json_schema=REWRITE_SCHEMA,
            timeout_s=self._timeout,
        )
        try:
            out = await asyncio.wait_for(self._llm.generate(request), self._timeout + 1)
            data = _RewriteJSON.model_validate(json.loads(out.text))
        except (UpstreamError, TimeoutError, ValueError, ValidationError) as exc:
            log.warning("rewrite_failed", error=type(exc).__name__)
            return RewriteOutcome(query=self.plain(message, language), used_model=True, error=type(exc).__name__)
        extra = tuple(q.strip()[:200] for q in data.search_queries_en if q.strip())[:3]
        query = RetrievalQuery(
            standalone_query=data.standalone_query.strip()[:MAX_QUERY_CHARS] or message[:MAX_QUERY_CHARS],
            search_queries=extra,
            language=language,
            filters=_filters(data.content_types, intent),
            top_k=self._top_k,
        )
        return RewriteOutcome(query=query, used_model=True)
