"""Render a static HTML dashboard from :class:`DashboardData`.

Writes four files into ``out_dir``:

* ``index.html``
* ``assets/dashboard_data.json``
* ``assets/dashboard_ui_state.json``
* ``assets/dashboard.js``
* ``assets/style.css``

Dashboard trend charts use Highcharts Stock from CDN when available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html import escape
import json
import math
from pathlib import Path
import re
from typing import Any

from cookimport.config.run_settings_contracts import summarize_run_config_payload

from ..dashboard_schema import BenchmarkRecord, DashboardData

_ALL_METHOD_BENCHMARK_SEGMENT = "all-method-benchmark"
_SINGLE_PROFILE_BENCHMARK_SEGMENT = "single-profile-benchmark"
_ALL_METHOD_CONFIG_PREFIX = "config_"
_ALL_METHOD_REPORT_JSON = "all_method_benchmark_report.json"
_ALL_METHOD_OUTPUT_SUBDIR = _ALL_METHOD_BENCHMARK_SEGMENT
_ALL_METHOD_RUN_PAGE_PREFIX = "all-method-benchmark-run__"
_PREVIOUS_RUNS_SECTION_HREF = "../index.html#previous-runs-section"
_TS_PATTERN = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T_](\d{2})[.:](\d{2})[.:](\d{2})$"
)


@dataclass
class _AllMethodGroup:
    group_dir: str
    run_root_dir: str
    run_dir_timestamp: str | None
    source_slug: str
    records: list[BenchmarkRecord]
    detail_page_name: str = ""


@dataclass
class _AllMethodConfigAggregate:
    config_key: str
    config_name: str
    extractor: str
    parser: str
    skiphf: str
    preprocess: str
    importer_name: str
    run_config_text: str
    run_config_hash: str | None
    books: int
    wins: int
    strict_precision_mean: float | None
    strict_recall_mean: float | None
    strict_f1_mean: float | None
    practical_f1_mean: float | None
    recipes_mean: float | None
    recipe_identified_pct_mean: float | None


@dataclass
class _AllMethodRun:
    run_key: str
    run_dir_timestamp: str | None
    groups: list[_AllMethodGroup] = field(default_factory=list)
    config_aggregates: list[_AllMethodConfigAggregate] = field(default_factory=list)
    detail_page_name: str = ""


@dataclass
class _AllMethodBookAggregate:
    source_label: str
    config_count: int
    mean_strict_precision: float | None
    mean_strict_recall: float | None
    mean_strict_f1: float | None
    mean_practical_f1: float | None
    mean_recipe_identified_pct: float | None


@dataclass
class _MetricRadarItem:
    label: str
    title: str
    values: list[float | None]
def _normalize_path_parts(path_value: str | None) -> tuple[str, list[str]]:
    if path_value is None:
        return "", []
    raw = str(path_value).strip().replace("\\", "/")
    if not raw:
        return "", []
    prefix = "/" if raw.startswith("/") else ""
    parts = [part for part in raw.split("/") if part and part != "."]
    return prefix, parts


def _all_method_group_key(
    record: BenchmarkRecord,
) -> tuple[str, str, str | None, str] | None:
    prefix, parts = _normalize_path_parts(record.artifact_dir)
    if len(parts) < 3:
        return None

    lower_parts = [part.lower() for part in parts]
    for idx, part in enumerate(lower_parts):
        if part == _ALL_METHOD_BENCHMARK_SEGMENT:
            if idx + 2 >= len(parts):
                continue
            source_slug = parts[idx + 1]
            config_dir = parts[idx + 2]
            if not config_dir.startswith(_ALL_METHOD_CONFIG_PREFIX):
                continue
        elif part == _SINGLE_PROFILE_BENCHMARK_SEGMENT:
            if idx + 1 >= len(parts):
                continue
            source_slug = parts[idx + 1]
        else:
            continue
        run_root_parts = parts[: idx + 1]
        group_parts = parts[: idx + 2]
        run_root_dir = (
            f"{prefix}{'/'.join(run_root_parts)}"
            if prefix
            else "/".join(run_root_parts)
        )
        group_dir = f"{prefix}{'/'.join(group_parts)}" if prefix else "/".join(group_parts)
        run_dir_timestamp = parts[idx - 1] if idx > 0 else None
        return group_dir, run_root_dir, run_dir_timestamp, source_slug

    return None


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    match = _TS_PATTERN.match(text)
    if match:
        try:
            return datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
                int(match.group(5)),
                int(match.group(6)),
            )
        except ValueError:
            return None

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _run_timestamp_sort_key(value: str | None) -> tuple[int, float, str]:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return (0, float("-inf"), value or "")
    return (1, parsed.timestamp(), value or "")


def _config_name(record: BenchmarkRecord) -> str:
    artifact_dir = str(record.artifact_dir or "")
    if not artifact_dir:
        return "<unknown>"
    _, parts = _normalize_path_parts(artifact_dir)
    lower_parts = [part.lower() for part in parts]
    if _SINGLE_PROFILE_BENCHMARK_SEGMENT in lower_parts:
        config_hash = str(record.run_config_hash or "").strip().lower()
        if config_hash:
            return f"profile_{config_hash[:12]}"
        return "single_profile"
    return Path(artifact_dir).name or artifact_dir


def _metric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt_float(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _fmt_int(value: int | None) -> str:
    if value is None:
        return "-"
    return str(value)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _render_metric_radar_cards(
    *,
    items: list[_MetricRadarItem],
    metric_specs: list[tuple[str, str, int, float | None]],
    aria_prefix: str,
) -> str:
    if not items or not metric_specs:
        return "<p class=\"empty-note\">No metrics available for radar charts.</p>"

    metric_count = len(metric_specs)
    center_x = 90.0
    center_y = 90.0
    radius = 62.0

    axis_points: list[tuple[float, float]] = []
    for axis_index in range(metric_count):
        angle = (-math.pi / 2.0) + ((2.0 * math.pi * axis_index) / metric_count)
        axis_points.append(
            (
                center_x + (radius * math.cos(angle)),
                center_y + (radius * math.sin(angle)),
            )
        )

    metric_max_values: list[float] = []
    for metric_index in range(metric_count):
        _, _, _, fixed_max = metric_specs[metric_index]
        if fixed_max is not None and fixed_max > 0:
            metric_max_values.append(float(fixed_max))
            continue
        present_values = []
        for item in items:
            if metric_index >= len(item.values):
                continue
            value = item.values[metric_index]
            if value is None:
                continue
            present_values.append(float(value))
        metric_max_values.append(max(present_values) if present_values else 0.0)

    rings_svg: list[str] = []
    for level in (0.25, 0.5, 0.75, 1.0):
        ring_points = " ".join(
            f"{center_x + ((axis_x - center_x) * level):.2f},{center_y + ((axis_y - center_y) * level):.2f}"
            for axis_x, axis_y in axis_points
        )
        rings_svg.append(
            f"<polygon class=\"metric-radar-ring\" points=\"{ring_points}\"></polygon>"
        )

    axes_svg = "".join(
        (
            f"<line class=\"metric-radar-axis\" x1=\"{center_x:.2f}\" y1=\"{center_y:.2f}\" "
            f"x2=\"{axis_x:.2f}\" y2=\"{axis_y:.2f}\"></line>"
        )
        for axis_x, axis_y in axis_points
    )

    axis_labels_svg: list[str] = []
    for metric_index, (axis_x, axis_y) in enumerate(axis_points):
        short_label, _, _, _ = metric_specs[metric_index]
        label_x = center_x + ((axis_x - center_x) * 1.2)
        label_y = center_y + ((axis_y - center_y) * 1.2)
        anchor = "middle"
        if label_x > center_x + 6:
            anchor = "start"
        elif label_x < center_x - 6:
            anchor = "end"
        axis_labels_svg.append(
            (
                f"<text class=\"metric-radar-axis-label\" x=\"{label_x:.2f}\" y=\"{label_y:.2f}\" "
                f"text-anchor=\"{anchor}\" dominant-baseline=\"middle\">{escape(short_label)}</text>"
            )
        )

    cards: list[str] = []
    for item in items:
        normalized_values: list[float] = []
        for metric_index, max_value in enumerate(metric_max_values):
            value = item.values[metric_index] if metric_index < len(item.values) else None
            if value is None or max_value <= 0:
                normalized_values.append(0.0)
                continue
            normalized_values.append(max(0.0, min(1.0, float(value) / max_value)))

        shape_points = " ".join(
            f"{center_x + ((axis_x - center_x) * level):.2f},{center_y + ((axis_y - center_y) * level):.2f}"
            for (axis_x, axis_y), level in zip(axis_points, normalized_values, strict=False)
        )

        point_svg: list[str] = []
        for metric_index, ((axis_x, axis_y), level) in enumerate(
            zip(axis_points, normalized_values, strict=False)
        ):
            value = item.values[metric_index] if metric_index < len(item.values) else None
            if value is None:
                continue
            point_x = center_x + ((axis_x - center_x) * level)
            point_y = center_y + ((axis_y - center_y) * level)
            point_svg.append(
                f"<circle class=\"metric-radar-point\" cx=\"{point_x:.2f}\" cy=\"{point_y:.2f}\" r=\"2.3\"></circle>"
            )

        value_rows: list[str] = []
        for metric_index, (_, value_label, digits, fixed_max) in enumerate(metric_specs):
            value = item.values[metric_index] if metric_index < len(item.values) else None
            if value is None:
                value_text = "-"
            elif fixed_max == 1.0:
                value_text = f"{float(value) * 100.0:.1f}%"
            else:
                value_text = _fmt_float(float(value), digits=digits)
            value_rows.append(
                (
                    f"<div class=\"metric-radar-value-label\">{escape(value_label)}</div>"
                    f"<div class=\"metric-radar-value-number\">{escape(value_text)}</div>"
                )
            )

        title_text = item.title.strip() or "-"
        heading_text = f"{item.label}: {title_text}" if title_text != "-" else item.label
        aria_label = f"{aria_prefix} {item.label}"
        if title_text != "-":
            aria_label = f"{aria_label} {title_text}"

        cards.append(
            (
                "<article class=\"metric-radar-card\">"
                f"<h4 title=\"{escape(title_text)}\">{escape(heading_text)}</h4>"
                f"<svg class=\"metric-radar-svg\" viewBox=\"0 0 180 180\" role=\"img\" aria-label=\"{escape(aria_label)}\">"
                f"{''.join(rings_svg)}"
                f"{axes_svg}"
                f"{''.join(axis_labels_svg)}"
                f"<polygon class=\"metric-radar-shape\" points=\"{shape_points}\"></polygon>"
                f"{''.join(point_svg)}"
                "</svg>"
                f"<div class=\"metric-radar-values\">{''.join(value_rows)}</div>"
                "</article>"
            )
        )

    return f"<div class=\"metric-radar-grid\">{''.join(cards)}</div>"


def _dim_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    if not text:
        return None
    return text


def _dims_from_config_name(config_name: str) -> dict[str, str]:
    dims: dict[str, str] = {}
    for key in ("extractor", "parser", "skiphf", "pre"):
        match = re.search(rf"{key}_(.+?)(?:__|$)", config_name)
        if match is None:
            continue
        token = match.group(1).strip()
        if token:
            dims[key] = token
    return dims


def _all_method_dims(record: BenchmarkRecord) -> tuple[str, str, str, str]:
    run_config = record.run_config or {}
    parsed_name_dims = _dims_from_config_name(_config_name(record))

    extractor = _dim_value(run_config.get("epub_extractor")) or parsed_name_dims.get("extractor")
    parser = _dim_value(run_config.get("epub_unstructured_html_parser_version")) or parsed_name_dims.get("parser")
    skiphf = _dim_value(run_config.get("epub_unstructured_skip_headers_footers")) or parsed_name_dims.get("skiphf")
    preprocess = _dim_value(run_config.get("epub_unstructured_preprocess_mode")) or parsed_name_dims.get("pre")

    extractor_text = extractor or "-"
    if extractor_text not in {"unstructured", "auto"}:
        return extractor_text, "-", "-", "-"
    return extractor_text, parser or "-", skiphf or "-", preprocess or "-"


def _run_config_summary(record: BenchmarkRecord) -> str:
    if record.run_config_summary:
        return str(record.run_config_summary)
    run_config = record.run_config or {}
    return summarize_run_config_payload(run_config)


def _source_label(record: BenchmarkRecord) -> str:
    source = str(record.source_file or "").strip()
    if not source:
        return "-"
    return Path(source).name or source


def _gold_recipe_headers(record: BenchmarkRecord) -> int | None:
    explicit = getattr(record, "gold_recipe_headers", None)
    if explicit is not None:
        try:
            value = int(explicit)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    for label_metrics in record.per_label:
        if str(label_metrics.label).upper() != "RECIPE_TITLE":
            continue
        value = label_metrics.gold_total
        if value is None:
            continue
        try:
            parsed = int(value)
            if parsed > 0:
                return parsed
        except (TypeError, ValueError):
            continue
    return None


def _group_gold_recipe_headers(group: _AllMethodGroup) -> int | None:
    values = [
        value
        for value in (_gold_recipe_headers(record) for record in group.records)
        if value is not None and value > 0
    ]
    if not values:
        return None
    return max(values)


def _recipes_identified_ratio(
    record: BenchmarkRecord,
    *,
    group_gold_recipe_headers: int | None = None,
) -> float | None:
    if record.recipes is None:
        return None
    gold_total = _gold_recipe_headers(record)
    if gold_total is None:
        gold_total = group_gold_recipe_headers
    if gold_total is None or gold_total <= 0:
        return None
    return max(0.0, min(1.0, float(record.recipes) / float(gold_total)))


def _slug_token(value: str | None) -> str:
    token = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip())
    token = token.strip("._-")
    return token or "unknown"


def _all_method_group_info_from_path(group_dir: Path) -> tuple[str, str, str | None, str] | None:
    """Return (group_dir, run_root_dir, run_dir_timestamp, source_slug) for an all-method group dir."""
    try:
        resolved = group_dir.expanduser().resolve(strict=False)
    except OSError:
        resolved = group_dir
    parts = list(resolved.parts)
    lower_parts = [part.lower() for part in parts]
    for idx, part in enumerate(lower_parts):
        if part != _ALL_METHOD_BENCHMARK_SEGMENT:
            continue
        if idx + 1 >= len(parts):
            continue
        run_root_dir = str(Path(*parts[: idx + 1]))
        group_dir_str = str(Path(*parts[: idx + 2]))
        run_dir_timestamp = parts[idx - 1] if idx > 0 else None
        source_slug = parts[idx + 1]
        return group_dir_str, run_root_dir, run_dir_timestamp, source_slug
    return None


def _load_all_method_report(group_dir: Path) -> dict[str, Any] | None:
    report_path = group_dir / _ALL_METHOD_REPORT_JSON
    try:
        if not report_path.is_file():
            return None
    except OSError:
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    variants = payload.get("variants")
    if not isinstance(variants, list):
        return None
    return payload


def _load_manifest_fields(
    config_dir: Path,
) -> tuple[str | None, str | None, int | None, dict[str, Any] | None]:
    """Load (importer_name, source_file, recipe_count, run_config) from a config dir when available."""
    candidates = (
        config_dir / "manifest.json",
    )
    for path in candidates:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        importer_name = payload.get("importer_name") or payload.get("pipeline")
        source_file = payload.get("source_file")
        recipe_count = payload.get("recipe_count")
        run_config = payload.get("run_config") if isinstance(payload.get("run_config"), dict) else None
        try:
            recipe_count_int = int(recipe_count) if recipe_count is not None else None
        except (TypeError, ValueError):
            recipe_count_int = None
        return (
            str(importer_name) if importer_name is not None else None,
            str(source_file) if source_file is not None else None,
            recipe_count_int,
            run_config,
        )
    return (None, None, None, None)
