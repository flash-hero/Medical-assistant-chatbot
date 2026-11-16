"""Fixtures for the RAG track tests (helpers live in rag_fixtures.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rag_fixtures import source_entry, write_registry


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
