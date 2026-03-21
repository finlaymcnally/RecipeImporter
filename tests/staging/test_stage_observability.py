from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
from cookimport.runs import (
    RECIPE_MANIFEST_FILE_NAME,
    KNOWLEDGE_MANIFEST_FILE_NAME,
    KNOWLEDGE_STAGE_STATUS_FILE_NAME,
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
    assert summary["stage_state"] == "interrupted"
    assert summary["termination_cause"] == "operator_interrupt"
    assert summary["finalization_completeness"] == "interrupted_before_finalization"
    assert summary["pre_kill_failures_observed"] is True
    assert summary["artifact_states"]["phase_manifest.json"] == "skipped_due_to_interrupt"
    assert summary["artifact_states"]["task_status.jsonl"] == "skipped_due_to_interrupt"
    assert summary["artifact_states"]["worker_assignments.json"] == "present"
    assert summary["artifact_states"]["knowledge_manifest.json"] == "present"


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
