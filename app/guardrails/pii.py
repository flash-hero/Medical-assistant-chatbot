"""Deterministic PII redaction, applied to every user message BEFORE any model call or log line.

Replaced with placeholders: e-mails [EMAIL], IBANs [IBAN], payment cards (Luhn-valid) [CARD], exact dates of
birth [DOB] (age statements such as "I am 45" are kept), national-ID / medical-record-like numbers [ID], phone
numbers [PHONE] (international +212/+213/+216/+33/+1 and national 0X / Tunisian 8-digit formats) and
self-introduced names
[NAME] ("my name is", "je m'appelle", "اسمي", "ana smiti").
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_CARD = re.compile(r"(?<![\d+])[1-9](?:[ -]?\d){12,18}(?!\d)")  # card numbers never start with 0

_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[ée]cembre|يناير|فبراير|مارس|أبريل|ابريل|ماي|مايو|يونيو|يونيوز|يوليو|"
    r"يوليوز|غشت|أغسطس|اغسطس|شتنبر|سبتمبر|أكتوبر|اكتوبر|نونبر|نوفمبر|دجنبر|ديسمبر|جانفي|فيفري|أفريل|"
    r"افريل|جوان|جويلية|أوت|اوت"
)
_NUMERIC_DATE = r"\d{1,2}[/.\-]\d{1,2}[/.\-](?:\d{4}|\d{2})|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}"
_TEXT_DATE = (
    rf"\d{{1,2}}(?:st|nd|rd|th|er)?\s+(?:of\s+)?(?:{_MONTHS})\.?,?\s+\d{{4}}|"
    rf"(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
)
_DOB_CONTEXT = re.compile(
    r"(?P<ctx>\b(?:born(?:\s+on)?|date\s+of\s+birth|birth\s*date|birthday|d\.?o\.?b\.?|n[ée]e?\s+le|"
    r"date\s+de\s+naissance|ma\s+naissance)|مواليد|تاريخ\s+الميلاد|تاريخ\s+الازدياد|تاريخ\s+ازديادي|"
    r"تزاديت|زديت|ولدت|مولود|مولودة)\s*(?:is|was|on|in|le|est|c'est|:|-|في|نهار|ف|هو)?\s*"
    rf"(?P<date>{_TEXT_DATE}|{_NUMERIC_DATE})",
    re.IGNORECASE,
)
_BARE_NUMERIC_DATE = re.compile(rf"(?<![\d/.\-])(?:{_NUMERIC_DATE})(?![\d/.\-]*\d)")
_YEAR_IN_DATE = re.compile(r"(\d{4})|(?:[/.\-](\d{2}))$")

_ID_CONTEXT = re.compile(
    r"(?P<ctx>\b(?:mrn|medical\s+record(?:\s+number)?|record\s+number|patient\s+(?:id|number|no)|"
    r"hospital\s+number|dossier(?:\s+m[ée]dical)?|n°\s*de\s+dossier|num[ée]ro\s+de\s+dossier|ipp|nir|"
    r"s[ée]curit[ée]\s+sociale|social\s+security(?:\s+number)?|ssn|passport(?:\s+number)?|passeport|cin|"
    r"carte\s+d'identit[ée]|id\s+card|id\s+number|national\s+id|insurance\s+number|matricule)|"
    r"رقم\s+الملف|رقم\s+البطاقة|رقم\s+الهوية|البطاقة\s+الوطنية|رقم\s+التأمين|رقم\s+الضمان\s+الاجتماعي|"
    r"لاكارط|cnss|cnops)\s*(?:number|no\.?|n°|num[ée]ro|#|:|est|is)?\s*[:#]?\s*"
    r"(?P<id>[A-Z]{0,3}[\s-]?\d[\d\s-]{3,20}\d|[A-Z]{1,2}\d{4,10})",
    re.IGNORECASE,
)
_NIR = re.compile(
    r"(?<!\d)[12][\s.]?\d{2}[\s.]?(?:0[1-9]|1[0-2]|[2-9]\d)[\s.]?(?:\d{2}|2[AB])[\s.]?\d{3}[\s.]?\d{3}"
    r"(?:[\s.]?\d{2})?(?!\d)"
)
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_CIN = re.compile(r"\b[A-Z]{1,2}\d{5,6}\b")  # Moroccan CIN style; case-sensitive on purpose

_PHONES = (
    re.compile(r"(?<![\w+])(?:\+|00)\d{1,3}[\s.\-]?(?:\(0\)[\s.\-]?)?\d(?:[\s.\-]?\d){6,12}(?!\d)"),
    re.compile(r"(?<![\d+])0[1-9](?:[\s.\-]?\d{2}){4}(?!\d)"),  # FR / MA / DZ national, incl. 06 / 07 mobiles
    re.compile(r"(?<![\d+])0[5-7]\d{8}(?!\d)"),
    re.compile(r"(?<![\d+])\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)"),  # North American
    re.compile(r"(?<![\d+.,])[24579]\d(?:[\s.]?\d{3}){2}(?![\d.,])"),  # Tunisian 8-digit
)
PHONE_PATTERNS: tuple[re.Pattern[str], ...] = _PHONES  # reused by output checks (phone allow-list)
_LONG_DIGITS = re.compile(r"(?<!\d)\d{9,}(?!\d)")

_NAME_TRIGGER = re.compile(
    r"(?:\bmy\s+name\s+is|\bmy\s+name's|\bi\s+am\s+called|\bi'm\s+called|"
    r"\bje\s+m['’ ]?appelle|\bmon\s+(?:nom|pr[ée]nom)\s+(?:est|c'est)|\bmoi\s+c['’]est|"
    r"\bana\s+smiti|\bsmiti|\bana\s+ismi|\bismi|\besmi|"
    r"(?:أنا\s+|انا\s+)?(?:اسمي|إسمي|سميتي|كنسمى|يسموني|أدعى|ادعى))\s*[:,]?\s*",
    re.IGNORECASE,
)
_NAME_TOKEN = re.compile(r"[^\W\d_][\w'’\-]*", re.UNICODE)
_NAME_STOP = frozenset(
    [
        "and",
        "but",
        "i",
        "i'm",
        "im",
        "am",
        "have",
        "has",
        "had",
        "with",
        "from",
        "et",
        "mais",
        "je",
        "j'ai",
        "suis",
        "ai",
        "avec",
        "de",
        "du",
        "w",
        "o",
        "and",
        "wa",
        "ana",
        "3andi",
        "عندي",
        "انا",
        "أنا",
        "و",
        "عمري",
        "من",
        "في",
        "كنعاني",
        "عندو",
    ]
)
_MAX_NAME_TOKENS = 3


@dataclass(frozen=True)
class Redaction:
    text: str
    counts: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    s = re.sub(r"\s", "", raw).upper()
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def _plausible_birth_year(date_text: str, today: date) -> bool:
    m = _YEAR_IN_DATE.search(date_text)
    if not m:
        return False
    year = int(m.group(1) or m.group(2))
    if year < 100:
        year += 1900 if year > today.year % 100 else 2000
    return 1900 <= year <= today.year - 10


class _Redactor:
    def __init__(self, today: date) -> None:
        self.today = today
        self.counts: Counter[str] = Counter()

    def sub(
        self, pattern: re.Pattern[str], text: str, label: str, keep: Callable[[re.Match[str]], bool]
    ) -> str:
        def repl(m: re.Match[str]) -> str:
            if not keep(m):
                return m.group(0)
            self.counts[label] += 1
            return f"[{label}]"

        return pattern.sub(repl, text)

    def sub_group(self, pattern: re.Pattern[str], text: str, label: str, group: str) -> str:
        def repl(m: re.Match[str]) -> str:
            self.counts[label] += 1
            start, end = m.span(group)
            whole_start = m.start()
            g = m.group(0)
            return g[: start - whole_start] + f"[{label}]" + g[end - whole_start :]

        return pattern.sub(repl, text)

    def names(self, text: str) -> str:
        out: list[str] = []
        pos = 0
        for m in _NAME_TRIGGER.finditer(text):
            if m.start() < pos:
                continue
            end = _name_span_end(text, m.end())
            if end == m.end():
                continue
            out.append(text[pos : m.end()])
            out.append("[NAME]")
            self.counts["NAME"] += 1
            pos = end
        out.append(text[pos:])
        return "".join(out)


def _name_span_end(text: str, start: int) -> int:
    """End offset of up to _MAX_NAME_TOKENS name-like tokens starting at `start` (stops at stop words)."""
    end = start
    for taken, tok in enumerate(_NAME_TOKEN.finditer(text, start)):  # taken = tokens accepted so far
        gap = text[end : tok.start()]
        if taken and (gap.strip() or "\n" in gap):
            break
        if not taken and gap.strip():
            break
        word = tok.group(0).casefold()
        if word in _NAME_STOP or (taken and word.startswith("و") and len(word) > 2):
            break
        end = tok.end()
        if taken + 1 >= _MAX_NAME_TOKENS:
            break
    return end


def redact(text: str, *, today: date | None = None) -> Redaction:
    """Return the redacted text and a count per placeholder type. Pure function, never logs."""
    r = _Redactor(today or date.today())
    t = r.sub(_EMAIL, text, "EMAIL", lambda m: True)
    t = r.sub(_IBAN, t, "IBAN", lambda m: _iban_ok(m.group(0)))
    t = r.sub(_CARD, t, "CARD", lambda m: _luhn_ok(re.sub(r"\D", "", m.group(0))))
    t = r.sub_group(_DOB_CONTEXT, t, "DOB", "date")
    t = r.sub(_BARE_NUMERIC_DATE, t, "DOB", lambda m: _plausible_birth_year(m.group(0), r.today))
    t = r.sub_group(_ID_CONTEXT, t, "ID", "id")
    t = r.sub(_SSN, t, "ID", lambda m: True)
    t = r.sub(_NIR, t, "ID", lambda m: len(re.sub(r"\D", "", m.group(0))) >= 13)
    t = r.sub(_CIN, t, "ID", lambda m: True)
    for pattern in _PHONES:
        t = r.sub(pattern, t, "PHONE", lambda m: True)
    t = r.sub(_LONG_DIGITS, t, "ID", lambda m: True)
    t = r.names(t)
    return Redaction(text=t, counts=MappingProxyType(dict(r.counts)))
