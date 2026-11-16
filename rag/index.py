"""Qdrant collection schema and operations (qdrant-client 1.20, server 1.20.1).

One collection per corpus version (ausculta_corpus_<version>) behind the alias Settings.qdrant_alias.
  dense      768-d cosine, HNSW, int8 scalar quantisation kept in RAM, original vectors on disk (rescoring)
  bm25_xx    sparse, modifier=IDF (server-side IDF over each language's documents)
Payload: every Chunk field (enough to build RetrievedPassage) with keyword/integer payload indexes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from core.models import EMBED_DIM
from core.schemas.document import Chunk
from rag.errors import IndexMismatch
from rag.sparse import SPARSE_VECTORS, SparseVec

DENSE_VECTOR = "dense"
KEYWORD_INDEXES = ("language", "source_id", "content_type", "reuse_mode", "doc_id", "parent_id")
INTEGER_INDEXES = ("trust_tier",)
POINT_NAMESPACE = uuid.UUID("6f1d3c3e-7a52-4c55-9a7e-0b8f2d0c5a11")
UPSERT_BATCH = 128
_CHUNK_FIELDS = frozenset(Chunk.model_fields)


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, chunk_id))


def chunk_payload(chunk: Chunk) -> dict[str, Any]:
    return chunk.model_dump(mode="json")


def chunk_from_payload(payload: Mapping[str, Any]) -> Chunk:
    return Chunk.model_validate({k: v for k, v in payload.items() if k in _CHUNK_FIELDS})


def _schema(dim: int) -> dict[str, Any]:
    return {
        "vectors_config": {
            DENSE_VECTOR: models.VectorParams(
                size=dim,
                distance=models.Distance.COSINE,
                on_disk=True,  # originals on disk, read only for rescoring
                hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128),
            )
        },
        "sparse_vectors_config": {
            name: models.SparseVectorParams(modifier=models.Modifier.IDF) for name in SPARSE_VECTORS.values()
        },
        "quantization_config": models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(
                type=models.ScalarType.INT8, quantile=0.99, always_ram=True
            )
        ),
        "on_disk_payload": True,
    }


def _check_schema(info: models.CollectionInfo, name: str, dim: int) -> None:
    vectors = info.config.params.vectors
    dense = vectors.get(DENSE_VECTOR) if isinstance(vectors, dict) else None
    if dense is None or dense.size != dim:
        raise IndexMismatch(f"collection {name!r} has no {DENSE_VECTOR!r} vector of size {dim}")
    sparse = set((info.config.params.sparse_vectors or {}).keys())
    missing = set(SPARSE_VECTORS.values()) - sparse
    if missing:
        raise IndexMismatch(f"collection {name!r} lacks sparse vectors {sorted(missing)}")


async def ensure_collection(client: AsyncQdrantClient, name: str, *, dim: int = EMBED_DIM) -> bool:
    """Create the collection and payload indexes if absent. Returns True when it was created."""
    if await client.collection_exists(name):
        _check_schema(await client.get_collection(name), name, dim)
        return False
    await client.create_collection(name, **_schema(dim))
    for field in KEYWORD_INDEXES:
        await client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
    for field in INTEGER_INDEXES:
        await client.create_payload_index(name, field, models.PayloadSchemaType.INTEGER)
    return True


def build_points(
    chunks: Sequence[Chunk], dense: Mapping[str, Sequence[float]], sparse: Mapping[str, SparseVec]
) -> list[models.PointStruct]:
    """dense is keyed by chunk checksum, sparse by chunk_id (empty sparse vectors are omitted)."""
    points = []
    for chunk in chunks:
        vector: dict[str, Any] = {DENSE_VECTOR: list(dense[chunk.checksum])}
        sv = sparse.get(chunk.chunk_id)
        if sv is not None and not sv.empty:
            vector[SPARSE_VECTORS[str(chunk.language)]] = sv.to_qdrant()
        points.append(
            models.PointStruct(id=point_id(chunk.chunk_id), vector=vector, payload=chunk_payload(chunk))
        )
    return points


async def upsert_points(
    client: AsyncQdrantClient, name: str, points: Sequence[models.PointStruct], *, batch: int = UPSERT_BATCH
) -> None:
    for start in range(0, len(points), batch):
        await client.upsert(name, list(points[start : start + batch]), wait=True)


async def count_points(client: AsyncQdrantClient, name: str) -> int:
    return (await client.count(name, exact=True)).count


async def point_ids(client: AsyncQdrantClient, name: str) -> set[str]:
    ids: set[str] = set()
    offset: Any = None
    while True:
        records, offset = await client.scroll(
            name, limit=1024, offset=offset, with_payload=False, with_vectors=False
        )
        ids.update(str(r.id) for r in records)
        if offset is None:
            return ids


async def prune_points(client: AsyncQdrantClient, name: str, keep: Iterable[str]) -> int:
    """Delete points that are not part of this build (e.g. left over from an earlier --limit run)."""
    extra = sorted((await point_ids(client, name)) - set(keep))
    if extra:
        await client.delete(name, points_selector=models.PointIdsList(points=list(extra)), wait=True)
    return len(extra)


async def alias_target(client: AsyncQdrantClient, alias: str) -> str | None:
    for item in (await client.get_aliases()).aliases:
        if item.alias_name == alias:
            return item.collection_name
    return None


async def switch_alias(client: AsyncQdrantClient, alias: str, collection: str) -> str | None:
    """Atomically point `alias` at `collection` (one aliases request). Returns the previous target."""
    if not await client.collection_exists(collection):
        raise IndexMismatch(f"collection {collection!r} does not exist")
    previous = await alias_target(client, alias)
    ops: list[Any] = []
    if previous is not None:
        ops.append(models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias)))
    ops.append(
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(collection_name=collection, alias_name=alias)
        )
    )
    await client.update_collection_aliases(change_aliases_operations=ops)
    return previous


async def list_collections(client: AsyncQdrantClient) -> list[str]:
    return sorted(c.name for c in (await client.get_collections()).collections)
