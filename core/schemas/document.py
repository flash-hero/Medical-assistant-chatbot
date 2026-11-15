"""Normalised corpus contract.

data_pipeline writes  {AUSCULTA_DATA_ROOT}/normalized/{source_id}.jsonl   one Document per line (UTF-8)
rag reads those files, writes chunks to {AUSCULTA_DATA_ROOT}/chunks/{corpus_version}/{source_id}.jsonl
and indexes Chunk payloads into Qdrant.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from core.schemas.source import ContentType, Language, ReuseMode


class Section(BaseModel):
    """A structural unit of a document (heading + its text). Chunking never crosses section boundaries
    except to merge tiny sections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: str  # stable within the document, e.g. "s3" or an SPL section code "34067-9"
    heading_path: tuple[str, ...] = ()  # ("Diabetes", "Symptoms")
    text: str = Field(min_length=1)  # plain text; paragraphs separated by "\n\n"; list items "- "
    kind: str | None = None  # e.g. "indications", "warnings", "summary", "when_to_seek_care"


class Document(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(pattern=r"^[a-z0-9_]+:[A-Za-z0-9._\-:/]+$")  # "{source_id}:{native_id}"
    source_id: str
    url: HttpUrl
    title: str = Field(min_length=1)
    language: Language
    content_type: ContentType
    audience: str = "patient"  # "patient" | "professional"
    trust_tier: int = Field(ge=1, le=3)
    reuse_mode: ReuseMode
    license_id: str
    attribution: str
    published_on: date | None = None
    reviewed_on: date | None = None  # source's own "last reviewed/updated" date
    retrieved_at: datetime
    sections: tuple[Section, ...] = Field(min_length=1)
    synonyms: tuple[str, ...] = ()  # alternative names (incl. INN/USAN/brand for drugs, FR/AR names)
    metadata: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    checksum: str = ""  # sha256 of canonical text; set by `with_checksum()`

    def canonical_text(self) -> str:
        parts = [self.title, *(f"{' > '.join(s.heading_path)}\n{s.text}" for s in self.sections)]
        return "\n\n".join(parts)

    def with_checksum(self) -> Document:
        digest = hashlib.sha256(self.canonical_text().encode("utf-8")).hexdigest()
        return self.model_copy(update={"checksum": digest})


class Chunk(BaseModel):
    """Retrieval unit. `context_header` is prepended to `text` for embedding and BM25 (contextual chunk
    header), but citations show `text` only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str  # f"{doc_id}#{section_id}#{ordinal}"
    doc_id: str
    source_id: str
    section_id: str
    parent_id: str  # f"{doc_id}#{section_id}" -> used for small-to-big expansion
    ordinal: int = Field(ge=0)
    heading_path: tuple[str, ...] = ()
    text: str = Field(min_length=1)
    context_header: str  # "MedlinePlus | Diabetes > Symptoms | en | reviewed 2025-05-01"
    title: str
    url: HttpUrl
    language: Language
    content_type: ContentType
    trust_tier: int = Field(ge=1, le=3)
    reuse_mode: ReuseMode
    attribution: str
    reviewed_on: date | None = None
    section_kind: str | None = None
    token_estimate: int = Field(ge=1)
    checksum: str  # sha256(context_header + "\n" + text)

    def embedding_text(self) -> str:
        """Document-side text for gemini-embedding-2 (prefix format from the model docs)."""
        return f"title: {self.title} | text: {self.context_header}\n{self.text}"

    def lexical_text(self) -> str:
        return f"{self.context_header}\n{self.text}"


class CorpusManifest(BaseModel):
    """Written by rag after a successful index build; exposed by the API as the corpus version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus_version: str  # e.g. "2026-11-15.1"
    collection: str
    embed_model: str
    embed_dim: int
    created_at: datetime
    sources: dict[str, int]  # source_id -> chunk count
    documents: int
    chunks: int
    signature: str = ""  # HMAC-SHA256 over the sorted chunk checksums (key: AUSCULTA_SESSION_SECRET)
