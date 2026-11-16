"""SpendMeter implementations (core.ports.SpendMeter) and the kill switch.

The daily cap (Settings.daily_spend_cap_usd) is enforced on estimated cost at reservation time (the provider
reserves before each call and settles with real token counts afterwards). Days roll over at 00:00 UTC.
Kill switch: Settings.kill_switch (restart) OR the file {data_root}/KILL_SWITCH (no restart needed).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from core.errors import SpendCapReached

KILL_SWITCH_FILE = "KILL_SWITCH"
_RESERVATION_TTL_S = 15 * 60


def _today() -> date:
    return datetime.now(UTC).date()


class MemorySpendMeter:
    def __init__(self, cap_usd: float, *, today: Callable[[], date] = _today) -> None:
        self._cap = cap_usd
        self._today = today
        self._day = today()
        self._settled = 0.0
        self._reserved: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _roll(self) -> None:
        day = self._today()
        if day != self._day:
            self._day, self._settled, self._reserved = day, 0.0, {}

    async def reserve(self, usd: float) -> str:
        async with self._lock:
            self._roll()
            if self._settled + sum(self._reserved.values()) + max(0.0, usd) > self._cap:
                raise SpendCapReached("daily spend cap reached")
            rid = uuid.uuid4().hex
            self._reserved[rid] = max(0.0, usd)
            return rid

    async def settle(self, reservation_id: str, actual_usd: float) -> None:
        async with self._lock:
            self._roll()
            self._reserved.pop(reservation_id, None)
            self._settled += max(0.0, actual_usd)

    async def spent_today(self) -> float:
        async with self._lock:
            self._roll()
            return self._settled + sum(self._reserved.values())

    @property
    def cap(self) -> float:
        return self._cap


_RESERVE_LUA = """
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
local cap = tonumber(ARGV[1])
local usd = tonumber(ARGV[2])
if spent + usd > cap then return 0 end
redis.call('INCRBYFLOAT', KEYS[1], usd)
redis.call('EXPIRE', KEYS[1], 172800)
redis.call('SET', KEYS[2], usd, 'EX', ARGV[3])
return 1
"""


class RedisSpendMeter:
    """Shared daily bucket for multi-instance deployments (reservation counted immediately, corrected on settle)."""

    def __init__(self, client: Any, cap_usd: float, *, prefix: str = "ausculta:spend:") -> None:
        self._r = client
        self._cap = cap_usd
        self._prefix = prefix
        self._script = client.register_script(_RESERVE_LUA)

    def _day_key(self) -> str:
        return f"{self._prefix}{_today().isoformat()}"

    async def reserve(self, usd: float) -> str:
        rid = uuid.uuid4().hex
        ok = await self._script(
            keys=[self._day_key(), f"{self._prefix}r:{rid}"], args=[self._cap, max(0.0, usd), _RESERVATION_TTL_S]
        )
        if not int(ok):
            raise SpendCapReached("daily spend cap reached")
        return rid

    async def settle(self, reservation_id: str, actual_usd: float) -> None:
        key = f"{self._prefix}r:{reservation_id}"
        reserved = float(await self._r.get(key) or 0.0)
        await self._r.delete(key)
        await self._r.incrbyfloat(self._day_key(), max(0.0, actual_usd) - reserved)

    async def spent_today(self) -> float:
        return float(await self._r.get(self._day_key()) or 0.0)


class KillSwitch:
    """True when the operator paused the assistant (env flag, or the KILL_SWITCH file in the data root)."""

    def __init__(self, env_flag: bool, data_root: Path, *, cache_s: float = 1.0) -> None:
        self._env = env_flag
        self._file = data_root / KILL_SWITCH_FILE
        self._cache_s = cache_s
        self._checked_at = -1e9
        self._file_on = False

    def active(self) -> bool:
        if self._env:
            return True
        now = time.monotonic()
        if now - self._checked_at >= self._cache_s:
            self._file_on = self._file.exists()
            self._checked_at = now
        return self._file_on
