from __future__ import annotations

from typing import Any, Mapping, Sequence

from .nonrecipe_authority_contract import NonRecipeSeedResult, NonRecipeSpan

_FINAL_OTHER_LABELS = {
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


def prepare_nonrecipe_full_blocks_by_index(
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


def normalize_nonrecipe_route_label(raw_label: str | None) -> tuple[str, str | None]:
    normalized = str(raw_label or "").strip().upper()
    if normalized == "NONRECIPE_CANDIDATE":
        return "candidate", None
    if normalized == "NONRECIPE_EXCLUDE":
        return "exclude", None
    if not normalized:
        return "candidate", "missing route label"
    return "candidate", f"unexpected route label '{raw_label}'"


def require_nonrecipe_route_label(raw_label: str | None, *, block_index: int) -> str:
    normalized_label, warning = normalize_nonrecipe_route_label(raw_label)
    if warning is None:
        return normalized_label
    if warning == "missing route label":
        raise ValueError(f"Missing non-recipe route label at block {block_index}.")
    raise ValueError(f"Invalid non-recipe route label at block {block_index}: {warning}.")


def normalize_nonrecipe_final_category(raw_label: str | None) -> tuple[str, str | None]:
    normalized = str(raw_label or "").strip().lower()
    if normalized == "knowledge":
        return "knowledge", None
    if normalized in _FINAL_OTHER_LABELS:
        return "other", None
    if not normalized:
        return "other", "missing final label"
    return "other", f"unexpected final label '{raw_label}'"


def require_nonrecipe_final_category(raw_label: str | None, *, block_index: int) -> str:
    normalized_category, warning = normalize_nonrecipe_final_category(raw_label)
    if warning is None:
        return normalized_category
    if warning == "missing final label":
        raise ValueError(f"Missing final non-recipe label at block {block_index}.")
    raise ValueError(
        f"Invalid final non-recipe label at block {block_index}: {warning}."
    )


def build_nonrecipe_span(
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


def build_nonrecipe_spans_from_categories(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    block_category_by_index: Mapping[int, str],
) -> list[NonRecipeSpan]:
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
                    build_nonrecipe_span(
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
            build_nonrecipe_span(
                category=current_category,
                block_indices=current_indices,
                block_ids=current_block_ids,
            )
        )
    return spans


def build_nonrecipe_seed_result(
    *,
    full_blocks_by_index: Mapping[int, Mapping[str, Any]],
    route_by_index: Mapping[int, str],
) -> NonRecipeSeedResult:
    seed_nonrecipe_spans = build_nonrecipe_spans_from_categories(
        full_blocks_by_index=full_blocks_by_index,
        block_category_by_index=route_by_index,
    )
    return NonRecipeSeedResult(
        seed_nonrecipe_spans=seed_nonrecipe_spans,
        seed_candidate_spans=[
            span for span in seed_nonrecipe_spans if span.category == "candidate"
        ],
        seed_excluded_spans=[
            span for span in seed_nonrecipe_spans if span.category == "exclude"
        ],
        seed_route_by_index={
            int(index): str(category) for index, category in route_by_index.items()
        },
    )


def count_nonrecipe_reason_values(values: Mapping[int, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values.values():
        normalized = str(value or "").strip()
        if not normalized:
            continue
        counts[normalized] = int(counts.get(normalized) or 0) + 1
    return counts


def preview_nonrecipe_text(value: Any, limit: int = 120) -> str:
    rendered = " ".join(str(value or "").split())
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 3)].rstrip() + "..."
