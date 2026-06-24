from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import WebSocket

from app.agent.patient_agent import OpenAITextGenerationClient, PatientAgent, PatientReply
from app.agent.scenario_loader import Scenario, load_scenarios
from app.agent.state import ConversationState, ConversationTurn, LatencySnapshot
from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.config import AppSettings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata
from app.voice.audio import (
    TimedPcmSegment,
    chunk_mulaw_audio,
    duration_ms_from_mulaw,
    mix_pcm16_tracks,
    mulaw_to_pcm16,
    pcm16_to_wav_bytes,
    render_timed_pcm_track,
    wav_bytes_to_pcm16,
)
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
            max_end_of_turn_silence_ms=settings.max_end_of_turn_silence_ms,
        )
        self.interruption = InterruptionController()
        self.transcript_segments: list[TranscriptSegment] = []
        self.agent_audio_segments: list[TimedPcmSegment] = []
        self.patient_audio_segments: list[TimedPcmSegment] = []
        self.playback_task: asyncio.Task[None] | None = None
        self.pending_interrupt_reply = False
        self.last_interrupt_started_ms: int | None = None
        self.llm_client = (
            OpenAITextGenerationClient(settings.llm_api_key, settings.llm_model)
            if settings.llm_api_key
            else None
        )
        if not settings.stt_api_key or not settings.tts_api_key:
            raise RuntimeError("STT_API_KEY and TTS_API_KEY are required for live calls.")
        self.patient_agent = PatientAgent(
            scenario,
            self.state,
            self.llm_client,
            response_style="concise",
        )
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
            await self._queue_patient_audio(
                websocket,
                text=self.patient_agent.opening_line(),
                timestamp_start=0.0,
                action=self.state.action_history[-1] if self.state.action_history else None,
                progress=self.state.last_goal_progress,
                reason="initial scenario opening",
            )
            return

        if event_type == "media":
            media = payload["media"]
            timestamp_ms = int(media.get("timestamp", 0))
            decoded_mulaw = base64.b64decode(media["payload"])
            self.agent_audio_segments.append(
                TimedPcmSegment(start_ms=timestamp_ms, pcm_bytes=mulaw_to_pcm16(decoded_mulaw))
            )
            event = self.turn_manager.ingest_mulaw_frame(decoded_mulaw, timestamp_ms)

            if event.speech_started and self._playback_is_active():
                self.state.record_barge_in(successful=False)
                await websocket.send_json({"event": "clear", "streamSid": self.stream_sid})
                self.interruption.clear()
                await self._cancel_playback()

            unsolicited_interrupt = self.patient_agent.maybe_interrupt_ongoing_agent_turn(
                event.speech_ongoing_ms
            )
            if (
                unsolicited_interrupt is not None
                and not self._playback_is_active()
                and not self.pending_interrupt_reply
            ):
                self.pending_interrupt_reply = True
                self.last_interrupt_started_ms = timestamp_ms
                overlap_ms = min(900, event.speech_ongoing_ms)
                self.state.record_barge_in(successful=True, overlap_duration_ms=overlap_ms)
                await self._queue_patient_audio(
                    websocket,
                    text=unsolicited_interrupt.text,
                    timestamp_start=timestamp_ms / 1000,
                    interrupted=bool(unsolicited_interrupt.correction),
                    action=unsolicited_interrupt.action,
                    progress=unsolicited_interrupt.scenario_goal_progress,
                    reason=unsolicited_interrupt.reason,
                    allow_overlap=True,
                    overlap_duration_ms=overlap_ms,
                )

            if event.completed_turn is not None:
                await self._process_completed_turn(websocket, event.completed_turn)
            return

        if event_type == "mark":
            self.interruption.acknowledge_mark(payload["mark"]["name"])
            return

        if event_type == "stop":
            tail = self.turn_manager.force_flush(int(payload.get("sequenceNumber", 0)) * 20)
            if tail is not None:
                await self._process_completed_turn(websocket, tail)
            await self._cancel_playback()
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
            confidence=transcription.confidence or 0.78,
            channel="agent",
            speaker_source="channel",
        )

        if self.pending_interrupt_reply:
            self.pending_interrupt_reply = False
            self.last_interrupt_started_ms = None
            return

        reply = self.patient_agent.reply_to_agent(transcription.text)
        for key, value in reply.disclosed_facts.items():
            self.state.disclose_fact(key, value)

        await self._queue_patient_audio(
            websocket,
            text=reply.text,
            timestamp_start=turn.end_timestamp_ms / 1000,
            interrupted=bool(reply.correction),
            action=reply.action,
            progress=reply.scenario_goal_progress,
            reason=reply.reason,
            allow_overlap=reply.allow_overlap,
        )
        if reply.should_end_call:
            self.state.mark_complete("goal_reached")

    async def _queue_patient_audio(
        self,
        websocket: WebSocket,
        *,
        text: str,
        timestamp_start: float,
        action: str | None,
        progress: float | None,
        reason: str,
        interrupted: bool = False,
        allow_overlap: bool = False,
        overlap_duration_ms: int = 0,
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

        patient_pcm = wav_bytes_to_pcm16(synthesis.wav_bytes)
        audio_index = len(self.patient_audio_segments)
        self.patient_audio_segments.append(
            TimedPcmSegment(start_ms=int(timestamp_start * 1000), pcm_bytes=patient_pcm)
        )

        segment_index = self._append_segment(
            speaker="PATIENT",
            text=text,
            start_seconds=timestamp_start,
            end_seconds=timestamp_start + (synthesis.duration_ms / 1000),
            interrupted=interrupted or allow_overlap,
            latency=LatencySnapshot(
                model_response_generated_ms=synthesis.latency_ms,
                speech_playback_started_ms=synthesis.latency_ms,
            ),
            action=action,
            progress=progress,
            channel="patient",
            speaker_source="tts",
            overlap_duration_ms=overlap_duration_ms,
            confidence=1.0,
        )

        if self._playback_is_active():
            await self._cancel_playback()

        mark_name = f"{self.call_id}-{segment_index}"
        self.interruption.register_outbound_audio(mark_name)
        self.playback_task = asyncio.create_task(
            self._stream_patient_audio(
                websocket=websocket,
                mulaw_bytes=synthesis.mulaw_bytes,
                mark_name=mark_name,
                transcript_segment_index=segment_index,
                audio_segment_index=audio_index,
                start_seconds=timestamp_start,
            )
        )

    async def _stream_patient_audio(
        self,
        *,
        websocket: WebSocket,
        mulaw_bytes: bytes,
        mark_name: str,
        transcript_segment_index: int,
        audio_segment_index: int,
        start_seconds: float,
    ) -> None:
        sent_bytes = bytearray()
        try:
            for chunk in chunk_mulaw_audio(mulaw_bytes):
                payload = base64.b64encode(chunk).decode("ascii")
                await websocket.send_json(
                    {"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}}
                )
                sent_bytes.extend(chunk)
                await asyncio.sleep(max(0.02, len(chunk) / 8000))

            await websocket.send_json(
                {"event": "mark", "streamSid": self.stream_sid, "mark": {"name": mark_name}}
            )
        except asyncio.CancelledError:
            actual_duration_ms = duration_ms_from_mulaw(bytes(sent_bytes))
            self._truncate_patient_segment(
                transcript_segment_index=transcript_segment_index,
                audio_segment_index=audio_segment_index,
                start_seconds=start_seconds,
                actual_duration_ms=actual_duration_ms,
            )
            raise
        finally:
            self.playback_task = None

    async def _cancel_playback(self) -> None:
        if self.playback_task is None:
            return
        self.playback_task.cancel()
        try:
            await self.playback_task
        except asyncio.CancelledError:
            pass
        self.playback_task = None

    def _truncate_patient_segment(
        self,
        *,
        transcript_segment_index: int,
        audio_segment_index: int,
        start_seconds: float,
        actual_duration_ms: int,
    ) -> None:
        end_seconds = start_seconds + (actual_duration_ms / 1000)
        if transcript_segment_index < len(self.transcript_segments):
            self.transcript_segments[transcript_segment_index].end_timestamp = end_seconds
        patient_turns = [turn for turn in self.state.conversation if turn.speaker == "PATIENT"]
        if patient_turns:
            patient_turns[-1].end_timestamp = end_seconds
        if audio_segment_index < len(self.patient_audio_segments):
            pcm_length = int(actual_duration_ms * 16)
            original = self.patient_audio_segments[audio_segment_index]
            self.patient_audio_segments[audio_segment_index] = TimedPcmSegment(
                start_ms=original.start_ms,
                pcm_bytes=original.pcm_bytes[:pcm_length],
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
        action: str | None = None,
        progress: float | None = None,
        channel: str | None = None,
        speaker_source: str = "simulator",
        overlap_duration_ms: int = 0,
        confidence: float | None = None,
    ) -> int:
        self.state.append_turn(
            ConversationTurn(
                speaker=speaker,  # type: ignore[arg-type]
                text=text,
                start_timestamp=start_seconds,
                end_timestamp=end_seconds,
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
        self.transcript_segments.append(
            TranscriptSegment(
                speaker=speaker,  # type: ignore[arg-type]
                start_timestamp=start_seconds,
                end_timestamp=end_seconds,
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
        return len(self.transcript_segments) - 1

    def _finalize(self) -> None:
        if not self.transcript_segments:
            return

        duration_seconds = max(segment.end_timestamp for segment in self.transcript_segments)
        transcript = TranscriptDocument(
            call_id=self.call_id,
            scenario_id=self.scenario.id,
            created_on=self.started_at.date(),
            duration_seconds=duration_seconds,
            segments=sorted(self.transcript_segments, key=lambda segment: segment.start_timestamp),
        )

        paths = self.artifact_store.paths_for(self.call_id)
        duration_ms = int(duration_seconds * 1000)
        patient_track_pcm = render_timed_pcm_track(
            self.patient_audio_segments,
            minimum_duration_ms=duration_ms,
        )
        agent_track_pcm = render_timed_pcm_track(
            self.agent_audio_segments,
            minimum_duration_ms=duration_ms,
        )
        mixed_track_pcm = mix_pcm16_tracks(patient_track_pcm, agent_track_pcm)

        paths.patient_recording.write_bytes(pcm16_to_wav_bytes(patient_track_pcm))
        paths.agent_recording.write_bytes(pcm16_to_wav_bytes(agent_track_pcm))
        mixed_wav_path = paths.mixed_recording.with_suffix(".wav")
        mixed_wav_path.write_bytes(pcm16_to_wav_bytes(mixed_track_pcm))
        self.artifact_store.convert_audio(mixed_wav_path, paths.mixed_recording)
        mixed_wav_path.unlink(missing_ok=True)

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
            recording_path=f"artifacts/recordings/{paths.mixed_recording.name}",
            patient_recording_path=f"artifacts/recordings/{paths.patient_recording.name}",
            agent_recording_path=f"artifacts/recordings/{paths.agent_recording.name}",
            mixed_recording_path=f"artifacts/recordings/{paths.mixed_recording.name}",
            transcript_path=f"artifacts/transcripts/{self.call_id}.txt",
            estimated_cost_usd=self.settings.expected_cost_per_call_usd,
            model_names={
                "llm": self.settings.llm_model,
                "stt": self.settings.stt_model,
                "tts": self.settings.tts_model,
            },
            average_response_latency_ms=self._average_latency_ms(),
            average_transcript_confidence=self._average_confidence(),
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

    def _average_confidence(self) -> float | None:
        confidences = [
            segment.confidence
            for segment in self.transcript_segments
            if segment.confidence is not None
        ]
        if not confidences:
            return None
        return sum(confidences) / len(confidences)

    def _playback_is_active(self) -> bool:
        return self.playback_task is not None and not self.playback_task.done()
