"""Shared fixtures for the engine / API tests.

No autouse fixtures here: the guardrails and llm tests are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from core.config import REPO_ROOT, Settings

TEST_CANARY = "AUSC-0123456789abcdef"
TEST_SECRET = "test-session-secret-0123456789abcdef-0123456789"  # secret-scan: allow
DEMO_PROFILE = REPO_ROOT / "config" / "hospital" / "demo.yaml"
TODAY = date(2026, 12, 1)  # inside the demo profile's validity window


def make_settings(data_root: Path, **env: Any) -> Settings:
    """Settings that ignore the developer's .env file (tests must never use the real key or database)."""
    values: dict[str, Any] = {
        "AUSCULTA_LLM_BACKEND": "fake",
        "AUSCULTA_ENV": "test",
        "AUSCULTA_DATA_ROOT": str(data_root),
        "DATABASE_URL": f"sqlite+aiosqlite:///{(data_root / 'test.db').as_posix()}",
        "REDIS_URL": None,
        "AUSCULTA_SESSION_SECRET": TEST_SECRET,
        "AUSCULTA_HOSPITAL_PROFILE": str(DEMO_PROFILE),
        "GEMINI_API_KEY": None,
    }
    values.update(env)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture(scope="session")
def engine_config() -> Any:
    from app.pipeline.factory import load_engine_config

    return load_engine_config(DEMO_PROFILE, canary=TEST_CANARY)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    def factory(**env: Any) -> Settings:
        return make_settings(tmp_path, **env)

    return factory


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def canary() -> str:
    return TEST_CANARY
