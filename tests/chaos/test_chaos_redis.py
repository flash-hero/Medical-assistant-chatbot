"""Chaos: Redis (sessions, turn gate, idempotency, spend) and the rate-limit storage are down.

Expected: every stateful request is a fast 503 dependency_unavailable with Retry-After (never a 500, never a
hang) whose message names the emergency (15) and crisis (3114) numbers, /ready is 503, no admission slot
leaks, and service resumes when Redis is back. The model-free emergency / self-harm path still delivers its
safety template as a valid SSE turn, statelessly (P5-D8, fixed).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from chaos_support import EMERGENCY, FEVER, SELF_HARM
from limits.errors import StorageError
from redis.exceptions import ConnectionError as RedisConnectionError

from core.errors import DependencyUnavailable
from evals.fakes.fake_redis import FakeRedis

FAST_FAIL_S = 2.0


def _break_limiter(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(*_a: Any, **_k: Any) -> Any:
        raise StorageError(ConnectionError("limits storage down"))

    monkeypatch.setattr(api.container.rate._limiter, "hit", down)
    monkeypatch.setattr(api.container.rate._fixed, "hit", down)
    monkeypatch.setattr(api.container.rate._storage, "check", down)


EMERGENCY_NUMBER = "15"  # config/hospital/demo.yaml
CRISIS_NUMBER = "3114"


def _assert_503(response: Any) -> None:
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["error"]["code"] == "dependency_unavailable"
    assert int(response.headers["retry-after"]) >= 1
    assert "emergency" in body["error"]["message"]
    assert EMERGENCY_NUMBER in body["error"]["message"]
    assert CRISIS_NUMBER in body["error"]["message"]


def _assert_safety_turn(turn: Any, kind: str) -> None:
    """A complete model-free turn: meta, the safety template with the hospital contacts, the closing
    answer, done, and nothing out of order."""
    turn.assert_contract()
    assert turn.types[0] == "meta"
    assert turn.types[-1] == "done"
    assert "error" not in turn.types
    safety = next(e for e in turn.events if e.type == "safety")
    assert safety.kind == kind
    numbers = {c.number for c in safety.contacts}
    assert EMERGENCY_NUMBER in numbers or CRISIS_NUMBER in numbers
    assert turn.answer().mode == "template"


async def test_redis_and_limiter_outage_is_a_fast_503_everywhere(
    chaos_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
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


async def test_service_resumes_when_redis_comes_back(chaos_app: Any) -> None:
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


async def test_redis_outage_never_leaves_the_session_lock_held(chaos_app: Any) -> None:
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


@pytest.mark.parametrize(("message", "kind"), [(EMERGENCY, "emergency"), (SELF_HARM, "self_harm")])
async def test_emergency_path_still_answers_during_a_redis_outage(
    chaos_app: Any, monkeypatch: pytest.MonkeyPatch, message: str, kind: str
) -> None:
    """P5-D8: Redis and the rate-limit storage are both down; the safety template is still served."""
    redis = FakeRedis()
    async with chaos_app(redis_client=redis) as api:
        token = await api.token()
        redis.fail = RedisConnectionError("redis down")
        _break_limiter(api, monkeypatch)
        t0 = time.perf_counter()
        turn = await api.chat(token, message)
        assert time.perf_counter() - t0 < FAST_FAIL_S
        _assert_safety_turn(turn, kind)
        _assert_503((await api.chat(token, FEVER)).response)  # ordinary turns are still refused
        assert api.container.registry.running == 0
        assert api.container.admission.held == 0


async def test_safety_turn_survives_a_failing_session_save(
    chaos_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The session loads but the store fails on the turn's first save: the template still closes the turn
    (the engine ends it statelessly) instead of an error event."""
    async with chaos_app() as api:
        token = await api.token()

        async def down(*_a: Any, **_k: Any) -> Any:
            raise DependencyUnavailable("session store unavailable")

        monkeypatch.setattr(api.container.sessions, "apply", down)
        _assert_safety_turn(await api.chat(token, SELF_HARM), "self_harm")
        fever = await api.chat(token, FEVER)  # a model turn with the same failure ends with an error event
        fever.assert_contract()
        error = next(e for e in fever.events if e.type == "error")
        assert error.code == "dependency_unavailable"
        assert EMERGENCY_NUMBER in error.message
        assert CRISIS_NUMBER in error.message


async def test_safety_turn_survives_a_failing_turn_gate(
    chaos_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with chaos_app() as api:
        token = await api.token()

        async def down(*_a: Any, **_k: Any) -> Any:
            raise DependencyUnavailable("turn store unavailable")

        monkeypatch.setattr(api.container.registry, "replay", down)
        monkeypatch.setattr(api.container.registry, "begin", down)
        _assert_safety_turn(await api.chat(token, EMERGENCY), "emergency")
        assert api.container.registry.running == 0


@pytest.mark.parametrize(("locale", "phrase"), [("en", "emergency"), ("fr", "urgence"), ("ar", "الطوارئ")])
async def test_every_503_message_names_the_emergency_and_crisis_numbers(
    chaos_app: Any, locale: str, phrase: str
) -> None:
    redis = FakeRedis()
    async with chaos_app(redis_client=redis) as api:
        redis.fail = RedisConnectionError("redis down")
        r = await api.client.post(f"/api/v1/session?locale={locale}", json={"locale": locale})
        assert r.status_code == 503
        message = r.json()["error"]["message"]
        assert phrase in message
        assert EMERGENCY_NUMBER in message
        assert CRISIS_NUMBER in message
        texts, profile = api.container.texts, api.container.profile()
        for code in ("dependency_unavailable", "overloaded", "service_paused"):
            text = texts.error(code, locale, profile)
            assert EMERGENCY_NUMBER in text, (code, text)
            assert CRISIS_NUMBER in text, (code, text)
            assert "{" not in text
