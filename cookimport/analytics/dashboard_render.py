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
from pathlib import Path
import re
import shutil
from typing import Any

from .dashboard_schema import BenchmarkRecord, DashboardData

_ALL_METHOD_BENCHMARK_SEGMENT = "all-method-benchmark"
_ALL_METHOD_CONFIG_PREFIX = "config_"
_ALL_METHOD_INDEX_PAGE = "all-method-benchmark.html"
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


@dataclass
class _AllMethodRun:
    run_key: str
    run_dir_timestamp: str | None
    groups: list[_AllMethodGroup] = field(default_factory=list)
    config_aggregates: list[_AllMethodConfigAggregate] = field(default_factory=list)
    detail_page_name: str = ""


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
        "<link rel=\"stylesheet\" href=\"assets/style.css\">"
        "</head>"
        "<body>"
        "<header><h1>All Method Benchmark Runs</h1>"
        "<p><a href=\"index.html\">Dashboard home</a></p>"
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
    for group in run.groups:
        best_group = _best_record(group.records)
        book_rows.append(
            (
                "<tr>"
                f"<td>{escape(_group_source_label(group))}</td>"
                f"<td class=\"num\">{len(group.records)}</td>"
                f"<td>{escape(_config_name(best_group) if best_group else '-')}</td>"
                f"<td class=\"num\">{_fmt_float(best_group.f1 if best_group else None)}</td>"
                f"<td class=\"num\">{_fmt_float(best_group.practical_f1 if best_group else None)}</td>"
                f"<td><a href=\"{escape(group.detail_page_name)}\">Open book details</a></td>"
                "</tr>"
            )
        )

    return (
        "<!DOCTYPE html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>cookimport – All Method Benchmark Run {escape(run.run_dir_timestamp or '')}</title>"
        "<link rel=\"stylesheet\" href=\"assets/style.css\">"
        "</head>"
        "<body>"
        "<header>"
        "<h1>All Method Benchmark Run Summary</h1>"
        f"<p><a href=\"index.html\">Dashboard home</a> · <a href=\"{_ALL_METHOD_INDEX_PAGE}\">All-method runs</a></p>"
        "</header>"
        "<main>"
        "<section>"
        f"<p><strong>Run folder:</strong> {escape(run.run_dir_timestamp or '-')}</p>"
        f"<p><strong>Book jobs:</strong> {len(run.groups)}</p>"
        f"<p><strong>Configs aggregated:</strong> {len(run.config_aggregates)}</p>"
        f"<p><strong>Winner:</strong> {escape(winner_line)}</p>"
        "</section>"
        "<section>"
        "<h2>Config Performance Across Books</h2>"
        "<p class=\"section-note\">Aggregated by configuration across all per-book jobs in this run.</p>"
        "<table><thead><tr>"
        "<th>Rank</th><th>Configuration</th><th>Extractor</th><th>Parser</th><th>Skip HF</th><th>Preprocess</th><th>Books</th><th>Wins</th><th>Mean Strict Precision</th><th>Mean Strict Recall</th><th>Mean Strict F1</th><th>Mean Practical F1</th><th>Mean Recipes</th><th>Importer</th><th>Run Config</th>"
        "</tr></thead><tbody>"
        f"{''.join(aggregate_rows)}"
        "</tbody></table>"
        "</section>"
        "<section>"
        "<h2>Per-Book Drilldown</h2>"
        "<p class=\"section-note\">Open each source row for the existing per-book config breakdown page.</p>"
        "<table><thead><tr>"
        "<th>Source</th><th>Configs</th><th>Winner</th><th>Strict F1</th><th>Practical F1</th><th>Details</th>"
        "</tr></thead><tbody>"
        f"{''.join(book_rows)}"
        "</tbody></table>"
        "</section>"
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
            "Recipes",
            1,
            [float(record.recipes) for record in group.records if record.recipes is not None],
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

    chart_specs: list[tuple[str, int, list[float | None]]] = [
        (
            "Strict Precision",
            4,
            [record.precision for record in group.records],
        ),
        (
            "Strict Recall",
            4,
            [record.recall for record in group.records],
        ),
        (
            "Strict F1",
            4,
            [record.f1 for record in group.records],
        ),
        (
            "Practical F1",
            4,
            [record.practical_f1 for record in group.records],
        ),
        (
            "Recipes",
            1,
            [float(record.recipes) if record.recipes is not None else None for record in group.records],
        ),
    ]
    chart_blocks: list[str] = []
    for label, digits, raw_values in chart_specs:
        present_values = [value for value in raw_values if value is not None]
        max_value = max(present_values) if present_values else 0.0
        bar_rows: list[str] = []
        for run_index, value in enumerate(raw_values, start=1):
            width_pct = 0.0
            if value is not None and max_value > 0:
                width_pct = max(0.0, min(100.0, float(value) / float(max_value) * 100.0))
            bar_fill_class = "metric-bar-fill" if value is not None else "metric-bar-fill metric-bar-fill-missing"
            value_text = _fmt_float(float(value), digits=digits) if value is not None else "-"
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

    nav_links = ["<a href=\"index.html\">Dashboard home</a>"]
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
        "<link rel=\"stylesheet\" href=\"assets/style.css\">"
        "</head>"
        "<body>"
        "<header>"
        "<h1>All Method Benchmark Details</h1>"
        f"<p>{' · '.join(nav_links)}</p>"
        "</header>"
        "<main>"
        "<section>"
        f"<p><strong>Run folder:</strong> {escape(group.run_dir_timestamp or '-')}</p>"
        f"<p><strong>Source:</strong> {escape(source_label)}</p>"
        f"<p><strong>Total configs:</strong> {len(group.records)}</p>"
        f"<p><strong>Winner:</strong> {escape(winner_line)}</p>"
        "</section>"
        "<section>"
        "<h2>Run Summary</h2>"
        "<p class=\"section-note\">Compact stats only (no per-config labels): count, min, median, mean, max.</p>"
        "<table class=\"summary-compact\"><thead><tr>"
        "<th>Stat</th><th>N</th><th>Min</th><th>Median</th><th>Mean</th><th>Max</th>"
        "</tr></thead><tbody>"
        f"{''.join(summary_rows)}"
        "</tbody></table>"
        "</section>"
        "<section>"
        "<h2>Metric Bar Charts</h2>"
        "<p class=\"section-note\">One bar per run/configuration for each metric category.</p>"
        f"{''.join(chart_blocks)}"
        "</section>"
        "<section>"
        "<h2>Ranked Configurations</h2>"
        "<table><thead><tr>"
        "<th>Rank</th><th>Configuration</th><th>Extractor</th><th>Parser</th><th>Skip HF</th><th>Preprocess</th><th>Strict Precision</th><th>Strict Recall</th><th>Strict F1</th><th>Practical F1</th><th>Recipes</th><th>Importer</th><th>Source</th><th>Run Config</th><th>Artifact</th>"
        "</tr></thead><tbody>"
        f"{''.join(rows)}"
        "</tbody></table>"
        "</section>"
        "</main>"
        "<footer>Generated by <code>cookimport stats-dashboard</code></footer>"
        "</body>"
        "</html>"
    )


def _render_all_method_pages(out_dir: Path, data: DashboardData) -> str:
    groups = _collect_all_method_groups(data)
    runs = _collect_all_method_runs(groups)
    legacy_dir = out_dir / _ALL_METHOD_BENCHMARK_SEGMENT
    if legacy_dir.exists():
        shutil.rmtree(legacy_dir, ignore_errors=True)

    for stale_detail_page in out_dir.glob(f"{_ALL_METHOD_BENCHMARK_SEGMENT}__*.html"):
        stale_detail_page.unlink(missing_ok=True)
    for stale_run_page in out_dir.glob(f"{_ALL_METHOD_RUN_PAGE_PREFIX}*.html"):
        stale_run_page.unlink(missing_ok=True)

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
        detail_path = out_dir / group.detail_page_name
        detail_path.write_text(
            _render_all_method_detail_html(
                group,
                run_detail_page_name=run_page_by_key.get(group.run_root_dir),
            ),
            encoding="utf-8",
        )

    for run in runs:
        run_path = out_dir / run.detail_page_name
        run_path.write_text(
            _render_all_method_run_html(run),
            encoding="utf-8",
        )

    index_path = out_dir / _ALL_METHOD_INDEX_PAGE
    index_path.write_text(
        _render_all_method_index_html(runs),
        encoding="utf-8",
    )

    if not runs:
        return (
            "<section id=\"all-method-section\">"
            "<h2>All-Method Benchmark Runs</h2>"
            f"<p><a href=\"{_ALL_METHOD_INDEX_PAGE}\">Open all-method benchmark page</a> (0 runs)</p>"
            "<p class=\"empty-note\">No all-method benchmark runs found in benchmark history.</p>"
            "</section>"
        )

    return (
        "<section id=\"all-method-section\">"
        "<h2>All-Method Benchmark Runs</h2>"
        "<p class=\"section-note\">Standalone run-summary and per-book pages generated from benchmark CSV rows grouped by all-method run folder.</p>"
        f"<p><a href=\"{_ALL_METHOD_INDEX_PAGE}\">Open all-method benchmark page</a> ({len(runs)} runs)</p>"
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
  <div id="header-meta"></div>
</header>

<nav id="filters">
  <fieldset id="category-filters"><legend>Categories</legend></fieldset>
  <fieldset id="extractor-filters"><legend>EPUB Extractor</legend></fieldset>
  <fieldset id="date-filters"><legend>Date range</legend>
    <button data-days="7">7d</button>
    <button data-days="30">30d</button>
    <button data-days="90">90d</button>
    <button data-days="0" class="active">All</button>
  </fieldset>
</nav>

<main>
  <section id="throughput-section">
    <h2>Stage / Import Throughput</h2>
    <p class="section-note">Use the run/date view for overall history, then use file trend to see how one file's speed changes across runs.</p>
    <h3>Run / Date Trend (sec/recipe)</h3>
    <div id="throughput-chart" class="chart-container"></div>
    <h3>Recent Runs (Date / Run View)</h3>
    <table id="recent-runs"><thead><tr>
      <th>Timestamp</th><th>File</th><th>Importer</th><th>Total (s)</th>
      <th>Recipes</th><th>sec/recipe</th><th>EPUB Req</th><th>EPUB Eff</th><th>Auto Score</th><th>Run Config</th><th>Artifact</th>
    </tr></thead><tbody></tbody></table>
    <h3>File Trend (Selected File)</h3>
    <div class="inline-controls">
      <label for="file-trend-select">File:</label>
      <select id="file-trend-select"></select>
    </div>
    <div id="file-trend-chart" class="chart-container"></div>
    <table id="file-trend-table"><thead><tr>
      <th>Timestamp</th><th>Total (s)</th><th>sec/recipe</th><th>Recipes</th><th>Importer</th><th>EPUB Req</th><th>EPUB Eff</th><th>Auto Score</th><th>Run Config</th><th>Artifact</th>
    </tr></thead><tbody></tbody></table>
  </section>

  <section id="benchmark-section">
    <h2>Benchmark Evaluations</h2>
    <p class="section-note">Practical F1 measures content overlap (same label, any overlap). Strict F1 measures localization quality (IoU threshold).</p>
    <div id="benchmark-chart" class="chart-container"></div>
    <h3>Recent Benchmarks</h3>
    <table id="benchmark-table"><thead><tr>
      <th>Timestamp</th><th>Strict Precision</th><th>Strict Recall</th><th>Practical F1</th><th>Strict F1</th>
      <th>Gold</th><th>Matched</th><th>Recipes</th><th>Source</th><th>Importer</th><th>Run Config</th><th>Artifact</th>
    </tr></thead><tbody></tbody></table>
  </section>

  __ALL_METHOD_SECTION__

  <section id="per-label-section">
    <h2>Per-Label Breakdown (Latest Benchmark)</h2>
    <table id="per-label-table"><thead><tr>
      <th>Label</th><th>Precision</th><th>Recall</th>
      <th>Gold</th><th>Pred</th>
    </tr></thead><tbody></tbody></table>
  </section>

  <section id="boundary-section">
    <h2>Boundary Classification (Latest Benchmark)</h2>
    <div id="boundary-summary"></div>
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
  --bg: #f8f9fa;
  --card: #ffffff;
  --border: #dee2e6;
  --accent: #0d6efd;
  --accent2: #198754;
  --accent3: #dc3545;
  --text: #212529;
  --muted: #6c757d;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --mono: 'SF Mono', SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: var(--font); color: var(--text); background: var(--bg);
  margin: 0; padding: 0 1rem 2rem;
  line-height: 1.5;
}
header { padding: 1.5rem 0 0.5rem; border-bottom: 2px solid var(--border); margin-bottom: 1rem; }
header h1 { margin: 0 0 0.25rem; font-size: 1.5rem; }
#header-meta { font-size: 0.85rem; color: var(--muted); }
#header-meta span { margin-right: 1.5em; }

nav#filters { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
fieldset { border: 1px solid var(--border); border-radius: 6px; padding: 0.4rem 0.75rem; }
legend { font-size: 0.8rem; color: var(--muted); padding: 0 0.3rem; }
fieldset label { margin-right: 0.75rem; font-size: 0.85rem; cursor: pointer; }
fieldset button {
  background: var(--card); border: 1px solid var(--border); border-radius: 4px;
  padding: 0.2rem 0.6rem; margin-right: 0.3rem; cursor: pointer; font-size: 0.8rem;
}
fieldset button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

section { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 1.25rem; margin-bottom: 1.5rem; }
section h2 { margin: 0 0 1rem; font-size: 1.2rem; }
section h3 { margin: 1.25rem 0 0.5rem; font-size: 1rem; color: var(--muted); }
.section-note { margin: 0 0 0.75rem; color: var(--muted); font-size: 0.85rem; }

.chart-container { width: 100%; overflow-x: auto; min-height: 120px; }
.chart-container svg { display: block; }

table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
th { font-weight: 600; color: var(--muted); font-size: 0.8rem; text-transform: uppercase; }
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

.empty-note { color: var(--muted); font-style: italic; padding: 1rem 0; }

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

footer { text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 2rem; }
"""

_JS = """\
(function () {
  "use strict";

  let DATA = null;
  let activeCategories = new Set(["stage_import", "benchmark_eval"]);
  let activeExtractors = new Set();
  let activeDays = 0; // 0 = all
  let selectedFileTrend = "";

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
    setupFilters();
    setupExtractorFilters();
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
    renderThroughput();
    renderBenchmarks();
    renderPerLabel();
    renderBoundary();
  }

  // ---- SVG sparkline helper ----
  function svgSparkline(points, opts) {
    // points: [{x: date, y: number, label: string}]
    // opts: {width, height, color, yLabel}
    const w = opts.width || 700;
    const h = opts.height || 140;
    const pad = { top: 20, right: 20, bottom: 30, left: 55 };
    const iw = w - pad.left - pad.right;
    const ih = h - pad.top - pad.bottom;

    if (points.length === 0) return '<p class="empty-note">No data points for chart.</p>';

    const xs = points.map(p => p.x.getTime());
    const ys = points.map(p => p.y);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(0, Math.min(...ys)), yMax = Math.max(...ys) * 1.1 || 1;

    function sx(v) { return pad.left + (xMax === xMin ? iw / 2 : (v - xMin) / (xMax - xMin) * iw); }
    function sy(v) { return pad.top + ih - (yMax === yMin ? ih / 2 : (v - yMin) / (yMax - yMin) * ih); }

    let svg = '<svg width="' + w + '" height="' + h + '" xmlns="http://www.w3.org/2000/svg">';

    // Y-axis labels
    const yTicks = 4;
    for (let i = 0; i <= yTicks; i++) {
      const v = yMin + (yMax - yMin) * i / yTicks;
      const y = sy(v);
      svg += '<line x1="' + pad.left + '" y1="' + y + '" x2="' + (w - pad.right) + '" y2="' + y + '" stroke="#e9ecef" stroke-width="1"/>';
      svg += '<text x="' + (pad.left - 5) + '" y="' + (y + 4) + '" text-anchor="end" font-size="10" fill="#6c757d">' + v.toFixed(2) + '</text>';
    }

    // Y-axis label
    if (opts.yLabel) {
      svg += '<text x="12" y="' + (pad.top + ih / 2) + '" text-anchor="middle" font-size="11" fill="#6c757d" transform="rotate(-90, 12, ' + (pad.top + ih / 2) + ')">' + opts.yLabel + '</text>';
    }

    // Data line
    const linePoints = points.map(p => sx(p.x.getTime()) + "," + sy(p.y)).join(" ");
    svg += '<polyline fill="none" stroke="' + (opts.color || "#0d6efd") + '" stroke-width="2" points="' + linePoints + '"/>';

    // Data points
    points.forEach(p => {
      const cx = sx(p.x.getTime()), cy = sy(p.y);
      svg += '<circle cx="' + cx + '" cy="' + cy + '" r="3" fill="' + (opts.color || "#0d6efd") + '">';
      svg += '<title>' + p.label + '</title></circle>';
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

    // Chart: sec/recipe over time
    const chartDiv = document.getElementById("throughput-chart");
    const points = records
      .filter(r => r.per_recipe_seconds != null && r.run_timestamp)
      .map(r => ({
        x: parseTs(r.run_timestamp) || new Date(),
        y: r.per_recipe_seconds,
        label: r.file_name + ": " + r.per_recipe_seconds.toFixed(3) + " sec/recipe"
      }))
      .filter(p => p.x)
      .sort((a, b) => a.x - b.x);

    chartDiv.innerHTML = svgSparkline(points, {
      width: Math.min(900, Math.max(400, points.length * 30)),
      height: 160,
      color: "#0d6efd",
      yLabel: "sec / recipe"
    });

    // Recent runs table
    const recentBody = document.querySelector("#recent-runs tbody");
    recentBody.innerHTML = "";
    const recentRuns = [...records]
      .sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp))
      .slice(0, 20);
    recentRuns.forEach(r => {
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
      recentBody.appendChild(tr);
    });

    // File trend controls
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
    fileChart.innerHTML = svgSparkline(filePoints, {
      width: Math.min(900, Math.max(400, filePoints.length * 55)),
      height: 160,
      color: "#198754",
      yLabel: "total sec"
    });

    const fileBody = document.querySelector("#file-trend-table tbody");
    fileBody.innerHTML = "";
    [...fileRecords]
      .sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp))
      .forEach(r => {
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
      fileBody.appendChild(tr);
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

    // Chart: recall + precision over time
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

    // Build dual-line SVG
    let chartHtml = "";
    if (rPoints.length > 0) {
      chartHtml += '<div style="margin-bottom:4px"><strong style="color:#198754;font-size:0.8rem">&#9679; Recall</strong> &nbsp; <strong style="color:#0d6efd;font-size:0.8rem">&#9679; Precision</strong></div>';
      // Merge for a common scale
      const allY = [...rPoints.map(p => p.y), ...pPoints.map(p => p.y)];
      const allX = [...rPoints.map(p => p.x.getTime()), ...pPoints.map(p => p.x.getTime())];
      const w = Math.min(900, Math.max(400, Math.max(rPoints.length, pPoints.length) * 40));

      chartHtml += svgSparkline(rPoints, {width: w, height: 160, color: "#198754", yLabel: "score"});
      // Overlay precision as second line (simpler: just render both)
      // For v1, show them stacked
      chartHtml += svgSparkline(pPoints, {width: w, height: 160, color: "#0d6efd", yLabel: "precision"});
    }
    chartDiv.innerHTML = chartHtml || '<p class="empty-note">Not enough data for trend chart.</p>';

    // Table
    const tbody = document.querySelector("#benchmark-table tbody");
    tbody.innerHTML = "";
    const sorted = [...records].sort((a, b) => compareRunTimestampDesc(a.run_timestamp, b.run_timestamp));
    sorted.forEach(r => {
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
      tbody.appendChild(tr);
    });
  }

  // ---- Per-label section ----
  function renderPerLabel() {
    const records = filteredBenchmarks();
    const section = document.getElementById("per-label-section");
    if (records.length === 0) {
      section.innerHTML = '<h2>Per-Label Breakdown</h2><p class="empty-note">No benchmark records with per-label data.</p>';
      return;
    }
    // Use the most recent benchmark that has per_label data
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
    if (!s) return "";
    return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
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
    // Show last 3 path components
    const parts = p.replace(/\\\\/g, "/").split("/");
    return parts.slice(-3).join("/");
  }
})();
"""
