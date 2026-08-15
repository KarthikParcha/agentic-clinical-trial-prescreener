"""LangGraph-compatible state passed through the pre-screening workflow."""

from typing import NotRequired, TypedDict

from clinical_trial_prescreener.domain.assessment import (
    CoordinatorDecision,
    CriterionAssessment,
    TrialAssessment,
    VerificationResult,
)
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.domain.patient import PatientProfile
from clinical_trial_prescreener.domain.trial import ClinicalTrial
from clinical_trial_prescreener.observability.trace_models import WorkflowTrace


class WorkflowError(TypedDict):
    """A terminal, structured error captured from a known application/provider failure."""

    node: str
    error_type: str
    message: str
    category: NotRequired[str]
    validation_category: NotRequired[str]
    provider_error_code: NotRequired[str]


class PrescreeningWorkflowState(TypedDict):
    """State fields are added as each bounded workflow node completes."""

    patient: PatientProfile
    trial: ClinicalTrial
    criteria: NotRequired[list[EligibilityCriterion]]
    criterion_assessments: NotRequired[list[CriterionAssessment]]
    trial_assessment: NotRequired[TrialAssessment]
    verification_result: NotRequired[VerificationResult]
    coordinator_decision: NotRequired[CoordinatorDecision]
    missing_information: NotRequired[list[str]]
    retry_count: NotRequired[int]
    reevaluation_count: NotRequired[int]
    error: NotRequired[WorkflowError]
    trace: NotRequired[WorkflowTrace]


def initial_workflow_state(
    patient: PatientProfile, trial: ClinicalTrial
) -> PrescreeningWorkflowState:
    """Create the minimal valid initial state with finite loop counters."""

    return {
        "patient": patient,
        "trial": trial,
        "retry_count": 0,
        "reevaluation_count": 0,
    }
