from __future__ import annotations

import json
from pathlib import Path

import pytest

import cookimport.bench.line_label_projection as canonical_eval
from cookimport.bench.eval_stage_blocks import (
    compute_block_metrics,
    evaluate_stage_blocks,
    load_gold_block_labels,
    load_stage_block_prediction_manifest,
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


def test_build_gold_line_labels_preserves_inline_recipe_title_subspan_inside_other_line() -> None:
    text = (
        "Make Pasta alle Vongole to practice layering acids. "
        "Heat a pan and continue cooking."
    )
    lines = canonical_eval._build_canonical_lines(text)
    title_start = text.index("Pasta alle Vongole")
    title_end = title_start + len("Pasta alle Vongole")
    gold_spans = [
        {
            "span_id": "s0",
            "label": "OTHER",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "RECIPE_TITLE",
            "start_char": title_start,
            "end_char": title_end,
        },
    ]

    labels = canonical_eval._build_gold_line_labels(
        lines=lines,
        gold_spans=gold_spans,
        strict_empty_to_other=True,
    )

    assert labels[0] == {"OTHER", "RECIPE_TITLE"}


def test_build_gold_projection_warnings_flags_inline_recipe_title_subspan_inside_other_line() -> None:
    text = (
        "Make Pasta alle Vongole to practice layering acids. "
        "Heat a pan and continue cooking."
    )
    lines = canonical_eval._build_canonical_lines(text)
    title_start = text.index("Pasta alle Vongole")
    title_end = title_start + len("Pasta alle Vongole")
    gold_spans = [
        {
            "span_id": "s0",
            "label": "OTHER",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "RECIPE_TITLE",
            "start_char": title_start,
            "end_char": title_end,
        },
    ]

    warnings = canonical_eval._build_gold_projection_warnings(
        lines=lines,
        gold_spans=gold_spans,
    )

    assert any(
        row["warning"] == "gold_inline_label_subspan_inside_other_line"
        and row["label"] == "RECIPE_TITLE"
        for row in warnings
    )


def test_build_gold_line_labels_preserves_unsupported_contents_recipe_titles() -> None:
    lines = canonical_eval._build_canonical_lines(
        "Bright Cabbage Slaw\nScented Cream\nSuggested Menus\nFOREWORD"
    )
    gold_spans = [
        {
            "span_id": "s0",
            "label": "RECIPE_TITLE",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "RECIPE_TITLE",
            "start_char": lines[1]["start_char"],
            "end_char": lines[1]["end_char"],
        },
        {
            "span_id": "s2",
            "label": "OTHER",
            "start_char": lines[3]["start_char"],
            "end_char": lines[3]["end_char"],
        },
    ]

    labels = canonical_eval._build_gold_line_labels(
        lines=lines,
        gold_spans=gold_spans,
        strict_empty_to_other=True,
    )

    assert labels[0] == {"RECIPE_TITLE"}
    assert labels[1] == {"RECIPE_TITLE"}


def test_build_gold_projection_warnings_flags_unsupported_contents_recipe_titles() -> None:
    lines = canonical_eval._build_canonical_lines(
        "Bright Cabbage Slaw\nScented Cream\nSuggested Menus\nFOREWORD"
    )
    gold_spans = [
        {
            "span_id": "s0",
            "label": "RECIPE_TITLE",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "RECIPE_TITLE",
            "start_char": lines[1]["start_char"],
            "end_char": lines[1]["end_char"],
        },
        {
            "span_id": "s2",
            "label": "OTHER",
            "start_char": lines[3]["start_char"],
            "end_char": lines[3]["end_char"],
        },
    ]

    warnings = canonical_eval._build_gold_projection_warnings(
        lines=lines,
        gold_spans=gold_spans,
    )

    assert any(
        row["warning"] == "gold_recipe_title_precedes_later_recipe_title_before_structure"
        and row["line_index"] == 0
        for row in warnings
    )
    assert any(
        row["warning"] == "gold_recipe_title_without_nearby_recipe_structure"
        and row["line_index"] == 1
        for row in warnings
    )


def test_build_gold_line_labels_keeps_supported_recipe_titles() -> None:
    lines = canonical_eval._build_canonical_lines("Bright Cabbage Slaw\nServes 4\n1 cup stock")
    gold_spans = [
        {
            "span_id": "s0",
            "label": "RECIPE_TITLE",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "YIELD_LINE",
            "start_char": lines[1]["start_char"],
            "end_char": lines[1]["end_char"],
        },
        {
            "span_id": "s2",
            "label": "INGREDIENT_LINE",
            "start_char": lines[2]["start_char"],
            "end_char": lines[2]["end_char"],
        },
    ]

    labels = canonical_eval._build_gold_line_labels(
        lines=lines,
        gold_spans=gold_spans,
        strict_empty_to_other=True,
    )

    assert labels[0] == {"RECIPE_TITLE"}


def test_build_gold_line_labels_preserves_section_heading_before_real_recipe_title() -> None:
    lines = canonical_eval._build_canonical_lines(
        "A Panzanella for Every Season\n"
        "Panzanella notes.\n"
        "Summer: Tomato, Basil, and Cucumber\n"
        "Serves 4 generously\n"
        "1 cup stock"
    )
    gold_spans = [
        {
            "span_id": "s0",
            "label": "OTHER",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "RECIPE_TITLE",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s2",
            "label": "OTHER",
            "start_char": lines[1]["start_char"],
            "end_char": lines[1]["end_char"],
        },
        {
            "span_id": "s3",
            "label": "RECIPE_TITLE",
            "start_char": lines[2]["start_char"],
            "end_char": lines[2]["end_char"],
        },
        {
            "span_id": "s4",
            "label": "YIELD_LINE",
            "start_char": lines[3]["start_char"],
            "end_char": lines[3]["end_char"],
        },
        {
            "span_id": "s5",
            "label": "INGREDIENT_LINE",
            "start_char": lines[4]["start_char"],
            "end_char": lines[4]["end_char"],
        },
    ]

    labels = canonical_eval._build_gold_line_labels(
        lines=lines,
        gold_spans=gold_spans,
        strict_empty_to_other=True,
    )

    assert labels[0] == {"OTHER", "RECIPE_TITLE"}
    assert labels[2] == {"RECIPE_TITLE"}


def test_build_gold_projection_warnings_flags_section_heading_before_real_recipe_title() -> None:
    lines = canonical_eval._build_canonical_lines(
        "A Panzanella for Every Season\n"
        "Panzanella notes.\n"
        "Summer: Tomato, Basil, and Cucumber\n"
        "Serves 4 generously\n"
        "1 cup stock"
    )
    gold_spans = [
        {
            "span_id": "s0",
            "label": "OTHER",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "RECIPE_TITLE",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s2",
            "label": "OTHER",
            "start_char": lines[1]["start_char"],
            "end_char": lines[1]["end_char"],
        },
        {
            "span_id": "s3",
            "label": "RECIPE_TITLE",
            "start_char": lines[2]["start_char"],
            "end_char": lines[2]["end_char"],
        },
        {
            "span_id": "s4",
            "label": "YIELD_LINE",
            "start_char": lines[3]["start_char"],
            "end_char": lines[3]["end_char"],
        },
        {
            "span_id": "s5",
            "label": "INGREDIENT_LINE",
            "start_char": lines[4]["start_char"],
            "end_char": lines[4]["end_char"],
        },
    ]

    warnings = canonical_eval._build_gold_projection_warnings(
        lines=lines,
        gold_spans=gold_spans,
    )

    assert any(
        row["warning"] == "gold_recipe_title_precedes_later_recipe_title_before_structure"
        and row["line_index"] == 0
        and row["later_title_line_index"] == 2
        for row in warnings
    )


def test_build_gold_line_labels_keeps_recipe_variant_lines_without_title_support() -> None:
    lines = canonical_eval._build_canonical_lines(
        "Variations\n"
        "To make Classic Torn Croutons, add garlic and oregano.\n"
        "To make Cheesy Torn Croutons, add Parmesan and pepper."
    )
    gold_spans = [
        {
            "span_id": "s0",
            "label": "RECIPE_VARIANT",
            "start_char": lines[0]["start_char"],
            "end_char": lines[0]["end_char"],
        },
        {
            "span_id": "s1",
            "label": "RECIPE_VARIANT",
            "start_char": lines[1]["start_char"],
            "end_char": lines[1]["end_char"],
        },
        {
            "span_id": "s2",
            "label": "RECIPE_VARIANT",
            "start_char": lines[2]["start_char"],
            "end_char": lines[2]["end_char"],
        },
    ]

    labels = canonical_eval._build_gold_line_labels(
        lines=lines,
        gold_spans=gold_spans,
        strict_empty_to_other=True,
    )

    assert labels[0] == {"RECIPE_VARIANT"}
    assert labels[1] == {"RECIPE_VARIANT"}
    assert labels[2] == {"RECIPE_VARIANT"}


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


def test_load_stage_block_prediction_manifest_preserves_unresolved_metadata(
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
                "block_count": 2,
                "block_labels": {
                    "0": "RECIPE_TITLE",
                    "1": "OTHER",
                },
                "unresolved_candidate_block_indices": [1],
                "unresolved_candidate_route_by_index": {"1": "candidate"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    manifest = load_stage_block_prediction_manifest(stage_path)

    assert manifest.labels == {0: "RECIPE_TITLE", 1: "OTHER"}
    assert manifest.unresolved_block_indices == [1]
    assert manifest.unresolved_block_category_by_index == {1: "candidate"}
    assert manifest.unresolved_recipe_owned_block_indices == []
    assert manifest.unresolved_recipe_owned_recipe_id_by_index == {}


def test_load_stage_block_prediction_manifest_preserves_unresolved_recipe_owned_metadata(
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
                "block_count": 2,
                "block_labels": {
                    "0": "OTHER",
                    "1": "RECIPE_TITLE",
                },
                "unresolved_recipe_owned_block_indices": [0],
                "unresolved_recipe_owned_recipe_id_by_index": {"0": "urn:recipe:test:fragmentary"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    manifest = load_stage_block_prediction_manifest(stage_path)

    assert manifest.unresolved_recipe_owned_block_indices == [0]
    assert manifest.unresolved_recipe_owned_recipe_id_by_index == {
        0: "urn:recipe:test:fragmentary"
    }


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


def test_evaluate_stage_blocks_excludes_unresolved_predictions_from_semantic_scoring(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "touched_block_indices": [0]},
            {"span_id": "s1", "label": "INGREDIENT_LINE", "touched_block_indices": [1]},
            {"span_id": "s2", "label": "KNOWLEDGE", "touched_block_indices": [2]},
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
                    "1": "INGREDIENT_LINE",
                    "2": "OTHER",
                },
                "unresolved_candidate_block_indices": [2],
                "unresolved_candidate_route_by_index": {"2": "candidate"},
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
                {"index": 2, "text": "Useful kitchen note"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    report = evaluate_stage_blocks(
        gold_freeform_jsonl=gold_path,
        stage_predictions_json=stage_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "eval",
    )["report"]

    assert report["overall_block_accuracy"] == pytest.approx(1.0)
    assert report["counts"]["gold_total"] == 2
    assert report["authority_coverage"]["scored_prediction_blocks"] == 2
    assert report["authority_coverage"]["total_prediction_blocks"] == 3
    assert report["authority_coverage"]["unresolved_candidate_blocks"] == 1
    assert report["authority_coverage"]["prediction_coverage"] == pytest.approx(2 / 3)
    assert report["authority_coverage"]["unresolved_candidate_block_indices"] == [2]
    assert report["authority_coverage"]["unresolved_candidate_route_by_index"] == {
        2: "candidate"
    }


def test_evaluate_stage_blocks_excludes_unresolved_recipe_owned_predictions_from_semantic_scoring(
    tmp_path: Path,
) -> None:
    gold_path = tmp_path / "freeform_span_labels.jsonl"
    _write_jsonl(
        gold_path,
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "touched_block_indices": [0]},
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
                    "1": "INGREDIENT_LINE",
                },
                "unresolved_recipe_owned_block_indices": [0],
                "unresolved_recipe_owned_recipe_id_by_index": {
                    "0": "urn:recipe:test:fragmentary"
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

    report = evaluate_stage_blocks(
        gold_freeform_jsonl=gold_path,
        stage_predictions_json=stage_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "eval",
    )["report"]

    assert report["overall_block_accuracy"] == pytest.approx(1.0)
    assert report["counts"]["gold_total"] == 1
    assert report["authority_coverage"]["scored_prediction_blocks"] == 1
    assert report["authority_coverage"]["total_prediction_blocks"] == 2
    assert report["authority_coverage"]["unresolved_recipe_owned_blocks"] == 1
    assert report["authority_coverage"]["unresolved_recipe_owned_block_indices"] == [0]
    assert report["authority_coverage"]["unresolved_recipe_owned_recipe_id_by_index"] == {
        0: "urn:recipe:test:fragmentary"
    }


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

