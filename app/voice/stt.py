from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    confidence: float | None
    latency_ms: float


class SpeechToTextClient(Protocol):
    def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        ...


class OpenAITranscriptionClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        started = time.perf_counter()
        payload = io.BytesIO(wav_bytes)
        payload.name = "turn.wav"
        response = self.client.audio.transcriptions.create(
            file=payload,
            model=self.model,
            response_format="text",
        )
        text = getattr(response, "text", response)
        latency_ms = (time.perf_counter() - started) * 1000
        return TranscriptionResult(text=text.strip(), confidence=None, latency_ms=latency_ms)


class StaticSpeechToTextClient:
    def __init__(self, scripted_results: list[str]) -> None:
        self.scripted_results = scripted_results
        self.index = 0

    def transcribe(self, wav_bytes: bytes) -> TranscriptionResult:
        if self.index >= len(self.scripted_results):
            text = ""
        else:
            text = self.scripted_results[self.index]
        self.index += 1
        return TranscriptionResult(text=text, confidence=1.0, latency_ms=0.0)

