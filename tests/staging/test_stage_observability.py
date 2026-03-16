from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from cookimport.runs import (
    RECIPE_MANIFEST_FILE_NAME,
    KNOWLEDGE_MANIFEST_FILE_NAME,
    build_stage_observability_report,
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


def test_build_stage_observability_report_for_three_pass_recipe_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    llm_root = run_root / "raw" / "llm" / "book"
    for stage_key in ("chunking", "schemaorg", "final"):
        (llm_root / stage_key / "in").mkdir(parents=True)
    _write_json(
        llm_root / RECIPE_MANIFEST_FILE_NAME,
        {
            "pipeline": "codex-farm-3pass-v1",
            "process_runs": {"pass1": {}, "pass2": {}, "pass3": {}},
        },
    )

    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="bench_pred_run",
        created_at="2026-03-15T23:40:19",
        run_config={},
    )

    assert _stage_keys(report) == ["chunking", "schemaorg", "final"]
    assert [row.stage_label for row in report.stages] == [
        "Chunking",
        "Schema.org Extraction",
        "Final Draft",
    ]


def test_build_stage_observability_report_for_merged_repair_recipe_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    llm_root = run_root / "raw" / "llm" / "book"
    for stage_key in ("chunking", "merged_repair"):
        (llm_root / stage_key / "out").mkdir(parents=True)
    _write_json(
        llm_root / RECIPE_MANIFEST_FILE_NAME,
        {
            "pipeline": "codex-farm-2stage-repair-v1",
            "process_runs": {"pass1": {}, "pass2": {}},
        },
    )

    report = build_stage_observability_report(
        run_root=run_root,
        run_kind="bench_pred_run",
        created_at="2026-03-15T23:40:19",
        run_config={},
    )

    assert _stage_keys(report) == ["chunking", "merged_repair"]
    assert report.stages[1].stage_label == "Merged Repair"


def test_build_stage_observability_report_for_knowledge_enabled_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    llm_root = run_root / "raw" / "llm" / "book"
    (llm_root / "knowledge" / "in").mkdir(parents=True)
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

    assert _stage_keys(report) == ["knowledge", "write_outputs"]
    assert report.stages[0].workbooks[0].manifest_path == (
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
