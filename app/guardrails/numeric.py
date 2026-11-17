"""Numeric grounding: every number that carries a unit or a percentage in an answer sentence must appear in a
cited passage after normalisation ("500 mg" == "500mg" == "500 milligrams" == "five hundred mg", "0,5 g" ==
"0.5 g" == "٠٫٥ غ", "٥٠٠ ملغ" == "500 mg").

- Number words (EN/FR/AR), Unicode digits, Arabic separators and invisible characters are normalised first
  (app/guardrails/numbers.py).
- Rate units stay in the unit: "10 mg/kg" is not grounded by "10 mg", "4 g per day" is "4 g/d". A bare unit IS
  grounded by the same value with a time rate ("4 g" by "4 g/day"), never by a weight or area rate.
- "4x2000mg" / "2 × 500 mg": the amount must be grounded, and the multiplier must appear as a count
  ("4 times", "4 tablets", "4 x") in the sources.
- Fail closed: a sentence with a dosing verb ("take", "prenez", "خذ"...) and a number that is not part of a
  parsed quantity ("take 2 every 4 hours", "take 5OO mg", "a tablet and a half") reports an UNPARSED
  quantity, so the sentence is dropped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.guardrails.numbers import normalise_numbers

UNPARSED = "?"  # unit of a number-like token next to a dosing verb that could not be parsed (fail closed)
MULTIPLIER = "×"

# canonical unit -> spellings (EN / FR / AR), longest first at match time
_UNITS: dict[str, tuple[str, ...]] = {
    "mg": (
        "milligrams",
        "milligram",
        "milligrammes",
        "milligramme",
        "mgs",
        "mg",
        "ملغ",
        "ملغم",
        "مغ",
        "ملليغرام",
        "ميليغرام",
    ),
    "mcg": ("micrograms", "microgram", "microgrammes", "microgramme", "mcg", "µg", "μg", "ميكروغرام"),
    "g": ("grams", "gram", "grammes", "gramme", "g", "غرام", "غ"),
    "kg": ("kilograms", "kilogram", "kilogrammes", "kilogramme", "kg", "كغ", "كلغ", "كيلوغرام"),
    "ml": ("millilitres", "milliliters", "millilitre", "milliliter", "ml", "cc", "مل", "ملليلتر"),
    "l": ("litres", "liters", "litre", "liter", "l", "لتر"),
    "%": ("percent", "per cent", "pour cent", "pourcent", "%", "٪", "بالمائة", "في المائة"),
    "mmhg": ("mmhg", "mm hg"),
    "mmol/l": ("mmol/l", "mmol/litre"),
    "mmol": ("mmol", "millimoles", "millimole"),
    "mg/dl": ("mg/dl",),
    "meq": ("meq", "milliequivalents", "milliequivalent", "milliéquivalents", "milliéquivalent"),
    "iu": ("iu", "ui", "international units", "unités internationales", "وحدة دولية"),
    "units": ("units", "unit", "unités", "unité", "وحدات", "وحدة"),
    "h": ("hours", "hour", "hrs", "hr", "heures", "heure", "h", "ساعات", "ساعة"),
    "min": ("minutes", "minute", "min", "دقائق", "دقيقة"),
    "d": ("days", "day", "jours", "jour", "أيام", "ايام", "يوم", "يوما"),
    "wk": ("weeks", "week", "semaines", "semaine", "أسابيع", "اسابيع", "أسبوع", "اسبوع"),
    "mo": ("months", "month", "mois", "أشهر", "اشهر", "شهر"),
    "y": ("years", "year", "ans", "an", "années", "année", "سنوات", "سنة", "عام", "أعوام"),
    "°c": ("°c", "degrees celsius", "degrés celsius", "degrés", "degrees", "درجة مئوية", "درجة"),
    "°f": ("°f", "degrees fahrenheit"),
    "bpm": ("bpm", "beats per minute", "battements par minute"),
    "tablets": (
        "tablets",
        "tablet",
        "caplets",
        "caplet",
        "pills",
        "pill",
        "capsules",
        "capsule",
        "comprimés",
        "comprimé",
        "gélules",
        "gélule",
        "أقراص",
        "اقراص",
        "قرص",
        "حبوب",
        "حبات",
        "حبة",
        "كبسولات",
        "كبسولة",
    ),
    "tsp": (
        "teaspoons",
        "teaspoon",
        "teaspoonfuls",
        "teaspoonful",
        "tsp",
        "cuillères à café",
        "cuillère à café",
        "cuilleres a cafe",
        "cuillere a cafe",
        "c. à café",
        "ملاعق صغيرة",
        "ملعقة صغيرة",
    ),
    "tbsp": (
        "tablespoons",
        "tablespoon",
        "tablespoonfuls",
        "tablespoonful",
        "tbsp",
        "cuillères à soupe",
        "cuillère à soupe",
        "cuilleres a soupe",
        "cuillere a soupe",
        "c. à soupe",
        "ملاعق كبيرة",
        "ملعقة كبيرة",
    ),
    "spoons": ("spoonfuls", "spoonful", "spoons", "spoon", "cuillères", "cuillère", "ملاعق", "ملعقة"),
    "drops": ("drops", "drop", "gouttes", "goutte", "نقاط", "نقطة", "قطرات", "قطرة"),
    "puffs": (
        "puffs",
        "puff",
        "inhalations",
        "inhalation",
        "bouffées",
        "bouffée",
        "بخات",
        "بخة",
        "نفخات",
        "نفخة",
    ),
    "sprays": ("sprays", "spray", "pulvérisations", "pulvérisation", "رشات", "رشة"),
    "sachets": ("sachets", "sachet", "أكياس", "اكياس", "كيس"),
    "ampoules": ("ampoules", "ampoule", "أمبولات", "أمبولة"),
    "suppositories": ("suppositories", "suppository", "suppositoires", "suppositoire", "تحاميل", "تحميلة"),
    "glasses": ("glasses", "glass", "verres", "verre", "أكواب", "كوب", "كأس"),
    "times": ("times", "fois", "مرات", "مرة"),
    "doses": ("doses", "dose", "prises", "prise", "جرعات", "جرعة"),
}
# rate denominators: canonical -> spellings ("/kg", "per day", "par jour", "لكل كغ")
_DENOMINATORS: dict[str, tuple[str, ...]] = {
    "kg": ("kilograms", "kilogram", "kilogrammes", "kilogramme", "kilos", "kilo", "kg", "كيلوغرام", "كغ", "كلغ"),
    "d": ("24 hours", "24 heures", "24 h", "24h", "days", "day", "jours", "jour", "اليوم", "يوم"),
    "m2": ("square metres", "square meters", "square metre", "square meter", "mètre carré", "m2"),
    "h": ("hours", "hour", "heures", "heure", "ساعة"),
    "min": ("minutes", "minute"),
    "wk": ("weeks", "week", "semaines", "semaine", "الأسبوع", "أسبوع"),
    "dose": ("doses", "dose", "prises", "prise", "الجرعة", "جرعة"),
}
_SHORT_DENOMINATORS: dict[str, str] = {"d": "d", "j": "d", "h": "h", "hr": "h", "min": "min"}
_TIME_RATES = frozenset({"d", "h", "min", "wk", "dose"})
_COUNT_UNITS = frozenset(
    {"times", "tablets", "doses", "drops", "puffs", "sprays", "sachets", "tsp", "tbsp", "spoons", "ampoules"}
)

_SPELLING_TO_UNIT = {s: unit for unit, spellings in _UNITS.items() for s in spellings}
_SPELLING_TO_DEN = {s: den for den, spellings in _DENOMINATORS.items() for s in spellings}


def _alt(spellings: Iterable[str]) -> str:
    return "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))


_UNIT_ALT = _alt(_SPELLING_TO_UNIT)
_DEN_WORD = _alt(_SPELLING_TO_DEN)
_DEN_ANY = _alt((*_SPELLING_TO_DEN, *_SHORT_DENOMINATORS))
_PER = r"(?:per|par|a|an|each|every|chaque|لكل|كل|في)"
_RATE = (
    rf"(?:\s*/\s*(?P<s1>{_DEN_ANY})(?!\w)|\s+{_PER}\s+(?P<w1>{_DEN_WORD})(?!\w)"
    r"|\s+(?P<daily>daily|quotidiens?|quotidiennes?|يوميا|يومياً)(?!\w)"
    r"|\s+(?:in|over|within|en|sur|خلال|في)\s+(?P<per24>24\s*(?:h|hours?|heures?|ساعة))(?!\w))"
    rf"(?:\s*/\s*(?P<s2>{_DEN_ANY})(?!\w)|\s+{_PER}\s+(?P<w2>{_DEN_WORD})(?!\w))?"
)
_NUM = r"(?:[1-9]\d{0,2}(?:[ ,]\d{3})+(?!\d)|\d+(?:[.,]\d+)?)"
_QUANTITY = re.compile(
    rf"(?<![\w.,])(?P<n1>{_NUM})(?:\s*(?:-|–|to|à|a|إلى|الى)\s*(?P<n2>{_NUM}))?\s?(?P<unit>{_UNIT_ALT})"
    rf"(?:{_RATE})?(?!\w)",
    re.IGNORECASE,
)
_MULTIPLIED = re.compile(
    rf"(?<![\w.,])(?P<times>\d+)\s*[x×*]\s*(?P<n1>{_NUM})\s?(?P<unit>{_UNIT_ALT})(?:{_RATE})?(?!\w)",
    re.IGNORECASE,
)
_THOUSANDS = re.compile(r"^[1-9]\d{0,2}(?:[ ,]\d{3})+$")
_NUMBER_LIKE = re.compile(r"\d+(?:[.,]\d+)?|(?<!\w)(?:half|demie?|نصف)(?!\w)", re.IGNORECASE)
_CITATION = re.compile(r"\[\d+(?:\s*[,;]\s*\d+)*\]")
_DOSING_VERB = re.compile(
    r"(?<!\w)(?:take|give|use|apply|inhale|swallow|chew|administer|inject|dissolve|double|increase|reduce|"
    r"spray|insert|prends|prenez|prendre|donnez|donner|administrez|administrer|appliquez|appliquer|avalez|"
    r"avaler|utilisez|utiliser|inhalez|mâchez|dissolvez|injectez|augmentez|diminuez|réduisez|doublez|"
    r"mettez|خذ|خذي|خذوا|تأخذ|تاخذ|تأخذي|تناول|تناولي|تتناول|تتناولي|أعط|اعط|أعطي|اعطي|أعطه|اعطه|أعطها|"
    r"اعطها|تعطي|استعمل|استعملي|تستعمل|استخدم|استخدمي|تستخدم|ضع|ضعي|ابلع|ابلعي|امضغ|زد|قلل|ضاعف|ضاعفي)(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Quantity:
    value: str  # normalised number ("0.5", "500")
    unit: str  # canonical unit, with its rate when present ("mg/kg", "g/d"); MULTIPLIER; UNPARSED


def _norm_number(raw: str) -> str:
    """ "1,000" / "1 000" -> "1000"; "0,5" / "0.50" -> "0.5"; "05" -> "5"."""
    n = re.sub(r"[ ,]", "", raw) if _THOUSANDS.match(raw) else raw.replace(",", ".")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    n = n.lstrip("0")
    return "0" + n if not n or n.startswith(".") else n


def _den(m: re.Match[str], short: str, word: str) -> str:
    raw = m.group(short) or m.group(word)
    if raw is None:
        return ""
    key = raw.lower()
    return _SHORT_DENOMINATORS.get(key) or _SPELLING_TO_DEN.get(key) or _SPELLING_TO_DEN.get(raw, "")


def _unit(m: re.Match[str]) -> str:
    raw = m.group("unit")
    base = _SPELLING_TO_UNIT.get(raw.lower()) or _SPELLING_TO_UNIT.get(raw, "")
    if not base:
        return ""
    first = _den(m, "s1", "w1") or ("d" if m.group("daily") or m.group("per24") else "")
    second = _den(m, "s2", "w2")
    return "/".join(p for p in (base, first, second) if p)


def _scan(text: str) -> tuple[list[Quantity], list[tuple[int, int]], str]:
    """Quantities of `text`, the spans they cover in the normalised copy, and that copy."""
    norm = normalise_numbers(text)
    found: list[Quantity] = []
    spans: list[tuple[int, int]] = []
    for m in _MULTIPLIED.finditer(norm):
        unit = _unit(m)
        if unit:
            found.append(Quantity(_norm_number(m.group("n1")), unit))
            found.append(Quantity(_norm_number(m.group("times")), MULTIPLIER))
            spans.append(m.span())
    for m in _QUANTITY.finditer(norm):
        unit = _unit(m)
        if not unit or any(a < m.end() and m.start() < b for a, b in spans):
            continue
        found.append(Quantity(_norm_number(m.group("n1")), unit))
        if m.group("n2"):
            found.append(Quantity(_norm_number(m.group("n2")), unit))
        spans.append(m.span())
    return found, spans, norm


_UNIT_AFTER = re.compile(
    rf"(?:\s*(?:-|–|to|à|a|إلى|الى)\s*{_NUM})?\s?(?:{_UNIT_ALT})(?!\w)", re.IGNORECASE
)


def unit_follows(text: str, pos: int) -> bool:
    """True when a unit (optionally after a range end: "10 to 12 days") starts at `pos` of `text` (ASCII
    digits). Lets the phone allow-list keep "above 39 °C" next to the word "emergency"."""
    return _UNIT_AFTER.match(text, pos) is not None


def extract_quantities(text: str) -> tuple[Quantity, ...]:
    """All number+unit / percentage quantities in `text`, normalised (ranges yield both ends)."""
    return tuple(_scan(text)[0])


def _unparsed(norm: str, spans: list[tuple[int, int]]) -> list[Quantity]:
    """Number-like tokens outside every parsed quantity, when the sentence has a dosing verb."""
    if not _DOSING_VERB.search(norm):
        return []
    covered = [*spans, *(m.span() for m in _CITATION.finditer(norm))]
    return [
        Quantity(m.group(0), UNPARSED)
        for m in _NUMBER_LIKE.finditer(norm)
        if not any(a <= m.start() and m.end() <= b for a, b in covered)
    ]


def _available(sources: Iterable[str]) -> set[Quantity]:
    """Source quantities, plus the bare-unit form of every time-rate quantity ("4 g/d" also grounds "4 g")."""
    out: set[Quantity] = set()
    for src in sources:
        for q in extract_quantities(src):
            out.add(q)
            parts = q.unit.split("/")
            while len(parts) > 1 and parts[-1] in _TIME_RATES:
                parts.pop()
                out.add(Quantity(q.value, "/".join(parts)))
    return out


def _grounded(q: Quantity, available: set[Quantity]) -> bool:
    if q.unit == MULTIPLIER:
        return any(
            a.value == q.value and (a.unit == MULTIPLIER or a.unit.split("/")[0] in _COUNT_UNITS)
            for a in available
        )
    return q in available


def ungrounded_quantities(sentence: str, sources: Iterable[str]) -> tuple[Quantity, ...]:
    """Quantities of `sentence` that appear in none of `sources` (empty tuple = grounded), plus UNPARSED
    tokens when a dosing verb meets a number that could not be parsed (fail closed)."""
    wanted, spans, norm = _scan(sentence)
    unparsed = _unparsed(norm, spans)
    if not wanted:
        return tuple(unparsed)
    available = _available(sources)
    return (*(q for q in wanted if not _grounded(q, available)), *unparsed)
