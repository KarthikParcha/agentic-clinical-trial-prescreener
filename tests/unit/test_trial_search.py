import asyncio
import json
from collections.abc import Awaitable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from clinical_trial_prescreener.infrastructure.clinicaltrials.exceptions import (
    ClinicalTrialsClientError,
)
from clinical_trial_prescreener.services.trial_search import (
    VERSION_1_QUERY_TERM,
    TrialSearchRequest,
    TrialSearchService,
)

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "type2_diabetes_recruiting_india.json.json"
)


def run(coroutine: Awaitable[object]) -> object:
    return asyncio.run(coroutine)


@pytest.fixture(scope="module")
def raw_trials() -> dict[str, dict[str, Any]]:
    fixture = json.loads(FIXTURE_PATH.read_text())
    return {
        study["protocolSection"]["identificationModule"]["nctId"]: study
        for study in fixture["studies"]
    }


class StubClinicalTrialsClient:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def search_studies(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def request() -> TrialSearchRequest:
    return TrialSearchRequest(condition="Type 2 Diabetes", country="India")


def test_search_passes_version_1_query_and_max_results(
    raw_trials: dict[str, dict[str, Any]],
) -> None:
    client = StubClinicalTrialsClient({"studies": [raw_trials["NCT07438444"]]})
    service = TrialSearchService(client)  # type: ignore[arg-type]

    result = run(
        service.search(
            TrialSearchRequest(
                condition="Type 2 Diabetes", country="India", max_results=5
            )
        )
    )

    assert [trial.trial_id for trial in result] == ["NCT07438444"]
    assert client.calls == [
        {
            "condition": "Type 2 Diabetes",
            "page_size": 5,
            "query_term": VERSION_1_QUERY_TERM,
        }
    ]


def test_returns_recruiting_interventional_trial_with_recruiting_india_site(
    raw_trials: dict[str, dict[str, Any]],
) -> None:
    client = StubClinicalTrialsClient({"studies": [raw_trials["NCT06035874"]]})
    service = TrialSearchService(client)  # type: ignore[arg-type]

    result = run(service.search(request()))

    assert [trial.trial_id for trial in result] == ["NCT06035874"]


@pytest.mark.parametrize(
    ("mutation", "trial_id"),
    [
        (lambda study: _set_overall_status(study, "COMPLETED"), "completed"),
        (lambda study: _set_study_type(study, "OBSERVATIONAL"), "observational"),
        (lambda study: _set_location_status(study, "NOT_YET_RECRUITING"), "india-not-recruiting"),
        (lambda study: _set_other_country_with_non_recruiting_india(study), "other-country-recruiting"),
        (lambda study: _remove_locations(study), "no-locations"),
    ],
)
def test_defensive_filter_rejects_non_candidates(
    raw_trials: dict[str, dict[str, Any]],
    mutation: Any,
    trial_id: str,
) -> None:
    raw_study = deepcopy(raw_trials["NCT06035874"])
    mutation(raw_study)
    client = StubClinicalTrialsClient({"studies": [raw_study]})
    service = TrialSearchService(client)  # type: ignore[arg-type]

    assert run(service.search(request())) == [], trial_id


def test_zero_raw_studies_returns_empty_list() -> None:
    service = TrialSearchService(StubClinicalTrialsClient({"studies": []}))  # type: ignore[arg-type]

    assert run(service.search(request())) == []


def test_client_exception_propagates() -> None:
    service = TrialSearchService(
        StubClinicalTrialsClient(ClinicalTrialsClientError("request failed"))  # type: ignore[arg-type]
    )

    with pytest.raises(ClinicalTrialsClientError, match="request failed"):
        run(service.search(request()))


@pytest.mark.parametrize("max_results", [0, 6])
def test_invalid_max_results_is_rejected(max_results: int) -> None:
    with pytest.raises(ValidationError):
        TrialSearchRequest(
            condition="Type 2 Diabetes", country="India", max_results=max_results
        )


@pytest.mark.parametrize(
    ("condition", "country"),
    [("", "India"), ("Type 2 Diabetes", ""), ("Type 1 Diabetes", "India"), ("Type 2 Diabetes", "United States")],
)
def test_blank_or_unsupported_request_fields_are_rejected(
    condition: str, country: str
) -> None:
    with pytest.raises(ValidationError):
        TrialSearchRequest(condition=condition, country=country)


def _set_overall_status(study: dict[str, Any], value: str) -> None:
    study["protocolSection"]["statusModule"]["overallStatus"] = value


def _set_study_type(study: dict[str, Any], value: str) -> None:
    study["protocolSection"]["designModule"]["studyType"] = value


def _set_location_status(study: dict[str, Any], value: str) -> None:
    study["protocolSection"]["contactsLocationsModule"]["locations"][0]["status"] = value


def _set_other_country_with_non_recruiting_india(study: dict[str, Any]) -> None:
    locations = study["protocolSection"]["contactsLocationsModule"]["locations"]
    locations[0]["status"] = "NOT_YET_RECRUITING"
    locations.append({"country": "United States", "status": "RECRUITING"})


def _remove_locations(study: dict[str, Any]) -> None:
    del study["protocolSection"]["contactsLocationsModule"]
