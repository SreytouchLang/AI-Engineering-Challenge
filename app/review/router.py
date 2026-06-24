from __future__ import annotations

from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.analysis.quality import VoiceQualityReport
from app.analysis.schemas import CallEvaluation, Severity
from app.analysis.validation import TranscriptValidationReport
from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata

settings = get_settings()
artifact_store = ArtifactStore(settings.artifacts_root)
router = APIRouter(prefix="/review", tags=["review"])


@router.get("/", response_class=HTMLResponse)
async def review_home(
    severity: str | None = None,
    scenario: str | None = None,
    category: str | None = None,
    review_status: str | None = None,
    min_quality: int | None = None,
    min_confidence: float | None = None,
) -> str:
    calls = _load_calls()
    rows: list[str] = []
    for bundle in calls:
        if severity and not any(issue.severity.value == severity for issue in bundle.evaluation.issues):
            continue
        if scenario and bundle.metadata.scenario_id != scenario:
            continue
        if category and not any(issue.category == category for issue in bundle.evaluation.issues):
            continue
        if review_status and not any(issue.review_status == review_status for issue in bundle.evaluation.issues):
            continue
        if min_quality is not None and (bundle.quality.overall_score if bundle.quality else 0) < min_quality:
            continue
        if min_confidence is not None and (bundle.validation.average_confidence if bundle.validation else 0) < min_confidence:
            continue

        quality_score = bundle.quality.overall_score if bundle.quality else "N/A"
        confidence = (
            f"{bundle.validation.average_confidence:.2f}" if bundle.validation else "N/A"
        )
        rows.append(
            "<tr>"
            f"<td><a href='/review/calls/{bundle.metadata.call_id}'>{bundle.metadata.call_id}</a></td>"
            f"<td>{escape(bundle.metadata.scenario_id)}</td>"
            f"<td>{quality_score}</td>"
            f"<td>{confidence}</td>"
            f"<td>{bundle.metadata.transcript_validation_status}</td>"
            f"<td>{bundle.metadata.submission_ready}</td>"
            "</tr>"
        )

    return _page(
        "Review Dashboard",
        """
        <h1>Review Dashboard</h1>
        <form method="get" style="margin-bottom:1rem;">
          <label>Severity <input name="severity" /></label>
          <label>Scenario <input name="scenario" /></label>
          <label>Category <input name="category" /></label>
          <label>Status <input name="review_status" /></label>
          <label>Min quality <input name="min_quality" type="number" /></label>
          <label>Min confidence <input name="min_confidence" type="number" step="0.01" /></label>
          <button type="submit">Filter</button>
        </form>
        <table border="1" cellpadding="6" cellspacing="0">
          <thead>
            <tr>
              <th>Call</th>
              <th>Scenario</th>
              <th>Quality</th>
              <th>Confidence</th>
              <th>Validation</th>
              <th>Submission Ready</th>
            </tr>
          </thead>
          <tbody>
        """
        + "\n".join(rows)
        + """
          </tbody>
        </table>
        """,
    )


@router.get("/calls/{call_id}", response_class=HTMLResponse)
async def review_call(call_id: str) -> str:
    bundle = _load_call_bundle(call_id)
    mixed_recording_url = ""
    if bundle.metadata.mixed_recording_path:
        mixed_recording_url = f"/review/artifact/recordings/{Path(bundle.metadata.mixed_recording_path).name}"

    transcript_rows = []
    for index, segment in enumerate(bundle.transcript.segments):
        transcript_rows.append(
            "<tr id='seg-{idx}' onclick='jumpTo({start})' style='cursor:pointer;'>"
            f"<td>{index}</td>"
            f"<td>{escape(segment.speaker)}</td>"
            f"<td>{segment.start_timestamp:.2f}</td>"
            f"<td>{segment.end_timestamp:.2f}</td>"
            f"<td>{escape(segment.action or '')}</td>"
            f"<td>{escape(segment.text)}</td>"
            "</tr>".format(idx=index, start=segment.start_timestamp)
        )

    issue_cards = []
    for index, issue in enumerate(bundle.evaluation.issues):
        issue_cards.append(
            f"""
            <div style="border:1px solid #ccc;padding:1rem;margin:1rem 0;">
              <h3>{escape(issue.title)}</h3>
              <p><strong>Severity:</strong> {escape(issue.severity.value)} |
                 <strong>Category:</strong> {escape(issue.category)} |
                 <strong>Timestamp:</strong> {escape(issue.timestamp)}
                 <button onclick="jumpTo({issue.timestamp.split(':')[0]}*60+{issue.timestamp.split(':')[1]})">Jump</button>
              </p>
              <p><strong>Expected:</strong> {escape(issue.expected_behavior)}</p>
              <p><strong>Actual:</strong> {escape(issue.actual_behavior or issue.evidence)}</p>
              <p><strong>Evidence:</strong> {escape(issue.evidence_excerpt or issue.evidence)}</p>
              <form method="post" action="/review/calls/{call_id}/issues/{index}">
                <label>Status
                  <select name="review_status">
                    <option value="pending" {"selected" if issue.review_status == "pending" else ""}>pending</option>
                    <option value="approved" {"selected" if issue.review_status == "approved" else ""}>approved</option>
                    <option value="rejected" {"selected" if issue.review_status == "rejected" else ""}>rejected</option>
                  </select>
                </label>
                <label>Severity
                  <select name="severity">
                    {"".join(f"<option value='{sev.value}' {'selected' if issue.severity.value == sev.value else ''}>{sev.value}</option>" for sev in Severity)}
                  </select>
                </label>
                <label>Actual behavior <input type="text" name="actual_behavior" value="{escape(issue.actual_behavior or issue.evidence)}" size="60" /></label>
                <label>Reviewer notes <input type="text" name="review_notes" value="{escape(issue.review_notes or '')}" size="60" /></label>
                <button type="submit">Save Issue</button>
              </form>
            </div>
            """
        )

    quality_form = ""
    if bundle.quality is not None:
        review = bundle.quality.human_review
        quality_form = f"""
        <h2>Voice Quality</h2>
        <p><strong>Overall score:</strong> {bundle.quality.overall_score}</p>
        <form method="post" action="/review/calls/{call_id}/quality">
          <label>Reviewer <input name="reviewer" value="{escape(review.reviewer or '')}" /></label>
          <label>Review date <input name="review_date" type="date" value="{review.review_date or ''}" /></label>
          <label>Naturalness <input name="naturalness" type="number" min="1" max="5" value="{review.naturalness or ''}" /></label>
          <label>Clarity <input name="clarity" type="number" min="1" max="5" value="{review.clarity or ''}" /></label>
          <label>Pacing <input name="pacing" type="number" min="1" max="5" value="{review.pacing or ''}" /></label>
          <label>Persona consistency <input name="persona_consistency" type="number" min="1" max="5" value="{review.persona_consistency or ''}" /></label>
          <label>Turn-taking <input name="turn_taking" type="number" min="1" max="5" value="{review.turn_taking or ''}" /></label>
          <label>Scenario completion <input name="scenario_completion" type="number" min="1" max="5" value="{review.scenario_completion or ''}" /></label>
          <label>Audio quality <input name="audio_quality" type="number" min="1" max="5" value="{review.audio_quality or ''}" /></label>
          <label>Transcript quality <input name="transcript_quality" type="number" min="1" max="5" value="{review.transcript_quality or ''}" /></label>
          <label>Bug evidence <input name="bug_evidence" type="number" min="1" max="5" value="{review.bug_evidence or ''}" /></label>
          <label>Listened end to end <input name="played_from_beginning_to_end" type="checkbox" {_checked(review.played_from_beginning_to_end)} /></label>
          <label>Both speakers audible <input name="both_speakers_audible" type="checkbox" {_checked(review.both_speakers_audible)} /></label>
          <label>Conversation coherent <input name="conversation_coherent" type="checkbox" {_checked(review.conversation_coherent)} /></label>
          <label>Patient sounds natural <input name="patient_sounds_natural" type="checkbox" {_checked(review.patient_sounds_natural)} /></label>
          <label>Turn-taking sensible <input name="turn_taking_sensible" type="checkbox" {_checked(review.turn_taking_sensible)} /></label>
          <label>No major audio glitches <input name="no_major_audio_glitches" type="checkbox" {_checked(review.no_major_audio_glitches)} /></label>
          <label>No excessive delay <input name="no_excessive_delay" type="checkbox" {_checked(review.no_excessive_delay)} /></label>
          <label>Scenario objective pursued <input name="scenario_objective_pursued" type="checkbox" {_checked(review.scenario_objective_pursued)} /></label>
          <label>Final outcome clear <input name="final_outcome_clear" type="checkbox" {_checked(review.final_outcome_clear)} /></label>
          <label>Approved for submission <input name="approved_for_submission" type="checkbox" {_checked(review.approved_for_submission)} /></label>
          <label>Reviewer notes <input name="reviewer_notes" size="70" value="{escape(review.reviewer_notes or '')}" /></label>
          <button type="submit">Save Quality Review</button>
        </form>
        """

    validation_block = ""
    if bundle.validation is not None:
        validation_issues = "".join(
            f"<li>{escape(issue.code)}: {escape(issue.message)}</li>"
            for issue in bundle.validation.issues
        ) or "<li>No validation issues.</li>"
        validation_block = f"""
        <h2>Transcript Validation</h2>
        <p><strong>Passed:</strong> {bundle.validation.passed} |
           <strong>Average confidence:</strong> {bundle.validation.average_confidence:.2f}</p>
        <ul>{validation_issues}</ul>
        """

    audio_block = (
        f"<audio id='call-audio' controls src='{mixed_recording_url}'></audio>"
        if mixed_recording_url
        else "<p>No mixed recording artifact is available for this call yet.</p>"
    )

    submission_form = f"""
    <form method="post" action="/review/calls/{call_id}/submission">
      <label>Submission ready
        <select name="submission_ready">
          <option value="false" {"selected" if not bundle.metadata.submission_ready else ""}>false</option>
          <option value="true" {"selected" if bundle.metadata.submission_ready else ""}>true</option>
        </select>
      </label>
      <label>Call notes <input name="reviewer_notes" size="70" value="{escape(bundle.metadata.reviewer_notes or '')}" /></label>
      <button type="submit">Save Call Review</button>
    </form>
    """

    return _page(
        f"Review {call_id}",
        f"""
        <h1>Review: {escape(call_id)}</h1>
        <p><strong>Scenario:</strong> {escape(bundle.metadata.scenario_id)} |
           <strong>Validation:</strong> {escape(bundle.metadata.transcript_validation_status)} |
           <strong>Submission ready:</strong> {bundle.metadata.submission_ready}</p>
        {audio_block}
        {submission_form}
        {validation_block}
        {quality_form}
        <h2>Issues</h2>
        {''.join(issue_cards) or '<p>No issues for this call.</p>'}
        <h2>Transcript</h2>
        <table border="1" cellpadding="4" cellspacing="0">
          <thead>
            <tr><th>#</th><th>Speaker</th><th>Start</th><th>End</th><th>Action</th><th>Text</th></tr>
          </thead>
          <tbody>
            {''.join(transcript_rows)}
          </tbody>
        </table>
        <script>
        function jumpTo(seconds) {{
          var audio = document.getElementById('call-audio');
          if (audio) {{
            audio.currentTime = seconds;
            audio.play();
          }}
        }}
        </script>
        """,
    )


@router.post("/calls/{call_id}/issues/{issue_index}")
async def update_issue(
    call_id: str,
    issue_index: int,
    review_status: str = Form(...),
    severity: str = Form(...),
    actual_behavior: str = Form(...),
    review_notes: str = Form(""),
) -> RedirectResponse:
    bundle = _load_call_bundle(call_id)
    issue = bundle.evaluation.issues[issue_index]
    issue.review_status = review_status
    issue.severity = Severity(severity)
    issue.actual_behavior = actual_behavior
    issue.review_notes = review_notes or None
    artifact_store.write_evaluation(bundle.evaluation)
    return RedirectResponse(url=f"/review/calls/{call_id}", status_code=303)


@router.post("/calls/{call_id}/quality")
async def update_quality_review(
    call_id: str,
    reviewer: str = Form(""),
    review_date: str = Form(""),
    naturalness: str = Form(""),
    clarity: str = Form(""),
    pacing: str = Form(""),
    persona_consistency: str = Form(""),
    turn_taking: str = Form(""),
    scenario_completion: str = Form(""),
    audio_quality: str = Form(""),
    transcript_quality: str = Form(""),
    bug_evidence: str = Form(""),
    played_from_beginning_to_end: str | None = Form(None),
    both_speakers_audible: str | None = Form(None),
    conversation_coherent: str | None = Form(None),
    patient_sounds_natural: str | None = Form(None),
    turn_taking_sensible: str | None = Form(None),
    no_major_audio_glitches: str | None = Form(None),
    no_excessive_delay: str | None = Form(None),
    scenario_objective_pursued: str | None = Form(None),
    final_outcome_clear: str | None = Form(None),
    approved_for_submission: str | None = Form(None),
    reviewer_notes: str = Form(""),
) -> RedirectResponse:
    bundle = _load_call_bundle(call_id)
    if bundle.quality is None:
        raise HTTPException(status_code=404, detail="No quality artifact found for this call.")
    bundle.quality.human_review.reviewer = reviewer or None
    bundle.quality.human_review.review_date = review_date or None
    bundle.quality.human_review.naturalness = _optional_int(naturalness)
    bundle.quality.human_review.clarity = _optional_int(clarity)
    bundle.quality.human_review.pacing = _optional_int(pacing)
    bundle.quality.human_review.persona_consistency = _optional_int(persona_consistency)
    bundle.quality.human_review.turn_taking = _optional_int(turn_taking)
    bundle.quality.human_review.scenario_completion = _optional_int(scenario_completion)
    bundle.quality.human_review.audio_quality = _optional_int(audio_quality)
    bundle.quality.human_review.transcript_quality = _optional_int(transcript_quality)
    bundle.quality.human_review.bug_evidence = _optional_int(bug_evidence)
    bundle.quality.human_review.played_from_beginning_to_end = _checkbox_to_bool(
        played_from_beginning_to_end
    )
    bundle.quality.human_review.both_speakers_audible = _checkbox_to_bool(
        both_speakers_audible
    )
    bundle.quality.human_review.conversation_coherent = _checkbox_to_bool(
        conversation_coherent
    )
    bundle.quality.human_review.patient_sounds_natural = _checkbox_to_bool(
        patient_sounds_natural
    )
    bundle.quality.human_review.turn_taking_sensible = _checkbox_to_bool(
        turn_taking_sensible
    )
    bundle.quality.human_review.no_major_audio_glitches = _checkbox_to_bool(
        no_major_audio_glitches
    )
    bundle.quality.human_review.no_excessive_delay = _checkbox_to_bool(
        no_excessive_delay
    )
    bundle.quality.human_review.scenario_objective_pursued = _checkbox_to_bool(
        scenario_objective_pursued
    )
    bundle.quality.human_review.final_outcome_clear = _checkbox_to_bool(
        final_outcome_clear
    )
    bundle.quality.human_review.approved_for_submission = _checkbox_to_bool(
        approved_for_submission
    )
    bundle.quality.human_review.reviewer_notes = reviewer_notes or None
    artifact_store.write_model_json(bundle.paths.quality_json, bundle.quality)
    artifact_store.write_markdown(bundle.paths.quality_md, bundle.quality.render_markdown())
    return RedirectResponse(url=f"/review/calls/{call_id}", status_code=303)


@router.post("/calls/{call_id}/submission")
async def update_submission_state(
    call_id: str,
    submission_ready: str = Form(...),
    reviewer_notes: str = Form(""),
) -> RedirectResponse:
    bundle = _load_call_bundle(call_id)
    updated = bundle.metadata.model_copy(
        update={
            "submission_ready": submission_ready.lower() == "true",
            "reviewer_notes": reviewer_notes or None,
        }
    )
    artifact_store.write_metadata(updated)
    return RedirectResponse(url=f"/review/calls/{call_id}", status_code=303)


@router.get("/artifact/{kind}/{filename}")
async def serve_artifact(kind: str, filename: str) -> FileResponse:
    mapping = {
        "recordings": artifact_store.recordings_dir,
        "transcripts": artifact_store.transcripts_dir,
        "quality": artifact_store.quality_dir,
        "validation": artifact_store.validation_dir,
    }
    base = mapping.get(kind)
    if base is None:
        raise HTTPException(status_code=404, detail="Unknown artifact category.")
    path = base / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return FileResponse(path)


class _CallBundle:
    def __init__(
        self,
        *,
        metadata: CallMetadata,
        evaluation: CallEvaluation,
        transcript,
        quality: VoiceQualityReport | None,
        validation: TranscriptValidationReport | None,
        paths,
    ) -> None:
        self.metadata = metadata
        self.evaluation = evaluation
        self.transcript = transcript
        self.quality = quality
        self.validation = validation
        self.paths = paths


def _load_calls() -> list[_CallBundle]:
    bundles: list[_CallBundle] = []
    for metadata_path in sorted(artifact_store.metadata_dir.glob("*.json")):
        bundles.append(_load_call_bundle(metadata_path.stem))
    return bundles


def _load_call_bundle(call_id: str) -> _CallBundle:
    paths = artifact_store.paths_for(call_id)
    if not paths.metadata_json.exists():
        raise HTTPException(status_code=404, detail="Call metadata not found.")
    metadata = CallMetadata.model_validate_json(paths.metadata_json.read_text(encoding="utf-8"))
    evaluation = (
        CallEvaluation.model_validate_json(paths.evaluation_json.read_text(encoding="utf-8"))
        if paths.evaluation_json.exists()
        else CallEvaluation(
            call_id=call_id,
            scenario_id=metadata.scenario_id,
            summary="No evaluation yet.",
            scenario_completed=False,
            agent_outcome="pending",
            expected_outcome="pending",
            scores={"task_completion": 1, "factual_consistency": 1, "scheduling_correctness": 1, "context_retention": 1, "clarification_quality": 1, "safety": 1, "conversation_quality": 1},
            issues=[],
        )
    )
    transcript = None
    if paths.transcript_json.exists():
        from app.analysis.transcript import TranscriptDocument

        transcript = TranscriptDocument.model_validate_json(paths.transcript_json.read_text(encoding="utf-8"))
    else:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    quality = (
        VoiceQualityReport.model_validate_json(paths.quality_json.read_text(encoding="utf-8"))
        if paths.quality_json.exists()
        else None
    )
    validation = (
        TranscriptValidationReport.model_validate_json(paths.validation_json.read_text(encoding="utf-8"))
        if paths.validation_json.exists()
        else None
    )
    return _CallBundle(
        metadata=metadata,
        evaluation=evaluation,
        transcript=transcript,
        quality=quality,
        validation=validation,
        paths=paths,
    )


def _optional_int(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def _checkbox_to_bool(value: str | None) -> bool:
    return value is not None


def _checked(value: bool | None) -> str:
    return "checked" if value else ""


def _page(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>{escape(title)}</title>
        <style>
          body {{ font-family: Georgia, serif; margin: 2rem; line-height: 1.4; }}
          label {{ display: inline-block; margin: 0.4rem 1rem 0.4rem 0; }}
          input, select {{ margin-left: 0.3rem; }}
          table {{ width: 100%; margin-top: 1rem; }}
          td, th {{ vertical-align: top; }}
        </style>
      </head>
      <body>
        <p><a href="/review/">Back to dashboard</a></p>
        {body}
      </body>
    </html>
    """
