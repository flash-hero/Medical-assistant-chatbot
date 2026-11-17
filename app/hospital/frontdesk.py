"""Deterministic front-desk answers rendered ONLY from HospitalProfile fields (no free generation of facts).

Matching runs on core.text.detection_form: exact keyword/name tokens, plus rapidfuzz partial matching for
longer keywords (misspellings such as "cardiolgy"). At most two sections are rendered (best matches
first)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from rapidfuzz import fuzz

from app.pipeline.texts import Texts
from core.schemas.hospital import FAQ, Department, HospitalProfile, L10n
from core.text import detection_form

_FUZZY_MIN = 88.0
_FUZZY_MIN_CHARS = 5
_MAX_SECTIONS = 2

# Profile-level topics: keywords (any language, normalised at match time) -> renderer key.
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "visiting_hours": (
        "visit",
        "visiting",
        "visitors",
        "visite",
        "visites",
        "visiter",
        "زياره",
        "الزياره",
        "ziyara",
        "nzour",
        "نزور",
    ),
    "documents_to_bring": (
        "documents",
        "papers",
        "bring",
        "apporter",
        "papiers",
        "pieces",
        "وثائق",
        "الوثائق",
        "الاوراق",
        "lwra9",
        "lwraq",
    ),
    "insurance": ("insurance", "mutuelle", "assurance", "carte vitale", "تامين", "التامين", "cnss", "cnops"),
    "directions": (
        "directions",
        "how to get",
        "get there",
        "metro",
        "bus",
        "acces",
        "itineraire",
        "venir",
        "الوصول",
        "كيف نوصل",
        "كيفاش نوصل",
        "transport",
        "tram",
    ),
    "address": ("address", "adresse", "عنوان", "العنوان", "location of the hospital", "l3onwan"),
    "contacts": (
        "phone",
        "call",
        "number",
        "telephone",
        "numero",
        "contact",
        "switchboard",
        "standard",
        "هاتف",
        "الهاتف",
        "رقم",
        "نعيط",
        "n3iyet",
        "noumero",
    ),
    "emergency": ("emergency number", "numero d urgence", "رقم الطوارئ", "samu"),
}


@dataclass(frozen=True)
class FrontDeskAnswer:
    text: str
    matched: tuple[str, ...]  # ids such as "department:cardiology", "faq:parking", "topic:visiting_hours"


def _norm(text: str) -> str:
    return detection_form(text)


def _token_hit(keyword: str, padded: str, raw: str) -> float:
    k = _norm(keyword)
    if not k:
        return 0.0
    if f" {k} " in padded:
        return 100.0
    if len(k) >= _FUZZY_MIN_CHARS:
        score = fuzz.partial_ratio(k, raw)
        return score if score >= _FUZZY_MIN else 0.0
    return 0.0


def _best(keywords: list[str], query: str) -> float:
    padded = f" {query} "
    return max((_token_hit(k, padded, query) for k in keywords), default=0.0)


def _l10n_all(value: L10n | None) -> list[str]:
    if value is None:
        return []
    return [v for v in (value.en, value.fr, value.ar) if v]


def _department_keywords(d: Department) -> list[str]:
    return [*d.keywords, *_l10n_all(d.name)]


def _faq_keywords(f: FAQ) -> list[str]:
    return list(f.keywords)


def _line(texts: Texts, key: str, value: str, locale: str) -> str:
    return f"- {texts.label(key, locale)}: {value}"


def render_department(d: Department, texts: Texts, locale: str) -> str:
    lines = [f"**{d.name.get(locale)}**" + (f": {d.description.get(locale)}" if d.description else "")]
    if d.location:
        lines.append(_line(texts, "location", d.location.get(locale), locale))
    if d.hours:
        lines.append(_line(texts, "hours", d.hours.get(locale), locale))
    if d.phone:
        lines.append(_line(texts, "phone", d.phone, locale))
    lines.append(
        f"- {texts.label('appointments_yes' if d.accepts_appointments else 'appointments_no', locale)}"
    )
    return "\n".join(lines)


def _render_contacts(p: HospitalProfile, texts: Texts, locale: str) -> str:
    rows = [p.main_phone, p.handoff, p.emergency, *p.crisis_lines]
    lines = [f"**{texts.label('contacts', locale)}**"]
    for c in rows:
        hours = f" ({c.hours.get(locale)})" if c.hours else ""
        lines.append(f"- {c.label.get(locale)}: {c.number}{hours}")
    return "\n".join(lines)


def _render_field(key: str, value: L10n | None) -> Callable[[HospitalProfile, Texts, str], str | None]:
    def render(p: HospitalProfile, texts: Texts, locale: str) -> str | None:
        field = getattr(p, key) if value is None else value
        if field is None:
            return None
        return f"**{texts.label(key, locale)}**\n{field.get(locale)}"

    return render


def _render_emergency(p: HospitalProfile, texts: Texts, locale: str) -> str:
    hours = f" ({p.emergency.hours.get(locale)})" if p.emergency.hours else ""
    label = p.emergency.label.get(locale)
    return f"**{texts.label('emergency', locale)}**\n- {label}: {p.emergency.number}{hours}"


_TOPIC_RENDERERS: dict[str, Callable[[HospitalProfile, Texts, str], str | None]] = {
    "visiting_hours": _render_field("visiting_hours", None),
    "documents_to_bring": _render_field("documents_to_bring", None),
    "insurance": _render_field("insurance", None),
    "directions": _render_field("directions", None),
    "address": _render_field("address", None),
    "contacts": _render_contacts,
    "emergency": _render_emergency,
}


def _render_faq(f: FAQ, texts: Texts, locale: str) -> str:
    return f"{f.answer.get(locale)}"


def _candidates(
    query: str, p: HospitalProfile
) -> list[tuple[float, str, Callable[[Texts, str], str | None]]]:
    found: list[tuple[float, str, Callable[[Texts, str], str | None]]] = []
    for d in p.departments:
        score = _best(_department_keywords(d), query)
        if score:
            found.append((score + 1, f"department:{d.id}", partial(render_department, d)))
    for f in p.faqs:
        score = _best(_faq_keywords(f), query)
        if score:
            found.append((score, f"faq:{f.id}", partial(_render_faq, f)))
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = _best(list(keywords), query)
        if score:
            found.append((score - 1, f"topic:{topic}", partial(_TOPIC_RENDERERS[topic], p)))
    return sorted(found, key=lambda x: -x[0])


def answer_front_desk(
    question: str, profile: HospitalProfile, texts: Texts, locale: str
) -> FrontDeskAnswer | None:
    """Render the best-matching profile sections for `question`, or None when nothing matches."""
    query = _norm(question)
    sections: list[str] = []
    matched: list[str] = []
    for _, key, render in _candidates(query, profile):
        if len(sections) >= _MAX_SECTIONS:
            break
        text = render(texts, locale)
        if text and text not in sections:
            sections.append(text)
            matched.append(key)
    if not sections:
        return None
    return FrontDeskAnswer(text="\n\n".join(sections), matched=tuple(matched))


def hospital_keywords(profile: HospitalProfile | None) -> tuple[str, ...]:
    """Normalised department names that mark a message as a front-desk question (intent heuristic only).
    Department keywords such as "heart" or "skin" are left out: they are medical words too."""
    if profile is None:
        return ()
    words = [name for d in profile.departments for name in _l10n_all(d.name)]
    return tuple(sorted({_norm(w) for w in words if len(_norm(w)) >= 3}))
