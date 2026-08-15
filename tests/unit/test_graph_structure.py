from types import SimpleNamespace

import pytest

from clinical_trial_prescreener.domain.assessment import (
    CoordinatorAction,
    CoordinatorDecision,
)
from clinical_trial_prescreener.workflow.graph import (
    PrescreeningWorkflow,
    route_after_coordinate,
)
from clinical_trial_prescreener.workflow.state import PrescreeningWorkflowState
from tests.unit.test_patient_fact_resolver import synthetic_patient
from tests.unit.test_workflow_state import trial


def state_for(action: CoordinatorAction) -> PrescreeningWorkflowState:
    return {
        "patient": synthetic_patient(),
        "trial": trial(),
        "coordinator_decision": CoordinatorDecision(
            action=action,
            reason="Test route.",
            requires_human_review=action is CoordinatorAction.HUMAN_REVIEW,
        ),
    }


def test_graph_compiles_with_the_five_explicit_nodes() -> None:
    workflow = PrescreeningWorkflow(
        criteria_extractor=object(),  # type: ignore[arg-type]
        eligibility_evaluator=object(),  # type: ignore[arg-type]
        assessment_service=object(),  # type: ignore[arg-type]
        verification_agent=object(),  # type: ignore[arg-type]
        coordinator_agent=SimpleNamespace(max_reevaluation_count=1),  # type: ignore[arg-type]
    )

    graph = workflow.compile()

    assert {"extract", "evaluate", "aggregate", "verify", "coordinate"}.issubset(
        graph.nodes
    )


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (CoordinatorAction.COMPLETE, "complete"),
        (CoordinatorAction.REQUEST_INFORMATION, "request_information"),
        (CoordinatorAction.HUMAN_REVIEW, "human_review"),
        (CoordinatorAction.REEVALUATE, "evaluate"),
    ],
)
def test_coordinator_actions_route_to_expected_destinations(
    action: CoordinatorAction, expected: str
) -> None:
    assert route_after_coordinate(state_for(action)) == expected


def test_unsupported_coordinator_action_fails_safely() -> None:
    state = state_for(CoordinatorAction.COMPLETE)
    state["coordinator_decision"] = SimpleNamespace(action="DELETE_TRIAL")  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Unsupported coordinator action"):
        route_after_coordinate(state)
