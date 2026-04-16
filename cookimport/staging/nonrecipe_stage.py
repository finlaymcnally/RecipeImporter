from __future__ import annotations

from typing import Any, Mapping, Sequence

from cookimport.parsing.canonical_line_roles.contracts import RECIPE_LOCAL_LINE_ROLE_LABELS
from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel, AuthoritativeLabeledLine

from .nonrecipe_authority import (
    rows_for_nonrecipe_authority,
    rows_for_nonrecipe_candidate_queue,
    rows_for_nonrecipe_late_outputs,
    rows_for_nonrecipe_span,
    rows_for_nonrecipe_stage,
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
    prepare_nonrecipe_full_rows_by_index,
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
    row_index: int,
    block_label: AuthoritativeBlockLabel,
    divested_row_indices: set[int],
    warnings: list[str],
) -> str:
    raw_label = getattr(block_label, "final_label", None)
    normalized_label = str(raw_label or "").strip().upper()
    if normalized_label in _DIVESTED_RECIPE_LOCAL_ROUTE_LABELS:
        normalization_reason = (
            "divested recipe-local label"
            if int(row_index) in divested_row_indices
            else "available recipe-local label"
        )
        warnings.append(
            "row "
            f"{row_index}: {normalization_reason} '{normalized_label}' "
            "normalized to NONRECIPE_CANDIDATE for nonrecipe routing"
        )
        return "candidate"
    return require_nonrecipe_route_label(
        raw_label,
        block_index=row_index,
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
        "changed_row_count": 0,
        "reviewed_candidate_row_count": 0,
        "candidate_nonrecipe_span_count": len(routing.candidate_nonrecipe_spans),
        "candidate_row_count": len(routing.candidate_row_indices),
        "excluded_row_count": len(routing.excluded_row_indices),
        "final_authority_row_count": len(authority.authoritative_row_indices),
        "unresolved_candidate_row_count": len(
            candidate_status.unresolved_candidate_row_indices
        ),
        "grounding_counts": {},
        "grounding_by_row": {},
        "changed_rows": [],
        "conflicts": [],
        "ignored_row_indices": [],
        "scored_effect": "route_only",
    }


def _normalize_nonrecipe_source_rows(
    source_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for raw_row in source_rows:
        if not isinstance(raw_row, Mapping):
            continue
        try:
            row_index = int(raw_row.get("row_index", raw_row.get("index")))
        except (TypeError, ValueError):
            continue
        source_block_index = raw_row.get("source_block_index", raw_row.get("block_index"))
        try:
            normalized_source_block_index = int(source_block_index)
        except (TypeError, ValueError):
            normalized_source_block_index = row_index
        block_id = str(
            raw_row.get("row_id")
            or raw_row.get("id")
            or raw_row.get("block_id")
            or f"row:{row_index}"
        ).strip() or f"row:{row_index}"
        normalized_rows.append(
            {
                **dict(raw_row),
                "index": row_index,
                "block_id": block_id,
                "row_id": str(raw_row.get("row_id") or block_id),
                "source_block_index": normalized_source_block_index,
                "source_block_id": str(
                    raw_row.get("source_block_id")
                    or raw_row.get("block_id")
                    or f"b{normalized_source_block_index}"
                ).strip()
                or f"b{normalized_source_block_index}",
            }
        )
    return normalized_rows


def _row_level_block_labels_from_labeled_lines(
    labeled_lines: Sequence[AuthoritativeLabeledLine],
) -> list[AuthoritativeBlockLabel]:
    return [
        AuthoritativeBlockLabel(
            source_block_id=str(row.row_id),
            source_block_index=int(row.atomic_index),
            supporting_atomic_indices=[int(row.atomic_index)],
            deterministic_label=str(row.deterministic_label),
            final_label=str(row.final_label),
            decided_by=row.decided_by,
            reason_tags=list(row.reason_tags),
            escalation_reasons=list(row.escalation_reasons),
        )
        for row in sorted(labeled_lines, key=lambda value: int(value.atomic_index))
    ]


def build_nonrecipe_stage_result(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    final_block_labels: Sequence[AuthoritativeBlockLabel],
    recipe_ownership_result: RecipeOwnershipResult,
    overrides: Any | None = None,
) -> NonRecipeStageResult:
    del overrides

    full_rows_by_index = prepare_nonrecipe_full_rows_by_index(full_blocks)
    labels_by_index = {int(row.source_block_index): row for row in final_block_labels}
    owned_row_indices = set(recipe_ownership_result.owned_row_indices)
    divested_row_indices = set(recipe_ownership_result.divested_row_indices)
    available_to_nonrecipe = list(
        recipe_ownership_result.available_to_nonrecipe_row_indices
    )

    route_by_index: dict[int, str] = {}
    warnings: list[str] = []
    row_preview_by_index = {
        int(row_index): preview_nonrecipe_text(full_rows_by_index[row_index].get("text"))
        for row_index in available_to_nonrecipe
        if row_index in full_rows_by_index
    }

    for row_index in sorted(owned_row_indices):
        block_label = labels_by_index.get(row_index)
        if block_label is None:
            continue
        route, warning = normalize_nonrecipe_route_label(getattr(block_label, "final_label", None))
        if warning is None:
            raise RecipeOwnershipInvariantError(
                f"Recipe-owned row {row_index} carried nonrecipe route '{route}'."
            )

    for row_index in available_to_nonrecipe:
        if row_index not in full_rows_by_index:
            raise RecipeOwnershipInvariantError(
                f"Recipe ownership referenced missing nonrecipe-admissible row {row_index}."
            )

        block_label = labels_by_index.get(row_index)
        if block_label is None:
            raise ValueError(
                f"Missing final row label for non-recipe row {row_index}."
            )
        route = _resolve_available_nonrecipe_route_label(
            row_index=row_index,
            block_label=block_label,
            divested_row_indices=divested_row_indices,
            warnings=warnings,
        )
        route_by_index[row_index] = route

    seed = build_nonrecipe_seed_result(
        full_rows_by_index=full_rows_by_index,
        route_by_index=route_by_index,
    )
    routing = build_nonrecipe_routing_result(
        full_rows_by_index=full_rows_by_index,
        candidate_row_indices=[
            index for index, route in sorted(route_by_index.items()) if route == "candidate"
        ],
        excluded_row_indices=[
            index for index, route in sorted(route_by_index.items()) if route == "exclude"
        ],
        row_preview_by_index=row_preview_by_index,
        warnings=warnings,
    )
    authority = build_nonrecipe_authority_result(
        full_rows_by_index=full_rows_by_index,
        row_category_by_index={
            int(row_index): "other"
            for row_index in routing.excluded_row_indices
        },
        authoritative_row_indices=routing.excluded_row_indices,
        excluded_row_indices=routing.excluded_row_indices,
    )
    candidate_status = build_nonrecipe_finalize_status_result(
        full_rows_by_index=full_rows_by_index,
        candidate_row_indices=routing.candidate_row_indices,
        authoritative_row_indices=authority.authoritative_row_indices,
        excluded_row_indices=routing.excluded_row_indices,
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


def build_nonrecipe_stage_result_from_labeled_rows(
    *,
    source_rows: Sequence[Mapping[str, Any]],
    labeled_lines: Sequence[AuthoritativeLabeledLine],
    recipe_ownership_result: RecipeOwnershipResult,
    overrides: Any | None = None,
) -> NonRecipeStageResult:
    del overrides

    normalized_rows = _normalize_nonrecipe_source_rows(source_rows)
    full_rows_by_index = prepare_nonrecipe_full_rows_by_index(normalized_rows)
    row_labels = _row_level_block_labels_from_labeled_lines(labeled_lines)
    labels_by_index = {int(row.source_block_index): row for row in row_labels}
    owned_row_indices = set(recipe_ownership_result.owned_row_indices)
    divested_row_indices = set(recipe_ownership_result.divested_row_indices)

    route_by_index: dict[int, str] = {}
    warnings: list[str] = []
    row_preview_by_index: dict[int, str] = {}

    for row_index, row_payload in sorted(full_rows_by_index.items()):
        if row_index in owned_row_indices and row_index not in divested_row_indices:
            continue
        row_label = labels_by_index.get(int(row_index))
        if row_label is None:
            raise ValueError(
                f"Missing final row label for non-recipe row {row_index}."
            )
        route = _resolve_available_nonrecipe_route_label(
            row_index=int(row_index),
            block_label=row_label,
            divested_row_indices={
                int(index) for index in divested_row_indices
            },
            warnings=warnings,
        )
        route_by_index[int(row_index)] = route
        row_preview_by_index[int(row_index)] = preview_nonrecipe_text(row_payload.get("text"))

    seed = build_nonrecipe_seed_result(
        full_rows_by_index=full_rows_by_index,
        route_by_index=route_by_index,
    )
    routing = build_nonrecipe_routing_result(
        full_rows_by_index=full_rows_by_index,
        candidate_row_indices=[
            index for index, route in sorted(route_by_index.items()) if route == "candidate"
        ],
        excluded_row_indices=[
            index for index, route in sorted(route_by_index.items()) if route == "exclude"
        ],
        row_preview_by_index=row_preview_by_index,
        warnings=warnings,
    )
    authority = build_nonrecipe_authority_result(
        full_rows_by_index=full_rows_by_index,
        row_category_by_index={
            int(row_index): "other"
            for row_index in routing.excluded_row_indices
        },
        authoritative_row_indices=routing.excluded_row_indices,
        excluded_row_indices=routing.excluded_row_indices,
        row_source_block_index_by_index={
            int(index): int(payload.get("source_block_index", index))
            for index, payload in full_rows_by_index.items()
        },
    )
    candidate_status = build_nonrecipe_finalize_status_result(
        full_rows_by_index=full_rows_by_index,
        candidate_row_indices=routing.candidate_row_indices,
        authoritative_row_indices=authority.authoritative_row_indices,
        excluded_row_indices=routing.excluded_row_indices,
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
    full_rows_by_index = prepare_nonrecipe_full_rows_by_index(full_blocks)
    candidate_index_set = {
        int(index) for index in stage_result.routing.candidate_row_indices
    }
    final_row_category_by_index = dict(
        stage_result.authority.authoritative_row_category_by_index
    )
    changed_rows: list[dict[str, Any]] = []
    warnings = list(stage_result.routing.warnings)
    reviewed_row_indices: set[int] = set()

    for row_index, raw_category in sorted(block_category_updates.items()):
        normalized_category = require_nonrecipe_final_category(
            raw_category,
            block_index=int(row_index),
        )
        if row_index not in candidate_index_set:
            continue
        prior_final_category = final_row_category_by_index.get(row_index)
        final_row_category_by_index[row_index] = normalized_category
        reviewed_row_indices.add(int(row_index))
        if prior_final_category is None or normalized_category == prior_final_category:
            continue
        changed_rows.append(
            {
                "row_index": int(row_index),
                "previous_final_category": prior_final_category,
                "final_category": normalized_category,
                "grounding": (
                    dict((grounding_by_block or {}).get(row_index) or {})
                    if normalized_category == "knowledge"
                    else {}
                ),
                "applied_packet_ids": list(applied_packet_ids_by_block.get(row_index) or [])
                if applied_packet_ids_by_block is not None
                else [],
            }
        )

    conflict_rows = [dict(row) for row in (conflicts or [])]
    ignored_indices = sorted({int(index) for index in (ignored_block_indices or [])})
    authority = build_nonrecipe_authority_result(
        full_rows_by_index=full_rows_by_index,
        row_category_by_index=final_row_category_by_index,
        authoritative_row_indices=sorted(final_row_category_by_index),
        excluded_row_indices=stage_result.routing.excluded_row_indices,
        row_source_block_index_by_index={
            int(index): int(payload.get("source_block_index", index))
            for index, payload in full_rows_by_index.items()
        },
    )
    candidate_status = build_nonrecipe_finalize_status_result(
        full_rows_by_index=full_rows_by_index,
        candidate_row_indices=stage_result.routing.candidate_row_indices,
        authoritative_row_indices=authority.authoritative_row_indices,
        excluded_row_indices=stage_result.routing.excluded_row_indices,
    )
    scored_effect = (
        "partial_final_authority"
        if reviewed_row_indices and candidate_status.unresolved_candidate_row_indices
        else "final_authority" if reviewed_row_indices else "route_only"
    )
    return NonRecipeStageResult(
        seed=stage_result.seed,
        routing=NonRecipeRoutingResult(
            route_by_row=dict(stage_result.routing.route_by_row),
            candidate_nonrecipe_spans=list(stage_result.routing.candidate_nonrecipe_spans),
            excluded_nonrecipe_spans=list(stage_result.routing.excluded_nonrecipe_spans),
            candidate_row_indices=list(stage_result.routing.candidate_row_indices),
            excluded_row_indices=list(stage_result.routing.excluded_row_indices),
            row_preview_by_index=dict(stage_result.routing.row_preview_by_index),
            warnings=warnings,
        ),
        authority=authority,
        candidate_status=candidate_status,
        refinement_report={
            "enabled": True,
            "authority_mode": (
                "knowledge_refined_final"
                if changed_rows
                else "nonrecipe_finalized_candidates"
            ),
            "input_mode": "nonrecipe_candidate_spans",
            "seed_nonrecipe_span_count": len(stage_result.seed.seed_nonrecipe_spans),
            "final_nonrecipe_span_count": len(authority.authoritative_nonrecipe_spans),
            "final_knowledge_span_count": len(authority.authoritative_knowledge_spans),
            "changed_row_count": len(changed_rows),
            "reviewed_candidate_row_count": len(reviewed_row_indices),
            "candidate_nonrecipe_span_count": len(stage_result.routing.candidate_nonrecipe_spans),
            "candidate_row_count": len(stage_result.routing.candidate_row_indices),
            "excluded_row_count": len(stage_result.routing.excluded_row_indices),
            "final_authority_row_count": len(authority.authoritative_row_indices),
            "unresolved_candidate_row_count": len(
                candidate_status.unresolved_candidate_row_indices
            ),
            "grounding_counts": dict(grounding_summary or {}),
            "grounding_by_row": {
                str(index): dict(value)
                for index, value in sorted((grounding_by_block or {}).items())
            },
            "changed_rows": changed_rows,
            "conflicts": conflict_rows,
            "ignored_row_indices": ignored_indices,
            "scored_effect": scored_effect,
        },
    )


__all__ = [
    "NonRecipeAuthorityContract", "NonRecipeAuthorityResult", "NonRecipeCandidateStatusResult",
    "NonRecipeRoutingResult", "NonRecipeScoringView", "NonRecipeSeedResult",
    "NonRecipeSpan", "NonRecipeStageResult", "rows_for_nonrecipe_authority",
    "rows_for_nonrecipe_candidate_queue", "rows_for_nonrecipe_late_outputs",
    "rows_for_nonrecipe_span", "rows_for_nonrecipe_stage",
    "build_nonrecipe_authority_contract", "build_nonrecipe_stage_result",
    "build_nonrecipe_stage_result_from_labeled_rows",
    "refine_nonrecipe_stage_result",
]
