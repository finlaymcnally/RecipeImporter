from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from cookimport.analytics import compare_control_engine as engine
from cookimport.analytics.compare_control_engine import (
    COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD,
    COMPARE_CONTROL_DISCOVERY_DEFAULT_MAX_CARDS,
    COMPARE_CONTROL_DISCOVERY_MAX_CARDS,
)
from cookimport.analytics.dashboard_state_server import (
    _read_ui_state_payload,
    _ui_state_path_for_dashboard,
    _write_ui_state_payload,
    ensure_dashboard_ui_state_file,
)
from cookimport.paths import history_root_for_output

COMPARE_CONTROL_CHART_LAYOUTS = {"stacked", "side_by_side", "combined"}
COMPARE_CONTROL_DEFAULT_CHART_LAYOUT = "stacked"
COMPARE_CONTROL_COMBINED_AXIS_MODES = {"single", "dual"}
COMPARE_CONTROL_DEFAULT_COMBINED_AXIS_MODE = "single"


def _clean_compare_control_string_list(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values or []:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(key)
    return cleaned


def _normalize_compare_control_discovery_prefs_for_dashboard(
    value: Any,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    max_cards_raw = source.get("max_cards")
    if max_cards_raw is None:
        max_cards = COMPARE_CONTROL_DISCOVERY_DEFAULT_MAX_CARDS
    else:
        try:
            max_cards = int(max_cards_raw)
        except (TypeError, ValueError):
            max_cards = COMPARE_CONTROL_DISCOVERY_DEFAULT_MAX_CARDS
    max_cards = max(1, min(COMPARE_CONTROL_DISCOVERY_MAX_CARDS, max_cards))
    return {
        "exclude_fields": _clean_compare_control_string_list(source.get("exclude_fields")),
        "prefer_fields": _clean_compare_control_string_list(source.get("prefer_fields")),
        "demote_patterns": _clean_compare_control_string_list(source.get("demote_patterns")),
        "max_cards": max_cards,
    }


def _normalize_compare_control_dashboard_chart_layout(value: Any) -> str:
    key = str(value or COMPARE_CONTROL_DEFAULT_CHART_LAYOUT).strip().lower()
    if key in COMPARE_CONTROL_CHART_LAYOUTS:
        return key
    return COMPARE_CONTROL_DEFAULT_CHART_LAYOUT


def _normalize_compare_control_dashboard_combined_axis_mode(value: Any) -> str:
    key = str(value or COMPARE_CONTROL_DEFAULT_COMBINED_AXIS_MODE).strip().lower()
    if key in COMPARE_CONTROL_COMBINED_AXIS_MODES:
        return key
    return COMPARE_CONTROL_DEFAULT_COMBINED_AXIS_MODE


def _resolve_compare_control_dashboard_dir(
    output_root: Path,
    dashboard_dir: Path | None,
) -> Path:
    if dashboard_dir is not None:
        return dashboard_dir.expanduser()
    return history_root_for_output(output_root.expanduser()) / "dashboard"


def _compare_control_ui_state_path_for_dashboard(dashboard_dir: Path) -> Path:
    return _ui_state_path_for_dashboard(dashboard_dir.expanduser())


def _default_compare_control_dashboard_state_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "previous_runs": {
            "compare_control": {
                "outcome_field": COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD,
                "compare_field": "",
                "hold_constant_fields": [],
                "split_field": "",
                "view_mode": "discover",
                "selected_groups": [],
                "discovery_preferences": _normalize_compare_control_discovery_prefs_for_dashboard(
                    {}
                ),
                "second_set_enabled": False,
                "chart_layout": COMPARE_CONTROL_DEFAULT_CHART_LAYOUT,
                "combined_axis_mode": COMPARE_CONTROL_DEFAULT_COMBINED_AXIS_MODE,
            }
        },
    }


def _load_compare_control_dashboard_ui_state_payload(ui_state_path: Path) -> dict[str, Any]:
    if not ui_state_path.exists():
        return _default_compare_control_dashboard_state_payload()
    payload = _read_ui_state_payload(ui_state_path)
    if not isinstance(payload, dict):
        return _default_compare_control_dashboard_state_payload()
    return payload


def _write_compare_control_dashboard_ui_state_payload(
    ui_state_path: Path,
    payload: dict[str, Any],
) -> None:
    ensure_dashboard_ui_state_file(ui_state_path.parent.parent)
    next_payload = dict(payload)
    next_payload["saved_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    _write_ui_state_payload(ui_state_path, next_payload)


def _compare_control_dispatch_action(
    records: list[dict[str, Any]],
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resolved_action = str(action or "").strip().lower()
    query = payload if isinstance(payload, dict) else {}

    if resolved_action in {"analyze", "discover"}:
        next_query = dict(query)
        if resolved_action == "discover":
            next_query["view_mode"] = "discover"
        return engine.analyze(records, next_query)
    if resolved_action == "fields":
        filtered_records, filter_context = engine.apply_filters(records, query.get("filters"))
        return {
            **engine.build_field_catalog(filtered_records),
            "candidate_rows": len(filtered_records),
            "filters": filter_context,
        }
    if resolved_action == "suggest_hold_constants":
        return engine.suggest_hold_constants(records, query)
    if resolved_action == "suggest_splits":
        return engine.suggest_splits(records, query)
    if resolved_action == "insights":
        return engine.generate_insights(records, query)
    if resolved_action == "subset_filter_patch":
        return engine.build_subset_filter_patch(
            str(query.get("compare_field") or ""),
            [
                str(value).strip()
                for value in (query.get("selected_groups") or [])
                if str(value).strip()
            ],
        )
    if resolved_action == "ping":
        return {"pong": True}
    raise engine.CompareControlError(
        "unknown_action",
        f"Unsupported compare-control action: {resolved_action or '<empty>'}.",
    )
