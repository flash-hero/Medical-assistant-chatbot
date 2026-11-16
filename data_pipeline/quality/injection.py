"""Indirect-prompt-injection scan for corpus text (EN / FR / AR) plus hidden-markup and smuggling checks.

Matching runs on core.text.detection_form(): casefolded, accents stripped, Arabic letters folded
(alef variants -> ا, ى -> ي, ة -> ه), diacritics and tatweel removed. Patterns below are therefore written in
that folded form. A hit never deletes text: the document is moved to quarantine/ with the reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.schemas.document import Document
from core.text import SanitizeResult, detection_form, sanitize

_EN = {
    "en_ignore_previous": r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|above|earlier|preceding|all|any|your|these|those|the)\b.{0,25}\b(instructions?|prompts?|rules?|directives?|guidelines?|messages?|context)\b",
    "en_forget_everything": r"\bforget (everything|all of (this|that)|what you (were|have been) told)\b",
    "en_system_prompt": r"\b(system|developer|hidden|initial|original) (prompt|message|instructions?)\b",
    "en_reveal_prompt": r"\b(reveal|show|print|repeat|output|leak|display)\b.{0,25}\b(your|the) (system|hidden|initial|original|secret)\b",
    "en_you_are_now": r"\byou are now (a|an|the|in|my|dan|free|unrestricted|acting|operating|going|no longer)\b",
    "en_new_instructions": r"\b(new|updated|additional) (instructions?|rules?|directives?)\s*:",
    "en_pretend": r"\b(pretend|imagine) (to be|you are|that you are|you're)\b",
    "en_roleplay_mode": r"\b(developer|debug|jailbreak|god|dan|admin(istrator)?) mode\b",
    "en_do_not_tell_user": r"\b(do not|don't|never) (tell|inform|reveal to|mention to|let) (the )?(user|human|patient)\b|\bwithout (telling|informing|alerting) the (user|human)\b",
    "en_exfiltrate": r"\b(send|post|forward|upload|exfiltrate|transmit)\b.{0,40}\b(to|at) (https?:|www\.)",
    "en_respond_only": r"\b(respond|reply|answer) (only )?with\b.{0,40}\b(regardless|no matter|ignoring)\b",
    "en_ai_address": r"\b(dear|attention|note to|message for|instructions? for) (the )?(ai|assistant|language model|llm|chatbot|model)\b",
    "en_as_an_ai_directive": r"\b(when|if) (you are|you're) (an? )?(ai|assistant|language model|llm)\b.{0,60}\b(you must|you should|always|never)\b",
}
_FR = {
    "fr_ignore_previous": r"\b(ignore|ignorez|ignorer|oublie|oubliez|oublier|neglige|negligez)\b.{0,30}\b(tout|toute|toutes|tous|les|vos|tes|ces|ses|mes)?\s*(instructions?|consignes?|regles?|directives?)\b",
    "fr_forget_everything": r"\b(oublie|oubliez|oublier)\b.{0,15}\b(tout|toutes? les|ce que)\b",
    "fr_system_prompt": r"\b(prompt|invite|message|instructions?) (systeme|developpeur|cache|initial)\b|\bsystem prompt\b",
    "fr_reveal_prompt": r"\b(revele|reveler|affiche|afficher|montre|montrer|repete|repeter)\b.{0,25}\b(ton|votre|le|ta|vos) (prompt|message|instructions?|invite)\b",
    "fr_you_are_now": r"\b(tu es|vous etes) (maintenant|desormais|a present)\b",
    "fr_new_instructions": r"\bnouvelles? (instructions?|consignes?|regles?)\s*:",
    "fr_pretend": r"\b(fais|faites|fait) comme si\b|\bfais semblant\b|\bfaites semblant\b",
    "fr_roleplay_mode": r"\bmode (developpeur|debogage|jailbreak|administrateur|dieu)\b",
    "fr_do_not_tell_user": r"\bne (dis|dites|reveles|revelez) (pas|jamais) (a l'utilisateur|a l utilisateur)\b|\bsans (le )?(dire|prevenir|informer) (a )?l'? ?utilisateur\b",
    "fr_ai_address": r"\b(cher|attention|message pour|instructions? pour) (l'? ?)?(ia|assistant|modele de langage|chatbot)\b",
}
_AR = {
    "ar_ignore_previous": r"(تجاهل|تجاهلي|تجاهلوا|اهمل|اهملي|انس|انسي|تخط|تخطي)\s+(كل|جميع|اي|ال)?\s*(ال)?(تعليمات|اوامر|قواعد|توجيهات|ارشادات)\s*(ال)?(سابقه|السابقه|اعلاه|السابقة|الماضيه)?",
    "ar_forget_everything": r"(انس|انسي|انسوا)\s+(كل|جميع)\s+(شيء|شي|ما)",
    "ar_system_prompt": r"(موجه|رساله|تعليمات|اوامر)\s+(ال)?نظام|system prompt|(ال)?موجه الاصلي",
    "ar_reveal_prompt": r"(اكشف|اظهر|اعرض|كرر|اطبع)\s+.{0,20}(موجه|تعليمات|رساله)\s+(ال)?(نظام|اصلي|مخفي)",
    "ar_you_are_now": r"\bانت الان\b|\bانتي الان\b|\bانت لم تعد\b",
    "ar_new_instructions": r"(تعليمات|اوامر|قواعد)\s+جديده\s*:",
    "ar_pretend": r"(تظاهر|تخيل|اوهم)\s+(بانك|انك|بان)",
    "ar_roleplay_mode": r"(وضع|نمط)\s+(ال)?(مطور|المطور|مسؤول|اله|الاله|جيلبريك)",
    "ar_do_not_tell_user": r"(لا|ولا)\s+(تخبر|تقل|تكشف)\s+(ال)?مستخدم",
    "ar_ai_address": r"(الى|الي|رساله ل|تعليمات ل)\s*(ال)?(ذكاء الاصطناعي|مساعد|نموذج اللغه|روبوت)",
}
_TEXT_PATTERNS = {name: re.compile(pattern, re.IGNORECASE | re.DOTALL) for group in (_EN, _FR, _AR) for name, pattern in group.items()}

# Structural patterns run on the *sanitised but otherwise raw* text (punctuation matters here).
_RAW_PATTERNS = {
    "role_tag_line": re.compile(r"(?im)^\s*(assistant|system|user|human|developer|assistante?|utilisateur|systeme|système|مساعد|نظام|مستخدم)\s*:\s*\S"),
    "chat_template_token": re.compile(r"<\|(im_start|im_end|system|user|assistant|endoftext)\|>|\[/?INST\]|<<\s*/?SYS\s*>>|<\s*/?(start|end)_of_turn\s*>", re.I),
    "markdown_heading_role": re.compile(r"(?im)^#{2,4}\s*(system|instruction|assistant|user)\b"),
    "hidden_html_tag": re.compile(r"<\s*(script|iframe|object|embed|style|meta|link|base|form|svg)\b", re.I),
    "html_comment": re.compile(r"<!--"),
    "hidden_css": re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|color\s*:\s*(white|#fff))", re.I),
    "script_uri": re.compile(r"\b(javascript|vbscript)\s*:|data:\s*text/html|data:[a-z/+.-]+;base64", re.I),
    "markdown_image_url": re.compile(r"!\[[^\]]*\]\(\s*https?://", re.I),
    "base64_blob": re.compile(r"\b[A-Za-z0-9+/]{200,}={0,2}\b"),
}
_SUSPICIOUS_SANITIZE_FLAGS = ("tag_chars", "bidi_override", "vs_supplement", "private_use")


@dataclass(frozen=True)
class InjectionHit:
    pattern_id: str
    snippet: str  # <= 80 characters around the match, for the quarantine record


def _snippet(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 20)
    return " ".join(text[start : match.end() + 20].split())[:80]


def scan_text(text: str) -> list[InjectionHit]:
    """All injection/hidden-markup hits in one text. Deterministic; no model involved."""
    hits: list[InjectionHit] = []
    cleaned = sanitize(text).text
    folded = detection_form(cleaned, keep_punct=True)
    for name, pattern in _TEXT_PATTERNS.items():
        match = pattern.search(folded)
        if match:
            hits.append(InjectionHit(name, _snippet(folded, match)))
    for name, pattern in _RAW_PATTERNS.items():
        match = pattern.search(cleaned)
        if match:
            hits.append(InjectionHit(name, _snippet(cleaned, match)))
    return hits


def smuggling_flags(result: SanitizeResult) -> list[InjectionHit]:
    """Unicode smuggling characters seen by sanitize() (tag chars, bidi overrides, variation selectors...)."""
    return [InjectionHit(f"unicode_{flag}", f"{result.removed} characters removed") for flag in _SUSPICIOUS_SANITIZE_FLAGS if flag in result.flags]


def document_text_fields(doc: Document) -> list[str]:
    fields = [doc.title, *doc.synonyms]
    for section in doc.sections:
        fields.append(section.text)
        fields.extend(section.heading_path)
    fields.extend(str(v) for v in doc.metadata.values() if isinstance(v, str))
    return fields


def scan_document(doc: Document) -> list[InjectionHit]:
    seen: dict[str, InjectionHit] = {}
    for text in document_text_fields(doc):
        for hit in [*scan_text(text), *smuggling_flags(sanitize(text))]:
            seen.setdefault(hit.pattern_id, hit)
    return list(seen.values())
