from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.bench.eval_stage_blocks import (
    compute_block_metrics,
    evaluate_stage_blocks,
    load_gold_block_labels,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_load_gold_block_labels_allows_multilabel_blocks(tmp_path: Path) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    conflict_path = tmp_path / "gold_conflicts.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "a", "label": "RECIPE_TITLE", "touched_block_indices": [0]},
            {"span_id": "b", "label": "INGREDIENT_LINE", "touched_block_indices": [0]},
        ],
    )

    gold = load_gold_block_labels(gold_path, conflict_output_path=conflict_path)
    assert gold == {0: {"RECIPE_TITLE", "INGREDIENT_LINE"}}

    lines = [line for line in conflict_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["warning"] == "gold_block_has_multiple_labels"
    assert payload["block_index"] == 0
    assert set(payload["labels"]) == {"INGREDIENT_LINE", "RECIPE_TITLE"}


def test_load_gold_block_labels_requires_exhaustive_blocks(tmp_path: Path) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    conflict_path = tmp_path / "gold_conflicts.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "a", "label": "RECIPE_TITLE", "touched_block_indices": [1]},
            {"span_id": "b", "label": "INGREDIENT_LINE", "touched_block_indices": [2]},
        ],
    )

    with pytest.raises(ValueError, match="Gold is not exhaustive"):
        load_gold_block_labels(gold_path, conflict_output_path=conflict_path)

    lines = [line for line in conflict_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["error"] == "gold_missing_block_labels"
    assert payload["missing_block_indices"] == [0]


def test_compute_block_metrics_reports_macro_and_worst_label() -> None:
    gold = {
        0: "RECIPE_TITLE",
        1: "INGREDIENT_LINE",
        2: "INSTRUCTION_LINE",
        3: "OTHER",
    }
    pred = {
        0: "RECIPE_TITLE",
        1: "OTHER",
        2: "INSTRUCTION_LINE",
        3: "OTHER",
    }

    metrics = compute_block_metrics(gold, pred)

    assert metrics["overall_block_accuracy"] == pytest.approx(0.75)
    assert metrics["macro_f1_excluding_other"] == pytest.approx(2 / 3)
    assert metrics["worst_label_recall"]["label"] == "INGREDIENT_LINE"
    assert metrics["worst_label_recall"]["recall"] == pytest.approx(0.0)
    assert metrics["per_label"]["INGREDIENT_LINE"]["gold_total"] == 1
    assert metrics["per_label"]["INGREDIENT_LINE"]["pred_total"] == 0


def test_compute_block_metrics_accepts_any_gold_label_match() -> None:
    gold = {
        0: {"RECIPE_TITLE", "RECIPE_NOTES"},
        1: "INGREDIENT_LINE",
    }
    pred = {
        0: "RECIPE_NOTES",
        1: "OTHER",
    }

    metrics = compute_block_metrics(gold, pred)

    assert metrics["overall_block_accuracy"] == pytest.approx(0.5)
    assert metrics["wrong_label_blocks"] == [
        {
            "block_index": 1,
            "gold_label": "INGREDIENT_LINE",
            "gold_labels": ["INGREDIENT_LINE"],
            "pred_label": "OTHER",
        }
    ]
    assert metrics["per_label"]["RECIPE_NOTES"]["gold_total"] == 1
    assert metrics["per_label"]["RECIPE_NOTES"]["pred_total"] == 1
    assert metrics["per_label"]["RECIPE_NOTES"]["recall"] == pytest.approx(1.0)
    assert metrics["per_label"]["RECIPE_TITLE"]["gold_total"] == 1
    assert metrics["per_label"]["RECIPE_TITLE"]["pred_total"] == 0
    assert metrics["per_label"]["RECIPE_TITLE"]["recall"] == pytest.approx(0.0)


def test_evaluate_stage_blocks_writes_reports_and_debug_artifacts(tmp_path: Path) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "touched_block_indices": [0]},
            {"span_id": "s1", "label": "INGREDIENT_LINE", "touched_block_indices": [1]},
            {"span_id": "s2", "label": "INSTRUCTION_LINE", "touched_block_indices": [2]},
            {"span_id": "s3", "label": "OTHER", "touched_block_indices": [3]},
        ],
    )

    stage_path = tmp_path / "stage_block_predictions.json"
    stage_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "abc123",
                "block_count": 4,
                "block_labels": {
                    "0": "RECIPE_TITLE",
                    "1": "OTHER",
                    "2": "INSTRUCTION_LINE",
                    "3": "OTHER",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {"index": 0, "text": "Simple Soup"},
                {"index": 1, "text": "1 cup stock"},
                {"index": 2, "text": "Heat stock."},
                {"index": 3, "text": "Page footer"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "eval"
    result = evaluate_stage_blocks(
        gold_freeform_jsonl=gold_path,
        stage_predictions_json=stage_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=out_dir,
    )

    report = result["report"]
    assert report["overall_block_accuracy"] == pytest.approx(0.75)
    assert report["macro_f1_excluding_other"] == pytest.approx(2 / 3)
    assert report["worst_label_recall"]["label"] == "INGREDIENT_LINE"
    assert report["worst_label_recall"]["recall"] == pytest.approx(0.0)

    assert (out_dir / "eval_report.json").exists()
    assert (out_dir / "eval_report.md").exists()
    assert (out_dir / "missed_gold_blocks.jsonl").exists()
    assert (out_dir / "wrong_label_blocks.jsonl").exists()
    assert (out_dir / "missed_gold_spans.jsonl").exists()
    assert (out_dir / "false_positive_preds.jsonl").exists()

    missed_rows = [
        json.loads(line)
        for line in (out_dir / "missed_gold_blocks.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(missed_rows) == 1
    assert missed_rows[0]["block_index"] == 1
    assert missed_rows[0]["gold_label"] == "INGREDIENT_LINE"
    assert missed_rows[0]["gold_labels"] == ["INGREDIENT_LINE"]
    assert missed_rows[0]["pred_label"] == "OTHER"


def test_evaluate_stage_blocks_allows_multilabel_gold_blocks(tmp_path: Path) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "s0a", "label": "RECIPE_TITLE", "touched_block_indices": [0]},
            {"span_id": "s0b", "label": "OTHER", "touched_block_indices": [0]},
            {"span_id": "s1", "label": "INGREDIENT_LINE", "touched_block_indices": [1]},
        ],
    )

    stage_path = tmp_path / "stage_block_predictions.json"
    stage_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "abc123",
                "block_count": 2,
                "block_labels": {
                    "0": "OTHER",
                    "1": "OTHER",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {"index": 0, "text": "Simple Soup"},
                {"index": 1, "text": "1 cup stock"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "eval"
    result = evaluate_stage_blocks(
        gold_freeform_jsonl=gold_path,
        stage_predictions_json=stage_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=out_dir,
    )

    report = result["report"]
    assert report["overall_block_accuracy"] == pytest.approx(0.5)
    assert report["wrong_label_blocks"] == [
        {
            "block_index": 1,
            "gold_label": "INGREDIENT_LINE",
            "gold_labels": ["INGREDIENT_LINE"],
            "pred_label": "OTHER",
        }
    ]
    conflict_lines = [
        line
        for line in (out_dir / "gold_conflicts.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(conflict_lines) == 1
    conflict_payload = json.loads(conflict_lines[0])
    assert conflict_payload["warning"] == "gold_block_has_multiple_labels"
    assert conflict_payload["block_index"] == 0


def test_evaluate_stage_blocks_defaults_missing_gold_blocks_to_other(tmp_path: Path) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "s1", "label": "RECIPE_TITLE", "touched_block_indices": [1]},
            {"span_id": "s2", "label": "INGREDIENT_LINE", "touched_block_indices": [2]},
        ],
    )

    stage_path = tmp_path / "stage_block_predictions.json"
    stage_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "abc123",
                "block_count": 3,
                "block_labels": {
                    "0": "OTHER",
                    "1": "RECIPE_TITLE",
                    "2": "INGREDIENT_LINE",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {"index": 0, "text": "Page footer"},
                {"index": 1, "text": "Simple Soup"},
                {"index": 2, "text": "1 cup stock"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "eval"
    result = evaluate_stage_blocks(
        gold_freeform_jsonl=gold_path,
        stage_predictions_json=stage_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=out_dir,
    )

    report = result["report"]
    assert report["overall_block_accuracy"] == pytest.approx(1.0)
    assert report["wrong_label_blocks"] == []
    diagnostics = [
        json.loads(line)
        for line in (out_dir / "gold_conflicts.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0]["warning"] == "gold_missing_block_labels_defaulted_to_other"
    assert diagnostics[0]["missing_gold_indices"] == [0]
    assert diagnostics[0]["default_label"] == "OTHER"
