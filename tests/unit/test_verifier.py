import asyncio
import json
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

import pytest

from clinical_trial_prescreener.agents.verification_context import (
    VerificationContextBuilder,
)
from clinical_trial_prescreener.agents.verifier import (
    VerificationAgent,
    VerificationError,
)
from clinical_trial_prescreener.domain.assessment import (
    CriterionAssessment,
    CriterionStatus,
    EvaluationMethod,
    VerificationResult,
    VerificationStatus,
)
from clinical_trial_prescreener.domain.criterion import (
    CriterionCategory,
    CriterionType,
    EligibilityCriterion,
    EvaluationType,
)
from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    StudyType,
    TrialStatus,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from tests.golden.criteria_evaluation import load_golden_criteria
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


class StubVerificationClient:
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


def response(
    status: str, *, findings: list[dict[str, object]] | None = None, human: bool = False
) -> str:
    normalized_findings = [dict(item) for item in findings or []]
    if human:
        for item in normalized_findings:
            if item.get("requires_human_review"):
                item.setdefault("issue_type", "HUMAN_JUDGMENT")
                item.setdefault("concrete_evidence", item.get("finding", "Evidence"))
                item.setdefault("expected_semantics", "Deterministic resolution")
                item.setdefault("observed_semantics", "Human judgment required")
    return json.dumps(
        {
            "status": status,
            "findings": normalized_findings,
            "summary_reason": "Mocked independent evidence review.",
            "requires_human_review": human,
        }
    )


def nct_context() -> tuple[
    ClinicalTrial,
    list[EligibilityCriterion],
    list[CriterionAssessment],
    object,
]:
    trial = ClinicalTrial(
        trial_id="NCT07438444",
        title="NCT07438444 verification test",
        status=TrialStatus.RECRUITING,
        study_type=StudyType.INTERVENTIONAL,
        eligibility_text="Frozen NCT07438444 source evidence.",
    )
    criteria = [item.expected for item in load_golden_criteria(GOLDEN_PATH).criteria]
    assessments = [
        EligibilityEvaluator(reference_date=REFERENCE_DATE).evaluate(
            criterion, synthetic_patient()
        )
        for criterion in criteria
    ]
    return trial, criteria, assessments, AssessmentService().aggregate(
        trial.trial_id, assessments
    )


def verify(
    client: StubVerificationClient,
    trial: ClinicalTrial,
    criteria: list[EligibilityCriterion],
    assessments: list[CriterionAssessment],
    trial_assessment: object,
) -> object:
    return run(
        VerificationAgent(client).verify(
            trial=trial,
            patient=synthetic_patient(),
            criteria=criteria,
            criterion_assessments=assessments,
            trial_assessment=trial_assessment,  # type: ignore[arg-type]
        )
    )


def test_correct_nct07438444_unknown_cardiovascular_assessment_is_approved() -> None:
    trial, criteria, assessments, trial_assessment = nct_context()
    client = StubVerificationClient(response("APPROVED"))

    result = verify(client, trial, criteria, assessments, trial_assessment)

    assert result.status is VerificationStatus.APPROVED
    assert len(client.calls) == 1
    assert '"status":"UNKNOWN"' in client.calls[0]["user_prompt"]
    assert "heart_failure_hospitalization" in client.calls[0]["user_prompt"]


def test_compound_temporal_context_exposes_explicit_effective_window() -> None:
    _, criteria, assessments, _ = nct_context()
    context = VerificationContextBuilder().build(criteria, assessments)
    cardiovascular = context["criteria"][5]

    assert cardiovascular["effective_temporal_window"] == {"value": "6", "unit": "MONTH"}
    assert all(
        child["effective_temporal_window"] == {"value": "6", "unit": "MONTH"}
        and child["temporal_source"] == "explicit"
        for child in cardiovascular["children"]
    )


def test_unsafe_cardiovascular_not_met_is_returned_for_reevaluation() -> None:
    trial, criteria, assessments, _ = nct_context()
    assessments[5] = CriterionAssessment(
        criterion_id="EXC-002",
        criterion_type=CriterionType.EXCLUSION,
        status=CriterionStatus.NOT_MET,
        reason="Incorrectly assumed unknown heart failure evidence was absent.",
        trial_evidence=criteria[5].original_text,
        evaluation_method=EvaluationMethod.COMPOUND,
    )
    trial_assessment = AssessmentService().aggregate(trial.trial_id, assessments)
    client = StubVerificationClient(
        response(
            "REQUIRES_REEVALUATION",
            findings=[
                {
                    "criterion_id": "EXC-002",
                    "finding": "Heart failure hospitalization evidence is missing.",
                    "recommended_status": "UNKNOWN",
                    "missing_information": [
                        "medical_history: heart_failure_hospitalization"
                    ],
                }
            ],
        )
    )

    result = verify(client, trial, criteria, assessments, trial_assessment)

    assert result.status is VerificationStatus.REQUIRES_REEVALUATION
    assert result.findings[0].recommended_status is CriterionStatus.UNKNOWN


def test_incorrect_hba1c_not_met_is_detected() -> None:
    trial, criteria, assessments, _ = nct_context()
    assessments[2] = CriterionAssessment(
        criterion_id="INC-003",
        criterion_type=CriterionType.INCLUSION,
        status=CriterionStatus.NOT_MET,
        reason="Incorrect numeric comparison.",
        trial_evidence=criteria[2].original_text,
        patient_evidence="HbA1c=8.2 %",
        evaluation_method=EvaluationMethod.DETERMINISTIC,
    )
    trial_assessment = AssessmentService().aggregate(trial.trial_id, assessments)
    client = StubVerificationClient(
        response(
            "CORRECTED",
            findings=[
                {
                    "criterion_id": "INC-003",
                    "finding": "HbA1c 8.2 is within the inclusive 7.5 to 10 range.",
                    "previous_status": "NOT_MET",
                    "recommended_status": "MET",
                }
            ],
        )
    )

    result = verify(client, trial, criteria, assessments, trial_assessment)

    assert result.status is VerificationStatus.CORRECTED
    assert result.findings[0].recommended_status is CriterionStatus.MET


def test_corrected_without_an_explicit_status_change_is_invalid() -> None:
    with pytest.raises(ValueError, match="explicit criterion status correction"):
        VerificationResult(
            status=VerificationStatus.CORRECTED,
            findings=[
                {
                    "criterion_id": "EXC-002",
                    "finding": "Missing information was noted.",
                    "recommended_status": "UNKNOWN",
                }
            ],
            summary_reason="No actual correction was provided.",
        )


def test_missing_hf_information_alone_is_approved_not_human_review() -> None:
    trial, criteria, assessments, trial_assessment = nct_context()
    result = verify(
        StubVerificationClient(
            response(
                "HUMAN_REVIEW",
                findings=[
                    {
                        "criterion_id": "EXC-002",
                        "finding": "Missing hospitalization information requires review.",
                        "requires_human_review": True,
                    }
                ],
                human=True,
            )
        ),
        trial,
        criteria,
        assessments,
        trial_assessment,
    )

    assert result.status is VerificationStatus.APPROVED


def test_correct_assessment_after_reevaluation_is_approved() -> None:
    trial, criteria, assessments, trial_assessment = nct_context()
    result = verify(
        StubVerificationClient(response("APPROVED")),
        trial,
        criteria,
        assessments,
        trial_assessment,
    )

    assert result.status is VerificationStatus.APPROVED


def test_unsupported_procedure_fact_is_escalated_without_inventing_patient_data() -> None:
    trial, criteria, assessments, trial_assessment = nct_context()
    client = StubVerificationClient(
        response(
            "HUMAN_REVIEW",
            findings=[
                {
                    "criterion_id": "EXC-004",
                    "finding": "Procedure consideration is not represented by supplied patient data.",
                    "requires_human_review": True,
                }
            ],
            human=True,
        )
    )

    result = verify(client, trial, criteria, assessments, trial_assessment)

    assert result.status is VerificationStatus.HUMAN_REVIEW
    assert "bariatric_surgery_considered" not in client.calls[0]["user_prompt"]
    assert result.findings[0].recommended_status is None


def test_conflicting_patient_evidence_is_safely_escalated() -> None:
    trial, criteria, assessments, trial_assessment = nct_context()
    client = StubVerificationClient(
        response(
            "HUMAN_REVIEW",
            findings=[
                {
                    "criterion_id": "INC-003",
                    "finding": "Conflicting HbA1c evidence cannot be resolved safely.",
                    "requires_human_review": True,
                }
            ],
            human=True,
        )
    )

    result = verify(client, trial, criteria, assessments, trial_assessment)

    assert result.status is VerificationStatus.HUMAN_REVIEW
    assert result.requires_human_review


def test_human_only_criterion_remains_escalated() -> None:
    trial, _, _, _ = nct_context()
    criterion = EligibilityCriterion(
        criterion_id="EXC-999",
        criterion_type=CriterionType.EXCLUSION,
        category=CriterionCategory.OTHER,
        original_text="Investigator judgment is required.",
        evaluation_type=EvaluationType.HUMAN_ONLY,
        requires_human_review=True,
    )
    assessment = CriterionAssessment(
        criterion_id="EXC-999",
        criterion_type=CriterionType.EXCLUSION,
        status=CriterionStatus.UNKNOWN,
        reason="Human judgment is required.",
        trial_evidence=criterion.original_text,
        missing_information=["investigator judgment"],
        evaluation_method=EvaluationMethod.HUMAN,
        requires_human_review=True,
    )
    trial_assessment = AssessmentService().aggregate(trial.trial_id, [assessment])
    client = StubVerificationClient(
        response(
            "HUMAN_REVIEW",
            findings=[
                {
                    "criterion_id": "EXC-999",
                    "finding": "Criterion requires investigator judgment.",
                    "requires_human_review": True,
                }
            ],
            human=True,
        )
    )

    result = verify(client, trial, [criterion], [assessment], trial_assessment)

    assert result.status is VerificationStatus.HUMAN_REVIEW
    assert result.requires_human_review is True


def test_provider_and_schema_errors_remain_distinguishable() -> None:
    trial, criteria, assessments, trial_assessment = nct_context()
    provider_error = RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        verify(
            StubVerificationClient(provider_error),
            trial,
            criteria,
            assessments,
            trial_assessment,
        )
    with pytest.raises(VerificationError, match="failed after one repair attempt"):
        verify(
            StubVerificationClient("not-json"),
            trial,
            criteria,
            assessments,
            trial_assessment,
        )
