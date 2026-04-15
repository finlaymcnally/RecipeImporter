from __future__ import annotations

import json
from pathlib import Path

from cookimport.bench.eval_source_rows import evaluate_source_rows


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_evaluate_source_rows_falls_back_to_row_index_when_row_ids_drift(tmp_path: Path) -> None:
    gold_export_root = tmp_path / "gold"
    _write_jsonl(
        gold_export_root / "row_gold_labels.jsonl",
        [
            {"row_id": "gold:r0", "row_index": 0, "labels": ["RECIPE_TITLE"], "text": "Bright Slaw"},
            {"row_id": "gold:r1", "row_index": 1, "labels": ["INGREDIENT_LINE"], "text": "1 cabbage"},
        ],
    )

    eval_root = tmp_path / "eval"
    line_role_dir = eval_root / "line-role-pipeline"
    stage_predictions_json = line_role_dir / "semantic_row_predictions.json"
    _write_json(stage_predictions_json, {"stage": "fixture"})
    _write_jsonl(
        line_role_dir / "row_label_predictions.jsonl",
        [
            {
                "row_id": "pred:r0",
                "atomic_index": 0,
                "block_index": 10,
                "label": "RECIPE_TITLE",
                "text": "Bright Slaw",
            },
            {
                "row_id": "pred:r1",
                "atomic_index": 1,
                "block_index": 11,
                "label": "INGREDIENT_LINE",
                "text": "1 cabbage",
            },
        ],
    )

    result = evaluate_source_rows(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_json,
        extracted_blocks_json=tmp_path / "unused.json",
        out_dir=eval_root / "source-rows-eval",
    )

    report = result["report"]
    assert report["overall_line_accuracy"] == 1.0
    assert report["counts"]["direct_row_id_match_rows"] == 0
    assert report["counts"]["row_index_fallback_match_rows"] == 2


def test_evaluate_source_rows_prefers_row_index_when_row_id_collides_with_wrong_text(
    tmp_path: Path,
) -> None:
    gold_export_root = tmp_path / "gold"
    _write_jsonl(
        gold_export_root / "row_gold_labels.jsonl",
        [
            {
                "row_id": "gold:stale",
                "row_index": 0,
                "labels": ["OTHER"],
                "text": "Think about making a grilled cheese sandwich.",
            },
            {
                "row_id": "gold:r1",
                "row_index": 1,
                "labels": ["KNOWLEDGE"],
                "text": "Olive oil is produced seasonally.",
            },
        ],
    )

    eval_root = tmp_path / "eval"
    line_role_dir = eval_root / "line-role-pipeline"
    stage_predictions_json = line_role_dir / "semantic_row_predictions.json"
    _write_json(stage_predictions_json, {"stage": "fixture"})
    _write_jsonl(
        line_role_dir / "row_label_predictions.jsonl",
        [
            {
                "row_id": "gold:stale",
                "atomic_index": 1,
                "block_index": 728,
                "label": "KNOWLEDGE",
                "text": "Olive oil is produced seasonally.",
            },
            {
                "row_id": "pred:new",
                "atomic_index": 0,
                "block_index": 1692,
                "label": "OTHER",
                "reason_tags": ["nonrecipe_authority:preserved_exclude"],
                "text": "Think about making a grilled cheese sandwich.",
            },
        ],
    )

    result = evaluate_source_rows(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_json,
        extracted_blocks_json=tmp_path / "unused.json",
        out_dir=eval_root / "source-rows-eval",
    )

    report = result["report"]
    assert report["overall_line_accuracy"] == 1.0
    assert report["counts"]["direct_row_id_match_rows"] == 0
    assert report["counts"]["row_index_fallback_match_rows"] == 2
    assert report["counts"]["row_identity_conflict_rows"] == 1
    aligned_rows = [
        json.loads(line)
        for line in (
            eval_root / "source-rows-eval" / "aligned_prediction_blocks.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert aligned_rows[0]["line_text"] == "Think about making a grilled cheese sandwich."
    assert aligned_rows[0]["pred_label"] == "OTHER"
    assert aligned_rows[1]["line_text"] == "Olive oil is produced seasonally."
    assert aligned_rows[1]["pred_label"] == "KNOWLEDGE"


def test_evaluate_source_rows_overlays_nonrecipe_authority_labels(tmp_path: Path) -> None:
    gold_export_root = tmp_path / "gold"
    _write_jsonl(
        gold_export_root / "row_gold_labels.jsonl",
        [
            {
                "row_id": "gold:r0",
                "row_index": 0,
                "block_index": 999,
                "labels": ["KNOWLEDGE"],
                "text": "Salt dissolves quickly.",
            }
        ],
    )

    eval_root = tmp_path / "eval"
    processed_output_root = tmp_path / "processed"
    line_role_dir = eval_root / "line-role-pipeline"
    stage_predictions_json = line_role_dir / "semantic_row_predictions.json"
    _write_json(stage_predictions_json, {"stage": "fixture"})
    _write_jsonl(
        line_role_dir / "row_label_predictions.jsonl",
        [
            {
                "row_id": "gold:r0",
                "atomic_index": 0,
                "block_index": 999,
                "label": "NONRECIPE_CANDIDATE",
                "text": "Salt dissolves quickly.",
            }
        ],
    )
    _write_json(
        eval_root / "run_manifest.json",
        {"artifacts": {"processed_output_run_dir": str(processed_output_root)}},
    )
    _write_json(
        processed_output_root / "09_nonrecipe_authority.json",
        {"authoritative_block_category_by_index": {"999": "knowledge"}},
    )

    result = evaluate_source_rows(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_json,
        extracted_blocks_json=tmp_path / "unused.json",
        out_dir=eval_root / "source-rows-eval",
    )

    report = result["report"]
    assert report["overall_line_accuracy"] == 1.0
    assert report["counts"]["authority_override_rows"] == 1
    assert report["artifacts"]["nonrecipe_authority_path"] == str(
        processed_output_root / "09_nonrecipe_authority.json"
    )


def test_evaluate_source_rows_accepts_multi_label_gold_rows(tmp_path: Path) -> None:
    gold_export_root = tmp_path / "gold"
    _write_jsonl(
        gold_export_root / "row_gold_labels.jsonl",
        [
            {
                "row_id": "gold:r0",
                "row_index": 0,
                "block_index": 275,
                "labels": ["KNOWLEDGE", "OTHER"],
                "text": "SALT AND FLAVOR",
            }
        ],
    )

    eval_root = tmp_path / "eval"
    line_role_dir = eval_root / "line-role-pipeline"
    stage_predictions_json = line_role_dir / "semantic_row_predictions.json"
    _write_json(stage_predictions_json, {"stage": "fixture"})
    _write_jsonl(
        line_role_dir / "row_label_predictions.jsonl",
        [
            {
                "row_id": "gold:r0",
                "atomic_index": 0,
                "row_index": 0,
                "block_index": 275,
                "label": "OTHER",
                "text": "SALT AND FLAVOR",
            }
        ],
    )

    result = evaluate_source_rows(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_json,
        extracted_blocks_json=tmp_path / "unused.json",
        out_dir=eval_root / "source-rows-eval",
    )

    report = result["report"]
    assert report["overall_line_accuracy"] == 1.0
    assert report["counts"]["wrong_rows"] == 0


def test_evaluate_source_rows_preserves_row_level_nonrecipe_exclude_over_block_authority(
    tmp_path: Path,
) -> None:
    gold_export_root = tmp_path / "gold"
    _write_jsonl(
        gold_export_root / "row_gold_labels.jsonl",
        [
            {
                "row_id": "gold:r0",
                "row_index": 0,
                "block_index": 999,
                "labels": ["OTHER"],
                "text": "Think about making a grilled cheese sandwich.",
            }
        ],
    )

    eval_root = tmp_path / "eval"
    processed_output_root = tmp_path / "processed"
    line_role_dir = eval_root / "line-role-pipeline"
    stage_predictions_json = line_role_dir / "semantic_row_predictions.json"
    _write_json(stage_predictions_json, {"stage": "fixture"})
    _write_jsonl(
        line_role_dir / "row_label_predictions.jsonl",
        [
            {
                "row_id": "gold:r0",
                "atomic_index": 0,
                "block_index": 999,
                "label": "OTHER",
                "reason_tags": ["nonrecipe_authority:preserved_exclude"],
                "text": "Think about making a grilled cheese sandwich.",
            }
        ],
    )
    _write_json(
        eval_root / "run_manifest.json",
        {"artifacts": {"processed_output_run_dir": str(processed_output_root)}},
    )
    _write_json(
        processed_output_root / "09_nonrecipe_authority.json",
        {"authoritative_block_category_by_index": {"999": "knowledge"}},
    )

    result = evaluate_source_rows(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_json,
        extracted_blocks_json=tmp_path / "unused.json",
        out_dir=eval_root / "source-rows-eval",
    )

    report = result["report"]
    assert report["overall_line_accuracy"] == 1.0
    assert report["counts"]["authority_override_rows"] == 0


def test_evaluate_source_rows_prefers_row_level_nonrecipe_authority_over_block_summary(
    tmp_path: Path,
) -> None:
    gold_export_root = tmp_path / "gold"
    _write_jsonl(
        gold_export_root / "row_gold_labels.jsonl",
        [
            {
                "row_id": "gold:r0",
                "row_index": 10,
                "block_index": 999,
                "labels": ["OTHER"],
                "text": "Think about making a grilled cheese sandwich.",
            },
            {
                "row_id": "gold:r1",
                "row_index": 11,
                "block_index": 999,
                "labels": ["KNOWLEDGE"],
                "text": "Slow, even heat melts the cheese before the bread burns.",
            },
        ],
    )

    eval_root = tmp_path / "eval"
    processed_output_root = tmp_path / "processed"
    line_role_dir = eval_root / "line-role-pipeline"
    stage_predictions_json = line_role_dir / "semantic_row_predictions.json"
    _write_json(stage_predictions_json, {"stage": "fixture"})
    _write_jsonl(
        line_role_dir / "row_label_predictions.jsonl",
        [
            {
                "row_id": "gold:r0",
                "atomic_index": 10,
                "block_index": 999,
                "label": "NONRECIPE_CANDIDATE",
                "text": "Think about making a grilled cheese sandwich.",
            },
            {
                "row_id": "gold:r1",
                "atomic_index": 11,
                "block_index": 999,
                "label": "NONRECIPE_CANDIDATE",
                "text": "Slow, even heat melts the cheese before the bread burns.",
            },
        ],
    )
    _write_json(
        eval_root / "run_manifest.json",
        {"artifacts": {"processed_output_run_dir": str(processed_output_root)}},
    )
    _write_json(
        processed_output_root / "09_nonrecipe_authority.json",
        {
            "authoritative_block_category_by_index": {"999": "knowledge"},
            "authoritative_row_category_by_index": {"10": "other", "11": "knowledge"},
        },
    )

    result = evaluate_source_rows(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_json,
        extracted_blocks_json=tmp_path / "unused.json",
        out_dir=eval_root / "source-rows-eval",
    )

    report = result["report"]
    assert report["overall_line_accuracy"] == 1.0
    assert report["counts"]["authority_override_rows"] == 2
