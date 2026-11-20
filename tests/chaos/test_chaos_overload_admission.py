"""P5-D12 regression: under overload, admission refuses at once a request that could not get a slot within
`queue_wait_s`, instead of queueing it until the wait times out (503 after the full wait).

Before the fix, with the production defaults (8 slots, 32 queued, 5 s wait) and 3x the slots in clients, the
queue never filled, so no request was refused at once: every 503 came after the full 5 s wait (simulation in
docs/progress/p5.md: p50 5,039 ms, p95 5,213 ms, 0 of 398 within 200 ms).
"""

from __future__ import annotations

import asyncio
import math
import random
import time

import pytest

from app.limits.admission import MIN_HOLD_SAMPLES, WAIT_MARGIN, AdmissionController
from core.errors import Overloaded


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def _warm(ac: AdmissionController, clock: FakeClock, *, hold_s: float, turns: int) -> None:
    """`turns` sequential turns of `hold_s` each, so the controller knows the hold time."""
    for _ in range(turns):
        await ac.acquire()
        clock.now += hold_s
        ac.release()


async def test_a_queue_position_that_cannot_drain_in_time_is_refused_at_once() -> None:
    clock = FakeClock()
    ac = AdmissionController(2, 10, 1.5, clock=clock)
    await _warm(ac, clock, hold_s=2.0, turns=MIN_HOLD_SAMPLES)
    assert ac.expected_wait_s(1) == pytest.approx(1.0)  # 2 slots, 2 s per turn: one slot frees every second
    assert pytest.approx(1.05) == WAIT_MARGIN * 1.5
    await ac.acquire()
    await ac.acquire()
    first = asyncio.create_task(ac.acquire())  # position 1: about 1 s, well within the 1.5 s wait -> queued
    await asyncio.sleep(0)
    assert ac.waiting == 1
    with pytest.raises(Overloaded) as err:  # position 2: about 2 s > 1.5 s -> refused now, not after 1.5 s
        await ac.acquire()
    assert err.value.http_status == 503
    assert err.value.retry_after_s == 5.0
    assert "drain" in str(err.value)
    assert ac.waiting == 1
    ac.release()  # the queued request gets its slot
    await first
    for _ in range(2):
        ac.release()
    assert (ac.held, ac.waiting) == (0, 0)


async def test_cold_start_queues_as_before() -> None:
    """Without enough released slots the hold time is unknown: requests queue (bounded by queue_max)."""
    clock = FakeClock()
    ac = AdmissionController(2, 10, 1.5, clock=clock)
    await _warm(ac, clock, hold_s=30.0, turns=1)  # one long turn is not enough history
    assert ac.expected_wait_s(5) is None
    await ac.acquire()
    await ac.acquire()
    waiters = [asyncio.create_task(ac.acquire()) for _ in range(5)]
    await asyncio.sleep(0)
    assert ac.waiting == 5
    for w in waiters:
        w.cancel()
    await asyncio.gather(*waiters, return_exceptions=True)
    assert ac.waiting == 0


async def test_hold_time_follows_the_turns_whoever_releases_first() -> None:
    """Releases are matched with the oldest grant: the mean hold time stays right when turns of different
    lengths finish out of order."""
    clock = FakeClock()
    ac = AdmissionController(4, 0, 1.0, clock=clock)
    for _ in range(10):
        for _ in range(4):
            await ac.acquire()
        clock.now += 1.0
        ac.release()  # the short turn finishes first...
        clock.now += 2.0
        for _ in range(3):
            ac.release()  # ...the three others 2 s later: true mean hold = (1 + 3 + 3 + 3) / 4 = 2.5 s
    expected = ac.expected_wait_s(4)
    assert expected is not None
    assert expected == pytest.approx(2.5, rel=0.25)


async def test_overload_rejections_are_fast_when_the_queue_is_longer_than_it_can_drain() -> None:
    """5x the slots in clients that retry soon after a 503; the queue (4x the slots) is longer than what the
    slots can serve within the wait (about 5 positions at 0.2 s per turn on 2 slots). After the warm-up no 503
    may take anywhere near the wait. Before the fix: queue positions 6-8 waited the full 0.6 s, then 503."""
    slots, queue_max, wait_s, hold_s = 2, 8, 0.6, 0.2
    ac = AdmissionController(slots, queue_max, wait_s)
    rng = random.Random(7)
    warmup_end = time.perf_counter() + 1.0
    stop = warmup_end + 2.0
    rejections: list[float] = []
    served = 0

    async def client() -> None:
        nonlocal served
        await asyncio.sleep(rng.uniform(0.0, hold_s))  # clients do not arrive in lockstep
        while time.perf_counter() < stop:
            t0 = time.perf_counter()
            try:
                async with ac.slot():
                    await asyncio.sleep(hold_s * math.exp(rng.gauss(0.0, 0.2)))
                served += 1
            except Overloaded:
                if t0 >= warmup_end:
                    rejections.append(time.perf_counter() - t0)
                await asyncio.sleep(0.05)

    await asyncio.gather(*(client() for _ in range(5 * slots)))
    assert served > 0
    assert rejections, "the overload must produce rejections"
    assert max(rejections) < wait_s / 2
    assert (ac.held, ac.waiting) == (0, 0)
