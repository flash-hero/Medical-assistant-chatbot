"""Deterministic in-process fake of core.ports.LLMProvider.

Used by unit tests, contract tests and load tests (AUSCULTA_LLM_BACKEND=fake). Features:
  - lexical feature-hashing embeddings (similar texts -> similar unit vectors), any dimension
  - scripted generation via a `responder` callable, streamed in small chunks with optional delay
  - decision answers via a `decider` callable (default: neutral, low-risk answers)
  - failure injection per role, latency injection, and counters for open streams (cancellation tests)
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field

from core.models import ModelRole, model_for
from core.ports import (
    DecisionAnswer,
    DecisionQuestion,
    DecisionResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
)

_TOKEN = re.compile(r"\w+", re.UNICODE)

Responder = Callable[[GenerationRequest], str]
Decider = Callable[[str, str, DecisionQuestion], DecisionAnswer]


def default_responder(request: GenerationRequest) -> str:
    if request.json_schema is not None:
        return "{}"
    return "This is a deterministic test answer based on the provided sources [1]."


def default_decider(input_text: str, key: str, q: DecisionQuestion) -> DecisionAnswer:
    if q.kind == "noul":
        return DecisionAnswer(kind="noul", confidence=0.99, noul=0.01)
    if q.kind == "choice":
        options = list(q.criteria.keys()) if isinstance(q.criteria, Mapping) else ["unknown"]
        return DecisionAnswer(kind="choice", confidence=0.9, choice=options[0], probabilities={options[0]: 0.9})
    levels = list(q.criteria or ["0", "1"])
    return DecisionAnswer(kind="score", confidence=0.9, score=float(len(levels) - 1) / 2)


def hash_embed(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    for tok in _TOKEN.findall(text.casefold()):
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
        vec[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@dataclass
class FakeLLMProvider:
    responder: Responder = default_responder
    decider: Decider = default_decider
    chunk_chars: int = 24
    chunk_delay_s: float = 0.0
    latency_s: float = 0.0
    failures: dict[ModelRole, Exception] = field(default_factory=dict)
    embed_failures_remaining: int = 0  # raise UpstreamRateLimited-like errors on the next N embed calls
    embed_error: Exception | None = None
    calls: list[tuple[str, ModelRole | None, int]] = field(default_factory=list)  # (kind, role, n_items)
    open_streams: int = 0
    max_open_streams: int = 0
    closed_streams: int = 0

    def _maybe_fail(self, role: ModelRole) -> None:
        if role in self.failures:
            raise self.failures[role]

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(("generate", request.role, 1))
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        self._maybe_fail(request.role)
        text = self.responder(request)
        return GenerationResult(
            text=text,
            finish_reason="STOP",
            model_id=model_for(request.role).model_id,
            input_tokens=len(_TOKEN.findall(request.system + request.prompt)),
            output_tokens=len(_TOKEN.findall(text)),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        self.calls.append(("stream", request.role, 1))
        self.open_streams += 1
        self.max_open_streams = max(self.max_open_streams, self.open_streams)
        try:
            if self.latency_s:
                await asyncio.sleep(self.latency_s)
            self._maybe_fail(request.role)
            text = self.responder(request)
            pieces = [text[i : i + self.chunk_chars] for i in range(0, len(text), self.chunk_chars)] or [""]
            for i, piece in enumerate(pieces):
                if self.chunk_delay_s:
                    await asyncio.sleep(self.chunk_delay_s)
                yield GenerationChunk(text=piece, finish_reason="STOP" if i == len(pieces) - 1 else None)
        finally:
            self.open_streams -= 1
            self.closed_streams += 1

    async def decide(
        self, role: ModelRole, input_text: str, questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        self.calls.append(("decide", role, len(questions)))
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        self._maybe_fail(role)
        answers = {k: self.decider(input_text, k, q) for k, q in questions.items()}
        return DecisionResult(answers=answers, model_id=model_for(role).model_id, input_tokens=len(input_text) // 4)

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        self.calls.append(("embed", ModelRole.EMBED, len(texts)))
        if self.embed_failures_remaining > 0 and self.embed_error is not None:
            self.embed_failures_remaining -= 1
            raise self.embed_error
        self._maybe_fail(ModelRole.EMBED)
        return [hash_embed(t, dim) for t in texts]

    def count(self, kind: str) -> int:
        return sum(1 for c in self.calls if c[0] == kind)
