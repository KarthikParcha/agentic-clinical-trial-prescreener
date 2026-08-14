import asyncio
from collections.abc import Awaitable

import pytest

from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    StudyType,
    TrialStatus,
)
from clinical_trial_prescreener.infrastructure.clinicaltrials.client import (
    ClinicalTrialsClient,
)
from clinical_trial_prescreener.services.trial_search import (
    TrialSearchRequest,
    TrialSearchService,
)


def run(coroutine: Awaitable[list[ClinicalTrial]]) -> list[ClinicalTrial]:
    return asyncio.run(coroutine)


@pytest.mark.integration
def test_live_type_2_diabetes_india_trial_search_returns_valid_candidates() -> None:
    async def search() -> list[ClinicalTrial]:
        client = ClinicalTrialsClient()
        try:
            service = TrialSearchService(client)
            return await service.search(
                TrialSearchRequest(
                    condition="Type 2 Diabetes",
                    country="India",
                    max_results=3,
                )
            )
        finally:
            await client.aclose()

    trials = run(search())

    assert len(trials) <= 3
    for trial in trials:
        assert trial.trial_id
        assert trial.title
        assert trial.status is TrialStatus.RECRUITING
        assert trial.study_type is StudyType.INTERVENTIONAL
        assert any(
            location.country == "India" and location.status == "RECRUITING"
            for location in trial.locations
        )
