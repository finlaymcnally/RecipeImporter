"""QualitySuite ETA helpers based on all-method scheduler telemetry."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import statistics
from typing import Iterable, Sequence

_PENDING_UNIT_WEIGHT = 1.0
_ACTIVE_UNIT_WEIGHT = 0.20
_EVAL_UNIT_WEIGHT = 0.75
_WING_UNIT_WEIGHT = 0.35
_POST_UNIT_WEIGHT = 0.55
_PREP_UNIT_WEIGHT = 0.25
_RECENT_RATE_INTERVALS = 16


@dataclass(frozen=True)
class SchedulerTelemetryRow:
    elapsed_seconds: float
    pending: int
    active: int
    eval_active: int
    wing_backlog: int
    post_active: int
    prep_active: int


@dataclass(frozen=True)
class QualityRunEtaEstimate:
    experiment_count: int
    active_experiments: int
    pending_work_units: float
    estimated_remaining_seconds: float | None
    experiments_with_eta: int


def _coerce_non_negative_int(value: object) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, numeric)


def _coerce_non_negative_float(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, numeric)


def parse_scheduler_timeseries_rows(path: Path) -> list[SchedulerTelemetryRow]:
    rows: list[SchedulerTelemetryRow] = []
    if not path.exists() or not path.is_file():
        return rows
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, dict):
            continue
        rows.append(
            SchedulerTelemetryRow(
                elapsed_seconds=_coerce_non_negative_float(
                    payload.get("elapsed_seconds")
                ),
                pending=_coerce_non_negative_int(payload.get("pending")),
                active=_coerce_non_negative_int(payload.get("active")),
                eval_active=_coerce_non_negative_int(payload.get("evaluate_active")),
                wing_backlog=_coerce_non_negative_int(payload.get("wing_backlog")),
                post_active=_coerce_non_negative_int(payload.get("post_active")),
                prep_active=_coerce_non_negative_int(payload.get("prep_active")),
            )
        )
    rows.sort(key=lambda row: row.elapsed_seconds)
    return rows


def remaining_work_units(row: SchedulerTelemetryRow) -> float:
    return (
        (float(row.pending) * _PENDING_UNIT_WEIGHT)
        + (float(row.active) * _ACTIVE_UNIT_WEIGHT)
        + (float(row.eval_active) * _EVAL_UNIT_WEIGHT)
        + (float(row.wing_backlog) * _WING_UNIT_WEIGHT)
        + (float(row.post_active) * _POST_UNIT_WEIGHT)
        + (float(row.prep_active) * _PREP_UNIT_WEIGHT)
    )


def _recent_positive_rate_units_per_second(
    rows: Sequence[SchedulerTelemetryRow],
) -> float | None:
    if len(rows) < 2:
        return None
    rates: list[float] = []
    points = list(rows[-_RECENT_RATE_INTERVALS:])
    for prior, current in zip(points, points[1:]):
        elapsed = float(current.elapsed_seconds) - float(prior.elapsed_seconds)
        if elapsed <= 0:
            continue
        delta_units = remaining_work_units(prior) - remaining_work_units(current)
        if delta_units <= 0:
            continue
        rates.append(delta_units / elapsed)
    if not rates:
        return None
    return max(0.0, float(statistics.median(rates)))


def estimate_experiment_eta_seconds(
    rows: Sequence[SchedulerTelemetryRow],
) -> float | None:
    if not rows:
        return None
    current = rows[-1]
    remaining_units = remaining_work_units(current)
    if remaining_units <= 0:
        return 0.0
    recent_rate = _recent_positive_rate_units_per_second(rows)
    if recent_rate is None or recent_rate <= 0:
        return None
    return remaining_units / recent_rate


def _scheduler_timeseries_paths_for_experiment(experiment_dir: Path) -> list[Path]:
    return sorted(
        experiment_dir.glob("**/scheduler_timeseries.jsonl"),
        key=lambda path: str(path),
    )


def _candidate_rows_for_experiment(experiment_dir: Path) -> list[SchedulerTelemetryRow]:
    candidates: list[SchedulerTelemetryRow] = []
    for path in _scheduler_timeseries_paths_for_experiment(experiment_dir):
        rows = parse_scheduler_timeseries_rows(path)
        if not rows:
            continue
        candidates.append(rows[-1])
    return candidates


def _active_rows_for_experiment(experiment_dir: Path) -> list[SchedulerTelemetryRow]:
    active_rows: list[SchedulerTelemetryRow] = []
    for path in _scheduler_timeseries_paths_for_experiment(experiment_dir):
        rows = parse_scheduler_timeseries_rows(path)
        if not rows:
            continue
        last = rows[-1]
        if remaining_work_units(last) > 0:
            active_rows.extend(rows)
    return active_rows


def estimate_quality_run_eta(experiments_root: Path) -> QualityRunEtaEstimate:
    experiment_dirs = sorted(
        [path for path in experiments_root.iterdir() if path.is_dir()],
        key=lambda path: path.name,
    ) if experiments_root.exists() and experiments_root.is_dir() else []

    active_experiments = 0
    pending_work_units = 0.0
    eta_seconds: list[float] = []
    for experiment_dir in experiment_dirs:
        last_rows = _candidate_rows_for_experiment(experiment_dir)
        if not last_rows:
            continue
        last_row = max(last_rows, key=remaining_work_units)
        remaining_units = remaining_work_units(last_row)
        if remaining_units <= 0:
            continue
        active_experiments += 1
        pending_work_units += remaining_units
        active_rows = _active_rows_for_experiment(experiment_dir)
        estimated = estimate_experiment_eta_seconds(active_rows)
        if estimated is None:
            continue
        eta_seconds.append(float(estimated))

    return QualityRunEtaEstimate(
        experiment_count=len(experiment_dirs),
        active_experiments=active_experiments,
        pending_work_units=pending_work_units,
        estimated_remaining_seconds=max(eta_seconds) if eta_seconds else None,
        experiments_with_eta=len(eta_seconds),
    )


def format_eta_seconds_short(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    total_seconds = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
