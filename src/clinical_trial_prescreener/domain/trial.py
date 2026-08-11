"""Normalized clinical-trial domain schemas."""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TrialStatus(str, Enum):
    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    RECRUITING = "RECRUITING"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    UNKNOWN = "UNKNOWN"


class StudyType(str, Enum):
    INTERVENTIONAL = "INTERVENTIONAL"
    OBSERVATIONAL = "OBSERVATIONAL"
    EXPANDED_ACCESS = "EXPANDED_ACCESS"


class TrialSex(str, Enum):
    ALL = "ALL"
    FEMALE = "FEMALE"
    MALE = "MALE"


class Intervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    name: str
    description: str | None = None
    other_names: list[str] = Field(default_factory=list)


class TrialLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility: str | None = None
    status: str | None = None
    city: str | None = None
    state: str | None = None
    country: str
    postal_code: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ClinicalTrial(BaseModel):
    """Internal normalized representation of a clinical trial."""

    model_config = ConfigDict(extra="forbid")

    trial_id: str
    title: str
    official_title: str | None = None
    status: TrialStatus
    study_type: StudyType
    phases: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)
    minimum_age_years: int | None = None
    maximum_age_years: int | None = None
    sex: TrialSex | None = None
    eligibility_text: str | None = None
    locations: list[TrialLocation] = Field(default_factory=list)

    @field_validator("trial_id", "title")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("minimum_age_years", "maximum_age_years")
    @classmethod
    def validate_non_negative_age(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("must not be negative")
        return value

    @model_validator(mode="after")
    def validate_age_range(self) -> "ClinicalTrial":
        if (
            self.minimum_age_years is not None
            and self.maximum_age_years is not None
            and self.maximum_age_years < self.minimum_age_years
        ):
            raise ValueError("maximum_age_years cannot be lower than minimum_age_years")
        return self
