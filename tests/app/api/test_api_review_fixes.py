"""Regression tests for the P3 review findings owned by the API layer (docs/reviews/2026-11-16-p3-review.md):
C9/P8 safety turns first, S1 abuse limits, P2/S5 shared turn lock + atomic session state across workers,
P10/S9 non-ASCII tokens, P12 retriever warm-up, P16 dependency errors, P17 Redis shutdown, S6/P7 purge task,
S7 form caps, S18 e-mail hygiene, C10 demo profile outside demo mode."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace

import pytest
from limits import parse
from limits.errors import StorageError
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from app.storage import repositories
from app.storage.models import AppointmentContactRow
from core.schemas.chat import RiskKind
from evals.fakes.fake_redis import FakeRedis
from evals.fakes.fake_retriever import FakeRetriever
from evals.fakes.scripted import scripted_provider

API = "/api/v1"
FEVER = "What is a fever?"
EMERGENCY = "I have crushing chest pain spreading to my left arm and I'm sweating"
SELF_HARM = "I want to kill myself"
APPOINTMENT = {
    "full_name": "Test Patient",
    "phone": "+33 1 00 00 00 99",
    "department_id": "cardiology",
    "preferred_dates": "Monday morning",
    "consent": True,
}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _code(res) -> str:
    return res.response.json()["error"]["code"]


async def _wait(predicate, tries: int = 300) -> None:
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


def _rules(**changes):
    return lambda rules: replace(rules, **{k: parse(v) for k, v in changes.items()})


# ---- C9 / P8: the deterministic precheck runs before every limit ------------------------------------
async def test_c9_self_harm_at_the_turn_limit_still_gets_the_safety_template(api_factory) -> None:
    """Repro: 'I want to kill myself' at the turn limit used to be a 429 with no safety event."""
    async with api_factory(AUSCULTA_MAX_TURNS=1) as api:
        token = await api.token()
        (await api.chat(token, "hello")).assert_contract()
        res = await api.chat(token, SELF_HARM)
        res.assert_contract()
        assert res.first("safety").kind == "self_harm"
        assert res.first("done").turns_left == 0
        assert (await api.chat(token, "hello")).response.status_code == 429


@pytest.mark.parametrize("how", ["env", "file"])
async def test_c9_kill_switch_pauses_model_turns_but_not_emergencies(api_factory, tmp_path, how) -> None:
    env = {"AUSCULTA_KILL_SWITCH": True} if how == "env" else {}
    if how == "file":
        (tmp_path / "KILL_SWITCH").write_text("paused\n", encoding="utf-8")
    async with api_factory(**env) as api:
        token = await api.token()
        paused = await api.chat(token, FEVER)
        assert paused.response.status_code == 503
        assert _code(paused) == "service_paused"
        for message in (EMERGENCY, SELF_HARM):
            res = await api.chat(token, message)
            res.assert_contract()
            assert res.first("safety").kind in ("emergency", "self_harm")


async def test_c9_rate_limited_client_still_gets_the_emergency_template(api_factory) -> None:
    async with api_factory(AUSCULTA_RATE_SESSION_MIN=1, AUSCULTA_RATE_IP_MIN=2) as api:
        token = await api.token()
        (await api.chat(token, "hello")).assert_contract()
        limited = await api.chat(token, "hello")
        assert limited.response.status_code == 429
        res = await api.chat(token, EMERGENCY)
        res.assert_contract()
        assert res.first("safety").kind == "emergency"


async def test_c9_running_turn_does_not_block_an_emergency(api_factory) -> None:
    llm = scripted_provider()
    llm.latency_s = 0.4
    async with api_factory(llm=llm) as api:
        token = await api.token()
        running = asyncio.create_task(api.chat(token, FEVER))
        await _wait(lambda: api.container.registry.running == 1)
        assert (await api.chat(token, FEVER)).response.status_code == 409
        emergency = await api.chat(token, EMERGENCY)
        emergency.assert_contract()
        assert emergency.first("safety").kind == "emergency"
        (await running).assert_contract()
        state = await api.container.sessions.get(emergency.first("meta").session_id)
        assert state is not None
        assert state.turns_used == 2
        assert RiskKind.EMERGENCY in state.sticky_risks


async def test_c9_safety_turns_have_their_own_generous_bucket(api_factory) -> None:
    async with api_factory(rate_rules=_rules(safety_per_ip="2/minute")) as api:
        token = await api.token()
        for _ in range(2):
            (await api.chat(token, EMERGENCY)).assert_contract()
        res = await api.chat(token, EMERGENCY)
        assert res.response.status_code == 429
        assert _code(res) == "rate_limited"


# ---- S1: IPv6 /64 keys, global session-creation cap, per-IP concurrent turns ------------------------
async def test_s1_ipv6_clients_of_one_slash64_share_a_bucket(api_factory) -> None:
    async with api_factory(AUSCULTA_RATE_IP_MIN=2, client=("2001:db8:1:2::1", 1)) as api:  # 1 session/min
        await api.session()
        same64 = api.client_for("2001:db8:1:2:abcd:ef01:2345:6789")
        r = await same64.post(f"{API}/session", json={"locale": "en"})
        assert r.status_code == 429
        other64 = api.client_for("2001:db8:1:3::1")
        assert (await other64.post(f"{API}/session", json={"locale": "en"})).status_code == 201


async def test_s1_ipv4_mapped_ipv6_is_the_ipv4_client(api_factory) -> None:
    async with api_factory(AUSCULTA_RATE_IP_MIN=2, client=("203.0.113.9", 1)) as api:
        await api.session()
        mapped = api.client_for("::ffff:203.0.113.9")
        assert (await mapped.post(f"{API}/session", json={"locale": "en"})).status_code == 429


async def test_s1_global_session_creation_cap(api_factory) -> None:
    async with api_factory(rate_rules=_rules(session_create_global="3/minute")) as api:
        for i in range(3):
            r = await api.client_for(f"198.51.100.{i + 1}").post(f"{API}/session", json={"locale": "en"})
            assert r.status_code == 201
        r = await api.client_for("198.51.100.99").post(f"{API}/session", json={"locale": "en"})
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "rate_limited"


async def test_s1_per_ip_concurrent_turns_are_capped_at_two(api_factory) -> None:
    llm = scripted_provider()
    llm.latency_s = 0.4
    async with api_factory(llm=llm) as api:
        tokens = [await api.token() for _ in range(3)]
        running = [asyncio.create_task(api.chat(t, FEVER)) for t in tokens[:2]]
        await _wait(lambda: api.container.registry.running == 2)
        third = await api.chat(tokens[2], FEVER)
        assert third.response.status_code == 429
        assert _code(third) == "rate_limited"
        assert "retry-after" in third.response.headers
        emergency = await api.chat(tokens[2], EMERGENCY)
        emergency.assert_contract()
        for task in running:
            (await task).assert_contract()
        assert (await api.chat(tokens[2], FEVER)).response.status_code == 200
        assert api.container.registry.running == 0


# ---- P2 / S5: two workers sharing one Redis ------------------------------------------------------------
async def test_p2_two_workers_share_the_session_lock_and_the_replay(api_factory) -> None:
    redis = FakeRedis()
    slow = scripted_provider()
    slow.latency_s = 0.3
    other = scripted_provider()
    async with (
        api_factory(llm=slow, redis_client=redis) as a,
        api_factory(llm=other, redis_client=redis) as b,
    ):
        token = await a.token()
        turn = str(uuid.uuid4())
        running = asyncio.create_task(a.chat(token, FEVER, client_turn_id=turn))
        await _wait(lambda: a.container.registry.running == 1)
        clash = await b.chat(token, FEVER)
        assert clash.response.status_code == 409
        assert _code(clash) == "turn_in_progress"
        first = await running
        first.assert_contract()
        again = await b.chat(token, FEVER, client_turn_id=turn)
        assert again.response.text == first.response.text
        assert other.calls == [], "the replay on the other worker must not run (or bill) the turn again"
        fresh = await b.chat(token, FEVER)
        fresh.assert_contract()
        assert fresh.first("done").turns_left == 18


async def test_p2_safety_flag_from_another_worker_is_not_lost(api_factory) -> None:
    redis = FakeRedis()
    slow = scripted_provider()
    slow.latency_s = 0.3
    async with (
        api_factory(llm=slow, redis_client=redis) as a,
        api_factory(redis_client=redis) as b,
    ):
        body = await a.session()
        token = body["session_token"]
        running = asyncio.create_task(a.chat(token, FEVER))
        await _wait(lambda: a.container.registry.running == 1)
        (await b.chat(token, EMERGENCY)).assert_contract()
        (await running).assert_contract()
        state = await a.container.sessions.get(body["session_id"])
        assert state is not None
        assert state.turns_used == 2
        assert RiskKind.EMERGENCY in state.sticky_risks


async def test_p2_lock_is_released_after_the_turn(api_factory) -> None:
    redis = FakeRedis()
    async with api_factory(redis_client=redis) as api:
        token = await api.token()
        for _ in range(3):
            (await api.chat(token, FEVER)).assert_contract()
        assert not [k for k in redis.data if ":lock:" in k]
        assert not [k for k in redis.data if ":inflight:" in k]


# ---- P10 / S9: non-ASCII bearer token ---------------------------------------------------------------
@pytest.mark.parametrize("token", ["é.é", "Ünïcødé", "abc.dèf", "ÿ" * 600])
async def test_p10_non_ascii_bearer_token_is_401(api, token) -> None:
    for path, body in (
        ("chat", {"message": "hi", "locale": "en", "client_turn_id": str(uuid.uuid4())}),
        ("feedback", {"turn_id": str(uuid.uuid4()), "rating": "up"}),
    ):
        r = await api.client.post(
            f"{API}/{path}", json=body, headers={"Authorization": b"Bearer " + token.encode("latin-1")}
        )
        assert r.status_code == 401, r.text
        assert r.json()["error"]["code"] == "unauthorized"


# ---- P12: retriever warm-up --------------------------------------------------------------------------
class WarmRetriever(FakeRetriever):
    warmed: int = 0
    fail: bool = False

    async def warmup(self) -> None:
        self.warmed += 1
        if self.fail:
            raise RuntimeError("model files missing")


async def test_p12_startup_warms_the_retriever_once(api_factory) -> None:
    retriever = WarmRetriever()
    async with api_factory(retriever=retriever) as api:
        assert retriever.warmed == 1
        assert (await api.client.get(f"{API}/health")).status_code == 200


async def test_p12_failed_warmup_does_not_stop_the_api(api_factory) -> None:
    retriever = WarmRetriever()
    retriever.fail = True
    async with api_factory(retriever=retriever) as api:
        assert retriever.warmed == 1
        (await api.chat(await api.token(), FEVER)).assert_contract()


# ---- P16 / P17: dependency errors and shutdown --------------------------------------------------------
async def test_p16_redis_outage_is_503_not_500(api_factory) -> None:
    redis = FakeRedis()
    async with api_factory(redis_client=redis) as api:
        token = await api.token()
        redis.fail = RedisConnectionError("redis down")
        for res in (await api.chat(token, FEVER), await api.chat(token, EMERGENCY)):
            assert res.response.status_code == 503
            assert _code(res) == "dependency_unavailable"
            assert int(res.response.headers["retry-after"]) >= 1
        r = await api.client.post(f"{API}/session", json={"locale": "en"})
        assert r.status_code == 503
        assert "emergency" in r.json()["error"]["message"]


async def test_p16_rate_limiter_storage_error_is_503(api, monkeypatch) -> None:
    token = await api.token()

    async def broken(*_a, **_k):
        raise StorageError(ConnectionError("limits storage down"))

    monkeypatch.setattr(api.container.rate._limiter, "hit", broken)
    res = await api.chat(token, FEVER)
    assert res.response.status_code == 503
    assert _code(res) == "dependency_unavailable"


async def test_p17_shutdown_closes_the_redis_client(api_factory) -> None:
    redis = FakeRedis()
    async with api_factory(redis_client=redis):
        assert redis.closed is False
    assert redis.closed is True


# ---- S6 / P7: periodic purge -------------------------------------------------------------------------
async def test_s6_purge_runs_at_startup_and_then_periodically(api_factory, monkeypatch) -> None:
    runs: list[int] = []

    async def counting(self, now=None):
        runs.append(1)
        return {}

    monkeypatch.setattr(repositories.Storage, "purge_expired", counting)
    async with api_factory(purge_interval_s=0.05):
        await _wait(lambda: len(runs) >= 3)
    stopped = len(runs)
    await asyncio.sleep(0.15)
    assert len(runs) == stopped, "the purge task stops with the app"


async def test_s6_purge_failure_is_logged_and_retried(api_factory, monkeypatch) -> None:
    runs: list[int] = []

    async def failing(self, now=None):
        runs.append(1)
        raise RuntimeError("db locked")

    monkeypatch.setattr(repositories.Storage, "purge_expired", failing)
    async with api_factory(purge_interval_s=0.05) as api:
        await _wait(lambda: len(runs) >= 2)
        assert (await api.client.get(f"{API}/health")).status_code == 200


# ---- S7: appointment / feedback caps and request-code collisions --------------------------------------
async def test_s7_three_appointment_requests_per_session(api) -> None:
    token = await api.token()
    for _ in range(3):
        r = await api.client.post(f"{API}/appointments", json=APPOINTMENT, headers=_auth(token))
        assert r.status_code == 201
    r = await api.client.post(f"{API}/appointments", json=APPOINTMENT, headers=_auth(token))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1


async def test_s7_appointment_caps_per_ip_and_global(api_factory) -> None:
    async with api_factory(rate_rules=_rules(appointments_per_ip="2/day", appointments_global="3/day")) as api:
        for _ in range(2):
            r = await api.client.post(f"{API}/appointments", json=APPOINTMENT, headers=_auth(await api.token()))
            assert r.status_code == 201
        r = await api.client.post(f"{API}/appointments", json=APPOINTMENT, headers=_auth(await api.token()))
        assert r.status_code == 429, "per-IP daily cap"
        other = api.client_for("198.51.100.20")
        tok = (await other.post(f"{API}/session", json={"locale": "en"})).json()["session_token"]
        assert (await other.post(f"{API}/appointments", json=APPOINTMENT, headers=_auth(tok))).status_code == 201
        third = api.client_for("198.51.100.21")
        tok = (await third.post(f"{API}/session", json={"locale": "en"})).json()["session_token"]
        r = await third.post(f"{API}/appointments", json=APPOINTMENT, headers=_auth(tok))
        assert r.status_code == 429, "global daily cap"


async def test_s7_feedback_caps(api_factory) -> None:
    async with api_factory(rate_rules=_rules(feedback_per_session="1/day")) as api:
        token = await api.token()
        turn_id = (await api.chat(token, "hello")).first("meta").turn_id
        body = {"turn_id": turn_id, "rating": "up"}
        assert (await api.client.post(f"{API}/feedback", json=body, headers=_auth(token))).status_code == 204
        r = await api.client.post(f"{API}/feedback", json=body, headers=_auth(token))
        assert r.status_code == 429


async def test_s7_request_code_collision_is_retried(api, monkeypatch) -> None:
    codes = iter(["AR-AAAAAA", "AR-AAAAAA", "AR-BBBBBB"])
    monkeypatch.setattr(repositories, "new_request_code", lambda: next(codes))
    token = await api.token()
    first = await api.client.post(f"{API}/appointments", json=APPOINTMENT, headers=_auth(token))
    second = await api.client.post(f"{API}/appointments", json=APPOINTMENT, headers=_auth(token))
    assert (first.status_code, second.status_code) == (201, 201), second.text
    assert (first.json()["request_id"], second.json()["request_id"]) == ("AR-AAAAAA", "AR-BBBBBB")


# ---- S18: e-mail hygiene -----------------------------------------------------------------------------
async def test_s18_appointment_email_is_sanitised(api) -> None:
    token = await api.token()
    body = {**APPOINTMENT, "email": "jo​hn‮@example.org"}
    r = await api.client.post(f"{API}/appointments", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    async with api.container.storage.appointments._s() as db:
        row = (await db.scalars(select(AppointmentContactRow))).one()
    assert row.email == "john@example.org"


@pytest.mark.parametrize("email", ["<script>@x.org", 'a"b@example.org', "a@b<c>.org", "​@example.org"])
async def test_s18_markup_in_email_is_rejected(api, email) -> None:
    token = await api.token()
    r = await api.client.post(f"{API}/appointments", json={**APPOINTMENT, "email": email}, headers=_auth(token))
    assert r.status_code == 422


# ---- C10: demo profile outside demo mode ---------------------------------------------------------------
async def test_c10_demo_profile_is_not_served_when_demo_mode_is_off(api_factory) -> None:
    async with api_factory(AUSCULTA_DEMO_MODE=False) as api:
        assert (await api.client.get(f"{API}/hospital")).status_code == 404
        body = await api.session()
        assert (body["hospital"], body["demo_mode"]) == (None, False)
        res = await api.chat(body["session_token"], SELF_HARM)
        res.assert_contract()
        assert res.first("safety").contacts == ()
