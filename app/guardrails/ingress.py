"""Ingress: the first thing that touches a user message. Sanitise, cap, redact. Never logs raw text."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from app.guardrails.pii import redact
from core.errors import InvalidInput
from core.text import sanitize

# sanitize() flags that indicate deliberate character smuggling (weights used by the injection detector).
SMUGGLING_FLAG_WEIGHTS: Mapping[str, float] = {
    "tag_chars": 0.9,
    "vs_supplement": 0.9,
    "private_use": 0.6,
    "bidi_override": 0.3,  # can come from legitimate RTL editors, so weak on its own
}
_RAW_LIMIT_FACTOR = 4  # reject absurdly large inputs before doing any work on them


@dataclass(frozen=True)
class IngressResult:
    text: str  # sanitised, capped and redacted: the ONLY form used downstream (model, logs, history)
    redactions: Mapping[str, int]
    sanitize_flags: frozenset[str]
    removed_chars: int
    truncated: bool

    @property
    def redaction_total(self) -> int:
        return sum(self.redactions.values())

    @property
    def smuggling_flags(self) -> frozenset[str]:
        return frozenset(f for f in self.sanitize_flags if f in SMUGGLING_FLAG_WEIGHTS)


def process_ingress(raw: object, *, max_chars: int, today: date | None = None) -> IngressResult:
    """Validate and clean one user message. Raises InvalidInput for non-text, empty or oversized input."""
    if not isinstance(raw, str):
        raise InvalidInput("message must be text")
    if len(raw) > max_chars * _RAW_LIMIT_FACTOR:
        raise InvalidInput("message too long", detail={"max_chars": max_chars})
    cleaned = sanitize(raw, max_chars=max_chars)
    if not cleaned.text.strip():
        raise InvalidInput("message is empty")
    redacted = redact(cleaned.text, today=today)
    return IngressResult(
        text=redacted.text,
        redactions=redacted.counts,
        sanitize_flags=cleaned.flags,
        removed_chars=cleaned.removed,
        truncated="truncated" in cleaned.flags,
    )
