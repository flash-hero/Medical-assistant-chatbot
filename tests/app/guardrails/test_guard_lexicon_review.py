"""Review findings C1 (historical cues must not hide a live emergency) and C12 (self-harm phrasings), on the
real lexicon. Inputs are the review repros plus fresh phrasings written for these tests (not from the
eval sets).
"""

from __future__ import annotations

import pytest

from app.guardrails.lexicon import LexiconMatcher
from core.schemas.chat import RiskKind


def _kinds(lex: LexiconMatcher, text: str) -> set[RiskKind]:
    return {s.kind for s in lex.signals(text)}


# ---- C1: a historical cue is scoped to its own sub-clause; present-time cues override it -------------------
LIVE_EMERGENCY_AFTER_HISTORY = [
    "He was diagnosed with epilepsy and is having a seizure right now",  # review repro
    "she was diagnosed with asthma and she is turning blue",  # review repro
    "My son who was diagnosed with epilepsy is having a seizure",
    "I was diagnosed with asthma last year and I can't breathe",
    "My dad had a stroke in 2015 and he is having a seizure",
    "Il a été diagnostiqué épileptique l'année dernière et il convulse",
    "Mon fils qui a des antécédents d'épilepsie convulse en ce moment",
    "تم تشخيصه بالصرع العام الماضي وهو الآن يتشنج",
    "ابني اللي شخصوه بالصرع راه كيتشنج",
]

STILL_HISTORICAL = [
    "I had a seizure last year and I'm fine now",
    "I had a seizure and was diagnosed with epilepsy last year",
    "She is recovering from a stroke she had last year",
    "I have a history of epilepsy and seizures, can I drive?",
    "J'ai fait une crise d'épilepsie l'année dernière et je vais bien",
]


@pytest.mark.parametrize("text", LIVE_EMERGENCY_AFTER_HISTORY)
def test_present_emergency_is_not_hidden_by_a_historical_cue(lexicon: LexiconMatcher, text: str) -> None:
    assert RiskKind.EMERGENCY in _kinds(lexicon, text)


@pytest.mark.parametrize("text", STILL_HISTORICAL)
def test_past_events_stay_historical(lexicon: LexiconMatcher, text: str) -> None:
    assert RiskKind.EMERGENCY not in _kinds(lexicon, text)


# ---- C12: self-harm phrasings, incl. the Darija negation circumfix -----------------------------------------
SELF_HARM = [
    "I don't see the point in living",  # review repro
    "no point in going on",  # review repro
    "ما بغيتش نعيش",  # review repro
    "honestly I do not see the point of living anymore",
    "there's no point in going on like this",
    "I can't see the point in being alive",
    "مابغيتش نعيش",
    "والله ما بغيتش نبقى نعيش",
    "je ne vois pas l'intérêt de vivre",
    "لا أرى فائدة من العيش",
]

NOT_SELF_HARM = [
    "I don't see the point in going to the gym",
    "There is no point in going on a diet before the holidays",
    "ما بغيتش نمشي للسبيطار",
]


@pytest.mark.parametrize("text", SELF_HARM)
def test_review_self_harm_phrasings(lexicon: LexiconMatcher, text: str) -> None:
    assert RiskKind.SELF_HARM in _kinds(lexicon, text)


@pytest.mark.parametrize("text", NOT_SELF_HARM)
def test_review_self_harm_near_misses(lexicon: LexiconMatcher, text: str) -> None:
    assert RiskKind.SELF_HARM not in _kinds(lexicon, text)
