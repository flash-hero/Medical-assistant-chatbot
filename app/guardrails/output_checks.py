"""Deterministic per-sentence checks on model output (run inline while streaming and again before release).

Per sentence, in order:
  0. output hygiene: invisible / smuggling characters removed (Unicode tags, zero-width, bidi controls,
     variation selectors: the ingress sanitiser) and fullwidth ASCII folded, so nothing hidden or disguised
     reaches the user and the checks below see what the reader sees                    (red team P5)
  1. canary-token leak and system-prompt echo (word 8-gram overlap)           -> fatal: answer withdrawn
     The canary is matched on an alphanumeric squeeze (spaced, dotted, fullwidth, Arabic-Indic digits), also
     reversed or base64-encoded; both checks also run over the tail of the text released before the
     sentence (RELEASED_TAIL_CHARS), so a canary or a prompt cut into short sentences is caught too
     (red team P5).
  2. markup removal: URLs, e-mail addresses, markdown links/images, HTML, code -> sentence kept, text modified
  3. phone numbers not in HospitalProfile.allowed_numbers()                     -> number removed
     (also short numbers after a call verb or near an emergency word: app/guardrails/scrub.py)
  4. citation markers that do not reference a provided passage                 -> marker removed
  5. numeric grounding: number+unit / % must appear in a cited passage         -> sentence dropped
  6. forbidden claims (diagnosis, personal dosing, stopping treatment, triage) -> sentence dropped
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from app.guardrails.claims import find_forbidden_claims
from app.guardrails.numeric import UNPARSED, ungrounded_quantities
from app.guardrails.scrub import strip_domains, strip_phones
from app.guardrails.sentences import Sentence, split_sentences
from core.text import detection_form, sanitize

NGRAM = 8
MIN_SHARED_NGRAMS = 2
# Released text re-checked with each new sentence: longer than any obfuscated canary (spaced / zero-width:
# ~45 characters) and than two 8-gram windows of prompt words.
RELEASED_TAIL_CHARS = 200
_MD_IMAGE = re.compile(r"!\[[^\]]{0,300}\]\([^)]{0,800}\)")
_MD_LINK = re.compile(r"\[([^\]\d][^\]]{0,300})\]\([^)]{0,800}\)")
_HTML = re.compile(r"</?[a-zA-Z][^<>]{0,300}>|<!--.*?-->", re.DOTALL)
# scheme URLs and www., plus script-capable schemes even without "//" (red team P5: javascript:, data:)
_URL = re.compile(r"\b(?:https?://|ftp://|www\.)\S+|\b(?:javascript|vbscript|data|file):\S+", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CODE = re.compile(r"`+")
_MARKER_LIST = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)+)\]")
_MARKER = re.compile(r"\[(\d+)\]")
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?؟])")
_FULLWIDTH = {**{cp: cp - 0xFEE0 for cp in range(0xFF01, 0xFF5F)}, 0x3000: 0x20}
_SQUEEZE = re.compile(r"[^0-9a-z]")
_BASE64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


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


def clean_output(text: str) -> str:
    """Model text as it may reach the user: the ingress sanitiser (no tag / zero-width / bidi / variation-
    selector characters) plus fullwidth ASCII folded to ASCII."""
    return sanitize(text.translate(_FULLWIDTH)).text


def ngrams(text: str, n: int = NGRAM, *, form: str | None = None) -> frozenset[tuple[str, ...]]:
    """Word n-grams of the detection form; citation markers dropped, underscores split ("a_b" -> "a b").
    `form`: the text's _match_form when the caller already has it."""
    toks = (form if form is not None else _match_form(text)).replace("_", " ").split()
    return frozenset(tuple(toks[i : i + n]) for i in range(len(toks) - n + 1))


def _match_form(text: str) -> str:
    return detection_form(_without_markers(text))


def _without_markers(text: str) -> str:
    return _MARKER_LIST.sub(" ", _MARKER.sub(" ", text))


def policy_ngrams(system_prompt: str, canary: str) -> frozenset[tuple[str, ...]]:
    return ngrams(system_prompt.replace(canary, " "))


def _base64_decoded(text: str) -> Iterator[str]:
    for token in _BASE64.findall(text):
        try:
            yield base64.b64decode(token + "=" * (-len(token) % 4)).decode("latin-1")
        except (binascii.Error, ValueError):
            continue


def canary_in(text: str, canary: str, *, form: str | None = None) -> bool:
    """The canary's random part, also spaced / dotted / fullwidth / with Arabic-Indic digits (the squeeze),
    reversed, or base64-encoded (the "encode your instructions" attack)."""
    secret = _SQUEEZE.sub("", canary.split("-")[-1].casefold())
    if not secret:
        return False
    flat = _SQUEEZE.sub("", form if form is not None else _match_form(text))
    if secret in flat or secret[::-1] in flat:
        return True
    return any(secret in _SQUEEZE.sub("", d.casefold()) for d in _base64_decoded(text))


def _leak(text: str, ctx: CheckContext) -> str | None:
    form = _match_form(text)  # one normalisation for both checks
    if ctx.canary and canary_in(text, ctx.canary, form=form):
        return "canary_leak"
    if ctx.policy_ngrams and len(ngrams(text, form=form) & ctx.policy_ngrams) >= MIN_SHARED_NGRAMS:
        return "system_prompt_echo"
    return None


def strip_markup(text: str) -> str:
    out = _MD_IMAGE.sub("", text)
    out = _MD_LINK.sub(r"\1", out)
    out = _HTML.sub("", out)
    out = _URL.sub("", out)
    out = _EMAIL.sub("", out)
    out = strip_domains(out)
    return _CODE.sub("", out)


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


def check_sentence(sentence: str, ctx: CheckContext, *, released: str = "") -> SentenceCheck:
    """`released`: the answer text already released before this sentence. The leak checks also cover its
    tail, so a canary or a prompt run cut across sentences is caught at constant cost per sentence."""
    text = clean_output(sentence)
    leak = _leak(f"{released[-RELEASED_TAIL_CHARS:]} {text}" if released else text, ctx)
    if leak:
        return SentenceCheck("", kept=False, modified=True, fatal=True, violations=(leak,), citations=())
    cleaned = strip_phones(strip_markup(text), ctx.allowed_numbers)
    cleaned, cited = _fix_markers(cleaned, len(ctx.passages))
    cleaned = _tidy(cleaned)
    violations: list[str] = []
    if cleaned != sentence.strip():
        violations.append("markup_or_number_removed")
    sources = [ctx.passages[i - 1] for i in cited] if cited else list(ctx.passages)
    ungrounded = ungrounded_quantities(cleaned, sources)
    if any(q.unit != UNPARSED for q in ungrounded):
        violations.append("numeric_ungrounded")
    if any(q.unit == UNPARSED for q in ungrounded):
        violations.append("numeric_unparsed")
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
    checked: list[tuple[Sentence, SentenceCheck]] = []
    released = ""
    for s in sentences:
        c = check_sentence(s.text, ctx, released=released)
        checked.append((s, c))
        released = f"{released} {clean_output(s.text)}".strip()
    return AnswerCheck(sentences=tuple(checked), fatal=any(c.fatal for _, c in checked))


def check_answer(text: str, ctx: CheckContext) -> AnswerCheck:
    return check_sentences(split_sentences(text), ctx)
