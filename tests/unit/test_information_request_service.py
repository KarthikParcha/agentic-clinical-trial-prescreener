import asyncio
import json
from pathlib import Path

import pytest

from clinical_trial_prescreener.agents.coordinator import CoordinatorAgent
from clinical_trial_prescreener.agents.verifier import VerificationAgent
from clinical_trial_prescreener.domain.assessment import (
    CoordinatorAction,
    CriterionStatus,
    TrialAssessmentStatus,
    VerificationStatus,
)
from clinical_trial_prescreener.domain.information_request import (
    InformationAnswer,
    InformationRequest,
)
from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    StudyType,
    TrialStatus,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from clinical_trial_prescreener.services.information_request_service import (
    InformationRequestService,
)
from clinical_trial_prescreener.workflow.graph import PrescreeningWorkflow
from clinical_trial_prescreener.workflow.state import initial_workflow_state
from tests.golden.criteria_evaluation import load_golden_criteria
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


class FrozenCriteriaExtractor:
    def __init__(self, criteria: list[object]) -> None:
        self._criteria = criteria

    async def extract(self, source: object, **_: object) -> list[object]:
        return [criterion.model_copy(deep=True) for criterion in self._criteria]


class ApprovedVerificationClient:
    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {
                "status": "APPROVED",
                "summary_reason": "Supplied evidence supports the assessment.",
            }
        )


def _criteria() -> list[object]:
    return [item.expected for item in load_golden_criteria(GOLDEN_PATH).criteria]


def _trial() -> ClinicalTrial:
    return ClinicalTrial(
        trial_id="NCT07438444",
        title="Frozen NCT07438444 information-request test",
        status=TrialStatus.RECRUITING,
        study_type=StudyType.INTERVENTIONAL,
    )


def _run_workflow(patient: object) -> dict[str, object]:
    graph = PrescreeningWorkflow(
        criteria_extractor=FrozenCriteriaExtractor(_criteria()),  # type: ignore[arg-type]
        eligibility_evaluator=EligibilityEvaluator(reference_date=REFERENCE_DATE),
        assessment_service=AssessmentService(),
        verification_agent=VerificationAgent(ApprovedVerificationClient()),
        coordinator_agent=CoordinatorAgent(),
    ).compile()
    return asyncio.run(
        graph.ainvoke(initial_workflow_state(patient, _trial()), {"recursion_limit": 20})
    )


def test_request_information_answer_re_evaluates_to_possible_match() -> None:
    initial = _run_workflow(synthetic_patient())

    assert initial["trial_assessment"].status is TrialAssessmentStatus.INSUFFICIENT_INFORMATION
    assert initial["verification_result"].status is VerificationStatus.APPROVED
    assert initial["coordinator_decision"].action is CoordinatorAction.REQUEST_INFORMATION

    requests = InformationRequestService().create_requests(
        initial["criteria"], initial["criterion_assessments"]
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.criterion_id == "EXC-002"
    assert request.patient_field == "heart_failure_hospitalization"
    assert request.question == (
        "Has the patient been hospitalized for heart failure within the past 6 months?"
    )
    assert request.temporal_context is not None
    assert request.temporal_context.value == 6
    assert request.temporal_context.unit.value == "MONTH"

    updated_patient = InformationRequestService().apply_answer(
        synthetic_patient(),
        request,
        InformationAnswer(
            criterion_id="EXC-002",
            patient_field="heart_failure_hospitalization",
            value=False,
            temporal_context=request.temporal_context,
        ),
    )
    result = _run_workflow(updated_patient)

    statuses = {
        item.criterion_id: item.status for item in result["criterion_assessments"]
    }
    assert statuses["EXC-002"] is CriterionStatus.NOT_MET
    assert result["trial_assessment"].status is TrialAssessmentStatus.POSSIBLE_MATCH
    assert result["verification_result"].status is VerificationStatus.APPROVED
    assert result["coordinator_decision"].action is CoordinatorAction.COMPLETE


def test_missing_answer_preserves_unknown_information() -> None:
    initial = _run_workflow(synthetic_patient())
    request = InformationRequestService().create_requests(
        initial["criteria"], initial["criterion_assessments"]
    )[0]

    unchanged_patient = InformationRequestService().apply_answer(
        synthetic_patient(),
        request,
        InformationAnswer(
            criterion_id=request.criterion_id,
            patient_field=request.patient_field,
            temporal_context=request.temporal_context,
        ),
    )
    result = _run_workflow(unchanged_patient)

    statuses = {
        item.criterion_id: item.status for item in result["criterion_assessments"]
    }
    assert statuses["EXC-002"] is CriterionStatus.UNKNOWN


def test_unsupported_or_mismatched_answers_are_rejected() -> None:
    patient = synthetic_patient()
    service = InformationRequestService()
    request = InformationRequest(
        criterion_id="EXC-002",
        patient_field="unsupported_fact",
        question="Unsupported?",
        reason="Test.",
    )

    with pytest.raises(ValueError, match="not supported"):
        service.apply_answer(
            patient,
            request,
            InformationAnswer(
                criterion_id="EXC-002",
                patient_field="unsupported_fact",
                value=False,
            ),
        )

    supported = InformationRequest(
        criterion_id="EXC-002",
        patient_field="heart_failure_hospitalization",
        question="Has the patient been hospitalized for heart failure within the past 6 months?",
        reason="Test.",
    )
    with pytest.raises(ValueError, match="must match"):
        service.apply_answer(
            patient,
            supported,
            InformationAnswer(
                criterion_id="EXC-002",
                patient_field="heart_attack",
                value=False,
            ),
        )
