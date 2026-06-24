from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.agent.patient_agent import PatientAgent
from app.agent.scenario_loader import Scenario
from app.agent.state import ConversationState, ConversationTurn, LatencySnapshot
from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.config import AppSettings
from app.safety import AUTHORIZED_DESTINATION, mask_phone_number
from app.storage.metadata import CallMetadata
from app.voice.audio import duration_ms_from_text


@dataclass(slots=True)
class DryRunResult:
    transcript: TranscriptDocument
    metadata: CallMetadata


class OfficeAgentSimulator:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.step = 0

    def next_message(self, state: ConversationState) -> str | None:
        handler = getattr(self, f"_message_{self.scenario.category}", self._message_default)
        message = handler(state)
        if message is not None:
            self.step += 1
        return message

    def _message_default(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Thanks for calling. How can I help today?",
            "Can I get your full name and date of birth?",
            "Thanks, I can help with that. Anything else today?",
        ]
        if self.step >= len(sequence):
            return None
        return sequence[self.step]

    def _message_scheduling(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Thanks for calling Athena. How can I help today?",
            "What day next week works best for you?",
            "What time would you prefer?",
            "Can I get your full name and date of birth?",
            f"I have {self.scenario.background.details['confirmed_slot']} available. Does that work for you?",
            f"You're scheduled for {self.scenario.background.details['confirmed_slot']}. Anything else I can help with?",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_reschedule(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Thanks for calling Athena. What can I help with today?",
            "What is your current appointment time?",
            "What new day or time would you prefer?",
            "Can I get your full name and date of birth?",
            f"I can move that to {self.scenario.background.details['rescheduled_slot']}.",
            f"Your visit has been rescheduled to {self.scenario.background.details['rescheduled_slot']}. Anything else?",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_cancel(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Athena scheduling, how can I help?",
            "Which appointment would you like to cancel?",
            "I don't see a cancellation fee noted here.",
            "That appointment has been canceled. Anything else I can help with?",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_refill(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Athena support, how can I help today?",
            "Which medication are you calling about?",
            "What dose do you take?",
            "What pharmacy should we use?",
            "Thanks. I'll send a refill request to the clinician for review.",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_office_info(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Athena office information, how can I help?",
            "We're open Monday through Friday from 8 AM to 5 PM, we're at 240 Harbor Avenue, and visitor parking is in the south lot.",
            "We're open this Friday but closed on Sunday.",
            "Anything else I can help with today?",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_insurance(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Athena billing, how can I help?",
            "What insurance plan are you asking about?",
            "I can't guarantee coverage, but we can tell you we're in-network for many plans and recommend confirming with your insurer.",
            "Anything else I can help with?",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_weekend_edge(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Athena scheduling, how can I help?",
            "What day were you hoping for?",
            "We're closed on Sundays, but I can offer Monday morning instead.",
            "Anything else I can help with?",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_ambiguous(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Athena care line, how can I help?",
            "Can you tell me a little more about what feels wrong?",
            "I can offer the next available same-week visit, or connect you with a nurse if it feels urgent.",
            "Anything else I can help with?",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_interruption(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Athena scheduling, how can I help today?",
            (
                "Let me explain all of our appointment categories, provider templates, "
                "intake rules, and check-in expectations before we choose a slot."
            ),
            "Understood. What time on Tuesday works best for you?",
            "You're confirmed for Tuesday at 9:30 AM. Anything else I can help with?",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_context_change(self, state: ConversationState) -> str | None:
        changed = state.facts_disclosed.get("change_requested") == "yes"
        if not changed:
            sequence = [
                "Athena scheduling, how can I help?",
                "What day works best for you?",
                "What is the visit for?",
                f"I can tentatively hold {self.scenario.background.details['initial_hold']}. Does that work?",
            ]
            index = self.step
        else:
            sequence = [
                f"Thanks for clarifying. I can update that to {self.scenario.background.details['changed_hold']}.",
                (
                    "Just confirming, the visit is now "
                    f"{self.scenario.background.details['changed_reason']} on "
                    f"{self.scenario.background.details['changed_hold']}."
                ),
            ]
            index = self.step - 4
        return sequence[index] if 0 <= index < len(sequence) else None

    def _message_safety_escalation(self, state: ConversationState) -> str | None:
        del state
        sequence = [
            "Athena care line, how can I help today?",
            "Can you tell me more about what's happening right now?",
            "Because of chest tightness, you should seek urgent medical help right away or call 911 if you're in immediate danger.",
        ]
        return sequence[self.step] if self.step < len(sequence) else None

    def _message_repetition_recovery(self, state: ConversationState) -> str | None:
        corrected = bool(state.corrections)
        if not corrected:
            sequence = [
                "Athena scheduling, how can I help?",
                "Maria, what day works best for you?",
                f"Just checking, did you say {self.scenario.background.details['wrong_requested_day']}?",
            ]
            index = self.step
        else:
            sequence = [
                f"Thanks for correcting me. I have {self.scenario.background.details['correct_requested_day']} available.",
                f"You're confirmed for {self.scenario.background.details['correct_requested_day']}. Anything else I can help with?",
            ]
            index = self.step - 2
        return sequence[index] if 0 <= index < len(sequence) else None


class DryRunConversationRunner:
    def __init__(
        self,
        settings: AppSettings,
        scenario: Scenario,
        *,
        response_style: str = "concise",
    ) -> None:
        self.settings = settings
        self.scenario = scenario
        self.response_style = response_style

    def run(self, call_id: str) -> DryRunResult:
        started_at = datetime.now(UTC)
        state = ConversationState(
            scenario_id=self.scenario.id,
            call_id=call_id,
            patient_name=self.scenario.patient.name,
            current_goal=self.scenario.goal.primary,
        )
        patient = PatientAgent(
            self.scenario,
            state,
            response_style=self.response_style,
        )
        office = OfficeAgentSimulator(self.scenario)

        current_second = 0.0
        segments: list[TranscriptSegment] = []

        opening = patient.opening_line()
        current_second = self._append_exchange(
            state=state,
            segments=segments,
            current_second=current_second,
            speaker="PATIENT",
            text=opening,
            latency=LatencySnapshot(model_response_generated_ms=0.0),
            action=state.action_history[-1] if state.action_history else None,
            progress=state.last_goal_progress,
        )

        while state.turn_count < self.scenario.constraints.max_turns:
            agent_text = office.next_message(state)
            if agent_text is None:
                break
            current_second = self._append_exchange(
                state=state,
                segments=segments,
                current_second=current_second,
                speaker="AGENT",
                text=agent_text,
                latency=LatencySnapshot(audio_received_ms=0.0, speech_recognized_ms=0.0),
                confidence=1.0,
                channel="agent",
                speaker_source="simulator",
            )

            reply = patient.reply_to_agent(agent_text)
            for key, value in reply.disclosed_facts.items():
                state.disclose_fact(key, value)

            patient_start = current_second
            overlap_ms = 0
            if reply.allow_overlap and segments:
                last_agent_segment = segments[-1]
                overlap_ms = min(850, int((last_agent_segment.end_timestamp - last_agent_segment.start_timestamp) * 1000))
                patient_start = max(
                    last_agent_segment.start_timestamp + 0.35,
                    last_agent_segment.end_timestamp - (overlap_ms / 1000),
                )
                state.record_barge_in(successful=True, overlap_duration_ms=overlap_ms)

            current_second = self._append_exchange(
                state=state,
                segments=segments,
                current_second=patient_start,
                speaker="PATIENT",
                text=reply.text,
                interrupted=bool(reply.correction),
                latency=LatencySnapshot(model_response_generated_ms=0.0),
                action=reply.action,
                progress=reply.scenario_goal_progress,
                channel="patient",
                speaker_source="simulator",
                overlap_duration_ms=overlap_ms,
                confidence=1.0,
            )
            if reply.should_end_call:
                break

        if not state.termination_reason:
            state.mark_terminated("dry_run_complete")

        transcript = TranscriptDocument(
            call_id=call_id,
            scenario_id=self.scenario.id,
            created_on=started_at.date(),
            duration_seconds=current_second,
            segments=segments,
        )

        metadata = CallMetadata(
            call_id=call_id,
            provider="simulator",
            scenario_id=self.scenario.id,
            destination_number=AUTHORIZED_DESTINATION,
            originating_number_masked=mask_phone_number(self.settings.telephony_from_number),
            start_time=started_at,
            end_time=started_at,
            duration_seconds=current_second,
            call_status="completed",
            mode="dry_run",
            is_real_call=False,
            transcript_generation_status="completed",
            transcript_generated_at=started_at,
            transcript_source="dry_run_simulation",
            transcript_strategy="dry_run_scripted_turns",
            transcript_path=f"artifacts/transcripts/{call_id}.txt",
            estimated_cost_usd=0.0,
            model_names={"llm": self.settings.llm_model},
            average_response_latency_ms=0.0,
            termination_reason=state.termination_reason,
            analysis_completion_status="pending",
        )
        return DryRunResult(transcript=transcript, metadata=metadata)

    def _append_exchange(
        self,
        *,
        state: ConversationState,
        segments: list[TranscriptSegment],
        current_second: float,
        speaker: str,
        text: str,
        latency: LatencySnapshot,
        interrupted: bool = False,
        action: str | None = None,
        progress: float | None = None,
        channel: str | None = None,
        speaker_source: str = "simulator",
        overlap_duration_ms: int = 0,
        confidence: float | None = None,
    ) -> float:
        duration_ms = duration_ms_from_text(text)
        start = current_second
        end = current_second + (duration_ms / 1000)
        state.append_turn(
            ConversationTurn(
                speaker=speaker,  # type: ignore[arg-type]
                text=text,
                start_timestamp=start,
                end_timestamp=end,
                confidence=confidence,
                interruption_status=interrupted,
                latency=latency,
                action=action,
                goal_progress=progress,
                channel=channel,  # type: ignore[arg-type]
                speaker_source=speaker_source,
                overlap_duration_ms=overlap_duration_ms,
            )
        )
        segments.append(
            TranscriptSegment(
                speaker=speaker,  # type: ignore[arg-type]
                start_timestamp=start,
                end_timestamp=end,
                text=text,
                confidence=confidence,
                interruption_status=interrupted,
                latency_metadata=latency.model_dump(),
                action=action,
                channel=channel,  # type: ignore[arg-type]
                speaker_source=speaker_source,
                goal_progress=progress,
                overlap_duration_ms=overlap_duration_ms,
            )
        )
        return max(end, max((segment.end_timestamp for segment in segments), default=end))
