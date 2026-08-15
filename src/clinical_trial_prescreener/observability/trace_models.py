"""Safe, compact models for workflow observability."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_name: str
    status: str
    duration_ms: int
    input_summary: dict[str, object] = Field(default_factory=dict)
    output_summary: dict[str, object] = Field(default_factory=dict)
    decision: str | None = None
    error: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class WorkflowTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    patient_id: str
    trial_id: str
    started_at: datetime
    completed_at: datetime | None = None
    final_outcome: str | None = None
    steps: list[TraceStep] = Field(default_factory=list)
