from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.agent.scenario_loader import Scenario
from app.config import AppSettings
from app.safety import (
    RunBudget,
    format_phone_number_for_display,
    normalize_e164,
    redact_phone_number,
    validate_destination,
)
from app.storage.artifacts import ArtifactStore


@dataclass(slots=True)
class LiveCallPreflightReport:
    call_id: str
    scenario_id: str
    destination: str
    originating_number_masked: str | None
    webhook_url: str | None
    websocket_url: str | None
    recording_enabled: bool
    maximum_duration_seconds: int
    estimated_cost_usd: float
    artifacts_directory: str
    credentials_present: bool
    ffmpeg_available: bool
    ready: bool
    checks: dict[str, bool]
    problems: list[str]

    def render_text(self) -> str:
        return (
            "\n".join(
                [
                    "LIVE CALL PREFLIGHT",
                    "",
                    f"Call ID: {self.call_id}",
                    f"Scenario: {self.scenario_id}",
                    f"Destination: {self.destination}",
                    f"Originating number: {self.originating_number_masked or 'missing'}",
                    f"Webhook URL: {self.webhook_url or 'missing'}",
                    f"WebSocket URL: {self.websocket_url or 'missing'}",
                    f"Recording enabled: {self.recording_enabled}",
                    f"Maximum duration: {self.maximum_duration_seconds}",
                    f"Estimated maximum cost: ${self.estimated_cost_usd:.2f}",
                    f"Artifacts directory: {self.artifacts_directory}",
                    f"Credentials present: {self.credentials_present}",
                    f"ffmpeg available: {self.ffmpeg_available}",
                    f"Ready: {self.ready}",
                    "",
                    "Checks:",
                    *[f"- {name}: {value}" for name, value in self.checks.items()],
                    "",
                    "Problems:",
                    *([f"- {problem}" for problem in self.problems] or ["- None"]),
                ]
            ).rstrip()
            + "\n"
        )


def build_live_call_preflight(
    *,
    settings: AppSettings,
    scenario: Scenario,
    artifact_store: ArtifactStore,
    call_id: str,
) -> LiveCallPreflightReport:
    problems: list[str] = []
    checks: dict[str, bool] = {}

    destination_valid = False
    try:
        destination = validate_destination(settings.authorized_destination)
        destination_valid = True
    except Exception as exc:
        destination = settings.authorized_destination
        problems.append(str(exc))
    checks["destination_locked"] = destination_valid

    checks["enable_real_calls"] = settings.enable_real_calls
    if not settings.enable_real_calls:
        problems.append("ENABLE_REAL_CALLS must be true before a live call can be placed.")

    originating_number_valid = False
    try:
        if settings.telephony_from_number:
            normalize_e164(settings.telephony_from_number)
            originating_number_valid = True
    except Exception as exc:
        problems.append(f"TELEPHONY_FROM_NUMBER is invalid: {exc}")
    checks["single_originating_number_configured"] = originating_number_valid
    if settings.telephony_from_number is None:
        problems.append("TELEPHONY_FROM_NUMBER is required.")

    twilio_credentials_present = all((settings.telephony_account_id, settings.telephony_auth_token))
    openai_credentials_present = all((settings.llm_api_key, settings.stt_api_key, settings.tts_api_key))
    credentials_present = twilio_credentials_present and openai_credentials_present and originating_number_valid
    checks["twilio_credentials_present"] = twilio_credentials_present
    checks["openai_credentials_present"] = openai_credentials_present
    checks["credentials_present"] = credentials_present
    if not twilio_credentials_present:
        problems.append("Twilio credentials are missing.")
    if not openai_credentials_present:
        problems.append("One or more OpenAI credentials are missing.")

    webhook_url = None
    websocket_url = None
    webhook_https = False
    websocket_derived = False
    try:
        webhook_url = settings.require_public_base_url()
        websocket_url = settings.media_stream_url()
        webhook_https = webhook_url.startswith("https://")
        websocket_derived = websocket_url.startswith("wss://")
    except Exception as exc:
        problems.append(str(exc))
    checks["public_webhook_https"] = webhook_https
    checks["websocket_url_derived"] = websocket_derived
    if webhook_url and not webhook_https:
        problems.append("PUBLIC_BASE_URL must use HTTPS.")
    if websocket_url and not websocket_derived:
        problems.append("The derived media-stream URL must use wss://.")

    webhook_reachable = False
    if webhook_url is not None:
        try:
            response = httpx.get(f"{webhook_url}/health", timeout=5.0)
            webhook_reachable = response.status_code == 200
            if response.status_code != 200:
                problems.append(f"Webhook health check returned HTTP {response.status_code}.")
        except httpx.HTTPError as exc:
            problems.append(f"Webhook health check failed: {exc}")
    elif not any("PUBLIC_BASE_URL is required" in problem for problem in problems):
        problems.append("PUBLIC_BASE_URL is required for webhook-based live calls.")
    checks["webhook_reachable"] = webhook_reachable

    checks["scenario_valid"] = bool(scenario.id and scenario.goal.primary)
    if not checks["scenario_valid"]:
        problems.append("Scenario is missing a required id or primary goal.")

    checks["recording_enabled"] = True
    checks["maximum_duration_configured"] = settings.max_call_duration_seconds > 0 and scenario.constraints.max_duration_seconds > 0
    if not checks["maximum_duration_configured"]:
        problems.append("Maximum call duration must be configured.")

    checks["cost_within_limit"] = True
    try:
        RunBudget(
            max_calls_per_run=settings.max_calls_per_run,
            monthly_cost_limit_usd=settings.monthly_cost_limit_usd,
        ).reserve_call(settings.expected_cost_per_call_usd)
    except RuntimeError as exc:
        checks["cost_within_limit"] = False
        problems.append(str(exc))

    checks["call_id_unique"] = True
    try:
        artifact_store.reserve_call_id(call_id)
    except FileExistsError as exc:
        checks["call_id_unique"] = False
        problems.append(str(exc))

    checks["artifacts_directory_exists"] = artifact_store.root.exists()
    if not checks["artifacts_directory_exists"]:
        problems.append("Artifacts directory does not exist.")

    checks["artifacts_directory_writable"] = _artifacts_directory_writable(artifact_store.root)
    if not checks["artifacts_directory_writable"]:
        problems.append("Artifacts directory is not writable.")

    ffmpeg_available = shutil.which("ffmpeg") is not None
    ffprobe_available = shutil.which("ffprobe") is not None
    checks["ffmpeg_available"] = ffmpeg_available
    checks["ffprobe_available"] = ffprobe_available
    if not ffmpeg_available or not ffprobe_available:
        problems.append("Both ffmpeg and ffprobe must be available on PATH.")

    free_bytes = shutil.disk_usage(artifact_store.root).free
    checks["sufficient_disk_space"] = free_bytes >= 100 * 1024 * 1024
    if not checks["sufficient_disk_space"]:
        problems.append("Less than 100MB of free disk space is available for artifacts.")

    ready = all(checks.values()) and not problems
    display_destination = format_phone_number_for_display(destination) if destination_valid else destination
    return LiveCallPreflightReport(
        call_id=call_id,
        scenario_id=scenario.id,
        destination=display_destination,
        originating_number_masked=redact_phone_number(settings.telephony_from_number),
        webhook_url=webhook_url,
        websocket_url=websocket_url,
        recording_enabled=True,
        maximum_duration_seconds=min(
            settings.max_call_duration_seconds,
            scenario.constraints.max_duration_seconds,
        ),
        estimated_cost_usd=settings.expected_cost_per_call_usd,
        artifacts_directory=str(artifact_store.root),
        credentials_present=credentials_present,
        ffmpeg_available=ffmpeg_available and ffprobe_available,
        ready=ready,
        checks=checks,
        problems=problems,
    )


def _artifacts_directory_writable(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True
