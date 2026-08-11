from decimal import Decimal

import pytest
from pydantic import ValidationError

from clinical_trial_prescreener.domain.trial import ClinicalTrial, TrialSex


def valid_trial_data() -> dict[str, object]:
    return {
        "trial_id": "NCT07438444",
        "title": "Type 2 Diabetes Treatment Study",
        "official_title": "A Study of Treatment for Type 2 Diabetes",
        "status": "RECRUITING",
        "study_type": "INTERVENTIONAL",
        "phases": ["PHASE3"],
        "conditions": ["Type 2 Diabetes"],
        "interventions": [
            {
                "type": "DRUG",
                "name": "Study Drug",
                "description": "An investigational treatment.",
                "other_names": ["SD-101"],
            }
        ],
        "minimum_age_years": 18,
        "maximum_age_years": 75,
        "sex": "ALL",
        "eligibility_text": "Participants must meet all eligibility criteria.",
        "locations": [
            {
                "facility": "Example Research Centre",
                "status": "RECRUITING",
                "city": "Mumbai",
                "state": "Maharashtra",
                "country": "India",
                "postal_code": "400001",
                "latitude": Decimal("19.0760"),
                "longitude": Decimal("72.8777"),
            }
        ],
    }


def test_valid_normalized_recruiting_interventional_trial() -> None:
    trial = ClinicalTrial(**valid_trial_data())

    assert trial.trial_id == "NCT07438444"
    assert trial.status.value == "RECRUITING"
    assert trial.study_type.value == "INTERVENTIONAL"
    assert trial.sex is TrialSex.ALL


def test_trial_with_multiple_conditions() -> None:
    data = valid_trial_data()
    data["conditions"] = ["Type 2 Diabetes", "Obesity"]

    trial = ClinicalTrial(**data)

    assert trial.conditions == ["Type 2 Diabetes", "Obesity"]


def test_trial_with_multiple_interventions() -> None:
    data = valid_trial_data()
    data["interventions"] = [
        {"type": "DRUG", "name": "Study Drug"},
        {"type": "BEHAVIORAL", "name": "Lifestyle Program"},
    ]

    trial = ClinicalTrial(**data)

    assert [intervention.name for intervention in trial.interventions] == [
        "Study Drug",
        "Lifestyle Program",
    ]


def test_trial_with_multiple_locations() -> None:
    data = valid_trial_data()
    data["locations"] = [
        {"facility": "Mumbai Site", "country": "India"},
        {"facility": "Delhi Site", "country": "India"},
    ]

    trial = ClinicalTrial(**data)

    assert [location.facility for location in trial.locations] == [
        "Mumbai Site",
        "Delhi Site",
    ]


def test_trial_without_maximum_age() -> None:
    data = valid_trial_data()
    data["maximum_age_years"] = None

    trial = ClinicalTrial(**data)

    assert trial.maximum_age_years is None


def test_trial_without_locations() -> None:
    data = valid_trial_data()
    data["locations"] = []

    trial = ClinicalTrial(**data)

    assert trial.locations == []


def test_trial_without_eligibility_text() -> None:
    data = valid_trial_data()
    data["eligibility_text"] = None

    trial = ClinicalTrial(**data)

    assert trial.eligibility_text is None


def test_blank_trial_id_is_rejected() -> None:
    data = valid_trial_data()
    data["trial_id"] = " "

    with pytest.raises(ValidationError, match="must not be blank"):
        ClinicalTrial(**data)


def test_blank_title_is_rejected() -> None:
    data = valid_trial_data()
    data["title"] = " "

    with pytest.raises(ValidationError, match="must not be blank"):
        ClinicalTrial(**data)


def test_negative_minimum_age_is_rejected() -> None:
    data = valid_trial_data()
    data["minimum_age_years"] = -1

    with pytest.raises(ValidationError, match="must not be negative"):
        ClinicalTrial(**data)


def test_maximum_age_below_minimum_age_is_rejected() -> None:
    data = valid_trial_data()
    data["minimum_age_years"] = 65
    data["maximum_age_years"] = 18

    with pytest.raises(
        ValidationError,
        match="maximum_age_years cannot be lower than minimum_age_years",
    ):
        ClinicalTrial(**data)


def test_blank_location_country_is_rejected() -> None:
    data = valid_trial_data()
    data["locations"] = [{"country": "  "}]

    with pytest.raises(ValidationError, match="must not be blank"):
        ClinicalTrial(**data)


def test_unexpected_field_is_rejected() -> None:
    data = valid_trial_data()
    data["protocolSection"] = {}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ClinicalTrial(**data)
