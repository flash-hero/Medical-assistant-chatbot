"""Drug-name query expansion from data_pipeline/drug_synonyms.yaml (read-only; optional).

The file is produced by the data track, so the loader accepts the shapes it may reasonably take:
  {name: [synonym, ...]}                       mapping of canonical name -> names
  {name: {synonyms: [...], brands: [...]}}     mapping of canonical name -> record
  [{name|inn|canonical: x, synonyms|aliases|brands|names: [...]}, ...]  (optionally under a top key)
Every string found in a record (except bookkeeping keys) joins the group. Matching runs on
core.text.detection_form() n-grams, so case, accents and Arabic letter variants do not matter.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import structlog
import yaml

from core.text import detection_form

log = structlog.get_logger(__name__)

_IGNORED_KEYS = frozenset(
    {
        "id",
        "source",
        "source_id",
        "url",
        "rxcui",
        "unii",
        "notes",
        "license",
        "type",
        "kind",
        "count",
        "updated",
        "review_status",
        "reviewed_by",
        "reviewed_on",
        "status",
        "atc",
        "class",
    }
)
_TOP_KEYS = ("drugs", "synonyms", "entries", "groups", "items")
MAX_NGRAM = 4
MAX_GROUP_NAMES = 8
# Arabic proclitics + definite article ("الباراسيتامول", "بالأسبرين") are stripped when matching.
_AR_ARTICLES = ("وال", "بال", "كال", "فال", "لل", "ال")
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")


def _variants(token: str) -> tuple[str, ...]:
    for prefix in _AR_ARTICLES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 3:
            return (token, token[len(prefix) :])
    return (token,)


def _latin_name(name: str) -> bool:
    """Expansions feed the English BM25 analyser, so only Latin-script names are useful there."""
    return bool(_LATIN.search(name)) and not _ARABIC.search(name)


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, inner in value.items():
            if str(key).lower() not in _IGNORED_KEYS:
                yield from _strings(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _strings(inner)


def _groups(data: Any) -> Iterable[list[str]]:
    if isinstance(data, Mapping):
        top = next((data[k] for k in _TOP_KEYS if k in data and isinstance(data[k], (list, dict))), None)
        if top is not None:
            yield from _groups(top)
            return
        for name, value in data.items():
            yield [str(name), *_strings(value)]
    elif isinstance(data, list):
        for item in data:
            yield list(_strings(item))


@dataclass(frozen=True)
class SynonymIndex:
    groups: tuple[tuple[str, ...], ...] = ()
    lookup: Mapping[str, tuple[int, ...]] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_groups(cls, raw_groups: Iterable[Sequence[str]]) -> SynonymIndex:
        groups: list[tuple[str, ...]] = []
        lookup: dict[str, list[int]] = {}
        for raw in raw_groups:
            names = tuple(dict.fromkeys(n.strip() for n in raw if isinstance(n, str) and len(n.strip()) >= 3))
            if len(names) < 2:
                continue
            gid = len(groups)
            groups.append(names)
            for name in names:
                key = detection_form(name)
                if key and len(key.split()) <= MAX_NGRAM:
                    lookup.setdefault(key, []).append(gid)
        frozen = {k: tuple(v) for k, v in lookup.items()}
        return cls(tuple(groups), MappingProxyType(frozen))

    def __len__(self) -> int:
        return len(self.groups)

    def matched_groups(self, text: str) -> list[int]:
        raw = tuple(detection_form(text).split())
        stripped = tuple(_variants(t)[-1] for t in raw)
        found: list[int] = []
        for tokens in dict.fromkeys((raw, stripped)):  # ordered, deterministic
            for n in range(MAX_NGRAM, 0, -1):
                for i in range(len(tokens) - n + 1):
                    for gid in self.lookup.get(" ".join(tokens[i : i + n]), ()):
                        if gid not in found:
                            found.append(gid)
        return found

    def expansions(self, texts: Sequence[str], *, max_groups: int = 3) -> tuple[str, ...]:
        """One extra English lexical query per matched drug: its other Latin-script names
        (paracetamol -> acetaminophen Tylenol ...; باراسيتامول -> paracetamol acetaminophen ...)."""
        joined = " ".join(texts)
        present = set(detection_form(joined).split())
        out: list[str] = []
        for gid in self.matched_groups(joined)[:max_groups]:
            others: dict[str, str] = {}  # detection form -> first spelling (paracetamol == paracétamol)
            for name in self.groups[gid]:
                folded = detection_form(name)
                if _latin_name(name) and not set(folded.split()) <= present:
                    others.setdefault(folded, name)
            if others:
                out.append(" ".join(list(others.values())[:MAX_GROUP_NAMES]))
        return tuple(out)


def load_synonyms(path: Path) -> SynonymIndex:
    if not path.exists():
        return SynonymIndex()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("drug_synonyms_unreadable", path=str(path), error=type(exc).__name__)
        return SynonymIndex()
    index = SynonymIndex.from_groups(_groups(data))
    log.info("drug_synonyms_loaded", groups=len(index))
    return index
