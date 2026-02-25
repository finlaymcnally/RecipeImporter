"""Collectors that scan on-disk metric surfaces and return a DashboardData.

All collectors are **read-only** – they never write into ``data/output`` or
``data/golden``.

Primary data sources
--------------------
* ``data/.history/performance_history.csv`` (stage/import trends)
* ``data/golden/benchmark-vs-golden/*/eval_report.json`` (benchmark evals)

Fallback
--------
* ``data/output/<timestamp>/*.excel_import_report.json`` (per-file reports)
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cookimport.parsing.epub_auto_select import selected_auto_score
from cookimport.paths import history_csv_for_output

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

_JOB_PARTS = ".job_parts"
_PREDICTION_RUN = "prediction-run"
_PYTEST_RUN_SEGMENT_RE = re.compile(r"^pytest-\d+$")


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


def _safe_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _stable_hash_for_run_config(run_config: dict[str, Any]) -> str:
    canonical = json.dumps(
        run_config,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _summary_for_run_config(run_config: dict[str, Any]) -> str:
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
        value = run_config.get(key)
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " | ".join(parts)


def _normalize_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(Path(text).expanduser().resolve())
    except OSError:
        return text


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _parse_run_config_json(
    raw: Any,
    *,
    warnings: list[str],
    context: str,
) -> dict[str, Any] | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        warnings.append(f"{context}: malformed run_config_json ({exc})")
        return None
    if isinstance(parsed, dict):
        return parsed
    warnings.append(f"{context}: run_config_json is not a JSON object")
    return None


def _candidate_stage_report_paths(
    report_path_raw: Any,
    run_dir_raw: Any,
) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def _append(path: Path) -> None:
        try:
            key = str(path.resolve(strict=False))
        except OSError:
            key = str(path)
        if key in seen:
            return
        seen.add(key)
        candidates.append(path)

    report_text = str(report_path_raw).strip() if report_path_raw is not None else ""
    if report_text:
        report_path = Path(report_text).expanduser()
        _append(report_path)
        if not report_path.is_absolute():
            _append(Path.cwd() / report_path)

    run_dir_text = str(run_dir_raw).strip() if run_dir_raw is not None else ""
    if report_text and run_dir_text:
        report_name = Path(report_text).name
        if report_name:
            run_dir = Path(run_dir_text).expanduser()
            _append(run_dir / report_name)
            if not run_dir.is_absolute():
                _append(Path.cwd() / run_dir / report_name)

    return candidates


def _load_stage_run_config_from_report(
    report_path_raw: Any,
    run_dir_raw: Any,
    *,
    warnings: list[str],
    context: str,
    cache: dict[
        tuple[str, str],
        tuple[dict[str, Any] | None, str | None, str | None, bool],
    ],
) -> tuple[dict[str, Any] | None, str | None, str | None, bool]:
    report_key = str(report_path_raw).strip() if report_path_raw is not None else ""
    run_dir_key = str(run_dir_raw).strip() if run_dir_raw is not None else ""
    cache_key = (report_key, run_dir_key)
    if cache_key in cache:
        return cache[cache_key]

    found_report = False
    for candidate in _candidate_stage_report_paths(report_path_raw, run_dir_raw):
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue

        found_report = True
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(
                f"{context}: failed reading report runConfig from {candidate}: {exc}"
            )
            continue

        run_config = payload.get("runConfig")
        if isinstance(run_config, dict):
            run_config_hash = str(payload.get("runConfigHash") or "").strip() or None
            run_config_summary = str(payload.get("runConfigSummary") or "").strip() or None
            if run_config_hash is None:
                run_config_hash = _stable_hash_for_run_config(run_config)
            if run_config_summary is None:
                run_config_summary = _summary_for_run_config(run_config)
            cache[cache_key] = (run_config, run_config_hash, run_config_summary, True)
            return (run_config, run_config_hash, run_config_summary, True)

    cache[cache_key] = (None, None, None, found_report)
    return (None, None, None, found_report)


def _load_total_recipes_from_report(
    report_path_raw: Any,
    *,
    warnings: list[str],
    context: str,
    cache: dict[str, int | None],
) -> int | None:
    report_key = str(report_path_raw).strip() if report_path_raw is not None else ""
    if not report_key:
        return None
    if report_key in cache:
        return cache[report_key]

    for candidate in _candidate_stage_report_paths(report_path_raw, ""):
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue

        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(
                f"{context}: failed reading processed report {candidate}: {exc}"
            )
            continue

        recipes = _safe_int(payload.get("totalRecipes"))
        cache[report_key] = recipes
        return recipes

    cache[report_key] = None
    return None


def _load_stage_auto_score_from_report(
    report_path_raw: Any,
    run_dir_raw: Any,
    *,
    warnings: list[str],
    context: str,
    cache: dict[tuple[str, str], float | None],
) -> float | None:
    report_key = str(report_path_raw).strip() if report_path_raw is not None else ""
    run_dir_key = str(run_dir_raw).strip() if run_dir_raw is not None else ""
    cache_key = (report_key, run_dir_key)
    if cache_key in cache:
        return cache[cache_key]

    for candidate in _candidate_stage_report_paths(report_path_raw, run_dir_raw):
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue

        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(
                f"{context}: failed reading report auto score from {candidate}: {exc}"
            )
            continue

        auto_score = _safe_float(payload.get("epubAutoSelectedScore"))
        if auto_score is None:
            artifact = payload.get("epubAutoSelection")
            auto_score = selected_auto_score(artifact if isinstance(artifact, dict) else None)
        cache[cache_key] = auto_score
        return auto_score

    cache[cache_key] = None
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


def _parse_timestamp(ts_str: str | None) -> datetime | None:
    if ts_str is None:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        dt = _parse_dir_timestamp(ts_str)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _timestamp_sort_key(ts_str: str | None) -> tuple[int, float, str]:
    parsed = _parse_timestamp(ts_str)
    if parsed is None:
        return (1, float("inf"), ts_str or "")
    return (0, parsed.timestamp(), ts_str or "")


def _is_recent(ts_str: str | None, cutoff: datetime | None) -> bool:
    if cutoff is None or ts_str is None:
        return True
    parsed = _parse_timestamp(ts_str)
    if parsed is None:
        return True  # can't parse → include it
    return parsed >= cutoff


def _compute_cutoff(since_days: int | None) -> datetime | None:
    if since_days is None:
        return None
    return datetime.now(tz=timezone.utc) - timedelta(days=since_days)


def _path_parts_lower(path_value: str | Path | None) -> tuple[str, ...]:
    if path_value is None:
        return ()
    text = str(path_value).strip()
    if not text:
        return ()
    return tuple(
        part.lower()
        for part in text.replace("\\", "/").split("/")
        if part and part != "."
    )


def _is_pytest_temp_eval_artifact(path_value: str | Path | None) -> bool:
    """Return True when a path matches pytest temp eval/prediction artifact layout."""
    parts = _path_parts_lower(path_value)
    if len(parts) < 3:
        return False
    for idx in range(len(parts) - 2):
        if (
            _PYTEST_RUN_SEGMENT_RE.match(parts[idx])
            and parts[idx + 1].startswith("test_")
            and parts[idx + 2] in {"eval", _PREDICTION_RUN}
        ):
            return True
    return False


def _resolve_eval_run_timestamp(eval_dir: Path, golden_root: Path) -> str:
    """Resolve benchmark run timestamp from eval dir or nearest timestamped parent."""
    path = eval_dir
    while True:
        if _parse_dir_timestamp(path.name) is not None:
            return path.name
        if path == golden_root or path.parent == path:
            break
        path = path.parent
    return eval_dir.name


# ---------------------------------------------------------------------------
# Stage / import collector
# ---------------------------------------------------------------------------

_BENCHMARK_CATEGORIES = {"benchmark_eval", "benchmark_prediction"}


def _collect_from_csv(
    csv_path: Path,
    cutoff: datetime | None,
    warnings: list[str],
) -> tuple[list[StageRecord], list[BenchmarkRecord]]:
    """Read the unified CSV and split rows into stage and benchmark records."""
    stage_records: list[StageRecord] = []
    bench_records: list[BenchmarkRecord] = []
    report_run_config_cache: dict[
        tuple[str, str], tuple[dict[str, Any] | None, str | None, str | None, bool]
    ] = {}
    report_auto_score_cache: dict[tuple[str, str], float | None] = {}
    benchmark_report_recipes_cache: dict[str, int | None] = {}
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row_num, row in enumerate(reader, start=2):
                try:
                    ts = row.get("run_timestamp")
                    if not _is_recent(ts, cutoff):
                        continue

                    row_category = row.get("run_category", "")
                    if row_category in _BENCHMARK_CATEGORIES:
                        bench_record = _benchmark_record_from_csv_row(
                            row,
                            row_category,
                            warnings=warnings,
                            context=f"CSV row {row_num}",
                        )
                        if bench_record.recipes is None and bench_record.report_path:
                            bench_record.recipes = _load_total_recipes_from_report(
                                bench_record.report_path,
                                warnings=warnings,
                                context=f"CSV row {row_num}",
                                cache=benchmark_report_recipes_cache,
                            )
                        if _is_pytest_temp_eval_artifact(bench_record.artifact_dir):
                            continue
                        bench_records.append(bench_record)
                        continue

                    # Stage / import row
                    run_dir = row.get("run_dir", "")
                    category = RunCategory.stage_import
                    if "labelstudio" in run_dir.lower():
                        category = RunCategory.labelstudio_import
                    importer_name = _normalize_optional_text(row.get("importer_name"))
                    file_name = row.get("file_name", "")
                    is_epub_like = (
                        (importer_name or "").lower() == "epub"
                        or str(file_name).lower().endswith(".epub")
                    )

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
                    run_config = _parse_run_config_json(
                        row.get("run_config_json"),
                        warnings=warnings,
                        context=f"CSV row {row_num}",
                    )
                    epub_extractor_requested = _normalize_optional_text(
                        row.get("epub_extractor_requested")
                    )
                    epub_extractor_effective = _normalize_optional_text(
                        row.get("epub_extractor_effective")
                    )
                    epub_auto_selected_score = _safe_float(
                        row.get("epub_auto_selected_score")
                    )
                    has_explicit_epub_fields = (
                        epub_extractor_requested is not None
                        or epub_extractor_effective is not None
                        or epub_auto_selected_score is not None
                    )
                    run_config_hash = (
                        str(row.get("run_config_hash") or "").strip() or None
                    )
                    run_config_summary = (
                        str(row.get("run_config_summary") or "").strip() or None
                    )
                    run_config_warning: str | None = None
                    if run_config is None:
                        (
                            run_config,
                            report_hash,
                            report_summary,
                            report_found,
                        ) = _load_stage_run_config_from_report(
                            row.get("report_path"),
                            run_dir,
                            warnings=warnings,
                            context=f"CSV row {row_num}",
                            cache=report_run_config_cache,
                        )
                        if run_config_hash is None:
                            run_config_hash = report_hash
                        if run_config_summary is None:
                            run_config_summary = report_summary
                        report_ref = str(row.get("report_path") or "").strip()
                        if (
                            run_config is None
                            and run_config_summary is None
                            and report_ref
                            and not report_found
                        ):
                            run_config_warning = "missing report (stale row)"
                    else:
                        if run_config_hash is None:
                            run_config_hash = _stable_hash_for_run_config(run_config)
                        if run_config_summary is None:
                            run_config_summary = _summary_for_run_config(run_config)
                    if run_config is not None and (is_epub_like or has_explicit_epub_fields):
                        if epub_extractor_requested is None:
                            epub_extractor_requested = _normalize_optional_text(
                                run_config.get("epub_extractor_requested")
                            )
                        if epub_extractor_requested is None:
                            epub_extractor_requested = _normalize_optional_text(
                                run_config.get("epub_extractor")
                            )
                        if epub_extractor_effective is None:
                            epub_extractor_effective = _normalize_optional_text(
                                run_config.get("epub_extractor_effective")
                            )
                        if epub_extractor_effective is None:
                            epub_extractor_effective = _normalize_optional_text(
                                run_config.get("epub_extractor")
                            )
                        if epub_auto_selected_score is None:
                            epub_auto_selected_score = _safe_float(
                                run_config.get("epub_auto_selected_score")
                            )
                    if epub_auto_selected_score is None and (is_epub_like or has_explicit_epub_fields):
                        epub_auto_selected_score = _load_stage_auto_score_from_report(
                            row.get("report_path"),
                            run_dir,
                            warnings=warnings,
                            context=f"CSV row {row_num}",
                            cache=report_auto_score_cache,
                        )
                    if not (is_epub_like or has_explicit_epub_fields):
                        epub_extractor_requested = None
                        epub_extractor_effective = None
                        epub_auto_selected_score = None

                    stage_records.append(StageRecord(
                        run_timestamp=ts,
                        run_dir=run_dir,
                        file_name=file_name,
                        report_path=row.get("report_path"),
                        artifact_dir=run_dir,
                        importer_name=importer_name,
                        run_config=run_config,
                        run_config_hash=run_config_hash,
                        run_config_summary=run_config_summary,
                        run_config_warning=run_config_warning,
                        epub_extractor_requested=epub_extractor_requested,
                        epub_extractor_effective=epub_extractor_effective,
                        epub_auto_selected_score=epub_auto_selected_score,
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
    return stage_records, bench_records


def _benchmark_record_from_csv_row(
    row: dict[str, str],
    row_category: str,
    *,
    warnings: list[str],
    context: str,
) -> BenchmarkRecord:
    """Build a BenchmarkRecord from a CSV row with benchmark columns."""
    precision = _safe_float(row.get("precision"))
    recall = _safe_float(row.get("recall"))
    f1 = _safe_float(row.get("f1"))
    if f1 is None and precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    practical_precision = _safe_float(row.get("practical_precision"))
    practical_recall = _safe_float(row.get("practical_recall"))
    practical_f1 = _safe_float(row.get("practical_f1"))
    if (
        practical_f1 is None
        and practical_precision is not None
        and practical_recall is not None
        and (practical_precision + practical_recall) > 0
    ):
        practical_f1 = (
            2 * practical_precision * practical_recall
            / (practical_precision + practical_recall)
        )

    cat = RunCategory.benchmark_eval
    if row_category == "benchmark_prediction":
        cat = RunCategory.benchmark_prediction

    run_dir = row.get("run_dir", "")
    normalized_run_dir = _normalize_path(run_dir) or run_dir
    normalized_report_path = _normalize_path(row.get("report_path"))
    run_config = _parse_run_config_json(
        row.get("run_config_json"),
        warnings=warnings,
        context=context,
    )
    run_config_hash = str(row.get("run_config_hash") or "").strip() or None
    run_config_summary = str(row.get("run_config_summary") or "").strip() or None
    if run_config is not None:
        if run_config_hash is None:
            run_config_hash = _stable_hash_for_run_config(run_config)
        if run_config_summary is None:
            run_config_summary = _summary_for_run_config(run_config)
    return BenchmarkRecord(
        run_timestamp=row.get("run_timestamp"),
        artifact_dir=normalized_run_dir,
        report_path=normalized_report_path,
        run_category=cat,
        precision=precision,
        recall=recall,
        f1=f1,
        practical_precision=practical_precision,
        practical_recall=practical_recall,
        practical_f1=practical_f1,
        gold_total=_safe_int(row.get("gold_total")),
        gold_recipe_headers=_safe_int(row.get("gold_recipe_headers")),
        pred_total=_safe_int(row.get("pred_total")),
        gold_matched=_safe_int(row.get("gold_matched")),
        recipes=_safe_int(row.get("recipes")),
        supported_precision=_safe_float(row.get("supported_precision")),
        supported_recall=_safe_float(row.get("supported_recall")),
        supported_practical_precision=_safe_float(
            row.get("supported_practical_precision")
        ),
        supported_practical_recall=_safe_float(
            row.get("supported_practical_recall")
        ),
        supported_practical_f1=_safe_float(row.get("supported_practical_f1")),
        granularity_mismatch_likely=_safe_bool(
            row.get("granularity_mismatch_likely")
        ),
        pred_width_p50=_safe_float(row.get("pred_width_p50")),
        gold_width_p50=_safe_float(row.get("gold_width_p50")),
        boundary_correct=_safe_int(row.get("boundary_correct")),
        boundary_over=_safe_int(row.get("boundary_over")),
        boundary_under=_safe_int(row.get("boundary_under")),
        boundary_partial=_safe_int(row.get("boundary_partial")),
        source_file=row.get("file_name") or None,
        importer_name=row.get("importer_name") or None,
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
    )


def _merge_benchmark_record_fields(
    target: BenchmarkRecord,
    incoming: BenchmarkRecord,
) -> None:
    def _assign_if_missing(field: str, value: Any) -> None:
        if value is None:
            return
        current = getattr(target, field)
        if current is None:
            setattr(target, field, value)
            return
        if isinstance(current, str) and current == "":
            setattr(target, field, value)
            return
        if isinstance(current, list) and not current:
            setattr(target, field, value)
            return
        if isinstance(current, dict) and not current:
            setattr(target, field, value)

    for field in (
        "run_timestamp",
        "report_path",
        "precision",
        "recall",
        "f1",
        "practical_precision",
        "practical_recall",
        "practical_f1",
        "gold_total",
        "gold_recipe_headers",
        "pred_total",
        "gold_matched",
        "recipes",
        "supported_precision",
        "supported_recall",
        "supported_practical_precision",
        "supported_practical_recall",
        "supported_practical_f1",
        "granularity_mismatch_likely",
        "pred_width_p50",
        "gold_width_p50",
        "boundary_correct",
        "boundary_over",
        "boundary_under",
        "boundary_partial",
        "coverage_ratio",
        "extracted_chars",
        "chunked_chars",
        "task_count",
        "source_file",
        "importer_name",
        "run_config",
        "run_config_hash",
        "run_config_summary",
        "processed_report_path",
    ):
        _assign_if_missing(field, getattr(incoming, field))


def _merge_benchmark_records(
    json_records: list[BenchmarkRecord],
    csv_records: list[BenchmarkRecord],
) -> list[BenchmarkRecord]:
    merged: list[BenchmarkRecord] = list(json_records)
    def _artifact_key(path: str | None) -> str | None:
        return _normalize_path(path)

    by_artifact_dir: dict[str, BenchmarkRecord] = {
        key: record
        for record in merged
        if (key := _artifact_key(record.artifact_dir))
    }

    for csv_record in csv_records:
        existing = (
            by_artifact_dir.get(_artifact_key(csv_record.artifact_dir))
            if _artifact_key(csv_record.artifact_dir)
            else None
        )
        if existing is None:
            merged.append(csv_record)
            key = _artifact_key(csv_record.artifact_dir)
            if key:
                by_artifact_dir[key] = csv_record
            continue
        _merge_benchmark_record_fields(existing, csv_record)

    return merged


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
            importer_name = _normalize_optional_text(data.get("importerName"))
            is_epub_like = (importer_name or "").lower() == "epub"

            w_list = data.get("warnings") or []
            e_list = data.get("errors") or []
            run_config = data.get("runConfig") if isinstance(data.get("runConfig"), dict) else None
            run_config_hash = str(data.get("runConfigHash") or "").strip() or None
            run_config_summary = str(data.get("runConfigSummary") or "").strip() or None
            if run_config is not None:
                if run_config_hash is None:
                    run_config_hash = _stable_hash_for_run_config(run_config)
                if run_config_summary is None:
                    run_config_summary = _summary_for_run_config(run_config)
            epub_extractor_requested = _normalize_optional_text(
                data.get("epubExtractorRequested")
            )
            epub_extractor_effective = _normalize_optional_text(
                data.get("epubExtractorEffective")
            )
            has_explicit_epub_fields = (
                epub_extractor_requested is not None
                or epub_extractor_effective is not None
            )
            if run_config is not None and (is_epub_like or has_explicit_epub_fields):
                if epub_extractor_requested is None:
                    epub_extractor_requested = _normalize_optional_text(
                        run_config.get("epub_extractor_requested")
                    )
                if epub_extractor_requested is None:
                    epub_extractor_requested = _normalize_optional_text(
                        run_config.get("epub_extractor")
                    )
                if epub_extractor_effective is None:
                    epub_extractor_effective = _normalize_optional_text(
                        run_config.get("epub_extractor_effective")
                    )
                if epub_extractor_effective is None:
                    epub_extractor_effective = _normalize_optional_text(
                        run_config.get("epub_extractor")
                    )
            if epub_extractor_effective is None and (is_epub_like or has_explicit_epub_fields):
                epub_extractor_effective = _normalize_optional_text(data.get("epubBackend"))
            epub_auto_selected_score = _safe_float(data.get("epubAutoSelectedScore"))
            if epub_auto_selected_score is None and (is_epub_like or has_explicit_epub_fields):
                artifact = data.get("epubAutoSelection")
                if isinstance(artifact, dict):
                    epub_auto_selected_score = selected_auto_score(artifact)
            if (
                epub_auto_selected_score is None
                and run_config is not None
                and (is_epub_like or has_explicit_epub_fields)
            ):
                epub_auto_selected_score = _safe_float(
                    run_config.get("epub_auto_selected_score")
                )
            if not (is_epub_like or has_explicit_epub_fields):
                epub_extractor_requested = None
                epub_extractor_effective = None
                epub_auto_selected_score = None

            records.append(StageRecord(
                run_timestamp=data.get("runTimestamp") or child.name,
                run_dir=run_dir_str,
                file_name=file_name,
                report_path=str(report_path),
                artifact_dir=run_dir_str,
                importer_name=importer_name,
                run_config=run_config,
                run_config_hash=run_config_hash,
                run_config_summary=run_config_summary,
                epub_extractor_requested=epub_extractor_requested,
                epub_extractor_effective=epub_extractor_effective,
                epub_auto_selected_score=epub_auto_selected_score,
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
    processed_report_recipes_cache: dict[str, int | None] = {}
    if not golden_root.is_dir():
        return records

    # Scan recursively so nested benchmark layouts (for example all-method
    # config_* eval reports) are included.
    eval_reports: list[Path] = sorted(golden_root.rglob("eval_report.json"))

    # Deduplicate by resolved path.
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
        if _is_pytest_temp_eval_artifact(eval_dir):
            continue

        # Resolve timestamp from this directory or nearest timestamped parent.
        ts_str = _resolve_eval_run_timestamp(eval_dir, golden_root)
        ts_parsed = _parse_dir_timestamp(ts_str)

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
        f1 = _safe_float(data.get("f1"))
        if f1 is None and precision is not None and recall is not None and (precision + recall) > 0:
            f1 = 2 * precision * recall / (precision + recall)
        practical_precision = _safe_float(data.get("practical_precision"))
        practical_recall = _safe_float(data.get("practical_recall"))
        practical_f1 = _safe_float(data.get("practical_f1"))
        if (
            practical_f1 is None
            and practical_precision is not None
            and practical_recall is not None
            and (practical_precision + practical_recall) > 0
        ):
            practical_f1 = (
                2 * practical_precision * practical_recall
                / (practical_precision + practical_recall)
            )

        # Supported-labels relaxed metrics (from app_aligned)
        app_aligned = data.get("app_aligned") or {}
        supported_relaxed = app_aligned.get("supported_labels_relaxed") or {}
        supported_precision = _safe_float(data.get("supported_precision"))
        if supported_precision is None:
            supported_precision = _safe_float(supported_relaxed.get("precision"))
        supported_recall = _safe_float(data.get("supported_recall"))
        if supported_recall is None:
            supported_recall = _safe_float(supported_relaxed.get("recall"))
        supported_practical_precision = _safe_float(data.get("supported_practical_precision"))
        supported_practical_recall = _safe_float(data.get("supported_practical_recall"))
        supported_practical_f1 = _safe_float(data.get("supported_practical_f1"))
        if (
            supported_practical_f1 is None
            and supported_practical_precision is not None
            and supported_practical_recall is not None
            and (supported_practical_precision + supported_practical_recall) > 0
        ):
            supported_practical_f1 = (
                2 * supported_practical_precision * supported_practical_recall
                / (supported_practical_precision + supported_practical_recall)
            )
        granularity_mismatch = data.get("granularity_mismatch") or {}
        granularity_mismatch_likely = (
            _safe_bool(granularity_mismatch.get("likely"))
            if isinstance(granularity_mismatch, dict)
            else None
        )
        span_width_stats = data.get("span_width_stats") or {}
        pred_width_p50 = _safe_float((span_width_stats.get("pred") or {}).get("p50"))
        gold_width_p50 = _safe_float((span_width_stats.get("gold") or {}).get("p50"))
        recipe_counts = data.get("recipe_counts") or {}
        gold_recipe_headers = None
        predicted_recipe_count = None
        if isinstance(recipe_counts, dict):
            gold_recipe_headers = _safe_int(recipe_counts.get("gold_recipe_headers"))
            predicted_recipe_count = _safe_int(
                recipe_counts.get("predicted_recipe_count")
            )

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
            artifact_dir=_normalize_path(eval_dir),
            report_path=_normalize_path(rp),
            run_category=RunCategory.benchmark_eval,
            precision=precision,
            recall=recall,
            f1=f1,
            practical_precision=practical_precision,
            practical_recall=practical_recall,
            practical_f1=practical_f1,
            gold_total=_safe_int(counts.get("gold_total")),
            gold_recipe_headers=gold_recipe_headers,
            pred_total=_safe_int(counts.get("pred_total")),
            gold_matched=_safe_int(counts.get("gold_matched")),
            supported_precision=supported_precision,
            supported_recall=supported_recall,
            supported_practical_precision=supported_practical_precision,
            supported_practical_recall=supported_practical_recall,
            supported_practical_f1=supported_practical_f1,
            granularity_mismatch_likely=granularity_mismatch_likely,
            pred_width_p50=pred_width_p50,
            gold_width_p50=gold_width_p50,
            per_label=per_label,
            boundary_correct=_safe_int(boundary.get("correct")),
            boundary_over=_safe_int(boundary.get("over")),
            boundary_under=_safe_int(boundary.get("under")),
            boundary_partial=_safe_int(boundary.get("partial")),
        )

        # Optional: coverage.json enrichment
        coverage_candidates = (
            eval_dir / "coverage.json",
            eval_dir / _PREDICTION_RUN / "coverage.json",
        )
        for coverage_path in coverage_candidates:
            if not coverage_path.is_file():
                continue
            try:
                cov = json.loads(coverage_path.read_text(encoding="utf-8"))
                extracted = _safe_int(cov.get("extracted_chars"))
                chunked = _safe_int(cov.get("chunked_chars"))
                record.extracted_chars = extracted
                record.chunked_chars = chunked
                if extracted and chunked:
                    record.coverage_ratio = chunked / extracted
                break
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"Malformed coverage.json in {coverage_path.parent}: {exc}")

        # Optional: manifest.json enrichment
        manifest_candidates = (
            eval_dir / "manifest.json",
            eval_dir / _PREDICTION_RUN / "manifest.json",
        )
        for manifest_path in manifest_candidates:
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                record.task_count = _safe_int(manifest.get("task_count"))
                record.source_file = manifest.get("source_file")
                record.importer_name = (
                    manifest.get("importer_name")
                    or manifest.get("pipeline")
                )
                recipe_count = _safe_int(manifest.get("recipe_count"))
                if recipe_count is not None:
                    record.recipes = recipe_count
                run_config = manifest.get("run_config")
                if isinstance(run_config, dict):
                    record.run_config = run_config
                    if record.run_config_hash is None:
                        record.run_config_hash = _stable_hash_for_run_config(run_config)
                    if record.run_config_summary is None:
                        record.run_config_summary = _summary_for_run_config(run_config)
                run_config_hash = str(manifest.get("run_config_hash") or "").strip()
                if run_config_hash:
                    record.run_config_hash = run_config_hash
                run_config_summary = str(manifest.get("run_config_summary") or "").strip()
                if run_config_summary:
                    record.run_config_summary = run_config_summary
                processed_report_path = manifest.get("processed_report_path")
                if processed_report_path:
                    record.processed_report_path = str(processed_report_path)
                    if record.recipes is None:
                        record.recipes = _load_total_recipes_from_report(
                            record.processed_report_path,
                            warnings=warnings,
                            context=f"benchmark manifest {manifest_path}",
                            cache=processed_report_recipes_cache,
                        )
                break
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"Malformed manifest.json in {manifest_path.parent}: {exc}")

        if record.recipes is None and predicted_recipe_count is not None:
            record.recipes = predicted_recipe_count

        records.append(record)

    # Sort by parsed timestamp (un-parseable sorts last)
    records.sort(key=lambda r: _timestamp_sort_key(r.run_timestamp))
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
    latest_stage_dt: datetime | None = None

    for r in stage_records:
        if r.recipes is not None:
            total_recipes += r.recipes
        if r.tips is not None:
            total_tips += r.tips
        if r.total_seconds is not None:
            total_runtime += r.total_seconds
            has_runtime = True
        if not r.run_timestamp:
            continue
        parsed = _parse_timestamp(r.run_timestamp)
        if parsed is None:
            if latest_stage_dt is None and (
                latest_stage_ts is None or r.run_timestamp > latest_stage_ts
            ):
                latest_stage_ts = r.run_timestamp
            continue
        if latest_stage_dt is None or parsed > latest_stage_dt or (
            parsed == latest_stage_dt
            and (latest_stage_ts is None or r.run_timestamp > latest_stage_ts)
        ):
            latest_stage_dt = parsed
            latest_stage_ts = r.run_timestamp

    latest_bench_ts: str | None = None
    latest_bench_dt: datetime | None = None
    for r in benchmark_records:
        if not r.run_timestamp:
            continue
        parsed = _parse_timestamp(r.run_timestamp)
        if parsed is None:
            if latest_bench_dt is None and (
                latest_bench_ts is None or r.run_timestamp > latest_bench_ts
            ):
                latest_bench_ts = r.run_timestamp
            continue
        if latest_bench_dt is None or parsed > latest_bench_dt or (
            parsed == latest_bench_dt
            and (latest_bench_ts is None or r.run_timestamp > latest_bench_ts)
        ):
            latest_bench_dt = parsed
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

    # -- Stage + benchmark records from CSV --
    csv_path = history_csv_for_output(output_root)
    if not csv_path.exists():
        legacy_csv_path = output_root / ".history" / "performance_history.csv"
        if legacy_csv_path.exists():
            csv_path = legacy_csv_path
    stage_records: list[StageRecord] = []
    csv_bench_records: list[BenchmarkRecord] = []

    if csv_path.is_file() and not scan_reports:
        stage_records, csv_bench_records = _collect_from_csv(csv_path, cutoff, warnings)
    else:
        if scan_reports and csv_path.is_file():
            # User wants both: CSV first, then fill in from reports
            stage_records, csv_bench_records = _collect_from_csv(csv_path, cutoff, warnings)
        # Fallback / supplement from individual report JSONs
        report_records = _collect_stage_from_reports(output_root, cutoff, warnings)
        # Deduplicate by (run_timestamp, file_name)
        seen = {(r.run_timestamp, r.file_name) for r in stage_records}
        for r in report_records:
            if (r.run_timestamp, r.file_name) not in seen:
                stage_records.append(r)
                seen.add((r.run_timestamp, r.file_name))

    # Sort stage records by parsed timestamp (un-parseable sorts last)
    stage_records.sort(key=lambda r: _timestamp_sort_key(r.run_timestamp))

    # -- Benchmark records from JSON + CSV --
    benchmark_records = _collect_benchmarks(golden_root, cutoff, warnings)
    benchmark_records = _merge_benchmark_records(benchmark_records, csv_bench_records)
    benchmark_records.sort(key=lambda r: _timestamp_sort_key(r.run_timestamp))

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
