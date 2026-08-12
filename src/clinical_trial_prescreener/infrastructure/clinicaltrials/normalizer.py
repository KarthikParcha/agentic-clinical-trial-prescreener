"""Deterministic normalization of ClinicalTrials.gov study records."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from clinical_trial_prescreener.domain.trial import (
    ClinicalTrial,
    Intervention,
    StudyType,
    TrialLocation,
    TrialSex,
    TrialStatus,
)

_AGE_PATTERN = re.compile(r"^(0|[1-9]\d*) Years?$")


def normalize_trial(raw_study: dict[str, Any]) -> ClinicalTrial:
    """Convert one raw ClinicalTrials.gov study into an internal trial model."""

    protocol_section = _required_mapping(raw_study, "protocolSection")
    identification = _required_mapping(protocol_section, "identificationModule")
    status = _required_mapping(protocol_section, "statusModule")
    design = _required_mapping(protocol_section, "designModule")
    eligibility = _optional_mapping(protocol_section, "eligibilityModule")

    return ClinicalTrial(
        trial_id=_required_string(identification, "nctId"),
        title=_required_string(identification, "briefTitle"),
        official_title=_optional_string(identification, "officialTitle"),
        status=_normalize_status(_required_string(status, "overallStatus")),
        study_type=StudyType(_required_string(design, "studyType")),
        phases=_optional_string_list(design, "phases"),
        conditions=_optional_string_list(
            _optional_mapping(protocol_section, "conditionsModule"), "conditions"
        ),
        interventions=_normalize_interventions(
            _optional_mapping(protocol_section, "armsInterventionsModule")
        ),
        minimum_age_years=_parse_age(eligibility.get("minimumAge")),
        maximum_age_years=_parse_age(eligibility.get("maximumAge")),
        sex=_normalize_sex(eligibility.get("sex")),
        eligibility_text=_optional_string(eligibility, "eligibilityCriteria"),
        locations=_normalize_locations(
            _optional_mapping(protocol_section, "contactsLocationsModule")
        ),
    )


def _required_mapping(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if value is None:
        raise ValueError(f"Missing required object: {key}")
    if not isinstance(value, dict):
        raise TypeError(f"Invalid object: {key}")
    return value


def _optional_mapping(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"Invalid object: {key}")
    return value


def _required_string(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid required value: {key}")
    return value


def _optional_string(source: dict[str, Any], key: str) -> str | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"Invalid string value: {key}")
    return value


def _optional_string_list(source: dict[str, Any], key: str) -> list[str]:
    value = source.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"Invalid string list: {key}")
    return value


def _parse_age(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Age must be a string in whole years")

    match = _AGE_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Unsupported age format: {value!r}")
    return int(match.group(1))


def _normalize_status(value: str) -> TrialStatus:
    try:
        return TrialStatus(value)
    except ValueError:
        return TrialStatus.UNKNOWN


def _normalize_sex(value: object) -> TrialSex | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Invalid sex value")
    return TrialSex(value)


def _normalize_interventions(module: dict[str, Any]) -> list[Intervention]:
    interventions = module.get("interventions")
    if interventions is None:
        return []
    if not isinstance(interventions, list):
        raise TypeError("Invalid interventions list")

    normalized: list[Intervention] = []
    for intervention in interventions:
        if not isinstance(intervention, dict):
            raise TypeError("Invalid intervention")
        normalized.append(
            Intervention(
                type=_required_string(intervention, "type"),
                name=_required_string(intervention, "name"),
                description=_optional_string(intervention, "description"),
                other_names=_optional_string_list(intervention, "otherNames"),
            )
        )
    return normalized


def _normalize_locations(module: dict[str, Any]) -> list[TrialLocation]:
    locations = module.get("locations")
    if locations is None:
        return []
    if not isinstance(locations, list):
        raise TypeError("Invalid locations list")

    normalized: list[TrialLocation] = []
    for location in locations:
        if not isinstance(location, dict):
            raise TypeError("Invalid location")
        geo_point = _optional_mapping(location, "geoPoint")
        normalized.append(
            TrialLocation(
                facility=_optional_string(location, "facility"),
                status=_optional_string(location, "status"),
                city=_optional_string(location, "city"),
                state=_optional_string(location, "state"),
                country=_required_string(location, "country"),
                postal_code=_optional_string(location, "zip"),
                latitude=_optional_decimal(geo_point, "lat"),
                longitude=_optional_decimal(geo_point, "lon"),
            )
        )
    return normalized


def _optional_decimal(source: dict[str, Any], key: str) -> Decimal | None:
    value = source.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"Invalid decimal value: {key}")
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"Invalid decimal value: {key}") from error
