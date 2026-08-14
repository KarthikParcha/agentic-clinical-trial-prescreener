from decimal import Decimal

import pytest
from pydantic import ValidationError

from clinical_trial_prescreener.domain.criterion import (
    ComparisonOperator,
    EligibilityCriterion,
    EvaluationType,
    LogicalOperator,
    TemporalUnit,
)


def atomic_criterion(**overrides: object) -> EligibilityCriterion:
    data: dict[str, object] = {
        "criterion_id": "INC-001",
        "criterion_type": "INCLUSION",
        "category": "AGE",
        "original_text": "Participants must be at least 18 years old.",
        "evaluation_type": "NUMERIC",
        "field_name": "age",
        "operator": "GTE",
        "value": Decimal(18),
        "required_patient_fields": ["age"],
    }
    data.update(overrides)
    return EligibilityCriterion(**data)


def test_numeric_age_criterion() -> None:
    criterion = atomic_criterion()

    assert criterion.operator is ComparisonOperator.GTE
    assert criterion.value == Decimal(18)
    assert criterion.required_patient_fields == ["age"]


def test_hba1c_range_criterion() -> None:
    criterion = atomic_criterion(
        criterion_id="INC-002",
        category="LAB",
        original_text="HbA1c must be between 7.5% and 10% at screening.",
        field_name="hba1c",
        operator="BETWEEN_INCLUSIVE",
        value=None,
        lower_value=Decimal("7.5"),
        upper_value=Decimal(10),
        unit="%",
        required_patient_fields=["laboratory_results.hba1c"],
    )

    assert criterion.lower_value == Decimal("7.5")
    assert criterion.upper_value == Decimal(10)
    assert criterion.operator is ComparisonOperator.BETWEEN_INCLUSIVE


def test_bmi_threshold_criterion() -> None:
    criterion = atomic_criterion(
        criterion_id="INC-003",
        category="BMI",
        original_text="BMI must be at least 23 kg/m2.",
        field_name="bmi",
        value=Decimal(23),
        unit="kg/m2",
        required_patient_fields=["bmi"],
    )

    assert criterion.value == Decimal(23)
    assert criterion.unit == "kg/m2"


def test_boolean_pregnancy_criterion() -> None:
    criterion = atomic_criterion(
        criterion_id="EXC-001",
        criterion_type="EXCLUSION",
        category="PREGNANCY",
        original_text="Pregnancy is excluded.",
        evaluation_type="BOOLEAN",
        field_name="pregnancy_status",
        operator="EQ",
        value=True,
        required_patient_fields=["pregnancy_status"],
    )

    assert criterion.value is True
    assert criterion.evaluation_type is EvaluationType.BOOLEAN


def test_temporal_recent_event_criterion() -> None:
    criterion = atomic_criterion(
        criterion_id="EXC-002",
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text="No heart attack within 6 months before screening.",
        evaluation_type="TEMPORAL",
        field_name="medical_history.heart_attack_date",
        operator="NOT_EXISTS",
        value=None,
        temporal_window={"value": Decimal(6), "unit": "MONTH"},
        required_patient_fields=["medical_history.heart_attack_date"],
    )

    assert criterion.temporal_window is not None
    assert criterion.temporal_window.value == Decimal(6)
    assert criterion.temporal_window.unit is TemporalUnit.MONTH


def test_semantic_medically_stable_criterion() -> None:
    criterion = atomic_criterion(
        criterion_id="INC-004",
        category="MEDICAL_HISTORY",
        original_text="Participants must be medically stable.",
        evaluation_type="SEMANTIC",
        field_name=None,
        operator=None,
        value=None,
        required_patient_fields=["medical_history"],
        requires_human_review=True,
    )

    assert criterion.operator is None
    assert criterion.value is None
    assert criterion.requires_human_review is True


def test_human_only_criterion() -> None:
    criterion = atomic_criterion(
        criterion_id="INC-005",
        category="CONSENT",
        original_text="Investigator judges that participation is appropriate.",
        evaluation_type="HUMAN_ONLY",
        field_name=None,
        operator=None,
        value=None,
        required_patient_fields=[],
        requires_human_review=True,
    )

    assert criterion.evaluation_type is EvaluationType.HUMAN_ONLY
    assert criterion.field_name is None


@pytest.mark.parametrize("logical_operator", [LogicalOperator.AND, LogicalOperator.OR])
def test_valid_compound_criterion(logical_operator: LogicalOperator) -> None:
    criterion = EligibilityCriterion(
        criterion_id="INC-C01",
        criterion_type="INCLUSION",
        category="DIAGNOSIS",
        original_text="Type 2 Diabetes with HbA1c above 8%.",
        evaluation_type="COMPOUND",
        logical_operator=logical_operator,
        children=[
            atomic_criterion(
                criterion_id="INC-C01-A",
                category="DIAGNOSIS",
                original_text="Diagnosis of Type 2 Diabetes.",
                evaluation_type="CATEGORICAL",
                field_name="condition",
                operator="EQ",
                value="Type 2 Diabetes",
                required_patient_fields=["condition"],
            ),
            atomic_criterion(
                criterion_id="INC-C01-B",
                category="LAB",
                original_text="HbA1c above 8%.",
                field_name="hba1c",
                operator="GT",
                value=Decimal(8),
                unit="%",
                required_patient_fields=["laboratory_results.hba1c"],
            ),
        ],
        required_patient_fields=["condition", "laboratory_results.hba1c"],
    )

    assert criterion.logical_operator is logical_operator
    assert len(criterion.children) == 2


def test_compound_criterion_without_children_is_rejected() -> None:
    with pytest.raises(ValidationError, match="compound criterion must contain children"):
        EligibilityCriterion(
            criterion_id="INC-C02",
            criterion_type="INCLUSION",
            category="OTHER",
            original_text="A compound requirement.",
            evaluation_type="COMPOUND",
            logical_operator="AND",
        )


def test_compound_criterion_without_logical_operator_is_rejected() -> None:
    with pytest.raises(
        ValidationError, match="compound criterion must provide a logical_operator"
    ):
        EligibilityCriterion(
            criterion_id="INC-C03",
            criterion_type="INCLUSION",
            category="OTHER",
            original_text="A compound requirement.",
            evaluation_type="COMPOUND",
            children=[atomic_criterion()],
        )


def test_atomic_criterion_with_children_is_rejected() -> None:
    with pytest.raises(
        ValidationError, match="non-compound criterion must not contain children"
    ):
        atomic_criterion(children=[atomic_criterion(criterion_id="INC-CHILD")])


def test_blank_criterion_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        atomic_criterion(criterion_id="  ")


def test_blank_original_text_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        atomic_criterion(original_text="  ")


def test_unexpected_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EligibilityCriterion(
            criterion_id="INC-006",
            criterion_type="INCLUSION",
            category="OTHER",
            original_text="A valid source criterion.",
            evaluation_type="SEMANTIC",
            confidence=0.9,
        )


def test_missing_deterministic_values_are_allowed_for_semantic_criterion() -> None:
    criterion = EligibilityCriterion(
        criterion_id="INC-007",
        criterion_type="INCLUSION",
        category="MEDICAL_HISTORY",
        original_text="Participant must be medically stable.",
        evaluation_type="SEMANTIC",
    )

    assert criterion.field_name is None
    assert criterion.operator is None
    assert criterion.value is None


def test_required_patient_fields_are_preserved() -> None:
    fields = ["medical_history.heart_attack_date", "medical_history.stroke_date"]
    criterion = atomic_criterion(required_patient_fields=fields)

    assert criterion.required_patient_fields == fields
