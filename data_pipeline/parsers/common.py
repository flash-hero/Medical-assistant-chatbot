"""Helpers shared by all source parsers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime

from core.schemas.document import Document, Section
from core.schemas.source import ContentType, Language, SourceRecord

MetadataValue = str | int | float | bool | list[str]
_DOC_ID_NATIVE = re.compile(r"[^A-Za-z0-9._\-:/]+")


def make_native_id(raw: str) -> str:
    """Make a string safe for the {source_id}:{native_id} doc_id pattern."""
    cleaned = _DOC_ID_NATIVE.sub("-", raw.strip()).strip("-")
    if not cleaned:
        raise ValueError("empty native id")
    return cleaned


def unique_strings(values: Iterable[str], *, exclude: Iterable[str] = ()) -> tuple[str, ...]:
    """Case-insensitive de-duplication that keeps first spelling and order."""
    banned = {e.casefold() for e in exclude}
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = " ".join(value.split())
        key = text.casefold()
        if text and key not in seen and key not in banned:
            seen.add(key)
            out.append(text)
    return tuple(out)


def clean_metadata(raw: dict[str, MetadataValue | None]) -> dict[str, MetadataValue]:
    """Drop None / empty values so Document.metadata stays small and JSON-friendly."""
    out: dict[str, MetadataValue] = {}
    for key, value in raw.items():
        if value is None or value == "" or value == []:
            continue
        out[key] = value
    return out


def parse_us_date(text: str | None) -> date | None:
    """MM/DD/YYYY (MedlinePlus style) or ISO YYYY-MM-DD[...]; None when absent or malformed."""
    if not text:
        return None
    stripped = text.strip()
    for fmt, candidate in (("%m/%d/%Y", stripped), ("%Y-%m-%d", stripped[:10]), ("%Y%m%d", stripped)):
        try:
            return datetime.strptime(candidate, fmt).date()  # noqa: DTZ007 - calendar dates carry no zone
        except ValueError:
            continue
    return None


def build_document(
    record: SourceRecord,
    *,
    native_id: str,
    url: str,
    title: str,
    language: Language,
    content_type: ContentType,
    sections: Sequence[Section],
    retrieved_at: datetime,
    synonyms: Iterable[str] = (),
    published_on: date | None = None,
    reviewed_on: date | None = None,
    metadata: dict[str, MetadataValue | None] | None = None,
    audience: str = "patient",
) -> Document:
    """Build a Document with licence/trust fields copied from the registry record and a checksum."""
    clean_title = " ".join(title.split())
    return Document(
        doc_id=f"{record.id}:{make_native_id(native_id)}",
        source_id=record.id,
        url=url,  # type: ignore[arg-type]
        title=clean_title,
        language=language,
        content_type=content_type,
        audience=audience,
        trust_tier=record.trust_tier,
        reuse_mode=record.reuse_mode,
        license_id=record.license.id,
        attribution=record.license.attribution,
        published_on=published_on,
        reviewed_on=reviewed_on,
        retrieved_at=retrieved_at,
        sections=tuple(sections),
        synonyms=unique_strings(synonyms, exclude=[clean_title]),
        metadata=clean_metadata(metadata or {}),
    ).with_checksum()
