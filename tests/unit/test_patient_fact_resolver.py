from datetime import date
from decimal import Decimal

from clinical_trial_prescreener.domain.criterion import TemporalWindow
from clinical_trial_prescreener.domain.patient import PatientProfile
from clinical_trial_prescreener.services.patient_fact_resolver import (
    PatientFactResolver,
)

REFERENCE_DATE = date(2026, 7, 15)


def synthetic_patient() -> PatientProfile:
    return PatientProfile(
        patient_id="DEMO-P001",
        age=48,
        sex="FEMALE",
        country="India",
        condition="Type 2 Diabetes",
        consent_for_demo=True,
        diagnosis_date=date(2022, 6, 15),
        laboratory_results=[{"test_name": "HbA1c", "value": "8.2", "unit": "%"}],
        bmi=Decimal("29.1"),
        medications=[{"medication_name": "Metformin", "status": "CURRENT"}],
        medical_history=[
            {
                "condition_name": "Heart attack",
                "status": "RESOLVED",
                "diagnosis_date": date(2025, 1, 1),
            },
            {
                "condition_name": "Stroke",
                "status": "RESOLVED",
                "diagnosis_date": date(2025, 1, 1),
            },
            {
                "condition_name": "Congestive heart failure",
                "status": "ACTIVE",
                "notes": "NYHA Class II",
            },
            {"condition_name": "Morbid obesity", "status": "RESOLVED"},
        ],
    )


def test_resolves_version_1_canonical_facts_from_actual_patient_fields() -> None:
    resolver = PatientFactResolver(reference_date=REFERENCE_DATE)
    patient = synthetic_patient()

    assert resolver.resolve(patient, "diagnosis_duration_years").value > Decimal(4)
    assert resolver.resolve(patient, "insulin_naive").value is True
    assert resolver.resolve(patient, "hba1c").value == Decimal("8.2")
    assert resolver.resolve(patient, "bmi").value == Decimal("29.1")
    assert resolver.resolve(patient, "type_1_diabetes").value is False
    assert resolver.resolve(patient, "type_2_diabetes").value is True
    assert resolver.resolve(patient, "nyha_class").value == "II"
    assert resolver.resolve(patient, "morbid_obesity").value is False


def test_temporal_history_does_not_assume_missing_events_are_false() -> None:
    resolver = PatientFactResolver(reference_date=REFERENCE_DATE)
    patient = synthetic_patient()
    six_months = TemporalWindow(value=6, unit="MONTH")

    assert resolver.resolve(patient, "heart_attack", temporal_window=six_months).value is False
    assert resolver.resolve(patient, "stroke", temporal_window=six_months).value is False
    heart_failure = resolver.resolve(
        patient, "heart_failure_hospitalization", temporal_window=six_months
    )
    assert heart_failure.value is None
    assert heart_failure.missing_information == [
        "medical_history: heart_failure_hospitalization"
    ]


def test_missing_and_unsupported_facts_remain_explicitly_unknown() -> None:
    resolver = PatientFactResolver(reference_date=REFERENCE_DATE)
    patient = PatientProfile(
        patient_id="DEMO-P002",
        age=48,
        sex="FEMALE",
        country="India",
        condition="Type 2 Diabetes",
        consent_for_demo=True,
    )

    assert resolver.resolve(patient, "hba1c").value is None
    assert resolver.resolve(patient, "bariatric_surgery_considered").value is None
