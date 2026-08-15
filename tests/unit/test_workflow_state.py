from clinical_trial_prescreener.domain.assessment import (
    CoordinatorAction,
    CoordinatorDecision,
)
from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    StudyType,
    TrialStatus,
)
from clinical_trial_prescreener.workflow.state import initial_workflow_state
from tests.unit.test_patient_fact_resolver import synthetic_patient


def trial() -> ClinicalTrial:
    return ClinicalTrial(
        trial_id="NCT07438444",
        title="Workflow state test",
        status=TrialStatus.RECRUITING,
        study_type=StudyType.INTERVENTIONAL,
        eligibility_text="Eligibility source fixture.",
    )


def test_initial_workflow_state_accepts_patient_and_trial() -> None:
    patient = synthetic_patient()
    state = initial_workflow_state(patient, trial())

    assert state["patient"] == patient
    assert state["trial"].trial_id == "NCT07438444"
    assert state["retry_count"] == 0
    assert state["reevaluation_count"] == 0
    assert "criteria" not in state


def test_later_workflow_state_fields_can_be_populated() -> None:
    state = initial_workflow_state(synthetic_patient(), trial())
    decision = CoordinatorDecision(
        action=CoordinatorAction.COMPLETE,
        reason="Test completion.",
    )

    state["criteria"] = []
    state["criterion_assessments"] = []
    state["missing_information"] = ["heart failure hospitalization history"]
    state["coordinator_decision"] = decision
    state["error"] = {
        "node": "verify",
        "error_type": "VerificationError",
        "message": "Recorded for a future workflow failure path.",
    }

    assert state["coordinator_decision"] == decision
    assert state["missing_information"] == ["heart failure hospitalization history"]
