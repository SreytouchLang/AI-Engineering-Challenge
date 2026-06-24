from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.agent.dry_run import DryRunConversationRunner
from app.agent.scenario_loader import Scenario, load_scenarios
from app.analysis.evaluator import ConversationEvaluator
from app.analysis.quality import VoiceQualityAnalyzer
from app.analysis.validation import TranscriptValidator
from app.config import AppSettings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata
from app.storage.recording_builder import build_dry_run_recordings


class ExperimentVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    response_style: str


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    baseline: ExperimentVariant
    candidate: ExperimentVariant
    scenarios: list[str]
    budget_limit_usd: float = Field(gt=0)
    maximum_calls: int = Field(ge=2)


@dataclass(slots=True)
class VariantSummary:
    variant_id: str
    average_quality_score: float
    average_patient_words: float
    validation_pass_rate: float
    issue_count: int
    calls: list[dict[str, object]]


class ExperimentRunner:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.scenario_index = {
            scenario.id: scenario for scenario in load_scenarios(settings.project_root / "scenarios")
        }

    def load_config(self, path: Path) -> ExperimentConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return ExperimentConfig.model_validate(raw)

    def run(self, config: ExperimentConfig) -> dict[str, object]:
        variants = [config.baseline, config.candidate]
        temp_store = ArtifactStore(
            self.settings.project_root / "tmp" / "experiments" / config.id / "artifacts"
        )
        summaries = [
            self._run_variant(config, variant, temp_store)
            for variant in variants
        ]
        winner = max(summaries, key=lambda summary: summary.average_quality_score)
        return {
            "experiment_id": config.id,
            "scenarios": config.scenarios,
            "baseline": _summary_to_dict(summaries[0]),
            "candidate": _summary_to_dict(summaries[1]),
            "winner": winner.variant_id,
            "note": (
                "Dry-run comparison only. Use this as a pre-live tuning signal, "
                "not as substitute evidence for the required real calls."
            ),
        }

    def write_results(self, config: ExperimentConfig, results: dict[str, object]) -> tuple[Path, Path]:
        output_dir = self.settings.project_root / "experiments" / config.id
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "results.json"
        md_path = output_dir / "results.md"
        json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        md_path.write_text(_render_results_markdown(results), encoding="utf-8")
        return json_path, md_path

    def _run_variant(
        self,
        config: ExperimentConfig,
        variant: ExperimentVariant,
        temp_store: ArtifactStore,
    ) -> VariantSummary:
        calls: list[dict[str, object]] = []
        quality_scores: list[int] = []
        patient_word_counts: list[float] = []
        validation_passes = 0
        issue_count = 0

        for index, scenario_id in enumerate(config.scenarios, start=1):
            scenario = self.scenario_index[scenario_id]
            call_id = f"{config.id}-{variant.id}-{index:02d}"
            transcript, metadata = self._run_single_call(
                call_id=call_id,
                scenario=scenario,
                temp_store=temp_store,
                response_style=variant.response_style,
            )
            paths = temp_store.paths_for(call_id)
            validation = TranscriptValidator(
                gap_threshold_ms=self.settings.transcript_gap_threshold_ms,
                confidence_threshold=self.settings.transcript_confidence_threshold,
                duration_tolerance_seconds=self.settings.duration_mismatch_tolerance_seconds,
            ).validate(transcript, metadata, paths)
            quality = VoiceQualityAnalyzer().build_report(transcript, metadata, validation, paths)
            evaluation = ConversationEvaluator().evaluate(scenario, transcript)
            quality_scores.append(quality.overall_score)
            patient_word_counts.append(
                _average(
                    [
                        len(segment.text.split())
                        for segment in transcript.segments
                        if segment.speaker == "PATIENT"
                    ]
                )
            )
            validation_passes += int(validation.passed)
            issue_count += len(evaluation.issues)
            calls.append(
                {
                    "call_id": call_id,
                    "scenario_id": scenario_id,
                    "quality_score": quality.overall_score,
                    "validation_passed": validation.passed,
                    "issue_count": len(evaluation.issues),
                    "average_patient_words": patient_word_counts[-1],
                }
            )

        return VariantSummary(
            variant_id=variant.id,
            average_quality_score=round(_average(quality_scores), 2),
            average_patient_words=round(_average(patient_word_counts), 2),
            validation_pass_rate=round(validation_passes / max(1, len(config.scenarios)), 2),
            issue_count=issue_count,
            calls=calls,
        )

    def _run_single_call(
        self,
        *,
        call_id: str,
        scenario: Scenario,
        temp_store: ArtifactStore,
        response_style: str,
    ) -> tuple:
        result = DryRunConversationRunner(
            self.settings,
            scenario,
            response_style=response_style,
        ).run(call_id=call_id)
        temp_store.write_transcript(result.transcript)
        _, mixed_path = build_dry_run_recordings(
            transcript=result.transcript,
            artifact_store=temp_store,
        )
        metadata = result.metadata.model_copy(
            update={
                "recording_path": f"artifacts/recordings/{mixed_path.name}",
                "patient_recording_path": f"artifacts/recordings/{call_id}-patient.wav",
                "agent_recording_path": f"artifacts/recordings/{call_id}-agent.wav",
                "mixed_recording_path": f"artifacts/recordings/{mixed_path.name}",
                "transcript_path": f"artifacts/transcripts/{call_id}.txt",
                "average_transcript_confidence": 1.0,
            }
        )
        temp_store.write_metadata(metadata)
        return result.transcript, metadata


def _summary_to_dict(summary: VariantSummary) -> dict[str, object]:
    return {
        "variant_id": summary.variant_id,
        "average_quality_score": summary.average_quality_score,
        "average_patient_words": summary.average_patient_words,
        "validation_pass_rate": summary.validation_pass_rate,
        "issue_count": summary.issue_count,
        "calls": summary.calls,
    }


def _render_results_markdown(results: dict[str, object]) -> str:
    baseline = results["baseline"]
    candidate = results["candidate"]
    return (
        f"# Experiment: {results['experiment_id']}\n\n"
        f"- Winner: `{results['winner']}`\n"
        f"- Note: {results['note']}\n\n"
        "## Summary\n\n"
        f"- Baseline average quality: `{baseline['average_quality_score']}`\n"
        f"- Candidate average quality: `{candidate['average_quality_score']}`\n"
        f"- Baseline average patient words: `{baseline['average_patient_words']}`\n"
        f"- Candidate average patient words: `{candidate['average_patient_words']}`\n"
        f"- Baseline validation pass rate: `{baseline['validation_pass_rate']}`\n"
        f"- Candidate validation pass rate: `{candidate['validation_pass_rate']}`\n"
    )


def _average(values: list[float | int]) -> float:
    if not values:
        return 0.0
    return sum(float(value) for value in values) / len(values)
