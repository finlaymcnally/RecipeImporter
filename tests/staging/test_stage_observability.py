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
        "build_intermediate_det",
        "recipe_llm_correct_and_link",
        "build_final_recipe",
    ]
    assert [row.stage_label for row in report.stages] == [
        "Build Intermediate Recipe",
        "Recipe LLM Correction",
        "Build Final Recipe",
    ]


def test_build_stage_observability_report_for_knowledge_enabled_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    llm_root = run_root / "raw" / "llm" / "book"
    (llm_root / "knowledge" / "in").mkdir(parents=True)
    (run_root / "08_nonrecipe_spans.json").write_text("{}", encoding="utf-8")
    (run_root / "09_knowledge_outputs.json").write_text("{}", encoding="utf-8")
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
        "classify_nonrecipe",
        "nonrecipe_knowledge_review",
        "write_outputs",
    ]
    assert report.stages[1].stage_label == "Non-Recipe Knowledge Review"
    assert report.stages[1].workbooks[0].manifest_path == (
        "raw/llm/book/knowledge_manifest.json"
    )


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
    stage_root = run_root / "raw" / "llm" / "book" / "knowledge"
    stage_root.mkdir(parents=True, exist_ok=True)
    (stage_root.parent / KNOWLEDGE_MANIFEST_FILE_NAME).write_text(
        json.dumps({"pipeline_id": "recipe.knowledge.compact.v1"}, sort_keys=True),
        encoding="utf-8",
    )
    _write_json(
        stage_root / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
        {
            "schema_version": "knowledge_stage_status.v1",
            "stage_key": "nonrecipe_knowledge_review",
            "stage_state": "completed",
            "termination_cause": "completed",
            "finalization_completeness": "complete",
            "artifact_states": {},
            "pre_kill_failure_counts": {},
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
    (line_role_root / "task_manifest.jsonl").write_text(
        json.dumps({"task_id": "line-role-canonical-0001.task-001"}) + "\n",
        encoding="utf-8",
    )
    (line_role_root / "workers" / "worker-001" / "out" / "line-role-canonical-0001.task-001.json").write_text(
        "{}",
        encoding="utf-8",
    )
    _write_json(
        line_role_root / "workers" / "worker-001" / "shards" / "line-role-canonical-0001" / "status.json",
        {"status": "validated"},
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
        stage for stage in payload["stages"] if stage["stage_key"] == "recipe_llm_correct_and_link"
    )
    line_role_stage = next(
        stage for stage in payload["stages"] if stage["stage_key"] == "line_role"
    )

    assert (run_root / recipe_stage["workbooks"][0]["artifact_paths"]["recipe_stage_summary_json"]).exists()
    assert (run_root / line_role_stage["workbooks"][0]["artifact_paths"]["line_role_stage_summary_json"]).exists()


def test_build_line_role_stage_summary_reports_packet_and_line_rollups(tmp_path: Path) -> None:
    stage_root = tmp_path / "line-role-pipeline" / "runtime" / "line_role"
    (stage_root / "proposals").mkdir(parents=True, exist_ok=True)
    _write_json(stage_root / "phase_manifest.json", {"worker_count": 1, "shard_count": 1})
    (stage_root / "task_manifest.jsonl").write_text(
        json.dumps({"task_id": "line-role-canonical-0001.task-001"}) + "\n",
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
    (stage_root / "task_status.jsonl").write_text(
        json.dumps(
            {
                "task_id": "line-role-canonical-0001.task-001",
                "state": "validated",
                "terminal_outcome": "validated",
                "last_attempt_type": "resume_existing_output",
                "metadata": {
                    "llm_authoritative_row_count": 2,
                    "fallback_row_count": 0,
                    "suspicious_row_count": 2,
                    "suspicious_packet": True,
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

    summary = build_line_role_stage_summary(stage_root)

    assert summary["lines"]["canonical_line_total"] == 2
    assert summary["lines"]["llm_authoritative_row_count"] == 2
    assert summary["lines"]["fallback_row_count"] == 0
    assert summary["packets"]["packet_total"] == 1
    assert summary["packets"]["state_counts"] == {"validated": 1}
    assert summary["packets"]["attempt_type_counts"] == {"resume_existing_output": 1}
    assert summary["packets"]["suspicious_packet_count"] == 1
    assert summary["important_artifacts"]["canonical_line_table_jsonl"] == "canonical_line_table.jsonl"
    assert summary["important_artifacts"]["task_status_jsonl"] == "task_status.jsonl"


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
        stage_root / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
        {
            "schema_version": "knowledge_stage_status.v1",
            "stage_key": "nonrecipe_knowledge_review",
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
    assert summary["schema_version"] == "knowledge_stage_summary.v1"
    assert summary["stage_state"] == "interrupted"
    assert summary["termination_cause"] == "operator_interrupt"
    assert summary["finalization_completeness"] == "interrupted_before_finalization"
    assert summary["pre_kill_failures_observed"] is True
    assert summary["artifact_states"]["phase_manifest.json"] == "skipped_due_to_interrupt"
    assert summary["artifact_states"]["task_status.jsonl"] == "skipped_due_to_interrupt"
    assert summary["artifact_states"]["worker_assignments.json"] == "present"
    assert summary["artifact_states"]["knowledge_manifest.json"] == "present"
    assert summary["packets"]["packet_total"] == 0
    assert summary["workers"]["outcome_counts"] == {}
    assert summary["followups"]["circuit_breaker_activation_count"] == 0
    assert summary["salvage"]["success_count"] == 0


def test_summarize_knowledge_stage_artifacts_marks_unexpected_missing(tmp_path: Path) -> None:
    stage_root = tmp_path / "raw" / "llm" / "book" / "knowledge"
    stage_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        stage_root / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
        {
            "schema_version": "knowledge_stage_status.v1",
            "stage_key": "nonrecipe_knowledge_review",
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
        json.dumps({"pipeline_id": "recipe.knowledge.compact.v1"}, sort_keys=True),
        encoding="utf-8",
    )
    (stage_root / "task_status.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "task_id": "book.ks0000.nr.task-001",
                        "state": "validated",
                        "last_attempt_type": "main_worker",
                        "terminal_reason_code": "validated",
                        "metadata": {
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
            "stage_key": "nonrecipe_knowledge_review",
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
    assert summary["workers"]["outcome_counts"] == {
        "completed_outputs_stabilized": 1,
    }
    assert summary["workers"]["output_count"] == 1


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
