"""Co-occurrence ("combination") entries of the risk lexicon.

A combination is a list of groups; a group lists alternatives; an alternative is one or more words matched as
consecutive tokens. The combination matches when every group matches a different token span, all within
MAX_SPAN tokens of each other, in any order. This generalises over word order and filler words ("my chest
feels heavy", "heavy pressure in the middle of my chest"), which literal phrases cannot.

Word syntax: a trailing "*" matches a prefix ("breath*" = breathe, breathing), a leading "*" a suffix
("*نزف" = ينزف, تنزف, كتنزف), both a substring. Arabic-script words also match a token carrying up to two
proclitics (و ف ب ل ك) and/or the article ("فصدري", "بالصدر"). Arabizi words are compared on the consonant
skeleton ("sadri" = "sdri" = "sedri").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.config_files import ConfigFileError
from app.guardrails.lexicon_text import arabizi_skeleton, normalize
from core.schemas.chat import RiskKind

MAX_SPAN = 12  # tokens from the first to the last matched word
COMBO_LANGS: tuple[str, ...] = ("en", "fr", "ar", "arabizi")
_PROCLITICS = frozenset("وفبلك")
_ARTICLE = "ال"
_MIN_STEM = 3  # a proclitic is only stripped when at least this many letters remain
_SHORT_STEMS = frozenset({"ما", "لا"})  # negation particles glued to و / ف: "وما بقاش كيجاوب", "ولا يتنفس"

Span = tuple[int, int]  # [start, end) token indices


def _is_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


@lru_cache(maxsize=16384)
def token_forms(token: str) -> tuple[str, ...]:
    """A token as written plus, for Arabic script, without 1-2 proclitics and without the article."""
    if not _is_arabic(token):
        return (token,)
    forms = [token]
    for n in (1, 2):
        stem = token[n:]
        if (len(stem) >= _MIN_STEM or stem in _SHORT_STEMS) and all(c in _PROCLITICS for c in token[:n]):
            forms.append(stem)
    forms += [f[len(_ARTICLE) :] for f in forms if f.startswith(_ARTICLE) and len(f) - 2 >= _MIN_STEM]
    return tuple(dict.fromkeys(forms))


@lru_cache(maxsize=16384)
def _skeleton(token: str) -> str:
    return arabizi_skeleton(token)


@dataclass(frozen=True)
class WordPattern:
    core: str
    prefix: bool = False  # "core*": the token starts with core
    suffix: bool = False  # "*core": the token ends with core
    skeleton: bool = False  # Arabizi: compare consonant skeletons

    @classmethod
    def parse(cls, word: str, lang: str) -> WordPattern:
        raw = word.strip()
        core = normalize(raw.strip("*"))
        if lang == "arabizi":
            core = _skeleton(core)
        if not core:
            raise ConfigFileError(f"combination word {word!r} is empty after normalisation")
        if " " in core:
            raise ConfigFileError(f"combination word {word!r} must be a single token")
        return cls(core, raw.endswith("*"), raw.startswith("*"), lang == "arabizi")

    def match_form(self, form: str) -> bool:
        if self.prefix and self.suffix:
            return self.core in form
        if self.prefix:
            return form.startswith(self.core)
        if self.suffix:
            return form.endswith(self.core)
        return form == self.core

    def matches(self, token: str) -> bool:
        forms = (_skeleton(token),) if self.skeleton else token_forms(token)
        return any(self.match_form(f) for f in forms)


Alternative = tuple[WordPattern, ...]
Group = tuple[Alternative, ...]


@dataclass(frozen=True)
class Combination:
    kind: RiskKind
    lang: str
    groups: tuple[Group, ...]


class TokenIndex:
    """The tokens of one message, with per-pattern positions memoised for the whole scan."""

    def __init__(self, tokens: tuple[str, ...]) -> None:
        self.tokens = tokens
        self._tables: dict[bool, dict[str, list[int]]] = {}
        self._memo: dict[WordPattern, tuple[int, ...]] = {}

    def _table(self, skeleton: bool) -> dict[str, list[int]]:
        if skeleton not in self._tables:
            table: dict[str, list[int]] = {}
            for i, tok in enumerate(self.tokens):
                for form in (_skeleton(tok),) if skeleton else token_forms(tok):
                    table.setdefault(form, []).append(i)
            self._tables[skeleton] = table
        return self._tables[skeleton]

    def positions(self, pattern: WordPattern) -> tuple[int, ...]:
        found = self._memo.get(pattern)
        if found is None:
            table = self._table(pattern.skeleton)
            if pattern.prefix or pattern.suffix:
                hits = {i for form, idx in table.items() if pattern.match_form(form) for i in idx}
            else:
                hits = set(table.get(pattern.core, ()))
            found = self._memo[pattern] = tuple(sorted(hits))
        return found


def _alternative_spans(alt: Alternative, index: TokenIndex) -> list[Span]:
    spans: list[Span] = []
    for start in index.positions(alt[0]):
        if all(start + k in index.positions(p) for k, p in enumerate(alt[1:], 1)):
            spans.append((start, start + len(alt)))
    return spans


def _overlaps(a: Span, b: Span) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _maximal(spans: set[Span]) -> list[Span]:
    """Drop spans contained in a longer span of the same group: "ما قادرش" wins over "قادرش", so a negation
    particle that belongs to the phrase is matched instead of being read as a negation before it."""
    return sorted(s for s in spans if not any(t != s and t[0] <= s[0] and s[1] <= t[1] for t in spans))


def _extent(spans: Sequence[Span]) -> int:
    return max(e for _, e in spans) - min(s for s, _ in spans)


def _fill(anchor: Span, others: Sequence[list[Span]]) -> list[Span] | None:
    """Greedily add, for every other group, its free span nearest to what is already chosen."""
    chosen = [anchor]
    for spans in others:
        free = [s for s in spans if not any(_overlaps(s, c) for c in chosen)]
        if not free:
            return None
        chosen.append(min(free, key=lambda s: min(abs(s[0] - c[0]) for c in chosen)))
    return chosen


def find(combo: Combination, index: TokenIndex, max_span: int = MAX_SPAN) -> tuple[int, ...] | None:
    """Token indices of the tightest match of `combo` (every word of every chosen alternative), or None."""
    per_group = [_maximal({s for alt in g for s in _alternative_spans(alt, index)}) for g in combo.groups]
    if not all(per_group):
        return None
    order = sorted(range(len(per_group)), key=lambda i: len(per_group[i]))
    others = [per_group[i] for i in order[1:]]
    best: list[Span] | None = None
    for anchor in per_group[order[0]]:
        chosen = _fill(anchor, others)
        if chosen and _extent(chosen) <= max_span and (best is None or _extent(chosen) < _extent(best)):
            best = chosen
    if best is None:
        return None
    return tuple(sorted(i for start, end in best for i in range(start, end)))


# ---- loading --------------------------------------------------------------------------------------------
def _parse_alternative(text: str, lang: str, where: str) -> Alternative:
    words: list[WordPattern] = []
    for raw in text.split():
        pieces = normalize(raw.strip("*")).split()
        if not pieces:
            raise ConfigFileError(f"{where}: combination word {raw!r} is empty after normalisation")
        for k, piece in enumerate(pieces):
            marked = ("*" if raw.startswith("*") and k == 0 else "") + piece
            marked += "*" if raw.endswith("*") and k == len(pieces) - 1 else ""
            words.append(WordPattern.parse(marked, lang))
    return tuple(words)


def _parse_group(raw: Any, lang: str, where: str) -> Group:
    if not isinstance(raw, list) or not raw or not all(isinstance(w, str) for w in raw):
        raise ConfigFileError(f"{where}: every combination group must be a list of words")
    return tuple(_parse_alternative(w, lang, where) for w in raw if w.strip())


def _parse_one(raw: Any, kind: RiskKind, lang: str, where: str) -> Combination:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ConfigFileError(f"{where}: a combination needs at least two groups")
    return Combination(kind, lang, tuple(_parse_group(g, lang, where) for g in raw))


def parse_combinations(raw: Any, kind: RiskKind, where: str) -> tuple[Combination, ...]:
    """Parse the `combinations` section of a lexicon file ({lang: [[group, group, ...], ...]})."""
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise ConfigFileError(f"{where}: 'combinations' must be a mapping of languages")
    combos: list[Combination] = []
    for lang, items in raw.items():
        if lang not in COMBO_LANGS:
            raise ConfigFileError(f"{where}: unknown language {lang!r} in 'combinations'")
        for item in items or []:
            combos.append(_parse_one(item, kind, str(lang), f"{where}:{lang}"))
    return tuple(combos)
