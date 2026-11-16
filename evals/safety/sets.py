"""Safety evaluation sets: loading, validation and the frozen held-out split.

Layout: evals/safety/sets/{lang}/{category}.jsonl, one JSON object per line:
  {"id", "lang", "text", "history"?, "expected_kinds", "notes"}
Arabic ids carry the variety as their third part: ar-emg-{msa|ma|dz|tn|azi}-NN (azi = Arabizi).

The held-out split (20% of every lang x category file, chosen by SHA-256 of the id) is frozen in
sets/splits.json. Lexicon tuning only ever looks at failures of the "tune" split; held-out numbers are
reported, never inspected item by item while tuning.

  python -m evals.safety.sets --make-splits   # writes splits.json (refuses to overwrite without --force)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.schemas.chat import RiskKind

SETS_DIR = Path(__file__).resolve().parent / "sets"
SPLITS_FILE = "splits.json"
LANGS: tuple[str, ...] = ("en", "fr", "ar")
RISK_CATEGORIES: tuple[str, ...] = ("emergency", "self_harm", "harm_to_others", "abuse_disclosure")
INJECTION = "injection"
HARD_NEGATIVE = "hard_negative"
CATEGORIES: tuple[str, ...] = (*RISK_CATEGORIES, INJECTION, HARD_NEGATIVE)
KNOWN_KINDS: frozenset[str] = frozenset(k.value for k in RiskKind)
HELDOUT_FRACTION = 0.2
TUNE = "tune"
HELDOUT = "heldout"
_FIELDS = frozenset({"id", "lang", "text", "history", "expected_kinds", "notes"})


class SetFormatError(ValueError):
    """A set file is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class SafetyItem:
    id: str
    lang: str
    category: str
    text: str
    expected_kinds: frozenset[str]
    notes: str = ""
    history: tuple[str, ...] = ()

    @property
    def variety(self) -> str:
        """Arabic variety from the id (msa, ma, dz, tn, azi); the language itself otherwise."""
        parts = self.id.split("-")
        return parts[2] if len(parts) == 4 else self.lang

    @property
    def turns(self) -> tuple[str, ...]:
        """Every user message of the item, oldest first (the engine prechecks each one on arrival)."""
        return (*self.history, self.text)


def _str_list(value: Any, field: str, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise SetFormatError(f"{where}: '{field}' must be a list of non-empty strings")
    return tuple(value)


def _check_category(kinds: frozenset[str], category: str, where: str) -> None:
    if category == HARD_NEGATIVE and kinds:
        raise SetFormatError(f"{where}: hard negatives must have empty expected_kinds")
    if category != HARD_NEGATIVE and category not in kinds:
        raise SetFormatError(f"{where}: expected_kinds must contain {category!r}")


def parse_item(raw: Mapping[str, Any], *, lang: str, category: str, where: str) -> SafetyItem:
    """Validate one decoded JSON object from {lang}/{category}.jsonl."""
    extra = set(raw) - _FIELDS
    if extra:
        raise SetFormatError(f"{where}: unknown fields {sorted(extra)}")
    for key in ("id", "lang", "text"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise SetFormatError(f"{where}: '{key}' must be a non-empty string")
    if raw["lang"] != lang or not raw["id"].startswith(f"{lang}-"):
        raise SetFormatError(f"{where}: lang/id prefix must be {lang!r}")
    raw_kinds = raw.get("expected_kinds")
    if not isinstance(raw_kinds, list) or not all(isinstance(k, str) for k in raw_kinds):
        raise SetFormatError(f"{where}: 'expected_kinds' must be a list of strings")
    kinds = frozenset(raw_kinds)
    unknown = kinds - KNOWN_KINDS
    if unknown:
        raise SetFormatError(f"{where}: unknown kinds {sorted(unknown)}")
    _check_category(kinds, category, where)
    history = _str_list(raw["history"], "history", where) if "history" in raw else ()
    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise SetFormatError(f"{where}: 'notes' must be a string")
    return SafetyItem(raw["id"], lang, category, raw["text"], kinds, notes, history)


def load_file(path: Path, *, lang: str, category: str) -> tuple[SafetyItem, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SetFormatError(f"cannot read {path.name}: {exc.strerror}") from exc
    items: list[SafetyItem] = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        where = f"{lang}/{path.name}:{n}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SetFormatError(f"{where}: invalid JSON ({exc.msg})") from exc
        if not isinstance(raw, dict):
            raise SetFormatError(f"{where}: each line must be a JSON object")
        items.append(parse_item(raw, lang=lang, category=category, where=where))
    return tuple(items)


def load_sets(root: Path = SETS_DIR, langs: Sequence[str] = LANGS) -> tuple[SafetyItem, ...]:
    """Every item of every lang x category file; ids must be unique across all files."""
    items = tuple(
        item
        for lang in langs
        for category in CATEGORIES
        for item in load_file(root / lang / f"{category}.jsonl", lang=lang, category=category)
    )
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise SetFormatError(f"duplicate id {item.id}")
        seen.add(item.id)
    return items


def _rank(item_id: str) -> str:
    return hashlib.sha256(item_id.encode("utf-8")).hexdigest()


def select_heldout(items: Iterable[SafetyItem], fraction: float = HELDOUT_FRACTION) -> frozenset[str]:
    """round(fraction * n) items (at least one) of every lang x category group, by SHA-256 of the id."""
    groups: dict[tuple[str, str], list[str]] = {}
    for item in items:
        groups.setdefault((item.lang, item.category), []).append(item.id)
    chosen: set[str] = set()
    for ids in groups.values():
        k = max(1, round(len(ids) * fraction))
        chosen.update(sorted(ids, key=_rank)[:k])
    return frozenset(chosen)


def load_heldout(root: Path = SETS_DIR) -> frozenset[str]:
    path = root / SPLITS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetFormatError(
            f"cannot load {SPLITS_FILE}; run `python -m evals.safety.sets --make-splits`"
        ) from exc
    ids = raw.get("heldout") if isinstance(raw, dict) else None
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise SetFormatError(f"{SPLITS_FILE}: 'heldout' must be a list of ids")
    return frozenset(ids)


def split_of(item: SafetyItem, heldout: frozenset[str]) -> str:
    return HELDOUT if item.id in heldout else TUNE


def write_json_atomic(path: Path, payload: Any) -> None:
    """UTF-8 JSON via a temp file + os.replace, so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def make_splits(root: Path = SETS_DIR, *, force: bool = False) -> frozenset[str]:
    path = root / SPLITS_FILE
    if path.exists() and not force:
        raise SetFormatError(f"{SPLITS_FILE} already exists; the held-out split is frozen (use --force)")
    heldout = select_heldout(load_sets(root))
    write_json_atomic(
        path,
        {
            "fraction": HELDOUT_FRACTION,
            "method": "per lang x category file: lowest SHA-256(id), round(fraction * n)",
            "heldout": sorted(heldout),
        },
    )
    return heldout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sets", type=Path, default=SETS_DIR)
    parser.add_argument("--make-splits", action="store_true", help="freeze the held-out split")
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing split (never while tuning)"
    )
    args = parser.parse_args(argv)
    try:
        items = load_sets(args.sets)
        if args.make_splits:
            make_splits(args.sets, force=args.force)
    except SetFormatError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(f"{len(items)} items valid\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
