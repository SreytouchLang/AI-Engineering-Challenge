from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from app.analysis.schemas import CallEvaluation
from app.analysis.transcript import TranscriptDocument
from app.storage.metadata import CallMetadata


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    recording: Path
    patient_recording: Path
    agent_recording: Path
    mixed_recording: Path
    transcript_text: Path
    transcript_json: Path
    evaluation_json: Path
    metadata_json: Path
    quality_json: Path
    quality_md: Path
    validation_json: Path
    validation_md: Path


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.recordings_dir = root / "recordings"
        self.transcripts_dir = root / "transcripts"
        self.evaluations_dir = root / "evaluations"
        self.metadata_dir = root / "call_metadata"
        self.quality_dir = root / "quality"
        self.validation_dir = root / "validation"
        self.ensure_layout()

    def ensure_layout(self) -> None:
        for directory in (
            self.recordings_dir,
            self.transcripts_dir,
            self.evaluations_dir,
            self.metadata_dir,
            self.quality_dir,
            self.validation_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def paths_for(self, call_id: str, recording_extension: str = "mp3") -> ArtifactPaths:
        return ArtifactPaths(
            recording=self.recordings_dir / f"{call_id}.{recording_extension}",
            patient_recording=self.recordings_dir / f"{call_id}-patient.wav",
            agent_recording=self.recordings_dir / f"{call_id}-agent.wav",
            mixed_recording=self.recordings_dir / f"{call_id}-mixed.{recording_extension}",
            transcript_text=self.transcripts_dir / f"{call_id}.txt",
            transcript_json=self.transcripts_dir / f"{call_id}.json",
            evaluation_json=self.evaluations_dir / f"{call_id}.json",
            metadata_json=self.metadata_dir / f"{call_id}.json",
            quality_json=self.quality_dir / f"{call_id}-quality.json",
            quality_md=self.quality_dir / f"{call_id}-quality.md",
            validation_json=self.validation_dir / f"{call_id}-validation.json",
            validation_md=self.validation_dir / f"{call_id}-validation.md",
        )

    def next_call_id(self) -> str:
        existing = sorted(self.metadata_dir.glob("call-*.json"))
        if not existing:
            return "call-001"
        last = existing[-1].stem
        sequence = int(last.split("-")[1]) + 1
        return f"call-{sequence:03d}"

    def original_recording_path(self, call_id: str, suffix: str) -> Path:
        extension = suffix.removeprefix(".")
        return self.recordings_dir / f"{call_id}-provider-original.{extension}"

    def recording_validation_paths(self, call_id: str) -> tuple[Path, Path]:
        return (
            self.validation_dir / f"{call_id}-recording-validation.json",
            self.validation_dir / f"{call_id}-recording-validation.md",
        )

    def reserve_call_id(self, call_id: str) -> None:
        paths = self.paths_for(call_id)
        candidates = [
            paths.recording,
            paths.patient_recording,
            paths.agent_recording,
            paths.mixed_recording,
            paths.transcript_text,
            paths.transcript_json,
            paths.evaluation_json,
            paths.metadata_json,
            paths.quality_json,
            paths.quality_md,
            paths.validation_json,
            paths.validation_md,
        ]
        candidates.extend(self.recordings_dir.glob(f"{call_id}-provider-original.*"))
        collisions = [path for path in candidates if path.exists()]
        if collisions:
            joined = ", ".join(path.name for path in collisions)
            raise FileExistsError(f"Duplicate call id detected for {call_id}: {joined}")

    def write_transcript(self, document: TranscriptDocument) -> ArtifactPaths:
        paths = self.paths_for(document.call_id)
        paths.transcript_text.write_text(document.render_text(), encoding="utf-8")
        paths.transcript_json.write_text(
            document.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return paths

    def write_metadata(self, metadata: CallMetadata) -> Path:
        path = self.paths_for(metadata.call_id).metadata_json
        path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
        return path

    def write_evaluation(self, evaluation: CallEvaluation) -> Path:
        path = self.paths_for(evaluation.call_id).evaluation_json
        path.write_text(evaluation.model_dump_json(indent=2), encoding="utf-8")
        return path

    def write_model_json(self, path: Path, payload: BaseModel) -> Path:
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_evaluation(self, call_id: str) -> CallEvaluation:
        path = self.paths_for(call_id).evaluation_json
        return CallEvaluation.model_validate_json(path.read_text(encoding="utf-8"))

    def list_evaluations(self) -> list[CallEvaluation]:
        items: list[CallEvaluation] = []
        for path in sorted(self.evaluations_dir.glob("*.json")):
            items.append(CallEvaluation.model_validate_json(path.read_text(encoding="utf-8")))
        return items

    def validate_audio_artifact(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"Recording file is missing: {path}")
        if path.suffix.lower() not in {".mp3", ".ogg", ".wav"}:
            raise ValueError(f"Unsupported recording format: {path.suffix}")
        if path.stat().st_size <= 0:
            raise ValueError(f"Recording file is empty: {path}")

    def convert_audio(self, source: Path, destination: Path) -> Path:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            str(destination),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return destination

    def copy_audio(self, source: Path, destination: Path) -> Path:
        shutil.copyfile(source, destination)
        return destination

    def write_json(self, path: Path, payload: dict) -> Path:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def write_markdown(self, path: Path, content: str) -> Path:
        path.write_text(content, encoding="utf-8")
        return path
