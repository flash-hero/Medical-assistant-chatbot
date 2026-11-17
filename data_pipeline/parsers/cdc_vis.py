"""CDC Vaccine Information Statements (current VIS HTML pages on cdc.gov) -> Documents.

Same licence record as the CDC site (public domain, attribute CDC, unaltered content): reuse_mode=quote_only.
The index page lists the current English VIS pages; translations are hosted by Immunize.org and are not used.
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
    entry_time,
    extract_page,
    fetch_urls,
    iter_pages,
    local_path_id,
    page_document,
)
from data_pipeline.paths import DataPaths

SOURCE_ID = "cdc_vis"
INDEX_URL = "https://www.cdc.gov/vaccines/hcp/current-vis/index.html"
_VIS_LINK = re.compile(r'href="(/vaccines/hcp/current-vis/[a-z0-9\-]+\.html)"')
FETCH_CONFIG = FetchConfig(default_rps=1.0)
BUILD_OPTIONS = {"min_chars": 400}
RULES = PageRules(
    content_xpaths=("//main",),
    title_xpath="//h1",
    title_suffix=re.compile(r"\s+\|\s+.*$"),
    date_xpaths=("//main//p[contains(., 'Current edition')]",),
    drop_headings=re.compile(r"^(On This Page|More about the vaccine)", re.I),
    drop_lines=re.compile(
        r"^(Language|Rich text file|PDF|Additional languages|For Health Care Providers)\b", re.I
    ),
)


def vis_urls(index_html: str) -> list[str]:
    """Absolute URLs of the VIS pages linked from the index (the index itself excluded)."""
    paths = dict.fromkeys(p for p in _VIS_LINK.findall(index_html) if not p.endswith("/index.html"))
    return [f"https://www.cdc.gov{p}" for p in paths]


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> int:
    index = await fetcher.fetch(INDEX_URL, refresh=True)
    if index.path is None:
        raise RuntimeError(f"cannot read {INDEX_URL}: HTTP {index.status}")
    urls = vis_urls(index.path.read_text(encoding="utf-8", errors="replace"))
    return await fetch_urls(fetcher, urls, limit=limit, concurrency=2)


def _accept(entry: ManifestEntry) -> bool:
    return entry.url != INDEX_URL and "/current-vis/" in entry.url


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    for entry, content in iter_pages(paths, record, _accept):
        page = extract_page(content, RULES)
        if page is None:
            continue
        yield page_document(
            record,
            url=entry.url,
            page=page,
            retrieved_at=entry_time(entry),
            native_id=local_path_id(entry.url, "vaccines/hcp/current-vis").removesuffix(".html"),
            content_type=ContentType.VACCINE,
            metadata={"document_kind": "Vaccine Information Statement"},
        )
