"""Forbidden-claim patterns in EN/FR/AR: diagnosis statements, personal dosing, stopping or changing treatment.

Patterns run on a lowercased copy of one answer sentence. A match is ignored when a negation or a referral cue
precedes it in the same sentence ("do not stop taking your medicine without asking your doctor" is a safe
sentence). Matching sentences are removed from the answer (they are never rewritten).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EN_NEG = r"(?:not|n't|never|no one should|without|before (?:talking|speaking|asking))"
_FR_NEG = r"(?:ne|n'|pas|jamais|sans|avant d'en parler)"
_AR_NEG = r"(?:لا|لا ت|دون|بدون|قبل استشارة)"

_DIAGNOSIS = (
    r"^(?:i think |i believe |it is likely that |most likely )?you (?:probably |likely |most likely |definitely |"
    r"clearly |certainly |surely |may |might |could )?(?:have|'ve got|are suffering from|are having) "
    r"(?!to\b|the right\b|questions?\b|any\b|a right\b|more\b|less\b|several\b|options?\b|"
    r"an? (?:higher|lower|greater|increased|reduced) (?:risk|chance)\b)",
    r"\b(?:it|this|that) (?:sounds|looks|seems) like (?:you have|you've got|a case of|an? \w+ (?:infection|attack|"
    r"disease|disorder|syndrome))",
    r"\byour (?:symptoms|signs) (?:indicate|suggest|mean|point to|are consistent with)\b",
    r"\bmy (?:diagnosis|assessment) is\b",
    r"^vous (?:avez|souffrez) (?:probablement|sûrement|surement|certainement|sans doute|peut-être|peut etre)\b",
    r"\b(?:on dirait|cela ressemble à|ça ressemble à|il semble) que vous (?:avez|faites|souffrez)\b",
    r"\bvos symptômes (?:indiquent|suggèrent|correspondent à)\b",
    r"^(?:أنت|انت) (?:مصاب|مصابة|تعاني) (?:ب|من)",
    r"(?:يبدو|أعتقد|اعتقد) (?:أنك|انك) (?:مصاب|تعاني|لديك)",
    r"(?:أعراضك|اعراضك) (?:تدل|تشير)",
)
_DOSING = (
    r"\b(?:you should|you can|you could|you need to|you must|please) (?:take|give|use|increase|reduce|double)\b"
    r".{0,40}\b\d",
    r"^(?:take|give (?:him|her|them|your child|your baby)|use) \d+(?:[.,]\d+)?\s*(?:mg|ml|g|mcg|µg|tablets?|"
    r"pills?|capsules?|drops?|puffs?)\b",
    r"\b(?:your|the right|a safe) dose (?:for you )?(?:is|would be|should be)\b",
    r"\bdouble (?:your|the) (?:dose|dosage)\b",
    r"\b(?:vous devez|vous pouvez|il faut|prenez|donnez(?:-lui)?) (?:prendre )?\d+(?:[.,]\d+)?\s*(?:mg|ml|g|"
    r"comprimés?|gélules?|gouttes?)\b",
    r"\bvotre (?:dose|posologie) (?:est|devrait être|sera)\b",
    r"\bdoublez (?:la|votre) dose\b",
    r"(?:خذ|خذي|تناول|تناولي|أعطه|اعطه|أعطها|اعطها) \d+",
    r"(?:جرعتك|الجرعة المناسبة لك) (?:هي|هو)",
    r"(?:ضاعف|ضاعفي) الجرعة",
)
_STOP_TREATMENT = (
    r"\b(?:stop|quit|discontinue|skip|halve) (?:taking )?(?:your|the|this|that) (?:medication|medicine|treatment|"
    r"pills?|tablets?|drug|dose|prescription)",
    r"\byou (?:can|should|could) (?:safely )?(?:stop|quit|discontinue|skip)\b",
    r"\b(?:arrêtez|arretez|cessez|interrompez|sautez) (?:de prendre )?(?:votre|ce|le|la|vos|ces) "
    r"(?:traitement|médicament|medicament|comprimés?|dose)",
    r"\bvous pouvez (?:arrêter|arreter|cesser|interrompre)\b",
    r"(?:توقف|توقفي|أوقف|اوقف) (?:عن )?(?:تناول|أخذ|اخذ)? ?(?:الدواء|دوائك|العلاج|علاجك)",
)

_CATEGORIES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("diagnosis", tuple(re.compile(p, re.IGNORECASE) for p in _DIAGNOSIS)),
    ("personal_dosing", tuple(re.compile(p, re.IGNORECASE) for p in _DOSING)),
    ("stop_treatment", tuple(re.compile(p, re.IGNORECASE) for p in _STOP_TREATMENT)),
)
_NEGATION_BEFORE = re.compile(rf"(?:{_EN_NEG}|{_FR_NEG}|{_AR_NEG})\W*(?:\w+\W+){{0,3}}$", re.IGNORECASE)
_CONDITIONAL_BEFORE = re.compile(r"\b(?:if|when|whether|si|lorsque|quand|إذا|اذا|عندما)\W+(?:\w+\W+){0,2}$")


@dataclass(frozen=True)
class ClaimViolation:
    category: str  # "diagnosis" | "personal_dosing" | "stop_treatment"


def _guarded(sentence: str, start: int) -> bool:
    before = sentence[:start]
    return bool(_NEGATION_BEFORE.search(before) or _CONDITIONAL_BEFORE.search(before))


def find_forbidden_claims(sentence: str) -> tuple[ClaimViolation, ...]:
    """Return the forbidden-claim categories present in one sentence (empty when safe)."""
    text = re.sub(r"\s+", " ", sentence.strip().lstrip("-*• ").replace("**", ""))
    found: list[ClaimViolation] = []
    for category, patterns in _CATEGORIES:
        for pattern in patterns:
            m = pattern.search(text)
            if m and not _guarded(text, m.start()):
                found.append(ClaimViolation(category))
                break
    return tuple(found)
