"""Turn orchestrator: emits core.schemas.events in the order the SSE contract requires.

  meta -> [safety ...] -> [notice(demo)] -> status(checking) -> [safety ...] -> route -> answer path -> done

Safety events come from the deterministic precheck BEFORE any model call, so the emergency and self-harm
templates need no model at all (they return in milliseconds even when every model call fails). Emergency
and self-harm turns carry NO further medical content. Injection / harmful / abusive turns get a refusal
and a strike; 3 strikes lock the session. Session state (sticky risks, strikes, history) is saved before
any long-running step so a cancelled turn never loses a safety decision."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime

import structlog

from app.guardrails.ingress import IngressResult
from app.guardrails.intent_rules import heuristic_intent
from app.guardrails.router import GuardRouter, Precheck, RouteResult, RouterInput
from app.guardrails.safety_config import SAFETY_KINDS, STRIKE_KINDS
from app.hospital.frontdesk import answer_front_desk, hospital_keywords
from app.hospital.profile import ProfileState
from app.pipeline.forms import appointment_form
from app.pipeline.medical import MedicalResponder, MedicalTurn
from app.pipeline.record import TurnTrace
from app.pipeline.session import SessionState, SessionStore
from app.pipeline.texts import Texts, contacts_for, render
from core.config import Settings
from core.errors import AusculaError
from core.schemas.chat import GuardVerdict, Intent, Locale, RiskKind
from core.schemas.events import (
    AnswerEvent,
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    MetaEvent,
    NoticeEvent,
    ReleaseInfo,
    SafetyEvent,
    StatusEvent,
)
from core.schemas.hospital import HospitalProfile

log = structlog.get_logger(__name__)
SAFETY_ORDER: tuple[RiskKind, ...] = (
    RiskKind.EMERGENCY,
    RiskKind.SELF_HARM,
    RiskKind.HARM_TO_OTHERS,
    RiskKind.ABUSE_DISCLOSURE,
)
STRIKE_TEMPLATES: tuple[tuple[RiskKind, str], ...] = (
    (RiskKind.HARMFUL_REQUEST, "refusal_harmful"),
    (RiskKind.INJECTION, "refusal_injection"),
    (RiskKind.ABUSIVE_USER, "refusal_abusive"),
)
MEDICAL_INTENTS = frozenset({Intent.MEDICAL_INFO, Intent.MEDICATION, Intent.SYMPTOM_INFO})
TEMPLATE_INTENTS = {Intent.SMALLTALK: "smalltalk", Intent.META: "meta", Intent.OUT_OF_SCOPE: "out_of_scope"}
SESSION_LIMIT_NOTICE_AT = 3


@dataclass(frozen=True)
class TurnRequest:
    turn_id: str
    client_turn_id: str
    session: SessionState
    message: IngressResult
    locale: Locale
    precheck: Precheck


@dataclass(frozen=True)
class _Ctx:
    req: TurnRequest
    profile: HospitalProfile | None
    trace: TurnTrace


class TurnEngine:
    def __init__(
        self,
        *,
        router: GuardRouter,
        medical: MedicalResponder,
        texts: Texts,
        profile_state: ProfileState,
        sessions: SessionStore,
        settings: Settings,
        release: ReleaseInfo,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self._router = router
        self._medical = medical
        self._texts = texts
        self._profiles = profile_state
        self._sessions = sessions
        self._settings = settings
        self._release = release
        self._today = today

    @property
    def release(self) -> ReleaseInfo:
        return self._release

    @property
    def texts(self) -> Texts:
        return self._texts

    def precheck(self, message: IngressResult) -> Precheck:
        return self._router.precheck(message.text, message.sanitize_flags)

    async def run(self, req: TurnRequest, trace: TurnTrace) -> AsyncGenerator[ChatEvent, None]:
        ctx = _Ctx(req=req, profile=self._profiles.active(self._today()), trace=trace)
        yield MetaEvent(
            turn_id=req.turn_id,
            session_id=req.session.session_id,
            locale=req.locale,
            demo_mode=self._settings.demo_mode,
            release=trace.record.release,
        )
        trace.mark("meta")
        try:
            async for ev in self._body(ctx):
                yield ev
        except Exception as exc:
            code = exc.code if isinstance(exc, AusculaError) else "internal_error"
            log.error("turn_failed", turn_id=req.turn_id, error=type(exc).__name__, code=code)
            trace.update(error_code=code)
            retry = exc.detail.get("retry_after_s") if isinstance(exc, AusculaError) else None
            yield ErrorEvent(
                code=code,
                message=self._texts.error(code, req.locale),
                retry_after_s=float(retry) if isinstance(retry, (int, float)) else None,
            )
        yield DoneEvent(turn_id=req.turn_id, turns_left=await self._turns_left(req))

    async def _turns_left(self, req: TurnRequest) -> int:
        try:
            session = await self._sessions.get(req.session.session_id) or req.session
        except Exception as exc:
            log.warning("session_reload_failed", error=type(exc).__name__)
            session = req.session.with_turn("", window=0)
        return max(0, self._settings.max_turns_per_session - session.turns_used)

    # ---- body ------------------------------------------------------------------------------------
    async def _body(self, ctx: _Ctx) -> AsyncIterator[ChatEvent]:
        req, trace = ctx.req, ctx.trace
        lang = req.locale
        pre_kinds = req.precheck.safety_kinds
        for ev in self._safety_events(pre_kinds, ctx, lang):  # life-critical text first, right after meta
            yield ev
        if self._settings.demo_mode and req.session.turns_used == 0:
            yield NoticeEvent(code="demo_mode", message=self._texts.notice("demo_mode", lang, ctx.profile))
        session = req.session.with_turn(req.message.text, window=self._settings.history_window_turns)
        session = session.with_risks(pre_kinds)
        trace.update(
            risk_kinds=_names(s.kind for s in req.precheck.signals), redactions=req.message.redaction_total
        )
        if pre_kinds & self._router.config.block_medical_after or session.locked:
            await self._sessions.put(session)
            yield self._closing_answer(ctx, session, pre_kinds, heuristic_intent(req.message.text), lang)
            return
        yield StatusEvent(stage="checking")
        route = await self._route(ctx, session)
        async for event in self._after_route(ctx, session, route, pre_kinds):
            yield event

    async def _route(self, ctx: _Ctx, session: SessionState) -> RouteResult:
        req = ctx.req
        inp = RouterInput(
            text=req.message.text,
            history=req.session.user_history(),
            locale_hint=req.locale,
            sticky=req.session.sticky_risks,
            hospital_keywords=hospital_keywords(ctx.profile),
        )
        route = await self._router.route(inp, req.precheck)
        ctx.trace.mark("route")
        v = route.verdict
        ctx.trace.update(
            intent=v.intent.value,
            language=v.language,
            classifier=route.classifier,
            risk_kinds=_names(s.kind for s in route.current),
        )
        if not v.classifier_available:
            ctx.trace.degrade("classifier_unavailable")
        return route

    async def _after_route(
        self, ctx: _Ctx, session: SessionState, route: RouteResult, pre_kinds: frozenset[RiskKind]
    ) -> AsyncIterator[ChatEvent]:
        v = route.verdict
        lang = v.language
        current = route.current_kinds()
        new_safety = (current & SAFETY_KINDS) - pre_kinds
        for ev in self._safety_events(new_safety, ctx, lang):
            yield ev
        session = session.with_risks(current & SAFETY_KINDS)
        if current & SAFETY_KINDS & self._router.config.block_medical_after:
            await self._sessions.put(session)
            yield self._closing_answer(ctx, session, current & SAFETY_KINDS, v.intent, lang)
            return
        if route.blocked:
            await self._sessions.put(session)
            ctx.trace.audit("upstream_blocked", stage="guard")
            yield self._fixed("refusal_blocked", v.intent, lang, ctx, mode="refusal")
            return
        if current & STRIKE_KINDS:
            yield await self._strike(ctx, session, current, v.intent, lang)
            return
        await self._sessions.put(session)
        async for event in self._dispatch(ctx, session, v):
            yield event
        left = self._settings.max_turns_per_session - session.turns_used
        if 0 < left <= SESSION_LIMIT_NOTICE_AT:
            yield NoticeEvent(
                code="session_limit_near",
                message=self._texts.notice("session_limit_near", lang, ctx.profile, turns_left=left),
            )

    async def _strike(
        self, ctx: _Ctx, session: SessionState, current: frozenset[RiskKind], intent: Intent, lang: Locale
    ) -> AnswerEvent:
        session = session.with_strike(self._router.config.strikes_to_lock)
        await self._sessions.put(session)
        ctx.trace.audit("strike", count=session.strikes, kinds=",".join(sorted(k.value for k in current)))
        if session.locked:
            ctx.trace.audit("session_locked")
            return self._fixed("session_locked", intent, lang, ctx, mode="refusal")
        key = next(t for k, t in STRIKE_TEMPLATES if k in current)
        return self._fixed(key, intent, lang, ctx, mode="refusal")

    async def _dispatch(self, ctx: _Ctx, session: SessionState, v: GuardVerdict) -> AsyncIterator[ChatEvent]:
        lang = v.language
        if v.intent in MEDICAL_INTENTS:
            turn = MedicalTurn(
                message=ctx.req.message.text,
                history=ctx.req.session.user_history(),
                verdict=v,
                high_risk=v.high_risk_medical
                or not v.classifier_available
                or bool(ctx.req.session.sticky_risks),
                profile=ctx.profile,
            )
            async for ev in self._medical.respond(turn, ctx.trace):
                yield ev
            return
        if v.intent is Intent.HOSPITAL_ADMIN:
            yield self._front_desk(ctx, v.intent, lang)
            return
        if v.intent is Intent.APPOINTMENT:
            for ev in self._appointment(ctx, lang):
                yield ev
            return
        yield self._fixed(TEMPLATE_INTENTS[v.intent], v.intent, lang, ctx, mode="template")

    # ---- fixed answers ---------------------------------------------------------------------------
    def _safety_events(self, kinds: Iterable[RiskKind], ctx: _Ctx, lang: Locale) -> list[SafetyEvent]:
        events: list[SafetyEvent] = []
        wanted = set(kinds)
        for kind in SAFETY_ORDER:
            if kind not in wanted:
                continue
            t = self._texts.safety[kind.value]
            values = self._texts.values(ctx.profile, lang)
            events.append(
                SafetyEvent(
                    kind=kind.value,  # type: ignore[arg-type]
                    template_id=t.template_id,
                    title=render(t.title, lang, values),
                    message=render(t.message, lang, values),
                    contacts=contacts_for(t.contacts, ctx.profile, lang),
                )
            )
            ctx.trace.audit("safety_template", kind=kind.value, template_id=t.template_id)
        if events:
            ctx.trace.mark("safety")
        return events

    def _closing_answer(
        self, ctx: _Ctx, session: SessionState, kinds: frozenset[RiskKind], intent: Intent, lang: Locale
    ) -> AnswerEvent:
        first = next((k for k in SAFETY_ORDER if k in kinds), None)
        if first is None:  # locked session without a safety signal
            ctx.trace.audit("session_locked")
            return self._fixed("session_locked", intent, lang, ctx, mode="refusal")
        t = self._texts.safety[first.value]
        ctx.trace.update(mode="template", intent=ctx.trace.record.intent or intent.value)
        return AnswerEvent(
            text=render(t.followup, lang, self._texts.values(ctx.profile, lang)),
            intent=intent,
            mode="template",
            verified=False,
        )

    def _fixed(self, key: str, intent: Intent, lang: Locale, ctx: _Ctx, *, mode: str) -> AnswerEvent:
        ctx.trace.update(mode=mode, intent=ctx.trace.record.intent or intent.value)
        if mode == "refusal":
            ctx.trace.audit("refusal", template=key)
        return AnswerEvent(
            text=self._texts.response(key, lang, ctx.profile),
            intent=intent,
            mode=mode,  # type: ignore[arg-type]
            verified=False,
        )

    def _front_desk(self, ctx: _Ctx, intent: Intent, lang: Locale) -> AnswerEvent:
        if ctx.profile is None:
            return self._fixed("frontdesk_unavailable", intent, lang, ctx, mode="template")
        found = answer_front_desk(ctx.req.message.text, ctx.profile, self._texts, lang)
        if found is None:
            return self._fixed("frontdesk_no_match", intent, lang, ctx, mode="template")
        ctx.trace.update(mode="template")
        ctx.trace.audit("front_desk", matched=",".join(found.matched)[:200])
        return AnswerEvent(text=found.text, intent=intent, mode="template", verified=False)

    def _appointment(self, ctx: _Ctx, lang: Locale) -> list[ChatEvent]:
        form = appointment_form(ctx.profile, self._texts, lang)
        if form is None:
            return [self._fixed("appointment_unavailable", Intent.APPOINTMENT, lang, ctx, mode="template")]
        intro = self._fixed("appointment_intro", Intent.APPOINTMENT, lang, ctx, mode="template")
        return [intro, form]


def _names(kinds: Iterable[RiskKind]) -> tuple[str, ...]:
    return tuple(sorted({k.value for k in kinds}))
