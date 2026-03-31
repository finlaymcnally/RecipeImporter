from __future__ import annotations

from typing import Any, Mapping, Sequence

from .nonrecipe_authority_contract import (
    NonRecipeAuthorityContract,
    NonRecipeAuthorityResult,
    NonRecipeScoringView,
    NonRecipeSpan,
    NonRecipeStageResult,
)
from .nonrecipe_seed import (
    build_nonrecipe_spans_from_categories,
    prepare_nonrecipe_full_blocks_by_index,
)


def build_nonrecipe_authority_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_category_by_index: Mapping[int, str],
    authoritative_block_indices: Sequence[int],
    excluded_block_indices: Sequence[int] | None = None,
) -> NonRecipeAuthorityResult:
    excluded_index_set = {
        int(index) for index in (excluded_block_indices or ()) if int(index) in full_blocks_by_index
    }
    authoritative_index_set = {
        int(index) for index in authoritative_block_indices if int(index) in full_blocks_by_index
    }
    authoritative_index_set.update(excluded_index_set)
    authoritative_block_category_by_index = {
        int(index): (
            "other"
            if int(index) in excluded_index_set
            else str(block_category_by_index[int(index)])
        )
        for index in sorted(authoritative_index_set)
        if int(index) in excluded_index_set or int(index) in block_category_by_index
    }
    authoritative_nonrecipe_spans = build_nonrecipe_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=authoritative_block_category_by_index,
    )
    return NonRecipeAuthorityResult(
        authoritative_block_indices=sorted(authoritative_block_category_by_index),
        authoritative_block_category_by_index=authoritative_block_category_by_index,
        authoritative_nonrecipe_spans=authoritative_nonrecipe_spans,
        authoritative_knowledge_spans=[
            span for span in authoritative_nonrecipe_spans if span.category == "knowledge"
        ],
        authoritative_other_spans=[
            span for span in authoritative_nonrecipe_spans if span.category == "other"
        ],
    )


def _block_rows_for_indices(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_indices: Sequence[int],
    block_category_by_index: Mapping[int, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_index in block_indices:
        block_index = int(raw_index)
        block = full_blocks_by_index.get(block_index)
        if block is None:
            continue
        payload = dict(block)
        payload["index"] = block_index
        if block_index in block_category_by_index:
            payload["nonrecipe_final_category"] = str(block_category_by_index[block_index])
        rows.append(payload)
    return rows


def build_nonrecipe_authority_contract(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> NonRecipeAuthorityContract:
    full_blocks_by_index = prepare_nonrecipe_full_blocks_by_index(full_blocks)
    final_blocks = _block_rows_for_indices(
        full_blocks_by_index=full_blocks_by_index,
        block_indices=stage_result.authority.authoritative_block_indices,
        block_category_by_index=stage_result.authority.authoritative_block_category_by_index,
    )
    candidate_queue_blocks = _block_rows_for_indices(
        full_blocks_by_index=full_blocks_by_index,
        block_indices=stage_result.routing.candidate_block_indices,
        block_category_by_index=stage_result.candidate_block_route_by_index(),
    )
    excluded_blocks = _block_rows_for_indices(
        full_blocks_by_index=full_blocks_by_index,
        block_indices=stage_result.routing.excluded_block_indices,
        block_category_by_index=stage_result.authority.authoritative_block_category_by_index,
    )
    has_finalized_candidates = bool(
        stage_result.candidate_status.finalized_candidate_block_indices
    )
    return NonRecipeAuthorityContract(
        final_blocks=final_blocks,
        candidate_queue_blocks=candidate_queue_blocks,
        excluded_blocks=excluded_blocks,
        candidate_status=stage_result.candidate_status,
        late_output_blocks=list(final_blocks if has_finalized_candidates else candidate_queue_blocks),
        scoring_view=NonRecipeScoringView(
            authoritative_block_indices=list(stage_result.authority.authoritative_block_indices),
            authoritative_block_category_by_index=dict(
                stage_result.authority.authoritative_block_category_by_index
            ),
            unresolved_candidate_block_indices=list(
                stage_result.candidate_status.unresolved_candidate_block_indices
            ),
            unresolved_candidate_route_by_index=dict(
                stage_result.candidate_status.unresolved_candidate_route_by_index
            ),
        ),
        late_output_mode=("final_authority" if has_finalized_candidates else "candidate_queue"),
    )


def block_rows_for_nonrecipe_stage(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    full_blocks_by_index = prepare_nonrecipe_full_blocks_by_index(full_blocks)
    return _block_rows_for_indices(
        full_blocks_by_index=full_blocks_by_index,
        block_indices=sorted(stage_result.seed.seed_route_by_index),
        block_category_by_index=stage_result.seed.seed_route_by_index,
    )


def block_rows_for_nonrecipe_authority(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    return list(
        build_nonrecipe_authority_contract(
            full_blocks=full_blocks,
            stage_result=stage_result,
        ).final_blocks
    )


def block_rows_for_nonrecipe_candidate_queue(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    return list(
        build_nonrecipe_authority_contract(
            full_blocks=full_blocks,
            stage_result=stage_result,
        ).candidate_queue_blocks
    )


def block_rows_for_nonrecipe_late_outputs(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    return list(
        build_nonrecipe_authority_contract(
            full_blocks=full_blocks,
            stage_result=stage_result,
        ).late_output_blocks
    )


def block_rows_for_nonrecipe_span(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    span: NonRecipeSpan,
) -> list[dict[str, Any]]:
    full_blocks_by_index = prepare_nonrecipe_full_blocks_by_index(full_blocks)
    return _block_rows_for_indices(
        full_blocks_by_index=full_blocks_by_index,
        block_indices=span.block_indices,
        block_category_by_index={
            int(block_index): span.category for block_index in span.block_indices
        },
    )
