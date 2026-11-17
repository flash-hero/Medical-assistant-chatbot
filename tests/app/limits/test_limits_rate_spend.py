"""Rate limits (moving window), spend meters and the kill switch."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from limits import parse

from app.limits.rate import RateLimiter, RateRules, rules_from_settings, storage_uri
from app.limits.spend import KILL_SWITCH_FILE, KillSwitch, MemorySpendMeter, RedisSpendMeter
from core.errors import RateLimited, SpendCapReached


# ---- rate ----------------------------------------------------------------------------------------
def test_rules_and_storage_from_settings(settings_factory) -> None:
    s = settings_factory(AUSCULTA_RATE_IP_MIN=7, AUSCULTA_RATE_SESSION_MIN=3)
    rules = rules_from_settings(s)
    assert (rules.per_ip.amount, rules.per_session.amount, rules.session_create_per_ip.amount) == (7, 3, 3)
    assert storage_uri(s) == "async+memory://"
    assert storage_uri(settings_factory(REDIS_URL="redis://h:6379/0")) == "async+redis://h:6379/0"
    assert storage_uri(settings_factory(REDIS_URL="async+redis://h:6379/0")) == "async+redis://h:6379/0"


def _limiter(n: int = 2) -> RateLimiter:
    rule = parse(f"{n}/minute")
    return RateLimiter(
        "async+memory://", RateRules(per_ip=rule, per_session=rule, session_create_per_ip=rule)
    )


async def test_ip_limit_raises_with_retry_after() -> None:
    rl = _limiter(2)
    await rl.check_ip("1.2.3.4")
    await rl.check_ip("1.2.3.4")
    with pytest.raises(RateLimited) as err:
        await rl.check_ip("1.2.3.4")
    assert 1 <= err.value.retry_after_s <= 61
    assert err.value.detail["scope"] == "ip"
    await rl.check_ip("5.6.7.8")  # other identifiers are unaffected


async def test_session_and_session_create_scopes_are_independent() -> None:
    rl = _limiter(1)
    await rl.check_session("s1")
    await rl.check_session_create("s1")
    with pytest.raises(RateLimited):
        await rl.check_session("s1")
    with pytest.raises(RateLimited):
        await rl.check_session_create("s1")
    assert await rl.ping() is True


async def test_ping_reports_storage_failure() -> None:
    rl = _limiter(1)

    async def boom() -> bool:
        raise ConnectionError("down")

    rl._storage.check = boom  # type: ignore[method-assign]
    assert await rl.ping() is False


# ---- spend ---------------------------------------------------------------------------------------
async def test_memory_spend_meter_enforces_cap_and_rolls_over() -> None:
    day = [date(2026, 11, 16)]
    meter = MemorySpendMeter(1.0, today=lambda: day[0])
    rid = await meter.reserve(0.6)
    assert await meter.spent_today() == pytest.approx(0.6)
    with pytest.raises(SpendCapReached):
        await meter.reserve(0.5)
    await meter.settle(rid, 0.2)
    assert await meter.spent_today() == pytest.approx(0.2)
    await meter.reserve(0.5)
    await meter.settle("unknown", -1.0)  # negative actuals are clamped
    assert meter.cap == 1.0
    day[0] = date(2026, 11, 17)
    assert await meter.spent_today() == 0.0
    await meter.reserve(-5)  # negative estimates are clamped to 0
    assert await meter.spent_today() == 0.0


class _FakeAsyncRedis:
    """Enough of redis.asyncio for RedisSpendMeter (the Lua script is emulated)."""

    def __init__(self) -> None:
        self.kv: dict[str, Any] = {}

    def register_script(self, _lua: str) -> Any:
        async def script(keys: list[str], args: list[Any]) -> int:
            spent = float(self.kv.get(keys[0], 0.0))
            cap, usd = float(args[0]), float(args[1])
            if spent + usd > cap:
                return 0
            self.kv[keys[0]] = spent + usd
            self.kv[keys[1]] = usd
            return 1

        return script

    async def get(self, key: str) -> Any:
        value = self.kv.get(key)
        return None if value is None else str(value).encode()

    async def delete(self, key: str) -> None:
        self.kv.pop(key, None)

    async def incrbyfloat(self, key: str, amount: float) -> None:
        self.kv[key] = float(self.kv.get(key, 0.0)) + amount


async def test_redis_spend_meter_reserve_settle() -> None:
    r = _FakeAsyncRedis()
    meter = RedisSpendMeter(r, 1.0)
    rid = await meter.reserve(0.7)
    with pytest.raises(SpendCapReached):
        await meter.reserve(0.4)
    await meter.settle(rid, 0.1)
    assert await meter.spent_today() == pytest.approx(0.1)
    await meter.reserve(0.4)
    assert await meter.spent_today() == pytest.approx(0.5)


# ---- kill switch ---------------------------------------------------------------------------------
def test_kill_switch_env_flag(tmp_path: Path) -> None:
    assert KillSwitch(True, tmp_path).active() is True
    assert KillSwitch(False, tmp_path).active() is False


def test_kill_switch_file_is_picked_up_without_restart(tmp_path: Path) -> None:
    ks = KillSwitch(False, tmp_path, cache_s=0.0)
    assert ks.active() is False
    (tmp_path / KILL_SWITCH_FILE).write_text("paused by operator", encoding="utf-8")
    assert ks.active() is True
    (tmp_path / KILL_SWITCH_FILE).unlink()
    assert ks.active() is False


def test_kill_switch_caches_file_checks(tmp_path: Path) -> None:
    ks = KillSwitch(False, tmp_path, cache_s=3600)
    assert ks.active() is False
    (tmp_path / KILL_SWITCH_FILE).write_text("x", encoding="utf-8")
    assert ks.active() is False  # cached
