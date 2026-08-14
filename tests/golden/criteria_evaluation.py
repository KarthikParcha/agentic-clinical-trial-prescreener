"""Focused semantic evaluation for the NCT07438444 golden criteria."""

import re
from decimal import Decimal
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinical_trial_prescreener.domain.criterion import (
    EligibilityCriterion,
    EvaluationType,
)

FIELD_MAPPING = "field_mapping"
THRESHOLD = "threshold"
LOGICAL_STRUCTURE = "logical_structure"
REQUIRED_PATIENT_FIELDS = "required_patient_fields"
BOOLEAN_SEMANTICS = "boolean_semantics"
TEMPORAL_WINDOW = "temporal_window"


class GoldenCriterionExpectation(BaseModel):
    """One human-reviewed top-level criterion and its matching hints."""

    model_config = ConfigDict(extra="forbid")

    expectation_id: str
    label: str
    match_groups: list[list[str]]
    expected: EligibilityCriterion


class GoldenCriteriaSet(BaseModel):
    """Human-reviewed expected criteria for one trial population."""

    model_config = ConfigDict(extra="forbid")

    trial_id: str
    target_population: str
    excluded_population: str
    excluded_population_markers: list[str]
    criteria: list[GoldenCriterionExpectation]


class FieldComparison(BaseModel):
    """One semantic field comparison within a matched criterion."""

    model_config = ConfigDict(extra="forbid")

    path: str
    field_name: str
    expected: str
    actual: str
    passed: bool
    metric_group: str | None = None


class CriterionComparison(BaseModel):
    """Detailed result for one expected top-level criterion."""

    model_config = ConfigDict(extra="forbid")

    expectation_id: str
    label: str
    matched: bool
    actual_criterion_id: str | None = None
    field_comparisons: list[FieldComparison] = Field(default_factory=list)


class AccuracyMetric(BaseModel):
    """Aggregate accuracy for one structural concern."""

    model_config = ConfigDict(extra="forbid")

    passed_checks: int
    total_checks: int
    accuracy_percent: float | None
    status: str
    quality: str


class CriteriaEvaluationReport(BaseModel):
    """Coverage, aggregate accuracy, and field-level structure for one run."""

    model_config = ConfigDict(extra="forbid")

    expected_count: int
    found_count: int
    matched_count: int
    matched_criteria: list[str]
    missed_criteria: list[str]
    unexpected_criteria: list[str]
    structural_errors: list[str]
    population_leakage: list[str]
    field_mapping_accuracy: AccuracyMetric
    threshold_accuracy: AccuracyMetric
    logical_structure_accuracy: AccuracyMetric
    required_patient_fields_accuracy: AccuracyMetric
    boolean_semantics_accuracy: AccuracyMetric
    temporal_window_accuracy: AccuracyMetric
    criterion_comparisons: list[CriterionComparison]


def load_golden_criteria(path: Path) -> GoldenCriteriaSet:
    """Load and validate a human-reviewed golden JSON file."""

    return GoldenCriteriaSet.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_criteria(
    extracted: list[EligibilityCriterion], golden: GoldenCriteriaSet
) -> CriteriaEvaluationReport:
    """Match top-level criteria semantically, then compare important structure."""

    remaining = list(extracted)
    matched_ids: list[str] = []
    missed: list[str] = []
    structural_errors: list[str] = []
    comparisons: list[CriterionComparison] = []

    for expectation in golden.criteria:
        match = _best_match(expectation, remaining)
        if match is None:
            missed.append(_expectation_name(expectation))
            comparisons.append(
                CriterionComparison(
                    expectation_id=expectation.expectation_id,
                    label=expectation.label,
                    matched=False,
                )
            )
            continue

        remaining.remove(match)
        matched_ids.append(_expectation_name(expectation))
        field_comparisons: list[FieldComparison] = []
        _compare_structure(
            expectation.expected,
            match,
            expectation.expectation_id,
            structural_errors,
            field_comparisons,
        )
        comparisons.append(
            CriterionComparison(
                expectation_id=expectation.expectation_id,
                label=expectation.label,
                matched=True,
                actual_criterion_id=match.criterion_id,
                field_comparisons=field_comparisons,
            )
        )

    unexpected = [_criterion_name(criterion) for criterion in remaining]
    leakage = [
        _criterion_name(criterion)
        for criterion in remaining
        if _contains_population_marker(
            criterion.original_text, golden.excluded_population_markers
        )
    ]
    all_fields = [
        field for comparison in comparisons for field in comparison.field_comparisons
    ]
    return CriteriaEvaluationReport(
        expected_count=len(golden.criteria),
        found_count=len(extracted),
        matched_count=len(matched_ids),
        matched_criteria=matched_ids,
        missed_criteria=missed,
        unexpected_criteria=unexpected,
        structural_errors=structural_errors,
        population_leakage=leakage,
        field_mapping_accuracy=_accuracy(all_fields, FIELD_MAPPING),
        threshold_accuracy=_accuracy(all_fields, THRESHOLD),
        logical_structure_accuracy=_accuracy(all_fields, LOGICAL_STRUCTURE),
        required_patient_fields_accuracy=_accuracy(all_fields, REQUIRED_PATIENT_FIELDS),
        boolean_semantics_accuracy=_accuracy(all_fields, BOOLEAN_SEMANTICS),
        temporal_window_accuracy=_accuracy(all_fields, TEMPORAL_WINDOW),
        criterion_comparisons=comparisons,
    )


def format_evaluation_report(report: CriteriaEvaluationReport) -> str:
    """Render a console-friendly summary and field-wise PASS/FAIL report."""

    lines = [
        "NCT07438444 CRITERIA EXTRACTION GOLDEN EVALUATION",
        "=" * 52,
        f"Expected: {report.expected_count}",
        f"Found: {report.found_count}",
        f"Matched: {report.matched_count}",
        f"Missed: {len(report.missed_criteria)}",
        f"Unexpected: {len(report.unexpected_criteria)}",
        f"Population leakage: {len(report.population_leakage)}",
        "",
        "AGGREGATE ACCURACY",
        "-" * 52,
        _metric_line("Field mapping accuracy", report.field_mapping_accuracy),
        _metric_line("Threshold accuracy", report.threshold_accuracy),
        _metric_line("Logical structure", report.logical_structure_accuracy),
        _metric_line(
            "Required patient fields",
            report.required_patient_fields_accuracy,
        ),
        _metric_line(
            "Boolean semantics",
            report.boolean_semantics_accuracy,
            use_quality=True,
        ),
        _metric_line("Temporal windows", report.temporal_window_accuracy),
        "",
        "DETAILED FIELD-WISE COMPARISON",
        "-" * 52,
    ]

    for comparison in report.criterion_comparisons:
        match_status = "MATCHED" if comparison.matched else "MISSED"
        actual_id = (
            f" -> {comparison.actual_criterion_id}"
            if comparison.actual_criterion_id
            else ""
        )
        lines.append(
            f"[{match_status}] {comparison.expectation_id}: "
            f"{comparison.label}{actual_id}"
        )
        for field in comparison.field_comparisons:
            status = "PASS" if field.passed else "FAIL"
            lines.append(
                f"  [{status}] {field.path}.{field.field_name}: "
                f"expected={field.expected}; actual={field.actual}"
            )
        lines.append("")

    if report.missed_criteria:
        lines.append("MISSED CRITERIA")
        lines.extend(f"  - {item}" for item in report.missed_criteria)
        lines.append("")
    if report.unexpected_criteria:
        lines.append("UNEXPECTED CRITERIA")
        lines.extend(f"  - {item}" for item in report.unexpected_criteria)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _best_match(
    expectation: GoldenCriterionExpectation,
    candidates: list[EligibilityCriterion],
) -> EligibilityCriterion | None:
    eligible = [
        candidate
        for candidate in candidates
        if _matches_groups(candidate.original_text, expectation.match_groups)
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda candidate: _text_similarity(
            expectation.expected.original_text, candidate.original_text
        ),
    )


def _matches_groups(text: str, groups: list[list[str]]) -> bool:
    normalized = _normalize(text)
    return all(
        any(_normalize(option) in normalized for option in alternatives)
        for alternatives in groups
    )


def _text_similarity(left: str, right: str) -> float:
    left_words = set(_normalize(left).split())
    right_words = set(_normalize(right).split())
    union = left_words | right_words
    if not union:
        return 0.0
    return len(left_words & right_words) / len(union)


def _compare_structure(
    expected: EligibilityCriterion,
    actual: EligibilityCriterion | None,
    path: str,
    errors: list[str],
    fields: list[FieldComparison],
    inherited_actual_temporal: object | None = None,
) -> None:
    _record_field(
        fields,
        errors,
        path,
        "criterion_type",
        expected.criterion_type,
        _actual(actual, "criterion_type"),
    )
    _record_field(
        fields,
        errors,
        path,
        "category",
        expected.category,
        _actual(actual, "category"),
    )

    evaluation_metric = None
    if expected.evaluation_type is EvaluationType.BOOLEAN:
        evaluation_metric = BOOLEAN_SEMANTICS
    elif expected.evaluation_type is EvaluationType.COMPOUND:
        evaluation_metric = LOGICAL_STRUCTURE
    _record_field(
        fields,
        errors,
        path,
        "evaluation_type",
        expected.evaluation_type,
        _actual(actual, "evaluation_type"),
        evaluation_metric,
    )

    if expected.field_name is not None or _actual(actual, "field_name") is not None:
        _record_field(
            fields,
            errors,
            path,
            "field_name",
            expected.field_name,
            _actual(actual, "field_name"),
            FIELD_MAPPING if expected.field_name is not None else None,
        )

    _compare_rule_fields(
        expected,
        actual,
        path,
        errors,
        fields,
        inherited_actual_temporal,
    )

    expected_required = sorted(expected.required_patient_fields)
    actual_required = sorted(actual.required_patient_fields) if actual else []
    if expected_required or actual_required:
        _record_field(
            fields,
            errors,
            path,
            "required_patient_fields",
            expected_required,
            actual_required,
            REQUIRED_PATIENT_FIELDS if expected_required else None,
        )

    expected_child_count = len(expected.children)
    actual_child_count = len(actual.children) if actual else 0
    if expected_child_count or actual_child_count:
        _record_field(
            fields,
            errors,
            path,
            "children_count",
            expected_child_count,
            actual_child_count,
            LOGICAL_STRUCTURE
            if expected.evaluation_type is EvaluationType.COMPOUND
            else None,
        )

    for index, expected_child in enumerate(expected.children, start=1):
        actual_child = (
            actual.children[index - 1]
            if actual is not None and len(actual.children) >= index
            else None
        )
        _compare_structure(
            expected_child,
            actual_child,
            f"{path}.children[{index}]",
            errors,
            fields,
            actual.temporal_window or inherited_actual_temporal if actual else None,
        )


def _compare_rule_fields(
    expected: EligibilityCriterion,
    actual: EligibilityCriterion | None,
    path: str,
    errors: list[str],
    fields: list[FieldComparison],
    inherited_actual_temporal: object | None,
) -> None:
    for field_name in ("operator", "value", "lower_value", "upper_value", "unit"):
        expected_value = getattr(expected, field_name)
        actual_value = _actual(actual, field_name)
        if expected_value is None and (actual is None or actual_value is None):
            continue

        metric_group = None
        if expected.evaluation_type is EvaluationType.NUMERIC:
            metric_group = THRESHOLD
        elif expected.evaluation_type is EvaluationType.BOOLEAN and field_name in {
            "operator",
            "value",
        }:
            metric_group = BOOLEAN_SEMANTICS
        _record_field(
            fields,
            errors,
            path,
            field_name,
            expected_value,
            actual_value,
            metric_group,
        )

    expected_temporal = expected.temporal_window
    direct_actual_temporal = actual.temporal_window if actual else None
    actual_temporal = direct_actual_temporal or inherited_actual_temporal
    if expected_temporal is not None or actual_temporal is not None:
        _record_field(
            fields,
            errors,
            path,
            "temporal_window",
            expected_temporal,
            (
                actual_temporal
                if direct_actual_temporal is not None or actual_temporal is None
                else _InheritedTemporal(actual_temporal)
            ),
            TEMPORAL_WINDOW if expected_temporal is not None else None,
        )

    expected_logical = expected.logical_operator
    actual_logical = actual.logical_operator if actual else None
    if expected_logical is not None or actual_logical is not None:
        _record_field(
            fields,
            errors,
            path,
            "logical_operator",
            expected_logical,
            actual_logical,
            LOGICAL_STRUCTURE if expected_logical is not None else None,
        )


def _record_field(
    fields: list[FieldComparison],
    errors: list[str],
    path: str,
    field_name: str,
    expected: object,
    actual: object,
    metric_group: str | None = None,
) -> None:
    passed = _same_value(expected, actual)
    expected_display = _display(expected)
    actual_display = _display(actual)
    fields.append(
        FieldComparison(
            path=path,
            field_name=field_name,
            expected=expected_display,
            actual=actual_display,
            passed=passed,
            metric_group=metric_group,
        )
    )
    if not passed:
        errors.append(
            f"{path}.{field_name}: expected {expected_display}, got {actual_display}"
        )


def _accuracy(fields: list[FieldComparison], metric_group: str) -> AccuracyMetric:
    checks = [field for field in fields if field.metric_group == metric_group]
    passed = sum(field.passed for field in checks)
    total = len(checks)
    if total == 0:
        return AccuracyMetric(
            passed_checks=0,
            total_checks=0,
            accuracy_percent=None,
            status="N/A",
            quality="not_applicable",
        )

    percent = round((passed / total) * 100, 1)
    if percent >= 90:
        quality = "good"
    elif percent >= 70:
        quality = "fair"
    else:
        quality = "poor"
    return AccuracyMetric(
        passed_checks=passed,
        total_checks=total,
        accuracy_percent=percent,
        status="PASS" if passed == total else "FAIL",
        quality=quality,
    )


def _metric_line(
    label: str, metric: AccuracyMetric, *, use_quality: bool = False
) -> str:
    if metric.accuracy_percent is None:
        return f"{label}: N/A (0 checks)"
    suffix = metric.quality.upper() if use_quality else metric.status
    return (
        f"{label}: {metric.accuracy_percent:.1f}% "
        f"({metric.passed_checks}/{metric.total_checks}) {suffix}"
    )


def _actual(actual: EligibilityCriterion | None, field_name: str) -> object:
    if actual is None:
        return "<missing>"
    return getattr(actual, field_name)


def _same_value(expected: object, actual: object) -> bool:
    if isinstance(actual, _InheritedTemporal):
        actual = actual.value
    if isinstance(expected, bool) or isinstance(actual, bool):
        return (
            isinstance(expected, bool)
            and isinstance(actual, bool)
            and expected == actual
        )
    expected_number = _as_decimal(expected)
    actual_number = _as_decimal(actual)
    if expected_number is not None and actual_number is not None:
        return expected_number == actual_number
    return expected == actual


def _as_decimal(value: object) -> Decimal | None:
    if not isinstance(value, Decimal | int | float | str) or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _display(value: object) -> str:
    if isinstance(value, _InheritedTemporal):
        return f"inherited {_display(value.value)}"
    if isinstance(value, BaseModel):
        return repr(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return repr(value.value)
    if isinstance(value, Decimal):
        return repr(str(value))
    if isinstance(value, list):
        return repr([item.value if isinstance(item, Enum) else item for item in value])
    return repr(value)


class _InheritedTemporal:
    """Display marker for a temporal window inherited from a compound parent."""

    def __init__(self, value: object) -> None:
        self.value = value


def _contains_population_marker(text: str, markers: list[str]) -> bool:
    normalized = _normalize(text)
    return any(_normalize(marker) in normalized for marker in markers)


def _expectation_name(expectation: GoldenCriterionExpectation) -> str:
    return f"{expectation.expectation_id}: {expectation.label}"


def _criterion_name(criterion: EligibilityCriterion) -> str:
    return f"{criterion.criterion_id}: {criterion.original_text}"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
