"""Filesystem layout of the data root (outside the repo and outside OneDrive)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_ROOT = Path("C:/dev/ausculta-data")
REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = Path(__file__).resolve().parent / "sources" / "registry.yaml"
DOCS_SOURCES_DIR = REPO_ROOT / "docs" / "sources"


@dataclass(frozen=True)
class DataPaths:
    """All directories this track writes to, derived from one root."""

    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def normalized(self) -> Path:
        return self.root / "normalized"

    @property
    def ready(self) -> Path:
        return self.normalized / "_ready"

    @property
    def quarantine(self) -> Path:
        return self.root / "quarantine"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def fetch_cache(self) -> Path:
        return self.root / "fetch-cache"

    def raw_dir(self, source_id: str) -> Path:
        return self.raw / source_id

    def normalized_file(self, source_id: str) -> Path:
        return self.normalized / f"{source_id}.jsonl"

    def ready_file(self, source_id: str) -> Path:
        return self.ready / f"{source_id}.json"

    def quarantine_file(self, source_id: str) -> Path:
        return self.quarantine / f"{source_id}.jsonl"

    def ensure(self) -> DataPaths:
        for directory in (self.raw, self.normalized, self.ready, self.quarantine, self.reports, self.fetch_cache):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def default_paths() -> DataPaths:
    """Data root from AUSCULTA_DATA_ROOT (same variable as core.config) without loading .env."""
    return DataPaths(Path(os.environ.get("AUSCULTA_DATA_ROOT", str(DEFAULT_DATA_ROOT))))
