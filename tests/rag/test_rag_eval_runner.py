from datetime import UTC, datetime

import pytest
from qdrant_client import AsyncQdrantClient
from rag_fixtures import QDRANT_LOCAL_WARNINGS, build_index, retrieval_docs

from core.config import Settings
from evals.fakes.fake_llm import FakeLLMProvider
from evals.retrieval.evaluate import Ablation, AblationRun, Outcome, paired_ndcg, sample_rows, summarize
from evals.retrieval.gold import GoldQuery, save_gold
from evals.retrieval.resume_check import measure_resume
from evals.retrieval.runner import EvalContext, EvalOptions, evaluable, run_eval
from rag.chunking import chunk_document
from rag.paths import DataPaths
from rag.retrieval_config import RetrievalConfig, load_retrieval_config
from rag.sparse import SparseEncoder

pytestmark = [pytest.mark.filterwarnings(w) for w in QDRANT_LOCAL_WARNINGS]
NOW = datetime(2026, 11, 16, 2, 0, tzinfo=UTC)
QUESTIONS = {
    "asthma": (
        "What triggers asthma and wheezing?",
        "Qu'est-ce qui déclenche l'asthme ?",
        "ما الذي يسبب نوبات الربو؟",
    ),
    "diabetes": ("What does an A1C test measure?", "Que mesure le test A1C ?", "ماذا يقيس اختبار A1C؟"),
    "migraine": (
        "What is a migraine aura?",
        "Qu'est-ce qu'une aura migraineuse ?",
        "ما هي هالة الصداع النصفي؟",
    ),
    "measles": (
        "How many MMR vaccine doses protect against measles?",
        "Combien de doses du vaccin ROR ?",
        "كم جرعة من لقاح الحصبة؟",
    ),
}
OOC = (
    ("What are the side effects of zorvalimab?", "Effets du zorvalimab ?", "آثار زورفاليماب؟"),
    ("How do I bake sourdough bread?", "Comment faire du pain au levain ?", "كيف أخبز خبز العجين المخمر؟"),
)


@pytest.fixture(scope="module")
def sparse() -> SparseEncoder:
    return SparseEncoder(DataPaths.from_settings(Settings()).fastembed_dir)


def gold_rows() -> list[GoldQuery]:
    docs = {d.doc_id.split(":")[1]: d for d in retrieval_docs()}
    rows = []
    for name, (en, fr, ar) in QUESTIONS.items():
        chunk = chunk_document(docs[name], publisher="DemoPlus")[0]
        for lang, text in (("en", en), ("fr", fr), ("ar", ar)):
            extra = {} if lang == "en" else {"search_queries": (en,), "rewrite": "parallel_en"}
            rows.append(
                GoldQuery(
                    qid=f"{name}-{lang}",
                    language=lang,
                    question=text,
                    answerable=True,
                    kind="passage",
                    relevant_chunk_ids=(chunk.chunk_id,),
                    status="llm_generated_unreviewed",
                    generator="test",
                    created_at=NOW,
                    **extra,
                )
            )
    for i, (en, fr, ar) in enumerate(OOC):
        for lang, text in (("en", en), ("fr", fr), ("ar", ar)):
            extra = {} if lang == "en" else {"search_queries": (en,), "rewrite": "parallel_en"}
            rows.append(
                GoldQuery(
                    qid=f"ooc{i}-{lang}",
                    language=lang,
                    question=text,
                    answerable=False,
                    kind="ooc_fictional",
                    status="llm_generated_unreviewed",
                    generator="test",
                    created_at=NOW,
                    **extra,
                )
            )
    missing = rows[0].model_copy(update={"qid": "not-indexed-en", "relevant_chunk_ids": ("nope#s#0",)})
    return [*rows, missing]


@pytest.fixture
async def setup(tmp_path, registry_path, sparse):
    client = AsyncQdrantClient(location=":memory:")
    collection = await build_index(tmp_path, registry_path, client, retrieval_docs())
    save_gold(tmp_path / "gold" / "g.jsonl", gold_rows())
    yield client, collection, tmp_path
    await client.close()


async def test_online_eval_runs_all_ablations_calibrates_and_writes_config(setup, sparse):
    client, collection, tmp = setup
    llm = FakeLLMProvider()
    ctx = EvalContext(client, llm, DataPaths(tmp / "data"), sparse, NOW)
    opts = EvalOptions(
        collection=collection,
        gold_dir=tmp / "gold",
        rerank_sample=2,
        rerank_pause_s=0.0,
        embed_latency_sample=2,
        resume_check=False,
        backend="fake",
    )
    report = await run_eval(ctx, opts)
    names = [a["ablation"] for a in report["ablations"]]
    assert names == ["dense", "sparse", "hybrid", "hybrid_native", "hybrid_rerank"]
    assert report["gold"]["skipped_not_indexed"] == 1
    assert report["gold"]["answerable"] == {"en": 4, "fr": 4, "ar": 4}
    hybrid = report["ablations"][2]["by_language"]
    assert hybrid["en"]["recall_at_20"] == 1.0
    assert hybrid["all"]["latency"]["retrieval_ms_p95"] > 0
    assert report["pre_embed"]["embedded"] == report["pre_embed"]["texts"]
    assert report["rerank_decision"]["measured"]
    assert report["embed_api_latency"]["n"] == 2.0
    assert report["calibration"]["held_out"]["n_ooc"] == 6
    stored = load_retrieval_config(ctx.paths, collection)
    assert stored.confidence.calibrated
    assert {r["metric"] for r in report["gate_records"]} >= {"recall_at_20", "retrieval_latency_p95_ms"}
    assert {g["gate"] for g in report["gates"]} >= {"rag.recall_at_20_en", "rag.retrieval_p95_ms"}
    second = await run_eval(ctx, opts)  # query cache: nothing embedded twice
    assert second["pre_embed"]["embedded"] == 0


async def test_offline_eval_makes_no_api_call_and_emits_only_latency_records(setup, sparse):
    client, collection, tmp = setup
    from rag.offline import CacheOnlyLLM

    llm = CacheOnlyLLM()
    ctx = EvalContext(client, llm, DataPaths(tmp / "data"), sparse, NOW)
    opts = EvalOptions(collection=collection, gold_dir=tmp / "gold", offline=True, resume_check=False)
    report = await run_eval(ctx, opts)
    assert llm.refused_calls == 0
    assert [a["ablation"] for a in report["ablations"]] == ["sparse", "hybrid_standin"]
    assert report["ablations"][1]["scored"] is False
    assert "recall_at_20" not in report["ablations"][1]["by_language"]["en"]
    assert report["standin_vectors"] > 0
    assert [r["metric"] for r in report["gate_records"]] == ["retrieval_latency_p95_ms"]
    assert report["retrieval_config"] is None


async def test_resume_check_measures_zero_repeats(sparse):
    from rag.paths import DataPaths as P

    result = await measure_resume(
        P.from_settings(Settings()).fastembed_dir, n_docs=9, batch=2, fail_on_call=3
    )
    assert result.repeat_calls == 0
    assert result.first_run_embedded == 4
    assert result.resumed_embedded == result.total_chunks - 4


def test_sampling_summaries_and_paired_ndcg():
    rows = gold_rows()
    sample = sample_rows(rows, 2)
    assert sorted(r.language for r in sample) == ["ar", "ar", "en", "en", "fr", "fr"]
    assert sample == sample_rows(rows, 2)
    abl = Ablation("x", RetrievalConfig())
    good = Outcome("q", "en", "passage", True, "x", ("g",), (("g",),), True, 0.9, {}, {"retrieval_ms": 5.0})
    late = Outcome(
        "q", "en", "passage", True, "y", ("g",), (("a",), ("g",)), True, 0.9, {}, {"retrieval_ms": 7.0}
    )
    ooc = Outcome(
        "o",
        "en",
        "ooc_fictional",
        False,
        "x",
        (),
        (("a",),),
        False,
        0.1,
        {"lexical_coverage": 0.2},
        {"retrieval_ms": 3.0},
    )
    s = summarize(AblationRun(abl, (good, ooc)))
    assert s["by_language"]["en"]["recall_at_8"] == 1.0
    assert s["by_language"]["en"]["abstain_rate_out_of_corpus"] == 1.0
    assert s["by_language"]["en"]["degraded_rule_abstain_ooc"] == 1.0
    cmp = paired_ndcg(AblationRun(abl, (good,)), AblationRun(Ablation("y", RetrievalConfig()), (late,)))
    assert cmp["n"] == 1.0
    assert cmp["gain"] < 0
    assert paired_ndcg(AblationRun(abl, ()), AblationRun(abl, ())) == {"n": 0.0}
    _kept, skipped = evaluable(rows, {rows[0].relevant_chunk_ids[0]})
    assert skipped == len([r for r in rows if r.answerable]) - 3
