"""Wikipedia source: extract -> sections, API helpers, mock-MediaWiki fetch, recorded-response parse."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from dp_helpers import FIXTURES

from core.schemas.source import SourceRecord
from data_pipeline.catalog import run_parse
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.parsers import wikipedia, wikipedia_api, wikipedia_text
from data_pipeline.paths import DataPaths
from data_pipeline.registry import get_source

WIKI = FIXTURES / "wikipedia"


def _fx(name: str) -> bytes:
    return (WIKI / name).read_bytes()


def _json(name: str) -> dict[str, object]:
    return json.loads(_fx(name))


def _ok(name: str) -> httpx.Response:
    return httpx.Response(200, content=_fx(name), headers={"content-type": "application/json; charset=utf-8"})


async def _no_sleep(_: float) -> None:
    return None


def _record() -> SourceRecord:
    record = get_source("wikipedia_medicine")
    assert record is not None
    return record


def _fetcher(paths: DataPaths, routes: dict[str, list[httpx.Response] | httpx.Response]) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        route = routes.get(str(request.url))
        if route is None:
            return httpx.Response(404, text="nope")
        if isinstance(route, list):
            return route.pop(0) if len(route) > 1 else route[0]
        return route

    return Fetcher(
        _record(),
        paths,
        FetchConfig(default_rps=1000.0, backoff_base_s=0.0, max_retries=1),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )


ENGLISH = ["Asthma", "Addiction", "Medicine", "Cancer", "Gout"]


def _routes() -> dict[str, list[httpx.Response] | httpx.Response]:
    top, high = (c for _, c in wikipedia.IMPORTANCE_CATEGORIES)
    return {
        wikipedia.members_url(top): _ok("members_top_p1.json"),
        wikipedia.members_url(top, "page|abc|2"): _ok("members_top_p2.json"),
        wikipedia.members_url(high): _ok("members_high.json"),
        wikipedia.langlinks_url(ENGLISH, "ar"): _ok("langlinks_ar.json"),
        wikipedia.langlinks_url(ENGLISH, "fr"): _ok("langlinks_fr.json"),
        wikipedia.article_url("en", "Asthma"): _ok("article_en_asthma.json"),
        wikipedia.article_url("en", "Medicine"): _ok("article_disambiguation.json"),
        wikipedia.article_url("en", "Gout"): _ok("article_missing.json"),
        wikipedia.article_url("fr", "Asthme"): _ok("article_fr_asthme.json"),
        wikipedia.article_url("ar", "ربو"): _ok("article_ar_rabw.json"),
    }


# ---- text -> sections ----------------------------------------------------------------------------
def test_sections_keep_hierarchy_and_drop_reference_blocks_in_every_language() -> None:
    en = "Intro line one.\nIntro line two.\n\n== Causes ==\nGenes.\n=== Risk factors ===\nSmoke.\n== See also ==\nX\n=== Sub ===\nY\n== Treatment ==\nInhaler."  # noqa: E501
    sections = wikipedia_text.extract_to_sections(en, "Asthma", "en")
    assert [s.heading_path for s in sections] == [
        ("Asthma",),
        ("Asthma", "Causes"),
        ("Asthma", "Causes", "Risk factors"),
        ("Asthma", "Treatment"),
    ]
    assert sections[0].text == "Intro line one.\n\nIntro line two."
    assert [s.kind for s in sections] == ["summary", "causes", "causes", "treatment"]
    assert [s.section_id for s in sections] == ["s0", "s1", "s2", "s3"]


def test_french_and_arabic_reference_sections_are_dropped_and_kinds_are_localised() -> None:
    fr = wikipedia_text.extract_to_sections(
        "Texte.\n== Symptômes ==\nToux.\n== Notes et références ==\nN1\n== Pronostic ==\nBon.", "Asthme", "fr"
    )
    assert [(s.heading_path[-1], s.kind) for s in fr] == [
        ("Asthme", "summary"),
        ("Symptômes", "symptoms"),
        ("Pronostic", "prognosis"),
    ]
    ar = wikipedia_text.extract_to_sections(
        "نص.\n== المراجع ==\nم1\n== العلاج ==\nدواء.\n== وصلات خارجية ==\nرابط", "ربو", "ar"
    )
    assert [(s.heading_path[-1], s.kind) for s in ar] == [("ربو", "summary"), ("العلاج", "treatment")]


def test_sections_edge_cases() -> None:
    assert wikipedia_text.extract_to_sections("", "T", "en") == ()
    assert wikipedia_text.extract_to_sections("== Empty ==\n\n== Also ==", "T", "en") == ()
    unknown = wikipedia_text.extract_to_sections("A.\n== Whatever ==\nB.", "T", "de")
    assert [s.kind for s in unknown] == ["summary", None]
    crlf = wikipedia_text.extract_to_sections("A.\r\n== Causes ==\r\nB.", "T", "en")
    assert [s.text for s in crlf] == ["A.", "B."]


# ---- API helpers ---------------------------------------------------------------------------------
def test_api_url_is_deterministic_and_carries_maxlag() -> None:
    a = wikipedia_api.api_url("fr", {"b": "x y", "a": 1})
    b = wikipedia_api.api_url("fr", {"a": 1, "b": "x y"})
    assert a == b
    assert a.startswith("https://fr.wikipedia.org/w/api.php?")
    assert "maxlag=5" in a
    assert "x%20y" in a


def test_title_redirects_follow_normalisation_then_redirect() -> None:
    data = {
        "query": {
            "normalized": [{"from": "gout (disease)", "to": "Gout (disease)"}],
            "redirects": [{"from": "Gout (disease)", "to": "Gout"}],
        }
    }
    assert wikipedia_api.title_redirects(data)["gout (disease)"] == "Gout"
    assert wikipedia_api.title_redirects({}) == {}
    assert wikipedia_api.title_redirects({"query": {"redirects": [{"from": 1}, "x"]}}) == {}


def test_langlink_titles_and_pages_of_ignore_malformed_shapes() -> None:
    data = _json("langlinks_ar.json")
    assert wikipedia_api.langlink_titles(data, "ar") == {"Asthma": "ربو", "Gout": "نقرس"}
    assert wikipedia_api.langlink_titles(data, "fr") == {}
    assert wikipedia_api.pages_of({"query": {"pages": "x"}}) == []
    assert wikipedia_api.pages_of({}) == []
    assert wikipedia_api.error_code({"error": {"code": "maxlag"}}) == "maxlag"
    assert wikipedia_api.error_code({"error": "weird"}) is None


async def test_fetch_api_json_retries_a_lagged_response_then_succeeds(paths: DataPaths) -> None:
    url = wikipedia.article_url("en", "Asthma")
    pauses: list[float] = []

    async def record_sleep(seconds: float) -> None:
        pauses.append(seconds)

    async with _fetcher(paths, {url: [_ok("error_maxlag.json"), _ok("article_en_asthma.json")]}) as fetcher:
        data = await wikipedia_api.fetch_api_json(fetcher, url, sleep=record_sleep)
    assert data is not None
    assert wikipedia_api.pages_of(data)[0]["title"] == "Asthma"
    assert pauses == [wikipedia_api.MAXLAG_PAUSE_S]


async def test_fetch_api_json_gives_up_on_persistent_lag_and_on_other_errors(paths: DataPaths) -> None:
    lagged = wikipedia.article_url("en", "A")
    bad = wikipedia.article_url("en", "B")
    gone = wikipedia.article_url("en", "C")
    routes = {lagged: _ok("error_maxlag.json"), bad: _ok("error_other.json")}
    async with _fetcher(paths, routes) as fetcher:
        assert await wikipedia_api.fetch_api_json(fetcher, lagged, sleep=_no_sleep, max_attempts=2) is None
        assert await wikipedia_api.fetch_api_json(fetcher, bad, sleep=_no_sleep) is None
        assert await wikipedia_api.fetch_api_json(fetcher, gone, sleep=_no_sleep) is None


async def test_fetch_api_json_returns_none_for_refused_urls(paths: DataPaths) -> None:
    async with _fetcher(paths, {}) as fetcher:
        assert await wikipedia_api.fetch_api_json(fetcher, "https://example.org/w/api.php") is None


# ---- fetch ---------------------------------------------------------------------------------------
def test_fetch_config_requires_contact_details_and_never_invents_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(wikipedia.CONTACT_ENV, raising=False)
    with pytest.raises(wikipedia.ContactRequiredError, match=wikipedia.CONTACT_ENV):
        wikipedia.fetch_config_for()
    monkeypatch.setenv(wikipedia.CONTACT_ENV, "ops@example.org")
    config = wikipedia.fetch_config_for("wikipedia_medicine")
    assert config.user_agent.startswith("AuscultaBot/")
    assert config.user_agent.endswith("contact: ops@example.org)")
    assert config.default_rps <= 5


async def test_list_english_titles_follows_continuation_and_prefers_top(paths: DataPaths) -> None:
    async with _fetcher(paths, _routes()) as fetcher:
        found = await wikipedia.list_english_titles(fetcher)
    assert found == {
        "Asthma": "top",
        "Addiction": "top",
        "Medicine": "top",
        "Cancer": "top",
        "Gout": "high",
    }


async def test_list_english_titles_raises_when_a_category_cannot_be_read(paths: DataPaths) -> None:
    async with _fetcher(paths, {}) as fetcher:
        with pytest.raises(RuntimeError, match="cannot list"):
            await wikipedia.list_english_titles(fetcher)


async def test_linked_titles_batches_and_resolves_redirects(paths: DataPaths) -> None:
    batch = ["asthma", "Gout (disease)", "Cancer"]
    routes = {wikipedia.langlinks_url(batch, "ar"): _ok("langlinks_ar.json")}
    async with _fetcher(paths, routes) as fetcher:
        mapping = await wikipedia.linked_titles(fetcher, batch, "ar")
        missing = await wikipedia.linked_titles(fetcher, ["Unmapped"], "ar")
    assert mapping == {"asthma": "ربو", "Gout (disease)": "نقرس"}
    assert missing == {}


async def test_fetch_downloads_every_language_and_resumes_from_the_cache(paths: DataPaths) -> None:
    async with _fetcher(paths, _routes()) as fetcher:
        first = await wikipedia.fetch(fetcher, paths)
    # English Asthma, French Asthme, Arabic ربو are usable; Medicine is a disambiguation page that still
    # counts
    # as a response; Gout is a missing page and Addiction/Cancer answer 404.
    assert first == 5
    calls: list[str] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500)

    async with Fetcher(
        _record(),
        paths,
        FetchConfig(default_rps=1000.0, max_retries=0),
        transport=httpx.MockTransport(refuse),
        sleep=_no_sleep,
    ) as cached:
        again = await wikipedia.fetch(cached, paths)
    assert again == first
    retried = ("Addiction", "Cancer", "%D9%86%D9%82%D8%B1%D8%B3")  # the earlier 404s are asked again
    assert calls
    assert all(any(title in c for title in retried) for c in calls)


async def test_fetch_limit_caps_english_articles_and_their_translations(paths: DataPaths) -> None:
    top, high = (c for _, c in wikipedia.IMPORTANCE_CATEGORIES)
    routes = _routes()
    routes[wikipedia.langlinks_url(["Asthma"], "ar")] = _ok("langlinks_ar.json")
    routes[wikipedia.langlinks_url(["Asthma"], "fr")] = _ok("langlinks_fr.json")
    assert top
    assert high
    async with _fetcher(paths, routes) as fetcher:
        assert await wikipedia.fetch(fetcher, paths, limit=1) == 3


# ---- parse ---------------------------------------------------------------------------------------
async def _fetched(paths: DataPaths) -> None:
    async with _fetcher(paths, _routes()) as fetcher:
        await wikipedia.fetch(fetcher, paths)


async def test_parse_builds_documents_in_three_languages_with_cross_language_synonyms(
    paths: DataPaths,
) -> None:
    await _fetched(paths)
    docs = {d.language.value: d for d in wikipedia.parse(paths, _record())}
    assert set(docs) == {"en", "fr", "ar"}
    en, fr, ar = docs["en"], docs["fr"], docs["ar"]
    assert en.doc_id == "wikipedia_medicine:en/44905"
    assert str(en.url) == "https://en.wikipedia.org/wiki/Asthma"
    assert fr.doc_id == "wikipedia_medicine:fr/1111"
    assert ar.doc_id == "wikipedia_medicine:ar/2222"
    assert en.reviewed_on == date(2026, 11, 13)
    assert en.trust_tier == 3
    assert en.reuse_mode.value == "paraphrase_ok"
    assert en.license_id == "CC-BY-SA-4.0"
    assert set(en.synonyms) == {"Asthme", "ربو"}
    assert set(fr.synonyms) == {"Asthma", "ربو"}
    assert set(ar.synonyms) == {"Asthma", "Asthme"}
    assert en.metadata["importance"] == "top"
    assert fr.metadata["english_title"] == "Asthma"
    assert ar.metadata["importance"] == "top"
    assert (
        ar.metadata["history_url"]
        == "https://ar.wikipedia.org/w/index.php?title=%D8%B1%D8%A8%D9%88&action=history"
    )
    assert en.metadata["licence_url"] == "https://creativecommons.org/licenses/by-sa/4.0/"
    for doc in docs.values():
        text = "\n".join(s.text for s in doc.sections)
        assert "Liens externes" not in text
        assert "exemple.invalid" not in text
        assert "example.invalid" not in text
        assert not any(h in ("References", "External links") for s in doc.sections for h in s.heading_path)


async def test_parse_raises_without_any_article_response(paths: DataPaths) -> None:
    with pytest.raises(FileNotFoundError, match="run fetch"):
        list(wikipedia.parse(paths, _record()))


async def test_full_build_through_the_catalog_writes_a_ready_corpus(paths: DataPaths) -> None:
    await _fetched(paths)
    report = run_parse("wikipedia_medicine", paths)
    assert report.kept == 3
    assert report.quarantined == 0
    assert paths.ready_file("wikipedia_medicine").exists()
    languages = {
        json.loads(line)["language"]
        for line in paths.normalized_file("wikipedia_medicine").read_text(encoding="utf-8").splitlines()
    }
    assert languages == {"en", "fr", "ar"}


def test_page_to_document_skips_unusable_pages() -> None:
    record = _record()
    catalogue = wikipedia.Catalogue({}, {}, {})
    entry = wikipedia.ManifestEntry(url="u", status=200, sha256="", bytes=0, fetched_at="bad-date", path="p")

    def page(name: str) -> dict[str, object]:
        return wikipedia_api.pages_of(_json(name))[0]

    for fixture in ("article_disambiguation.json", "article_missing.json"):
        assert (
            wikipedia.page_to_document(wikipedia.RawPage("en", "x", entry, page(fixture)), record, catalogue)
            is None
        )
    unknown_language = wikipedia.RawPage("de", "x", entry, page("article_en_asthma.json"))
    assert wikipedia.page_to_document(unknown_language, record, catalogue) is None
    no_headings = {**page("article_en_asthma.json"), "extract": "== Only ==\n"}
    assert (
        wikipedia.page_to_document(wikipedia.RawPage("en", "x", entry, no_headings), record, catalogue)
        is None
    )
    ok = wikipedia.page_to_document(
        wikipedia.RawPage("en", "x", entry, page("article_en_asthma.json")), record, catalogue
    )
    assert ok is not None
    assert ok.retrieved_at.year >= 2026  # an unparsable fetched_at falls back to now
    assert ok.metadata.get("importance") is None
    bad_revision = {**page("article_en_asthma.json"), "revisions": [{"timestamp": "not-a-date"}]}
    again = wikipedia.page_to_document(wikipedia.RawPage("en", "x", entry, bad_revision), record, catalogue)
    assert again is not None
    assert again.reviewed_on is None
