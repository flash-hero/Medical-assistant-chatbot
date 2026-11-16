"""Per-IP and per-session rate limits on the `limits` library (moving window).

Storage: in-memory in dev/test, Redis in prod (REDIS_URL). Identifiers are hashed so raw IPs never reach Redis
keys or logs.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from limits import RateLimitItem, parse
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string

from core.config import Settings
from core.errors import RateLimited


@dataclass(frozen=True)
class RateRules:
    per_ip: RateLimitItem
    per_session: RateLimitItem
    session_create_per_ip: RateLimitItem


def rules_from_settings(settings: Settings) -> RateRules:
    return RateRules(
        per_ip=parse(f"{settings.rate_per_ip_per_min}/minute"),
        per_session=parse(f"{settings.rate_per_session_per_min}/minute"),
        session_create_per_ip=parse(f"{max(1, settings.rate_per_ip_per_min // 2)}/minute"),
    )


def storage_uri(settings: Settings) -> str:
    if settings.redis_url:
        return "async+" + settings.redis_url if not settings.redis_url.startswith("async+") else settings.redis_url
    return "async+memory://"


def _hash(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:24]


class RateLimiter:
    def __init__(self, uri: str, rules: RateRules, *, clock: Callable[[], float] = time.time) -> None:
        options = {"implementation": "redispy"} if uri.startswith("async+redis") else {}
        self._storage = storage_from_string(uri, **options)
        self._limiter = MovingWindowRateLimiter(self._storage)  # type: ignore[arg-type]
        self._rules = rules
        self._clock = clock

    async def _hit(self, item: RateLimitItem, scope: str, identifier: str) -> None:
        key = _hash(identifier)
        if await self._limiter.hit(item, scope, key):
            return
        stats = await self._limiter.get_window_stats(item, scope, key)
        retry = max(1.0, math.ceil(stats.reset_time - self._clock()))
        raise RateLimited(f"{scope} rate limit", retry_after_s=retry, scope=scope)

    async def check_ip(self, ip: str) -> None:
        await self._hit(self._rules.per_ip, "ip", ip)

    async def check_session(self, session_id: str) -> None:
        await self._hit(self._rules.per_session, "session", session_id)

    async def check_session_create(self, ip: str) -> None:
        await self._hit(self._rules.session_create_per_ip, "session_create", ip)

    async def ping(self) -> bool:
        try:
            return bool(await self._storage.check())  # type: ignore[misc]
        except Exception:  # noqa: BLE001 - readiness probes report, never raise
            return False
