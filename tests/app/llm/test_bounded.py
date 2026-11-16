import asyncio

import pytest

from app.llm.gemini_provider import _bounded


async def test_bounded_returns_value_and_times_out():
    async def quick():
        return 42

    assert await _bounded(quick(), 1.0) == 42
    with pytest.raises(TimeoutError):
        await _bounded(asyncio.sleep(1.0), 0.01)


async def test_outer_cancel_is_never_swallowed_even_when_inner_finishes_same_tick():
    """Regression: asyncio.wait_for on 3.11 could swallow this cancel."""
    for _ in range(200):

        async def inner():
            return "done"

        async def runner():
            await _bounded(inner(), 5.0)
            await asyncio.sleep(10)  # must never be reached after cancel

        task = asyncio.create_task(runner())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
