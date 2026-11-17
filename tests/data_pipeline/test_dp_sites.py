"""Site modules (NIDDK, NCI PDQ, CDC, CDC VIS, NIH institutes): mock-origin fetch, recorded-page parse."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from dp_helpers import fixture_bytes, put_raw

from core.schemas.source import ContentType, SourceRecord
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.parsers import cdc, cdc_vis, nci_pdq, niddk, nih_institutes
from data_pipeline.paths import DataPaths
from data_pipeline.registry import get_source


async def _no_sleep(_: float) -> None:
    return None


def _fetcher(paths: DataPaths, source_id: str, routes: dict[str, httpx.Response]) -> Fetcher:
    record = get_source(source_id)
    assert record is not None

    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404, text="nope"))

    return Fetcher(
        record,
        paths,
        FetchConfig(default_rps=1000.0, backoff_base_s=0.0, max_retries=1),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )


def _record(source_id: str) -> SourceRecord:
    record = get_source(source_id)
    assert record is not None
    return record


def _html(name: str) -> httpx.Response:
    return httpx.Response(200, content=fixture_bytes(name), headers={"content-type": "text/html"})


# ---- NIDDK ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "wanted"),
    [
        ("https://www.niddk.nih.gov/health-information/diabetes", True),
        ("https://www.niddk.nih.gov/health-information", False),
        ("https://www.niddk.nih.gov/health-information/informacion-de-la-salud/x", False),
        ("https://www.niddk.nih.gov/health-information/health-statistics/x", False),
        ("https://www.niddk.nih.gov/about-niddk/x", False),
    ],
)
def test_niddk_is_wanted_url(url: str, wanted: bool) -> None:
    assert niddk.is_wanted_url(url) is wanted


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://www.niddk.nih.gov/health-information/diagnostic-tests/a1c", ContentType.LAB_TEST),
        ("https://www.niddk.nih.gov/health-information/diet-nutrition/x", ContentType.WELLNESS),
        ("https://www.niddk.nih.gov/health-information/weight-management/x", ContentType.WELLNESS),
        ("https://www.niddk.nih.gov/health-information/kidney-disease", ContentType.CONDITION),
    ],
)
def test_niddk_content_type(url: str, kind: ContentType) -> None:
    assert niddk.content_type_for(url) is kind


def test_niddk_parse_extracts_content_and_drops_trials_references_and_menus(paths: DataPaths) -> None:
    url = "https://www.niddk.nih.gov/health-information/blood-diseases/aplastic-anemia/diagnosis"
    put_raw(paths, "niddk", url, fixture_bytes("niddk_page.html"))
    put_raw(paths, "niddk", "https://www.niddk.nih.gov/about-niddk/x", "<html></html>")
    docs = list(niddk.parse(paths, _record("niddk")))
    assert len(docs) == 1
    doc = docs[0]
    body = "\n".join(s.text for s in doc.sections)
    assert doc.title == "Diagnosis of Aplastic Anemia"
    assert doc.doc_id == "niddk:blood-diseases/aplastic-anemia/diagnosis"
    assert doc.reviewed_on == date(2020, 7, 1)
    assert doc.audience == "patient"
    assert doc.metadata["section_path"] == "blood-diseases"
    assert "- the amount of hemoglobin" in body
    assert "complete blood count" in body
    for dropped in ("On this page", "Clinical trials", "citation that must not", "Copyright footer", "Print"):
        assert dropped.lower() not in body.lower()


def test_niddk_professional_pages_are_flagged(paths: DataPaths) -> None:
    url = "https://www.niddk.nih.gov/health-information/professionals/clinical-tools/x"
    put_raw(paths, "niddk", url, fixture_bytes("niddk_page.html"))
    (doc,) = niddk.parse(paths, _record("niddk"))
    assert doc.audience == "professional"


async def test_niddk_fetch_reads_sitemap_and_fetches_only_wanted_pages(paths: DataPaths) -> None:
    routes = {
        niddk.SITEMAP_URL: httpx.Response(200, content=fixture_bytes("sitemap_pages.xml")),
        "https://www.niddk.nih.gov/health-information/diabetes": _html("niddk_page.html"),
        "https://www.niddk.nih.gov/health-information/blood-diseases/anemia": _html("niddk_page.html"),
    }
    async with _fetcher(paths, "niddk", routes) as fetcher:
        assert await niddk.fetch(fetcher, paths) == 2
        assert (
            await niddk.fetch(fetcher, paths, limit=1) == 1
        )  # resumable: second run is served from the manifest
    assert len(list(niddk.parse(paths, _record("niddk")))) == 2


# ---- NCI PDQ -------------------------------------------------------------------------------------
PDQ_URL = "https://www.cancer.gov/types/bone/patient/ewing-treatment-pdq"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (PDQ_URL, True),
        ("https://www.cancer.gov/types/bone/hp/ewing-treatment-pdq", False),
        ("https://www.cancer.gov/types/bone/patient/ewing-treatment", False),
        ("https://www.cancer.gov/about-cancer/x-pdq", False),
    ],
)
def test_pdq_is_patient_url(url: str, ok: bool) -> None:
    assert nci_pdq.is_patient_pdq_url(url) is ok


def test_pdq_parse_keeps_patient_summary_and_drops_about_section(paths: DataPaths) -> None:
    put_raw(paths, "nci_pdq", PDQ_URL, fixture_bytes("nci_pdq_page.html"))
    put_raw(
        paths,
        "nci_pdq",
        "https://www.cancer.gov/types/bone/patient/retired-pdq",
        fixture_bytes("nci_pdq_page.html"),
        final_url="https://www.cancer.gov/types/bone/something-else",
    )
    docs = list(nci_pdq.parse(paths, _record("nci_pdq")))
    assert [d.doc_id for d in docs] == ["nci_pdq:bone/patient/ewing-treatment-pdq"]
    doc = docs[0]
    text = "\n".join(s.text for s in doc.sections)
    assert doc.title == "Ewing Sarcoma Treatment (PDQ)-Patient Version"
    assert doc.reviewed_on == date(2025, 2, 28)
    assert doc.metadata["cancer_type"] == "bone"
    assert doc.metadata["pdq_version"] == "patient"
    assert "forms in bone or soft tissue" in text
    assert "- Pain or swelling" in text
    assert "Enlarge" not in text
    assert "Health Professional Version" not in text
    assert "Purpose of this summary" not in text


async def test_pdq_fetch_filters_sitemap_to_patient_summaries(paths: DataPaths) -> None:
    sitemap = (
        '<urlset xmlns="x">'
        f"<url><loc>{PDQ_URL}</loc></url>"
        "<url><loc>https://www.cancer.gov/types/bone/hp/ewing-treatment-pdq</loc></url></urlset>"
    )
    routes = {nci_pdq.SITEMAP_URL: httpx.Response(200, text=sitemap), PDQ_URL: _html("nci_pdq_page.html")}
    async with _fetcher(paths, "nci_pdq", routes) as fetcher:
        assert await nci_pdq.fetch(fetcher) == 1


# ---- CDC syndication -----------------------------------------------------------------------------
def _item(item_id: int, source_url: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": item_id,
        "name": "Item",
        "description": "Page description",
        "mediaType": "HTML",
        "language": {"isoCode2": "en"},
        "sourceUrl": source_url,
        "contentUrl": f"https://tools.cdc.gov/api/v2/resources/media/{item_id}/content.html",
        "dateContentReviewed": "2024-05-02T00:00:00Z",
    }
    base.update(overrides)
    return base


def _listing(items: list[dict[str, object]], pages: int = 1) -> bytes:
    return json.dumps({"results": items, "meta": {"pagination": {"totalPages": pages}}}).encode()


def test_cdc_is_wanted_item() -> None:
    assert cdc.is_wanted_item(_item(1, "https://www.cdc.gov/raw-milk/index.html"))
    assert not cdc.is_wanted_item(_item(1, "https://www.cdc.gov/niosh/topics/x.html"))
    assert not cdc.is_wanted_item(_item(1, "https://other.example.org/x"))
    assert not cdc.is_wanted_item(_item(1, "https://www.cdc.gov/x", language={"isoCode2": "es"}))
    assert not cdc.is_wanted_item(_item(1, "https://www.cdc.gov/x", mediaType="Video"))
    assert not cdc.is_wanted_item(_item(1, "https://www.cdc.gov/x", contentUrl=""))
    assert not cdc.is_wanted_item(_item(1, "https://www.cdc.gov/x", language="en"))


def test_cdc_listing_urls_cover_every_page() -> None:
    urls = cdc.listing_urls(3)
    assert len(urls) == 3
    assert urls[0].endswith("pagenum=1")
    assert urls[2].endswith("pagenum=3")


def test_cdc_parse_reads_listing_and_content_pages(paths: DataPaths) -> None:
    patient = _item(101, "https://www.cdc.gov/raw-milk/index.html")
    hcp = _item(
        102, "https://www.cdc.gov/clinical-overview/hcp/index.html", dateContentReviewed="", dateModified=""
    )
    skipped = _item(103, "https://www.cdc.gov/niosh/x.html")
    unfetched = _item(104, "https://www.cdc.gov/unfetched/index.html")
    put_raw(
        paths,
        "cdc",
        cdc.LISTING_URL.format(page=1),
        _listing([patient, hcp, skipped, unfetched]),
        content_type="application/json",
    )
    put_raw(paths, "cdc", str(patient["contentUrl"]), fixture_bytes("cdc_content.html"))
    put_raw(paths, "cdc", str(hcp["contentUrl"]), fixture_bytes("cdc_content_hcp.html"))
    docs = {d.doc_id: d for d in cdc.parse(paths, _record("cdc"))}
    assert set(docs) == {"cdc:101", "cdc:102"}
    milk = docs["cdc:101"]
    text = "\n".join(s.text for s in milk.sections)
    assert milk.title == "Raw Milk"
    assert str(milk.url) == "https://www.cdc.gov/raw-milk/index.html"
    assert milk.reviewed_on == date(2024, 5, 2)
    assert milk.audience == "patient"
    assert milk.reuse_mode.value == "quote_only"
    assert "Pasteurization is crucial" in text
    assert "Salmonella" in text
    assert "Jump to" not in text
    assert "Raw milk and cheese" not in text
    assert docs["cdc:102"].audience == "professional"
    assert docs["cdc:102"].reviewed_on is None


def test_cdc_parse_skips_unreadable_listing_and_missing_content(paths: DataPaths) -> None:
    item = _item(201, "https://www.cdc.gov/a/index.html")
    put_raw(paths, "cdc", cdc.LISTING_URL.format(page=1), b"not json", content_type="application/json")
    put_raw(
        paths, "cdc", cdc.LISTING_URL.format(page=2), b'{"results": "nope"}', content_type="application/json"
    )
    put_raw(paths, "cdc", cdc.LISTING_URL.format(page=3), _listing([item]), content_type="application/json")
    broken = put_raw(paths, "cdc", str(item["contentUrl"]), fixture_bytes("cdc_content.html"))
    broken.unlink()
    assert list(cdc.parse(paths, _record("cdc"))) == []


async def test_cdc_fetch_walks_every_listing_page_then_wanted_content(paths: DataPaths) -> None:
    keep = _item(301, "https://www.cdc.gov/raw-milk/index.html")
    skip = _item(302, "https://www.cdc.gov/niosh/x.html")
    routes = {
        cdc.LISTING_URL.format(page=1): httpx.Response(200, content=_listing([keep], pages=2)),
        cdc.LISTING_URL.format(page=2): httpx.Response(200, content=_listing([skip], pages=2)),
        str(keep["contentUrl"]): _html("cdc_content.html"),
    }
    async with _fetcher(paths, "cdc", routes) as fetcher:
        assert await cdc.fetch(fetcher, paths) == 1
    assert [d.doc_id for d in cdc.parse(paths, _record("cdc"))] == ["cdc:301"]


async def test_cdc_fetch_raises_when_listing_unreachable(paths: DataPaths) -> None:
    async with _fetcher(paths, "cdc", {}) as fetcher:
        with pytest.raises(RuntimeError, match="cannot read the CDC syndication listing"):
            await cdc.fetch(fetcher, paths)


# ---- CDC VIS -------------------------------------------------------------------------------------
def test_vis_urls_dedupes_and_skips_index_and_other_paths() -> None:
    urls = cdc_vis.vis_urls(fixture_bytes("cdc_vis_index.html").decode())
    assert urls == [
        "https://www.cdc.gov/vaccines/hcp/current-vis/hpv.html",
        "https://www.cdc.gov/vaccines/hcp/current-vis/mmr.html",
    ]


def test_vis_parse_keeps_statement_and_drops_menu_and_language_lines(paths: DataPaths) -> None:
    put_raw(paths, "cdc_vis", cdc_vis.INDEX_URL, fixture_bytes("cdc_vis_index.html"))
    put_raw(
        paths,
        "cdc_vis",
        "https://www.cdc.gov/vaccines/hcp/current-vis/hpv.html",
        fixture_bytes("cdc_vis_page.html"),
    )
    put_raw(paths, "cdc_vis", "https://www.cdc.gov/vaccines/other/x.html", fixture_bytes("cdc_vis_page.html"))
    (doc,) = cdc_vis.parse(paths, _record("cdc_vis"))
    text = "\n".join(s.text for s in doc.sections)
    assert doc.doc_id == "cdc_vis:hpv"
    assert doc.content_type is ContentType.VACCINE
    assert doc.title == "HPV (Human Papillomavirus) Vaccine Information Statement"
    assert doc.reviewed_on == date(2021, 8, 6)
    assert "HPV vaccine can prevent infection" in text
    assert "must be dropped" not in text
    assert "On This Page" not in text
    assert "Language" not in text


async def test_vis_fetch_reads_index_then_pages(paths: DataPaths) -> None:
    page = "https://www.cdc.gov/vaccines/hcp/current-vis/hpv.html"
    routes = {
        cdc_vis.INDEX_URL: _html("cdc_vis_index.html"),
        page: _html("cdc_vis_page.html"),
        "https://www.cdc.gov/vaccines/hcp/current-vis/mmr.html": httpx.Response(404),
    }
    async with _fetcher(paths, "cdc_vis", routes) as fetcher:
        assert await cdc_vis.fetch(fetcher) == 1
    async with _fetcher(paths, "cdc_vis", {}) as fetcher:
        with pytest.raises(RuntimeError, match="cannot read"):
            await cdc_vis.fetch(fetcher, limit=1)


# ---- NIH institutes ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("source_id", "path", "wanted"),
    [
        ("nimh", "/health/topics/anxiety-disorders", True),
        ("nimh", "/health/publications/adhd", True),
        ("nimh", "/about/x", False),
        ("nhlbi", "/health/asthma", True),
        ("nhlbi", "/health/anemia/causes", True),
        ("nhlbi", "/health/a/b/c", False),
        ("nei", "/eye-health-information/eye-conditions-and-diseases/amd", True),
        ("nei", "/eye-health-information/news/x", False),
        ("nichd", "/health/topics/adrenalgland/conditioninfo/causes", True),
        ("niams", "/health-topics/acne/basics/symptoms", True),
        ("nccih", "/health/acai", True),
        ("nccih", "/health/providers", False),
        ("nccih", "/health/espanol", False),
    ],
)
def test_institute_url_patterns(source_id: str, path: str, wanted: bool) -> None:
    institute = nih_institutes.institute_for(source_id)
    assert nih_institutes.is_wanted_url(institute, f"https://{institute.host}{path}") is wanted
    assert not nih_institutes.is_wanted_url(institute, f"https://evil.example.org{path}")


def test_institute_registry_and_options() -> None:
    assert set(nih_institutes.MODULE_SOURCE_IDS) == {"nimh", "nhlbi", "nei", "nichd", "niams", "nccih"}
    with pytest.raises(KeyError, match="not an NIH institute"):
        nih_institutes.institute_for("niddk")
    config = nih_institutes.fetch_config_for("nimh")
    assert config.host_rps == {"www.nimh.nih.gov": 0.5}
    assert nih_institutes.build_options_for("nei") == {"min_chars": 300, "strip_repeated_lines": True}
    assert nih_institutes.path_of("https://www.nimh.nih.gov/health/topics/x") == "/health/topics/x"


@pytest.mark.parametrize("source_id", sorted(nih_institutes.MODULE_SOURCE_IDS))
def test_institute_parse_with_each_rule_set(paths: DataPaths, source_id: str) -> None:
    institute = nih_institutes.institute_for(source_id)
    sample_path = {
        "nimh": "/health/topics/generalized-anxiety-disorder",
        "nhlbi": "/health/anxiety",
        "nei": "/eye-health-information/eye-conditions-and-diseases/anxiety",
        "nichd": "/health/topics/anxiety",
        "niams": "/health-topics/anxiety",
        "nccih": "/health/anxiety",
    }[source_id]
    put_raw(paths, source_id, f"https://{institute.host}{sample_path}", fixture_bytes("institute_page.html"))
    put_raw(paths, source_id, f"https://{institute.host}/not/wanted", fixture_bytes("institute_page.html"))
    (doc,) = nih_institutes.parse(paths, _record(source_id))
    text = "\n".join(s.text for s in doc.sections)
    assert doc.title == "Generalized Anxiety Disorder"
    assert doc.metadata["institute"] == source_id
    assert "intense and excessive worry" in text
    assert "- Feeling restless or on edge" in text
    assert "Dropped reference list" not in text
    assert "On this page" not in text


def test_institute_content_type_marks_wellness_paths() -> None:
    assert nih_institutes._content_type("eye-health-information/healthy-vision/x") is ContentType.WELLNESS
    assert nih_institutes._content_type("health/heart-healthy-living/x") is ContentType.WELLNESS
    assert nih_institutes._content_type("health/asthma") is ContentType.CONDITION


async def test_institute_fetch_uses_the_fetchers_source(paths: DataPaths) -> None:
    institute = nih_institutes.institute_for("nccih")
    sitemap = institute.sitemaps[0]
    xml = (
        '<urlset xmlns="x"><url><loc>https://www.nccih.nih.gov/health/acai</loc></url>'
        "<url><loc>https://www.nccih.nih.gov/health/providers</loc></url></urlset>"
    )
    routes = {
        sitemap: httpx.Response(200, text=xml),
        "https://www.nccih.nih.gov/health/acai": _html("institute_page.html"),
    }
    async with _fetcher(paths, "nccih", routes) as fetcher:
        assert await nih_institutes.fetch(fetcher) == 1
