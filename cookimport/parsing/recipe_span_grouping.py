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
_TITLE_LIKE_LABELS = {"RECIPE_TITLE", "RECIPE_VARIANT"}
_ACCEPTANCE_RECIPE_BODY_LABELS = {
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
}
_BRIDGEABLE_RECIPE_STRUCTURE_LABELS = _RECIPE_LOCAL_LABELS - _TITLE_LIKE_LABELS
_NONRECIPE_GAP_LABELS = {"KNOWLEDGE", "OTHER"}


def group_recipe_spans_from_labels(
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
        label = str(block.final_label or "OTHER")
        if label in _TITLE_LIKE_LABELS:
            if pending:
                flush_pending()
            pending = [block]
            continue
        if label in _RECIPE_LOCAL_LABELS:
            if not pending:
                pending = [block]
                continue
            pending.append(block)
            continue
        if _should_bridge_nonrecipe_gap(
            pending=pending,
            ordered_blocks=ordered_blocks,
            gap_position=position,
        ):
            pending.append(block)
            continue
        if pending:
            warning = None
            if pending and str(pending[0].final_label or "OTHER") not in _TITLE_LIKE_LABELS:
                warning = "recipe_span_started_without_title"
            flush_pending(warning=warning)

    if pending:
        warning = None
        if pending and str(pending[0].final_label or "OTHER") not in _TITLE_LIKE_LABELS:
            warning = "recipe_span_started_without_title"
        flush_pending(warning=warning)

    normalized_blocks = _normalize_nonaccepted_recipe_local_block_labels(
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
    block_indices = [int(row.source_block_index) for row in block_rows]
    source_block_ids = [str(row.source_block_id) for row in block_rows]
    atomic_indices: list[int] = []
    title_block_index: int | None = None
    title_atomic_index: int | None = None
    warnings: list[str] = []
    escalation_reasons: list[str] = []
    decision_notes: list[str] = []

    for row in block_rows:
        block_atomic_indices = sorted(
            int(value) for value in atomic_indices_by_block.get(int(row.source_block_index), [])
        )
        atomic_indices.extend(block_atomic_indices)
        escalation_reasons.extend(row.escalation_reasons)
        if title_block_index is None and str(row.final_label or "OTHER") in _TITLE_LIKE_LABELS:
            title_block_index = int(row.source_block_index)
            if block_atomic_indices:
                title_atomic_index = block_atomic_indices[0]

    if warning:
        warnings.append(warning)
        escalation_reasons.append(warning)
        decision_notes.append(warning)
    has_title_anchor = _has_title_anchor(block_rows)
    has_acceptance_recipe_body = _has_acceptance_recipe_body(block_rows)
    rejection_reason: str | None = None
    if not has_title_anchor:
        warnings.append("recipe_span_missing_title_label")
        escalation_reasons.append("missing_required_recipe_fields")
        decision_notes.append("span_missing_title_block")
        rejection_reason = "rejected_missing_title_anchor"
    elif not has_acceptance_recipe_body:
        warnings.append("recipe_span_missing_recipe_body")
        escalation_reasons.append("missing_required_recipe_fields")
        decision_notes.append("span_missing_recipe_body")
        rejection_reason = "rejected_missing_recipe_body"

    if title_block_index is not None:
        title_row = next(
            (
                row
                for row in block_rows
                if int(row.source_block_index) == int(title_block_index)
            ),
            None,
        )
        if title_row is not None and "fallback_decision" in title_row.escalation_reasons:
            escalation_reasons.append("fallback_title_block")
            decision_notes.append("title_block_was_not_rule_held")

    atomic_indices = sorted(set(atomic_indices))
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
        start_block_index=min(block_indices),
        end_block_index=max(block_indices),
        block_indices=block_indices,
        source_block_ids=source_block_ids,
        start_atomic_index=atomic_indices[0] if atomic_indices else None,
        end_atomic_index=atomic_indices[-1] if atomic_indices else None,
        atomic_indices=atomic_indices,
        title_block_index=title_block_index,
        title_atomic_index=title_atomic_index,
        warnings=warnings,
        escalation_reasons=escalation_reasons,
        decision_notes=decision_notes,
    )


def _should_bridge_nonrecipe_gap(
    *,
    pending: Sequence[AuthoritativeBlockLabel],
    ordered_blocks: Sequence[AuthoritativeBlockLabel],
    gap_position: int,
) -> bool:
    if not pending:
        return False
    if gap_position < 0 or gap_position >= len(ordered_blocks):
        return False
    if not _has_title_anchor(pending):
        return False
    if not _has_bridgeable_recipe_structure(pending):
        return False

    current_label = str(ordered_blocks[gap_position].final_label or "OTHER")
    if current_label not in _NONRECIPE_GAP_LABELS:
        return False

    next_position = gap_position + 1
    if next_position >= len(ordered_blocks):
        return False
    next_label = str(ordered_blocks[next_position].final_label or "OTHER")
    return next_label in _ACCEPTANCE_RECIPE_BODY_LABELS


def _has_title_anchor(block_rows: Sequence[AuthoritativeBlockLabel]) -> bool:
    return any(str(row.final_label or "OTHER") in _TITLE_LIKE_LABELS for row in block_rows)


def _has_acceptance_recipe_body(
    block_rows: Sequence[AuthoritativeBlockLabel],
) -> bool:
    return any(
        str(row.final_label or "OTHER") in _ACCEPTANCE_RECIPE_BODY_LABELS
        for row in block_rows
    )


def _has_bridgeable_recipe_structure(
    block_rows: Sequence[AuthoritativeBlockLabel],
) -> bool:
    return any(
        str(row.final_label or "OTHER") in _BRIDGEABLE_RECIPE_STRUCTURE_LABELS
        for row in block_rows
    )


def _decision_to_recipe_span(decision: RecipeSpanDecision) -> RecipeSpan:
    payload = decision.model_dump(
        mode="json",
        exclude={"decision", "rejection_reason"},
    )
    return RecipeSpan.model_validate(payload)


def _normalize_nonaccepted_recipe_local_block_labels(
    *,
    ordered_blocks: Sequence[AuthoritativeBlockLabel],
    accepted_spans: Sequence[RecipeSpan],
) -> list[AuthoritativeBlockLabel]:
    accepted_block_indices = {
        int(block_index)
        for span in accepted_spans
        for block_index in span.block_indices
    }
    normalized_blocks: list[AuthoritativeBlockLabel] = []
    for block in ordered_blocks:
        block_index = int(block.source_block_index)
        label = str(block.final_label or "OTHER")
        if block_index in accepted_block_indices or label not in _RECIPE_LOCAL_LABELS:
            normalized_blocks.append(block)
            continue
        normalized_blocks.append(
            block.model_copy(
                update={
                    "final_label": "OTHER",
                    "decided_by": "fallback",
                    "reason_tags": [*list(block.reason_tags), "recipe_span_rejected_to_other"],
                    "escalation_reasons": [
                        *list(block.escalation_reasons),
                        "recipe_span_rejected_to_other",
                    ],
                    "review_exclusion_reason": None,
                }
            )
        )
    return normalized_blocks
