"""Runtime settings, read from environment / .env. Secrets are SecretStr and never logged."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    # Gemini
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_tier: Literal["free", "paid"] = Field(default="free", alias="GEMINI_TIER")
    llm_backend: Literal["gemini", "fake"] = Field(default="gemini", alias="AUSCULTA_LLM_BACKEND")
    embed_backend: Literal["local", "gemini", "fake"] = Field(default="local", alias="AUSCULTA_EMBED_BACKEND")
    embed_threads: int | None = Field(default=None, alias="AUSCULTA_EMBED_THREADS", ge=1, le=64)
    # Fake LLM/embedding backends are refused in staging/prod unless explicitly allowed (CI smoke stack only).
    allow_fake: bool = Field(default=False, alias="AUSCULTA_ALLOW_FAKE")

    # Runtime
    env: Literal["dev", "test", "staging", "prod"] = Field(default="dev", alias="AUSCULTA_ENV")
    demo_mode: bool = Field(default=True, alias="AUSCULTA_DEMO_MODE")
    data_root: Path = Field(default=Path("C:/dev/ausculta-data"), alias="AUSCULTA_DATA_ROOT")
    session_secret: SecretStr | None = Field(default=None, alias="AUSCULTA_SESSION_SECRET")
    hospital_profile_path: Path = Field(
        default=REPO_ROOT / "config" / "hospital" / "demo.yaml", alias="AUSCULTA_HOSPITAL_PROFILE"
    )
    allowed_origins: tuple[str, ...] = Field(
        default=("http://localhost:3000", "http://127.0.0.1:3000"), alias="AUSCULTA_ALLOWED_ORIGINS"
    )
    trusted_proxy_count: int = Field(default=0, alias="AUSCULTA_TRUSTED_PROXY_COUNT", ge=0, le=3)

    # Services
    qdrant_url: str = Field(default="http://127.0.0.1:6333", alias="QDRANT_URL")
    qdrant_api_key: SecretStr | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_alias: str = Field(default="ausculta_corpus", alias="QDRANT_ALIAS")
    database_url: str = Field(
        default="sqlite+aiosqlite:///C:/dev/ausculta-data/ausculta.db", alias="DATABASE_URL"
    )
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    # Limits and spend
    daily_spend_cap_usd: float = Field(default=5.0, alias="AUSCULTA_DAILY_SPEND_CAP_USD", ge=0)
    kill_switch: bool = Field(default=False, alias="AUSCULTA_KILL_SWITCH")
    max_message_chars: int = Field(default=2000, alias="AUSCULTA_MAX_MESSAGE_CHARS", ge=100, le=8000)
    max_turns_per_session: int = Field(default=20, alias="AUSCULTA_MAX_TURNS", ge=1, le=100)
    history_window_turns: int = Field(default=3, alias="AUSCULTA_HISTORY_WINDOW", ge=0, le=20)
    llm_concurrency: int = Field(default=8, alias="AUSCULTA_LLM_CONCURRENCY", ge=1, le=256)
    queue_max: int = Field(default=32, alias="AUSCULTA_QUEUE_MAX", ge=0, le=4096)
    queue_wait_s: float = Field(default=5.0, alias="AUSCULTA_QUEUE_WAIT_S", ge=0, le=60)
    rate_per_ip_per_min: int = Field(default=20, alias="AUSCULTA_RATE_IP_MIN", ge=1)
    rate_per_session_per_min: int = Field(default=10, alias="AUSCULTA_RATE_SESSION_MIN", ge=1)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return tuple(o.strip() for o in v.split(",") if o.strip())
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        """Refuse configurations that are unsafe outside dev/test (review P11/S14)."""
        if self.env not in ("staging", "prod"):
            return self
        problems = []
        if "fake" in (self.llm_backend, self.embed_backend) and not self.allow_fake:
            problems.append("fake LLM/embedding backend (set AUSCULTA_ALLOW_FAKE=1 only for CI smoke stacks)")
        if not self.redis_url:
            problems.append("REDIS_URL is required (limits, sessions and spend are shared across workers)")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL must not be SQLite")
        if self.session_secret is None or len(self.session_secret.get_secret_value()) < 32:
            problems.append("AUSCULTA_SESSION_SECRET must be set (>= 32 characters)")
        if problems:
            raise ValueError(f"unsafe {self.env} configuration: " + "; ".join(problems))
        return self

    @property
    def models_dir(self) -> Path:
        """Local model weights (embedding model), outside the repo."""
        return self.data_root / "models"

    @property
    def is_free_tier(self) -> bool:
        return self.gemini_tier == "free"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
