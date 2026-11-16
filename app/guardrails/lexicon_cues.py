"""Context cues for the lexicon matcher: negation, historical, informational and personal markers.

Negation is scoped by the language of the matched entry (Arabizi "ma"/"la" must not negate French "ma mère" or
"la poitrine"); the other cue families are shared across languages because users mix languages.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.config_files import ConfigFileError
from app.guardrails.lexicon_text import arabizi_skeleton, normalize

CUE_LANGS: tuple[str, ...] = ("en", "fr", "ar", "arabizi")
# Pronouns that start a new proposition: a negation before them does not negate what follows.
_SUBJECT_PRONOUNS = frozenset(
    {"i", "je", "j", "we", "nous", "انا", "ana", "he", "she", "il", "elle", "هو", "هي"}
)
Phrases = tuple[tuple[str, ...], ...]
_FR_INVERSION = re.compile(r"\b(?:t|est|peut|sont|faut|doit) (?:il|elle|ils|elles|on)\b")


def _phrase_regex(phrases: Iterable[str]) -> re.Pattern[str] | None:
    items = sorted({p for p in phrases if p}, key=len, reverse=True)
    if not items:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(items) + r")(?!\w)")


def _escaped(phrases: Iterable[str]) -> list[str]:
    return [re.escape(p) for p in phrases if p]


@dataclass(frozen=True)
class CueSet:
    """Cues in one normalised form (plain or Arabizi skeleton)."""

    negation: Mapping[str, Phrases]  # entry language -> negation phrases (as token tuples)
    negation_window: int
    historical: re.Pattern[str] | None
    informational: re.Pattern[str] | None
    personal: re.Pattern[str] | None
    clause_breaks: re.Pattern[str] | None
    darija_negation_affix: bool
    negation_exceptions: Mapping[str, Phrases] = field(default_factory=dict)

    def split(self, clause: str) -> list[str]:
        if self.clause_breaks is None:
            return [clause]
        parts = self.clause_breaks.split(clause)
        return [p.strip() for p in parts if p and p.strip()]

    def is_negated(self, before: list[str], lang: str = "en") -> bool:
        """True when a negation cue of `lang` ends within `negation_window` tokens before the hit, with no new
        subject pronoun in between ("I don't have chest pain" vs "no, I can't breathe")."""
        n = len(before)
        cues = self.negation.get(lang, ())
        exceptions = self.negation_exceptions.get(lang, ())
        for start in range(max(0, n - self.negation_window - 3), n):
            if _starts_with_any(before, start, exceptions):
                continue
            for cue in (*cues, *self._affix_cue(before[start], lang)):
                end = start + len(cue)
                if end > n or tuple(before[start:end]) != cue:
                    continue
                gap = before[end:]
                if len(gap) <= self.negation_window and not (set(gap) & _SUBJECT_PRONOUNS):
                    return True
        return False

    def is_negation_token(self, token: str, lang: str = "en") -> bool:
        """True when `token` alone is a negation cue of `lang` (single-word cues and the Darija circumfix)."""
        return (token,) in self.negation.get(lang, ()) or bool(self._affix_cue(token, lang))

    def _affix_cue(self, token: str, lang: str) -> Phrases:
        # Maghrebi negation circumfix: ما...ش (e.g. ماعنديش) on a single Arabic-script token.
        if not self.darija_negation_affix or lang != "ar":
            return ()
        if len(token) >= 4 and token.startswith("م") and token.endswith("ش"):
            return ((token,),)
        return ()

    def is_historical(self, clause: str) -> bool:
        return bool(self.historical and self.historical.search(clause))

    def is_informational(self, clause: str, hit_start: int) -> bool:
        if self.informational is None or not self.informational.search(clause[:hit_start]):
            return False
        # The question words themselves ("ما هي" = "what is") and French inversion ("abîme-t-elle") are not
        # personal references, so they are blanked before looking for one.
        rest = _FR_INVERSION.sub(" ", self.informational.sub(" ", clause))
        return not (self.personal and self.personal.search(rest))


def _starts_with_any(tokens: list[str], start: int, phrases: Phrases) -> bool:
    return any(tuple(tokens[start : start + len(p)]) == p for p in phrases)


def _section(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    section = raw.get(key) or {}
    if not isinstance(section, Mapping):
        raise ConfigFileError(f"context cues: '{key}' must be a mapping of languages")
    return section


def _lang_list(raw: Mapping[str, Any], key: str, lang: str) -> list[str]:
    items = _section(raw, key).get(lang) or []
    if not isinstance(items, list):
        raise ConfigFileError(f"context cues: '{key}.{lang}' must be a list")
    return [str(i) for i in items]


def _lang_lists(raw: Mapping[str, Any], key: str) -> list[str]:
    return [item for lang in CUE_LANGS for item in _lang_list(raw, key, lang)]


def _phrases(raw: Mapping[str, Any], key: str, form: Callable[[str], str]) -> dict[str, Phrases]:
    out: dict[str, Phrases] = {}
    for lang in CUE_LANGS:
        normed = [n for n in (form(i) for i in _lang_list(raw, key, lang)) if n]
        out[lang] = tuple(tuple(n.split()) for n in normed)
    return out


def build_cue_set(raw: Mapping[str, Any], form: Callable[[str], str], *, skeleton: bool = False) -> CueSet:
    def norm(items: list[str]) -> list[str]:
        return [n for n in (form(i) for i in items) if n]

    def regex_items(items: list[str]) -> list[str]:
        # Historical cues may contain simple regexes (\d); escape everything else after normalisation.
        return [i if "\\d" in i else re.escape(form(i)) for i in items if form(i) or "\\d" in i]

    return CueSet(
        negation=_phrases(raw, "negation", form),
        negation_window=int(raw.get("negation_window", 3)),
        historical=_regex_or_none(regex_items(_lang_lists(raw, "historical"))),
        informational=_phrase_regex(_escaped(norm(_lang_lists(raw, "informational")))),
        personal=_phrase_regex(_escaped(norm(_lang_lists(raw, "personal")))),
        clause_breaks=_phrase_regex(_escaped(norm(_lang_lists(raw, "clause_breaks")))),
        darija_negation_affix=not skeleton,
        negation_exceptions=_phrases(raw, "negation_exceptions", form),
    )


def _regex_or_none(items: list[str]) -> re.Pattern[str] | None:
    items = [i for i in items if i]
    if not items:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(sorted(set(items), key=len, reverse=True)) + r")(?!\w)")


def plain_form(text: str) -> str:
    return normalize(text)


def skeleton_form(text: str) -> str:
    return arabizi_skeleton(normalize(text))
