"""Verify a collection against its signed manifest (review S8/P6): at promote, rollback and API startup.

A collection is trusted only when ALL of these hold:
  - manifests/<collection>.manifest.json exists, names this collection, and was built with the embedding
    model this deployment embeds queries with (otherwise dense retrieval would compare different spaces);
  - every stored chunk's checksum equals sha256(context_header + "\\n" + text) recomputed from its stored
    text, and its point id is the one derived from its chunk_id;
  - the number of stored points equals the manifest's chunk count;
  - the manifest's HMAC (HKDF-derived key, rag/signing.py) matches the digest of the served fields of the
    payloads actually stored in Qdrant.

API startup: `await verify_live_corpus(settings)` returns VerifiedCorpus or raises CorpusUnverified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from core.config import Settings
from core.models import EMBED_DIM
from rag.embedding import embed_model_id
from rag.errors import CorpusUnverified
from rag.index import alias_target, point_id
from rag.manifest import read_manifest
from rag.paths import DataPaths
from rag.signing import SIGNED_FIELDS, corpus_digest, record_hash, signature_matches, text_checksum

SCAN_PAGE = 2048
_QDRANT_ERRORS = (UnexpectedResponse, ResponseHandlingException, httpx.HTTPError, OSError)


@dataclass(frozen=True)
class CollectionScan:
    points: int
    digest: str
    bad_checksums: int  # stored checksum != sha256(context_header + "\n" + stored text)
    misplaced: int  # point id is not point_id(chunk_id)


@dataclass(frozen=True)
class VerifiedCorpus:
    collection: str
    corpus_version: str
    embed_model: str
    chunks: int


async def scan_collection(client: AsyncQdrantClient, collection: str) -> CollectionScan:
    """Stream every payload once (signed fields only, no vectors) and hash it."""
    hashes: list[str] = []
    bad = misplaced = 0
    offset: Any = None
    while True:
        records, offset = await client.scroll(
            collection, limit=SCAN_PAGE, offset=offset, with_payload=list(SIGNED_FIELDS), with_vectors=False
        )
        for rec in records:
            payload = rec.payload or {}
            bad += text_checksum(payload) != payload.get("checksum")
            misplaced += str(rec.id) != point_id(str(payload.get("chunk_id", "")))
            hashes.append(record_hash(payload))
        if offset is None:
            return CollectionScan(len(hashes), corpus_digest(hashes), bad, misplaced)


async def verify_collection(
    client: AsyncQdrantClient,
    paths: DataPaths,
    collection: str,
    secret: str,
    *,
    embed_model: str | None = None,
    embed_dim: int = EMBED_DIM,
) -> VerifiedCorpus:
    """Raise CorpusUnverified unless `collection` matches its signed manifest (see module docstring).
    `embed_model` (the deployment's embedding namespace, rag.embedding.embed_model_id) is checked when
    given."""
    if not secret:
        raise CorpusUnverified("AUSCULTA_SESSION_SECRET is not set: the corpus manifest cannot be verified")
    if not await client.collection_exists(collection):
        raise CorpusUnverified(f"collection {collection!r} does not exist")
    manifest = read_manifest(paths, collection)
    if manifest is None:
        raise CorpusUnverified(f"{collection} has no manifest (incomplete build?)")
    if manifest.collection != collection:
        raise CorpusUnverified(f"{collection}: its manifest describes {manifest.collection!r}")
    if embed_model is not None and (manifest.embed_model, manifest.embed_dim) != (embed_model, embed_dim):
        raise CorpusUnverified(
            f"{collection} holds {manifest.embed_model} vectors ({manifest.embed_dim}-d) but this deployment "
            f"embeds queries with {embed_model} ({embed_dim}-d): rebuild the collection or change "
            "AUSCULTA_EMBED_BACKEND"
        )
    scan = await scan_collection(client, collection)
    if scan.bad_checksums or scan.misplaced:
        raise CorpusUnverified(
            f"{collection}: {scan.bad_checksums} stored chunk(s) whose text no longer matches their "
            "checksum, "
            f"{scan.misplaced} point(s) under a foreign id"
        )
    if scan.points != manifest.chunks or not signature_matches(manifest, scan.digest, secret):
        raise CorpusUnverified(f"{collection}: stored chunks do not match the signed manifest")
    return VerifiedCorpus(collection, manifest.corpus_version, manifest.embed_model, manifest.chunks)


async def verify_live_corpus(
    settings: Settings, *, client: AsyncQdrantClient | None = None
) -> VerifiedCorpus:
    """API startup check of the collection behind settings.qdrant_alias, against the manifest signed with
    the key derived from AUSCULTA_SESSION_SECRET and the embedding model of AUSCULTA_EMBED_BACKEND.

    Returns what was verified; raises CorpusUnverified (code "corpus_unverified", a rag.errors.IndexMismatch)
    on any failure, including no secret, no alias and Qdrant unreachable. Reads every stored payload once
    (signed fields, no vectors), so its duration grows with the corpus. `client` is for tests; by default
    one is opened from settings and closed again."""
    own = client is None
    if client is None:
        key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        client = AsyncQdrantClient(url=settings.qdrant_url, api_key=key, timeout=30)
    secret = settings.session_secret.get_secret_value() if settings.session_secret else ""
    try:
        collection = await alias_target(client, settings.qdrant_alias)
        if collection is None:
            raise CorpusUnverified(f"alias {settings.qdrant_alias!r} does not point at any collection")
        return await verify_collection(
            client,
            DataPaths.from_settings(settings),
            collection,
            secret,
            embed_model=embed_model_id(settings.embed_backend),
        )
    except _QDRANT_ERRORS as exc:
        raise CorpusUnverified(f"vector store unavailable ({type(exc).__name__})") from exc
    finally:
        if own:
            await client.close()
