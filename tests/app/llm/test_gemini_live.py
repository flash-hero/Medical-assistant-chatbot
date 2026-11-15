"""Live checks against the real Gemini API (synthetic prompts only). Run: pytest -m live tests/app/llm"""

import asyncio
import math

import pytest

from app.llm.gemini_provider import GeminiProvider
from core.config import get_settings
from core.models import EMBED_DIM, EMBED_QUERY_PREFIX, ModelRole
from core.ports import DecisionQuestion, GenerationRequest

pytestmark = pytest.mark.live


@pytest.fixture
async def provider():
    settings = get_settings()
    if settings.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY not configured")
    p = GeminiProvider(settings)
    yield p
    await p.aclose()


async def test_generate_and_stream(provider):
    req = GenerationRequest(
        role=ModelRole.ANSWER, system="Answer in one sentence.", prompt="What is a fever?"
    )
    res = await provider.generate(req)
    assert res.text.strip()
    assert res.model_id == "gemini-3.5-flash-lite"
    chunks = [c async for c in provider.stream(req)]
    assert "".join(c.text for c in chunks).strip()
    assert chunks[-1].finish_reason == "STOP"


async def test_json_schema_output(provider):
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "lang": {"type": "string", "enum": ["en", "fr", "ar"]}},
        "required": ["query", "lang"],
    }
    req = GenerationRequest(
        role=ModelRole.REWRITE,
        system="Rewrite the user's question as a standalone search query. Return JSON.",
        prompt="c'est quoi l'asthme ?",
        json_schema=schema,
    )
    res = await provider.generate(req)
    import json

    data = json.loads(res.text)
    assert data["lang"] == "fr"
    assert data["query"]


async def test_stream_cancellation_closes_cleanly(provider):
    req = GenerationRequest(
        role=ModelRole.ANSWER, system="Be thorough.", prompt="Explain how vaccines work in 300 words."
    )

    async def consume():
        async for _ in provider.stream(req):
            await asyncio.sleep(0.05)

    task = asyncio.create_task(consume())
    await asyncio.sleep(1.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_decide(provider):
    res = await provider.decide(
        ModelRole.GUARD,
        "USER: I have crushing chest pain spreading to my left arm and I am sweating",
        {
            "emergency": DecisionQuestion("noul", "Does the user describe a possible medical emergency now?"),
            "lang": DecisionQuestion("choice", "Language of the message", {"en": "English", "fr": "French"}),
            "rel": DecisionQuestion("score", "Relevance to cardiology", ["none", "some", "high"]),
        },
    )
    assert res.answers["emergency"].noul > 0.5
    assert res.answers["lang"].choice == "en"
    assert res.answers["rel"].score is not None


async def test_embed_batches_and_unit_norm(provider):
    # Free tier counts every text against 100/min, so keep live probes small.
    texts = [f"{EMBED_QUERY_PREFIX}synthetic query {i}" for i in range(12)]
    vecs = await provider.embed(texts, dim=EMBED_DIM)
    assert len(vecs) == 12
    assert all(len(v) == EMBED_DIM for v in vecs)
    assert abs(math.sqrt(sum(x * x for x in vecs[0])) - 1.0) < 1e-3
