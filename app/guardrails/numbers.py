"""Number normalisation for MATCHING copies of text (numeric grounding, claim patterns, phone and PII checks).

Never shown and never sent to a model. Three levels:
  ascii_digits(text)      every Unicode decimal digit (Arabic-Indic, Persian, fullwidth...) -> ASCII. Same
                          length, so offsets found on the copy are valid on the original.
  strip_format(text)      removes format characters (ZWSP, ZWJ/ZWNJ, LRM/RLM, BOM, soft hyphen...).
  normalise_numbers(text) NFKC + both of the above + Arabic decimal/thousands separators + simple fractions
                          + EN/FR/AR number words -> digits ("five hundred" -> "500", "deux" -> "2",
                          "خمسة وعشرون" -> "25", "قرصين" -> "2 قرص", "twice" -> "2 times").

"one" / "un" / "une" / "واحد" are also articles or pronouns, so they become "1" only next to a dose unit
("one tablet", "une gélule", "قرص واحد") or inside a compound ("twenty-one", "one and a half").
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

_AR_DECIMAL = "٫"
_AR_THOUSANDS = "٬"

# Dose units next to which "one" / "un(e)" / "واحد" is a number, not an article.
_DOSE_UNIT_WORDS = (
    r"(?:mg|mgs|milligrams?|milligrammes?|g|grams?|grammes?|mcg|micrograms?|microgrammes?|ml|"
    r"millilit(?:er|re)s?|cc|tablets?|pills?|capsules?|caplets?|drops?|puffs?|sprays?|sachets?|teaspoons?|"
    r"tablespoons?|tsp|tbsp|spoonfuls?|doses?|units?|comprim[ée]s?|g[ée]lules?|gouttes?|bouff[ée]es?|"
    r"pulv[ée]risations?|cuill[èe]res?|prises?|unit[ée]s?)"
)
_AR_DOSE_NOUNS = (
    r"(?:قرص|حبة|حبه|كبسولة|كبسوله|نقطة|نقطه|قطرة|قطره|ملعقة|ملعقه|كيس|جرعة|جرعه|بخة|بخه|وحدة|وحده)"
)

_EN_SMALL: Mapping[str, int] = {
    "zero": 0,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_FR_SMALL: Mapping[str, int] = {
    "zéro": 0,
    "zero": 0,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
    "vingt": 20,
    "vingts": 20,
    "trente": 30,
    "quarante": 40,
    "cinquante": 50,
    "soixante": 60,
    "quatre-vingt": 80,
    "quatre-vingts": 80,
}
_AR_SMALL: Mapping[str, int] = {
    "صفر": 0,
    "اثنان": 2,
    "اثنين": 2,
    "اثنتان": 2,
    "اثنتين": 2,
    "ثلاث": 3,
    "ثلاثة": 3,
    "أربع": 4,
    "اربع": 4,
    "أربعة": 4,
    "اربعة": 4,
    "خمس": 5,
    "خمسة": 5,
    "ست": 6,
    "ستة": 6,
    "سبع": 7,
    "سبعة": 7,
    "ثمان": 8,
    "ثماني": 8,
    "ثمانية": 8,
    "تسع": 9,
    "تسعة": 9,
    "عشر": 10,
    "عشرة": 10,
    "عشرون": 20,
    "عشرين": 20,
    "ثلاثون": 30,
    "ثلاثين": 30,
    "أربعون": 40,
    "اربعون": 40,
    "أربعين": 40,
    "اربعين": 40,
    "خمسون": 50,
    "خمسين": 50,
    "ستون": 60,
    "ستين": 60,
    "سبعون": 70,
    "سبعين": 70,
    "ثمانون": 80,
    "ثمانين": 80,
    "تسعون": 90,
    "تسعين": 90,
}
_AR_HUNDREDS: Mapping[str, int] = {
    **{
        f"{p}{h}": n * 100
        for h in ("مائة", "مئة")
        for p, n in (
            ("ثلاث", 3),
            ("ثلاثة", 3),
            ("أربع", 4),
            ("اربع", 4),
            ("خمس", 5),
            ("ست", 6),
            ("سبع", 7),
            ("ثمان", 8),
            ("ثماني", 8),
            ("تسع", 9),
        )
    },
    "مائتان": 200,
    "مائتين": 200,
    "مئتان": 200,
    "مئتين": 200,
}
_HUNDRED = frozenset({"hundred", "cent", "cents", "مائة", "مئة"})
_THOUSAND: Mapping[str, int] = {
    "thousand": 1,
    "mille": 1,
    "ألف": 1,
    "الف": 1,
    "آلاف": 1,
    "الاف": 1,
    "ألفان": 2,
    "ألفين": 2,
    "الفين": 2,
}
_ONE = frozenset({"one", "un", "une", "واحد", "واحدة", "أحد", "احد"})

_WORD_VALUE: dict[str, tuple[int, str]] = {
    **{w: (v, "en") for w, v in _EN_SMALL.items()},
    **{w: (v, "fr") for w, v in _FR_SMALL.items()},
    **{w: (v, "ar") for w, v in _AR_SMALL.items()},
    **{w: (v, "ar") for w, v in _AR_HUNDREDS.items()},
    **dict.fromkeys(("one",), (1, "en")),
    **dict.fromkeys(("un", "une"), (1, "fr")),
    **dict.fromkeys(("واحد", "واحدة", "أحد", "احد"), (1, "ar")),
    **dict.fromkeys(("اثنا", "اثني"), (2, "ar")),
}
_NUMBER_WORD = "|".join(
    sorted((re.escape(w) for w in (*_WORD_VALUE, *_HUNDRED, *_THOUSAND)), key=len, reverse=True)
)
# A run of number words: words joined by spaces, hyphens, "and" / "et" or the Arabic "و" (often glued).
_RUN = re.compile(
    rf"(?<![\w-])(?:و)?(?:{_NUMBER_WORD})(?:(?:\s*-\s*|\s+(?:and|et)\s+|\s+و\s*|\s+)(?:{_NUMBER_WORD}))*(?![\w-])",
    re.IGNORECASE,
)
_RUN_PART = re.compile(rf"(?:و)?({_NUMBER_WORD})", re.IGNORECASE)
_AND_A_HALF = re.compile(r"(\d+) (?:and a half|et demie?)\b", re.IGNORECASE)
_ONE_AND_A_HALF = re.compile(r"(?<!\w)(?:one and a half|une? et demie?)(?!\w)", re.IGNORECASE)
_HALF_A = re.compile(r"(?<!\w)(?:half an?|un demi|une demie|demi-|demie-)\s*(?=\w)", re.IGNORECASE)
_AR_HALF = re.compile(r"(?<!\w)نصف(?=\s)")
_FRACTION = re.compile(r"(?<![\d/.,])([123])\s*/\s*([2348])(?![/\d])")
_PER_CENT = re.compile(r"(?<!\w)(?:pour|per)\s+cent(?!\w)", re.IGNORECASE)  # not "pour 100"
_TWICE = re.compile(r"(?<!\w)(twice|thrice)(?!\w)", re.IGNORECASE)
_AR_DUAL: Mapping[str, str] = {
    "قرصين": "قرص",
    "قرصان": "قرص",
    "حبتين": "حبة",
    "حبتان": "حبة",
    "كبسولتين": "كبسولة",
    "كبسولتان": "كبسولة",
    "مرتين": "مرة",
    "مرتان": "مرة",
    "يومين": "يوم",
    "يومان": "يوم",
    "ساعتين": "ساعة",
    "ساعتان": "ساعة",
    "دقيقتين": "دقيقة",
    "أسبوعين": "أسبوع",
    "اسبوعين": "أسبوع",
    "شهرين": "شهر",
    "سنتين": "سنة",
    "عامين": "عام",
    "ملعقتين": "ملعقة",
    "ملعقتان": "ملعقة",
    "جرعتين": "جرعة",
    "جرعتان": "جرعة",
    "نقطتين": "نقطة",
    "قطرتين": "قطرة",
    "كيسين": "كيس",
    "بختين": "بخة",
}
_AR_DUAL_RE = re.compile(r"(?<!\w)(" + "|".join(_AR_DUAL) + r")(?!\w)")
_AR_ONE_AFTER = re.compile(rf"(?<!\w)({_AR_DOSE_NOUNS})\s+(?:واحد|واحدة|واحده)(?!\w)")
_ONE_BEFORE_UNIT = re.compile(rf"(?<![\w-])(?:one|un|une)\s+(?={_DOSE_UNIT_WORDS}(?!\w))", re.IGNORECASE)


def ascii_digits(text: str) -> str:
    """Every Unicode decimal digit -> its ASCII digit. Length-preserving (one code point each)."""
    if text.isascii():
        return text
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() and not ch.isascii() else ch for ch in text)


def strip_format(text: str) -> str:
    """Remove format characters (Unicode category Cf: ZWSP, ZWJ/ZWNJ, direction marks, BOM, soft hyphen)."""
    if text.isascii():
        return text
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


_Part = tuple[int, str, str]  # (value, kind "small" | "hundred" | "thousand", lang)


def _compose(parts: list[_Part]) -> list[tuple[int, int, int]]:
    """Group a run of number words into numbers: (first part index, last part index, value). A word that
    cannot extend the current number ("two and three") starts a new one."""
    groups: list[tuple[int, int, int]] = []
    first, total, current, last_lang = 0, 0, -1, ""
    for i, (value, kind, lang) in enumerate(parts):
        if kind == "hundred":
            current = (current if current > 0 else 1) * 100
        elif kind == "thousand":
            total += (current if current > 0 else 1) * 1000 * value
            current = -1
        elif current < 0 and not total:
            first, current = i, value
        elif current >= 0 and _extends(current, value, lang, last_lang):
            current += value
        elif current < 0:
            current = value  # "two thousand five"
        else:
            groups.append((first, i - 1, total + current))
            first, total, current = i, 0, value
        last_lang = lang
    groups.append((first, len(parts) - 1, total + max(current, 0)))
    return groups


def _extends(current: int, value: int, lang: str, last_lang: str) -> bool:
    if current % 100 == 0 and value < 100:
        return True  # "two hundred fifty", "deux cent cinquante", "مائتين وخمسين"
    tens = current % 100
    if tens >= 20 and tens % 10 == 0 and value < 10:
        return True  # "twenty-five", "vingt et un"
    if lang == "fr" and tens in (60, 80) and 10 <= value < 20:
        return True  # "soixante-dix", "quatre-vingt-quinze"
    if lang == "ar" and last_lang == "ar" and current < 10:
        return value == 10 or (value >= 20 and value % 10 == 0)  # "خمسة عشر", "خمسة وعشرون"
    return False


def _part_of(word: str) -> _Part:
    low = word.casefold()
    if low in _HUNDRED:
        return 100, "hundred", "en"
    if low in _THOUSAND:
        return _THOUSAND[low], "thousand", "en"
    value, lang = _WORD_VALUE[low]
    return value, "small", lang


def _run_to_digits(m: re.Match[str]) -> str:
    raw = m.group(0)
    spans = [p.span(1) for p in _RUN_PART.finditer(raw)]
    words = [raw[a:b] for a, b in spans]
    if len(words) == 1 and words[0].casefold() in _ONE:
        return raw  # a lone "one" / "un" / "واحد" is an article or a pronoun (handled next to units only)
    out = [raw[: spans[0][0]]]
    for n, (first, _last, value) in enumerate(_compose([_part_of(w) for w in words])):
        if n:
            out.append(raw[spans[first - 1][1] : spans[first][0]])  # keep "and" / "et" / "و" between numbers
        out.append(str(value))
    return "".join(out)


def _number_words(text: str) -> str:
    text = _PER_CENT.sub("%", text)
    text = _AR_DUAL_RE.sub(lambda m: "2 " + _AR_DUAL[m.group(1)], text)
    text = _AR_ONE_AFTER.sub(r"1 \1", text)
    text = _ONE_AND_A_HALF.sub("1.5", text)
    text = _RUN.sub(_run_to_digits, text)
    text = _AND_A_HALF.sub(lambda m: f"{m.group(1)}.5", text)
    text = _ONE_BEFORE_UNIT.sub("1 ", text)
    text = _HALF_A.sub("0.5 ", text)
    text = _AR_HALF.sub("0.5", text)
    return _TWICE.sub(lambda m: "2 times" if m.group(1).casefold() == "twice" else "3 times", text)


def normalise_numbers(text: str) -> str:
    """Matching copy with ASCII digits, plain separators and number words as digits (see module doc)."""
    t = unicodedata.normalize("NFKC", text)
    t = strip_format(t)
    t = ascii_digits(t).replace(_AR_DECIMAL, ".").replace(_AR_THOUSANDS, ",").replace("⁄", "/")
    t = _number_words(t)
    return _FRACTION.sub(lambda m: _fraction(int(m.group(1)), int(m.group(2))), t)


def _fraction(num: int, den: int) -> str:
    value = num / den
    return f"{value:.3f}".rstrip("0").rstrip(".") if num < den else f"{num}/{den}"
