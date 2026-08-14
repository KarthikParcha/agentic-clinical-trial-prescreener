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

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


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


def test_semantic_criterion_with_fake_deterministic_field_triggers_repair() -> None:
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
    repaired_semantic = {**invalid_semantic, "field_name": None}
    service, client = service_with(output(invalid_semantic), output(repaired_semantic))

    result = run(service.extract_text(ELIGIBILITY_TEXT))

    assert result[0].field_name is None
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


def test_second_invalid_response_raises_criteria_extraction_error() -> None:
    service, client = service_with("not-json", '{"criteria":"still invalid"}')

    with pytest.raises(CriteriaExtractionError, match="one repair attempt"):
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(client.calls) == 2


@pytest.mark.parametrize("eligibility_text", [None, "", "   "])
def test_blank_or_missing_eligibility_text_is_rejected(
    eligibility_text: str | None,
) -> None:
    service, client = service_with(output())

    with pytest.raises(ValueError, match="eligibility_text must not be blank"):
        run(service.extract_text(eligibility_text))

    assert client.calls == []


def test_provider_failure_is_not_converted_to_empty_criteria() -> None:
    service, client = service_with(GroqClientError("provider unavailable"))

    with pytest.raises(GroqClientError, match="provider unavailable"):
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(client.calls) == 1


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

    with pytest.raises(CriteriaExtractionError, match="one repair attempt"):
        run(service.extract_text(ELIGIBILITY_TEXT))

    assert len(client.calls) == 2


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
