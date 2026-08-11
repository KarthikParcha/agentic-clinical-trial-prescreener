from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from clinical_trial_prescreener.domain.patient import (
    MedicalCondition,
    Medication,
    PatientProfile,
    PregnancyStatus,
)


def valid_patient_data() -> dict[str, object]:
    return {
        "patient_id": "DEMO-P001",
        "age": 48,
        "sex": "FEMALE",
        "country": "India",
        "condition": "Type 2 Diabetes",
        "consent_for_demo": True,
    }


def test_valid_complete_synthetic_patient() -> None:
    patient = PatientProfile(
        **valid_patient_data(),
        diagnosis_date=date(2021, 4, 10),
        diagnosis_duration_years=Decimal("5.3"),
        height=Decimal(170),
        weight=Decimal(84),
        bmi=Decimal("29.1"),
        laboratory_results=[
            {
                "test_name": "HbA1c",
                "value": Decimal("8.2"),
                "unit": "%",
                "measured_date": date(2026, 7, 15),
                "reference_range": "4.0-5.6",
            }
        ],
        medications=[
            {
                "medication_name": "Metformin",
                "status": "CURRENT",
                "start_date": date(2024, 1, 10),
                "dosage": "500 mg",
                "frequency": "Twice daily",
            }
        ],
        medical_history=[
            {
                "condition_name": "Hypertension",
                "status": "ACTIVE",
                "diagnosis_date": date(2020, 1, 1),
                "notes": "Managed with medication.",
            }
        ],
        pregnancy_status="UNKNOWN",
        currently_in_trial=None,
    )

    assert patient.laboratory_results[0].value == Decimal("8.2")
    assert patient.medications[0].dosage == "500 mg"
    assert patient.medical_history[0].status.value == "ACTIVE"


def test_valid_patient_with_optional_data_missing() -> None:
    patient = PatientProfile(**valid_patient_data())

    assert patient.diagnosis_date is None
    assert patient.laboratory_results == []
    assert patient.medications == []
    assert patient.medical_history == []
    assert patient.currently_in_trial is None


def test_missing_required_patient_id_is_rejected() -> None:
    data = valid_patient_data()
    del data["patient_id"]

    with pytest.raises(ValidationError):
        PatientProfile(**data)


def test_blank_patient_id_is_rejected() -> None:
    data = valid_patient_data()
    data["patient_id"] = "  "

    with pytest.raises(ValidationError, match="must not be blank"):
        PatientProfile(**data)


@pytest.mark.parametrize("age", [0, -1])
def test_non_positive_age_is_rejected(age: int) -> None:
    data = valid_patient_data()
    data["age"] = age

    with pytest.raises(ValidationError, match="must be greater than zero"):
        PatientProfile(**data)


def test_unsupported_condition_is_rejected() -> None:
    data = valid_patient_data()
    data["condition"] = "Type 1 Diabetes"

    with pytest.raises(ValidationError, match="Version 1 supports only Type 2 Diabetes"):
        PatientProfile(**data)


def test_false_demo_consent_is_rejected() -> None:
    data = valid_patient_data()
    data["consent_for_demo"] = False

    with pytest.raises(ValidationError, match="consent_for_demo must be true"):
        PatientProfile(**data)


def test_invalid_medication_date_ordering_is_rejected() -> None:
    with pytest.raises(ValidationError, match="end_date cannot be before start_date"):
        Medication(
            medication_name="Metformin",
            status="DISCONTINUED",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 1, 31),
        )


def test_invalid_medical_history_date_ordering_is_rejected() -> None:
    with pytest.raises(ValidationError, match="resolved_date cannot be before diagnosis_date"):
        MedicalCondition(
            condition_name="Hypertension",
            status="RESOLVED",
            diagnosis_date=date(2024, 2, 1),
            resolved_date=date(2024, 1, 31),
        )


def test_false_currently_in_trial_is_preserved() -> None:
    patient = PatientProfile(**valid_patient_data(), currently_in_trial=False)

    assert patient.currently_in_trial is False


def test_null_currently_in_trial_is_preserved() -> None:
    patient = PatientProfile(**valid_patient_data(), currently_in_trial=None)

    assert patient.currently_in_trial is None


def test_unknown_pregnancy_status_is_preserved() -> None:
    patient = PatientProfile(**valid_patient_data(), pregnancy_status="UNKNOWN")

    assert patient.pregnancy_status is PregnancyStatus.UNKNOWN


def test_unexpected_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PatientProfile(**valid_patient_data(), unsupported_field="value")
