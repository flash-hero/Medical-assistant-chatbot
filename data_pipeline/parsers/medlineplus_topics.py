"""MedlinePlus Health Topics XML -> Documents (English topics only).

Only the public-domain topic summary is used. The <site> link records (which point at A.D.A.M. encyclopedia
and ASHP drug pages) are never read into a Document, and any topic whose own URL is excluded is skipped.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import structlog
from lxml import etree

from core.schemas.document import Document
from core.schemas.source import ContentType, Language, SourceRecord
from data_pipeline.fetch.client import Fetcher
from data_pipeline.parsers.common import build_document, parse_us_date
from data_pipeline.parsers.htmltext import html_to_sections, parse_fragment
from data_pipeline.paths import DataPaths
from data_pipeline.registry import is_excluded_url

SOURCE_ID = "medlineplus_topics"
INDEX_URL = "https://medlineplus.gov/xml.html"
_TOPICS_LINK = re.compile(r'href="(https://medlineplus\.gov/xml/mplus_topics_(\d{4}-\d{2}-\d{2})\.xml)"')
_CREDIT_PREFIX = re.compile(r"^(NIH|CDC|FDA|NLM)\s*:", re.I)
_TEST_GROUPS = frozenset({"diagnostic tests and screenings", "health check tools", "medical tests"})
_WELLNESS_GROUPS = frozenset(
    {
        "wellness and lifestyle",
        "food and nutrition",
        "exercise and physical fitness",
        "healthy living",
        "pharmacy and medicine",
        "personal health issues",
    }
)
BUILD_OPTIONS = {"min_chars": 100}  # some topic summaries are two sentences long
log = structlog.get_logger(__name__)


def discover_topics_url(index_html: str) -> str:
    """Newest dated Health Topic XML link published on xml.html (the explicit list of downloads)."""
    links = _TOPICS_LINK.findall(index_html)
    if not links:
        raise ValueError("no mplus_topics_*.xml link found on xml.html")
    return max(links, key=lambda pair: pair[1])[0]


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> Path:
    """Download xml.html and the newest topics file. The XML is robots-exempt only because xml.html itself
    publishes it for download (robots.txt disallows /xml/ for generic crawlers)."""
    index = await fetcher.fetch(INDEX_URL, refresh=True)
    if index.path is None:
        raise RuntimeError(f"cannot read {INDEX_URL}: HTTP {index.status}")
    topics_url = discover_topics_url(index.path.read_text(encoding="utf-8", errors="replace"))
    result = await fetcher.fetch(topics_url, robots_exempt=True)
    if result.path is None:
        raise RuntimeError(f"cannot download {topics_url}: HTTP {result.status}")
    return result.path


def _content_type(groups: list[str]) -> ContentType:
    lowered = {g.casefold() for g in groups}
    if lowered & _TEST_GROUPS:
        return ContentType.LAB_TEST
    if lowered & _WELLNESS_GROUPS and not any(
        g in lowered for g in ("disorders and conditions", "diseases and conditions", "symptoms")
    ):
        return ContentType.WELLNESS
    return ContentType.CONDITION


def _split_credit(markup: str) -> tuple[str, str]:
    """Remove the trailing '<p>NIH: National Institute ...</p>' credit paragraph; return (markup, credit)."""
    root = parse_fragment(markup)
    paragraphs = [c for c in root if isinstance(c.tag, str)]
    if paragraphs and paragraphs[-1].tag == "p":
        text = " ".join("".join(paragraphs[-1].itertext()).split())
        if _CREDIT_PREFIX.match(text) and len(text) < 160:
            root.remove(paragraphs[-1])
            return etree.tostring(root, encoding="unicode"), text
    return markup, ""


def topic_to_document(
    el: etree._Element, record: SourceRecord, retrieved_at: datetime, source_file: str
) -> Document | None:
    """One <health-topic> element -> Document, or None when it must be skipped."""
    if el.get("language") != "English":
        return None
    url = el.get("url", "")
    title = (el.get("title") or "").strip()
    summary = (el.findtext("full-summary") or "").strip()
    if not (url and title and summary) or is_excluded_url(url):
        return None
    body, credit = _split_credit(summary)
    sections = html_to_sections(parse_fragment(body), title)
    if not sections:
        return None
    groups = [(g.text or "").strip() for g in el.findall("group")]
    descriptors = el.findall("mesh-heading/descriptor")
    synonyms = [t.text or "" for t in el.findall("also-called")] + [
        t.text or "" for t in el.findall("see-reference")
    ]
    return build_document(
        record,
        native_id=el.get("id", ""),
        url=url,
        title=title,
        language=Language.EN,
        content_type=_content_type(groups),
        sections=sections,
        retrieved_at=retrieved_at,
        synonyms=synonyms,
        published_on=parse_us_date(el.get("date-created")),
        metadata={
            "topic_id": el.get("id", ""),
            "mesh_ids": [d.get("id", "") for d in descriptors if d.get("id")],
            "mesh_terms": [(d.text or "").strip() for d in descriptors],
            "groups": [g for g in groups if g],
            "primary_institute": (el.findtext("primary-institute") or "").strip(),
            "summary_credit": credit,
            "meta_description": (el.get("meta-desc") or "").strip(),
            "related_topics": [(r.text or "").strip() for r in el.findall("related-topic")],
            "source_file": source_file,
        },
    )


def parse_file(
    xml_path: Path, record: SourceRecord, retrieved_at: datetime | None = None
) -> Iterator[Document]:
    """Stream the (30 MB) topics file; elements are cleared as they are consumed."""
    stamp = retrieved_at or datetime.fromtimestamp(xml_path.stat().st_mtime, tz=UTC)
    parser_kwargs = {"tag": "health-topic", "load_dtd": False, "no_network": True, "resolve_entities": False}
    for _, el in etree.iterparse(str(xml_path), **parser_kwargs):  # type: ignore[arg-type]
        try:
            doc = topic_to_document(el, record, stamp, xml_path.name)
        except ValueError as exc:
            log.warning("topic_skipped", topic=el.get("id"), error=str(exc))
            doc = None
        el.clear()
        if doc is not None:
            yield doc


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    """Parse the newest topics file found under raw/medlineplus_topics/."""
    files = sorted(paths.raw_dir(record.id).rglob("mplus_topics_????-??-??.xml"))
    if not files:
        raise FileNotFoundError(f"no mplus_topics_*.xml under {paths.raw_dir(record.id)}; run fetch first")
    yield from parse_file(files[-1], record)
