"""Single retry policy for upstream calls (SDK retries are disabled so retries are never multiplied)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from app.llm.errors import is_retryable, map_exception
from core.errors import UpstreamRateLimited

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3  # total attempts, including the first
    base_delay_s: float = 0.5
    max_delay_s: float = 4.0
    max_honoured_retry_after_s: float = 8.0  # longer server hints -> fail fast, let the caller degrade

    def delay(self, attempt: int, retry_after_s: float | None, rng: random.Random) -> float:
        if retry_after_s is not None:
            return min(retry_after_s, self.max_honoured_retry_after_s)
        cap = min(self.max_delay_s, self.base_delay_s * (2**attempt))
        return rng.uniform(0, cap)  # full jitter


async def with_retry(
    call: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    rng: random.Random | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    rng = rng or random.Random()  # noqa: S311 - jitter, not crypto
    last: Exception | None = None
    for attempt in range(policy.attempts):
        try:
            return await call()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err = map_exception(exc)
            last = err
            retry_after = err.retry_after_s if isinstance(err, UpstreamRateLimited) else None
            too_long = retry_after is not None and retry_after > policy.max_honoured_retry_after_s
            if attempt == policy.attempts - 1 or not is_retryable(err) or too_long:
                raise err from exc
            await sleep(policy.delay(attempt, retry_after, rng))
    raise AssertionError("unreachable") from last
