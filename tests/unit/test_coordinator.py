import asyncio
import json
from collections.abc import Awaitable
from typing import Any

from clinical_trial_prescreener.agents.coordinator import CoordinatorAgent
from clinical_trial_prescreener.config import CoordinatorSettings
from clinical_trial_prescreener.domain.assessment import (
    CoordinatorAction,
    CriterionAssessment,
    CriterionStatus,
    EvaluationMethod,
    TrialAssessment,
    TrialAssessmentStatus,
    VerificationResult,
    VerificationStatus,
)
from clinical_trial_prescreener.domain.criterion import CriterionType


class StubCoordinatorClient:
    def __init__(self, response: str | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def run(coroutine: Awaitable[Any]) -> Any:
    return asyncio.run(coroutine)


def assessment(status: TrialAssessmentStatus) -> TrialAssessment:
    criterion_status = (
        CriterionStatus.UNKNOWN
        if status is TrialAssessmentStatus.INSUFFICIENT_INFORMATION
        else CriterionStatus.MET
    )
    criterion = CriterionAssessment(
        criterion_id="EXC-002",
        criterion_type=CriterionType.EXCLUSION,
        status=criterion_status,
        reason="Test evidence.",
        trial_evidence="Test criterion.",
        missing_information=(
            ["heart failure hospitalization history"]
            if criterion_status is CriterionStatus.UNKNOWN
            else []
        ),
        evaluation_method=EvaluationMethod.DETERMINISTIC,
        requires_human_review=status is TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED,
    )
    return TrialAssessment(
        trial_id="NCT07438444",
        status=status,
        criterion_assessments=[criterion],
        unknown_criterion_ids=(
            [criterion.criterion_id] if criterion_status is CriterionStatus.UNKNOWN else []
        ),
        human_review_criterion_ids=(
            [criterion.criterion_id]
            if status is TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED
            else []
        ),
        missing_information=criterion.missing_information,
        summary_reason="Test aggregate.",
        requires_human_review=status is TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED,
    )


def verification(status: VerificationStatus) -> VerificationResult:
    return VerificationResult(
        status=status,
        findings=(
            []
            if status is VerificationStatus.APPROVED
            else [
                {
                    "criterion_id": "EXC-002",
                    "finding": "Test verification concern.",
                    "recommended_status": "UNKNOWN",
                }
            ]
        ),
        summary_reason="Test verification.",
        requires_human_review=status is VerificationStatus.HUMAN_REVIEW,
    )


def decide(
    agent: CoordinatorAgent,
    *,
    trial_status: TrialAssessmentStatus,
    verification_status: VerificationStatus,
    missing: list[str] | None = None,
    retry_count: int = 0,
    reevaluation_count: int = 0,
) -> Any:
    return run(
        agent.decide(
            patient_id="DEMO-P001",
            trial_id="NCT07438444",
            trial_assessment=assessment(trial_status),
            verification_result=verification(verification_status),
            missing_information=missing or [],
            retry_count=retry_count,
            reevaluation_count=reevaluation_count,
        )
    )


def test_approved_possible_match_completes_without_llm() -> None:
    client = StubCoordinatorClient("unused")

    result = decide(
        CoordinatorAgent(client),
        trial_status=TrialAssessmentStatus.POSSIBLE_MATCH,
        verification_status=VerificationStatus.APPROVED,
    )

    assert result.action is CoordinatorAction.COMPLETE
    assert not client.calls


def test_verification_reevaluation_routes_without_llm() -> None:
    result = decide(
        CoordinatorAgent(),
        trial_status=TrialAssessmentStatus.POSSIBLE_MATCH,
        verification_status=VerificationStatus.REQUIRES_REEVALUATION,
    )

    assert result.action is CoordinatorAction.REEVALUATE


def test_approved_insufficient_information_requests_missing_information() -> None:
    result = decide(
        CoordinatorAgent(),
        trial_status=TrialAssessmentStatus.INSUFFICIENT_INFORMATION,
        verification_status=VerificationStatus.APPROVED,
        missing=["heart failure hospitalization history"],
    )

    assert result.action is CoordinatorAction.REQUEST_INFORMATION


def test_human_review_assessment_routes_to_human_review() -> None:
    result = decide(
        CoordinatorAgent(),
        trial_status=TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED,
        verification_status=VerificationStatus.APPROVED,
    )

    assert result.action is CoordinatorAction.HUMAN_REVIEW
    assert result.requires_human_review


def test_max_retry_limit_never_returns_retry() -> None:
    client = StubCoordinatorClient(
        json.dumps({"action": "RETRY", "reason": "Try provider once more."})
    )
    agent = CoordinatorAgent(client, CoordinatorSettings(max_retry_count=1))

    result = decide(
        agent,
        trial_status=TrialAssessmentStatus.UNLIKELY_MATCH,
        verification_status=VerificationStatus.APPROVED,
        retry_count=1,
    )

    assert result.action is CoordinatorAction.HUMAN_REVIEW
    assert not client.calls


def test_max_reevaluation_limit_routes_to_human_review() -> None:
    result = decide(
        CoordinatorAgent(settings=CoordinatorSettings()),
        trial_status=TrialAssessmentStatus.POSSIBLE_MATCH,
        verification_status=VerificationStatus.REQUIRES_REEVALUATION,
        reevaluation_count=1,
    )

    assert result.action is CoordinatorAction.HUMAN_REVIEW


def test_invalid_llm_action_is_distinguished_and_escalated() -> None:
    client = StubCoordinatorClient(json.dumps({"action": "DELETE_TRIAL", "reason": "No."}))

    result = decide(
        CoordinatorAgent(client),
        trial_status=TrialAssessmentStatus.UNLIKELY_MATCH,
        verification_status=VerificationStatus.APPROVED,
    )

    assert result.action is CoordinatorAction.HUMAN_REVIEW
    assert result.fallback_reason == "schema_validation_failure"
    assert len(client.calls) == 1


def test_provider_failure_is_distinguished_and_safely_escalated() -> None:
    client = StubCoordinatorClient(RuntimeError("provider unavailable"))

    result = decide(
        CoordinatorAgent(client),
        trial_status=TrialAssessmentStatus.UNLIKELY_MATCH,
        verification_status=VerificationStatus.APPROVED,
    )

    assert result.action is CoordinatorAction.HUMAN_REVIEW
    assert result.fallback_reason == "RuntimeError"


def test_ambiguous_llm_decision_uses_one_allowed_action() -> None:
    client = StubCoordinatorClient(
        json.dumps({"action": "RETRY", "reason": "A transient workflow issue is possible."})
    )

    result = decide(
        CoordinatorAgent(client),
        trial_status=TrialAssessmentStatus.UNLIKELY_MATCH,
        verification_status=VerificationStatus.APPROVED,
    )

    assert result.action is CoordinatorAction.RETRY
    assert result.used_llm
    assert len(client.calls) == 1
