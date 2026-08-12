import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from clinical_trial_prescreener.infrastructure.clinicaltrials.normalizer import (
    normalize_trial,
)

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "type2_diabetes_recruiting_india.json.json"
)


@pytest.fixture(scope="module")
def raw_studies() -> dict[str, dict]:
    fixture = json.loads(FIXTURE_PATH.read_text())
    return {
        study["protocolSection"]["identificationModule"]["nctId"]: study
        for study in fixture["studies"]
    }


def test_normalizes_nct06035874_from_recruiting_india_fixture(
    raw_studies: dict[str, dict],
) -> None:
    trial = normalize_trial(raw_studies["NCT06035874"])

    assert trial.trial_id == "NCT06035874"
    assert trial.title.startswith("Effect of Bempedoic Acid")
    assert trial.status.value == "RECRUITING"
    assert trial.study_type.value == "INTERVENTIONAL"
    assert trial.conditions == ["Type 2 Diabetes", "Non Alcholic Fatty Liver Disease"]
    assert trial.phases == ["NA"]
    assert trial.minimum_age_years == 20
    assert trial.maximum_age_years is None
    assert trial.eligibility_text is not None
    assert trial.eligibility_text.startswith("Inclusion Criteria:")


def test_normalizes_nct07438444_from_recruiting_india_fixture(
    raw_studies: dict[str, dict],
) -> None:
    trial = normalize_trial(raw_studies["NCT07438444"])

    assert trial.trial_id == "NCT07438444"
    assert trial.status.value == "RECRUITING"
    assert trial.study_type.value == "INTERVENTIONAL"
    assert trial.conditions == ["Diabetes Mellitus, Type 2", "Obesity", "Overweight"]
    assert trial.phases == ["PHASE4"]
    assert trial.minimum_age_years == 18
    assert trial.interventions[0].name == "Tirzepatide"
    assert trial.interventions[0].other_names == ["LY3298176"]

    location = trial.locations[0]
    assert location.facility == "B. J. Medical College & Civil Hospital"
    assert location.city == "Ahmedabad"
    assert location.state is None
    assert location.country == "India"
    assert location.postal_code == "380 016"
    assert location.latitude == Decimal("23.02579")
    assert location.longitude == Decimal("72.58727")


def test_missing_locations_becomes_empty_list(raw_studies: dict[str, dict]) -> None:
    raw_study = deepcopy(raw_studies["NCT06035874"])
    del raw_study["protocolSection"]["contactsLocationsModule"]

    trial = normalize_trial(raw_study)

    assert trial.locations == []


def test_missing_official_title_remains_none(raw_studies: dict[str, dict]) -> None:
    raw_study = deepcopy(raw_studies["NCT06035874"])
    del raw_study["protocolSection"]["identificationModule"]["officialTitle"]

    trial = normalize_trial(raw_study)

    assert trial.official_title is None


def test_malformed_age_fails_clearly(raw_studies: dict[str, dict]) -> None:
    raw_study = deepcopy(raw_studies["NCT06035874"])
    raw_study["protocolSection"]["eligibilityModule"]["minimumAge"] = "Twenty Years"

    with pytest.raises(ValueError, match="Unsupported age format"):
        normalize_trial(raw_study)


@pytest.mark.parametrize("field", ["nctId", "briefTitle"])
def test_missing_required_identification_data_fails_clearly(
    raw_studies: dict[str, dict], field: str
) -> None:
    raw_study = deepcopy(raw_studies["NCT06035874"])
    del raw_study["protocolSection"]["identificationModule"][field]

    with pytest.raises(ValueError, match=f"Missing or invalid required value: {field}"):
        normalize_trial(raw_study)
