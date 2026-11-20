"""Review P2/S5: session updates are atomic deltas, so two workers (or two concurrent turns) never lose an
update of turns_used, strikes, the lock or the sticky risk flags.
Memory store (dev) and Redis store (prod)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.pipeline.session import (
    MemorySessionStore,
    RedisSessionStore,
    SessionState,
    SessionUpdate,
)
from core.errors import DependencyUnavailable
from core.schemas.chat import RiskKind
from evals.fakes.fake_redis import FakeRedis


def _state(sid: str = "s1", *, minutes: int = 120) -> SessionState:
    now = datetime.now(UTC)
    return SessionState(
        session_id=sid, locale="fr", created_at=now, expires_at=now + timedelta(minutes=minutes)
    )


def _stores() -> list[object]:
    return [MemorySessionStore(), RedisSessionStore(FakeRedis())]


def test_applied_is_the_pure_form_of_an_update() -> None:
    s0 = _state()
    u = SessionUpdate(
        turn_text="hello", window=2, risks=frozenset({RiskKind.EMERGENCY}), strike=True, strikes_to_lock=1
    )
    s1 = s0.applied(u)
    assert (s1.turns_used, s1.strikes, s1.locked) == (1, 1, True)
    assert s1.sticky_risks == {RiskKind.EMERGENCY}
    assert s1.user_history() == ("hello",)
    assert s0.turns_used == 0  # immutable
    assert SessionUpdate().is_empty
    assert not u.is_empty
    assert s0.applied(SessionUpdate()) == s0


@pytest.mark.parametrize("store", _stores(), ids=["memory", "redis"])
async def test_round_trip_and_missing_session(store) -> None:
    state = _state("x").with_turn("first", window=3).with_risks(frozenset({RiskKind.SELF_HARM}))
    await store.put(state)
    got = await store.get("x")
    assert got == state
    assert await store.get("missing") is None
    assert await store.apply(_state("missing"), SessionUpdate(turn_text="t", window=3)) is None
    assert await store.ping() is True


@pytest.mark.parametrize("store", _stores(), ids=["memory", "redis"])
async def test_concurrent_updates_are_never_lost(store) -> None:
    """50 concurrent turns of two 'workers' that each started from the same stale snapshot."""
    base = _state("race")
    await store.put(base)
    kinds = list(RiskKind)

    async def one(i: int) -> None:
        await asyncio.sleep(0)
        await store.apply(
            base,  # the stale snapshot every worker read before its turn
            SessionUpdate(
                turn_text=f"t{i}",
                window=3,
                risks=frozenset({kinds[i % len(kinds)]}),
                strike=i % 2 == 0,
                strikes_to_lock=100,
            ),
        )

    await asyncio.gather(*(one(i) for i in range(50)))
    final = await store.get("race")
    assert final is not None
    assert final.turns_used == 50
    assert final.strikes == 25
    assert final.locked is False
    assert final.sticky_risks == frozenset(kinds)
    assert len(final.history) == 3


@pytest.mark.parametrize("store", _stores(), ids=["memory", "redis"])
async def test_strikes_lock_once_the_threshold_is_reached(store) -> None:
    base = _state("lock")
    await store.put(base)
    for _ in range(2):
        state = await store.apply(base, SessionUpdate(strike=True, strikes_to_lock=3))
        assert state is not None
        assert not state.locked
    state = await store.apply(base, SessionUpdate(strike=True, strikes_to_lock=3))
    assert state is not None
    assert (state.strikes, state.locked) == (3, True)
    assert (await store.get("lock")).locked is True  # type: ignore[union-attr]


async def test_redis_store_keeps_the_session_ttl_and_window() -> None:
    clock = [0.0]
    r = FakeRedis(clock=lambda: clock[0])
    store = RedisSessionStore(r)
    base = _state("ttl", minutes=10)
    await store.put(base)
    for i in range(5):
        await store.apply(base, SessionUpdate(turn_text=f"m{i}", window=2))
    got = await store.get("ttl")
    assert got is not None
    assert got.user_history() == ("m3", "m4")
    assert 0 < await r.ttl("ausculta:s2:ttl") <= 600
    clock[0] = 601.0
    assert await store.get("ttl") is None


async def test_redis_store_outage_is_a_dependency_error() -> None:
    r = FakeRedis()
    store = RedisSessionStore(r)
    await store.put(_state("down"))
    r.fail = RedisConnectionError("redis down")
    with pytest.raises(DependencyUnavailable):
        await store.get("down")
    with pytest.raises(DependencyUnavailable):
        await store.apply(_state("down"), SessionUpdate(turn_text="x", window=3))
    with pytest.raises(DependencyUnavailable):
        await store.put(_state("down"))
    assert await store.ping() is False


@pytest.mark.parametrize(
    "update",
    [
        SessionUpdate(
            turn_text="t", window=3, risks=frozenset({RiskKind.INJECTION}), strike=True, strikes_to_lock=1
        ),
        SessionUpdate(turn_text="t", window=0, strike=True, strikes_to_lock=1),
        SessionUpdate(risks=frozenset({RiskKind.ABUSIVE_USER}), strike=True, strikes_to_lock=1),
    ],
    ids=["turn-risks-strike", "turn-no-window-strike", "risks-strike"],
)
async def test_redis_lock_reads_the_strike_count_in_every_update_shape(update) -> None:
    store = RedisSessionStore(FakeRedis())
    base = _state("shape")
    await store.put(base)
    state = await store.apply(base, update)
    assert state is not None
    assert (state.strikes, state.locked) == (1, True)
