"""Free, offline text-to-speech using the macOS `say` command.

This powers the two-AI voice simulator: each conversation turn is synthesized
into real, listenable speech at no cost and with no API keys. Audio is rendered
at 8 kHz mono PCM16 to match the telephony-style mixing helpers in
``app.voice.audio`` (and to sound like a real phone call).

If `say` or `ffmpeg` are unavailable (for example on CI or Linux), callers
should check :func:`tts_available` first and fall back to silent placeholders.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.voice.audio import wav_bytes_to_pcm16

# Two distinct, widely available US English macOS voices so the patient and the
# clinic agent are easy to tell apart by ear.
DEFAULT_PATIENT_VOICE = "Samantha"
DEFAULT_AGENT_VOICE = "Daniel"

_TARGET_SAMPLE_RATE = 8000


@dataclass(frozen=True, slots=True)
class SynthesizedLine:
    pcm_bytes: bytes
    duration_ms: int


def tts_available() -> bool:
    """Return True when both `say` and `ffmpeg` are on PATH."""
    return shutil.which("say") is not None and shutil.which("ffmpeg") is not None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def synthesize_line(text: str, *, voice: str | None = None, rate_wpm: int | None = None) -> SynthesizedLine:
    """Synthesize one line of dialogue into 8 kHz mono PCM16 bytes.

    Falls back to a known-good built-in voice if the requested one is missing, so a
    machine without a specific voice installed still produces audio.
    """
    if not tts_available():
        raise RuntimeError("Local TTS requires both `say` and `ffmpeg` on PATH.")

    spoken = text.strip() or "..."
    chosen_voice = voice or DEFAULT_PATIENT_VOICE
    with tempfile.TemporaryDirectory(prefix="voice-sim-") as tmp:
        aiff_path = Path(tmp) / "line.aiff"
        wav_path = Path(tmp) / "line.wav"

        say_command = ["say"]
        if chosen_voice:
            say_command += ["-v", chosen_voice]
        if rate_wpm:
            say_command += ["-r", str(rate_wpm)]
        say_command += ["-o", str(aiff_path), spoken]

        result = _run(say_command)
        if result.returncode != 0 and chosen_voice != DEFAULT_PATIENT_VOICE:
            # Requested voice is probably not installed; retry with the default.
            retry_command = ["say", "-v", DEFAULT_PATIENT_VOICE]
            if rate_wpm:
                retry_command += ["-r", str(rate_wpm)]
            retry_command += ["-o", str(aiff_path), spoken]
            result = _run(retry_command)
        if result.returncode != 0:
            raise RuntimeError(f"`say` failed: {result.stderr.strip()}")

        convert = _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(aiff_path),
                "-ar",
                str(_TARGET_SAMPLE_RATE),
                "-ac",
                "1",
                "-acodec",
                "pcm_s16le",
                str(wav_path),
            ]
        )
        if convert.returncode != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {convert.stderr.strip()}")

        pcm = wav_bytes_to_pcm16(wav_path.read_bytes())

    duration_ms = int((len(pcm) / 2 / _TARGET_SAMPLE_RATE) * 1000)
    return SynthesizedLine(pcm_bytes=pcm, duration_ms=duration_ms)
