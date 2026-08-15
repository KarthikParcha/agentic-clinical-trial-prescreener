"""A small, explicit LangGraph wrapper around existing pre-screening components."""

from functools import partial
from time import perf_counter
from typing import Literal, cast

from langgraph.graph import END, START, StateGraph

from clinical_trial_prescreener.agents.coordinator import CoordinatorAgent
from clinical_trial_prescreener.agents.verifier import (
    VerificationAgent,
    VerificationError,
)
from clinical_trial_prescreener.domain.assessment import (
    CoordinatorAction,
    CoordinatorDecision,
    TrialAssessment,
    TrialAssessmentStatus,
    VerificationResult,
)
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.infrastructure.llm.groq_client import GroqClientError
from clinical_trial_prescreener.observability.trace_collector import TraceCollector
from clinical_trial_prescreener.observability.trace_models import (
    TraceStep,
    WorkflowTrace,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.criteria_extraction import (
    CriteriaExtractionError,
    ExtractionCanonicalization,
)
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from clinical_trial_prescreener.services.prescreening_service import CriteriaExtractor
from clinical_trial_prescreener.workflow.state import (
    PrescreeningWorkflowState,
    WorkflowError,
)

Route = Literal[
    "complete",
    "request_information",
    "human_review",
    "fail",
    "evaluate",
    "retry",
    "verify",
    "coordinate",
]


class PrescreeningWorkflow:
    """Connect existing components; no clinical or workflow policy is duplicated here."""

    def __init__(
        self,
        *,
        criteria_extractor: CriteriaExtractor,
        eligibility_evaluator: EligibilityEvaluator,
        assessment_service: AssessmentService,
        verification_agent: VerificationAgent,
        coordinator_agent: CoordinatorAgent,
        trace_collector: TraceCollector | None = None,
    ) -> None:
        self._criteria_extractor = criteria_extractor
        self._eligibility_evaluator = eligibility_evaluator
        self._assessment_service = assessment_service
        self._verification_agent = verification_agent
        self._coordinator_agent = coordinator_agent
        self._max_reevaluation_count = coordinator_agent.max_reevaluation_count
        self._trace_collector = trace_collector or TraceCollector()

    def compile(self):
        """Compile the initial fixed workflow and its bounded coordinator branch."""

        graph = StateGraph(PrescreeningWorkflowState)
        graph.add_node("extract", self.extract)
        graph.add_node("evaluate", self.evaluate)
        graph.add_node("aggregate", self.aggregate)
        graph.add_node("verify", self.verify)
        graph.add_node("coordinate", self.coordinate)

        graph.add_edge(START, "extract")
        graph.add_conditional_edges(
            "extract",
            partial(route_after_node_error, next_node="evaluate"),
            {"evaluate": "evaluate", "error": END},
        )
        graph.add_edge("evaluate", "aggregate")
        graph.add_conditional_edges(
            "aggregate",
            route_after_aggregate,
            {"verify": "verify", "coordinate": "coordinate"},
        )
        graph.add_conditional_edges(
            "verify",
            partial(route_after_node_error, next_node="coordinate"),
            {"coordinate": "coordinate", "error": END},
        )
        graph.add_conditional_edges(
            "coordinate",
            partial(
                route_after_coordinate,
                max_reevaluation_count=self._max_reevaluation_count,
            ),
            {
                "complete": END,
                "request_information": END,
                "human_review": END,
                "fail": END,
                "evaluate": "evaluate",
                # RETRY has no retry implementation in Day 31, so it terminates safely.
                "retry": END,
            },
        )
        return graph.compile()

    async def extract(
        self, state: PrescreeningWorkflowState
    ) -> dict[str, list[EligibilityCriterion] | WorkflowError]:
        self._trace_collector.start(
            patient_id=state["patient"].patient_id, trial_id=_trial(state).trial_id
        )
        started = perf_counter()
        try:
            criteria = await self._criteria_extractor.extract(_trial(state))
        except (CriteriaExtractionError, GroqClientError) as error:
            workflow_error = _workflow_error("extract", error)
            canonicalizations = _canonicalization_records(error)
            if not canonicalizations:
                canonicalizations = _canonicalization_records(
                    self._criteria_extractor
                )
            trace = self._record_trace(
                "extract",
                started,
                status="ERROR",
                error=workflow_error["error_type"],
                output_summary={
                    **_extraction_attempt_summary(self._criteria_extractor, error),
                    "canonicalization_applied": bool(canonicalizations),
                    "canonicalizations": canonicalizations,
                    "failure_category": workflow_error.get("category"),
                    "validation_stage": workflow_error.get("validation_category"),
                },
            )
            self._trace_collector.complete("ERROR")
            return {
                "error": workflow_error,
                "trace": trace,
            }
        return {
            "criteria": criteria,
            "trace": self._record_trace(
                "extract",
                started,
                output_summary={
                    "criteria_count": len(criteria),
                    "validation": "passed",
                    "validation_stage": None,
                    **_extraction_attempt_summary(self._criteria_extractor),
                    "canonicalization_applied": bool(
                        _canonicalization_records(self._criteria_extractor)
                    ),
                    "canonicalizations": _canonicalization_records(
                        self._criteria_extractor
                    ),
                },
            ),
        }

    def evaluate(
        self, state: PrescreeningWorkflowState
    ) -> dict[str, object]:
        started = perf_counter()
        criteria = _criteria(state)
        patient = state["patient"]
        updates: dict[str, list[object] | int] = {
            "criterion_assessments": [
                self._eligibility_evaluator.evaluate(criterion, patient)
                for criterion in criteria
            ]
        }
        decision = state.get("coordinator_decision")
        if decision is not None and decision.action is CoordinatorAction.REEVALUATE:
            updates["reevaluation_count"] = state.get("reevaluation_count", 0) + 1
        assessments = updates["criterion_assessments"]
        updates["trace"] = self._record_trace(
            "evaluate",
            started,
            output_summary={
                "MET": sum(item.status.value == "MET" for item in assessments),
                "NOT_MET": sum(item.status.value == "NOT_MET" for item in assessments),
                "UNKNOWN": sum(item.status.value == "UNKNOWN" for item in assessments),
            },
        )
        return updates

    def aggregate(self, state: PrescreeningWorkflowState) -> dict[str, object]:
        started = perf_counter()
        trial_assessment = self._assessment_service.aggregate(
            _trial(state).trial_id,
            cast(list, state["criterion_assessments"]),
        )
        return {
            "trial_assessment": trial_assessment,
            "missing_information": trial_assessment.missing_information,
            "trace": self._record_trace(
                "aggregate",
                started,
                output_summary={
                    "trial_status": trial_assessment.status.value,
                    "blocking": trial_assessment.blocking_criterion_ids,
                    "unknown": trial_assessment.unknown_criterion_ids,
                    "missing_information": trial_assessment.missing_information,
                },
            ),
        }

    async def verify(
        self, state: PrescreeningWorkflowState
    ) -> dict[str, VerificationResult | WorkflowError]:
        started = perf_counter()
        try:
            result = await self._verification_agent.verify(
                trial=_trial(state),
                patient=state["patient"],
                criteria=_criteria(state),
                criterion_assessments=cast(list, state["criterion_assessments"]),
                trial_assessment=cast(TrialAssessment, state["trial_assessment"]),
            )
        except (VerificationError, GroqClientError) as error:
            workflow_error = _workflow_error("verify", error)
            trace = self._record_trace(
                "verify", started, status="ERROR", error=workflow_error["error_type"]
            )
            self._trace_collector.complete("ERROR")
            return {
                "error": workflow_error,
                "trace": trace,
            }
        return {
            "verification_result": result,
            "trace": self._record_trace(
                "verify",
                started,
                output_summary={"verification_status": result.status.value},
                decision=result.summary_reason,
            ),
        }

    async def coordinate(self, state: PrescreeningWorkflowState) -> dict[str, CoordinatorDecision]:
        started = perf_counter()
        trial = _trial(state)
        trial_assessment = cast(TrialAssessment, state["trial_assessment"])
        if trial_assessment.status is TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED:
            decision = CoordinatorDecision(
                action=CoordinatorAction.HUMAN_REVIEW,
                reason="Trial assessment requires human review.",
                requires_human_review=True,
            )
        else:
            decision = await self._coordinator_agent.decide(
                patient_id=state["patient"].patient_id,
                trial_id=trial.trial_id,
                trial_assessment=trial_assessment,
                verification_result=cast(
                    VerificationResult, state["verification_result"]
                ),
                missing_information=state.get("missing_information", []),
                retry_count=state.get("retry_count", 0),
                reevaluation_count=state.get("reevaluation_count", 0),
            )
        trace = self._record_trace(
            "coordinate",
            started,
            output_summary={
                "retry_count": state.get("retry_count", 0),
                "reevaluation_count": state.get("reevaluation_count", 0),
            },
            decision=str(getattr(decision.action, "value", decision.action)),
            metadata={"reason": getattr(decision, "reason", "not available")},
        )
        self._trace_collector.complete(str(getattr(decision.action, "value", decision.action)))
        return {"coordinator_decision": decision, "trace": trace}

    def _record_trace(
        self,
        step_name: str,
        started: float,
        *,
        status: str = "SUCCESS",
        output_summary: dict[str, object] | None = None,
        decision: str | None = None,
        error: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> WorkflowTrace:
        return self._trace_collector.record(
            TraceStep(
                step_name=step_name,
                status=status,
                duration_ms=round((perf_counter() - started) * 1000),
                output_summary=output_summary or {},
                decision=decision,
                error=error,
                metadata=metadata or {},
            )
        )


def build_prescreening_graph(**kwargs: object):
    """Build the Day 31 workflow from already-configured services and agents."""

    return PrescreeningWorkflow(**kwargs).compile()  # type: ignore[arg-type]


def route_after_coordinate(
    state: PrescreeningWorkflowState, *, max_reevaluation_count: int = 1
) -> Route:
    """Translate exactly one coordinator action into a fixed graph destination."""

    decision = state.get("coordinator_decision")
    if decision is None:
        raise ValueError("Coordinator did not provide a decision")
    action = decision.action
    if (
        action is CoordinatorAction.REEVALUATE
        and state.get("reevaluation_count", 0) >= max_reevaluation_count
    ):
        return "human_review"
    routes: dict[CoordinatorAction, Route] = {
        CoordinatorAction.COMPLETE: "complete",
        CoordinatorAction.REQUEST_INFORMATION: "request_information",
        CoordinatorAction.HUMAN_REVIEW: "human_review",
        CoordinatorAction.FAIL: "fail",
        CoordinatorAction.REEVALUATE: "evaluate",
        CoordinatorAction.RETRY: "retry",
    }
    try:
        return routes[action]
    except KeyError as error:
        raise ValueError(f"Unsupported coordinator action: {action!r}") from error


def route_after_aggregate(
    state: PrescreeningWorkflowState,
) -> Literal["verify", "coordinate"]:
    """Bypass automated verification when aggregation already requires a human."""

    assessment = cast(TrialAssessment, state["trial_assessment"])
    if assessment.status is TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED:
        return "coordinate"
    return "verify"


def route_after_node_error(
    state: PrescreeningWorkflowState, *, next_node: Literal["evaluate", "coordinate"]
) -> Literal["evaluate", "coordinate", "error"]:
    """Stop only after a node captured a known provider/application failure."""

    return "error" if "error" in state else next_node


def _workflow_error(node: str, error: Exception) -> WorkflowError:
    workflow_error: WorkflowError = {
        "node": node,
        "error_type": type(error).__name__,
        "message": str(error),
    }
    if isinstance(error, CriteriaExtractionError):
        workflow_error["category"] = error.category.value
        if error.validation_category is not None:
            workflow_error["validation_category"] = error.validation_category.value
        if error.provider_error_code is not None:
            workflow_error["provider_error_code"] = error.provider_error_code
    return workflow_error


def _trial(state: PrescreeningWorkflowState):
    return state["trial"]


def _criteria(state: PrescreeningWorkflowState) -> list[EligibilityCriterion]:
    try:
        return state["criteria"]
    except KeyError as error:
        raise ValueError("Criteria are required before evaluation") from error


def _canonicalization_records(source: object) -> list[dict[str, object]]:
    records = getattr(source, "canonicalizations", None)
    if records is None:
        records = getattr(source, "last_canonicalizations", [])
    return [
        {
            "criterion_path": record.criterion_path,
            "raw_evaluation_type": record.raw_evaluation_type.value,
            "removed_fields": list(record.removed_fields),
        }
        for record in records
        if isinstance(record, ExtractionCanonicalization)
    ]


def _extraction_attempt_summary(
    source: object, error: CriteriaExtractionError | GroqClientError | None = None
) -> dict[str, object]:
    """Expose bounded extraction attempts without capturing provider payloads."""

    if isinstance(error, CriteriaExtractionError):
        provider_attempts = error.provider_attempts
        repair_attempts = error.extraction_repair_attempts
        provider_error_code = error.provider_error_code
    else:
        provider_attempts = getattr(source, "provider_attempts", 0)
        repair_attempts = getattr(source, "extraction_repair_attempts", 0)
        provider_error_code = getattr(source, "provider_error_code", None)
    return {
        "provider_attempts": provider_attempts,
        "extraction_repair_attempts": repair_attempts,
        "repair_attempted": repair_attempts > 0,
        "provider_error_code": provider_error_code,
    }
