from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.analysis.recording_validation import RecordingValidator
from app.analysis.transcript import TranscriptDocument
from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata
from app.submission import is_provider_confirmed_live_call
from app.telephony.client import TwilioTelephonyClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and validate a real-call recording.")
    parser.add_argument("--call-id", required=True, help="Call id such as call-001.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    paths = artifact_store.paths_for(args.call_id)
    metadata = CallMetadata.model_validate_json(paths.metadata_json.read_text(encoding="utf-8"))

    if not is_provider_confirmed_live_call(metadata):
        raise SystemExit(f"{args.call_id} is not a provider-confirmed live call, so no recording can be fetched.")
    if not metadata.provider_recording_id:
        raise SystemExit(f"{args.call_id} does not yet have a provider recording id.")

    client = TwilioTelephonyClient(settings)
    reference = client.wait_for_recording(recording_id=metadata.provider_recording_id)
    recording_bytes, downloaded_channels = client.download_recording(reference)

    original_path = artifact_store.original_recording_path(args.call_id, ".mp3")
    original_path.write_bytes(recording_bytes)
    artifact_store.validate_audio_artifact(original_path)
    artifact_store.copy_audio(original_path, paths.recording)
    artifact_store.validate_audio_artifact(paths.recording)

    transcript = (
        TranscriptDocument.model_validate_json(paths.transcript_json.read_text(encoding="utf-8"))
        if paths.transcript_json.exists()
        else None
    )
    report = RecordingValidator(duration_tolerance_seconds=settings.duration_mismatch_tolerance_seconds).validate(
        metadata=metadata.model_copy(update={"recording_path": f"artifacts/recordings/{paths.recording.name}"}),
        paths=paths,
        transcript=transcript,
    )

    recording_validation_json, recording_validation_md = artifact_store.recording_validation_paths(args.call_id)
    artifact_store.write_model_json(recording_validation_json, report)
    artifact_store.write_markdown(recording_validation_md, report.render_markdown())

    updated = metadata.model_copy(
        update={
            "provider": "twilio",
            "is_real_call": True,
            "provider_recording_status": reference.status,
            "provider_recording_channels": reference.channels or str(downloaded_channels),
            "provider_recording_source": reference.source,
            "provider_recording_url": metadata.provider_recording_url or reference.media_base_url,
            "provider_recording_duration_seconds": reference.duration_seconds,
            "recording_original_path": f"artifacts/recordings/{original_path.name}",
            "recording_path": f"artifacts/recordings/{paths.recording.name}",
            "recording_download_status": "completed",
            "recording_download_attempts": reference.attempts,
            "recording_downloaded_at": datetime.now(UTC),
            "recording_checksum_sha256": str(report.metrics["checksum_sha256"]),
            "recording_validation_path": f"artifacts/validation/{recording_validation_json.name}",
            "recording_validation_status": "passed" if report.passed else "failed",
        }
    )
    artifact_store.write_metadata(updated)

    print(
        json.dumps(
            {
                "call_id": args.call_id,
                "provider_recording_id": reference.recording_id,
                "recording_path": updated.recording_path,
                "recording_original_path": updated.recording_original_path,
                "recording_status": updated.recording_download_status,
                "validation_status": updated.recording_validation_status,
                "checksum_sha256": updated.recording_checksum_sha256,
            },
            indent=2,
        )
    )

    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
