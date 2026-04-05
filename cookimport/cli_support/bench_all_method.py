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
from .bench_all_method_execution import (
    _run_all_method_evaluate_prediction_record_once_impl,
    _run_all_method_prediction_once_impl,
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
    return _run_all_method_prediction_once_impl(
        gold_spans_path=gold_spans_path,
        source_file=source_file,
        variant=variant,
        config_index=config_index,
        total_variants=total_variants,
        root_output_dir=root_output_dir,
        scratch_root=scratch_root,
        processed_output_root=processed_output_root,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
        max_concurrent_split_phases=max_concurrent_split_phases,
        split_phase_gate_dir=split_phase_gate_dir,
        scheduler_events_dir=scheduler_events_dir,
        alignment_cache_dir=alignment_cache_dir,
        prediction_reuse_cache_dir=prediction_reuse_cache_dir,
        split_worker_cap_per_config=split_worker_cap_per_config,
        progress_callback=progress_callback,
    )


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
    return _run_all_method_evaluate_prediction_record_once_impl(
        gold_spans_path=gold_spans_path,
        source_file=source_file,
        prediction_record_path=prediction_record_path,
        eval_output_dir=eval_output_dir,
        processed_output_dir=processed_output_dir,
        sequence_matcher=sequence_matcher,
        epub_extractor=epub_extractor,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
        alignment_cache_dir=alignment_cache_dir,
        progress_callback=progress_callback,
    )


from .bench_all_method_runtime import (
    _run_all_method_benchmark as _run_all_method_benchmark_impl,
    _run_all_method_benchmark_global_queue as _run_all_method_benchmark_global_queue_impl,
    _run_all_method_benchmark_multi_source as _run_all_method_benchmark_multi_source_impl,
)
from .bench_all_method_interactive import (
    _interactive_all_method_benchmark as _interactive_all_method_benchmark_impl,
)


def _run_all_method_benchmark_global_queue(*args, **kwargs):
    return _run_all_method_benchmark_global_queue_impl(*args, **kwargs)


def _run_all_method_benchmark_multi_source(*args, **kwargs):
    return _run_all_method_benchmark_multi_source_impl(*args, **kwargs)


def _run_all_method_benchmark(*args, **kwargs):
    return _run_all_method_benchmark_impl(*args, **kwargs)


def _interactive_all_method_benchmark(*args, **kwargs):
    return _interactive_all_method_benchmark_impl(*args, **kwargs)


INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK = "single_book"
INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS = "selected_matched_books"
INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS = "all_matched_books"
