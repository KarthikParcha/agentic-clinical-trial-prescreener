from pathlib import Path

from clinical_trial_prescreener.domain.assessment import (
    CriterionAssessment,
    CriterionStatus,
    EvaluationMethod,
    TrialAssessmentStatus,
)
from clinical_trial_prescreener.domain.criterion import CriterionType
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from tests.golden.criteria_evaluation import load_golden_criteria
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


def assessment(
    criterion_id: str,
    criterion_type: CriterionType,
    status: CriterionStatus,
    *,
    human_review: bool = False,
    method: EvaluationMethod = EvaluationMethod.DETERMINISTIC,
    missing: list[str] | None = None,
) -> CriterionAssessment:
    return CriterionAssessment(
        criterion_id=criterion_id,
        criterion_type=criterion_type,
        status=status,
        reason="Synthetic assessment.",
        trial_evidence="Synthetic criterion.",
        missing_information=missing or (["required patient fact"] if status is CriterionStatus.UNKNOWN else []),
        evaluation_method=method,
        requires_human_review=human_review,
    )


def test_all_satisfied_criteria_produce_possible_match() -> None:
    result = AssessmentService().aggregate(
        "NCT00000001",
        [
            assessment("INC-001", CriterionType.INCLUSION, CriterionStatus.MET),
            assessment("EXC-001", CriterionType.EXCLUSION, CriterionStatus.NOT_MET),
            assessment("EXC-002", CriterionType.EXCLUSION, CriterionStatus.NOT_APPLICABLE),
        ],
    )

    assert result.status is TrialAssessmentStatus.POSSIBLE_MATCH
    assert result.blocking_criterion_ids == []
    assert result.unknown_criterion_ids == []


def test_inclusion_failure_and_exclusion_trigger_are_blockers() -> None:
    inclusion = AssessmentService().aggregate(
        "NCT00000001",
        [assessment("INC-001", CriterionType.INCLUSION, CriterionStatus.NOT_MET)],
    )
    exclusion = AssessmentService().aggregate(
        "NCT00000001",
        [assessment("EXC-001", CriterionType.EXCLUSION, CriterionStatus.MET)],
    )

    assert inclusion.status is TrialAssessmentStatus.UNLIKELY_MATCH
    assert inclusion.blocking_criterion_ids == ["INC-001"]
    assert exclusion.status is TrialAssessmentStatus.UNLIKELY_MATCH
    assert exclusion.blocking_criterion_ids == ["EXC-001"]


def test_unknown_and_human_review_priority_without_blocker() -> None:
    unknown = AssessmentService().aggregate(
        "NCT00000001",
        [assessment("EXC-001", CriterionType.EXCLUSION, CriterionStatus.UNKNOWN)],
    )
    human = AssessmentService().aggregate(
        "NCT00000001",
        [
            assessment(
                "EXC-001",
                CriterionType.EXCLUSION,
                CriterionStatus.UNKNOWN,
                human_review=True,
                method=EvaluationMethod.HUMAN,
            )
        ],
    )

    assert unknown.status is TrialAssessmentStatus.INSUFFICIENT_INFORMATION
    assert unknown.unknown_criterion_ids == ["EXC-001"]
    assert human.status is TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED
    assert human.human_review_criterion_ids == ["EXC-001"]
    assert human.requires_human_review is True


def test_blockers_take_priority_over_unknown_and_human_review() -> None:
    result = AssessmentService().aggregate(
        "NCT00000001",
        [
            assessment("INC-001", CriterionType.INCLUSION, CriterionStatus.NOT_MET),
            assessment("EXC-001", CriterionType.EXCLUSION, CriterionStatus.UNKNOWN),
            assessment(
                "EXC-002",
                CriterionType.EXCLUSION,
                CriterionStatus.UNKNOWN,
                human_review=True,
                method=EvaluationMethod.HUMAN,
            ),
        ],
    )

    assert result.status is TrialAssessmentStatus.UNLIKELY_MATCH
    assert result.blocking_criterion_ids == ["INC-001"]
    assert result.unknown_criterion_ids == ["EXC-001", "EXC-002"]
    assert result.human_review_criterion_ids == ["EXC-002"]


def test_missing_information_is_deduplicated_in_first_seen_order() -> None:
    result = AssessmentService().aggregate(
        "NCT00000001",
        [
            assessment(
                "INC-001",
                CriterionType.INCLUSION,
                CriterionStatus.UNKNOWN,
                missing=["HbA1c", "renal function"],
            ),
            assessment(
                "EXC-001",
                CriterionType.EXCLUSION,
                CriterionStatus.UNKNOWN,
                missing=["renal function", "medication history"],
            ),
        ],
    )

    assert result.missing_information == [
        "HbA1c",
        "renal function",
        "medication history",
    ]


def test_current_nct07438444_assessments_aggregate_to_insufficient_information() -> None:
    criteria = [
        item.expected for item in load_golden_criteria(GOLDEN_PATH).criteria
    ]
    evaluator = EligibilityEvaluator(reference_date=REFERENCE_DATE)
    assessments = [evaluator.evaluate(criterion, synthetic_patient()) for criterion in criteria]

    result = AssessmentService().aggregate("NCT07438444", assessments)

    assert result.status is TrialAssessmentStatus.INSUFFICIENT_INFORMATION
    assert result.blocking_criterion_ids == []
    assert result.unknown_criterion_ids == ["EXC-002"]
    assert result.missing_information == [
        "medical_history: heart_failure_hospitalization"
    ]
