from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def _starter_changed_rows(
    changed_line_rows: list[dict[str, Any]],
    *,
    coerce_int: Callable[[Any], int | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in changed_line_rows:
        rows.append(
            {
                "recipe_id": str(row.get("recipe_id") or ""),
                "span_region": str(row.get("span_region") or ""),
                "line_index": int(coerce_int(row.get("line_index")) or 0),
                "gold_label": str(row.get("gold_label") or ""),
                "baseline_pred": str(row.get("vanilla_pred") or ""),
                "codex_pred": str(row.get("codex_pred") or ""),
                "previous_line": str(row.get("previous_line") or ""),
                "current_line": str(row.get("current_line") or ""),
                "next_line": str(row.get("next_line") or ""),
            }
        )
    return rows


def _bridge_summary_rows(
    recipe_triage_rows: list[dict[str, Any]],
    *,
    coerce_int: Callable[[Any], int | None],
    coerce_str_list: Callable[[Any], list[str]],
) -> list[dict[str, Any]]:
    return [
        {
            "source_key": str(row.get("source_key") or ""),
            "source_file": str(row.get("source_file") or ""),
            "codex_run_id": str(row.get("codex_run_id") or ""),
            "baseline_run_id": str(row.get("baseline_run_id") or ""),
            "recipe_id": str(row.get("recipe_id") or ""),
            "correction_call_id": str(row.get("correction_call_id") or ""),
            "correction_input_block_count": int(
                coerce_int(row.get("correction_input_block_count")) or 0
            ),
            "correction_warning_count": int(
                coerce_int(row.get("correction_warning_count")) or 0
            ),
            "correction_warning_buckets": coerce_str_list(
                row.get("correction_warning_buckets")
            ),
            "correction_ingredient_count": int(
                coerce_int(row.get("correction_ingredient_count")) or 0
            ),
            "correction_step_count": int(coerce_int(row.get("correction_step_count")) or 0),
            "correction_mapping_count": int(
                coerce_int(row.get("correction_mapping_count")) or 0
            ),
            "correction_empty_mapping": bool(row.get("correction_empty_mapping")),
            "build_intermediate_status": str(row.get("build_intermediate_status") or ""),
            "correction_status": str(row.get("correction_status") or ""),
            "build_final_status": str(row.get("build_final_status") or ""),
            "final_mapping_status": str(row.get("final_mapping_status") or ""),
            "final_mapping_reason": str(row.get("final_mapping_reason") or ""),
            "structural_status": str(row.get("structural_status") or ""),
            "structural_reason_codes": coerce_str_list(row.get("structural_reason_codes")),
            "recipe_warning_count": int(coerce_int(row.get("recipe_warning_count")) or 0),
            "recipe_error_count": int(coerce_int(row.get("recipe_error_count")) or 0),
            "outside_span_wrong_line_count": int(
                coerce_int(row.get("outside_span_wrong_line_count")) or 0
            ),
            "outside_span_trace_status_top": str(row.get("outside_span_trace_status_top") or ""),
        }
        for row in recipe_triage_rows
    ]


def _outside_span_trace_manifest(
    *,
    starter_pack_dir: Path,
    starter_pack_dir_name: str,
    starter_pack_outside_trace_file_name: str,
    outside_span_trace_rows: list[dict[str, Any]],
    pair_breakdown_rows: list[dict[str, Any]],
    sample_limit: int,
    coerce_int: Callable[[Any], int | None],
    coerce_str_list: Callable[[Any], list[str]],
    sample_rows_evenly: Callable[[list[dict[str, Any]], int], list[dict[str, Any]]],
    aggregate_region_accuracy: Callable[
        [list[dict[str, Any]]],
        tuple[float | None, float | None, float | None],
    ],
    write_jsonl: Callable[[Path, list[dict[str, Any]]], None],
    serialize_float: Callable[[float | None], str],
    outside_wrong_line_threshold: int,
    outside_accuracy_gap_threshold: float,
) -> tuple[dict[str, Any], float | None, float | None, float | None]:
    inside_accuracy, outside_accuracy, outside_span_accuracy_gap = aggregate_region_accuracy(
        pair_breakdown_rows
    )
    outside_span_wrong_line_count = len(outside_span_trace_rows)
    include_outside_span_trace = (
        outside_span_wrong_line_count >= outside_wrong_line_threshold
        or (
            outside_span_accuracy_gap is not None
            and outside_span_accuracy_gap >= outside_accuracy_gap_threshold
        )
    )
    if include_outside_span_trace:
        sorted_outside_rows = sorted(
            outside_span_trace_rows,
            key=lambda row: (
                str(row.get("recipe_id") or ""),
                int(coerce_int(row.get("line_index")) or 0),
                str(row.get("call_id") or ""),
            ),
        )
        sampled_outside_rows = (
            sample_rows_evenly(sorted_outside_rows, sample_limit)
            if sample_limit > 0
            else sorted_outside_rows
        )
        outside_rows_out = [
            {
                "call_id": str(row.get("call_id") or ""),
                "recipe_id": str(row.get("recipe_id") or ""),
                "line_index": int(coerce_int(row.get("line_index")) or 0),
                "gold_label": str(row.get("gold_label") or ""),
                "pred_label": str(row.get("pred_label") or ""),
                "trace_status": str(row.get("trace_status") or ""),
                "warning_buckets": coerce_str_list(row.get("warning_buckets")),
                "raw_block_stable_key": row.get("raw_block_stable_key"),
                "raw_block_excerpt": str(row.get("raw_block_excerpt") or ""),
                "prompt_candidate_block_excerpt": str(
                    row.get("prompt_candidate_block_excerpt") or ""
                ),
            }
            for row in sampled_outside_rows
        ]
        write_jsonl(starter_pack_dir / starter_pack_outside_trace_file_name, outside_rows_out)
        manifest = {
            "included": True,
            "path": f"{starter_pack_dir_name}/{starter_pack_outside_trace_file_name}",
            "rows": len(outside_rows_out),
            "source_rows": outside_span_wrong_line_count,
        }
    else:
        manifest = {
            "included": False,
            "path": None,
            "rows": 0,
            "source_rows": outside_span_wrong_line_count,
            "omitted_reason": (
                "outside_span thresholds not met: "
                f"outside_span_wrong_line_count={outside_span_wrong_line_count} "
                f"(threshold={outside_wrong_line_threshold}), "
                f"outside_span_accuracy_gap="
                f"{serialize_float(outside_span_accuracy_gap) if outside_span_accuracy_gap is not None else 'n/a'} "
                f"(threshold={outside_accuracy_gap_threshold:.2f})."
            ),
        }

    return manifest, inside_accuracy, outside_accuracy, outside_span_accuracy_gap


def _run_overview_lines(
    *,
    comparison_summary: dict[str, Any],
    warning_trace_summary: dict[str, Any],
    inside_accuracy: float | None,
    outside_accuracy: float | None,
    outside_span_accuracy_gap: float | None,
    aggregate_confusion_deltas: Callable[[dict[str, Any]], list[dict[str, Any]]],
    average_float: Callable[[list[float | None]], float | None],
    coerce_float: Callable[[Any], float | None],
    serialize_float: Callable[[float | None], str],
) -> tuple[list[str], list[dict[str, Any]]]:
    top_confusion_deltas = aggregate_confusion_deltas(comparison_summary)
    warning_lines = warning_trace_summary["warnings_by_stage"]
    bucket_lines = warning_trace_summary["warning_buckets"]
    pairs = [
        pair
        for pair in (comparison_summary.get("pairs") or [])
        if isinstance(pair, dict)
    ]
    codex_overall_accuracy_avg = average_float(
        [
            coerce_float(pair.get("codex_run", {}).get("overall_line_accuracy"))
            for pair in pairs
            if isinstance(pair.get("codex_run"), dict)
        ]
    )
    codex_macro_f1_avg = average_float(
        [
            coerce_float(pair.get("codex_run", {}).get("macro_f1_excluding_other"))
            for pair in pairs
            if isinstance(pair.get("codex_run"), dict)
        ]
    )
    return [
        "# Starter Pack Run Overview",
        "",
        f"- pair_count: {len(pairs)}",
        f"- codex_overall_line_accuracy_avg: {serialize_float(codex_overall_accuracy_avg)}",
        f"- codex_macro_f1_excluding_other_avg: {serialize_float(codex_macro_f1_avg)}",
        f"- inside_span_accuracy: {serialize_float(inside_accuracy)}",
        f"- outside_span_accuracy: {serialize_float(outside_accuracy)}",
        f"- inside_vs_outside_accuracy_gap: {serialize_float(outside_span_accuracy_gap)}",
        (
            "- warning_counts_by_stage: "
            + ", ".join(f"{key}={value}" for key, value in warning_lines.items())
            if warning_lines
            else "- warning_counts_by_stage: none"
        ),
        (
            "- warning_bucket_counts: "
            + ", ".join(f"{key}={value}" for key, value in bucket_lines.items())
            if bucket_lines
            else "- warning_bucket_counts: none"
        ),
        (
            "- correction_empty_mapping_count: "
            f"{warning_trace_summary.get('correction_empty_mapping_count')}"
        ),
        (
            "- correction_empty_output_count: "
            f"{warning_trace_summary.get('correction_empty_output_count')}"
        ),
        (
            "- correction_empty_mapping_with_nonempty_output_count: "
            f"{warning_trace_summary.get('correction_empty_mapping_with_nonempty_output_count')}"
        ),
        (
            "- recipe_warning_recipe_count: "
            f"{warning_trace_summary.get('recipe_warning_recipe_count')}"
        ),
        (
            "- structural_problem_recipe_count: "
            f"{warning_trace_summary.get('structural_problem_recipe_count')}"
        ),
        (
            "- final_mapping_status_counts: "
            f"{json.dumps(warning_trace_summary.get('final_mapping_status_counts') or {}, sort_keys=True)}"
        ),
        (
            "- recipe_stage_status_counts: "
            f"{json.dumps(warning_trace_summary.get('recipe_stage_status_counts') or {}, sort_keys=True)}"
        ),
        (
            "- top_confusion_deltas: "
            + (
                ", ".join(
                    f"{row['gold_label']}->{row['pred_label']} ({row['delta_count']:+d})"
                    for row in top_confusion_deltas
                )
                if top_confusion_deltas
                else "none"
            )
        ),
        "",
    ], pairs


def _write_starter_pack_v1(
    *,
    output_dir: Path,
    comparison_summary: dict[str, Any],
    changed_line_rows: list[dict[str, Any]],
    pair_breakdown_rows: list[dict[str, Any]],
    per_recipe_breakdown_payload: dict[str, Any],
    recipe_triage_rows: list[dict[str, Any]],
    call_inventory_rows: list[dict[str, Any]],
    outside_span_trace_rows: list[dict[str, Any]],
    sample_limit: int,
    starter_pack_dir_name: str,
    starter_pack_readme_file_name: str,
    starter_pack_triage_file_name: str,
    starter_pack_triage_packet_file_name: str,
    starter_pack_call_inventory_file_name: str,
    starter_pack_changed_lines_file_name: str,
    starter_pack_warning_trace_summary_file_name: str,
    starter_pack_bridge_summary_file_name: str,
    starter_pack_selected_packets_file_name: str,
    starter_pack_casebook_file_name: str,
    starter_pack_outside_trace_file_name: str,
    starter_pack_label_policy_file_name: str,
    starter_pack_manifest_file_name: str,
    starter_pack_comparison_mirror_file_name: str,
    starter_pack_breakdown_mirror_file_name: str,
    starter_pack_net_error_blame_file_name: str,
    starter_pack_config_version_metadata_file_name: str,
    starter_pack_explicit_escalation_changed_lines_file_name: str,
    starter_pack_baseline_trace_parity_file_name: str,
    starter_pack_selection_policy: dict[str, int],
    starter_pack_outside_wrong_line_threshold: int,
    starter_pack_outside_accuracy_gap_threshold: float,
    starter_pack_heavy_artifacts_omitted_by_default: list[str],
    upload_bundle_triage_packet_schema_version: str,
    write_starter_pack_readme: Callable[..., None],
    write_json: Callable[[Path, Any], None],
    write_jsonl: Callable[[Path, list[dict[str, Any]]], None],
    starter_pack_serialize_recipe_triage_row: Callable[[dict[str, Any]], dict[str, Any]],
    upload_bundle_build_triage_packet_rows: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    build_warning_and_trace_summary: Callable[..., dict[str, Any]],
    select_starter_pack_recipe_cases: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    upload_bundle_recipe_stages_for_row: Callable[..., list[dict[str, str]]],
    build_selected_recipe_packets: Callable[..., list[dict[str, Any]]],
    render_starter_pack_casebook: Callable[[list[dict[str, Any]]], str],
    aggregate_region_accuracy: Callable[
        [list[dict[str, Any]]],
        tuple[float | None, float | None, float | None],
    ],
    aggregate_confusion_deltas: Callable[[dict[str, Any]], list[dict[str, Any]]],
    render_starter_pack_label_policy: Callable[[], str],
    starter_pack_collect_run_rows_from_pairs: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    starter_pack_build_run_dir_by_id: Callable[..., dict[str, Path]],
    build_recipe_pipeline_topology: Callable[..., dict[str, Any]],
    upload_bundle_build_explicit_escalation_changed_lines_packet: Callable[..., tuple[dict[str, Any], list[dict[str, Any]]]],
    upload_bundle_build_net_error_blame_summary: Callable[..., dict[str, Any]],
    upload_bundle_build_config_version_metadata: Callable[..., dict[str, Any]],
    starter_pack_build_baseline_trace_parity_cues: Callable[..., dict[str, Any]],
    coerce_int: Callable[[Any], int | None],
    coerce_float: Callable[[Any], float | None],
    coerce_str_list: Callable[[Any], list[str]],
    float_or_zero: Callable[[Any], float],
    average_float: Callable[[list[float | None]], float | None],
    serialize_float: Callable[[float | None], str],
    sample_rows_evenly: Callable[[list[dict[str, Any]], int], list[dict[str, Any]]],
    timestamp_now: Callable[[], str],
) -> dict[str, Any]:
    starter_pack_dir = output_dir / starter_pack_dir_name
    starter_pack_dir.mkdir(parents=True, exist_ok=True)

    write_starter_pack_readme(
        output_path=starter_pack_dir / starter_pack_readme_file_name,
        comparison_summary=comparison_summary,
    )

    sorted_recipe_triage_rows = sorted(
        recipe_triage_rows,
        key=lambda row: (
            -int(coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            -abs(float_or_zero(row.get("delta_codex_minus_baseline"))),
            str(row.get("recipe_id") or ""),
            str(row.get("source_key") or ""),
            str(row.get("codex_run_id") or ""),
        ),
    )
    serialized_triage_rows = [
        starter_pack_serialize_recipe_triage_row(row)
        for row in sorted_recipe_triage_rows
    ]
    write_jsonl(starter_pack_dir / starter_pack_triage_file_name, serialized_triage_rows)
    triage_packet_rows = upload_bundle_build_triage_packet_rows(sorted_recipe_triage_rows)
    write_jsonl(starter_pack_dir / starter_pack_triage_packet_file_name, triage_packet_rows)

    sorted_call_inventory_rows = sorted(
        call_inventory_rows,
        key=lambda row: (
            str(row.get("run_id") or ""),
            str(row.get("recipe_id") or ""),
            str(row.get("stage_key") or ""),
            str(row.get("call_id") or ""),
        ),
    )
    write_jsonl(
        starter_pack_dir / starter_pack_call_inventory_file_name,
        sorted_call_inventory_rows,
    )
    write_jsonl(
        starter_pack_dir / starter_pack_changed_lines_file_name,
        _starter_changed_rows(changed_line_rows, coerce_int=coerce_int),
    )

    warning_trace_summary = build_warning_and_trace_summary(
        call_inventory_rows=sorted_call_inventory_rows,
        recipe_triage_rows=sorted_recipe_triage_rows,
        outside_span_trace_rows=outside_span_trace_rows,
    )
    write_json(
        starter_pack_dir / starter_pack_warning_trace_summary_file_name,
        warning_trace_summary,
    )
    write_jsonl(
        starter_pack_dir / starter_pack_bridge_summary_file_name,
        _bridge_summary_rows(
            sorted_recipe_triage_rows,
            coerce_int=coerce_int,
            coerce_str_list=coerce_str_list,
        ),
    )

    selected_recipe_rows = select_starter_pack_recipe_cases(sorted_recipe_triage_rows)
    default_recipe_stages = upload_bundle_recipe_stages_for_row(
        recipe_pipeline_id="codex-recipe-shard-v1",
        correction_call_id=None,
    )
    selected_packets = build_selected_recipe_packets(
        selected_recipe_rows=selected_recipe_rows,
        changed_line_rows=changed_line_rows,
        default_recipe_stages=default_recipe_stages,
    )
    write_jsonl(starter_pack_dir / starter_pack_selected_packets_file_name, selected_packets)
    (starter_pack_dir / starter_pack_casebook_file_name).write_text(
        render_starter_pack_casebook(selected_packets),
        encoding="utf-8",
    )

    (
        outside_span_manifest,
        inside_accuracy,
        outside_accuracy,
        outside_span_accuracy_gap,
    ) = _outside_span_trace_manifest(
        starter_pack_dir=starter_pack_dir,
        starter_pack_dir_name=starter_pack_dir_name,
        starter_pack_outside_trace_file_name=starter_pack_outside_trace_file_name,
        outside_span_trace_rows=outside_span_trace_rows,
        pair_breakdown_rows=pair_breakdown_rows,
        sample_limit=sample_limit,
        coerce_int=coerce_int,
        coerce_str_list=coerce_str_list,
        sample_rows_evenly=sample_rows_evenly,
        aggregate_region_accuracy=aggregate_region_accuracy,
        write_jsonl=write_jsonl,
        serialize_float=serialize_float,
        outside_wrong_line_threshold=starter_pack_outside_wrong_line_threshold,
        outside_accuracy_gap_threshold=starter_pack_outside_accuracy_gap_threshold,
    )

    run_overview_lines, comparison_pairs = _run_overview_lines(
        comparison_summary=comparison_summary,
        warning_trace_summary=warning_trace_summary,
        inside_accuracy=inside_accuracy,
        outside_accuracy=outside_accuracy,
        outside_span_accuracy_gap=outside_span_accuracy_gap,
        aggregate_confusion_deltas=aggregate_confusion_deltas,
        average_float=average_float,
        coerce_float=coerce_float,
        serialize_float=serialize_float,
    )

    (starter_pack_dir / starter_pack_label_policy_file_name).write_text(
        render_starter_pack_label_policy(),
        encoding="utf-8",
    )
    write_json(
        starter_pack_dir / starter_pack_comparison_mirror_file_name,
        comparison_summary,
    )
    write_json(
        starter_pack_dir / starter_pack_breakdown_mirror_file_name,
        per_recipe_breakdown_payload,
    )

    starter_pack_run_rows = starter_pack_collect_run_rows_from_pairs(comparison_pairs)
    starter_pack_run_dir_by_id = starter_pack_build_run_dir_by_id(
        output_dir=output_dir,
        run_rows=starter_pack_run_rows,
    )
    recipe_pipeline_context = build_recipe_pipeline_topology(
        run_rows=starter_pack_run_rows,
        comparison_pairs=comparison_pairs,
        recipe_triage_rows=sorted_recipe_triage_rows,
    )
    (
        explicit_escalation_changed_lines_summary,
        explicit_escalation_changed_lines_rows,
    ) = upload_bundle_build_explicit_escalation_changed_lines_packet(
        source_root=output_dir,
        run_dir_by_id=starter_pack_run_dir_by_id,
        changed_line_rows=changed_line_rows,
    )
    write_jsonl(
        starter_pack_dir / starter_pack_explicit_escalation_changed_lines_file_name,
        explicit_escalation_changed_lines_rows,
    )
    net_error_blame_summary = upload_bundle_build_net_error_blame_summary(
        changed_line_rows=changed_line_rows,
        recipe_triage_rows=sorted_recipe_triage_rows,
        comparison_pairs=comparison_pairs,
        recipe_pipeline_context=recipe_pipeline_context,
        explicit_escalation_rows=explicit_escalation_changed_lines_rows,
    )
    write_json(
        starter_pack_dir / starter_pack_net_error_blame_file_name,
        net_error_blame_summary,
    )
    config_version_metadata = upload_bundle_build_config_version_metadata(
        source_root=output_dir,
        run_rows=starter_pack_run_rows,
        comparison_pairs=comparison_pairs,
        run_dir_by_id=starter_pack_run_dir_by_id,
    )
    write_json(
        starter_pack_dir / starter_pack_config_version_metadata_file_name,
        config_version_metadata,
    )
    baseline_trace_parity = starter_pack_build_baseline_trace_parity_cues(
        comparison_pairs=comparison_pairs,
        run_rows=starter_pack_run_rows,
        run_dir_by_id=starter_pack_run_dir_by_id,
    )
    write_json(
        starter_pack_dir / starter_pack_baseline_trace_parity_file_name,
        baseline_trace_parity,
    )
    pair_comparability = config_version_metadata.get("pair_comparability")
    pair_comparability = pair_comparability if isinstance(pair_comparability, dict) else {}
    run_overview_lines.extend(
        [
            "- config_compatible_pair_ratio: "
            + serialize_float(coerce_float(pair_comparability.get("config_compatible_pair_ratio"))),
            "- net_error_delta_lines: "
            + str(int(coerce_int(net_error_blame_summary.get("net_error_delta_lines")) or 0)),
            "- explicit_escalation_changed_lines: "
            + str(int(coerce_int(explicit_escalation_changed_lines_summary.get("row_count")) or 0)),
            "- baseline_trace_fully_ready_pairs: "
            + str(int(coerce_int(baseline_trace_parity.get("fully_ready_pairs")) or 0)),
            "",
        ]
    )
    (starter_pack_dir / "00_run_overview.md").write_text(
        "\n".join(run_overview_lines),
        encoding="utf-8",
    )

    starter_pack_manifest = {
        "starter_pack_version": "v1",
        "selection_policy": dict(starter_pack_selection_policy),
        "outside_span_inclusion_policy": {
            "wrong_line_count_threshold": starter_pack_outside_wrong_line_threshold,
            "accuracy_gap_threshold": starter_pack_outside_accuracy_gap_threshold,
        },
        "heavy_artifacts_omitted_by_default": list(
            starter_pack_heavy_artifacts_omitted_by_default
        ),
        "outside_span_trace_sample": outside_span_manifest,
        "triage_packet": {
            "schema_version": upload_bundle_triage_packet_schema_version,
            "row_count": len(triage_packet_rows),
        },
        "net_error_blame_summary_file": starter_pack_net_error_blame_file_name,
        "config_version_metadata_file": starter_pack_config_version_metadata_file_name,
        "explicit_escalation_changed_lines": {
            "summary": explicit_escalation_changed_lines_summary,
            "file": starter_pack_explicit_escalation_changed_lines_file_name,
            "row_count": len(explicit_escalation_changed_lines_rows),
        },
        "baseline_trace_parity_file": starter_pack_baseline_trace_parity_file_name,
        "generated_at": timestamp_now(),
    }
    write_json(starter_pack_dir / starter_pack_manifest_file_name, starter_pack_manifest)

    included_files = sorted(
        f"{starter_pack_dir_name}/{path.name}"
        for path in starter_pack_dir.iterdir()
        if path.is_file()
    )
    return {
        "path": starter_pack_dir_name,
        "included_files": included_files,
        "manifest": starter_pack_manifest,
    }
