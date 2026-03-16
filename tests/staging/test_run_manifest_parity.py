from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.cli import app
from cookimport.labelstudio.ingest import generate_pred_run_artifacts

runner = CliRunner()


def _walk_line_bounds(payload: object) -> list[int]:
    values: list[int] = []
    if isinstance(payload, dict):
        if "start_line" in payload:
            try:
                values.append(int(payload["start_line"]))
            except (TypeError, ValueError):
                pass
        if "end_line" in payload:
            try:
                values.append(int(payload["end_line"]))
            except (TypeError, ValueError):
                pass
        for nested in payload.values():
            values.extend(_walk_line_bounds(nested))
    elif isinstance(payload, list):
        for nested in payload:
            values.extend(_walk_line_bounds(nested))
    return values


def _line_bounds_from_stage_run(stage_run_root: Path) -> tuple[int, int]:
    values: list[int] = []
    for raw_json in stage_run_root.glob("raw/**/*.json"):
        try:
            payload = json.loads(raw_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values.extend(_walk_line_bounds(payload))
    assert values, "Stage run did not produce line-coordinate metadata in raw artifacts."
    return min(values), max(values)


def _line_bounds_from_pred_run(pred_run_root: Path) -> tuple[int, int] | None:
    values: list[int] = []
    archive_path = pred_run_root / "extracted_archive.json"
    if archive_path.exists():
        try:
            archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            archive_payload = []
        if isinstance(archive_payload, list):
            for block in archive_payload:
                if not isinstance(block, dict):
                    continue
                values.extend(_walk_line_bounds(block.get("location")))

    tasks_path = pred_run_root / "label_studio_tasks.jsonl"
    if tasks_path.exists():
        for line in tasks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            data = payload.get("data")
            if not isinstance(data, dict):
                continue
            # Freeform tasks carry source location metadata in source_map blocks.
            values.extend(_walk_line_bounds(data.get("source_map")))
    if not values:
        return None
    return min(values), max(values)


def test_stage_and_pred_run_manifests_share_source_identity_and_coords(tmp_path: Path) -> None:
    source = Path("tests/fixtures/simple_text.txt")
    stage_output = tmp_path / "stage-output"
    stage_result = runner.invoke(
        app,
        [
            "stage",
            str(source),
            "--out",
            str(stage_output),
            "--workers",
            "1",
            "--pdf-split-workers",
            "1",
            "--epub-split-workers",
            "1",
            "--ocr-device",
            "auto",
            "--ocr-batch-size",
            "1",
            "--pdf-pages-per-job",
            "50",
            "--epub-spine-items-per-job",
            "10",
            "--epub-extractor",
            "unstructured",
            "--llm-recipe-pipeline",
            "off",
        ],
    )
    assert stage_result.exit_code == 0

    stage_runs = [
        path
        for path in stage_output.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(stage_runs) == 1
    stage_run = stage_runs[0]

    pred_output = tmp_path / "pred-output"
    pred_result = generate_pred_run_artifacts(
        path=source,
        output_dir=pred_output,
        pipeline="text",
        workers=1,
        pdf_split_workers=1,
        epub_split_workers=1,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        ocr_device="auto",
        ocr_batch_size=1,
        warm_models=False,
        llm_recipe_pipeline="off",
    )
    pred_run = Path(pred_result["run_root"])

    stage_manifest = json.loads((stage_run / "run_manifest.json").read_text(encoding="utf-8"))
    pred_manifest = json.loads((pred_run / "run_manifest.json").read_text(encoding="utf-8"))
    assert (stage_run / "stage_observability.json").exists()
    assert (pred_run / "stage_observability.json").exists()
    assert stage_manifest["artifacts"]["stage_observability_json"] == "stage_observability.json"
    assert pred_manifest["artifacts"]["stage_observability_json"] == "stage_observability.json"
    assert stage_manifest["run_kind"] == "stage"
    assert pred_manifest["run_kind"] == "bench_pred_run"
    assert stage_manifest["source"]["source_hash"] == pred_manifest["source"]["source_hash"]

    stage_cfg = stage_manifest["run_config"]
    pred_cfg = pred_manifest["run_config"]
    parity_keys = {
        "bucket1_fixed_behavior_version",
        "workers",
        "pdf_split_workers",
        "epub_split_workers",
        "pdf_pages_per_job",
        "epub_spine_items_per_job",
        "epub_extractor",
        "epub_unstructured_html_parser_version",
        "epub_unstructured_skip_headers_footers",
        "epub_unstructured_preprocess_mode",
        "ingredient_text_fix_backend",
        "ingredient_pre_normalize_mode",
        "ingredient_packaging_mode",
        "ingredient_parser_backend",
        "ingredient_unit_canonicalizer",
        "ingredient_missing_unit_policy",
        "ocr_device",
        "ocr_batch_size",
        "warm_models",
        "llm_recipe_pipeline",
        "llm_knowledge_pipeline",
        "codex_farm_cmd",
        "codex_farm_context_blocks",
        "codex_farm_knowledge_context_blocks",
        "codex_farm_failure_mode",
        "write_markdown",
    }
    for key in parity_keys:
        assert stage_cfg[key] == pred_cfg[key]

    pred_line_bounds = _line_bounds_from_pred_run(pred_run)
    if pred_line_bounds is not None:
        assert _line_bounds_from_stage_run(stage_run) == pred_line_bounds
