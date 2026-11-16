"""Hot view of the promoted collection: corpus version + retrieval config, re-read when the files change.

`python -m rag promote` switches the Qdrant alias atomically (queries follow immediately) and rewrites
manifests/active.json; a running API picks up the new corpus_version and retrieval config within
`min_interval_s` without a restart.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path

from rag.manifest import ActivePointer, read_active
from rag.paths import DataPaths
from rag.retrieval_config import RetrievalConfig, load_retrieval_config


def _mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


class ActiveState:
    def __init__(
        self, paths: DataPaths, *, min_interval_s: float = 5.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._paths = paths
        self._interval = min_interval_s
        self._clock = clock
        self._checked = -math.inf
        self._stamp: tuple[int | None, int | None] | None = None
        self._pointer: ActivePointer | None = None
        self._config = RetrievalConfig()

    def _refresh(self) -> None:
        now = self._clock()
        if now - self._checked < self._interval:
            return
        self._checked = now
        pointer = read_active(self._paths) if self._paths.active_pointer.exists() else None
        collection = pointer.collection if pointer else None
        cfg_path = self._paths.retrieval_config_file(collection) if collection else None
        stamp = (_mtime(self._paths.active_pointer), _mtime(cfg_path) if cfg_path else None)
        if stamp == self._stamp:
            return
        self._stamp = stamp
        self._pointer = pointer
        self._config = load_retrieval_config(self._paths, collection)

    def pointer(self) -> ActivePointer | None:
        self._refresh()
        return self._pointer

    def corpus_version(self) -> str:
        pointer = self.pointer()
        return pointer.corpus_version if pointer else ""

    def config(self) -> RetrievalConfig:
        self._refresh()
        return self._config
