from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase_worker_runtime import resolve_phase_worker_count

PHASE_PLAN_JSON_NAME = "phase_plan.json"
PHASE_PLAN_SUMMARY_JSON_NAME = "phase_plan_summary.json"
PHASE_PLAN_SCHEMA_VERSION = "codex_phase_plan.v1"
PHASE_PLAN_SUMMARY_SCHEMA_VERSION = "codex_phase_plan_summary.v1"


def build_phase_plan(
    *,
    stage_key: str,
    stage_label: str,
    stage_order: int,
    surface_pipeline: str,
    runtime_pipeline_id: str,
    shard_specs: Sequence[Mapping[str, Any]],
    worker_count: int | None,
    requested_shard_count: int | None = None,
    budget_native_shard_count: int | None = None,
    launch_shard_count: int | None = None,
    planning_warnings: Sequence[str] | None = None,
    invalid_request_errors: Sequence[str] | None = None,
) -> dict[str, Any]:
    requested_workers = resolve_phase_worker_count(
        requested_worker_count=worker_count,
        shard_count=len(shard_specs),
    )
    normalized_shards: list[dict[str, Any]] = []
    worker_ids = _assign_workers(
        requested_worker_count=requested_workers,
        shard_count=len(shard_specs),
    )
    work_unit_label = next(
        (
            str(shard.get("work_unit_label") or "").strip()
            for shard in shard_specs
            if str(shard.get("work_unit_label") or "").strip()
        ),
        "units",
    )
    for index, shard in enumerate(shard_specs):
        worker_id = str(shard.get("worker_id") or "").strip() or worker_ids[index]
        normalized_shards.append(
            {
                "shard_id": (
                    str(shard.get("shard_id") or "").strip()
                    or f"{stage_key}-shard-{index + 1:04d}"
                ),
                "worker_id": worker_id,
                "owned_ids": [
                    str(item)
                    for item in shard.get("owned_ids") or []
                    if str(item).strip()
                ],
                "call_ids": [
                    str(item)
                    for item in shard.get("call_ids") or []
                    if str(item).strip()
                ],
                "prompt_chars": max(0, int(shard.get("prompt_chars") or 0)),
                "task_prompt_chars": max(0, int(shard.get("task_prompt_chars") or 0)),
                "work_unit_count": max(0, int(shard.get("work_unit_count") or 0)),
            }
        )
    worker_count_effective = len({shard["worker_id"] for shard in normalized_shards}) or 0
    launch_count = (
        max(0, int(launch_shard_count))
        if launch_shard_count is not None
        else len(normalized_shards)
    )
    requested_count = (
        max(1, int(requested_shard_count))
        if requested_shard_count is not None
        else (launch_count or len(normalized_shards) or 1)
    )
    budget_native_count = (
        max(1, int(budget_native_shard_count))
        if budget_native_shard_count is not None
        else (launch_count or len(normalized_shards) or 1)
    )
    return {
        "schema_version": PHASE_PLAN_SCHEMA_VERSION,
        "stage_key": stage_key,
        "stage_label": stage_label,
        "stage_order": stage_order,
        "surface_pipeline": surface_pipeline,
        "runtime_pipeline_id": runtime_pipeline_id,
        "requested_shard_count": requested_count,
        "budget_native_shard_count": budget_native_count,
        "launch_shard_count": launch_count,
        "survivability_recommended_shard_count": None,
        "minimum_safe_shard_count": None,
        "planning_warnings": _clean_string_list(planning_warnings),
        "invalid_request_errors": _clean_string_list(invalid_request_errors),
        "worker_count_requested": requested_workers,
        "worker_count": worker_count_effective,
        "fresh_agent_count": worker_count_effective,
        "interaction_count": sum(len(shard["call_ids"]) for shard in normalized_shards),
        "shard_count": len(normalized_shards),
        "owned_id_count": sum(len(shard["owned_ids"]) for shard in normalized_shards),
        "shards_per_worker": _int_distribution(
            [
                sum(1 for shard in normalized_shards if shard["worker_id"] == worker_id)
                for worker_id in sorted({shard["worker_id"] for shard in normalized_shards})
            ]
        ),
        "owned_ids_per_shard": _int_distribution(
            [len(shard["owned_ids"]) for shard in normalized_shards]
        ),
        "work_unit_label": work_unit_label,
        "work_unit_count": sum(shard["work_unit_count"] for shard in normalized_shards),
        "work_units_per_shard": _int_distribution(
            [shard["work_unit_count"] for shard in normalized_shards]
        ),
        "first_turn_payload_chars": _int_distribution(
            [shard["prompt_chars"] for shard in normalized_shards]
        ),
        "task_payload_chars": _int_distribution(
            [shard["task_prompt_chars"] for shard in normalized_shards]
        ),
        "workers": [
            {
                "worker_id": worker_id,
                "shard_count": sum(
                    1 for shard in normalized_shards if shard["worker_id"] == worker_id
                ),
                "shard_ids": [
                    shard["shard_id"]
                    for shard in normalized_shards
                    if shard["worker_id"] == worker_id
                ],
            }
            for worker_id in sorted({shard["worker_id"] for shard in normalized_shards})
        ],
        "shards": normalized_shards,
    }


def attach_survivability_to_phase_plan(
    *,
    phase_plan: Mapping[str, Any],
    survivability_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    updated_phase_plan = dict(phase_plan)
    if not isinstance(survivability_report, Mapping):
        return updated_phase_plan
    updated_phase_plan["minimum_safe_shard_count"] = survivability_report.get(
        "minimum_safe_shard_count"
    )
    updated_phase_plan["survivability_recommended_shard_count"] = survivability_report.get(
        "minimum_safe_shard_count"
    )
    updated_phase_plan["binding_limit"] = survivability_report.get("binding_limit")
    updated_phase_plan["survivability_verdict"] = survivability_report.get(
        "survivability_verdict"
    )
    updated_phase_plan["survivability"] = dict(survivability_report)
    shard_metrics = {
        str(row.get("shard_id") or ""): row
        for row in survivability_report.get("shards") or []
        if isinstance(row, Mapping)
    }
    updated_shards: list[dict[str, Any]] = []
    for shard in phase_plan.get("shards") or []:
        if not isinstance(shard, Mapping):
            continue
        updated_shard = dict(shard)
        metrics = shard_metrics.get(str(updated_shard.get("shard_id") or ""))
        if isinstance(metrics, Mapping):
            for key in (
                "estimated_input_tokens",
                "estimated_output_tokens",
                "estimated_followup_tokens",
                "estimated_peak_session_tokens",
                "verdict",
                "binding_limit",
            ):
                updated_shard[key] = metrics.get(key)
        updated_shards.append(updated_shard)
    updated_phase_plan["shards"] = updated_shards
    return updated_phase_plan


def build_phase_plan_summary(
    phase_plan: Mapping[str, Any],
) -> dict[str, Any]:
    survivability = (
        phase_plan.get("survivability")
        if isinstance(phase_plan.get("survivability"), Mapping)
        else {}
    )
    totals = (
        survivability.get("totals")
        if isinstance(survivability.get("totals"), Mapping)
        else {}
    )
    summary = {
        "schema_version": PHASE_PLAN_SUMMARY_SCHEMA_VERSION,
        "stage_key": phase_plan.get("stage_key"),
        "stage_label": phase_plan.get("stage_label"),
        "stage_order": phase_plan.get("stage_order"),
        "surface_pipeline": phase_plan.get("surface_pipeline"),
        "runtime_pipeline_id": phase_plan.get("runtime_pipeline_id"),
        "requested_shard_count": phase_plan.get("requested_shard_count"),
        "survivability_recommended_shard_count": phase_plan.get(
            "survivability_recommended_shard_count"
        ),
        "budget_native_shard_count": phase_plan.get("budget_native_shard_count"),
        "launch_shard_count": phase_plan.get("launch_shard_count"),
        "shard_count": phase_plan.get("shard_count"),
        "worker_count": phase_plan.get("worker_count"),
        "interaction_count": phase_plan.get("interaction_count"),
        "work_unit_label": phase_plan.get("work_unit_label"),
        "work_unit_count": phase_plan.get("work_unit_count"),
        "binding_limit": phase_plan.get("binding_limit"),
        "survivability_verdict": phase_plan.get("survivability_verdict"),
        "planning_warnings": list(phase_plan.get("planning_warnings") or []),
        "invalid_request_errors": list(phase_plan.get("invalid_request_errors") or []),
        "first_turn_payload_chars": dict(phase_plan.get("first_turn_payload_chars") or {}),
        "task_payload_chars": dict(phase_plan.get("task_payload_chars") or {}),
        "predicted_tokens": {
            "estimated_input_tokens": totals.get("estimated_input_tokens"),
            "estimated_output_tokens": totals.get("estimated_output_tokens"),
            "estimated_followup_tokens": totals.get("estimated_followup_tokens"),
            "estimated_peak_session_tokens": totals.get("estimated_peak_session_tokens"),
        },
    }
    return summary


def build_phase_plan_prediction_drift(
    *,
    phase_plan: Mapping[str, Any],
    observed_stage_summary: Mapping[str, Any],
) -> dict[str, Any] | None:
    survivability = (
        phase_plan.get("survivability")
        if isinstance(phase_plan.get("survivability"), Mapping)
        else {}
    )
    totals = (
        survivability.get("totals")
        if isinstance(survivability.get("totals"), Mapping)
        else {}
    )
    predicted_input = _coerce_int(totals.get("estimated_input_tokens"))
    predicted_output = _coerce_int(totals.get("estimated_output_tokens"))
    predicted_followup = _coerce_int(totals.get("estimated_followup_tokens"))
    predicted_peak = _coerce_int(totals.get("estimated_peak_session_tokens"))
    observed_input = _coerce_int(observed_stage_summary.get("tokens_input"))
    observed_output = _coerce_int(observed_stage_summary.get("tokens_output"))
    observed_total = _coerce_int(observed_stage_summary.get("tokens_total"))
    if all(
        value is None
        for value in (
            predicted_input,
            predicted_output,
            predicted_followup,
            predicted_peak,
            observed_input,
            observed_output,
            observed_total,
        )
    ):
        return None
    return {
        "predicted_input_tokens": predicted_input,
        "observed_input_tokens": observed_input,
        "input_token_delta": _delta(observed_input, predicted_input),
        "predicted_output_tokens": predicted_output,
        "observed_output_tokens": observed_output,
        "output_token_delta": _delta(observed_output, predicted_output),
        "predicted_followup_tokens": predicted_followup,
        "predicted_peak_session_tokens": predicted_peak,
        "observed_billed_total_tokens": observed_total,
        "billed_total_minus_predicted_peak_session_tokens": _delta(
            observed_total,
            predicted_peak,
        ),
    }


def write_phase_plan_artifacts(
    *,
    stage_dir: Path,
    phase_plan: Mapping[str, Any],
) -> tuple[Path, Path]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    phase_plan_path = stage_dir / PHASE_PLAN_JSON_NAME
    phase_plan_summary_path = stage_dir / PHASE_PLAN_SUMMARY_JSON_NAME
    phase_plan_path.write_text(
        json.dumps(dict(phase_plan), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    phase_plan_summary_path.write_text(
        json.dumps(build_phase_plan_summary(phase_plan), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return phase_plan_path, phase_plan_summary_path


def _assign_workers(*, requested_worker_count: int, shard_count: int) -> list[str]:
    effective_workers = max(1, min(requested_worker_count, max(shard_count, 1)))
    return [f"worker-{(index % effective_workers) + 1:03d}" for index in range(shard_count)]


def _clean_string_list(values: Sequence[str] | None) -> list[str]:
    return [text for text in (str(value).strip() for value in values or []) if text]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _delta(observed: int | None, predicted: int | None) -> int | None:
    if observed is None or predicted is None:
        return None
    return int(observed) - int(predicted)


def _int_distribution(values: Sequence[int]) -> dict[str, int | float]:
    normalized = [int(value) for value in values if int(value) >= 0]
    if not normalized:
        return {"count": 0, "min": 0, "max": 0, "avg": 0.0}
    return {
        "count": len(normalized),
        "min": min(normalized),
        "max": max(normalized),
        "avg": round(sum(normalized) / len(normalized), 3),
    }
