from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.safety import AUTHORIZED_DESTINATION, normalize_e164


class AppSettings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    enable_real_calls: bool = Field(default=False, validation_alias="ENABLE_REAL_CALLS")
    authorized_destination: str = Field(
        default=AUTHORIZED_DESTINATION,
        validation_alias="AUTHORIZED_DESTINATION",
    )
    telephony_account_id: str | None = Field(
        default=None,
        validation_alias="TELEPHONY_ACCOUNT_ID",
    )
    telephony_auth_token: str | None = Field(
        default=None,
        validation_alias="TELEPHONY_AUTH_TOKEN",
    )
    telephony_from_number: str | None = Field(
        default=None,
        validation_alias="TELEPHONY_FROM_NUMBER",
    )
    llm_api_key: str | None = Field(default=None, validation_alias="LLM_API_KEY")
    stt_api_key: str | None = Field(default=None, validation_alias="STT_API_KEY")
    tts_api_key: str | None = Field(default=None, validation_alias="TTS_API_KEY")
    public_base_url: AnyHttpUrl | None = Field(
        default=None,
        validation_alias="PUBLIC_BASE_URL",
    )
    max_call_duration_seconds: int = Field(
        default=180,
        validation_alias="MAX_CALL_DURATION_SECONDS",
        ge=30,
        le=900,
    )
    max_calls_per_run: int = Field(
        default=1,
        validation_alias="MAX_CALLS_PER_RUN",
        ge=1,
        le=25,
    )
    monthly_cost_limit_usd: float = Field(
        default=20.0,
        validation_alias="MONTHLY_COST_LIMIT_USD",
        gt=0,
    )

    llm_model: str = "gpt-4o-mini"
    stt_model: str = "gpt-4o-transcribe"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "coral"
    twilio_status_callback_path: str = "/telephony/status"
    twilio_recording_callback_path: str = "/telephony/recording"
    twilio_media_ws_path: str = "/telephony/media-stream"
    outbound_response_timeout_seconds: int = Field(default=20, ge=1, le=120)
    vad_rms_threshold: int = Field(default=300, ge=1, le=5000)
    min_speech_ms: int = Field(default=350, ge=50, le=5000)
    end_of_turn_silence_ms: int = Field(default=850, ge=100, le=5000)
    expected_cost_per_call_usd: float = Field(default=1.25, ge=0)

    @field_validator("authorized_destination")
    @classmethod
    def _validate_authorized_destination(cls, value: str) -> str:
        normalized = normalize_e164(value)
        if normalized != AUTHORIZED_DESTINATION:
            raise ValueError(
                "AUTHORIZED_DESTINATION must remain locked to +18054398008."
            )
        return normalized

    @field_validator("telephony_from_number")
    @classmethod
    def _validate_from_number(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return normalize_e164(value)

    @computed_field  # type: ignore[misc]
    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @computed_field  # type: ignore[misc]
    @property
    def artifacts_root(self) -> Path:
        return self.project_root / "artifacts"

    def require_public_base_url(self) -> str:
        if self.public_base_url is None:
            raise RuntimeError(
                "PUBLIC_BASE_URL is required for webhook-based live call execution."
            )
        return str(self.public_base_url).rstrip("/")

    def media_stream_url(self) -> str:
        base_url = self.require_public_base_url()
        scheme = "wss://" if base_url.startswith("https://") else "ws://"
        host = base_url.split("://", maxsplit=1)[1]
        return f"{scheme}{host}{self.twilio_media_ws_path}"


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
