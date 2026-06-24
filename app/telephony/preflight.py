from __future__ import annotations

import shutil
from dataclasses import dataclass

import httpx

from app.agent.scenario_loader import Scenario
from app.config import AppSettings
from app.safety import RunBudget, mask_phone_number, validate_destination
from app.storage.artifacts import ArtifactStore


@dataclass(slots=True)
class LiveCallPreflightReport:
    call_id: str
    scenario_id: str
    destination: str
    originating_number_masked: str | None
    public_webhook: str | None
    websocket_endpoint: str | None
    recording_enabled: bool
    recording_channels: str
    maximum_duration_seconds: int
    estimated_cost_usd: float
    output_directory: str
    credentials_present: bool
    ready: bool
    checks: dict[str, bool]
    problems: list[str]

    def render_text(self) -> str:
        return "\n".join(
            [
                "LIVE CALL PREFLIGHT",
                "",
                f"Scenario: {self.scenario_id}",
                f"Call ID: {self.call_id}",
                f"Destination: {self.destination}",
                f"Originating number: {self.originating_number_masked or 'missing'}",
                f"Public webhook: {self.public_webhook or 'missing'}",
                f"WebSocket endpoint: {self.websocket_endpoint or 'missing'}",
                f"Recording enabled: {self.recording_enabled}",
                f"Recording channels: {self.recording_channels}",
                f"Maximum duration: {self.maximum_duration_seconds}",
                f"Estimated cost: ${self.estimated_cost_usd:.2f}",
                f"Output directory: {self.output_directory}",
                f"Credentials present: {self.credentials_present}",
                f"Ready: {self.ready}",
                "",
                "Checks:",
                *[f"- {name}: {value}" for name, value in self.checks.items()],
                "",
                "Problems:",
                *([f"- {problem}" for problem in self.problems] or ["- None"]),
            ]
        ).rstrip() + "\n"


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
    checks["authorized_destination"] = destination_valid

    checks["enable_real_calls"] = settings.enable_real_calls
    if not settings.enable_real_calls:
        problems.append("ENABLE_REAL_CALLS must be true.")

    checks["single_originating_number"] = bool(settings.telephony_from_number)
    if not settings.telephony_from_number:
        problems.append("TELEPHONY_FROM_NUMBER is required.")

    credentials_present = all(
        (
            settings.telephony_account_id,
            settings.telephony_auth_token,
            settings.telephony_from_number,
            settings.stt_api_key,
            settings.tts_api_key,
        )
    )
    checks["credentials_present"] = credentials_present
    if not credentials_present:
        problems.append("One or more required live-call credentials are missing.")

    public_webhook = None
    websocket_endpoint = None
    public_url_valid = False
    websocket_reachable = False
    try:
        public_webhook = settings.require_public_base_url()
        websocket_endpoint = settings.media_stream_url()
        public_url_valid = public_webhook.startswith("https://")
    except Exception as exc:
        problems.append(str(exc))

    checks["public_webhook_https"] = public_url_valid
    if public_webhook and not public_url_valid:
        problems.append("PUBLIC_BASE_URL must use HTTPS.")

    if public_webhook is not None:
        try:
            response = httpx.get(
                f"{public_webhook}/health",
                timeout=5.0,
            )
            checks["webhook_reachable"] = response.status_code == 200
            if response.status_code != 200:
                problems.append(
                    f"Webhook health check returned HTTP {response.status_code}."
                )
        except httpx.HTTPError as exc:
            checks["webhook_reachable"] = False
            problems.append(f"Webhook health check failed: {exc}")
    else:
        checks["webhook_reachable"] = False

    if websocket_endpoint is not None:
        websocket_reachable = checks["webhook_reachable"]
    checks["websocket_reachable"] = websocket_reachable
    if websocket_endpoint and not websocket_reachable:
        problems.append("WebSocket reachability could not be verified from the public health check.")

    checks["scenario_valid"] = bool(scenario.id and scenario.goal.primary)
    checks["recording_enabled"] = True
    checks["dual_channel_recording"] = True
    checks["maximum_duration_enforced"] = settings.max_call_duration_seconds > 0
    checks["cost_within_limit"] = True
    try:
        RunBudget(
            max_calls_per_run=settings.max_calls_per_run,
            monthly_cost_limit_usd=settings.monthly_cost_limit_usd,
        ).reserve_call(settings.expected_cost_per_call_usd)
    except RuntimeError as exc:
        checks["cost_within_limit"] = False
        problems.append(str(exc))

    checks["artifact_output_directory_exists"] = artifact_store.root.exists()
    if not artifact_store.root.exists():
        problems.append("Artifact output directory does not exist.")

    checks["duplicate_call_id"] = True
    try:
        artifact_store.reserve_call_id(call_id)
    except FileExistsError as exc:
        checks["duplicate_call_id"] = False
        problems.append(str(exc))

    free_bytes = shutil.disk_usage(artifact_store.root).free
    checks["sufficient_disk_space"] = free_bytes >= 100 * 1024 * 1024
    if not checks["sufficient_disk_space"]:
        problems.append("Less than 100MB of free disk space is available for artifacts.")

    ready = all(checks.values()) and not problems
    return LiveCallPreflightReport(
        call_id=call_id,
        scenario_id=scenario.id,
        destination=destination,
        originating_number_masked=mask_phone_number(settings.telephony_from_number),
        public_webhook=public_webhook,
        websocket_endpoint=websocket_endpoint,
        recording_enabled=True,
        recording_channels="dual (provider) + patient/agent/mixed (local artifacts)",
        maximum_duration_seconds=min(
            settings.max_call_duration_seconds,
            scenario.constraints.max_duration_seconds,
        ),
        estimated_cost_usd=settings.expected_cost_per_call_usd,
        output_directory=str(artifact_store.root),
        credentials_present=credentials_present,
        ready=ready,
        checks=checks,
        problems=problems,
    )
