"""Admission control: a global concurrency limit on model-backed turns plus a bounded wait queue.

  - at most `concurrency` turns hold a slot at once
  - at most `queue_max` requests wait for a slot; more are rejected at once (503 + Retry-After)
  - a request that could not get a slot within `wait_s` is also rejected at once: its queue position times the
    observed slot hold time, over `concurrency` slots, is longer than WAIT_MARGIN x `wait_s` (P5-D12: with the
    defaults, 8 slots and 32 queued, a 3x overload never filled the queue, so every excess request waited the
    full 5 s before its 503). Until enough turns have released a slot (cold start) requests simply queue.
  - a waiting request gives up after `wait_s` (503 + Retry-After)

Slots are released on every exit path (normal end, error, cancellation); `held` and `waiting` are exposed
for the leak test and the readiness probe.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from core.errors import Overloaded

RETRY_AFTER_FULL_S = 5.0
HOLD_EWMA_ALPHA = 0.1  # weight of the newest slot hold time (about the last 20 turns)
MIN_HOLD_SAMPLES = 8  # releases needed (at most `concurrency`) before queue positions are judged
WAIT_MARGIN = 0.7  # hold times vary: queue only positions expected to get a slot well within the wait


class AdmissionController:
    def __init__(
        self,
        concurrency: int,
        queue_max: int,
        wait_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self._capacity = concurrency
        self._free = concurrency
        self._queue_max = queue_max
        self._wait_s = wait_s
        self._waiters: list[asyncio.Future[None]] = []
        self._clock = clock
        # grant times of the current holders, oldest first: a release is matched with the oldest grant, which
        # keeps the sum (and so the mean) of the hold times right without knowing which holder released
        self._granted: deque[float] = deque()
        self._hold_s: float | None = None
        self._releases = 0

    @property
    def held(self) -> int:
        return self._capacity - self._free

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    @property
    def capacity(self) -> int:
        return self._capacity

    def expected_wait_s(self, position: int) -> float | None:
        """Seconds until queue position `position` (1 = next) gets a slot when every slot is busy; None while
        too few slots have been released to know the hold time."""
        if self._hold_s is None or self._releases < min(self._capacity, MIN_HOLD_SAMPLES):
            return None
        return position * self._hold_s / self._capacity

    async def acquire(self) -> None:
        if self._free > 0 and not self._waiters:
            self._free -= 1
            self._granted.append(self._clock())
            return
        if len(self._waiters) >= self._queue_max:
            raise Overloaded("admission queue full", retry_after_s=RETRY_AFTER_FULL_S)
        expected = self.expected_wait_s(len(self._waiters) + 1)
        if expected is not None and expected > WAIT_MARGIN * self._wait_s:
            raise Overloaded("admission queue cannot drain in time", retry_after_s=RETRY_AFTER_FULL_S)
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
        now = self._clock()
        while self._waiters:
            fut = self._waiters.pop(0)
            if not fut.done():
                self._note_release(now)
                self._granted.append(now)
                fut.set_result(None)  # hand the slot over directly (free count unchanged)
                return
        if self._free >= self._capacity:
            raise RuntimeError("admission slot released more times than acquired")
        self._note_release(now)
        self._free += 1

    def _note_release(self, now: float) -> None:
        start = self._granted.popleft() if self._granted else now
        hold = max(0.0, now - start)
        previous = hold if self._hold_s is None else self._hold_s
        self._hold_s = previous + HOLD_EWMA_ALPHA * (hold - previous)
        self._releases += 1

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self.acquire()
        try:
            yield
        finally:
            self.release()
