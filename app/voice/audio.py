from __future__ import annotations

import audioop
import io
import wave


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

