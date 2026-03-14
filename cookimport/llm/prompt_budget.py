from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

_TOKEN_KEYS = (
    "tokens_input",
    "tokens_cached_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_total",
)


def build_prediction_run_prompt_budget_summary(
    pred_manifest: Mapping[str, Any],
    pred_run_dir: Path,
) -> dict[str, Any]:
    by_pass: dict[str, dict[str, Any]] = {}

    llm_payload = pred_manifest.get("llm_codex_farm")
    if isinstance(llm_payload, Mapping):
        process_runs = llm_payload.get("process_runs")
        if isinstance(process_runs, Mapping):
            for pass_name in ("pass1", "pass2", "pass3"):
                pass_payload = process_runs.get(pass_name)
                if not isinstance(pass_payload, Mapping):
                    continue
                pass_summary = _build_codex_farm_pass_summary(
                    pass_name=pass_name,
                    pass_payload=pass_payload,
                )
                if pass_summary is not None:
                    by_pass[pass_name] = pass_summary
        knowledge_payload = llm_payload.get("knowledge")
        if isinstance(knowledge_payload, Mapping):
            process_run = knowledge_payload.get("process_run")
            if isinstance(process_run, Mapping):
                pass4_summary = _build_codex_farm_pass_summary(
                    pass_name="pass4",
                    pass_payload=process_run,
                )
                if pass4_summary is not None:
                    by_pass["pass4"] = pass4_summary

    line_role_summary = _build_line_role_pass_summary(
        pred_manifest=pred_manifest,
        pred_run_dir=pred_run_dir,
    )
    if line_role_summary is not None:
        by_pass["line_role"] = line_role_summary

    totals: dict[str, int | None] = {
        "call_count": None,
        "duration_total_ms": None,
        **{key: None for key in _TOKEN_KEYS},
    }
    for payload in by_pass.values():
        totals["call_count"] = _sum_optional_ints(
            totals.get("call_count"),
            _nonnegative_int(payload.get("call_count")),
        )
        totals["duration_total_ms"] = _sum_optional_ints(
            totals.get("duration_total_ms"),
            _nonnegative_int(payload.get("duration_total_ms")),
        )
        for key in _TOKEN_KEYS:
            totals[key] = _sum_optional_ints(
                totals.get(key),
                _nonnegative_int(payload.get(key)),
            )

    return {
        "schema_version": "prompt_budget_summary.v1",
        "prediction_run_dir": str(pred_run_dir),
        "by_pass": by_pass,
        "totals": totals,
    }


def write_prediction_run_prompt_budget_summary(
    pred_run_dir: Path,
    summary: Mapping[str, Any],
) -> Path:
    target_path = pred_run_dir / "prompt_budget_summary.json"
    target_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target_path


def _build_codex_farm_pass_summary(
    *,
    pass_name: str,
    pass_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    process_payload = pass_payload.get("process_payload")
    telemetry_rows = None
    if isinstance(process_payload, Mapping):
        telemetry = process_payload.get("telemetry")
        if isinstance(telemetry, Mapping) and isinstance(telemetry.get("rows"), list):
            telemetry_rows = telemetry.get("rows")

    token_totals: dict[str, int | None] = {key: None for key in _TOKEN_KEYS}
    row_count = 0
    if isinstance(telemetry_rows, list):
        for row in telemetry_rows:
            if not isinstance(row, Mapping):
                continue
            row_count += 1
            for key in _TOKEN_KEYS:
                token_totals[key] = _sum_optional_ints(
                    token_totals.get(key),
                    _nonnegative_int(row.get(key)),
                )

    summary_payload = _extract_summary_payload(pass_payload=pass_payload)
    if isinstance(summary_payload, Mapping):
        for key in _TOKEN_KEYS:
            fallback_value = summary_payload.get(key)
            if key == "tokens_reasoning" and fallback_value is None:
                fallback_value = summary_payload.get("tokens_reasoning_total")
            if token_totals.get(key) is None:
                token_totals[key] = _nonnegative_int(fallback_value)

    call_count = (
        _extract_call_count(summary_payload)
        if isinstance(summary_payload, Mapping)
        else None
    )
    if call_count is None and row_count > 0:
        call_count = row_count
    duration_total_ms = (
        _extract_duration_total_ms(summary_payload, call_count=call_count)
        if isinstance(summary_payload, Mapping)
        else None
    )

    if (
        call_count is None
        and duration_total_ms is None
        and all(token_totals.get(key) is None for key in _TOKEN_KEYS)
    ):
        return None

    return {
        "pass": pass_name,
        "kind": "codex_farm",
        "call_count": call_count,
        "duration_total_ms": duration_total_ms,
        **token_totals,
    }


def _build_line_role_pass_summary(
    *,
    pred_manifest: Mapping[str, Any],
    pred_run_dir: Path,
) -> dict[str, Any] | None:
    telemetry_path = _resolve_line_role_telemetry_path(
        pred_manifest=pred_manifest,
        pred_run_dir=pred_run_dir,
    )
    if telemetry_path is None:
        return None
    try:
        payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, Mapping):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return None

    call_count = _nonnegative_int(summary.get("call_count"))
    batch_count = _nonnegative_int(summary.get("batch_count"))
    if call_count is None:
        call_count = batch_count

    token_totals = {
        key: _nonnegative_int(summary.get(key))
        for key in _TOKEN_KEYS
    }
    if (
        call_count is None
        and _nonnegative_int(summary.get("duration_total_ms")) is None
        and all(value is None for value in token_totals.values())
    ):
        return None

    return {
        "pass": "line_role",
        "kind": "line_role",
        "call_count": call_count,
        "batch_count": batch_count,
        "attempt_count": _nonnegative_int(summary.get("attempt_count")),
        "duration_total_ms": _nonnegative_int(summary.get("duration_total_ms")),
        **token_totals,
    }


def _resolve_line_role_telemetry_path(
    *,
    pred_manifest: Mapping[str, Any],
    pred_run_dir: Path,
) -> Path | None:
    raw_path = str(pred_manifest.get("line_role_pipeline_telemetry_path") or "").strip()
    candidates: list[Path] = []
    if raw_path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = pred_run_dir / candidate
        candidates.append(candidate)
    candidates.append(pred_run_dir / "line-role-pipeline" / "telemetry_summary.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _extract_summary_payload(*, pass_payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    process_payload = pass_payload.get("process_payload")
    if isinstance(process_payload, Mapping):
        telemetry_report = process_payload.get("telemetry_report")
        if isinstance(telemetry_report, Mapping) and isinstance(
            telemetry_report.get("summary"), Mapping
        ):
            return telemetry_report.get("summary")
    telemetry_report = pass_payload.get("telemetry_report")
    if isinstance(telemetry_report, Mapping) and isinstance(
        telemetry_report.get("summary"), Mapping
    ):
        return telemetry_report.get("summary")
    return None


def _extract_call_count(summary: Mapping[str, Any]) -> int | None:
    call_count = _nonnegative_int(summary.get("call_count"))
    if call_count is not None:
        return call_count
    status_counts = summary.get("status_counts")
    if isinstance(status_counts, Mapping):
        parsed = [
            _nonnegative_int(value)
            for value in status_counts.values()
        ]
        if any(value is not None for value in parsed):
            return sum(int(value or 0) for value in parsed)
    matched_rows = _nonnegative_int(summary.get("matched_rows"))
    if matched_rows is not None:
        return matched_rows
    return None


def _extract_duration_total_ms(
    summary: Mapping[str, Any],
    *,
    call_count: int | None,
) -> int | None:
    duration_total_ms = _nonnegative_int(summary.get("duration_total_ms"))
    if duration_total_ms is not None:
        return duration_total_ms
    duration_avg_ms = summary.get("duration_avg_ms")
    avg_value = _nonnegative_float(duration_avg_ms)
    if avg_value is not None and call_count is not None and call_count > 0:
        return int(round(avg_value * call_count))
    return None


def _nonnegative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _nonnegative_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _sum_optional_ints(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right
