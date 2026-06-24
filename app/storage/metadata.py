from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CallMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    provider_call_id: str | None = None
    scenario_id: str
    destination_number: str
    originating_number_masked: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_seconds: float | None = None
    call_status: str
    mode: str = "dry_run"
    recording_path: str | None = None
    transcript_path: str | None = None
    estimated_cost_usd: float = Field(default=0, ge=0)
    model_names: dict[str, str] = Field(default_factory=dict)
    average_response_latency_ms: float | None = None
    termination_reason: str | None = None
    analysis_completion_status: str = "pending"

