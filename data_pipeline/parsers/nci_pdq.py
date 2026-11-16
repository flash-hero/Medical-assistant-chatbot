"""NCI PDQ cancer information summaries, PATIENT version only (cancer.gov) -> Documents.

Licence (read 2026-11-15, https://www.cancer.gov/policies/copyright-reuse): "Unless otherwise indicated, all
text
within National Cancer Institute (NCI) products is free of copyright and may be reused without our permission.
Credit the National Cancer Institute as the source." Health-professional PDQ versions, Spanish pages, images
and the "About This PDQ Summary" section are not ingested. cancer.gov redirects retired patient summaries to
newer non-PDQ pages; those are skipped because the final URL is no longer a PDQ patient summary.
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

SOURCE_ID = "nci_pdq"
SITEMAP_URL = "https://www.cancer.gov/sitemaps/pageinstructions.xml"
_PATIENT_PDQ = re.compile(r"^https://www\.cancer\.gov/types/[a-z0-9\-]+/patient/[a-z0-9\-]+-pdq$")
FETCH_CONFIG = FetchConfig(default_rps=1.0)
BUILD_OPTIONS = {"min_chars": 300}
RULES = PageRules(
    content_xpaths=("//div[@id='cgvBody']", "//article"),
    remove_xpaths=(
        f"//*[{class_xpath('pdq-hp-patient-toggle')}]",
        f"//*[{class_xpath('on-this-page')}]",
        f"//*[{class_xpath('article-footer')}]",
    ),
    title_xpath="//h1",
    title_suffix=re.compile(r"\s+-\s+NCI$"),
    date_xpaths=(f"//footer[{class_xpath('article-footer')}]",),
    drop_headings=re.compile(r"^About This PDQ Summary", re.I),
    drop_lines=re.compile(r"^Enlarge\b"),
)


def is_patient_pdq_url(url: str) -> bool:
    return bool(_PATIENT_PDQ.match(url))


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> int:
    urls = [u for u in await collect_sitemap_urls(fetcher, SITEMAP_URL) if is_patient_pdq_url(u)]
    return await fetch_urls(fetcher, urls, limit=limit, concurrency=2)


def _accept(entry: ManifestEntry) -> bool:
    """Only pages that are still PDQ patient summaries after redirects."""
    return is_patient_pdq_url(entry.url) and is_patient_pdq_url(entry.final_url or entry.url)


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    for entry, content in iter_pages(paths, record, _accept):
        page = extract_page(content, RULES)
        if page is None:
            continue
        native = local_path_id(entry.url, "types")
        yield page_document(
            record,
            url=entry.url,
            page=page,
            retrieved_at=entry_time(entry),
            native_id=native,
            content_type=ContentType.CONDITION,
            metadata={"cancer_type": native.split("/")[0], "pdq_version": "patient"},
        )
