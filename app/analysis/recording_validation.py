from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.transcript import TranscriptDocument
from app.storage.artifacts import ArtifactPaths
from app.storage.metadata import CallMetadata


class RecordingValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    message: str


class RecordingValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    passed: bool
    checks: dict[str, bool]
    metrics: dict[str, float | int | str]
    issues: list[RecordingValidationIssue] = Field(default_factory=list)

    def render_markdown(self) -> str:
        lines = [f"## {self.call_id}", ""]
        for name, value in self.checks.items():
            lines.append(f"- {name}: `{value}`")
        lines.extend(["", "Metrics:"])
        for name, value in self.metrics.items():
            lines.append(f"- {name}: `{value}`")
        lines.extend(["", "Issues:"])
        if not self.issues:
            lines.append("- None")
        else:
            for issue in self.issues:
                lines.append(f"- `{issue.code}` ({issue.severity}): {issue.message}")
        return "\n".join(lines).rstrip() + "\n"


class RecordingValidator:
    def __init__(
        self,
        *,
        duration_tolerance_seconds: float = 2.5,
        silence_window_ms: int = 500,
        long_silence_threshold_ms: int = 4000,
    ) -> None:
        self.duration_tolerance_seconds = duration_tolerance_seconds
        self.silence_window_ms = silence_window_ms
        self.long_silence_threshold_ms = long_silence_threshold_ms

    def validate(
        self,
        *,
        metadata: CallMetadata,
        paths: ArtifactPaths,
        transcript: TranscriptDocument | None = None,
    ) -> RecordingValidationReport:
        issues: list[RecordingValidationIssue] = []
        mixed_path = self._select_mixed_recording(paths)

        exists = mixed_path is not None and mixed_path.exists()
        supported_format = exists and mixed_path.suffix.lower() in {".mp3", ".ogg"}
        nonzero_size = exists and mixed_path.stat().st_size > 0
        decodable = False
        duration_seconds = 0.0
        if exists and supported_format and nonzero_size:
            try:
                duration_seconds = self._duration_seconds(mixed_path)
                decodable = duration_seconds > 0
            except Exception:
                decodable = False

        patient_audible = paths.patient_recording.exists() and self._has_audio_energy(
            paths.patient_recording
        )
        agent_audible = paths.agent_recording.exists() and self._has_audio_energy(
            paths.agent_recording
        )
        both_speakers_audible = patient_audible and agent_audible
        mixed_not_silent = exists and self._has_audio_energy(mixed_path) if exists else False
        clipping_events = self._clipping_events(mixed_path) if exists else 0
        longest_silence_ms = self._longest_silence_ms(mixed_path) if exists else 0
        duration_matches_metadata = (
            metadata.duration_seconds is not None
            and abs(metadata.duration_seconds - duration_seconds) <= self.duration_tolerance_seconds
            if decodable
            else False
        )
        transcript_matches_audio = (
            transcript is not None
            and abs(transcript.duration_seconds - duration_seconds) <= self.duration_tolerance_seconds
            if decodable
            else False
        )

        checks = {
            "recording_exists": bool(exists),
            "supported_public_format": bool(supported_format),
            "nonzero_size": bool(nonzero_size),
            "decoder_can_open": bool(decodable),
            "both_speakers_audible": both_speakers_audible,
            "audio_not_silent": mixed_not_silent,
            "no_excessive_clipping": clipping_events <= 1,
            "no_long_unexplained_silence": longest_silence_ms <= self.long_silence_threshold_ms,
            "duration_matches_metadata": duration_matches_metadata,
            "duration_matches_transcript": transcript_matches_audio if transcript is not None else True,
        }

        if not checks["recording_exists"]:
            issues.append(self._issue("recording_missing", "high", "Mixed MP3/OGG recording is missing."))
        if exists and not checks["supported_public_format"]:
            issues.append(self._issue("bad_public_format", "high", "Mixed recording must be MP3 or OGG."))
        if exists and not checks["nonzero_size"]:
            issues.append(self._issue("empty_recording", "high", "Recording file size is zero."))
        if exists and not checks["decoder_can_open"]:
            issues.append(self._issue("decode_failed", "high", "Recording could not be decoded."))
        if exists and not checks["both_speakers_audible"]:
            issues.append(
                self._issue(
                    "missing_speaker_audio",
                    "high",
                    "Separate patient and agent channel artifacts do not both contain audible speech.",
                )
            )
        if exists and not checks["audio_not_silent"]:
            issues.append(self._issue("silent_recording", "high", "Recording appears to be silent."))
        if exists and not checks["no_excessive_clipping"]:
            issues.append(self._issue("clipping_detected", "medium", "Recording contains clipping artifacts."))
        if exists and not checks["no_long_unexplained_silence"]:
            issues.append(
                self._issue(
                    "long_silence",
                    "medium",
                    "Recording contains a long unexplained silence interval.",
                )
            )
        if exists and not checks["duration_matches_metadata"]:
            issues.append(
                self._issue(
                    "metadata_duration_mismatch",
                    "medium",
                    "Recording duration does not align with call metadata.",
                )
            )
        if transcript is not None and exists and not checks["duration_matches_transcript"]:
            issues.append(
                self._issue(
                    "transcript_duration_mismatch",
                    "medium",
                    "Recording duration does not align with the transcript duration.",
                )
            )

        return RecordingValidationReport(
            call_id=metadata.call_id,
            passed=all(checks.values()),
            checks=checks,
            metrics={
                "mixed_recording": mixed_path.name if mixed_path is not None else "missing",
                "duration_seconds": round(duration_seconds, 2),
                "clipping_events": clipping_events,
                "longest_silence_ms": longest_silence_ms,
            },
            issues=issues,
        )

    def _select_mixed_recording(self, paths: ArtifactPaths) -> Path | None:
        for candidate in (paths.mixed_recording, paths.recording):
            if candidate.exists():
                return candidate
        for suffix in (".mp3", ".ogg", ".wav"):
            candidate = paths.mixed_recording.with_suffix(suffix)
            if candidate.exists():
                return candidate
        return None

    def _duration_seconds(self, path: Path) -> float:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as wav_file:
                return wav_file.getnframes() / float(wav_file.getframerate())
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout or "{}")
        return float(payload.get("format", {}).get("duration", 0.0))

    def _pcm_samples(self, path: Path) -> list[int]:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as wav_file:
                raw = wav_file.readframes(wav_file.getnframes())
        else:
            process = subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    str(path),
                    "-f",
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "-ac",
                    "1",
                    "-ar",
                    "8000",
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
            )
            raw = process.stdout
        return [
            int.from_bytes(raw[index : index + 2], "little", signed=True)
            for index in range(0, len(raw), 2)
            if len(raw[index : index + 2]) == 2
        ]

    def _has_audio_energy(self, path: Path) -> bool:
        try:
            samples = self._pcm_samples(path)
        except Exception:
            return False
        if not samples:
            return False
        average_amplitude = sum(abs(sample) for sample in samples) / len(samples)
        return average_amplitude >= 120

    def _clipping_events(self, path: Path | None) -> int:
        if path is None:
            return 0
        try:
            samples = self._pcm_samples(path)
        except Exception:
            return 0
        return int(any(abs(sample) >= 32000 for sample in samples))

    def _longest_silence_ms(self, path: Path | None) -> int:
        if path is None:
            return 0
        try:
            samples = self._pcm_samples(path)
        except Exception:
            return 0
        if not samples:
            return 0
        samples_per_window = int((8000 * self.silence_window_ms) / 1000)
        longest = 0
        current = 0
        for index in range(0, len(samples), samples_per_window):
            window = samples[index : index + samples_per_window]
            if not window:
                continue
            energy = sum(abs(sample) for sample in window) / len(window)
            if energy < 80:
                current += self.silence_window_ms
                longest = max(longest, current)
            else:
                current = 0
        return longest

    def _issue(self, code: str, severity: str, message: str) -> RecordingValidationIssue:
        return RecordingValidationIssue(code=code, severity=severity, message=message)
