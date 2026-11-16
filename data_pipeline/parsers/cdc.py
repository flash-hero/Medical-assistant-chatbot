"""CDC content via the CDC Content Syndication API (tools.cdc.gov/api/v2) -> Documents.

Licence (read 2026-11-15, https://www.cdc.gov/other/agencymaterials.html): most CDC content is public domain
and may be freely used, with four requirements: attribute CDC, show a non-endorsement disclaimer, do NOT change
the substantive content, and state the material is available free on the agency site. The registry therefore
sets reuse_mode=quote_only. Syndicated HTML is fetched unchanged from `contentUrl`; the citation URL is the
page's own cdc.gov address. Only English HTML items are used; occupational (NIOSH) pages are out of scope.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import structlog

from core.schemas.document import Document
from core.schemas.source import ContentType, SourceRecord
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.fetch.manifest import Manifest
from data_pipeline.parsers.webpage import (
    ExtractedPage,
    PageRules,
    class_xpath,
    entry_time,
    extract_page,
    fetch_urls,
    page_document,
    parse_loose_date,
)
from data_pipeline.paths import DataPaths

SOURCE_ID = "cdc"
API_BASE = "https://tools.cdc.gov/api/v2/resources/media"
LISTING_URL = (
    API_BASE + "?max=100&format=json&mediatype=html&language=english&sort=datepublished&pagenum={page}"
)
FETCH_CONFIG = FetchConfig(default_rps=1.0)
BUILD_OPTIONS = {"min_chars": 300}
_SKIP_SOURCE_PARTS = ("/niosh/",)
_PROFESSIONAL_PARTS = (
    "/hcp/",
    "/php/",
    "/clinical",
    "/laboratory",
    "/lab/",
    "/public-health-",
    "/health-departments",
)
RULES = PageRules(
    content_xpaths=("//div[@id='content']", "//body"),
    remove_xpaths=(
        f"//*[{class_xpath('dfe-section__nav')}]",
        f"//*[{class_xpath('onThisPageAnchor')}]",
        f"//*[{class_xpath('dfe-image')}]",
    ),
    title_xpath="//h1",
)
log = structlog.get_logger(__name__)


def listing_urls(total_pages: int) -> list[str]:
    return [LISTING_URL.format(page=n) for n in range(1, total_pages + 1)]


def _results(path: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("cdc_listing_unreadable", path=str(path), error=str(exc))
        return []
    results = data.get("results") if isinstance(data, dict) else None
    return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []


def is_wanted_item(item: dict[str, object]) -> bool:
    """English HTML syndication items whose own page lives on www.cdc.gov (and is not occupational)."""
    source_url = str(item.get("sourceUrl") or "")
    language = item.get("language")
    english = isinstance(language, dict) and language.get("isoCode2") == "en"
    if not (english and str(item.get("mediaType", "")).upper() == "HTML" and item.get("contentUrl")):
        return False
    return source_url.startswith("https://www.cdc.gov/") and not any(
        p in source_url for p in _SKIP_SOURCE_PARTS
    )


def _listing_items(manifest: Manifest, raw_dir: Path) -> Iterator[dict[str, object]]:
    for entry in sorted(manifest.entries(), key=lambda e: e.url):
        if entry.ok and entry.url.startswith(API_BASE + "?"):
            yield from _results(raw_dir / entry.path)


async def fetch(fetcher: Fetcher, paths: DataPaths, *, limit: int | None = None) -> int:
    first = await fetcher.fetch(LISTING_URL.format(page=1), refresh=True)
    if first.path is None:
        raise RuntimeError(f"cannot read the CDC syndication listing: HTTP {first.status}")
    meta = json.loads(first.path.read_text(encoding="utf-8")).get("meta", {})
    total_pages = int(meta.get("pagination", {}).get("totalPages", 1))
    for url in listing_urls(total_pages)[1:]:
        await fetcher.fetch(url, refresh=True)
    raw_dir = paths.raw_dir(SOURCE_ID)
    items = [i for i in _listing_items(fetcher.manifest, raw_dir) if is_wanted_item(i)]
    return await fetch_urls(fetcher, [str(i["contentUrl"]) for i in items], limit=limit, concurrency=4)


def _audience(source_url: str) -> str:
    return "professional" if any(part in source_url for part in _PROFESSIONAL_PARTS) else "patient"


def _reviewed(item: dict[str, object]) -> date | None:
    for key in ("dateContentReviewed", "dateContentUpdated", "dateModified"):
        parsed = parse_loose_date(str(item.get(key) or ""))
        if parsed:
            return parsed
    return None


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    raw_dir = paths.raw_dir(record.id)
    manifest = Manifest(raw_dir / "_manifest.jsonl")
    for item in _listing_items(manifest, raw_dir):
        if not is_wanted_item(item):
            continue
        entry = manifest.latest(str(item["contentUrl"]))
        if entry is None or not entry.ok:
            continue
        try:
            content = (raw_dir / entry.path).read_bytes()
        except OSError:
            continue
        page = extract_page(content, RULES)
        if page is None:
            continue
        page = ExtractedPage(
            title=page.title,
            sections=page.sections,
            reviewed_on=_reviewed(item),
            description=str(item.get("description") or ""),
        )
        source_url = str(item["sourceUrl"])
        yield page_document(
            record,
            url=source_url,
            page=page,
            retrieved_at=entry_time(entry),
            native_id=str(item["id"]),
            content_type=ContentType.CONDITION,
            audience=_audience(source_url),
            metadata={"cdc_media_id": str(item["id"]), "syndication_url": str(item["contentUrl"])},
        )
