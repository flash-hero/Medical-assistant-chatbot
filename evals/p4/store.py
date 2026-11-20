"""On-disk state of the P4 runs (all under {data_root}/reports):

p4/cache/<suite>/<item id>.json     one ItemResult per finished item (resumable: a cached item is skipped)
p4/archive/<suite>/<id>.<tag>.json  results replaced by a re-run (`run --ids ... --replace`), kept for audit
p4/judge/<suite>/<item id>.json     judge verdicts for the item's final answer (keyed by the answer hash)
p4/ledger.json                      model calls used by every run, cumulative (the free-tier budget)
p4/p4.db                            the app's SQLite file for eval turns (never the dev database)
p4.metrics.json                     metric records for evals/gates.yaml (rewritten from the cache)
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.p4.results import ItemResult

METRICS_FILE = "p4.metrics.json"
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _file_id(item_id: str) -> str:
    return _SAFE_ID.sub("_", item_id)


@dataclass(frozen=True)
class Store:
    reports: Path  # {data_root}/reports

    @property
    def root(self) -> Path:
        return self.reports / "p4"

    @property
    def metrics_path(self) -> Path:
        return self.reports / METRICS_FILE

    @property
    def db_path(self) -> Path:
        return self.root / "p4.db"

    @property
    def log_path(self) -> Path:
        return self.root / "run.log"

    # ---- item results ----------------------------------------------------------------------------
    def item_path(self, suite: str, item_id: str) -> Path:
        return self.root / "cache" / suite / f"{_file_id(item_id)}.json"

    def has(self, suite: str, item_id: str) -> bool:
        return self.item_path(suite, item_id).exists()

    def put(self, result: ItemResult) -> None:
        write_json_atomic(self.item_path(result.item.suite, result.item.id), result.to_dict())

    def archive(self, suite: str, item_id: str, tag: str) -> Path | None:
        """Move a cached result out of the cache (so the item runs again); returns its new path."""
        path = self.item_path(suite, item_id)
        if not path.exists():
            return None
        target = self.root / "archive" / suite / f"{_file_id(item_id)}.{_file_id(tag)}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, target)
        return target

    def get(self, suite: str, item_id: str) -> ItemResult | None:
        path = self.item_path(suite, item_id)
        if not path.exists():
            return None
        return ItemResult.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def results(self, suite: str) -> list[ItemResult]:
        folder = self.root / "cache" / suite
        if not folder.exists():
            return []
        return [
            ItemResult.from_dict(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(folder.glob("*.json"))
        ]

    def all_results(self) -> Iterator[ItemResult]:
        for suite in ("safety", "quality", "dose", "refusal", "latency"):
            yield from self.results(suite)

    # ---- judge verdicts --------------------------------------------------------------------------
    def judge_path(self, suite: str, item_id: str) -> Path:
        return self.root / "judge" / suite / f"{_file_id(item_id)}.json"

    def get_judgement(self, suite: str, item_id: str) -> dict[str, Any] | None:
        path = self.judge_path(suite, item_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None

    def put_judgement(self, suite: str, item_id: str, payload: Mapping[str, Any]) -> None:
        write_json_atomic(self.judge_path(suite, item_id), dict(payload))

    # ---- ledger ----------------------------------------------------------------------------------
    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger.json"

    def ledger(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {"generate": 0, "decide": 0, "retries": 0, "by_model": {}, "runs": []}
        data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def add_calls(self, delta: Mapping[str, Any]) -> dict[str, Any]:
        """Add one item's model calls to the cumulative totals (kept for discarded items too: they used
        quota). `delta` = {"generate": n, "decide": n, "retries": n, "by_model": {"kind:model": n}}."""
        led = self.ledger()
        for key in ("generate", "decide", "retries"):
            led[key] = int(led.get(key, 0)) + int(delta.get(key, 0))
        by_model = dict(led.get("by_model", {}))
        for key, n in dict(delta.get("by_model", {})).items():
            by_model[key] = int(by_model.get(key, 0)) + int(n)
        led["by_model"] = by_model
        led.setdefault("runs", [])
        write_json_atomic(self.ledger_path, led)
        return led

    def add_run(self, summary: Mapping[str, Any]) -> None:
        led = self.ledger()
        led["runs"] = [*list(led.get("runs", [])), dict(summary)]
        write_json_atomic(self.ledger_path, led)

    def write_metrics(self, records: list[dict[str, Any]]) -> Path:
        write_json_atomic(self.metrics_path, records)
        return self.metrics_path
