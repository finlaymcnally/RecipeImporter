from __future__ import annotations

from typing import Any, Mapping, Sequence

from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    RecipeSpan,
)

from .nonrecipe_authority import (
    block_rows_for_nonrecipe_authority,
    block_rows_for_nonrecipe_late_outputs,
    block_rows_for_nonrecipe_review_queue,
    block_rows_for_nonrecipe_span,
    block_rows_for_nonrecipe_stage,
    build_nonrecipe_authority_contract,
    build_nonrecipe_authority_result,
)
from .nonrecipe_authority_contract import (
    NonRecipeAuthorityContract,
    NonRecipeAuthorityResult,
    NonRecipeReviewStatusResult,
    NonRecipeRoutingResult,
    NonRecipeScoringView,
    NonRecipeSeedResult,
    NonRecipeSpan,
    NonRecipeStageResult,
)
from .nonrecipe_review_status import build_nonrecipe_review_status_result
from .nonrecipe_routing import build_nonrecipe_routing_result
from .nonrecipe_seed import (
    build_nonrecipe_seed_result,
    count_nonrecipe_reason_values,
    prepare_nonrecipe_full_blocks_by_index,
    preview_nonrecipe_text,
    require_nonrecipe_stage_category,
)


def _default_nonrecipe_refinement_report(
    *,
    seed: NonRecipeSeedResult,
    routing: NonRecipeRoutingResult,
    authority: NonRecipeAuthorityResult,
    review_status: NonRecipeReviewStatusResult,
) -> dict[str, Any]:
    return {
        "enabled": False,
        "authority_mode": "deterministic_seed_only",
        "input_mode": "stage7_review_eligible_nonrecipe_spans",
        "seed_nonrecipe_span_count": len(seed.seed_nonrecipe_spans),
        "final_nonrecipe_span_count": len(authority.authoritative_nonrecipe_spans),
        "changed_block_count": 0,
        "reviewed_block_count": 0,
        "review_eligible_nonrecipe_span_count": len(routing.review_eligible_nonrecipe_spans),
        "review_eligible_block_count": len(routing.review_eligible_block_indices),
        "review_excluded_block_count": len(routing.review_excluded_block_indices),
        "final_authority_block_count": len(authority.authoritative_block_indices),
        "unreviewed_review_eligible_block_count": len(
            review_status.unreviewed_review_eligible_block_indices
        ),
        "review_exclusion_reason_counts": count_nonrecipe_reason_values(
            routing.review_exclusion_reason_by_block
        ),
        "reviewer_category_counts": {},
        "changed_blocks": [],
        "conflicts": [],
        "ignored_block_indices": [],
        "scored_effect": "seed_only",
    }


def build_nonrecipe_stage_result(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    final_block_labels: Sequence[AuthoritativeBlockLabel],
    recipe_spans: Sequence[RecipeSpan],
    overrides: Any | None = None,
) -> NonRecipeStageResult:
    del overrides

    full_blocks_by_index = prepare_nonrecipe_full_blocks_by_index(full_blocks)
    recipe_block_indices = {
        int(block_index)
        for span in recipe_spans
        for block_index in span.block_indices
    }
    labels_by_index = {
        int(row.source_block_index): row
        for row in final_block_labels
    }

    block_category_by_index: dict[int, str] = {}
    review_eligible_block_category_by_index: dict[int, str] = {}
    review_exclusion_reason_by_block: dict[int, str] = {}
    warnings: list[str] = []
    block_preview_by_index = {
        int(block_index): preview_nonrecipe_text(full_blocks_by_index[block_index].get("text"))
        for block_index in sorted(full_blocks_by_index)
        if block_index not in recipe_block_indices
    }

    for block_index in sorted(full_blocks_by_index):
        if block_index in recipe_block_indices:
            continue

        block_label = labels_by_index.get(block_index)
        if block_label is None:
            raise ValueError(
                f"Missing final block label for non-recipe block {block_index}."
            )
        category = require_nonrecipe_stage_category(
            getattr(block_label, "final_label", None),
            block_index=block_index,
        )
        block_category_by_index[block_index] = category
        review_exclusion_reason = str(
            getattr(block_label, "review_exclusion_reason", None) or ""
        ).strip()
        if category == "other" and review_exclusion_reason:
            review_exclusion_reason_by_block[block_index] = review_exclusion_reason
            continue
        review_eligible_block_category_by_index[block_index] = category

    seed = build_nonrecipe_seed_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=block_category_by_index,
    )
    routing = build_nonrecipe_routing_result(
        full_blocks_by_index=full_blocks_by_index,
        review_eligible_block_indices=sorted(review_eligible_block_category_by_index),
        review_excluded_block_indices=sorted(review_exclusion_reason_by_block),
        review_exclusion_reason_by_block=review_exclusion_reason_by_block,
        block_preview_by_index=block_preview_by_index,
        warnings=warnings,
    )
    authority = build_nonrecipe_authority_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=block_category_by_index,
        authoritative_block_indices=sorted(review_exclusion_reason_by_block),
    )
    review_status = build_nonrecipe_review_status_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=block_category_by_index,
        review_eligible_block_indices=routing.review_eligible_block_indices,
        authoritative_block_indices=authority.authoritative_block_indices,
        review_excluded_block_indices=routing.review_excluded_block_indices,
    )
    return NonRecipeStageResult(
        seed=seed,
        routing=routing,
        authority=authority,
        review_status=review_status,
        refinement_report=_default_nonrecipe_refinement_report(
            seed=seed,
            routing=routing,
            authority=authority,
            review_status=review_status,
        ),
    )


def refine_nonrecipe_stage_result(
    *,
    stage_result: NonRecipeStageResult,
    full_blocks: Sequence[Mapping[str, Any]],
    block_category_updates: Mapping[int, str],
    reviewer_categories_by_block: Mapping[int, str] | None = None,
    applied_packet_ids_by_block: Mapping[int, Sequence[str]] | None = None,
    conflicts: Sequence[Mapping[str, Any]] | None = None,
    ignored_block_indices: Sequence[int] | None = None,
) -> NonRecipeStageResult:
    full_blocks_by_index = prepare_nonrecipe_full_blocks_by_index(full_blocks)
    seed_block_category_by_index = dict(stage_result.seed.seed_block_category_by_index)
    final_block_category_by_index = dict(seed_block_category_by_index)
    changed_blocks: list[dict[str, Any]] = []
    warnings = list(stage_result.routing.warnings)
    reviewer_counts: dict[str, int] = {}
    reviewed_block_indices: set[int] = set()

    for block_index, raw_category in sorted(block_category_updates.items()):
        normalized_category, warning = _normalize_stage7_category(str(raw_category))
        reviewer_category = str(
            (reviewer_categories_by_block or {}).get(block_index) or ""
        ).strip() or None
        if block_index not in final_block_category_by_index:
            if warning is not None:
                warnings.append(f"block {block_index}: {warning}")
            continue
        if warning is not None:
            warnings.append(f"block {block_index}: {warning}")
        seed_category = seed_block_category_by_index[block_index]
        final_block_category_by_index[block_index] = normalized_category
        reviewed_block_indices.add(int(block_index))
        if reviewer_category is not None:
            reviewer_counts[reviewer_category] = reviewer_counts.get(reviewer_category, 0) + 1
        if normalized_category == seed_category:
            continue
        changed_blocks.append(
            {
                "block_index": int(block_index),
                "seed_category": seed_category,
                "final_category": normalized_category,
                "reviewer_category": reviewer_category,
                "applied_packet_ids": list(applied_packet_ids_by_block.get(block_index) or [])
                if applied_packet_ids_by_block is not None
                else [],
            }
        )

    conflict_rows = [dict(row) for row in (conflicts or [])]
    ignored_indices = sorted({int(index) for index in (ignored_block_indices or [])})
    final_authority_block_indices = sorted(
        {
            *(int(index) for index in stage_result.routing.review_excluded_block_indices),
            *reviewed_block_indices,
        }
    )
    authority = build_nonrecipe_authority_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=final_block_category_by_index,
        authoritative_block_indices=final_authority_block_indices,
    )
    review_status = build_nonrecipe_review_status_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=final_block_category_by_index,
        review_eligible_block_indices=stage_result.routing.review_eligible_block_indices,
        authoritative_block_indices=authority.authoritative_block_indices,
        review_excluded_block_indices=stage_result.routing.review_excluded_block_indices,
    )
    scored_effect = (
        "partial_final_authority"
        if reviewed_block_indices and review_status.unreviewed_review_eligible_block_indices
        else "final_authority" if reviewed_block_indices else "seed_only"
    )
    return NonRecipeStageResult(
        seed=stage_result.seed,
        routing=NonRecipeRoutingResult(
            review_routing_by_block=dict(stage_result.routing.review_routing_by_block),
            review_eligible_nonrecipe_spans=list(stage_result.routing.review_eligible_nonrecipe_spans),
            review_excluded_other_spans=list(stage_result.routing.review_excluded_other_spans),
            review_eligible_block_indices=list(stage_result.routing.review_eligible_block_indices),
            review_excluded_block_indices=list(stage_result.routing.review_excluded_block_indices),
            review_exclusion_reason_by_block=dict(stage_result.routing.review_exclusion_reason_by_block),
            block_preview_by_index=dict(stage_result.routing.block_preview_by_index),
            warnings=warnings,
        ),
        authority=authority,
        review_status=review_status,
        refinement_report={
            "enabled": True,
            "authority_mode": (
                "knowledge_refined_final"
                if changed_blocks
                else "knowledge_reviewed_seed_kept"
            ),
            "input_mode": "stage7_review_eligible_nonrecipe_spans",
            "seed_nonrecipe_span_count": len(stage_result.seed.seed_nonrecipe_spans),
            "final_nonrecipe_span_count": len(authority.authoritative_nonrecipe_spans),
            "seed_knowledge_span_count": sum(
                1
                for span in stage_result.seed.seed_nonrecipe_spans
                if span.category == "knowledge"
            ),
            "final_knowledge_span_count": len(authority.authoritative_knowledge_spans),
            "changed_block_count": len(changed_blocks),
            "reviewed_block_count": len(reviewed_block_indices),
            "review_eligible_nonrecipe_span_count": len(stage_result.routing.review_eligible_nonrecipe_spans),
            "review_eligible_block_count": len(stage_result.routing.review_eligible_block_indices),
            "review_excluded_block_count": len(stage_result.routing.review_excluded_block_indices),
            "final_authority_block_count": len(authority.authoritative_block_indices),
            "unreviewed_review_eligible_block_count": len(
                review_status.unreviewed_review_eligible_block_indices
            ),
            "review_exclusion_reason_counts": count_nonrecipe_reason_values(
                stage_result.routing.review_exclusion_reason_by_block
            ),
            "reviewer_category_counts": reviewer_counts,
            "changed_blocks": changed_blocks,
            "conflicts": conflict_rows,
            "ignored_block_indices": ignored_indices,
            "scored_effect": scored_effect,
        },
    )


def _normalize_stage7_category(raw_label: str | None) -> tuple[str, str | None]:
    try:
        return require_nonrecipe_stage_category(raw_label, block_index=-1), None
    except ValueError as exc:
        message = str(exc)
        if "Missing final non-recipe label" in message:
            return "other", "missing final label"
        return "other", message.removeprefix("Invalid final non-recipe label at block -1: ").strip()


__all__ = [
    "NonRecipeAuthorityContract",
    "NonRecipeAuthorityResult",
    "NonRecipeReviewStatusResult",
    "NonRecipeRoutingResult",
    "NonRecipeScoringView",
    "NonRecipeSeedResult",
    "NonRecipeSpan",
    "NonRecipeStageResult",
    "block_rows_for_nonrecipe_authority",
    "block_rows_for_nonrecipe_late_outputs",
    "block_rows_for_nonrecipe_review_queue",
    "block_rows_for_nonrecipe_span",
    "block_rows_for_nonrecipe_stage",
    "build_nonrecipe_authority_contract",
    "build_nonrecipe_stage_result",
    "refine_nonrecipe_stage_result",
]
