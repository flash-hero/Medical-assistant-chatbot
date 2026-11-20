"""JSON error envelope and exception handlers.

Envelope: {"error": {"code": "<stable code>", "message": "<localised, user-safe>",
           "retry_after_s": <number|null>}}
429 and 503 also carry a Retry-After header (integer seconds). Internal details never reach the client.
An outage of Redis, the rate-limit storage or the database is 503 dependency_unavailable, never a 500 (P16).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from limits.errors import StorageError
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.pipeline.texts import Texts
from core.errors import AusculaError
from core.schemas.hospital import HospitalProfile

log = structlog.get_logger(__name__)
_LOCALES = ("en", "fr", "ar")


class TurnInProgress(AusculaError):
    """Another turn of the same session (or the same client_turn_id) is still running."""

    code, http_status = "turn_in_progress", 409


class PayloadTooLarge(AusculaError):
    code, http_status = "payload_too_large", 413


_HTTP_CODES = {
    400: "invalid_input",
    401: "unauthorized",
    404: "not_found",
    405: "not_found",
    413: "payload_too_large",
}


def request_locale(request: Request) -> str:
    q = request.query_params.get("locale", "")
    if q in _LOCALES:
        return q
    header = request.headers.get("accept-language", "")[:2].lower()
    return header if header in _LOCALES else "en"


def envelope(
    texts: Texts,
    code: str,
    status: int,
    locale: str,
    retry_after_s: float | None = None,
    profile: HospitalProfile | None = None,
) -> JSONResponse:
    headers: dict[str, str] = {}
    if retry_after_s is not None and status in (429, 503):
        headers["Retry-After"] = str(max(1, math.ceil(retry_after_s)))
    message = texts.error(code, locale, profile)
    body = {"error": {"code": code, "message": message, "retry_after_s": retry_after_s}}
    return JSONResponse(body, status_code=status, headers=headers)


DEFAULT_RETRY_AFTER_S = {429: 60.0, 503: 30.0}


def _retry_after(exc: AusculaError) -> float | None:
    """Every 429 / 503 carries Retry-After (contract); other statuses never do."""
    value = exc.detail.get("retry_after_s")
    if isinstance(value, (int, float)) and exc.http_status in DEFAULT_RETRY_AFTER_S:
        return float(value)
    return DEFAULT_RETRY_AFTER_S.get(exc.http_status)


def _no_profile(_: Request) -> HospitalProfile | None:
    return None


def install_error_handlers(
    app: FastAPI,
    texts_of: Callable[[Request], Texts],
    profile_of: Callable[[Request], HospitalProfile | None] = _no_profile,
) -> None:
    """`profile_of` fills the emergency / crisis numbers of the 503 messages (P5-D8)."""

    def profile(request: Request) -> HospitalProfile | None:
        try:
            return profile_of(request)
        except Exception as exc:  # an error page must never fail on the profile
            log.warning("error_profile_unavailable", error=type(exc).__name__)
            return None

    async def domain(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AusculaError)
        if exc.http_status >= 500:
            log.warning("request_failed", code=exc.code, path=request.url.path)
        return envelope(
            texts_of(request),
            exc.code,
            exc.http_status,
            request_locale(request),
            _retry_after(exc),
            profile(request),
        )

    async def validation(request: Request, exc: Exception) -> JSONResponse:
        return envelope(texts_of(request), "invalid_input", 422, request_locale(request))

    async def http(request: Request, exc: Exception) -> JSONResponse:
        status = getattr(exc, "status_code", 500)
        code = _HTTP_CODES.get(status, "invalid_input" if status < 500 else "internal_error")
        return envelope(texts_of(request), code, status, request_locale(request))

    async def dependency(request: Request, exc: Exception) -> JSONResponse:
        log.warning("dependency_failed", error=type(exc).__name__, path=request.url.path)
        return envelope(
            texts_of(request),
            "dependency_unavailable",
            503,
            request_locale(request),
            DEFAULT_RETRY_AFTER_S[503],
            profile(request),
        )

    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", error=type(exc).__name__, path=request.url.path)
        return envelope(texts_of(request), "internal_error", 500, request_locale(request))

    app.add_exception_handler(AusculaError, domain)
    app.add_exception_handler(RequestValidationError, validation)
    app.add_exception_handler(StarletteHTTPException, http)
    for kind in (RedisError, StorageError, SQLAlchemyError):
        app.add_exception_handler(kind, dependency)
    app.add_exception_handler(Exception, unexpected)
