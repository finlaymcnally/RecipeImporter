from __future__ import annotations

import json
from typing import Any, Callable


def _prompt_case_score(
    *,
    stage_key: str,
    warnings_count: int,
    empty_mapping: bool,
    changed_lines_for_recipe: int,
) -> int:
    stage_weights = {
        "recipe_refine": 6,
        "nonrecipe_finalize": 3,
        "tags": 1,
    }
    return (
        stage_weights.get(stage_key, 1)
        + warnings_count * 4
        + (8 if empty_mapping else 0)
        + changed_lines_for_recipe * 5
    )


def _prompt_row_identity_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("timestamp_utc") or ""),
        str(row.get("call_id") or ""),
        str(row.get("stage_key") or row.get("stage_artifact_stem") or ""),
    )


def _warning_buckets(
    warnings: list[str],
    *,
    prompt_warning_bucket: Callable[[str], str],
    normalize_whitespace: Callable[[str], str],
) -> list[str]:
    buckets = {
        prompt_warning_bucket(normalize_whitespace(message))
        for message in warnings
        if message.strip()
    }
    return sorted(buckets)


def _count_list_entries(
    value: Any,
    *,
    parse_json_like: Callable[[Any], Any],
) -> int:
    parsed = parse_json_like(value)
    if isinstance(parsed, list):
        return len(parsed)
    return 0


def _blocks_from_request_payload(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _block_id_from_row(
    block: dict[str, Any],
    *,
    coerce_int: Callable[[Any], int | None],
) -> str | None:
    for key in ("block_id", "stable_key"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    index_value = coerce_int(block.get("index"))
    if index_value is not None:
        return f"index:{index_value}"
    return None


def _build_intermediate_selected_blocks(
    row: dict[str, Any],
    *,
    parse_json_like: Callable[[Any], Any],
    coerce_int: Callable[[Any], int | None],
    coerce_str_list: Callable[[Any], list[str]],
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    request_payload = parse_json_like(row.get("request_input_payload"))
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    parsed_response = parse_json_like(row.get("parsed_response"))
    parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
    blocks_candidate = _blocks_from_request_payload(request_payload, "blocks_candidate")
    if not blocks_candidate:
        return [], None, None

    start = coerce_int(parsed_response.get("start_block_index"))
    end = coerce_int(parsed_response.get("end_block_index"))
    excluded_ids = {
        str(value).strip()
        for value in coerce_str_list(parsed_response.get("excluded_block_ids"))
        if str(value).strip()
    }

    selected: list[dict[str, Any]] = []
    for fallback_index, block in enumerate(blocks_candidate):
        block_index = coerce_int(block.get("index"))
        if block_index is None:
            block_index = fallback_index
        if start is not None and end is not None and not (start <= block_index <= end):
            continue
        block_id = _block_id_from_row(block, coerce_int=coerce_int)
        if block_id and block_id in excluded_ids:
            continue
        selected.append(block)

    if start is not None and end is not None and end >= start and not selected:
        selected_count = end - start + 1
    else:
        selected_count = len(selected)
    return selected, start, end


def _correction_input_blocks(
    row: dict[str, Any],
    *,
    parse_json_like: Callable[[Any], Any],
) -> list[dict[str, Any]]:
    request_payload = parse_json_like(row.get("request_input_payload"))
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    return _blocks_from_request_payload(request_payload, "blocks")


def _final_recipe_step_count(
    parsed_response: dict[str, Any],
    *,
    parse_json_like: Callable[[Any], Any],
) -> int:
    draft_payload = parse_json_like(parsed_response.get("draft_v1"))
    if isinstance(draft_payload, dict):
        steps = draft_payload.get("steps")
        if isinstance(steps, list):
            return len(steps)
    steps = parsed_response.get("steps")
    if isinstance(steps, list):
        return len(steps)
    return 0


def _mapping_count(
    value: Any,
    *,
    parse_json_like: Callable[[Any], Any],
) -> int:
    parsed = parse_json_like(value)
    if isinstance(parsed, dict):
        return len(parsed)
    if isinstance(parsed, list):
        return len(parsed)
    return 0


def _to_json_excerpt(
    value: Any,
    *,
    excerpt_limit: int,
    excerpt: Callable[..., str],
    normalize_whitespace: Callable[[str], str],
) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return excerpt(normalize_whitespace(value), max_len=excerpt_limit)
    return excerpt(
        normalize_whitespace(json.dumps(value, ensure_ascii=False, sort_keys=True)),
        max_len=excerpt_limit,
    )


def _input_excerpt_for_prompt_row(
    row: dict[str, Any],
    *,
    excerpt_limit: int,
    first_prompt_block_excerpt: Callable[..., str],
    parse_json_like: Callable[[Any], Any],
    excerpt: Callable[..., str],
    normalize_whitespace: Callable[[str], str],
) -> str:
    primary = first_prompt_block_excerpt(row, excerpt_limit=excerpt_limit)
    if primary:
        return primary
    request_payload = parse_json_like(row.get("request_input_payload"))
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    canonical_text = request_payload.get("canonical_text")
    if isinstance(canonical_text, str) and canonical_text.strip():
        return excerpt(normalize_whitespace(canonical_text), max_len=excerpt_limit)
    for key in ("extracted_instructions", "extracted_ingredients"):
        rows = request_payload.get(key)
        if not isinstance(rows, list):
            continue
        if rows and isinstance(rows[0], dict):
            text = str(rows[0].get("text") or rows[0].get("name") or "").strip()
            if text:
                return excerpt(normalize_whitespace(text), max_len=excerpt_limit)
        if rows and isinstance(rows[0], str):
            return excerpt(normalize_whitespace(str(rows[0])), max_len=excerpt_limit)
    return ""


def _output_excerpt_for_prompt_row(
    row: dict[str, Any],
    *,
    excerpt_limit: int,
    parse_json_like: Callable[[Any], Any],
    coerce_str_list: Callable[[Any], list[str]],
    prompt_row_stage_key: Callable[[dict[str, Any]], str],
    excerpt: Callable[..., str],
    normalize_whitespace: Callable[[str], str],
) -> str:
    parsed_response = parse_json_like(row.get("parsed_response"))
    parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
    warnings = coerce_str_list(parsed_response.get("warnings"))
    if warnings:
        return excerpt(normalize_whitespace(warnings[0]), max_len=excerpt_limit)

    stage_key = prompt_row_stage_key(row)
    if stage_key == "recipe_refine":
        canonical_recipe = (
            parsed_response.get("canonical_recipe")
            if isinstance(parsed_response.get("canonical_recipe"), dict)
            else {}
        )
        title = str(canonical_recipe.get("title") or "").strip()
        if title:
            return excerpt(normalize_whitespace(title), max_len=excerpt_limit)
        if canonical_recipe:
            return _to_json_excerpt(
                canonical_recipe,
                excerpt_limit=excerpt_limit,
                excerpt=excerpt,
                normalize_whitespace=normalize_whitespace,
            )
    if parsed_response:
        return _to_json_excerpt(
            parsed_response,
            excerpt_limit=excerpt_limit,
            excerpt=excerpt,
            normalize_whitespace=normalize_whitespace,
        )
    return ""


def _recipe_short_title(
    *,
    recipe_id: str,
    recipe_spans: list[dict[str, Any]],
    correction_row: dict[str, Any] | None,
    parse_json_like: Callable[[Any], Any],
) -> str:
    parsed_response = (
        parse_json_like(correction_row.get("parsed_response"))
        if isinstance(correction_row, dict)
        else None
    )
    if isinstance(parsed_response, dict):
        canonical_recipe = (
            parsed_response.get("canonical_recipe")
            if isinstance(parsed_response.get("canonical_recipe"), dict)
            else {}
        )
        title = str(canonical_recipe.get("title") or "").strip()
        if title:
            return title
    for span in recipe_spans:
        if str(span.get("recipe_id") or "") != recipe_id:
            continue
        title = str(span.get("title") or "").strip()
        if title:
            return title
    if ":" in recipe_id:
        return recipe_id.rsplit(":", 1)[-1]
    return recipe_id


def _nearest_recipe_id_for_line_index(
    *,
    line_index: int,
    recipe_spans: list[dict[str, Any]],
    span_line_bounds: Callable[[dict[str, Any]], tuple[int | None, int | None]],
) -> str | None:
    if not recipe_spans:
        return None
    ranked: list[tuple[int, int, int, str]] = []
    for span in recipe_spans:
        recipe_id = str(span.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        start, end = span_line_bounds(span)
        if start is None or end is None:
            continue
        if start <= line_index <= end:
            distance = 0
        else:
            distance = min(abs(line_index - start), abs(line_index - end))
        ranked.append((distance, start, recipe_id.count(":"), recipe_id))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return ranked[0][3]
