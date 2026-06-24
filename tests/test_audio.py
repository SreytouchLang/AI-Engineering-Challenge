from __future__ import annotations

import struct
import wave
from io import BytesIO

from app.voice.audio import (
    add_pcm16,
    mix_pcm16_tracks,
    mulaw_to_pcm16,
    pcm16_rms,
    pcm16_to_mulaw,
    pcm16_to_wav_bytes,
    render_timed_pcm_track,
    resample_pcm16,
    stereo_pcm16_to_mono,
    wav_bytes_to_pcm16,
    wav_to_mulaw,
)


def _pcm_bytes(samples: list[int]) -> bytes:
    return b"".join(struct.pack("<h", sample) for sample in samples)


def _pcm_samples(pcm_bytes: bytes) -> list[int]:
    return [sample[0] for sample in struct.iter_unpack("<h", pcm_bytes)]


def test_mulaw_round_trip_preserves_shape() -> None:
    original = _pcm_bytes([0, 1000, -1000, 12000, -12000, 25000, -25000])

    decoded = mulaw_to_pcm16(pcm16_to_mulaw(original))
    decoded_samples = _pcm_samples(decoded)

    assert len(decoded_samples) == 7
    assert decoded_samples[0] == 0
    assert decoded_samples[1] > 0
    assert decoded_samples[2] < 0
    assert max(abs(value) for value in decoded_samples) <= 32767


def test_stereo_wav_is_downmixed_and_resampled_to_8khz() -> None:
    stereo_samples = [1000, 3000, 1000, 3000, -1000, 500, -1000, 500]
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(_pcm_bytes(stereo_samples))

    pcm = wav_bytes_to_pcm16(buffer.getvalue())
    samples = _pcm_samples(pcm)

    assert len(samples) == 2
    assert samples[0] == 2000
    assert samples[1] in {-250, -249}


def test_resample_pcm16_handles_single_sample_inputs() -> None:
    pcm = _pcm_bytes([1200])

    resampled = resample_pcm16(pcm, sample_rate=16000, target_sample_rate=8000)

    assert _pcm_samples(resampled) == [1200]


def test_add_pcm16_and_mix_pcm16_tracks_saturate() -> None:
    left = _pcm_bytes([30000, -30000])
    right = _pcm_bytes([10000, -10000])

    mixed = add_pcm16(left, right)
    combined = mix_pcm16_tracks(left, right)

    assert _pcm_samples(mixed) == [32767, -32768]
    assert _pcm_samples(combined) == [32767, -32768]


def test_render_timed_pcm_track_mixes_overlap() -> None:
    base = _pcm_bytes([1000, 1000, 1000, 1000])
    overlay = _pcm_bytes([500, 500])

    rendered = render_timed_pcm_track(
        [
            type("Segment", (), {"start_ms": 0, "pcm_bytes": base})(),
            type("Segment", (), {"start_ms": 0, "pcm_bytes": overlay})(),
        ]
    )

    assert _pcm_samples(rendered)[:2] == [1500, 1500]


def test_wav_to_mulaw_produces_expected_duration_and_rms() -> None:
    wav_bytes = pcm16_to_wav_bytes(_pcm_bytes([0, 1000, -1000, 0]), sample_rate=8000)

    mulaw = wav_to_mulaw(wav_bytes)
    pcm = mulaw_to_pcm16(mulaw)

    assert len(mulaw) == 4
    assert len(pcm) == 8
    assert pcm16_rms(pcm) > 0


def test_stereo_pcm16_to_mono_averages_channels() -> None:
    mono = stereo_pcm16_to_mono(_pcm_bytes([1000, 3000, -2000, 2000]))
    assert _pcm_samples(mono) == [2000, 0]
