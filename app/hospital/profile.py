"""Load and validate the hospital profile. Receptionist features are disabled when it is missing, invalid or
expired; the engine then uses the generic "call your local emergency number" wording."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import structlog
from pydantic import ValidationError

from app.config_files import ConfigFileError, load_yaml
from core.schemas.hospital import HospitalProfile

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ProfileState:
    profile: HospitalProfile | None
    error: str | None = None

    def active(self, today: date) -> HospitalProfile | None:
        """The profile when valid on `today`, else None (expired profiles disable receptionist mode)."""
        if self.profile is None or not self.profile.is_valid_on(today):
            return None
        return self.profile

    @property
    def loaded(self) -> bool:
        return self.profile is not None


def load_profile(path: Path) -> ProfileState:
    try:
        profile = HospitalProfile.model_validate(load_yaml(path))
    except ConfigFileError as exc:
        log.error("hospital_profile_unreadable", file=path.name)
        return ProfileState(profile=None, error=str(exc))
    except ValidationError as exc:
        log.error("hospital_profile_invalid", file=path.name, errors=exc.error_count())
        return ProfileState(profile=None, error=f"invalid hospital profile ({exc.error_count()} errors)")
    log.info("hospital_profile_loaded", profile=profile.id, demo=profile.is_demo, expires=str(profile.expires_on))
    return ProfileState(profile=profile)
