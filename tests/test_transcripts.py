from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.storage.artifacts import ArtifactStore


def test_transcript_requires_ordered_timestamps() -> None:
    with pytest.raises(ValueError):
        TranscriptDocument(
            call_id="call-001",
            scenario_id="demo",
            created_on=date(2026, 6, 23),
            duration_seconds=10.0,
            segments=[
                TranscriptSegment(
                    speaker="PATIENT",
                    start_timestamp=1.0,
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

