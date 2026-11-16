"""Forbidden-claim patterns: diagnosis, personal dosing, stopping treatment (app/guardrails/claims.py)."""

from __future__ import annotations

import pytest

from app.guardrails.claims import ClaimViolation, find_forbidden_claims


def _cats(sentence: str) -> set[str]:
    return {v.category for v in find_forbidden_claims(sentence)}


@pytest.mark.parametrize(
    "sentence",
    [
        "You probably have the flu.",
        "I think you have appendicitis.",
        "It sounds like you have a urinary tract infection [1].",
        "This looks like a viral infection.",
        "Your symptoms indicate a migraine.",
        "My diagnosis is bronchitis.",
        "Vous avez probablement une grippe.",
        "On dirait que vous avez une angine.",
        "Vos symptômes indiquent une migraine.",
        "أنت مصاب بالانفلونزا",
        "يبدو أنك مصاب بالتهاب",
        "أعراضك تدل على الربو",
        "- **You likely have** a sinus infection.",
    ],
)
def test_diagnosis_statements(sentence: str) -> None:
    assert "diagnosis" in _cats(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "You should take 2 tablets every 6 hours.",
        "Take 500 mg now.",
        "Give your child 5 ml of the syrup.",
        "Your dose is 20 mg a day.",
        "Double your dose tonight.",
        "Vous devez prendre 2 comprimés.",
        "Prenez 1 g de paracétamol.",
        "Votre posologie est de trois prises.",
        "Doublez la dose ce soir.",
        "خذ 2 حبوب",
        "جرعتك هي قرص واحد",
        "ضاعف الجرعة",
    ],
)
def test_personal_dosing(sentence: str) -> None:
    assert "personal_dosing" in _cats(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Stop taking your medication.",
        "You can safely stop the antibiotics now.",
        "Arrêtez votre traitement.",
        "Vous pouvez arrêter ce médicament.",
        "توقف عن تناول الدواء",
    ],
)
def test_stop_treatment(sentence: str) -> None:
    assert "stop_treatment" in _cats(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Do not stop taking your medicine without asking your doctor.",
        "Never double your dose to make up for a missed one.",
        "If you have chest pain, call your emergency number.",
        "You have the right to ask for an interpreter.",
        "You may have questions about your results.",
        "You have an increased risk if you smoke.",
        "Fever is a common symptom of the flu [1].",
        "The usual adult dose on the label is 500 mg [2].",
        "N'arrêtez pas votre traitement sans en parler à votre médecin.",
        "Si vous avez de la fièvre, consultez un médecin.",
        "لا تتوقف عن تناول الدواء دون استشارة الطبيب",
        "",
    ],
)
def test_safe_sentences(sentence: str) -> None:
    assert find_forbidden_claims(sentence) == ()


def test_one_violation_per_category() -> None:
    found = find_forbidden_claims(
        "You probably have the flu, you should take 2 tablets and stop taking your medicine."
    )
    assert found == (
        ClaimViolation("diagnosis"),
        ClaimViolation("personal_dosing"),
        ClaimViolation("stop_treatment"),
    )


@pytest.mark.parametrize(
    ("sentence", "category"),
    [
        # negation words embedded in other words must not guard the claim
        ("Another option: you should take 2 tablets tonight.", "personal_dosing"),
        ("Une bonne idée : prenez 2 comprimés le soir.", "personal_dosing"),
        ("Pour passer la nuit, vous devez prendre 2 comprimés.", "personal_dosing"),
        ("خلال اليوم خذ 2 حبوب", "personal_dosing"),
        ("Knowing this, you can stop taking your medication.", "stop_treatment"),
        ("Personne ici : arrêtez votre traitement.", "stop_treatment"),
    ],
)
def test_negation_cues_must_be_whole_words(sentence: str, category: str) -> None:
    assert category in _cats(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "You may have heard that vitamin C prevents colds.",
        "You might have noticed that fever often comes with chills.",
        "Don't double your dose if you forget one.",
        "Ne doublez pas la dose.",
    ],
)
def test_common_safe_phrasings(sentence: str) -> None:
    assert find_forbidden_claims(sentence) == ()


@pytest.mark.parametrize("sentence", ["لا تضاعف الجرعة", "يؤخذ 2 مرات في اليوم حسب النشرة"])
def test_arabic_claim_verbs_are_whole_words(sentence: str) -> None:
    assert find_forbidden_claims(sentence) == ()
