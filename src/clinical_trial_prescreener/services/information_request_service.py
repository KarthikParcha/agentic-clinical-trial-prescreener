"""Deterministically request and apply supported missing patient facts."""

from clinical_trial_prescreener.domain.assessment import (
    CriterionAssessment,
    CriterionStatus,
)
from clinical_trial_prescreener.domain.criterion import (
    EligibilityCriterion,
    TemporalWindow,
)
from clinical_trial_prescreener.domain.information_request import (
    InformationAnswer,
    InformationRequest,
)
from clinical_trial_prescreener.domain.patient import (
    PatientFactConfirmation,
    PatientProfile,
)

_QUESTIONS = {
    "heart_failure_hospitalization": (
        "Has the patient been hospitalized for heart failure within the past 6 months?"
    )
}


class InformationRequestService:
    """Create and apply only deterministic V1 information requests."""

    def create_requests(
        self,
        criteria: list[EligibilityCriterion],
        assessments: list[CriterionAssessment],
    ) -> list[InformationRequest]:
        """Create questions for resolvable UNKNOWN criterion facts only."""

        criteria_by_id = {criterion.criterion_id: criterion for criterion in criteria}
        requests: list[InformationRequest] = []
        for assessment in assessments:
            if assessment.status is not CriterionStatus.UNKNOWN:
                continue
            criterion = criteria_by_id.get(assessment.criterion_id)
            if criterion is None:
                continue
            for field_name, temporal_context in _missing_supported_fields(
                criterion, assessment.missing_information
            ):
                question = _QUESTIONS.get(field_name)
                if question is None:
                    continue
                requests.append(
                    InformationRequest(
                        criterion_id=criterion.criterion_id,
                        patient_field=field_name,
                        question=question,
                        reason=assessment.reason,
                        temporal_context=temporal_context,
                    )
                )
        return requests

    def apply_answer(
        self,
        patient: PatientProfile,
        request: InformationRequest,
        answer: InformationAnswer,
    ) -> PatientProfile:
        """Return a copy carrying a supplied fact, without inferring absent answers."""

        if answer.criterion_id != request.criterion_id:
            raise ValueError("answer criterion_id must match the information request")
        if answer.patient_field != request.patient_field:
            raise ValueError("answer patient_field must match the information request")
        if answer.temporal_context != request.temporal_context:
            raise ValueError("answer temporal_context must match the information request")
        if request.patient_field not in _QUESTIONS:
            raise ValueError("patient_field is not supported for deterministic updates")
        if answer.value is None:
            return patient.model_copy(deep=True)

        confirmation = PatientFactConfirmation(
            fact_name=request.patient_field,
            value=answer.value,
            temporal_context=request.temporal_context,
        )
        confirmations = [
            item
            for item in patient.fact_confirmations
            if not (
                item.fact_name == confirmation.fact_name
                and item.temporal_context == confirmation.temporal_context
            )
        ]
        confirmations.append(confirmation)
        return patient.model_copy(update={"fact_confirmations": confirmations})


def _missing_supported_fields(
    criterion: EligibilityCriterion, missing_information: list[str]
) -> list[tuple[str, TemporalWindow | None]]:
    missing = set(missing_information)
    fields: list[tuple[str, TemporalWindow | None]] = []
    _collect_missing_fields(criterion, missing, criterion.temporal_window, fields)
    return fields


def _collect_missing_fields(
    criterion: EligibilityCriterion,
    missing: set[str],
    inherited_temporal_context: TemporalWindow | None,
    fields: list[tuple[str, TemporalWindow | None]],
) -> None:
    temporal_context = criterion.temporal_window or inherited_temporal_context
    if (
        criterion.field_name in _QUESTIONS
        and f"medical_history: {criterion.field_name}" in missing
    ):
        fields.append((criterion.field_name, temporal_context))
    for child in criterion.children:
        _collect_missing_fields(child, missing, temporal_context, fields)
