from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True, init=False)
class NonRecipeSpan:
    span_id: str
    category: str
    row_start_index: int
    row_end_index: int
    row_indices: list[int]
    row_ids: list[str]

    def __init__(
        self,
        *,
        span_id: str,
        category: str,
        row_start_index: int | None = None,
        row_end_index: int | None = None,
        row_indices: list[int] | None = None,
        row_ids: list[str] | None = None,
    ) -> None:
        object.__setattr__(self, "span_id", span_id)
        object.__setattr__(self, "category", category)
        object.__setattr__(
            self,
            "row_start_index",
            int(row_start_index or 0),
        )
        object.__setattr__(
            self,
            "row_end_index",
            int(row_end_index or 0),
        )
        object.__setattr__(
            self,
            "row_indices",
            list(row_indices or []),
        )
        object.__setattr__(
            self,
            "row_ids",
            list(row_ids or []),
        )


@dataclass(frozen=True, slots=True)
class NonRecipeRoutingResult:
    route_by_row: dict[int, str]
    candidate_nonrecipe_spans: list[NonRecipeSpan]
    excluded_nonrecipe_spans: list[NonRecipeSpan]
    candidate_row_indices: list[int]
    excluded_row_indices: list[int]
    row_preview_by_index: dict[int, str]
    warnings: list[str]

@dataclass(frozen=True, slots=True)
class NonRecipeAuthorityResult:
    authoritative_row_indices: list[int]
    authoritative_row_category_by_index: dict[int, str]
    authoritative_row_source_block_index_by_index: dict[int, int]
    authoritative_nonrecipe_spans: list[NonRecipeSpan]
    authoritative_knowledge_spans: list[NonRecipeSpan]
    authoritative_other_spans: list[NonRecipeSpan]

    @property
    def authoritative_block_indices(self) -> list[int]:
        return sorted(
            {
                int(source_block_index)
                for source_block_index in self.authoritative_row_source_block_index_by_index.values()
            }
        )

    @property
    def authoritative_block_category_by_index(self) -> dict[int, str]:
        summary: dict[int, str] = {}
        for row_index, category in sorted(self.authoritative_row_category_by_index.items()):
            source_block_index = int(
                self.authoritative_row_source_block_index_by_index.get(row_index, row_index)
            )
            prior = summary.get(source_block_index)
            if prior == "knowledge" or category == "knowledge":
                summary[source_block_index] = "knowledge"
            else:
                summary[source_block_index] = "other"
        return summary


@dataclass(frozen=True, slots=True)
class NonRecipeCandidateStatusResult:
    finalized_candidate_row_indices: list[int]
    unresolved_candidate_row_indices: list[int]
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
    authoritative_row_indices: list[int]
    authoritative_row_category_by_index: dict[int, str]
    unresolved_candidate_row_indices: list[int]
    unresolved_candidate_route_by_index: dict[int, str]

@dataclass(frozen=True, slots=True)
class NonRecipeAuthorityContract:
    final_rows: list[dict[str, Any]]
    candidate_queue_rows: list[dict[str, Any]]
    excluded_rows: list[dict[str, Any]]
    candidate_status: NonRecipeCandidateStatusResult
    late_output_rows: list[dict[str, Any]]
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

    def authoritative_row_category_by_index(self) -> dict[int, str]:
        return dict(self.authority.authoritative_row_category_by_index)

    def unresolved_candidate_route_by_index(self) -> dict[int, str]:
        return dict(self.candidate_status.unresolved_candidate_route_by_index)

    def candidate_row_route_by_index(self) -> dict[int, str]:
        routes: dict[int, str] = {}
        authoritative = self.authority.authoritative_row_category_by_index
        unresolved = self.candidate_status.unresolved_candidate_route_by_index
        for raw_index in self.routing.candidate_row_indices:
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
