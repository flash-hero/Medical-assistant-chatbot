"""Rate limits on the `limits` library.

Per-minute rules use a moving window; the daily form caps use fixed windows (cheap for large counts).
Storage: in-memory in dev/test, Redis in prod (REDIS_URL). Identifiers are hashed so raw IPs never reach Redis
keys or logs. Clients are keyed by IPv4 address or IPv6 /64 (`client_key`), because one IPv6 subscriber
usually holds a whole /64 (review S1). A storage outage is a DependencyUnavailable (503), never a 500 (P16).

Scopes: ip, session, session_create (per client), session_create_global, safety (model-free emergency /
self-harm turns: a separate, generous bucket so the safety template is never rate-limited away by ordinary
traffic), appointment_{session,ip,global} and feedback_{session,ip,global} (review S7).
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from limits import RateLimitItem, parse
from limits.aio.strategies import FixedWindowRateLimiter, MovingWindowRateLimiter
from limits.errors import StorageError
from limits.storage import storage_from_string

from core.config import Settings
from core.errors import DependencyUnavailable, RateLimited

# Defaults of the caps that have no Settings field yet (core/config.py is owned by the lead).
SESSION_CREATE_GLOBAL_PER_MIN = 300
SAFETY_PER_IP_PER_MIN = 60
APPOINTMENTS_PER_SESSION = 3
APPOINTMENTS_PER_IP_PER_DAY = 10
APPOINTMENTS_GLOBAL_PER_DAY = 500
FEEDBACK_PER_SESSION = 40
FEEDBACK_PER_IP_PER_DAY = 200
FEEDBACK_GLOBAL_PER_DAY = 5000
GLOBAL = "global"


def _rule(text: str) -> Callable[[], RateLimitItem]:
    return lambda: parse(text)


@dataclass(frozen=True)
class RateRules:
    per_ip: RateLimitItem
    per_session: RateLimitItem
    session_create_per_ip: RateLimitItem
    session_create_global: RateLimitItem = field(
        default_factory=_rule(f"{SESSION_CREATE_GLOBAL_PER_MIN}/minute")
    )
    safety_per_ip: RateLimitItem = field(default_factory=_rule(f"{SAFETY_PER_IP_PER_MIN}/minute"))
    appointments_per_session: RateLimitItem = field(default_factory=_rule(f"{APPOINTMENTS_PER_SESSION}/day"))
    appointments_per_ip: RateLimitItem = field(default_factory=_rule(f"{APPOINTMENTS_PER_IP_PER_DAY}/day"))
    appointments_global: RateLimitItem = field(default_factory=_rule(f"{APPOINTMENTS_GLOBAL_PER_DAY}/day"))
    feedback_per_session: RateLimitItem = field(default_factory=_rule(f"{FEEDBACK_PER_SESSION}/day"))
    feedback_per_ip: RateLimitItem = field(default_factory=_rule(f"{FEEDBACK_PER_IP_PER_DAY}/day"))
    feedback_global: RateLimitItem = field(default_factory=_rule(f"{FEEDBACK_GLOBAL_PER_DAY}/day"))


def rules_from_settings(settings: Settings) -> RateRules:
    per_create = max(1, settings.rate_per_ip_per_min // 2)
    return RateRules(
        per_ip=parse(f"{settings.rate_per_ip_per_min}/minute"),
        per_session=parse(f"{settings.rate_per_session_per_min}/minute"),
        session_create_per_ip=parse(f"{per_create}/minute"),
        session_create_global=parse(f"{max(per_create, SESSION_CREATE_GLOBAL_PER_MIN)}/minute"),
    )


def storage_uri(settings: Settings) -> str:
    if settings.redis_url:
        return (
            "async+" + settings.redis_url
            if not settings.redis_url.startswith("async+")
            else settings.redis_url
        )
    return "async+memory://"


def client_key(ip: str) -> str:
    """Rate-limit identity of a client address: the IPv4 address (also for IPv4-mapped IPv6) or the IPv6 /64."""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.IPv6Network((addr, 64), strict=False))
    return str(addr)


def _hash(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:24]


class RateLimiter:
    def __init__(self, uri: str, rules: RateRules, *, clock: Callable[[], float] = time.time) -> None:
        options = {"implementation": "redispy"} if uri.startswith("async+redis") else {}
        self._storage = storage_from_string(uri, wrap_exceptions=True, **options)
        self._limiter = MovingWindowRateLimiter(self._storage)
        self._fixed = FixedWindowRateLimiter(self._storage)
        self._rules = rules
        self._clock = clock

    async def _hit(self, item: RateLimitItem, scope: str, identifier: str, *, fixed: bool = False) -> None:
        limiter = self._fixed if fixed else self._limiter
        key = _hash(identifier)
        try:
            if await limiter.hit(item, scope, key):
                return
            stats = await limiter.get_window_stats(item, scope, key)
        except StorageError as exc:
            raise DependencyUnavailable("rate limiter unavailable") from exc
        retry = max(1.0, math.ceil(stats.reset_time - self._clock()))
        raise RateLimited(f"{scope} rate limit", retry_after_s=retry, scope=scope)

    async def check_ip(self, ip: str) -> None:
        await self._hit(self._rules.per_ip, "ip", client_key(ip))

    async def check_session(self, session_id: str) -> None:
        await self._hit(self._rules.per_session, "session", session_id)

    async def check_session_create(self, ip: str) -> None:
        await self._hit(self._rules.session_create_per_ip, "session_create", client_key(ip))
        await self._hit(self._rules.session_create_global, "session_create_global", GLOBAL)

    async def check_safety(self, ip: str) -> None:
        await self._hit(self._rules.safety_per_ip, "safety", client_key(ip))

    async def check_appointment(self, session_id: str, ip: str) -> None:
        r = self._rules
        await self._hit(r.appointments_per_session, "appointment_session", session_id, fixed=True)
        await self._hit(r.appointments_per_ip, "appointment_ip", client_key(ip), fixed=True)
        await self._hit(r.appointments_global, "appointment_global", GLOBAL, fixed=True)

    async def check_feedback(self, session_id: str, ip: str) -> None:
        r = self._rules
        await self._hit(r.feedback_per_session, "feedback_session", session_id, fixed=True)
        await self._hit(r.feedback_per_ip, "feedback_ip", client_key(ip), fixed=True)
        await self._hit(r.feedback_global, "feedback_global", GLOBAL, fixed=True)

    async def ping(self) -> bool:
        try:
            return bool(await self._storage.check())  # type: ignore[misc]
        except Exception:
            return False
