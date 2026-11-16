"""Per-host politeness: at most `rps` requests per second to each host, shared by all coroutines."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping


class HostRateLimiter:
    def __init__(
        self,
        default_rps: float = 1.0,
        host_rps: Mapping[str, float] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        if default_rps <= 0:
            raise ValueError("default_rps must be positive")
        self._default_rps = default_rps
        self._host_rps = dict(host_rps or {})
        self._min_interval_override: dict[str, float] = {}
        self._next_slot: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._clock = clock
        self._sleep = sleep

    def interval_for(self, host: str) -> float:
        rps = self._host_rps.get(host, self._default_rps)
        return max(1.0 / rps, self._min_interval_override.get(host, 0.0))

    def raise_interval(self, host: str, seconds: float) -> None:
        """Honour a robots.txt Crawl-delay: never go faster than the site asks."""
        self._min_interval_override[host] = max(self._min_interval_override.get(host, 0.0), seconds)

    def delay_until(self, host: str, seconds: float) -> None:
        """Back off: no request to this host before `seconds` from now (e.g. after Retry-After)."""
        target = self._clock() + seconds
        self._next_slot[host] = max(self._next_slot.get(host, 0.0), target)

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = self._clock()
            slot = max(self._next_slot.get(host, 0.0), now)
            self._next_slot[host] = slot + self.interval_for(host)
            delay = slot - now
        if delay > 0:
            await self._sleep(delay)
