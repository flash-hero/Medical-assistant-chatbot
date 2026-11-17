"""POST /api/v1/appointments and POST /api/v1/feedback through the real ASGI app."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.hospital.profile import ProfileState
from app.pipeline.factory import EngineConfig
from app.storage.models import AppointmentContactRow, AuditEventRow, FeedbackRow

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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _rows(api, model) -> list:
    factory = api.container.storage.appointments._s
    async with factory() as db:
        return list((await db.scalars(select(model))).all())


# ---- appointments ----------------------------------------------------------------------------------
async def test_valid_appointment_request_is_stored_for_staff_only(api) -> None:
    token = await api.token("fr")
    calls = len(api.llm.calls)
    r = await api.client.post(f"{API}/appointments", json=VALID, headers=_auth(token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"request_id", "message"}
    assert body["request_id"] in body["message"]
    assert len(api.llm.calls) == calls, "appointment data must never reach the model"
    contacts = await _rows(api, AppointmentContactRow)
    assert [(c.full_name, c.phone, c.request_id) for c in contacts] == [
        ("Test Patient", "+33 1 00 00 00 99", body["request_id"])
    ]
    audit = [a for a in await _rows(api, AuditEventRow) if a.event_type == "appointment_request"]
    assert audit
    assert "Test Patient" not in str(audit[0].detail)


async def test_confirmation_follows_the_session_locale_or_query(api) -> None:
    token = await api.token("fr")
    fr = await api.client.post(f"{API}/appointments", json=VALID, headers=_auth(token))
    en = await api.client.post(f"{API}/appointments?locale=en", json=VALID, headers=_auth(token))
    assert fr.json()["message"] != en.json()["message"]


async def test_form_text_is_sanitised(api) -> None:
    token = await api.token()
    payload = {**VALID, "full_name": "Test‮ Patient​", "reason": "pain\u0007 in knee"}
    r = await api.client.post(f"{API}/appointments", json=payload, headers=_auth(token))
    assert r.status_code == 201
    contact = (await _rows(api, AppointmentContactRow))[0]
    assert "‮" not in contact.full_name
    assert "\u0007" not in (contact.reason or "")


@pytest.mark.parametrize(
    "change",
    [
        {"department_id": "laboratory"},  # exists but does not accept appointment requests
        {"department_id": "neurosurgery"},  # unknown
        {"department_id": "Cardiology!"},  # pattern
        {"consent": False},
        {"phone": "call me"},
        {"email": "not-an-email"},
        {"full_name": ""},
        {"full_name": "​​"},  # empty after sanitising
        {"reason": "x" * 501},
        {"unexpected": "field"},
    ],
    ids=[
        "not-bookable",
        "unknown-dept",
        "bad-dept-id",
        "no-consent",
        "bad-phone",
        "bad-email",
        "empty-name",
        "invisible-name",
        "long-reason",
        "extra-field",
    ],
)
async def test_invalid_appointment_requests_are_422(api, change) -> None:
    token = await api.token()
    r = await api.client.post(f"{API}/appointments", json={**VALID, **change}, headers=_auth(token))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "invalid_input"
    assert await _rows(api, AppointmentContactRow) == []


async def test_empty_email_is_accepted_as_none(api) -> None:
    token = await api.token()
    r = await api.client.post(f"{API}/appointments", json={**VALID, "email": ""}, headers=_auth(token))
    assert r.status_code == 201
    assert (await _rows(api, AppointmentContactRow))[0].email is None


async def test_appointments_need_a_session(api) -> None:
    r = await api.client.post(f"{API}/appointments", json=VALID)
    assert r.status_code == 401


async def test_appointments_unavailable_without_a_profile(api_factory, engine_config) -> None:
    cfg = EngineConfig(**{**engine_config.__dict__, "profile_state": ProfileState(None, "missing")})
    async with api_factory(config=cfg) as api:
        r = await api.client.post(f"{API}/appointments", json=VALID, headers=_auth(await api.token()))
        assert r.status_code == 404


async def test_database_failure_is_503(api, monkeypatch) -> None:
    async def down(*_a, **_k):
        raise OperationalError("INSERT", {}, Exception("disk I/O error"))

    monkeypatch.setattr(api.container.storage.appointments, "create", down)
    r = await api.client.post(f"{API}/appointments", json=VALID, headers=_auth(await api.token()))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "dependency_unavailable"
    assert "retry-after" in r.headers


# ---- feedback --------------------------------------------------------------------------------------
async def test_feedback_on_an_own_turn_is_stored_redacted(api) -> None:
    token = await api.token()
    turn_id = (await api.chat(token, "What is a fever?")).first("meta").turn_id
    comment = "Wrong answer, call me at +33 6 12 34 56 78 or jane.doe@example.org"
    r = await api.client.post(
        f"{API}/feedback",
        json={"turn_id": turn_id, "rating": "down", "reason": "incorrect", "comment": comment},
        headers=_auth(token),
    )
    assert r.status_code == 204
    assert r.content == b""
    row = (await _rows(api, FeedbackRow))[0]
    assert (row.turn_id, row.rating, row.reason) == (turn_id, "down", "incorrect")
    assert "12 34 56 78" not in row.comment
    assert "jane.doe@example.org" not in row.comment


async def test_feedback_after_restart_uses_the_database(api) -> None:
    token = await api.token()
    turn_id = (await api.chat(token, "hello")).first("meta").turn_id
    api.container.registry._turn_owner.clear()  # in-memory ownership lost (restart)
    r = await api.client.post(
        f"{API}/feedback", json={"turn_id": turn_id, "rating": "up"}, headers=_auth(token)
    )
    assert r.status_code == 204
    assert (await _rows(api, FeedbackRow))[0].comment is None


async def test_feedback_on_another_sessions_turn_is_404(api) -> None:
    owner = await api.token()
    turn_id = (await api.chat(owner, "hello")).first("meta").turn_id
    other = await api.token()
    for tid in (turn_id, str(uuid.uuid4())):
        r = await api.client.post(
            f"{API}/feedback", json={"turn_id": tid, "rating": "up"}, headers=_auth(other)
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "payload",
    [
        {"turn_id": "nope", "rating": "up"},
        {"turn_id": str(uuid.uuid4()), "rating": "meh"},
        {"turn_id": str(uuid.uuid4()), "rating": "up", "reason": "boring"},
        {"turn_id": str(uuid.uuid4()), "rating": "up", "comment": "x" * 501},
    ],
    ids=["bad-turn-id", "bad-rating", "bad-reason", "long-comment"],
)
async def test_invalid_feedback_is_422(api, payload) -> None:
    r = await api.client.post(f"{API}/feedback", json=payload, headers=_auth(await api.token()))
    assert r.status_code == 422


async def test_feedback_database_failure_is_503(api, monkeypatch) -> None:
    token = await api.token()
    turn_id = (await api.chat(token, "hello")).first("meta").turn_id

    async def down(**_k):
        raise OperationalError("INSERT", {}, Exception("locked"))

    monkeypatch.setattr(api.container.storage.feedback, "add", down)
    r = await api.client.post(
        f"{API}/feedback", json={"turn_id": turn_id, "rating": "up"}, headers=_auth(token)
    )
    assert r.status_code == 503
