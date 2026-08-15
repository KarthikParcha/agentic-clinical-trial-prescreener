import asyncio
import json
from collections.abc import Awaitable
from typing import Any

import pytest

from clinical_trial_prescreener.domain.criterion import (
    ComparisonOperator,
    CriterionType,
    EligibilityCriterion,
    EvaluationType,
    LogicalOperator,
    TemporalUnit,
)
from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    StudyType,
    TrialStatus,
)
from clinical_trial_prescreener.infrastructure.llm.groq_client import GroqClientError
from clinical_trial_prescreener.services.criteria_extraction import (
    CriteriaExtractionError,
    CriteriaExtractionService,
    ExtractionFailureCategory,
    _SourceEvidenceError,
    _validate_source_evidence,
)

ELIGIBILITY_TEXT = """Inclusion Criteria:
Participants must have an HbA1c between 7.5% and 10% at screening.
Participants must have BMI at least 23 kg/m2.
Participants must be medically stable.
Type 2 Diabetes with HbA1c above 8%.
Diagnosis of Type 2 Diabetes.
HbA1c above 8%.

Exclusion Criteria:
Participants with Type 1 Diabetes are excluded.
Heart attack or stroke within 6 months before screening.
Heart attack within 6 months before screening.
Stroke within 6 months before screening.
"""

def run(coroutine: Awaitable[Any]) -> Any:
    return asyncio.run(coroutine)


class StubGeneratedContentClient:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, str]] = []
        self._response_index = 0

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        call = {"system_prompt": system_prompt, "user_prompt": user_prompt}
        self.calls.append(call)
        response = self.responses[self._response_index]
        self._response_index += 1
        if isinstance(response, Exception):
            raise response
        return response


class RateLimitCause(Exception):
    status_code = 429


def criterion(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "criterion_type": "INCLUSION",
        "category": "BMI",
        "original_text": "Participants must have BMI at least 23 kg/m2.",
        "evaluation_type": "NUMERIC",
        "field_name": "bmi",
        "operator": "GTE",
        "value": 23,
        "unit": "kg/m2",
        "required_patient_fields": ["bmi"],
    }
    data.update(overrides)
    return data


def output(*criteria: dict[str, object]) -> str:
    return json.dumps({"criteria": list(criteria)})


def service_with(
    *responses: str | Exception,
) -> tuple[CriteriaExtractionService, StubGeneratedContentClient]:
    client = StubGeneratedContentClient(list(responses))
    return CriteriaExtractionService(client), client


def json_generation_failure() -> GroqClientError:
    return GroqClientError(
        "Groq request failed",
        status_code=400,
        error_code="json_validate_failed",
    )


def test_valid_numeric_json_becomes_domain_criterion() -> None:
    service, _ = service_with(output(criterion()))

    result = run(
        service.extract_text(
            ELIGIBILITY_TEXT + "\nNYHA Class III or IV congestive heart failure."
        )
    )

    assert len(result) == 1
    assert isinstance(result[0], EligibilityCriterion)
    assert result[0].value == 23
    assert result[0].operator is ComparisonOperator.GTE


def test_hba1c_range_extraction_validates() -> None:
    hba1c = criterion(
        category="LAB",
        original_text=(
            "Participants must have an HbA1c between 7.5% and 10% at screening."
        ),
        field_name="hba1c",
        operator="BETWEEN_INCLUSIVE",
        value=None,
        lower_value=7.5,
        upper_value=10,
        unit="%",
        required_patient_fields=["laboratory_results.hba1c"],
    )
    service, _ = service_with(output(hba1c))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert str(result[0].lower_value) == "7.5"
    assert result[0].upper_value == 10
    assert result[0].operator is ComparisonOperator.BETWEEN_INCLUSIVE
    assert result[0].field_name == "hba1c"
    assert result[0].required_patient_fields == ["laboratory_results"]


def test_known_concepts_use_real_patientprofile_fields_and_union_requirements() -> None:
    heart_attack = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text="Heart attack within 6 months before screening.",
        evaluation_type="BOOLEAN",
        field_name="made_up.heart_attack",
        operator="EQ",
        value=True,
        unit=None,
    )
    stroke = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text="Stroke within 6 months before screening.",
        evaluation_type="BOOLEAN",
        field_name="made_up.stroke",
        operator="EQ",
        value=True,
        unit=None,
    )
    compound = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text="Heart attack or stroke within 6 months before screening.",
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=[heart_attack, stroke],
    )
    service, _ = service_with(output(compound))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert [child.field_name for child in result[0].children] == [
        "heart_attack",
        "stroke",
    ]
    assert result[0].required_patient_fields == ["medical_history"]


def test_unsafe_procedure_mapping_is_removed_and_marked_for_human_review() -> None:
    procedure = criterion(
        criterion_type="EXCLUSION",
        category="PROCEDURE",
        original_text="Bariatric surgery is being considered.",
        evaluation_type="BOOLEAN",
        field_name="procedures.bariatric_surgery_considered",
        operator="EQ",
        value=True,
        unit=None,
        required_patient_fields=["procedures.bariatric_surgery_considered"],
    )
    service, _ = service_with(output(procedure))

    result = run(service.extract_text("Bariatric surgery is being considered."))

    assert result[0].field_name is None
    assert result[0].required_patient_fields == []
    assert result[0].requires_human_review is True


def test_truth_oriented_boolean_values_and_categorical_alternatives_are_preserved() -> None:
    type_1_diabetes = criterion(
        criterion_type="EXCLUSION",
        category="DIAGNOSIS",
        original_text="Participants with Type 1 Diabetes are excluded.",
        evaluation_type="BOOLEAN",
        field_name="invented.type_1_diabetes",
        operator="EQ",
        value=True,
        unit=None,
    )
    heart_attack = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text="Heart attack within 6 months before screening.",
        evaluation_type="BOOLEAN",
        field_name="invented.heart_attack",
        operator="EQ",
        value=True,
        unit=None,
    )
    nyha = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text="NYHA Class III or IV congestive heart failure.",
        evaluation_type="CATEGORICAL",
        field_name="invented.nyha",
        operator="IN",
        value=["III", "IV"],
        unit=None,
    )
    service, _ = service_with(output(type_1_diabetes, heart_attack, nyha))

    result = run(
        service.extract_text(
            ELIGIBILITY_TEXT + "\nNYHA Class III or IV congestive heart failure."
        )
    )

    assert result[0].field_name == "type_1_diabetes"
    assert result[0].operator is ComparisonOperator.EQ
    assert result[0].value is True
    assert result[1].field_name == "heart_attack"
    assert result[1].operator is ComparisonOperator.EQ
    assert result[1].value is True
    assert result[2].field_name == "nyha_class"
    assert result[2].operator is ComparisonOperator.IN
    assert result[2].value == ["III", "IV"]


def test_duration_uses_a_canonical_numeric_fact_and_diagnosis_date() -> None:
    duration = criterion(
        category="DIAGNOSIS",
        original_text="Have had type 2 diabetes for at least one year.",
        evaluation_type="TEMPORAL",
        field_name="invented.duration",
        operator=None,
        value=None,
        unit=None,
        temporal_window={"value": 1, "unit": "YEAR"},
    )
    service, _ = service_with(output(duration))

    result = run(service.extract_text(duration["original_text"]))

    assert result[0].evaluation_type is EvaluationType.NUMERIC
    assert result[0].field_name == "diagnosis_duration_years"
    assert result[0].operator is ComparisonOperator.GTE
    assert result[0].value == 1
    assert result[0].unit == "year"
    assert result[0].temporal_window is None
    assert result[0].required_patient_fields == ["diagnosis_date"]


def test_nyha_or_children_normalize_to_one_categorical_fact() -> None:
    source = "NYHA Class III or IV congestive heart failure."
    nyha = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text=source,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=[
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Class III",
                evaluation_type="CATEGORICAL",
                field_name=None,
                operator="EQ",
                value="III",
                unit=None,
            ),
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Class IV",
                evaluation_type="CATEGORICAL",
                field_name=None,
                operator="EQ",
                value="IV",
                unit=None,
            ),
        ],
    )
    service, _ = service_with(output(nyha))

    result = run(service.extract_text(source))

    assert result[0].evaluation_type is EvaluationType.CATEGORICAL
    assert result[0].field_name == "nyha_class"
    assert result[0].operator is ComparisonOperator.IN
    assert result[0].value == ["III", "IV"]
    assert result[0].children == []


def test_unmapped_procedure_leaf_keeps_explicit_compound_structure() -> None:
    source = (
        "Have type 2 diabetes along with morbid obesity and being considered for "
        "bariatric surgery or any other procedure intended for weight loss."
    )
    procedure_children = [
        criterion(
            criterion_type="EXCLUSION",
            category="PROCEDURE",
            original_text="being considered for bariatric surgery",
            evaluation_type="BOOLEAN",
            field_name=None,
            operator="EQ",
            value=True,
            unit=None,
        ),
        criterion(
            criterion_type="EXCLUSION",
            category="PROCEDURE",
            original_text="any other procedure intended for weight loss",
            evaluation_type="BOOLEAN",
            field_name=None,
            operator="EQ",
            value=True,
            unit=None,
        ),
    ]
    procedure = criterion(
        criterion_type="EXCLUSION",
        category="PROCEDURE",
        original_text=(
            "being considered for bariatric surgery or any other procedure intended "
            "for weight loss"
        ),
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=procedure_children,
    )
    compound = criterion(
        criterion_type="EXCLUSION",
        category="DIAGNOSIS",
        original_text=source,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="AND",
        children=[
            criterion(
                criterion_type="EXCLUSION",
                category="DIAGNOSIS",
                original_text="type 2 diabetes",
                evaluation_type="BOOLEAN",
                field_name=None,
                operator="EQ",
                value=True,
                unit=None,
            ),
            criterion(
                criterion_type="EXCLUSION",
                category="DIAGNOSIS",
                original_text="morbid obesity",
                evaluation_type="BOOLEAN",
                field_name=None,
                operator="EQ",
                value=True,
                unit=None,
            ),
            procedure,
        ],
    )
    service, _ = service_with(output(compound))

    result = run(service.extract_text(source))

    assert result[0].evaluation_type is EvaluationType.COMPOUND
    assert result[0].logical_operator is LogicalOperator.AND
    assert result[0].children[2].logical_operator is LogicalOperator.OR
    assert result[0].children[0].field_name == "type_2_diabetes"
    assert result[0].children[1].field_name == "morbid_obesity"
    assert all(child.field_name is None for child in result[0].children[2].children)
    assert result[0].requires_human_review is True


def test_semantic_criterion_without_deterministic_fields_validates() -> None:
    semantic = criterion(
        category="MEDICAL_HISTORY",
        original_text="Participants must be medically stable.",
        evaluation_type="SEMANTIC",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        required_patient_fields=["medical_history"],
        requires_human_review=True,
    )
    service, _ = service_with(output(semantic))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert result[0].evaluation_type is EvaluationType.SEMANTIC
    assert result[0].field_name is None
    assert result[0].operator is None
    assert result[0].requires_human_review is True


def test_semantic_criterion_with_fake_deterministic_field_is_canonicalized() -> None:
    invalid_semantic = criterion(
        category="MEDICAL_HISTORY",
        original_text="Participants must be medically stable.",
        evaluation_type="SEMANTIC",
        field_name="medical_stability",
        operator=None,
        value=None,
        unit=None,
        requires_human_review=True,
    )
    service, client = service_with(output(invalid_semantic))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert result[0].field_name is None
    assert result[0].evaluation_type is EvaluationType.SEMANTIC
    assert len(client.calls) == 1
    assert [item.model_dump(mode="json") for item in service.last_canonicalizations] == [
        {
                "criterion_path": "criteria.0",
            "raw_evaluation_type": "SEMANTIC",
            "removed_fields": ["field_name"],
        }
    ]


def test_human_only_forbidden_fields_are_removed_before_domain_construction() -> None:
    source = "Subject has a contraindication for a MR examination."
    human_only = criterion(
        category="PROCEDURE",
        original_text=source,
        evaluation_type="HUMAN_ONLY",
        field_name="mri_contraindication",
        operator="BETWEEN",
        value="unsafe",
        lower_value=1,
        upper_value=2,
        unit="score",
        temporal_window={"value": 3, "unit": "MONTH"},
        required_patient_fields=["medical_history"],
        requires_human_review=True,
    )
    service, _ = service_with(output(human_only))

    result = run(service.extract_text(source))

    assert result[0].evaluation_type is EvaluationType.HUMAN_ONLY
    assert result[0].original_text == source
    assert result[0].field_name is None
    assert result[0].operator is None
    assert result[0].value is None
    assert result[0].lower_value is None
    assert result[0].upper_value is None
    assert result[0].unit is None
    assert result[0].temporal_window is None
    assert result[0].required_patient_fields == ["medical_history"]
    assert result[0].requires_human_review is True
    assert service.last_canonicalizations[0].removed_fields == [
        "field_name",
        "operator",
        "value",
        "lower_value",
        "upper_value",
        "unit",
        "temporal_window",
    ]


def test_boolean_deterministic_fields_are_not_removed() -> None:
    source = "Participants with Type 1 Diabetes are excluded."
    boolean = criterion(
        criterion_type="EXCLUSION",
        category="DIAGNOSIS",
        original_text=source,
        evaluation_type="BOOLEAN",
        field_name="type_1_diabetes",
        operator="EQ",
        value=True,
        unit=None,
    )
    service, _ = service_with(output(boolean))

    result = run(service.extract_text(source))

    assert result[0].evaluation_type is EvaluationType.BOOLEAN
    assert result[0].field_name == "type_1_diabetes"
    assert result[0].operator is ComparisonOperator.EQ
    assert result[0].value is True
    assert service.last_canonicalizations == []


def test_numeric_thresholds_are_preserved_by_dto_canonicalization() -> None:
    service, _ = service_with(output(criterion()))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert result[0].evaluation_type is EvaluationType.NUMERIC
    assert result[0].operator is ComparisonOperator.GTE
    assert result[0].value == 23
    assert result[0].unit == "kg/m2"
    assert service.last_canonicalizations == []


def test_nested_semantic_fields_are_canonicalized_recursively() -> None:
    source = (
        "Subject has metallic material in the body or any contraindication for a MR "
        "examination."
    )
    compound = criterion(
        criterion_type="EXCLUSION",
        category="PROCEDURE",
        original_text=source,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=[
            criterion(
                criterion_type="EXCLUSION",
                category="PROCEDURE",
                original_text="metallic material in the body",
                evaluation_type="HUMAN_ONLY",
                field_name="metal_in_body",
                operator="EQ",
                value=True,
                unit=None,
                requires_human_review=True,
            ),
            criterion(
                criterion_type="EXCLUSION",
                category="PROCEDURE",
                original_text="any contraindication for a MR examination",
                evaluation_type="SEMANTIC",
                field_name=None,
                operator=None,
                value=None,
                unit=None,
                requires_human_review=True,
            ),
        ],
    )
    service, _ = service_with(output(compound))

    result = run(service.extract_text(source))

    nested = result[0].children[0]
    assert nested.evaluation_type is EvaluationType.HUMAN_ONLY
    assert nested.original_text == "metallic material in the body"
    assert nested.field_name is None
    assert (
        service.last_canonicalizations[0].criterion_path
        == "criteria.0.children.0"
    )
    assert service.last_canonicalizations[0].raw_evaluation_type is EvaluationType.HUMAN_ONLY
    assert service.last_canonicalizations[0].removed_fields == [
        "field_name",
        "operator",
        "value",
    ]


def test_non_compound_with_children_still_fails_bounded_validation() -> None:
    unsafe = criterion(
        evaluation_type="HUMAN_ONLY",
        logical_operator="AND",
        children=[criterion()],
    )
    service, client = service_with(output(unsafe), output(unsafe))

    with pytest.raises(CriteriaExtractionError) as raised:
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert raised.value.category is ExtractionFailureCategory.REPAIR_EXHAUSTED
    assert raised.value.validation_category is ExtractionFailureCategory.SCHEMA_VALIDATION
    assert len(client.calls) == 2


def test_inclusion_exclusion_and_original_text_are_preserved() -> None:
    exclusion_text = "Participants with Type 1 Diabetes are excluded."
    exclusion = criterion(
        criterion_type="EXCLUSION",
        category="DIAGNOSIS",
        original_text=exclusion_text,
        evaluation_type="CATEGORICAL",
        field_name="diagnoses",
        operator="IN",
        value=["Type 1 Diabetes"],
        unit=None,
        required_patient_fields=["diagnoses"],
    )
    service, _ = service_with(output(criterion(), exclusion))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert [item.criterion_type for item in result] == [
        CriterionType.INCLUSION,
        CriterionType.EXCLUSION,
    ]
    assert result[1].original_text == exclusion_text


@pytest.mark.parametrize("logical_operator", ["AND", "OR"])
def test_compound_and_or_criterion_validates(logical_operator: str) -> None:
    if logical_operator == "AND":
        original_text = "Type 2 Diabetes with HbA1c above 8%."
        children = [
            criterion(
                category="DIAGNOSIS",
                original_text="Diagnosis of Type 2 Diabetes.",
                evaluation_type="CATEGORICAL",
                field_name="diagnoses",
                operator="IN",
                value=["Type 2 Diabetes"],
                unit=None,
            ),
            criterion(
                category="LAB",
                original_text="HbA1c above 8%.",
                field_name="hba1c",
                operator="GT",
                value=8,
                unit="%",
            ),
        ]
        criterion_type = "INCLUSION"
    else:
        original_text = "Heart attack or stroke within 6 months before screening."
        children = [
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Heart attack within 6 months before screening.",
                evaluation_type="TEMPORAL",
                field_name="medical_history.heart_attack_date",
                operator="EXISTS",
                value=None,
                unit=None,
                temporal_window={"value": 6, "unit": "MONTH"},
            ),
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Stroke within 6 months before screening.",
                evaluation_type="TEMPORAL",
                field_name="medical_history.stroke_date",
                operator="EXISTS",
                value=None,
                unit=None,
                temporal_window={"value": 6, "unit": "MONTH"},
            ),
        ]
        criterion_type = "EXCLUSION"

    compound = criterion(
        criterion_type=criterion_type,
        category="MEDICAL_HISTORY",
        original_text=original_text,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator=logical_operator,
        children=children,
    )
    service, _ = service_with(output(compound))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert result[0].logical_operator is LogicalOperator(logical_operator)
    assert len(result[0].children) == 2
    assert [child.criterion_id for child in result[0].children] == [
        f"{result[0].criterion_id}.1",
        f"{result[0].criterion_id}.2",
    ]


def test_ids_are_assigned_deterministically_by_type_and_source_order() -> None:
    exclusion = criterion(
        criterion_type="EXCLUSION",
        category="DIAGNOSIS",
        original_text="Participants with Type 1 Diabetes are excluded.",
    )
    service, _ = service_with(output(criterion(), exclusion, criterion(), exclusion))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert [item.criterion_id for item in result] == [
        "INC-001",
        "EXC-001",
        "INC-002",
        "EXC-002",
    ]


def test_malformed_json_triggers_one_repair_attempt() -> None:
    service, client = service_with("not-json", output(criterion()))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert [item.criterion_id for item in result] == ["INC-001"]
    assert len(client.calls) == 2
    assert "failed validation" in client.calls[1]["user_prompt"]
    assert "not-json" in client.calls[1]["user_prompt"]


def test_schema_invalid_json_triggers_one_repair_attempt() -> None:
    invalid = output(criterion(category="NOT_A_CATEGORY"))
    service, client = service_with(invalid, output(criterion()))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(result) == 1
    assert len(client.calls) == 2
    assert "NOT_A_CATEGORY" in client.calls[1]["user_prompt"]


def test_empty_compound_repair_prompt_has_path_rule_and_source_text() -> None:
    invalid_compound = criterion(
        criterion_type="EXCLUSION",
        original_text="Heart attack or stroke within 6 months before screening.",
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=[],
    )
    repaired = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text=invalid_compound["original_text"],
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=[
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Heart attack within 6 months before screening.",
                evaluation_type="BOOLEAN",
                field_name="heart_attack",
                operator="EQ",
                value=True,
                unit=None,
            ),
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Stroke within 6 months before screening.",
                evaluation_type="BOOLEAN",
                field_name="stroke",
                operator="EQ",
                value=True,
                unit=None,
            ),
        ],
    )
    service, client = service_with(output(invalid_compound), output(repaired))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    repair_prompt = client.calls[1]["user_prompt"]
    assert result[0].evaluation_type is EvaluationType.COMPOUND
    assert len(result[0].children) == 2
    assert "Failing criterion path: criteria.0" in repair_prompt
    assert "compound criterion must contain children" in repair_prompt
    assert invalid_compound["original_text"] in repair_prompt
    assert "logical_operator=AND or OR" in repair_prompt
    assert "at least 2 meaningful child criteria" in repair_prompt
    assert "do not invent children" in repair_prompt


def test_valid_compound_does_not_trigger_targeted_repair() -> None:
    source = "Heart attack or stroke within 6 months before screening."
    compound = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text=source,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=[
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Heart attack within 6 months before screening.",
                evaluation_type="BOOLEAN",
                field_name="heart_attack",
                operator="EQ",
                value=True,
                unit=None,
            ),
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Stroke within 6 months before screening.",
                evaluation_type="BOOLEAN",
                field_name="stroke",
                operator="EQ",
                value=True,
                unit=None,
            ),
        ],
    )
    service, client = service_with(output(compound))

    result = run(service.extract_text(source))

    assert result[0].logical_operator is LogicalOperator.OR
    assert len(result[0].children) == 2
    assert len(client.calls) == 1


def test_repair_with_invented_children_fails_source_traceability() -> None:
    source = "Participants must be medically stable."
    invalid_compound = criterion(
        category="MEDICAL_HISTORY",
        original_text=source,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="AND",
        children=[],
    )
    invented_children = {
        **invalid_compound,
        "children": [
            criterion(
                category="MEDICAL_HISTORY",
                original_text="Invented child criterion one.",
                evaluation_type="SEMANTIC",
                field_name=None,
                operator=None,
                value=None,
                unit=None,
                requires_human_review=True,
            ),
            criterion(
                category="MEDICAL_HISTORY",
                original_text="Invented child criterion two.",
                evaluation_type="SEMANTIC",
                field_name=None,
                operator=None,
                value=None,
                unit=None,
                requires_human_review=True,
            ),
        ],
    }
    service, client = service_with(output(invalid_compound), output(invented_children))

    with pytest.raises(CriteriaExtractionError) as raised:
        run(service.extract_text(source))

    assert raised.value.category is ExtractionFailureCategory.REPAIR_EXHAUSTED
    assert raised.value.validation_category is ExtractionFailureCategory.SOURCE_TRACEABILITY
    assert len(client.calls) == 2


def test_nested_empty_compound_reports_nested_path_in_repair_prompt() -> None:
    source = "Heart attack or stroke within 6 months before screening."
    nested_invalid = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text=source,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=[
            criterion(
                criterion_type="EXCLUSION",
                category="MEDICAL_HISTORY",
                original_text="Heart attack or stroke",
                evaluation_type="COMPOUND",
                field_name=None,
                operator=None,
                value=None,
                unit=None,
                logical_operator="OR",
                children=[],
            )
        ],
    )
    service, client = service_with(output(nested_invalid), output(nested_invalid))

    with pytest.raises(CriteriaExtractionError):
        run(service.extract_text(source))

    assert "Failing criterion path: criteria.0.children.0" in client.calls[1][
        "user_prompt"
    ]


def test_unsuccessful_empty_compound_repair_still_fails_closed() -> None:
    invalid_compound = criterion(
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="AND",
        children=[],
    )
    service, client = service_with(output(invalid_compound), output(invalid_compound))

    with pytest.raises(CriteriaExtractionError) as raised:
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert raised.value.category is ExtractionFailureCategory.REPAIR_EXHAUSTED
    assert raised.value.validation_category is ExtractionFailureCategory.SCHEMA_VALIDATION
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("raw_unit", "expected_unit"),
    [
        ("month", TemporalUnit.MONTH),
        ("months", TemporalUnit.MONTH),
        ("Months", TemporalUnit.MONTH),
        ("MONTH", TemporalUnit.MONTH),
        ("years", TemporalUnit.YEAR),
        ("weeks", TemporalUnit.WEEK),
        ("days", TemporalUnit.DAY),
    ],
)
def test_temporal_unit_aliases_are_canonicalized_before_validation(
    raw_unit: str, expected_unit: TemporalUnit
) -> None:
    temporal = criterion(temporal_window={"value": 6, "unit": raw_unit})
    service, client = service_with(output(temporal))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert result[0].temporal_window is not None
    assert result[0].temporal_window.unit is expected_unit
    assert result[0].temporal_window.value == 6
    assert len(client.calls) == 1


def test_unsupported_temporal_unit_remains_a_schema_validation_failure() -> None:
    unsupported = output(criterion(temporal_window={"value": 6, "unit": "quarter"}))
    service, client = service_with(unsupported, unsupported)

    with pytest.raises(CriteriaExtractionError) as raised:
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert raised.value.category is ExtractionFailureCategory.REPAIR_EXHAUSTED
    assert raised.value.validation_category is ExtractionFailureCategory.SCHEMA_VALIDATION
    assert len(client.calls) == 2


def test_nested_child_temporal_unit_is_canonicalized_without_changing_value() -> None:
    source_text = "Heart attack within 6 months before screening."
    child = criterion(
        category="MEDICAL_HISTORY",
        original_text=source_text,
        evaluation_type="BOOLEAN",
        field_name="heart_attack",
        operator="EQ",
        value=True,
        unit=None,
        temporal_window={"value": 6, "unit": "months"},
    )
    compound = criterion(
        category="MEDICAL_HISTORY",
        original_text=source_text,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="AND",
        children=[child],
    )
    service, _ = service_with(output(compound))

    result = run(service.extract_text(source_text))

    nested_window = result[0].children[0].temporal_window
    assert nested_window is not None
    assert nested_window.unit is TemporalUnit.MONTH
    assert nested_window.value == 6


def test_second_invalid_response_raises_criteria_extraction_error() -> None:
    service, client = service_with("not-json", '{"criteria":"still invalid"}')

    with pytest.raises(CriteriaExtractionError, match="one repair attempt") as raised:
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(client.calls) == 2
    assert raised.value.category is ExtractionFailureCategory.REPAIR_EXHAUSTED
    assert raised.value.validation_category is ExtractionFailureCategory.SCHEMA_VALIDATION


@pytest.mark.parametrize("eligibility_text", [None, "", "   "])
def test_blank_or_missing_eligibility_text_is_rejected(
    eligibility_text: str | None,
) -> None:
    service, client = service_with(output())

    with pytest.raises(ValueError, match="eligibility_text must not be blank"):
        run(service.extract_text(eligibility_text))

    assert client.calls == []


def test_provider_failure_is_categorized_without_returning_empty_criteria() -> None:
    service, client = service_with(GroqClientError("provider unavailable"))

    with pytest.raises(CriteriaExtractionError) as raised:
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(client.calls) == 1
    assert raised.value.category is ExtractionFailureCategory.PROVIDER_ERROR


def test_json_generation_failure_retries_once_without_using_repair_budget() -> None:
    service, client = service_with(json_generation_failure(), output(criterion()))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(result) == 1
    assert len(client.calls) == 2
    assert service.provider_attempts == 2
    assert service.extraction_repair_attempts == 0
    assert service.provider_error_code == "json_validate_failed"


def test_second_json_generation_failure_fails_as_provider_error() -> None:
    service, client = service_with(
        json_generation_failure(), json_generation_failure()
    )

    with pytest.raises(CriteriaExtractionError) as raised:
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(client.calls) == 2
    assert raised.value.category is ExtractionFailureCategory.PROVIDER_ERROR
    assert raised.value.provider_attempts == 2
    assert raised.value.extraction_repair_attempts == 0
    assert raised.value.provider_error_code == "json_validate_failed"


@pytest.mark.parametrize(
    "failure",
    [
        GroqClientError("invalid credentials", status_code=401),
        GroqClientError("invalid configuration", status_code=400),
    ],
)
def test_non_json_provider_failures_are_not_retried(failure: GroqClientError) -> None:
    service, client = service_with(failure, output(criterion()))

    with pytest.raises(CriteriaExtractionError):
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(client.calls) == 1
    assert service.provider_attempts == 1
    assert service.extraction_repair_attempts == 0


def test_schema_repair_budget_remains_separate_from_provider_attempts() -> None:
    service, client = service_with(
        json_generation_failure(),
        "not-json",
        output(criterion()),
    )

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(result) == 1
    assert len(client.calls) == 3
    assert service.provider_attempts == 3
    assert service.extraction_repair_attempts == 1


def test_provider_rate_limit_is_categorized_and_preserves_cause() -> None:
    provider_error = GroqClientError("provider unavailable")
    provider_error.__cause__ = RateLimitCause("rate limited")
    service, _ = service_with(provider_error)

    with pytest.raises(CriteriaExtractionError) as raised:
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert raised.value.category is ExtractionFailureCategory.PROVIDER_RATE_LIMIT
    assert isinstance(raised.value.__cause__, GroqClientError)


def test_extract_accepts_clinical_trial_without_patient_profile() -> None:
    trial = ClinicalTrial(
        trial_id="NCT00000001",
        title="Criteria extraction trial",
        status=TrialStatus.RECRUITING,
        study_type=StudyType.INTERVENTIONAL,
        eligibility_text=ELIGIBILITY_TEXT,
    )
    service, client = service_with(output(criterion()))

    result = run(service.extract(trial))

    assert len(result) == 1
    sent_prompt = client.calls[0]["user_prompt"]
    assert ELIGIBILITY_TEXT in sent_prompt
    assert trial.title not in sent_prompt
    assert "PatientProfile" not in sent_prompt
    assert "Type 2 Diabetes" in sent_prompt


def test_source_text_not_present_in_eligibility_retries_then_fails() -> None:
    invented = output(criterion(original_text="Invented clinical requirement."))
    service, client = service_with(invented, invented)

    with pytest.raises(CriteriaExtractionError, match="one repair attempt") as raised:
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(client.calls) == 2
    assert raised.value.category is ExtractionFailureCategory.REPAIR_EXHAUSTED
    assert raised.value.validation_category is ExtractionFailureCategory.SOURCE_TRACEABILITY


@pytest.mark.parametrize(
    ("source_text", "extracted_text"),
    [
        ("HbA1c <9% at screening.", "HbA1c \\<9% at screening."),
        ("HbA1c &lt;9% at screening.", "HbA1c <9% at screening."),
        (
            "HbA1c <9%\n\n at screening.",
            "HbA1c <9% at screening.",
        ),
        (
            "Use of PPAR-γ \\[e.g., pioglitazone\\] at screening.",
            "Use of PPAR-γ [e.g., pioglitazone] at screening.",
        ),
        ("Café HbA1c <9% at screening.", "Cafe\u0301 HbA1c <9% at screening."),
    ],
)
def test_traceability_normalizes_harmless_text_representations(
    source_text: str, extracted_text: str
) -> None:
    extracted = EligibilityCriterion(
        criterion_id="INC-001",
        criterion_type=CriterionType.INCLUSION,
        category="LAB",
        original_text=extracted_text,
        evaluation_type=EvaluationType.SEMANTIC,
    )

    _validate_source_evidence([extracted], source_text)

    assert extracted.original_text == extracted_text


@pytest.mark.parametrize("extracted_text", ["HbA1c >9% at screening.", "HbA1c <=9% at screening."])
def test_traceability_rejects_different_comparison_operator(
    extracted_text: str,
) -> None:
    extracted = EligibilityCriterion(
        criterion_id="INC-001",
        criterion_type=CriterionType.INCLUSION,
        category="LAB",
        original_text=extracted_text,
        evaluation_type=EvaluationType.SEMANTIC,
    )

    with pytest.raises(_SourceEvidenceError, match="not present"):
        _validate_source_evidence([extracted], "HbA1c <9% at screening.")


def test_source_validation_allows_flattened_markdown_list_formatting() -> None:
    eligibility_text = """Exclusion Criteria:
* Have had any of these events:
  * heart attack
  * stroke
"""
    flattened = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text="Have had any of these events: heart attack, stroke",
        evaluation_type="SEMANTIC",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        requires_human_review=True,
    )
    service, client = service_with(output(flattened))

    result = run(service.extract_text(eligibility_text))

    assert len(result) == 1
    assert len(client.calls) == 1


def test_source_validation_allows_compound_child_logical_decomposition() -> None:
    eligibility_text = "Have Class III or IV congestive heart failure."
    children = [
        criterion(
            criterion_type="EXCLUSION",
            category="MEDICAL_HISTORY",
            original_text="Class III",
            evaluation_type="CATEGORICAL",
            field_name="nyha_class",
            operator="EQ",
            value="III",
            unit=None,
        ),
        criterion(
            criterion_type="EXCLUSION",
            category="MEDICAL_HISTORY",
            original_text="Class IV",
            evaluation_type="CATEGORICAL",
            field_name="nyha_class",
            operator="EQ",
            value="IV",
            unit=None,
        ),
    ]
    compound = criterion(
        criterion_type="EXCLUSION",
        category="MEDICAL_HISTORY",
        original_text=eligibility_text,
        evaluation_type="COMPOUND",
        field_name=None,
        operator=None,
        value=None,
        unit=None,
        logical_operator="OR",
        children=children,
    )
    service, client = service_with(output(compound))

    result = run(service.extract_text(eligibility_text))

    assert len(result[0].children) == 2
    assert len(client.calls) == 1
