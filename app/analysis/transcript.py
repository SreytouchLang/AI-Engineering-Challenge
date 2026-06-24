from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Literal["PATIENT", "AGENT", "SYSTEM"]
    start_timestamp: float
    end_timestamp: float
    text: str
    confidence: float | None = None
    interruption_status: bool = False
    latency_metadata: dict[str, float | None] = Field(default_factory=dict)
    action: str | None = None
    channel: Literal["patient", "agent", "system", "mixed"] | None = None
    speaker_source: str = "simulator"
    goal_progress: float | None = None
    overlap_duration_ms: int = 0

    @field_validator("end_timestamp")
    @classmethod
    def _validate_end_timestamp(cls, value: float, info) -> float:
        start = info.data.get("start_timestamp")
        if start is not None and value < start:
            raise ValueError("Transcript segment end time cannot precede start time.")
        return value


class TranscriptDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    scenario_id: str
    created_on: date
    duration_seconds: float
    segments: list[TranscriptSegment]

    @model_validator(mode="after")
    def _validate_ordering(self) -> TranscriptDocument:
        previous_start = -1.0
        for segment in self.segments:
            if segment.start_timestamp < previous_start:
                raise ValueError("Transcript segment start timestamps must be monotonically ordered.")
            previous_start = segment.start_timestamp
        return self

    def require_agent_turns(self) -> None:
        if not any(segment.speaker == "AGENT" for segment in self.segments):
            raise ValueError("Transcript must include at least one AGENT turn.")

    def render_text(self) -> str:
        header = [
            f"Call: {self.call_id}",
            f"Scenario: {self.scenario_id}",
            f"Date: {self.created_on.isoformat()}",
            f"Duration: {format_duration(self.duration_seconds)}",
            "",
        ]
        body = [
            f"[{format_segment_timestamp(segment.start_timestamp)} - "
            f"{format_segment_timestamp(segment.end_timestamp)}] "
            f"{segment.speaker}: {segment.text}"
            for segment in self.segments
        ]
        return "\n".join(header + body) + "\n"


def format_duration(duration_seconds: float) -> str:
    minutes = int(duration_seconds // 60)
    seconds = duration_seconds - (minutes * 60)
    return f"{minutes:02d}:{seconds:04.1f}"


def format_segment_timestamp(timestamp_seconds: float) -> str:
    minutes = int(timestamp_seconds // 60)
    seconds = timestamp_seconds - (minutes * 60)
    return f"{minutes:02d}:{seconds:04.1f}"
