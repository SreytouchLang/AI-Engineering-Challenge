from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LatencySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_received_ms: float | None = None
    speech_recognized_ms: float | None = None
    model_response_generated_ms: float | None = None
    speech_playback_started_ms: float | None = None


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Literal["PATIENT", "AGENT", "SYSTEM"]
    text: str
    start_timestamp: float | None = None
    end_timestamp: float | None = None
    confidence: float | None = None
    interruption_status: bool = False
    latency: LatencySnapshot = Field(default_factory=LatencySnapshot)


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
    scenario_completed: bool = False
    termination_reason: str | None = None
    conversation: list[ConversationTurn] = Field(default_factory=list)

    def append_turn(self, turn: ConversationTurn) -> None:
        self.conversation.append(turn)
        if turn.speaker != "SYSTEM":
            self.turn_count += 1
        if turn.interruption_status:
            self.interruption_count += 1

    def disclose_fact(self, key: str, value: str) -> None:
        self.facts_disclosed[key] = value

    def confirm_fact(self, key: str, value: str) -> None:
        self.facts_confirmed_by_agent[key] = value

    def register_correction(self, correction: str) -> None:
        if correction not in self.corrections:
            self.corrections.append(correction)

    def ensure_identity_consistency(self, name: str) -> None:
        if name != self.patient_name:
            raise ValueError(
                f"Patient identity changed from {self.patient_name!r} to {name!r}."
            )

    def recent_context(self, limit: int = 6) -> list[ConversationTurn]:
        return self.conversation[-limit:]

    def mark_complete(self, reason: str) -> None:
        self.scenario_completed = True
        self.termination_reason = reason

    def mark_terminated(self, reason: str) -> None:
        self.termination_reason = reason

    def compact_summary(self) -> str:
        recent_turns = [
            f"{turn.speaker}: {turn.text}" for turn in self.recent_context(limit=4)
        ]
        return (
            f"goal={self.current_goal}; "
            f"disclosed={self.facts_disclosed}; "
            f"confirmed={self.facts_confirmed_by_agent}; "
            f"corrections={self.corrections}; "
            f"recent={recent_turns}"
        )

