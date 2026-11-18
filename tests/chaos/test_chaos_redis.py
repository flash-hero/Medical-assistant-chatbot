"""Chaos: Redis (sessions, turn gate, idempotency, spend) and the rate-limit storage are down.

Expected: every stateful request is a fast 503 dependency_unavailable with Retry-After (never a 500, never a
hang), /ready is 503, no admission slot leaks, and service resumes when Redis is back. The model-free
emergency / self-harm path should still deliver its safety template (see the xfail below: open defect).
"""

from __future__ import annotations

import time

import pytest
from chaos_support import EMERGENCY, FEVER, SELF_HARM
from limits.errors import StorageError
from redis.exceptions import ConnectionError as RedisConnectionError

from evals.fakes.fake_redis import FakeRedis

FAST_FAIL_S = 2.0


def _break_limiter(api, monkeypatch) -> None:
    async def down(*_a, **_k):
        raise StorageError(ConnectionError("limits storage down"))

    monkeypatch.setattr(api.container.rate._limiter, "hit", down)
    monkeypatch.setattr(api.container.rate._fixed, "hit", down)
    monkeypatch.setattr(api.container.rate._storage, "check", down)


def _assert_503(response) -> None:
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["error"]["code"] == "dependency_unavailable"
    assert int(response.headers["retry-after"]) >= 1
    assert "emergency" in body["error"]["message"]


async def test_redis_and_limiter_outage_is_a_fast_503_everywhere(chaos_app, monkeypatch) -> None:
    redis = FakeRedis()
    async with chaos_app(redis_client=redis) as api:
        token = await api.token()
        redis.fail = RedisConnectionError("redis down")
        _break_limiter(api, monkeypatch)
        for message in (FEVER, "What are the visiting hours?", "I would like an appointment"):
            t0 = time.perf_counter()
            turn = await api.chat(token, message)
            assert time.perf_counter() - t0 < FAST_FAIL_S
            _assert_503(turn.response)
        _assert_503(await api.client.post("/api/v1/session", json={"locale": "en"}))
        ready = await api.client.get("/api/v1/ready")
        assert ready.status_code == 503
        assert ready.json()["checks"]["sessions"] is False
        assert ready.json()["checks"]["rate_limiter"] is False
        assert api.container.admission.held == 0
        assert api.container.admission.waiting == 0


async def test_service_resumes_when_redis_comes_back(chaos_app) -> None:
    redis = FakeRedis()
    async with chaos_app(redis_client=redis) as api:
        token = await api.token()
        redis.fail = RedisConnectionError("redis down")
        _assert_503((await api.chat(token, FEVER)).response)
        redis.fail = None
        back = await api.chat(token, FEVER)
        back.assert_contract()
        assert back.answer().mode in ("streamed", "verified")
        assert (await api.client.get("/api/v1/ready")).status_code == 200


async def test_redis_outage_never_leaves_the_session_lock_held(chaos_app) -> None:
    """Redis fails between session load and the end of the turn: the next turn is not stuck on a 409."""
    redis = FakeRedis()
    async with chaos_app(redis_client=redis) as api:
        token = await api.token()
        redis.fail = RedisConnectionError("redis down")
        for _ in range(3):
            assert (await api.chat(token, FEVER)).response.status_code == 503
        redis.fail = None
        turn = await api.chat(token, FEVER)
        turn.assert_contract()


@pytest.mark.xfail(
    strict=True,
    reason="P5 open defect D5: with Redis (or the rate-limit storage) down, emergency / self-harm messages get "
    "a 503 error instead of the model-free safety template; the error text has no crisis line",
)
@pytest.mark.parametrize("message", [EMERGENCY, SELF_HARM])
async def test_emergency_path_still_answers_during_a_redis_outage(chaos_app, monkeypatch, message) -> None:
    redis = FakeRedis()
    async with chaos_app(redis_client=redis) as api:
        token = await api.token()
        redis.fail = RedisConnectionError("redis down")
        _break_limiter(api, monkeypatch)
        turn = await api.chat(token, message)
        assert turn.response.status_code == 200
        assert any(e.type == "safety" for e in turn.events)
