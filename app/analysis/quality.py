from __future__ import annotations

import statistics
import wave
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.transcript import TranscriptDocument
from app.analysis.validation import TranscriptValidationReport
from app.storage.artifacts import ArtifactPaths
from app.storage.metadata import CallMetadata


class HumanVoiceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str | None = None
    review_date: date | None = None
    naturalness: int | None = Field(default=None, ge=1, le=5)
    clarity: int | None = Field(default=None, ge=1, le=5)
    pacing: int | None = Field(default=None, ge=1, le=5)
    persona_consistency: int | None = Field(default=None, ge=1, le=5)
    turn_taking: int | None = Field(default=None, ge=1, le=5)
    scenario_completion: int | None = Field(default=None, ge=1, le=5)
    audio_quality: int | None = Field(default=None, ge=1, le=5)
    transcript_quality: int | None = Field(default=None, ge=1, le=5)
    bug_evidence: int | None = Field(default=None, ge=1, le=5)
    played_from_beginning_to_end: bool | None = None
    both_speakers_audible: bool | None = None
    conversation_coherent: bool | None = None
    patient_sounds_natural: bool | None = None
    turn_taking_sensible: bool | None = None
    no_major_audio_glitches: bool | None = None
    no_excessive_delay: bool | None = None
    scenario_objective_pursued: bool | None = None
    final_outcome_clear: bool | None = None
    approved_for_submission: bool | None = None
    reviewer_notes: str | None = None

    def is_completed(self) -> bool:
        checklist_values = (
            self.played_from_beginning_to_end,
            self.both_speakers_audible,
            self.conversation_coherent,
            self.patient_sounds_natural,
            self.turn_taking_sensible,
            self.no_major_audio_glitches,
            self.no_excessive_delay,
            self.scenario_objective_pursued,
            self.final_outcome_clear,
            self.approved_for_submission,
        )
        score_values = (
            self.naturalness,
            self.clarity,
            self.pacing,
            self.persona_consistency,
            self.turn_taking,
            self.scenario_completion,
            self.audio_quality,
            self.transcript_quality,
            self.bug_evidence,
        )
        return (
            self.reviewer is not None
            and self.review_date is not None
            and self.reviewer_notes is not None
            and all(value is not None for value in checklist_values)
            and all(value is not None for value in score_values)
        )


class VoiceQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    overall_score: int = Field(ge=0, le=100)
    metrics: dict[str, int | float | bool]
    human_review: HumanVoiceReview = Field(default_factory=HumanVoiceReview)

    def render_markdown(self) -> str:
        lines = [
            f"# Voice Quality: {self.call_id}",
            "",
            f"- Overall score: `{self.overall_score}`",
            "",
            "## Metrics",
            "",
        ]
        for key, value in self.metrics.items():
            lines.append(f"- {key}: `{value}`")
        lines.extend(["", "## Human Review", ""])
        human = self.human_review.model_dump()
        for key, value in human.items():
            lines.append(f"- {key}: `{value}`")
        return "\n".join(lines).rstrip() + "\n"


class VoiceQualityAnalyzer:
    def build_report(
        self,
        transcript: TranscriptDocument,
        metadata: CallMetadata,
        validation: TranscriptValidationReport,
        paths: ArtifactPaths,
    ) -> VoiceQualityReport:
        response_latencies_ms = self._response_latencies_ms(transcript)
        silence_durations_ms = self._silence_durations_ms(transcript)
        stt_latencies_ms = self._latency_values(transcript, "stt_latency_ms")
        llm_latencies_ms = self._latency_values(transcript, "llm_latency_ms")
        tts_latencies_ms = self._latency_values(transcript, "tts_latency_ms")
        total_turn_latencies_ms = self._latency_values(transcript, "total_response_latency_ms")
        overlap_duration_ms = sum(segment.overlap_duration_ms for segment in transcript.segments)
        successful_barge_ins = sum(
            1
            for segment in transcript.segments
            if segment.speaker == "PATIENT" and segment.action == "interrupt_politely" and segment.overlap_duration_ms > 0
        )
        accidental_interruptions = sum(
            1
            for segment in transcript.segments
            if segment.speaker == "PATIENT" and segment.overlap_duration_ms > 0 and segment.action != "interrupt_politely"
        )
        repeated_phrases = self._repeated_phrases(transcript)
        unfinished_utterances = self._unfinished_utterances(transcript)
        robotic_or_long_responses = self._robotic_or_long_responses(transcript)
        clipping_events = self._audio_clipping_events(paths)

        metrics: dict[str, int | float | bool] = {
            "average_response_latency_ms": round(_average(response_latencies_ms), 1),
            "p50_response_latency_ms": round(_percentile(response_latencies_ms, 50), 1),
            "p95_response_latency_ms": round(_percentile(response_latencies_ms, 95), 1),
            "max_response_latency_ms": round(max(response_latencies_ms, default=0), 1),
            "average_silence_ms": round(_average(silence_durations_ms), 1),
            "longest_silence_ms": round(max(silence_durations_ms, default=0), 1),
            "average_stt_latency_ms": round(_average(stt_latencies_ms), 1),
            "average_llm_latency_ms": round(_average(llm_latencies_ms), 1),
            "average_tts_latency_ms": round(_average(tts_latencies_ms), 1),
            "average_total_turn_latency_ms": round(_average(total_turn_latencies_ms), 1),
            "turn_count": len(transcript.segments),
            "patient_turn_count": sum(1 for segment in transcript.segments if segment.speaker == "PATIENT"),
            "agent_turn_count": sum(1 for segment in transcript.segments if segment.speaker == "AGENT"),
            "accidental_interruptions": accidental_interruptions,
            "successful_barge_ins": successful_barge_ins,
            "overlap_duration_ms": overlap_duration_ms,
            "max_overlap_duration_ms": max(
                (segment.overlap_duration_ms for segment in transcript.segments),
                default=0,
            ),
            "repeated_phrases": repeated_phrases,
            "unfinished_utterances": unfinished_utterances,
            "robotic_or_long_responses": robotic_or_long_responses,
            "call_completion": metadata.call_status == "completed",
            "audio_clipping_events": clipping_events,
            "transcript_confidence": round(validation.average_confidence, 3),
            "validation_passed": validation.passed,
        }

        score = 100
        score -= min(25, int(_average(response_latencies_ms) / 120))
        score -= min(18, int(max(silence_durations_ms, default=0) / 250))
        score -= accidental_interruptions * 8
        score -= robotic_or_long_responses * 4
        score -= repeated_phrases * 3
        score -= unfinished_utterances * 2
        score -= clipping_events * 5
        if not validation.passed:
            score -= 20
        overall_score = max(0, min(100, score))
        return VoiceQualityReport(
            call_id=transcript.call_id,
            overall_score=overall_score,
            metrics=metrics,
        )

    def _response_latencies_ms(self, transcript: TranscriptDocument) -> list[float]:
        latencies: list[float] = []
        previous_agent_end: float | None = None
        for segment in transcript.segments:
            if segment.speaker == "AGENT":
                previous_agent_end = segment.end_timestamp
            elif segment.speaker == "PATIENT" and previous_agent_end is not None:
                latencies.append(max(0.0, (segment.start_timestamp - previous_agent_end) * 1000))
                previous_agent_end = None
        return latencies

    def _silence_durations_ms(self, transcript: TranscriptDocument) -> list[float]:
        silences: list[float] = []
        for previous, current in zip(transcript.segments, transcript.segments[1:]):
            silence_ms = max(0.0, (current.start_timestamp - previous.end_timestamp) * 1000)
            silences.append(silence_ms)
        return silences

    def _latency_values(self, transcript: TranscriptDocument, key: str) -> list[float]:
        values: list[float] = []
        for segment in transcript.segments:
            value = segment.latency_metadata.get(key)
            if value is not None:
                values.append(float(value))
        return values

    def _repeated_phrases(self, transcript: TranscriptDocument) -> int:
        seen: dict[str, int] = {}
        repeats = 0
        for segment in transcript.segments:
            if segment.speaker != "PATIENT":
                continue
            normalized = " ".join(segment.text.lower().split())
            seen[normalized] = seen.get(normalized, 0) + 1
            if seen[normalized] > 1:
                repeats += 1
        return repeats

    def _unfinished_utterances(self, transcript: TranscriptDocument) -> int:
        unfinished = 0
        for segment in transcript.segments:
            if segment.speaker != "PATIENT":
                continue
            if segment.text.endswith("...") or segment.text.rstrip()[-1:] not in {".", "?", "!"}:
                unfinished += 1
        return unfinished

    def _robotic_or_long_responses(self, transcript: TranscriptDocument) -> int:
        count = 0
        for segment in transcript.segments:
            if segment.speaker != "PATIENT":
                continue
            words = len(segment.text.split())
            sentence_count = max(1, segment.text.count(".") + segment.text.count("?") + segment.text.count("!"))
            if words > 18 or sentence_count > 2:
                count += 1
        return count

    def _audio_clipping_events(self, paths: ArtifactPaths) -> int:
        clipping = 0
        for track in (paths.patient_recording, paths.agent_recording):
            if not track.exists() or track.suffix.lower() != ".wav":
                continue
            with wave.open(str(track), "rb") as wav_file:
                pcm = wav_file.readframes(wav_file.getnframes())
            for index in range(0, len(pcm), 2):
                sample = int.from_bytes(pcm[index : index + 2], "little", signed=True)
                if abs(sample) >= 32000:
                    clipping += 1
                    break
        return clipping


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return statistics.mean(values)


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(round((percentile / 100) * (len(sorted_values) - 1)))
    return sorted_values[index]
