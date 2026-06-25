from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.analysis.validation import TranscriptValidator
from app.config import get_settings
from app.doc_paths import get_repo_doc_paths
from app.storage.artifacts import ArtifactStore
from app.submission import is_provider_confirmed_live_call, list_call_bundles


def main() -> None:
    settings = get_settings()
    docs = get_repo_doc_paths(settings.project_root)
    docs.ensure_layout()
    artifact_store = ArtifactStore(settings.artifacts_root)
    validator = TranscriptValidator(
        gap_threshold_ms=settings.transcript_gap_threshold_ms,
        confidence_threshold=settings.transcript_confidence_threshold,
        duration_tolerance_seconds=settings.duration_mismatch_tolerance_seconds,
    )
    bundles = []
    reports = []
    for bundle in list_call_bundles(artifact_store):
        if not is_provider_confirmed_live_call(bundle.metadata):
            continue
        transcript = bundle.transcript
        if transcript is None:
            continue
        bundles.append(bundle)
        report = validator.validate(
            transcript=transcript,
            metadata=bundle.metadata,
            paths=bundle.paths,
        )
        reports.append(report)
        updated = bundle.metadata.model_copy(
            update={
                "transcript_validation_path": f"artifacts/validation/{bundle.paths.validation_json.name}",
                "transcript_validation_status": "passed" if report.passed else "failed",
                "average_transcript_confidence": report.average_confidence,
            }
        )
        artifact_store.write_metadata(updated)

    output_path = docs.transcript_validation_report
    lines = ["# Transcript Validation Report", ""]
    if not bundles:
        lines.extend(
            [
                "No provider-confirmed live calls were found, so transcript validation could not pass.",
                "",
            ]
        )
    for report in reports:
        lines.append(f"## {report.call_id}")
        lines.append("")
        for name, value in report.checks.items():
            lines.append(f"- {name}: `{value}`")
        lines.append("")
        if report.issues:
            lines.append("Issues:")
            for issue in report.issues:
                lines.append(f"- `{issue.code}` ({issue.severity}): {issue.message}")
            lines.append("")
        else:
            lines.extend(["Issues:", "- None", ""])
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    if not bundles or any(not report.passed for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
