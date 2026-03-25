from __future__ import annotations

from typing import Any, Mapping, Sequence

from .nonrecipe_authority_contract import NonRecipeReviewStatusResult
from .nonrecipe_seed import build_nonrecipe_spans_from_categories


def build_nonrecipe_review_status_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_category_by_index: Mapping[int, str],
    review_eligible_block_indices: Sequence[int],
    authoritative_block_indices: Sequence[int],
    review_excluded_block_indices: Sequence[int],
) -> NonRecipeReviewStatusResult:
    authoritative_index_set = {int(index) for index in authoritative_block_indices}
    review_excluded_index_set = {int(index) for index in review_excluded_block_indices}
    reviewed_block_indices = sorted(
        int(index)
        for index in authoritative_index_set
        if int(index) not in review_excluded_index_set
    )
    unreviewed_review_eligible_block_indices = [
        int(index)
        for index in review_eligible_block_indices
        if int(index) not in authoritative_index_set
    ]
    unreviewed_block_category_by_index = {
        int(index): str(block_category_by_index[int(index)])
        for index in unreviewed_review_eligible_block_indices
        if int(index) in block_category_by_index
    }
    unreviewed_spans, _, _ = build_nonrecipe_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=unreviewed_block_category_by_index,
    )
    return NonRecipeReviewStatusResult(
        reviewed_block_indices=reviewed_block_indices,
        unreviewed_review_eligible_block_indices=unreviewed_review_eligible_block_indices,
        unreviewed_block_category_by_index=unreviewed_block_category_by_index,
        unreviewed_spans=unreviewed_spans,
    )
