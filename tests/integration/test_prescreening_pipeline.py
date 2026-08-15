"""Offline end-to-end pipeline test using the frozen NCT07438444 criteria."""

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

import pytest

from clinical_trial_prescreener.domain.assessment import (
    CriterionStatus,
    TrialAssessmentStatus,
)
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    StudyType,
    TrialStatus,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from clinical_trial_prescreener.services.prescreening_service import PrescreeningService
from tests.golden.criteria_evaluation import load_golden_criteria
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


class FrozenCriteriaExtractor:
    """Stable extraction boundary for deterministic pipeline integration coverage."""

    def __init__(self, criteria: list[EligibilityCriterion]) -> None:
        self._criteria = criteria
        self.source: ClinicalTrial | str | None = None

    async def extract(
        self,
        source: ClinicalTrial | str,
        *,
        target_population: str = "Type 2 Diabetes",
    ) -> list[EligibilityCriterion]:
        self.source = source
        assert target_population == "Type 2 Diabetes"
        return [criterion.model_copy(deep=True) for criterion in self._criteria]


def run(coroutine: Awaitable[Any]) -> Any:
    return asyncio.run(coroutine)


@pytest.mark.integration
def test_frozen_nct07438444_prescreening_pipeline() -> None:
    trial = ClinicalTrial(
        trial_id="NCT07438444",
        title="Frozen NCT07438444 pipeline test",
        status=TrialStatus.RECRUITING,
        study_type=StudyType.INTERVENTIONAL,
    )
    frozen_criteria = [
        item.expected for item in load_golden_criteria(GOLDEN_PATH).criteria
    ]
    extractor = FrozenCriteriaExtractor(frozen_criteria)
    pipeline = PrescreeningService(
        extractor,
        EligibilityEvaluator(reference_date=REFERENCE_DATE),
        AssessmentService(),
    )

    result = run(pipeline.prescreen(synthetic_patient(), trial))

    assert extractor.source is trial
    assert result.patient_id == "DEMO-P001"
    assert result.trial_id == "NCT07438444"
    assert [item.status for item in result.criterion_assessments] == [
        CriterionStatus.MET,
        CriterionStatus.MET,
        CriterionStatus.MET,
        CriterionStatus.MET,
        CriterionStatus.NOT_MET,
        CriterionStatus.UNKNOWN,
        CriterionStatus.NOT_MET,
        CriterionStatus.NOT_MET,
    ]
    assert result.trial_assessment.status is TrialAssessmentStatus.INSUFFICIENT_INFORMATION
    assert result.trial_assessment.blocking_criterion_ids == []
    assert result.trial_assessment.unknown_criterion_ids == ["EXC-002"]
    assert result.trial_assessment.missing_information == [
        "medical_history: heart_failure_hospitalization"
    ]
