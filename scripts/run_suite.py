from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.dry_run import DryRunConversationRunner
from app.agent.scenario_loader import load_scenarios
from app.config import get_settings
from app.storage.artifacts import ArtifactStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the dry-run scenario suite.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for the number of scenarios to execute.",
    )
    return parser.parse_args()


def next_call_id(artifact_store: ArtifactStore, index: int) -> str:
    return f"call-{index:03d}"


def main() -> None:
    args = parse_args()
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    scenarios = load_scenarios(settings.project_root / "scenarios")
    if args.limit is not None:
        scenarios = scenarios[: args.limit]

    results: list[dict[str, str]] = []
    for index, scenario in enumerate(scenarios, start=1):
        call_id = next_call_id(artifact_store, index)
        while artifact_store.paths_for(call_id).metadata_json.exists():
            index += 1
            call_id = next_call_id(artifact_store, index)
        artifact_store.reserve_call_id(call_id)
        result = DryRunConversationRunner(settings, scenario).run(call_id=call_id)
        transcript_paths = artifact_store.write_transcript(result.transcript)
        metadata = result.metadata.model_copy(
            update={"transcript_path": f"artifacts/transcripts/{call_id}.txt"}
        )
        artifact_store.write_metadata(metadata)
        results.append(
            {
                "call_id": call_id,
                "scenario_id": scenario.id,
                "transcript": str(transcript_paths.transcript_text),
            }
        )

    print(json.dumps({"completed": len(results), "results": results}, indent=2))


if __name__ == "__main__":
    main()
