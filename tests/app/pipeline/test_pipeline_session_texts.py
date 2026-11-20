"""Unit tests: session state and stores, fixed texts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config_files import ConfigFileError
from app.pipeline.session import MemorySessionStore, RedisSessionStore, SessionState
from app.pipeline.texts import (
    RESPONSES_PATH,
    SAFETY_TEMPLATES_PATH,
    contacts_for,
    form_label,
    load_texts,
    render,
)
from core.schemas.chat import RiskKind
from evals.fakes.fake_redis import FakeRedis


def _state(sid: str = "s1", *, minutes: int = 120) -> SessionState:
    now = datetime.now(UTC)
    return SessionState(
        session_id=sid, locale="en", created_at=now, expires_at=now + timedelta(minutes=minutes)
    )


# ---- SessionState --------------------------------------------------------------------------------
def test_session_state_transitions_return_new_objects() -> None:
    s0 = _state()
    s1 = s0.with_turn("first", window=2).with_turn("second", window=2).with_turn("third", window=2)
    assert s0.turns_used == 0
    assert s0.history == ()
    assert s1.turns_used == 3
    assert s1.user_history() == ("second", "third")
    assert s0.with_turn("x", window=0).history == ()
    s2 = s1.with_risks(frozenset({RiskKind.EMERGENCY})).with_risks(frozenset({RiskKind.SELF_HARM}))
    assert s2.sticky_risks == {RiskKind.EMERGENCY, RiskKind.SELF_HARM}
    s3 = s2.with_strike(2)
    assert (s3.strikes, s3.locked) == (1, False)
    s4 = s3.with_strike(2)
    assert (s4.strikes, s4.locked) == (2, True)


def test_session_state_json_round_trip() -> None:
    s = _state().with_turn("مرحبا", window=6).with_risks(frozenset({RiskKind.SELF_HARM})).with_strike(3)
    raw = s.to_json()
    assert "مرحبا" in raw  # ensure_ascii=False keeps Arabic readable
    assert SessionState.from_json(raw) == s


# ---- MemorySessionStore ---------------------------------------------------------------------------
async def test_memory_store_get_put_and_ttl() -> None:
    now = [0.0]
    store = MemorySessionStore(clock=lambda: now[0])
    assert await store.get("nope") is None
    await store.put(_state("a"))
    assert (await store.get("a")).session_id == "a"  # type: ignore[union-attr]
    now[0] = 2 * 60 * 60 + 1
    assert await store.get("a") is None
    assert await store.ping() is True


async def test_memory_store_drops_expired_sessions_and_evicts_oldest() -> None:
    store = MemorySessionStore(max_sessions=2)
    await store.put(_state("old", minutes=-1))
    assert await store.get("old") is None
    for sid in ("a", "b", "c"):
        await store.put(_state(sid))
    assert await store.get("a") is None
    assert await store.get("c") is not None


# ---- RedisSessionStore -----------------------------------------------------------------------------
async def test_redis_store_round_trip_with_ttl() -> None:
    r = FakeRedis()
    store = RedisSessionStore(r)
    state = _state("x").with_turn("hi", window=3).with_risks(frozenset({RiskKind.EMERGENCY}))
    await store.put(state)
    for key in ("ausculta:s2:x", "ausculta:s2:x:risks", "ausculta:s2:x:history"):
        assert 0 < await r.ttl(key) <= 7200
    assert await store.get("x") == state
    assert await store.get("missing") is None
    assert await store.ping() is True
    r.fail = ConnectionError("down")
    assert await store.ping() is False


# ---- texts ---------------------------------------------------------------------------------------
def test_texts_render_profile_values(engine_config) -> None:
    texts, profile = engine_config.texts, engine_config.profile_state.profile
    msg = texts.response("refusal_harmful", "en", profile)
    assert profile.emergency.number in msg
    assert profile.crisis_lines[0].number in msg
    generic = texts.response("refusal_harmful", "fr", None)
    assert texts.fallback_number["fr"] in generic
    assert "{" not in generic
    assert "7" in texts.notice("session_limit_near", "en", None, turns_left=7)
    assert texts.label("hours", "ar") == "مواعيد العمل"


def test_texts_errors_fall_back_to_internal_error(engine_config) -> None:
    texts = engine_config.texts
    assert texts.error("rate_limited", "fr").startswith("Trop")
    assert texts.error("no_such_code", "en") == texts.error("internal_error", "en")


@pytest.mark.parametrize("code", ["dependency_unavailable", "overloaded", "service_paused"])
@pytest.mark.parametrize("locale", ["en", "fr", "ar"])
def test_503_errors_name_the_emergency_and_crisis_numbers(engine_config, code: str, locale: str) -> None:
    """P5-D8: a refused request still points at urgent help, with the hospital's numbers when known."""
    texts, profile = engine_config.texts, engine_config.profile_state.profile
    msg = texts.error(code, locale, profile)
    assert profile.emergency.number in msg
    assert profile.crisis_lines[0].number in msg
    generic = texts.error(code, locale)
    assert texts.call_fallback[locale] in generic
    assert "{" not in generic
    assert "{" not in msg


def test_render_ignores_unknown_placeholders_and_falls_back_to_english() -> None:
    assert render({"en": "a {missing} b"}, "fr", {}) == "a  b"
    assert render({"en": "x", "fr": ""}, "fr", {}) == "x"


def test_contacts_for_resolves_selectors(engine_config) -> None:
    profile = engine_config.profile_state.profile
    assert contacts_for(("emergency",), None, "en") == ()
    contacts = contacts_for(
        ("emergency", "emergency", "crisis_lines", "handoff", "poison_control", "bogus"), profile, "fr"
    )
    numbers = [c.number for c in contacts]
    assert numbers[0] == profile.emergency.number
    assert len(numbers) == len(set(numbers))
    first_crisis = profile.crisis_lines[0].number
    digits = "".join(ch for ch in first_crisis if ch.isdigit())
    assert [c.number for c in contacts_for((f"crisis_line:{digits}",), profile, "en")] == [first_crisis]
    no_poison = profile.model_copy(update={"poison_control": None})
    assert contacts_for(("poison_control",), no_poison, "en") == ()


def test_form_label(engine_config) -> None:
    assert form_label(engine_config.texts, ("fields", "phone"), "ar") == "رقم الهاتف"


def _copy_configs(tmp_path: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    safety = yaml.safe_load(SAFETY_TEMPLATES_PATH.read_text(encoding="utf-8"))
    responses = yaml.safe_load(RESPONSES_PATH.read_text(encoding="utf-8"))
    return tmp_path / "s.yaml", tmp_path / "r.yaml", safety, responses


def _write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.mark.parametrize(
    "breaker",
    [
        lambda s, r: r["responses"]["busy"].update({"en": "call {secret_field}"}),
        lambda s, r: s["safety"].pop("abuse_disclosure"),
        lambda s, r: s["safety"]["emergency"].update({"template_id": ""}),
        lambda s, r: r["responses"]["busy"].pop("ar"),
        lambda s, r: r.pop("form"),
        lambda s, r: r.update({"notices": ["not", "a", "mapping"]}),
        lambda s, r: r["form"]["fields"]["phone"].pop("fr"),
    ],
)
def test_load_texts_rejects_malformed_files(tmp_path: Path, breaker) -> None:
    s_path, r_path, safety, responses = _copy_configs(tmp_path)
    breaker(safety, responses)
    _write(s_path, safety)
    _write(r_path, responses)
    with pytest.raises(ConfigFileError):
        load_texts(s_path, r_path)


def test_load_texts_accepts_the_shipped_files(tmp_path: Path) -> None:
    s_path, r_path, safety, responses = _copy_configs(tmp_path)
    safety.pop("approval", None)
    _write(s_path, safety)
    _write(r_path, responses)
    texts = load_texts(s_path, r_path)
    assert texts.approval_status == "draft"
    assert set(texts.safety) == {"emergency", "self_harm", "harm_to_others", "abuse_disclosure"}
