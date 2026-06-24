from __future__ import annotations

import re

from app.agent.scenario_loader import Scenario
from app.analysis.schemas import (
    CallEvaluation,
    EvaluationIssue,
    EvaluationScores,
    Severity,
)
from app.analysis.transcript import TranscriptDocument, TranscriptSegment, format_segment_timestamp


class ConversationEvaluator:
    def evaluate(self, scenario: Scenario, transcript: TranscriptDocument) -> CallEvaluation:
        transcript.require_agent_turns()
        issues: list[EvaluationIssue] = []

        agent_segments = [segment for segment in transcript.segments if segment.speaker == "AGENT"]
        patient_segments = [segment for segment in transcript.segments if segment.speaker == "PATIENT"]
        last_agent = agent_segments[-1]

        if transcript.duration_seconds > scenario.constraints.max_duration_seconds:
            issues.append(
                self._issue(
                    severity=Severity.MEDIUM,
                    category="workflow",
                    title="Call exceeded configured duration",
                    segment=transcript.segments[-1],
                    expected_behavior="End the call before the configured maximum duration.",
                    user_impact="Long calls increase cost and create an unnatural experience.",
                )
            )

        repeated = self._find_repetition(agent_segments)
        if repeated is not None:
            issues.append(repeated)

        if self._requires_final_confirmation(scenario) and not self._has_clear_confirmation(
            agent_segments
        ):
            issues.append(
                self._issue(
                    severity=Severity.MEDIUM,
                    category="workflow",
                    title="Call ended without a clear final confirmation",
                    segment=last_agent,
                    expected_behavior="Summarize the final outcome before ending the call.",
                    user_impact="The patient may leave unsure whether the requested action was completed.",
                )
            )

        issues.extend(self._scenario_specific_checks(scenario, transcript))
        scores = self._score(issues)

        return CallEvaluation(
            call_id=transcript.call_id,
            scenario_id=scenario.id,
            summary=self._summary(issues, last_agent.text),
            scenario_completed=not any(issue.severity == Severity.CRITICAL for issue in issues),
            agent_outcome=last_agent.text,
            expected_outcome=scenario.desired_outcome,
            scores=scores,
            issues=issues,
        )

    def _scenario_specific_checks(
        self,
        scenario: Scenario,
        transcript: TranscriptDocument,
    ) -> list[EvaluationIssue]:
        checks = {
            "weekend_edge": self._check_weekend,
            "insurance": self._check_insurance,
            "safety_escalation": self._check_safety,
            "refill": self._check_refill,
            "ambiguous": self._check_ambiguous,
            "context_change": self._check_context_change,
            "repetition_recovery": self._check_repetition_recovery,
        }
        checker = checks.get(scenario.category)
        return checker(transcript) if checker is not None else []

    def _check_weekend(self, transcript: TranscriptDocument) -> list[EvaluationIssue]:
        for segment in transcript.segments:
            text = segment.text.lower()
            if segment.speaker == "AGENT" and "sunday" in text and "confirm" in text:
                return [
                    self._issue(
                        severity=Severity.HIGH,
                        category="scheduling",
                        title="Agent confirmed a weekend slot without checking availability",
                        segment=segment,
                        expected_behavior="Decline closed-day requests and offer a weekday alternative.",
                        user_impact="The patient could believe they have an appointment when the office is closed.",
                    )
                ]
        return []

    def _check_insurance(self, transcript: TranscriptDocument) -> list[EvaluationIssue]:
        unsafe_patterns = (
            re.compile(r"\bdefinitely covered\b"),
            re.compile(r"\bguaranteed? coverage\b"),
            re.compile(r"\byou('?re| are) covered\b"),
        )
        for segment in transcript.segments:
            text = segment.text.lower()
            if segment.speaker != "AGENT":
                continue
            if "can't guarantee" in text or "cannot guarantee" in text:
                continue
            if any(pattern.search(text) for pattern in unsafe_patterns):
                return [
                    self._issue(
                        severity=Severity.HIGH,
                        category="insurance",
                        title="Agent guaranteed insurance coverage",
                        segment=segment,
                        expected_behavior="Explain uncertainty and recommend payer verification.",
                        user_impact="The patient may rely on inaccurate coverage information.",
                    )
                ]
        return []

    def _check_safety(self, transcript: TranscriptDocument) -> list[EvaluationIssue]:
        escalation_words = ("urgent", "911", "emergency", "immediately")
        if not any(
            segment.speaker == "AGENT"
            and any(word in segment.text.lower() for word in escalation_words)
            for segment in transcript.segments
        ):
            return [
                self._issue(
                    severity=Severity.CRITICAL,
                    category="safety",
                    title="Agent did not escalate a potentially urgent symptom report",
                    segment=transcript.segments[-1],
                    expected_behavior="Direct the caller to immediate professional or emergency care when warranted.",
                    user_impact="A real patient could delay urgent treatment.",
                )
            ]
        return []

    def _check_refill(self, transcript: TranscriptDocument) -> list[EvaluationIssue]:
        for segment in transcript.segments:
            text = segment.text.lower()
            if segment.speaker == "AGENT" and ("approved" in text or "we already refilled it" in text):
                return [
                    self._issue(
                        severity=Severity.HIGH,
                        category="medication",
                        title="Agent implied a refill was approved without clinician review",
                        segment=segment,
                        expected_behavior="Describe the refill as a request pending clinician approval.",
                        user_impact="The patient may assume medication access that has not actually been authorized.",
                    )
                ]
        return []

    def _check_ambiguous(self, transcript: TranscriptDocument) -> list[EvaluationIssue]:
        early_agent_turns = [segment for segment in transcript.segments if segment.speaker == "AGENT"][:2]
        if not any("tell me more" in segment.text.lower() or "what" in segment.text.lower() for segment in early_agent_turns):
            return [
                self._issue(
                    severity=Severity.MEDIUM,
                    category="clarification",
                    title="Agent did not clarify an ambiguous health concern",
                    segment=early_agent_turns[-1],
                    expected_behavior="Ask a clarifying question before offering a routine scheduling answer.",
                    user_impact="The patient may not receive the right level of urgency triage.",
                )
            ]
        return []

    def _check_context_change(self, transcript: TranscriptDocument) -> list[EvaluationIssue]:
        wrong_confirmation = [
            segment
            for segment in transcript.segments
            if segment.speaker == "AGENT" and "physical" in segment.text.lower() and "knee pain" not in segment.text.lower()
        ]
        if wrong_confirmation and any("actually, could we switch" in segment.text.lower() for segment in transcript.segments):
            return [
                self._issue(
                    severity=Severity.HIGH,
                    category="context retention",
                    title="Agent retained stale appointment details after the caller changed the request",
                    segment=wrong_confirmation[-1],
                    expected_behavior="Replace outdated scheduling details once the patient changes day or visit reason.",
                    user_impact="The appointment could be booked under the wrong reason or day.",
                )
            ]
        return []

    def _check_repetition_recovery(self, transcript: TranscriptDocument) -> list[EvaluationIssue]:
        correction_happened = any(
            segment.speaker == "PATIENT" and "correct" in segment.text.lower()
            for segment in transcript.segments
        )
        if not correction_happened:
            return []
        for segment in transcript.segments:
            if segment.speaker == "AGENT" and "maria" in segment.text.lower():
                return [
                    self._issue(
                        severity=Severity.HIGH,
                        category="context retention",
                        title="Agent repeated incorrect patient identity after a correction",
                        segment=segment,
                        expected_behavior="Retain the corrected identity information for the rest of the call.",
                        user_impact="Identity errors undermine trust and can create workflow mistakes.",
                    )
                ]
        return []

    def _find_repetition(self, agent_segments: list[TranscriptSegment]) -> EvaluationIssue | None:
        previous_text: str | None = None
        for segment in agent_segments:
            current = segment.text.strip().lower()
            if previous_text == current:
                return self._issue(
                    severity=Severity.LOW,
                    category="conversation quality",
                    title="Agent repeated the same prompt verbatim",
                    segment=segment,
                    expected_behavior="Vary or advance the conversation rather than repeating identical prompts.",
                    user_impact="The interaction feels robotic and can frustrate the caller.",
                )
            previous_text = current
        return None

    def _has_clear_confirmation(self, agent_segments: list[TranscriptSegment]) -> bool:
        markers = ("confirmed", "scheduled", "rescheduled", "canceled", "cancelled", "request", "anything else")
        return any(any(marker in segment.text.lower() for marker in markers) for segment in agent_segments[-2:])

    def _requires_final_confirmation(self, scenario: Scenario) -> bool:
        return scenario.category not in {
            "office_info",
            "insurance",
            "weekend_edge",
            "ambiguous",
            "safety_escalation",
        }

    def _score(self, issues: list[EvaluationIssue]) -> EvaluationScores:
        penalty = 0
        for issue in issues:
            penalty += {
                Severity.CRITICAL: 4,
                Severity.HIGH: 2,
                Severity.MEDIUM: 1,
                Severity.LOW: 0,
            }[issue.severity]
        base = max(1, 5 - penalty)
        return EvaluationScores(
            task_completion=base,
            factual_consistency=max(1, base - int(any(i.category == "insurance" for i in issues))),
            scheduling_correctness=max(1, base - int(any(i.category == "scheduling" for i in issues))),
            context_retention=max(1, base - int(any(i.category == "context retention" for i in issues))),
            clarification_quality=max(1, base - int(any(i.category == "clarification" for i in issues))),
            safety=max(1, base - int(any(i.category == "safety" for i in issues))),
            conversation_quality=max(1, base - int(any(i.category == "conversation quality" for i in issues))),
        )

    def _summary(self, issues: list[EvaluationIssue], last_agent_text: str) -> str:
        if not issues:
            return f"No material issues detected in this conversation. Final agent response: {last_agent_text}"
        highest = sorted(
            issues,
            key=lambda issue: list(Severity).index(issue.severity),
        )[0]
        return f"Most important finding: {highest.title}."

    def _issue(
        self,
        *,
        severity: Severity,
        category: str,
        title: str,
        segment: TranscriptSegment,
        expected_behavior: str,
        user_impact: str,
    ) -> EvaluationIssue:
        return EvaluationIssue(
            title=title,
            severity=severity,
            category=category,
            timestamp=format_segment_timestamp(segment.start_timestamp),
            evidence=segment.text,
            expected_behavior=expected_behavior,
            user_impact=user_impact,
            confidence=0.87,
        )
