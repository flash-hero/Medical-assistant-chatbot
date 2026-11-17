"""Fixtures for the RAG track tests (helpers live in rag_fixtures.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag_fixtures import source_entry, write_registry


@pytest.fixture(autouse=True)
def _never_load_the_real_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building a LocalEmbeddingProvider is fine (the model loads lazily); LOADING it (~1.2 GB) in a test is
    not: memory is short and only one process may hold the model. Fail loudly instead (pytest.fail raises a
    BaseException, so the provider's `except Exception` cannot turn it into a silent sparse-only degrade)."""

    def factory(model_id: str, cache_dir: Path, threads: int | None):  # same signature as the real one
        def refuse():
            pytest.fail(f"a test tried to load the real embedding model {model_id}")

        return refuse

    monkeypatch.setattr("app.llm.local_embedder.fastembed_factory", factory)


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    excluded = source_entry(
        "x_bad_site",
        status="excluded",
        reuse_mode="link_only",
        domains=["bad.example.com"],
        license={"id": "proprietary", "name": "All rights reserved", "commercial_use": "no"},
    )
    held = source_entry("held_src", status="hold")
    return write_registry(tmp_path / "registry.yaml", [source_entry("demo_src"), held, excluded])
