"""Baseline-vs-candidate comparison for speed-suite runs."""

from __future__ import annotations

import datetime as dt
import statistics
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cookimport.bench.speed_runner import load_speed_run_summary


class SpeedThresholds(BaseModel):
    regression_pct: float = 5.0
    absolute_seconds_floor: float = 0.5


def compare_speed_runs(
    baseline_run_dir: Path,
    candidate_run_dir: Path,
    *,
    thresholds: SpeedThresholds,
) -> dict[str, Any]:
    baseline_summary = load_speed_run_summary(baseline_run_dir)
    candidate_summary = load_speed_run_summary(candidate_run_dir)

    baseline_rows = _index_summary_rows(baseline_summary)
    candidate_rows = _index_summary_rows(candidate_summary)

    baseline_keys = set(baseline_rows)
    candidate_keys = set(candidate_rows)
    shared_keys = sorted(baseline_keys & candidate_keys)

    compared_rows: list[dict[str, Any]] = []
    regression_count = 0
    improved_count = 0
    flat_count = 0

    for key in shared_keys:
        target_id, scenario = key
        baseline_row = baseline_rows[key]
        candidate_row = candidate_rows[key]
        baseline_seconds = _select_row_seconds(baseline_row)
        candidate_seconds = _select_row_seconds(candidate_row)
        delta_seconds = (
            candidate_seconds - baseline_seconds
            if baseline_seconds is not None and candidate_seconds is not None
            else None
        )
        delta_pct = (
            ((delta_seconds / baseline_seconds) * 100.0)
            if delta_seconds is not None
            and baseline_seconds is not None
            and baseline_seconds > 0.0
            else None
        )
        regression = _is_regression(
            delta_seconds=delta_seconds,
            delta_pct=delta_pct,
            baseline_seconds=baseline_seconds,
            thresholds=thresholds,
        )
        status = "incomplete"
        if regression:
            status = "regression"
            regression_count += 1
        elif delta_seconds is not None:
            if delta_seconds < 0:
                status = "improved"
                improved_count += 1
            else:
                status = "flat"
                flat_count += 1

        compared_rows.append(
            {
                "target_id": target_id,
                "scenario": scenario,
                "baseline_seconds": baseline_seconds,
                "candidate_seconds": candidate_seconds,
                "delta_seconds": delta_seconds,
                "delta_pct": delta_pct,
                "regression": regression,
                "status": status,
            }
        )

    missing_in_baseline = [
        {"target_id": target_id, "scenario": scenario}
        for target_id, scenario in sorted(candidate_keys - baseline_keys)
    ]
    missing_in_candidate = [
        {"target_id": target_id, "scenario": scenario}
        for target_id, scenario in sorted(baseline_keys - candidate_keys)
    ]

    baseline_distribution = [
        value
        for value in (_select_row_seconds(row) for row in baseline_rows.values())
        if value is not None
    ]
    candidate_distribution = [
        value
        for value in (_select_row_seconds(row) for row in candidate_rows.values())
        if value is not None
    ]
    verdict = "FAIL" if regression_count > 0 else "PASS"
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
        "baseline_run_dir": str(baseline_run_dir),
        "candidate_run_dir": str(candidate_run_dir),
        "thresholds": thresholds.model_dump(),
        "baseline_suite_name": baseline_summary.get("suite_name"),
        "candidate_suite_name": candidate_summary.get("suite_name"),
        "rows": compared_rows,
        "missing_in_baseline": missing_in_baseline,
        "missing_in_candidate": missing_in_candidate,
        "overall": {
            "verdict": verdict,
            "pairs_compared": len(compared_rows),
            "regression_count": regression_count,
            "improved_count": improved_count,
            "flat_count": flat_count,
            "baseline_median_seconds": (
                float(statistics.median(baseline_distribution))
                if baseline_distribution
                else None
            ),
            "candidate_median_seconds": (
                float(statistics.median(candidate_distribution))
                if candidate_distribution
                else None
            ),
        },
    }


def format_speed_compare_report(payload: dict[str, Any]) -> str:
    overall = payload.get("overall") or {}
    lines = [
        "# Speed Comparison Report",
        "",
        f"- Baseline: {payload.get('baseline_run_dir')}",
        f"- Candidate: {payload.get('candidate_run_dir')}",
        f"- Verdict: {overall.get('verdict')}",
        f"- Compared pairs: {overall.get('pairs_compared')}",
        f"- Regressions: {overall.get('regression_count')}",
        f"- Improved: {overall.get('improved_count')}",
        f"- Flat: {overall.get('flat_count')}",
        "",
        "## Thresholds",
        "",
        f"- Regression percent: {payload.get('thresholds', {}).get('regression_pct')}",
        "- Absolute seconds floor: "
        f"{payload.get('thresholds', {}).get('absolute_seconds_floor')}",
        "",
        "## Pair Results",
        "",
    ]
    for row in payload.get("rows", []):
        lines.append(
            "- "
            f"{row.get('target_id')} | {row.get('scenario')} | "
            f"baseline={_render_seconds(row.get('baseline_seconds'))} | "
            f"candidate={_render_seconds(row.get('candidate_seconds'))} | "
            f"delta={_render_delta_seconds(row.get('delta_seconds'))} | "
            f"delta_pct={_render_delta_pct(row.get('delta_pct'))} | "
            f"status={row.get('status')}"
        )

    if payload.get("missing_in_baseline"):
        lines.extend(["", "## Missing In Baseline", ""])
        for row in payload["missing_in_baseline"]:
            lines.append(f"- {row.get('target_id')} | {row.get('scenario')}")

    if payload.get("missing_in_candidate"):
        lines.extend(["", "## Missing In Candidate", ""])
        for row in payload["missing_in_candidate"]:
            lines.append(f"- {row.get('target_id')} | {row.get('scenario')}")

    lines.append("")
    return "\n".join(lines)


def _index_summary_rows(summary_payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in summary_payload.get("summary_rows", []):
        target_id = str(row.get("target_id") or "").strip()
        scenario = str(row.get("scenario") or "").strip()
        if not target_id or not scenario:
            continue
        indexed[(target_id, scenario)] = row
    return indexed


def _select_row_seconds(row: dict[str, Any]) -> float | None:
    primary = _coerce_float(row.get("median_total_seconds"))
    if primary is not None:
        return primary
    return _coerce_float(row.get("median_wall_seconds"))


def _is_regression(
    *,
    delta_seconds: float | None,
    delta_pct: float | None,
    baseline_seconds: float | None,
    thresholds: SpeedThresholds,
) -> bool:
    if delta_seconds is None:
        return False
    if delta_seconds < 0:
        return False
    if delta_seconds < max(0.0, float(thresholds.absolute_seconds_floor)):
        return False
    if baseline_seconds is None or baseline_seconds <= 0.0:
        return True
    if delta_pct is None:
        return False
    return delta_pct >= float(thresholds.regression_pct)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return 0.0
    return numeric


def _render_seconds(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.3f}s"


def _render_delta_seconds(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "n/a"
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.3f}s"


def _render_delta_pct(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "n/a"
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.2f}%"
