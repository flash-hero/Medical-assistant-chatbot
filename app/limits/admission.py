"""Admission control: a global concurrency limit on model-backed turns plus a bounded wait queue.

  - at most `concurrency` turns hold a slot at once
  - at most `queue_max` requests wait for a slot; more are rejected at once (503 + Retry-After)
  - a waiting request gives up after `wait_s` (503 + Retry-After)

Slots are released on every exit path (normal end, error, cancellation); `held` and `waiting` are exposed
for the leak test and the readiness probe.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.errors import Overloaded

RETRY_AFTER_FULL_S = 5.0


class AdmissionController:
    def __init__(self, concurrency: int, queue_max: int, wait_s: float) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self._capacity = concurrency
        self._free = concurrency
        self._queue_max = queue_max
        self._wait_s = wait_s
        self._waiters: list[asyncio.Future[None]] = []

    @property
    def held(self) -> int:
        return self._capacity - self._free

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    @property
    def capacity(self) -> int:
        return self._capacity

    async def acquire(self) -> None:
        if self._free > 0 and not self._waiters:
            self._free -= 1
            return
        if len(self._waiters) >= self._queue_max:
            raise Overloaded("admission queue full", retry_after_s=RETRY_AFTER_FULL_S)
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        try:
            async with asyncio.timeout(self._wait_s):
                await fut
        except TimeoutError as exc:
            self._abandon(fut)
            raise Overloaded("admission wait timed out", retry_after_s=max(1.0, self._wait_s)) from exc
        except BaseException:
            self._abandon(fut)
            raise

    def _abandon(self, fut: asyncio.Future[None]) -> None:
        """A waiter leaves (timeout / cancel). If it had already been handed a slot, pass the slot on."""
        if fut in self._waiters:
            self._waiters.remove(fut)
            return
        if fut.done() and not fut.cancelled():
            self.release()

    def release(self) -> None:
        while self._waiters:
            fut = self._waiters.pop(0)
            if not fut.done():
                fut.set_result(None)  # hand the slot over directly (free count unchanged)
                return
        if self._free >= self._capacity:
            raise RuntimeError("admission slot released more times than acquired")
        self._free += 1

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self.acquire()
        try:
            yield
        finally:
            self.release()
