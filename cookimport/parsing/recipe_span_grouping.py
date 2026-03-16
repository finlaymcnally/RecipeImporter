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

    for block in ordered_blocks:
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

    return spans, span_decisions, ordered_blocks


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
    has_title_anchor = any(
        str(row.final_label or "OTHER") in _TITLE_LIKE_LABELS for row in block_rows
    )
    if not has_title_anchor:
        warnings.append("recipe_span_missing_title_label")
        escalation_reasons.append("missing_required_recipe_fields")
        decision_notes.append("span_missing_title_block")

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
    rejection_reason = None if has_title_anchor else "rejected_missing_title_anchor"
    if rejection_reason is not None:
        decision_notes.append(rejection_reason)

    return RecipeSpanDecision(
        span_id=f"recipe_span_{span_index}",
        decision=(
            "accepted_recipe_span"
            if has_title_anchor
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


def _decision_to_recipe_span(decision: RecipeSpanDecision) -> RecipeSpan:
    payload = decision.model_dump(
        mode="json",
        exclude={"decision", "rejection_reason"},
    )
    return RecipeSpan.model_validate(payload)
