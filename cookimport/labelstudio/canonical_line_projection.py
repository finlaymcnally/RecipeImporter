from __future__ import annotations

import json
import re
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
_WHITESPACE_RE = re.compile(r"\s+")
_MATCH_CHAR_MAP = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        "…": "...",
    }
)


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
    block_labels = {int(row.line_index): str(row.label) for row in spans}
    label_blocks: dict[str, list[int]] = {label: [] for label in FREEFORM_LABELS}
    for line_index, label in block_labels.items():
        label_blocks.setdefault(label, []).append(int(line_index))
    for label in label_blocks:
        label_blocks[label].sort()
    return {
        "schema_version": "stage_block_predictions.v1",
        "source_file": str(source_file),
        "source_hash": str(source_hash or "unknown"),
        "workbook_slug": str(workbook_slug),
        "block_count": len(block_labels),
        "block_labels": {str(index): label for index, label in sorted(block_labels.items())},
        "label_blocks": label_blocks,
        "conflicts": [],
        "notes": [
            "Projected from canonical line-role predictions.",
            "block_index in this artifact is canonical line_index over atomic spans.",
            *[str(note).strip() for note in (notes or []) if str(note).strip()],
        ],
    }


def _normalize_match_text(text: str) -> str:
    normalized = str(text or "").translate(_MATCH_CHAR_MAP).lower()
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def _load_pass4_knowledge_evidence(
    snippets_path: Path | None,
) -> tuple[dict[int, set[str]], set[int]]:
    if snippets_path is None or not snippets_path.exists() or not snippets_path.is_file():
        return {}, set()

    quotes_by_block: dict[int, set[str]] = {}
    provenance_blocks: set[int] = set()
    for line in snippets_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        provenance = payload.get("provenance")
        if isinstance(provenance, dict):
            raw_indices = provenance.get("block_indices")
            if isinstance(raw_indices, list):
                for value in raw_indices:
                    try:
                        provenance_blocks.add(int(value))
                    except (TypeError, ValueError):
                        continue

        evidence_rows = payload.get("evidence")
        if not isinstance(evidence_rows, list):
            continue
        for evidence in evidence_rows:
            if not isinstance(evidence, dict):
                continue
            try:
                block_index = int(evidence.get("block_index"))
            except (TypeError, ValueError):
                continue
            provenance_blocks.add(block_index)
            quote = _normalize_match_text(str(evidence.get("quote") or ""))
            if not quote:
                continue
            quotes_by_block.setdefault(block_index, set()).add(quote)

    return quotes_by_block, provenance_blocks


def _quote_matches_span(*, quote: str, span_text: str) -> bool:
    normalized_quote = _normalize_match_text(quote)
    normalized_span = _normalize_match_text(span_text)
    if not normalized_quote or not normalized_span:
        return False
    return normalized_quote in normalized_span or normalized_span in normalized_quote


def _merge_pass4_knowledge_into_spans(
    spans: Sequence[FreeformSpanPrediction],
    *,
    knowledge_snippets_path: Path | None,
) -> tuple[list[FreeformSpanPrediction], list[str]]:
    quotes_by_block, provenance_blocks = _load_pass4_knowledge_evidence(knowledge_snippets_path)
    if not provenance_blocks:
        if knowledge_snippets_path is not None and knowledge_snippets_path.exists():
            return list(spans), [
                "Pass4 knowledge snippets were present but did not yield usable evidence."
            ]
        return list(spans), []

    spans_by_block: dict[int, list[FreeformSpanPrediction]] = {}
    for span in spans:
        spans_by_block.setdefault(int(span.block_index), []).append(span)

    selected_line_indices: set[int] = set()
    for block_index in sorted(provenance_blocks):
        block_spans = [
            span for span in spans_by_block.get(block_index, []) if not bool(span.within_recipe_span)
        ]
        if not block_spans:
            continue
        block_quotes = quotes_by_block.get(block_index, set())
        quote_matches = {
            int(span.line_index)
            for span in block_spans
            if any(_quote_matches_span(quote=quote, span_text=span.text) for quote in block_quotes)
        }
        if quote_matches:
            selected_line_indices.update(quote_matches)
            continue
        selected_line_indices.update(int(span.line_index) for span in block_spans)

    merged_spans: list[FreeformSpanPrediction] = []
    upgraded_count = 0
    for span in spans:
        if int(span.line_index) in selected_line_indices and str(span.label) == "OTHER":
            merged_spans.append(span.model_copy(update={"label": "KNOWLEDGE"}))
            upgraded_count += 1
            continue
        merged_spans.append(span)

    notes = ["Pass4 knowledge evidence merged into canonical line-role projection."]
    if upgraded_count:
        notes.append(f"Pass4 upgraded {upgraded_count} projected OTHER spans to KNOWLEDGE.")
    else:
        notes.append("Pass4 knowledge evidence did not change projected labels.")
    return merged_spans, notes


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
    knowledge_snippets_path: Path | None = None,
) -> dict[str, Path]:
    pipeline_dir = run_root / "line-role-pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    spans = project_line_roles_to_freeform_spans(predictions)
    spans, merge_notes = _merge_pass4_knowledge_into_spans(
        spans,
        knowledge_snippets_path=knowledge_snippets_path,
    )
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
        notes=merge_notes,
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
    guardrail_report_path = pipeline_dir / "guardrail_report.json"
    if guardrail_report_path.exists():
        artifact_paths["guardrail_report_path"] = guardrail_report_path
    guardrail_changed_rows_path = pipeline_dir / "guardrail_changed_rows.jsonl"
    if guardrail_changed_rows_path.exists():
        artifact_paths["guardrail_changed_rows_path"] = guardrail_changed_rows_path
    do_no_harm_diagnostics_path = pipeline_dir / "do_no_harm_diagnostics.json"
    if do_no_harm_diagnostics_path.exists():
        artifact_paths["do_no_harm_diagnostics_path"] = do_no_harm_diagnostics_path
    do_no_harm_changed_rows_path = pipeline_dir / "do_no_harm_changed_rows.jsonl"
    if do_no_harm_changed_rows_path.exists():
        artifact_paths["do_no_harm_changed_rows_path"] = do_no_harm_changed_rows_path
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
