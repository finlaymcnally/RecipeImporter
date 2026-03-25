from __future__ import annotations

from typing import Any, Mapping, Sequence

from cookimport.staging.nonrecipe_stage import (
    NonRecipeAuthorityResult,
    NonRecipeReviewStatusResult,
    NonRecipeRoutingResult,
    NonRecipeSeedResult,
    NonRecipeSpan,
    NonRecipeStageResult,
)


def make_stage_result(
    *,
    seed: NonRecipeSeedResult,
    routing: NonRecipeRoutingResult,
    authority: NonRecipeAuthorityResult,
    review_status: NonRecipeReviewStatusResult,
    refinement_report: Mapping[str, Any] | None = None,
) -> NonRecipeStageResult:
    return NonRecipeStageResult(
        seed=seed,
        routing=routing,
        authority=authority,
        review_status=review_status,
        refinement_report=dict(refinement_report or {}),
    )


def make_seed_result(
    block_category_by_index: Mapping[int, str],
    *,
    nonrecipe_spans: Sequence[NonRecipeSpan] | None = None,
    knowledge_spans: Sequence[NonRecipeSpan] | None = None,
    other_spans: Sequence[NonRecipeSpan] | None = None,
) -> NonRecipeSeedResult:
    resolved_spans = (
        list(nonrecipe_spans)
        if nonrecipe_spans is not None
        else spans_from_category_map(block_category_by_index)
    )
    return NonRecipeSeedResult(
        seed_nonrecipe_spans=resolved_spans,
        seed_knowledge_spans=(
            list(knowledge_spans)
            if knowledge_spans is not None
            else [span for span in resolved_spans if span.category == "knowledge"]
        ),
        seed_other_spans=(
            list(other_spans)
            if other_spans is not None
            else [span for span in resolved_spans if span.category == "other"]
        ),
        seed_block_category_by_index={
            int(index): str(category)
            for index, category in block_category_by_index.items()
        },
    )


def make_routing_result(
    *,
    review_eligible_block_indices: Sequence[int],
    review_excluded_block_indices: Sequence[int] = (),
    review_exclusion_reason_by_block: Mapping[int, str] | None = None,
    review_eligible_nonrecipe_spans: Sequence[NonRecipeSpan] | None = None,
    review_excluded_other_spans: Sequence[NonRecipeSpan] | None = None,
    review_routing_by_block: Mapping[int, str] | None = None,
    block_preview_by_index: Mapping[int, str] | None = None,
    warnings: Sequence[str] | None = None,
) -> NonRecipeRoutingResult:
    eligible_indices = [int(index) for index in review_eligible_block_indices]
    excluded_indices = [int(index) for index in review_excluded_block_indices]
    return NonRecipeRoutingResult(
        review_routing_by_block=(
            {
                **{int(index): "review_eligible" for index in eligible_indices},
                **{int(index): "excluded_other" for index in excluded_indices},
            }
            if review_routing_by_block is None
            else {int(index): str(route) for index, route in review_routing_by_block.items()}
        ),
        review_eligible_nonrecipe_spans=(
            list(review_eligible_nonrecipe_spans)
            if review_eligible_nonrecipe_spans is not None
            else spans_for_indices(eligible_indices, category="review_candidate")
        ),
        review_excluded_other_spans=(
            list(review_excluded_other_spans)
            if review_excluded_other_spans is not None
            else spans_for_indices(excluded_indices, category="other")
        ),
        review_eligible_block_indices=eligible_indices,
        review_excluded_block_indices=excluded_indices,
        review_exclusion_reason_by_block={
            int(index): str(reason)
            for index, reason in (review_exclusion_reason_by_block or {}).items()
        },
        block_preview_by_index={
            int(index): str(preview)
            for index, preview in (block_preview_by_index or {}).items()
        },
        warnings=[str(warning) for warning in (warnings or [])],
    )


def make_authority_result(
    block_category_by_index: Mapping[int, str],
) -> NonRecipeAuthorityResult:
    authoritative_map = {
        int(index): str(category)
        for index, category in block_category_by_index.items()
    }
    authoritative_spans = spans_from_category_map(authoritative_map)
    return NonRecipeAuthorityResult(
        authoritative_block_indices=sorted(authoritative_map),
        authoritative_block_category_by_index=authoritative_map,
        authoritative_nonrecipe_spans=authoritative_spans,
        authoritative_knowledge_spans=[
            span for span in authoritative_spans if span.category == "knowledge"
        ],
        authoritative_other_spans=[
            span for span in authoritative_spans if span.category == "other"
        ],
    )


def make_review_status_result(
    *,
    reviewed_block_indices: Sequence[int],
    unreviewed_block_category_by_index: Mapping[int, str],
) -> NonRecipeReviewStatusResult:
    unreviewed_map = {
        int(index): str(category)
        for index, category in unreviewed_block_category_by_index.items()
    }
    return NonRecipeReviewStatusResult(
        reviewed_block_indices=[int(index) for index in reviewed_block_indices],
        unreviewed_review_eligible_block_indices=sorted(unreviewed_map),
        unreviewed_block_category_by_index=unreviewed_map,
        unreviewed_spans=spans_from_category_map(unreviewed_map),
    )


def spans_for_indices(block_indices: Sequence[int], *, category: str) -> list[NonRecipeSpan]:
    return spans_from_category_map({int(index): category for index in block_indices})


def spans_from_category_map(
    block_category_by_index: Mapping[int, str],
) -> list[NonRecipeSpan]:
    spans: list[NonRecipeSpan] = []
    current_category: str | None = None
    current_indices: list[int] = []
    previous_index: int | None = None

    for block_index in sorted(int(index) for index in block_category_by_index):
        category = str(block_category_by_index[block_index])
        if (
            current_category is None
            or previous_index is None
            or block_index != previous_index + 1
            or category != current_category
        ):
            if current_indices:
                spans.append(_build_span(current_indices, current_category or "other"))
            current_category = category
            current_indices = [block_index]
            previous_index = block_index
            continue
        current_indices.append(block_index)
        previous_index = block_index

    if current_indices:
        spans.append(_build_span(current_indices, current_category or "other"))
    return spans


def _build_span(block_indices: Sequence[int], category: str) -> NonRecipeSpan:
    ordered_indices = [int(index) for index in block_indices]
    start = ordered_indices[0]
    end = ordered_indices[-1] + 1
    return NonRecipeSpan(
        span_id=f"nr.{category}.{start}.{end}",
        category=category,
        block_start_index=start,
        block_end_index=end,
        block_indices=ordered_indices,
        block_ids=[f"b{index}" for index in ordered_indices],
    )
