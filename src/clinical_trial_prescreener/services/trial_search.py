"""Version 1 clinical-trial candidate search service."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    StudyType,
    TrialStatus,
)
from clinical_trial_prescreener.infrastructure.clinicaltrials.client import (
    ClinicalTrialsClient,
)
from clinical_trial_prescreener.infrastructure.clinicaltrials.normalizer import (
    normalize_trial,
)

VERSION_1_CONDITION = "Type 2 Diabetes"
VERSION_1_COUNTRY = "India"
VERSION_1_QUERY_TERM = (
    "AREA[StudyType]INTERVENTIONAL "
    "AND AREA[OverallStatus]RECRUITING "
    "AND SEARCH[Location](AREA[LocationCountry]India "
    "AND AREA[LocationStatus]RECRUITING)"
)


class TrialSearchRequest(BaseModel):
    """Version 1 inputs for finding candidate clinical trials."""

    model_config = ConfigDict(extra="forbid")

    condition: str
    country: str
    max_results: int = Field(default=3, ge=1, le=5)

    @field_validator("condition", "country")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, value: str) -> str:
        if value != VERSION_1_CONDITION:
            raise ValueError("Version 1 supports only Type 2 Diabetes")
        return value

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: str) -> str:
        if value != VERSION_1_COUNTRY:
            raise ValueError("Version 1 supports only India")
        return value


class TrialSearchService:
    """Find normalized Version 1 trial candidates using a fixed search policy."""

    def __init__(self, client: ClinicalTrialsClient) -> None:
        self._client = client

    async def search(self, request: TrialSearchRequest) -> list[ClinicalTrial]:
        """Return trials satisfying the Version 1 candidate-search policy."""

        response = await self._client.search_studies(
            condition=request.condition,
            page_size=request.max_results,
            query_term=VERSION_1_QUERY_TERM,
        )
        raw_studies = response.get("studies", [])
        if not isinstance(raw_studies, list):
            raise TypeError("ClinicalTrials.gov response field 'studies' must be a list")

        trials = [normalize_trial(_raw_study(study)) for study in raw_studies]
        return [trial for trial in trials if _is_version_1_candidate(trial, request)]


def _raw_study(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("ClinicalTrials.gov study must be an object")
    return value


def _is_version_1_candidate(
    trial: ClinicalTrial, request: TrialSearchRequest
) -> bool:
    return (
        trial.status is TrialStatus.RECRUITING
        and trial.study_type is StudyType.INTERVENTIONAL
        and any(
            location.country == request.country and location.status == "RECRUITING"
            for location in trial.locations
        )
    )
