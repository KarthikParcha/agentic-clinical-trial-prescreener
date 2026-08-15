import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from clinical_trial_prescreener.dashboard.app import (
    CriteriaSource,
    available_run_snapshots,
    build_dashboard_view,
    criteria_counts,
    criteria_table_rows,
    failed_extraction_dashboard_run,
    load_dashboard_payload,
    load_multi_trial_report_artifact,
    researcher_status,
    select_trial_result,
    successful_dashboard_run,
)

APP_PATH = (
    Path(__file__).parents[2]
    / "src/clinical_trial_prescreener/dashboard/app.py"
)


def test_successful_trace_renders_expected_summary_data() -> None:
    view = build_dashboard_view(successful_dashboard_run())

    assert view["summary"] == {
        "run_id": "fixture-success-001",
        "patient_id": "DEMO-P001",
        "trial_id": "NCT07438444",
        "criteria_source": "VALIDATED_FIXTURE",
        "final_workflow_outcome": "REQUEST_INFORMATION",
        "trial_assessment": "INSUFFICIENT_INFORMATION",
        "verification_decision": "APPROVED",
        "coordinator_action": "REQUEST_INFORMATION",
        "total_duration_ms": 436,
        "error_status": "NONE",
    }
    assert [row["stage"] for row in view["timeline"]] == [
        "EXTRACT",
        "EVALUATE",
        "AGGREGATE",
        "VERIFY",
        "COORDINATE",
        "END",
    ]


def test_streamlit_app_waits_for_a_fresh_run_before_rendering_results() -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=20).run()

    assert not app.exception
    assert {item.label for item in app.selectbox} >= {"Patient profile"}
    assert "Run" not in {item.label for item in app.selectbox}
    assert app.info[-1].value == (
        "Run Pre-Screening to view fresh results in this dashboard session."
    )


def test_failed_extraction_trace_remains_renderable() -> None:
    view = build_dashboard_view(failed_extraction_dashboard_run())

    assert view["summary"]["error_status"] == "ERROR"
    assert view["error"] == {
        "node": "EXTRACT",
        "failure": "REPAIR_EXHAUSTED",
        "stage": "SOURCE_TRACEABILITY",
        "graph": "NOT_STARTED",
    }
    assert view["extraction"]["attempt_count"] == 2
    assert view["extraction"]["repair_attempted"] is True


def test_missing_later_graph_steps_do_not_crash_dashboard() -> None:
    view = build_dashboard_view(failed_extraction_dashboard_run())
    timeline = {row["stage"]: row for row in view["timeline"]}

    assert timeline["EXTRACT"]["status"] == "FAILED"
    assert timeline["EVALUATE"]["status"] == "NOT_STARTED"
    assert timeline["AGGREGATE"]["status"] == "NOT_STARTED"
    assert timeline["VERIFY"]["status"] == "NOT_STARTED"
    assert timeline["COORDINATE"]["status"] == "NOT_STARTED"
    assert timeline["END"]["status"] == "NOT_REACHED"


def test_demo_criteria_counts_are_correct() -> None:
    assert criteria_counts(successful_dashboard_run()) == {
        "MET": 4,
        "NOT_MET": 3,
        "UNKNOWN": 1,
        "NOT_APPLICABLE": 0,
    }


def test_agent_decisions_are_shown_separately() -> None:
    view = build_dashboard_view(successful_dashboard_run())

    assert view["verification_agent"]["decision"] == "APPROVED"
    assert "evidence" in view["verification_agent"]["reason"].casefold()
    assert view["coordinator_agent"]["action"] == "REQUEST_INFORMATION"
    assert view["coordinator_agent"]["retry_count"] == 0
    assert view["coordinator_agent"]["reevaluation_count"] == 0


def test_extraction_canonicalization_debug_is_shown_without_raw_response() -> None:
    view = build_dashboard_view(successful_dashboard_run())

    assert view["extraction"]["canonicalizations"] == [
        {
            "criterion_path": "criteria.7.children.0",
            "raw_evaluation_type": "HUMAN_ONLY",
            "removed_fields": ["operator", "value"],
        }
    ]
    assert "raw_response" not in view["extraction"]


def test_extraction_attempt_debug_is_rendered_without_provider_payload() -> None:
    run = failed_extraction_dashboard_run()
    run.trace.steps[0].output_summary.update(
        {
            "provider_attempts": 2,
            "extraction_repair_attempts": 0,
            "provider_error_code": "json_validate_failed",
        }
    )

    loaded = load_dashboard_payload(
        run.trace.model_dump_json(), criteria_source=CriteriaSource.LIVE_LLM
    )
    view = build_dashboard_view(loaded)

    assert view["extraction"]["provider_attempts"] == 2
    assert view["extraction"]["extraction_repair_attempts"] == 0
    assert view["extraction"]["provider_error_code"] == "json_validate_failed"
    assert "failed_generation" not in str(view["extraction"])


def test_raw_existing_trace_can_be_loaded_without_later_state() -> None:
    raw_trace = failed_extraction_dashboard_run().trace.model_dump_json()

    loaded = load_dashboard_payload(raw_trace, criteria_source=CriteriaSource.LIVE_LLM)
    view = build_dashboard_view(loaded)

    assert view["summary"]["run_id"] == "fixture-extraction-failure-001"
    assert view["error"]["graph"] == "NOT_STARTED"


def test_secrets_and_hidden_reasoning_are_not_included() -> None:
    run = successful_dashboard_run()
    run.trace.steps[0].metadata.update(
        {
            "api_key": "gsk_should_never_render",
            "hidden_reasoning": "private chain-of-thought",
        }
    )
    run.verification.reason = "api_key=gsk_should_never_render verification summary"

    rendered = json.dumps(build_dashboard_view(run))

    assert "gsk_should_never_render" not in rendered
    assert "private chain-of-thought" not in rendered
    assert "[REDACTED]" in rendered


def test_multi_trial_artifact_loads_three_trial_results() -> None:
    artifact = load_multi_trial_report_artifact(
        Path(__file__).parents[1] / "integration" / "output" / "live_multi_trial"
    )

    assert artifact is not None
    assert artifact.search_summary.trials_found == 3
    assert len(artifact.trial_results) == 3


def test_trial_selection_is_scoped_to_the_selected_run() -> None:
    run = next(
        item
        for item in available_run_snapshots()
        if item.run_id == "live-multi-trial-report-artifacts"
    )
    selected = select_trial_result(run, run.trial_results[1].trial_id)

    assert selected.trial_id == run.trial_results[1].trial_id
    try:
        select_trial_result(run, "NCT00000000")
    except ValueError as error:
        assert "selected run" in str(error)
    else:
        raise AssertionError("A trial outside the selected run must be rejected")


def test_criteria_table_contains_every_saved_report_criterion() -> None:
    run = next(
        item
        for item in available_run_snapshots()
        if item.run_id == "live-multi-trial-report-artifacts"
    )
    result = run.trial_results[0]

    assert len(criteria_table_rows(result)) == len(result.criteria)


def test_researcher_snapshot_hides_provider_debug_information() -> None:
    run = failed_extraction_dashboard_run()
    run.extraction.provider_error_code = "json_validate_failed"
    snapshot = next(
        item
        for item in available_run_snapshots()
        if item.run_id == "fixture-success-001"
    )

    rendered = json.dumps(criteria_table_rows(snapshot.trial_results[0]))

    assert "provider_error_code" not in rendered
    assert "json_validate_failed" not in rendered


def test_researcher_status_never_introduces_prohibited_eligibility_language() -> None:
    run = next(
        item
        for item in available_run_snapshots()
        if item.run_id == "live-multi-trial-report-artifacts"
    )

    rendered = " ".join(researcher_status(result) for result in run.trial_results)

    assert "ELIGIBLE" not in rendered
    assert "INELIGIBLE" not in rendered


def test_saved_report_is_used_without_generating_new_content() -> None:
    run = next(
        item
        for item in available_run_snapshots()
        if item.run_id == "live-multi-trial-report-artifacts"
    )

    report = run.trial_results[0].report_markdown

    assert report is not None
    assert report.startswith("# Clinical Trial Pre-Screening Report")
