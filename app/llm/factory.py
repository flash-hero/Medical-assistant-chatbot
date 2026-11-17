"""Composition roots for the LLM provider and the embedding provider."""

from __future__ import annotations

from core.config import Settings
from core.models import embedding_spec
from core.ports import EmbeddingProvider, LLMProvider, SpendMeter


def build_llm_provider(settings: Settings, *, spend: SpendMeter | None = None) -> LLMProvider:
    if settings.llm_backend == "fake":
        from evals.fakes.fake_llm import FakeLLMProvider

        return FakeLLMProvider()
    from app.llm.gemini_provider import GeminiProvider

    return GeminiProvider(settings, spend=spend)


def build_embedding_provider(settings: Settings, *, llm: LLMProvider | None = None) -> EmbeddingProvider:
    """Embedding backend from AUSCULTA_EMBED_BACKEND: "local" (default, EmbeddingGemma on this machine),
    "gemini" (API; reuses `llm` when it is the Gemini provider), or "fake" (tests)."""
    spec = embedding_spec(settings.embed_backend)
    if spec.backend == "fake":
        from evals.fakes.fake_llm import FakeLLMProvider

        return FakeLLMProvider()
    if spec.backend == "gemini":
        if llm is not None and settings.llm_backend == "gemini":
            return llm
        from app.llm.gemini_provider import GeminiProvider

        return GeminiProvider(settings)
    from app.llm.local_embedder import LocalEmbeddingProvider, fastembed_factory

    return LocalEmbeddingProvider(
        spec.model_id,
        spec.dim,
        fastembed_factory(spec.model_id, settings.models_dir, settings.embed_threads),
    )
