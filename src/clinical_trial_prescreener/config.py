"""Application configuration models."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClinicalTrialsSettings(BaseSettings):
    """Configuration for ClinicalTrials.gov API access."""

    model_config = SettingsConfigDict(env_prefix="CLINICAL_TRIALS_")

    base_url: str = "https://clinicaltrials.gov/api/v2"
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_page_size: int = Field(default=1000, ge=1)
