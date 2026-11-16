"""JSON error envelope and exception handlers.

Envelope: {"error": {"code": "<stable code>", "message": "<localised, user-safe>", "retry_after_s": <number|null>}}
429 and 503 also carry a Retry-After header (integer seconds). Internal details never reach the client.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.pipeline.texts import Texts
from core.errors import AusculaError

log = structlog.get_logger(__name__)
_LOCALES = ("en", "fr", "ar")


class TurnInProgress(AusculaError):
    """Another turn of the same session (or the same client_turn_id) is still running."""

    code, http_status = "turn_in_progress", 409


class PayloadTooLarge(AusculaError):
    code, http_status = "payload_too_large", 413


_HTTP_CODES = {400: "invalid_input", 401: "unauthorized", 404: "not_found", 405: "not_found", 413: "payload_too_large"}


def request_locale(request: Request) -> str:
    q = request.query_params.get("locale", "")
    if q in _LOCALES:
        return q
    header = request.headers.get("accept-language", "")[:2].lower()
    return header if header in _LOCALES else "en"


def envelope(
    texts: Texts, code: str, status: int, locale: str, retry_after_s: float | None = None
) -> JSONResponse:
    headers: dict[str, str] = {}
    if retry_after_s is not None and status in (429, 503):
        headers["Retry-After"] = str(max(1, math.ceil(retry_after_s)))
    body = {"error": {"code": code, "message": texts.error(code, locale), "retry_after_s": retry_after_s}}
    return JSONResponse(body, status_code=status, headers=headers)


def _retry_after(exc: AusculaError) -> float | None:
    value = exc.detail.get("retry_after_s")
    if isinstance(value, (int, float)):
        return float(value)
    return 30.0 if exc.http_status == 503 else None


def install_error_handlers(app: FastAPI, texts_of: Callable[[Request], Texts]) -> None:
    async def domain(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AusculaError)
        if exc.http_status >= 500:
            log.warning("request_failed", code=exc.code, path=request.url.path)
        return envelope(texts_of(request), exc.code, exc.http_status, request_locale(request), _retry_after(exc))

    async def validation(request: Request, exc: Exception) -> JSONResponse:
        return envelope(texts_of(request), "invalid_input", 422, request_locale(request))

    async def http(request: Request, exc: Exception) -> JSONResponse:
        status = getattr(exc, "status_code", 500)
        code = _HTTP_CODES.get(status, "invalid_input" if status < 500 else "internal_error")
        return envelope(texts_of(request), code, status, request_locale(request))

    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", error=type(exc).__name__, path=request.url.path)
        return envelope(texts_of(request), "internal_error", 500, request_locale(request))

    app.add_exception_handler(AusculaError, domain)
    app.add_exception_handler(RequestValidationError, validation)
    app.add_exception_handler(StarletteHTTPException, http)
    app.add_exception_handler(Exception, unexpected)
