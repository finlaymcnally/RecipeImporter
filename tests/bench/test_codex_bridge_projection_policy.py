from __future__ import annotations

from cookimport.bench.codex_bridge_projection_policy import (
    resolve_trace_status,
    select_prompt_row_for_trace,
)


def test_select_prompt_row_for_trace_blocks_outside_span_fallback() -> None:
    prompt_rows_by_recipe = {"recipe:c0": {"call_id": "c0-recipe-correction"}}
    fallback_prompt_row = {"call_id": "fallback-build-final"}

    selected = select_prompt_row_for_trace(
        recipe_key="",
        span_region="outside_active_recipe_span",
        prompt_rows_by_recipe=prompt_rows_by_recipe,
        fallback_prompt_row=fallback_prompt_row,
    )

    assert selected is None


def test_select_prompt_row_for_trace_keeps_inside_span_fallback() -> None:
    fallback_prompt_row = {"call_id": "fallback-build-final"}

    selected = select_prompt_row_for_trace(
        recipe_key="",
        span_region="inside_active_recipe_span",
        prompt_rows_by_recipe={},
        fallback_prompt_row=fallback_prompt_row,
    )

    assert selected == fallback_prompt_row


def test_resolve_trace_status_uses_outside_span_statuses() -> None:
    assert (
        resolve_trace_status(
            span_region="outside_active_recipe_span",
            has_prompt_excerpt=False,
            has_archive_excerpt=True,
        )
        == "outside_span_archive_only"
    )
    assert (
        resolve_trace_status(
            span_region="outside_active_recipe_span",
            has_prompt_excerpt=False,
            has_archive_excerpt=False,
        )
        == "outside_span_unattributed"
    )
