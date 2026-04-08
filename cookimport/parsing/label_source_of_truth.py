from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import format_stage_counter_progress
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RawArtifact,
    RecipeComment,
    RecipeCandidate,
)
from cookimport.core.reporting import ProvenanceBuilder, generate_recipe_id
from cookimport.core.source_model import (
    resolve_conversion_source_model,
    source_blocks_to_rows,
)
from cookimport.labelstudio.archive import build_extracted_archive
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABELS,
    normalize_freeform_label,
)
from cookimport.parsing.canonical_line_roles import (
    CANONICAL_LINE_ROLE_ALLOWED_LABELS,
    CanonicalLineRolePrediction,
    label_atomic_lines_with_baseline,
)
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate, atomize_blocks

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
    "NONRECIPE_CANDIDATE",
    "NONRECIPE_EXCLUDE",
)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique_string_list(values: Sequence[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        rendered = str(value or "").strip()
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        output.append(rendered)
    return output


def _notify_authoritative_progress(
    *,
    progress_callback: Any | None,
    current: int,
    total: int,
    detail_lines: Sequence[Any] | None = None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        format_stage_counter_progress(
            "Building authoritative labels...",
            current,
            total,
            stage_label="authoritative labels",
            detail_lines=[
                str(value).strip()
                for value in (detail_lines or [])
                if str(value).strip()
            ]
            or None,
        )
    )


class AuthoritativeLabeledLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_block_id: str
    source_block_index: int
    atomic_index: int
    text: str
    within_recipe_span_hint: bool | None = None
    deterministic_label: str
    final_label: str
    decided_by: Literal["rule", "codex", "fallback"]
    reason_tags: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "AuthoritativeLabeledLine":
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.reason_tags = _unique_string_list(self.reason_tags)
        return self


class AuthoritativeBlockLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_block_id: str
    source_block_index: int
    supporting_atomic_indices: list[int] = Field(default_factory=list)
    deterministic_label: str
    final_label: str
    decided_by: Literal["rule", "codex", "fallback"]
    reason_tags: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "AuthoritativeBlockLabel":
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.reason_tags = _unique_string_list(self.reason_tags)
        return self


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
    escalation_reasons: list[str] = Field(default_factory=list)
    decision_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "RecipeSpan":
        self.warnings = _unique_string_list(self.warnings)
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.decision_notes = _unique_string_list(self.decision_notes)
        return self


class RecipeSpanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str
    decision: Literal["accepted_recipe_span", "rejected_pseudo_recipe_span"]
    rejection_reason: str | None = None
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
    escalation_reasons: list[str] = Field(default_factory=list)
    decision_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_metadata(self) -> "RecipeSpanDecision":
        self.warnings = _unique_string_list(self.warnings)
        self.escalation_reasons = _unique_string_list(self.escalation_reasons)
        self.decision_notes = _unique_string_list(self.decision_notes)
        return self


class LabelStageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labeled_lines: list[AuthoritativeLabeledLine] = Field(default_factory=list)
    block_labels: list[AuthoritativeBlockLabel] = Field(default_factory=list)


class LabelFirstStageResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    labeled_lines: list[AuthoritativeLabeledLine] = Field(default_factory=list)
    block_labels: list[AuthoritativeBlockLabel] = Field(default_factory=list)
    recipe_spans: list[RecipeSpan] = Field(default_factory=list)
    span_decisions: list[RecipeSpanDecision] = Field(default_factory=list)
    non_recipe_lines: list[AuthoritativeLabeledLine] = Field(default_factory=list)
    outside_recipe_blocks: list[dict[str, Any]] = Field(default_factory=list)
    updated_conversion_result: ConversionResult
    archive_blocks: list[dict[str, Any]] = Field(default_factory=list)
    source_hash: str | None = None


def build_label_first_stage_result(
    *,
    conversion_result: ConversionResult,
    source_file: Path,
    importer_name: str,
    run_settings: RunSettings,
    artifact_root: Path | None = None,
    full_blocks: Sequence[dict[str, Any]] | None = None,
    live_llm_allowed: bool = False,
    progress_callback: Any | None = None,
) -> LabelFirstStageResult:
    archive_blocks = _archive_block_rows(
        conversion_result=conversion_result,
        full_blocks=full_blocks,
    )
    archive_block_count = len(archive_blocks)
    _notify_authoritative_progress(
        progress_callback=progress_callback,
        current=0,
        total=4,
        detail_lines=[f"archive blocks: {archive_block_count}"],
    )
    source_hash = _resolve_source_hash(
        conversion_result=conversion_result,
        source_file=source_file,
    )
    atomized = _atomize_archive_blocks(
        archive_blocks,
        conversion_result=conversion_result,
        atomic_block_splitter=_run_setting_value(
            run_settings,
            "atomic_block_splitter",
            default="off",
        ),
    )
    _notify_authoritative_progress(
        progress_callback=progress_callback,
        current=1,
        total=4,
        detail_lines=[
            f"archive blocks: {archive_block_count}",
            f"atomic lines: {len(atomized)}",
        ],
    )
    if atomized:
        _notify_authoritative_progress(
            progress_callback=progress_callback,
            current=2,
            total=4,
            detail_lines=[
                f"archive blocks: {archive_block_count}",
                f"atomic lines: {len(atomized)}",
            ],
        )
        final_predictions, deterministic_reference_predictions = label_atomic_lines_with_baseline(
            atomized,
            run_settings,
            artifact_root=artifact_root,
            source_hash=source_hash,
            live_llm_allowed=live_llm_allowed,
            progress_callback=progress_callback,
        )
    else:
        final_predictions = []
        deterministic_reference_predictions = []

    labeled_lines = _build_authoritative_lines(
        authoritative_predictions=final_predictions,
        deterministic_reference_predictions=deterministic_reference_predictions,
    )
    block_labels = _build_authoritative_block_labels(labeled_lines)
    _notify_authoritative_progress(
        progress_callback=progress_callback,
        current=3,
        total=4,
        detail_lines=[
            f"labeled lines: {len(labeled_lines)}",
            f"block labels: {len(block_labels)}",
        ],
    )

    from cookimport.parsing.recipe_span_grouping import recipe_boundary_from_labels

    recipe_spans, span_decisions, normalized_block_labels = recipe_boundary_from_labels(
        block_labels,
        labeled_lines,
    )
    _notify_authoritative_progress(
        progress_callback=progress_callback,
        current=4,
        total=4,
        detail_lines=[
            f"recipe spans: {len(recipe_spans)}",
            f"block labels: {len(normalized_block_labels)}",
        ],
    )
    return build_conversion_result_from_label_spans(
        source_file=source_file,
        importer_name=importer_name,
        source_hash=source_hash,
        original_result=conversion_result,
        archive_blocks=archive_blocks,
        labeled_lines=labeled_lines,
        block_labels=normalized_block_labels,
        recipe_spans=recipe_spans,
        span_decisions=span_decisions,
        run_settings=run_settings,
    )


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
    span_decisions: Sequence[RecipeSpanDecision],
    run_settings: RunSettings | None = None,
) -> LabelFirstStageResult:
    lines_by_block: dict[int, list[AuthoritativeLabeledLine]] = defaultdict(list)
    for row in labeled_lines:
        lines_by_block[int(row.source_block_index)].append(row)
    for rows in lines_by_block.values():
        rows.sort(key=lambda row: row.atomic_index)

    ordered_blocks = sorted(
        (dict(block) for block in archive_blocks if isinstance(block, dict)),
        key=lambda row: int(row.get("index", 0)),
    )

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
    provenance_builder = ProvenanceBuilder(
        source_file=source_file.name,
        source_hash=source_hash,
        extraction_method="label_first_stage2",
    )

    accepted_recipe_spans: list[RecipeSpan] = []
    decision_by_span_id = {row.span_id: row for row in span_decisions}
    updated_span_decisions: list[RecipeSpanDecision] = []

    for span in recipe_spans:
        span_rows = [
            row
            for block_index in span.block_indices
            for row in lines_by_block.get(int(block_index), [])
        ]
        span_rows.sort(key=lambda row: row.atomic_index)
        recipe = _build_recipe_candidate_from_span(
            recipe_index=len(accepted_recipe_spans),
            span=span,
            span_rows=span_rows,
            source_hash=source_hash,
            importer_name=importer_name,
            provenance_builder=provenance_builder,
        )
        existing_decision = decision_by_span_id.get(span.span_id)
        decision = (
            existing_decision
            if existing_decision is not None
            else RecipeSpanDecision(
                span_id=span.span_id,
                decision="accepted_recipe_span",
                start_block_index=span.start_block_index,
                end_block_index=span.end_block_index,
                block_indices=list(span.block_indices),
                source_block_ids=list(span.source_block_ids),
                start_atomic_index=span.start_atomic_index,
                end_atomic_index=span.end_atomic_index,
                atomic_indices=list(span.atomic_indices),
                title_block_index=span.title_block_index,
                title_atomic_index=span.title_atomic_index,
                warnings=list(span.warnings),
                escalation_reasons=list(span.escalation_reasons),
                decision_notes=list(span.decision_notes),
            )
        )
        if not _recipe_candidate_has_projected_body(recipe):
            invariant_warning = (
                "accepted_recipe_span_projection_missing_body"
                f":{span.span_id}"
            )
            if invariant_warning not in report.warnings:
                report.warnings.append(invariant_warning)
            decision = _annotate_recipe_span_decision(
                decision,
                warning=invariant_warning,
                escalation_reason="accepted_recipe_span_projection_invariant_failed",
                decision_note="accepted_recipe_span_projection_missing_body",
            )
        accepted_recipe_spans.append(span)
        updated_span_decisions.append(decision)
        recipes.append(recipe)

    accepted_span_ids = {row.span_id for row in accepted_recipe_spans}
    for decision in span_decisions:
        if decision.span_id in accepted_span_ids:
            continue
        if decision.span_id not in {row.span_id for row in updated_span_decisions}:
            updated_span_decisions.append(decision)

    block_ids_in_recipe = {
        int(block_index)
        for span in accepted_recipe_spans
        for block_index in span.block_indices
    }
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

    updated_result = ConversionResult(
        source=original_result.source,
        recipes=recipes,
        source_blocks=list(original_result.source_blocks),
        source_support=list(original_result.source_support),
        chunks=[],
        raw_artifacts=list(original_result.raw_artifacts),
        report=report,
        workbook=original_result.workbook,
        workbook_path=original_result.workbook_path,
    )
    return LabelFirstStageResult(
        labeled_lines=list(labeled_lines),
        block_labels=list(block_labels),
        recipe_spans=accepted_recipe_spans,
        span_decisions=updated_span_decisions,
        non_recipe_lines=non_recipe_lines,
        outside_recipe_blocks=non_recipe_blocks,
        updated_conversion_result=updated_result,
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
                decided_by=row.decided_by,
                reason_tags=list(row.reason_tags),
                escalation_reasons=list(row.escalation_reasons),
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
    location = {
        "start_block": span.start_block_index,
        "end_block": span.end_block_index,
        "chunk_index": recipe_index,
        "label_source": "label-first-v1",
        "recipe_span_id": span.span_id,
        "title_block_index": span.title_block_index,
    }
    provenance = provenance_builder.build(
        confidence_score=None,
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
    )
    return recipe


def _recipe_candidate_has_projected_body(recipe: RecipeCandidate) -> bool:
    ingredients = list(recipe.ingredients or [])
    instructions = list(recipe.instructions or [])
    if ingredients or instructions:
        return True
    if recipe.recipe_yield or recipe.prep_time or recipe.cook_time or recipe.total_time:
        return True
    return False


def _annotate_recipe_span_decision(
    decision: RecipeSpanDecision,
    *,
    warning: str | None = None,
    escalation_reason: str | None = None,
    decision_note: str | None = None,
) -> RecipeSpanDecision:
    warnings = list(decision.warnings)
    if warning and warning not in warnings:
        warnings.append(warning)
    escalation_reasons = list(decision.escalation_reasons)
    if escalation_reason and escalation_reason not in escalation_reasons:
        escalation_reasons.append(escalation_reason)
    decision_notes = list(decision.decision_notes)
    if decision_note and decision_note not in decision_notes:
        decision_notes.append(decision_note)
    return decision.model_copy(
        update={
            "warnings": warnings,
            "escalation_reasons": escalation_reasons,
            "decision_notes": decision_notes,
        }
    )


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
    resolved_blocks, _resolved_support = resolve_conversion_source_model(
        conversion_result,
        full_blocks=full_blocks,
    )
    return source_blocks_to_rows(resolved_blocks)


def _atomize_archive_blocks(
    archive_blocks: Sequence[dict[str, Any]],
    *,
    conversion_result: ConversionResult,
    atomic_block_splitter: str,
) -> list[AtomicLineCandidate]:
    del conversion_result
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
            within_recipe_span=None,
            atomic_block_splitter=atomic_block_splitter,
        )
        for candidate in atomized:
            staged.append(
                {
                    "recipe_id": candidate.recipe_id,
                    "block_id": candidate.block_id,
                    "block_index": candidate.block_index,
                    "text": candidate.text,
                    "within_recipe_span": candidate.within_recipe_span,
                    "rule_tags": list(candidate.rule_tags),
                }
            )

    output: list[AtomicLineCandidate] = []
    for atomic_index, row in enumerate(staged):
        output.append(
            AtomicLineCandidate(
                recipe_id=row["recipe_id"],
                block_id=str(row["block_id"]),
                block_index=int(row["block_index"]),
                atomic_index=atomic_index,
                text=str(row["text"]),
                within_recipe_span=row["within_recipe_span"],
                rule_tags=list(row["rule_tags"]),
            )
        )
    return output


def _build_authoritative_lines(
    *,
    authoritative_predictions: Sequence[CanonicalLineRolePrediction],
    deterministic_reference_predictions: Sequence[CanonicalLineRolePrediction],
) -> list[AuthoritativeLabeledLine]:
    deterministic_reference_by_atomic = {
        int(prediction.atomic_index): prediction
        for prediction in deterministic_reference_predictions
    }
    labeled_lines: list[AuthoritativeLabeledLine] = []
    for prediction in authoritative_predictions:
        deterministic_reference = deterministic_reference_by_atomic.get(
            int(prediction.atomic_index),
            prediction,
        )
        deterministic_label = _canonical_label(
            getattr(deterministic_reference, "label", "NONRECIPE_CANDIDATE")
        )
        final_label = _canonical_label(
            getattr(prediction, "label", "NONRECIPE_CANDIDATE")
        )
        labeled_lines.append(
            AuthoritativeLabeledLine(
                source_block_id=str(prediction.block_id),
                source_block_index=int(prediction.block_index or 0),
                atomic_index=int(prediction.atomic_index),
                text=str(prediction.text or ""),
                within_recipe_span_hint=prediction.within_recipe_span,
                deterministic_label=deterministic_label,
                final_label=final_label,
                decided_by=prediction.decided_by,
                reason_tags=list(prediction.reason_tags),
                escalation_reasons=list(prediction.escalation_reasons),
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
        supporting_rows = [row for row in rows if row.final_label == selected_final] or rows
        escalation_reasons = _unique_string_list(
            reason
            for row in rows
            for reason in row.escalation_reasons
        )
        reason_tags = _unique_string_list(
            tag
            for row in rows
            for tag in row.reason_tags
        )
        if len({row.final_label for row in rows}) > 1:
            escalation_reasons.append("mixed_block_labels")
        output.append(
            AuthoritativeBlockLabel(
                source_block_id=representative.source_block_id,
                source_block_index=block_index,
                supporting_atomic_indices=support,
                deterministic_label=selected_det,
                final_label=selected_final,
                decided_by=representative.decided_by,
                reason_tags=reason_tags,
                escalation_reasons=escalation_reasons,
            )
        )
    return output


def _select_block_label(
    rows: Sequence[AuthoritativeLabeledLine],
    *,
    field_name: Literal["deterministic_label", "final_label"],
) -> str:
    labels = [
        str(getattr(row, field_name) or "NONRECIPE_CANDIDATE") for row in rows
    ]
    for priority_label in _LABEL_RESOLUTION_PRIORITY:
        if priority_label in labels:
            return priority_label
    for label in labels:
        if label in CANONICAL_LINE_ROLE_ALLOWED_LABELS:
            return label
    return "NONRECIPE_CANDIDATE"


def _canonical_label(raw_label: Any) -> str:
    normalized = normalize_freeform_label(str(raw_label or "NONRECIPE_CANDIDATE"))
    if normalized not in CANONICAL_LINE_ROLE_ALLOWED_LABELS:
        return "NONRECIPE_CANDIDATE"
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
