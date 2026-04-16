from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable


def _first_prompt_block_excerpt(
    row: dict[str, Any],
    *,
    excerpt_limit: int,
    parse_json_like: Callable[[Any], Any],
    excerpt: Callable[..., str],
    normalize_whitespace: Callable[[str], str],
) -> str:
    request_input_payload = parse_json_like(row.get("request_input_payload"))
    if not isinstance(request_input_payload, dict):
        return ""
    for key in ("rows_candidate", "rows_before", "rows_after", "rows"):
        blocks = request_input_payload.get(key)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return excerpt(normalize_whitespace(text), max_len=excerpt_limit)
    evidence_rows = request_input_payload.get("evidence_rows")
    if isinstance(evidence_rows, list):
        for evidence_row in evidence_rows:
            if not isinstance(evidence_row, (list, tuple)) or len(evidence_row) < 2:
                continue
            text = str(evidence_row[1] or "").strip()
            if text:
                return excerpt(normalize_whitespace(text), max_len=excerpt_limit)
    return ""


def _prompt_row_stage_key(row: dict[str, Any]) -> str:
    return str(row.get("stage_key") or "").strip()


def _prompt_row_recipe_id(
    row: dict[str, Any],
    *,
    parse_json_like: Callable[[Any], Any],
) -> str:
    direct = str(row.get("recipe_id") or "").strip()
    if direct:
        return direct
    parsed_response = parse_json_like(row.get("parsed_response"))
    if isinstance(parsed_response, dict):
        parsed_recipe_id = str(parsed_response.get("recipe_id") or "").strip()
        if parsed_recipe_id:
            return parsed_recipe_id
    return ""


def _prompt_row_owned_recipe_ids(
    row: dict[str, Any],
    *,
    parse_json_like: Callable[[Any], Any],
) -> list[str]:
    request_input_payload = parse_json_like(row.get("request_input_payload"))
    request_input_payload = (
        request_input_payload if isinstance(request_input_payload, dict) else {}
    )

    owned_ids: list[str] = []
    shard_recipe_rows = request_input_payload.get("r")
    if isinstance(shard_recipe_rows, list):
        for recipe_row in shard_recipe_rows:
            if not isinstance(recipe_row, dict):
                continue
            recipe_id = str(recipe_row.get("rid") or "").strip()
            if recipe_id:
                owned_ids.append(recipe_id)

    if not owned_ids:
        for key in ("owned_ids", "ids"):
            values = request_input_payload.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                recipe_id = str(value or "").strip()
                if recipe_id:
                    owned_ids.append(recipe_id)

    if owned_ids:
        return list(dict.fromkeys(owned_ids))

    recipe_id = _prompt_row_recipe_id(row, parse_json_like=parse_json_like)
    return [recipe_id] if recipe_id else []


def _line_context(
    *,
    line_text_by_index: dict[int, str],
    line_index: int,
    excerpt_limit: int,
    excerpt: Callable[..., str],
) -> dict[str, str]:
    previous = line_text_by_index.get(line_index - 1, "")
    current = line_text_by_index.get(line_index, "")
    following = line_text_by_index.get(line_index + 1, "")
    return {
        "previous_line": excerpt(previous, max_len=excerpt_limit),
        "current_line": excerpt(current, max_len=excerpt_limit),
        "next_line": excerpt(following, max_len=excerpt_limit),
    }


def _alignment_is_healthy(
    alignment: dict[str, Any],
    *,
    coerce_float: Callable[[Any], float | None],
    coverage_min: float,
    match_ratio_min: float,
) -> bool:
    canonical_coverage = coerce_float(alignment.get("canonical_char_coverage"))
    prediction_match_ratio = coerce_float(alignment.get("prediction_block_match_ratio"))
    if canonical_coverage is None or prediction_match_ratio is None:
        return False
    return canonical_coverage >= coverage_min and prediction_match_ratio >= match_ratio_min


def _build_projection_trace(
    *,
    line_view: Any,
    full_prompt_rows: list[dict[str, Any]],
    prompt_row_stage_key: Callable[[dict[str, Any]], str],
    parse_json_like: Callable[[Any], Any],
    coerce_str_list: Callable[[Any], list[str]],
    upload_bundle_recipe_correction_output_rows: Callable[[Any], list[dict[str, Any]]],
    upload_bundle_recipe_correction_metrics: Callable[[dict[str, Any]], dict[str, Any]],
    is_empty_mapping_value: Callable[[Any], bool],
    rate: Callable[[int, int], float | None],
) -> dict[str, Any]:
    wrong_line_indices = [
        line_index
        for line_index, gold_label in line_view.gold_label_by_index.items()
        if line_view.pred_label_by_index.get(line_index, gold_label) != gold_label
    ]
    wrong_line_set = set(wrong_line_indices)

    stage_call_counts: Counter[str] = Counter()
    stage_warning_counts: Counter[str] = Counter()
    stage_recipe_ids: dict[str, set[str]] = defaultdict(set)
    correction_empty_mapping_calls = 0
    correction_empty_mapping_recipe_ids: Counter[str] = Counter()

    for row in full_prompt_rows:
        stage_key = prompt_row_stage_key(row) or "unknown"
        stage_call_counts[stage_key] += 1

        recipe_id = str(row.get("recipe_id") or "").strip()
        if recipe_id:
            stage_recipe_ids[stage_key].add(recipe_id)

        parsed_response = parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = coerce_str_list(parsed_response.get("warnings"))
        correction_outputs = (
            upload_bundle_recipe_correction_output_rows(parsed_response)
            if stage_key == "recipe_refine"
            else []
        )
        if correction_outputs:
            warnings = []
            for output_row in correction_outputs:
                warnings.extend(upload_bundle_recipe_correction_metrics(output_row)["warnings"])
        if warnings:
            stage_warning_counts[stage_key] += len(warnings)

        if correction_outputs:
            empty_mapping_recipe_ids: list[str] = []
            for output_row in correction_outputs:
                metrics = upload_bundle_recipe_correction_metrics(output_row)
                if not metrics["empty_mapping"]:
                    continue
                output_recipe_id = str(output_row.get("recipe_id") or "").strip()
                if output_recipe_id:
                    empty_mapping_recipe_ids.append(output_recipe_id)
            if empty_mapping_recipe_ids:
                correction_empty_mapping_calls += 1
                for output_recipe_id in empty_mapping_recipe_ids:
                    correction_empty_mapping_recipe_ids[output_recipe_id] += 1
        elif "ingredient_step_mapping" in parsed_response and is_empty_mapping_value(
            parsed_response.get("ingredient_step_mapping")
        ):
            correction_empty_mapping_calls += 1
            if recipe_id:
                correction_empty_mapping_recipe_ids[recipe_id] += 1

    region_counts = {
        "inside_active_recipe_span": {"line_total": 0, "wrong_total": 0},
        "outside_active_recipe_span": {"line_total": 0, "wrong_total": 0},
    }
    recipe_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"line_total": 0, "wrong_total": 0}
    )
    for line_index in sorted(line_view.gold_label_by_index.keys()):
        recipe_id = line_view.recipe_id_by_index.get(line_index)
        region_key = "inside_active_recipe_span" if recipe_id else "outside_active_recipe_span"
        region_counts[region_key]["line_total"] += 1
        if line_index in wrong_line_set:
            region_counts[region_key]["wrong_total"] += 1

        if recipe_id:
            recipe_counts[recipe_id]["line_total"] += 1
            if line_index in wrong_line_set:
                recipe_counts[recipe_id]["wrong_total"] += 1

    return {
        "summary": {
            "canonical_line_total": len(line_view.gold_label_by_index),
            "wrong_line_total": len(wrong_line_indices),
            "stage_call_counts": dict(sorted(stage_call_counts.items())),
            "stage_warning_counts": dict(sorted(stage_warning_counts.items())),
            "correction_empty_ingredient_step_mapping_calls": correction_empty_mapping_calls,
        },
        "regions": {
            region: {
                **payload,
                "wrong_rate": rate(payload["wrong_total"], payload["line_total"]),
            }
            for region, payload in region_counts.items()
        },
        "per_recipe": [
            {
                "recipe_id": recipe_id,
                "line_total": payload["line_total"],
                "wrong_total": payload["wrong_total"],
                "wrong_rate": rate(payload["wrong_total"], payload["line_total"]),
            }
            for recipe_id, payload in sorted(
                recipe_counts.items(),
                key=lambda item: (
                    -item[1]["wrong_total"],
                    -item[1]["line_total"],
                    item[0],
                ),
            )
        ],
        "recipe_ids_seen_by_stage": {
            stage_key: sorted(recipe_ids)
            for stage_key, recipe_ids in sorted(stage_recipe_ids.items())
        },
        "correction_empty_mapping_recipe_ids": [
            {"recipe_id": recipe_id, "count": count}
            for recipe_id, count in correction_empty_mapping_recipe_ids.most_common()
        ],
        "bridge_note": (
            "Recipe span assignment for per-line diagnostics uses recipe-correction evidence rows. "
            "Canonical line indices that do not fall inside an active recipe span are treated as "
            "outside_active_recipe_span."
        ),
    }
