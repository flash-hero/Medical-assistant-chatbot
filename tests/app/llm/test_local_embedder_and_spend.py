"""Local embedding provider (no model download: injected fake model) and the stream spend-leak fix."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from app.limits.spend import MemorySpendMeter
from app.llm.factory import build_embedding_provider
from app.llm.gemini_provider import GeminiProvider
from app.llm.local_embedder import LocalEmbeddingProvider
from core.config import Settings
from core.errors import UpstreamUnavailable
from core.models import ModelRole
from core.ports import EmbeddingProvider, GenerationRequest


class FakeModel:
    def __init__(self, dim: int = 8, fail: bool = False) -> None:
        self.dim, self.fail, self.calls = dim, fail, 0

    def embed(self, documents: Any, batch_size: int = 16) -> Any:
        self.calls += 1
        if self.fail:
            raise RuntimeError("onnx exploded")
        for i, _ in enumerate(documents):
            v = np.zeros(self.dim, dtype=np.float32)
            v[i % self.dim] = 3.0  # not unit length on purpose
            yield v


async def test_local_provider_embeds_in_order_unit_norm_and_lazily_loads() -> None:
    built: list[FakeModel] = []

    def factory() -> FakeModel:
        built.append(FakeModel())
        return built[-1]

    provider = LocalEmbeddingProvider("m", 8, factory)
    assert isinstance(provider, EmbeddingProvider)
    assert built == []  # nothing loaded until needed
    vecs = await provider.embed(["a", "b", "c"], dim=8)
    assert len(vecs) == 3
    assert [v.index(max(v)) for v in vecs] == [0, 1, 2]
    assert all(abs(sum(x * x for x in v) - 1.0) < 1e-6 for v in vecs)
    await provider.embed(["d"], dim=8)
    assert len(built) == 1  # loaded once
    assert await provider.embed([], dim=8) == []


async def test_local_provider_rejects_wrong_dim_and_maps_failures() -> None:
    provider = LocalEmbeddingProvider("m", 8, lambda: FakeModel())
    with pytest.raises(ValueError, match="8-dim"):
        await provider.embed(["x"], dim=768)
    broken = LocalEmbeddingProvider("m", 8, lambda: FakeModel(fail=True))
    with pytest.raises(UpstreamUnavailable):
        await broken.embed(["x"], dim=8)
    wrong = LocalEmbeddingProvider("m", 8, lambda: FakeModel(dim=4))
    with pytest.raises(UpstreamUnavailable, match="dimension"):
        await wrong.embed(["x"], dim=8)


async def test_warmup_loads_the_model_off_the_event_loop() -> None:
    built: list[int] = []
    provider = LocalEmbeddingProvider("m", 8, lambda: built.append(1) or FakeModel())
    await provider.warmup()
    assert built == [1]


def test_factory_selects_backend(tmp_path: Any) -> None:
    local = build_embedding_provider(
        Settings(AUSCULTA_EMBED_BACKEND="local", AUSCULTA_DATA_ROOT=str(tmp_path))
    )
    assert isinstance(local, LocalEmbeddingProvider)
    assert local.model_id == "google/embeddinggemma-300m"
    fake = build_embedding_provider(Settings(AUSCULTA_EMBED_BACKEND="fake"))
    assert type(fake).__name__ == "FakeLLMProvider"


def test_prod_settings_refuse_unsafe_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    # hermetic: CI sets these for the whole job (fake backends, a Redis service)
    for name in ("REDIS_URL", "AUSCULTA_LLM_BACKEND", "AUSCULTA_EMBED_BACKEND", "AUSCULTA_ALLOW_FAKE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="REDIS_URL"):
        Settings(
            AUSCULTA_ENV="prod", AUSCULTA_SESSION_SECRET="x" * 40, DATABASE_URL="postgresql+asyncpg://h/db"
        )
    with pytest.raises(ValueError, match="fake"):
        Settings(
            AUSCULTA_ENV="prod",
            AUSCULTA_LLM_BACKEND="fake",
            REDIS_URL="redis://r:6379/0",
            AUSCULTA_SESSION_SECRET="x" * 40,
            DATABASE_URL="postgresql+asyncpg://h/db",
        )
    ok = Settings(
        AUSCULTA_ENV="prod",
        AUSCULTA_LLM_BACKEND="fake",
        AUSCULTA_ALLOW_FAKE=True,
        REDIS_URL="redis://r:6379/0",
        AUSCULTA_SESSION_SECRET="x" * 40,  # secret-scan: allow (test value)
        DATABASE_URL="postgresql+asyncpg://h/db",
    )
    assert ok.env == "prod"


# ---- stream spend leak (review P1/S2) --------------------------------------------------------------
class _FailingModels:
    def __init__(self, exc: BaseException, delay: float = 0.0) -> None:
        self.exc, self.delay = exc, delay

    async def generate_content_stream(self, **_: Any) -> Any:
        if self.delay:
            await asyncio.sleep(self.delay)
        raise self.exc


def _provider(models: Any, meter: MemorySpendMeter) -> GeminiProvider:
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    settings = Settings(GEMINI_API_KEY="unused-test-key")  # secret-scan: allow (test value)
    from app.llm.retry import RetryPolicy

    return GeminiProvider(settings, spend=meter, client=client, policy=RetryPolicy(attempts=1))  # type: ignore[arg-type]


async def _consume(provider: GeminiProvider) -> None:
    async for _ in provider.stream(GenerationRequest(role=ModelRole.ANSWER, system="s", prompt="p")):
        pass


async def test_failed_stream_open_settles_the_reservation() -> None:
    meter = MemorySpendMeter(cap_usd=5.0)
    provider = _provider(_FailingModels(RuntimeError("503 unavailable")), meter)
    for _ in range(5):
        with pytest.raises(Exception):  # noqa: B017 - any mapped upstream error
            await _consume(provider)
    assert await meter.spent_today() == pytest.approx(0.0, abs=1e-6)


async def test_cancel_during_stream_open_settles_the_reservation() -> None:
    meter = MemorySpendMeter(cap_usd=5.0)
    provider = _provider(_FailingModels(RuntimeError("never reached"), delay=5.0), meter)
    task = asyncio.create_task(_consume(provider))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)  # let the shielded cleanup finish
    assert await meter.spent_today() == pytest.approx(0.0, abs=1e-6)


# ---- decide() metering (review S12) ----------------------------------------------------------------
class _Decisions:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def create(self, **kwargs: Any) -> Any:
        if self.fail:
            raise RuntimeError("503 unavailable")
        answers = {k: SimpleNamespace(type="noul", noul=0.2, confidence=0.8) for k in kwargs["questions"]}
        return SimpleNamespace(
            answers=answers, usage=SimpleNamespace(total_input_tokens=10_000), prompt_feedback=None
        )


def _decide_provider(decisions: _Decisions, meter: MemorySpendMeter) -> GeminiProvider:
    from app.llm.retry import RetryPolicy

    client = SimpleNamespace(aio=SimpleNamespace(decisions=decisions))
    settings = Settings(GEMINI_API_KEY="unused-test-key")  # secret-scan: allow (test value)
    return GeminiProvider(settings, spend=meter, client=client, policy=RetryPolicy(attempts=1))  # type: ignore[arg-type]


async def test_decide_is_metered_on_success_and_free_on_failure() -> None:
    from core.ports import DecisionQuestion

    questions = {"emergency": DecisionQuestion("noul", "Is this an emergency?")}
    meter = MemorySpendMeter(cap_usd=5.0)
    res = await _decide_provider(_Decisions(), meter).decide(ModelRole.GUARD, "hello", questions)
    assert res.input_tokens == 10_000
    assert await meter.spent_today() == pytest.approx(10_000 * 0.10 / 1_000_000)
    failing = MemorySpendMeter(cap_usd=5.0)
    with pytest.raises(Exception):  # noqa: B017 - mapped upstream error
        await _decide_provider(_Decisions(fail=True), failing).decide(ModelRole.GUARD, "hello", questions)
    assert await failing.spent_today() == pytest.approx(0.0, abs=1e-9)
