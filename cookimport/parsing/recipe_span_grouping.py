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

    for row in block_rows:
        block_atomic_indices = sorted(
            int(value) for value in atomic_indices_by_block.get(int(row.source_block_index), [])
        )
        atomic_indices.extend(block_atomic_indices)
        if title_block_index is None and str(row.final_label or "OTHER") in _TITLE_LIKE_LABELS:
            title_block_index = int(row.source_block_index)
            if block_atomic_indices:
                title_atomic_index = block_atomic_indices[0]

    if warning:
        warnings.append(warning)
    if not any(str(row.final_label or "OTHER") in _TITLE_LIKE_LABELS for row in block_rows):
        warnings.append("recipe_span_missing_title_label")

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
    )
