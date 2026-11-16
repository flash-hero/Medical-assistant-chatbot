"""Heuristic prompt-injection / jailbreak detector (EN, FR, AR incl. Darija). Deterministic, no model call.

It is a backstop for the GUARD classifier, not the security boundary (the boundary is architectural: no tools,
no
secrets in prompts, no model-emitted URLs). Each pattern family has a weight; weights combine as independent
evidence (1 - prod(1 - w)) together with character-smuggling flags from ingress. Reasons are pattern ids only:
user text never appears in a Signal or a log line.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.guardrails.ingress import SMUGGLING_FLAG_WEIGHTS
from core.schemas.chat import RiskKind, Signal
from core.text import detection_form

_TARGET = (
    r"(?:instructions?|rules?|prompts?|directives?|guidelines?|programming|constraints?|guardrails?|"
    r"restrictions?|polic(?:y|ies)|safety (?:rules|settings|filters?))"
)
_FILLER = (
    r"(?:(?:all|any|every|of|your|the|my|these|those|previous|prior|above|earlier|preceding|original|initial|"
    r"system|safety|current|its)\s+){0,4}"
)

# Patterns on the detection form (lowercase, accents stripped, Arabic folded, punctuation removed).
_PHRASES: tuple[tuple[str, float, str], ...] = (
    ("override_en", 0.7, rf"\b(?:ignore|disregard|forget|override|bypass|skip|drop)\s+{_FILLER}{_TARGET}\b"),
    ("override_en", 0.6, r"\byou (?:are|re) no longer (?:bound|restricted|limited)\b"),
    (
        "override_en",
        0.6,
        r"\b(?:disable|turn off|deactivate|remove) (?:your |the |all )?(?:safety|filters?|guardrails?)",
    ),
    (
        "new_instructions",
        0.55,
        r"\b(?:new|updated|real|actual|true|secret) (?:instructions|system prompt|rules)\b",
    ),
    ("new_instructions", 0.55, r"\byour (?:new|real|true) (?:task|role|purpose|instructions?) (?:is|are)\b"),
    (
        "reveal_prompt",
        0.7,
        r"\b(?:reveal|show|print|display|repeat|output|tell me|give me|what is|what are|leak|share|dump|"
        r"write out|recite|list)\b(?:\s+\w+){0,4}\s+(?:system prompt|system message|initial prompt|hidden "
        r"(?:instructions?|prompt|rules)|your (?:instructions|rules|prompt|guidelines|configuration|system)|"
        r"developer (?:message|prompt)|reference code|confidential code|secret code)",
    ),
    ("reveal_prompt", 0.6, r"\b(?:system prompt|initial instructions|hidden instructions)\b"),
    (
        "repeat_above",
        0.6,
        r"\b(?:repeat|print|copy|output|translate|summari[sz]e|echo)\b(?:\s+\w+){0,3}\s+(?:text|words|everything|"
        r"all|content|message|instructions)\b(?:\s+\w+){0,2}\s+(?:above|before|so far|preceding|verbatim)",
    ),
    (
        "roleplay_unrestricted",
        0.7,
        r"\b(?:you are now|from now on you are|from now on|act as|pretend (?:to be|you are)|role ?play as|"
        r"simulate|imagine you are)\b(?:\s+\w+){0,8}\s+(?:unrestricted|uncensored|unfiltered|jailbroken|evil|"
        r"no (?:rules|restrictions|limits|filters)|without (?:rules|restrictions|limits|filters|ethics))",
    ),
    (
        "dan_mode",
        0.8,
        r"\b(?:do anything now|developer mode|dev mode|jailbreak|jail break|god mode|sudo mode)\b",
    ),
    ("dan_mode", 0.35, r"\b(?:dan|stan|aim)\b(?:\s+\w+){0,3}\s+(?:mode|prompt)\b"),
    # French
    (
        "override_fr",
        0.7,
        r"\b(?:ignore|ignorez|oublie|oubliez|contourne|outrepasse)\s+(?:\w+\s+){0,4}"
        r"(?:instructions?|regles?|consignes?|directives?|restrictions?)\b",
    ),
    (
        "reveal_prompt_fr",
        0.7,
        r"\b(?:montre|montrez|affiche|affichez|revele|revelez|repete|repetez|donne|donnez|ecris|ecrivez|dis)"
        r"(?:\s+moi)?(?:\s+\w+){0,3}\s+(?:prompt|message systeme|instructions? (?:cachees?|initiales?|"
        r"systeme)|"
        r"tes (?:instructions|consignes|regles)|vos (?:instructions|consignes|regles))",
    ),
    (
        "roleplay_fr",
        0.7,
        r"\b(?:tu es maintenant|a partir de maintenant|fais comme si tu etais|joue le role|fais semblant)\b"
        r"(?:\s+\w+){0,8}\s+(?:sans (?:regles|limites|restrictions|filtres|censure)|non censure|"
        r"mode developpeur)",
    ),
    ("dan_mode_fr", 0.8, r"\bmode (?:developpeur|dieu|sans limites?)\b"),
    (
        "repeat_above_fr",
        0.6,
        r"\brepete(?:z)?\b(?:\s+\w+){0,3}\s+(?:texte|message|tout)\b(?:\s+\w+){0,2}\s+"
        r"(?:ci dessus|precedent|au dessus)",
    ),
    # Arabic (MSA and Darija, folded: أ->ا, ة->ه)
    (
        "override_ar",
        0.7,
        r"(?:تجاهل|انس|انسى|اهمل|تخطى|نسى)\s+(?:\S+\s+){0,3}(?:التعليمات|القواعد|الاوامر|"
        r"التوجيهات|القيود)",
    ),
    (
        "reveal_prompt_ar",
        0.7,
        r"(?:اكشف|اظهر|اعرض|اعطني|اعطيني|ورني|وريني|اكتب لي|قول لي)\s+(?:\S+\s+){0,3}"
        r"(?:التعليمات|موجه النظام|رساله النظام|البرومبت|القواعد ديالك|تعليماتك|قواعدك)",
    ),
    ("roleplay_ar", 0.7, r"(?:انت الان|من الان)\s+(?:\S+\s+){0,5}(?:بدون|بلا|من غير)\s+(?:قيود|قواعد|حدود)"),
    ("dan_mode_ar", 0.8, r"وضع المطور"),
    (
        "override_arabizi",
        0.6,
        r"\b(?:nsa|tjahel|ignori)\s+(?:\w+\s+){0,3}(?:l9awa3id|lqawa3id|instructions)\b",
    ),
)

# Structural patterns on the sanitised, lowercased raw text (punctuation matters here).
_STRUCTURE: tuple[tuple[str, float, str], ...] = (
    ("fake_role_tag", 0.8, r"<\|?\s*(?:im_start|im_end|system|endoftext|assistant)\s*\|?>"),
    ("fake_role_tag", 0.8, r"<\s*/?\s*(?:untrusted_source|user_message|system|instructions?|passage)\b"),
    ("fake_role_tag", 0.6, r"\[/?(?:system|inst|assistant|developer)\]"),
    ("fake_role_tag", 0.6, r"(?m)^\s*#{1,6}\s*(?:system|instructions?|new instructions)\b"),
    ("fake_role_tag", 0.5, r"(?m)^\s*(?:system|developer|assistant)\s*:"),
    ("markdown_image", 0.7, r"!\[[^\]]{0,200}\]\([^)]{0,500}\)"),
    ("markdown_link", 0.45, r"\[[^\]]{0,200}\]\(\s*(?:https?:)?//"),
    (
        "exfil_request",
        0.7,
        r"(?:include|append|add|put|insert|encode)\b.{0,60}\b(?:in|into|to)\b.{0,20}"
        r"\b(?:url|link|image|query string|markdown)",
    ),
    ("html_injection", 0.5, r"<\s*(?:script|iframe|img|svg|object|embed|style)\b"),
)

_B64 = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_HEX = re.compile(r"(?:\b[0-9a-fA-F]{2}[\s:,-]?){24,}")
_COMPILED_PHRASES = tuple((rid, w, re.compile(p)) for rid, w, p in _PHRASES)
_COMPILED_STRUCT = tuple((rid, w, re.compile(p, re.IGNORECASE)) for rid, w, p in _STRUCTURE)


@dataclass(frozen=True)
class InjectionResult:
    score: float
    reasons: tuple[str, ...]

    def flagged(self, threshold: float) -> bool:
        return self.score >= threshold

    def signal(self) -> Signal:
        source = "sanitizer" if all(r.startswith("smuggling:") for r in self.reasons) else "lexicon"
        return Signal(
            kind=RiskKind.INJECTION,
            source=source,
            score=round(self.score, 3),
            detail=",".join(self.reasons)[:200],
        )


def _combine(weights: Iterable[float]) -> float:
    remaining = 1.0
    for w in weights:
        remaining *= 1.0 - max(0.0, min(1.0, w))
    return 1.0 - remaining


def _looks_like_base64_text(blob: str) -> bool:
    try:
        raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
    except (binascii.Error, ValueError):
        return False
    if len(raw) < 24:
        return False
    printable = sum(32 <= b < 127 for b in raw)
    return printable / len(raw) > 0.85


def _encoded_blobs(text: str) -> list[tuple[str, float]]:
    hits: list[tuple[str, float]] = []
    if any(_looks_like_base64_text(m.group(0)) for m in _B64.finditer(text)):
        hits.append(("base64_blob", 0.6))
    elif _B64.search(text):
        hits.append(("encoded_blob", 0.3))
    if _HEX.search(text):
        hits.append(("hex_blob", 0.5))
    return hits


def detect_injection(text: str, *, smuggling_flags: Iterable[str] = ()) -> InjectionResult:
    """Score a (sanitised, redacted) user message for injection attempts."""
    found: dict[str, float] = {}
    plain = detection_form(text)
    for rid, weight, pattern in _COMPILED_PHRASES:
        if pattern.search(plain):
            found[rid] = max(found.get(rid, 0.0), weight)
    lowered = text.lower()
    for rid, weight, pattern in _COMPILED_STRUCT:
        if pattern.search(lowered):
            found[rid] = max(found.get(rid, 0.0), weight)
    for rid, weight in _encoded_blobs(text):
        found[rid] = max(found.get(rid, 0.0), weight)
    weights: Mapping[str, float] = SMUGGLING_FLAG_WEIGHTS
    for flag in smuggling_flags:
        if flag in weights:
            found[f"smuggling:{flag}"] = weights[flag]
    reasons = tuple(sorted(found))
    return InjectionResult(score=_combine(found.values()), reasons=reasons)
