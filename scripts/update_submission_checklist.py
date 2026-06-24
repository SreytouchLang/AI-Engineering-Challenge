from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.submission import (
    approved_live_issues,
    has_required_recording,
    list_call_bundles,
    manual_review_completed,
    public_repository_audit_verified,
    public_repository_accessible,
    real_call_is_complete,
    selected_for_submission,
    submission_form_ready,
    transcript_is_valid,
)


REPO_URL = "https://github.com/SreytouchLang/AI-Engineering-Challenge"


def _replace_checkbox(content: str, label: str, checked: bool) -> str:
    state = "x" if checked else " "
    pattern = re.compile(rf"- \[[ x]\] {re.escape(label)}")
    return pattern.sub(f"- [{state}] {label}", content)


def _loom_fields_populated(readme_text: str) -> bool:
    return "Main walkthrough: `TBD`" not in readme_text and "AI debugging walkthrough: `TBD`" not in readme_text
def main() -> None:
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    bundles = list_call_bundles(artifact_store)

    repo_accessible, _ = public_repository_accessible(REPO_URL)
    if not repo_accessible:
        repo_accessible = public_repository_audit_verified(settings.project_root, REPO_URL)
    complete_real_calls = [bundle for bundle in bundles if real_call_is_complete(bundle)]
    selected_calls = [bundle for bundle in bundles if selected_for_submission(bundle)]
    recordings_ok = bool(selected_calls) and all(has_required_recording(bundle) for bundle in selected_calls)
    transcripts_ok = bool(selected_calls) and all(transcript_is_valid(bundle) for bundle in selected_calls)
    approved_bugs_ok = any(approved_live_issues(bundle) for bundle in selected_calls)
    manual_review_ok = bool(selected_calls) and all(manual_review_completed(bundle) for bundle in selected_calls)
    submission_form_ok = submission_form_ready(settings.project_root / "SUBMISSION_FORM_READY.md")

    readme_path = settings.project_root / "README.md"
    content = readme_path.read_text(encoding="utf-8")
    if "Repository:" not in content:
        content = content.replace(
            "# Pretty Good AI Voice Tester\n",
            "# Pretty Good AI Voice Tester\n\nRepository: https://github.com/SreytouchLang/AI-Engineering-Challenge\n",
            1,
        )

    content = _replace_checkbox(content, "Public GitHub repository is accessible", repo_accessible)
    content = _replace_checkbox(content, "At least 10 complete real calls are included", len(complete_real_calls) >= 10)
    content = _replace_checkbox(content, "Every real call has an MP3 or OGG recording", recordings_ok)
    content = _replace_checkbox(content, "Every real call has a transcript with both speakers", transcripts_ok)
    content = _replace_checkbox(content, "Bug report cites approved live-call findings", approved_bugs_ok)
    content = _replace_checkbox(content, "Recordings were manually checked for natural conversation quality", manual_review_ok)
    content = _replace_checkbox(content, "Submission form information is ready", submission_form_ok and _loom_fields_populated(content))
    readme_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
