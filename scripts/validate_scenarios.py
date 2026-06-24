from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.scenario_loader import load_scenarios
from app.config import get_settings

REQUIRED_CATEGORIES = {
    "scheduling",
    "reschedule",
    "cancel",
    "refill",
    "office_info",
    "insurance",
    "weekend_edge",
    "ambiguous",
    "interruption",
    "context_change",
    "repetition_recovery",
    "safety_escalation",
}


def main() -> None:
    settings = get_settings()
    scenarios = load_scenarios(settings.project_root / "scenarios")
    issues: list[str] = []
    categories = {scenario.category for scenario in scenarios}

    if len(scenarios) < 12:
        issues.append(f"Expected at least 12 scenarios, found {len(scenarios)}.")

    missing_categories = sorted(REQUIRED_CATEGORIES - categories)
    if missing_categories:
        issues.append(f"Missing required scenario categories: {', '.join(missing_categories)}")

    for scenario in scenarios:
        if not scenario.patient.name.strip():
            issues.append(f"{scenario.id}: patient name is missing.")
        if not scenario.patient.tone.strip():
            issues.append(f"{scenario.id}: emotional tone is missing.")
        if not scenario.background.reason.strip():
            issues.append(f"{scenario.id}: reason for calling is missing.")
        if not scenario.facts.disclose_initially:
            issues.append(f"{scenario.id}: initial facts are missing.")
        if not scenario.goal.acceptable_outcomes:
            issues.append(f"{scenario.id}: acceptable outcomes are missing.")
        if not scenario.follow_up_questions:
            issues.append(f"{scenario.id}: follow-up questions are missing.")
        if not scenario.desired_outcome.strip():
            issues.append(f"{scenario.id}: desired outcome is missing.")
        if not scenario.failure_signals:
            issues.append(f"{scenario.id}: meaningful failure signals are missing.")
        if not scenario.evaluation.success_signals:
            issues.append(f"{scenario.id}: success criteria are missing.")
        if not scenario.evaluation.high_severity_failures:
            issues.append(f"{scenario.id}: high-severity failure examples are missing.")
        if scenario.constraints.max_duration_seconds <= 0:
            issues.append(f"{scenario.id}: maximum duration must be positive.")
        if scenario.constraints.max_turns <= 0:
            issues.append(f"{scenario.id}: maximum turns must be positive.")
        if scenario.category == "interruption" and not scenario.constraints.allow_interruption:
            issues.append(f"{scenario.id}: interruption scenarios must allow interruption.")
        if scenario.category == "office_info":
            details = scenario.background.details
            if not any(key in details for key in ("address", "parking", "hours")):
                issues.append(f"{scenario.id}: office-info scenarios should include location, parking, or hours details.")

    result = {
        "scenario_count": len(scenarios),
        "categories": sorted(categories),
        "issues": issues,
    }
    print(json.dumps(result, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
