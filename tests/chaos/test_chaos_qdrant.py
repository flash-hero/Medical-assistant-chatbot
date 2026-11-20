"""Chaos: the vector store (Qdrant) is down.

Expected: medical questions get the fixed "medical information temporarily unavailable" template (with the
emergency number) plus a "degraded" notice; emergency and front-desk turns are unaffected; /ready is 503 with
Retry-After; nothing hangs; answers recover when the store comes back.
"""

from __future__ import annotations

import socket
import time
from typing import Any

import pytest
from chaos_support import EMERGENCY, FEVER, VISITING
from qdrant_client import AsyncQdrantClient

from core.config import Settings
from evals.fakes.fake_llm import FakeLLMProvider
from evals.fakes.fake_retriever import FakeRetriever

MEDICAL_TURN_BUDGET_S = 10.0  # retrieval timeout is 8 s; a dead store must fail well inside the turn


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _assert_qdrant_down_behaviour(api: Any, texts: Any) -> None:
    token = await api.token()
    t0 = time.perf_counter()
    medical = await api.chat(token, FEVER)
    elapsed = time.perf_counter() - t0
    medical.assert_contract()
    answer = medical.answer()
    profile = api.container.profile()
    assert answer.mode == "template"
    assert answer.text == texts.response("retrieval_unavailable", "en", profile)
    assert profile.emergency.number in answer.text
    assert any(e.type == "notice" and e.code == "degraded" for e in medical.events)
    assert "delta" not in medical.types
    assert elapsed < MEDICAL_TURN_BUDGET_S

    emergency = await api.chat(await api.token(), EMERGENCY)
    emergency.assert_contract()
    assert [e.kind for e in emergency.events if e.type == "safety"] == ["emergency"]

    desk = await api.chat(await api.token(), VISITING)
    desk.assert_contract()
    assert desk.answer().intent == "hospital_admin"
    assert desk.answer().text != texts.response("retrieval_unavailable", "en", profile)

    ready = await api.client.get("/api/v1/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"]["retriever"] is False
    assert int(ready.headers["retry-after"]) >= 1


async def test_fake_store_down_degrades_medical_answers_only(chaos_app: Any) -> None:
    retriever = FakeRetriever(error=ConnectionError("qdrant: connection refused"), healthy=False)
    async with chaos_app(retriever=retriever) as api:
        await _assert_qdrant_down_behaviour(api, api.container.texts)
        assert api.container.admission.held == 0


async def test_store_recovery_restores_answers_and_readiness(chaos_app: Any) -> None:
    retriever = FakeRetriever(error=ConnectionError("down"), healthy=False)
    async with chaos_app(retriever=retriever) as api:
        token = await api.token()
        assert (await api.chat(token, FEVER)).answer().mode == "template"
        retriever.error, retriever.healthy = None, True
        back = await api.chat(token, FEVER)
        back.assert_contract()
        assert back.answer().mode in ("streamed", "verified")
        assert back.answer().citations
        assert (await api.client.get("/api/v1/ready")).status_code == 200


async def test_slow_store_hits_the_retrieval_timeout_not_the_turn_deadline(chaos_app: Any) -> None:
    """A store that hangs is cut by the retrieval timeout (8 s) and degrades; the turn still completes."""
    retriever = FakeRetriever(latency_s=60.0)
    async with chaos_app(retriever=retriever) as api:
        token = await api.token()
        t0 = time.perf_counter()
        turn = await api.chat(token, FEVER)
        turn.assert_contract()
        assert turn.answer().mode == "template"
        assert time.perf_counter() - t0 < MEDICAL_TURN_BUDGET_S + 2


def _real_retriever_or_skip(port: int) -> Any:
    from rag.embedding import QueryEmbedder
    from rag.paths import DataPaths
    from rag.rerank import NoopReranker
    from rag.retrieval import HybridRetriever
    from rag.sparse import SparseEncoder

    fastembed_dir = DataPaths.from_settings(Settings()).fastembed_dir
    if not fastembed_dir.exists():
        pytest.skip("BM25 analyser assets are not present on this machine")
    return HybridRetriever(
        client=AsyncQdrantClient(url=f"http://127.0.0.1:{port}", timeout=2),
        collection="ausculta_corpus",
        query_embedder=QueryEmbedder(FakeLLMProvider(), model_id="fake"),
        sparse=SparseEncoder(fastembed_dir),
        reranker=NoopReranker(),
        version="chaos",
    )


@pytest.mark.filterwarnings("ignore::UserWarning")
async def test_real_hybrid_retriever_against_a_dead_qdrant_port(chaos_app: Any) -> None:
    """The production retriever (real Qdrant client, real BM25 encoder) pointed at a closed port."""
    retriever = _real_retriever_or_skip(_closed_port())
    async with chaos_app(retriever=retriever) as api:
        assert await retriever.health() is False
        await _assert_qdrant_down_behaviour(api, api.container.texts)
