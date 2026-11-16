"""Polite, resumable async fetcher.

Guarantees, in this order, before any byte is requested:
  1. the URL is not inside an excluded source (registry domain/path rules)  -> ExcludedSourceError
  2. the source itself is fetchable (not excluded / not optional-noncommercial) -> FetchRefused
  3. the URL host belongs to the source's declared domains                       -> FetchRefused
  4. robots.txt allows the path (unless the URL was explicitly published as a download) -> RobotsDisallowedError
Every redirect hop is re-checked with 1-3.  Downloads stream to `<file>.part` and resume with HTTP Range.
Every outcome is appended to raw/{source_id}/_manifest.jsonl.
"""

from __future__ import annotations

import asyncio
import email.utils
import json
import os
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
import structlog

from core.schemas.source import SourceRecord, SourceStatus
from data_pipeline.fetch.manifest import Manifest, ManifestEntry
from data_pipeline.fetch.naming import url_to_relpath
from data_pipeline.fetch.ratelimit import HostRateLimiter
from data_pipeline.fetch.robots import RobotsCache, RobotsUnavailableError
from data_pipeline.paths import DataPaths
from data_pipeline.registry import excluded_source_for_url, url_belongs_to_source
from data_pipeline.storage import sha256_file

USER_AGENT = "AuscultaBot/0.1 (health-information research; non-commercial crawl)"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_REDIRECTS = 5
MAX_RETRY_AFTER_S = 300.0

log = structlog.get_logger(__name__)


class FetchRefusedError(Exception):
    """The request was refused locally; nothing was sent to the origin."""


class ExcludedSourceError(FetchRefusedError):
    """The URL belongs to an excluded source."""


class RobotsDisallowedError(FetchRefusedError):
    """robots.txt disallows this path for our user agent."""


class FetchFailedError(Exception):
    """The origin kept failing after all retries."""


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str = USER_AGENT
    default_rps: float = 1.0
    host_rps: Mapping[str, float] = field(default_factory=dict)
    timeout_s: float = 60.0
    max_retries: int = 5
    backoff_base_s: float = 2.0
    backoff_cap_s: float = 60.0
    respect_robots: bool = True
    max_bytes: int = 4 * 1024**3
    extra_hosts: tuple[str, ...] = ()  # CDN hosts that serve this source's files (still excluded-checked)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    path: Path | None
    sha256: str = ""
    size: int = 0
    from_cache: bool = False
    not_modified: bool = False

    @property
    def ok(self) -> bool:
        return self.path is not None


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    if value.strip().isdigit():
        return min(float(value), MAX_RETRY_AFTER_S)
    parsed = email.utils.parsedate_to_datetime(value) if value else None
    if parsed is None:
        return None
    return max(0.0, min((parsed - datetime.now(UTC)).total_seconds(), MAX_RETRY_AFTER_S))


class Fetcher:
    def __init__(
        self,
        source: SourceRecord,
        paths: DataPaths,
        config: FetchConfig | None = None,
        *,
        registry: Sequence[SourceRecord] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self._config = config or FetchConfig()
        self._registry = registry
        self._sleep = sleep
        self._raw_dir = paths.raw_dir(source.id)
        self._manifest = Manifest(self._raw_dir / "_manifest.jsonl")
        self._limiter = HostRateLimiter(
            self._config.default_rps, self._config.host_rps, clock=clock, sleep=sleep
        )
        self._robots = RobotsCache(self._config.user_agent, self._load_robots)
        self._client = httpx.AsyncClient(
            transport=transport,
            headers={"User-Agent": self._config.user_agent, "Accept": "*/*"},
            timeout=httpx.Timeout(self._config.timeout_s, connect=20.0),
            follow_redirects=False,
        )

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    # ---- guards ---------------------------------------------------------------------------------
    def guard(self, url: str) -> None:
        excluded = excluded_source_for_url(url, self._registry)
        if excluded:
            raise ExcludedSourceError(f"{url} belongs to excluded source {excluded}")
        if self.source.status in (SourceStatus.EXCLUDED, SourceStatus.OPTIONAL_NONCOMMERCIAL):
            raise FetchRefusedError(f"source {self.source.id} has status {self.source.status.value}")
        if not url.lower().startswith(("http://", "https://")):
            raise FetchRefusedError(f"unsupported URL scheme: {url}")
        host_ok = url_belongs_to_source(url, self.source) or any(
            url_belongs_to_source(url, self.source.model_copy(update={"domains": (h,)}))
            for h in self._config.extra_hosts
        )
        if not host_ok:
            raise FetchRefusedError(f"{url} is outside the declared domains of {self.source.id}")

    # ---- robots ---------------------------------------------------------------------------------
    async def _load_robots(self, robots_url: str) -> tuple[int, str]:
        await self._limiter.wait(httpx.URL(robots_url).host)
        try:
            response = await self._client.get(robots_url)
        except httpx.HTTPError as exc:
            raise RobotsUnavailableError(f"{robots_url}: {exc!r}") from exc
        return response.status_code, response.text if response.status_code < 300 else ""

    async def _check_robots(self, url: str) -> None:
        verdict = await self._robots.check(url)
        if verdict.crawl_delay:
            host = httpx.URL(url).host
            self._limiter.raise_interval(host, verdict.crawl_delay)
        if not verdict.allowed:
            raise RobotsDisallowedError(f"robots.txt disallows {url}")

    # ---- public API -----------------------------------------------------------------------------
    async def fetch(
        self,
        url: str,
        *,
        relpath: str | None = None,
        robots_exempt: bool = False,
        refresh: bool = False,
    ) -> FetchResult:
        """Fetch one URL into raw/{source_id}/. `robots_exempt` is only for files the publisher
        explicitly lists as downloads; it is recorded in the manifest."""
        self.guard(url)
        rel = relpath or url_to_relpath(url)
        target = self._raw_dir / rel
        previous = self._manifest.latest(url)
        if previous and previous.ok and target.exists() and not refresh:
            return FetchResult(url, previous.status, target, previous.sha256, previous.bytes, from_cache=True)
        if self._config.respect_robots and not robots_exempt:
            await self._check_robots(url)
        return await self._download(url, target, rel, previous if target.exists() else None, robots_exempt)

    # ---- download with retries ------------------------------------------------------------------
    async def _download(
        self, url: str, target: Path, rel: str, previous: ManifestEntry | None, exempt: bool
    ) -> FetchResult:
        part = target.with_name(target.name + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        last_error = "unknown"
        for attempt in range(self._config.max_retries + 1):
            try:
                outcome = await self._attempt(url, target, part, rel, previous, exempt)
            except (httpx.TransportError, OSError) as exc:
                last_error = repr(exc)
                await self._backoff(url, attempt, None)
                continue
            if isinstance(outcome, FetchResult):
                return outcome
            last_error = f"HTTP {outcome[0]}"
            await self._backoff(url, attempt, outcome[1])
        self._record(url, 599, "", 0, rel="", note=f"gave_up: {last_error}")
        raise FetchFailedError(f"{url}: gave up after {self._config.max_retries + 1} attempts ({last_error})")

    async def _backoff(self, url: str, attempt: int, retry_after: float | None) -> None:
        base = min(self._config.backoff_base_s * (2**attempt), self._config.backoff_cap_s)
        wait = max(retry_after or 0.0, base * (0.5 + random.random() / 2))  # noqa: S311
        self._limiter.delay_until(httpx.URL(url).host, wait)
        await self._sleep(wait)

    async def _attempt(
        self, url: str, target: Path, part: Path, rel: str, previous: ManifestEntry | None, exempt: bool
    ) -> FetchResult | tuple[int, float | None]:
        headers = self._request_headers(part, previous)
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            self.guard(current)
            await self._limiter.wait(httpx.URL(current).host)
            async with self._client.stream("GET", current, headers=headers) as response:
                location = response.headers.get("location")
                if response.status_code in (301, 302, 303, 307, 308) and location:
                    current = urljoin(current, location)
                    continue
                return await self._handle(response, url, target, part, rel, previous, exempt)
        raise FetchFailedError(f"{url}: too many redirects")

    def _request_headers(self, part: Path, previous: ManifestEntry | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        meta = self._read_part_meta(part)
        if part.exists() and part.stat().st_size > 0 and meta.get("resumable"):
            headers["Range"] = f"bytes={part.stat().st_size}-"
            headers["Accept-Encoding"] = "identity"
            if meta.get("etag"):
                headers["If-Range"] = meta["etag"]
        elif previous:
            if previous.etag:
                headers["If-None-Match"] = previous.etag
            if previous.last_modified:
                headers["If-Modified-Since"] = previous.last_modified
        return headers

    @staticmethod
    def _read_part_meta(part: Path) -> dict[str, object]:
        meta_path = part.with_name(part.name + ".meta")
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    async def _handle(
        self,
        response: httpx.Response,
        url: str,
        target: Path,
        part: Path,
        rel: str,
        previous: ManifestEntry | None,
        exempt: bool,
    ) -> FetchResult | tuple[int, float | None]:
        status = response.status_code
        if status in RETRYABLE_STATUS:
            return status, _retry_after_seconds(response.headers.get("retry-after"))
        if status == 304 and previous:
            self._record(url, 304, previous.sha256, previous.bytes, rel, note="not_modified", prior=previous)
            return FetchResult(url, 304, target, previous.sha256, previous.bytes, not_modified=True)
        if status == 416:
            part.unlink(missing_ok=True)
            return status, 0.0
        if status not in (200, 206):
            self._record(url, status, "", 0, rel="", note="client_error")
            return FetchResult(url, status, None)
        size = await self._stream_to_part(response, part)
        digest = await asyncio.to_thread(self._finalise, part, target)
        self._record(
            url, status, digest, size, rel, response=response, note="robots_override" if exempt else ""
        )
        return FetchResult(url, status, target, digest, size)

    async def _stream_to_part(self, response: httpx.Response, part: Path) -> int:
        resuming = response.status_code == 206 and part.exists()
        encoded = bool(response.headers.get("content-encoding"))
        part.with_name(part.name + ".meta").write_text(
            json.dumps({"resumable": not encoded, "etag": response.headers.get("etag", "")}), encoding="utf-8"
        )
        declared = int(response.headers.get("content-length") or 0)
        if declared > self._config.max_bytes:
            raise FetchFailedError(f"{response.url}: {declared} bytes exceeds max_bytes")
        written = part.stat().st_size if resuming else 0
        try:
            with part.open("ab" if resuming else "wb") as handle:
                async for block in response.aiter_bytes(1 << 16):
                    written += len(block)
                    if written > self._config.max_bytes:
                        raise FetchFailedError(f"{response.url}: exceeded max_bytes while streaming")
                    handle.write(block)
        except httpx.TransportError:
            if encoded:
                part.unlink(missing_ok=True)
            raise
        return written

    @staticmethod
    def _finalise(part: Path, target: Path) -> str:
        digest = sha256_file(part)
        os.replace(part, target)
        part.with_name(part.name + ".meta").unlink(missing_ok=True)
        return digest

    def _record(
        self,
        url: str,
        status: int,
        sha: str,
        size: int,
        rel: str,
        *,
        response: httpx.Response | None = None,
        note: str = "",
        prior: ManifestEntry | None = None,
    ) -> None:
        headers = response.headers if response is not None else {}
        entry = ManifestEntry(
            url=url,
            status=status,
            sha256=sha,
            bytes=size,
            fetched_at=datetime.now(UTC).isoformat(),
            final_url=str(response.url) if response is not None else url,
            path=rel,
            etag=headers.get("etag", prior.etag if prior else ""),
            last_modified=headers.get("last-modified", prior.last_modified if prior else ""),
            content_type=headers.get("content-type", prior.content_type if prior else ""),
            note=note,
        )
        self._manifest.append(entry)
        log.info("fetched", source=self.source.id, url=url, status=status, bytes=size, note=note)

    # ---- convenience ----------------------------------------------------------------------------
    async def fetch_text(self, url: str, **kwargs: bool | str) -> str:
        result = await self.fetch(url, **kwargs)  # type: ignore[arg-type]
        if result.path is None:
            raise FetchFailedError(f"{url}: HTTP {result.status}")
        return result.path.read_text(encoding="utf-8", errors="replace")

    async def fetch_many(
        self, urls: Sequence[str], *, concurrency: int = 8, **kwargs: bool
    ) -> list[FetchResult | Exception]:
        gate = asyncio.Semaphore(concurrency)

        async def one(target_url: str) -> FetchResult | Exception:
            async with gate:
                try:
                    return await self.fetch(target_url, **kwargs)
                except (FetchRefusedError, FetchFailedError) as exc:
                    log.warning("fetch_failed", url=target_url, error=str(exc))
                    return exc

        return list(await asyncio.gather(*(one(u) for u in urls)))
