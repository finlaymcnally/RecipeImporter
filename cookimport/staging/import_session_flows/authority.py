from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cookimport.parsing.label_source_of_truth import LabelFirstStageResult
from cookimport.staging.output_names import (
    AUTHORITATIVE_BLOCK_LABELS_SCHEMA_VERSION,
    LABEL_DETERMINISTIC_DIR_NAME,
    LABEL_DETERMINISTIC_SCHEMA_VERSION,
    LABEL_REFINE_DIR_NAME,
    LABEL_REFINE_SCHEMA_VERSION,
    RECIPE_BOUNDARY_DECISIONS_SCHEMA_VERSION,
    RECIPE_BOUNDARY_DIR_NAME,
    RECIPE_BOUNDARY_SCHEMA_VERSION,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "\n".join(
            json.dumps(row, sort_keys=True)
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )

def _write_label_first_artifacts(
    *,
    run_root: Path,
    workbook_slug: str,
    label_first_result: LabelFirstStageResult,
    line_role_pipeline: str,
) -> dict[str, Path]:
    det_lines_path = run_root / LABEL_DETERMINISTIC_DIR_NAME / workbook_slug / "labeled_lines.jsonl"
    det_blocks_path = run_root / LABEL_DETERMINISTIC_DIR_NAME / workbook_slug / "block_labels.json"
    final_lines_path = run_root / LABEL_REFINE_DIR_NAME / workbook_slug / "labeled_lines.jsonl"
    final_blocks_path = run_root / LABEL_REFINE_DIR_NAME / workbook_slug / "block_labels.json"
    final_diffs_path = run_root / LABEL_REFINE_DIR_NAME / workbook_slug / "label_diffs.jsonl"
    span_path = run_root / RECIPE_BOUNDARY_DIR_NAME / workbook_slug / "recipe_spans.json"
    span_decisions_path = run_root / RECIPE_BOUNDARY_DIR_NAME / workbook_slug / "span_decisions.json"
    authoritative_blocks_path = (
        run_root / RECIPE_BOUNDARY_DIR_NAME / workbook_slug / "authoritative_block_labels.json"
    )

    det_line_rows = [
        {
            "source_block_id": row.source_block_id,
            "source_block_index": row.source_block_index,
            "atomic_index": row.atomic_index,
            "text": row.text,
            "label": row.deterministic_label,
            "final_label": row.final_label,
            "decided_by": row.decided_by,
            "reason_tags": list(row.reason_tags),
            "escalation_reasons": list(row.escalation_reasons),
        }
        for row in label_first_result.labeled_lines
    ]
    det_block_rows = {
        "schema_version": LABEL_DETERMINISTIC_SCHEMA_VERSION,
        "workbook_slug": workbook_slug,
        "block_labels": [
            {
                "source_block_id": row.source_block_id,
                "source_block_index": row.source_block_index,
                "supporting_atomic_indices": list(row.supporting_atomic_indices),
                "label": row.deterministic_label,
                "final_label": row.final_label,
                "decided_by": row.decided_by,
                "reason_tags": list(row.reason_tags),
                "escalation_reasons": list(row.escalation_reasons),
            }
            for row in label_first_result.block_labels
        ],
    }
    _write_jsonl(det_lines_path, det_line_rows)
    _write_json(det_blocks_path, det_block_rows)

    wrote_final_stage = str(line_role_pipeline or "off").strip().lower() != "off"
    if wrote_final_stage:
        final_line_rows = [
            {
                "source_block_id": row.source_block_id,
                "source_block_index": row.source_block_index,
                "atomic_index": row.atomic_index,
                "text": row.text,
                "deterministic_label": row.deterministic_label,
                "label": row.final_label,
                "decided_by": row.decided_by,
                "reason_tags": list(row.reason_tags),
                "escalation_reasons": list(row.escalation_reasons),
            }
            for row in label_first_result.labeled_lines
        ]
        final_block_rows = {
            "schema_version": LABEL_REFINE_SCHEMA_VERSION,
            "workbook_slug": workbook_slug,
            "block_labels": [
                row.model_dump(mode="json")
                for row in label_first_result.block_labels
            ],
        }
        diff_rows = [
            {
                "atomic_index": row.atomic_index,
                "source_block_index": row.source_block_index,
                "text": row.text,
                "deterministic_label": row.deterministic_label,
                "final_label": row.final_label,
            }
            for row in label_first_result.labeled_lines
            if row.deterministic_label != row.final_label
        ]
        _write_jsonl(final_lines_path, final_line_rows)
        _write_json(final_blocks_path, final_block_rows)
        _write_jsonl(final_diffs_path, diff_rows)

    _write_json(
        span_path,
        {
            "schema_version": RECIPE_BOUNDARY_SCHEMA_VERSION,
            "workbook_slug": workbook_slug,
            "recipe_spans": [
                row.model_dump(mode="json") for row in label_first_result.recipe_spans
            ],
        },
    )
    _write_json(
        span_decisions_path,
        {
            "schema_version": RECIPE_BOUNDARY_DECISIONS_SCHEMA_VERSION,
            "workbook_slug": workbook_slug,
            "span_decisions": [
                _serialize_span_decision(row)
                for row in _span_decisions_for_artifacts(label_first_result)
            ],
        },
    )
    _write_json(
        authoritative_blocks_path,
        {
            "schema_version": AUTHORITATIVE_BLOCK_LABELS_SCHEMA_VERSION,
            "workbook_slug": workbook_slug,
            "block_labels": [
                row.model_dump(mode="json") for row in label_first_result.block_labels
            ],
        },
    )

    paths = {
        "label_deterministic_lines_path": det_lines_path,
        "label_deterministic_blocks_path": det_blocks_path,
        "recipe_spans_path": span_path,
        "span_decisions_path": span_decisions_path,
        "authoritative_block_labels_path": authoritative_blocks_path,
    }
    if wrote_final_stage:
        paths.update(
            {
                "label_llm_lines_path": final_lines_path,
                "label_llm_blocks_path": final_blocks_path,
                "label_llm_diffs_path": final_diffs_path,
            }
        )
    return paths

def _span_decisions_for_artifacts(
    label_first_result: LabelFirstStageResult,
) -> list[Any]:
    if label_first_result.span_decisions:
        return list(label_first_result.span_decisions)
    return [
        {
            "span_id": row.span_id,
            "decision": "accepted_recipe_span",
            "rejection_reason": None,
            "start_block_index": row.start_block_index,
            "end_block_index": row.end_block_index,
            "block_indices": list(row.block_indices),
            "source_block_ids": list(row.source_block_ids),
            "start_atomic_index": row.start_atomic_index,
            "end_atomic_index": row.end_atomic_index,
            "atomic_indices": list(row.atomic_indices),
            "title_block_index": row.title_block_index,
            "title_atomic_index": row.title_atomic_index,
            "warnings": list(row.warnings),
            "escalation_reasons": list(row.escalation_reasons),
            "decision_notes": list(row.decision_notes),
        }
        for row in label_first_result.recipe_spans
    ]

def _serialize_span_decision(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        payload = row.model_dump(mode="json")
    else:
        payload = dict(row)
    return {
        "span_id": payload.get("span_id"),
        "decision": payload.get("decision", "accepted_recipe_span"),
        "rejection_reason": payload.get("rejection_reason"),
        "start_block_index": payload.get("start_block_index"),
        "end_block_index": payload.get("end_block_index"),
        "block_indices": list(payload.get("block_indices") or []),
        "source_block_ids": list(payload.get("source_block_ids") or []),
        "start_atomic_index": payload.get("start_atomic_index"),
        "end_atomic_index": payload.get("end_atomic_index"),
        "atomic_indices": list(payload.get("atomic_indices") or []),
        "title_block_index": payload.get("title_block_index"),
        "title_atomic_index": payload.get("title_atomic_index"),
        "escalation_reasons": list(payload.get("escalation_reasons") or []),
        "decision_notes": list(payload.get("decision_notes") or []),
        "warnings": list(payload.get("warnings") or []),
    }
