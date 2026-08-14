"""Application configuration models."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClinicalTrialsSettings(BaseSettings):
    """Configuration for ClinicalTrials.gov API access."""

    model_config = SettingsConfigDict(env_prefix="CLINICAL_TRIALS_")

    base_url: str = "https://clinicaltrials.gov/api/v2"
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_page_size: int = Field(default=1000, ge=1)


class GroqSettings(BaseSettings):
    """Configuration for Groq-hosted language-model requests."""

    model_config = SettingsConfigDict(
        env_prefix="GROQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: SecretStr
    llm_model: str = "llama-3.3-70b-versatile"

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value
