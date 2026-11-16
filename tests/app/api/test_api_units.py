"""Unit tests of the API building blocks: tokens, client IP, turn registry, slot guard, SSE response,
middleware and the composition root."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app.api import container as container_mod
from app.api.container import Overrides, _session_secret, build_retriever_or_none
from app.api.deps import bearer_token, client_ip, seconds_to_utc_midnight
from app.api.errors import TurnInProgress, request_locale
from app.api.middleware import BodySizeLimitMiddleware
from app.api.sse import SSEResponse
from app.api.tokens import SessionTokenSigner
from app.api.turns import SlotGuard, TurnRegistry, _release_abandoned
from app.config_files import ConfigFileError
from core.errors import Unauthorized
from evals.fakes.asgi_driver import drive
from evals.fakes.fake_retriever import FakeRetriever

SECRET = b"k" * 32  # secret-scan: allow
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


# ---- tokens ----------------------------------------------------------------------------------------
def _signer(now: datetime = NOW) -> SessionTokenSigner:
    return SessionTokenSigner(SECRET, clock=lambda: now)


def test_token_round_trip_carries_only_session_and_expiry() -> None:
    token = _signer().issue("sid-1", NOW + timedelta(hours=2))
    claims = _signer().verify(token)
    assert claims.session_id == "sid-1"
    assert claims.expires_at == NOW + timedelta(hours=2)
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    assert set(payload) == {"sid", "exp", "v"}


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = SessionTokenSigner(b"z" * 32).issue("sid", NOW + timedelta(hours=1))
    with pytest.raises(Unauthorized):
        _signer().verify(token)


@pytest.mark.parametrize("mutate", ["payload", "signature"])
def test_tampered_token_is_rejected(mutate) -> None:
    payload, sig = _signer().issue("sid", NOW + timedelta(hours=1)).split(".")
    if mutate == "payload":
        payload = base64.urlsafe_b64encode(b'{"sid":"admin","exp":9999999999,"v":1}').decode().rstrip("=")
    else:
        sig = sig[:-2] + ("AA" if not sig.endswith("AA") else "BB")
    with pytest.raises(Unauthorized):
        _signer().verify(f"{payload}.{sig}")


def test_expired_token_is_rejected() -> None:
    token = _signer().issue("sid", NOW + timedelta(seconds=5))
    with pytest.raises(Unauthorized, match="expired"):
        _signer(NOW + timedelta(seconds=6)).verify(token)


def test_wrong_version_and_malformed_payloads_are_rejected() -> None:
    signer = _signer()
    for body in (b'{"sid":"s","exp":9999999999,"v":2}', b"[1,2]", b"not json", b'{"sid":"s"}'):
        payload = base64.urlsafe_b64encode(body).decode().rstrip("=")
        token = f"{payload}.{signer._sign(payload)}"
        with pytest.raises(Unauthorized):
            signer.verify(token)
    for token in ("", "x" * 600, "a.b.c", "nodot"):
        with pytest.raises(Unauthorized):
            signer.verify(token)


def test_short_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SessionTokenSigner(b"short")
    assert len(SessionTokenSigner.random_secret()) == 32


# ---- request helpers -------------------------------------------------------------------------------
def _request(headers: dict[str, str] | None = None, client=("10.0.0.5", 1234), query: str = "") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "client": client, "query_string": query.encode()})


@pytest.mark.parametrize(
    ("xff", "proxies", "expected"),
    [
        (None, 0, "10.0.0.5"),
        ("198.51.100.1", 0, "10.0.0.5"),  # no trusted proxy: the header is ignored
        ("198.51.100.1", 1, "198.51.100.1"),
        ("6.6.6.6, 198.51.100.1", 1, "198.51.100.1"),  # left entries are client-supplied
        ("6.6.6.6, 198.51.100.1, 172.16.0.2", 2, "198.51.100.1"),
        ("198.51.100.1", 2, "10.0.0.5"),  # fewer hops than proxies
        ("garbage", 1, "10.0.0.5"),
        ("2001:db8::1", 1, "2001:db8::1"),
    ],
)
def test_client_ip_honours_only_trusted_proxies(xff, proxies, expected) -> None:
    headers = {"X-Forwarded-For": xff} if xff else {}
    assert client_ip(_request(headers), proxies) == expected


def test_client_ip_without_peer() -> None:
    assert client_ip(_request(client=None), 0) == "0.0.0.0"


def test_bearer_token_parsing() -> None:
    assert bearer_token(_request({"Authorization": "bearer  abc.def "})) == "abc.def"
    for header in ({}, {"Authorization": "Token abc"}, {"Authorization": "Bearer   "}):
        with pytest.raises(Unauthorized):
            bearer_token(_request(header))


def test_request_locale_prefers_query_then_header() -> None:
    assert request_locale(_request({"Accept-Language": "ar"}, query="locale=fr")) == "fr"
    assert request_locale(_request({"Accept-Language": "ar-MA"})) == "ar"
    assert request_locale(_request({"Accept-Language": "de"}, query="locale=xx")) == "en"


def test_seconds_to_utc_midnight() -> None:
    assert seconds_to_utc_midnight(datetime(2026, 11, 16, 23, 59, 30, tzinfo=UTC)) == 30
    assert seconds_to_utc_midnight(datetime(2026, 11, 16, 23, 59, 59, 999999, tzinfo=UTC)) == 1
    assert 0 < seconds_to_utc_midnight() <= 86400


# ---- turn registry, slot guard ---------------------------------------------------------------------
def test_registry_single_flight_replay_and_ownership() -> None:
    clock = [0.0]
    reg = TurnRegistry(ttl_s=10, max_entries=2, clock=lambda: clock[0])
    reg.begin("s1", "c1")
    with pytest.raises(TurnInProgress):
        reg.begin("s1", "c2")
    reg.begin("s2", "c1")
    assert reg.running == 2
    reg.finish("s1", "c1", "t1", ("frame",))
    assert reg.replay("s1", "c1") == ("frame",)
    assert reg.owns("t1", "s1")
    assert not reg.owns("t1", "s2")
    reg.abandon("s2", "other")  # wrong client turn: claim kept
    assert reg.running == 1
    reg.abandon("s2", "c1")
    assert reg.running == 0
    clock[0] = 11
    assert reg.replay("s1", "c1") is None  # expired


def test_registry_bounds_replay_entries() -> None:
    reg = TurnRegistry(ttl_s=100, max_entries=2, clock=lambda: 0.0)
    for i in range(4):
        reg.begin(f"s{i}", "c")
        reg.finish(f"s{i}", "c", f"t{i}", (f"f{i}",))
    assert reg.replay("s0", "c") is None
    assert reg.replay("s3", "c") == ("f3",)
    reg.finish("s9", "c", "t9", None)  # cancelled turns are not replayable
    assert reg.replay("s9", "c") is None
    assert reg.owns("t9", "s9")


def test_slot_guard_releases_once() -> None:
    released: list[int] = []
    guard = SlotGuard(lambda: released.append(1))
    guard.release()
    guard.release()
    assert released == [1]
    assert guard.released


def test_abandoned_stream_finalizer_frees_slot_and_claim() -> None:
    released: list[int] = []
    reg = TurnRegistry()
    reg.begin("s", "c")
    guard = SlotGuard(lambda: released.append(1))
    _release_abandoned(guard, reg, "s", "c")
    _release_abandoned(guard, reg, "s", "c")
    _release_abandoned(None, reg, "s", "c")
    assert released == [1]
    assert reg.running == 0


# ---- SSE response and middleware -------------------------------------------------------------------
async def test_sse_response_runs_on_close_when_the_body_never_starts() -> None:
    closed: list[str] = []

    async def body():
        await asyncio.sleep(10)
        yield "never"

    async def on_close() -> None:
        closed.append("closed")

    response = SSEResponse(body(), on_close=on_close)
    result = await drive(response, "POST", "/x", disconnect_after_s=0.01)
    assert closed == ["closed"]
    assert result.chunks == []
    assert result.elapsed_s < 1


async def test_sse_response_survives_a_send_failure() -> None:
    closed: list[str] = []

    async def body():
        for i in range(100):
            yield f"data: {i}\n\n"
            await asyncio.sleep(0)

    async def on_close() -> None:
        closed.append("closed")

    response = SSEResponse(body(), on_close=on_close, headers={"X-Test": "1"})
    result = await drive(response, "POST", "/x", disconnect_after_chunks=2)
    assert result.headers["x-test"] == "1"
    assert result.headers["cache-control"] == "no-store"
    assert closed == ["closed"]


async def _echo_app(scope, receive, send) -> None:
    message = await receive()
    await PlainTextResponse(str(len(message.get("body", b""))))(scope, receive, send)


def _reject(_scope):
    return PlainTextResponse("too large", status_code=413)


@pytest.mark.parametrize(("length", "status"), [("abc", 413), ("-1", 413), ("100000", 413), ("10", 200)])
async def test_body_limit_checks_declared_length(length, status) -> None:
    app = BodySizeLimitMiddleware(_echo_app, max_bytes=50, reject=_reject)
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"x" * 10, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/", "headers": [(b"content-length", length.encode())]}
    await app(scope, receive, send)
    assert sent[0]["status"] == status


async def test_body_limit_passes_non_http_scopes() -> None:
    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    await BodySizeLimitMiddleware(inner, max_bytes=1, reject=_reject)({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]


# ---- composition root ------------------------------------------------------------------------------
def test_session_secret_rules(settings_factory) -> None:
    assert _session_secret(settings_factory()) == b"test-session-secret-0123456789abcdef-0123456789"
    with pytest.raises(ConfigFileError, match="at least 32"):
        _session_secret(settings_factory(AUSCULTA_SESSION_SECRET="short"))
    with pytest.raises(ConfigFileError, match="required"):
        _session_secret(settings_factory(AUSCULTA_SESSION_SECRET=None, AUSCULTA_ENV="prod"))
    ephemeral = _session_secret(settings_factory(AUSCULTA_SESSION_SECRET=None, AUSCULTA_ENV="dev"))
    assert len(ephemeral) == 32


def test_fake_backend_uses_the_fake_retriever(settings_factory) -> None:
    assert isinstance(build_retriever_or_none(settings_factory(), llm=None), FakeRetriever)


def test_missing_rag_module_degrades_to_no_retriever(settings_factory, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "rag.retrieval", None)  # import raises ImportError
    assert build_retriever_or_none(settings_factory(AUSCULTA_LLM_BACKEND="gemini"), llm=None) is None


def test_failing_retriever_build_degrades_to_no_retriever(settings_factory, monkeypatch) -> None:
    def broken(*_a, **_k):
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setitem(sys.modules, "rag.retrieval", SimpleNamespace(build_retriever=broken))
    assert build_retriever_or_none(settings_factory(AUSCULTA_LLM_BACKEND="gemini"), llm=None) is None


def test_real_retriever_is_built_lazily(settings_factory, monkeypatch) -> None:
    sentinel = FakeRetriever(version="real")
    monkeypatch.setitem(
        sys.modules, "rag.retrieval", SimpleNamespace(build_retriever=lambda settings, llm: sentinel)
    )
    assert build_retriever_or_none(settings_factory(AUSCULTA_LLM_BACKEND="gemini"), llm=None) is sentinel


def test_gemini_backend_uses_the_llm_factory(settings_factory, monkeypatch) -> None:
    built: list[object] = []

    def fake_factory(settings, *, spend):
        built.append(spend)
        return "provider"

    monkeypatch.setitem(sys.modules, "app.llm.factory", SimpleNamespace(build_llm_provider=fake_factory))
    llm = container_mod._llm(settings_factory(AUSCULTA_LLM_BACKEND="gemini"), Overrides(), spend="meter")
    assert llm == "provider"
    assert built == ["meter"]


def test_fake_backend_without_override_uses_the_scripted_provider(settings_factory) -> None:
    from evals.fakes.fake_llm import FakeLLMProvider

    llm = container_mod._llm(settings_factory(), Overrides(), spend=None)
    assert isinstance(llm, FakeLLMProvider)


def test_redis_url_selects_redis_backed_stores(settings_factory) -> None:
    class FakeRedis:
        def register_script(self, _src):
            return None

    c = container_mod.build_container(
        settings_factory(REDIS_URL="redis://127.0.0.1:6390/0"),
        Overrides(redis_client=FakeRedis(), retriever=None),
    )
    assert type(c.sessions).__name__ == "RedisSessionStore"
    assert type(c.spend).__name__ == "RedisSpendMeter"


async def test_container_lifecycle_and_degraded_paths(api_factory, monkeypatch) -> None:
    closed: list[str] = []

    class ClosingRetriever(FakeRetriever):
        async def aclose(self) -> None:
            closed.append("aclose")

        @property
        def corpus_version(self) -> str:
            raise RuntimeError("manifest unreadable")

        async def health(self) -> bool:
            raise ConnectionError("down")

    async with api_factory(retriever=ClosingRetriever()) as api:
        c = api.container
        assert c.release().corpus_version == c.engine.release.corpus_version
        assert (await c.ready_checks())["retriever"] is False
        await c.startup()  # idempotent
    assert closed == ["aclose"]


async def test_startup_survives_a_purge_failure(api_factory, monkeypatch) -> None:
    async with api_factory() as api:
        c = api.container

        async def broken():
            raise RuntimeError("db locked")

        monkeypatch.setattr(c.storage.appointments, "purge_expired", broken)
        c.started = False
        await c.startup()
        assert c.started


async def test_shutdown_survives_a_failing_retriever_close(api_factory) -> None:
    class BadClose(FakeRetriever):
        def close(self) -> None:
            raise RuntimeError("boom")

    async with api_factory(retriever=BadClose()) as api:
        assert api.container.started
    assert not api.container.started
