"""Wikipedia medicine articles in English, French and Arabic via the MediaWiki Action API -> Documents.

Scope: the English articles that WikiProject Medicine rates Top or High importance, plus the French and Arabic
articles they link to through interlanguage links. Text only (plain-text extracts with section structure);
images, infoboxes, tables and references are not ingested.

Licence (read 2026-11-16, https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use section 7): text is
CC BY-SA 4.0 (commercial use allowed). Attribution is satisfied by a hyperlink to the article, whose history
page lists the authors; derivative text must stay under CC BY-SA. Hence trust tier 3 and `paraphrase_ok`
with the share-alike condition carried in the registry.

Access etiquette (https://wikitech.wikimedia.org/wiki/Robot_policy, "Action API rules"): one request at a
time, well below 5 requests per second, `maxlag` on every call, a descriptive User-Agent. robots.txt
disallows /w/ for generic crawlers, but the policy names api.php as the interface bots must use, so API
requests are robots-exempt (recorded in the fetch manifest).

Pipeline: category listing -> interlanguage links in batches of 50 -> one article request per page. Every
response is cached by the Fetcher, so an interrupted run resumes without repeating a request.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, quote, urlsplit

import structlog

from core.schemas.document import Document
from core.schemas.source import ContentType, Language, SourceRecord
from data_pipeline.fetch.client import USER_AGENT, FetchConfig, Fetcher
from data_pipeline.fetch.manifest import Manifest, ManifestEntry
from data_pipeline.parsers.common import build_document
from data_pipeline.parsers.wikipedia_api import (
    api_url,
    fetch_api_json,
    langlink_titles,
    load_json,
    pages_of,
    title_redirects,
)
from data_pipeline.parsers.wikipedia_text import extract_to_sections
from data_pipeline.paths import DataPaths

SOURCE_ID = "wikipedia_medicine"
TARGET_LANGS: tuple[str, ...] = ("fr", "ar")
IMPORTANCE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("top", "Category:Top-importance medicine articles"),
    ("high", "Category:High-importance medicine articles"),
)
LANGLINK_BATCH = 50
CONTACT_ENV = "AUSCULTA_CRAWLER_CONTACT"
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
BUILD_OPTIONS = {"min_chars": 400}
PROGRESS_EVERY = 100
log = structlog.get_logger(__name__)


class ContactRequiredError(RuntimeError):
    """Wikimedia needs contact details in the User-Agent and none were configured."""


def fetch_config_for(_source_id: str = SOURCE_ID) -> FetchConfig:
    """Two requests per second at most (policy limit: 5), serial.

    Wikimedia answers HTTP 403 ("please respect our robot policy") to a User-Agent without contact details
    (https://meta.wikimedia.org/wiki/User-Agent_policy). The contact is the operator's own identity, so it is
    never guessed: set AUSCULTA_CRAWLER_CONTACT to an email address or a URL before fetching.
    """
    contact = os.environ.get(CONTACT_ENV, "").strip()
    if not contact:
        raise ContactRequiredError(
            f"set {CONTACT_ENV} (an email address or URL for the crawler operator) before fetching "
            "Wikipedia: Wikimedia refuses requests whose User-Agent has no contact details"
        )
    agent = f"{USER_AGENT.rstrip(')')}; contact: {contact})"
    return FetchConfig(user_agent=agent, default_rps=2.0, respect_robots=True)


# ---- URL builders ---------------------------------------------------------------------------------
def members_url(category: str, cont: str | None = None) -> str:
    params: dict[str, str | int] = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmnamespace": 1,
        "cmlimit": 500,
    }
    if cont:
        params["cmcontinue"] = cont
    return api_url("en", params)


def langlinks_url(titles: Sequence[str], lang: str) -> str:
    return api_url(
        "en",
        {
            "action": "query",
            "prop": "langlinks",
            "lllang": lang,
            "lllimit": "max",
            "redirects": 1,
            "titles": "|".join(titles),
        },
    )


def article_url(lang: str, title: str) -> str:
    return api_url(
        lang,
        {
            "action": "query",
            "prop": "extracts|info|revisions|pageprops",
            "explaintext": 1,
            "exsectionformat": "wiki",
            "inprop": "url",
            "rvprop": "ids|timestamp",
            "ppprop": "disambiguation",
            "redirects": 1,
            "titles": title,
        },
    )


# ---- fetching ---------------------------------------------------------------------------------------
def talk_to_article(talk_title: str) -> str:
    return talk_title.removeprefix("Talk:").strip()


def _member_titles(data: Mapping[str, object]) -> list[str]:
    query = data.get("query")
    members = query.get("categorymembers") if isinstance(query, dict) else None
    titles = [m.get("title") for m in members if isinstance(m, dict)] if isinstance(members, list) else []
    return [talk_to_article(t) for t in titles if isinstance(t, str) and t.startswith("Talk:")]


def _continuation(data: Mapping[str, object]) -> str | None:
    cont = data.get("continue")
    token = cont.get("cmcontinue") if isinstance(cont, dict) else None
    return token if isinstance(token, str) else None


async def list_english_titles(fetcher: Fetcher) -> dict[str, str]:
    """English article title -> importance ("top" or "high"); an article in both lists counts as top."""
    found: dict[str, str] = {}
    for importance, category in IMPORTANCE_CATEGORIES:
        cont: str | None = None
        while True:
            data = await fetch_api_json(fetcher, members_url(category, cont))
            if data is None:
                raise RuntimeError(f"cannot list {category}")
            for title in _member_titles(data):
                found.setdefault(title, importance)
            cont = _continuation(data)
            if cont is None:
                break
    return found


async def linked_titles(fetcher: Fetcher, titles: Sequence[str], lang: str) -> dict[str, str]:
    """English title -> its title on the `lang` wiki, from batched interlanguage-link queries."""
    out: dict[str, str] = {}
    for start in range(0, len(titles), LANGLINK_BATCH):
        batch = titles[start : start + LANGLINK_BATCH]
        data = await fetch_api_json(fetcher, langlinks_url(batch, lang))
        if data is None:
            log.warning("langlinks_batch_failed", lang=lang, first=batch[0])
            continue
        by_final = langlink_titles(data, lang)
        redirects = title_redirects(data)
        for requested in batch:
            target = by_final.get(redirects.get(requested, requested))
            if target:
                out[requested] = target
    return out


async def fetch_articles(fetcher: Fetcher, lang: str, titles: Sequence[str]) -> int:
    """One request per article, serially. Returns the number of usable responses."""
    ok = 0
    for index, title in enumerate(titles, start=1):
        data = await fetch_api_json(fetcher, article_url(lang, title))
        ok += 1 if data is not None and pages_of(data) else 0
        if index % PROGRESS_EVERY == 0:
            log.info("wikipedia_progress", lang=lang, done=index, total=len(titles), ok=ok)
    return ok


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> int:
    """Download the article set. `limit` caps the English articles (French/Arabic follow from those)."""
    english = list(await list_english_titles(fetcher))
    if limit is not None:
        english = english[:limit]
    total = await fetch_articles(fetcher, "en", english)
    for lang in TARGET_LANGS:
        mapping = await linked_titles(fetcher, english, lang)
        total += await fetch_articles(fetcher, lang, list(dict.fromkeys(mapping.values())))
    return total


# ---- parsing ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RawPage:
    lang: str
    requested_title: str
    entry: ManifestEntry
    page: Mapping[str, object]


def _query_of(entry: ManifestEntry) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(entry.url).query).items() if v}


def _lang_of(entry: ManifestEntry) -> str:
    return (urlsplit(entry.url).hostname or "").split(".")[0]


@dataclass(frozen=True)
class Catalogue:
    """What the listing and interlanguage-link responses say about the fetched articles."""

    importance: dict[str, str]  # English title -> top | high
    english_of: dict[tuple[str, str], str]  # (lang, title) -> English title
    names: dict[str, dict[str, str]]  # English title -> {lang: title}


def _load_catalogue(paths: DataPaths, record: SourceRecord) -> tuple[Catalogue, list[RawPage]]:
    raw_dir = paths.raw_dir(record.id)
    importance: dict[str, str] = {}
    english_of: dict[tuple[str, str], str] = {}
    names: dict[str, dict[str, str]] = {}
    pages: list[RawPage] = []
    for entry in sorted(Manifest(raw_dir / "_manifest.jsonl").entries(), key=lambda e: e.url):
        data = load_json(raw_dir / entry.path) if entry.ok else None
        if data is None or "query" not in data:
            continue
        query = _query_of(entry)
        if query.get("list") == "categorymembers":
            level = "top" if "Top-importance" in query.get("cmtitle", "") else "high"
            for title in _member_titles(data):
                if importance.get(title) != "top":
                    importance[title] = level
        elif "langlinks" in query.get("prop", ""):
            lang = query.get("lllang", "")
            redirects = title_redirects(data)
            for requested in query.get("titles", "").split("|"):
                target = langlink_titles(data, lang).get(redirects.get(requested, requested))
                if target:
                    english_of[(lang, target)] = requested
                    names.setdefault(requested, {})[lang] = target
        elif "extracts" in query.get("prop", ""):
            pages.extend(
                RawPage(_lang_of(entry), query.get("titles", ""), entry, page) for page in pages_of(data)
            )
    return Catalogue(importance, english_of, names), pages


def _revision_date(page: Mapping[str, object]) -> date | None:
    revisions = page.get("revisions")
    stamp = revisions[0].get("timestamp") if isinstance(revisions, list) and revisions else None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).date() if stamp else None
    except ValueError:
        return None


def _is_usable(page: Mapping[str, object]) -> bool:
    props = page.get("pageprops")
    disambiguation = isinstance(props, dict) and "disambiguation" in props
    return not (page.get("missing") or page.get("invalid") or disambiguation) and bool(page.get("extract"))


def _history_url(lang: str, title: str) -> str:
    slug = quote(title.replace(" ", "_"), safe="")
    return f"https://{lang}.wikipedia.org/w/index.php?title={slug}&action=history"


def _entry_time(entry: ManifestEntry) -> datetime:
    try:
        return datetime.fromisoformat(entry.fetched_at)
    except ValueError:
        return datetime.now(UTC)


def page_to_document(raw: RawPage, record: SourceRecord, catalogue: Catalogue) -> Document | None:
    page = raw.page
    if raw.lang not in ("en", *TARGET_LANGS) or not _is_usable(page):
        return None
    title = str(page.get("title") or "").strip()
    url = str(page.get("canonicalurl") or page.get("fullurl") or "")
    sections = extract_to_sections(str(page["extract"]), title, raw.lang) if title else ()
    if not sections or not url:
        return None
    english = (
        title if raw.lang == "en" else catalogue.english_of.get((raw.lang, raw.requested_title), "")
    ) or ""
    others = catalogue.names.get(english, {}) if english else {}
    synonyms = [english, *others.values()] if raw.lang != "en" else list(others.values())
    return build_document(
        record,
        native_id=f"{raw.lang}/{page.get('pageid')}",
        url=url,
        title=title,
        language=Language(raw.lang),
        content_type=ContentType.CONDITION,
        sections=sections,
        retrieved_at=_entry_time(raw.entry),
        synonyms=synonyms,
        reviewed_on=_revision_date(page),
        metadata={
            "wiki_lang": raw.lang,
            "page_id": int(str(page.get("pageid") or 0)),
            "revision_id": int(str(page.get("lastrevid") or 0)),
            "english_title": english,
            "importance": catalogue.importance.get(english, ""),
            "licence_url": LICENCE_URL,
            "history_url": _history_url(raw.lang, title),
        },
    )


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    catalogue, pages = _load_catalogue(paths, record)
    if not pages:
        raise FileNotFoundError(f"no Wikipedia article responses under {paths.raw_dir(record.id)}; run fetch")
    for raw in pages:
        doc = page_to_document(raw, record, catalogue)
        if doc is not None:
            yield doc
