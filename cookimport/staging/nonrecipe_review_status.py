from __future__ import annotations

from typing import Any, Mapping, Sequence

from .nonrecipe_authority_contract import NonRecipeCandidateStatusResult
from .nonrecipe_seed import build_nonrecipe_spans_from_categories


def build_nonrecipe_finalize_status_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    candidate_block_indices: Sequence[int],
    authoritative_block_indices: Sequence[int],
    excluded_block_indices: Sequence[int],
) -> NonRecipeCandidateStatusResult:
    authoritative_index_set = {int(index) for index in authoritative_block_indices}
    excluded_index_set = {int(index) for index in excluded_block_indices}
    finalized_candidate_block_indices = sorted(
        int(index)
        for index in authoritative_index_set
        if int(index) not in excluded_index_set
    )
    unresolved_candidate_block_indices = [
        int(index)
        for index in candidate_block_indices
        if int(index) not in authoritative_index_set
    ]
    unresolved_candidate_route_by_index = {
        int(index): "candidate" for index in unresolved_candidate_block_indices
    }
    unresolved_candidate_spans = build_nonrecipe_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=unresolved_candidate_route_by_index,
    )
    return NonRecipeCandidateStatusResult(
        finalized_candidate_block_indices=finalized_candidate_block_indices,
        unresolved_candidate_block_indices=unresolved_candidate_block_indices,
        unresolved_candidate_route_by_index=unresolved_candidate_route_by_index,
        unresolved_candidate_spans=unresolved_candidate_spans,
    )
