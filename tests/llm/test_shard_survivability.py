from __future__ import annotations

from cookimport.llm.shard_survivability import (
    attach_observed_telemetry_to_survivability_report,
    ShardSurvivabilityPreflightError,
    StageSurvivabilityBudget,
    evaluate_stage_survivability,
    estimate_shard_survivability,
    format_shard_survivability_error,
)


def test_estimate_shard_survivability_marks_binding_limit_and_peak_tokens() -> None:
    estimate = estimate_shard_survivability(
        stage_key="nonrecipe_finalize",
        shard_id="knowledge-0001",
        owned_unit_count=20,
        estimated_input_tokens=40_000,
        estimated_output_tokens=30_000,
        budget=StageSurvivabilityBudget(
            stage_key="nonrecipe_finalize",
            max_input_tokens=100_000,
            max_output_tokens=40_000,
            max_session_peak_tokens=90_000,
            max_owned_units=100,
            output_followup_multiplier=1.0,
        ),
    )

    assert estimate["estimated_followup_tokens"] == 30_000
    assert estimate["estimated_peak_session_tokens"] == 100_000
    assert estimate["binding_limit"] == "session_peak"
    assert estimate["verdict"] == "unsafe"


def test_evaluate_stage_survivability_recommends_minimum_safe_shard_count() -> None:
    report = evaluate_stage_survivability(
        stage_key="line_role",
        requested_shard_count=1,
        budget=StageSurvivabilityBudget(
            stage_key="line_role",
            max_input_tokens=10_000,
            max_output_tokens=5_000,
            max_session_peak_tokens=12_000,
            max_owned_units=4,
            output_followup_multiplier=0.0,
        ),
        shard_estimates=[
            {
                "shard_id": "line-role-0001",
                "owned_unit_count": 8,
                "estimated_input_tokens": 16_000,
                "estimated_output_tokens": 2_000,
            }
        ],
    )

    assert report["survivability_verdict"] == "unsafe"
    assert report["minimum_safe_shard_count"] == 2
    assert report["binding_limit"] == "session_peak"
    assert report["worst_shard"]["shard_id"] == "line-role-0001"


def test_shard_survivability_error_formats_actionable_message() -> None:
    report = {
        "stage_label": "Recipe Refine",
        "requested_shard_count": 1,
        "minimum_safe_shard_count": 3,
        "binding_limit": "output",
        "worst_shard": {"shard_id": "recipe-0001"},
    }

    message = format_shard_survivability_error(report)

    assert "Recipe Refine" in message
    assert "minimum safe count is 3" in message
    assert "binding limit is output" in message
    assert "recipe-0001" in message
    assert str(ShardSurvivabilityPreflightError(report)) == message


def test_attach_observed_telemetry_to_survivability_report_records_predicted_vs_observed() -> None:
    report = evaluate_stage_survivability(
        stage_key="recipe_refine",
        requested_shard_count=1,
        shard_estimates=[
            {
                "shard_id": "recipe-0001",
                "owned_unit_count": 2,
                "estimated_input_tokens": 100,
                "estimated_output_tokens": 50,
                "estimated_followup_tokens": 20,
            }
        ],
    )

    enriched = attach_observed_telemetry_to_survivability_report(
        report,
        telemetry_rows=[
            {
                "task_id": "recipe-0001",
                "tokens_input": 110,
                "tokens_output": 55,
                "tokens_total": 165,
                "prompt_input_mode": "path",
                "proposal_status": "validated",
                "supervision_state": "completed",
            },
            {
                "task_id": "recipe-0001",
                "tokens_total": 18,
                "prompt_input_mode": "inline_repair",
                "proposal_status": "validated",
                "supervision_state": "completed",
            },
        ],
    )

    shard_payload = enriched["shards"][0]
    assert shard_payload["observed"]["attempt_count"] == 2
    assert shard_payload["observed"]["initial_input_tokens"] == 110
    assert shard_payload["observed"]["structured_followup_call_count"] == 1
    assert shard_payload["observed"]["structured_followup_tokens_total"] == 18
    assert shard_payload["predicted_vs_observed"]["initial_input_tokens"]["delta"] == 10
    assert (
        shard_payload["predicted_vs_observed"]["followup_tokens"]["delta"]
        == -2
    )
    assert enriched["observed_summary"]["call_count"] == 2
