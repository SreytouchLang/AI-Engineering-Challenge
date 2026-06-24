from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import WebSocket

from app.agent.patient_agent import OpenAITextGenerationClient, PatientAgent
from app.agent.scenario_loader import Scenario, load_scenarios
from app.agent.state import ConversationState, ConversationTurn, LatencySnapshot
from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.config import AppSettings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata
from app.voice.audio import chunk_mulaw_audio
from app.voice.interruption import InterruptionController
from app.voice.stt import OpenAITranscriptionClient
from app.voice.tts import OpenAITtsClient
from app.voice.turn_manager import CompletedTurn, TurnManager


class MediaStreamSessionRegistry:
    def __init__(self, settings: AppSettings, artifact_store: ArtifactStore) -> None:
        self.settings = settings
        self.artifact_store = artifact_store
        self.sessions: dict[str, MediaStreamSession] = {}
        self._scenario_index = self._load_scenario_index(settings.project_root / "scenarios")

    def get_or_create(self, call_id: str, scenario_id: str) -> "MediaStreamSession":
        if call_id not in self.sessions:
            scenario = self._scenario_index[scenario_id]
            self.sessions[call_id] = MediaStreamSession(
                settings=self.settings,
                artifact_store=self.artifact_store,
                scenario=scenario,
                call_id=call_id,
            )
        return self.sessions[call_id]

    def finalize(self, call_id: str) -> None:
        self.sessions.pop(call_id, None)

    def _load_scenario_index(self, directory: Path) -> dict[str, Scenario]:
        return {scenario.id: scenario for scenario in load_scenarios(directory)}


class MediaStreamSession:
    def __init__(
        self,
        *,
        settings: AppSettings,
        artifact_store: ArtifactStore,
        scenario: Scenario,
        call_id: str,
    ) -> None:
        self.settings = settings
        self.artifact_store = artifact_store
        self.scenario = scenario
        self.call_id = call_id
        self.state = ConversationState(
            scenario_id=scenario.id,
            call_id=call_id,
            patient_name=scenario.patient.name,
            current_goal=scenario.goal.primary,
        )
        self.started_at = datetime.now(UTC)
        self.stream_sid: str | None = None
        self.turn_manager = TurnManager(
            rms_threshold=settings.vad_rms_threshold,
            min_speech_ms=settings.min_speech_ms,
            end_of_turn_silence_ms=settings.end_of_turn_silence_ms,
        )
        self.interruption = InterruptionController()
        self.transcript_segments: list[TranscriptSegment] = []
        self.llm_client = (
            OpenAITextGenerationClient(settings.llm_api_key, settings.llm_model)
            if settings.llm_api_key
            else None
        )
        if not settings.stt_api_key or not settings.tts_api_key:
            raise RuntimeError("STT_API_KEY and TTS_API_KEY are required for live calls.")
        self.patient_agent = PatientAgent(scenario, self.state, self.llm_client)
        self.stt_client = OpenAITranscriptionClient(settings.stt_api_key, settings.stt_model)
        self.tts_client = OpenAITtsClient(
            settings.tts_api_key,
            settings.tts_model,
            settings.tts_voice,
        )

    async def handle_message(self, websocket: WebSocket, raw_message: str) -> None:
        payload = json.loads(raw_message)
        event_type = payload["event"]

        if event_type == "start":
            self.stream_sid = payload["streamSid"]
            await self._send_patient_audio(
                websocket,
                self.patient_agent.opening_line(),
                timestamp_start=0.0,
            )
            return

        if event_type == "media":
            media = payload["media"]
            timestamp_ms = int(media.get("timestamp", 0))
            decoded = base64.b64decode(media["payload"])
            event = self.turn_manager.ingest_mulaw_frame(decoded, timestamp_ms)
            if event.speech_started and self.interruption.should_clear_for_barge_in():
                await websocket.send_json(
                    {"event": "clear", "streamSid": self.stream_sid}
                )
                self.interruption.clear()
            if event.completed_turn is not None:
                await self._process_completed_turn(websocket, event.completed_turn)
            return

        if event_type == "mark":
            self.interruption.acknowledge_mark(payload["mark"]["name"])
            return

        if event_type == "stop":
            tail = self.turn_manager.force_flush(
                int(payload.get("sequenceNumber", 0)) * 20
            )
            if tail is not None:
                await self._process_completed_turn(websocket, tail)
            self._finalize()

    async def _process_completed_turn(
        self,
        websocket: WebSocket,
        turn: CompletedTurn,
    ) -> None:
        transcription = self.stt_client.transcribe(turn.wav_bytes)
        if not transcription.text:
            return
        self._append_segment(
            speaker="AGENT",
            text=transcription.text,
            start_seconds=turn.start_timestamp_ms / 1000,
            end_seconds=turn.end_timestamp_ms / 1000,
            latency=LatencySnapshot(
                audio_received_ms=0.0,
                speech_recognized_ms=transcription.latency_ms,
            ),
        )
        reply = self.patient_agent.reply_to_agent(transcription.text)
        for key, value in reply.disclosed_facts.items():
            self.state.disclose_fact(key, value)

        await self._send_patient_audio(
            websocket,
            reply.text,
            timestamp_start=turn.end_timestamp_ms / 1000,
            interrupted=bool(reply.correction),
        )
        if reply.should_end_call:
            self.state.mark_complete("goal_reached")

    async def _send_patient_audio(
        self,
        websocket: WebSocket,
        text: str,
        *,
        timestamp_start: float,
        interrupted: bool = False,
    ) -> None:
        synthesis = self.tts_client.synthesize(
            text,
            instructions=(
                f"Speak as a realistic patient. Tone: {self.scenario.patient.tone}. "
                "Keep the delivery concise and natural."
            ),
        )
        if self.stream_sid is None:
            raise RuntimeError("Cannot send audio before the Twilio stream is ready.")

        payload = base64.b64encode(synthesis.mulaw_bytes).decode("ascii")
        await websocket.send_json(
            {"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}}
        )
        mark_name = f"{self.call_id}-{len(self.transcript_segments)}"
        await websocket.send_json(
            {"event": "mark", "streamSid": self.stream_sid, "mark": {"name": mark_name}}
        )
        self.interruption.register_outbound_audio(mark_name)
        self._append_segment(
            speaker="PATIENT",
            text=text,
            start_seconds=timestamp_start,
            end_seconds=timestamp_start + (synthesis.duration_ms / 1000),
            interrupted=interrupted,
            latency=LatencySnapshot(
                model_response_generated_ms=synthesis.latency_ms,
                speech_playback_started_ms=synthesis.latency_ms,
            ),
        )

    def _append_segment(
        self,
        *,
        speaker: str,
        text: str,
        start_seconds: float,
        end_seconds: float,
        latency: LatencySnapshot,
        interrupted: bool = False,
    ) -> None:
        self.state.append_turn(
            ConversationTurn(
                speaker=speaker,  # type: ignore[arg-type]
                text=text,
                start_timestamp=start_seconds,
                end_timestamp=end_seconds,
                interruption_status=interrupted,
                latency=latency,
            )
        )
        self.transcript_segments.append(
            TranscriptSegment(
                speaker=speaker,  # type: ignore[arg-type]
                start_timestamp=start_seconds,
                end_timestamp=end_seconds,
                text=text,
                interruption_status=interrupted,
                latency_metadata=latency.model_dump(),
            )
        )

    def _finalize(self) -> None:
        if not self.transcript_segments:
            return
        duration_seconds = self.transcript_segments[-1].end_timestamp
        transcript = TranscriptDocument(
            call_id=self.call_id,
            scenario_id=self.scenario.id,
            created_on=self.started_at.date(),
            duration_seconds=duration_seconds,
            segments=self.transcript_segments,
        )
        metadata = CallMetadata(
            call_id=self.call_id,
            scenario_id=self.scenario.id,
            destination_number=self.settings.authorized_destination,
            originating_number_masked=None,
            start_time=self.started_at,
            end_time=datetime.now(UTC),
            duration_seconds=duration_seconds,
            call_status="completed",
            mode="live",
            transcript_path=f"artifacts/transcripts/{self.call_id}.txt",
            estimated_cost_usd=self.settings.expected_cost_per_call_usd,
            model_names={
                "llm": self.settings.llm_model,
                "stt": self.settings.stt_model,
                "tts": self.settings.tts_model,
            },
            average_response_latency_ms=self._average_latency_ms(),
            termination_reason=self.state.termination_reason,
            analysis_completion_status="pending",
        )
        self.artifact_store.write_transcript(transcript)
        self.artifact_store.write_metadata(metadata)

    def _average_latency_ms(self) -> float | None:
        values: list[float] = []
        for segment in self.transcript_segments:
            for value in segment.latency_metadata.values():
                if value is not None:
                    values.append(value)
        if not values:
            return None
        return sum(values) / len(values)

