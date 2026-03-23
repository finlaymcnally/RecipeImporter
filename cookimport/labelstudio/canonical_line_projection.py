from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict

from cookimport.core.models import ConversionResult
from cookimport.parsing.canonical_line_roles import CanonicalLineRolePrediction
from cookimport.staging.draft_v1 import (
    apply_line_role_spans_to_recipes as apply_line_role_spans_to_staging_recipes,
)
from cookimport.staging.stage_block_predictions import FREEFORM_LABELS

_FREEFORM_LABEL_SET = set(FREEFORM_LABELS)
_PROJECTED_LABEL_PRIORITY: tuple[str, ...] = (
    "RECIPE_VARIANT",
    "RECIPE_TITLE",
    "YIELD_LINE",
    "TIME_LINE",
    "HOWTO_SECTION",
    "INGREDIENT_LINE",
    "RECIPE_NOTES",
    "INSTRUCTION_LINE",
    "KNOWLEDGE",
)
_PROJECTED_RECIPE_LOCAL_LABELS: set[str] = {
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
}


class FreeformSpanPrediction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    line_index: int
    atomic_index: int
    block_id: str
    block_index: int
    recipe_id: str | None = None
    recipe_index: int | None = None
    within_recipe_span: bool = False
    label: str
    text: str


def project_line_roles_to_freeform_spans(
    predictions: Sequence[CanonicalLineRolePrediction],
) -> list[FreeformSpanPrediction]:
    ordered = sorted(predictions, key=lambda row: int(row.atomic_index))
    rows: list[FreeformSpanPrediction] = []
    for position, prediction in enumerate(ordered):
        recipe_id = str(prediction.recipe_id or "").strip() or None
        recipe_index = _recipe_index_from_recipe_id(recipe_id)
        within_recipe_span = bool(prediction.within_recipe_span)
        label = str(prediction.label or "OTHER").strip().upper() or "OTHER"
        if label not in _FREEFORM_LABEL_SET:
            label = "OTHER"
        block_index = int(prediction.block_index) if prediction.block_index is not None else position
        rows.append(
            FreeformSpanPrediction(
                line_index=position,
                atomic_index=int(prediction.atomic_index),
                block_id=str(prediction.block_id),
                block_index=block_index,
                recipe_id=recipe_id,
                recipe_index=recipe_index,
                within_recipe_span=within_recipe_span,
                label=label,
                text=str(prediction.text or ""),
            )
        )
    return rows


def build_line_role_stage_prediction_payload(
    spans: Sequence[FreeformSpanPrediction],
    *,
    source_file: str,
    source_hash: str,
    workbook_slug: str,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    labels_by_block: dict[int, list[str]] = {}
    for row in spans:
        block_index = int(row.block_index)
        labels_by_block.setdefault(block_index, []).append(str(row.label))

    block_count = max(labels_by_block.keys(), default=-1) + 1
    resolved_labels: dict[int, str] = {}
    conflicts: list[dict[str, Any]] = []
    for block_index, labels in sorted(labels_by_block.items()):
        conflict_labels = _projected_conflict_labels(labels)
        if len(conflict_labels) > 1:
            conflicts.append(
                {
                    "block_index": block_index,
                    "labels": conflict_labels,
                }
            )
        resolved_labels[block_index] = _resolve_projected_block_label(labels)

    label_blocks: dict[str, list[int]] = {label: [] for label in FREEFORM_LABELS}
    for block_index in range(block_count):
        label = resolved_labels.get(block_index, "OTHER")
        label_blocks.setdefault(label, []).append(block_index)
    for label in label_blocks:
        label_blocks[label].sort()
    return {
        "schema_version": "stage_block_predictions.v1",
        "source_file": str(source_file),
        "source_hash": str(source_hash or "unknown"),
        "workbook_slug": str(workbook_slug),
        "block_count": block_count,
        "block_labels": {
            str(index): resolved_labels.get(index, "OTHER") for index in range(block_count)
        },
        "label_blocks": label_blocks,
        "conflicts": conflicts,
        "notes": [
            "Projected from canonical line-role predictions.",
            "block_labels in this artifact are aggregated by source block_index.",
            *[str(note).strip() for note in (notes or []) if str(note).strip()],
        ],
    }


def build_line_role_extracted_archive_payload(
    spans: Sequence[FreeformSpanPrediction],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for span in sorted(spans, key=lambda row: int(row.line_index)):
        rows.append(
            {
                "index": int(span.line_index),
                "text": str(span.text),
                "location": {
                    "line_index": int(span.line_index),
                    "atomic_index": int(span.atomic_index),
                    "block_index": int(span.block_index),
                    "block_id": str(span.block_id),
                    "recipe_id": span.recipe_id,
                    "recipe_index": span.recipe_index,
                    "within_recipe_span": bool(span.within_recipe_span),
                    "features": {
                        "line_role_projection": True,
                        "source_block_index": int(span.block_index),
                        "source_block_id": str(span.block_id),
                        "atomic_index": int(span.atomic_index),
                        "recipe_id": span.recipe_id,
                        "recipe_index": span.recipe_index,
                        "within_recipe_span": bool(span.within_recipe_span),
                    },
                },
            }
        )
    return rows


def write_line_role_projection_artifacts(
    *,
    run_root: Path,
    source_file: str,
    source_hash: str,
    workbook_slug: str,
    predictions: Sequence[CanonicalLineRolePrediction],
) -> dict[str, Path]:
    pipeline_dir = run_root / "line-role-pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    spans = project_line_roles_to_freeform_spans(predictions)
    line_role_predictions_path = pipeline_dir / "line_role_predictions.jsonl"
    line_role_predictions_path.write_text(
        "".join(
            json.dumps(row.model_dump(mode="json"), sort_keys=True) + "\n"
            for row in predictions
        ),
        encoding="utf-8",
    )

    projected_spans_path = pipeline_dir / "freeform_span_predictions.jsonl"
    projected_spans_path.write_text(
        "".join(
            json.dumps(row.model_dump(mode="json"), sort_keys=True) + "\n"
            for row in spans
        ),
        encoding="utf-8",
    )

    stage_payload = build_line_role_stage_prediction_payload(
        spans,
        source_file=source_file,
        source_hash=source_hash,
        workbook_slug=workbook_slug,
    )
    stage_path = pipeline_dir / "stage_block_predictions.json"
    stage_path.write_text(
        json.dumps(stage_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    extracted_archive_payload = build_line_role_extracted_archive_payload(spans)
    extracted_archive_path = pipeline_dir / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(extracted_archive_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    artifact_paths: dict[str, Path] = {
        "line_role_predictions_path": line_role_predictions_path,
        "projected_spans_path": projected_spans_path,
        "stage_block_predictions_path": stage_path,
        "extracted_archive_path": extracted_archive_path,
    }
    telemetry_summary_path = pipeline_dir / "telemetry_summary.json"
    if telemetry_summary_path.exists():
        artifact_paths["telemetry_summary_path"] = telemetry_summary_path
    return artifact_paths


def apply_line_role_spans_to_recipes(
    *,
    conversion_result: ConversionResult,
    spans: Sequence[FreeformSpanPrediction],
) -> dict[str, Any]:
    return apply_line_role_spans_to_staging_recipes(
        conversion_result=conversion_result,
        spans=list(spans),
    )


def _recipe_index_from_recipe_id(recipe_id: str | None) -> int | None:
    if recipe_id is None:
        return None
    text = str(recipe_id).strip()
    if not text:
        return None
    if text.startswith("recipe:"):
        raw_index = text.split(":", 1)[1]
        try:
            return int(raw_index)
        except ValueError:
            return None
    return None


def _projected_conflict_labels(labels: Sequence[str]) -> list[str]:
    label_set = {
        str(label or "").strip().upper()
        for label in labels
        if str(label or "").strip()
    }
    label_set.discard("OTHER")
    if "KNOWLEDGE" in label_set and any(
        recipe_label in label_set for recipe_label in _PROJECTED_RECIPE_LOCAL_LABELS
    ):
        label_set.discard("KNOWLEDGE")
    return sorted(label_set)


def _resolve_projected_block_label(labels: Sequence[str]) -> str:
    label_set = set(_projected_conflict_labels(labels))
    if not label_set:
        return "OTHER"
    for label in _PROJECTED_LABEL_PRIORITY:
        if label in label_set:
            return label
    return "OTHER"
