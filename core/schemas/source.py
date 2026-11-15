"""Source registry contract (data_pipeline/sources/registry.yaml).

A document may be indexed only if its source has status ACTIVE and a verified licence record
(evidence URL + verified_on date). CI enforces this via data_pipeline.registry.assert_indexable().
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class Language(StrEnum):
    EN = "en"
    FR = "fr"
    AR = "ar"
    ES = "es"


class ContentType(StrEnum):
    CONDITION = "condition"
    DRUG_LABEL = "drug_label"
    LAB_TEST = "lab_test"
    GUIDELINE = "guideline"
    FIRST_AID = "first_aid"
    FAQ = "faq"
    TEXTBOOK = "textbook"
    GENETICS = "genetics"
    VACCINE = "vaccine"
    WELLNESS = "wellness"
    HOSPITAL = "hospital"


class ReuseMode(StrEnum):
    PARAPHRASE_OK = "paraphrase_ok"  # model may summarise / translate, with attribution
    QUOTE_ONLY = "quote_only"  # substantive content must not be altered: quote + cite
    LINK_ONLY = "link_only"  # never indexed as text; may be offered as a link


class SourceStatus(StrEnum):
    ACTIVE = "active"  # licence verified; may be indexed
    HOLD = "hold"  # gathered but terms not yet verified; must not be indexed
    OPTIONAL_NONCOMMERCIAL = "optional_noncommercial"  # only in the non-commercial build profile
    EXCLUDED = "excluded"  # never fetched, never indexed


class CommercialUse(StrEnum):
    YES = "yes"
    NO = "no"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


class LicenseRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str  # e.g. "public-domain-us-gov", "CC0-1.0", "OGL-UK-3.0", "CC-BY-SA-4.0"
    name: str
    evidence_url: HttpUrl | None = None  # page where the terms were read
    commercial_use: CommercialUse = CommercialUse.UNKNOWN
    attribution: str = ""  # exact credit line shown in citations / attribution page
    conditions: tuple[str, ...] = ()  # e.g. "do not imply endorsement", "refresh every 7 days"
    verified_on: date | None = None
    verified_by: str | None = None


class AccessSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str  # "bulk" | "api" | "crawl"
    endpoints: tuple[str, ...] = ()
    rate_limit_per_min: int | None = None
    notes: str = ""


class SourceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{1,63}$")
    name: str
    publisher: str
    homepage: HttpUrl
    status: SourceStatus
    wave: int = Field(ge=0, le=3)  # 0 = excluded list
    trust_tier: int = Field(ge=1, le=3)
    reuse_mode: ReuseMode
    languages: tuple[Language, ...]
    content_types: tuple[ContentType, ...]
    license: LicenseRecord
    access: AccessSpec | None = None
    refresh_days: int | None = Field(default=None, ge=1)
    domains: tuple[str, ...] = ()  # hostnames belonging to this source (used by the exclusion check)
    notes: str = ""

    @model_validator(mode="after")
    def _active_requires_verified_licence(self) -> SourceRecord:
        if self.status is SourceStatus.ACTIVE:
            lic = self.license
            missing = [
                name
                for name, val in (
                    ("license.evidence_url", lic.evidence_url),
                    ("license.verified_on", lic.verified_on),
                    ("license.verified_by", lic.verified_by),
                )
                if not val
            ]
            if missing:
                raise ValueError(f"source {self.id!r} is ACTIVE but lacks {', '.join(missing)}")
            if lic.commercial_use in (CommercialUse.NO, CommercialUse.UNKNOWN):
                raise ValueError(f"source {self.id!r} is ACTIVE but commercial_use={lic.commercial_use}")
            if self.reuse_mode is ReuseMode.LINK_ONLY:
                raise ValueError(f"source {self.id!r} is ACTIVE with reuse_mode=link_only (cannot index)")
        return self

    @property
    def indexable(self) -> bool:
        return self.status is SourceStatus.ACTIVE
