"""Deterministic multilingual risk lexicon (emergency, self-harm, harm to others, abuse disclosure).

No model dependency: this is what lets the emergency template return in < 300 ms when every model call fails.
Matching runs on normalised clauses (core.text.detection_form):
  1. exact, word-bounded matches of every term (one regex per risk kind); Arabic-script terms also match with
     an attached proclitic (و ف ب ل ك: "بنوبة قلبية" matches "نوبة قلبية"),
  2. Arabizi entries also on a consonant skeleton (3/7/9 digits, vowels and digraphs folded),
  3. token-level fuzzy matches for multi-word terms (misspellings), only for kinds without an exact hit.
Every hit is judged on the plain clause for negation ("no chest pain"), historical context ("diagnosed last
month", per kind) and, for condition names, purely informational questions ("what are the signs of a stroke?").
Per-kind idioms ("dying to know") are blanked out before matching. The lexicon files are marked
`draft-unreviewed` until a clinician signs them off.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from app.config_files import CONFIG_ROOT, ConfigFileError, load_yaml
from app.guardrails.lexicon_cues import CueSet, build_cue_set, plain_form, skeleton_form
from app.guardrails.lexicon_text import split_clauses
from core.schemas.chat import RiskKind, Signal

LEXICON_DIR = CONFIG_ROOT / "safety" / "lexicons"
LEXICON_KINDS: tuple[RiskKind, ...] = (
    RiskKind.EMERGENCY,
    RiskKind.SELF_HARM,
    RiskKind.HARM_TO_OTHERS,
    RiskKind.ABUSE_DISCLOSURE,
)
TERM_LANGS: tuple[str, ...] = ("en", "fr", "ar", "arabizi")
_PREFILTER_SCORE = 75.0
_MIN_SKELETON_CHARS = 6
_AR_PROCLITIC = "(?P<pre>[وفبلك]{1,2})?"
_TOKEN = re.compile(r"\S+")
HitStatus = Literal["active", "negated", "historical", "informational"]


@dataclass(frozen=True)
class LexiconSettings:
    fuzzy_min_term_chars: int = 8


@dataclass(frozen=True)
class _Entry:
    kind: RiskKind
    lang: str
    key: str  # normalised (plain) or skeleton form
    condition: bool
    form: Literal["plain", "skeleton"]


@dataclass(frozen=True)
class LexiconHit:
    kind: RiskKind
    lang: str
    score: float
    fuzzy: bool
    status: HitStatus
    condition: bool

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True)
class _Clause:
    plain: str
    skeleton: str
    skeleton_offsets: tuple[int, ...]  # plain-text offset of the token behind each skeleton token


@dataclass(frozen=True)
class KindRules:
    """Per-kind matching rules from the lexicon file."""

    suppress_historical: bool = True  # abuse disclosed "last week" must still trigger; old diagnoses must not
    exclusions: re.Pattern[str] | None = None  # idioms masked before matching ("dying to know")


@dataclass(frozen=True)
class _KindIndex:
    regex: Mapping[str, re.Pattern[str] | None]  # form -> alternation regex
    by_key: Mapping[tuple[str, str], tuple[_Entry, ...]]  # (form, key) -> entries
    fuzzy: tuple[_Entry, ...] = field(default=())
    rules: KindRules = field(default_factory=KindRules)


def _alternation(keys: Iterable[str], *, proclitics: bool) -> re.Pattern[str] | None:
    items = sorted({k for k in keys if k}, key=len, reverse=True)
    if not items:
        return None
    pre = _AR_PROCLITIC if proclitics else ""
    return re.compile(r"(?<!\w)" + pre + "(?P<t>" + "|".join(re.escape(k) for k in items) + r")(?!\w)")


def _make_clause(plain: str) -> _Clause:
    """Build the skeleton token by token so every skeleton match maps back to a plain-text offset."""
    pieces: list[str] = []
    offsets: list[int] = []
    for tok in _TOKEN.finditer(plain):
        for piece in skeleton_form(tok.group(0)).split():
            pieces.append(piece)
            offsets.append(tok.start())
    return _Clause(plain=plain, skeleton=" ".join(pieces), skeleton_offsets=tuple(offsets))


def _plain_offset(clause: _Clause, skeleton_start: int) -> int:
    index = clause.skeleton[:skeleton_start].count(" ")
    return clause.skeleton_offsets[index] if index < len(clause.skeleton_offsets) else len(clause.plain)


def _token_close(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) <= 4 or len(b) <= 4:
        return False
    limit = 2 if len(a) >= 9 else 1
    return Levenshtein.distance(a, b, score_cutoff=limit) <= limit


class LexiconMatcher:
    def __init__(
        self,
        entries: Sequence[_Entry],
        cues: CueSet,
        settings: LexiconSettings,
        *,
        version: str = "draft-unreviewed",
        rules: Mapping[RiskKind, KindRules] | None = None,
    ) -> None:
        self._cues = cues
        self._settings = settings
        self.version = version
        rules = rules or {}
        self._index = {
            kind: self._build_index(kind, entries, rules.get(kind, KindRules())) for kind in LEXICON_KINDS
        }

    def _build_index(self, kind: RiskKind, entries: Sequence[_Entry], rules: KindRules) -> _KindIndex:
        mine = [e for e in entries if e.kind is kind]
        by_key: dict[tuple[str, str], list[_Entry]] = {}
        for e in mine:
            by_key.setdefault((e.form, e.key), []).append(e)
        fuzzy = tuple(
            e
            for e in mine
            if e.form == "plain" and " " in e.key and len(e.key) >= self._settings.fuzzy_min_term_chars
        )
        regex = {
            form: _alternation((k for (f, k) in by_key if f == form), proclitics=form == "plain")
            for form in ("plain", "skeleton")
        }
        return _KindIndex(regex=regex, by_key={k: tuple(v) for k, v in by_key.items()}, fuzzy=fuzzy, rules=rules)

    @property
    def term_count(self) -> int:
        return sum(len(v) for idx in self._index.values() for v in idx.by_key.values())

    # ---- scanning ------------------------------------------------------------------------------
    def _clauses(self, text: str) -> list[_Clause]:
        return [_make_clause(part) for raw in split_clauses(text) for part in self._cues.split(plain_form(raw))]

    def scan(self, text: str) -> tuple[LexiconHit, ...]:
        """All hits, including suppressed ones (status != "active"), for every lexicon kind."""
        clauses = self._clauses(text)
        hits: list[LexiconHit] = []
        for idx in self._index.values():
            kind_clauses = _masked(clauses, idx.rules.exclusions)
            kind_hits = self._exact_hits(idx, kind_clauses)
            if not any(h.active for h in kind_hits):
                kind_hits += self._fuzzy_hits(idx, kind_clauses)
            hits.extend(kind_hits)
        return tuple(hits)

    def _exact_hits(self, idx: _KindIndex, clauses: list[_Clause]) -> list[LexiconHit]:
        hits: list[LexiconHit] = []
        for clause in clauses:
            for form, pattern in idx.regex.items():
                if pattern is None:
                    continue
                text = clause.plain if form == "plain" else clause.skeleton
                for m in pattern.finditer(text):
                    if form == "plain" and m.group("pre") and not _is_arabic(m.group("t")):
                        continue
                    start = m.start("t") if form == "plain" else _plain_offset(clause, m.start("t"))
                    for entry in idx.by_key[(form, m.group("t"))]:
                        hits.append(self._judge(entry, idx.rules, clause.plain, start, score=1.0, fuzzy=False))
        return hits

    def _fuzzy_hits(self, idx: _KindIndex, clauses: list[_Clause]) -> list[LexiconHit]:
        """One rapidfuzz alignment per entry over the whole message (bounded cost for long input), then a
        token-level check inside the clause that contains the best alignment."""
        if not idx.fuzzy or not clauses:
            return []
        joined = "\n".join(c.plain for c in clauses)
        bounds: list[int] = []
        pos = 0
        for c in clauses:
            bounds.append(pos)
            pos += len(c.plain) + 1
        hits: list[LexiconHit] = []
        for entry in idx.fuzzy:
            rough = fuzz.partial_ratio_alignment(entry.key, joined, score_cutoff=_PREFILTER_SCORE)
            if rough is None:
                continue
            ci = max(i for i, b in enumerate(bounds) if b <= rough.dest_start)
            clause = clauses[ci].plain
            start = _fuzzy_start(entry.key, clause, max(0, rough.dest_start - bounds[ci]))
            if start is None:
                continue
            hit = self._judge(entry, idx.rules, clause, start, score=0.9, fuzzy=True)
            hits.append(hit)
            if hit.active:
                break
        return hits

    def _judge(
        self, entry: _Entry, rules: KindRules, clause: str, start: int, *, score: float, fuzzy: bool
    ) -> LexiconHit:
        status: HitStatus = "active"
        if self._cues.is_negated(clause[:start].split(), entry.lang):
            status = "negated"
        elif rules.suppress_historical and self._cues.is_historical(clause):
            status = "historical"
        elif entry.condition and self._cues.is_informational(clause, start):
            status = "informational"
        return LexiconHit(entry.kind, entry.lang, score, fuzzy, status, entry.condition)

    def signals(self, text: str) -> tuple[Signal, ...]:
        """One Signal(source="lexicon") per risk kind with at least one active hit. No user text in `detail`."""
        best: dict[RiskKind, LexiconHit] = {}
        for hit in self.scan(text):
            if hit.active and (hit.kind not in best or hit.score > best[hit.kind].score):
                best[hit.kind] = hit
        return tuple(
            Signal(
                kind=h.kind,
                source="lexicon",
                score=h.score,
                detail=f"{h.lang}:{'fuzzy' if h.fuzzy else 'exact'}",
            )
            for h in best.values()
        )

    def hit_languages(self, text: str) -> frozenset[str]:
        return frozenset(h.lang for h in self.scan(text) if h.active)


def _is_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def _masked(clauses: list[_Clause], exclusions: re.Pattern[str] | None) -> list[_Clause]:
    """Blank out idioms ("dying to know") in the plain form, keeping offsets; the skeleton is rebuilt."""
    if exclusions is None:
        return clauses
    out: list[_Clause] = []
    for c in clauses:
        plain = exclusions.sub(lambda m: " " * len(m.group(0)), c.plain)
        out.append(c if plain == c.plain else _make_clause(plain))
    return out


def _fuzzy_start(key: str, clause: str, approx_start: int) -> int | None:
    """Character offset in `clause` of a token-level fuzzy match of `key` near `approx_start`, or None.
    Short tokens must match exactly ("dye" != "die"); longer ones tolerate one or two edits."""
    words = clause.split()
    key_tokens = key.split()
    first = len(clause[:approx_start].split())
    for begin in (first - 1, first, first + 1):
        window = words[begin : begin + len(key_tokens)] if begin >= 0 else []
        if len(window) == len(key_tokens) and all(
            _token_close(a, b) for a, b in zip(key_tokens, window, strict=True)
        ):
            return _offset_of_word(clause, begin)
    return None


def _offset_of_word(clause: str, index: int) -> int:
    for i, m in enumerate(_TOKEN.finditer(clause)):
        if i == index:
            return m.start()
    return len(clause)


# ---- loading ------------------------------------------------------------------------------------
def _kind_of(data: Mapping[str, Any], path: Path) -> RiskKind:
    try:
        return RiskKind(data["kind"])
    except (KeyError, ValueError) as exc:
        raise ConfigFileError(f"{path.name}: missing or unknown 'kind'") from exc


def _rules_from_file(data: Mapping[str, Any], path: Path) -> KindRules:
    raw = data.get("exclusions") or []
    if not isinstance(raw, list):
        raise ConfigFileError(f"{path.name}: 'exclusions' must be a list")
    keys = sorted({plain_form(str(x)) for x in raw} - {""}, key=len, reverse=True)
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keys) + r")(?!\w)") if keys else None
    return KindRules(suppress_historical=bool(data.get("suppress_historical", True)), exclusions=pattern)


def _entries_from_file(data: Mapping[str, Any], path: Path) -> list[_Entry]:
    kind = _kind_of(data, path)
    entries: list[_Entry] = []
    for section, condition in (("terms", False), ("condition_terms", True)):
        langs = data.get(section) or {}
        if not isinstance(langs, Mapping):
            raise ConfigFileError(f"{path.name}: '{section}' must be a mapping of languages")
        for lang in TERM_LANGS:
            for term in langs.get(lang) or []:
                entries.extend(_entries_for_term(kind, lang, str(term), condition))
    return entries


def _entries_for_term(kind: RiskKind, lang: str, term: str, condition: bool) -> list[_Entry]:
    key = plain_form(term)
    if not key:
        return []
    out = [_Entry(kind, lang, key, condition, "plain")]
    if lang == "arabizi":
        skel = skeleton_form(term)
        if len(skel.replace(" ", "")) >= _MIN_SKELETON_CHARS:
            out.append(_Entry(kind, lang, skel, condition, "skeleton"))
    return out


def load_lexicon(directory: Path = LEXICON_DIR, settings: LexiconSettings | None = None) -> LexiconMatcher:
    """Load every risk lexicon plus context cues from config/safety/lexicons (fails fast on bad files)."""
    cues = build_cue_set(load_yaml(directory / "context_cues.yaml"), plain_form)
    entries: list[_Entry] = []
    versions: set[str] = set()
    rules: dict[RiskKind, KindRules] = {}
    for kind in LEXICON_KINDS:
        path = directory / f"{kind.value}.yaml"
        data = load_yaml(path)
        versions.add(str(data.get("version", "")))
        entries.extend(_entries_from_file(data, path))
        rules[_kind_of(data, path)] = _rules_from_file(data, path)
    version = "draft-unreviewed" if "draft-unreviewed" in versions else ",".join(sorted(versions))
    return LexiconMatcher(entries, cues, settings or LexiconSettings(), version=version, rules=rules)
