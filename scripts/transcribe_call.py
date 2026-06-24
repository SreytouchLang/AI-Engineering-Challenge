from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.analysis.transcript import TranscriptDocument, TranscriptSegment
from app.analysis.validation import TranscriptValidator
from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata
from app.submission import is_provider_confirmed_live_call

SpeakerLabel = Literal["PATIENT", "AGENT", "SYSTEM"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or refresh a two-speaker transcript for a live call.")
    parser.add_argument("--call-id", required=True, help="Call id such as call-001.")
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Force regeneration from audio instead of reusing the existing live-stream transcript.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    paths = artifact_store.paths_for(args.call_id)
    metadata = CallMetadata.model_validate_json(paths.metadata_json.read_text(encoding="utf-8"))

    if not is_provider_confirmed_live_call(metadata):
        raise SystemExit(f"{args.call_id} is not a provider-confirmed live call, so transcript generation cannot proceed.")

    transcript_source = "live_media_stream"
    transcript_strategy = "existing_live_stream_transcript"
    if paths.transcript_json.exists() and not args.regenerate:
        transcript = TranscriptDocument.model_validate_json(paths.transcript_json.read_text(encoding="utf-8"))
    else:
        if not settings.stt_api_key:
            raise SystemExit("STT_API_KEY is required to regenerate transcripts from audio.")
        client = OpenAI(api_key=settings.stt_api_key)
        if paths.patient_recording.exists() and paths.agent_recording.exists():
            transcript = _transcript_from_channel_tracks(
                client=client,
                call_id=args.call_id,
                scenario_id=metadata.scenario_id,
                created_on=metadata.start_time.date(),
                patient_path=paths.patient_recording,
                agent_path=paths.agent_recording,
            )
            transcript_source = "separate_channel_recordings"
            transcript_strategy = "dual_channel_transcription"
        else:
            recording_path = _existing_recording_path(paths, metadata)
            if recording_path is None:
                raise SystemExit("No recording artifacts are available for transcript generation.")
            transcript = _transcript_from_diarized_recording(
                client=client,
                call_id=args.call_id,
                scenario_id=metadata.scenario_id,
                created_on=metadata.start_time.date(),
                recording_path=recording_path,
            )
            transcript_source = "mixed_recording_diarization"
            transcript_strategy = "mixed_recording_diarization"

    artifact_store.write_transcript(transcript)
    validation = TranscriptValidator(
        gap_threshold_ms=settings.transcript_gap_threshold_ms,
        confidence_threshold=settings.transcript_confidence_threshold,
        duration_tolerance_seconds=settings.duration_mismatch_tolerance_seconds,
    ).validate(
        transcript=transcript,
        metadata=metadata,
        paths=paths,
    )
    artifact_store.write_model_json(paths.validation_json, validation)
    artifact_store.write_markdown(paths.validation_md, validation.render_markdown())

    updated = metadata.model_copy(
        update={
            "transcript_path": f"artifacts/transcripts/{paths.transcript_text.name}",
            "transcript_generation_status": "completed",
            "transcript_generated_at": metadata.end_time or metadata.start_time,
            "transcript_source": transcript_source,
            "transcript_strategy": transcript_strategy,
            "transcript_validation_path": f"artifacts/validation/{paths.validation_json.name}",
            "transcript_validation_status": "passed" if validation.passed else "failed",
            "average_transcript_confidence": validation.average_confidence,
        }
    )
    artifact_store.write_metadata(updated)

    print(
        json.dumps(
            {
                "call_id": args.call_id,
                "transcript_path": updated.transcript_path,
                "transcript_source": updated.transcript_source,
                "transcript_strategy": updated.transcript_strategy,
                "validation_status": updated.transcript_validation_status,
                "average_confidence": updated.average_transcript_confidence,
            },
            indent=2,
        )
    )

    if not validation.passed:
        raise SystemExit(1)


def _transcript_from_channel_tracks(
    *,
    client: OpenAI,
    call_id: str,
    scenario_id: str,
    created_on,
    patient_path: Path,
    agent_path: Path,
) -> TranscriptDocument:
    patient_segments = _transcribe_channel(
        client=client,
        path=patient_path,
        speaker="PATIENT",
        channel="patient",
    )
    agent_segments = _transcribe_channel(
        client=client,
        path=agent_path,
        speaker="AGENT",
        channel="agent",
    )
    segments = sorted(patient_segments + agent_segments, key=lambda segment: segment.start_timestamp)
    if not segments:
        raise RuntimeError("No transcribed segments were produced from the channel recordings.")
    duration_seconds = max(segment.end_timestamp for segment in segments)
    return TranscriptDocument(
        call_id=call_id,
        scenario_id=scenario_id,
        created_on=created_on,
        duration_seconds=duration_seconds,
        segments=segments,
    )


def _transcript_from_diarized_recording(
    *,
    client: OpenAI,
    call_id: str,
    scenario_id: str,
    created_on,
    recording_path: Path,
) -> TranscriptDocument:
    with recording_path.open("rb") as recording_file:
        response = client.audio.transcriptions.create(
            file=recording_file,
            model="gpt-4o-transcribe-diarize",
            response_format="diarized_json",
        )
    payload = _response_dict(response)
    segments_payload = payload.get("segments", [])
    speaker_map: dict[str, Literal["PATIENT", "AGENT"]] = {}
    segments: list[TranscriptSegment] = []
    for segment_payload in segments_payload:
        raw_speaker = str(segment_payload.get("speaker", "")).strip()
        if raw_speaker not in speaker_map and len(speaker_map) < 2:
            speaker_map[raw_speaker] = "PATIENT" if not speaker_map else "AGENT"
        speaker = speaker_map.get(raw_speaker)
        if speaker is None:
            continue
        text = str(segment_payload.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                speaker=speaker,
                start_timestamp=float(segment_payload.get("start", 0.0)),
                end_timestamp=float(segment_payload.get("end", 0.0)),
                text=text,
                channel="patient" if speaker == "PATIENT" else "agent",
                speaker_source="diarized_audio",
            )
        )
    if not segments:
        raise RuntimeError("No diarized transcript segments were returned.")
    duration_seconds = max(segment.end_timestamp for segment in segments)
    return TranscriptDocument(
        call_id=call_id,
        scenario_id=scenario_id,
        created_on=created_on,
        duration_seconds=duration_seconds,
        segments=sorted(segments, key=lambda segment: segment.start_timestamp),
    )


def _transcribe_channel(
    *,
    client: OpenAI,
    path: Path,
    speaker: Literal["PATIENT", "AGENT"],
    channel: Literal["patient", "agent"],
) -> list[TranscriptSegment]:
    with path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    payload = _response_dict(response)
    segments: list[TranscriptSegment] = []
    for segment_payload in payload.get("segments", []):
        text = str(segment_payload.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                speaker=speaker,
                start_timestamp=float(segment_payload.get("start", 0.0)),
                end_timestamp=float(segment_payload.get("end", 0.0)),
                text=text,
                channel=channel,
                speaker_source="transcribed_channel",
            )
        )
    return segments


def _existing_recording_path(paths, metadata: CallMetadata) -> Path | None:
    candidates = [
        paths.recording if metadata.recording_path else None,
        paths.mixed_recording if metadata.mixed_recording_path else None,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    return None


def _response_dict(response: object) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        payload = response.model_dump()
        if isinstance(payload, dict):
            return payload
    if isinstance(response, dict):
        return response
    raise RuntimeError("Unexpected transcription response type.")


def _speaker_label(value: str) -> SpeakerLabel:
    if value == "PATIENT":
        return "PATIENT"
    if value == "AGENT":
        return "AGENT"
    return "SYSTEM"


if __name__ == "__main__":
    main()
