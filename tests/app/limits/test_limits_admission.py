"""Admission control: concurrency slots, bounded queue, wait timeout, release on every exit path."""

from __future__ import annotations

import asyncio

import pytest

from app.limits.admission import AdmissionController
from core.errors import Overloaded


def test_rejects_invalid_capacity() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        AdmissionController(0, 1, 1.0)


async def test_slots_are_granted_up_to_capacity_then_queued_in_order() -> None:
    ac = AdmissionController(2, 4, 5.0)
    await ac.acquire()
    await ac.acquire()
    assert (ac.held, ac.waiting, ac.capacity) == (2, 0, 2)
    order: list[int] = []

    async def waiter(i: int) -> None:
        await ac.acquire()
        order.append(i)

    tasks = [asyncio.create_task(waiter(i)) for i in range(3)]
    await asyncio.sleep(0)
    assert ac.waiting == 3
    for _ in range(3):
        ac.release()
        await asyncio.sleep(0)
    await asyncio.gather(*tasks)
    assert order == [0, 1, 2]
    assert ac.held == 2  # slots were handed over, not freed
    ac.release()
    ac.release()
    assert ac.held == 0


async def test_full_queue_is_rejected_immediately() -> None:
    ac = AdmissionController(1, 0, 5.0)
    await ac.acquire()
    with pytest.raises(Overloaded) as err:
        await ac.acquire()
    assert err.value.retry_after_s == 5.0
    assert err.value.http_status == 503


async def test_wait_timeout_raises_overloaded_and_leaves_no_waiter() -> None:
    ac = AdmissionController(1, 2, 0.01)
    await ac.acquire()
    with pytest.raises(Overloaded) as err:
        await ac.acquire()
    assert err.value.retry_after_s >= 1.0
    assert ac.waiting == 0
    ac.release()
    assert ac.held == 0


async def test_cancelled_waiter_leaves_queue() -> None:
    ac = AdmissionController(1, 2, 5.0)
    await ac.acquire()
    task = asyncio.create_task(ac.acquire())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ac.waiting == 0
    ac.release()
    assert ac.held == 0


async def test_waiter_cancelled_after_being_handed_a_slot_passes_it_on() -> None:
    ac = AdmissionController(1, 2, 5.0)
    await ac.acquire()
    task = asyncio.create_task(ac.acquire())
    await asyncio.sleep(0)
    ac.release()  # hands the slot to the waiter's future
    task.cancel()  # ...but the waiter is cancelled before it resumes
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ac.held == 0
    assert ac.waiting == 0


async def test_slot_context_releases_on_error_and_cancellation() -> None:
    ac = AdmissionController(1, 1, 5.0)
    with pytest.raises(RuntimeError):
        async with ac.slot():
            raise RuntimeError("boom")
    assert ac.held == 0

    started = asyncio.Event()

    async def hold() -> None:
        async with ac.slot():
            started.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(hold())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ac.held == 0


def test_double_release_is_detected() -> None:
    ac = AdmissionController(1, 1, 1.0)
    with pytest.raises(RuntimeError, match="more times"):
        ac.release()


async def test_many_cancel_cycles_leak_nothing() -> None:
    ac = AdmissionController(2, 8, 5.0)
    for _ in range(300):
        tasks = [asyncio.create_task(_hold(ac)) for _ in range(5)]
        await asyncio.sleep(0)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert (ac.held, ac.waiting) == (0, 0)


async def _hold(ac: AdmissionController) -> None:
    async with ac.slot():
        await asyncio.sleep(1)
