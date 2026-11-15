"""Map Gemini SDK / transport exceptions to core.errors.Upstream* (the only errors the provider raises)."""

from __future__ import annotations

import re
from typing import Any

from core.errors import (
    AusculaError,
    UpstreamBadRequest,
    UpstreamBlocked,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamTimeout,
    UpstreamUnavailable,
)

_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s")
_PER_DAY = re.compile(
    r"per\s*day|per_day|PerDay|requests_per_day|_free_tier_requests.*limit: 0", re.IGNORECASE
)
_PER_MIN = re.compile(r"per\s*minute|per_minute|PerMinute", re.IGNORECASE)
BLOCK_CODES = frozenset({"safety", "prohibited_content", "blocklist", "jailbreak", "spii", "content_blocked"})
BLOCK_FINISH = frozenset({"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "RECITATION"})


def _status_of(exc: BaseException) -> int | None:
    for attr in ("code", "status_code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    return None


def _text_of(exc: BaseException) -> str:
    parts = [str(exc)]
    for attr in ("details", "body", "message"):
        val: Any = getattr(exc, attr, None)
        if val:
            parts.append(str(val))
    return " ".join(parts)


def classify_rate_limit(text: str) -> tuple[str, float | None]:
    """Return (scope, retry_after_s) for a 429 body. A 'limit: 0' quota means the model is not available on
    this tier at all, which behaves like a daily exhaustion (do not retry)."""
    match = _RETRY_DELAY.search(text)
    retry_after = float(match.group(1)) if match else None
    if "limit: 0" in text or _PER_DAY.search(text):
        return "day", retry_after
    if _PER_MIN.search(text):
        return "minute", retry_after
    return "unknown", retry_after


def map_exception(exc: BaseException) -> AusculaError:
    """Translate any exception raised by an SDK call into a core.errors.Upstream* error."""
    if isinstance(exc, AusculaError):
        return exc
    name = type(exc).__name__
    if "Timeout" in name or isinstance(exc, TimeoutError):
        return UpstreamTimeout(f"upstream timeout ({name})")
    if any(k in name for k in ("ConnectError", "NetworkError", "RemoteProtocolError", "ReadError")):
        return UpstreamUnavailable(f"upstream connection error ({name})")
    status = _status_of(exc)
    text = _text_of(exc)
    if status == 429:
        scope, retry_after = classify_rate_limit(text)
        return UpstreamRateLimited("upstream rate limited", scope=scope, retry_after_s=retry_after)  # type: ignore[arg-type]
    if status == 400:
        lowered = text.lower()
        code = next((c for c in BLOCK_CODES if f"'{c}'" in lowered or f'"{c}"' in lowered), None)
        if code:
            return UpstreamBlocked("upstream blocked the input", reason=code, stage="prompt")
        return UpstreamBadRequest(f"upstream rejected the request ({status})")
    if status in (401, 403, 404):
        return UpstreamBadRequest(f"upstream refused the request ({status})")
    if status is not None and (status >= 500 or status in (408, 409)):
        return UpstreamUnavailable(f"upstream server error ({status})")
    return UpstreamError(f"unexpected upstream error ({name})")


def is_retryable(err: AusculaError) -> bool:
    if isinstance(err, UpstreamRateLimited):
        return err.scope == "minute" or (err.scope == "unknown" and (err.retry_after_s or 0) <= 8)
    return isinstance(err, (UpstreamTimeout, UpstreamUnavailable))
