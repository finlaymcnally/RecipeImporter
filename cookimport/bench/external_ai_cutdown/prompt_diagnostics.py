from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .io import _iter_jsonl


def _parse_json_like(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _coerce_str_list(value: Any) -> list[str]:
    parsed = _parse_json_like(value)
    if isinstance(parsed, list):
        rows: list[str] = []
        for entry in parsed:
            if isinstance(entry, str):
                text = entry.strip()
                if text:
                    rows.append(text)
        return rows
    if isinstance(parsed, str):
        text = parsed.strip()
        if text:
            return [text]
    return []


def _is_empty_mapping_value(value: Any) -> bool:
    parsed = _parse_json_like(value)
    if isinstance(parsed, dict):
        return len(parsed) == 0
    if isinstance(parsed, str):
        return parsed.strip() in {"{}", "null", ""}
    return value is None


def _upload_bundle_recipe_correction_output_rows(value: Any) -> list[dict[str, Any]]:
    parsed = _parse_json_like(value)
    if not isinstance(parsed, dict):
        return []

    candidates: list[dict[str, Any]] = []
    payload = parsed.get("payload")
    if isinstance(payload, dict):
        candidates.append(payload)
    candidates.append(parsed)

    for candidate in candidates:
        recipe_rows = candidate.get("r")
        if not isinstance(recipe_rows, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for recipe_row in recipe_rows:
            if not isinstance(recipe_row, dict):
                continue
            compact_recipe = recipe_row.get("cr")
            compact_recipe = compact_recipe if isinstance(compact_recipe, dict) else {}
            normalized_rows.append(
                {
                    "recipe_id": str(recipe_row.get("rid") or "").strip(),
                    "repair_status": str(recipe_row.get("st") or "").strip(),
                    "status_reason": str(recipe_row.get("sr") or "").strip(),
                    "warnings": _coerce_str_list(recipe_row.get("w")),
                    "has_mapping_field": "m" in recipe_row,
                    "canonical_recipe": {
                        "title": str(compact_recipe.get("t") or "").strip(),
                        "ingredients": _coerce_str_list(compact_recipe.get("i")),
                        "steps": _coerce_str_list(compact_recipe.get("s")),
                        "description": str(compact_recipe.get("d") or "").strip(),
                        "recipe_yield": str(compact_recipe.get("y") or "").strip(),
                    },
                    "ingredient_step_mapping": recipe_row.get("m"),
                    "ingredient_step_mapping_reason": str(recipe_row.get("mr") or "").strip(),
                }
            )
        if normalized_rows:
            return normalized_rows

    if any(
        key in parsed
        for key in (
            "canonical_recipe",
            "ingredient_step_mapping",
            "ingredient_step_mapping_reason",
            "warnings",
        )
    ):
        canonical_recipe = (
            parsed.get("canonical_recipe") if isinstance(parsed.get("canonical_recipe"), dict) else {}
        )
        return [
            {
                "recipe_id": str(parsed.get("recipe_id") or "").strip(),
                "repair_status": str(parsed.get("repair_status") or "").strip(),
                "status_reason": str(parsed.get("status_reason") or "").strip(),
                "warnings": _coerce_str_list(parsed.get("warnings")),
                "has_mapping_field": "ingredient_step_mapping" in parsed,
                "canonical_recipe": {
                    "title": str(canonical_recipe.get("title") or "").strip(),
                    "ingredients": _coerce_str_list(canonical_recipe.get("ingredients")),
                    "steps": _coerce_str_list(canonical_recipe.get("steps")),
                    "description": str(canonical_recipe.get("description") or "").strip(),
                    "recipe_yield": str(canonical_recipe.get("recipe_yield") or "").strip(),
                },
                "ingredient_step_mapping": parsed.get("ingredient_step_mapping"),
                "ingredient_step_mapping_reason": str(
                    parsed.get("ingredient_step_mapping_reason") or ""
                ).strip(),
            }
        ]
    return []


def _upload_bundle_recipe_correction_output_for_recipe(
    value: Any,
    *,
    recipe_id: str,
) -> dict[str, Any]:
    normalized_recipe_id = str(recipe_id or "").strip()
    rows = _upload_bundle_recipe_correction_output_rows(value)
    if normalized_recipe_id:
        for row in rows:
            if str(row.get("recipe_id") or "").strip() == normalized_recipe_id:
                return row
    return rows[0] if len(rows) == 1 else {}


def _upload_bundle_recipe_correction_input_row_count(
    value: Any,
    *,
    recipe_id: str | None = None,
) -> int:
    parsed = _parse_json_like(value)
    if not isinstance(parsed, dict):
        return 0
    normalized_recipe_id = str(recipe_id or "").strip()
    if normalized_recipe_id:
        shard_recipe_rows = parsed.get("r")
        if isinstance(shard_recipe_rows, list):
            for recipe_row in shard_recipe_rows:
                if not isinstance(recipe_row, dict):
                    continue
                if str(recipe_row.get("rid") or "").strip() != normalized_recipe_id:
                    continue
                evidence_rows = recipe_row.get("ev")
                return len(evidence_rows) if isinstance(evidence_rows, list) else 0
    evidence_rows = parsed.get("evidence_rows")
    if isinstance(evidence_rows, list):
        return len(evidence_rows)
    shard_recipe_rows = parsed.get("r")
    if isinstance(shard_recipe_rows, list):
        return sum(
            len(recipe_row.get("ev") or [])
            for recipe_row in shard_recipe_rows
            if isinstance(recipe_row, dict) and isinstance(recipe_row.get("ev"), list)
        )
    return 0


def _upload_bundle_recipe_correction_metrics(
    output_row: dict[str, Any],
    *,
    mapping_count: Callable[[Any], int],
) -> dict[str, Any]:
    canonical_recipe = (
        output_row.get("canonical_recipe")
        if isinstance(output_row.get("canonical_recipe"), dict)
        else {}
    )
    ingredients = _coerce_str_list(canonical_recipe.get("ingredients"))
    steps = _coerce_str_list(canonical_recipe.get("steps"))
    warnings = _coerce_str_list(output_row.get("warnings"))
    mapping_value = output_row.get("ingredient_step_mapping")
    mapping_count_value = mapping_count(mapping_value)
    has_signal = bool(
        str(canonical_recipe.get("title") or "").strip()
        or str(canonical_recipe.get("description") or "").strip()
        or str(canonical_recipe.get("recipe_yield") or "").strip()
        or ingredients
        or steps
        or mapping_count_value > 0
        or warnings
        or str(output_row.get("repair_status") or "").strip()
        or str(output_row.get("status_reason") or "").strip()
    )
    return {
        "ingredient_count": len(ingredients),
        "step_count": len(steps),
        "mapping_count": mapping_count_value,
        "warnings": warnings,
        "empty_mapping": bool(output_row.get("has_mapping_field"))
        and _is_empty_mapping_value(mapping_value),
        "empty_output": not has_signal,
    }


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_warning_bucket_name(bucket: str) -> str:
    cleaned = str(bucket or "").strip().lower()
    if cleaned in {"ocr_or_page_artifact", "page_or_layout_artifact"}:
        return "page_or_layout_artifact"
    return cleaned


def _normalize_warning_bucket_reason(reason: str) -> str:
    cleaned = str(reason or "").strip()
    normalized_bare = _normalize_warning_bucket_name(cleaned)
    if normalized_bare and normalized_bare != cleaned:
        return normalized_bare
    prefix = "warning_bucket:"
    if not cleaned.startswith(prefix):
        return cleaned
    bucket = _normalize_warning_bucket_name(cleaned[len(prefix) :])
    if not bucket:
        return cleaned
    return f"{prefix}{bucket}"


def _prompt_warning_bucket(message: str) -> str:
    lowered = message.lower()
    if "split" in lowered and "line" in lowered:
        return "split_line_boundary"
    if "serving" in lowered and "split" in lowered:
        return "serving_boundary_split"
    if "ingredient" in lowered and ("fragment" in lowered or "incomplete" in lowered):
        return "ingredient_fragment"
    if "no " in lowered and "instruction" in lowered:
        return "missing_instructions"
    if "page" in lowered or "ocr" in lowered or "artifact" in lowered:
        return "page_or_layout_artifact"
    if "yield" in lowered:
        return "yield_detection"
    return "other"


def _summarize_prompt_warning_aggregate(
    full_prompt_log_path: Path,
    *,
    prompt_row_stage_key: Callable[[dict[str, Any]], str],
    mapping_count: Callable[[Any], int],
) -> dict[str, Any]:
    rows = _iter_jsonl(full_prompt_log_path)
    by_stage_calls: Counter[str] = Counter()
    by_stage_calls_with_warnings: Counter[str] = Counter()
    warning_message_counts: Counter[str] = Counter()
    warning_bucket_counts: Counter[str] = Counter()
    correction_empty_mapping_calls = 0
    correction_empty_mapping_recipe_ids: Counter[str] = Counter()

    calls_with_warnings = 0
    warning_total = 0

    for row in rows:
        stage_key = prompt_row_stage_key(row) or "unknown"
        by_stage_calls[stage_key] += 1

        parsed_response = _parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = _coerce_str_list(parsed_response.get("warnings"))
        correction_outputs = (
            _upload_bundle_recipe_correction_output_rows(parsed_response)
            if stage_key == "recipe_refine"
            else []
        )
        if correction_outputs:
            warnings = []
            for output_row in correction_outputs:
                warnings.extend(
                    _upload_bundle_recipe_correction_metrics(
                        output_row,
                        mapping_count=mapping_count,
                    )["warnings"]
                )
        if warnings:
            calls_with_warnings += 1
            by_stage_calls_with_warnings[stage_key] += 1
        for warning in warnings:
            normalized = _normalize_whitespace(warning)
            warning_message_counts[normalized] += 1
            warning_bucket_counts[_prompt_warning_bucket(normalized)] += 1
            warning_total += 1

        if correction_outputs:
            empty_mapping_recipe_ids: list[str] = []
            for output_row in correction_outputs:
                metrics = _upload_bundle_recipe_correction_metrics(
                    output_row,
                    mapping_count=mapping_count,
                )
                if not metrics["empty_mapping"]:
                    continue
                recipe_id = str(output_row.get("recipe_id") or row.get("recipe_id") or "").strip()
                if recipe_id:
                    empty_mapping_recipe_ids.append(recipe_id)
            if empty_mapping_recipe_ids:
                correction_empty_mapping_calls += 1
                for recipe_id in empty_mapping_recipe_ids:
                    correction_empty_mapping_recipe_ids[recipe_id] += 1
        elif "ingredient_step_mapping" in parsed_response and _is_empty_mapping_value(
            parsed_response.get("ingredient_step_mapping")
        ):
            correction_empty_mapping_calls += 1
            recipe_id = str(row.get("recipe_id") or "").strip()
            if recipe_id:
                correction_empty_mapping_recipe_ids[recipe_id] += 1

    return {
        "source_full_prompt_log": str(full_prompt_log_path),
        "total_calls": len(rows),
        "calls_with_warnings": calls_with_warnings,
        "warnings_total": warning_total,
        "calls_by_stage": dict(sorted(by_stage_calls.items())),
        "calls_with_warnings_by_stage": dict(sorted(by_stage_calls_with_warnings.items())),
        "warning_buckets": dict(
            sorted(warning_bucket_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "top_warning_messages": [
            {"warning": message, "count": count}
            for message, count in warning_message_counts.most_common(20)
        ],
        "correction_empty_ingredient_step_mapping_calls": correction_empty_mapping_calls,
        "correction_empty_ingredient_step_mapping_recipe_ids": [
            {"recipe_id": recipe_id, "count": count}
            for recipe_id, count in correction_empty_mapping_recipe_ids.most_common()
        ],
    }
