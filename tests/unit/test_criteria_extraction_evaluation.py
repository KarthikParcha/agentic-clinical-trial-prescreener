from decimal import Decimal
from pathlib import Path

from clinical_trial_prescreener.domain.criterion import (
    CriterionType,
    EligibilityCriterion,
    EvaluationType,
    LogicalOperator,
)
from tests.golden.criteria_evaluation import (
    evaluate_criteria,
    format_evaluation_report,
    load_golden_criteria,
)

GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


def test_human_reviewed_golden_file_has_eight_type_2_diabetes_criteria() -> None:
    golden = load_golden_criteria(GOLDEN_PATH)

    assert golden.trial_id == "NCT07438444"
    assert golden.target_population == "Type 2 Diabetes"
    assert len(golden.criteria) == 8
    assert [item.expected.criterion_type for item in golden.criteria].count(
        CriterionType.INCLUSION
    ) == 4
    assert [item.expected.criterion_type for item in golden.criteria].count(
        CriterionType.EXCLUSION
    ) == 4

    expected_source = " ".join(
        item.expected.original_text.casefold() for item in golden.criteria
    )
    assert "self-reported change in body weight" not in expected_source
    assert "medications or alternative remedies for weight loss" not in expected_source


def test_golden_compounds_preserve_temporal_and_nested_logical_structure() -> None:
    golden = load_golden_criteria(GOLDEN_PATH)
    by_id = {item.expectation_id: item.expected for item in golden.criteria}

    cardiovascular = by_id["RECENT_CARDIOVASCULAR_EVENT"]
    assert cardiovascular.logical_operator is LogicalOperator.OR
    assert cardiovascular.temporal_window is not None
    assert cardiovascular.temporal_window.value == Decimal(6)
    assert all(child.temporal_window is not None for child in cardiovascular.children)

    procedure = by_id["T2D_MORBID_OBESITY_WEIGHT_LOSS_PROCEDURE"]
    assert procedure.logical_operator is LogicalOperator.AND
    assert procedure.children[2].logical_operator is LogicalOperator.OR
    assert len(procedure.children[2].children) == 2

    duration = by_id["T2D_DURATION"]
    assert duration.evaluation_type is EvaluationType.NUMERIC
    assert duration.field_name == "diagnosis_duration_years"
    assert duration.required_patient_fields == ["diagnosis_date"]
    assert duration.temporal_window is None


def test_exact_semantic_extraction_matches_all_golden_expectations() -> None:
    golden = load_golden_criteria(GOLDEN_PATH)
    extracted = [item.expected.model_copy(deep=True) for item in golden.criteria]

    report = evaluate_criteria(extracted, golden)

    assert report.expected_count == 8
    assert report.found_count == 8
    assert report.matched_count == 8
    assert report.missed_criteria == []
    assert report.unexpected_criteria == []
    assert report.structural_errors == []
    assert report.population_leakage == []
    for metric in (
        report.field_mapping_accuracy,
        report.threshold_accuracy,
        report.logical_structure_accuracy,
        report.required_patient_fields_accuracy,
        report.boolean_semantics_accuracy,
        report.temporal_window_accuracy,
    ):
        assert metric.accuracy_percent == 100
        assert metric.status == "PASS"

    formatted = format_evaluation_report(report)
    assert "Expected: 8" in formatted
    assert "Found: 8" in formatted
    assert "Field mapping accuracy: 100.0%" in formatted
    assert "[PASS] HBA1C_RANGE.operator" in formatted


def test_evaluation_identifies_wrong_type_threshold_window_and_logic() -> None:
    golden = load_golden_criteria(GOLDEN_PATH)
    extracted = [item.expected.model_copy(deep=True) for item in golden.criteria]
    extracted[0].criterion_type = CriterionType.EXCLUSION
    extracted[2].lower_value = Decimal("8.0")
    extracted[5].temporal_window = None
    extracted[5].children[0].temporal_window = None
    extracted[5].logical_operator = LogicalOperator.AND

    report = evaluate_criteria(extracted, golden)

    assert report.matched_count == 8
    assert any(
        "T2D_DURATION.criterion_type" in error for error in report.structural_errors
    )
    assert any("HBA1C_RANGE.lower_value" in error for error in report.structural_errors)
    assert any(
        "RECENT_CARDIOVASCULAR_EVENT.children[1].temporal_window" in error
        for error in report.structural_errors
    )
    assert any(
        "RECENT_CARDIOVASCULAR_EVENT.logical_operator" in error
        for error in report.structural_errors
    )


def test_evaluation_captures_known_groq_baseline_structural_failures() -> None:
    golden = load_golden_criteria(GOLDEN_PATH)
    extracted = [item.expected.model_copy(deep=True) for item in golden.criteria]

    def clear_deterministic_mapping(criterion: EligibilityCriterion) -> None:
        criterion.field_name = None
        criterion.required_patient_fields = []
        for child in criterion.children:
            clear_deterministic_mapping(child)

    for criterion in extracted:
        clear_deterministic_mapping(criterion)

    for criterion in extracted[4:]:
        for candidate in [criterion, *criterion.children]:
            if candidate.evaluation_type is EvaluationType.BOOLEAN:
                candidate.value = False

    extracted[6].value = None
    for child in extracted[5].children:
        child.temporal_window = None

    flattened_procedure = extracted[7].children[2]
    flattened_procedure.evaluation_type = EvaluationType.BOOLEAN
    flattened_procedure.value = False
    flattened_procedure.logical_operator = None
    flattened_procedure.children = []

    report = evaluate_criteria(extracted, golden)

    assert report.matched_count == 8
    assert report.field_mapping_accuracy.accuracy_percent == 0
    assert report.threshold_accuracy.accuracy_percent == 100
    assert report.required_patient_fields_accuracy.accuracy_percent == 0
    assert report.boolean_semantics_accuracy.quality == "poor"
    assert any(".field_name" in error for error in report.structural_errors)
    assert any(
        ".required_patient_fields" in error for error in report.structural_errors
    )
    assert any(
        "TYPE_1_DIABETES.value: expected True, got False" in error
        for error in report.structural_errors
    )

    formatted = format_evaluation_report(report)
    assert "Boolean semantics:" in formatted and "POOR" in formatted
    assert "[FAIL] TYPE_1_DIABETES.value" in formatted
    assert any("NYHA_CLASS_III_IV.value" in error for error in report.structural_errors)
    # The temporal window on the compound parent is semantically inherited by each
    # child, so removing duplicate child windows remains valid.
    assert not any(
        "RECENT_CARDIOVASCULAR_EVENT.children[1].temporal_window" in error
        for error in report.structural_errors
    )
    assert any(
        "T2D_MORBID_OBESITY_WEIGHT_LOSS_PROCEDURE.children[3].logical_operator" in error
        for error in report.structural_errors
    )


def test_evaluation_accepts_temporal_window_inherited_from_compound_parent() -> None:
    golden = load_golden_criteria(GOLDEN_PATH)
    extracted = [item.expected.model_copy(deep=True) for item in golden.criteria]

    for child in extracted[5].children:
        child.temporal_window = None

    report = evaluate_criteria(extracted, golden)

    assert report.temporal_window_accuracy.accuracy_percent == 100
    inherited = next(
        field
        for field in report.criterion_comparisons[5].field_comparisons
        if field.path.endswith("children[1]") and field.field_name == "temporal_window"
    )
    assert inherited.passed is True
    assert inherited.actual.startswith("inherited ")


def test_evaluation_identifies_missed_unexpected_and_population_leakage() -> None:
    golden = load_golden_criteria(GOLDEN_PATH)
    extracted = [item.expected.model_copy(deep=True) for item in golden.criteria]
    extracted.pop(3)
    leaked = golden.criteria[3].expected.model_copy(deep=True)
    leaked.criterion_id = "UNEXPECTED-001"
    leaked.original_text = (
        "Have a self-reported change in body weight greater than 5 kilograms"
    )
    extracted.append(leaked)

    report = evaluate_criteria(extracted, golden)

    assert report.matched_count == 7
    assert report.missed_criteria == ["BMI_MINIMUM: BMI at least 23 kg/m2"]
    assert report.unexpected_criteria == [
        (
            "UNEXPECTED-001: Have a self-reported change in body weight greater than "
            "5 kilograms"
        )
    ]
    assert report.population_leakage == report.unexpected_criteria
