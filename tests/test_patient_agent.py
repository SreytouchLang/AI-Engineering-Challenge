from __future__ import annotations

from app.agent.patient_agent import PatientAgent
from app.agent.scenario_loader import load_scenario
from app.agent.state import ConversationState
from app.config import get_settings


def test_patient_agent_concise_style_limits_to_two_sentences() -> None:
    scenario = load_scenario(get_settings().project_root / "scenarios" / "01_simple_scheduling.yaml")
    state = ConversationState(
        scenario_id=scenario.id,
        call_id="call-001",
        patient_name=scenario.patient.name,
        current_goal=scenario.goal.primary,
    )
    agent = PatientAgent(scenario, state, response_style="concise")

    rendered = agent._apply_response_style("First sentence. Second sentence. Third sentence.")

    assert rendered == "First sentence. Second sentence."
