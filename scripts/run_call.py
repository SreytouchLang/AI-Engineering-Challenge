from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.dry_run import DryRunConversationRunner
from app.agent.scenario_loader import load_scenario
from app.config import get_settings
from app.safety import AUTHORIZED_DESTINATION, mask_phone_number
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata
from app.storage.recording_builder import build_dry_run_recordings
from app.telephony.client import TwilioTelephonyClient
from app.telephony.preflight import build_live_call_preflight


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a dry run or live assessment call.")
    parser.add_argument("--scenario", required=True, help="Path to the scenario YAML.")
    parser.add_argument("--call-id", help="Optional explicit call id.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the text-only simulator instead of placing a phone call.",
    )
    parser.add_argument(
        "--confirm-live-call",
        default="false",
        help="Must be set to true to place a real call.",
    )
    return parser.parse_args()


def next_call_id(artifact_store: ArtifactStore) -> str:
    existing = sorted(artifact_store.metadata_dir.glob("call-*.json"))
    if not existing:
        return "call-001"
    last = existing[-1].stem
    sequence = int(last.split("-")[1]) + 1
    return f"call-{sequence:03d}"


def main() -> None:
    args = parse_args()
    settings = get_settings()
    scenario = load_scenario(args.scenario)
    artifact_store = ArtifactStore(settings.artifacts_root)
    call_id = args.call_id or next_call_id(artifact_store)

    if args.dry_run or not settings.enable_real_calls:
        artifact_store.reserve_call_id(call_id)
        result = DryRunConversationRunner(settings, scenario).run(call_id=call_id)
        transcript_paths = artifact_store.write_transcript(result.transcript)
        _, mixed_recording_path = build_dry_run_recordings(
            transcript=result.transcript,
            artifact_store=artifact_store,
        )
        metadata = result.metadata.model_copy(
            update={
                "transcript_path": f"artifacts/transcripts/{call_id}.txt",
                "recording_path": f"artifacts/recordings/{mixed_recording_path.name}",
                "patient_recording_path": f"artifacts/recordings/{call_id}-patient.wav",
                "agent_recording_path": f"artifacts/recordings/{call_id}-agent.wav",
                "mixed_recording_path": f"artifacts/recordings/{mixed_recording_path.name}",
                "average_transcript_confidence": 1.0,
            }
        )
        artifact_store.write_metadata(metadata)
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "call_id": call_id,
                    "scenario_id": scenario.id,
                    "transcript": str(transcript_paths.transcript_text),
                },
                indent=2,
            )
        )
        return

    preflight = build_live_call_preflight(
        settings=settings,
        scenario=scenario,
        artifact_store=artifact_store,
        call_id=call_id,
    )
    print(preflight.render_text())
    if args.confirm_live_call.lower() != "true":
        raise SystemExit(
            "Live call preflight displayed. Re-run with --confirm-live-call=true when ready."
        )
    if not preflight.ready:
        raise SystemExit("Live call preflight failed. Resolve the reported problems first.")
    if not sys.stdin.isatty():
        raise SystemExit("Interactive confirmation is required before placing a live call.")
    confirmation = input("Type CALL to place the live call: ").strip()
    if confirmation != "CALL":
        raise SystemExit("Live call cancelled before dialing.")

    artifact_store.reserve_call_id(call_id)
    metadata = CallMetadata(
        call_id=call_id,
        scenario_id=scenario.id,
        destination_number=AUTHORIZED_DESTINATION,
        originating_number_masked=mask_phone_number(settings.telephony_from_number),
        start_time=resulting_timestamp(),
        call_status="preflight_passed",
        mode="live",
        estimated_cost_usd=settings.expected_cost_per_call_usd,
        model_names={
            "llm": settings.llm_model,
            "stt": settings.stt_model,
            "tts": settings.tts_model,
        },
        problems=[],
    )
    artifact_store.write_metadata(metadata)
    try:
        result = TwilioTelephonyClient(settings).create_call(
            call_id=call_id,
            scenario_id=scenario.id,
        )
    except Exception as exc:
        failed = metadata.model_copy(
            update={
                "call_status": "failed_to_start",
                "termination_reason": "provider_start_failed",
                "problems": [str(exc)],
            }
        )
        artifact_store.write_metadata(failed)
        raise

    updated = metadata.model_copy(
        update={
            "provider_call_id": result.provider_call_id,
            "destination_number": result.destination,
            "call_status": result.status,
        }
    )
    artifact_store.write_metadata(updated)
    print(
        "\n".join(
            [
                "CALL RESULT",
                "",
                f"Provider call ID: {result.provider_call_id}",
                f"Status: {result.status}",
                "Duration: pending",
                "Recording: pending",
                "Transcript: pending",
                "Evaluation: pending",
                "Quality score: pending",
                f"Estimated cost: ${settings.expected_cost_per_call_usd:.2f}",
                "Submission-ready: false",
                "Problems: none",
            ]
        )
    )


def resulting_timestamp():
    from datetime import UTC, datetime

    return datetime.now(UTC)


if __name__ == "__main__":
    main()
