"""Idempotency-Key on appointment requests: a retried identical submission never creates a duplicate."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.api.idempotency import (
    IdempotencyConflict,
    MemoryIdempotencyStore,
    RedisIdempotencyStore,
    body_hash,
    run_idempotent,
)
from app.storage.models import AppointmentContactRow
from core.errors import InvalidInput
from evals.fakes.fake_redis import FakeRedis

API = "/api/v1"
VALID = {
    "full_name": "Test Patient",
    "phone": "+33 1 00 00 00 99",
    "email": "patient@example.org",
    "department_id": "cardiology",
    "preferred_dates": "Monday or Tuesday morning",
    "reason": "Follow-up visit",
    "consent": True,
}


@pytest.fixture(params=["memory", "redis"])
def store(request):
    return MemoryIdempotencyStore() if request.param == "memory" else RedisIdempotencyStore(FakeRedis())


async def test_identical_retry_replays_and_runs_create_once(store) -> None:
    calls: list[int] = []

    async def create() -> dict[str, str]:
        calls.append(1)
        return {"request_id": f"AR-{len(calls)}", "message": "ok"}

    h = body_hash({"a": 1})
    first = await run_idempotent(store, "s1", "key-12345678", h, create)
    again = await run_idempotent(store, "s1", "key-12345678", h, create)
    assert first == again == {"request_id": "AR-1", "message": "ok"}
    assert len(calls) == 1
    other_session = await run_idempotent(store, "s2", "key-12345678", h, create)
    assert other_session["request_id"] == "AR-2"  # keys are scoped to the session


async def test_reuse_with_a_different_body_or_malformed_key_is_rejected(store) -> None:
    async def create() -> dict[str, str]:
        return {"request_id": "AR-1", "message": "ok"}

    await run_idempotent(store, "s1", "key-12345678", body_hash({"a": 1}), create)
    with pytest.raises(InvalidInput, match="different request"):
        await run_idempotent(store, "s1", "key-12345678", body_hash({"a": 2}), create)
    with pytest.raises(InvalidInput, match="malformed"):
        await run_idempotent(store, "s1", "bad key!", body_hash({"a": 1}), create)


async def test_concurrent_identical_request_gets_409_and_failure_releases_the_key(store) -> None:
    gate = asyncio.Event()

    async def slow() -> dict[str, str]:
        await gate.wait()
        return {"request_id": "AR-1", "message": "ok"}

    h = body_hash({"a": 1})
    first = asyncio.create_task(run_idempotent(store, "s1", "key-12345678", h, slow))
    await asyncio.sleep(0)
    with pytest.raises(IdempotencyConflict):
        await run_idempotent(store, "s1", "key-12345678", h, slow)
    gate.set()
    await first

    async def boom() -> dict[str, str]:
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await run_idempotent(store, "s1", "key-other-1", h, boom)
    ok = await run_idempotent(store, "s1", "key-other-1", h, slow)  # released: a retry can run
    assert ok["request_id"] == "AR-1"


async def test_api_retry_with_the_same_key_creates_one_request(api) -> None:
    token = await api.token("en")
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "form-retry-0001"}
    first = await api.client.post(f"{API}/appointments", json=VALID, headers=headers)
    retry = await api.client.post(f"{API}/appointments", json=VALID, headers=headers)
    assert first.status_code == retry.status_code == 201, retry.text
    assert first.json() == retry.json()
    factory = api.container.storage.appointments._s
    async with factory() as db:
        rows = list((await db.scalars(select(AppointmentContactRow))).all())
    assert len(rows) == 1
    changed = await api.client.post(
        f"{API}/appointments", json={**VALID, "reason": "Something else"}, headers=headers
    )
    assert changed.status_code == 422
