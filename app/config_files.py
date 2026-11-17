"""Read-only access to the YAML / text files under config/ (UTF-8, validated by each consumer)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from core.config import REPO_ROOT

CONFIG_ROOT = REPO_ROOT / "config"
LOCALES: tuple[str, ...] = ("en", "fr", "ar")


class ConfigFileError(ValueError):
    """A config file is missing or malformed. Raised at startup, never during a turn."""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigFileError(f"cannot read config file {path.name}: {exc.strerror}") from exc


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(read_text(path))
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"invalid YAML in {path.name}") from exc
    if not isinstance(data, dict):
        raise ConfigFileError(f"{path.name} must contain a mapping at the top level")
    return data


def localized(value: Mapping[str, str] | None, locale: str) -> str:
    """Pick the string for `locale` from an {en, fr, ar} mapping, falling back to English."""
    if not value:
        return ""
    return str(value.get(locale) or value.get("en") or "")


def require_locales(value: object, where: str) -> dict[str, str]:
    """Validate an {en, fr, ar} mapping of non-empty strings."""
    if not isinstance(value, Mapping):
        raise ConfigFileError(f"{where}: expected a mapping of locales")
    missing = [loc for loc in LOCALES if not isinstance(value.get(loc), str) or not value.get(loc)]
    if missing:
        raise ConfigFileError(f"{where}: missing locales {missing}")
    return {loc: str(value[loc]) for loc in LOCALES}
