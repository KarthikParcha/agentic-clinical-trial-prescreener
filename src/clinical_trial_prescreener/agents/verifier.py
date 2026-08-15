"""Single-pass LLM verification of evidence-backed pre-screening assessments."""

import json
from typing import Protocol

from pydantic import ValidationError

from clinical_trial_prescreener.agents.verification_context import (
    VerificationContextBuilder,
)
from clinical_trial_prescreener.domain.assessment import (
    CriterionAssessment,
    CriterionStatus,
    TrialAssessment,
    VerificationResult,
    VerificationStatus,
)
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.domain.patient import PatientProfile
from clinical_trial_prescreener.domain.trial import ClinicalTrial


class VerificationClient(Protocol):
    """The JSON-generation capability needed by the bounded verifier."""

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return one JSON-object response."""


class VerificationError(RuntimeError):
    """Raised when one verification response is invalid or unsafe to use."""


SYSTEM_PROMPT = """You are a bounded verification agent for clinical-trial pre-screening.

Review whether the supplied criterion and trial assessments are supported by the
provided source criterion evidence and patient evidence. You do not determine final
trial eligibility and must never use the words ELIGIBLE or INELIGIBLE as a conclusion.

Rules:
- Return APPROVED when every current assessment is supported by the supplied evidence.
  This includes INSUFFICIENT_INFORMATION caused by an UNKNOWN with explicit structured
  missing_information. Missing data alone is not a correction, reevaluation request,
  or human-review reason.
- Return CORRECTED only with at least one concrete correction containing criterion_id,
  previous_status, recommended_status, and evidence. Never use CORRECTED merely to
  restate a supported assessment or missing information.
- Return REQUIRES_REEVALUATION only for a concrete deterministic inconsistency that
  should be recomputed; never because evidence is missing.
- Never invent patient facts, trial criteria, thresholds, dates, or evidence.
- Flag unsupported MET or NOT_MET conclusions, missed exclusion concerns, incorrect
  AND/OR reasoning, and conclusions that should remain UNKNOWN.
- Use HUMAN_REVIEW only for inherent human/investigator judgment, unresolved semantic
  meaning, or conflicting patient/trial evidence that cannot be safely resolved.
- HUMAN_REVIEW findings must include issue_type, criterion_id, concrete_evidence,
  expected_semantics, observed_semantics, and reason. A vague inconsistency claim is
  invalid. Use effective_temporal_window and temporal_source from normalized evidence;
  do not infer inheritance from raw child fields.
- Review this one input once. Do not request retries or additional data.

Return exactly one JSON object matching the supplied schema. Output JSON only."""


class VerificationAgent:
    """Perform exactly one independently prompted verification pass."""

    def __init__(self, client: VerificationClient) -> None:
        self._client = client
        self._context_builder = VerificationContextBuilder()

    async def verify(
        self,
        *,
        trial: ClinicalTrial,
        patient: PatientProfile,
        criteria: list[EligibilityCriterion],
        criterion_assessments: list[CriterionAssessment],
        trial_assessment: TrialAssessment,
    ) -> VerificationResult:
        """Verify supplied evidence and assessments without performing an eligibility decision."""

        _validate_input_consistency(criteria, criterion_assessments, trial_assessment)
        prompt = _verification_prompt(
            trial, patient, criteria, criterion_assessments, trial_assessment, self._context_builder
        )
        response = await self._client.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        try:
            result = _parse_result(response, criteria)
        except VerificationError as first_error:
            repair = f"{prompt}\nInvalid decision: {first_error}. Return corrected JSON only."
            repaired = await self._client.generate(system_prompt=SYSTEM_PROMPT, user_prompt=repair)
            try:
                result = _parse_result(repaired, criteria)
            except VerificationError as second_error:
                raise VerificationError("Verifier failed after one repair attempt") from second_error
        result = _calibrate_supported_missing_data(result, criterion_assessments)
        return result


def _verification_prompt(
    trial: ClinicalTrial,
    patient: PatientProfile,
    criteria: list[EligibilityCriterion],
    criterion_assessments: list[CriterionAssessment],
    trial_assessment: TrialAssessment,
    context_builder: VerificationContextBuilder,
) -> str:
    schema = json.dumps(VerificationResult.model_json_schema(), separators=(",", ":"))
    context = {
        "trial": {
            "trial_id": trial.trial_id,
            "eligibility_text": trial.eligibility_text,
        },
        "patient": patient.model_dump(mode="json"),
        "normalized_evidence": context_builder.build(criteria, criterion_assessments),
        "trial_assessment": trial_assessment.model_dump(mode="json"),
    }
    return f"""Verify this pre-screening evidence package.

Evidence package:
{json.dumps(context, separators=(",", ":"), ensure_ascii=False)}

Required response schema:
{schema}
"""


def _validate_input_consistency(
    criteria: list[EligibilityCriterion],
    criterion_assessments: list[CriterionAssessment],
    trial_assessment: TrialAssessment,
) -> None:
    criterion_ids = [item.criterion_id for item in criteria]
    assessment_ids = [item.criterion_id for item in criterion_assessments]
    if criterion_ids != assessment_ids:
        raise ValueError("criterion_assessments must match criteria in source order")
    if trial_assessment.criterion_assessments != criterion_assessments:
        raise ValueError("trial_assessment must contain the supplied criterion assessments")


def _validate_finding_ids(
    result: VerificationResult, criteria: list[EligibilityCriterion]
) -> None:
    criterion_ids = {item.criterion_id for item in criteria}
    invalid_ids = {
        finding.criterion_id
        for finding in result.findings
        if finding.criterion_id is not None and finding.criterion_id not in criterion_ids
    }
    if invalid_ids:
        raise VerificationError(
            "Verifier referenced criterion IDs not present in the supplied extraction"
        )


def _parse_result(response: str, criteria: list[EligibilityCriterion]) -> VerificationResult:
    try:
        result = VerificationResult.model_validate_json(response)
    except (ValidationError, ValueError) as error:
        raise VerificationError("Verifier returned invalid structured output") from error
    _validate_finding_ids(result, criteria)
    return result


def _calibrate_supported_missing_data(
    result: VerificationResult, assessments: list[CriterionAssessment]
) -> VerificationResult:
    """Prevent a missing-data-only escalation from overriding supported UNKNOWN truth."""

    unresolved = [
        assessment
        for assessment in assessments
        if assessment.status is CriterionStatus.UNKNOWN
    ]
    missing_data_only = bool(unresolved) and all(
        assessment.missing_information and not assessment.requires_human_review
        for assessment in unresolved
    )
    explicit_conflict = any(
        "conflict" in finding.finding.casefold() for finding in result.findings
    )
    assessments_by_id = {assessment.criterion_id: assessment for assessment in assessments}
    explicit_human_issue = any(
        finding.requires_human_review
        and finding.criterion_id is not None
        and assessments_by_id.get(finding.criterion_id) is not None
        and assessments_by_id[finding.criterion_id].requires_human_review
        for finding in result.findings
    )
    if (
        result.status is VerificationStatus.HUMAN_REVIEW
        and missing_data_only
        and not explicit_conflict
        and not explicit_human_issue
    ):
        return VerificationResult(
            status=VerificationStatus.APPROVED,
            summary_reason=(
                "Explicit structured missing information supports the current UNKNOWN "
                "assessment."
            ),
        )
    return result
