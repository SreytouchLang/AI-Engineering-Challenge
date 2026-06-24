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
    parser = argparse.ArgumentParser(description="Replay a saved call without placing another phone call.")
    parser.add_argument("--call-id", required=True, help="Call id such as call-007.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Overwrite the saved evaluation, validation, and quality artifacts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    paths = artifact_store.paths_for(args.call_id)

    metadata = CallMetadata.model_validate_json(paths.metadata_json.read_text(encoding="utf-8"))
    transcript = TranscriptDocument.model_validate_json(paths.transcript_json.read_text(encoding="utf-8"))
    scenarios = {scenario.id: scenario for scenario in load_scenarios(settings.project_root / "scenarios")}

    validation = TranscriptValidator(
        gap_threshold_ms=settings.transcript_gap_threshold_ms,
        confidence_threshold=settings.transcript_confidence_threshold,
        duration_tolerance_seconds=settings.duration_mismatch_tolerance_seconds,
    ).validate(
        transcript=transcript,
        metadata=metadata,
        paths=paths,
    )
    quality = VoiceQualityAnalyzer().build_report(
        transcript=transcript,
        metadata=metadata,
        validation=validation,
        paths=paths,
    )
    replayed_evaluation = ConversationEvaluator().evaluate(
        scenario=scenarios[metadata.scenario_id],
        transcript=transcript,
    )
    replayed_evaluation.transcript_validation_passed = validation.passed
    replayed_evaluation.quality_score = quality.overall_score

    original_evaluation = artifact_store.load_evaluation(args.call_id) if paths.evaluation_json.exists() else None
    comparison = {
        "call_id": args.call_id,
        "original_issue_count": len(original_evaluation.issues) if original_evaluation else 0,
        "replayed_issue_count": len(replayed_evaluation.issues),
        "original_issue_titles": [issue.title for issue in original_evaluation.issues] if original_evaluation else [],
        "replayed_issue_titles": [issue.title for issue in replayed_evaluation.issues],
        "validation_passed": validation.passed,
        "quality_score": quality.overall_score,
    }

    if args.write:
        artifact_store.write_model_json(paths.validation_json, validation)
        artifact_store.write_markdown(paths.validation_md, validation.render_markdown())
        artifact_store.write_model_json(paths.quality_json, quality)
        artifact_store.write_markdown(paths.quality_md, quality.render_markdown())
        artifact_store.write_evaluation(replayed_evaluation)

    print(
        json.dumps(
            {
                "comparison": comparison,
                "validation": validation.model_dump(mode="json"),
                "quality": quality.model_dump(mode="json"),
                "evaluation": replayed_evaluation.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
