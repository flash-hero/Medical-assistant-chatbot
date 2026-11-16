"""Data-root layout owned by the RAG track (all paths derive from Settings.data_root).

normalized/{source_id}.jsonl            input, written by data_pipeline (read-only here)
normalized/_ready/{source_id}.json      completion marker written by data_pipeline
chunks/{corpus_version}/{source}.jsonl  chunker output
embed-cache/embeddings.sqlite3          persistent embedding cache (model id, dim, checksum)
embed-cache/fastembed/                  fastembed BM25 assets (stopword lists)
manifests/                              signed corpus manifests, build state, active pointer
reports/retrieval/                      evaluation reports
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.config import REPO_ROOT, Settings
from core.errors import InvalidInput

COLLECTION_PREFIX = "ausculta_corpus_"
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,47}$")
_SOURCE = re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")
_COLLECTION = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")

REGISTRY_PATH = REPO_ROOT / "data_pipeline" / "sources" / "registry.yaml"
DRUG_SYNONYMS_PATH = REPO_ROOT / "data_pipeline" / "drug_synonyms.yaml"
GOLD_DIR = REPO_ROOT / "evals" / "retrieval" / "gold"
GATES_PATH = REPO_ROOT / "evals" / "gates.yaml"


def validate_corpus_version(version: str) -> str:
    if not _VERSION.match(version):
        raise InvalidInput(f"invalid corpus version {version!r} (letters, digits, '.', '_', '-')")
    return version


def validate_source_id(source_id: str) -> str:
    if not _SOURCE.match(source_id):
        raise InvalidInput(f"invalid source id {source_id!r}")
    return source_id


def validate_collection(name: str) -> str:
    if not _COLLECTION.match(name):
        raise InvalidInput(f"invalid collection name {name!r}")
    return name


def collection_name(corpus_version: str) -> str:
    """One Qdrant collection per corpus version: '2026-11-15.1' -> 'ausculta_corpus_2026_11_15_1'."""
    slug = re.sub(r"[^a-z0-9]+", "_", validate_corpus_version(corpus_version).lower()).strip("_")
    return f"{COLLECTION_PREFIX}{slug}"


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> DataPaths:
        return cls(root=Path(settings.data_root))

    @property
    def normalized_dir(self) -> Path:
        return self.root / "normalized"

    @property
    def ready_dir(self) -> Path:
        return self.normalized_dir / "_ready"

    def normalized_file(self, source_id: str) -> Path:
        return self.normalized_dir / f"{validate_source_id(source_id)}.jsonl"

    def ready_marker(self, source_id: str) -> Path:
        return self.ready_dir / f"{validate_source_id(source_id)}.json"

    def chunks_dir(self, corpus_version: str) -> Path:
        return self.root / "chunks" / validate_corpus_version(corpus_version)

    def chunks_file(self, corpus_version: str, source_id: str) -> Path:
        return self.chunks_dir(corpus_version) / f"{validate_source_id(source_id)}.jsonl"

    @property
    def embed_cache_dir(self) -> Path:
        return self.root / "embed-cache"

    @property
    def embed_cache_db(self) -> Path:
        return self.embed_cache_dir / "embeddings.sqlite3"

    @property
    def query_cache_db(self) -> Path:
        return self.embed_cache_dir / "query-embeddings.sqlite3"

    @property
    def fastembed_dir(self) -> Path:
        return self.embed_cache_dir / "fastembed"

    @property
    def manifests_dir(self) -> Path:
        return self.root / "manifests"

    def manifest_file(self, collection: str) -> Path:
        return self.manifests_dir / f"{validate_collection(collection)}.manifest.json"

    def retrieval_config_file(self, collection: str) -> Path:
        return self.manifests_dir / f"{validate_collection(collection)}.retrieval.json"

    def build_state_file(self, collection: str) -> Path:
        return self.manifests_dir / "build-state" / f"{validate_collection(collection)}.json"

    @property
    def active_pointer(self) -> Path:
        return self.manifests_dir / "active.json"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports" / "retrieval"
