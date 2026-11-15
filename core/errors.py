"""Error taxonomy. Every error carries a stable machine code; user-facing text is chosen by the API layer.

Retry policy (owned by the LLM wrapper, SDK retries disabled):
  retry with backoff+jitter: UpstreamTimeout, UpstreamUnavailable, UpstreamRateLimited(scope="minute")
  never retry:               UpstreamBlocked, UpstreamBadRequest, UpstreamRateLimited(scope="day")
"""

from __future__ import annotations

from typing import Literal


class AusculaError(Exception):
    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str = "", *, detail: dict[str, object] | None = None) -> None:
        super().__init__(message or self.code)
        self.detail: dict[str, object] = dict(detail or {})


# ---- client-side (4xx) -------------------------------------------------------------------------
class InvalidInput(AusculaError):
    code, http_status = "invalid_input", 422


class Unauthorized(AusculaError):
    code, http_status = "unauthorized", 401


class NotFound(AusculaError):
    code, http_status = "not_found", 404


class RateLimited(AusculaError):
    code, http_status = "rate_limited", 429

    def __init__(self, message: str = "", *, retry_after_s: float, scope: str) -> None:
        super().__init__(message, detail={"retry_after_s": retry_after_s, "scope": scope})
        self.retry_after_s = retry_after_s


class SessionExhausted(AusculaError):
    code, http_status = "session_exhausted", 429


# ---- server capacity (5xx) ---------------------------------------------------------------------
class Overloaded(AusculaError):
    """Admission control rejected the request (queue full / wait timeout). Maps to 503 + Retry-After."""

    code, http_status = "overloaded", 503

    def __init__(self, message: str = "", *, retry_after_s: float = 5.0) -> None:
        super().__init__(message, detail={"retry_after_s": retry_after_s})
        self.retry_after_s = retry_after_s


class KillSwitchActive(AusculaError):
    code, http_status = "service_paused", 503


class SpendCapReached(AusculaError):
    code, http_status = "service_paused", 503


class DependencyUnavailable(AusculaError):
    """A local dependency (Qdrant, DB, Redis) is down."""

    code, http_status = "dependency_unavailable", 503


# ---- upstream LLM ------------------------------------------------------------------------------
class UpstreamError(AusculaError):
    code, http_status = "upstream_error", 502


class UpstreamTimeout(UpstreamError):
    code = "upstream_timeout"


class UpstreamUnavailable(UpstreamError):
    code = "upstream_unavailable"


class UpstreamRateLimited(UpstreamError):
    code = "upstream_rate_limited"

    def __init__(
        self, message: str = "", *, scope: Literal["minute", "day", "unknown"], retry_after_s: float | None
    ) -> None:
        super().__init__(message, detail={"scope": scope, "retry_after_s": retry_after_s})
        self.scope = scope
        self.retry_after_s = retry_after_s


class UpstreamBlocked(UpstreamError):
    """The provider's safety system blocked the prompt or the response. Treated as a RISK SIGNAL."""

    code = "upstream_blocked"

    def __init__(self, message: str = "", *, reason: str, stage: Literal["prompt", "response"]) -> None:
        super().__init__(message, detail={"reason": reason, "stage": stage})
        self.reason = reason
        self.stage = stage


class UpstreamBadRequest(UpstreamError):
    code = "upstream_bad_request"


RETRYABLE: tuple[type[AusculaError], ...] = (UpstreamTimeout, UpstreamUnavailable)
