from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from core.schemas.source import SourceRecord, SourceStatus
from data_pipeline.fetch.client import (
    USER_AGENT,
    ExcludedSourceError,
    FetchConfig,
    Fetcher,
    FetchFailedError,
    FetchRefusedError,
    RobotsDisallowedError,
)
from data_pipeline.fetch.manifest import Manifest
from data_pipeline.fetch.naming import url_to_relpath
from data_pipeline.fetch.ratelimit import HostRateLimiter
from data_pipeline.paths import DataPaths
from data_pipeline.registry import load_registry

HOST = "https://a.example.org"


def _source(domains: list[str] | None = None, status: str = "active") -> SourceRecord:
    return SourceRecord.model_validate(
        {
            "id": "src_a",
            "name": "A",
            "publisher": "P",
            "homepage": f"{HOST}/",
            "status": status,
            "wave": 1,
            "trust_tier": 1,
            "reuse_mode": "paraphrase_ok",
            "languages": ["en"],
            "content_types": ["condition"],
            "domains": domains if domains is not None else ["a.example.org"],
            "license": {
                "id": "pd",
                "name": "pd",
                "evidence_url": f"{HOST}/t",
                "commercial_use": "yes",
                "attribution": "A",
                "verified_on": "2026-11-15",
                "verified_by": "data-agent",
            },
        }
    )


class Recorder:
    """MockTransport handler that records requests and serves canned responses."""

    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = str(request.url)
        route = self.routes.get(key)
        if route is None:
            return httpx.Response(404, text="nope")
        if isinstance(route, list):
            return route.pop(0) if len(route) > 1 else route[0]
        return route

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


async def _no_sleep(_: float) -> None:
    return None


def _fetcher(tmp_path: Path, handler: Recorder, **cfg: object) -> Fetcher:
    config = FetchConfig(backoff_base_s=0.0, default_rps=1000.0, **cfg)  # type: ignore[arg-type]
    return Fetcher(
        _source(),
        DataPaths(tmp_path).ensure(),
        config,
        registry=load_registry(),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )


ROBOTS_OK = httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")


async def test_fetch_writes_file_manifest_and_sends_user_agent(tmp_path: Path) -> None:
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK, f"{HOST}/page.html": httpx.Response(200, text="hello")})
    async with _fetcher(tmp_path, handler) as fetcher:
        result = await fetcher.fetch(f"{HOST}/page.html")
    assert result.ok and result.path is not None
    assert result.path.read_text(encoding="utf-8") == "hello"
    assert result.sha256 and result.size == 5
    assert all(r.headers["user-agent"] == USER_AGENT for r in handler.requests)
    assert "@" not in USER_AGENT
    rows = [json.loads(x) for x in (tmp_path / "raw" / "src_a" / "_manifest.jsonl").read_text("utf-8").splitlines()]
    assert rows[0]["url"] == f"{HOST}/page.html" and rows[0]["status"] == 200 and rows[0]["bytes"] == 5


async def test_second_fetch_is_served_from_cache_without_a_request(tmp_path: Path) -> None:
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK, f"{HOST}/p": httpx.Response(200, text="x")})
    async with _fetcher(tmp_path, handler) as fetcher:
        await fetcher.fetch(f"{HOST}/p")
        before = len(handler.requests)
        again = await fetcher.fetch(f"{HOST}/p")
    assert again.from_cache and len(handler.requests) == before


async def test_refresh_sends_conditional_headers_and_handles_304(tmp_path: Path) -> None:
    first = httpx.Response(200, text="v1", headers={"ETag": '"abc"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"})
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK, f"{HOST}/p": [first, httpx.Response(304)]})
    async with _fetcher(tmp_path, handler) as fetcher:
        await fetcher.fetch(f"{HOST}/p")
        result = await fetcher.fetch(f"{HOST}/p", refresh=True)
    conditional = handler.requests[-1]
    assert conditional.headers["if-none-match"] == '"abc"'
    assert conditional.headers["if-modified-since"].startswith("Mon, 01 Jan 2024")
    assert result.not_modified and result.path is not None and result.path.read_text("utf-8") == "v1"


async def test_robots_disallow_is_respected_and_nothing_is_requested(tmp_path: Path) -> None:
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK, f"{HOST}/private/x": httpx.Response(200, text="secret")})
    async with _fetcher(tmp_path, handler) as fetcher:
        with pytest.raises(RobotsDisallowedError):
            await fetcher.fetch(f"{HOST}/private/x")
    assert "/private/x" not in handler.paths()


async def test_robots_exempt_is_recorded_in_manifest(tmp_path: Path) -> None:
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK, f"{HOST}/private/x": httpx.Response(200, text="data")})
    async with _fetcher(tmp_path, handler) as fetcher:
        result = await fetcher.fetch(f"{HOST}/private/x", robots_exempt=True)
        assert result.ok
        assert fetcher.manifest.latest(f"{HOST}/private/x").note == "robots_override"  # type: ignore[union-attr]


async def test_robots_5xx_blocks_fetching(tmp_path: Path) -> None:
    from data_pipeline.fetch.robots import RobotsUnavailableError

    handler = Recorder({f"{HOST}/robots.txt": httpx.Response(503), f"{HOST}/p": httpx.Response(200, text="x")})
    async with _fetcher(tmp_path, handler) as fetcher:
        with pytest.raises(RobotsUnavailableError):
            await fetcher.fetch(f"{HOST}/p")


async def test_robots_404_allows_everything_and_403_denies(tmp_path: Path) -> None:
    ok = Recorder({f"{HOST}/p": httpx.Response(200, text="x")})
    async with _fetcher(tmp_path, ok) as fetcher:
        assert (await fetcher.fetch(f"{HOST}/p")).ok
    denied = Recorder({f"{HOST}/robots.txt": httpx.Response(403), f"{HOST}/q": httpx.Response(200, text="x")})
    async with _fetcher(tmp_path / "two", denied) as fetcher:
        with pytest.raises(RobotsDisallowedError):
            await fetcher.fetch(f"{HOST}/q")


async def test_excluded_url_is_refused_before_any_request(tmp_path: Path) -> None:
    handler = Recorder({})
    async with _fetcher(tmp_path, handler) as fetcher:
        with pytest.raises(ExcludedSourceError):
            await fetcher.fetch("https://www.mayoclinic.org/diseases")
    assert handler.requests == []


async def test_excluded_path_inside_allowed_host_is_refused(tmp_path: Path) -> None:
    source = _source(domains=["medlineplus.gov"])
    handler = Recorder({})
    fetcher = Fetcher(source, DataPaths(tmp_path).ensure(), registry=load_registry(), transport=httpx.MockTransport(handler))
    async with fetcher:
        with pytest.raises(ExcludedSourceError):
            await fetcher.fetch("https://medlineplus.gov/ency/article/1.htm")
        with pytest.raises(ExcludedSourceError):
            await fetcher.fetch("https://medlineplus.gov/druginfo/meds/a1.html")
    assert handler.requests == []


async def test_host_outside_declared_domains_and_bad_scheme_are_refused(tmp_path: Path) -> None:
    handler = Recorder({})
    async with _fetcher(tmp_path, handler) as fetcher:
        with pytest.raises(FetchRefusedError):
            await fetcher.fetch("https://other.example.com/x")
        with pytest.raises(FetchRefusedError):
            await fetcher.fetch("file:///etc/passwd")
    assert handler.requests == []


@pytest.mark.parametrize("status", ["excluded", "optional_noncommercial"])
async def test_non_fetchable_source_status_is_refused(tmp_path: Path, status: str) -> None:
    handler = Recorder({})
    fetcher = Fetcher(
        _source().model_copy(update={"status": SourceStatus(status)}),
        DataPaths(tmp_path).ensure(),
        registry=[],
        transport=httpx.MockTransport(handler),
    )
    async with fetcher:
        with pytest.raises(FetchRefusedError):
            await fetcher.fetch(f"{HOST}/p")
    assert handler.requests == []


async def test_redirect_to_excluded_host_is_blocked(tmp_path: Path) -> None:
    routes = {
        f"{HOST}/robots.txt": ROBOTS_OK,
        f"{HOST}/go": httpx.Response(302, headers={"Location": "https://www.webmd.com/x"}),
    }
    handler = Recorder(routes)
    async with _fetcher(tmp_path, handler) as fetcher:
        with pytest.raises(ExcludedSourceError):
            await fetcher.fetch(f"{HOST}/go")
    assert "www.webmd.com" not in {r.url.host for r in handler.requests}


async def test_redirect_within_source_is_followed(tmp_path: Path) -> None:
    routes = {
        f"{HOST}/robots.txt": ROBOTS_OK,
        f"{HOST}/old": httpx.Response(301, headers={"Location": "/new"}),
        f"{HOST}/new": httpx.Response(200, text="moved"),
    }
    async with _fetcher(tmp_path, Recorder(routes)) as fetcher:
        result = await fetcher.fetch(f"{HOST}/old")
    assert result.path is not None and result.path.read_text("utf-8") == "moved"


async def test_retries_on_429_then_succeeds(tmp_path: Path) -> None:
    routes = {
        f"{HOST}/robots.txt": ROBOTS_OK,
        f"{HOST}/p": [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(503), httpx.Response(200, text="ok")],
    }
    handler = Recorder(routes)
    async with _fetcher(tmp_path, handler) as fetcher:
        result = await fetcher.fetch(f"{HOST}/p")
    assert result.ok and handler.paths().count("/p") == 3


async def test_gives_up_after_max_retries_and_records_failure(tmp_path: Path) -> None:
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK, f"{HOST}/p": httpx.Response(500)})
    async with _fetcher(tmp_path, handler, max_retries=2) as fetcher:
        with pytest.raises(FetchFailedError):
            await fetcher.fetch(f"{HOST}/p")
        assert fetcher.manifest.latest(f"{HOST}/p").status == 599  # type: ignore[union-attr]
    assert handler.paths().count("/p") == 3


async def test_404_is_recorded_without_raising(tmp_path: Path) -> None:
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK})
    async with _fetcher(tmp_path, handler) as fetcher:
        result = await fetcher.fetch(f"{HOST}/missing")
    assert not result.ok and result.status == 404


async def test_transport_error_is_retried(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, text="fine")

    fetcher = Fetcher(
        _source(),
        DataPaths(tmp_path).ensure(),
        FetchConfig(backoff_base_s=0.0, default_rps=1000.0),
        registry=load_registry(),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )
    async with fetcher:
        assert (await fetcher.fetch(f"{HOST}/p")).ok
    assert calls["n"] == 2


async def test_resume_uses_range_and_appends(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if "range" in request.headers:
            assert request.headers["range"] == "bytes=5-"
            return httpx.Response(206, content=b"world", headers={"Content-Range": "bytes 5-9/10"})
        return httpx.Response(200, content=b"helloworld")

    paths = DataPaths(tmp_path).ensure()
    rel = url_to_relpath(f"{HOST}/big.bin")
    part = paths.raw_dir("src_a") / (rel + ".part")
    part.parent.mkdir(parents=True)
    part.write_bytes(b"hello")
    part.with_name(part.name + ".meta").write_text(json.dumps({"resumable": True, "etag": ""}), encoding="utf-8")
    fetcher = Fetcher(_source(), paths, FetchConfig(default_rps=1000.0), registry=load_registry(), transport=httpx.MockTransport(handler))
    async with fetcher:
        result = await fetcher.fetch(f"{HOST}/big.bin")
    assert result.path is not None and result.path.read_bytes() == b"helloworld"
    assert not part.exists()


async def test_max_bytes_is_enforced(tmp_path: Path) -> None:
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK, f"{HOST}/big": httpx.Response(200, content=b"x" * 100)})
    async with _fetcher(tmp_path, handler, max_bytes=10) as fetcher:
        with pytest.raises(FetchFailedError):
            await fetcher.fetch(f"{HOST}/big")


async def test_fetch_many_collects_failures(tmp_path: Path) -> None:
    handler = Recorder({f"{HOST}/robots.txt": ROBOTS_OK, f"{HOST}/a": httpx.Response(200, text="a")})
    async with _fetcher(tmp_path, handler) as fetcher:
        results = await fetcher.fetch_many([f"{HOST}/a", "https://www.webmd.com/x", f"{HOST}/private/z"], concurrency=2)
        text = await fetcher.fetch_text(f"{HOST}/a")
    assert results[0].ok  # type: ignore[union-attr]
    assert isinstance(results[1], ExcludedSourceError)
    assert isinstance(results[2], RobotsDisallowedError)
    assert text == "a"


async def test_fetch_text_raises_on_http_error(tmp_path: Path) -> None:
    async with _fetcher(tmp_path, Recorder({})) as fetcher:
        with pytest.raises(FetchFailedError):
            await fetcher.fetch_text(f"{HOST}/nothing")


def test_manifest_keeps_last_good_entry(tmp_path: Path) -> None:
    from data_pipeline.fetch.manifest import ManifestEntry

    manifest = Manifest(tmp_path / "m.jsonl")
    good = ManifestEntry(url="u", status=200, sha256="s", bytes=1, fetched_at="t", path="p")
    manifest.append(good)
    manifest.append(ManifestEntry(url="u", status=500, sha256="", bytes=0, fetched_at="t2"))
    assert Manifest(tmp_path / "m.jsonl").latest("u") == good
    assert len(manifest.entries()) == 1


async def test_rate_limiter_spaces_requests_per_host() -> None:
    now = {"t": 0.0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["t"] += seconds

    limiter = HostRateLimiter(1.0, {"fast.example": 10.0}, clock=lambda: now["t"], sleep=fake_sleep)
    for _ in range(3):
        await limiter.wait("slow.example")
    assert sleeps == [pytest.approx(1.0), pytest.approx(1.0)]
    sleeps.clear()
    await limiter.wait("fast.example")
    await limiter.wait("fast.example")
    assert sleeps == [pytest.approx(0.1)]
    limiter.raise_interval("slow.example", 5.0)
    assert limiter.interval_for("slow.example") == 5.0
    limiter.delay_until("other.example", 3.0)
    sleeps.clear()
    await limiter.wait("other.example")
    assert sleeps == [pytest.approx(3.0)]
    with pytest.raises(ValueError, match="positive"):
        HostRateLimiter(0)


def test_url_to_relpath_is_stable_and_safe() -> None:
    assert url_to_relpath("https://medlineplus.gov/xml/mplus_topics_2026-11-13.xml") == "medlineplus.gov/xml/mplus_topics_2026-11-13.xml"
    assert url_to_relpath("https://a.org/").endswith("/index")
    assert url_to_relpath("https://a.org/dir/") == "a.org/dir/index"
    q1 = url_to_relpath("https://a.org/search?q=1")
    q2 = url_to_relpath("https://a.org/search?q=2")
    assert q1 != q2
    long = url_to_relpath("https://a.org/" + "x" * 400 + ".html")
    assert len(long) < 160 and ":" not in long and "?" not in long
    assert url_to_relpath("https://a.org/a b/c%20d.html") == "a.org/a_b/c_d.html"
