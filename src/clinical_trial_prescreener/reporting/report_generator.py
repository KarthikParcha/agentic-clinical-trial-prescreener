"""Render evidence-backed pre-screening reports from structured workflow data."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from clinical_trial_prescreener.domain.assessment import (
    CoordinatorDecision,
    CriterionAssessment,
    CriterionStatus,
    TrialAssessment,
    VerificationResult,
)
from clinical_trial_prescreener.domain.criterion import (
    CriterionType,
    EligibilityCriterion,
    LogicalOperator,
    TemporalWindow,
)
from clinical_trial_prescreener.domain.information_request import InformationRequest
from clinical_trial_prescreener.domain.patient import PatientProfile
from clinical_trial_prescreener.domain.trial import ClinicalTrial
from clinical_trial_prescreener.services.patient_fact_resolver import (
    PatientFactResolver,
)

SAFETY_DISCLAIMER = (
    "This automated assessment is for pre-screening support only.\n"
    "It does not determine final clinical trial eligibility.\n"
    "Final eligibility must be confirmed by the study team."
)


class InformationRequestAudit(BaseModel):
    """A compact audit trail for one structured information request."""

    model_config = ConfigDict(extra="forbid")

    request: InformationRequest
    initial_status: CriterionStatus
    supplied_value: bool | None = None
    re_evaluated_status: CriterionStatus | None = None


class ReportCriterionAssessment(BaseModel):
    """Safe evidence view for one inclusion or exclusion assessment."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    status: CriterionStatus
    patient_evidence: str | None = None
    trial_evidence: str
    missing_information: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    canonical_fact: str | None = None
    reference_date: date | None = None
    unresolved_human_review_children: list[str] = Field(default_factory=list)
    unresolved_human_review_affects_result: bool | None = None


class PreScreeningReport(BaseModel):
    """Structured, deterministic report suitable for text or Markdown rendering."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str
    trial_id: str
    trial_title: str | None = None
    trial_status: str
    inclusion_assessments: list[ReportCriterionAssessment] = Field(
        default_factory=list
    )
    exclusion_assessments: list[ReportCriterionAssessment] = Field(
        default_factory=list
    )
    missing_information: list[str] = Field(default_factory=list)
    information_request_history: list[InformationRequestAudit] = Field(
        default_factory=list
    )
    verification_status: str | None = None
    verification_reason: str | None = None
    coordinator_action: str | None = None
    coordinator_reason: str | None = None
    human_review_requirements: list[str] = Field(default_factory=list)
    safety_disclaimer: str = SAFETY_DISCLAIMER


def generate_report(
    *,
    patient: PatientProfile,
    trial: ClinicalTrial,
    trial_assessment: TrialAssessment,
    verification_result: VerificationResult | None = None,
    coordinator_decision: CoordinatorDecision | None = None,
    information_request_history: list[InformationRequestAudit] | None = None,
    criteria: list[EligibilityCriterion] | None = None,
    reference_date: date | None = None,
) -> PreScreeningReport:
    """Build a report without adding interpretation beyond structured workflow data."""

    criteria_by_id = {criterion.criterion_id: criterion for criterion in criteria or []}
    resolver = PatientFactResolver(reference_date=reference_date)
    inclusions, exclusions = _split_assessments(
        trial_assessment.criterion_assessments,
        criteria_by_id=criteria_by_id,
        patient=patient,
        resolver=resolver,
        reference_date=reference_date,
    )
    return PreScreeningReport(
        patient_id=patient.patient_id,
        trial_id=trial.trial_id,
        trial_title=trial.title,
        trial_status=trial_assessment.status.value,
        inclusion_assessments=inclusions,
        exclusion_assessments=exclusions,
        missing_information=list(trial_assessment.missing_information),
        information_request_history=information_request_history or [],
        verification_status=(
            verification_result.status.value if verification_result is not None else None
        ),
        verification_reason=(
            verification_result.summary_reason
            if verification_result is not None
            else None
        ),
        coordinator_action=(
            coordinator_decision.action.value if coordinator_decision is not None else None
        ),
        coordinator_reason=(
            coordinator_decision.reason if coordinator_decision is not None else None
        ),
        human_review_requirements=_human_review_requirements(
            trial_assessment, verification_result, coordinator_decision
        ),
    )


def render_report(report: PreScreeningReport) -> str:
    """Render a readable Markdown report without generating new conclusions."""

    lines = [
        "# Clinical Trial Pre-Screening Report",
        "",
        "## Summary",
        f"- Patient ID: {report.patient_id}",
        f"- Trial ID: {report.trial_id}",
        f"- Trial title: {report.trial_title or 'Not available'}",
        f"- Trial assessment: {report.trial_status}",
        "",
        "## Inclusion Criteria",
        *_render_assessments(report.inclusion_assessments),
        "",
        "## Exclusion Criteria",
        *_render_assessments(report.exclusion_assessments),
        "",
        "## Missing Information",
        *_render_list(report.missing_information, "None"),
        "",
        "## Information-Request History",
        *_render_information_history(report.information_request_history),
        "",
        "## Verification",
        f"- Status: {report.verification_status or 'Not available'}",
        f"- Reason: {report.verification_reason or 'Not available'}",
        "",
        "## Coordinator Outcome",
        f"- Action: {report.coordinator_action or 'Not available'}",
        f"- Reason: {report.coordinator_reason or 'Not available'}",
        "",
        "## Human-Review Requirements",
        *_render_list(report.human_review_requirements, "None identified"),
        "",
        "## Safety Disclaimer",
        report.safety_disclaimer,
    ]
    return "\n".join(lines) + "\n"


def _split_assessments(
    assessments: list[CriterionAssessment],
    *,
    criteria_by_id: dict[str, EligibilityCriterion],
    patient: PatientProfile,
    resolver: PatientFactResolver,
    reference_date: date | None,
) -> tuple[list[ReportCriterionAssessment], list[ReportCriterionAssessment]]:
    inclusions: list[ReportCriterionAssessment] = []
    exclusions: list[ReportCriterionAssessment] = []
    for assessment in assessments:
        criterion = criteria_by_id.get(assessment.criterion_id)
        item = ReportCriterionAssessment(
            criterion_id=assessment.criterion_id,
            status=assessment.status,
            patient_evidence=_patient_evidence(
                assessment, criterion, patient, resolver
            ),
            trial_evidence=assessment.trial_evidence,
            missing_information=list(assessment.missing_information),
            requires_human_review=assessment.requires_human_review,
            canonical_fact=criterion.field_name if criterion is not None else None,
            reference_date=(
                reference_date
                if criterion is not None and _temporal_context(criterion) is not None
                else None
            ),
            unresolved_human_review_children=(
                _unresolved_human_review_children(criterion)
                if criterion is not None
                else []
            ),
            unresolved_human_review_affects_result=(
                _human_review_affects_result(criterion, assessment.status)
                if criterion is not None
                else None
            ),
        )
        if assessment.criterion_type is CriterionType.INCLUSION:
            inclusions.append(item)
        else:
            exclusions.append(item)
    return inclusions, exclusions


def _patient_evidence(
    assessment: CriterionAssessment,
    criterion: EligibilityCriterion | None,
    patient: PatientProfile,
    resolver: PatientFactResolver,
) -> str | None:
    if criterion is None or criterion.field_name != "nyha_class":
        return assessment.patient_evidence
    fact = resolver.resolve(patient, "nyha_class")
    if not fact.is_known:
        return assessment.patient_evidence
    return f"NYHA class={fact.value}; {fact.patient_evidence}"


def _temporal_context(criterion: EligibilityCriterion) -> TemporalWindow | None:
    if criterion.temporal_window is not None:
        return criterion.temporal_window
    for child in criterion.children:
        if context := _temporal_context(child):
            return context
    return None


def _unresolved_human_review_children(criterion: EligibilityCriterion) -> list[str]:
    children: list[str] = []
    for child in criterion.children:
        if child.requires_human_review:
            children.append(child.original_text)
            continue
        children.extend(_unresolved_human_review_children(child))
    return children


def _human_review_affects_result(
    criterion: EligibilityCriterion, status: CriterionStatus
) -> bool | None:
    if not _unresolved_human_review_children(criterion):
        return None
    if (
        criterion.logical_operator is LogicalOperator.AND
        and status is CriterionStatus.NOT_MET
    ):
        return False
    return not (
        criterion.logical_operator is LogicalOperator.OR
        and status is CriterionStatus.MET
    )


def _human_review_requirements(
    trial_assessment: TrialAssessment,
    verification_result: VerificationResult | None,
    coordinator_decision: CoordinatorDecision | None,
) -> list[str]:
    requirements = [
        f"criterion: {criterion_id}"
        for criterion_id in trial_assessment.human_review_criterion_ids
    ]
    if verification_result is not None and verification_result.requires_human_review:
        requirements.append("verification requires human review")
    if coordinator_decision is not None and coordinator_decision.requires_human_review:
        requirements.append("coordinator requires human review")
    return requirements


def _render_assessments(assessments: list[ReportCriterionAssessment]) -> list[str]:
    if not assessments:
        return ["- None"]
    lines: list[str] = []
    for assessment in assessments:
        lines.extend(
            [
                f"- {assessment.criterion_id}: {assessment.status.value}",
                f"  - Criterion result: {assessment.status.value}",
                f"  - Patient evidence: {assessment.patient_evidence or 'Not available'}",
                f"  - Trial evidence: {assessment.trial_evidence}",
                (
                    "  - Missing information: "
                    + (", ".join(assessment.missing_information) or "None")
                ),
                (
                    "  - Human review required: "
                    + ("Yes" if assessment.requires_human_review else "No")
                ),
            ]
        )
        if assessment.reference_date is not None:
            lines.append(
                "  - Reference/screening date for temporal assessment: "
                f"{assessment.reference_date.isoformat()}"
            )
        if assessment.unresolved_human_review_children:
            lines.append("  - Unresolved human-review branch:")
            lines.extend(
                f"    - {child}"
                for child in assessment.unresolved_human_review_children
            )
            affects_result = assessment.unresolved_human_review_affects_result
            if affects_result is False:
                lines.append(
                    "  - Effect on current result: No. A decisive logical branch "
                    "already determines this criterion result."
                )
            elif affects_result is True:
                lines.append(
                    "  - Effect on current result: Yes. Human review remains "
                    "necessary to resolve this criterion."
                )
    return lines


def _render_information_history(history: list[InformationRequestAudit]) -> list[str]:
    if not history:
        return ["- None"]
    lines: list[str] = []
    for item in history:
        supplied = (
            "Not supplied" if item.supplied_value is None else str(item.supplied_value)
        )
        re_evaluated = (
            item.re_evaluated_status.value
            if item.re_evaluated_status is not None
            else "Not re-evaluated"
        )
        temporal = (
            f"{item.request.temporal_context.value} "
            f"{item.request.temporal_context.unit.value}"
            if item.request.temporal_context is not None
            else "None"
        )
        lines.extend(
            [
                f"- {item.request.criterion_id}",
                f"  - Initial status: {item.initial_status.value}",
                f"  - Requested field: {item.request.patient_field}",
                f"  - Question: {item.request.question}",
                f"  - Temporal context: {temporal}",
                f"  - Supplied answer: {supplied}",
                f"  - Re-evaluated status: {re_evaluated}",
                "",
            ]
        )
    return lines[:-1]


def _render_list(values: list[str], empty_value: str) -> list[str]:
    return [f"- {value}" for value in values] or [f"- {empty_value}"]
