from __future__ import annotations

from typing import Any, Mapping, Sequence

from cookimport.parsing.canonical_line_roles.contracts import RECIPE_LOCAL_LINE_ROLE_LABELS
from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel

from .nonrecipe_authority import (
    block_rows_for_nonrecipe_authority,
    block_rows_for_nonrecipe_candidate_queue,
    block_rows_for_nonrecipe_late_outputs,
    block_rows_for_nonrecipe_span,
    block_rows_for_nonrecipe_stage,
    build_nonrecipe_authority_contract,
    build_nonrecipe_authority_result,
)
from .nonrecipe_authority_contract import (
    NonRecipeAuthorityContract,
    NonRecipeAuthorityResult,
    NonRecipeCandidateStatusResult,
    NonRecipeRoutingResult,
    NonRecipeScoringView,
    NonRecipeSeedResult,
    NonRecipeSpan,
    NonRecipeStageResult,
)
from .nonrecipe_finalize_status import build_nonrecipe_finalize_status_result
from .nonrecipe_routing import build_nonrecipe_routing_result
from .nonrecipe_seed import (
    build_nonrecipe_seed_result,
    normalize_nonrecipe_route_label,
    prepare_nonrecipe_full_blocks_by_index,
    preview_nonrecipe_text,
    require_nonrecipe_final_category,
    require_nonrecipe_route_label,
)
from .recipe_ownership import (
    RecipeOwnershipInvariantError,
    RecipeOwnershipResult,
)

_DIVESTED_RECIPE_LOCAL_ROUTE_LABELS = frozenset(RECIPE_LOCAL_LINE_ROLE_LABELS)


def _resolve_available_nonrecipe_route_label(
    *,
    block_index: int,
    block_label: AuthoritativeBlockLabel,
    divested_block_indices: set[int],
    warnings: list[str],
) -> str:
    raw_label = getattr(block_label, "final_label", None)
    normalized_label = str(raw_label or "").strip().upper()
    if (
        int(block_index) in divested_block_indices
        and normalized_label in _DIVESTED_RECIPE_LOCAL_ROUTE_LABELS
    ):
        warnings.append(
            "block "
            f"{block_index}: divested recipe-local label '{normalized_label}' "
            "normalized to NONRECIPE_CANDIDATE for nonrecipe routing"
        )
        return "candidate"
    return require_nonrecipe_route_label(
        raw_label,
        block_index=block_index,
    )


def _default_nonrecipe_refinement_report(
    *,
    seed: NonRecipeSeedResult,
    routing: NonRecipeRoutingResult,
    authority: NonRecipeAuthorityResult,
    candidate_status: NonRecipeCandidateStatusResult,
) -> dict[str, Any]:
    return {
        "enabled": False,
        "authority_mode": "deterministic_route_only",
        "input_mode": "nonrecipe_candidate_spans",
        "seed_nonrecipe_span_count": len(seed.seed_nonrecipe_spans),
        "final_nonrecipe_span_count": len(authority.authoritative_nonrecipe_spans),
        "changed_block_count": 0,
        "reviewed_block_count": 0,
        "candidate_nonrecipe_span_count": len(routing.candidate_nonrecipe_spans),
        "candidate_block_count": len(routing.candidate_block_indices),
        "excluded_block_count": len(routing.excluded_block_indices),
        "final_authority_block_count": len(authority.authoritative_block_indices),
        "unresolved_candidate_block_count": len(
            candidate_status.unresolved_candidate_block_indices
        ),
        "grounding_counts": {},
        "grounding_by_block": {},
        "changed_blocks": [],
        "conflicts": [],
        "ignored_block_indices": [],
        "scored_effect": "route_only",
    }


def build_nonrecipe_stage_result(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    final_block_labels: Sequence[AuthoritativeBlockLabel],
    recipe_ownership_result: RecipeOwnershipResult,
    overrides: Any | None = None,
) -> NonRecipeStageResult:
    del overrides

    full_blocks_by_index = prepare_nonrecipe_full_blocks_by_index(full_blocks)
    labels_by_index = {int(row.source_block_index): row for row in final_block_labels}
    owned_block_indices = set(recipe_ownership_result.owned_block_indices)
    divested_block_indices = set(recipe_ownership_result.divested_block_indices)
    available_to_nonrecipe = list(
        recipe_ownership_result.available_to_nonrecipe_block_indices
    )

    route_by_index: dict[int, str] = {}
    warnings: list[str] = []
    block_preview_by_index = {
        int(block_index): preview_nonrecipe_text(full_blocks_by_index[block_index].get("text"))
        for block_index in available_to_nonrecipe
        if block_index in full_blocks_by_index
    }

    for block_index in sorted(owned_block_indices):
        block_label = labels_by_index.get(block_index)
        if block_label is None:
            continue
        route, warning = normalize_nonrecipe_route_label(getattr(block_label, "final_label", None))
        if warning is None:
            raise RecipeOwnershipInvariantError(
                f"Recipe-owned block {block_index} carried nonrecipe route '{route}'."
            )

    for block_index in available_to_nonrecipe:
        if block_index not in full_blocks_by_index:
            raise RecipeOwnershipInvariantError(
                f"Recipe ownership referenced missing nonrecipe-admissible block {block_index}."
            )

        block_label = labels_by_index.get(block_index)
        if block_label is None:
            raise ValueError(
                f"Missing final block label for non-recipe block {block_index}."
            )
        route = _resolve_available_nonrecipe_route_label(
            block_index=block_index,
            block_label=block_label,
            divested_block_indices=divested_block_indices,
            warnings=warnings,
        )
        route_by_index[block_index] = route

    seed = build_nonrecipe_seed_result(
        full_blocks_by_index=full_blocks_by_index,
        route_by_index=route_by_index,
    )
    routing = build_nonrecipe_routing_result(
        full_blocks_by_index=full_blocks_by_index,
        candidate_block_indices=[
            index for index, route in sorted(route_by_index.items()) if route == "candidate"
        ],
        excluded_block_indices=[
            index for index, route in sorted(route_by_index.items()) if route == "exclude"
        ],
        block_preview_by_index=block_preview_by_index,
        warnings=warnings,
    )
    authority = build_nonrecipe_authority_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index={
            int(block_index): "other"
            for block_index in routing.excluded_block_indices
        },
        authoritative_block_indices=routing.excluded_block_indices,
        excluded_block_indices=routing.excluded_block_indices,
    )
    candidate_status = build_nonrecipe_finalize_status_result(
        full_blocks_by_index=full_blocks_by_index,
        candidate_block_indices=routing.candidate_block_indices,
        authoritative_block_indices=authority.authoritative_block_indices,
        excluded_block_indices=routing.excluded_block_indices,
    )
    return NonRecipeStageResult(
        seed=seed,
        routing=routing,
        authority=authority,
        candidate_status=candidate_status,
        refinement_report=_default_nonrecipe_refinement_report(
            seed=seed,
            routing=routing,
            authority=authority,
            candidate_status=candidate_status,
        ),
    )


def refine_nonrecipe_stage_result(
    *,
    stage_result: NonRecipeStageResult,
    full_blocks: Sequence[Mapping[str, Any]],
    block_category_updates: Mapping[int, str],
    grounding_by_block: Mapping[int, Mapping[str, Any]] | None = None,
    grounding_summary: Mapping[str, Any] | None = None,
    applied_packet_ids_by_block: Mapping[int, Sequence[str]] | None = None,
    conflicts: Sequence[Mapping[str, Any]] | None = None,
    ignored_block_indices: Sequence[int] | None = None,
) -> NonRecipeStageResult:
    full_blocks_by_index = prepare_nonrecipe_full_blocks_by_index(full_blocks)
    candidate_index_set = {
        int(index) for index in stage_result.routing.candidate_block_indices
    }
    final_block_category_by_index = dict(
        stage_result.authority.authoritative_block_category_by_index
    )
    changed_blocks: list[dict[str, Any]] = []
    warnings = list(stage_result.routing.warnings)
    reviewed_block_indices: set[int] = set()

    for block_index, raw_category in sorted(block_category_updates.items()):
        normalized_category = require_nonrecipe_final_category(
            raw_category,
            block_index=int(block_index),
        )
        if block_index not in candidate_index_set:
            continue
        prior_final_category = final_block_category_by_index.get(block_index)
        final_block_category_by_index[block_index] = normalized_category
        reviewed_block_indices.add(int(block_index))
        if prior_final_category is None or normalized_category == prior_final_category:
            continue
        changed_blocks.append(
            {
                "block_index": int(block_index),
                "previous_final_category": prior_final_category,
                "final_category": normalized_category,
                "grounding": (
                    dict((grounding_by_block or {}).get(block_index) or {})
                    if normalized_category == "knowledge"
                    else {}
                ),
                "applied_packet_ids": list(applied_packet_ids_by_block.get(block_index) or [])
                if applied_packet_ids_by_block is not None
                else [],
            }
        )

    conflict_rows = [dict(row) for row in (conflicts or [])]
    ignored_indices = sorted({int(index) for index in (ignored_block_indices or [])})
    authority = build_nonrecipe_authority_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=final_block_category_by_index,
        authoritative_block_indices=sorted(final_block_category_by_index),
        excluded_block_indices=stage_result.routing.excluded_block_indices,
    )
    candidate_status = build_nonrecipe_finalize_status_result(
        full_blocks_by_index=full_blocks_by_index,
        candidate_block_indices=stage_result.routing.candidate_block_indices,
        authoritative_block_indices=authority.authoritative_block_indices,
        excluded_block_indices=stage_result.routing.excluded_block_indices,
    )
    scored_effect = (
        "partial_final_authority"
        if reviewed_block_indices and candidate_status.unresolved_candidate_block_indices
        else "final_authority" if reviewed_block_indices else "route_only"
    )
    return NonRecipeStageResult(
        seed=stage_result.seed,
        routing=NonRecipeRoutingResult(
            route_by_block=dict(stage_result.routing.route_by_block),
            candidate_nonrecipe_spans=list(stage_result.routing.candidate_nonrecipe_spans),
            excluded_nonrecipe_spans=list(stage_result.routing.excluded_nonrecipe_spans),
            candidate_block_indices=list(stage_result.routing.candidate_block_indices),
            excluded_block_indices=list(stage_result.routing.excluded_block_indices),
            block_preview_by_index=dict(stage_result.routing.block_preview_by_index),
            warnings=warnings,
        ),
        authority=authority,
        candidate_status=candidate_status,
        refinement_report={
            "enabled": True,
            "authority_mode": (
                "knowledge_refined_final"
                if changed_blocks
                else "nonrecipe_finalized_candidates"
            ),
            "input_mode": "nonrecipe_candidate_spans",
            "seed_nonrecipe_span_count": len(stage_result.seed.seed_nonrecipe_spans),
            "final_nonrecipe_span_count": len(authority.authoritative_nonrecipe_spans),
            "final_knowledge_span_count": len(authority.authoritative_knowledge_spans),
            "changed_block_count": len(changed_blocks),
            "reviewed_block_count": len(reviewed_block_indices),
            "candidate_nonrecipe_span_count": len(stage_result.routing.candidate_nonrecipe_spans),
            "candidate_block_count": len(stage_result.routing.candidate_block_indices),
            "excluded_block_count": len(stage_result.routing.excluded_block_indices),
            "final_authority_block_count": len(authority.authoritative_block_indices),
            "unresolved_candidate_block_count": len(
                candidate_status.unresolved_candidate_block_indices
            ),
            "grounding_counts": dict(grounding_summary or {}),
            "grounding_by_block": {
                str(index): dict(value)
                for index, value in sorted((grounding_by_block or {}).items())
            },
            "changed_blocks": changed_blocks,
            "conflicts": conflict_rows,
            "ignored_block_indices": ignored_indices,
            "scored_effect": scored_effect,
        },
    )


__all__ = [
    "NonRecipeAuthorityContract", "NonRecipeAuthorityResult", "NonRecipeCandidateStatusResult",
    "NonRecipeRoutingResult", "NonRecipeScoringView", "NonRecipeSeedResult",
    "NonRecipeSpan", "NonRecipeStageResult", "block_rows_for_nonrecipe_authority",
    "block_rows_for_nonrecipe_candidate_queue", "block_rows_for_nonrecipe_late_outputs",
    "block_rows_for_nonrecipe_span", "block_rows_for_nonrecipe_stage",
    "build_nonrecipe_authority_contract", "build_nonrecipe_stage_result",
    "refine_nonrecipe_stage_result",
]
