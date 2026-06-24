from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.analysis.schemas import CallEvaluation, EvaluationIssue, Severity


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
    output_path: Path,
    *,
    include_pending: bool = False,
) -> str:
    issues: list[tuple[CallEvaluation, EvaluationIssue]] = []
    for evaluation in evaluations:
        for issue in evaluation.issues:
            if issue.review_status == "approved" or (
                include_pending and issue.review_status == "pending"
            ):
                issues.append((evaluation, issue))

    severities = {severity.value: 0 for severity in Severity}
    for _, issue in issues:
        severities[issue.severity.value] += 1

    lines = [
        "# Bug Report",
        "",
        "## Executive Summary",
        "",
        f"- Calls completed: {len(evaluations)}",
        f"- Scenarios tested: {len({evaluation.scenario_id for evaluation in evaluations})}",
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
            lines.extend(
                [
                    f"## BUG-{index:03d}: {issue.title}",
                    "",
                    f"**Severity:** {issue.severity.value.title()}  ",
                    f"**Category:** {issue.category}  ",
                    f"**Call:** `{evaluation.call_id}`  ",
                    f"**Transcript:** `artifacts/transcripts/{evaluation.call_id}.txt`  ",
                    f"**Recording:** `artifacts/recordings/{evaluation.call_id}.mp3`  ",
                    f"**Timestamp:** {issue.timestamp}  ",
                    "",
                    "### What happened",
                    "",
                    issue.evidence,
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
                    issue.evidence,
                    "",
                    "### Reproduction steps",
                    "",
                    "1. Run the scenario associated with this call.",
                    "2. Listen at the cited timestamp and compare against the transcript.",
                    "3. Observe whether the agent repeats the same failure mode.",
                    "",
                ]
            )

    report = "\n".join(lines).rstrip() + "\n"
    output_path.write_text(report, encoding="utf-8")
    return report


def _edit_issue(issue: EvaluationIssue, input_fn: Callable[[str], str]) -> None:
    title = input_fn(f"Title [{issue.title}]: ").strip()
    category = input_fn(f"Category [{issue.category}]: ").strip()
    expected = input_fn(f"Expected behavior [{issue.expected_behavior}]: ").strip()
    impact = input_fn(f"User impact [{issue.user_impact}]: ").strip()
    if title:
        issue.title = title
    if category:
        issue.category = category
    if expected:
        issue.expected_behavior = expected
    if impact:
        issue.user_impact = impact

