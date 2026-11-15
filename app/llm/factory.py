"""Composition root for the LLM provider (real Gemini or the deterministic fake)."""

from __future__ import annotations

from core.config import Settings
from core.ports import LLMProvider, SpendMeter


def build_llm_provider(settings: Settings, *, spend: SpendMeter | None = None) -> LLMProvider:
    if settings.llm_backend == "fake":
        from evals.fakes.fake_llm import FakeLLMProvider

        return FakeLLMProvider()
    from app.llm.gemini_provider import GeminiProvider

    return GeminiProvider(settings, spend=spend)
