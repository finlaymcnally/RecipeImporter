from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RawArtifact,
    RecipeComment,
    RecipeCandidate,
)
from cookimport.core.reporting import ProvenanceBuilder, generate_recipe_id
from cookimport.labelstudio.archive import build_extracted_archive
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABELS,
    normalize_freeform_label,
)
from cookimport.parsing.canonical_line_roles import (
    CanonicalLineRolePrediction,
    label_atomic_lines_with_baseline,
)
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate, atomize_blocks
from cookimport.parsing.tips import (
    extract_tip_candidates_from_candidate,
    partition_tip_candidates,
)

_RECIPE_LOCAL_LABELS = {
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
}
_TITLE_LIKE_LABELS = {"RECIPE_TITLE", "RECIPE_VARIANT"}
_LABEL_RESOLUTION_PRIORITY: tuple[str, ...] = (
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


class AuthoritativeLabeledLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_block_id: str
    source_block_index: int
    atomic_index: int
    text: str
    within_recipe_span_hint: bool = False
    deterministic_label: str
    final_label: str
    confidence: float
    decided_by: Literal["rule", "codex", "fallback"]
    reason_tags: list[str] = Field(default_factory=list)


class AuthoritativeBlockLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_block_id: str
    source_block_index: int
    supporting_atomic_indices: list[int] = Field(default_factory=list)
    deterministic_label: str
    final_label: str
    confidence: float
    decided_by: Literal["rule", "codex", "fallback"]
    reason_tags: list[str] = Field(default_factory=list)


class RecipeSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str
    start_block_index: int
    end_block_index: int
    block_indices: list[int] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    start_atomic_index: int | None = None
    end_atomic_index: int | None = None
    atomic_indices: list[int] = Field(default_factory=list)
    title_block_index: int | None = None
    title_atomic_index: int | None = None
    warnings: list[str] = Field(default_factory=list)


class LabelStageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labeled_lines: list[AuthoritativeLabeledLine] = Field(default_factory=list)
    block_labels: list[AuthoritativeBlockLabel] = Field(default_factory=list)


class LabelFirstCompatibilityResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    labeled_lines: list[AuthoritativeLabeledLine] = Field(default_factory=list)
    block_labels: list[AuthoritativeBlockLabel] = Field(default_factory=list)
    recipe_spans: list[RecipeSpan] = Field(default_factory=list)
    non_recipe_lines: list[AuthoritativeLabeledLine] = Field(default_factory=list)
    conversion_result: ConversionResult
    archive_blocks: list[dict[str, Any]] = Field(default_factory=list)
    source_hash: str | None = None


def build_label_first_compatibility_result(
    *,
    conversion_result: ConversionResult,
    source_file: Path,
    importer_name: str,
    run_settings: RunSettings,
    artifact_root: Path | None = None,
    full_blocks: Sequence[dict[str, Any]] | None = None,
    live_llm_allowed: bool = False,
    progress_callback: Any | None = None,
) -> LabelFirstCompatibilityResult:
    archive_blocks = _archive_block_rows(
        conversion_result=conversion_result,
        full_blocks=full_blocks,
    )
    source_hash = _resolve_source_hash(
        conversion_result=conversion_result,
        source_file=source_file,
    )
    atomized = _atomize_archive_blocks(
        archive_blocks,
        atomic_block_splitter=_run_setting_value(
            run_settings,
            "atomic_block_splitter",
            default="atomic-v1",
        ),
    )
    if atomized:
        final_predictions, baseline_predictions = label_atomic_lines_with_baseline(
            atomized,
            run_settings,
            artifact_root=artifact_root,
            source_hash=source_hash,
            live_llm_allowed=live_llm_allowed,
            progress_callback=progress_callback,
        )
    else:
        final_predictions = []
        baseline_predictions = []

    labeled_lines = _build_authoritative_lines(
        final_predictions=final_predictions,
        baseline_predictions=baseline_predictions,
    )
    block_labels = _build_authoritative_block_labels(labeled_lines)

    from cookimport.parsing.recipe_span_grouping import group_recipe_spans_from_labels

    recipe_spans, normalized_block_labels = group_recipe_spans_from_labels(
        block_labels,
        labeled_lines,
    )
    compatibility = build_conversion_result_from_label_spans(
        source_file=source_file,
        importer_name=importer_name,
        source_hash=source_hash,
        original_result=conversion_result,
        archive_blocks=archive_blocks,
        labeled_lines=labeled_lines,
        block_labels=normalized_block_labels,
        recipe_spans=recipe_spans,
        run_settings=run_settings,
    )
    return compatibility


def build_conversion_result_from_label_spans(
    *,
    source_file: Path,
    importer_name: str,
    source_hash: str,
    original_result: ConversionResult,
    archive_blocks: Sequence[dict[str, Any]],
    labeled_lines: Sequence[AuthoritativeLabeledLine],
    block_labels: Sequence[AuthoritativeBlockLabel],
    recipe_spans: Sequence[RecipeSpan],
    run_settings: RunSettings | None = None,
) -> LabelFirstCompatibilityResult:
    block_ids_in_recipe = {
        int(block_index)
        for span in recipe_spans
        for block_index in span.block_indices
    }
    lines_by_block: dict[int, list[AuthoritativeLabeledLine]] = defaultdict(list)
    for row in labeled_lines:
        lines_by_block[int(row.source_block_index)].append(row)
    for rows in lines_by_block.values():
        rows.sort(key=lambda row: row.atomic_index)

    ordered_blocks = sorted(
        (dict(block) for block in archive_blocks if isinstance(block, dict)),
        key=lambda row: int(row.get("index", 0)),
    )
    non_recipe_blocks = [
        dict(block)
        for block in ordered_blocks
        if int(block.get("index", -1)) not in block_ids_in_recipe
    ]
    non_recipe_lines = [
        row
        for row in labeled_lines
        if int(row.source_block_index) not in block_ids_in_recipe
    ]

    report = (
        original_result.report.model_copy(deep=True)
        if isinstance(original_result.report, ConversionReport)
        else ConversionReport()
    )
    report.warnings = list(report.warnings)
    label_warning = "label_source_of_truth=label-first-v1"
    if label_warning not in report.warnings:
        report.warnings.append(label_warning)

    recipes: list[RecipeCandidate] = []
    tip_candidates: list[Any] = []
    provenance_builder = ProvenanceBuilder(
        source_file=source_file.name,
        source_hash=source_hash,
        extraction_method="label_first_stage2",
    )
    overrides = None
    if run_settings is not None:
        raw_overrides = getattr(run_settings, "parsing_overrides", None)
        if isinstance(raw_overrides, dict):
            overrides = raw_overrides

    for recipe_index, span in enumerate(recipe_spans):
        span_rows = [
            row
            for block_index in span.block_indices
            for row in lines_by_block.get(int(block_index), [])
        ]
        span_rows.sort(key=lambda row: row.atomic_index)
        recipe = _build_recipe_candidate_from_span(
            recipe_index=recipe_index,
            span=span,
            span_rows=span_rows,
            source_hash=source_hash,
            importer_name=importer_name,
            provenance_builder=provenance_builder,
        )
        recipes.append(recipe)
        tip_candidates.extend(
            extract_tip_candidates_from_candidate(recipe, overrides=overrides)
        )

    tips, _recipe_specific, _not_tips = partition_tip_candidates(tip_candidates)
    updated_result = ConversionResult(
        source=original_result.source,
        recipes=recipes,
        tips=tips,
        tip_candidates=list(tip_candidates),
        topic_candidates=list(original_result.topic_candidates),
        chunks=list(original_result.chunks),
        non_recipe_blocks=non_recipe_blocks,
        raw_artifacts=list(original_result.raw_artifacts),
        report=report,
        workbook=original_result.workbook,
        workbook_path=original_result.workbook_path,
    )
    return LabelFirstCompatibilityResult(
        labeled_lines=list(labeled_lines),
        block_labels=list(block_labels),
        recipe_spans=list(recipe_spans),
        non_recipe_lines=non_recipe_lines,
        conversion_result=updated_result,
        archive_blocks=[dict(block) for block in ordered_blocks],
        source_hash=source_hash,
    )


def build_authoritative_stage_block_predictions(
    *,
    block_labels: Sequence[AuthoritativeBlockLabel],
    archive_blocks: Sequence[dict[str, Any]],
    source_file: str,
    source_hash: str,
    workbook_slug: str,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    max_index = max(
        (int(block.get("index", -1)) for block in archive_blocks if isinstance(block, dict)),
        default=-1,
    )
    block_count = max_index + 1 if max_index >= 0 else 0
    resolved = {int(row.source_block_index): row.final_label for row in block_labels}
    label_blocks: dict[str, list[int]] = {label: [] for label in FREEFORM_LABELS}
    for block_index in range(block_count):
        label = str(resolved.get(block_index, "OTHER") or "OTHER")
        label_blocks.setdefault(label, []).append(block_index)
    return {
        "schema_version": "stage_block_predictions.v1",
        "source_file": str(source_file),
        "source_hash": str(source_hash or "unknown"),
        "workbook_slug": str(workbook_slug),
        "block_count": block_count,
        "block_labels": {
            str(block_index): str(resolved.get(block_index, "OTHER") or "OTHER")
            for block_index in range(block_count)
        },
        "label_blocks": {
            label: sorted(indices)
            for label, indices in label_blocks.items()
        },
        "conflicts": [],
        "notes": [
            "Derived directly from authoritative Phase 2 labels.",
            *[str(note).strip() for note in (notes or []) if str(note).strip()],
        ],
    }


def authoritative_lines_to_canonical_predictions(
    labeled_lines: Sequence[AuthoritativeLabeledLine],
    recipe_spans: Sequence[RecipeSpan],
) -> list[CanonicalLineRolePrediction]:
    recipe_index_by_block: dict[int, int] = {}
    span_id_by_block: dict[int, str] = {}
    for recipe_index, span in enumerate(recipe_spans):
        for block_index in span.block_indices:
            recipe_index_by_block[int(block_index)] = recipe_index
            span_id_by_block[int(block_index)] = span.span_id
    predictions: list[CanonicalLineRolePrediction] = []
    for row in labeled_lines:
        block_index = int(row.source_block_index)
        recipe_index = recipe_index_by_block.get(block_index)
        predictions.append(
            CanonicalLineRolePrediction(
                recipe_id=(
                    f"recipe:{recipe_index}"
                    if recipe_index is not None
                    else span_id_by_block.get(block_index)
                ),
                block_id=row.source_block_id,
                block_index=block_index,
                atomic_index=int(row.atomic_index),
                text=row.text,
                within_recipe_span=recipe_index is not None,
                label=row.final_label,
                confidence=float(row.confidence),
                decided_by=row.decided_by,
                reason_tags=list(row.reason_tags),
            )
        )
    return predictions


def _build_recipe_candidate_from_span(
    *,
    recipe_index: int,
    span: RecipeSpan,
    span_rows: Sequence[AuthoritativeLabeledLine],
    source_hash: str,
    importer_name: str,
    provenance_builder: ProvenanceBuilder,
) -> RecipeCandidate:
    by_label: dict[str, list[str]] = defaultdict(list)
    for row in span_rows:
        if row.final_label not in FREEFORM_ALLOWED_LABELS:
            continue
        text = str(row.text or "").strip()
        if not text:
            continue
        if text not in by_label[row.final_label]:
            by_label[row.final_label].append(text)

    title_candidates = by_label.get("RECIPE_TITLE") or by_label.get("RECIPE_VARIANT") or []
    recipe_name = title_candidates[0] if title_candidates else _fallback_recipe_name(span_rows)
    confidence_rows = [float(row.confidence) for row in span_rows]
    confidence = (
        round(sum(confidence_rows) / len(confidence_rows), 4)
        if confidence_rows
        else None
    )
    location = {
        "start_block": span.start_block_index,
        "end_block": span.end_block_index,
        "chunk_index": recipe_index,
        "label_source": "label-first-v1",
        "recipe_span_id": span.span_id,
        "title_block_index": span.title_block_index,
    }
    provenance = provenance_builder.build(
        confidence_score=float(confidence or 0.0),
        location=location,
    )
    comments = [RecipeComment(text=text) for text in by_label.get("RECIPE_NOTES", [])]
    recipe = RecipeCandidate(
        name=recipe_name,
        identifier=generate_recipe_id(
            importer_name,
            source_hash,
            f"label_span_{recipe_index}",
        ),
        recipeIngredient=list(by_label.get("INGREDIENT_LINE", [])),
        recipeInstructions=list(
            by_label.get("HOWTO_SECTION", []) + by_label.get("INSTRUCTION_LINE", [])
        ),
        recipeYield=(by_label.get("YIELD_LINE") or [None])[0],
        totalTime=(by_label.get("TIME_LINE") or [None])[0],
        comment=comments,
        provenance=provenance,
        confidence=confidence,
    )
    return recipe


def _fallback_recipe_name(rows: Sequence[AuthoritativeLabeledLine]) -> str:
    for row in rows:
        text = str(row.text or "").strip()
        if text:
            return text
    return "Untitled Recipe"


def _archive_block_rows(
    *,
    conversion_result: ConversionResult,
    full_blocks: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if full_blocks:
        rows: list[dict[str, Any]] = []
        for fallback_index, block in enumerate(full_blocks):
            if not isinstance(block, dict):
                continue
            row = dict(block)
            row.setdefault("index", fallback_index)
            row.setdefault("block_id", f"block:{row['index']}")
            rows.append(row)
        rows.sort(key=lambda row: int(row.get("index", 0)))
        return rows

    archive = build_extracted_archive(
        conversion_result,
        list(conversion_result.raw_artifacts),
    )
    rows: list[dict[str, Any]] = []
    for block in archive:
        rows.append(
            {
                "index": int(block.index),
                "block_id": str(block.location.get("block_id") or f"block:{block.index}"),
                "text": str(block.text or ""),
                "location": dict(block.location or {}),
                "source_kind": block.source_kind,
            }
        )
    rows.sort(key=lambda row: int(row.get("index", 0)))
    return rows


def _atomize_archive_blocks(
    archive_blocks: Sequence[dict[str, Any]],
    *,
    atomic_block_splitter: str,
) -> list[AtomicLineCandidate]:
    staged: list[dict[str, Any]] = []
    for row in archive_blocks:
        block_index = int(row.get("index", 0))
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        atomized = atomize_blocks(
            [
                {
                    "block_id": str(row.get("block_id") or f"block:{block_index}"),
                    "block_index": block_index,
                    "text": text,
                }
            ],
            recipe_id=None,
            within_recipe_span=False,
            atomic_block_splitter=atomic_block_splitter,
        )
        for candidate in atomized:
            staged.append(
                {
                    "recipe_id": None,
                    "block_id": candidate.block_id,
                    "block_index": candidate.block_index,
                    "text": candidate.text,
                    "within_recipe_span": False,
                    "rule_tags": list(candidate.rule_tags),
                }
            )

    output: list[AtomicLineCandidate] = []
    for atomic_index, row in enumerate(staged):
        prev_text = staged[atomic_index - 1]["text"] if atomic_index > 0 else None
        next_text = (
            staged[atomic_index + 1]["text"]
            if atomic_index + 1 < len(staged)
            else None
        )
        output.append(
            AtomicLineCandidate(
                recipe_id=None,
                block_id=str(row["block_id"]),
                block_index=int(row["block_index"]),
                atomic_index=atomic_index,
                text=str(row["text"]),
                within_recipe_span=False,
                prev_text=prev_text,
                next_text=next_text,
                rule_tags=list(row["rule_tags"]),
            )
        )
    return output


def _build_authoritative_lines(
    *,
    final_predictions: Sequence[CanonicalLineRolePrediction],
    baseline_predictions: Sequence[CanonicalLineRolePrediction],
) -> list[AuthoritativeLabeledLine]:
    baseline_by_atomic = {
        int(prediction.atomic_index): prediction for prediction in baseline_predictions
    }
    labeled_lines: list[AuthoritativeLabeledLine] = []
    for prediction in final_predictions:
        baseline = baseline_by_atomic.get(int(prediction.atomic_index), prediction)
        deterministic_label = _canonical_label(getattr(baseline, "label", "OTHER"))
        final_label = _canonical_label(getattr(prediction, "label", "OTHER"))
        labeled_lines.append(
            AuthoritativeLabeledLine(
                source_block_id=str(prediction.block_id),
                source_block_index=int(prediction.block_index or 0),
                atomic_index=int(prediction.atomic_index),
                text=str(prediction.text or ""),
                within_recipe_span_hint=bool(prediction.within_recipe_span),
                deterministic_label=deterministic_label,
                final_label=final_label,
                confidence=float(prediction.confidence),
                decided_by=prediction.decided_by,
                reason_tags=list(prediction.reason_tags),
            )
        )
    labeled_lines.sort(key=lambda row: row.atomic_index)
    return labeled_lines


def _build_authoritative_block_labels(
    labeled_lines: Sequence[AuthoritativeLabeledLine],
) -> list[AuthoritativeBlockLabel]:
    rows_by_block: dict[int, list[AuthoritativeLabeledLine]] = defaultdict(list)
    for row in labeled_lines:
        rows_by_block[int(row.source_block_index)].append(row)

    output: list[AuthoritativeBlockLabel] = []
    for block_index in sorted(rows_by_block):
        rows = sorted(rows_by_block[block_index], key=lambda row: row.atomic_index)
        selected_final = _select_block_label(rows, field_name="final_label")
        selected_det = _select_block_label(rows, field_name="deterministic_label")
        support = [
            int(row.atomic_index)
            for row in rows
            if row.final_label == selected_final
        ]
        representative = next(
            (
                row
                for row in rows
                if row.final_label == selected_final
            ),
            rows[0],
        )
        output.append(
            AuthoritativeBlockLabel(
                source_block_id=representative.source_block_id,
                source_block_index=block_index,
                supporting_atomic_indices=support,
                deterministic_label=selected_det,
                final_label=selected_final,
                confidence=max(float(row.confidence) for row in rows),
                decided_by=representative.decided_by,
                reason_tags=list(representative.reason_tags),
            )
        )
    return output


def _select_block_label(
    rows: Sequence[AuthoritativeLabeledLine],
    *,
    field_name: Literal["deterministic_label", "final_label"],
) -> str:
    labels = [str(getattr(row, field_name) or "OTHER") for row in rows]
    for priority_label in _LABEL_RESOLUTION_PRIORITY:
        if priority_label in labels:
            return priority_label
    for label in labels:
        if label in FREEFORM_ALLOWED_LABELS:
            return label
    return "OTHER"


def _canonical_label(raw_label: Any) -> str:
    normalized = normalize_freeform_label(str(raw_label or "OTHER"))
    if normalized not in FREEFORM_ALLOWED_LABELS:
        return "OTHER"
    return normalized


def _run_setting_value(
    run_settings: RunSettings,
    field_name: str,
    *,
    default: str,
) -> str:
    value = getattr(run_settings, field_name, default)
    if hasattr(value, "value"):
        value = value.value
    return str(value or default)


def _resolve_source_hash(
    *,
    conversion_result: ConversionResult,
    source_file: Path,
) -> str:
    for artifact in conversion_result.raw_artifacts:
        if isinstance(artifact, RawArtifact) and artifact.source_hash:
            return str(artifact.source_hash)
    try:
        from cookimport.core.reporting import compute_file_hash

        return compute_file_hash(source_file)
    except Exception:  # noqa: BLE001
        return "unknown"
