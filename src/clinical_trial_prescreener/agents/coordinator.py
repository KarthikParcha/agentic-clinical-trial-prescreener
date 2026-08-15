"""Bounded routing decisions for the pre-screening workflow."""

import json
from typing import Protocol

from pydantic import ValidationError

from clinical_trial_prescreener.config import CoordinatorSettings
from clinical_trial_prescreener.domain.assessment import (
    CoordinatorAction,
    CoordinatorDecision,
    TrialAssessment,
    TrialAssessmentStatus,
    VerificationResult,
    VerificationStatus,
)


class CoordinatorClient(Protocol):
    """The JSON-generation capability needed only for ambiguous routing."""

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return one JSON-object response."""


SYSTEM_PROMPT = """You are a bounded coordinator for a clinical-trial pre-screening workflow.

Choose exactly one next workflow action from the supplied response schema. You decide
only the next action; you do not evaluate criteria or retrieve, change, or infer data.
Never declare a patient ELIGIBLE or INELIGIBLE. Never invent patient facts, alter trial
criteria, recommend diagnosis or treatment, bypass human review, or create unlimited
retries. Missing patient information remains missing.

Use HUMAN_REVIEW if the structured state cannot be routed safely. Return JSON only."""


class CoordinatorAgent:
    """Choose one finite next action while leaving all workflow execution to callers."""

    def __init__(
        self,
        client: CoordinatorClient | None = None,
        settings: CoordinatorSettings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or CoordinatorSettings()

    @property
    def max_reevaluation_count(self) -> int:
        """Expose the finite coordinator limit to the orchestration guardrail."""

        return self._settings.max_reevaluation_count

    async def decide(
        self,
        *,
        patient_id: str,
        trial_id: str,
        trial_assessment: TrialAssessment,
        verification_result: VerificationResult,
        missing_information: list[str],
        retry_count: int,
        reevaluation_count: int,
    ) -> CoordinatorDecision:
        """Return a decision only; no evaluation, retrieval, mutation, or retry occurs here."""

        _validate_state(
            patient_id,
            trial_id,
            trial_assessment,
            retry_count,
            reevaluation_count,
        )
        deterministic = self._deterministic_decision(
            trial_assessment=trial_assessment,
            verification_result=verification_result,
            missing_information=missing_information,
            retry_count=retry_count,
            reevaluation_count=reevaluation_count,
        )
        if deterministic is not None:
            return deterministic

        if self._client is None:
            return _human_review_fallback("No coordinator LLM client is configured.")

        try:
            response = await self._client.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=_coordinator_prompt(
                    patient_id=patient_id,
                    trial_id=trial_id,
                    trial_assessment=trial_assessment,
                    verification_result=verification_result,
                    missing_information=missing_information,
                    retry_count=retry_count,
                    reevaluation_count=reevaluation_count,
                    settings=self._settings,
                ),
            )
        except Exception as error:  # noqa: BLE001 - external provider errors need safe fallback
            return _human_review_fallback(
                "Coordinator LLM provider failure.", fallback_reason=type(error).__name__
            )

        try:
            decision = CoordinatorDecision.model_validate_json(response)
        except (ValidationError, ValueError):
            return _human_review_fallback(
                "Coordinator LLM returned invalid structured output.",
                fallback_reason="schema_validation_failure",
            )

        if decision.action is CoordinatorAction.RETRY and retry_count >= self._settings.max_retry_count:
            return _human_review_fallback("Coordinator retry limit has been reached.")
        if (
            decision.action is CoordinatorAction.REEVALUATE
            and reevaluation_count >= self._settings.max_reevaluation_count
        ):
            return _human_review_fallback("Coordinator reevaluation limit has been reached.")
        return decision.model_copy(update={"used_llm": True})

    def _deterministic_decision(
        self,
        *,
        trial_assessment: TrialAssessment,
        verification_result: VerificationResult,
        missing_information: list[str],
        retry_count: int,
        reevaluation_count: int,
    ) -> CoordinatorDecision | None:
        if reevaluation_count >= self._settings.max_reevaluation_count:
            return _human_review_fallback("Maximum reevaluation count has been reached.")
        if retry_count >= self._settings.max_retry_count:
            return _human_review_fallback("Maximum retry count has been reached.")
        if verification_result.status is VerificationStatus.HUMAN_REVIEW:
            return _human_review_fallback("Verification requires human review.")
        if verification_result.status in {
            VerificationStatus.REQUIRES_REEVALUATION,
            VerificationStatus.CORRECTED,
        }:
            return CoordinatorDecision(
                action=CoordinatorAction.REEVALUATE,
                reason="Verification identified an assessment requiring reevaluation.",
            )
        if trial_assessment.status is TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED:
            return _human_review_fallback("Trial assessment requires human review.")
        if (
            verification_result.status is VerificationStatus.APPROVED
            and trial_assessment.status is TrialAssessmentStatus.POSSIBLE_MATCH
        ):
            return CoordinatorDecision(
                action=CoordinatorAction.COMPLETE,
                reason="The possible-match assessment was independently approved.",
            )
        if (
            verification_result.status is VerificationStatus.APPROVED
            and trial_assessment.status is TrialAssessmentStatus.INSUFFICIENT_INFORMATION
            and _meaningful(missing_information)
        ):
            return CoordinatorDecision(
                action=CoordinatorAction.REQUEST_INFORMATION,
                reason="Approved assessment is blocked by meaningful missing information.",
            )
        return None


def _coordinator_prompt(
    *,
    patient_id: str,
    trial_id: str,
    trial_assessment: TrialAssessment,
    verification_result: VerificationResult,
    missing_information: list[str],
    retry_count: int,
    reevaluation_count: int,
    settings: CoordinatorSettings,
) -> str:
    schema = json.dumps(CoordinatorDecision.model_json_schema(), separators=(",", ":"))
    context = {
        "patient_id": patient_id,
        "trial_id": trial_id,
        "trial_assessment": trial_assessment.model_dump(mode="json"),
        "verification_result": verification_result.model_dump(mode="json"),
        "missing_information": missing_information,
        "retry_count": retry_count,
        "reevaluation_count": reevaluation_count,
        "limits": {
            "max_retry_count": settings.max_retry_count,
            "max_reevaluation_count": settings.max_reevaluation_count,
        },
    }
    return f"""Choose the safest one next workflow action for this state.

Structured state:
{json.dumps(context, separators=(',', ':'), ensure_ascii=False)}

Required response schema:
{schema}
"""


def _validate_state(
    patient_id: str,
    trial_id: str,
    trial_assessment: TrialAssessment,
    retry_count: int,
    reevaluation_count: int,
) -> None:
    if not patient_id.strip() or not trial_id.strip():
        raise ValueError("patient_id and trial_id must not be blank")
    if trial_assessment.trial_id != trial_id:
        raise ValueError("trial_assessment trial_id must match trial_id")
    if retry_count < 0 or reevaluation_count < 0:
        raise ValueError("retry_count and reevaluation_count must not be negative")


def _meaningful(items: list[str]) -> bool:
    return any(item.strip() for item in items)


def _human_review_fallback(
    reason: str, *, fallback_reason: str | None = None
) -> CoordinatorDecision:
    return CoordinatorDecision(
        action=CoordinatorAction.HUMAN_REVIEW,
        reason=reason,
        requires_human_review=True,
        fallback_reason=fallback_reason,
    )
