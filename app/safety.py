from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

AUTHORIZED_DESTINATION = "+18054398008"

E164_PATTERN = re.compile(r"^\+[1-9]\d{9,14}$")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AC[a-fA-F0-9]{32}"),
    re.compile(r"(?im)(?:api[_-]?key|auth[_-]?token)[ \t]*[:=][ \t]*['\"]?([A-Za-z0-9_\-]{12,})['\"]?"),
)


def normalize_e164(number: str) -> str:
    """Normalize a phone number into E.164."""

    digits = re.sub(r"\D", "", number or "")
    if not digits:
        raise ValueError("Phone number is required.")

    if number.strip().startswith("+"):
        normalized = f"+{digits}"
    elif len(digits) == 10:
        normalized = f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        normalized = f"+{digits}"
    else:
        raise ValueError(f"Unable to normalize phone number: {number!r}")

    if not E164_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid E.164 number: {normalized}")
    return normalized


def validate_destination(number: str) -> str:
    """Allow calls only to the challenge's authorized destination."""

    normalized = normalize_e164(number)
    if normalized != AUTHORIZED_DESTINATION:
        raise ValueError(f"Blocked outbound call to unauthorized destination: {normalized}")
    return normalized


def ensure_real_calls_enabled(enabled: bool) -> None:
    if not enabled:
        raise RuntimeError("Real calls are disabled. Re-run with ENABLE_REAL_CALLS=true to continue.")


def mask_phone_number(number: str | None) -> str | None:
    if number is None:
        return None
    normalized = normalize_e164(number)
    if len(normalized) <= 6:
        return normalized
    return f"{normalized[:3]}***{normalized[-4:]}"


def redact_phone_number(number: str | None) -> str | None:
    if number is None:
        return None
    normalized = normalize_e164(number)
    if normalized.startswith("+1") and len(normalized) == 12:
        return "+1" + ("*" * 10)
    visible_prefix = normalized[:2] if len(normalized) > 2 else normalized
    return visible_prefix + ("*" * max(0, len(normalized) - len(visible_prefix)))


def format_phone_number_for_display(number: str) -> str:
    normalized = normalize_e164(number)
    if normalized.startswith("+1") and len(normalized) == 12:
        return f"+1-{normalized[2:5]}-{normalized[5:8]}-{normalized[8:12]}"
    return normalized


def find_secret_like_values(text: str) -> list[str]:
    findings: list[str] = []
    for pattern in SECRET_PATTERNS:
        findings.extend(pattern.findall(text))
    return findings


def scan_paths_for_secrets(paths: list[Path]) -> dict[Path, list[str]]:
    results: dict[Path, list[str]] = {}
    for path in paths:
        if path.is_dir():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings = find_secret_like_values(content)
        if findings:
            results[path] = findings
    return results


@dataclass(slots=True)
class RunBudget:
    max_calls_per_run: int
    monthly_cost_limit_usd: float
    calls_started: int = 0
    projected_cost_usd: float = 0.0

    def reserve_call(self, estimated_cost_usd: float) -> None:
        if self.calls_started >= self.max_calls_per_run:
            raise RuntimeError(f"Call limit reached for this run ({self.max_calls_per_run}).")
        if self.projected_cost_usd + estimated_cost_usd > self.monthly_cost_limit_usd:
            raise RuntimeError("Projected cost would exceed MONTHLY_COST_LIMIT_USD.")
        self.calls_started += 1
        self.projected_cost_usd += estimated_cost_usd
