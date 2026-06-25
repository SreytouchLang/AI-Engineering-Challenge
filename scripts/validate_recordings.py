from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.analysis.recording_validation import RecordingValidator
from app.config import get_settings
from app.doc_paths import get_repo_doc_paths
from app.storage.artifacts import ArtifactStore
from app.submission import is_provider_confirmed_live_call, list_call_bundles


def main() -> None:
    settings = get_settings()
    docs = get_repo_doc_paths(settings.project_root)
    docs.ensure_layout()
    artifact_store = ArtifactStore(settings.artifacts_root)
    bundles = [bundle for bundle in list_call_bundles(artifact_store) if is_provider_confirmed_live_call(bundle.metadata)]
    validator = RecordingValidator(duration_tolerance_seconds=settings.duration_mismatch_tolerance_seconds)
    reports = []
    for bundle in bundles:
        report = validator.validate(
            metadata=bundle.metadata,
            paths=bundle.paths,
            transcript=bundle.transcript,
        )
        reports.append(report)
        validation_json, validation_md = artifact_store.recording_validation_paths(bundle.call_id)
        artifact_store.write_model_json(validation_json, report)
        artifact_store.write_markdown(validation_md, report.render_markdown())
        updated = bundle.metadata.model_copy(
            update={
                "recording_validation_path": f"artifacts/validation/{validation_json.name}",
                "recording_validation_status": "passed" if report.passed else "failed",
                "recording_checksum_sha256": str(report.metrics["checksum_sha256"]),
            }
        )
        artifact_store.write_metadata(updated)

    output_path = docs.recording_validation_report
    lines = ["# Recording Validation Report", ""]
    if not bundles:
        lines.extend(
            [
                "No provider-confirmed live calls were found, so recording validation could not pass.",
                "",
            ]
        )
    for report in reports:
        lines.append(report.render_markdown())
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    if not bundles or any(not report.passed for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
