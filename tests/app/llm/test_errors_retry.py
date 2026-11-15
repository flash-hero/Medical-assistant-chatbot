import random

import pytest

from app.llm.errors import classify_rate_limit, is_retryable, map_exception
from app.llm.retry import RetryPolicy, with_retry
from core.errors import (
    UpstreamBadRequest,
    UpstreamBlocked,
    UpstreamRateLimited,
    UpstreamTimeout,
    UpstreamUnavailable,
)


class FakeAPIError(Exception):
    def __init__(self, code, details=""):
        super().__init__(f"{code} {details}")
        self.code = code
        self.details = details


class ReadTimeout(Exception):
    pass


def test_rate_limit_scope_parsing():
    assert classify_rate_limit("Generate content requests per day limit exceeded")[0] == "day"
    assert classify_rate_limit("quota_metric: generate_content_requests_per_minute")[0] == "minute"
    assert classify_rate_limit("free_tier_input_token_count, limit: 0, model: gemini-4-argon")[0] == "day"
    assert classify_rate_limit("'retryDelay': '12s' per minute") == ("minute", 12.0)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (FakeAPIError(429, "requests per minute"), UpstreamRateLimited),
        (FakeAPIError(400, "{'error': {'code': 'safety'}}"), UpstreamBlocked),
        (FakeAPIError(400, "bad field"), UpstreamBadRequest),
        (FakeAPIError(403, "denied"), UpstreamBadRequest),
        (FakeAPIError(503, "overloaded"), UpstreamUnavailable),
        (FakeAPIError(504, "deadline"), UpstreamUnavailable),
        (ReadTimeout(), UpstreamTimeout),
        (TimeoutError(), UpstreamTimeout),
    ],
)
def test_map_exception(exc, expected):
    assert isinstance(map_exception(exc), expected)


def test_retryable_classification():
    assert is_retryable(UpstreamTimeout())
    assert is_retryable(UpstreamRateLimited(scope="minute", retry_after_s=None))
    assert not is_retryable(UpstreamRateLimited(scope="day", retry_after_s=None))
    assert not is_retryable(UpstreamBlocked(reason="safety", stage="prompt"))


async def test_with_retry_retries_transient_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeAPIError(503)
        return "ok"

    async def fake_sleep(s):
        sleeps.append(s)

    assert await with_retry(flaky, RetryPolicy(attempts=3), rng=random.Random(1), sleep=fake_sleep) == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    assert all(0 <= s <= 4.0 for s in sleeps)


async def test_with_retry_does_not_retry_daily_quota_or_blocks():
    calls = {"n": 0}

    async def daily():
        calls["n"] += 1
        raise FakeAPIError(429, "requests per day limit exceeded")

    with pytest.raises(UpstreamRateLimited):
        await with_retry(daily, RetryPolicy(attempts=5))
    assert calls["n"] == 1


async def test_with_retry_fails_fast_on_long_retry_after():
    async def slow_hint():
        raise FakeAPIError(429, "per minute 'retryDelay': '45s'")

    with pytest.raises(UpstreamRateLimited):
        await with_retry(slow_hint, RetryPolicy(attempts=3))
