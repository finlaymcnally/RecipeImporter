from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
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
        "extract_knowledge_optional",
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
