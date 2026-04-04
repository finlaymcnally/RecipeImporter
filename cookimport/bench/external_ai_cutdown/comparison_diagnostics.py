from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def _build_pair_diagnostics(
    *,
    source_key: str,
    source_file: str | None,
    codex_run: Any,
    baseline_run: Any,
    excerpt_limit: int,
    targeted_case_limit: int,
    pair_diagnostics_cls: Callable[..., Any],
    llm_stage_map: dict[str, Any],
    load_full_prompt_rows_for_run: Callable[[Any], list[dict[str, Any]]],
    normalize_recipe_spans_to_line_coordinates: Callable[..., list[dict[str, Any]]],
    build_recipe_spans_from_full_prompt_rows: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]]
    ],
    build_line_prediction_view: Callable[..., Any],
    line_context: Callable[..., dict[str, str]],
    rate: Callable[[int, int], float | None],
    delta: Callable[[float | None, float | None], float | None],
    confusion_matrix_from_view: Callable[[Any], dict[str, dict[str, int]]],
    delta_confusion_matrix: Callable[..., dict[str, dict[str, int]]],
    prompt_row_stage_key: Callable[[dict[str, Any]], str],
    parse_json_like: Callable[[Any], Any],
    coerce_str_list: Callable[[Any], list[str]],
    upload_bundle_recipe_correction_output_rows: Callable[[Any], list[dict[str, Any]]],
    upload_bundle_recipe_correction_metrics: Callable[[dict[str, Any]], dict[str, Any]],
    is_empty_mapping_value: Callable[[Any], bool],
    first_prompt_block_excerpt: Callable[..., str],
    prompt_case_score: Callable[..., int],
    prompt_row_identity_key: Callable[[dict[str, Any]], tuple[str, str, str]],
    prompt_row_owned_recipe_ids: Callable[[dict[str, Any]], list[str]],
    load_json: Callable[[Path], dict[str, Any]],
    load_llm_manifest_recipe_diagnostics: Callable[..., dict[str, dict[str, Any]]],
    build_preprocess_trace_failure_rows: Callable[..., tuple[list[dict[str, Any]], str]],
    coerce_int: Callable[[Any], int | None],
    nearest_recipe_id_for_line_index: Callable[..., str | None],
    build_intermediate_selected_blocks: Callable[
        [dict[str, Any]], tuple[list[dict[str, Any]], int | None, int | None]
    ],
    upload_bundle_recipe_stages_for_row: Callable[..., list[dict[str, str]]],
    upload_bundle_recipe_correction_output_for_recipe: Callable[..., dict[str, Any]],
    upload_bundle_recipe_correction_input_block_count: Callable[..., int],
    warning_buckets: Callable[[list[str]], list[str]],
    final_recipe_step_count: Callable[[dict[str, Any]], int],
    mapping_count: Callable[[Any], int],
    coerce_bool: Callable[[Any], bool | None],
    coerce_float: Callable[[Any], float | None],
    recipe_short_title: Callable[..., str],
    input_excerpt_for_prompt_row: Callable[..., str],
    upload_bundle_call_inventory_stage_included: Callable[[str | None], bool],
    upload_bundle_extract_call_runtime: Callable[[dict[str, Any]], dict[str, Any]],
    upload_bundle_estimate_call_cost_usd: Callable[..., float | None],
    upload_bundle_call_inventory_stage_rank: Callable[[str | None], int],
    prompt_row_recipe_id: Callable[[dict[str, Any]], str],
    output_excerpt_for_prompt_row: Callable[..., str],
    stage_label: Callable[[str], str],
) -> Any:
    codex_prompt_rows = load_full_prompt_rows_for_run(codex_run)
    recipe_spans = normalize_recipe_spans_to_line_coordinates(
        run_dir=Path(codex_run.run_dir),
        recipe_spans=build_recipe_spans_from_full_prompt_rows(codex_prompt_rows),
    )

    codex_view = build_line_prediction_view(
        run_dir=Path(codex_run.run_dir),
        recipe_spans=recipe_spans,
    )
    baseline_view = build_line_prediction_view(
        run_dir=Path(baseline_run.run_dir),
        recipe_spans=recipe_spans,
    )

    all_line_indices = sorted(
        set(codex_view.gold_label_by_index.keys()) | set(baseline_view.gold_label_by_index.keys())
    )
    line_text_by_index = (
        codex_view.line_text_by_index
        if codex_view.line_text_by_index
        else baseline_view.line_text_by_index
    )

    changed_line_rows: list[dict[str, Any]] = []
    recipe_flip_counts: Counter[str] = Counter()

    region_metrics: dict[str, dict[str, int]] = {
        "inside_active_recipe_span": {
            "line_total": 0,
            "codex_correct": 0,
            "baseline_correct": 0,
        },
        "outside_active_recipe_span": {
            "line_total": 0,
            "codex_correct": 0,
            "baseline_correct": 0,
        },
    }
    per_recipe_metrics: dict[str, dict[str, int]] = defaultdict(
        lambda: {"line_total": 0, "codex_correct": 0, "baseline_correct": 0}
    )

    for line_index in all_line_indices:
        gold_label = str(
            codex_view.gold_label_by_index.get(
                line_index,
                baseline_view.gold_label_by_index.get(line_index, "OTHER"),
            )
        )
        codex_pred = str(
            codex_view.pred_label_by_index.get(
                line_index,
                codex_view.gold_label_by_index.get(line_index, gold_label),
            )
        )
        baseline_pred = str(
            baseline_view.pred_label_by_index.get(
                line_index,
                baseline_view.gold_label_by_index.get(line_index, gold_label),
            )
        )

        recipe_id = codex_view.recipe_id_by_index.get(line_index)
        span_region = codex_view.recipe_span_by_index.get(
            line_index, "outside_active_recipe_span"
        )
        if span_region not in region_metrics:
            span_region = "outside_active_recipe_span"
        region_metrics[span_region]["line_total"] += 1
        if codex_pred == gold_label:
            region_metrics[span_region]["codex_correct"] += 1
        if baseline_pred == gold_label:
            region_metrics[span_region]["baseline_correct"] += 1

        if recipe_id:
            per_recipe_metrics[recipe_id]["line_total"] += 1
            if codex_pred == gold_label:
                per_recipe_metrics[recipe_id]["codex_correct"] += 1
            if baseline_pred == gold_label:
                per_recipe_metrics[recipe_id]["baseline_correct"] += 1

        if codex_pred == baseline_pred:
            continue

        if recipe_id:
            recipe_flip_counts[recipe_id] += 1

        changed_line_rows.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "line_index": line_index,
                "recipe_id": recipe_id,
                "span_region": span_region,
                "gold_label": gold_label,
                "vanilla_pred": baseline_pred,
                "codex_pred": codex_pred,
                **line_context(
                    line_text_by_index=line_text_by_index,
                    line_index=line_index,
                    excerpt_limit=excerpt_limit,
                ),
            }
        )

    region_breakdown: list[dict[str, Any]] = []
    for region_name, payload in region_metrics.items():
        line_total = int(payload["line_total"])
        codex_accuracy = rate(int(payload["codex_correct"]), line_total)
        baseline_accuracy = rate(int(payload["baseline_correct"]), line_total)
        region_breakdown.append(
            {
                "region": region_name,
                "line_total": line_total,
                "codex_correct": int(payload["codex_correct"]),
                "baseline_correct": int(payload["baseline_correct"]),
                "codex_accuracy": codex_accuracy,
                "baseline_accuracy": baseline_accuracy,
                "delta_codex_minus_baseline": delta(codex_accuracy, baseline_accuracy),
            }
        )

    per_recipe_breakdown = [
        {
            "recipe_id": recipe_id,
            "line_total": int(payload["line_total"]),
            "codex_correct": int(payload["codex_correct"]),
            "baseline_correct": int(payload["baseline_correct"]),
            "codex_accuracy": rate(int(payload["codex_correct"]), int(payload["line_total"])),
            "baseline_accuracy": rate(
                int(payload["baseline_correct"]), int(payload["line_total"])
            ),
            "delta_codex_minus_baseline": delta(
                rate(int(payload["codex_correct"]), int(payload["line_total"])),
                rate(int(payload["baseline_correct"]), int(payload["line_total"])),
            ),
            "changed_lines_codex_vs_vanilla": int(recipe_flip_counts.get(recipe_id, 0)),
        }
        for recipe_id, payload in sorted(
            per_recipe_metrics.items(),
            key=lambda item: (
                -int(recipe_flip_counts.get(item[0], 0)),
                -int(item[1]["line_total"]),
                item[0],
            ),
        )
    ]

    codex_confusion = confusion_matrix_from_view(codex_view)
    baseline_confusion = confusion_matrix_from_view(baseline_view)
    confusion_delta = delta_confusion_matrix(
        codex_confusion=codex_confusion,
        baseline_confusion=baseline_confusion,
    )

    targeted_prompt_candidates: list[dict[str, Any]] = []
    for row in codex_prompt_rows:
        stage_key = prompt_row_stage_key(row)
        if stage_key not in llm_stage_map:
            continue
        parsed_response = parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = coerce_str_list(parsed_response.get("warnings"))
        empty_mapping = False
        if stage_key == "recipe_refine":
            correction_outputs = upload_bundle_recipe_correction_output_rows(parsed_response)
            if correction_outputs:
                warnings = []
                empty_mapping = False
                for output_row in correction_outputs:
                    metrics = upload_bundle_recipe_correction_metrics(output_row)
                    warnings.extend(metrics["warnings"])
                    empty_mapping = empty_mapping or bool(metrics["empty_mapping"])
            else:
                empty_mapping = (
                    "ingredient_step_mapping" in parsed_response
                    and is_empty_mapping_value(parsed_response.get("ingredient_step_mapping"))
                )
        else:
            empty_mapping = (
                "ingredient_step_mapping" in parsed_response
                and is_empty_mapping_value(parsed_response.get("ingredient_step_mapping"))
            )
        recipe_id = str(row.get("recipe_id") or "").strip()
        changed_lines_for_recipe = int(recipe_flip_counts.get(recipe_id, 0))
        if not warnings and not empty_mapping and changed_lines_for_recipe <= 0:
            continue

        call_id = str(row.get("call_id") or "").strip()
        targeted_prompt_candidates.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "stage_key": stage_key,
                "stage_label": stage_label(stage_key),
                "call_id": call_id,
                "recipe_id": recipe_id or None,
                "changed_lines_for_recipe": changed_lines_for_recipe,
                "warning_count": len(warnings),
                "warnings": warnings,
                "empty_ingredient_step_mapping": empty_mapping,
                "input_excerpt": first_prompt_block_excerpt(
                    row,
                    excerpt_limit=excerpt_limit,
                ),
                "score": prompt_case_score(
                    stage_key=stage_key,
                    warnings_count=len(warnings),
                    empty_mapping=empty_mapping,
                    changed_lines_for_recipe=changed_lines_for_recipe,
                ),
            }
        )

    targeted_prompt_candidates.sort(
        key=lambda row: (
            -int(row.get("score") or 0),
            -int(row.get("changed_lines_for_recipe") or 0),
            -int(row.get("warning_count") or 0),
            str(row.get("stage_key") or ""),
            str(row.get("call_id") or ""),
        )
    )

    targeted_prompt_case_rows: list[dict[str, Any]] = []
    seen_prompt_case_keys: set[tuple[str, str]] = set()
    for row in targeted_prompt_candidates:
        dedupe_key = (str(row.get("stage_key") or ""), str(row.get("call_id") or ""))
        if dedupe_key in seen_prompt_case_keys:
            continue
        seen_prompt_case_keys.add(dedupe_key)
        targeted_prompt_case_rows.append(
            {
                key: value
                for key, value in row.items()
                if key != "score"
            }
        )
        if len(targeted_prompt_case_rows) >= targeted_case_limit:
            break

    stage_rows_by_recipe: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in sorted(codex_prompt_rows, key=prompt_row_identity_key):
        stage_key = prompt_row_stage_key(row)
        if stage_key not in {
            "recipe_build_intermediate",
            "recipe_refine",
            "recipe_build_final",
        }:
            continue
        for recipe_id in prompt_row_owned_recipe_ids(row):
            if stage_key not in stage_rows_by_recipe[recipe_id]:
                stage_rows_by_recipe[recipe_id][stage_key] = row

    run_manifest_path = Path(codex_run.run_dir) / "run_manifest.json"
    run_manifest = load_json(run_manifest_path) if run_manifest_path.is_file() else {}
    manifest_diagnostics_by_recipe = load_llm_manifest_recipe_diagnostics(
        run_dir=Path(codex_run.run_dir),
        run_manifest=run_manifest,
    )
    preprocess_rows, preprocess_status = build_preprocess_trace_failure_rows(
        run_dir=Path(codex_run.run_dir),
        run_manifest=run_manifest,
        full_prompt_rows=codex_prompt_rows,
        excerpt_limit=excerpt_limit,
    )
    outside_span_trace_rows: list[dict[str, Any]] = []
    outside_span_wrong_counts: Counter[str] = Counter()
    outside_span_trace_statuses_by_recipe: dict[str, Counter[str]] = defaultdict(Counter)
    for row in preprocess_rows:
        if str(row.get("span_region") or "") != "outside_active_recipe_span":
            continue
        line_index = coerce_int(row.get("line_index"))
        if line_index is None:
            continue
        recipe_id = str(row.get("recipe_id") or "").strip()
        if not recipe_id:
            inferred_recipe_id = nearest_recipe_id_for_line_index(
                line_index=line_index,
                recipe_spans=recipe_spans,
            )
            recipe_id = inferred_recipe_id or "unknown_recipe"
        trace_status = str(row.get("trace_status") or "")
        row_warning_buckets = coerce_str_list(row.get("warning_buckets"))
        outside_span_trace_rows.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "call_id": row.get("call_id"),
                "recipe_id": recipe_id,
                "line_index": line_index,
                "gold_label": row.get("gold_label"),
                "pred_label": row.get("pred_label"),
                "trace_status": trace_status,
                "warning_buckets": row_warning_buckets,
                "raw_block_stable_key": row.get("raw_block_stable_key"),
                "raw_block_excerpt": row.get("raw_block_excerpt"),
                "prompt_candidate_block_excerpt": row.get("prompt_candidate_block_excerpt"),
            }
        )
        outside_span_wrong_counts[recipe_id] += 1
        if trace_status:
            outside_span_trace_statuses_by_recipe[recipe_id][trace_status] += 1

    recipe_ids: set[str] = set(per_recipe_metrics.keys())
    recipe_ids.update(stage_rows_by_recipe.keys())
    recipe_ids.update(
        str(span.get("recipe_id") or "") for span in recipe_spans if span.get("recipe_id")
    )
    recipe_ids.update(outside_span_wrong_counts.keys())
    recipe_ids.update(manifest_diagnostics_by_recipe.keys())
    recipe_ids.discard("")
    recipe_triage_rows: list[dict[str, Any]] = []
    for recipe_id in sorted(recipe_ids):
        metrics = per_recipe_metrics.get(
            recipe_id,
            {"line_total": 0, "codex_correct": 0, "baseline_correct": 0},
        )
        line_total = int(metrics.get("line_total") or 0)
        codex_correct = int(metrics.get("codex_correct") or 0)
        baseline_correct = int(metrics.get("baseline_correct") or 0)
        codex_accuracy = rate(codex_correct, line_total)
        baseline_accuracy = rate(baseline_correct, line_total)
        delta_codex_minus_baseline = delta(codex_accuracy, baseline_accuracy)

        build_intermediate_row = stage_rows_by_recipe.get(recipe_id, {}).get(
            "recipe_build_intermediate"
        )
        correction_row = stage_rows_by_recipe.get(recipe_id, {}).get("recipe_refine")
        build_final_row = stage_rows_by_recipe.get(recipe_id, {}).get("recipe_build_final")
        manifest_diagnostics = manifest_diagnostics_by_recipe.get(recipe_id, {})
        build_intermediate_start_block_index: int | None = None
        build_intermediate_end_block_index: int | None = None
        build_intermediate_selected_block_count = 0
        build_intermediate_blocks: list[dict[str, Any]] = []

        if isinstance(build_intermediate_row, dict):
            (
                build_intermediate_blocks,
                build_intermediate_start_block_index,
                build_intermediate_end_block_index,
            ) = build_intermediate_selected_blocks(
                build_intermediate_row
            )
            build_intermediate_selected_block_count = len(build_intermediate_blocks)
        correction_call_id = (
            str(correction_row.get("call_id") or "") if isinstance(correction_row, dict) else ""
        )
        correction_input_payload = (
            parse_json_like(correction_row.get("request_input_payload"))
            if isinstance(correction_row, dict)
            else None
        )
        correction_input_payload = (
            correction_input_payload if isinstance(correction_input_payload, dict) else {}
        )
        parsed_correction = (
            upload_bundle_recipe_correction_output_for_recipe(
                correction_row.get("parsed_response"),
                recipe_id=recipe_id,
            )
            if isinstance(correction_row, dict)
            else {}
        )
        correction_input_block_count = int(
            coerce_int(manifest_diagnostics.get("correction_input_block_count"))
            or upload_bundle_recipe_correction_input_block_count(
                correction_input_payload,
                recipe_id=recipe_id,
            )
        )
        correction_metrics = upload_bundle_recipe_correction_metrics(parsed_correction)
        correction_warnings = list(correction_metrics["warnings"])
        correction_warning_count = int(
            coerce_int(manifest_diagnostics.get("correction_warning_count"))
            or len(correction_warnings)
        )
        correction_warning_buckets = warning_buckets(correction_warnings)
        correction_ingredient_count = int(
            coerce_int(manifest_diagnostics.get("correction_ingredient_count"))
            or int(correction_metrics["ingredient_count"])
        )
        correction_step_count = int(
            coerce_int(manifest_diagnostics.get("correction_step_count"))
            or int(correction_metrics["step_count"])
        )
        correction_mapping_value = parsed_correction.get("ingredient_step_mapping")
        correction_mapping_count = int(
            coerce_int(manifest_diagnostics.get("correction_mapping_count"))
            or int(correction_metrics["mapping_count"])
            or 0
        )
        correction_empty_mapping = bool(
            manifest_diagnostics.get("correction_empty_mapping")
        ) or is_empty_mapping_value(correction_mapping_value)
        correction_empty_output = bool(
            manifest_diagnostics.get("correction_empty_output")
        ) or bool(correction_metrics["empty_output"])
        build_final_parsed = (
            parse_json_like(build_final_row.get("parsed_response"))
            if isinstance(build_final_row, dict)
            else None
        )
        build_final_parsed = build_final_parsed if isinstance(build_final_parsed, dict) else {}
        final_recipe_step_count_value = final_recipe_step_count(build_final_parsed)
        final_recipe_mapping_count = mapping_count(
            build_final_parsed.get("ingredient_step_mapping")
        )
        final_recipe_empty_mapping = bool(build_final_row) and is_empty_mapping_value(
            build_final_parsed.get("ingredient_step_mapping")
        )
        final_recipe_warnings = coerce_str_list(build_final_parsed.get("warnings"))
        final_recipe_warning_count = len(final_recipe_warnings)
        final_recipe_warning_buckets = warning_buckets(final_recipe_warnings)

        outside_span_status_counter = outside_span_trace_statuses_by_recipe.get(recipe_id, Counter())
        outside_span_trace_status_top = ""
        if outside_span_status_counter:
            outside_span_trace_status_top = sorted(
                outside_span_status_counter.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]

        recipe_pipeline_id = str(codex_run.llm_recipe_pipeline or "").strip()
        recipe_stages = upload_bundle_recipe_stages_for_row(
            recipe_pipeline_id=recipe_pipeline_id,
            correction_call_id=correction_call_id,
        )
        build_intermediate_status = str(manifest_diagnostics.get("build_intermediate_status") or "")
        correction_status = str(manifest_diagnostics.get("correction_status") or "")
        build_final_status = str(manifest_diagnostics.get("build_final_status") or "")
        final_mapping_status = str(manifest_diagnostics.get("final_mapping_status") or "")
        final_mapping_reason = str(manifest_diagnostics.get("final_mapping_reason") or "")
        structural_status = str(manifest_diagnostics.get("structural_status") or "")
        structural_reason_codes = coerce_str_list(
            manifest_diagnostics.get("structural_reason_codes")
        )
        recipe_warning_count = int(coerce_int(manifest_diagnostics.get("recipe_warning_count")) or 0)
        recipe_error_count = int(coerce_int(manifest_diagnostics.get("recipe_error_count")) or 0)

        line_total_effective = (
            line_total
            if line_total > 0
            else (correction_input_block_count or build_intermediate_selected_block_count)
        )
        short_title = recipe_short_title(
            recipe_id=recipe_id,
            recipe_spans=recipe_spans,
            correction_row=correction_row,
        )
        recipe_triage_rows.append(
            {
                "source_key": source_key,
                "source_file": source_file,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
                "recipe_pipeline_id": recipe_pipeline_id,
                "recipe_stages": recipe_stages,
                "selection_hint_preprocess_status": preprocess_status,
                "recipe_id": recipe_id,
                "short_title": short_title,
                "line_total": line_total_effective,
                "changed_lines_codex_vs_baseline": int(recipe_flip_counts.get(recipe_id, 0)),
                "codex_accuracy": codex_accuracy,
                "baseline_accuracy": baseline_accuracy,
                "delta_codex_minus_baseline": delta_codex_minus_baseline,
                "correction_call_id": correction_call_id,
                "correction_input_block_count": correction_input_block_count,
                "correction_warning_count": correction_warning_count,
                "correction_warning_buckets": correction_warning_buckets,
                "correction_ingredient_count": correction_ingredient_count,
                "correction_step_count": correction_step_count,
                "correction_mapping_count": correction_mapping_count,
                "correction_empty_mapping": correction_empty_mapping,
                "correction_empty_output": correction_empty_output,
                "build_intermediate_status": build_intermediate_status,
                "correction_status": correction_status,
                "build_final_status": build_final_status,
                "final_mapping_status": final_mapping_status,
                "final_mapping_reason": final_mapping_reason,
                "structural_status": structural_status,
                "structural_reason_codes": structural_reason_codes,
                "recipe_warning_count": recipe_warning_count,
                "recipe_error_count": recipe_error_count,
                "build_intermediate_call_id": str(build_intermediate_row.get("call_id") or "")
                if isinstance(build_intermediate_row, dict)
                else "",
                "correction_call_id": correction_call_id,
                "build_final_call_id": str(build_final_row.get("call_id") or "")
                if isinstance(build_final_row, dict)
                else "",
                "build_intermediate_start_block_index": build_intermediate_start_block_index,
                "build_intermediate_end_block_index": build_intermediate_end_block_index,
                "build_intermediate_selected_block_count": build_intermediate_selected_block_count,
                "correction_input_block_count": correction_input_block_count,
                "build_intermediate_missing_block_count": 0,
                "build_intermediate_extra_block_count": 0,
                "final_recipe_step_count": final_recipe_step_count_value,
                "final_recipe_mapping_count": final_recipe_mapping_count,
                "final_recipe_empty_mapping": final_recipe_empty_mapping,
                "final_recipe_warning_count": final_recipe_warning_count,
                "final_recipe_warning_buckets": final_recipe_warning_buckets,
                "build_intermediate_clamped_block_loss_count": 0,
                "build_intermediate_clamped_block_loss_ratio": None,
                "correction_degradation_reasons": [],
                "correction_degradation_severity": "",
                "correction_promotion_policy": "",
                "build_final_execution_mode": "",
                "build_final_routing_reason": "",
                "build_final_fallback_reason": "",
                "transport_mismatch": coerce_bool(
                    manifest_diagnostics.get("transport_mismatch")
                ),
                "transport_mismatch_reasons": coerce_str_list(
                    manifest_diagnostics.get("transport_mismatch_reasons")
                ),
                "transport_effective_to_payload_coverage_ratio": coerce_float(
                    manifest_diagnostics.get("transport_effective_to_payload_coverage_ratio")
                ),
                "evidence_split_quantity_lines": int(
                    coerce_int(manifest_diagnostics.get("evidence_split_quantity_lines")) or 0
                ),
                "evidence_dropped_page_markers": int(
                    coerce_int(manifest_diagnostics.get("evidence_dropped_page_markers")) or 0
                ),
                "evidence_folded_page_markers": int(
                    coerce_int(manifest_diagnostics.get("evidence_folded_page_markers")) or 0
                ),
                "outside_span_wrong_line_count": int(outside_span_wrong_counts.get(recipe_id, 0)),
                "outside_span_trace_status_top": outside_span_trace_status_top,
                "raw_block_window_excerpt": input_excerpt_for_prompt_row(
                    correction_row,
                    excerpt_limit=excerpt_limit,
                )
                if isinstance(correction_row, dict)
                else "",
            }
        )

    call_inventory_rows: list[dict[str, Any]] = []
    for row in sorted(codex_prompt_rows, key=prompt_row_identity_key):
        stage_key = prompt_row_stage_key(row)
        if not upload_bundle_call_inventory_stage_included(stage_key):
            continue
        parsed_response = parse_json_like(row.get("parsed_response"))
        parsed_response = parsed_response if isinstance(parsed_response, dict) else {}
        warnings = coerce_str_list(parsed_response.get("warnings"))
        row_warning_buckets = warning_buckets(warnings)

        input_block_count = 0
        extracted_ingredient_count = 0
        step_count = 0
        mapping_count_value = 0
        request_input_payload = parse_json_like(row.get("request_input_payload"))
        request_input_payload = (
            request_input_payload if isinstance(request_input_payload, dict) else {}
        )
        if stage_key == "recipe_refine":
            correction_outputs = upload_bundle_recipe_correction_output_rows(parsed_response)
            input_block_count = upload_bundle_recipe_correction_input_block_count(
                request_input_payload
            )
            if correction_outputs:
                warnings = []
                extracted_ingredient_count = 0
                step_count = 0
                mapping_count_value = 0
                for output_row in correction_outputs:
                    metrics = upload_bundle_recipe_correction_metrics(output_row)
                    warnings.extend(metrics["warnings"])
                    extracted_ingredient_count += int(metrics["ingredient_count"])
                    step_count += int(metrics["step_count"])
                    mapping_count_value += int(metrics["mapping_count"])
                row_warning_buckets = warning_buckets(warnings)
            else:
                canonical_recipe = (
                    parsed_response.get("canonical_recipe")
                    if isinstance(parsed_response.get("canonical_recipe"), dict)
                    else {}
                )
                extracted_ingredient_count = len(canonical_recipe.get("ingredients") or [])
                step_count = len(canonical_recipe.get("steps") or [])
                mapping_count_value = mapping_count(parsed_response.get("ingredient_step_mapping"))
        elif stage_key == "line_role":
            row_payload = request_input_payload.get("rows")
            input_block_count = len(row_payload) if isinstance(row_payload, list) else 0
        elif stage_key == "recipe_build_final":
            draft_payload = parse_json_like(parsed_response.get("draft_v1"))
            draft_payload = draft_payload if isinstance(draft_payload, dict) else {}
            steps_payload = draft_payload.get("steps")
            step_count = len(steps_payload) if isinstance(steps_payload, list) else 0
            mapping_count_value = mapping_count(parsed_response.get("ingredient_step_mapping"))

        runtime_payload = upload_bundle_extract_call_runtime(row)
        observed_cost_usd = coerce_float(runtime_payload.get("cost_usd"))
        estimated_cost_usd = (
            observed_cost_usd
            if observed_cost_usd is not None
            else upload_bundle_estimate_call_cost_usd(
                tokens_input=coerce_int(runtime_payload.get("tokens_input")),
                tokens_cached_input=coerce_int(runtime_payload.get("tokens_cached_input")),
                tokens_output=coerce_int(runtime_payload.get("tokens_output")),
            )
        )

        call_inventory_rows.append(
            {
                "run_id": codex_run.run_id,
                "source_key": source_key,
                "source_file": source_file,
                "recipe_id": prompt_row_recipe_id(row),
                "stage_key": stage_key,
                "stage_label": stage_label(stage_key),
                "call_id": str(row.get("call_id") or ""),
                "timestamp_utc": str(row.get("timestamp_utc") or ""),
                "model": str(row.get("model") or ""),
                "input_block_count": input_block_count,
                "warning_count": len(warnings),
                "warning_buckets": row_warning_buckets,
                "extracted_ingredient_count": extracted_ingredient_count,
                "extracted_instruction_count": step_count,
                "step_count": step_count,
                "mapping_count": mapping_count_value,
                "input_excerpt": input_excerpt_for_prompt_row(row, excerpt_limit=excerpt_limit),
                "output_excerpt": output_excerpt_for_prompt_row(row, excerpt_limit=excerpt_limit),
                "duration_ms": coerce_int(runtime_payload.get("duration_ms")),
                "tokens_input": coerce_int(runtime_payload.get("tokens_input")),
                "tokens_cached_input": coerce_int(runtime_payload.get("tokens_cached_input")),
                "tokens_output": coerce_int(runtime_payload.get("tokens_output")),
                "tokens_reasoning": coerce_int(runtime_payload.get("tokens_reasoning")),
                "tokens_total": coerce_int(runtime_payload.get("tokens_total")),
                "cost_usd": observed_cost_usd,
                "estimated_cost_usd": estimated_cost_usd,
                "cost_source": (
                    "observed_telemetry"
                    if observed_cost_usd is not None
                    else (
                        "estimated_from_tokens_default_pricing"
                        if estimated_cost_usd is not None
                        else None
                    )
                ),
                "retry_attempt": coerce_int(runtime_payload.get("attempt_index")),
                "runtime_status": runtime_payload.get("status"),
                "_stage_rank": upload_bundle_call_inventory_stage_rank(stage_key),
            }
        )
    call_inventory_rows.sort(
        key=lambda row: (
            str(row.get("recipe_id") or ""),
            int(row.get("_stage_rank") or 99),
            str(row.get("call_id") or ""),
            str(row.get("timestamp_utc") or ""),
        )
    )
    for row in call_inventory_rows:
        row.pop("_stage_rank", None)

    pair_breakdown = {
        "source_key": source_key,
        "source_file": source_file,
        "codex_run_id": codex_run.run_id,
        "baseline_run_id": baseline_run.run_id,
        "recipe_span_count": len(recipe_spans),
        "changed_lines_total": len(changed_line_rows),
        "region_breakdown": region_breakdown,
        "per_recipe_breakdown": per_recipe_breakdown,
    }

    return pair_diagnostics_cls(
        changed_line_rows=changed_line_rows,
        pair_breakdown=pair_breakdown,
        confusion_matrix_codex=codex_confusion,
        confusion_matrix_baseline=baseline_confusion,
        confusion_delta_codex_minus_baseline=confusion_delta,
        targeted_prompt_case_rows=targeted_prompt_case_rows,
        recipe_triage_rows=recipe_triage_rows,
        call_inventory_rows=call_inventory_rows,
        outside_span_trace_rows=outside_span_trace_rows,
    )


def _build_comparison_summary(
    *,
    records: list[Any],
    excerpt_limit: int,
    targeted_prompt_case_limit: int,
    build_pair_diagnostics: Callable[..., Any],
    nearest_baseline: Callable[[Any, list[Any]], Any],
    delta: Callable[[float | None, float | None], float | None],
    config_differences: Callable[[dict[str, Any], dict[str, Any]], dict[str, dict[str, Any]]],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    by_source: dict[str, list[Any]] = defaultdict(list)
    for record in records:
        by_source[record.source_key].append(record)

    pairs: list[dict[str, Any]] = []
    unpaired_codex: list[dict[str, Any]] = []
    unpaired_baseline: list[dict[str, Any]] = []
    changed_line_rows: list[dict[str, Any]] = []
    pair_breakdown_rows: list[dict[str, Any]] = []
    targeted_prompt_case_rows: list[dict[str, Any]] = []
    recipe_triage_rows: list[dict[str, Any]] = []
    call_inventory_rows: list[dict[str, Any]] = []
    outside_span_trace_rows: list[dict[str, Any]] = []

    for source_key in sorted(by_source.keys()):
        runs = by_source[source_key]
        codex_runs = [run for run in runs if run.codex_enabled]
        baseline_runs = [run for run in runs if not run.codex_enabled]

        if codex_runs and baseline_runs:
            for codex_run in sorted(
                codex_runs,
                key=lambda run: (run.run_timestamp or datetime.min, run.run_id),
                reverse=True,
            ):
                baseline = nearest_baseline(codex_run, baseline_runs)
                pair_diagnostics = build_pair_diagnostics(
                    source_key=source_key,
                    source_file=codex_run.source_file or baseline.source_file,
                    codex_run=codex_run,
                    baseline_run=baseline,
                    excerpt_limit=excerpt_limit,
                    targeted_case_limit=targeted_prompt_case_limit,
                )
                changed_line_rows.extend(pair_diagnostics.changed_line_rows)
                pair_breakdown_rows.append(pair_diagnostics.pair_breakdown)
                targeted_prompt_case_rows.extend(pair_diagnostics.targeted_prompt_case_rows)
                recipe_triage_rows.extend(pair_diagnostics.recipe_triage_rows)
                call_inventory_rows.extend(pair_diagnostics.call_inventory_rows)
                outside_span_trace_rows.extend(pair_diagnostics.outside_span_trace_rows)
                pairs.append(
                    {
                        "source_key": source_key,
                        "source_file": codex_run.source_file or baseline.source_file,
                        "codex_run": {
                            "run_id": codex_run.run_id,
                            "output_subdir": codex_run.output_subdir,
                            "llm_recipe_pipeline": codex_run.llm_recipe_pipeline,
                            "atomic_block_splitter": codex_run.atomic_block_splitter,
                            "line_role_pipeline": codex_run.line_role_pipeline,
                            "overall_line_accuracy": codex_run.metric_overall_line_accuracy,
                            "macro_f1_excluding_other": codex_run.metric_macro_f1_excluding_other,
                            "practical_f1": codex_run.metric_practical_f1,
                            "worst_label_recall": codex_run.worst_label_recall,
                        },
                        "baseline_run": {
                            "run_id": baseline.run_id,
                            "output_subdir": baseline.output_subdir,
                            "llm_recipe_pipeline": baseline.llm_recipe_pipeline,
                            "atomic_block_splitter": baseline.atomic_block_splitter,
                            "line_role_pipeline": baseline.line_role_pipeline,
                            "overall_line_accuracy": baseline.metric_overall_line_accuracy,
                            "macro_f1_excluding_other": baseline.metric_macro_f1_excluding_other,
                            "practical_f1": baseline.metric_practical_f1,
                            "worst_label_recall": baseline.worst_label_recall,
                        },
                        "delta_codex_minus_baseline": {
                            "overall_line_accuracy": delta(
                                codex_run.metric_overall_line_accuracy,
                                baseline.metric_overall_line_accuracy,
                            ),
                            "macro_f1_excluding_other": delta(
                                codex_run.metric_macro_f1_excluding_other,
                                baseline.metric_macro_f1_excluding_other,
                            ),
                            "practical_f1": delta(
                                codex_run.metric_practical_f1,
                                baseline.metric_practical_f1,
                            ),
                        },
                        "run_config_differences": config_differences(
                            codex_run.config_snapshot,
                            baseline.config_snapshot,
                        ),
                        "changed_line_count": len(pair_diagnostics.changed_line_rows),
                        "confusion_matrix": {
                            "codex": pair_diagnostics.confusion_matrix_codex,
                            "baseline": pair_diagnostics.confusion_matrix_baseline,
                            "delta_codex_minus_baseline": pair_diagnostics.confusion_delta_codex_minus_baseline,
                        },
                    }
                )
            continue

        if codex_runs:
            for codex_run in codex_runs:
                unpaired_codex.append(
                    {
                        "source_key": source_key,
                        "source_file": codex_run.source_file,
                        "run_id": codex_run.run_id,
                        "output_subdir": codex_run.output_subdir,
                        "llm_recipe_pipeline": codex_run.llm_recipe_pipeline,
                        "atomic_block_splitter": codex_run.atomic_block_splitter,
                        "line_role_pipeline": codex_run.line_role_pipeline,
                    }
                )
        if baseline_runs:
            for baseline in baseline_runs:
                unpaired_baseline.append(
                    {
                        "source_key": source_key,
                        "source_file": baseline.source_file,
                        "run_id": baseline.run_id,
                        "output_subdir": baseline.output_subdir,
                        "llm_recipe_pipeline": baseline.llm_recipe_pipeline,
                        "atomic_block_splitter": baseline.atomic_block_splitter,
                        "line_role_pipeline": baseline.line_role_pipeline,
                    }
                )

    summary = {
        "pairing_rule": (
            "Within each source_key group, each codex-enabled run is paired with the "
            "nearest baseline (llm_recipe_pipeline=off/none/empty) by timestamp."
        ),
        "pairs": pairs,
        "unpaired_codex_runs": unpaired_codex,
        "unpaired_baseline_runs": unpaired_baseline,
    }
    return (
        summary,
        changed_line_rows,
        pair_breakdown_rows,
        targeted_prompt_case_rows,
        recipe_triage_rows,
        call_inventory_rows,
        outside_span_trace_rows,
    )


def _select_targeted_prompt_cases(
    *,
    rows: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            -int(row.get("changed_lines_for_recipe") or 0),
            -int(row.get("warning_count") or 0),
            -int(bool(row.get("empty_ingredient_step_mapping"))),
            str(row.get("stage_key") or ""),
            str(row.get("call_id") or ""),
        ),
    )
    selected: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for row in sorted_rows:
        dedupe_key = (
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
            str(row.get("stage_key") or ""),
            str(row.get("call_id") or ""),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def _write_targeted_prompt_cases_markdown(
    *,
    output_path: Path,
    rows: list[dict[str, Any]],
    excerpt: Callable[..., str],
) -> None:
    lines = [
        "# Targeted Prompt Cases",
        "",
        "Deterministic high-signal prompt cases selected from codex runs.",
        "Selection preference: higher changed-line impact, then warning-heavy/empty-mapping cases.",
        "",
    ]
    if not rows:
        lines.append("No targeted prompt cases were selected.")
        lines.append("")
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return

    for index, row in enumerate(rows, start=1):
        warnings = row.get("warnings")
        warning_rows = warnings if isinstance(warnings, list) else []
        warning_summary = (
            "; ".join(excerpt(str(item), max_len=220) for item in warning_rows[:3])
            if warning_rows
            else "none"
        )
        lines.extend(
            [
                f"## Case {index}",
                f"- source_key: `{row.get('source_key')}`",
                f"- codex_run_id: `{row.get('codex_run_id')}`",
                f"- baseline_run_id: `{row.get('baseline_run_id')}`",
                f"- stage/call: `{row.get('stage_key')}` / `{row.get('call_id')}`",
                f"- recipe_id: `{row.get('recipe_id')}`",
                f"- changed_lines_for_recipe: {row.get('changed_lines_for_recipe')}",
                f"- warning_count: {row.get('warning_count')}",
                (
                    "- empty_ingredient_step_mapping: true"
                    if bool(row.get("empty_ingredient_step_mapping"))
                    else "- empty_ingredient_step_mapping: false"
                ),
                f"- warning_summary: {warning_summary}",
                f"- input_excerpt: {excerpt(str(row.get('input_excerpt') or ''), max_len=320)}",
                "",
            ]
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")


def _aggregate_region_accuracy(
    pair_breakdown_rows: list[dict[str, Any]],
    *,
    coerce_int: Callable[[Any], int | None],
    rate: Callable[[int, int], float | None],
) -> tuple[float | None, float | None, float | None]:
    totals: dict[str, dict[str, int]] = {
        "inside_active_recipe_span": {"line_total": 0, "codex_correct": 0},
        "outside_active_recipe_span": {"line_total": 0, "codex_correct": 0},
    }
    for pair_row in pair_breakdown_rows:
        region_rows = pair_row.get("region_breakdown")
        if not isinstance(region_rows, list):
            continue
        for region_row in region_rows:
            if not isinstance(region_row, dict):
                continue
            region = str(region_row.get("region") or "")
            if region not in totals:
                continue
            totals[region]["line_total"] += int(coerce_int(region_row.get("line_total")) or 0)
            totals[region]["codex_correct"] += int(
                coerce_int(region_row.get("codex_correct")) or 0
            )

    inside_accuracy = rate(
        totals["inside_active_recipe_span"]["codex_correct"],
        totals["inside_active_recipe_span"]["line_total"],
    )
    outside_accuracy = rate(
        totals["outside_active_recipe_span"]["codex_correct"],
        totals["outside_active_recipe_span"]["line_total"],
    )
    if inside_accuracy is None or outside_accuracy is None:
        gap = None
    else:
        gap = inside_accuracy - outside_accuracy
    return inside_accuracy, outside_accuracy, gap


def _aggregate_confusion_deltas(
    comparison_summary: dict[str, Any],
    *,
    coerce_int: Callable[[Any], int | None],
    top_k: int = 8,
) -> list[dict[str, Any]]:
    pairs = comparison_summary.get("pairs")
    if not isinstance(pairs, list):
        return []
    counter: Counter[tuple[str, str]] = Counter()
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        confusion = pair.get("confusion_matrix")
        if not isinstance(confusion, dict):
            continue
        delta_matrix = confusion.get("delta_codex_minus_baseline")
        if not isinstance(delta_matrix, dict):
            continue
        for gold_label, pred_counts in delta_matrix.items():
            if not isinstance(gold_label, str) or not isinstance(pred_counts, dict):
                continue
            for pred_label, count_raw in pred_counts.items():
                if not isinstance(pred_label, str):
                    continue
                count = coerce_int(count_raw)
                if count is None or count == 0:
                    continue
                counter[(gold_label, pred_label)] += count
    rows = [
        {"gold_label": gold_label, "pred_label": pred_label, "delta_count": count}
        for (gold_label, pred_label), count in counter.items()
    ]
    rows.sort(
        key=lambda row: (
            -abs(int(row.get("delta_count") or 0)),
            str(row.get("gold_label") or ""),
            str(row.get("pred_label") or ""),
        )
    )
    return rows[:top_k]


def _build_warning_and_trace_summary(
    *,
    call_inventory_rows: list[dict[str, Any]],
    recipe_triage_rows: list[dict[str, Any]],
    outside_span_trace_rows: list[dict[str, Any]],
    coerce_int: Callable[[Any], int | None],
    coerce_str_list: Callable[[Any], list[str]],
    upload_bundle_status_is_problem: Callable[[Any], bool],
    counter_to_sorted_dict: Callable[[Counter[str]], dict[str, int]],
) -> dict[str, Any]:
    warnings_by_stage: Counter[str] = Counter()
    warning_buckets: Counter[str] = Counter()
    for row in call_inventory_rows:
        stage_key = str(row.get("stage_key") or "")
        warning_count = int(coerce_int(row.get("warning_count")) or 0)
        warnings_by_stage[stage_key] += warning_count
        for bucket in coerce_str_list(row.get("warning_buckets")):
            warning_buckets[bucket] += 1

    outside_span_trace_status_counts: Counter[str] = Counter()
    outside_span_warning_bucket_counts: Counter[str] = Counter()
    for row in outside_span_trace_rows:
        trace_status = str(row.get("trace_status") or "")
        if trace_status:
            outside_span_trace_status_counts[trace_status] += 1
        for bucket in coerce_str_list(row.get("warning_buckets")):
            outside_span_warning_bucket_counts[bucket] += 1

    correction_empty_mapping_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("correction_empty_mapping"))
    )
    correction_empty_output_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("correction_empty_output"))
    )
    correction_empty_mapping_with_nonempty_output_count = sum(
        1
        for row in recipe_triage_rows
        if bool(row.get("correction_empty_mapping")) and not bool(row.get("correction_empty_output"))
    )
    final_recipe_empty_mapping_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("final_recipe_empty_mapping"))
    )
    recipe_warning_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if int(coerce_int(row.get("recipe_warning_count")) or 0) > 0
    )
    structural_problem_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if str(row.get("structural_status") or "").strip().lower()
        not in {"", "ok", "none"}
    )
    transport_mismatch_recipe_count = sum(
        1 for row in recipe_triage_rows if bool(row.get("transport_mismatch"))
    )
    build_intermediate_clamped_loss_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if int(coerce_int(row.get("build_intermediate_clamped_block_loss_count")) or 0) > 0
    )
    correction_degraded_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if coerce_str_list(row.get("correction_degradation_reasons"))
        or upload_bundle_status_is_problem(row.get("correction_status"))
    )
    build_final_fallback_recipe_count = sum(
        1
        for row in recipe_triage_rows
        if str(row.get("build_final_fallback_reason") or "").strip()
        or upload_bundle_status_is_problem(row.get("build_final_status"))
    )

    build_intermediate_status_counts: Counter[str] = Counter()
    correction_status_counts: Counter[str] = Counter()
    build_final_status_counts: Counter[str] = Counter()
    final_mapping_status_counts: Counter[str] = Counter()
    structural_status_counts: Counter[str] = Counter()
    correction_degradation_severity_counts: Counter[str] = Counter()
    build_final_execution_mode_counts: Counter[str] = Counter()
    for row in recipe_triage_rows:
        build_intermediate_status = str(row.get("build_intermediate_status") or "").strip() or "missing"
        raw_correction_status = str(row.get("correction_status") or "").strip()
        if raw_correction_status:
            correction_status = raw_correction_status
        elif bool(row.get("correction_empty_output")) and (
            bool(row.get("correction_call_id"))
            or int(coerce_int(row.get("correction_input_block_count")) or 0) > 0
        ):
            correction_status = "empty_output_without_manifest_status"
        elif (
            bool(row.get("correction_call_id"))
            or int(coerce_int(row.get("correction_input_block_count")) or 0) > 0
            or int(coerce_int(row.get("correction_ingredient_count")) or 0) > 0
            or int(coerce_int(row.get("correction_step_count")) or 0) > 0
            or int(coerce_int(row.get("correction_mapping_count")) or 0) > 0
        ):
            correction_status = "nonempty_output_without_manifest_status"
        else:
            correction_status = "missing"
        build_final_status = str(row.get("build_final_status") or "").strip() or "missing"
        final_mapping_status = str(row.get("final_mapping_status") or "").strip() or "missing"
        structural_status = str(row.get("structural_status") or "").strip() or "missing"
        build_intermediate_status_counts[build_intermediate_status] += 1
        correction_status_counts[correction_status] += 1
        build_final_status_counts[build_final_status] += 1
        final_mapping_status_counts[final_mapping_status] += 1
        structural_status_counts[structural_status] += 1

        correction_degradation_severity = str(row.get("correction_degradation_severity") or "").strip()
        if correction_degradation_severity:
            correction_degradation_severity_counts[correction_degradation_severity] += 1
        build_final_execution_mode = str(row.get("build_final_execution_mode") or "").strip()
        if build_final_execution_mode:
            build_final_execution_mode_counts[build_final_execution_mode] += 1

    return {
        "warnings_by_stage": counter_to_sorted_dict(warnings_by_stage),
        "warning_buckets": counter_to_sorted_dict(warning_buckets),
        "correction_empty_mapping_count": correction_empty_mapping_count,
        "correction_empty_mapping_note": (
            "Counts recipes where the correction mapping object was empty. "
            "This does not imply the correction payload itself was empty."
        ),
        "correction_empty_output_count": correction_empty_output_count,
        "correction_empty_mapping_with_nonempty_output_count": (
            correction_empty_mapping_with_nonempty_output_count
        ),
        "final_recipe_empty_mapping_count": final_recipe_empty_mapping_count,
        "recipe_warning_recipe_count": recipe_warning_recipe_count,
        "structural_problem_recipe_count": structural_problem_recipe_count,
        "transport_mismatch_recipe_count": transport_mismatch_recipe_count,
        "build_intermediate_clamped_loss_recipe_count": build_intermediate_clamped_loss_recipe_count,
        "correction_degraded_recipe_count": correction_degraded_recipe_count,
        "build_final_fallback_recipe_count": build_final_fallback_recipe_count,
        "recipe_stage_status_counts": {
            "recipe_build_intermediate": counter_to_sorted_dict(build_intermediate_status_counts),
            "recipe_refine": counter_to_sorted_dict(correction_status_counts),
            "recipe_build_final": counter_to_sorted_dict(build_final_status_counts),
        },
        "correction_degradation_severity_counts": counter_to_sorted_dict(
            correction_degradation_severity_counts
        ),
        "build_final_execution_mode_counts": counter_to_sorted_dict(
            build_final_execution_mode_counts
        ),
        "final_mapping_status_counts": counter_to_sorted_dict(final_mapping_status_counts),
        "structural_status_counts": counter_to_sorted_dict(structural_status_counts),
        "outside_span_wrong_line_count": len(outside_span_trace_rows),
        "outside_span_trace_status_counts": counter_to_sorted_dict(
            outside_span_trace_status_counts
        ),
        "outside_span_warning_bucket_counts": counter_to_sorted_dict(
            outside_span_warning_bucket_counts
        ),
    }
