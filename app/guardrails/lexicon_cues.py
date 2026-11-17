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

# ---- historical scope (review C1) --------------------------------------------------------------------------
# A historical cue ("was diagnosed with", "last year") covers the sub-clause that holds it. Sub-clauses start
# at "while" / "mais" / "بينما"..., and at "and" / "et" / "و" when a new clause follows (a subject pronoun, an
# auxiliary or a time word: "and is having a seizure", "et il convulse", "وهو الآن"). Plain "and" between
# nouns ("a history of epilepsy and seizures") does not split. All forms are the normalised plain form.
_EN_CLAUSE_START = (
    r"i|im|ive|id|he|hes|she|shes|it|its|they|theyre|we|you|my|his|her|our|their|is|are|am|was|were|has|have|"
    r"had|can|cant|cannot|couldnt|wont|doesnt|dont|isnt|arent|keeps|now|still|suddenly|then|today|tonight|"
    r"currently"
)
_FR_CLAUSE_START = (
    r"il|elle|je|j|on|ils|elles|mon|ma|mes|son|sa|ses|est|a|ai|n|ne|maintenant|soudain|aujourd|depuis"
)
_AR_CLAUSE_START = (
    r"هو|هي|انا|هوا|هيا|راه|راها|راهو|راني|راهي|ما|لا|دابا|الان|حاليا|درك|توا|اليوم|مازال|مازالت|لازال"
)
_AZI_CLAUSE_START = r"howa|hiya|ana|rah|raha|rani|daba|db|tawa|drk|ma|mazal|lyoum"
_SCOPE_BREAK = re.compile(
    rf"(?<!\w)(?:(?:and|w|o)\s+(?=(?:{_EN_CLAUSE_START}|{_AZI_CLAUSE_START})(?!\w))"
    rf"|et\s+(?=(?:{_FR_CLAUSE_START})(?!\w))|و\s*(?=(?:{_AR_CLAUSE_START})(?!\w))"
    r"|(?:while|whereas|although|though|alors que|tandis que|pendant que|mais|بينما|في حين|لكن|ولكن)(?!\w))"
)
# Present progressive ("is having", "am bleeding", "is not breathing") overrides a historical cue in the same
# sub-clause; recovery / routine verbs ("is recovering from a stroke she had last year") do not.
_BENIGN_ING = (
    r"recovering|healing|doing|getting|improving|taking|feeling|managing|living|coping|waiting|asking|"
    r"wondering|looking|trying|planning|going|thinking|hoping|reading|writing|studying|working|visiting|"
    r"caring|staying|resting|eating|using|following|seeing|attending|receiving|undergoing|preparing|telling|"
    r"saying|talking|worrying|being|monitoring|treating|checking|booking|coming|nothing|something|anything|"
    r"everything|morning|evening|during|thing|bring|king|ring|spring|sibling|string|ceiling|wedding|building|"
    r"ongoing"
)
_EN_PROGRESSIVE = re.compile(
    rf"(?<!\w)(?:am|is|are|im|hes|shes|theyre|youre)\s+(?:(?:still|now|currently|just|really|suddenly|not)\s+)?"
    rf"(?!(?:{_BENIGN_ING})(?!\w))\w{{2,}}ing(?!\w)"
)
# Past-tense markers: a sub-clause WITHOUT its own historical cue continues the historical one when it is in
# the past ("I had a seizure and was diagnosed with epilepsy last year"). Arabic has no reliable marker here,
# so Arabic sub-clauses without their own cue are judged as present (the safe side).
_PAST = re.compile(
    r"(?<!\w)(?:was|were|had|did|got|went|fell|broke|took|became|came|felt|lost|passed|left|gave|bled|"
    r"\w{3,}ed|avait|avaient|avais|etait|etaient|etais|\w{3,}aient|\w{3,}ait|"
    r"(?:a|ai|as|avons|avez|ont) (?:eu|ete|fait|subi)|(?:est|suis|sont) (?:tombee?s?|nee?|allee?|evanouie?))"
    r"(?!\w)"
)


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
    present: re.Pattern[str] | None = None  # present-time cues ("right now", "en ce moment", "الآن", "راه")

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

    def is_present(self, text: str) -> bool:
        """A present-time cue or an English present progressive ("is having a seizure")."""
        return bool((self.present and self.present.search(text)) or _EN_PROGRESSIVE.search(text))

    def historical_at(self, clause: str, hit_start: int) -> bool:
        """Is the hit at `hit_start` about the past? Call only for a clause with a historical cue.

        The cue covers its own sub-clause; a present-time cue in the hit's sub-clause overrides it; a
        sub-clause without a cue is historical only when it is itself in the past tense (review C1)."""
        segment, whole = _segment_at(clause, hit_start)
        if self.is_present(segment):
            return False
        return whole or self.is_historical(segment) or bool(_PAST.search(segment))

    def is_informational(self, clause: str, hit_start: int) -> bool:
        """A general question about the hit: an informational cue BEFORE it, or a French inversion anywhere
        ("une surdose abîme-t-elle le foie"), and no personal reference in the clause."""
        cue_before = self.informational is not None and self.informational.search(clause[:hit_start])
        if not (cue_before or _FR_INVERSION.search(clause)):
            return False
        # The question words themselves ("ما هي" = "what is") and French inversion ("abîme-t-elle") are not
        # personal references, so they are blanked before looking for one.
        rest = self.informational.sub(" ", clause) if self.informational is not None else clause
        rest = _FR_INVERSION.sub(" ", rest)
        return not (self.personal and self.personal.search(rest))


def _segment_at(clause: str, pos: int) -> tuple[str, bool]:
    """The sub-clause of `clause` that holds offset `pos`, and whether it is the whole clause."""
    starts = [m.start() for m in _SCOPE_BREAK.finditer(clause) if m.start() > 0]
    if not starts:
        return clause, True
    begin = max((s for s in starts if s <= pos), default=0)
    end = min((s for s in starts if s > pos), default=len(clause))
    return clause[begin:end], False


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
        present=_present_regex(_escaped(norm(_lang_lists(raw, "present")))),
    )


def _present_regex(items: list[str]) -> re.Pattern[str] | None:
    """Present-time cues, also with the Arabic conjunction glued on ("والان")."""
    if not items:
        return None
    return re.compile(r"(?<!\w)و?(?:" + "|".join(sorted(set(items), key=len, reverse=True)) + r")(?!\w)")


def _regex_or_none(items: list[str]) -> re.Pattern[str] | None:
    items = [i for i in items if i]
    if not items:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(sorted(set(items), key=len, reverse=True)) + r")(?!\w)")


def plain_form(text: str) -> str:
    return normalize(text)


def skeleton_form(text: str) -> str:
    return arabizi_skeleton(normalize(text))
