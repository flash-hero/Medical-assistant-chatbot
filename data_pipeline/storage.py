"""Atomic writers for the corpus files. Temp file in the same directory, then os.replace."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from core.schemas.document import Document


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_jsonl(path: Path, lines: Iterable[str]) -> tuple[int, str]:
    """Write already-serialised JSON lines atomically. Returns (line count, sha256 of the file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            for line in lines:
                payload = (line + "\n").encode("utf-8")
                handle.write(payload)
                digest.update(payload)
                count += 1
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return count, digest.hexdigest()


def write_documents_jsonl(path: Path, documents: Iterable[Document]) -> tuple[int, str]:
    return write_jsonl(path, (doc.model_dump_json() for doc in documents))


def read_documents_jsonl(path: Path) -> Iterator[Document]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield Document.model_validate_json(line)


def read_json_lines(path: Path) -> Iterator[dict[str, object]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def write_ready_marker(ready_path: Path, *, source_id: str, documents: int, sha256_of_jsonl: str) -> None:
    payload = {
        "source_id": source_id,
        "documents": documents,
        "sha256_of_jsonl": sha256_of_jsonl,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_text(ready_path, json.dumps(payload, indent=2) + "\n")
