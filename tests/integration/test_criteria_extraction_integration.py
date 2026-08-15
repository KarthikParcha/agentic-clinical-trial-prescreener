import asyncio
import json
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from clinical_trial_prescreener.config import GroqSettings
from clinical_trial_prescreener.domain.criterion import EligibilityCriterion
from clinical_trial_prescreener.infrastructure.clinicaltrials.normalizer import (
    normalize_trial,
)
from clinical_trial_prescreener.infrastructure.llm.groq_client import GroqClient
from clinical_trial_prescreener.services.criteria_extraction import (
    CriteriaExtractionError,
    CriteriaExtractionService,
)
from tests.golden.criteria_evaluation import (
    CriteriaEvaluationReport,
    evaluate_criteria,
    format_evaluation_report,
    load_golden_criteria,
)

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "type2_diabetes_recruiting_india.json.json"
)
OUTPUT_DIRECTORY = Path(__file__).parent / "output"
OUTPUT_PATH = OUTPUT_DIRECTORY / "nct07438444_criteria_extraction_v3.txt"
REPORT_PATH = OUTPUT_DIRECTORY / "nct07438444_criteria_evaluation_v3.txt"
GOLDEN_PATH = (
    Path(__file__).parents[1] / "golden" / "nct07438444_expected_criteria.json"
)


def run(coroutine: Awaitable[Any]) -> Any:
    return asyncio.run(coroutine)


def groq_credentials_available() -> bool:
    try:
        GroqSettings()  # type: ignore[call-arg]
    except ValidationError:
        return False
    return True


def write_criteria_output(
    trial_id: str,
    criteria: list[EligibilityCriterion],
    evaluation: CriteriaEvaluationReport,
) -> Path:
    output = {
        "trial_id": trial_id,
        "target_population": "Type 2 Diabetes",
        "criteria": [criterion.model_dump(mode="json") for criterion in criteria],
        "golden_evaluation": evaluation.model_dump(mode="json"),
    }
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return OUTPUT_PATH


def write_evaluation_report(report_text: str) -> Path:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    return REPORT_PATH


@pytest.mark.integration
@pytest.mark.skipif(
    not groq_credentials_available(),
    reason="GROQ_API_KEY is not available",
)
def test_live_groq_extracts_nct07438444_type_2_diabetes_criteria_v3() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text())
    raw_study = next(
        study
        for study in fixture["studies"]
        if study["protocolSection"]["identificationModule"]["nctId"] == "NCT07438444"
    )
    trial = normalize_trial(raw_study)

    async def extract() -> list[EligibilityCriterion]:
        client = GroqClient()
        try:
            return await CriteriaExtractionService(client).extract(
                trial,
                target_population="Type 2 Diabetes",
            )
        finally:
            await client.aclose()

    try:
        criteria = run(extract())
    except CriteriaExtractionError as error:
        stage = error.validation_category.value if error.validation_category else "n/a"
        pytest.fail(
            "Live extraction failed: "
            f"category={error.category.value}; validation_stage={stage}"
        )

    assert criteria
    assert all(isinstance(item, EligibilityCriterion) for item in criteria)
    golden = load_golden_criteria(GOLDEN_PATH)
    evaluation = evaluate_criteria(criteria, golden)
    report_text = format_evaluation_report(evaluation)
    output_path = write_criteria_output(trial.trial_id, criteria, evaluation)
    report_path = write_evaluation_report(report_text)
    print(f"\n{report_text}", flush=True)
    assert output_path.is_file()
    assert report_path.is_file()

    assert evaluation.expected_count == 8
    assert evaluation.matched_count == 8
    assert evaluation.missed_criteria == []
    assert evaluation.unexpected_criteria == []
    assert evaluation.population_leakage == []

    source_evidence = " ".join(item.original_text.casefold() for item in criteria)
    assert "type 2 diabetes for at least one year" in source_evidence
    assert "insulin naive" in source_evidence
    assert "hba1c" in source_evidence and "7.5%" in source_evidence
    assert "body mass index" in source_evidence or "bmi" in source_evidence
    assert "type 1 diabetes" in source_evidence
    assert "heart conditions within 6 months" in source_evidence
