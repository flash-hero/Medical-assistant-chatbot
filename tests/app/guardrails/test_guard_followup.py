"""A front-desk question sent right after an emergency message is not a new emergency (engine-api live run).

Seen live: "my dad collapsed and he is not breathing" then "What are the visiting hours?" 2 s later; the guard
model flagged the second message as an emergency because the earlier one was, so the visiting-hours question
went unanswered. Rules locked here:
  - deterministic detection (lexicon + injection heuristics) looks at the CURRENT message only;
  - history may inform the classifier, but every risk / population question asks about the latest message;
  - keeping the banner up for the rest of the session is the sticky flag's job (source "session_sticky"),
    never a new detection of the current message.
"""

from __future__ import annotations

import re

import pytest

from app.guardrails.guard_classifier import decision_questions, fallback_system
from app.guardrails.guard_prompts import GuardPrompts, load_guard_prompts
from app.guardrails.lexicon import LexiconMatcher
from app.guardrails.router import GuardRouter, RouterInput
from app.guardrails.safety_config import SafetyConfig
from core.models import ModelRole
from core.ports import DecisionAnswer, DecisionQuestion
from core.schemas.chat import Intent, Population, RiskKind
from evals.fakes.fake_llm import FakeLLMProvider, default_decider

# (risk message, front-desk follow-up, a follow-up that itself adds to the risk) per language
SESSIONS: dict[str, tuple[RiskKind, str, str, str]] = {
    "en": (
        RiskKind.EMERGENCY,
        "my dad collapsed and he is not breathing",
        "What are the visiting hours?",
        "he is still not breathing, what should I do now?",
    ),
    "fr": (
        RiskKind.EMERGENCY,
        "mon père s'est effondré et il ne respire plus",
        "Quels sont les horaires de visite ?",
        "il ne respire plus du tout",
    ),
    "ar": (RiskKind.EMERGENCY, "أبي سقط ولا يتنفس", "ما هي مواعيد الزيارة؟", "باقي لا يتنفس"),
    "arabizi": (
        RiskKind.EMERGENCY,
        "baba t7 w ma kaytnfsch",
        "wach kayn parking f sbitar?",
        "ba9i ma kaytnfsch",
    ),
    "self_harm_en": (
        RiskKind.SELF_HARM,
        "I want to end my life",
        "can I visit my mother in cardiology?",
        "I still want to end my life",
    ),
}
_PROMPTS = load_guard_prompts()
LATEST_MESSAGE_SCOPE = _PROMPTS.risk_scope
POPULATION_SCOPE = _PROMPTS.population_scope
_CURRENT_BLOCK = re.compile(r'<user_message role="current" nonce="[0-9a-f]+">\n(.*?)\n</user_message', re.S)


def _risk_messages(kind: RiskKind) -> tuple[str, ...]:
    return tuple(s[1].casefold() for s in SESSIONS.values() if s[0] is kind)


def context_reading_decider(payload: str, key: str, q: DecisionQuestion) -> DecisionAnswer:
    """Mimics the live failure: an unscoped risk question reads the whole conversation; a question scoped to
    the latest message reads only the role="current" block. Flags a risk when its message text is read."""
    if not key.startswith("risk_"):
        if key == "intent":
            return DecisionAnswer(
                kind="choice", confidence=0.9, choice="hospital_admin", probabilities={"hospital_admin": 0.9}
            )
        return default_decider(payload, key, q)
    scoped = LATEST_MESSAGE_SCOPE in q.instructions
    match = _CURRENT_BLOCK.search(payload)
    read = (match.group(1) if scoped and match else payload).casefold()
    flagged = any(message in read for message in _risk_messages(RiskKind(key[5:])))
    return DecisionAnswer(kind="noul", confidence=0.9, noul=0.97 if flagged else 0.01)


def _router(
    lexicon: LexiconMatcher, guard_prompts: GuardPrompts, safety_config: SafetyConfig
) -> tuple[GuardRouter, FakeLLMProvider]:
    llm = FakeLLMProvider(decider=context_reading_decider)
    return GuardRouter(llm, lexicon, guard_prompts, safety_config), llm


# ---- deterministic detection: the current message only ----------------------------------------------------
@pytest.mark.parametrize("session", sorted(SESSIONS))
def test_precheck_flags_the_risk_message_but_not_the_front_desk_follow_up(
    session: str, lexicon: LexiconMatcher, guard_prompts: GuardPrompts, safety_config: SafetyConfig
) -> None:
    kind, risk, follow_up, _ = SESSIONS[session]
    router, _ = _router(lexicon, guard_prompts, safety_config)
    assert router.precheck(risk).safety_kinds == frozenset({kind})
    assert router.precheck(follow_up).signals == ()


@pytest.mark.parametrize("session", sorted(SESSIONS))
def test_precheck_flags_a_follow_up_that_itself_describes_the_risk(
    session: str, lexicon: LexiconMatcher, guard_prompts: GuardPrompts, safety_config: SafetyConfig
) -> None:
    kind, _, _, still = SESSIONS[session]
    router, _ = _router(lexicon, guard_prompts, safety_config)
    assert router.precheck(still).safety_kinds == frozenset({kind})


# ---- classifier questions: about the latest message ------------------------------------------------------
def test_every_risk_question_asks_about_the_latest_message(guard_prompts: GuardPrompts) -> None:
    questions = decision_questions(guard_prompts)
    for kind in RiskKind:
        instructions = questions[f"risk_{kind.value}"].instructions
        assert instructions.startswith(guard_prompts.risks[kind])
        assert instructions.endswith(LATEST_MESSAGE_SCOPE)
    for pop in Population:
        assert questions[f"pop_{pop.value}"].instructions.endswith(POPULATION_SCOPE)


def test_scope_names_the_current_marker_and_keeps_follow_ups_about_the_risk() -> None:
    for scope in (LATEST_MESSAGE_SCOPE, POPULATION_SCOPE):
        assert 'role="current"' in scope
        assert "latest message" in scope
    assert "does not count unless" in LATEST_MESSAGE_SCOPE
    assert "asks about it" in LATEST_MESSAGE_SCOPE  # "what should I do now?" after an emergency still counts


def test_fallback_classifier_is_told_the_same_scope(guard_prompts: GuardPrompts) -> None:
    system = fallback_system(guard_prompts)
    assert f"Risks: {LATEST_MESSAGE_SCOPE}" in system
    assert f"Populations: {POPULATION_SCOPE}" in system


def test_unscoped_question_reproduces_the_live_false_positive(guard_prompts: GuardPrompts) -> None:
    """The fake decider really does mimic the failure: without the scope the follow-up is flagged."""
    _, risk, follow_up, _ = SESSIONS["en"]
    payload = f'<user_message role="earlier" n="1" nonce="ab">\n{risk}\n</user_message nonce="ab">\n'
    payload += f'<user_message role="current" nonce="ab">\n{follow_up}\n</user_message nonce="ab">'
    raw = DecisionQuestion(kind="noul", instructions=guard_prompts.risks[RiskKind.EMERGENCY])
    scoped = decision_questions(guard_prompts)["risk_emergency"]
    assert (context_reading_decider(payload, "risk_emergency", raw).noul or 0) > 0.5
    assert (context_reading_decider(payload, "risk_emergency", scoped).noul or 0) < 0.5


# ---- the whole route: no new detection, sticky flag keeps the banner -------------------------------------
@pytest.mark.parametrize("session", sorted(SESSIONS))
async def test_front_desk_follow_up_is_not_a_new_detection(
    session: str, lexicon: LexiconMatcher, guard_prompts: GuardPrompts, safety_config: SafetyConfig
) -> None:
    kind, risk, follow_up, _ = SESSIONS[session]
    router, llm = _router(lexicon, guard_prompts, safety_config)
    inp = RouterInput(text=follow_up, history=(risk,), sticky=frozenset({kind}))
    res = await router.route(inp, router.precheck(follow_up))
    assert llm.calls[0][:2] == ("decide", ModelRole.GUARD)
    assert res.classifier == "decide"
    assert res.current == ()  # nothing new: the pipeline answers the front-desk question
    assert [(s.kind, s.source) for s in res.verdict.risks] == [(kind, "session_sticky")]  # banner stays
    assert res.verdict.intent is Intent.HOSPITAL_ADMIN


@pytest.mark.parametrize("session", sorted(SESSIONS))
async def test_follow_up_that_adds_to_the_risk_is_still_detected(
    session: str, lexicon: LexiconMatcher, guard_prompts: GuardPrompts, safety_config: SafetyConfig
) -> None:
    kind, risk, _, still = SESSIONS[session]
    router, _ = _router(lexicon, guard_prompts, safety_config)
    inp = RouterInput(text=still, history=(risk,), sticky=frozenset({kind}))
    res = await router.route(inp, router.precheck(still))
    assert kind in res.current_kinds()
    assert all(s.source != "session_sticky" for s in res.verdict.risks if s.kind is kind)


async def test_risk_message_itself_is_still_flagged_by_the_classifier(
    lexicon: LexiconMatcher, guard_prompts: GuardPrompts, safety_config: SafetyConfig
) -> None:
    """The scope does not blind the classifier: a risk in the current message is still reported."""
    _, risk, _, _ = SESSIONS["en"]
    router, _ = _router(lexicon, guard_prompts, safety_config)
    no_lexicon = router.precheck("hello")  # leave the decision to the classifier alone
    res = await router.route(RouterInput(text=risk), no_lexicon)
    assert [(s.kind, s.source) for s in res.current] == [(RiskKind.EMERGENCY, "classifier")]
