"""GET /api/v1/hospital, /health, /ready and /meta."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import get_container
from app.api.errors import request_locale
from app.api.schemas import MetaInfo
from app.hospital.public import public_hospital
from core.errors import NotFound

router = APIRouter()
READY_RETRY_AFTER_S = 10.0
REQUIRED_CHECKS = ("database", "sessions", "rate_limiter", "retriever")


@router.get("/hospital")
async def hospital(request: Request) -> dict[str, object]:
    c = get_container(request)
    profile = c.profile()
    if profile is None:
        raise NotFound("no verified hospital profile is loaded")
    return public_hospital(profile, request_locale(request))


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process answers. No dependency is checked."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: database, session store, rate limiter and the vector store must answer."""
    c = get_container(request)
    checks = await c.ready_checks()
    paused = c.kill_switch.active()
    if all(checks[name] for name in REQUIRED_CHECKS):
        return JSONResponse({"status": "ready", "checks": checks, "paused": paused})
    error = {
        "code": "dependency_unavailable",
        "message": c.texts.error("dependency_unavailable", request_locale(request)),
        "retry_after_s": READY_RETRY_AFTER_S,
    }
    return JSONResponse(
        {"error": error, "checks": checks, "paused": paused},
        status_code=503,
        headers={"Retry-After": str(int(READY_RETRY_AFTER_S))},
    )


@router.get("/meta")
async def meta(request: Request) -> MetaInfo:
    c = get_container(request)
    release = c.release()
    return MetaInfo(
        app_version=release.app_version,
        corpus_version=release.corpus_version,
        prompt_hash=release.prompt_hash,
        models=dict(release.models),
        demo_mode=c.settings.demo_mode,
    )
