"""Deterministic regression coverage for supported Trial 2 source requirements."""

import asyncio

from clinical_trial_prescreener.agents.coordinator import CoordinatorAgent
from clinical_trial_prescreener.domain.assessment import (
    CriterionStatus,
    TrialAssessmentStatus,
    VerificationResult,
    VerificationStatus,
)
from clinical_trial_prescreener.domain.criterion import (
    CriterionCategory,
    CriterionType,
    EligibilityCriterion,
    EvaluationType,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.criteria_extraction import (
    _enrich_patient_field_metadata,
)
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient


def _trial_two_criteria() -> list[EligibilityCriterion]:
    return [
        EligibilityCriterion(
            criterion_id="INC-001",
            criterion_type=CriterionType.INCLUSION,
            category=CriterionCategory.OTHER,
            original_text=(
                "Type 2 diabetics between the ages of 25 years and 60 years will "
                "be chosen; both male and female patients"
            ),
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="INC-002",
            criterion_type=CriterionType.INCLUSION,
            category=CriterionCategory.OTHER,
            original_text=(
                "A fasting blood sugar level of 126 mg/dl and a random blood sugar "
                "level of less than 200 mg/dl"
            ),
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="EXC-001",
            criterion_type=CriterionType.EXCLUSION,
            category=CriterionCategory.OTHER,
            original_text="Patients with systemic conditions other than type 2 diabetes",
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="EXC-002",
            criterion_type=CriterionType.EXCLUSION,
            category=CriterionCategory.OTHER,
            original_text="Women who are pregnant",
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="EXC-003",
            criterion_type=CriterionType.EXCLUSION,
            category=CriterionCategory.OTHER,
            original_text="Those patients that have used antibiotics within the previous three months",
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
    ]


def test_trial_two_supported_and_missing_deterministic_facts_are_not_human_review() -> None:
    criteria = _trial_two_criteria()
    _enrich_patient_field_metadata(criteria)
    results = {
        criterion.criterion_id: EligibilityEvaluator(reference_date=REFERENCE_DATE).evaluate(
            criterion, synthetic_patient()
        )
        for criterion in criteria
    }

    assert results["INC-001"].status is CriterionStatus.MET
    assert results["INC-001"].patient_evidence == (
        "condition=Type 2 Diabetes; age=48"
    )
    assert results["INC-001"].requires_human_review is False

    assert results["INC-002"].status is CriterionStatus.UNKNOWN
    assert results["INC-002"].missing_information == [
        "fasting blood glucose",
        "random blood glucose",
    ]
    assert results["INC-002"].requires_human_review is False

    assert results["EXC-001"].status is CriterionStatus.UNKNOWN
    assert results["EXC-001"].missing_information == ["other systemic conditions"]
    assert results["EXC-001"].requires_human_review is False

    assert results["EXC-002"].status is CriterionStatus.UNKNOWN
    assert results["EXC-002"].missing_information == ["pregnancy status"]
    assert results["EXC-002"].requires_human_review is False

    assert results["EXC-003"].status is CriterionStatus.UNKNOWN
    assert results["EXC-003"].missing_information == [
        "antibiotic use within previous 3 months"
    ]
    assert results["EXC-003"].requires_human_review is False

    assessment = AssessmentService().aggregate("NCT07549373", list(results.values()))
    assert assessment.status is TrialAssessmentStatus.INSUFFICIENT_INFORMATION
    decision = asyncio.run(
        CoordinatorAgent().decide(
            patient_id="DEMO-P001",
            trial_id="NCT07549373",
            trial_assessment=assessment,
            verification_result=VerificationResult(
                status=VerificationStatus.APPROVED,
                summary_reason="Deterministic regression test verification.",
            ),
            missing_information=assessment.missing_information,
            retry_count=0,
            reevaluation_count=0,
        )
    )
    assert decision.action.value == "REQUEST_INFORMATION"
