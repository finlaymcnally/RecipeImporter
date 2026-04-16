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


def prepare_nonrecipe_full_rows_by_index(
    rows: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    prepared: dict[int, dict[str, Any]] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        try:
            row_index = int(raw_row.get("index"))
        except (TypeError, ValueError):
            continue
        payload = dict(raw_row)
        payload["index"] = row_index
        row_id = payload.get("row_id") or payload.get("block_id") or payload.get("id")
        if not isinstance(row_id, str) or not row_id.strip():
            row_id = f"row:{row_index}"
        payload["row_id"] = row_id.strip()
        payload.setdefault("block_id", payload["row_id"])
        prepared[row_index] = payload
    return prepared


def prepare_nonrecipe_full_blocks_by_index(
    blocks: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    return prepare_nonrecipe_full_rows_by_index(blocks)


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
    row_indices: list[int],
    row_ids: list[str],
) -> NonRecipeSpan:
    start = int(row_indices[0])
    end = int(row_indices[-1]) + 1
    return NonRecipeSpan(
        span_id=f"nr.{category}.{start}.{end}",
        category=category,
        row_start_index=start,
        row_end_index=end,
        row_indices=list(row_indices),
        row_ids=list(row_ids),
    )


def build_nonrecipe_spans_from_categories(
    *,
    full_rows_by_index: Mapping[int, Mapping[str, Any]],
    row_category_by_index: Mapping[int, str],
) -> list[NonRecipeSpan]:
    spans: list[NonRecipeSpan] = []
    current_indices: list[int] = []
    current_row_ids: list[str] = []
    current_category: str | None = None
    previous_index: int | None = None

    for row_index in sorted(row_category_by_index):
        category = str(row_category_by_index[row_index] or "other")
        row_payload = full_rows_by_index.get(int(row_index), {})
        row_id = str(row_payload.get("row_id") or row_payload.get("block_id") or f"row:{row_index}")
        if (
            current_category is None
            or previous_index is None
            or row_index != previous_index + 1
            or category != current_category
        ):
            if current_category is not None and current_indices:
                spans.append(
                    build_nonrecipe_span(
                        category=current_category,
                        row_indices=current_indices,
                        row_ids=current_row_ids,
                    )
                )
            current_indices = [int(row_index)]
            current_row_ids = [row_id]
            current_category = category
            previous_index = int(row_index)
            continue

        current_indices.append(int(row_index))
        current_row_ids.append(row_id)
        previous_index = int(row_index)

    if current_category is not None and current_indices:
        spans.append(
            build_nonrecipe_span(
                category=current_category,
                row_indices=current_indices,
                row_ids=current_row_ids,
            )
        )
    return spans


def build_nonrecipe_seed_result(
    *,
    full_rows_by_index: Mapping[int, Mapping[str, Any]],
    route_by_index: Mapping[int, str],
) -> NonRecipeSeedResult:
    seed_nonrecipe_spans = build_nonrecipe_spans_from_categories(
        full_rows_by_index=full_rows_by_index,
        row_category_by_index=route_by_index,
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
def preview_nonrecipe_text(value: Any, limit: int = 120) -> str:
    rendered = " ".join(str(value or "").split())
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 3)].rstrip() + "..."
