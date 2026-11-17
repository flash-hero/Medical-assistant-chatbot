"""Signed corpus manifests, build state and the active-collection pointer (all JSON in manifests/).

Signature scheme: rag/signing.py. Verification against the stored Qdrant payloads: rag/verify.py.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from core.schemas.document import Chunk, CorpusManifest
from rag.fileio import atomic_write_text, read_json
from rag.paths import DataPaths
from rag.signing import corpus_digest, record_hash, sign_manifest


def chunks_digest(chunks: Sequence[Chunk]) -> str:
    """Corpus digest of chunks as they are stored in Qdrant (payload = Chunk.model_dump(mode="json"))."""
    return corpus_digest(record_hash(c.model_dump(mode="json")) for c in chunks)


def make_manifest(
    *,
    corpus_version: str,
    collection: str,
    chunks: Sequence[Chunk],
    embed_model: str,
    embed_dim: int,
    secret: str,
    created_at: datetime,
) -> CorpusManifest:
    per_source = Counter(c.source_id for c in chunks)
    unsigned = CorpusManifest(
        corpus_version=corpus_version,
        collection=collection,
        embed_model=embed_model,
        embed_dim=embed_dim,
        created_at=created_at,
        sources=dict(sorted(per_source.items())),
        documents=len({c.doc_id for c in chunks}),
        chunks=len(chunks),
    )
    signature = sign_manifest(unsigned, chunks_digest(chunks), secret)
    return unsigned.model_copy(update={"signature": signature})


def write_manifest(paths: DataPaths, manifest: CorpusManifest) -> str:
    path = paths.manifest_file(manifest.collection)
    atomic_write_text(path, manifest.model_dump_json(indent=2) + "\n")
    return str(path)


def read_manifest(paths: DataPaths, collection: str) -> CorpusManifest | None:
    path = paths.manifest_file(collection)
    if not path.exists():
        return None
    return CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))


# ---- build state -------------------------------------------------------------------------------------
BuildStatus = Literal["chunked", "indexing", "quota_exhausted", "failed", "indexed"]


class BuildState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus_version: str
    collection: str
    sources: tuple[str, ...]
    status: BuildStatus
    documents: int = 0
    total_chunks: int = 0
    indexed_chunks: int = 0
    embedded_this_run: int = 0
    cache_hits_this_run: int = 0
    updated_at: datetime
    resume_command: str = ""
    error: str | None = None


def write_build_state(paths: DataPaths, state: BuildState) -> None:
    atomic_write_text(paths.build_state_file(state.collection), state.model_dump_json(indent=2) + "\n")


def read_build_state(paths: DataPaths, collection: str) -> BuildState | None:
    path = paths.build_state_file(collection)
    if not path.exists():
        return None
    return BuildState.model_validate_json(path.read_text(encoding="utf-8"))


# ---- active pointer ----------------------------------------------------------------------------------
class ActivePointer(BaseModel):
    """Which collection the alias points at (written by promote; read by the API for corpus_version)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    alias: str
    collection: str
    corpus_version: str
    promoted_at: datetime
    previous_collection: str | None = None
    # Set only by `promote --override-gates`: why a collection went live without a passing gate report
    # (e.g. a development seed). A normal promotion clears it.
    gate_override: str | None = None


def write_active(paths: DataPaths, pointer: ActivePointer) -> None:
    atomic_write_text(paths.active_pointer, pointer.model_dump_json(indent=2) + "\n")


def read_active(paths: DataPaths) -> ActivePointer | None:
    path = paths.active_pointer
    if not path.exists():
        return None
    try:
        return ActivePointer.model_validate(read_json(path))
    except (ValueError, ValidationError):
        return None
