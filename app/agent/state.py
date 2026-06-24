from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LatencySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_received_ms: float | None = None
    speech_recognized_ms: float | None = None
    model_response_generated_ms: float | None = None
    speech_playback_started_ms: float | None = None
    stt_latency_ms: float | None = None
    llm_latency_ms: float | None = None
    tts_latency_ms: float | None = None
    total_response_latency_ms: float | None = None
    silence_before_turn_ms: float | None = None


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Literal["PATIENT", "AGENT", "SYSTEM"]
    text: str
    start_timestamp: float | None = None
    end_timestamp: float | None = None
    confidence: float | None = None
    interruption_status: bool = False
    latency: LatencySnapshot = Field(default_factory=LatencySnapshot)
    action: str | None = None
    channel: Literal["patient", "agent", "system", "mixed"] | None = None
    speaker_source: str = "simulator"
    goal_progress: float | None = None
    overlap_duration_ms: int = 0


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    call_id: str
    patient_name: str
    current_goal: str
    facts_disclosed: dict[str, str] = Field(default_factory=dict)
    facts_confirmed_by_agent: dict[str, str] = Field(default_factory=dict)
    unresolved_questions: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    turn_count: int = 0
    interruption_count: int = 0
    successful_barge_ins: int = 0
    accidental_interruptions: int = 0
    overlap_duration_ms: int = 0
    scenario_completed: bool = False
    termination_reason: str | None = None
    conversation: list[ConversationTurn] = Field(default_factory=list)
    action_history: list[str] = Field(default_factory=list)
    last_goal_progress: float | None = None

    def append_turn(self, turn: ConversationTurn) -> None:
        self.conversation.append(turn)
        if turn.speaker != "SYSTEM":
            self.turn_count += 1
        if turn.interruption_status:
            self.interruption_count += 1
        if turn.overlap_duration_ms:
            self.overlap_duration_ms += turn.overlap_duration_ms

    def disclose_fact(self, key: str, value: str) -> None:
        self.facts_disclosed[key] = value

    def confirm_fact(self, key: str, value: str) -> None:
        self.facts_confirmed_by_agent[key] = value

    def register_correction(self, correction: str) -> None:
        if correction not in self.corrections:
            self.corrections.append(correction)

    def register_action(self, action: str, progress: float | None = None) -> None:
        self.action_history.append(action)
        if progress is not None:
            self.last_goal_progress = progress

    def has_action(self, action: str) -> bool:
        return action in self.action_history

    def record_barge_in(self, *, successful: bool, overlap_duration_ms: int = 0) -> None:
        if successful:
            self.successful_barge_ins += 1
        else:
            self.accidental_interruptions += 1
        if overlap_duration_ms:
            self.overlap_duration_ms += overlap_duration_ms

    def ensure_identity_consistency(self, name: str) -> None:
        if name != self.patient_name:
            raise ValueError(f"Patient identity changed from {self.patient_name!r} to {name!r}.")

    def recent_context(self, limit: int = 6) -> list[ConversationTurn]:
        return self.conversation[-limit:]

    def mark_complete(self, reason: str) -> None:
        self.scenario_completed = True
        self.termination_reason = reason

    def mark_terminated(self, reason: str) -> None:
        self.termination_reason = reason

    def compact_summary(self) -> str:
        recent_turns = [f"{turn.speaker}: {turn.text}" for turn in self.recent_context(limit=4)]
        return (
            f"goal={self.current_goal}; "
            f"disclosed={self.facts_disclosed}; "
            f"confirmed={self.facts_confirmed_by_agent}; "
            f"corrections={self.corrections}; "
            f"actions={self.action_history[-4:]}; "
            f"recent={recent_turns}"
        )
