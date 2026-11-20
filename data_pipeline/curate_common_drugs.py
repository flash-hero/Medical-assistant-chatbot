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
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.config import get_settings
from data_pipeline.drug_synonyms import SYNONYMS_PATH

# Trailing salt / ester words that do not change the medicine ("escitalopram oxalate" is escitalopram).
SALT_WORDS = frozenset(
    [
        "acetate",
        "alafenamide",
        "besylate",
        "bitartrate",
        "calcium",
        "cilexetil",
        "citrate",
        "dihydrate",
        "dihydrochloride",
        "disoproxil",
        "erbumine",
        "etexilate",
        "fumarate",
        "hcl",
        "hyclate",
        "hydrobromide",
        "hydrochloride",
        "magnesium",
        "maleate",
        "medoxomil",
        "mesylate",
        "monohydrate",
        "oxalate",
        "phosphate",
        "potassium",
        "proxetil",
        "sodium",
        "succinate",
        "sulfate",
        "tartrate",
        "tromethamine",
        "xinafoate",
    ]
)
# Names that ARE the salt's cation: never strip ("calcium carbonate" must not become "calcium").
CATIONS = frozenset(
    {
        "aluminium",
        "aluminum",
        "calcium",
        "ferrous",
        "iron",
        "lithium",
        "magnesium",
        "potassium",
        "sodium",
        "zinc",
    }
)
ALIASES = {"ethinylestradiol": "ethinyl estradiol"}
_LIST_SEPARATOR = re.compile(r"\s+and\s+|\s*\+\s*|\s*/\s*")


def _base_name(part: str) -> str:
    tokens = ALIASES.get(part, part).split()
    if not tokens or tokens[0] in CATIONS:
        return " ".join(tokens)
    end = len(tokens)
    while end > 1 and tokens[end - 1] in SALT_WORDS:
        end -= 1
    return " ".join(tokens[:end])


def signature(ingredients: str) -> tuple[str, ...]:
    """Order- and salt-insensitive identity of an ingredient list ("a and b salt" == "b + a")."""
    parts = (p.strip() for p in _LIST_SEPARATOR.split(ingredients.strip().lower()))
    return tuple(sorted(_base_name(p) for p in parts if p))


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
    """One label per medicine: an exact ingredient_key match wins, else the first salt- and
    order-insensitive match."""
    by_signature = {signature(k): name for k, name in keys.items()}
    exact: dict[str, str] = {}
    loose: dict[str, str] = {}
    for doc in labels:
        metadata = doc.get("metadata") or {}
        key = str(metadata.get("ingredient_key", "") if isinstance(metadata, Mapping) else "").strip().lower()
        if not key:
            continue
        if (name := keys.get(key)) is not None:
            exact.setdefault(name, str(doc["doc_id"]))
        elif (name := by_signature.get(signature(key))) is not None:
            loose.setdefault(name, str(doc["doc_id"]))
    by_name = {**loose, **exact}
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
