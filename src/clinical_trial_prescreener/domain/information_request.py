"""Structured requests for missing synthetic patient information."""

from pydantic import BaseModel, ConfigDict, field_validator

from clinical_trial_prescreener.domain.criterion import TemporalWindow


class InformationRequest(BaseModel):
    """One deterministic question required to re-evaluate a criterion."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    patient_field: str
    question: str
    reason: str
    temporal_context: TemporalWindow | None = None
    required: bool = True

    @field_validator("criterion_id", "patient_field", "question", "reason")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class InformationAnswer(BaseModel):
    """One bounded answer to an InformationRequest; None preserves missingness."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    patient_field: str
    value: bool | None = None
    temporal_context: TemporalWindow | None = None

    @field_validator("criterion_id", "patient_field")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value
