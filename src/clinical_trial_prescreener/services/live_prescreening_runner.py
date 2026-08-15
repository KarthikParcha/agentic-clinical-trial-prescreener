"""Bounded live orchestration for one patient across searched trial candidates."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from clinical_trial_prescreener.agents.coordinator import CoordinatorAgent
from clinical_trial_prescreener.agents.verifier import VerificationAgent
from clinical_trial_prescreener.domain.assessment import (
    CoordinatorDecision,
    CriterionAssessment,
    TrialAssessment,
    VerificationResult,
)
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.domain.patient import PatientProfile
from clinical_trial_prescreener.domain.trial import ClinicalTrial
from clinical_trial_prescreener.infrastructure.clinicaltrials.client import (
    ClinicalTrialsClient,
)
from clinical_trial_prescreener.infrastructure.llm.groq_client import GroqClient
from clinical_trial_prescreener.observability.trace_models import WorkflowTrace
from clinical_trial_prescreener.reporting.report_generator import (
    PreScreeningReport,
    generate_report,
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

ProgressCallback = Callable[[str, str, str], None]


class CapturedCriteriaExtractor:
    """Pass one already-validated extraction into the existing single-trial graph."""

    def __init__(self, criteria: list[EligibilityCriterion]) -> None:
        self._criteria = criteria

    async def extract(self, source: object, **_: object) -> list[EligibilityCriterion]:
        return [criterion.model_copy(deep=True) for criterion in self._criteria]


@dataclass(frozen=True)
class LiveTrialResult:
    """One independently processed candidate, including safe extraction failure data."""

    trial: ClinicalTrial
    extraction_error: CriteriaExtractionError | None = None
    criteria: list[EligibilityCriterion] = field(default_factory=list)
    criterion_assessments: list[CriterionAssessment] = field(default_factory=list)
    trial_assessment: TrialAssessment | None = None
    verification_result: VerificationResult | None = None
    coordinator_decision: CoordinatorDecision | None = None
    missing_information: list[str] = field(default_factory=list)
    trace: WorkflowTrace | None = None
    report: PreScreeningReport | None = None
    final_outcome: str | None = None


@dataclass(frozen=True)
class LivePrescreeningRun:
    """An immutable patient snapshot and the results of one bounded live search."""

    run_id: str
    patient_snapshot: PatientProfile
    trials: list[LiveTrialResult] = field(default_factory=list)


async def run_live_prescreening(
    patient: PatientProfile,
    *,
    max_results: int = 3,
    reference_date: date | None = None,
    progress: ProgressCallback | None = None,
) -> LivePrescreeningRun:
    """Run the existing V1 flow once per searched trial without changing its logic."""

    if not 1 <= max_results <= 3:
        raise ValueError("max_results must be between 1 and 3")
    run_id = f"run-{uuid4()}"
    search_client = ClinicalTrialsClient()
    groq_client = GroqClient()
    try:
        _progress(progress, "SEARCH", "running", "Searching trials...")
        trials = await TrialSearchService(search_client).search(
            TrialSearchRequest(
                condition=patient.condition,
                country=patient.country,
                max_results=max_results,
            )
        )
        _progress(progress, "SEARCH", "complete", f"Found {len(trials)} trials.")
        results = [
            await _process_trial(
                patient,
                trial,
                groq_client,
                reference_date=reference_date,
                progress=progress,
            )
            for trial in trials
        ]
        return LivePrescreeningRun(
            run_id=run_id,
            patient_snapshot=patient.model_copy(deep=True),
            trials=results,
        )
    finally:
        await search_client.aclose()
        await groq_client.aclose()


async def _process_trial(
    patient: PatientProfile,
    trial: ClinicalTrial,
    groq_client: GroqClient,
    *,
    reference_date: date | None,
    progress: ProgressCallback | None,
) -> LiveTrialResult:
    _progress(progress, trial.trial_id, "EXTRACT", "running")
    extractor = CriteriaExtractionService(groq_client)
    try:
        criteria = await extractor.extract(trial)
    except CriteriaExtractionError as error:
        _progress(progress, trial.trial_id, "EXTRACT", "failed")
        return LiveTrialResult(trial=trial, extraction_error=error)

    _progress(progress, trial.trial_id, "EXTRACT", "complete")
    _progress(progress, trial.trial_id, "EVALUATE", "running")
    workflow = PrescreeningWorkflow(
        criteria_extractor=CapturedCriteriaExtractor(criteria),  # type: ignore[arg-type]
        eligibility_evaluator=EligibilityEvaluator(reference_date=reference_date),
        assessment_service=AssessmentService(),
        verification_agent=VerificationAgent(groq_client),
        coordinator_agent=CoordinatorAgent(groq_client),
    ).compile()
    state = await workflow.ainvoke(
        initial_workflow_state(patient, trial), {"recursion_limit": 20}
    )
    _progress(progress, trial.trial_id, "EVALUATE", "complete")
    _progress(progress, trial.trial_id, "VERIFY", "complete")
    assessment = state.get("trial_assessment")
    verification = state.get("verification_result")
    coordinator = state.get("coordinator_decision")
    trace = state.get("trace")
    report = (
        generate_report(
            patient=patient,
            trial=trial,
            trial_assessment=assessment,
            verification_result=verification,
            coordinator_decision=coordinator,
            criteria=criteria,
            reference_date=reference_date,
        )
        if assessment is not None
        else None
    )
    return LiveTrialResult(
        trial=trial,
        criteria=criteria,
        criterion_assessments=list(state.get("criterion_assessments", [])),
        trial_assessment=assessment,
        verification_result=verification,
        coordinator_decision=coordinator,
        missing_information=list(state.get("missing_information", [])),
        trace=trace,
        report=report,
        final_outcome=trace.final_outcome if trace is not None else "FAILED",
    )


def _progress(
    callback: ProgressCallback | None, trial_or_stage: str, status: str, detail: str
) -> None:
    if callback is not None:
        callback(trial_or_stage, status, detail)
