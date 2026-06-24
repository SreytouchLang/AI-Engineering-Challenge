from __future__ import annotations

import audioop
from dataclasses import dataclass

from app.voice.audio import pcm16_to_wav_bytes


@dataclass(slots=True)
class CompletedTurn:
    wav_bytes: bytes
    start_timestamp_ms: int
    end_timestamp_ms: int
    duration_ms: int
    average_rms: float


@dataclass(slots=True)
class TurnEvent:
    speech_started: bool = False
    completed_turn: CompletedTurn | None = None


class TurnManager:
    """Simple VAD-based turn detection for 8kHz mu-law audio."""

    def __init__(
        self,
        *,
        rms_threshold: int,
        min_speech_ms: int,
        end_of_turn_silence_ms: int,
    ) -> None:
        self.rms_threshold = rms_threshold
        self.min_speech_ms = min_speech_ms
        self.end_of_turn_silence_ms = end_of_turn_silence_ms
        self._reset()

    def ingest_mulaw_frame(self, payload: bytes, timestamp_ms: int) -> TurnEvent:
        pcm = audioop.ulaw2lin(payload, 2)
        rms = audioop.rms(pcm, 2)
        is_speech = rms >= self.rms_threshold
        frame_ms = max(1, int(round(len(payload) / 8)))
        event = TurnEvent()

        if is_speech and not self.in_speech:
            self.in_speech = True
            self.turn_start_ms = timestamp_ms
            self.last_speech_ms = timestamp_ms
            event.speech_started = True

        if self.in_speech:
            self.buffer.extend(pcm)
            self.samples_seen += 1
            self.rms_total += rms

        if is_speech:
            self.last_speech_ms = timestamp_ms
            self.speech_duration_ms += frame_ms

        silence_ms = timestamp_ms - self.last_speech_ms if self.last_speech_ms is not None else 0
        if (
            self.in_speech
            and not is_speech
            and self.speech_duration_ms >= self.min_speech_ms
            and silence_ms >= self.end_of_turn_silence_ms
        ):
            event.completed_turn = self._flush(timestamp_ms)

        return event

    def force_flush(self, timestamp_ms: int) -> CompletedTurn | None:
        if not self.in_speech or self.speech_duration_ms < self.min_speech_ms:
            self._reset()
            return None
        return self._flush(timestamp_ms)

    def _flush(self, timestamp_ms: int) -> CompletedTurn:
        wav_bytes = pcm16_to_wav_bytes(bytes(self.buffer), sample_rate=8000)
        average_rms = self.rms_total / max(1, self.samples_seen)
        completed = CompletedTurn(
            wav_bytes=wav_bytes,
            start_timestamp_ms=self.turn_start_ms or 0,
            end_timestamp_ms=timestamp_ms,
            duration_ms=max(0, timestamp_ms - (self.turn_start_ms or 0)),
            average_rms=average_rms,
        )
        self._reset()
        return completed

    def _reset(self) -> None:
        self.buffer = bytearray()
        self.in_speech = False
        self.turn_start_ms: int | None = None
        self.last_speech_ms: int | None = None
        self.speech_duration_ms = 0
        self.rms_total = 0.0
        self.samples_seen = 0

