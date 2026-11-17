"""HMAC-signed session tokens: base64url(payload) "." base64url(HMAC-SHA256(payload)).

The payload holds only the session id, expiry and a version; nothing personal. Lifetime 2 h.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.errors import Unauthorized

TOKEN_LIFETIME = timedelta(hours=2)
_VERSION = 1
_MAX_TOKEN_CHARS = 512


@dataclass(frozen=True)
class TokenClaims:
    session_id: str
    expires_at: datetime


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SessionTokenSigner:
    def __init__(self, secret: bytes, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must be at least 32 bytes")
        self._key = hashlib.sha256(b"ausculta-session-token" + secret).digest()
        self._clock = clock

    @staticmethod
    def random_secret() -> bytes:
        return secrets.token_bytes(32)

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest())

    def issue(self, session_id: str, expires_at: datetime) -> str:
        body = {"sid": session_id, "exp": int(expires_at.timestamp()), "v": _VERSION}
        payload = _b64(json.dumps(body, separators=(",", ":")).encode("utf-8"))
        return f"{payload}.{self._sign(payload)}"

    def verify(self, token: str) -> TokenClaims:
        if not token or len(token) > _MAX_TOKEN_CHARS or token.count(".") != 1:
            raise Unauthorized("malformed token")
        payload, signature = token.split(".")
        if not hmac.compare_digest(signature, self._sign(payload)):
            raise Unauthorized("bad signature")
        try:
            body = json.loads(_unb64(payload))
            sid, exp, version = str(body["sid"]), int(body["exp"]), int(body["v"])
        except (ValueError, KeyError, TypeError) as exc:
            raise Unauthorized("malformed token") from exc
        expires = datetime.fromtimestamp(exp, UTC)
        if version != _VERSION or expires <= self._clock():
            raise Unauthorized("token expired")
        return TokenClaims(session_id=sid, expires_at=expires)
