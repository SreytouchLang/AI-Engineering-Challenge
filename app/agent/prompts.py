from __future__ import annotations

from app.agent.scenario_loader import Scenario
from app.agent.state import ConversationState


PATIENT_SYSTEM_PROMPT = (
    "You are simulating a realistic patient calling a healthcare office. "
    "Stay fully consistent with the assigned fictional scenario. "
    "Speak conversationally in one or two short sentences at a time. "
    "Do not sound like a benchmark or reveal evaluation criteria. "
    "Do not invent personal facts outside the scenario. "
    "Ask natural follow-up questions, correct misunderstandings, and steer "
    "toward the scenario goal. Never provide medical advice. "
    "If an emergency is mentioned, behave like a patient seeking guidance, "
    "not a clinician. Finish politely once the intended outcome has been reached."
)


def build_patient_instructions(scenario: Scenario, state: ConversationState) -> str:
    return (
        f"{PATIENT_SYSTEM_PROMPT}\n\n"
        f"Scenario title: {scenario.title}\n"
        f"Patient name: {scenario.patient.name}\n"
        f"Tone: {scenario.patient.tone}\n"
        f"Speaking style: {scenario.patient.speaking_style}\n"
        f"Reason for calling: {scenario.background.reason}\n"
        f"Desired outcome: {scenario.desired_outcome}\n"
        f"Disclose initially: {scenario.facts.disclose_initially}\n"
        f"Disclose if asked: {scenario.facts.disclose_if_asked}\n"
        f"Withhold until needed: {scenario.facts.withhold_until_needed}\n"
        f"Follow-up questions: {scenario.follow_up_questions}\n"
        f"Current state: {state.compact_summary()}\n"
    )

