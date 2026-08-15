"""Deterministic aggregation of criterion assessments into a trial assessment."""

from clinical_trial_prescreener.domain.assessment import (
    CriterionAssessment,
    CriterionStatus,
    EvaluationMethod,
    TrialAssessment,
    TrialAssessmentStatus,
)
from clinical_trial_prescreener.domain.criterion import CriterionType


class AssessmentService:
    """Apply the Version 1 trial-level aggregation policy without re-evaluation."""

    def aggregate(
        self, trial_id: str, criterion_assessments: list[CriterionAssessment]
    ) -> TrialAssessment:
        """Return the preliminary status, preserving decisive and unresolved evidence."""

        blockers = [
            assessment.criterion_id
            for assessment in criterion_assessments
            if _is_blocking(assessment)
        ]
        unknowns = [
            assessment.criterion_id
            for assessment in criterion_assessments
            if assessment.status is CriterionStatus.UNKNOWN
        ]
        human_review = [
            assessment.criterion_id
            for assessment in criterion_assessments
            if assessment.status is CriterionStatus.UNKNOWN
            and (
                assessment.requires_human_review
                or assessment.evaluation_method is EvaluationMethod.HUMAN
            )
        ]

        if blockers:
            status = TrialAssessmentStatus.UNLIKELY_MATCH
            summary = (
                "One or more inclusion criteria are not met or exclusion criteria "
                "are met."
            )
        elif human_review:
            status = TrialAssessmentStatus.HUMAN_REVIEW_REQUIRED
            summary = (
                "No definitive blocking criterion was found, but one or more "
                "criteria require human judgment."
            )
        elif unknowns:
            status = TrialAssessmentStatus.INSUFFICIENT_INFORMATION
            summary = (
                "No definitive blocking criterion was found, but required patient "
                "information is missing."
            )
        else:
            status = TrialAssessmentStatus.POSSIBLE_MATCH
            summary = (
                "All evaluated inclusion criteria are met and no evaluated exclusion "
                "criteria are met."
            )

        return TrialAssessment(
            trial_id=trial_id,
            status=status,
            criterion_assessments=criterion_assessments,
            blocking_criterion_ids=blockers,
            unknown_criterion_ids=unknowns,
            human_review_criterion_ids=human_review,
            missing_information=_deduplicate_missing(criterion_assessments),
            summary_reason=summary,
            requires_human_review=bool(human_review),
        )


def _is_blocking(assessment: CriterionAssessment) -> bool:
    return (
        assessment.criterion_type is CriterionType.INCLUSION
        and assessment.status is CriterionStatus.NOT_MET
    ) or (
        assessment.criterion_type is CriterionType.EXCLUSION
        and assessment.status is CriterionStatus.MET
    )


def _deduplicate_missing(
    criterion_assessments: list[CriterionAssessment],
) -> list[str]:
    """Retain first-seen missing-information order for predictable output."""

    return list(
        dict.fromkeys(
            item
            for assessment in criterion_assessments
            for item in assessment.missing_information
        )
    )
