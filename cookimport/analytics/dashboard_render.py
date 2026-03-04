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

from .dashboard_schema import BenchmarkRecord, DashboardData

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

    # Keep a program-side UI-state file so browser settings can sync across devices
    # when the dashboard is served via the local state API endpoint.
    ui_state_path = assets_dir / "dashboard_ui_state.json"
    if not ui_state_path.exists():
        ui_state_path.write_text(
            json.dumps({"version": 1}, indent=2) + "\n",
            encoding="utf-8",
        )

    # Write CSS
    css_path = assets_dir / "style.css"
    css_path.write_text(_CSS, encoding="utf-8")

    # Write JS
    js_path = assets_dir / "dashboard.js"
    js_path.write_text(_JS, encoding="utf-8")

    _render_all_method_pages(out_dir, data)

    # Write HTML
    html_path = out_dir / "index.html"
    html_data_json = data_json.replace("</", "<\\/")
    html_path.write_text(
        _HTML.replace("__DASHBOARD_DATA_INLINE__", html_data_json),
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
        config_dir / "prediction-run" / "manifest.json",
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


def _collect_all_method_groups(data: DashboardData) -> list[_AllMethodGroup]:
    # First pass: collect per-group canonical records from benchmark_records (executed eval reports).
    group_meta: dict[str, tuple[str, str | None, str]] = {}
    best_by_group_config: dict[str, dict[str, BenchmarkRecord]] = {}

    for record in data.benchmark_records:
        key_info = _all_method_group_key(record)
        if key_info is None:
            continue
        group_dir_raw, run_root_dir_raw, run_dir_timestamp, source_slug = key_info
        try:
            group_dir = str(Path(group_dir_raw).expanduser().resolve(strict=False))
        except OSError:
            group_dir = group_dir_raw
        try:
            run_root_dir = str(Path(run_root_dir_raw).expanduser().resolve(strict=False))
        except OSError:
            run_root_dir = run_root_dir_raw

        group_meta[group_dir] = (run_root_dir, run_dir_timestamp, source_slug)
        configs = best_by_group_config.setdefault(group_dir, {})

        config_dir_name = None
        _, parts = _normalize_path_parts(record.artifact_dir)
        lower_parts = [part.lower() for part in parts]
        for idx, part in enumerate(lower_parts):
            if part == _ALL_METHOD_BENCHMARK_SEGMENT:
                if idx + 2 >= len(parts):
                    continue
                candidate = parts[idx + 2]
                if candidate.startswith(_ALL_METHOD_CONFIG_PREFIX):
                    config_dir_name = candidate
                    break
            elif part == _SINGLE_PROFILE_BENCHMARK_SEGMENT:
                config_hash = str(record.run_config_hash or "").strip().lower()
                config_dir_name = (
                    f"profile_{config_hash}"
                    if config_hash
                    else "single_profile"
                )
                break
        if config_dir_name is None:
            config_dir_name = _config_name(record)

        prior = configs.get(config_dir_name)
        if prior is None or _run_timestamp_sort_key(record.run_timestamp) > _run_timestamp_sort_key(prior.run_timestamp):
            configs[config_dir_name] = record

    # Second pass: prefer all_method_benchmark_report.json when present (it includes reused variants).
    groups_by_dir: dict[str, _AllMethodGroup] = {}
    allowed_run_roots: set[str] = set()
    for run_root_dir, _, _ in group_meta.values():
        try:
            allowed_run_roots.add(str(Path(run_root_dir).expanduser().resolve(strict=False)))
        except OSError:
            allowed_run_roots.add(run_root_dir)
    golden_root = Path(str(data.golden_root or "")).expanduser()
    try:
        golden_root = golden_root.resolve(strict=False)
    except OSError:
        pass

    report_paths: list[Path] = []
    try:
        if golden_root.is_dir():
            report_paths = list(golden_root.rglob(_ALL_METHOD_REPORT_JSON))
    except OSError:
        report_paths = []

    for report_path in report_paths:
        info = _all_method_group_info_from_path(report_path.parent)
        if info is None:
            continue
        group_dir, run_root_dir, run_dir_timestamp, source_slug = info
        if allowed_run_roots:
            try:
                run_root_dir_key = str(Path(run_root_dir).expanduser().resolve(strict=False))
            except OSError:
                run_root_dir_key = run_root_dir
            if run_root_dir_key not in allowed_run_roots:
                continue

        report = _load_all_method_report(Path(group_dir))
        if report is None:
            continue
        created_at = str(report.get("created_at") or "").strip() or None
        variants = report.get("variants") or []
        if not isinstance(variants, list) or not variants:
            continue

        executed = best_by_group_config.get(group_dir, {})
        manifest_cache: dict[str, tuple[str | None, str | None, int | None, dict[str, Any] | None]] = {}

        synthetic: list[BenchmarkRecord] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            config_dir_name = str(variant.get("config_dir") or "").strip()
            if not config_dir_name:
                continue

            config_dir_path = Path(group_dir) / config_dir_name
            rep_name = str(variant.get("evaluation_representative_config_dir") or config_dir_name).strip()
            base = executed.get(rep_name)

            manifest_key = str(config_dir_path)
            fields = manifest_cache.get(manifest_key)
            if fields is None:
                fields = _load_manifest_fields(config_dir_path)
                manifest_cache[manifest_key] = fields
            importer_name, source_file, recipe_count, run_config = fields

            def _f(key: str) -> float | None:
                value = variant.get(key)
                try:
                    return float(value) if value is not None else None
                except (TypeError, ValueError):
                    return None

            run_config_hash = str(variant.get("run_config_hash") or "").strip() or None
            run_config_summary = str(variant.get("run_config_summary") or "").strip() or None

            eval_report_json = str(variant.get("eval_report_json") or "").strip()
            report_path_abs = None
            if eval_report_json:
                report_path_abs = str((Path(group_dir) / eval_report_json).expanduser().resolve(strict=False))

            synthetic.append(
                BenchmarkRecord(
                    run_timestamp=created_at,
                    artifact_dir=str(config_dir_path.expanduser().resolve(strict=False)),
                    report_path=report_path_abs,
                    strict_accuracy=_f("strict_accuracy"),
                    macro_f1_excluding_other=_f("macro_f1_excluding_other"),
                    precision=_f("precision"),
                    recall=_f("recall"),
                    f1=_f("f1"),
                    practical_precision=_f("practical_precision"),
                    practical_recall=_f("practical_recall"),
                    practical_f1=_f("practical_f1"),
                    gold_total=base.gold_total if base else None,
                    gold_recipe_headers=base.gold_recipe_headers if base else None,
                    pred_total=base.pred_total if base else None,
                    gold_matched=base.gold_matched if base else None,
                    recipes=recipe_count,
                    supported_precision=base.supported_precision if base else None,
                    supported_recall=base.supported_recall if base else None,
                    supported_practical_precision=base.supported_practical_precision if base else None,
                    supported_practical_recall=base.supported_practical_recall if base else None,
                    supported_practical_f1=base.supported_practical_f1 if base else None,
                    granularity_mismatch_likely=base.granularity_mismatch_likely if base else None,
                    pred_width_p50=base.pred_width_p50 if base else None,
                    gold_width_p50=base.gold_width_p50 if base else None,
                    per_label=list(base.per_label) if base else [],
                    boundary_correct=base.boundary_correct if base else None,
                    boundary_over=base.boundary_over if base else None,
                    boundary_under=base.boundary_under if base else None,
                    boundary_partial=base.boundary_partial if base else None,
                    task_count=base.task_count if base else None,
                    source_file=source_file or (str(report.get("source_file") or "").strip() or None),
                    importer_name=importer_name or (base.importer_name if base else None),
                    run_config=run_config or (base.run_config if base else None),
                    run_config_hash=run_config_hash or (base.run_config_hash if base else None),
                    run_config_summary=run_config_summary or (base.run_config_summary if base else None),
                    processed_report_path=base.processed_report_path if base else None,
                )
            )

        if not synthetic:
            continue

        records = sorted(synthetic, key=_config_name)
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

        groups_by_dir[group_dir] = _AllMethodGroup(
            group_dir=group_dir,
            run_root_dir=run_root_dir,
            run_dir_timestamp=run_dir_timestamp,
            source_slug=source_slug,
            records=records,
        )

    # Final pass: add any all-method groups that were present only via benchmark_records (older runs).
    for group_dir, (run_root_dir, run_dir_timestamp, source_slug) in group_meta.items():
        if group_dir in groups_by_dir:
            continue
        records = list((best_by_group_config.get(group_dir) or {}).values())
        if not records:
            continue
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
        groups_by_dir[group_dir] = _AllMethodGroup(
            group_dir=group_dir,
            run_root_dir=run_root_dir,
            run_dir_timestamp=run_dir_timestamp,
            source_slug=source_slug,
            records=records,
        )

    groups = list(groups_by_dir.values())
    groups.sort(key=lambda group: _run_timestamp_sort_key(group.run_dir_timestamp), reverse=True)
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
        f"<p><a href=\"../index.html\">Dashboard home</a> · <a href=\"{_PREVIOUS_RUNS_SECTION_HREF}\">Previous runs</a></p>"
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
        "<th>Rank</th>"
        "<th title=\"Configuration directory/name.\">Configuration</th>"
        "<th title=\"High-level dimension (extraction path).\"><span>Extractor</span></th>"
        "<th title=\"High-level dimension (parser choice).\"><span>Parser</span></th>"
        "<th title=\"Whether header/footer skipping was enabled.\">Skip HF</th>"
        "<th title=\"Whether preprocessing was enabled.\">Preprocess</th>"
        "<th title=\"How many books this configuration ran on.\">Books</th>"
        "<th title=\"How many books this configuration 'won' (best score within that book).\"><span>Wins</span></th>"
        "<th title=\"Average strict precision across books for this configuration.\">Mean Strict Precision</th>"
        "<th title=\"Average strict recall across books for this configuration.\">Mean Strict Recall</th>"
        "<th title=\"Average Strict F1 across books. Strict scoring is boundary-sensitive.\">Mean Strict F1</th>"
        "<th title=\"Average Practical F1 across books. Practical scoring is forgiving (any overlap counts).\"><span>Mean Practical F1</span></th>"
        "<th title=\"Average predicted recipe count (not a score).\"><span>Mean Recipes</span></th>"
        "<th title=\"Importer used to generate predictions.\">Importer</th>"
        "<th title=\"Key run settings summary (hover rows for full text).\"><span>Run Config</span></th>"
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
        "<th title=\"Which book/source file this row refers to.\">Source</th>"
        "<th title=\"How many configurations were evaluated for this book.\">Configs</th>"
        "<th title=\"Best configuration for this book.\">Winner</th>"
        "<th title=\"Strict F1 for the best configuration (boundary-sensitive).\"><span>Strict F1</span></th>"
        "<th title=\"Practical F1 for the best configuration (forgiving; any overlap counts).\"><span>Practical F1</span></th>"
        "<th>Details</th>"
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
    nav_links.append(
        f"<a href=\"{_PREVIOUS_RUNS_SECTION_HREF}\">Previous runs</a>"
    )
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
        "<th>Rank</th>"
        "<th title=\"Configuration directory/name.\">Configuration</th>"
        "<th title=\"High-level dimension (extraction path).\"><span>Extractor</span></th>"
        "<th title=\"High-level dimension (parser choice).\"><span>Parser</span></th>"
        "<th title=\"Whether header/footer skipping was enabled.\">Skip HF</th>"
        "<th title=\"Whether preprocessing was enabled.\">Preprocess</th>"
        "<th title=\"Strict precision for this config.\"><span>Strict Precision</span></th>"
        "<th title=\"Strict recall for this config.\"><span>Strict Recall</span></th>"
        "<th title=\"Strict F1 for this config (boundary-sensitive).\"><span>Strict F1</span></th>"
        "<th title=\"Practical F1 for this config (forgiving; any overlap counts).\"><span>Practical F1</span></th>"
        "<th title=\"Predicted recipe count (not a score).\"><span>Recipes</span></th>"
        "<th title=\"Importer used to generate predictions.\">Importer</th>"
        "<th title=\"Which book/source file this config was evaluated on.\">Source</th>"
        "<th title=\"Key run settings summary (hover rows for full text).\"><span>Run Config</span></th>"
        "<th>Artifact</th>"
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


def _render_all_method_pages(out_dir: Path, data: DashboardData) -> None:
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

    return None


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
  <p id="header-subtitle">Latest benchmark diagnostics and history.</p>
  <div id="header-meta"></div>
</header>

<main>
  <section id="diagnostics-section">
    <h2>Diagnostics (Latest Benchmark)</h2>
    <p class="section-note">Deep quality views for the most recent benchmark evaluation. Use these when a score looks off and you want to know why.</p>
    <details class="section-details">
      <summary>Metric help (benchmarks)</summary>
      <section>
        <p class="section-note">Benchmarks compare predicted labeled spans to your labeled gold spans. Higher is better. Scores are 0.0–1.0 (1.0 == 100%).</p>
        <ul class="metric-help-list">
          <li><code>strict_accuracy</code>: strict line/block accuracy from benchmark evaluation.</li>
          <li><code>macro_f1_excluding_other</code>: macro F1 across labels, excluding <code>OTHER</code>.</li>
          <li><code>Gold</code> / <code>Matched</code>: span counts for the benchmark (not recipe totals).</li>
        </ul>
      </section>
    </details>
    <div class="diagnostics-grid">
      <section id="runtime-section" class="diagnostic-card">
        <h2>Benchmark Runtime (Latest)</h2>
        <p class="section-note">AI runtime context for the latest benchmark row: model, thinking effort, and pipeline mode.</p>
        <div id="runtime-summary"></div>
      </section>

      <section id="boundary-section" class="diagnostic-card">
        <h2>Boundary Classification (Latest Benchmark)</h2>
        <p class="section-note">How predictions align to gold span boundaries across the latest benchmark run group.</p>
        <div id="boundary-summary"></div>
      </section>

      <section id="per-label-section" class="diagnostic-card">
        <h2>Per-Label Breakdown (Latest Benchmark Run)</h2>
        <div class="per-label-controls">
          <label class="per-label-rolling-label" for="per-label-rolling-window-size">Rolling N</label>
          <input
            id="per-label-rolling-window-size"
            type="number"
            min="1"
            max="50"
            step="1"
            value="10"
          >
          <label class="per-label-checkbox" for="per-label-comparison-point-value">
            <input id="per-label-comparison-point-value" type="checkbox">
            Point value
          </label>
        </div>
        <p class="section-note">Per label: precision answers false alarms, recall answers misses. Latest-run codexfarm precision/recall columns show raw baseline scores. Use the Point value checkbox to switch the comparison columns between delta-vs-baseline and raw point values (positive/green means codexfarm baseline is higher than the comparison value; negative/red means codexfarm baseline is lower). Rolling metrics use the selected N runs per variant (codexfarm vs vanilla) without cross-mixing.</p>
        <table id="per-label-table" class="dashboard-resizable-table"><thead>
          <tr class="per-label-header-primary">
            <th title="The label name being scored (for example RECIPE_TITLE)." rowspan="2">Label</th>
            <th title="Gold span count for this label." rowspan="2">Gold</th>
            <th title="Predicted span count for this label." rowspan="2">Pred</th>
            <th title="Latest-run codexfarm precision for this label (strict scoring baseline)." rowspan="2"><span class="per-label-col-head">Run<br>Precision<br><span class="per-label-col-sub">(codexfarm)</span></span></th>
            <th title="Latest-run codexfarm recall for this label (strict scoring baseline)." rowspan="2"><span class="per-label-col-head">Run<br>Recall<br><span class="per-label-col-sub">(codexfarm)</span></span></th>
            <th class="per-label-comparison-header" data-per-label-comparison-scope="run" data-per-label-comparison-metric="precision" data-per-label-comparison-variant="vanilla" title="Latest-run codexfarm precision minus latest-run vanilla precision for this label." rowspan="2"><span class="per-label-col-head">Run<br><span class="per-label-comparison-mode-value">Delta</span> Precision<br><span class="per-label-col-sub">(vanilla)</span></span></th>
            <th class="per-label-comparison-header" data-per-label-comparison-scope="run" data-per-label-comparison-metric="recall" data-per-label-comparison-variant="vanilla" title="Latest-run codexfarm recall minus latest-run vanilla recall for this label." rowspan="2"><span class="per-label-col-head">Run<br><span class="per-label-comparison-mode-value">Delta</span> Recall<br><span class="per-label-col-sub">(vanilla)</span></span></th>
            <th class="per-label-rolling-group" title="Rolling-window deltas (selected N) for codexfarm and vanilla columns." colspan="4"><span class="per-label-col-head per-label-rolling-group-head"><span class="per-label-rolling-window-value">10</span>-run Rolling <span class="per-label-comparison-mode-value">Delta</span>:</span></th>
          </tr>
          <tr class="per-label-header-rolling">
            <th class="per-label-comparison-header" data-per-label-comparison-scope="rolling" data-per-label-comparison-metric="precision" data-per-label-comparison-variant="codexfarm" title="Latest-run codexfarm precision minus rolling codexfarm precision over N runs for this label."><span class="per-label-col-head">Precision<br><span class="per-label-col-sub">(codexfarm)</span></span></th>
            <th class="per-label-comparison-header" data-per-label-comparison-scope="rolling" data-per-label-comparison-metric="recall" data-per-label-comparison-variant="codexfarm" title="Latest-run codexfarm recall minus rolling codexfarm recall over N runs for this label."><span class="per-label-col-head">Recall<br><span class="per-label-col-sub">(codexfarm)</span></span></th>
            <th class="per-label-comparison-header" data-per-label-comparison-scope="rolling" data-per-label-comparison-metric="precision" data-per-label-comparison-variant="vanilla" title="Latest-run codexfarm precision minus rolling vanilla precision over N runs for this label."><span class="per-label-col-head">Precision<br><span class="per-label-col-sub">(vanilla)</span></span></th>
            <th class="per-label-comparison-header" data-per-label-comparison-scope="rolling" data-per-label-comparison-metric="recall" data-per-label-comparison-variant="vanilla" title="Latest-run codexfarm recall minus rolling vanilla recall over N runs for this label."><span class="per-label-col-head">Recall<br><span class="per-label-col-sub">(vanilla)</span></span></th>
          </tr>
        </thead><tbody></tbody></table>
      </section>
    </div>
  </section>

  <section id="previous-runs-section">
    <h2>Previous Runs</h2>
    <p class="section-note">Timestamp links to the run artifact folder. Full history is rendered; use horizontal scroll for wide columns.</p>
    <details class="section-details">
      <summary>Metric help (table)</summary>
      <section>
        <p class="section-note">Previous Runs shows explicit benchmark metrics only.</p>
        <ul class="metric-help-list">
          <li><code>strict_accuracy</code>: strict benchmark accuracy (higher is better).</li>
          <li><code>macro_f1_excluding_other</code>: class-balanced quality over non-OTHER labels.</li>
          <li><code>Recipes</code>: predicted recipe count (when available). Separate from span scoring.</li>
        </ul>
      </section>
    </details>
    <div class="previous-runs-top-grid">
      <div class="previous-runs-analysis-panels">
        <section id="compare-control-panel" class="compare-control-panel">
          <h3>Compare &amp; Control</h3>
          <p class="section-note">Use visible rows to find likely drivers, compare one field, hold confounders constant, and push selected groups into table filters.</p>
          <div class="compare-control-controls">
            <label for="compare-control-view-mode">View</label>
            <select id="compare-control-view-mode">
              <option value="discover">discover</option>
              <option value="raw">raw</option>
              <option value="controlled">controlled</option>
            </select>
            <label for="compare-control-outcome-field">Outcome</label>
            <select id="compare-control-outcome-field"></select>
            <label for="compare-control-compare-field">Compare by</label>
            <select id="compare-control-compare-field"></select>
            <label for="compare-control-split-field">Split by</label>
            <select id="compare-control-split-field"></select>
          </div>
          <div class="compare-control-hold">
            <span class="compare-control-hold-label">Hold constant</span>
            <div id="compare-control-hold-fields" class="compare-control-hold-fields"></div>
          </div>
          <div id="compare-control-group-selection" class="compare-control-group-selection"></div>
          <div class="compare-control-actions">
            <button id="compare-control-filter-subset" type="button">Filter to subset</button>
            <button id="compare-control-clear-selection" type="button">Clear groups</button>
            <button id="compare-control-reset" type="button">Reset</button>
          </div>
          <p id="compare-control-status" class="section-note"></p>
          <div id="compare-control-results" class="compare-control-results"></div>
        </section>
      </div>
      <div class="trend-chart-wrap">
        <h3>Benchmark Score Trend</h3>
        <p class="section-note">Interactive time-series view of benchmark quality metrics (same chart tech as the git-stats dashboards).</p>
        <div id="benchmark-trend-chart" class="highcharts-host" aria-label="Benchmark score trend chart"></div>
        <p id="benchmark-trend-fallback" class="empty-note" hidden></p>
      </div>
    </div>
    <section id="quick-filters-panel" class="quick-filters-panel">
      <h3>Quick Filters</h3>
      <p class="section-note">Fast toggles for benchmark focus.</p>
      <div class="quick-filters-list">
        <label for="quick-filter-official-only">
          <input id="quick-filter-official-only" type="checkbox" checked>
          Official benchmarks only (single-offline vanilla/codexfarm)
        </label>
        <label for="quick-filter-exclude-ai-tests">
          <input id="quick-filter-exclude-ai-tests" type="checkbox">
          Exclude AI test/smoke benchmark runs
        </label>
      </div>
      <div class="quick-filters-actions">
        <section class="previous-runs-presets-panel">
          <h4>View presets</h4>
          <p class="section-note">Save/load column + filter views. <strong>Save current view</strong> captures what you currently have applied.</p>
          <div class="previous-runs-presets-controls">
            <label for="previous-runs-preset-select">Preset</label>
            <select id="previous-runs-preset-select">
              <option value="">(none)</option>
            </select>
          </div>
          <div class="previous-runs-presets-actions">
            <button id="previous-runs-preset-load" type="button">Load</button>
            <button id="previous-runs-preset-save-current" type="button">Save current view</button>
            <button id="previous-runs-preset-delete" type="button">Delete</button>
          </div>
          <p id="previous-runs-preset-status" class="section-note"></p>
        </section>
        <button id="previous-runs-clear-all-filters" type="button">Clear all filters</button>
      </div>
      <p id="quick-filters-status" class="section-note"></p>
    </section>
    <div class="table-wrap table-scroll">
      <div class="previous-runs-columns-control">
        <button
          id="previous-runs-columns-toggle"
          class="previous-runs-columns-toggle"
          type="button"
          aria-haspopup="true"
          aria-expanded="false"
          aria-controls="previous-runs-columns-popup"
          title="Show or hide table columns"
        >+/-</button>
        <div id="previous-runs-columns-popup" class="previous-runs-columns-popup" hidden>
          <p class="section-note">Check fields to include them in Previous Runs. Drag table headers to reorder and drag edges to resize.</p>
          <div id="previous-runs-columns-checklist"></div>
          <div class="previous-runs-columns-popup-actions">
            <div class="previous-runs-global-filter-mode">
              <label for="previous-runs-global-filter-mode">Across columns</label>
              <select id="previous-runs-global-filter-mode">
                <option value="and">AND</option>
                <option value="or">OR</option>
              </select>
            </div>
            <button id="previous-runs-clear-filters" type="button">Clear column filters</button>
            <button id="previous-runs-column-reset" type="button">Reset defaults</button>
          </div>
        </div>
      </div>
      <table id="previous-runs-table">
        <colgroup></colgroup>
        <thead>
          <tr class="previous-runs-header-row"></tr>
          <tr class="previous-runs-active-filters-row"></tr>
          <tr class="previous-runs-filter-spacer-row"></tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </section>
</main>

<footer>Generated by <code>cookimport stats-dashboard</code></footer>

<script id="dashboard-data-inline" type="application/json">__DASHBOARD_DATA_INLINE__</script>
<script src="https://code.highcharts.com/stock/highstock.js"></script>
<script>
if (!window.Highcharts || typeof window.Highcharts.stockChart !== 'function') {
  document.write('<script src="https://cdn.jsdelivr.net/npm/highcharts/highstock.js"><\\/script>');
}
</script>
<script src="https://code.highcharts.com/highcharts-more.js"></script>
<script>
if (!window.Highcharts || !window.Highcharts.seriesTypes || typeof window.Highcharts.seriesTypes.arearange !== 'function') {
  document.write('<script src="https://cdn.jsdelivr.net/npm/highcharts/highcharts-more.js"><\\/script>');
}
</script>
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
  --previous-runs-header-row-height: 2.18rem;
  --previous-runs-filter-row-height: 2.18rem;
  --previous-runs-spacer-row-height: 2.18rem;
  --previous-runs-body-row-height: 1.85rem;
  --previous-runs-visible-body-rows: 10;
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
.metric-help-list {
  margin: 0.15rem 0 0.4rem 1.1rem;
  color: var(--muted);
  font-size: 0.83rem;
}
.metric-help-list li { margin: 0.2rem 0; }
#previous-runs-clear-filters,
#previous-runs-clear-all-filters,
#previous-runs-column-reset {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0.18rem 0.62rem;
}
#previous-runs-clear-filters:hover,
#previous-runs-clear-all-filters:hover,
#previous-runs-column-reset:hover {
  border-color: #c7d0d9;
}
.compare-control-panel {
  margin: 0.75rem 0 0.9rem;
  background: #fbfcf7;
  border: 1px solid #dde5cf;
}
.previous-runs-top-grid {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(0, 2fr);
  gap: 0.75rem;
  align-items: start;
  margin: 0.5rem 0 0.9rem;
}
.previous-runs-analysis-panels {
  display: grid;
  gap: 0.7rem;
}
.previous-runs-top-grid .compare-control-panel,
.previous-runs-top-grid .trend-chart-wrap {
  margin: 0;
}
.compare-control-panel h3 {
  margin-top: 0;
  color: #4a6438;
}
.compare-control-controls {
  display: grid;
  grid-template-columns: minmax(78px, auto) minmax(0, 1fr);
  gap: 0.32rem 0.45rem;
  align-items: center;
}
.compare-control-controls label,
.compare-control-hold-label {
  color: var(--muted);
  font-size: 0.73rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
#compare-control-view-mode,
#compare-control-outcome-field,
#compare-control-compare-field,
#compare-control-split-field {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  color: var(--text);
  font-size: 0.8rem;
  padding: 0.28rem 0.4rem;
}
#compare-control-filter-subset,
#compare-control-clear-selection,
#compare-control-reset {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.77rem;
  padding: 0.18rem 0.62rem;
}
#compare-control-filter-subset:hover,
#compare-control-clear-selection:hover,
#compare-control-reset:hover {
  border-color: #c7d0d9;
}
#compare-control-filter-subset:disabled,
#compare-control-clear-selection:disabled,
#compare-control-reset:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
#compare-control-status.error {
  color: var(--accent3);
}
.compare-control-hold {
  margin-top: 0.5rem;
}
.compare-control-hold-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.24rem 0.5rem;
  margin-top: 0.24rem;
}
.compare-control-hold-item {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  font-size: 0.76rem;
  color: var(--text);
}
.compare-control-hold-item input[type="checkbox"] {
  margin: 0;
}
.compare-control-group-selection {
  margin-top: 0.5rem;
}
.compare-control-group-selection-list {
  display: grid;
  gap: 0.21rem;
  max-height: 150px;
  overflow-y: auto;
  padding-right: 0.2rem;
}
.compare-control-group-option {
  display: inline-flex;
  align-items: center;
  gap: 0.36rem;
  font-size: 0.76rem;
  color: var(--text);
}
.compare-control-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.52rem;
}
.compare-control-results {
  border: 1px dashed #ccd9c1;
  border-radius: 8px;
  background: #fff;
  padding: 0.48rem 0.62rem;
}
.compare-control-results p {
  margin: 0.2rem 0;
  font-size: 0.81rem;
}
.compare-control-results ul {
  margin: 0.25rem 0 0.05rem 1rem;
  padding: 0;
}
.compare-control-results li {
  margin: 0.15rem 0;
  font-size: 0.79rem;
}
.compare-control-discovery-list {
  display: grid;
  gap: 0.26rem;
}
.compare-control-discovery-card {
  border: 1px solid #d8e2cb;
  border-radius: 7px;
  background: #f9fcf3;
  text-align: left;
  padding: 0.34rem 0.48rem;
  cursor: pointer;
  color: var(--text);
}
.compare-control-discovery-card:hover {
  border-color: #b4c59f;
}
.compare-control-discovery-card .score {
  color: #466832;
  font-weight: 600;
}
.compare-control-split-list {
  margin-top: 0.36rem;
}
.compare-control-inline-note {
  color: var(--muted);
  font-size: 0.78rem;
}
.compare-control-warning {
  color: #8a5b07;
  font-size: 0.79rem;
}

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
.trend-chart-wrap {
  margin: 0.5rem 0 0.85rem;
}
.quick-filters-panel {
  margin: 0.55rem 0 0.85rem;
  background: #f8fbf6;
  border: 1px solid #d7e3cf;
}
.quick-filters-panel h3 {
  margin-top: 0;
  color: #435c3b;
}
.quick-filters-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.52rem 1.1rem;
}
.quick-filters-list label {
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  font-size: 0.82rem;
  color: var(--text);
  cursor: pointer;
}
.quick-filters-list input[type="checkbox"] {
  width: 0.95rem;
  height: 0.95rem;
  accent-color: var(--accent2);
}
.quick-filters-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.42rem;
  align-items: flex-start;
  margin-top: 0.45rem;
}
#previous-runs-clear-all-filters {
  font-size: 0.78rem;
  align-self: flex-start;
}
#quick-filters-status {
  margin: 0.52rem 0 0.05rem;
}
.highcharts-host {
  width: 100%;
  height: 800px;
  min-height: 720px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fbfdff;
}

.table-wrap {
  overflow-x: auto;
  position: relative;
}
.previous-runs-columns-control {
  position: absolute;
  top: 0.4rem;
  right: 0.45rem;
  z-index: 5;
  display: inline-block;
}
.previous-runs-columns-toggle {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f4f8fd;
  color: var(--text);
  cursor: pointer;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  padding: 0.14rem 0.5rem;
  min-width: 2.6rem;
}
.previous-runs-columns-toggle:hover,
.previous-runs-columns-toggle.open {
  border-color: #8ab0d8;
  background: #e7f1ff;
  color: #174d84;
}
.previous-runs-columns-popup {
  position: absolute;
  top: calc(100% + 0.25rem);
  right: 0;
  width: min(310px, calc(100vw - 1.6rem));
  max-height: min(65vh, 460px);
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fbfdff;
  box-shadow: 0 10px 24px rgba(21, 34, 48, 0.14);
  padding: 0.55rem 0.6rem;
}
#previous-runs-columns-checklist {
  display: grid;
  gap: 0.28rem;
}
.previous-runs-columns-check-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 0.42rem;
  align-items: start;
  color: var(--text);
  font-size: 0.78rem;
}
.previous-runs-columns-check-item code {
  color: var(--muted);
  font-size: 0.72rem;
}
.previous-runs-presets-panel {
  margin: 0;
  padding: 0.55rem 0.6rem;
  border: 1px solid #c7d9bf;
  border-radius: 8px;
  background: #fbfef9;
  box-shadow: 0 10px 24px rgba(21, 34, 48, 0.08);
  width: min(420px, calc(100vw - 2.2rem));
  max-width: 100%;
  flex: 0 1 420px;
}
.previous-runs-presets-panel h4 {
  margin: 0 0 0.2rem;
  font-size: 0.79rem;
  color: #1a466f;
}
.previous-runs-presets-controls {
  display: grid;
  gap: 0.22rem;
}
.previous-runs-presets-controls label {
  font-size: 0.72rem;
  color: var(--muted);
}
#previous-runs-preset-select {
  width: 100%;
  min-height: 1.9rem;
}
.previous-runs-presets-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.34rem;
  margin-top: 0.36rem;
}
.previous-runs-presets-actions button {
  font-size: 0.74rem;
}
#previous-runs-preset-status {
  margin: 0.38rem 0 0;
  font-size: 0.72rem;
}
#previous-runs-preset-status.error {
  color: #ad2e24;
}
.previous-runs-columns-popup-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem;
  align-items: flex-end;
  margin-top: 0.48rem;
}
.previous-runs-columns-popup-actions button {
  font-size: 0.74rem;
}
.previous-runs-global-filter-mode {
  display: grid;
  gap: 0.18rem;
}
.previous-runs-global-filter-mode label {
  font-size: 0.72rem;
  color: var(--muted);
}
#previous-runs-global-filter-mode {
  min-height: 1.9rem;
}

.table-scroll {
  min-height: calc(
    var(--previous-runs-header-row-height)
    + var(--previous-runs-filter-row-height)
    + var(--previous-runs-spacer-row-height)
    + (var(--previous-runs-visible-body-rows) * var(--previous-runs-body-row-height))
  );
  max-height: calc(
    var(--previous-runs-header-row-height)
    + var(--previous-runs-filter-row-height)
    + var(--previous-runs-spacer-row-height)
    + (var(--previous-runs-visible-body-rows) * var(--previous-runs-body-row-height))
  );
  overflow-x: auto;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.table-scroll thead th {
  position: sticky;
  background: var(--card);
  z-index: 1;
}
#previous-runs-table thead tr.previous-runs-header-row th {
  top: 0;
  z-index: 3;
}
#previous-runs-table thead tr.previous-runs-active-filters-row th {
  top: var(--previous-runs-header-row-height);
  background: #f7fbff;
  z-index: 2;
  text-transform: none;
  letter-spacing: 0;
  font-weight: 500;
  padding-top: 0.46rem;
  padding-bottom: 0.46rem;
}
#previous-runs-table thead tr.previous-runs-filter-spacer-row th {
  top: calc(var(--previous-runs-header-row-height) + var(--previous-runs-filter-row-height));
  background: #fcfdff;
  z-index: 1;
  text-transform: none;
  letter-spacing: 0;
  font-weight: 500;
  padding-top: 0.06rem;
  padding-bottom: 0.06rem;
  border-bottom: 0;
}

table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.dashboard-resizable-table {
  width: max-content;
  min-width: 100%;
}
.dashboard-resizable-table th,
.dashboard-resizable-table td {
  position: relative;
}
th, td { text-align: left; padding: 0.37rem 0.55rem; border-bottom: 1px solid var(--border); }
#previous-runs-table {
  border-collapse: separate;
  border-spacing: 0;
  width: max-content;
  min-width: 1600px;
  max-width: none;
}
#previous-runs-table thead th {
  background-clip: padding-box;
}
#previous-runs-table th,
#previous-runs-table td {
  white-space: nowrap;
}
#previous-runs-table th {
  padding-right: 0.9rem;
}
#previous-runs-table .previous-runs-header-title {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
}
#previous-runs-table thead tr.previous-runs-header-row th:not(:last-child),
.dashboard-resizable-table thead tr:first-child th:not(:last-child) {
  border-right: 1px solid #d6e0ea;
}
.previous-runs-column-filter {
  position: relative;
}
.previous-runs-column-filter-summary-wrap {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.35rem;
  align-items: center;
}
.previous-runs-column-filter-summary {
  min-height: 1.22rem;
  display: flex;
  flex-direction: column;
  gap: 0.24rem;
  color: var(--muted);
  font-size: 0.77rem;
  line-height: 1.28;
}
.previous-runs-column-filter-summary.filter-active {
  color: #174d84;
  font-weight: 600;
}
.previous-runs-column-filter-summary-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.34rem;
}
.previous-runs-column-filter-summary-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.previous-runs-column-filter-summary-remove {
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #6f8091;
  cursor: pointer;
  width: auto;
  height: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  padding: 0.02rem;
  min-width: 13px;
  min-height: 13px;
}
.previous-runs-column-filter-summary-remove:hover {
  color: #556778;
}
.previous-runs-column-filter-toggle {
  width: auto;
  height: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #174d84;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.08rem 0.16rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  line-height: 1;
  min-width: 1rem;
  min-height: 1rem;
  align-self: center;
}
.previous-runs-icon-svg {
  display: block;
  width: 12px;
  height: 12px;
}
.previous-runs-column-filter-toggle:hover {
  color: #123a63;
}
.previous-runs-column-filter-toggle.filter-active {
  color: #174d84;
}
.previous-runs-column-filter-popover {
  position: absolute;
  top: calc(100% + 0.24rem);
  right: 0;
  min-width: 230px;
  max-width: min(340px, 85vw);
  border: 1px solid #cfd9e4;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
  padding: 0.5rem;
  z-index: 20;
  white-space: normal;
}
.previous-runs-column-filter-popover-title {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 0.35rem;
}
.previous-runs-column-filter-mode {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 0.32rem;
  margin: 0 0 0.42rem;
}
.previous-runs-column-filter-mode-label {
  font-size: 0.68rem;
  color: var(--muted);
}
.previous-runs-column-filter-mode-buttons {
  display: inline-flex;
  justify-content: flex-end;
  gap: 0.24rem;
}
.previous-runs-column-filter-mode-btn {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.66rem;
  padding: 0.08rem 0.42rem;
}
.previous-runs-column-filter-mode-btn.active {
  border-color: #8ab0d8;
  background: #e7f1ff;
  color: #174d84;
}
.previous-runs-column-filter-mode-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.previous-runs-column-filter-mode-btn:hover:not(:disabled) {
  border-color: #c7d0d9;
}
.previous-runs-column-filter-active-list {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  margin: 0 0 0.45rem;
}
.previous-runs-column-filter-active-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.28rem;
  font-size: 0.71rem;
  color: var(--text);
  border: 1px solid #dde6f0;
  border-radius: 6px;
  background: #f8fbff;
  padding: 0.15rem 0.22rem 0.15rem 0.34rem;
}
.previous-runs-column-filter-active-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.previous-runs-column-filter-active-remove {
  border: 1px solid #d7e0ea;
  border-radius: 999px;
  background: #ffffff;
  color: #4a5b6b;
  cursor: pointer;
  width: 1.1rem;
  height: 1.1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  line-height: 1;
  padding: 0;
}
.previous-runs-column-filter-active-remove:hover {
  border-color: #c6d0dc;
}
.previous-runs-column-filter-active-empty {
  font-size: 0.7rem;
  color: var(--muted);
}
.previous-runs-column-filter-popover-controls {
  display: grid;
  grid-template-columns: minmax(86px, 1fr) minmax(120px, 1.2fr);
  gap: 0.3rem;
  align-items: center;
  margin-bottom: 0.4rem;
}
.previous-runs-column-filter-popover-controls select,
.previous-runs-column-filter-popover-controls input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  color: var(--text);
  font-size: 0.75rem;
  padding: 0.18rem 0.32rem;
}
.previous-runs-column-filter-suggestions {
  margin: 0 0 0.42rem;
}
.previous-runs-column-filter-suggestions-title {
  color: var(--muted);
  font-size: 0.68rem;
  margin-bottom: 0.2rem;
}
.previous-runs-column-filter-suggestions-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.22rem;
  max-height: 6.8rem;
  overflow-y: auto;
}
.previous-runs-column-filter-suggestion {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f8fbff;
  color: var(--text);
  cursor: pointer;
  font-size: 0.68rem;
  line-height: 1.2;
  padding: 0.12rem 0.42rem;
}
.previous-runs-column-filter-suggestion.best {
  border-color: #8ab0d8;
  background: #e7f1ff;
  color: #174d84;
}
.previous-runs-column-filter-suggestion:hover {
  border-color: #c7d0d9;
}
.previous-runs-column-filter-popover-actions {
  display: flex;
  gap: 0.3rem;
  justify-content: flex-end;
}
.previous-runs-column-filter-clear {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.68rem;
  padding: 0.12rem 0.48rem;
}
.previous-runs-column-filter-clear:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.previous-runs-column-filter-clear:hover:not(:disabled) {
  border-color: #c7d0d9;
}
.previous-runs-column-filter-save,
.previous-runs-column-filter-close {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f6f9fc;
  color: var(--text);
  cursor: pointer;
  font-size: 0.68rem;
  padding: 0.12rem 0.48rem;
}
.previous-runs-column-filter-save {
  border-color: #8ab0d8;
  background: #e7f1ff;
  color: #174d84;
}
.previous-runs-column-filter-save:hover,
.previous-runs-column-filter-close:hover {
  border-color: #c7d0d9;
}
#previous-runs-table th.previous-runs-draggable {
  cursor: grab;
}
#previous-runs-table th.previous-runs-draggable:active {
  cursor: grabbing;
}
#previous-runs-table th.previous-runs-drag-source {
  opacity: 0.65;
}
#previous-runs-table th.previous-runs-drag-target {
  box-shadow: inset 0 -2px 0 var(--focus);
}
.previous-runs-resize-handle,
.dashboard-table-resize-handle {
  position: absolute;
  top: 0;
  right: -0.28rem;
  width: 0.62rem;
  height: 100%;
  cursor: col-resize;
}
body.previous-runs-resizing,
body.dashboard-table-resizing {
  cursor: col-resize;
  user-select: none;
}
th {
  font-weight: 600;
  color: var(--muted);
  font-size: 0.73rem;
  text-transform: uppercase;
  letter-spacing: 0.045em;
}
td.num { text-align: right; font-family: var(--mono); }
td.delta-better { color: #0d5b37; font-weight: 600; }
td.delta-worse { color: #8a261f; font-weight: 600; }
td a { color: var(--accent); text-decoration: none; word-break: break-all; }
td a:hover { text-decoration: underline; }
td.warn-note { color: #b45309; font-weight: 600; }
.empty-note-cell {
  text-align: center;
  color: var(--muted);
  font-style: italic;
  padding: 0.8rem;
}
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
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.7rem;
}
.diagnostic-card {
  margin: 0;
  background: #f8fbfe;
}
#runtime-summary table,
#boundary-summary table {
  margin: 0;
  width: 100%;
  min-width: 0;
  table-layout: fixed;
}
#runtime-summary td:first-child {
  color: var(--muted);
  width: 42%;
}
#runtime-summary,
#boundary-summary {
  overflow-x: hidden;
}
#per-label-section {
  grid-column: 1 / -1;
  overflow-x: auto;
}
.per-label-controls {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0 0 0.45rem;
  padding: 0.2rem 0.35rem;
  border: 1px solid #d5e0ea;
  border-radius: 6px;
  background: #f9fcff;
}
.per-label-controls .per-label-rolling-label {
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.per-label-controls input[type="number"] {
  width: 3.6rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.1rem 0.3rem;
  background: #fff;
  color: var(--text);
  font-size: 0.78rem;
  font-family: var(--mono);
}
.per-label-controls .per-label-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  margin-left: 0.25rem;
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  cursor: pointer;
}
.per-label-controls .per-label-checkbox input[type="checkbox"] {
  width: 0.88rem;
  height: 0.88rem;
  margin: 0;
}
#per-label-table {
  width: max-content;
  min-width: max-content;
}
#per-label-table th:first-child,
#per-label-table td:first-child {
  width: 25.5ch;
  min-width: 25.5ch;
}
#per-label-table th {
  white-space: normal;
  text-align: left;
  padding-top: 0.16rem;
  padding-bottom: 0.16rem;
}
#per-label-table th,
#per-label-table td {
  padding-left: 2px;
  padding-right: 2px;
}
#per-label-table th:first-child,
#per-label-table td:first-child {
  padding-left: 0.24rem;
  padding-right: 0.24rem;
}
#per-label-table td.num {
  text-align: left;
}
#per-label-table td:nth-child(n+2):nth-child(-n+3),
#per-label-table thead tr.per-label-header-primary th:nth-child(n+2):nth-child(-n+3) {
  width: calc(6ch + 10px);
  min-width: calc(6ch + 10px);
}
#per-label-table td:nth-child(n+4):nth-child(-n+11),
#per-label-table thead tr.per-label-header-primary th:nth-child(n+4):nth-child(-n+7),
#per-label-table thead tr.per-label-header-rolling th {
  width: calc(10ch + 10px);
  min-width: calc(10ch + 10px);
}
#per-label-table thead tr.per-label-header-primary th.per-label-rolling-group {
  text-align: center;
  vertical-align: bottom;
  padding-bottom: 0.04rem;
}
#per-label-table thead tr.per-label-header-primary th.per-label-rolling-group .per-label-col-head {
  text-align: center;
}
.per-label-rolling-group-head {
  white-space: nowrap;
}
#per-label-table thead tr.per-label-header-rolling th {
  vertical-align: top;
}
.per-label-col-head {
  display: block;
  line-height: 1.06;
  text-align: left;
  font-size: 0.92em;
}
.per-label-col-sub {
  font-size: 0.74em;
  letter-spacing: 0.01em;
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
  .diagnostics-grid {
    grid-template-columns: 1fr;
  }
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
  #recent-runs th:nth-child(9),
  #recent-runs td:nth-child(9),
  #recent-runs th:nth-child(10),
  #recent-runs td:nth-child(10),
  #file-trend-table th:nth-child(6),
  #file-trend-table td:nth-child(6),
  #file-trend-table th:nth-child(7),
  #file-trend-table td:nth-child(7),
  #file-trend-table th:nth-child(8),
  #file-trend-table td:nth-child(8),
  #file-trend-table th:nth-child(9),
  #file-trend-table td:nth-child(9),
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
  .previous-runs-column-filter {
    min-width: 120px;
  }
  .previous-runs-column-filter-popover {
    right: auto;
    left: 0;
    min-width: 210px;
  }
  .previous-runs-column-filter-popover-controls {
    grid-template-columns: 1fr;
  }
  .previous-runs-columns-control {
    top: 0.35rem;
    right: 0.35rem;
  }
  .previous-runs-columns-popup {
    width: min(280px, calc(100vw - 1.3rem));
  }
  .previous-runs-top-grid {
    grid-template-columns: 1fr;
  }
  .compare-control-controls {
    grid-template-columns: 1fr;
  }
  #compare-control-view-mode,
  #compare-control-outcome-field,
  #compare-control-compare-field,
  #compare-control-split-field {
    width: 100%;
  }
  .compare-control-hold-fields {
    grid-template-columns: 1fr;
  }
  .quick-filters-list {
    flex-direction: column;
    align-items: flex-start;
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
  let previousRunsColumnFilters = Object.create(null);
  let previousRunsColumnFilterModes = Object.create(null);
  let previousRunsColumnFilterGlobalMode = "and";
  let previousRunsQuickFilters = {
    exclude_ai_tests: false,
    official_full_golden_only: true,
  };
  let previousRunsFieldOptions = [];
  let previousRunsVisibleColumns = [];
  let previousRunsColumnWidths = Object.create(null);
  let dashboardTableColumnWidths = Object.create(null);
  let previousRunsDraggedColumn = null;
  let previousRunsOpenFilterField = "";
  let previousRunsOpenFilterDraft = null;
  let previousRunsColumnsPopupOpen = false;
  let previousRunsFilterResultCache = null;
  let previousRunsViewPresets = Object.create(null);
  let previousRunsSelectedPreset = "";
  let previousRunsSortField = "run_timestamp";
  let previousRunsSortDirection = "desc";
  function compareControlDefaultState() {
    return {
      outcome_field: "strict_accuracy",
      compare_field: "",
      hold_constant_fields: [],
      split_field: "",
      view_mode: "discover",
      selected_groups: [],
    };
  }
  let compareControlState = compareControlDefaultState();
  let compareControlStatusMessage = "";
  let compareControlStatusIsError = false;
  let perLabelRollingWindowSize = 10;
  let perLabelComparisonMode = "delta";
  // Keep wheel-zoom off across all Highcharts charts unless explicitly re-enabled.
  const HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED = false;
  const PER_LABEL_ROLLING_WINDOW_MIN = 1;
  const PER_LABEL_ROLLING_WINDOW_MAX = 50;
  const PREVIOUS_RUNS_COLUMN_FILTER_OPERATORS = [
    ["contains", "contains"],
    ["not_contains", "does not contain"],
    ["eq", "equals"],
    ["neq", "not equals"],
    ["starts_with", "starts with"],
    ["ends_with", "ends with"],
    ["gt", "> (numeric)"],
    ["gte", ">= (numeric)"],
    ["lt", "< (numeric)"],
    ["lte", "<= (numeric)"],
    ["regex", "matches regex"],
    ["is_empty", "is empty"],
    ["not_empty", "is not empty"],
  ];
  const PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP = Object.fromEntries(
    PREVIOUS_RUNS_COLUMN_FILTER_OPERATORS
  );
  const PREVIOUS_RUNS_UNARY_FILTER_OPERATORS = new Set(["is_empty", "not_empty"]);
  const PREVIOUS_RUNS_COLUMN_FILTER_MODES = [
    ["and", "AND"],
    ["or", "OR"],
  ];
  const PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL = Object.fromEntries(
    PREVIOUS_RUNS_COLUMN_FILTER_MODES
  );
  const PREVIOUS_RUNS_FILTER_SUGGESTION_LIMIT = 8;
  const PREVIOUS_RUNS_PRESET_NAME_MAX = 80;
  const PREVIOUS_RUNS_PRESET_MAX_COUNT = 40;
  const PREVIOUS_RUNS_DEFAULT_COLUMNS = [
    "run_timestamp",
    "strict_accuracy",
    "macro_f1_excluding_other",
    "gold_total",
    "gold_matched",
    "recipes",
    "all_token_use",
    "source_label",
    "importer_name",
    "ai_model",
    "ai_effort",
  ];
  const PREVIOUS_RUNS_COLUMN_META = {
    run_timestamp: {
      label: "Timestamp",
      title: "When the benchmark happened. Link opens the run artifact folder.",
      numeric: false,
    },
    strict_accuracy: {
      label: "strict_accuracy",
      title: "Strict benchmark accuracy from canonical/stage scoring.",
      numeric: true,
    },
    macro_f1_excluding_other: {
      label: "macro_f1_excluding_other",
      title: "Macro F1 across labels excluding OTHER.",
      numeric: true,
    },
    gold_total: {
      label: "Gold",
      title: "How many gold spans were evaluated (span count, not recipes).",
      numeric: true,
    },
    gold_matched: {
      label: "Matched",
      title: "How many gold spans were matched under strict scoring.",
      numeric: true,
    },
    recipes: {
      label: "Recipes",
      title: "Predicted recipe count (when available). Separate from span scoring.",
      numeric: true,
    },
    all_token_use: {
      label: "All token use",
      title: "Combined token view (discounted_total/input/output). Discounted total applies cached-input tokens at 10% weight.",
      numeric: true,
    },
    tokens_input: {
      label: "Tokens In",
      title: "CodexFarm input tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_cached_input: {
      label: "Tokens Cached In",
      title: "CodexFarm cached-input tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_output: {
      label: "Tokens Out",
      title: "CodexFarm output tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_reasoning: {
      label: "Tokens Reasoning",
      title: "CodexFarm reasoning tokens summed for this benchmark run.",
      numeric: true,
    },
    tokens_total: {
      label: "Tokens Total",
      title: "CodexFarm total tokens summed for this benchmark run.",
      numeric: true,
    },
    source_label: {
      label: "Source",
      title: "Which source file/book was evaluated.",
      numeric: false,
    },
    importer_name: {
      label: "Importer",
      title: "Importer used to generate predictions.",
      numeric: false,
    },
    ai_model: {
      label: "AI Model",
      title: "Best-effort AI model from benchmark run config metadata.",
      numeric: false,
    },
    ai_effort: {
      label: "AI Effort",
      title: "Best-effort AI thinking effort from benchmark run config metadata.",
      numeric: false,
    },
  };
  const PREVIOUS_RUNS_SCORE_FIELDS = new Set([
    "strict_accuracy",
    "macro_f1_excluding_other",
    "precision",
    "recall",
    "f1",
    "practical_f1",
    "supported_precision",
    "supported_recall",
    "supported_practical_precision",
    "supported_practical_recall",
    "supported_practical_f1",
  ]);
  const ANALYSIS_FIELD_PREFERRED = [
    "source_label",
    "source_file_basename",
    "importer_name",
    "ai_model",
    "ai_effort",
    "run_config.llm_recipe_pipeline",
    "run_config.epub_extractor",
    "run_config.epub_extractor_effective",
    "run_config.epub_unstructured_preprocess_mode",
    "run_config.epub_unstructured_skip_headers_footers",
    "run_config.codex_farm_reasoning_effort",
    "run_config.codex_farm_model",
  ];
  const COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD = "strict_accuracy";
  const COMPARE_CONTROL_VIEW_MODES = new Set(["discover", "raw", "controlled"]);
  const COMPARE_CONTROL_OUTCOME_PREFERRED = [
    "strict_accuracy",
    "macro_f1_excluding_other",
    "precision",
    "recall",
    "f1",
    "practical_f1",
    "supported_practical_f1",
  ];
  const COMPARE_CONTROL_FIELD_SKIP = new Set([
    "artifact_dir",
    "artifact_dir_basename",
    "run_dir",
    "report_path",
    "run_timestamp",
    "run_config_summary",
    "run_config_hash",
    "per_label_json",
    "per_label",
  ]);
  const COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED = [
    "benchmark_total_seconds",
    "benchmark_prediction_seconds",
    "benchmark_evaluation_seconds",
    "all_token_use",
    "tokens_total",
    "tokens_input",
    "tokens_output",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "benchmark_cost_usd",
    "run_cost_usd",
  ];
  const COMPARE_CONTROL_SECONDARY_FIELD_PATTERN = /(token|runtime|second|latency|cost|usd|price)/i;
  const COMPARE_CONTROL_SECONDARY_MAX_FIELDS = 4;
  const COMPARE_CONTROL_WARNING_ROW_COVERAGE_MIN = 0.6;
  const COMPARE_CONTROL_WARNING_STRATA_COVERAGE_MIN = 0.6;
  const COMPARE_CONTROL_WARNING_MIN_ROWS = 20;
  const COMPARE_CONTROL_WARNING_MIN_STRATA = 3;
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
  const DASHBOARD_UI_STATE_VERSION = 1;
  const DASHBOARD_UI_STATE_STORAGE_KEY = "cookimport.stats_dashboard.ui_state.v1";
  const DASHBOARD_UI_STATE_SERVER_PATH = "assets/dashboard_ui_state.json";
  const DASHBOARD_UI_STATE_SYNC_INTERVAL_MS = 3000;
  let dashboardUiStateLoadAttempted = false;
  let dashboardUiProgramStateLoadAttempted = false;
  let dashboardUiProgramStoreAvailable = false;
  let dashboardUiProgramSyncInFlight = false;
  let dashboardUiProgramSyncTimer = null;
  let dashboardUiStorageResolved = false;
  let dashboardUiStorage = null;
  let dashboardUiStateSavedAtMs = -1;
  let dashboardUiStatePersistSuppressed = false;

  function dashboardUiStorageHandle() {
    if (dashboardUiStorageResolved) return dashboardUiStorage;
    dashboardUiStorageResolved = true;
    if (typeof window === "undefined") return null;
    try {
      const storage = window.localStorage;
      if (!storage) return null;
      const probeKey = "__cookimport_dashboard_probe__";
      storage.setItem(probeKey, "1");
      storage.removeItem(probeKey);
      dashboardUiStorage = storage;
      return dashboardUiStorage;
    } catch (error) {
      dashboardUiStorage = null;
      return null;
    }
  }

  function persistDashboardUiStateToBrowserStorage(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return;
    try {
      const storage = dashboardUiStorageHandle();
      if (storage) {
        storage.setItem(DASHBOARD_UI_STATE_STORAGE_KEY, JSON.stringify(payload));
      }
    } catch (error) {
      // Ignore storage failures (private mode, quota, sandboxed contexts).
    }
  }

  function sanitizeColumnWidthsMap(rawMap) {
    if (!rawMap || typeof rawMap !== "object" || Array.isArray(rawMap)) {
      return Object.create(null);
    }
    const next = Object.create(null);
    Object.keys(rawMap).forEach(columnKey => {
      const key = String(columnKey || "").trim();
      if (!key) return;
      const width = Number(rawMap[columnKey]);
      if (!Number.isFinite(width) || width <= 0) return;
      next[key] = Math.max(72, width);
    });
    return next;
  }

  function sanitizeDashboardTableColumnWidths(rawTableWidths) {
    if (!rawTableWidths || typeof rawTableWidths !== "object" || Array.isArray(rawTableWidths)) {
      return Object.create(null);
    }
    const next = Object.create(null);
    Object.keys(rawTableWidths).forEach(tableKey => {
      const key = String(tableKey || "").trim();
      if (!key) return;
      const columnWidths = sanitizeColumnWidthsMap(rawTableWidths[tableKey]);
      if (!Object.keys(columnWidths).length) return;
      next[key] = columnWidths;
    });
    return next;
  }

  function dashboardTableColumnWidth(tableKey, columnKey) {
    const table = String(tableKey || "").trim();
    const column = String(columnKey || "").trim();
    if (!table || !column) return null;
    const rawMap = dashboardTableColumnWidths[table];
    if (!rawMap || typeof rawMap !== "object" || Array.isArray(rawMap)) return null;
    const width = Number(rawMap[column]);
    if (!Number.isFinite(width) || width <= 0) return null;
    return Math.max(72, width);
  }

  function setDashboardTableColumnWidth(tableKey, columnKey, width) {
    const table = String(tableKey || "").trim();
    const column = String(columnKey || "").trim();
    const nextWidth = Number(width);
    if (!table || !column || !Number.isFinite(nextWidth) || nextWidth <= 0) return;
    let rawMap = dashboardTableColumnWidths[table];
    if (!rawMap || typeof rawMap !== "object" || Array.isArray(rawMap)) {
      rawMap = Object.create(null);
      dashboardTableColumnWidths[table] = rawMap;
    }
    rawMap[column] = Math.max(72, nextWidth);
  }

  function clearDashboardTableColumnWidths(tableKey) {
    const table = String(tableKey || "").trim();
    if (!table) return;
    delete dashboardTableColumnWidths[table];
  }

  function normalizePreviousRunsColumnFilterMode(value) {
    const key = String(value || "and").trim().toLowerCase();
    return key === "or" ? "or" : "and";
  }

  function normalizePreviousRunsColumnFilterGlobalMode(value) {
    return normalizePreviousRunsColumnFilterMode(value);
  }

  function normalizePerLabelRollingWindowSize(value) {
    const parsed = Number.parseInt(String(value == null ? "" : value).trim(), 10);
    if (!Number.isFinite(parsed)) return 10;
    return Math.max(PER_LABEL_ROLLING_WINDOW_MIN, Math.min(PER_LABEL_ROLLING_WINDOW_MAX, parsed));
  }

  function normalizePerLabelComparisonMode(value) {
    const key = String(value || "delta").trim().toLowerCase();
    return key === "point_value" ? "point_value" : "delta";
  }

  function normalizeCompareControlViewMode(value) {
    const key = String(value || "discover").trim().toLowerCase();
    return COMPARE_CONTROL_VIEW_MODES.has(key) ? key : "discover";
  }

  function uniqueStringList(values) {
    const seen = new Set();
    const ordered = [];
    (Array.isArray(values) ? values : []).forEach(value => {
      const key = String(value || "").trim();
      if (!key || seen.has(key)) return;
      seen.add(key);
      ordered.push(key);
    });
    return ordered;
  }

  function normalizeCompareControlState(rawState) {
    const source = rawState && typeof rawState === "object" && !Array.isArray(rawState)
      ? rawState
      : Object.create(null);
    const base = compareControlDefaultState();
    return {
      outcome_field: String(source.outcome_field || base.outcome_field).trim() || base.outcome_field,
      compare_field: String(source.compare_field || "").trim(),
      hold_constant_fields: uniqueStringList(source.hold_constant_fields),
      split_field: String(source.split_field || "").trim(),
      view_mode: normalizeCompareControlViewMode(source.view_mode),
      selected_groups: uniqueStringList(source.selected_groups),
    };
  }

  function resetCompareControlState() {
    compareControlState = compareControlDefaultState();
    compareControlStatusMessage = "Compare & Control reset to default state.";
    compareControlStatusIsError = false;
  }

  function sanitizePreviousRunsPresetName(rawName) {
    const text = String(rawName || "").trim().replace(/\\s+/g, " ");
    if (!text) return "";
    return text.slice(0, PREVIOUS_RUNS_PRESET_NAME_MAX);
  }

  function sanitizePreviousRunsPresetState(rawPreset) {
    if (!rawPreset || typeof rawPreset !== "object" || Array.isArray(rawPreset)) {
      return null;
    }
    const visibleColumns = Array.isArray(rawPreset.visible_columns)
      ? rawPreset.visible_columns
        .map(fieldName => String(fieldName || "").trim())
        .filter(Boolean)
      : [];
    const columnFilters = Object.create(null);
    const columnFilterModes = Object.create(null);
    const rawColumnFilters = rawPreset.column_filters;
    if (rawColumnFilters && typeof rawColumnFilters === "object" && !Array.isArray(rawColumnFilters)) {
      Object.keys(rawColumnFilters).forEach(fieldName => {
        const key = String(fieldName || "").trim();
        if (!key) return;
        const normalized = normalizePreviousRunsColumnFilterList(rawColumnFilters[fieldName]);
        if (!normalized.length) return;
        columnFilters[key] = normalized;
      });
    }
    const rawColumnFilterModes = rawPreset.column_filter_modes;
    if (rawColumnFilterModes && typeof rawColumnFilterModes === "object" && !Array.isArray(rawColumnFilterModes)) {
      Object.keys(rawColumnFilterModes).forEach(fieldName => {
        const key = String(fieldName || "").trim();
        if (!key) return;
        if (!Object.prototype.hasOwnProperty.call(columnFilters, key)) return;
        columnFilterModes[key] = normalizePreviousRunsColumnFilterMode(rawColumnFilterModes[key]);
      });
    }
    const rawQuickFilters = rawPreset.quick_filters;
    const quickFilters = {
      exclude_ai_tests: false,
      official_full_golden_only: true,
    };
    if (rawQuickFilters && typeof rawQuickFilters === "object") {
      if (Object.prototype.hasOwnProperty.call(rawQuickFilters, "exclude_ai_tests")) {
        quickFilters.exclude_ai_tests = Boolean(rawQuickFilters.exclude_ai_tests);
      }
      if (Object.prototype.hasOwnProperty.call(rawQuickFilters, "official_full_golden_only")) {
        quickFilters.official_full_golden_only = Boolean(rawQuickFilters.official_full_golden_only);
      }
    }
    const rawSort = rawPreset.sort;
    const sort = {
      field: "run_timestamp",
      direction: "desc",
    };
    if (rawSort && typeof rawSort === "object" && !Array.isArray(rawSort)) {
      const sortField = String(rawSort.field || "").trim();
      if (sortField) sort.field = sortField;
      const sortDirection = String(rawSort.direction || "").toLowerCase();
      if (sortDirection === "asc" || sortDirection === "desc") {
        sort.direction = sortDirection;
      }
    }
    const compareControl = normalizeCompareControlState(rawPreset.compare_control);
    const columnFilterGlobalMode = Object.prototype.hasOwnProperty.call(rawPreset, "column_filter_global_mode")
      ? normalizePreviousRunsColumnFilterGlobalMode(rawPreset.column_filter_global_mode)
      : "and";
    return {
      visible_columns: visibleColumns,
      column_filters: columnFilters,
      column_filter_modes: columnFilterModes,
      column_filter_global_mode: columnFilterGlobalMode,
      quick_filters: quickFilters,
      column_widths: sanitizeColumnWidthsMap(rawPreset.column_widths),
      sort,
      compare_control: compareControl,
    };
  }

  function sanitizePreviousRunsPresetMap(rawPresets) {
    if (!rawPresets || typeof rawPresets !== "object" || Array.isArray(rawPresets)) {
      return Object.create(null);
    }
    const next = Object.create(null);
    Object.keys(rawPresets).forEach(rawName => {
      const name = sanitizePreviousRunsPresetName(rawName);
      if (!name) return;
      const preset = sanitizePreviousRunsPresetState(rawPresets[rawName]);
      if (!preset) return;
      next[name] = preset;
    });
    return next;
  }

  function dashboardUiStateSavedAtMsFromValue(rawValue) {
    const text = String(rawValue || "").trim();
    if (!text) return -1;
    const parsed = Date.parse(text);
    return Number.isFinite(parsed) ? parsed : -1;
  }

  function applyDashboardUiStatePayload(parsed, savedAtMs) {
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return false;
    const nextSavedAtMs = Number.isFinite(savedAtMs) ? savedAtMs : -1;
    if (dashboardUiStateSavedAtMs >= 0 && nextSavedAtMs >= 0 && nextSavedAtMs <= dashboardUiStateSavedAtMs) {
      return false;
    }
    if (dashboardUiStateSavedAtMs >= 0 && nextSavedAtMs < 0) return false;
    const version = Number(parsed.version || 0);
    if (version && version !== DASHBOARD_UI_STATE_VERSION) return false;
    dashboardTableColumnWidths = sanitizeDashboardTableColumnWidths(parsed.table_column_widths);
    previousRunsViewPresets = sanitizePreviousRunsPresetMap(parsed.previous_runs_presets);
    const previousRuns = parsed.previous_runs;
    if (!previousRuns || typeof previousRuns !== "object") {
      dashboardUiStateSavedAtMs = nextSavedAtMs >= 0 ? nextSavedAtMs : 0;
      return true;
    }

    if (Array.isArray(previousRuns.visible_columns)) {
      previousRunsVisibleColumns = previousRuns.visible_columns
        .map(fieldName => String(fieldName || "").trim())
        .filter(Boolean);
    }

    const rawColumnFilters = previousRuns.column_filters;
    if (rawColumnFilters && typeof rawColumnFilters === "object" && !Array.isArray(rawColumnFilters)) {
      const nextColumnFilters = Object.create(null);
      Object.keys(rawColumnFilters).forEach(fieldName => {
        const key = String(fieldName || "").trim();
        if (!key) return;
        const normalized = normalizePreviousRunsColumnFilterList(rawColumnFilters[fieldName]);
        if (!normalized.length) return;
        nextColumnFilters[key] = normalized;
      });
      previousRunsColumnFilters = nextColumnFilters;
    }
    const rawColumnFilterModes = previousRuns.column_filter_modes;
    if (rawColumnFilterModes && typeof rawColumnFilterModes === "object" && !Array.isArray(rawColumnFilterModes)) {
      const nextModes = Object.create(null);
      Object.keys(rawColumnFilterModes).forEach(fieldName => {
        const key = String(fieldName || "").trim();
        if (!key) return;
        if (!Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, key)) return;
        nextModes[key] = normalizePreviousRunsColumnFilterMode(rawColumnFilterModes[fieldName]);
      });
      previousRunsColumnFilterModes = nextModes;
    }
    if (Object.prototype.hasOwnProperty.call(previousRuns, "column_filter_global_mode")) {
      previousRunsColumnFilterGlobalMode = normalizePreviousRunsColumnFilterGlobalMode(
        previousRuns.column_filter_global_mode
      );
    } else {
      previousRunsColumnFilterGlobalMode = "and";
    }

    const rawQuickFilters = previousRuns.quick_filters;
    if (rawQuickFilters && typeof rawQuickFilters === "object") {
      if (Object.prototype.hasOwnProperty.call(rawQuickFilters, "exclude_ai_tests")) {
        previousRunsQuickFilters.exclude_ai_tests = Boolean(rawQuickFilters.exclude_ai_tests);
      }
      if (Object.prototype.hasOwnProperty.call(rawQuickFilters, "official_full_golden_only")) {
        previousRunsQuickFilters.official_full_golden_only = Boolean(rawQuickFilters.official_full_golden_only);
      }
    }
    if (Object.prototype.hasOwnProperty.call(previousRuns, "per_label_rolling_window_size")) {
      perLabelRollingWindowSize = normalizePerLabelRollingWindowSize(
        previousRuns.per_label_rolling_window_size
      );
    }
    if (Object.prototype.hasOwnProperty.call(previousRuns, "per_label_comparison_mode")) {
      perLabelComparisonMode = normalizePerLabelComparisonMode(
        previousRuns.per_label_comparison_mode
      );
    }

    const rawColumnWidths = previousRuns.column_widths;
    if (rawColumnWidths && typeof rawColumnWidths === "object" && !Array.isArray(rawColumnWidths)) {
      const nextColumnWidths = sanitizeColumnWidthsMap(rawColumnWidths);
      previousRunsColumnWidths = nextColumnWidths;
      Object.keys(nextColumnWidths).forEach(fieldName => {
        setDashboardTableColumnWidth("previous-runs-table", fieldName, nextColumnWidths[fieldName]);
      });
    } else {
      previousRunsColumnWidths = sanitizeColumnWidthsMap(
        dashboardTableColumnWidths["previous-runs-table"]
      );
    }

    const rawSort = previousRuns.sort;
    if (rawSort && typeof rawSort === "object" && !Array.isArray(rawSort)) {
      const sortField = String(rawSort.field || "").trim();
      if (sortField) {
        previousRunsSortField = sortField;
      }
      const sortDirection = String(rawSort.direction || "").toLowerCase();
      if (sortDirection === "asc" || sortDirection === "desc") {
        previousRunsSortDirection = sortDirection;
      }
    }

    if (Object.prototype.hasOwnProperty.call(previousRuns, "compare_control")) {
      compareControlState = normalizeCompareControlState(previousRuns.compare_control);
    } else {
      compareControlState = normalizeCompareControlState(compareControlState);
    }
    const selectedPreset = sanitizePreviousRunsPresetName(previousRuns.selected_preset);
    previousRunsSelectedPreset = Object.prototype.hasOwnProperty.call(previousRunsViewPresets, selectedPreset)
      ? selectedPreset
      : "";
    dashboardUiStateSavedAtMs = nextSavedAtMs >= 0 ? nextSavedAtMs : 0;
    return true;
  }

  function loadDashboardUiState() {
    if (dashboardUiStateLoadAttempted) return;
    dashboardUiStateLoadAttempted = true;
    const storage = dashboardUiStorageHandle();
    if (!storage) return;
    let parsed = null;
    try {
      parsed = JSON.parse(storage.getItem(DASHBOARD_UI_STATE_STORAGE_KEY) || "null");
    } catch (error) {
      return;
    }
    if (!parsed || typeof parsed !== "object") return;
    applyDashboardUiStatePayload(
      parsed,
      dashboardUiStateSavedAtMsFromValue(parsed.saved_at)
    );
  }

  function loadDashboardUiStateFromProgramStore() {
    const options = arguments.length > 0 ? arguments[0] : null;
    const force = Boolean(options && options.force);
    if (!force && dashboardUiProgramStateLoadAttempted) return Promise.resolve(false);
    if (!force) {
      dashboardUiProgramStateLoadAttempted = true;
    }
    if (dashboardUiProgramSyncInFlight) return Promise.resolve(false);
    if (typeof fetch !== "function") return Promise.resolve(false);
    dashboardUiProgramSyncInFlight = true;
    return fetch(DASHBOARD_UI_STATE_SERVER_PATH, { cache: "no-store" })
      .then(response => {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(parsed => {
        dashboardUiProgramStoreAvailable = true;
        const applied = applyDashboardUiStatePayload(
          parsed,
          dashboardUiStateSavedAtMsFromValue(parsed && parsed.saved_at)
        );
        if (applied) {
          persistDashboardUiStateToBrowserStorage(parsed);
        }
        return applied;
      })
      .catch(() => false)
      .finally(() => {
        dashboardUiProgramSyncInFlight = false;
      });
  }

  function startDashboardUiProgramSyncLoop() {
    if (typeof window === "undefined") return;
    if (dashboardUiProgramSyncTimer != null) return;
    dashboardUiProgramSyncTimer = window.setInterval(() => {
      loadDashboardUiStateFromProgramStore({ force: true }).then(applied => {
        if (!applied) return;
        const previous = dashboardUiStatePersistSuppressed;
        dashboardUiStatePersistSuppressed = true;
        try {
          setupPreviousRunsQuickFilters();
          setupPreviousRunsGlobalFilterModeControl();
          setupCompareControlControls();
          setupPerLabelControls();
          renderPreviousRunsColumnEditor();
          renderAll();
        } finally {
          dashboardUiStatePersistSuppressed = previous;
        }
      });
    }, DASHBOARD_UI_STATE_SYNC_INTERVAL_MS);
  }

  function buildDashboardUiStatePayload() {
    const savedAt = new Date().toISOString();
    dashboardUiStateSavedAtMs = dashboardUiStateSavedAtMsFromValue(savedAt);
    const visibleColumns = previousRunsVisibleColumns
      .map(fieldName => String(fieldName || "").trim())
      .filter(Boolean);
    const columnFilters = Object.create(null);
    const columnFilterModes = Object.create(null);
    Object.keys(previousRunsColumnFilters).forEach(fieldName => {
      const clauses = previousRunsColumnFilterClauses(fieldName);
      if (!clauses.length) return;
      columnFilters[fieldName] = clauses.map(clause => ({
        operator: clause.operator,
        value: clause.value,
      }));
      columnFilterModes[fieldName] = previousRunsColumnFilterMode(fieldName);
    });
    const columnWidths = Object.create(null);
    Object.keys(previousRunsColumnWidths).forEach(fieldName => {
      const key = String(fieldName || "").trim();
      if (!key) return;
      const width = Number(previousRunsColumnWidths[fieldName]);
      if (!Number.isFinite(width) || width <= 0) return;
      columnWidths[key] = Math.max(72, width);
      setDashboardTableColumnWidth("previous-runs-table", key, width);
    });
    const tableColumnWidths = sanitizeDashboardTableColumnWidths(dashboardTableColumnWidths);
    if (Object.keys(columnWidths).length) {
      tableColumnWidths["previous-runs-table"] = Object.assign(Object.create(null), columnWidths);
    } else {
      delete tableColumnWidths["previous-runs-table"];
    }
    const previousRunsPresets = Object.create(null);
    Object.keys(previousRunsViewPresets).forEach(rawName => {
      const name = sanitizePreviousRunsPresetName(rawName);
      if (!name) return;
      const preset = sanitizePreviousRunsPresetState(previousRunsViewPresets[rawName]);
      if (!preset) return;
      previousRunsPresets[name] = preset;
    });
    const selectedPreset = sanitizePreviousRunsPresetName(previousRunsSelectedPreset);
    const selectedPresetName = Object.prototype.hasOwnProperty.call(previousRunsPresets, selectedPreset)
      ? selectedPreset
      : "";
    const payload = {
      version: DASHBOARD_UI_STATE_VERSION,
      previous_runs: {
        visible_columns: visibleColumns,
        column_filters: columnFilters,
        column_filter_modes: columnFilterModes,
        column_filter_global_mode: normalizePreviousRunsColumnFilterGlobalMode(
          previousRunsColumnFilterGlobalMode
        ),
        quick_filters: {
          exclude_ai_tests: Boolean(previousRunsQuickFilters.exclude_ai_tests),
          official_full_golden_only: Boolean(previousRunsQuickFilters.official_full_golden_only),
        },
        per_label_rolling_window_size: normalizePerLabelRollingWindowSize(perLabelRollingWindowSize),
        per_label_comparison_mode: normalizePerLabelComparisonMode(perLabelComparisonMode),
        column_widths: columnWidths,
        sort: {
          field: String(previousRunsSortField || "run_timestamp"),
          direction: previousRunsSortDirection === "asc" ? "asc" : "desc",
        },
        compare_control: normalizeCompareControlState(compareControlState),
        selected_preset: selectedPresetName,
      },
      previous_runs_presets: previousRunsPresets,
      table_column_widths: tableColumnWidths,
      saved_at: savedAt,
    };
    return payload;
  }

  function persistDashboardUiStateToProgramStore(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return;
    if (typeof fetch !== "function") return;
    try {
      fetch(DASHBOARD_UI_STATE_SERVER_PATH, {
        method: "PUT",
        cache: "no-store",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }).catch(() => {
        // Ignore program-side sync failures when dashboard is opened as plain static HTML.
      });
    } catch (error) {
      // Ignore program-side sync failures when dashboard is opened as plain static HTML.
    }
  }

  function persistDashboardUiState() {
    if (dashboardUiStatePersistSuppressed) return;
    const payload = buildDashboardUiStatePayload();
    persistDashboardUiStateToBrowserStorage(payload);
    persistDashboardUiStateToProgramStore(payload);
  }

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
    applyHighchartsGlobalDefaults();
    loadDashboardUiState();
    loadDashboardUiStateFromProgramStore()
      .then(() => {
        renderHeader();
        setupPreviousRunsFilters();
        renderAll();
        startDashboardUiProgramSyncLoop();
      });
  }

  function applyHighchartsGlobalDefaults() {
    if (
      typeof window === "undefined" ||
      !window.Highcharts ||
      typeof window.Highcharts.setOptions !== "function"
    ) {
      return;
    }
    window.Highcharts.setOptions({
      time: {
        useUTC: false,
      },
      chart: {
        zooming: {
          mouseWheel: {
            enabled: HIGHCHARTS_MOUSE_WHEEL_ZOOM_ENABLED,
          },
        },
      },
    });
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
    const m = text.match(/^(\\d{4})-(\\d{2})-(\\d{2})[T_](\\d{2})[.:](\\d{2})[.:](\\d{2})(?:_.+)?$/);
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

  function isTimestampTokenText(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    return /^\\d{4}-\\d{2}-\\d{2}[T_]\\d{2}[.:]\\d{2}[.:]\\d{2}(?:_.+)?$/.test(text);
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

  function benchmarkArtifactPath(record) {
    return String((record && record.artifact_dir) || "")
      .replace(/\\\\/g, "/")
      .toLowerCase();
  }

  function isSpeedBenchmarkRecord(record) {
    const path = benchmarkArtifactPath(record);
    return path.includes("/bench/speed/runs/");
  }

  function isAllMethodBenchmarkRecord(record) {
    const path = benchmarkArtifactPath(record);
    return path.includes("/all-method-benchmark/");
  }

  function isLikelyAiTestBenchmarkRecord(record) {
    const path = benchmarkArtifactPath(record);
    if (!path) return false;
    if (path.includes("/bench/")) return true;
    if (/(^|\\/)pytest-\\d+(\\/|$)/.test(path)) return true;
    if (/(^|\\/)test_[^/]+(\\/|$)/.test(path)) return true;
    const parts = path.split("/").filter(Boolean);
    for (let i = 0; i < parts.length; i++) {
      const segment = String(parts[i] || "").toLowerCase();
      const timestampSuffix = segment.match(
        /^(\\d{4}-\\d{2}-\\d{2}[t_]\\d{2}[.:]\\d{2}[.:]\\d{2})_(.+)$/
      );
      if (!timestampSuffix) continue;
      const suffix = String(timestampSuffix[2] || "").toLowerCase();
      if (/(^|[-_])(manual|smoke|test|debug|quick|probe|sample|trial)([-_]|$)/.test(suffix)) {
        return true;
      }
    }
    return false;
  }

  function isOfficialGoldenBenchmarkRecord(record) {
    const path = benchmarkArtifactPath(record);
    if (!path) return false;
    if (!path.includes("/benchmark-vs-golden/")) return false;
    if (!path.includes("/single-offline-benchmark/")) return false;
    const variant = benchmarkVariantForRecord(record);
    return variant === "vanilla" || variant === "codexfarm";
  }

  function activePreviousRunsQuickFilterLabels(enabled) {
    const state = enabled || {
      exclude_ai_tests: Boolean(previousRunsQuickFilters.exclude_ai_tests),
      official_full_golden_only: Boolean(previousRunsQuickFilters.official_full_golden_only),
    };
    const labels = [];
    if (state.exclude_ai_tests) labels.push("exclude AI test/smoke runs");
    if (state.official_full_golden_only) {
      labels.push("official single-offline vanilla/codexfarm runs only");
    }
    return labels;
  }

  function updatePreviousRunsQuickFiltersStatus(context) {
    const status = document.getElementById("quick-filters-status");
    if (!status) return;
    const sourceTotal = Number((context && context.source_total) || 0);
    const filteredTotal = Number((context && context.filtered_total) || 0);
    const labels = activePreviousRunsQuickFilterLabels(context ? context.enabled : null);
    const summary = labels.length ? labels.join("; ") : "none";
    const removedParts = [];
    if (context && context.removed_ai_tests > 0) {
      removedParts.push(String(context.removed_ai_tests) + " test rows");
    }
    if (context && context.removed_unofficial > 0) {
      removedParts.push(String(context.removed_unofficial) + " unofficial rows");
    }
    const removedText = removedParts.length
      ? " Removed: " + removedParts.join(", ") + "."
      : "";
    status.textContent =
      "Quick filters: " +
      summary +
      ". Showing " +
      filteredTotal +
      " of " +
      sourceTotal +
      " benchmark rows." +
      removedText;
  }

  function applyPreviousRunsQuickFilters(records, options) {
    const baseRecords = Array.isArray(records) ? records : [];
    const updateStatus = !options || options.updateStatus !== false;
    const enabled = {
      exclude_ai_tests: Boolean(previousRunsQuickFilters.exclude_ai_tests),
      official_full_golden_only: Boolean(previousRunsQuickFilters.official_full_golden_only),
    };
    let filtered = baseRecords;
    let removedAiTests = 0;
    let removedUnofficial = 0;

    if (enabled.exclude_ai_tests) {
      const next = [];
      filtered.forEach(record => {
        if (isLikelyAiTestBenchmarkRecord(record)) {
          removedAiTests += 1;
          return;
        }
        next.push(record);
      });
      filtered = next;
    }

    if (enabled.official_full_golden_only) {
      const next = [];
      filtered.forEach(record => {
        if (!isOfficialGoldenBenchmarkRecord(record)) {
          removedUnofficial += 1;
          return;
        }
        next.push(record);
      });
      filtered = next;
    }

    const context = {
      source_total: baseRecords.length,
      filtered_total: filtered.length,
      removed_ai_tests: removedAiTests,
      removed_unofficial: removedUnofficial,
      enabled,
    };
    if (updateStatus) {
      updatePreviousRunsQuickFiltersStatus(context);
    }
    return {
      records: filtered,
      context,
    };
  }

  function stagePassesExtractorFilter(record) {
    const extractor = epubExtractorEffective(record) || epubExtractorRequested(record);
    if (!extractor) return true;
    if (activeExtractors.size === 0) return false;
    return activeExtractors.has(extractor);
  }

  // ---- Previous-runs column filters ----
  function clearPreviousRunsTableColumnFilters() {
    previousRunsColumnFilters = Object.create(null);
    previousRunsColumnFilterModes = Object.create(null);
    previousRunsColumnFilterGlobalMode = "and";
    closePreviousRunsColumnFilterEditor();
  }

  function clearAllPreviousRunsFilters() {
    clearPreviousRunsTableColumnFilters();
    previousRunsQuickFilters.exclude_ai_tests = false;
    previousRunsQuickFilters.official_full_golden_only = false;
    setupPreviousRunsQuickFilters();
  }

  function setupPreviousRunsFilters() {
    previousRunsFieldOptions = collectBenchmarkFieldPaths();
    setupPerLabelControls();
    ensurePreviousRunsColumns();
    setupPreviousRunsColumnsControls();
    setupPreviousRunsQuickFilters();
    setupPreviousRunsGlobalFilterModeControl();
    setupPreviousRunsPresetControls();
    setupCompareControlControls();
    const clearBtn = document.getElementById("previous-runs-clear-filters");
    if (clearBtn && !clearBtn.dataset.bound) {
      clearBtn.addEventListener("click", () => {
        clearPreviousRunsTableColumnFilters();
        renderAll();
      });
      clearBtn.dataset.bound = "1";
    }
    const clearAllBtn = document.getElementById("previous-runs-clear-all-filters");
    if (clearAllBtn && !clearAllBtn.dataset.bound) {
      clearAllBtn.addEventListener("click", () => {
        clearAllPreviousRunsFilters();
        renderAll();
      });
      clearAllBtn.dataset.bound = "1";
    }
    renderPreviousRunsColumnEditor();
  }

  function setupPreviousRunsGlobalFilterModeControl() {
    const select = document.getElementById("previous-runs-global-filter-mode");
    if (!select) return;
    const normalized = normalizePreviousRunsColumnFilterGlobalMode(
      previousRunsColumnFilterGlobalMode
    );
    previousRunsColumnFilterGlobalMode = normalized;
    if (select.value !== normalized) {
      select.value = normalized;
    }
    if (select.dataset.bound) return;
    select.addEventListener("change", () => {
      previousRunsColumnFilterGlobalMode = normalizePreviousRunsColumnFilterGlobalMode(
        select.value
      );
      renderAll();
    });
    select.dataset.bound = "1";
  }

  function setupPreviousRunsQuickFilters() {
    const excludeTests = document.getElementById("quick-filter-exclude-ai-tests");
    const officialOnly = document.getElementById("quick-filter-official-only");
    if (excludeTests) {
      excludeTests.checked = Boolean(previousRunsQuickFilters.exclude_ai_tests);
      if (!excludeTests.dataset.bound) {
        excludeTests.addEventListener("change", () => {
          previousRunsQuickFilters.exclude_ai_tests = Boolean(excludeTests.checked);
          renderAll();
        });
        excludeTests.dataset.bound = "1";
      }
    }
    if (officialOnly) {
      officialOnly.checked = Boolean(previousRunsQuickFilters.official_full_golden_only);
      if (!officialOnly.dataset.bound) {
        officialOnly.addEventListener("change", () => {
          previousRunsQuickFilters.official_full_golden_only = Boolean(officialOnly.checked);
          renderAll();
        });
        officialOnly.dataset.bound = "1";
      }
    }
  }

  function previousRunsAvailableColumnFields() {
    const ordered = [];
    const seen = new Set();
    PREVIOUS_RUNS_DEFAULT_COLUMNS.concat(previousRunsFieldOptions).forEach(fieldName => {
      const key = String(fieldName || "").trim();
      if (!key || seen.has(key)) return;
      seen.add(key);
      ordered.push(key);
    });
    return ordered;
  }

  function ensurePreviousRunsColumns() {
    const available = new Set(previousRunsAvailableColumnFields());
    if (!available.has(previousRunsSortField)) {
      previousRunsSortField = "run_timestamp";
      previousRunsSortDirection = "desc";
    }
    const seed = previousRunsVisibleColumns.length
      ? previousRunsVisibleColumns
      : PREVIOUS_RUNS_DEFAULT_COLUMNS;
    const next = [];
    const seen = new Set();
    seed.forEach(fieldName => {
      const key = String(fieldName || "").trim();
      if (!key || !available.has(key) || seen.has(key)) return;
      seen.add(key);
      next.push(key);
    });
    if (!next.length) {
      const fallback = previousRunsAvailableColumnFields()[0] || "run_timestamp";
      next.push(fallback);
    }
    previousRunsVisibleColumns = next;
    prunePreviousRunsColumnFilters();
  }

  function prunePreviousRunsColumnFilters() {
    const available = new Set(previousRunsAvailableColumnFields());
    const next = Object.create(null);
    const nextModes = Object.create(null);
    Object.keys(previousRunsColumnFilters).forEach(fieldName => {
      if (!available.has(fieldName)) return;
      const clauses = previousRunsColumnFilterClauses(fieldName);
      if (!clauses.length) return;
      next[fieldName] = clauses.map(clause => ({
        operator: clause.operator,
        value: clause.value,
      }));
      nextModes[fieldName] = previousRunsColumnFilterMode(fieldName);
    });
    previousRunsColumnFilters = next;
    previousRunsColumnFilterModes = nextModes;
    if (previousRunsOpenFilterField && !available.has(previousRunsOpenFilterField)) {
      closePreviousRunsColumnFilterEditor();
    }
  }

  function normalizePreviousRunsColumnFilterClause(rawClause) {
    if (!rawClause || typeof rawClause !== "object" || Array.isArray(rawClause)) return null;
    const operator = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[rawClause.operator]
      ? String(rawClause.operator)
      : "contains";
    const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(operator);
    const value = unary ? "" : String(rawClause.value || "");
    if (!unary && value.trim() === "") return null;
    return {
      operator,
      value,
    };
  }

  function normalizePreviousRunsColumnFilterList(rawValue) {
    if (!rawValue) return [];
    const sourceList = Array.isArray(rawValue) ? rawValue : [rawValue];
    const next = [];
    const seen = new Set();
    sourceList.forEach(candidate => {
      const clause = normalizePreviousRunsColumnFilterClause(candidate);
      if (!clause) return;
      const dedupeKey = clause.operator + "::" + normalizeRuleValue(clause.value);
      if (seen.has(dedupeKey)) return;
      seen.add(dedupeKey);
      next.push(clause);
    });
    return next;
  }

  function previousRunsColumnFilterClauses(fieldName) {
    const raw = previousRunsColumnFilters[fieldName];
    if (!raw) return [];
    return normalizePreviousRunsColumnFilterList(raw);
  }

  function previousRunsColumnFilterMode(fieldName) {
    const key = String(fieldName || "").trim();
    if (!key) return "and";
    if (!Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, key)) {
      return "and";
    }
    return normalizePreviousRunsColumnFilterMode(previousRunsColumnFilterModes[key]);
  }

  function setPreviousRunsColumnFilterMode(fieldName, mode) {
    const key = String(fieldName || "").trim();
    if (!key) return false;
    if (!Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, key)) {
      delete previousRunsColumnFilterModes[key];
      return false;
    }
    previousRunsColumnFilterModes[key] = normalizePreviousRunsColumnFilterMode(mode);
    return true;
  }

  function openPreviousRunsColumnFilterEditor(fieldName) {
    const meta = previousRunsColumnMeta(fieldName);
    previousRunsOpenFilterField = String(fieldName || "");
    previousRunsOpenFilterDraft = {
      operator: meta.numeric ? "eq" : "contains",
      value: "",
    };
  }

  function closePreviousRunsColumnFilterEditor() {
    previousRunsOpenFilterField = "";
    previousRunsOpenFilterDraft = null;
  }

  function currentPreviousRunsColumnFilterDraft(fieldName) {
    const meta = previousRunsColumnMeta(fieldName);
    const fallbackOperator = meta.numeric ? "eq" : "contains";
    const fallback = {
      operator: fallbackOperator,
      value: "",
      active: false,
    };
    if (
      previousRunsOpenFilterField !== fieldName ||
      !previousRunsOpenFilterDraft ||
      typeof previousRunsOpenFilterDraft !== "object"
    ) {
      return fallback;
    }
    const draftOperator = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[previousRunsOpenFilterDraft.operator]
      ? String(previousRunsOpenFilterDraft.operator)
      : fallback.operator;
    const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(draftOperator);
    return {
      operator: draftOperator,
      value: unary ? "" : String(previousRunsOpenFilterDraft.value || ""),
      active: unary ? true : String(previousRunsOpenFilterDraft.value || "").trim() !== "",
    };
  }

  function previousRunsColumnMeta(fieldName) {
    const meta = PREVIOUS_RUNS_COLUMN_META[fieldName];
    if (meta) return meta;
    return {
      label: fieldName,
      title: fieldName,
      numeric: false,
    };
  }

  function previousRunsColumnFilterState(fieldName) {
    const clauses = previousRunsColumnFilterClauses(fieldName);
    const fallbackOperator = previousRunsColumnMeta(fieldName).numeric ? "eq" : "contains";
    if (!clauses.length) {
      return {
        operator: fallbackOperator,
        value: "",
        active: false,
      };
    }
    const operator = clauses[0].operator;
    const value = clauses[0].value;
    const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(operator);
    const active = unary ? true : String(value || "").trim() !== "";
    return {
      operator,
      value,
      active,
    };
  }

  function setPreviousRunsColumnFilterClauses(fieldName, clauses) {
    const key = String(fieldName || "").trim();
    if (!key) return false;
    const normalized = normalizePreviousRunsColumnFilterList(clauses);
    if (!normalized.length) {
      delete previousRunsColumnFilters[key];
      delete previousRunsColumnFilterModes[key];
      return false;
    }
    previousRunsColumnFilters[key] = normalized;
    previousRunsColumnFilterModes[key] = normalizePreviousRunsColumnFilterMode(
      previousRunsColumnFilterModes[key]
    );
    return true;
  }

  function setPreviousRunsColumnFilter(fieldName, operator, value) {
    const clause = normalizePreviousRunsColumnFilterClause({
      operator,
      value,
    });
    if (!clause) {
      clearPreviousRunsColumnFilter(fieldName);
      return false;
    }
    return setPreviousRunsColumnFilterClauses(fieldName, [clause]);
  }

  function addPreviousRunsColumnFilter(fieldName, operator, value) {
    const clause = normalizePreviousRunsColumnFilterClause({
      operator,
      value,
    });
    if (!clause) return false;
    const existing = previousRunsColumnFilterClauses(fieldName);
    const nextKey = clause.operator + "::" + normalizeRuleValue(clause.value);
    const hasMatch = existing.some(candidate => (
      candidate.operator + "::" + normalizeRuleValue(candidate.value) === nextKey
    ));
    if (hasMatch) {
      return false;
    }
    existing.push(clause);
    setPreviousRunsColumnFilterClauses(fieldName, existing);
    return true;
  }

  function removePreviousRunsColumnFilterAt(fieldName, index) {
    const clauses = previousRunsColumnFilterClauses(fieldName);
    if (!clauses.length) return false;
    const idx = Number(index);
    if (!Number.isInteger(idx) || idx < 0 || idx >= clauses.length) return false;
    clauses.splice(idx, 1);
    setPreviousRunsColumnFilterClauses(fieldName, clauses);
    return true;
  }

  function clearPreviousRunsColumnFilter(fieldName) {
    if (!Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, fieldName)) {
      return false;
    }
    delete previousRunsColumnFilters[fieldName];
    delete previousRunsColumnFilterModes[fieldName];
    return true;
  }

  function activePreviousRunsColumnFilters() {
    const ordered = [];
    const seenFields = new Set();
    const orderedFields = [];
    previousRunsVisibleColumns.forEach(fieldName => {
      if (Object.prototype.hasOwnProperty.call(previousRunsColumnFilters, fieldName)) {
        seenFields.add(fieldName);
        orderedFields.push(fieldName);
      }
    });
    Object.keys(previousRunsColumnFilters)
      .sort((left, right) => String(left).localeCompare(String(right)))
      .forEach(fieldName => {
        if (seenFields.has(fieldName)) return;
        seenFields.add(fieldName);
        orderedFields.push(fieldName);
      });
    orderedFields.forEach(fieldName => {
      const clauses = previousRunsColumnFilterClauses(fieldName);
      const combine_mode = previousRunsColumnFilterMode(fieldName);
      clauses.forEach((clause, clauseIndex) => {
        ordered.push({
          field: fieldName,
          operator: clause.operator,
          value: clause.value,
          combine_mode,
          clause_index: clauseIndex,
        });
      });
    });
    return ordered;
  }

  function previousRunsIconSvgPath(iconName) {
    if (iconName === "plus") return "M8 3.25v9.5M3.25 8h9.5";
    if (iconName === "minus") return "M3.25 8h9.5";
    return "M4.3 4.3l7.4 7.4M11.7 4.3l-7.4 7.4";
  }

  function setPreviousRunsIcon(button, iconName) {
    if (!(button instanceof HTMLElement)) return;
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.classList.add("previous-runs-icon-svg");
    const path = document.createElementNS(svgNS, "path");
    path.setAttribute("d", previousRunsIconSvgPath(iconName));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "1.8");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path);
    button.replaceChildren(svg);
  }

  function formatPreviousRunsColumnFilterSummary(fieldName, filter) {
    const label = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[filter.operator] || filter.operator;
    if (PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(filter.operator)) {
      return label;
    }
    return label + " " + String(filter.value || "");
  }

  function formatPreviousRunsColumnFiltersSummary(fieldName, clauses) {
    const list = Array.isArray(clauses) ? clauses : [];
    if (!list.length) return "No filter";
    const mode = previousRunsColumnFilterMode(fieldName);
    const joinLabel = " " + String(PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL[mode] || mode).toUpperCase() + " ";
    const shown = list
      .slice(0, 2)
      .map(clause => formatPreviousRunsColumnFilterSummary(fieldName, clause));
    if (list.length <= 2) {
      return shown.join(joinLabel);
    }
    return shown.join(joinLabel) + joinLabel + "+" + (list.length - 2) + " more";
  }

  function groupPreviousRunsFiltersByField(filters) {
    const groupsByField = new Map();
    const orderedGroups = [];
    (filters || []).forEach(filter => {
      const fieldName = String(filter.field || "").trim();
      if (!fieldName) return;
      let group = groupsByField.get(fieldName);
      if (!group) {
        group = {
          field: fieldName,
          mode: normalizePreviousRunsColumnFilterMode(filter.combine_mode),
          clauses: [],
        };
        groupsByField.set(fieldName, group);
        orderedGroups.push(group);
      }
      group.mode = normalizePreviousRunsColumnFilterMode(filter.combine_mode || group.mode);
      group.clauses.push({
        operator: String(filter.operator || "contains"),
        value: String(filter.value || ""),
      });
    });
    return orderedGroups;
  }

  function recordMatchesPreviousRunsFilterGroups(record, groupedFilters, globalMode) {
    const groups = (groupedFilters || []).filter(group => (
      group && Array.isArray(group.clauses) && group.clauses.length
    ));
    if (!groups.length) return true;
    const topMode = normalizePreviousRunsColumnFilterGlobalMode(globalMode);
    const matchesGroup = group => {
      if (!group || !Array.isArray(group.clauses) || !group.clauses.length) return true;
      const mode = normalizePreviousRunsColumnFilterMode(group.mode);
      const evaluate = clause => {
        const value = previousRunsFieldValue(record, group.field);
        return evaluatePreviousRunsFilterOperator(value, clause.operator, clause.value);
      };
      if (mode === "or") {
        return group.clauses.some(evaluate);
      }
      return group.clauses.every(evaluate);
    };
    if (topMode === "or") {
      return groups.some(matchesGroup);
    }
    return groups.every(matchesGroup);
  }

  function setupCompareControlControls() {
    const panel = document.getElementById("compare-control-panel");
    const viewMode = document.getElementById("compare-control-view-mode");
    const outcomeField = document.getElementById("compare-control-outcome-field");
    const compareField = document.getElementById("compare-control-compare-field");
    const splitField = document.getElementById("compare-control-split-field");
    const holdFields = document.getElementById("compare-control-hold-fields");
    const groupSelection = document.getElementById("compare-control-group-selection");
    const results = document.getElementById("compare-control-results");
    const filterSubset = document.getElementById("compare-control-filter-subset");
    const clearSelection = document.getElementById("compare-control-clear-selection");
    const resetButton = document.getElementById("compare-control-reset");
    if (
      !panel ||
      !viewMode ||
      !outcomeField ||
      !compareField ||
      !splitField ||
      !holdFields ||
      !groupSelection ||
      !results ||
      !filterSubset ||
      !clearSelection ||
      !resetButton
    ) {
      return;
    }

    if (!viewMode.dataset.bound) {
      viewMode.addEventListener("change", () => {
        compareControlState.view_mode = normalizeCompareControlViewMode(viewMode.value);
        renderAll();
      });
      viewMode.dataset.bound = "1";
    }
    if (!outcomeField.dataset.bound) {
      outcomeField.addEventListener("change", () => {
        compareControlState.outcome_field = String(outcomeField.value || "").trim();
        renderAll();
      });
      outcomeField.dataset.bound = "1";
    }
    if (!compareField.dataset.bound) {
      compareField.addEventListener("change", () => {
        compareControlState.compare_field = String(compareField.value || "").trim();
        compareControlState.selected_groups = [];
        if (!compareControlState.compare_field) {
          compareControlState.view_mode = "discover";
        }
        renderAll();
      });
      compareField.dataset.bound = "1";
    }
    if (!splitField.dataset.bound) {
      splitField.addEventListener("change", () => {
        compareControlState.split_field = String(splitField.value || "").trim();
        renderAll();
      });
      splitField.dataset.bound = "1";
    }
    if (!holdFields.dataset.bound) {
      holdFields.addEventListener("change", event => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        if (!target.classList.contains("compare-control-hold-checkbox")) return;
        const fieldName = String(target.value || "").trim();
        if (!fieldName) return;
        const current = new Set(uniqueStringList(compareControlState.hold_constant_fields));
        if (target.checked) {
          current.add(fieldName);
        } else {
          current.delete(fieldName);
        }
        compareControlState.hold_constant_fields = Array.from(current);
        renderAll();
      });
      holdFields.dataset.bound = "1";
    }
    if (!groupSelection.dataset.bound) {
      groupSelection.addEventListener("change", event => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        if (!target.classList.contains("compare-control-group-checkbox")) return;
        const groupKey = String(target.value || "").trim();
        if (!groupKey) return;
        const current = new Set(uniqueStringList(compareControlState.selected_groups));
        if (target.checked) {
          current.add(groupKey);
        } else {
          current.delete(groupKey);
        }
        compareControlState.selected_groups = Array.from(current);
        renderAll();
      });
      groupSelection.dataset.bound = "1";
    }
    if (!results.dataset.bound) {
      results.addEventListener("click", event => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const card = target.closest(".compare-control-discovery-card");
        if (!(card instanceof HTMLElement)) return;
        const fieldName = String(card.getAttribute("data-compare-field") || "").trim();
        if (!fieldName) return;
        compareControlState.compare_field = fieldName;
        compareControlState.view_mode = "raw";
        compareControlState.selected_groups = [];
        compareControlStatusMessage = "Selected " + fieldName + " from discovery.";
        compareControlStatusIsError = false;
        renderAll();
      });
      results.dataset.bound = "1";
    }
    if (!filterSubset.dataset.bound) {
      filterSubset.addEventListener("click", () => {
        const applied = syncCompareControlSelectionToTableFilters();
        compareControlStatusMessage = applied.message;
        compareControlStatusIsError = !applied.applied;
        renderAll();
      });
      filterSubset.dataset.bound = "1";
    }
    if (!clearSelection.dataset.bound) {
      clearSelection.addEventListener("click", () => {
        compareControlState.selected_groups = [];
        compareControlStatusMessage = "Cleared selected groups.";
        compareControlStatusIsError = false;
        renderAll();
      });
      clearSelection.dataset.bound = "1";
    }
    if (!resetButton.dataset.bound) {
      resetButton.addEventListener("click", () => {
        resetCompareControlState();
        renderAll();
      });
      resetButton.dataset.bound = "1";
    }
  }

  function compareControlFieldLabel(fieldName) {
    return analysisFieldLabel(fieldName);
  }

  function compareControlFieldSortValue(fieldInfo) {
    if (!fieldInfo) return 0;
    return Number(fieldInfo.non_empty_count || 0);
  }

  function buildCompareControlFieldCatalog(records) {
    const byField = Object.create(null);
    const orderedFields = [];
    const seen = new Set();

    function considerField(fieldName) {
      const key = String(fieldName || "").trim();
      if (!key || seen.has(key) || COMPARE_CONTROL_FIELD_SKIP.has(key)) return;
      seen.add(key);
      const valueCounts = Object.create(null);
      const numericValues = [];
      let nonEmpty = 0;
      let numericCount = 0;
      records.forEach(record => {
        const rawValue = previousRunsFieldValue(record, key);
        if (isEmptyRuleValue(rawValue)) return;
        const comparableKey = analysisComparableValue(rawValue);
        if (!Object.prototype.hasOwnProperty.call(valueCounts, comparableKey)) {
          valueCounts[comparableKey] = {
            key: comparableKey,
            label: analysisDisplayValue(rawValue, comparableKey),
            count: 0,
          };
        }
        valueCounts[comparableKey].count += 1;
        nonEmpty += 1;
        const numeric = maybeNumber(rawValue);
        if (numeric != null) {
          numericCount += 1;
          numericValues.push(numeric);
        }
      });
      const categories = Object.values(valueCounts).sort((left, right) => {
        if (right.count !== left.count) return right.count - left.count;
        return String(left.label).localeCompare(String(right.label), undefined, { numeric: true });
      });
      const distinctCount = categories.length;
      if (distinctCount < 2) return;
      const numeric = nonEmpty > 0 && numericCount === nonEmpty;
      const info = {
        field: key,
        label: compareControlFieldLabel(key),
        numeric,
        non_empty_count: nonEmpty,
        distinct_count: distinctCount,
        categories: numeric ? [] : categories.slice(0, 120),
        numeric_min: numericValues.length ? Math.min(...numericValues) : null,
        numeric_max: numericValues.length ? Math.max(...numericValues) : null,
      };
      byField[key] = info;
      orderedFields.push(info);
    }

    COMPARE_CONTROL_OUTCOME_PREFERRED.forEach(considerField);
    ANALYSIS_FIELD_PREFERRED.forEach(considerField);
    PREVIOUS_RUNS_DEFAULT_COLUMNS.forEach(considerField);
    previousRunsFieldOptions.forEach(considerField);
    orderedFields.sort((left, right) => {
      const sizeGap = compareControlFieldSortValue(right) - compareControlFieldSortValue(left);
      if (sizeGap !== 0) return sizeGap;
      return String(left.label || left.field).localeCompare(
        String(right.label || right.field),
        undefined,
        { numeric: true },
      );
    });
    const numericFields = orderedFields.filter(field => field.numeric);
    const categoricalFields = orderedFields.filter(field => !field.numeric);
    return {
      fields: orderedFields,
      by_field: byField,
      numeric_fields: numericFields,
      categorical_fields: categoricalFields,
    };
  }

  function chooseDefaultCompareOutcome(catalog) {
    const byField = (catalog && catalog.by_field) || Object.create(null);
    for (const fieldName of COMPARE_CONTROL_OUTCOME_PREFERRED) {
      const info = byField[fieldName];
      if (info && info.numeric) return fieldName;
    }
    const numericField = (catalog && catalog.numeric_fields || []).find(Boolean);
    if (numericField) return numericField.field;
    return COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD;
  }

  function normalizeCompareControlStateForCatalog(rawState, catalog) {
    const state = normalizeCompareControlState(rawState);
    const byField = (catalog && catalog.by_field) || Object.create(null);
    const defaultOutcome = chooseDefaultCompareOutcome(catalog);
    if (!byField[state.outcome_field] || !byField[state.outcome_field].numeric) {
      state.outcome_field = defaultOutcome;
    }
    if (state.compare_field && !byField[state.compare_field]) {
      state.compare_field = "";
    }
    if (state.compare_field === state.outcome_field) {
      state.compare_field = "";
    }
    state.hold_constant_fields = state.hold_constant_fields.filter(fieldName => (
      byField[fieldName] &&
      fieldName !== state.outcome_field &&
      fieldName !== state.compare_field
    ));
    if (!byField[state.split_field] || state.split_field === state.outcome_field || state.split_field === state.compare_field) {
      state.split_field = "";
    }
    if (!state.compare_field) {
      state.view_mode = "discover";
      state.selected_groups = [];
    } else {
      state.view_mode = normalizeCompareControlViewMode(state.view_mode);
      const compareField = byField[state.compare_field];
      if (!compareField || compareField.numeric) {
        state.selected_groups = [];
      } else {
        const allowed = new Set(
          (compareField.categories || [])
            .map(entry => String(entry.key || "").trim())
            .filter(Boolean)
            .filter(value => value !== "__EMPTY__")
        );
        state.selected_groups = state.selected_groups.filter(value => allowed.has(value));
      }
    }
    return state;
  }

  function compareControlPairs(records, outcomeField, compareField) {
    const pairs = [];
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      const compare = maybeNumber(previousRunsFieldValue(record, compareField));
      if (outcome == null || compare == null) return;
      pairs.push({ x: compare, y: outcome, record });
    });
    return pairs;
  }

  function rankWithTies(values) {
    const indexed = values
      .map((value, index) => ({ value, index }))
      .sort((left, right) => left.value - right.value);
    const ranks = new Array(values.length);
    let idx = 0;
    while (idx < indexed.length) {
      let end = idx;
      while (end + 1 < indexed.length && indexed[end + 1].value === indexed[idx].value) {
        end += 1;
      }
      const rank = (idx + end + 2) / 2;
      for (let pos = idx; pos <= end; pos += 1) {
        ranks[indexed[pos].index] = rank;
      }
      idx = end + 1;
    }
    return ranks;
  }

  function pearsonCorrelation(xs, ys) {
    if (!Array.isArray(xs) || !Array.isArray(ys) || xs.length !== ys.length || xs.length < 2) {
      return null;
    }
    const meanX = mean(xs);
    const meanY = mean(ys);
    if (meanX == null || meanY == null) return null;
    let sumXY = 0;
    let sumXX = 0;
    let sumYY = 0;
    for (let idx = 0; idx < xs.length; idx += 1) {
      const dx = xs[idx] - meanX;
      const dy = ys[idx] - meanY;
      sumXY += dx * dy;
      sumXX += dx * dx;
      sumYY += dy * dy;
    }
    if (sumXX <= 0 || sumYY <= 0) return null;
    return sumXY / Math.sqrt(sumXX * sumYY);
  }

  function spearmanCorrelation(xs, ys) {
    if (!Array.isArray(xs) || !Array.isArray(ys) || xs.length !== ys.length || xs.length < 2) {
      return null;
    }
    const rankX = rankWithTies(xs);
    const rankY = rankWithTies(ys);
    return pearsonCorrelation(rankX, rankY);
  }

  function linearRegressionFromPairs(pairs) {
    if (!Array.isArray(pairs) || pairs.length < 2) {
      return {
        slope: null,
        intercept: null,
        r_squared: null,
        pearson: null,
      };
    }
    const xs = pairs.map(pair => pair.x);
    const ys = pairs.map(pair => pair.y);
    const meanX = mean(xs);
    const meanY = mean(ys);
    if (meanX == null || meanY == null) {
      return {
        slope: null,
        intercept: null,
        r_squared: null,
        pearson: null,
      };
    }
    let sumXX = 0;
    let sumXY = 0;
    for (let idx = 0; idx < pairs.length; idx += 1) {
      const dx = pairs[idx].x - meanX;
      sumXX += dx * dx;
      sumXY += dx * (pairs[idx].y - meanY);
    }
    if (sumXX <= 0) {
      return {
        slope: 0,
        intercept: meanY,
        r_squared: 0,
        pearson: 0,
      };
    }
    const slope = sumXY / sumXX;
    const intercept = meanY - (slope * meanX);
    const pearson = pearsonCorrelation(xs, ys);
    const rSquared = pearson == null ? null : pearson * pearson;
    return {
      slope,
      intercept,
      r_squared: rSquared,
      pearson,
    };
  }

  function equalCountBinsFromPairs(pairs, maxBins) {
    const sorted = Array.isArray(pairs)
      ? pairs
        .filter(pair => pair && Number.isFinite(pair.x) && Number.isFinite(pair.y))
        .sort((left, right) => left.x - right.x)
      : [];
    if (!sorted.length) return [];
    const targetBins = Math.max(1, Math.min(Number(maxBins) || 5, sorted.length));
    const binSize = Math.max(1, Math.ceil(sorted.length / targetBins));
    const bins = [];
    for (let start = 0; start < sorted.length; start += binSize) {
      const chunk = sorted.slice(start, start + binSize);
      const xs = chunk.map(item => item.x);
      const ys = chunk.map(item => item.y);
      bins.push({
        x_min: xs[0],
        x_max: xs[xs.length - 1],
        x_mean: mean(xs),
        y_mean: mean(ys),
        count: chunk.length,
      });
    }
    return bins;
  }

  function equalCountBinsFromValues(values, maxBins) {
    const sorted = Array.isArray(values)
      ? values
        .filter(value => Number.isFinite(value))
        .sort((left, right) => left - right)
      : [];
    if (!sorted.length) return [];
    const targetBins = Math.max(1, Math.min(Number(maxBins) || 4, sorted.length));
    const binSize = Math.max(1, Math.ceil(sorted.length / targetBins));
    const bins = [];
    for (let start = 0; start < sorted.length; start += binSize) {
      const chunk = sorted.slice(start, start + binSize);
      bins.push({
        min: chunk[0],
        max: chunk[chunk.length - 1],
        mean: mean(chunk),
        count: chunk.length,
      });
    }
    return bins;
  }

  function compareControlSecondaryMetricFields(records, outcomeField, compareField) {
    const totalRows = Array.isArray(records) ? records.length : 0;
    if (!totalRows) return [];
    const candidateOrder = [
      ...COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED,
      ...previousRunsFieldOptions,
    ];
    const preferredSet = new Set(COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED);
    const seen = new Set();
    const selected = [];
    for (const candidate of candidateOrder) {
      const fieldName = String(candidate || "").trim();
      if (!fieldName || seen.has(fieldName)) continue;
      seen.add(fieldName);
      if (fieldName === outcomeField || fieldName === compareField) continue;
      if (COMPARE_CONTROL_FIELD_SKIP.has(fieldName)) continue;
      if (!preferredSet.has(fieldName) && !COMPARE_CONTROL_SECONDARY_FIELD_PATTERN.test(fieldName)) {
        continue;
      }
      let numericCount = 0;
      records.forEach(record => {
        if (maybeNumber(previousRunsFieldValue(record, fieldName)) != null) {
          numericCount += 1;
        }
      });
      if (numericCount < 2) continue;
      selected.push(fieldName);
      if (selected.length >= COMPARE_CONTROL_SECONDARY_MAX_FIELDS) break;
    }
    return selected;
  }

  function compareControlWeakCoverageWarnings(analysis) {
    if (!analysis || typeof analysis !== "object" || Array.isArray(analysis)) return [];
    const warnings = [];
    const candidateRows = Number(analysis.candidate_rows || 0);
    const usedRows = Number(analysis.used_rows || 0);
    if (usedRows <= 0) {
      warnings.push("No comparable rows remained after hold-constant controls.");
      return warnings;
    }
    if (candidateRows > 0) {
      const rowCoverage = usedRows / candidateRows;
      if (rowCoverage < COMPARE_CONTROL_WARNING_ROW_COVERAGE_MIN) {
        warnings.push(
          "Row coverage is low (" +
          usedRows +
          " / " +
          candidateRows +
          ", " +
          (rowCoverage * 100).toFixed(1) +
          "%)."
        );
      }
    }
    if (usedRows < COMPARE_CONTROL_WARNING_MIN_ROWS) {
      warnings.push("Only " + usedRows + " comparable rows are available.");
    }
    const totalStrata = Number(analysis.total_strata || 0);
    const usedStrata = Number(analysis.used_strata || 0);
    if (totalStrata > 0) {
      const strataCoverage = usedStrata / totalStrata;
      if (strataCoverage < COMPARE_CONTROL_WARNING_STRATA_COVERAGE_MIN) {
        warnings.push(
          "Comparable strata are limited (" +
          usedStrata +
          " / " +
          totalStrata +
          ", " +
          (strataCoverage * 100).toFixed(1) +
          "%)."
        );
      }
    }
    if (totalStrata > 0 && usedStrata < Math.min(totalStrata, COMPARE_CONTROL_WARNING_MIN_STRATA)) {
      warnings.push("Only " + usedStrata + " strata contribute to controlled estimates.");
    }
    return warnings;
  }

  function analyzeCompareControlCategoricalRaw(records, outcomeField, compareField) {
    const groupsByKey = Object.create(null);
    const secondaryFields = compareControlSecondaryMetricFields(records, outcomeField, compareField);
    let usedRows = 0;
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      if (outcome == null) return;
      const rawCompareValue = previousRunsFieldValue(record, compareField);
      const groupKey = analysisComparableValue(rawCompareValue);
      if (groupKey === "__EMPTY__") return;
      if (!Object.prototype.hasOwnProperty.call(groupsByKey, groupKey)) {
        groupsByKey[groupKey] = {
          key: groupKey,
          label: analysisDisplayValue(rawCompareValue, groupKey),
          count: 0,
          outcome_sum: 0,
          secondary_sum: Object.create(null),
          secondary_count: Object.create(null),
        };
      }
      const group = groupsByKey[groupKey];
      group.count += 1;
      group.outcome_sum += outcome;
      secondaryFields.forEach(fieldName => {
        const secondaryValue = maybeNumber(previousRunsFieldValue(record, fieldName));
        if (secondaryValue == null) return;
        const sumValue = Number(group.secondary_sum[fieldName] || 0);
        const countValue = Number(group.secondary_count[fieldName] || 0);
        group.secondary_sum[fieldName] = sumValue + secondaryValue;
        group.secondary_count[fieldName] = countValue + 1;
      });
      usedRows += 1;
    });
    const groups = Object.values(groupsByKey)
      .map(group => ({
        key: group.key,
        label: group.label,
        count: group.count,
        outcome_mean: group.count > 0 ? group.outcome_sum / group.count : null,
        secondary_means: secondaryFields.reduce((acc, fieldName) => {
          const countValue = Number(group.secondary_count[fieldName] || 0);
          if (countValue > 0) {
            acc[fieldName] = Number(group.secondary_sum[fieldName] || 0) / countValue;
          }
          return acc;
        }, Object.create(null)),
      }))
      .sort((left, right) => {
        if (right.count !== left.count) return right.count - left.count;
        return String(left.label).localeCompare(String(right.label), undefined, { numeric: true });
      });
    return {
      type: "categorical",
      groups,
      used_rows: usedRows,
      candidate_rows: records.length,
      secondary_fields: secondaryFields,
    };
  }

  function analyzeCompareControlNumericRaw(records, outcomeField, compareField) {
    const pairs = compareControlPairs(records, outcomeField, compareField);
    const regression = linearRegressionFromPairs(pairs);
    const xs = pairs.map(pair => pair.x);
    const ys = pairs.map(pair => pair.y);
    const spearman = spearmanCorrelation(xs, ys);
    const bins = equalCountBinsFromPairs(pairs, 5);
    return {
      type: "numeric",
      used_rows: pairs.length,
      candidate_rows: records.length,
      slope: regression.slope,
      intercept: regression.intercept,
      r_squared: regression.r_squared,
      spearman,
      bins,
    };
  }

  function analyzeCompareControlCategoricalControlled(records, outcomeField, compareField, holdFields) {
    const hold = uniqueStringList(holdFields);
    if (!hold.length) {
      const raw = analyzeCompareControlCategoricalRaw(records, outcomeField, compareField);
      return {
        ...raw,
        used_strata: 0,
        total_strata: 0,
        hold_fields: hold,
      };
    }

    const strata = Object.create(null);
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      if (outcome == null) return;
      const rawCompare = previousRunsFieldValue(record, compareField);
      const groupKey = analysisComparableValue(rawCompare);
      if (groupKey === "__EMPTY__") return;
      const stratumKey = hold
        .map(fieldName => analysisComparableValue(previousRunsFieldValue(record, fieldName)))
        .join("||");
      if (!Object.prototype.hasOwnProperty.call(strata, stratumKey)) {
        strata[stratumKey] = Object.create(null);
      }
      if (!Object.prototype.hasOwnProperty.call(strata[stratumKey], groupKey)) {
        strata[stratumKey][groupKey] = {
          key: groupKey,
          label: analysisDisplayValue(rawCompare, groupKey),
          count: 0,
          outcome_sum: 0,
        };
      }
      const group = strata[stratumKey][groupKey];
      group.count += 1;
      group.outcome_sum += outcome;
    });

    const weightedGroups = Object.create(null);
    let usedRows = 0;
    let usedStrata = 0;
    const totalStrata = Object.keys(strata).length;
    Object.keys(strata).forEach(stratumKey => {
      const groups = Object.values(strata[stratumKey]);
      if (groups.length < 2) return;
      const stratumWeight = groups.reduce((acc, group) => acc + Number(group.count || 0), 0);
      if (stratumWeight <= 0) return;
      usedStrata += 1;
      usedRows += stratumWeight;
      groups.forEach(group => {
        if (!Object.prototype.hasOwnProperty.call(weightedGroups, group.key)) {
          weightedGroups[group.key] = {
            key: group.key,
            label: group.label,
            weighted_sum: 0,
            weight: 0,
            count: 0,
            strata_count: 0,
          };
        }
        const meanOutcome = group.count > 0 ? group.outcome_sum / group.count : null;
        if (meanOutcome == null) return;
        // Use shared stratum weights so group means are compared on the same stratum mix.
        weightedGroups[group.key].weighted_sum += meanOutcome * stratumWeight;
        weightedGroups[group.key].weight += stratumWeight;
        weightedGroups[group.key].count += group.count;
        weightedGroups[group.key].strata_count += 1;
      });
    });
    const groups = Object.values(weightedGroups)
      .map(group => ({
        key: group.key,
        label: group.label,
        count: group.count,
        outcome_mean: group.weight > 0 ? group.weighted_sum / group.weight : null,
      }))
      .sort((left, right) => {
        if (right.count !== left.count) return right.count - left.count;
        return String(left.label).localeCompare(String(right.label), undefined, { numeric: true });
      });
    return {
      type: "categorical",
      groups,
      used_rows: usedRows,
      candidate_rows: records.length,
      used_strata: usedStrata,
      total_strata: totalStrata,
      hold_fields: hold,
    };
  }

  function analyzeCompareControlNumericControlled(records, outcomeField, compareField, holdFields) {
    const hold = uniqueStringList(holdFields);
    if (!hold.length) {
      const raw = analyzeCompareControlNumericRaw(records, outcomeField, compareField);
      return {
        ...raw,
        used_strata: 0,
        total_strata: 0,
        hold_fields: hold,
      };
    }

    const strata = Object.create(null);
    records.forEach(record => {
      const outcome = maybeNumber(previousRunsFieldValue(record, outcomeField));
      const compare = maybeNumber(previousRunsFieldValue(record, compareField));
      if (outcome == null || compare == null) return;
      const stratumKey = hold
        .map(fieldName => analysisComparableValue(previousRunsFieldValue(record, fieldName)))
        .join("||");
      if (!Object.prototype.hasOwnProperty.call(strata, stratumKey)) {
        strata[stratumKey] = [];
      }
      strata[stratumKey].push({ x: compare, y: outcome });
    });

    let usedStrata = 0;
    const centeredPairs = [];
    const totalStrata = Object.keys(strata).length;
    Object.keys(strata).forEach(stratumKey => {
      const rows = strata[stratumKey];
      if (!rows || rows.length < 2) return;
      const meanX = mean(rows.map(row => row.x));
      const meanY = mean(rows.map(row => row.y));
      if (meanX == null || meanY == null) return;
      const distinctX = new Set(rows.map(row => row.x)).size;
      if (distinctX < 2) return;
      usedStrata += 1;
      rows.forEach(row => {
        centeredPairs.push({
          x: row.x - meanX,
          y: row.y - meanY,
        });
      });
    });

    const regression = linearRegressionFromPairs(centeredPairs);
    const xs = centeredPairs.map(pair => pair.x);
    const ys = centeredPairs.map(pair => pair.y);
    const spearman = spearmanCorrelation(xs, ys);
    return {
      type: "numeric",
      used_rows: centeredPairs.length,
      candidate_rows: records.length,
      used_strata: usedStrata,
      total_strata: totalStrata,
      hold_fields: hold,
      slope: regression.slope,
      intercept: regression.intercept,
      r_squared: regression.r_squared,
      spearman,
      bins: [],
    };
  }

  function analyzeCompareControlDiscovery(records, outcomeField, catalog) {
    const totalRows = Array.isArray(records) ? records.length : 0;
    const byField = (catalog && catalog.by_field) || Object.create(null);
    const scored = [];
    Object.keys(byField).forEach(fieldName => {
      if (fieldName === outcomeField) return;
      const fieldInfo = byField[fieldName];
      if (!fieldInfo) return;
      let strength = null;
      let summary = "";
      let coverageRatio = 0;
      if (fieldInfo.numeric) {
        const analysis = analyzeCompareControlNumericRaw(records, outcomeField, fieldName);
        coverageRatio = totalRows > 0 ? analysis.used_rows / totalRows : 0;
        const corrStrength = analysis.spearman == null ? 0 : Math.abs(analysis.spearman);
        const slopeStrength = analysis.slope == null ? 0 : Math.abs(analysis.slope);
        strength = corrStrength + Math.min(1, slopeStrength);
        summary =
          "Spearman " + fmtMaybe(analysis.spearman, 3) +
          ", R² " + fmtMaybe(analysis.r_squared, 3);
      } else {
        const analysis = analyzeCompareControlCategoricalRaw(records, outcomeField, fieldName);
        coverageRatio = totalRows > 0 ? analysis.used_rows / totalRows : 0;
        if (analysis.groups.length < 2) return;
        const means = analysis.groups
          .map(group => maybeNumber(group.outcome_mean))
          .filter(value => value != null);
        if (!means.length) return;
        const minMean = Math.min(...means);
        const maxMean = Math.max(...means);
        strength = Math.abs(maxMean - minMean) * 100;
        const topGroup = analysis.groups[0];
        summary = topGroup
          ? ("Top group: " + topGroup.label + " (" + fmtMaybe(topGroup.outcome_mean, 3) + ")")
          : "";
      }
      const finalScore = Number.isFinite(strength) ? strength * Math.max(0.2, coverageRatio) : 0;
      scored.push({
        field: fieldName,
        field_label: fieldInfo.label,
        numeric: fieldInfo.numeric,
        coverage_ratio: coverageRatio,
        score: finalScore,
        summary,
      });
    });
    scored.sort((left, right) => right.score - left.score);
    return scored.slice(0, 10);
  }

  function compareControlSplitSegments(records, splitField, catalog) {
    const byField = (catalog && catalog.by_field) || Object.create(null);
    const splitInfo = byField[splitField];
    if (!splitInfo) return [];
    if (splitInfo.numeric) {
      const numericValues = records
        .map(record => maybeNumber(previousRunsFieldValue(record, splitField)))
        .filter(value => value != null);
      const bins = equalCountBinsFromValues(numericValues, 4);
      if (!bins.length) return [];
      const segments = bins.map((bin, idx) => ({
        key: "bin_" + idx,
        label: fmtMaybe(bin.min, 3) + " to " + fmtMaybe(bin.max, 3),
        records: records.filter(record => {
          const value = maybeNumber(previousRunsFieldValue(record, splitField));
          if (value == null) return false;
          if (idx === bins.length - 1) return value >= bin.min && value <= bin.max;
          return value >= bin.min && value < bin.max;
        }),
      }));
      const missing = records.filter(record => (
        maybeNumber(previousRunsFieldValue(record, splitField)) == null
      ));
      if (missing.length) {
        segments.push({
          key: "missing",
          label: "(missing)",
          records: missing,
        });
      }
      return segments.filter(segment => segment.records.length > 0).slice(0, 8);
    }
    const byGroup = Object.create(null);
    records.forEach(record => {
      const rawValue = previousRunsFieldValue(record, splitField);
      const key = analysisComparableValue(rawValue);
      const label = analysisDisplayValue(rawValue, key);
      if (!Object.prototype.hasOwnProperty.call(byGroup, key)) {
        byGroup[key] = {
          key,
          label,
          records: [],
        };
      }
      byGroup[key].records.push(record);
    });
    return Object.values(byGroup)
      .sort((left, right) => {
        if (right.records.length !== left.records.length) {
          return right.records.length - left.records.length;
        }
        return String(left.label).localeCompare(String(right.label), undefined, { numeric: true });
      })
      .slice(0, 8);
  }

  function compareControlSegmentSummary(records, state, catalog) {
    if (!Array.isArray(records) || !records.length || !state.compare_field) return "-";
    const compareInfo = catalog.by_field[state.compare_field];
    if (!compareInfo) return "-";
    if (compareInfo.numeric) {
      const numeric = state.view_mode === "controlled"
        ? analyzeCompareControlNumericControlled(
          records,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : analyzeCompareControlNumericRaw(records, state.outcome_field, state.compare_field);
      return (
        "slope " + fmtMaybe(numeric.slope, 4) +
        ", Spearman " + fmtMaybe(numeric.spearman, 3)
      );
    }
    const categorical = state.view_mode === "controlled"
      ? analyzeCompareControlCategoricalControlled(
        records,
        state.outcome_field,
        state.compare_field,
        state.hold_constant_fields,
      )
      : analyzeCompareControlCategoricalRaw(records, state.outcome_field, state.compare_field);
    if (!categorical.groups.length) return "-";
    const top = categorical.groups[0];
    return top.label + ": " + fmtMaybe(top.outcome_mean, 3);
  }

  function renderCompareControlPanel(context) {
    const panel = document.getElementById("compare-control-panel");
    const statusNode = document.getElementById("compare-control-status");
    const resultsNode = document.getElementById("compare-control-results");
    const viewModeNode = document.getElementById("compare-control-view-mode");
    const outcomeNode = document.getElementById("compare-control-outcome-field");
    const compareNode = document.getElementById("compare-control-compare-field");
    const splitNode = document.getElementById("compare-control-split-field");
    const holdNode = document.getElementById("compare-control-hold-fields");
    const groupNode = document.getElementById("compare-control-group-selection");
    const filterSubset = document.getElementById("compare-control-filter-subset");
    const clearSelection = document.getElementById("compare-control-clear-selection");
    if (
      !panel ||
      !statusNode ||
      !resultsNode ||
      !viewModeNode ||
      !outcomeNode ||
      !compareNode ||
      !splitNode ||
      !holdNode ||
      !groupNode ||
      !filterSubset ||
      !clearSelection
    ) {
      return;
    }

    const records = Array.isArray(context && context.records) ? context.records : [];
    const catalog = buildCompareControlFieldCatalog(records);
    compareControlState = normalizeCompareControlStateForCatalog(compareControlState, catalog);
    const state = compareControlState;

    viewModeNode.value = state.view_mode;
    outcomeNode.innerHTML = (catalog.numeric_fields || [])
      .map(field => (
        '<option value="' + esc(field.field) + '">' + esc(field.label) + "</option>"
      ))
      .join("");
    if (!outcomeNode.innerHTML) {
      outcomeNode.innerHTML = '<option value="">(no numeric outcome)</option>';
    }
    if (state.outcome_field && catalog.by_field[state.outcome_field]) {
      outcomeNode.value = state.outcome_field;
    }

    const compareOptions = [
      '<option value="">(discover best candidates)</option>',
      ...(catalog.fields || []).map(field => (
        '<option value="' + esc(field.field) + '">' +
        esc(field.label + (field.numeric ? " [numeric]" : "")) +
        "</option>"
      )),
    ];
    compareNode.innerHTML = compareOptions.join("");
    compareNode.value = state.compare_field;

    const splitOptions = [
      '<option value="">(none)</option>',
      ...(catalog.fields || [])
        .filter(field => field.field !== state.compare_field && field.field !== state.outcome_field)
        .map(field => (
          '<option value="' + esc(field.field) + '">' +
          esc(field.label + (field.numeric ? " [numeric]" : "")) +
          "</option>"
        )),
    ];
    splitNode.innerHTML = splitOptions.join("");
    splitNode.value = state.split_field;

    const holdCandidates = (catalog.fields || [])
      .filter(field => field.field !== state.compare_field && field.field !== state.outcome_field)
      .slice(0, 20);
    if (!holdCandidates.length) {
      holdNode.innerHTML = '<span class="compare-control-inline-note">No hold-constant fields available.</span>';
    } else {
      holdNode.innerHTML = holdCandidates
        .map(field => {
          const checked = state.hold_constant_fields.includes(field.field) ? " checked" : "";
          return (
            '<label class="compare-control-hold-item">' +
              '<input class="compare-control-hold-checkbox" type="checkbox" value="' + esc(field.field) + '"' + checked + ">" +
              esc(field.label) +
            "</label>"
          );
        })
        .join("");
    }

    if (!records.length) {
      statusNode.textContent = "No visible benchmark rows after current filters.";
      resultsNode.innerHTML = '<p class="empty-note">Broaden Previous Runs filters, then compare fields here.</p>';
      groupNode.innerHTML = "";
      filterSubset.disabled = true;
      clearSelection.disabled = true;
      return;
    }
    if (!catalog.numeric_fields.length) {
      statusNode.textContent = "No numeric outcome fields available in current rows.";
      resultsNode.innerHTML = '<p class="empty-note">Need at least one numeric metric to run Compare &amp; Control.</p>';
      groupNode.innerHTML = "";
      filterSubset.disabled = true;
      clearSelection.disabled = true;
      return;
    }

    const compareInfo = catalog.by_field[state.compare_field];
    const selectedGroups = uniqueStringList(state.selected_groups);
    const coverageBase = records.length;
    let htmlParts = [];
    let statusText = "";
    let statusIsError = false;

    if (!state.compare_field || state.view_mode === "discover" || !compareInfo) {
      const discovery = analyzeCompareControlDiscovery(records, state.outcome_field, catalog);
      statusText =
        "Discovery view over " + records.length + " visible rows. Click a field card to compare.";
      if (!discovery.length) {
        htmlParts.push("<p>No candidate fields had enough variation for discovery scoring.</p>");
      } else {
        htmlParts.push('<div class="compare-control-discovery-list">');
        discovery.forEach(item => {
          htmlParts.push(
            '<button class="compare-control-discovery-card" type="button" data-compare-field="' + esc(item.field) + '">' +
              "<strong>" + esc(item.field_label) + "</strong> " +
              '<span class="score">score ' + esc(fmtMaybe(item.score, 3)) + "</span>" +
              "<br>" +
              '<span class="compare-control-inline-note">' +
                esc(item.summary + " | coverage " + (item.coverage_ratio * 100).toFixed(1) + "%") +
              "</span>" +
            "</button>"
          );
        });
        htmlParts.push("</div>");
      }
      groupNode.innerHTML = "";
      filterSubset.disabled = true;
      clearSelection.disabled = true;
    } else if (compareInfo.numeric) {
      groupNode.innerHTML = '<p class="compare-control-inline-note">Group subset selection is available for categorical compare fields.</p>';
      filterSubset.disabled = true;
      clearSelection.disabled = true;
      const analysis = state.view_mode === "controlled"
        ? analyzeCompareControlNumericControlled(
          records,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : analyzeCompareControlNumericRaw(records, state.outcome_field, state.compare_field);
      const coverage = coverageBase > 0 ? (analysis.used_rows / coverageBase) * 100 : 0;
      statusText =
        (state.view_mode === "controlled" ? "Controlled" : "Raw") +
        " numeric compare on " +
        analysis.used_rows +
        " / " +
        coverageBase +
        " rows (" +
        coverage.toFixed(1) +
        "% coverage).";
      if (state.view_mode === "controlled") {
        statusText +=
          " Comparable strata: " +
          analysis.used_strata +
          " / " +
          analysis.total_strata +
          ".";
        const warnings = compareControlWeakCoverageWarnings(analysis);
        if (warnings.length) {
          htmlParts.push('<p class="compare-control-warning"><strong>Coverage warning:</strong></p><ul>');
          warnings.forEach(text => {
            htmlParts.push('<li class="compare-control-warning">' + esc(text) + "</li>");
          });
          htmlParts.push("</ul>");
        }
      }
      htmlParts.push("<p><strong>Slope:</strong> " + esc(fmtMaybe(analysis.slope, 5)) + "</p>");
      htmlParts.push("<p><strong>R²:</strong> " + esc(fmtMaybe(analysis.r_squared, 4)) + "</p>");
      htmlParts.push("<p><strong>Spearman:</strong> " + esc(fmtMaybe(analysis.spearman, 4)) + "</p>");
      if (analysis.bins && analysis.bins.length) {
        htmlParts.push("<p><strong>Equal-count bins:</strong></p><ul>");
        analysis.bins.forEach(bin => {
          htmlParts.push(
            "<li>" +
            esc(
              fmtMaybe(bin.x_min, 3) +
              " to " +
              fmtMaybe(bin.x_max, 3) +
              " (" +
              bin.count +
              " rows): outcome avg " +
              fmtMaybe(bin.y_mean, 4)
            ) +
            "</li>"
          );
        });
        htmlParts.push("</ul>");
      }
    } else {
      const groupOptions = compareInfo.categories || [];
      groupNode.innerHTML = groupOptions.length
        ? (
          '<p class="compare-control-inline-note">Select groups, then use <strong>Filter to subset</strong> to write table filters.</p>' +
          '<div class="compare-control-group-selection-list">' +
          groupOptions
            .map(group => {
              if (group.key === "__EMPTY__") return "";
              const checked = selectedGroups.includes(group.key) ? " checked" : "";
              return (
                '<label class="compare-control-group-option">' +
                  '<input class="compare-control-group-checkbox" type="checkbox" value="' + esc(group.key) + '"' + checked + ">" +
                  esc(group.label + " (" + group.count + ")") +
                "</label>"
              );
            })
            .join("") +
          "</div>"
        )
        : '<p class="compare-control-inline-note">No groups available for selection.</p>';
      filterSubset.disabled = selectedGroups.length === 0;
      clearSelection.disabled = selectedGroups.length === 0;
      const analysis = state.view_mode === "controlled"
        ? analyzeCompareControlCategoricalControlled(
          records,
          state.outcome_field,
          state.compare_field,
          state.hold_constant_fields,
        )
        : analyzeCompareControlCategoricalRaw(records, state.outcome_field, state.compare_field);
      const coverage = coverageBase > 0 ? (analysis.used_rows / coverageBase) * 100 : 0;
      statusText =
        (state.view_mode === "controlled" ? "Controlled" : "Raw") +
        " categorical compare on " +
        analysis.used_rows +
        " / " +
        coverageBase +
        " rows (" +
        coverage.toFixed(1) +
        "% coverage).";
      if (state.view_mode === "controlled") {
        statusText +=
          " Comparable strata: " +
          analysis.used_strata +
          " / " +
          analysis.total_strata +
          ".";
        const warnings = compareControlWeakCoverageWarnings(analysis);
        if (warnings.length) {
          htmlParts.push('<p class="compare-control-warning"><strong>Coverage warning:</strong></p><ul>');
          warnings.forEach(text => {
            htmlParts.push('<li class="compare-control-warning">' + esc(text) + "</li>");
          });
          htmlParts.push("</ul>");
        }
      }
      if (!analysis.groups.length) {
        htmlParts.push("<p>No comparable groups found with the current controls.</p>");
      } else {
        htmlParts.push("<p><strong>Group outcome means:</strong></p><ul>");
        analysis.groups.slice(0, 12).forEach(group => {
          const secondarySummary = (analysis.secondary_fields || [])
            .map(fieldName => {
              const value = maybeNumber(
                group &&
                group.secondary_means &&
                Object.prototype.hasOwnProperty.call(group.secondary_means, fieldName)
                  ? group.secondary_means[fieldName]
                  : null
              );
              if (value == null) return null;
              return compareControlFieldLabel(fieldName) + " " + fmtMaybe(value, 3);
            })
            .filter(Boolean)
            .slice(0, 3);
          const secondaryText = secondarySummary.length
            ? " | " + secondarySummary.join(", ")
            : "";
          htmlParts.push(
            "<li>" +
            esc(group.label + ": avg " + fmtMaybe(group.outcome_mean, 4) + " (" + group.count + " rows)" + secondaryText) +
            "</li>"
          );
        });
        htmlParts.push("</ul>");
      }
    }

    if (state.split_field) {
      const segments = compareControlSplitSegments(records, state.split_field, catalog);
      if (segments.length) {
        htmlParts.push('<div class="compare-control-split-list"><p><strong>Split by ' + esc(compareControlFieldLabel(state.split_field)) + ":</strong></p><ul>");
        segments.forEach(segment => {
          const summary = compareControlSegmentSummary(segment.records, state, catalog);
          htmlParts.push(
            "<li>" +
            esc(segment.label + " (" + segment.records.length + " rows): " + summary) +
            "</li>"
          );
        });
        htmlParts.push("</ul></div>");
      }
    }

    if (compareControlStatusMessage) {
      const prefix = compareControlStatusIsError ? "Compare/Control: " : "";
      statusText = prefix + compareControlStatusMessage + (statusText ? " " + statusText : "");
      statusIsError = compareControlStatusIsError;
      compareControlStatusMessage = "";
      compareControlStatusIsError = false;
    }
    statusNode.textContent = statusText || "Compare & Control ready.";
    statusNode.classList.toggle("error", Boolean(statusIsError));
    resultsNode.innerHTML = htmlParts.join("");
  }

  function syncCompareControlSelectionToTableFilters() {
    const state = normalizeCompareControlState(compareControlState);
    const compareField = String(state.compare_field || "").trim();
    const selectedGroups = uniqueStringList(state.selected_groups)
      .filter(value => value && value !== "__EMPTY__");
    if (!compareField) {
      return {
        applied: false,
        message: "Pick a categorical compare field first.",
      };
    }
    if (!selectedGroups.length) {
      return {
        applied: false,
        message: "Select one or more groups before filtering to subset.",
      };
    }
    const clauses = selectedGroups.map(value => ({
      operator: "eq",
      value,
    }));
    const applied = setPreviousRunsColumnFilterClauses(compareField, clauses);
    if (!applied) {
      return {
        applied: false,
        message: "Could not write selected groups into table filters.",
      };
    }
    setPreviousRunsColumnFilterMode(compareField, "or");
    closePreviousRunsColumnFilterEditor();
    compareControlState.selected_groups = selectedGroups;
    return {
      applied: true,
      message: "Filter to subset wrote " + selectedGroups.length + " clauses into Previous Runs table filters.",
    };
  }

  function analysisComparableValue(value) {
    if (value == null) return "__EMPTY__";
    if (typeof value === "string") {
      const text = value.trim();
      return text ? text : "__EMPTY__";
    }
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return "__EMPTY__";
      return String(value);
    }
    return String(value);
  }

  function analysisDisplayValue(rawValue, comparableValue) {
    if (comparableValue === "__EMPTY__") return "(empty)";
    if (typeof rawValue === "boolean") return rawValue ? "true" : "false";
    if (typeof rawValue === "number") {
      if (!Number.isFinite(rawValue)) return "(empty)";
      return Number.isInteger(rawValue) ? String(rawValue) : rawValue.toFixed(4);
    }
    return String(rawValue);
  }

  function analysisFieldLabel(fieldName) {
    const meta = previousRunsColumnMeta(fieldName);
    if (!meta || !meta.label || meta.label === fieldName) return fieldName;
    return meta.label + " (" + fieldName + ")";
  }

  function previousRunsRecordsMatchingOtherFilters(excludedField) {
    const base = applyPreviousRunsQuickFilters(
      filteredBenchmarks(),
      { updateStatus: false },
    ).records;
    const filters = activePreviousRunsColumnFilters()
      .filter(filter => filter.field !== excludedField);
    if (!filters.length) return base;
    const grouped = groupPreviousRunsFiltersByField(filters);
    return base.filter(record => (
      recordMatchesPreviousRunsFilterGroups(
        record,
        grouped,
        previousRunsColumnFilterGlobalMode
      )
    ));
  }

  function previousRunsSuggestionValue(value) {
    if (value == null) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return "";
      return Number.isInteger(value) ? String(value) : String(value);
    }
    return String(value).trim();
  }

  function previousRunsSuggestionScore(typedLower, candidateLower) {
    if (!typedLower) return 500;
    if (!candidateLower) return -1;
    if (candidateLower === typedLower) return 2000;
    if (candidateLower.startsWith(typedLower)) {
      return 1500 - Math.min(300, candidateLower.length - typedLower.length);
    }
    const wordStart = candidateLower.indexOf(" " + typedLower);
    if (wordStart >= 0) {
      return 1300 - wordStart;
    }
    const includes = candidateLower.indexOf(typedLower);
    if (includes >= 0) {
      return 1100 - includes;
    }
    let needleIndex = 0;
    for (let idx = 0; idx < candidateLower.length && needleIndex < typedLower.length; idx += 1) {
      if (candidateLower[idx] === typedLower[needleIndex]) {
        needleIndex += 1;
      }
    }
    if (needleIndex === typedLower.length) {
      return 900;
    }
    return -1;
  }

  function previousRunsColumnSuggestionCandidates(fieldName, typedText) {
    const typedLower = normalizeRuleValue(typedText || "");
    const counts = new Map();
    previousRunsRecordsMatchingOtherFilters(fieldName).forEach(record => {
      const rawValue = previousRunsFieldValue(record, fieldName);
      const candidate = previousRunsSuggestionValue(rawValue);
      if (!candidate) return;
      counts.set(candidate, (counts.get(candidate) || 0) + 1);
    });

    const scored = [];
    counts.forEach((count, value) => {
      const lower = value.toLowerCase();
      const score = previousRunsSuggestionScore(typedLower, lower);
      if (score < 0) return;
      scored.push({
        value,
        count,
        score,
      });
    });

    scored.sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      if (right.count !== left.count) return right.count - left.count;
      if (left.value.length !== right.value.length) return left.value.length - right.value.length;
      return left.value.localeCompare(right.value);
    });
    return scored.slice(0, PREVIOUS_RUNS_FILTER_SUGGESTION_LIMIT);
  }

  function previousRunsPresetNames() {
    return Object.keys(previousRunsViewPresets).sort((left, right) => (
      String(left).localeCompare(String(right), undefined, { sensitivity: "base" })
    ));
  }

  function setPreviousRunsPresetStatus(message, isError) {
    const status = document.getElementById("previous-runs-preset-status");
    if (!status) return;
    status.textContent = String(message || "");
    status.classList.toggle("error", Boolean(isError));
  }

  function renderPreviousRunsPresetEditor() {
    const select = document.getElementById("previous-runs-preset-select");
    if (!select) return;
    const names = previousRunsPresetNames();
    const selected = sanitizePreviousRunsPresetName(previousRunsSelectedPreset);
    previousRunsSelectedPreset = names.includes(selected) ? selected : "";

    select.innerHTML = "";
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "(none)";
    select.appendChild(emptyOption);
    names.forEach(name => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    });
    select.value = previousRunsSelectedPreset;

    const loadBtn = document.getElementById("previous-runs-preset-load");
    if (loadBtn) loadBtn.disabled = !previousRunsSelectedPreset;
    const deleteBtn = document.getElementById("previous-runs-preset-delete");
    if (deleteBtn) deleteBtn.disabled = !previousRunsSelectedPreset;
  }

  function captureCurrentPreviousRunsPresetState() {
    ensurePreviousRunsColumns();
    const visibleColumns = previousRunsVisibleColumns
      .map(fieldName => String(fieldName || "").trim())
      .filter(Boolean);
    const columnFilters = Object.create(null);
    const columnFilterModes = Object.create(null);
    Object.keys(previousRunsColumnFilters).forEach(fieldName => {
      const clauses = previousRunsColumnFilterClauses(fieldName);
      if (!clauses.length) return;
      columnFilters[fieldName] = clauses.map(clause => ({
        operator: clause.operator,
        value: clause.value,
      }));
      columnFilterModes[fieldName] = previousRunsColumnFilterMode(fieldName);
    });
    const columnWidths = Object.create(null);
    Object.keys(previousRunsColumnWidths).forEach(fieldName => {
      const key = String(fieldName || "").trim();
      if (!key) return;
      const width = Number(previousRunsColumnWidths[fieldName]);
      if (!Number.isFinite(width) || width <= 0) return;
      columnWidths[key] = Math.max(72, width);
    });
    return sanitizePreviousRunsPresetState({
      visible_columns: visibleColumns,
      column_filters: columnFilters,
      column_filter_modes: columnFilterModes,
      column_filter_global_mode: normalizePreviousRunsColumnFilterGlobalMode(
        previousRunsColumnFilterGlobalMode
      ),
      quick_filters: {
        exclude_ai_tests: Boolean(previousRunsQuickFilters.exclude_ai_tests),
        official_full_golden_only: Boolean(previousRunsQuickFilters.official_full_golden_only),
      },
      column_widths: columnWidths,
      sort: {
        field: String(previousRunsSortField || "run_timestamp"),
        direction: previousRunsSortDirection === "asc" ? "asc" : "desc",
      },
      compare_control: normalizeCompareControlState(compareControlState),
    });
  }

  function applyPreviousRunsPresetByName(rawName) {
    const name = sanitizePreviousRunsPresetName(rawName);
    if (!name) {
      setPreviousRunsPresetStatus("Pick a preset first.", true);
      return false;
    }
    if (!Object.prototype.hasOwnProperty.call(previousRunsViewPresets, name)) {
      setPreviousRunsPresetStatus('Preset "' + name + '" was not found.', true);
      return false;
    }
    const preset = sanitizePreviousRunsPresetState(previousRunsViewPresets[name]);
    if (!preset) {
      setPreviousRunsPresetStatus('Preset "' + name + '" is invalid.', true);
      return false;
    }

    previousRunsSelectedPreset = name;
    previousRunsVisibleColumns = preset.visible_columns.slice();
    ensurePreviousRunsColumns();

    const availableSet = new Set(previousRunsAvailableColumnFields());
    const nextColumnFilters = Object.create(null);
    const nextColumnFilterModes = Object.create(null);
    Object.keys(preset.column_filters).forEach(fieldName => {
      if (!availableSet.has(fieldName)) return;
      const normalized = normalizePreviousRunsColumnFilterList(preset.column_filters[fieldName]);
      if (!normalized.length) return;
      nextColumnFilters[fieldName] = normalized;
      nextColumnFilterModes[fieldName] = normalizePreviousRunsColumnFilterMode(
        preset.column_filter_modes && preset.column_filter_modes[fieldName]
      );
    });
    previousRunsColumnFilters = nextColumnFilters;
    previousRunsColumnFilterModes = nextColumnFilterModes;
    previousRunsColumnFilterGlobalMode = normalizePreviousRunsColumnFilterGlobalMode(
      preset.column_filter_global_mode
    );

    previousRunsQuickFilters.exclude_ai_tests = Boolean(preset.quick_filters.exclude_ai_tests);
    previousRunsQuickFilters.official_full_golden_only = Boolean(
      preset.quick_filters.official_full_golden_only
    );
    previousRunsSortField = String(preset.sort.field || "run_timestamp");
    previousRunsSortDirection = preset.sort.direction === "asc" ? "asc" : "desc";
    ensurePreviousRunsColumns();

    previousRunsColumnWidths = sanitizeColumnWidthsMap(preset.column_widths);
    clearDashboardTableColumnWidths("previous-runs-table");
    Object.keys(previousRunsColumnWidths).forEach(fieldName => {
      setDashboardTableColumnWidth(
        "previous-runs-table",
        fieldName,
        previousRunsColumnWidths[fieldName]
      );
    });

    compareControlState = normalizeCompareControlState(preset.compare_control);

    closePreviousRunsColumnFilterEditor();
    setupPreviousRunsGlobalFilterModeControl();
    setupPreviousRunsQuickFilters();
    renderPreviousRunsPresetEditor();
    renderAll();
    setPreviousRunsPresetStatus('Loaded preset "' + name + '".', false);
    return true;
  }

  function saveCurrentPreviousRunsViewPreset(rawName) {
    let name = sanitizePreviousRunsPresetName(rawName);
    if (!name && typeof window !== "undefined" && typeof window.prompt === "function") {
      name = sanitizePreviousRunsPresetName(
        window.prompt("Preset name for current Previous Runs view:", previousRunsSelectedPreset || "")
      );
    }
    if (!name) {
      setPreviousRunsPresetStatus("Preset save cancelled (name is required).", true);
      return false;
    }
    const names = previousRunsPresetNames();
    const exists = Object.prototype.hasOwnProperty.call(previousRunsViewPresets, name);
    if (!exists && names.length >= PREVIOUS_RUNS_PRESET_MAX_COUNT) {
      setPreviousRunsPresetStatus(
        "Preset limit reached (" + PREVIOUS_RUNS_PRESET_MAX_COUNT + "). Delete one first.",
        true
      );
      return false;
    }
    const snapshot = captureCurrentPreviousRunsPresetState();
    if (!snapshot) {
      setPreviousRunsPresetStatus("Could not capture current view.", true);
      return false;
    }
    previousRunsViewPresets[name] = snapshot;
    previousRunsSelectedPreset = name;
    renderPreviousRunsPresetEditor();
    persistDashboardUiState();
    setPreviousRunsPresetStatus(
      (exists ? "Updated" : "Saved") + ' preset "' + name + '".',
      false
    );
    return true;
  }

  function deletePreviousRunsPreset(rawName) {
    const name = sanitizePreviousRunsPresetName(rawName);
    if (!name || !Object.prototype.hasOwnProperty.call(previousRunsViewPresets, name)) {
      setPreviousRunsPresetStatus("Pick an existing preset to delete.", true);
      return false;
    }
    delete previousRunsViewPresets[name];
    if (previousRunsSelectedPreset === name) {
      previousRunsSelectedPreset = "";
    }
    renderPreviousRunsPresetEditor();
    persistDashboardUiState();
    setPreviousRunsPresetStatus('Deleted preset "' + name + '".', false);
    return true;
  }

  function syncPreviousRunsPopupVisibility() {
    const popup = document.getElementById("previous-runs-columns-popup");
    const toggleBtn = document.getElementById("previous-runs-columns-toggle");
    if (popup) {
      popup.hidden = !previousRunsColumnsPopupOpen;
    }
    if (toggleBtn) {
      toggleBtn.setAttribute("aria-expanded", previousRunsColumnsPopupOpen ? "true" : "false");
      toggleBtn.classList.toggle("open", previousRunsColumnsPopupOpen);
    }
  }

  function setPreviousRunsColumnsPopupOpen(nextOpen) {
    previousRunsColumnsPopupOpen = Boolean(nextOpen);
    syncPreviousRunsPopupVisibility();
  }

  function setupPreviousRunsColumnsControls() {
    const control = document.querySelector(".previous-runs-columns-control");
    const popup = document.getElementById("previous-runs-columns-popup");
    const toggleBtn = document.getElementById("previous-runs-columns-toggle");

    if (toggleBtn && !toggleBtn.dataset.bound) {
      toggleBtn.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        setPreviousRunsColumnsPopupOpen(!previousRunsColumnsPopupOpen);
      });
      toggleBtn.dataset.bound = "1";
    }

    if (popup && !popup.dataset.bound) {
      popup.addEventListener("click", event => {
        event.stopPropagation();
      });
      popup.dataset.bound = "1";
    }

    if (document.body && !document.body.dataset.previousRunsColumnsBound) {
      document.addEventListener("click", event => {
        if (!previousRunsColumnsPopupOpen) return;
        if (!(event.target instanceof Node)) return;
        if (control && control.contains(event.target)) return;
        setPreviousRunsColumnsPopupOpen(false);
      });
      document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        if (!previousRunsColumnsPopupOpen) return;
        setPreviousRunsColumnsPopupOpen(false);
      });
      document.body.dataset.previousRunsColumnsBound = "1";
    }

    const resetBtn = document.getElementById("previous-runs-column-reset");
    if (resetBtn && !resetBtn.dataset.bound) {
      resetBtn.addEventListener("click", () => {
        previousRunsVisibleColumns = PREVIOUS_RUNS_DEFAULT_COLUMNS
          .filter(fieldName => previousRunsAvailableColumnFields().includes(fieldName));
        ensurePreviousRunsColumns();
        previousRunsColumnWidths = Object.create(null);
        clearDashboardTableColumnWidths("previous-runs-table");
        renderPreviousRunsColumnEditor();
        renderPreviousRuns();
      });
      resetBtn.dataset.bound = "1";
    }
    setPreviousRunsColumnsPopupOpen(false);
  }

  function setupPreviousRunsPresetControls() {
    const presetSelect = document.getElementById("previous-runs-preset-select");
    if (presetSelect && !presetSelect.dataset.bound) {
      presetSelect.addEventListener("change", () => {
        previousRunsSelectedPreset = sanitizePreviousRunsPresetName(presetSelect.value);
        renderPreviousRunsPresetEditor();
        persistDashboardUiState();
      });
      presetSelect.dataset.bound = "1";
    }

    const presetLoadBtn = document.getElementById("previous-runs-preset-load");
    if (presetLoadBtn && !presetLoadBtn.dataset.bound) {
      presetLoadBtn.addEventListener("click", () => {
        const selectedName = sanitizePreviousRunsPresetName(
          presetSelect ? presetSelect.value : previousRunsSelectedPreset
        );
        applyPreviousRunsPresetByName(selectedName);
      });
      presetLoadBtn.dataset.bound = "1";
    }

    const presetSaveCurrentBtn = document.getElementById("previous-runs-preset-save-current");
    if (presetSaveCurrentBtn && !presetSaveCurrentBtn.dataset.bound) {
      presetSaveCurrentBtn.addEventListener("click", () => {
        const selectedName = sanitizePreviousRunsPresetName(
          presetSelect ? presetSelect.value : previousRunsSelectedPreset
        );
        saveCurrentPreviousRunsViewPreset(selectedName);
      });
      presetSaveCurrentBtn.dataset.bound = "1";
    }

    const presetDeleteBtn = document.getElementById("previous-runs-preset-delete");
    if (presetDeleteBtn && !presetDeleteBtn.dataset.bound) {
      presetDeleteBtn.addEventListener("click", () => {
        const selectedName = sanitizePreviousRunsPresetName(
          presetSelect ? presetSelect.value : previousRunsSelectedPreset
        );
        deletePreviousRunsPreset(selectedName);
      });
      presetDeleteBtn.dataset.bound = "1";
    }

    renderPreviousRunsPresetEditor();
  }

  function renderPreviousRunsColumnEditor() {
    ensurePreviousRunsColumns();
    const host = document.getElementById("previous-runs-columns-checklist");
    if (!host) return;

    host.innerHTML = "";
    const availableFields = previousRunsAvailableColumnFields();
    const availableSet = new Set(availableFields);
    const visibleSet = new Set(previousRunsVisibleColumns);
    const disabledFieldName = previousRunsVisibleColumns.length <= 1
      ? previousRunsVisibleColumns[0]
      : null;
    const checklistOrder = [...previousRunsVisibleColumns].filter(
      fieldName => availableSet.has(fieldName)
    );
    availableFields.forEach(fieldName => {
      if (!visibleSet.has(fieldName)) {
        checklistOrder.push(fieldName);
      }
    });
    checklistOrder.forEach(fieldName => {
      const meta = previousRunsColumnMeta(fieldName);
      const row = document.createElement("label");
      row.className = "previous-runs-columns-check-item";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = fieldName;
      checkbox.checked = visibleSet.has(fieldName);
      checkbox.disabled = fieldName === disabledFieldName;
      checkbox.addEventListener("change", () => {
        const checked = checkbox.checked;
        const currentVisible = new Set(previousRunsVisibleColumns);
        if (checked) {
          if (!currentVisible.has(fieldName)) {
            previousRunsVisibleColumns.push(fieldName);
          }
        } else {
          if (previousRunsVisibleColumns.length <= 1) {
            checkbox.checked = true;
            return;
          }
          previousRunsVisibleColumns = previousRunsVisibleColumns.filter(
            candidate => candidate !== fieldName
          );
        }
        ensurePreviousRunsColumns();
        renderPreviousRunsColumnEditor();
        renderPreviousRuns();
      });
      row.appendChild(checkbox);

      const labelText = document.createElement("span");
      labelText.textContent = meta.label || fieldName;
      if ((meta.label || fieldName) !== fieldName) {
        const key = document.createElement("code");
        key.textContent = " " + fieldName;
        labelText.appendChild(key);
      }
      row.appendChild(labelText);
      host.appendChild(row);
    });
  }

  function reorderPreviousRunsColumns(fromField, toField) {
    const from = previousRunsVisibleColumns.indexOf(fromField);
    const to = previousRunsVisibleColumns.indexOf(toField);
    if (from < 0 || to < 0 || from === to) return false;
    const next = [...previousRunsVisibleColumns];
    const moved = next.splice(from, 1)[0];
    next.splice(to, 0, moved);
    previousRunsVisibleColumns = next;
    prunePreviousRunsColumnFilters();
    return true;
  }

  function collectBenchmarkFieldPaths() {
    const preferred = [
      "source_file_basename",
      "source_label",
      "source_file",
      "importer_name",
      "ai_model",
      "ai_effort",
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
      "all_token_use",
      "tokens_input",
      "tokens_cached_input",
      "tokens_output",
      "tokens_reasoning",
      "tokens_total",
      "all_method_record",
      "speed_suite_record",
      "artifact_dir",
    ];
    const discovered = new Set();
    (DATA.benchmark_records || []).forEach(record => {
      addFlattenedFieldPaths(record, "", discovered, 0);
    });
    discovered.add("source_file_basename");
    discovered.add("source_label");
    discovered.add("ai_model");
    discovered.add("ai_effort");
    discovered.add("artifact_dir_basename");
    discovered.add("all_method_record");
    discovered.add("speed_suite_record");
    PREVIOUS_RUNS_DEFAULT_COLUMNS.forEach(fieldName => discovered.add(fieldName));

    const ordered = [];
    const seen = new Set();
    preferred.forEach(fieldName => {
      if (discovered.has(fieldName) && !seen.has(fieldName)) {
        ordered.push(fieldName);
        seen.add(fieldName);
      }
    });
    Array.from(discovered)
      .sort((a, b) => a.localeCompare(b))
      .forEach(fieldName => {
        if (!seen.has(fieldName)) {
          ordered.push(fieldName);
          seen.add(fieldName);
        }
      });
    return ordered;
  }

  function addFlattenedFieldPaths(value, prefix, output, depth) {
    if (depth > 4) {
      if (prefix) output.add(prefix);
      return;
    }
    if (value == null) {
      if (prefix) output.add(prefix);
      return;
    }
    if (Array.isArray(value)) {
      if (prefix) output.add(prefix);
      return;
    }
    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (!keys.length) {
        if (prefix) output.add(prefix);
        return;
      }
      keys.forEach(key => {
        const nextPrefix = prefix ? prefix + "." + key : key;
        addFlattenedFieldPaths(value[key], nextPrefix, output, depth + 1);
      });
      return;
    }
    if (prefix) output.add(prefix);
  }

  function currentPreviousRunsFilterResult() {
    if (previousRunsFilterResultCache) return previousRunsFilterResultCache;
    previousRunsFilterResultCache = computePreviousRunsFilterResult();
    return previousRunsFilterResultCache;
  }

  function computePreviousRunsFilterResult() {
    const rawRecords = filteredBenchmarks();
    const quickFiltered = applyPreviousRunsQuickFilters(rawRecords);
    const allRecords = quickFiltered.records;
    const quickFilterLabels = activePreviousRunsQuickFilterLabels(quickFiltered.context.enabled);
    const quickFiltersText = quickFilterLabels.length ? quickFilterLabels.join("; ") : "none";
    if (!allRecords.length) {
      const activeExpression = activePreviousRunsColumnFilters()
        .map(filter => {
          const meta = previousRunsColumnMeta(filter.field);
          return meta.label + " " + formatPreviousRunsColumnFilterSummary(filter.field, filter);
        })
        .join("; ");
      updatePreviousRunsFilterStatus({
        total: rawRecords.length,
        matched: 0,
        expression: activeExpression || "(none)",
        quick_filters_text: quickFiltersText,
        column_filter_global_mode: normalizePreviousRunsColumnFilterGlobalMode(
          previousRunsColumnFilterGlobalMode
        ),
        error: null,
      });
      renderCompareControlPanel({
        records: [],
      });
      return {
        records: [],
        total: rawRecords.length,
        error: null,
      };
    }

    const compiled = compilePreviousRunsFilterPredicate();
    const matchedRecords = compiled.error
      ? allRecords
      : allRecords.filter(compiled.predicate);
    updatePreviousRunsFilterStatus({
      total: rawRecords.length,
      matched: matchedRecords.length,
      expression: compiled.expression,
      quick_filters_text: quickFiltersText,
      column_filter_global_mode: compiled.global_mode,
      error: compiled.error,
    });
    renderCompareControlPanel({
      records: matchedRecords,
    });
    return {
      records: matchedRecords,
      total: rawRecords.length,
      error: compiled.error,
    };
  }

  function compilePreviousRunsFilterPredicate() {
    const filters = activePreviousRunsColumnFilters();
    const globalMode = normalizePreviousRunsColumnFilterGlobalMode(
      previousRunsColumnFilterGlobalMode
    );
    if (!filters.length) {
      return {
        predicate: () => true,
        expression: "(none)",
        global_mode: globalMode,
        error: null,
      };
    }

    for (const filter of filters) {
      if (filter.operator !== "regex") continue;
      try {
        new RegExp(String(filter.value || ""), "i");
      } catch (error) {
        return {
          predicate: () => true,
          expression: formatPreviousRunsColumnFilterSummary(filter.field, filter),
          global_mode: globalMode,
          error: "Invalid regex for " + filter.field + ".",
        };
      }
    }

    const groupedFilters = groupPreviousRunsFiltersByField(filters);
    const topJoinLabel = " " + String(PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL[globalMode] || globalMode).toUpperCase() + " ";

    return {
      predicate: record => recordMatchesPreviousRunsFilterGroups(record, groupedFilters, globalMode),
      expression: groupedFilters
        .map(group => {
          const meta = previousRunsColumnMeta(group.field);
          const mode = normalizePreviousRunsColumnFilterMode(group.mode);
          const joinLabel = " " + String(PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL[mode] || mode).toUpperCase() + " ";
          const clauseText = group.clauses
            .map(clause => formatPreviousRunsColumnFilterSummary(group.field, clause))
            .join(joinLabel);
          if (group.clauses.length > 1) {
            return meta.label + " (" + clauseText + ")";
          }
          return meta.label + " " + clauseText;
        })
        .join(topJoinLabel),
      global_mode: globalMode,
      error: null,
    };
  }

  function evaluatePreviousRunsFilterOperator(value, operator, expected) {
    const op = String(operator || "contains");
    const wanted = String(expected || "");

    if (op === "is_empty") return isEmptyRuleValue(value);
    if (op === "not_empty") return !isEmptyRuleValue(value);

    const actualText = normalizeRuleValue(value);
    const expectedText = normalizeRuleValue(wanted);
    if (op === "contains") return actualText.includes(expectedText);
    if (op === "not_contains") return !actualText.includes(expectedText);
    if (op === "starts_with") return actualText.startsWith(expectedText);
    if (op === "ends_with") return actualText.endsWith(expectedText);
    if (op === "regex") {
      try {
        const pattern = new RegExp(wanted, "i");
        return pattern.test(String(value == null ? "" : value));
      } catch (error) {
        return false;
      }
    }

    const leftNumber = maybeNumber(value);
    const rightNumber = maybeNumber(wanted);
    if (op === "gt") return leftNumber != null && rightNumber != null && leftNumber > rightNumber;
    if (op === "gte") return leftNumber != null && rightNumber != null && leftNumber >= rightNumber;
    if (op === "lt") return leftNumber != null && rightNumber != null && leftNumber < rightNumber;
    if (op === "lte") return leftNumber != null && rightNumber != null && leftNumber <= rightNumber;

    if (op === "eq" || op === "neq") {
      let equal = false;
      if (leftNumber != null && rightNumber != null) {
        equal = leftNumber === rightNumber;
      } else {
        equal = actualText === expectedText;
      }
      return op === "eq" ? equal : !equal;
    }
    return false;
  }

  function previousRunsFieldValue(record, fieldPath) {
    if (fieldPath === "source_file_basename") return basename(record.source_file || "");
    if (fieldPath === "source_label") return sourceLabelForRecord(record);
    if (fieldPath === "ai_model") return aiModelLabelForRecord(record);
    if (fieldPath === "ai_effort") return aiEffortLabelForRecord(record);
    if (fieldPath === "ai_model_effort") return aiModelEffortLabelForRecord(record);
    if (fieldPath === "all_token_use") {
      const tokensInput = maybeNumber(record && record.tokens_input);
      const tokensCachedInput = maybeNumber(record && record.tokens_cached_input);
      const tokensOutput = maybeNumber(record && record.tokens_output);
      const tokensTotal = maybeNumber(record && record.tokens_total);
      return previousRunsDiscountedTokenTotal(
        tokensInput,
        tokensCachedInput,
        tokensOutput,
        tokensTotal,
      );
    }
    if (fieldPath === "artifact_dir_basename") return basename(record.artifact_dir || "");
    if (fieldPath === "all_method_record") return isAllMethodBenchmarkRecord(record);
    if (fieldPath === "speed_suite_record") return isSpeedBenchmarkRecord(record);
    if (!fieldPath) return null;

    const parts = fieldPath.split(".");
    let current = record;
    for (let idx = 0; idx < parts.length; idx += 1) {
      const key = parts[idx];
      if (current == null || typeof current !== "object" || !(key in current)) {
        return null;
      }
      current = current[key];
    }
    if (Array.isArray(current) || (current && typeof current === "object")) {
      try {
        return JSON.stringify(current);
      } catch (error) {
        return String(current);
      }
    }
    return current;
  }

  function maybeNumber(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "boolean") return value ? 1 : 0;
    const parsed = Number(String(value == null ? "" : value).trim());
    return Number.isFinite(parsed) ? parsed : null;
  }

  function normalizeRuleValue(value) {
    if (value == null) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value).toLowerCase().trim();
  }

  function isEmptyRuleValue(value) {
    if (value == null) return true;
    if (typeof value === "string") return value.trim() === "";
    if (Array.isArray(value)) return value.length === 0;
    return false;
  }

  function updatePreviousRunsFilterStatus(result) {
    const status = document.getElementById("previous-runs-filter-status");
    if (!status) return;
    const header = "Showing " + result.matched + " of " + result.total + " rows.";
    const quickFiltersPart = result.quick_filters_text
      ? " Quick filters: " + result.quick_filters_text + "."
      : "";
    const activeFilters = activePreviousRunsColumnFilters();
    const filtersPart = activeFilters.length
      ? " Active filters: " + result.expression + "."
      : " Active filters: none.";
    const globalMode = normalizePreviousRunsColumnFilterGlobalMode(
      result.column_filter_global_mode
    );
    const globalModePart = " Column combine: " + (
      globalMode === "or"
        ? "OR across columns."
        : "AND across columns."
    );
    if (result.error) {
      status.textContent = (
        header +
        quickFiltersPart +
        filtersPart +
        globalModePart +
        " Filter error: " +
        result.error +
        " (showing unfiltered rows)."
      );
      status.classList.add("filter-error");
      return;
    }
    status.textContent = header + quickFiltersPart + filtersPart + globalModePart;
    status.classList.remove("filter-error");
  }

  // ---- Render all sections ----
  function renderAll() {
    previousRunsFilterResultCache = null;
    renderPreviousRuns();
    renderBenchmarkTrendChart();
    renderLatestRuntime();
    renderPerLabel();
    renderBoundary();
    setupResizableDashboardTables();
  }

  function ensureResizableTableColgroup(table, columnCount) {
    if (!(table instanceof HTMLTableElement) || columnCount <= 0) return [];
    let colgroup = table.querySelector("colgroup");
    if (!colgroup) {
      colgroup = document.createElement("colgroup");
      table.insertBefore(colgroup, table.firstChild);
    }
    while (colgroup.children.length < columnCount) {
      colgroup.appendChild(document.createElement("col"));
    }
    while (colgroup.children.length > columnCount) {
      colgroup.removeChild(colgroup.lastChild);
    }
    return Array.from(colgroup.querySelectorAll("col"));
  }

  function setupResizableDashboardTable(table, options) {
    if (!(table instanceof HTMLTableElement)) return;
    const tableKey = String((options && options.tableKey) || table.id || "").trim();
    if (!tableKey) return;
    let cells = Array.from(table.querySelectorAll("thead tr:first-child > th"));
    if (!cells.length) {
      const fallbackRow = table.querySelector("tbody tr");
      if (fallbackRow) {
        cells = Array.from(fallbackRow.querySelectorAll(":scope > th, :scope > td"));
      }
    }
    if (!cells.length) return;
    const cols = ensureResizableTableColgroup(table, cells.length);
    if (!cols.length) return;
    table.classList.add("dashboard-resizable-table");
    cells.forEach((cell, index) => {
      if (!(cell instanceof HTMLElement)) return;
      const columnKey = "col_" + index;
      const col = cols[index];
      const persistedWidth = dashboardTableColumnWidth(tableKey, columnKey);
      if (persistedWidth != null) {
        col.style.width = persistedWidth + "px";
      }

      Array.from(cell.querySelectorAll(".dashboard-table-resize-handle")).forEach(handle => {
        handle.remove();
      });
      const resizeHandle = document.createElement("span");
      resizeHandle.className = "dashboard-table-resize-handle";
      resizeHandle.setAttribute("aria-hidden", "true");
      resizeHandle.draggable = false;
      resizeHandle.addEventListener("mousedown", event => {
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX;
        const startWidth = col.getBoundingClientRect().width || cell.getBoundingClientRect().width;
        const minWidth = 72;
        document.body.classList.add("dashboard-table-resizing");

        const onMove = moveEvent => {
          const nextWidth = Math.max(minWidth, startWidth + (moveEvent.clientX - startX));
          col.style.width = nextWidth + "px";
          setDashboardTableColumnWidth(tableKey, columnKey, nextWidth);
        };

        const onUp = () => {
          document.body.classList.remove("dashboard-table-resizing");
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          persistDashboardUiState();
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      });
      cell.appendChild(resizeHandle);
    });
  }

  function setupResizableDashboardTables() {
    // Keep Per-Label Breakdown content-sized and clear previously persisted drag widths.
    clearDashboardTableColumnWidths("per-label-table");
  }

  function latestPreferredBenchmarkRecord(records) {
    const sorted = [...records].sort((a, b) =>
      compareRunTimestampDesc(a.run_timestamp, b.run_timestamp)
    );
    const nonSpeed = sorted.filter(r => !isSpeedBenchmarkRecord(r));
    const preferred = nonSpeed.length > 0 ? nonSpeed : sorted;
    if (!preferred.length) return null;
    const latestTs = String(preferred[0].run_timestamp || "");
    const latestGroup = preferred.filter(
      record => String(record.run_timestamp || "") === latestTs
    );
    if (latestGroup.length <= 1) {
      return latestGroup[0];
    }
    let best = latestGroup[0];
    function score(record) {
      const model = aiModelForRecord(record);
      const effort = aiEffortForRecord(record);
      const pipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
      const pipelineText = String(pipeline || "").toLowerCase();
      const pipelineOn = pipelineText && pipelineText !== "off";
      return [
        model ? 2 : 0,
        effort ? 1 : 0,
        pipelineOn ? 1 : 0,
      ];
    }
    latestGroup.slice(1).forEach(candidate => {
      const bestScore = score(best);
      const nextScore = score(candidate);
      for (let i = 0; i < bestScore.length; i++) {
        if (nextScore[i] > bestScore[i]) {
          best = candidate;
          return;
        }
        if (nextScore[i] < bestScore[i]) {
          return;
        }
      }
    });
    return best;
  }

  function hasHighchartsStock() {
    return (
      typeof window !== "undefined" &&
      window.Highcharts &&
      typeof window.Highcharts.stockChart === "function"
    );
  }

  function hasHighchartsAreaRange() {
    return (
      typeof window !== "undefined" &&
      window.Highcharts &&
      window.Highcharts.seriesTypes &&
      typeof window.Highcharts.seriesTypes.arearange === "function"
    );
  }

  function benchmarkVariantFromPathOrPipeline(record) {
    const path = benchmarkArtifactPath(record);
    if (path.includes("/codexfarm/") || path.endsWith("/codexfarm")) return "codexfarm";
    if (path.includes("/vanilla/") || path.endsWith("/vanilla")) return "vanilla";
    const pipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
    if (pipeline) {
      const pipelineText = String(pipeline).toLowerCase();
      if (pipelineText === "off") return "vanilla";
      return "codexfarm";
    }
    return null;
  }

  function benchmarkVariantForRecord(record) {
    const pipelineOrPathVariant = benchmarkVariantFromPathOrPipeline(record);
    if (pipelineOrPathVariant) return pipelineOrPathVariant;
    if (rawAiModelForRecord(record) || rawAiEffortForRecord(record)) return "codexfarm";
    return "other";
  }

  function benchmarkRunGroupInfo(record) {
    const fallbackTimestamp = String((record && record.run_timestamp) || "").trim();
    const rawPath = String((record && record.artifact_dir) || "")
      .trim()
      .replace(/\\\\/g, "/");
    let runToken = "";
    if (rawPath) {
      const parts = rawPath.split("/").filter(Boolean);
      for (let i = 0; i < parts.length - 1; i++) {
        const segment = String(parts[i] || "").toLowerCase();
        if (segment !== "benchmark-vs-golden") continue;
        const candidate = String(parts[i + 1] || "");
        if (!isTimestampTokenText(candidate)) continue;
        runToken = candidate;
        break;
      }
    }
    if (!runToken && rawPath) {
      const parts = rawPath.split("/").filter(Boolean);
      for (let i = parts.length - 1; i >= 0; i--) {
        const candidate = String(parts[i] || "");
        if (!isTimestampTokenText(candidate)) continue;
        runToken = candidate;
        break;
      }
    }
    const runGroupLabel = runToken || fallbackTimestamp || "-";
    const runGroupKey = runToken || fallbackTimestamp || rawPath || "-";
    const runGroupTimestampText = runToken || fallbackTimestamp || "";
    return { runGroupKey, runGroupLabel, runGroupTimestampText };
  }

  function benchmarkRunGroupXAxisTimestampMs(record, runGroup) {
    const candidates = [];
    const groupTimestampText = String((runGroup && runGroup.runGroupTimestampText) || "").trim();
    if (groupTimestampText) candidates.push(groupTimestampText);
    const recordTimestampText = String((record && record.run_timestamp) || "").trim();
    if (recordTimestampText) candidates.push(recordTimestampText);
    for (let i = 0; i < candidates.length; i++) {
      const ts = parseTs(candidates[i]);
      if (!ts) continue;
      return ts.getTime();
    }
    return null;
  }

  function benchmarkSeriesFromRecords(records, metricKey, variantKey) {
    return records
      .map(record => {
        if (!record) return null;
        if (variantKey && benchmarkVariantForRecord(record) !== variantKey) return null;
        const value = record[metricKey];
        if (value == null) return null;
        const parsedValue = Number(value);
        if (!Number.isFinite(parsedValue)) return null;
        const runGroup = benchmarkRunGroupInfo(record);
        const xMs = benchmarkRunGroupXAxisTimestampMs(record, runGroup);
        if (xMs == null) return null;
        return {
          x: xMs,
          y: parsedValue,
          custom: {
            runGroupKey: runGroup.runGroupKey,
            runGroupLabel: runGroup.runGroupLabel,
          },
        };
      })
      .filter(point => point !== null)
      .sort((a, b) => a.x - b.x);
  }

  function trendSeriesPointForRunGroup(series, runGroupKey, hoveredX) {
    if (!series || !Array.isArray(series.points)) return null;
    let best = null;
    const target = Number(hoveredX || 0);
    series.points.forEach(point => {
      if (!point) return;
      const custom = (point.options && point.options.custom) || point.custom || {};
      if (String(custom.runGroupKey || "") !== runGroupKey) return;
      if (!best) {
        best = point;
        return;
      }
      const pointDelta = Math.abs(Number(point.x || 0) - target);
      const bestDelta = Math.abs(Number(best.x || 0) - target);
      if (pointDelta < bestDelta) {
        best = point;
      }
    });
    return best;
  }

  function buildTrendRegression(points) {
    const usable = Array.isArray(points)
      ? points
        .map(point => {
          const x = Number(point && point.x);
          const y = Number(point && point.y);
          if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
          const custom = (point && point.custom) || {};
          return { x, y, custom };
        })
        .filter(point => point !== null)
        .sort((a, b) => a.x - b.x)
      : [];
    if (!usable.length) return null;

    const count = usable.length;
    const meanX = usable.reduce((sum, point) => sum + point.x, 0) / count;
    const meanY = usable.reduce((sum, point) => sum + point.y, 0) / count;
    let varianceX = 0;
    let covarianceXY = 0;
    usable.forEach(point => {
      const dx = point.x - meanX;
      varianceX += dx * dx;
      covarianceXY += dx * (point.y - meanY);
    });
    const slope = varianceX > 0 ? covarianceXY / varianceX : 0;
    const intercept = meanY - slope * meanX;

    const trendPoints = usable.map(point => ({
      x: point.x,
      y: intercept + slope * point.x,
      custom: point.custom,
    }));
    let squaredError = 0;
    usable.forEach((point, index) => {
      const residual = point.y - trendPoints[index].y;
      squaredError += residual * residual;
    });
    const stdDev = Math.sqrt(squaredError / count);
    if (!Number.isFinite(stdDev)) return null;

    const bandPoints = trendPoints.map(point => ({
      x: point.x,
      low: point.y - stdDev,
      high: point.y + stdDev,
      custom: point.custom,
    }));
    return { trendPoints, bandPoints, stdDev };
  }

  function trendSeriesIdPart(name, index) {
    const base = String(name || "series")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    const safe = base || "series";
    return "trend-series-" + index + "-" + safe;
  }

  function withTrendOverlays(baseSeriesList) {
    const supportsAreaRange = hasHighchartsAreaRange();
    const output = [];
    (baseSeriesList || []).forEach((baseSeries, index) => {
      if (!baseSeries) return;
      const baseId = trendSeriesIdPart(baseSeries.name, index);
      const baseWithId = {
        ...baseSeries,
        id: baseId,
      };
      output.push(baseWithId);

      const regression = buildTrendRegression(baseSeries.data);
      if (!regression) return;

      if (supportsAreaRange) {
        output.push({
          id: baseId + "-std-band",
          name: baseSeries.name + " \u00b11\u03c3",
          type: "arearange",
          linkedTo: baseId,
          showInLegend: false,
          enableMouseTracking: false,
          color: baseSeries.color,
          fillOpacity: 0.14,
          lineWidth: 0,
          zIndex: 1,
          custom: { isTrendOverlay: true },
          data: regression.bandPoints,
          turboThreshold: 0,
        });
      }

      output.push({
        id: baseId + "-trendline",
        name: baseSeries.name + " trend",
        type: "line",
        linkedTo: baseId,
        showInLegend: false,
        enableMouseTracking: false,
        color: baseSeries.color,
        dashStyle: "ShortDash",
        lineWidth: 1.75,
        marker: { enabled: false },
        zIndex: 2,
        custom: { isTrendOverlay: true },
        data: regression.trendPoints,
        turboThreshold: 0,
      });
    });
    return output;
  }

  function isTrendOverlaySeries(series) {
    const options = (series && series.options) || {};
    const custom = (options && options.custom) || {};
    return Boolean(custom.isTrendOverlay);
  }

  function buildBenchmarkTrendSeries(records) {
    const metricDefs = [
      {
        key: "strict_accuracy",
        colors: {
          default: "#1f5ea8",
          vanilla: "#7daee8",
          codexfarm: "#1f5ea8",
          other: "#7f96b3",
        },
      },
      {
        key: "macro_f1_excluding_other",
        colors: {
          default: "#127a52",
          vanilla: "#55b895",
          codexfarm: "#127a52",
          other: "#6ea08c",
        },
      },
    ];
    const variantOrder = ["vanilla", "codexfarm", "other"];
    const presentVariants = new Set(
      records.map(record => benchmarkVariantForRecord(record))
    );
    const hasPairedVariants =
      presentVariants.has("vanilla") || presentVariants.has("codexfarm");

    const baseSeries = [];
    if (!hasPairedVariants) {
      metricDefs.forEach(metric => {
        baseSeries.push({
          name: metric.key,
          type: "scatter",
          lineWidth: 0,
          marker: {
            enabled: true,
            radius: 3,
          },
          color: metric.colors.default,
          data: benchmarkSeriesFromRecords(records, metric.key),
          turboThreshold: 0,
        });
      });
      return withTrendOverlays(
        baseSeries.filter(series => Array.isArray(series.data) && series.data.length > 0)
      );
    }

    metricDefs.forEach(metric => {
      variantOrder.forEach(variant => {
        if (!presentVariants.has(variant)) return;
        const points = benchmarkSeriesFromRecords(records, metric.key, variant);
        if (!points.length) return;
        baseSeries.push({
          name: metric.key + " (" + variant + ")",
          type: "scatter",
          lineWidth: 0,
          marker: {
            enabled: true,
            radius: 3,
          },
          color: metric.colors[variant] || metric.colors.default,
          data: points,
          turboThreshold: 0,
        });
      });
    });
    return withTrendOverlays(baseSeries);
  }

  function renderBenchmarkTrendChart() {
    const chartHost = document.getElementById("benchmark-trend-chart");
    if (!chartHost) return;
    const fallback = document.getElementById("benchmark-trend-fallback");
    const filterResult = currentPreviousRunsFilterResult();
    const records = filterResult.records;
    const sorted = [...records].sort((a, b) =>
      compareRunTimestampAsc(a.run_timestamp, b.run_timestamp)
    );
    const trendSeries = buildBenchmarkTrendSeries(sorted);
    const allRunTimestamps = sorted
      .map(record => {
        const ts = parseTs(record.run_timestamp);
        return ts ? ts.getTime() : null;
      })
      .filter(value => value != null)
      .sort((a, b) => a - b);
    const timelineMin = allRunTimestamps.length ? allRunTimestamps[0] : null;
    const timelineMax = allRunTimestamps.length ? allRunTimestamps[allRunTimestamps.length - 1] : null;
    const pointCount = trendSeries.reduce(
      (total, series) => total + (series.data ? series.data.length : 0),
      0,
    );

    if (pointCount === 0) {
      chartHost.innerHTML = "";
      if (fallback) {
        fallback.hidden = false;
        if (filterResult.total > 0 && records.length === 0) {
          fallback.textContent = "No benchmark rows match the current Previous Runs filters.";
        } else {
          fallback.textContent = "No benchmark score points available yet.";
        }
      }
      return;
    }

    if (!hasHighchartsStock()) {
      chartHost.innerHTML = "";
      if (fallback) {
        fallback.hidden = false;
        fallback.textContent =
          "Highcharts did not load, so the interactive trend chart is unavailable. The run table is still usable below.";
      }
      return;
    }

    if (fallback) {
      fallback.hidden = true;
      fallback.textContent = "";
    }

    const xAxisConfig = {
      type: "datetime",
    };
    if (timelineMin != null) xAxisConfig.min = timelineMin;
    if (timelineMax != null) xAxisConfig.max = timelineMax;

    window.Highcharts.stockChart("benchmark-trend-chart", {
      chart: {
        height: 800,
      },
      credits: { enabled: false },
      title: { text: "Explicit Benchmark Score Trends" },
      legend: { enabled: true },
      rangeSelector: {
        // Start on full history so default chart span matches long-run table context.
        buttons: [
          { type: "month", count: 1, text: "1m" },
          { type: "month", count: 3, text: "3m" },
          { type: "month", count: 6, text: "6m" },
          { type: "ytd", text: "YTD" },
          { type: "year", count: 1, text: "1y" },
          { type: "all", text: "All" },
        ],
        selected: 5,
        inputEnabled: false,
      },
      xAxis: xAxisConfig,
      yAxis: [
        {
          title: { text: "Score (0-1)" },
          min: 0,
          max: 1,
        },
      ],
      tooltip: {
        shared: false,
        useHTML: true,
        formatter: function() {
          const hoveredPoint =
            this.point ||
            (Array.isArray(this.points) && this.points.length ? this.points[0].point : null);
          if (!hoveredPoint) return false;
          const hoveredCustom =
            (hoveredPoint.options && hoveredPoint.options.custom) || hoveredPoint.custom || {};
          const runGroupKey = String(hoveredCustom.runGroupKey || "").trim();
          if (!runGroupKey) return false;

          const hoveredX = Number(hoveredPoint.x || 0);
          const chart = hoveredPoint.series && hoveredPoint.series.chart;
          if (!chart) return false;

          const rows = [];
          chart.series.forEach(series => {
            if (!series || series.visible === false || isTrendOverlaySeries(series)) return;
            const match = trendSeriesPointForRunGroup(series, runGroupKey, hoveredX);
            if (!match) return;
            const score = Number(match.y);
            if (!Number.isFinite(score)) return;
            rows.push({
              name: String(series.name || ""),
              color: String(series.color || "#2f2f2f"),
              score,
            });
          });
          if (!rows.length) return false;
          rows.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));

          const label = String(hoveredCustom.runGroupLabel || "").trim();
          const header = label && label !== "-"
            ? label
            : window.Highcharts.dateFormat("%A, %b %e, %Y, %I:%M:%S %p", hoveredX);
          let html = '<span style="font-size: 0.85rem"><b>' + esc(header) + "</b></span><br/>";
          rows.forEach(row => {
            html +=
              '<span style="color:' + row.color + '">&#9679;</span> ' +
              esc(row.name) +
              ': <b>' +
              row.score.toFixed(4) +
              "</b><br/>";
          });
          return html;
        },
      },
      series: trendSeries,
    });
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
      .map(r => r.strict_accuracy)
      .filter(v => v != null && Number.isFinite(v));
    const macroValues = benchmarks
      .map(r => r.macro_f1_excluding_other)
      .filter(v => v != null && Number.isFinite(v));
    const medianPerRecipe = median(perRecipeValues);
    const strictMean = mean(strictValues);
    const macroMean = mean(macroValues);
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
        label: "Mean strict_accuracy",
        value: strictMean == null ? "-" : (strictMean * 100).toFixed(1) + "%",
        detail: "macro_f1_excluding_other " + (macroMean == null ? "-" : (macroMean * 100).toFixed(1) + "%"),
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
          '<td>' + esc(importerLabelForRecord(r)) + '</td>' +
          '<td class="num">' + (r.total_seconds != null ? r.total_seconds.toFixed(2) : "-") + '</td>' +
          '<td class="num">' + (r.recipes != null ? r.recipes : "-") + '</td>' +
          '<td class="num">' + (r.per_recipe_seconds != null ? r.per_recipe_seconds.toFixed(3) : "-") + '</td>' +
          extractorCells(r) +
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
          '<td>' + esc(importerLabelForRecord(r)) + '</td>' +
          extractorCells(r) +
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
        '<span class="chart-legend-item"><span class="chart-legend-dot" style="background:#127a52"></span>macro_f1_excluding_other</span>' +
        '<span class="chart-legend-item"><span class="chart-legend-dot" style="background:#1f5ea8"></span>strict_accuracy</span>'
      );
    }

    const chartDiv = document.getElementById("benchmark-chart");
    const macroPoints = records
      .filter(r => r.macro_f1_excluding_other != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.macro_f1_excluding_other,
        label: (r.run_timestamp || "") + " macro_f1_excluding_other=" + (r.macro_f1_excluding_other != null ? r.macro_f1_excluding_other.toFixed(4) : "?")
      }))
      .sort((a, b) => a.x - b.x);

    const strictPoints = records
      .filter(r => r.strict_accuracy != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.strict_accuracy,
        label: (r.run_timestamp || "") + " strict_accuracy=" + (r.strict_accuracy != null ? r.strict_accuracy.toFixed(4) : "?")
      }))
      .sort((a, b) => a.x - b.x);

    chartDiv.innerHTML = svgLineChart(
      [
        { name: "macro_f1_excluding_other", color: "#127a52", points: macroPoints },
        { name: "strict_accuracy", color: "#1f5ea8", points: strictPoints },
      ],
      {
        width: Math.min(920, Math.max(400, Math.max(macroPoints.length, strictPoints.length) * 38)),
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
        const sourceLabel = sourceLabelForRecord(r);
        const sourceTitle = sourceTitleForRecord(r);
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
          '<td class="num">' + fmt4(r.strict_accuracy) + '</td>' +
          '<td class="num">' + fmt4(r.macro_f1_excluding_other) + mismatchTag + '</td>' +
          '<td class="num">' + (r.gold_total != null ? r.gold_total : "-") + '</td>' +
          '<td class="num">' + (r.gold_matched != null ? r.gold_matched : "-") + '</td>' +
          '<td class="num">' + (r.recipes != null ? r.recipes : "-") + '</td>' +
          '<td title="' + esc(sourceTitle) + '">' + esc(sourceLabel || "-") + '</td>' +
          '<td>' + esc(importerLabelForRecord(r)) + '</td>' +
          '<td title="' + esc(configRaw) + '">' + esc(configSummary || "-") + '</td>' +
          '<td><a href="' + esc(r.artifact_dir || "") + '">' + esc(shortPath(r.artifact_dir)) + '</a>' + processedReportLink + '</td>';
        return tr;
      },
    });
  }

  function renderPreviousRunsTableColumns(table, columns) {
    const previousRunsTableKey = "previous-runs-table";
    const colgroup = table.querySelector("colgroup");
    const headerRow = table.querySelector("thead tr.previous-runs-header-row");
    const filterRow = table.querySelector("thead tr.previous-runs-active-filters-row");
    const spacerRow = table.querySelector("thead tr.previous-runs-filter-spacer-row");
    if (!colgroup || !headerRow || !filterRow || !spacerRow) return;

    colgroup.innerHTML = "";
    headerRow.innerHTML = "";
    filterRow.innerHTML = "";
    spacerRow.innerHTML = "";
    columns.forEach(fieldName => {
      const meta = previousRunsColumnMeta(fieldName);
      const filterClauses = previousRunsColumnFilterClauses(fieldName);
      const hasActiveFilters = filterClauses.length > 0;
      const isEditorOpen = previousRunsOpenFilterField === fieldName;
      const draftState = currentPreviousRunsColumnFilterDraft(fieldName);
      const col = document.createElement("col");
      col.dataset.columnKey = fieldName;
      const width = Number(previousRunsColumnWidths[fieldName]);
      const persistedWidth = Number.isFinite(width)
        ? Math.max(72, width)
        : dashboardTableColumnWidth(previousRunsTableKey, fieldName);
      if (persistedWidth != null) {
        previousRunsColumnWidths[fieldName] = persistedWidth;
        setDashboardTableColumnWidth(previousRunsTableKey, fieldName, persistedWidth);
        col.style.width = persistedWidth + "px";
      }
      colgroup.appendChild(col);

      const th = document.createElement("th");
      th.dataset.columnKey = fieldName;
      const isSorted = previousRunsSortField === fieldName;
      const sortIndicator = isSorted
        ? (previousRunsSortDirection === "asc" ? " ▲" : " ▼")
        : "";

      const titleWrap = document.createElement("span");
      titleWrap.className = "previous-runs-header-title";
      const titleText = document.createElement("span");
      titleText.textContent = (meta.label || fieldName) + sortIndicator;
      titleWrap.appendChild(titleText);
      th.appendChild(titleWrap);

      th.title = (meta.title || fieldName) + " Click to sort A→Z / Z→A.";
      th.classList.add("previous-runs-draggable");
      th.draggable = true;
      if (meta.numeric) {
        th.classList.add("num");
      }
      th.addEventListener("click", event => {
        if (
          event.target instanceof HTMLElement
          && event.target.classList.contains("previous-runs-resize-handle")
        ) {
          return;
        }
        if (previousRunsSortField === fieldName) {
          previousRunsSortDirection = previousRunsSortDirection === "asc" ? "desc" : "asc";
        } else {
          previousRunsSortField = fieldName;
          previousRunsSortDirection = fieldName === "run_timestamp" ? "desc" : "asc";
        }
        renderPreviousRuns();
      });
      th.addEventListener("dragstart", event => {
        previousRunsDraggedColumn = fieldName;
        th.classList.add("previous-runs-drag-source");
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", fieldName);
        }
      });
      th.addEventListener("dragover", event => {
        if (!previousRunsDraggedColumn || previousRunsDraggedColumn === fieldName) return;
        event.preventDefault();
        if (event.dataTransfer) {
          event.dataTransfer.dropEffect = "move";
        }
        th.classList.add("previous-runs-drag-target");
      });
      th.addEventListener("dragleave", () => {
        th.classList.remove("previous-runs-drag-target");
      });
      th.addEventListener("drop", event => {
        event.preventDefault();
        th.classList.remove("previous-runs-drag-target");
        const sourceField = previousRunsDraggedColumn || (
          event.dataTransfer ? event.dataTransfer.getData("text/plain") : ""
        );
        if (!sourceField || sourceField === fieldName) return;
        if (reorderPreviousRunsColumns(sourceField, fieldName)) {
          renderPreviousRunsColumnEditor();
          renderPreviousRuns();
        }
      });
      th.addEventListener("dragend", () => {
        previousRunsDraggedColumn = null;
        headerRow.querySelectorAll("th").forEach(candidate => {
          candidate.classList.remove("previous-runs-drag-source");
          candidate.classList.remove("previous-runs-drag-target");
        });
      });

      const resizeHandle = document.createElement("span");
      resizeHandle.className = "previous-runs-resize-handle";
      resizeHandle.setAttribute("aria-hidden", "true");
      resizeHandle.draggable = false;
      resizeHandle.addEventListener("mousedown", event => {
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX;
        const startWidth = th.getBoundingClientRect().width;
        const minWidth = 72;
        document.body.classList.add("previous-runs-resizing");

        const onMove = moveEvent => {
          const nextWidth = Math.max(minWidth, startWidth + (moveEvent.clientX - startX));
          previousRunsColumnWidths[fieldName] = nextWidth;
          setDashboardTableColumnWidth(previousRunsTableKey, fieldName, nextWidth);
          th.style.width = nextWidth + "px";
          col.style.width = nextWidth + "px";
        };

        const onUp = () => {
          document.body.classList.remove("previous-runs-resizing");
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          persistDashboardUiState();
        };

        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      });
      th.appendChild(resizeHandle);
      headerRow.appendChild(th);

      const filterTh = document.createElement("th");
      filterTh.dataset.columnKey = fieldName;
      const filterWrap = document.createElement("div");
      filterWrap.className = "previous-runs-column-filter";

      const summaryWrap = document.createElement("div");
      summaryWrap.className = "previous-runs-column-filter-summary-wrap";
      const summary = document.createElement("div");
      summary.className = "previous-runs-column-filter-summary";
      if (hasActiveFilters) {
        summary.classList.add("filter-active");
        const mode = previousRunsColumnFilterMode(fieldName);
        const joinLabel = String(PREVIOUS_RUNS_COLUMN_FILTER_MODE_LABEL[mode] || mode).toUpperCase();
        filterClauses.forEach((clause, clauseIndex) => {
          const summaryItem = document.createElement("div");
          summaryItem.className = "previous-runs-column-filter-summary-item";
          const summaryText = document.createElement("span");
          const prefix = clauseIndex > 0 ? joinLabel + " " : "";
          summaryText.textContent = prefix + formatPreviousRunsColumnFilterSummary(fieldName, clause);
          summaryItem.appendChild(summaryText);
          const summaryRemoveBtn = document.createElement("button");
          summaryRemoveBtn.type = "button";
          summaryRemoveBtn.className = "previous-runs-column-filter-summary-remove";
          setPreviousRunsIcon(summaryRemoveBtn, "close");
          summaryRemoveBtn.setAttribute("aria-label", "Remove filter " + String(clauseIndex + 1));
          summaryRemoveBtn.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            removePreviousRunsColumnFilterAt(fieldName, clauseIndex);
            renderAll();
          });
          summaryItem.appendChild(summaryRemoveBtn);
          summary.appendChild(summaryItem);
        });
      } else {
        summary.textContent = "No filter";
      }
      summaryWrap.appendChild(summary);

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "previous-runs-column-filter-toggle";
      if (hasActiveFilters) {
        toggleBtn.classList.add("filter-active");
      }
      setPreviousRunsIcon(toggleBtn, isEditorOpen ? "minus" : "plus");
      toggleBtn.title = isEditorOpen ? "Close filter editor" : "Open filter editor";
      toggleBtn.setAttribute("aria-label", (meta.label || fieldName) + " filter editor");
      toggleBtn.setAttribute("aria-expanded", isEditorOpen ? "true" : "false");
      toggleBtn.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        if (previousRunsOpenFilterField === fieldName) {
          closePreviousRunsColumnFilterEditor();
        } else {
          openPreviousRunsColumnFilterEditor(fieldName);
        }
        renderPreviousRuns();
      });
      summaryWrap.appendChild(toggleBtn);
      filterWrap.appendChild(summaryWrap);

      if (isEditorOpen) {
        const popover = document.createElement("div");
        popover.className = "previous-runs-column-filter-popover";
        const columnMode = previousRunsColumnFilterMode(fieldName);

        const popoverTitle = document.createElement("div");
        popoverTitle.className = "previous-runs-column-filter-popover-title";
        popoverTitle.textContent = (meta.label || fieldName) + " filter";
        popover.appendChild(popoverTitle);

        const modeWrap = document.createElement("div");
        modeWrap.className = "previous-runs-column-filter-mode";
        const modeLabel = document.createElement("span");
        modeLabel.className = "previous-runs-column-filter-mode-label";
        modeLabel.textContent = "Stack mode";
        modeWrap.appendChild(modeLabel);
        const modeButtons = document.createElement("div");
        modeButtons.className = "previous-runs-column-filter-mode-buttons";
        PREVIOUS_RUNS_COLUMN_FILTER_MODES.forEach(([modeValue, modeLabelText]) => {
          const modeBtn = document.createElement("button");
          modeBtn.type = "button";
          modeBtn.className = "previous-runs-column-filter-mode-btn";
          modeBtn.textContent = modeLabelText;
          if (modeValue === columnMode) {
            modeBtn.classList.add("active");
          }
          modeBtn.disabled = !hasActiveFilters;
          modeBtn.addEventListener("click", () => {
            if (!hasActiveFilters) return;
            setPreviousRunsColumnFilterMode(fieldName, modeValue);
            renderAll();
          });
          modeButtons.appendChild(modeBtn);
        });
        modeWrap.appendChild(modeButtons);
        popover.appendChild(modeWrap);

        const activeList = document.createElement("div");
        activeList.className = "previous-runs-column-filter-active-list";
        if (hasActiveFilters) {
          filterClauses.forEach((clause, clauseIndex) => {
            const row = document.createElement("div");
            row.className = "previous-runs-column-filter-active-item";
            const text = document.createElement("span");
            text.textContent = formatPreviousRunsColumnFilterSummary(fieldName, clause);
            row.appendChild(text);
            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "previous-runs-column-filter-active-remove";
            setPreviousRunsIcon(removeBtn, "close");
            removeBtn.setAttribute("aria-label", "Remove filter " + String(clauseIndex + 1));
            removeBtn.addEventListener("click", () => {
              removePreviousRunsColumnFilterAt(fieldName, clauseIndex);
              renderAll();
            });
            row.appendChild(removeBtn);
            activeList.appendChild(row);
          });
        } else {
          const empty = document.createElement("div");
          empty.className = "previous-runs-column-filter-active-empty";
          empty.textContent = "No active filters yet.";
          activeList.appendChild(empty);
        }
        popover.appendChild(activeList);

        const controls = document.createElement("div");
        controls.className = "previous-runs-column-filter-popover-controls";

        const operatorSelect = document.createElement("select");
        operatorSelect.setAttribute("aria-label", (meta.label || fieldName) + " filter operator");
        PREVIOUS_RUNS_COLUMN_FILTER_OPERATORS.forEach(([operatorValue, operatorLabel]) => {
          const option = document.createElement("option");
          option.value = operatorValue;
          option.textContent = operatorLabel;
          if (operatorValue === draftState.operator) {
            option.selected = true;
          }
          operatorSelect.appendChild(option);
        });
        controls.appendChild(operatorSelect);

        const valueInput = document.createElement("input");
        valueInput.type = "text";
        valueInput.value = draftState.value;
        valueInput.placeholder = meta.numeric ? "number" : "value";
        valueInput.setAttribute("aria-label", (meta.label || fieldName) + " filter value");
        valueInput.disabled = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(draftState.operator);
        controls.appendChild(valueInput);

        popover.appendChild(controls);

        const suggestionWrap = document.createElement("div");
        suggestionWrap.className = "previous-runs-column-filter-suggestions";
        const suggestionTitle = document.createElement("div");
        suggestionTitle.className = "previous-runs-column-filter-suggestions-title";
        suggestionWrap.appendChild(suggestionTitle);
        const suggestionList = document.createElement("div");
        suggestionList.className = "previous-runs-column-filter-suggestions-list";
        suggestionWrap.appendChild(suggestionList);
        popover.appendChild(suggestionWrap);

        function syncDraft(operatorValue, valueText) {
          const nextOperator = PREVIOUS_RUNS_COLUMN_FILTER_OPERATOR_MAP[operatorValue]
            ? String(operatorValue)
            : "contains";
          const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(nextOperator);
          const nextValue = unary ? "" : String(valueText || "");
          if (!previousRunsOpenFilterDraft || previousRunsOpenFilterField !== fieldName) {
            previousRunsOpenFilterDraft = {
              operator: nextOperator,
              value: nextValue,
            };
            return;
          }
          previousRunsOpenFilterDraft.operator = nextOperator;
          previousRunsOpenFilterDraft.value = nextValue;
        }

        function renderSuggestionList() {
          const operatorValue = String(operatorSelect.value || "contains");
          const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(operatorValue);
          if (unary || meta.numeric) {
            suggestionWrap.hidden = true;
            valueInput.dataset.topSuggestion = "";
            suggestionList.innerHTML = "";
            return;
          }

          const typedText = String(valueInput.value || "");
          const candidates = previousRunsColumnSuggestionCandidates(fieldName, typedText);
          const topCandidate = candidates.length ? candidates[0].value : "";
          valueInput.dataset.topSuggestion = topCandidate;
          suggestionWrap.hidden = false;
          suggestionList.innerHTML = "";
          if (!candidates.length) {
            suggestionTitle.textContent = "No matching suggestions.";
            return;
          }

          suggestionTitle.textContent = topCandidate
            ? "Tab completes top match."
            : "Suggestions";

          candidates.forEach((candidate, candidateIndex) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "previous-runs-column-filter-suggestion";
            if (candidateIndex === 0) {
              button.classList.add("best");
            }
            button.textContent = candidate.value;
            button.title = candidate.value + " (" + candidate.count + " rows)";
            button.addEventListener("click", () => {
              valueInput.value = candidate.value;
              syncDraft(operatorSelect.value || "contains", valueInput.value || "");
              renderSuggestionList();
              valueInput.focus();
            });
            suggestionList.appendChild(button);
          });
        }

        function applyFilterAndClose() {
          addPreviousRunsColumnFilter(fieldName, operatorSelect.value || "contains", valueInput.value || "");
          closePreviousRunsColumnFilterEditor();
          renderAll();
        }

        operatorSelect.addEventListener("change", () => {
          const nextOperator = String(operatorSelect.value || "contains");
          const unary = PREVIOUS_RUNS_UNARY_FILTER_OPERATORS.has(nextOperator);
          if (unary) {
            valueInput.value = "";
          }
          syncDraft(nextOperator, valueInput.value || "");
          valueInput.disabled = unary;
          renderSuggestionList();
        });

        valueInput.addEventListener("input", () => {
          syncDraft(operatorSelect.value || "contains", valueInput.value || "");
          renderSuggestionList();
        });
        valueInput.addEventListener("keydown", event => {
          if (event.key === "Tab" && !event.shiftKey) {
            const suggested = String(valueInput.dataset.topSuggestion || "");
            const current = String(valueInput.value || "");
            if (
              suggested &&
              normalizeRuleValue(suggested) !== normalizeRuleValue(current)
            ) {
              event.preventDefault();
              valueInput.value = suggested;
              syncDraft(operatorSelect.value || "contains", valueInput.value || "");
              renderSuggestionList();
              return;
            }
          }
          if (event.key !== "Enter") return;
          event.preventDefault();
          applyFilterAndClose();
        });

        const actions = document.createElement("div");
        actions.className = "previous-runs-column-filter-popover-actions";

        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "previous-runs-column-filter-save";
        saveBtn.textContent = "Save";
        saveBtn.addEventListener("click", applyFilterAndClose);
        actions.appendChild(saveBtn);

        const clearBtn = document.createElement("button");
        clearBtn.type = "button";
        clearBtn.className = "previous-runs-column-filter-clear";
        clearBtn.textContent = "Clear";
        clearBtn.disabled = !hasActiveFilters;
        clearBtn.addEventListener("click", () => {
          clearPreviousRunsColumnFilter(fieldName);
          closePreviousRunsColumnFilterEditor();
          renderAll();
        });
        actions.appendChild(clearBtn);

        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.className = "previous-runs-column-filter-close";
        closeBtn.textContent = "Close";
        closeBtn.addEventListener("click", () => {
          closePreviousRunsColumnFilterEditor();
          renderPreviousRuns();
        });
        actions.appendChild(closeBtn);

        popover.appendChild(actions);
        renderSuggestionList();
        filterWrap.appendChild(popover);
      }

      filterTh.appendChild(filterWrap);
      filterRow.appendChild(filterTh);

      const spacerTh = document.createElement("th");
      spacerTh.dataset.columnKey = fieldName;
      spacerRow.appendChild(spacerTh);
    });

    const headerHeight = headerRow.getBoundingClientRect().height;
    const filterHeight = filterRow.getBoundingClientRect().height;
    const spacerHeight = spacerRow.getBoundingClientRect().height;
    if (headerHeight > 0) {
      table.style.setProperty("--previous-runs-header-row-height", headerHeight + "px");
    }
    if (filterHeight > 0) {
      table.style.setProperty("--previous-runs-filter-row-height", filterHeight + "px");
    }
    if (spacerHeight > 0) {
      table.style.setProperty("--previous-runs-spacer-row-height", spacerHeight + "px");
    }
  }

  function previousRunsRowFieldValue(row, fieldName) {
    if (fieldName === "run_timestamp") return row.run_timestamp || "";
    if (row.type === "all_method") {
      if (fieldName === "source_label") return row.source || "-";
      if (fieldName === "source_file_basename") return row.source || "-";
      if (fieldName === "importer_name") return row.importer_name || "-";
      if (fieldName === "ai_model") return row.ai_model || "-";
      if (fieldName === "ai_effort") return row.ai_effort || "-";
      if (fieldName === "ai_model_effort") return row.ai_model_effort || "-";
      if (fieldName === "all_token_use") {
        return previousRunsDiscountedTokenTotal(
          maybeNumber(row.tokens_input),
          maybeNumber(row.tokens_cached_input),
          maybeNumber(row.tokens_output),
          maybeNumber(row.tokens_total),
        );
      }
      if (fieldName === "artifact_dir") return row.href || "";
      if (Object.prototype.hasOwnProperty.call(row, fieldName)) {
        return row[fieldName];
      }
      return null;
    }

    const record = row.record;
    if (!record) return null;
    if (fieldName === "source_label") return sourceLabelForRecord(record);
    if (fieldName === "importer_name") return importerLabelForRecord(record);
    if (fieldName === "ai_model") return aiModelLabelForRecord(record);
    if (fieldName === "ai_effort") return aiEffortLabelForRecord(record);
    if (fieldName === "ai_model_effort") return aiModelEffortLabelForRecord(record);
    if (fieldName === "all_token_use") {
      return previousRunsDiscountedTokenTotal(
        maybeNumber(record.tokens_input),
        maybeNumber(record.tokens_cached_input),
        maybeNumber(record.tokens_output),
        maybeNumber(record.tokens_total),
      );
    }
    if (fieldName === "artifact_dir") return record.artifact_dir || "";
    return previousRunsFieldValue(record, fieldName);
  }

  function previousRunsDiscountedTokenTotal(tokensInput, tokensCachedInput, tokensOutput, tokensTotal) {
    const input = maybeNumber(tokensInput);
    const cached = maybeNumber(tokensCachedInput);
    const output = maybeNumber(tokensOutput);
    const rawTotal = maybeNumber(tokensTotal);
    if (input == null && cached == null && output == null) {
      return rawTotal;
    }

    let effectiveInput = input != null ? input : 0;
    if (cached != null) {
      if (input != null) {
        effectiveInput = Math.max(0, input - cached) + (cached * 0.1);
      } else {
        effectiveInput = cached * 0.1;
      }
    }
    const effectiveOutput = output != null ? output : 0;
    return effectiveInput + effectiveOutput;
  }

  function previousRunsTokenPartsForRow(row) {
    if (row.type === "all_method") {
      return {
        total: previousRunsDiscountedTokenTotal(
          maybeNumber(row.tokens_input),
          maybeNumber(row.tokens_cached_input),
          maybeNumber(row.tokens_output),
          maybeNumber(row.tokens_total),
        ),
        input: maybeNumber(row.tokens_input),
        cached_input: maybeNumber(row.tokens_cached_input),
        output: maybeNumber(row.tokens_output),
        raw_total: maybeNumber(row.tokens_total),
      };
    }
    const record = row.record || null;
    return {
      total: previousRunsDiscountedTokenTotal(
        maybeNumber(record && record.tokens_input),
        maybeNumber(record && record.tokens_cached_input),
        maybeNumber(record && record.tokens_output),
        maybeNumber(record && record.tokens_total),
      ),
      input: maybeNumber(record && record.tokens_input),
      cached_input: maybeNumber(record && record.tokens_cached_input),
      output: maybeNumber(record && record.tokens_output),
      raw_total: maybeNumber(record && record.tokens_total),
    };
  }

  function formatTokenCount(value) {
    if (value == null || !Number.isFinite(value)) return "-";
    const rounded = Math.round(value);
    if (Math.abs(value - rounded) < 1e-9) {
      return rounded.toLocaleString("en-US");
    }
    return value.toLocaleString("en-US", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
  }

  function formatTokenCountCompact(value) {
    if (value == null || !Number.isFinite(value)) return "-";
    const absValue = Math.abs(value);
    const sign = value < 0 ? "-" : "";
    if (absValue >= 1000000) {
      const millionsText = Number((absValue / 1000000).toFixed(2)).toString();
      return sign + millionsText + "m";
    }
    if (absValue >= 1000) {
      const thousands = Math.floor(absValue / 1000);
      return sign + String(thousands) + "k";
    }
    return formatTokenCount(value);
  }

  function previousRunsAllTokenUseDisplay(row) {
    const parts = previousRunsTokenPartsForRow(row);
    if (parts.total == null && parts.input == null && parts.output == null) {
      return "-";
    }
    return (
      formatTokenCountCompact(parts.total) +
      " total | " +
      formatTokenCountCompact(parts.input) +
      " in | " +
      formatTokenCountCompact(parts.output) +
      " out"
    );
  }

  function previousRunsAllTokenUseTitle(row) {
    const parts = previousRunsTokenPartsForRow(row);
    if (
      parts.total == null &&
      parts.input == null &&
      parts.cached_input == null &&
      parts.output == null
    ) {
      return "";
    }
    return (
      "discounted_total=" +
      formatTokenCount(parts.total) +
      " (cached input at 0.1x), raw_total=" +
      formatTokenCount(parts.raw_total) +
      ", input=" +
      formatTokenCount(parts.input) +
      ", cached_input=" +
      formatTokenCount(parts.cached_input) +
      ", output=" +
      formatTokenCount(parts.output)
    );
  }

  function previousRunsDisplayValue(fieldName, value) {
    if (value == null || value === "") return "-";
    if (fieldName === "run_timestamp") return String(value);
    if (PREVIOUS_RUNS_SCORE_FIELDS.has(fieldName)) return fmt4(value);
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return "-";
      return Number.isInteger(value) ? String(value) : Number(value).toFixed(4);
    }
    return String(value);
  }

  function previousRunsCellTitle(row, fieldName) {
    if (fieldName === "run_timestamp") {
      return row.href || "";
    }
    if (fieldName === "all_token_use") {
      return previousRunsAllTokenUseTitle(row);
    }
    if (row.type === "single" && fieldName === "source_label" && row.record) {
      return sourceTitleForRecord(row.record);
    }
    const value = previousRunsRowFieldValue(row, fieldName);
    if (value == null) return "";
    return typeof value === "string" ? value : String(value);
  }

  function previousRunsValueIsNumeric(fieldName, value) {
    if (previousRunsColumnMeta(fieldName).numeric) return true;
    if (PREVIOUS_RUNS_SCORE_FIELDS.has(fieldName)) return true;
    return typeof value === "number" && Number.isFinite(value);
  }

  function comparePreviousRunsFieldValues(fieldName, left, right) {
    if (fieldName === "run_timestamp") {
      return compareRunTimestampAsc(left, right);
    }

    const leftEmpty = left == null || left === "";
    const rightEmpty = right == null || right === "";
    if (leftEmpty && rightEmpty) return 0;
    if (leftEmpty) return 1;
    if (rightEmpty) return -1;

    const leftNumber = maybeNumber(left);
    const rightNumber = maybeNumber(right);
    if (leftNumber != null && rightNumber != null) {
      if (leftNumber < rightNumber) return -1;
      if (leftNumber > rightNumber) return 1;
      return 0;
    }

    const leftText = String(left).toLowerCase();
    const rightText = String(right).toLowerCase();
    return leftText.localeCompare(rightText, undefined, { numeric: true });
  }

  function comparePreviousRunsRows(leftRow, rightRow) {
    const fieldName = String(previousRunsSortField || "run_timestamp");
    const direction = previousRunsSortDirection === "asc" ? 1 : -1;
    const leftValue = previousRunsRowFieldValue(leftRow, fieldName);
    const rightValue = previousRunsRowFieldValue(rightRow, fieldName);
    const primary = comparePreviousRunsFieldValues(fieldName, leftValue, rightValue);
    if (primary !== 0) return primary * direction;

    const tieBreak = compareRunTimestampDesc(leftRow.run_timestamp, rightRow.run_timestamp);
    if (tieBreak !== 0) return tieBreak;
    const leftHref = String(leftRow.href || "");
    const rightHref = String(rightRow.href || "");
    return leftHref.localeCompare(rightHref);
  }

  function renderPreviousRunsCell(row, fieldName) {
    const td = document.createElement("td");
    if (fieldName === "run_timestamp") {
      const ts = row.run_timestamp || "";
      const href = row.href || "";
      if (href) {
        const link = document.createElement("a");
        link.href = href;
        link.title = href;
        link.textContent = ts || "-";
        td.appendChild(link);
      } else {
        td.textContent = ts || "-";
      }
      return td;
    }
    if (fieldName === "all_token_use") {
      const value = previousRunsRowFieldValue(row, fieldName);
      if (previousRunsValueIsNumeric(fieldName, value)) {
        td.classList.add("num");
      }
      td.textContent = previousRunsAllTokenUseDisplay(row);
      const title = previousRunsAllTokenUseTitle(row);
      if (title) {
        td.title = title;
      }
      return td;
    }

    const value = previousRunsRowFieldValue(row, fieldName);
    if (previousRunsValueIsNumeric(fieldName, value)) {
      td.classList.add("num");
    }
    td.textContent = previousRunsDisplayValue(fieldName, value);
    const title = previousRunsCellTitle(row, fieldName);
    if (title) {
      td.title = title;
    }
    return td;
  }

  // ---- Previous runs section ----
  function renderPreviousRuns() {
    const filterResult = currentPreviousRunsFilterResult();
    const records = filterResult.records;
    const section = document.getElementById("previous-runs-section");
    const table = document.getElementById("previous-runs-table");
    if (!section || !table) return;
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    ensurePreviousRunsColumns();
    setupPreviousRunsGlobalFilterModeControl();
    const visibleColumns = [...previousRunsVisibleColumns];
    renderPreviousRunsTableColumns(table, visibleColumns);
    renderPreviousRunsColumnEditor();

    if (records.length === 0) {
      const emptyMessage = filterResult.total === 0
        ? "No benchmark evaluation records found. Run an eval workflow to generate eval_report.json files."
        : "No benchmark rows match the current Previous Runs filters.";
      const colspan = Math.max(1, visibleColumns.length);
      tbody.innerHTML = '<tr><td colspan="' + colspan + '" class="empty-note-cell">' + esc(emptyMessage) + "</td></tr>";
      persistDashboardUiState();
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

    function isTimestampToken(token) {
      const text = String(token || "").trim();
      if (!text) return false;
      return /^\\d{4}-\\d{2}-\\d{2}[T_]\\d{2}[.:]\\d{2}[.:]\\d{2}(?:_.+)?$/.test(text);
    }

    function nearestRunTimestamp(parts, beforeIndex) {
      if (!Array.isArray(parts) || beforeIndex <= 0) return null;
      for (let i = beforeIndex - 1; i >= 0; i--) {
        const candidate = parts[i];
        if (isTimestampToken(candidate)) return String(candidate);
      }
      return null;
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
        const runDirTimestamp = nearestRunTimestamp(info.parts, idx);
        const fallbackTimestamp = String((record && record.run_timestamp) || "").trim();
        const runRootDir = info.prefix + info.parts.slice(0, idx + 1).join("/");
        const groupDir = info.prefix + info.parts.slice(0, idx + 2).join("/");
        return {
          runKey: runRootDir || groupDir,
          groupKey: groupDir,
          runDirTimestamp: runDirTimestamp || fallbackTimestamp || null,
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
          metric(best.macro_f1_excluding_other),
          metric(best.strict_accuracy),
          metric(best.f1),
          metric(best.practical_f1),
        ];
        const nextKey = [
          metric(next.macro_f1_excluding_other),
          metric(next.strict_accuracy),
          metric(next.f1),
          metric(next.practical_f1),
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

    function summarizeAllMethodSource(counts) {
      const labels = Object.keys(counts);
      if (!labels.length) return "all-method benchmark run";
      labels.sort((a, b) => {
        const countA = counts[a] || 0;
        const countB = counts[b] || 0;
        if (countB !== countA) return countB - countA;
        return String(a).localeCompare(String(b));
      });
      if (labels.length === 1) {
        return "all-method: " + labels[0];
      }
      return "all-method: " + labels[0] + " + " + (labels.length - 1) + " more";
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
      const sourceCounts = Object.create(null);
      const aiModelCounts = Object.create(null);
      const aiEffortCounts = Object.create(null);

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
              strictAccuracyValues: [],
              macroF1Values: [],
              goldTotalSum: 0,
              goldTotalN: 0,
                goldMatchedSum: 0,
                goldMatchedN: 0,
                recipesSum: 0,
                recipesN: 0,
                tokensInputSum: 0,
                tokensInputN: 0,
                tokensCachedInputSum: 0,
                tokensCachedInputN: 0,
                tokensOutputSum: 0,
                tokensOutputN: 0,
                tokensTotalSum: 0,
                tokensTotalN: 0,
                wins: 0,
              };
              state[configKey] = agg;
            }

          agg.groupKeys.add(group.groupKey);
          const importer = importerLabelForRecord(r);
          agg.importerCounts[importer] = (agg.importerCounts[importer] || 0) + 1;
          const sourceLabel = sourceLabelForRecord(r);
          if (sourceLabel && sourceLabel !== "-") {
            sourceCounts[sourceLabel] = (sourceCounts[sourceLabel] || 0) + 1;
          }
          const aiModel = aiModelLabelForRecord(r);
          if (aiModel && aiModel !== "-") {
            aiModelCounts[aiModel] = (aiModelCounts[aiModel] || 0) + 1;
          }
          const aiEffort = aiEffortLabelForRecord(r);
          if (aiEffort && aiEffort !== "-") {
            aiEffortCounts[aiEffort] = (aiEffortCounts[aiEffort] || 0) + 1;
          }
          if (r.strict_accuracy != null) agg.strictAccuracyValues.push(Number(r.strict_accuracy));
          if (r.macro_f1_excluding_other != null) agg.macroF1Values.push(Number(r.macro_f1_excluding_other));
          if (r.gold_total != null) { agg.goldTotalSum += Number(r.gold_total); agg.goldTotalN += 1; }
          if (r.gold_matched != null) { agg.goldMatchedSum += Number(r.gold_matched); agg.goldMatchedN += 1; }
          if (r.recipes != null) { agg.recipesSum += Number(r.recipes); agg.recipesN += 1; }
          if (r.tokens_input != null) { agg.tokensInputSum += Number(r.tokens_input); agg.tokensInputN += 1; }
          if (r.tokens_cached_input != null) { agg.tokensCachedInputSum += Number(r.tokens_cached_input); agg.tokensCachedInputN += 1; }
          if (r.tokens_output != null) { agg.tokensOutputSum += Number(r.tokens_output); agg.tokensOutputN += 1; }
          if (r.tokens_total != null) { agg.tokensTotalSum += Number(r.tokens_total); agg.tokensTotalN += 1; }
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
          strict_accuracy_mean: mean(agg.strictAccuracyValues),
          macro_f1_excluding_other_mean: mean(agg.macroF1Values),
          gold_total: agg.goldTotalN ? agg.goldTotalSum : null,
          gold_matched: agg.goldMatchedN ? agg.goldMatchedSum : null,
          recipes: agg.recipesN ? agg.recipesSum : null,
          tokens_input: agg.tokensInputN ? agg.tokensInputSum : null,
          tokens_cached_input: agg.tokensCachedInputN ? agg.tokensCachedInputSum : null,
          tokens_output: agg.tokensOutputN ? agg.tokensOutputSum : null,
          tokens_total: agg.tokensTotalN ? agg.tokensTotalSum : null,
          importer_name: importer,
        };
      });

      aggregates.sort((a, b) => {
        const aKey = [
          a.books,
          metric(a.macro_f1_excluding_other_mean),
          metric(a.strict_accuracy_mean),
          a.wins,
        ];
        const bKey = [
          b.books,
          metric(b.macro_f1_excluding_other_mean),
          metric(b.strict_accuracy_mean),
          b.wins,
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
      const sourceSummary = summarizeAllMethodSource(sourceCounts);
      const aiModel = mostCommonValue(aiModelCounts) || "-";
      const aiEffort = mostCommonValue(aiEffortCounts) || "-";

      return {
        type: "all_method",
        run_timestamp: ts,
        href,
        strict_accuracy: best ? best.strict_accuracy_mean : null,
        macro_f1_excluding_other: best ? best.macro_f1_excluding_other_mean : null,
        gold_total: best ? best.gold_total : null,
        gold_matched: best ? best.gold_matched : null,
        recipes: best ? best.recipes : null,
        tokens_input: best ? best.tokens_input : null,
        tokens_cached_input: best ? best.tokens_cached_input : null,
        tokens_output: best ? best.tokens_output : null,
        tokens_total: best ? best.tokens_total : null,
        source: sourceSummary,
        importer_name: best ? best.importer_name : "-",
        ai_model: aiModel,
        ai_effort: aiEffort,
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

    rows.sort((a, b) => comparePreviousRunsRows(a, b));
    tbody.innerHTML = "";
    rows.forEach(row => {
      const tr = document.createElement("tr");
      visibleColumns.forEach(fieldName => {
        tr.appendChild(renderPreviousRunsCell(row, fieldName));
      });
      tbody.appendChild(tr);
    });
    persistDashboardUiState();
  }

  // ---- Per-label section ----
  function aggregatePerLabelRows(records) {
    const byLabel = Object.create(null);
    (records || []).forEach(record => {
      const labels = Array.isArray(record && record.per_label) ? record.per_label : [];
      labels.forEach(lbl => {
        const label = String(lbl.label || "").trim();
        if (!label) return;
        if (!byLabel[label]) {
          byLabel[label] = {
            label,
            gold_total: 0,
            pred_total: 0,
            tp_from_recall: 0,
            tp_from_precision: 0,
            has_gold: false,
            has_pred: false,
          };
        }
        const agg = byLabel[label];
        const goldTotal = lbl.gold_total != null ? Number(lbl.gold_total) : null;
        const predTotal = lbl.pred_total != null ? Number(lbl.pred_total) : null;
        const recall = lbl.recall != null ? Number(lbl.recall) : null;
        const precision = lbl.precision != null ? Number(lbl.precision) : null;

        if (goldTotal != null && Number.isFinite(goldTotal)) {
          agg.gold_total += goldTotal;
          agg.has_gold = true;
          if (recall != null && Number.isFinite(recall)) {
            agg.tp_from_recall += recall * goldTotal;
          }
        }
        if (predTotal != null && Number.isFinite(predTotal)) {
          agg.pred_total += predTotal;
          agg.has_pred = true;
          if (precision != null && Number.isFinite(precision)) {
            agg.tp_from_precision += precision * predTotal;
          }
        }
      });
    });

    return Object.values(byLabel)
      .map(agg => {
        const goldTotal = agg.has_gold ? agg.gold_total : null;
        const predTotal = agg.has_pred ? agg.pred_total : null;
        let tp = null;
        if (agg.has_gold && agg.has_pred) {
          tp = (agg.tp_from_recall + agg.tp_from_precision) / 2;
        } else if (agg.has_gold) {
          tp = agg.tp_from_recall;
        } else if (agg.has_pred) {
          tp = agg.tp_from_precision;
        }
        let precision = null;
        if (predTotal != null) {
          precision = predTotal > 0 && tp != null ? (tp / predTotal) : 0;
        }
        let recall = null;
        if (goldTotal != null) {
          recall = goldTotal > 0 && tp != null ? (tp / goldTotal) : 0;
        }
        return {
          label: agg.label,
          precision,
          recall,
          gold_total: goldTotal,
          pred_total: predTotal,
        };
      })
      .sort((a, b) => String(a.label).localeCompare(String(b.label)));
  }

  function perLabelRowsByLabel(rows) {
    const mapping = Object.create(null);
    (rows || []).forEach(row => {
      const label = String((row && row.label) || "").trim();
      if (!label) return;
      mapping[label] = row;
    });
    return mapping;
  }

  function perLabelComparisonModeLabel(mode) {
    return mode === "point_value" ? "Point Value" : "Delta";
  }

  function perLabelComparisonHeaderTitle(mode, scope, metric, variant) {
    const metricLabel = metric === "recall" ? "recall" : "precision";
    const variantLabel = variant === "vanilla" ? "vanilla" : "codexfarm";
    if (mode === "point_value") {
      if (scope === "run") {
        return "Latest-run " + variantLabel + " " + metricLabel + " for this label.";
      }
      return "Rolling " + variantLabel + " " + metricLabel + " over N runs for this label.";
    }
    if (scope === "run") {
      return "Latest-run codexfarm " + metricLabel + " minus latest-run " + variantLabel + " " + metricLabel + " for this label.";
    }
    return "Latest-run codexfarm " + metricLabel + " minus rolling " + variantLabel + " " + metricLabel + " over N runs for this label.";
  }

  function perLabelComparisonCell(value, baseline) {
    const valueNum = maybeNumber(value);
    const baselineNum = maybeNumber(baseline);
    if (valueNum == null || baselineNum == null) {
      return '<td class="num" style="text-align:left">-</td>';
    }
    const rawDelta = baselineNum - valueNum;
    const delta = Math.abs(rawDelta) <= 1e-12 ? 0 : rawDelta;
    let cellClass = "num";
    if (delta > 0) {
      cellClass += " delta-better";
    } else if (delta < 0) {
      cellClass += " delta-worse";
    }
    if (normalizePerLabelComparisonMode(perLabelComparisonMode) === "point_value") {
      return '<td class="' + cellClass + '" style="text-align:left">' + fmt4(valueNum) + "</td>";
    }
    const absText = Math.abs(delta).toFixed(4);
    let signedText = "";
    if (delta < 0) {
      signedText = "-" + absText;
    } else if (delta > 0) {
      signedText = "+" + absText;
    } else {
      // Reserve sign width for 0.0000 without showing a plus symbol.
      signedText = "&nbsp;" + absText;
    }
    return '<td class="' + cellClass + '" style="text-align:left">' + signedText + "</td>";
  }

  function syncPerLabelRollingWindowUi() {
    const value = normalizePerLabelRollingWindowSize(perLabelRollingWindowSize);
    perLabelRollingWindowSize = value;
    const input = document.getElementById("per-label-rolling-window-size");
    if (input) {
      input.value = String(value);
    }
    document.querySelectorAll(".per-label-rolling-window-value").forEach(node => {
      node.textContent = String(value);
    });
  }

  function syncPerLabelComparisonModeUi() {
    const mode = normalizePerLabelComparisonMode(perLabelComparisonMode);
    perLabelComparisonMode = mode;
    const checkbox = document.getElementById("per-label-comparison-point-value");
    if (checkbox) {
      checkbox.checked = mode === "point_value";
    }
    const modeLabel = perLabelComparisonModeLabel(mode);
    document.querySelectorAll(".per-label-comparison-mode-value").forEach(node => {
      node.textContent = modeLabel;
    });
    document.querySelectorAll(".per-label-comparison-header").forEach(node => {
      const scope = String(node.getAttribute("data-per-label-comparison-scope") || "").trim().toLowerCase();
      const metric = String(node.getAttribute("data-per-label-comparison-metric") || "").trim().toLowerCase();
      const variant = String(node.getAttribute("data-per-label-comparison-variant") || "").trim().toLowerCase();
      if (!scope || !metric || !variant) return;
      node.title = perLabelComparisonHeaderTitle(mode, scope, metric, variant);
    });
  }

  function setupPerLabelControls() {
    syncPerLabelRollingWindowUi();
    syncPerLabelComparisonModeUi();
    const input = document.getElementById("per-label-rolling-window-size");
    if (input && input.dataset.bound !== "1") {
      input.addEventListener("change", () => {
        const nextValue = normalizePerLabelRollingWindowSize(input.value);
        if (nextValue === perLabelRollingWindowSize) {
          syncPerLabelRollingWindowUi();
          return;
        }
        perLabelRollingWindowSize = nextValue;
        syncPerLabelRollingWindowUi();
        persistDashboardUiState();
        renderPerLabel();
      });
      input.dataset.bound = "1";
    }
    const checkbox = document.getElementById("per-label-comparison-point-value");
    if (checkbox && checkbox.dataset.bound !== "1") {
      checkbox.addEventListener("change", () => {
        const nextMode = checkbox.checked ? "point_value" : "delta";
        if (nextMode === perLabelComparisonMode) {
          syncPerLabelComparisonModeUi();
          return;
        }
        perLabelComparisonMode = nextMode;
        syncPerLabelComparisonModeUi();
        persistDashboardUiState();
        renderPerLabel();
      });
      checkbox.dataset.bound = "1";
    }
  }

  function rollingPerLabelByVariant(records, variant, windowSize) {
    const byRunTimestamp = Object.create(null);
    (records || []).forEach(record => {
      if (!record) return;
      if (benchmarkVariantForRecord(record) !== variant) return;
      const ts = String(record.run_timestamp || "").trim();
      if (!ts) return;
      if (!Array.isArray(record.per_label) || !record.per_label.length) return;
      if (!byRunTimestamp[ts]) byRunTimestamp[ts] = [];
      byRunTimestamp[ts].push(record);
    });

    const recentRunTimestamps = Object.keys(byRunTimestamp)
      .sort(compareRunTimestampDesc)
      .slice(0, windowSize);
    const valuesByLabel = Object.create(null);
    recentRunTimestamps.forEach(ts => {
      const runRows = aggregatePerLabelRows(byRunTimestamp[ts]);
      runRows.forEach(row => {
        const label = row.label;
        if (!valuesByLabel[label]) {
          valuesByLabel[label] = {
            precision_values: [],
            recall_values: [],
          };
        }
        if (row.precision != null && Number.isFinite(row.precision)) {
          valuesByLabel[label].precision_values.push(Number(row.precision));
        }
        if (row.recall != null && Number.isFinite(row.recall)) {
          valuesByLabel[label].recall_values.push(Number(row.recall));
        }
      });
    });

    const out = Object.create(null);
    Object.keys(valuesByLabel).forEach(label => {
      const entry = valuesByLabel[label];
      out[label] = {
        precision: entry.precision_values.length ? mean(entry.precision_values) : null,
        recall: entry.recall_values.length ? mean(entry.recall_values) : null,
      };
    });
    return out;
  }

  function latestRunGroupRecords(records, hasData) {
    const latestRecord = (records || []).find(record => record && hasData(record));
    if (!latestRecord) {
      return {
        runGroupLabel: "",
        records: [],
      };
    }
    const latestRunGroup = benchmarkRunGroupInfo(latestRecord);
    const latestRunGroupKey = String((latestRunGroup && latestRunGroup.runGroupKey) || "").trim();
    const latestRunGroupLabel = String(
      (latestRunGroup && latestRunGroup.runGroupLabel) || latestRecord.run_timestamp || ""
    ).trim();
    const latestRunRecords = (records || []).filter(record => {
      if (!record || !hasData(record)) return false;
      const recordRunGroup = benchmarkRunGroupInfo(record);
      return String((recordRunGroup && recordRunGroup.runGroupKey) || "").trim() === latestRunGroupKey;
    });
    return {
      runGroupLabel: latestRunGroupLabel,
      records: latestRunRecords,
    };
  }

  function renderPerLabel() {
    const records = filteredBenchmarks();
    const section = document.getElementById("per-label-section");
    if (!section) return;
    const title = section.querySelector("h2");
    const tbody = document.querySelector("#per-label-table tbody");
    if (!tbody) return;
    syncPerLabelRollingWindowUi();
    syncPerLabelComparisonModeUi();
    if (records.length === 0) {
      if (title) title.textContent = "Per-Label Breakdown";
      tbody.innerHTML = '<tr><td class="empty-note-cell" colspan="11">No benchmark records with per-label data.</td></tr>';
      return;
    }
    const sorted = [...records].sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    const nonSpeed = sorted.filter(r =>
      !isSpeedBenchmarkRecord(r)
    );
    const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;
    const latestAllMethodRecords = preferredRecords.filter(r =>
      isAllMethodBenchmarkRecord(r) &&
      r.per_label &&
      r.per_label.length > 0
    );
    const candidateRecords = latestAllMethodRecords.length > 0
      ? latestAllMethodRecords
      : preferredRecords.filter(r => r.per_label && r.per_label.length > 0);
    const latestRunGroup = latestRunGroupRecords(
      candidateRecords,
      record => Array.isArray(record.per_label) && record.per_label.length > 0,
    );
    const latestRunRecords = latestRunGroup.records;
    const latestRunLabel = latestRunGroup.runGroupLabel;
    if (!latestRunRecords.length) {
      if (title) title.textContent = "Per-Label Breakdown";
      tbody.innerHTML = '<tr><td class="empty-note-cell" colspan="11">No per-label metrics available in benchmark records.</td></tr>';
      return;
    }
    if (title) {
      title.textContent =
        "Per-Label Breakdown (" + (latestRunLabel || "latest") + ", " + latestRunRecords.length + " evals)";
    }
    tbody.innerHTML = "";
    const rollingWindowSize = normalizePerLabelRollingWindowSize(perLabelRollingWindowSize);
    const runCodexFarmRows = aggregatePerLabelRows(
      latestRunRecords.filter(record => benchmarkVariantForRecord(record) === "codexfarm")
    );
    const runVanillaRows = aggregatePerLabelRows(
      latestRunRecords.filter(record => benchmarkVariantForRecord(record) === "vanilla")
    );
    const latestRows = aggregatePerLabelRows(latestRunRecords);
    const runCodexFarmByLabel = perLabelRowsByLabel(runCodexFarmRows);
    const runVanillaByLabel = perLabelRowsByLabel(runVanillaRows);
    const rollingCodexFarmByLabel = rollingPerLabelByVariant(
      candidateRecords,
      "codexfarm",
      rollingWindowSize,
    );
    const rollingVanillaByLabel = rollingPerLabelByVariant(
      candidateRecords,
      "vanilla",
      rollingWindowSize,
    );

    latestRows.forEach(lbl => {
      const runCodexFarm = runCodexFarmByLabel[lbl.label] || {};
      const runVanilla = runVanillaByLabel[lbl.label] || {};
      const rollingCodexFarm = rollingCodexFarmByLabel[lbl.label] || {};
      const rollingVanilla = rollingVanillaByLabel[lbl.label] || {};
      const baselinePrecision = runCodexFarm.precision;
      const baselineRecall = runCodexFarm.recall;
      const tr = document.createElement("tr");
      tr.innerHTML =
        '<td>' + esc(lbl.label) + '</td>' +
        '<td class="num" style="text-align:left">' + (lbl.gold_total != null ? Math.round(lbl.gold_total) : "-") + '</td>' +
        '<td class="num" style="text-align:left">' + (lbl.pred_total != null ? Math.round(lbl.pred_total) : "-") + '</td>' +
        '<td class="num" style="text-align:left">' + fmt4(runCodexFarm.precision) + '</td>' +
        '<td class="num" style="text-align:left">' + fmt4(runCodexFarm.recall) + '</td>' +
        perLabelComparisonCell(runVanilla.precision, baselinePrecision) +
        perLabelComparisonCell(runVanilla.recall, baselineRecall) +
        perLabelComparisonCell(rollingCodexFarm.precision, baselinePrecision) +
        perLabelComparisonCell(rollingCodexFarm.recall, baselineRecall) +
        perLabelComparisonCell(rollingVanilla.precision, baselinePrecision) +
        perLabelComparisonCell(rollingVanilla.recall, baselineRecall);
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
    const nonSpeed = sorted.filter(r =>
      !isSpeedBenchmarkRecord(r)
    );
    const preferredRecords = nonSpeed.length > 0 ? nonSpeed : sorted;
    const hasBoundaryMetrics = function(record) {
      return (
        record.boundary_correct != null ||
        record.boundary_over != null ||
        record.boundary_under != null ||
        record.boundary_partial != null
      );
    };
    const latestAllMethodRecords = preferredRecords.filter(r =>
      isAllMethodBenchmarkRecord(r) &&
      hasBoundaryMetrics(r)
    );
    const candidateRecords = latestAllMethodRecords.length > 0
      ? latestAllMethodRecords
      : preferredRecords.filter(hasBoundaryMetrics);
    const latestRunGroup = latestRunGroupRecords(candidateRecords, hasBoundaryMetrics);
    const latestRunRecords = latestRunGroup.records;
    const latestRunLabel = latestRunGroup.runGroupLabel;
    if (!latestRunRecords.length) {
      section.innerHTML = '<h2>Boundary Classification</h2><p class="empty-note">No boundary data available in benchmark records.</p>';
      return;
    }
    section.querySelector("h2").textContent =
      "Boundary Classification (" + esc(latestRunLabel || "latest") + ", " + latestRunRecords.length + " evals)";
    const div = document.getElementById("boundary-summary");
    const boundary = {
      correct: 0,
      over: 0,
      under: 0,
      partial: 0,
      has_correct: false,
      has_over: false,
      has_under: false,
      has_partial: false,
    };
    const coverage = {
      gold_total: 0,
      gold_matched: 0,
      pred_total: 0,
      has_gold_total: false,
      has_gold_matched: false,
      has_pred_total: false,
    };
    latestRunRecords.forEach(record => {
      const correct = maybeNumber(record.boundary_correct);
      const over = maybeNumber(record.boundary_over);
      const under = maybeNumber(record.boundary_under);
      const partial = maybeNumber(record.boundary_partial);
      const goldTotal = maybeNumber(record.gold_total);
      const goldMatched = maybeNumber(record.gold_matched);
      const predTotal = maybeNumber(record.pred_total);

      if (correct != null) {
        boundary.correct += correct;
        boundary.has_correct = true;
      }
      if (over != null) {
        boundary.over += over;
        boundary.has_over = true;
      }
      if (under != null) {
        boundary.under += under;
        boundary.has_under = true;
      }
      if (partial != null) {
        boundary.partial += partial;
        boundary.has_partial = true;
      }
      if (goldTotal != null) {
        coverage.gold_total += goldTotal;
        coverage.has_gold_total = true;
      }
      if (goldMatched != null) {
        coverage.gold_matched += goldMatched;
        coverage.has_gold_matched = true;
      }
      if (predTotal != null) {
        coverage.pred_total += predTotal;
        coverage.has_pred_total = true;
      }
    });

    const valueOrNull = function(value, hasValue) {
      return hasValue ? Math.round(value) : null;
    };
    const boundaryCorrect = valueOrNull(boundary.correct, boundary.has_correct);
    const boundaryOver = valueOrNull(boundary.over, boundary.has_over);
    const boundaryUnder = valueOrNull(boundary.under, boundary.has_under);
    const boundaryPartial = valueOrNull(boundary.partial, boundary.has_partial);
    const classifiedMatchedTotal = (boundaryCorrect || 0) + (boundaryOver || 0) + (boundaryUnder || 0) + (boundaryPartial || 0);
    const goldTotal = coverage.has_gold_total ? Math.max(0, Math.round(coverage.gold_total)) : null;
    const matchedGold = coverage.has_gold_matched ? Math.max(0, Math.round(coverage.gold_matched)) : null;
    const matchedButUnclassified = (
      matchedGold != null
        ? Math.max(0, matchedGold - classifiedMatchedTotal)
        : null
    );
    const unmatchedGold = (
      goldTotal != null
        ? Math.max(
          0,
          goldTotal - (matchedGold != null ? matchedGold : classifiedMatchedTotal)
        )
        : null
    );
    const pctGold = function(v) {
      return goldTotal != null && goldTotal > 0 ? ((v || 0) / goldTotal * 100).toFixed(1) + "%" : "-";
    };

    const contextParts = [];
    if (coverage.has_gold_total && coverage.has_gold_matched && coverage.gold_total > 0) {
      const recallPct = (coverage.gold_matched / coverage.gold_total * 100).toFixed(1);
      contextParts.push(
        "Coverage: " + Math.round(coverage.gold_matched) + "/" + Math.round(coverage.gold_total) + " matched gold spans (" + recallPct + "%)."
      );
    }
    if (
      coverage.has_pred_total &&
      coverage.has_gold_matched &&
      coverage.pred_total > 0 &&
      Math.round(coverage.pred_total) !== Math.round(coverage.gold_total || -1)
    ) {
      const precisionPct = (coverage.gold_matched / coverage.pred_total * 100).toFixed(1);
      contextParts.push(
        "Matched predictions: " + Math.round(coverage.gold_matched) + "/" + Math.round(coverage.pred_total) + " (" + precisionPct + "%)."
      );
    }
    const contextHtml = contextParts.length
      ? '<p class="section-note">' + esc(contextParts.join(" ")) + '</p>'
      : "";

    div.innerHTML =
      contextHtml +
      '<table id="boundary-table"><thead><tr><th>Category</th><th>Count</th><th>% of gold</th></tr></thead><tbody>' +
      '<tr><td title="Prediction span matches gold boundaries exactly.">Correct</td><td class="num">' + (boundaryCorrect != null ? boundaryCorrect : "-") + '</td><td class="num">' + pctGold(boundaryCorrect) + '</td></tr>' +
      '<tr><td title="Prediction fully contains the gold span (too wide).">Over-segmented</td><td class="num">' + (boundaryOver != null ? boundaryOver : "-") + '</td><td class="num">' + pctGold(boundaryOver) + '</td></tr>' +
      '<tr><td title="Prediction is fully inside the gold span (too narrow).">Under-segmented</td><td class="num">' + (boundaryUnder != null ? boundaryUnder : "-") + '</td><td class="num">' + pctGold(boundaryUnder) + '</td></tr>' +
      '<tr><td title="Prediction overlaps but boundaries are misaligned.">Partial</td><td class="num">' + (boundaryPartial != null ? boundaryPartial : "-") + '</td><td class="num">' + pctGold(boundaryPartial) + '</td></tr>' +
      (
        matchedButUnclassified != null
          ? '<tr><td title="Gold spans counted as matched overall but not assigned to a boundary bucket.">Matched (boundary unclassified)</td><td class="num">' + matchedButUnclassified + '</td><td class="num">' + pctGold(matchedButUnclassified) + '</td></tr>'
          : ""
      ) +
      '<tr><td title="Gold spans not matched by prediction.">Unmatched gold spans</td><td class="num">' + (unmatchedGold != null ? unmatchedGold : "-") + '</td><td class="num">' + pctGold(unmatchedGold) + '</td></tr>' +
      '</tbody></table>';
  }

  // ---- Runtime section ----
  function renderLatestRuntime() {
    const section = document.getElementById("runtime-section");
    if (!section) return;
    const summary = document.getElementById("runtime-summary");
    if (!summary) return;

    const records = filteredBenchmarks();
    if (records.length === 0) {
      section.querySelector("h2").textContent = "Benchmark Runtime";
      summary.innerHTML = '<p class="empty-note">No benchmark records.</p>';
      return;
    }

    const latest = latestPreferredBenchmarkRecord(records);
    if (!latest) {
      section.querySelector("h2").textContent = "Benchmark Runtime";
      summary.innerHTML = '<p class="empty-note">No benchmark runtime metadata available.</p>';
      return;
    }

    const pipelineMode = runConfigValue(latest, ["llm_recipe_pipeline", "llm_pipeline"]);
    const model = aiModelForRecord(latest);
    const effort = aiEffortForRecord(latest);
    const totalTokenUse = formatTokenCountCompact(
      previousRunsDiscountedTokenTotal(
        maybeNumber(latest.tokens_input),
        maybeNumber(latest.tokens_cached_input),
        maybeNumber(latest.tokens_output),
        maybeNumber(latest.tokens_total),
      ),
    );
    const pipelineOff = pipelineMode && String(pipelineMode).toLowerCase() === "off";

    const sourceLabel = sourceLabelForRecord(latest);
    const sourceTitle = sourceTitleForRecord(latest);

    section.querySelector("h2").textContent =
      "Benchmark Runtime (" + esc(latest.run_timestamp || "latest") + ")";
    summary.innerHTML =
      '<table id="runtime-table"><tbody>' +
      '<tr><td>Model</td><td>' + esc(model || (pipelineOff ? "off" : "-")) + '</td></tr>' +
      '<tr><td>Thinking Effort</td><td>' + esc(effort || (pipelineOff ? "n/a (pipeline off)" : "-")) + '</td></tr>' +
      '<tr><td>Pipeline</td><td>' + esc(pipelineMode || "-") + '</td></tr>' +
      '<tr><td>Token use</td><td>' + esc(totalTokenUse) + '</td></tr>' +
      '<tr><td>Source</td><td title="' + esc(sourceTitle) + '">' + esc(sourceLabel || "-") + '</td></tr>' +
      '<tr><td>Importer</td><td>' + esc(importerLabelForRecord(latest)) + '</td></tr>' +
      '</tbody></table>';
  }

  // ---- Utils ----
  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function fmt4(v) { return v != null ? v.toFixed(4) : "-"; }
  function normalizePathParts(pathValue) {
    if (pathValue == null) return { prefix: "", parts: [] };
    const raw = String(pathValue).trim().replace(/\\\\/g, "/");
    if (!raw) return { prefix: "", parts: [] };
    const prefix = raw.startsWith("/") ? "/" : "";
    const parts = raw.split("/").filter(p => p && p !== ".");
    return { prefix, parts };
  }
  function isUsefulSourceToken(token) {
    const text = String(token || "").trim();
    if (!text) return false;
    const lower = text.toLowerCase();
    if (lower === "eval" || lower === "eval_output" || lower === "prediction-run") return false;
    if (lower.startsWith("config_") || lower.startsWith("repeat_")) return false;
    return true;
  }
  function sourceSlugFromArtifactPath(pathValue) {
    const info = normalizePathParts(pathValue);
    if (!info.parts.length) return null;
    const lower = info.parts.map(p => String(p).toLowerCase());

    const markerNext = ["all-method-benchmark", "single-profile-benchmark", "scenario_runs", "source_runs"];
    for (let i = 0; i < lower.length; i++) {
      if (!markerNext.includes(lower[i])) continue;
      const candidate = info.parts[i + 1];
      if (isUsefulSourceToken(candidate)) return String(candidate);
    }

    for (let i = 0; i < lower.length; i++) {
      if (!["candidate", "promoted", "challenger", "baseline", "control"].includes(lower[i])) {
        continue;
      }
      const candidate = info.parts[i + 1];
      if (isUsefulSourceToken(candidate)) return String(candidate);
    }

    for (let i = 0; i < lower.length; i++) {
      if (lower[i] !== "eval") continue;
      const candidate = info.parts[i + 1];
      if (isUsefulSourceToken(candidate)) return String(candidate);
    }
    return null;
  }
  function sourceTitleForRecord(record) {
    const sourceFile = String((record && record.source_file) || "").trim();
    if (sourceFile) return sourceFile;
    const artifactDir = String((record && record.artifact_dir) || "").trim();
    if (artifactDir) return artifactDir;
    const slug = sourceSlugFromArtifactPath(artifactDir);
    return slug || "";
  }
  function importerLabelForRecord(record) {
    const explicit = String((record && record.importer_name) || "").trim();
    if (explicit) return explicit;
    const source = String((record && record.source_file) || "");
    let suffix = "";
    if (source) {
      const name = basename(source).toLowerCase();
      const dot = name.lastIndexOf(".");
      if (dot > 0) suffix = name.slice(dot);
    }
    if (suffix === ".epub") return "epub";
    if (suffix === ".pdf") return "pdf";
    if (suffix === ".doc" || suffix === ".docx" || suffix === ".txt" || suffix === ".md" || suffix === ".rtf") return "text";
    if (suffix === ".html" || suffix === ".htm") return "web";
    const cfg = (record && record.run_config) || {};
    if (cfg.epub_extractor != null || cfg.epub_extractor_requested != null || cfg.epub_extractor_effective != null) {
      return "epub";
    }
    return "-";
  }
  function sourceLabelForRecord(record) {
    const sourceFileLabel = basename((record && record.source_file) || "");
    if (sourceFileLabel) return sourceFileLabel;
    const slug = sourceSlugFromArtifactPath(record ? record.artifact_dir : null);
    if (slug) return slug;
    const artifactTail = basename((record && record.artifact_dir) || "");
    return artifactTail || "-";
  }
  function cleanConfigValue(value) {
    if (value == null) return null;
    const text = String(value).trim();
    if (!text) return null;
    const lower = text.toLowerCase();
    if (
      lower === "none" ||
      lower === "null" ||
      lower === "n/a" ||
      lower === "<default>" ||
      lower === "default" ||
      lower === "(default)"
    ) {
      return null;
    }
    return text;
  }
  function runConfigSummaryMap(summary) {
    const mapping = Object.create(null);
    const text = String(summary || "").trim();
    if (!text) return mapping;
    text.split("|").forEach(chunk => {
      const part = String(chunk || "").trim();
      if (!part) return;
      const idx = part.indexOf("=");
      if (idx <= 0) return;
      const key = part.slice(0, idx).trim();
      const value = part.slice(idx + 1).trim();
      if (!key || !value) return;
      mapping[key] = value;
    });
    return mapping;
  }
  function runConfigValue(record, keys) {
    const cfg = (record && record.run_config) || {};
    for (let i = 0; i < keys.length; i++) {
      const key = String(keys[i] || "");
      if (!key) continue;
      if (!Object.prototype.hasOwnProperty.call(cfg, key)) continue;
      const direct = cleanConfigValue(cfg[key]);
      if (direct != null) return direct;
    }
    const summaryFields = runConfigSummaryMap(runConfigSummary(record));
    for (let i = 0; i < keys.length; i++) {
      const key = String(keys[i] || "");
      if (!key) continue;
      const fromSummary = cleanConfigValue(summaryFields[key]);
      if (fromSummary != null) return fromSummary;
    }
    return null;
  }
  function rawAiModelForRecord(record) {
    return runConfigValue(record, [
      "codex_farm_model",
      "codex_model",
      "provider_model",
      "model",
    ]);
  }
  function rawAiEffortForRecord(record) {
    return runConfigValue(record, [
      "codex_farm_reasoning_effort",
      "codex_farm_thinking_effort",
      "codex_reasoning_effort",
      "model_reasoning_effort",
      "thinking_effort",
      "reasoning_effort",
    ]);
  }
  function aiModelForRecord(record) {
    if (benchmarkVariantForRecord(record) === "vanilla") return null;
    return rawAiModelForRecord(record);
  }
  function aiEffortForRecord(record) {
    if (benchmarkVariantForRecord(record) === "vanilla") return null;
    return rawAiEffortForRecord(record);
  }
  function aiModelEffortLabelForRecord(record) {
    const model = aiModelForRecord(record);
    const effort = aiEffortForRecord(record);
    if (model && effort) return model + " (" + effort + ")";
    if (model) return model;
    if (effort) return "effort=" + effort;
    const pipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
    if (pipeline) {
      const pipelineText = String(pipeline).toLowerCase();
      if (pipelineText === "off") return "off";
      return "-";
    }
    return "-";
  }
  function aiModelLabelForRecord(record) {
    const model = aiModelForRecord(record);
    if (model) return model;
    const pipeline = runConfigValue(record, ["llm_recipe_pipeline", "llm_pipeline"]);
    if (pipeline && String(pipeline).toLowerCase() === "off") return "off";
    return "-";
  }
  function aiEffortLabelForRecord(record) {
    const effort = aiEffortForRecord(record);
    if (effort) return effort;
    return "-";
  }
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
  function extractorCells(record) {
    return (
      '<td>' + esc(epubExtractorRequested(record) || "-") + '</td>' +
      '<td>' + esc(epubExtractorEffective(record) || "-") + '</td>'
    );
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
    if (cfg.llm_recipe_pipeline != null) parts.push("llm_recipe_pipeline=" + cfg.llm_recipe_pipeline);
    if (cfg.codex_farm_model != null) parts.push("codex_farm_model=" + cfg.codex_farm_model);
    if (cfg.codex_farm_reasoning_effort != null) parts.push("codex_farm_reasoning_effort=" + cfg.codex_farm_reasoning_effort);
    if (cfg.codex_model != null) parts.push("codex_model=" + cfg.codex_model);
    if (cfg.model_reasoning_effort != null) parts.push("model_reasoning_effort=" + cfg.model_reasoning_effort);
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
