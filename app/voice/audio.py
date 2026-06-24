from __future__ import annotations

import io
import json
import math
import subprocess
import sys
import wave
from array import array
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_PCM16_MAX = 32767
_PCM16_MIN = -32768
_MULAW_BIAS = 0x84
_MULAW_CLIP = 32635


@dataclass(frozen=True, slots=True)
class TimedPcmSegment:
    start_ms: int
    pcm_bytes: bytes


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    samples = array("h", (_decode_mulaw_byte(value) for value in mulaw_bytes))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    samples = _pcm16_array(pcm_bytes)
    encoded = bytearray(len(samples))
    for index, sample in enumerate(samples):
        encoded[index] = _encode_mulaw_sample(sample)
    return bytes(encoded)


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
        pcm = stereo_pcm16_to_mono(pcm)
    if sample_rate != 8000:
        pcm = resample_pcm16(pcm, sample_rate=sample_rate, target_sample_rate=8000)
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
        pcm = stereo_pcm16_to_mono(pcm)

    if sample_rate != 8000:
        pcm = resample_pcm16(pcm, sample_rate=sample_rate, target_sample_rate=8000)

    return pcm16_to_mulaw(pcm)


def chunk_mulaw_audio(mulaw_bytes: bytes, chunk_size: int = 160) -> list[bytes]:
    return [mulaw_bytes[index : index + chunk_size] for index in range(0, len(mulaw_bytes), chunk_size)]


def duration_ms_from_mulaw(mulaw_bytes: bytes) -> int:
    return int((len(mulaw_bytes) / 8000) * 1000)


def duration_ms_from_text(text: str, floor_ms: int = 900) -> int:
    words = max(1, len(text.split()))
    estimated = int(words * 340)
    return max(floor_ms, estimated)


def silence_pcm16(duration_ms: int, sample_rate: int = 8000) -> bytes:
    frame_count = int(sample_rate * (duration_ms / 1000))
    return b"\x00\x00" * frame_count


def pcm16_rms(pcm_bytes: bytes) -> int:
    samples = _pcm16_array(pcm_bytes)
    if not samples:
        return 0
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    return int(round(math.sqrt(mean_square)))


def stereo_pcm16_to_mono(pcm_bytes: bytes) -> bytes:
    samples = _pcm16_array(pcm_bytes)
    if len(samples) % 2 != 0:
        raise ValueError("Stereo PCM must contain an even number of samples.")
    mono_samples = [_clip_pcm16(int(round((samples[index] + samples[index + 1]) / 2))) for index in range(0, len(samples), 2)]
    return _pcm16_bytes(mono_samples)


def resample_pcm16(
    pcm_bytes: bytes,
    *,
    sample_rate: int,
    target_sample_rate: int,
) -> bytes:
    if sample_rate <= 0 or target_sample_rate <= 0:
        raise ValueError("Sample rates must be positive integers.")
    samples = list(_pcm16_array(pcm_bytes))
    if not samples or sample_rate == target_sample_rate:
        return pcm_bytes

    target_length = max(1, int(round(len(samples) * target_sample_rate / sample_rate)))
    if len(samples) == 1:
        return _pcm16_bytes([samples[0]] * target_length)

    scale = (len(samples) - 1) / max(1, target_length - 1)
    resampled: list[int] = []
    for index in range(target_length):
        source_position = index * scale
        left_index = int(source_position)
        right_index = min(left_index + 1, len(samples) - 1)
        fraction = source_position - left_index
        left = samples[left_index]
        right = samples[right_index]
        interpolated = left if left_index == right_index else round(left + ((right - left) * fraction))
        resampled.append(_clip_pcm16(interpolated))
    return _pcm16_bytes(resampled)


def render_timed_pcm_track(
    segments: list[TimedPcmSegment],
    *,
    minimum_duration_ms: int = 0,
) -> bytes:
    if not segments and minimum_duration_ms <= 0:
        return b""

    end_offsets = [segment.start_ms + int((len(segment.pcm_bytes) / 2 / 8000) * 1000) for segment in segments]
    total_duration_ms = max(end_offsets + [minimum_duration_ms], default=minimum_duration_ms)
    track = bytearray(silence_pcm16(total_duration_ms))

    for segment in segments:
        start_byte = int(segment.start_ms * 16)
        end_byte = start_byte + len(segment.pcm_bytes)
        if end_byte > len(track):
            track.extend(b"\x00" * (end_byte - len(track)))
        existing = bytes(track[start_byte:end_byte])
        if any(existing):
            mixed = add_pcm16(existing, segment.pcm_bytes)
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
    return add_pcm16(track_a, track_b)


def wav_duration_seconds(path: str) -> float:
    with wave.open(path, "rb") as wav_file:
        return wav_file.getnframes() / float(wav_file.getframerate())


def audio_duration_seconds(path: str | Path) -> float:
    audio_path = Path(path)
    if audio_path.suffix.lower() == ".wav":
        return wav_duration_seconds(str(audio_path))

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout or "{}")
    return float(payload.get("format", {}).get("duration", 0.0))


def add_pcm16(first: bytes, second: bytes) -> bytes:
    if len(first) != len(second):
        raise ValueError("PCM buffers must be the same length to be mixed.")
    samples_a = _pcm16_array(first)
    samples_b = _pcm16_array(second)
    return _pcm16_bytes(_clip_pcm16(left + right) for left, right in zip(samples_a, samples_b, strict=True))


def _pcm16_array(pcm_bytes: bytes) -> array[int]:
    if len(pcm_bytes) % 2 != 0:
        raise ValueError("PCM16 byte buffers must contain an even number of bytes.")
    samples: array[int] = array("h")
    samples.frombytes(pcm_bytes)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _pcm16_bytes(samples: Iterable[int]) -> bytes:
    pcm = array("h", (_clip_pcm16(int(sample)) for sample in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()


def _clip_pcm16(value: int) -> int:
    return max(_PCM16_MIN, min(_PCM16_MAX, value))


def _decode_mulaw_byte(value: int) -> int:
    inverted = (~value) & 0xFF
    magnitude = (((inverted & 0x0F) << 3) + _MULAW_BIAS) << ((inverted >> 4) & 0x07)
    sample = magnitude - _MULAW_BIAS
    return -sample if inverted & 0x80 else sample


def _encode_mulaw_sample(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    magnitude = min(abs(sample), _MULAW_CLIP) + _MULAW_BIAS
    exponent = min(7, max(0, magnitude.bit_length() - 8))
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa)) & 0xFF
