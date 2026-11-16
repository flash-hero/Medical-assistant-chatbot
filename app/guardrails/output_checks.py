"""Deterministic per-sentence checks on model output (run inline while streaming and again before release).

Per sentence, in order:
  1. canary-token leak and system-prompt echo (word 8-gram overlap)           -> fatal: answer withdrawn
  2. markup removal: URLs, e-mail addresses, markdown links/images, HTML, code -> sentence kept, text modified
  3. phone numbers not in HospitalProfile.allowed_numbers()                     -> number removed
  4. citation markers that do not reference a provided passage                 -> marker removed
  5. numeric grounding: number+unit / % must appear in a cited passage         -> sentence dropped
  6. forbidden claims (diagnosis, personal dosing, stopping treatment)         -> sentence dropped
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.guardrails.claims import find_forbidden_claims
from app.guardrails.numeric import ungrounded_quantities
from app.guardrails.pii import PHONE_PATTERNS
from app.guardrails.sentences import Sentence, split_sentences
from core.text import detection_form

NGRAM = 8
MIN_SHARED_NGRAMS = 2
_MD_IMAGE = re.compile(r"!\[[^\]]{0,300}\]\([^)]{0,800}\)")
_MD_LINK = re.compile(r"\[([^\]\d][^\]]{0,300})\]\([^)]{0,800}\)")
_HTML = re.compile(r"</?[a-zA-Z][^<>]{0,300}>|<!--.*?-->", re.DOTALL)
_URL = re.compile(r"\b(?:https?://|ftp://|www\.)\S+", re.IGNORECASE)
_DOMAIN = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|gov|edu|int|fr|ma|dz|tn|uk|io|info|health|example)\b(?:/\S*)?",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CODE = re.compile(r"`+")
_MARKER_LIST = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)+)\]")
_MARKER = re.compile(r"\[(\d+)\]")
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?؟])")


@dataclass(frozen=True)
class CheckContext:
    canary: str
    policy_ngrams: frozenset[tuple[str, ...]]
    allowed_numbers: frozenset[str]
    passages: tuple[str, ...]  # passage text, index = citation number - 1


@dataclass(frozen=True)
class SentenceCheck:
    text: str  # cleaned sentence ("" when dropped)
    kept: bool
    modified: bool
    fatal: bool
    violations: tuple[str, ...]
    citations: tuple[int, ...]


@dataclass(frozen=True)
class AnswerCheck:
    sentences: tuple[tuple[Sentence, SentenceCheck], ...]
    fatal: bool

    @property
    def text(self) -> str:
        kept = [Sentence(c.text, s.separator) for s, c in self.sentences if c.kept]
        return "".join(s.rendered for s in kept).strip()

    @property
    def changed(self) -> bool:
        return any(c.modified or not c.kept for _, c in self.sentences)

    @property
    def citations(self) -> tuple[int, ...]:
        seen: dict[int, None] = {}
        for _, c in self.sentences:
            if c.kept:
                seen.update(dict.fromkeys(c.citations))
        return tuple(seen)

    @property
    def violations(self) -> tuple[str, ...]:
        return tuple(v for _, c in self.sentences for v in c.violations)


def ngrams(text: str, n: int = NGRAM) -> frozenset[tuple[str, ...]]:
    toks = detection_form(text).split()
    return frozenset(tuple(toks[i : i + n]) for i in range(len(toks) - n + 1))


def policy_ngrams(system_prompt: str, canary: str) -> frozenset[tuple[str, ...]]:
    return ngrams(system_prompt.replace(canary, " "))


def _leak(sentence: str, ctx: CheckContext) -> str | None:
    lowered = sentence.casefold()
    if ctx.canary and (ctx.canary.casefold() in lowered or ctx.canary.split("-")[-1].casefold() in lowered):
        return "canary_leak"
    if ctx.policy_ngrams and len(ngrams(sentence) & ctx.policy_ngrams) >= MIN_SHARED_NGRAMS:
        return "system_prompt_echo"
    return None


def strip_markup(text: str) -> str:
    out = _MD_IMAGE.sub("", text)
    out = _MD_LINK.sub(r"\1", out)
    out = _HTML.sub("", out)
    out = _URL.sub("", out)
    out = _EMAIL.sub("", out)
    out = _DOMAIN.sub("", out)
    return _CODE.sub("", out)


def _strip_phones(text: str, allowed: frozenset[str]) -> str:
    def repl(m: re.Match[str]) -> str:
        return m.group(0) if re.sub(r"\D", "", m.group(0)) in allowed else ""

    for pattern in PHONE_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _fix_markers(text: str, n_passages: int) -> tuple[str, tuple[int, ...]]:
    text = _MARKER_LIST.sub(lambda m: "".join(f"[{x}]" for x in re.split(r"\s*[,;]\s*", m.group(1))), text)
    cited: list[int] = []

    def repl(m: re.Match[str]) -> str:
        n = int(m.group(1))
        if 1 <= n <= n_passages:
            cited.append(n)
            return m.group(0)
        return ""

    return _MARKER.sub(repl, text), tuple(dict.fromkeys(cited))


def _tidy(text: str) -> str:
    return _SPACE_BEFORE_PUNCT.sub(r"\1", _SPACES.sub(" ", text)).strip()


def check_sentence(sentence: str, ctx: CheckContext) -> SentenceCheck:
    leak = _leak(sentence, ctx)
    if leak:
        return SentenceCheck("", kept=False, modified=True, fatal=True, violations=(leak,), citations=())
    cleaned = _strip_phones(strip_markup(sentence), ctx.allowed_numbers)
    cleaned, cited = _fix_markers(cleaned, len(ctx.passages))
    cleaned = _tidy(cleaned)
    violations: list[str] = []
    if cleaned != sentence.strip():
        violations.append("markup_or_number_removed")
    sources = [ctx.passages[i - 1] for i in cited] if cited else list(ctx.passages)
    if ungrounded_quantities(cleaned, sources):
        violations.append("numeric_ungrounded")
    violations.extend(f"forbidden_{v.category}" for v in find_forbidden_claims(cleaned))
    drop = any(v.startswith(("numeric_", "forbidden_")) for v in violations) or not _has_words(cleaned)
    return SentenceCheck(
        text="" if drop else cleaned,
        kept=not drop,
        modified=bool(violations) or drop,
        fatal=False,
        violations=tuple(violations),
        citations=() if drop else cited,
    )


def _has_words(text: str) -> bool:
    return bool(re.sub(r"\[\d+\]|[\W_]", "", text))


def check_sentences(sentences: Sequence[Sentence], ctx: CheckContext) -> AnswerCheck:
    checked = tuple((s, check_sentence(s.text, ctx)) for s in sentences)
    return AnswerCheck(sentences=checked, fatal=any(c.fatal for _, c in checked))


def check_answer(text: str, ctx: CheckContext) -> AnswerCheck:
    return check_sentences(split_sentences(text), ctx)
