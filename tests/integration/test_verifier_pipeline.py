"""Deterministic verifier flow demonstrating supported and unsafe assessments."""

import asyncio
import json
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

import pytest

from clinical_trial_prescreener.agents.verifier import VerificationAgent
from clinical_trial_prescreener.domain.assessment import (
    CriterionAssessment,
    CriterionStatus,
    EvaluationMethod,
    VerificationStatus,
)
from clinical_trial_prescreener.domain.criterion import (
    CriterionType,
    EligibilityCriterion,
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
from tests.golden.criteria_evaluation import load_golden_criteria
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


class StubVerificationClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(self._payload)


def run(coroutine: Awaitable[Any]) -> Any:
    return asyncio.run(coroutine)


def assessment_context() -> tuple[
    ClinicalTrial,
    list[EligibilityCriterion],
    list[CriterionAssessment],
]:
    trial = ClinicalTrial(
        trial_id="NCT07438444",
        title="NCT07438444 verifier pipeline",
        status=TrialStatus.RECRUITING,
        study_type=StudyType.INTERVENTIONAL,
        eligibility_text="Frozen NCT07438444 source evidence.",
    )
    criteria = [item.expected for item in load_golden_criteria(GOLDEN_PATH).criteria]
    assessments = [
        EligibilityEvaluator(reference_date=REFERENCE_DATE).evaluate(
            criterion, synthetic_patient()
        )
        for criterion in criteria
    ]
    return trial, criteria, assessments


async def verify(
    client: StubVerificationClient,
    trial: ClinicalTrial,
    criteria: list[EligibilityCriterion],
    assessments: list[CriterionAssessment],
) -> VerificationStatus:
    trial_assessment = AssessmentService().aggregate(trial.trial_id, assessments)
    result = await VerificationAgent(client).verify(
        trial=trial,
        patient=synthetic_patient(),
        criteria=criteria,
        criterion_assessments=assessments,
        trial_assessment=trial_assessment,
    )
    return result.status


@pytest.mark.integration
def test_verifier_pipeline_prints_correct_and_injected_error_outcomes() -> None:
    trial, criteria, correct_assessments = assessment_context()
    correct_status = run(
        verify(
            StubVerificationClient(
                {
                    "status": "APPROVED",
                    "findings": [],
                    "summary_reason": "All supplied evidence supports the assessments.",
                    "requires_human_review": False,
                }
            ),
            trial,
            criteria,
            correct_assessments,
        )
    )

    wrong_assessments = [item.model_copy(deep=True) for item in correct_assessments]
    wrong_assessments[5] = CriterionAssessment(
        criterion_id="EXC-002",
        criterion_type=CriterionType.EXCLUSION,
        status=CriterionStatus.NOT_MET,
        reason="Incorrectly treated absent heart-failure evidence as false.",
        trial_evidence=criteria[5].original_text,
        evaluation_method=EvaluationMethod.COMPOUND,
    )
    wrong_status = run(
        verify(
            StubVerificationClient(
                {
                    "status": "REQUIRES_REEVALUATION",
                    "findings": [
                        {
                            "criterion_id": "EXC-002",
                            "finding": "Heart-failure hospitalization evidence is missing.",
                            "recommended_status": "UNKNOWN",
                            "missing_information": [
                                "medical_history: heart_failure_hospitalization"
                            ],
                        }
                    ],
                    "summary_reason": "The cardiovascular conclusion is unsupported.",
                    "requires_human_review": False,
                }
            ),
            trial,
            criteria,
            wrong_assessments,
        )
    )

    print("\nVERIFIER PIPELINE")
    print("Correct pipeline: EXC-002 = UNKNOWN ->", correct_status.value)
    print("Injected wrong pipeline: EXC-002 = NOT_MET ->", wrong_status.value)

    assert correct_status is VerificationStatus.APPROVED
    assert wrong_status is VerificationStatus.REQUIRES_REEVALUATION
