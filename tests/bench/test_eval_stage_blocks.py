from __future__ import annotations

import json
from pathlib import Path

import pytest

import cookimport.bench.eval_canonical_text as canonical_eval
from cookimport.bench.eval_canonical_text import evaluate_canonical_text
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
    telemetry = report.get("evaluation_telemetry")
    assert isinstance(telemetry, dict)
    assert telemetry["total_seconds"] >= 0.0
    assert telemetry["subphases"]["load_gold_seconds"] >= 0.0
    assert telemetry["subphases"]["load_prediction_seconds"] >= 0.0
    assert telemetry["work_units"]["prediction_block_count"] == pytest.approx(4.0)

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
    telemetry = report.get("evaluation_telemetry")
    assert isinstance(telemetry, dict)
    assert telemetry["total_seconds"] >= 0.0
    assert telemetry["subphases"]["load_gold_seconds"] >= 0.0
    assert telemetry["subphases"]["load_prediction_seconds"] >= 0.0
    assert telemetry["subphases"]["alignment_seconds"] >= 0.0
    assert telemetry["work_units"]["prediction_block_count"] == pytest.approx(2.0)
    assert (out_dir / "unmatched_pred_blocks.jsonl").read_text(encoding="utf-8").strip() == ""


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


def test_evaluate_canonical_text_auto_matches_legacy_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gold_export_root, stage_predictions_path, extracted_archive_path = _write_minimal_canonical_fixture(
        tmp_path
    )
    monkeypatch.setenv(canonical_eval._ALIGNMENT_STRATEGY_ENV, "legacy")
    legacy_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "legacy",
    )

    monkeypatch.setenv(canonical_eval._ALIGNMENT_STRATEGY_ENV, "auto")
    auto_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "auto",
    )

    legacy_report = legacy_result["report"]
    auto_report = auto_result["report"]
    assert legacy_report["overall_line_accuracy"] == pytest.approx(
        auto_report["overall_line_accuracy"]
    )
    assert legacy_report["macro_f1_excluding_other"] == pytest.approx(
        auto_report["macro_f1_excluding_other"]
    )
    assert legacy_report["wrong_label_blocks"] == auto_report["wrong_label_blocks"]
    assert auto_report["alignment"]["alignment_strategy"] == "legacy"
    assert auto_report["alignment"]["alignment_requested_strategy"] == "auto"
    assert auto_report["alignment"]["alignment_fallback_used"] is True
    assert (
        auto_report["alignment"]["alignment_fallback_reason"]
        == canonical_eval._ALIGNMENT_FAST_DEPRECATION_REASON
    )
    assert legacy_report["alignment"]["alignment_strategy"] == "legacy"


def test_evaluate_canonical_text_fast_request_is_deprecated_and_forced_to_legacy(
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
        out_dir=tmp_path / "fast-deprecated",
    )
    alignment = result["report"]["alignment"]
    assert alignment["alignment_strategy"] == "legacy"
    assert alignment["alignment_requested_strategy"] == "fast"
    assert alignment["alignment_fallback_used"] is True
    assert alignment["alignment_fallback_reason"] == canonical_eval._ALIGNMENT_FAST_DEPRECATION_REASON
    assert alignment["alignment_fast_path_deprecated"] is True
    assert "deprecated due to accuracy risk" in str(
        alignment["alignment_fast_path_deprecation_message"]
    )
