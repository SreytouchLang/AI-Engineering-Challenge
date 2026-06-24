from __future__ import annotations

from datetime import date

import pytest
from twilio.base.exceptions import TwilioException

from app.agent.scenario_loader import load_scenario
from app.analysis.evaluator import ConversationEvaluator
from app.analysis.schemas import CallEvaluation, EvaluationIssue, EvaluationScores
from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.config import AppSettings, get_settings
from app.telephony.client import TwilioTelephonyClient


def make_transcript(agent_lines: list[str]) -> TranscriptDocument:
    segments: list[TranscriptSegment] = []
    second = 0.0
    for index, line in enumerate(agent_lines):
        segments.append(
            TranscriptSegment(
                speaker="PATIENT" if index == 0 else "AGENT",
                start_timestamp=second,
                end_timestamp=second + 1.0,
                text=line,
            )
        )
        second += 1.0
    return TranscriptDocument(
        call_id="call-007",
        scenario_id="weekend_scheduling",
        created_on=date(2026, 6, 23),
        duration_seconds=second,
        segments=segments,
    )


def test_evaluator_flags_weekend_confirmation_bug() -> None:
    scenario = load_scenario(
        get_settings().project_root / "scenarios" / "07_weekend_request.yaml"
    )
    transcript = TranscriptDocument(
        call_id="call-007",
        scenario_id=scenario.id,
        created_on=date(2026, 6, 23),
        duration_seconds=6.0,
        segments=[
            TranscriptSegment(
                speaker="PATIENT",
                start_timestamp=0.0,
                end_timestamp=1.0,
                text="Could I come in Sunday at ten?",
            ),
            TranscriptSegment(
                speaker="AGENT",
                start_timestamp=1.0,
                end_timestamp=2.0,
                text="Yes, your Sunday appointment is confirmed for 10 AM.",
            ),
        ],
    )
    evaluation = ConversationEvaluator().evaluate(scenario, transcript)
    assert any(issue.category == "scheduling" for issue in evaluation.issues)


def test_evaluator_does_not_flag_cautious_insurance_language() -> None:
    scenario = load_scenario(
        get_settings().project_root / "scenarios" / "06_insurance.yaml"
    )
    transcript = TranscriptDocument(
        call_id="call-006",
        scenario_id=scenario.id,
        created_on=date(2026, 6, 23),
        duration_seconds=6.0,
        segments=[
            TranscriptSegment(
                speaker="PATIENT",
                start_timestamp=0.0,
                end_timestamp=1.0,
                text="Do you take Bright Harbor Select Plus?",
            ),
            TranscriptSegment(
                speaker="AGENT",
                start_timestamp=1.0,
                end_timestamp=2.0,
                text="I can't guarantee coverage, so please confirm with your insurer.",
            ),
        ],
    )
    evaluation = ConversationEvaluator().evaluate(scenario, transcript)
    assert evaluation.issues == []


def test_evaluation_issue_requires_supported_severity_values() -> None:
    with pytest.raises(ValueError):
        EvaluationIssue(
            title="Bad",
            severity="urgent",  # type: ignore[arg-type]
            category="test",
            timestamp="00:01.0",
            evidence="example",
            expected_behavior="something",
            user_impact="impact",
            confidence=0.5,
        )


def test_call_evaluation_requires_issue_evidence() -> None:
    scores = EvaluationScores(
        task_completion=5,
        factual_consistency=5,
        scheduling_correctness=5,
        context_retention=5,
        clarification_quality=5,
        safety=5,
        conversation_quality=5,
    )
    with pytest.raises(ValueError):
        CallEvaluation(
            call_id="call-001",
            scenario_id="demo",
            summary="summary",
            scenario_completed=True,
            agent_outcome="done",
            expected_outcome="done",
            scores=scores,
            issues=[
                EvaluationIssue(
                    title="Missing evidence",
                    severity="low",
                    category="test",
                    timestamp="",
                    evidence="",
                    expected_behavior="Provide evidence",
                    user_impact="Confusing review",
                    confidence=0.5,
                )
            ],
        )


def test_telephony_client_surfaces_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCalls:
        def create(self, **kwargs):
            raise TwilioException("boom")

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.calls = FakeCalls()

    monkeypatch.setattr("app.telephony.client.Client", FakeClient)
    settings = AppSettings(
        enable_real_calls=True,
        telephony_account_id="acct",
        telephony_auth_token="token",
        telephony_from_number="+15555550123",
        public_base_url="https://example.com",
    )
    client = TwilioTelephonyClient(settings)
    with pytest.raises(RuntimeError, match="Telephony provider error"):
        client.create_call(call_id="call-001", scenario_id="simple_scheduling")
