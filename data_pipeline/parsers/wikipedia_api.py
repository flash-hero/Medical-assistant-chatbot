"""MediaWiki Action API helpers shared by the Wikipedia fetcher: URL building and maxlag-aware JSON fetching.

API etiquette (https://www.mediawiki.org/wiki/API:Etiquette): a descriptive User-Agent (the Fetcher sends
one),
requests made serially or with very low concurrency, and the `maxlag` parameter so the client backs off when
the replicas are lagging. A lagged server answers HTTP 200 with an `error` object and a Retry-After header, so
the status code alone does not reveal it: the body is inspected here and the request is repeated after a
pause.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from urllib.parse import quote, urlencode

import structlog

from data_pipeline.fetch.client import Fetcher, FetchFailedError, FetchRefusedError

log = structlog.get_logger(__name__)

API_TEMPLATE = "https://{lang}.wikipedia.org/w/api.php"
MAXLAG_SECONDS = 5
MAX_ATTEMPTS = 6
MAXLAG_PAUSE_S = 5.0
MAXLAG_PAUSE_CAP_S = 60.0

Sleep = Callable[[float], Awaitable[None]]


def api_url(lang: str, params: Mapping[str, str | int]) -> str:
    """Deterministic API URL (sorted parameters) so that the fetch manifest can resume a run."""
    query = {"format": "json", "formatversion": 2, "maxlag": MAXLAG_SECONDS, **params}
    encoded = urlencode(sorted(query.items()), quote_via=quote, safe="|:")
    return f"{API_TEMPLATE.format(lang=lang)}?{encoded}"


def load_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def error_code(data: Mapping[str, object]) -> str | None:
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("code", "unknown"))
    return None


async def fetch_api_json(
    fetcher: Fetcher, url: str, *, sleep: Sleep = asyncio.sleep, max_attempts: int = MAX_ATTEMPTS
) -> dict[str, object] | None:
    """GET an API URL and return its parsed JSON, or None when the origin never gave a usable answer.

    A cached copy that turns out to hold an API error (for instance a `maxlag` body saved by an earlier run)
    is fetched again. The Fetcher already honours HTTP 429/503 and Retry-After; this loop adds the maxlag
    case.
    """
    refresh = False
    for attempt in range(max_attempts):
        try:
            result = await fetcher.fetch(url, robots_exempt=True, refresh=refresh)
        except (FetchFailedError, FetchRefusedError) as exc:
            log.warning("wikipedia_fetch_failed", url=url, error=str(exc))
            return None
        if result.path is None:
            return None
        data = load_json(result.path)
        code = None if data is None else error_code(data)
        if data is not None and code is None:
            return data
        refresh = True
        if code not in (None, "maxlag", "ratelimited"):
            log.warning("wikipedia_api_error", url=url, code=code)
            return None
        await sleep(min(MAXLAG_PAUSE_S * (attempt + 1), MAXLAG_PAUSE_CAP_S))
    log.warning("wikipedia_gave_up", url=url, attempts=max_attempts)
    return None


def pages_of(data: Mapping[str, object]) -> list[dict[str, object]]:
    """The `query.pages` list of a formatversion=2 response ([] when the shape is unexpected)."""
    query = data.get("query")
    pages = query.get("pages") if isinstance(query, dict) else None
    return [p for p in pages if isinstance(p, dict)] if isinstance(pages, list) else []


def title_redirects(data: Mapping[str, object]) -> dict[str, str]:
    """Requested title -> final page title, following the `normalized` and `redirects` lists of a response."""
    query = data.get("query")
    if not isinstance(query, dict):
        return {}
    steps: dict[str, str] = {}
    for key in ("normalized", "redirects"):
        entries = query.get(key)
        for entry in entries if isinstance(entries, list) else []:
            if (
                isinstance(entry, dict)
                and isinstance(entry.get("from"), str)
                and isinstance(entry.get("to"), str)
            ):
                steps[entry["from"]] = entry["to"]
    resolved: dict[str, str] = {}
    for start in steps:
        current, hops = start, 0
        while current in steps and hops < 5:
            current, hops = steps[current], hops + 1
        resolved[start] = current
    return resolved


def langlink_titles(data: Mapping[str, object], lang: str) -> dict[str, str]:
    """Final page title -> its title in `lang`, for every page of a `prop=langlinks` response."""
    out: dict[str, str] = {}
    for page in pages_of(data):
        title = page.get("title")
        links = page.get("langlinks")
        if not isinstance(title, str) or not isinstance(links, list):
            continue
        for link in links:
            if isinstance(link, dict) and link.get("lang") == lang and isinstance(link.get("title"), str):
                out[title] = str(link["title"])
                break
    return out
