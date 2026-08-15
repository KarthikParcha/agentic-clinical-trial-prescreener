"""Streamlit dashboard for safe workflow-trace inspection."""

import asyncio
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parents[2]))

import streamlit as st
from pydantic import BaseModel, ConfigDict, Field

from clinical_trial_prescreener.domain.patient import PatientProfile, Sex
from clinical_trial_prescreener.observability.trace_models import (
    TraceStep,
    WorkflowTrace,
)
from clinical_trial_prescreener.reporting.report_generator import render_report
from clinical_trial_prescreener.services.live_prescreening_runner import (
    LivePrescreeningRun,
    run_live_prescreening,
)

TIMELINE_STAGES = ("EXTRACT", "EVALUATE", "AGGREGATE", "VERIFY", "COORDINATE")
SAFE_STEP_OUTPUTS: dict[str, set[str]] = {
    "EXTRACT": {
        "criteria_count",
        "validation",
        "attempt_count",
        "provider_attempts",
        "extraction_repair_attempts",
        "repair_attempted",
        "provider_error_code",
        "canonicalization_applied",
        "canonicalizations",
        "failure_category",
        "validation_stage",
    },
    "EVALUATE": {"MET", "NOT_MET", "UNKNOWN", "NOT_APPLICABLE"},
    "AGGREGATE": {
        "trial_status",
        "blocking",
        "unknown",
        "missing_information",
    },
    "VERIFY": {"verification_status"},
    "COORDINATE": {"retry_count", "reevaluation_count"},
}
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|credential|token)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
_SECRET_VALUE = re.compile(r"(?i)\b(?:gsk_|sk-)[A-Za-z0-9_-]+")


class CriteriaSource(str, Enum):
    LIVE_LLM = "LIVE_LLM"
    VALIDATED_FIXTURE = "VALIDATED_FIXTURE"


class CriterionDebugRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    criterion_type: str
    canonical_fact: str | None = None
    patient_evidence: str | None = None
    criterion_status: str
    missing_information: list[str] = Field(default_factory=list)
    requires_human_review: bool = False


class VerificationDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    reason: str
    issues_or_corrections: list[str] = Field(default_factory=list)


class CoordinatorDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    reason: str
    retry_count: int = 0
    reevaluation_count: int = 0


class CanonicalizationDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_path: str
    raw_evaluation_type: str
    removed_fields: list[str] = Field(default_factory=list)


class ExtractionDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria_source: CriteriaSource
    model: str | None = None
    criteria_count: int = 0
    attempt_count: int = 0
    provider_attempts: int = 0
    extraction_repair_attempts: int = 0
    repair_attempted: bool = False
    provider_error_code: str | None = None
    canonicalization_applied: bool = False
    canonicalizations: list[CanonicalizationDebug] = Field(default_factory=list)
    validation_result: str = "NOT_AVAILABLE"
    failure_category: str | None = None
    validation_stage: str | None = None


class DashboardError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str
    error_type: str
    failure_category: str | None = None
    validation_stage: str | None = None
    graph_status: str = "STOPPED"


class DashboardRun(BaseModel):
    """Safe dashboard snapshot around an existing compact workflow trace."""

    model_config = ConfigDict(extra="forbid")

    trace: WorkflowTrace
    criteria_source: CriteriaSource
    trial_assessment: str | None = None
    criteria_debug: list[CriterionDebugRow] = Field(default_factory=list)
    verification: VerificationDebug | None = None
    coordinator: CoordinatorDebug | None = None
    extraction: ExtractionDebug
    error: DashboardError | None = None


def successful_dashboard_run() -> DashboardRun:
    """Return the deterministic DEMO-P001 successful debug fixture."""

    started = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
    trace = WorkflowTrace(
        run_id="fixture-success-001",
        patient_id="DEMO-P001",
        trial_id="NCT07438444",
        started_at=started,
        completed_at=started + timedelta(milliseconds=436),
        final_outcome="REQUEST_INFORMATION",
        steps=[
            TraceStep(
                step_name="extract",
                status="SUCCESS",
                duration_ms=82,
                output_summary={"criteria_count": 8, "validation": "passed"},
            ),
            TraceStep(
                step_name="evaluate",
                status="SUCCESS",
                duration_ms=14,
                output_summary={"MET": 4, "NOT_MET": 3, "UNKNOWN": 1},
            ),
            TraceStep(
                step_name="aggregate",
                status="SUCCESS",
                duration_ms=2,
                output_summary={
                    "trial_status": "INSUFFICIENT_INFORMATION",
                    "blocking": [],
                    "unknown": ["EXC-002"],
                    "missing_information": [
                        "medical_history: heart_failure_hospitalization"
                    ],
                },
            ),
            TraceStep(
                step_name="verify",
                status="SUCCESS",
                duration_ms=310,
                output_summary={"verification_status": "APPROVED"},
                decision="Available evidence and UNKNOWN handling are consistent.",
            ),
            TraceStep(
                step_name="coordinate",
                status="SUCCESS",
                duration_ms=28,
                output_summary={"retry_count": 0, "reevaluation_count": 0},
                decision="REQUEST_INFORMATION",
            ),
        ],
    )
    return DashboardRun(
        trace=trace,
        criteria_source=CriteriaSource.VALIDATED_FIXTURE,
        trial_assessment="INSUFFICIENT_INFORMATION",
        criteria_debug=_demo_criteria_rows(),
        verification=VerificationDebug(
            decision="APPROVED",
            reason="Available evidence and UNKNOWN handling are consistent.",
        ),
        coordinator=CoordinatorDebug(
            action="REQUEST_INFORMATION",
            reason="Heart-failure hospitalization history is required.",
        ),
        extraction=ExtractionDebug(
            criteria_source=CriteriaSource.VALIDATED_FIXTURE,
            model=None,
            criteria_count=8,
            attempt_count=0,
            repair_attempted=False,
            canonicalization_applied=True,
            canonicalizations=[
                CanonicalizationDebug(
                    criterion_path="criteria.7.children.0",
                    raw_evaluation_type="HUMAN_ONLY",
                    removed_fields=["operator", "value"],
                )
            ],
            validation_result="PASSED",
        ),
    )


def failed_extraction_dashboard_run() -> DashboardRun:
    """Return a valid incomplete run where extraction failed before graph start."""

    started = datetime(2026, 8, 15, 9, 5, tzinfo=UTC)
    trace = WorkflowTrace(
        run_id="fixture-extraction-failure-001",
        patient_id="DEMO-P001",
        trial_id="NCT07438444",
        started_at=started,
        completed_at=started + timedelta(milliseconds=4170),
        final_outcome="ERROR",
        steps=[
            TraceStep(
                step_name="extract",
                status="FAILED",
                duration_ms=4170,
                output_summary={
                    "criteria_count": 0,
                    "attempt_count": 2,
                    "repair_attempted": True,
                    "canonicalization_applied": True,
                    "validation": "failed",
                    "failure_category": "REPAIR_EXHAUSTED",
                    "validation_stage": "SOURCE_TRACEABILITY",
                },
                error="CriteriaExtractionError",
            )
        ],
    )
    return DashboardRun(
        trace=trace,
        criteria_source=CriteriaSource.LIVE_LLM,
        extraction=ExtractionDebug(
            criteria_source=CriteriaSource.LIVE_LLM,
            model="llama-3.3-70b-versatile",
            criteria_count=0,
            attempt_count=2,
            repair_attempted=True,
            canonicalization_applied=True,
            validation_result="FAILED",
            failure_category="REPAIR_EXHAUSTED",
            validation_stage="SOURCE_TRACEABILITY",
        ),
        error=DashboardError(
            node="EXTRACT",
            error_type="CriteriaExtractionError",
            failure_category="REPAIR_EXHAUSTED",
            validation_stage="SOURCE_TRACEABILITY",
            graph_status="NOT_STARTED",
        ),
    )


def load_dashboard_payload(
    text: str, *, criteria_source: CriteriaSource = CriteriaSource.LIVE_LLM
) -> DashboardRun:
    """Load either a dashboard snapshot or a raw serialized WorkflowTrace."""

    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError("dashboard input must be a JSON object")
    if "trace" in payload:
        allowed = {name: payload[name] for name in DashboardRun.model_fields if name in payload}
        return DashboardRun.model_validate(allowed)

    trace_fields = {
        name: payload[name] for name in WorkflowTrace.model_fields if name in payload
    }
    trace = WorkflowTrace.model_validate(trace_fields)
    extraction = _extraction_from_trace(trace, criteria_source)
    return DashboardRun(
        trace=trace,
        criteria_source=criteria_source,
        extraction=extraction,
        error=_error_from_trace(trace, extraction),
    )


def build_dashboard_view(run: DashboardRun) -> dict[str, object]:
    """Build the sanitized values rendered by Streamlit."""

    summary = {
        "run_id": _safe_text(run.trace.run_id),
        "patient_id": _safe_text(run.trace.patient_id),
        "trial_id": _safe_text(run.trace.trial_id),
        "criteria_source": run.criteria_source.value,
        "final_workflow_outcome": _safe_optional_text(run.trace.final_outcome)
        or "INCOMPLETE",
        "trial_assessment": _safe_optional_text(run.trial_assessment)
        or "NOT_AVAILABLE",
        "verification_decision": (
            _safe_text(run.verification.decision)
            if run.verification
            else "NOT_STARTED"
        ),
        "coordinator_action": (
            _safe_text(run.coordinator.action) if run.coordinator else "NOT_STARTED"
        ),
        "total_duration_ms": _total_duration_ms(run.trace),
        "error_status": "ERROR" if _has_error(run) else "NONE",
    }
    criteria = [
        {
            "criterion_id": _safe_text(item.criterion_id),
            "criterion_type": _safe_text(item.criterion_type),
            "canonical_fact": _safe_optional_text(item.canonical_fact),
            "patient_evidence": _safe_optional_text(item.patient_evidence),
            "criterion_status": _safe_text(item.criterion_status),
            "missing_information": ", ".join(
                _safe_text(value) for value in item.missing_information
            ),
            "requires_human_review": item.requires_human_review,
        }
        for item in run.criteria_debug
    ]
    return {
        "summary": summary,
        "timeline": _timeline_rows(run),
        "criteria": criteria,
        "criteria_counts": criteria_counts(run),
        "verification_agent": _verification_view(run.verification),
        "coordinator_agent": _coordinator_view(run.coordinator),
        "extraction": _extraction_view(run.extraction),
        "error": _error_view(run.error),
    }


def criteria_counts(run: DashboardRun) -> dict[str, int]:
    """Count the finite criterion statuses shown in the debug table."""

    statuses = ("MET", "NOT_MET", "UNKNOWN", "NOT_APPLICABLE")
    return {
        status: sum(item.criterion_status == status for item in run.criteria_debug)
        for status in statuses
    }


def render_dashboard(run: DashboardRun) -> None:
    """Render one sanitized dashboard run."""

    view = build_dashboard_view(run)
    st.title("Clinical Trial Pre-Screening — AI Debug Dashboard")
    st.caption("Local observability view. No model or external API is called by this page.")

    st.header("1. Run Summary")
    st.dataframe([view["summary"]], width="stretch", hide_index=True)

    st.header("2. Workflow Timeline")
    st.dataframe(view["timeline"], width="stretch", hide_index=True)

    st.header("3. Criteria Debug")
    counts = view["criteria_counts"]
    columns = st.columns(4)
    for column, status in zip(
        columns, ("MET", "NOT_MET", "UNKNOWN", "NOT_APPLICABLE"), strict=True
    ):
        column.metric(status, counts[status])
    st.dataframe(view["criteria"], width="stretch", hide_index=True)

    st.header("4. Agent Decisions")
    verifier_column, coordinator_column = st.columns(2)
    with verifier_column:
        st.subheader("Verification Agent")
        st.json(view["verification_agent"])
    with coordinator_column:
        st.subheader("Coordinator Agent")
        st.json(view["coordinator_agent"])

    st.header("5. Extraction Debug")
    st.json(view["extraction"])

    st.header("6. Error View")
    if view["error"] is None:
        st.success("No workflow error recorded.")
    else:
        st.error("This run is incomplete but remains inspectable.")
        st.json(view["error"])


def main() -> None:
    """Render the approved run-scoped researcher and developer views."""

    st.set_page_config(page_title="Clinical Trial Pre-Screening", layout="wide")
    render_approved_ui()


def _demo_criteria_rows() -> list[CriterionDebugRow]:
    rows = (
        ("INC-001", "INCLUSION", "diagnosis_duration_years", "diagnosis_date=2022-06-15", "MET", []),
        ("INC-002", "INCLUSION", "insulin_naive", "no insulin medication found", "MET", []),
        ("INC-003", "INCLUSION", "hba1c", "HbA1c=8.2 %", "MET", []),
        ("INC-004", "INCLUSION", "bmi", "bmi=29.1", "MET", []),
        ("EXC-001", "EXCLUSION", "type_1_diabetes", "medical history does not contain Type 1 Diabetes", "NOT_MET", []),
        ("EXC-002", "EXCLUSION", "recent_cardiovascular_event", "heart attack=False; stroke=False; heart failure hospitalization=missing", "UNKNOWN", ["medical_history: heart_failure_hospitalization"]),
        ("EXC-003", "EXCLUSION", "nyha_class", "NYHA Class II", "NOT_MET", []),
        ("EXC-004", "EXCLUSION", "morbid_obesity_weight_loss_procedure", "morbid obesity is resolved", "NOT_MET", []),
    )
    return [
        CriterionDebugRow(
            criterion_id=criterion_id,
            criterion_type=criterion_type,
            canonical_fact=canonical_fact,
            patient_evidence=evidence,
            criterion_status=status,
            missing_information=missing,
        )
        for criterion_id, criterion_type, canonical_fact, evidence, status, missing in rows
    ]


def _timeline_rows(run: DashboardRun) -> list[dict[str, object]]:
    steps = {step.step_name.upper(): step for step in run.trace.steps}
    rows: list[dict[str, object]] = []
    for stage in TIMELINE_STAGES:
        step = steps.get(stage)
        if step is None:
            rows.append(
                {
                    "stage": stage,
                    "status": "NOT_STARTED",
                    "duration_ms": None,
                    "important_output": "",
                    "error": "",
                }
            )
            continue
        safe_output = {
            key: _safe_object(value)
            for key, value in step.output_summary.items()
            if key in SAFE_STEP_OUTPUTS[stage]
        }
        rows.append(
            {
                "stage": stage,
                "status": _safe_text(step.status),
                "duration_ms": step.duration_ms,
                "important_output": json.dumps(safe_output, ensure_ascii=False),
                "error": _safe_optional_text(step.error) or "",
            }
        )
    rows.append(
        {
            "stage": "END",
            "status": (
                "NOT_REACHED"
                if run.error is not None
                else "COMPLETED"
                if run.trace.completed_at is not None
                else "INCOMPLETE"
            ),
            "duration_ms": 0 if run.trace.completed_at is not None else None,
            "important_output": _safe_text(run.trace.final_outcome or ""),
            "error": "",
        }
    )
    return rows


def _total_duration_ms(trace: WorkflowTrace) -> int:
    if trace.completed_at is not None:
        return max(0, round((trace.completed_at - trace.started_at).total_seconds() * 1000))
    return sum(step.duration_ms for step in trace.steps)


def _has_error(run: DashboardRun) -> bool:
    return run.error is not None or any(
        step.status.upper() in {"ERROR", "FAILED"} for step in run.trace.steps
    )


def _verification_view(value: VerificationDebug | None) -> dict[str, object]:
    if value is None:
        return {"decision": "NOT_STARTED", "reason": "Not available", "issues_or_corrections": []}
    return {
        "decision": _safe_text(value.decision),
        "reason": _safe_text(value.reason),
        "issues_or_corrections": [_safe_text(item) for item in value.issues_or_corrections],
    }


def _coordinator_view(value: CoordinatorDebug | None) -> dict[str, object]:
    if value is None:
        return {
            "action": "NOT_STARTED",
            "reason": "Not available",
            "retry_count": 0,
            "reevaluation_count": 0,
        }
    return {
        "action": _safe_text(value.action),
        "reason": _safe_text(value.reason),
        "retry_count": value.retry_count,
        "reevaluation_count": value.reevaluation_count,
    }


def _extraction_view(value: ExtractionDebug) -> dict[str, object]:
    return {
        "criteria_source": value.criteria_source.value,
        "model": _safe_optional_text(value.model) or "NOT_APPLICABLE",
        "criteria_count": value.criteria_count,
        "attempt_count": value.attempt_count,
        "provider_attempts": value.provider_attempts,
        "extraction_repair_attempts": value.extraction_repair_attempts,
        "repair_attempted": value.repair_attempted,
        "provider_error_code": _safe_optional_text(value.provider_error_code),
        "canonicalization_applied": value.canonicalization_applied,
        "canonicalizations": [
            {
                "criterion_path": _safe_text(item.criterion_path),
                "raw_evaluation_type": _safe_text(item.raw_evaluation_type),
                "removed_fields": [
                    _safe_text(field_name) for field_name in item.removed_fields
                ],
            }
            for item in value.canonicalizations
        ],
        "validation_result": _safe_text(value.validation_result),
        "failure_category": _safe_optional_text(value.failure_category),
        "validation_stage": _safe_optional_text(value.validation_stage),
    }


def _error_view(value: DashboardError | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "node": _safe_text(value.node),
        "failure": _safe_optional_text(value.failure_category) or _safe_text(value.error_type),
        "stage": _safe_optional_text(value.validation_stage) or "NOT_AVAILABLE",
        "graph": _safe_text(value.graph_status),
    }


def _extraction_from_trace(
    trace: WorkflowTrace, criteria_source: CriteriaSource
) -> ExtractionDebug:
    step = next(
        (item for item in trace.steps if item.step_name.casefold() == "extract"), None
    )
    output = step.output_summary if step else {}
    return ExtractionDebug(
        criteria_source=criteria_source,
        criteria_count=_safe_int(output.get("criteria_count")),
        attempt_count=_safe_int(output.get("attempt_count")),
        provider_attempts=_safe_int(output.get("provider_attempts")),
        extraction_repair_attempts=_safe_int(
            output.get("extraction_repair_attempts")
        ),
        repair_attempted=output.get("repair_attempted") is True,
        provider_error_code=_optional_scalar_string(output.get("provider_error_code")),
        canonicalization_applied=output.get("canonicalization_applied") is True,
        canonicalizations=_canonicalizations_from_trace(
            output.get("canonicalizations")
        ),
        validation_result=str(output.get("validation", "NOT_AVAILABLE")).upper(),
        failure_category=_optional_scalar_string(output.get("failure_category")),
        validation_stage=_optional_scalar_string(output.get("validation_stage")),
    )


def _error_from_trace(
    trace: WorkflowTrace, extraction: ExtractionDebug
) -> DashboardError | None:
    step = next(
        (
            item
            for item in trace.steps
            if item.status.upper() in {"ERROR", "FAILED"}
        ),
        None,
    )
    if step is None:
        return None
    return DashboardError(
        node=step.step_name.upper(),
        error_type=step.error or "WorkflowError",
        failure_category=extraction.failure_category,
        validation_stage=extraction.validation_stage,
        graph_status="NOT_STARTED" if step.step_name.casefold() == "extract" else "STOPPED",
    )


def _canonicalizations_from_trace(value: object) -> list[CanonicalizationDebug]:
    if not isinstance(value, list):
        return []
    canonicalizations: list[CanonicalizationDebug] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            canonicalizations.append(CanonicalizationDebug.model_validate(item))
        except ValueError:
            continue
    return canonicalizations


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_scalar_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _safe_optional_text(value: str | None) -> str | None:
    return _safe_text(value) if value is not None else None


def _safe_text(value: str) -> str:
    redacted = _SECRET_ASSIGNMENT.sub(r"\1=[REDACTED]", value)
    return _SECRET_VALUE.sub("[REDACTED]", redacted)


def _safe_object(value: object) -> object:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_safe_object(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _safe_object(item)
            for key, item in value.items()
            if not any(
                marker in str(key).casefold()
                for marker in ("secret", "password", "credential", "api_key", "token", "prompt", "reasoning")
            )
        }
    return value


# The types below are display snapshots. They deliberately duplicate no clinical
# rules: every value is an immutable, safe projection of an existing run artifact.
class PatientSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    condition: str | None = None
    country: str | None = None


class CriterionDetail(CriterionDebugRow):
    model_config = ConfigDict(extra="forbid")

    short_requirement: str = ""
    original_text: str = ""
    evaluation_type: str | None = None
    operator: str | None = None
    threshold_value: str | None = None
    temporal_window: str | None = None
    reason: str | None = None
    required_patient_fields: list[str] = Field(default_factory=list)
    human_review_detail: str | None = None


class TrialResultSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trial_id: str
    title: str
    extraction_status: Literal["PASS", "FAIL"]
    criteria: list[CriterionDetail] = Field(default_factory=list)
    trial_assessment: str | None = None
    verification: VerificationDebug | None = None
    coordinator: CoordinatorDebug | None = None
    missing_information: list[str] = Field(default_factory=list)
    trace: WorkflowTrace | None = None
    report_markdown: str | None = None
    final_outcome: str | None = None
    extraction: ExtractionDebug
    error: DashboardError | None = None


class SearchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trials_found: int
    successfully_assessed: int
    need_more_information: int
    human_review: int
    could_not_safely_assess: int


class RunSnapshot(BaseModel):
    """Immutable UI input containing only data from one execution."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    patient_snapshot: PatientSnapshot
    search_summary: SearchSummary
    trial_results: list[TrialResultSnapshot] = Field(default_factory=list)
    run_status: str = "COMPLETED"


_REPORT_DIRECTORY = (
    Path(__file__).parents[3] / "tests" / "integration" / "output" / "live_multi_trial"
)


def available_run_snapshots() -> list[RunSnapshot]:
    """Return locally available immutable snapshots; never calls providers."""

    runs = [
        _legacy_run_snapshot(successful_dashboard_run()),
        _legacy_run_snapshot(failed_extraction_dashboard_run()),
    ]
    if artifact_run := load_multi_trial_report_artifact(_REPORT_DIRECTORY):
        runs.insert(0, artifact_run)
    return runs


def select_trial_result(run: RunSnapshot, trial_id: str) -> TrialResultSnapshot:
    """Select only from the currently selected run to prevent cross-run mixing."""

    for result in run.trial_results:
        if result.trial_id == trial_id:
            return result
    raise ValueError("trial_id is not part of the selected run")


def researcher_status(result: TrialResultSnapshot) -> str:
    """Map established workflow statuses to researcher-facing labels."""

    if result.extraction_status == "FAIL":
        return "COULD NOT SAFELY ASSESS"
    labels = {
        "POSSIBLE_MATCH": "POSSIBLE MATCH",
        "UNLIKELY_MATCH": "UNLIKELY MATCH",
        "INSUFFICIENT_INFORMATION": "NEEDS MORE INFORMATION",
        "HUMAN_REVIEW_REQUIRED": "HUMAN REVIEW",
    }
    return labels.get(result.trial_assessment or "", "ASSESSMENT INCOMPLETE")


def criteria_table_rows(result: TrialResultSnapshot) -> list[dict[str, object]]:
    """Return every criterion as a safe table row for the researcher view."""

    return [
        {
            "criterion_id": _safe_text(item.criterion_id),
            "type": _safe_text(item.criterion_type),
            "requirement": _safe_text(item.short_requirement),
            "canonical_fact": _safe_optional_text(item.canonical_fact) or "Not mapped",
            "patient_evidence": _safe_optional_text(item.patient_evidence)
            or "Not available",
            "status": _safe_text(item.criterion_status),
            "missing_information": ", ".join(
                _safe_text(value) for value in item.missing_information
            )
            or "None",
            "human_review": "Yes" if item.requires_human_review else "No",
        }
        for item in result.criteria
    ]


def load_multi_trial_report_artifact(directory: Path) -> RunSnapshot | None:
    """Load the saved multi-trial reports as one immutable, report-backed run."""

    report_paths = sorted(directory.glob("*.md")) if directory.exists() else []
    results = [_trial_result_from_report(path) for path in report_paths]
    if not results:
        return None
    patient_id = _report_value(report_paths[0].read_text(encoding="utf-8"), "Patient ID")
    patient = PatientSnapshot(
        patient_id=patient_id or "NOT_AVAILABLE",
        condition="Type 2 Diabetes",
        country="India",
    )
    return RunSnapshot(
        run_id="live-multi-trial-report-artifacts",
        patient_snapshot=patient,
        search_summary=_search_summary(results),
        trial_results=results,
        run_status="COMPLETED_FROM_SAVED_ARTIFACTS",
    )


def render_approved_ui() -> None:
    """Render the only two top-level tabs using one selected immutable run."""

    _initialize_dashboard_state()
    _render_run_controls()
    runs = list(st.session_state["executed_runs"])
    if not runs:
        st.info("Run Pre-Screening to view fresh results in this dashboard session.")
        return
    run_ids = [run.run_id for run in runs]
    if st.session_state.get("selected_run_id") not in run_ids:
        st.session_state["selected_run_id"] = run_ids[0]
    selected_run_id = st.selectbox("Run", run_ids, key="selected_run_id")
    run = next(item for item in runs if item.run_id == selected_run_id)
    if not run.trial_results:
        st.warning("This run contains no trial results.")
        return
    trial_ids = [item.trial_id for item in run.trial_results]
    selected_trial_id = st.session_state.get(f"selected_trial_{run.run_id}", trial_ids[0])
    if selected_trial_id not in trial_ids:
        selected_trial_id = trial_ids[0]
    researcher_tab, developer_tab = st.tabs(["Researcher View", "Developer Debug"])
    with researcher_tab:
        selected_trial_id = _render_researcher_view(run, selected_trial_id)
    with developer_tab:
        _render_developer_debug(run, select_trial_result(run, selected_trial_id))


def _initialize_dashboard_state() -> None:
    st.session_state.setdefault("patient_profiles", _synthetic_patient_profiles())
    st.session_state.setdefault("executed_runs", [])


def _render_run_controls() -> None:
    profiles: dict[str, PatientProfile] = st.session_state["patient_profiles"]
    st.subheader("Run pre-screening")
    control_col, action_col = st.columns((3, 1), vertical_alignment="bottom")
    with control_col:
        patient_id = st.selectbox("Patient profile", list(profiles), key="run_patient_id")
        patient = profiles[patient_id]
        summary_cols = st.columns(3)
        summary_cols[0].write(f"**Condition:** {patient.condition}")
        summary_cols[1].write(f"**Country:** {patient.country}")
        max_trials = summary_cols[2].number_input(
            "Max trials", min_value=1, max_value=3, value=3, step=1, key="max_trials"
        )
    with action_col:
        run_clicked = st.button(
            "Run Pre-Screening", type="primary", icon=":material/play_arrow:"
        )
    with st.expander("Edit or create synthetic patient"):
        _render_patient_form(profiles, patient)
    if run_clicked:
        _run_selected_patient(patient, int(max_trials))


def _render_patient_form(
    profiles: dict[str, PatientProfile], selected: PatientProfile
) -> None:
    """Accept only structured V1 patient fields; blank optional values stay missing."""

    with st.form("synthetic_patient_form"):
        first, second, third = st.columns(3)
        patient_id = first.text_input("Patient ID", value=selected.patient_id)
        age = second.number_input("Age", min_value=1, value=selected.age, step=1)
        sex = third.selectbox("Sex", [item.value for item in Sex], index=[item.value for item in Sex].index(selected.sex.value))
        country = first.text_input("Country", value=selected.country)
        condition = second.selectbox("Condition", ["Type 2 Diabetes"], disabled=True)
        consent = third.checkbox("Consent for demo", value=selected.consent_for_demo)
        include_duration = st.checkbox("Provide diagnosis duration", value=selected.diagnosis_duration_years is not None)
        duration = st.text_input(
            "Diagnosis duration (years)",
            value=str(selected.diagnosis_duration_years or ""),
            disabled=not include_duration,
        )
        include_bmi = st.checkbox("Provide BMI", value=selected.bmi is not None)
        bmi = st.text_input("BMI", value=str(selected.bmi or ""), disabled=not include_bmi)
        include_hba1c = st.checkbox("Provide HbA1c", value=False)
        hba1c = st.text_input("HbA1c (%)", disabled=not include_hba1c)
        submitted = st.form_submit_button("Save synthetic patient", icon=":material/save:")
    if not submitted:
        return
    try:
        payload: dict[str, object] = {
            "patient_id": patient_id,
            "age": int(age),
            "sex": sex,
            "country": country,
            "condition": condition,
            "consent_for_demo": consent,
            "diagnosis_duration_years": _optional_decimal(duration) if include_duration else None,
            "bmi": _optional_decimal(bmi) if include_bmi else None,
            "laboratory_results": (
                [{"test_name": "HbA1c", "value": _optional_decimal(hba1c), "unit": "%"}]
                if include_hba1c and _optional_decimal(hba1c) is not None
                else []
            ),
        }
        profile = PatientProfile.model_validate(payload)
    except (ValueError, InvalidOperation) as error:
        st.error(f"Synthetic patient was not saved: {error}")
        return
    profiles[profile.patient_id] = profile
    st.success("Synthetic patient saved. Missing optional fields remain unknown.")


def _run_selected_patient(patient: PatientProfile, max_trials: int) -> None:
    """Call live services only after the explicit researcher action."""

    progress_area = st.status("Preparing live pre-screening run...", expanded=True)

    def progress(scope: str, stage: str, status: str) -> None:
        if scope == "SEARCH":
            progress_area.write(status)
        else:
            progress_area.write(f"{scope}: {stage} {status}")

    try:
        live_run = asyncio.run(
            run_live_prescreening(patient, max_results=max_trials, progress=progress)
        )
    except Exception as error:  # noqa: BLE001 - provider failures remain visible to the user
        progress_area.update(label="Live pre-screening could not start", state="error")
        st.error(f"Live workflow failed before a run was completed: {type(error).__name__}")
        return
    snapshot = run_snapshot_from_live_run(live_run)
    st.session_state["executed_runs"] = [snapshot, *st.session_state["executed_runs"]]
    st.session_state["selected_run_id"] = snapshot.run_id
    progress_area.update(label=f"Completed {len(snapshot.trial_results)} trial runs", state="complete")
    st.rerun()


def _render_researcher_view(run: RunSnapshot, selected_trial_id: str) -> str:
    st.title("Clinical Trial Pre-Screening")
    st.caption("Evidence-backed pre-screening support. Final trial eligibility is confirmed by the study team.")
    st.subheader("Run summary")
    patient_col, condition_col, country_col, status_col = st.columns(4)
    patient_col.metric("Patient ID", _safe_text(run.patient_snapshot.patient_id), border=True)
    condition_col.metric("Condition", _safe_optional_text(run.patient_snapshot.condition) or "Not available", border=True)
    country_col.metric("Country", _safe_optional_text(run.patient_snapshot.country) or "Not available", border=True)
    status_col.metric("Run status", _safe_text(run.run_status), border=True)
    with st.container(horizontal=True):
        st.metric("Trials found", run.search_summary.trials_found, border=True)
        st.metric("Successfully assessed", run.search_summary.successfully_assessed, border=True)
        st.metric("Need more information", run.search_summary.need_more_information, border=True)
        st.metric("Human review", run.search_summary.human_review, border=True)
        st.metric("Could not safely assess", run.search_summary.could_not_safely_assess, border=True)

    trial_column, detail_column = st.columns((1, 3), gap="large")
    with trial_column:
        st.subheader("Trials")
        labels = {
            item.trial_id: (
                f"{item.trial_id}\n{_short_title(item.title)}\n"
                f"{researcher_status(item)} · {len(item.criteria)} criteria"
            )
            for item in run.trial_results
        }
        chosen = st.radio(
            "Select trial",
            [item.trial_id for item in run.trial_results],
            index=[item.trial_id for item in run.trial_results].index(selected_trial_id),
            format_func=lambda trial_id: labels[trial_id],
            key=f"selected_trial_{run.run_id}",
        )
    with detail_column:
        _render_selected_trial(select_trial_result(run, chosen))
    return chosen


def _render_selected_trial(result: TrialResultSnapshot) -> None:
    overview_tab, criteria_tab, report_tab = st.tabs(["Overview", "Criteria", "Report"])
    with overview_tab:
        st.subheader(result.trial_id)
        st.write(_safe_text(result.title))
        st.metric("Pre-screening status", researcher_status(result), border=True)
        if result.extraction_status == "FAIL":
            st.error("COULD NOT SAFELY ASSESS")
            st.write(
                "Reason: "
                f"{_safe_optional_text(result.extraction.failure_category) or 'NOT_AVAILABLE'}"
                f" / {_safe_optional_text(result.extraction.validation_stage) or 'NOT_AVAILABLE'}"
            )
            st.info("No patient-trial assessment was performed.")
            return
        counts = criteria_counts_for_result(result)
        with st.container(horizontal=True):
            st.metric("MET", counts["MET"], border=True)
            st.metric("NOT_MET", counts["NOT_MET"], border=True)
            st.metric("UNKNOWN", counts["UNKNOWN"], border=True)
        st.markdown("**Missing information**")
        _render_bullets(result.missing_information, "None recorded")
        verification = result.verification.decision if result.verification else "NOT_EVALUATED"
        coordinator = result.coordinator.action if result.coordinator else "NOT_EVALUATED"
        st.write(f"**Verification status:** {_safe_text(verification)}")
        st.write(f"**Coordinator outcome:** {_safe_text(coordinator)}")
        st.write(f"**Final workflow outcome:** {_safe_optional_text(result.final_outcome) or 'NOT_AVAILABLE'}")
    with criteria_tab:
        rows = criteria_table_rows(result)
        st.dataframe(rows, hide_index=True, width="stretch", key=f"criteria_{result.trial_id}")
        if result.criteria:
            detail_id = st.selectbox(
                "Inspect one criterion",
                [item.criterion_id for item in result.criteria],
                key=f"criterion_detail_{result.trial_id}",
            )
            _render_criterion_detail(
                next(item for item in result.criteria if item.criterion_id == detail_id)
            )
    with report_tab:
        if result.report_markdown is None:
            st.info("No report was generated for this trial result.")
        else:
            st.markdown(_safe_text(result.report_markdown))
            with st.expander("View full Markdown"):
                st.code(_safe_text(result.report_markdown), language="markdown")


def _render_criterion_detail(criterion: CriterionDetail) -> None:
    with st.container(border=True):
        st.markdown(f"**{_safe_text(criterion.criterion_id)} — full evidence**")
        st.write(f"**Trial source criterion:** {_safe_text(criterion.original_text)}")
        st.write(f"**Patient evidence:** {_safe_optional_text(criterion.patient_evidence) or 'Not available'}")
        st.write(f"**Evaluation type:** {_safe_optional_text(criterion.evaluation_type) or 'Not available'}")
        st.write(f"**Operator:** {_safe_optional_text(criterion.operator) or 'Not available'}")
        st.write(f"**Threshold/value:** {_safe_optional_text(criterion.threshold_value) or 'Not available'}")
        st.write(f"**Temporal window:** {_safe_optional_text(criterion.temporal_window) or 'Not available'}")
        st.write(f"**Reason:** {_safe_optional_text(criterion.reason) or 'Not available'}")
        st.write("**Required patient fields:** " + ", ".join(criterion.required_patient_fields or ["None"]))
        st.write(f"**Human-review detail:** {_safe_optional_text(criterion.human_review_detail) or 'None'}")


def _render_developer_debug(run: RunSnapshot, result: TrialResultSnapshot) -> None:
    st.title("Developer Debug")
    st.caption("Safe observability data for the currently selected run and trial.")
    with st.container(horizontal=True):
        st.metric("Run ID", _safe_text(run.run_id), border=True)
        st.metric("Patient ID", _safe_text(run.patient_snapshot.patient_id), border=True)
        st.metric("Trial ID", _safe_text(result.trial_id), border=True)
        st.metric("Final outcome", _safe_optional_text(result.final_outcome) or "NOT_AVAILABLE", border=True)
        st.metric("Error status", "ERROR" if result.error else "NONE", border=True)
    timeline_tab, extraction_tab, evaluation_tab, agents_tab, graph_tab, errors_tab = st.tabs(
        ["Workflow timeline", "Extraction", "Evaluation", "Agents", "Graph", "Errors"]
    )
    with timeline_tab:
        st.dataframe(_trace_timeline(result), hide_index=True, width="stretch")
    with extraction_tab:
        st.dataframe([_extraction_view(result.extraction)], hide_index=True, width="stretch")
    with evaluation_tab:
        st.dataframe(criteria_table_rows(result), hide_index=True, width="stretch")
    with agents_tab:
        agent_columns = st.columns(2)
        with agent_columns[0]:
            st.subheader("Verification Agent")
            st.dataframe([_verification_view(result.verification)], hide_index=True, width="stretch")
        with agent_columns[1]:
            st.subheader("Coordinator Agent")
            st.dataframe([_coordinator_view(result.coordinator)], hide_index=True, width="stretch")
    with graph_tab:
        nodes = [step.step_name for step in result.trace.steps] if result.trace else []
        st.code("\n-> ".join([*nodes, "END"]) if nodes else "Trace was not captured in this artifact.")
    with errors_tab:
        error = result.error or _error_from_result(result)
        if error is None:
            st.success("No structured workflow error recorded.")
        else:
            st.error("This trial result remains inspectable after a safe failure.")
            st.dataframe([_error_view(error)], hide_index=True, width="stretch")


def criteria_counts_for_result(result: TrialResultSnapshot) -> dict[str, int]:
    return {
        status: sum(item.criterion_status == status for item in result.criteria)
        for status in ("MET", "NOT_MET", "UNKNOWN")
    }


def _legacy_run_snapshot(run: DashboardRun) -> RunSnapshot:
    detail_rows = [
        CriterionDetail(
            **row.model_dump(),
            short_requirement=row.criterion_id,
            original_text=row.criterion_id,
        )
        for row in run.criteria_debug
    ]
    result = TrialResultSnapshot(
        trial_id=run.trace.trial_id,
        title="Saved workflow trace",
        extraction_status="FAIL" if run.error and run.error.node == "EXTRACT" else "PASS",
        criteria=detail_rows,
        trial_assessment=run.trial_assessment,
        verification=run.verification,
        coordinator=run.coordinator,
        trace=run.trace,
        final_outcome=run.trace.final_outcome,
        extraction=run.extraction,
        error=run.error,
    )
    return RunSnapshot(
        run_id=run.trace.run_id,
        patient_snapshot=PatientSnapshot(patient_id=run.trace.patient_id),
        search_summary=_search_summary([result]),
        trial_results=[result],
        run_status="ERROR" if run.error else "COMPLETED",
    )


def _trial_result_from_report(path: Path) -> TrialResultSnapshot:
    text = path.read_text(encoding="utf-8")
    criteria = _criteria_from_report(text)
    assessment = _report_value(text, "Trial assessment")
    verification_status = _report_value_in_section(text, "Verification", "Status")
    verification_reason = _report_value_in_section(text, "Verification", "Reason")
    coordinator_action = _report_value_in_section(text, "Coordinator Outcome", "Action")
    coordinator_reason = _report_value_in_section(text, "Coordinator Outcome", "Reason")
    missing = _report_list_section(text, "Missing Information")
    return TrialResultSnapshot(
        trial_id=_report_value(text, "Trial ID") or path.stem,
        title=_report_value(text, "Trial title") or "Not available",
        extraction_status="PASS",
        criteria=criteria,
        trial_assessment=assessment,
        verification=(
            VerificationDebug(decision=verification_status, reason=verification_reason or "Not available")
            if verification_status
            else None
        ),
        coordinator=(
            CoordinatorDebug(action=coordinator_action, reason=coordinator_reason or "Not available")
            if coordinator_action
            else None
        ),
        missing_information=missing,
        report_markdown=text,
        final_outcome=coordinator_action or assessment,
        extraction=ExtractionDebug(
            criteria_source=CriteriaSource.LIVE_LLM,
            criteria_count=len(criteria),
            validation_result="PASSED_FROM_SAVED_REPORT",
        ),
    )


def _criteria_from_report(text: str) -> list[CriterionDetail]:
    criteria: list[CriterionDetail] = []
    current: dict[str, object] | None = None
    for line in text.splitlines():
        match = re.match(r"^- ((?:INC|EXC)-\d+): ([A-Z_]+)$", line)
        if match:
            if current is not None:
                criteria.append(CriterionDetail.model_validate(current))
            current = {
                "criterion_id": match.group(1),
                "criterion_type": "INCLUSION" if match.group(1).startswith("INC") else "EXCLUSION",
                "criterion_status": match.group(2),
                "short_requirement": match.group(1),
                "original_text": match.group(1),
            }
            continue
        if current is None:
            continue
        for label, key in (
            ("  - Trial evidence: ", "original_text"),
            ("  - Patient evidence: ", "patient_evidence"),
            ("  - Missing information: ", "missing_information"),
            ("  - Human review required: ", "requires_human_review"),
        ):
            if line.startswith(label):
                value = line.removeprefix(label)
                if key == "missing_information":
                    current[key] = [] if value == "None" else [value]
                elif key == "requires_human_review":
                    current[key] = value == "Yes"
                else:
                    current[key] = value
                break
    if current is not None:
        criteria.append(CriterionDetail.model_validate(current))
    for item in criteria:
        item.short_requirement = _short_title(item.original_text)
    return criteria


def _report_value(text: str, label: str) -> str | None:
    match = re.search(rf"^- {re.escape(label)}: (.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _report_value_in_section(text: str, section: str, label: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(section)}\n- {re.escape(label)}: (.+)$",
        text,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else None


def _report_list_section(text: str, section: str) -> list[str]:
    match = re.search(rf"^## {re.escape(section)}\n(?P<items>(?:- .+\n)+)", text, flags=re.MULTILINE)
    if not match:
        return []
    return [line.removeprefix("- ") for line in match.group("items").splitlines() if line != "- None"]


def _search_summary(results: list[TrialResultSnapshot]) -> SearchSummary:
    statuses = [researcher_status(item) for item in results]
    return SearchSummary(
        trials_found=len(results),
        successfully_assessed=sum(item.extraction_status == "PASS" for item in results),
        need_more_information=statuses.count("NEEDS MORE INFORMATION"),
        human_review=statuses.count("HUMAN REVIEW"),
        could_not_safely_assess=statuses.count("COULD NOT SAFELY ASSESS"),
    )


def _trace_timeline(result: TrialResultSnapshot) -> list[dict[str, object]]:
    if result.trace is None:
        return [{"stage": "TRACE", "status": "NOT_CAPTURED", "duration_ms": None, "important_output": "Saved report artifact", "error": ""}]
    return _timeline_rows(
        DashboardRun(
            trace=result.trace,
            criteria_source=result.extraction.criteria_source.value,
            extraction=result.extraction.model_dump(mode="json"),
            error=(result.error.model_dump(mode="json") if result.error else None),
        )
    )


def _error_from_result(result: TrialResultSnapshot) -> DashboardError | None:
    if result.extraction_status == "FAIL":
        return DashboardError(
            node="EXTRACT",
            error_type="CriteriaExtractionError",
            failure_category=result.extraction.failure_category,
            validation_stage=result.extraction.validation_stage,
            graph_status="NOT_STARTED",
        )
    return None


def _short_title(value: str, limit: int = 80) -> str:
    clean = " ".join(value.split())
    return clean if len(clean) <= limit else f"{clean[: limit - 1]}…"


def _render_bullets(items: list[str], empty_message: str) -> None:
    if not items:
        st.write(empty_message)
        return
    for item in items:
        st.write(f"• {_safe_text(item)}")


def run_snapshot_from_live_run(live_run: LivePrescreeningRun) -> RunSnapshot:
    """Project one completed application-service run into immutable UI data."""

    results: list[TrialResultSnapshot] = []
    for item in live_run.trials:
        if item.extraction_error is not None:
            failure = item.extraction_error
            validation_stage = (
                failure.validation_category.value
                if failure.validation_category is not None
                else None
            )
            extraction = ExtractionDebug(
                criteria_source=CriteriaSource.LIVE_LLM,
                provider_attempts=failure.provider_attempts,
                extraction_repair_attempts=failure.extraction_repair_attempts,
                repair_attempted=failure.extraction_repair_attempts > 0,
                provider_error_code=failure.provider_error_code,
                validation_result="FAILED",
                failure_category=failure.category.value,
                validation_stage=validation_stage,
            )
            results.append(
                TrialResultSnapshot(
                    trial_id=item.trial.trial_id,
                    title=item.trial.title,
                    extraction_status="FAIL",
                    extraction=extraction,
                    error=DashboardError(
                        node="EXTRACT",
                        error_type=type(failure).__name__,
                        failure_category=failure.category.value,
                        validation_stage=validation_stage,
                        graph_status="NOT_STARTED",
                    ),
                    final_outcome="FAILED",
                )
            )
            continue
        extraction = _extraction_debug_from_trace(item.trace, len(item.criteria))
        results.append(
            TrialResultSnapshot(
                trial_id=item.trial.trial_id,
                title=item.trial.title,
                extraction_status="PASS",
                criteria=_criterion_details(item.criteria, item.criterion_assessments),
                trial_assessment=(
                    item.trial_assessment.status.value
                    if item.trial_assessment is not None
                    else None
                ),
                verification=(
                    VerificationDebug(
                        decision=item.verification_result.status.value,
                        reason=item.verification_result.summary_reason,
                        issues_or_corrections=[
                            finding.finding for finding in item.verification_result.findings
                        ],
                    )
                    if item.verification_result is not None
                    else None
                ),
                coordinator=(
                    CoordinatorDebug(
                        action=item.coordinator_decision.action.value,
                        reason=item.coordinator_decision.reason,
                    )
                    if item.coordinator_decision is not None
                    else None
                ),
                missing_information=list(item.missing_information),
                trace=item.trace,
                report_markdown=render_report(item.report) if item.report is not None else None,
                final_outcome=item.final_outcome,
                extraction=extraction,
                error=_error_from_live_trace(item.trace, extraction),
            )
        )
    return RunSnapshot(
        run_id=live_run.run_id,
        patient_snapshot=PatientSnapshot(
            patient_id=live_run.patient_snapshot.patient_id,
            condition=live_run.patient_snapshot.condition,
            country=live_run.patient_snapshot.country,
        ),
        search_summary=_search_summary(results),
        trial_results=results,
        run_status="COMPLETED",
    )


def _criterion_details(
    criteria: list[object], assessments: list[object]
) -> list[CriterionDetail]:
    assessments_by_id = {item.criterion_id: item for item in assessments}
    details: list[CriterionDetail] = []
    for criterion in criteria:
        assessment = assessments_by_id.get(criterion.criterion_id)
        details.append(
            CriterionDetail(
                criterion_id=criterion.criterion_id,
                criterion_type=criterion.criterion_type.value,
                canonical_fact=criterion.field_name,
                patient_evidence=(assessment.patient_evidence if assessment else None),
                criterion_status=(assessment.status.value if assessment else "NOT_EVALUATED"),
                missing_information=(list(assessment.missing_information) if assessment else []),
                requires_human_review=(
                    assessment.requires_human_review if assessment else criterion.requires_human_review
                ),
                short_requirement=_short_title(criterion.original_text),
                original_text=criterion.original_text,
                evaluation_type=criterion.evaluation_type.value,
                operator=criterion.operator.value if criterion.operator is not None else None,
                threshold_value=_criterion_threshold(criterion),
                temporal_window=(
                    f"{criterion.temporal_window.value} {criterion.temporal_window.unit.value}"
                    if criterion.temporal_window is not None
                    else None
                ),
                reason=assessment.reason if assessment else None,
                required_patient_fields=list(criterion.required_patient_fields),
                human_review_detail=(
                    "Human review is required for this criterion."
                    if (assessment and assessment.requires_human_review)
                    else None
                ),
            )
        )
    return details


def _criterion_threshold(criterion: object) -> str | None:
    values = [
        getattr(criterion, name)
        for name in ("value", "lower_value", "upper_value")
        if getattr(criterion, name) is not None
    ]
    return ", ".join(str(value) for value in values) or None


def _extraction_debug_from_trace(
    trace: WorkflowTrace | None, criteria_count: int
) -> ExtractionDebug:
    if trace is None:
        return ExtractionDebug(
            criteria_source=CriteriaSource.LIVE_LLM,
            criteria_count=criteria_count,
            validation_result="NOT_AVAILABLE",
        )
    return _extraction_from_trace(trace, CriteriaSource.LIVE_LLM).model_copy(
        update={"criteria_count": criteria_count}
    )


def _error_from_live_trace(
    trace: WorkflowTrace | None, extraction: ExtractionDebug
) -> DashboardError | None:
    if trace is None:
        return None
    return _error_from_trace(trace, extraction)


def _optional_decimal(value: str) -> Decimal | None:
    stripped = value.strip()
    if not stripped:
        return None
    return Decimal(stripped)


def _synthetic_patient_profiles() -> dict[str, PatientProfile]:
    return {
        "DEMO-P001": PatientProfile(
            patient_id="DEMO-P001",
            age=48,
            sex="FEMALE",
            country="India",
            condition="Type 2 Diabetes",
            consent_for_demo=True,
            diagnosis_date=date(2022, 6, 15),
            laboratory_results=[{"test_name": "HbA1c", "value": "8.2", "unit": "%"}],
            bmi=Decimal("29.1"),
            medications=[{"medication_name": "Metformin", "status": "CURRENT"}],
            medical_history=[
                {
                    "condition_name": "Heart attack",
                    "status": "RESOLVED",
                    "diagnosis_date": date(2025, 1, 1),
                },
                {
                    "condition_name": "Stroke",
                    "status": "RESOLVED",
                    "diagnosis_date": date(2025, 1, 1),
                },
                {
                    "condition_name": "Congestive heart failure",
                    "status": "ACTIVE",
                    "notes": "NYHA Class II",
                },
                {"condition_name": "Morbid obesity", "status": "RESOLVED"},
            ],
        )
    }


if __name__ == "__main__":
    main()
