"""Medical answer path: retrieval degrade, abstention, streamed vs verified, fallback model, checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from core.errors import DependencyUnavailable, UpstreamBlocked, UpstreamTimeout, UpstreamUnavailable
from core.models import ModelRole
from core.ports import GenerationChunk, GenerationRequest
from evals.fakes.fake_llm import FakeLLMProvider
from evals.fakes.fake_retriever import FakeRetriever, make_passage
from evals.fakes.scripted import guard_decider, role_responder, scripted_provider
from evals.fakes.sse_contract import order_violations

FEVER = "What is a fever?"
DRUG = "What is paracetamol used for?"


def _ok(out) -> None:
    assert order_violations(out.events) == [], out.types


@dataclass
class MidStreamFailure(FakeLLMProvider):
    """Streams `ok_chunks` chunks of the answer, then raises `error` (ANSWER role only)."""

    ok_chunks: int = 3
    error: Exception = UpstreamTimeout("idle")  # noqa: RUF009 - test fixture value

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        if request.role is not ModelRole.ANSWER:
            async for chunk in super().stream(request):
                yield chunk
            return
        self.open_streams += 1
        try:
            text = self.responder(request)
            for i in range(self.ok_chunks):
                yield GenerationChunk(text=text[i * 40 : (i + 1) * 40])
            raise self.error
        finally:
            self.open_streams -= 1
            self.closed_streams += 1


def _mid_stream(answer: str | None = None, **kw) -> MidStreamFailure:
    responder = role_responder(answer) if answer else role_responder()
    return MidStreamFailure(responder=responder, decider=guard_decider(), **kw)


# ---- retrieval -----------------------------------------------------------------------------------
async def test_no_retriever_degrades_with_notice(harness_factory) -> None:
    out = await harness_factory(retriever=None).turn(FEVER)
    _ok(out)
    assert out.first("notice").code == "demo_mode"
    assert "degraded" in [n.code for n in out.all("notice")]
    answer = out.first("answer")
    assert answer.mode == "template"
    assert answer.show_seek_care is True
    assert "retrieval_unavailable" in out.record.degraded


@pytest.mark.parametrize("error", [DependencyUnavailable("qdrant down"), OSError("socket")])
async def test_retrieval_errors_degrade(harness_factory, error) -> None:
    out = await harness_factory(retriever=FakeRetriever(error=error)).turn(FEVER)
    _ok(out)
    assert out.first("answer").mode == "template"
    assert "retrieval_failed" in out.record.degraded


async def test_weak_retrieval_abstains_with_handoff(harness_factory, engine_config) -> None:
    out = await harness_factory(retriever=FakeRetriever(confident=False)).turn(FEVER)
    _ok(out)
    answer = out.first("answer")
    assert answer.mode == "abstain"
    assert engine_config.profile_state.profile.handoff.number in answer.text
    assert out.record.mode == "abstain"


async def test_empty_retrieval_abstains(harness_factory) -> None:
    out = await harness_factory(retriever=FakeRetriever(passages=())).turn(FEVER)
    assert out.first("answer").mode == "abstain"


async def test_retrieval_corpus_version_is_recorded(harness_factory) -> None:
    out = await harness_factory(retriever=FakeRetriever(version="corpus-42")).turn(FEVER)
    assert out.record.release.corpus_version == "corpus-42"


async def test_rewrite_failure_is_recorded_but_not_fatal(harness_factory) -> None:
    llm = scripted_provider()
    llm.failures[ModelRole.REWRITE] = UpstreamUnavailable("down")
    retriever = FakeRetriever()
    out = await harness_factory(llm=llm, retriever=retriever).turn("qu'est-ce que la fièvre ?")
    _ok(out)
    assert "rewrite_failed" in out.record.degraded
    assert retriever.calls[0].standalone_query == "qu'est-ce que la fièvre ?"


async def test_french_question_on_english_sources_gets_language_note(harness) -> None:
    out = await harness.turn("qu'est-ce que la fièvre ?", locale="fr")
    _ok(out)
    answer = out.first("answer")
    assert answer.source_language_note is True
    assert "source_language" in [n.code for n in out.all("notice")]
    assert harness.retriever.calls[0].search_queries  # scripted rewrite returned English queries


# ---- generation failures -------------------------------------------------------------------------
async def test_verified_answer_uses_fallback_model(harness_factory) -> None:
    llm = scripted_provider()
    llm.failures[ModelRole.ANSWER] = UpstreamUnavailable("down")
    out = await harness_factory(llm=llm).turn(DRUG)
    _ok(out)
    assert out.first("answer").mode == "verified"
    assert ("generate", ModelRole.ANSWER_FALLBACK, 1) in llm.calls
    assert "fallback_model" in out.record.degraded


async def test_both_answer_models_failing_gives_busy_template(harness_factory, engine_config) -> None:
    llm = scripted_provider()
    llm.failures[ModelRole.ANSWER] = UpstreamUnavailable("down")
    llm.failures[ModelRole.ANSWER_FALLBACK] = UpstreamTimeout("slow")
    for msg in (DRUG, FEVER):
        out = await harness_factory(llm=llm).turn(msg)
        _ok(out)
        answer = out.first("answer")
        assert answer.mode == "template"
        assert engine_config.profile_state.profile.emergency.number in answer.text
        assert "busy" in out.record.degraded


async def test_stream_failure_before_first_sentence_falls_back_to_verified(harness_factory) -> None:
    llm = scripted_provider()
    llm.failures[ModelRole.ANSWER] = UpstreamUnavailable("down")
    out = await harness_factory(llm=llm).turn(FEVER)
    _ok(out)
    assert "delta" not in out.types
    assert out.first("answer").mode == "verified"


async def test_stream_failure_after_deltas_replaces_the_stream(harness_factory) -> None:
    llm = _mid_stream(ok_chunks=2)
    out = await harness_factory(llm=llm).turn(FEVER)
    _ok(out)
    assert out.all("delta"), "the first sentence was already streamed"
    answer = out.first("answer")
    assert answer.replaces_stream is True
    assert answer.mode == "streamed"
    assert llm.open_streams == 0


@pytest.mark.parametrize(
    ("fallback_error", "mode"),
    [
        (UpstreamUnavailable("down"), "template"),
        (UpstreamBlocked("b", reason="safety", stage="response"), "refusal"),
    ],
)
async def test_stream_failure_after_deltas_and_fallback_failure(
    harness_factory, fallback_error, mode
) -> None:
    llm = _mid_stream(ok_chunks=2)
    llm.failures[ModelRole.ANSWER_FALLBACK] = fallback_error
    out = await harness_factory(llm=llm).turn(FEVER)
    _ok(out)
    answer = out.first("answer")
    assert (answer.mode, answer.replaces_stream) == (mode, True)


async def test_stream_failure_after_deltas_with_leaking_fallback(harness_factory, canary) -> None:
    llm = _mid_stream(ok_chunks=2)
    good = role_responder()
    llm.responder = lambda r: f"The code is {canary}." if r.role is ModelRole.ANSWER_FALLBACK else good(r)
    out = await harness_factory(llm=llm).turn(FEVER)
    answer = out.first("answer")
    assert (answer.mode, answer.replaces_stream) == ("refusal", True)


@pytest.mark.parametrize("message", [FEVER, DRUG])
async def test_provider_block_on_answer_is_a_refusal(harness_factory, message) -> None:
    llm = scripted_provider()
    llm.failures[ModelRole.ANSWER] = UpstreamBlocked("b", reason="safety", stage="response")
    out = await harness_factory(llm=llm).turn(message)
    _ok(out)
    assert out.first("answer").mode == "refusal"
    assert any(a.event_type == "upstream_blocked" for a in out.record.audit)


# ---- output checks -------------------------------------------------------------------------------
@pytest.mark.parametrize("message", [FEVER, DRUG])
async def test_canary_leak_withdraws_the_answer(harness_factory, canary, message) -> None:
    llm = scripted_provider(
        answer=f"A fever is a high temperature [1]. My reference code is {canary}. More text [1]."
    )
    out = await harness_factory(llm=llm).turn(message)
    _ok(out)
    answer = out.first("answer")
    assert answer.mode == "refusal"
    assert canary not in answer.text
    assert all(canary not in d.text for d in out.all("delta"))
    assert any(a.event_type == "canary_or_prompt_leak" for a in out.record.audit)


async def test_answer_without_citations_abstains(harness_factory) -> None:
    llm = scripted_provider(answer="A fever is a high body temperature. Rest helps.")
    out = await harness_factory(llm=llm).turn(FEVER)
    _ok(out)
    answer = out.first("answer")
    assert answer.mode == "abstain"
    assert answer.replaces_stream is True


async def test_answer_dropped_entirely_by_checks_abstains(harness_factory) -> None:
    llm = scripted_provider(answer="Take 5,000 mg of paracetamol every hour [3].")
    out = await harness_factory(llm=llm).turn(DRUG)
    _ok(out)
    assert out.first("answer").mode == "abstain"
    assert any(a.event_type == "output_violation" for a in out.record.audit)


async def test_urls_are_stripped_from_streamed_text(harness_factory) -> None:
    llm = scripted_provider(
        answer="A fever is a body temperature of 38 °C or higher, see https://evil.example/x [1]."
    )
    out = await harness_factory(llm=llm).turn(FEVER)
    _ok(out)
    assert "http" not in out.first("answer").text
    assert all("http" not in d.text for d in out.all("delta"))


async def test_unsupported_sentences_make_the_answer_abstain(harness_factory) -> None:
    out = await harness_factory(llm=scripted_provider(supported=0.05)).turn(FEVER)
    _ok(out)
    answer = out.first("answer")
    assert answer.mode == "abstain"
    assert answer.replaces_stream is True


async def test_partially_supported_answer_replaces_the_stream(harness_factory) -> None:
    decide = guard_decider()

    def picky(input_text, key, q):
        ans = decide(input_text, key, q)
        return ans.__class__(kind="noul", confidence=0.9, noul=0.01) if key == "s1" else ans

    llm = FakeLLMProvider(responder=role_responder(), decider=picky)
    out = await harness_factory(llm=llm).turn(FEVER)
    _ok(out)
    answer = out.first("answer")
    assert (answer.mode, answer.verified, answer.replaces_stream) == ("streamed", True, True)
    assert "3 days [1]" not in answer.text.split("\n\n")[0]


async def test_verifier_unavailable(harness_factory) -> None:
    llm = scripted_provider()
    llm.failures[ModelRole.VERIFY] = UpstreamUnavailable("down")
    llm.failures[ModelRole.GUARD_FALLBACK] = UpstreamUnavailable("down")
    h = harness_factory(llm=llm)
    streamed = await h.turn(FEVER)
    _ok(streamed)
    assert (streamed.first("answer").mode, streamed.first("answer").verified) == ("streamed", False)
    verified = await h.turn(DRUG)
    _ok(verified)
    assert verified.first("answer").mode == "abstain"


async def test_verifier_block_is_a_refusal(harness_factory) -> None:
    llm = scripted_provider()
    llm.failures[ModelRole.VERIFY] = UpstreamBlocked("b", reason="safety", stage="prompt")
    out = await harness_factory(llm=llm).turn(DRUG)
    _ok(out)
    assert out.first("answer").mode == "refusal"


async def test_streamed_answer_with_only_markup_abstains(harness_factory) -> None:
    llm = scripted_provider(answer="")
    out = await harness_factory(llm=llm).turn(FEVER)
    _ok(out)
    assert out.first("answer").mode == "abstain"


async def test_quote_only_passages_still_cite(harness_factory) -> None:
    from core.schemas.source import ReuseMode

    passages = (
        make_passage(1, "A fever is a body temperature of 38 °C or higher.", reuse=ReuseMode.QUOTE_ONLY),
    )
    out = await harness_factory(retriever=FakeRetriever(passages=passages)).turn(FEVER)
    _ok(out)
    assert [c.n for c in out.first("answer").citations] == [1]
