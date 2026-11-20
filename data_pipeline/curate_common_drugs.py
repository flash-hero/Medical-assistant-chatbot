"""Select the openFDA labels of common medicines for the v1 index.

The full openFDA set (7,677 labels, one per active-ingredient set) is too large to embed on a laptop CPU, and
most entries are niche OTC products. This picks ONE single-ingredient label per medicine listed in
data_pipeline/drug_synonyms.yaml (matched on the label's normalised `ingredient_key` against the USAN or INN),
and writes their doc ids for `python -m rag build --only-docs openfda_labels=<file>`.

Run: python -m data_pipeline.curate_common_drugs [--out C:/dev/ausculta-data/curated/openfda_common.txt]
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.config import get_settings
from data_pipeline.drug_synonyms import SYNONYMS_PATH


@dataclass(frozen=True)
class Selection:
    doc_ids: tuple[str, ...]
    matched: tuple[str, ...]  # medicine names that found a label
    missing: tuple[str, ...]  # medicine names with no single-ingredient label


def wanted_keys(entries: Iterable[Mapping[str, object]]) -> dict[str, str]:
    """ingredient_key -> display name, from USAN (US label naming) and INN spellings."""
    keys: dict[str, str] = {}
    for entry in entries:
        inn = str(entry.get("inn", "")).strip().lower()
        usan = str(entry.get("usan", "") or "").strip().lower()
        for key in filter(None, (usan, inn)):
            keys.setdefault(key, usan or inn)
    return keys


def select(labels: Iterable[Mapping[str, object]], keys: Mapping[str, str]) -> Selection:
    by_name: dict[str, str] = {}
    for doc in labels:
        metadata = doc.get("metadata") or {}
        key = str(metadata.get("ingredient_key", "") if isinstance(metadata, Mapping) else "").strip().lower()
        name = keys.get(key)
        if name is not None and name not in by_name:
            by_name[name] = str(doc["doc_id"])
    names = sorted(set(keys.values()))
    return Selection(
        doc_ids=tuple(by_name[n] for n in sorted(by_name)),
        matched=tuple(sorted(by_name)),
        missing=tuple(n for n in names if n not in by_name),
    )


def _iter_labels(path: Path) -> Iterable[dict[str, object]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main(argv: list[str] | None = None) -> int:
    root = get_settings().data_root
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--labels", type=Path, default=root / "normalized" / "openfda_labels.jsonl")
    parser.add_argument("--out", type=Path, default=root / "curated" / "openfda_common.txt")
    args = parser.parse_args(argv)
    entries = yaml.safe_load(SYNONYMS_PATH.read_text(encoding="utf-8"))["entries"]
    result = select(_iter_labels(args.labels), wanted_keys(entries))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text("".join(f"{d}\n" for d in result.doc_ids), encoding="utf-8")
    tmp.replace(args.out)
    print(f"selected {len(result.doc_ids)} labels for {len(result.matched)} medicines -> {args.out}")
    print(f"no single-ingredient US label for {len(result.missing)}: {', '.join(result.missing[:40])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
