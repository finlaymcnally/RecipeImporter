from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    RecipeSpan,
)

_OTHER_LABELS = {
    "other",
    "boilerplate",
    "toc",
    "front_matter",
    "front-matter",
    "endorsement",
    "navigation",
    "marketing",
    "chapter_heading",
    "chapter-heading",
}


@dataclass(frozen=True, slots=True)
class NonRecipeSpan:
    span_id: str
    category: str
    block_start_index: int
    block_end_index: int
    block_indices: list[int]
    block_ids: list[str]


@dataclass(frozen=True, slots=True)
class NonRecipeStageResult:
    nonrecipe_spans: list[NonRecipeSpan]
    knowledge_spans: list[NonRecipeSpan]
    other_spans: list[NonRecipeSpan]
    block_category_by_index: dict[int, str]
    warnings: list[str] = field(default_factory=list)


def build_nonrecipe_stage_result(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    final_block_labels: Sequence[AuthoritativeBlockLabel],
    recipe_spans: Sequence[RecipeSpan],
    overrides: Any | None = None,
) -> NonRecipeStageResult:
    del overrides

    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    recipe_block_indices = {
        int(block_index)
        for span in recipe_spans
        for block_index in span.block_indices
    }
    labels_by_index = {
        int(row.source_block_index): str(row.final_label or "").strip()
        for row in final_block_labels
    }

    block_category_by_index: dict[int, str] = {}
    warnings: list[str] = []
    spans: list[NonRecipeSpan] = []
    current_indices: list[int] = []
    current_block_ids: list[str] = []
    current_category: str | None = None
    previous_index: int | None = None

    for block_index in sorted(full_blocks_by_index):
        if block_index in recipe_block_indices:
            if current_category is not None and current_indices:
                spans.append(
                    _build_span(
                        category=current_category,
                        block_indices=current_indices,
                        block_ids=current_block_ids,
                    )
                )
            current_indices = []
            current_block_ids = []
            current_category = None
            previous_index = None
            continue

        category, warning = _normalize_stage7_category(labels_by_index.get(block_index))
        if warning is not None:
            warnings.append(f"block {block_index}: {warning}")
        block_category_by_index[block_index] = category

        block_id = str(full_blocks_by_index[block_index].get("block_id") or f"b{block_index}")
        if (
            current_category is None
            or previous_index is None
            or block_index != previous_index + 1
            or category != current_category
        ):
            if current_category is not None and current_indices:
                spans.append(
                    _build_span(
                        category=current_category,
                        block_indices=current_indices,
                        block_ids=current_block_ids,
                    )
                )
            current_indices = [block_index]
            current_block_ids = [block_id]
            current_category = category
            previous_index = block_index
            continue

        current_indices.append(block_index)
        current_block_ids.append(block_id)
        previous_index = block_index

    if current_category is not None and current_indices:
        spans.append(
            _build_span(
                category=current_category,
                block_indices=current_indices,
                block_ids=current_block_ids,
            )
        )

    knowledge_spans = [span for span in spans if span.category == "knowledge"]
    other_spans = [span for span in spans if span.category == "other"]
    return NonRecipeStageResult(
        nonrecipe_spans=spans,
        knowledge_spans=knowledge_spans,
        other_spans=other_spans,
        block_category_by_index=block_category_by_index,
        warnings=warnings,
    )


def block_rows_for_nonrecipe_stage(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    rows: list[dict[str, Any]] = []
    for block_index in sorted(stage_result.block_category_by_index):
        block = full_blocks_by_index.get(int(block_index))
        if block is None:
            continue
        payload = dict(block)
        payload["index"] = int(block_index)
        payload["stage7_category"] = stage_result.block_category_by_index[int(block_index)]
        rows.append(payload)
    return rows


def block_rows_for_nonrecipe_span(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    span: NonRecipeSpan,
) -> list[dict[str, Any]]:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    rows: list[dict[str, Any]] = []
    for block_index in span.block_indices:
        block = full_blocks_by_index.get(int(block_index))
        if block is None:
            continue
        payload = dict(block)
        payload["index"] = int(block_index)
        payload["stage7_category"] = span.category
        rows.append(payload)
    return rows


def _prepare_full_blocks_by_index(
    blocks: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    prepared: dict[int, dict[str, Any]] = {}
    for raw_block in blocks:
        if not isinstance(raw_block, Mapping):
            continue
        try:
            block_index = int(raw_block.get("index"))
        except (TypeError, ValueError):
            continue
        payload = dict(raw_block)
        payload["index"] = block_index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{block_index}"
        payload["block_id"] = block_id.strip()
        prepared[block_index] = payload
    return prepared


def _normalize_stage7_category(raw_label: str | None) -> tuple[str, str | None]:
    normalized = str(raw_label or "").strip().lower()
    if normalized == "knowledge":
        return "knowledge", None
    if normalized in _OTHER_LABELS:
        return "other", None
    if not normalized:
        return "other", "missing final label mapped to Stage 7 other"
    return "other", f"unexpected final label '{raw_label}' mapped to Stage 7 other"


def _build_span(
    *,
    category: str,
    block_indices: list[int],
    block_ids: list[str],
) -> NonRecipeSpan:
    start = int(block_indices[0])
    end = int(block_indices[-1]) + 1
    return NonRecipeSpan(
        span_id=f"nr.{category}.{start}.{end}",
        category=category,
        block_start_index=start,
        block_end_index=end,
        block_indices=list(block_indices),
        block_ids=list(block_ids),
    )
