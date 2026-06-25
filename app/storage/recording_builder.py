from __future__ import annotations

from pathlib import Path

from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.storage.artifacts import ArtifactPaths, ArtifactStore
from app.voice.audio import (
    TimedPcmSegment,
    mix_pcm16_tracks,
    pcm16_to_wav_bytes,
    render_timed_pcm_track,
    silence_pcm16,
)
from app.voice.local_tts import (
    DEFAULT_AGENT_VOICE,
    DEFAULT_PATIENT_VOICE,
    synthesize_line,
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


def build_spoken_recordings(
    *,
    transcript: TranscriptDocument,
    artifact_store: ArtifactStore,
    patient_voice: str = DEFAULT_PATIENT_VOICE,
    agent_voice: str = DEFAULT_AGENT_VOICE,
    gap_ms: int = 280,
) -> tuple[ArtifactPaths, Path, TranscriptDocument]:
    """Render a real, listenable two-voice conversation with free local TTS.

    Each turn is synthesized with a distinct voice and laid out sequentially so
    turn-taking sounds natural. Because synthesized speech rarely matches the
    text-estimated timing, the transcript is re-timed to the real audio and
    returned so the transcript, recordings, and metadata all stay consistent.
    """
    paths = artifact_store.paths_for(transcript.call_id)
    patient_segments: list[TimedPcmSegment] = []
    agent_segments: list[TimedPcmSegment] = []
    retimed: list[TranscriptSegment] = []

    cursor_ms = 0
    for segment in transcript.segments:
        if segment.speaker == "AGENT":
            speech = synthesize_line(segment.text, voice=agent_voice)
        elif segment.speaker == "PATIENT":
            speech = synthesize_line(segment.text, voice=patient_voice)
        else:
            speech = synthesize_line(segment.text)

        start_ms = cursor_ms
        timed = TimedPcmSegment(start_ms=start_ms, pcm_bytes=speech.pcm_bytes)
        if segment.speaker == "PATIENT":
            patient_segments.append(timed)
        elif segment.speaker == "AGENT":
            agent_segments.append(timed)

        end_ms = start_ms + speech.duration_ms
        retimed.append(
            segment.model_copy(
                update={
                    "start_timestamp": round(start_ms / 1000, 3),
                    "end_timestamp": round(end_ms / 1000, 3),
                    "overlap_duration_ms": 0,
                    "interruption_status": False,
                    "speaker_source": "voice_sim",
                }
            )
        )
        cursor_ms = end_ms + gap_ms

    total_duration_ms = max(1, cursor_ms - gap_ms)
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
        actual_mixed_path = mixed_wav_path

    retimed_transcript = transcript.model_copy(
        update={
            "duration_seconds": round(total_duration_ms / 1000, 3),
            "segments": retimed,
        }
    )
    return paths, actual_mixed_path, retimed_transcript
