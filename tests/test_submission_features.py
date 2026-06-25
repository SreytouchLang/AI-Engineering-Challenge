from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from app.agent.scenario_loader import load_scenario
from app.analysis.bug_reporter import build_bug_report, build_bug_review_queue
from app.analysis.quality import HumanVoiceReview
from app.analysis.recording_validation import RecordingValidator
from app.analysis.schemas import CallEvaluation, EvaluationIssue, EvaluationScores, Severity
from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.analysis.validation import TranscriptValidator
from app.config import AppSettings
from app.safety import AUTHORIZED_DESTINATION, scan_paths_for_secrets
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata
from app.submission import loom_url_ready, submission_form_values
from app.telephony.preflight import build_live_call_preflight
from app.voice.audio import pcm16_to_wav_bytes


def test_preflight_reports_missing_live_call_requirements(tmp_path: Path) -> None:
    settings = AppSettings(
        enable_real_calls=False,
        authorized_destination=AUTHORIZED_DESTINATION,
        telephony_account_id="",
        telephony_auth_token="",
        telephony_from_number="",
        stt_api_key="",
        tts_api_key="",
        public_base_url=None,
    )
    artifact_store = ArtifactStore(tmp_path)
    scenario = load_scenario(Path(__file__).resolve().parents[1] / "scenarios" / "01_simple_scheduling.yaml")

    report = build_live_call_preflight(
        settings=settings,
        scenario=scenario,
        artifact_store=artifact_store,
        call_id="call-001",
    )

    assert report.ready is False
    assert report.checks["enable_real_calls"] is False
    assert report.checks["credentials_present"] is False
    assert any("ENABLE_REAL_CALLS" in problem for problem in report.problems)


def test_transcript_validator_flags_placeholder_text(tmp_path: Path) -> None:
    transcript = TranscriptDocument(
        call_id="call-001",
        scenario_id="demo",
        created_on=date(2026, 6, 23),
        duration_seconds=4.0,
        segments=[
            TranscriptSegment(
                speaker="PATIENT",
                start_timestamp=0.0,
                end_timestamp=1.0,
                text="Hello there.",
                channel="patient",
            ),
            TranscriptSegment(
                speaker="AGENT",
                start_timestamp=1.0,
                end_timestamp=2.0,
                text="[inaudible]",
                channel="agent",
            ),
        ],
    )
    metadata = CallMetadata(
        call_id="call-001",
        scenario_id="demo",
        destination_number=AUTHORIZED_DESTINATION,
        start_time=datetime(2026, 6, 23, tzinfo=UTC),
        call_status="completed",
    )
    report = TranscriptValidator(
        gap_threshold_ms=4500,
        confidence_threshold=0.65,
        duration_tolerance_seconds=1.5,
    ).validate(transcript, metadata, ArtifactStore(tmp_path).paths_for("call-001"))
    assert any(issue.code == "placeholder_text_detected" for issue in report.issues)


def test_recording_validator_flags_silent_audio(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    paths = store.paths_for("call-001")
    silent_pcm = b"\x00\x00" * 8000
    paths.patient_recording.write_bytes(pcm16_to_wav_bytes(silent_pcm))
    paths.agent_recording.write_bytes(pcm16_to_wav_bytes(silent_pcm))
    paths.mixed_recording.with_suffix(".wav").write_bytes(pcm16_to_wav_bytes(silent_pcm))
    metadata = CallMetadata(
        call_id="call-001",
        scenario_id="demo",
        destination_number=AUTHORIZED_DESTINATION,
        start_time=datetime(2026, 6, 23, tzinfo=UTC),
        duration_seconds=1.0,
        call_status="completed",
        mode="live",
        provider_call_id="CA123",
    )
    report = RecordingValidator().validate(metadata=metadata, paths=paths)
    issue_codes = {issue.code for issue in report.issues}
    assert "silent_recording" in issue_codes
    assert "bad_public_format" in issue_codes


def test_build_bug_report_skips_dry_run_calls(tmp_path: Path) -> None:
    evaluation = CallEvaluation(
        call_id="call-001",
        scenario_id="demo",
        summary="summary",
        scenario_completed=False,
        agent_outcome="outcome",
        expected_outcome="expected",
        scores=EvaluationScores(
            task_completion=3,
            factual_consistency=3,
            scheduling_correctness=3,
            context_retention=3,
            clarification_quality=3,
            safety=3,
            conversation_quality=3,
        ),
        issues=[
            EvaluationIssue(
                title="Dry run issue",
                severity=Severity.HIGH,
                category="workflow",
                timestamp="00:01.0",
                evidence="problem",
                expected_behavior="better behavior",
                user_impact="confusing",
                confidence=0.9,
                review_status="approved",
            )
        ],
    )
    metadata = CallMetadata(
        call_id="call-001",
        scenario_id="demo",
        destination_number=AUTHORIZED_DESTINATION,
        start_time=datetime(2026, 6, 23, tzinfo=UTC),
        call_status="completed",
        mode="dry_run",
        transcript_validation_status="passed",
    )
    output_path = tmp_path / "BUG_REPORT.md"
    report = build_bug_report([evaluation], {"call-001": metadata}, output_path)
    assert "BUG-001" not in report
    assert "No approved bugs yet" in report


def test_human_review_requires_complete_fields() -> None:
    review = HumanVoiceReview(reviewer="Ava", reviewer_notes="Looks good.")
    assert review.is_completed() is False


def test_secret_scan_skips_binary_files(tmp_path: Path) -> None:
    binary_file = tmp_path / "sample.wav"
    binary_file.write_bytes(b"\xff\xfe\x00\x01")
    assert scan_paths_for_secrets([binary_file]) == {}


def test_artifact_store_next_call_id_advances_after_existing_metadata(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    metadata = CallMetadata(
        call_id="call-001",
        scenario_id="demo",
        destination_number=AUTHORIZED_DESTINATION,
        start_time=datetime(2026, 6, 23, tzinfo=UTC),
        call_status="completed",
    )
    store.write_metadata(metadata)
    assert store.next_call_id() == "call-002"


def test_recording_validator_prefers_public_recording_artifact(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    paths = store.paths_for("call-001")
    paths.recording.write_bytes(b"public")
    paths.mixed_recording.write_bytes(b"local")
    metadata = CallMetadata(
        call_id="call-001",
        scenario_id="demo",
        destination_number=AUTHORIZED_DESTINATION,
        start_time=datetime(2026, 6, 23, tzinfo=UTC),
        call_status="completed",
        mode="live",
        provider="twilio",
        is_real_call=True,
        provider_call_id="CA123",
    )
    report = RecordingValidator().validate(metadata=metadata, paths=paths)
    assert report.metrics["mixed_recording"] == "call-001.mp3"


def test_bug_review_queue_includes_expected_review_fields(tmp_path: Path) -> None:
    evaluation = CallEvaluation(
        call_id="call-001",
        scenario_id="demo",
        summary="summary",
        scenario_completed=False,
        agent_outcome="outcome",
        expected_outcome="expected",
        scores=EvaluationScores(
            task_completion=3,
            factual_consistency=3,
            scheduling_correctness=3,
            context_retention=3,
            clarification_quality=3,
            safety=3,
            conversation_quality=3,
        ),
        issues=[
            EvaluationIssue(
                title="Confirmed the wrong time",
                severity=Severity.HIGH,
                category="scheduling",
                timestamp="00:12.0",
                evidence="The office repeated the wrong slot.",
                evidence_excerpt="...wrong slot...",
                expected_behavior="Restate the confirmed slot accurately.",
                actual_behavior="Repeated a conflicting appointment time.",
                user_impact="The caller could arrive at the wrong time.",
                confidence=0.91,
                recording_path="artifacts/recordings/call-001.mp3",
                transcript_path="artifacts/transcripts/call-001.txt",
                reproduction_steps=["Run the simple scheduling scenario."],
            )
        ],
    )
    metadata = CallMetadata(
        call_id="call-001",
        provider="twilio",
        provider_call_id="CA123",
        scenario_id="demo",
        destination_number=AUTHORIZED_DESTINATION,
        start_time=datetime(2026, 6, 23, tzinfo=UTC),
        call_status="completed",
        mode="live",
        is_real_call=True,
        recording_validation_status="passed",
        transcript_validation_status="passed",
    )
    output_path = tmp_path / "BUG_REVIEW_QUEUE.md"
    queue = build_bug_review_queue([evaluation], {"call-001": metadata}, output_path)
    assert "**Actual behavior:**" in queue
    assert "**Expected behavior:**" in queue
    assert "**Reproduction steps:**" in queue
    assert "**Confidence:** 0.91" in queue


def test_submission_form_values_track_main_and_ai_loom_separately(tmp_path: Path) -> None:
    form = tmp_path / "SUBMISSION_FORM_READY.md"
    form.write_text(
        "\n".join(
            [
                "GitHub repository: https://github.com/SreytouchLang/AI-Engineering-Challenge",
                "Main Loom URL: https://www.loom.com/share/main-video",
                "AI debugging Loom URL:",
                "Single originating phone number in E.164 format:",
                "Number of selected real calls:",
                "Strongest call:",
                "Strongest finding:",
                "Final validation date:",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    values = submission_form_values(form)

    assert loom_url_ready(values["Main Loom URL"]) is True
    assert loom_url_ready(values["AI debugging Loom URL"]) is False
