from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.scenario_loader import load_scenarios
from app.analysis.evaluator import ConversationEvaluator
from app.analysis.quality import VoiceQualityAnalyzer
from app.analysis.transcript import TranscriptDocument
from app.analysis.validation import TranscriptValidator
from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a completed call transcript.")
    parser.add_argument("--call-id", required=True, help="Call id such as call-001.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    paths = artifact_store.paths_for(args.call_id)
    metadata_path = paths.metadata_json
    transcript_path = paths.transcript_json

    metadata = CallMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    transcript = TranscriptDocument.model_validate_json(
        transcript_path.read_text(encoding="utf-8")
    )
    validation = TranscriptValidator(
        gap_threshold_ms=settings.transcript_gap_threshold_ms,
        confidence_threshold=settings.transcript_confidence_threshold,
        duration_tolerance_seconds=settings.duration_mismatch_tolerance_seconds,
    ).validate(
        transcript=transcript,
        metadata=metadata,
        paths=paths,
    )
    artifact_store.write_model_json(paths.validation_json, validation)
    artifact_store.write_markdown(paths.validation_md, validation.render_markdown())

    quality = VoiceQualityAnalyzer().build_report(
        transcript=transcript,
        metadata=metadata,
        validation=validation,
        paths=paths,
    )
    artifact_store.write_model_json(paths.quality_json, quality)
    artifact_store.write_markdown(paths.quality_md, quality.render_markdown())

    scenarios = {
        scenario.id: scenario for scenario in load_scenarios(settings.project_root / "scenarios")
    }
    evaluation = ConversationEvaluator().evaluate(
        scenario=scenarios[metadata.scenario_id],
        transcript=transcript,
    )
    for issue in evaluation.issues:
        issue.recording_path = metadata.mixed_recording_path or metadata.recording_path
        issue.transcript_path = metadata.transcript_path
        issue.evidence_excerpt = issue.evidence[:180]
        issue.actual_behavior = issue.actual_behavior or issue.evidence
        issue.transcript_confidence = validation.average_confidence
    evaluation.transcript_validation_passed = validation.passed
    evaluation.quality_score = quality.overall_score
    artifact_store.write_evaluation(evaluation)
    updated_metadata = metadata.model_copy(
        update={
            "analysis_completion_status": "completed",
            "transcript_validation_path": f"artifacts/validation/{paths.validation_json.name}",
            "transcript_validation_status": "passed" if validation.passed else "failed",
            "quality_report_path": f"artifacts/quality/{paths.quality_json.name}",
            "quality_score": quality.overall_score,
            "average_transcript_confidence": validation.average_confidence,
        }
    )
    artifact_store.write_metadata(updated_metadata)
    print(
        json.dumps(
            {
                "validation": validation.model_dump(mode="json"),
                "quality": quality.model_dump(mode="json"),
                "evaluation": evaluation.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
