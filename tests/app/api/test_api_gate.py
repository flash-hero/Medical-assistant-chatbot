"""Turn gates (review P2/S5, S1): one running turn per session, per-IP concurrent turns, idempotent replay.
Memory gate = one process (dev); Redis gate = shared across workers (SET NX EX lock, compare-and-delete)."""

from __future__ import annotations

import asyncio

import pytest

from app.api.errors import TurnInProgress
from app.api.gate import MemoryTurnGate, RedisTurnGate, TurnClaim
from core.errors import DependencyUnavailable, RateLimited
from evals.fakes.fake_redis import FakeRedis


def _claim(sid: str = "s1", ctid: str = "c1", ip: str = "203.0.113.7", exclusive: bool = True) -> TurnClaim:
    return TurnClaim(session_id=sid, client_turn_id=ctid, ip_key=ip, exclusive=exclusive)


def _gates(clock=None):
    clock = clock or (lambda: 0.0)
    return [
        MemoryTurnGate(ip_cap=2, clock=clock),
        RedisTurnGate(FakeRedis(clock=clock), ip_cap=2),
    ]


@pytest.mark.parametrize("gate", _gates(), ids=["memory", "redis"])
async def test_single_flight_per_session_and_release(gate) -> None:
    a = _claim()
    await gate.begin(a)
    assert gate.running == 1
    with pytest.raises(TurnInProgress):
        await gate.begin(_claim(ctid="c2"))
    await gate.begin(_claim(ctid="c3", exclusive=False))  # model-free safety turns never wait
    assert gate.running == 2
    await gate.finish(a, "t1", ("f1", "f2"))
    assert await gate.replay("s1", "c1") == ("f1", "f2")
    assert await gate.replay("s1", "other") is None
    assert gate.owns("t1", "s1") and not gate.owns("t1", "s2")
    await gate.begin(_claim(ctid="c4"))  # the session is free again


@pytest.mark.parametrize("gate", _gates(), ids=["memory", "redis"])
async def test_per_ip_concurrent_turns(gate) -> None:
    first, second = _claim("s1"), _claim("s2")
    await gate.begin(first)
    await gate.begin(second)
    with pytest.raises(RateLimited) as err:
        await gate.begin(_claim("s3"))
    assert err.value.detail["scope"] == "concurrent"
    await gate.begin(_claim("s3", ip="198.51.100.1"))  # other clients are unaffected
    await gate.finish(first, "t1", None)
    await gate.begin(_claim("s4"))
    assert await gate.replay("s1", "c1") is None  # cancelled turns are not replayable


@pytest.mark.parametrize("gate", _gates(), ids=["memory", "redis"])
async def test_rejected_begin_holds_nothing(gate) -> None:
    await gate.begin(_claim("s1"))
    await gate.begin(_claim("s2"))
    with pytest.raises(RateLimited):
        await gate.begin(_claim("s3"))
    assert gate.running == 2
    await gate.begin(_claim("s3", ip="198.51.100.9"))  # s3's lock was released after the 429


@pytest.mark.parametrize("gate", _gates(), ids=["memory", "redis"])
async def test_release_nowait_frees_an_abandoned_claim(gate) -> None:
    claim = _claim()
    await gate.begin(claim)
    gate.release_nowait(claim)
    await asyncio.sleep(0)  # the Redis gate releases in a task
    await asyncio.sleep(0)
    assert gate.running == 0
    await gate.begin(_claim(ctid="c2"))
    gate.release_nowait(claim)  # idempotent: does not release the new holder
    with pytest.raises(TurnInProgress):
        await gate.begin(_claim(ctid="c3"))


async def test_memory_gate_bounds_and_expires_replays() -> None:
    clock = [0.0]
    gate = MemoryTurnGate(ttl_s=10, max_entries=2, clock=lambda: clock[0])
    for i in range(3):
        c = _claim(f"s{i}", "c")
        await gate.begin(c)
        await gate.finish(c, f"t{i}", (f"f{i}",))
    assert await gate.replay("s0", "c") is None  # evicted (max_entries)
    assert await gate.replay("s2", "c") == ("f2",)
    clock[0] = 11.0
    assert await gate.replay("s2", "c") is None  # expired


async def test_redis_lock_expires_if_a_worker_dies() -> None:
    clock = [0.0]
    r = FakeRedis(clock=lambda: clock[0])
    gate = RedisTurnGate(r, ip_cap=2, lock_ttl_s=60)
    await gate.begin(_claim())
    other_worker = RedisTurnGate(r, ip_cap=2, lock_ttl_s=60)
    with pytest.raises(TurnInProgress):
        await other_worker.begin(_claim(ctid="c2"))
    clock[0] = 61.0
    await other_worker.begin(_claim(ctid="c2"))
    await gate.finish(_claim(), "t1", None)  # the dead worker's late release does not free c2's lock
    with pytest.raises(TurnInProgress):
        await other_worker.begin(_claim(ctid="c3"))


async def test_redis_replay_is_shared_and_size_capped() -> None:
    r = FakeRedis()
    a, b = RedisTurnGate(r, ip_cap=2), RedisTurnGate(r, ip_cap=2, replay_max_bytes=10)
    claim = _claim()
    await a.begin(claim)
    await a.finish(claim, "t1", ("event: meta\n\n", "event: done\n\n"))
    assert await b.replay("s1", "c1") == ("event: meta\n\n", "event: done\n\n")
    await b.begin(_claim(ctid="c9"))
    await b.finish(_claim(ctid="c9"), "t9", ("x" * 50,))
    assert await b.replay("s1", "c9") is None  # too large to keep: a retry runs the turn again


async def test_redis_gate_outage_is_a_dependency_error() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    r = FakeRedis()
    gate = RedisTurnGate(r, ip_cap=2)
    r.fail = RedisConnectionError("down")
    with pytest.raises(DependencyUnavailable):
        await gate.begin(_claim())
    with pytest.raises(DependencyUnavailable):
        await gate.replay("s1", "c1")
    assert gate.running == 0
    await gate.finish(_claim(), "t1", ("f",))  # cleanup never raises
