from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable


def _source_metadata(
    run_manifest: dict[str, Any],
    *,
    source_file_name: Callable[[str | None], str | None],
    source_key: Callable[[str | None, str | None], str],
) -> dict[str, Any]:
    source = run_manifest.get("source") if isinstance(run_manifest.get("source"), dict) else {}
    source_path = source.get("path") if isinstance(source, dict) else None
    source_hash = source.get("source_hash") if isinstance(source, dict) else None
    source_file = source_file_name(source_path if isinstance(source_path, str) else None)
    return {
        "source_path": source_path if isinstance(source_path, str) else None,
        "source_hash": source_hash if isinstance(source_hash, str) else None,
        "source_file": source_file,
        "source_key": source_key(
            source_hash if isinstance(source_hash, str) else None,
            source_file,
        ),
    }


def _pipeline_snapshot(run_manifest: dict[str, Any]) -> dict[str, Any]:
    run_config = run_manifest.get("run_config")
    if not isinstance(run_config, dict):
        run_config = {}
    llm_recipe_pipeline = str(run_config.get("llm_recipe_pipeline") or "unknown")
    atomic_block_splitter = str(run_config.get("atomic_block_splitter") or "off")
    line_role_pipeline = str(run_config.get("line_role_pipeline") or "off")
    return {
        "llm_recipe_pipeline": llm_recipe_pipeline,
        "atomic_block_splitter": atomic_block_splitter,
        "line_role_pipeline": line_role_pipeline,
        "codex_enabled": llm_recipe_pipeline not in {"off", "none", ""},
    }


def _full_prompt_log_details_from_existing_run(
    *,
    run_dir: Path,
    run_manifest: dict[str, Any],
    codex_enabled: bool,
    resolve_full_prompt_log_path: Callable[[Path, dict[str, Any]], Path | None],
    iter_jsonl: Callable[[Path], list[dict[str, Any]]],
) -> dict[str, Any]:
    full_prompt_log_source = resolve_full_prompt_log_path(run_dir, run_manifest)
    status = "not_applicable"
    rows = 0
    full_prompt_log_path: str | None = None
    if full_prompt_log_source is not None and full_prompt_log_source.is_file():
        rows = len(iter_jsonl(full_prompt_log_source))
        status = "complete"
        try:
            full_prompt_log_path = str(full_prompt_log_source.relative_to(run_dir))
        except ValueError:
            full_prompt_log_path = str(full_prompt_log_source)
    elif codex_enabled:
        status = "missing"
    return {
        "status": status,
        "rows": rows,
        "path": full_prompt_log_path,
    }


def _build_run_record_from_existing_run(
    *,
    run_dir: Path,
    top_confusions_limit: int,
    record_cls: Callable[..., Any],
    load_json: Callable[[Path], dict[str, Any]],
    source_file_name: Callable[[str | None], str | None],
    source_key: Callable[[str | None, str | None], str],
    coerce_float: Callable[[Any], float | None],
    coerce_int: Callable[[Any], int | None],
    parse_run_timestamp: Callable[[str], Any],
    config_snapshot: Callable[[dict[str, Any]], dict[str, Any]],
    top_confusions: Callable[..., list[dict[str, Any]]],
    resolve_full_prompt_log_path: Callable[[Path, dict[str, Any]], Path | None],
    iter_jsonl: Callable[[Path], list[dict[str, Any]]],
) -> Any:
    run_manifest = load_json(run_dir / "run_manifest.json")
    eval_report = load_json(run_dir / "eval_report.json")

    run_id = str(run_manifest.get("run_id") or run_dir.name)
    source_meta = _source_metadata(
        run_manifest,
        source_file_name=source_file_name,
        source_key=source_key,
    )
    pipeline = _pipeline_snapshot(run_manifest)

    worst_label_recall = eval_report.get("worst_label_recall")
    if not isinstance(worst_label_recall, dict):
        worst_label_recall = {}

    prompt_log = _full_prompt_log_details_from_existing_run(
        run_dir=run_dir,
        run_manifest=run_manifest,
        codex_enabled=bool(pipeline["codex_enabled"]),
        resolve_full_prompt_log_path=resolve_full_prompt_log_path,
        iter_jsonl=iter_jsonl,
    )

    return record_cls(
        run_id=run_id,
        source_key=source_meta["source_key"],
        source_file=source_meta["source_file"],
        source_hash=source_meta["source_hash"],
        llm_recipe_pipeline=pipeline["llm_recipe_pipeline"],
        atomic_block_splitter=pipeline["atomic_block_splitter"],
        line_role_pipeline=pipeline["line_role_pipeline"],
        codex_enabled=pipeline["codex_enabled"],
        metric_overall_line_accuracy=coerce_float(eval_report.get("overall_line_accuracy")),
        metric_macro_f1_excluding_other=coerce_float(
            eval_report.get("macro_f1_excluding_other")
        ),
        metric_practical_f1=coerce_float(eval_report.get("practical_f1")),
        worst_label_recall={
            "label": worst_label_recall.get("label"),
            "recall": coerce_float(worst_label_recall.get("recall")),
            "gold_total": coerce_int(worst_label_recall.get("gold_total")),
        },
        run_timestamp=parse_run_timestamp(run_id),
        output_subdir=run_dir.name,
        config_snapshot=config_snapshot(run_manifest),
        top_confusions=top_confusions(
            eval_report.get("confusion"),
            top_k=top_confusions_limit,
        ),
        summary_path=str(run_dir / "need_to_know_summary.json"),
        run_dir=str(run_dir),
        full_prompt_log_status=prompt_log["status"],
        full_prompt_log_rows=prompt_log["rows"],
        full_prompt_log_path=prompt_log["path"],
    )


def _build_run_cutdown(
    *,
    run_dir: Path,
    output_run_dir: Path,
    sample_limit: int,
    excerpt_limit: int,
    top_confusions_limit: int,
    top_labels_limit: int,
    prompt_pairs_per_category: int,
    prompt_excerpt_limit: int,
    record_cls: Callable[..., Any],
    load_json: Callable[[Path], dict[str, Any]],
    write_json: Callable[[Path, Any], None],
    write_jsonl_sample: Callable[..., dict[str, Any]],
    jsonl_row_count: Callable[[Path], int],
    iter_jsonl: Callable[[Path], list[dict[str, Any]]],
    coerce_float: Callable[[Any], float | None],
    coerce_int: Callable[[Any], int | None],
    source_file_name: Callable[[str | None], str | None],
    source_key: Callable[[str | None, str | None], str],
    parse_run_timestamp: Callable[[str], Any],
    config_snapshot: Callable[[dict[str, Any]], dict[str, Any]],
    top_confusions: Callable[..., list[dict[str, Any]]],
    compact_per_label: Callable[[Any], dict[str, dict[str, Any]]],
    lowest_metric_labels: Callable[..., list[dict[str, Any]]],
    alignment_is_healthy: Callable[[dict[str, Any]], bool],
    resolve_prompt_log_path: Callable[[Path, dict[str, Any]], Path | None],
    resolve_full_prompt_log_path: Callable[[Path, dict[str, Any]], Path | None],
    reconstruct_full_prompt_log: Callable[..., int],
    build_recipe_spans_from_full_prompt_rows: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]]
    ],
    write_prompt_log_samples_from_full_prompt_log: Callable[..., dict[str, Any]],
    write_prompt_log_samples: Callable[..., dict[str, Any]],
    summarize_prompt_warning_aggregate: Callable[[Path], dict[str, Any]],
    build_line_prediction_view: Callable[..., Any],
    build_projection_trace: Callable[..., dict[str, Any]],
    build_wrong_label_full_context_rows: Callable[..., list[dict[str, Any]]],
    write_jsonl_gzip_deterministic: Callable[[Path, list[dict[str, Any]]], int],
    build_preprocess_trace_failure_rows: Callable[..., tuple[list[dict[str, Any]], str]],
    line_level_sampled_jsonl_inputs: tuple[tuple[str, str], ...],
    unmatched_pred_blocks_input: str,
    alignment_sampled_jsonl_inputs: tuple[tuple[str, str], ...],
    full_prompt_log_file_name: str,
    prompt_log_file_name: str,
    prompt_warning_aggregate_file_name: str,
    projection_trace_file_name: str,
    wrong_label_full_context_file_name: str,
    preprocess_trace_failures_file_name: str,
    alignment_healthy_coverage_min: float,
    alignment_healthy_match_ratio_min: float,
) -> Any:
    run_manifest = load_json(run_dir / "run_manifest.json")
    eval_report = load_json(run_dir / "eval_report.json")

    run_id = str(run_manifest.get("run_id") or run_dir.name)
    source_meta = _source_metadata(
        run_manifest,
        source_file_name=source_file_name,
        source_key=source_key,
    )
    pipeline = _pipeline_snapshot(run_manifest)

    counts = eval_report.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    alignment = eval_report.get("alignment")
    if not isinstance(alignment, dict):
        alignment = {}
    worst_label_recall = eval_report.get("worst_label_recall")
    if not isinstance(worst_label_recall, dict):
        worst_label_recall = {}

    output_run_dir.mkdir(parents=True, exist_ok=True)

    eval_report_md_path = run_dir / "eval_report.md"
    if eval_report_md_path.is_file():
        shutil.copy2(eval_report_md_path, output_run_dir / "eval_report.md")

    sample_counts: dict[str, Any] = {}
    for source_name, output_name in line_level_sampled_jsonl_inputs:
        sample_counts[output_name] = write_jsonl_sample(
            source_path=run_dir / source_name,
            output_path=output_run_dir / output_name,
            sample_limit=sample_limit,
            excerpt_limit=excerpt_limit,
        )

    unmatched_total_rows = jsonl_row_count(run_dir / unmatched_pred_blocks_input)
    sample_counts[unmatched_pred_blocks_input] = {
        "total_rows": unmatched_total_rows,
        "sample_rows": 0,
        "mode": "counts_only_default",
    }

    alignment_total_counts = {
        source_name: jsonl_row_count(run_dir / source_name)
        for source_name, _ in alignment_sampled_jsonl_inputs
    }
    healthy_alignment = alignment_is_healthy(alignment)
    sample_counts["alignment_debug_sampling"] = {
        "mode": "counts_only_healthy_alignment"
        if healthy_alignment
        else "sampled_alignment_debug",
        "counts": alignment_total_counts,
        "thresholds": {
            "canonical_char_coverage_min": alignment_healthy_coverage_min,
            "prediction_block_match_ratio_min": alignment_healthy_match_ratio_min,
        },
        "actual": {
            "canonical_char_coverage": coerce_float(alignment.get("canonical_char_coverage")),
            "prediction_block_match_ratio": coerce_float(
                alignment.get("prediction_block_match_ratio")
            ),
        },
    }
    if not healthy_alignment:
        for source_name, output_name in alignment_sampled_jsonl_inputs:
            sample_counts[output_name] = write_jsonl_sample(
                source_path=run_dir / source_name,
                output_path=output_run_dir / output_name,
                sample_limit=sample_limit,
                excerpt_limit=excerpt_limit,
            )

    codex_prompt_log = resolve_prompt_log_path(run_dir, run_manifest)
    full_prompt_log_source = resolve_full_prompt_log_path(run_dir, run_manifest)
    full_prompt_log_output = output_run_dir / full_prompt_log_file_name
    full_prompt_log_status = "not_applicable"
    full_prompt_log_rows = 0
    full_prompt_log_output_path: str | None = None
    full_prompt_rows: list[dict[str, Any]] = []
    if full_prompt_log_source is not None:
        shutil.copy2(full_prompt_log_source, full_prompt_log_output)
        full_prompt_rows = iter_jsonl(full_prompt_log_output)
        full_prompt_log_rows = len(full_prompt_rows)
        full_prompt_log_status = "complete"
        full_prompt_log_output_path = full_prompt_log_file_name
    elif pipeline["codex_enabled"]:
        reconstructed_rows = reconstruct_full_prompt_log(
            run_dir=run_dir,
            run_manifest=run_manifest,
            output_path=full_prompt_log_output,
        )
        if reconstructed_rows > 0:
            full_prompt_log_status = "complete"
            full_prompt_log_rows = reconstructed_rows
            full_prompt_log_output_path = full_prompt_log_file_name
            full_prompt_rows = iter_jsonl(full_prompt_log_output)
            if len(full_prompt_rows) != reconstructed_rows:
                full_prompt_log_rows = len(full_prompt_rows)
        else:
            full_prompt_log_status = "missing"

    sample_counts[full_prompt_log_file_name] = {
        "status": full_prompt_log_status,
        "rows": full_prompt_log_rows,
        "source_path": str(full_prompt_log_source) if full_prompt_log_source is not None else None,
    }
    recipe_spans = (
        build_recipe_spans_from_full_prompt_rows(full_prompt_rows) if full_prompt_rows else []
    )

    prompt_log_output = output_run_dir / prompt_log_file_name
    if full_prompt_log_status == "complete" and full_prompt_log_output.is_file():
        sample_counts[prompt_log_file_name] = write_prompt_log_samples_from_full_prompt_log(
            source_path=full_prompt_log_output,
            output_path=prompt_log_output,
            max_pairs_per_category=prompt_pairs_per_category,
            excerpt_limit=prompt_excerpt_limit,
        )
    elif codex_prompt_log is not None:
        if prompt_pairs_per_category <= 0:
            shutil.copy2(codex_prompt_log, prompt_log_output)
            sample_counts[prompt_log_file_name] = {
                "status": "full_copied",
                "source_path": str(codex_prompt_log),
            }
        else:
            sample_counts[prompt_log_file_name] = write_prompt_log_samples(
                source_path=codex_prompt_log,
                output_path=prompt_log_output,
                max_pairs_per_category=prompt_pairs_per_category,
            )
    elif pipeline["codex_enabled"]:
        sample_counts[prompt_log_file_name] = {"status": "missing", "source_path": None}

    if pipeline["codex_enabled"] and full_prompt_log_status == "complete" and full_prompt_log_output.is_file():
        prompt_warning_aggregate = summarize_prompt_warning_aggregate(full_prompt_log_output)
        write_json(output_run_dir / prompt_warning_aggregate_file_name, prompt_warning_aggregate)
        sample_counts[prompt_warning_aggregate_file_name] = {
            "status": "written",
            "total_calls": int(prompt_warning_aggregate.get("total_calls") or 0),
            "calls_with_warnings": int(prompt_warning_aggregate.get("calls_with_warnings") or 0),
            "warnings_total": int(prompt_warning_aggregate.get("warnings_total") or 0),
        }

        line_view = build_line_prediction_view(run_dir=run_dir, recipe_spans=recipe_spans)
        projection_trace = build_projection_trace(
            line_view=line_view,
            full_prompt_rows=full_prompt_rows,
        )
        projection_trace["recipe_span_count"] = len(recipe_spans)
        projection_trace["recipe_spans"] = recipe_spans
        write_json(output_run_dir / projection_trace_file_name, projection_trace)
        sample_counts[projection_trace_file_name] = {
            "status": "written",
            "recipe_span_count": len(recipe_spans),
            "canonical_line_total": int(
                projection_trace.get("summary", {}).get("canonical_line_total") or 0
            ),
        }
    elif pipeline["codex_enabled"]:
        sample_counts[prompt_warning_aggregate_file_name] = {"status": "missing_full_prompt_log"}
        sample_counts[projection_trace_file_name] = {"status": "missing_full_prompt_log"}

    wrong_label_total_rows = jsonl_row_count(run_dir / "wrong_label_lines.jsonl")
    if wrong_label_total_rows <= 0:
        sample_counts[wrong_label_full_context_file_name] = {
            "status": "not_applicable",
            "rows": 0,
            "source_rows": 0,
        }
        sample_counts[preprocess_trace_failures_file_name] = {
            "status": "not_applicable",
            "rows": 0,
            "source_rows": 0,
        }
    else:
        wrong_label_full_rows = build_wrong_label_full_context_rows(
            run_dir=run_dir,
            recipe_spans=recipe_spans,
            excerpt_limit=excerpt_limit,
        )
        wrong_label_full_output = output_run_dir / wrong_label_full_context_file_name
        if wrong_label_full_rows:
            written_wrong_context_rows = write_jsonl_gzip_deterministic(
                wrong_label_full_output,
                wrong_label_full_rows,
            )
            sample_counts[wrong_label_full_context_file_name] = {
                "status": "written",
                "rows": written_wrong_context_rows,
                "source_rows": wrong_label_total_rows,
            }
        else:
            sample_counts[wrong_label_full_context_file_name] = {
                "status": "not_applicable",
                "rows": 0,
                "source_rows": wrong_label_total_rows,
            }

        if not pipeline["codex_enabled"]:
            sample_counts[preprocess_trace_failures_file_name] = {
                "status": "not_applicable",
                "rows": 0,
                "source_rows": wrong_label_total_rows,
            }
        else:
            preprocess_rows, preprocess_status = build_preprocess_trace_failure_rows(
                run_dir=run_dir,
                run_manifest=run_manifest,
                full_prompt_rows=full_prompt_rows,
                excerpt_limit=excerpt_limit,
            )
            preprocess_output = output_run_dir / preprocess_trace_failures_file_name
            if preprocess_status == "ready" and preprocess_rows:
                written_preprocess_rows = write_jsonl_gzip_deterministic(
                    preprocess_output,
                    preprocess_rows,
                )
                sample_counts[preprocess_trace_failures_file_name] = {
                    "status": "written",
                    "rows": written_preprocess_rows,
                    "source_rows": wrong_label_total_rows,
                }
            else:
                sample_counts[preprocess_trace_failures_file_name] = {
                    "status": (
                        preprocess_status if preprocess_status != "ready" else "not_applicable"
                    ),
                    "rows": 0,
                    "source_rows": wrong_label_total_rows,
                }

    top_confusion_rows = top_confusions(
        eval_report.get("confusion"),
        top_k=top_confusions_limit,
    )
    compact_per_label_rows = compact_per_label(eval_report.get("per_label"))
    low_recall_labels = lowest_metric_labels(
        per_label=compact_per_label_rows,
        metric_key="recall",
        total_key="gold_total",
        limit=top_labels_limit,
    )
    low_precision_labels = lowest_metric_labels(
        per_label=compact_per_label_rows,
        metric_key="precision",
        total_key="pred_total",
        limit=top_labels_limit,
    )

    summary = {
        "run_id": run_id,
        "source": {
            "source_file": source_meta["source_file"],
            "source_path": source_meta["source_path"],
            "source_hash": source_meta["source_hash"],
            "source_key": source_meta["source_key"],
        },
        "run_config_snapshot": config_snapshot(run_manifest),
        "eval_mode": eval_report.get("eval_mode"),
        "eval_type": eval_report.get("eval_type"),
        "pipeline_knobs": {
            "llm_recipe_pipeline": pipeline["llm_recipe_pipeline"],
            "atomic_block_splitter": pipeline["atomic_block_splitter"],
            "line_role_pipeline": pipeline["line_role_pipeline"],
        },
        "key_metrics": {
            "overall_line_accuracy": coerce_float(eval_report.get("overall_line_accuracy")),
            "overall_block_accuracy": coerce_float(eval_report.get("overall_block_accuracy")),
            "macro_f1_excluding_other": coerce_float(eval_report.get("macro_f1_excluding_other")),
            "practical_precision": coerce_float(eval_report.get("practical_precision")),
            "practical_recall": coerce_float(eval_report.get("practical_recall")),
            "practical_f1": coerce_float(eval_report.get("practical_f1")),
        },
        "counts": {
            "gold_total": coerce_int(counts.get("gold_total")),
            "gold_matched": coerce_int(counts.get("gold_matched")),
            "gold_missed": coerce_int(counts.get("gold_missed")),
            "pred_total": coerce_int(counts.get("pred_total")),
            "pred_matched": coerce_int(counts.get("pred_matched")),
            "pred_false_positive": coerce_int(counts.get("pred_false_positive")),
        },
        "alignment_summary": {
            "alignment_strategy": alignment.get("alignment_strategy"),
            "alignment_primary_strategy": alignment.get("alignment_primary_strategy"),
            "canonical_char_coverage": coerce_float(alignment.get("canonical_char_coverage")),
            "prediction_char_coverage": coerce_float(alignment.get("prediction_char_coverage")),
            "prediction_block_match_ratio": coerce_float(
                alignment.get("prediction_block_match_ratio")
            ),
            "nonempty_prediction_block_match_ratio": coerce_float(
                alignment.get("nonempty_prediction_block_match_ratio")
            ),
        },
        "worst_label_recall": {
            "label": worst_label_recall.get("label"),
            "recall": coerce_float(worst_label_recall.get("recall")),
            "gold_total": coerce_int(worst_label_recall.get("gold_total")),
        },
        "top_confusions": top_confusion_rows,
        "per_label_metrics": compact_per_label_rows,
        "lowest_recall_labels": low_recall_labels,
        "lowest_precision_labels": low_precision_labels,
        "sample_counts": sample_counts,
        "full_prompt_log_status": full_prompt_log_status,
        "full_prompt_log_rows": full_prompt_log_rows,
        "full_prompt_log_path": full_prompt_log_output_path,
        "included_files": sorted(path.name for path in output_run_dir.iterdir() if path.is_file()),
    }

    summary_path = output_run_dir / "need_to_know_summary.json"
    write_json(summary_path, summary)

    return record_cls(
        run_id=run_id,
        source_key=source_meta["source_key"],
        source_file=source_meta["source_file"],
        source_hash=source_meta["source_hash"],
        llm_recipe_pipeline=pipeline["llm_recipe_pipeline"],
        atomic_block_splitter=pipeline["atomic_block_splitter"],
        line_role_pipeline=pipeline["line_role_pipeline"],
        codex_enabled=pipeline["codex_enabled"],
        metric_overall_line_accuracy=coerce_float(eval_report.get("overall_line_accuracy")),
        metric_macro_f1_excluding_other=coerce_float(
            eval_report.get("macro_f1_excluding_other")
        ),
        metric_practical_f1=coerce_float(eval_report.get("practical_f1")),
        worst_label_recall={
            "label": worst_label_recall.get("label"),
            "recall": coerce_float(worst_label_recall.get("recall")),
            "gold_total": coerce_int(worst_label_recall.get("gold_total")),
        },
        run_timestamp=parse_run_timestamp(run_id),
        output_subdir=output_run_dir.name,
        config_snapshot=config_snapshot(run_manifest),
        top_confusions=top_confusion_rows,
        summary_path=str(summary_path),
        run_dir=str(run_dir),
        full_prompt_log_status=full_prompt_log_status,
        full_prompt_log_rows=full_prompt_log_rows,
        full_prompt_log_path=(
            f"{output_run_dir.name}/{full_prompt_log_file_name}"
            if full_prompt_log_output_path is not None
            else None
        ),
    )
