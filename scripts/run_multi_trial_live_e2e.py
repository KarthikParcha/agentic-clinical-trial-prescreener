"""Run the bounded live multi-trial V1 acceptance check."""

import asyncio
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from clinical_trial_prescreener.agents.coordinator import CoordinatorAgent
from clinical_trial_prescreener.agents.verifier import VerificationAgent
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.domain.trial import ClinicalTrial
from clinical_trial_prescreener.infrastructure.clinicaltrials.client import (
    ClinicalTrialsClient,
)
from clinical_trial_prescreener.infrastructure.llm.groq_client import GroqClient
from clinical_trial_prescreener.reporting.report_generator import (
    generate_report,
    render_report,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.criteria_extraction import (
    CriteriaExtractionError,
    CriteriaExtractionService,
)
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from clinical_trial_prescreener.services.trial_search import (
    TrialSearchRequest,
    TrialSearchService,
)
from clinical_trial_prescreener.workflow.graph import PrescreeningWorkflow
from clinical_trial_prescreener.workflow.state import initial_workflow_state
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

REPORT_DIRECTORY = ROOT / "tests" / "integration" / "output" / "live_multi_trial"


class CapturedCriteriaExtractor:
    """Pass one live-validated extraction into the existing single-trial graph."""

    def __init__(self, criteria: list[EligibilityCriterion]) -> None:
        self._criteria = criteria

    async def extract(self, source: object, **_: object) -> list[EligibilityCriterion]:
        return [criterion.model_copy(deep=True) for criterion in self._criteria]


@dataclass
class TrialRun:
    trial: ClinicalTrial
    eligibility_characters: int
    eligibility_lines: int
    extraction_passed: bool
    criteria_count: int = 0
    extraction_failure: str | None = None
    met: int = 0
    not_met: int = 0
    unknown: int = 0
    trial_assessment: str | None = None
    verification: str | None = None
    coordinator: str | None = None
    final_outcome: str | None = None
    missing_information: list[str] | None = None
    report_path: Path | None = None


async def run() -> list[TrialRun]:
    """Search live candidates, then process each independently and fail closed."""

    search_client = ClinicalTrialsClient()
    groq_client = GroqClient()
    try:
        trials = await TrialSearchService(search_client).search(
            TrialSearchRequest(
                condition="Type 2 Diabetes",
                country="India",
                max_results=3,
            )
        )
        print_returned_trials(trials)
        runs: list[TrialRun] = []
        for trial in trials:
            runs.append(await process_trial(trial, groq_client))
        return runs
    finally:
        await search_client.aclose()
        await groq_client.aclose()


async def process_trial(trial: ClinicalTrial, groq_client: GroqClient) -> TrialRun:
    """Use the existing V1 graph once for one independently extracted trial."""

    eligibility_text = trial.eligibility_text or ""
    run = TrialRun(
        trial=trial,
        eligibility_characters=len(eligibility_text),
        eligibility_lines=len(eligibility_text.splitlines()),
        extraction_passed=False,
    )
    extractor = CriteriaExtractionService(groq_client)
    try:
        criteria = await extractor.extract(trial)
    except CriteriaExtractionError as error:
        validation = (
            f"/{error.validation_category.value}"
            if error.validation_category is not None
            else ""
        )
        run.extraction_failure = f"{error.category.value}{validation}"
        return run

    run.extraction_passed = True
    run.criteria_count = len(criteria)
    workflow = PrescreeningWorkflow(
        criteria_extractor=CapturedCriteriaExtractor(criteria),  # type: ignore[arg-type]
        eligibility_evaluator=EligibilityEvaluator(reference_date=REFERENCE_DATE),
        assessment_service=AssessmentService(),
        verification_agent=VerificationAgent(groq_client),
        coordinator_agent=CoordinatorAgent(groq_client),
    ).compile()
    state = await workflow.ainvoke(
        initial_workflow_state(synthetic_patient(), trial),
        {"recursion_limit": 20},
    )
    assessments = state.get("criterion_assessments", [])
    run.met = sum(item.status.value == "MET" for item in assessments)
    run.not_met = sum(item.status.value == "NOT_MET" for item in assessments)
    run.unknown = sum(item.status.value == "UNKNOWN" for item in assessments)
    run.missing_information = list(state.get("missing_information", []))
    assessment = state.get("trial_assessment")
    verification = state.get("verification_result")
    coordinator = state.get("coordinator_decision")
    run.trial_assessment = assessment.status.value if assessment is not None else None
    run.verification = verification.status.value if verification is not None else None
    run.coordinator = coordinator.action.value if coordinator is not None else None
    run.final_outcome = (
        state["trace"].final_outcome if state.get("trace") is not None else "FAILED"
    )
    if assessment is not None:
        report = generate_report(
            patient=synthetic_patient(),
            trial=trial,
            trial_assessment=assessment,
            verification_result=verification,
            coordinator_decision=coordinator,
            criteria=criteria,
            reference_date=REFERENCE_DATE,
        )
        REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        run.report_path = REPORT_DIRECTORY / f"{trial.trial_id}.md"
        run.report_path.write_text(render_report(report), encoding="utf-8")
    return run


def print_returned_trials(trials: list[ClinicalTrial]) -> None:
    """Print the live search set without raw API payloads."""

    print("Returned trials:")
    for trial in trials:
        print(f"- {trial.trial_id}: {trial.title}")


def print_summary(runs: list[TrialRun]) -> None:
    """Render the compact acceptance summary without clinical conclusions."""

    print("\nMULTI-TRIAL LIVE E2E")
    print("====================")
    print("\nPatient: DEMO-P001")
    print(f"\nSearch results: {len(runs)}")
    for index, item in enumerate(runs, start=1):
        print(f"\nTRIAL {index}")
        print(f"NCT ID: {item.trial.trial_id}")
        print(f"Title: {item.trial.title}")
        print(
            "Eligibility text: "
            f"{item.eligibility_characters} characters, {item.eligibility_lines} lines"
        )
        print(f"Extraction: {'PASS' if item.extraction_passed else 'FAIL'}")
        print(f"Criteria count: {item.criteria_count}")
        if item.extraction_failure is not None:
            print(f"Extraction failure category: {item.extraction_failure}")
        print(f"MET: {item.met}")
        print(f"NOT_MET: {item.not_met}")
        print(f"UNKNOWN: {item.unknown}")
        print(f"Trial assessment: {item.trial_assessment or 'NOT_EVALUATED'}")
        print(f"Verification: {item.verification or 'NOT_EVALUATED'}")
        print(f"Coordinator: {item.coordinator or 'NOT_EVALUATED'}")
        print(f"Final outcome: {item.final_outcome or 'FAILED'}")
        print(
            "Missing information: "
            + (", ".join(item.missing_information or []) or "None")
        )
        print(f"Report generated: {'YES' if item.report_path is not None else 'NO'}")

    assessments = Counter(item.trial_assessment for item in runs if item.trial_assessment)
    actions = Counter(item.coordinator for item in runs if item.coordinator)
    print("\nSUMMARY")
    print(f"\nTrials searched: {len(runs)}")
    print(f"Extraction passed: {sum(item.extraction_passed for item in runs)}")
    print(f"Extraction failed: {sum(not item.extraction_passed for item in runs)}")
    print(f"Reports generated: {sum(item.report_path is not None for item in runs)}")
    for status in (
        "POSSIBLE_MATCH",
        "UNLIKELY_MATCH",
        "INSUFFICIENT_INFORMATION",
        "HUMAN_REVIEW_REQUIRED",
    ):
        print(f"\n{status}: {assessments[status]}")
    for action in ("REQUEST_INFORMATION", "COMPLETE", "HUMAN_REVIEW"):
        print(f"{action}: {actions[action]}")
    print(
        "FAILED: "
        f"{sum(item.final_outcome in {'FAILED', 'ERROR'} for item in runs)}"
    )


def main() -> None:
    print_summary(asyncio.run(run()))


if __name__ == "__main__":
    main()
