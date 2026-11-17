from __future__ import annotations

from pathlib import Path

import pytest
from dp_helpers import make_record

from core.schemas.source import SourceRecord
from data_pipeline.paths import DataPaths


@pytest.fixture
def record() -> SourceRecord:
    return make_record()


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    return DataPaths(tmp_path / "data").ensure()
