from __future__ import annotations

import json
from pathlib import Path

from cookimport.bench.quality_compare import (
    QualityThresholds,
    compare_quality_runs,
    format_quality_compare_report,
)


def _write_summary(path: Path, payload: dict[str, object]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def test_compare_quality_runs_fails_on_regression_and_settings_mismatch(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_summary(
        baseline,
        {
            "experiments": [
                {
                    "id": "baseline",
                    "status": "ok",
                    "run_settings_hash": "hash-a",
                    "strict_f1_macro": 0.80,
                    "practical_f1_macro": 0.82,
                    "source_success_rate": 1.0,
                }
            ]
        },
    )
    _write_summary(
        candidate,
        {
            "experiments": [
                {
                    "id": "candidate",
                    "status": "ok",
                    "run_settings_hash": "hash-b",
                    "strict_f1_macro": 0.78,
                    "practical_f1_macro": 0.79,
                    "source_success_rate": 0.95,
                }
            ]
        },
    )

    payload = compare_quality_runs(
        baseline,
        candidate,
        thresholds=QualityThresholds(
            strict_f1_drop_max=0.005,
            practical_f1_drop_max=0.005,
            source_success_rate_drop_max=0.0,
        ),
    )

    assert payload["settings_match"] is False
    assert payload["overall"]["verdict"] == "FAIL"
    reasons = payload["overall"]["reasons"]
    assert any("Run settings hash mismatch" in reason for reason in reasons)
    assert any("strict_f1_macro drop exceeded threshold" in reason for reason in reasons)
    assert any("practical_f1_macro drop exceeded threshold" in reason for reason in reasons)
    assert any("source_success_rate drop exceeded threshold" in reason for reason in reasons)


def test_compare_quality_runs_allows_settings_mismatch_with_override_and_single_success_fallback(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline_override"
    candidate = tmp_path / "candidate_override"
    _write_summary(
        baseline,
        {
            "experiments": [
                {
                    "id": "exp_baseline",
                    "status": "ok",
                    "run_settings_hash": "hash-a",
                    "strict_f1_macro": 0.70,
                    "practical_f1_macro": 0.72,
                    "source_success_rate": 1.0,
                },
                {
                    "id": "failed_other",
                    "status": "failed",
                    "run_settings_hash": "hash-a",
                    "strict_f1_macro": 0.0,
                    "practical_f1_macro": 0.0,
                    "source_success_rate": 0.0,
                },
            ]
        },
    )
    _write_summary(
        candidate,
        {
            "experiments": [
                {
                    "id": "exp_candidate",
                    "status": "ok",
                    "run_settings_hash": "hash-b",
                    "strict_f1_macro": 0.71,
                    "practical_f1_macro": 0.73,
                    "source_success_rate": 1.0,
                }
            ]
        },
    )

    payload = compare_quality_runs(
        baseline,
        candidate,
        thresholds=QualityThresholds(),
        allow_settings_mismatch=True,
    )

    assert payload["baseline_experiment_id"] == "exp_baseline"
    assert payload["candidate_experiment_id"] == "exp_candidate"
    assert payload["settings_match"] is False
    assert payload["overall"]["verdict"] == "PASS"
    assert payload["overall"]["reasons"] == []
    report = format_quality_compare_report(payload)
    assert "Quality Comparison Report" in report
    assert "Verdict: PASS" in report
