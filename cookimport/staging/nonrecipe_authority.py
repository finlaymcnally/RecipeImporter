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
    prepare_nonrecipe_full_rows_by_index,
)


def build_nonrecipe_authority_result(
    *,
    full_rows_by_index: Mapping[int, Mapping[str, Any]],
    row_category_by_index: Mapping[int, str],
    authoritative_row_indices: Sequence[int],
    excluded_row_indices: Sequence[int] | None = None,
    row_source_block_index_by_index: Mapping[int, int] | None = None,
) -> NonRecipeAuthorityResult:
    excluded_index_set = {
        int(index) for index in (excluded_row_indices or ()) if int(index) in full_rows_by_index
    }
    authoritative_index_set = {
        int(index) for index in authoritative_row_indices if int(index) in full_rows_by_index
    }
    authoritative_index_set.update(excluded_index_set)
    authoritative_row_category_by_index = {
        int(index): (
            "other"
            if int(index) in excluded_index_set
            else str(row_category_by_index[int(index)])
        )
        for index in sorted(authoritative_index_set)
        if int(index) in excluded_index_set or int(index) in row_category_by_index
    }
    authoritative_row_source_block_index_by_index = {
        int(index): int(
            (
                row_source_block_index_by_index or {}
            ).get(
                int(index),
                full_rows_by_index.get(int(index), {}).get("source_block_index", index),
            )
        )
        for index in sorted(authoritative_row_category_by_index)
    }
    authoritative_nonrecipe_spans = build_nonrecipe_spans_from_categories(
        full_rows_by_index=full_rows_by_index,
        row_category_by_index=authoritative_row_category_by_index,
    )
    return NonRecipeAuthorityResult(
        authoritative_row_indices=sorted(authoritative_row_category_by_index),
        authoritative_row_category_by_index=authoritative_row_category_by_index,
        authoritative_row_source_block_index_by_index=authoritative_row_source_block_index_by_index,
        authoritative_nonrecipe_spans=authoritative_nonrecipe_spans,
        authoritative_knowledge_spans=[
            span for span in authoritative_nonrecipe_spans if span.category == "knowledge"
        ],
        authoritative_other_spans=[
            span for span in authoritative_nonrecipe_spans if span.category == "other"
        ],
    )


def _rows_for_indices(
    *,
    full_rows_by_index: Mapping[int, Mapping[str, Any]],
    row_indices: Sequence[int],
    row_category_by_index: Mapping[int, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_index in row_indices:
        row_index = int(raw_index)
        row = full_rows_by_index.get(row_index)
        if row is None:
            continue
        payload = dict(row)
        payload["index"] = row_index
        if row_index in row_category_by_index:
            payload["nonrecipe_final_category"] = str(row_category_by_index[row_index])
        rows.append(payload)
    return rows


def build_nonrecipe_authority_contract(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> NonRecipeAuthorityContract:
    full_rows_by_index = prepare_nonrecipe_full_rows_by_index(full_blocks)
    final_rows = _rows_for_indices(
        full_rows_by_index=full_rows_by_index,
        row_indices=stage_result.authority.authoritative_row_indices,
        row_category_by_index=stage_result.authority.authoritative_row_category_by_index,
    )
    candidate_queue_rows = _rows_for_indices(
        full_rows_by_index=full_rows_by_index,
        row_indices=stage_result.routing.candidate_row_indices,
        row_category_by_index=stage_result.candidate_row_route_by_index(),
    )
    excluded_rows = _rows_for_indices(
        full_rows_by_index=full_rows_by_index,
        row_indices=stage_result.routing.excluded_row_indices,
        row_category_by_index=stage_result.authority.authoritative_row_category_by_index,
    )
    has_finalized_candidates = bool(
        stage_result.candidate_status.finalized_candidate_row_indices
    )
    return NonRecipeAuthorityContract(
        final_rows=final_rows,
        candidate_queue_rows=candidate_queue_rows,
        excluded_rows=excluded_rows,
        candidate_status=stage_result.candidate_status,
        late_output_rows=list(final_rows if has_finalized_candidates else candidate_queue_rows),
        scoring_view=NonRecipeScoringView(
            authoritative_row_indices=list(stage_result.authority.authoritative_row_indices),
            authoritative_row_category_by_index=dict(
                stage_result.authority.authoritative_row_category_by_index
            ),
            unresolved_candidate_row_indices=list(
                stage_result.candidate_status.unresolved_candidate_row_indices
            ),
            unresolved_candidate_route_by_index=dict(
                stage_result.candidate_status.unresolved_candidate_route_by_index
            ),
        ),
        late_output_mode=("final_authority" if has_finalized_candidates else "candidate_queue"),
    )


def rows_for_nonrecipe_stage(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    full_rows_by_index = prepare_nonrecipe_full_rows_by_index(full_blocks)
    return _rows_for_indices(
        full_rows_by_index=full_rows_by_index,
        row_indices=sorted(stage_result.seed.seed_route_by_index),
        row_category_by_index=stage_result.seed.seed_route_by_index,
    )


def rows_for_nonrecipe_authority(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    return list(
        build_nonrecipe_authority_contract(
            full_blocks=full_blocks,
            stage_result=stage_result,
        ).final_rows
    )


def rows_for_nonrecipe_candidate_queue(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    return list(
        build_nonrecipe_authority_contract(
            full_blocks=full_blocks,
            stage_result=stage_result,
        ).candidate_queue_rows
    )


def rows_for_nonrecipe_late_outputs(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    return list(
        build_nonrecipe_authority_contract(
            full_blocks=full_blocks,
            stage_result=stage_result,
        ).late_output_rows
    )


def rows_for_nonrecipe_span(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    span: NonRecipeSpan,
) -> list[dict[str, Any]]:
    full_rows_by_index = prepare_nonrecipe_full_rows_by_index(full_blocks)
    return _rows_for_indices(
        full_rows_by_index=full_rows_by_index,
        row_indices=span.row_indices,
        row_category_by_index={
            int(row_index): span.category for row_index in span.row_indices
        },
    )
