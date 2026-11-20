"""Settings read from real environment variables (the path production uses)."""

from core.config import Settings


def test_allowed_origins_from_a_comma_separated_env_var(monkeypatch):
    # Regression: a tuple field was JSON-decoded from the environment, so "http://localhost" crashed startup.
    monkeypatch.setenv("AUSCULTA_ALLOWED_ORIGINS", "http://localhost, https://ausculta.example.org")
    assert Settings().allowed_origins == ("http://localhost", "https://ausculta.example.org")


def test_single_origin_from_env(monkeypatch):
    monkeypatch.setenv("AUSCULTA_ALLOWED_ORIGINS", "http://localhost")
    assert Settings().allowed_origins == ("http://localhost",)
