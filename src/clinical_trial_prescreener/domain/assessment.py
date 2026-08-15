"""Criterion-level assessment schemas."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinical_trial_prescreener.domain.criterion import (
    CriterionType,
    EligibilityCriterion,
)


class CriterionStatus(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvaluationMethod(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    COMPOUND = "COMPOUND"
    SEMANTIC_LLM = "SEMANTIC_LLM"
    HUMAN = "HUMAN"


class TrialAssessmentStatus(str, Enum):
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    UNLIKELY_MATCH = "UNLIKELY_MATCH"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class VerificationStatus(str, Enum):
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    REQUIRES_REEVALUATION = "REQUIRES_REEVALUATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class CoordinatorAction(str, Enum):
    """The finite set of actions a workflow layer may execute next."""

    COMPLETE = "COMPLETE"
    REEVALUATE = "REEVALUATE"
    REQUEST_INFORMATION = "REQUEST_INFORMATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    RETRY = "RETRY"
    FAIL = "FAIL"


class CriterionAssessment(BaseModel):
    """Evidence-backed truth assessment for one eligibility criterion."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    criterion_type: CriterionType
    status: CriterionStatus
    reason: str
    trial_evidence: str
    patient_evidence: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    evaluation_method: EvaluationMethod
    requires_human_review: bool = False

    @field_validator("criterion_id", "reason", "trial_evidence")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_unknown_evidence(self) -> "CriterionAssessment":
        if self.status is CriterionStatus.UNKNOWN and not self.missing_information:
            raise ValueError("UNKNOWN assessments must identify missing_information")
        if self.status is not CriterionStatus.UNKNOWN and self.missing_information:
            raise ValueError("only UNKNOWN assessments may contain missing_information")
        return self


class TrialAssessment(BaseModel):
    """Deterministic preliminary aggregation of criterion truth assessments."""

    model_config = ConfigDict(extra="forbid")

    trial_id: str
    status: TrialAssessmentStatus
    criterion_assessments: list[CriterionAssessment]
    blocking_criterion_ids: list[str] = Field(default_factory=list)
    unknown_criterion_ids: list[str] = Field(default_factory=list)
    human_review_criterion_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    summary_reason: str
    requires_human_review: bool = False

    @field_validator("trial_id", "summary_reason")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_aggregation_consistency(self) -> "TrialAssessment":
        assessment_ids = [item.criterion_id for item in self.criterion_assessments]
        if len(assessment_ids) != len(set(assessment_ids)):
            raise ValueError("criterion_assessments must have unique criterion IDs")
        for name, values in (
            ("blocking_criterion_ids", self.blocking_criterion_ids),
            ("unknown_criterion_ids", self.unknown_criterion_ids),
            ("human_review_criterion_ids", self.human_review_criterion_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
            if not set(values).issubset(assessment_ids):
                raise ValueError(f"{name} must refer to criterion_assessments")
        if self.requires_human_review != bool(self.human_review_criterion_ids):
            raise ValueError(
                "requires_human_review must match human_review_criterion_ids"
            )
        return self


class PrescreeningResult(BaseModel):
    """The connected criterion and trial-level outputs for one patient and trial."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str
    trial_id: str
    criteria: list[EligibilityCriterion]
    criterion_assessments: list[CriterionAssessment]
    trial_assessment: TrialAssessment

    @field_validator("patient_id", "trial_id")
    @classmethod
    def validate_result_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_pipeline_consistency(self) -> "PrescreeningResult":
        criterion_ids = [item.criterion_id for item in self.criteria]
        assessment_ids = [item.criterion_id for item in self.criterion_assessments]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criteria must have unique criterion IDs")
        if criterion_ids != assessment_ids:
            raise ValueError("criterion_assessments must match criteria in source order")
        if self.trial_assessment.trial_id != self.trial_id:
            raise ValueError("trial_assessment trial_id must match trial_id")
        if self.trial_assessment.criterion_assessments != self.criterion_assessments:
            raise ValueError(
                "trial_assessment criterion_assessments must match pipeline assessments"
            )
        return self


class VerificationFinding(BaseModel):
    """One evidence-supported concern found during bounded verification."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str | None = None
    finding: str
    previous_status: CriterionStatus | None = None
    recommended_status: CriterionStatus | None = None
    missing_information: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    issue_type: str | None = None
    concrete_evidence: str | None = None
    expected_semantics: str | None = None
    observed_semantics: str | None = None

    @field_validator(
        "criterion_id",
        "finding",
        "issue_type",
        "concrete_evidence",
        "expected_semantics",
        "observed_semantics",
    )
    @classmethod
    def validate_optional_non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank when provided")
        return value


class VerificationResult(BaseModel):
    """Structured output from one independent, bounded verification pass."""

    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    findings: list[VerificationFinding] = Field(default_factory=list)
    summary_reason: str
    requires_human_review: bool = False

    @field_validator("summary_reason")
    @classmethod
    def validate_summary_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_verification_consistency(self) -> "VerificationResult":
        if (
            self.status is VerificationStatus.APPROVED
            and (self.findings or self.requires_human_review)
        ):
            raise ValueError("APPROVED verification must not contain unresolved findings")
        if self.status is VerificationStatus.CORRECTED and not any(
            finding.criterion_id is not None
            and finding.previous_status is not None
            and finding.recommended_status is not None
            and finding.previous_status is not finding.recommended_status
            for finding in self.findings
        ):
            raise ValueError(
                "CORRECTED verification requires an explicit criterion status correction"
            )
        if self.status is VerificationStatus.HUMAN_REVIEW and not self.requires_human_review:
            raise ValueError("HUMAN_REVIEW verification must require human review")
        if self.status is VerificationStatus.HUMAN_REVIEW and not any(
            finding.requires_human_review
            and finding.criterion_id is not None
            and finding.issue_type is not None
            and finding.concrete_evidence is not None
            and finding.expected_semantics is not None
            and finding.observed_semantics is not None
            for finding in self.findings
        ):
            raise ValueError("HUMAN_REVIEW requires a concrete criterion-specific issue")
        return self


class CoordinatorDecision(BaseModel):
    """A bounded, structured next-step decision without workflow side effects."""

    model_config = ConfigDict(extra="forbid")

    action: CoordinatorAction
    reason: str
    requires_human_review: bool = False
    used_llm: bool = False
    fallback_reason: str | None = None

    @field_validator("reason", "fallback_reason")
    @classmethod
    def validate_optional_non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank when provided")
        return value

    @model_validator(mode="after")
    def validate_human_review_consistency(self) -> "CoordinatorDecision":
        if self.action is CoordinatorAction.HUMAN_REVIEW and not self.requires_human_review:
            raise ValueError("HUMAN_REVIEW decisions must require human review")
        if self.action is not CoordinatorAction.HUMAN_REVIEW and self.requires_human_review:
            raise ValueError("only HUMAN_REVIEW decisions may require human review")
        return self
