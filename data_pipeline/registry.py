"""Load and validate data_pipeline/sources/registry.yaml.

`domains` entries may be a bare host ("mayoclinic.org", which also covers sub-domains) or a host plus a path
prefix ("medlineplus.gov/ency/"), which is how excluded content that lives inside an otherwise usable site
(A.D.A.M. encyclopedia, ASHP drug monographs) is refused.

CLI:  python -m data_pipeline.registry --check      (exit 1 on any violation)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import ValidationError

from core.schemas.source import CommercialUse, ReuseMode, SourceRecord, SourceStatus
from data_pipeline.paths import REGISTRY_PATH


class RegistryError(Exception):
    """The registry file is unreadable or a record is invalid."""


class SourceNotIndexableError(Exception):
    """A document or fetch referenced a source that may not be used."""


@dataclass(frozen=True)
class DomainRule:
    host: str
    path_prefix: str  # "" matches the whole host

    def matches(self, host: str, path: str) -> bool:
        host_ok = host == self.host or host.endswith("." + self.host)
        return host_ok and (not self.path_prefix or path.startswith(self.path_prefix))


def parse_domain_rule(entry: str) -> DomainRule:
    cleaned = entry.strip().lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")
    host, _, rest = cleaned.partition("/")
    return DomainRule(host=host, path_prefix=("/" + rest) if rest else "")


def _normalise_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    return host, (parts.path or "/").lower()


def _coerce_yaml_booleans(item: object) -> object:
    """YAML 1.1 reads an unquoted `yes`/`no` as a boolean; the licence enum wants the strings."""
    if not isinstance(item, dict):
        return item
    lic = item.get("license")
    if isinstance(lic, dict) and isinstance(lic.get("commercial_use"), bool):
        lic = {**lic, "commercial_use": "yes" if lic["commercial_use"] else "no"}
        return {**item, "license": lic}
    return item


def load_registry(path: Path | None = None) -> tuple[SourceRecord, ...]:
    registry_path = path or REGISTRY_PATH
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"cannot read registry {registry_path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        raise RegistryError("registry must be a mapping with a 'sources' list")
    records: list[SourceRecord] = []
    for index, item in enumerate(raw["sources"]):
        try:
            records.append(SourceRecord.model_validate(_coerce_yaml_booleans(item)))
        except ValidationError as exc:
            label = item.get("id", f"#{index}") if isinstance(item, dict) else f"#{index}"
            raise RegistryError(f"invalid source {label}: {exc}") from exc
    return tuple(records)


@lru_cache(maxsize=1)
def _default_registry() -> tuple[SourceRecord, ...]:
    return load_registry()


def reload_default_registry() -> tuple[SourceRecord, ...]:
    _default_registry.cache_clear()
    return _default_registry()


def _records(records: Sequence[SourceRecord] | None) -> Sequence[SourceRecord]:
    return _default_registry() if records is None else records


def get_source(source_id: str, records: Sequence[SourceRecord] | None = None) -> SourceRecord | None:
    return next((r for r in _records(records) if r.id == source_id), None)


def is_indexable(source_id: str, records: Sequence[SourceRecord] | None = None) -> bool:
    record = get_source(source_id, records)
    return bool(record and record.indexable)


def assert_indexable(source_id: str, records: Sequence[SourceRecord] | None = None) -> SourceRecord:
    record = get_source(source_id, records)
    if record is None:
        raise SourceNotIndexableError(f"source {source_id!r} is not in the registry")
    if not record.indexable:
        raise SourceNotIndexableError(f"source {source_id!r} has status {record.status.value}, not active")
    return record


def excluded_rules(records: Sequence[SourceRecord] | None = None) -> tuple[tuple[str, DomainRule], ...]:
    return tuple(
        (r.id, parse_domain_rule(d))
        for r in _records(records)
        if r.status is SourceStatus.EXCLUDED
        for d in r.domains
    )


def excluded_source_for_url(url: str, records: Sequence[SourceRecord] | None = None) -> str | None:
    """Return the id of the excluded source whose host/path rule matches the URL, else None."""
    host, path = _normalise_url(url)
    for source_id, rule in excluded_rules(records):
        if rule.matches(host, path):
            return source_id
    return None


def is_excluded_url(url: str, records: Sequence[SourceRecord] | None = None) -> bool:
    return excluded_source_for_url(url, records) is not None


def url_belongs_to_source(url: str, record: SourceRecord) -> bool:
    """True when the URL host is one of the source's declared domains (unrestricted if none declared)."""
    if not record.domains:
        return True
    host, path = _normalise_url(url)
    return any(parse_domain_rule(d).matches(host, path) for d in record.domains)


def _check_dates(record: SourceRecord, today: date) -> Iterable[str]:
    verified = record.license.verified_on
    if verified and verified > today:
        yield f"{record.id}: licence verified_on {verified} is in the future"


def _check_active(record: SourceRecord) -> Iterable[str]:
    lic = record.license
    if record.status is not SourceStatus.ACTIVE:
        return
    if not lic.attribution.strip():
        yield f"{record.id}: ACTIVE source has an empty attribution line"
    if not record.domains:
        yield f"{record.id}: ACTIVE source declares no domains (needed for the host check)"
    if lic.commercial_use not in (CommercialUse.YES, CommercialUse.CONDITIONAL):
        yield f"{record.id}: ACTIVE source with commercial_use={lic.commercial_use.value}"
    if lic.evidence_url is None or lic.verified_on is None or not lic.verified_by:
        yield f"{record.id}: ACTIVE source lacks a verified licence record"
    if record.reuse_mode is ReuseMode.LINK_ONLY:
        yield f"{record.id}: ACTIVE source with reuse_mode=link_only"


def _check_excluded(record: SourceRecord) -> Iterable[str]:
    if record.status is not SourceStatus.EXCLUDED:
        return
    if not record.domains and "path" not in record.notes.lower():
        yield f"{record.id}: EXCLUDED source declares no domains or path patterns"
    if record.reuse_mode is not ReuseMode.LINK_ONLY:
        yield f"{record.id}: EXCLUDED source must use reuse_mode=link_only"


def _check_domain_conflicts(records: Sequence[SourceRecord]) -> Iterable[str]:
    rules = excluded_rules(records)
    for record in records:
        if record.status is not SourceStatus.ACTIVE:
            continue
        for domain in record.domains:
            active_rule = parse_domain_rule(domain)
            for excluded_id, rule in rules:
                if active_rule.host == rule.host and not rule.path_prefix:
                    yield f"{record.id}: active domain {domain} is excluded by {excluded_id}"


def check_records(records: Sequence[SourceRecord], *, today: date | None = None) -> list[str]:
    """Return every violation found (an empty list means the registry is valid)."""
    today = today or date.today()
    problems: list[str] = []
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            problems.append(f"{record.id}: duplicate source id")
        seen.add(record.id)
        problems.extend(_check_dates(record, today))
        problems.extend(_check_active(record))
        problems.extend(_check_excluded(record))
    problems.extend(_check_domain_conflicts(records))
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m data_pipeline.registry")
    parser.add_argument("--check", action="store_true", help="validate the registry; exit 1 on violations")
    parser.add_argument("--path", type=Path, default=None, help="registry file (default: bundled)")
    args = parser.parse_args(argv)
    try:
        records = load_registry(args.path)
    except RegistryError as exc:
        sys.stderr.write(f"REGISTRY INVALID: {exc}\n")
        return 1
    problems = check_records(records)
    for problem in problems:
        sys.stderr.write(f"VIOLATION: {problem}\n")
    active = sum(1 for r in records if r.status is SourceStatus.ACTIVE)
    sys.stdout.write(f"registry: {len(records)} sources, {active} active, {len(problems)} violations\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
