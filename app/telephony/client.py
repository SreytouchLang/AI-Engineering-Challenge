from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from twilio.base.exceptions import TwilioException
from twilio.rest import Client

from app.config import AppSettings
from app.safety import ensure_real_calls_enabled, validate_destination


@dataclass(slots=True)
class OutboundCallResult:
    call_id: str
    provider_call_id: str
    status: str
    destination: str
    scenario_id: str


@dataclass(slots=True)
class ProviderRecordingReference:
    recording_id: str
    status: str
    channels: str | None
    source: str | None
    media_base_url: str
    duration_seconds: float | None
    attempts: int


class TwilioTelephonyClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def create_call(self, *, call_id: str, scenario_id: str) -> OutboundCallResult:
        ensure_real_calls_enabled(self.settings.enable_real_calls)
        destination = validate_destination(self.settings.authorized_destination)
        if not self.settings.telephony_from_number:
            raise RuntimeError("TELEPHONY_FROM_NUMBER is required for live calls.")

        base_url = self.settings.require_public_base_url()
        stream_query = urlencode({"call_id": call_id, "scenario_id": scenario_id})
        callback_query = urlencode({"call_id": call_id})
        stream_url = f"{self.settings.media_stream_url()}?{stream_query}"
        twiml = f'<Response><Connect><Stream url="{stream_url}" /></Connect></Response>'
        try:
            call = self._client().calls.create(
                to=destination,
                from_=self.settings.telephony_from_number,
                twiml=twiml,
                record=True,
                recording_channels="dual",
                recording_track="both",
                time_limit=self.settings.max_call_duration_seconds,
                status_callback=(f"{base_url}{self.settings.twilio_status_callback_path}?{callback_query}"),
                status_callback_event=[
                    "initiated",
                    "ringing",
                    "answered",
                    "completed",
                ],
                status_callback_method="POST",
                recording_status_callback=(f"{base_url}{self.settings.twilio_recording_callback_path}?{callback_query}"),
                recording_status_callback_event=[
                    "in-progress",
                    "completed",
                    "absent",
                ],
                recording_status_callback_method="POST",
            )
        except TwilioException as exc:
            raise RuntimeError(f"Telephony provider error while creating the outbound call: {exc}") from exc
        return OutboundCallResult(
            call_id=call_id,
            provider_call_id=call.sid,
            status=call.status,
            destination=destination,
            scenario_id=scenario_id,
        )

    def wait_for_recording(
        self,
        *,
        recording_id: str,
        max_attempts: int = 5,
        initial_backoff_seconds: float = 1.5,
    ) -> ProviderRecordingReference:
        backoff_seconds = initial_backoff_seconds
        for attempt in range(1, max_attempts + 1):
            try:
                recording = self._client().recordings(recording_id).fetch()
            except TwilioException as exc:
                raise RuntimeError(f"Telephony provider error while fetching recording metadata: {exc}") from exc

            status = str(recording.status or "")
            if status == "completed":
                return ProviderRecordingReference(
                    recording_id=recording.sid,
                    status=status,
                    channels=str(recording.channels) if recording.channels is not None else None,
                    source=str(recording.source) if recording.source is not None else None,
                    media_base_url=_recording_media_base_url(recording.uri),
                    duration_seconds=_optional_float(recording.duration),
                    attempts=attempt,
                )
            if status in {"failed", "absent", "deleted"}:
                raise RuntimeError(f"Provider recording {recording_id} is not retrievable (status={status}).")
            if attempt < max_attempts:
                time.sleep(backoff_seconds)
                backoff_seconds *= 2

        raise RuntimeError(f"Provider recording {recording_id} did not reach completed status after {max_attempts} attempts.")

    def download_recording(
        self,
        recording: ProviderRecordingReference,
        *,
        response_format: str = "mp3",
    ) -> tuple[bytes, int]:
        primary_url = f"{recording.media_base_url}.{response_format}?{urlencode({'RequestedChannels': 2})}"
        response = self._download_with_auth(primary_url)
        if response.status_code == 400:
            fallback_url = f"{recording.media_base_url}.{response_format}?{urlencode({'RequestedChannels': 1})}"
            fallback = self._download_with_auth(fallback_url)
            fallback.raise_for_status()
            return fallback.content, 1
        response.raise_for_status()
        return response.content, 2

    def _download_with_auth(self, url: str) -> httpx.Response:
        return httpx.get(
            url,
            auth=(self.settings.telephony_account_id or "", self.settings.telephony_auth_token or ""),
            follow_redirects=True,
            timeout=30.0,
        )

    def _client(self) -> Client:
        if not self.settings.telephony_account_id or not self.settings.telephony_auth_token:
            raise RuntimeError("Telephony credentials are missing.")
        return Client(
            self.settings.telephony_account_id,
            self.settings.telephony_auth_token,
        )


def _recording_media_base_url(recording_uri: str) -> str:
    if recording_uri.endswith(".json"):
        recording_uri = recording_uri[:-5]
    return f"https://api.twilio.com{recording_uri}"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        return float(value)
    return None
