from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


_SCHEMA_VERSION = "recipe_authority_decisions.v1"


@dataclass(frozen=True, slots=True)
class RecipeAuthorityDecision:
    recipe_id: str
    semantic_outcome: str
    publish_status: str
    ownership_action: str
    owned_row_indices: list[int]
    divested_row_indices: list[int]
    retained_row_indices: list[int]
    worker_repair_status: str | None = None
    status_reason: str | None = None
    single_correction_status: str | None = None
    final_assembly_status: str | None = None
    structural_status: str | None = None
    structural_reason_codes: list[str] = field(default_factory=list)
    mapping_status: str | None = None
    mapping_reason: str | None = None
    final_recipe_authority_status: str | None = None
    final_recipe_authority_reason: str | None = None


def classify_recipe_ownership_action(
    *,
    owned_row_indices: list[int],
    divested_row_indices: list[int],
) -> str:
    if not divested_row_indices:
        return "retain"
    owned_row_index_set = {int(index) for index in owned_row_indices}
    divested_row_index_set = {int(index) for index in divested_row_indices}
    if owned_row_index_set and owned_row_index_set.issubset(divested_row_index_set):
        return "fully_divested"
    return "partially_divested"


def recipe_authority_decision_to_payload(
    decision: RecipeAuthorityDecision | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(decision, RecipeAuthorityDecision):
        payload = {
            "recipe_id": decision.recipe_id,
            "semantic_outcome": decision.semantic_outcome,
            "publish_status": decision.publish_status,
            "ownership_action": decision.ownership_action,
            "owned_row_indices": list(decision.owned_row_indices),
            "divested_row_indices": list(decision.divested_row_indices),
            "retained_row_indices": list(decision.retained_row_indices),
            "worker_repair_status": decision.worker_repair_status,
            "status_reason": decision.status_reason,
            "single_correction_status": decision.single_correction_status,
            "final_assembly_status": decision.final_assembly_status,
            "structural_status": decision.structural_status,
            "structural_reason_codes": list(decision.structural_reason_codes),
            "mapping_status": decision.mapping_status,
            "mapping_reason": decision.mapping_reason,
            "final_recipe_authority_status": decision.final_recipe_authority_status,
            "final_recipe_authority_reason": decision.final_recipe_authority_reason,
        }
    else:
        payload = dict(decision)
    return {key: value for key, value in payload.items() if value is not None}


def recipe_authority_decisions_to_payload(
    *,
    decisions_by_recipe_id: Mapping[str, RecipeAuthorityDecision | Mapping[str, Any]],
    workbook_slug: str,
    refinement_mode: str,
) -> dict[str, Any]:
    rows = [
        recipe_authority_decision_to_payload(decisions_by_recipe_id[recipe_id])
        for recipe_id in sorted(decisions_by_recipe_id)
    ]
    semantic_outcome_counts: dict[str, int] = {}
    publish_status_counts: dict[str, int] = {}
    ownership_action_counts: dict[str, int] = {}
    for row in rows:
        semantic_outcome = str(row.get("semantic_outcome") or "").strip()
        publish_status = str(row.get("publish_status") or "").strip()
        ownership_action = str(row.get("ownership_action") or "").strip()
        if semantic_outcome:
            semantic_outcome_counts[semantic_outcome] = (
                semantic_outcome_counts.get(semantic_outcome, 0) + 1
            )
        if publish_status:
            publish_status_counts[publish_status] = (
                publish_status_counts.get(publish_status, 0) + 1
            )
        if ownership_action:
            ownership_action_counts[ownership_action] = (
                ownership_action_counts.get(ownership_action, 0) + 1
            )
    return {
        "schema_version": _SCHEMA_VERSION,
        "workbook_slug": workbook_slug,
        "refinement_mode": refinement_mode,
        "recipe_count": len(rows),
        "counts": {
            "semantic_outcomes": semantic_outcome_counts,
            "publish_statuses": publish_status_counts,
            "ownership_actions": ownership_action_counts,
        },
        "recipes": rows,
    }
