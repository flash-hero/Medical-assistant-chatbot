"""MedlinePlus Genetics compendium (ghr-summaries.xml) -> Documents: conditions, genes, chromosomes, mtDNA.

The compendium holds the public-domain description / normal-function text plus inheritance codes, synonyms
and cross-reference lists. Database key lists (SNOMED CT, OMIM, GTR...) are pointers and are kept only as
identifier metadata, never as text.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import structlog
from lxml import etree

from core.schemas.document import Document, Section
from core.schemas.source import ContentType, Language, SourceRecord
from data_pipeline.fetch.client import Fetcher
from data_pipeline.parsers.common import build_document
from data_pipeline.parsers.htmltext import html_to_sections, parse_fragment
from data_pipeline.paths import DataPaths

SOURCE_ID = "medlineplus_genetics"
COMPENDIUM_URL = "https://medlineplus.gov/download/ghr-summaries.xml"
BUILD_OPTIONS = {"min_chars": 100}
_ROLE_HEADINGS = {"description": None, "function": "Normal function"}
_ENTRY_TAGS = {
    "health-condition-summary": ("condition", ContentType.GENETICS),
    "gene-summary": ("gene", ContentType.GENETICS),
    "chromosome-summary": ("chromosome", ContentType.GENETICS),
    "mtdna-summary": ("mtdna", ContentType.GENETICS),
}
_NS_ATTR = re.compile(r'\sxmlns(:\w+)?="[^"]*"')
log = structlog.get_logger(__name__)


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> Path:
    result = await fetcher.fetch(COMPENDIUM_URL, refresh=True)
    if result.path is None:
        raise RuntimeError(f"cannot download {COMPENDIUM_URL}: HTTP {result.status}")
    return result.path


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child_text(el: etree._Element, name: str) -> str:
    for child in el:
        if _local(child.tag) == name:
            return " ".join("".join(child.itertext()).split())
    return ""


def _children(el: etree._Element, name: str) -> list[etree._Element]:
    return [c for c in el if _local(c.tag) == name]


def _html_to_fragment(html_el: etree._Element) -> str:
    markup = etree.tostring(html_el, encoding="unicode")
    markup = markup.replace("<html:", "<").replace("</html:", "</")
    markup = _NS_ATTR.sub("", markup)
    return re.sub(r"^<html>|</html>\s*$", "", markup.strip())


def _parse_month(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip()[:7], "%Y-%m").date()  # noqa: DTZ007
    except ValueError:
        return None


def _text_sections(el: etree._Element, title: str) -> list[Section]:
    sections: list[Section] = []
    for text_el in _children(_children(el, "text-list")[0], "text") if _children(el, "text-list") else []:
        role = _child_text(text_el, "text-role")
        htmls = _children(text_el, "html")
        if not htmls:
            continue
        heading = _ROLE_HEADINGS.get(role, role.replace("-", " ").capitalize() or None)
        parsed = html_to_sections(parse_fragment(_html_to_fragment(htmls[0])), title, intro_kind=None)
        for sec in parsed:
            path = sec.heading_path if heading is None else (*sec.heading_path[:1], heading, *sec.heading_path[1:])
            kind = "summary" if heading is None else role.replace("-", "_")
            sections.append(sec.model_copy(update={"heading_path": path, "kind": kind}))
    return sections


def _extra_sections(el: etree._Element, title: str, offset: int) -> list[Section]:
    """Inheritance pattern (conditions) and cross-references, rendered as short labelled sections."""
    extra: list[Section] = []
    patterns = [
        _child_text(p, "memo") for lst in _children(el, "inheritance-pattern-list") for p in _children(lst, "inheritance-pattern")
    ]
    if patterns:
        text = "Inheritance pattern: " + "; ".join(p for p in patterns if p) + "."
        extra.append(Section(section_id=f"s{offset + len(extra)}", heading_path=(title, "Inheritance"), text=text, kind="inheritance"))
    genes = [
        _child_text(g, "gene-symbol") or _child_text(g, "name")
        for lst in _children(el, "related-gene-list")
        for g in _children(lst, "related-gene")
    ]
    conditions = [
        _child_text(c, "name") for lst in _children(el, "related-health-condition-list") for c in _children(lst, "related-health-condition")
    ]
    for label, names, kind in (("Related genes", genes, "related_genes"), ("Related health conditions", conditions, "related_conditions")):
        if names:
            extra.append(
                Section(section_id=f"s{offset + len(extra)}", heading_path=(title, label), text=f"{label}: " + ", ".join(names) + ".", kind=kind)
            )
    return extra


def _title(kind: str, name: str, symbol: str) -> str:
    if kind == "gene":
        return f"{symbol} gene ({name})" if symbol and name else (symbol or name)
    if kind == "chromosome":
        return "Mitochondrial DNA" if name.lower() == "mitochondrial dna" else f"Chromosome {name}"
    return name


def entry_to_document(el: etree._Element, record: SourceRecord, retrieved_at: datetime) -> Document | None:
    kind, content_type = _ENTRY_TAGS[_local(el.tag)]
    name, symbol = _child_text(el, "name"), _child_text(el, "gene-symbol")
    page = _child_text(el, "ghr-page")
    title = _title("chromosome" if kind == "mtdna" else kind, name, symbol)
    if not (title and page and el.get("id")):
        return None
    sections = _text_sections(el, title)
    if not sections:
        return None
    sections += _extra_sections(el, title, len(sections))
    synonyms = [s.text or "" for lst in _children(el, "synonym-list") for s in _children(lst, "synonym")]
    keys = [(_child_text(k, "db"), _child_text(k, "key")) for lst in _children(el, "db-key-list") for k in _children(lst, "db-key")]
    return build_document(
        record,
        native_id=f"{kind}-{el.get('id')}",
        url=page,
        title=title,
        language=Language.EN,
        content_type=content_type,
        sections=sections,
        retrieved_at=retrieved_at,
        synonyms=[*synonyms, name] if kind == "gene" else synonyms,
        published_on=_parse_iso(_child_text(el, "published")),
        reviewed_on=_parse_month(_child_text(el, "reviewed")),
        metadata={
            "entry_kind": kind,
            "ghr_id": el.get("id", ""),
            "gene_symbol": symbol,
            "mesh_ids": [k for db, k in keys if db == "MeSH"],
            "omim_ids": [k for db, k in keys if db == "OMIM"],
            "source_file": "ghr-summaries.xml",
        },
    )


def _parse_iso(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


def parse_file(xml_path: Path, record: SourceRecord) -> Iterator[Document]:
    stamp = datetime.fromtimestamp(xml_path.stat().st_mtime, tz=UTC)
    tags = [f"{{*}}{t}" for t in _ENTRY_TAGS]
    for _, el in etree.iterparse(str(xml_path), tag=tags, load_dtd=False, no_network=True, resolve_entities=False):
        try:
            doc = entry_to_document(el, record, stamp)
        except ValueError as exc:
            log.warning("genetics_entry_skipped", id=el.get("id"), error=str(exc))
            doc = None
        el.clear()
        if doc is not None:
            yield doc


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    files = sorted(paths.raw_dir(record.id).rglob("ghr-summaries.xml"))
    if not files:
        raise FileNotFoundError(f"no ghr-summaries.xml under {paths.raw_dir(record.id)}; run fetch first")
    yield from parse_file(files[-1], record)
