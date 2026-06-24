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
from app.analysis.transcript import TranscriptDocument
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
    metadata_path = artifact_store.paths_for(args.call_id).metadata_json
    transcript_path = artifact_store.paths_for(args.call_id).transcript_json

    metadata = CallMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    transcript = TranscriptDocument.model_validate_json(
        transcript_path.read_text(encoding="utf-8")
    )
    scenarios = {
        scenario.id: scenario for scenario in load_scenarios(settings.project_root / "scenarios")
    }
    evaluation = ConversationEvaluator().evaluate(
        scenario=scenarios[metadata.scenario_id],
        transcript=transcript,
    )
    artifact_store.write_evaluation(evaluation)
    updated_metadata = metadata.model_copy(update={"analysis_completion_status": "completed"})
    artifact_store.write_metadata(updated_metadata)
    print(json.dumps(evaluation.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
