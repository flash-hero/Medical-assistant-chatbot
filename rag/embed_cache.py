"""Persistent embedding cache in SQLite, keyed by (model id, dimension, key).

For documents the key is Chunk.checksum (sha256 of header + text), so an unchanged chunk is never embedded
twice, across builds and across corpus versions. Every batch is committed as soon as it is embedded, which
is what makes a killed build resumable with zero repeat embedding calls.
"""

from __future__ import annotations

import math
import sqlite3
from array import array
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
  model TEXT NOT NULL,
  dim INTEGER NOT NULL,
  key TEXT NOT NULL,
  vec BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (model, dim, key)
) WITHOUT ROWID
"""
_IN_BATCH = 500


def _encode(vec: Sequence[float], dim: int) -> bytes:
    if len(vec) != dim:
        raise ValueError(f"vector has {len(vec)} dims, expected {dim}")
    if not all(math.isfinite(x) for x in vec):
        raise ValueError("vector contains NaN or infinity")
    return array("f", vec).tobytes()


def _decode(blob: bytes, dim: int) -> list[float] | None:
    if len(blob) != dim * 4:
        return None
    return array("f", blob).tolist()


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._db = sqlite3.connect(str(path), timeout=30.0)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(_SCHEMA)
        self._db.commit()

    @property
    def path(self) -> Path:
        return self._path

    def get_many(self, model: str, dim: int, keys: Iterable[str]) -> dict[str, list[float]]:
        wanted = list(dict.fromkeys(keys))
        found: dict[str, list[float]] = {}
        for i in range(0, len(wanted), _IN_BATCH):
            batch = wanted[i : i + _IN_BATCH]
            marks = ",".join("?" * len(batch))
            rows = self._db.execute(
                f"SELECT key, vec FROM embeddings WHERE model=? AND dim=? AND key IN ({marks})",  # noqa: S608
                (model, dim, *batch),
            )
            for key, blob in rows:
                vec = _decode(blob, dim)
                if vec is not None:
                    found[key] = vec
        return found

    def put_many(self, model: str, dim: int, items: Mapping[str, Sequence[float]]) -> int:
        now = datetime.now(UTC).isoformat()
        rows = [(model, dim, key, _encode(vec, dim), now) for key, vec in items.items()]
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO embeddings (model, dim, key, vec, created_at) VALUES (?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def count(self, model: str | None = None, dim: int | None = None) -> int:
        if model is None:
            return int(self._db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0])
        row = self._db.execute(
            "SELECT COUNT(*) FROM embeddings WHERE model=? AND dim=?", (model, dim)
        ).fetchone()
        return int(row[0])

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> EmbeddingCache:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
