"""Human-audit artefacts: the stratified 200-document sample and the generated ATTRIBUTION.md.

Both are pure renderers over already-normalised documents and the ACTIVE registry entries; the human
`data.manual_audit_clean` measurement happens later and is reported as not_run by this track.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core.schemas.document import Document
from core.schemas.source import SourceRecord, SourceStatus
from core.text import sanitize
from data_pipeline.quality.gates import licence_problems
from data_pipeline.quality.injection import scan_document
from data_pipeline.quality.language import detect_language
from data_pipeline.registry import is_excluded_url

AUDIT_SEED = 20261115
PREVIEW_CHARS = 300
_MD_ESCAPE = re.compile(r"([\\`*_{}\[\]<>#|])")


@dataclass(frozen=True)
class AuditRow:
    document: Document
    checks: Mapping[str, bool]

    @property
    def clean(self) -> bool:
        return all(self.checks.values())


def automated_checks(doc: Document, record: SourceRecord | None) -> dict[str, bool]:
    """The per-document checks shown next to each audit-sample entry."""
    body = "\n".join(section.text for section in doc.sections)
    detected = detect_language(body)
    return {
        "licence_verified": record is not None and not licence_problems(doc, record),
        "not_excluded_url": not is_excluded_url(str(doc.url)),
        "text_sanitised": sanitize(body).text == body,
        "no_injection_patterns": not scan_document(doc),
        "language_matches": detected in ("unknown", doc.language.value),
        "has_title_and_url": bool(doc.title.strip()) and bool(str(doc.url)),
    }


def stratified_quotas(counts: Mapping[str, int], size: int) -> dict[str, int]:
    """Documents to draw per source: proportional to its size, at least one per non-empty source, total <= size."""
    pools = {source: n for source, n in counts.items() if n > 0}
    total = sum(pools.values())
    if not pools or size <= 0:
        return {}
    quotas = {source: min(n, max(1, math.floor(size * n / total))) for source, n in pools.items()}
    order = sorted(pools, key=lambda s: (-pools[s], s))
    while sum(quotas.values()) > size:
        trimmable = [s for s in order if quotas[s] > 1]
        if not trimmable:
            break
        quotas[trimmable[0]] -= 1
    turn = 0
    while sum(quotas.values()) < min(size, total):
        source = order[turn % len(order)]
        turn += 1
        if quotas[source] < pools[source]:
            quotas[source] += 1
    return quotas


def _md(text: str) -> str:
    return _MD_ESCAPE.sub(r"\\\1", " ".join(text.split()))


def render_audit_markdown(rows: Sequence[AuditRow], *, generated_on: str, corpus_size: int) -> str:
    clean = sum(1 for r in rows if r.clean)
    lines = [
        "# Manual audit sample",
        "",
        f"Generated {generated_on} by `python -m data_pipeline report` (seed {AUDIT_SEED}). "
        f"{len(rows)} documents drawn from {corpus_size:,} normalised documents, stratified by source.",
        "",
        "For each entry the auditor decides whether the text is a clean, correct health-information document "
        "(readable, on topic, no navigation or advertising text, no personal data, no instructions aimed at an AI) "
        "and records the result in the checklist below. The automated checks are a pre-filter, not the audit.",
        f"Automated pre-check: {clean} of {len(rows)} pass all automated checks. "
        "`data.manual_audit_clean` (target 0.97) is **not run** by the data agent.",
        "",
    ]
    for number, row in enumerate(rows, start=1):
        doc = row.document
        preview = _md(" ".join(s.text for s in doc.sections))[:PREVIEW_CHARS]
        failed = [name for name, ok in row.checks.items() if not ok]
        lines += [
            f"## {number}. {_md(doc.title)}",
            "",
            f"- source: `{doc.source_id}` | language: `{doc.language.value}` | audience: `{doc.audience}` | "
            f"licence: `{doc.license_id}` | reuse: `{doc.reuse_mode.value}`",
            f"- URL: {doc.url}",
            f"- doc_id: `{doc.doc_id}` | sections: {len(doc.sections)}",
            f"- automated checks: {'all pass' if not failed else 'FAILED: ' + ', '.join(failed)}",
            f"- first {PREVIEW_CHARS} characters: {preview}",
            "- [ ] auditor: clean / [ ] not clean (reason: ...)",
            "",
        ]
    return "\n".join(lines)


def render_attribution_markdown(records: Sequence[SourceRecord], *, generated_on: str) -> str:
    """ATTRIBUTION.md generated from the ACTIVE registry entries only."""
    active = sorted((r for r in records if r.status is SourceStatus.ACTIVE), key=lambda r: (r.wave, r.id))
    grouped: dict[int, list[SourceRecord]] = defaultdict(list)
    for record in active:
        grouped[record.wave].append(record)
    lines = [
        "# Attribution",
        "",
        f"Generated {generated_on} from the ACTIVE entries of `data_pipeline/sources/registry.yaml`. "
        "Do not edit by hand; change the registry and run `python -m data_pipeline report`.",
        "",
        "Ausculta shows information from the sources below. Each answer cites its source; this page records the "
        "licence evidence and the credit line each publisher asks for. Images and logos are never used.",
        "",
    ]
    for wave in sorted(grouped):
        lines += [f"## Wave {wave}", ""]
        for record in grouped[wave]:
            lic = record.license
            lines += [
                f"### {record.name}",
                "",
                f"- Publisher: {record.publisher}",
                f"- Credit line: {lic.attribution}",
                f"- Licence: {lic.name} (`{lic.id}`); commercial use: {lic.commercial_use.value}",
                f"- Licence evidence: {lic.evidence_url} (verified {lic.verified_on} by {lic.verified_by})",
                f"- Reuse mode: `{record.reuse_mode.value}` | trust tier {record.trust_tier} | languages: "
                f"{', '.join(language.value for language in record.languages)}",
            ]
            lines += [f"- Condition: {condition}" for condition in lic.conditions]
            lines.append("")
    return "\n".join(lines)


def attribution_entries(records: Sequence[SourceRecord]) -> list[dict[str, object]]:
    """Machine-readable credit lines for the web app: one entry per ACTIVE source."""
    active = sorted((r for r in records if r.status is SourceStatus.ACTIVE), key=lambda r: (r.wave, r.id))
    return [
        {
            "id": record.id,
            "name": record.name,
            "publisher": record.publisher,
            "license_name": record.license.name,
            "attribution": record.license.attribution,
            "homepage": str(record.homepage),
            "languages": [language.value for language in record.languages],
        }
        for record in active
    ]


def render_attribution_json(records: Sequence[SourceRecord]) -> str:
    return json.dumps(attribution_entries(records), indent=2, ensure_ascii=False)
