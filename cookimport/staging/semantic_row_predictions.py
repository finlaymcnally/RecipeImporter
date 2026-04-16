from __future__ import annotations

from typing import Any, Mapping

from cookimport.core.models import AuthoritativeRecipeSemantics
from cookimport.core.models import ConversionResult
from cookimport.parsing.label_source_of_truth import AuthoritativeBlockLabel
from cookimport.staging.row_label_resolution import (
    FREEFORM_LABELS,
    RECIPE_LOCAL_LABELS,
    resolve_semantic_row_label,
)
from cookimport.staging.knowledge_row_evidence import build_knowledge_row_evidence
from cookimport.staging.nonrecipe_stage import NonRecipeStageResult
from cookimport.staging.recipe_authority_decisions import RecipeAuthorityDecision
from cookimport.staging.recipe_row_evidence import (
    build_recipe_row_evidence,
    is_howto_section_text as _is_howto_section_text,
    load_stage_prediction_archive_rows,
    resolve_stage_prediction_source_file,
    resolve_stage_prediction_source_hash,
)
from cookimport.staging.recipe_ownership import (
    RecipeOwnershipInvariantError,
    RecipeOwnershipResult,
)

UNRESOLVED_CANDIDATE_ROW_INDICES_KEY = "unresolved_candidate_row_indices"
UNRESOLVED_CANDIDATE_ROW_CATEGORY_KEY = "unresolved_candidate_route_by_row_index"
UNRESOLVED_RECIPE_OWNED_ROW_INDICES_KEY = "unresolved_recipe_owned_row_indices"
UNRESOLVED_RECIPE_OWNED_RECIPE_ID_BY_ROW_INDEX_KEY = (
    "unresolved_recipe_owned_recipe_id_by_row_index"
)


def build_semantic_row_predictions(
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
    boundary_labels: list[AuthoritativeBlockLabel] | None = None,
) -> dict[str, Any]:
    """Build a deterministic row-native semantic label manifest from staged outputs."""
    archive_rows = load_stage_prediction_archive_rows(conversion_result, archive_blocks)
    recipe_evidence = build_recipe_row_evidence(
        conversion_result,
        archive_rows=archive_rows,
        recipe_ownership_result=recipe_ownership_result,
        authoritative_payloads_by_recipe_id=authoritative_payloads_by_recipe_id,
        recipe_authority_decisions_by_recipe_id=recipe_authority_decisions_by_recipe_id,
        boundary_labels=boundary_labels,
    )
    knowledge_evidence = build_knowledge_row_evidence(nonrecipe_stage_result)

    row_labels = {
        index: set(labels)
        for index, labels in recipe_evidence.row_labels.items()
    }
    notes = list(recipe_evidence.notes)
    notes.extend(knowledge_evidence.notes)
    if recipe_evidence.unresolved_exact_evidence:
        notes.append(
            "Recipe-local title/variant/yield/time evidence now stays unresolved when exact grounding is unavailable."
        )

    if knowledge_evidence.knowledge_indices and recipe_evidence.row_count == 0:
        notes.append("Knowledge rows were present but no extracted archive rows were available.")
    for row_index in sorted(knowledge_evidence.knowledge_indices):
        if recipe_ownership_result.is_row_recipe_owned(row_index):
            owner = recipe_ownership_result.row_owner_by_index.get(int(row_index), "unknown")
            raise RecipeOwnershipInvariantError(
                f"Row {row_index} was marked KNOWLEDGE but is recipe-owned by '{owner}'."
            )
        if row_index < 0 or row_index >= recipe_evidence.row_count:
            notes.append(
                f"Knowledge row reference was out of range ({row_index}); ignored."
            )
            continue
        row_labels.setdefault(row_index, set()).add("KNOWLEDGE")

    if not _contains_label(row_labels, "TIME_LINE"):
        notes.append("TIME_LINE was not detected in stage evidence.")
    if not _contains_label(row_labels, "YIELD_LINE"):
        notes.append("YIELD_LINE was not detected in stage evidence.")

    conflicts: list[dict[str, Any]] = []
    resolved: dict[int, str] = {}
    for row_index in range(recipe_evidence.row_count):
        labels = sorted(label for label in row_labels.get(row_index, set()) if label != "OTHER")
        if "KNOWLEDGE" in labels and any(label in RECIPE_LOCAL_LABELS for label in labels):
            raise RecipeOwnershipInvariantError(
                "Recipe/local vs KNOWLEDGE overlap is forbidden: "
                f"row {row_index} had labels {labels}."
            )
        if len(labels) > 1:
            conflicts.append({"row_index": row_index, "labels": labels})
        resolved[row_index] = resolve_semantic_row_label(labels)

    label_rows: dict[str, list[int]] = {label: [] for label in FREEFORM_LABELS}
    for row_index in range(recipe_evidence.row_count):
        label_rows.setdefault(resolved.get(row_index, "OTHER"), []).append(row_index)

    return {
        "schema_version": "semantic_row_predictions.v1",
        "source_file": source_file or resolve_stage_prediction_source_file(conversion_result),
        "source_hash": source_hash or resolve_stage_prediction_source_hash(conversion_result),
        "workbook_slug": workbook_slug,
        "row_count": recipe_evidence.row_count,
        "row_labels": {
            str(index): resolved.get(index, "OTHER")
            for index in range(recipe_evidence.row_count)
        },
        "label_rows": {
            label: sorted(indices)
            for label, indices in label_rows.items()
        },
        "counts": {
            "rows": recipe_evidence.row_count,
            "authoritative_knowledge_rows": len(knowledge_evidence.knowledge_indices),
            "unresolved_candidate_rows": len(knowledge_evidence.unresolved_row_indices),
            "unresolved_recipe_owned_rows": len(recipe_evidence.unresolved_recipe_owned_indices),
        },
        UNRESOLVED_CANDIDATE_ROW_INDICES_KEY: list(knowledge_evidence.unresolved_row_indices),
        UNRESOLVED_CANDIDATE_ROW_CATEGORY_KEY: {
            str(index): category
            for index, category in sorted(knowledge_evidence.unresolved_categories.items())
        },
        UNRESOLVED_RECIPE_OWNED_ROW_INDICES_KEY: list(recipe_evidence.unresolved_recipe_owned_indices),
        UNRESOLVED_RECIPE_OWNED_RECIPE_ID_BY_ROW_INDEX_KEY: {
            str(index): recipe_id
            for index, recipe_id in sorted(recipe_evidence.unresolved_recipe_owned_recipe_id_by_index.items())
        },
        "unresolved_recipe_exact_evidence": list(recipe_evidence.unresolved_exact_evidence),
        "conflicts": conflicts,
        "notes": sorted(set(note for note in notes if note)),
    }


def _contains_label(row_labels: dict[int, set[str]], target_label: str) -> bool:
    return any(target_label in labels for labels in row_labels.values())
