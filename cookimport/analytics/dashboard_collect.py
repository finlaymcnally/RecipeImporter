"""Collectors that scan on-disk metric surfaces and return a DashboardData.

All collectors are **read-only** – they never write into ``data/output`` or
``data/golden``.

Primary data sources
--------------------
* ``data/output/.history/performance_history.csv`` (stage/import trends)
* ``data/golden/eval-vs-pipeline/*/eval_report.json`` (benchmark evals)

Fallback
--------
* ``data/output/<timestamp>/*.excel_import_report.json`` (per-file reports)
"""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .dashboard_schema import (
    BenchmarkLabelMetrics,
    BenchmarkRecord,
    DashboardData,
    DashboardSummary,
    RunCategory,
    StageRecord,
)

logger = logging.getLogger(__name__)

# Timestamp patterns used in run-folder names.
# Folders use dots in the time portion: YYYY-MM-DD_HH.MM.SS
# but some older folders may use colons: YYYY-MM-DD_HH:MM:SS
_TS_DIR_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[_](\d{2})[.:](\d{2})[.:](\d{2})$"
)

_HISTORY_CSV = ".history/performance_history.csv"
_JOB_PARTS = ".job_parts"
_PREDICTION_RUN = "prediction-run"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        v = float(value)
        return v if v == v else None  # NaN guard
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_div(numerator: float | None, denominator: int | float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _parse_dir_timestamp(name: str) -> datetime | None:
    m = _TS_DIR_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(
            f"{m.group(1)}_{m.group(2)}.{m.group(3)}.{m.group(4)}",
            "%Y-%m-%d_%H.%M.%S",
        )
    except ValueError:
        return None


def _is_recent(ts_str: str | None, cutoff: datetime | None) -> bool:
    if cutoff is None or ts_str is None:
        return True
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff
    except (ValueError, TypeError):
        # Also try parsing the folder-name format
        parsed = _parse_dir_timestamp(ts_str)
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed >= cutoff
        return True  # can't parse → include it


def _compute_cutoff(since_days: int | None) -> datetime | None:
    if since_days is None:
        return None
    return datetime.now(tz=timezone.utc) - timedelta(days=since_days)


# ---------------------------------------------------------------------------
# Stage / import collector
# ---------------------------------------------------------------------------

def _collect_stage_from_csv(
    csv_path: Path,
    cutoff: datetime | None,
    warnings: list[str],
) -> list[StageRecord]:
    records: list[StageRecord] = []
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row_num, row in enumerate(reader, start=2):
                try:
                    ts = row.get("run_timestamp")
                    if not _is_recent(ts, cutoff):
                        continue

                    run_dir = row.get("run_dir", "")
                    category = RunCategory.stage_import
                    if "labelstudio" in run_dir.lower():
                        category = RunCategory.labelstudio_import

                    recipes = _safe_int(row.get("recipes"))
                    tips = _safe_int(row.get("tips"))
                    tip_candidates = _safe_int(row.get("tip_candidates"))
                    topic_candidates = _safe_int(row.get("topic_candidates"))
                    total_seconds = _safe_float(row.get("total_seconds"))

                    total_units = _safe_int(row.get("total_units"))
                    if total_units is None and all(
                        v is not None for v in (recipes, tips, tip_candidates, topic_candidates)
                    ):
                        total_units = recipes + tips + tip_candidates + topic_candidates

                    per_recipe = _safe_float(row.get("per_recipe_seconds"))
                    if per_recipe is None:
                        per_recipe = _safe_div(total_seconds, recipes)

                    per_unit = _safe_float(row.get("per_unit_seconds"))
                    if per_unit is None:
                        per_unit = _safe_div(total_seconds, total_units)

                    records.append(StageRecord(
                        run_timestamp=ts,
                        run_dir=run_dir,
                        file_name=row.get("file_name", ""),
                        report_path=row.get("report_path"),
                        artifact_dir=run_dir,
                        importer_name=row.get("importer_name") or None,
                        run_category=category,
                        total_seconds=total_seconds,
                        parsing_seconds=_safe_float(row.get("parsing_seconds")),
                        writing_seconds=_safe_float(row.get("writing_seconds")),
                        ocr_seconds=_safe_float(row.get("ocr_seconds")),
                        recipes=recipes,
                        tips=tips,
                        tip_candidates=tip_candidates,
                        topic_candidates=topic_candidates,
                        total_units=total_units,
                        per_recipe_seconds=per_recipe,
                        per_unit_seconds=per_unit,
                        output_files=_safe_int(row.get("output_files")),
                        output_bytes=_safe_int(row.get("output_bytes")),
                    ))
                except Exception as exc:
                    warnings.append(f"CSV row {row_num}: {exc}")
    except Exception as exc:
        warnings.append(f"Failed to read {csv_path}: {exc}")
    return records


def _collect_stage_from_reports(
    output_root: Path,
    cutoff: datetime | None,
    warnings: list[str],
) -> list[StageRecord]:
    records: list[StageRecord] = []
    if not output_root.is_dir():
        return records

    for child in sorted(output_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue  # skip .history, .job_parts, etc.

        parsed_ts = _parse_dir_timestamp(child.name)
        if parsed_ts is None:
            continue  # not a run-timestamp folder

        if cutoff is not None:
            ts_utc = parsed_ts.replace(tzinfo=timezone.utc)
            if ts_utc < cutoff:
                continue

        for report_path in sorted(child.glob("*.excel_import_report.json")):
            try:
                data = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"Malformed report {report_path}: {exc}")
                continue

            timing = data.get("timing") or {}
            total_seconds = _safe_float(
                timing.get("total_seconds") or timing.get("totalSeconds")
            )
            recipes = _safe_int(data.get("totalRecipes"))
            tips = _safe_int(data.get("totalTips"))
            tip_candidates = _safe_int(data.get("totalTipCandidates"))
            topic_candidates = _safe_int(data.get("totalTopicCandidates"))

            total_units = None
            if all(v is not None for v in (recipes, tips, tip_candidates, topic_candidates)):
                total_units = recipes + tips + tip_candidates + topic_candidates

            source_file = data.get("sourceFile")
            file_name = (
                Path(str(source_file)).name
                if source_file
                else report_path.stem.replace(".excel_import_report", "")
            )

            run_dir_str = str(child)
            category = RunCategory.stage_import
            if "labelstudio" in run_dir_str.lower():
                category = RunCategory.labelstudio_import

            w_list = data.get("warnings") or []
            e_list = data.get("errors") or []

            records.append(StageRecord(
                run_timestamp=data.get("runTimestamp") or child.name,
                run_dir=run_dir_str,
                file_name=file_name,
                report_path=str(report_path),
                artifact_dir=run_dir_str,
                importer_name=data.get("importerName"),
                run_category=category,
                total_seconds=total_seconds,
                parsing_seconds=_safe_float(
                    timing.get("parsing_seconds") or timing.get("parsingSeconds")
                ),
                writing_seconds=_safe_float(
                    timing.get("writing_seconds") or timing.get("writingSeconds")
                ),
                ocr_seconds=_safe_float(
                    timing.get("ocr_seconds") or timing.get("ocrSeconds")
                ),
                recipes=recipes,
                tips=tips,
                tip_candidates=tip_candidates,
                topic_candidates=topic_candidates,
                total_units=total_units,
                per_recipe_seconds=_safe_div(total_seconds, recipes),
                per_unit_seconds=_safe_div(total_seconds, total_units),
                output_files=_safe_int(
                    (data.get("outputStats") or {}).get("files", {}).get("total", {}).get("count")
                ),
                output_bytes=_safe_int(
                    (data.get("outputStats") or {}).get("files", {}).get("total", {}).get("bytes")
                ),
                warnings_count=len(w_list) if isinstance(w_list, list) else None,
                errors_count=len(e_list) if isinstance(e_list, list) else None,
            ))
    return records


# ---------------------------------------------------------------------------
# Benchmark collector
# ---------------------------------------------------------------------------

def _collect_benchmarks(
    golden_root: Path,
    cutoff: datetime | None,
    warnings: list[str],
) -> list[BenchmarkRecord]:
    records: list[BenchmarkRecord] = []
    if not golden_root.is_dir():
        return records

    # Scan for eval_report.json under golden_root, focusing on
    # eval-vs-pipeline but also allowing other nested locations.
    eval_reports: list[Path] = []
    for pattern in [
        "eval-vs-pipeline/*/eval_report.json",
        "*/eval_report.json",
    ]:
        eval_reports.extend(golden_root.glob(pattern))

    # Deduplicate by resolved path
    seen: set[Path] = set()
    for rp in eval_reports:
        resolved = rp.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        eval_dir = rp.parent

        # Skip prediction-run directories
        if _PREDICTION_RUN in eval_dir.parts:
            continue

        # Attempt timestamp from directory name
        dir_name = eval_dir.name
        ts_parsed = _parse_dir_timestamp(dir_name)
        ts_str = dir_name

        if cutoff is not None and ts_parsed is not None:
            ts_utc = ts_parsed.replace(tzinfo=timezone.utc)
            if ts_utc < cutoff:
                continue

        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Malformed eval report {rp}: {exc}")
            continue

        # Top-level counts/metrics
        counts = data.get("counts") or {}
        precision = _safe_float(data.get("precision"))
        recall = _safe_float(data.get("recall"))
        f1 = None
        if precision is not None and recall is not None and (precision + recall) > 0:
            f1 = 2 * precision * recall / (precision + recall)

        # Supported-labels relaxed metrics (from app_aligned)
        app_aligned = data.get("app_aligned") or {}
        supported_relaxed = app_aligned.get("supported_labels_relaxed") or {}
        supported_precision = _safe_float(supported_relaxed.get("precision"))
        supported_recall = _safe_float(supported_relaxed.get("recall"))

        # Per-label breakdown
        per_label_raw = data.get("per_label") or {}
        per_label: list[BenchmarkLabelMetrics] = []
        for label_name, metrics in per_label_raw.items():
            if isinstance(metrics, dict):
                per_label.append(BenchmarkLabelMetrics(
                    label=label_name,
                    precision=_safe_float(metrics.get("precision")),
                    recall=_safe_float(metrics.get("recall")),
                    gold_total=_safe_int(metrics.get("gold_total")),
                    pred_total=_safe_int(metrics.get("pred_total")),
                ))

        # Boundary
        boundary = data.get("boundary") or {}

        record = BenchmarkRecord(
            run_timestamp=ts_str,
            artifact_dir=str(eval_dir),
            report_path=str(rp),
            run_category=RunCategory.benchmark_eval,
            precision=precision,
            recall=recall,
            f1=f1,
            gold_total=_safe_int(counts.get("gold_total")),
            pred_total=_safe_int(counts.get("pred_total")),
            gold_matched=_safe_int(counts.get("gold_matched")),
            supported_precision=supported_precision,
            supported_recall=supported_recall,
            per_label=per_label,
            boundary_correct=_safe_int(boundary.get("correct")),
            boundary_over=_safe_int(boundary.get("over")),
            boundary_under=_safe_int(boundary.get("under")),
            boundary_partial=_safe_int(boundary.get("partial")),
        )

        # Optional: coverage.json enrichment
        coverage_path = eval_dir / "coverage.json"
        if coverage_path.is_file():
            try:
                cov = json.loads(coverage_path.read_text(encoding="utf-8"))
                extracted = _safe_int(cov.get("extracted_chars"))
                chunked = _safe_int(cov.get("chunked_chars"))
                record.extracted_chars = extracted
                record.chunked_chars = chunked
                if extracted and chunked:
                    record.coverage_ratio = chunked / extracted
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"Malformed coverage.json in {eval_dir}: {exc}")

        # Optional: manifest.json enrichment
        manifest_path = eval_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                record.task_count = _safe_int(manifest.get("task_count"))
                record.source_file = manifest.get("source_file")
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"Malformed manifest.json in {eval_dir}: {exc}")

        records.append(record)

    # Sort by timestamp string (stable; un-parseable sorts last)
    records.sort(key=lambda r: r.run_timestamp or "zzzz")
    return records


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _build_summary(
    stage_records: list[StageRecord],
    benchmark_records: list[BenchmarkRecord],
) -> DashboardSummary:
    total_recipes = 0
    total_tips = 0
    total_runtime = 0.0
    has_runtime = False
    latest_stage_ts: str | None = None

    for r in stage_records:
        if r.recipes is not None:
            total_recipes += r.recipes
        if r.tips is not None:
            total_tips += r.tips
        if r.total_seconds is not None:
            total_runtime += r.total_seconds
            has_runtime = True
        if r.run_timestamp and (
            latest_stage_ts is None or r.run_timestamp > latest_stage_ts
        ):
            latest_stage_ts = r.run_timestamp

    latest_bench_ts: str | None = None
    for r in benchmark_records:
        if r.run_timestamp and (
            latest_bench_ts is None or r.run_timestamp > latest_bench_ts
        ):
            latest_bench_ts = r.run_timestamp

    return DashboardSummary(
        total_stage_records=len(stage_records),
        total_benchmark_records=len(benchmark_records),
        total_recipes=total_recipes,
        total_tips=total_tips,
        total_runtime_seconds=total_runtime if has_runtime else None,
        latest_stage_timestamp=latest_stage_ts,
        latest_benchmark_timestamp=latest_bench_ts,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def collect_dashboard_data(
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
    scan_reports: bool = False,
) -> DashboardData:
    """Scan metric surfaces and return a populated :class:`DashboardData`.

    Parameters
    ----------
    output_root:
        Root of staged outputs (default: ``data/output``).
    golden_root:
        Root of golden-set / benchmark data (default: ``data/golden``).
    since_days:
        If set, only include runs from the last *n* days.
    scan_reports:
        If ``True``, also scan individual ``*.excel_import_report.json``
        files even when the performance history CSV is available.
    """
    warnings: list[str] = []
    cutoff = _compute_cutoff(since_days)

    # -- Stage records --
    csv_path = output_root / _HISTORY_CSV
    stage_records: list[StageRecord] = []

    if csv_path.is_file() and not scan_reports:
        stage_records = _collect_stage_from_csv(csv_path, cutoff, warnings)
    else:
        if scan_reports and csv_path.is_file():
            # User wants both: CSV first, then fill in from reports
            stage_records = _collect_stage_from_csv(csv_path, cutoff, warnings)
        # Fallback / supplement from individual report JSONs
        report_records = _collect_stage_from_reports(output_root, cutoff, warnings)
        # Deduplicate by (run_timestamp, file_name)
        seen = {(r.run_timestamp, r.file_name) for r in stage_records}
        for r in report_records:
            if (r.run_timestamp, r.file_name) not in seen:
                stage_records.append(r)
                seen.add((r.run_timestamp, r.file_name))

    # Sort stage records by timestamp
    stage_records.sort(key=lambda r: r.run_timestamp or "zzzz")

    # -- Benchmark records --
    benchmark_records = _collect_benchmarks(golden_root, cutoff, warnings)

    # -- Summary --
    summary = _build_summary(stage_records, benchmark_records)

    return DashboardData(
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        output_root=str(output_root),
        golden_root=str(golden_root),
        stage_records=stage_records,
        benchmark_records=benchmark_records,
        summary=summary,
        collector_warnings=warnings,
    )
