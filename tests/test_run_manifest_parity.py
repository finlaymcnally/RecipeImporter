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


def _line_bounds_from_pred_run(pred_run_root: Path) -> tuple[int, int]:
    values: list[int] = []
    tasks_path = pred_run_root / "label_studio_tasks.jsonl"
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        values.extend(_walk_line_bounds(data.get("location")))
    assert values, "Prediction run did not produce line-coordinate metadata."
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
    )
    pred_run = Path(pred_result["run_root"])

    stage_manifest = json.loads((stage_run / "run_manifest.json").read_text(encoding="utf-8"))
    pred_manifest = json.loads((pred_run / "run_manifest.json").read_text(encoding="utf-8"))
    assert stage_manifest["run_kind"] == "stage"
    assert pred_manifest["run_kind"] == "bench_pred_run"
    assert stage_manifest["source"]["source_hash"] == pred_manifest["source"]["source_hash"]

    stage_cfg = stage_manifest["run_config"]
    pred_cfg = pred_manifest["run_config"]
    parity_keys = {
        "workers",
        "pdf_split_workers",
        "epub_split_workers",
        "pdf_pages_per_job",
        "epub_spine_items_per_job",
        "epub_extractor",
        "ocr_device",
        "ocr_batch_size",
        "warm_models",
    }
    for key in parity_keys:
        assert stage_cfg[key] == pred_cfg[key]

    assert _line_bounds_from_stage_run(stage_run) == _line_bounds_from_pred_run(pred_run)
