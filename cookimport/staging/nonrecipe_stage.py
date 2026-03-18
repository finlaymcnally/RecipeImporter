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
    seed_nonrecipe_spans: list[NonRecipeSpan] | None = None
    seed_knowledge_spans: list[NonRecipeSpan] | None = None
    seed_other_spans: list[NonRecipeSpan] | None = None
    seed_block_category_by_index: dict[int, str] | None = None
    refinement_report: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seed_nonrecipe_spans is None:
            object.__setattr__(self, "seed_nonrecipe_spans", list(self.nonrecipe_spans))
        if self.seed_knowledge_spans is None:
            object.__setattr__(self, "seed_knowledge_spans", list(self.knowledge_spans))
        if self.seed_other_spans is None:
            object.__setattr__(self, "seed_other_spans", list(self.other_spans))
        if self.seed_block_category_by_index is None:
            object.__setattr__(
                self,
                "seed_block_category_by_index",
                dict(self.block_category_by_index),
            )
        if not self.refinement_report:
            object.__setattr__(
                self,
                "refinement_report",
                {
                    "enabled": False,
                    "authority_mode": "deterministic_seed_only",
                    "input_mode": "stage7_seed_nonrecipe_spans",
                    "seed_nonrecipe_span_count": len(self.seed_nonrecipe_spans or []),
                    "final_nonrecipe_span_count": len(self.nonrecipe_spans),
                    "changed_block_count": 0,
                    "reviewed_block_count": 0,
                    "reviewer_category_counts": {},
                    "changed_blocks": [],
                    "conflicts": [],
                    "ignored_block_indices": [],
                    "scored_effect": "seed_only",
                },
            )


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

    for block_index in sorted(full_blocks_by_index):
        if block_index in recipe_block_indices:
            continue

        category, warning = _normalize_stage7_category(labels_by_index.get(block_index))
        if warning is not None:
            warnings.append(f"block {block_index}: {warning}")
        block_category_by_index[block_index] = category

    spans, knowledge_spans, other_spans = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=block_category_by_index,
    )
    return NonRecipeStageResult(
        nonrecipe_spans=spans,
        knowledge_spans=knowledge_spans,
        other_spans=other_spans,
        block_category_by_index=block_category_by_index,
        warnings=warnings,
    )


def refine_nonrecipe_stage_result(
    *,
    stage_result: NonRecipeStageResult,
    full_blocks: Sequence[Mapping[str, Any]],
    block_category_updates: Mapping[int, str],
    reviewer_categories_by_block: Mapping[int, str] | None = None,
    applied_chunk_ids_by_block: Mapping[int, Sequence[str]] | None = None,
    conflicts: Sequence[Mapping[str, Any]] | None = None,
    ignored_block_indices: Sequence[int] | None = None,
) -> NonRecipeStageResult:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    seed_block_category_by_index = dict(
        stage_result.seed_block_category_by_index or stage_result.block_category_by_index
    )
    final_block_category_by_index = dict(seed_block_category_by_index)
    changed_blocks: list[dict[str, Any]] = []
    warnings = list(stage_result.warnings)
    reviewer_counts: dict[str, int] = {}

    for block_index, raw_category in sorted(block_category_updates.items()):
        normalized_category, warning = _normalize_stage7_category(str(raw_category))
        reviewer_category = str(
            (reviewer_categories_by_block or {}).get(block_index) or ""
        ).strip() or None
        if block_index not in final_block_category_by_index:
            if warning is not None:
                warnings.append(f"block {block_index}: {warning}")
            continue
        if warning is not None:
            warnings.append(f"block {block_index}: {warning}")
        seed_category = seed_block_category_by_index[block_index]
        final_block_category_by_index[block_index] = normalized_category
        if reviewer_category is not None:
            reviewer_counts[reviewer_category] = reviewer_counts.get(reviewer_category, 0) + 1
        if normalized_category == seed_category:
            continue
        changed_blocks.append(
            {
                "block_index": int(block_index),
                "seed_category": seed_category,
                "final_category": normalized_category,
                "reviewer_category": reviewer_category,
                "applied_chunk_ids": list(applied_chunk_ids_by_block.get(block_index) or [])
                if applied_chunk_ids_by_block is not None
                else [],
            }
        )

    spans, knowledge_spans, other_spans = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=final_block_category_by_index,
    )
    conflict_rows = [dict(row) for row in (conflicts or [])]
    ignored_indices = sorted({int(index) for index in (ignored_block_indices or [])})
    return NonRecipeStageResult(
        nonrecipe_spans=spans,
        knowledge_spans=knowledge_spans,
        other_spans=other_spans,
        block_category_by_index=final_block_category_by_index,
        warnings=warnings,
        seed_nonrecipe_spans=list(stage_result.seed_nonrecipe_spans or stage_result.nonrecipe_spans),
        seed_knowledge_spans=list(stage_result.seed_knowledge_spans or stage_result.knowledge_spans),
        seed_other_spans=list(stage_result.seed_other_spans or stage_result.other_spans),
        seed_block_category_by_index=seed_block_category_by_index,
        refinement_report={
            "enabled": True,
            "authority_mode": (
                "knowledge_refined_final"
                if changed_blocks
                else "knowledge_reviewed_seed_kept"
            ),
            "input_mode": "stage7_seed_nonrecipe_spans",
            "seed_nonrecipe_span_count": len(stage_result.seed_nonrecipe_spans or stage_result.nonrecipe_spans),
            "final_nonrecipe_span_count": len(spans),
            "seed_knowledge_span_count": len(stage_result.seed_knowledge_spans or stage_result.knowledge_spans),
            "final_knowledge_span_count": len(knowledge_spans),
            "changed_block_count": len(changed_blocks),
            "reviewed_block_count": sum(reviewer_counts.values()),
            "reviewer_category_counts": reviewer_counts,
            "changed_blocks": changed_blocks,
            "conflicts": conflict_rows,
            "ignored_block_indices": ignored_indices,
            "scored_effect": "final_authority" if changed_blocks else "seed_only",
        },
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


def _build_spans_from_categories(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_category_by_index: Mapping[int, str],
) -> tuple[list[NonRecipeSpan], list[NonRecipeSpan], list[NonRecipeSpan]]:
    spans: list[NonRecipeSpan] = []
    current_indices: list[int] = []
    current_block_ids: list[str] = []
    current_category: str | None = None
    previous_index: int | None = None

    for block_index in sorted(block_category_by_index):
        category = str(block_category_by_index[block_index] or "other")
        block_payload = full_blocks_by_index.get(int(block_index), {})
        block_id = str(block_payload.get("block_id") or f"b{block_index}")
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
            current_indices = [int(block_index)]
            current_block_ids = [block_id]
            current_category = category
            previous_index = int(block_index)
            continue

        current_indices.append(int(block_index))
        current_block_ids.append(block_id)
        previous_index = int(block_index)

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
    return spans, knowledge_spans, other_spans
