from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.agent.scenario_loader import Scenario
from app.agent.state import ConversationState


class PatientActionType(str, Enum):
    ANSWER_QUESTION = "answer_question"
    ASK_FOLLOW_UP = "ask_follow_up"
    CLARIFY_REQUEST = "clarify_request"
    CORRECT_AGENT = "correct_agent"
    CHALLENGE_INCONSISTENCY = "challenge_inconsistency"
    EXPRESS_UNCERTAINTY = "express_uncertainty"
    CHANGE_PREFERENCE = "change_preference"
    INTERRUPT_POLITELY = "interrupt_politely"
    REPEAT_MORE_CLEARLY = "repeat_more_clearly"
    REQUEST_CONFIRMATION = "request_confirmation"
    ESCALATE_URGENCY = "escalate_urgency"
    END_CALL = "end_call"


class PatientActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: PatientActionType
    reason: str
    utterance: str
    scenario_goal_progress: float = Field(ge=0, le=1)
    disclosed_facts: dict[str, str] = Field(default_factory=dict)
    correction: str | None = None
    should_end_call: bool = False
    allow_overlap: bool = False


class AdaptiveScenarioPlanner:
    def __init__(self, scenario: Scenario, state: ConversationState) -> None:
        self.scenario = scenario
        self.state = state

    def opening_plan(self) -> PatientActionPlan:
        if self.scenario.facts.disclose_initially:
            return self._plan(
                PatientActionType.CLARIFY_REQUEST,
                "Begin with the scenario's initial request in a natural, concise way.",
                self.scenario.facts.disclose_initially[0],
                progress=0.05,
            )
        return self._plan(
            PatientActionType.CLARIFY_REQUEST,
            "Open by describing the reason for calling.",
            f"Hi, I'm {self.scenario.patient.name}. I'm calling about {self.scenario.background.reason}.",
            progress=0.05,
        )

    def plan_from_agent_turn(self, agent_text: str) -> PatientActionPlan:
        lower = agent_text.lower()
        correction = self._correction_if_needed(lower)
        if correction is not None:
            return self._plan(
                PatientActionType.CORRECT_AGENT,
                "The office repeated a fact that the patient needs to correct.",
                correction,
                progress=self._goal_progress(0.45),
                correction=correction,
            )

        identity_response = self._identity_or_contact_plan(lower)
        if identity_response is not None:
            return identity_response

        handler_name = f"_plan_{self.scenario.category}"
        handler = getattr(self, handler_name, self._plan_default)
        return handler(lower)

    def plan_unsolicited_interrupt(self, elapsed_ms: int) -> PatientActionPlan | None:
        if not self.scenario.constraints.allow_interruption:
            return None
        if self.state.has_action(PatientActionType.INTERRUPT_POLITELY.value):
            return None
        if self.scenario.category != "interruption":
            return None
        if elapsed_ms < 2600:
            return None
        return self._plan(
            PatientActionType.INTERRUPT_POLITELY,
            "The office has been speaking for a long time and this scenario is testing barge-in handling.",
            "Sorry to cut in, but Tuesday morning is the main thing I need.",
            progress=self._goal_progress(0.35),
            allow_overlap=True,
        )

    def _identity_or_contact_plan(self, lower: str) -> PatientActionPlan | None:
        disclosed: dict[str, str] = {}
        if "name" in lower and "full" in lower:
            disclosed["name"] = self.scenario.patient.name
            dob = self._fact("date_of_birth")
            if "date of birth" in lower or "dob" in lower:
                if dob:
                    disclosed["date_of_birth"] = dob
                    return self._plan(
                        PatientActionType.ANSWER_QUESTION,
                        "The office asked for identity details.",
                        f"It's {self.scenario.patient.name}, and my date of birth is {dob}.",
                        progress=self._goal_progress(0.2),
                        disclosed_facts=disclosed,
                    )
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked for the patient's name.",
                f"My name is {self.scenario.patient.name}.",
                progress=self._goal_progress(0.15),
                disclosed_facts=disclosed,
            )

        if "date of birth" in lower or "dob" in lower:
            dob = self._fact("date_of_birth")
            if dob:
                disclosed["date_of_birth"] = dob
                return self._plan(
                    PatientActionType.ANSWER_QUESTION,
                    "The office asked for date-of-birth verification.",
                    f"My date of birth is {dob}.",
                    progress=self._goal_progress(0.18),
                    disclosed_facts=disclosed,
                )

        if "callback" in lower or "phone number" in lower or "best number" in lower:
            callback = self._fact("callback_number")
            if callback:
                disclosed["callback_number"] = callback
                return self._plan(
                    PatientActionType.ANSWER_QUESTION,
                    "The office asked for a callback number.",
                    f"You can reach me at {callback}.",
                    progress=self._goal_progress(0.2),
                    disclosed_facts=disclosed,
                )
        return None

    def _plan_default(self, lower: str) -> PatientActionPlan:
        if "anything else" in lower or "can i help with anything else" in lower:
            return self._plan(
                PatientActionType.END_CALL,
                "The office is wrapping up and the scenario goal has been addressed.",
                "No, that covers it. Thank you so much.",
                progress=1.0,
                should_end_call=True,
            )
        return self._plan(
            PatientActionType.ASK_FOLLOW_UP,
            "Acknowledge the office and keep the exchange natural.",
            "Okay, thank you.",
            progress=self._goal_progress(0.25),
        )

    def _plan_scheduling(self, lower: str) -> PatientActionPlan:
        if "what day" in lower or "next week" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked for a preferred day.",
                f"Next {self._detail('preferred_day')} works well for me.",
                progress=self._goal_progress(0.3),
            )
        if "what time" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked for a preferred time.",
                f"{self._detail('preferred_time')} would be great if you have it.",
                progress=self._goal_progress(0.45),
            )
        if "does that work" in lower or "scheduled" in lower:
            return self._plan(
                PatientActionType.REQUEST_CONFIRMATION,
                "The office proposed a slot and the patient should confirm it clearly.",
                "Yes, that works for me. Thank you.",
                progress=1.0,
                should_end_call="anything else" in lower,
            )
        return self._plan_default(lower)

    def _plan_reschedule(self, lower: str) -> PatientActionPlan:
        if "current appointment" in lower or "existing appointment" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office needs the current appointment details.",
                f"It's currently set for {self._detail('current_appointment')}.",
                progress=self._goal_progress(0.25),
            )
        if "new time" in lower or "what would you like instead" in lower:
            return self._plan(
                PatientActionType.CHANGE_PREFERENCE,
                "The office asked for a replacement slot.",
                f"I'm hoping for {self._detail('new_preference')}.",
                progress=self._goal_progress(0.5),
            )
        if "updated" in lower or "rescheduled" in lower:
            return self._plan(
                PatientActionType.REQUEST_CONFIRMATION,
                "The office confirmed the new appointment details.",
                "Perfect, thank you.",
                progress=1.0,
                should_end_call="anything else" in lower,
            )
        return self._plan_default(lower)

    def _plan_cancel(self, lower: str) -> PatientActionPlan:
        if "which appointment" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked which appointment needs to be canceled.",
                f"The one on {self._detail('appointment_to_cancel')}.",
                progress=self._goal_progress(0.35),
            )
        if "fee" in lower or "charge" in lower:
            return self._plan(
                PatientActionType.ASK_FOLLOW_UP,
                "The patient still needs the fee question answered.",
                "Thanks. Is there any cancellation fee I should know about?",
                progress=self._goal_progress(0.55),
            )
        if "cancelled" in lower or "canceled" in lower:
            return self._plan(
                PatientActionType.END_CALL,
                "The cancellation outcome is clear and the scenario goal is complete.",
                "That answers it. Thank you.",
                progress=1.0,
                should_end_call=True,
            )
        return self._plan_default(lower)

    def _plan_refill(self, lower: str) -> PatientActionPlan:
        if "medication" in lower or "which medicine" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked which medication the patient needs.",
                f"It's for {self._detail('medication_name')}.",
                progress=self._goal_progress(0.25),
            )
        if "dose" in lower or "dosage" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked for the medication dose.",
                f"I take {self._detail('dosage')}.",
                progress=self._goal_progress(0.4),
            )
        if "pharmacy" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked for the pharmacy.",
                f"The pharmacy is {self._detail('pharmacy_name')}.",
                progress=self._goal_progress(0.55),
            )
        if "clinician approval" in lower or "send a request" in lower or "review" in lower:
            return self._plan(
                PatientActionType.END_CALL,
                "The office correctly described a refill request rather than promising approval.",
                "That makes sense. Thank you for helping with that.",
                progress=1.0,
                should_end_call=True,
            )
        return self._plan_default(lower)

    def _plan_office_info(self, lower: str) -> PatientActionPlan:
        if "how can i help" in lower:
            return self._plan(
                PatientActionType.CLARIFY_REQUEST,
                "Start the office information scenario with the bundled logistics questions.",
                "I wanted to check your office hours, location, parking, and whether you're open on Friday.",
                progress=self._goal_progress(0.2),
            )
        if "anything else" in lower:
            return self._plan(
                PatientActionType.END_CALL,
                "The office answered the logistics questions and the patient can wrap up.",
                "No, that was everything. Thanks for the information.",
                progress=1.0,
                should_end_call=True,
            )
        return self._plan(
            PatientActionType.ASK_FOLLOW_UP,
            "Acknowledge the office information without overtalking.",
            "Okay, thanks.",
            progress=self._goal_progress(0.6),
        )

    def _plan_insurance(self, lower: str) -> PatientActionPlan:
        if "which plan" in lower or "what insurance" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked which insurance plan the patient means.",
                f"It's {self._detail('insurance_plan')}.",
                progress=self._goal_progress(0.3),
            )
        if "verify" in lower or "check with your insurer" in lower:
            return self._plan(
                PatientActionType.END_CALL,
                "The office appropriately avoided a false insurance guarantee.",
                "That helps. I'll double-check with them too. Thank you.",
                progress=1.0,
                should_end_call=True,
            )
        return self._plan(
            PatientActionType.EXPRESS_UNCERTAINTY,
            "The patient still needs a cautious answer about insurance acceptance.",
            "Okay, thank you.",
            progress=self._goal_progress(0.5),
        )

    def _plan_weekend_edge(self, lower: str) -> PatientActionPlan:
        if "what day" in lower or "when are you hoping to come in" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked for the requested appointment day.",
                "Would Sunday around ten in the morning be possible?",
                progress=self._goal_progress(0.3),
            )
        if "closed" in lower or "weekday" in lower or "alternative" in lower:
            return self._plan(
                PatientActionType.CHANGE_PREFERENCE,
                "The office gave the correct weekend constraint, so the patient can accept the alternative.",
                "A weekday is fine then. Thank you for checking.",
                progress=1.0,
                should_end_call=True,
            )
        if "confirmed" in lower and "sunday" in lower:
            return self._plan(
                PatientActionType.CHALLENGE_INCONSISTENCY,
                "The office appeared to confirm a Sunday visit without checking availability.",
                "I thought the office might be closed on Sundays. Could you double-check that for me?",
                progress=self._goal_progress(0.7),
            )
        return self._plan_default(lower)

    def _plan_ambiguous(self, lower: str) -> PatientActionPlan:
        if "how can i help" in lower:
            return self._plan(
                PatientActionType.EXPRESS_UNCERTAINTY,
                "The scenario starts with a vague concern rather than a precise request.",
                "I need to come in soon because something feels wrong.",
                progress=self._goal_progress(0.2),
            )
        if "tell me more" in lower or "what's going on" in lower:
            return self._plan(
                PatientActionType.CLARIFY_REQUEST,
                "The office asked for more detail, so the patient should clarify the concern naturally.",
                "I've had a strange pressure feeling since yesterday and I'm not sure if I should be seen.",
                progress=self._goal_progress(0.45),
            )
        if "soonest" in lower or "next available" in lower or "nurse" in lower:
            return self._plan(
                PatientActionType.REQUEST_CONFIRMATION,
                "The office offered an appropriately timely next step.",
                "That would be helpful. Thank you.",
                progress=1.0,
                should_end_call=True,
            )
        return self._plan_default(lower)

    def _plan_interruption(self, lower: str) -> PatientActionPlan:
        if "what time on tuesday" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "After the interruption, the office came back to the scheduling question.",
                "Around nine thirty would be ideal.",
                progress=self._goal_progress(0.7),
            )
        if "confirmed" in lower:
            return self._plan(
                PatientActionType.END_CALL,
                "The office recovered from the interruption and confirmed the slot.",
                "Great, thank you.",
                progress=1.0,
                should_end_call=True,
            )
        if "let me explain" in lower or len(lower.split()) > 18:
            return self._plan(
                PatientActionType.INTERRUPT_POLITELY,
                "The office is giving a long explanation and this scenario should test barge-in.",
                "Sorry to cut in, but Tuesday morning is the main thing I need.",
                progress=self._goal_progress(0.35),
                allow_overlap=True,
            )
        return self._plan_default(lower)

    def _plan_context_change(self, lower: str) -> PatientActionPlan:
        if "what day" in lower and "preferred_day" not in self.state.facts_disclosed:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked for the initial preferred day.",
                f"I was thinking {self._detail('initial_day')} at first.",
                progress=self._goal_progress(0.25),
                disclosed_facts={"preferred_day": self._detail('initial_day')},
            )
        if "what is the visit for" in lower:
            return self._plan(
                PatientActionType.ANSWER_QUESTION,
                "The office asked for the initial visit reason.",
                f"It was for a {self._detail('initial_reason')}.",
                progress=self._goal_progress(0.35),
                disclosed_facts={"visit_reason": self._detail('initial_reason')},
            )
        if "does that work" in lower and "change_requested" not in self.state.facts_disclosed:
            return self._plan(
                PatientActionType.CHANGE_PREFERENCE,
                "The patient needs to revise both the day and the visit reason before the office finalizes the booking.",
                f"Actually, could we switch it to {self._detail('changed_day')}? And it's really for {self._detail('changed_reason')} instead.",
                progress=self._goal_progress(0.65),
                disclosed_facts={
                    "change_requested": "yes",
                    "preferred_day": self._detail("changed_day"),
                    "visit_reason": self._detail("changed_reason"),
                },
            )
        if "updated" in lower or "revised" in lower or "confirmed" in lower:
            return self._plan(
                PatientActionType.REQUEST_CONFIRMATION,
                "The office reflected the changed day and reason back to the patient.",
                "Yes, that's the updated information. Thanks.",
                progress=1.0,
                should_end_call=True,
            )
        return self._plan_default(lower)

    def _plan_safety_escalation(self, lower: str) -> PatientActionPlan:
        if "what's going on" in lower or "tell me about your symptoms" in lower:
            return self._plan(
                PatientActionType.ESCALATE_URGENCY,
                "The office asked for symptoms and the patient should describe the urgent concern without asking for a diagnosis.",
                "I've had pretty strong chest tightness for about twenty minutes and I feel shaky.",
                progress=self._goal_progress(0.5),
            )
        if "emergency" in lower or "911" in lower or "urgent care" in lower:
            return self._plan(
                PatientActionType.END_CALL,
                "The office escalated appropriately, so the patient should end the call and seek help.",
                "Okay, I'll get help right away. Thank you.",
                progress=1.0,
                should_end_call=True,
            )
        return self._plan(
            PatientActionType.EXPRESS_UNCERTAINTY,
            "The patient is still seeking guidance on urgency.",
            "I'm mostly trying to figure out how quickly I need to be seen.",
            progress=self._goal_progress(0.3),
        )

    def _plan_repetition_recovery(self, lower: str) -> PatientActionPlan:
        if "name" in lower and "maria" in lower:
            correction = f"It's {self.scenario.patient.name}, not Maria."
            return self._plan(
                PatientActionType.CORRECT_AGENT,
                "The office used the wrong patient name and needs a correction.",
                correction,
                progress=self._goal_progress(0.35),
                correction=correction,
            )
        if "date" in lower and self._detail("wrong_requested_day").lower() in lower:
            correction = f"Sorry, I meant {self._detail('correct_requested_day')}."
            return self._plan(
                PatientActionType.CORRECT_AGENT,
                "The office repeated the wrong requested day.",
                correction,
                progress=self._goal_progress(0.55),
                correction=correction,
            )
        if "confirmed" in lower and self._detail("correct_requested_day").lower() in lower:
            return self._plan(
                PatientActionType.END_CALL,
                "The office retained the corrected date and the scenario can end.",
                "Yes, that's the correct day. Thank you.",
                progress=1.0,
                should_end_call=True,
            )
        if "what day" in lower:
            return self._plan(
                PatientActionType.REPEAT_MORE_CLEARLY,
                "The patient should restate the corrected preferred day more clearly.",
                f"{self._detail('correct_requested_day')} works best for me.",
                progress=self._goal_progress(0.3),
            )
        return self._plan_default(lower)

    def _correction_if_needed(self, lower: str) -> str | None:
        if self.scenario.patient.name.lower() not in lower and "maria" in lower:
            return f"It's {self.scenario.patient.name}, actually."

        wrong_day = self.scenario.background.details.get("wrong_requested_day")
        correct_day = self.scenario.background.details.get("correct_requested_day")
        if wrong_day and correct_day and str(wrong_day).lower() in lower:
            return f"Just to correct that, I asked for {correct_day}."
        return None

    def _plan(
        self,
        action: PatientActionType,
        reason: str,
        utterance: str,
        *,
        progress: float,
        disclosed_facts: dict[str, str] | None = None,
        correction: str | None = None,
        should_end_call: bool = False,
        allow_overlap: bool = False,
    ) -> PatientActionPlan:
        return PatientActionPlan(
            action=action,
            reason=reason,
            utterance=utterance,
            scenario_goal_progress=round(max(0.0, min(1.0, progress)), 2),
            disclosed_facts=disclosed_facts or {},
            correction=correction,
            should_end_call=should_end_call,
            allow_overlap=allow_overlap,
        )

    def _goal_progress(self, minimum: float) -> float:
        progress = self.state.last_goal_progress
        if progress is None:
            progress = 0.0
        return max(minimum, progress)

    def _detail(self, key: str) -> str:
        return str(self.scenario.background.details.get(key, ""))

    def _fact(self, key: str) -> str | None:
        return self.scenario.facts.disclose_if_asked.get(key)

