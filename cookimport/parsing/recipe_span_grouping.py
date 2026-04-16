from __future__ import annotations

from typing import Sequence

from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    AuthoritativeLabeledLine,
    RecipeSpan,
    RecipeSpanDecision,
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
_SPAN_START_LABELS = {"RECIPE_TITLE"}
_TITLE_ANCHOR_LABELS = {"RECIPE_TITLE"}
_INGREDIENT_EVIDENCE_LABELS = {"INGREDIENT_LINE"}
_INSTRUCTION_EVIDENCE_LABELS = {"INSTRUCTION_LINE"}
_GAP_LABELS = {"NONRECIPE_CANDIDATE", "NONRECIPE_EXCLUDE"}
_MAX_GAP_BLOCKS = 2


def recipe_boundary_from_labels(
    block_labels: Sequence[AuthoritativeBlockLabel],
    labeled_lines: Sequence[AuthoritativeLabeledLine],
) -> tuple[list[RecipeSpan], list[RecipeSpanDecision], list[AuthoritativeBlockLabel]]:
    ordered_blocks = sorted(block_labels, key=lambda row: row.source_block_index)
    atomic_indices_by_block: dict[int, list[int]] = {}
    for row in labeled_lines:
        atomic_indices_by_block.setdefault(int(row.source_block_index), []).append(
            int(row.atomic_index)
        )

    spans: list[RecipeSpan] = []
    span_decisions: list[RecipeSpanDecision] = []
    pending: list[AuthoritativeBlockLabel] = []
    gap_blocks: list[AuthoritativeBlockLabel] = []

    def flush_pending(*, warning: str | None = None) -> None:
        nonlocal pending
        if not pending:
            return
        decision = _build_span_decision(
            span_index=len(span_decisions),
            block_rows=pending,
            atomic_indices_by_block=atomic_indices_by_block,
            warning=warning,
        )
        span_decisions.append(decision)
        if decision.decision == "accepted_recipe_span":
            spans.append(_decision_to_recipe_span(decision))
        pending = []

    for position, block in enumerate(ordered_blocks):
        label = str(block.final_label or "NONRECIPE_CANDIDATE")
        if label in _SPAN_START_LABELS:
            gap_blocks = []
            if pending:
                flush_pending()
            pending = [block]
            continue
        if gap_blocks and label in _RECIPE_LOCAL_LABELS:
            if _should_continue_after_gap(
                pending=pending,
                gap_blocks=gap_blocks,
                next_label=label,
            ):
                gap_blocks = []
                pending.append(block)
                continue
            if pending:
                flush_pending()
            gap_blocks = []
        if label in _RECIPE_LOCAL_LABELS:
            if not pending:
                pending = [block]
                continue
            pending.append(block)
            continue
        if _should_buffer_gap(
            pending=pending,
            gap_blocks=gap_blocks,
            current_label=label,
        ):
            gap_blocks.append(block)
            continue
        if pending:
            warning = None
            if pending and str(pending[0].final_label or "NONRECIPE_CANDIDATE") not in _SPAN_START_LABELS:
                warning = "recipe_span_started_without_title"
            flush_pending(warning=warning)
        gap_blocks = []

    if pending:
        warning = None
        if pending and str(pending[0].final_label or "NONRECIPE_CANDIDATE") not in _SPAN_START_LABELS:
            warning = "recipe_span_started_without_title"
        flush_pending(warning=warning)

    normalized_blocks = _normalize_recipe_boundary_block_labels(
        ordered_blocks=ordered_blocks,
        accepted_spans=spans,
    )
    return spans, span_decisions, normalized_blocks


def _build_span_decision(
    *,
    span_index: int,
    block_rows: Sequence[AuthoritativeBlockLabel],
    atomic_indices_by_block: dict[int, list[int]],
    warning: str | None,
) -> RecipeSpanDecision:
    source_block_indices = [int(row.source_block_index) for row in block_rows]
    source_block_ids = [str(row.source_block_id) for row in block_rows]
    row_indices: list[int] = []
    title_row_index: int | None = None
    title_source_block_index: int | None = None
    title_atomic_index: int | None = None
    warnings: list[str] = []
    escalation_reasons: list[str] = []
    decision_notes: list[str] = []

    for row in block_rows:
        block_row_indices = sorted(
            int(value) for value in atomic_indices_by_block.get(int(row.source_block_index), [])
        )
        row_indices.extend(block_row_indices)
        escalation_reasons.extend(row.escalation_reasons)
        if title_row_index is None and str(row.final_label or "NONRECIPE_CANDIDATE") in _TITLE_ANCHOR_LABELS:
            title_source_block_index = int(row.source_block_index)
            if block_row_indices:
                title_row_index = block_row_indices[0]
                title_atomic_index = block_row_indices[0]
            else:
                title_row_index = int(row.source_block_index)

    if warning:
        warnings.append(warning)
        escalation_reasons.append(warning)
        decision_notes.append(warning)
    has_title_anchor = _has_title_anchor(block_rows)
    missing_core_fields = _missing_required_recipe_fields(block_rows)
    rejection_reason: str | None = None
    if not has_title_anchor:
        warnings.append("recipe_span_missing_title_label")
        escalation_reasons.append("missing_required_recipe_fields")
        decision_notes.append("span_missing_title_block")
        rejection_reason = "rejected_missing_title_anchor"
    elif missing_core_fields:
        escalation_reasons.append("missing_required_recipe_fields")
        for field_name in missing_core_fields:
            warnings.append(f"recipe_span_missing_{field_name}_label")
            decision_notes.append(f"span_missing_{field_name}_block")
        rejection_reason = _rejection_reason_for_missing_core_fields(missing_core_fields)

    if title_source_block_index is not None:
        title_row = next(
            (
                row
                for row in block_rows
                if int(row.source_block_index) == title_source_block_index
            ),
            None,
        )
        if title_row is not None and "fallback_decision" in title_row.escalation_reasons:
            escalation_reasons.append("fallback_title_block")
            decision_notes.append("title_block_was_not_rule_held")

    row_indices = sorted(set(row_indices)) or list(source_block_indices)
    atomic_indices = list(row_indices)
    if rejection_reason is not None:
        decision_notes.append(rejection_reason)

    return RecipeSpanDecision(
        span_id=f"recipe_span_{span_index}",
        decision=(
            "accepted_recipe_span"
            if rejection_reason is None
            else "rejected_pseudo_recipe_span"
        ),
        rejection_reason=rejection_reason,
        start_row_index=min(row_indices),
        end_row_index=max(row_indices),
        row_indices=row_indices,
        source_block_ids=source_block_ids,
        start_atomic_index=atomic_indices[0] if atomic_indices else None,
        end_atomic_index=atomic_indices[-1] if atomic_indices else None,
        atomic_indices=atomic_indices,
        title_row_index=title_row_index,
        title_atomic_index=title_atomic_index,
        warnings=warnings,
        escalation_reasons=escalation_reasons,
        decision_notes=decision_notes,
    )


def _should_buffer_gap(
    *,
    pending: Sequence[AuthoritativeBlockLabel],
    gap_blocks: Sequence[AuthoritativeBlockLabel],
    current_label: str,
) -> bool:
    if not pending:
        return False
    if current_label not in _GAP_LABELS:
        return False
    if len(gap_blocks) >= _MAX_GAP_BLOCKS:
        return False
    if not _has_title_anchor(pending):
        return False
    return True


def _should_continue_after_gap(
    *,
    pending: Sequence[AuthoritativeBlockLabel],
    gap_blocks: Sequence[AuthoritativeBlockLabel],
    next_label: str,
) -> bool:
    if not pending or not gap_blocks:
        return False
    if len(gap_blocks) > _MAX_GAP_BLOCKS:
        return False
    if not _has_title_anchor(pending):
        return False
    return next_label in (_RECIPE_LOCAL_LABELS - _TITLE_ANCHOR_LABELS)


def _has_title_anchor(block_rows: Sequence[AuthoritativeBlockLabel]) -> bool:
    return any(
        str(row.final_label or "NONRECIPE_CANDIDATE") in _TITLE_ANCHOR_LABELS
        for row in block_rows
    )


def _missing_required_recipe_fields(
    block_rows: Sequence[AuthoritativeBlockLabel],
) -> list[str]:
    missing: list[str] = []
    if not _has_ingredient_evidence(block_rows):
        missing.append("ingredient")
    if not _has_instruction_evidence(block_rows):
        missing.append("instruction")
    return missing


def _has_ingredient_evidence(
    block_rows: Sequence[AuthoritativeBlockLabel],
) -> bool:
    return any(
        str(row.final_label or "NONRECIPE_CANDIDATE") in _INGREDIENT_EVIDENCE_LABELS
        for row in block_rows
    )


def _has_instruction_evidence(
    block_rows: Sequence[AuthoritativeBlockLabel],
) -> bool:
    return any(
        str(row.final_label or "NONRECIPE_CANDIDATE") in _INSTRUCTION_EVIDENCE_LABELS
        for row in block_rows
    )


def _rejection_reason_for_missing_core_fields(missing_core_fields: Sequence[str]) -> str:
    missing = tuple(missing_core_fields)
    if missing == ("ingredient",):
        return "rejected_missing_ingredient_evidence"
    if missing == ("instruction",):
        return "rejected_missing_instruction_evidence"
    return "rejected_missing_ingredient_and_instruction_evidence"

def _decision_to_recipe_span(decision: RecipeSpanDecision) -> RecipeSpan:
    payload = decision.model_dump(
        mode="json",
        exclude={"decision", "rejection_reason"},
    )
    return RecipeSpan.model_validate(payload)


def _normalize_recipe_boundary_block_labels(
    *,
    ordered_blocks: Sequence[AuthoritativeBlockLabel],
    accepted_spans: Sequence[RecipeSpan],
) -> list[AuthoritativeBlockLabel]:
    accepted_block_ids = {
        str(source_block_id)
        for span in accepted_spans
        for source_block_id in span.source_block_ids
    }
    normalized_blocks: list[AuthoritativeBlockLabel] = []
    for block in ordered_blocks:
        block_id = str(block.source_block_id)
        label = str(block.final_label or "NONRECIPE_CANDIDATE")
        if block_id in accepted_block_ids:
            if label in _RECIPE_LOCAL_LABELS:
                normalized_blocks.append(block)
                continue
            normalized_blocks.append(
                block.model_copy(
                    update={
                        "final_label": "RECIPE_NOTES",
                        "decided_by": "fallback",
                        "reason_tags": [
                            *list(block.reason_tags),
                            "accepted_recipe_span_nonrecipe_block_to_notes",
                        ],
                        "escalation_reasons": [
                            *list(block.escalation_reasons),
                            "accepted_recipe_span_nonrecipe_block_to_notes",
                        ],
                    }
                )
            )
            continue
        if label not in _RECIPE_LOCAL_LABELS:
            normalized_blocks.append(block)
            continue
        normalized_blocks.append(
            block.model_copy(
                update={
                    "final_label": "NONRECIPE_CANDIDATE",
                    "decided_by": "fallback",
                    "reason_tags": [*list(block.reason_tags), "recipe_span_rejected_to_route"],
                    "escalation_reasons": [
                        *list(block.escalation_reasons),
                        "recipe_span_rejected_to_route",
                    ],
                }
            )
        )
    return normalized_blocks
