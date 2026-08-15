"""Run the live Groq-backed NCT07438444 pre-screening workflow smoke check."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from clinical_trial_prescreener.agents.coordinator import CoordinatorAgent
from clinical_trial_prescreener.agents.verifier import VerificationAgent
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.infrastructure.clinicaltrials.normalizer import (
    normalize_trial,
)
from clinical_trial_prescreener.infrastructure.llm.groq_client import GroqClient
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.criteria_extraction import (
    CriteriaExtractionError,
    CriteriaExtractionService,
)
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from clinical_trial_prescreener.workflow.graph import PrescreeningWorkflow
from clinical_trial_prescreener.workflow.state import initial_workflow_state
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

TRIAL_FIXTURE = ROOT / "tests" / "fixtures" / "type2_diabetes_recruiting_india.json.json"
TRIAL_ID = "NCT07438444"


class CapturedCriteriaExtractor:
    """Provide one already live-validated extraction to the graph's extract node."""

    def __init__(self, criteria: list[EligibilityCriterion]) -> None:
        self._criteria = criteria

    async def extract(self, source: object, **_: object) -> list[EligibilityCriterion]:
        return [criterion.model_copy(deep=True) for criterion in self._criteria]


def load_trial():
    """Normalize the existing ClinicalTrials.gov source fixture for the requested trial."""

    fixture = json.loads(TRIAL_FIXTURE.read_text(encoding="utf-8"))
    raw_study = next(
        study
        for study in fixture["studies"]
        if study["protocolSection"]["identificationModule"]["nctId"] == TRIAL_ID
    )
    return normalize_trial(raw_study)


async def run() -> dict[str, Any]:
    """Execute every live workflow component once and return only final state."""

    patient = synthetic_patient()
    trial = load_trial()
    groq_client = GroqClient()
    try:
        try:
            criteria = await CriteriaExtractionService(groq_client).extract(trial)
        except CriteriaExtractionError as error:
            error_state: dict[str, Any] = {
                "patient": patient,
                "trial": trial,
                "retry_count": 0,
                "reevaluation_count": 0,
                "error": {
                    "node": "extract",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "category": error.category.value,
                },
            }
            if error.validation_category is not None:
                error_state["error"]["validation_category"] = (
                    error.validation_category.value
                )
            return error_state
        workflow = PrescreeningWorkflow(
            criteria_extractor=CapturedCriteriaExtractor(criteria),  # type: ignore[arg-type]
            eligibility_evaluator=EligibilityEvaluator(reference_date=REFERENCE_DATE),
            assessment_service=AssessmentService(),
            verification_agent=VerificationAgent(groq_client),
            coordinator_agent=CoordinatorAgent(groq_client),
        ).compile()
        return await workflow.ainvoke(
            initial_workflow_state(patient, trial),
            {"recursion_limit": 20},
        )
    finally:
        await groq_client.aclose()


def print_summary(state: dict[str, Any]) -> None:
    """Print a compact, non-sensitive summary without prompts or model payloads."""

    patient = state["patient"]
    trial = state["trial"]
    criteria = state.get("criteria", [])
    assessments = state.get("criterion_assessments", [])
    trial_assessment = state.get("trial_assessment")
    verification_result = state.get("verification_result")
    coordinator_decision = state.get("coordinator_decision")

    print(f"Patient: {patient.patient_id}")
    print(f"Trial: {trial.trial_id}")
    print(f"Criteria count: {len(criteria)}")
    print("Criterion assessments:")
    for assessment in assessments:
        print(f"{assessment.criterion_id} -> {assessment.status.value}")
    print(
        "Trial assessment: "
        f"{trial_assessment.status.value if trial_assessment is not None else 'NOT_AVAILABLE'}"
    )
    print(
        "Verification result: "
        f"{verification_result.status.value if verification_result is not None else 'NOT_AVAILABLE'}"
    )
    print(
        "Coordinator action: "
        f"{coordinator_decision.action.value if coordinator_decision is not None else 'NOT_AVAILABLE'}"
    )
    print(f"Reevaluation count: {state.get('reevaluation_count', 0)}")
    print("Missing information:")
    for item in state.get("missing_information", []):
        print(f"- {item}")
    if not state.get("missing_information"):
        print("- None")
    if error := state.get("error"):
        diagnostic = f"Workflow error: {error['node']} / {error['error_type']}"
        if category := error.get("category"):
            diagnostic += f" / {category}"
        if validation_category := error.get("validation_category"):
            diagnostic += f" / {validation_category}"
        print(diagnostic)
        print("Final workflow outcome: TERMINATED_WITH_ERROR")
    else:
        action = coordinator_decision.action.value if coordinator_decision is not None else "NO_ACTION"
        print(f"Final workflow outcome: ENDED_AFTER_{action}")
    if trace := state.get("trace"):
        print("Trace:")
        for step in trace.steps:
            detail = step.decision or step.output_summary or step.error or "completed"
            print(f"- {step.step_name}: {step.status} ({step.duration_ms} ms) {detail}")


def main() -> None:
    print_summary(asyncio.run(run()))


if __name__ == "__main__":
    main()
