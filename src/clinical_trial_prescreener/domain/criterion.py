"""Eligibility-criterion domain schemas."""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CriterionType(str, Enum):
    INCLUSION = "INCLUSION"
    EXCLUSION = "EXCLUSION"


class EvaluationType(str, Enum):
    NUMERIC = "NUMERIC"
    BOOLEAN = "BOOLEAN"
    CATEGORICAL = "CATEGORICAL"
    TEMPORAL = "TEMPORAL"
    SEMANTIC = "SEMANTIC"
    COMPOUND = "COMPOUND"
    HUMAN_ONLY = "HUMAN_ONLY"


class CriterionCategory(str, Enum):
    AGE = "AGE"
    SEX = "SEX"
    DIAGNOSIS = "DIAGNOSIS"
    LAB = "LAB"
    BMI = "BMI"
    MEDICATION = "MEDICATION"
    MEDICAL_HISTORY = "MEDICAL_HISTORY"
    PREGNANCY = "PREGNANCY"
    PROCEDURE = "PROCEDURE"
    LIFESTYLE = "LIFESTYLE"
    LOCATION = "LOCATION"
    CONSENT = "CONSENT"
    OTHER = "OTHER"


class ComparisonOperator(str, Enum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    BETWEEN = "BETWEEN"
    BETWEEN_INCLUSIVE = "BETWEEN_INCLUSIVE"
    IN = "IN"
    NOT_IN = "NOT_IN"
    EXISTS = "EXISTS"
    NOT_EXISTS = "NOT_EXISTS"


class LogicalOperator(str, Enum):
    AND = "AND"
    OR = "OR"


class TemporalUnit(str, Enum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    YEAR = "YEAR"


class TemporalWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Decimal
    unit: TemporalUnit


class EligibilityCriterion(BaseModel):
    """Structured trial criterion before patient-specific evaluation."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    criterion_type: CriterionType
    category: CriterionCategory
    original_text: str
    evaluation_type: EvaluationType
    field_name: str | None = None
    operator: ComparisonOperator | None = None
    value: Decimal | bool | str | list[str] | None = None
    lower_value: Decimal | None = None
    upper_value: Decimal | None = None
    unit: str | None = None
    temporal_window: TemporalWindow | None = None
    logical_operator: LogicalOperator | None = None
    children: list["EligibilityCriterion"] = Field(default_factory=list)
    required_patient_fields: list[str] = Field(default_factory=list)
    requires_human_review: bool = False

    @field_validator("criterion_id", "original_text")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_compound_structure(self) -> "EligibilityCriterion":
        if self.evaluation_type is EvaluationType.COMPOUND:
            if not self.children:
                raise ValueError("compound criterion must contain children")
            if self.logical_operator is None:
                raise ValueError("compound criterion must provide a logical_operator")
            return self

        if self.children:
            raise ValueError("non-compound criterion must not contain children")
        if self.logical_operator is not None:
            raise ValueError("non-compound criterion must not provide a logical_operator")
        return self
