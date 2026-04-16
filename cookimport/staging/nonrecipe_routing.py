from __future__ import annotations

from typing import Any, Mapping, Sequence

from .nonrecipe_authority_contract import NonRecipeRoutingResult
from .nonrecipe_seed import build_nonrecipe_spans_from_categories


def build_nonrecipe_routing_result(
    *,
    full_rows_by_index: Mapping[int, Mapping[str, Any]],
    candidate_row_indices: Sequence[int],
    excluded_row_indices: Sequence[int],
    row_preview_by_index: Mapping[int, str],
    warnings: Sequence[str],
) -> NonRecipeRoutingResult:
    candidate_nonrecipe_spans = build_nonrecipe_spans_from_categories(
        full_rows_by_index=full_rows_by_index,
        row_category_by_index={
            int(index): "candidate" for index in sorted(candidate_row_indices)
        },
    )
    excluded_nonrecipe_spans = build_nonrecipe_spans_from_categories(
        full_rows_by_index=full_rows_by_index,
        row_category_by_index={
            int(index): "exclude" for index in sorted(excluded_row_indices)
        },
    )
    route_by_row = {
        **{int(index): "candidate" for index in sorted(candidate_row_indices)},
        **{int(index): "exclude" for index in sorted(excluded_row_indices)},
    }
    return NonRecipeRoutingResult(
        route_by_row=route_by_row,
        candidate_nonrecipe_spans=candidate_nonrecipe_spans,
        excluded_nonrecipe_spans=excluded_nonrecipe_spans,
        candidate_row_indices=[int(index) for index in candidate_row_indices],
        excluded_row_indices=[int(index) for index in excluded_row_indices],
        row_preview_by_index={
            int(index): str(preview)
            for index, preview in row_preview_by_index.items()
        },
        warnings=[str(warning) for warning in warnings],
    )
