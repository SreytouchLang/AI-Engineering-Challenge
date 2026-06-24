from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.analysis.schemas import CallEvaluation
from app.analysis.transcript import TranscriptDocument
from app.storage.metadata import CallMetadata


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    recording: Path
    transcript_text: Path
    transcript_json: Path
    evaluation_json: Path
    metadata_json: Path


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.recordings_dir = root / "recordings"
        self.transcripts_dir = root / "transcripts"
        self.evaluations_dir = root / "evaluations"
        self.metadata_dir = root / "call_metadata"
        self.ensure_layout()

    def ensure_layout(self) -> None:
        for directory in (
            self.recordings_dir,
            self.transcripts_dir,
            self.evaluations_dir,
            self.metadata_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def paths_for(self, call_id: str, recording_extension: str = "mp3") -> ArtifactPaths:
        return ArtifactPaths(
            recording=self.recordings_dir / f"{call_id}.{recording_extension}",
            transcript_text=self.transcripts_dir / f"{call_id}.txt",
            transcript_json=self.transcripts_dir / f"{call_id}.json",
            evaluation_json=self.evaluations_dir / f"{call_id}.json",
            metadata_json=self.metadata_dir / f"{call_id}.json",
        )

    def reserve_call_id(self, call_id: str) -> None:
        paths = self.paths_for(call_id)
        candidates = (
            paths.recording,
            paths.transcript_text,
            paths.transcript_json,
            paths.evaluation_json,
            paths.metadata_json,
        )
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

    def write_json(self, path: Path, payload: dict) -> Path:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

