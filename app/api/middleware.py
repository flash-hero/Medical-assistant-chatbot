"""Pure ASGI middleware (no BaseHTTPMiddleware: it would buffer SSE and hide client disconnects).

SecurityHeaders  adds hardening headers to every HTTP response (API responses are never cacheable).
BodySizeLimit    rejects request bodies above `max_bytes` with 413, using Content-Length when present and
                 counting streamed chunks otherwise.
"""

from __future__ import annotations

from collections.abc import Callable

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_BODY_BYTES = 32 * 1024
SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"),
)
HSTS = ("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self._headers = (*SECURITY_HEADERS, HSTS) if hsts else SECURITY_HEADERS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self._headers:
                    headers.setdefault(name, value)
                headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyTooLarge(HTTPException):
    """Raised from `receive`; FastAPI re-raises HTTPExceptions from body parsing, so the 413 envelope
    handler answers it."""

    def __init__(self) -> None:
        super().__init__(status_code=413)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int, reject: Callable[[Scope], Response]) -> None:
        self.app = app
        self._max = max_bytes
        self._reject = reject

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self._max):
            await self._reject(scope)(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max:
                    raise BodyTooLarge
            return message

        await self.app(scope, limited_receive, send)
