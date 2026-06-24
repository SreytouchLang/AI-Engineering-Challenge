from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.transcript import TranscriptDocument
from app.safety import find_secret_like_values
from app.storage.artifacts import ArtifactPaths
from app.storage.metadata import CallMetadata
from app.voice.audio import audio_duration_seconds


class TranscriptValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    message: str


class TranscriptValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    scenario_id: str
    passed: bool
    average_confidence: float
    minimum_confidence: float
    checks: dict[str, bool]
    metrics: dict[str, float | int]
    issues: list[TranscriptValidationIssue] = Field(default_factory=list)

    def render_markdown(self) -> str:
        lines = [
            f"# Transcript Validation: {self.call_id}",
            "",
            f"- Scenario: `{self.scenario_id}`",
            f"- Passed: `{self.passed}`",
            f"- Average confidence: `{self.average_confidence:.2f}`",
            f"- Minimum confidence: `{self.minimum_confidence:.2f}`",
            "",
            "## Checks",
            "",
        ]
        for key, value in self.checks.items():
            lines.append(f"- {key}: `{value}`")
        lines.extend(["", "## Issues", ""])
        if not self.issues:
            lines.append("- No validation issues detected.")
        else:
            for issue in self.issues:
                lines.append(f"- `{issue.code}` ({issue.severity}): {issue.message}")
        return "\n".join(lines).rstrip() + "\n"


class TranscriptValidator:
    def __init__(
        self,
        *,
        gap_threshold_ms: int,
        confidence_threshold: float,
        duration_tolerance_seconds: float,
    ) -> None:
        self.gap_threshold_ms = gap_threshold_ms
        self.confidence_threshold = confidence_threshold
        self.duration_tolerance_seconds = duration_tolerance_seconds

    def validate(
        self,
        transcript: TranscriptDocument,
        metadata: CallMetadata,
        paths: ArtifactPaths,
    ) -> TranscriptValidationReport:
        issues: list[TranscriptValidationIssue] = []
        segments = sorted(transcript.segments, key=lambda segment: segment.start_timestamp)

        both_speakers_present = {
            "PATIENT",
            "AGENT",
        } <= {segment.speaker for segment in segments}
        monotonic_timestamps = all(later.start_timestamp >= earlier.start_timestamp for earlier, later in zip(segments, segments[1:]))
        average_confidence = self._average_confidence(segments)
        minimum_confidence = min((segment.confidence if segment.confidence is not None else 1.0) for segment in segments)
        duration_match, audio_duration_seconds = self._duration_match(
            transcript=transcript,
            metadata=metadata,
            paths=paths,
        )
        unexplained_gap_count = self._gap_count(segments)
        channel_consistency = self._channel_consistency(segments)
        overlap_preserved = self._overlap_preserved(segments)
        corrections_reflected = self._corrections_reflected(segments)
        starts_near_call_start = bool(segments) and segments[0].start_timestamp <= 5.0
        no_placeholder_text = self._no_placeholder_text(segments)
        no_secret_like_content = self._no_secret_like_content(segments)

        if not both_speakers_present:
            issues.append(
                TranscriptValidationIssue(
                    code="both_speakers_missing",
                    severity="high",
                    message="Transcript does not include both PATIENT and AGENT turns.",
                )
            )
        if not monotonic_timestamps:
            issues.append(
                TranscriptValidationIssue(
                    code="non_monotonic_timestamps",
                    severity="high",
                    message="Transcript segment start timestamps are out of order.",
                )
            )
        if average_confidence < self.confidence_threshold:
            issues.append(
                TranscriptValidationIssue(
                    code="low_confidence",
                    severity="high",
                    message=(
                        f"Average transcript confidence {average_confidence:.2f} is below the threshold of {self.confidence_threshold:.2f}."
                    ),
                )
            )
        if not duration_match:
            issues.append(
                TranscriptValidationIssue(
                    code="duration_mismatch",
                    severity="medium",
                    message=(
                        f"Transcript duration {transcript.duration_seconds:.2f}s does not closely match "
                        f"audio duration {audio_duration_seconds:.2f}s."
                    ),
                )
            )
        if unexplained_gap_count:
            issues.append(
                TranscriptValidationIssue(
                    code="transcript_gaps",
                    severity="medium",
                    message=f"Detected {unexplained_gap_count} unexplained transcript gap(s).",
                )
            )
        if not channel_consistency:
            issues.append(
                TranscriptValidationIssue(
                    code="speaker_channel_mismatch",
                    severity="high",
                    message="At least one transcript segment's speaker does not match its primary channel.",
                )
            )
        if not overlap_preserved:
            issues.append(
                TranscriptValidationIssue(
                    code="missing_overlap_metadata",
                    severity="medium",
                    message="Transcript contains overlapping turns without overlap metadata.",
                )
            )
        if not corrections_reflected:
            issues.append(
                TranscriptValidationIssue(
                    code="correction_not_retained",
                    severity="medium",
                    message="A corrected fact appears to be contradicted later in the transcript.",
                )
            )
        if not starts_near_call_start:
            issues.append(
                TranscriptValidationIssue(
                    code="late_transcript_start",
                    severity="medium",
                    message="Transcript does not begin near the start of the call.",
                )
            )
        if not no_placeholder_text:
            issues.append(
                TranscriptValidationIssue(
                    code="placeholder_text_detected",
                    severity="high",
                    message="Transcript contains placeholder or undecoded text.",
                )
            )
        if not no_secret_like_content:
            issues.append(
                TranscriptValidationIssue(
                    code="secret_like_content_detected",
                    severity="high",
                    message="Transcript contains content that resembles a credential or token.",
                )
            )

        checks = {
            "both_speakers_present": both_speakers_present,
            "monotonic_timestamps": monotonic_timestamps,
            "duration_matches_audio": duration_match,
            "no_large_unexplained_gaps": unexplained_gap_count == 0,
            "speaker_channels_consistent": channel_consistency,
            "overlap_preserved": overlap_preserved,
            "corrections_reflected": corrections_reflected,
            "confidence_threshold_met": average_confidence >= self.confidence_threshold,
            "starts_near_call_start": starts_near_call_start,
            "no_placeholder_text": no_placeholder_text,
            "no_secret_like_content": no_secret_like_content,
        }
        metrics = {
            "transcript_duration_seconds": round(transcript.duration_seconds, 2),
            "audio_duration_seconds": round(audio_duration_seconds, 2),
            "gap_count": unexplained_gap_count,
            "segment_count": len(segments),
        }
        passed = all(checks.values())
        return TranscriptValidationReport(
            call_id=transcript.call_id,
            scenario_id=transcript.scenario_id,
            passed=passed,
            average_confidence=round(average_confidence, 3),
            minimum_confidence=round(minimum_confidence, 3),
            checks=checks,
            metrics=metrics,
            issues=issues,
        )

    def _average_confidence(self, segments) -> float:
        confidences = [segment.confidence if segment.confidence is not None else 1.0 for segment in segments]
        return sum(confidences) / max(1, len(confidences))

    def _duration_match(
        self,
        *,
        transcript: TranscriptDocument,
        metadata: CallMetadata,
        paths: ArtifactPaths,
    ) -> tuple[bool, float]:
        candidate_paths: list[Path] = []
        if metadata.mixed_recording_path:
            candidate_paths.append(paths.mixed_recording)
        if metadata.recording_path:
            candidate_paths.append(paths.recording)
        if paths.mixed_recording.exists():
            candidate_paths.append(paths.mixed_recording)
        if paths.patient_recording.exists():
            candidate_paths.append(paths.patient_recording)

        detected_audio_duration_seconds = transcript.duration_seconds
        for candidate in candidate_paths:
            if not candidate.exists():
                continue
            detected_audio_duration_seconds = audio_duration_seconds(candidate)
            break

        duration_delta = abs(detected_audio_duration_seconds - transcript.duration_seconds)
        return duration_delta <= self.duration_tolerance_seconds, detected_audio_duration_seconds

    def _gap_count(self, segments) -> int:
        gap_count = 0
        for previous, current in zip(segments, segments[1:]):
            gap_ms = int((current.start_timestamp - previous.end_timestamp) * 1000)
            if gap_ms > self.gap_threshold_ms:
                gap_count += 1
        return gap_count

    def _channel_consistency(self, segments) -> bool:
        for segment in segments:
            if segment.channel is None:
                continue
            if segment.speaker == "PATIENT" and segment.channel != "patient":
                return False
            if segment.speaker == "AGENT" and segment.channel != "agent":
                return False
        return True

    def _overlap_preserved(self, segments) -> bool:
        for previous, current in zip(segments, segments[1:]):
            if current.start_timestamp < previous.end_timestamp and current.overlap_duration_ms <= 0:
                return False
        return True

    def _corrections_reflected(self, segments) -> bool:
        wrong_name_pattern = re.compile(r"not ([A-Za-z]+)", re.IGNORECASE)
        wrong_day_pattern = re.compile(r"meant ([A-Za-z]+)", re.IGNORECASE)
        known_wrong_tokens: set[str] = set()
        for segment in segments:
            if segment.speaker == "PATIENT":
                if segment.action == "correct_agent":
                    name_match = wrong_name_pattern.search(segment.text)
                    if name_match:
                        known_wrong_tokens.add(name_match.group(1).lower())
                    day_match = wrong_day_pattern.search(segment.text)
                    if day_match:
                        for token in known_wrong_tokens:
                            if token in segment.text.lower():
                                continue
                        continue
            elif segment.speaker == "AGENT":
                lowered = segment.text.lower()
                if any(token in lowered for token in known_wrong_tokens):
                    return False
        return True

    def _no_placeholder_text(self, segments) -> bool:
        placeholders = ("tbd", "placeholder", "[inaudible]", "lorem ipsum")
        for segment in segments:
            lowered = segment.text.lower()
            if any(token in lowered for token in placeholders):
                return False
        return True

    def _no_secret_like_content(self, segments) -> bool:
        combined = "\n".join(segment.text for segment in segments)
        return not find_secret_like_values(combined)
