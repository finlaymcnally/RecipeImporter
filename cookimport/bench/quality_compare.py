"""Baseline-vs-candidate comparison for quality-suite runs."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cookimport.bench.qualitysuite.summary import load_quality_run_summary


class QualityThresholds(BaseModel):
    strict_f1_drop_max: float = 0.005
    practical_f1_drop_max: float = 0.005
    source_success_rate_drop_max: float = 0.0


def compare_quality_runs(
    baseline_run_dir: Path,
    candidate_run_dir: Path,
    *,
    thresholds: QualityThresholds,
    baseline_experiment_id: str | None = None,
    candidate_experiment_id: str | None = None,
    allow_settings_mismatch: bool = False,
) -> dict[str, Any]:
    baseline_summary = load_quality_run_summary(baseline_run_dir)
    candidate_summary = load_quality_run_summary(candidate_run_dir)

    baseline_row = _select_experiment_row(
        summary=baseline_summary,
        requested_id=baseline_experiment_id,
        default_id="baseline",
        side_name="baseline",
    )
    candidate_row = _select_experiment_row(
        summary=candidate_summary,
        requested_id=candidate_experiment_id,
        default_id="candidate",
        side_name="candidate",
    )

    baseline_settings_hash = _coerce_text(baseline_row.get("run_settings_hash"))
    candidate_settings_hash = _coerce_text(candidate_row.get("run_settings_hash"))
    settings_match = (
        baseline_settings_hash is not None
        and candidate_settings_hash is not None
        and baseline_settings_hash == candidate_settings_hash
    )

    reasons: list[str] = []
    status_failures = _status_failures(
        baseline_row=baseline_row,
        candidate_row=candidate_row,
    )
    reasons.extend(status_failures)

    if not settings_match and not allow_settings_mismatch:
        reasons.append(
            "Run settings hash mismatch between selected baseline and candidate experiments."
        )

    delta_payload = _build_delta_payload(
        baseline_row=baseline_row,
        candidate_row=candidate_row,
    )
    reasons.extend(
        _gate_regressions(
            delta_payload=delta_payload,
            thresholds=thresholds,
        )
    )

    verdict = "PASS" if not reasons else "FAIL"
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
        "baseline_run_dir": str(baseline_run_dir),
        "candidate_run_dir": str(candidate_run_dir),
        "baseline_experiment_id": str(baseline_row.get("id") or ""),
        "candidate_experiment_id": str(candidate_row.get("id") or ""),
        "allow_settings_mismatch": bool(allow_settings_mismatch),
        "baseline_run_settings_hash": baseline_settings_hash,
        "candidate_run_settings_hash": candidate_settings_hash,
        "settings_match": settings_match,
        "thresholds": thresholds.model_dump(),
        "baseline_summary": _selected_summary_fields(baseline_row),
        "candidate_summary": _selected_summary_fields(candidate_row),
        "metric_deltas": delta_payload,
        "overall": {
            "verdict": verdict,
            "reason_count": len(reasons),
            "reasons": reasons,
            "settings_mismatch_forced_fail": (
                (not settings_match) and (not allow_settings_mismatch)
            ),
        },
    }


def format_quality_compare_report(payload: dict[str, Any]) -> str:
    overall = payload.get("overall") or {}
    lines = [
        "# Quality Comparison Report",
        "",
        f"- Baseline run: {payload.get('baseline_run_dir')}",
        f"- Candidate run: {payload.get('candidate_run_dir')}",
        f"- Baseline experiment: {payload.get('baseline_experiment_id')}",
        f"- Candidate experiment: {payload.get('candidate_experiment_id')}",
        f"- Verdict: {overall.get('verdict')}",
        "",
        "## Run Settings Parity",
        "",
        (
            "- Baseline run settings hash: "
            f"{payload.get('baseline_run_settings_hash') or 'missing'}"
        ),
        (
            "- Candidate run settings hash: "
            f"{payload.get('candidate_run_settings_hash') or 'missing'}"
        ),
        f"- Settings match: {payload.get('settings_match')}",
        f"- Allow settings mismatch: {payload.get('allow_settings_mismatch')}",
        "",
        "## Thresholds",
        "",
        (
            "- strict_f1_drop_max: "
            f"{payload.get('thresholds', {}).get('strict_f1_drop_max')}"
        ),
        (
            "- practical_f1_drop_max: "
            f"{payload.get('thresholds', {}).get('practical_f1_drop_max')}"
        ),
        (
            "- source_success_rate_drop_max: "
            f"{payload.get('thresholds', {}).get('source_success_rate_drop_max')}"
        ),
        "",
        "## Metric Deltas (candidate - baseline)",
        "",
    ]

    for metric_name, row in sorted((payload.get("metric_deltas") or {}).items()):
        if not isinstance(row, dict):
            continue
        lines.append(
            "- "
            f"{metric_name}: baseline={_render_float(row.get('baseline'))} | "
            f"candidate={_render_float(row.get('candidate'))} | "
            f"delta={_render_delta(row.get('delta'))}"
        )

    lines.extend(["", "## Verdict Reasons", ""])
    reasons = overall.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        lines.append("- None")
    else:
        for reason in reasons:
            lines.append(f"- {reason}")
    lines.append("")
    return "\n".join(lines)


def _select_experiment_row(
    *,
    summary: dict[str, Any],
    requested_id: str | None,
    default_id: str,
    side_name: str,
) -> dict[str, Any]:
    rows = _experiment_rows(summary)
    indexed = {
        str(row.get("id") or "").strip(): row
        for row in rows
        if str(row.get("id") or "").strip()
    }
    if requested_id is not None:
        cleaned = str(requested_id).strip()
        if cleaned not in indexed:
            available = ", ".join(sorted(indexed)) or "<none>"
            raise ValueError(
                f"{side_name} experiment id not found: {cleaned}. Available: {available}"
            )
        return indexed[cleaned]

    if default_id in indexed:
        return indexed[default_id]

    successful = [
        row
        for row in rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    if len(successful) == 1:
        return successful[0]

    available = ", ".join(sorted(indexed)) or "<none>"
    raise ValueError(
        f"{side_name} experiment selection is ambiguous. "
        f"Provide --{side_name}-experiment-id. Available: {available}"
    )


def _experiment_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = summary.get("experiments")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _status_failures(
    *,
    baseline_row: dict[str, Any],
    candidate_row: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    for side_name, row in (("baseline", baseline_row), ("candidate", candidate_row)):
        status = str(row.get("status") or "").strip().lower()
        if status == "ok":
            continue
        if status in {"failed", "incomplete"}:
            failures.append(
                f"Selected {side_name} experiment has status={status}."
            )
            continue
        failures.append(
            f"Selected {side_name} experiment has unsupported status={status or 'missing'}."
        )
    return failures


def _build_delta_payload(
    *,
    baseline_row: dict[str, Any],
    candidate_row: dict[str, Any],
) -> dict[str, dict[str, float | None]]:
    metric_names = (
        "strict_precision_macro",
        "strict_recall_macro",
        "strict_f1_macro",
        "practical_precision_macro",
        "practical_recall_macro",
        "practical_f1_macro",
        "source_success_rate",
    )
    payload: dict[str, dict[str, float | None]] = {}
    for name in metric_names:
        baseline_value = _coerce_float(baseline_row.get(name))
        candidate_value = _coerce_float(candidate_row.get(name))
        delta = None
        if baseline_value is not None and candidate_value is not None:
            delta = candidate_value - baseline_value
        payload[name] = {
            "baseline": baseline_value,
            "candidate": candidate_value,
            "delta": delta,
        }
    return payload


def _gate_regressions(
    *,
    delta_payload: dict[str, dict[str, float | None]],
    thresholds: QualityThresholds,
) -> list[str]:
    reasons: list[str] = []

    strict_drop = _metric_drop(delta_payload.get("strict_f1_macro"))
    if strict_drop is None:
        reasons.append("Missing strict_f1_macro on selected experiment rows.")
    elif strict_drop > float(thresholds.strict_f1_drop_max):
        reasons.append(
            "strict_f1_macro drop exceeded threshold "
            f"({strict_drop:.4f} > {float(thresholds.strict_f1_drop_max):.4f})."
        )

    practical_drop = _metric_drop(delta_payload.get("practical_f1_macro"))
    if practical_drop is None:
        reasons.append("Missing practical_f1_macro on selected experiment rows.")
    elif practical_drop > float(thresholds.practical_f1_drop_max):
        reasons.append(
            "practical_f1_macro drop exceeded threshold "
            f"({practical_drop:.4f} > {float(thresholds.practical_f1_drop_max):.4f})."
        )

    success_drop = _metric_drop(delta_payload.get("source_success_rate"))
    if success_drop is None:
        reasons.append("Missing source_success_rate on selected experiment rows.")
    elif success_drop > float(thresholds.source_success_rate_drop_max):
        reasons.append(
            "source_success_rate drop exceeded threshold "
            f"({success_drop:.4f} > {float(thresholds.source_success_rate_drop_max):.4f})."
        )

    return reasons


def _metric_drop(delta_row: dict[str, float | None] | None) -> float | None:
    if not isinstance(delta_row, dict):
        return None
    delta = delta_row.get("delta")
    if delta is None:
        return None
    return max(0.0, 0.0 - float(delta))


def _selected_summary_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "status": row.get("status"),
        "error": row.get("error"),
        "run_settings_hash": row.get("run_settings_hash"),
        "strict_f1_macro": row.get("strict_f1_macro"),
        "practical_f1_macro": row.get("practical_f1_macro"),
        "source_success_rate": row.get("source_success_rate"),
        "sources_planned": row.get("sources_planned"),
        "sources_successful": row.get("sources_successful"),
        "configs_planned": row.get("configs_planned"),
        "configs_completed": row.get("configs_completed"),
        "configs_successful": row.get("configs_successful"),
    }


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, numeric)


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _render_float(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.4f}"


def _render_delta(value: Any) -> str:
    numeric = _coerce_signed_float(value)
    if numeric is None:
        return "n/a"
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.4f}"


def _coerce_signed_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
