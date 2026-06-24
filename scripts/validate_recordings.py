from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.analysis.recording_validation import RecordingValidator
from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.submission import is_provider_confirmed_live_call, list_call_bundles


def main() -> None:
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    bundles = [
        bundle
        for bundle in list_call_bundles(artifact_store)
        if is_provider_confirmed_live_call(bundle.metadata)
    ]
    validator = RecordingValidator(
        duration_tolerance_seconds=settings.duration_mismatch_tolerance_seconds
    )
    reports = [
        validator.validate(
            metadata=bundle.metadata,
            paths=bundle.paths,
            transcript=bundle.transcript,
        )
        for bundle in bundles
    ]

    output_path = settings.project_root / "RECORDING_VALIDATION_REPORT.md"
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
