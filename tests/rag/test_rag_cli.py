"""End-to-end CLI: build (incl. cache-only), status, eval (offline + online), promote, rollback.

Runs against a local-path Qdrant and the fake LLM backend; no network."""

import json
import re
import shutil
from datetime import UTC, datetime

import pytest
from qdrant_client import AsyncQdrantClient
from rag_fixtures import QDRANT_LOCAL_WARNINGS, make_doc, retrieval_docs, write_normalized
from test_rag_eval_runner import gold_rows
from test_rag_eval_units import _passing_report

from core.config import Settings
from evals.retrieval.gold import save_gold
from evals.retrieval.report import write_report
from rag.cli import EXIT_ERROR, EXIT_GATE, EXIT_OK, EXIT_QUOTA, main
from rag.manifest import read_active
from rag.paths import DataPaths

pytestmark = [pytest.mark.filterwarnings(w) for w in QDRANT_LOCAL_WARNINGS]


@pytest.fixture
def env(tmp_path, registry_path, monkeypatch):
    settings = Settings(
        AUSCULTA_DATA_ROOT=str(tmp_path / "data"),
        AUSCULTA_LLM_BACKEND="fake",
        AUSCULTA_SESSION_SECRET="cli-test-secret-0123456789",
        QDRANT_ALIAS="cli_alias",
    )
    from rag.registry import load_registry

    monkeypatch.setattr("rag.cli.get_settings", lambda: settings)
    monkeypatch.setattr("rag.cli.load_registry", lambda: load_registry(registry_path))
    qpath = str(tmp_path / "qdrant")
    monkeypatch.setattr("rag.cli.qdrant_client", lambda s, timeout=60: AsyncQdrantClient(path=qpath))
    # reuse the machine's BM25 stopword assets: the test must not download anything
    shared = DataPaths.from_settings(Settings()).fastembed_dir
    shutil.copytree(
        shared, DataPaths(tmp_path / "data").fastembed_dir, ignore=shutil.ignore_patterns(".locks")
    )
    write_normalized(tmp_path / "data", "demo_src", retrieval_docs())
    save_gold(tmp_path / "gold" / "g.jsonl", gold_rows())
    return DataPaths(tmp_path / "data"), tmp_path / "gold"


def _passing(paths: DataPaths, collection: str, minute: int) -> None:
    when = datetime(2026, 11, 16, 3, minute, tzinfo=UTC)
    write_report(paths.reports_dir, _passing_report(collection, when), when)


def test_cli_build_eval_promote_rollback(env, capsys):
    paths, gold = env
    assert main(["build", "--corpus-version", "c1", "--sources", "demo_src"]) == EXIT_OK
    assert main(["build", "--corpus-version", "c2", "--sources", "demo_src", "--cache-only"]) == EXIT_OK
    assert "embedded 0 (api calls 0)" in capsys.readouterr().out

    assert main(["status"]) == EXIT_OK
    status = capsys.readouterr().out
    found = re.search(
        r"ausculta_corpus_c1: (\d+) points, build indexed (\d+)/(\d+), manifest (\d+) chunks", status
    )
    assert found
    assert len(set(found.groups())) == 1
    assert "signed=True" in status

    offline = [
        "eval",
        "--collection",
        "ausculta_corpus_c1",
        "--offline",
        "--no-resume-check",
        "--gold",
        str(gold),
    ]
    assert main(offline) == EXIT_OK
    assert "MISSING" in capsys.readouterr().out
    assert main(["promote", "ausculta_corpus_c1"]) == EXIT_GATE  # offline reports never promote

    online = [
        "eval",
        "--collection",
        "ausculta_corpus_c2",
        "--gold",
        str(gold),
        "--no-resume-check",
        "--rerank-sample",
        "1",
        "--rerank-pause-s",
        "0",
        "--embed-latency-sample",
        "1",
    ]
    assert main(online) in (EXIT_OK, EXIT_GATE)
    assert paths.retrieval_config_file("ausculta_corpus_c2").exists()

    _passing(paths, "ausculta_corpus_c1", 10)
    _passing(paths, "ausculta_corpus_c2", 11)
    assert main(["promote", "ausculta_corpus_c1"]) == EXIT_OK
    assert read_active(paths).collection == "ausculta_corpus_c1"
    assert main(["promote", "ausculta_corpus_c2"]) == EXIT_OK
    active = read_active(paths)
    assert active.collection == "ausculta_corpus_c2"
    assert active.previous_collection == "ausculta_corpus_c1"
    assert main(["rollback"]) == EXIT_OK
    assert read_active(paths).collection == "ausculta_corpus_c1"

    manifest = paths.manifest_file("ausculta_corpus_c2")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps({**data, "signature": "0" * 64}), encoding="utf-8")
    assert main(["promote", "ausculta_corpus_c2"]) == EXIT_ERROR
    assert "do not match the signed manifest" in capsys.readouterr().out


def test_cache_only_build_stops_on_a_miss_and_bad_inputs_fail(env, tmp_path, capsys):
    write_normalized(tmp_path / "data", "demo_src", [make_doc("brand_new_topic", title="Brand New Topic")])
    assert main(["build", "--corpus-version", "c3", "--sources", "demo_src", "--cache-only"]) == EXIT_QUOTA
    out = capsys.readouterr().out
    assert "0 API calls made" in out
    assert "--corpus-version c3 --sources demo_src" in out
    assert main(["build", "--corpus-version", "c4", "--sources", "held_src"]) == EXIT_ERROR
    assert main(["rollback"]) == EXIT_ERROR
    assert main(["promote", "ausculta_corpus_nope"]) == EXIT_GATE


def test_build_refuses_without_a_session_secret(env, monkeypatch):
    monkeypatch.setattr("rag.cli.get_settings", lambda: Settings(AUSCULTA_SESSION_SECRET=None))
    assert main(["build", "--corpus-version", "c5", "--sources", "demo_src"]) == EXIT_ERROR


def test_cli_gold_generates_unreviewed_files_within_the_call_budget(env, tmp_path, monkeypatch, capsys):
    from test_rag_eval_generate import responder

    from evals.fakes.fake_llm import FakeLLMProvider
    from evals.retrieval.gold import load_gold

    fake = FakeLLMProvider(responder=responder)
    monkeypatch.setattr("rag.cli.llm_provider", lambda settings: fake)
    monkeypatch.setattr("evals.retrieval.generate.GoldGenerator.min_interval_s", 0.0)
    assert main(["build", "--corpus-version", "g1", "--sources", "demo_src"]) == EXIT_OK
    out_dir = tmp_path / "generated"
    args = ["gold", "--passages", "4", "--batch", "2", "--ooc", "2", "--min-tokens", "1", "--out", str(out_dir)]
    assert main(args) == EXIT_OK
    printed = capsys.readouterr().out
    assert "Generation calls used: 4/120" in printed  # 2 question batches + 1 OOC + 1 rewrite
    rows = load_gold(out_dir)
    assert len(rows) == 4 * 3 + 2 * 3
    assert {r.status for r in rows} == {"llm_generated_unreviewed"}
    assert all(r.rewrite == "model" for r in rows if r.language != "en")
    capped = ["gold", "--passages", "4", "--batch", "2", "--max-calls", "1", "--out", str(tmp_path / "capped")]
    assert main([*capped, "--min-tokens", "1"]) == EXIT_ERROR
    assert "Partial output was saved" in capsys.readouterr().out
