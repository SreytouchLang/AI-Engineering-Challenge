from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.doc_paths import get_repo_doc_paths
from app.safety import scan_paths_for_secrets
from app.storage.artifacts import ArtifactStore
from app.submission import (
    approved_live_issues,
    artifact_link_targets_exist,
    list_call_bundles,
    manual_review_completed,
    public_repository_accessible,
    public_repository_audit_verified,
    real_call_is_complete,
    selected_for_submission,
    submission_form_ready,
)

REPO_URL = "https://github.com/SreytouchLang/AI-Engineering-Challenge"


def _run(command: list[str]) -> bool:
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    return result.returncode == 0


def _module_available(module_name: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


def main() -> None:
    settings = get_settings()
    docs = get_repo_doc_paths(settings.project_root)
    docs.ensure_layout()
    artifact_store = ArtifactStore(settings.artifacts_root)
    bundles = list_call_bundles(artifact_store)
    selected_calls = [bundle for bundle in bundles if selected_for_submission(bundle)]

    repo_ok, _ = public_repository_accessible(REPO_URL)
    if not repo_ok:
        repo_ok = public_repository_audit_verified(settings.project_root, REPO_URL)
    real_calls_ok = len([bundle for bundle in bundles if real_call_is_complete(bundle)]) >= 10
    recordings_ok = bool(selected_calls) and all(bundle.metadata.recording_validation_status == "passed" for bundle in selected_calls)
    transcripts_ok = bool(selected_calls) and all(
        bundle.metadata.transcript_validation_status == "passed" and bundle.paths.transcript_json.exists() for bundle in selected_calls
    )
    approved_bugs_ok = any(approved_live_issues(bundle) for bundle in selected_calls)
    manual_review_ok = bool(selected_calls) and all(manual_review_completed(bundle) for bundle in selected_calls)

    readme_path = settings.project_root / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8")
    main_loom_ok = "Main walkthrough: `TBD`" not in readme_text
    ai_loom_ok = "AI debugging walkthrough: `TBD`" not in readme_text
    submission_form_ok = submission_form_ready(docs.submission_form_ready)

    tests_ok = _run([sys.executable, "-m", "pytest", "-q"])
    format_ok = _run([sys.executable, "-m", "ruff", "format", "--check", "."]) if _module_available("ruff") else False
    lint_ok = _run([sys.executable, "-m", "ruff", "check", "."]) if _module_available("ruff") else False
    type_ok = _run([sys.executable, "-m", "mypy", "app", "scripts", "tests"]) if _module_available("mypy") else False
    scenario_ok = _run([sys.executable, "scripts/validate_scenarios.py"])
    recording_ok = _run([sys.executable, "scripts/validate_recordings.py"])
    transcript_ok = _run([sys.executable, "scripts/validate_transcripts.py"])

    metadata_ok = all(bundle.metadata.destination_number == settings.authorized_destination for bundle in bundles)
    link_failures = artifact_link_targets_exist(
        settings.project_root,
        [
            settings.project_root / "README.md",
            docs.bug_report,
            docs.final_call_selection,
        ],
    )
    links_ok = not link_failures

    secret_paths = [
        path
        for path in settings.project_root.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
        and path.name != ".env"
        and "tests" not in path.parts
    ]
    secrets_ok = not scan_paths_for_secrets(secret_paths)

    bug_evidence_ok = approved_bugs_ok
    final_status = all(
        [
            repo_ok,
            real_calls_ok,
            recordings_ok,
            transcripts_ok,
            approved_bugs_ok,
            manual_review_ok,
            main_loom_ok,
            ai_loom_ok,
            submission_form_ok,
            tests_ok,
            format_ok,
            lint_ok,
            type_ok,
            scenario_ok,
            recording_ok,
            transcript_ok,
            metadata_ok,
            links_ok,
            secrets_ok,
            bug_evidence_ok,
        ]
    )

    rows = [
        ("Formatting", format_ok),
        ("Linting", lint_ok),
        ("Type checking", type_ok),
        ("Tests", tests_ok),
        ("Public repository", repo_ok),
        ("Real calls >= 10", real_calls_ok),
        ("Recordings complete", recordings_ok),
        ("Transcripts complete", transcripts_ok),
        ("Manual review complete", manual_review_ok),
        ("Approved bugs", approved_bugs_ok),
        ("Main Loom", main_loom_ok),
        ("AI debugging Loom", ai_loom_ok),
        ("Submission form", submission_form_ok),
        ("Security scan", secrets_ok),
        ("Scenario validation", scenario_ok),
        ("Recording validation", recording_ok),
        ("Transcript validation", transcript_ok),
        ("Metadata validation", metadata_ok),
        ("Artifact-link validation", links_ok),
        ("Bug-evidence validation", bug_evidence_ok),
    ]
    print("FINAL SUBMISSION CHECK\n")
    for label, passed in rows:
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    print(f"\nFINAL STATUS: {'READY' if final_status else 'NOT READY'}")
    if not final_status:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
