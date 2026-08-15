"""A small in-memory collector with no persistence or sensitive payload capture."""

from datetime import UTC, datetime
from uuid import uuid4

from clinical_trial_prescreener.observability.trace_models import (
    TraceStep,
    WorkflowTrace,
)


class TraceCollector:
    def __init__(self) -> None:
        self._trace: WorkflowTrace | None = None

    def start(self, *, patient_id: str, trial_id: str) -> WorkflowTrace:
        if self._trace is None:
            self._trace = WorkflowTrace(
                run_id=str(uuid4()),
                patient_id=patient_id,
                trial_id=trial_id,
                started_at=datetime.now(UTC),
            )
        return self._trace

    def record(self, step: TraceStep) -> WorkflowTrace:
        if self._trace is None:
            raise RuntimeError("trace must be started before recording steps")
        self._trace.steps.append(step)
        return self._trace

    def complete(self, outcome: str) -> WorkflowTrace:
        if self._trace is None:
            raise RuntimeError("trace must be started before completion")
        self._trace.completed_at = datetime.now(UTC)
        self._trace.final_outcome = outcome
        return self._trace
