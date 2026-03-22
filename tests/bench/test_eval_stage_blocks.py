from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import cookimport.bench.eval_canonical_text as canonical_eval
from cookimport.bench.eval_canonical_text import evaluate_canonical_text
from cookimport.bench.eval_stage_blocks import (
    compute_block_metrics,
    evaluate_stage_blocks,
    load_gold_block_labels,
    load_stage_block_labels,
)
from cookimport.labelstudio.canonical_line_projection import (
    write_line_role_projection_artifacts,
)
from cookimport.parsing.canonical_line_roles import CanonicalLineRolePrediction


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


def test_load_gold_block_labels_maps_howto_section_by_neighboring_labels(tmp_path: Path) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "a", "label": "INGREDIENT_LINE", "touched_block_indices": [0]},
            {"span_id": "b", "label": "HOWTO_SECTION", "touched_block_indices": [1]},
            {"span_id": "c", "label": "INGREDIENT_LINE", "touched_block_indices": [2]},
            {"span_id": "d", "label": "INSTRUCTION_LINE", "touched_block_indices": [3]},
            {"span_id": "e", "label": "HOWTO_SECTION", "touched_block_indices": [4]},
            {"span_id": "f", "label": "INSTRUCTION_LINE", "touched_block_indices": [5]},
        ],
    )

    gold = load_gold_block_labels(gold_path)
    assert gold[1] == {"INGREDIENT_LINE"}
    assert gold[4] == {"INSTRUCTION_LINE"}


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


def test_build_gold_line_labels_preserves_howto_section_labels() -> None:
    lines = canonical_eval._build_canonical_lines("a\nb\nc\nd\ne")
    gold_spans = [
        {
            "span_id": "s0",
            "label": "INGREDIENT_LINE",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "HOWTO_SECTION",
            "start_char": lines[1]["start_char"],
            "end_char": lines[1]["end_char"],
        },
        {
            "span_id": "s2",
            "label": "INGREDIENT_LINE",
            "start_char": lines[2]["start_char"],
            "end_char": lines[2]["end_char"],
        },
        {
            "span_id": "s3",
            "label": "INSTRUCTION_LINE",
            "start_char": lines[3]["start_char"],
            "end_char": lines[3]["end_char"],
        },
        {
            "span_id": "s4",
            "label": "HOWTO_SECTION",
            "start_char": lines[4]["start_char"],
            "end_char": lines[4]["end_char"],
        },
    ]

    labels = canonical_eval._build_gold_line_labels(
        lines=lines,
        gold_spans=gold_spans,
        strict_empty_to_other=False,
    )
    assert labels[1] == {"HOWTO_SECTION"}
    assert labels[4] == {"HOWTO_SECTION"}


def test_load_stage_block_labels_maps_howto_section_by_neighboring_labels(
    tmp_path: Path,
) -> None:
    stage_path = tmp_path / "stage_block_predictions.json"
    stage_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "abc123",
                "block_count": 6,
                "block_labels": {
                    "0": "INGREDIENT_LINE",
                    "1": "HOWTO_SECTION",
                    "2": "INGREDIENT_LINE",
                    "3": "INSTRUCTION_LINE",
                    "4": "HOWTO_SECTION",
                    "5": "INSTRUCTION_LINE",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    labels = load_stage_block_labels(stage_path)
    assert labels[1] == "INGREDIENT_LINE"
    assert labels[4] == "INSTRUCTION_LINE"


def test_build_pred_line_labels_preserves_howto_section_labels() -> None:
    lines = canonical_eval._build_canonical_lines("a\nb\nc\nd\ne")

    def _line_block_payload(line_index: int, label: str) -> dict[str, object]:
        line = lines[line_index]
        return {
            "matched": True,
            "label": label,
            "canonical_start_char": line["start_char"],
            "canonical_end_char": line["end_char"],
        }

    aligned_prediction_blocks = [
        _line_block_payload(0, "INGREDIENT_LINE"),
        _line_block_payload(1, "HOWTO_SECTION"),
        _line_block_payload(2, "INGREDIENT_LINE"),
        _line_block_payload(3, "INSTRUCTION_LINE"),
        _line_block_payload(4, "HOWTO_SECTION"),
    ]

    labels = canonical_eval._build_pred_line_labels(
        lines=lines,
        aligned_prediction_blocks=aligned_prediction_blocks,
    )
    assert labels[1] == "HOWTO_SECTION"
    assert labels[4] == "HOWTO_SECTION"


def test_evaluate_canonical_text_includes_howto_section_totals(tmp_path: Path) -> None:
    canonical_text = "FOR THE SAUCE\n1 cup cream\nWhisk until smooth."
    canonical_lines = canonical_eval._build_canonical_lines(canonical_text)

    gold_export_root = tmp_path / "gold"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    canonical_text_path = gold_export_root / "canonical_text.txt"
    canonical_spans_path = gold_export_root / "canonical_span_labels.jsonl"
    canonical_text_path.write_text(canonical_text, encoding="utf-8")
    _write_jsonl(
        canonical_spans_path,
        [
            {
                "span_id": "s0",
                "label": "HOWTO_SECTION",
                "start_char": canonical_lines[0]["start_char"],
                "end_char": canonical_lines[0]["end_char"],
            },
            {
                "span_id": "s1",
                "label": "INGREDIENT_LINE",
                "start_char": canonical_lines[1]["start_char"],
                "end_char": canonical_lines[1]["end_char"],
            },
            {
                "span_id": "s2",
                "label": "INSTRUCTION_LINE",
                "start_char": canonical_lines[2]["start_char"],
                "end_char": canonical_lines[2]["end_char"],
            },
        ],
    )

    stage_predictions_path = tmp_path / "stage_block_predictions.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "hash-demo",
                "block_count": 3,
                "block_labels": {
                    "0": "HOWTO_SECTION",
                    "1": "INGREDIENT_LINE",
                    "2": "INSTRUCTION_LINE",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_blocks_path = tmp_path / "extracted_archive.json"
    extracted_blocks_path.write_text(
        json.dumps(
            [
                {"index": 0, "text": "FOR THE SAUCE"},
                {"index": 1, "text": "1 cup cream"},
                {"index": 2, "text": "Whisk until smooth."},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_blocks_path,
        out_dir=tmp_path / "eval",
        strict_empty_gold_to_other=True,
        canonical_paths={
            "canonical_text_path": canonical_text_path,
            "canonical_span_labels_path": canonical_spans_path,
            "canonical_manifest_path": gold_export_root / "canonical_manifest.json",
        },
    )
    report = result["report"]

    assert report["per_label"]["HOWTO_SECTION"]["gold_total"] == 1
    assert report["per_label"]["HOWTO_SECTION"]["pred_total"] == 1
    assert report["per_label"]["HOWTO_SECTION"]["tp"] == 1
    assert report["confusion"]["HOWTO_SECTION"]["HOWTO_SECTION"] == 1


def test_evaluate_canonical_text_scores_knowledge_stage_in_line_role_projection(
    tmp_path: Path,
) -> None:
    canonical_text = "Recipe Title\nUseful kitchen note\n1 cup stock"
    canonical_lines = canonical_eval._build_canonical_lines(canonical_text)

    gold_export_root = tmp_path / "gold"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    (gold_export_root / "canonical_text.txt").write_text(canonical_text, encoding="utf-8")
    _write_jsonl(
        gold_export_root / "canonical_span_labels.jsonl",
        [
            {
                "span_id": "s0",
                "label": "RECIPE_TITLE",
                "start_char": canonical_lines[0]["start_char"],
                "end_char": canonical_lines[0]["end_char"],
            },
            {
                "span_id": "s1",
                "label": "KNOWLEDGE",
                "start_char": canonical_lines[1]["start_char"],
                "end_char": canonical_lines[1]["end_char"],
            },
            {
                "span_id": "s2",
                "label": "INGREDIENT_LINE",
                "start_char": canonical_lines[2]["start_char"],
                "end_char": canonical_lines[2]["end_char"],
            },
        ],
    )
    (gold_export_root / "canonical_manifest.json").write_text(
        json.dumps({"schema_version": "canonical_gold.v1"}, sort_keys=True),
        encoding="utf-8",
    )

    predictions = [
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="b0",
            block_index=0,
            atomic_index=0,
            text="Recipe Title",
            within_recipe_span=False,
            label="RECIPE_TITLE",
            decided_by="rule",
            reason_tags=["test"],
        ),
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="b1",
            block_index=1,
            atomic_index=1,
            text="Useful kitchen note",
            within_recipe_span=False,
            label="OTHER",
            decided_by="rule",
            reason_tags=["test"],
        ),
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="b2",
            block_index=2,
            atomic_index=2,
            text="1 cup stock",
            within_recipe_span=True,
            label="INGREDIENT_LINE",
            decided_by="rule",
            reason_tags=["test"],
        ),
    ]

    baseline_artifacts = write_line_role_projection_artifacts(
        run_root=tmp_path / "baseline",
        source_file="book.epub",
        source_hash="hash-123",
        workbook_slug="book",
        predictions=predictions,
    )
    baseline_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=baseline_artifacts["stage_block_predictions_path"],
        extracted_blocks_json=baseline_artifacts["extracted_archive_path"],
        out_dir=tmp_path / "baseline-eval",
        canonical_paths={
            "canonical_text_path": gold_export_root / "canonical_text.txt",
            "canonical_span_labels_path": gold_export_root / "canonical_span_labels.jsonl",
            "canonical_manifest_path": gold_export_root / "canonical_manifest.json",
        },
    )
    assert baseline_result["report"]["overall_line_accuracy"] == pytest.approx(2 / 3)
    assert baseline_result["report"]["per_label"]["KNOWLEDGE"]["tp"] == 0

    repeated_artifacts = write_line_role_projection_artifacts(
        run_root=tmp_path / "repeated",
        source_file="book.epub",
        source_hash="hash-123",
        workbook_slug="book",
        predictions=predictions,
    )
    repeated_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=repeated_artifacts["stage_block_predictions_path"],
        extracted_blocks_json=repeated_artifacts["extracted_archive_path"],
        out_dir=tmp_path / "repeated-eval",
        canonical_paths={
            "canonical_text_path": gold_export_root / "canonical_text.txt",
            "canonical_span_labels_path": gold_export_root / "canonical_span_labels.jsonl",
            "canonical_manifest_path": gold_export_root / "canonical_manifest.json",
        },
    )

    assert repeated_result["report"]["overall_line_accuracy"] == pytest.approx(2 / 3)
    assert repeated_result["report"]["per_label"]["KNOWLEDGE"]["tp"] == 0


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

    assert metrics["strict_accuracy"] == pytest.approx(0.75)
    assert metrics["overall_block_accuracy"] == pytest.approx(0.75)
    assert metrics["macro_f1_excluding_other"] == pytest.approx(2 / 3)
    assert "precision" not in metrics
    assert "recall" not in metrics
    assert "f1" not in metrics
    assert "practical_f1" not in metrics
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
    segmentation = report.get("segmentation")
    assert isinstance(segmentation, dict)
    assert segmentation["label_projection"] == "core_structural_v1"
    assert segmentation["boundary_tolerance_blocks"] == 0
    assert segmentation["boundaries"]["overall_micro"]["tp"] == 2
    assert segmentation["boundaries"]["overall_micro"]["fn"] == 2
    assert segmentation["error_taxonomy"]["bucket_counts"]["ingredient_errors"] == 1
    assert segmentation["error_taxonomy"]["bucket_counts"]["boundary_errors"] == 2
    telemetry = report.get("evaluation_telemetry")
    assert isinstance(telemetry, dict)
    assert telemetry["total_seconds"] >= 0.0
    assert telemetry["subphases"]["load_gold_seconds"] >= 0.0
    assert telemetry["subphases"]["load_prediction_seconds"] >= 0.0
    assert telemetry["work_units"]["prediction_block_count"] == pytest.approx(4.0)
    assert telemetry["work_units"]["segmentation_false_positive_boundary_count"] == pytest.approx(0.0)
    assert telemetry["work_units"]["segmentation_missed_boundary_count"] == pytest.approx(2.0)

    assert (out_dir / "eval_report.json").exists()
    assert (out_dir / "eval_report.md").exists()
    assert (out_dir / "missed_gold_blocks.jsonl").exists()
    assert (out_dir / "wrong_label_blocks.jsonl").exists()
    assert (out_dir / "missed_gold_boundaries.jsonl").exists()
    assert (out_dir / "false_positive_boundaries.jsonl").exists()

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

    missed_boundary_rows = [
        json.loads(line)
        for line in (out_dir / "missed_gold_boundaries.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(missed_boundary_rows) == 2


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


def test_evaluate_stage_blocks_fails_on_severe_blockization_mismatch(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {
                "span_id": f"s{index}",
                "label": "OTHER",
                "touched_block_indices": [index],
                "touched_blocks": [
                    {
                        "block_index": index,
                        "location": {
                            "features": {
                                "extraction_backend": "unstructured",
                                "unstructured_html_parser_version": "v1",
                                "unstructured_preprocess_mode": "br_split_v1",
                                "unstructured_skip_headers_footers": False,
                            }
                        },
                    }
                ],
            }
            for index in range(50)
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
                "block_count": 200,
                "block_labels": {str(index): "OTHER" for index in range(200)},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {
                    "index": index,
                    "text": f"block {index}",
                    "location": {
                        "features": {
                            "extraction_backend": "beautifulsoup",
                        }
                    },
                }
                for index in range(200)
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "eval"
    with pytest.raises(ValueError, match="blockization mismatch"):
        evaluate_stage_blocks(
            gold_freeform_jsonl=gold_path,
            stage_predictions_json=stage_path,
            extracted_blocks_json=extracted_archive_path,
            out_dir=out_dir,
        )

    diagnostics = [
        json.loads(line)
        for line in (out_dir / "gold_conflicts.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(
        row.get("error") == "gold_prediction_blockization_mismatch"
        for row in diagnostics
        if isinstance(row, dict)
    )


def test_evaluate_stage_blocks_warns_on_nonfatal_blockization_mismatch(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {
                "span_id": "s0",
                "label": "RECIPE_TITLE",
                "touched_block_indices": [0],
                "touched_blocks": [
                    {
                        "block_index": 0,
                        "location": {
                            "features": {
                                "extraction_backend": "unstructured",
                            }
                        },
                    }
                ],
            },
            {
                "span_id": "s1",
                "label": "OTHER",
                "touched_block_indices": [1],
                "touched_blocks": [
                    {
                        "block_index": 1,
                        "location": {
                            "features": {
                                "extraction_backend": "unstructured",
                            }
                        },
                    }
                ],
            },
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
                "block_labels": {"0": "RECIPE_TITLE", "1": "OTHER"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {
                    "index": 0,
                    "text": "title",
                    "location": {"features": {"extraction_backend": "beautifulsoup"}},
                },
                {
                    "index": 1,
                    "text": "body",
                    "location": {"features": {"extraction_backend": "beautifulsoup"}},
                },
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
    diagnostics = report.get("diagnostics") or {}
    assert diagnostics["blockization"][0]["warning"] == "gold_prediction_blockization_mismatch"


def test_evaluate_stage_blocks_auto_applies_gold_adaptation(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {
                "span_id": "s0",
                "label": "RECIPE_TITLE",
                "selected_text": "Simple Soup",
                "touched_block_indices": [0],
                "touched_blocks": [
                    {
                        "block_index": 0,
                        "location": {
                            "features": {
                                "extraction_backend": "unstructured",
                                "unstructured_stable_key": "urn:block:s0",
                                "spine_index": 0,
                            }
                        },
                    }
                ],
            },
            {
                "span_id": "s1",
                "label": "INGREDIENT_LINE",
                "selected_text": "1 cup stock",
                "touched_block_indices": [1],
                "touched_blocks": [
                    {
                        "block_index": 1,
                        "location": {
                            "features": {
                                "extraction_backend": "unstructured",
                                "unstructured_stable_key": "urn:block:s1",
                                "spine_index": 0,
                            }
                        },
                    }
                ],
            },
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
                "block_labels": {"0": "RECIPE_TITLE", "1": "INGREDIENT_LINE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {
                    "index": 0,
                    "text": "Simple Soup",
                    "location": {
                        "features": {
                            "extraction_backend": "beautifulsoup",
                            "unstructured_stable_key": "urn:block:s0",
                            "spine_index": 0,
                        }
                    },
                },
                {
                    "index": 1,
                    "text": "1 cup stock",
                    "location": {
                        "features": {
                            "extraction_backend": "beautifulsoup",
                            "unstructured_stable_key": "urn:block:s1",
                            "spine_index": 0,
                        }
                    },
                },
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
        gold_adaptation_mode="auto",
    )

    assert result["report"]["overall_block_accuracy"] == pytest.approx(1.0)
    adaptation = result["report"]["diagnostics"]["gold_adaptation"]
    assert adaptation["mode"] == "auto"
    assert adaptation["coverage_ratio"] == pytest.approx(1.0)
    assert (out_dir / "gold_adaptation_diagnostics.json").exists()
    conflict_rows = [
        json.loads(line)
        for line in (out_dir / "gold_conflicts.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(row.get("warning") == "gold_adaptation_applied" for row in conflict_rows)


def test_evaluate_stage_blocks_force_gold_adaptation_without_mismatch(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {
                "span_id": "s0",
                "label": "RECIPE_TITLE",
                "selected_text": "Simple Soup",
                "touched_block_indices": [0],
                "touched_blocks": [
                    {
                        "block_index": 0,
                        "location": {
                            "features": {
                                "extraction_backend": "unstructured",
                                "unstructured_stable_key": "urn:block:s0",
                                "spine_index": 0,
                            }
                        },
                    }
                ],
            }
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
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {
                    "index": 0,
                    "text": "Simple Soup",
                    "location": {
                        "features": {
                            "extraction_backend": "unstructured",
                            "unstructured_stable_key": "urn:block:s0",
                            "spine_index": 0,
                        }
                    },
                }
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
        gold_adaptation_mode="force",
    )

    assert result["report"]["overall_block_accuracy"] == pytest.approx(1.0)
    adaptation = result["report"]["diagnostics"]["gold_adaptation"]
    assert adaptation["mode"] == "force"
    assert adaptation["coverage_ratio"] == pytest.approx(1.0)


def test_evaluate_stage_blocks_gold_adaptation_threshold_failure(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {
                "span_id": "s99",
                "label": "RECIPE_TITLE",
                "selected_text": "Unmapped block",
                "touched_block_indices": [99],
            }
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
                "block_count": 1,
                "block_labels": {"0": "RECIPE_TITLE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [{"index": 0, "text": "Simple Soup"}],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Adaptive gold remap thresholds failed"):
        evaluate_stage_blocks(
            gold_freeform_jsonl=gold_path,
            stage_predictions_json=stage_path,
            extracted_blocks_json=extracted_archive_path,
            out_dir=tmp_path / "eval",
            gold_adaptation_mode="force",
            gold_adaptation_min_coverage=1.0,
            gold_adaptation_max_ambiguous=0,
        )


def test_evaluate_stage_blocks_boundary_tolerance_affects_segmentation_metrics(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "touched_block_indices": [0]},
            {"span_id": "s1", "label": "INGREDIENT_LINE", "touched_block_indices": [1]},
            {"span_id": "s2", "label": "OTHER", "touched_block_indices": [2]},
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
                    "0": "RECIPE_TITLE",
                    "1": "OTHER",
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
                {"index": 0, "text": "Simple Soup"},
                {"index": 1, "text": "1 cup stock"},
                {"index": 2, "text": "Optional garnish"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    strict_result = evaluate_stage_blocks(
        gold_freeform_jsonl=gold_path,
        stage_predictions_json=stage_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "eval-strict",
        boundary_tolerance_blocks=0,
    )
    tolerant_result = evaluate_stage_blocks(
        gold_freeform_jsonl=gold_path,
        stage_predictions_json=stage_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "eval-tolerant",
        boundary_tolerance_blocks=1,
    )

    strict_boundaries = strict_result["report"]["segmentation"]["boundaries"]
    tolerant_boundaries = tolerant_result["report"]["segmentation"]["boundaries"]

    assert strict_boundaries["ingredient_start"]["tp"] == 0
    assert strict_boundaries["ingredient_start"]["fp"] == 1
    assert strict_boundaries["ingredient_start"]["fn"] == 1
    assert tolerant_boundaries["ingredient_start"]["tp"] == 1
    assert tolerant_boundaries["ingredient_start"]["fp"] == 0
    assert tolerant_boundaries["ingredient_start"]["fn"] == 0
    assert strict_boundaries["overall_micro"]["f1"] == pytest.approx(0.0)
    assert tolerant_boundaries["overall_micro"]["f1"] == pytest.approx(1.0)


def test_evaluate_stage_blocks_optional_segeval_metrics_require_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import cookimport.bench.segeval_adapter as segeval_adapter

    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "touched_block_indices": [0]},
            {"span_id": "s1", "label": "OTHER", "touched_block_indices": [1]},
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
                "block_labels": {"0": "RECIPE_TITLE", "1": "OTHER"},
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
                {"index": 1, "text": "Page footer"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    def _raise_missing_dependency(_module_name: str):
        raise ModuleNotFoundError("No module named 'segeval'")

    monkeypatch.setattr(segeval_adapter.importlib, "import_module", _raise_missing_dependency)

    with pytest.raises(ValueError, match="Install optional segmentation metrics dependency"):
        evaluate_stage_blocks(
            gold_freeform_jsonl=gold_path,
            stage_predictions_json=stage_path,
            extracted_blocks_json=extracted_archive_path,
            out_dir=tmp_path / "eval",
            segmentation_metrics="boundary_f1,pk",
        )


def test_evaluate_canonical_text_scores_lines_across_different_blockization(
    tmp_path: Path,
) -> None:
    gold_export_root = tmp_path / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    canonical_text = "Title\nSubtitle\n1 cup stock"
    (gold_export_root / "canonical_text.txt").write_text(
        canonical_text,
        encoding="utf-8",
    )
    _write_jsonl(
        gold_export_root / "canonical_block_map.jsonl",
        [
            {"block_index": 0, "start_char": 0, "end_char": 5},
            {"block_index": 1, "start_char": 6, "end_char": 14},
            {"block_index": 2, "start_char": 15, "end_char": 26},
        ],
    )
    _write_jsonl(
        gold_export_root / "canonical_span_labels.jsonl",
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "start_char": 0, "end_char": 5},
            {"span_id": "s1", "label": "RECIPE_TITLE", "start_char": 6, "end_char": 14},
            {
                "span_id": "s2",
                "label": "INGREDIENT_LINE",
                "start_char": 15,
                "end_char": 26,
            },
        ],
    )
    (gold_export_root / "canonical_manifest.json").write_text(
        json.dumps({"schema_version": "canonical_gold.v1"}, sort_keys=True),
        encoding="utf-8",
    )

    stage_predictions_path = tmp_path / "stage_block_predictions.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "abc123",
                "block_count": 2,
                "block_labels": {"0": "RECIPE_TITLE", "1": "INGREDIENT_LINE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {"index": 0, "text": "Title\nSubtitle"},
                {"index": 1, "text": "1 cup stock"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "eval"
    result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=out_dir,
    )

    report = result["report"]
    assert report["eval_mode"] == "canonical_text"
    assert report["overall_line_accuracy"] == pytest.approx(1.0)
    assert report["macro_f1_excluding_other"] == pytest.approx(1.0)
    segmentation = report.get("segmentation")
    assert isinstance(segmentation, dict)
    assert segmentation["label_projection"] == "core_structural_v1"
    assert segmentation["boundary_tolerance_blocks"] == 0
    assert segmentation["metrics_requested"] == ["boundary_f1"]
    assert segmentation["boundaries"]["overall_micro"]["tp"] == 2
    assert segmentation["boundaries"]["overall_micro"]["fp"] == 0
    assert segmentation["boundaries"]["overall_micro"]["fn"] == 0
    assert segmentation["boundaries"]["overall_micro"]["f1"] == pytest.approx(1.0)
    assert segmentation["error_taxonomy"]["total_count"] == 0
    assert report["boundary"] == {
        "correct": 1,
        "over": 2,
        "under": 0,
        "partial": 0,
    }
    assert report["boundary_overlap_threshold"] == pytest.approx(0.5)
    telemetry = report.get("evaluation_telemetry")
    assert isinstance(telemetry, dict)
    assert telemetry["total_seconds"] >= 0.0
    assert telemetry["subphases"]["load_gold_seconds"] >= 0.0
    assert telemetry["subphases"]["load_prediction_seconds"] >= 0.0
    assert telemetry["subphases"]["alignment_seconds"] >= 0.0
    assert telemetry["alignment_sequence_matcher_impl"] == "dmp"
    assert telemetry["alignment_sequence_matcher_mode"] == "dmp"
    assert telemetry["alignment_sequence_matcher_mode"] == telemetry[
        "alignment_sequence_matcher_impl"
    ]
    assert telemetry["alignment_sequence_matcher_requested_mode"] == "dmp"
    assert telemetry["work_units"]["prediction_block_count"] == pytest.approx(2.0)
    assert telemetry["work_units"]["segmentation_gold_boundary_count"] == pytest.approx(2.0)
    assert telemetry["work_units"]["segmentation_pred_boundary_count"] == pytest.approx(2.0)
    assert telemetry["work_units"]["segmentation_false_positive_boundary_count"] == pytest.approx(0.0)
    assert telemetry["work_units"]["segmentation_missed_boundary_count"] == pytest.approx(0.0)
    assert (out_dir / "unmatched_pred_blocks.jsonl").read_text(encoding="utf-8").strip() == ""
    assert (out_dir / "missed_gold_boundaries.jsonl").exists()
    assert (out_dir / "false_positive_boundaries.jsonl").exists()
    assert (out_dir / "missed_gold_boundaries.jsonl").read_text(encoding="utf-8").strip() == ""
    assert (
        out_dir / "false_positive_boundaries.jsonl"
    ).read_text(encoding="utf-8").strip() == ""


def _write_minimal_canonical_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    gold_export_root = tmp_path / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    canonical_text = "Title\nSubtitle\n1 cup stock"
    (gold_export_root / "canonical_text.txt").write_text(
        canonical_text,
        encoding="utf-8",
    )
    _write_jsonl(
        gold_export_root / "canonical_block_map.jsonl",
        [
            {"block_index": 0, "start_char": 0, "end_char": 5},
            {"block_index": 1, "start_char": 6, "end_char": 14},
            {"block_index": 2, "start_char": 15, "end_char": 26},
        ],
    )
    _write_jsonl(
        gold_export_root / "canonical_span_labels.jsonl",
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "start_char": 0, "end_char": 5},
            {"span_id": "s1", "label": "RECIPE_TITLE", "start_char": 6, "end_char": 14},
            {
                "span_id": "s2",
                "label": "INGREDIENT_LINE",
                "start_char": 15,
                "end_char": 26,
            },
        ],
    )
    (gold_export_root / "canonical_manifest.json").write_text(
        json.dumps({"schema_version": "canonical_gold.v1"}, sort_keys=True),
        encoding="utf-8",
    )

    stage_predictions_path = tmp_path / "stage_block_predictions.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "abc123",
                "block_count": 2,
                "block_labels": {"0": "RECIPE_TITLE", "1": "INGREDIENT_LINE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {"index": 0, "text": "Title\nSubtitle"},
                {"index": 1, "text": "1 cup stock"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return gold_export_root, stage_predictions_path, extracted_archive_path


def test_evaluate_canonical_text_omits_legacy_alias_artifacts(tmp_path: Path) -> None:
    gold_export_root, stage_predictions_path, extracted_archive_path = _write_minimal_canonical_fixture(
        tmp_path
    )
    out_dir = tmp_path / "eval"

    result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=out_dir,
    )

    assert "missed_gold" not in result
    assert "false_positive_preds" not in result
    assert (out_dir / "missed_gold_lines.jsonl").exists()
    assert (out_dir / "wrong_label_lines.jsonl").exists()
    assert (out_dir / "missed_gold_blocks.jsonl").exists()
    assert (out_dir / "wrong_label_blocks.jsonl").exists()
    assert not (out_dir / "missed_gold_spans.jsonl").exists()
    assert not (out_dir / "false_positive_preds.jsonl").exists()


def test_evaluate_canonical_text_auto_matches_global_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gold_export_root, stage_predictions_path, extracted_archive_path = _write_minimal_canonical_fixture(
        tmp_path
    )
    monkeypatch.setenv(canonical_eval._ALIGNMENT_STRATEGY_ENV, "global")
    global_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "global",
    )

    monkeypatch.setenv(canonical_eval._ALIGNMENT_STRATEGY_ENV, "auto")
    auto_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "auto",
    )

    global_report = global_result["report"]
    auto_report = auto_result["report"]
    assert global_report["overall_line_accuracy"] == pytest.approx(
        auto_report["overall_line_accuracy"]
    )
    assert global_report["macro_f1_excluding_other"] == pytest.approx(
        auto_report["macro_f1_excluding_other"]
    )
    assert global_report["wrong_label_blocks"] == auto_report["wrong_label_blocks"]
    assert auto_report["alignment"]["alignment_strategy"] == "global"
    assert auto_report["alignment"]["alignment_requested_strategy"] == "auto"
    assert auto_report["alignment"]["alignment_fallback_used"] is True
    assert (
        auto_report["alignment"]["alignment_fallback_reason"]
        == canonical_eval._ALIGNMENT_FAST_DEPRECATION_REASON
    )
    assert global_report["alignment"]["alignment_strategy"] == "global"


def test_evaluate_canonical_text_fast_request_is_deprecated_and_forced_to_global(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gold_export_root, stage_predictions_path, extracted_archive_path = _write_minimal_canonical_fixture(
        tmp_path
    )
    monkeypatch.setenv(canonical_eval._ALIGNMENT_STRATEGY_ENV, "fast")

    result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "fast-disabled",
    )
    alignment = result["report"]["alignment"]
    assert alignment["alignment_strategy"] == "global"
    assert alignment["alignment_requested_strategy"] == "fast"
    assert alignment["alignment_fallback_used"] is True
    assert alignment["alignment_fallback_reason"] == canonical_eval._ALIGNMENT_FAST_DEPRECATION_REASON
    assert alignment["alignment_fast_path_deprecated"] is True
    assert "disabled due to accuracy risk" in str(
        alignment["alignment_fast_path_deprecation_message"]
    )


def _write_boundary_cache_fixture(
    tmp_path: Path,
    *,
    fixture_name: str,
    block_texts: list[str],
) -> tuple[Path, Path, Path]:
    fixture_root = tmp_path / fixture_name
    gold_export_root = fixture_root / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    canonical_text = "Title\n\nSubtitle\n\n1 cup stock"
    (gold_export_root / "canonical_text.txt").write_text(canonical_text, encoding="utf-8")
    _write_jsonl(
        gold_export_root / "canonical_block_map.jsonl",
        [
            {"block_index": 0, "start_char": 0, "end_char": 5},
            {"block_index": 1, "start_char": 7, "end_char": 15},
            {"block_index": 2, "start_char": 17, "end_char": 28},
        ],
    )
    _write_jsonl(
        gold_export_root / "canonical_span_labels.jsonl",
        [
            {"span_id": "t", "label": "OTHER", "start_char": 0, "end_char": 5},
            {"span_id": "s", "label": "OTHER", "start_char": 7, "end_char": 15},
            {"span_id": "i", "label": "OTHER", "start_char": 17, "end_char": 28},
        ],
    )
    (gold_export_root / "canonical_manifest.json").write_text(
        json.dumps({"schema_version": "canonical_gold.v1"}, sort_keys=True),
        encoding="utf-8",
    )

    block_labels = {str(index): "OTHER" for index, _text in enumerate(block_texts)}
    stage_predictions_path = fixture_root / "stage_block_predictions.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": fixture_name,
                "source_file": f"{fixture_name}.epub",
                "source_hash": fixture_name,
                "block_count": len(block_texts),
                "block_labels": block_labels,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path = fixture_root / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [{"index": index, "text": text} for index, text in enumerate(block_texts)],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return gold_export_root, stage_predictions_path, extracted_archive_path


def test_evaluate_canonical_text_alignment_cache_hits_without_metric_changes(
    tmp_path: Path,
) -> None:
    gold_export_root, stage_predictions_path, extracted_archive_path = _write_minimal_canonical_fixture(
        tmp_path
    )
    cache_dir = tmp_path / "alignment-cache"
    first_out = tmp_path / "first"
    second_out = tmp_path / "second"

    first_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=first_out,
        alignment_cache_dir=cache_dir,
    )
    second_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=second_out,
        alignment_cache_dir=cache_dir,
    )

    first_report = first_result["report"]
    second_report = second_result["report"]
    first_telemetry = first_report["evaluation_telemetry"]
    second_telemetry = second_report["evaluation_telemetry"]
    assert first_telemetry["alignment_cache_enabled"] is True
    assert first_telemetry["alignment_cache_hit"] is False
    assert second_telemetry["alignment_cache_enabled"] is True
    assert second_telemetry["alignment_cache_hit"] is True
    assert second_telemetry["alignment_cache_validation_error"] is None
    assert second_telemetry["alignment_cache_load_seconds"] >= 0.0
    assert second_telemetry["alignment_cache_write_seconds"] >= 0.0
    assert second_telemetry["subphases"]["alignment_sequence_matcher_seconds"] == pytest.approx(0.0)

    assert first_report["overall_line_accuracy"] == pytest.approx(second_report["overall_line_accuracy"])
    assert first_report["macro_f1_excluding_other"] == pytest.approx(
        second_report["macro_f1_excluding_other"]
    )
    assert first_report["wrong_label_blocks"] == second_report["wrong_label_blocks"]
    assert first_report["missed_gold_blocks"] == second_report["missed_gold_blocks"]

    for artifact_name in (
        "missed_gold_lines.jsonl",
        "wrong_label_lines.jsonl",
        "unmatched_pred_blocks.jsonl",
        "alignment_gaps.jsonl",
    ):
        assert (first_out / artifact_name).read_text(encoding="utf-8") == (
            second_out / artifact_name
        ).read_text(encoding="utf-8")


def test_evaluate_canonical_text_alignment_cache_key_includes_block_boundaries(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "alignment-cache"
    two_block_fixture = _write_boundary_cache_fixture(
        tmp_path,
        fixture_name="two-blocks",
        block_texts=["Title", "Subtitle\n\n1 cup stock"],
    )
    three_block_fixture = _write_boundary_cache_fixture(
        tmp_path,
        fixture_name="three-blocks",
        block_texts=["Title", "Subtitle", "1 cup stock"],
    )

    first_result = evaluate_canonical_text(
        gold_export_root=two_block_fixture[0],
        stage_predictions_json=two_block_fixture[1],
        extracted_blocks_json=two_block_fixture[2],
        out_dir=tmp_path / "first",
        alignment_cache_dir=cache_dir,
    )
    second_result = evaluate_canonical_text(
        gold_export_root=three_block_fixture[0],
        stage_predictions_json=three_block_fixture[1],
        extracted_blocks_json=three_block_fixture[2],
        out_dir=tmp_path / "second",
        alignment_cache_dir=cache_dir,
    )

    first_telemetry = first_result["report"]["evaluation_telemetry"]
    second_telemetry = second_result["report"]["evaluation_telemetry"]
    assert first_telemetry["alignment_cache_enabled"] is True
    assert second_telemetry["alignment_cache_enabled"] is True
    assert first_telemetry["alignment_cache_hit"] is False
    assert second_telemetry["alignment_cache_hit"] is False
    assert first_telemetry["alignment_cache_key"] != second_telemetry["alignment_cache_key"]


def test_evaluate_canonical_text_alignment_cache_recovers_from_stale_lock(
    tmp_path: Path,
) -> None:
    gold_export_root, stage_predictions_path, extracted_archive_path = _write_minimal_canonical_fixture(
        tmp_path
    )
    cache_dir = tmp_path / "alignment-cache"

    evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "first",
        alignment_cache_dir=cache_dir,
    )

    cache_files = sorted(cache_dir.glob("**/*.json"))
    assert len(cache_files) == 1
    cache_file = cache_files[0]
    lock_path = cache_file.with_suffix(".lock")

    cache_file.unlink()
    lock_path.write_text("stale lock\n", encoding="utf-8")
    stale_ts = time.time() - 7200.0
    os.utime(lock_path, (stale_ts, stale_ts))

    result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "second",
        alignment_cache_dir=cache_dir,
    )

    telemetry = result["report"]["evaluation_telemetry"]
    assert telemetry["alignment_cache_enabled"] is True
    assert telemetry["alignment_cache_hit"] is False
    assert telemetry["alignment_cache_validation_error"] is None
    assert cache_file.exists()
    assert not lock_path.exists()


def test_evaluate_canonical_text_alignment_cache_recovers_from_corrupt_entry(
    tmp_path: Path,
) -> None:
    gold_export_root, stage_predictions_path, extracted_archive_path = _write_minimal_canonical_fixture(
        tmp_path
    )
    cache_dir = tmp_path / "alignment-cache"

    first_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "first",
        alignment_cache_dir=cache_dir,
    )

    cache_files = sorted(cache_dir.glob("**/*.json"))
    assert len(cache_files) == 1
    cache_file = cache_files[0]
    cache_file.write_text("{not-json", encoding="utf-8")

    second_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "second",
        alignment_cache_dir=cache_dir,
    )

    telemetry = second_result["report"]["evaluation_telemetry"]
    assert telemetry["alignment_cache_enabled"] is True
    assert telemetry["alignment_cache_hit"] is False
    assert str(telemetry["alignment_cache_validation_error"]).startswith("cache_read_error:")
    assert cache_file.exists()

    quarantined = list(cache_file.parent.glob(f"{cache_file.stem}.corrupt.decode.*.json"))
    assert quarantined

    first_report = first_result["report"]
    second_report = second_result["report"]
    assert first_report["overall_line_accuracy"] == pytest.approx(second_report["overall_line_accuracy"])
    assert first_report["macro_f1_excluding_other"] == pytest.approx(
        second_report["macro_f1_excluding_other"]
    )
