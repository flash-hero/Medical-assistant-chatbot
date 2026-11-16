"""Per-document quality gates. Order matters: exclusion and licence first, then injection (on the RAW text so
smuggling characters are still visible), then sanitisation, boilerplate, length and language.

Outcome verdicts:
  keep        -> goes to normalized/{source}.jsonl (document is the cleaned copy)
  quarantine  -> goes to quarantine/{source}.jsonl with the reasons (injection / smuggling)
  drop        -> logged in reports/{source}_dropped.jsonl (excluded, licence mismatch, too short, wrong language)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.schemas.document import Document, Section
from core.schemas.source import SourceRecord
from data_pipeline.quality.boilerplate import clean_document
from data_pipeline.quality.fastpath import fast_sanitize as sanitize
from data_pipeline.quality.injection import InjectionHit, scan_document
from data_pipeline.quality.language import detect_language
from data_pipeline.registry import is_excluded_url

DEFAULT_MIN_CHARS = 200
Verdict = Literal["keep", "quarantine", "drop"]


@dataclass(frozen=True)
class GateOutcome:
    verdict: Verdict
    document: Document | None  # cleaned copy for "keep"; the original for the others
    reasons: tuple[str, ...] = ()
    hits: tuple[InjectionHit, ...] = ()


def sanitize_document(doc: Document) -> Document | None:
    """Run core.text.sanitize on every text field. None when nothing readable remains."""
    sections: list[Section] = []
    for section in doc.sections:
        text = sanitize(section.text).text
        if text:
            path = tuple(h for h in (sanitize(p).text for p in section.heading_path) if h)
            sections.append(section.model_copy(update={"text": text, "heading_path": path}))
    title = sanitize(doc.title).text
    if not sections or not title:
        return None
    synonyms = tuple(s for s in (sanitize(x).text for x in doc.synonyms) if s)
    metadata = {k: sanitize(v).text if isinstance(v, str) else v for k, v in doc.metadata.items()}
    return doc.model_copy(
        update={
            "title": title,
            "sections": tuple(sections),
            "synonyms": synonyms,
            "metadata": metadata,
            "attribution": sanitize(doc.attribution).text,
        }
    )


def licence_problems(doc: Document, record: SourceRecord) -> list[str]:
    problems: list[str] = []
    if not record.indexable:
        problems.append(f"source_not_active:{record.status.value}")
    if doc.source_id != record.id:
        problems.append("source_id_mismatch")
    if doc.license_id != record.license.id:
        problems.append("license_id_mismatch")
    if doc.attribution != record.license.attribution:
        problems.append("attribution_mismatch")
    if doc.reuse_mode != record.reuse_mode or doc.trust_tier != record.trust_tier:
        problems.append("reuse_or_trust_mismatch")
    if record.license.verified_on is None or record.license.evidence_url is None:
        problems.append("licence_unverified")
    return problems


def check_document(
    doc: Document, record: SourceRecord, *, min_chars: int = DEFAULT_MIN_CHARS, check_language: bool = True
) -> GateOutcome:
    if is_excluded_url(str(doc.url)):
        return GateOutcome("drop", doc, ("excluded_url",))
    problems = licence_problems(doc, record)
    if problems:
        return GateOutcome("drop", doc, tuple(problems))
    hits = scan_document(doc)  # raw text: smuggling characters are still present here
    if hits:
        return GateOutcome("quarantine", doc, tuple(h.pattern_id for h in hits), tuple(hits))
    cleaned = sanitize_document(doc)
    cleaned = clean_document(cleaned) if cleaned else None
    if cleaned is None:
        return GateOutcome("drop", doc, ("empty_after_cleaning",))
    body = "\n".join(s.text for s in cleaned.sections)
    if len(body) < min_chars:
        return GateOutcome("drop", doc, (f"too_short:{len(body)}",))
    if check_language:
        detected = detect_language(body)
        if detected not in ("unknown", cleaned.language.value):
            return GateOutcome("drop", doc, (f"language_mismatch:{detected}",))
    return GateOutcome("keep", cleaned.with_checksum())
