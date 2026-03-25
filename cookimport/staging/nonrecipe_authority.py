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
) -> NonRecipeAuthorityResult:
    authoritative_block_category_by_index = {
        int(index): str(block_category_by_index[int(index)])
        for index in authoritative_block_indices
        if int(index) in block_category_by_index
    }
    authoritative_nonrecipe_spans, authoritative_knowledge_spans, authoritative_other_spans = (
        build_nonrecipe_spans_from_categories(
            full_blocks_by_index=full_blocks_by_index,
            block_category_by_index=authoritative_block_category_by_index,
        )
    )
    return NonRecipeAuthorityResult(
        authoritative_block_indices=[
            int(index) for index in authoritative_block_indices if int(index) in block_category_by_index
        ],
        authoritative_block_category_by_index=authoritative_block_category_by_index,
        authoritative_nonrecipe_spans=authoritative_nonrecipe_spans,
        authoritative_knowledge_spans=authoritative_knowledge_spans,
        authoritative_other_spans=authoritative_other_spans,
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
            payload["stage7_category"] = str(block_category_by_index[block_index])
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
    review_queue_categories = stage_result.surviving_review_block_category_by_index()
    review_queue_blocks = _block_rows_for_indices(
        full_blocks_by_index=full_blocks_by_index,
        block_indices=stage_result.routing.review_eligible_block_indices,
        block_category_by_index=review_queue_categories,
    )
    excluded_blocks = _block_rows_for_indices(
        full_blocks_by_index=full_blocks_by_index,
        block_indices=stage_result.routing.review_excluded_block_indices,
        block_category_by_index=stage_result.authority.authoritative_block_category_by_index,
    )
    has_reviewed_authority = bool(stage_result.review_status.reviewed_block_indices)
    return NonRecipeAuthorityContract(
        final_blocks=final_blocks,
        review_queue_blocks=review_queue_blocks,
        excluded_blocks=excluded_blocks,
        review_status=stage_result.review_status,
        late_output_blocks=list(final_blocks if has_reviewed_authority else review_queue_blocks),
        scoring_view=NonRecipeScoringView(
            authoritative_block_indices=list(stage_result.authority.authoritative_block_indices),
            authoritative_block_category_by_index=dict(
                stage_result.authority.authoritative_block_category_by_index
            ),
            unresolved_review_eligible_block_indices=list(
                stage_result.review_status.unreviewed_review_eligible_block_indices
            ),
            unresolved_review_eligible_block_category_by_index=dict(
                stage_result.review_status.unreviewed_block_category_by_index
            ),
        ),
        late_output_mode=(
            "final_authority"
            if has_reviewed_authority
            else "review_queue"
        ),
    )


def block_rows_for_nonrecipe_stage(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    full_blocks_by_index = prepare_nonrecipe_full_blocks_by_index(full_blocks)
    return _block_rows_for_indices(
        full_blocks_by_index=full_blocks_by_index,
        block_indices=sorted(stage_result.seed.seed_block_category_by_index),
        block_category_by_index=stage_result.seed.seed_block_category_by_index,
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


def block_rows_for_nonrecipe_review_queue(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    return list(
        build_nonrecipe_authority_contract(
            full_blocks=full_blocks,
            stage_result=stage_result,
        ).review_queue_blocks
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
        block_category_by_index={int(block_index): span.category for block_index in span.block_indices},
    )
