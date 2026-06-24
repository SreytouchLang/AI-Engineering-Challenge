from __future__ import annotations

from pathlib import Path

import pytest

from app.safety import (
    AUTHORIZED_DESTINATION,
    RunBudget,
    ensure_real_calls_enabled,
    normalize_e164,
    scan_paths_for_secrets,
    validate_destination,
)


def test_authorized_destination_constant_is_locked() -> None:
    assert AUTHORIZED_DESTINATION == "+18054398008"


def test_normalize_e164_accepts_common_us_formats() -> None:
    assert normalize_e164("(805) 439-8008") == "+18054398008"
    assert normalize_e164("1-555-555-0123") == "+15555550123"


def test_validate_destination_rejects_other_numbers() -> None:
    with pytest.raises(ValueError):
        validate_destination("+15555550123")


def test_real_call_flag_is_required() -> None:
    with pytest.raises(RuntimeError):
        ensure_real_calls_enabled(False)


def test_run_budget_blocks_excess_calls_and_cost() -> None:
    budget = RunBudget(max_calls_per_run=1, monthly_cost_limit_usd=2.0)
    budget.reserve_call(estimated_cost_usd=1.5)
    with pytest.raises(RuntimeError):
        budget.reserve_call(estimated_cost_usd=0.1)

    budget = RunBudget(max_calls_per_run=2, monthly_cost_limit_usd=1.0)
    with pytest.raises(RuntimeError):
        budget.reserve_call(estimated_cost_usd=1.1)


def test_secret_detection_finds_leaked_tokens(tmp_path: Path) -> None:
    secret_file = tmp_path / "secrets.txt"
    secret_file.write_text("OPENAI_API_KEY=sk-testtoken1234567890123456", encoding="utf-8")
    findings = scan_paths_for_secrets([secret_file])
    assert secret_file in findings

