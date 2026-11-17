"""Request-scoped helpers: the container, the client IP behind trusted proxies, bearer-token sessions."""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request

from app.api.container import Container
from app.pipeline.session import SessionState
from core.errors import KillSwitchActive, SpendCapReached, Unauthorized

UNKNOWN_IP = "0.0.0.0"  # noqa: S104 - a label for "no client address", never bound
KILL_SWITCH_RETRY_S = 300.0


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request, trusted_proxies: int) -> str:
    """The caller's address. With N trusted proxies in front, X-Forwarded-For's N-th entry from the right is
    the one our outermost proxy appended; anything further left was supplied by the client and is ignored."""
    peer = request.client.host if request.client else UNKNOWN_IP
    if trusted_proxies <= 0:
        return peer
    header = ",".join(request.headers.getlist("x-forwarded-for"))
    hops = [h for h in (p.strip() for p in header.split(",")) if h]
    if len(hops) < trusted_proxies:
        return peer
    return _valid_ip(hops[-trusted_proxies]) or peer


def bearer_token(request: Request) -> str:
    """The bearer token; anything that is not plain ASCII is a 401, never a 500 (review P10/S9)."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or not token.isascii():
        raise Unauthorized("missing or malformed bearer token")
    return token


@dataclass(frozen=True)
class Authed:
    session: SessionState
    ip: str


async def load_session(c: Container, session_id: str) -> SessionState:
    """The stored session state; 401 when it expired or was forgotten."""
    state = await c.sessions.get(session_id)
    if state is None:
        raise Unauthorized("session expired")
    return state


async def authenticate(request: Request, c: Container) -> Authed:
    """Verify the token, rate-limit by IP and session, and load the session state (401 when gone)."""
    claims = c.signer.verify(bearer_token(request))
    ip = client_ip(request, c.settings.trusted_proxy_count)
    await c.rate.check_ip(ip)
    await c.rate.check_session(claims.session_id)
    return Authed(session=await load_session(c, claims.session_id), ip=ip)


def seconds_to_utc_midnight(now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return float(max(1, math.ceil((tomorrow - now).total_seconds())))


def ensure_not_paused(c: Container) -> None:
    """Kill switch (env flag or KILL_SWITCH file): every chat turn gets 503 + Retry-After."""
    if c.kill_switch.active():
        raise KillSwitchActive("paused by operator", detail={"retry_after_s": KILL_SWITCH_RETRY_S})


async def ensure_spend_available(c: Container) -> None:
    """Daily spend cap: model-backed turns get 503 + Retry-After (until 00:00 UTC)."""
    if await c.spend.spent_today() >= c.settings.daily_spend_cap_usd:
        raise SpendCapReached("daily spend cap reached", detail={"retry_after_s": seconds_to_utc_midnight()})
