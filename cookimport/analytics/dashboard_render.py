"""Render a static HTML dashboard from :class:`DashboardData`.

Writes four files into ``out_dir``:

* ``index.html``
* ``assets/dashboard_data.json``
* ``assets/dashboard.js``
* ``assets/style.css``

No external CDN dependencies – everything is local.
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

from .dashboard_schema import BenchmarkRecord, DashboardData

_ALL_METHOD_BENCHMARK_SEGMENT = "all-method-benchmark"
_ALL_METHOD_CONFIG_PREFIX = "config_"
_ALL_METHOD_OUTPUT_SUBDIR = _ALL_METHOD_BENCHMARK_SEGMENT
_ALL_METHOD_INDEX_PAGE = "index.html"
_ALL_METHOD_INDEX_HREF = f"{_ALL_METHOD_OUTPUT_SUBDIR}/{_ALL_METHOD_INDEX_PAGE}"
_ALL_METHOD_RUN_PAGE_PREFIX = "all-method-benchmark-run__"
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


def render_dashboard(out_dir: Path, data: DashboardData) -> Path:
    """Write dashboard files and return the path to ``index.html``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    data_json = data.model_dump_json(indent=2)

    # Write data JSON
    data_path = assets_dir / "dashboard_data.json"
    data_path.write_text(
        data_json,
        encoding="utf-8",
    )

    # Write CSS
    css_path = assets_dir / "style.css"
    css_path.write_text(_CSS, encoding="utf-8")

    # Write JS
    js_path = assets_dir / "dashboard.js"
    js_path.write_text(_JS, encoding="utf-8")

    all_method_section_html = _render_all_method_pages(out_dir, data)

    # Write HTML
    html_path = out_dir / "index.html"
    html_data_json = data_json.replace("</", "<\\/")
    html_path.write_text(
        _HTML
        .replace("__DASHBOARD_DATA_INLINE__", html_data_json)
        .replace("__ALL_METHOD_SECTION__", all_method_section_html),
        encoding="utf-8",
    )

    return html_path


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
        if part != _ALL_METHOD_BENCHMARK_SEGMENT:
            continue
        if idx + 2 >= len(parts):
            continue
        source_slug = parts[idx + 1]
        config_dir = parts[idx + 2]
        if not config_dir.startswith(_ALL_METHOD_CONFIG_PREFIX):
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
    ordered_keys = (
        "epub_extractor",
        "epub_extractor_requested",
        "epub_extractor_effective",
        "ocr_device",
        "ocr_batch_size",
        "workers",
        "effective_workers",
        "pdf_split_workers",
        "epub_split_workers",
        "pdf_pages_per_job",
        "epub_spine_items_per_job",
        "warm_models",
    )
    parts: list[str] = []
    for key in ordered_keys:
        if key not in run_config:
            continue
        parts.append(f"{key}={run_config.get(key)}")
    return " | ".join(parts)


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


def _collect_all_method_groups(data: DashboardData) -> list[_AllMethodGroup]:
    grouped: dict[str, _AllMethodGroup] = {}
    seen_by_group: dict[str, dict[str, BenchmarkRecord]] = {}

    for record in data.benchmark_records:
        key_info = _all_method_group_key(record)
        if key_info is None:
            continue
        group_dir, run_root_dir, run_dir_timestamp, source_slug = key_info

        group = grouped.get(group_dir)
        if group is None:
            group = _AllMethodGroup(
                group_dir=group_dir,
                run_root_dir=run_root_dir,
                run_dir_timestamp=run_dir_timestamp,
                source_slug=source_slug,
                records=[],
            )
            grouped[group_dir] = group
            seen_by_group[group_dir] = {}

        record_key = str(record.artifact_dir or "")
        if not record_key:
            record_key = f"row-{len(seen_by_group[group_dir]) + 1}"
        prior = seen_by_group[group_dir].get(record_key)
        if prior is None:
            seen_by_group[group_dir][record_key] = record
            continue

        if _run_timestamp_sort_key(record.run_timestamp) > _run_timestamp_sort_key(prior.run_timestamp):
            seen_by_group[group_dir][record_key] = record

    groups: list[_AllMethodGroup] = []
    for group_dir, group in grouped.items():
        records = list(seen_by_group[group_dir].values())
        records = sorted(records, key=_config_name)
        records = sorted(
            records,
            key=lambda row: (
                _metric(row.f1),
                _metric(row.practical_f1),
                _metric(row.precision),
                _metric(row.recall),
            ),
            reverse=True,
        )
        groups.append(
            _AllMethodGroup(
                group_dir=group.group_dir,
                run_root_dir=group.run_root_dir,
                run_dir_timestamp=group.run_dir_timestamp,
                source_slug=group.source_slug,
                records=records,
            )
        )

    groups.sort(
        key=lambda group: _run_timestamp_sort_key(group.run_dir_timestamp),
        reverse=True,
    )
    return groups


def _best_record(records: list[BenchmarkRecord]) -> BenchmarkRecord | None:
    if not records:
        return None
    return max(
        records,
        key=lambda row: (
            _metric(row.f1),
            _metric(row.practical_f1),
            _metric(row.precision),
            _metric(row.recall),
        ),
    )


def _group_source_label(group: _AllMethodGroup) -> str:
    names = sorted(
        {
            _source_label(record)
            for record in group.records
            if _source_label(record) != "-"
        }
    )
    if not names:
        return group.source_slug
    if len(names) == 1:
        return names[0]
    return f"{names[0]} (+{len(names) - 1} more)"


def _group_page_name(group: _AllMethodGroup) -> str:
    return (
        f"{_ALL_METHOD_BENCHMARK_SEGMENT}__"
        f"{_slug_token(group.run_dir_timestamp)}__"
        f"{_slug_token(group.source_slug)}.html"
    )


def _run_page_name(run: _AllMethodRun) -> str:
    return (
        f"{_ALL_METHOD_RUN_PAGE_PREFIX}"
        f"{_slug_token(run.run_dir_timestamp)}.html"
    )


def _aggregate_config_key(record: BenchmarkRecord) -> str:
    config_hash = str(record.run_config_hash or "").strip().lower()
    if config_hash:
        return f"hash:{config_hash}"
    return f"name:{_config_name(record)}"


def _aggregate_run_configs(
    groups: list[_AllMethodGroup],
) -> list[_AllMethodConfigAggregate]:
    state: dict[str, dict[str, Any]] = {}

    for group in groups:
        group_gold_total = _group_gold_recipe_headers(group)
        winner = _best_record(group.records)
        winner_key = _aggregate_config_key(winner) if winner is not None else None
        for record in group.records:
            config_key = _aggregate_config_key(record)
            entry = state.get(config_key)
            if entry is None:
                config_hash = str(record.run_config_hash or "").strip() or None
                summary = _run_config_summary(record)
                if summary and config_hash:
                    run_config_text = f"{summary} [{config_hash[:10]}]"
                elif config_hash:
                    run_config_text = f"[{config_hash[:10]}]"
                else:
                    run_config_text = summary or "-"
                extractor_dim, parser_dim, skiphf_dim, preprocess_dim = _all_method_dims(
                    record
                )
                entry = {
                    "config_names": set(),
                    "book_keys": set(),
                    "wins": 0,
                    "extractor": extractor_dim,
                    "parser": parser_dim,
                    "skiphf": skiphf_dim,
                    "preprocess": preprocess_dim,
                    "importer_name": str(record.importer_name or "-"),
                    "run_config_text": run_config_text,
                    "run_config_hash": config_hash,
                    "strict_precision_values": [],
                    "strict_recall_values": [],
                    "strict_f1_values": [],
                    "practical_f1_values": [],
                    "recipes_values": [],
                    "recipe_identified_pct_values": [],
                }
                state[config_key] = entry

            entry["config_names"].add(_config_name(record))
            entry["book_keys"].add(group.group_dir)
            if record.precision is not None:
                entry["strict_precision_values"].append(float(record.precision))
            if record.recall is not None:
                entry["strict_recall_values"].append(float(record.recall))
            if record.f1 is not None:
                entry["strict_f1_values"].append(float(record.f1))
            if record.practical_f1 is not None:
                entry["practical_f1_values"].append(float(record.practical_f1))
            if record.recipes is not None:
                entry["recipes_values"].append(float(record.recipes))
            recipe_identified_ratio = _recipes_identified_ratio(
                record,
                group_gold_recipe_headers=group_gold_total,
            )
            if recipe_identified_ratio is not None:
                entry["recipe_identified_pct_values"].append(recipe_identified_ratio)

        if winner_key is not None and winner_key in state:
            state[winner_key]["wins"] += 1

    aggregates: list[_AllMethodConfigAggregate] = []
    for config_key, entry in state.items():
        config_names = sorted(str(name) for name in entry["config_names"] if str(name))
        config_name = config_names[0] if config_names else "<unknown>"
        aggregates.append(
            _AllMethodConfigAggregate(
                config_key=config_key,
                config_name=config_name,
                extractor=entry["extractor"],
                parser=entry["parser"],
                skiphf=entry["skiphf"],
                preprocess=entry["preprocess"],
                importer_name=entry["importer_name"],
                run_config_text=entry["run_config_text"],
                run_config_hash=entry["run_config_hash"],
                books=len(entry["book_keys"]),
                wins=int(entry["wins"]),
                strict_precision_mean=_mean(entry["strict_precision_values"]),
                strict_recall_mean=_mean(entry["strict_recall_values"]),
                strict_f1_mean=_mean(entry["strict_f1_values"]),
                practical_f1_mean=_mean(entry["practical_f1_values"]),
                recipes_mean=_mean(entry["recipes_values"]),
                recipe_identified_pct_mean=_mean(
                    entry["recipe_identified_pct_values"]
                ),
            )
        )

    aggregates = sorted(aggregates, key=lambda row: row.config_name.lower())
    aggregates = sorted(
        aggregates,
        key=lambda row: (
            row.books,
            _metric(row.practical_f1_mean),
            _metric(row.strict_f1_mean),
            row.wins,
            _metric(row.strict_precision_mean),
            _metric(row.strict_recall_mean),
        ),
        reverse=True,
    )
    return aggregates


def _collect_all_method_runs(groups: list[_AllMethodGroup]) -> list[_AllMethodRun]:
    runs_by_key: dict[str, _AllMethodRun] = {}
    for group in groups:
        run_key = group.run_root_dir or group.group_dir
        run = runs_by_key.get(run_key)
        if run is None:
            run = _AllMethodRun(
                run_key=run_key,
                run_dir_timestamp=group.run_dir_timestamp,
            )
            runs_by_key[run_key] = run
        run.groups.append(group)
        if _run_timestamp_sort_key(group.run_dir_timestamp) > _run_timestamp_sort_key(
            run.run_dir_timestamp
        ):
            run.run_dir_timestamp = group.run_dir_timestamp

    runs: list[_AllMethodRun] = []
    for run in runs_by_key.values():
        run.groups = sorted(
            run.groups,
            key=lambda group: _group_source_label(group).lower(),
        )
        run.config_aggregates = _aggregate_run_configs(run.groups)
        runs.append(run)

    runs.sort(
        key=lambda run: _run_timestamp_sort_key(run.run_dir_timestamp),
        reverse=True,
    )
    return runs


def _run_best_config(run: _AllMethodRun) -> _AllMethodConfigAggregate | None:
    if not run.config_aggregates:
        return None
    return run.config_aggregates[0]


def _render_all_method_index_html(runs: list[_AllMethodRun]) -> str:
    empty_note = ""
    if not runs:
        empty_note = (
            "<p class=\"empty-note\">No all-method benchmark runs found in benchmark history.</p>"
        )

    row_html: list[str] = []
    for run in runs:
        best = _run_best_config(run)
        winner_name = best.config_name if best is not None else "-"
        row_html.append(
            (
                "<tr>"
                f"<td>{escape(run.run_dir_timestamp or '-')}</td>"
                f"<td class=\"num\">{len(run.groups)}</td>"
                f"<td class=\"num\">{len(run.config_aggregates)}</td>"
                f"<td>{escape(winner_name)}</td>"
                f"<td class=\"num\">{_fmt_float(best.strict_f1_mean if best else None)}</td>"
                f"<td class=\"num\">{_fmt_float(best.practical_f1_mean if best else None)}</td>"
                f"<td><a href=\"{escape(run.detail_page_name)}\">Open run details</a></td>"
                "</tr>"
            )
        )

    return (
        "<!DOCTYPE html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>cookimport – All Method Benchmarks</title>"
        "<link rel=\"stylesheet\" href=\"../assets/style.css\">"
        "</head>"
        "<body>"
        "<header><h1>All Method Benchmark Runs</h1>"
        "<p><a href=\"../index.html\">Dashboard home</a></p>"
        "</header>"
        "<main>"
        "<section>"
        "<p class=\"section-note\">Each row links to a run summary page with config performance aggregated across all books in one all-method sweep.</p>"
        f"{empty_note}"
        "<table><thead><tr>"
        "<th>Run Folder</th><th>Book Jobs</th><th>Configs</th><th>Winner</th><th>Mean Strict F1</th><th>Mean Practical F1</th><th>Details</th>"
        "</tr></thead><tbody>"
        f"{''.join(row_html)}"
        "</tbody></table>"
        "</section>"
        "</main>"
        "<footer>Generated by <code>cookimport stats-dashboard</code></footer>"
        "</body>"
        "</html>"
    )


def _render_all_method_run_html(run: _AllMethodRun) -> str:
    best = _run_best_config(run)
    winner_line = "-"
    if best is not None:
        winner_line = (
            f"{best.config_name} "
            f"(books={best.books}, wins={best.wins}, "
            f"mean_strict_f1={_fmt_float(best.strict_f1_mean)}, "
            f"mean_practical_f1={_fmt_float(best.practical_f1_mean)})"
        )

    aggregate_rows: list[str] = []
    for rank, aggregate in enumerate(run.config_aggregates, start=1):
        aggregate_rows.append(
            (
                "<tr>"
                f"<td class=\"num\">{rank}</td>"
                f"<td>{escape(aggregate.config_name)}</td>"
                f"<td>{escape(aggregate.extractor)}</td>"
                f"<td>{escape(aggregate.parser)}</td>"
                f"<td>{escape(aggregate.skiphf)}</td>"
                f"<td>{escape(aggregate.preprocess)}</td>"
                f"<td class=\"num\">{aggregate.books}</td>"
                f"<td class=\"num\">{aggregate.wins}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.strict_precision_mean)}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.strict_recall_mean)}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.strict_f1_mean)}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.practical_f1_mean)}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.recipes_mean, digits=1)}</td>"
                f"<td>{escape(aggregate.importer_name or '-')}</td>"
                f"<td title=\"{escape(aggregate.run_config_text)}\">{escape(aggregate.run_config_text)}</td>"
                "</tr>"
            )
        )

    book_rows: list[str] = []
    book_averages: list[_AllMethodBookAggregate] = []
    for group in run.groups:
        source_label = _group_source_label(group)
        best_group = _best_record(group.records)
        group_gold_headers = _group_gold_recipe_headers(group)
        recipe_identified_values = [
            ratio
            for ratio in (
                _recipes_identified_ratio(
                    record,
                    group_gold_recipe_headers=group_gold_headers,
                )
                for record in group.records
            )
            if ratio is not None
        ]
        book_averages.append(
            _AllMethodBookAggregate(
                source_label=source_label,
                config_count=len(group.records),
                mean_strict_precision=_mean(
                    [
                        float(record.precision)
                        for record in group.records
                        if record.precision is not None
                    ]
                ),
                mean_strict_recall=_mean(
                    [
                        float(record.recall)
                        for record in group.records
                        if record.recall is not None
                    ]
                ),
                mean_strict_f1=_mean(
                    [
                        float(record.f1)
                        for record in group.records
                        if record.f1 is not None
                    ]
                ),
                mean_practical_f1=_mean(
                    [
                        float(record.practical_f1)
                        for record in group.records
                        if record.practical_f1 is not None
                    ]
                ),
                mean_recipe_identified_pct=_mean(
                    [float(value) for value in recipe_identified_values]
                ),
            )
        )
        book_rows.append(
            (
                "<tr>"
                f"<td>{escape(source_label)}</td>"
                f"<td class=\"num\">{len(group.records)}</td>"
                f"<td>{escape(_config_name(best_group) if best_group else '-')}</td>"
                f"<td class=\"num\">{_fmt_float(best_group.f1 if best_group else None)}</td>"
                f"<td class=\"num\">{_fmt_float(best_group.practical_f1 if best_group else None)}</td>"
                f"<td><a href=\"{escape(group.detail_page_name)}\">Open book details</a></td>"
                "</tr>"
            )
        )

    summary_specs: list[tuple[str, int, list[float]]] = [
        (
            "Mean Strict Precision",
            4,
            [
                float(aggregate.strict_precision_mean)
                for aggregate in run.config_aggregates
                if aggregate.strict_precision_mean is not None
            ],
        ),
        (
            "Mean Strict Recall",
            4,
            [
                float(aggregate.strict_recall_mean)
                for aggregate in run.config_aggregates
                if aggregate.strict_recall_mean is not None
            ],
        ),
        (
            "Mean Strict F1",
            4,
            [
                float(aggregate.strict_f1_mean)
                for aggregate in run.config_aggregates
                if aggregate.strict_f1_mean is not None
            ],
        ),
        (
            "Mean Practical F1",
            4,
            [
                float(aggregate.practical_f1_mean)
                for aggregate in run.config_aggregates
                if aggregate.practical_f1_mean is not None
            ],
        ),
        (
            "Recipes Identified %",
            1,
            [
                float(aggregate.recipe_identified_pct_mean)
                for aggregate in run.config_aggregates
                if aggregate.recipe_identified_pct_mean is not None
            ],
        ),
    ]
    summary_rows: list[str] = []
    for label, digits, values in summary_specs:
        summary_rows.append(
            (
                "<tr>"
                f"<td>{escape(label)}</td>"
                f"<td class=\"num\">{len(values)}</td>"
                f"<td class=\"num\">{_fmt_float(min(values) if values else None, digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(_median(values), digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(_mean(values), digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(max(values) if values else None, digits=digits)}</td>"
                "</tr>"
            )
        )

    chart_specs: list[tuple[str, int, list[float | None], float | None]] = [
        (
            "Mean Strict Precision",
            4,
            [aggregate.strict_precision_mean for aggregate in run.config_aggregates],
            1.0,
        ),
        (
            "Mean Strict Recall",
            4,
            [aggregate.strict_recall_mean for aggregate in run.config_aggregates],
            1.0,
        ),
        (
            "Mean Strict F1",
            4,
            [aggregate.strict_f1_mean for aggregate in run.config_aggregates],
            1.0,
        ),
        (
            "Mean Practical F1",
            4,
            [aggregate.practical_f1_mean for aggregate in run.config_aggregates],
            1.0,
        ),
        (
            "Recipes Identified %",
            1,
            [aggregate.recipe_identified_pct_mean for aggregate in run.config_aggregates],
            1.0,
        ),
    ]
    chart_blocks: list[str] = []
    for label, digits, raw_values, fixed_max in chart_specs:
        present_values = [value for value in raw_values if value is not None]
        if fixed_max is not None and fixed_max > 0:
            max_value = float(fixed_max)
        else:
            max_value = max(present_values) if present_values else 0.0
        bar_rows: list[str] = []
        for config_index, value in enumerate(raw_values, start=1):
            width_pct = 0.0
            if value is not None and max_value > 0:
                width_pct = max(0.0, min(100.0, float(value) / float(max_value) * 100.0))
            bar_fill_class = "metric-bar-fill" if value is not None else "metric-bar-fill metric-bar-fill-missing"
            if value is None:
                value_text = "-"
            elif fixed_max == 1.0:
                value_text = f"{float(value) * 100.0:.1f}%"
            else:
                value_text = _fmt_float(float(value), digits=digits)
            bar_rows.append(
                (
                    "<div class=\"metric-bar-row\">"
                    f"<span class=\"metric-bar-label\">Config {config_index:02d}</span>"
                    "<span class=\"metric-bar-track\">"
                    f"<span class=\"{bar_fill_class}\" style=\"width:{width_pct:.2f}%\"></span>"
                    "</span>"
                    f"<span class=\"metric-bar-value\">{escape(value_text)}</span>"
                    "</div>"
                )
            )
        chart_blocks.append(
            (
                "<section class=\"metric-chart-block\">"
                f"<h3>{escape(label)}</h3>"
                f"<div class=\"metric-chart-grid\">{''.join(bar_rows)}</div>"
                "</section>"
            )
        )

    def _book_leader_text(metric_label: str, values: list[tuple[str, float | None]]) -> str:
        best_label = "-"
        best_value: float | None = None
        for label, value in values:
            if value is None:
                continue
            if best_value is None or value > best_value:
                best_label = label
                best_value = float(value)
        if best_value is None:
            return f"{metric_label}: -"
        return f"{metric_label}: {best_label} ({best_value * 100.0:.1f}%)"

    book_highlights = [
        _book_leader_text(
            "Highest avg strict precision",
            [
                (book.source_label, book.mean_strict_precision)
                for book in book_averages
            ],
        ),
        _book_leader_text(
            "Highest avg strict recall",
            [
                (book.source_label, book.mean_strict_recall)
                for book in book_averages
            ],
        ),
        _book_leader_text(
            "Highest avg strict F1",
            [(book.source_label, book.mean_strict_f1) for book in book_averages],
        ),
    ]
    book_highlight_html = "".join(
        f"<p class=\"section-note\">{escape(line)}</p>"
        for line in book_highlights
    )

    book_chart_specs: list[tuple[str, int, list[float | None], float | None]] = [
        (
            "Avg Strict Precision",
            4,
            [
                book.mean_strict_precision
                for book in book_averages
            ],
            1.0,
        ),
        (
            "Avg Strict Recall",
            4,
            [
                book.mean_strict_recall
                for book in book_averages
            ],
            1.0,
        ),
        (
            "Avg Strict F1",
            4,
            [
                book.mean_strict_f1
                for book in book_averages
            ],
            1.0,
        ),
        (
            "Avg Practical F1",
            4,
            [
                book.mean_practical_f1
                for book in book_averages
            ],
            1.0,
        ),
        (
            "Avg Recipes Identified %",
            1,
            [book.mean_recipe_identified_pct for book in book_averages],
            1.0,
        ),
    ]
    book_chart_blocks: list[str] = []
    for label, digits, raw_values, fixed_max in book_chart_specs:
        present_values = [value for value in raw_values if value is not None]
        if fixed_max is not None and fixed_max > 0:
            max_value = float(fixed_max)
        else:
            max_value = max(present_values) if present_values else 0.0
        bar_rows: list[str] = []
        for book_index, value in enumerate(raw_values, start=1):
            source_label = book_averages[book_index - 1].source_label
            config_count = book_averages[book_index - 1].config_count
            width_pct = 0.0
            if value is not None and max_value > 0:
                width_pct = max(0.0, min(100.0, float(value) / float(max_value) * 100.0))
            bar_fill_class = "metric-bar-fill" if value is not None else "metric-bar-fill metric-bar-fill-missing"
            if value is None:
                value_text = "-"
            elif fixed_max == 1.0:
                value_text = f"{float(value) * 100.0:.1f}%"
            else:
                value_text = _fmt_float(float(value), digits=digits)
            bar_rows.append(
                (
                    "<div class=\"metric-bar-row\">"
                    f"<span class=\"metric-bar-label\" title=\"{escape(source_label)}\">Book {book_index:02d} (n={config_count})</span>"
                    "<span class=\"metric-bar-track\">"
                    f"<span class=\"{bar_fill_class}\" style=\"width:{width_pct:.2f}%\"></span>"
                    "</span>"
                    f"<span class=\"metric-bar-value\">{escape(value_text)}</span>"
                    "</div>"
                )
            )
        book_chart_blocks.append(
            (
                "<section class=\"metric-chart-block\">"
                f"<h3>{escape(label)}</h3>"
                f"<div class=\"metric-chart-grid\">{''.join(bar_rows)}</div>"
                "</section>"
            )
        )

    book_radar_metric_specs: list[tuple[str, str, int, float | None]] = [
        ("Strict P", "Avg Strict Precision", 4, 1.0),
        ("Strict R", "Avg Strict Recall", 4, 1.0),
        ("Strict F1", "Avg Strict F1", 4, 1.0),
        ("Prac F1", "Avg Practical F1", 4, 1.0),
        ("Recipes", "Avg Recipes Identified %", 1, 1.0),
    ]
    book_radar_items = [
        _MetricRadarItem(
            label=f"Book {book_index:02d}",
            title=f"{book.source_label} (configs={book.config_count})",
            values=[
                book.mean_strict_precision,
                book.mean_strict_recall,
                book.mean_strict_f1,
                book.mean_practical_f1,
                book.mean_recipe_identified_pct,
            ],
        )
        for book_index, book in enumerate(book_averages, start=1)
    ]
    book_radar_cards = _render_metric_radar_cards(
        items=book_radar_items,
        metric_specs=book_radar_metric_specs,
        aria_prefix="Cookbook",
    )

    run_radar_metric_specs: list[tuple[str, str, int, float | None]] = [
        ("Strict P", "Mean Strict Precision", 4, 1.0),
        ("Strict R", "Mean Strict Recall", 4, 1.0),
        ("Strict F1", "Mean Strict F1", 4, 1.0),
        ("Prac F1", "Mean Practical F1", 4, 1.0),
        ("Recipes", "Recipes Identified %", 1, 1.0),
    ]
    run_radar_items = [
        _MetricRadarItem(
            label=f"Config {config_index:02d}",
            title=aggregate.config_name,
            values=[
                aggregate.strict_precision_mean,
                aggregate.strict_recall_mean,
                aggregate.strict_f1_mean,
                aggregate.practical_f1_mean,
                aggregate.recipe_identified_pct_mean,
            ],
        )
        for config_index, aggregate in enumerate(run.config_aggregates, start=1)
    ]
    run_radar_cards = _render_metric_radar_cards(
        items=run_radar_items,
        metric_specs=run_radar_metric_specs,
        aria_prefix="Run config",
    )

    return (
        "<!DOCTYPE html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>cookimport – All Method Benchmark Run {escape(run.run_dir_timestamp or '')}</title>"
        "<link rel=\"stylesheet\" href=\"../assets/style.css\">"
        "</head>"
        "<body>"
        "<header>"
        "<h1>All Method Benchmark Run Summary</h1>"
        f"<p><a href=\"../index.html\">Dashboard home</a> · <a href=\"{_ALL_METHOD_INDEX_PAGE}\">All-method runs</a></p>"
        "</header>"
        "<main>"
        "<nav class=\"all-method-quick-nav\" aria-label=\"Run page sections\">"
        "<a href=\"#run-summary\">Summary</a>"
        "<a href=\"#run-charts\">Charts</a>"
        "<a href=\"#run-config-table\">Ranked Table</a>"
        "<a href=\"#run-drilldown\">Drilldown</a>"
        "</nav>"
        "<section id=\"run-overview\">"
        f"<p><strong>Run folder:</strong> {escape(run.run_dir_timestamp or '-')}</p>"
        f"<p><strong>Book jobs:</strong> {len(run.groups)}</p>"
        f"<p><strong>Configs aggregated:</strong> {len(run.config_aggregates)}</p>"
        f"<p><strong>Winner:</strong> {escape(winner_line)}</p>"
        "</section>"
        "<section id=\"run-summary\">"
        "<h2>Run Summary</h2>"
        "<p class=\"section-note\">Compact stats across aggregated config rows: count, min, median, mean, max.</p>"
        "<table class=\"summary-compact\"><thead><tr>"
        "<th>Stat</th><th>N</th><th>Min</th><th>Median</th><th>Mean</th><th>Max</th>"
        "</tr></thead><tbody>"
        f"{''.join(summary_rows)}"
        "</tbody></table>"
        "</section>"
        "<details id=\"run-charts\" class=\"section-details\" open>"
        "<summary>Charts</summary>"
        "<section id=\"run-chart-bars\">"
        "<h2>Metric Bar Charts</h2>"
        "<p class=\"section-note\">One bar per aggregated configuration for each metric category. All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for each book.</p>"
        f"{''.join(chart_blocks)}"
        "</section>"
        "<section id=\"run-chart-radar\">"
        "<h2>Metric Web Charts (Radar)</h2>"
        "<p class=\"section-note\">Each web is one aggregated configuration. All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for each book.</p>"
        f"{run_radar_cards}"
        "</section>"
        "<section id=\"run-book-chart-bars\">"
        "<h2>Per-Cookbook Average Metric Bar Charts</h2>"
        "<p class=\"section-note\">One bar per cookbook. Values are averaged across all configs that ran for that cookbook. Labels use Book 01/Book 02 order from Per-Book Drilldown. All axes use fixed 0-100%; recipes is percent identified vs each cookbook's golden recipe headers.</p>"
        f"{book_highlight_html}"
        f"{''.join(book_chart_blocks)}"
        "</section>"
        "<section id=\"run-book-chart-radar\">"
        "<h2>Per-Cookbook Average Web Charts (Radar)</h2>"
        "<p class=\"section-note\">Each web is one cookbook with metrics averaged across all configs that ran for that cookbook. All axes use fixed 0-100%; recipes is percent identified vs each cookbook's golden recipe headers.</p>"
        f"{book_radar_cards}"
        "</section>"
        "</details>"
        "<details id=\"run-config-table\" class=\"section-details\" open>"
        "<summary>Ranked Config Table</summary>"
        "<section>"
        "<h2>Config Performance Across Books</h2>"
        "<p class=\"section-note\">Aggregated by configuration across all per-book jobs in this run.</p>"
        "<table><thead><tr>"
        "<th>Rank</th><th>Configuration</th><th>Extractor</th><th>Parser</th><th>Skip HF</th><th>Preprocess</th><th>Books</th><th>Wins</th><th>Mean Strict Precision</th><th>Mean Strict Recall</th><th>Mean Strict F1</th><th>Mean Practical F1</th><th>Mean Recipes</th><th>Importer</th><th>Run Config</th>"
        "</tr></thead><tbody>"
        f"{''.join(aggregate_rows)}"
        "</tbody></table>"
        "</section>"
        "</details>"
        "<details id=\"run-drilldown\" class=\"section-details\" open>"
        "<summary>Per-Book Drilldown</summary>"
        "<section>"
        "<h2>Per-Book Drilldown</h2>"
        "<p class=\"section-note\">Open each source row for the existing per-book config breakdown page.</p>"
        "<table><thead><tr>"
        "<th>Source</th><th>Configs</th><th>Winner</th><th>Strict F1</th><th>Practical F1</th><th>Details</th>"
        "</tr></thead><tbody>"
        f"{''.join(book_rows)}"
        "</tbody></table>"
        "</section>"
        "</details>"
        "</main>"
        "<footer>Generated by <code>cookimport stats-dashboard</code></footer>"
        "</body>"
        "</html>"
    )


def _render_all_method_detail_html(
    group: _AllMethodGroup,
    *,
    run_detail_page_name: str | None = None,
) -> str:
    best = _best_record(group.records)
    source_label = _group_source_label(group)
    rows: list[str] = []
    for rank, record in enumerate(group.records, start=1):
        extractor_dim, parser_dim, skiphf_dim, preprocess_dim = _all_method_dims(record)
        config_hash = str(record.run_config_hash or "")
        summary = _run_config_summary(record)
        if summary and config_hash:
            summary = f"{summary} [{config_hash[:10]}]"
        elif config_hash:
            summary = f"[{config_hash[:10]}]"
        artifact_href = str(record.artifact_dir or "").strip()
        artifact_cell = "-"
        if artifact_href:
            artifact_cell = (
                f"<a href=\"{escape(artifact_href)}\">"
                f"{escape(_config_name(record))}</a>"
            )
        rows.append(
            (
                "<tr>"
                f"<td class=\"num\">{rank}</td>"
                f"<td>{escape(_config_name(record))}</td>"
                f"<td>{escape(extractor_dim)}</td>"
                f"<td>{escape(parser_dim)}</td>"
                f"<td>{escape(skiphf_dim)}</td>"
                f"<td>{escape(preprocess_dim)}</td>"
                f"<td class=\"num\">{_fmt_float(record.precision)}</td>"
                f"<td class=\"num\">{_fmt_float(record.recall)}</td>"
                f"<td class=\"num\">{_fmt_float(record.f1)}</td>"
                f"<td class=\"num\">{_fmt_float(record.practical_f1)}</td>"
                f"<td class=\"num\">{_fmt_int(record.recipes)}</td>"
                f"<td>{escape(record.importer_name or '-')}</td>"
                f"<td>{escape(_source_label(record))}</td>"
                f"<td title=\"{escape(summary)}\">{escape(summary or '-')}</td>"
                f"<td>{artifact_cell}</td>"
                "</tr>"
            )
        )

    winner_line = "-"
    if best is not None:
        winner_line = (
            f"{_config_name(best)} "
            f"(strict_f1={_fmt_float(best.f1)}, practical_f1={_fmt_float(best.practical_f1)})"
        )
    group_gold_total = _group_gold_recipe_headers(group)
    recipes_identified_values = [
        _recipes_identified_ratio(
            record,
            group_gold_recipe_headers=group_gold_total,
        )
        for record in group.records
    ]

    summary_specs: list[tuple[str, int, list[float]]] = [
        (
            "Strict Precision",
            4,
            [float(record.precision) for record in group.records if record.precision is not None],
        ),
        (
            "Strict Recall",
            4,
            [float(record.recall) for record in group.records if record.recall is not None],
        ),
        (
            "Strict F1",
            4,
            [float(record.f1) for record in group.records if record.f1 is not None],
        ),
        (
            "Practical F1",
            4,
            [float(record.practical_f1) for record in group.records if record.practical_f1 is not None],
        ),
        (
            "Recipes Identified %",
            1,
            [
                float(value)
                for value in recipes_identified_values
                if value is not None
            ],
        ),
    ]
    summary_rows = []
    for label, digits, values in summary_specs:
        summary_rows.append(
            (
                "<tr>"
                f"<td>{escape(label)}</td>"
                f"<td class=\"num\">{len(values)}</td>"
                f"<td class=\"num\">{_fmt_float(min(values) if values else None, digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(_median(values), digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(_mean(values), digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(max(values) if values else None, digits=digits)}</td>"
                "</tr>"
            )
        )

    chart_specs: list[tuple[str, int, list[float | None], float | None]] = [
        (
            "Strict Precision",
            4,
            [record.precision for record in group.records],
            1.0,
        ),
        (
            "Strict Recall",
            4,
            [record.recall for record in group.records],
            1.0,
        ),
        (
            "Strict F1",
            4,
            [record.f1 for record in group.records],
            1.0,
        ),
        (
            "Practical F1",
            4,
            [record.practical_f1 for record in group.records],
            1.0,
        ),
        (
            "Recipes Identified %",
            1,
            recipes_identified_values,
            1.0,
        ),
    ]
    chart_blocks: list[str] = []
    for label, digits, raw_values, fixed_max in chart_specs:
        present_values = [value for value in raw_values if value is not None]
        if fixed_max is not None and fixed_max > 0:
            max_value = float(fixed_max)
        else:
            max_value = max(present_values) if present_values else 0.0
        bar_rows: list[str] = []
        for run_index, value in enumerate(raw_values, start=1):
            width_pct = 0.0
            if value is not None and max_value > 0:
                width_pct = max(0.0, min(100.0, float(value) / float(max_value) * 100.0))
            bar_fill_class = "metric-bar-fill" if value is not None else "metric-bar-fill metric-bar-fill-missing"
            if value is None:
                value_text = "-"
            elif fixed_max == 1.0:
                value_text = f"{float(value) * 100.0:.1f}%"
            else:
                value_text = _fmt_float(float(value), digits=digits)
            bar_rows.append(
                (
                    "<div class=\"metric-bar-row\">"
                    f"<span class=\"metric-bar-label\">Run {run_index:02d}</span>"
                    "<span class=\"metric-bar-track\">"
                    f"<span class=\"{bar_fill_class}\" style=\"width:{width_pct:.2f}%\"></span>"
                    "</span>"
                    f"<span class=\"metric-bar-value\">{escape(value_text)}</span>"
                    "</div>"
                )
            )
        chart_blocks.append(
            (
                "<section class=\"metric-chart-block\">"
                f"<h3>{escape(label)}</h3>"
                f"<div class=\"metric-chart-grid\">{''.join(bar_rows)}</div>"
                "</section>"
            )
        )

    detail_radar_metric_specs: list[tuple[str, str, int, float | None]] = [
        ("Strict P", "Strict Precision", 4, 1.0),
        ("Strict R", "Strict Recall", 4, 1.0),
        ("Strict F1", "Strict F1", 4, 1.0),
        ("Prac F1", "Practical F1", 4, 1.0),
        ("Recipes", "Recipes Identified %", 1, 1.0),
    ]
    detail_radar_items = [
        _MetricRadarItem(
            label=f"Run {run_index:02d}",
            title=_config_name(record),
            values=[
                record.precision,
                record.recall,
                record.f1,
                record.practical_f1,
                recipes_identified_values[run_index - 1],
            ],
        )
        for run_index, record in enumerate(group.records, start=1)
    ]
    detail_radar_cards = _render_metric_radar_cards(
        items=detail_radar_items,
        metric_specs=detail_radar_metric_specs,
        aria_prefix="Config",
    )

    nav_links = ["<a href=\"../index.html\">Dashboard home</a>"]
    nav_links.append(f"<a href=\"{_ALL_METHOD_INDEX_PAGE}\">All-method runs</a>")
    if run_detail_page_name:
        nav_links.append(
            f"<a href=\"{escape(run_detail_page_name)}\">Run summary</a>"
        )

    return (
        "<!DOCTYPE html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>cookimport – All Method Benchmark {escape(group.run_dir_timestamp or '')}</title>"
        "<link rel=\"stylesheet\" href=\"../assets/style.css\">"
        "</head>"
        "<body>"
        "<header>"
        "<h1>All Method Benchmark Details</h1>"
        f"<p>{' · '.join(nav_links)}</p>"
        "</header>"
        "<main>"
        "<nav class=\"all-method-quick-nav\" aria-label=\"Detail page sections\">"
        "<a href=\"#detail-summary\">Summary</a>"
        "<a href=\"#detail-charts\">Charts</a>"
        "<a href=\"#detail-ranked-table\">Ranked Table</a>"
        "</nav>"
        "<section id=\"detail-overview\">"
        f"<p><strong>Run folder:</strong> {escape(group.run_dir_timestamp or '-')}</p>"
        f"<p><strong>Source:</strong> {escape(source_label)}</p>"
        f"<p><strong>Total configs:</strong> {len(group.records)}</p>"
        f"<p><strong>Golden recipes:</strong> {escape(_fmt_int(group_gold_total))}</p>"
        f"<p><strong>Winner:</strong> {escape(winner_line)}</p>"
        "</section>"
        "<section id=\"detail-summary\">"
        "<h2>Run Summary</h2>"
        "<p class=\"section-note\">Compact stats only (no per-config labels): count, min, median, mean, max.</p>"
        "<table class=\"summary-compact\"><thead><tr>"
        "<th>Stat</th><th>N</th><th>Min</th><th>Median</th><th>Mean</th><th>Max</th>"
        "</tr></thead><tbody>"
        f"{''.join(summary_rows)}"
        "</tbody></table>"
        "</section>"
        "<details id=\"detail-charts\" class=\"section-details\" open>"
        "<summary>Charts</summary>"
        "<section id=\"detail-chart-bars\">"
        "<h2>Metric Bar Charts</h2>"
        "<p class=\"section-note\">One bar per run/configuration for each metric category. All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for this source.</p>"
        f"{''.join(chart_blocks)}"
        "</section>"
        "<section id=\"detail-chart-radar\">"
        "<h2>Metric Web Charts (Radar)</h2>"
        "<p class=\"section-note\">Each web is one run/configuration. All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for this source.</p>"
        f"{detail_radar_cards}"
        "</section>"
        "</details>"
        "<details id=\"detail-ranked-table\" class=\"section-details\" open>"
        "<summary>Ranked Config Table</summary>"
        "<section>"
        "<h2>Ranked Configurations</h2>"
        "<table><thead><tr>"
        "<th>Rank</th><th>Configuration</th><th>Extractor</th><th>Parser</th><th>Skip HF</th><th>Preprocess</th><th>Strict Precision</th><th>Strict Recall</th><th>Strict F1</th><th>Practical F1</th><th>Recipes</th><th>Importer</th><th>Source</th><th>Run Config</th><th>Artifact</th>"
        "</tr></thead><tbody>"
        f"{''.join(rows)}"
        "</tbody></table>"
        "</section>"
        "</details>"
        "</main>"
        "<footer>Generated by <code>cookimport stats-dashboard</code></footer>"
        "</body>"
        "</html>"
    )


def _render_all_method_pages(out_dir: Path, data: DashboardData) -> str:
    groups = _collect_all_method_groups(data)
    runs = _collect_all_method_runs(groups)
    all_method_dir = out_dir / _ALL_METHOD_OUTPUT_SUBDIR
    all_method_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / f"{_ALL_METHOD_BENCHMARK_SEGMENT}.html").unlink(missing_ok=True)
    for stale_detail_page in out_dir.glob(f"{_ALL_METHOD_BENCHMARK_SEGMENT}__*.html"):
        stale_detail_page.unlink(missing_ok=True)
    for stale_run_page in out_dir.glob(f"{_ALL_METHOD_RUN_PAGE_PREFIX}*.html"):
        stale_run_page.unlink(missing_ok=True)
    for stale_subdir_page in all_method_dir.glob("*.html"):
        stale_subdir_page.unlink(missing_ok=True)

    used_page_names: set[str] = set()
    for group in groups:
        base_name = _group_page_name(group)
        page_name = base_name
        suffix = 2
        while page_name in used_page_names:
            page_name = f"{base_name[:-5]}_{suffix}.html"
            suffix += 1
        used_page_names.add(page_name)
        group.detail_page_name = page_name

    for run in runs:
        base_name = _run_page_name(run)
        page_name = base_name
        suffix = 2
        while page_name in used_page_names:
            page_name = f"{base_name[:-5]}_{suffix}.html"
            suffix += 1
        used_page_names.add(page_name)
        run.detail_page_name = page_name

    run_page_by_key = {
        run.run_key: run.detail_page_name
        for run in runs
    }

    for group in groups:
        detail_path = all_method_dir / group.detail_page_name
        detail_path.write_text(
            _render_all_method_detail_html(
                group,
                run_detail_page_name=run_page_by_key.get(group.run_root_dir),
            ),
            encoding="utf-8",
        )

    for run in runs:
        run_path = all_method_dir / run.detail_page_name
        run_path.write_text(
            _render_all_method_run_html(run),
            encoding="utf-8",
        )

    index_path = all_method_dir / _ALL_METHOD_INDEX_PAGE
    index_path.write_text(
        _render_all_method_index_html(runs),
        encoding="utf-8",
    )

    if not runs:
        return (
            "<section id=\"all-method-section\">"
            "<h2>All-Method Benchmark Runs</h2>"
            f"<p><a href=\"{_ALL_METHOD_INDEX_HREF}\">Open all-method benchmark page</a> (0 runs)</p>"
            "<p class=\"empty-note\">No all-method benchmark runs found in benchmark history.</p>"
            "</section>"
        )

    return (
        "<section id=\"all-method-section\">"
        "<h2>All-Method Benchmark Runs</h2>"
        "<p class=\"section-note\">Standalone run-summary and per-book pages generated from benchmark CSV rows grouped by all-method run folder.</p>"
        f"<p><a href=\"{_ALL_METHOD_INDEX_HREF}\">Open all-method benchmark page</a> ({len(runs)} runs)</p>"
        "</section>"
    )


# ---------------------------------------------------------------------------
# Static assets (inlined as Python strings to keep everything in one module)
# ---------------------------------------------------------------------------

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cookimport – Lifetime Stats Dashboard</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header id="dash-header">
  <h1>cookimport Stats Dashboard</h1>
  <p id="header-subtitle">All-method runs, latest benchmark diagnostics, and history.</p>
  <div id="header-meta"></div>
</header>

<main>
  __ALL_METHOD_SECTION__

  <section id="diagnostics-section">
    <h2>Diagnostics (Latest Benchmark)</h2>
    <p class="section-note">Deep quality views for the most recent benchmark evaluation.</p>
    <div class="diagnostics-grid">
      <section id="per-label-section" class="diagnostic-card">
        <h2>Per-Label Breakdown (Latest Benchmark)</h2>
        <table id="per-label-table"><thead><tr>
          <th>Label</th><th>Precision</th><th>Recall</th>
          <th>Gold</th><th>Pred</th>
        </tr></thead><tbody></tbody></table>
      </section>

      <section id="boundary-section" class="diagnostic-card">
        <h2>Boundary Classification (Latest Benchmark)</h2>
        <div id="boundary-summary"></div>
      </section>
    </div>
  </section>

  <section id="previous-runs-section">
    <h2>Previous Runs</h2>
    <p class="section-note">Timestamp links to the run artifact folder. Scroll for full history.</p>
    <div class="table-wrap table-scroll">
      <table id="previous-runs-table"><thead><tr>
        <th>Timestamp</th><th>Strict Precision</th><th>Strict Recall</th><th>Practical F1</th><th>Strict F1</th>
        <th>Gold</th><th>Matched</th><th>Recipes</th><th>Source</th><th>Importer</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </section>
</main>

<footer>Generated by <code>cookimport stats-dashboard</code></footer>

<script id="dashboard-data-inline" type="application/json">__DASHBOARD_DATA_INLINE__</script>
<script src="assets/dashboard.js"></script>
</body>
</html>
"""

_CSS = """\
:root {
  --bg: #eef2f6;
  --bg-accent: #dde7f1;
  --card: #ffffff;
  --border: #d4dde7;
  --accent: #1f5ea8;
  --accent2: #127a52;
  --accent3: #bb3a2f;
  --text: #18222c;
  --muted: #546372;
  --font: 'IBM Plex Sans', 'Avenir Next', 'Segoe UI', Arial, sans-serif;
  --mono: 'SF Mono', SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
  --focus: #0b72ff;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: var(--font);
  color: var(--text);
  background: linear-gradient(180deg, var(--bg-accent) 0%, var(--bg) 220px, var(--bg) 100%);
  margin: 0;
  padding: 0 1rem 2rem;
  line-height: 1.5;
  min-height: 100vh;
}
a {
  color: var(--accent);
}
a:focus-visible,
button:focus-visible,
select:focus-visible,
input:focus-visible,
summary:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
header {
  padding: 1.5rem 0 0.65rem;
  border-bottom: 2px solid var(--border);
  margin-bottom: 0.8rem;
}
header h1 {
  margin: 0;
  font-size: 1.7rem;
  letter-spacing: 0.015em;
}
#header-subtitle {
  margin: 0.25rem 0 0.45rem;
  color: var(--muted);
  font-size: 0.95rem;
}
#header-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  font-size: 0.83rem;
  color: var(--muted);
}
#header-meta span {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card);
  padding: 0.1rem 0.55rem;
}

#kpi-strip {
  background: transparent;
  border: 0;
  padding: 0;
  margin-bottom: 1rem;
}
#kpi-strip h2 {
  margin: 0 0 0.45rem;
  font-size: 0.96rem;
  letter-spacing: 0.06em;
  color: var(--muted);
  text-transform: uppercase;
}
#kpi-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.65rem;
}
.kpi-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card);
  padding: 0.7rem 0.8rem;
}
.kpi-label {
  color: var(--muted);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
}
.kpi-value {
  display: block;
  margin-top: 0.2rem;
  font-family: var(--mono);
  font-size: 1.15rem;
  font-weight: 600;
}
.kpi-detail {
  display: block;
  margin-top: 0.12rem;
  font-size: 0.75rem;
  color: var(--muted);
}

#controls-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.7rem;
  margin-bottom: 1.2rem;
}
#filters {
  display: flex;
  gap: 0.65rem;
  flex-wrap: wrap;
  flex: 1 1 auto;
}
fieldset {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.35rem 0.65rem;
  background: rgba(255, 255, 255, 0.85);
}
legend {
  font-size: 0.73rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  padding: 0 0.28rem;
}
fieldset label {
  margin-right: 0.65rem;
  font-size: 0.83rem;
  cursor: pointer;
}
fieldset button {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.18rem 0.58rem;
  margin-right: 0.22rem;
  cursor: pointer;
  font-size: 0.78rem;
}
fieldset button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

section {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.1rem;
  margin-bottom: 1rem;
}
section h2 {
  margin: 0 0 0.6rem;
  font-size: 1.12rem;
}
section h3 {
  margin: 1rem 0 0.4rem;
  font-size: 0.93rem;
  color: var(--muted);
}
.section-note { margin: 0 0 0.75rem; color: var(--muted); font-size: 0.85rem; }

.chart-container { width: 100%; overflow-x: auto; min-height: 120px; }
.chart-container svg { display: block; }
.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin: 0.2rem 0 0.45rem;
}
.chart-legend-item {
  font-size: 0.78rem;
  color: var(--muted);
}
.chart-legend-dot {
  display: inline-block;
  width: 0.62rem;
  height: 0.62rem;
  border-radius: 999px;
  margin-right: 0.28rem;
  vertical-align: middle;
}

.table-wrap {
  overflow-x: auto;
}

.table-scroll {
  max-height: 12.5rem; /* ~5 visible rows */
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.table-scroll thead th {
  position: sticky;
  top: 0;
  background: var(--card);
  z-index: 1;
}

table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { text-align: left; padding: 0.37rem 0.55rem; border-bottom: 1px solid var(--border); }
th {
  font-weight: 600;
  color: var(--muted);
  font-size: 0.73rem;
  text-transform: uppercase;
  letter-spacing: 0.045em;
}
td.num { text-align: right; font-family: var(--mono); }
td a { color: var(--accent); text-decoration: none; word-break: break-all; }
td a:hover { text-decoration: underline; }
td.warn-note { color: #b45309; font-weight: 600; }
.mismatch-tag {
  color: #b45309;
  font-size: 0.72rem;
  font-weight: 600;
  margin-left: 0.35rem;
}

.inline-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.25rem 0 0.75rem;
  flex-wrap: wrap;
}
.inline-controls label {
  color: var(--muted);
  font-size: 0.85rem;
}
.inline-controls select {
  min-width: 240px;
  max-width: 100%;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.25rem 0.4rem;
  background: var(--card);
  color: var(--text);
}
.control-label {
  color: var(--muted);
  font-size: 0.82rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.chart-mode-controls button {
  border: 1px solid var(--border);
  background: #f6f9fc;
  color: var(--text);
  border-radius: 999px;
  padding: 0.2rem 0.55rem;
  font-size: 0.78rem;
}
.chart-mode-controls button.active {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
}

.table-collapse-global {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin: 0;
  margin-left: auto;
}

.table-collapse-controls {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0.1rem 0 0.55rem;
}
.table-collapse-toggle {
  background: #f6f9fc;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0.2rem 0.62rem;
}
.table-collapse-toggle:hover {
  border-color: #c7d0d9;
}
.table-collapse-status {
  color: var(--muted);
  font-size: 0.78rem;
}

.empty-note { color: var(--muted); font-style: italic; padding: 1rem 0; }

.all-method-quick-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-bottom: 0.7rem;
  position: sticky;
  top: 0.35rem;
  z-index: 4;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(3px);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.35rem 0.45rem;
}
.all-method-quick-nav a {
  text-decoration: none;
  font-size: 0.76rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.1rem 0.42rem;
  color: var(--muted);
}
.all-method-quick-nav a:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.section-details {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 0.7rem;
  background: #f8fbfe;
}
.section-details > summary {
  cursor: pointer;
  list-style: none;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--muted);
  padding: 0.42rem 0.6rem;
}
.section-details > summary::-webkit-details-marker {
  display: none;
}
.section-details > summary::before {
  content: "+";
  display: inline-block;
  margin-right: 0.34rem;
}
.section-details[open] > summary::before {
  content: "-";
}
.section-details > section {
  margin: 0;
  border: 0;
  border-top: 1px solid var(--border);
  border-radius: 0;
  background: transparent;
}

.summary-compact th,
.summary-compact td {
  padding: 0.3rem 0.5rem;
}
.summary-compact th {
  font-size: 0.74rem;
}

.metric-chart-block {
  margin-top: 0.85rem;
}
.metric-chart-block h3 {
  margin: 0 0 0.45rem;
  color: var(--text);
  font-size: 0.92rem;
}
.metric-chart-grid {
  display: grid;
  gap: 0.28rem;
}
.metric-bar-row {
  display: grid;
  grid-template-columns: 3.5rem minmax(220px, 1fr) 4.5rem;
  align-items: center;
  gap: 0.5rem;
}
.metric-bar-label {
  color: var(--muted);
  font-size: 0.76rem;
  font-family: var(--mono);
}
.metric-bar-track {
  display: block;
  width: 100%;
  background: #edf0f2;
  border-radius: 6px;
  height: 0.65rem;
  overflow: hidden;
}
.metric-bar-fill {
  display: block;
  height: 100%;
  background: var(--accent);
}
.metric-bar-fill-missing {
  background: #c5cdd5;
}
.metric-bar-value {
  text-align: right;
  font-family: var(--mono);
  font-size: 0.75rem;
}

.metric-radar-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.75rem;
}
.metric-radar-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.55rem;
  background: var(--card);
}
.metric-radar-card h4 {
  margin: 0 0 0.4rem;
  color: var(--text);
  font-size: 0.78rem;
  font-family: var(--mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.metric-radar-svg {
  width: 100%;
  height: auto;
  display: block;
}
.metric-radar-ring {
  fill: none;
  stroke: #d5dde5;
  stroke-width: 1;
}
.metric-radar-axis {
  stroke: #c2ccd7;
  stroke-width: 1;
}
.metric-radar-axis-label {
  fill: var(--muted);
  font-size: 7px;
  font-family: var(--mono);
}
.metric-radar-shape {
  fill: rgba(37, 99, 235, 0.22);
  stroke: var(--accent);
  stroke-width: 2;
}
.metric-radar-point {
  fill: var(--accent);
}
.metric-radar-values {
  margin-top: 0.45rem;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.15rem 0.55rem;
}
.metric-radar-value-label {
  color: var(--muted);
  font-size: 0.72rem;
}
.metric-radar-value-number {
  text-align: right;
  font-family: var(--mono);
  font-size: 0.72rem;
}

.diagnostics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 0.7rem;
}
.diagnostic-card {
  margin: 0;
  background: #f8fbfe;
}

footer { text-align: center; color: var(--muted); font-size: 0.78rem; margin-top: 1.3rem; }

@media (max-width: 1100px) {
  #controls-bar {
    align-items: stretch;
  }
  .table-collapse-global {
    margin-left: 0;
  }
}

@media (max-width: 900px) {
  body {
    padding: 0 0.55rem 1.4rem;
  }
  header h1 {
    font-size: 1.38rem;
  }
  #header-subtitle {
    font-size: 0.88rem;
  }
  section {
    padding: 0.82rem;
  }
  #recent-runs th:nth-child(7),
  #recent-runs td:nth-child(7),
  #recent-runs th:nth-child(8),
  #recent-runs td:nth-child(8),
  #recent-runs th:nth-child(10),
  #recent-runs td:nth-child(10),
  #recent-runs th:nth-child(11),
  #recent-runs td:nth-child(11),
  #file-trend-table th:nth-child(6),
  #file-trend-table td:nth-child(6),
  #file-trend-table th:nth-child(7),
  #file-trend-table td:nth-child(7),
  #file-trend-table th:nth-child(9),
  #file-trend-table td:nth-child(9),
  #file-trend-table th:nth-child(10),
  #file-trend-table td:nth-child(10),
  #benchmark-table th:nth-child(6),
  #benchmark-table td:nth-child(6),
  #benchmark-table th:nth-child(7),
  #benchmark-table td:nth-child(7),
  #benchmark-table th:nth-child(11),
  #benchmark-table td:nth-child(11),
  #benchmark-table th:nth-child(12),
  #benchmark-table td:nth-child(12) {
    display: none;
  }
  .all-method-quick-nav {
    position: static;
  }
}

@media (max-width: 620px) {
  #kpi-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metric-bar-row {
    grid-template-columns: 3.2rem minmax(90px, 1fr) 3.8rem;
  }
}
"""

_JS = """\
(function () {
  "use strict";

  let DATA = null;
  let activeCategories = new Set(["stage_import", "benchmark_eval"]);
  let activeExtractors = new Set();
  let activeDays = 0; // 0 = all
  let selectedFileTrend = "";
  let throughputScaleMode = "clamp95";
  const TABLE_COLLAPSE_DEFAULT_ROWS = {
    "recent-runs": 8,
    "file-trend-table": 8,
    "benchmark-table": 12,
  };
  const THROUGHPUT_SCALE_NOTES = {
    raw: "Raw sec/recipe values.",
    clamp95: "Values above the 95th percentile are clamped to keep day-to-day runs readable.",
    log: "Log scale (log10(sec/recipe + 1)) keeps large spikes visible without flattening small runs.",
  };
  const tableCollapsedState = Object.create(null);

  // ---- Load data ----
  function showLoadError(msg) {
    document.querySelector("main").innerHTML =
      '<p class="empty-note">' + msg + "</p>";
  }

  function loadInlineData() {
    const inline = document.getElementById("dashboard-data-inline");
    if (!inline) return null;
    const raw = (inline.textContent || "").trim();
    if (!raw) return null;
    return JSON.parse(raw);
  }

  function loadFromFetch(previousError) {
    fetch("assets/dashboard_data.json")
      .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(d => { DATA = d; init(); })
      .catch(e => {
        if (previousError) {
          showLoadError("Failed to load dashboard data: " + previousError + "; " + e);
          return;
        }
        showLoadError("Failed to load dashboard_data.json: " + e);
      });
  }

  try {
    const inlineData = loadInlineData();
    if (inlineData) {
      DATA = inlineData;
      init();
    } else {
      loadFromFetch(null);
    }
  } catch (e) {
    loadFromFetch(e);
  }

  function init() {
    renderHeader();
    renderAll();
  }

  // ---- Header ----
  function renderHeader() {
    const m = document.getElementById("header-meta");
    const s = DATA.summary;
    const parts = [];
    parts.push("<span>Generated: " + DATA.generated_at.replace("T", " ").slice(0, 19) + "</span>");
    parts.push("<span>Stage records: " + s.total_stage_records + "</span>");
    parts.push("<span>Benchmark records: " + s.total_benchmark_records + "</span>");
    parts.push("<span>Total recipes: " + s.total_recipes + "</span>");
    if (s.total_runtime_seconds != null)
      parts.push("<span>Total runtime: " + s.total_runtime_seconds.toFixed(1) + "s</span>");
    m.innerHTML = parts.join("");
  }

  // ---- Filters ----
  function setupFilters() {
    const cf = document.getElementById("category-filters");
    const cats = [
      ["stage_import", "Stage imports", true],
      ["benchmark_eval", "Benchmarks", true],
      ["labelstudio_import", "Label Studio imports", false],
      ["benchmark_prediction", "Benchmark predictions", false],
    ];
    cats.forEach(([val, lbl, checked]) => {
      const id = "cat-" + val;
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.checked = checked; cb.value = val; cb.id = id;
      if (checked) activeCategories.add(val);
      cb.addEventListener("change", () => {
        if (cb.checked) activeCategories.add(val); else activeCategories.delete(val);
        renderAll();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(" " + lbl));
      cf.appendChild(label);
    });

    document.querySelectorAll("#date-filters button").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#date-filters button").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activeDays = parseInt(btn.dataset.days, 10);
        renderAll();
      });
    });
  }

  function setupExtractorFilters() {
    const ef = document.getElementById("extractor-filters");
    if (!ef) return;
    ef.innerHTML = "";
    const extractors = Array.from(
      new Set(
        (DATA.stage_records || [])
          .map(record => epubExtractorEffective(record) || epubExtractorRequested(record))
          .filter(Boolean)
      )
    ).sort((a, b) => a.localeCompare(b));

    activeExtractors = new Set(extractors);
    if (extractors.length === 0) {
      const note = document.createElement("span");
      note.className = "empty-note";
      note.textContent = "No EPUB extractor data";
      ef.appendChild(note);
      return;
    }

    extractors.forEach(extractor => {
      const id = "extractor-" + extractor;
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.value = extractor;
      cb.id = id;
      cb.addEventListener("change", () => {
        if (cb.checked) activeExtractors.add(extractor);
        else activeExtractors.delete(extractor);
        renderAll();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(" " + extractor));
      ef.appendChild(label);
    });
  }

  function setupThroughputModeControls() {
    const root = document.getElementById("throughput-mode-controls");
    if (!root) return;
    root.querySelectorAll("button[data-mode]").forEach(btn => {
      if (!btn.dataset.bound) {
        btn.addEventListener("click", () => {
          throughputScaleMode = btn.dataset.mode || "clamp95";
          root.querySelectorAll("button[data-mode]").forEach(other => {
            other.classList.toggle("active", other === btn);
          });
          renderThroughput();
        });
        btn.dataset.bound = "1";
      }
    });
  }

  // ---- Filtering helpers ----
  function parseTs(ts) {
    if (ts == null) return null;
    const text = String(ts).trim();
    if (!text) return null;

    // Parse canonical timestamp forms explicitly to avoid browser Date.parse quirks:
    // YYYY-MM-DD_HH.MM.SS and YYYY-MM-DDTHH:MM:SS
    const m = text.match(/^(\\d{4})-(\\d{2})-(\\d{2})[T_](\\d{2})[.:](\\d{2})[.:](\\d{2})$/);
    if (m) {
      const d = new Date(
        Number(m[1]),
        Number(m[2]) - 1,
        Number(m[3]),
        Number(m[4]),
        Number(m[5]),
        Number(m[6]),
      );
      return isNaN(d.getTime()) ? null : d;
    }

    // Fallback for ISO strings with timezone offsets.
    const normalized = text.replace(/_(\\d{2})[.:](\\d{2})[.:](\\d{2})$/, "T$1:$2:$3");
    const d = new Date(normalized);
    return isNaN(d.getTime()) ? null : d;
  }

  function compareRunTimestampAsc(aTs, bTs) {
    const a = parseTs(aTs);
    const b = parseTs(bTs);
    if (a && b) return a - b;
    if (a) return -1;
    if (b) return 1;
    return (aTs || "").localeCompare(bTs || "");
  }

  function compareRunTimestampDesc(aTs, bTs) {
    return compareRunTimestampAsc(bTs, aTs);
  }

  function isRecent(ts) {
    if (activeDays === 0) return true;
    const d = parseTs(ts);
    if (!d) return true;
    const cutoff = new Date(Date.now() - activeDays * 86400000);
    return d >= cutoff;
  }

  function filteredStage() {
    return DATA.stage_records.filter(r =>
      activeCategories.has(r.run_category) &&
      isRecent(r.run_timestamp) &&
      stagePassesExtractorFilter(r)
    );
  }

  function filteredBenchmarks() {
    return DATA.benchmark_records.filter(r =>
      activeCategories.has(r.run_category) && isRecent(r.run_timestamp)
    );
  }

  function stagePassesExtractorFilter(record) {
    const extractor = epubExtractorEffective(record) || epubExtractorRequested(record);
    if (!extractor) return true;
    if (activeExtractors.size === 0) return false;
    return activeExtractors.has(extractor);
  }

  // ---- Render all sections ----
  function renderAll() {
    renderPreviousRuns();
    renderPerLabel();
    renderBoundary();
  }

  function setAllTableCollapsedState(collapsed) {
    Object.keys(TABLE_COLLAPSE_DEFAULT_ROWS).forEach(tableId => {
      tableCollapsedState[tableId] = collapsed;
    });
  }

  function setupGlobalCollapseControls() {
    const showAllBtn = document.getElementById("show-all-tables");
    const collapseAllBtn = document.getElementById("collapse-all-tables");
    if (!showAllBtn || !collapseAllBtn) return;

    if (!showAllBtn.dataset.bound) {
      showAllBtn.addEventListener("click", () => {
        setAllTableCollapsedState(false);
        renderAll();
      });
      showAllBtn.dataset.bound = "1";
    }

    if (!collapseAllBtn.dataset.bound) {
      collapseAllBtn.addEventListener("click", () => {
        setAllTableCollapsedState(true);
        renderAll();
      });
      collapseAllBtn.dataset.bound = "1";
    }
  }

  function renderRowsWithCollapse(options) {
    const table = document.getElementById(options.tableId);
    if (!table) return;
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    const rows = options.rows || [];
    const defaultVisible = options.defaultVisible || 10;
    const canCollapse = rows.length > defaultVisible;

    if (canCollapse && typeof tableCollapsedState[options.tableId] !== "boolean") {
      tableCollapsedState[options.tableId] = true;
    }

    const collapsed = canCollapse ? tableCollapsedState[options.tableId] : false;
    const visibleRows = collapsed ? rows.slice(0, defaultVisible) : rows;
    visibleRows.forEach(row => {
      const tr = options.renderRow(row);
      if (tr) tbody.appendChild(tr);
    });

    renderTableCollapseControl({
      tableId: options.tableId,
      canCollapse,
      collapsed,
      totalRows: rows.length,
      defaultVisible,
      label: options.label || "rows",
      rerender: options.rerender,
    });
  }

  function renderTableCollapseControl(options) {
    const table = document.getElementById(options.tableId);
    if (!table || !table.parentNode) return;
    const controlId = "collapse-control-" + options.tableId;
    let control = document.getElementById(controlId);
    if (!control) {
      control = document.createElement("div");
      control.id = controlId;
      control.className = "table-collapse-controls";
      control.innerHTML =
        '<button type="button" class="table-collapse-toggle"></button>' +
        '<span class="table-collapse-status"></span>';
      table.parentNode.insertBefore(control, table);
    }

    if (!options.canCollapse) {
      control.style.display = "none";
      return;
    }

    control.style.display = "";
    const button = control.querySelector("button");
    const status = control.querySelector(".table-collapse-status");
    button.textContent = options.collapsed
      ? "Show all " + options.totalRows
      : "Show fewer";
    status.textContent = options.collapsed
      ? "Showing first " + Math.min(options.defaultVisible, options.totalRows) + " of " + options.totalRows + " " + options.label
      : "Showing all " + options.totalRows + " " + options.label;
    button.onclick = function () {
      tableCollapsedState[options.tableId] = !options.collapsed;
      options.rerender();
    };
  }

  // ---- Stats helpers ----
  function mean(values) {
    if (!values.length) return null;
    return values.reduce((acc, v) => acc + v, 0) / values.length;
  }

  function median(values) {
    if (!values.length) return null;
    const ordered = [...values].sort((a, b) => a - b);
    const mid = Math.floor(ordered.length / 2);
    if (ordered.length % 2 === 1) return ordered[mid];
    return (ordered[mid - 1] + ordered[mid]) / 2;
  }

  function percentile(values, pct) {
    if (!values.length) return null;
    const ordered = [...values].sort((a, b) => a - b);
    const rank = (Math.max(0, Math.min(100, pct)) / 100) * (ordered.length - 1);
    const lower = Math.floor(rank);
    const upper = Math.ceil(rank);
    if (lower === upper) return ordered[lower];
    const weight = rank - lower;
    return ordered[lower] * (1 - weight) + ordered[upper] * weight;
  }

  function fmtMaybe(value, digits) {
    if (value == null || Number.isNaN(value)) return "-";
    return Number(value).toFixed(digits);
  }

  function latestTimestampLabel(records) {
    let latest = null;
    records.forEach(record => {
      const ts = parseTs(record.run_timestamp);
      if (!ts) return;
      if (latest == null || ts > latest) latest = ts;
    });
    if (!latest) return "-";
    const yr = latest.getFullYear();
    const mo = String(latest.getMonth() + 1).padStart(2, "0");
    const dy = String(latest.getDate()).padStart(2, "0");
    const hh = String(latest.getHours()).padStart(2, "0");
    const mm = String(latest.getMinutes()).padStart(2, "0");
    return yr + "-" + mo + "-" + dy + " " + hh + ":" + mm;
  }

  function renderKpis() {
    const host = document.getElementById("kpi-cards");
    if (!host) return;
    const stage = filteredStage();
    const benchmarks = filteredBenchmarks();
    const perRecipeValues = stage
      .map(r => r.per_recipe_seconds)
      .filter(v => v != null && Number.isFinite(v));
    const strictValues = benchmarks
      .map(r => r.f1)
      .filter(v => v != null && Number.isFinite(v));
    const practicalValues = benchmarks
      .map(r => r.practical_f1)
      .filter(v => v != null && Number.isFinite(v));
    const medianPerRecipe = median(perRecipeValues);
    const strictMean = mean(strictValues);
    const practicalMean = mean(practicalValues);
    const latestLabel = latestTimestampLabel(stage.concat(benchmarks));

    const cards = [
      {
        label: "Stage rows",
        value: String(stage.length),
        detail: stage.length ? "filtered rows" : "no visible rows",
      },
      {
        label: "Median sec/recipe",
        value: fmtMaybe(medianPerRecipe, 3),
        detail: perRecipeValues.length + " runs with timing",
      },
      {
        label: "Mean strict F1",
        value: strictMean == null ? "-" : (strictMean * 100).toFixed(1) + "%",
        detail: "practical " + (practicalMean == null ? "-" : (practicalMean * 100).toFixed(1) + "%"),
      },
      {
        label: "Latest run",
        value: latestLabel,
        detail: benchmarks.length + " benchmark rows",
      },
    ];
    host.innerHTML = cards.map(card =>
      '<article class="kpi-card">' +
        '<span class="kpi-label">' + esc(card.label) + '</span>' +
        '<span class="kpi-value">' + esc(card.value) + '</span>' +
        '<span class="kpi-detail">' + esc(card.detail) + '</span>' +
      '</article>'
    ).join("");
  }

  // ---- SVG line chart helper ----
  function svgLineChart(seriesList, opts) {
    const w = opts.width || 700;
    const h = opts.height || 160;
    const pad = { top: 20, right: 20, bottom: 32, left: 58 };
    const iw = w - pad.left - pad.right;
    const ih = h - pad.top - pad.bottom;

    const usableSeries = (seriesList || []).map(s => ({
      name: s.name || "",
      color: s.color || "#0d6efd",
      points: (s.points || []).filter(p => p && p.x && p.y != null),
    })).filter(s => s.points.length > 0);
    if (!usableSeries.length) return '<p class="empty-note">No data points for chart.</p>';

    const allPoints = usableSeries.flatMap(s => s.points);
    const xs = allPoints.map(p => p.x.getTime());
    const ys = allPoints.map(p => p.y);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    let yMin = opts.yMin != null ? opts.yMin : Math.min(...ys);
    let yMax = opts.yMax != null ? opts.yMax : Math.max(...ys);
    if (opts.includeZero) {
      yMin = Math.min(0, yMin);
    }
    if (yMax === yMin) {
      yMax = yMin + 1;
    }
    const yPad = (yMax - yMin) * 0.08;
    if (!opts.yMax) yMax += yPad;
    if (!opts.yMin) yMin = Math.max(0, yMin - yPad);

    function sx(v) { return pad.left + (xMax === xMin ? iw / 2 : (v - xMin) / (xMax - xMin) * iw); }
    function sy(v) { return pad.top + ih - (yMax === yMin ? ih / 2 : (v - yMin) / (yMax - yMin) * ih); }

    let svg = '<svg width="' + w + '" height="' + h + '" xmlns="http://www.w3.org/2000/svg">';

    const yTickFormatter = opts.yTickFormatter || (v => v.toFixed(2));
    const yTicks = opts.yTicks || 4;
    for (let i = 0; i <= yTicks; i++) {
      const v = yMin + (yMax - yMin) * i / yTicks;
      const y = sy(v);
      svg += '<line x1="' + pad.left + '" y1="' + y + '" x2="' + (w - pad.right) + '" y2="' + y + '" stroke="#e9ecef" stroke-width="1"/>';
      svg += '<text x="' + (pad.left - 5) + '" y="' + (y + 4) + '" text-anchor="end" font-size="10" fill="#6c757d">' + esc(yTickFormatter(v)) + '</text>';
    }

    if (opts.yLabel) {
      svg += '<text x="12" y="' + (pad.top + ih / 2) + '" text-anchor="middle" font-size="11" fill="#6c757d" transform="rotate(-90, 12, ' + (pad.top + ih / 2) + ')">' + esc(opts.yLabel) + '</text>';
    }

    svg += '<line x1="' + pad.left + '" y1="' + (h - pad.bottom) + '" x2="' + (w - pad.right) + '" y2="' + (h - pad.bottom) + '" stroke="#d6dee8" stroke-width="1"/>';
    const midTs = xMin + ((xMax - xMin) / 2);
    const xTickValues = [xMin, midTs, xMax];
    xTickValues.forEach(ts => {
      const x = sx(ts);
      const d = new Date(ts);
      const label = String(d.getFullYear()) + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
      svg += '<text x="' + x + '" y="' + (h - pad.bottom + 14) + '" text-anchor="middle" font-size="10" fill="#6c757d">' + label + '</text>';
    });

    usableSeries.forEach(series => {
      const ordered = [...series.points].sort((a, b) => a.x - b.x);
      const linePoints = ordered.map(p => sx(p.x.getTime()) + "," + sy(p.y)).join(" ");
      svg += '<polyline fill="none" stroke="' + series.color + '" stroke-width="2.25" points="' + linePoints + '"/>';
      ordered.forEach(point => {
        const cx = sx(point.x.getTime());
        const cy = sy(point.y);
        svg += '<circle cx="' + cx + '" cy="' + cy + '" r="3.1" fill="' + series.color + '">';
        svg += '<title>' + esc(point.label || "") + '</title></circle>';
      });
    });

    svg += '</svg>';
    return svg;
  }

  // ---- Throughput section ----
  function renderThroughput() {
    const records = filteredStage();
    const section = document.getElementById("throughput-section");
    if (records.length === 0) {
      section.innerHTML = '<h2>Stage / Import Throughput</h2><p class="empty-note">No stage/import records found. Run <code>cookimport perf-report</code> to generate performance history.</p>';
      return;
    }

    const scaleNote = document.getElementById("throughput-scale-note");
    if (scaleNote) {
      scaleNote.textContent = THROUGHPUT_SCALE_NOTES[throughputScaleMode] || THROUGHPUT_SCALE_NOTES.clamp95;
    }

    const chartDiv = document.getElementById("throughput-chart");
    const rawPoints = records
      .filter(r => r.per_recipe_seconds != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        rawY: r.per_recipe_seconds,
        label: r.file_name + ": " + r.per_recipe_seconds.toFixed(3) + " sec/recipe"
      }))
      .filter(p => p.x)
      .sort((a, b) => a.x - b.x);

    const rawValues = rawPoints.map(point => point.rawY);
    const clamp95 = percentile(rawValues, 95);
    const chartPoints = rawPoints.map(point => {
      let y = point.rawY;
      if (throughputScaleMode === "clamp95" && clamp95 != null) {
        y = Math.min(point.rawY, clamp95);
      } else if (throughputScaleMode === "log") {
        y = Math.log10(point.rawY + 1);
      }
      return {
        x: point.x,
        y,
        label: point.label,
      };
    });
    chartDiv.innerHTML = svgLineChart(
      [
        {
          name: "sec/recipe",
          color: "#1f5ea8",
          points: chartPoints,
        },
      ],
      {
        width: Math.min(920, Math.max(400, chartPoints.length * 30)),
        height: 170,
        yLabel: throughputScaleMode === "log" ? "log10(sec/recipe + 1)" : "sec / recipe",
        includeZero: throughputScaleMode !== "log",
      }
    );

    const recentRuns = [...records]
      .sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    renderRowsWithCollapse({
      tableId: "recent-runs",
      rows: recentRuns,
      defaultVisible: TABLE_COLLAPSE_DEFAULT_ROWS["recent-runs"],
      label: "runs",
      rerender: renderThroughput,
      renderRow: r => {
        const tr = document.createElement("tr");
        tr.innerHTML =
          '<td>' + esc(r.run_timestamp || "") + '</td>' +
          '<td>' + esc(r.file_name) + '</td>' +
          '<td>' + esc(r.importer_name || "-") + '</td>' +
          '<td class="num">' + (r.total_seconds != null ? r.total_seconds.toFixed(2) : "-") + '</td>' +
          '<td class="num">' + (r.recipes != null ? r.recipes : "-") + '</td>' +
          '<td class="num">' + (r.per_recipe_seconds != null ? r.per_recipe_seconds.toFixed(3) : "-") + '</td>' +
          extractorCells(r) +
          autoScoreCell(r) +
          runConfigCell(r) +
          '<td><a href="' + esc(r.artifact_dir || "") + '">' + esc(shortPath(r.artifact_dir)) + '</a></td>';
        return tr;
      },
    });

    const fileSelect = document.getElementById("file-trend-select");
    const fileNames = Array.from(new Set(records.map(r => r.file_name).filter(Boolean)))
      .sort((a, b) => a.localeCompare(b));

    if (!fileNames.includes(selectedFileTrend)) {
      selectedFileTrend = fileNames[0] || "";
    }

    const nextOptions = fileNames.map(name =>
      '<option value="' + esc(name) + '"' + (name === selectedFileTrend ? " selected" : "") + '>' + esc(name) + "</option>"
    ).join("");
    if (fileSelect.innerHTML !== nextOptions) {
      fileSelect.innerHTML = nextOptions;
    }

    if (!fileSelect.dataset.bound) {
      fileSelect.addEventListener("change", () => {
        selectedFileTrend = fileSelect.value;
        renderThroughput();
      });
      fileSelect.dataset.bound = "1";
    }

    const fileRecords = records
      .filter(r => r.file_name === selectedFileTrend)
      .sort((a, b) => compareRunTimestampAsc(a.run_timestamp, b.run_timestamp));

    const filePoints = fileRecords
      .filter(r => r.total_seconds != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.total_seconds,
        label: (r.run_timestamp || "") + " " + selectedFileTrend + " total=" + r.total_seconds.toFixed(3) + "s"
      }))
      .sort((a, b) => a.x - b.x);

    const fileChart = document.getElementById("file-trend-chart");
    fileChart.innerHTML = svgLineChart(
      [
        {
          name: "total seconds",
          color: "#127a52",
          points: filePoints,
        },
      ],
      {
        width: Math.min(920, Math.max(400, filePoints.length * 48)),
        height: 165,
        yLabel: "total sec",
        includeZero: true,
      }
    );

    const fileRows = [...fileRecords]
      .sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    renderRowsWithCollapse({
      tableId: "file-trend-table",
      rows: fileRows,
      defaultVisible: TABLE_COLLAPSE_DEFAULT_ROWS["file-trend-table"],
      label: "runs",
      rerender: renderThroughput,
      renderRow: r => {
        const tr = document.createElement("tr");
        tr.innerHTML =
          '<td>' + esc(r.run_timestamp || "") + '</td>' +
          '<td class="num">' + (r.total_seconds != null ? r.total_seconds.toFixed(2) : "-") + '</td>' +
          '<td class="num">' + (r.per_recipe_seconds != null ? r.per_recipe_seconds.toFixed(3) : "-") + '</td>' +
          '<td class="num">' + (r.recipes != null ? r.recipes : "-") + '</td>' +
          '<td>' + esc(r.importer_name || "-") + '</td>' +
          extractorCells(r) +
          autoScoreCell(r) +
          runConfigCell(r) +
          '<td><a href="' + esc(r.artifact_dir || "") + '">' + esc(shortPath(r.artifact_dir)) + '</a></td>';
        return tr;
      },
    });
  }

  // ---- Benchmark section ----
  function renderBenchmarks() {
    const records = filteredBenchmarks();
    const section = document.getElementById("benchmark-section");
    if (records.length === 0) {
      section.innerHTML = '<h2>Benchmark Evaluations</h2><p class="empty-note">No benchmark evaluation records found. Run an eval workflow to generate eval_report.json files.</p>';
      return;
    }

    const legend = document.getElementById("benchmark-legend");
    if (legend) {
      legend.innerHTML = (
        '<span class="chart-legend-item"><span class="chart-legend-dot" style="background:#127a52"></span>Strict Recall</span>' +
        '<span class="chart-legend-item"><span class="chart-legend-dot" style="background:#1f5ea8"></span>Strict Precision</span>'
      );
    }

    const chartDiv = document.getElementById("benchmark-chart");
    const rPoints = records
      .filter(r => r.recall != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.recall,
        label: (r.run_timestamp || "") + " recall=" + (r.recall != null ? r.recall.toFixed(4) : "?")
      }))
      .sort((a, b) => a.x - b.x);

    const pPoints = records
      .filter(r => r.precision != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.precision,
        label: (r.run_timestamp || "") + " precision=" + (r.precision != null ? r.precision.toFixed(4) : "?")
      }))
      .sort((a, b) => a.x - b.x);

    chartDiv.innerHTML = svgLineChart(
      [
        { name: "Strict Recall", color: "#127a52", points: rPoints },
        { name: "Strict Precision", color: "#1f5ea8", points: pPoints },
      ],
      {
        width: Math.min(920, Math.max(400, Math.max(rPoints.length, pPoints.length) * 38)),
        height: 182,
        yLabel: "score",
        yMin: 0,
        yMax: 1,
      }
    );

    const sorted = [...records].sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    renderRowsWithCollapse({
      tableId: "benchmark-table",
      rows: sorted,
      defaultVisible: TABLE_COLLAPSE_DEFAULT_ROWS["benchmark-table"],
      label: "benchmarks",
      rerender: renderBenchmarks,
      renderRow: r => {
        const sourceLabel = basename(r.source_file || "");
        const configSummary = runConfigSummary(r);
        const configRaw = r.run_config ? JSON.stringify(r.run_config) : "";
        const processedReportLink = r.processed_report_path
          ? ' <a href="' + esc(r.processed_report_path) + '" title="' + esc(r.processed_report_path) + '">report</a>'
          : "";
        const mismatchTag = r.granularity_mismatch_likely
          ? ' <span class="mismatch-tag" title="Strict IoU is low while practical overlap is high.">mismatch</span>'
          : "";
        const tr = document.createElement("tr");
        tr.innerHTML =
          '<td>' + esc(r.run_timestamp || "") + '</td>' +
          '<td class="num">' + fmt4(r.precision) + '</td>' +
          '<td class="num">' + fmt4(r.recall) + '</td>' +
          '<td class="num">' + fmt4(r.practical_f1) + '</td>' +
          '<td class="num">' + fmt4(r.f1) + mismatchTag + '</td>' +
          '<td class="num">' + (r.gold_total != null ? r.gold_total : "-") + '</td>' +
          '<td class="num">' + (r.gold_matched != null ? r.gold_matched : "-") + '</td>' +
          '<td class="num">' + (r.recipes != null ? r.recipes : "-") + '</td>' +
          '<td title="' + esc(r.source_file || "") + '">' + esc(sourceLabel || "-") + '</td>' +
          '<td>' + esc(r.importer_name || "-") + '</td>' +
          '<td title="' + esc(configRaw) + '">' + esc(configSummary || "-") + '</td>' +
          '<td><a href="' + esc(r.artifact_dir || "") + '">' + esc(shortPath(r.artifact_dir)) + '</a>' + processedReportLink + '</td>';
        return tr;
      },
    });
  }

  // ---- Previous runs section ----
  function renderPreviousRuns() {
    const records = filteredBenchmarks();
    const section = document.getElementById("previous-runs-section");
    const table = document.getElementById("previous-runs-table");
    if (!section || !table) return;
    const tbody = table.querySelector("tbody");
    if (!tbody) return;

    if (records.length === 0) {
      section.innerHTML = '<h2>Previous Runs</h2><p class="empty-note">No benchmark evaluation records found. Run an eval workflow to generate eval_report.json files.</p>';
      return;
    }

    const ALL_METHOD_SEGMENT = "all-method-benchmark";
    const ALL_METHOD_CONFIG_PREFIX = "config_";

    function normalizePathParts(pathValue) {
      if (pathValue == null) return { prefix: "", parts: [] };
      const raw = String(pathValue).trim().replace(/\\\\/g, "/");
      if (!raw) return { prefix: "", parts: [] };
      const prefix = raw.startsWith("/") ? "/" : "";
      const parts = raw.split("/").filter(p => p && p !== ".");
      return { prefix, parts };
    }

    function allMethodRunInfo(record) {
      const artifactDir = record ? record.artifact_dir : null;
      const info = normalizePathParts(artifactDir);
      if (info.parts.length < 3) return null;
      const lower = info.parts.map(p => String(p).toLowerCase());
      for (let idx = 0; idx < lower.length; idx++) {
        if (lower[idx] !== ALL_METHOD_SEGMENT) continue;
        if (idx + 2 >= info.parts.length) continue;
        const sourceSlug = info.parts[idx + 1];
        const configDir = info.parts[idx + 2];
        if (!String(configDir).startsWith(ALL_METHOD_CONFIG_PREFIX)) continue;
        const runDirTimestamp = idx > 0 ? info.parts[idx - 1] : null;
        const runRootDir = info.prefix + info.parts.slice(0, idx + 1).join("/");
        const groupDir = info.prefix + info.parts.slice(0, idx + 2).join("/");
        return {
          runKey: runRootDir || groupDir,
          groupKey: groupDir,
          runDirTimestamp,
          configDir: String(configDir),
          sourceSlug: String(sourceSlug),
        };
      }
      return null;
    }

    function slugToken(value) {
      const token = String(value || "")
        .trim()
        .replace(/[^a-zA-Z0-9._-]+/g, "_")
        .replace(/^[._-]+|[._-]+$/g, "");
      return token || "unknown";
    }

    function metric(value) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function aggregateConfigKey(record, configDir) {
      const hash = String(record.run_config_hash || "").trim().toLowerCase();
      if (hash) return "hash:" + hash;
      return "name:" + String(configDir || "");
    }

    function bestRecord(recordsForGroup) {
      if (!recordsForGroup.length) return null;
      let best = recordsForGroup[0];
      recordsForGroup.slice(1).forEach(next => {
        const bestKey = [
          metric(best.f1),
          metric(best.practical_f1),
          metric(best.precision),
          metric(best.recall),
        ];
        const nextKey = [
          metric(next.f1),
          metric(next.practical_f1),
          metric(next.precision),
          metric(next.recall),
        ];
        for (let i = 0; i < bestKey.length; i++) {
          if (nextKey[i] > bestKey[i]) { best = next; return; }
          if (nextKey[i] < bestKey[i]) return;
        }
      });
      return best;
    }

    function mostCommonValue(counts) {
      let best = null;
      let bestCount = -1;
      Object.keys(counts).forEach(key => {
        const count = counts[key] || 0;
        if (count > bestCount) {
          best = key;
          bestCount = count;
        }
      });
      return best;
    }

    const singleRows = [];
    const allMethodRuns = Object.create(null);

    records.forEach(r => {
      const info = allMethodRunInfo(r);
      if (!info) {
        singleRows.push({ type: "single", record: r });
        return;
      }
      let run = allMethodRuns[info.runKey];
      if (!run) {
        run = {
          runKey: info.runKey,
          runDirTimestamp: info.runDirTimestamp,
          groups: Object.create(null),
        };
        allMethodRuns[info.runKey] = run;
      }
      if (!run.runDirTimestamp && info.runDirTimestamp) {
        run.runDirTimestamp = info.runDirTimestamp;
      }
      let group = run.groups[info.groupKey];
      if (!group) {
        group = { groupKey: info.groupKey, records: [] };
        run.groups[info.groupKey] = group;
      }
      group.records.push({ record: r, configDir: info.configDir });
    });

    function summarizeAllMethodRun(run) {
      const groups = Object.keys(run.groups).map(k => run.groups[k]);
      if (!groups.length) return null;

      const state = Object.create(null);
      const winsByConfig = Object.create(null);

      groups.forEach(group => {
        const groupRecords = group.records.map(entry => entry.record);
        const winner = bestRecord(groupRecords);
        const winnerInfo = winner ? allMethodRunInfo(winner) : null;
        const winnerKey = (winner && winnerInfo)
          ? aggregateConfigKey(winner, winnerInfo.configDir)
          : null;
        if (winnerKey) {
          winsByConfig[winnerKey] = (winsByConfig[winnerKey] || 0) + 1;
        }

        group.records.forEach(entry => {
          const r = entry.record;
          const configDir = entry.configDir;
          const configKey = aggregateConfigKey(r, configDir);
          let agg = state[configKey];
          if (!agg) {
            agg = {
              configKey,
              configName: configDir,
              groupKeys: new Set(),
              importerCounts: Object.create(null),
              precisionValues: [],
              recallValues: [],
              strictF1Values: [],
              practicalF1Values: [],
              goldTotalSum: 0,
              goldTotalN: 0,
              goldMatchedSum: 0,
              goldMatchedN: 0,
              recipesSum: 0,
              recipesN: 0,
              wins: 0,
            };
            state[configKey] = agg;
          }

          agg.groupKeys.add(group.groupKey);
          const importer = r.importer_name != null ? String(r.importer_name) : "-";
          agg.importerCounts[importer] = (agg.importerCounts[importer] || 0) + 1;
          if (r.precision != null) agg.precisionValues.push(Number(r.precision));
          if (r.recall != null) agg.recallValues.push(Number(r.recall));
          if (r.f1 != null) agg.strictF1Values.push(Number(r.f1));
          if (r.practical_f1 != null) agg.practicalF1Values.push(Number(r.practical_f1));
          if (r.gold_total != null) { agg.goldTotalSum += Number(r.gold_total); agg.goldTotalN += 1; }
          if (r.gold_matched != null) { agg.goldMatchedSum += Number(r.gold_matched); agg.goldMatchedN += 1; }
          if (r.recipes != null) { agg.recipesSum += Number(r.recipes); agg.recipesN += 1; }
        });
      });

      Object.keys(winsByConfig).forEach(key => {
        if (state[key]) state[key].wins = winsByConfig[key];
      });

      const aggregates = Object.keys(state).map(key => {
        const agg = state[key];
        const importer = mostCommonValue(agg.importerCounts) || "-";
        return {
          configKey: agg.configKey,
          configName: agg.configName,
          books: agg.groupKeys.size,
          wins: agg.wins || 0,
          strict_precision_mean: mean(agg.precisionValues),
          strict_recall_mean: mean(agg.recallValues),
          strict_f1_mean: mean(agg.strictF1Values),
          practical_f1_mean: mean(agg.practicalF1Values),
          gold_total: agg.goldTotalN ? agg.goldTotalSum : null,
          gold_matched: agg.goldMatchedN ? agg.goldMatchedSum : null,
          recipes: agg.recipesN ? agg.recipesSum : null,
          importer_name: importer,
        };
      });

      aggregates.sort((a, b) => {
        const aKey = [
          a.books,
          metric(a.practical_f1_mean),
          metric(a.strict_f1_mean),
          a.wins,
          metric(a.strict_precision_mean),
          metric(a.strict_recall_mean),
        ];
        const bKey = [
          b.books,
          metric(b.practical_f1_mean),
          metric(b.strict_f1_mean),
          b.wins,
          metric(b.strict_precision_mean),
          metric(b.strict_recall_mean),
        ];
        for (let i = 0; i < aKey.length; i++) {
          if (bKey[i] !== aKey[i]) return bKey[i] - aKey[i];
        }
        return String(a.configName || "").localeCompare(String(b.configName || ""));
      });

      const best = aggregates.length ? aggregates[0] : null;
      const ts = run.runDirTimestamp || "";
      const fileName = "all-method-benchmark-run__" + slugToken(ts) + ".html";
      const href = "all-method-benchmark/" + fileName;

      return {
        type: "all_method",
        run_timestamp: ts,
        href,
        precision: best ? best.strict_precision_mean : null,
        recall: best ? best.strict_recall_mean : null,
        practical_f1: best ? best.practical_f1_mean : null,
        f1: best ? best.strict_f1_mean : null,
        gold_total: best ? best.gold_total : null,
        gold_matched: best ? best.gold_matched : null,
        recipes: best ? best.recipes : null,
        source: "all-method benchmark run",
        importer_name: best ? best.importer_name : "-",
      };
    }

    const bundledRows = Object.keys(allMethodRuns)
      .map(key => summarizeAllMethodRun(allMethodRuns[key]))
      .filter(Boolean);
    const rows = bundledRows.concat(singleRows.map(item => ({
      type: "single",
      run_timestamp: item.record.run_timestamp || "",
      href: item.record.artifact_dir || "",
      record: item.record,
    })));

    rows.sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    tbody.innerHTML = "";
    rows.forEach(row => {
      const tr = document.createElement("tr");
      if (row.type === "all_method") {
        const ts = row.run_timestamp || "";
        const href = row.href || "";
        const tsCell = href
          ? '<a href="' + esc(href) + '" title="' + esc(href) + '">' + esc(ts) + "</a>"
          : esc(ts);
        tr.innerHTML =
          "<td>" + tsCell + "</td>" +
          '<td class="num">' + fmt4(row.precision) + "</td>" +
          '<td class="num">' + fmt4(row.recall) + "</td>" +
          '<td class="num">' + fmt4(row.practical_f1) + "</td>" +
          '<td class="num">' + fmt4(row.f1) + "</td>" +
          '<td class="num">' + (row.gold_total != null ? row.gold_total : "-") + "</td>" +
          '<td class="num">' + (row.gold_matched != null ? row.gold_matched : "-") + "</td>" +
          '<td class="num">' + (row.recipes != null ? row.recipes : "-") + "</td>" +
          '<td>' + esc(row.source || "-") + "</td>" +
          "<td>" + esc(row.importer_name || "-") + "</td>";
        tbody.appendChild(tr);
        return;
      }

      const r = row.record;
      const sourceLabel = basename(r.source_file || "");
      const ts = r.run_timestamp || "";
      const href = r.artifact_dir || "";
      const tsCell = href
        ? '<a href="' + esc(href) + '" title="' + esc(href) + '">' + esc(ts) + "</a>"
        : esc(ts);
      tr.innerHTML =
        "<td>" + tsCell + "</td>" +
        '<td class="num">' + fmt4(r.precision) + "</td>" +
        '<td class="num">' + fmt4(r.recall) + "</td>" +
        '<td class="num">' + fmt4(r.practical_f1) + "</td>" +
        '<td class="num">' + fmt4(r.f1) + "</td>" +
        '<td class="num">' + (r.gold_total != null ? r.gold_total : "-") + "</td>" +
        '<td class="num">' + (r.gold_matched != null ? r.gold_matched : "-") + "</td>" +
        '<td class="num">' + (r.recipes != null ? r.recipes : "-") + "</td>" +
        '<td title="' + esc(r.source_file || "") + '">' + esc(sourceLabel || "-") + "</td>" +
        "<td>" + esc(r.importer_name || "-") + "</td>";
      tbody.appendChild(tr);
    });
  }

  // ---- Per-label section ----
  function renderPerLabel() {
    const records = filteredBenchmarks();
    const section = document.getElementById("per-label-section");
    if (!section) return;
    if (records.length === 0) {
      section.innerHTML = '<h2>Per-Label Breakdown</h2><p class="empty-note">No benchmark records with per-label data.</p>';
      return;
    }
    const sorted = [...records].sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    const latest = sorted.find(r => r.per_label && r.per_label.length > 0);
    if (!latest) {
      section.innerHTML = '<h2>Per-Label Breakdown</h2><p class="empty-note">No per-label metrics available in benchmark records.</p>';
      return;
    }
    section.querySelector("h2").textContent = "Per-Label Breakdown (" + esc(latest.run_timestamp || "latest") + ")";
    const tbody = document.querySelector("#per-label-table tbody");
    tbody.innerHTML = "";
    latest.per_label.forEach(lbl => {
      const f1 = (lbl.precision != null && lbl.recall != null && (lbl.precision + lbl.recall) > 0)
        ? (2 * lbl.precision * lbl.recall / (lbl.precision + lbl.recall)) : null;
      const tr = document.createElement("tr");
      tr.innerHTML =
        '<td>' + esc(lbl.label) + '</td>' +
        '<td class="num">' + fmt4(lbl.precision) + '</td>' +
        '<td class="num">' + fmt4(lbl.recall) + '</td>' +
        '<td class="num">' + (lbl.gold_total != null ? lbl.gold_total : "-") + '</td>' +
        '<td class="num">' + (lbl.pred_total != null ? lbl.pred_total : "-") + '</td>';
      tbody.appendChild(tr);
    });
  }

  // ---- Boundary section ----
  function renderBoundary() {
    const records = filteredBenchmarks();
    const section = document.getElementById("boundary-section");
    if (!section) return;
    if (records.length === 0) {
      section.innerHTML = '<h2>Boundary Classification</h2><p class="empty-note">No benchmark records.</p>';
      return;
    }
    const sorted = [...records].sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    const latest = sorted.find(r => r.boundary_correct != null || r.boundary_over != null || r.boundary_under != null || r.boundary_partial != null);
    if (!latest) {
      section.innerHTML = '<h2>Boundary Classification</h2><p class="empty-note">No boundary data available in benchmark records.</p>';
      return;
    }
    section.querySelector("h2").textContent = "Boundary Classification (" + esc(latest.run_timestamp || "latest") + ")";
    const div = document.getElementById("boundary-summary");
    const total = (latest.boundary_correct || 0) + (latest.boundary_over || 0) + (latest.boundary_under || 0) + (latest.boundary_partial || 0);
    const pct = function(v) { return total > 0 ? ((v || 0) / total * 100).toFixed(1) + "%" : "-"; };
    div.innerHTML =
      '<table><thead><tr><th>Category</th><th>Count</th><th>%</th></tr></thead><tbody>' +
      '<tr><td>Correct</td><td class="num">' + (latest.boundary_correct != null ? latest.boundary_correct : "-") + '</td><td class="num">' + pct(latest.boundary_correct) + '</td></tr>' +
      '<tr><td>Over-segmented</td><td class="num">' + (latest.boundary_over != null ? latest.boundary_over : "-") + '</td><td class="num">' + pct(latest.boundary_over) + '</td></tr>' +
      '<tr><td>Under-segmented</td><td class="num">' + (latest.boundary_under != null ? latest.boundary_under : "-") + '</td><td class="num">' + pct(latest.boundary_under) + '</td></tr>' +
      '<tr><td>Partial</td><td class="num">' + (latest.boundary_partial != null ? latest.boundary_partial : "-") + '</td><td class="num">' + pct(latest.boundary_partial) + '</td></tr>' +
      '</tbody></table>';
  }

  // ---- Utils ----
  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function fmt4(v) { return v != null ? v.toFixed(4) : "-"; }
  function basename(path) {
    if (!path) return "";
    const parts = path.replace(/\\\\/g, "/").split("/");
    return parts[parts.length - 1] || path;
  }
  function epubExtractorRequested(record) {
    if (record.epub_extractor_requested) return String(record.epub_extractor_requested);
    const importer = String(record.importer_name || "").toLowerCase();
    if (importer && importer !== "epub") return null;
    const cfg = record.run_config || {};
    return cfg.epub_extractor_requested || cfg.epub_extractor || null;
  }
  function epubExtractorEffective(record) {
    if (record.epub_extractor_effective) return String(record.epub_extractor_effective);
    const importer = String(record.importer_name || "").toLowerCase();
    if (importer && importer !== "epub") return null;
    const cfg = record.run_config || {};
    return cfg.epub_extractor_effective || cfg.epub_extractor || null;
  }
  function autoScoreValue(record) {
    const direct = record.epub_auto_selected_score;
    if (direct != null && direct !== "") {
      const parsed = Number(direct);
      if (!Number.isNaN(parsed)) return parsed;
    }
    const cfg = record.run_config || {};
    const cfgValue = cfg.epub_auto_selected_score;
    if (cfgValue != null && cfgValue !== "") {
      const parsed = Number(cfgValue);
      if (!Number.isNaN(parsed)) return parsed;
    }
    return null;
  }
  function extractorCells(record) {
    return (
      '<td>' + esc(epubExtractorRequested(record) || "-") + '</td>' +
      '<td>' + esc(epubExtractorEffective(record) || "-") + '</td>'
    );
  }
  function autoScoreCell(record) {
    const score = autoScoreValue(record);
    return '<td class="num">' + (score != null ? score.toFixed(3) : "-") + '</td>';
  }
  function runConfigSummary(record) {
    if (record.run_config_summary) {
      return record.run_config_summary;
    }
    const cfg = record.run_config || {};
    const parts = [];
    if (cfg.epub_extractor != null) parts.push("epub_extractor=" + cfg.epub_extractor);
    if (cfg.epub_extractor_requested != null) parts.push("epub_extractor_requested=" + cfg.epub_extractor_requested);
    if (cfg.epub_extractor_effective != null) parts.push("epub_extractor_effective=" + cfg.epub_extractor_effective);
    if (cfg.ocr_device != null) parts.push("ocr_device=" + cfg.ocr_device);
    if (cfg.ocr_batch_size != null) parts.push("ocr_batch_size=" + cfg.ocr_batch_size);
    if (cfg.effective_workers != null) parts.push("effective_workers=" + cfg.effective_workers);
    else if (cfg.workers != null) parts.push("workers=" + cfg.workers);
    return parts.join(" | ");
  }
  function runConfigCell(record) {
    const summary = runConfigSummary(record);
    const warning = record.run_config_warning || "";
    const hash = record.run_config_hash || "";
    let title = warning;
    if (record.run_config) {
      title = JSON.stringify(record.run_config);
    } else if (summary) {
      title = summary;
    }
    if (hash) {
      title = (title ? title + "\\n" : "") + "hash=" + hash;
    }
    if (summary) {
      const shortHash = hash ? " [" + hash.slice(0, 10) + "]" : "";
      return '<td title="' + esc(title) + '">' + esc(summary + shortHash) + '</td>';
    }
    if (warning) {
      return '<td class="warn-note" title="' + esc(title) + '">' + esc("[warn] " + warning) + '</td>';
    }
    return '<td>-</td>';
  }
  function shortPath(p) {
    if (!p) return "";
    const parts = p.replace(/\\\\/g, "/").split("/");
    return parts.slice(-3).join("/");
  }
})();
"""
