"""Deterministic regression coverage for supported Trial 1 source requirements."""

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


def _trial_one_criteria() -> list[EligibilityCriterion]:
    return [
        EligibilityCriterion(
            criterion_id="INC-001",
            criterion_type=CriterionType.INCLUSION,
            category=CriterionCategory.OTHER,
            original_text="At least 18 years old at time of consent",
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="INC-004",
            criterion_type=CriterionType.INCLUSION,
            category=CriterionCategory.OTHER,
            original_text=(
                "Participants with medical history of hypertension and on active "
                "pharmacological treatment"
            ),
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="INC-002",
            criterion_type=CriterionType.INCLUSION,
            category=CriterionCategory.CONSENT,
            original_text=(
                "Signed and dated written informed consent in accordance with "
                "ICH-GCP and local legislation prior to admission to the trial"
            ),
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="INC-005",
            criterion_type=CriterionType.INCLUSION,
            category=CriterionCategory.OTHER,
            original_text=(
                "Participants with medical history of type 2 diabetes mellitus "
                "(T2DM) and on active pharmacological treatment"
            ),
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="INC-006",
            criterion_type=CriterionType.INCLUSION,
            category=CriterionCategory.OTHER,
            original_text=(
                "Established cardiovascular (CV) disease and on active "
                "pharmacological treatment"
            ),
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
        EligibilityCriterion(
            criterion_id="EXC-001",
            criterion_type=CriterionType.EXCLUSION,
            category=CriterionCategory.OTHER,
            original_text="History of HF or hospitalization for HF or treatment of HF",
            evaluation_type=EvaluationType.HUMAN_ONLY,
            requires_human_review=True,
        ),
    ]


def test_trial_one_supported_facts_and_concrete_gaps_are_evaluated_deterministically() -> None:
    criteria = _trial_one_criteria()
    _enrich_patient_field_metadata(criteria)
    assessments = [
        EligibilityEvaluator(reference_date=REFERENCE_DATE).evaluate(criterion, synthetic_patient())
        for criterion in criteria
    ]
    results = {item.criterion_id: item for item in assessments}

    assert results["INC-001"].status is CriterionStatus.MET
    assert results["INC-001"].patient_evidence == "age=48"
    assert results["INC-005"].status is CriterionStatus.MET
    assert "Metformin" in results["INC-005"].patient_evidence
    assert results["INC-004"].status is CriterionStatus.UNKNOWN
    assert results["INC-004"].missing_information == [
        "medical_history: hypertension diagnosis"
    ]
    assert results["INC-002"].status is CriterionStatus.UNKNOWN
    assert results["INC-002"].missing_information == [
        "signed and dated trial-specific informed consent"
    ]
    assert results["INC-002"].requires_human_review is True
    assert results["INC-006"].status is CriterionStatus.UNKNOWN
    assert results["INC-006"].missing_information == [
        "medications: active cardiovascular treatment"
    ]
    assert results["INC-006"].patient_evidence == (
        "medical_history=Heart attack, Stroke, Congestive heart failure"
    )
    assert results["EXC-001"].status is CriterionStatus.MET
    assert results["EXC-001"].patient_evidence == "medical_history=Congestive heart failure"

    assessment = AssessmentService().aggregate("NCT07064473", assessments)
    assert assessment.status is TrialAssessmentStatus.UNLIKELY_MATCH
    decision = asyncio.run(
        CoordinatorAgent().decide(
            patient_id="DEMO-P001",
            trial_id="NCT07064473",
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
    assert decision.action.value == "HUMAN_REVIEW"
