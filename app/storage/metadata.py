from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CallMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    provider_call_id: str | None = None
    provider_recording_id: str | None = None
    provider_recording_status: str | None = None
    provider_recording_channels: str | None = None
    provider_recording_source: str | None = None
    provider_recording_url: str | None = None
    scenario_id: str
    destination_number: str
    originating_number_masked: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_seconds: float | None = None
    call_status: str
    mode: str = "dry_run"
    recording_path: str | None = None
    patient_recording_path: str | None = None
    agent_recording_path: str | None = None
    mixed_recording_path: str | None = None
    transcript_path: str | None = None
    transcript_validation_path: str | None = None
    transcript_validation_status: str = "pending"
    quality_report_path: str | None = None
    quality_score: int | None = None
    average_transcript_confidence: float | None = None
    estimated_cost_usd: float = Field(default=0, ge=0)
    model_names: dict[str, str] = Field(default_factory=dict)
    average_response_latency_ms: float | None = None
    termination_reason: str | None = None
    analysis_completion_status: str = "pending"
    submission_ready: bool = False
    reviewer_notes: str | None = None
    problems: list[str] = Field(default_factory=list)
