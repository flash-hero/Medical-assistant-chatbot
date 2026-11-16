from __future__ import annotations

import re
from datetime import date, datetime

import httpx
import pytest
from dp_helpers import fixture_bytes, make_record, put_raw

from core.schemas.source import ContentType, Language
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.fetch.manifest import ManifestEntry
from data_pipeline.parsers import webpage
from data_pipeline.parsers.webpage import PageRules, class_xpath, extract_page, parse_loose_date
from data_pipeline.paths import DataPaths

HOST = "https://a.example.org"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Last Reviewed September 2019", date(2019, 9, 1)),
        ("Updated: May 16, 2025", date(2025, 5, 16)),
        ("Sept. 3, 2020", date(2020, 9, 3)),
        ("2024-02-29T12:00:00Z", date(2024, 2, 29)),
        ("last revised 8/6/2021", date(2021, 8, 6)),
        ("February 30, 2021", None),
        ("no date here", None),
        ("", None),
        (None, None),
        ("13/45/2021", None),
    ],
)
def test_parse_loose_date(text: str | None, expected: date | None) -> None:
    assert parse_loose_date(text) == expected


def test_class_xpath_matches_one_token_only() -> None:
    tree = webpage.parse_html('<div><p class="a share b">x</p><p class="shared">y</p></div>')
    assert [p.text for p in tree.xpath(f"//p[{class_xpath('share')}]")] == ["x"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bronchitis Bronchitis", "Bronchitis"),
        ("Type 2 Diabetes", "Type 2 Diabetes"),
        ("A B A B", "A B"),
        ("", ""),
    ],
)
def test_collapse_repeated_title(title: str, expected: str) -> None:
    assert webpage.collapse_repeated_title(title) == expected


def test_parse_html_accepts_str_and_bytes() -> None:
    assert webpage.parse_html("<p>é</p>").text_content() == "é"
    assert webpage.parse_html("<p>é</p>".encode()).text_content() == "é"


def test_extract_page_applies_rules_and_drops_noise() -> None:
    rules = PageRules(
        content_xpaths=("//main",),
        remove_xpaths=("//div[@class='ad']",),
        title_suffix=re.compile(r"\s+\|\s+.*$"),
        date_xpaths=("//span[@class='d']",),
        drop_headings=re.compile(r"^References$"),
        drop_lines=re.compile(r"^Enlarge"),
        drop_section_text=re.compile(r"^Menu"),
    )
    html = (
        "<html><head><title>T | Site</title><meta name='description' content='desc'></head><body>"
        "<span class='d'>Updated: May 16, 2025</span><nav>NAV</nav><main>"
        "<h1>Asthma | Site</h1><div class='ad'>BUY NOW</div><p>Menu items</p>"
        "<h2>Overview</h2><p>Enlarge this</p><p>Real paragraph text.</p>"
        "<h2>References</h2><p>Ref one</p></main></body></html>"
    )
    page = extract_page(html, rules)
    assert page is not None
    assert page.title == "Asthma"
    assert page.description == "desc"
    assert page.reviewed_on == date(2025, 5, 16)
    text = "\n".join(s.text for s in page.sections)
    assert "Real paragraph text." in text
    for banned in ("BUY NOW", "NAV", "Enlarge", "Ref one", "Menu items"):
        assert banned not in text
    assert [s.section_id for s in page.sections] == [f"s{i}" for i in range(len(page.sections))]


def test_extract_page_fallbacks_and_none_cases() -> None:
    rules = PageRules(content_xpaths=("//main",))
    page = extract_page(
        "<html><head><title>Only Title</title></head><body><main><p>Body text here.</p></main></body></html>",
        rules,
    )
    assert page is not None
    assert page.title == "Only Title"
    assert extract_page("<html><head><title>T</title></head><body><p>x</p></body></html>", rules) is None
    assert extract_page("<html><body><main><p>x</p></main></body></html>", rules) is None
    assert (
        extract_page("<html><head><title>T</title></head><body><main><h1>T</h1></main></body></html>", rules)
        is None
    )


def test_page_document_copies_licence_fields_from_the_record() -> None:
    record = make_record()
    page = extract_page(fixture_bytes("institute_page.html"), PageRules(content_xpaths=("//main",)))
    assert page is not None
    doc = webpage.page_document(
        record,
        url=f"{HOST}/p",
        page=page,
        retrieved_at=datetime(2026, 11, 15),
        native_id="a/b",
        content_type=ContentType.WELLNESS,
        language=Language.EN,
        synonyms=["GAD"],
        metadata={"k": "v"},
    )
    assert doc.doc_id == "src_a:a/b"
    assert doc.license_id == "pd"
    assert doc.attribution == "Source: A"
    assert doc.metadata["k"] == "v"
    assert doc.synonyms == ("GAD",)
    assert doc.checksum


def test_sitemap_locs_pages_and_children_and_malformed() -> None:
    pages, children = webpage.sitemap_locs(fixture_bytes("sitemap_pages.xml").decode())
    assert len(pages) == 5
    assert children == []
    pages, children = webpage.sitemap_locs(fixture_bytes("sitemap_index.xml").decode())
    assert pages == []
    assert children == ["https://www.niddk.nih.gov/sitemap-a.xml"]
    assert webpage.sitemap_locs("<not xml") == ([], [])


@pytest.mark.parametrize(
    ("url", "prefix", "expected"),
    [
        ("https://x.org/a/b/c?q=1#f", "", "a/b/c"),
        ("https://x.org/health-information/diabetes", "health-information", "diabetes"),
        ("https://x.org/", "", "index"),
        ("https://x.org/other/page", "health-information", "other/page"),
    ],
)
def test_local_path_id(url: str, prefix: str, expected: str) -> None:
    assert webpage.local_path_id(url, prefix) == expected


def test_entry_time_parses_or_falls_back() -> None:
    good = ManifestEntry(url="u", status=200, sha256="", bytes=0, fetched_at="2026-11-15T10:00:00+00:00")
    bad = ManifestEntry(url="u", status=200, sha256="", bytes=0, fetched_at="garbage")
    assert webpage.entry_time(good).year == 2026
    assert webpage.entry_time(bad).tzinfo is not None


def test_iter_pages_filters_by_ok_content_type_accept_and_missing_files(paths: DataPaths) -> None:
    record = make_record()
    put_raw(paths, record.id, f"{HOST}/b", "<p>b</p>")
    put_raw(paths, record.id, f"{HOST}/a", "<p>a</p>")
    put_raw(paths, record.id, f"{HOST}/data.json", "{}", content_type="application/json")
    put_raw(paths, record.id, f"{HOST}/gone", "x", status=404)
    missing = put_raw(paths, record.id, f"{HOST}/missing", "<p>m</p>")
    missing.unlink()
    got = [(e.url, c) for e, c in webpage.iter_pages(paths, record)]
    assert got == [(f"{HOST}/a", b"<p>a</p>"), (f"{HOST}/b", b"<p>b</p>")]
    only_a = [e.url for e, _ in webpage.iter_pages(paths, record, lambda e: e.url.endswith("/a"))]
    assert only_a == [f"{HOST}/a"]


def _fetcher(paths: DataPaths, routes: dict[str, httpx.Response]) -> Fetcher:
    async def no_sleep(_: float) -> None:
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404, text="nope"))

    return Fetcher(
        make_record(),
        paths,
        FetchConfig(default_rps=1000.0, backoff_base_s=0.0, max_retries=1),
        registry=(),
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
    )


async def test_collect_sitemap_urls_follows_index_levels_and_dedupes(paths: DataPaths) -> None:
    index = f"{HOST}/sitemap.xml"
    child = f"{HOST}/child.xml"
    index_xml = f'<sitemapindex xmlns="x"><sitemap><loc>{child}</loc></sitemap></sitemapindex>'
    child_xml = (
        f'<urlset xmlns="x"><url><loc>{HOST}/p1</loc></url><url><loc>{HOST}/p1</loc></url>'
        f"<url><loc>{HOST}/p2</loc></url></urlset>"
    )
    routes = {index: httpx.Response(200, text=index_xml), child: httpx.Response(200, text=child_xml)}
    async with _fetcher(paths, routes) as f:
        assert await webpage.collect_sitemap_urls(f, index) == [f"{HOST}/p1", f"{HOST}/p2"]
        assert await webpage.collect_sitemap_urls(f, index, depth=0) == []


async def test_collect_sitemap_urls_raises_when_unreadable(paths: DataPaths) -> None:
    async with _fetcher(paths, {f"{HOST}/s.xml": httpx.Response(404)}) as f:
        with pytest.raises(RuntimeError, match="cannot read sitemap"):
            await webpage.collect_sitemap_urls(f, f"{HOST}/s.xml")


async def test_fetch_urls_dedupes_limits_and_counts_ok(paths: DataPaths) -> None:
    routes = {f"{HOST}/{n}": httpx.Response(200, text=n) for n in ("a", "b", "c")}
    async with _fetcher(paths, routes) as f:
        assert await webpage.fetch_urls(f, [f"{HOST}/a", f"{HOST}/a", f"{HOST}/b", f"{HOST}/c"], limit=2) == 2
    async with _fetcher(paths, routes) as f:
        assert await webpage.fetch_urls(f, [f"{HOST}/c", f"{HOST}/zzz"]) == 1
