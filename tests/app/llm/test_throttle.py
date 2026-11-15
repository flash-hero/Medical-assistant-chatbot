import pytest

from app.llm.throttle import TokenBucket


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.slept.append(s)
        self.t += s


async def test_bucket_allows_burst_then_paces():
    clock = FakeClock()
    bucket = TokenBucket(60, clock=clock.now, sleep=clock.sleep)  # 1 token / s, capacity 60
    assert await bucket.acquire(60) == 0.0
    waited = await bucket.acquire(30)
    assert waited == pytest.approx(30.0)
    assert clock.t == pytest.approx(30.0)


async def test_bucket_rejects_oversized_request():
    bucket = TokenBucket(10)
    with pytest.raises(ValueError, match="capacity"):
        await bucket.acquire(11)


async def test_bucket_refills_over_time():
    clock = FakeClock()
    bucket = TokenBucket(120, clock=clock.now, sleep=clock.sleep)  # 2 tokens / s
    await bucket.acquire(120)
    clock.t += 10
    assert await bucket.acquire(20) == 0.0
