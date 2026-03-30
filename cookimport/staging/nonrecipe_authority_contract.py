from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NonRecipeSpan:
    span_id: str
    category: str
    block_start_index: int
    block_end_index: int
    block_indices: list[int]
    block_ids: list[str]


@dataclass(frozen=True, slots=True)
class NonRecipeRoutingResult:
    route_by_block: dict[int, str]
    candidate_nonrecipe_spans: list[NonRecipeSpan]
    excluded_nonrecipe_spans: list[NonRecipeSpan]
    candidate_block_indices: list[int]
    excluded_block_indices: list[int]
    exclusion_reason_by_block: dict[int, str]
    block_preview_by_index: dict[int, str]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class NonRecipeAuthorityResult:
    authoritative_block_indices: list[int]
    authoritative_block_category_by_index: dict[int, str]
    authoritative_nonrecipe_spans: list[NonRecipeSpan]
    authoritative_knowledge_spans: list[NonRecipeSpan]
    authoritative_other_spans: list[NonRecipeSpan]


@dataclass(frozen=True, slots=True)
class NonRecipeCandidateStatusResult:
    finalized_candidate_block_indices: list[int]
    unresolved_candidate_block_indices: list[int]
    unresolved_candidate_route_by_index: dict[int, str]
    unresolved_candidate_spans: list[NonRecipeSpan]


@dataclass(frozen=True, slots=True)
class NonRecipeSeedResult:
    seed_nonrecipe_spans: list[NonRecipeSpan]
    seed_candidate_spans: list[NonRecipeSpan]
    seed_excluded_spans: list[NonRecipeSpan]
    seed_route_by_index: dict[int, str]


@dataclass(frozen=True, slots=True)
class NonRecipeScoringView:
    authoritative_block_indices: list[int]
    authoritative_block_category_by_index: dict[int, str]
    unresolved_candidate_block_indices: list[int]
    unresolved_candidate_route_by_index: dict[int, str]


@dataclass(frozen=True, slots=True)
class NonRecipeAuthorityContract:
    final_blocks: list[dict[str, Any]]
    candidate_queue_blocks: list[dict[str, Any]]
    excluded_blocks: list[dict[str, Any]]
    candidate_status: NonRecipeCandidateStatusResult
    late_output_blocks: list[dict[str, Any]]
    scoring_view: NonRecipeScoringView
    late_output_mode: str


@dataclass(frozen=True, slots=True)
class NonRecipeStageResult:
    seed: NonRecipeSeedResult
    routing: NonRecipeRoutingResult
    authority: NonRecipeAuthorityResult
    candidate_status: NonRecipeCandidateStatusResult
    refinement_report: dict[str, Any] = field(default_factory=dict)

    def authoritative_block_category_by_index(self) -> dict[int, str]:
        return dict(self.authority.authoritative_block_category_by_index)

    def unresolved_candidate_route_by_index(self) -> dict[int, str]:
        return dict(self.candidate_status.unresolved_candidate_route_by_index)

    def candidate_block_route_by_index(self) -> dict[int, str]:
        routes: dict[int, str] = {}
        authoritative = self.authority.authoritative_block_category_by_index
        unresolved = self.candidate_status.unresolved_candidate_route_by_index
        for raw_index in self.routing.candidate_block_indices:
            index = int(raw_index)
            if index in authoritative:
                routes[index] = str(authoritative[index])
                continue
            if index in unresolved:
                routes[index] = str(unresolved[index])
        return routes

    def authoritative_nonrecipe_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_nonrecipe_spans)

    def authoritative_knowledge_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_knowledge_spans)

    def authoritative_other_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_other_spans)

    def unresolved_candidate_spans(self) -> list[NonRecipeSpan]:
        return list(self.candidate_status.unresolved_candidate_spans)
