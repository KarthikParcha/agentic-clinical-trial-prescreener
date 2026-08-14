"""Extract validated eligibility criteria from trial eligibility text."""

import json
import re
from decimal import Decimal
from typing import Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from clinical_trial_prescreener.domain.criterion import (
    ComparisonOperator,
    CriterionCategory,
    CriterionType,
    EligibilityCriterion,
    EvaluationType,
    LogicalOperator,
    TemporalWindow,
)
from clinical_trial_prescreener.domain.trial import ClinicalTrial

VERSION_1_TARGET_POPULATION = "Type 2 Diabetes"

# Canonical facts are the stable interface for a future PatientFactResolver.
# Their required fields are real PatientProfile data used to derive each fact.
CANONICAL_FACT_REQUIREMENTS = {
    "hba1c": ["laboratory_results"],
    "bmi": ["bmi"],
    "insulin_naive": ["medications"],
    "type_1_diabetes": ["medical_history"],
    "type_2_diabetes": ["condition"],
    "diagnosis_duration_years": ["diagnosis_date"],
    "heart_attack": ["medical_history"],
    "stroke": ["medical_history"],
    "heart_failure_hospitalization": ["medical_history"],
    "nyha_class": ["medical_history"],
    "morbid_obesity": ["medical_history"],
}


class GeneratedContentClient(Protocol):
    """Provider-neutral interface needed by criteria extraction."""

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return generated text for the supplied instructions."""


class CriteriaExtractionError(RuntimeError):
    """Raised after both LLM outputs fail extraction-format validation."""


class _InvalidExtractionResponse(ValueError):
    """Internal signal for a repairable LLM response."""


class ExtractedCriterion(BaseModel):
    """External LLM criterion shape before application-assigned IDs."""

    model_config = ConfigDict(extra="forbid")

    criterion_type: CriterionType
    category: CriterionCategory
    original_text: str
    evaluation_type: EvaluationType
    field_name: str | None = None
    operator: ComparisonOperator | None = None
    value: Decimal | bool | str | list[str] | None = None
    lower_value: Decimal | None = None
    upper_value: Decimal | None = None
    unit: str | None = None
    temporal_window: TemporalWindow | None = None
    logical_operator: LogicalOperator | None = None
    children: list["ExtractedCriterion"] = Field(default_factory=list)
    required_patient_fields: list[str] = Field(default_factory=list)
    requires_human_review: bool = False

    @field_validator("original_text")
    @classmethod
    def validate_original_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_compound_structure(self) -> "ExtractedCriterion":
        if self.evaluation_type in {
            EvaluationType.SEMANTIC,
            EvaluationType.HUMAN_ONLY,
        } and any(
            value is not None
            for value in (
                self.field_name,
                self.operator,
                self.value,
                self.lower_value,
                self.upper_value,
                self.unit,
                self.temporal_window,
            )
        ):
            raise ValueError(
                "semantic and human-only criteria must not contain invented "
                "deterministic fields"
            )

        if self.evaluation_type is EvaluationType.COMPOUND:
            if not self.children:
                raise ValueError("compound criterion must contain children")
            if self.logical_operator is None:
                raise ValueError("compound criterion must provide a logical_operator")
            return self

        if self.children:
            raise ValueError("non-compound criterion must not contain children")
        if self.logical_operator is not None:
            raise ValueError(
                "non-compound criterion must not provide a logical_operator"
            )
        return self

    def to_domain(self, criterion_id: str) -> EligibilityCriterion:
        """Create a domain model with deterministic recursive child IDs."""

        data = self.model_dump(exclude={"children"})
        children = [
            child.to_domain(f"{criterion_id}.{index}")
            for index, child in enumerate(self.children, start=1)
        ]
        return EligibilityCriterion(
            criterion_id=criterion_id,
            children=children,
            **data,
        )


class CriteriaExtractionOutput(BaseModel):
    """Top-level JSON object required from the LLM."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[ExtractedCriterion]


SYSTEM_PROMPT = """You extract clinical-trial eligibility CRITERIA only.

You never determine whether a patient is eligible, never assess a patient, and never
provide medical advice. No patient profile is supplied or needed.

Extract only criteria supported by the supplied trial eligibility text. Do not invent
criteria, thresholds, units, temporal windows, definitions, patient facts, or medical
conclusions. Preserve inclusion versus exclusion, source meaning, numeric boundaries,
units, temporal windows, negation, and explicit AND/OR relationships. Copy each
original_text as a contiguous excerpt of the supplied eligibility text; do not
paraphrase it.

Use structured deterministic fields only when the source explicitly supports them.
Use SEMANTIC or HUMAN_ONLY for language that cannot safely become a deterministic
rule. For an ambiguous concept such as "medically stable", do not fabricate a field,
operator, value, threshold, or definition. Use COMPOUND with children and an AND or OR
logical_operator when one source criterion contains an explicit compound relationship.
Use explicit temporal values only; never assign a duration to words such as "recent".

EligibilityCriterion represents the condition that makes the source criterion
statement TRUE; it does not represent the value that would make a patient eligible.
For example, the exclusion "Have type 1 diabetes" is EXCLUSION, EQ, true (the
exclusion is met when that condition is true), never false. Apply this convention to
diagnoses, medical history, procedures, and boolean children of compound rules.

field_name is a canonical patient FACT, not a PatientProfile container. Use only this
controlled fact vocabulary: hba1c, bmi, insulin_naive, type_1_diabetes,
type_2_diabetes, diagnosis_duration_years, heart_attack, stroke,
heart_failure_hospitalization, nyha_class, morbid_obesity. required_patient_fields is
the actual PatientProfile data needed to derive that fact: hba1c ->
laboratory_results; insulin_naive -> medications; type_1_diabetes and nyha_class ->
medical_history; diagnosis_duration_years -> diagnosis_date. Do not invent any other
field_name. If a source concept cannot be safely mapped (for example, consideration
for a bariatric or other weight-loss procedure), set field_name to null and
requires_human_review to true.

Use EQ with a true/false value for canonical boolean facts, never EXISTS. In
particular, "Insulin naive" is insulin_naive EQ true, and "heart attack" is
heart_attack EQ true. Represent "type 2 diabetes for at least one year" as NUMERIC
diagnosis_duration_years GTE 1 with unit "year" and no temporal_window. Reserve
HUMAN_ONLY for genuinely judgment-based source language, never simply because a
single leaf has no safe field mapping.

For IN and NOT_IN, preserve every explicit source alternative. For example, "NYHA
Class III or IV" uses IN with value ["III", "IV"]. Preserve nested logic: "A AND B
AND (C OR D)" is an AND compound with A, B, and an OR child containing C and D; do
not flatten it. A compound temporal_window applies to all descendants unless a child
explicitly overrides it.

For a list-based compound, parent original_text must be the complete contiguous source
span including every listed alternative. Never synthesize a partial parent such as
"heart conditions ... stroke"; use the complete parent and individual list items as
children. The Type 2 Diabetes + morbid obesity + bariatric/other weight-loss procedure
exclusion must be an AND compound with an OR procedure child. A missing procedure fact
mapping affects only that leaf and requires human review; it never makes the parent
HUMAN_ONLY.

For a trial with multiple populations, extract criteria that apply to the requested
target population plus criteria that genuinely apply globally. Exclude criteria that
apply only to other populations. Preserve applicable source order.

Return exactly one JSON object matching the supplied schema. Output JSON only, with no
Markdown or explanatory text."""


class CriteriaExtractionService:
    """Coordinate safe LLM extraction and domain validation."""

    def __init__(self, client: GeneratedContentClient) -> None:
        self._client = client

    async def extract(
        self,
        source: ClinicalTrial | str,
        *,
        target_population: str = VERSION_1_TARGET_POPULATION,
    ) -> list[EligibilityCriterion]:
        """Extract criteria from a normalized trial or raw eligibility text."""

        eligibility_text = (
            source.eligibility_text if isinstance(source, ClinicalTrial) else source
        )
        return await self.extract_text(
            eligibility_text,
            target_population=target_population,
        )

    async def extract_text(
        self,
        eligibility_text: str | None,
        *,
        target_population: str = VERSION_1_TARGET_POPULATION,
    ) -> list[EligibilityCriterion]:
        """Extract criteria with one repair attempt for invalid model output."""

        if not isinstance(eligibility_text, str) or not eligibility_text.strip():
            raise ValueError("eligibility_text must not be blank")
        if target_population != VERSION_1_TARGET_POPULATION:
            raise ValueError("Version 1 supports only the Type 2 Diabetes population")

        user_prompt = _extraction_prompt(eligibility_text, target_population)
        first_response = await self._client.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        try:
            return _validated_criteria(first_response, eligibility_text)
        except _InvalidExtractionResponse as first_error:
            repair_prompt = _repair_prompt(
                user_prompt=user_prompt,
                invalid_response=first_response,
                feedback=str(first_error),
            )

        second_response = await self._client.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=repair_prompt,
        )
        try:
            return _validated_criteria(second_response, eligibility_text)
        except _InvalidExtractionResponse as second_error:
            raise CriteriaExtractionError(
                "LLM returned invalid criteria extraction output after one repair attempt"
            ) from second_error


def _extraction_prompt(eligibility_text: str, target_population: str) -> str:
    schema = json.dumps(
        CriteriaExtractionOutput.model_json_schema(), separators=(",", ":")
    )
    return f"""Extract eligibility criteria for this target population:
<target_population>{target_population}</target_population>

Eligibility text:
<eligibility_text>
{eligibility_text}
</eligibility_text>

Required JSON Schema (use only the enum values shown):
{schema}

Important field rules:
- Do not include criterion_id; the application assigns IDs.
- For a single threshold, put the number in value.
- For a range, use BETWEEN or BETWEEN_INCLUSIVE and lower_value/upper_value.
- Preserve the source unit in unit.
- For explicit time windows, use temporal_window with value and unit.
- For SEMANTIC or HUMAN_ONLY ambiguity, omit unsupported deterministic fields and set
  requires_human_review appropriately.
- required_patient_fields names information that a future evaluator would require; it
  does not state or infer any patient facts.
- The application derives required_patient_fields from the canonical mapping.
- Return a top-level object with a criteria array, even when the array is empty.
"""


def _repair_prompt(*, user_prompt: str, invalid_response: str, feedback: str) -> str:
    concise_feedback = " ".join(feedback.split())[:1000]
    return f"""{user_prompt}

Your previous JSON response failed validation. Correct only its format/schema issues
while continuing to use only the eligibility source above.
<validation_feedback>{concise_feedback}</validation_feedback>
<invalid_response>{invalid_response}</invalid_response>
Return the corrected JSON object only."""


def _validated_criteria(
    generated_content: str, eligibility_text: str
) -> list[EligibilityCriterion]:
    try:
        payload = json.loads(generated_content)
        output = CriteriaExtractionOutput.model_validate(payload)
        criteria = _assign_ids(output.criteria)
        _validate_source_evidence(criteria, eligibility_text)
        _validate_required_compound_structure(criteria)
        _enrich_patient_field_metadata(criteria)
    except (json.JSONDecodeError, ValidationError, _SourceEvidenceError) as error:
        raise _InvalidExtractionResponse(str(error)) from error
    return criteria


def _assign_ids(criteria: list[ExtractedCriterion]) -> list[EligibilityCriterion]:
    counters = {CriterionType.INCLUSION: 0, CriterionType.EXCLUSION: 0}
    domain_criteria: list[EligibilityCriterion] = []
    for criterion in criteria:
        criterion_type = criterion.criterion_type
        counters[criterion_type] += 1
        prefix = "INC" if criterion_type is CriterionType.INCLUSION else "EXC"
        criterion_id = f"{prefix}-{counters[criterion_type]:03d}"
        domain_criteria.append(criterion.to_domain(criterion_id))
    return domain_criteria


def _enrich_patient_field_metadata(criteria: list[EligibilityCriterion]) -> None:
    """Apply the small V1 field catalog and deterministic field requirements."""

    for criterion in criteria:
        _enrich_criterion_patient_fields(criterion)


def _enrich_criterion_patient_fields(criterion: EligibilityCriterion) -> set[str]:
    canonical_fact = _canonical_fact(criterion.original_text)
    if (
        criterion.evaluation_type is EvaluationType.COMPOUND
        and canonical_fact == "nyha_class"
    ):
        criterion.children = []
        criterion.logical_operator = None
        _apply_canonical_fact_contract(criterion, canonical_fact)
        criterion.field_name = canonical_fact
        criterion.required_patient_fields = CANONICAL_FACT_REQUIREMENTS[canonical_fact]
        return set(criterion.required_patient_fields)

    child_fields: set[str] = set()
    for child in criterion.children:
        child_fields.update(_enrich_criterion_patient_fields(child))

    if criterion.evaluation_type is EvaluationType.COMPOUND:
        criterion.field_name = None
        criterion.required_patient_fields = sorted(child_fields)
        criterion.requires_human_review = (
            criterion.requires_human_review
            or any(child.requires_human_review for child in criterion.children)
        )
        return child_fields

    if canonical_fact is None:
        criterion.field_name = None
        criterion.required_patient_fields = []
        criterion.requires_human_review = True
        return set()

    _apply_canonical_fact_contract(criterion, canonical_fact)
    required_fields = CANONICAL_FACT_REQUIREMENTS[canonical_fact]
    criterion.field_name = canonical_fact
    criterion.required_patient_fields = required_fields
    return set(required_fields)


def _canonical_fact(original_text: str) -> str | None:
    """Return a safe V1 resolver fact for known source concepts only."""

    text = _normalized_text(original_text)
    if "bariatric" in text or "procedure intended for weight loss" in text:
        return None
    if "hba1c" in text:
        return "hba1c"
    if "body mass index" in text or re.search(r"\bbmi\b", text):
        return "bmi"
    if "insulin naive" in text:
        return "insulin_naive"
    if "at least one year" in text and "type 2 diabetes" in text:
        return "diagnosis_duration_years"
    if "type 2 diabetes" in text:
        return "type_2_diabetes"
    if "type 1 diabetes" in text:
        return "type_1_diabetes"
    if "heart attack" in text:
        return "heart_attack"
    if "stroke" in text:
        return "stroke"
    if "new york heart association" in text or "nyha" in text:
        return "nyha_class"
    if "morbid obesity" in text:
        return "morbid_obesity"
    if "heart failure" in text:
        return "heart_failure_hospitalization"
    return None


def _apply_canonical_fact_contract(
    criterion: EligibilityCriterion, canonical_fact: str
) -> None:
    """Normalize known facts so the future resolver receives one stable contract."""

    if canonical_fact == "diagnosis_duration_years":
        criterion.category = CriterionCategory.DIAGNOSIS
        criterion.evaluation_type = EvaluationType.NUMERIC
        criterion.operator = ComparisonOperator.GTE
        criterion.value = Decimal(1)
        criterion.lower_value = None
        criterion.upper_value = None
        criterion.unit = "year"
        criterion.temporal_window = None
    elif canonical_fact in {
        "insulin_naive",
        "type_1_diabetes",
        "type_2_diabetes",
        "heart_attack",
        "stroke",
        "heart_failure_hospitalization",
        "morbid_obesity",
    }:
        criterion.evaluation_type = EvaluationType.BOOLEAN
        criterion.operator = ComparisonOperator.EQ
        criterion.value = True
        criterion.lower_value = None
        criterion.upper_value = None
        criterion.unit = None
        if canonical_fact == "insulin_naive":
            criterion.category = CriterionCategory.MEDICATION
        elif canonical_fact in {"heart_attack", "stroke", "heart_failure_hospitalization"}:
            criterion.category = CriterionCategory.MEDICAL_HISTORY
        else:
            criterion.category = CriterionCategory.DIAGNOSIS
    elif canonical_fact == "nyha_class":
        criterion.category = CriterionCategory.MEDICAL_HISTORY
        criterion.evaluation_type = EvaluationType.CATEGORICAL
        criterion.operator = ComparisonOperator.IN
        criterion.value = ["III", "IV"]
        criterion.lower_value = None
        criterion.upper_value = None
        criterion.unit = None


def _validate_required_compound_structure(criteria: list[EligibilityCriterion]) -> None:
    """Require explicit source logic where V1 has a known compound contract."""

    for criterion in _walk_criteria(criteria):
        text = _normalized_text(criterion.original_text)
        if (
            "type 2 diabetes" in text
            and "morbid obesity" in text
            and "bariatric" in text
            and "procedure intended for weight loss" in text
            and criterion.evaluation_type is not EvaluationType.COMPOUND
        ):
            raise _SourceEvidenceError(
                "explicit Type 2 Diabetes/morbid-obesity/procedure logic must be "
                "a COMPOUND criterion, not HUMAN_ONLY"
            )
        if (
            "bariatric" in text
            and "procedure intended for weight loss" in text
            and criterion.evaluation_type is not EvaluationType.COMPOUND
        ):
            raise _SourceEvidenceError(
                "explicit bariatric/other-procedure logic must be a COMPOUND "
                "criterion, not HUMAN_ONLY"
            )


def _walk_criteria(criteria: list[EligibilityCriterion]) -> list[EligibilityCriterion]:
    """Return every criterion node so nested source-logic contracts are checked."""

    nodes: list[EligibilityCriterion] = []
    for criterion in criteria:
        nodes.append(criterion)
        nodes.extend(_walk_criteria(criterion.children))
    return nodes


class _SourceEvidenceError(ValueError):
    """Raised when original_text cannot be traced to the supplied source."""


def _validate_source_evidence(
    criteria: list[EligibilityCriterion], eligibility_text: str
) -> None:
    normalized_source = _normalized_text(eligibility_text)
    for criterion in criteria:
        _validate_criterion_source(criterion, normalized_source)


def _validate_criterion_source(
    criterion: EligibilityCriterion,
    normalized_source: str,
    normalized_parent: str | None = None,
) -> None:
    normalized_criterion = _normalized_text(criterion.original_text)
    if not normalized_criterion:
        raise _SourceEvidenceError("original_text contains no source wording")
    is_contiguous_source = normalized_criterion in normalized_source
    is_parent_decomposition = normalized_parent is not None and _ordered_words(
        normalized_criterion, normalized_parent
    )
    if not is_contiguous_source and not is_parent_decomposition:
        raise _SourceEvidenceError(
            f"original_text is not present in eligibility_text: "
            f"{criterion.original_text!r}"
        )

    for child in criterion.children:
        _validate_criterion_source(child, normalized_source, normalized_criterion)


def _ordered_words(candidate: str, source: str) -> bool:
    source_words = iter(source.split())
    return all(
        any(word == source_word for source_word in source_words)
        for word in candidate.split()
    )


def _normalized_text(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip().casefold()
    without_list_markers = re.sub(r"(^|\s)(?:[*+-]|\d+[.)])\s+", r"\1", collapsed)
    return re.sub(r"[,:;]", "", without_list_markers)
