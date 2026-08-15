"""Deterministic criterion-level evaluation with three-valued compound logic."""

from datetime import date
from decimal import Decimal, InvalidOperation

from clinical_trial_prescreener.domain.assessment import (
    CriterionAssessment,
    CriterionStatus,
    EvaluationMethod,
)
from clinical_trial_prescreener.domain.criterion import (
    ComparisonOperator,
    EligibilityCriterion,
    EvaluationType,
    LogicalOperator,
    TemporalWindow,
)
from clinical_trial_prescreener.domain.patient import PatientProfile
from clinical_trial_prescreener.services.patient_fact_resolver import (
    PatientFactResolver,
)


class EligibilityEvaluator:
    """Evaluate criterion truth only; trial-level eligibility remains out of scope."""

    def __init__(self, *, reference_date: date | None = None) -> None:
        self._resolver = PatientFactResolver(reference_date=reference_date)

    def evaluate(
        self, criterion: EligibilityCriterion, patient: PatientProfile
    ) -> CriterionAssessment:
        return self._evaluate(criterion, patient, inherited_temporal_window=None)

    def _evaluate(
        self,
        criterion: EligibilityCriterion,
        patient: PatientProfile,
        inherited_temporal_window: TemporalWindow | None,
    ) -> CriterionAssessment:
        if criterion.evaluation_type is EvaluationType.COMPOUND:
            return self._evaluate_compound(
                criterion, patient, inherited_temporal_window
            )
        if criterion.evaluation_type in {EvaluationType.SEMANTIC, EvaluationType.HUMAN_ONLY}:
            if _is_unsupported_deterministic_source(criterion.original_text):
                return self._unknown(
                    criterion,
                    method=EvaluationMethod.DETERMINISTIC,
                    missing=_concrete_missing_information(criterion.original_text),
                    reason="Structured patient evidence is unavailable for this criterion.",
                    requires_human_review=False,
                )
            return self._unknown(
                criterion,
                method=(
                    EvaluationMethod.SEMANTIC_LLM
                    if criterion.evaluation_type is EvaluationType.SEMANTIC
                    else EvaluationMethod.HUMAN
                ),
                missing=_concrete_missing_information(criterion.original_text),
                reason="Criterion requires semantic or human evaluation.",
                requires_human_review=True,
            )
        if criterion.field_name is None:
            return self._unknown(
                criterion,
                method=EvaluationMethod.HUMAN,
                missing=criterion.required_patient_fields
                or _concrete_missing_information(criterion.original_text),
                reason="Criterion has no safely mapped canonical patient fact.",
                requires_human_review=criterion.requires_human_review,
            )

        temporal_window = criterion.temporal_window or inherited_temporal_window
        fact_name = (
            "other_systemic_conditions"
            if _requires_other_systemic_conditions(criterion.original_text)
            else criterion.field_name
        )
        fact = self._resolver.resolve(
            patient, fact_name, temporal_window=temporal_window
        )
        if not fact.is_known:
            return self._unknown(
                criterion,
                method=EvaluationMethod.DETERMINISTIC,
                missing=fact.missing_information,
                reason=f"Required fact {fact_name} is unavailable.",
                patient_evidence=fact.patient_evidence,
            )
        status = _compare(criterion, fact.value)
        if status is CriterionStatus.UNKNOWN:
            return self._unknown(
                criterion,
                method=EvaluationMethod.DETERMINISTIC,
                missing=["valid deterministic operator and comparison value"],
                reason="Criterion cannot be compared with its supplied rule fields.",
            )
        return CriterionAssessment(
            criterion_id=criterion.criterion_id,
            criterion_type=criterion.criterion_type,
            status=status,
            reason=(
                f"{fact_name}={fact.value!r} "
                f"{_operator_text(criterion.operator)} criterion value."
            ),
            trial_evidence=criterion.original_text,
            patient_evidence=fact.patient_evidence,
            evaluation_method=EvaluationMethod.DETERMINISTIC,
            requires_human_review=criterion.requires_human_review,
        )

    def _evaluate_compound(
        self,
        criterion: EligibilityCriterion,
        patient: PatientProfile,
        inherited_temporal_window: TemporalWindow | None,
    ) -> CriterionAssessment:
        effective_window = criterion.temporal_window or inherited_temporal_window
        children = [
            self._evaluate(child, patient, effective_window)
            for child in criterion.children
        ]
        status = _combine_statuses(
            [child.status for child in children], criterion.logical_operator
        )
        missing = sorted(
            {item for child in children for item in child.missing_information}
        )
        return CriterionAssessment(
            criterion_id=criterion.criterion_id,
            criterion_type=criterion.criterion_type,
            status=status,
            reason=(
                f"{criterion.logical_operator.value} child statuses: "
                + ", ".join(child.status.value for child in children)
            ),
            trial_evidence=criterion.original_text,
            patient_evidence="; ".join(
                evidence
                for child in children
                if (evidence := child.patient_evidence) is not None
            )
            or None,
            missing_information=missing if status is CriterionStatus.UNKNOWN else [],
            evaluation_method=EvaluationMethod.COMPOUND,
            requires_human_review=(
                criterion.requires_human_review
                or any(child.requires_human_review for child in children)
            ),
        )

    @staticmethod
    def _unknown(
        criterion: EligibilityCriterion,
        *,
        method: EvaluationMethod,
        missing: list[str],
        reason: str,
        requires_human_review: bool | None = None,
        patient_evidence: str | None = None,
    ) -> CriterionAssessment:
        return CriterionAssessment(
            criterion_id=criterion.criterion_id,
            criterion_type=criterion.criterion_type,
            status=CriterionStatus.UNKNOWN,
            reason=reason,
            trial_evidence=criterion.original_text,
            patient_evidence=patient_evidence,
            missing_information=missing,
            evaluation_method=method,
            requires_human_review=(
                criterion.requires_human_review
                if requires_human_review is None
                else requires_human_review
            ),
        )


def _compare(criterion: EligibilityCriterion, actual: Decimal | bool | str) -> CriterionStatus:
    operator = criterion.operator
    if operator is None:
        return CriterionStatus.UNKNOWN
    if operator in {ComparisonOperator.IN, ComparisonOperator.NOT_IN}:
        expected = criterion.value if isinstance(criterion.value, list) else []
        result = actual in expected
        return _status(not result if operator is ComparisonOperator.NOT_IN else result)
    if operator in {ComparisonOperator.BETWEEN, ComparisonOperator.BETWEEN_INCLUSIVE}:
        actual_number = _decimal(actual)
        if actual_number is None or criterion.lower_value is None or criterion.upper_value is None:
            return CriterionStatus.UNKNOWN
        if operator is ComparisonOperator.BETWEEN:
            return _status(criterion.lower_value < actual_number < criterion.upper_value)
        return _status(criterion.lower_value <= actual_number <= criterion.upper_value)

    expected = criterion.value
    if operator in {ComparisonOperator.EQ, ComparisonOperator.NE}:
        result = actual == expected
        return _status(not result if operator is ComparisonOperator.NE else result)
    actual_number = _decimal(actual)
    expected_number = _decimal(expected)
    if actual_number is None or expected_number is None:
        return CriterionStatus.UNKNOWN
    comparisons = {
        ComparisonOperator.GT: actual_number > expected_number,
        ComparisonOperator.GTE: actual_number >= expected_number,
        ComparisonOperator.LT: actual_number < expected_number,
        ComparisonOperator.LTE: actual_number <= expected_number,
    }
    return _status(comparisons.get(operator, False))


def _combine_statuses(
    statuses: list[CriterionStatus], logical_operator: LogicalOperator | None
) -> CriterionStatus:
    if logical_operator is LogicalOperator.AND:
        if CriterionStatus.NOT_MET in statuses:
            return CriterionStatus.NOT_MET
        if CriterionStatus.UNKNOWN in statuses:
            return CriterionStatus.UNKNOWN
        return CriterionStatus.MET
    if logical_operator is LogicalOperator.OR:
        if CriterionStatus.MET in statuses:
            return CriterionStatus.MET
        if CriterionStatus.UNKNOWN in statuses:
            return CriterionStatus.UNKNOWN
        return CriterionStatus.NOT_MET
    return CriterionStatus.UNKNOWN


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _status(value: bool) -> CriterionStatus:
    return CriterionStatus.MET if value else CriterionStatus.NOT_MET


def _operator_text(operator: ComparisonOperator | None) -> str:
    return operator.value if operator is not None else "cannot be compared to"


def _requires_other_systemic_conditions(source_text: str) -> bool:
    """Recognize the precise exclusion that cannot be inferred from Type 2 Diabetes."""

    normalized = " ".join(source_text.casefold().split())
    return (
        "systemic condition" in normalized
        and "other than" in normalized
        and "type 2 diabetes" in normalized
    )


def _is_unsupported_deterministic_source(source_text: str) -> bool:
    """Recognize source statements that need structured data, not clinical judgment."""

    text = " ".join(source_text.casefold().split())
    return any(
        marker in text
        for marker in (
            "medical history of hypertension",
            "active pharmacological treatment",
            "atrial fibrillation",
            "atrial flutter",
            "mineralocorticoid receptor antagonist",
            "potassium-sparing diuretic",
            "direct renin inhibitor",
        )
    )


def _concrete_missing_information(source_text: str) -> list[str]:
    text = " ".join(source_text.casefold().split())
    if "informed consent" in text or "written consent" in text:
        return ["signed and dated trial-specific informed consent"]
    if "birth control" in text or "childbearing potential" in text:
        return ["study-required contraception confirmation"]
    if "hypertension" in text:
        return ["medical_history: hypertension diagnosis"]
    if "type 2 diabetes" in text and "treatment" in text:
        return ["medications: active Type 2 Diabetes treatment"]
    if "cardiovascular" in text:
        return ["medications: active cardiovascular treatment"]
    if "atrial fibrillation" in text or "atrial flutter" in text:
        return ["medical_history and screening ECG: atrial rhythm and heart rate"]
    if any(marker in text for marker in ("antagonist", "diuretic", "renin inhibitor")):
        return ["medications: current use of the listed treatment"]
    return ["structured patient evidence required for this trial criterion"]
