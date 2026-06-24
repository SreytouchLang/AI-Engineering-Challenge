from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.scenario_loader import load_scenario, load_scenarios
from app.agent.state import ConversationState
from app.config import get_settings


def test_repository_includes_twelve_scenarios() -> None:
    scenarios = load_scenarios(get_settings().project_root / "scenarios")
    assert len(scenarios) >= 12


def test_invalid_scenario_ids_are_rejected(tmp_path: Path) -> None:
    scenario_path = tmp_path / "bad.yaml"
    scenario_path.write_text(
        """
id: Bad-Scenario
title: Bad
category: scheduling
patient:
  name: Test
  tone: calm
background:
  reason: test
  details: {}
goal:
  primary: test
facts:
  disclose_initially: []
  disclose_if_asked: {}
  withhold_until_needed: []
constraints:
  max_duration_seconds: 180
  allow_interruption: false
  max_turns: 10
evaluation:
  high_severity_failures: []
  medium_severity_failures: []
  success_signals: []
desired_outcome: test
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_scenario(scenario_path)


def test_patient_identity_cannot_change_mid_conversation() -> None:
    state = ConversationState(
        scenario_id="demo",
        call_id="call-001",
        patient_name="Maya Thompson",
        current_goal="demo",
    )
    with pytest.raises(ValueError):
        state.ensure_identity_consistency("Other Name")
