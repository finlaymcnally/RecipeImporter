from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
from cookimport.runs import (
    RECIPE_MANIFEST_FILE_NAME,
    KNOWLEDGE_MANIFEST_FILE_NAME,
    KNOWLEDGE_STAGE_STATUS_FILE_NAME,
    build_line_role_stage_summary,
    build_stage_observability_report,
    summarize_knowledge_stage_artifacts,
    write_stage_observability_report,
)
from cookimport.runs.stage_observability import build_recipe_stage_summary


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _stage_keys(report: object) -> list[str]:
    return [row.stage_key for row in report.stages]


def test_build_stage_observability_report_for_deterministic_stage_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    (run_root / "intermediate drafts" / "book").mkdir(parents=True)
    (run_root / "final drafts" / "book").mkdir(parents=True)

    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="stage",
        created_at="2026-03-15T23:40:19",
        run_config={"llm_recipe_pipeline": "off"},
    )

    assert _stage_keys(report) == ["write_outputs"]
    assert report.stages[0].stage_label == "Write Outputs"


def test_build_stage_observability_report_for_single_correction_recipe_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    llm_root = run_root / "raw" / "llm" / "book"
    (llm_root / "recipe_phase_runtime" / "inputs").mkdir(parents=True)
    _write_json(
        llm_root / RECIPE_MANIFEST_FILE_NAME,
        {
            "pipeline": RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
            "paths": {
                "recipe_phase_runtime_dir": str(llm_root / "recipe_phase_runtime"),
                "recipe_phase_input_dir": str(llm_root / "recipe_phase_runtime" / "inputs"),
                "recipe_phase_proposals_dir": str(llm_root / "recipe_phase_runtime" / "proposals"),
            },
            "process_runs": {"recipe_correction": {}},
        },
    )

    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="bench_pred_run",
        created_at="2026-03-15T23:40:19",
        run_config={},
    )

    assert _stage_keys(report) == [
        "recipe_build_intermediate",
        "recipe_refine",
        "recipe_build_final",
    ]
    assert [row.stage_label for row in report.stages] == [
        "Recipe Build Intermediate",
        "Recipe Refine",
        "Recipe Build Final",
    ]


def test_build_stage_observability_report_for_knowledge_enabled_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    llm_root = run_root / "raw" / "llm" / "book"
    (llm_root / "knowledge" / "in").mkdir(parents=True)
    (run_root / "08_nonrecipe_route.json").write_text("{}", encoding="utf-8")
    (run_root / "09_nonrecipe_authority.json").write_text("{}", encoding="utf-8")
    (run_root / "09_nonrecipe_finalize_status.json").write_text("{}", encoding="utf-8")
    _write_json(
        llm_root / KNOWLEDGE_MANIFEST_FILE_NAME,
        {"pipeline_id": "recipe.knowledge.compact.v1"},
    )

    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="stage",
        created_at="2026-03-15T23:40:19",
        run_config={},
    )

    assert _stage_keys(report) == [
        "nonrecipe_route",
        "nonrecipe_finalize",
        "write_outputs",
    ]
    assert report.stages[1].stage_label == "Non-Recipe Finalize"
    assert report.stages[1].workbooks[0].manifest_path == (
        "raw/llm/book/knowledge_manifest.json"
    )


def test_build_stage_observability_report_can_scan_external_processed_output_root(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "benchmark-run"
    processed_root = tmp_path / "processed-output"
    recipe_root = processed_root / "raw" / "llm" / "book" / "recipe_phase_runtime"
    recipe_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        recipe_root.parent / RECIPE_MANIFEST_FILE_NAME,
        {
            "pipeline": RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
            "paths": {
                "recipe_phase_runtime_dir": str(recipe_root),
                "recipe_phase_input_dir": str(recipe_root / "inputs"),
                "recipe_phase_proposals_dir": str(recipe_root / "proposals"),
            },
            "process_runs": {"recipe_correction": {}},
        },
    )
    (processed_root / "final drafts" / "book").mkdir(parents=True, exist_ok=True)

    report = build_stage_observability_report(
        run_root=run_root,
        artifact_scan_root=processed_root,
        run_kind="bench_pred_run",
        created_at="2026-03-15T23:40:19",
        run_config={},
    )

    assert _stage_keys(report) == [
        "recipe_build_intermediate",
        "recipe_refine",
        "recipe_build_final",
        "write_outputs",
    ]
    assert report.stages[1].workbooks[0].stage_dir == str(recipe_root)


def test_write_stage_observability_report_writes_json(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="stage",
        created_at=dt.datetime(2026, 3, 15, 23, 40, 19).isoformat(timespec="seconds"),
        run_config={"llm_recipe_pipeline": "off"},
    )

    path = write_stage_observability_report(run_root=run_root, report=report)

    assert path == run_root / "stage_observability.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "stage_observability.v1"
    assert payload["stages"][0]["stage_key"] == "write_outputs"


def test_write_stage_observability_report_writes_knowledge_stage_summary_artifact(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    stage_root = run_root / "raw" / "llm" / "book" / "nonrecipe_finalize"
    stage_root.mkdir(parents=True, exist_ok=True)
    (stage_root.parent / KNOWLEDGE_MANIFEST_FILE_NAME).write_text(
        json.dumps({"pipeline_id": "recipe.knowledge.compact.v1"}, sort_keys=True),
        encoding="utf-8",
    )
    _write_json(
        stage_root / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
        {
            "schema_version": "knowledge_stage_status.v1",
            "stage_key": "nonrecipe_finalize",
            "stage_state": "completed",
            "termination_cause": "completed",
            "finalization_completeness": "complete",
            "artifact_states": {},
            "pre_kill_failure_counts": {},
        },
    )
    _write_json(
        stage_root / "telemetry.json",
        {
            "summary": {
                "visible_input_tokens": 90,
                "visible_output_tokens": 30,
                "wrapper_overhead_tokens": 60,
                "tokens_reasoning": 0,
                "tokens_total": 180,
                "packet_economics": {
                    "packet_count_total": 3,
                    "primary_packet_count_total": 2,
                    "repair_packet_count_total": 1,
                    "owned_row_count_total": 3,
                    "packet_churn_count": 1,
                    "packets_per_shard": 3.0,
                    "repair_packet_share": 0.3333,
                    "packets_per_owned_row": 1.0,
                    "cost_per_owned_row": 60.0,
                    "visible_input_tokens_per_owned_row": 30.0,
                    "visible_output_tokens_per_owned_row": 10.0,
                    "wrapper_overhead_tokens_per_owned_row": 20.0,
                    "reasoning_tokens_per_owned_row": 0.0,
                    "semantic_payload_tokens_total": 120,
                    "semantic_payload_tokens_per_owned_row": 40.0,
                    "protocol_overhead_tokens_total": 60,
                    "protocol_overhead_share": 0.3333,
                },
            }
        },
    )
    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="stage",
        created_at=dt.datetime(2026, 3, 15, 23, 40, 19).isoformat(timespec="seconds"),
        run_config={},
    )

    path = write_stage_observability_report(run_root=run_root, report=report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    workbook = payload["stages"][0]["workbooks"][0]

    assert (
        run_root
        / workbook["artifact_paths"]["knowledge_stage_summary_json"]
    ).exists()


def test_write_stage_observability_report_writes_recipe_and_line_role_stage_summaries(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    recipe_root = run_root / "raw" / "llm" / "book" / "recipe_phase_runtime"
    recipe_root.mkdir(parents=True, exist_ok=True)
    (recipe_root / "proposals").mkdir(parents=True, exist_ok=True)
    (recipe_root / "workers" / "worker-001" / "shards" / "recipe-shard-0001").mkdir(
        parents=True, exist_ok=True
    )
    (recipe_root / "workers" / "worker-001" / "out").mkdir(parents=True, exist_ok=True)
    (recipe_root / "workers" / "worker-001" / "live_status.json").write_text(
        json.dumps({"state": "completed"}, sort_keys=True),
        encoding="utf-8",
    )
    _write_json(recipe_root / "phase_manifest.json", {"worker_count": 1, "shard_count": 1})
    _write_json(
        recipe_root / "promotion_report.json",
        {
            "invalid_shards": 1,
            "missing_output_shards": 0,
            "recipe_result_counts": {
                "repaired": 1,
                "fragmentary": 1,
                "not_a_recipe": 0,
            },
        },
    )
    (recipe_root / "task_manifest.jsonl").write_text(
        json.dumps({"task_id": "recipe-shard-0001.task-001"}) + "\n",
        encoding="utf-8",
    )
    (recipe_root / "workers" / "worker-001" / "out" / "recipe-shard-0001.task-001.json").write_text(
        "{}",
        encoding="utf-8",
    )
    _write_json(
        recipe_root / "workers" / "worker-001" / "shards" / "recipe-shard-0001" / "status.json",
        {"status": "validated"},
    )
    _write_json(
        recipe_root.parent / RECIPE_MANIFEST_FILE_NAME,
        {
            "pipeline": RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
            "counts": {
                "recipes_total": 2,
                "recipe_correction_error": 0,
                "final_recipe_authority_promoted": 1,
                "final_recipe_authority_not_promoted": 1,
                "final_recipe_authority_error": 0,
            },
            "paths": {
                "recipe_phase_runtime_dir": str(recipe_root),
                "recipe_phase_input_dir": str(recipe_root / "inputs"),
                "recipe_phase_proposals_dir": str(recipe_root / "proposals"),
            },
            "process_runs": {"recipe_correction": {}},
        },
    )

    line_role_root = run_root / "line-role-pipeline" / "runtime" / "line_role"
    line_role_root.mkdir(parents=True, exist_ok=True)
    (line_role_root / "proposals").mkdir(parents=True, exist_ok=True)
    (line_role_root / "workers" / "worker-001" / "shards" / "line-role-canonical-0001").mkdir(
        parents=True, exist_ok=True
    )
    (line_role_root / "workers" / "worker-001" / "out").mkdir(parents=True, exist_ok=True)
    (line_role_root / "workers" / "worker-001" / "live_status.json").write_text(
        json.dumps({"state": "completed"}, sort_keys=True),
        encoding="utf-8",
    )
    _write_json(line_role_root / "phase_manifest.json", {"worker_count": 1, "shard_count": 1})
    _write_json(
        line_role_root / "promotion_report.json",
        {"invalid_shards": 0, "missing_output_shards": 1},
    )
    (line_role_root / "shard_manifest.jsonl").write_text(
        json.dumps({"shard_id": "line-role-canonical-0001"}) + "\n",
        encoding="utf-8",
    )
    (line_role_root / "workers" / "worker-001" / "out" / "line-role-canonical-0001.json").write_text(
        "{}",
        encoding="utf-8",
    )
    _write_json(
        line_role_root / "workers" / "worker-001" / "shards" / "line-role-canonical-0001" / "status.json",
        {"status": "validated"},
    )
    label_llm_dir = run_root / "label_refine" / "book"
    label_llm_dir.mkdir(parents=True, exist_ok=True)
    (label_llm_dir / "labeled_lines.jsonl").write_text(
        json.dumps(
            {
                "atomic_index": 0,
                "label": "OTHER",
                "decided_by": "fallback",
                "reason_tags": [
                    "codex_policy_rejected",
                    "codex_policy_rejected:outside_recipe_knowledge_not_allowed",
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="bench_pred_run",
        created_at=dt.datetime(2026, 3, 21, 16, 0, 0).isoformat(timespec="seconds"),
        run_config={},
    )

    path = write_stage_observability_report(run_root=run_root, report=report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    recipe_stage = next(
        stage for stage in payload["stages"] if stage["stage_key"] == "recipe_refine"
    )
    line_role_stage = next(
        stage for stage in payload["stages"] if stage["stage_key"] == "line_role"
    )

    assert (run_root / recipe_stage["workbooks"][0]["artifact_paths"]["recipe_stage_summary_json"]).exists()
    assert (run_root / line_role_stage["workbooks"][0]["artifact_paths"]["line_role_stage_summary_json"]).exists()
    assert recipe_stage["workbooks"][0]["attention_summary"]["zero_target_counts"]["invalid_shard_count"] == 1
    assert line_role_stage["workbooks"][0]["attention_summary"]["zero_target_counts"]["missing_output_shard_count"] == 1


def test_build_stage_observability_report_surfaces_processing_attention_summaries(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    label_llm_dir = run_root / "label_refine" / "book"
    label_llm_dir.mkdir(parents=True, exist_ok=True)
    (label_llm_dir / "labeled_lines.jsonl").write_text(
        json.dumps(
            {
                "atomic_index": 0,
                "label": "OTHER",
                "decided_by": "fallback",
                "reason_tags": ["codex_policy_rejected", "codex_policy_rejected:title_without_local_support"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    group_dir = run_root / "recipe_boundary" / "book"
    group_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        group_dir / "span_decisions.json",
        {
            "span_decisions": [
                {
                    "span_id": "s1",
                    "decision": "accepted_recipe_span",
                    "rejection_reason": None,
                },
                {
                    "span_id": "s2",
                    "decision": "rejected_pseudo_recipe_span",
                    "rejection_reason": "rejected_missing_recipe_body",
                },
            ]
        },
    )
    (run_root / "08_nonrecipe_route.json").write_text("{}", encoding="utf-8")
    (run_root / "08_nonrecipe_exclusions.jsonl").write_text(
        json.dumps(
            {
                "block_index": 7,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    recipe_manifest_dir = run_root / "raw" / "llm" / "book"
    recipe_manifest_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        recipe_manifest_dir / RECIPE_MANIFEST_FILE_NAME,
        {
            "pipeline": RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
            "counts": {
                "recipe_correction_error": 0,
                "final_recipe_authority_promoted": 1,
                "final_recipe_authority_not_promoted": 2,
                "final_recipe_authority_error": 1,
            },
            "paths": {
                "recipe_phase_runtime_dir": str(recipe_manifest_dir / "recipe_phase_runtime"),
                "recipe_phase_input_dir": str(recipe_manifest_dir / "recipe_phase_runtime" / "inputs"),
                "recipe_phase_proposals_dir": str(recipe_manifest_dir / "recipe_phase_runtime" / "proposals"),
            },
            "process_runs": {"recipe_correction": {}},
        },
    )

    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="stage",
        created_at="2026-03-25T21:13:02",
        run_config={},
    )
    payload = report.model_dump(exclude_none=True)

    label_stage = next(stage for stage in payload["stages"] if stage["stage_key"] == "label_refine")
    span_stage = next(stage for stage in payload["stages"] if stage["stage_key"] == "recipe_boundary")
    nonrecipe_stage = next(stage for stage in payload["stages"] if stage["stage_key"] == "nonrecipe_route")
    final_recipe_stage = next(stage for stage in payload["stages"] if stage["stage_key"] == "recipe_build_final")

    assert label_stage["workbooks"][0]["attention_summary"]["zero_target_counts"]["codex_policy_rejected_row_count"] == 1
    assert span_stage["workbooks"][0]["attention_summary"]["zero_target_counts"]["rejected_pseudo_recipe_span_count"] == 1
    assert nonrecipe_stage["workbooks"][0]["attention_summary"]["context_counts"]["excluded_row_count"] == 1
    assert final_recipe_stage["workbooks"][0]["attention_summary"]["zero_target_counts"]["final_recipe_not_promoted_count"] == 2


def test_build_recipe_stage_summary_reports_task_followup_rollups(tmp_path: Path) -> None:
    stage_root = tmp_path / "raw" / "llm" / "book" / "recipe_phase_runtime"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    (stage_root / "workers" / "worker-001" / "out").mkdir(parents=True, exist_ok=True)
    task_root = stage_root / "workers" / "worker-001" / "shards" / "recipe-shard-0001.task-001"
    task_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        stage_root / "phase_manifest.json",
        {
            "worker_count": 1,
            "shard_count": 1,
            "runtime_metadata": {
                "worker_session_guardrails": {
                    "planned_happy_path_worker_cap": 1,
                    "actual_happy_path_worker_sessions": 1,
                    "repair_worker_session_count": 1,
                    "repair_followup_call_count": 0,
                    "cap_exceeded": False,
                    "happy_path_within_cap": True,
                    "status": "within_cap",
                },
                "task_file_guardrails": {
                    "assignment_count": 1,
                    "warning_count": 1,
                    "largest_assignment": {
                        "worker_id": "worker-001",
                        "task_file_bytes": 24576,
                        "task_file_estimated_tokens": 5000,
                    },
                },
            },
        },
    )
    _write_json(
        stage_root / "promotion_report.json",
        {
            "invalid_shards": 1,
            "missing_output_shards": 0,
            "handled_locally_skip_llm": {
                "count": 2,
                "status_counts": {
                    "fragmentary": 1,
                    "not_a_recipe": 1,
                },
            },
            "recipe_result_counts": {
                "repaired": 1,
                "fragmentary": 2,
                "not_a_recipe": 1,
            },
        },
    )
    _write_json(
        stage_root.parent / RECIPE_MANIFEST_FILE_NAME,
        {
            "counts": {
                "recipes_total": 4,
                "recipe_correction_error": 1,
                "final_recipe_authority_promoted": 1,
                "final_recipe_authority_not_promoted": 3,
                "final_recipe_authority_error": 1,
            }
        },
    )
    (stage_root / "task_manifest.jsonl").write_text(
        json.dumps({"task_id": "recipe-shard-0001.task-001"}) + "\n",
        encoding="utf-8",
    )
    (stage_root / "workers" / "worker-001" / "out" / "recipe-shard-0001.task-001.json").write_text(
        "{}",
        encoding="utf-8",
    )
    _write_json(task_root / "repair_status.json", {"status": "repaired"})
    _write_json(task_root / "status.json", {"status": "validated"})
    _write_json(
        stage_root / "workers" / "worker-001" / "status.json",
        {
            "repair_worker_session_count": 1,
            "fresh_session_retry_count": 0,
            "fresh_worker_replacement_count": 0,
        },
    )

    summary = build_recipe_stage_summary(stage_root)

    assert summary["schema_version"] == "recipe_stage_summary.v8"
    assert summary["followups"]["label"] == "task_followup"
    assert summary["followups"]["handled_locally_skip_llm_count"] == 2
    assert summary["followups"]["repair_completed_count"] == 1
    assert (
        summary["repair_recovery_policy"]["budgets"]["same_session_repair_rewrite"][
            "allowed_attempts"
        ]
        == 1
    )
    assert (
        summary["repair_recovery_policy"]["budgets"]["same_session_repair_rewrite"][
            "spent_attempts"
        ]
        == 1
    )
    assert summary["worker_session_guardrails"]["planned_happy_path_worker_cap"] == 1
    assert summary["worker_session_guardrails"]["repair_worker_session_count"] == 1
    assert summary["task_file_guardrails"]["warning_count"] == 1
    assert summary["attention_summary"]["needs_attention"] is True
    assert summary["attention_summary"]["zero_target_counts"]["invalid_shard_count"] == 1
    assert summary["attention_summary"]["zero_target_counts"]["fragmentary_recipe_count"] == 2
    assert summary["attention_summary"]["zero_target_counts"]["not_a_recipe_recipe_count"] == 1
    assert summary["attention_summary"]["zero_target_counts"]["final_recipe_not_promoted_count"] == 3
    assert "same_session_fix_escalated_count" not in summary["attention_summary"]["zero_target_counts"]
    assert summary["attention_summary"]["context_counts"]["handled_locally_skip_llm_count"] == 2
    assert "same_session_fix_attempted_count" not in summary["attention_summary"]["context_counts"]
    assert summary["attention_summary"]["reason_counts"]["handled_locally_skip_llm_status_counts"] == {
        "fragmentary": 1,
        "not_a_recipe": 1,
    }


def test_build_recipe_stage_summary_detects_inline_transport(tmp_path: Path) -> None:
    stage_root = tmp_path / "raw" / "llm" / "book" / "recipe_phase_runtime"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    (stage_root / "workers" / "worker-001" / "out").mkdir(parents=True, exist_ok=True)
    (
        stage_root / "workers" / "worker-001" / "shards" / "recipe-shard-0000"
    ).mkdir(parents=True, exist_ok=True)
    _write_json(
        stage_root / "phase_manifest.json",
        {
            "worker_count": 1,
            "shard_count": 1,
            "settings": {"recipe_codex_exec_style": "inline-json-v1"},
            "runtime_metadata": {"transport": "inline-json-v1"},
        },
    )
    _write_json(
        stage_root / "promotion_report.json",
        {
            "invalid_shards": 0,
            "missing_output_shards": 0,
            "handled_locally_skip_llm": {"count": 0, "status_counts": {}},
            "recipe_result_counts": {"repaired": 1, "fragmentary": 0, "not_a_recipe": 0},
        },
    )
    _write_json(stage_root.parent / RECIPE_MANIFEST_FILE_NAME, {"counts": {}})
    (stage_root / "task_manifest.jsonl").write_text(
        json.dumps({"task_id": "recipe-shard-0000.task-001"}) + "\n",
        encoding="utf-8",
    )
    (
        stage_root
        / "workers"
        / "worker-001"
        / "out"
        / "recipe-shard-0000.task-001.json"
    ).write_text("{}", encoding="utf-8")
    _write_json(
        stage_root / "workers" / "worker-001" / "shards" / "recipe-shard-0000" / "status.json",
        {"status": "validated"},
    )
    _write_json(
        stage_root / "telemetry.json",
        {
            "rows": [
                {
                    "prompt_input_mode": "inline",
                    "codex_transport": "inline-json-v1",
                }
            ],
            "summary": {"prompt_input_mode_counts": {"inline": 1}},
        },
    )

    summary = build_recipe_stage_summary(stage_root)

    assert summary["schema_version"] == "recipe_stage_summary.v8"
    assert summary["followups"]["label"] == "shard_finalization"
    assert summary["repair_recovery_policy"]["transport"] == "inline-json-v1"
    assert "worker_session_guardrails" not in summary
    assert "task_file_guardrails" not in summary


def test_build_line_role_stage_summary_reports_shard_and_line_rollups(tmp_path: Path) -> None:
    stage_root = tmp_path / "line-role-pipeline" / "runtime" / "line_role"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    _write_json(
        stage_root / "phase_manifest.json",
        {
            "worker_count": 1,
            "shard_count": 1,
            "runtime_metadata": {
                "worker_session_guardrails": {
                    "planned_happy_path_worker_cap": 1,
                    "actual_happy_path_worker_sessions": 1,
                    "repair_worker_session_count": 0,
                    "repair_followup_call_count": 0,
                    "cap_exceeded": False,
                    "happy_path_within_cap": True,
                    "status": "within_cap",
                },
                "task_file_guardrails": {
                    "assignment_count": 1,
                    "warning_count": 0,
                    "largest_assignment": {
                        "worker_id": "worker-001",
                        "task_file_bytes": 2048,
                        "task_file_estimated_tokens": 300,
                    },
                },
            },
        },
    )
    _write_json(
        stage_root / "promotion_report.json",
        {"invalid_shards": 1, "missing_output_shards": 1},
    )
    (stage_root / "shard_manifest.jsonl").write_text(
        json.dumps({"shard_id": "line-role-canonical-0001"}) + "\n",
        encoding="utf-8",
    )
    (stage_root / "canonical_line_table.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"line_id": "0", "atomic_index": 0}),
                json.dumps({"line_id": "1", "atomic_index": 1}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (stage_root / "shard_status.jsonl").write_text(
        json.dumps(
            {
                "shard_id": "line-role-canonical-0001",
                "state": "validated",
                "terminal_outcome": "validated",
                "last_attempt_type": "resume_existing_output",
                "metadata": {
                    "llm_authoritative_row_count": 2,
                    "unresolved_row_count": 0,
                    "suspicious_row_count": 2,
                    "suspicious_shard": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        stage_root / "workers" / "worker-001" / "live_status.json",
        {"state": "completed", "reason_code": "resume_existing_outputs"},
    )
    _write_json(
        stage_root / "workers" / "worker-001" / "shards" / "line-role-canonical-0001" / "status.json",
        {"status": "validated"},
    )
    _write_json(
        stage_root / "workers" / "worker-001" / "status.json",
        {
            "same_session_repair_rewrite_count": 0,
            "fresh_session_retry_count": 0,
            "fresh_worker_replacement_count": 0,
        },
    )
    label_llm_dir = tmp_path / "label_refine" / "book"
    label_llm_dir.mkdir(parents=True, exist_ok=True)
    (label_llm_dir / "labeled_lines.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "atomic_index": 0,
                        "label": "OTHER",
                        "decided_by": "fallback",
                        "reason_tags": [
                            "codex_policy_rejected",
                            "codex_policy_rejected:outside_recipe_knowledge_not_allowed",
                        ],
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "atomic_index": 1,
                        "label": "INGREDIENT_LINE",
                        "decided_by": "codex",
                        "reason_tags": ["codex_line_role"],
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_line_role_stage_summary(stage_root)

    assert summary["schema_version"] == "line_role_stage_summary.v6"
    assert summary["lines"]["canonical_line_total"] == 2
    assert summary["lines"]["llm_authoritative_row_count"] == 2
    assert summary["lines"]["unresolved_row_count"] == 0
    assert summary["shards"]["shard_total"] == 1
    assert summary["shards"]["state_counts"] == {"validated": 1}
    assert summary["shards"]["attempt_type_counts"] == {"resume_existing_output": 1}
    assert summary["shards"]["suspicious_shard_count"] == 1
    assert summary["important_artifacts"]["canonical_line_table_jsonl"] == "canonical_line_table.jsonl"
    assert summary["important_artifacts"]["shard_status_jsonl"] == "shard_status.jsonl"
    assert (
        summary["repair_recovery_policy"]["budgets"]["fresh_session_retry"][
            "allowed_attempts"
        ]
        == 1
    )
    assert (
        summary["repair_recovery_policy"]["budgets"]["fresh_session_retry"][
            "spent_attempts"
        ]
        == 0
    )
    assert summary["worker_session_guardrails"]["planned_happy_path_worker_cap"] == 1
    assert summary["task_file_guardrails"]["warning_count"] == 0
    assert summary["attention_summary"]["needs_attention"] is True
    assert summary["attention_summary"]["zero_target_counts"]["invalid_shard_count"] == 1
    assert summary["attention_summary"]["zero_target_counts"]["missing_output_shard_count"] == 1
    assert summary["attention_summary"]["zero_target_counts"]["codex_policy_rejected_row_count"] == 1
    assert (
        summary["attention_summary"]["reason_counts"]["codex_policy_rejection_reason_counts"][
            "outside_recipe_knowledge_not_allowed"
        ]
        == 1
    )


def test_build_line_role_stage_summary_reports_inline_watchdog_and_repair_budgets(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "line-role-pipeline" / "runtime" / "line_role"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    _write_json(
        stage_root / "phase_manifest.json",
        {
            "worker_count": 1,
            "shard_count": 1,
            "runtime_metadata": {
                "worker_session_guardrails": {
                    "planned_happy_path_worker_cap": 1,
                    "actual_happy_path_worker_sessions": 0,
                    "repair_worker_session_count": 0,
                    "repair_followup_call_count": 2,
                    "cap_exceeded": False,
                    "happy_path_within_cap": True,
                    "status": "within_cap",
                },
                "task_file_guardrails": {
                    "assignment_count": 0,
                    "warning_count": 0,
                    "largest_assignment": None,
                },
            },
        },
    )
    _write_json(stage_root / "promotion_report.json", {"invalid_shards": 0, "missing_output_shards": 0})
    (stage_root / "shard_manifest.jsonl").write_text(
        json.dumps({"shard_id": "line-role-canonical-0001"}) + "\n",
        encoding="utf-8",
    )
    (stage_root / "canonical_line_table.jsonl").write_text(
        json.dumps({"line_id": "0", "atomic_index": 0}) + "\n",
        encoding="utf-8",
    )
    (stage_root / "shard_status.jsonl").write_text(
        json.dumps(
            {
                "shard_id": "line-role-canonical-0001",
                "state": "validated",
                "terminal_outcome": "validated",
                "last_attempt_type": "watchdog_retry",
                "metadata": {
                    "llm_authoritative_row_count": 1,
                    "unresolved_row_count": 0,
                    "suspicious_row_count": 0,
                    "suspicious_shard": False,
                    "watchdog_retry_status": "recovered",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        stage_root / "workers" / "worker-001" / "live_status.json",
        {"state": "completed", "reason_code": "completed_outputs_stabilized"},
    )
    _write_json(
        stage_root / "workers" / "worker-001" / "status.json",
        {
            "telemetry": {
                "summary": {
                    "prompt_input_mode_counts": {
                        "structured_session_repair": 1,
                        "inline_watchdog_retry": 1,
                    },
                    "structured_repair_followup_call_count": 1,
                    "watchdog_retry_call_count": 1,
                    "structured_followup_call_count": 2,
                }
            }
        },
    )
    _write_json(
        stage_root / "telemetry.json",
        {
            "summary": {
                "codex_transport": "inline-json-v1",
                "codex_transport_counts": {"inline-json-v1": 2},
                "codex_policy_mode": "shell_disabled",
                "codex_policy_mode_counts": {"shell_disabled": 2},
                "codex_shell_tool_enabled": False,
                "codex_shell_tool_enabled_counts": {"false": 2},
                "prompt_input_mode_counts": {
                    "structured_session_repair": 1,
                    "inline_watchdog_retry": 1,
                },
                "structured_repair_followup_call_count": 1,
                "watchdog_retry_call_count": 1,
                "structured_followup_call_count": 2,
            }
        },
    )
    label_llm_dir = tmp_path / "label_refine" / "book"
    label_llm_dir.mkdir(parents=True, exist_ok=True)
    (label_llm_dir / "labeled_lines.jsonl").write_text(
        json.dumps(
            {
                "atomic_index": 0,
                "label": "RECIPE_NOTES",
                "decided_by": "codex",
                "reason_tags": ["codex_line_role"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_line_role_stage_summary(stage_root)

    assert summary["schema_version"] == "line_role_stage_summary.v6"
    assert summary["codex_transport"] == "inline-json-v1"
    assert summary["codex_policy_mode"] == "shell_disabled"
    assert summary["codex_shell_tool_enabled"] is False
    assert summary["repair_recovery_policy"]["transport"] == "inline-json-v1"
    assert (
        summary["repair_recovery_policy"]["budgets"]["structured_repair_followup"][
            "spent_attempts"
        ]
        == 1
    )
    assert summary["repair_recovery_policy"]["budgets"]["watchdog_retry"] == {
        "followup_kind": "watchdog_retry",
        "followup_surface": "structured_session",
        "budget_scope": "shard_result",
        "allowed_attempts": 1,
        "spent_attempts": 1,
        "remaining_attempts": 0,
    }


def test_build_line_role_stage_summary_uses_shard_ledger_when_status_files_are_absent(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "line-role-pipeline" / "runtime" / "line_role"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    _write_json(
        stage_root / "phase_manifest.json",
        {
            "worker_count": 1,
            "shard_count": 1,
        },
    )
    _write_json(stage_root / "promotion_report.json", {"invalid_shards": 0, "missing_output_shards": 0})
    (stage_root / "shard_manifest.jsonl").write_text(
        json.dumps({"shard_id": "line-role-canonical-0001"}) + "\n",
        encoding="utf-8",
    )
    (stage_root / "canonical_line_table.jsonl").write_text(
        json.dumps({"line_id": "0", "atomic_index": 0}) + "\n",
        encoding="utf-8",
    )
    (stage_root / "shard_status.jsonl").write_text(
        json.dumps(
            {
                "shard_id": "line-role-canonical-0001",
                "state": "validated",
                "terminal_outcome": "validated",
                "last_attempt_type": "structured_session_initial",
                "metadata": {
                    "llm_authoritative_row_count": 1,
                    "unresolved_row_count": 0,
                    "suspicious_row_count": 0,
                    "suspicious_shard": False,
                    "transport": "inline-json-v1",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        stage_root / "telemetry.json",
        {
            "summary": {
                "codex_transport": "inline-json-v1",
            }
        },
    )

    summary = build_line_role_stage_summary(stage_root)

    assert summary["stage_state"] == "completed"
    assert summary["parent_shards"]["completed_total"] == 0
    assert summary["shards"]["state_counts"] == {"validated": 1}


def test_summarize_knowledge_stage_artifacts_uses_status_file(tmp_path: Path) -> None:
    stage_root = tmp_path / "raw" / "llm" / "book" / "knowledge"
    proposals_dir = stage_root / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    (proposals_dir / "book.ks0000.nr.json").write_text("{}", encoding="utf-8")
    (stage_root / "worker_assignments.json").write_text("[]", encoding="utf-8")
    (stage_root.parent / KNOWLEDGE_MANIFEST_FILE_NAME).write_text(
        json.dumps({"pipeline_id": "recipe.knowledge.compact.v1"}, sort_keys=True),
        encoding="utf-8",
    )
    _write_json(
        stage_root / "phase_manifest.json",
        {
            "worker_count": 1,
            "shard_count": 0,
            "runtime_metadata": {
                "worker_session_guardrails": {
                    "planned_happy_path_worker_cap": 1,
                    "actual_happy_path_worker_sessions": 0,
                    "repair_worker_session_count": 0,
                    "repair_followup_call_count": 0,
                    "cap_exceeded": False,
                    "happy_path_within_cap": True,
                    "status": "within_cap",
                },
                "task_file_guardrails": {
                    "assignment_count": 0,
                    "warning_count": 0,
                    "largest_assignment": None,
                },
            },
        },
    )
    _write_json(
        stage_root / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
        {
            "schema_version": "knowledge_stage_status.v1",
            "stage_key": "nonrecipe_finalize",
            "stage_state": "interrupted",
            "termination_cause": "operator_interrupt",
            "finalization_completeness": "interrupted_before_finalization",
            "artifact_states": {
                "phase_manifest.json": "skipped_due_to_interrupt",
                "task_status.jsonl": "skipped_due_to_interrupt",
                "worker_assignments.json": "present",
                "promotion_report.json": "skipped_due_to_interrupt",
                "telemetry.json": "skipped_due_to_interrupt",
                "failures.json": "skipped_due_to_interrupt",
                "knowledge_manifest.json": "present",
                "proposals/*": "present",
            },
            "pre_kill_failure_counts": {
                "worker_terminal_states": {"watchdog_killed": 1},
                "worker_reason_codes": {"watchdog_malformed_final_output": 1},
            },
        },
    )

    summary = summarize_knowledge_stage_artifacts(stage_root)

    assert summary["authoritative"] is True
    assert summary["schema_version"] == "knowledge_stage_summary.v10"
    assert summary["stage_state"] == "interrupted"
    assert summary["termination_cause"] == "operator_interrupt"
    assert summary["finalization_completeness"] == "interrupted_before_finalization"
    assert summary["pre_kill_failures_observed"] is True
    assert summary["artifact_states"]["phase_manifest.json"] == "skipped_due_to_interrupt"
    assert summary["artifact_states"]["task_status.jsonl"] == "skipped_due_to_interrupt"
    assert summary["artifact_states"]["worker_assignments.json"] == "present"
    assert summary["artifact_states"]["knowledge_manifest.json"] == "present"
    assert summary["worker_session_guardrails"]["planned_happy_path_worker_cap"] == 1
    assert summary["task_file_guardrails"]["warning_count"] == 0
    assert summary["packets"]["packet_total"] == 0
    assert summary["workers"]["outcome_counts"] == {}
    assert summary["followups"]["circuit_breaker_activation_count"] == 0
    assert summary["repair_recovery_policy"]["active_transport"] == "inline-json-v1"
    assert summary["salvage"]["success_count"] == 0
    assert summary["attention_summary"]["needs_attention"] is True
    assert summary["attention_summary"]["zero_target_counts"]["pre_kill_failure_count"] == 2


def test_summarize_knowledge_stage_artifacts_marks_unexpected_missing(tmp_path: Path) -> None:
    stage_root = tmp_path / "raw" / "llm" / "book" / "knowledge"
    stage_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        stage_root / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
        {
            "schema_version": "knowledge_stage_status.v1",
            "stage_key": "nonrecipe_finalize",
            "stage_state": "completed",
            "termination_cause": "completed",
            "finalization_completeness": "complete",
            "artifact_states": {
                "phase_manifest.json": "present",
                "task_status.jsonl": "present",
                "worker_assignments.json": "present",
                "promotion_report.json": "present",
                "telemetry.json": "present",
                "failures.json": "present",
                "knowledge_manifest.json": "present",
                "proposals/*": "present",
            },
            "pre_kill_failure_counts": {},
        },
    )
    _write_json(
        stage_root / "telemetry.json",
        {
            "summary": {
                "visible_input_tokens": 90,
                "visible_output_tokens": 30,
                "wrapper_overhead_tokens": 60,
                "tokens_reasoning": 0,
                "tokens_total": 180,
                "packet_economics": {
                    "packet_count_total": 3,
                    "primary_packet_count_total": 2,
                    "repair_packet_count_total": 1,
                    "owned_row_count_total": 3,
                    "packet_churn_count": 1,
                    "packets_per_shard": 3.0,
                    "repair_packet_share": 0.3333,
                    "packets_per_owned_row": 1.0,
                    "cost_per_owned_row": 60.0,
                    "visible_input_tokens_per_owned_row": 30.0,
                    "visible_output_tokens_per_owned_row": 10.0,
                    "wrapper_overhead_tokens_per_owned_row": 20.0,
                    "reasoning_tokens_per_owned_row": 0.0,
                    "semantic_payload_tokens_total": 120,
                    "semantic_payload_tokens_per_owned_row": 40.0,
                    "protocol_overhead_tokens_total": 60,
                    "protocol_overhead_share": 0.3333,
                },
            }
        },
    )

    summary = summarize_knowledge_stage_artifacts(stage_root)

    assert summary["authoritative"] is True
    assert summary["artifact_states"]["phase_manifest.json"] == "unexpectedly_missing"
    assert summary["artifact_states"]["task_status.jsonl"] == "unexpectedly_missing"
    assert summary["artifact_states"]["worker_assignments.json"] == "unexpectedly_missing"
    assert summary["artifact_states"]["proposals/*"] == "unexpectedly_missing"


def _build_knowledge_stage_rollup_fixture(tmp_path: Path) -> dict[str, object]:
    stage_root = tmp_path / "raw" / "llm" / "book" / "knowledge"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    (stage_root / "worker_assignments.json").write_text("[]\n", encoding="utf-8")
    (stage_root / "shard_manifest.jsonl").write_text(
        json.dumps({"shard_id": "book.ks0000.nr"}) + "\n",
        encoding="utf-8",
    )
    (stage_root.parent / KNOWLEDGE_MANIFEST_FILE_NAME).write_text(
        json.dumps(
            {
                "pipeline_id": "recipe.knowledge.compact.v1",
                "counts": {
                    "kept_knowledge_block_count": 2,
                    "retrieval_gate_rejected_block_count": 1,
                    "grounding_gate_demoted_block_count": 1,
                    "grounding_gate_demoted_after_invalid_grounding_drop_count": 1,
                    "grounding_gate_demoted_for_category_only_count": 0,
                    "knowledge_blocks_grounded_to_existing_tags": 1,
                    "knowledge_blocks_using_proposed_tags": 1,
                    "tag_proposal_count": 1,
                },
                "grounding_counts": {
                    "grounding_gate_demotion_reason_counts": {
                        "invalid_grounding_dropped_to_empty": 1
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (stage_root / "task_status.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "task_id": "book.ks0000.nr.task-001",
                        "state": "validated",
                        "last_attempt_type": "deterministic_bypass",
                        "terminal_reason_code": "deterministic_other_bypass",
                        "metadata": {
                            "deterministic_bypass_reason_code": "book_framing_or_marketing",
                            "watchdog_retry_status": "not_attempted",
                            "retry_status": "not_attempted",
                            "repair_status": "not_attempted",
                        },
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "task_id": "book.ks0000.nr.task-002",
                        "state": "retry_recovered",
                        "last_attempt_type": "watchdog_retry",
                        "terminal_reason_code": "validated",
                        "metadata": {
                            "watchdog_retry_status": "recovered",
                            "retry_status": "not_attempted",
                            "repair_status": "not_attempted",
                        },
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "task_id": "book.ks0000.nr.task-003",
                        "state": "repair_failed",
                        "last_attempt_type": "repair",
                        "terminal_reason_code": "repair_skipped_circuit_breaker",
                        "metadata": {
                            "watchdog_retry_status": "not_attempted",
                            "retry_status": "not_attempted",
                            "repair_status": "skipped",
                            "repair_skip_reason_code": "repair_skipped_circuit_breaker",
                        },
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        stage_root / "workers" / "worker-001" / "live_status.json",
        {"state": "completed", "reason_code": "workspace_outputs_stabilized"},
    )
    _write_json(
        stage_root / "telemetry.json",
        {
            "summary": {
                "visible_input_tokens": 90,
                "visible_output_tokens": 30,
                "wrapper_overhead_tokens": 60,
                "tokens_reasoning": 0,
                "tokens_total": 180,
                "packet_economics": {
                    "packet_count_total": 3,
                    "primary_packet_count_total": 2,
                    "repair_packet_count_total": 1,
                    "owned_row_count_total": 3,
                    "packet_churn_count": 1,
                    "packets_per_shard": 3.0,
                    "repair_packet_share": 0.3333,
                    "packets_per_owned_row": 1.0,
                    "cost_per_owned_row": 60.0,
                    "visible_input_tokens_per_owned_row": 30.0,
                    "visible_output_tokens_per_owned_row": 10.0,
                    "wrapper_overhead_tokens_per_owned_row": 20.0,
                    "reasoning_tokens_per_owned_row": 0.0,
                    "semantic_payload_tokens_total": 120,
                    "semantic_payload_tokens_per_owned_row": 40.0,
                    "protocol_overhead_tokens_total": 60,
                    "protocol_overhead_share": 0.3333,
                },
            }
        },
    )
    _write_json(
        stage_root / "workers" / "worker-001" / "assigned_tasks.json",
        [
            {"task_id": "book.ks0000.nr.task-001"},
            {"task_id": "book.ks0000.nr.task-002"},
            {"task_id": "book.ks0000.nr.task-003"},
        ],
    )
    _write_json(
        stage_root / "workers" / "worker-001" / "out" / "book.ks0000.nr.task-001.json",
        {"v": "2", "bid": "book.ks0000.nr.task-001", "r": []},
    )
    _write_json(
        stage_root
        / "workers"
        / "worker-001"
        / "shards"
        / "book.ks0000.nr.task-001"
        / "proposal.json",
        {
            "status": "validated",
            "validation_metadata": {"response_trailing_eof_trimmed": True},
        },
    )
    _write_json(
        stage_root
        / "workers"
        / "worker-001"
        / "shards"
        / "book.ks0000.nr.task-002"
        / "watchdog_retry"
        / "status.json",
        {"status": "validated"},
    )
    _write_json(
        stage_root
        / "workers"
        / "worker-001"
        / "shards"
        / "book.ks0000.nr.task-003"
        / "repair_live_status.json",
        {"state": "running"},
    )
    _write_json(
        stage_root / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
        {
            "schema_version": "knowledge_stage_status.v1",
            "stage_key": "nonrecipe_finalize",
            "stage_state": "completed_with_failures",
            "termination_cause": "completed",
            "finalization_completeness": "complete",
            "artifact_states": {
                "phase_manifest.json": "present",
                "shard_manifest.jsonl": "present",
                "task_manifest.jsonl": "present",
                "task_status.jsonl": "present",
                "worker_assignments.json": "present",
                "promotion_report.json": "present",
                "telemetry.json": "present",
                "failures.json": "present",
                "knowledge_manifest.json": "present",
                "proposals/*": "present",
            },
            "pre_kill_failure_counts": {},
        },
    )

    summary = summarize_knowledge_stage_artifacts(stage_root)
    return {
        "summary": summary,
    }


def test_summarize_knowledge_stage_artifacts_reports_packet_and_worker_rollups(
    tmp_path: Path,
) -> None:
    fixture = _build_knowledge_stage_rollup_fixture(tmp_path)
    summary = fixture["summary"]

    assert summary["packets"]["packet_total"] == 3
    assert summary["packets"]["deterministic_bypass_total"] == 1
    assert summary["packets"]["llm_review_total"] == 2
    assert summary["packets"]["deterministic_bypass_reason_code_counts"] == {
        "book_framing_or_marketing": 1
    }
    assert summary["packets"]["state_counts"] == {
        "repair_failed": 1,
        "retry_recovered": 1,
        "validated": 1,
    }
    assert summary["packets"]["terminal_outcome_counts"] == {
        "repair_failed": 1,
        "retry_recovered": 1,
        "validated": 1,
    }
    assert summary["packets"]["no_final_output_shard_count"] == 0
    assert summary["packets"]["no_final_output_reason_code_counts"] == {}
    assert summary["packets"]["topline"]["deterministic_bypass"] == 1
    assert summary["workers"]["outcome_counts"] == {
        "completed_outputs_stabilized": 1,
    }
    assert summary["workers"]["output_count"] == 1
    assert summary["repair_recovery_policy"]["active_transport"] == "inline-json-v1"
    assert (
        summary["repair_recovery_policy"]["semantic_steps"]["nonrecipe_classify"][
            "budgets"
        ]["structured_repair_followup"]["allowed_attempts"]
        == 3
    )
    assert summary["packet_economics"] == {
        "packet_count_total": 3,
        "primary_packet_count_total": 2,
        "repair_packet_count_total": 1,
        "owned_row_count_total": 3,
        "packet_churn_count": 1,
        "packets_per_shard": 3.0,
        "repair_packet_share": 0.3333,
        "packets_per_owned_row": 1.0,
        "cost_per_owned_row": 60.0,
        "visible_input_tokens_per_owned_row": 30.0,
        "visible_output_tokens_per_owned_row": 10.0,
        "wrapper_overhead_tokens_per_owned_row": 20.0,
        "reasoning_tokens_per_owned_row": 0.0,
        "semantic_payload_tokens_total": 120,
        "semantic_payload_tokens_per_owned_row": 40.0,
        "protocol_overhead_tokens_total": 60,
        "protocol_overhead_share": 0.3333,
    }
    assert summary["grounding_counts"] == {
        "kept_knowledge_block_count": 2,
        "retrieval_gate_rejected_block_count": 1,
        "grounding_gate_demoted_block_count": 1,
        "grounding_gate_demoted_after_invalid_grounding_drop_count": 1,
        "grounding_gate_demoted_for_category_only_count": 0,
        "knowledge_blocks_grounded_to_existing_tags": 1,
        "knowledge_blocks_using_proposed_tags": 1,
        "tag_proposal_count": 1,
        "grounding_gate_demotion_reason_counts": {
            "invalid_grounding_dropped_to_empty": 1
        },
    }


def test_summarize_knowledge_stage_artifacts_reports_followup_and_salvage_rollups(
    tmp_path: Path,
) -> None:
    fixture = _build_knowledge_stage_rollup_fixture(tmp_path)
    summary = fixture["summary"]

    assert summary["followups"]["attempt_counts"] == {
        "repair": 1,
        "watchdog_retry": 1,
    }
    assert summary["followups"]["accepted_counts"] == {"watchdog_retry": 1}
    assert summary["followups"]["skip_reason_counts"] == {
        "repair_skipped_circuit_breaker": 1,
    }
    assert summary["followups"]["stale_count"] == 1
    assert summary["followups"]["stale_counts"] == {"repair": 1}
    assert summary["followups"]["circuit_breaker_activation_count"] == 1
    assert summary["salvage"]["success_count"] == 1
    assert summary["salvage"]["kind_counts"] == {"trailing_eof_trimmed": 1}
    assert "semantic_audit_open_shard_count" not in summary["attention_summary"]["zero_target_counts"]
    assert "semantic_audit_repair_requested_count" not in summary["attention_summary"]["context_counts"]
    assert "semantic_audit_flag_code_counts" not in summary["attention_summary"]["reason_counts"]
