from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.analysis.bug_reporter import build_bug_report, review_issues
from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review evaluations and build BUG_REPORT.md.")
    parser.add_argument(
        "--review",
        action="store_true",
        help="Interactively approve, edit, or reject detected issues first.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    evaluations = artifact_store.list_evaluations()
    metadata_by_call = {
        path.stem: CallMetadata.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(artifact_store.metadata_dir.glob("*.json"))
    }
    if args.review:
        review_issues(evaluations)
        for evaluation in evaluations:
            artifact_store.write_evaluation(evaluation)

    report = build_bug_report(
        evaluations,
        metadata_by_call,
        settings.project_root / "BUG_REPORT.md",
        include_pending=not args.review,
    )
    print(report)


if __name__ == "__main__":
    main()
