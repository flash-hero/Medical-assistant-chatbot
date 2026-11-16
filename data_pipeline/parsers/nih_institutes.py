"""NIH institute health-information pages (sitemap crawl) -> Documents.

One data table drives six sources (NIMH, NHLBI, NEI, NICHD, NIAMS, NCCIH); each source keeps its own licence
record in the registry (terms read on each institute's own policy page, 2026-11-15). NIA, NINDS and NIAID are
registered as `hold`: their servers refuse our crawler (HTTP 403/405), and that block is not circumvented.
Images and logos are never ingested; Spanish and other-language pages are skipped by the URL patterns.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from core.schemas.document import Document
from core.schemas.source import ContentType, SourceRecord
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.fetch.manifest import ManifestEntry
from data_pipeline.parsers.webpage import (
    PageRules,
    collect_sitemap_urls,
    entry_time,
    extract_page,
    fetch_urls,
    iter_pages,
    local_path_id,
    page_document,
)
from data_pipeline.paths import DataPaths

_SECONDS_BETWEEN_REQUESTS = 2.0  # polite to institute servers: 0.5 request per second per host
_MENU_TEXT = re.compile(r"^(Menu\s+)?On this page\b", re.I)


@dataclass(frozen=True)
class Institute:
    source_id: str
    host: str
    sitemaps: tuple[str, ...]
    include: re.Pattern[str]  # matched against the URL path
    rules: PageRules
    min_chars: int = 300


def _rules(content: str, *, dates: tuple[str, ...] = ("//time",), extra: tuple[str, ...] = ()) -> PageRules:
    return PageRules(
        content_xpaths=(content, "//main"),
        remove_xpaths=extra,
        date_xpaths=dates,
        title_xpath="//h1",
        title_suffix=re.compile(r"\s+\|\s+.*$"),
        drop_headings=re.compile(
            r"^(References?|Reprints|Clinical Trials?\b.*|Explore clinical trials.*|Share outreach materials.*|Additional federal resources|"
            r"Related (Topics|Resources|Information)|Sources?|Find help and support)$",
            re.I,
        ),
        drop_section_text=_MENU_TEXT,
    )


INSTITUTES: dict[str, Institute] = {
    "nimh": Institute(
        "nimh",
        "www.nimh.nih.gov",
        ("https://www.nimh.nih.gov/sites/default/files/sitemap/sitemap.xml",),
        re.compile(r"^/health/(topics|publications)/[a-z0-9\-]+$"),
        _rules("//div[contains(@class,'main_container')]", dates=("//*[contains(text(),'Last Revised')]",)),
    ),
    "nhlbi": Institute(
        "nhlbi",
        "www.nhlbi.nih.gov",
        ("https://www.nhlbi.nih.gov/sitemap.xml",),
        re.compile(r"^/health/[a-z0-9\-]+(/[a-z0-9\-]+)?$"),
        _rules("//div[contains(@class,'layout__region--second')]"),
    ),
    "nei": Institute(
        "nei",
        "www.nei.nih.gov",
        ("https://www.nei.nih.gov/sitemap.xml",),
        re.compile(r"^/eye-health-information/(eye-conditions-and-diseases|healthy-vision)(/[a-z0-9\-]+)+$"),
        _rules("//div[contains(@class,'r-content')]"),
    ),
    "nichd": Institute(
        "nichd",
        "www.nichd.nih.gov",
        ("https://www.nichd.nih.gov/default/sitemap.xml",),
        re.compile(r"^/health/topics/[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+){0,3}$"),
        _rules("//div[contains(@class,'region-content')]"),
    ),
    "niams": Institute(
        "niams",
        "www.niams.nih.gov",
        ("https://www.niams.nih.gov/sitemap.xml",),
        re.compile(r"^/health-topics/[a-z0-9\-]+(/[a-z0-9\-]+)*$"),
        _rules("//main"),
    ),
    "nccih": Institute(
        "nccih",
        "www.nccih.nih.gov",
        ("https://www.nccih.nih.gov/sitemap/sitemap-index.xml",),
        re.compile(r"^/health/(?!providers|espanol)[a-z0-9\-]+$"),
        _rules("//div[contains(@class,'maincontainerdiv')]", dates=()),
    ),
}
MODULE_SOURCE_IDS = tuple(INSTITUTES)


def institute_for(source_id: str) -> Institute:
    try:
        return INSTITUTES[source_id]
    except KeyError as exc:
        raise KeyError(f"{source_id!r} is not an NIH institute source") from exc


def fetch_config_for(source_id: str) -> FetchConfig:
    return FetchConfig(host_rps={institute_for(source_id).host: 1.0 / _SECONDS_BETWEEN_REQUESTS})


def build_options_for(source_id: str) -> dict[str, Any]:
    return {"min_chars": institute_for(source_id).min_chars, "strip_repeated_lines": True}


def path_of(url: str) -> str:
    return "/" + local_path_id(url)


def is_wanted_url(institute: Institute, url: str) -> bool:
    return url.startswith(f"https://{institute.host}/") and bool(institute.include.match(path_of(url)))


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> int:
    institute = institute_for(fetcher.source.id)
    urls: list[str] = []
    for sitemap in institute.sitemaps:
        urls.extend(u for u in await collect_sitemap_urls(fetcher, sitemap) if is_wanted_url(institute, u))
    return await fetch_urls(fetcher, urls, limit=limit, concurrency=2)


def _content_type(path: str) -> ContentType:
    return (
        ContentType.WELLNESS
        if "healthy-vision" in path or "health/heart-healthy-living" in path
        else ContentType.CONDITION
    )


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    institute = institute_for(record.id)

    def accept(entry: ManifestEntry) -> bool:
        return is_wanted_url(institute, entry.url)

    for entry, content in iter_pages(paths, record, accept):
        page = extract_page(content, institute.rules)
        if page is None:
            continue
        native = local_path_id(entry.url)
        yield page_document(
            record,
            url=entry.url,
            page=page,
            retrieved_at=entry_time(entry),
            native_id=native,
            content_type=_content_type(native),
            metadata={"institute": record.id},
        )
