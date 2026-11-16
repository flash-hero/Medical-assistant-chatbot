"""Load and query data_pipeline/drug_synonyms.yaml (INN <-> USAN <-> brand, French DCI, Arabic names).

Used by RAG for cross-lingual query expansion. Entries stay `review_status: unverified` until a pharmacist signs
them off; consumers should treat them as retrieval aliases only, never as clinical statements.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.text import detection_form

SYNONYMS_PATH = Path(__file__).resolve().parent / "drug_synonyms.yaml"


class DrugSynonymError(Exception):
    """The synonyms file is unreadable or invalid."""


class DrugEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inn: str = Field(min_length=2)
    usan: str | None = None
    fr: str = Field(min_length=2)
    ar: tuple[str, ...] = Field(min_length=1)
    brands: tuple[str, ...] = ()
    review_status: Literal["unverified", "reviewed"] = "unverified"

    def all_names(self) -> tuple[str, ...]:
        """Every name for this medicine, deduplicated on the matching form, in a stable order."""
        names = [self.inn, *([self.usan] if self.usan else []), self.fr, *self.ar, *self.brands]
        seen: set[str] = set()
        out: list[str] = []
        for name in names:
            key = detection_form(name)
            if key and key not in seen:
                seen.add(key)
                out.append(name)
        return tuple(out)


def load_entries(path: Path | None = None) -> tuple[DrugEntry, ...]:
    target = path or SYNONYMS_PATH
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DrugSynonymError(f"cannot read {target}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        raise DrugSynonymError("drug synonyms file must contain an 'entries' list")
    try:
        entries = tuple(DrugEntry.model_validate(item) for item in raw["entries"])
    except ValidationError as exc:
        raise DrugSynonymError(f"invalid drug synonym entry: {exc}") from exc
    duplicates = _duplicates([e.inn.casefold() for e in entries])
    if duplicates:
        raise DrugSynonymError(f"duplicate INN entries: {sorted(duplicates)}")
    return entries


def _duplicates(values: Sequence[str]) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return repeated


@lru_cache(maxsize=1)
def default_entries() -> tuple[DrugEntry, ...]:
    return load_entries()


def build_index(entries: Sequence[DrugEntry]) -> dict[str, tuple[DrugEntry, ...]]:
    """detection_form(name) -> entries that carry that name (a brand may belong to several)."""
    index: dict[str, list[DrugEntry]] = {}
    for entry in entries:
        for name in entry.all_names():
            index.setdefault(detection_form(name), []).append(entry)
    return {k: tuple(v) for k, v in index.items()}


def expand_term(term: str, entries: Sequence[DrugEntry] | None = None) -> tuple[str, ...]:
    """All known names for the medicine(s) matching `term` (any language); empty when unknown."""
    index = build_index(entries if entries is not None else default_entries())
    matches = index.get(detection_form(term), ())
    names: list[str] = []
    for entry in matches:
        names.extend(n for n in entry.all_names() if n not in names)
    return tuple(names)
