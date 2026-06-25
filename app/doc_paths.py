from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RepoDocPaths:
    root: Path
    guides_dir: Path
    submission_dir: Path
    reports_dir: Path
    architecture: Path
    bug_report: Path
    bug_review_queue: Path
    final_call_selection: Path
    first_real_call_plan: Path
    iteration_log: Path
    live_call_progress: Path
    live_call_readiness: Path
    manual_call_review: Path
    public_repository_audit: Path
    recording_validation_report: Path
    scenarios: Path
    setup_credentials: Path
    submission_form_ready: Path
    submission_gap_report: Path
    submission_status: Path
    transcript_validation_report: Path
    voice_sim_bug_report: Path

    def ensure_layout(self) -> None:
        for directory in (self.root, self.guides_dir, self.submission_dir, self.reports_dir):
            directory.mkdir(parents=True, exist_ok=True)


def get_repo_doc_paths(project_root: Path) -> RepoDocPaths:
    docs_root = project_root / "docs"
    guides_dir = docs_root / "guides"
    submission_dir = docs_root / "submission"
    reports_dir = docs_root / "reports"
    return RepoDocPaths(
        root=docs_root,
        guides_dir=guides_dir,
        submission_dir=submission_dir,
        reports_dir=reports_dir,
        architecture=guides_dir / "ARCHITECTURE.md",
        bug_report=reports_dir / "BUG_REPORT.md",
        bug_review_queue=reports_dir / "BUG_REVIEW_QUEUE.md",
        final_call_selection=submission_dir / "FINAL_CALL_SELECTION.md",
        first_real_call_plan=submission_dir / "FIRST_REAL_CALL_PLAN.md",
        iteration_log=guides_dir / "ITERATION_LOG.md",
        live_call_progress=submission_dir / "LIVE_CALL_PROGRESS.md",
        live_call_readiness=submission_dir / "LIVE_CALL_READINESS.md",
        manual_call_review=submission_dir / "MANUAL_CALL_REVIEW.md",
        public_repository_audit=submission_dir / "PUBLIC_REPOSITORY_AUDIT.md",
        recording_validation_report=reports_dir / "RECORDING_VALIDATION_REPORT.md",
        scenarios=guides_dir / "SCENARIOS.md",
        setup_credentials=guides_dir / "SETUP_CREDENTIALS.md",
        submission_form_ready=submission_dir / "SUBMISSION_FORM_READY.md",
        submission_gap_report=submission_dir / "SUBMISSION_GAP_REPORT.md",
        submission_status=submission_dir / "SUBMISSION_STATUS.md",
        transcript_validation_report=reports_dir / "TRANSCRIPT_VALIDATION_REPORT.md",
        voice_sim_bug_report=reports_dir / "VOICE_SIM_BUG_REPORT.md",
    )
