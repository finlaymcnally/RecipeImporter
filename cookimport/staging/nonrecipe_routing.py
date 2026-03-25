from __future__ import annotations

from typing import Any, Mapping, Sequence

from .nonrecipe_authority_contract import NonRecipeRoutingResult
from .nonrecipe_seed import build_nonrecipe_spans_from_categories

_REVIEW_CANDIDATE_CATEGORY = "review_candidate"


def build_nonrecipe_routing_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    review_eligible_block_indices: Sequence[int],
    review_excluded_block_indices: Sequence[int],
    review_exclusion_reason_by_block: Mapping[int, str],
    block_preview_by_index: Mapping[int, str],
    warnings: Sequence[str],
) -> NonRecipeRoutingResult:
    review_eligible_nonrecipe_spans, _, _ = build_nonrecipe_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index={
            int(index): _REVIEW_CANDIDATE_CATEGORY
            for index in sorted(review_eligible_block_indices)
        },
    )
    _, _, review_excluded_other_spans = build_nonrecipe_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index={
            int(index): "other"
            for index in sorted(review_excluded_block_indices)
        },
    )
    review_routing_by_block = {
        **{
            int(index): "review_eligible"
            for index in sorted(review_eligible_block_indices)
        },
        **{
            int(index): "excluded_other"
            for index in sorted(review_excluded_block_indices)
        },
    }
    return NonRecipeRoutingResult(
        review_routing_by_block=review_routing_by_block,
        review_eligible_nonrecipe_spans=review_eligible_nonrecipe_spans,
        review_excluded_other_spans=review_excluded_other_spans,
        review_eligible_block_indices=[int(index) for index in review_eligible_block_indices],
        review_excluded_block_indices=[int(index) for index in review_excluded_block_indices],
        review_exclusion_reason_by_block={
            int(index): str(reason)
            for index, reason in review_exclusion_reason_by_block.items()
        },
        block_preview_by_index={
            int(index): str(preview)
            for index, preview in block_preview_by_index.items()
        },
        warnings=[str(warning) for warning in warnings],
    )
