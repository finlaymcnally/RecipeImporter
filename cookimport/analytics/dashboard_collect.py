"""Collectors that scan on-disk metric surfaces and return a DashboardData.

All collectors are **read-only** – they never write into ``data/output`` or
``data/golden``.

Primary data sources
--------------------
* ``<repo>/.history/performance_history.csv`` (stage/import + benchmark trends)
* nested ``<output_root>/**/.history/performance_history.csv`` benchmark rows
  (supplemental benchmark history written by nested benchmark workflows)

Fallback
--------
* ``data/output/<timestamp>/*.excel_import_report.json`` (per-file reports)
* ``data/golden/**/eval_report.json`` (benchmark scan path for explicit opt-in/fallback)
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

from cookimport.paths import history_csv_for_output

from .benchmark_semantics import (
    ai_assistance_profile_for_record,
    benchmark_variant_for_record,
)
from .dashboard_schema import (
    BenchmarkLabelMetrics,
    BenchmarkRecord,
    DashboardData,
    DashboardSummary,
    RunCategory,
    StageRecord,
)

logger = logging.getLogger(__name__)
_TOKEN_USAGE_KEYS = (
    "tokens_input",
    "tokens_cached_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_total",
)

# Timestamp patterns used in run-folder names.
# Folders use dots in the time portion: YYYY-MM-DD_HH.MM.SS
# but some older folders may use colons: YYYY-MM-DD_HH:MM:SS
_TS_DIR_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[_](\d{2})[.:](\d{2})[.:](\d{2})(?:$|_.+)$"
)

_JOB_PARTS = ".job_parts"
_PREDICTION_RUN = "prediction-run"
_PYTEST_RUN_SEGMENT_RE = re.compile(r"^pytest-\d+$")
_BENCHMARK_ARTIFACT_EXCLUDE_TOKEN_RE = re.compile(
    r"(^|[-_])(gate|gated|smoke|test|debug|quick|probe|sample|trial|regression)([-_]|$)"
)
_TIMESTAMP_WITH_SUFFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[t_]\d{2}[.:]\d{2}[.:]\d{2}_(.+)$"
)


def _apply_benchmark_semantics(record: BenchmarkRecord) -> None:
    record.ai_assistance_profile = ai_assistance_profile_for_record(record)
    record.benchmark_variant = benchmark_variant_for_record(record)


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


def _benchmark_report_metric_value(
    report: dict[str, Any] | None,
    metric_name: str,
) -> float | None:
    if not isinstance(report, dict):
        return None
    if metric_name == "strict_accuracy":
        for key in (
            "strict_accuracy",
            "overall_line_accuracy",
            "overall_block_accuracy",
            "accuracy",
        ):
            value = _safe_float(report.get(key))
            if value is not None:
                return value
        precision = _safe_float(report.get("precision"))
        recall = _safe_float(report.get("recall"))
        f1 = _safe_float(report.get("f1"))
        if (
            precision is not None
            and recall is not None
            and f1 is not None
            and abs(precision - recall) <= 1e-9
            and abs(recall - f1) <= 1e-9
        ):
            return precision
        return None
    if metric_name == "macro_f1_excluding_other":
        explicit_macro = _safe_float(report.get("macro_f1_excluding_other"))
        if explicit_macro is not None:
            return explicit_macro
        practical_f1 = _safe_float(report.get("practical_f1"))
        if practical_f1 is not None:
            return practical_f1
        practical_precision = _safe_float(report.get("practical_precision"))
        practical_recall = _safe_float(report.get("practical_recall"))
        if (
            practical_precision is not None
            and practical_recall is not None
            and (practical_precision + practical_recall) > 0
        ):
            return (
                2 * practical_precision * practical_recall
                / (practical_precision + practical_recall)
            )
        return None
    return _safe_float(report.get(metric_name))


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _nonnegative_int(value: Any) -> int | None:
    parsed = _safe_int(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _extract_codex_token_usage_from_process_run(
    pass_payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    process_payload = (
        pass_payload.get("process_payload")
        if isinstance(pass_payload.get("process_payload"), dict)
        else None
    )
    telemetry_payload = (
        process_payload.get("telemetry")
        if isinstance(process_payload, dict)
        and isinstance(process_payload.get("telemetry"), dict)
        else None
    )
    if telemetry_payload is None and isinstance(pass_payload.get("telemetry"), dict):
        telemetry_payload = pass_payload.get("telemetry")
    telemetry_rows = (
        telemetry_payload.get("rows")
        if isinstance(telemetry_payload, dict)
        and isinstance(telemetry_payload.get("rows"), list)
        else None
    )

    totals: dict[str, int | None] = {key: None for key in _TOKEN_USAGE_KEYS}
    if isinstance(telemetry_rows, list):
        for row in telemetry_rows:
            if not isinstance(row, dict):
                continue
            for key in _TOKEN_USAGE_KEYS:
                value = _nonnegative_int(row.get(key))
                if value is None:
                    continue
                current = totals.get(key)
                totals[key] = value if current is None else current + value

    telemetry_report = None
    if isinstance(process_payload, dict) and isinstance(
        process_payload.get("telemetry_report"), dict
    ):
        telemetry_report = process_payload.get("telemetry_report")
    elif isinstance(pass_payload.get("telemetry_report"), dict):
        telemetry_report = pass_payload.get("telemetry_report")
    summary_payload = (
        telemetry_report.get("summary")
        if isinstance(telemetry_report, dict)
        and isinstance(telemetry_report.get("summary"), dict)
        else None
    )
    if isinstance(summary_payload, dict):
        summary_value_map = {
            "tokens_input": summary_payload.get("tokens_input"),
            "tokens_cached_input": summary_payload.get("tokens_cached_input"),
            "tokens_output": summary_payload.get("tokens_output"),
            "tokens_reasoning": (
                summary_payload.get("tokens_reasoning")
                if summary_payload.get("tokens_reasoning") is not None
                else summary_payload.get("tokens_reasoning_total")
            ),
            "tokens_total": summary_payload.get("tokens_total"),
        }
        for key, raw_value in summary_value_map.items():
            if totals.get(key) is not None:
                continue
            parsed_value = _nonnegative_int(raw_value)
            if parsed_value is not None:
                totals[key] = parsed_value

    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _extract_codex_token_usage_from_manifest(
    manifest: dict[str, Any] | None,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    if not isinstance(manifest, dict):
        return (None, None, None, None, None)

    llm_codex_farm = manifest.get("llm_codex_farm")
    if not isinstance(llm_codex_farm, dict):
        if isinstance(manifest.get("process_runs"), dict):
            llm_codex_farm = manifest
        else:
            return (None, None, None, None, None)

    process_runs = llm_codex_farm.get("process_runs")
    if not isinstance(process_runs, dict):
        return _extract_codex_token_usage_from_process_run(llm_codex_farm)

    totals: dict[str, int | None] = {key: None for key in _TOKEN_USAGE_KEYS}
    for pass_name in sorted(process_runs):
        pass_payload = process_runs.get(pass_name)
        if not isinstance(pass_payload, dict):
            continue
        (
            pass_tokens_input,
            pass_tokens_cached_input,
            pass_tokens_output,
            pass_tokens_reasoning,
            pass_tokens_total,
        ) = _extract_codex_token_usage_from_process_run(pass_payload)
        for key, value in (
            ("tokens_input", pass_tokens_input),
            ("tokens_cached_input", pass_tokens_cached_input),
            ("tokens_output", pass_tokens_output),
            ("tokens_reasoning", pass_tokens_reasoning),
            ("tokens_total", pass_tokens_total),
        ):
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _extract_line_role_token_usage_from_manifest(
    manifest: dict[str, Any] | None,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    if not isinstance(manifest, dict):
        return (None, None, None, None, None)
    telemetry_path = str(manifest.get("line_role_pipeline_telemetry_path") or "").strip()
    if not telemetry_path:
        return (None, None, None, None, None)
    try:
        telemetry_payload = json.loads(Path(telemetry_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return (None, None, None, None, None)
    if not isinstance(telemetry_payload, dict):
        return (None, None, None, None, None)
    summary = telemetry_payload.get("summary")
    if not isinstance(summary, dict):
        return (None, None, None, None, None)
    return (
        _nonnegative_int(summary.get("tokens_input")),
        _nonnegative_int(summary.get("tokens_cached_input")),
        _nonnegative_int(summary.get("tokens_output")),
        _nonnegative_int(summary.get("tokens_reasoning")),
        _nonnegative_int(summary.get("tokens_total")),
    )


def _sum_token_usage(
    *token_sets: tuple[int | None, int | None, int | None, int | None, int | None],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    totals: dict[str, int | None] = {key: None for key in _TOKEN_USAGE_KEYS}
    for token_values in token_sets:
        for key, value in zip(_TOKEN_USAGE_KEYS, token_values):
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


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
        "llm_recipe_pipeline",
        "codex_farm_model",
        "codex_farm_reasoning_effort",
        "codex_model",
        "codex_reasoning_effort",
        "model",
        "model_reasoning_effort",
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


def _clean_runtime_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"none", "null", "n/a"}:
        return None
    return text


def _extract_codex_runtime_from_manifest(
    manifest: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return (model, reasoning_effort) from llm_codex_farm manifest payloads."""
    llm_codex_farm = manifest.get("llm_codex_farm")
    if not isinstance(llm_codex_farm, dict):
        return (None, None)

    model_candidates: list[str] = []
    effort_candidates: list[str] = []

    def _collect(model_value: Any, effort_value: Any) -> None:
        model = _clean_runtime_text(model_value)
        effort = _clean_runtime_text(effort_value)
        if model is not None:
            model_candidates.append(model)
        if effort is not None:
            effort_candidates.append(effort)

    _collect(
        llm_codex_farm.get("codex_farm_model") or llm_codex_farm.get("codex_model"),
        llm_codex_farm.get("codex_farm_reasoning_effort")
        or llm_codex_farm.get("codex_reasoning_effort"),
    )

    process_runs = llm_codex_farm.get("process_runs")
    if isinstance(process_runs, dict):
        for pass_name in sorted(process_runs):
            run_entry = process_runs.get(pass_name)
            if not isinstance(run_entry, dict):
                continue
            process_payload = run_entry.get("process_payload")
            if not isinstance(process_payload, dict):
                continue
            _collect(
                process_payload.get("codex_model"),
                process_payload.get("codex_reasoning_effort"),
            )
            telemetry = process_payload.get("telemetry_report")
            if not isinstance(telemetry, dict):
                continue
            insights = telemetry.get("insights")
            if not isinstance(insights, dict):
                continue
            breakdown = insights.get("model_reasoning_breakdown")
            if not isinstance(breakdown, list):
                continue
            for row in breakdown:
                if not isinstance(row, dict):
                    continue
                _collect(row.get("model"), row.get("reasoning_effort"))

    model = model_candidates[0] if model_candidates else None
    effort = effort_candidates[0] if effort_candidates else None
    return (model, effort)


def _extract_codex_runtime_error_from_manifest(manifest: dict[str, Any]) -> str | None:
    llm_codex_farm = manifest.get("llm_codex_farm")
    if not isinstance(llm_codex_farm, dict):
        return None
    for key in ("fatalError", "fatal_error", "error", "last_error"):
        text = _clean_runtime_text(llm_codex_farm.get(key))
        if text is not None:
            return text
    return None


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


def _candidate_benchmark_eval_report_paths(artifact_dir_raw: Any) -> list[Path]:
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

    run_dir_text = str(artifact_dir_raw).strip() if artifact_dir_raw is not None else ""
    if not run_dir_text:
        return candidates
    run_dir = Path(run_dir_text).expanduser()
    _append(run_dir / "eval_report.json")
    if not run_dir.is_absolute():
        _append(Path.cwd() / run_dir / "eval_report.json")
    return candidates


def _parse_benchmark_per_label_json(
    raw: Any,
    *,
    warnings: list[str],
    context: str,
) -> list[BenchmarkLabelMetrics]:
    payload: Any
    if isinstance(raw, (dict, list)):
        payload = raw
    else:
        text = str(raw).strip() if raw is not None else ""
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            warnings.append(f"{context}: malformed per_label_json ({exc})")
            return []

    rows: list[BenchmarkLabelMetrics] = []
    if isinstance(payload, dict):
        iterator = sorted(payload.items())
        for label_name, metrics in iterator:
            if not isinstance(metrics, dict):
                continue
            rows.append(
                BenchmarkLabelMetrics(
                    label=str(label_name),
                    precision=_safe_float(metrics.get("precision")),
                    recall=_safe_float(metrics.get("recall")),
                    gold_total=_safe_int(metrics.get("gold_total")),
                    pred_total=_safe_int(metrics.get("pred_total")),
                )
            )
        return rows

    if not isinstance(payload, list):
        warnings.append(f"{context}: per_label_json is not a list/object")
        return []
    for item in payload:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        rows.append(
            BenchmarkLabelMetrics(
                label=label,
                precision=_safe_float(item.get("precision")),
                recall=_safe_float(item.get("recall")),
                gold_total=_safe_int(item.get("gold_total")),
                pred_total=_safe_int(item.get("pred_total")),
            )
        )
    return rows


def _load_benchmark_per_label_from_eval_report(
    artifact_dir_raw: Any,
    *,
    warnings: list[str],
    context: str,
    cache: dict[str, list[BenchmarkLabelMetrics] | None],
) -> list[BenchmarkLabelMetrics]:
    cache_key = str(artifact_dir_raw).strip() if artifact_dir_raw is not None else ""
    if not cache_key:
        return []
    if cache_key in cache:
        cached = cache[cache_key]
        return list(cached) if cached is not None else []

    for candidate in _candidate_benchmark_eval_report_paths(artifact_dir_raw):
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue

        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(
                f"{context}: failed reading eval report {candidate}: {exc}"
            )
            continue

        per_label_raw = payload.get("per_label")
        rows = _parse_benchmark_per_label_json(
            per_label_raw,
            warnings=warnings,
            context=f"{context} eval_report {candidate}",
        )
        cache[cache_key] = rows
        return list(rows)

    cache[cache_key] = None
    return []


def _safe_div(numerator: float | None, denominator: int | float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _extract_dir_timestamp_text(name: str) -> str | None:
    m = _TS_DIR_RE.match(name)
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2)}.{m.group(3)}.{m.group(4)}"


def _parse_dir_timestamp(name: str) -> datetime | None:
    normalized = _extract_dir_timestamp_text(name)
    if normalized is None:
        return None
    try:
        return datetime.strptime(normalized, "%Y-%m-%d_%H.%M.%S")
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


def _is_excluded_benchmark_artifact(path_value: str | Path | None) -> bool:
    """Return True when a benchmark artifact path should be hidden from dashboard data."""
    parts = _path_parts_lower(path_value)
    if not parts:
        return False
    normalized = "/" + "/".join(parts) + "/"
    if "/bench/" in normalized:
        return True
    if _is_pytest_temp_eval_artifact("/".join(parts)):
        return True
    for segment in parts:
        suffix_match = _TIMESTAMP_WITH_SUFFIX_RE.match(segment)
        if suffix_match is None:
            continue
        suffix = str(suffix_match.group(1) or "").strip().lower()
        if not suffix:
            continue
        if _BENCHMARK_ARTIFACT_EXCLUDE_TOKEN_RE.search(suffix):
            return True
    return False


def _resolve_eval_run_timestamp(eval_dir: Path, golden_root: Path) -> str:
    """Resolve benchmark run timestamp from eval dir or nearest timestamped parent."""
    path = eval_dir
    while True:
        normalized = _extract_dir_timestamp_text(path.name)
        if normalized is not None:
            return normalized
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
    benchmark_report_recipes_cache: dict[str, int | None] = {}
    benchmark_eval_per_label_cache: dict[str, list[BenchmarkLabelMetrics] | None] = {}
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
                        if _is_excluded_benchmark_artifact(bench_record.artifact_dir):
                            continue
                        if bench_record.recipes is None and bench_record.report_path:
                            bench_record.recipes = _load_total_recipes_from_report(
                                bench_record.report_path,
                                warnings=warnings,
                                context=f"CSV row {row_num}",
                                cache=benchmark_report_recipes_cache,
                            )
                        if not bench_record.per_label:
                            bench_record.per_label = _load_benchmark_per_label_from_eval_report(
                                bench_record.artifact_dir,
                                warnings=warnings,
                                context=f"CSV row {row_num}",
                                cache=benchmark_eval_per_label_cache,
                            )
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
                    has_explicit_epub_fields = (
                        epub_extractor_requested is not None
                        or epub_extractor_effective is not None
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
                    if not (is_epub_like or has_explicit_epub_fields):
                        epub_extractor_requested = None
                        epub_extractor_effective = None

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


def _collect_nested_benchmark_csv_rows(
    output_root: Path,
    *,
    primary_csv_path: Path,
    cutoff: datetime | None,
    warnings: list[str],
) -> list[BenchmarkRecord]:
    """Collect supplemental benchmark rows from nested history CSV files."""
    records: list[BenchmarkRecord] = []
    if not output_root.exists() or not output_root.is_dir():
        return records

    try:
        nested_csv_paths = sorted(
            path
            for path in output_root.rglob("performance_history.csv")
            if path.parent.name == ".history"
        )
    except OSError as exc:
        warnings.append(
            f"Failed to scan nested benchmark history CSVs under {output_root}: {exc}"
        )
        return records

    for nested_csv_path in nested_csv_paths:
        if not nested_csv_path.is_file():
            continue
        if nested_csv_path == primary_csv_path:
            continue
        _, nested_benchmark_records = _collect_from_csv(
            nested_csv_path,
            cutoff,
            warnings,
        )
        if not nested_benchmark_records:
            continue
        records = _merge_benchmark_records(records, nested_benchmark_records)

    return records


def _enrich_csv_benchmark_records_from_manifests(
    records: list[BenchmarkRecord],
    *,
    warnings: list[str],
) -> None:
    """Backfill benchmark CSV runtime metadata from nearby manifest files."""
    if not records:
        return

    manifest_cache: dict[Path, dict[str, Any] | None] = {}
    processed_report_recipes_cache: dict[str, int | None] = {}

    def _load_manifest(path: Path) -> dict[str, Any] | None:
        if path in manifest_cache:
            return manifest_cache[path]
        if not path.is_file():
            manifest_cache[path] = None
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Malformed manifest.json in {path.parent}: {exc}")
            manifest_cache[path] = None
            return None
        if not isinstance(payload, dict):
            manifest_cache[path] = None
            return None
        manifest_cache[path] = payload
        return payload

    for record in records:
        artifact_dir = _normalize_path(record.artifact_dir)
        if not artifact_dir:
            continue
        eval_dir = Path(artifact_dir)
        if not eval_dir.is_dir():
            continue

        config_changed = False

        manifest_candidates = (
            eval_dir / "manifest.json",
            eval_dir / "run_manifest.json",
            eval_dir / _PREDICTION_RUN / "manifest.json",
            eval_dir / _PREDICTION_RUN / "run_manifest.json",
        )
        for manifest_path in manifest_candidates:
            manifest = _load_manifest(manifest_path)
            if manifest is None:
                continue

            if record.source_file is None:
                source_file = _clean_runtime_text(manifest.get("source_file"))
                if source_file is not None:
                    record.source_file = source_file
            if record.importer_name is None:
                importer_name = _clean_runtime_text(
                    manifest.get("importer_name") or manifest.get("pipeline")
                )
                if importer_name is not None:
                    record.importer_name = importer_name
            if record.task_count is None:
                record.task_count = _safe_int(manifest.get("task_count"))
            if record.recipes is None:
                recipe_count = _safe_int(manifest.get("recipe_count"))
                if recipe_count is not None:
                    record.recipes = recipe_count

            if record.processed_report_path is None:
                processed_report_path = manifest.get("processed_report_path")
                if processed_report_path:
                    record.processed_report_path = str(processed_report_path)
            if record.recipes is None and record.processed_report_path:
                record.recipes = _load_total_recipes_from_report(
                    record.processed_report_path,
                    warnings=warnings,
                    context=f"benchmark manifest {manifest_path}",
                    cache=processed_report_recipes_cache,
                )

            manifest_run_config = manifest.get("run_config")
            if isinstance(manifest_run_config, dict):
                if not isinstance(record.run_config, dict):
                    record.run_config = dict(manifest_run_config)
                    config_changed = True
                else:
                    merged_run_config = dict(record.run_config)
                    merged = False
                    for key, value in manifest_run_config.items():
                        if key in merged_run_config and merged_run_config.get(key) not in (
                            None,
                            "",
                        ):
                            continue
                        merged_run_config[key] = value
                        merged = True
                    if merged:
                        record.run_config = merged_run_config
                        config_changed = True

            codex_model, codex_reasoning_effort = _extract_codex_runtime_from_manifest(
                manifest
            )
            codex_runtime_error = _extract_codex_runtime_error_from_manifest(manifest)
            (
                token_input,
                token_cached_input,
                token_output,
                token_reasoning,
                token_total,
            ) = _sum_token_usage(
                _extract_codex_token_usage_from_manifest(manifest),
                _extract_line_role_token_usage_from_manifest(manifest),
            )
            if (
                codex_model is not None
                or codex_reasoning_effort is not None
                or codex_runtime_error is not None
            ):
                merged_run_config: dict[str, Any]
                if isinstance(record.run_config, dict):
                    merged_run_config = dict(record.run_config)
                else:
                    merged_run_config = {}
                if (
                    codex_model is not None
                    and not _clean_runtime_text(merged_run_config.get("codex_farm_model"))
                    and not _clean_runtime_text(merged_run_config.get("codex_model"))
                ):
                    merged_run_config["codex_farm_model"] = codex_model
                    config_changed = True
                if (
                    codex_reasoning_effort is not None
                    and not _clean_runtime_text(
                        merged_run_config.get("codex_farm_reasoning_effort")
                    )
                    and not _clean_runtime_text(
                        merged_run_config.get("codex_reasoning_effort")
                    )
                    and not _clean_runtime_text(
                        merged_run_config.get("model_reasoning_effort")
                    )
                ):
                    merged_run_config["codex_farm_reasoning_effort"] = (
                        codex_reasoning_effort
                    )
                    config_changed = True
                if (
                    codex_runtime_error is not None
                    and not _clean_runtime_text(
                        merged_run_config.get("codex_farm_runtime_error")
                    )
                ):
                    merged_run_config["codex_farm_runtime_error"] = codex_runtime_error
                    config_changed = True
                record.run_config = merged_run_config
            if record.tokens_input is None and token_input is not None:
                record.tokens_input = token_input
            if record.tokens_cached_input is None and token_cached_input is not None:
                record.tokens_cached_input = token_cached_input
            if record.tokens_output is None and token_output is not None:
                record.tokens_output = token_output
            if record.tokens_reasoning is None and token_reasoning is not None:
                record.tokens_reasoning = token_reasoning
            if record.tokens_total is None and token_total is not None:
                record.tokens_total = token_total

        if isinstance(record.run_config, dict) and (
            config_changed
            or record.run_config_hash is None
            or record.run_config_summary is None
        ):
            record.run_config_hash = _stable_hash_for_run_config(record.run_config)
            record.run_config_summary = _summary_for_run_config(record.run_config)


def _benchmark_record_from_csv_row(
    row: dict[str, str],
    row_category: str,
    *,
    warnings: list[str],
    context: str,
) -> BenchmarkRecord:
    """Build a BenchmarkRecord from a CSV row with benchmark columns."""
    strict_accuracy = _safe_float(row.get("strict_accuracy"))
    if strict_accuracy is None:
        strict_accuracy = _safe_float(row.get("benchmark_overall_accuracy"))
    if strict_accuracy is None:
        strict_accuracy = _safe_float(row.get("benchmark_overall_block_accuracy"))
    if strict_accuracy is None:
        strict_accuracy = _safe_float(row.get("benchmark_overall_line_accuracy"))
    if strict_accuracy is None:
        strict_accuracy = _safe_float(row.get("benchmark_accuracy"))

    macro_f1_excluding_other = _safe_float(row.get("macro_f1_excluding_other"))
    if macro_f1_excluding_other is None:
        macro_f1_excluding_other = _safe_float(
            row.get("benchmark_macro_f1_excluding_other")
        )

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
    if strict_accuracy is None:
        strict_accuracy = _benchmark_report_metric_value(
            {
                "precision": precision,
                "recall": recall,
                "f1": f1,
            },
            "strict_accuracy",
        )
    if macro_f1_excluding_other is None:
        macro_f1_excluding_other = _benchmark_report_metric_value(
            {
                "practical_precision": practical_precision,
                "practical_recall": practical_recall,
                "practical_f1": practical_f1,
            },
            "macro_f1_excluding_other",
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
    per_label = _parse_benchmark_per_label_json(
        row.get("per_label_json"),
        warnings=warnings,
        context=context,
    )
    return BenchmarkRecord(
        run_timestamp=row.get("run_timestamp"),
        artifact_dir=normalized_run_dir,
        report_path=normalized_report_path,
        run_category=cat,
        strict_accuracy=strict_accuracy,
        macro_f1_excluding_other=macro_f1_excluding_other,
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
        tokens_input=_safe_int(row.get("tokens_input")),
        tokens_cached_input=_safe_int(row.get("tokens_cached_input")),
        tokens_output=_safe_int(row.get("tokens_output")),
        tokens_reasoning=_safe_int(row.get("tokens_reasoning")),
        tokens_total=_safe_int(row.get("tokens_total")),
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
        per_label=per_label,
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
        "strict_accuracy",
        "macro_f1_excluding_other",
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
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
        "supported_precision",
        "supported_recall",
        "supported_practical_precision",
        "supported_practical_recall",
        "supported_practical_f1",
        "granularity_mismatch_likely",
        "pred_width_p50",
        "gold_width_p50",
        "per_label",
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
            if not (is_epub_like or has_explicit_epub_fields):
                epub_extractor_requested = None
                epub_extractor_effective = None

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
        if _is_excluded_benchmark_artifact(eval_dir):
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
        strict_accuracy = _benchmark_report_metric_value(data, "strict_accuracy")
        has_explicit_strict_metric = any(
            _safe_float(data.get(key)) is not None
            for key in (
                "strict_accuracy",
                "overall_line_accuracy",
                "overall_block_accuracy",
                "accuracy",
            )
        )
        if has_explicit_strict_metric and strict_accuracy is not None:
            precision = strict_accuracy
            recall = strict_accuracy
            f1 = strict_accuracy
        else:
            precision = _safe_float(data.get("precision"))
            recall = _safe_float(data.get("recall"))
            f1 = _safe_float(data.get("f1"))
            if f1 is None and precision is not None and recall is not None and (precision + recall) > 0:
                f1 = 2 * precision * recall / (precision + recall)

        macro_f1 = _benchmark_report_metric_value(data, "macro_f1_excluding_other")
        has_explicit_macro_metric = (
            _safe_float(data.get("macro_f1_excluding_other")) is not None
        )
        if has_explicit_macro_metric and macro_f1 is not None:
            practical_precision = macro_f1
            practical_recall = macro_f1
            practical_f1 = macro_f1
        else:
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
            strict_accuracy=strict_accuracy,
            macro_f1_excluding_other=macro_f1,
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
                codex_model, codex_reasoning_effort = _extract_codex_runtime_from_manifest(
                    manifest
                )
                codex_runtime_error = _extract_codex_runtime_error_from_manifest(manifest)
                (
                    token_input,
                    token_cached_input,
                    token_output,
                    token_reasoning,
                    token_total,
                ) = _extract_codex_token_usage_from_manifest(manifest)
                if (
                    codex_model is not None
                    or codex_reasoning_effort is not None
                    or codex_runtime_error is not None
                ):
                    merged_run_config: dict[str, Any]
                    if isinstance(record.run_config, dict):
                        merged_run_config = dict(record.run_config)
                    else:
                        merged_run_config = {}
                    if (
                        codex_model is not None
                        and not _clean_runtime_text(
                            merged_run_config.get("codex_farm_model")
                        )
                        and not _clean_runtime_text(
                            merged_run_config.get("codex_model")
                        )
                    ):
                        merged_run_config["codex_farm_model"] = codex_model
                    if (
                        codex_reasoning_effort is not None
                        and not _clean_runtime_text(
                            merged_run_config.get("codex_farm_reasoning_effort")
                        )
                        and not _clean_runtime_text(
                            merged_run_config.get("codex_reasoning_effort")
                        )
                        and not _clean_runtime_text(
                            merged_run_config.get("model_reasoning_effort")
                        )
                    ):
                        merged_run_config["codex_farm_reasoning_effort"] = (
                            codex_reasoning_effort
                        )
                    if (
                        codex_runtime_error is not None
                        and not _clean_runtime_text(
                            merged_run_config.get("codex_farm_runtime_error")
                        )
                    ):
                        merged_run_config["codex_farm_runtime_error"] = (
                            codex_runtime_error
                        )
                    record.run_config = merged_run_config
                    if record.run_config_hash is None:
                        record.run_config_hash = _stable_hash_for_run_config(
                            merged_run_config
                        )
                    if record.run_config_summary is None:
                        record.run_config_summary = _summary_for_run_config(
                            merged_run_config
                        )
                if record.tokens_input is None and token_input is not None:
                    record.tokens_input = token_input
                if record.tokens_cached_input is None and token_cached_input is not None:
                    record.tokens_cached_input = token_cached_input
                if record.tokens_output is None and token_output is not None:
                    record.tokens_output = token_output
                if record.tokens_reasoning is None and token_reasoning is not None:
                    record.tokens_reasoning = token_reasoning
                if record.tokens_total is None and token_total is not None:
                    record.tokens_total = token_total
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


def _oldest_benchmark_timestamp(records: list[BenchmarkRecord]) -> datetime | None:
    oldest: datetime | None = None
    for record in records:
        parsed = _parse_timestamp(record.run_timestamp)
        if parsed is None:
            continue
        if oldest is None or parsed < oldest:
            oldest = parsed
    return oldest


def _has_older_benchmark_eval_reports(
    golden_root: Path,
    *,
    cutoff: datetime | None,
    oldest_csv_timestamp: datetime,
) -> bool:
    """Return True when eval_report paths indicate pre-CSV benchmark history."""
    if not golden_root.is_dir():
        return False
    try:
        candidates = golden_root.rglob("eval_report.json")
    except OSError:
        return False

    for report_path in candidates:
        eval_dir = report_path.parent
        if _PREDICTION_RUN in eval_dir.parts:
            continue
        if _is_excluded_benchmark_artifact(eval_dir):
            continue
        timestamp_text = _resolve_eval_run_timestamp(eval_dir, golden_root)
        parsed = _parse_timestamp(timestamp_text)
        if parsed is None:
            continue
        if cutoff is not None and parsed < cutoff:
            continue
        if parsed < oldest_csv_timestamp:
            return True
    return False


def _collect_older_benchmark_json_rows(
    golden_root: Path,
    *,
    cutoff: datetime | None,
    oldest_csv_timestamp: datetime,
    warnings: list[str],
) -> list[BenchmarkRecord]:
    records = _collect_benchmarks(golden_root, cutoff, warnings)
    older_rows: list[BenchmarkRecord] = []
    for record in records:
        parsed = _parse_timestamp(record.run_timestamp)
        if parsed is None:
            continue
        if parsed < oldest_csv_timestamp:
            older_rows.append(record)
    return older_rows


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
    scan_benchmark_reports: bool = False,
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
    scan_benchmark_reports:
        If ``True``, recursively scan benchmark ``eval_report.json`` artifacts
        in ``golden_root`` and merge them with CSV history rows.
    """
    warnings: list[str] = []
    cutoff = _compute_cutoff(since_days)

    # -- Stage + benchmark records from CSV --
    csv_path = history_csv_for_output(output_root)
    if not csv_path.exists():
        legacy_candidates = (
            output_root.expanduser().parent / ".history" / "performance_history.csv",
            output_root / ".history" / "performance_history.csv",
        )
        for legacy_csv_path in legacy_candidates:
            if legacy_csv_path == csv_path:
                continue
            if legacy_csv_path.exists():
                csv_path = legacy_csv_path
                break
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

    if csv_path.is_file():
        nested_csv_bench_records = _collect_nested_benchmark_csv_rows(
            output_root,
            primary_csv_path=csv_path,
            cutoff=cutoff,
            warnings=warnings,
        )
        if nested_csv_bench_records:
            csv_bench_records = _merge_benchmark_records(
                list(csv_bench_records),
                nested_csv_bench_records,
            )
    if csv_bench_records:
        _enrich_csv_benchmark_records_from_manifests(
            csv_bench_records,
            warnings=warnings,
        )

    supplemental_older_json_bench_records: list[BenchmarkRecord] = []
    if not scan_benchmark_reports and csv_bench_records:
        oldest_csv_timestamp = _oldest_benchmark_timestamp(csv_bench_records)
        if oldest_csv_timestamp is not None and _has_older_benchmark_eval_reports(
            golden_root,
            cutoff=cutoff,
            oldest_csv_timestamp=oldest_csv_timestamp,
        ):
            supplemental_older_json_bench_records = _collect_older_benchmark_json_rows(
                golden_root,
                cutoff=cutoff,
                oldest_csv_timestamp=oldest_csv_timestamp,
                warnings=warnings,
            )

    # Sort stage records by parsed timestamp (un-parseable sorts last)
    stage_records.sort(key=lambda r: _timestamp_sort_key(r.run_timestamp))

    # -- Benchmark records (CSV-first; optional JSON scan) --
    if scan_benchmark_reports:
        benchmark_records = _collect_benchmarks(golden_root, cutoff, warnings)
        benchmark_records = _merge_benchmark_records(benchmark_records, csv_bench_records)
    elif csv_bench_records:
        benchmark_records = _merge_benchmark_records(
            supplemental_older_json_bench_records,
            list(csv_bench_records),
        )
    else:
        benchmark_records = _collect_benchmarks(golden_root, cutoff, warnings)
    for record in benchmark_records:
        _apply_benchmark_semantics(record)
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
