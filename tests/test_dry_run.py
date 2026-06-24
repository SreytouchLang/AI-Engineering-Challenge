from __future__ import annotations

from pathlib import Path

from app.agent.dry_run import DryRunConversationRunner
from app.agent.scenario_loader import load_scenario, load_scenarios
from app.config import AppSettings, get_settings


def test_dry_run_generates_both_speakers_for_every_scenario() -> None:
    settings = AppSettings()
    for scenario in load_scenarios(get_settings().project_root / "scenarios"):
        result = DryRunConversationRunner(settings, scenario).run(call_id=f"dry-{scenario.id}")
        speakers = {segment.speaker for segment in result.transcript.segments}
        assert {"PATIENT", "AGENT"} <= speakers
        assert result.transcript.duration_seconds <= scenario.constraints.max_duration_seconds


def test_context_change_flow_keeps_updated_reason_and_day() -> None:
    scenario = load_scenario(
        get_settings().project_root / "scenarios" / "10_context_change.yaml"
    )
    result = DryRunConversationRunner(AppSettings(), scenario).run(call_id="call-010")
    rendered = result.transcript.render_text().lower()
    assert "wednesday, july 16 at 2:00 pm" in rendered
    assert "knee pain" in rendered


def test_repetition_recovery_retains_corrected_day_and_name() -> None:
    scenario = load_scenario(
        get_settings().project_root / "scenarios" / "12_repetition_recovery.yaml"
    )
    result = DryRunConversationRunner(AppSettings(), scenario).run(call_id="call-012")
    rendered = result.transcript.render_text().lower()
    assert "camille ross" in rendered
    assert "tuesday" in rendered
    assert "maria" in rendered

