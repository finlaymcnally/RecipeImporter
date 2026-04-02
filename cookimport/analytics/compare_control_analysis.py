from __future__ import annotations

import math
from typing import Any

from .compare_control_constants import (
    COMPARE_CONTROL_DISCOVERY_DEFAULT_MAX_CARDS,
    COMPARE_CONTROL_DISCOVERY_DEMOTE_FACTOR,
    COMPARE_CONTROL_DISCOVERY_MAX_CARDS,
    COMPARE_CONTROL_DISCOVERY_PREFER_FIELD_BOOST,
    COMPARE_CONTROL_SECONDARY_FIELD_PATTERN,
    COMPARE_CONTROL_SECONDARY_MAX_FIELDS,
    COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED,
    COMPARE_CONTROL_VIEW_MODES,
    COMPARE_CONTROL_WARNING_MIN_ROWS,
    COMPARE_CONTROL_WARNING_MIN_STRATA,
    COMPARE_CONTROL_WARNING_ROW_COVERAGE_MIN,
    COMPARE_CONTROL_WARNING_STRATA_COVERAGE_MIN,
    INSIGHTS_COMPARE_FIELD_PREFERRED,
    INSIGHTS_DISCOVERY_NOISE_PATTERN,
    INSIGHTS_HOLD_FIELD_PREFERRED,
    INSIGHTS_PROCESS_FIELDS,
)
from .compare_control_errors import CompareControlError
from .compare_control_fields import (
    COMPARE_CONTROL_FIELD_SKIP,
    analysis_comparable_value,
    analysis_display_value,
    build_compare_control_field_catalog,
    choose_default_compare_outcome,
    collect_benchmark_field_paths,
    is_empty_rule_value,
    maybe_number,
    previous_runs_field_value,
)
from .compare_control_filters import apply_filters


def _normalize_view_mode(value: Any) -> str:
    key = str(value or "discover").strip().lower()
    return key if key in COMPARE_CONTROL_VIEW_MODES else "discover"


def _unique_string_list(values: Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    source = values if isinstance(values, list) else []
    for value in source:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _normalize_discovery_preferences(value: Any) -> dict[str, Any]:
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
        "exclude_fields": _unique_string_list(source.get("exclude_fields")),
        "prefer_fields": _unique_string_list(source.get("prefer_fields")),
        "demote_patterns": _unique_string_list(source.get("demote_patterns")),
        "max_cards": max_cards,
    }


def _normalize_compare_control_state_for_catalog(
    raw_state: dict[str, Any] | None,
    catalog: dict[str, Any],
) -> dict[str, Any]:
    source = raw_state if isinstance(raw_state, dict) else {}
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    if not isinstance(by_field, dict):
        by_field = {}
    default_outcome = choose_default_compare_outcome(catalog)

    state = {
        "outcome_field": str(source.get("outcome_field") or default_outcome).strip() or default_outcome,
        "compare_field": str(source.get("compare_field") or "").strip(),
        "hold_constant_fields": _unique_string_list(source.get("hold_constant_fields")),
        "split_field": str(source.get("split_field") or "").strip(),
        "view_mode": _normalize_view_mode(source.get("view_mode")),
        "selected_groups": _unique_string_list(source.get("selected_groups")),
        "discovery_preferences": _normalize_discovery_preferences(
            source.get("discovery_preferences")
        ),
    }

    if state["outcome_field"] not in by_field or not bool(by_field[state["outcome_field"]].get("numeric")):
        state["outcome_field"] = default_outcome

    if state["compare_field"] and state["compare_field"] not in by_field:
        state["compare_field"] = ""
    if state["compare_field"] == state["outcome_field"]:
        state["compare_field"] = ""

    state["hold_constant_fields"] = [
        field
        for field in state["hold_constant_fields"]
        if field in by_field and field not in {state["outcome_field"], state["compare_field"]}
    ]

    split_field = state["split_field"]
    if split_field not in by_field or split_field in {
        state["outcome_field"],
        state["compare_field"],
    }:
        state["split_field"] = ""

    if not state["compare_field"]:
        state["view_mode"] = "discover"
        state["selected_groups"] = []
    else:
        compare_info = by_field.get(state["compare_field"], {})
        if not isinstance(compare_info, dict) or compare_info.get("numeric"):
            state["selected_groups"] = []
        else:
            allowed = {
                str(entry.get("key") or "").strip()
                for entry in compare_info.get("categories") or []
                if isinstance(entry, dict)
            }
            allowed.discard("")
            allowed.discard("__EMPTY__")
            state["selected_groups"] = [
                value for value in state["selected_groups"] if value in allowed
            ]

    return state


def _insights_top_categories(
    catalog: dict[str, Any],
    field_name: str,
    *,
    max_items: int = 5,
) -> list[dict[str, Any]]:
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    if not isinstance(by_field, dict):
        return []
    info = by_field.get(field_name)
    if not isinstance(info, dict):
        return []
    categories = info.get("categories")
    if not isinstance(categories, list):
        return []
    top: list[dict[str, Any]] = []
    for entry in categories[: max(1, max_items)]:
        if not isinstance(entry, dict):
            continue
        top.append(
            {
                "key": entry.get("key"),
                "label": entry.get("label"),
                "count": int(entry.get("count") or 0),
            }
        )
    return top


def _insights_pick_compare_field(
    state: dict[str, Any],
    catalog: dict[str, Any],
) -> str:
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    if not isinstance(by_field, dict):
        return ""

    requested = str(state.get("compare_field") or "").strip()
    if requested and requested in by_field:
        return requested

    def _good_categorical_field(field_name: str) -> bool:
        info = by_field.get(field_name)
        if not isinstance(info, dict):
            return False
        if bool(info.get("numeric")):
            return False
        distinct = int(info.get("distinct_count") or 0)
        return 2 <= distinct <= 16

    for field_name in INSIGHTS_COMPARE_FIELD_PREFERRED:
        if _good_categorical_field(field_name):
            return field_name

    fields = catalog.get("fields") if isinstance(catalog, dict) else []
    if isinstance(fields, list):
        for field_info in fields:
            if not isinstance(field_info, dict):
                continue
            field_name = str(field_info.get("field") or "").strip()
            if not field_name:
                continue
            if _good_categorical_field(field_name):
                return field_name
    return ""


def _insights_pick_hold_fields(
    state: dict[str, Any],
    catalog: dict[str, Any],
    *,
    outcome_field: str,
    compare_field: str,
) -> list[str]:
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    if not isinstance(by_field, dict):
        return []

    requested = [
        str(value or "").strip()
        for value in (state.get("hold_constant_fields") or [])
        if str(value or "").strip()
    ]
    if requested:
        return [
            field_name
            for field_name in requested
            if field_name in by_field and field_name not in {outcome_field, compare_field}
        ]

    selected: list[str] = []
    for field_name in INSIGHTS_HOLD_FIELD_PREFERRED:
        if field_name not in by_field:
            continue
        if field_name in {outcome_field, compare_field}:
            continue
        selected.append(field_name)
        if len(selected) >= 2:
            break
    return selected


def _insights_is_noise_field(field_name: str) -> bool:
    key = str(field_name or "").strip()
    if not key:
        return True
    return bool(INSIGHTS_DISCOVERY_NOISE_PATTERN.search(key))


def _insights_categorical_delta(analysis: dict[str, Any]) -> dict[str, Any] | None:
    groups = analysis.get("groups") if isinstance(analysis, dict) else None
    if not isinstance(groups, list):
        return None

    candidates: list[dict[str, Any]] = []
    for entry in groups:
        if not isinstance(entry, dict):
            continue
        mean = maybe_number(entry.get("outcome_mean"))
        if mean is None:
            continue
        candidates.append(
            {
                "key": entry.get("key"),
                "label": entry.get("label"),
                "count": int(entry.get("count") or 0),
                "outcome_mean": mean,
            }
        )
    if len(candidates) < 2:
        return None

    ranked = sorted(candidates, key=lambda item: float(item["outcome_mean"]), reverse=True)
    best = ranked[0]
    worst = ranked[-1]
    return {
        "best_group": best,
        "worst_group": worst,
        "outcome_delta": float(best["outcome_mean"]) - float(worst["outcome_mean"]),
    }


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _rank_with_ties(values: list[float]) -> list[float]:
    indexed = sorted(((value, idx) for idx, value in enumerate(values)), key=lambda item: item[0])
    ranks = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        end = idx
        while end + 1 < len(indexed) and indexed[end + 1][0] == indexed[idx][0]:
            end += 1
        rank = (idx + end + 2) / 2
        for pos in range(idx, end + 1):
            ranks[indexed[pos][1]] = rank
        idx = end + 1
    return ranks


def _pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    if mean_x is None or mean_y is None:
        return None
    sum_xy = 0.0
    sum_xx = 0.0
    sum_yy = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        sum_xy += dx * dy
        sum_xx += dx * dx
        sum_yy += dy * dy
    if sum_xx <= 0 or sum_yy <= 0:
        return None
    return sum_xy / math.sqrt(sum_xx * sum_yy)


def _spearman_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    rank_x = _rank_with_ties(xs)
    rank_y = _rank_with_ties(ys)
    return _pearson_correlation(rank_x, rank_y)


def _linear_regression_from_pairs(pairs: list[dict[str, float]]) -> dict[str, float | None]:
    if len(pairs) < 2:
        return {
            "slope": None,
            "intercept": None,
            "r_squared": None,
            "pearson": None,
        }
    xs = [pair["x"] for pair in pairs]
    ys = [pair["y"] for pair in pairs]
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    if mean_x is None or mean_y is None:
        return {
            "slope": None,
            "intercept": None,
            "r_squared": None,
            "pearson": None,
        }
    sum_xx = 0.0
    sum_xy = 0.0
    for pair in pairs:
        dx = pair["x"] - mean_x
        sum_xx += dx * dx
        sum_xy += dx * (pair["y"] - mean_y)
    if sum_xx <= 0:
        return {
            "slope": 0.0,
            "intercept": mean_y,
            "r_squared": 0.0,
            "pearson": 0.0,
        }
    slope = sum_xy / sum_xx
    intercept = mean_y - (slope * mean_x)
    pearson = _pearson_correlation(xs, ys)
    r_squared = None if pearson is None else pearson * pearson
    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "pearson": pearson,
    }


def _equal_count_bins_from_pairs(
    pairs: list[dict[str, float]],
    max_bins: int,
) -> list[dict[str, Any]]:
    sorted_pairs = sorted(
        [
            pair
            for pair in pairs
            if math.isfinite(pair["x"]) and math.isfinite(pair["y"])
        ],
        key=lambda pair: pair["x"],
    )
    if not sorted_pairs:
        return []
    target_bins = max(1, min(max_bins, len(sorted_pairs)))
    bin_size = max(1, math.ceil(len(sorted_pairs) / target_bins))
    bins: list[dict[str, Any]] = []
    for start in range(0, len(sorted_pairs), bin_size):
        chunk = sorted_pairs[start : start + bin_size]
        xs = [item["x"] for item in chunk]
        ys = [item["y"] for item in chunk]
        bins.append(
            {
                "x_min": xs[0],
                "x_max": xs[-1],
                "x_mean": _mean(xs),
                "y_mean": _mean(ys),
                "count": len(chunk),
            }
        )
    return bins


def _equal_count_bins_from_values(values: list[float], max_bins: int) -> list[dict[str, Any]]:
    sorted_values = sorted([value for value in values if math.isfinite(value)])
    if not sorted_values:
        return []
    target_bins = max(1, min(max_bins, len(sorted_values)))
    bin_size = max(1, math.ceil(len(sorted_values) / target_bins))
    bins: list[dict[str, Any]] = []
    for start in range(0, len(sorted_values), bin_size):
        chunk = sorted_values[start : start + bin_size]
        bins.append(
            {
                "min": chunk[0],
                "max": chunk[-1],
                "mean": _mean(chunk),
                "count": len(chunk),
            }
        )
    return bins


def _compare_control_pairs(
    records: list[dict[str, Any]],
    outcome_field: str,
    compare_field: str,
) -> list[dict[str, float]]:
    pairs: list[dict[str, float]] = []
    for record in records:
        outcome = maybe_number(previous_runs_field_value(record, outcome_field))
        compare = maybe_number(previous_runs_field_value(record, compare_field))
        if outcome is None or compare is None:
            continue
        pairs.append({"x": compare, "y": outcome})
    return pairs


def _compare_control_secondary_metric_fields(
    records: list[dict[str, Any]],
    outcome_field: str,
    compare_field: str,
    field_options: list[str],
) -> list[str]:
    if not records:
        return []
    candidate_order = list(COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED) + list(field_options)
    preferred_set = set(COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED)
    seen: set[str] = set()
    selected: list[str] = []
    for candidate in candidate_order:
        field_name = str(candidate or "").strip()
        if not field_name or field_name in seen:
            continue
        seen.add(field_name)
        if field_name in {outcome_field, compare_field}:
            continue
        if field_name in COMPARE_CONTROL_FIELD_SKIP:
            continue
        if field_name not in preferred_set and not COMPARE_CONTROL_SECONDARY_FIELD_PATTERN.search(field_name):
            continue
        numeric_count = 0
        numeric_min: float | None = None
        numeric_max: float | None = None
        for record in records:
            numeric_value = maybe_number(previous_runs_field_value(record, field_name))
            if numeric_value is None:
                continue
            numeric_count += 1
            if numeric_min is None or numeric_value < numeric_min:
                numeric_min = numeric_value
            if numeric_max is None or numeric_value > numeric_max:
                numeric_max = numeric_value
        if numeric_count < 2:
            continue
        if (
            numeric_min is not None
            and numeric_max is not None
            and abs(numeric_max - numeric_min) <= 1e-12
        ):
            continue
        selected.append(field_name)
        if len(selected) >= COMPARE_CONTROL_SECONDARY_MAX_FIELDS:
            break
    return selected


def compare_control_weak_coverage_warnings(analysis: dict[str, Any]) -> list[str]:
    if not isinstance(analysis, dict):
        return []
    warnings: list[str] = []
    candidate_rows = int(analysis.get("candidate_rows") or 0)
    used_rows = int(analysis.get("used_rows") or 0)
    if used_rows <= 0:
        warnings.append("No comparable rows remained after hold-constant controls.")
        return warnings

    if candidate_rows > 0:
        row_coverage = used_rows / candidate_rows
        if row_coverage < COMPARE_CONTROL_WARNING_ROW_COVERAGE_MIN:
            warnings.append(
                "Row coverage is low "
                f"({used_rows} / {candidate_rows}, {(row_coverage * 100):.1f}%)."
            )

    if used_rows < COMPARE_CONTROL_WARNING_MIN_ROWS:
        warnings.append(f"Only {used_rows} comparable rows are available.")

    total_strata = int(analysis.get("total_strata") or 0)
    used_strata = int(analysis.get("used_strata") or 0)
    if total_strata > 0:
        strata_coverage = used_strata / total_strata
        if strata_coverage < COMPARE_CONTROL_WARNING_STRATA_COVERAGE_MIN:
            warnings.append(
                "Comparable strata are limited "
                f"({used_strata} / {total_strata}, {(strata_coverage * 100):.1f}%)."
            )

    if total_strata > 0 and used_strata < min(total_strata, COMPARE_CONTROL_WARNING_MIN_STRATA):
        warnings.append(f"Only {used_strata} strata contribute to controlled estimates.")
    return warnings


def analyze_compare_control_categorical_raw(
    records: list[dict[str, Any]],
    outcome_field: str,
    compare_field: str,
    field_options: list[str],
) -> dict[str, Any]:
    groups_by_key: dict[str, dict[str, Any]] = {}
    secondary_fields = _compare_control_secondary_metric_fields(
        records,
        outcome_field,
        compare_field,
        field_options,
    )
    used_rows = 0
    for record in records:
        outcome = maybe_number(previous_runs_field_value(record, outcome_field))
        if outcome is None:
            continue
        raw_compare_value = previous_runs_field_value(record, compare_field)
        group_key = analysis_comparable_value(raw_compare_value)
        if group_key == "__EMPTY__":
            continue
        group = groups_by_key.get(group_key)
        if group is None:
            group = {
                "key": group_key,
                "label": analysis_display_value(raw_compare_value, group_key),
                "count": 0,
                "outcome_sum": 0.0,
                "secondary_sum": {},
                "secondary_count": {},
            }
            groups_by_key[group_key] = group
        group["count"] += 1
        group["outcome_sum"] += outcome
        for field_name in secondary_fields:
            secondary_value = maybe_number(previous_runs_field_value(record, field_name))
            if secondary_value is None:
                continue
            group["secondary_sum"][field_name] = float(group["secondary_sum"].get(field_name) or 0.0) + secondary_value
            group["secondary_count"][field_name] = int(group["secondary_count"].get(field_name) or 0) + 1
        used_rows += 1

    groups: list[dict[str, Any]] = []
    for group in groups_by_key.values():
        secondary_means: dict[str, float] = {}
        for field_name in secondary_fields:
            count_value = int(group["secondary_count"].get(field_name) or 0)
            if count_value <= 0:
                continue
            secondary_means[field_name] = float(group["secondary_sum"].get(field_name) or 0.0) / count_value
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "count": group["count"],
                "outcome_mean": (
                    float(group["outcome_sum"]) / int(group["count"])
                    if int(group["count"]) > 0
                    else None
                ),
                "secondary_means": secondary_means,
            }
        )

    groups.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("label") or "").lower()))
    return {
        "type": "categorical",
        "groups": groups,
        "used_rows": used_rows,
        "candidate_rows": len(records),
        "secondary_fields": secondary_fields,
    }


def analyze_compare_control_numeric_raw(
    records: list[dict[str, Any]],
    outcome_field: str,
    compare_field: str,
) -> dict[str, Any]:
    pairs = _compare_control_pairs(records, outcome_field, compare_field)
    regression = _linear_regression_from_pairs(pairs)
    xs = [pair["x"] for pair in pairs]
    ys = [pair["y"] for pair in pairs]
    spearman = _spearman_correlation(xs, ys)
    bins = _equal_count_bins_from_pairs(pairs, 5)
    return {
        "type": "numeric",
        "used_rows": len(pairs),
        "candidate_rows": len(records),
        "slope": regression["slope"],
        "intercept": regression["intercept"],
        "r_squared": regression["r_squared"],
        "spearman": spearman,
        "bins": bins,
    }


def analyze_compare_control_categorical_controlled(
    records: list[dict[str, Any]],
    outcome_field: str,
    compare_field: str,
    hold_fields: list[str],
    field_options: list[str],
) -> dict[str, Any]:
    hold = _unique_string_list(hold_fields)
    if not hold:
        raw = analyze_compare_control_categorical_raw(
            records,
            outcome_field,
            compare_field,
            field_options,
        )
        raw["used_strata"] = 0
        raw["total_strata"] = 0
        raw["hold_fields"] = hold
        return raw

    strata: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        outcome = maybe_number(previous_runs_field_value(record, outcome_field))
        if outcome is None:
            continue
        raw_compare = previous_runs_field_value(record, compare_field)
        group_key = analysis_comparable_value(raw_compare)
        if group_key == "__EMPTY__":
            continue
        stratum_key = "||".join(
            analysis_comparable_value(previous_runs_field_value(record, field_name))
            for field_name in hold
        )
        strata.setdefault(stratum_key, {})
        stratum_groups = strata[stratum_key]
        if group_key not in stratum_groups:
            stratum_groups[group_key] = {
                "key": group_key,
                "label": analysis_display_value(raw_compare, group_key),
                "count": 0,
                "outcome_sum": 0.0,
            }
        stratum_groups[group_key]["count"] += 1
        stratum_groups[group_key]["outcome_sum"] += outcome

    weighted_groups: dict[str, dict[str, Any]] = {}
    used_rows = 0
    used_strata = 0
    total_strata = len(strata)
    for stratum_groups in strata.values():
        groups = list(stratum_groups.values())
        if len(groups) < 2:
            continue
        stratum_weight = sum(int(group.get("count") or 0) for group in groups)
        if stratum_weight <= 0:
            continue
        used_strata += 1
        used_rows += stratum_weight
        for group in groups:
            mean_outcome = (
                float(group["outcome_sum"]) / int(group["count"])
                if int(group["count"]) > 0
                else None
            )
            if mean_outcome is None:
                continue
            bucket = weighted_groups.setdefault(
                group["key"],
                {
                    "key": group["key"],
                    "label": group["label"],
                    "weighted_sum": 0.0,
                    "weight": 0.0,
                    "count": 0,
                    "strata_count": 0,
                },
            )
            bucket["weighted_sum"] += mean_outcome * stratum_weight
            bucket["weight"] += stratum_weight
            bucket["count"] += int(group.get("count") or 0)
            bucket["strata_count"] += 1

    groups: list[dict[str, Any]] = []
    for group in weighted_groups.values():
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "count": group["count"],
                "outcome_mean": (
                    float(group["weighted_sum"]) / float(group["weight"])
                    if float(group["weight"]) > 0
                    else None
                ),
            }
        )
    groups.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("label") or "").lower()))
    return {
        "type": "categorical",
        "groups": groups,
        "used_rows": used_rows,
        "candidate_rows": len(records),
        "used_strata": used_strata,
        "total_strata": total_strata,
        "hold_fields": hold,
    }


def analyze_compare_control_numeric_controlled(
    records: list[dict[str, Any]],
    outcome_field: str,
    compare_field: str,
    hold_fields: list[str],
) -> dict[str, Any]:
    hold = _unique_string_list(hold_fields)
    if not hold:
        raw = analyze_compare_control_numeric_raw(records, outcome_field, compare_field)
        raw["used_strata"] = 0
        raw["total_strata"] = 0
        raw["hold_fields"] = hold
        return raw

    strata: dict[str, list[dict[str, float]]] = {}
    for record in records:
        outcome = maybe_number(previous_runs_field_value(record, outcome_field))
        compare = maybe_number(previous_runs_field_value(record, compare_field))
        if outcome is None or compare is None:
            continue
        stratum_key = "||".join(
            analysis_comparable_value(previous_runs_field_value(record, field_name))
            for field_name in hold
        )
        strata.setdefault(stratum_key, []).append({"x": compare, "y": outcome})

    used_strata = 0
    centered_pairs: list[dict[str, float]] = []
    total_strata = len(strata)
    for rows in strata.values():
        if len(rows) < 2:
            continue
        mean_x = _mean([row["x"] for row in rows])
        mean_y = _mean([row["y"] for row in rows])
        if mean_x is None or mean_y is None:
            continue
        distinct_x = {row["x"] for row in rows}
        if len(distinct_x) < 2:
            continue
        used_strata += 1
        for row in rows:
            centered_pairs.append({"x": row["x"] - mean_x, "y": row["y"] - mean_y})

    regression = _linear_regression_from_pairs(centered_pairs)
    xs = [pair["x"] for pair in centered_pairs]
    ys = [pair["y"] for pair in centered_pairs]
    spearman = _spearman_correlation(xs, ys)
    return {
        "type": "numeric",
        "used_rows": len(centered_pairs),
        "candidate_rows": len(records),
        "used_strata": used_strata,
        "total_strata": total_strata,
        "hold_fields": hold,
        "slope": regression["slope"],
        "intercept": regression["intercept"],
        "r_squared": regression["r_squared"],
        "spearman": spearman,
        "bins": [],
    }


def _fmt_maybe(value: Any, digits: int) -> str:
    numeric = maybe_number(value)
    if numeric is None:
        return "-"
    return f"{numeric:.{digits}f}"


def analyze_compare_control_discovery(
    records: list[dict[str, Any]],
    outcome_field: str,
    catalog: dict[str, Any],
    field_options: list[str],
    discovery_preferences: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    total_rows = len(records)
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    if not isinstance(by_field, dict):
        by_field = {}
    preferences = _normalize_discovery_preferences(discovery_preferences)
    excluded_fields = {field.lower() for field in preferences["exclude_fields"]}
    preferred_fields = {field.lower() for field in preferences["prefer_fields"]}
    demote_patterns = [
        pattern.lower().strip()
        for pattern in preferences["demote_patterns"]
        if str(pattern or "").strip()
    ]
    max_cards = int(preferences["max_cards"])
    scored: list[dict[str, Any]] = []
    for field_name, field_info in by_field.items():
        if field_name == outcome_field:
            continue
        if not isinstance(field_info, dict):
            continue
        field_name_lower = str(field_name).lower()
        if field_name_lower in excluded_fields:
            continue
        strength: float | None = None
        summary = ""
        coverage_ratio = 0.0
        if bool(field_info.get("numeric")):
            analysis = analyze_compare_control_numeric_raw(records, outcome_field, field_name)
            coverage_ratio = analysis["used_rows"] / total_rows if total_rows > 0 else 0.0
            corr_strength = abs(float(analysis["spearman"])) if analysis["spearman"] is not None else 0.0
            slope_strength = abs(float(analysis["slope"])) if analysis["slope"] is not None else 0.0
            strength = corr_strength + min(1.0, slope_strength)
            summary = (
                f"Spearman {_fmt_maybe(analysis['spearman'], 3)}, "
                f"R^2 {_fmt_maybe(analysis['r_squared'], 3)}"
            )
        else:
            analysis = analyze_compare_control_categorical_raw(
                records,
                outcome_field,
                field_name,
                field_options,
            )
            coverage_ratio = analysis["used_rows"] / total_rows if total_rows > 0 else 0.0
            groups = analysis.get("groups") or []
            if len(groups) < 2:
                continue
            means = [
                maybe_number(group.get("outcome_mean"))
                for group in groups
                if isinstance(group, dict)
            ]
            means = [value for value in means if value is not None]
            if not means:
                continue
            strength = abs(max(means) - min(means)) * 100.0
            top_group = groups[0] if groups else None
            summary = (
                f"Top group: {top_group.get('label')} ({_fmt_maybe(top_group.get('outcome_mean'), 3)})"
                if isinstance(top_group, dict)
                else ""
            )

        final_score = 0.0
        if strength is not None and math.isfinite(strength):
            final_score = strength * max(0.2, coverage_ratio)
        score_modifiers: list[str] = []
        if field_name_lower in preferred_fields:
            final_score *= COMPARE_CONTROL_DISCOVERY_PREFER_FIELD_BOOST
            score_modifiers.append("preferred")
        if any(pattern in field_name_lower for pattern in demote_patterns):
            final_score *= COMPARE_CONTROL_DISCOVERY_DEMOTE_FACTOR
            score_modifiers.append("demoted")
        if score_modifiers:
            summary = f"{summary} | {'/'.join(score_modifiers)}".strip()
        scored.append(
            {
                "field": field_name,
                "field_label": field_info.get("label") or field_name,
                "numeric": bool(field_info.get("numeric")),
                "coverage_ratio": coverage_ratio,
                "score": final_score,
                "summary": summary,
            }
        )

    scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return scored[:max_cards]


def compare_control_split_segments(
    records: list[dict[str, Any]],
    split_field: str,
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    if not isinstance(by_field, dict):
        return []
    split_info = by_field.get(split_field)
    if not isinstance(split_info, dict):
        return []

    if bool(split_info.get("numeric")):
        values = [
            maybe_number(previous_runs_field_value(record, split_field))
            for record in records
        ]
        numeric_values = [value for value in values if value is not None]
        bins = _equal_count_bins_from_values(numeric_values, 4)
        segments: list[dict[str, Any]] = []
        for idx, bin_info in enumerate(bins):
            min_value = float(bin_info["min"])
            max_value = float(bin_info["max"])
            bucket_records = [
                record
                for record in records
                if (
                    (value := maybe_number(previous_runs_field_value(record, split_field)))
                    is not None
                    and min_value <= value <= max_value
                )
            ]
            if not bucket_records:
                continue
            segments.append(
                {
                    "key": f"bin_{idx}",
                    "label": f"{_fmt_maybe(min_value, 3)} to {_fmt_maybe(max_value, 3)}",
                    "records": bucket_records,
                }
            )
        missing = [
            record
            for record in records
            if maybe_number(previous_runs_field_value(record, split_field)) is None
        ]
        if missing:
            segments.append(
                {
                    "key": "missing",
                    "label": "(missing)",
                    "records": missing,
                }
            )
        return [segment for segment in segments if segment["records"]][:8]

    by_group: dict[str, dict[str, Any]] = {}
    for record in records:
        raw_value = previous_runs_field_value(record, split_field)
        key = analysis_comparable_value(raw_value)
        label = analysis_display_value(raw_value, key)
        bucket = by_group.setdefault(key, {"key": key, "label": label, "records": []})
        bucket["records"].append(record)

    segments = sorted(
        by_group.values(),
        key=lambda segment: (
            -len(segment.get("records") or []),
            str(segment.get("label") or "").lower(),
        ),
    )
    return segments[:8]


def _compare_control_segment_summary(
    records: list[dict[str, Any]],
    state: dict[str, Any],
    catalog: dict[str, Any],
    field_options: list[str],
) -> str:
    if not records or not state.get("compare_field"):
        return "-"
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    compare_info = by_field.get(state["compare_field"]) if isinstance(by_field, dict) else None
    if not isinstance(compare_info, dict):
        return "-"

    if bool(compare_info.get("numeric")):
        if state.get("view_mode") == "controlled":
            numeric = analyze_compare_control_numeric_controlled(
                records,
                state["outcome_field"],
                state["compare_field"],
                state.get("hold_constant_fields") or [],
            )
        else:
            numeric = analyze_compare_control_numeric_raw(
                records,
                state["outcome_field"],
                state["compare_field"],
            )
        return f"slope {_fmt_maybe(numeric.get('slope'), 4)}, Spearman {_fmt_maybe(numeric.get('spearman'), 3)}"

    if state.get("view_mode") == "controlled":
        categorical = analyze_compare_control_categorical_controlled(
            records,
            state["outcome_field"],
            state["compare_field"],
            state.get("hold_constant_fields") or [],
            field_options,
        )
    else:
        categorical = analyze_compare_control_categorical_raw(
            records,
            state["outcome_field"],
            state["compare_field"],
            field_options,
        )

    groups = categorical.get("groups") or []
    if not groups:
        return "-"
    top = groups[0]
    return f"{top.get('label')}: {_fmt_maybe(top.get('outcome_mean'), 3)}"


def _analysis_for_field(
    records: list[dict[str, Any]],
    target_field: str,
    candidate_field: str,
    field_options: list[str],
) -> tuple[float, float]:
    if candidate_field == target_field:
        return (0.0, 0.0)

    candidate_values = [previous_runs_field_value(record, candidate_field) for record in records]
    target_values = [previous_runs_field_value(record, target_field) for record in records]

    numeric_candidate = all(
        maybe_number(value) is not None
        for value in candidate_values
        if not is_empty_rule_value(value)
    )
    numeric_target = all(
        maybe_number(value) is not None
        for value in target_values
        if not is_empty_rule_value(value)
    )

    if numeric_candidate and numeric_target:
        xs: list[float] = []
        ys: list[float] = []
        for candidate, target in zip(candidate_values, target_values):
            left = maybe_number(candidate)
            right = maybe_number(target)
            if left is None or right is None:
                continue
            xs.append(left)
            ys.append(right)
        if len(xs) < 2:
            return (0.0, 0.0)
        corr = _spearman_correlation(xs, ys)
        strength = abs(corr) if corr is not None else 0.0
        coverage = len(xs) / len(records) if records else 0.0
        return (strength, coverage)

    categorical = analyze_compare_control_categorical_raw(
        records,
        target_field,
        candidate_field,
        field_options,
    )
    means = [
        maybe_number(group.get("outcome_mean"))
        for group in categorical.get("groups") or []
        if isinstance(group, dict)
    ]
    means = [value for value in means if value is not None]
    if len(means) < 2:
        return (0.0, 0.0)
    strength = abs(max(means) - min(means))
    coverage = categorical["used_rows"] / len(records) if records else 0.0
    return (strength, coverage)


def analyze(
    records: list[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    query_payload = query if isinstance(query, dict) else {}
    filtered_records, filter_context = apply_filters(records, query_payload.get("filters"))
    field_options = collect_benchmark_field_paths(filtered_records)
    catalog = build_compare_control_field_catalog(filtered_records, field_options)
    state = _normalize_compare_control_state_for_catalog(query_payload, catalog)

    if not filtered_records:
        return {
            "view_mode": state["view_mode"],
            "outcome_field": state["outcome_field"],
            "compare_field": state["compare_field"],
            "split_field": state["split_field"],
            "hold_constant_fields": state["hold_constant_fields"],
            "candidate_rows": 0,
            "analysis": {
                "type": "empty",
                "message": "No visible benchmark rows after filters.",
            },
            "filters": filter_context,
            "catalog": catalog,
        }

    if not catalog.get("numeric_fields"):
        raise CompareControlError(
            "no_numeric_outcome",
            "No numeric outcome fields are available for compare/control analysis.",
        )

    compare_field = state.get("compare_field") or ""
    compare_info = catalog["by_field"].get(compare_field) if compare_field else None

    if not compare_field or state["view_mode"] == "discover" or not isinstance(compare_info, dict):
        discovery = analyze_compare_control_discovery(
            filtered_records,
            state["outcome_field"],
            catalog,
            field_options,
            state.get("discovery_preferences"),
        )
        return {
            "view_mode": "discover",
            "outcome_field": state["outcome_field"],
            "compare_field": "",
            "split_field": "",
            "hold_constant_fields": [],
            "discovery_preferences": state.get("discovery_preferences"),
            "candidate_rows": len(filtered_records),
            "analysis": {
                "type": "discover",
                "items": discovery,
            },
            "filters": filter_context,
            "catalog": catalog,
        }

    if bool(compare_info.get("numeric")):
        if state["view_mode"] == "controlled":
            analysis_payload = analyze_compare_control_numeric_controlled(
                filtered_records,
                state["outcome_field"],
                compare_field,
                state["hold_constant_fields"],
            )
        else:
            analysis_payload = analyze_compare_control_numeric_raw(
                filtered_records,
                state["outcome_field"],
                compare_field,
            )
    else:
        if state["view_mode"] == "controlled":
            analysis_payload = analyze_compare_control_categorical_controlled(
                filtered_records,
                state["outcome_field"],
                compare_field,
                state["hold_constant_fields"],
                field_options,
            )
        else:
            analysis_payload = analyze_compare_control_categorical_raw(
                filtered_records,
                state["outcome_field"],
                compare_field,
                field_options,
            )

    warnings: list[str] = []
    if state["view_mode"] == "controlled":
        warnings = compare_control_weak_coverage_warnings(analysis_payload)

    split_segments: list[dict[str, Any]] = []
    split_field = state.get("split_field") or ""
    if split_field:
        segments = compare_control_split_segments(filtered_records, split_field, catalog)
        split_segments = [
            {
                "key": segment.get("key"),
                "label": segment.get("label"),
                "row_count": len(segment.get("records") or []),
                "summary": _compare_control_segment_summary(
                    segment.get("records") or [],
                    state,
                    catalog,
                    field_options,
                ),
            }
            for segment in segments
        ]

    return {
        "view_mode": state["view_mode"],
        "outcome_field": state["outcome_field"],
        "compare_field": compare_field,
        "split_field": split_field,
        "hold_constant_fields": state["hold_constant_fields"],
        "selected_groups": state["selected_groups"],
        "candidate_rows": len(filtered_records),
        "analysis": analysis_payload,
        "warnings": warnings,
        "split_segments": split_segments,
        "filters": filter_context,
        "catalog": catalog,
    }


def suggest_hold_constants(
    records: list[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    query_payload = query if isinstance(query, dict) else {}
    filtered_records, filter_context = apply_filters(records, query_payload.get("filters"))
    field_options = collect_benchmark_field_paths(filtered_records)
    catalog = build_compare_control_field_catalog(filtered_records, field_options)
    state = _normalize_compare_control_state_for_catalog(query_payload, catalog)

    compare_field = state.get("compare_field") or ""
    if not compare_field:
        raise CompareControlError(
            "missing_compare_field",
            "compare_field is required for hold-constant suggestions.",
        )

    suggestions: list[dict[str, Any]] = []
    for field_info in catalog.get("fields") or []:
        if not isinstance(field_info, dict):
            continue
        field_name = str(field_info.get("field") or "").strip()
        if not field_name or field_name in {
            state["outcome_field"],
            compare_field,
            state.get("split_field") or "",
        }:
            continue

        strength_outcome, coverage_outcome = _analysis_for_field(
            filtered_records,
            state["outcome_field"],
            field_name,
            field_options,
        )
        strength_compare, coverage_compare = _analysis_for_field(
            filtered_records,
            compare_field,
            field_name,
            field_options,
        )
        coverage = max(coverage_outcome, coverage_compare)
        score = (strength_outcome + strength_compare) * max(0.2, coverage)

        suggestions.append(
            {
                "field": field_name,
                "field_label": field_info.get("label") or field_name,
                "numeric": bool(field_info.get("numeric")),
                "coverage_ratio": coverage,
                "distinct_count": int(field_info.get("distinct_count") or 0),
                "score": score,
                "outcome_strength": strength_outcome,
                "compare_strength": strength_compare,
            }
        )

    suggestions.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    max_suggestions = int(query_payload.get("max_suggestions") or 8)
    max_suggestions = max(1, min(20, max_suggestions))

    return {
        "outcome_field": state["outcome_field"],
        "compare_field": compare_field,
        "candidate_rows": len(filtered_records),
        "suggestions": suggestions[:max_suggestions],
        "filters": filter_context,
    }


def suggest_splits(
    records: list[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    query_payload = query if isinstance(query, dict) else {}
    filtered_records, filter_context = apply_filters(records, query_payload.get("filters"))
    field_options = collect_benchmark_field_paths(filtered_records)
    catalog = build_compare_control_field_catalog(filtered_records, field_options)
    state = _normalize_compare_control_state_for_catalog(query_payload, catalog)

    suggestions: list[dict[str, Any]] = []
    for field_info in catalog.get("fields") or []:
        if not isinstance(field_info, dict):
            continue
        field_name = str(field_info.get("field") or "").strip()
        if not field_name:
            continue
        if field_name in {
            state["outcome_field"],
            state.get("compare_field") or "",
        }:
            continue
        strength, coverage = _analysis_for_field(
            filtered_records,
            state["outcome_field"],
            field_name,
            field_options,
        )
        score = strength * max(0.2, coverage)
        suggestions.append(
            {
                "field": field_name,
                "field_label": field_info.get("label") or field_name,
                "numeric": bool(field_info.get("numeric")),
                "distinct_count": int(field_info.get("distinct_count") or 0),
                "coverage_ratio": coverage,
                "score": score,
            }
        )

    suggestions.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    max_suggestions = int(query_payload.get("max_suggestions") or 8)
    max_suggestions = max(1, min(20, max_suggestions))

    return {
        "outcome_field": state["outcome_field"],
        "compare_field": state.get("compare_field") or "",
        "candidate_rows": len(filtered_records),
        "suggestions": suggestions[:max_suggestions],
        "filters": filter_context,
    }


def generate_insights(
    records: list[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    query_payload = query if isinstance(query, dict) else {}
    filtered_records, filter_context = apply_filters(records, query_payload.get("filters"))
    field_options = collect_benchmark_field_paths(filtered_records)
    catalog = build_compare_control_field_catalog(filtered_records, field_options)
    state = _normalize_compare_control_state_for_catalog(query_payload, catalog)

    outcome_field = state["outcome_field"]
    compare_field = _insights_pick_compare_field(state, catalog)
    hold_fields = _insights_pick_hold_fields(
        state,
        catalog,
        outcome_field=outcome_field,
        compare_field=compare_field,
    )

    profile = {
        "candidate_rows": len(filtered_records),
        "field_count": len(catalog.get("fields") or []),
        "numeric_field_count": len(catalog.get("numeric_fields") or []),
        "categorical_field_count": len(catalog.get("categorical_fields") or []),
        "top_source_labels": _insights_top_categories(catalog, "source_label"),
        "top_importers": _insights_top_categories(catalog, "importer_name"),
        "top_ai_models": _insights_top_categories(catalog, "ai_model"),
    }

    if not filtered_records:
        return {
            "outcome_field": outcome_field,
            "compare_field": compare_field,
            "hold_constant_fields": hold_fields,
            "candidate_rows": 0,
            "profile": profile,
            "highlights": [
                {
                    "severity": "warning",
                    "title": "No rows after filters",
                    "summary": "Current quick filters + column filters removed all benchmark rows.",
                }
            ],
            "drivers": {
                "actionable_top": [],
                "ignored_high_cardinality": [],
            },
            "comparisons": {
                "raw": None,
                "controlled": None,
                "controlled_warnings": [],
            },
            "process_factors": [],
            "model_efficiency": {
                "groups": [],
            },
            "suggested_queries": [],
            "filters": filter_context,
            "catalog": catalog,
        }

    discovery_items = analyze_compare_control_discovery(
        filtered_records,
        outcome_field,
        catalog,
        field_options,
        state.get("discovery_preferences"),
    )
    actionable_drivers = [
        item for item in discovery_items if not _insights_is_noise_field(str(item.get("field") or ""))
    ]
    noisy_drivers = [
        item for item in discovery_items if _insights_is_noise_field(str(item.get("field") or ""))
    ]

    raw_analysis: dict[str, Any] | None = None
    controlled_analysis: dict[str, Any] | None = None
    controlled_warnings: list[str] = []
    compare_delta: dict[str, Any] | None = None

    compare_info = catalog.get("by_field", {}).get(compare_field) if compare_field else None
    if isinstance(compare_info, dict):
        if bool(compare_info.get("numeric")):
            raw_analysis = analyze_compare_control_numeric_raw(
                filtered_records,
                outcome_field,
                compare_field,
            )
            controlled_analysis = analyze_compare_control_numeric_controlled(
                filtered_records,
                outcome_field,
                compare_field,
                hold_fields,
            )
        else:
            raw_analysis = analyze_compare_control_categorical_raw(
                filtered_records,
                outcome_field,
                compare_field,
                field_options,
            )
            controlled_analysis = analyze_compare_control_categorical_controlled(
                filtered_records,
                outcome_field,
                compare_field,
                hold_fields,
                field_options,
            )
            compare_delta = _insights_categorical_delta(raw_analysis)

        if controlled_analysis is not None and hold_fields:
            controlled_warnings = compare_control_weak_coverage_warnings(controlled_analysis)

    process_factors: list[dict[str, Any]] = []
    by_field = catalog.get("by_field") if isinstance(catalog, dict) else {}
    if isinstance(by_field, dict):
        for field_name in INSIGHTS_PROCESS_FIELDS:
            field_info = by_field.get(field_name)
            if not isinstance(field_info, dict):
                continue
            if bool(field_info.get("numeric")):
                continue
            distinct_count = int(field_info.get("distinct_count") or 0)
            if distinct_count < 2 or distinct_count > 12:
                continue
            analysis = analyze_compare_control_categorical_raw(
                filtered_records,
                outcome_field,
                field_name,
                field_options,
            )
            delta = _insights_categorical_delta(analysis)
            if delta is None:
                continue
            process_factors.append(
                {
                    "field": field_name,
                    "field_label": field_info.get("label") or field_name,
                    "distinct_count": distinct_count,
                    "groups": (analysis.get("groups") or [])[:6],
                    "delta": delta,
                }
            )
    process_factors.sort(
        key=lambda item: abs(float(item.get("delta", {}).get("outcome_delta") or 0.0)),
        reverse=True,
    )

    model_efficiency = {"groups": []}
    if isinstance(by_field, dict) and isinstance(by_field.get("ai_model"), dict):
        ai_analysis = analyze_compare_control_categorical_raw(
            filtered_records,
            outcome_field,
            "ai_model",
            field_options,
        )
        model_groups: list[dict[str, Any]] = []
        for group in ai_analysis.get("groups") or []:
            if not isinstance(group, dict):
                continue
            mean_outcome = maybe_number(group.get("outcome_mean"))
            secondary = group.get("secondary_means") if isinstance(group.get("secondary_means"), dict) else {}
            token_use = maybe_number(secondary.get("all_token_use"))
            quality_per_million = None
            if token_use is not None and token_use > 0 and mean_outcome is not None:
                quality_per_million = mean_outcome / (token_use / 1_000_000.0)
            model_groups.append(
                {
                    "key": group.get("key"),
                    "label": group.get("label"),
                    "count": int(group.get("count") or 0),
                    "outcome_mean": mean_outcome,
                    "all_token_use_mean": token_use,
                    "quality_per_million_tokens": quality_per_million,
                }
            )
        model_efficiency = {"groups": model_groups}

    highlights: list[dict[str, Any]] = []
    quick_context = filter_context.get("quick_filters") if isinstance(filter_context, dict) else {}
    if isinstance(quick_context, dict):
        removed_unofficial = int(quick_context.get("removed_unofficial") or 0)
        if removed_unofficial > 0:
            highlights.append(
                {
                    "severity": "info",
                    "title": "Official benchmark filter is active",
                    "summary": (
                        f"{removed_unofficial} rows were excluded by official-full-golden filtering."
                    ),
                }
            )
    if len(filtered_records) < 20:
        highlights.append(
            {
                "severity": "warning",
                "title": "Small sample size",
                "summary": (
                    f"Only {len(filtered_records)} rows are available after filters; "
                    "treat deltas as directional."
                ),
            }
        )
    if compare_delta is not None:
        best_group = compare_delta.get("best_group", {})
        worst_group = compare_delta.get("worst_group", {})
        highlights.append(
            {
                "severity": "info",
                "title": f"Raw gap on {compare_field}",
                "summary": (
                    f"{best_group.get('label')} leads {worst_group.get('label')} by "
                    f"{_fmt_maybe(compare_delta.get('outcome_delta'), 3)} on {outcome_field}."
                ),
            }
        )
    if controlled_warnings:
        highlights.append(
            {
                "severity": "warning",
                "title": "Controlled coverage warning",
                "summary": controlled_warnings[0],
            }
        )
    if actionable_drivers:
        top_driver = actionable_drivers[0]
        highlights.append(
            {
                "severity": "info",
                "title": "Top actionable driver",
                "summary": (
                    f"{top_driver.get('field')} (score {_fmt_maybe(top_driver.get('score'), 3)}). "
                    f"{top_driver.get('summary')}"
                ),
            }
        )
    if noisy_drivers:
        highlights.append(
            {
                "severity": "info",
                "title": "High-cardinality discovery fields detected",
                "summary": (
                    "Some top discovery fields are path/hash identifiers; use actionable "
                    "driver list for decision-oriented comparisons."
                ),
            }
        )
    if process_factors:
        top_factor = process_factors[0]
        delta = top_factor.get("delta") if isinstance(top_factor.get("delta"), dict) else {}
        highlights.append(
            {
                "severity": "info",
                "title": "Strongest process-factor spread",
                "summary": (
                    f"{top_factor.get('field')} shows "
                    f"{_fmt_maybe(delta.get('outcome_delta'), 3)} max-min outcome spread."
                ),
            }
        )

    suggested_queries: list[dict[str, Any]] = [
        {
            "label": "Discover candidate drivers",
            "action": "discover",
            "payload": {
                "outcome_field": outcome_field,
                "filters": query_payload.get("filters") or {},
            },
        }
    ]
    if compare_field:
        suggested_queries.append(
            {
                "label": f"Raw compare by {compare_field}",
                "action": "analyze",
                "payload": {
                    "view_mode": "raw",
                    "outcome_field": outcome_field,
                    "compare_field": compare_field,
                    "filters": query_payload.get("filters") or {},
                },
            }
        )
        if hold_fields:
            suggested_queries.append(
                {
                    "label": f"Controlled compare by {compare_field}",
                    "action": "analyze",
                    "payload": {
                        "view_mode": "controlled",
                        "outcome_field": outcome_field,
                        "compare_field": compare_field,
                        "hold_constant_fields": hold_fields,
                        "filters": query_payload.get("filters") or {},
                    },
                }
            )
        if raw_analysis and str(raw_analysis.get("type") or "") == "categorical":
            top_groups = [
                str(group.get("key") or "").strip()
                for group in (raw_analysis.get("groups") or [])[:2]
                if isinstance(group, dict) and str(group.get("key") or "").strip()
            ]
            if top_groups:
                suggested_queries.append(
                    {
                        "label": f"Filter to top {compare_field} groups",
                        "action": "subset_filter_patch",
                        "payload": {
                            "compare_field": compare_field,
                            "selected_groups": top_groups,
                        },
                    }
                )

    return {
        "outcome_field": outcome_field,
        "compare_field": compare_field,
        "hold_constant_fields": hold_fields,
        "candidate_rows": len(filtered_records),
        "profile": profile,
        "highlights": highlights,
        "drivers": {
            "actionable_top": actionable_drivers[:10],
            "ignored_high_cardinality": noisy_drivers[:6],
        },
        "comparisons": {
            "raw": raw_analysis,
            "controlled": controlled_analysis,
            "controlled_warnings": controlled_warnings,
        },
        "process_factors": process_factors[:6],
        "model_efficiency": model_efficiency,
        "suggested_queries": suggested_queries,
        "filters": filter_context,
        "catalog": catalog,
    }


def build_subset_filter_patch(
    compare_field: str,
    selected_groups: list[str],
) -> dict[str, Any]:
    field_name = str(compare_field or "").strip()
    if not field_name:
        raise CompareControlError(
            "missing_compare_field",
            "compare_field is required for subset_filter_patch.",
        )
    groups = [
        group
        for group in _unique_string_list(selected_groups)
        if group and group != "__EMPTY__"
    ]
    if not groups:
        raise CompareControlError(
            "missing_selected_groups",
            "Select one or more groups before requesting a subset filter patch.",
        )
    return {
        "compare_field": field_name,
        "column_filter_mode": "or",
        "clauses": [{"operator": "eq", "value": group} for group in groups],
    }
