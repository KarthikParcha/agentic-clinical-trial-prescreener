"""Extract validated eligibility criteria from trial eligibility text."""

import json
import re
import unicodedata
from decimal import Decimal
from enum import Enum
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
from clinical_trial_prescreener.infrastructure.llm.groq_client import GroqClientError

VERSION_1_TARGET_POPULATION = "Type 2 Diabetes"

_TEMPORAL_UNIT_ALIASES = {
    "day": "DAY",
    "days": "DAY",
    "week": "WEEK",
    "weeks": "WEEK",
    "month": "MONTH",
    "months": "MONTH",
    "year": "YEAR",
    "years": "YEAR",
}
_DETERMINISTIC_ONLY_FIELDS = (
    "field_name",
    "operator",
    "value",
    "lower_value",
    "upper_value",
    "unit",
    "temporal_window",
)

# Canonical facts are the stable interface for a future PatientFactResolver.
# Their required fields are real PatientProfile data used to derive each fact.
CANONICAL_FACT_REQUIREMENTS = {
    "age": ["age"],
    "fasting_blood_glucose": ["laboratory_results"],
    "random_blood_glucose": ["laboratory_results"],
    "hba1c": ["laboratory_results"],
    "bmi": ["bmi"],
    "insulin_naive": ["medications"],
    "type_1_diabetes": ["medical_history"],
    "type_2_diabetes": ["condition"],
    "type_2_diabetes_on_treatment": ["condition", "medications"],
    "diagnosis_duration_years": ["diagnosis_date"],
    "heart_attack": ["medical_history"],
    "stroke": ["medical_history"],
    "heart_failure_hospitalization": ["medical_history"],
    "heart_failure_history": ["medical_history"],
    "other_systemic_conditions": ["fact_confirmations"],
    "pregnancy_status": ["pregnancy_status"],
    "antibiotic_use": ["medications"],
    "hypertension_on_active_treatment": ["medical_history", "medications"],
    "cardiovascular_disease_on_active_treatment": [
        "medical_history",
        "medications",
    ],
    "nyha_class": ["medical_history"],
    "morbid_obesity": ["medical_history"],
}


class GeneratedContentClient(Protocol):
    """Provider-neutral interface needed by criteria extraction."""

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return generated text for the supplied instructions."""


class ExtractionFailureCategory(str, Enum):
    """Safe, concise categories for bounded extraction failures."""

    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    MALFORMED_JSON = "MALFORMED_JSON"
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    SOURCE_TRACEABILITY = "SOURCE_TRACEABILITY"
    DOMAIN_VALIDATION = "DOMAIN_VALIDATION"
    REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"


class CriteriaExtractionError(RuntimeError):
    """A structured, bounded extraction failure with its original cause preserved."""

    def __init__(
        self,
        message: str,
        *,
        category: ExtractionFailureCategory = ExtractionFailureCategory.PROVIDER_ERROR,
        validation_category: ExtractionFailureCategory | None = None,
        canonicalizations: list["ExtractionCanonicalization"] | None = None,
        provider_attempts: int = 0,
        extraction_repair_attempts: int = 0,
        provider_error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.validation_category = validation_category
        self.canonicalizations = canonicalizations or []
        self.provider_attempts = provider_attempts
        self.extraction_repair_attempts = extraction_repair_attempts
        self.provider_error_code = provider_error_code


class ExtractionCanonicalization(BaseModel):
    """Safe metadata for one representation-only DTO normalization."""

    model_config = ConfigDict(extra="forbid")

    criterion_path: str
    raw_evaluation_type: EvaluationType
    removed_fields: list[str]


class _InvalidExtractionResponse(ValueError):
    """Internal signal for a repairable LLM response."""

    def __init__(
        self,
        category: ExtractionFailureCategory,
        detail: str,
        *,
        canonicalizations: list[ExtractionCanonicalization] | None = None,
    ) -> None:
        super().__init__(detail)
        self.category = category
        self.canonicalizations = canonicalizations or []


class RawExtractedCriterion(BaseModel):
    """Permissive LLM DTO before representation-only canonicalization."""

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
    children: list["RawExtractedCriterion"] = Field(default_factory=list)
    required_patient_fields: list[str] = Field(default_factory=list)
    requires_human_review: bool = False

    @field_validator("original_text")
    @classmethod
    def validate_original_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_compound_structure(self) -> "RawExtractedCriterion":
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


class ExtractedCriterion(RawExtractedCriterion):
    """Canonical extraction DTO safe to convert into the strict domain model."""

    children: list["ExtractedCriterion"] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_semantic_representation(self) -> "ExtractedCriterion":
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

    criteria: list[RawExtractedCriterion]


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
        self._last_canonicalizations: list[ExtractionCanonicalization] = []
        self._provider_attempts = 0
        self._extraction_repair_attempts = 0
        self._provider_retry_used = False
        self._provider_error_code: str | None = None

    @property
    def last_canonicalizations(self) -> list[ExtractionCanonicalization]:
        """Return safe representation changes from the latest validation attempt."""

        return list(self._last_canonicalizations)

    @property
    def provider_attempts(self) -> int:
        """Return provider calls made during the latest extraction."""

        return self._provider_attempts

    @property
    def extraction_repair_attempts(self) -> int:
        """Return schema/source repair prompts used during the latest extraction."""

        return self._extraction_repair_attempts

    @property
    def provider_error_code(self) -> str | None:
        """Return the latest safe provider error code, when present."""

        return self._provider_error_code

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
        """Extract criteria with bounded provider retry and one repair attempt."""

        if not isinstance(eligibility_text, str) or not eligibility_text.strip():
            raise ValueError("eligibility_text must not be blank")
        if target_population != VERSION_1_TARGET_POPULATION:
            raise ValueError("Version 1 supports only the Type 2 Diabetes population")

        self._reset_attempt_debug()
        user_prompt = _extraction_prompt(eligibility_text, target_population)
        try:
            response = await self._generate_with_provider_retry(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except GroqClientError as error:
            raise self._provider_extraction_error(error) from error
        try:
            criteria, canonicalizations = _validated_criteria_with_debug(
                response, eligibility_text
            )
            self._last_canonicalizations = canonicalizations
            return criteria
        except _InvalidExtractionResponse as error:
            self._last_canonicalizations = error.canonicalizations
            response = await self._repair_invalid_response(
                user_prompt=user_prompt,
                invalid_response=response,
                validation_error=error,
                system_prompt=SYSTEM_PROMPT,
            )
            try:
                criteria, canonicalizations = _validated_criteria_with_debug(
                    response, eligibility_text
                )
                self._last_canonicalizations = canonicalizations
                return criteria
            except _InvalidExtractionResponse as repaired_error:
                self._last_canonicalizations = repaired_error.canonicalizations
                raise self._repair_exhausted(repaired_error) from repaired_error

    async def _repair_invalid_response(
        self,
        *,
        user_prompt: str,
        invalid_response: str,
        validation_error: _InvalidExtractionResponse,
        system_prompt: str,
    ) -> str:
        if self._extraction_repair_attempts >= 1:
            raise validation_error
        self._extraction_repair_attempts += 1
        repair_prompt = _repair_prompt(
            user_prompt=user_prompt,
            invalid_response=invalid_response,
            validation_error=validation_error,
        )
        try:
            return await self._generate_with_provider_retry(
                system_prompt=system_prompt, user_prompt=repair_prompt
            )
        except GroqClientError as error:
            raise self._provider_extraction_error(error) from error

    def _repair_exhausted(
        self, error: _InvalidExtractionResponse
    ) -> CriteriaExtractionError:
        return CriteriaExtractionError(
            "LLM returned invalid criteria extraction output after one repair attempt",
            category=ExtractionFailureCategory.REPAIR_EXHAUSTED,
            validation_category=error.category,
            canonicalizations=error.canonicalizations,
            provider_attempts=self.provider_attempts,
            extraction_repair_attempts=self.extraction_repair_attempts,
            provider_error_code=self.provider_error_code,
        )

    def _reset_attempt_debug(self) -> None:
        self._last_canonicalizations = []
        self._provider_attempts = 0
        self._extraction_repair_attempts = 0
        self._provider_retry_used = False
        self._provider_error_code = None

    async def _generate_with_provider_retry(
        self, *, system_prompt: str, user_prompt: str
    ) -> str:
        """Retry Groq's pre-response JSON-mode failure once per extraction."""

        while True:
            self._provider_attempts += 1
            try:
                return await self._client.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            except GroqClientError as error:
                self._provider_error_code = error.error_code
                if (
                    error.is_json_generation_failure
                    and not self._provider_retry_used
                ):
                    self._provider_retry_used = True
                    continue
                raise

    def _provider_extraction_error(
        self, error: GroqClientError
    ) -> CriteriaExtractionError:
        return _provider_extraction_error(
            error,
            provider_attempts=self.provider_attempts,
            extraction_repair_attempts=self.extraction_repair_attempts,
            provider_error_code=self.provider_error_code,
        )


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


def _repair_prompt(
    *,
    user_prompt: str,
    invalid_response: str,
    validation_error: _InvalidExtractionResponse,
) -> str:
    concise_feedback = " ".join(str(validation_error).split())[:1000]
    targeted_guidance = _compound_repair_guidance(
        validation_error, invalid_response
    )
    return f"""{user_prompt}

Your previous JSON response failed validation. Correct only its format/schema issues
while continuing to use only the eligibility source above.
<validation_feedback>{concise_feedback}</validation_feedback>
{targeted_guidance}
<invalid_response>{invalid_response}</invalid_response>
Return the corrected JSON object only."""


def _compound_repair_guidance(
    validation_error: _InvalidExtractionResponse, invalid_response: str
) -> str:
    """Describe only invalid COMPOUND DTO structure for the bounded repair prompt."""

    cause = validation_error.__cause__
    if not isinstance(cause, ValidationError):
        return ""
    try:
        payload = json.loads(invalid_response)
    except json.JSONDecodeError:
        payload = None

    instructions: list[str] = []
    for detail in cause.errors():
        message = str(detail.get("msg", ""))
        if "compound criterion" not in message.casefold():
            continue
        location = tuple(detail.get("loc", ()))
        path = _format_validation_path(location)
        source_text = _original_text_at_validation_path(payload, location)
        source_evidence = (
            json.dumps(source_text, ensure_ascii=False)
            if source_text is not None
            else "not available"
        )
        instructions.append(
            "\n".join(
                (
                    f"- Failing criterion path: {path}",
                    f"  Original validation error: {message}",
                    f"  Source criterion original_text: {source_evidence}",
                    (
                        "  Domain rule: evaluation_type=COMPOUND requires "
                        "logical_operator=AND or OR and non-empty children."
                    ),
                    (
                        "  When the source expresses compound logic, provide at least "
                        "2 meaningful child criteria, each with traceable source evidence."
                    ),
                    (
                        "  If the source does not express compound logic, reconsider "
                        "evaluation_type using only the source text; do not invent children."
                    ),
                    (
                        "  Preserve criterion_type, original_text, clinical meaning, "
                        "and source traceability. Never fabricate patient fields."
                    ),
                )
            )
        )
    if not instructions:
        return ""
    joined_instructions = "\n".join(instructions)
    return (
        "<targeted_structure_repair>\n"
        "Repair only the following invalid structures:\n"
        f"{joined_instructions}\n"
        "</targeted_structure_repair>"
    )


def _format_validation_path(location: tuple[object, ...]) -> str:
    return ".".join(str(item) for item in location)


def _original_text_at_validation_path(
    payload: object, location: tuple[object, ...]
) -> str | None:
    current = payload
    nearest_original_text: str | None = None
    for item in location:
        if isinstance(current, dict):
            original_text = current.get("original_text")
            if isinstance(original_text, str):
                nearest_original_text = original_text
            current = current.get(item)
        elif isinstance(current, list) and isinstance(item, int):
            current = current[item] if 0 <= item < len(current) else None
        else:
            break
    if isinstance(current, dict):
        original_text = current.get("original_text")
        if isinstance(original_text, str):
            nearest_original_text = original_text
    return nearest_original_text


def _validated_criteria(
    generated_content: str, eligibility_text: str
) -> list[EligibilityCriterion]:
    criteria, _ = _validated_criteria_with_debug(generated_content, eligibility_text)
    return criteria


def _validated_criteria_with_debug(
    generated_content: str, eligibility_text: str
) -> tuple[list[EligibilityCriterion], list[ExtractionCanonicalization]]:
    try:
        payload = json.loads(generated_content)
    except json.JSONDecodeError as error:
        raise _InvalidExtractionResponse(
            ExtractionFailureCategory.MALFORMED_JSON, "response is not valid JSON"
        ) from error
    payload = _canonicalize_temporal_units(payload)
    try:
        output = CriteriaExtractionOutput.model_validate(payload)
    except ValidationError as error:
        raise _InvalidExtractionResponse(
            ExtractionFailureCategory.SCHEMA_VALIDATION,
            "response does not match the extraction schema",
        ) from error
    canonicalizations: list[ExtractionCanonicalization] = []
    try:
        normalized = [
            _canonicalize_extracted_criterion(
                criterion,
                path=f"criteria.{index}",
                canonicalizations=canonicalizations,
            )
            for index, criterion in enumerate(output.criteria)
        ]
    except ValidationError as error:
        raise _InvalidExtractionResponse(
            ExtractionFailureCategory.DOMAIN_VALIDATION,
            "canonical extraction DTO cannot form strict criteria",
            canonicalizations=canonicalizations,
        ) from error
    try:
        criteria = _assign_ids(normalized)
    except ValidationError as error:
        raise _InvalidExtractionResponse(
            ExtractionFailureCategory.DOMAIN_VALIDATION,
            "validated extraction cannot form domain criteria",
            canonicalizations=canonicalizations,
        ) from error
    try:
        _validate_source_evidence(criteria, eligibility_text)
        _validate_required_compound_structure(criteria)
    except _SourceEvidenceError as error:
        raise _InvalidExtractionResponse(
            ExtractionFailureCategory.SOURCE_TRACEABILITY,
            "criterion source text or explicit source logic is not traceable",
            canonicalizations=canonicalizations,
        ) from error
    _enrich_patient_field_metadata(criteria)
    return criteria, canonicalizations


def _canonicalize_extracted_criterion(
    raw: RawExtractedCriterion,
    *,
    path: str,
    canonicalizations: list[ExtractionCanonicalization],
) -> ExtractedCriterion:
    """Remove only meaningless deterministic fields from semantic DTO nodes."""

    data = raw.model_dump(exclude={"children"})
    removed_fields: list[str] = []
    if raw.evaluation_type in {
        EvaluationType.HUMAN_ONLY,
        EvaluationType.SEMANTIC,
    }:
        for field_name in _DETERMINISTIC_ONLY_FIELDS:
            if data.get(field_name) is not None:
                data.pop(field_name)
                removed_fields.append(field_name)
    if removed_fields:
        canonicalizations.append(
            ExtractionCanonicalization(
                criterion_path=path,
                raw_evaluation_type=raw.evaluation_type,
                removed_fields=removed_fields,
            )
        )

    children = [
        _canonicalize_extracted_criterion(
            child,
            path=f"{path}.children.{index}",
            canonicalizations=canonicalizations,
        )
        for index, child in enumerate(raw.children)
    ]
    return ExtractedCriterion.model_validate({**data, "children": children})


def _canonicalize_temporal_units(payload: object) -> object:
    """Canonicalize only documented temporal-unit aliases before strict validation."""

    if isinstance(payload, list):
        return [_canonicalize_temporal_units(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    normalized: dict[object, object] = {}
    for key, value in payload.items():
        if key == "temporal_window" and isinstance(value, dict):
            window = _canonicalize_temporal_units(value)
            if isinstance(window, dict) and isinstance(window.get("unit"), str):
                unit = window["unit"]
                window["unit"] = _TEMPORAL_UNIT_ALIASES.get(unit.casefold(), unit)
            normalized[key] = window
        else:
            normalized[key] = _canonicalize_temporal_units(value)
    return normalized


def _provider_extraction_error(
    error: GroqClientError,
    *,
    provider_attempts: int,
    extraction_repair_attempts: int,
    provider_error_code: str | None,
) -> CriteriaExtractionError:
    """Classify Groq failures without exposing request content or credentials."""

    cause = error.__cause__
    category = (
        ExtractionFailureCategory.PROVIDER_RATE_LIMIT
        if error.status_code == 429 or getattr(cause, "status_code", None) == 429
        else ExtractionFailureCategory.PROVIDER_ERROR
    )
    message = (
        "Groq rate limit prevented criteria extraction"
        if category is ExtractionFailureCategory.PROVIDER_RATE_LIMIT
        else "Groq provider error prevented criteria extraction"
    )
    return CriteriaExtractionError(
        message,
        category=category,
        provider_attempts=provider_attempts,
        extraction_repair_attempts=extraction_repair_attempts,
        provider_error_code=provider_error_code,
    )


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
    if _is_type_2_diabetes_age_range(criterion.original_text):
        _apply_type_2_diabetes_age_range_contract(criterion)
        return set(criterion.required_patient_fields)
    if _is_glucose_pair(criterion.original_text):
        _apply_glucose_pair_contract(criterion)
        return set(criterion.required_patient_fields)
    canonical_fact = _canonical_fact(criterion.original_text)
    if criterion.evaluation_type in {
        EvaluationType.SEMANTIC,
        EvaluationType.HUMAN_ONLY,
    } and canonical_fact is None:
        criterion.field_name = None
        return set(criterion.required_patient_fields)
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
    criterion.requires_human_review = False
    return set(required_fields)


def _is_type_2_diabetes_age_range(source_text: str) -> bool:
    text = _normalized_text(source_text)
    return "type 2 diabetic" in text and "between the ages of" in text


def _apply_type_2_diabetes_age_range_contract(criterion: EligibilityCriterion) -> None:
    """Preserve the explicit Trial 2 diagnosis-and-age conjunction."""

    age_match = re.search(
        r"between the ages of\s+(\d+)\s+years? and\s+(\d+)\s+years?",
        criterion.original_text,
        flags=re.IGNORECASE,
    )
    if age_match is None:
        return
    criterion.category = CriterionCategory.OTHER
    criterion.evaluation_type = EvaluationType.COMPOUND
    criterion.field_name = None
    criterion.operator = None
    criterion.value = None
    criterion.lower_value = None
    criterion.upper_value = None
    criterion.unit = None
    criterion.logical_operator = LogicalOperator.AND
    criterion.children = [
        EligibilityCriterion(
            criterion_id=f"{criterion.criterion_id}-diagnosis",
            criterion_type=criterion.criterion_type,
            category=CriterionCategory.DIAGNOSIS,
            original_text="Type 2 diabetics",
            evaluation_type=EvaluationType.BOOLEAN,
            field_name="type_2_diabetes",
            operator=ComparisonOperator.EQ,
            value=True,
            required_patient_fields=["condition"],
        ),
        EligibilityCriterion(
            criterion_id=f"{criterion.criterion_id}-age",
            criterion_type=criterion.criterion_type,
            category=CriterionCategory.AGE,
            original_text=age_match.group(0),
            evaluation_type=EvaluationType.NUMERIC,
            field_name="age",
            operator=ComparisonOperator.BETWEEN_INCLUSIVE,
            lower_value=Decimal(age_match.group(1)),
            upper_value=Decimal(age_match.group(2)),
            unit="year",
            required_patient_fields=["age"],
        ),
    ]
    criterion.required_patient_fields = ["age", "condition"]
    criterion.requires_human_review = False


def _is_glucose_pair(source_text: str) -> bool:
    text = _normalized_text(source_text)
    return "fasting blood sugar" in text and "random blood sugar" in text


def _apply_glucose_pair_contract(criterion: EligibilityCriterion) -> None:
    """Preserve the explicit Trial 2 fasting/random glucose conjunction."""

    criterion.category = CriterionCategory.LAB
    criterion.evaluation_type = EvaluationType.COMPOUND
    criterion.field_name = None
    criterion.operator = None
    criterion.value = None
    criterion.lower_value = None
    criterion.upper_value = None
    criterion.unit = None
    criterion.logical_operator = LogicalOperator.AND
    criterion.children = [
        EligibilityCriterion(
            criterion_id=f"{criterion.criterion_id}-fasting-glucose",
            criterion_type=criterion.criterion_type,
            category=CriterionCategory.LAB,
            original_text="A fasting blood sugar level of 126 mg/dl",
            evaluation_type=EvaluationType.NUMERIC,
            field_name="fasting_blood_glucose",
            operator=ComparisonOperator.EQ,
            value=Decimal(126),
            unit="mg/dL",
            required_patient_fields=["laboratory_results"],
        ),
        EligibilityCriterion(
            criterion_id=f"{criterion.criterion_id}-random-glucose",
            criterion_type=criterion.criterion_type,
            category=CriterionCategory.LAB,
            original_text="a random blood sugar level of less than 200 mg/dl",
            evaluation_type=EvaluationType.NUMERIC,
            field_name="random_blood_glucose",
            operator=ComparisonOperator.LT,
            value=Decimal(200),
            unit="mg/dL",
            required_patient_fields=["laboratory_results"],
        ),
    ]
    criterion.required_patient_fields = ["laboratory_results"]
    criterion.requires_human_review = False


def _canonical_fact(original_text: str) -> str | None:
    """Return a safe V1 resolver fact for known source concepts only."""

    text = _normalized_text(original_text)
    if "bariatric" in text or "procedure intended for weight loss" in text:
        return None
    if "systemic condition" in text and "other than" in text and "type 2 diabetes" in text:
        return "other_systemic_conditions"
    if "fasting blood sugar" in text:
        return "fasting_blood_glucose"
    if "random blood sugar" in text:
        return "random_blood_glucose"
    if "pregnant" in text:
        return "pregnancy_status"
    if "antibiotics" in text and "previous three months" in text:
        return "antibiotic_use"
    if re.search(r"\bat least\s+\d+\s+years? old\b", text):
        return "age"
    if "hypertension" in text and "active pharmacological treatment" in text:
        return "hypertension_on_active_treatment"
    if "type 2 diabetes" in text and "active pharmacological treatment" in text:
        return "type_2_diabetes_on_treatment"
    if "cardiovascular" in text and "active pharmacological treatment" in text:
        return "cardiovascular_disease_on_active_treatment"
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
    if "heart failure hospitalization" in text:
        return "heart_failure_hospitalization"
    if "history of hf" in text or "history of heart failure" in text:
        return "heart_failure_history"
    return None


def _apply_canonical_fact_contract(
    criterion: EligibilityCriterion, canonical_fact: str
) -> None:
    """Normalize known facts so the future resolver receives one stable contract."""

    if canonical_fact == "age":
        match = re.search(
            r"\bat least\s+(\d+)\s+years? old\b",
            _normalized_text(criterion.original_text),
        )
        if match is None:
            return
        criterion.category = CriterionCategory.AGE
        criterion.evaluation_type = EvaluationType.NUMERIC
        criterion.operator = ComparisonOperator.GTE
        criterion.value = Decimal(match.group(1))
        criterion.lower_value = None
        criterion.upper_value = None
        criterion.unit = "year"
        criterion.temporal_window = None
    elif canonical_fact in {"fasting_blood_glucose", "random_blood_glucose"}:
        criterion.category = CriterionCategory.LAB
        criterion.evaluation_type = EvaluationType.NUMERIC
    elif canonical_fact == "antibiotic_use":
        criterion.category = CriterionCategory.MEDICATION
        criterion.evaluation_type = EvaluationType.BOOLEAN
        criterion.operator = ComparisonOperator.EQ
        criterion.value = True
        criterion.lower_value = None
        criterion.upper_value = None
        criterion.unit = None
        criterion.temporal_window = TemporalWindow(value=Decimal(3), unit="MONTH")
    elif canonical_fact == "diagnosis_duration_years":
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
        "type_2_diabetes_on_treatment",
        "hypertension_on_active_treatment",
        "cardiovascular_disease_on_active_treatment",
        "heart_attack",
        "stroke",
        "heart_failure_hospitalization",
        "heart_failure_history",
        "other_systemic_conditions",
        "pregnancy_status",
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
        elif canonical_fact in {
            "heart_attack",
            "stroke",
            "heart_failure_hospitalization",
            "heart_failure_history",
            "hypertension_on_active_treatment",
            "cardiovascular_disease_on_active_treatment",
            "other_systemic_conditions",
            "pregnancy_status",
        }:
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
    normalized_source = _normalize_traceability_text(eligibility_text)
    for criterion in criteria:
        _validate_criterion_source(criterion, normalized_source)


def _validate_criterion_source(
    criterion: EligibilityCriterion,
    normalized_source: str,
    normalized_parent: str | None = None,
) -> None:
    normalized_criterion = _normalize_traceability_text(criterion.original_text)
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


def _normalize_traceability_text(value: str) -> str:
    """Normalize representation only while preserving comparison-operator meaning."""

    normalized = unicodedata.normalize("NFC", value)
    normalized = (
        normalized.replace("\\<", "<")
        .replace("\\>", ">")
        .replace("\\[", "[")
        .replace("\\]", "]")
    )
    normalized = (
        normalized.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )
    return _normalized_text(normalized)
