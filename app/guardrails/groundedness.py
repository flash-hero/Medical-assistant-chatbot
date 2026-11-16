"""Sentence-level groundedness: one VERIFY decide call with one noul question per answer sentence
("is this sentence supported by the passages?"). Unsupported sentences are removed; the caller abstains when
too
little remains. Falls back to a GUARD_FALLBACK JSON classifier; when both fail the result is `available=False`
(verify-then-release answers must then abstain).
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from app.guardrails.safety_config import GroundednessConfig
from core.errors import UpstreamError
from core.models import ModelRole
from core.ports import DecisionQuestion, GenerationRequest, LLMProvider

log = structlog.get_logger(__name__)
_MAX_SENTENCE_CHARS = 600


@dataclass(frozen=True)
class VerifyPrompts:
    preamble: str
    question: str  # contains {sentence}
    fallback_system: str


@dataclass(frozen=True)
class GroundednessResult:
    supported: tuple[bool, ...]  # one flag per input sentence
    available: bool  # False when no verifier could run
    blocked: bool = False  # the provider blocked the verification input (a risk signal)
    model_id: str = ""

    @property
    def kept_ratio(self) -> float:
        return sum(self.supported) / len(self.supported) if self.supported else 0.0


def _passages_block(passages: Sequence[str], nonce: str) -> str:
    parts = [
        f'<passage n="{i}" nonce="{nonce}">\n{p}\n</passage nonce="{nonce}">'
        for i, p in enumerate(passages, 1)
    ]
    return "\n".join(parts)


def _escape(sentence: str) -> str:
    return sentence.replace("«", '"').replace("»", '"')[:_MAX_SENTENCE_CHARS]


class GroundednessVerifier:
    def __init__(
        self, llm: LLMProvider, prompts: VerifyPrompts, config: GroundednessConfig, *, timeout_s: float = 8.0
    ) -> None:
        self._llm = llm
        self._prompts = prompts
        self._cfg = config
        self._timeout = timeout_s

    async def verify(self, sentences: Sequence[str], passages: Sequence[str]) -> GroundednessResult:
        if not sentences:
            return GroundednessResult(supported=(), available=True)
        nonce = secrets.token_hex(6)
        context = f"{self._prompts.preamble}\n{_passages_block(passages, nonce)}"
        flags: list[bool] = []
        model_id = ""
        step = self._cfg.max_sentences_per_call
        for start in range(0, len(sentences), step):
            batch = sentences[start : start + step]
            result = await self._verify_batch(batch, context)
            if not result.available or result.blocked:
                return GroundednessResult(
                    supported=tuple(False for _ in sentences),
                    available=result.available,
                    blocked=result.blocked,
                )
            flags.extend(result.supported)
            model_id = result.model_id
        return GroundednessResult(supported=tuple(flags), available=True, model_id=model_id)

    async def _verify_batch(self, batch: Sequence[str], context: str) -> GroundednessResult:
        questions = {
            f"s{i}": DecisionQuestion(
                kind="noul", instructions=self._prompts.question.format(sentence=_escape(s))
            )
            for i, s in enumerate(batch)
        }
        try:
            # asyncio.timeout, not wait_for: on Python 3.11 wait_for swallows an outer task.cancel() when the
            # call finishes in the same loop iteration, so a cancelled turn would keep running.
            async with asyncio.timeout(self._timeout):
                res = await self._llm.decide(ModelRole.VERIFY, context, questions)
            flags = tuple(
                (res.answers[k].noul or 0.0) >= self._cfg.supported_min
                for k in sorted(questions, key=_key_index)
            )
            return GroundednessResult(supported=flags, available=True, model_id=res.model_id)
        except (UpstreamError, TimeoutError, KeyError) as exc:
            if getattr(exc, "code", "") == "upstream_blocked":
                return GroundednessResult(supported=(), available=True, blocked=True)
            log.warning("verify_decide_failed", error=type(exc).__name__)
        return await self._fallback(batch, context)

    async def _fallback(self, batch: Sequence[str], context: str) -> GroundednessResult:
        ids = [f"s{i}" for i in range(len(batch))]
        schema: Mapping[str, Any] = {
            "type": "object",
            "properties": {k: {"type": "boolean"} for k in ids},
            "required": ids,
        }
        listing = "\n".join(f'{k}: "{_escape(s)}"' for k, s in zip(ids, batch, strict=True))
        request = GenerationRequest(
            role=ModelRole.GUARD_FALLBACK,
            system=self._prompts.fallback_system,
            prompt=f"{context}\n\nSENTENCES:\n{listing}",
            json_schema=schema,
            timeout_s=self._timeout,
        )
        try:
            async with asyncio.timeout(self._timeout):  # not wait_for: see _verify_batch
                out = await self._llm.generate(request)
            data = json.loads(out.text)
            flags = tuple(data.get(k) is True for k in ids)
            return GroundednessResult(supported=flags, available=True, model_id=out.model_id)
        except (UpstreamError, TimeoutError, ValueError, AttributeError) as exc:
            if getattr(exc, "code", "") == "upstream_blocked":
                return GroundednessResult(supported=(), available=True, blocked=True)
            log.warning("verify_fallback_failed", error=type(exc).__name__)
            return GroundednessResult(supported=(), available=False)


def _key_index(key: str) -> int:
    return int(key[1:])
