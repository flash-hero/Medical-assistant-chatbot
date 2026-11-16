import json
from datetime import UTC, datetime

from rag_fixtures import make_doc

from core.errors import UpstreamRateLimited
from core.models import ModelRole
from evals.fakes.fake_llm import FakeLLMProvider
from evals.retrieval.generate import (
    QUESTION_SCHEMA,
    GoldGenerator,
    clean_question,
    generate_gold,
    parse_items,
)
from rag.chunking import ChunkerConfig, chunk_document

NOW = datetime(2026, 11, 16, tzinfo=UTC)


class Sleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, s: float) -> None:
        self.calls.append(s)


def passages(n: int):
    cfg = ChunkerConfig(small_section_tokens=0)
    return [
        chunk_document(make_doc(f"t{i}", title=f"Topic {i}"), publisher="P", config=cfg)[0] for i in range(n)
    ]


def responder(request):
    if "<passage" in request.prompt:
        pids = [p.split("=")[1].split(">")[0] for p in request.prompt.split("<passage id")[1:]]
        items = [
            {"pid": p, "en": f"What about topic {p}?", "fr": f"Et le sujet {p} ?", "ar": f"ماذا عن {p}؟"}
            for p in pids
        ]
        items.append({"pid": "P99", "en": "unknown passage id", "fr": "x" * 20, "ar": "y" * 20})
        items.append({"pid": pids[0], "en": "see http://evil.example", "fr": "ok ok ok", "ar": "ok ok ok"})
        return json.dumps({"items": items})
    if request.prompt.startswith("Write"):
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "fictional",
                        "en": "Symptoms of Zorbic fever?",
                        "fr": "Symptômes de la fièvre Zorbic ?",
                        "ar": "أعراض حمى زوربيك؟",
                    },
                    {
                        "kind": "offdomain",
                        "en": "How to bake bread at home?",
                        "fr": "Comment faire du pain ?",
                        "ar": "كيف أخبز الخبز؟",
                    },
                ]
            }
        )
    ids = [line.split("]")[0].strip("[") for line in request.prompt.splitlines()]
    return json.dumps({"items": [{"id": i, "en": f"english rewrite of {i}"} for i in ids]})


async def test_full_generation_uses_few_calls_and_marks_rows_unreviewed():
    llm = FakeLLMProvider(responder=responder)
    sleep = Sleep()
    gen = GoldGenerator(llm, created_at=NOW, sleep=sleep, min_interval_s=1.0)
    rows, rewrites, stopped = await generate_gold(gen, passages(12), batch_size=5, ooc=2)
    assert stopped is None
    assert gen.calls == 3 + 1 + 1  # 3 question batches, 1 OOC call, 1 rewrite call (28 FR/AR rows)
    assert sleep.calls == [1.0] * 4
    answerable = [r for r in rows if r.answerable]
    assert len(answerable) == 12 * 3
    assert len([r for r in rows if not r.answerable]) == 6
    assert {r.status for r in rows} == {"llm_generated_unreviewed"}
    assert {r.kind for r in rows if not r.answerable} == {"ooc_fictional", "ooc_offdomain"}
    assert gen.skipped == 2 * 3  # unknown pid and URL-bearing item in each batch
    assert len(rewrites) == len([r for r in rows if r.language != "en"])
    assert all(call[1] is ModelRole.REWRITE for call in llm.calls)
    first = answerable[0]
    assert first.relevant_chunk_ids == (passages(12)[0].chunk_id,)


async def test_budget_and_quota_stops_keep_partial_output():
    llm = FakeLLMProvider(responder=responder)
    gen = GoldGenerator(llm, created_at=NOW, sleep=Sleep(), max_calls=2)
    rows, _, stopped = await generate_gold(gen, passages(15), batch_size=5, ooc=2)
    assert "budget" in stopped
    assert len(rows) == 10 * 3

    class DayQuota(FakeLLMProvider):
        async def generate(self, request):
            if self.count("generate") >= 1:
                self.calls.append(("generate", request.role, 1))
                raise UpstreamRateLimited("day", scope="day", retry_after_s=None)
            return await super().generate(request)

    gen2 = GoldGenerator(DayQuota(responder=responder), created_at=NOW, sleep=Sleep())
    rows2, _, stopped2 = await generate_gold(gen2, passages(10), batch_size=5)
    assert "daily" in stopped2
    assert len(rows2) == 5 * 3


async def test_minute_rate_limit_waits_and_retries():
    class OnceLimited(FakeLLMProvider):
        async def generate(self, request):
            if self.count("generate") == 0:
                self.calls.append(("generate", request.role, 1))
                raise UpstreamRateLimited("rl", scope="minute", retry_after_s=30.0)
            return await super().generate(request)

    sleep = Sleep()
    gen = GoldGenerator(OnceLimited(responder=responder), created_at=NOW, sleep=sleep, min_interval_s=2.0)
    out = await gen.question_batch("b0", passages(2))
    assert len(out) == 6
    assert sleep.calls == [30.0, 2.0]
    assert gen.calls == 2


def test_parsing_and_cleaning_are_defensive():
    assert parse_items("not json") == []
    assert parse_items('{"items": "nope"}') == []
    assert parse_items('{"items": [1, {"a": 2}]}') == [{"a": 2}]
    assert clean_question("  What   is​ asthma?  ") == "What is asthma?"
    assert clean_question("short") is None
    assert clean_question(42) is None
    assert QUESTION_SCHEMA["properties"]["items"]["items"]["required"] == ["pid", "en", "fr", "ar"]
