from __future__ import annotations

import audioop
import struct

from app.voice.interruption import InterruptionController
from app.voice.turn_manager import TurnManager


def make_mulaw_frame(amplitude: int, duration_ms: int = 20) -> bytes:
    samples = int(8000 * duration_ms / 1000)
    pcm = b"".join(struct.pack("<h", amplitude) for _ in range(samples))
    return audioop.lin2ulaw(pcm, 2)


def test_turn_manager_detects_a_completed_turn() -> None:
    manager = TurnManager(rms_threshold=200, min_speech_ms=40, end_of_turn_silence_ms=40)
    speech = make_mulaw_frame(1200)
    silence = make_mulaw_frame(0)

    assert manager.ingest_mulaw_frame(speech, 0).speech_started is True
    assert manager.ingest_mulaw_frame(speech, 20).completed_turn is None
    assert manager.ingest_mulaw_frame(silence, 40).completed_turn is None
    completed = manager.ingest_mulaw_frame(silence, 80).completed_turn
    assert completed is not None
    assert completed.duration_ms >= 40
    assert completed.wav_bytes.startswith(b"RIFF")


def test_turn_manager_force_flush_ignores_too_short_audio() -> None:
    manager = TurnManager(rms_threshold=200, min_speech_ms=80, end_of_turn_silence_ms=40)
    manager.ingest_mulaw_frame(make_mulaw_frame(1000), 0)
    assert manager.force_flush(20) is None


def test_interruption_controller_clears_pending_marks() -> None:
    controller = InterruptionController()
    controller.register_outbound_audio("mark-1")
    assert controller.should_clear_for_barge_in() is True
    controller.clear()
    assert controller.should_clear_for_barge_in() is False

