"""Deterministic, model-free signals the engine adds on top of the guard verdict (fail-safe direction only).

  mentions_population(text)  a pregnancy / breastfeeding / child / older-adult mention (EN, FR, AR, Darija)
                             forces verify-then-release, whatever the classifier said (review C6)
  fallback_language(...)     when the classifier is down, Latin text without clear English cues is answered
                             in the UI locale rather than in English (review C14)

Both run on core.text.detection_form (casefolded, Latin accents stripped, Arabic letters folded, punctuation
removed), so "Bébé", "bebe" and "BEBE" are the same token and "nouveau-né" reads "nouveau ne".
"""

from __future__ import annotations

import re

from core.schemas.chat import Locale
from core.text import detection_form

_POPULATION_LATIN = re.compile(
    r"\b(?:"
    # pregnancy / breastfeeding
    r"pregnan\w*|expecting a baby|breast ?feed\w*|nursing|lactat\w*|"
    r"enceinte\w*|grossesse\w*|allait\w*|hamla|hamel|"
    # children
    r"bab(?:y|ies)|infants?|newborns?|toddlers?|child\w*|kids?|my (?:son|daughter)|"
    r"bebes?|nourrissons?|nouveau nes?|enfants?|mon fils|ma fille|drari|"
    r"\d{1,3} ?(?:years?|yrs?|months?|weeks?) ?old|\d{1,3} (?:ans|mois)|"
    # older adults
    r"elderly|older (?:adult|people|person|patient)s?|seniors?|grand ?(?:mother|father|ma|pa)|"
    r"personnes? agees?|ages|grand ?(?:mere|pere)"
    r")\b"
)
# Arabic stems (no \b: clitics such as و/ب/ل/ال attach to the front of the word).
_POPULATION_ARABIC = re.compile(r"حامل|الحمل|حملي|رضيع|رضع|رضاعه|مرضع|طفل|اطفال|مسن|كبار السن|كبير في السن")
# Clear English function words; FR-only spellings ("me", "a" from "à") are left out on purpose.
_ENGLISH_CUES = re.compile(
    r"\b(?:the|is|are|was|what|how|why|when|which|who|i|my|you|your|it|its|of|and|to|for|with|can|could|"
    r"does|should|have|has|this|that|about|from)\b"
)
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")


def mentions_population(text: str) -> bool:
    form = detection_form(text)
    return bool(_POPULATION_LATIN.search(form) or _POPULATION_ARABIC.search(form))


def fallback_language(language: Locale, text: str, hint: Locale) -> Locale:
    """The answer language when no classifier judged it: keep a confident guess, else trust the UI locale."""
    if language != "en" or hint == "en" or _ARABIC_LETTER.search(text):
        return language
    return "en" if _ENGLISH_CUES.search(detection_form(text)) else hint
