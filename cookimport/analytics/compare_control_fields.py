from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any

from . import benchmark_semantics
from .compare_control_constants import (
    ANALYSIS_FIELD_LABEL_OVERRIDES,
    ANALYSIS_FIELD_PREFERRED,
    COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD,
    COMPARE_CONTROL_FIELD_SKIP,
    COMPARE_CONTROL_OUTCOME_PREFERRED,
    PREVIOUS_RUNS_DEFAULT_COLUMNS,
)


def _normalize_path(path_value: str | None) -> str:
    return str(path_value or "").strip().replace("\\", "/")


def _basename(path_value: str | None) -> str:
    path = _normalize_path(path_value)
    if not path:
        return ""
    parts = path.split("/")
    return parts[-1] if parts else path


def _is_useful_source_token(token: str | None) -> bool:
    text = str(token or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower in {"eval", "eval_output"}:
        return False
    if lower.startswith("config_") or lower.startswith("repeat_"):
        return False
    return True


def _source_slug_from_artifact_path(path_value: str | None) -> str | None:
    raw = _normalize_path(path_value)
    if not raw:
        return None
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts:
        return None
    lower = [part.lower() for part in parts]

    marker_next = {
        "all-method-benchmark",
        "single-profile-benchmark",
        "scenario_runs",
        "source_runs",
    }
    for idx, segment in enumerate(lower):
        if segment not in marker_next:
            continue
        candidate = parts[idx + 1] if idx + 1 < len(parts) else None
        if _is_useful_source_token(candidate):
            return str(candidate)

    cohort_markers = {"candidate", "promoted", "challenger", "baseline", "control"}
    for idx, segment in enumerate(lower):
        if segment not in cohort_markers:
            continue
        candidate = parts[idx + 1] if idx + 1 < len(parts) else None
        if _is_useful_source_token(candidate):
            return str(candidate)

    for idx, segment in enumerate(lower):
        if segment != "eval":
            continue
        candidate = parts[idx + 1] if idx + 1 < len(parts) else None
        if _is_useful_source_token(candidate):
            return str(candidate)
    return None


def _clean_config_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if lower in {
        "none",
        "null",
        "n/a",
        "<default>",
        "default",
        "(default)",
    }:
        return None
    return text


def _run_config_summary_map(summary: Any) -> dict[str, str]:
    mapping: dict[str, str] = {}
    text = str(summary or "").strip()
    if not text:
        return mapping
    for chunk in text.split("|"):
        part = str(chunk or "").strip()
        if not part:
            continue
        idx = part.find("=")
        if idx <= 0:
            continue
        key = part[:idx].strip()
        value = part[idx + 1 :].strip()
        if key and value:
            mapping[key] = value
    return mapping


def _run_config_value(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    cfg = record.get("run_config")
    if not isinstance(cfg, dict):
        cfg = {}
    for key in keys:
        if key not in cfg:
            continue
        value = _clean_config_value(cfg.get(key))
        if value is not None:
            return value
    summary_fields = _run_config_summary_map(record.get("run_config_summary"))
    for key in keys:
        value = _clean_config_value(summary_fields.get(key))
        if value is not None:
            return value
    return None


def _benchmark_artifact_path(record: dict[str, Any]) -> str:
    return _normalize_path(record.get("artifact_dir")).lower()


def _raw_ai_model_for_record(record: dict[str, Any]) -> str | None:
    return _run_config_value(
        record,
        (
            "codex_farm_model",
            "codex_model",
            "provider_model",
            "model",
        ),
    )


def _raw_ai_effort_for_record(record: dict[str, Any]) -> str | None:
    return _run_config_value(
        record,
        (
            "codex_farm_reasoning_effort",
            "codex_farm_thinking_effort",
            "codex_reasoning_effort",
            "model_reasoning_effort",
            "thinking_effort",
            "reasoning_effort",
        ),
    )


def benchmark_variant_for_record(record: dict[str, Any]) -> str:
    return benchmark_semantics.benchmark_variant_for_record(record)


def ai_assistance_profile_for_record(record: dict[str, Any]) -> str:
    return benchmark_semantics.ai_assistance_profile_for_record(record)


def ai_assistance_profile_label_for_record(record: dict[str, Any]) -> str:
    return benchmark_semantics.ai_assistance_profile_label_for_record(record)


def _ai_model_for_record(record: dict[str, Any]) -> str | None:
    if ai_assistance_profile_for_record(record) == "deterministic":
        return None
    return _raw_ai_model_for_record(record)


def _ai_effort_for_record(record: dict[str, Any]) -> str | None:
    if ai_assistance_profile_for_record(record) == "deterministic":
        return None
    return _raw_ai_effort_for_record(record)


def _codex_runtime_error_for_record(record: dict[str, Any]) -> str | None:
    if ai_assistance_profile_for_record(record) == "deterministic":
        return None
    return _run_config_value(
        record,
        (
            "codex_farm_runtime_error",
            "codex_farm_fatal_error",
            "codex_farm_error",
            "fatal_error",
        ),
    )


def ai_model_label_for_record(record: dict[str, Any]) -> str:
    if _codex_runtime_error_for_record(record):
        return "System error"
    model = _ai_model_for_record(record)
    if model:
        return model
    if ai_assistance_profile_for_record(record) == "deterministic":
        return "off"
    return "-"


def _runtime_error_profile_label(record: dict[str, Any]) -> str | None:
    recipe_pipeline = _run_config_value(record, ("llm_recipe_pipeline", "llm_pipeline"))
    line_role_pipeline = _run_config_value(record, ("line_role_pipeline",))
    if recipe_pipeline is None and line_role_pipeline is None:
        return None
    recipe_on = recipe_pipeline is not None and recipe_pipeline.lower() != "off"
    line_role_on = line_role_pipeline is not None and line_role_pipeline.lower() != "off"
    if recipe_on and line_role_on:
        return "Full-stack AI"
    if recipe_on:
        return "Recipe only"
    if line_role_on:
        return "Line-role only"
    return "AI off"


def ai_effort_label_for_record(record: dict[str, Any]) -> str:
    effort = _ai_effort_for_record(record)
    if effort:
        return effort
    if _codex_runtime_error_for_record(record):
        runtime_profile = _runtime_error_profile_label(record)
        if runtime_profile:
            return runtime_profile
    return ai_assistance_profile_label_for_record(record)


def source_label_for_record(record: dict[str, Any]) -> str:
    source_file_label = _basename(record.get("source_file"))
    if source_file_label:
        return source_file_label
    slug = _source_slug_from_artifact_path(record.get("artifact_dir"))
    if slug:
        return slug
    artifact_tail = _basename(record.get("artifact_dir"))
    return artifact_tail or "-"


def is_speed_benchmark_record(record: dict[str, Any]) -> bool:
    return "/bench/speed/runs/" in _benchmark_artifact_path(record)


def is_all_method_benchmark_record(record: dict[str, Any]) -> bool:
    return "/all-method-benchmark/" in _benchmark_artifact_path(record)


def is_likely_ai_test_benchmark_record(record: dict[str, Any]) -> bool:
    path = _benchmark_artifact_path(record)
    if not path:
        return False
    if "/bench/" in path:
        return True
    if re.search(r"(^|/)pytest-\d+(/|$)", path):
        return True
    if re.search(r"(^|/)test_[^/]+(/|$)", path):
        return True

    parts = [segment for segment in path.split("/") if segment]
    for segment in parts:
        match = re.match(
            r"^(\d{4}-\d{2}-\d{2}[t_]\d{2}[.:]\d{2}[.:]\d{2})_(.+)$", segment
        )
        if not match:
            continue
        suffix = str(match.group(2) or "").lower()
        if re.search(
            r"(^|[-_])(manual|smoke|test|debug|quick|probe|sample|trial)([-_]|$)",
            suffix,
        ):
            return True
    return False


def is_official_golden_benchmark_record(record: dict[str, Any]) -> bool:
    if not benchmark_semantics.is_official_golden_benchmark_record(record):
        return False
    variant = benchmark_variant_for_record(record)
    return variant in {"vanilla", "codex-exec"}


def maybe_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str("" if value is None else value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _timestamp_to_number(value: Any) -> float | None:
    text = str("" if value is None else value).strip()
    if not text:
        return None
    normalized = re.sub(
        r"^(\d{4}-\d{2}-\d{2})_(\d{2})[.:](\d{2})[.:](\d{2})$",
        r"\1T\2:\3:\4",
        text,
    )
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp()


def compare_control_numeric_value(record: dict[str, Any], field_path: str) -> float | None:
    field = str(field_path or "").strip()
    raw_value = previous_runs_field_value(record, field)
    if field == "run_timestamp":
        return _timestamp_to_number(raw_value)
    return maybe_number(raw_value)


def normalize_rule_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).lower().strip()


def is_empty_rule_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list):
        return len(value) == 0
    return False


def previous_runs_discounted_token_total(
    tokens_input: Any,
    tokens_cached_input: Any,
    tokens_output: Any,
    tokens_total: Any,
) -> float | None:
    input_tokens = maybe_number(tokens_input)
    cached_tokens = maybe_number(tokens_cached_input)
    output_tokens = maybe_number(tokens_output)
    raw_total = maybe_number(tokens_total)
    if input_tokens is None and cached_tokens is None and output_tokens is None:
        return raw_total

    effective_input = input_tokens if input_tokens is not None else 0.0
    if cached_tokens is not None:
        if input_tokens is not None:
            effective_input = max(0.0, input_tokens - cached_tokens) + (cached_tokens * 0.1)
        else:
            effective_input = cached_tokens * 0.1
    effective_output = output_tokens if output_tokens is not None else 0.0
    return effective_input + effective_output


def previous_runs_metric_per_recipe(
    metric_value: Any,
    recipes_value: Any,
) -> float | None:
    metric = maybe_number(metric_value)
    recipes = maybe_number(recipes_value)
    if metric is None or recipes is None or recipes <= 0:
        return None
    return metric / recipes


def previous_runs_field_value(record: dict[str, Any], field_path: str) -> Any:
    field = str(field_path or "").strip()
    if field == "source_file_basename":
        return _basename(record.get("source_file"))
    if field == "source_label":
        return source_label_for_record(record)
    if field == "ai_model":
        return ai_model_label_for_record(record)
    if field == "ai_effort":
        return ai_effort_label_for_record(record)
    if field == "ai_assistance_profile":
        return ai_assistance_profile_label_for_record(record)
    if field == "all_token_use":
        return previous_runs_discounted_token_total(
            record.get("tokens_input"),
            record.get("tokens_cached_input"),
            record.get("tokens_output"),
            record.get("tokens_total"),
        )
    if field == "conversion_seconds_per_recipe":
        return previous_runs_metric_per_recipe(
            previous_runs_field_value(
                record,
                "run_config.single_book_split_cache.conversion_seconds",
            ),
            record.get("recipes"),
        )
    if field == "all_token_use_per_recipe":
        return previous_runs_metric_per_recipe(
            previous_runs_field_value(record, "all_token_use"),
            record.get("recipes"),
        )
    if field == "artifact_dir_basename":
        return _basename(record.get("artifact_dir"))
    if field == "all_method_record":
        return is_all_method_benchmark_record(record)
    if field == "speed_suite_record":
        return is_speed_benchmark_record(record)
    if not field:
        return None

    current: Any = record
    for key in field.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current.get(key)

    if isinstance(current, (list, dict)):
        try:
            return json.dumps(current, sort_keys=True)
        except TypeError:
            return str(current)
    return current


def _add_flattened_field_paths(
    value: Any,
    prefix: str,
    output: set[str],
    depth: int,
) -> None:
    if depth > 4:
        if prefix:
            output.add(prefix)
        return
    if value is None:
        if prefix:
            output.add(prefix)
        return
    if isinstance(value, list):
        if prefix:
            output.add(prefix)
        return
    if isinstance(value, dict):
        keys = list(value.keys())
        if not keys:
            if prefix:
                output.add(prefix)
            return
        for key in keys:
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _add_flattened_field_paths(value.get(key), next_prefix, output, depth + 1)
        return
    if prefix:
        output.add(prefix)


def collect_benchmark_field_paths(records: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "source_file_basename",
        "source_label",
        "source_file",
        "importer_name",
        "ai_model",
        "ai_effort",
        "ai_assistance_profile",
        "run_timestamp",
        "run_config_hash",
        "run_config_summary",
        "run_config.model",
        "run_config.reasoning_effort",
        "run_config.codex_model",
        "run_config.codex_reasoning_effort",
        "strict_accuracy",
        "macro_f1_excluding_other",
        "precision",
        "recall",
        "f1",
        "practical_f1",
        "gold_total",
        "gold_matched",
        "recipes",
        "conversion_seconds_per_recipe",
        "all_token_use",
        "all_token_use_per_recipe",
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
        "all_method_record",
        "speed_suite_record",
        "artifact_dir",
    ]
    discovered: set[str] = set()
    for record in records:
        _add_flattened_field_paths(record, "", discovered, 0)
    discovered.update(
        {
            "source_file_basename",
            "source_label",
            "ai_model",
            "ai_effort",
            "ai_assistance_profile",
            "artifact_dir_basename",
            "all_method_record",
            "speed_suite_record",
            "conversion_seconds_per_recipe",
            "all_token_use_per_recipe",
        }
    )
    discovered.update(PREVIOUS_RUNS_DEFAULT_COLUMNS)

    ordered: list[str] = []
    seen: set[str] = set()
    for field_name in preferred:
        if field_name in discovered and field_name not in seen:
            ordered.append(field_name)
            seen.add(field_name)
    for field_name in sorted(discovered):
        if field_name in seen:
            continue
        ordered.append(field_name)
        seen.add(field_name)
    return ordered


def analysis_field_label(field_name: str) -> str:
    override = ANALYSIS_FIELD_LABEL_OVERRIDES.get(field_name)
    if override:
        return override
    pretty = field_name.replace("_", " ").replace(".", " ").strip()
    if not pretty:
        return field_name
    return " ".join(word.capitalize() for word in pretty.split()) + f" ({field_name})"


def analysis_comparable_value(value: Any) -> str:
    if value is None:
        return "__EMPTY__"
    if isinstance(value, str):
        text = value.strip()
        return text if text else "__EMPTY__"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return "__EMPTY__"
        return str(value)
    return str(value)


def analysis_display_value(raw_value: Any, comparable_value: str) -> str:
    if comparable_value == "__EMPTY__":
        return "(empty)"
    if isinstance(raw_value, bool):
        return "true" if raw_value else "false"
    if isinstance(raw_value, (int, float)):
        value = float(raw_value)
        if not math.isfinite(value):
            return "(empty)"
        if value.is_integer():
            return str(int(value))
        return f"{value:.4f}"
    return str(raw_value)


def _compare_control_field_sort_value(field_info: dict[str, Any]) -> int:
    return int(field_info.get("non_empty_count") or 0)


def build_compare_control_field_catalog(
    records: list[dict[str, Any]],
    field_options: list[str],
) -> dict[str, Any]:
    by_field: dict[str, dict[str, Any]] = {}
    ordered_fields: list[dict[str, Any]] = []
    seen: set[str] = set()

    def consider_field(field_name: str) -> None:
        key = str(field_name or "").strip()
        if not key or key in seen or key in COMPARE_CONTROL_FIELD_SKIP:
            return
        seen.add(key)
        value_counts: dict[str, dict[str, Any]] = {}
        numeric_values: list[float] = []
        non_empty = 0
        numeric_count = 0
        for record in records:
            raw_value = previous_runs_field_value(record, key)
            if is_empty_rule_value(raw_value):
                continue
            comparable_key = analysis_comparable_value(raw_value)
            if comparable_key not in value_counts:
                value_counts[comparable_key] = {
                    "key": comparable_key,
                    "label": analysis_display_value(raw_value, comparable_key),
                    "count": 0,
                }
            value_counts[comparable_key]["count"] += 1
            non_empty += 1
            numeric_value = compare_control_numeric_value(record, key)
            if numeric_value is not None:
                numeric_count += 1
                numeric_values.append(numeric_value)

        categories = sorted(
            value_counts.values(),
            key=lambda entry: (
                -int(entry.get("count") or 0),
                str(entry.get("label") or "").lower(),
            ),
        )
        distinct_count = len(categories)
        if distinct_count < 2:
            return

        numeric = non_empty > 0 and numeric_count == non_empty
        info = {
            "field": key,
            "label": analysis_field_label(key),
            "numeric": numeric,
            "time_like": key == "run_timestamp" and numeric,
            "non_empty_count": non_empty,
            "distinct_count": distinct_count,
            "categories": [] if numeric else categories[:120],
            "numeric_min": min(numeric_values) if numeric_values else None,
            "numeric_max": max(numeric_values) if numeric_values else None,
        }
        by_field[key] = info
        ordered_fields.append(info)

    for name in COMPARE_CONTROL_OUTCOME_PREFERRED:
        consider_field(name)
    for name in ANALYSIS_FIELD_PREFERRED:
        consider_field(name)
    for name in PREVIOUS_RUNS_DEFAULT_COLUMNS:
        consider_field(name)
    for name in field_options:
        consider_field(name)

    ordered_fields.sort(
        key=lambda item: (
            -_compare_control_field_sort_value(item),
            str(item.get("label") or item.get("field") or "").lower(),
        )
    )
    numeric_fields = [field for field in ordered_fields if field.get("numeric")]
    categorical_fields = [field for field in ordered_fields if not field.get("numeric")]
    return {
        "fields": ordered_fields,
        "by_field": by_field,
        "numeric_fields": numeric_fields,
        "categorical_fields": categorical_fields,
    }


def choose_default_compare_outcome(catalog: dict[str, Any]) -> str:
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    if not isinstance(by_field, dict):
        by_field = {}
    for field_name in COMPARE_CONTROL_OUTCOME_PREFERRED:
        info = by_field.get(field_name)
        if isinstance(info, dict) and info.get("numeric"):
            return field_name
    numeric_fields = catalog.get("numeric_fields") if isinstance(catalog, dict) else []
    if isinstance(numeric_fields, list) and numeric_fields:
        first = numeric_fields[0]
        if isinstance(first, dict) and first.get("field"):
            return str(first["field"])
    return COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD
