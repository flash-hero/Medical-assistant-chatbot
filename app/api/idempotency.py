"""Idempotency-Key support for form submissions (appointment requests).

The web client sends `Idempotency-Key` and reuses it when it retries an unchanged form (review T14). A retried
POST with the same key and the same body returns the original response instead of creating a duplicate request
for hospital staff. The same key with a different body is rejected (422); a retry that arrives while the first
attempt is still running gets 409. Keys are scoped to the session and expire after 24 h.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from core.errors import AusculaError, InvalidInput

KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")
TTL_S = 24 * 3600
_PENDING, _DONE = "pending", "done"


class IdempotencyConflict(AusculaError):
    code, http_status = "idempotency_conflict", 409


@dataclass(frozen=True)
class IdemRecord:
    body_hash: str
    status: str  # "pending" | "done"
    response: dict[str, str] | None = None

    def dumps(self) -> str:
        return json.dumps({"h": self.body_hash, "s": self.status, "r": self.response})

    @classmethod
    def loads(cls, raw: str | bytes) -> IdemRecord:
        data = json.loads(raw)
        return cls(body_hash=str(data["h"]), status=str(data["s"]), response=data.get("r"))


class IdempotencyStore(Protocol):
    async def claim(self, scope: str, key: str, body_hash: str) -> IdemRecord | None:
        """Claim the key. None = newly claimed by this caller; otherwise the existing record."""
        ...

    async def complete(self, scope: str, key: str, record: IdemRecord) -> None: ...

    async def release(self, scope: str, key: str) -> None: ...


class MemoryIdempotencyStore:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._data: dict[tuple[str, str], tuple[float, IdemRecord]] = {}
        self._clock = clock

    def _live(self, k: tuple[str, str]) -> IdemRecord | None:
        hit = self._data.get(k)
        if hit is None or hit[0] <= self._clock():
            self._data.pop(k, None)
            return None
        return hit[1]

    async def claim(self, scope: str, key: str, body_hash: str) -> IdemRecord | None:
        existing = self._live((scope, key))
        if existing is not None:
            return existing
        self._data[(scope, key)] = (self._clock() + TTL_S, IdemRecord(body_hash, _PENDING))
        return None

    async def complete(self, scope: str, key: str, record: IdemRecord) -> None:
        self._data[(scope, key)] = (self._clock() + TTL_S, record)

    async def release(self, scope: str, key: str) -> None:
        self._data.pop((scope, key), None)


class RedisIdempotencyStore:
    def __init__(self, client: Any, *, prefix: str = "ausculta:idem:") -> None:
        self._r = client
        self._prefix = prefix

    def _k(self, scope: str, key: str) -> str:
        return f"{self._prefix}{scope}:{key}"

    async def claim(self, scope: str, key: str, body_hash: str) -> IdemRecord | None:
        pending = IdemRecord(body_hash, _PENDING).dumps()
        if await self._r.set(self._k(scope, key), pending, nx=True, ex=TTL_S):
            return None
        raw = await self._r.get(self._k(scope, key))
        # Vanished between SET NX and GET (expired or released): treat as in progress, the client retries.
        return IdemRecord.loads(raw) if raw is not None else IdemRecord(body_hash, _PENDING)

    async def complete(self, scope: str, key: str, record: IdemRecord) -> None:
        await self._r.set(self._k(scope, key), record.dumps(), ex=TTL_S)

    async def release(self, scope: str, key: str) -> None:
        await self._r.delete(self._k(scope, key))


def body_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


async def run_idempotent(
    store: IdempotencyStore | None,
    scope: str,
    key: str | None,
    payload_hash: str,
    create: Callable[[], Awaitable[dict[str, str]]],
) -> dict[str, str]:
    """Run `create` at most once per (scope, key); replay its response for identical retries."""
    if store is None or key is None:
        return await create()
    if not KEY_PATTERN.match(key):
        raise InvalidInput("malformed Idempotency-Key", detail={"field": "Idempotency-Key"})
    prior = await store.claim(scope, key, payload_hash)
    if prior is not None:
        if prior.body_hash != payload_hash:
            raise InvalidInput(
                "Idempotency-Key reused with a different request", detail={"field": "Idempotency-Key"}
            )
        if prior.status != _DONE or prior.response is None:
            raise IdempotencyConflict("an identical request is still being processed")
        return prior.response
    try:
        response = await create()
    except BaseException:
        await store.release(scope, key)
        raise
    await store.complete(scope, key, IdemRecord(payload_hash, _DONE, response))
    return response
