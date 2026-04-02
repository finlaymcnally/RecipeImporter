from __future__ import annotations

import re
from typing import Any

from .compare_control_constants import COLUMN_FILTER_OPERATORS, UNARY_FILTER_OPERATORS
from .compare_control_errors import CompareControlError
from .compare_control_fields import (
    is_empty_rule_value,
    is_likely_ai_test_benchmark_record,
    is_official_golden_benchmark_record,
    maybe_number,
    normalize_rule_value,
    previous_runs_field_value,
)


def evaluate_previous_runs_filter_operator(
    value: Any,
    operator: Any,
    expected: Any,
) -> bool:
    op = str(operator or "contains")
    if op not in COLUMN_FILTER_OPERATORS:
        op = "contains"
    wanted = str(expected or "")

    if op == "is_empty":
        return is_empty_rule_value(value)
    if op == "not_empty":
        return not is_empty_rule_value(value)

    actual_text = normalize_rule_value(value)
    expected_text = normalize_rule_value(wanted)
    if op == "contains":
        return expected_text in actual_text
    if op == "not_contains":
        return expected_text not in actual_text
    if op == "starts_with":
        return actual_text.startswith(expected_text)
    if op == "ends_with":
        return actual_text.endswith(expected_text)
    if op == "regex":
        try:
            pattern = re.compile(wanted, re.IGNORECASE)
        except re.error:
            return False
        return bool(pattern.search(str("" if value is None else value)))

    left_number = maybe_number(value)
    right_number = maybe_number(wanted)
    if op == "gt":
        return left_number is not None and right_number is not None and left_number > right_number
    if op == "gte":
        return left_number is not None and right_number is not None and left_number >= right_number
    if op == "lt":
        return left_number is not None and right_number is not None and left_number < right_number
    if op == "lte":
        return left_number is not None and right_number is not None and left_number <= right_number

    if op in {"eq", "neq"}:
        if left_number is not None and right_number is not None:
            equal = left_number == right_number
        else:
            equal = actual_text == expected_text
        return equal if op == "eq" else not equal

    return False


def _normalize_column_filter_clause(raw_clause: Any) -> dict[str, str] | None:
    if not isinstance(raw_clause, dict):
        return None
    operator = str(raw_clause.get("operator") or "contains")
    if operator not in COLUMN_FILTER_OPERATORS:
        operator = "contains"
    unary = operator in UNARY_FILTER_OPERATORS
    value = "" if unary else str(raw_clause.get("value") or "")
    if not unary and value.strip() == "":
        return None
    return {
        "operator": operator,
        "value": value,
    }


def _normalize_column_filter_list(raw_value: Any) -> list[dict[str, str]]:
    source_list = raw_value if isinstance(raw_value, list) else [raw_value]
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in source_list:
        clause = _normalize_column_filter_clause(candidate)
        if clause is None:
            continue
        dedupe_key = f"{clause['operator']}::{normalize_rule_value(clause['value'])}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(clause)
    return normalized


def _normalize_filter_mode(value: Any) -> str:
    return "or" if str(value or "and").strip().lower() == "or" else "and"


def _normalize_column_filter_groups(raw_column_filters: Any) -> list[dict[str, Any]]:
    if raw_column_filters is None:
        return []

    if isinstance(raw_column_filters, list):
        groups_by_field: dict[str, dict[str, Any]] = {}
        ordered_fields: list[str] = []
        for entry in raw_column_filters:
            if not isinstance(entry, dict):
                continue
            field_name = str(entry.get("field") or "").strip()
            if not field_name:
                continue
            group = groups_by_field.get(field_name)
            if group is None:
                group = {
                    "field": field_name,
                    "mode": _normalize_filter_mode(entry.get("combine_mode")),
                    "clauses": [],
                }
                groups_by_field[field_name] = group
                ordered_fields.append(field_name)
            group["mode"] = _normalize_filter_mode(entry.get("combine_mode") or group["mode"])
            clause = _normalize_column_filter_clause(entry)
            if clause is not None:
                group["clauses"].append(clause)
        return [
            group
            for field_name in ordered_fields
            if (group := groups_by_field.get(field_name)) and group.get("clauses")
        ]

    if isinstance(raw_column_filters, dict):
        groups: list[dict[str, Any]] = []
        for field_name, config in raw_column_filters.items():
            key = str(field_name or "").strip()
            if not key:
                continue
            mode = "and"
            clauses_payload: Any = config
            if isinstance(config, dict):
                mode = _normalize_filter_mode(config.get("mode"))
                clauses_payload = config.get("clauses")
            clauses = _normalize_column_filter_list(clauses_payload)
            if not clauses:
                continue
            groups.append(
                {
                    "field": key,
                    "mode": mode,
                    "clauses": clauses,
                }
            )
        return groups

    return []


def _record_matches_previous_runs_filter_groups(
    record: dict[str, Any],
    grouped_filters: list[dict[str, Any]],
    global_mode: str,
) -> bool:
    groups = [
        group
        for group in grouped_filters
        if isinstance(group, dict) and isinstance(group.get("clauses"), list) and group["clauses"]
    ]
    if not groups:
        return True

    top_mode = _normalize_filter_mode(global_mode)

    def matches_group(group: dict[str, Any]) -> bool:
        clauses = group.get("clauses")
        if not isinstance(clauses, list) or not clauses:
            return True
        mode = _normalize_filter_mode(group.get("mode"))

        def evaluate(clause: dict[str, Any]) -> bool:
            value = previous_runs_field_value(record, str(group.get("field") or ""))
            return evaluate_previous_runs_filter_operator(
                value,
                clause.get("operator"),
                clause.get("value"),
            )

        if mode == "or":
            return any(evaluate(clause) for clause in clauses)
        return all(evaluate(clause) for clause in clauses)

    if top_mode == "or":
        return any(matches_group(group) for group in groups)
    return all(matches_group(group) for group in groups)


def _normalize_quick_filters(raw_quick_filters: Any) -> dict[str, bool]:
    source = raw_quick_filters if isinstance(raw_quick_filters, dict) else {}
    return {
        "exclude_ai_tests": bool(source.get("exclude_ai_tests", False)),
        "official_full_golden_only": bool(source.get("official_full_golden_only", True)),
    }


def _apply_quick_filters(
    records: list[dict[str, Any]],
    quick_filters: dict[str, bool],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filtered = list(records)
    removed_ai_tests = 0
    removed_unofficial = 0

    if quick_filters.get("exclude_ai_tests"):
        next_rows: list[dict[str, Any]] = []
        for record in filtered:
            if is_likely_ai_test_benchmark_record(record):
                removed_ai_tests += 1
                continue
            next_rows.append(record)
        filtered = next_rows

    if quick_filters.get("official_full_golden_only"):
        next_rows = []
        for record in filtered:
            if not is_official_golden_benchmark_record(record):
                removed_unofficial += 1
                continue
            next_rows.append(record)
        filtered = next_rows

    return filtered, {
        "source_total": len(records),
        "filtered_total": len(filtered),
        "removed_ai_tests": removed_ai_tests,
        "removed_unofficial": removed_unofficial,
        "enabled": quick_filters,
    }


def _validate_filter_regexes(groups: list[dict[str, Any]]) -> None:
    for group in groups:
        field_name = str(group.get("field") or "").strip()
        for clause in group.get("clauses") or []:
            operator = str(clause.get("operator") or "contains")
            if operator != "regex":
                continue
            pattern_text = str(clause.get("value") or "")
            try:
                re.compile(pattern_text, re.IGNORECASE)
            except re.error as exc:
                raise CompareControlError(
                    "invalid_filter_regex",
                    f"Invalid regex for field {field_name}.",
                    {
                        "field": field_name,
                        "operator": "regex",
                        "pattern": pattern_text,
                        "reason": str(exc),
                    },
                ) from exc


def apply_filters(
    records: list[dict[str, Any]],
    filters: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_records = list(records)
    filter_payload = filters if isinstance(filters, dict) else {}

    quick_filters = _normalize_quick_filters(filter_payload.get("quick_filters"))
    quick_filtered, quick_context = _apply_quick_filters(source_records, quick_filters)

    grouped_filters = _normalize_column_filter_groups(filter_payload.get("column_filters"))
    global_mode = _normalize_filter_mode(filter_payload.get("column_filter_global_mode"))
    _validate_filter_regexes(grouped_filters)

    if not grouped_filters:
        return quick_filtered, {
            "quick_filters": quick_context,
            "column_filters": {
                "global_mode": global_mode,
                "groups": [],
                "matched_rows": len(quick_filtered),
            },
        }

    matched = [
        record
        for record in quick_filtered
        if _record_matches_previous_runs_filter_groups(record, grouped_filters, global_mode)
    ]
    return matched, {
        "quick_filters": quick_context,
        "column_filters": {
            "global_mode": global_mode,
            "groups": grouped_filters,
            "matched_rows": len(matched),
        },
    }
