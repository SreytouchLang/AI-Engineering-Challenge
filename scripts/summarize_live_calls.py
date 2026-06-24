from __future__ import annotations

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
    is_provider_confirmed_live_call,
    list_call_bundles,
    manual_review_completed,
    real_call_is_complete,
    selected_for_submission,
    transcript_is_valid,
)


def _checkbox(value: bool | None) -> str:
    return "[x]" if value else "[ ]"


def _manual_review_section(bundle) -> str:
    review = bundle.quality.human_review if bundle.quality is not None else None
    recording_target = bundle.metadata.recording_path or bundle.metadata.mixed_recording_path or ""
    transcript_target = bundle.metadata.transcript_path or ""
    if review is None:
        return "\n".join(
            [
                f"## {bundle.call_id}",
                "",
                f"**Scenario:** {bundle.metadata.scenario_id}",
                f"**Duration:** {bundle.metadata.duration_seconds or ''}",
                f"**Recording:** {recording_target}",
                f"**Transcript:** {transcript_target}",
                "",
                "- [ ] Listened from beginning to end",
                "- [ ] Both speakers are audible",
                "- [ ] Conversation is coherent",
                "- [ ] Patient sounds natural",
                "- [ ] Turn-taking is acceptable",
                "- [ ] No major audio glitches",
                "- [ ] No severe latency",
                "- [ ] Scenario goal was pursued",
                "- [ ] Final outcome is clear",
                "- [ ] Approved for submission",
                "",
                "Reviewer:",
                "Date:",
                "Naturalness score:",
                "Notes:",
                "",
            ]
        )

    return "\n".join(
        [
            f"## {bundle.call_id}",
            "",
            f"**Scenario:** {bundle.metadata.scenario_id}",
            f"**Duration:** {bundle.metadata.duration_seconds or ''}",
            f"**Recording:** {recording_target}",
            f"**Transcript:** {transcript_target}",
            "",
            f"- {_checkbox(review.played_from_beginning_to_end)} Listened from beginning to end",
            f"- {_checkbox(review.both_speakers_audible)} Both speakers are audible",
            f"- {_checkbox(review.conversation_coherent)} Conversation is coherent",
            f"- {_checkbox(review.patient_sounds_natural)} Patient sounds natural",
            f"- {_checkbox(review.turn_taking_sensible)} Turn-taking is acceptable",
            f"- {_checkbox(review.no_major_audio_glitches)} No major audio glitches",
            f"- {_checkbox(review.no_excessive_delay)} No severe latency",
            f"- {_checkbox(review.scenario_objective_pursued)} Scenario goal was pursued",
            f"- {_checkbox(review.final_outcome_clear)} Final outcome is clear",
            f"- {_checkbox(review.approved_for_submission)} Approved for submission",
            "",
            f"Reviewer: {review.reviewer or ''}",
            f"Date: {review.review_date or ''}",
            f"Naturalness score: {review.naturalness or ''}",
            f"Notes: {review.reviewer_notes or ''}",
            "",
        ]
    )


def main() -> None:
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    bundles = list_call_bundles(artifact_store)
    live_bundles = [bundle for bundle in bundles if is_provider_confirmed_live_call(bundle.metadata)]

    tracker_lines = [
        "# Live Call Progress",
        "",
        "| Call | Scenario | Provider confirmed | MP3/OGG | Two speakers | Transcript valid | Manual review | Selected |",
        "| ---- | -------- | ------------------ | ------- | ------------ | ---------------- | ------------- | -------- |",
    ]
    for bundle in live_bundles:
        two_speakers = bundle.transcript is not None and {"PATIENT", "AGENT"} <= {segment.speaker for segment in bundle.transcript.segments}
        tracker_lines.append(
            "| {call} | {scenario} | {provider} | {recording} | {two_speakers} | {validated} | {reviewed} | {selected} |".format(
                call=bundle.call_id,
                scenario=bundle.metadata.scenario_id,
                provider="Yes",
                recording="Yes" if has_required_recording(bundle) else "No",
                two_speakers="Yes" if two_speakers else "No",
                validated="Yes" if transcript_is_valid(bundle) else "No",
                reviewed="Yes" if manual_review_completed(bundle) else "No",
                selected="Yes" if selected_for_submission(bundle) else "No",
            )
        )
    if not live_bundles:
        tracker_lines.append("| None | - | No | No | No | No | No | No |")
    progress_path = settings.project_root / "LIVE_CALL_PROGRESS.md"
    progress_path.write_text("\n".join(tracker_lines).rstrip() + "\n", encoding="utf-8")

    manual_lines = ["# Manual Call Review", ""]
    if not live_bundles:
        manual_lines.extend(
            [
                "No provider-confirmed live calls are available to review yet.",
                "",
            ]
        )
    for bundle in live_bundles:
        manual_lines.append(_manual_review_section(bundle))
    manual_path = settings.project_root / "MANUAL_CALL_REVIEW.md"
    manual_path.write_text("\n".join(manual_lines).rstrip() + "\n", encoding="utf-8")

    total_real_calls = len(live_bundles)
    valid_real_calls = sum(1 for bundle in live_bundles if real_call_is_complete(bundle))
    failed_calls = sum(1 for bundle in live_bundles if bundle.metadata.call_status != "completed")
    recordings = sum(
        1 for bundle in live_bundles if has_required_recording(bundle) and bundle.metadata.recording_validation_status == "passed"
    )
    transcripts = sum(
        1 for bundle in live_bundles if bundle.transcript is not None and bundle.metadata.transcript_validation_status == "passed"
    )
    manual_approvals = sum(
        1 for bundle in live_bundles if bundle.quality is not None and bundle.quality.human_review.approved_for_submission is True
    )
    selected_calls = sum(1 for bundle in live_bundles if selected_for_submission(bundle))
    remaining = max(0, 10 - selected_calls)

    print(
        "\n".join(
            [
                f"total real calls: {total_real_calls}",
                f"valid real calls: {valid_real_calls}",
                f"failed calls: {failed_calls}",
                f"calls with recordings: {recordings}",
                f"calls with complete transcripts: {transcripts}",
                f"manually approved calls: {manual_approvals}",
                f"selected submission calls: {selected_calls}",
                f"remaining calls required: {remaining}",
                f"approved live issues: {sum(len(approved_live_issues(bundle)) for bundle in live_bundles)}",
            ]
        )
    )


if __name__ == "__main__":
    main()
