"""UTF-8, atomic file helpers (temp file in the same directory, then os.replace)."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def atomic_write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def atomic_write_json(path: Path, data: Any) -> Path:
    return atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: Iterable[BaseModel | dict[str, Any]]) -> int:
    lines: list[str] = []
    for row in rows:
        if isinstance(row, BaseModel):
            lines.append(row.model_dump_json())
        else:
            lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    atomic_write_text(path, "".join(f"{line}\n" for line in lines))
    return len(lines)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (line number, raw line) for non-blank lines. Parsing/validation is the caller's job so that
    one bad line can be counted and skipped without aborting a whole file."""
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            if stripped:
                yield lineno, stripped
