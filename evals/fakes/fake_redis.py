"""In-process fake of the redis.asyncio client subset the API uses (no server, deterministic, single loop).

  r = FakeRedis()                      # bytes values like redis-py's default (decode_responses=False)
  r = FakeRedis(clock=lambda: t[0])    # injectable clock for TTL tests
  r.fail = ConnectionError("down")     # every command raises (dependency-outage tests)

Supported: strings (get/set NX EX/delete/incr/decr/incrbyfloat/expire/ttl), hashes (hset/hgetall/hincrby),
sets (sadd/smembers), lists (rpush/ltrim/lrange), ping, pipeline(transaction=True) and register_script.
Lua scripts cannot run here: register_script() returns a callable that runs a Python emulation registered for
that exact script source in KNOWN_SCRIPTS (the API's lock-release script). Commands queued in a pipeline run
back to back on execute() without yielding to the event loop, which is exactly MULTI/EXEC atomicity for
asyncio callers.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

ScriptFn = Callable[["FakeRedis", Sequence[str], Sequence[Any]], Any]


def _b(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, float):
        return repr(value).encode("ascii")
    return str(value).encode("utf-8")


def _release_if_owner(r: FakeRedis, keys: Sequence[str], args: Sequence[Any]) -> int:
    """Emulates app.api.gate.RELEASE_LOCK_LUA: delete KEYS[1] only when it still holds ARGV[1]."""
    if r._raw_get(keys[0]) == _b(args[0]):
        r._delete(keys[0])
        return 1
    return 0


def known_scripts() -> dict[str, ScriptFn]:
    from app.api.gate import RELEASE_LOCK_LUA

    return {RELEASE_LOCK_LUA: _release_if_owner}


@dataclass
class _Entry:
    value: Any
    expires_at: float | None = None


class _Script:
    def __init__(self, redis: FakeRedis, source: str) -> None:
        self._redis = redis
        self._source = source

    async def __call__(self, keys: Sequence[str] = (), args: Sequence[Any] = ()) -> Any:
        self._redis._check()
        fn = self._redis.scripts.get(self._source)
        if fn is None:
            raise NotImplementedError("FakeRedis has no emulation for this Lua script")
        return fn(self._redis, list(keys), list(args))


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._queue: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., FakePipeline]:
        if not hasattr(self._redis, f"_cmd_{name}"):
            raise AttributeError(name)

        def queue(*args: Any, **kwargs: Any) -> FakePipeline:
            self._queue.append((name, args, kwargs))
            return self

        return queue

    async def execute(self) -> list[Any]:
        self._redis._check()
        out = [getattr(self._redis, f"_cmd_{n}")(*a, **k) for n, a, k in self._queue]
        self._queue.clear()
        return out

    async def __aenter__(self) -> FakePipeline:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._queue.clear()


@dataclass
class FakeRedis:
    clock: Callable[[], float] = time.monotonic
    fail: Exception | None = None
    data: dict[str, _Entry] = field(default_factory=dict)
    scripts: dict[str, ScriptFn] = field(default_factory=known_scripts)
    commands: int = 0
    closed: bool = False

    # ---- plumbing --------------------------------------------------------------------------------
    def _check(self) -> None:
        self.commands += 1
        if self.fail is not None:
            raise self.fail

    def _live(self, key: str) -> _Entry | None:
        entry = self.data.get(key)
        if entry is not None and entry.expires_at is not None and self.clock() >= entry.expires_at:
            del self.data[key]
            return None
        return entry

    def _raw_get(self, key: str) -> Any:
        entry = self._live(key)
        return None if entry is None else entry.value

    def _delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0

    def _container(self, key: str, kind: type) -> Any:
        entry = self._live(key)
        if entry is None:
            entry = self.data[key] = _Entry(kind())
        if not isinstance(entry.value, kind):
            raise TypeError(f"WRONGTYPE {key}")
        return entry.value

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        if name.startswith("_") or not hasattr(type(self), f"_cmd_{name}"):
            raise AttributeError(name)
        cmd = getattr(self, f"_cmd_{name}")

        async def run(*args: Any, **kwargs: Any) -> Any:
            self._check()
            return cmd(*args, **kwargs)

        return run

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self)

    def register_script(self, source: str) -> _Script:
        return _Script(self, source)

    async def aclose(self) -> None:
        self.closed = True

    # ---- commands ----------------------------------------------------------------------------------
    def _cmd_ping(self) -> bool:
        return True

    def _cmd_get(self, key: str) -> bytes | None:
        value = self._raw_get(key)
        return value if value is None or isinstance(value, bytes) else None

    def _cmd_set(
        self, key: str, value: Any, ex: float | None = None, px: float | None = None, nx: bool = False
    ) -> bool | None:
        if nx and self._live(key) is not None:
            return None
        ttl = ex if ex is not None else (px / 1000 if px is not None else None)
        self.data[key] = _Entry(_b(value), None if ttl is None else self.clock() + float(ttl))
        return True

    def _cmd_delete(self, *keys: str) -> int:
        return sum(self._delete(k) for k in keys if self._live(k) is not None)

    def _cmd_exists(self, *keys: str) -> int:
        return sum(1 for k in keys if self._live(k) is not None)

    def _cmd_incr(self, key: str, amount: int = 1) -> int:
        entry = self._live(key)
        value = int(entry.value) + amount if entry is not None else amount
        self.data[key] = _Entry(_b(value), entry.expires_at if entry else None)
        return value

    def _cmd_decr(self, key: str, amount: int = 1) -> int:
        return self._cmd_incr(key, -amount)

    def _cmd_incrbyfloat(self, key: str, amount: float) -> float:
        entry = self._live(key)
        value = float(entry.value) + float(amount) if entry is not None else float(amount)
        self.data[key] = _Entry(_b(value), entry.expires_at if entry else None)
        return value

    def _cmd_expire(self, key: str, seconds: float) -> bool:
        entry = self._live(key)
        if entry is None:
            return False
        entry.expires_at = self.clock() + float(seconds)
        return True

    def _cmd_ttl(self, key: str) -> int:
        entry = self._live(key)
        if entry is None:
            return -2
        return -1 if entry.expires_at is None else max(0, round(entry.expires_at - self.clock()))

    def _cmd_hset(
        self,
        key: str,
        field_name: str | None = None,
        value: Any = None,
        mapping: Mapping[str, Any] | None = None,
    ) -> int:
        h: dict[bytes, bytes] = self._container(key, dict)
        items = dict(mapping or {})
        if field_name is not None:
            items[field_name] = value
        added = sum(1 for k in items if _b(k) not in h)
        h.update({_b(k): _b(v) for k, v in items.items()})
        return added

    def _cmd_hgetall(self, key: str) -> dict[bytes, bytes]:
        entry = self._live(key)
        return dict(entry.value) if entry is not None and isinstance(entry.value, dict) else {}

    def _cmd_hincrby(self, key: str, field_name: str, amount: int = 1) -> int:
        h: dict[bytes, bytes] = self._container(key, dict)
        value = int(h.get(_b(field_name), b"0")) + amount
        h[_b(field_name)] = _b(value)
        return value

    def _cmd_sadd(self, key: str, *members: Any) -> int:
        s: set[bytes] = self._container(key, set)
        before = len(s)
        s.update(_b(m) for m in members)
        return len(s) - before

    def _cmd_smembers(self, key: str) -> set[bytes]:
        entry = self._live(key)
        return set(entry.value) if entry is not None and isinstance(entry.value, set) else set()

    def _cmd_rpush(self, key: str, *values: Any) -> int:
        lst: list[bytes] = self._container(key, list)
        lst.extend(_b(v) for v in values)
        return len(lst)

    def _cmd_ltrim(self, key: str, start: int, end: int) -> bool:
        entry = self._live(key)
        if entry is None:
            return True
        lst: list[bytes] = entry.value
        n = len(lst)
        lo = max(0, start + n if start < 0 else start)
        hi = end + n if end < 0 else min(end, n - 1)
        entry.value = lst[lo : hi + 1] if lo <= hi else []
        if not entry.value:
            self._delete(key)
        return True

    def _cmd_lrange(self, key: str, start: int, end: int) -> list[bytes]:
        entry = self._live(key)
        if entry is None:
            return []
        lst: list[bytes] = entry.value
        n = len(lst)
        lo = max(0, start + n if start < 0 else start)
        hi = end + n if end < 0 else min(end, n - 1)
        return list(lst[lo : hi + 1]) if lo <= hi else []
