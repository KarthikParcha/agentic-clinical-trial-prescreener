"""Deterministically derive Version 1 canonical facts from PatientProfile."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from clinical_trial_prescreener.domain.criterion import TemporalWindow
from clinical_trial_prescreener.domain.patient import PatientProfile


class PatientFactResolution(BaseModel):
    """One resolved canonical fact or an explicit missing-data result."""

    model_config = ConfigDict(extra="forbid")

    fact_name: str
    value: Decimal | bool | str | None = None
    patient_evidence: str | None = None
    missing_information: list[str] = Field(default_factory=list)

    @property
    def is_known(self) -> bool:
        return self.value is not None


class PatientFactResolver:
    """Resolve only the canonical facts established by the frozen V1 contract."""

    def __init__(self, *, reference_date: date | None = None) -> None:
        self._reference_date = reference_date or datetime.now(UTC).date()

    def resolve(
        self,
        patient: PatientProfile,
        fact_name: str,
        *,
        temporal_window: TemporalWindow | None = None,
    ) -> PatientFactResolution:
        """Return a fact value, preserving unavailable data as missing information."""

        handlers = {
            "age": self._age,
            "diagnosis_duration_years": self._diagnosis_duration_years,
            "insulin_naive": self._insulin_naive,
            "hba1c": self._hba1c,
            "fasting_blood_glucose": self._fasting_blood_glucose,
            "random_blood_glucose": self._random_blood_glucose,
            "bmi": self._bmi,
            "type_1_diabetes": self._type_1_diabetes,
            "type_2_diabetes": self._type_2_diabetes,
            "type_2_diabetes_on_treatment": self._type_2_diabetes_on_treatment,
            "other_systemic_conditions": self._other_systemic_conditions,
            "pregnancy_status": self._pregnancy_status,
            "antibiotic_use": self._antibiotic_use,
            "heart_attack": self._medical_history_event,
            "stroke": self._medical_history_event,
            "heart_failure_hospitalization": self._medical_history_event,
            "heart_failure_history": self._heart_failure_history,
            "hypertension_on_active_treatment": self._hypertension_on_active_treatment,
            "cardiovascular_disease_on_active_treatment": (
                self._cardiovascular_disease_on_active_treatment
            ),
            "nyha_class": self._nyha_class,
            "morbid_obesity": self._morbid_obesity,
        }
        handler = handlers.get(fact_name)
        if handler is None:
            return self._missing(fact_name, f"{fact_name} is not represented in PatientProfile")
        if fact_name in {
            "heart_attack",
            "stroke",
            "heart_failure_hospitalization",
        }:
            return handler(patient, fact_name, temporal_window)
        if fact_name == "antibiotic_use":
            return handler(patient, temporal_window)
        return handler(patient)

    def _diagnosis_duration_years(self, patient: PatientProfile) -> PatientFactResolution:
        if patient.diagnosis_duration_years is not None:
            return PatientFactResolution(
                fact_name="diagnosis_duration_years",
                value=patient.diagnosis_duration_years,
                patient_evidence=(
                    f"diagnosis_duration_years={patient.diagnosis_duration_years}"
                ),
            )
        if patient.diagnosis_date is None:
            return self._missing("diagnosis_duration_years", "diagnosis_date")
        years = Decimal((self._reference_date - patient.diagnosis_date).days) / Decimal("365.25")
        return PatientFactResolution(
            fact_name="diagnosis_duration_years",
            value=years,
            patient_evidence=f"diagnosis_date={patient.diagnosis_date.isoformat()}",
        )

    @staticmethod
    def _age(patient: PatientProfile) -> PatientFactResolution:
        return PatientFactResolution(
            fact_name="age", value=Decimal(patient.age), patient_evidence=f"age={patient.age}"
        )

    def _insulin_naive(self, patient: PatientProfile) -> PatientFactResolution:
        if not patient.medications:
            return self._missing("insulin_naive", "medications")
        insulin_medications = [
            medication.medication_name
            for medication in patient.medications
            if "insulin" in medication.medication_name.casefold()
        ]
        return PatientFactResolution(
            fact_name="insulin_naive",
            value=not insulin_medications,
            patient_evidence=(
                "medications contain insulin: " + ", ".join(insulin_medications)
                if insulin_medications
                else "medication history contains no insulin"
            ),
        )

    def _hba1c(self, patient: PatientProfile) -> PatientFactResolution:
        results = [
            result
            for result in patient.laboratory_results
            if result.test_name.casefold().replace(" ", "") == "hba1c"
        ]
        if not results:
            return self._missing("hba1c", "laboratory_results: HbA1c")
        result = max(results, key=lambda item: item.measured_date or date.min)
        return PatientFactResolution(
            fact_name="hba1c",
            value=result.value,
            patient_evidence=f"HbA1c={result.value} {result.unit}",
        )

    def _fasting_blood_glucose(
        self, patient: PatientProfile
    ) -> PatientFactResolution:
        return self._blood_glucose(patient, "fasting", "fasting blood glucose")

    def _random_blood_glucose(
        self, patient: PatientProfile
    ) -> PatientFactResolution:
        return self._blood_glucose(patient, "random", "random blood glucose")

    def _blood_glucose(
        self, patient: PatientProfile, keyword: str, display_name: str
    ) -> PatientFactResolution:
        matching = [
            item
            for item in patient.laboratory_results
            if keyword in item.test_name.casefold()
            and "glucose" in item.test_name.casefold()
        ]
        if not matching:
            return self._missing(display_name, display_name)
        result = max(matching, key=lambda item: item.measured_date or date.min)
        return PatientFactResolution(
            fact_name=display_name,
            value=result.value,
            patient_evidence=f"{result.test_name}={result.value} {result.unit}",
        )

    def _bmi(self, patient: PatientProfile) -> PatientFactResolution:
        if patient.bmi is None:
            return self._missing("bmi", "bmi")
        return PatientFactResolution(
            fact_name="bmi", value=patient.bmi, patient_evidence=f"bmi={patient.bmi}"
        )

    def _type_1_diabetes(self, patient: PatientProfile) -> PatientFactResolution:
        has_type_1 = any(
            "type 1 diabetes" in item.condition_name.casefold()
            for item in patient.medical_history
        )
        return PatientFactResolution(
            fact_name="type_1_diabetes",
            value=has_type_1,
            patient_evidence=(
                "medical_history contains Type 1 Diabetes"
                if has_type_1
                else "patient.condition=Type 2 Diabetes; no Type 1 Diabetes record"
            ),
        )

    def _type_2_diabetes(self, patient: PatientProfile) -> PatientFactResolution:
        return PatientFactResolution(
            fact_name="type_2_diabetes",
            value=patient.condition == "Type 2 Diabetes",
            patient_evidence=f"condition={patient.condition}",
        )

    def _type_2_diabetes_on_treatment(
        self, patient: PatientProfile
    ) -> PatientFactResolution:
        if patient.condition != "Type 2 Diabetes":
            return PatientFactResolution(
                fact_name="type_2_diabetes_on_treatment",
                value=False,
                patient_evidence=f"condition={patient.condition}",
            )
        current_names = [
            item.medication_name
            for item in patient.medications
            if item.status.value == "CURRENT"
        ]
        diabetes_treatment = [
            name
            for name in current_names
            if "metformin" in name.casefold() or "insulin" in name.casefold()
        ]
        if not diabetes_treatment:
            return self._missing(
                "type_2_diabetes_on_treatment",
                "medications: active Type 2 Diabetes treatment",
            )
        return PatientFactResolution(
            fact_name="type_2_diabetes_on_treatment",
            value=True,
            patient_evidence=(
                "condition=Type 2 Diabetes; current medication="
                + ", ".join(diabetes_treatment)
            ),
        )

    def _hypertension_on_active_treatment(
        self, patient: PatientProfile
    ) -> PatientFactResolution:
        if not any("hypertension" in item.condition_name.casefold() for item in patient.medical_history):
            return self._missing(
                "hypertension_on_active_treatment",
                "medical_history: hypertension diagnosis",
            )
        return self._missing(
            "hypertension_on_active_treatment",
            "medications: active antihypertensive treatment",
        )

    def _cardiovascular_disease_on_active_treatment(
        self, patient: PatientProfile
    ) -> PatientFactResolution:
        cardiovascular_history = [
            item.condition_name
            for item in patient.medical_history
            if any(
                term in item.condition_name.casefold()
                for term in ("heart attack", "myocardial", "stroke", "heart failure")
            )
        ]
        if not cardiovascular_history:
            return self._missing(
                "cardiovascular_disease_on_active_treatment",
                "medical_history: established cardiovascular disease",
            )
        return self._missing(
            "cardiovascular_disease_on_active_treatment",
            "medications: active cardiovascular treatment",
            patient_evidence="medical_history=" + ", ".join(cardiovascular_history),
        )

    def _heart_failure_history(self, patient: PatientProfile) -> PatientFactResolution:
        matching = [
            item.condition_name
            for item in patient.medical_history
            if "heart failure" in item.condition_name.casefold()
        ]
        if not matching:
            return self._missing(
                "heart_failure_history", "medical_history: heart failure history"
            )
        return PatientFactResolution(
            fact_name="heart_failure_history",
            value=True,
            patient_evidence="medical_history=" + ", ".join(matching),
        )

    def _other_systemic_conditions(
        self, patient: PatientProfile
    ) -> PatientFactResolution:
        confirmation = next(
            (
                item
                for item in patient.fact_confirmations
                if item.fact_name == "other_systemic_conditions"
                and item.temporal_context is None
            ),
            None,
        )
        if confirmation is None:
            return self._missing(
                "other_systemic_conditions",
                "other systemic conditions",
            )
        return PatientFactResolution(
            fact_name="other_systemic_conditions",
            value=confirmation.value,
            patient_evidence=(
                "patient-supplied confirmation: other_systemic_conditions="
                f"{confirmation.value}"
            ),
        )

    def _pregnancy_status(self, patient: PatientProfile) -> PatientFactResolution:
        if patient.pregnancy_status is None or patient.pregnancy_status.value == "UNKNOWN":
            return self._missing("pregnancy_status", "pregnancy status")
        return PatientFactResolution(
            fact_name="pregnancy_status",
            value=patient.pregnancy_status.value == "PREGNANT",
            patient_evidence=f"pregnancy_status={patient.pregnancy_status.value}",
        )

    def _antibiotic_use(
        self,
        patient: PatientProfile,
        temporal_window: TemporalWindow | None,
    ) -> PatientFactResolution:
        antibiotic_names = [
            item.medication_name
            for item in patient.medications
            if any(
                marker in item.medication_name.casefold()
                for marker in ("cillin", "floxacin", "cycline", "mycin")
            )
        ]
        if not antibiotic_names:
            return self._missing(
                "antibiotic_use", "antibiotic use within previous 3 months"
            )
        return self._missing(
            "antibiotic_use", "antibiotic timing within previous 3 months"
        )

    def _medical_history_event(
        self,
        patient: PatientProfile,
        fact_name: str,
        temporal_window: TemporalWindow | None,
    ) -> PatientFactResolution:
        confirmation = next(
            (
                item
                for item in patient.fact_confirmations
                if item.fact_name == fact_name
                and item.temporal_context == temporal_window
            ),
            None,
        )
        if confirmation is not None:
            return PatientFactResolution(
                fact_name=fact_name,
                value=confirmation.value,
                patient_evidence=(
                    f"patient-supplied confirmation: {fact_name}="
                    f"{confirmation.value}"
                ),
            )
        aliases = {
            "heart_attack": ("heart attack", "myocardial infarction"),
            "stroke": ("stroke", "cerebrovascular accident"),
            "heart_failure_hospitalization": ("heart failure hospitalization",),
        }[fact_name]
        matching = [
            item
            for item in patient.medical_history
            if any(alias in item.condition_name.casefold() for alias in aliases)
        ]
        if not matching:
            return self._missing(fact_name, f"medical_history: {fact_name}")
        event = max(matching, key=lambda item: item.diagnosis_date or date.min)
        if temporal_window is None:
            return PatientFactResolution(
                fact_name=fact_name,
                value=True,
                patient_evidence=f"medical_history={event.condition_name}",
            )
        if event.diagnosis_date is None:
            return self._missing(fact_name, f"date for {fact_name}")
        days = _window_days(temporal_window)
        within_window = (self._reference_date - event.diagnosis_date).days <= days
        return PatientFactResolution(
            fact_name=fact_name,
            value=within_window,
            patient_evidence=(
                f"{event.condition_name} date={event.diagnosis_date.isoformat()}; "
                f"window={temporal_window.value} {temporal_window.unit.value}"
            ),
        )

    def _nyha_class(self, patient: PatientProfile) -> PatientFactResolution:
        for item in patient.medical_history:
            text = " ".join(filter(None, [item.condition_name, item.notes])).upper()
            match = re.search(r"(?:NYHA|CLASS)\s*(I{1,3}|IV)\b", text)
            if match:
                return PatientFactResolution(
                    fact_name="nyha_class",
                    value=match.group(1),
                    patient_evidence=f"medical_history={item.condition_name}",
                )
        return self._missing("nyha_class", "medical_history: NYHA class")

    def _morbid_obesity(self, patient: PatientProfile) -> PatientFactResolution:
        matching = [
            item
            for item in patient.medical_history
            if "morbid obesity" in item.condition_name.casefold()
        ]
        if not matching:
            return self._missing("morbid_obesity", "medical_history: morbid obesity")
        active = any(item.status.value == "ACTIVE" for item in matching)
        return PatientFactResolution(
            fact_name="morbid_obesity",
            value=active,
            patient_evidence=("medical_history contains active morbid obesity" if active else "morbid obesity is resolved")
        )

    @staticmethod
    def _missing(
        fact_name: str, missing: str, *, patient_evidence: str | None = None
    ) -> PatientFactResolution:
        return PatientFactResolution(
            fact_name=fact_name,
            patient_evidence=patient_evidence,
            missing_information=[missing],
        )


def _window_days(window: TemporalWindow) -> int:
    multipliers = {"DAY": 1, "WEEK": 7, "MONTH": 30, "YEAR": 365}
    return int(window.value) * multipliers[window.unit.value]
