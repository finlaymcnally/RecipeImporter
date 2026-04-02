from __future__ import annotations

from pathlib import Path
from typing import Any

from .compare_control_analysis import (
    analyze,
    analyze_compare_control_categorical_controlled,
    analyze_compare_control_categorical_raw,
    analyze_compare_control_discovery,
    analyze_compare_control_numeric_controlled,
    analyze_compare_control_numeric_raw,
    build_subset_filter_patch,
    compare_control_split_segments,
    compare_control_weak_coverage_warnings,
    generate_insights,
    suggest_hold_constants,
    suggest_splits,
)
from .compare_control_constants import (
    COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD,
    COMPARE_CONTROL_DISCOVERY_DEFAULT_MAX_CARDS,
    COMPARE_CONTROL_DISCOVERY_MAX_CARDS,
)
from .compare_control_errors import CompareControlError, error_payload, success_payload
from .compare_control_fields import (
    ai_assistance_profile_for_record,
    ai_effort_label_for_record,
    ai_model_label_for_record,
    benchmark_variant_for_record,
    build_compare_control_field_catalog,
    collect_benchmark_field_paths,
    is_all_method_benchmark_record,
    is_official_golden_benchmark_record,
    is_speed_benchmark_record,
    previous_runs_field_value,
)
from .compare_control_filters import apply_filters, evaluate_previous_runs_filter_operator
from .dashboard_collect import collect_dashboard_data


def load_dashboard_records(
    output_root: Path,
    golden_root: Path,
    *,
    since_days: int | None,
    scan_reports: bool,
    scan_benchmark_reports: bool,
) -> list[dict[str, Any]]:
    data = collect_dashboard_data(
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        scan_reports=scan_reports,
        scan_benchmark_reports=scan_benchmark_reports,
    )
    return [record.model_dump(mode="python") for record in data.benchmark_records]


def build_field_catalog(records: list[dict[str, Any]]) -> dict[str, Any]:
    field_options = collect_benchmark_field_paths(records)
    compare_catalog = build_compare_control_field_catalog(records, field_options)
    return {
        "field_options": field_options,
        "fields": compare_catalog["fields"],
        "by_field": compare_catalog["by_field"],
        "numeric_fields": compare_catalog["numeric_fields"],
        "categorical_fields": compare_catalog["categorical_fields"],
    }
