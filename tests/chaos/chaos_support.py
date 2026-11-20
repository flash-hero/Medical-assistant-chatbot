"""Shared helpers of the chaos tests (imported by conftest.py and the test modules; conftest itself cannot be
imported by test modules)."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.api.container import Container
from core.config import REPO_ROOT, Settings
from core.schemas.events import ChatEvent
from evals.fakes.sse_contract import order_violations, parse_sse

DEMO_PROFILE = REPO_ROOT / "config" / "hospital" / "demo.yaml"
CANARY = "AUSC-00112233445566ff"
FEVER = "What is a fever and how long does it usually last?"
EMERGENCY = "I have crushing chest pain spreading to my left arm and I'm sweating"
SELF_HARM = "I want to kill myself"
VISITING = "What are the visiting hours?"


def chaos_settings(root: Path, **env: Any) -> Settings:
    values: dict[str, Any] = {
        "AUSCULTA_LLM_BACKEND": "fake",
        "AUSCULTA_EMBED_BACKEND": "fake",
        "AUSCULTA_ENV": "test",
        "AUSCULTA_DATA_ROOT": str(root),
        "DATABASE_URL": f"sqlite+aiosqlite:///{(root / 'chaos.db').as_posix()}",
        "REDIS_URL": None,
        "AUSCULTA_SESSION_SECRET": secrets.token_urlsafe(48),
        "AUSCULTA_HOSPITAL_PROFILE": str(DEMO_PROFILE),
        "GEMINI_API_KEY": None,
        "AUSCULTA_RATE_IP_MIN": 100_000,
        "AUSCULTA_RATE_SESSION_MIN": 100_000,
    }
    values.update(env)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@dataclass
class Turn:
    response: httpx.Response
    events: list[ChatEvent]

    @property
    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def answer(self) -> Any:
        return next(e for e in self.events if e.type == "answer")

    def assert_contract(self) -> None:
        assert self.response.status_code == 200, self.response.text
        assert order_violations(self.events) == [], self.types


@dataclass
class ChaosApp:
    app: Any
    container: Container
    client: httpx.AsyncClient

    async def token(self, locale: str = "en") -> str:
        r = await self.client.post("/api/v1/session", json={"locale": locale})
        assert r.status_code == 201, r.text
        return str(r.json()["session_token"])

    async def chat(self, token: str, message: str, locale: str = "en") -> Turn:
        r = await self.client.post(
            "/api/v1/chat",
            json={"message": message, "locale": locale, "client_turn_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        return Turn(r, parse_sse(r.text) if r.status_code == 200 else [])
