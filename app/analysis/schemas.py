from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvaluationScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_completion: int = Field(ge=1, le=5)
    factual_consistency: int = Field(ge=1, le=5)
    scheduling_correctness: int = Field(ge=1, le=5)
    context_retention: int = Field(ge=1, le=5)
    clarification_quality: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    conversation_quality: int = Field(ge=1, le=5)


class EvaluationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    severity: Severity
    category: str
    timestamp: str
    evidence: str
    evidence_excerpt: str | None = None
    expected_behavior: str
    actual_behavior: str | None = None
    user_impact: str
    recording_path: str | None = None
    transcript_path: str | None = None
    reproduction_steps: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    review_status: str = "pending"
    review_notes: str | None = None
    transcript_confidence: float | None = Field(default=None, ge=0, le=1)
    duplicate_of: str | None = None

    @field_validator("timestamp", "evidence", "title", "category")
    @classmethod
    def _require_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Evaluation issue fields must not be blank.")
        return value


class CallEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    scenario_id: str
    summary: str
    scenario_completed: bool
    agent_outcome: str
    expected_outcome: str
    scores: EvaluationScores
    issues: list[EvaluationIssue] = Field(default_factory=list)
    transcript_validation_passed: bool = True
    quality_score: int | None = None

    @model_validator(mode="after")
    def _require_evidence(self) -> CallEvaluation:
        for issue in self.issues:
            if not issue.evidence or not issue.timestamp:
                raise ValueError("Each evaluation issue must include evidence and a timestamp.")
        return self
