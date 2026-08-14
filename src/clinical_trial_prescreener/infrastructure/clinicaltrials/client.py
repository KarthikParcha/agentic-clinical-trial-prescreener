"""Async HTTP client for the ClinicalTrials.gov API v2."""

from typing import Any

import httpx

from clinical_trial_prescreener.config import ClinicalTrialsSettings
from clinical_trial_prescreener.infrastructure.clinicaltrials.exceptions import (
    ClinicalTrialsClientError,
)


class ClinicalTrialsClient:
    """Retrieve raw study-search responses from ClinicalTrials.gov."""

    def __init__(
        self,
        settings: ClinicalTrialsSettings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or ClinicalTrialsSettings()
        self._client = httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=httpx.Timeout(self._settings.timeout_seconds),
            transport=transport,
        )

    async def search_studies(
        self,
        condition: str,
        page_size: int = 10,
        page_token: str | None = None,
        query_term: str | None = None,
    ) -> dict[str, Any]:
        """Return the raw API response for a condition search."""

        self._validate_search_inputs(condition, page_size)
        params: dict[str, str | int] = {
            "query.cond": condition,
            "pageSize": page_size,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        if query_term is not None:
            params["query.term"] = query_term

        try:
            response = await self._client.get("studies", params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise ClinicalTrialsClientError(
                f"ClinicalTrials.gov returned HTTP {error.response.status_code}"
            ) from error
        except httpx.RequestError as error:
            raise ClinicalTrialsClientError(
                "ClinicalTrials.gov request failed"
            ) from error

        try:
            payload = response.json()
        except ValueError as error:
            raise ClinicalTrialsClientError(
                "ClinicalTrials.gov returned invalid JSON"
            ) from error

        if not isinstance(payload, dict):
            raise ClinicalTrialsClientError(
                "ClinicalTrials.gov returned a JSON response that is not an object"
            )
        return payload

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""

        await self._client.aclose()

    def _validate_search_inputs(self, condition: str, page_size: int) -> None:
        if not isinstance(condition, str) or not condition.strip():
            raise ValueError("condition must not be blank")
        if isinstance(page_size, bool) or not isinstance(page_size, int):
            raise TypeError("page_size must be an integer")
        if page_size < 1 or page_size > self._settings.max_page_size:
            raise ValueError(
                f"page_size must be between 1 and {self._settings.max_page_size}"
            )
