"""robots.txt handling on top of urllib.robotparser.

Policy (matches RobotFileParser): 404 and other 4xx except 401/403 mean "no restrictions"; 401/403 mean
"everything disallowed"; a 5xx or network failure means we cannot tell, so we refuse until it is reachable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser


class RobotsUnavailableError(Exception):
    """robots.txt could not be retrieved reliably (5xx / network error)."""


@dataclass(frozen=True)
class RobotsVerdict:
    allowed: bool
    crawl_delay: float | None = None


_ALLOW_ALL = RobotFileParser()
_ALLOW_ALL.parse([])
_DENY_ALL = RobotFileParser()
_DENY_ALL.parse(["User-agent: *", "Disallow: /"])

RobotsLoader = Callable[[str], Awaitable[tuple[int, str]]]


class RobotsCache:
    """Caches one parsed robots.txt per scheme+host. `loader(url)` returns (status, body text)."""

    def __init__(self, user_agent: str, loader: RobotsLoader) -> None:
        self._agent = user_agent
        self._loader = loader
        self._parsers: dict[str, RobotFileParser] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    async def _parser_for(self, origin: str) -> RobotFileParser:
        if origin in self._parsers:
            return self._parsers[origin]
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin in self._parsers:
                return self._parsers[origin]
            status, body = await self._loader(f"{origin}/robots.txt")
            if status in (401, 403):
                parser = _DENY_ALL
            elif 200 <= status < 300:
                parser = RobotFileParser()
                parser.parse(body.splitlines())
            elif 400 <= status < 500:
                parser = _ALLOW_ALL
            else:
                raise RobotsUnavailableError(f"{origin}/robots.txt returned {status}")
            self._parsers[origin] = parser
            return parser

    async def check(self, url: str) -> RobotsVerdict:
        parser = await self._parser_for(self.origin(url))
        delay = parser.crawl_delay(self._agent)
        return RobotsVerdict(
            allowed=parser.can_fetch(self._agent, url), crawl_delay=float(delay) if delay else None
        )
