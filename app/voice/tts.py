from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Protocol

from openai import Omit, OpenAI

from app.voice.audio import duration_ms_from_mulaw, duration_ms_from_text, wav_to_mulaw


@dataclass(slots=True)
class SynthesisResult:
    wav_bytes: bytes
    mulaw_bytes: bytes
    latency_ms: float
    duration_ms: int


class SpeechSynthesisClient(Protocol):
    def synthesize(self, text: str, instructions: str | None = None) -> SynthesisResult: ...


class OpenAITtsClient:
    def __init__(self, api_key: str, model: str, voice: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.voice = voice

    def synthesize(self, text: str, instructions: str | None = None) -> SynthesisResult:
        started = time.perf_counter()
        buffer = io.BytesIO()
        request_instructions: str | Omit = instructions if instructions is not None else Omit()
        with self.client.audio.speech.with_streaming_response.create(
            model=self.model,
            voice=self.voice,
            input=text,
            instructions=request_instructions,
            response_format="wav",
        ) as response:
            for chunk in response.iter_bytes():
                buffer.write(chunk)

        wav_bytes = buffer.getvalue()
        mulaw_bytes = wav_to_mulaw(wav_bytes)
        latency_ms = (time.perf_counter() - started) * 1000
        return SynthesisResult(
            wav_bytes=wav_bytes,
            mulaw_bytes=mulaw_bytes,
            latency_ms=latency_ms,
            duration_ms=duration_ms_from_mulaw(mulaw_bytes),
        )


class SilentSpeechSynthesisClient:
    def synthesize(self, text: str, instructions: str | None = None) -> SynthesisResult:
        del instructions
        duration_ms = duration_ms_from_text(text)
        mulaw_bytes = b"\xff" * int(duration_ms * 8)
        return SynthesisResult(
            wav_bytes=b"",
            mulaw_bytes=mulaw_bytes,
            latency_ms=0.0,
            duration_ms=duration_ms,
        )
