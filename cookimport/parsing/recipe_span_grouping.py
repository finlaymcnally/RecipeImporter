from __future__ import annotations

from typing import Sequence

from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    AuthoritativeLabeledLine,
    RecipeSpan,
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
) -> tuple[list[RecipeSpan], list[AuthoritativeBlockLabel]]:
    ordered_blocks = sorted(block_labels, key=lambda row: row.source_block_index)
    atomic_indices_by_block: dict[int, list[int]] = {}
    for row in labeled_lines:
        atomic_indices_by_block.setdefault(int(row.source_block_index), []).append(
            int(row.atomic_index)
        )

    spans: list[RecipeSpan] = []
    pending: list[AuthoritativeBlockLabel] = []

    def flush_pending(*, warning: str | None = None) -> None:
        nonlocal pending
        if not pending:
            return
        spans.append(
            _build_span(
                span_index=len(spans),
                block_rows=pending,
                atomic_indices_by_block=atomic_indices_by_block,
                warning=warning,
            )
        )
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

    return spans, ordered_blocks


def _build_span(
    *,
    span_index: int,
    block_rows: Sequence[AuthoritativeBlockLabel],
    atomic_indices_by_block: dict[int, list[int]],
    warning: str | None,
) -> RecipeSpan:
    block_indices = [int(row.source_block_index) for row in block_rows]
    source_block_ids = [str(row.source_block_id) for row in block_rows]
    atomic_indices: list[int] = []
    title_block_index: int | None = None
    title_atomic_index: int | None = None
    warnings: list[str] = []
    block_trust_scores: list[float] = []
    block_escalation_scores: list[float] = []
    escalation_reasons: list[str] = []
    decision_notes: list[str] = []

    for row in block_rows:
        block_atomic_indices = sorted(
            int(value) for value in atomic_indices_by_block.get(int(row.source_block_index), [])
        )
        atomic_indices.extend(block_atomic_indices)
        if row.trust_score is not None:
            block_trust_scores.append(float(row.trust_score))
        if row.escalation_score is not None:
            block_escalation_scores.append(float(row.escalation_score))
        escalation_reasons.extend(row.escalation_reasons)
        if title_block_index is None and str(row.final_label or "OTHER") in _TITLE_LIKE_LABELS:
            title_block_index = int(row.source_block_index)
            if block_atomic_indices:
                title_atomic_index = block_atomic_indices[0]

    if warning:
        warnings.append(warning)
        escalation_reasons.append(warning)
        decision_notes.append(warning)
    if not any(str(row.final_label or "OTHER") in _TITLE_LIKE_LABELS for row in block_rows):
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
        if title_row is not None and title_row.trust_score is not None and float(title_row.trust_score) < 0.9:
            escalation_reasons.append("low_trust_title_block")
            decision_notes.append("title_block_trust_below_rule_hold")
            block_escalation_scores.append(max(float(title_row.escalation_score or 0.0), 0.8))

    atomic_indices = sorted(set(atomic_indices))
    return RecipeSpan(
        span_id=f"recipe_span_{span_index}",
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
        trust_score=min(block_trust_scores) if block_trust_scores else None,
        escalation_score=max(block_escalation_scores) if block_escalation_scores else None,
        escalation_reasons=escalation_reasons,
        decision_notes=decision_notes,
    )
