from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.analysis.validation import TranscriptValidator
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata


def test_transcript_requires_monotonic_start_timestamps() -> None:
    with pytest.raises(ValueError):
        TranscriptDocument(
            call_id="call-001",
            scenario_id="demo",
            created_on=date(2026, 6, 23),
            duration_seconds=10.0,
            segments=[
                TranscriptSegment(
                    speaker="PATIENT",
                    start_timestamp=2.0,
                    end_timestamp=2.0,
                    text="Hello",
                ),
                TranscriptSegment(
                    speaker="AGENT",
                    start_timestamp=1.5,
                    end_timestamp=2.5,
                    text="Hi there",
                ),
            ],
        )


def test_transcript_overlap_requires_overlap_metadata(tmp_path: Path) -> None:
    transcript = TranscriptDocument(
        call_id="call-001",
        scenario_id="demo",
        created_on=date(2026, 6, 23),
        duration_seconds=3.0,
        segments=[
            TranscriptSegment(
                speaker="AGENT",
                start_timestamp=0.0,
                end_timestamp=2.0,
                text="Long explanation",
                channel="agent",
            ),
            TranscriptSegment(
                speaker="PATIENT",
                start_timestamp=1.4,
                end_timestamp=2.2,
                text="Sorry to cut in",
                channel="patient",
            ),
        ],
    )
    metadata = CallMetadata(
        call_id="call-001",
        scenario_id="demo",
        destination_number="+18054398008",
        start_time=datetime(2026, 6, 23, tzinfo=UTC),
        call_status="completed",
    )
    validator = TranscriptValidator(
        gap_threshold_ms=4500,
        confidence_threshold=0.65,
        duration_tolerance_seconds=1.5,
    )
    report = validator.validate(transcript, metadata, ArtifactStore(tmp_path).paths_for("call-001"))
    assert any(issue.code == "missing_overlap_metadata" for issue in report.issues)


def test_transcript_with_no_agent_turns_is_rejected() -> None:
    transcript = TranscriptDocument(
        call_id="call-001",
        scenario_id="demo",
        created_on=date(2026, 6, 23),
        duration_seconds=2.0,
        segments=[
            TranscriptSegment(
                speaker="PATIENT",
                start_timestamp=0.0,
                end_timestamp=1.0,
                text="Hello",
            )
        ],
    )
    with pytest.raises(ValueError):
        transcript.require_agent_turns()


def test_artifact_store_rejects_duplicate_call_ids(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    existing = store.paths_for("call-001").metadata_json
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        store.reserve_call_id("call-001")


def test_validate_audio_artifact_checks_existence_and_format(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    missing = tmp_path / "recordings" / "call-001.mp3"
    with pytest.raises(FileNotFoundError):
        store.validate_audio_artifact(missing)

    bad = tmp_path / "recordings" / "call-001.txt"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not audio", encoding="utf-8")
    with pytest.raises(ValueError):
        store.validate_audio_artifact(bad)
