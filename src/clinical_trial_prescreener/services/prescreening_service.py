"""Thin end-to-end orchestration for one patient and one clinical trial."""

from typing import Protocol

from clinical_trial_prescreener.domain.assessment import PrescreeningResult
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.domain.patient import PatientProfile
from clinical_trial_prescreener.domain.trial import ClinicalTrial
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)


class CriteriaExtractor(Protocol):
    """The extraction capability needed by the pipeline."""

    async def extract(
        self,
        source: ClinicalTrial | str,
        *,
        target_population: str = "Type 2 Diabetes",
    ) -> list[EligibilityCriterion]:
        """Extract the ordered criteria applicable to the target population."""


class PrescreeningService:
    """Connect extraction, criterion evaluation, and trial aggregation only."""

    def __init__(
        self,
        criteria_extractor: CriteriaExtractor,
        eligibility_evaluator: EligibilityEvaluator,
        assessment_service: AssessmentService,
    ) -> None:
        self._criteria_extractor = criteria_extractor
        self._eligibility_evaluator = eligibility_evaluator
        self._assessment_service = assessment_service

    async def prescreen(
        self,
        patient: PatientProfile,
        trial: ClinicalTrial,
        *,
        target_population: str = "Type 2 Diabetes",
    ) -> PrescreeningResult:
        """Evaluate extracted criteria and aggregate without duplicating domain logic."""

        criteria = await self._criteria_extractor.extract(
            trial, target_population=target_population
        )
        criterion_assessments = [
            self._eligibility_evaluator.evaluate(criterion, patient)
            for criterion in criteria
        ]
        trial_assessment = self._assessment_service.aggregate(
            trial.trial_id, criterion_assessments
        )
        return PrescreeningResult(
            patient_id=patient.patient_id,
            trial_id=trial.trial_id,
            criteria=criteria,
            criterion_assessments=criterion_assessments,
            trial_assessment=trial_assessment,
        )
