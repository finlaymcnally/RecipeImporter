from __future__ import annotations

import json
from pathlib import Path

from cookimport.bench.speed_compare import (
    SpeedThresholds,
    compare_speed_runs,
    format_speed_compare_report,
)


def _write_summary(path: Path, payload: dict[str, object]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def test_compare_speed_runs_detects_regression_with_dual_thresholds(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_summary(
        baseline,
        {
            "suite_name": "speed",
            "summary_rows": [
                {
                    "target_id": "alpha",
                    "scenario": "stage_import",
                    "median_total_seconds": 10.0,
                },
                {
                    "target_id": "alpha",
                    "scenario": "benchmark_canonical_legacy",
                    "median_total_seconds": 20.0,
                },
            ],
        },
    )
    _write_summary(
        candidate,
        {
            "suite_name": "speed",
            "summary_rows": [
                {
                    "target_id": "alpha",
                    "scenario": "stage_import",
                    "median_total_seconds": 11.2,
                },
                {
                    "target_id": "alpha",
                    "scenario": "benchmark_canonical_legacy",
                    "median_total_seconds": 18.0,
                },
            ],
        },
    )

    comparison = compare_speed_runs(
        baseline,
        candidate,
        thresholds=SpeedThresholds(regression_pct=5.0, absolute_seconds_floor=0.5),
    )

    assert comparison["overall"]["verdict"] == "FAIL"
    rows = {
        (row["target_id"], row["scenario"]): row
        for row in comparison["rows"]
    }
    assert rows[("alpha", "stage_import")]["status"] == "regression"
    assert rows[("alpha", "benchmark_canonical_legacy")]["status"] == "improved"
    report = format_speed_compare_report(comparison)
    assert "Verdict: FAIL" in report
    assert "alpha | stage_import" in report


def test_compare_speed_runs_passes_when_only_small_delta(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline_small"
    candidate = tmp_path / "candidate_small"
    _write_summary(
        baseline,
        {
            "suite_name": "speed",
            "summary_rows": [
                {
                    "target_id": "beta",
                    "scenario": "stage_import",
                    "median_total_seconds": 10.0,
                }
            ],
        },
    )
    _write_summary(
        candidate,
        {
            "suite_name": "speed",
            "summary_rows": [
                {
                    "target_id": "beta",
                    "scenario": "stage_import",
                    "median_total_seconds": 10.2,
                }
            ],
        },
    )

    comparison = compare_speed_runs(
        baseline,
        candidate,
        thresholds=SpeedThresholds(regression_pct=5.0, absolute_seconds_floor=0.5),
    )

    assert comparison["overall"]["verdict"] == "PASS"
    assert comparison["overall"]["regression_count"] == 0
