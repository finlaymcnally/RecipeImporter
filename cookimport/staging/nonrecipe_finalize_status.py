from __future__ import annotations

from typing import Any, Mapping, Sequence

from .nonrecipe_authority_contract import NonRecipeCandidateStatusResult
from .nonrecipe_seed import build_nonrecipe_spans_from_categories


def build_nonrecipe_finalize_status_result(
    *,
    full_rows_by_index: Mapping[int, Mapping[str, Any]],
    candidate_row_indices: Sequence[int],
    authoritative_row_indices: Sequence[int],
    excluded_row_indices: Sequence[int],
) -> NonRecipeCandidateStatusResult:
    authoritative_index_set = {int(index) for index in authoritative_row_indices}
    excluded_index_set = {int(index) for index in excluded_row_indices}
    finalized_candidate_row_indices = sorted(
        int(index)
        for index in authoritative_index_set
        if int(index) not in excluded_index_set
    )
    unresolved_candidate_row_indices = [
        int(index)
        for index in candidate_row_indices
        if int(index) not in authoritative_index_set
    ]
    unresolved_candidate_route_by_index = {
        int(index): "candidate" for index in unresolved_candidate_row_indices
    }
    unresolved_candidate_spans = build_nonrecipe_spans_from_categories(
        full_rows_by_index=full_rows_by_index,
        row_category_by_index=unresolved_candidate_route_by_index,
    )
    return NonRecipeCandidateStatusResult(
        finalized_candidate_row_indices=finalized_candidate_row_indices,
        unresolved_candidate_row_indices=unresolved_candidate_row_indices,
        unresolved_candidate_route_by_index=unresolved_candidate_route_by_index,
        unresolved_candidate_spans=unresolved_candidate_spans,
    )
