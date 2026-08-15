import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from clinical_trial_prescreener.domain.assessment import (
    CoordinatorAction,
    CoordinatorDecision,
    CriterionAssessment,
    CriterionStatus,
    EvaluationMethod,
    TrialAssessmentStatus,
    VerificationResult,
    VerificationStatus,
)
from clinical_trial_prescreener.domain.criterion import (
    ComparisonOperator,
    CriterionCategory,
    CriterionType,
    EligibilityCriterion,
    EvaluationType,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.criteria_extraction import (
    CriteriaExtractionError,
    ExtractionCanonicalization,
)
from clinical_trial_prescreener.workflow.graph import PrescreeningWorkflow
from clinical_trial_prescreener.workflow.state import initial_workflow_state
from tests.unit.test_patient_fact_resolver import synthetic_patient
from tests.unit.test_workflow_state import trial


class FakeExtractor:
    def __init__(
        self,
        criteria: list[EligibilityCriterion] | Exception,
        canonicalizations: list[ExtractionCanonicalization] | None = None,
    ) -> None:
        self.criteria = criteria
        self.calls = 0
        self.last_canonicalizations = canonicalizations or []

    async def extract(self, source: object, **_: object) -> list[EligibilityCriterion]:
        self.calls += 1
        if isinstance(self.criteria, Exception):
            raise self.criteria
        return self.criteria


class FakeEvaluator:
    def __init__(self, statuses: list[CriterionStatus]) -> None:
        self.statuses = statuses
        self.calls = 0

    def evaluate(
        self, criterion: EligibilityCriterion, patient: object
    ) -> CriterionAssessment:
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        return CriterionAssessment(
            criterion_id=criterion.criterion_id,
            criterion_type=criterion.criterion_type,
            status=status,
            reason="Fake evaluation.",
            trial_evidence=criterion.original_text,
            missing_information=(
                ["heart failure hospitalization history"]
                if status is CriterionStatus.UNKNOWN
                else []
            ),
            evaluation_method=EvaluationMethod.DETERMINISTIC,
            requires_human_review=criterion.requires_human_review,
        )


class FakeVerifier:
    def __init__(self, results: list[VerificationResult]) -> None:
        self.results = results
        self.calls = 0

    async def verify(self, **_: object) -> VerificationResult:
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result


class FakeCoordinator:
    def __init__(self, decisions: list[object], max_reevaluation_count: int = 1) -> None:
        self.decisions = decisions
        self.max_reevaluation_count = max_reevaluation_count
        self.calls: list[dict[str, object]] = []

    async def decide(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.decisions[min(len(self.calls) - 1, len(self.decisions) - 1)]


def criterion() -> EligibilityCriterion:
    return EligibilityCriterion(
        criterion_id="INC-001",
        criterion_type=CriterionType.INCLUSION,
        category=CriterionCategory.DIAGNOSIS,
        original_text="Type 2 Diabetes is required.",
        evaluation_type=EvaluationType.BOOLEAN,
        field_name="type_2_diabetes",
        operator=ComparisonOperator.EQ,
        value=True,
    )


def human_review_criterion() -> EligibilityCriterion:
    return EligibilityCriterion(
        criterion_id="INC-HUMAN-001",
        criterion_type=CriterionType.INCLUSION,
        category=CriterionCategory.OTHER,
        original_text="The investigator must confirm clinical suitability.",
        evaluation_type=EvaluationType.HUMAN_ONLY,
        requires_human_review=True,
    )


def verification(status: VerificationStatus) -> VerificationResult:
    return VerificationResult(
        status=status,
        summary_reason="Fake verification.",
        findings=[],
        requires_human_review=status is VerificationStatus.HUMAN_REVIEW,
    )


def decision(action: CoordinatorAction) -> CoordinatorDecision:
    return CoordinatorDecision(
        action=action,
        reason="Fake routing decision.",
        requires_human_review=action is CoordinatorAction.HUMAN_REVIEW,
    )


def workflow(
    *,
    evaluator: FakeEvaluator,
    verifier: FakeVerifier,
    coordinator: FakeCoordinator,
    extractor: FakeExtractor | None = None,
) -> PrescreeningWorkflow:
    return PrescreeningWorkflow(
        criteria_extractor=extractor or FakeExtractor([criterion()]),  # type: ignore[arg-type]
        eligibility_evaluator=evaluator,  # type: ignore[arg-type]
        assessment_service=AssessmentService(),
        verification_agent=verifier,  # type: ignore[arg-type]
        coordinator_agent=coordinator,  # type: ignore[arg-type]
    )


def invoke(graph: object) -> dict[str, Any]:
    return asyncio.run(
        graph.ainvoke(  # type: ignore[attr-defined]
            initial_workflow_state(synthetic_patient(), trial()),
            {"recursion_limit": 20},
        )
    )


def test_normal_assessment_completes_at_end() -> None:
    coordinator = FakeCoordinator([decision(CoordinatorAction.COMPLETE)])
    graph = workflow(
        evaluator=FakeEvaluator([CriterionStatus.MET]),
        verifier=FakeVerifier([verification(VerificationStatus.APPROVED)]),
        coordinator=coordinator,
    ).compile()

    result = invoke(graph)

    assert result["coordinator_decision"].action is CoordinatorAction.COMPLETE
    assert result["trial_assessment"].status.value == "POSSIBLE_MATCH"
    trace = result["trace"]
    assert [step.step_name for step in trace.steps] == [
        "extract",
        "evaluate",
        "aggregate",
        "verify",
        "coordinate",
    ]
    assert trace.final_outcome == "COMPLETE"


def test_extraction_canonicalization_is_recorded_in_safe_trace_output() -> None:
    canonicalization = ExtractionCanonicalization(
        criterion_path="criteria.7.children.0",
        raw_evaluation_type=EvaluationType.HUMAN_ONLY,
        removed_fields=["operator", "value"],
    )
    graph = workflow(
        extractor=FakeExtractor([criterion()], [canonicalization]),
        evaluator=FakeEvaluator([CriterionStatus.MET]),
        verifier=FakeVerifier([verification(VerificationStatus.APPROVED)]),
        coordinator=FakeCoordinator([decision(CoordinatorAction.COMPLETE)]),
    ).compile()

    result = invoke(graph)

    extract_step = result["trace"].steps[0]
    assert extract_step.output_summary["canonicalization_applied"] is True
    assert extract_step.output_summary["canonicalizations"] == [
        {
            "criterion_path": "criteria.7.children.0",
            "raw_evaluation_type": "HUMAN_ONLY",
            "removed_fields": ["operator", "value"],
        }
    ]


def test_extraction_trace_separates_provider_and_repair_attempts() -> None:
    extractor = FakeExtractor([criterion()])
    extractor.provider_attempts = 2
    extractor.extraction_repair_attempts = 1
    extractor.provider_error_code = "json_validate_failed"
    graph = workflow(
        extractor=extractor,
        evaluator=FakeEvaluator([CriterionStatus.MET]),
        verifier=FakeVerifier([verification(VerificationStatus.APPROVED)]),
        coordinator=FakeCoordinator([decision(CoordinatorAction.COMPLETE)]),
    ).compile()

    result = invoke(graph)

    assert result["trace"].steps[0].output_summary == {
        "criteria_count": 1,
        "validation": "passed",
        "validation_stage": None,
        "provider_attempts": 2,
        "extraction_repair_attempts": 1,
        "repair_attempted": True,
        "provider_error_code": "json_validate_failed",
        "canonicalization_applied": False,
        "canonicalizations": [],
    }


def test_demo_patient_insufficient_information_requests_information_and_preserves_missing() -> None:
    graph = workflow(
        evaluator=FakeEvaluator([CriterionStatus.UNKNOWN]),
        verifier=FakeVerifier([verification(VerificationStatus.APPROVED)]),
        coordinator=FakeCoordinator([decision(CoordinatorAction.REQUEST_INFORMATION)]),
    ).compile()

    result = invoke(graph)

    assert result["coordinator_decision"].action is CoordinatorAction.REQUEST_INFORMATION
    assert result["missing_information"] == ["heart failure hospitalization history"]


def test_human_review_required_bypasses_verification_and_routes_safely() -> None:
    verifier = FakeVerifier([verification(VerificationStatus.APPROVED)])
    coordinator = FakeCoordinator([decision(CoordinatorAction.COMPLETE)])
    graph = workflow(
        extractor=FakeExtractor([human_review_criterion()]),
        evaluator=FakeEvaluator([CriterionStatus.UNKNOWN]),
        verifier=verifier,
        coordinator=coordinator,
    ).compile()

    result = invoke(graph)

    assert result["trial_assessment"].status is TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED
    assert "verification_result" not in result
    assert result["coordinator_decision"].action is CoordinatorAction.HUMAN_REVIEW
    assert verifier.calls == 0
    assert coordinator.calls == []
    assert result["trace"].final_outcome == "HUMAN_REVIEW"


def test_reevaluation_loops_once_then_completes_with_corrected_assessment() -> None:
    evaluator = FakeEvaluator([CriterionStatus.NOT_MET, CriterionStatus.MET])
    verifier = FakeVerifier(
        [
            verification(VerificationStatus.REQUIRES_REEVALUATION),
            verification(VerificationStatus.APPROVED),
        ]
    )
    coordinator = FakeCoordinator(
        [decision(CoordinatorAction.REEVALUATE), decision(CoordinatorAction.COMPLETE)]
    )
    graph = workflow(
        evaluator=evaluator, verifier=verifier, coordinator=coordinator
    ).compile()

    result = invoke(graph)

    assert evaluator.calls == 2
    assert verifier.calls == 2
    assert result["reevaluation_count"] == 1
    assert coordinator.calls[1]["reevaluation_count"] == 1
    assert result["coordinator_decision"].action is CoordinatorAction.COMPLETE


def test_max_reevaluation_limit_terminates_a_repeated_reevaluation_route() -> None:
    evaluator = FakeEvaluator([CriterionStatus.MET])
    coordinator = FakeCoordinator(
        [decision(CoordinatorAction.REEVALUATE)], max_reevaluation_count=1
    )
    graph = workflow(
        evaluator=evaluator,
        verifier=FakeVerifier([verification(VerificationStatus.REQUIRES_REEVALUATION)]),
        coordinator=coordinator,
    ).compile()

    result = invoke(graph)

    assert evaluator.calls == 2
    assert result["reevaluation_count"] == 1
    assert len(coordinator.calls) == 2


@pytest.mark.parametrize("action", [CoordinatorAction.HUMAN_REVIEW, CoordinatorAction.FAIL])
def test_terminal_coordinator_actions_end_the_graph(action: CoordinatorAction) -> None:
    graph = workflow(
        evaluator=FakeEvaluator([CriterionStatus.MET]),
        verifier=FakeVerifier([verification(VerificationStatus.APPROVED)]),
        coordinator=FakeCoordinator([decision(action)]),
    ).compile()

    result = invoke(graph)

    assert result["coordinator_decision"].action is action


def test_known_extraction_error_is_structured_and_terminates() -> None:
    graph = workflow(
        extractor=FakeExtractor(CriteriaExtractionError("invalid provider response")),
        evaluator=FakeEvaluator([CriterionStatus.MET]),
        verifier=FakeVerifier([verification(VerificationStatus.APPROVED)]),
        coordinator=FakeCoordinator([decision(CoordinatorAction.COMPLETE)]),
    ).compile()

    result = invoke(graph)

    assert result["error"] == {
        "node": "extract",
        "error_type": "CriteriaExtractionError",
        "message": "invalid provider response",
        "category": "PROVIDER_ERROR",
    }


def test_unsupported_coordinator_action_fails_safely() -> None:
    graph = workflow(
        evaluator=FakeEvaluator([CriterionStatus.MET]),
        verifier=FakeVerifier([verification(VerificationStatus.APPROVED)]),
        coordinator=FakeCoordinator([SimpleNamespace(action="DELETE_TRIAL")]),
    ).compile()

    with pytest.raises(ValueError, match="Unsupported coordinator action"):
        invoke(graph)
