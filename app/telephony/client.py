from __future__ import annotations

from dataclasses import dataclass
from html import escape

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


class TwilioTelephonyClient:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def create_call(self, *, call_id: str, scenario_id: str) -> OutboundCallResult:
        ensure_real_calls_enabled(self.settings.enable_real_calls)
        destination = validate_destination(self.settings.authorized_destination)
        if not self.settings.telephony_account_id or not self.settings.telephony_auth_token:
            raise RuntimeError("Telephony credentials are missing.")
        if not self.settings.telephony_from_number:
            raise RuntimeError("TELEPHONY_FROM_NUMBER is required for live calls.")

        client = Client(
            self.settings.telephony_account_id,
            self.settings.telephony_auth_token,
        )
        base_url = self.settings.require_public_base_url()
        stream_url = (
            f"{self.settings.media_stream_url()}?call_id={escape(call_id)}"
            f"&scenario_id={escape(scenario_id)}"
        )
        twiml = (
            "<Response>"
            "<Connect>"
            f"<Stream url=\"{stream_url}\" />"
            "</Connect>"
            "</Response>"
        )
        try:
            call = client.calls.create(
                to=destination,
                from_=self.settings.telephony_from_number,
                twiml=twiml,
                record=True,
                time_limit=self.settings.max_call_duration_seconds,
                status_callback=f"{base_url}{self.settings.twilio_status_callback_path}",
                recording_status_callback=(
                    f"{base_url}{self.settings.twilio_recording_callback_path}"
                ),
            )
        except TwilioException as exc:
            raise RuntimeError(
                f"Telephony provider error while creating the outbound call: {exc}"
            ) from exc
        return OutboundCallResult(
            call_id=call_id,
            provider_call_id=call.sid,
            status=call.status,
            destination=destination,
            scenario_id=scenario_id,
        )
