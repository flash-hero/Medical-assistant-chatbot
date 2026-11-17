"""Review S8/P6 (API side): the live corpus is verified against its signed manifest at startup
(rag.verify.verify_live_corpus) and nothing is retrieved from it unless that succeeds. Fakes only: no Qdrant,
no embedding model."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.api import container as container_mod
from app.api.container import Overrides
from app.api.corpus import VerifiedRetriever
from core.errors import DependencyUnavailable
from core.schemas.chat import RetrievalQuery
from evals.fakes.fake_retriever import FakeRetriever
from rag.errors import CorpusUnverified

API = "/api/v1"
FEVER = "What is a fever?"


@dataclass(frozen=True)
class Verified:
    collection: str = "ausculta_corpus_v9"
    corpus_version: str = "2026-11-17.full"
    embed_model: str = "google/embeddinggemma-300m@fmt1"
    chunks: int = 3


def _verifier(result: object = None, *, error: Exception | None = None, delay_s: float = 0.0):
    calls: list[object] = []

    async def verify(settings):
        calls.append(settings)
        if delay_s:
            await asyncio.sleep(delay_s)
        if error is not None:
            raise error
        return result or Verified()

    verify.calls = calls  # type: ignore[attr-defined]
    return verify


async def test_verified_corpus_is_served(api_factory) -> None:
    verify = _verifier()
    async with api_factory(corpus_verifier=verify) as api:
        await api.container.corpus_ready()
        assert len(verify.calls) == 1
        assert (await api.container.ready_checks())["retriever"] is True
        res = await api.chat(await api.token(), FEVER)
        res.assert_contract()
        assert res.first("answer").mode == "streamed"


@pytest.mark.parametrize(
    "error",
    [CorpusUnverified("stored chunks do not match the signed manifest"), RuntimeError("bug in the check")],
    ids=["unverified", "checker-crash"],
)
async def test_unverified_corpus_is_never_served(api_factory, error) -> None:
    async with api_factory(corpus_verifier=_verifier(error=error)) as api:
        await api.container.corpus_ready()
        assert (await api.container.ready_checks())["retriever"] is False
        assert (await api.client.get(f"{API}/ready")).status_code == 503
        res = await api.chat(await api.token(), FEVER)
        res.assert_contract()
        assert res.first("answer").mode == "template"
        assert "degraded" in [e.code for e in res.events if e.type == "notice"]
        assert api.retriever.calls == [], "no query may reach an unverified collection"
        emergency = await api.chat(await api.token(), "I want to kill myself")
        assert emergency.first("safety").kind == "self_harm"


async def test_turns_while_verification_runs_degrade_instead_of_waiting(api_factory) -> None:
    async with api_factory(corpus_verifier=_verifier(delay_s=0.5)) as api:
        assert (await api.container.ready_checks())["retriever"] is False
        res = await api.chat(await api.token(), FEVER)
        assert res.first("answer").mode == "template"
        await api.container.corpus_ready()
        assert (await api.container.ready_checks())["retriever"] is True


async def test_shutdown_during_verification_is_clean(api_factory) -> None:
    async with api_factory(corpus_verifier=_verifier(delay_s=30)) as api:
        task = api.container._corpus_task
        assert task is not None
    assert task.done()


async def test_wrapper_delegates_once_verified() -> None:
    closed: list[str] = []

    class Inner(FakeRetriever):
        warmed: int = 0

        async def warmup(self) -> None:
            self.warmed += 1

        async def aclose(self) -> None:
            closed.append("inner")

    inner = Inner()
    wrapped = VerifiedRetriever(inner)
    assert wrapped.corpus_version == inner.corpus_version
    with pytest.raises(DependencyUnavailable):
        await wrapped.retrieve(RetrievalQuery(standalone_query="fever", language="en"))
    assert await wrapped.health() is False
    await wrapped.verify(_verifier(), settings=None)
    assert wrapped.state == "verified"
    assert await wrapped.health() is True
    assert (await wrapped.retrieve(RetrievalQuery(standalone_query="fever", language="en"))).passages
    await wrapped.warmup()
    await wrapped.aclose()
    assert (inner.warmed, closed) == (1, ["inner"])
    await VerifiedRetriever(object()).warmup()  # type: ignore[arg-type]  # inner without warmup
    await VerifiedRetriever(object()).aclose()  # type: ignore[arg-type]  # inner without close


def test_real_retriever_is_wrapped_and_verified_by_rag(settings_factory, monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    real = FakeRetriever(version="real")
    monkeypatch.setitem(sys.modules, "rag.retrieval", SimpleNamespace(build_retriever=lambda s, llm: real))
    c = container_mod.build_container(
        settings_factory(AUSCULTA_LLM_BACKEND="gemini"), Overrides(llm=object())
    )
    assert isinstance(c.retriever, VerifiedRetriever)
    from rag.verify import verify_live_corpus

    assert c.corpus_verifier is verify_live_corpus
    fake = container_mod.build_container(settings_factory(), Overrides())
    assert not isinstance(fake.retriever, VerifiedRetriever)  # fake backend: synthetic passages, no check
    assert fake.corpus_verifier is None
