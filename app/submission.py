from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.analysis.quality import VoiceQualityReport
from app.analysis.schemas import CallEvaluation, EvaluationIssue
from app.analysis.transcript import TranscriptDocument
from app.analysis.validation import TranscriptValidationReport
from app.safety import AUTHORIZED_DESTINATION
from app.storage.artifacts import ArtifactPaths, ArtifactStore
from app.storage.metadata import CallMetadata


@dataclass(slots=True)
class CallBundle:
    call_id: str
    paths: ArtifactPaths
    metadata: CallMetadata
    transcript: TranscriptDocument | None
    evaluation: CallEvaluation | None
    validation: TranscriptValidationReport | None
    quality: VoiceQualityReport | None


def load_call_bundle(artifact_store: ArtifactStore, call_id: str) -> CallBundle:
    paths = artifact_store.paths_for(call_id)
    metadata = CallMetadata.model_validate_json(paths.metadata_json.read_text(encoding="utf-8"))
    transcript = (
        TranscriptDocument.model_validate_json(paths.transcript_json.read_text(encoding="utf-8"))
        if paths.transcript_json.exists()
        else None
    )
    evaluation = (
        CallEvaluation.model_validate_json(paths.evaluation_json.read_text(encoding="utf-8")) if paths.evaluation_json.exists() else None
    )
    validation = (
        TranscriptValidationReport.model_validate_json(paths.validation_json.read_text(encoding="utf-8"))
        if paths.validation_json.exists()
        else None
    )
    quality = (
        VoiceQualityReport.model_validate_json(paths.quality_json.read_text(encoding="utf-8")) if paths.quality_json.exists() else None
    )
    return CallBundle(
        call_id=call_id,
        paths=paths,
        metadata=metadata,
        transcript=transcript,
        evaluation=evaluation,
        validation=validation,
        quality=quality,
    )


def list_call_bundles(artifact_store: ArtifactStore) -> list[CallBundle]:
    bundles: list[CallBundle] = []
    for path in sorted(artifact_store.metadata_dir.glob("call-*.json")):
        bundles.append(load_call_bundle(artifact_store, path.stem))
    return bundles


def is_provider_confirmed_live_call(metadata: CallMetadata) -> bool:
    return (
        (metadata.is_real_call or metadata.mode in {"live", "live_call"})
        and metadata.provider == "twilio"
        and metadata.destination_number == AUTHORIZED_DESTINATION
        and bool(metadata.provider_call_id)
    )


def selected_for_submission(bundle: CallBundle) -> bool:
    return bool(
        real_call_is_complete(bundle)
        and manual_review_completed(bundle)
        and bundle.metadata.submission_ready
        and bundle.quality is not None
        and bundle.quality.human_review.approved_for_submission is True
    )


def manual_review_completed(bundle: CallBundle) -> bool:
    return bundle.quality is not None and bundle.quality.human_review.is_completed()


def approved_live_issues(bundle: CallBundle) -> list[EvaluationIssue]:
    if bundle.evaluation is None or not is_provider_confirmed_live_call(bundle.metadata):
        return []
    if bundle.metadata.recording_validation_status != "passed":
        return []
    if bundle.metadata.transcript_validation_status != "passed":
        return []
    return [issue for issue in bundle.evaluation.issues if issue.review_status == "approved"]


def recording_artifact_path(bundle: CallBundle) -> Path | None:
    for candidate in (bundle.paths.recording, bundle.paths.mixed_recording):
        if candidate.exists():
            return candidate
    return None


def has_required_recording(bundle: CallBundle) -> bool:
    recording = recording_artifact_path(bundle)
    return recording is not None and recording.suffix.lower() in {".mp3", ".ogg"}


def transcript_is_valid(bundle: CallBundle) -> bool:
    return bundle.transcript is not None and bundle.validation is not None and bundle.validation.passed


def real_call_is_complete(bundle: CallBundle) -> bool:
    return bool(
        is_provider_confirmed_live_call(bundle.metadata)
        and bundle.metadata.call_status == "completed"
        and bundle.metadata.recording_validation_status == "passed"
        and has_required_recording(bundle)
        and transcript_is_valid(bundle)
        and bundle.evaluation is not None
    )


def public_repository_accessible(url: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [
                "curl",
                "-I",
                "-L",
                "--silent",
                "--show-error",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip()
        if status.isdigit():
            return status == "200", f"HTTP {status}"
    except Exception:
        pass
    try:
        response = httpx.get(url, follow_redirects=True, timeout=10.0)
    except httpx.HTTPError as exc:
        return False, str(exc)
    return response.status_code == 200, f"HTTP {response.status_code}"


def public_repository_audit_verified(project_root: Path, url: str) -> bool:
    audit_path = project_root / "PUBLIC_REPOSITORY_AUDIT.md"
    if not audit_path.exists():
        return False
    content = audit_path.read_text(encoding="utf-8")
    return url in content and "HTTP/2 200" in content


def artifact_link_targets_exist(root: Path, markdown_paths: Iterable[Path]) -> list[str]:
    import re

    pattern = re.compile(r"\]\(([^)]+)\)")
    missing: list[str] = []
    for markdown_path in markdown_paths:
        if not markdown_path.exists():
            missing.append(f"Missing markdown source: {markdown_path.name}")
            continue
        content = markdown_path.read_text(encoding="utf-8")
        for target in pattern.findall(content):
            if "://" in target or target.startswith("#"):
                continue
            candidate = (markdown_path.parent / target).resolve()
            if not candidate.exists():
                missing.append(f"{markdown_path.name} -> {target}")
    return missing


def submission_form_ready(path: Path) -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    required_prefixes = [
        "GitHub repository:",
        "Main Loom URL:",
        "AI debugging Loom URL:",
        "Single originating phone number in E.164 format:",
        "Number of selected real calls:",
        "Strongest call:",
        "Strongest finding:",
        "Final validation date:",
    ]
    if any(prefix not in content for prefix in required_prefixes):
        return False
    blocked_tokens = ("TBD", "Pending", "Unknown", "TODO")
    if any(token in content for token in blocked_tokens):
        return False
    values = {
        line.split(":", maxsplit=1)[0].strip(): line.split(":", maxsplit=1)[1].strip() for line in content.splitlines() if ":" in line
    }
    required_values = [
        values.get("GitHub repository", ""),
        values.get("Main Loom URL", ""),
        values.get("AI debugging Loom URL", ""),
        values.get("Single originating phone number in E.164 format", ""),
        values.get("Number of selected real calls", ""),
        values.get("Strongest call", ""),
        values.get("Strongest finding", ""),
        values.get("Final validation date", ""),
    ]
    return all(required_values)
