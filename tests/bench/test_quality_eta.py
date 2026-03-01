from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.bench.quality_eta import (
    estimate_experiment_eta_seconds,
    estimate_quality_run_remaining_seconds,
    estimate_quality_run_eta,
    format_eta_seconds_short,
    parse_scheduler_timeseries_rows,
)


def _write_scheduler_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_estimate_experiment_eta_seconds_tracks_linear_pending_drain(
    tmp_path: Path,
) -> None:
    path = tmp_path / "linear" / "scheduler_timeseries.jsonl"
    _write_scheduler_rows(
        path,
        [
            {"elapsed_seconds": 0.0, "pending": 26, "active": 0},
            {"elapsed_seconds": 120.0, "pending": 14, "active": 0},
            {"elapsed_seconds": 240.0, "pending": 2, "active": 0},
        ],
    )
    rows = parse_scheduler_timeseries_rows(
        path
    )
    eta_seconds = estimate_experiment_eta_seconds(rows)
    assert eta_seconds == pytest.approx(20.0, abs=1.0)


def test_estimate_experiment_eta_seconds_handles_zero_pending_tail(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tail" / "scheduler_timeseries.jsonl"
    _write_scheduler_rows(
        path,
        [
            {
                "elapsed_seconds": 0.0,
                "pending": 4,
                "active": 12,
                "evaluate_active": 3,
                "wing_backlog": 4,
                "post_active": 0,
            },
            {
                "elapsed_seconds": 120.0,
                "pending": 0,
                "active": 10,
                "evaluate_active": 2,
                "wing_backlog": 3,
                "post_active": 3,
            },
            {
                "elapsed_seconds": 240.0,
                "pending": 0,
                "active": 6,
                "evaluate_active": 1,
                "wing_backlog": 1,
                "post_active": 2,
            },
        ],
    )
    rows = parse_scheduler_timeseries_rows(
        path
    )
    eta_seconds = estimate_experiment_eta_seconds(rows)
    assert eta_seconds is not None
    assert eta_seconds > 30.0


def test_estimate_experiment_eta_seconds_returns_none_without_progress(
    tmp_path: Path,
) -> None:
    path = tmp_path / "flat" / "scheduler_timeseries.jsonl"
    _write_scheduler_rows(
        path,
        [
            {"elapsed_seconds": 0.0, "pending": 8, "active": 10, "evaluate_active": 2},
            {"elapsed_seconds": 120.0, "pending": 8, "active": 10, "evaluate_active": 2},
            {"elapsed_seconds": 240.0, "pending": 8, "active": 10, "evaluate_active": 2},
        ],
    )
    rows = parse_scheduler_timeseries_rows(
        path
    )
    assert estimate_experiment_eta_seconds(rows) is None


def test_estimate_quality_run_eta_uses_slowest_active_experiment(tmp_path: Path) -> None:
    exp_a = tmp_path / "experiments" / "fast" / "race" / "round_01_probe" / "scheduler_timeseries.jsonl"
    exp_b = tmp_path / "experiments" / "slow" / "race" / "round_01_probe" / "scheduler_timeseries.jsonl"
    _write_scheduler_rows(
        exp_a,
        [
            {"elapsed_seconds": 0.0, "pending": 16, "active": 0},
            {"elapsed_seconds": 100.0, "pending": 6, "active": 0},
            {"elapsed_seconds": 200.0, "pending": 2, "active": 0},
        ],
    )
    _write_scheduler_rows(
        exp_b,
        [
            {"elapsed_seconds": 0.0, "pending": 20, "active": 0},
            {"elapsed_seconds": 100.0, "pending": 12, "active": 0},
            {"elapsed_seconds": 200.0, "pending": 8, "active": 0},
        ],
    )

    estimate = estimate_quality_run_eta(tmp_path / "experiments")
    assert estimate.experiment_count == 2
    assert estimate.active_experiments == 2
    assert estimate.estimated_remaining_seconds is not None
    assert estimate.estimated_remaining_seconds == pytest.approx(133.33, abs=2.0)
    assert estimate.experiments_with_eta == 2


def test_estimate_quality_run_remaining_seconds_includes_queued_experiments(
    tmp_path: Path,
) -> None:
    exp_a = tmp_path / "experiments" / "active_a" / "scheduler_timeseries.jsonl"
    exp_b = tmp_path / "experiments" / "active_b" / "scheduler_timeseries.jsonl"
    _write_scheduler_rows(
        exp_a,
        [
            {"elapsed_seconds": 0.0, "pending": 30, "active": 0},
            {"elapsed_seconds": 100.0, "pending": 20, "active": 0},
            {"elapsed_seconds": 200.0, "pending": 10, "active": 0},
        ],
    )
    _write_scheduler_rows(
        exp_b,
        [
            {"elapsed_seconds": 0.0, "pending": 24, "active": 0},
            {"elapsed_seconds": 100.0, "pending": 16, "active": 0},
            {"elapsed_seconds": 200.0, "pending": 8, "active": 0},
        ],
    )
    for queued_id in ("queued_c", "queued_d", "queued_e", "queued_f"):
        (tmp_path / "experiments" / queued_id).mkdir(parents=True, exist_ok=True)

    estimate = estimate_quality_run_eta(tmp_path / "experiments")
    remaining_seconds = estimate_quality_run_remaining_seconds(
        estimate=estimate,
        total_experiments=6,
        completed_experiments=0,
        parallel_workers=2,
    )
    assert estimate.active_experiments == 2
    assert remaining_seconds is not None
    assert remaining_seconds == pytest.approx(300.0, abs=3.0)


def test_estimate_quality_run_remaining_seconds_falls_back_to_completed_median(
    tmp_path: Path,
) -> None:
    _write_scheduler_rows(
        tmp_path / "experiments" / "done_a" / "scheduler_timeseries.jsonl",
        [
            {"elapsed_seconds": 0.0, "pending": 4, "active": 0},
            {"elapsed_seconds": 120.0, "pending": 0, "active": 0},
        ],
    )
    _write_scheduler_rows(
        tmp_path / "experiments" / "done_b" / "scheduler_timeseries.jsonl",
        [
            {"elapsed_seconds": 0.0, "pending": 5, "active": 0},
            {"elapsed_seconds": 180.0, "pending": 0, "active": 0},
        ],
    )

    estimate = estimate_quality_run_eta(tmp_path / "experiments")
    remaining_seconds = estimate_quality_run_remaining_seconds(
        estimate=estimate,
        total_experiments=5,
        completed_experiments=2,
        parallel_workers=2,
    )
    assert estimate.active_experiments == 0
    assert estimate.completed_experiment_median_seconds == pytest.approx(150.0, abs=0.1)
    assert remaining_seconds == pytest.approx(300.0, abs=1.0)


def test_format_eta_seconds_short_handles_ranges() -> None:
    assert format_eta_seconds_short(None) == "n/a"
    assert format_eta_seconds_short(8.6) == "9s"
    assert format_eta_seconds_short(94.0) == "1m 34s"
    assert format_eta_seconds_short(3784.0) == "1h 3m 4s"
