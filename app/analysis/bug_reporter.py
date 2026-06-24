from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.analysis.schemas import CallEvaluation, EvaluationIssue, Severity
from app.storage.metadata import CallMetadata


def review_issues(
    evaluations: list[CallEvaluation],
    input_fn: Callable[[str], str] = input,
) -> list[CallEvaluation]:
    for evaluation in evaluations:
        for issue in evaluation.issues:
            while True:
                answer = input_fn(
                    f"[{evaluation.call_id}] {issue.title} "
                    "(a=approve, r=reject, e=edit, s=skip): "
                ).strip().lower()
                if answer == "a":
                    issue.review_status = "approved"
                    break
                if answer == "r":
                    issue.review_status = "rejected"
                    break
                if answer == "s":
                    break
                if answer == "e":
                    _edit_issue(issue, input_fn)
                    continue
                print("Please choose a, r, e, or s.")
    return evaluations


def build_bug_report(
    evaluations: list[CallEvaluation],
    metadata_by_call: dict[str, CallMetadata],
    output_path: Path,
    *,
    include_pending: bool = False,
) -> str:
    issues: list[tuple[CallEvaluation, EvaluationIssue]] = []
    included_calls: set[str] = set()
    for evaluation in evaluations:
        metadata = metadata_by_call.get(evaluation.call_id)
        if metadata is not None and metadata.transcript_validation_status != "passed":
            continue
        included_calls.add(evaluation.call_id)
        for issue in evaluation.issues:
            if not _issue_is_reportable(issue):
                continue
            if issue.review_status == "approved" or (include_pending and issue.review_status == "pending"):
                issues.append((evaluation, issue))

    severities = {severity.value: 0 for severity in Severity}
    for _, issue in issues:
        severities[issue.severity.value] += 1

    lines = [
        "# Bug Report",
        "",
        "## Executive Summary",
        "",
        f"- Calls completed: {len(included_calls)}",
        f"- Scenarios tested: {len({evaluation.scenario_id for evaluation in evaluations if evaluation.call_id in included_calls})}",
        f"- High-severity issues: {severities['high']}",
        f"- Medium-severity issues: {severities['medium']}",
        f"- Low-severity issues: {severities['low']}",
    ]

    if issues:
        lines.append(f"- Most important finding: {issues[0][1].title}")
    else:
        lines.append("- Most important finding: No approved issues yet; real-call evidence is still pending.")
    lines.extend(["", ""])

    if not issues:
        lines.append("No approved bugs yet. Run `python scripts/analyze_call.py` and `python scripts/build_report.py --review` after real calls exist.")
    else:
        for index, (evaluation, issue) in enumerate(issues, start=1):
            metadata = metadata_by_call.get(evaluation.call_id)
            transcript_link = issue.transcript_path or (metadata.transcript_path if metadata else None)
            recording_link = issue.recording_path or (
                metadata.mixed_recording_path or metadata.recording_path if metadata else None
            )
            relative_transcript = transcript_link or f"artifacts/transcripts/{evaluation.call_id}.txt"
            relative_recording = recording_link or f"artifacts/recordings/{evaluation.call_id}-mixed.mp3"
            lines.extend(
                [
                    f"## BUG-{index:03d}: {issue.title}",
                    "",
                    f"**Severity:** {issue.severity.value.title()}  ",
                    f"**Category:** {issue.category}  ",
                    f"**Call:** `{evaluation.call_id}`  ",
                    f"**Scenario:** `{evaluation.scenario_id}`  ",
                    f"**Transcript:** [{Path(relative_transcript).name}]({relative_transcript})  ",
                    f"**Recording:** [{Path(relative_recording).name}]({relative_recording})  ",
                    f"**Timestamp:** {issue.timestamp}  ",
                    f"**Human Review:** {issue.review_status}  ",
                    "",
                    "### What happened",
                    "",
                    issue.actual_behavior or issue.evidence,
                    "",
                    "### Why it matters",
                    "",
                    issue.user_impact,
                    "",
                    "### Expected behavior",
                    "",
                    issue.expected_behavior,
                    "",
                    "### Evidence",
                    "",
                    issue.evidence_excerpt or issue.evidence,
                    "",
                    "### Reproduction steps",
                    "",
                    *[f"{step_index}. {step}" for step_index, step in enumerate(issue.reproduction_steps or [
                        "Run the scenario associated with this call.",
                        "Listen at the cited timestamp and compare against the transcript.",
                        "Observe whether the agent repeats the same failure mode.",
                    ], start=1)],
                    "",
                ]
            )

    report = "\n".join(lines).rstrip() + "\n"
    output_path.write_text(report, encoding="utf-8")
    return report


def _edit_issue(issue: EvaluationIssue, input_fn: Callable[[str], str]) -> None:
    title = input_fn(f"Title [{issue.title}]: ").strip()
    severity = input_fn(f"Severity [{issue.severity.value}]: ").strip().lower()
    category = input_fn(f"Category [{issue.category}]: ").strip()
    expected = input_fn(f"Expected behavior [{issue.expected_behavior}]: ").strip()
    actual = input_fn(f"Actual behavior [{issue.actual_behavior or issue.evidence}]: ").strip()
    impact = input_fn(f"User impact [{issue.user_impact}]: ").strip()
    notes = input_fn(f"Reviewer notes [{issue.review_notes or ''}]: ").strip()
    if title:
        issue.title = title
    if severity:
        issue.severity = Severity(severity)
    if category:
        issue.category = category
    if expected:
        issue.expected_behavior = expected
    if actual:
        issue.actual_behavior = actual
    if impact:
        issue.user_impact = impact
    if notes:
        issue.review_notes = notes


def _issue_is_reportable(issue: EvaluationIssue) -> bool:
    if not issue.timestamp or not issue.evidence or not issue.expected_behavior:
        return False
    if issue.transcript_confidence is not None and issue.transcript_confidence < 0.65:
        return False
    if issue.duplicate_of:
        return False
    return True
