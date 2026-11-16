"""Generic HTML page -> Document support for crawled sites (shared by NIDDK, NCI PDQ, CDC, NIH institutes...).

A site module supplies `PageRules` (where the main content is, what to remove, which sections to drop); this
module does the lxml work, the manifest walk and the sitemap parsing. Nothing here talks to the network except
`fetch_urls`, which goes through the polite Fetcher.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import structlog
from lxml import etree
from lxml import html as lxml_html
from lxml.html import HtmlElement

from core.schemas.document import Document, Section
from core.schemas.source import ContentType, Language, SourceRecord
from data_pipeline.fetch.client import FetchFailedError, Fetcher, FetchRefusedError
from data_pipeline.fetch.manifest import Manifest, ManifestEntry
from data_pipeline.parsers.common import build_document
from data_pipeline.parsers.htmltext import collapse_ws, html_to_sections
from data_pipeline.paths import DataPaths

log = structlog.get_logger(__name__)


def class_xpath(token: str) -> str:
    """XPath predicate matching one class token (class="a b" matches token "b")."""
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {token} ')"


COMMON_REMOVE: tuple[str, ...] = (
    "//script",
    "//style",
    "//noscript",
    "//nav",
    "//header",
    "//footer",
    "//aside",
    "//form",
    "//svg",
    "//iframe",
    "//button",
    "//*[@role='navigation' or @role='banner' or @role='contentinfo' or @aria-hidden='true']",
    "//*[@hidden]",
) + tuple(
    f"//*[{class_xpath(token)}]"
    for token in ("breadcrumb", "breadcrumbs", "share", "social-share", "print-only", "skip-link", "sr-only")
)


@dataclass(frozen=True)
class PageRules:
    """Per-site extraction rules. All XPath strings are evaluated on the parsed page."""

    content_xpaths: tuple[str, ...] = ("//main", "//article", "//body")
    remove_xpaths: tuple[str, ...] = ()
    title_xpath: str = "//h1"
    title_suffix: re.Pattern[str] | None = None
    date_xpaths: tuple[str, ...] = ()
    drop_headings: re.Pattern[str] | None = None  # sections under a matching top-level heading are dropped
    drop_lines: re.Pattern[str] | None = None  # single lines (e.g. "Enlarge ...") removed from section text
    drop_section_text: re.Pattern[str] | None = None  # whole sections whose text matches (e.g. "On this page" menus)
    keep_common_remove: bool = True
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedPage:
    title: str
    sections: tuple[Section, ...]
    reviewed_on: date | None
    description: str


_MONTH_DATE = re.compile(
    r"(?:(?P<m1>January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(?:(?P<d>\d{1,2}),?\s+)?(?P<y1>\d{4}))|"
    r"(?:(?P<y2>\d{4})-(?P<m2>\d{2})-(?P<d2>\d{2}))|(?:(?P<m3>\d{1,2})/(?P<d3>\d{1,2})/(?P<y3>\d{4}))",
    re.I,
)
_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}


def parse_loose_date(text: str | None) -> date | None:
    """First date in a string like 'Last Reviewed September 2019', 'Updated: May 16, 2025' or an ISO stamp."""
    if not text:
        return None
    match = _MONTH_DATE.search(text)
    if not match:
        return None
    try:
        if match["m1"]:
            return date(int(match["y1"]), _MONTHS[match["m1"].lower()], int(match["d"] or 1))
        if match["y2"]:
            return date(int(match["y2"]), int(match["m2"]), int(match["d2"]))
        return date(int(match["y3"]), int(match["m3"]), int(match["d3"]))
    except (ValueError, KeyError):
        return None


def parse_html(content: bytes | str) -> HtmlElement:
    if isinstance(content, str):
        content = content.encode("utf-8")
    parser = lxml_html.HTMLParser(encoding="utf-8", remove_comments=True, remove_pis=True)
    return lxml_html.document_fromstring(content, parser=parser)


def _drop_all(tree: HtmlElement, xpaths: Iterable[str]) -> None:
    for xpath in xpaths:
        for node in tree.xpath(xpath):
            if node.getparent() is not None:
                node.drop_tree()


def _first_text(tree: HtmlElement, xpath: str) -> str:
    nodes = tree.xpath(xpath)
    if not nodes:
        return ""
    node = nodes[0]
    return collapse_ws(node if isinstance(node, str) else node.text_content())


def _meta(tree: HtmlElement, name: str) -> str:
    values = tree.xpath(f"//meta[@name='{name}' or @property='{name}']/@content")
    return collapse_ws(values[0]) if values else ""


def _filter_sections(sections: Iterable[Section], rules: PageRules) -> tuple[Section, ...]:
    kept: list[Section] = []
    for section in sections:
        top = section.heading_path[1] if len(section.heading_path) > 1 else ""
        if rules.drop_headings and top and rules.drop_headings.search(top):
            continue
        text = section.text
        if rules.drop_section_text and rules.drop_section_text.search(text):
            continue
        if rules.drop_lines:
            text = "\n".join(ln for ln in text.split("\n") if not rules.drop_lines.search(ln)).strip()
        if text:
            kept.append(section.model_copy(update={"text": text}))
    return tuple(section.model_copy(update={"section_id": f"s{i}"}) for i, section in enumerate(kept))


def collapse_repeated_title(title: str) -> str:
    """'Bronchitis Bronchitis' (kicker + heading) -> 'Bronchitis'."""
    words = title.split()
    half, odd = divmod(len(words), 2)
    if not odd and half and words[:half] == words[half:]:
        return " ".join(words[:half])
    return title


def extract_page(content: bytes | str, rules: PageRules) -> ExtractedPage | None:
    """Main content of a page as sections; None when no content container or no title is found."""
    tree = parse_html(content)
    title = _first_text(tree, rules.title_xpath)
    if not title:
        title = _first_text(tree, "//title")
    if rules.title_suffix:
        title = rules.title_suffix.sub("", title).strip()
    title = collapse_repeated_title(title)
    description = _meta(tree, "description")
    reviewed = next((d for d in (parse_loose_date(_first_text(tree, x)) for x in rules.date_xpaths) if d), None)
    container = next((nodes[0] for xp in rules.content_xpaths if (nodes := tree.xpath(xp))), None)
    if container is None or not title:
        return None
    if rules.keep_common_remove:
        _drop_all(container, [x.replace("//", ".//", 1) for x in COMMON_REMOVE])
    _drop_all(container, [x.replace("//", ".//", 1) if x.startswith("//") else x for x in rules.remove_xpaths])
    heading = container.xpath(".//h1")
    if heading and collapse_ws(heading[0].text_content()) and heading[0].getparent() is not None:
        heading[0].drop_tree()  # the title is carried by heading_path[0]
    sections = _filter_sections(html_to_sections(container, title), rules)
    if not sections:
        return None
    return ExtractedPage(title=title, sections=sections, reviewed_on=reviewed, description=description)


def page_document(
    record: SourceRecord,
    *,
    url: str,
    page: ExtractedPage,
    retrieved_at: datetime,
    native_id: str,
    content_type: ContentType = ContentType.CONDITION,
    language: Language = Language.EN,
    audience: str = "patient",
    synonyms: Iterable[str] = (),
    metadata: dict[str, str | int | float | bool | list[str] | None] | None = None,
) -> Document:
    meta: dict[str, str | int | float | bool | list[str] | None] = {"meta_description": page.description}
    meta.update(metadata or {})
    return build_document(
        record,
        native_id=native_id,
        url=url,
        title=page.title,
        language=language,
        content_type=content_type,
        sections=page.sections,
        retrieved_at=retrieved_at,
        synonyms=synonyms,
        reviewed_on=page.reviewed_on,
        metadata=meta,
        audience=audience,
    )


# ---- sitemap ------------------------------------------------------------------------------------
def sitemap_locs(xml_text: str) -> tuple[list[str], list[str]]:
    """(page URLs, child sitemap URLs) of a sitemap or sitemap index. Malformed XML yields two empty lists."""
    try:
        root = etree.fromstring(xml_text.encode("utf-8"), parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return [], []
    pages: list[str] = []
    children: list[str] = []
    for node in root.iter():
        if not isinstance(node.tag, str) or not node.tag.endswith("loc") or not node.text:
            continue
        parent = node.getparent().tag if node.getparent() is not None else ""
        (children if str(parent).endswith("sitemap") else pages).append(node.text.strip())
    return pages, children


async def collect_sitemap_urls(fetcher: Fetcher, sitemap_url: str, *, depth: int = 2) -> list[str]:
    """All page URLs below a sitemap (index files followed up to `depth` levels)."""
    result = await fetcher.fetch(sitemap_url, refresh=True)
    if result.path is None:
        raise RuntimeError(f"cannot read sitemap {sitemap_url}: HTTP {result.status}")
    pages, children = sitemap_locs(result.path.read_text(encoding="utf-8", errors="replace"))
    if depth > 0:
        for child in children:
            pages.extend(await collect_sitemap_urls(fetcher, child, depth=depth - 1))
    return list(dict.fromkeys(pages))


# ---- fetching and reading back ------------------------------------------------------------------
async def fetch_urls(fetcher: Fetcher, urls: Iterable[str], *, limit: int | None = None, concurrency: int = 4) -> int:
    """Fetch pages politely (resumable: URLs already in the manifest are skipped). Returns the OK count."""
    wanted = list(dict.fromkeys(urls))
    if limit is not None:
        wanted = wanted[:limit]
    ok = 0
    for start in range(0, len(wanted), 100):
        batch = wanted[start : start + 100]
        results = await fetcher.fetch_many(batch, concurrency=concurrency)
        ok += sum(1 for r in results if not isinstance(r, Exception) and r.ok)
        log.info("fetch_progress", source=fetcher.source.id, done=start + len(batch), total=len(wanted), ok=ok)
    return ok


def iter_pages(
    paths: DataPaths, record: SourceRecord, accept: Callable[[ManifestEntry], bool] | None = None
) -> Iterator[tuple[ManifestEntry, bytes]]:
    """(manifest entry, raw bytes) for each successfully fetched HTML page of a source, in URL order."""
    raw_dir = paths.raw_dir(record.id)
    manifest = Manifest(raw_dir / "_manifest.jsonl")
    for entry in sorted(manifest.entries(), key=lambda e: e.url):
        if not entry.ok or (accept is not None and not accept(entry)):
            continue
        if "html" not in entry.content_type.lower() and entry.content_type:
            continue
        file = raw_dir / entry.path
        try:
            yield entry, file.read_bytes()
        except OSError as exc:
            log.warning("raw_file_unreadable", path=str(file), error=str(exc))


def entry_time(entry: ManifestEntry) -> datetime:
    try:
        return datetime.fromisoformat(entry.fetched_at)
    except ValueError:
        return datetime.now(UTC)


def local_path_id(url: str, strip_prefix: str = "") -> str:
    """Stable native id from a URL path: '/a/b/c' -> 'a/b/c' (optionally without a leading prefix)."""
    path = re.sub(r"^https?://[^/]+", "", url).split("?")[0].split("#")[0].strip("/")
    if strip_prefix and path.startswith(strip_prefix.strip("/")):
        path = path[len(strip_prefix.strip("/")) :].strip("/")
    return path or "index"


__all__ = [
    "FetchFailedError",
    "FetchRefusedError",
    "PageRules",
    "class_xpath",
    "collect_sitemap_urls",
    "extract_page",
    "fetch_urls",
    "iter_pages",
    "page_document",
    "parse_loose_date",
    "sitemap_locs",
]
