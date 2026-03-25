from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from cookimport.parsing.label_source_of_truth import (
    AuthoritativeBlockLabel,
    RecipeSpan,
)

_OTHER_LABELS = {
    "other",
    "boilerplate",
    "toc",
    "front_matter",
    "front-matter",
    "endorsement",
    "navigation",
    "marketing",
    "chapter_heading",
    "chapter-heading",
}
_REVIEW_CANDIDATE_CATEGORY = "review_candidate"


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
class NonRecipeStageResult:
    nonrecipe_spans: list[NonRecipeSpan]
    knowledge_spans: list[NonRecipeSpan]
    other_spans: list[NonRecipeSpan]
    block_category_by_index: dict[int, str]
    review_routing_by_block: dict[int, str] = field(default_factory=dict)
    review_eligible_nonrecipe_spans: list[NonRecipeSpan] = field(default_factory=list)
    review_excluded_other_spans: list[NonRecipeSpan] = field(default_factory=list)
    review_eligible_block_indices: list[int] = field(default_factory=list)
    review_excluded_block_indices: list[int] = field(default_factory=list)
    final_authority_block_indices: list[int] = field(default_factory=list)
    unreviewed_review_eligible_block_indices: list[int] = field(default_factory=list)
    review_exclusion_reason_by_block: dict[int, str] = field(default_factory=dict)
    block_preview_by_index: dict[int, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    seed_nonrecipe_spans: list[NonRecipeSpan] | None = None
    seed_block_category_by_index: dict[int, str] | None = None
    routing: NonRecipeRoutingResult | None = None
    authority: NonRecipeAuthorityResult | None = None
    review_status: NonRecipeReviewStatusResult | None = None
    refinement_report: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        explicit_review_routing = not (
            not self.review_eligible_nonrecipe_spans
            and not self.review_excluded_other_spans
            and not self.review_eligible_block_indices
            and not self.review_excluded_block_indices
            and not self.review_exclusion_reason_by_block
            and not self.review_routing_by_block
            and not self.final_authority_block_indices
            and not self.unreviewed_review_eligible_block_indices
        )
        if not explicit_review_routing:
            object.__setattr__(
                self,
                "review_eligible_nonrecipe_spans",
                self._spans_for_block_indices(
                    sorted(self.block_category_by_index),
                    category=_REVIEW_CANDIDATE_CATEGORY,
                ),
            )
            object.__setattr__(self, "review_excluded_other_spans", [])
            object.__setattr__(
                self,
                "review_eligible_block_indices",
                sorted(self.block_category_by_index),
            )
            object.__setattr__(self, "review_excluded_block_indices", [])
            object.__setattr__(self, "review_exclusion_reason_by_block", {})
        elif self.review_eligible_block_indices and not self.review_eligible_nonrecipe_spans:
            object.__setattr__(
                self,
                "review_eligible_nonrecipe_spans",
                self._spans_for_block_indices(
                    self.review_eligible_block_indices,
                    category=_REVIEW_CANDIDATE_CATEGORY,
                ),
            )
        if self.review_excluded_block_indices and not self.review_excluded_other_spans:
            object.__setattr__(
                self,
                "review_excluded_other_spans",
                self._spans_for_block_indices(
                    self.review_excluded_block_indices,
                    category="other",
                ),
            )
        if not self.review_routing_by_block:
            review_routing_by_block = {
                int(index): "excluded_other"
                for index in self.review_excluded_block_indices
            }
            for index in self.review_eligible_block_indices:
                review_routing_by_block.setdefault(int(index), "review_eligible")
            if not review_routing_by_block and not explicit_review_routing:
                review_routing_by_block = {
                    int(index): "review_eligible"
                    for index in sorted(self.block_category_by_index)
                }
            object.__setattr__(self, "review_routing_by_block", review_routing_by_block)
        if not self.final_authority_block_indices:
            if explicit_review_routing:
                final_authority_block_indices = sorted(
                    {int(index) for index in self.review_excluded_block_indices}
                )
            else:
                final_authority_block_indices = sorted(self.block_category_by_index)
            object.__setattr__(
                self,
                "final_authority_block_indices",
                final_authority_block_indices,
            )
        if not self.unreviewed_review_eligible_block_indices:
            final_authority_index_set = {
                int(index) for index in self.final_authority_block_indices
            }
            object.__setattr__(
                self,
                "unreviewed_review_eligible_block_indices",
                [
                    int(index)
                    for index in self.review_eligible_block_indices
                    if int(index) not in final_authority_index_set
                ],
            )
        if self.seed_nonrecipe_spans is None:
            object.__setattr__(self, "seed_nonrecipe_spans", list(self.nonrecipe_spans))
        if self.seed_block_category_by_index is None:
            object.__setattr__(
                self,
                "seed_block_category_by_index",
                dict(self.block_category_by_index),
            )
        authoritative_block_category_by_index = {
            int(index): self.block_category_by_index[int(index)]
            for index in self.final_authority_block_indices
            if int(index) in self.block_category_by_index
        }
        authoritative_spans, authoritative_knowledge_spans, authoritative_other_spans = (
            self._spans_for_block_category_map(authoritative_block_category_by_index)
        )
        review_excluded_index_set = {
            int(index) for index in self.review_excluded_block_indices
        }
        reviewed_block_indices = sorted(
            int(index)
            for index in self.final_authority_block_indices
            if int(index) not in review_excluded_index_set
        )
        unreviewed_block_category_by_index = {
            int(index): self.block_category_by_index[int(index)]
            for index in self.unreviewed_review_eligible_block_indices
            if int(index) in self.block_category_by_index
        }
        unreviewed_spans, _, _ = self._spans_for_block_category_map(
            unreviewed_block_category_by_index
        )
        if self.routing is None:
            object.__setattr__(
                self,
                "routing",
                NonRecipeRoutingResult(
                    review_routing_by_block=dict(self.review_routing_by_block),
                    review_eligible_nonrecipe_spans=list(
                        self.review_eligible_nonrecipe_spans
                    ),
                    review_excluded_other_spans=list(self.review_excluded_other_spans),
                    review_eligible_block_indices=list(self.review_eligible_block_indices),
                    review_excluded_block_indices=list(self.review_excluded_block_indices),
                    review_exclusion_reason_by_block=dict(
                        self.review_exclusion_reason_by_block
                    ),
                    block_preview_by_index=dict(self.block_preview_by_index),
                    warnings=list(self.warnings),
                ),
            )
        if self.authority is None:
            object.__setattr__(
                self,
                "authority",
                NonRecipeAuthorityResult(
                    authoritative_block_indices=list(self.final_authority_block_indices),
                    authoritative_block_category_by_index=(
                        authoritative_block_category_by_index
                    ),
                    authoritative_nonrecipe_spans=authoritative_spans,
                    authoritative_knowledge_spans=authoritative_knowledge_spans,
                    authoritative_other_spans=authoritative_other_spans,
                ),
            )
        if self.review_status is None:
            object.__setattr__(
                self,
                "review_status",
                NonRecipeReviewStatusResult(
                    reviewed_block_indices=reviewed_block_indices,
                    unreviewed_review_eligible_block_indices=list(
                        self.unreviewed_review_eligible_block_indices
                    ),
                    unreviewed_block_category_by_index=unreviewed_block_category_by_index,
                    unreviewed_spans=unreviewed_spans,
                ),
            )
        if not self.refinement_report:
            object.__setattr__(
                self,
                "refinement_report",
                {
                    "enabled": False,
                    "authority_mode": "deterministic_seed_only",
                    "input_mode": "stage7_review_eligible_nonrecipe_spans",
                    "seed_nonrecipe_span_count": len(self.seed_nonrecipe_spans or []),
                    "final_nonrecipe_span_count": len(self.nonrecipe_spans),
                    "changed_block_count": 0,
                    "reviewed_block_count": 0,
                    "review_eligible_nonrecipe_span_count": len(
                        self.review_eligible_nonrecipe_spans
                    ),
                    "review_eligible_block_count": len(self.review_eligible_block_indices),
                    "review_excluded_block_count": len(self.review_excluded_block_indices),
                    "final_authority_block_count": len(self.final_authority_block_indices),
                    "unreviewed_review_eligible_block_count": len(
                        self.unreviewed_review_eligible_block_indices
                    ),
                    "review_exclusion_reason_counts": _count_reason_values(
                        self.review_exclusion_reason_by_block
                    ),
                    "reviewer_category_counts": {},
                    "changed_blocks": [],
                    "conflicts": [],
                    "ignored_block_indices": [],
                    "scored_effect": "seed_only",
                },
            )

    def authoritative_block_category_by_index(self) -> dict[int, str]:
        return dict(self.authority.authoritative_block_category_by_index)

    def unreviewed_block_category_by_index(self) -> dict[int, str]:
        return dict(self.review_status.unreviewed_block_category_by_index)

    def review_eligible_block_seed_category_by_index(self) -> dict[int, str]:
        if self.seed_block_category_by_index is None:
            return {}
        return {
            int(index): self.seed_block_category_by_index[int(index)]
            for index in self.review_eligible_block_indices
            if int(index) in self.seed_block_category_by_index
        }

    def authoritative_nonrecipe_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_nonrecipe_spans)

    def authoritative_knowledge_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_knowledge_spans)

    def authoritative_other_spans(self) -> list[NonRecipeSpan]:
        return list(self.authority.authoritative_other_spans)

    def unreviewed_nonrecipe_spans(self) -> list[NonRecipeSpan]:
        return list(self.review_status.unreviewed_spans)

    def _spans_for_block_indices(
        self,
        block_indices: Sequence[int],
        *,
        category: str,
    ) -> list[NonRecipeSpan]:
        spans, _, _ = self._spans_for_block_category_map(
            {int(index): category for index in block_indices}
        )
        return spans

    def _spans_for_block_category_map(
        self,
        block_category_by_index: Mapping[int, str],
    ) -> tuple[list[NonRecipeSpan], list[NonRecipeSpan], list[NonRecipeSpan]]:
        full_blocks_by_index = {
            int(block_index): {"block_id": block_id}
            for block_index, block_id in self._block_ids_by_index().items()
        }
        return _build_spans_from_categories(
            full_blocks_by_index=full_blocks_by_index,
            block_category_by_index=block_category_by_index,
        )

    def _block_ids_by_index(self) -> dict[int, str]:
        block_ids_by_index: dict[int, str] = {}
        for span in (
            list(self.nonrecipe_spans)
            + list(self.review_eligible_nonrecipe_spans)
            + list(self.review_excluded_other_spans)
            + list(self.seed_nonrecipe_spans or [])
        ):
            for block_index, block_id in zip(
                span.block_indices,
                span.block_ids,
                strict=False,
            ):
                block_ids_by_index.setdefault(int(block_index), str(block_id))
        return block_ids_by_index


def build_nonrecipe_stage_result(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    final_block_labels: Sequence[AuthoritativeBlockLabel],
    recipe_spans: Sequence[RecipeSpan],
    overrides: Any | None = None,
) -> NonRecipeStageResult:
    del overrides

    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
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
    review_exclusion_reason_by_block: dict[int, str] = {}
    warnings: list[str] = []
    block_preview_by_index = {
        int(block_index): _preview_text(full_blocks_by_index[block_index].get("text"))
        for block_index in sorted(full_blocks_by_index)
        if block_index not in recipe_block_indices
    }

    for block_index in sorted(full_blocks_by_index):
        if block_index in recipe_block_indices:
            continue

        block_label = labels_by_index.get(block_index)
        category, warning = _normalize_stage7_category(
            str(getattr(block_label, "final_label", None) or "")
        )
        if warning is not None:
            warnings.append(f"block {block_index}: {warning}")
        block_category_by_index[block_index] = category
        review_exclusion_reason = str(
            getattr(block_label, "review_exclusion_reason", None) or ""
        ).strip()
        if category == "other" and review_exclusion_reason:
            review_exclusion_reason_by_block[block_index] = review_exclusion_reason

    spans, knowledge_spans, other_spans = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=block_category_by_index,
    )
    review_eligible_block_category_by_index = {
        index: category
        for index, category in block_category_by_index.items()
        if index not in review_exclusion_reason_by_block
    }
    review_excluded_block_category_by_index = {
        index: block_category_by_index[index]
        for index in sorted(review_exclusion_reason_by_block)
    }
    review_eligible_nonrecipe_spans, _, _ = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index={
            index: _REVIEW_CANDIDATE_CATEGORY
            for index in sorted(review_eligible_block_category_by_index)
        },
    )
    _, _, review_excluded_other_spans = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=review_excluded_block_category_by_index,
    )
    return NonRecipeStageResult(
        nonrecipe_spans=spans,
        knowledge_spans=knowledge_spans,
        other_spans=other_spans,
        block_category_by_index=block_category_by_index,
        review_routing_by_block={
            **{
                int(index): "review_eligible"
                for index in sorted(review_eligible_block_category_by_index)
            },
            **{
                int(index): "excluded_other"
                for index in sorted(review_exclusion_reason_by_block)
            },
        },
        review_eligible_nonrecipe_spans=review_eligible_nonrecipe_spans,
        review_excluded_other_spans=review_excluded_other_spans,
        review_eligible_block_indices=sorted(review_eligible_block_category_by_index),
        review_excluded_block_indices=sorted(review_exclusion_reason_by_block),
        final_authority_block_indices=sorted(review_exclusion_reason_by_block),
        unreviewed_review_eligible_block_indices=sorted(
            review_eligible_block_category_by_index
        ),
        review_exclusion_reason_by_block=review_exclusion_reason_by_block,
        block_preview_by_index=block_preview_by_index,
        warnings=warnings,
    )


def refine_nonrecipe_stage_result(
    *,
    stage_result: NonRecipeStageResult,
    full_blocks: Sequence[Mapping[str, Any]],
    block_category_updates: Mapping[int, str],
    reviewer_categories_by_block: Mapping[int, str] | None = None,
    applied_chunk_ids_by_block: Mapping[int, Sequence[str]] | None = None,
    conflicts: Sequence[Mapping[str, Any]] | None = None,
    ignored_block_indices: Sequence[int] | None = None,
) -> NonRecipeStageResult:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    seed_block_category_by_index = dict(
        stage_result.seed_block_category_by_index or stage_result.block_category_by_index
    )
    final_block_category_by_index = dict(seed_block_category_by_index)
    changed_blocks: list[dict[str, Any]] = []
    warnings = list(stage_result.warnings)
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
                "applied_chunk_ids": list(applied_chunk_ids_by_block.get(block_index) or [])
                if applied_chunk_ids_by_block is not None
                else [],
            }
        )

    spans, knowledge_spans, other_spans = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=final_block_category_by_index,
    )
    conflict_rows = [dict(row) for row in (conflicts or [])]
    ignored_indices = sorted({int(index) for index in (ignored_block_indices or [])})
    final_authority_block_indices = sorted(
        {
            *(int(index) for index in stage_result.review_excluded_block_indices),
            *reviewed_block_indices,
        }
    )
    unreviewed_review_eligible_block_indices = [
        int(index)
        for index in stage_result.review_eligible_block_indices
        if int(index) not in reviewed_block_indices
    ]
    scored_effect = (
        "partial_final_authority"
        if reviewed_block_indices and unreviewed_review_eligible_block_indices
        else "final_authority"
        if reviewed_block_indices
        else "seed_only"
    )
    return NonRecipeStageResult(
        nonrecipe_spans=spans,
        knowledge_spans=knowledge_spans,
        other_spans=other_spans,
        block_category_by_index=final_block_category_by_index,
        review_routing_by_block=dict(stage_result.review_routing_by_block),
        review_eligible_nonrecipe_spans=list(stage_result.review_eligible_nonrecipe_spans),
        review_excluded_other_spans=list(stage_result.review_excluded_other_spans),
        review_eligible_block_indices=list(stage_result.review_eligible_block_indices),
        review_excluded_block_indices=list(stage_result.review_excluded_block_indices),
        final_authority_block_indices=final_authority_block_indices,
        unreviewed_review_eligible_block_indices=unreviewed_review_eligible_block_indices,
        review_exclusion_reason_by_block=dict(stage_result.review_exclusion_reason_by_block),
        block_preview_by_index=dict(stage_result.block_preview_by_index),
        warnings=warnings,
        seed_nonrecipe_spans=list(stage_result.seed_nonrecipe_spans or stage_result.nonrecipe_spans),
        seed_block_category_by_index=seed_block_category_by_index,
        refinement_report={
            "enabled": True,
            "authority_mode": (
                "knowledge_refined_final"
                if changed_blocks
                else "knowledge_reviewed_seed_kept"
            ),
            "input_mode": "stage7_review_eligible_nonrecipe_spans",
            "seed_nonrecipe_span_count": len(stage_result.seed_nonrecipe_spans or stage_result.nonrecipe_spans),
            "final_nonrecipe_span_count": len(spans),
            "seed_knowledge_span_count": sum(
                1
                for span in (stage_result.seed_nonrecipe_spans or stage_result.nonrecipe_spans)
                if span.category == "knowledge"
            ),
            "final_knowledge_span_count": len(knowledge_spans),
            "changed_block_count": len(changed_blocks),
            "reviewed_block_count": sum(reviewer_counts.values()),
            "review_eligible_nonrecipe_span_count": len(stage_result.review_eligible_nonrecipe_spans),
            "review_eligible_block_count": len(stage_result.review_eligible_block_indices),
            "review_excluded_block_count": len(stage_result.review_excluded_block_indices),
            "final_authority_block_count": len(final_authority_block_indices),
            "unreviewed_review_eligible_block_count": len(
                unreviewed_review_eligible_block_indices
            ),
            "review_exclusion_reason_counts": _count_reason_values(
                stage_result.review_exclusion_reason_by_block
            ),
            "reviewer_category_counts": reviewer_counts,
            "changed_blocks": changed_blocks,
            "conflicts": conflict_rows,
            "ignored_block_indices": ignored_indices,
            "scored_effect": scored_effect,
        },
    )


def block_rows_for_nonrecipe_stage(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    rows: list[dict[str, Any]] = []
    for block_index in sorted(stage_result.block_category_by_index):
        block = full_blocks_by_index.get(int(block_index))
        if block is None:
            continue
        payload = dict(block)
        payload["index"] = int(block_index)
        payload["stage7_category"] = stage_result.block_category_by_index[int(block_index)]
        rows.append(payload)
    return rows


def block_rows_for_nonrecipe_authority(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    rows: list[dict[str, Any]] = []
    for block_index in stage_result.authority.authoritative_block_indices:
        block = full_blocks_by_index.get(int(block_index))
        if block is None:
            continue
        payload = dict(block)
        payload["index"] = int(block_index)
        payload["stage7_category"] = (
            stage_result.authority.authoritative_block_category_by_index[int(block_index)]
        )
        rows.append(payload)
    return rows


def block_rows_for_nonrecipe_span(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    span: NonRecipeSpan,
) -> list[dict[str, Any]]:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    rows: list[dict[str, Any]] = []
    for block_index in span.block_indices:
        block = full_blocks_by_index.get(int(block_index))
        if block is None:
            continue
        payload = dict(block)
        payload["index"] = int(block_index)
        payload["stage7_category"] = span.category
        rows.append(payload)
    return rows


def _prepare_full_blocks_by_index(
    blocks: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    prepared: dict[int, dict[str, Any]] = {}
    for raw_block in blocks:
        if not isinstance(raw_block, Mapping):
            continue
        try:
            block_index = int(raw_block.get("index"))
        except (TypeError, ValueError):
            continue
        payload = dict(raw_block)
        payload["index"] = block_index
        block_id = payload.get("block_id") or payload.get("id")
        if not isinstance(block_id, str) or not block_id.strip():
            block_id = f"b{block_index}"
        payload["block_id"] = block_id.strip()
        prepared[block_index] = payload
    return prepared


def _normalize_stage7_category(raw_label: str | None) -> tuple[str, str | None]:
    normalized = str(raw_label or "").strip().lower()
    if normalized == "knowledge":
        return "knowledge", None
    if normalized in _OTHER_LABELS:
        return "other", None
    if not normalized:
        return "other", "missing final label mapped to Stage 7 other"
    return "other", f"unexpected final label '{raw_label}' mapped to Stage 7 other"


def _build_span(
    *,
    category: str,
    block_indices: list[int],
    block_ids: list[str],
) -> NonRecipeSpan:
    start = int(block_indices[0])
    end = int(block_indices[-1]) + 1
    return NonRecipeSpan(
        span_id=f"nr.{category}.{start}.{end}",
        category=category,
        block_start_index=start,
        block_end_index=end,
        block_indices=list(block_indices),
        block_ids=list(block_ids),
    )


def _build_spans_from_categories(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_category_by_index: Mapping[int, str],
) -> tuple[list[NonRecipeSpan], list[NonRecipeSpan], list[NonRecipeSpan]]:
    spans: list[NonRecipeSpan] = []
    current_indices: list[int] = []
    current_block_ids: list[str] = []
    current_category: str | None = None
    previous_index: int | None = None

    for block_index in sorted(block_category_by_index):
        category = str(block_category_by_index[block_index] or "other")
        block_payload = full_blocks_by_index.get(int(block_index), {})
        block_id = str(block_payload.get("block_id") or f"b{block_index}")
        if (
            current_category is None
            or previous_index is None
            or block_index != previous_index + 1
            or category != current_category
        ):
            if current_category is not None and current_indices:
                spans.append(
                    _build_span(
                        category=current_category,
                        block_indices=current_indices,
                        block_ids=current_block_ids,
                    )
                )
            current_indices = [int(block_index)]
            current_block_ids = [block_id]
            current_category = category
            previous_index = int(block_index)
            continue

        current_indices.append(int(block_index))
        current_block_ids.append(block_id)
        previous_index = int(block_index)

    if current_category is not None and current_indices:
        spans.append(
            _build_span(
                category=current_category,
                block_indices=current_indices,
                block_ids=current_block_ids,
            )
        )

    knowledge_spans = [span for span in spans if span.category == "knowledge"]
    other_spans = [span for span in spans if span.category == "other"]
    return spans, knowledge_spans, other_spans


def _count_reason_values(values: Mapping[int, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values.values():
        normalized = str(value or "").strip()
        if not normalized:
            continue
        counts[normalized] = int(counts.get(normalized) or 0) + 1
    return counts


def _preview_text(value: Any, limit: int = 120) -> str:
    rendered = " ".join(str(value or "").split())
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 3)].rstrip() + "..."
