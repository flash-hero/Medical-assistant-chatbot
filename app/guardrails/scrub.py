"""Output scrubbing of contact details the assistant must never invent: phone numbers outside the hospital
allow-list, bare and defanged domains. Used by app/guardrails/output_checks.py on every answer sentence.

Phone numbers:
- long phone formats anywhere (app/guardrails/pii.PHONE_PATTERNS);
- any run of 2+ digits after a call verb ("call", "dial", "appelez", "composez", "اتصل") or near an emergency
  word ("emergency", "urgence", "طوارئ", "poison") unless the hospital profile allows it: "call 911",
  "appelez le 17", "اتصل بالرقم ٩١١", "Call 9 1 1". Digits are judged on an ASCII copy of the same length, so
  Arabic-Indic and fullwidth digits cannot slip through. Quantities ("above 39 °C", "within 24 hours"),
  times, ratios and citation markers are not numbers to call.
Domains:
- any label.tld with a 2-3 letter TLD or a known longer one ("evil.xyz", "bit.ly/x", "site.ru");
- defanged forms: "example[.]com", "example(.)com", "evil [dot] com", "evil dot com".
One-letter parts ("e.g.", "i.e.", "U.S."), decimals ("2.5") and a capitalised common word after a missing
space ("fever.The") are kept.
"""

from __future__ import annotations

import re

from app.guardrails.numbers import ascii_digits
from app.guardrails.numeric import unit_follows
from app.guardrails.pii import PHONE_PATTERNS

_LONG_TLDS = (
    r"info|health|online|site|shop|store|link|click|help|life|live|care|clinic|doctor|email|tech|cloud|"
    r"space|website|today|news|blog|page|example|local|zone|world|network|support|center|company"
)
_DOMAIN = re.compile(
    rf"(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+(?P<tld>[a-z]{{2,3}}|{_LONG_TLDS})(?![\w-])"
    r"(?:/\S*)?",
    re.IGNORECASE,
)
_SPACE_MISSING_WORDS = frozenset(
    "the it is so an and but for you we he she le la les un une il on en de du des et if in at to as or no "
    "my me be do us".split()
)
_DOT_WORD_TLDS = (
    r"com|org|net|io|xyz|ru|cn|info|biz|ly|fr|ma|dz|tn|uk|top|app|dev|site|online|link|click|health|gov|edu|"
    r"ca|ch"
)
_DEFANGED_DOMAIN = re.compile(
    r"(?<![\w@.-])[a-z0-9-]+(?:\s*[\[({]\s*(?:\.|dot|point)\s*[\])}]\s*[a-z]{2,}"
    rf"|\s+(?:dot|point)\s+(?:{_DOT_WORD_TLDS}))+(?![\w-])(?:/\S*)?",
    re.IGNORECASE,
)

_CALL_VERB = re.compile(
    r"(?<!\w)(?:call|calling|dial|dialing|dialling|phone|ring|text|contact|reach|appelez|appeler|appelle|"
    r"composez|composer|compose|téléphonez|téléphoner|contactez|contacter|joignez|joindre|اتصل|اتصلي|اتصلوا|"
    r"اطلب|اطلبي|اطلبوا|كلم|كلمي|تواصل|تواصلي|عيط|عيطي|اضرب|ضرب)(?!\w)",
    re.IGNORECASE,
)
_EMERGENCY_WORD = re.compile(
    r"(?<!\w)(?:emergency|emergencies|ambulance|poison|hotline|helpline|crisis|urgence|urgences|samu|"
    r"pompiers|secours|antipoison|طوارئ|الطوارئ|للطوارئ|إسعاف|الإسعاف|اسعاف|الاسعاف|النجدة|نجدة|مستعجلات|"
    r"المستعجلات|السموم)(?!\w)",
    re.IGNORECASE,
)
# A run of 2+ digits, possibly spaced or dashed ("9 1 1", "1-800-222-1222"), not part of a time, ratio,
# decimal or citation marker ("24/7", "8:30", "2.5", "[2]").
_DIGIT_RUN = re.compile(r"(?<![\w.,:/\[])(?:\+\s?)?\d(?:[ .\-]?\d)+(?![\w\]]|[/:]\d|[.,]\d)")
_VERB_WINDOW = 40  # characters before the number that may hold the call verb
_EMERGENCY_BEFORE = 40
_EMERGENCY_AFTER = 30


def _domain_repl(m: re.Match[str]) -> str:
    tld = m.group("tld")
    missing_space = tld[0].isupper() and tld[1:].islower() and tld.casefold() in _SPACE_MISSING_WORDS
    return m.group(0) if missing_space and "/" not in m.group(0) else ""


def strip_domains(text: str) -> str:
    """Remove bare and defanged domains (URLs with a scheme and e-mails are removed before this)."""
    return _DOMAIN.sub(_domain_repl, _DEFANGED_DOMAIN.sub("", text))


def _allowed_run(run: str, allowed: frozenset[str]) -> bool:
    """The digits of `run` form an allowed number, or every 2+ digit group is one ("15 112")."""
    if re.sub(r"\D", "", run) in allowed:
        return True
    groups = [g for g in re.split(r"[ .\-]+", run.lstrip("+ ")) if g]
    return len(groups) > 1 and all(len(g) > 1 and g in allowed for g in groups)


def _contact_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - _VERB_WINDOW) : start]
    near = text[max(0, start - _EMERGENCY_BEFORE) : end + _EMERGENCY_AFTER]
    return bool(_CALL_VERB.search(before) or _EMERGENCY_WORD.search(near))


def _strip_contact_numbers(text: str, allowed: frozenset[str]) -> str:
    digits = ascii_digits(text)  # same length as `text`: offsets carry over
    cuts = [
        m.span()
        for m in _DIGIT_RUN.finditer(digits)
        if not unit_follows(digits, m.end())
        and not _allowed_run(m.group(0), allowed)
        and _contact_context(digits, m.start(), m.end())
    ]
    for start, end in reversed(cuts):
        text = text[:start] + text[end:]
    return text


def strip_phones(text: str, allowed: frozenset[str]) -> str:
    """Remove every phone-like number that is not in `allowed` (digits-only forms)."""

    def repl(m: re.Match[str]) -> str:
        return m.group(0) if _allowed_run(ascii_digits(m.group(0)), allowed) else ""

    text = _strip_contact_numbers(text, allowed)
    for pattern in PHONE_PATTERNS:
        text = pattern.sub(repl, text)
    return text
