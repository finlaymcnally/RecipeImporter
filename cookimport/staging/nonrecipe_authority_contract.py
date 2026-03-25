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
    review_routing_by_block: dict[int, str]
    review_eligible_nonrecipe_spans: list[NonRecipeSpan]
    review_excluded_other_spans: list[NonRecipeSpan]
    review_eligible_block_indices: list[int]
    review_excluded_block_indices: list[int]
    review_exclusion_reason_by_block: dict[int, str]
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
class NonRecipeReviewStatusResult:
    reviewed_block_indices: list[int]
    unreviewed_review_eligible_block_indices: list[int]
    unreviewed_block_category_by_index: dict[int, str]
    unreviewed_spans: list[NonRecipeSpan]


@dataclass(frozen=True, slots=True)
class NonRecipeSeedResult:
    seed_nonrecipe_spans: list[NonRecipeSpan]
    seed_knowledge_spans: list[NonRecipeSpan]
    seed_other_spans: list[NonRecipeSpan]
    seed_block_category_by_index: dict[int, str]


@dataclass(frozen=True, slots=True)
class NonRecipeScoringView:
    authoritative_block_indices: list[int]
    authoritative_block_category_by_index: dict[int, str]
    unresolved_review_eligible_block_indices: list[int]
    unresolved_review_eligible_block_category_by_index: dict[int, str]


@dataclass(frozen=True, slots=True)
class NonRecipeAuthorityContract:
    final_blocks: list[dict[str, Any]]
    review_queue_blocks: list[dict[str, Any]]
    excluded_blocks: list[dict[str, Any]]
    review_status: NonRecipeReviewStatusResult
    late_output_blocks: list[dict[str, Any]]
    scoring_view: NonRecipeScoringView
    late_output_mode: str


@dataclass(frozen=True, slots=True)
class NonRecipeStageResult:
    seed: NonRecipeSeedResult
    routing: NonRecipeRoutingResult
    authority: NonRecipeAuthorityResult
    review_status: NonRecipeReviewStatusResult
    refinement_report: dict[str, Any] = field(default_factory=dict)

    def authoritative_block_category_by_index(self) -> dict[int, str]:
        return dict(self.authority.authoritative_block_category_by_index)

    def unreviewed_block_category_by_index(self) -> dict[int, str]:
        return dict(self.review_status.unreviewed_block_category_by_index)

    def review_eligible_block_seed_category_by_index(self) -> dict[int, str]:
        return {
            int(index): self.seed.seed_block_category_by_index[int(index)]
            for index in self.routing.review_eligible_block_indices
            if int(index) in self.seed.seed_block_category_by_index
        }

    def surviving_review_block_category_by_index(self) -> dict[int, str]:
        categories: dict[int, str] = {}
        authoritative = self.authority.authoritative_block_category_by_index
        unresolved = self.review_status.unreviewed_block_category_by_index
        seed = self.seed.seed_block_category_by_index
        for raw_index in self.routing.review_eligible_block_indices:
            index = int(raw_index)
            if index in authoritative:
                categories[index] = str(authoritative[index])
                continue
            if index in unresolved:
                categories[index] = str(unresolved[index])
                continue
            if index in seed:
                categories[index] = str(seed[index])
        return categories

    def authoritative_nonrecipe_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_nonrecipe_spans)

    def authoritative_knowledge_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_knowledge_spans)

    def authoritative_other_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_other_spans)

    def unreviewed_nonrecipe_spans(self) -> list[NonRecipeSpan]:
        return list(self.review_status.unreviewed_spans)
