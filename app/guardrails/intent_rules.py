"""Deterministic intent and language heuristics, used when the GUARD classifier is unavailable or unsure.

They are deliberately conservative: anything that is not clearly front-desk, appointment, greeting or a
question
about the assistant is treated as a medical question (which then takes the verify-then-release path).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from core.schemas.chat import Intent, Locale
from core.text import detection_form, guess_language

_APPOINTMENT = re.compile(
    r"\b(?:appointment|appointments|book|booking|reschedule|cancel my|rendez vous|rdv|prendre rendez|"
    r"annuler mon|maw3id|mow3id|rendez vou)\b|موعد|مواعيد الطبيب|نحجز|احجز|حجز"
)
_ADMIN = re.compile(
    r"\b(?:opening hours|open|opens|close|closes|visiting|visit hours|visitors|parking|car park|where is|"
    r"how do i get|address|directions|phone number|contact|switchboard|department|ward|floor|building|wifi|"
    r"cafeteria|documents|insurance|pay|payment|bill|interpreter|lost property|wheelchair|horaires|heures|"
    r"ouvert|ouvre|ferme|visite|visites|stationnement|ou se trouve|adresse|acces|telephone|service de|"
    r"batiment|etage|mutuelle|carte vitale|paiement|interprete|fin kayn|fin jat|wa9t|sa3a)\b|"
    r"مواعيد العمل|وقت الزياره|اوقات الزياره|الزياره|موقف|فين كاين|فين جا|اين يوجد|العنوان|رقم الهاتف|"
    r"قسم|الطابق|المبنى|التامين|الدفع|مترجم|الاستقبال"
)
_GREETING = re.compile(
    r"^(?:hi|hello|hey|good morning|good evening|thanks|thank you|bonjour|bonsoir|salut|merci|coucou|"
    r"salam|slm|salam alikoum|salam alaykoum|ahlan|marhaba|choukran|shukran|baraka allahu fik|"
    r"مرحبا|السلام عليكم|السلام|اهلا|شكرا|بارك الله فيك|صباح الخير|مساء الخير)(?:\s+\w+)?$"
)
_META = re.compile(
    r"\b(?:are you (?:a |an )?(?:human|bot|robot|ai|real|doctor|person)|who are you|what are you|"
    r"what can you do|"
    r"t es qui|qui es tu|es tu un robot|tu es un robot|tu es humain|que peux tu faire|chkoun nta|chkon nta|"
    r"nta robot)\b|من انت|شكون نتا|شكون انت|واش نتا روبو|هل انت انسان|ماذا يمكنك"
)
# "Who made you?" is answered from the meta template (it names the creator), never by the model.
_CREATOR = re.compile(
    r"\b(?:who (?:created|made|built|developed|designed|programmed|coded|trained|owns) "
    r"(?:you|u|this|ausculta|the (?:chat)?bot|the assistant)|"
    r"who (?:is|s) (?:your|the) (?:creator|developer|maker|author|founder|owner)|"
    r"who (?:is|s) behind (?:you|this|ausculta)|your (?:creator|developer|maker)|"
    r"qui (?:t a|vous a) (?:cree|concu|developpe|fait|programme|construit)|"
    r"qui a (?:cree|concu|developpe|fait|programme|construit) (?:ausculta|ce (?:chat)?bot|cet assistant|toi)|"
    r"(?:ton|votre) (?:createur|developpeur|concepteur)|"
    r"(?:chkoun|chkon|chkun|chkoune) (?:li )?(?:sawbek|sawbak|sawbk|darek|dark|brmjek))\b|"
    r"من (?:صنعك|طورك|انشاك|برمجك|صممك|ابتكرك|اخترعك|دربك)|"
    r"(?:صانعك|مطورك|مبتكرك|مصممك)|"
    r"شكون (?:لي )?(?:صاوبك|صوبك|دارك|برمجك)"
)
_MEDICATION = re.compile(
    r"\b(?:mg|ml|dose|dosage|pill|pills|tablet|tablets|capsule|medicine|medication|drug|side effects?|"
    r"interaction|paracetamol|acetaminophen|ibuprofen|aspirin|amoxicillin|metformin|insulin|antibiotic|"
    r"medicament|comprime|comprimes|posologie|effets secondaires|antibiotique|doliprane|dwa|ldwa|l7bob|"
    r"7bob)\b|دواء|الدواء|دوا|حبوب|جرعه|مضاد حيوي|باراسيتامول|اثار جانبيه"
)
_SYMPTOM = re.compile(
    r"\b(?:i have|i ve had|i feel|i m feeling|my \w+ hurts|pain in my|j ai mal|j ai de la|je ressens|"
    r"3andi|kayderni|kaywje3ni)\b|عندي|كيضرني|كيوجعني|اشعر ب|احس ب"
)
_ARABIZI_WORDS = frozenset(
    [
        "bghit",
        "wach",
        "dyal",
        "dial",
        "3andi",
        "3ndi",
        "kifach",
        "chno",
        "chnou",
        "rani",
        "bzaf",
        "mzyan",
        "daba",
        "kayderni",
        "wa9t",
        "sa3a",
        "fin",
        "kayn",
        "nmout",
        "lyoum",
        "ghadi",
        "khasni",
        "bach",
        "mn",
        "m3a",
        "3la",
        "lwa9t",
        "ndir",
    ]
)
_ARABIZI_TOKEN = re.compile(r"^(?=.*[a-z])(?=.*[2379])[a-z2379']{3,}$")


def heuristic_intent(text: str, hospital_keywords: Iterable[str] = ()) -> Intent:
    t = detection_form(text)
    if not t:
        return Intent.OUT_OF_SCOPE
    if _CREATOR.search(t) or _META.search(t):
        return Intent.META
    if _GREETING.match(t):
        return Intent.SMALLTALK
    if _APPOINTMENT.search(t):
        return Intent.APPOINTMENT
    if _MEDICATION.search(t):
        return Intent.MEDICATION
    if _ADMIN.search(t) or _mentions_any(t, hospital_keywords):
        return Intent.HOSPITAL_ADMIN
    if _SYMPTOM.search(t):
        return Intent.SYMPTOM_INFO
    return Intent.MEDICAL_INFO


def is_creator_question(text: str) -> bool:
    """Deterministic: the user asks who created, built or owns the assistant (EN/FR/AR/Darija)."""
    return bool(_CREATOR.search(detection_form(text)))


def _mentions_any(t: str, keywords: Iterable[str]) -> bool:
    padded = f" {t} "
    return any(f" {k} " in padded for k in keywords if k)


def looks_like_arabizi(text: str) -> bool:
    toks = detection_form(text).split()
    if not toks:
        return False
    hits = sum(1 for tok in toks if tok in _ARABIZI_WORDS or _ARABIZI_TOKEN.match(tok))
    return hits >= 2 or (hits == 1 and len(toks) <= 3)


def heuristic_language(text: str, fallback: Locale = "en") -> Locale:
    guessed = guess_language(text)
    if guessed == "ar" or looks_like_arabizi(text):
        return "ar"
    if guessed == "fr":
        return "fr"
    return "en" if re.search(r"[a-zA-Z]", text) else fallback
