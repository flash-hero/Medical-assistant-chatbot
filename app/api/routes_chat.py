"""POST /api/v1/session and POST /api/v1/chat (SSE over POST).

Pre-stream checks, in order (each failure is a JSON error, never a stream):
  kill switch (503) -> token (401) -> IP / session rate limits (429) -> session state (401)
  -> message length (422) -> idempotent replay of a completed client_turn_id -> session turn budget (429)
  -> one running turn per session (409) -> [model-backed turns only] daily spend cap (503)
  -> admission slot (503 + Retry-After).
Emergency / self-harm turns detected by the deterministic precheck need no model and skip the spend cap and
the admission queue, so the safety template is never delayed or rejected by load.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import anyio
from fastapi import APIRouter, Request
from sqlalchemy.exc import SQLAlchemyError

from app.api.container import Container
from app.api.deps import (
    authenticate,
    client_ip,
    ensure_not_paused,
    ensure_spend_available,
    get_container,
)
from app.api.schemas import ChatBody, SessionCreate, SessionCreated
from app.api.sse import SSEResponse
from app.api.tokens import TOKEN_LIFETIME
from app.api.turns import SlotGuard, TurnStream, replay_frames
from app.guardrails.ingress import process_ingress
from app.guardrails.router import Precheck
from app.hospital.public import public_hospital
from app.pipeline.engine import TurnRequest
from app.pipeline.record import TurnRecord, TurnTrace
from app.pipeline.session import SessionState
from core.errors import DependencyUnavailable, InvalidInput, SessionExhausted

router = APIRouter()


@router.post("/session", status_code=201)
async def create_session(body: SessionCreate, request: Request) -> SessionCreated:
    c = get_container(request)
    await c.rate.check_session_create(client_ip(request, c.settings.trusted_proxy_count))
    now = datetime.now(UTC)
    expires = now + TOKEN_LIFETIME
    state = SessionState(session_id=str(uuid.uuid4()), locale=body.locale, created_at=now, expires_at=expires)
    try:
        await c.storage.sessions.create(state, demo_mode=c.settings.demo_mode)
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database unavailable") from exc
    await c.sessions.put(state)
    profile = c.profile()
    return SessionCreated(
        session_token=c.signer.issue(state.session_id, expires),
        session_id=state.session_id,
        expires_at=expires.isoformat(),
        turns_left=c.settings.max_turns_per_session,
        hospital=public_hospital(profile, body.locale) if profile is not None else None,
        demo_mode=c.settings.demo_mode,
    )


def _model_free(c: Container, precheck: Precheck, session: SessionState) -> bool:
    """True when the engine will answer from templates only (no model call can happen)."""
    return bool(precheck.safety_kinds & c.config.safety.block_medical_after) or session.locked


@router.post("/chat")
async def chat(body: ChatBody, request: Request) -> SSEResponse:
    c = get_container(request)
    ensure_not_paused(c)
    auth = await authenticate(request, c)
    session = auth.session
    if len(body.message) > c.settings.max_message_chars:
        raise InvalidInput("message too long", detail={"max_chars": c.settings.max_message_chars})
    client_turn_id = str(body.client_turn_id)
    frames = c.registry.replay(session.session_id, client_turn_id)
    if frames is not None:
        return SSEResponse(replay_frames(frames))
    if session.turns_used >= c.settings.max_turns_per_session:
        left_s = (session.expires_at - datetime.now(UTC)).total_seconds()
        raise SessionExhausted("turn budget used", detail={"retry_after_s": max(1.0, left_s)})
    ingress = process_ingress(body.message, max_chars=c.settings.max_message_chars, today=c.today())
    precheck = await anyio.to_thread.run_sync(c.engine.precheck, ingress)
    c.registry.begin(session.session_id, client_turn_id)
    try:
        slot = None
        if not _model_free(c, precheck, session):
            await ensure_spend_available(c)
            await c.admission.acquire()
            slot = SlotGuard(c.admission.release)
    except BaseException:
        c.registry.abandon(session.session_id, client_turn_id)
        raise
    stream = _turn_stream(c, body, session, ingress, precheck, slot)
    return SSEResponse(stream.frames(), on_close=stream.close)


def _turn_stream(
    c: Container,
    body: ChatBody,
    session: SessionState,
    ingress: object,
    precheck: Precheck,
    slot: SlotGuard | None,
) -> TurnStream:
    turn_id = str(uuid.uuid4())
    client_turn_id = str(body.client_turn_id)
    request = TurnRequest(
        turn_id=turn_id,
        client_turn_id=client_turn_id,
        session=session,
        message=ingress,  # type: ignore[arg-type]
        locale=body.locale,
        precheck=precheck,
    )
    trace = TurnTrace(
        TurnRecord(
            turn_id=turn_id, session_id=session.session_id, client_turn_id=client_turn_id, release=c.release()
        )
    )
    return TurnStream(
        engine=c.engine,
        request=request,
        trace=trace,
        registry=c.registry,
        persist=c.persist_turn,
        slot=slot,
        keepalive_s=c.keepalive_s,
        cancel_grace_s=c.cancel_grace_s,
    )
