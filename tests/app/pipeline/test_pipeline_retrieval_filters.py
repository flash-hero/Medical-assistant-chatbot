"""Regression (P4 evaluation, 2026-11-20): the rewriter's content-type hint must not hide the answer.

The rewrite model names content types for the search, and the medical path applied them as a hard filter.
The model may name types the live index does not hold (v1 corpus: no guideline, faq, first_aid or drug_label
point) or a wrong existing type, and the filter then removed the passages that answer the question:
  "Quels sont les risques potentiels associés à l'anesthésie générale ?" -> ["faq", "guideline"] -> 0 passages
  "كيف يجب أن أنظف أطقم الأسنان ..." (dentures) -> ["wellness", "faq"] -> contact-lens passages, not confident
and the answerable question abstained. The confidence gate was calibrated on unfiltered retrieval (the path
every standalone English question takes), so when the hinted search cannot support an answer (no passage or
not confident) the medical path searches once more without the hint and the gate decides on that result.
The filter forced by the intent (medication -> drug labels only, review C7) is never relaxed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from core.schemas.chat import Intent, RetrievalQuery, RetrievalResult, RetrievedPassage
from core.schemas.source import ContentType
from evals.fakes.fake_llm import FakeLLMProvider
from evals.fakes.fake_retriever import FakeRetriever, default_passages
from evals.fakes.scripted import GuardScript, guard_decider, role_responder
from evals.fakes.sse_contract import order_violations

QUESTION_FR = "Quels sont les risques potentiels associés à l'anesthésie générale ?"
ANSWER = "A fever is a body temperature that is higher than normal [1]."
MISSING_TYPES = ["faq", "guideline"]  # no passage of these types in the index
WEAK_TYPES = ["wellness"]  # passages exist, but none answers the question (gate not confident)


def _llm(intent: Intent, content_types: list[str]) -> FakeLLMProvider:
    rewrite = {
        "standalone_query": QUESTION_FR,
        "search_queries_en": ["general anesthesia risks"],
        "content_types": content_types,
    }
    rules = (("anesth", GuardScript(intent=intent, language="fr")),)
    return FakeLLMProvider(responder=role_responder(ANSWER, rewrite=rewrite), decider=guard_decider(rules))


@dataclass
class _Index(FakeRetriever):
    """Honours the content-type filter: missing types give nothing, weak types give unconfident passages,
    `unconfident=True` makes every search unconfident (an out-of-corpus question)."""

    unconfident: bool = False

    def _found(self, wanted: set[str]) -> Sequence[RetrievedPassage]:
        held = default_passages()
        if not wanted:
            return held
        if wanted <= set(MISSING_TYPES) | {ContentType.DRUG_LABEL.value}:
            return ()
        if wanted <= set(MISSING_TYPES) | set(WEAK_TYPES):
            return held[:1]
        return tuple(p for p in held if p.content_type.value in wanted)

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.calls.append(query)
        wanted = set(query.filters.get("content_type", []))
        found = tuple(self._found(wanted))[: query.top_k]
        confident = bool(found) and not self.unconfident and not wanted & set(WEAK_TYPES)
        return RetrievalResult(passages=found, confident=confident, confidence=0.9 if confident else 0.1)


def _relaxed(out: Any) -> list[Any]:
    return [
        a.detail.get("content_types") for a in out.record.audit if a.event_type == "retrieval_filter_relaxed"
    ]


async def test_a_content_type_hint_that_matches_nothing_is_dropped(
    harness_factory: Callable[..., Any],
) -> None:
    index = _Index()
    h = harness_factory(llm=_llm(Intent.MEDICAL_INFO, MISSING_TYPES), retriever=index)
    out = await h.turn(QUESTION_FR, locale="fr")
    assert order_violations(out.events) == [], out.types
    answer = out.first("answer")
    assert answer.mode in ("streamed", "verified"), answer.mode
    assert answer.citations
    assert [q.filters for q in index.calls] == [{"content_type": MISSING_TYPES}, {}]
    assert _relaxed(out) == ["faq,guideline"]


async def test_a_hint_that_narrows_to_the_wrong_type_is_dropped(harness_factory: Callable[..., Any]) -> None:
    index = _Index()
    h = harness_factory(llm=_llm(Intent.MEDICAL_INFO, [*WEAK_TYPES, "faq"]), retriever=index)
    out = await h.turn(QUESTION_FR, locale="fr")
    assert out.first("answer").mode in ("streamed", "verified")
    assert [q.filters for q in index.calls] == [{"content_type": ["wellness", "faq"]}, {}]
    assert _relaxed(out) == ["wellness,faq"]


async def test_a_content_type_hint_that_supports_an_answer_is_kept(
    harness_factory: Callable[..., Any],
) -> None:
    index = _Index()
    h = harness_factory(llm=_llm(Intent.MEDICAL_INFO, ["condition"]), retriever=index)
    out = await h.turn(QUESTION_FR, locale="fr")
    assert out.first("answer").mode in ("streamed", "verified")
    assert [q.filters for q in index.calls] == [{"content_type": ["condition"]}]
    assert _relaxed(out) == []


async def test_the_gate_still_abstains_on_the_unfiltered_search(harness_factory: Callable[..., Any]) -> None:
    index = _Index(unconfident=True)
    h = harness_factory(llm=_llm(Intent.MEDICAL_INFO, ["condition"]), retriever=index)
    out = await h.turn(QUESTION_FR, locale="fr")
    assert order_violations(out.events) == [], out.types
    assert out.first("answer").mode == "abstain"
    assert [q.filters for q in index.calls] == [{"content_type": ["condition"]}, {}]
    assert _relaxed(out) == ["condition"]


async def test_no_hint_means_a_single_search(harness_factory: Callable[..., Any]) -> None:
    index = _Index(unconfident=True)
    h = harness_factory(llm=_llm(Intent.MEDICAL_INFO, []), retriever=index)
    out = await h.turn(QUESTION_FR, locale="fr")
    assert out.first("answer").mode == "abstain"
    assert [q.filters for q in index.calls] == [{}]


async def test_the_medication_drug_label_filter_is_never_relaxed(harness_factory: Callable[..., Any]) -> None:
    index = _Index()
    h = harness_factory(llm=_llm(Intent.MEDICATION, ["condition"]), retriever=index)
    out = await h.turn(QUESTION_FR, locale="fr")
    assert order_violations(out.events) == [], out.types
    assert out.first("answer").mode == "abstain"
    assert [q.filters for q in index.calls] == [{"content_type": ["drug_label"]}]
    assert _relaxed(out) == []
