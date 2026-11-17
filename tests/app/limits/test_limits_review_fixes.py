"""Review S1 / S7 / P16 in the rate limiter: client keys by IPv6 /64, a global session-creation cap, a separate
safety bucket, daily form caps, and storage outages reported as a dependency error (503), not a crash."""

from __future__ import annotations

import pytest
from limits import parse
from limits.errors import StorageError

from app.limits.rate import RateLimiter, RateRules, client_key, rules_from_settings
from core.errors import DependencyUnavailable, RateLimited


@pytest.mark.parametrize(
    ("ip", "key"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("2001:DB8:1:2::ffff", "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
        ("not-an-ip", "not-an-ip"),
    ],
)
def test_client_key_groups_ipv6_by_slash64(ip: str, key: str) -> None:
    assert client_key(ip) == key


def _limiter(**changes: str) -> RateLimiter:
    rule = parse("100/minute")
    rules = RateRules(per_ip=rule, per_session=rule, session_create_per_ip=rule)
    from dataclasses import replace

    return RateLimiter("async+memory://", replace(rules, **{k: parse(v) for k, v in changes.items()}))


async def test_ip_checks_use_the_client_key() -> None:
    rl = _limiter(per_ip="1/minute")
    await rl.check_ip("2001:db8:1:2::1")
    with pytest.raises(RateLimited):
        await rl.check_ip("2001:db8:1:2::2")
    await rl.check_ip("2001:db8:1:9::1")


async def test_global_session_creation_cap_spans_clients() -> None:
    rl = _limiter(session_create_global="2/minute")
    await rl.check_session_create("198.51.100.1")
    await rl.check_session_create("198.51.100.2")
    with pytest.raises(RateLimited) as err:
        await rl.check_session_create("198.51.100.3")
    assert err.value.detail["scope"] == "session_create_global"


async def test_safety_bucket_is_separate_from_the_ip_bucket() -> None:
    rl = _limiter(per_ip="1/minute", safety_per_ip="2/minute")
    await rl.check_ip("198.51.100.1")
    with pytest.raises(RateLimited):
        await rl.check_ip("198.51.100.1")
    await rl.check_safety("198.51.100.1")
    await rl.check_safety("198.51.100.1")
    with pytest.raises(RateLimited) as err:
        await rl.check_safety("198.51.100.1")
    assert err.value.detail["scope"] == "safety"


async def test_form_caps_check_session_then_ip_then_global() -> None:
    rl = _limiter(appointments_per_session="1/day", appointments_per_ip="2/day", appointments_global="3/day")
    await rl.check_appointment("s1", "198.51.100.1")
    with pytest.raises(RateLimited) as err:
        await rl.check_appointment("s1", "198.51.100.1")
    assert err.value.detail["scope"] == "appointment_session"
    await rl.check_appointment("s2", "198.51.100.1")
    with pytest.raises(RateLimited) as err:
        await rl.check_appointment("s3", "198.51.100.1")
    assert err.value.detail["scope"] == "appointment_ip"
    await rl.check_appointment("s4", "198.51.100.2")
    with pytest.raises(RateLimited) as err:
        await rl.check_appointment("s5", "198.51.100.3")
    assert err.value.detail["scope"] == "appointment_global"
    assert err.value.retry_after_s > 60  # a daily window


async def test_feedback_caps() -> None:
    rl = _limiter(feedback_per_session="1/day")
    await rl.check_feedback("s1", "198.51.100.1")
    with pytest.raises(RateLimited):
        await rl.check_feedback("s1", "198.51.100.1")
    await rl.check_feedback("s2", "198.51.100.1")


def test_default_rules_from_settings(settings_factory) -> None:
    rules = rules_from_settings(settings_factory())
    assert rules.safety_per_ip.amount >= 30
    assert rules.appointments_per_session.amount == 3
    assert rules.session_create_global.amount >= rules.session_create_per_ip.amount


async def test_storage_errors_become_dependency_unavailable() -> None:
    rl = _limiter()

    async def broken(*_a, **_k):
        raise StorageError(ConnectionError("redis down"))

    rl._limiter.hit = broken  # type: ignore[method-assign]
    with pytest.raises(DependencyUnavailable):
        await rl.check_ip("198.51.100.1")
    rl._fixed.hit = broken  # type: ignore[method-assign]
    with pytest.raises(DependencyUnavailable):
        await rl.check_appointment("s1", "198.51.100.1")


async def test_redis_uri_wraps_storage_exceptions() -> None:
    rl = RateLimiter("async+redis://127.0.0.1:1/0", rules_from_settings_like())
    assert rl._storage.wrap_exceptions is True


def rules_from_settings_like() -> RateRules:
    rule = parse("1/minute")
    return RateRules(per_ip=rule, per_session=rule, session_create_per_ip=rule)
