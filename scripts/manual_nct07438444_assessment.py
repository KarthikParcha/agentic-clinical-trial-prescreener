"""Run the frozen NCT07438444 criteria against the documented synthetic patient."""

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from clinical_trial_prescreener.domain.assessment import CriterionStatus
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.domain.patient import PatientProfile
from clinical_trial_prescreener.services.assessment_service import AssessmentService
from clinical_trial_prescreener.services.eligibility_evaluator import (
    EligibilityEvaluator,
)
from clinical_trial_prescreener.services.patient_fact_resolver import (
    PatientFactResolver,
)

ROOT = Path(__file__).parents[1]
GOLDEN_PATH = ROOT / "tests" / "golden" / "nct07438444_expected_criteria.json"
OUTPUT_PATH = (
    ROOT / "tests" / "integration" / "output" / "nct07438444_manual_assessment.txt"
)
REFERENCE_DATE = date(2026, 7, 15)


def synthetic_patient() -> PatientProfile:
    """Build the synthetic patient from the manual eligibility walkthrough."""

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


def load_frozen_criteria() -> list[tuple[str, EligibilityCriterion]]:
    """Load the frozen human-reviewed criteria contract, without calling an LLM."""

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return [
        (
            item["label"],
            EligibilityCriterion.model_validate(item["expected"]),
        )
        for item in golden["criteria"]
    ]


def main() -> None:
    patient = synthetic_patient()
    resolver = PatientFactResolver(reference_date=REFERENCE_DATE)
    evaluator = EligibilityEvaluator(reference_date=REFERENCE_DATE)

    lines = [
        "NCT07438444 MANUAL CRITERION ASSESSMENT",
        "=" * 40,
        f"Patient: {patient.patient_id}",
        "Resolver: deterministic Version 1 canonical facts",
        "",
        "Criterion assessments:",
    ]
    assessments = []
    for label, criterion in load_frozen_criteria():
        if criterion.field_name:
            fact = resolver.resolve(patient, criterion.field_name)
            fact_text = str(fact.value) if fact.is_known else "missing"
        else:
            fact_text = "human-review leaf"
        assessment = evaluator.evaluate(criterion, patient)
        assessments.append(assessment)
        lines.append(f"- {label}: {assessment.status.value} (fact: {fact_text})")
        if assessment.missing_information:
            lines.append(f"  missing: {', '.join(assessment.missing_information)}")

    trial_assessment = AssessmentService().aggregate("NCT07438444", assessments)
    status_counts = {
        status: sum(item.status is status for item in assessments)
        for status in (
            CriterionStatus.MET,
            CriterionStatus.NOT_MET,
            CriterionStatus.UNKNOWN,
        )
    }
    missing_information = [
        _display_missing(item) for item in trial_assessment.missing_information
    ] or ["None"]
    lines.extend(
        [
            "",
            "TRIAL-LEVEL ASSESSMENT",
            "=" * 40,
            f"Trial: {trial_assessment.trial_id}",
            f"Patient: {patient.patient_id}",
            "",
            f"Criteria evaluated: {len(assessments)}",
            "",
            f"MET: {status_counts[CriterionStatus.MET]}",
            f"NOT_MET: {status_counts[CriterionStatus.NOT_MET]}",
            f"UNKNOWN: {status_counts[CriterionStatus.UNKNOWN]}",
            "",
            "Overall:",
            trial_assessment.status.value,
            "",
            "Blocking criteria:",
            ", ".join(trial_assessment.blocking_criterion_ids) or "None",
            "",
            "Unknown criteria:",
            ", ".join(trial_assessment.unknown_criterion_ids) or "None",
            "",
            "Missing information:",
            *missing_information,
            "",
            "Human review:",
            "True / inherently required"
            if trial_assessment.requires_human_review
            else "False / not inherently required yet",
        ]
    )

    report = "\n".join(lines) + "\n"
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"Saved report: {OUTPUT_PATH}")


def _display_missing(value: str) -> str:
    """Render the current resolver's technical missing field for the manual report."""

    labels = {
        "medical_history: heart_failure_hospitalization": (
            "heart failure hospitalization history"
        )
    }
    return labels.get(value, value)


if __name__ == "__main__":
    main()
