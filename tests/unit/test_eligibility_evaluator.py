from pathlib import Path

import pytest
from pydantic import ValidationError

from clinical_trial_prescreener.domain.assessment import (
    CriterionAssessment,
    CriterionStatus,
    EvaluationMethod,
)
from clinical_trial_prescreener.domain.criterion import (
    ComparisonOperator,
    CriterionCategory,
    CriterionType,
    EligibilityCriterion,
    EvaluationType,
)
from clinical_trial_prescreener.domain.patient import PatientFactConfirmation
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
    _combine_statuses,
)
from tests.golden.criteria_evaluation import load_golden_criteria
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


def test_evaluates_nct07438444_truth_without_trial_level_interpretation() -> None:
    criteria = {
        item.expectation_id: item.expected for item in load_golden_criteria(GOLDEN_PATH).criteria
    }
    evaluator = EligibilityEvaluator(reference_date=REFERENCE_DATE)
    patient = synthetic_patient()

    statuses = {
        key: evaluator.evaluate(criterion, patient).status for key, criterion in criteria.items()
    }

    assert statuses == {
        "T2D_DURATION": CriterionStatus.MET,
        "INSULIN_NAIVE": CriterionStatus.MET,
        "HBA1C_RANGE": CriterionStatus.MET,
        "BMI_MINIMUM": CriterionStatus.MET,
        "TYPE_1_DIABETES": CriterionStatus.NOT_MET,
        "RECENT_CARDIOVASCULAR_EVENT": CriterionStatus.UNKNOWN,
        "NYHA_CLASS_III_IV": CriterionStatus.NOT_MET,
        "T2D_MORBID_OBESITY_WEIGHT_LOSS_PROCEDURE": CriterionStatus.NOT_MET,
    }

    cardiovascular = evaluator.evaluate(criteria["RECENT_CARDIOVASCULAR_EVENT"], patient)
    assert cardiovascular.evaluation_method is EvaluationMethod.COMPOUND
    assert cardiovascular.missing_information == [
        "medical_history: heart_failure_hospitalization"
    ]


def test_compound_truth_tables_prioritize_decisive_child_statuses() -> None:
    from clinical_trial_prescreener.domain.criterion import LogicalOperator

    assert _combine_statuses(
        [CriterionStatus.MET, CriterionStatus.UNKNOWN], LogicalOperator.OR
    ) is CriterionStatus.MET
    assert _combine_statuses(
        [CriterionStatus.NOT_MET, CriterionStatus.UNKNOWN], LogicalOperator.OR
    ) is CriterionStatus.UNKNOWN
    assert _combine_statuses(
        [CriterionStatus.NOT_MET, CriterionStatus.UNKNOWN], LogicalOperator.AND
    ) is CriterionStatus.NOT_MET


def test_unknown_assessment_requires_explicit_missing_information() -> None:
    with pytest.raises(ValidationError, match="missing_information"):
        CriterionAssessment(
            criterion_id="INC-001",
            criterion_type=CriterionType.INCLUSION,
            status=CriterionStatus.UNKNOWN,
            reason="No value",
            trial_evidence="Source text",
            evaluation_method=EvaluationMethod.DETERMINISTIC,
        )


def test_other_systemic_conditions_exclusion_is_not_met_by_type_2_diabetes_alone() -> None:
    criterion = EligibilityCriterion(
        criterion_id="EXC-001",
        criterion_type=CriterionType.EXCLUSION,
        category=CriterionCategory.MEDICAL_HISTORY,
        original_text="Patients with systemic conditions other than type 2 diabetes",
        evaluation_type=EvaluationType.BOOLEAN,
        field_name="type_2_diabetes",
        operator=ComparisonOperator.EQ,
        value=True,
    )

    result = EligibilityEvaluator(reference_date=REFERENCE_DATE).evaluate(
        criterion, synthetic_patient()
    )

    assert result.status is CriterionStatus.UNKNOWN
    assert result.missing_information == ["other systemic conditions"]
    assert result.reason == "Required fact other_systemic_conditions is unavailable."


def test_other_systemic_conditions_exclusion_is_not_met_when_explicitly_absent() -> None:
    criterion = EligibilityCriterion(
        criterion_id="EXC-001",
        criterion_type=CriterionType.EXCLUSION,
        category=CriterionCategory.MEDICAL_HISTORY,
        original_text="Patients with systemic conditions other than type 2 diabetes",
        evaluation_type=EvaluationType.BOOLEAN,
        field_name="type_2_diabetes",
        operator=ComparisonOperator.EQ,
        value=True,
    )
    patient = synthetic_patient().model_copy(
        update={
            "fact_confirmations": [
                PatientFactConfirmation(
                    fact_name="other_systemic_conditions",
                    value=False,
                )
            ]
        }
    )

    result = EligibilityEvaluator(reference_date=REFERENCE_DATE).evaluate(
        criterion, patient
    )

    assert result.status is CriterionStatus.NOT_MET
    assert result.patient_evidence == (
        "patient-supplied confirmation: other_systemic_conditions=False"
    )
