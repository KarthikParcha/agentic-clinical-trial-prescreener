"""Patient-domain schemas for synthetic trial pre-screening."""

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class MedicationStatus(str, Enum):
    CURRENT = "CURRENT"
    PREVIOUS = "PREVIOUS"
    DISCONTINUED = "DISCONTINUED"
    UNKNOWN = "UNKNOWN"


class MedicalConditionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"


class PregnancyStatus(str, Enum):
    PREGNANT = "PREGNANT"
    NOT_PREGNANT = "NOT_PREGNANT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class LabResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_name: str
    value: Decimal
    unit: str
    measured_date: date | None = None
    reference_range: str | None = None


class Medication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_name: str
    status: MedicationStatus
    start_date: date | None = None
    end_date: date | None = None
    dosage: str | None = None
    frequency: str | None = None

    @model_validator(mode="after")
    def validate_date_order(self) -> "Medication":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class MedicalCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition_name: str
    status: MedicalConditionStatus
    diagnosis_date: date | None = None
    resolved_date: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_date_order(self) -> "MedicalCondition":
        if (
            self.diagnosis_date
            and self.resolved_date
            and self.resolved_date < self.diagnosis_date
        ):
            raise ValueError("resolved_date cannot be before diagnosis_date")
        return self


class PatientProfile(BaseModel):
    """Validated synthetic patient data for Version 1 pre-screening."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str
    age: int
    sex: Sex
    country: str
    condition: str
    consent_for_demo: bool
    diagnosis_date: date | None = None
    diagnosis_duration_years: Decimal | None = None
    height: Decimal | None = None
    weight: Decimal | None = None
    bmi: Decimal | None = None
    laboratory_results: list[LabResult] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    medical_history: list[MedicalCondition] = Field(default_factory=list)
    pregnancy_status: PregnancyStatus | None = None
    currently_in_trial: bool | None = None

    @field_validator("patient_id", "country")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("age")
    @classmethod
    def validate_age(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, value: str) -> str:
        if value != "Type 2 Diabetes":
            raise ValueError("Version 1 supports only Type 2 Diabetes")
        return value

    @field_validator("consent_for_demo")
    @classmethod
    def validate_demo_consent(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("consent_for_demo must be true")
        return value
