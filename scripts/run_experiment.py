from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.experiments.runner import ExperimentRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a dry-run A/B experiment.")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the experiment YAML config.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    runner = ExperimentRunner(settings)
    config = runner.load_config(Path(args.config))
    results = runner.run(config)
    json_path, md_path = runner.write_results(config, results)
    print(
        json.dumps(
            {
                "results_json": str(json_path),
                "results_md": str(md_path),
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
