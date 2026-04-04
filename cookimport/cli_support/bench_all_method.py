from __future__ import annotations

import importlib
import sys

from cookimport.cli_ui.run_settings_flow import _prompt_codex_shard_plan_menu

from .command_resolution import resolve_registered_command
from .bench_cache import (
    _all_method_eval_signature_prediction_rows,
    _all_method_gold_fingerprint,
    _all_method_prediction_reuse_cache_entry_path,
    _all_method_prediction_reuse_key_payload,
    _all_method_prediction_reuse_summary,
    _all_method_split_convert_input_key_payload,
    _build_all_method_eval_signature,
    _build_all_method_prediction_reuse_key,
    _build_all_method_split_convert_input_key,
    _copy_all_method_prediction_artifacts_for_reuse,
    _copytree_with_hardlink_fallback,
    _group_all_method_rows_by_eval_signature,
    _json_safe,
    _load_all_method_eval_signature_cache_entry,
    _load_all_method_prediction_reuse_cache_entry,
    _load_single_book_split_cache_entry,
    _materialize_all_method_cached_eval_outputs,
    _path_is_within_root,
    _release_all_method_prediction_reuse_lock,
    _release_single_book_split_cache_lock,
    _resolve_all_method_eval_signature_cache_dir,
    _resolve_all_method_prediction_record_path,
    _resolve_all_method_prediction_reuse_cache_dir,
    _single_book_split_cache_entry_path,
    _single_book_split_cache_key_payload,
    _single_book_split_cache_lock_path,
    _stable_json_sha256,
    _wait_for_all_method_prediction_reuse_cache_entry,
    _wait_for_single_book_split_cache_entry,
    _write_all_method_eval_signature_cache_entry,
    _write_all_method_prediction_reuse_cache_entry,
    _write_single_book_split_cache_entry,
    _acquire_all_method_prediction_reuse_lock,
    _acquire_single_book_split_cache_lock,
    _build_single_book_split_cache_key,
)
from .bench_all_method_qualitysuite import (
    _normalize_compare_control_path_prefix,
    _qualitysuite_compare_control_filters_for_prefixes,
    _qualitysuite_compare_control_prefixes_for_path,
    _resolve_quality_compare_scope_path,
    _write_qualitysuite_agent_bridge_bundle,
    _write_qualitysuite_agent_bridge_bundle_for_compare,
    _write_qualitysuite_agent_bridge_bundle_for_run,
    _write_qualitysuite_agent_bridge_readme,
)
from .bench_all_method_reporting import (
    _AllMethodProgressDashboard,
    _AllMethodSourceDashboardRow,
    _benchmark_eval_profile_min_seconds,
    _benchmark_eval_profile_top_n,
    _evaluation_telemetry_checkpoints,
    _evaluation_telemetry_load_seconds,
    _median_metric,
    _normalize_timing_payload,
    _render_all_method_multi_source_report_md,
    _render_all_method_report_md,
    _report_count,
    _report_metric,
    _report_optional_metric,
    _row_dimension_str,
    _timing_with_updates,
    _write_all_method_source_reports_from_global_rows,
)
from .bench_all_method_scheduler import (
    _AllMethodSchedulerAdmissionDecision,
    _AllMethodSchedulerRuntime,
    _canonical_text_chars_for_all_method_target,
    _create_all_method_process_pool_executor,
    _estimate_all_method_source_cost,
    _load_prior_all_method_source_runtime_seconds,
    _plan_all_method_global_work_items,
    _plan_all_method_source_jobs,
    _probe_all_method_process_pool_executor,
    _probe_all_method_process_worker_picklable,
    _resolve_all_method_config_timeout_seconds,
    _resolve_all_method_retry_failed_configs,
    _resolve_all_method_scheduler_admission,
    _resolve_all_method_scheduler_limits,
    _resolve_all_method_scheduler_runtime,
    _resolve_all_method_source_parallelism,
    _resolve_all_method_split_phase_slot_cap,
    _resolve_all_method_split_worker_cap,
    _split_all_method_source_variants,
    _system_total_memory_bytes,
    _tail_pair_all_method_source_jobs,
)
from .bench_all_method_targets import (
    _display_benchmark_target_name,
    _display_gold_export_path,
    _display_prediction_run_path,
    _prune_empty_dirs,
    _resolve_all_method_targets,
    _resolve_benchmark_gold_and_source,
)
from .bench_all_method_types import (
    AllMethodTarget,
    AllMethodUnmatchedGold,
    AllMethodVariant,
    _AllMethodGlobalWorkItem,
    _AllMethodSourceEstimate,
    _AllMethodSourceJobPlan,
)
from .bench_all_method_variants import (
    _all_method_apply_baseline_contract,
    _all_method_apply_codex_contract_from_baseline,
    _all_method_apply_selected_codex_contract_from_baseline,
    _all_method_codex_surface_slug_parts,
    _all_method_is_schema_like_json_source,
    _all_method_optional_module_available,
    _all_method_settings_enable_any_codex,
    _all_method_variant_token,
    _build_all_method_sweep_payloads,
    _build_all_method_target_variants,
    _build_all_method_variants,
    _resolve_all_method_codex_choice,
)
from .stage import _path_for_manifest, _require_importer

runtime = sys.modules["cookimport.cli_support.bench"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)


def _labelstudio_benchmark_command():
    return resolve_registered_command(
        "cookimport.cli_commands.labelstudio", "labelstudio_benchmark"
    )


def _bench_artifacts_module():
    return importlib.import_module("cookimport.cli_support.bench_artifacts")


def _bench_single_book_module():
    return importlib.import_module("cookimport.cli_support.bench_single_book")


def _benchmark_report_metric_bundle(*args, **kwargs):
    return _bench_single_book_module()._benchmark_report_metric_bundle(*args, **kwargs)


def _load_pred_run_recipe_context(*args, **kwargs):
    return _bench_artifacts_module()._load_pred_run_recipe_context(*args, **kwargs)


def _run_offline_benchmark_prediction_stage(*args, **kwargs):
    return _bench_artifacts_module()._run_offline_benchmark_prediction_stage(
        *args, **kwargs
    )


def _resolve_qualitysuite_codex_farm_confirmation(
    *,
    include_codex_farm: bool,
    confirmation: str | None,
) -> bool:
    decision = resolve_codex_command_decision(
        "bench_quality_run",
        {},
        include_codex_farm_requested=include_codex_farm,
        explicit_confirmation_granted=(
            str(confirmation or "").strip() == QUALITY_RUN_CODEX_FARM_CONFIRMATION_TOKEN
        ),
    )
    if decision.allowed:
        return decision.explicit_activation_granted
    _fail(
        "bench quality-run with --include-codex-farm requires explicit positive user "
        "confirmation. Re-run with "
        f"--qualitysuite-codex-farm-confirmation "
        f"{QUALITY_RUN_CODEX_FARM_CONFIRMATION_TOKEN} "
        "only after the user has explicitly approved Codex Farm usage."
    )
    return False


def _resolve_speedsuite_codex_farm_confirmation(
    *,
    include_codex_farm: bool,
    confirmation: str | None,
) -> bool:
    decision = resolve_codex_command_decision(
        "bench_speed_run",
        {},
        include_codex_farm_requested=include_codex_farm,
        explicit_confirmation_granted=(
            str(confirmation or "").strip() == SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN
        ),
    )
    if decision.allowed:
        return decision.explicit_activation_granted
    _fail(
        "bench speed-run with --include-codex-farm requires explicit positive user "
        "confirmation. Re-run with "
        f"--speedsuite-codex-farm-confirmation "
        f"{SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN} "
        "only after the user has explicitly approved Codex Farm usage."
    )
    return False


def _print_codex_decision(decision: Any) -> None:
    if bool(_BENCHMARK_SUPPRESS_SUMMARY.get()):
        return
    summary = (
        format_codex_execution_policy_summary(decision)
        if hasattr(decision, "requested_mode")
        else format_codex_command_summary(decision)
    )
    surface = getattr(decision, "surface", None)
    codex_requested = bool(getattr(decision, "codex_requested", False))
    color = (
        typer.colors.CYAN
        if (
            surface is not None
            and (
                bool(getattr(surface, "any_codex_enabled", False))
                or codex_requested
            )
        )
        else typer.colors.BRIGHT_BLACK
    )
    typer.secho(summary, fg=color)


def _resolve_all_method_markdown_extractors_choice() -> bool:
    requested = os.getenv(ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV, "").strip() == "1"
    return requested and markdown_epub_extractors_enabled()


def _all_method_extract_alignment_guardrail_fields(
    report_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    report = report_payload if isinstance(report_payload, dict) else {}
    return {
        "alignment_cache_enabled": bool(report.get("alignment_cache_enabled")),
        "alignment_cache_hit": bool(report.get("alignment_cache_hit")),
        "alignment_cache_load_seconds": _report_metric(report.get("alignment_cache_load_seconds")),
        "alignment_cache_write_seconds": _report_metric(report.get("alignment_cache_write_seconds")),
        "alignment_sequence_matcher_impl": str(report.get("alignment_sequence_matcher_impl") or ""),
        "alignment_sequence_matcher_mode": str(report.get("alignment_sequence_matcher_mode") or ""),
        "alignment_sequence_matcher_requested_mode": str(
            report.get("alignment_sequence_matcher_requested_mode") or ""
        ),
        "alignment_sequence_matcher_forced_mode": str(
            report.get("alignment_sequence_matcher_forced_mode") or ""
        ),
    }


def _all_method_build_matcher_guardrails(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    executed_rows = [
        row
        for row in rows
        if str(row.get("status") or "").strip().lower() == "ok"
        and str(row.get("evaluation_result_source") or "").strip().lower() == "executed"
    ]
    eval_wall_sum = 0.0
    prediction_wall_sum = 0.0
    cache_enabled_count = 0
    cache_hit_count = 0
    matcher_mode_counts: dict[str, int] = {}

    for row in executed_rows:
        timing = _normalize_timing_payload(row.get("timing"))
        checkpoints = timing.get("checkpoints")
        if not isinstance(checkpoints, dict):
            checkpoints = {}
        eval_wall_sum += max(
            0.0,
            _report_metric(checkpoints.get("all_method_eval_wall_seconds")),
        )
        prediction_wall_sum += max(
            0.0,
            _report_metric(checkpoints.get("all_method_prediction_wall_seconds")),
        )
        cache_enabled = bool(row.get("alignment_cache_enabled"))
        if cache_enabled:
            cache_enabled_count += 1
            if bool(row.get("alignment_cache_hit")):
                cache_hit_count += 1
        matcher_mode = str(row.get("alignment_sequence_matcher_mode") or "").strip()
        if matcher_mode:
            matcher_mode_counts[matcher_mode] = matcher_mode_counts.get(matcher_mode, 0) + 1

    eval_to_prediction_ratio = (
        (eval_wall_sum / prediction_wall_sum) if prediction_wall_sum > 0 else 0.0
    )
    cache_hit_rate = (
        (float(cache_hit_count) / float(cache_enabled_count))
        if cache_enabled_count > 0
        else 1.0
    )
    warnings: list[str] = []
    if eval_to_prediction_ratio > ALL_METHOD_MATCHER_GUARDRAIL_EVAL_RATIO_WARN:
        warnings.append(
            "Eval wall share exceeded guardrail: "
            f"{eval_to_prediction_ratio:.3f} > {ALL_METHOD_MATCHER_GUARDRAIL_EVAL_RATIO_WARN:.3f}"
        )
    if cache_enabled_count > 0 and cache_hit_rate < ALL_METHOD_MATCHER_GUARDRAIL_CACHE_HIT_WARN:
        warnings.append(
            "Canonical alignment cache hit-rate dropped below guardrail: "
            f"{cache_hit_rate:.3f} < {ALL_METHOD_MATCHER_GUARDRAIL_CACHE_HIT_WARN:.3f}"
        )
    if matcher_mode_counts and not any(
        mode == "dmp" for mode in matcher_mode_counts
    ):
        warnings.append("Matcher guardrail expected dmp mode for canonical alignment.")

    return {
        "executed_evaluation_rows": len(executed_rows),
        "eval_wall_seconds_sum": eval_wall_sum,
        "prediction_wall_seconds_sum": prediction_wall_sum,
        "eval_to_prediction_wall_ratio": eval_to_prediction_ratio,
        "cache_enabled_count": cache_enabled_count,
        "cache_hit_count": cache_hit_count,
        "cache_hit_rate": cache_hit_rate,
        "matcher_mode_counts": matcher_mode_counts,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _all_method_config_dir_name(config_index: int, variant: AllMethodVariant) -> str:
    config_hash = variant.run_settings.short_hash()
    return f"config_{config_index:03d}_{config_hash}_{variant.slug}"


def _all_method_failed_row(
    *,
    config_index: int,
    config_dir_name: str,
    variant: AllMethodVariant,
    error: str,
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    row = {
        "config_index": config_index,
        "config_dir": config_dir_name,
        "slug": variant.slug,
        "status": "failed",
        "error": str(error),
        "run_config_hash": "",
        "run_config_summary": "",
        "dimensions": dict(variant.dimensions),
    }
    numeric_elapsed = _report_optional_metric(elapsed_seconds)
    if numeric_elapsed is not None:
        row["timing"] = _timing_with_updates(
            {},
            total_seconds=max(0.0, numeric_elapsed),
        )
    return row
def _run_all_method_prediction_once(
    *,
    gold_spans_path: Path,
    source_file: Path,
    variant: AllMethodVariant,
    config_index: int,
    total_variants: int,
    root_output_dir: Path,
    scratch_root: Path,
    processed_output_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    max_concurrent_split_phases: int,
    split_phase_gate_dir: Path,
    scheduler_events_dir: Path,
    alignment_cache_dir: Path | None,
    prediction_reuse_cache_dir: Path | None = None,
    split_worker_cap_per_config: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    config_started = time.monotonic()
    config_dir_name = _all_method_config_dir_name(config_index, variant)
    eval_output_dir = root_output_dir / config_dir_name
    scratch_output_dir = scratch_root / config_dir_name
    processed_output_dir = processed_output_root / config_dir_name
    prediction_record_path = eval_output_dir / "prediction-records.jsonl"
    prediction_reuse_key = _build_all_method_prediction_reuse_key(
        source_file=source_file,
        run_settings=variant.run_settings,
    )
    prediction_split_convert_input_key = _build_all_method_split_convert_input_key(
        source_file=source_file,
        run_settings=variant.run_settings,
    )
    prediction_result_source = "executed"
    prediction_reuse_scope = "executed"
    prediction_representative_config_dir = config_dir_name
    reused_prediction = False

    split_slots = max(1, _report_count(max_concurrent_split_phases))
    split_status_label = format_task_counter(
        "Config",
        config_index,
        max(1, _report_count(total_variants)),
        noun="config",
    )
    source_slug = slugify_name(source_file.stem)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    scheduler_event_path = scheduler_events_dir / f"config_{config_index:03d}.jsonl"
    if scheduler_event_path.exists():
        scheduler_event_path.unlink()

    def _emit_scheduler_event(
        event_name: str,
        **payload: Any,
    ) -> None:
        event = str(event_name or "").strip()
        if not event:
            return
        row = {
            "event": event,
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": time.monotonic(),
            "config_index": config_index,
            "config_slug": variant.slug,
            "config_dir": config_dir_name,
            "source_slug": source_slug,
        }
        row.update(payload)
        try:
            with scheduler_event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring scheduler event write failure for %s: %s",
                scheduler_event_path,
                exc,
            )

    def _scheduler_event_callback(payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        event_name = str(payload.get("event") or "").strip()
        if not event_name:
            return
        event_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"event", "config_index", "config_slug", "source_slug"}
        }
        _emit_scheduler_event(event_name, **event_payload)

    def _discard_progress(_message: str) -> None:
        return

    def _prediction_failed_row(error: str, *, elapsed_seconds: float) -> dict[str, Any]:
        row = _all_method_failed_row(
            config_index=config_index,
            config_dir_name=config_dir_name,
            variant=variant,
            error=error,
            elapsed_seconds=elapsed_seconds,
        )
        row["prediction_result_source"] = "failed"
        row["prediction_reuse_scope"] = "failed"
        row["prediction_representative_config_dir"] = config_dir_name
        row["prediction_reuse_key"] = prediction_reuse_key
        row["prediction_split_convert_input_key"] = prediction_split_convert_input_key
        return row

    def _reset_target_prediction_dirs() -> None:
        if eval_output_dir.exists():
            shutil.rmtree(eval_output_dir)
        if scratch_output_dir.exists():
            shutil.rmtree(scratch_output_dir)
        if processed_output_dir.exists():
            shutil.rmtree(processed_output_dir)

    benchmark_progress_callback = progress_callback or _discard_progress
    _emit_scheduler_event("config_started")

    requested_workers = max(1, _report_count(variant.run_settings.workers))
    requested_pdf_split_workers = max(1, _report_count(variant.run_settings.pdf_split_workers))
    requested_epub_split_workers = max(1, _report_count(variant.run_settings.epub_split_workers))
    effective_split_worker_cap = (
        max(1, _report_count(split_worker_cap_per_config))
        if split_worker_cap_per_config is not None
        else None
    )
    effective_workers = requested_workers
    effective_pdf_split_workers = requested_pdf_split_workers
    effective_epub_split_workers = requested_epub_split_workers
    if effective_split_worker_cap is not None:
        effective_workers = min(effective_workers, effective_split_worker_cap)
        effective_pdf_split_workers = min(
            effective_pdf_split_workers,
            effective_split_worker_cap,
        )
        effective_epub_split_workers = min(
            effective_epub_split_workers,
            effective_split_worker_cap,
        )

    prediction_reuse_cache_dir = (
        prediction_reuse_cache_dir
        if prediction_reuse_cache_dir is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    ).expanduser()
    prediction_reuse_cache_path = _all_method_prediction_reuse_cache_entry_path(
        cache_dir=prediction_reuse_cache_dir,
        prediction_reuse_key=prediction_reuse_key,
    )
    prediction_reuse_lock_path = prediction_reuse_cache_path.with_suffix(
        f"{prediction_reuse_cache_path.suffix}{ALL_METHOD_PREDICTION_REUSE_LOCK_SUFFIX}"
    )
    lock_acquired = False

    def _execute_prediction_run() -> str | None:
        _reset_target_prediction_dirs()
        try:
            with _benchmark_split_phase_overrides(
                split_phase_slots=split_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                split_phase_status_label=split_status_label,
            ):
                with _benchmark_progress_overrides(
                    progress_callback=benchmark_progress_callback,
                    suppress_summary=True,
                    suppress_spinner=True,
                    suppress_output_prune=True,
                ):
                    with _benchmark_scheduler_event_overrides(
                        scheduler_event_callback=_scheduler_event_callback
                    ):
                        benchmark_kwargs = build_benchmark_call_kwargs_from_run_settings(
                            variant.run_settings,
                            output_dir=scratch_output_dir,
                            processed_output_dir=processed_output_dir,
                            eval_output_dir=eval_output_dir,
                            eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                            no_upload=True,
                            write_markdown=False,
                            write_label_studio_tasks=False,
                        )
                        benchmark_kwargs["allow_codex"] = codex_surfaces_enabled(
                            variant.run_settings.to_run_config_dict()
                        )
                        benchmark_kwargs.update(
                            {
                                "source_file": source_file,
                                "workers": effective_workers,
                                "pdf_split_workers": effective_pdf_split_workers,
                                "epub_split_workers": effective_epub_split_workers,
                            }
                        )
                        prediction_generation_kwargs = {
                            "path": benchmark_kwargs["source_file"],
                            "output_dir": benchmark_kwargs["output_dir"],
                            "pipeline": benchmark_kwargs.get("pipeline", "auto"),
                            "segment_blocks": 40,
                            "segment_overlap": 5,
                            "limit": None,
                            "sample": None,
                            "workers": benchmark_kwargs["workers"],
                            "pdf_split_workers": benchmark_kwargs["pdf_split_workers"],
                            "epub_split_workers": benchmark_kwargs["epub_split_workers"],
                            "pdf_pages_per_job": benchmark_kwargs["pdf_pages_per_job"],
                            "epub_spine_items_per_job": benchmark_kwargs[
                                "epub_spine_items_per_job"
                            ],
                            "epub_extractor": benchmark_kwargs["epub_extractor"],
                            "epub_unstructured_html_parser_version": benchmark_kwargs[
                                "epub_unstructured_html_parser_version"
                            ],
                            "epub_unstructured_skip_headers_footers": benchmark_kwargs[
                                "epub_unstructured_skip_headers_footers"
                            ],
                            "epub_unstructured_preprocess_mode": benchmark_kwargs[
                                "epub_unstructured_preprocess_mode"
                            ],
                            "ocr_device": benchmark_kwargs["ocr_device"],
                            "pdf_ocr_policy": benchmark_kwargs["pdf_ocr_policy"],
                            "ocr_batch_size": benchmark_kwargs["ocr_batch_size"],
                            "pdf_column_gap_ratio": benchmark_kwargs[
                                "pdf_column_gap_ratio"
                            ],
                            "warm_models": benchmark_kwargs["warm_models"],
                            "section_detector_backend": benchmark_kwargs[
                                "section_detector_backend"
                            ],
                            "multi_recipe_splitter": benchmark_kwargs[
                                "multi_recipe_splitter"
                            ],
                            "multi_recipe_trace": benchmark_kwargs["multi_recipe_trace"],
                            "multi_recipe_min_ingredient_lines": benchmark_kwargs[
                                "multi_recipe_min_ingredient_lines"
                            ],
                            "multi_recipe_min_instruction_lines": benchmark_kwargs[
                                "multi_recipe_min_instruction_lines"
                            ],
                            "multi_recipe_for_the_guardrail": benchmark_kwargs[
                                "multi_recipe_for_the_guardrail"
                            ],
                            "instruction_step_segmentation_policy": benchmark_kwargs[
                                "instruction_step_segmentation_policy"
                            ],
                            "instruction_step_segmenter": benchmark_kwargs[
                                "instruction_step_segmenter"
                            ],
                            "web_schema_extractor": benchmark_kwargs[
                                "web_schema_extractor"
                            ],
                            "web_schema_normalizer": benchmark_kwargs[
                                "web_schema_normalizer"
                            ],
                            "web_html_text_extractor": benchmark_kwargs[
                                "web_html_text_extractor"
                            ],
                            "web_schema_policy": benchmark_kwargs["web_schema_policy"],
                            "web_schema_min_confidence": benchmark_kwargs[
                                "web_schema_min_confidence"
                            ],
                            "web_schema_min_ingredients": benchmark_kwargs[
                                "web_schema_min_ingredients"
                            ],
                            "web_schema_min_instruction_steps": benchmark_kwargs[
                                "web_schema_min_instruction_steps"
                            ],
                            "ingredient_text_fix_backend": benchmark_kwargs[
                                "ingredient_text_fix_backend"
                            ],
                            "ingredient_pre_normalize_mode": benchmark_kwargs[
                                "ingredient_pre_normalize_mode"
                            ],
                            "ingredient_packaging_mode": benchmark_kwargs[
                                "ingredient_packaging_mode"
                            ],
                            "ingredient_parser_backend": benchmark_kwargs[
                                "ingredient_parser_backend"
                            ],
                            "ingredient_unit_canonicalizer": benchmark_kwargs[
                                "ingredient_unit_canonicalizer"
                            ],
                            "ingredient_missing_unit_policy": benchmark_kwargs[
                                "ingredient_missing_unit_policy"
                            ],
                            "p6_time_backend": benchmark_kwargs["p6_time_backend"],
                            "p6_time_total_strategy": benchmark_kwargs[
                                "p6_time_total_strategy"
                            ],
                            "p6_temperature_backend": benchmark_kwargs[
                                "p6_temperature_backend"
                            ],
                            "p6_temperature_unit_backend": benchmark_kwargs[
                                "p6_temperature_unit_backend"
                            ],
                            "p6_ovenlike_mode": benchmark_kwargs["p6_ovenlike_mode"],
                            "p6_yield_mode": benchmark_kwargs["p6_yield_mode"],
                            "p6_emit_metadata_debug": benchmark_kwargs[
                                "p6_emit_metadata_debug"
                            ],
                            "recipe_scorer_backend": benchmark_kwargs[
                                "recipe_scorer_backend"
                            ],
                            "recipe_score_gold_min": benchmark_kwargs[
                                "recipe_score_gold_min"
                            ],
                            "recipe_score_silver_min": benchmark_kwargs[
                                "recipe_score_silver_min"
                            ],
                            "recipe_score_bronze_min": benchmark_kwargs[
                                "recipe_score_bronze_min"
                            ],
                            "recipe_score_min_ingredient_lines": benchmark_kwargs[
                                "recipe_score_min_ingredient_lines"
                            ],
                            "recipe_score_min_instruction_lines": benchmark_kwargs[
                                "recipe_score_min_instruction_lines"
                            ],
                            "llm_recipe_pipeline": benchmark_kwargs[
                                "llm_recipe_pipeline"
                            ],
                            "llm_knowledge_pipeline": benchmark_kwargs[
                                "llm_knowledge_pipeline"
                            ],
                            "knowledge_packet_input_char_budget": benchmark_kwargs[
                                "knowledge_packet_input_char_budget"
                            ],
                            "knowledge_packet_output_char_budget": benchmark_kwargs[
                                "knowledge_packet_output_char_budget"
                            ],
                            "knowledge_group_task_max_units": benchmark_kwargs[
                                "knowledge_group_task_max_units"
                            ],
                            "knowledge_group_task_max_evidence_chars": benchmark_kwargs[
                                "knowledge_group_task_max_evidence_chars"
                            ],
                            "atomic_block_splitter": benchmark_kwargs[
                                "atomic_block_splitter"
                            ],
                            "line_role_pipeline": benchmark_kwargs["line_role_pipeline"],
                            "codex_exec_style": benchmark_kwargs["codex_exec_style"],
                            "codex_farm_cmd": benchmark_kwargs["codex_farm_cmd"],
                            "codex_farm_model": benchmark_kwargs.get("codex_farm_model"),
                            "codex_farm_reasoning_effort": benchmark_kwargs.get(
                                "codex_farm_reasoning_effort"
                            ),
                            "codex_farm_root": benchmark_kwargs.get("codex_farm_root"),
                            "codex_farm_workspace_root": benchmark_kwargs.get(
                                "codex_farm_workspace_root"
                            ),
                            "codex_farm_pipeline_knowledge": benchmark_kwargs[
                                "codex_farm_pipeline_knowledge"
                            ],
                            "codex_farm_context_blocks": benchmark_kwargs[
                                "codex_farm_context_blocks"
                            ],
                            "codex_farm_knowledge_context_blocks": benchmark_kwargs[
                                "codex_farm_knowledge_context_blocks"
                            ],
                            "codex_farm_recipe_mode": benchmark_kwargs[
                                "codex_farm_recipe_mode"
                            ],
                            "codex_farm_failure_mode": benchmark_kwargs[
                                "codex_farm_failure_mode"
                            ],
                            "allow_codex": benchmark_kwargs["allow_codex"],
                            "codex_execution_policy": "execute",
                            "processed_output_root": benchmark_kwargs[
                                "processed_output_dir"
                            ],
                            "workspace_completion_quiescence_seconds": benchmark_kwargs[
                                "workspace_completion_quiescence_seconds"
                            ],
                            "completed_termination_grace_seconds": benchmark_kwargs[
                                "completed_termination_grace_seconds"
                            ],
                            "epub_title_backtrack_limit": benchmark_kwargs[
                                "epub_title_backtrack_limit"
                            ],
                            "epub_anchor_title_backtrack_limit": benchmark_kwargs[
                                "epub_anchor_title_backtrack_limit"
                            ],
                            "epub_ingredient_run_window": benchmark_kwargs[
                                "epub_ingredient_run_window"
                            ],
                            "epub_ingredient_header_window": benchmark_kwargs[
                                "epub_ingredient_header_window"
                            ],
                            "epub_title_max_length": benchmark_kwargs[
                                "epub_title_max_length"
                            ],
                            "write_markdown": benchmark_kwargs["write_markdown"],
                            "write_label_studio_tasks": benchmark_kwargs[
                                "write_label_studio_tasks"
                            ],
                            "scheduler_event_callback": _scheduler_event_callback,
                            "progress_callback": benchmark_progress_callback,
                            "run_manifest_kind": "bench_pred_run",
                        }
                        _run_offline_benchmark_prediction_stage(
                            prediction_generation_kwargs=prediction_generation_kwargs,
                            eval_output_dir=eval_output_dir,
                            predictions_out_path=prediction_record_path,
                            suppress_spinner=True,
                            external_progress_callback=benchmark_progress_callback,
                        )
        except Exception as exc:  # noqa: BLE001
            return str(exc)
        return None

    def _try_materialize_reused_prediction(
        cache_entry: dict[str, Any] | None,
    ) -> bool:
        nonlocal prediction_result_source
        nonlocal prediction_reuse_scope
        nonlocal prediction_representative_config_dir
        nonlocal reused_prediction
        if not isinstance(cache_entry, dict):
            return False
        source_config_dir = str(cache_entry.get("config_dir") or "").strip()
        source_eval_output_dir: Path | None = None
        source_scratch_output_dir: Path | None = None
        source_processed_output_dir: Path | None = None
        source_eval_raw = str(cache_entry.get("source_eval_output_dir") or "").strip()
        source_scratch_raw = str(
            cache_entry.get("source_scratch_output_dir") or ""
        ).strip()
        source_processed_raw = str(
            cache_entry.get("source_processed_output_dir") or ""
        ).strip()
        if source_eval_raw:
            source_eval_output_dir = Path(source_eval_raw).expanduser()
        if source_scratch_raw:
            source_scratch_output_dir = Path(source_scratch_raw).expanduser()
        if source_processed_raw:
            source_processed_output_dir = Path(source_processed_raw).expanduser()
        if not source_config_dir and source_eval_output_dir is None:
            return False
        if source_config_dir == config_dir_name:
            if source_eval_output_dir is None:
                return False
            if source_eval_output_dir.resolve(strict=False) == eval_output_dir.resolve(
                strict=False
            ):
                return False
        copy_seconds = _copy_all_method_prediction_artifacts_for_reuse(
            source_config_dir=source_config_dir,
            target_config_dir=config_dir_name,
            root_output_dir=root_output_dir,
            scratch_root=scratch_root,
            processed_output_root=processed_output_root,
            source_eval_output_dir=source_eval_output_dir,
            source_scratch_output_dir=source_scratch_output_dir,
            source_processed_output_dir=source_processed_output_dir,
        )
        if copy_seconds is None:
            return False
        reuse_scope = "in_run"
        if source_eval_output_dir is not None and not _path_is_within_root(
            source_eval_output_dir,
            root_output_dir,
        ):
            reuse_scope = "cross_run"
        prediction_result_source = (
            "reused_cross_run" if reuse_scope == "cross_run" else "reused_in_run"
        )
        prediction_reuse_scope = reuse_scope
        prediction_representative_config_dir = (
            source_config_dir
            or (str(source_eval_output_dir) if source_eval_output_dir is not None else "")
            or config_dir_name
        )
        reused_prediction = True
        _emit_scheduler_event(
            (
                "prediction_reused_cross_run"
                if prediction_result_source == "reused_cross_run"
                else "prediction_reused_in_run"
            ),
            source_config_dir=source_config_dir,
            reuse_copy_seconds=copy_seconds,
            prediction_result_source=prediction_result_source,
            prediction_reuse_scope=prediction_reuse_scope,
        )
        return True

    try:
        cache_entry = _load_all_method_prediction_reuse_cache_entry(
            cache_path=prediction_reuse_cache_path,
            expected_key=prediction_reuse_key,
        )
        if not _try_materialize_reused_prediction(cache_entry):
            lock_acquired = _acquire_all_method_prediction_reuse_lock(
                prediction_reuse_lock_path
            )
            if lock_acquired:
                cache_entry = _load_all_method_prediction_reuse_cache_entry(
                    cache_path=prediction_reuse_cache_path,
                    expected_key=prediction_reuse_key,
                )
                if not _try_materialize_reused_prediction(cache_entry):
                    run_error = _execute_prediction_run()
                    if run_error is not None:
                        _emit_scheduler_event(
                            "config_finished",
                            status="failed",
                            error=run_error,
                        )
                        return _prediction_failed_row(
                            run_error,
                            elapsed_seconds=max(0.0, time.monotonic() - config_started),
                        )
            else:
                waited_entry = _wait_for_all_method_prediction_reuse_cache_entry(
                    cache_path=prediction_reuse_cache_path,
                    expected_key=prediction_reuse_key,
                    lock_path=prediction_reuse_lock_path,
                )
                if not _try_materialize_reused_prediction(waited_entry):
                    run_error = _execute_prediction_run()
                    if run_error is not None:
                        _emit_scheduler_event(
                            "config_finished",
                            status="failed",
                            error=run_error,
                        )
                        return _prediction_failed_row(
                            run_error,
                            elapsed_seconds=max(0.0, time.monotonic() - config_started),
                        )
    finally:
        if lock_acquired:
            _release_all_method_prediction_reuse_lock(prediction_reuse_lock_path)

    if prediction_result_source == "executed":
        cache_payload = {
            "schema_version": ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION,
            "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "prediction_reuse_key": prediction_reuse_key,
            "prediction_split_convert_input_key": prediction_split_convert_input_key,
            "source_file": str(source_file),
            "config_index": config_index,
            "config_dir": config_dir_name,
            "source_eval_output_dir": str(eval_output_dir),
            "source_scratch_output_dir": str(scratch_output_dir),
            "source_processed_output_dir": str(processed_output_dir),
        }
        try:
            _write_all_method_prediction_reuse_cache_entry(
                cache_path=prediction_reuse_cache_path,
                payload=cache_payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring all-method prediction reuse cache write failure for %s: %s",
                prediction_reuse_cache_path,
                exc,
            )

    if not prediction_record_path.exists():
        missing_error = f"Missing prediction-records.jsonl in {eval_output_dir}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=missing_error,
        )
        return _prediction_failed_row(
            missing_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )
    try:
        prediction_records = list(read_prediction_records(prediction_record_path))
    except Exception as exc:  # noqa: BLE001
        parse_error = f"Failed to parse prediction records for {config_dir_name}: {exc}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=parse_error,
        )
        return _prediction_failed_row(
            parse_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )
    if not prediction_records:
        empty_error = f"Prediction records are empty for {config_dir_name}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=empty_error,
        )
        return _prediction_failed_row(
            empty_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )

    config_wall_seconds = max(0.0, time.monotonic() - config_started)
    report_timing: dict[str, Any] = {}
    run_manifest_path = eval_output_dir / "run_manifest.json"
    if run_manifest_path.exists() and run_manifest_path.is_file():
        try:
            run_manifest_payload = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            run_manifest_payload = {}
        if isinstance(run_manifest_payload, dict):
            artifacts_payload = run_manifest_payload.get("artifacts")
            if isinstance(artifacts_payload, dict):
                report_timing = _normalize_timing_payload(artifacts_payload.get("timing"))

    # Test doubles sometimes write timing only via eval_report.json.
    if not report_timing:
        report_json_path = eval_output_dir / "eval_report.json"
        if report_json_path.exists() and report_json_path.is_file():
            try:
                report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                report_payload = {}
            if isinstance(report_payload, dict):
                report_timing = _normalize_timing_payload(report_payload.get("timing"))

    prediction_phase_seconds = _report_optional_metric(
        report_timing.get("prediction_seconds")
    )
    report_total_seconds = _report_optional_metric(report_timing.get("total_seconds"))
    if reused_prediction:
        prediction_phase_seconds = 0.0
        report_total_seconds = config_wall_seconds
    if prediction_phase_seconds is None and report_total_seconds is not None:
        prediction_phase_seconds = report_total_seconds
    if prediction_phase_seconds is None:
        prediction_phase_seconds = config_wall_seconds
    prediction_checkpoints: dict[str, float] = {
        "all_method_prediction_wall_seconds": config_wall_seconds,
        "all_method_config_wall_seconds": config_wall_seconds,
        "all_method_prediction_reused_in_run": 1.0 if reused_prediction else 0.0,
    }
    if reused_prediction:
        prediction_checkpoints["all_method_prediction_reuse_copy_seconds"] = (
            config_wall_seconds
        )
    config_timing = _timing_with_updates(
        report_timing,
        prediction_seconds=prediction_phase_seconds,
        evaluation_seconds=0.0,
        total_seconds=(
            report_total_seconds if report_total_seconds is not None else config_wall_seconds
        ),
        checkpoints=prediction_checkpoints,
    )

    pred_context = _load_pred_run_recipe_context(eval_output_dir)
    row = {
        "config_index": config_index,
        "config_dir": config_dir_name,
        "slug": variant.slug,
        "status": "ok",
        "error": "",
        "run_config_hash": pred_context.run_config_hash or variant.run_settings.stable_hash(),
        "run_config_summary": pred_context.run_config_summary
        or variant.run_settings.summary(),
        "prediction_record_jsonl": _path_for_manifest(
            root_output_dir,
            prediction_record_path,
        ),
        "benchmark_sequence_matcher": variant.run_settings.benchmark_sequence_matcher,
        "duration_seconds": config_wall_seconds,
        "timing": config_timing,
        "dimensions": dict(variant.dimensions),
        "prediction_result_source": prediction_result_source,
        "prediction_reuse_scope": prediction_reuse_scope,
        "prediction_representative_config_dir": prediction_representative_config_dir,
        "prediction_reuse_key": prediction_reuse_key,
        "prediction_split_convert_input_key": prediction_split_convert_input_key,
    }
    _emit_scheduler_event(
        "config_finished",
        status="ok",
        duration_seconds=config_wall_seconds,
        prediction_result_source=prediction_result_source,
    )
    return row


def _run_all_method_evaluate_prediction_record_once(
    *,
    gold_spans_path: Path,
    source_file: Path,
    prediction_record_path: Path,
    eval_output_dir: Path,
    processed_output_dir: Path,
    sequence_matcher: str,
    epub_extractor: str | None,
    overlap_threshold: float,
    force_source_match: bool,
    alignment_cache_dir: Path | None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    evaluation_started = time.monotonic()

    def _discard_progress(_message: str) -> None:
        return

    benchmark_progress_callback = progress_callback or _discard_progress
    scratch_output_dir = eval_output_dir / ".scratch-eval-only"
    if scratch_output_dir.exists():
        shutil.rmtree(scratch_output_dir)
    for artifact_name in ("eval_report.json", "eval_report.md"):
        artifact_path = eval_output_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()

    fail_message_token = _LAST_FAIL_MESSAGE.set(None)
    try:
        with _benchmark_progress_overrides(
            progress_callback=benchmark_progress_callback,
            suppress_summary=True,
            suppress_spinner=True,
            suppress_output_prune=True,
        ):
            _labelstudio_benchmark_command()(
                gold_spans=gold_spans_path,
                source_file=source_file,
                output_dir=scratch_output_dir,
                processed_output_dir=processed_output_dir,
                eval_output_dir=eval_output_dir,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
                epub_extractor=(epub_extractor or "unstructured"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                no_upload=True,
                predictions_in=prediction_record_path,
                alignment_cache_dir=alignment_cache_dir,
            )
    except typer.Exit as exc:
        exit_code = getattr(exc, "exit_code", 1)
        failure_message = _LAST_FAIL_MESSAGE.get()
        error_message = (
            failure_message
            if failure_message
            else f"labelstudio_benchmark exited with code {exit_code}"
        )
        return {
            "status": "failed",
            "error": error_message,
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error": str(exc),
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    finally:
        _LAST_FAIL_MESSAGE.reset(fail_message_token)

    report_json_path = eval_output_dir / "eval_report.json"
    if not report_json_path.exists() or not report_json_path.is_file():
        return {
            "status": "failed",
            "error": f"Missing eval_report.json in {eval_output_dir}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    try:
        report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error": f"Failed to parse eval report in {eval_output_dir}: {exc}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    if not isinstance(report_payload, dict):
        return {
            "status": "failed",
            "error": f"Eval report payload is invalid in {eval_output_dir}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }

    evaluation_wall_seconds = max(0.0, time.monotonic() - evaluation_started)
    report_timing = _normalize_timing_payload(report_payload.get("timing"))
    report_total_seconds = _report_optional_metric(report_timing.get("total_seconds"))
    normalized_timing = _timing_with_updates(
        report_timing,
        total_seconds=(
            report_total_seconds
            if report_total_seconds is not None
            else evaluation_wall_seconds
        ),
        checkpoints={"all_method_eval_wall_seconds": evaluation_wall_seconds},
    )
    report_payload["timing"] = normalized_timing
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = eval_output_dir / "eval_report.md"
    report_md_text = (
        report_md_path.read_text(encoding="utf-8")
        if report_md_path.exists() and report_md_path.is_file()
        else ""
    )
    metric_bundle = _benchmark_report_metric_bundle(report_payload)
    return {
        "status": "ok",
        "error": "",
        **metric_bundle,
        "timing": normalized_timing,
        "report": report_payload,
        "report_md_text": report_md_text,
        "eval_report_json_path": report_json_path,
        "eval_report_md_path": report_md_path,
        "duration_seconds": evaluation_wall_seconds,
    }


def _run_all_method_benchmark_global_queue(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    unmatched_targets: list[AllMethodUnmatchedGold],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    golden_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    canonical_alignment_cache_root: Path | None = None,
    prediction_reuse_cache_root: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    run_started = time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)

    effective_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    effective_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )
    resolved_source_scheduling = _normalize_all_method_source_scheduling(
        source_scheduling
    )
    resolved_source_shard_threshold_seconds = (
        _coerce_positive_float(source_shard_threshold_seconds)
        or ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
    )
    resolved_source_shard_max_parts = (
        _coerce_positive_int(source_shard_max_parts)
        or ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
    )
    resolved_source_shard_min_variants = (
        _coerce_positive_int(source_shard_min_variants)
        or ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
    )
    resolved_canonical_cache_root = (
        canonical_alignment_cache_root.expanduser()
        if canonical_alignment_cache_root is not None
        else _resolve_all_method_canonical_alignment_cache_root(
            root_output_dir=root_output_dir
        )
    )
    resolved_prediction_reuse_cache_root = (
        prediction_reuse_cache_root.expanduser()
        if prediction_reuse_cache_root is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    )
    resolved_dashboard_output_root = (
        dashboard_output_root.expanduser()
        if dashboard_output_root is not None
        else None
    )

    total_targets = len(target_variants)
    source_job_plans = _plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy=resolved_source_scheduling,
        shard_threshold_seconds=resolved_source_shard_threshold_seconds,
        shard_max_parts=resolved_source_shard_max_parts,
        shard_min_variants=resolved_source_shard_min_variants,
    )
    work_items = _plan_all_method_global_work_items(
        target_variants=target_variants,
        scheduling_strategy=resolved_source_scheduling,
        shard_threshold_seconds=resolved_source_shard_threshold_seconds,
        shard_max_parts=resolved_source_shard_max_parts,
        shard_min_variants=resolved_source_shard_min_variants,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        canonical_alignment_cache_root=resolved_canonical_cache_root,
    )
    total_planned_config_runs = len(work_items)
    source_parallelism_default = min(
        _all_method_default_parallel_sources_from_cpu(),
        max(1, total_targets),
    )
    requested_source_parallelism = _report_count(max_parallel_sources)
    source_parallelism_configured = (
        requested_source_parallelism
        if requested_source_parallelism > 0
        else source_parallelism_default
    )
    source_parallelism_effective = _resolve_all_method_source_parallelism(
        total_sources=max(1, total_targets),
        requested=max_parallel_sources,
    )

    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=max(1, total_planned_config_runs),
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=1,
    )
    configured_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    requested_split_phase_slots = scheduler_runtime.split_phase_slots_requested
    effective_split_phase_slots = scheduler_runtime.split_phase_slots
    split_phase_slot_mode = scheduler_runtime.split_phase_slot_mode
    split_phase_slot_cap_by_cpu = scheduler_runtime.split_phase_slot_cap_by_cpu
    split_phase_slot_cap_by_memory = scheduler_runtime.split_phase_slot_cap_by_memory
    effective_wing_backlog_target = scheduler_runtime.wing_backlog_target
    configured_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_configured
    effective_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_effective
    eval_tail_headroom_mode = scheduler_runtime.eval_tail_headroom_mode
    effective_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    max_active_during_eval = scheduler_runtime.max_active_during_eval
    effective_inflight_pipelines = scheduler_runtime.effective_inflight_pipelines
    adaptive_overcommit_limit = scheduler_runtime.adaptive_overcommit_limit
    adaptive_max_guard_target = scheduler_runtime.adaptive_max_guard_target
    scheduler_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    scheduler_cpu_budget_total = scheduler_runtime.cpu_budget_total
    split_worker_cap_per_config, split_worker_guard = _resolve_all_method_split_worker_cap(
        split_phase_slots=effective_split_phase_slots,
        source_parallelism_effective=1,
    )

    max_requested_split_workers = max(
        [
            max(
                max(1, _report_count(item.variant.run_settings.workers)),
                max(1, _report_count(item.variant.run_settings.pdf_split_workers)),
                max(1, _report_count(item.variant.run_settings.epub_split_workers)),
            )
            for item in work_items
        ],
        default=1,
    )

    split_phase_gate_dir = root_output_dir / ".split_phase_slots"
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    scheduler_events_dir = root_output_dir / ".scheduler_events"
    scheduler_timeseries_path = root_output_dir / ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    if scheduler_events_dir.exists():
        shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    if scheduler_timeseries_path.exists():
        scheduler_timeseries_path.unlink()

    status_lock = threading.RLock()
    source_totals: dict[int, int] = {
        source_position: len(variants)
        for source_position, (_target, variants) in enumerate(target_variants)
    }
    source_active: dict[int, int] = defaultdict(int)
    source_completed: dict[int, int] = defaultdict(int)
    source_failed_seen: dict[int, bool] = defaultdict(bool)

    def _emit_status(
        message: str,
        *,
        color: typer.colors = typer.colors.CYAN,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned:
            return
        with status_lock:
            if progress_callback is not None:
                if dashboard is not None:
                    dashboard.set_task(cleaned)
                    _notify_progress_callback(progress_callback, dashboard.render())
                else:
                    _notify_progress_callback(progress_callback, cleaned)
                return
            typer.secho(cleaned, fg=color)

    if split_phase_slot_mode != "configured":
        _emit_status(
            (
                "Resource guard capped split slots to "
                f"{effective_split_phase_slots} "
                f"(requested {requested_split_phase_slots}; "
                f"cpu cap {split_phase_slot_cap_by_cpu}; "
                f"memory cap {split_phase_slot_cap_by_memory})."
            ),
            color=typer.colors.YELLOW,
        )

    if split_worker_cap_per_config < max_requested_split_workers:
        _emit_status(
            (
                "Resource guard capped split workers per active config to "
                f"{split_worker_cap_per_config} "
                f"(requested peak {max_requested_split_workers}; "
                f"split slots {effective_split_phase_slots})."
            ),
            color=typer.colors.YELLOW,
        )

    scheduler_phase_by_config: dict[int, str] = {}
    scheduler_event_offsets: dict[int, int] = {}
    scheduler_last_tick = time.monotonic()
    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_last_snapshot = ""
    scheduler_timeseries_last_snapshot = ""
    scheduler_timeseries_last_write_monotonic = run_started
    scheduler_timeseries_rows_written = 0
    scheduler_timeseries_heartbeat_seconds = max(
        ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS,
        ALL_METHOD_SCHEDULER_POLL_SECONDS,
    )
    scheduler_cpu_source = "proc_stat_linux"
    scheduler_cpu_samples_collected = 0
    scheduler_cpu_totals_last: tuple[int, int] | None = None
    scheduler_cpu_utilization_pct_last: float | None = None
    scheduler_cpu_utilization_pct_high_water = 0.0
    scheduler_admission_adjustments = 0
    scheduler_admission_pressure_boosts = 0
    scheduler_admission_saturation_clamps = 0
    scheduler_admission_cpu_hot_clamps = 0
    scheduler_admission_active_cap_peak = configured_inflight_pipelines
    scheduler_admission_guard_target_peak = min(
        max(1, total_planned_config_runs),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_last_key: tuple[int, int, str] | None = None
    scheduler_admission_active_cap_current = configured_inflight_pipelines
    scheduler_admission_guard_target_current = min(
        max(1, total_planned_config_runs),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_wing_target_current = effective_wing_backlog_target
    scheduler_admission_reason_current = "base"
    process_worker_probe_available: bool | None = None
    process_worker_probe_error: str | None = None
    config_executor_backends_seen: set[str] = set()

    def _scheduler_event_path(config_index: int) -> Path:
        return scheduler_events_dir / f"config_{config_index:03d}.jsonl"

    def _read_linux_cpu_totals() -> tuple[int, int] | None:
        try:
            with Path("/proc/stat").open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return None
        line = str(first_line or "").strip()
        if not line:
            return None
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        values: list[int] = []
        for token in parts[1:]:
            try:
                values.append(int(token))
            except ValueError:
                return None
        if len(values) < 4:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle

    def _sample_host_cpu_utilization_pct() -> float | None:
        nonlocal scheduler_cpu_source
        nonlocal scheduler_cpu_samples_collected
        nonlocal scheduler_cpu_totals_last

        current = _read_linux_cpu_totals()
        if current is None:
            scheduler_cpu_source = "unavailable"
            scheduler_cpu_totals_last = None
            return None
        previous = scheduler_cpu_totals_last
        scheduler_cpu_totals_last = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        busy_delta = max(0, total_delta - max(0, idle_delta))
        scheduler_cpu_samples_collected += 1
        return max(0.0, min(100.0, (float(busy_delta) / float(total_delta)) * 100.0))

    def _scheduler_phase_for_event(event_name: str) -> str | None:
        event = str(event_name or "").strip()
        if event in {"config_started", "prep_started"}:
            return "prep"
        if event == "split_wait_started":
            return "split_wait"
        if event == "split_active_started":
            return "split_active"
        if event in {"split_active_finished", "post_started"}:
            return "post"
        if event in {"post_finished", "evaluate_started"}:
            return "evaluate"
        if event in {"evaluate_finished", "config_finished"}:
            return "done"
        return None

    def _poll_scheduler_events(active_indices: set[int]) -> None:
        for active_index in sorted(active_indices):
            event_path = _scheduler_event_path(active_index)
            if not event_path.exists():
                continue
            offset = max(0, scheduler_event_offsets.get(active_index, 0))
            with event_path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    phase = _scheduler_phase_for_event(str(payload.get("event") or ""))
                    if phase is not None:
                        scheduler_phase_by_config[active_index] = phase
                scheduler_event_offsets[active_index] = handle.tell()

    def _compute_scheduler_counts(active_indices: set[int]) -> dict[str, int]:
        heavy_active = 0
        split_wait = 0
        prep_active = 0
        post_active = 0
        evaluate_active = 0
        for active_index in active_indices:
            phase = scheduler_phase_by_config.get(active_index, "prep")
            if phase == "split_active":
                heavy_active += 1
            elif phase == "split_wait":
                split_wait += 1
            elif phase == "post":
                post_active += 1
            elif phase == "evaluate":
                evaluate_active += 1
            elif phase == "done":
                continue
            else:
                prep_active += 1
        wing_backlog = split_wait + prep_active
        return {
            "heavy_active": heavy_active,
            "split_wait": split_wait,
            "prep_active": prep_active,
            "post_active": post_active,
            "evaluate_active": evaluate_active,
            "wing_backlog": wing_backlog,
            "active": len(active_indices),
        }

    def _tick_scheduler_metrics(*, active_indices: set[int], pending_count: int) -> dict[str, int]:
        nonlocal scheduler_last_tick
        nonlocal scheduler_capacity_seconds
        nonlocal scheduler_busy_seconds
        nonlocal scheduler_idle_gap_seconds
        nonlocal scheduler_wing_area_seconds
        nonlocal scheduler_max_wing_backlog
        nonlocal scheduler_max_active_pipelines
        nonlocal scheduler_max_eval_active
        nonlocal scheduler_cpu_utilization_pct_last
        nonlocal scheduler_cpu_utilization_pct_high_water

        now = time.monotonic()
        delta = max(0.0, now - scheduler_last_tick)
        counts = _compute_scheduler_counts(active_indices)
        scheduler_capacity_seconds += float(effective_split_phase_slots) * delta
        scheduler_busy_seconds += float(
            min(effective_split_phase_slots, counts["heavy_active"])
        ) * delta
        if pending_count > 0 and counts["heavy_active"] < effective_split_phase_slots:
            scheduler_idle_gap_seconds += delta
        scheduler_wing_area_seconds += float(counts["wing_backlog"]) * delta
        scheduler_max_wing_backlog = max(scheduler_max_wing_backlog, counts["wing_backlog"])
        scheduler_max_active_pipelines = max(
            scheduler_max_active_pipelines,
            counts["active"],
        )
        scheduler_max_eval_active = max(
            scheduler_max_eval_active,
            counts["evaluate_active"],
        )
        sampled_cpu = _sample_host_cpu_utilization_pct()
        if sampled_cpu is not None:
            scheduler_cpu_utilization_pct_last = sampled_cpu
            scheduler_cpu_utilization_pct_high_water = max(
                scheduler_cpu_utilization_pct_high_water,
                sampled_cpu,
            )
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return (
            f"scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} "
            f"| wing {counts['wing_backlog']} "
            f"| eval {counts['evaluate_active']} "
            f"| active {counts['active']} | pending {max(0, pending_count)}"
        )

    def _write_scheduler_timeseries_row(
        *,
        counts: dict[str, int],
        pending_count: int,
        force: bool = False,
    ) -> None:
        nonlocal scheduler_timeseries_last_snapshot
        nonlocal scheduler_timeseries_last_write_monotonic
        nonlocal scheduler_timeseries_rows_written

        pending_safe = max(0, pending_count)
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_safe)
        now_monotonic = time.monotonic()
        write_due = (
            force
            or snapshot != scheduler_timeseries_last_snapshot
            or (
                now_monotonic - scheduler_timeseries_last_write_monotonic
                >= scheduler_timeseries_heartbeat_seconds
            )
        )
        if not write_due:
            return
        row = {
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": now_monotonic,
            "elapsed_seconds": max(0.0, now_monotonic - run_started),
            "snapshot": snapshot,
            "heavy_active": _report_count(counts.get("heavy_active")),
            "heavy_capacity": _report_count(effective_split_phase_slots),
            "split_wait": _report_count(counts.get("split_wait")),
            "prep_active": _report_count(counts.get("prep_active")),
            "post_active": _report_count(counts.get("post_active")),
            "evaluate_active": _report_count(counts.get("evaluate_active")),
            "wing_backlog": _report_count(counts.get("wing_backlog")),
            "active": _report_count(counts.get("active")),
            "pending": pending_safe,
            "cpu_utilization_pct": scheduler_cpu_utilization_pct_last,
            "admission_active_cap": scheduler_admission_active_cap_current,
            "admission_guard_target": scheduler_admission_guard_target_current,
            "admission_wing_target": scheduler_admission_wing_target_current,
            "admission_reason": scheduler_admission_reason_current,
        }
        try:
            with scheduler_timeseries_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception:
            return
        scheduler_timeseries_last_snapshot = snapshot
        scheduler_timeseries_last_write_monotonic = now_monotonic
        scheduler_timeseries_rows_written += 1

    def _emit_scheduler_snapshot(
        *,
        counts: dict[str, int],
        pending_count: int,
        force_timeseries: bool = False,
    ) -> None:
        nonlocal scheduler_last_snapshot
        _write_scheduler_timeseries_row(
            counts=counts,
            pending_count=pending_count,
            force=force_timeseries,
        )
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(
            counts=counts,
            pending_count=max(0, pending_count),
        )
        if snapshot == scheduler_last_snapshot:
            return
        scheduler_last_snapshot = snapshot
        _emit_status(snapshot, color=typer.colors.BRIGHT_BLACK)

    item_by_global_index: dict[int, _AllMethodGlobalWorkItem] = {
        item.global_dispatch_index: item for item in work_items
    }
    variant_rows: list[dict[str, Any]] = []

    def _annotate_prediction_row(
        *,
        item: _AllMethodGlobalWorkItem,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(row)
        payload["global_dispatch_index"] = item.global_dispatch_index
        payload["source_position"] = item.source_position
        payload["source_group_key"] = item.source_group_key
        payload["source_slug"] = item.source_group_key
        payload["source_file"] = str(item.source_file)
        payload["source_file_name"] = item.source_file_name
        payload["gold_spans_path"] = str(item.gold_spans_path)
        payload["source_config_index"] = item.config_index
        payload["source_config_total"] = item.config_total
        payload["source_shard_index"] = item.source_shard_index + 1
        payload["source_shard_total"] = max(1, _report_count(item.source_shard_total))
        payload["source_estimated_seconds"] = item.source_estimated_seconds
        payload["source_estimate_basis"] = item.source_estimate_basis
        payload["_source_root"] = str(item.source_root)
        payload["_source_processed_root"] = str(item.source_processed_root)
        payload["_canonical_alignment_cache_dir"] = str(item.canonical_alignment_cache_dir)
        return payload

    def _latest_rows_by_dispatch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_by_index: dict[int, dict[str, Any]] = {}
        for row in rows:
            dispatch_index = _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            )
            latest_by_index[dispatch_index] = row
        return [latest_by_index[index] for index in sorted(latest_by_index)]

    def _mark_item_started(item: _AllMethodGlobalWorkItem, *, dashboard_tracking: bool) -> None:
        if not dashboard_tracking or dashboard is None:
            return
        source_position = item.source_position
        if source_active[source_position] <= 0:
            dashboard.start_source(source_position)
        source_active[source_position] += 1
        dashboard.start_config(
            source_index=source_position,
            config_index=item.config_index,
            config_total=max(1, item.config_total),
            config_slug=item.variant.slug,
        )

    def _mark_item_finished(
        item: _AllMethodGlobalWorkItem,
        *,
        success: bool,
        dashboard_tracking: bool,
    ) -> None:
        source_position = item.source_position
        source_active[source_position] = max(0, source_active[source_position] - 1)
        source_completed[source_position] += 1
        if not success:
            source_failed_seen[source_position] = True
        if not dashboard_tracking or dashboard is None:
            return
        dashboard.complete_config(
            source_index=source_position,
            success=success,
            config_index=item.config_index,
        )
        expected_total = max(0, _report_count(source_totals.get(source_position)))
        if (
            expected_total > 0
            and source_active[source_position] == 0
            and source_completed[source_position] >= expected_total
        ):
            dashboard.finish_source(
                source_position,
                failed=bool(source_failed_seen[source_position]),
            )

    def _run_serial_items(
        items: list[_AllMethodGlobalWorkItem],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        for item in items:
            progress_label = format_task_counter(
                "Running",
                item.global_dispatch_index,
                max(1, total_planned_config_runs),
                noun="config",
            )
            _mark_item_started(item, dashboard_tracking=dashboard_tracking)
            _emit_status(
                f"{progress_label}: {item.variant.slug} [{item.source_file_name}]",
                color=typer.colors.CYAN,
            )

            def _variant_progress(message: str) -> None:
                if progress_callback is None:
                    return
                if dashboard is None:
                    if _is_structured_progress_message(message):
                        _notify_progress_callback(progress_callback, message)
                        return
                    _notify_progress_callback(
                        progress_callback,
                        f"{progress_label}: {item.variant.slug} [{item.source_file_name}] | {message}",
                    )
                    return
                if _is_structured_progress_message(message):
                    _notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                _notify_progress_callback(progress_callback, dashboard.render())

            row = _run_all_method_prediction_once(
                gold_spans_path=item.gold_spans_path,
                source_file=item.source_file,
                variant=item.variant,
                config_index=item.global_dispatch_index,
                total_variants=max(1, total_planned_config_runs),
                root_output_dir=item.source_root,
                scratch_root=item.source_root / ".scratch",
                processed_output_root=item.source_processed_root,
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                max_concurrent_split_phases=effective_split_phase_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                scheduler_events_dir=scheduler_events_dir,
                alignment_cache_dir=item.canonical_alignment_cache_dir,
                prediction_reuse_cache_dir=resolved_prediction_reuse_cache_root,
                split_worker_cap_per_config=split_worker_cap_per_config,
                progress_callback=_variant_progress if progress_callback else None,
            )
            row = _annotate_prediction_row(item=item, row=row)
            variant_rows.append(row)

            success = str(row.get("status") or "").strip().lower() == "ok"
            _mark_item_finished(
                item,
                success=success,
                dashboard_tracking=dashboard_tracking,
            )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                            f"{item.variant.slug} [{item.source_file_name}]"
                        )
                    )
            else:
                _emit_status(
                    (
                        "Failed "
                        f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

    def _run_parallel_items(
        items: list[_AllMethodGlobalWorkItem],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        nonlocal process_worker_probe_available
        nonlocal process_worker_probe_error
        nonlocal scheduler_admission_adjustments
        nonlocal scheduler_admission_pressure_boosts
        nonlocal scheduler_admission_saturation_clamps
        nonlocal scheduler_admission_cpu_hot_clamps
        nonlocal scheduler_admission_active_cap_peak
        nonlocal scheduler_admission_guard_target_peak
        nonlocal scheduler_admission_last_key
        nonlocal scheduler_admission_active_cap_current
        nonlocal scheduler_admission_guard_target_current
        nonlocal scheduler_admission_wing_target_current
        nonlocal scheduler_admission_reason_current

        force_parallel_timeout = effective_config_timeout_seconds is not None
        serial_by_limits = (
            len(items) <= 1 or effective_inflight_pipelines <= 1
        ) and not force_parallel_timeout
        if serial_by_limits:
            config_executor_backends_seen.add("serial")
            _run_serial_items(items, dashboard_tracking=dashboard_tracking)
            return
        executor_backend = "process"
        process_workers_available, process_worker_error = (
            _probe_all_method_process_pool_executor()
        )
        if process_workers_available:
            picklable, picklable_error = _probe_all_method_process_worker_picklable()
            if not picklable:
                process_workers_available = False
                process_worker_error = picklable_error
        process_worker_probe_available = bool(process_workers_available)
        process_worker_probe_error = (
            str(process_worker_error).strip() if process_worker_error else None
        )
        if not process_workers_available:
            detail = (
                f" ({process_worker_error})"
                if isinstance(process_worker_error, str) and process_worker_error
                else ""
            )
            if require_process_workers:
                raise RuntimeError(
                    "Process-based config concurrency is required, but runtime probe "
                    f"reported it unavailable{detail}."
                )
            _emit_status(
                (
                    "Process-based config concurrency unavailable"
                    f"{detail}; using thread-based config concurrency."
                ),
                color=typer.colors.YELLOW,
            )
            executor_backend = "thread"
        config_executor_backends_seen.add(str(executor_backend))

        pending_items = list(items)
        futures: dict[Any, tuple[_AllMethodGlobalWorkItem, float]] = {}
        worker_limit = min(effective_inflight_pipelines, max(1, len(items)))
        scheduler_base_target = min(
            max(1, total_planned_config_runs),
            effective_split_phase_slots + effective_wing_backlog_target,
        )
        scheduler_smart_enabled = bool(effective_smart_scheduler)

        try:
            executor = (
                _create_all_method_process_pool_executor(max_workers=worker_limit)
                if executor_backend == "process"
                else ThreadPoolExecutor(max_workers=worker_limit)
            )
        except (PermissionError, OSError) as exc:
            if executor_backend == "process":
                if require_process_workers:
                    raise RuntimeError(
                        "Process-based config concurrency is required, but process "
                        f"executor startup failed: {exc}"
                    ) from exc
                _emit_status(
                    (
                        "Process-based config concurrency unavailable "
                        f"({exc}); using thread-based config concurrency."
                    ),
                    color=typer.colors.YELLOW,
                )
                executor_backend = "thread"
                config_executor_backends_seen.add("thread")
                try:
                    executor = ThreadPoolExecutor(max_workers=worker_limit)
                except Exception as thread_exc:  # noqa: BLE001
                    _emit_status(
                        (
                            "Thread-based config concurrency unavailable "
                            f"({thread_exc}); running single-config execution."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    config_executor_backends_seen.add("serial")
                    _run_serial_items(items, dashboard_tracking=dashboard_tracking)
                    return
            else:
                _emit_status(
                    (
                        "Thread-based config concurrency unavailable "
                        f"({exc}); running single-config execution."
                    ),
                    color=typer.colors.YELLOW,
                )
                config_executor_backends_seen.add("serial")
                _run_serial_items(items, dashboard_tracking=dashboard_tracking)
                return

        def _record_completion(
            *,
            item: _AllMethodGlobalWorkItem,
            row: dict[str, Any],
        ) -> None:
            variant_rows.append(row)
            success = str(row.get("status") or "").strip().lower() == "ok"
            scheduler_phase_by_config.pop(item.global_dispatch_index, None)
            scheduler_event_offsets.pop(item.global_dispatch_index, None)
            _mark_item_finished(item, success=success, dashboard_tracking=dashboard_tracking)
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                            f"{item.variant.slug} [{item.source_file_name}]"
                        )
                    )
            else:
                _emit_status(
                    (
                        "Failed "
                        f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

        def _submit_next() -> bool:
            if not pending_items:
                return False
            item = pending_items.pop(0)
            progress_label = format_task_counter(
                "Running",
                item.global_dispatch_index,
                max(1, total_planned_config_runs),
                noun="config",
            )
            _mark_item_started(item, dashboard_tracking=dashboard_tracking)
            _emit_status(
                f"{progress_label}: {item.variant.slug} [{item.source_file_name}]",
                color=typer.colors.CYAN,
            )

            try:
                future = executor.submit(
                    _run_all_method_prediction_once,
                    gold_spans_path=item.gold_spans_path,
                    source_file=item.source_file,
                    variant=item.variant,
                    config_index=item.global_dispatch_index,
                    total_variants=max(1, total_planned_config_runs),
                    root_output_dir=item.source_root,
                    scratch_root=item.source_root / ".scratch",
                    processed_output_root=item.source_processed_root,
                    overlap_threshold=overlap_threshold,
                    force_source_match=force_source_match,
                    max_concurrent_split_phases=effective_split_phase_slots,
                    split_phase_gate_dir=split_phase_gate_dir,
                    scheduler_events_dir=scheduler_events_dir,
                    alignment_cache_dir=item.canonical_alignment_cache_dir,
                    prediction_reuse_cache_dir=resolved_prediction_reuse_cache_root,
                    split_worker_cap_per_config=split_worker_cap_per_config,
                    progress_callback=None,
                )
            except Exception as exc:  # noqa: BLE001
                row = _all_method_failed_row(
                    config_index=item.global_dispatch_index,
                    config_dir_name=_all_method_config_dir_name(
                        item.global_dispatch_index,
                        item.variant,
                    ),
                    variant=item.variant,
                    error=f"Failed to submit benchmark config: {exc}",
                )
                _record_completion(item=item, row=_annotate_prediction_row(item=item, row=row))
                return True

            futures[future] = (item, time.monotonic())
            scheduler_phase_by_config[item.global_dispatch_index] = "prep"
            scheduler_event_offsets[item.global_dispatch_index] = 0
            return True

        def _refresh_admission_decision(
            *,
            counts: dict[str, int],
            pending_count: int,
        ) -> _AllMethodSchedulerAdmissionDecision:
            nonlocal scheduler_admission_adjustments
            nonlocal scheduler_admission_pressure_boosts
            nonlocal scheduler_admission_saturation_clamps
            nonlocal scheduler_admission_cpu_hot_clamps
            nonlocal scheduler_admission_active_cap_peak
            nonlocal scheduler_admission_guard_target_peak
            nonlocal scheduler_admission_last_key
            nonlocal scheduler_admission_active_cap_current
            nonlocal scheduler_admission_guard_target_current
            nonlocal scheduler_admission_wing_target_current
            nonlocal scheduler_admission_reason_current

            decision = _resolve_all_method_scheduler_admission(
                counts=counts,
                pending_count=pending_count,
                total_variants=max(1, total_planned_config_runs),
                configured_inflight_pipelines=configured_inflight_pipelines,
                split_phase_slots=effective_split_phase_slots,
                wing_backlog_target=effective_wing_backlog_target,
                max_active_during_eval=max_active_during_eval,
                adaptive_overcommit_limit=adaptive_overcommit_limit,
                adaptive_max_guard_target=max(
                    scheduler_base_target,
                    adaptive_max_guard_target,
                ),
                smart_scheduler_enabled=scheduler_smart_enabled,
                cpu_utilization_pct=scheduler_cpu_utilization_pct_last,
            )
            decision_key = (decision.active_cap, decision.guard_target, decision.reason)
            if scheduler_admission_last_key is None:
                scheduler_admission_last_key = decision_key
            elif decision_key != scheduler_admission_last_key:
                scheduler_admission_adjustments += 1
                scheduler_admission_last_key = decision_key
                if decision.pressure_boost > 0:
                    scheduler_admission_pressure_boosts += 1
                if decision.saturation_clamp:
                    scheduler_admission_saturation_clamps += 1
                if decision.cpu_hot_clamp:
                    scheduler_admission_cpu_hot_clamps += 1
            scheduler_admission_active_cap_peak = max(
                scheduler_admission_active_cap_peak,
                decision.active_cap,
            )
            scheduler_admission_guard_target_peak = max(
                scheduler_admission_guard_target_peak,
                decision.guard_target,
            )
            scheduler_admission_active_cap_current = decision.active_cap
            scheduler_admission_guard_target_current = decision.guard_target
            scheduler_admission_wing_target_current = decision.wing_target
            scheduler_admission_reason_current = decision.reason
            return decision

        try:
            while pending_items or futures:
                active_indices = {
                    item.global_dispatch_index
                    for item, _submitted in futures.values()
                }
                counts = _tick_scheduler_metrics(
                    active_indices=active_indices,
                    pending_count=len(pending_items),
                )
                if active_indices:
                    try:
                        _poll_scheduler_events(active_indices)
                    except Exception:
                        scheduler_smart_enabled = False
                counts = _compute_scheduler_counts(
                    {
                        item.global_dispatch_index
                        for item, _submitted in futures.values()
                    }
                )
                if dashboard_tracking and dashboard is not None:
                    for active_item, _submitted in futures.values():
                        dashboard.set_config_phase(
                            source_index=active_item.source_position,
                            config_index=active_item.config_index,
                            phase=scheduler_phase_by_config.get(
                                active_item.global_dispatch_index,
                                "prep",
                            ),
                        )
                admission_decision = _refresh_admission_decision(
                    counts=counts,
                    pending_count=len(pending_items),
                )
                _emit_scheduler_snapshot(
                    counts=counts,
                    pending_count=len(pending_items),
                )

                while len(futures) < worker_limit and pending_items:
                    heavy_plus_wing = counts["heavy_active"] + counts["wing_backlog"]
                    if counts["active"] >= admission_decision.active_cap:
                        break
                    if (
                        heavy_plus_wing >= admission_decision.guard_target
                        and counts["active"] >= configured_inflight_pipelines
                    ):
                        break
                    submitted = _submit_next()
                    if not submitted:
                        break
                    counts = _compute_scheduler_counts(
                        {
                            item.global_dispatch_index
                            for item, _submitted in futures.values()
                        }
                    )
                    admission_decision = _refresh_admission_decision(
                        counts=counts,
                        pending_count=len(pending_items),
                    )
                    _emit_scheduler_snapshot(
                        counts=counts,
                        pending_count=len(pending_items),
                    )

                if not futures:
                    if pending_items:
                        time.sleep(ALL_METHOD_SCHEDULER_POLL_SECONDS)
                    continue

                done, _ = wait(
                    list(futures.keys()),
                    timeout=ALL_METHOD_SCHEDULER_POLL_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                for done_future in done:
                    item, _submitted = futures.pop(done_future)
                    try:
                        row = done_future.result()
                    except Exception as exc:  # noqa: BLE001
                        row = _all_method_failed_row(
                            config_index=item.global_dispatch_index,
                            config_dir_name=_all_method_config_dir_name(
                                item.global_dispatch_index,
                                item.variant,
                            ),
                            variant=item.variant,
                            error=f"Benchmark config worker failed: {exc}",
                        )
                    _record_completion(
                        item=item,
                        row=_annotate_prediction_row(item=item, row=row),
                    )

                if (
                    effective_config_timeout_seconds is None
                    or executor_backend != "process"
                ):
                    continue
                timeout_threshold = float(max(1, effective_config_timeout_seconds))
                now = time.monotonic()
                timed_out: list[tuple[Any, _AllMethodGlobalWorkItem, float]] = []
                for future, (item, submitted_at) in list(futures.items()):
                    elapsed_seconds = max(0.0, now - submitted_at)
                    if elapsed_seconds < timeout_threshold:
                        continue
                    timed_out.append((future, item, elapsed_seconds))
                if not timed_out:
                    continue

                timed_out.sort(key=lambda item: item[1].global_dispatch_index)
                for timed_out_future, item, elapsed_seconds in timed_out:
                    futures.pop(timed_out_future, None)
                    row = _all_method_failed_row(
                        config_index=item.global_dispatch_index,
                        config_dir_name=_all_method_config_dir_name(
                            item.global_dispatch_index,
                            item.variant,
                        ),
                        variant=item.variant,
                        error=(
                            f"Config timed out after {int(timeout_threshold)}s "
                            f"(elapsed {elapsed_seconds:.1f}s)."
                        ),
                        elapsed_seconds=elapsed_seconds,
                    )
                    _record_completion(
                        item=item,
                        row=_annotate_prediction_row(item=item, row=row),
                    )

                if futures:
                    requeued = sorted(
                        [item for item, _submitted in futures.values()],
                        key=lambda item: item.global_dispatch_index,
                    )
                    pending_items = requeued + pending_items
                    futures.clear()
                scheduler_smart_enabled = False
                _emit_status(
                    (
                        "Config timeout reached for "
                        f"{len(timed_out)} run(s); restarting process worker pool."
                    ),
                    color=typer.colors.YELLOW,
                )
                shutdown_fn = getattr(executor, "shutdown", None)
                if callable(shutdown_fn):
                    try:
                        shutdown_fn(wait=False, cancel_futures=True)
                    except TypeError:
                        shutdown_fn(wait=False)
                try:
                    executor = _create_all_method_process_pool_executor(
                        max_workers=worker_limit
                    )
                except (PermissionError, OSError) as exc:
                    if require_process_workers:
                        raise RuntimeError(
                            "Process-based config concurrency is required, but process "
                            f"pool restart failed after timeout: {exc}"
                        ) from exc
                    _emit_status(
                        (
                            "Process-based config concurrency unavailable after timeout "
                            f"restart ({exc}); using thread-based config concurrency for remaining configs."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    executor_backend = "thread"
                    config_executor_backends_seen.add("thread")
                    try:
                        executor = ThreadPoolExecutor(max_workers=worker_limit)
                    except Exception as thread_exc:  # noqa: BLE001
                        _emit_status(
                            (
                                "Thread-based config concurrency unavailable "
                                f"({thread_exc}); running remaining configs as single-config execution."
                            ),
                            color=typer.colors.YELLOW,
                        )
                        config_executor_backends_seen.add("serial")
                        _run_serial_items(
                            pending_items,
                            dashboard_tracking=dashboard_tracking,
                        )
                        pending_items.clear()
                        futures.clear()
                        break
        finally:
            shutdown_fn = getattr(executor, "shutdown", None)
            if callable(shutdown_fn):
                try:
                    shutdown_fn(wait=True, cancel_futures=False)
                except TypeError:
                    shutdown_fn(wait=True)

    _run_parallel_items(work_items, dashboard_tracking=True)
    variant_rows = _latest_rows_by_dispatch(variant_rows)
    initial_failed_indices = [
        _report_count(
            row.get("global_dispatch_index", row.get("config_index"))
        )
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    retry_passes_executed = 0
    retry_recovered_configs = 0
    if effective_retry_failed_configs > 0 and initial_failed_indices:
        remaining_failed_indices = sorted(set(initial_failed_indices))
        for retry_pass in range(1, effective_retry_failed_configs + 1):
            if not remaining_failed_indices:
                break
            retry_items = [
                item_by_global_index[index]
                for index in remaining_failed_indices
                if index in item_by_global_index
            ]
            if not retry_items:
                break
            retry_passes_executed += 1
            _emit_status(
                (
                    f"Retry pass {retry_pass}/{effective_retry_failed_configs}: "
                    f"rerunning {len(retry_items)} failed config(s)."
                ),
                color=typer.colors.YELLOW,
            )
            prior_failed = set(remaining_failed_indices)
            _run_parallel_items(retry_items, dashboard_tracking=False)
            variant_rows = _latest_rows_by_dispatch(variant_rows)
            remaining_failed_indices = sorted(
                {
                    _report_count(
                        row.get("global_dispatch_index", row.get("config_index"))
                    )
                    for row in variant_rows
                    if str(row.get("status") or "").strip().lower() != "ok"
                }
            )
            recovered_this_pass = len(prior_failed - set(remaining_failed_indices))
            retry_recovered_configs += max(0, recovered_this_pass)
            if recovered_this_pass > 0:
                _emit_status(
                    (
                        f"Retry pass {retry_pass} recovered "
                        f"{recovered_this_pass} config(s)."
                    ),
                    color=typer.colors.CYAN,
                )

    _tick_scheduler_metrics(active_indices=set(), pending_count=0)
    _emit_scheduler_snapshot(
        counts=_compute_scheduler_counts(set()),
        pending_count=0,
        force_timeseries=True,
    )

    scheduler_utilization_pct = (
        (scheduler_busy_seconds / scheduler_capacity_seconds) * 100.0
        if scheduler_capacity_seconds > 0
        else 0.0
    )
    scheduler_avg_wing_backlog = (
        scheduler_wing_area_seconds / scheduler_capacity_seconds
        if scheduler_capacity_seconds > 0
        else 0.0
    )
    scheduler_summary: dict[str, Any] = {
        "mode": "smart" if bool(effective_smart_scheduler) else "fixed",
        "source_count": max(1, total_targets),
        "configured_inflight_pipelines": configured_inflight_pipelines,
        "effective_inflight_pipelines": effective_inflight_pipelines,
        "split_phase_slots_requested": requested_split_phase_slots,
        "split_phase_slots": effective_split_phase_slots,
        "split_phase_slot_mode": split_phase_slot_mode,
        "split_phase_slot_cap_by_cpu": split_phase_slot_cap_by_cpu,
        "split_phase_slot_cap_by_memory": split_phase_slot_cap_by_memory,
        "wing_backlog_target": effective_wing_backlog_target,
        "split_worker_cap_per_config": split_worker_cap_per_config,
        "split_worker_cap_by_cpu": split_worker_guard.get("split_worker_cap_by_cpu"),
        "split_worker_cap_by_memory": split_worker_guard.get("split_worker_cap_by_memory"),
        "eval_tail_headroom_mode": eval_tail_headroom_mode,
        "eval_tail_headroom_configured": configured_eval_tail_headroom,
        "eval_tail_headroom_effective": effective_eval_tail_headroom,
        "max_active_during_eval": max_active_during_eval,
        "adaptive_overcommit_limit": adaptive_overcommit_limit,
        "adaptive_max_guard_target": adaptive_max_guard_target,
        "source_parallelism_effective": 1,
        "cpu_budget_per_source": scheduler_cpu_budget_per_source,
        "cpu_budget_total": scheduler_cpu_budget_total,
        "max_eval_tail_pipelines": effective_eval_tail_headroom,
        "smart_tail_buffer_slots": (
            effective_eval_tail_headroom if bool(effective_smart_scheduler) else 0
        ),
        "smart_scheduler_enabled": bool(effective_smart_scheduler),
        "config_timeout_seconds": effective_config_timeout_seconds,
        "failed_retry_limit": effective_retry_failed_configs,
        "retry_passes_executed": retry_passes_executed,
        "retry_recovered_configs": retry_recovered_configs,
        "heavy_slot_capacity_seconds": scheduler_capacity_seconds,
        "heavy_slot_busy_seconds": scheduler_busy_seconds,
        "heavy_slot_utilization_pct": scheduler_utilization_pct,
        "avg_wing_backlog": scheduler_avg_wing_backlog,
        "max_wing_backlog": scheduler_max_wing_backlog,
        "idle_gap_seconds": scheduler_idle_gap_seconds,
        "max_active_pipelines_observed": scheduler_max_active_pipelines,
        "max_eval_active_observed": scheduler_max_eval_active,
        "adaptive_admission_adjustments": scheduler_admission_adjustments,
        "adaptive_admission_pressure_boosts": scheduler_admission_pressure_boosts,
        "adaptive_admission_saturation_clamps": scheduler_admission_saturation_clamps,
        "adaptive_admission_cpu_hot_clamps": scheduler_admission_cpu_hot_clamps,
        "adaptive_admission_active_cap_peak": scheduler_admission_active_cap_peak,
        "adaptive_admission_guard_target_peak": scheduler_admission_guard_target_peak,
        "timeseries_path": str(scheduler_timeseries_path),
        "timeseries_row_count": scheduler_timeseries_rows_written,
        "timeseries_heartbeat_seconds": scheduler_timeseries_heartbeat_seconds,
        "snapshot_poll_seconds": ALL_METHOD_SCHEDULER_POLL_SECONDS,
        "cpu_utilization_source": scheduler_cpu_source,
        "cpu_utilization_samples": scheduler_cpu_samples_collected,
        "cpu_utilization_pct_high_water": scheduler_cpu_utilization_pct_high_water,
        "scheduler_scope": "global_config_queue",
    }

    variant_rows = _latest_rows_by_dispatch(variant_rows)
    prediction_success_rows = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    failed_rows: list[dict[str, Any]] = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    successful_rows: list[dict[str, Any]] = []
    signature_candidate_rows: list[dict[str, Any]] = []
    evaluation_signatures_unique = 0
    evaluation_runs_executed = 0
    evaluation_results_reused_in_run = 0
    evaluation_results_reused_cross_run = 0
    eval_signature_cache_dir = _resolve_all_method_eval_signature_cache_dir(
        root_output_dir=root_output_dir,
        alignment_cache_dir=resolved_canonical_cache_root / "__global__",
    )

    for row in prediction_success_rows:
        source_root_raw = str(row.get("_source_root") or "").strip()
        if not source_root_raw:
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Source root is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        prediction_record_path = _resolve_all_method_prediction_record_path(
            root_output_dir=Path(source_root_raw),
            row=row,
        )
        if (
            prediction_record_path is None
            or not prediction_record_path.exists()
            or not prediction_record_path.is_file()
        ):
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Prediction record path is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        sequence_matcher = str(row.get("benchmark_sequence_matcher") or "").strip() or "dmp"
        gold_spans_path = Path(str(row.get("gold_spans_path") or "").strip())
        try:
            eval_signature = _build_all_method_eval_signature(
                gold_spans_path=gold_spans_path,
                prediction_record_path=prediction_record_path,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
            )
        except Exception as exc:  # noqa: BLE001
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = f"Failed to build evaluation signature: {exc}"
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        row["eval_signature"] = eval_signature
        row["benchmark_sequence_matcher"] = sequence_matcher
        signature_candidate_rows.append(row)

    grouped_by_signature = _group_all_method_rows_by_eval_signature(signature_candidate_rows)
    evaluation_signatures_unique = len(grouped_by_signature)
    grouped_items = sorted(
        grouped_by_signature.items(),
        key=lambda item: min(
            _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            )
            for row in item[1]
        ),
    )
    for signature_index, (eval_signature, group_rows) in enumerate(grouped_items, start=1):
        if not group_rows:
            continue
        ordered_group = sorted(
            group_rows,
            key=lambda row: _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            ),
        )
        representative_row = ordered_group[0]
        representative_config_dir = str(representative_row.get("config_dir") or "").strip()
        if not representative_config_dir:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative config directory is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue

        source_root = Path(str(representative_row.get("_source_root") or ""))
        source_processed_root = Path(
            str(representative_row.get("_source_processed_root") or "")
        )
        canonical_alignment_cache_dir = Path(
            str(representative_row.get("_canonical_alignment_cache_dir") or "")
        )
        representative_eval_output_dir = source_root / representative_config_dir
        representative_processed_output_dir = source_processed_root / representative_config_dir
        representative_prediction_record = _resolve_all_method_prediction_record_path(
            root_output_dir=source_root,
            row=representative_row,
        )
        if representative_prediction_record is None:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative prediction record is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        sequence_matcher = str(representative_row.get("benchmark_sequence_matcher") or "").strip()
        if not sequence_matcher:
            sequence_matcher = "dmp"

        cache_path = eval_signature_cache_dir / f"{eval_signature}.json"
        cache_entry = _load_all_method_eval_signature_cache_entry(
            cache_path=cache_path,
            expected_signature=eval_signature,
        )
        evaluation_result_source_for_group = "executed"
        evaluation_summary: dict[str, Any]
        if cache_entry is not None:
            cached_report = cache_entry.get("report")
            if not isinstance(cached_report, dict):
                cached_report = {}
            cached_md = str(cache_entry.get("report_md") or "")
            eval_report_json_path, eval_report_md_path = (
                _materialize_all_method_cached_eval_outputs(
                    eval_output_dir=representative_eval_output_dir,
                    report_payload=cached_report,
                    report_md_text=cached_md,
                )
            )
            metric_bundle = _benchmark_report_metric_bundle(cached_report)
            evaluation_summary = {
                "status": "ok",
                "error": "",
                **metric_bundle,
                "timing": _normalize_timing_payload(cached_report.get("timing")),
                "report": cached_report,
                "report_md_text": cached_md,
                "eval_report_json_path": eval_report_json_path,
                "eval_report_md_path": eval_report_md_path,
                "duration_seconds": 0.0,
            }
            evaluation_result_source_for_group = "reused_cross_run"
            evaluation_results_reused_cross_run += len(ordered_group)
        else:
            _emit_status(
                (
                    "Evaluating signature "
                    f"{signature_index}/{max(1, evaluation_signatures_unique)} "
                    f"(group size {len(ordered_group)})."
                ),
                color=typer.colors.CYAN,
            )
            evaluation_summary = _run_all_method_evaluate_prediction_record_once(
                gold_spans_path=Path(str(representative_row.get("gold_spans_path") or "")),
                source_file=Path(str(representative_row.get("source_file") or "")),
                prediction_record_path=representative_prediction_record,
                eval_output_dir=representative_eval_output_dir,
                processed_output_dir=representative_processed_output_dir,
                sequence_matcher=sequence_matcher,
                epub_extractor=_row_dimension_str(representative_row, "epub_extractor"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                alignment_cache_dir=canonical_alignment_cache_dir,
                progress_callback=None,
            )
            if str(evaluation_summary.get("status") or "").strip().lower() == "ok":
                evaluation_runs_executed += 1
                if len(ordered_group) > 1:
                    evaluation_results_reused_in_run += len(ordered_group) - 1
                cached_payload = {
                    "schema_version": ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION,
                    "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "eval_signature": eval_signature,
                    "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                    "sequence_matcher": sequence_matcher,
                    "source_file": str(representative_row.get("source_file") or ""),
                    "gold_spans_path": str(representative_row.get("gold_spans_path") or ""),
                    "report": evaluation_summary.get("report"),
                    "report_md": evaluation_summary.get("report_md_text"),
                }
                try:
                    _write_all_method_eval_signature_cache_entry(
                        cache_path=cache_path,
                        payload=cached_payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Ignoring eval-signature cache write failure for %s: %s",
                        cache_path,
                        exc,
                    )

        if str(evaluation_summary.get("status") or "").strip().lower() != "ok":
            error_text = str(evaluation_summary.get("error") or "Evaluation failed.")
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = error_text
                failed_row["evaluation_result_source"] = "failed"
                failed_row["evaluation_representative_config_dir"] = representative_config_dir
                failed_row["eval_signature"] = eval_signature
                failed_rows.append(failed_row)
            continue

        summary_timing = _normalize_timing_payload(evaluation_summary.get("timing"))
        summary_evaluation_seconds = _report_optional_metric(
            summary_timing.get("evaluation_seconds")
        )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                summary_timing.get("total_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                evaluation_summary.get("duration_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = 0.0
        summary_eval_wall_seconds = max(
            0.0,
            _report_metric(evaluation_summary.get("duration_seconds")),
        )
        summary_report_json_path = Path(str(evaluation_summary.get("eval_report_json_path") or ""))
        summary_report_md_path = Path(str(evaluation_summary.get("eval_report_md_path") or ""))
        alignment_guardrail_fields = _all_method_extract_alignment_guardrail_fields(
            cast(dict[str, Any] | None, evaluation_summary.get("report"))
        )

        for row in ordered_group:
            result_row = dict(row)
            is_representative = (
                _report_count(
                    result_row.get("global_dispatch_index", result_row.get("config_index"))
                )
                == _report_count(
                    representative_row.get(
                        "global_dispatch_index",
                        representative_row.get("config_index"),
                    )
                )
            )
            row_result_source = "executed"
            if evaluation_result_source_for_group == "reused_cross_run":
                row_result_source = "reused_cross_run"
            elif not is_representative:
                row_result_source = "reused_in_run"

            row_timing = _normalize_timing_payload(result_row.get("timing"))
            prediction_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
            if prediction_total_seconds is None:
                prediction_total_seconds = _report_optional_metric(
                    result_row.get("duration_seconds")
                )
            if prediction_total_seconds is None:
                prediction_total_seconds = 0.0
            row_eval_seconds = summary_evaluation_seconds if row_result_source == "executed" else 0.0
            row_eval_wall = summary_eval_wall_seconds if row_result_source == "executed" else 0.0
            row_total_seconds = max(0.0, prediction_total_seconds + row_eval_seconds)
            row_timing = _timing_with_updates(
                row_timing,
                evaluation_seconds=row_eval_seconds,
                total_seconds=row_total_seconds,
                checkpoints={
                    "all_method_eval_wall_seconds": row_eval_wall,
                    "all_method_eval_reused_in_run": (
                        1.0 if row_result_source == "reused_in_run" else 0.0
                    ),
                    "all_method_eval_reused_cross_run": (
                        1.0 if row_result_source == "reused_cross_run" else 0.0
                    ),
                },
            )

            result_row["status"] = "ok"
            result_row["error"] = ""
            result_row["precision"] = _report_metric(evaluation_summary.get("precision"))
            result_row["recall"] = _report_metric(evaluation_summary.get("recall"))
            result_row["f1"] = _report_metric(evaluation_summary.get("f1"))
            result_row["practical_precision"] = _report_metric(
                evaluation_summary.get("practical_precision")
            )
            result_row["practical_recall"] = _report_metric(
                evaluation_summary.get("practical_recall")
            )
            result_row["practical_f1"] = _report_metric(evaluation_summary.get("practical_f1"))
            result_row.update(alignment_guardrail_fields)
            result_row["eval_signature"] = eval_signature
            result_row["evaluation_result_source"] = row_result_source
            result_row["evaluation_representative_config_dir"] = representative_config_dir
            result_row["duration_seconds"] = row_total_seconds
            result_row["timing"] = row_timing
            result_row["eval_report_json"] = _path_for_manifest(
                source_root,
                summary_report_json_path,
            )
            result_row["eval_report_md"] = _path_for_manifest(
                source_root,
                summary_report_md_path,
            )
            successful_rows.append(result_row)

    matcher_guardrails = _all_method_build_matcher_guardrails(successful_rows)
    scheduler_summary["matcher_guardrails"] = matcher_guardrails
    for warning in matcher_guardrails.get("warnings", []):
        _emit_status(f"Matcher guardrail warning: {warning}", color=typer.colors.YELLOW)

    source_rows = _write_all_method_source_reports_from_global_rows(
        target_variants=target_variants,
        source_job_plans=source_job_plans,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        successful_rows=successful_rows,
        failed_rows=failed_rows,
        include_codex_farm_requested=include_codex_farm_requested,
        include_codex_farm_effective=include_codex_farm_effective,
        eval_signature_cache_dir=eval_signature_cache_dir,
        scheduler_summary=scheduler_summary,
        retry_failed_configs_requested=effective_retry_failed_configs,
        retry_passes_executed=retry_passes_executed,
        retry_recovered_configs=retry_recovered_configs,
    )

    successful_source_count = sum(
        1 for row in source_rows if str(row.get("status", "")).lower() == "ok"
    )
    total_completed_config_runs = sum(
        _report_count(row.get("variant_count_completed")) for row in source_rows
    )
    total_successful_config_runs = sum(
        _report_count(row.get("variant_count_successful")) for row in source_rows
    )
    total_failed_config_runs = max(
        0,
        total_completed_config_runs - total_successful_config_runs,
    )
    total_evaluation_signatures_unique = sum(
        _report_count(row.get("evaluation_signatures_unique")) for row in source_rows
    )
    total_evaluation_runs_executed = sum(
        _report_count(row.get("evaluation_runs_executed")) for row in source_rows
    )
    total_evaluation_results_reused_in_run = sum(
        _report_count(row.get("evaluation_results_reused_in_run"))
        for row in source_rows
    )
    total_evaluation_results_reused_cross_run = sum(
        _report_count(row.get("evaluation_results_reused_cross_run"))
        for row in source_rows
    )
    total_prediction_signatures_unique = sum(
        _report_count(row.get("prediction_signatures_unique")) for row in source_rows
    )
    total_prediction_runs_executed = sum(
        _report_count(row.get("prediction_runs_executed")) for row in source_rows
    )
    total_prediction_results_reused_in_run = sum(
        _report_count(row.get("prediction_results_reused_in_run"))
        for row in source_rows
    )
    total_prediction_results_reused_cross_run = sum(
        _report_count(row.get("prediction_results_reused_cross_run"))
        for row in source_rows
    )
    total_split_convert_input_groups = sum(
        _report_count(row.get("split_convert_input_groups")) for row in source_rows
    )
    total_split_convert_reuse_candidates = sum(
        _report_count(row.get("split_convert_reuse_candidates")) for row in source_rows
    )
    total_split_convert_reuse_safe_candidates = sum(
        _report_count(row.get("split_convert_reuse_safe_candidates"))
        for row in source_rows
    )
    total_split_convert_reuse_blocked = sum(
        _report_count(row.get("split_convert_reuse_blocked_by_prediction_variance"))
        for row in source_rows
    )
    run_wall_seconds = max(0.0, time.monotonic() - run_started)

    source_timing_values: list[tuple[dict[str, Any], float]] = []
    config_total_seconds = 0.0
    for row in source_rows:
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        source_seconds = _report_optional_metric(
            timing_summary.get("source_wall_seconds")
        )
        if source_seconds is not None:
            source_timing_values.append((row, source_seconds))
        config_seconds = _report_optional_metric(
            timing_summary.get("config_total_seconds")
        )
        if config_seconds is not None:
            config_total_seconds += config_seconds
    source_total_seconds = sum(seconds for _row, seconds in source_timing_values)
    source_average_seconds = (
        source_total_seconds / len(source_timing_values) if source_timing_values else None
    )
    config_average_seconds = (
        config_total_seconds / total_successful_config_runs
        if total_successful_config_runs > 0
        else None
    )
    slowest_source_row = (
        max(source_timing_values, key=lambda item: item[1])[0]
        if source_timing_values
        else None
    )
    slowest_source_seconds = (
        max(seconds for _row, seconds in source_timing_values)
        if source_timing_values
        else None
    )
    slowest_config_name: str | None = None
    slowest_config_seconds: float | None = None
    for row in source_rows:
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        candidate_seconds = _report_optional_metric(
            timing_summary.get("slowest_config_seconds")
        )
        if candidate_seconds is None:
            continue
        candidate_dir = str(timing_summary.get("slowest_config_dir") or "").strip()
        if not candidate_dir:
            continue
        candidate_name = f"{row.get('source_slug', '')}/{candidate_dir}".strip("/")
        if slowest_config_seconds is None or candidate_seconds > slowest_config_seconds:
            slowest_config_seconds = candidate_seconds
            slowest_config_name = candidate_name

    report_payload: dict[str, Any] = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        "matched_target_count": total_targets,
        "unmatched_target_count": len(unmatched_targets),
        "scheduler_scope": "global_config_queue",
        "source_schedule_strategy": resolved_source_scheduling,
        "source_shard_threshold_seconds": resolved_source_shard_threshold_seconds,
        "source_shard_max_parts": resolved_source_shard_max_parts,
        "source_shard_min_variants": resolved_source_shard_min_variants,
        "source_job_count_planned": len(source_job_plans),
        "source_schedule_plan": [
            {
                "dispatch_index": dispatch_index + 1,
                "source_position": plan.source_position + 1,
                "source_group_key": plan.source_group_key,
                "source_file": str(plan.source_file),
                "source_file_name": plan.source_display_name,
                "source_slug": plan.source_slug,
                "source_shard_index": plan.shard_index + 1,
                "source_shard_total": max(1, _report_count(plan.shard_total)),
                "variant_count": len(plan.variants),
                "estimated_seconds": plan.estimated_seconds,
                "estimate_basis": plan.estimate_basis,
            }
            for dispatch_index, plan in enumerate(source_job_plans)
        ],
        "global_queue_schedule_plan": [
            {
                "dispatch_index": item.global_dispatch_index,
                "source_position": item.source_position + 1,
                "source_group_key": item.source_group_key,
                "source_file": str(item.source_file),
                "source_file_name": item.source_file_name,
                "source_slug": item.source_slug,
                "source_shard_index": item.source_shard_index + 1,
                "source_shard_total": max(1, _report_count(item.source_shard_total)),
                "source_config_index": item.config_index,
                "source_config_total": item.config_total,
                "variant_slug": item.variant.slug,
                "estimated_seconds": item.source_estimated_seconds,
                "estimate_basis": item.source_estimate_basis,
            }
            for item in work_items
        ],
        "source_parallelism_configured": source_parallelism_configured,
        "source_parallelism_effective": source_parallelism_effective,
        "total_config_runs_planned": total_planned_config_runs,
        "total_config_runs_completed": total_completed_config_runs,
        "total_config_runs_successful": total_successful_config_runs,
        "global_queue_planned_configs": total_planned_config_runs,
        "global_queue_completed_configs": total_completed_config_runs,
        "global_queue_failed_configs": total_failed_config_runs,
        "evaluation_signatures_unique": total_evaluation_signatures_unique,
        "evaluation_runs_executed": total_evaluation_runs_executed,
        "evaluation_results_reused_in_run": total_evaluation_results_reused_in_run,
        "evaluation_results_reused_cross_run": total_evaluation_results_reused_cross_run,
        "prediction_signatures_unique": total_prediction_signatures_unique,
        "prediction_runs_executed": total_prediction_runs_executed,
        "prediction_results_reused_in_run": total_prediction_results_reused_in_run,
        "prediction_results_reused_cross_run": total_prediction_results_reused_cross_run,
        "split_convert_input_groups": total_split_convert_input_groups,
        "split_convert_reuse_candidates": total_split_convert_reuse_candidates,
        "split_convert_reuse_safe_candidates": total_split_convert_reuse_safe_candidates,
        "split_convert_reuse_blocked_by_prediction_variance": total_split_convert_reuse_blocked,
        "prediction_reuse_key_schema_version": (
            ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION
        ),
        "split_convert_input_key_schema_version": (
            ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION
        ),
        "successful_source_count": successful_source_count,
        "failed_source_count": total_targets - successful_source_count,
        "config_timeout_seconds": effective_config_timeout_seconds,
        "retry_failed_configs_requested": effective_retry_failed_configs,
        "include_codex_farm_requested": include_codex_farm_requested,
        "include_codex_farm_effective": include_codex_farm_effective,
        "canonical_alignment_cache_root": str(resolved_canonical_cache_root),
        "prediction_reuse_cache_root": str(resolved_prediction_reuse_cache_root),
        "executor_resolution": {
            "process_workers_required": bool(require_process_workers),
            "process_worker_probe_available": process_worker_probe_available,
            "process_worker_probe_error": process_worker_probe_error,
            "config_executor_backends_seen": sorted(config_executor_backends_seen),
        },
        "timing_summary": {
            "run_wall_seconds": run_wall_seconds,
            "source_total_seconds": source_total_seconds,
            "source_average_seconds": source_average_seconds,
            "config_total_seconds": config_total_seconds,
            "config_average_seconds": config_average_seconds,
            "slowest_source": (
                str(slowest_source_row.get("source_file", ""))
                if isinstance(slowest_source_row, dict)
                else None
            ),
            "slowest_source_seconds": slowest_source_seconds,
            "slowest_config": slowest_config_name,
            "slowest_config_seconds": slowest_config_seconds,
        },
        "scheduler_summary": dict(scheduler_summary),
        "sources": source_rows,
        "unmatched": [
            {
                "gold_spans_path": str(unmatched.gold_spans_path),
                "gold_display": unmatched.gold_display,
                "reason": unmatched.reason,
                "source_hint": unmatched.source_hint,
            }
            for unmatched in unmatched_targets
        ],
    }

    history_csv_path = history_csv_for_output(
        processed_output_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    _refresh_dashboard_after_history_write(
        csv_path=history_csv_path,
        output_root=resolved_dashboard_output_root,
        golden_root=golden_root,
        dashboard_out_dir=(
            history_root_for_output(resolved_dashboard_output_root) / "dashboard"
            if resolved_dashboard_output_root is not None
            else None
        ),
        reason="all-method benchmark global queue batch append",
    )

    report_json_path = root_output_dir / "all_method_benchmark_multi_source_report.json"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
    report_md_path.write_text(
        _render_all_method_multi_source_report_md(report_payload),
        encoding="utf-8",
    )

    completion_color = (
        typer.colors.GREEN
        if successful_source_count == total_targets
        and total_successful_config_runs == total_planned_config_runs
        else typer.colors.YELLOW
    )
    _emit_status(
        (
            "All method benchmark complete: "
            f"sources {successful_source_count}/{total_targets}, "
            f"configs {total_successful_config_runs}/{total_planned_config_runs}."
        ),
        color=completion_color,
    )
    if progress_callback is None:
        typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)
    return report_md_path


def _run_all_method_benchmark_multi_source(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    unmatched_targets: list[AllMethodUnmatchedGold],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    golden_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    scheduler_scope: str | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    canonical_alignment_cache_root: Path | None = None,
    prediction_reuse_cache_root: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    _normalize_all_method_scheduler_scope(scheduler_scope)
    return _run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=unmatched_targets,
        include_codex_farm_requested=include_codex_farm_requested,
        include_codex_farm_effective=include_codex_farm_effective,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        golden_root=golden_root,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
        progress_callback=progress_callback,
        dashboard=dashboard,
        max_parallel_sources=max_parallel_sources,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        config_timeout_seconds=config_timeout_seconds,
        retry_failed_configs=retry_failed_configs,
        source_scheduling=source_scheduling,
        source_shard_threshold_seconds=source_shard_threshold_seconds,
        source_shard_max_parts=source_shard_max_parts,
        source_shard_min_variants=source_shard_min_variants,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        canonical_alignment_cache_root=canonical_alignment_cache_root,
        prediction_reuse_cache_root=prediction_reuse_cache_root,
        dashboard_output_root=dashboard_output_root,
        require_process_workers=require_process_workers,
    )


def _run_all_method_benchmark(
    *,
    gold_spans_path: Path,
    source_file: Path,
    variants: list[AllMethodVariant],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    golden_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    dashboard_source_index: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    refresh_dashboard_after_source: bool = True,
    source_parallelism_effective: int | None = 1,
    canonical_alignment_cache_dir_override: Path | None = None,
    prediction_reuse_cache_dir_override: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    source_started = time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = root_output_dir / ".scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)
    split_phase_gate_dir = root_output_dir / ".split_phase_slots"
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    canonical_alignment_cache_dir = (
        canonical_alignment_cache_dir_override
        if canonical_alignment_cache_dir_override is not None
        else (root_output_dir / ".cache" / "canonical_alignment")
    )
    prediction_reuse_cache_dir = (
        prediction_reuse_cache_dir_override.expanduser()
        if prediction_reuse_cache_dir_override is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    )
    scheduler_events_dir = root_output_dir / ".scheduler_events"
    scheduler_timeseries_path = root_output_dir / ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    if scheduler_events_dir.exists():
        shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    if scheduler_timeseries_path.exists():
        scheduler_timeseries_path.unlink()

    total_variants = len(variants)
    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=total_variants,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=source_parallelism_effective,
    )
    configured_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    requested_split_phase_slots = scheduler_runtime.split_phase_slots_requested
    effective_split_phase_slots = scheduler_runtime.split_phase_slots
    split_phase_slot_mode = scheduler_runtime.split_phase_slot_mode
    split_phase_slot_cap_by_cpu = scheduler_runtime.split_phase_slot_cap_by_cpu
    split_phase_slot_cap_by_memory = scheduler_runtime.split_phase_slot_cap_by_memory
    effective_wing_backlog_target = scheduler_runtime.wing_backlog_target
    configured_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_configured
    effective_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_effective
    eval_tail_headroom_mode = scheduler_runtime.eval_tail_headroom_mode
    effective_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    max_active_during_eval = scheduler_runtime.max_active_during_eval
    effective_inflight_pipelines = scheduler_runtime.effective_inflight_pipelines
    adaptive_overcommit_limit = scheduler_runtime.adaptive_overcommit_limit
    adaptive_max_guard_target = scheduler_runtime.adaptive_max_guard_target
    scheduler_source_parallelism = scheduler_runtime.source_parallelism_effective
    scheduler_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    scheduler_cpu_budget_total = scheduler_runtime.cpu_budget_total
    split_worker_cap_per_config, split_worker_guard = _resolve_all_method_split_worker_cap(
        split_phase_slots=effective_split_phase_slots,
        source_parallelism_effective=source_parallelism_effective,
    )
    max_requested_split_workers = max(
        [
            max(
                max(1, _report_count(variant.run_settings.workers)),
                max(1, _report_count(variant.run_settings.pdf_split_workers)),
                max(1, _report_count(variant.run_settings.epub_split_workers)),
            )
            for variant in variants
        ],
        default=1,
    )
    effective_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    effective_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )

    def _emit_status(
        message: str,
        *,
        color: typer.colors = typer.colors.CYAN,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned:
            return
        if progress_callback is not None:
            if _is_structured_progress_message(cleaned):
                _notify_progress_callback(progress_callback, cleaned)
                return
            if dashboard is not None:
                dashboard.set_task(cleaned)
                _notify_progress_callback(progress_callback, dashboard.render())
                return
            _notify_progress_callback(progress_callback, cleaned)
            return
        typer.secho(cleaned, fg=color)

    if split_phase_slot_mode != "configured":
        _emit_status(
            (
                "Resource guard capped split slots to "
                f"{effective_split_phase_slots} "
                f"(requested {requested_split_phase_slots}; "
                f"cpu cap {split_phase_slot_cap_by_cpu}; "
                f"memory cap {split_phase_slot_cap_by_memory})."
            ),
            color=typer.colors.YELLOW,
        )

    if split_worker_cap_per_config < max_requested_split_workers:
        _emit_status(
            (
                "Resource guard capped split workers per active config to "
                f"{split_worker_cap_per_config} "
                f"(requested peak {max_requested_split_workers}; "
                f"split slots {effective_split_phase_slots})."
            ),
            color=typer.colors.YELLOW,
        )

    variant_rows: list[dict[str, Any]] = []
    indexed_variants = list(enumerate(variants, start=1))
    scheduler_phase_by_config: dict[int, str] = {}
    scheduler_event_offsets: dict[int, int] = {}
    scheduler_last_tick = time.monotonic()
    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_last_snapshot = ""
    scheduler_smart_enabled = bool(effective_smart_scheduler)
    scheduler_timeseries_last_snapshot = ""
    scheduler_timeseries_last_write_monotonic = source_started
    scheduler_timeseries_rows_written = 0
    scheduler_timeseries_heartbeat_seconds = max(
        ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS,
        ALL_METHOD_SCHEDULER_POLL_SECONDS,
    )
    scheduler_cpu_source = "proc_stat_linux"
    scheduler_cpu_samples_collected = 0
    scheduler_cpu_totals_last: tuple[int, int] | None = None
    scheduler_cpu_utilization_pct_last: float | None = None
    scheduler_cpu_utilization_pct_high_water = 0.0
    scheduler_admission_adjustments = 0
    scheduler_admission_pressure_boosts = 0
    scheduler_admission_saturation_clamps = 0
    scheduler_admission_cpu_hot_clamps = 0
    scheduler_admission_active_cap_peak = configured_inflight_pipelines
    scheduler_admission_guard_target_peak = min(
        max(1, total_variants),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_last_key: tuple[int, int, str] | None = None
    scheduler_admission_active_cap_current = configured_inflight_pipelines
    scheduler_admission_guard_target_current = min(
        max(1, total_variants),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_wing_target_current = effective_wing_backlog_target
    scheduler_admission_reason_current = "base"
    process_worker_probe_available: bool | None = None
    process_worker_probe_error: str | None = None
    config_executor_backends_seen: set[str] = set()

    def _scheduler_event_path(config_index: int) -> Path:
        return scheduler_events_dir / f"config_{config_index:03d}.jsonl"

    def _read_linux_cpu_totals() -> tuple[int, int] | None:
        try:
            with Path("/proc/stat").open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return None
        line = str(first_line or "").strip()
        if not line:
            return None
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        values: list[int] = []
        for token in parts[1:]:
            try:
                values.append(int(token))
            except ValueError:
                return None
        if len(values) < 4:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle

    def _sample_host_cpu_utilization_pct() -> float | None:
        nonlocal scheduler_cpu_source
        nonlocal scheduler_cpu_samples_collected
        nonlocal scheduler_cpu_totals_last

        current = _read_linux_cpu_totals()
        if current is None:
            scheduler_cpu_source = "unavailable"
            scheduler_cpu_totals_last = None
            return None
        previous = scheduler_cpu_totals_last
        scheduler_cpu_totals_last = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        busy_delta = max(0, total_delta - max(0, idle_delta))
        scheduler_cpu_samples_collected += 1
        return max(0.0, min(100.0, (float(busy_delta) / float(total_delta)) * 100.0))

    def _scheduler_phase_for_event(event_name: str) -> str | None:
        event = str(event_name or "").strip()
        if event in {"config_started", "prep_started"}:
            return "prep"
        if event == "split_wait_started":
            return "split_wait"
        if event == "split_active_started":
            return "split_active"
        if event in {"split_active_finished", "post_started"}:
            return "post"
        if event in {"post_finished", "evaluate_started"}:
            return "evaluate"
        if event in {"evaluate_finished", "config_finished"}:
            return "done"
        return None

    def _poll_scheduler_events(active_indices: set[int]) -> None:
        for active_index in sorted(active_indices):
            event_path = _scheduler_event_path(active_index)
            if not event_path.exists():
                continue
            offset = max(0, scheduler_event_offsets.get(active_index, 0))
            with event_path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Ignoring malformed scheduler event in %s: %s",
                            event_path,
                            line[:160],
                        )
                        continue
                    if not isinstance(payload, dict):
                        continue
                    phase = _scheduler_phase_for_event(str(payload.get("event") or ""))
                    if phase is not None:
                        scheduler_phase_by_config[active_index] = phase
                scheduler_event_offsets[active_index] = handle.tell()

    def _compute_scheduler_counts(active_indices: set[int]) -> dict[str, int]:
        heavy_active = 0
        split_wait = 0
        prep_active = 0
        post_active = 0
        evaluate_active = 0
        for active_index in active_indices:
            phase = scheduler_phase_by_config.get(active_index, "prep")
            if phase == "split_active":
                heavy_active += 1
            elif phase == "split_wait":
                split_wait += 1
            elif phase == "post":
                post_active += 1
            elif phase == "evaluate":
                evaluate_active += 1
            elif phase == "done":
                continue
            else:
                prep_active += 1
        wing_backlog = split_wait + prep_active
        return {
            "heavy_active": heavy_active,
            "split_wait": split_wait,
            "prep_active": prep_active,
            "post_active": post_active,
            "evaluate_active": evaluate_active,
            "wing_backlog": wing_backlog,
            "active": len(active_indices),
        }

    def _tick_scheduler_metrics(*, active_indices: set[int], pending_count: int) -> dict[str, int]:
        nonlocal scheduler_last_tick
        nonlocal scheduler_capacity_seconds
        nonlocal scheduler_busy_seconds
        nonlocal scheduler_idle_gap_seconds
        nonlocal scheduler_wing_area_seconds
        nonlocal scheduler_max_wing_backlog
        nonlocal scheduler_max_active_pipelines
        nonlocal scheduler_max_eval_active
        nonlocal scheduler_cpu_utilization_pct_last
        nonlocal scheduler_cpu_utilization_pct_high_water

        now = time.monotonic()
        delta = max(0.0, now - scheduler_last_tick)
        counts = _compute_scheduler_counts(active_indices)
        scheduler_capacity_seconds += float(effective_split_phase_slots) * delta
        scheduler_busy_seconds += float(
            min(effective_split_phase_slots, counts["heavy_active"])
        ) * delta
        if pending_count > 0 and counts["heavy_active"] < effective_split_phase_slots:
            scheduler_idle_gap_seconds += delta
        scheduler_wing_area_seconds += float(counts["wing_backlog"]) * delta
        scheduler_max_wing_backlog = max(
            scheduler_max_wing_backlog,
            counts["wing_backlog"],
        )
        scheduler_max_active_pipelines = max(
            scheduler_max_active_pipelines,
            counts["active"],
        )
        scheduler_max_eval_active = max(
            scheduler_max_eval_active,
            counts["evaluate_active"],
        )
        sampled_cpu = _sample_host_cpu_utilization_pct()
        if sampled_cpu is not None:
            scheduler_cpu_utilization_pct_last = sampled_cpu
            scheduler_cpu_utilization_pct_high_water = max(
                scheduler_cpu_utilization_pct_high_water,
                sampled_cpu,
            )
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return (
            f"scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} "
            f"| wing {counts['wing_backlog']} "
            f"| eval {counts['evaluate_active']} "
            f"| active {counts['active']} | pending {max(0, pending_count)}"
        )

    def _write_scheduler_timeseries_row(
        *,
        counts: dict[str, int],
        pending_count: int,
        force: bool = False,
    ) -> None:
        nonlocal scheduler_timeseries_last_snapshot
        nonlocal scheduler_timeseries_last_write_monotonic
        nonlocal scheduler_timeseries_rows_written

        pending_safe = max(0, pending_count)
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_safe)
        now_monotonic = time.monotonic()
        write_due = (
            force
            or snapshot != scheduler_timeseries_last_snapshot
            or (
                now_monotonic - scheduler_timeseries_last_write_monotonic
                >= scheduler_timeseries_heartbeat_seconds
            )
        )
        if not write_due:
            return
        row = {
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": now_monotonic,
            "elapsed_seconds": max(0.0, now_monotonic - source_started),
            "snapshot": snapshot,
            "heavy_active": _report_count(counts.get("heavy_active")),
            "heavy_capacity": _report_count(effective_split_phase_slots),
            "split_wait": _report_count(counts.get("split_wait")),
            "prep_active": _report_count(counts.get("prep_active")),
            "post_active": _report_count(counts.get("post_active")),
            "evaluate_active": _report_count(counts.get("evaluate_active")),
            "wing_backlog": _report_count(counts.get("wing_backlog")),
            "active": _report_count(counts.get("active")),
            "pending": pending_safe,
            "cpu_utilization_pct": scheduler_cpu_utilization_pct_last,
            "admission_active_cap": scheduler_admission_active_cap_current,
            "admission_guard_target": scheduler_admission_guard_target_current,
            "admission_wing_target": scheduler_admission_wing_target_current,
            "admission_reason": scheduler_admission_reason_current,
        }
        try:
            with scheduler_timeseries_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring scheduler time-series write failure for %s: %s",
                scheduler_timeseries_path,
                exc,
            )
            return
        scheduler_timeseries_last_snapshot = snapshot
        scheduler_timeseries_last_write_monotonic = now_monotonic
        scheduler_timeseries_rows_written += 1

    def _emit_scheduler_snapshot(
        *,
        counts: dict[str, int],
        pending_count: int,
        force_timeseries: bool = False,
    ) -> None:
        nonlocal scheduler_last_snapshot
        _write_scheduler_timeseries_row(
            counts=counts,
            pending_count=pending_count,
            force=force_timeseries,
        )
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(
            counts=counts,
            pending_count=max(0, pending_count),
        )
        if snapshot == scheduler_last_snapshot:
            return
        scheduler_last_snapshot = snapshot
        _emit_status(snapshot, color=typer.colors.BRIGHT_BLACK)

    def _compute_scheduler_metrics_from_event_files(
        *,
        source_end_monotonic: float,
    ) -> dict[str, float | int] | None:
        rows: list[tuple[float, str, int]] = []
        for event_path in sorted(scheduler_events_dir.glob("config_*.jsonl")):
            try:
                lines = event_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event_name = str(payload.get("event") or "").strip()
                if not event_name:
                    continue
                event_time = _report_optional_metric(payload.get("monotonic_seconds"))
                event_index = _report_count(payload.get("config_index"))
                if event_time is None or event_index <= 0:
                    continue
                rows.append((event_time, event_name, event_index))
        if not rows:
            return None

        rows.sort(key=lambda item: item[0])
        phases: dict[int, str] = {}
        started_configs: set[int] = set()
        capacity_seconds = 0.0
        busy_seconds = 0.0
        idle_gap_seconds = 0.0
        wing_area_seconds = 0.0
        max_wing_backlog = 0
        max_active_pipelines = 0
        max_eval_active = 0

        def _counts() -> dict[str, int]:
            heavy_active = 0
            split_wait = 0
            prep_active = 0
            post_active = 0
            evaluate_active = 0
            for phase in phases.values():
                if phase == "split_active":
                    heavy_active += 1
                elif phase == "split_wait":
                    split_wait += 1
                elif phase == "post":
                    post_active += 1
                elif phase == "evaluate":
                    evaluate_active += 1
                elif phase == "done":
                    continue
                else:
                    prep_active += 1
            wing_backlog = split_wait + prep_active
            active = (
                heavy_active
                + split_wait
                + prep_active
                + post_active
                + evaluate_active
            )
            return {
                "heavy_active": heavy_active,
                "evaluate_active": evaluate_active,
                "wing_backlog": wing_backlog,
                "active": active,
            }

        previous_time = rows[0][0]
        for event_time, event_name, event_index in rows:
            delta = max(0.0, event_time - previous_time)
            counts = _counts()
            capacity_seconds += float(effective_split_phase_slots) * delta
            busy_seconds += float(
                min(effective_split_phase_slots, counts["heavy_active"])
            ) * delta
            if (
                len(started_configs) < total_variants
                and counts["heavy_active"] < effective_split_phase_slots
            ):
                idle_gap_seconds += delta
            wing_area_seconds += float(counts["wing_backlog"]) * delta
            max_wing_backlog = max(max_wing_backlog, counts["wing_backlog"])
            max_active_pipelines = max(max_active_pipelines, counts["active"])
            max_eval_active = max(max_eval_active, counts["evaluate_active"])
            previous_time = event_time

            mapped_phase = _scheduler_phase_for_event(event_name)
            if event_name == "config_started":
                started_configs.add(event_index)
            if mapped_phase is not None:
                phases[event_index] = mapped_phase
            if event_name == "config_finished":
                phases[event_index] = "done"

        tail_delta = max(0.0, source_end_monotonic - previous_time)
        if tail_delta > 0:
            counts = _counts()
            capacity_seconds += float(effective_split_phase_slots) * tail_delta
            busy_seconds += float(
                min(effective_split_phase_slots, counts["heavy_active"])
            ) * tail_delta
            if (
                len(started_configs) < total_variants
                and counts["heavy_active"] < effective_split_phase_slots
            ):
                idle_gap_seconds += tail_delta
            wing_area_seconds += float(counts["wing_backlog"]) * tail_delta
            max_wing_backlog = max(max_wing_backlog, counts["wing_backlog"])
            max_active_pipelines = max(max_active_pipelines, counts["active"])
            max_eval_active = max(max_eval_active, counts["evaluate_active"])

        return {
            "heavy_slot_capacity_seconds": capacity_seconds,
            "heavy_slot_busy_seconds": busy_seconds,
            "idle_gap_seconds": idle_gap_seconds,
            "wing_backlog_area_seconds": wing_area_seconds,
            "max_wing_backlog": max_wing_backlog,
            "max_active_pipelines_observed": max_active_pipelines,
            "max_eval_active_observed": max_eval_active,
        }

    def _finalize_scheduler_metrics() -> dict[str, Any]:
        event_metrics = _compute_scheduler_metrics_from_event_files(
            source_end_monotonic=time.monotonic()
        )
        capacity_seconds = scheduler_capacity_seconds
        busy_seconds = scheduler_busy_seconds
        idle_gap_seconds = scheduler_idle_gap_seconds
        wing_area_seconds = scheduler_wing_area_seconds
        max_wing_backlog = scheduler_max_wing_backlog
        max_active = scheduler_max_active_pipelines
        max_eval_active = scheduler_max_eval_active
        if isinstance(event_metrics, dict):
            capacity_seconds = _report_metric(
                event_metrics.get("heavy_slot_capacity_seconds")
            )
            busy_seconds = _report_metric(event_metrics.get("heavy_slot_busy_seconds"))
            idle_gap_seconds = _report_metric(event_metrics.get("idle_gap_seconds"))
            wing_area_seconds = _report_metric(event_metrics.get("wing_backlog_area_seconds"))
            max_wing_backlog = max(
                max_wing_backlog,
                _report_count(event_metrics.get("max_wing_backlog")),
            )
            max_active = max(
                max_active,
                _report_count(event_metrics.get("max_active_pipelines_observed")),
            )
            max_eval_active = max(
                max_eval_active,
                _report_count(event_metrics.get("max_eval_active_observed")),
            )
        utilization_pct = (
            (busy_seconds / capacity_seconds) * 100.0
            if capacity_seconds > 0
            else 0.0
        )
        avg_wing_backlog = (
            wing_area_seconds / capacity_seconds
            if capacity_seconds > 0
            else 0.0
        )
        return {
            "mode": "smart" if scheduler_smart_enabled else "fixed",
            "configured_inflight_pipelines": configured_inflight_pipelines,
            "effective_inflight_pipelines": effective_inflight_pipelines,
            "split_phase_slots_requested": requested_split_phase_slots,
            "split_phase_slots": effective_split_phase_slots,
            "split_phase_slot_mode": split_phase_slot_mode,
            "split_phase_slot_cap_by_cpu": split_phase_slot_cap_by_cpu,
            "split_phase_slot_cap_by_memory": split_phase_slot_cap_by_memory,
            "split_worker_cap_per_config": split_worker_cap_per_config,
            "split_worker_cap_by_cpu": split_worker_guard.get("split_worker_cap_by_cpu"),
            "split_worker_cap_by_memory": split_worker_guard.get(
                "split_worker_cap_by_memory"
            ),
            "wing_backlog_target": effective_wing_backlog_target,
            "eval_tail_headroom_mode": eval_tail_headroom_mode,
            "eval_tail_headroom_configured": configured_eval_tail_headroom,
            "eval_tail_headroom_effective": effective_eval_tail_headroom,
            "max_active_during_eval": max_active_during_eval,
            "adaptive_overcommit_limit": adaptive_overcommit_limit,
            "adaptive_max_guard_target": adaptive_max_guard_target,
            "source_parallelism_effective": scheduler_source_parallelism,
            "cpu_budget_per_source": scheduler_cpu_budget_per_source,
            "cpu_budget_total": scheduler_cpu_budget_total,
            "max_eval_tail_pipelines": effective_eval_tail_headroom,
            "smart_tail_buffer_slots": (
                effective_eval_tail_headroom if bool(effective_smart_scheduler) else 0
            ),
            "smart_scheduler_enabled": bool(effective_smart_scheduler),
            "heavy_slot_capacity_seconds": capacity_seconds,
            "heavy_slot_busy_seconds": busy_seconds,
            "heavy_slot_utilization_pct": utilization_pct,
            "avg_wing_backlog": avg_wing_backlog,
            "max_wing_backlog": max_wing_backlog,
            "idle_gap_seconds": idle_gap_seconds,
            "max_active_pipelines_observed": max_active,
            "max_eval_active_observed": max_eval_active,
            "adaptive_admission_adjustments": scheduler_admission_adjustments,
            "adaptive_admission_pressure_boosts": scheduler_admission_pressure_boosts,
            "adaptive_admission_saturation_clamps": scheduler_admission_saturation_clamps,
            "adaptive_admission_cpu_hot_clamps": scheduler_admission_cpu_hot_clamps,
            "adaptive_admission_active_cap_peak": scheduler_admission_active_cap_peak,
            "adaptive_admission_guard_target_peak": scheduler_admission_guard_target_peak,
            "timeseries_path": str(scheduler_timeseries_path),
            "timeseries_row_count": scheduler_timeseries_rows_written,
            "timeseries_heartbeat_seconds": scheduler_timeseries_heartbeat_seconds,
            "snapshot_poll_seconds": ALL_METHOD_SCHEDULER_POLL_SECONDS,
            "cpu_utilization_source": scheduler_cpu_source,
            "cpu_utilization_samples": scheduler_cpu_samples_collected,
            "cpu_utilization_pct_high_water": scheduler_cpu_utilization_pct_high_water,
        }

    def _shutdown_parallel_executor(
        executor: Any,
        *,
        terminate_workers: bool,
    ) -> None:
        if terminate_workers:
            worker_map = getattr(executor, "_processes", None)
            if isinstance(worker_map, dict):
                for process in list(worker_map.values()):
                    if process is None:
                        continue
                    try:
                        if process.is_alive():
                            process.terminate()
                    except Exception:
                        continue
                for process in list(worker_map.values()):
                    if process is None:
                        continue
                    try:
                        process.join(timeout=1.0)
                        if process.is_alive() and hasattr(process, "kill"):
                            process.kill()
                    except Exception:
                        continue
        shutdown_fn = getattr(executor, "shutdown", None)
        if not callable(shutdown_fn):
            return
        try:
            shutdown_fn(wait=not terminate_workers, cancel_futures=terminate_workers)
        except TypeError:
            shutdown_fn(wait=not terminate_workers)
        except Exception:
            return

    def _latest_rows_by_config(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_by_index: dict[int, dict[str, Any]] = {}
        for row in rows:
            config_index = _report_count(row.get("config_index"))
            latest_by_index[config_index] = row
        return [latest_by_index[index] for index in sorted(latest_by_index)]

    def _run_serial_variants(
        items: list[tuple[int, AllMethodVariant]],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        for config_index, variant in items:
            progress_label = format_task_counter(
                "Running",
                config_index,
                max(1, total_variants),
                noun="config",
            )
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.start_config(
                    source_index=dashboard_source_index,
                    config_index=config_index,
                    config_total=max(1, total_variants),
                    config_slug=variant.slug,
                )
            _emit_status(f"{progress_label}: {variant.slug}", color=typer.colors.CYAN)

            def _variant_progress(message: str) -> None:
                if progress_callback is None:
                    return
                if dashboard is None:
                    if _is_structured_progress_message(message):
                        _notify_progress_callback(progress_callback, message)
                        return
                    _notify_progress_callback(
                        progress_callback,
                        f"{progress_label}: {variant.slug} | {message}",
                    )
                    return
                if _is_structured_progress_message(message):
                    _notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                _notify_progress_callback(progress_callback, dashboard.render())

            row = _run_all_method_prediction_once(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                variant=variant,
                config_index=config_index,
                total_variants=max(1, total_variants),
                root_output_dir=root_output_dir,
                scratch_root=scratch_root,
                processed_output_root=processed_output_root,
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                max_concurrent_split_phases=effective_split_phase_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                scheduler_events_dir=scheduler_events_dir,
                alignment_cache_dir=canonical_alignment_cache_dir,
                prediction_reuse_cache_dir=prediction_reuse_cache_dir,
                split_worker_cap_per_config=split_worker_cap_per_config,
                progress_callback=_variant_progress if progress_callback else None,
            )
            variant_rows.append(row)

            success = str(row.get("status") or "").strip().lower() == "ok"
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.complete_config(
                    source_index=dashboard_source_index,
                    success=success,
                    config_index=config_index,
                )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        f"Completed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: {variant.slug}"
                    )
            else:
                _emit_status(
                    (
                        f"Failed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

    def _run_parallel_variants(
        items: list[tuple[int, AllMethodVariant]],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        nonlocal process_worker_probe_available
        nonlocal process_worker_probe_error
        nonlocal scheduler_smart_enabled
        nonlocal scheduler_admission_adjustments
        nonlocal scheduler_admission_pressure_boosts
        nonlocal scheduler_admission_saturation_clamps
        nonlocal scheduler_admission_cpu_hot_clamps
        nonlocal scheduler_admission_active_cap_peak
        nonlocal scheduler_admission_guard_target_peak
        nonlocal scheduler_admission_last_key
        nonlocal scheduler_admission_active_cap_current
        nonlocal scheduler_admission_guard_target_current
        nonlocal scheduler_admission_wing_target_current
        nonlocal scheduler_admission_reason_current
        force_parallel_timeout = effective_config_timeout_seconds is not None
        serial_by_limits = (
            len(items) <= 1 or effective_inflight_pipelines <= 1
        ) and not force_parallel_timeout
        if serial_by_limits:
            config_executor_backends_seen.add("serial")
            _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
            return
        executor_backend = "process"
        process_workers_available, process_worker_error = (
            _probe_all_method_process_pool_executor()
        )
        if process_workers_available:
            picklable, picklable_error = _probe_all_method_process_worker_picklable()
            if not picklable:
                process_workers_available = False
                process_worker_error = picklable_error
        process_worker_probe_available = bool(process_workers_available)
        process_worker_probe_error = (
            str(process_worker_error).strip() if process_worker_error else None
        )
        if not process_workers_available:
            detail = (
                f" ({process_worker_error})"
                if isinstance(process_worker_error, str) and process_worker_error
                else ""
            )
            if require_process_workers:
                raise RuntimeError(
                    "Process-based config concurrency is required, but runtime probe "
                    f"reported it unavailable{detail}."
                )
            _emit_status(
                (
                    "Process-based config concurrency unavailable"
                    f"{detail}; using thread-based config concurrency."
                ),
                color=typer.colors.YELLOW,
            )
            executor_backend = "thread"
        config_executor_backends_seen.add(str(executor_backend))

        pending_items = list(items)
        futures: dict[Any, tuple[int, AllMethodVariant, float]] = {}
        worker_limit = min(effective_inflight_pipelines, len(items))
        scheduler_base_target = min(
            total_variants,
            effective_split_phase_slots + effective_wing_backlog_target,
        )

        try:
            executor = (
                _create_all_method_process_pool_executor(max_workers=worker_limit)
                if executor_backend == "process"
                else ThreadPoolExecutor(max_workers=worker_limit)
            )
        except (PermissionError, OSError) as exc:
            if executor_backend == "process":
                if require_process_workers:
                    raise RuntimeError(
                        "Process-based config concurrency is required, but process "
                        f"executor startup failed: {exc}"
                    ) from exc
                _emit_status(
                    (
                        "Process-based config concurrency unavailable "
                        f"({exc}); using thread-based config concurrency."
                    ),
                    color=typer.colors.YELLOW,
                )
                executor_backend = "thread"
                config_executor_backends_seen.add("thread")
                try:
                    executor = ThreadPoolExecutor(max_workers=worker_limit)
                except Exception as thread_exc:  # noqa: BLE001
                    _emit_status(
                        (
                            "Thread-based config concurrency unavailable "
                            f"({thread_exc}); running single-config execution."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    config_executor_backends_seen.add("serial")
                    _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
                    return
            else:
                _emit_status(
                    (
                        "Thread-based config concurrency unavailable "
                        f"({exc}); running single-config execution."
                    ),
                    color=typer.colors.YELLOW,
                )
                config_executor_backends_seen.add("serial")
                _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
                return

        def _record_completion(
            *,
            config_index: int,
            variant: AllMethodVariant,
            row: dict[str, Any],
        ) -> None:
            variant_rows.append(row)
            success = str(row.get("status") or "").strip().lower() == "ok"
            scheduler_phase_by_config.pop(config_index, None)
            scheduler_event_offsets.pop(config_index, None)
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.complete_config(
                    source_index=dashboard_source_index,
                    success=success,
                    config_index=config_index,
                )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                            f"{variant.slug}"
                        )
                    )
            else:
                _emit_status(
                    (
                        f"Failed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

        def _submit_next() -> bool:
            if not pending_items:
                return False
            config_index, variant = pending_items.pop(0)
            progress_label = format_task_counter(
                "Running",
                config_index,
                max(1, total_variants),
                noun="config",
            )
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.start_config(
                    source_index=dashboard_source_index,
                    config_index=config_index,
                    config_total=max(1, total_variants),
                    config_slug=variant.slug,
                )
            _emit_status(f"{progress_label}: {variant.slug}", color=typer.colors.CYAN)

            try:
                future = executor.submit(
                    _run_all_method_prediction_once,
                    gold_spans_path=gold_spans_path,
                    source_file=source_file,
                    variant=variant,
                    config_index=config_index,
                    total_variants=max(1, total_variants),
                    root_output_dir=root_output_dir,
                    scratch_root=scratch_root,
                    processed_output_root=processed_output_root,
                    overlap_threshold=overlap_threshold,
                    force_source_match=force_source_match,
                    max_concurrent_split_phases=effective_split_phase_slots,
                    split_phase_gate_dir=split_phase_gate_dir,
                    scheduler_events_dir=scheduler_events_dir,
                    alignment_cache_dir=canonical_alignment_cache_dir,
                    prediction_reuse_cache_dir=prediction_reuse_cache_dir,
                    split_worker_cap_per_config=split_worker_cap_per_config,
                    progress_callback=None,
                )
            except Exception as exc:  # noqa: BLE001
                row = _all_method_failed_row(
                    config_index=config_index,
                    config_dir_name=_all_method_config_dir_name(config_index, variant),
                    variant=variant,
                    error=f"Failed to submit benchmark config: {exc}",
                )
                _record_completion(
                    config_index=config_index,
                    variant=variant,
                    row=row,
                )
                return True

            futures[future] = (config_index, variant, time.monotonic())
            scheduler_phase_by_config[config_index] = "prep"
            scheduler_event_offsets[config_index] = 0
            return True

        def _refresh_admission_decision(
            *,
            counts: dict[str, int],
            pending_count: int,
        ) -> _AllMethodSchedulerAdmissionDecision:
            nonlocal scheduler_admission_adjustments
            nonlocal scheduler_admission_pressure_boosts
            nonlocal scheduler_admission_saturation_clamps
            nonlocal scheduler_admission_cpu_hot_clamps
            nonlocal scheduler_admission_active_cap_peak
            nonlocal scheduler_admission_guard_target_peak
            nonlocal scheduler_admission_last_key
            nonlocal scheduler_admission_active_cap_current
            nonlocal scheduler_admission_guard_target_current
            nonlocal scheduler_admission_wing_target_current
            nonlocal scheduler_admission_reason_current

            decision = _resolve_all_method_scheduler_admission(
                counts=counts,
                pending_count=pending_count,
                total_variants=max(1, total_variants),
                configured_inflight_pipelines=configured_inflight_pipelines,
                split_phase_slots=effective_split_phase_slots,
                wing_backlog_target=effective_wing_backlog_target,
                max_active_during_eval=max_active_during_eval,
                adaptive_overcommit_limit=adaptive_overcommit_limit,
                adaptive_max_guard_target=max(
                    scheduler_base_target,
                    adaptive_max_guard_target,
                ),
                smart_scheduler_enabled=scheduler_smart_enabled,
                cpu_utilization_pct=scheduler_cpu_utilization_pct_last,
            )
            decision_key = (decision.active_cap, decision.guard_target, decision.reason)
            if scheduler_admission_last_key is None:
                scheduler_admission_last_key = decision_key
            elif decision_key != scheduler_admission_last_key:
                scheduler_admission_adjustments += 1
                scheduler_admission_last_key = decision_key
                if decision.pressure_boost > 0:
                    scheduler_admission_pressure_boosts += 1
                if decision.saturation_clamp:
                    scheduler_admission_saturation_clamps += 1
                if decision.cpu_hot_clamp:
                    scheduler_admission_cpu_hot_clamps += 1
            scheduler_admission_active_cap_peak = max(
                scheduler_admission_active_cap_peak,
                decision.active_cap,
            )
            scheduler_admission_guard_target_peak = max(
                scheduler_admission_guard_target_peak,
                decision.guard_target,
            )
            scheduler_admission_active_cap_current = decision.active_cap
            scheduler_admission_guard_target_current = decision.guard_target
            scheduler_admission_wing_target_current = decision.wing_target
            scheduler_admission_reason_current = decision.reason
            return decision

        try:
            while pending_items or futures:
                active_indices = {
                    config_index for config_index, _variant, _submitted in futures.values()
                }
                counts = _tick_scheduler_metrics(
                    active_indices=active_indices,
                    pending_count=len(pending_items),
                )
                if active_indices:
                    try:
                        _poll_scheduler_events(active_indices)
                    except Exception as exc:  # noqa: BLE001
                        if scheduler_smart_enabled:
                            scheduler_smart_enabled = False
                            _emit_status(
                                (
                                    "Smart scheduler telemetry failed "
                                    f"({exc}); falling back to fixed queue refill."
                                ),
                                color=typer.colors.YELLOW,
                            )
                counts = _compute_scheduler_counts(
                    {
                        config_index
                        for config_index, _variant, _submitted in futures.values()
                    }
                )
                if (
                    dashboard_tracking
                    and dashboard is not None
                    and dashboard_source_index is not None
                ):
                    for active_index in sorted(active_indices):
                        dashboard.set_config_phase(
                            source_index=dashboard_source_index,
                            config_index=active_index,
                            phase=scheduler_phase_by_config.get(active_index, "prep"),
                        )
                admission_decision = _refresh_admission_decision(
                    counts=counts,
                    pending_count=len(pending_items),
                )
                _emit_scheduler_snapshot(
                    counts=counts,
                    pending_count=len(pending_items),
                )

                while len(futures) < worker_limit and pending_items:
                    heavy_plus_wing = counts["heavy_active"] + counts["wing_backlog"]
                    if counts["active"] >= admission_decision.active_cap:
                        break
                    if (
                        heavy_plus_wing >= admission_decision.guard_target
                        and counts["active"] >= configured_inflight_pipelines
                    ):
                        break
                    submitted = _submit_next()
                    if not submitted:
                        break
                    counts = _compute_scheduler_counts(
                        {
                            config_index
                            for config_index, _variant, _submitted in futures.values()
                        }
                    )
                    admission_decision = _refresh_admission_decision(
                        counts=counts,
                        pending_count=len(pending_items),
                    )
                    _emit_scheduler_snapshot(
                        counts=counts,
                        pending_count=len(pending_items),
                    )

                if not futures:
                    if pending_items:
                        time.sleep(ALL_METHOD_SCHEDULER_POLL_SECONDS)
                    continue

                done, _ = wait(
                    list(futures.keys()),
                    timeout=ALL_METHOD_SCHEDULER_POLL_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                for done_future in done:
                    config_index, variant, _submitted = futures.pop(done_future)
                    try:
                        row = done_future.result()
                    except Exception as exc:  # noqa: BLE001
                        row = _all_method_failed_row(
                            config_index=config_index,
                            config_dir_name=_all_method_config_dir_name(config_index, variant),
                            variant=variant,
                            error=f"Benchmark config worker failed: {exc}",
                        )
                    _record_completion(
                        config_index=config_index,
                        variant=variant,
                        row=row,
                    )

                if (
                    effective_config_timeout_seconds is None
                    or executor_backend != "process"
                ):
                    continue
                timeout_threshold = float(max(1, effective_config_timeout_seconds))
                now = time.monotonic()
                timed_out: list[tuple[Any, int, AllMethodVariant, float]] = []
                for future, (config_index, variant, submitted_at) in list(futures.items()):
                    elapsed_seconds = max(0.0, now - submitted_at)
                    if elapsed_seconds < timeout_threshold:
                        continue
                    timed_out.append((future, config_index, variant, elapsed_seconds))
                if not timed_out:
                    continue

                timed_out.sort(key=lambda item: item[1])
                for timed_out_future, config_index, variant, elapsed_seconds in timed_out:
                    futures.pop(timed_out_future, None)
                    row = _all_method_failed_row(
                        config_index=config_index,
                        config_dir_name=_all_method_config_dir_name(config_index, variant),
                        variant=variant,
                        error=(
                            f"Config timed out after {int(timeout_threshold)}s "
                            f"(elapsed {elapsed_seconds:.1f}s)."
                        ),
                        elapsed_seconds=elapsed_seconds,
                    )
                    _record_completion(
                        config_index=config_index,
                        variant=variant,
                        row=row,
                    )

                if futures:
                    requeued = sorted(
                        [
                            (config_index, variant)
                            for config_index, variant, _submitted in futures.values()
                        ],
                        key=lambda item: item[0],
                    )
                    pending_items = requeued + pending_items
                    futures.clear()
                scheduler_smart_enabled = False
                _emit_status(
                    (
                        "Config timeout reached for "
                        f"{len(timed_out)} run(s); restarting process worker pool."
                    ),
                    color=typer.colors.YELLOW,
                )
                _shutdown_parallel_executor(executor, terminate_workers=True)
                try:
                    executor = _create_all_method_process_pool_executor(
                        max_workers=worker_limit
                    )
                except (PermissionError, OSError) as exc:
                    if require_process_workers:
                        raise RuntimeError(
                            "Process-based config concurrency is required, but process "
                            f"pool restart failed after timeout: {exc}"
                        ) from exc
                    _emit_status(
                        (
                            "Process-based config concurrency unavailable after timeout "
                            f"restart ({exc}); using thread-based config concurrency for remaining configs."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    executor_backend = "thread"
                    config_executor_backends_seen.add("thread")
                    try:
                        executor = ThreadPoolExecutor(max_workers=worker_limit)
                    except Exception as thread_exc:  # noqa: BLE001
                        _emit_status(
                            (
                                "Thread-based config concurrency unavailable "
                                f"({thread_exc}); running remaining configs as single-config execution."
                            ),
                            color=typer.colors.YELLOW,
                        )
                        config_executor_backends_seen.add("serial")
                        _run_serial_variants(
                            pending_items,
                            dashboard_tracking=dashboard_tracking,
                        )
                        pending_items.clear()
                        futures.clear()
                        break
        finally:
            _shutdown_parallel_executor(executor, terminate_workers=False)

    _run_parallel_variants(indexed_variants, dashboard_tracking=True)
    variant_rows = _latest_rows_by_config(variant_rows)
    initial_failed_indices = [
        _report_count(row.get("config_index"))
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    retry_passes_executed = 0
    retry_recovered_configs = 0
    if effective_retry_failed_configs > 0 and initial_failed_indices:
        variant_by_index = {config_index: variant for config_index, variant in indexed_variants}
        remaining_failed_indices = sorted(set(initial_failed_indices))
        for retry_pass in range(1, effective_retry_failed_configs + 1):
            if not remaining_failed_indices:
                break
            retry_items = [
                (config_index, variant_by_index[config_index])
                for config_index in remaining_failed_indices
                if config_index in variant_by_index
            ]
            if not retry_items:
                break
            retry_passes_executed += 1
            _emit_status(
                (
                    f"Retry pass {retry_pass}/{effective_retry_failed_configs}: "
                    f"rerunning {len(retry_items)} failed config(s)."
                ),
                color=typer.colors.YELLOW,
            )
            prior_failed = set(remaining_failed_indices)
            _run_parallel_variants(retry_items, dashboard_tracking=False)
            variant_rows = _latest_rows_by_config(variant_rows)
            remaining_failed_indices = sorted(
                {
                    _report_count(row.get("config_index"))
                    for row in variant_rows
                    if str(row.get("status") or "").strip().lower() != "ok"
                }
            )
            recovered_this_pass = len(prior_failed - set(remaining_failed_indices))
            retry_recovered_configs += max(0, recovered_this_pass)
            if recovered_this_pass > 0:
                _emit_status(
                    (
                        f"Retry pass {retry_pass} recovered "
                        f"{recovered_this_pass} config(s)."
                    ),
                    color=typer.colors.CYAN,
                )
    _tick_scheduler_metrics(active_indices=set(), pending_count=0)
    _emit_scheduler_snapshot(
        counts=_compute_scheduler_counts(set()),
        pending_count=0,
        force_timeseries=True,
    )
    scheduler_summary = _finalize_scheduler_metrics()
    scheduler_summary["config_timeout_seconds"] = effective_config_timeout_seconds
    scheduler_summary["failed_retry_limit"] = effective_retry_failed_configs
    scheduler_summary["retry_passes_executed"] = retry_passes_executed
    scheduler_summary["retry_recovered_configs"] = retry_recovered_configs

    variant_rows = _latest_rows_by_config(variant_rows)
    prediction_success_rows = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    failed_rows: list[dict[str, Any]] = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    prediction_reuse_summary = _all_method_prediction_reuse_summary(
        prediction_success_rows
    )

    successful_rows: list[dict[str, Any]] = []
    signature_candidate_rows: list[dict[str, Any]] = []
    evaluation_signatures_unique = 0
    evaluation_runs_executed = 0
    evaluation_results_reused_in_run = 0
    evaluation_results_reused_cross_run = 0
    eval_signature_cache_dir = _resolve_all_method_eval_signature_cache_dir(
        root_output_dir=root_output_dir,
        alignment_cache_dir=canonical_alignment_cache_dir,
    )

    for row in prediction_success_rows:
        prediction_record_path = _resolve_all_method_prediction_record_path(
            root_output_dir=root_output_dir,
            row=row,
        )
        if (
            prediction_record_path is None
            or not prediction_record_path.exists()
            or not prediction_record_path.is_file()
        ):
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Prediction record path is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        sequence_matcher = str(row.get("benchmark_sequence_matcher") or "").strip() or "dmp"
        try:
            eval_signature = _build_all_method_eval_signature(
                gold_spans_path=gold_spans_path,
                prediction_record_path=prediction_record_path,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
            )
        except Exception as exc:  # noqa: BLE001
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = f"Failed to build evaluation signature: {exc}"
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        row["eval_signature"] = eval_signature
        row["benchmark_sequence_matcher"] = sequence_matcher
        signature_candidate_rows.append(row)

    grouped_by_signature = _group_all_method_rows_by_eval_signature(signature_candidate_rows)
    evaluation_signatures_unique = len(grouped_by_signature)
    grouped_items = sorted(
        grouped_by_signature.items(),
        key=lambda item: min(_report_count(row.get("config_index")) for row in item[1]),
    )
    for signature_index, (eval_signature, group_rows) in enumerate(grouped_items, start=1):
        if not group_rows:
            continue
        ordered_group = sorted(
            group_rows,
            key=lambda row: _report_count(row.get("config_index")),
        )
        representative_row = ordered_group[0]
        representative_config_dir = str(representative_row.get("config_dir") or "").strip()
        if not representative_config_dir:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative config directory is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        representative_eval_output_dir = root_output_dir / representative_config_dir
        representative_processed_output_dir = processed_output_root / representative_config_dir
        representative_prediction_record = _resolve_all_method_prediction_record_path(
            root_output_dir=root_output_dir,
            row=representative_row,
        )
        if representative_prediction_record is None:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative prediction record is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        sequence_matcher = str(representative_row.get("benchmark_sequence_matcher") or "").strip()
        if not sequence_matcher:
            sequence_matcher = "dmp"

        cache_path = eval_signature_cache_dir / f"{eval_signature}.json"
        cache_entry = _load_all_method_eval_signature_cache_entry(
            cache_path=cache_path,
            expected_signature=eval_signature,
        )

        evaluation_result_source_for_group = "executed"
        evaluation_summary: dict[str, Any]
        if cache_entry is not None:
            cached_report = cache_entry.get("report")
            if not isinstance(cached_report, dict):
                cached_report = {}
            cached_md = str(cache_entry.get("report_md") or "")
            eval_report_json_path, eval_report_md_path = (
                _materialize_all_method_cached_eval_outputs(
                    eval_output_dir=representative_eval_output_dir,
                    report_payload=cached_report,
                    report_md_text=cached_md,
                )
            )
            metric_bundle = _benchmark_report_metric_bundle(cached_report)
            evaluation_summary = {
                "status": "ok",
                "error": "",
                **metric_bundle,
                "timing": _normalize_timing_payload(cached_report.get("timing")),
                "report": cached_report,
                "report_md_text": cached_md,
                "eval_report_json_path": eval_report_json_path,
                "eval_report_md_path": eval_report_md_path,
                "duration_seconds": 0.0,
            }
            evaluation_result_source_for_group = "reused_cross_run"
            evaluation_results_reused_cross_run += len(ordered_group)
        else:
            _emit_status(
                (
                    "Evaluating signature "
                    f"{signature_index}/{max(1, evaluation_signatures_unique)} "
                    f"(group size {len(ordered_group)})."
                ),
                color=typer.colors.CYAN,
            )
            evaluation_summary = _run_all_method_evaluate_prediction_record_once(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                prediction_record_path=representative_prediction_record,
                eval_output_dir=representative_eval_output_dir,
                processed_output_dir=representative_processed_output_dir,
                sequence_matcher=sequence_matcher,
                epub_extractor=_row_dimension_str(representative_row, "epub_extractor"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                alignment_cache_dir=canonical_alignment_cache_dir,
                progress_callback=None,
            )
            if str(evaluation_summary.get("status") or "").strip().lower() == "ok":
                evaluation_runs_executed += 1
                if len(ordered_group) > 1:
                    evaluation_results_reused_in_run += len(ordered_group) - 1
                cached_payload = {
                    "schema_version": ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION,
                    "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "eval_signature": eval_signature,
                    "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                    "sequence_matcher": sequence_matcher,
                    "source_file": str(source_file),
                    "gold_spans_path": str(gold_spans_path),
                    "report": evaluation_summary.get("report"),
                    "report_md": evaluation_summary.get("report_md_text"),
                }
                try:
                    _write_all_method_eval_signature_cache_entry(
                        cache_path=cache_path,
                        payload=cached_payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Ignoring eval-signature cache write failure for %s: %s",
                        cache_path,
                        exc,
                    )

        if str(evaluation_summary.get("status") or "").strip().lower() != "ok":
            error_text = str(evaluation_summary.get("error") or "Evaluation failed.")
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = error_text
                failed_row["evaluation_result_source"] = "failed"
                failed_row["evaluation_representative_config_dir"] = representative_config_dir
                failed_row["eval_signature"] = eval_signature
                failed_rows.append(failed_row)
            continue

        summary_timing = _normalize_timing_payload(evaluation_summary.get("timing"))
        summary_evaluation_seconds = _report_optional_metric(
            summary_timing.get("evaluation_seconds")
        )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                summary_timing.get("total_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                evaluation_summary.get("duration_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = 0.0

        summary_eval_wall_seconds = max(
            0.0,
            _report_metric(evaluation_summary.get("duration_seconds")),
        )
        summary_report_json_path = Path(str(evaluation_summary.get("eval_report_json_path") or ""))
        summary_report_md_path = Path(str(evaluation_summary.get("eval_report_md_path") or ""))
        alignment_guardrail_fields = _all_method_extract_alignment_guardrail_fields(
            cast(dict[str, Any] | None, evaluation_summary.get("report"))
        )

        for row in ordered_group:
            result_row = dict(row)
            is_representative = (
                _report_count(result_row.get("config_index"))
                == _report_count(representative_row.get("config_index"))
            )
            row_result_source = "executed"
            if evaluation_result_source_for_group == "reused_cross_run":
                row_result_source = "reused_cross_run"
            elif not is_representative:
                row_result_source = "reused_in_run"

            row_timing = _normalize_timing_payload(result_row.get("timing"))
            prediction_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
            if prediction_total_seconds is None:
                prediction_total_seconds = _report_optional_metric(
                    result_row.get("duration_seconds")
                )
            if prediction_total_seconds is None:
                prediction_total_seconds = 0.0

            row_eval_seconds = summary_evaluation_seconds if row_result_source == "executed" else 0.0
            row_eval_wall = summary_eval_wall_seconds if row_result_source == "executed" else 0.0
            row_total_seconds = max(0.0, prediction_total_seconds + row_eval_seconds)
            row_timing = _timing_with_updates(
                row_timing,
                evaluation_seconds=row_eval_seconds,
                total_seconds=row_total_seconds,
                checkpoints={
                    "all_method_eval_wall_seconds": row_eval_wall,
                    "all_method_eval_reused_in_run": (
                        1.0 if row_result_source == "reused_in_run" else 0.0
                    ),
                    "all_method_eval_reused_cross_run": (
                        1.0 if row_result_source == "reused_cross_run" else 0.0
                    ),
                },
            )

            result_row["status"] = "ok"
            result_row["error"] = ""
            result_row["precision"] = _report_metric(evaluation_summary.get("precision"))
            result_row["recall"] = _report_metric(evaluation_summary.get("recall"))
            result_row["f1"] = _report_metric(evaluation_summary.get("f1"))
            result_row["practical_precision"] = _report_metric(
                evaluation_summary.get("practical_precision")
            )
            result_row["practical_recall"] = _report_metric(
                evaluation_summary.get("practical_recall")
            )
            result_row["practical_f1"] = _report_metric(evaluation_summary.get("practical_f1"))
            result_row.update(alignment_guardrail_fields)
            result_row["eval_signature"] = eval_signature
            result_row["evaluation_result_source"] = row_result_source
            result_row["evaluation_representative_config_dir"] = representative_config_dir
            result_row["duration_seconds"] = row_total_seconds
            result_row["timing"] = row_timing
            result_row["eval_report_json"] = _path_for_manifest(
                root_output_dir,
                summary_report_json_path,
            )
            result_row["eval_report_md"] = _path_for_manifest(
                root_output_dir,
                summary_report_md_path,
            )
            successful_rows.append(result_row)

    failed_rows.sort(key=lambda row: _report_count(row.get("config_index")))
    successful_rows.sort(
        key=lambda row: (
            _report_metric(row.get("f1")),
            _report_metric(row.get("practical_f1")),
            _report_metric(row.get("precision")),
            _report_metric(row.get("recall")),
        ),
        reverse=True,
    )
    for rank, row in enumerate(successful_rows, start=1):
        row["rank"] = rank

    matcher_guardrails = _all_method_build_matcher_guardrails(successful_rows)
    scheduler_summary["matcher_guardrails"] = matcher_guardrails
    for warning in matcher_guardrails.get("warnings", []):
        _emit_status(f"Matcher guardrail warning: {warning}", color=typer.colors.YELLOW)

    successful_timing: list[tuple[dict[str, Any], float]] = []
    for row in successful_rows:
        row_timing = _normalize_timing_payload(row.get("timing"))
        row_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
        if row_total_seconds is None:
            row_total_seconds = _report_optional_metric(row.get("duration_seconds"))
        if row_total_seconds is None:
            continue
        row["timing"] = _timing_with_updates(
            row_timing,
            total_seconds=row_total_seconds,
        )
        successful_timing.append((row, row_total_seconds))

    source_wall_seconds = max(0.0, time.monotonic() - source_started)
    total_config_seconds = sum(seconds for _row, seconds in successful_timing)
    average_config_seconds = (
        total_config_seconds / len(successful_timing) if successful_timing else None
    )
    median_config_seconds = _median_metric(
        [seconds for _row, seconds in successful_timing]
    )
    slowest_config_row = (
        max(successful_timing, key=lambda item: item[1])[0] if successful_timing else None
    )
    slowest_config_seconds = (
        max(seconds for _row, seconds in successful_timing) if successful_timing else None
    )

    winner = successful_rows[0] if successful_rows else None
    final_rows = successful_rows + failed_rows

    report_payload: dict[str, Any] = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_file": str(source_file),
        "gold_spans_path": str(gold_spans_path),
        "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        "scheduler_scope": "per_source",
        "variant_count": total_variants,
        "successful_variants": len(successful_rows),
        "failed_variants": len(failed_rows),
        "evaluation_signatures_unique": evaluation_signatures_unique,
        "evaluation_runs_executed": evaluation_runs_executed,
        "evaluation_results_reused_in_run": evaluation_results_reused_in_run,
        "evaluation_results_reused_cross_run": evaluation_results_reused_cross_run,
        "prediction_signatures_unique": _report_count(
            prediction_reuse_summary.get("prediction_signatures_unique")
        ),
        "prediction_runs_executed": _report_count(
            prediction_reuse_summary.get("prediction_runs_executed")
        ),
        "prediction_results_reused_in_run": _report_count(
            prediction_reuse_summary.get("prediction_results_reused_in_run")
        ),
        "prediction_results_reused_cross_run": _report_count(
            prediction_reuse_summary.get("prediction_results_reused_cross_run")
        ),
        "split_convert_input_groups": _report_count(
            prediction_reuse_summary.get("split_convert_input_groups")
        ),
        "split_convert_reuse_candidates": _report_count(
            prediction_reuse_summary.get("split_convert_reuse_candidates")
        ),
        "split_convert_reuse_safe_candidates": _report_count(
            prediction_reuse_summary.get("split_convert_reuse_safe_candidates")
        ),
        "split_convert_reuse_blocked_by_prediction_variance": _report_count(
            prediction_reuse_summary.get(
                "split_convert_reuse_blocked_by_prediction_variance"
            )
        ),
        "prediction_reuse_key_schema_version": (
            ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION
        ),
        "split_convert_input_key_schema_version": (
            ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION
        ),
        "evaluation_signature_cache_dir": str(eval_signature_cache_dir),
        "retry_failed_configs_requested": effective_retry_failed_configs,
        "retry_passes_executed": retry_passes_executed,
        "retry_recovered_configs": retry_recovered_configs,
        "include_codex_farm_requested": include_codex_farm_requested,
        "include_codex_farm_effective": include_codex_farm_effective,
        "prediction_reuse_cache_dir": str(prediction_reuse_cache_dir),
        "executor_resolution": {
            "process_workers_required": bool(require_process_workers),
            "process_worker_probe_available": process_worker_probe_available,
            "process_worker_probe_error": process_worker_probe_error,
            "config_executor_backends_seen": sorted(config_executor_backends_seen),
        },
        "timing_summary": {
            "source_wall_seconds": source_wall_seconds,
            "config_total_seconds": total_config_seconds,
            "config_average_seconds": average_config_seconds,
            "config_median_seconds": median_config_seconds,
            "slowest_config_dir": (
                str(slowest_config_row.get("config_dir"))
                if isinstance(slowest_config_row, dict)
                else None
            ),
            "slowest_config_seconds": slowest_config_seconds,
        },
        "scheduler": scheduler_summary,
        "variants": final_rows,
        "winner_by_f1": winner,
    }

    report_json_path = root_output_dir / "all_method_benchmark_report.json"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = root_output_dir / "all_method_benchmark_report.md"
    report_md_path.write_text(
        _render_all_method_report_md(report_payload),
        encoding="utf-8",
    )

    if refresh_dashboard_after_source:
        history_csv_path = history_csv_for_output(
            processed_output_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
        )
        resolved_dashboard_output_root = (
            dashboard_output_root.expanduser()
            if dashboard_output_root is not None
            else None
        )
        _refresh_dashboard_after_history_write(
            csv_path=history_csv_path,
            output_root=resolved_dashboard_output_root,
            golden_root=golden_root,
            dashboard_out_dir=(
                history_root_for_output(resolved_dashboard_output_root) / "dashboard"
                if resolved_dashboard_output_root is not None
                else None
            ),
            reason="all-method benchmark source batch append",
        )

    completion_color = (
        typer.colors.GREEN if len(failed_rows) == 0 else typer.colors.YELLOW
    )
    _emit_status(
        (
            "All method benchmark complete: "
            f"{len(successful_rows)}/{total_variants} configs evaluated successfully."
        ),
        color=completion_color,
    )
    if progress_callback is None:
        if successful_rows:
            typer.secho("Top configurations by strict F1:", fg=typer.colors.CYAN)
            for row in successful_rows[:3]:
                typer.echo(
                    (
                        f"  {row.get('rank')}) {row.get('config_dir')} "
                        f"p={_report_metric(row.get('precision')):.3f} "
                        f"r={_report_metric(row.get('recall')):.3f} "
                        f"f1={_report_metric(row.get('f1')):.3f}"
                    )
                )
        typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)
    return report_md_path

def _interactive_all_method_benchmark(
    *,
    selected_benchmark_settings: RunSettings,
    benchmark_eval_output: Path,
    processed_output_root: Path,
    golden_root: Path | None = None,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    scheduler_scope: str | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool | None = None,
) -> None:
    resolved_golden_root = golden_root or DEFAULT_GOLDEN
    scope_choice = _menu_select(
        "Select all method benchmark scope:",
        menu_help=(
            "Choose one gold/source pair (current behavior) or fan out "
            "across all freeform gold exports that match importable data/input files."
        ),
        choices=[
            questionary.Choice("Single golden set", value="single"),
            questionary.Choice(
                "All golden sets with matching input files",
                value="all_matched",
            ),
        ],
    )
    if scope_choice in {None, BACK_ACTION}:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return

    scope_all_matched = scope_choice == "all_matched"
    if scope_all_matched:
        targets, unmatched_targets = _resolve_all_method_targets(resolved_golden_root)
        if not targets:
            typer.secho(
                "No matched golden sets were found in data/input. Nothing to benchmark.",
                fg=typer.colors.YELLOW,
            )
            if unmatched_targets:
                typer.secho(
                    f"Skipped golden sets: {len(unmatched_targets)}",
                    fg=typer.colors.YELLOW,
                )
                for unmatched in unmatched_targets[:5]:
                    source_hint_text = unmatched.source_hint or "none"
                    typer.echo(
                        f"  - {unmatched.gold_display}: {unmatched.reason} "
                        f"(source hint: {source_hint_text})"
                    )
                if len(unmatched_targets) > 5:
                    typer.echo(
                        f"  - ... {len(unmatched_targets) - 5} additional skipped golden sets"
                    )
            return
    else:
        resolved_inputs = _resolve_benchmark_gold_and_source(
            gold_spans=None,
            source_file=None,
            output_dir=resolved_golden_root,
            allow_cancel=True,
        )
        if resolved_inputs is None:
            return
        selected_gold, selected_source = resolved_inputs
        targets = [
            AllMethodTarget(
                gold_spans_path=selected_gold,
                source_file=selected_source,
                source_file_name=selected_source.name,
                gold_display=_display_gold_export_path(selected_gold, resolved_golden_root),
            )
        ]
        unmatched_targets = []

    include_markdown_extractors = _resolve_all_method_markdown_extractors_choice()
    include_deterministic_sweeps = _prompt_confirm(
        (
            "Try deterministic option sweeps too? (section detector, multi-recipe splitting, "
            "ingredient missing-unit policy, instruction step segmentation, time/temp/yield)"
        ),
        default=True,
    )
    if include_deterministic_sweeps is None:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return
    if include_deterministic_sweeps:
        missing: list[str] = []
        if not _all_method_optional_module_available("pysbd"):
            missing.append("pysbd (instruction step segmenter)")
        if not _all_method_optional_module_available("quantulum3"):
            missing.append("quantulum3 (time/temp backends)")
        if not _all_method_optional_module_available("pint"):
            missing.append("pint (temperature units)")
        if missing:
            typer.secho(
                "Deterministic sweeps note: optional deps missing, some variants will be skipped: "
                + ", ".join(missing),
                fg=typer.colors.BRIGHT_BLACK,
            )
    base_target_variants = _build_all_method_target_variants(
        targets=targets,
        base_settings=selected_benchmark_settings,
        include_codex_farm=False,
        include_markdown_extractors=include_markdown_extractors,
        include_deterministic_sweeps=bool(include_deterministic_sweeps),
    )
    total_base_runs = sum(len(variants) for _target, variants in base_target_variants)
    if total_base_runs <= 0:
        typer.secho("No benchmark variants were generated for this selection.", fg=typer.colors.YELLOW)
        return

    if include_markdown_extractors:
        typer.secho(
            (
                "All method includes markdown + markitdown extractor variants "
                f"(enabled via {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 and "
                f"{ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1)."
            ),
            fg=typer.colors.YELLOW,
        )
    else:
        if markdown_epub_extractors_enabled():
            typer.secho(
                (
                    "All method excludes markdown + markitdown extractor variants by default. "
                    f"Set {ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1 to include them."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )
        else:
            typer.secho(
                (
                    "Markdown + markitdown extractors are policy-locked off. "
                    f"Set {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 to temporarily re-enable "
                    "them, then set "
                    f"{ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1 to include them in all method."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )

    if scope_all_matched:
        typer.secho(
            f"Matched golden sets: {len(targets)}",
            fg=typer.colors.CYAN,
        )
        skipped_color = typer.colors.YELLOW if unmatched_targets else typer.colors.BRIGHT_BLACK
        typer.secho(
            f"Skipped golden sets: {len(unmatched_targets)}",
            fg=skipped_color,
        )
        typer.secho(
            (
                "All method benchmark will run "
                f"{total_base_runs} configurations across {len(targets)} matched golden sets "
                "(Codex Farm excluded)."
            ),
            fg=typer.colors.CYAN,
        )
        if unmatched_targets:
            typer.secho("Skipped golden set samples:", fg=typer.colors.BRIGHT_BLACK)
            for unmatched in unmatched_targets[:5]:
                source_hint_text = unmatched.source_hint or "none"
                typer.echo(
                    f"  - {unmatched.gold_display}: {unmatched.reason} "
                    f"(source hint: {source_hint_text})"
                )
            if len(unmatched_targets) > 5:
                typer.echo(
                    f"  - ... {len(unmatched_targets) - 5} additional skipped golden sets"
                )
    else:
        selected_source = targets[0].source_file
        typer.secho(
            f"All method benchmark will run {total_base_runs} configurations (Codex Farm excluded).",
            fg=typer.colors.CYAN,
        )
        if selected_source.suffix.lower() == ".epub":
            typer.secho(
                (
                    "Dimensions: epub_extractor + unstructured parser/skip_headers/preprocess, "
                    "plus deterministic option sweeps when enabled."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )
        else:
            typer.secho(
                "Dimensions: non-EPUB source uses global benchmark run settings (plus sweeps when enabled).",
                fg=typer.colors.BRIGHT_BLACK,
            )
    typer.secho(
        "CodexFarm process selection is available for all-method runs.",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.secho(
        "All method benchmark uses canonical-text eval mode (extractor-independent).",
        fg=typer.colors.BRIGHT_BLACK,
    )

    all_method_codex_defaults_payload = {
        key: value
        for key, value in selected_benchmark_settings.model_dump(
            mode="json", exclude_none=True
        ).items()
        if key in RunSettings.model_fields
    }
    all_method_codex_defaults_payload.update(
        {
            "llm_recipe_pipeline": RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
            "line_role_pipeline": LINE_ROLE_PIPELINE_ROUTE_V2,
            "llm_knowledge_pipeline": KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
            "atomic_block_splitter": str(
                all_method_codex_defaults_payload.get("atomic_block_splitter") or "off"
            ),
        }
    )
    all_method_codex_settings = choose_interactive_codex_surfaces(
        selected_settings=RunSettings.from_dict(
            all_method_codex_defaults_payload,
            warn_context="interactive all-method codex defaults",
        ),
        back_action=BACK_ACTION,
        surface_options=("recipe", "line_role", "knowledge"),
        prompt_codex_shard_plan_menu=_prompt_codex_shard_plan_menu,
    )
    if all_method_codex_settings is None:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return
    include_codex_requested = _all_method_settings_enable_any_codex(
        all_method_codex_settings
    )
    include_codex_effective, codex_warning = _resolve_all_method_codex_choice(
        include_codex_requested
    )
    if codex_warning:
        typer.secho(codex_warning, fg=typer.colors.YELLOW)

    benchmark_settings_for_variants = selected_benchmark_settings
    if include_codex_effective:
        _ensure_codex_farm_cmd_available(selected_benchmark_settings.codex_farm_cmd)
        all_method_codex_settings = choose_codex_ai_settings(
            selected_settings=all_method_codex_settings,
            menu_select=_menu_select,
            back_action=BACK_ACTION,
        )
        if all_method_codex_settings is None:
            typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
            return
        benchmark_settings_for_variants = all_method_codex_settings

    selected_target_variants = _build_all_method_target_variants(
        targets=targets,
        base_settings=benchmark_settings_for_variants,
        include_codex_farm=include_codex_effective,
        codex_variant_settings=(
            benchmark_settings_for_variants if include_codex_effective else None
        ),
        include_markdown_extractors=include_markdown_extractors,
        include_deterministic_sweeps=bool(include_deterministic_sweeps),
    )
    total_selected_runs = sum(
        len(variants) for _target, variants in selected_target_variants
    )
    if total_selected_runs <= 0:
        typer.secho("No benchmark variants were generated for this selection.", fg=typer.colors.YELLOW)
        return
    total_sources_selected = max(1, len(selected_target_variants))
    source_parallelism_default = min(
        _all_method_default_parallel_sources_from_cpu(),
        total_sources_selected,
    )
    requested_source_parallelism = _report_count(max_parallel_sources)
    source_parallelism_configured = (
        requested_source_parallelism
        if requested_source_parallelism > 0
        else source_parallelism_default
    )
    source_parallelism_effective = _resolve_all_method_source_parallelism(
        total_sources=total_sources_selected,
        requested=max_parallel_sources,
    )
    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=total_selected_runs,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=source_parallelism_effective,
    )
    resolved_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    resolved_split_phase_slots = scheduler_runtime.split_phase_slots
    resolved_wing_backlog_target = scheduler_runtime.wing_backlog_target
    resolved_eval_tail_headroom_configured = (
        scheduler_runtime.eval_tail_headroom_configured
    )
    resolved_eval_tail_headroom_effective = (
        scheduler_runtime.eval_tail_headroom_effective
    )
    resolved_eval_tail_mode = scheduler_runtime.eval_tail_headroom_mode
    resolved_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    resolved_max_active_during_eval = scheduler_runtime.max_active_during_eval
    resolved_effective_inflight_pipelines = (
        scheduler_runtime.effective_inflight_pipelines
    )
    resolved_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    resolved_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    resolved_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )
    resolved_scheduler_scope = _normalize_all_method_scheduler_scope(scheduler_scope)
    resolved_source_scheduling = _normalize_all_method_source_scheduling(
        source_scheduling
    )
    resolved_source_shard_threshold_seconds = (
        _coerce_positive_float(source_shard_threshold_seconds)
        or ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
    )
    resolved_source_shard_max_parts = (
        _coerce_positive_int(source_shard_max_parts)
        or ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
    )
    resolved_source_shard_min_variants = (
        _coerce_positive_int(source_shard_min_variants)
        or ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
    )
    timeout_display = (
        f"{resolved_config_timeout_seconds}s"
        if resolved_config_timeout_seconds is not None
        else "off"
    )
    scheduler_mode = "smart" if resolved_smart_scheduler else "fixed"
    typer.secho(
        (
            "Scheduler: "
            f"scope={resolved_scheduler_scope}, "
            f"source parallel={source_parallelism_effective} "
            f"(configured {source_parallelism_configured}, "
            f"default {_all_method_default_parallel_sources_from_cpu()}), "
            f"source scheduling={resolved_source_scheduling}, "
            "source sharding threshold/max_parts/min_variants="
            f"{resolved_source_shard_threshold_seconds:.1f}/"
            f"{resolved_source_shard_max_parts}/"
            f"{resolved_source_shard_min_variants}, "
            f"mode={scheduler_mode}, "
            f"configured inflight={resolved_inflight_pipelines} "
            f"(default {ALL_METHOD_MAX_INFLIGHT_DEFAULT}), "
            f"effective inflight={resolved_effective_inflight_pipelines}, "
            f"split slots={resolved_split_phase_slots} "
            f"(default {ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT}), "
            f"eval headroom ({resolved_eval_tail_mode}) configured/effective="
            f"{resolved_eval_tail_headroom_configured}/"
            f"{resolved_eval_tail_headroom_effective}, "
            f"max active during eval={resolved_max_active_during_eval}, "
            f"cpu budget/source={resolved_cpu_budget_per_source}, "
            f"config timeout={timeout_display} "
            f"(default {ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT}s), "
            f"failed retries={resolved_retry_failed_configs} "
            f"(default {ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT}), "
            f"wing backlog={resolved_wing_backlog_target} "
            "(default split slots)"
        ),
        fg=typer.colors.BRIGHT_BLACK,
    )

    if scope_all_matched:
        proceed_prompt = (
            f"Proceed with {total_selected_runs} benchmark runs across "
            f"{len(targets)} matched golden sets?"
        )
    else:
        proceed_prompt = f"Proceed with {total_selected_runs} benchmark runs?"
    proceed = _prompt_confirm(
        proceed_prompt,
        default=False,
    )
    if proceed is not True:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return

    all_method_root = benchmark_eval_output / "all-method-benchmark"
    all_method_processed_root = (
        processed_output_root
        / benchmark_eval_output.name
        / "all-method-benchmark"
    )
    all_method_canonical_cache_root = _resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=all_method_root
    )
    typer.secho(
        (
            "All method canonical alignment cache root: "
            f"{all_method_canonical_cache_root}"
        ),
        fg=typer.colors.BRIGHT_BLACK,
    )

    status_initial = "Running all method benchmark..."
    status_prefix = "All method benchmark"

    if scope_all_matched:
        dashboard = _AllMethodProgressDashboard.from_target_variants(
            selected_target_variants
        )
        report_md_path = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
            telemetry_path=all_method_root / PROCESSING_TIMESERIES_FILENAME,
            run=lambda update_progress: _run_all_method_benchmark_multi_source(
                target_variants=selected_target_variants,
                unmatched_targets=unmatched_targets,
                include_codex_farm_requested=include_codex_requested,
                include_codex_farm_effective=include_codex_effective,
                root_output_dir=all_method_root,
                processed_output_root=all_method_processed_root,
                golden_root=resolved_golden_root,
                overlap_threshold=0.5,
                force_source_match=False,
                progress_callback=update_progress,
                dashboard=dashboard,
                max_parallel_sources=max_parallel_sources,
                max_inflight_pipelines=resolved_inflight_pipelines,
                max_concurrent_split_phases=resolved_split_phase_slots,
                max_eval_tail_pipelines=max_eval_tail_pipelines,
                config_timeout_seconds=resolved_config_timeout_seconds,
                retry_failed_configs=resolved_retry_failed_configs,
                source_scheduling=resolved_source_scheduling,
                source_shard_threshold_seconds=resolved_source_shard_threshold_seconds,
                source_shard_max_parts=resolved_source_shard_max_parts,
                source_shard_min_variants=resolved_source_shard_min_variants,
                wing_backlog_target=resolved_wing_backlog_target,
                smart_scheduler=resolved_smart_scheduler,
                scheduler_scope=resolved_scheduler_scope,
                canonical_alignment_cache_root=all_method_canonical_cache_root,
                dashboard_output_root=processed_output_root,
            ),
        )
        typer.secho(
            f"All method benchmark summary report: {report_md_path}",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            f"All method processing telemetry: {all_method_root / PROCESSING_TIMESERIES_FILENAME}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    else:
        single_target = targets[0]
        single_variants = selected_target_variants[0][1]
        single_root = all_method_root / slugify_name(single_target.source_file.stem)
        single_processed_root = all_method_processed_root / slugify_name(
            single_target.source_file.stem
        )
        dashboard = _AllMethodProgressDashboard.from_target_variants(
            [(single_target, single_variants)]
        )

        def _run_single_source(update_progress: Callable[[str], None]) -> Path:
            dashboard.start_source(0)
            dashboard.set_task(f"Running source 1/1: {single_target.source_file_name}")
            update_progress(dashboard.render())
            try:
                report_path = _run_all_method_benchmark(
                    gold_spans_path=single_target.gold_spans_path,
                    source_file=single_target.source_file,
                    variants=single_variants,
                    include_codex_farm_requested=include_codex_requested,
                    include_codex_farm_effective=include_codex_effective,
                    root_output_dir=single_root,
                    processed_output_root=single_processed_root,
                    golden_root=resolved_golden_root,
                    overlap_threshold=0.5,
                    force_source_match=False,
                    progress_callback=update_progress,
                    dashboard=dashboard,
                    dashboard_source_index=0,
                    max_inflight_pipelines=resolved_inflight_pipelines,
                    max_concurrent_split_phases=resolved_split_phase_slots,
                    max_eval_tail_pipelines=max_eval_tail_pipelines,
                    config_timeout_seconds=resolved_config_timeout_seconds,
                    retry_failed_configs=resolved_retry_failed_configs,
                    wing_backlog_target=resolved_wing_backlog_target,
                    smart_scheduler=resolved_smart_scheduler,
                    source_parallelism_effective=source_parallelism_effective,
                    canonical_alignment_cache_dir_override=(
                        all_method_canonical_cache_root
                        / slugify_name(single_target.source_file.stem)
                    ),
                    dashboard_output_root=processed_output_root,
                )
            except Exception:
                dashboard.finish_source(0, failed=True)
                dashboard.set_task("Source failed.")
                update_progress(dashboard.render())
                raise
            dashboard.finish_source(0, failed=False)
            dashboard.set_task("Source complete.")
            update_progress(dashboard.render())
            return report_path

        report_md_path = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
            telemetry_path=single_root / PROCESSING_TIMESERIES_FILENAME,
            run=_run_single_source,
        )
        typer.secho(f"All method benchmark report: {report_md_path}", fg=typer.colors.CYAN)
        typer.secho(
            f"All method processing telemetry: {single_root / PROCESSING_TIMESERIES_FILENAME}",
            fg=typer.colors.BRIGHT_BLACK,
        )

    typer.secho(
        f"All method processed outputs: {all_method_processed_root}",
        fg=typer.colors.CYAN,
    )

INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK = "single_book"
INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS = "selected_matched_books"
INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS = "all_matched_books"
