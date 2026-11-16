"""NIDDK health-information pages (sitemap crawl) -> Documents.

Licence (read 2026-11-15, https://www.niddk.nih.gov/copyright): "The majority of information on this site is
copyright free and can be freely downloaded and reproduced." Co-sponsored documents and licensed graphics are
exceptions; images are never ingested and each page is checked for copyright notices by the quality gates.
robots.txt asks for Crawl-delay 10, which the fetcher honours.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from core.schemas.document import Document
from core.schemas.source import ContentType, SourceRecord
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.fetch.manifest import ManifestEntry
from data_pipeline.parsers.webpage import (
    PageRules,
    class_xpath,
    collect_sitemap_urls,
    entry_time,
    extract_page,
    fetch_urls,
    iter_pages,
    local_path_id,
    page_document,
)
from data_pipeline.paths import DataPaths

SOURCE_ID = "niddk"
HOST = "www.niddk.nih.gov"
SITEMAP_URL = f"https://{HOST}/sitemap-sc.xml"
PREFIX = f"https://{HOST}/health-information"
FETCH_CONFIG = FetchConfig(host_rps={HOST: 0.1})
BUILD_OPTIONS = {"min_chars": 250, "strip_repeated_lines": True}
_SKIP_PATHS = ("/informacion-de-la-salud", "/clinical-trials", "/health-statistics", "/community-health-outreach")
RULES = PageRules(
    content_xpaths=(f"//div[{class_xpath('health-detail-content')}]", "//article"),
    remove_xpaths=(
        "//p[normalize-space(.)='On this page:']/following-sibling::ul[1]",
        "//p[normalize-space(.)='On this page:']",
        f"//*[{class_xpath('disclaimer')}]",
        f"//*[{class_xpath('dk-review-date')}]",
        f"//*[{class_xpath('youtube-container')}]",
    ),
    title_xpath="//h1",
    title_suffix=re.compile(r"\s+-\s+NIDDK$"),
    date_xpaths=(f"//div[{class_xpath('dk-review-date')}]",),
    drop_headings=re.compile(r"^(Clinical Trials?\b|References?$|Sources?$)", re.I),
)


def is_wanted_url(url: str) -> bool:
    """Health-information pages in English; Spanish, trial listings and statistics tables are skipped."""
    return url.startswith(PREFIX) and url != PREFIX and not any(skip in url for skip in _SKIP_PATHS)


def content_type_for(url: str) -> ContentType:
    if "/diagnostic-tests" in url:
        return ContentType.LAB_TEST
    if "/diet-nutrition" in url or "/weight-management" in url:
        return ContentType.WELLNESS
    return ContentType.CONDITION


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> int:
    urls = [u for u in await collect_sitemap_urls(fetcher, SITEMAP_URL) if is_wanted_url(u)]
    return await fetch_urls(fetcher, urls, limit=limit, concurrency=2)


def _accept(entry: ManifestEntry) -> bool:
    return is_wanted_url(entry.url)


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    for entry, content in iter_pages(paths, record, _accept):
        page = extract_page(content, RULES)
        if page is None:
            continue
        professional = "/health-information/professionals" in entry.url
        yield page_document(
            record,
            url=entry.url,
            page=page,
            retrieved_at=entry_time(entry),
            native_id=local_path_id(entry.url, "health-information"),
            content_type=content_type_for(entry.url),
            audience="professional" if professional else "patient",
            metadata={"section_path": local_path_id(entry.url, "health-information").split("/")[0]},
        )
