from __future__ import annotations

from datetime import date

import pytest

from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.config import AppSettings
from app.storage.artifacts import ArtifactStore
from app.storage.recording_builder import build_spoken_recordings
from app.voice.audio import pcm16_rms, wav_bytes_to_pcm16
from app.voice.local_tts import synthesize_line, tts_available

requires_tts = pytest.mark.skipif(
    not tts_available(),
    reason="Local TTS requires `say` (macOS) and `ffmpeg` on PATH.",
)


def _transcript() -> TranscriptDocument:
    return TranscriptDocument(
        call_id="call-test",
        scenario_id="scheduling",
        created_on=date(2026, 1, 1),
        duration_seconds=0.0,
        segments=[
            TranscriptSegment(speaker="PATIENT", start_timestamp=0.0, end_timestamp=1.0, text="Hi, I'd like to book a visit."),
            TranscriptSegment(speaker="AGENT", start_timestamp=1.0, end_timestamp=2.0, text="Sure, what day works for you?"),
        ],
    )


@requires_tts
def test_synthesize_line_produces_audible_pcm() -> None:
    line = synthesize_line("Hello, this is a test.", voice=None)
    assert line.duration_ms > 0
    assert pcm16_rms(line.pcm_bytes) > 0


@requires_tts
def test_build_spoken_recordings_writes_real_audio_and_retimes(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    paths, mixed_path, retimed = build_spoken_recordings(
        transcript=_transcript(),
        artifact_store=store,
    )

    # Real, non-silent audio was written for both channels and the mix.
    assert paths.patient_recording.exists()
    assert paths.agent_recording.exists()
    assert mixed_path.exists() and mixed_path.stat().st_size > 0
    assert pcm16_rms(wav_bytes_to_pcm16(paths.patient_recording.read_bytes())) > 0

    # Transcript was re-timed to the synthesized audio and stays ordered.
    assert retimed.duration_seconds > 0
    starts = [segment.start_timestamp for segment in retimed.segments]
    assert starts == sorted(starts)
    assert retimed.segments[1].start_timestamp >= retimed.segments[0].end_timestamp


def test_blank_public_base_url_coerces_to_none() -> None:
    settings = AppSettings(PUBLIC_BASE_URL="")  # type: ignore[call-arg]
    assert settings.public_base_url is None
