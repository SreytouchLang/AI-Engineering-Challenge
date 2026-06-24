from __future__ import annotations

from pathlib import Path

from app.analysis.transcript import TranscriptDocument
from app.storage.artifacts import ArtifactPaths, ArtifactStore
from app.voice.audio import (
    TimedPcmSegment,
    mix_pcm16_tracks,
    pcm16_to_wav_bytes,
    render_timed_pcm_track,
    silence_pcm16,
)


def build_dry_run_recordings(
    *,
    transcript: TranscriptDocument,
    artifact_store: ArtifactStore,
) -> tuple[ArtifactPaths, Path]:
    paths = artifact_store.paths_for(transcript.call_id)
    patient_segments: list[TimedPcmSegment] = []
    agent_segments: list[TimedPcmSegment] = []

    for segment in transcript.segments:
        duration_ms = max(1, int((segment.end_timestamp - segment.start_timestamp) * 1000))
        timed_segment = TimedPcmSegment(
            start_ms=int(segment.start_timestamp * 1000),
            pcm_bytes=silence_pcm16(duration_ms),
        )
        if segment.speaker == "PATIENT":
            patient_segments.append(timed_segment)
        elif segment.speaker == "AGENT":
            agent_segments.append(timed_segment)

    total_duration_ms = max(1, int(transcript.duration_seconds * 1000))
    patient_track = render_timed_pcm_track(patient_segments, minimum_duration_ms=total_duration_ms)
    agent_track = render_timed_pcm_track(agent_segments, minimum_duration_ms=total_duration_ms)
    mixed_track = mix_pcm16_tracks(patient_track, agent_track)

    paths.patient_recording.write_bytes(pcm16_to_wav_bytes(patient_track))
    paths.agent_recording.write_bytes(pcm16_to_wav_bytes(agent_track))
    mixed_wav_path = paths.mixed_recording.with_suffix(".wav")
    mixed_wav_path.write_bytes(pcm16_to_wav_bytes(mixed_track))
    actual_mixed_path = paths.mixed_recording
    try:
        artifact_store.convert_audio(mixed_wav_path, paths.mixed_recording)
        mixed_wav_path.unlink(missing_ok=True)
    except Exception:
        # Dry-run mode can fall back to WAV if ffmpeg is unavailable locally.
        actual_mixed_path = mixed_wav_path
    return paths, actual_mixed_path
