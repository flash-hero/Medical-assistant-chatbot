"""ASGI entry point.

  uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000

create_app(settings) wires the composition root (app/api/container.py), the routes under /api/v1, the JSON
error envelope, security headers, CORS for the configured origins only, and the request-body size limit.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import Scope

from app.api.container import Container, Overrides, build_container
from app.api.errors import envelope, install_error_handlers
from app.api.middleware import DEFAULT_MAX_BODY_BYTES, BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.api.routes_chat import router as chat_router
from app.api.routes_forms import router as forms_router
from app.api.routes_ops import router as ops_router
from app.pipeline.factory import app_version
from app.pipeline.texts import Texts
from core.config import Settings, get_settings

API_PREFIX = "/api/v1"


def configure_logging(settings: Settings) -> None:
    """Structured logs to stderr: JSON outside dev/test. Events carry ids and codes, never message text."""
    level = logging.DEBUG if settings.env == "dev" else logging.INFO
    renderer: structlog.typing.Processor = (
        structlog.dev.ConsoleRenderer(colors=False)
        if settings.env in ("dev", "test")
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def _too_large(container: Container) -> object:
    def reject(scope: Scope) -> Response:
        return envelope(container.texts, "payload_too_large", 413, "en")

    return reject


def create_app(settings: Settings | None = None, *, overrides: Overrides | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    container = build_container(settings, overrides)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await container.startup()
        try:
            yield
        finally:
            await container.shutdown()

    public_docs = settings.env in ("dev", "test")
    app = FastAPI(
        title="Ausculta API",
        version=app_version(),
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs" if public_docs else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json" if public_docs else None,
    )
    app.state.container = container
    install_error_handlers(app, _texts)
    for router in (chat_router, forms_router, ops_router):
        app.include_router(router, prefix=API_PREFIX)
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=DEFAULT_MAX_BODY_BYTES,
        reject=_too_large(container),  # type: ignore[arg-type]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Accept-Language"],
        allow_credentials=False,
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.env in ("staging", "prod"))
    return app


def _texts(request: Request) -> Texts:
    return request.app.state.container.texts  # type: ignore[no-any-return]
