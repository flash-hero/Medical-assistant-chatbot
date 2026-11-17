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


# ---- review C2: claims anywhere, FR/AR/number-word dosing, stop-treatment without a determiner
@pytest.mark.parametrize(
    ("sentence", "category"),
    [
        ("Based on what you describe, you probably have pneumonia.", "diagnosis"),
        ("From your symptoms, you have a urinary tract infection.", "diagnosis"),
        ("Dans ce cas, vous avez probablement une pneumonie.", "diagnosis"),
        ("D'après vos symptômes, vous souffrez sans doute d'une angine.", "diagnosis"),
        ("بناء على ما تصف، أنت مصاب بالتهاب رئوي.", "diagnosis"),
        ("بناءً على ما تصفه، أنت مصابٌ بالتهاب رئوي.", "diagnosis"),
        ("In your case, take 500 mg now.", "personal_dosing"),
        ("In your case, take five hundred milligrams now.", "personal_dosing"),
        ("You should take two tablets every four hours.", "personal_dosing"),
        ("Vous devriez prendre 1 g de paracétamol.", "personal_dosing"),
        ("Vous devriez prendre deux comprimés.", "personal_dosing"),
        ("Pour la fièvre, prenez deux comprimés.", "personal_dosing"),
        ("يجب أن تأخذ 500 ملغ.", "personal_dosing"),
        ("يجب عليك أن تتناول قرصين.", "personal_dosing"),
        ("Stop taking aspirin.", "stop_treatment"),
        ("You can stop taking ibuprofen now.", "stop_treatment"),
        ("Then stop using the inhaler.", "stop_treatment"),
        ("Arrêtez de prendre l'aspirine.", "stop_treatment"),
        ("Arrêtez l'aspirine.", "stop_treatment"),
        ("توقف عن تناول الأسبرين.", "stop_treatment"),
    ],
)
def test_review_c2_claims_are_caught_anywhere(sentence: str, category: str) -> None:
    assert category in _cats(sentence)


# ---- review C5: triage verdicts and probable-diagnosis forms ----------------------------------------------
@pytest.mark.parametrize(
    "sentence",
    [
        "You do not need to see a doctor.",
        "You don't need to go to the hospital for this.",
        "There is no need to see a doctor.",
        "Go to the ER now.",
        "Go to the emergency room immediately.",
        "You need to see a doctor urgently.",
        "You should go to the hospital right away.",
        "This is not serious.",
        "It's nothing serious.",
        "Your condition is urgent.",
        "Your symptoms are not serious.",
        "Nothing to worry about.",
        "You can wait until tomorrow.",
        "Votre état est urgent.",
        "Ce n'est pas grave.",
        "Vous n'avez pas besoin de consulter un médecin.",
        "Allez aux urgences immédiatement.",
        "Votre situation est grave.",
        "حالتك خطيرة.",
        "حالتك ليست خطيرة.",
        "لا داعي لزيارة الطبيب.",
        "لا تحتاج إلى رؤية الطبيب.",
        "اذهب إلى الطوارئ فورا.",
    ],
)
def test_review_c5_triage_verdicts(sentence: str) -> None:
    assert "triage" in _cats(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "This is probably appendicitis.",
        "It could be a heart attack.",
        "It might be a urinary tract infection.",
        "This sounds like appendicitis.",
        "These symptoms are most likely a migraine.",
        "C'est probablement une appendicite.",
        "Il s'agit probablement d'une grippe.",
        "Cela pourrait être une crise cardiaque.",
        "هذا على الأرجح التهاب الزائدة.",
        "قد تكون هذه نوبة قلبية.",
        "من المحتمل أنك مصاب بالانفلونزا.",
    ],
)
def test_review_c5_probable_diagnosis(sentence: str) -> None:
    assert "diagnosis" in _cats(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        # general "when to seek care" guidance: conditional, anywhere in the sentence
        "Go to the emergency room immediately if your lips turn blue [1].",
        "Call your emergency number now if you have chest pain that spreads to your arm.",
        "Seek emergency care right away in case of severe bleeding [2].",
        "If you think it is an emergency, call 15.",
        "Rendez-vous aux urgences immédiatement si vous avez du mal à respirer.",
        "اذهب إلى الطوارئ فورا إذا كان لديك ألم في الصدر.",
        # general information and safe sentences
        "Most nosebleeds are not serious [1].",
        "Meningitis is a serious infection [1].",
        "Sepsis is a medical emergency. This is a medical emergency [1].",
        "L'AVC est une urgence médicale [1].",
        "Chest pain can be a sign of a heart attack [1].",
        "It may be a good idea to rest.",
        "It is important to drink fluids.",
        "Tell your doctor about the medicines you have at home.",
        "You should see a doctor if the fever lasts more than 3 days [1].",
        "Patients who stop taking aspirin suddenly may have a higher risk [1].",
        "Arrêtez de fumer.",
        "Adults usually take 500 mg every 4 to 6 hours [1].",
        "You can use one of these methods.",
        "Unless you have a fever, rest at home.",
        "",
    ],
)
def test_review_c2_c5_safe_sentences_stay(sentence: str) -> None:
    assert find_forbidden_claims(sentence) == ()


@pytest.mark.parametrize(
    "sentence",
    [
        "You can take paracetamol with or without food [1].",  # the citation marker is not a dose number
        "Then you have the option of a flu vaccine.",
        "So you have to drink plenty of fluids.",
    ],
)
def test_citation_markers_and_generic_lead_ins_are_not_claims(sentence: str) -> None:
    assert find_forbidden_claims(sentence) == ()
