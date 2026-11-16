"""Append-only fetch manifest (JSONL) kept per source at raw/{source_id}/_manifest.jsonl."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from data_pipeline.storage import read_json_lines


@dataclass(frozen=True)
class ManifestEntry:
    url: str
    status: int
    sha256: str
    bytes: int
    fetched_at: str
    final_url: str = ""
    path: str = ""  # relative to raw/{source_id}/
    etag: str = ""
    last_modified: str = ""
    content_type: str = ""
    note: str = ""  # "not_modified", "robots_override", "resumed", ...

    @property
    def ok(self) -> bool:
        return self.status in (200, 206, 304) and bool(self.path)


class Manifest:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._latest: dict[str, ManifestEntry] = {}
        self._load()

    def _load(self) -> None:
        for row in read_json_lines(self._path):
            known = {k: v for k, v in row.items() if k in ManifestEntry.__dataclass_fields__}
            entry = ManifestEntry(**known)  # type: ignore[arg-type]
            previous = self._latest.get(entry.url)
            if entry.ok or previous is None or not previous.ok:
                self._latest[entry.url] = entry

    def latest(self, url: str) -> ManifestEntry | None:
        return self._latest.get(url)

    def entries(self) -> list[ManifestEntry]:
        return list(self._latest.values())

    def append(self, entry: ManifestEntry) -> None:
        line = json.dumps(asdict(entry), ensure_ascii=False)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            previous = self._latest.get(entry.url)
            if entry.ok or previous is None or not previous.ok:
                self._latest[entry.url] = entry
