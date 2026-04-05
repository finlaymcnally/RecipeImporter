from __future__ import annotations

import cookimport.cli_support.bench_all_method as root

def _interactive_all_method_benchmark(*, selected_benchmark_settings: root.RunSettings, benchmark_eval_output: root.Path, processed_output_root: root.Path, golden_root: root.Path | None=None, max_parallel_sources: int | None=None, max_inflight_pipelines: int | None=None, max_concurrent_split_phases: int | None=None, max_eval_tail_pipelines: int | None=None, config_timeout_seconds: int | None=None, retry_failed_configs: int | None=None, scheduler_scope: str | None=None, source_scheduling: str | None=None, source_shard_threshold_seconds: float | None=None, source_shard_max_parts: int | None=None, source_shard_min_variants: int | None=None, wing_backlog_target: int | None=None, smart_scheduler: bool | None=None) -> None:
    resolved_golden_root = golden_root or root.DEFAULT_GOLDEN
    scope_choice = root._menu_select('Select all method benchmark scope:', menu_help='Choose one gold/source pair (current behavior) or fan out across all freeform gold exports that match importable data/input files.', choices=[root.questionary.Choice('Single golden set', value='single'), root.questionary.Choice('All golden sets with matching input files', value='all_matched')])
    if scope_choice in {None, root.BACK_ACTION}:
        root.typer.secho('All method benchmark cancelled.', fg=root.typer.colors.YELLOW)
        return
    scope_all_matched = scope_choice == 'all_matched'
    if scope_all_matched:
        targets, unmatched_targets = root._resolve_all_method_targets(resolved_golden_root)
        if not targets:
            root.typer.secho('No matched golden sets were found in data/input. Nothing to benchmark.', fg=root.typer.colors.YELLOW)
            if unmatched_targets:
                root.typer.secho(f'Skipped golden sets: {len(unmatched_targets)}', fg=root.typer.colors.YELLOW)
                for unmatched in unmatched_targets[:5]:
                    source_hint_text = unmatched.source_hint or 'none'
                    root.typer.echo(f'  - {unmatched.gold_display}: {unmatched.reason} (source hint: {source_hint_text})')
                if len(unmatched_targets) > 5:
                    root.typer.echo(f'  - ... {len(unmatched_targets) - 5} additional skipped golden sets')
            return
    else:
        resolved_inputs = root._resolve_benchmark_gold_and_source(gold_spans=None, source_file=None, output_dir=resolved_golden_root, allow_cancel=True)
        if resolved_inputs is None:
            return
        selected_gold, selected_source = resolved_inputs
        targets = [root.AllMethodTarget(gold_spans_path=selected_gold, source_file=selected_source, source_file_name=selected_source.name, gold_display=root._display_gold_export_path(selected_gold, resolved_golden_root))]
        unmatched_targets = []
    include_markdown_extractors = root._resolve_all_method_markdown_extractors_choice()
    include_deterministic_sweeps = root._prompt_confirm('Try deterministic option sweeps too? (section detector, multi-recipe splitting, ingredient missing-unit policy, instruction step segmentation, time/temp/yield)', default=True)
    if include_deterministic_sweeps is None:
        root.typer.secho('All method benchmark cancelled.', fg=root.typer.colors.YELLOW)
        return
    if include_deterministic_sweeps:
        missing: list[str] = []
        if not root._all_method_optional_module_available('pysbd'):
            missing.append('pysbd (instruction step segmenter)')
        if not root._all_method_optional_module_available('quantulum3'):
            missing.append('quantulum3 (time/temp backends)')
        if not root._all_method_optional_module_available('pint'):
            missing.append('pint (temperature units)')
        if missing:
            root.typer.secho('Deterministic sweeps note: optional deps missing, some variants will be skipped: ' + ', '.join(missing), fg=root.typer.colors.BRIGHT_BLACK)
    base_target_variants = root._build_all_method_target_variants(targets=targets, base_settings=selected_benchmark_settings, include_codex_farm=False, include_markdown_extractors=include_markdown_extractors, include_deterministic_sweeps=bool(include_deterministic_sweeps))
    total_base_runs = sum((len(variants) for _target, variants in base_target_variants))
    if total_base_runs <= 0:
        root.typer.secho('No benchmark variants were generated for this selection.', fg=root.typer.colors.YELLOW)
        return
    if include_markdown_extractors:
        root.typer.secho(f'All method includes markdown + markitdown extractor variants (enabled via {root.EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 and {root.ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1).', fg=root.typer.colors.YELLOW)
    elif root.markdown_epub_extractors_enabled():
        root.typer.secho(f'All method excludes markdown + markitdown extractor variants by default. Set {root.ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1 to include them.', fg=root.typer.colors.BRIGHT_BLACK)
    else:
        root.typer.secho(f'Markdown + markitdown extractors are policy-locked off. Set {root.EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 to temporarily re-enable them, then set {root.ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1 to include them in all method.', fg=root.typer.colors.BRIGHT_BLACK)
    if scope_all_matched:
        root.typer.secho(f'Matched golden sets: {len(targets)}', fg=root.typer.colors.CYAN)
        skipped_color = root.typer.colors.YELLOW if unmatched_targets else root.typer.colors.BRIGHT_BLACK
        root.typer.secho(f'Skipped golden sets: {len(unmatched_targets)}', fg=skipped_color)
        root.typer.secho(f'All method benchmark will run {total_base_runs} configurations across {len(targets)} matched golden sets (Codex Farm excluded).', fg=root.typer.colors.CYAN)
        if unmatched_targets:
            root.typer.secho('Skipped golden set samples:', fg=root.typer.colors.BRIGHT_BLACK)
            for unmatched in unmatched_targets[:5]:
                source_hint_text = unmatched.source_hint or 'none'
                root.typer.echo(f'  - {unmatched.gold_display}: {unmatched.reason} (source hint: {source_hint_text})')
            if len(unmatched_targets) > 5:
                root.typer.echo(f'  - ... {len(unmatched_targets) - 5} additional skipped golden sets')
    else:
        selected_source = targets[0].source_file
        root.typer.secho(f'All method benchmark will run {total_base_runs} configurations (Codex Farm excluded).', fg=root.typer.colors.CYAN)
        if selected_source.suffix.lower() == '.epub':
            root.typer.secho('Dimensions: epub_extractor + unstructured parser/skip_headers/preprocess, plus deterministic option sweeps when enabled.', fg=root.typer.colors.BRIGHT_BLACK)
        else:
            root.typer.secho('Dimensions: non-EPUB source uses global benchmark run settings (plus sweeps when enabled).', fg=root.typer.colors.BRIGHT_BLACK)
    root.typer.secho('CodexFarm process selection is available for all-method runs.', fg=root.typer.colors.BRIGHT_BLACK)
    root.typer.secho('All method benchmark uses canonical-text eval mode (extractor-independent).', fg=root.typer.colors.BRIGHT_BLACK)
    all_method_codex_defaults_payload = {key: value for key, value in selected_benchmark_settings.model_dump(mode='json', exclude_none=True).items() if key in root.RunSettings.model_fields}
    all_method_codex_defaults_payload.update({'llm_recipe_pipeline': root.RECIPE_CODEX_FARM_PIPELINE_SHARD_V1, 'line_role_pipeline': root.LINE_ROLE_PIPELINE_ROUTE_V2, 'llm_knowledge_pipeline': root.KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2, 'atomic_block_splitter': str(all_method_codex_defaults_payload.get('atomic_block_splitter') or 'off')})
    all_method_codex_settings = root.choose_interactive_codex_surfaces(selected_settings=root.RunSettings.from_dict(all_method_codex_defaults_payload, warn_context='interactive all-method codex defaults'), back_action=root.BACK_ACTION, surface_options=('recipe', 'line_role', 'knowledge'), prompt_codex_shard_plan_menu=root._prompt_codex_shard_plan_menu)
    if all_method_codex_settings is None:
        root.typer.secho('All method benchmark cancelled.', fg=root.typer.colors.YELLOW)
        return
    include_codex_requested = root._all_method_settings_enable_any_codex(all_method_codex_settings)
    include_codex_effective, codex_warning = root._resolve_all_method_codex_choice(include_codex_requested)
    if codex_warning:
        root.typer.secho(codex_warning, fg=root.typer.colors.YELLOW)
    benchmark_settings_for_variants = selected_benchmark_settings
    if include_codex_effective:
        root._ensure_codex_farm_cmd_available(selected_benchmark_settings.codex_farm_cmd)
        all_method_codex_settings = root.choose_codex_ai_settings(selected_settings=all_method_codex_settings, menu_select=root._menu_select, back_action=root.BACK_ACTION)
        if all_method_codex_settings is None:
            root.typer.secho('All method benchmark cancelled.', fg=root.typer.colors.YELLOW)
            return
        benchmark_settings_for_variants = all_method_codex_settings
    selected_target_variants = root._build_all_method_target_variants(targets=targets, base_settings=benchmark_settings_for_variants, include_codex_farm=include_codex_effective, codex_variant_settings=benchmark_settings_for_variants if include_codex_effective else None, include_markdown_extractors=include_markdown_extractors, include_deterministic_sweeps=bool(include_deterministic_sweeps))
    total_selected_runs = sum((len(variants) for _target, variants in selected_target_variants))
    if total_selected_runs <= 0:
        root.typer.secho('No benchmark variants were generated for this selection.', fg=root.typer.colors.YELLOW)
        return
    total_sources_selected = max(1, len(selected_target_variants))
    source_parallelism_default = min(root._all_method_default_parallel_sources_from_cpu(), total_sources_selected)
    requested_source_parallelism = root._report_count(max_parallel_sources)
    source_parallelism_configured = requested_source_parallelism if requested_source_parallelism > 0 else source_parallelism_default
    source_parallelism_effective = root._resolve_all_method_source_parallelism(total_sources=total_sources_selected, requested=max_parallel_sources)
    scheduler_runtime = root._resolve_all_method_scheduler_runtime(total_variants=total_selected_runs, max_inflight_pipelines=max_inflight_pipelines, max_concurrent_split_phases=max_concurrent_split_phases, max_eval_tail_pipelines=max_eval_tail_pipelines, wing_backlog_target=wing_backlog_target, smart_scheduler=smart_scheduler, source_parallelism_effective=source_parallelism_effective)
    resolved_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    resolved_split_phase_slots = scheduler_runtime.split_phase_slots
    resolved_wing_backlog_target = scheduler_runtime.wing_backlog_target
    resolved_eval_tail_headroom_configured = scheduler_runtime.eval_tail_headroom_configured
    resolved_eval_tail_headroom_effective = scheduler_runtime.eval_tail_headroom_effective
    resolved_eval_tail_mode = scheduler_runtime.eval_tail_headroom_mode
    resolved_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    resolved_max_active_during_eval = scheduler_runtime.max_active_during_eval
    resolved_effective_inflight_pipelines = scheduler_runtime.effective_inflight_pipelines
    resolved_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    resolved_config_timeout_seconds = root._resolve_all_method_config_timeout_seconds(config_timeout_seconds)
    resolved_retry_failed_configs = root._resolve_all_method_retry_failed_configs(retry_failed_configs)
    resolved_scheduler_scope = root._normalize_all_method_scheduler_scope(scheduler_scope)
    resolved_source_scheduling = root._normalize_all_method_source_scheduling(source_scheduling)
    resolved_source_shard_threshold_seconds = root._coerce_positive_float(source_shard_threshold_seconds) or root.ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
    resolved_source_shard_max_parts = root._coerce_positive_int(source_shard_max_parts) or root.ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
    resolved_source_shard_min_variants = root._coerce_positive_int(source_shard_min_variants) or root.ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
    timeout_display = f'{resolved_config_timeout_seconds}s' if resolved_config_timeout_seconds is not None else 'off'
    scheduler_mode = 'smart' if resolved_smart_scheduler else 'fixed'
    root.typer.secho(f'Scheduler: scope={resolved_scheduler_scope}, source parallel={source_parallelism_effective} (configured {source_parallelism_configured}, default {root._all_method_default_parallel_sources_from_cpu()}), source scheduling={resolved_source_scheduling}, source sharding threshold/max_parts/min_variants={resolved_source_shard_threshold_seconds:.1f}/{resolved_source_shard_max_parts}/{resolved_source_shard_min_variants}, mode={scheduler_mode}, configured inflight={resolved_inflight_pipelines} (default {root.ALL_METHOD_MAX_INFLIGHT_DEFAULT}), effective inflight={resolved_effective_inflight_pipelines}, split slots={resolved_split_phase_slots} (default {root.ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT}), eval headroom ({resolved_eval_tail_mode}) configured/effective={resolved_eval_tail_headroom_configured}/{resolved_eval_tail_headroom_effective}, max active during eval={resolved_max_active_during_eval}, cpu budget/source={resolved_cpu_budget_per_source}, config timeout={timeout_display} (default {root.ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT}s), failed retries={resolved_retry_failed_configs} (default {root.ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT}), wing backlog={resolved_wing_backlog_target} (default split slots)', fg=root.typer.colors.BRIGHT_BLACK)
    if scope_all_matched:
        proceed_prompt = f'Proceed with {total_selected_runs} benchmark runs across {len(targets)} matched golden sets?'
    else:
        proceed_prompt = f'Proceed with {total_selected_runs} benchmark runs?'
    proceed = root._prompt_confirm(proceed_prompt, default=False)
    if proceed is not True:
        root.typer.secho('All method benchmark cancelled.', fg=root.typer.colors.YELLOW)
        return
    all_method_root = benchmark_eval_output / 'all-method-benchmark'
    all_method_processed_root = processed_output_root / benchmark_eval_output.name / 'all-method-benchmark'
    all_method_canonical_cache_root = root._resolve_all_method_canonical_alignment_cache_root(root_output_dir=all_method_root)
    root.typer.secho(f'All method canonical alignment cache root: {all_method_canonical_cache_root}', fg=root.typer.colors.BRIGHT_BLACK)
    status_initial = 'Running all method benchmark...'
    status_prefix = 'All method benchmark'
    if scope_all_matched:
        dashboard = root._AllMethodProgressDashboard.from_target_variants(selected_target_variants)
        report_md_path = root._run_with_progress_status(initial_status=status_initial, progress_prefix=status_prefix, telemetry_path=all_method_root / root.PROCESSING_TIMESERIES_FILENAME, run=lambda update_progress: root._run_all_method_benchmark_multi_source(target_variants=selected_target_variants, unmatched_targets=unmatched_targets, include_codex_farm_requested=include_codex_requested, include_codex_farm_effective=include_codex_effective, root_output_dir=all_method_root, processed_output_root=all_method_processed_root, golden_root=resolved_golden_root, overlap_threshold=0.5, force_source_match=False, progress_callback=update_progress, dashboard=dashboard, max_parallel_sources=max_parallel_sources, max_inflight_pipelines=resolved_inflight_pipelines, max_concurrent_split_phases=resolved_split_phase_slots, max_eval_tail_pipelines=max_eval_tail_pipelines, config_timeout_seconds=resolved_config_timeout_seconds, retry_failed_configs=resolved_retry_failed_configs, source_scheduling=resolved_source_scheduling, source_shard_threshold_seconds=resolved_source_shard_threshold_seconds, source_shard_max_parts=resolved_source_shard_max_parts, source_shard_min_variants=resolved_source_shard_min_variants, wing_backlog_target=resolved_wing_backlog_target, smart_scheduler=resolved_smart_scheduler, scheduler_scope=resolved_scheduler_scope, canonical_alignment_cache_root=all_method_canonical_cache_root, dashboard_output_root=processed_output_root))
        root.typer.secho(f'All method benchmark summary report: {report_md_path}', fg=root.typer.colors.CYAN)
        root.typer.secho(f'All method processing telemetry: {all_method_root / root.PROCESSING_TIMESERIES_FILENAME}', fg=root.typer.colors.BRIGHT_BLACK)
    else:
        single_target = targets[0]
        single_variants = selected_target_variants[0][1]
        single_root = all_method_root / root.slugify_name(single_target.source_file.stem)
        single_processed_root = all_method_processed_root / root.slugify_name(single_target.source_file.stem)
        dashboard = root._AllMethodProgressDashboard.from_target_variants([(single_target, single_variants)])

        def _run_single_source(update_progress: root.Callable[[str], None]) -> root.Path:
            dashboard.start_source(0)
            dashboard.set_task(f'Running source 1/1: {single_target.source_file_name}')
            update_progress(dashboard.render())
            try:
                report_path = root._run_all_method_benchmark(gold_spans_path=single_target.gold_spans_path, source_file=single_target.source_file, variants=single_variants, include_codex_farm_requested=include_codex_requested, include_codex_farm_effective=include_codex_effective, root_output_dir=single_root, processed_output_root=single_processed_root, golden_root=resolved_golden_root, overlap_threshold=0.5, force_source_match=False, progress_callback=update_progress, dashboard=dashboard, dashboard_source_index=0, max_inflight_pipelines=resolved_inflight_pipelines, max_concurrent_split_phases=resolved_split_phase_slots, max_eval_tail_pipelines=max_eval_tail_pipelines, config_timeout_seconds=resolved_config_timeout_seconds, retry_failed_configs=resolved_retry_failed_configs, wing_backlog_target=resolved_wing_backlog_target, smart_scheduler=resolved_smart_scheduler, source_parallelism_effective=source_parallelism_effective, canonical_alignment_cache_dir_override=all_method_canonical_cache_root / root.slugify_name(single_target.source_file.stem), dashboard_output_root=processed_output_root)
            except Exception:
                dashboard.finish_source(0, failed=True)
                dashboard.set_task('Source failed.')
                update_progress(dashboard.render())
                raise
            dashboard.finish_source(0, failed=False)
            dashboard.set_task('Source complete.')
            update_progress(dashboard.render())
            return report_path
        report_md_path = root._run_with_progress_status(initial_status=status_initial, progress_prefix=status_prefix, telemetry_path=single_root / root.PROCESSING_TIMESERIES_FILENAME, run=_run_single_source)
        root.typer.secho(f'All method benchmark report: {report_md_path}', fg=root.typer.colors.CYAN)
        root.typer.secho(f'All method processing telemetry: {single_root / root.PROCESSING_TIMESERIES_FILENAME}', fg=root.typer.colors.BRIGHT_BLACK)
    root.typer.secho(f'All method processed outputs: {all_method_processed_root}', fg=root.typer.colors.CYAN)
