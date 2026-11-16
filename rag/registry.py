"""Read-only view of data_pipeline/sources/registry.yaml (loaded with yaml + SourceRecord).

Deliberately independent of data_pipeline code: the RAG track only needs the indexing policy, and the
registry file is the contract. A record that fails validation is treated as NOT indexable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

import structlog
import yaml
from pydantic import ValidationError

from core.schemas.document import Document
from core.schemas.source import Language, ReuseMode, SourceRecord, SourceStatus
from rag.errors import SourceNotIndexable
from rag.paths import REGISTRY_PATH

log = structlog.get_logger(__name__)

INDEXED_LANGUAGES: frozenset[Language] = frozenset({Language.EN, Language.FR, Language.AR})


class _Yaml12Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false are booleans. YAML 1.1 would turn the registry's
    unquoted `commercial_use: yes` into True and fail validation (data_pipeline coerces it the same way)."""


_Yaml12Loader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


@dataclass(frozen=True)
class DomainRule:
    """'medlineplus.gov/ency/' -> host medlineplus.gov (and subdomains), path prefix /ency/."""

    host: str
    path_prefix: str = ""

    @classmethod
    def parse(cls, entry: str) -> DomainRule:
        cleaned = entry.strip().lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")
        host, _, rest = cleaned.partition("/")
        return cls(host=host, path_prefix=f"/{rest}" if rest else "")

    def matches(self, url: str) -> bool:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().removeprefix("www.")
        path = (parts.path or "/").lower()
        host_ok = host == self.host or host.endswith(f".{self.host}")
        return host_ok and (not self.path_prefix or path.startswith(self.path_prefix))


@dataclass(frozen=True)
class Registry:
    records: Mapping[str, SourceRecord]
    invalid: Mapping[str, str]  # source id -> validation error summary

    def require_indexable(self, source_id: str) -> SourceRecord:
        record = self.records.get(source_id)
        if record is None:
            reason = self.invalid.get(source_id, "not listed in the registry")
            raise SourceNotIndexable(f"source {source_id!r} cannot be indexed: {reason}")
        if record.status is not SourceStatus.ACTIVE:
            raise SourceNotIndexable(f"source {source_id!r} has status {record.status.value}, not active")
        return record

    @cached_property
    def excluded_rules(self) -> tuple[DomainRule, ...]:
        return tuple(
            DomainRule.parse(d)
            for r in self.records.values()
            if r.status is SourceStatus.EXCLUDED
            for d in r.domains
        )

    def refusal_reason(self, doc: Document, source_id: str) -> str | None:
        """Why this document must not be indexed under `source_id` (None = indexable)."""
        record = self.records.get(doc.source_id)
        if doc.source_id != source_id:
            return "source_mismatch"
        if record is None or record.status is not SourceStatus.ACTIVE:
            return "source_not_active"
        if doc.reuse_mode is ReuseMode.LINK_ONLY:
            return "link_only"
        if doc.language not in INDEXED_LANGUAGES:
            return "language_not_indexed"
        if any(rule.matches(str(doc.url)) for rule in self.excluded_rules):
            return "excluded_domain"
        return None


def _summary(exc: ValidationError) -> str:
    return "; ".join(str(e.get("msg", "")) for e in exc.errors())[:300]


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_Yaml12Loader) or {}  # noqa: S506
    entries = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise SourceNotIndexable(f"registry {path} has no 'sources' list")
    records: dict[str, SourceRecord] = {}
    invalid: dict[str, str] = {}
    for entry in entries:
        sid = str(entry.get("id", "?")) if isinstance(entry, dict) else "?"
        try:
            record = SourceRecord.model_validate(entry)
        except ValidationError as exc:
            invalid[sid] = f"invalid registry record: {_summary(exc)}"
            log.warning("registry_record_invalid", source_id=sid)
            continue
        records[record.id] = record
    return Registry(records=MappingProxyType(records), invalid=MappingProxyType(invalid))
