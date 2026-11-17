"""Deterministic intent and language heuristics (app/guardrails/intent_rules.py)."""

from __future__ import annotations

import pytest

from app.guardrails.intent_rules import heuristic_intent, heuristic_language, looks_like_arabizi
from core.schemas.chat import Intent


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("", Intent.OUT_OF_SCOPE),
        ("?!", Intent.OUT_OF_SCOPE),
        ("are you a robot?", Intent.META),
        ("t'es qui ?", Intent.META),
        ("شكون نتا", Intent.META),
        ("hello", Intent.SMALLTALK),
        ("bonjour", Intent.SMALLTALK),
        ("السلام عليكم", Intent.SMALLTALK),
        ("I want to book an appointment with cardiology", Intent.APPOINTMENT),
        ("je voudrais prendre rendez-vous", Intent.APPOINTMENT),
        ("بغيت نحجز موعد", Intent.APPOINTMENT),
        ("what are the side effects of ibuprofen", Intent.MEDICATION),
        ("posologie du doliprane", Intent.MEDICATION),
        ("واش هاد الدواء مزيان", Intent.MEDICATION),
        ("what are the visiting hours", Intent.HOSPITAL_ADMIN),
        ("où se trouve le service de radiologie", Intent.HOSPITAL_ADMIN),
        ("فين كاين قسم الأشعة", Intent.HOSPITAL_ADMIN),
        ("I have a headache since yesterday", Intent.SYMPTOM_INFO),
        ("j'ai mal au ventre", Intent.SYMPTOM_INFO),
        ("عندي الحمى", Intent.SYMPTOM_INFO),
        ("what causes diabetes", Intent.MEDICAL_INFO),
    ],
)
def test_heuristic_intent(text: str, intent: Intent) -> None:
    assert heuristic_intent(text) is intent


def test_hospital_keywords_route_to_admin() -> None:
    assert heuristic_intent("tell me about the cardiology unit") is Intent.MEDICAL_INFO
    assert heuristic_intent("tell me about the cardiology unit", ["cardiology"]) is Intent.HOSPITAL_ADMIN
    assert heuristic_intent("cardiology", ["", "neuro"]) is Intent.MEDICAL_INFO


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3andi wja3 f rassi bzaf", True),
        ("wach kayn tbib daba", True),
        ("bghit", True),
        ("I have a headache", False),
        ("", False),
    ],
)
def test_looks_like_arabizi(text: str, expected: bool) -> None:
    assert looks_like_arabizi(text) is expected


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("I have a headache", "en"),
        ("j'ai mal à la tête", "fr"),
        ("عندي صداع", "ar"),
        ("3andi wja3 f rassi", "ar"),
    ],
)
def test_heuristic_language(text: str, lang: str) -> None:
    assert heuristic_language(text) == lang


def test_heuristic_language_falls_back_without_letters() -> None:
    assert heuristic_language("123 456", fallback="fr") == "fr"
