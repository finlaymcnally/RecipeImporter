from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from cookimport.bench.upload_bundle_v1_model import UploadBundleSourceModel

LEGACY_PASS2_FAMILY_DISPLAY_NAME = "legacy-family:pass2_*"
LEGACY_PASS3_FAMILY_DISPLAY_NAME = "legacy-family:pass3_*"


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


def _float_or_zero(value: Any) -> float:
    parsed = _coerce_float(value)
    return float(parsed) if parsed is not None else 0.0


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

    per_recipe_rows: list[dict[str, Any]] = []
    for row in recipe_triage_rows:
        run_id = str(row.get("codex_run_id") or row.get("run_id") or "").strip()
        line_role_pipeline = line_role_pipeline_by_run_id.get(run_id, "unknown")
        pass3_fallback_reason = str(row.get("pass3_fallback_reason") or "").strip()
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
                "pass2_stage": {
                    "status": str(row.get("pass2_status") or ""),
                    "degradation_severity": str(row.get("pass2_degradation_severity") or ""),
                    "promotion_policy": str(row.get("pass2_promotion_policy") or ""),
                    "warning_count": int(_coerce_int(row.get("pass2_warning_count")) or 0),
                    "warning_buckets": _coerce_str_list(row.get("pass2_warning_buckets")),
                    "degradation_reasons": _coerce_str_list(row.get("pass2_degradation_reasons")),
                    "extracted_instruction_count": int(
                        _coerce_int(row.get("pass2_extracted_instruction_count")) or 0
                    ),
                },
                "pass3_stage": {
                    "status": str(row.get("pass3_status") or ""),
                    "execution_mode": str(row.get("pass3_execution_mode") or ""),
                    "routing_reason": str(row.get("pass3_routing_reason") or ""),
                    "empty_mapping": bool(row.get("pass3_empty_mapping")),
                    "warning_count": int(_coerce_int(row.get("pass3_warning_count")) or 0),
                    "warning_buckets": _coerce_str_list(row.get("pass3_warning_buckets")),
                    "fallback_reason": pass3_fallback_reason,
                },
                "final_or_fallback_stage": {
                    "status": "fallback" if pass3_fallback_reason else "final",
                    "fallback_reason": pass3_fallback_reason or None,
                    "pass1_status": str(row.get("pass1_status") or ""),
                    "pass2_status": str(row.get("pass2_status") or ""),
                    "pass3_status": str(row.get("pass3_status") or ""),
                    "pass2_degradation_severity": str(row.get("pass2_degradation_severity") or ""),
                    "pass2_promotion_policy": str(row.get("pass2_promotion_policy") or ""),
                    "pass3_execution_mode": str(row.get("pass3_execution_mode") or ""),
                    "pass3_routing_reason": str(row.get("pass3_routing_reason") or ""),
                },
            }
        )
    per_recipe_rows.sort(
        key=lambda row: (
            _float_or_zero(((row.get("line_role_pipeline_stage") or {}).get("delta_vs_baseline"))),
            -int(_coerce_int(((row.get("pass2_stage") or {}).get("warning_count"))) or 0),
            str(row.get("recipe_id") or ""),
        )
    )

    def _build_pass_stage_row(stage_key: str, label: str) -> dict[str, Any]:
        stage_payload = pass_stage_per_label_metrics.get(stage_key)
        stage_payload = stage_payload if isinstance(stage_payload, dict) else {}
        stage_labels = stage_payload.get("labels")
        stage_labels = stage_labels if isinstance(stage_labels, dict) else {}
        label_row = stage_labels.get(label)
        if isinstance(label_row, dict):
            return {
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
                "prediction-run codex artifacts"
            )
        return {
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
                "pass2_stage": _build_pass_stage_row("pass2", label),
                "pass3_stage": _build_pass_stage_row("pass3", label),
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

    context_payload = recipe_pipeline_context if isinstance(recipe_pipeline_context, dict) else {}
    return {
        "schema_version": "upload_bundle_stage_comparison.v1",
        "pair_count": len(comparison_pairs),
        "stage_label_mode": str(context_payload.get("stage_label_mode") or "standard_topology"),
        "stage_display_names": (
            context_payload.get("stage_display_names")
            if isinstance(context_payload.get("stage_display_names"), dict)
            else {
                "baseline_stage": "baseline",
                "line_role_pipeline_stage": "line-role",
                "pass2_stage": LEGACY_PASS2_FAMILY_DISPLAY_NAME,
                "pass3_stage": LEGACY_PASS3_FAMILY_DISPLAY_NAME,
                "final_or_fallback_stage": "final-fallback",
            }
        ),
        "legacy_field_aliases": (
            context_payload.get("legacy_field_aliases")
            if isinstance(context_payload.get("legacy_field_aliases"), dict)
            else {
                "pass2_stage": "pass2_*",
                "pass3_stage": "pass3_*",
            }
        ),
        "compatibility_note": str(context_payload.get("compatibility_note") or ""),
        "per_recipe": per_recipe_rows,
        "per_label": per_label_rows,
    }


def build_stage_separated_comparison_from_model(
    *,
    model: UploadBundleSourceModel,
    per_label_metrics: list[dict[str, Any]],
    pass_stage_per_label_metrics: dict[str, Any],
) -> dict[str, Any]:
    topology = model.topology if isinstance(model.topology, dict) else {}
    stage_display_names = topology.get("stage_display_names")
    context_payload: dict[str, Any] = {
        "stage_label_mode": str(topology.get("stage_label_mode") or "standard_topology"),
        "compatibility_note": str(topology.get("compatibility_note") or ""),
        "legacy_field_aliases": (
            model.compatibility_aliases
            if isinstance(model.compatibility_aliases, dict)
            else {}
        ),
    }
    if isinstance(stage_display_names, dict):
        context_payload["stage_display_names"] = stage_display_names
    return build_stage_separated_comparison(
        recipe_triage_rows=model.recipe_triage_rows,
        per_label_metrics=per_label_metrics,
        comparison_pairs=model.comparison_pairs,
        pass_stage_per_label_metrics=pass_stage_per_label_metrics,
        recipe_pipeline_context=context_payload,
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
