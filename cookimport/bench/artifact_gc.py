"""Benchmark artifact retention and garbage collection."""

from __future__ import annotations

import csv
import datetime as dt
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from cookimport.paths import history_csv_for_output

_BENCHMARK_CATEGORIES = {"benchmark_eval", "benchmark_prediction"}
_TIMESTAMP_DIR_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}\.\d{2}\.\d{2})(?:$|[-_].+)$"
)
_LEGACY_TIMESTAMP_DIR_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})(?:$|[-_].+)$"
)
_KEEP_SENTINEL_PREFIXES = (".gc_keep",)
_KEEP_SENTINEL_EXACT = (".keep", ".pinned", "KEEP", "PINNED")


@dataclass(frozen=True)
class BenchmarkGcResult:
    dry_run: bool
    keep_full_runs: int
    keep_full_days: int
    drop_speed_artifacts: bool
    include_labelstudio_benchmark: bool
    keep_labelstudio_runs: int
    wipe_output_runs: bool
    prune_benchmark_processed_outputs: bool
    total_run_roots: int
    policy_kept_run_roots: int
    pinned_kept_run_roots: int
    skipped_unconfirmed_run_roots: int
    kept_run_roots: int
    pruned_run_roots: int
    pruned_quality_run_roots: int
    pruned_speed_run_roots: int
    pruned_labelstudio_run_roots: int
    total_output_run_roots: int
    pruned_output_run_roots: int
    pruned_processed_output_roots: int
    reclaimed_bytes: int
    reclaimed_output_run_bytes: int
    reclaimed_processed_output_bytes: int
    history_rows_scanned: int
    history_rows_updated: int
    history_rows_pruned: int
    history_backup_path: str | None
    warnings: tuple[str, ...]


@dataclass
class _BenchmarkRunRoot:
    category: str
    run_timestamp: str
    run_started: dt.datetime
    path: Path
    size_bytes: int | None = None


def run_benchmark_gc(
    *,
    golden_root: Path,
    output_root: Path,
    keep_full_runs: int,
    keep_full_days: int,
    dry_run: bool,
    drop_speed_artifacts: bool,
    include_labelstudio_benchmark: bool = False,
    keep_labelstudio_runs: int = 5,
    wipe_output_runs: bool = True,
    prune_benchmark_processed_outputs: bool = False,
) -> BenchmarkGcResult:
    if keep_full_runs < 0:
        raise ValueError("keep_full_runs must be >= 0")
    if keep_full_days < 0:
        raise ValueError("keep_full_days must be >= 0")
    if keep_labelstudio_runs < 0:
        raise ValueError("keep_labelstudio_runs must be >= 0")

    benchmark_runs = _collect_benchmark_run_roots(golden_root)
    keep_paths, pinned_kept = _resolve_keep_paths(
        benchmark_runs,
        keep_full_runs=keep_full_runs,
        keep_full_days=keep_full_days,
        now=dt.datetime.now(),
    )
    labelstudio_runs: list[_BenchmarkRunRoot] = []
    labelstudio_keep_paths: set[Path] = set()
    if include_labelstudio_benchmark:
        labelstudio_runs = _collect_labelstudio_run_roots(golden_root)
        labelstudio_keep_paths, labelstudio_pinned = _resolve_keep_paths(
            labelstudio_runs,
            keep_full_runs=keep_labelstudio_runs,
            keep_full_days=0,
            now=dt.datetime.now(),
        )
        pinned_kept += labelstudio_pinned

    pruned_by_policy: list[_BenchmarkRunRoot] = []
    kept_by_policy: list[_BenchmarkRunRoot] = []
    for run in benchmark_runs:
        pinned = _has_keep_sentinel(run.path)
        keep = run.path in keep_paths or pinned
        if drop_speed_artifacts and run.category == "speed" and not pinned:
            keep = False
        if keep:
            kept_by_policy.append(run)
        else:
            pruned_by_policy.append(run)

    pruned_labelstudio_by_policy: list[_BenchmarkRunRoot] = []
    for run in labelstudio_runs:
        pinned = _has_keep_sentinel(run.path)
        keep = run.path in labelstudio_keep_paths or pinned
        if keep:
            kept_by_policy.append(run)
        else:
            pruned_labelstudio_by_policy.append(run)

    warnings: list[str] = []
    history_rows_scanned = 0
    history_rows_updated = 0
    history_rows_pruned = 0
    history_backup_path: str | None = None
    rows: list[dict[str, str]] = []
    history_rows_available = False

    csv_path = history_csv_for_output(output_root)
    if csv_path.is_file():
        rows = _load_history_rows(csv_path)
        history_rows_scanned = len(rows)
        history_rows_available = True
    else:
        if not pruned_by_policy:
            history_rows_available = False
        else:
            warnings.append(
                "History CSV not found; keeping all prune candidates because durable "
                f"benchmark retention cannot be confirmed: {csv_path}"
            )
            history_rows_available = False

    confirmed_pruned: list[_BenchmarkRunRoot] = []
    skipped_unconfirmed: list[_BenchmarkRunRoot] = []
    for run in pruned_by_policy:
        if history_rows_available and _run_root_has_durable_history(rows, run.path):
            confirmed_pruned.append(run)
            continue
        skipped_unconfirmed.append(run)
        warnings.append(
            "Skipped pruning run with unconfirmed durable history: "
            f"{run.path}"
        )

    confirmed_processed_output_roots: list[Path] = []
    if (
        prune_benchmark_processed_outputs
        and not wipe_output_runs
        and history_rows_available
        and rows
    ):
        for run in pruned_labelstudio_by_policy:
            candidate = output_root.expanduser() / run.path.name
            if not candidate.exists() or not candidate.is_dir():
                continue
            if _processed_output_root_confirmed_by_history(
                rows=rows,
                run_root=run.path,
                processed_root=candidate,
            ):
                confirmed_processed_output_roots.append(candidate)
            else:
                warnings.append(
                    "Skipped pruning processed output root without history confirmation: "
                    f"{candidate}"
                )

    reclaimed_bytes = 0
    for run in confirmed_pruned:
        if run.size_bytes is None:
            run.size_bytes = _directory_size(run.path)
        reclaimed_bytes += int(run.size_bytes or 0)
    for run in pruned_labelstudio_by_policy:
        if run.size_bytes is None:
            run.size_bytes = _directory_size(run.path)
        reclaimed_bytes += int(run.size_bytes or 0)

    output_run_roots: list[Path] = []
    if wipe_output_runs:
        output_run_roots = _collect_output_run_roots(output_root)
    reclaimed_output_run_bytes = 0
    for output_run_root in output_run_roots:
        reclaimed_output_run_bytes += _directory_size(output_run_root)

    reclaimed_processed_output_bytes = 0
    for processed_root in confirmed_processed_output_roots:
        reclaimed_processed_output_bytes += _directory_size(processed_root)

    if not dry_run:
        for run in confirmed_pruned:
            try:
                shutil.rmtree(run.path)
            except OSError as exc:
                warnings.append(f"Failed to remove {run.path}: {exc}")
        for run in pruned_labelstudio_by_policy:
            try:
                shutil.rmtree(run.path)
            except OSError as exc:
                warnings.append(f"Failed to remove {run.path}: {exc}")
        for output_run_root in output_run_roots:
            try:
                shutil.rmtree(output_run_root)
            except OSError as exc:
                warnings.append(f"Failed to remove {output_run_root}: {exc}")
        for processed_root in confirmed_processed_output_roots:
            try:
                shutil.rmtree(processed_root)
            except OSError as exc:
                warnings.append(f"Failed to remove {processed_root}: {exc}")

    return BenchmarkGcResult(
        dry_run=dry_run,
        keep_full_runs=keep_full_runs,
        keep_full_days=keep_full_days,
        drop_speed_artifacts=drop_speed_artifacts,
        include_labelstudio_benchmark=include_labelstudio_benchmark,
        keep_labelstudio_runs=keep_labelstudio_runs,
        wipe_output_runs=wipe_output_runs,
        prune_benchmark_processed_outputs=prune_benchmark_processed_outputs,
        total_run_roots=len(benchmark_runs) + len(labelstudio_runs),
        policy_kept_run_roots=len(kept_by_policy),
        pinned_kept_run_roots=pinned_kept,
        skipped_unconfirmed_run_roots=len(skipped_unconfirmed),
        kept_run_roots=len(kept_by_policy) + len(skipped_unconfirmed),
        pruned_run_roots=len(confirmed_pruned) + len(pruned_labelstudio_by_policy),
        pruned_quality_run_roots=sum(
            1 for run in confirmed_pruned if run.category == "quality"
        ),
        pruned_speed_run_roots=sum(
            1 for run in confirmed_pruned if run.category == "speed"
        ),
        pruned_labelstudio_run_roots=len(pruned_labelstudio_by_policy),
        total_output_run_roots=len(output_run_roots),
        pruned_output_run_roots=len(output_run_roots),
        pruned_processed_output_roots=len(confirmed_processed_output_roots),
        reclaimed_bytes=reclaimed_bytes,
        reclaimed_output_run_bytes=reclaimed_output_run_bytes,
        reclaimed_processed_output_bytes=reclaimed_processed_output_bytes,
        history_rows_scanned=history_rows_scanned,
        history_rows_updated=history_rows_updated,
        history_rows_pruned=history_rows_pruned,
        history_backup_path=history_backup_path,
        warnings=tuple(warnings),
    )


def _collect_benchmark_run_roots(
    golden_root: Path,
) -> list[_BenchmarkRunRoot]:
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
                )
            )

    collected.sort(key=lambda run: (run.run_started, run.path.name), reverse=True)
    return collected


def _collect_labelstudio_run_roots(golden_root: Path) -> list[_BenchmarkRunRoot]:
    collected: list[_BenchmarkRunRoot] = []
    root = golden_root / "benchmark-vs-golden"
    if not root.is_dir():
        return collected
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        parsed = _parse_run_timestamp(candidate.name)
        if parsed is None:
            continue
        run_timestamp, run_started = parsed
        collected.append(
            _BenchmarkRunRoot(
                category="labelstudio",
                run_timestamp=run_timestamp,
                run_started=run_started,
                path=candidate,
            )
        )
    collected.sort(key=lambda run: (run.run_started, run.path.name), reverse=True)
    return collected


def _collect_output_run_roots(output_root: Path) -> list[Path]:
    collected: list[Path] = []
    resolved_root = output_root.expanduser()
    if not resolved_root.is_dir():
        return collected
    for candidate in sorted(resolved_root.iterdir()):
        if not candidate.is_dir():
            continue
        if _parse_run_timestamp(candidate.name) is None:
            continue
        collected.append(candidate)
    collected.sort(
        key=lambda path: (_parse_run_timestamp(path.name) or ("", dt.datetime.min))[1],
        reverse=True,
    )
    return collected


def _resolve_keep_paths(
    runs: list[_BenchmarkRunRoot],
    *,
    keep_full_runs: int,
    keep_full_days: int,
    now: dt.datetime,
) -> tuple[set[Path], int]:
    keep_paths: set[Path] = set()
    pinned_kept = 0
    for run in runs:
        if _has_keep_sentinel(run.path):
            keep_paths.add(run.path)
            pinned_kept += 1
    if keep_full_runs > 0:
        for run in runs[:keep_full_runs]:
            keep_paths.add(run.path)

    if keep_full_days > 0:
        cutoff = now - dt.timedelta(days=keep_full_days)
        for run in runs:
            if run.run_started >= cutoff:
                keep_paths.add(run.path)
    return (keep_paths, pinned_kept)


def _has_keep_sentinel(run_root: Path) -> bool:
    try:
        for child in run_root.iterdir():
            name = child.name
            if name in _KEEP_SENTINEL_EXACT:
                return True
            if any(name.startswith(prefix) for prefix in _KEEP_SENTINEL_PREFIXES):
                return True
    except OSError:
        return False
    return False


def _processed_output_root_confirmed_by_history(
    *,
    rows: list[dict[str, str]],
    run_root: Path,
    processed_root: Path,
) -> bool:
    for row in rows:
        if str(row.get("run_category") or "") not in _BENCHMARK_CATEGORIES:
            continue
        run_dir_text = str(row.get("run_dir") or "").strip()
        if not run_dir_text:
            continue
        run_dir_candidates = _normalize_run_path_candidates(run_dir_text)
        if not any(_is_under_root(candidate, run_root) for candidate in run_dir_candidates):
            continue
        report_path_text = str(row.get("report_path") or "").strip()
        if not report_path_text:
            continue
        for candidate in _normalize_run_path_candidates(report_path_text):
            if _is_under_root(candidate, processed_root):
                return True
    return False


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


def _normalize_run_path_candidates(path_text: str) -> list[Path]:
    run_dir = Path(path_text).expanduser()
    candidates = [run_dir]
    if not run_dir.is_absolute():
        candidates.append(Path.cwd() / run_dir)
    return candidates


def _is_under_root(path_value: Path, root: Path) -> bool:
    try:
        path_value.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _row_has_durable_metrics(row: dict[str, str]) -> bool:
    if str(row.get("per_label_json") or "").strip():
        return True
    for metric_key in (
        "strict_accuracy",
        "macro_f1_excluding_other",
        "boundary_correct",
        "boundary_over",
        "boundary_under",
        "boundary_partial",
    ):
        if str(row.get(metric_key) or "").strip():
            return True
    return False


def _run_root_has_durable_history(rows: list[dict[str, str]], run_root: Path) -> bool:
    for row in rows:
        if str(row.get("run_category") or "") not in _BENCHMARK_CATEGORIES:
            continue
        run_dir_text = str(row.get("run_dir") or "").strip()
        if not run_dir_text:
            continue
        if not _row_has_durable_metrics(row):
            continue
        for candidate in _normalize_run_path_candidates(run_dir_text):
            if _is_under_root(candidate, run_root):
                return True
    return False
