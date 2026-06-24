from __future__ import annotations

import audioop
import io
import wave
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TimedPcmSegment:
    start_ms: int
    pcm_bytes: bytes


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    return audioop.ulaw2lin(mulaw_bytes, 2)


def pcm16_to_wav_bytes(
    pcm_bytes: bytes,
    sample_rate: int = 8000,
    channels: int = 1,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return buffer.getvalue()


def wav_bytes_to_pcm16(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        pcm = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        raise ValueError("Only 16-bit PCM WAV inputs are supported.")
    if channels == 2:
        pcm = audioop.tomono(pcm, sample_width, 0.5, 0.5)
    if sample_rate != 8000:
        pcm, _ = audioop.ratecv(pcm, sample_width, 1, sample_rate, 8000, None)
    return pcm


def wav_to_mulaw(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        pcm = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        raise ValueError("Only 16-bit PCM WAV inputs are supported.")

    if channels == 2:
        pcm = audioop.tomono(pcm, sample_width, 0.5, 0.5)

    if sample_rate != 8000:
        pcm, _ = audioop.ratecv(pcm, sample_width, 1, sample_rate, 8000, None)

    return audioop.lin2ulaw(pcm, 2)


def chunk_mulaw_audio(mulaw_bytes: bytes, chunk_size: int = 160) -> list[bytes]:
    return [
        mulaw_bytes[index : index + chunk_size]
        for index in range(0, len(mulaw_bytes), chunk_size)
    ]


def duration_ms_from_mulaw(mulaw_bytes: bytes) -> int:
    return int((len(mulaw_bytes) / 8000) * 1000)


def duration_ms_from_text(text: str, floor_ms: int = 900) -> int:
    words = max(1, len(text.split()))
    estimated = int(words * 340)
    return max(floor_ms, estimated)


def silence_pcm16(duration_ms: int, sample_rate: int = 8000) -> bytes:
    frame_count = int(sample_rate * (duration_ms / 1000))
    return b"\x00\x00" * frame_count


def render_timed_pcm_track(
    segments: list[TimedPcmSegment],
    *,
    minimum_duration_ms: int = 0,
) -> bytes:
    if not segments and minimum_duration_ms <= 0:
        return b""

    end_offsets = [
        segment.start_ms + int((len(segment.pcm_bytes) / 2 / 8000) * 1000)
        for segment in segments
    ]
    total_duration_ms = max(end_offsets + [minimum_duration_ms], default=minimum_duration_ms)
    track = bytearray(silence_pcm16(total_duration_ms))

    for segment in segments:
        start_byte = int(segment.start_ms * 16)
        end_byte = start_byte + len(segment.pcm_bytes)
        if end_byte > len(track):
            track.extend(b"\x00" * (end_byte - len(track)))
        existing = bytes(track[start_byte:end_byte])
        if any(existing):
            mixed = audioop.add(existing, segment.pcm_bytes, 2)
            track[start_byte:end_byte] = mixed
        else:
            track[start_byte:end_byte] = segment.pcm_bytes
    return bytes(track)


def mix_pcm16_tracks(track_a: bytes, track_b: bytes) -> bytes:
    if len(track_a) < len(track_b):
        track_a = track_a + b"\x00" * (len(track_b) - len(track_a))
    elif len(track_b) < len(track_a):
        track_b = track_b + b"\x00" * (len(track_a) - len(track_b))
    if not track_a:
        return track_b
    if not track_b:
        return track_a
    return audioop.add(track_a, track_b, 2)


def wav_duration_seconds(path: str) -> float:
    with wave.open(path, "rb") as wav_file:
        return wav_file.getnframes() / float(wav_file.getframerate())
