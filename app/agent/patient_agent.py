from __future__ import annotations

from dataclasses import dataclass, field
import time

from openai import OpenAI

from app.agent.planner import AdaptiveScenarioPlanner, PatientActionPlan
from app.agent.prompts import build_patient_instructions
from app.agent.scenario_loader import Scenario
from app.agent.state import ConversationState


@dataclass(slots=True)
class PatientReply:
    text: str
    action: str
    reason: str
    scenario_goal_progress: float
    llm_latency_ms: float | None = None
    should_end_call: bool = False
    disclosed_facts: dict[str, str] = field(default_factory=dict)
    correction: str | None = None
    allow_overlap: bool = False


class OpenAITextGenerationClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def respond(self, instructions: str, prompt: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=prompt,
        )
        return response.output_text.strip()

    def refine_response(
        self,
        *,
        instructions: str,
        draft_utterance: str,
        action: str,
        reason: str,
    ) -> str:
        prompt = (
            "Rewrite the draft patient line so it sounds natural on a phone call. "
            "Keep all facts unchanged, keep it to one or two short sentences, and "
            "do not add new medical or personal details.\n\n"
            f"Action: {action}\n"
            f"Reason: {reason}\n"
            f"Draft: {draft_utterance}"
        )
        return self.respond(instructions=instructions, prompt=prompt)


class PatientAgent:
    def __init__(
        self,
        scenario: Scenario,
        state: ConversationState,
        llm_client: OpenAITextGenerationClient | None = None,
        *,
        response_style: str = "concise",
    ) -> None:
        self.scenario = scenario
        self.state = state
        self.llm_client = llm_client
        self.response_style = response_style
        self.planner = AdaptiveScenarioPlanner(scenario, state)

    def opening_line(self) -> str:
        opening = self.planner.opening_plan()
        self.state.register_action(opening.action.value, opening.scenario_goal_progress)
        return opening.utterance

    def reply_to_agent(self, agent_text: str) -> PatientReply:
        plan = self.planner.plan_from_agent_turn(agent_text)
        return self._reply_from_plan(plan)

    def maybe_interrupt_ongoing_agent_turn(self, elapsed_ms: int) -> PatientReply | None:
        plan = self.planner.plan_unsolicited_interrupt(elapsed_ms)
        if plan is None:
            return None
        return self._reply_from_plan(plan)

    def _reply_from_plan(self, plan: PatientActionPlan) -> PatientReply:
        self.state.register_action(plan.action.value, plan.scenario_goal_progress)
        if plan.correction:
            self.state.register_correction(plan.correction)
        if plan.should_end_call:
            self.state.mark_complete("goal_reached")

        text, llm_latency_ms = self._render_utterance(plan)
        return PatientReply(
            text=text,
            action=plan.action.value,
            reason=plan.reason,
            scenario_goal_progress=plan.scenario_goal_progress,
            llm_latency_ms=llm_latency_ms,
            should_end_call=plan.should_end_call,
            disclosed_facts=plan.disclosed_facts,
            correction=plan.correction,
            allow_overlap=plan.allow_overlap,
        )

    def _render_utterance(self, plan: PatientActionPlan) -> tuple[str, float | None]:
        text = self._apply_response_style(plan.utterance)
        if self.llm_client is None:
            return text, None
        instructions = build_patient_instructions(self.scenario, self.state)
        started = time.perf_counter()
        refined = self.llm_client.refine_response(
            instructions=instructions,
            draft_utterance=text,
            action=plan.action.value,
            reason=plan.reason,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        return self._apply_response_style(refined), latency_ms

    def _apply_response_style(self, text: str) -> str:
        cleaned = " ".join(text.split())
        if self.response_style == "verbose":
            if cleaned.endswith("?"):
                return cleaned[:-1] + ", if that helps?"
            if cleaned.endswith("."):
                return cleaned[:-1] + ", if that works on your side."
            return cleaned + ", if that helps."
        if self.response_style != "concise":
            return cleaned
        sentences = [sentence.strip() for sentence in cleaned.split(".") if sentence.strip()]
        trimmed = ". ".join(sentences[:2])
        if cleaned.endswith("?") and not trimmed.endswith("?"):
            return trimmed + "?"
        if cleaned.endswith("!") and not trimmed.endswith("!"):
            return trimmed + "!"
        if trimmed and trimmed[-1].isalnum():
            return trimmed + "."
        return trimmed or cleaned
