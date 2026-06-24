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
    selected_for_submission,
    transcript_is_valid,
)


def _rank_score(bundle) -> float:
    score = float(bundle.metadata.quality_score or 0)
    if bundle.quality is not None:
        review = bundle.quality.human_review
        for value in (
            review.naturalness,
            review.clarity,
            review.pacing,
            review.turn_taking,
            review.audio_quality,
            review.transcript_quality,
            review.scenario_completion,
            review.bug_evidence,
        ):
            score += float(value or 0) * 2.0
        if review.approved_for_submission:
            score += 10
    score += len(approved_live_issues(bundle)) * 2.5
    if transcript_is_valid(bundle):
        score += 5
    return round(score, 2)


def main() -> None:
    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)
    bundles = [
        bundle
        for bundle in list_call_bundles(artifact_store)
        if is_provider_confirmed_live_call(bundle.metadata)
    ]
    ranked = sorted(bundles, key=_rank_score, reverse=True)

    lines = [
        "# Final Call Selection",
        "",
        "| Call | Scenario | Duration | Quality score | Recording | Transcript | Finding | Approved |",
        "| ---- | -------- | -------: | ------------: | --------- | ---------- | ------- | -------- |",
    ]
    for bundle in ranked:
        finding = approved_live_issues(bundle)[0].title if approved_live_issues(bundle) else "None approved"
        lines.append(
            "| {call} | {scenario} | {duration} | {quality} | {recording} | {transcript} | {finding} | {approved} |".format(
                call=bundle.call_id,
                scenario=bundle.metadata.scenario_id,
                duration=f"{bundle.metadata.duration_seconds or 0:.1f}",
                quality=bundle.metadata.quality_score or 0,
                recording="Yes" if has_required_recording(bundle) else "No",
                transcript="Yes" if transcript_is_valid(bundle) else "No",
                finding=finding,
                approved="Yes" if selected_for_submission(bundle) else "No",
            )
        )
    if not ranked:
        lines.append("| None | - | 0 | 0 | No | No | None | No |")

    approved = [bundle for bundle in ranked if selected_for_submission(bundle)]
    if len(approved) < 10:
        lines.extend(
            [
                "",
                f"Only {len(approved)} validated, manually approved calls are currently strong enough for selection.",
                f"{max(0, 10 - len(approved))} additional strong calls are still required.",
            ]
        )

    output_path = settings.project_root / "FINAL_CALL_SELECTION.md"
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    if len(approved) < 10:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
