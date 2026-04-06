from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterable

from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_contracts import (
    RUN_SETTING_CONTRACT_FULL,
    project_run_config_payload,
)
from cookimport.core.models import ConversionResult
from cookimport.labelstudio.canonical_line_projection import (
    FreeformSpanPrediction,
    build_line_role_extracted_archive_payload,
    build_line_role_stage_prediction_payload,
    project_line_roles_to_freeform_spans,
)
from cookimport.llm.prompt_budget import build_prediction_run_prompt_budget_summary
from cookimport.parsing.label_source_of_truth import (
    LabelFirstStageResult,
    authoritative_lines_to_canonical_predictions,
)
from cookimport.runs import RunManifest, write_run_manifest
from cookimport.staging.import_session import execute_stage_import_session_from_result
from cookimport.staging.nonrecipe_stage import NonRecipeStageResult

logger = logging.getLogger(__name__)


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)

def _write_manifest_best_effort(
    run_root: Path,
    manifest: RunManifest,
    *,
    notify: Callable[[str], None] | None = None,
) -> None:
    try:
        write_run_manifest(run_root, manifest)
    except Exception as exc:  # noqa: BLE001
        message = f"Warning: failed to write run_manifest.json in {run_root}: {exc}"
        if notify is not None:
            notify(message)
        logger.warning(message)

def _write_processed_outputs(
    *,
    result: ConversionResult,
    path: Path,
    run_dt: dt.datetime,
    output_root: Path,
    importer_name: str,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    schemaorg_overrides_by_recipe_id: dict[str, dict[str, Any]] | None = None,
    draft_overrides_by_recipe_id: dict[str, dict[str, Any]] | None = None,
    llm_codex_farm: dict[str, Any] | None = None,
    write_markdown: bool = True,
) -> Path:
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    run_root = output_root / timestamp
    run_root.mkdir(parents=True, exist_ok=True)
    report_totals_diagnostics_path = (
        run_root / f"{path.stem}.report_totals_mismatch_diagnostics.json"
    )
    session = execute_stage_import_session_from_result(
        result=result,
        source_file=path,
        run_root=run_root,
        run_dt=run_dt,
        importer_name=importer_name,
        run_settings=RunSettings.from_dict(
            project_run_config_payload(run_config, contract=RUN_SETTING_CONTRACT_FULL),
            warn_context="benchmark processed output run config",
        ),
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        write_markdown=write_markdown,
        full_blocks=None,
        count_diagnostics_path=report_totals_diagnostics_path,
    )
    result.report = session.conversion_result.report
    return run_root


def _looks_like_line_role_runtime_telemetry(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload.get("summary"), dict)
        or isinstance(payload.get("phases"), list)
        or isinstance(payload.get("runtime_artifacts"), dict)
    )


def _write_line_role_projection_telemetry_summary(
    *,
    telemetry_summary_path: Path,
    projection_payload: dict[str, Any],
) -> None:
    merged_payload = dict(projection_payload)
    if telemetry_summary_path.exists():
        try:
            existing_payload = json.loads(telemetry_summary_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing_payload = None
        if isinstance(existing_payload, dict):
            if _looks_like_line_role_runtime_telemetry(existing_payload):
                merged_payload = dict(existing_payload)
                merged_payload["projection_schema_version"] = str(
                    projection_payload.get("schema_version") or ""
                ).strip() or None
                for key, value in projection_payload.items():
                    if key == "schema_version":
                        continue
                    merged_payload[key] = value
            else:
                merged_payload = {**existing_payload, **projection_payload}
    telemetry_summary_path.write_text(
        json.dumps(merged_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_authoritative_line_role_artifacts(
    *,
    run_root: Path,
    source_file: str,
    source_hash: str,
    workbook_slug: str,
    label_first_result: LabelFirstStageResult,
    nonrecipe_stage_result: NonRecipeStageResult | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    pipeline_dir = run_root / "line-role-pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    route_predictions = authoritative_lines_to_canonical_predictions(
        label_first_result.labeled_lines,
        label_first_result.recipe_spans,
    )
    semantic_predictions, nonrecipe_projection_summary = _apply_nonrecipe_authority_to_predictions(
        predictions=route_predictions,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )
    projected_spans = project_line_roles_to_freeform_spans(semantic_predictions)
    scored_projected_spans, scoring_projection_summary = (
        _build_scored_line_role_projection_spans(
            projected_spans=projected_spans,
            nonrecipe_stage_result=nonrecipe_stage_result,
        )
    )
    stage_payload = build_line_role_stage_prediction_payload(
        scored_projected_spans,
        source_file=source_file,
        source_hash=source_hash,
        workbook_slug=workbook_slug,
        unresolved_block_indices=scoring_projection_summary["unresolved_candidate_block_indices"],
        unresolved_block_category_by_index=scoring_projection_summary[
            "unresolved_candidate_route_by_index"
        ],
        notes=[
            "Prediction-run projection reused authoritative Stage 2 labels for recipe-local lines.",
            "Outside-recipe route labels were projected into final KNOWLEDGE/OTHER only when final authority existed.",
            *([
                f"Nonrecipe authority finalized {nonrecipe_projection_summary['reviewed_candidate_block_count']} outside-recipe candidate blocks before scoring."
            ] if nonrecipe_projection_summary["reviewed_candidate_block_count"] else []),
            *([
                "Unresolved candidate outside-recipe rows were marked unresolved and excluded from semantic scoring."
            ] if scoring_projection_summary["unresolved_candidate_line_count"] else []),
            *([
                f"Knowledge refinement changed {nonrecipe_projection_summary['changed_block_count']} outside-recipe blocks before scoring."
            ] if nonrecipe_projection_summary["changed_block_count"] else []),
        ],
    )
    archive_payload = build_line_role_extracted_archive_payload(projected_spans)

    line_role_predictions_path = pipeline_dir / "line_role_predictions.jsonl"
    semantic_line_role_predictions_path = (
        pipeline_dir / "semantic_line_role_predictions.jsonl"
    )
    projected_spans_path = pipeline_dir / "projected_spans.jsonl"
    stage_predictions_path = pipeline_dir / "stage_block_predictions.json"
    extracted_archive_path = pipeline_dir / "extracted_archive.json"
    telemetry_summary_path = pipeline_dir / "telemetry_summary.json"

    line_role_predictions_path.write_text(
        "\n".join(
            json.dumps(row.model_dump(mode="json"), sort_keys=True)
            for row in route_predictions
        )
        + ("\n" if route_predictions else ""),
        encoding="utf-8",
    )
    semantic_line_role_predictions_path.write_text(
        "\n".join(
            json.dumps(row.model_dump(mode="json"), sort_keys=True)
            for row in semantic_predictions
        )
        + ("\n" if semantic_predictions else ""),
        encoding="utf-8",
    )
    projected_spans_path.write_text(
        "\n".join(
            json.dumps(row.model_dump(mode="json"), sort_keys=True)
            for row in projected_spans
        )
        + ("\n" if projected_spans else ""),
        encoding="utf-8",
    )
    stage_predictions_path.write_text(
        json.dumps(stage_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    extracted_archive_path.write_text(
        json.dumps(archive_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_line_role_projection_telemetry_summary(
        telemetry_summary_path=telemetry_summary_path,
        projection_payload={
            "schema_version": "line_role_final_authority_projection.v1",
            "mode": "final_authority_projection",
            "labeled_line_count": len(label_first_result.labeled_lines),
            "recipe_span_count": len(label_first_result.recipe_spans),
            **nonrecipe_projection_summary,
            **scoring_projection_summary,
        },
    )
    return (
        {
            "line_role_predictions_path": line_role_predictions_path,
            "semantic_line_role_predictions_path": semantic_line_role_predictions_path,
            "projected_spans_path": projected_spans_path,
            "stage_block_predictions_path": stage_predictions_path,
            "extracted_archive_path": extracted_archive_path,
            "telemetry_summary_path": telemetry_summary_path,
        },
        {
            "recipes_applied": len(label_first_result.recipe_spans),
            "span_count": len(projected_spans),
            "authoritative_stage_outputs_mutated": bool(
                nonrecipe_projection_summary["reviewed_candidate_block_count"]
            ),
            "mode": "final_authority_projection",
            **nonrecipe_projection_summary,
            **scoring_projection_summary,
        },
    )

def _build_scored_line_role_projection_spans(
    *,
    projected_spans: Iterable[FreeformSpanPrediction],
    nonrecipe_stage_result: NonRecipeStageResult | None,
) -> tuple[list[FreeformSpanPrediction], dict[str, Any]]:
    spans = list(projected_spans)
    if nonrecipe_stage_result is None:
        return spans, {
            "unresolved_candidate_line_count": 0,
            "unresolved_candidate_block_indices": [],
            "unresolved_candidate_route_by_index": {},
        }

    authoritative_categories = dict(
        nonrecipe_stage_result.authority.authoritative_block_category_by_index
    )
    unresolved_candidate_block_index_set = {
        int(index)
        for index in nonrecipe_stage_result.candidate_status.unresolved_candidate_block_indices
    }
    unresolved_line_indices: set[int] = set()
    unresolved_stage_block_indices: set[int] = set()
    unresolved_route_by_stage_block_index: dict[int, str] = {}
    scored_spans: list[FreeformSpanPrediction] = []
    for span in spans:
        if span.within_recipe_span or span.label not in {"KNOWLEDGE", "OTHER"}:
            scored_spans.append(span)
            continue
        block_index = int(span.block_index)
        line_index = int(span.line_index)
        authoritative_category = authoritative_categories.get(block_index)
        if authoritative_category in {"knowledge", "other"}:
            target_label = (
                "KNOWLEDGE" if authoritative_category == "knowledge" else "OTHER"
            )
            if span.label != target_label:
                span = span.model_copy(update={"label": target_label})
            scored_spans.append(span)
            continue
        if block_index in unresolved_candidate_block_index_set:
            unresolved_line_indices.add(line_index)
            unresolved_stage_block_indices.add(line_index)
            raw_route = nonrecipe_stage_result.candidate_status.unresolved_candidate_route_by_index.get(
                block_index
            )
            if raw_route is not None:
                unresolved_route_by_stage_block_index[line_index] = str(raw_route)
        scored_spans.append(span)
    return scored_spans, {
        "unresolved_candidate_line_count": len(unresolved_line_indices),
        "unresolved_candidate_block_indices": sorted(unresolved_stage_block_indices),
        "unresolved_candidate_route_by_index": {
            int(block_index): route
            for block_index, route in sorted(unresolved_route_by_stage_block_index.items())
        },
    }

def _apply_nonrecipe_authority_to_predictions(
    *,
    predictions: list[Any],
    nonrecipe_stage_result: NonRecipeStageResult | None,
) -> tuple[list[Any], dict[str, Any]]:
    if nonrecipe_stage_result is None:
        return predictions, {
            "authority_mode": "missing_nonrecipe_stage_result",
            "scored_effect": "route_only",
            "reviewed_candidate_block_count": 0,
            "reviewed_candidate_block_indices": [],
            "changed_block_count": 0,
            "changed_block_indices": [],
        }

    final_categories = dict(
        nonrecipe_stage_result.authority.authoritative_block_category_by_index
    )
    reviewed_candidate_block_indices = sorted(
        int(index)
        for index in nonrecipe_stage_result.candidate_status.finalized_candidate_block_indices
    )
    reviewed_candidate_index_set = set(reviewed_candidate_block_indices)
    changed_block_indices = sorted(
        int(row.get("block_index"))
        for row in (nonrecipe_stage_result.refinement_report.get("changed_blocks") or [])
        if isinstance(row, dict) and row.get("block_index") is not None
    )
    adjusted_predictions: list[Any] = []
    for prediction in predictions:
        block_index = getattr(prediction, "block_index", None)
        if getattr(prediction, "within_recipe_span", False) or block_index is None:
            adjusted_predictions.append(prediction)
            continue
        current_label = str(getattr(prediction, "label", "") or "").upper()
        if current_label not in {
            "OTHER",
            "KNOWLEDGE",
            "NONRECIPE_CANDIDATE",
            "NONRECIPE_EXCLUDE",
        }:
            adjusted_predictions.append(prediction)
            continue
        category = final_categories.get(int(block_index))
        if category not in {"knowledge", "other"}:
            adjusted_predictions.append(prediction)
            continue
        target_label = "KNOWLEDGE" if category == "knowledge" else "OTHER"
        block_index_int = int(block_index)
        reviewed_by_nonrecipe_authority = block_index_int in reviewed_candidate_index_set
        reason_tags = list(getattr(prediction, "reason_tags", []) or [])
        authority_reason_tag = f"nonrecipe_authority:{category}"
        if authority_reason_tag not in reason_tags and reviewed_by_nonrecipe_authority:
            reason_tags.append(authority_reason_tag)
        decided_by = (
            "codex" if reviewed_by_nonrecipe_authority else prediction.decided_by
        )
        if current_label == target_label and decided_by == prediction.decided_by:
            adjusted_predictions.append(prediction)
            continue
        adjusted_predictions.append(
            prediction.model_copy(
                update={
                    "label": target_label,
                    "decided_by": decided_by,
                    "reason_tags": reason_tags,
                }
            )
        )
    return adjusted_predictions, {
        "authority_mode": str(
            nonrecipe_stage_result.refinement_report.get("authority_mode")
            or "deterministic_route_only"
        ),
        "scored_effect": str(
            nonrecipe_stage_result.refinement_report.get("scored_effect")
            or "route_only"
        ),
        "reviewed_candidate_block_count": len(reviewed_candidate_block_indices),
        "reviewed_candidate_block_indices": reviewed_candidate_block_indices,
        "changed_block_count": len(changed_block_indices),
        "changed_block_indices": changed_block_indices,
    }

def _llm_selective_retry_run_config_summary(
    llm_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(llm_report, dict):
        return {}
    counts = llm_report.get("counts")
    if not isinstance(counts, dict):
        return {}
    correction_attempts = int(
        counts.get("selective_retry_recipe_correction_attempts") or 0
    )
    final_recipe_attempts = int(
        counts.get("selective_retry_final_recipe_attempts") or 0
    )
    return {
        "selective_retry_attempted": bool(
            correction_attempts or final_recipe_attempts
        ),
        "selective_retry_recipe_correction_attempts": correction_attempts,
        "selective_retry_recipe_correction_recovered": int(
            counts.get("selective_retry_recipe_correction_recovered") or 0
        ),
        "selective_retry_final_recipe_attempts": final_recipe_attempts,
        "selective_retry_final_recipe_recovered": int(
            counts.get("selective_retry_final_recipe_recovered") or 0
        ),
    }
