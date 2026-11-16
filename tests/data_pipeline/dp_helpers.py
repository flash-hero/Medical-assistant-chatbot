"""Shared builders for the data_pipeline tests (imported as `dp_helpers`)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from core.schemas.document import Document, Section
from core.schemas.source import SourceRecord
from data_pipeline.fetch.manifest import Manifest, ManifestEntry
from data_pipeline.fetch.naming import url_to_relpath
from data_pipeline.paths import DataPaths


def make_record(source_id: str = "src_a", **overrides: object) -> SourceRecord:
    base: dict[str, object] = {
        "id": source_id,
        "name": "Source A",
        "publisher": "Pub",
        "homepage": "https://a.example.org/",
        "status": "active",
        "wave": 1,
        "trust_tier": 1,
        "reuse_mode": "paraphrase_ok",
        "languages": ["en"],
        "content_types": ["condition"],
        "domains": ["a.example.org"],
        "license": {
            "id": "pd",
            "name": "Public domain",
            "evidence_url": "https://a.example.org/terms",
            "commercial_use": "yes",
            "attribution": "Source: A",
            "conditions": ["credit A"],
            "verified_on": "2026-11-15",
            "verified_by": "data-agent",
        },
    }
    base.update(overrides)
    return SourceRecord.model_validate(base)


LONG_EN = (
    "Diabetes is a chronic condition that affects how your body turns food into energy. "
    "Most of the food you eat is broken down into sugar and released into your bloodstream. "
    "When your blood sugar goes up, it signals your pancreas to release insulin. "
    "People with diabetes should talk with their doctor about the best care plan for them."
)


def make_doc(
    record: SourceRecord,
    native: str = "1",
    *,
    title: str = "Diabetes",
    text: str = LONG_EN,
    url: str | None = None,
    language: str = "en",
    **overrides: object,
) -> Document:
    base: dict[str, object] = {
        "doc_id": f"{record.id}:{native}",
        "source_id": record.id,
        "url": url or f"https://a.example.org/{native}",
        "title": title,
        "language": language,
        "content_type": "condition",
        "trust_tier": record.trust_tier,
        "reuse_mode": record.reuse_mode,
        "license_id": record.license.id,
        "attribution": record.license.attribution,
        "retrieved_at": datetime(2026, 11, 15, tzinfo=UTC),
        "sections": (Section(section_id="s0", heading_path=(title,), text=text, kind="summary"),),
    }
    base.update(overrides)
    return Document.model_validate(base).with_checksum()


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def put_raw(
    paths: DataPaths,
    source_id: str,
    url: str,
    content: bytes | str,
    *,
    content_type: str = "text/html; charset=utf-8",
    status: int = 200,
    final_url: str = "",
    fetched_at: str = "2026-11-15T10:00:00+00:00",
) -> Path:
    """Place raw bytes where the fetcher would have stored them and record the manifest entry."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    rel = url_to_relpath(url)
    target = paths.raw_dir(source_id) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    Manifest(paths.raw_dir(source_id) / "_manifest.jsonl").append(
        ManifestEntry(
            url=url,
            status=status,
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
            fetched_at=fetched_at,
            final_url=final_url or url,
            path=rel,
            content_type=content_type,
        )
    )
    return target
