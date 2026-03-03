"""Benchmark artifact retention and garbage collection."""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cookimport.analytics.perf_report import _CSV_FIELDS
from cookimport.paths import history_csv_for_output

_BENCHMARK_CATEGORIES = {"benchmark_eval", "benchmark_prediction"}
_TIMESTAMP_DIR_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}\.\d{2}\.\d{2})(?:$|_.+)$"
)
_LEGACY_TIMESTAMP_DIR_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})(?:$|_.+)$"
)


@dataclass(frozen=True)
class BenchmarkGcResult:
    dry_run: bool
    keep_full_runs: int
    keep_full_days: int
    drop_speed_artifacts: bool
    total_run_roots: int
    kept_run_roots: int
    pruned_run_roots: int
    pruned_quality_run_roots: int
    pruned_speed_run_roots: int
    reclaimed_bytes: int
    history_rows_scanned: int
    history_rows_updated: int
    history_backup_path: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _BenchmarkRunRoot:
    category: str
    run_timestamp: str
    run_started: dt.datetime
    path: Path
    size_bytes: int


def run_benchmark_gc(
    *,
    golden_root: Path,
    output_root: Path,
    keep_full_runs: int,
    keep_full_days: int,
    dry_run: bool,
    drop_speed_artifacts: bool,
) -> BenchmarkGcResult:
    if keep_full_runs < 0:
        raise ValueError("keep_full_runs must be >= 0")
    if keep_full_days < 0:
        raise ValueError("keep_full_days must be >= 0")

    runs = _collect_benchmark_run_roots(golden_root)
    keep_paths = _resolve_keep_paths(
        runs,
        keep_full_runs=keep_full_runs,
        keep_full_days=keep_full_days,
        now=dt.datetime.now(),
    )

    pruned: list[_BenchmarkRunRoot] = []
    kept: list[_BenchmarkRunRoot] = []
    for run in runs:
        keep = run.path in keep_paths
        if drop_speed_artifacts and run.category == "speed":
            keep = False
        if keep:
            kept.append(run)
        else:
            pruned.append(run)

    warnings: list[str] = []
    history_rows_scanned = 0
    history_rows_updated = 0
    history_backup_path: str | None = None

    csv_path = history_csv_for_output(output_root)
    if csv_path.is_file():
        rows = _load_history_rows(csv_path)
        history_rows_scanned = len(rows)
        history_rows_updated = _hydrate_benchmark_history_rows(rows, warnings=warnings)
        if not dry_run and history_rows_updated > 0:
            history_backup = _write_backup(csv_path)
            history_backup_path = str(history_backup)
            _write_history_rows(csv_path, rows)

    reclaimed_bytes = sum(run.size_bytes for run in pruned)
    if not dry_run:
        for run in pruned:
            try:
                shutil.rmtree(run.path)
            except OSError as exc:
                warnings.append(f"Failed to remove {run.path}: {exc}")

    return BenchmarkGcResult(
        dry_run=dry_run,
        keep_full_runs=keep_full_runs,
        keep_full_days=keep_full_days,
        drop_speed_artifacts=drop_speed_artifacts,
        total_run_roots=len(runs),
        kept_run_roots=len(kept),
        pruned_run_roots=len(pruned),
        pruned_quality_run_roots=sum(1 for run in pruned if run.category == "quality"),
        pruned_speed_run_roots=sum(1 for run in pruned if run.category == "speed"),
        reclaimed_bytes=reclaimed_bytes,
        history_rows_scanned=history_rows_scanned,
        history_rows_updated=history_rows_updated,
        history_backup_path=history_backup_path,
        warnings=tuple(warnings),
    )


def _collect_benchmark_run_roots(golden_root: Path) -> list[_BenchmarkRunRoot]:
    collected: list[_BenchmarkRunRoot] = []
    for category, root in (
        ("quality", golden_root / "bench" / "quality" / "runs"),
        ("speed", golden_root / "bench" / "speed" / "runs"),
    ):
        if not root.is_dir():
            continue
        for candidate in sorted(root.iterdir()):
            if not candidate.is_dir():
                continue
            parsed = _parse_run_timestamp(candidate.name)
            if parsed is None:
                continue
            run_timestamp, run_started = parsed
            collected.append(
                _BenchmarkRunRoot(
                    category=category,
                    run_timestamp=run_timestamp,
                    run_started=run_started,
                    path=candidate,
                    size_bytes=_directory_size(candidate),
                )
            )
    collected.sort(key=lambda run: (run.run_started, run.path.name), reverse=True)
    return collected


def _resolve_keep_paths(
    runs: list[_BenchmarkRunRoot],
    *,
    keep_full_runs: int,
    keep_full_days: int,
    now: dt.datetime,
) -> set[Path]:
    keep_paths: set[Path] = set()
    if keep_full_runs > 0:
        for run in runs[:keep_full_runs]:
            keep_paths.add(run.path)

    if keep_full_days > 0:
        cutoff = now - dt.timedelta(days=keep_full_days)
        for run in runs:
            if run.run_started >= cutoff:
                keep_paths.add(run.path)
    return keep_paths


def _parse_run_timestamp(name: str) -> tuple[str, dt.datetime] | None:
    match = _TIMESTAMP_DIR_RE.match(name)
    if match is not None:
        ts = match.group("ts")
        try:
            return (ts, dt.datetime.strptime(ts, "%Y-%m-%d_%H.%M.%S"))
        except ValueError:
            return None

    legacy_match = _LEGACY_TIMESTAMP_DIR_RE.match(name)
    if legacy_match is None:
        return None
    ts = legacy_match.group("ts")
    try:
        parsed = dt.datetime.strptime(ts, "%Y-%m-%d-%H-%M-%S")
    except ValueError:
        return None
    normalized = parsed.strftime("%Y-%m-%d_%H.%M.%S")
    return (normalized, parsed)


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _load_history_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_history_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in _CSV_FIELDS})


def _write_backup(csv_path: Path) -> Path:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    backup_name = f"{csv_path.stem}.{timestamp}.gc.bak{csv_path.suffix}"
    backup_path = csv_path.with_name(backup_name)
    shutil.copy2(csv_path, backup_path)
    return backup_path


def _hydrate_benchmark_history_rows(
    rows: list[dict[str, str]],
    *,
    warnings: list[str],
) -> int:
    updates = 0
    eval_report_cache: dict[str, dict[str, Any] | None] = {}

    for row in rows:
        if str(row.get("run_category") or "") not in _BENCHMARK_CATEGORIES:
            continue

        run_dir_text = str(row.get("run_dir") or "").strip()
        if not run_dir_text:
            continue

        report_payload = _load_eval_report_for_run_dir(
            run_dir_text,
            warnings=warnings,
            cache=eval_report_cache,
        )
        if not isinstance(report_payload, dict):
            continue

        row_updated = False

        if not str(row.get("per_label_json") or "").strip():
            serialized = _serialize_per_label_json(report_payload.get("per_label"))
            if serialized:
                row["per_label_json"] = serialized
                row_updated = True

        strict_accuracy = _metric_value(report_payload, "strict_accuracy")
        if strict_accuracy is not None and not str(row.get("strict_accuracy") or "").strip():
            row["strict_accuracy"] = _render_float(strict_accuracy)
            row_updated = True

        macro_f1 = _metric_value(report_payload, "macro_f1_excluding_other")
        if (
            macro_f1 is not None
            and not str(row.get("macro_f1_excluding_other") or "").strip()
        ):
            row["macro_f1_excluding_other"] = _render_float(macro_f1)
            row_updated = True

        boundary = report_payload.get("boundary")
        if isinstance(boundary, dict):
            for boundary_key, column_name in (
                ("correct", "boundary_correct"),
                ("over", "boundary_over"),
                ("under", "boundary_under"),
                ("partial", "boundary_partial"),
            ):
                if str(row.get(column_name) or "").strip():
                    continue
                boundary_value = _coerce_int(boundary.get(boundary_key))
                if boundary_value is None:
                    continue
                row[column_name] = str(boundary_value)
                row_updated = True

        if row_updated:
            updates += 1

    return updates


def _load_eval_report_for_run_dir(
    run_dir_text: str,
    *,
    warnings: list[str],
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    cache_key = run_dir_text
    if cache_key in cache:
        return cache[cache_key]

    run_dir = Path(run_dir_text).expanduser()
    candidates = [run_dir / "eval_report.json"]
    if not run_dir.is_absolute():
        candidates.append(Path.cwd() / run_dir / "eval_report.json")

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Malformed eval report {candidate}: {exc}")
            continue
        if isinstance(payload, dict):
            cache[cache_key] = payload
            return payload
    cache[cache_key] = None
    return None


def _serialize_per_label_json(per_label_payload: Any) -> str:
    if not isinstance(per_label_payload, dict):
        return ""
    rows: list[dict[str, Any]] = []
    for label, metrics in sorted(per_label_payload.items()):
        if not isinstance(metrics, dict):
            continue
        label_name = str(label or "").strip()
        if not label_name:
            continue
        rows.append(
            {
                "label": label_name,
                "precision": _coerce_float(metrics.get("precision")),
                "recall": _coerce_float(metrics.get("recall")),
                "gold_total": _coerce_int(metrics.get("gold_total")),
                "pred_total": _coerce_int(metrics.get("pred_total")),
            }
        )
    if not rows:
        return ""
    return json.dumps(rows, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _metric_value(report: dict[str, Any], metric_name: str) -> float | None:
    if metric_name == "strict_accuracy":
        for key in (
            "strict_accuracy",
            "overall_line_accuracy",
            "overall_block_accuracy",
            "accuracy",
        ):
            value = _coerce_float(report.get(key))
            if value is not None:
                return value
        precision = _coerce_float(report.get("precision"))
        recall = _coerce_float(report.get("recall"))
        f1 = _coerce_float(report.get("f1"))
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
        explicit = _coerce_float(report.get("macro_f1_excluding_other"))
        if explicit is not None:
            return explicit
        practical_f1 = _coerce_float(report.get("practical_f1"))
        if practical_f1 is not None:
            return practical_f1
        practical_precision = _coerce_float(report.get("practical_precision"))
        practical_recall = _coerce_float(report.get("practical_recall"))
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

    return _coerce_float(report.get(metric_name))


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _render_float(value: float) -> str:
    return f"{value:.12g}"
