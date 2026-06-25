"""Two-AI voice simulator (free, offline).

Runs the patient bot against the clinic agent simulator, synthesizes the whole
conversation into a real, listenable MP3 with free local TTS, re-times the
transcript to the audio, evaluates the agent, and writes an aggregate bug
report. No telephony, no API keys, no cost.

Examples:
    python scripts/run_voice_sim.py --all
    python scripts/run_voice_sim.py --scenario scenarios/07_weekend_request.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.dry_run import DryRunConversationRunner
from app.agent.scenario_loader import Scenario, load_scenario, load_scenarios
from app.analysis.evaluator import ConversationEvaluator
from app.analysis.schemas import CallEvaluation, EvaluationIssue, Severity
from app.config import AppSettings, get_settings
from app.storage.artifacts import ArtifactStore
from app.storage.recording_builder import build_spoken_recordings
from app.voice.local_tts import (
    DEFAULT_AGENT_VOICE,
    DEFAULT_PATIENT_VOICE,
    tts_available,
)

_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
_REPORT_PATH = PROJECT_ROOT / "VOICE_SIM_BUG_REPORT.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the free two-AI voice simulator.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario", help="Path to a single scenario YAML.")
    group.add_argument("--all", action="store_true", help="Run every scenario in scenarios/.")
    parser.add_argument("--patient-voice", default=DEFAULT_PATIENT_VOICE)
    parser.add_argument("--agent-voice", default=DEFAULT_AGENT_VOICE)
    parser.add_argument("--call-id", help="Explicit call id (single-scenario runs only).")
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="First call number when running --all (default: 1).",
    )
    return parser.parse_args()


def _overall_quality(evaluation: CallEvaluation) -> int:
    scores = evaluation.scores
    values = [
        scores.task_completion,
        scores.factual_consistency,
        scores.scheduling_correctness,
        scores.context_retention,
        scores.clarification_quality,
        scores.safety,
        scores.conversation_quality,
    ]
    return round(sum(values) / len(values))


def run_one(
    *,
    settings: AppSettings,
    scenario: Scenario,
    artifact_store: ArtifactStore,
    call_id: str,
    patient_voice: str,
    agent_voice: str,
) -> CallEvaluation:
    artifact_store.reserve_call_id(call_id)

    # 1. Generate the conversation text (offline patient + clinic agent).
    result = DryRunConversationRunner(settings, scenario).run(call_id=call_id)

    # 2. Synthesize real audio and re-time the transcript to match it.
    _, mixed_path, transcript = build_spoken_recordings(
        transcript=result.transcript,
        artifact_store=artifact_store,
        patient_voice=patient_voice,
        agent_voice=agent_voice,
    )
    artifact_store.write_transcript(transcript)

    # 3. Evaluate the agent's behavior and persist the findings.
    evaluation = ConversationEvaluator().evaluate(scenario, transcript)
    quality = _overall_quality(evaluation)
    evaluation = evaluation.model_copy(update={"quality_score": quality})
    artifact_store.write_evaluation(evaluation)

    # 4. Write consistent metadata for the spoken call.
    now = datetime.now(UTC)
    metadata = result.metadata.model_copy(
        update={
            "provider": "local_voice_sim",
            "mode": "voice_sim",
            "is_real_call": False,
            "duration_seconds": transcript.duration_seconds,
            "end_time": now,
            "transcript_path": f"artifacts/transcripts/{call_id}.txt",
            "transcript_source": "voice_sim_synthesis",
            "transcript_strategy": "voice_sim_sequential_turns",
            "recording_path": f"artifacts/recordings/{mixed_path.name}",
            "patient_recording_path": f"artifacts/recordings/{call_id}-patient.wav",
            "agent_recording_path": f"artifacts/recordings/{call_id}-agent.wav",
            "mixed_recording_path": f"artifacts/recordings/{mixed_path.name}",
            "quality_score": quality,
            "average_transcript_confidence": 1.0,
            "analysis_completion_status": "completed",
            "model_names": {"tts": "macos-say", "agent": "rule-based-simulator"},
        }
    )
    artifact_store.write_metadata(metadata)
    return evaluation


def write_bug_report(evaluations: list[CallEvaluation]) -> int:
    rows: list[tuple[Severity, str, EvaluationIssue]] = []
    for evaluation in evaluations:
        for issue in evaluation.issues:
            rows.append((issue.severity, evaluation.call_id, issue))
    rows.sort(key=lambda row: (_SEVERITY_ORDER.index(row[0]), row[1]))

    lines = [
        "# Voice Simulator Bug Report",
        "",
        f"Generated: {datetime.now(UTC).date().isoformat()}",
        "",
        "Findings from the free two-AI voice simulator. Each conversation was "
        "synthesized to real audio and transcribed; listen at the cited timestamp "
        "in the matching recording to reproduce.",
        "",
        f"Calls evaluated: {len(evaluations)} | Total findings: {len(rows)}",
        "",
    ]
    if not rows:
        lines.append("No issues detected across the evaluated conversations.")
    for severity, call_id, issue in rows:
        lines += [
            f"## [{severity.value.upper()}] {issue.title}",
            "",
            f"- **Call:** {call_id} at {issue.timestamp}",
            f"- **Category:** {issue.category}",
            f"- **Recording:** artifacts/recordings/{call_id}-mixed.mp3",
            f"- **What happened:** {issue.actual_behavior or issue.evidence}",
            f"- **Expected:** {issue.expected_behavior}",
            f"- **Why it matters:** {issue.user_impact}",
            "",
        ]
    _REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def main() -> None:
    args = parse_args()
    if not tts_available():
        raise SystemExit("Voice simulator needs `say` (macOS) and `ffmpeg` on PATH. Install ffmpeg with `brew install ffmpeg`.")

    settings = get_settings()
    artifact_store = ArtifactStore(settings.artifacts_root)

    if args.all:
        scenarios = load_scenarios(settings.project_root / "scenarios")
    else:
        scenarios = [load_scenario(args.scenario)]
        if args.call_id is None and len(scenarios) == 1:
            args.call_id = artifact_store.next_call_id()

    results: list[dict[str, object]] = []
    index = args.start_index
    for scenario in scenarios:
        if args.all or args.call_id is None:
            call_id = f"call-{index:03d}"
            while artifact_store.paths_for(call_id).metadata_json.exists():
                index += 1
                call_id = f"call-{index:03d}"
        else:
            call_id = args.call_id
        index += 1

        evaluation = run_one(
            settings=settings,
            scenario=scenario,
            artifact_store=artifact_store,
            call_id=call_id,
            patient_voice=args.patient_voice,
            agent_voice=args.agent_voice,
        )
        results.append(
            {
                "call_id": call_id,
                "scenario_id": scenario.id,
                "quality_score": evaluation.quality_score,
                "issues": len(evaluation.issues),
                "recording": f"artifacts/recordings/{call_id}-mixed.mp3",
            }
        )

    # Always rebuild the report from every evaluation on disk so a single-scenario
    # run never clobbers the aggregate findings from the full suite.
    total_findings = write_bug_report(artifact_store.list_evaluations())
    print(
        json.dumps(
            {
                "mode": "voice_sim",
                "calls": len(results),
                "total_findings": total_findings,
                "bug_report": str(_REPORT_PATH.relative_to(PROJECT_ROOT)),
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
