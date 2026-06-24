from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.scenario_loader import load_scenario
from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.telephony.preflight import build_live_call_preflight


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live-call preflight checks.")
    parser.add_argument("--scenario", required=True, help="Path to the scenario YAML.")
    parser.add_argument("--call-id", help="Optional preview call id to validate.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    scenario = load_scenario(args.scenario)
    call_id = args.call_id or artifact_store.next_call_id()
    report = build_live_call_preflight(
        settings=settings,
        scenario=scenario,
        artifact_store=artifact_store,
        call_id=call_id,
    )
    print(report.render_text())
    if not report.ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
