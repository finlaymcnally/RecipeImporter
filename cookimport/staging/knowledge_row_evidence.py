from __future__ import annotations

from dataclasses import dataclass

from .nonrecipe_stage import NonRecipeStageResult


@dataclass(frozen=True, slots=True)
class KnowledgeRowEvidence:
    knowledge_indices: set[int]
    unresolved_categories: dict[int, str]
    unresolved_row_indices: list[int]
    notes: list[str]


def build_knowledge_row_evidence(
    nonrecipe_stage_result: NonRecipeStageResult | None,
) -> KnowledgeRowEvidence:
    notes: list[str] = []
    if nonrecipe_stage_result is None:
        notes.append(
            "KNOWLEDGE labels require final non-recipe authority; no fallback chunk-lane projection ran."
        )
        return KnowledgeRowEvidence(
            knowledge_indices=set(),
            unresolved_categories={},
            unresolved_row_indices=[],
            notes=notes,
        )

    authoritative_categories = dict(
        nonrecipe_stage_result.authority.authoritative_block_category_by_index
    )
    unresolved_categories = {
        int(block_index): str(category)
        for block_index, category in (
            nonrecipe_stage_result.candidate_status.unresolved_candidate_route_by_index.items()
        )
    }
    unresolved_row_indices = sorted(unresolved_categories)
    knowledge_indices = {
        int(block_index)
        for block_index, category in authoritative_categories.items()
        if category == "knowledge"
    }
    if knowledge_indices:
        notes.append("KNOWLEDGE labels were derived from final non-recipe authority.")
    if nonrecipe_stage_result.candidate_status.unresolved_candidate_block_indices:
        notes.append(
            "Candidate non-recipe rows without final authority were marked unresolved and excluded from semantic scoring."
        )
    elif nonrecipe_stage_result.routing.candidate_block_indices:
        notes.append(
            "All candidate non-recipe rows had final authority before scoring."
        )
    return KnowledgeRowEvidence(
        knowledge_indices=knowledge_indices,
        unresolved_categories=unresolved_categories,
        unresolved_row_indices=unresolved_row_indices,
        notes=notes,
    )
