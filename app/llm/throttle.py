"""Client-side token bucket so bulk embedding stays under the provider's per-minute quota.

Free tier (measured 2026-11-15): `embed_content_free_tier_requests` = 100 per minute, counted PER TEXT
(a 100-text batch consumes 100). We budget 90/min to leave headroom for live query embeddings.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self,
        rate_per_min: float,
        *,
        capacity: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        if rate_per_min <= 0:
            raise ValueError("rate_per_min must be > 0")
        self._rate_s = rate_per_min / 60.0
        self._capacity = capacity if capacity is not None else rate_per_min
        self._tokens = self._capacity
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> float:
        return self._capacity

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate_s)
        self._last = now

    async def acquire(self, tokens: float = 1.0) -> float:
        """Wait until `tokens` are available; returns seconds waited. Requests larger than capacity are
        rejected (split them first)."""
        if tokens > self._capacity:
            raise ValueError(f"cannot acquire {tokens} tokens; capacity is {self._capacity}")
        waited = 0.0
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                deficit = (tokens - self._tokens) / self._rate_s
                await self._sleep(deficit)  # type: ignore[misc]
                waited += deficit
