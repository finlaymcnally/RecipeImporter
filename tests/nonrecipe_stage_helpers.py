from __future__ import annotations

from typing import Any, Mapping, Sequence

from cookimport.staging.nonrecipe_stage import (
    NonRecipeAuthorityResult,
    NonRecipeCandidateStatusResult,
    NonRecipeRoutingResult,
    NonRecipeSeedResult,
    NonRecipeSpan,
    NonRecipeStageResult,
)
from cookimport.staging.recipe_ownership import (
    RecipeOwnershipEntry,
    RecipeOwnershipResult,
)


def make_stage_result(
    *,
    seed: NonRecipeSeedResult,
    routing: NonRecipeRoutingResult,
    authority: NonRecipeAuthorityResult,
    candidate_status: NonRecipeCandidateStatusResult | None = None,
    finalize_status: NonRecipeCandidateStatusResult | None = None,
    refinement_report: Mapping[str, Any] | None = None,
) -> NonRecipeStageResult:
    resolved_candidate_status = candidate_status or finalize_status
    if resolved_candidate_status is None:
        raise TypeError("make_stage_result requires candidate_status or finalize_status")
    return NonRecipeStageResult(
        seed=seed,
        routing=routing,
        authority=authority,
        candidate_status=resolved_candidate_status,
        refinement_report=dict(refinement_report or {}),
    )


def make_seed_result(
    route_by_index: Mapping[int, str],
    *,
    nonrecipe_spans: Sequence[NonRecipeSpan] | None = None,
    candidate_spans: Sequence[NonRecipeSpan] | None = None,
    excluded_spans: Sequence[NonRecipeSpan] | None = None,
) -> NonRecipeSeedResult:
    resolved_spans = (
        list(nonrecipe_spans)
        if nonrecipe_spans is not None
        else spans_from_category_map(route_by_index)
    )
    return NonRecipeSeedResult(
        seed_nonrecipe_spans=resolved_spans,
        seed_candidate_spans=(
            list(candidate_spans)
            if candidate_spans is not None
            else [span for span in resolved_spans if span.category == "candidate"]
        ),
        seed_excluded_spans=(
            list(excluded_spans)
            if excluded_spans is not None
            else [span for span in resolved_spans if span.category == "exclude"]
        ),
        seed_route_by_index={
            int(index): str(category)
            for index, category in route_by_index.items()
        },
    )


def make_routing_result(
    *,
    candidate_row_indices: Sequence[int] | None = None,
    excluded_row_indices: Sequence[int] | None = None,
    candidate_nonrecipe_spans: Sequence[NonRecipeSpan] | None = None,
    excluded_nonrecipe_spans: Sequence[NonRecipeSpan] | None = None,
    row_preview_by_index: Mapping[int, str] | None = None,
    warnings: Sequence[str] | None = None,
) -> NonRecipeRoutingResult:
    candidate_indices = [
        int(index)
        for index in (
            candidate_row_indices or ()
        )
    ]
    excluded_indices = [
        int(index)
        for index in (
            excluded_row_indices or ()
        )
    ]
    return NonRecipeRoutingResult(
        route_by_row={
            **{int(index): "candidate" for index in candidate_indices},
            **{int(index): "exclude" for index in excluded_indices},
        },
        candidate_nonrecipe_spans=(
            list(candidate_nonrecipe_spans)
            if candidate_nonrecipe_spans is not None
            else spans_for_indices(candidate_indices, category="candidate")
        ),
        excluded_nonrecipe_spans=(
            list(excluded_nonrecipe_spans)
            if excluded_nonrecipe_spans is not None
            else spans_for_indices(excluded_indices, category="exclude")
        ),
        candidate_row_indices=candidate_indices,
        excluded_row_indices=excluded_indices,
        row_preview_by_index={
            int(index): str(preview)
            for index, preview in (row_preview_by_index or {}).items()
        },
        warnings=[str(warning) for warning in (warnings or [])],
    )


def make_authority_result(
    row_category_by_index: Mapping[int, str],
    *,
    row_source_block_index_by_index: Mapping[int, int] | None = None,
) -> NonRecipeAuthorityResult:
    authoritative_map = {
        int(index): str(category)
        for index, category in row_category_by_index.items()
    }
    authoritative_row_map = dict(authoritative_map)
    authoritative_spans = spans_from_category_map(authoritative_row_map)
    return NonRecipeAuthorityResult(
        authoritative_row_indices=sorted(authoritative_row_map),
        authoritative_row_category_by_index=authoritative_row_map,
        authoritative_row_source_block_index_by_index={
            int(index): int(
                (row_source_block_index_by_index or {}).get(int(index), int(index))
            )
            for index in authoritative_row_map
        },
        authoritative_nonrecipe_spans=authoritative_spans,
        authoritative_knowledge_spans=[
            span for span in authoritative_spans if span.category == "knowledge"
        ],
        authoritative_other_spans=[
            span for span in authoritative_spans if span.category == "other"
        ],
    )


def make_candidate_status_result(
    *,
    finalized_candidate_row_indices: Sequence[int] | None = None,
    unresolved_candidate_route_by_index: Mapping[int, str],
) -> NonRecipeCandidateStatusResult:
    unresolved_map = {
        int(index): str(route)
        for index, route in unresolved_candidate_route_by_index.items()
    }
    return NonRecipeCandidateStatusResult(
        finalized_candidate_row_indices=[
            int(index)
            for index in (finalized_candidate_row_indices or ())
        ],
        unresolved_candidate_row_indices=sorted(unresolved_map),
        unresolved_candidate_route_by_index=unresolved_map,
        unresolved_candidate_spans=spans_from_category_map(unresolved_map),
    )


def make_finalize_status_result(
    *,
    reviewed_row_indices: Sequence[int],
    unreviewed_row_category_by_index: Mapping[int, str],
) -> NonRecipeCandidateStatusResult:
    return make_candidate_status_result(
        finalized_candidate_row_indices=list(reviewed_row_indices),
        unresolved_candidate_route_by_index=unreviewed_row_category_by_index,
    )


def make_recipe_ownership_result(
    *,
    owned_by_recipe_id: Mapping[str, Sequence[int]],
    all_block_indices: Sequence[int],
    divested_by_recipe_id: Mapping[str, Sequence[int]] | None = None,
    ownership_mode: str = "recipe_boundary_with_explicit_divestment",
) -> RecipeOwnershipResult:
    resolved_divested = {
        str(recipe_id): [int(index) for index in indices]
        for recipe_id, indices in (divested_by_recipe_id or {}).items()
    }
    entries = [
        RecipeOwnershipEntry(
            recipe_id=str(recipe_id),
            recipe_span_id=f"span:{recipe_id}",
            owned_row_indices=[int(index) for index in indices],
            divested_row_indices=list(resolved_divested.get(str(recipe_id), [])),
        )
        for recipe_id, indices in owned_by_recipe_id.items()
    ]
    row_owner_by_index = {
        int(index): str(recipe_id)
        for recipe_id, indices in owned_by_recipe_id.items()
        for index in indices
    }
    owned_row_indices = sorted(row_owner_by_index)
    divested_row_indices = sorted(
        {
            int(index)
            for indices in resolved_divested.values()
            for index in indices
        }
    )
    all_indices = sorted({int(index) for index in all_block_indices})
    return RecipeOwnershipResult(
        ownership_mode=ownership_mode,
        recipe_entries=entries,
        row_owner_by_index=row_owner_by_index,
        owned_row_indices=owned_row_indices,
        divested_row_indices=divested_row_indices,
        available_to_nonrecipe_row_indices=[
            index for index in all_indices if index not in row_owner_by_index
        ],
        all_row_indices=all_indices,
    )


def spans_for_indices(row_indices: Sequence[int], *, category: str) -> list[NonRecipeSpan]:
    return spans_from_category_map({int(index): category for index in row_indices})


def spans_from_category_map(
    row_category_by_index: Mapping[int, str],
) -> list[NonRecipeSpan]:
    spans: list[NonRecipeSpan] = []
    current_category: str | None = None
    current_indices: list[int] = []
    previous_index: int | None = None

    for row_index in sorted(int(index) for index in row_category_by_index):
        category = str(row_category_by_index[row_index])
        if (
            current_category is None
            or previous_index is None
            or row_index != previous_index + 1
            or category != current_category
        ):
            if current_indices:
                spans.append(_build_span(current_indices, current_category or "other"))
            current_category = category
            current_indices = [row_index]
            previous_index = row_index
            continue
        current_indices.append(row_index)
        previous_index = row_index

    if current_indices:
        spans.append(_build_span(current_indices, current_category or "other"))
    return spans


def _build_span(row_indices: Sequence[int], category: str) -> NonRecipeSpan:
    ordered_indices = [int(index) for index in row_indices]
    start = ordered_indices[0]
    end = ordered_indices[-1] + 1
    return NonRecipeSpan(
        span_id=f"nr.{category}.{start}.{end}",
        category=category,
        row_start_index=start,
        row_end_index=end,
        row_indices=ordered_indices,
        row_ids=[f"b{index}" for index in ordered_indices],
    )
