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
class NonRecipeSeedResult:
    seed_nonrecipe_spans: list[NonRecipeSpan]
    seed_knowledge_spans: list[NonRecipeSpan]
    seed_other_spans: list[NonRecipeSpan]
    seed_block_category_by_index: dict[int, str]


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


def _build_nonrecipe_seed_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_category_by_index: Mapping[int, str],
) -> NonRecipeSeedResult:
    seed_nonrecipe_spans, seed_knowledge_spans, seed_other_spans = (
        _build_spans_from_categories(
            full_blocks_by_index=full_blocks_by_index,
            block_category_by_index=block_category_by_index,
        )
    )
    return NonRecipeSeedResult(
        seed_nonrecipe_spans=seed_nonrecipe_spans,
        seed_knowledge_spans=seed_knowledge_spans,
        seed_other_spans=seed_other_spans,
        seed_block_category_by_index={
            int(index): str(category)
            for index, category in block_category_by_index.items()
        },
    )


def _build_nonrecipe_routing_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    review_eligible_block_indices: Sequence[int],
    review_excluded_block_indices: Sequence[int],
    review_exclusion_reason_by_block: Mapping[int, str],
    block_preview_by_index: Mapping[int, str],
    warnings: Sequence[str],
) -> NonRecipeRoutingResult:
    review_eligible_nonrecipe_spans, _, _ = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index={
            int(index): _REVIEW_CANDIDATE_CATEGORY
            for index in sorted(review_eligible_block_indices)
        },
    )
    _, _, review_excluded_other_spans = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index={
            int(index): "other"
            for index in sorted(review_excluded_block_indices)
        },
    )
    review_routing_by_block = {
        **{
            int(index): "review_eligible"
            for index in sorted(review_eligible_block_indices)
        },
        **{
            int(index): "excluded_other"
            for index in sorted(review_excluded_block_indices)
        },
    }
    return NonRecipeRoutingResult(
        review_routing_by_block=review_routing_by_block,
        review_eligible_nonrecipe_spans=review_eligible_nonrecipe_spans,
        review_excluded_other_spans=review_excluded_other_spans,
        review_eligible_block_indices=[int(index) for index in review_eligible_block_indices],
        review_excluded_block_indices=[int(index) for index in review_excluded_block_indices],
        review_exclusion_reason_by_block={
            int(index): str(reason)
            for index, reason in review_exclusion_reason_by_block.items()
        },
        block_preview_by_index={
            int(index): str(preview)
            for index, preview in block_preview_by_index.items()
        },
        warnings=[str(warning) for warning in warnings],
    )


def _build_nonrecipe_authority_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_category_by_index: Mapping[int, str],
    authoritative_block_indices: Sequence[int],
) -> NonRecipeAuthorityResult:
    authoritative_block_category_by_index = {
        int(index): str(block_category_by_index[int(index)])
        for index in authoritative_block_indices
        if int(index) in block_category_by_index
    }
    authoritative_nonrecipe_spans, authoritative_knowledge_spans, authoritative_other_spans = (
        _build_spans_from_categories(
            full_blocks_by_index=full_blocks_by_index,
            block_category_by_index=authoritative_block_category_by_index,
        )
    )
    return NonRecipeAuthorityResult(
        authoritative_block_indices=[
            int(index) for index in authoritative_block_indices if int(index) in block_category_by_index
        ],
        authoritative_block_category_by_index=authoritative_block_category_by_index,
        authoritative_nonrecipe_spans=authoritative_nonrecipe_spans,
        authoritative_knowledge_spans=authoritative_knowledge_spans,
        authoritative_other_spans=authoritative_other_spans,
    )


def _build_nonrecipe_review_status_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_category_by_index: Mapping[int, str],
    review_eligible_block_indices: Sequence[int],
    authoritative_block_indices: Sequence[int],
    review_excluded_block_indices: Sequence[int],
) -> NonRecipeReviewStatusResult:
    authoritative_index_set = {int(index) for index in authoritative_block_indices}
    review_excluded_index_set = {int(index) for index in review_excluded_block_indices}
    reviewed_block_indices = sorted(
        int(index)
        for index in authoritative_index_set
        if int(index) not in review_excluded_index_set
    )
    unreviewed_review_eligible_block_indices = [
        int(index)
        for index in review_eligible_block_indices
        if int(index) not in authoritative_index_set
    ]
    unreviewed_block_category_by_index = {
        int(index): str(block_category_by_index[int(index)])
        for index in unreviewed_review_eligible_block_indices
        if int(index) in block_category_by_index
    }
    unreviewed_spans, _, _ = _build_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=unreviewed_block_category_by_index,
    )
    return NonRecipeReviewStatusResult(
        reviewed_block_indices=reviewed_block_indices,
        unreviewed_review_eligible_block_indices=unreviewed_review_eligible_block_indices,
        unreviewed_block_category_by_index=unreviewed_block_category_by_index,
        unreviewed_spans=unreviewed_spans,
    )


def _default_nonrecipe_refinement_report(
    *,
    seed: NonRecipeSeedResult,
    routing: NonRecipeRoutingResult,
    authority: NonRecipeAuthorityResult,
    review_status: NonRecipeReviewStatusResult,
) -> dict[str, Any]:
    return {
        "enabled": False,
        "authority_mode": "deterministic_seed_only",
        "input_mode": "stage7_review_eligible_nonrecipe_spans",
        "seed_nonrecipe_span_count": len(seed.seed_nonrecipe_spans),
        "final_nonrecipe_span_count": len(authority.authoritative_nonrecipe_spans),
        "changed_block_count": 0,
        "reviewed_block_count": 0,
        "review_eligible_nonrecipe_span_count": len(routing.review_eligible_nonrecipe_spans),
        "review_eligible_block_count": len(routing.review_eligible_block_indices),
        "review_excluded_block_count": len(routing.review_excluded_block_indices),
        "final_authority_block_count": len(authority.authoritative_block_indices),
        "unreviewed_review_eligible_block_count": len(
            review_status.unreviewed_review_eligible_block_indices
        ),
        "review_exclusion_reason_counts": _count_reason_values(
            routing.review_exclusion_reason_by_block
        ),
        "reviewer_category_counts": {},
        "changed_blocks": [],
        "conflicts": [],
        "ignored_block_indices": [],
        "scored_effect": "seed_only",
    }


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
    review_eligible_block_category_by_index: dict[int, str] = {}
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
        if block_label is None:
            raise ValueError(
                f"Missing final block label for non-recipe block {block_index}."
            )
        category = _require_nonrecipe_stage_category(
            getattr(block_label, "final_label", None),
            block_index=block_index,
        )
        block_category_by_index[block_index] = category
        review_exclusion_reason = str(
            getattr(block_label, "review_exclusion_reason", None) or ""
        ).strip()
        if category == "other" and review_exclusion_reason:
            review_exclusion_reason_by_block[block_index] = review_exclusion_reason
            continue
        review_eligible_block_category_by_index[block_index] = category

    seed = _build_nonrecipe_seed_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=block_category_by_index,
    )
    routing = _build_nonrecipe_routing_result(
        full_blocks_by_index=full_blocks_by_index,
        review_eligible_block_indices=sorted(review_eligible_block_category_by_index),
        review_excluded_block_indices=sorted(review_exclusion_reason_by_block),
        review_exclusion_reason_by_block=review_exclusion_reason_by_block,
        block_preview_by_index=block_preview_by_index,
        warnings=warnings,
    )
    authority = _build_nonrecipe_authority_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=block_category_by_index,
        authoritative_block_indices=sorted(review_exclusion_reason_by_block),
    )
    review_status = _build_nonrecipe_review_status_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=block_category_by_index,
        review_eligible_block_indices=routing.review_eligible_block_indices,
        authoritative_block_indices=authority.authoritative_block_indices,
        review_excluded_block_indices=routing.review_excluded_block_indices,
    )
    return NonRecipeStageResult(
        seed=seed,
        routing=routing,
        authority=authority,
        review_status=review_status,
        refinement_report=_default_nonrecipe_refinement_report(
            seed=seed,
            routing=routing,
            authority=authority,
            review_status=review_status,
        ),
    )


def refine_nonrecipe_stage_result(
    *,
    stage_result: NonRecipeStageResult,
    full_blocks: Sequence[Mapping[str, Any]],
    block_category_updates: Mapping[int, str],
    reviewer_categories_by_block: Mapping[int, str] | None = None,
    applied_packet_ids_by_block: Mapping[int, Sequence[str]] | None = None,
    conflicts: Sequence[Mapping[str, Any]] | None = None,
    ignored_block_indices: Sequence[int] | None = None,
) -> NonRecipeStageResult:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    seed_block_category_by_index = dict(stage_result.seed.seed_block_category_by_index)
    final_block_category_by_index = dict(seed_block_category_by_index)
    changed_blocks: list[dict[str, Any]] = []
    warnings = list(stage_result.routing.warnings)
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
                "applied_packet_ids": list(applied_packet_ids_by_block.get(block_index) or [])
                if applied_packet_ids_by_block is not None
                else [],
            }
        )

    conflict_rows = [dict(row) for row in (conflicts or [])]
    ignored_indices = sorted({int(index) for index in (ignored_block_indices or [])})
    final_authority_block_indices = sorted(
        {
            *(int(index) for index in stage_result.routing.review_excluded_block_indices),
            *reviewed_block_indices,
        }
    )
    authority = _build_nonrecipe_authority_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=final_block_category_by_index,
        authoritative_block_indices=final_authority_block_indices,
    )
    review_status = _build_nonrecipe_review_status_result(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=final_block_category_by_index,
        review_eligible_block_indices=stage_result.routing.review_eligible_block_indices,
        authoritative_block_indices=authority.authoritative_block_indices,
        review_excluded_block_indices=stage_result.routing.review_excluded_block_indices,
    )
    scored_effect = (
        "partial_final_authority"
        if reviewed_block_indices and review_status.unreviewed_review_eligible_block_indices
        else "final_authority" if reviewed_block_indices else "seed_only"
    )
    return NonRecipeStageResult(
        seed=stage_result.seed,
        routing=NonRecipeRoutingResult(
            review_routing_by_block=dict(stage_result.routing.review_routing_by_block),
            review_eligible_nonrecipe_spans=list(stage_result.routing.review_eligible_nonrecipe_spans),
            review_excluded_other_spans=list(stage_result.routing.review_excluded_other_spans),
            review_eligible_block_indices=list(stage_result.routing.review_eligible_block_indices),
            review_excluded_block_indices=list(stage_result.routing.review_excluded_block_indices),
            review_exclusion_reason_by_block=dict(stage_result.routing.review_exclusion_reason_by_block),
            block_preview_by_index=dict(stage_result.routing.block_preview_by_index),
            warnings=warnings,
        ),
        authority=authority,
        review_status=review_status,
        refinement_report={
            "enabled": True,
            "authority_mode": (
                "knowledge_refined_final"
                if changed_blocks
                else "knowledge_reviewed_seed_kept"
            ),
            "input_mode": "stage7_review_eligible_nonrecipe_spans",
            "seed_nonrecipe_span_count": len(stage_result.seed.seed_nonrecipe_spans),
            "final_nonrecipe_span_count": len(authority.authoritative_nonrecipe_spans),
            "seed_knowledge_span_count": sum(
                1
                for span in stage_result.seed.seed_nonrecipe_spans
                if span.category == "knowledge"
            ),
            "final_knowledge_span_count": len(authority.authoritative_knowledge_spans),
            "changed_block_count": len(changed_blocks),
            "reviewed_block_count": len(reviewed_block_indices),
            "review_eligible_nonrecipe_span_count": len(stage_result.routing.review_eligible_nonrecipe_spans),
            "review_eligible_block_count": len(stage_result.routing.review_eligible_block_indices),
            "review_excluded_block_count": len(stage_result.routing.review_excluded_block_indices),
            "final_authority_block_count": len(authority.authoritative_block_indices),
            "unreviewed_review_eligible_block_count": len(
                review_status.unreviewed_review_eligible_block_indices
            ),
            "review_exclusion_reason_counts": _count_reason_values(
                stage_result.routing.review_exclusion_reason_by_block
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
    for block_index in sorted(stage_result.seed.seed_block_category_by_index):
        block = full_blocks_by_index.get(int(block_index))
        if block is None:
            continue
        payload = dict(block)
        payload["index"] = int(block_index)
        payload["stage7_category"] = stage_result.seed.seed_block_category_by_index[
            int(block_index)
        ]
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


def block_rows_for_nonrecipe_survivors(
    *,
    full_blocks: Sequence[Mapping[str, Any]],
    stage_result: NonRecipeStageResult,
) -> list[dict[str, Any]]:
    full_blocks_by_index = _prepare_full_blocks_by_index(full_blocks)
    surviving_categories = stage_result.surviving_review_block_category_by_index()
    rows: list[dict[str, Any]] = []
    for block_index in stage_result.routing.review_eligible_block_indices:
        resolved_index = int(block_index)
        block = full_blocks_by_index.get(resolved_index)
        if block is None:
            continue
        payload = dict(block)
        payload["index"] = resolved_index
        if resolved_index in surviving_categories:
            payload["stage7_category"] = surviving_categories[resolved_index]
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
        return "other", "missing final label"
    return "other", f"unexpected final label '{raw_label}'"


def _require_nonrecipe_stage_category(raw_label: str | None, *, block_index: int) -> str:
    normalized_category, warning = _normalize_stage7_category(raw_label)
    if warning is None:
        return normalized_category
    if warning == "missing final label":
        raise ValueError(f"Missing final non-recipe label at block {block_index}.")
    raise ValueError(
        f"Invalid final non-recipe label at block {block_index}: {warning}."
    )


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
