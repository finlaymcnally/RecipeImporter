from __future__ import annotations

from typing import Any, Mapping, Sequence

from .nonrecipe_authority_contract import NonRecipeRoutingResult
from .nonrecipe_seed import build_nonrecipe_spans_from_categories


def build_nonrecipe_routing_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    candidate_block_indices: Sequence[int],
    excluded_block_indices: Sequence[int],
    block_preview_by_index: Mapping[int, str],
    warnings: Sequence[str],
) -> NonRecipeRoutingResult:
    candidate_nonrecipe_spans = build_nonrecipe_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index={
            int(index): "candidate" for index in sorted(candidate_block_indices)
        },
    )
    excluded_nonrecipe_spans = build_nonrecipe_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index={
            int(index): "exclude" for index in sorted(excluded_block_indices)
        },
    )
    route_by_block = {
        **{int(index): "candidate" for index in sorted(candidate_block_indices)},
        **{int(index): "exclude" for index in sorted(excluded_block_indices)},
    }
    return NonRecipeRoutingResult(
        route_by_block=route_by_block,
        candidate_nonrecipe_spans=candidate_nonrecipe_spans,
        excluded_nonrecipe_spans=excluded_nonrecipe_spans,
        candidate_block_indices=[int(index) for index in candidate_block_indices],
        excluded_block_indices=[int(index) for index in excluded_block_indices],
        block_preview_by_index={
            int(index): str(preview)
            for index, preview in block_preview_by_index.items()
        },
        warnings=[str(warning) for warning in warnings],
    )
