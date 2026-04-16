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
        block_start_index: int | None = None,
        block_end_index: int | None = None,
        block_indices: list[int] | None = None,
        block_ids: list[str] | None = None,
    ) -> None:
        object.__setattr__(self, "span_id", span_id)
        object.__setattr__(self, "category", category)
        object.__setattr__(
            self,
            "row_start_index",
            int(row_start_index if row_start_index is not None else block_start_index or 0),
        )
        object.__setattr__(
            self,
            "row_end_index",
            int(row_end_index if row_end_index is not None else block_end_index or 0),
        )
        object.__setattr__(
            self,
            "row_indices",
            list(row_indices if row_indices is not None else block_indices or []),
        )
        object.__setattr__(
            self,
            "row_ids",
            list(row_ids if row_ids is not None else block_ids or []),
        )

    @property
    def block_start_index(self) -> int:
        return int(self.row_start_index)

    @property
    def block_end_index(self) -> int:
        return int(self.row_end_index)

    @property
    def block_indices(self) -> list[int]:
        return list(self.row_indices)

    @property
    def block_ids(self) -> list[str]:
        return list(self.row_ids)


@dataclass(frozen=True, slots=True)
class NonRecipeRoutingResult:
    route_by_row: dict[int, str]
    candidate_nonrecipe_spans: list[NonRecipeSpan]
    excluded_nonrecipe_spans: list[NonRecipeSpan]
    candidate_row_indices: list[int]
    excluded_row_indices: list[int]
    row_preview_by_index: dict[int, str]
    warnings: list[str]

    @property
    def route_by_block(self) -> dict[int, str]:
        return dict(self.route_by_row)

    @property
    def candidate_block_indices(self) -> list[int]:
        return list(self.candidate_row_indices)

    @property
    def excluded_block_indices(self) -> list[int]:
        return list(self.excluded_row_indices)

    @property
    def block_preview_by_index(self) -> dict[int, str]:
        return dict(self.row_preview_by_index)


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

    @property
    def finalized_candidate_block_indices(self) -> list[int]:
        return list(self.finalized_candidate_row_indices)

    @property
    def unresolved_candidate_block_indices(self) -> list[int]:
        return list(self.unresolved_candidate_row_indices)


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

    @property
    def authoritative_block_indices(self) -> list[int]:
        return list(self.authoritative_row_indices)

    @property
    def authoritative_block_category_by_index(self) -> dict[int, str]:
        return dict(self.authoritative_row_category_by_index)

    @property
    def unresolved_candidate_block_indices(self) -> list[int]:
        return list(self.unresolved_candidate_row_indices)


@dataclass(frozen=True, slots=True)
class NonRecipeAuthorityContract:
    final_rows: list[dict[str, Any]]
    candidate_queue_rows: list[dict[str, Any]]
    excluded_rows: list[dict[str, Any]]
    candidate_status: NonRecipeCandidateStatusResult
    late_output_rows: list[dict[str, Any]]
    scoring_view: NonRecipeScoringView
    late_output_mode: str

    @property
    def final_blocks(self) -> list[dict[str, Any]]:
        return list(self.final_rows)

    @property
    def candidate_queue_blocks(self) -> list[dict[str, Any]]:
        return list(self.candidate_queue_rows)

    @property
    def excluded_blocks(self) -> list[dict[str, Any]]:
        return list(self.excluded_rows)

    @property
    def late_output_blocks(self) -> list[dict[str, Any]]:
        return list(self.late_output_rows)


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

    def candidate_block_route_by_index(self) -> dict[int, str]:
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
