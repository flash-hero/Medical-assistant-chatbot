"""Signed corpus manifests, build state and the active-collection pointer (all JSON in manifests/)."""

from __future__ import annotations

import hashlib
import hmac
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from core.errors import InvalidInput
from core.schemas.document import Chunk, CorpusManifest
from rag.fileio import atomic_write_text, read_json
from rag.paths import DataPaths


def sign_checksums(checksums: Iterable[str], secret: str) -> str:
    """HMAC-SHA256 over the newline-joined, sorted chunk checksums."""
    if not secret:
        raise InvalidInput("AUSCULTA_SESSION_SECRET is required to sign the corpus manifest")
    message = "\n".join(sorted(checksums)).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_manifest(manifest: CorpusManifest, checksums: Iterable[str], secret: str) -> bool:
    return hmac.compare_digest(manifest.signature, sign_checksums(checksums, secret))


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
    return CorpusManifest(
        corpus_version=corpus_version,
        collection=collection,
        embed_model=embed_model,
        embed_dim=embed_dim,
        created_at=created_at,
        sources=dict(sorted(per_source.items())),
        documents=len({c.doc_id for c in chunks}),
        chunks=len(chunks),
        signature=sign_checksums((c.checksum for c in chunks), secret),
    )


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
