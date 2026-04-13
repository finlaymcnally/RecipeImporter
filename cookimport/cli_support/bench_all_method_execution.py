from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from .bench_all_method_types import AllMethodVariant


def _run_all_method_prediction_once_impl(
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
    from .bench_all_method import (
        BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION,
        ALL_METHOD_PREDICTION_REUSE_LOCK_SUFFIX,
        _acquire_all_method_prediction_reuse_lock,
        _all_method_config_dir_name,
        _all_method_failed_row,
        _all_method_prediction_reuse_cache_entry_path,
        _benchmark_progress_overrides,
        _benchmark_scheduler_event_overrides,
        _benchmark_split_phase_overrides,
        _build_all_method_prediction_reuse_key,
        _build_all_method_split_convert_input_key,
        _copy_all_method_prediction_artifacts_for_reuse,
        _load_all_method_prediction_reuse_cache_entry,
        _load_pred_run_recipe_context,
        _normalize_timing_payload,
        _path_for_manifest,
        _path_is_within_root,
        _release_all_method_prediction_reuse_lock,
        _report_count,
        _report_optional_metric,
        _resolve_all_method_prediction_reuse_cache_dir,
        _run_offline_benchmark_prediction_stage,
        _timing_with_updates,
        _wait_for_all_method_prediction_reuse_cache_entry,
        _write_all_method_prediction_reuse_cache_entry,
        build_benchmark_call_kwargs_from_run_settings,
        codex_surfaces_enabled,
        dt,
        format_task_counter,
        json as root_json,
        logger,
        read_prediction_records,
        slugify_name,
    )

    del gold_spans_path, overlap_threshold, force_source_match, alignment_cache_dir
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
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "monotonic_seconds": time.monotonic(),
            "config_index": config_index,
            "config_slug": variant.slug,
            "config_dir": config_dir_name,
            "source_slug": source_slug,
        }
        row.update(payload)
        try:
            with scheduler_event_path.open("a", encoding="utf-8") as handle:
                handle.write(root_json.dumps(row, sort_keys=True) + "\n")
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
    requested_pdf_split_workers = max(
        1, _report_count(variant.run_settings.pdf_split_workers)
    )
    requested_epub_split_workers = max(
        1, _report_count(variant.run_settings.epub_split_workers)
    )
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
                            "line_role_codex_exec_style": benchmark_kwargs[
                                "line_role_codex_exec_style"
                            ],
                            "knowledge_codex_exec_style": benchmark_kwargs[
                                "knowledge_codex_exec_style"
                            ],
                            "knowledge_inline_repair_transcript_mode": benchmark_kwargs[
                                "knowledge_inline_repair_transcript_mode"
                            ],
                            "recipe_codex_exec_style": benchmark_kwargs[
                                "recipe_codex_exec_style"
                            ],
                            "codex_farm_cmd": benchmark_kwargs["codex_farm_cmd"],
                            "codex_farm_model": benchmark_kwargs.get(
                                "codex_farm_model"
                            ),
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
                            elapsed_seconds=max(
                                0.0, time.monotonic() - config_started
                            ),
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
                            elapsed_seconds=max(
                                0.0, time.monotonic() - config_started
                            ),
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
            run_manifest_payload = json.loads(
                run_manifest_path.read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001
            run_manifest_payload = {}
        if isinstance(run_manifest_payload, dict):
            artifacts_payload = run_manifest_payload.get("artifacts")
            if isinstance(artifacts_payload, dict):
                report_timing = _normalize_timing_payload(
                    artifacts_payload.get("timing")
                )

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
            report_total_seconds
            if report_total_seconds is not None
            else config_wall_seconds
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
        "run_config_hash": pred_context.run_config_hash
        or variant.run_settings.stable_hash(),
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


def _run_all_method_evaluate_prediction_record_once_impl(
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
    from .bench_all_method import (
        _LAST_FAIL_MESSAGE,
        BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        _benchmark_progress_overrides,
        _benchmark_report_metric_bundle,
        _labelstudio_benchmark_command,
        _normalize_timing_payload,
        _report_optional_metric,
        _timing_with_updates,
        typer,
    )

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
