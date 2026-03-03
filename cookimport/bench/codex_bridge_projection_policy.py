from __future__ import annotations


def select_prompt_row_for_trace(
    *,
    recipe_key: str,
    span_region: str,
    prompt_rows_by_recipe: dict[str, dict[str, object]],
    fallback_prompt_row: dict[str, object] | None,
) -> dict[str, object] | None:
    """Select a prompt row for trace context.

    Outside-span rows never borrow fallback prompt rows from unrelated recipes.
    """

    key = str(recipe_key).strip()
    if key:
        matched = prompt_rows_by_recipe.get(key)
        if matched is not None:
            return matched
    if span_region == "outside_active_recipe_span":
        return None
    return fallback_prompt_row


def resolve_trace_status(
    *,
    span_region: str,
    has_prompt_excerpt: bool,
    has_archive_excerpt: bool,
) -> str:
    if span_region == "outside_active_recipe_span":
        if has_archive_excerpt and has_prompt_excerpt:
            return "outside_span_joined_with_prompt_and_archive"
        if has_archive_excerpt:
            return "outside_span_archive_only"
        if has_prompt_excerpt:
            return "outside_span_prompt_only"
        return "outside_span_unattributed"

    if has_archive_excerpt and has_prompt_excerpt:
        return "joined_with_prompt_and_archive"
    if has_archive_excerpt:
        return "joined_with_archive_only"
    if has_prompt_excerpt:
        return "joined_with_prompt_only"
    return "missing_prompt_and_archive_context"
