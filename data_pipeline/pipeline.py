"""Gate a stream of parsed Documents and write the source's corpus files atomically.

Writes (all atomic):
  normalized/{source}.jsonl           kept documents, one per line
  normalized/_ready/{source}.json     completion marker for the RAG track (only after a successful build)
  quarantine/{source}.jsonl           injection / smuggling hits with reasons and the offending document
  reports/{source}_dropped.jsonl      excluded / licence / too-short / wrong-language / duplicate records
  reports/{source}_build.json         counts
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import structlog

from core.schemas.document import Document
from core.schemas.source import SourceRecord
from data_pipeline.paths import DataPaths
from data_pipeline.quality.boilerplate import RepeatedLineFilter
from data_pipeline.quality.dedup import find_duplicates
from data_pipeline.quality.gates import DEFAULT_MIN_CHARS, GateOutcome, check_document
from data_pipeline.registry import assert_indexable
from data_pipeline.storage import atomic_write_text, write_documents_jsonl, write_jsonl, write_ready_marker

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BuildReport:
    source_id: str
    parsed: int
    kept: int
    quarantined: int
    dropped: int
    duplicates_removed: int
    sections: int
    text_bytes: int
    drop_reasons: dict[str, int] = field(default_factory=dict)
    sha256_of_jsonl: str = ""
    finished_at: str = ""


def _quarantine_line(outcome: GateOutcome) -> str:
    doc = outcome.document
    assert doc is not None
    return json.dumps(
        {
            "doc_id": doc.doc_id,
            "source_id": doc.source_id,
            "url": str(doc.url),
            "reasons": list(outcome.reasons),
            "hits": [{"pattern": h.pattern_id, "snippet": h.snippet} for h in outcome.hits],
            "quarantined_at": datetime.now(UTC).isoformat(),
            "document": json.loads(doc.model_dump_json()),
        },
        ensure_ascii=False,
    )


def _dropped_line(doc_id: str, url: str, reasons: Iterable[str]) -> str:
    return json.dumps({"doc_id": doc_id, "url": url, "reasons": list(reasons)}, ensure_ascii=False)


def build_corpus(
    record: SourceRecord,
    documents: Iterable[Document],
    paths: DataPaths,
    *,
    min_chars: int = DEFAULT_MIN_CHARS,
    check_language: bool = True,
    strip_repeated_lines: bool = False,
    write_marker: bool = True,
) -> BuildReport:
    """Apply every gate, de-duplicate, then write the corpus files for one source."""
    assert_indexable(record.id, [record])
    paths.ensure()
    kept: list[Document] = []
    quarantined: list[GateOutcome] = []
    dropped_lines: list[str] = []
    reasons: Counter[str] = Counter()
    parsed = 0
    seen_ids: set[str] = set()
    for doc in documents:
        parsed += 1
        if doc.doc_id in seen_ids:
            dropped_lines.append(_dropped_line(doc.doc_id, str(doc.url), ["duplicate_doc_id"]))
            reasons["duplicate_doc_id"] += 1
            continue
        seen_ids.add(doc.doc_id)
        outcome = check_document(doc, record, min_chars=min_chars, check_language=check_language)
        if outcome.verdict == "keep" and outcome.document is not None:
            kept.append(outcome.document)
        elif outcome.verdict == "quarantine":
            quarantined.append(outcome)
            reasons["quarantined"] += 1
        else:
            dropped_lines.append(_dropped_line(doc.doc_id, str(doc.url), outcome.reasons))
            reasons[outcome.reasons[0].split(":")[0]] += 1
    if strip_repeated_lines and kept:
        kept = _strip_repeated(kept, record, min_chars, dropped_lines, reasons)
    dup_ids, groups = find_duplicates(kept)
    for group in groups:
        for dropped_id in group.dropped:
            dropped_lines.append(_dropped_line(dropped_id, "", [f"{group.kind}_duplicate_of:{group.kept}"]))
            reasons[f"{group.kind}_duplicate"] += 1
    final = [d for d in kept if d.doc_id not in dup_ids]
    return _write_outputs(
        record, paths, final, quarantined, dropped_lines, reasons, parsed, len(dup_ids), write_marker
    )


def _strip_repeated(
    docs: list[Document],
    record: SourceRecord,
    min_chars: int,
    dropped_lines: list[str],
    reasons: Counter[str],
) -> list[Document]:
    line_filter = RepeatedLineFilter.fit(docs)
    out: list[Document] = []
    for doc in docs:
        cleaned = line_filter.apply(doc)
        if cleaned is None or sum(len(s.text) for s in cleaned.sections) < min_chars:
            dropped_lines.append(_dropped_line(doc.doc_id, str(doc.url), ["too_short_after_boilerplate"]))
            reasons["too_short_after_boilerplate"] += 1
        else:
            out.append(cleaned.with_checksum())
    return out


def _write_outputs(
    record: SourceRecord,
    paths: DataPaths,
    final: list[Document],
    quarantined: list[GateOutcome],
    dropped_lines: list[str],
    reasons: Counter[str],
    parsed: int,
    duplicates: int,
    write_marker: bool,
) -> BuildReport:
    count, digest = write_documents_jsonl(paths.normalized_file(record.id), final)
    write_jsonl(paths.quarantine_file(record.id), (_quarantine_line(q) for q in quarantined))
    write_jsonl(paths.reports / f"{record.id}_dropped.jsonl", dropped_lines)
    report = BuildReport(
        source_id=record.id,
        parsed=parsed,
        kept=count,
        quarantined=len(quarantined),
        dropped=len(dropped_lines),
        duplicates_removed=duplicates,
        sections=sum(len(d.sections) for d in final),
        text_bytes=sum(len(s.text.encode("utf-8")) for d in final for s in d.sections),
        drop_reasons=dict(reasons),
        sha256_of_jsonl=digest,
        finished_at=datetime.now(UTC).isoformat(),
    )
    atomic_write_text(paths.reports / f"{record.id}_build.json", json.dumps(asdict(report), indent=2) + "\n")
    if write_marker:
        write_ready_marker(
            paths.ready_file(record.id), source_id=record.id, documents=count, sha256_of_jsonl=digest
        )
    log.info("corpus_built", source=record.id, parsed=parsed, kept=count, quarantined=len(quarantined))
    return report
