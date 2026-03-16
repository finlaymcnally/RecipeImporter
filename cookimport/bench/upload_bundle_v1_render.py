from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from cookimport.bench.upload_bundle_v1_model import UploadBundleSourceModel
from cookimport.runs.stage_observability import (
    recipe_stage_keys_for_pipeline,
    stage_label,
)


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return round(number, 6)


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_stage_rows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        stage_key = str(row.get("stage_key") or "").strip()
        stage_label = str(row.get("stage_label") or "").strip()
        if not stage_key or not stage_label:
            continue
        rows.append({"stage_key": stage_key, "stage_label": stage_label})
    return rows


def _float_or_zero(value: Any) -> float:
    parsed = _coerce_float(value)
    return float(parsed) if parsed is not None else 0.0


def _default_recipe_stages() -> list[dict[str, str]]:
    return [
        {
            "stage_key": stage_key,
            "stage_label": stage_label(stage_key),
        }
        for stage_key in recipe_stage_keys_for_pipeline(
            "codex-farm-single-correction-v1"
        )
    ]


def _recipe_stages_from_context(context_payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = _coerce_stage_rows(context_payload.get("recipe_stages"))
    return rows or _default_recipe_stages()


def _recipe_stage_metric_key(
    stage_key: str,
    pass_stage_per_label_metrics: dict[str, Any],
) -> str | None:
    if stage_key == "build_intermediate_det":
        return None
    if stage_key == "recipe_llm_correct_and_link":
        return "pass2"
    if stage_key == "build_final_recipe":
        return "pass3"
    return stage_key


def _build_recipe_stage_row(
    *,
    recipe_stage: dict[str, str],
    row: dict[str, Any],
    pass3_fallback_reason: str,
) -> dict[str, Any]:
    stage_key = str(recipe_stage.get("stage_key") or "")
    stage_label = str(recipe_stage.get("stage_label") or stage_key)
    if stage_key == "build_intermediate_det":
        return {
            "stage_key": stage_key,
            "stage_label": stage_label,
            "status": "ok",
            "deterministic_stage": True,
        }
    if stage_key == "recipe_llm_correct_and_link":
        return {
            "stage_key": stage_key,
            "stage_label": stage_label,
            "status": str(row.get("pass2_status") or ""),
            "degradation_severity": str(row.get("pass2_degradation_severity") or ""),
            "promotion_policy": str(row.get("pass2_promotion_policy") or ""),
            "warning_count": int(_coerce_int(row.get("pass2_warning_count")) or 0),
            "warning_buckets": _coerce_str_list(row.get("pass2_warning_buckets")),
            "degradation_reasons": _coerce_str_list(row.get("pass2_degradation_reasons")),
            "extracted_instruction_count": int(
                _coerce_int(row.get("pass2_extracted_instruction_count")) or 0
            ),
        }
    if stage_key == "build_final_recipe":
        return {
            "stage_key": stage_key,
            "stage_label": stage_label,
            "status": str(row.get("pass3_status") or ""),
            "execution_mode": str(row.get("pass3_execution_mode") or ""),
            "routing_reason": str(row.get("pass3_routing_reason") or ""),
            "empty_mapping": bool(row.get("pass3_empty_mapping")),
            "warning_count": int(_coerce_int(row.get("pass3_warning_count")) or 0),
            "warning_buckets": _coerce_str_list(row.get("pass3_warning_buckets")),
            "fallback_reason": pass3_fallback_reason,
        }
    return {
        "stage_key": stage_key,
        "stage_label": stage_label,
        "status": "",
    }


def build_stage_separated_comparison(
    *,
    recipe_triage_rows: list[dict[str, Any]],
    per_label_metrics: list[dict[str, Any]],
    comparison_pairs: list[dict[str, Any]],
    pass_stage_per_label_metrics: dict[str, Any],
    recipe_pipeline_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    line_role_pipeline_by_run_id: dict[str, str] = {}
    for pair in comparison_pairs:
        if not isinstance(pair, dict):
            continue
        codex_run = pair.get("codex_run")
        if not isinstance(codex_run, dict):
            continue
        run_id = str(codex_run.get("run_id") or "").strip()
        if not run_id:
            continue
        line_role_pipeline_by_run_id[run_id] = str(codex_run.get("line_role_pipeline") or "off")

    context_payload = recipe_pipeline_context if isinstance(recipe_pipeline_context, dict) else {}
    recipe_stages = _recipe_stages_from_context(context_payload)

    per_recipe_rows: list[dict[str, Any]] = []
    for row in recipe_triage_rows:
        run_id = str(row.get("codex_run_id") or row.get("run_id") or "").strip()
        line_role_pipeline = line_role_pipeline_by_run_id.get(run_id, "unknown")
        pass3_fallback_reason = str(row.get("pass3_fallback_reason") or "").strip()
        recipe_stage_rows = [
            _build_recipe_stage_row(
                recipe_stage=recipe_stage,
                row=row,
                pass3_fallback_reason=pass3_fallback_reason,
            )
            for recipe_stage in recipe_stages
        ]
        per_recipe_rows.append(
            {
                "source_key": str(row.get("source_key") or ""),
                "codex_run_id": run_id,
                "baseline_run_id": str(row.get("baseline_run_id") or ""),
                "recipe_id": str(row.get("recipe_id") or ""),
                "short_title": str(row.get("short_title") or ""),
                "baseline_stage": {
                    "line_accuracy": _coerce_float(row.get("baseline_accuracy")),
                },
                "line_role_pipeline_stage": {
                    "pipeline": line_role_pipeline,
                    "line_accuracy": _coerce_float(row.get("codex_accuracy")),
                    "delta_vs_baseline": _coerce_float(row.get("delta_codex_minus_baseline")),
                },
                "recipe_stages": recipe_stage_rows,
                "final_or_fallback_stage": {
                    "status": "fallback" if pass3_fallback_reason else "final",
                    "fallback_reason": pass3_fallback_reason or None,
                    "recipe_stage_statuses": {
                        str(stage_row.get("stage_key") or ""): str(stage_row.get("status") or "")
                        for stage_row in recipe_stage_rows
                    },
                },
            }
        )
    per_recipe_rows.sort(
        key=lambda row: (
            _float_or_zero(((row.get("line_role_pipeline_stage") or {}).get("delta_vs_baseline"))),
            -sum(
                int(_coerce_int(stage_row.get("warning_count")) or 0)
                for stage_row in (row.get("recipe_stages") or [])
                if isinstance(stage_row, dict)
            ),
            str(row.get("recipe_id") or ""),
        )
    )

    def _build_pass_stage_row(stage_key: str, stage_label: str, label: str) -> dict[str, Any]:
        metric_key = _recipe_stage_metric_key(
            stage_key,
            pass_stage_per_label_metrics,
        )
        if metric_key is None:
            return {
                "stage_key": stage_key,
                "stage_label": stage_label,
                "label_scored": False,
                "unavailable_reason": (
                    "Deterministic intermediate build is not separately scored in the "
                    "benchmark artifacts."
                ),
                "runs_scored": 0,
            }
        stage_payload = pass_stage_per_label_metrics.get(metric_key)
        stage_payload = stage_payload if isinstance(stage_payload, dict) else {}
        stage_labels = stage_payload.get("labels")
        stage_labels = stage_labels if isinstance(stage_labels, dict) else {}
        label_row = stage_labels.get(label)
        if isinstance(label_row, dict):
            return {
                "stage_key": stage_key,
                "stage_label": stage_label,
                "label_scored": True,
                "precision_avg": _coerce_float(label_row.get("precision_avg")),
                "recall_avg": _coerce_float(label_row.get("recall_avg")),
                "f1_avg": _coerce_float(label_row.get("f1_avg")),
                "gold_total_sum": int(_coerce_int(label_row.get("gold_total_sum")) or 0),
                "pred_total_sum": int(_coerce_int(label_row.get("pred_total_sum")) or 0),
                "runs_scored": int(_coerce_int(label_row.get("runs_scored")) or 0),
            }
        reason = str(stage_payload.get("unavailable_reason") or "").strip()
        if not reason and stage_payload.get("available"):
            reason = f"{stage_key} stage label metrics unavailable for label={label}"
        if not reason:
            reason = (
                f"{stage_key} stage outputs could not be projected/scored from discovered "
                "benchmark codex artifacts"
            )
        return {
            "stage_key": stage_key,
            "stage_label": stage_label,
            "label_scored": False,
            "unavailable_reason": reason,
            "runs_scored": int(_coerce_int(stage_payload.get("runs_scored")) or 0),
        }

    per_label_rows: list[dict[str, Any]] = []
    for row in per_label_metrics:
        label = str(row.get("label") or "")
        per_label_rows.append(
            {
                "label": label,
                "baseline_stage": {
                    "recall_avg": _coerce_float(row.get("baseline_recall_avg")),
                    "f1_avg": _coerce_float(row.get("baseline_f1_avg")),
                },
                "line_role_pipeline_stage": {
                    "recall_avg": _coerce_float(row.get("codex_recall_avg")),
                    "f1_avg": _coerce_float(row.get("codex_f1_avg")),
                    "delta_recall_avg": _coerce_float(row.get("delta_recall_avg")),
                    "delta_f1_avg": _coerce_float(row.get("delta_f1_avg")),
                },
                "recipe_stages": [
                    _build_pass_stage_row(
                        str(recipe_stage.get("stage_key") or ""),
                        str(recipe_stage.get("stage_label") or ""),
                        label,
                    )
                    for recipe_stage in recipe_stages
                ],
                "final_or_fallback_stage": {
                    "confusion_delta_outbound_total": int(
                        _coerce_int(row.get("confusion_delta_outbound_total")) or 0
                    ),
                    "confusion_delta_inbound_total": int(
                        _coerce_int(row.get("confusion_delta_inbound_total")) or 0
                    ),
                    "top_confusion_outbound": row.get("top_confusion_outbound"),
                    "top_confusion_inbound": row.get("top_confusion_inbound"),
                },
            }
        )

    return {
        "schema_version": "upload_bundle_stage_comparison.v2",
        "pair_count": len(comparison_pairs),
        "recipe_topology_key": str(
            context_payload.get("recipe_topology_key") or "single_correction"
        ),
        "recipe_stages": recipe_stages,
        "per_recipe": per_recipe_rows,
        "per_label": per_label_rows,
    }


def build_recipe_pipeline_context_from_model(
    *,
    model: UploadBundleSourceModel,
) -> dict[str, Any]:
    topology = model.topology if isinstance(model.topology, dict) else {}
    return {
        "schema_version": str(
            topology.get("schema_version") or "upload_bundle_recipe_pipeline_context.v2"
        ),
        "codex_recipe_pipelines": (
            list(topology.get("codex_recipe_pipelines"))
            if isinstance(topology.get("codex_recipe_pipelines"), list)
            else []
        ),
        "recipe_topology_key": str(topology.get("recipe_topology_key") or "single_correction"),
        "recipe_stages": _recipe_stages_from_context(topology),
        "observed_recipe_stage_call_counts": (
            dict(topology.get("observed_recipe_stage_call_counts"))
            if isinstance(topology.get("observed_recipe_stage_call_counts"), dict)
            else {}
        ),
        "observed_recipe_execution_modes": (
            list(topology.get("observed_recipe_execution_modes"))
            if isinstance(topology.get("observed_recipe_execution_modes"), list)
            else []
        ),
        "observed_recipe_routing_reasons": (
            list(topology.get("observed_recipe_routing_reasons"))
            if isinstance(topology.get("observed_recipe_routing_reasons"), list)
            else []
        ),
        "observed_recipe_pipelines": (
            list(topology.get("observed_recipe_pipelines"))
            if isinstance(topology.get("observed_recipe_pipelines"), list)
            else []
        ),
    }


def build_stage_separated_comparison_from_model(
    *,
    model: UploadBundleSourceModel,
    per_label_metrics: list[dict[str, Any]],
    pass_stage_per_label_metrics: dict[str, Any],
) -> dict[str, Any]:
    return build_stage_separated_comparison(
        recipe_triage_rows=model.recipe_triage_rows,
        per_label_metrics=per_label_metrics,
        comparison_pairs=model.comparison_pairs,
        pass_stage_per_label_metrics=pass_stage_per_label_metrics,
        recipe_pipeline_context=build_recipe_pipeline_context_from_model(model=model),
    )


def write_upload_bundle_v1(
    *,
    model: UploadBundleSourceModel,
    output_dir: Path,
    source_root: Path,
    write_impl: Callable[..., dict[str, Any]],
    high_level_only: bool = False,
    target_bundle_size_bytes: int | None = None,
) -> dict[str, Any]:
    return write_impl(
        output_dir=output_dir,
        source_dir=source_root,
        high_level_only=high_level_only,
        target_bundle_size_bytes=target_bundle_size_bytes,
        source_model=model,
    )
