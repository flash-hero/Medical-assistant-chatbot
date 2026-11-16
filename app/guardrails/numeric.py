"""Numeric grounding: every number that carries a unit or a percentage in an answer sentence must appear in a cited
passage after normalisation ("500 mg" == "500mg" == "500 milligrams", "0,5 g" == "0.5 g", "٥٠٠ ملغ" == "500 mg").
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_DIGITS = str.maketrans({**{chr(0x0660 + i): str(i) for i in range(10)}, **{chr(0x06F0 + i): str(i) for i in range(10)}})

# canonical unit -> spellings (EN / FR / AR), longest first at match time
_UNITS: dict[str, tuple[str, ...]] = {
    "mg": ("milligrams", "milligram", "milligrammes", "milligramme", "mg", "ملغ", "ملغم", "مغ", "ملليغرام", "ميليغرام"),
    "mcg": ("micrograms", "microgram", "microgrammes", "microgramme", "mcg", "µg", "μg", "ميكروغرام"),
    "g": ("grams", "gram", "grammes", "gramme", "g", "غرام", "غ"),
    "kg": ("kilograms", "kilogram", "kilogrammes", "kilogramme", "kg", "كغ", "كلغ", "كيلوغرام"),
    "ml": ("millilitres", "milliliters", "millilitre", "milliliter", "ml", "مل", "ملليلتر"),
    "l": ("litres", "liters", "litre", "liter", "l", "لتر"),
    "%": ("percent", "per cent", "pour cent", "pourcent", "%", "٪", "بالمائة", "في المائة"),
    "mmhg": ("mmhg", "mm hg"),
    "mmol/l": ("mmol/l", "mmol/litre"),
    "mg/dl": ("mg/dl",),
    "iu": ("iu", "ui", "international units", "unités internationales", "وحدة دولية"),
    "units": ("units", "unit", "unités", "unité", "وحدات", "وحدة"),
    "h": ("hours", "hour", "hrs", "hr", "heures", "heure", "h", "ساعات", "ساعة"),
    "min": ("minutes", "minute", "min", "دقائق", "دقيقة"),
    "d": ("days", "day", "jours", "jour", "أيام", "ايام", "يوم"),
    "wk": ("weeks", "week", "semaines", "semaine", "أسابيع", "اسابيع", "أسبوع", "اسبوع"),
    "mo": ("months", "month", "mois", "أشهر", "اشهر", "شهر"),
    "y": ("years", "year", "ans", "an", "années", "année", "سنوات", "سنة", "عام", "أعوام"),
    "°c": ("°c", "degrees celsius", "degrés celsius", "degrés", "degrees", "درجة مئوية", "درجة"),
    "°f": ("°f", "degrees fahrenheit"),
    "bpm": ("bpm", "beats per minute", "battements par minute"),
    "tablets": ("tablets", "tablet", "pills", "pill", "capsules", "capsule", "comprimés", "comprimé", "gélules",
                "gélule", "أقراص", "اقراص", "قرص", "حبوب", "حبة"),
    "times": ("times", "fois", "مرات", "مرة"),
    "doses": ("doses", "dose", "جرعات", "جرعة"),
}
_SPELLING_TO_UNIT = {s: unit for unit, spellings in _UNITS.items() for s in spellings}
_UNIT_ALT = "|".join(re.escape(s) for s in sorted(_SPELLING_TO_UNIT, key=len, reverse=True))
_NUM = r"(?:[1-9]\d{0,2}(?:[ ,  ]\d{3})+(?!\d)|\d+(?:[.,]\d+)?)"
_QUANTITY = re.compile(
    rf"(?<![\w.,])({_NUM})(?:\s*(?:-|–|to|à|a|إلى|الى)\s*({_NUM}))?\s?({_UNIT_ALT})(?![\w])",
    re.IGNORECASE,
)
_THOUSANDS = re.compile(r"^[1-9]\d{0,2}(?:[ ,  ]\d{3})+$")


@dataclass(frozen=True)
class Quantity:
    value: str  # normalised number ("0.5", "500")
    unit: str  # canonical unit


def _norm_number(raw: str) -> str:
    """"1,000" / "1 000" -> "1000"; "0,5" / "0.50" -> "0.5"; "05" -> "5"."""
    n = raw.translate(_DIGITS)
    n = re.sub(r"[ ,  ]", "", n) if _THOUSANDS.match(n) else n.replace(",", ".")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    n = n.lstrip("0")
    return "0" + n if not n or n.startswith(".") else n


def extract_quantities(text: str) -> tuple[Quantity, ...]:
    """All number+unit / percentage quantities in `text`, normalised (ranges yield both ends)."""
    found: list[Quantity] = []
    for m in _QUANTITY.finditer(text.translate(_DIGITS)):
        unit = _SPELLING_TO_UNIT.get(m.group(3).lower(), _SPELLING_TO_UNIT.get(m.group(3), ""))
        if not unit:
            continue
        found.append(Quantity(_norm_number(m.group(1)), unit))
        if m.group(2):
            found.append(Quantity(_norm_number(m.group(2)), unit))
    return tuple(found)


def ungrounded_quantities(sentence: str, sources: Iterable[str]) -> tuple[Quantity, ...]:
    """Quantities of `sentence` that appear in none of `sources` (empty tuple = grounded)."""
    wanted = extract_quantities(sentence)
    if not wanted:
        return ()
    available: set[Quantity] = set()
    for src in sources:
        available.update(extract_quantities(src))
    return tuple(q for q in wanted if q not in available)
