"""Ports (interfaces) between packages. Implementations:

  LLMProvider     app/llm/gemini_provider.py (real), evals/fakes/fake_llm.py (deterministic fake)
  Embedder        rag/embedding.py (uses LLMProvider.embed)
  Retriever       rag/retrieval.py (Qdrant hybrid + rerank), evals/fakes/fake_retriever.py
  stores/limits   app/storage/*, app/limits/* (Redis/Postgres in prod, in-memory/SQLite in dev)

Every port has a fake in evals/fakes so each package is testable without network or services.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from core.models import ModelRole
from core.schemas.chat import RetrievalQuery, RetrievalResult


# ---- LLM ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GenerationRequest:
    role: ModelRole  # selects the pinned model (ANSWER, ANSWER_FALLBACK, REWRITE, GUARD_FALLBACK, JUDGE)
    system: str
    prompt: str
    max_output_tokens: int | None = None  # None = ModelSpec default
    json_schema: Mapping[str, Any] | None = None  # set -> response is JSON matching this schema
    timeout_s: float | None = None


@dataclass(frozen=True)
class GenerationChunk:
    text: str
    finish_reason: str | None = None  # "STOP" | "MAX_TOKENS" | "SAFETY" | ... on the last chunk


@dataclass(frozen=True)
class GenerationResult:
    text: str
    finish_reason: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class DecisionQuestion:
    kind: Literal["noul", "choice", "score"]
    instructions: str
    criteria: Mapping[str, str] | Sequence[str] | None = None  # choice: option->desc; score: levels


@dataclass(frozen=True)
class DecisionAnswer:
    kind: Literal["noul", "choice", "score"]
    confidence: float
    noul: float | None = None  # P(yes)
    choice: str | None = None
    score: float | None = None  # probability-weighted level index
    probabilities: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionResult:
    answers: Mapping[str, DecisionAnswer]
    model_id: str
    input_tokens: int = 0
    latency_ms: float = 0.0


@runtime_checkable
class LLMProvider(Protocol):
    """Single gateway to the model API. Owns retries, timeouts, spend accounting and error mapping
    (raises only core.errors.Upstream* errors). Never stores prompts (Gemini store=False)."""

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        """Async generator; cancelling the consumer must close the upstream HTTP stream."""
        ...

    async def decide(
        self, role: ModelRole, input_text: str, questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult: ...

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        """Embeds already-prefixed texts (see core.models.EMBED_QUERY_PREFIX / Chunk.embedding_text).
        Batches internally (max 100 per API call). Returns unit-norm vectors, one per input."""
        ...


# ---- Retrieval ---------------------------------------------------------------------------------
@runtime_checkable
class Retriever(Protocol):
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult: ...

    async def health(self) -> bool: ...

    @property
    def corpus_version(self) -> str: ...


# ---- Spend / limits ----------------------------------------------------------------------------
@runtime_checkable
class SpendMeter(Protocol):
    async def reserve(self, usd: float) -> str:
        """Reserve estimated spend; raises SpendCapReached. Returns a reservation id."""
        ...

    async def settle(self, reservation_id: str, actual_usd: float) -> None: ...

    async def spent_today(self) -> float: ...
