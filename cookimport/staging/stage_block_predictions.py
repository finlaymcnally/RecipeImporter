from __future__ import annotations

from typing import Any, Mapping

from cookimport.core.models import AuthoritativeRecipeSemantics
from cookimport.core.models import ConversionResult
from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel
from cookimport.staging.block_label_resolution import (
    FREEFORM_LABELS,
    RECIPE_LOCAL_LABELS,
    resolve_stage_block_label,
)
from cookimport.staging.knowledge_block_evidence import build_knowledge_block_evidence
from cookimport.staging.nonrecipe_stage import NonRecipeStageResult
from cookimport.staging.recipe_authority_decisions import RecipeAuthorityDecision
from cookimport.staging.recipe_block_evidence import (
    build_recipe_block_evidence,
    is_howto_section_text as _is_howto_section_text,
    load_stage_prediction_archive,
    resolve_stage_prediction_source_file,
    resolve_stage_prediction_source_hash,
)
from cookimport.staging.recipe_ownership import (
    RecipeOwnershipInvariantError,
    RecipeOwnershipResult,
)

UNRESOLVED_CANDIDATE_BLOCK_INDICES_KEY = "unresolved_candidate_block_indices"
UNRESOLVED_CANDIDATE_BLOCK_CATEGORY_KEY = "unresolved_candidate_route_by_index"
UNRESOLVED_RECIPE_OWNED_BLOCK_INDICES_KEY = "unresolved_recipe_owned_block_indices"
UNRESOLVED_RECIPE_OWNED_BY_INDEX_KEY = "unresolved_recipe_owned_recipe_id_by_index"


def build_stage_block_predictions(
    conversion_result: ConversionResult,
    workbook_slug: str,
    *,
    recipe_ownership_result: RecipeOwnershipResult,
    authoritative_payloads_by_recipe_id: Mapping[str, AuthoritativeRecipeSemantics | dict[str, Any]] | None = None,
    recipe_authority_decisions_by_recipe_id: Mapping[str, RecipeAuthorityDecision | dict[str, Any]] | None = None,
    source_file: str | None = None,
    source_hash: str | None = None,
    archive_blocks: list[dict[str, Any]] | None = None,
    nonrecipe_stage_result: NonRecipeStageResult | None = None,
    boundary_block_labels: list[AuthoritativeBlockLabel] | None = None,
) -> dict[str, Any]:
    """Build a deterministic per-block label manifest from staged outputs."""
    archive = load_stage_prediction_archive(conversion_result, archive_blocks)
    recipe_evidence = build_recipe_block_evidence(
        conversion_result,
        archive=archive,
        recipe_ownership_result=recipe_ownership_result,
        authoritative_payloads_by_recipe_id=authoritative_payloads_by_recipe_id,
        recipe_authority_decisions_by_recipe_id=recipe_authority_decisions_by_recipe_id,
        boundary_block_labels=boundary_block_labels,
    )
    knowledge_evidence = build_knowledge_block_evidence(nonrecipe_stage_result)

    block_labels = {
        index: set(labels)
        for index, labels in recipe_evidence.block_labels.items()
    }
    notes = list(recipe_evidence.notes)
    notes.extend(knowledge_evidence.notes)

    if knowledge_evidence.knowledge_indices and recipe_evidence.block_count == 0:
        notes.append("Knowledge blocks were present but no extracted archive blocks were available.")
    for block_index in sorted(knowledge_evidence.knowledge_indices):
        if recipe_ownership_result.is_block_recipe_owned(block_index):
            owner = recipe_ownership_result.block_owner_by_index.get(int(block_index), "unknown")
            raise RecipeOwnershipInvariantError(
                f"Block {block_index} was marked KNOWLEDGE but is recipe-owned by '{owner}'."
            )
        if block_index < 0 or block_index >= recipe_evidence.block_count:
            notes.append(
                f"Knowledge block reference was out of range ({block_index}); ignored."
            )
            continue
        block_labels.setdefault(block_index, set()).add("KNOWLEDGE")

    if not _contains_label(block_labels, "TIME_LINE"):
        notes.append("TIME_LINE was not detected in stage evidence.")
    if not _contains_label(block_labels, "YIELD_LINE"):
        notes.append("YIELD_LINE was not detected in stage evidence.")

    conflicts: list[dict[str, Any]] = []
    resolved: dict[int, str] = {}
    for block_index in range(recipe_evidence.block_count):
        labels = sorted(label for label in block_labels.get(block_index, set()) if label != "OTHER")
        if "KNOWLEDGE" in labels and any(label in RECIPE_LOCAL_LABELS for label in labels):
            raise RecipeOwnershipInvariantError(
                "Recipe/local vs KNOWLEDGE overlap is forbidden: "
                f"block {block_index} had labels {labels}."
            )
        if len(labels) > 1:
            conflicts.append({"block_index": block_index, "labels": labels})
        resolved[block_index] = resolve_stage_block_label(labels)

    label_blocks: dict[str, list[int]] = {label: [] for label in FREEFORM_LABELS}
    for block_index in range(recipe_evidence.block_count):
        label_blocks.setdefault(resolved.get(block_index, "OTHER"), []).append(block_index)

    return {
        "schema_version": "stage_block_predictions.v1",
        "source_file": source_file or resolve_stage_prediction_source_file(conversion_result),
        "source_hash": source_hash or resolve_stage_prediction_source_hash(conversion_result),
        "workbook_slug": workbook_slug,
        "block_count": recipe_evidence.block_count,
        "block_labels": {
            str(index): resolved.get(index, "OTHER")
            for index in range(recipe_evidence.block_count)
        },
        "label_blocks": {
            label: sorted(indices)
            for label, indices in label_blocks.items()
        },
        "counts": {
            "blocks": recipe_evidence.block_count,
            "authoritative_knowledge_blocks": len(knowledge_evidence.knowledge_indices),
            "unresolved_candidate_blocks": len(knowledge_evidence.unresolved_block_indices),
            "unresolved_recipe_owned_blocks": len(recipe_evidence.unresolved_recipe_owned_indices),
        },
        UNRESOLVED_CANDIDATE_BLOCK_INDICES_KEY: list(knowledge_evidence.unresolved_block_indices),
        UNRESOLVED_CANDIDATE_BLOCK_CATEGORY_KEY: {
            str(index): category
            for index, category in sorted(knowledge_evidence.unresolved_categories.items())
        },
        UNRESOLVED_RECIPE_OWNED_BLOCK_INDICES_KEY: list(recipe_evidence.unresolved_recipe_owned_indices),
        UNRESOLVED_RECIPE_OWNED_BY_INDEX_KEY: {
            str(index): recipe_id
            for index, recipe_id in sorted(recipe_evidence.unresolved_recipe_owned_recipe_id_by_index.items())
        },
        "conflicts": conflicts,
        "notes": sorted(set(note for note in notes if note)),
    }


def _contains_label(block_labels: dict[int, set[str]], target_label: str) -> bool:
    return any(target_label in labels for labels in block_labels.values())
