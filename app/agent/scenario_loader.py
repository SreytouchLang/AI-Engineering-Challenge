from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.safety import normalize_e164


class ScenarioPatient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tone: str
    speaking_style: str = "natural"


class ScenarioBackground(BaseModel):
    model_config = ConfigDict(extra="allow")

    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class ScenarioGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str
    acceptable_outcomes: list[str] = Field(default_factory=list)


class ScenarioFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disclose_initially: list[str] = Field(default_factory=list)
    disclose_if_asked: dict[str, str] = Field(default_factory=dict)
    withhold_until_needed: list[str] = Field(default_factory=list)

    @field_validator("disclose_if_asked")
    @classmethod
    def _validate_callback_numbers(cls, value: dict[str, str]) -> dict[str, str]:
        if "callback_number" in value:
            value["callback_number"] = normalize_e164(value["callback_number"])
        return value


class ScenarioConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_duration_seconds: int = Field(ge=30, le=600)
    allow_interruption: bool = False
    max_turns: int = Field(default=18, ge=2, le=40)


class ScenarioEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high_severity_failures: list[str] = Field(default_factory=list)
    medium_severity_failures: list[str] = Field(default_factory=list)
    success_signals: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    category: str
    patient: ScenarioPatient
    background: ScenarioBackground
    goal: ScenarioGoal
    facts: ScenarioFacts
    constraints: ScenarioConstraints
    evaluation: ScenarioEvaluation
    follow_up_questions: list[str] = Field(default_factory=list)
    failure_signals: list[str] = Field(default_factory=list)
    desired_outcome: str

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not value.replace("_", "").isalnum() or value.lower() != value:
            raise ValueError("Scenario ids must be lowercase snake_case.")
        return value

    @field_validator("category")
    @classmethod
    def _validate_category(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Scenario category is required.")
        return value


def load_scenario(path: str | Path) -> Scenario:
    raw = Path(path)
    data = yaml.safe_load(raw.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Scenario file did not contain a mapping: {raw}")
    return Scenario.model_validate(data)


def load_scenarios(directory: str | Path) -> list[Scenario]:
    base = Path(directory)
    return [load_scenario(path) for path in sorted(base.glob("*.yaml"))]
