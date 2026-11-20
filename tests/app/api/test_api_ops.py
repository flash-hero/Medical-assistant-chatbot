"""Session creation, operations endpoints, error envelope, security headers, CORS and the body size limit,
all through the real ASGI app (create_app) with the scripted fake LLM."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.api.middleware import DEFAULT_MAX_BODY_BYTES, SECURITY_HEADERS
from app.hospital.profile import ProfileState
from app.pipeline.factory import EngineConfig
from evals.fakes.fake_retriever import FakeRetriever

API = "/api/v1"


def _assert_envelope(r, status: int, code: str) -> dict:
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) >= {"error"}
    assert set(body["error"]) == {"code", "message", "retry_after_s"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    return body["error"]


# ---- sessions --------------------------------------------------------------------------------------
async def test_create_session_returns_contract_fields(api) -> None:
    r = await api.client.post(f"{API}/session", json={"locale": "fr"})
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"session_token", "session_id", "expires_at", "turns_left", "hospital", "demo_mode"}
    assert body["turns_left"] == 20
    assert body["demo_mode"] is True
    assert body["hospital"]["id"] == "hopital_demo_ausculta"
    assert "démonstration" in body["hospital"]["name"]  # resolved to the session locale
    assert datetime.fromisoformat(body["expires_at"]) > datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    assert api.container.signer.verify(body["session_token"]).session_id == body["session_id"]
    assert await api.container.sessions.get(body["session_id"]) is not None


async def test_session_without_profile_has_no_hospital(api_factory, engine_config: EngineConfig) -> None:
    cfg = EngineConfig(**{**engine_config.__dict__, "profile_state": ProfileState(None, "missing")})
    async with api_factory(config=cfg) as api:
        body = await api.session()
        assert body["hospital"] is None
        r = await api.client.get(f"{API}/hospital")
        _assert_envelope(r, 404, "not_found")


@pytest.mark.parametrize(
    "payload",
    [{"locale": "de"}, {"locale": "en", "extra": 1}, ["en"]],
    ids=["unknown-locale", "extra-field", "not-an-object"],
)
async def test_invalid_session_body_is_422_envelope(api, payload) -> None:
    r = await api.client.post(f"{API}/session", json=payload)
    err = _assert_envelope(r, 422, "invalid_input")
    assert err["retry_after_s"] is None
    assert "retry-after" not in r.headers


async def test_session_creation_is_rate_limited_per_ip(api_factory) -> None:
    async with api_factory(AUSCULTA_RATE_IP_MIN=2) as api:  # session creation: rate_ip // 2 = 1 per minute
        assert (await api.client.post(f"{API}/session", json={})).status_code == 201
        r = await api.client.post(f"{API}/session", json={})
        err = _assert_envelope(r, 429, "rate_limited")
        assert int(r.headers["retry-after"]) >= 1
        assert err["retry_after_s"] >= 1


@pytest.mark.parametrize(("proxies", "second_status"), [(1, 201), (0, 429)])
async def test_trusted_proxy_count_decides_which_ip_is_limited(api_factory, proxies, second_status) -> None:
    async with api_factory(AUSCULTA_RATE_IP_MIN=2, AUSCULTA_TRUSTED_PROXY_COUNT=proxies) as api:
        first = await api.client.post(f"{API}/session", json={}, headers={"X-Forwarded-For": "192.0.2.1"})
        second = await api.client.post(f"{API}/session", json={}, headers={"X-Forwarded-For": "192.0.2.2"})
        assert first.status_code == 201
        assert second.status_code == second_status


# ---- operations ------------------------------------------------------------------------------------
async def test_health_is_dependency_free(api) -> None:
    r = await api.client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_ready_reports_every_check(api) -> None:
    r = await api.client.get(f"{API}/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["paused"] is False
    assert all(body["checks"].values())


@pytest.mark.parametrize("retriever", [None, FakeRetriever(healthy=False)], ids=["missing", "unhealthy"])
async def test_ready_is_503_with_retry_after_when_the_retriever_is_down(api_factory, retriever) -> None:
    async with api_factory(retriever=retriever) as api:
        r = await api.client.get(f"{API}/ready?locale=ar")
        err = _assert_envelope(r, 503, "dependency_unavailable")
        assert r.headers["retry-after"] == "10"
        assert r.json()["checks"]["retriever"] is False
        assert "الخدمات" in err["message"]  # localised from ?locale=


async def test_ready_reports_kill_switch_without_failing(api_factory) -> None:
    async with api_factory(AUSCULTA_KILL_SWITCH=True) as api:
        r = await api.client.get(f"{API}/ready")
        assert r.status_code == 200
        assert r.json()["paused"] is True


async def test_meta_exposes_the_release_tuple(api) -> None:
    r = await api.client.get(f"{API}/meta")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"app_version", "corpus_version", "prompt_hash", "models", "demo_mode"}
    assert body["corpus_version"] == "fake-corpus-1"
    assert body["models"]["answer"].startswith("fake:")
    assert body["prompt_hash"] == api.container.engine.release.prompt_hash


async def test_meta_follows_a_corpus_promotion(api) -> None:
    api.retriever.version = "corpus-2026-12-01"
    assert (await api.client.get(f"{API}/meta")).json()["corpus_version"] == "corpus-2026-12-01"


@pytest.mark.parametrize(("locale", "needle"), [("en", "demo hospital"), ("ar", "مستشفى")])
async def test_hospital_is_resolved_to_the_requested_locale(api, locale, needle) -> None:
    r = await api.client.get(f"{API}/hospital", params={"locale": locale})
    assert r.status_code == 200
    body = r.json()
    assert needle in body["name"]
    assert {"id", "name", "is_demo", "emergency", "crisis_lines", "handoff", "departments"} <= set(body)
    dept = body["departments"][0]
    assert set(dept) == {"id", "name", "location", "hours", "accepts_appointments"}
    assert all(isinstance(d["name"], str) for d in body["departments"])


async def test_hospital_locale_falls_back_to_accept_language(api) -> None:
    r = await api.client.get(f"{API}/hospital", headers={"Accept-Language": "fr-FR,fr;q=0.9"})
    assert "démonstration" in r.json()["name"]


# ---- envelope, headers, CORS, body size ------------------------------------------------------------
async def test_unknown_route_and_wrong_method_use_the_envelope(api) -> None:
    _assert_envelope(await api.client.get(f"{API}/nope"), 404, "not_found")
    _assert_envelope(await api.client.get(f"{API}/chat"), 405, "not_found")


async def test_security_headers_on_success_and_error(api) -> None:
    for r in (await api.client.get(f"{API}/health"), await api.client.get(f"{API}/nope")):
        for name, value in SECURITY_HEADERS:
            assert r.headers[name] == value
        assert r.headers["cache-control"] == "no-store"
        assert "strict-transport-security" not in r.headers


async def test_hsts_only_in_staging_and_prod(api_factory) -> None:
    from evals.fakes.fake_redis import FakeRedis

    staging = {  # the smallest configuration core/config.py accepts for staging (review P11/S14)
        "AUSCULTA_ENV": "staging",
        "AUSCULTA_ALLOW_FAKE": True,
        "REDIS_URL": "redis://127.0.0.1:6390/0",
        "DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:1/db",
    }
    async with api_factory(redis_client=FakeRedis(), **staging) as api:
        r = await api.client.get(f"{API}/health")
        assert r.headers["strict-transport-security"].startswith("max-age=")
        assert (await api.client.get(f"{API}/openapi.json")).status_code == 404  # docs off outside dev/test


async def test_cors_preflight_for_an_allowed_origin(api) -> None:
    r = await api.client.options(
        f"{API}/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in r.headers


async def test_cors_rejects_other_origins(api) -> None:
    pre = await api.client.options(
        f"{API}/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert pre.status_code == 400
    assert "access-control-allow-origin" not in pre.headers
    simple = await api.client.get(f"{API}/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


async def test_configured_origins_replace_the_defaults(api_factory) -> None:
    async with api_factory(AUSCULTA_ALLOWED_ORIGINS="https://chat.hopital.example") as api:
        ok = await api.client.get(f"{API}/health", headers={"Origin": "https://chat.hopital.example"})
        old = await api.client.get(f"{API}/health", headers={"Origin": "http://localhost:3000"})
        assert ok.headers["access-control-allow-origin"] == "https://chat.hopital.example"
        assert "access-control-allow-origin" not in old.headers


async def test_body_over_the_limit_is_413_by_content_length(api) -> None:
    big = json.dumps({"locale": "en", "pad": "x" * DEFAULT_MAX_BODY_BYTES})
    r = await api.client.post(f"{API}/session", content=big, headers={"Content-Type": "application/json"})
    _assert_envelope(r, 413, "payload_too_large")


async def test_streamed_body_over_the_limit_is_413(api) -> None:
    async def chunks():
        for _ in range(5):
            yield b"x" * (DEFAULT_MAX_BODY_BYTES // 4)

    r = await api.client.post(
        f"{API}/session", content=chunks(), headers={"Content-Type": "application/json"}
    )
    _assert_envelope(r, 413, "payload_too_large")


async def test_unexpected_errors_become_a_500_envelope(api, monkeypatch) -> None:
    async def boom() -> dict:
        raise RuntimeError("secret detail that must not leak")

    monkeypatch.setattr(api.container, "ready_checks", boom)
    api.client._transport.raise_app_exceptions = False  # the server error middleware re-raises after replying
    r = await api.client.get(f"{API}/ready")
    _assert_envelope(r, 500, "internal_error")
    assert "secret detail" not in r.text
