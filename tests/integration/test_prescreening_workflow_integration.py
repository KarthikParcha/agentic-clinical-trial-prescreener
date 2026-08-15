"""Deterministic full graph validation using frozen human-reviewed NCT07438444 criteria."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from clinical_trial_prescreener.agents.coordinator import CoordinatorAgent
from clinical_trial_prescreener.domain.assessment import (
    CriterionStatus,
    TrialAssessmentStatus,
    VerificationResult,
    VerificationStatus,
)
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.infrastructure.clinicaltrials.normalizer import (
    normalize_trial,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from clinical_trial_prescreener.workflow.graph import PrescreeningWorkflow
from clinical_trial_prescreener.workflow.state import initial_workflow_state
from tests.golden.criteria_evaluation import load_golden_criteria
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "type2_diabetes_recruiting_india.json.json"
)
GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


class FrozenCriteriaExtractor:
    """Stable validated extraction boundary; no live LLM is used in this test."""

    def __init__(self, criteria: list[EligibilityCriterion]) -> None:
        self._criteria = criteria

    async def extract(self, source: object, **_: object) -> list[EligibilityCriterion]:
        return [criterion.model_copy(deep=True) for criterion in self._criteria]


class ApprovedVerifier:
    """The only mocked external decision; it preserves the deterministic assessment."""

    async def verify(self, **_: object) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.APPROVED,
            summary_reason="Deterministic integration approval.",
        )


def nct07438444_trial():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw_study = next(
        study
        for study in fixture["studies"]
        if study["protocolSection"]["identificationModule"]["nctId"] == "NCT07438444"
    )
    return normalize_trial(raw_study)


@pytest.mark.integration
def test_frozen_nct07438444_executes_full_graph_to_request_information() -> None:
    criteria = [item.expected for item in load_golden_criteria(GOLDEN_PATH).criteria]
    graph = PrescreeningWorkflow(
        criteria_extractor=FrozenCriteriaExtractor(criteria),  # type: ignore[arg-type]
        eligibility_evaluator=EligibilityEvaluator(reference_date=REFERENCE_DATE),
        assessment_service=AssessmentService(),
        verification_agent=ApprovedVerifier(),  # type: ignore[arg-type]
        coordinator_agent=CoordinatorAgent(),
    ).compile()

    result: dict[str, Any] = asyncio.run(
        graph.ainvoke(
            initial_workflow_state(synthetic_patient(), nct07438444_trial()),
            {"recursion_limit": 20},
        )
    )

    assert [assessment.status for assessment in result["criterion_assessments"]] == [
        CriterionStatus.MET,
        CriterionStatus.MET,
        CriterionStatus.MET,
        CriterionStatus.MET,
        CriterionStatus.NOT_MET,
        CriterionStatus.UNKNOWN,
        CriterionStatus.NOT_MET,
        CriterionStatus.NOT_MET,
    ]
    assert result["trial_assessment"].status is TrialAssessmentStatus.INSUFFICIENT_INFORMATION
    assert result["verification_result"].status is VerificationStatus.APPROVED
    assert result["coordinator_decision"].action.value == "REQUEST_INFORMATION"
    assert result["reevaluation_count"] == 0
    assert result["missing_information"] == [
        "medical_history: heart_failure_hospitalization"
    ]
