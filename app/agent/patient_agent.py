from __future__ import annotations

from dataclasses import dataclass, field

from openai import OpenAI

from app.agent.prompts import build_patient_instructions
from app.agent.scenario_loader import Scenario
from app.agent.state import ConversationState


@dataclass(slots=True)
class PatientReply:
    text: str
    should_end_call: bool = False
    disclosed_facts: dict[str, str] = field(default_factory=dict)
    correction: str | None = None


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


class PatientAgent:
    def __init__(
        self,
        scenario: Scenario,
        state: ConversationState,
        llm_client: OpenAITextGenerationClient | None = None,
    ) -> None:
        self.scenario = scenario
        self.state = state
        self.llm_client = llm_client

    def opening_line(self) -> str:
        if self.scenario.facts.disclose_initially:
            return self.scenario.facts.disclose_initially[0]
        return f"Hi, I'm {self.scenario.patient.name}. I'm calling about {self.scenario.background.reason}."

    def reply_to_agent(self, agent_text: str) -> PatientReply:
        if self.llm_client is not None:
            return self._llm_reply(agent_text)
        return self._heuristic_reply(agent_text)

    def _llm_reply(self, agent_text: str) -> PatientReply:
        instructions = build_patient_instructions(self.scenario, self.state)
        text = self.llm_client.respond(
            instructions=instructions,
            prompt=f"Agent said: {agent_text}\nRespond as the patient.",
        )
        should_end = any(
            token in text.lower()
            for token in ("thank you, that's all", "thanks, that's all", "goodbye")
        )
        return PatientReply(text=text, should_end_call=should_end)

    def _heuristic_reply(self, agent_text: str) -> PatientReply:
        lower = agent_text.lower()
        disclosed: dict[str, str] = {}

        correction = self._correction_if_needed(lower)
        if correction is not None:
            self.state.register_correction(correction)
            return PatientReply(text=correction, correction=correction)

        if "name" in lower and "full" in lower:
            disclosed["name"] = self.scenario.patient.name
            if "date of birth" in lower or "dob" in lower:
                dob = self._fact("date_of_birth")
                if dob:
                    disclosed["date_of_birth"] = dob
                    return PatientReply(
                        text=f"It's {self.scenario.patient.name}, and my date of birth is {dob}.",
                        disclosed_facts=disclosed,
                    )
            return PatientReply(
                text=f"My name is {self.scenario.patient.name}.",
                disclosed_facts=disclosed,
            )

        if "date of birth" in lower or "dob" in lower:
            dob = self._fact("date_of_birth")
            if dob:
                disclosed["date_of_birth"] = dob
                return PatientReply(
                    text=f"My date of birth is {dob}.",
                    disclosed_facts=disclosed,
                )

        if "callback" in lower or "phone number" in lower or "best number" in lower:
            callback = self._fact("callback_number")
            if callback:
                disclosed["callback_number"] = callback
                return PatientReply(
                    text=f"You can reach me at {callback}.",
                    disclosed_facts=disclosed,
                )

        handler_name = f"_reply_{self.scenario.category}"
        handler = getattr(self, handler_name, self._reply_default)
        return handler(lower, disclosed)

    def _reply_default(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        del disclosed
        if "anything else" in lower or "can i help with anything else" in lower:
            self.state.mark_complete("goal_reached")
            return PatientReply(text="No, that covers it. Thank you so much.", should_end_call=True)
        return PatientReply(text="Okay, thank you.")

    def _reply_scheduling(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        if "what day" in lower or "next week" in lower:
            return PatientReply(text=f"Next {self._detail('preferred_day')} works well for me.")
        if "what time" in lower:
            return PatientReply(text=f"{self._detail('preferred_time')} would be great if you have it.")
        if "does that work" in lower or "scheduled" in lower:
            self.state.mark_complete("appointment_confirmed")
            return PatientReply(
                text="Yes, that works for me. Thank you.",
                should_end_call="anything else" in lower,
                disclosed_facts=disclosed,
            )
        return self._reply_default(lower, disclosed)

    def _reply_reschedule(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        if "current appointment" in lower or "existing appointment" in lower:
            return PatientReply(text=f"It's currently set for {self._detail('current_appointment')}.")
        if "new time" in lower or "what would you like instead" in lower:
            return PatientReply(text=f"I'm hoping for {self._detail('new_preference')}.")
        if "updated" in lower or "rescheduled" in lower:
            self.state.mark_complete("reschedule_confirmed")
            return PatientReply(text="Perfect, thank you.", should_end_call="anything else" in lower)
        return self._reply_default(lower, disclosed)

    def _reply_cancel(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        if "which appointment" in lower:
            return PatientReply(text=f"The one on {self._detail('appointment_to_cancel')}.")
        if "fee" in lower or "charge" in lower:
            return PatientReply(text="Thanks. Is there any cancellation fee I should know about?")
        if "cancelled" in lower or "canceled" in lower:
            self.state.mark_complete("cancellation_confirmed")
            return PatientReply(text="That answers it. Thank you.", should_end_call=True)
        return self._reply_default(lower, disclosed)

    def _reply_refill(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        if "medication" in lower or "which medicine" in lower:
            return PatientReply(text=f"It's for {self._detail('medication_name')}.")
        if "dose" in lower or "dosage" in lower:
            return PatientReply(text=f"I take {self._detail('dosage')}.")
        if "pharmacy" in lower:
            return PatientReply(text=f"The pharmacy is {self._detail('pharmacy_name')}.")
        if "clinician approval" in lower or "send a request" in lower:
            self.state.mark_complete("refill_request_submitted")
            return PatientReply(text="That makes sense. Thank you for helping with that.", should_end_call=True)
        return self._reply_default(lower, disclosed)

    def _reply_office_info(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        del disclosed
        if "how can i help" in lower:
            return PatientReply(
                text=(
                    "I wanted to check your office hours, location, parking, "
                    "and whether you're open on Friday."
                )
            )
        if "anything else" in lower:
            self.state.mark_complete("information_received")
            return PatientReply(text="No, that was everything. Thanks for the information.", should_end_call=True)
        return PatientReply(text="Okay, thanks.")

    def _reply_insurance(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        del disclosed
        if "which plan" in lower or "what insurance" in lower:
            return PatientReply(text=f"It's {self._detail('insurance_plan')}.")
        if "verify" in lower or "check with your insurer" in lower:
            self.state.mark_complete("insurance_guidance_received")
            return PatientReply(text="That helps. I'll double-check with them too. Thank you.", should_end_call=True)
        return PatientReply(text="Okay, thank you.")

    def _reply_weekend_edge(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        if "what day" in lower or "when are you hoping to come in" in lower:
            return PatientReply(text="Would Sunday around ten in the morning be possible?")
        if "closed" in lower or "weekday" in lower or "alternative" in lower:
            self.state.mark_complete("weekend_request_answered")
            return PatientReply(text="A weekday is fine then. Thank you for checking.", should_end_call=True)
        if "confirmed" in lower and "sunday" in lower:
            return PatientReply(text="Just to confirm, you really are open that Sunday?", disclosed_facts=disclosed)
        return self._reply_default(lower, disclosed)

    def _reply_ambiguous(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        del disclosed
        if "how can i help" in lower:
            return PatientReply(text="I need to come in soon because something feels wrong.")
        if "tell me more" in lower or "what's going on" in lower:
            return PatientReply(text="I've had a strange pressure feeling since yesterday and I'm not sure if I should be seen.")
        if "soonest" in lower or "next available" in lower or "nurse" in lower:
            self.state.mark_complete("urgency_triaged")
            return PatientReply(text="That would be helpful. Thank you.", should_end_call=True)
        return PatientReply(text="Sure.")

    def _reply_interruption(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        if "let me explain" in lower or len(lower.split()) > 18:
            return PatientReply(text="Sorry to cut in, but Tuesday morning is the main thing I need.")
        if "what time on tuesday" in lower:
            return PatientReply(text="Around nine thirty would be ideal.")
        if "confirmed" in lower:
            self.state.mark_complete("interruption_recovered")
            return PatientReply(text="Great, thank you.", should_end_call=True)
        return self._reply_default(lower, disclosed)

    def _reply_context_change(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        if "what day" in lower and "preferred_day" not in self.state.facts_disclosed:
            disclosed["preferred_day"] = self._detail("initial_day")
            return PatientReply(
                text=f"I was thinking {self._detail('initial_day')} at first.",
                disclosed_facts=disclosed,
            )
        if "what is the visit for" in lower:
            disclosed["visit_reason"] = self._detail("initial_reason")
            return PatientReply(
                text=f"It was for a {self._detail('initial_reason')}.",
                disclosed_facts=disclosed,
            )
        if "does that work" in lower and "change_requested" not in self.state.facts_disclosed:
            disclosed["change_requested"] = "yes"
            disclosed["preferred_day"] = self._detail("changed_day")
            disclosed["visit_reason"] = self._detail("changed_reason")
            return PatientReply(
                text=(
                    f"Actually, could we switch it to {self._detail('changed_day')}? "
                    f"And it's really for {self._detail('changed_reason')} instead."
                ),
                disclosed_facts=disclosed,
            )
        if "updated" in lower or "revised" in lower or "confirmed" in lower:
            self.state.mark_complete("context_change_applied")
            return PatientReply(text="Yes, that's the updated information. Thanks.", should_end_call=True)
        return self._reply_default(lower, disclosed)

    def _reply_safety_escalation(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        del disclosed
        if "what's going on" in lower or "tell me about your symptoms" in lower:
            return PatientReply(text="I've had pretty strong chest tightness for about twenty minutes and I feel shaky.")
        if "emergency" in lower or "911" in lower or "urgent care" in lower:
            self.state.mark_complete("safety_guidance_received")
            return PatientReply(text="Okay, I'll get help right away. Thank you.", should_end_call=True)
        return PatientReply(text="I'm mostly trying to figure out how quickly I need to be seen.")

    def _reply_repetition_recovery(self, lower: str, disclosed: dict[str, str]) -> PatientReply:
        if "name" in lower and "maria" in lower:
            correction = f"It's {self.scenario.patient.name}, not Maria."
            self.state.register_correction(correction)
            return PatientReply(text=correction, correction=correction)
        if "date" in lower and self._detail("wrong_requested_day").lower() in lower:
            correction = f"Sorry, I meant {self._detail('correct_requested_day')}."
            self.state.register_correction(correction)
            return PatientReply(text=correction, correction=correction)
        if "confirmed" in lower and self._detail("correct_requested_day").lower() in lower:
            self.state.mark_complete("correction_retained")
            return PatientReply(text="Yes, that's the correct day. Thank you.", should_end_call=True)
        if "what day" in lower:
            return PatientReply(text=f"{self._detail('correct_requested_day')} works best for me.")
        return self._reply_default(lower, disclosed)

    def _detail(self, key: str) -> str:
        return str(self.scenario.background.details.get(key, ""))

    def _fact(self, key: str) -> str | None:
        return self.scenario.facts.disclose_if_asked.get(key)

    def _correction_if_needed(self, lower: str) -> str | None:
        if self.scenario.patient.name.lower() not in lower and "maria" in lower:
            return f"It's {self.scenario.patient.name}, actually."

        wrong_day = self.scenario.background.details.get("wrong_requested_day")
        correct_day = self.scenario.background.details.get("correct_requested_day")
        if wrong_day and correct_day and str(wrong_day).lower() in lower:
            return f"Just to correct that, I asked for {correct_day}."
        return None

