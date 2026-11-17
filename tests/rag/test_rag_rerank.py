import pytest

from core.errors import UpstreamTimeout
from core.models import ModelRole
from core.ports import DecisionAnswer
from evals.fakes.fake_llm import FakeLLMProvider
from rag.rerank import DecisionReranker, NoopReranker, RerankItem, build_rerank_input


def items(n: int) -> list[RerankItem]:
    return [
        RerankItem(title=f"T{i}", heading=f"H{i}", text=f"passage {i} " + "word " * 600) for i in range(n)
    ]


def test_input_labels_passages_untrusted_and_truncates_them():
    text = build_rerank_input("  What is asthma? ", items(2), 50)
    assert text.startswith("QUESTION:\nWhat is asthma?")
    assert "untrusted" in text
    assert "[1] T0 > H0" in text
    assert "[2] T1 > H1" in text
    assert text.count("word") < 2 * 60
    assert "[1] Title only\n" in build_rerank_input("q", [RerankItem("Title only", "", "x")], 50)


async def test_noop_reranker_is_disabled():
    noop = NoopReranker()
    assert not noop.enabled
    assert not (await noop.rerank("q", items(3))).applied


async def test_scores_are_normalised_and_split_into_groups():
    seen: list[int] = []

    def decider(input_text, key, question):
        assert question.kind == "score"
        assert len(question.criteria) == 4
        return DecisionAnswer(kind="score", confidence=0.9, score=float(int(key[1:]) % 4))

    llm = FakeLLMProvider(decider=decider)
    rr = DecisionReranker(llm, max_candidates=5, group_size=2)
    res = await rr.rerank("q", items(7))
    seen = [n for kind, _, n in llm.calls if kind == "decide"]
    assert res.applied
    assert seen == [2, 2, 1]  # 5 candidates in groups of 2
    assert res.scores == pytest.approx((1 / 3, 2 / 3, 1 / 3, 2 / 3, 1 / 3))
    assert all(r == ModelRole.RERANK for kind, r, _ in llm.calls if kind == "decide")


async def test_failure_or_empty_input_is_not_applied():
    failing = DecisionReranker(FakeLLMProvider(failures={ModelRole.RERANK: UpstreamTimeout("slow")}))
    res = await failing.rerank("q", items(3))
    assert not res.applied
    assert res.scores == ()
    assert not (await DecisionReranker(FakeLLMProvider()).rerank("q", [])).applied
    with pytest.raises(ValueError):
        DecisionReranker(FakeLLMProvider(), group_size=0)
