from pathlib import Path

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
from clinical_trial_prescreener.domain.criterion import CriterionType
from clinical_trial_prescreener.domain.information_request import InformationAnswer
from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    StudyType,
    TrialStatus,
)
from clinical_trial_prescreener.reporting.report_generator import (
    SAFETY_DISCLAIMER,
    InformationRequestAudit,
    generate_report,
    render_report,
)
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from clinical_trial_prescreener.services.information_request_service import (
    InformationRequestService,
)
from tests.golden.criteria_evaluation import load_golden_criteria
from tests.unit.test_patient_fact_resolver import REFERENCE_DATE, synthetic_patient

GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


def _trial() -> ClinicalTrial:
    return ClinicalTrial(
        trial_id="NCT07438444",
        title="NCT07438444 evidence-backed report test",
        status=TrialStatus.RECRUITING,
        study_type=StudyType.INTERVENTIONAL,
    )


def _criteria():
    return [item.expected for item in load_golden_criteria(GOLDEN_PATH).criteria]


def _assessment(criterion_type: CriterionType, *, human_review: bool = False):
    return CriterionAssessment(
        criterion_id="EXC-999" if criterion_type is CriterionType.EXCLUSION else "INC-999",
        criterion_type=criterion_type,
        status=CriterionStatus.UNKNOWN,
        reason="Structured evidence is incomplete.",
        trial_evidence="Source criterion evidence.",
        patient_evidence="Patient evidence is unavailable.",
        missing_information=["medical_history: heart_failure_hospitalization"],
        evaluation_method=(
            EvaluationMethod.HUMAN if human_review else EvaluationMethod.DETERMINISTIC
        ),
        requires_human_review=human_review,
    )


def _verification() -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.APPROVED,
        summary_reason="Structured evidence supports the assessment.",
    )


def test_possible_match_report_preserves_evidence_and_request_history() -> None:
    criteria = _criteria()
    evaluator = EligibilityEvaluator(reference_date=REFERENCE_DATE)
    initial_assessments = [
        evaluator.evaluate(criterion, synthetic_patient()) for criterion in criteria
    ]
    request = InformationRequestService().create_requests(criteria, initial_assessments)[0]
    updated_patient = InformationRequestService().apply_answer(
        synthetic_patient(),
        request,
        InformationAnswer(
            criterion_id=request.criterion_id,
            patient_field=request.patient_field,
            value=False,
            temporal_context=request.temporal_context,
        ),
    )
    reassessments = [
        evaluator.evaluate(criterion, updated_patient) for criterion in criteria
    ]
    trial_assessment = AssessmentService().aggregate(_trial().trial_id, reassessments)
    history = [
        InformationRequestAudit(
            request=request,
            initial_status=CriterionStatus.UNKNOWN,
            supplied_value=False,
            re_evaluated_status=next(
                item.status
                for item in reassessments
                if item.criterion_id == request.criterion_id
            ),
        )
    ]
    report = generate_report(
        patient=updated_patient,
        trial=_trial(),
        trial_assessment=trial_assessment,
        verification_result=_verification(),
        coordinator_decision=CoordinatorDecision(
            action=CoordinatorAction.COMPLETE,
            reason="Approved possible-match assessment is complete.",
        ),
        information_request_history=history,
        criteria=criteria,
        reference_date=REFERENCE_DATE,
    )
    rendered = render_report(report)

    assert report.trial_status == TrialAssessmentStatus.POSSIBLE_MATCH.value
    assert report.exclusion_assessments[1].criterion_id == "EXC-002"
    assert report.exclusion_assessments[1].status is CriterionStatus.NOT_MET
    assert report.exclusion_assessments[2].patient_evidence == (
        "NYHA class=II; medical_history=Congestive heart failure"
    )
    assert report.exclusion_assessments[3].unresolved_human_review_affects_result is False
    assert "patient-supplied confirmation" in rendered
    assert "hospitalization due to heart failure" in rendered
    assert "Initial status: UNKNOWN" in rendered
    assert "Supplied answer: False" in rendered
    assert "Re-evaluated status: NOT_MET" in rendered
    assert "Reference/screening date for temporal assessment: 2026-07-15" in rendered
    assert "Unresolved human-review branch:" in rendered
    assert "Effect on current result: No." in rendered
    assert SAFETY_DISCLAIMER in rendered
    _assert_prohibited_language_absent(rendered)


def test_insufficient_information_report_displays_missing_information() -> None:
    criteria = _criteria()
    assessments = [
        EligibilityEvaluator(reference_date=REFERENCE_DATE).evaluate(
            criterion, synthetic_patient()
        )
        for criterion in criteria
    ]
    report = generate_report(
        patient=synthetic_patient(),
        trial=_trial(),
        trial_assessment=AssessmentService().aggregate(_trial().trial_id, assessments),
        verification_result=_verification(),
        coordinator_decision=CoordinatorDecision(
            action=CoordinatorAction.REQUEST_INFORMATION,
            reason="Required patient information is missing.",
        ),
    )
    rendered = render_report(report)

    assert report.trial_status == TrialAssessmentStatus.INSUFFICIENT_INFORMATION.value
    assert "medical_history: heart_failure_hospitalization" in rendered
    assert "REQUEST_INFORMATION" in rendered
    assert SAFETY_DISCLAIMER in rendered
    _assert_prohibited_language_absent(rendered)


def test_human_review_required_report_identifies_requirement() -> None:
    assessment = _assessment(CriterionType.EXCLUSION, human_review=True)
    trial_assessment = AssessmentService().aggregate(_trial().trial_id, [assessment])
    report = generate_report(
        patient=synthetic_patient(),
        trial=_trial(),
        trial_assessment=trial_assessment,
        verification_result=VerificationResult(
            status=VerificationStatus.HUMAN_REVIEW,
            summary_reason="Human judgment is required.",
            requires_human_review=True,
            findings=[
                {
                    "criterion_id": assessment.criterion_id,
                    "finding": "Structured evidence requires human judgment.",
                    "requires_human_review": True,
                    "issue_type": "SEMANTIC",
                    "concrete_evidence": assessment.trial_evidence,
                    "expected_semantics": "Human judgment is required.",
                    "observed_semantics": "No deterministic resolution is available.",
                }
            ],
        ),
        coordinator_decision=CoordinatorDecision(
            action=CoordinatorAction.HUMAN_REVIEW,
            reason="Human review is required.",
            requires_human_review=True,
        ),
    )
    rendered = render_report(report)

    assert report.trial_status == TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED.value
    assert report.human_review_requirements == [
        "criterion: EXC-999",
        "verification requires human review",
        "coordinator requires human review",
    ]
    assert "Human-Review Requirements" in rendered
    assert SAFETY_DISCLAIMER in rendered
    _assert_prohibited_language_absent(rendered)


def _assert_prohibited_language_absent(rendered: str) -> None:
    lowered = rendered.casefold()
    for term in ("eligible", "ineligible", "qualified", "disqualified"):
        assert term not in lowered
