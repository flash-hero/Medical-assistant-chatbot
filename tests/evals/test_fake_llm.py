import asyncio

import pytest

from core.models import ModelRole
from core.ports import GenerationRequest, LLMProvider
from evals.fakes.fake_llm import FakeLLMProvider, hash_embed


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_fake_satisfies_port_and_embeddings_are_lexical_and_unit_norm():
    fake = FakeLLMProvider()
    assert isinstance(fake, LLMProvider)
    a, b, c = (hash_embed(t, 768) for t in ("asthma inhaler attack", "asthma attack inhaler use", "hospital parking"))
    assert abs(_cos(a, a) - 1.0) < 1e-9
    assert _cos(a, b) > _cos(a, c)


async def test_stream_counts_open_and_closed_on_cancel():
    fake = FakeLLMProvider(responder=lambda r: "x" * 500, chunk_chars=5, chunk_delay_s=0.01)
    req = GenerationRequest(role=ModelRole.ANSWER, system="s", prompt="p")

    async def consume():
        async for _ in fake.stream(req):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    assert fake.open_streams == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.open_streams == 0 and fake.closed_streams == 1


async def test_failure_injection_per_role():
    fake = FakeLLMProvider(failures={ModelRole.ANSWER: TimeoutError("boom")})
    with pytest.raises(TimeoutError):
        await fake.generate(GenerationRequest(role=ModelRole.ANSWER, system="", prompt=""))
    ok = await fake.generate(GenerationRequest(role=ModelRole.ANSWER_FALLBACK, system="", prompt=""))
    assert ok.finish_reason == "STOP"
