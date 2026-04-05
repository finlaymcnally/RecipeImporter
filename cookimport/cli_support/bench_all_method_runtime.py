from __future__ import annotations

import cookimport.cli_support.bench_all_method as root

def _run_all_method_benchmark_global_queue(*, target_variants: list[tuple[root.AllMethodTarget, list[root.AllMethodVariant]]], unmatched_targets: list[root.AllMethodUnmatchedGold], include_codex_farm_requested: bool, include_codex_farm_effective: bool, root_output_dir: root.Path, processed_output_root: root.Path, golden_root: root.Path, overlap_threshold: float, force_source_match: bool, progress_callback: root.Callable[[str], None] | None=None, dashboard: root._AllMethodProgressDashboard | None=None, max_parallel_sources: int | None=None, max_inflight_pipelines: int | None=None, max_concurrent_split_phases: int | None=None, max_eval_tail_pipelines: int | None=None, config_timeout_seconds: int | None=None, retry_failed_configs: int | None=None, source_scheduling: str | None=None, source_shard_threshold_seconds: float | None=None, source_shard_max_parts: int | None=None, source_shard_min_variants: int | None=None, wing_backlog_target: int | None=None, smart_scheduler: bool=False, canonical_alignment_cache_root: root.Path | None=None, prediction_reuse_cache_root: root.Path | None=None, dashboard_output_root: root.Path | None=None, require_process_workers: bool=False) -> root.Path:
    run_started = root.time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)
    effective_config_timeout_seconds = root._resolve_all_method_config_timeout_seconds(config_timeout_seconds)
    effective_retry_failed_configs = root._resolve_all_method_retry_failed_configs(retry_failed_configs)
    resolved_source_scheduling = root._normalize_all_method_source_scheduling(source_scheduling)
    resolved_source_shard_threshold_seconds = root._coerce_positive_float(source_shard_threshold_seconds) or root.ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
    resolved_source_shard_max_parts = root._coerce_positive_int(source_shard_max_parts) or root.ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
    resolved_source_shard_min_variants = root._coerce_positive_int(source_shard_min_variants) or root.ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
    resolved_canonical_cache_root = canonical_alignment_cache_root.expanduser() if canonical_alignment_cache_root is not None else root._resolve_all_method_canonical_alignment_cache_root(root_output_dir=root_output_dir)
    resolved_prediction_reuse_cache_root = prediction_reuse_cache_root.expanduser() if prediction_reuse_cache_root is not None else root._resolve_all_method_prediction_reuse_cache_dir(root_output_dir=root_output_dir)
    resolved_dashboard_output_root = dashboard_output_root.expanduser() if dashboard_output_root is not None else None
    total_targets = len(target_variants)
    source_job_plans = root._plan_all_method_source_jobs(target_variants=target_variants, scheduling_strategy=resolved_source_scheduling, shard_threshold_seconds=resolved_source_shard_threshold_seconds, shard_max_parts=resolved_source_shard_max_parts, shard_min_variants=resolved_source_shard_min_variants)
    work_items = root._plan_all_method_global_work_items(target_variants=target_variants, scheduling_strategy=resolved_source_scheduling, shard_threshold_seconds=resolved_source_shard_threshold_seconds, shard_max_parts=resolved_source_shard_max_parts, shard_min_variants=resolved_source_shard_min_variants, root_output_dir=root_output_dir, processed_output_root=processed_output_root, canonical_alignment_cache_root=resolved_canonical_cache_root)
    total_planned_config_runs = len(work_items)
    source_parallelism_default = min(root._all_method_default_parallel_sources_from_cpu(), max(1, total_targets))
    requested_source_parallelism = root._report_count(max_parallel_sources)
    source_parallelism_configured = requested_source_parallelism if requested_source_parallelism > 0 else source_parallelism_default
    source_parallelism_effective = root._resolve_all_method_source_parallelism(total_sources=max(1, total_targets), requested=max_parallel_sources)
    scheduler_runtime = root._resolve_all_method_scheduler_runtime(total_variants=max(1, total_planned_config_runs), max_inflight_pipelines=max_inflight_pipelines, max_concurrent_split_phases=max_concurrent_split_phases, max_eval_tail_pipelines=max_eval_tail_pipelines, wing_backlog_target=wing_backlog_target, smart_scheduler=smart_scheduler, source_parallelism_effective=1)
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
    split_worker_cap_per_config, split_worker_guard = root._resolve_all_method_split_worker_cap(split_phase_slots=effective_split_phase_slots, source_parallelism_effective=1)
    max_requested_split_workers = max([max(max(1, root._report_count(item.variant.run_settings.workers)), max(1, root._report_count(item.variant.run_settings.pdf_split_workers)), max(1, root._report_count(item.variant.run_settings.epub_split_workers))) for item in work_items], default=1)
    split_phase_gate_dir = root_output_dir / '.split_phase_slots'
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    scheduler_events_dir = root_output_dir / '.scheduler_events'
    scheduler_timeseries_path = root_output_dir / root.ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    if scheduler_events_dir.exists():
        root.shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    if scheduler_timeseries_path.exists():
        scheduler_timeseries_path.unlink()
    status_lock = root.threading.RLock()
    source_totals: dict[int, int] = {source_position: len(variants) for source_position, (_target, variants) in enumerate(target_variants)}
    source_active: dict[int, int] = root.defaultdict(int)
    source_completed: dict[int, int] = root.defaultdict(int)
    source_failed_seen: dict[int, bool] = root.defaultdict(bool)

    def _emit_status(message: str, *, color: root.typer.colors=root.typer.colors.CYAN) -> None:
        cleaned = str(message or '').strip()
        if not cleaned:
            return
        with status_lock:
            if progress_callback is not None:
                if dashboard is not None:
                    dashboard.set_task(cleaned)
                    root._notify_progress_callback(progress_callback, dashboard.render())
                else:
                    root._notify_progress_callback(progress_callback, cleaned)
                return
            root.typer.secho(cleaned, fg=color)
    if split_phase_slot_mode != 'configured':
        _emit_status(f'Resource guard capped split slots to {effective_split_phase_slots} (requested {requested_split_phase_slots}; cpu cap {split_phase_slot_cap_by_cpu}; memory cap {split_phase_slot_cap_by_memory}).', color=root.typer.colors.YELLOW)
    if split_worker_cap_per_config < max_requested_split_workers:
        _emit_status(f'Resource guard capped split workers per active config to {split_worker_cap_per_config} (requested peak {max_requested_split_workers}; split slots {effective_split_phase_slots}).', color=root.typer.colors.YELLOW)
    scheduler_phase_by_config: dict[int, str] = {}
    scheduler_event_offsets: dict[int, int] = {}
    scheduler_last_tick = root.time.monotonic()
    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_last_snapshot = ''
    scheduler_timeseries_last_snapshot = ''
    scheduler_timeseries_last_write_monotonic = run_started
    scheduler_timeseries_rows_written = 0
    scheduler_timeseries_heartbeat_seconds = max(root.ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS, root.ALL_METHOD_SCHEDULER_POLL_SECONDS)
    scheduler_cpu_source = 'proc_stat_linux'
    scheduler_cpu_samples_collected = 0
    scheduler_cpu_totals_last: tuple[int, int] | None = None
    scheduler_cpu_utilization_pct_last: float | None = None
    scheduler_cpu_utilization_pct_high_water = 0.0
    scheduler_admission_adjustments = 0
    scheduler_admission_pressure_boosts = 0
    scheduler_admission_saturation_clamps = 0
    scheduler_admission_cpu_hot_clamps = 0
    scheduler_admission_active_cap_peak = configured_inflight_pipelines
    scheduler_admission_guard_target_peak = min(max(1, total_planned_config_runs), max(1, effective_split_phase_slots + effective_wing_backlog_target))
    scheduler_admission_last_key: tuple[int, int, str] | None = None
    scheduler_admission_active_cap_current = configured_inflight_pipelines
    scheduler_admission_guard_target_current = min(max(1, total_planned_config_runs), max(1, effective_split_phase_slots + effective_wing_backlog_target))
    scheduler_admission_wing_target_current = effective_wing_backlog_target
    scheduler_admission_reason_current = 'base'
    process_worker_probe_available: bool | None = None
    process_worker_probe_error: str | None = None
    config_executor_backends_seen: set[str] = set()

    def _scheduler_event_path(config_index: int) -> root.Path:
        return scheduler_events_dir / f'config_{config_index:03d}.jsonl'

    def _read_linux_cpu_totals() -> tuple[int, int] | None:
        try:
            with root.Path('/proc/stat').open('r', encoding='utf-8') as handle:
                first_line = handle.readline()
        except OSError:
            return None
        line = str(first_line or '').strip()
        if not line:
            return None
        parts = line.split()
        if not parts or parts[0] != 'cpu':
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
        return (total, idle)

    def _sample_host_cpu_utilization_pct() -> float | None:
        nonlocal scheduler_cpu_source
        nonlocal scheduler_cpu_samples_collected
        nonlocal scheduler_cpu_totals_last
        current = _read_linux_cpu_totals()
        if current is None:
            scheduler_cpu_source = 'unavailable'
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
        return max(0.0, min(100.0, float(busy_delta) / float(total_delta) * 100.0))

    def _scheduler_phase_for_event(event_name: str) -> str | None:
        event = str(event_name or '').strip()
        if event in {'config_started', 'prep_started'}:
            return 'prep'
        if event == 'split_wait_started':
            return 'split_wait'
        if event == 'split_active_started':
            return 'split_active'
        if event in {'split_active_finished', 'post_started'}:
            return 'post'
        if event in {'post_finished', 'evaluate_started'}:
            return 'evaluate'
        if event in {'evaluate_finished', 'config_finished'}:
            return 'done'
        return None

    def _poll_scheduler_events(active_indices: set[int]) -> None:
        for active_index in sorted(active_indices):
            event_path = _scheduler_event_path(active_index)
            if not event_path.exists():
                continue
            offset = max(0, scheduler_event_offsets.get(active_index, 0))
            with event_path.open('r', encoding='utf-8') as handle:
                handle.seek(offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = root.json.loads(line)
                    except root.json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    phase = _scheduler_phase_for_event(str(payload.get('event') or ''))
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
            phase = scheduler_phase_by_config.get(active_index, 'prep')
            if phase == 'split_active':
                heavy_active += 1
            elif phase == 'split_wait':
                split_wait += 1
            elif phase == 'post':
                post_active += 1
            elif phase == 'evaluate':
                evaluate_active += 1
            elif phase == 'done':
                continue
            else:
                prep_active += 1
        wing_backlog = split_wait + prep_active
        return {'heavy_active': heavy_active, 'split_wait': split_wait, 'prep_active': prep_active, 'post_active': post_active, 'evaluate_active': evaluate_active, 'wing_backlog': wing_backlog, 'active': len(active_indices)}

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
        now = root.time.monotonic()
        delta = max(0.0, now - scheduler_last_tick)
        counts = _compute_scheduler_counts(active_indices)
        scheduler_capacity_seconds += float(effective_split_phase_slots) * delta
        scheduler_busy_seconds += float(min(effective_split_phase_slots, counts['heavy_active'])) * delta
        if pending_count > 0 and counts['heavy_active'] < effective_split_phase_slots:
            scheduler_idle_gap_seconds += delta
        scheduler_wing_area_seconds += float(counts['wing_backlog']) * delta
        scheduler_max_wing_backlog = max(scheduler_max_wing_backlog, counts['wing_backlog'])
        scheduler_max_active_pipelines = max(scheduler_max_active_pipelines, counts['active'])
        scheduler_max_eval_active = max(scheduler_max_eval_active, counts['evaluate_active'])
        sampled_cpu = _sample_host_cpu_utilization_pct()
        if sampled_cpu is not None:
            scheduler_cpu_utilization_pct_last = sampled_cpu
            scheduler_cpu_utilization_pct_high_water = max(scheduler_cpu_utilization_pct_high_water, sampled_cpu)
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return f'scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} | wing {counts['wing_backlog']} | eval {counts['evaluate_active']} | active {counts['active']} | pending {max(0, pending_count)}'

    def _write_scheduler_timeseries_row(*, counts: dict[str, int], pending_count: int, force: bool=False) -> None:
        nonlocal scheduler_timeseries_last_snapshot
        nonlocal scheduler_timeseries_last_write_monotonic
        nonlocal scheduler_timeseries_rows_written
        pending_safe = max(0, pending_count)
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_safe)
        now_monotonic = root.time.monotonic()
        write_due = force or snapshot != scheduler_timeseries_last_snapshot or now_monotonic - scheduler_timeseries_last_write_monotonic >= scheduler_timeseries_heartbeat_seconds
        if not write_due:
            return
        row = {'timestamp': root.dt.datetime.now(tz=root.dt.timezone.utc).isoformat(timespec='milliseconds'), 'monotonic_seconds': now_monotonic, 'elapsed_seconds': max(0.0, now_monotonic - run_started), 'snapshot': snapshot, 'heavy_active': root._report_count(counts.get('heavy_active')), 'heavy_capacity': root._report_count(effective_split_phase_slots), 'split_wait': root._report_count(counts.get('split_wait')), 'prep_active': root._report_count(counts.get('prep_active')), 'post_active': root._report_count(counts.get('post_active')), 'evaluate_active': root._report_count(counts.get('evaluate_active')), 'wing_backlog': root._report_count(counts.get('wing_backlog')), 'active': root._report_count(counts.get('active')), 'pending': pending_safe, 'cpu_utilization_pct': scheduler_cpu_utilization_pct_last, 'admission_active_cap': scheduler_admission_active_cap_current, 'admission_guard_target': scheduler_admission_guard_target_current, 'admission_wing_target': scheduler_admission_wing_target_current, 'admission_reason': scheduler_admission_reason_current}
        try:
            with scheduler_timeseries_path.open('a', encoding='utf-8') as handle:
                handle.write(root.json.dumps(row, sort_keys=True) + '\n')
        except Exception:
            return
        scheduler_timeseries_last_snapshot = snapshot
        scheduler_timeseries_last_write_monotonic = now_monotonic
        scheduler_timeseries_rows_written += 1

    def _emit_scheduler_snapshot(*, counts: dict[str, int], pending_count: int, force_timeseries: bool=False) -> None:
        nonlocal scheduler_last_snapshot
        _write_scheduler_timeseries_row(counts=counts, pending_count=pending_count, force=force_timeseries)
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(counts=counts, pending_count=max(0, pending_count))
        if snapshot == scheduler_last_snapshot:
            return
        scheduler_last_snapshot = snapshot
        _emit_status(snapshot, color=root.typer.colors.BRIGHT_BLACK)
    item_by_global_index: dict[int, root._AllMethodGlobalWorkItem] = {item.global_dispatch_index: item for item in work_items}
    variant_rows: list[dict[str, root.Any]] = []

    def _annotate_prediction_row(*, item: root._AllMethodGlobalWorkItem, row: dict[str, root.Any]) -> dict[str, root.Any]:
        payload = dict(row)
        payload['global_dispatch_index'] = item.global_dispatch_index
        payload['source_position'] = item.source_position
        payload['source_group_key'] = item.source_group_key
        payload['source_slug'] = item.source_group_key
        payload['source_file'] = str(item.source_file)
        payload['source_file_name'] = item.source_file_name
        payload['gold_spans_path'] = str(item.gold_spans_path)
        payload['source_config_index'] = item.config_index
        payload['source_config_total'] = item.config_total
        payload['source_shard_index'] = item.source_shard_index + 1
        payload['source_shard_total'] = max(1, root._report_count(item.source_shard_total))
        payload['source_estimated_seconds'] = item.source_estimated_seconds
        payload['source_estimate_basis'] = item.source_estimate_basis
        payload['_source_root'] = str(item.source_root)
        payload['_source_processed_root'] = str(item.source_processed_root)
        payload['_canonical_alignment_cache_dir'] = str(item.canonical_alignment_cache_dir)
        return payload

    def _latest_rows_by_dispatch(rows: list[dict[str, root.Any]]) -> list[dict[str, root.Any]]:
        latest_by_index: dict[int, dict[str, root.Any]] = {}
        for row in rows:
            dispatch_index = root._report_count(row.get('global_dispatch_index', row.get('config_index')))
            latest_by_index[dispatch_index] = row
        return [latest_by_index[index] for index in sorted(latest_by_index)]

    def _mark_item_started(item: root._AllMethodGlobalWorkItem, *, dashboard_tracking: bool) -> None:
        if not dashboard_tracking or dashboard is None:
            return
        source_position = item.source_position
        if source_active[source_position] <= 0:
            dashboard.start_source(source_position)
        source_active[source_position] += 1
        dashboard.start_config(source_index=source_position, config_index=item.config_index, config_total=max(1, item.config_total), config_slug=item.variant.slug)

    def _mark_item_finished(item: root._AllMethodGlobalWorkItem, *, success: bool, dashboard_tracking: bool) -> None:
        source_position = item.source_position
        source_active[source_position] = max(0, source_active[source_position] - 1)
        source_completed[source_position] += 1
        if not success:
            source_failed_seen[source_position] = True
        if not dashboard_tracking or dashboard is None:
            return
        dashboard.complete_config(source_index=source_position, success=success, config_index=item.config_index)
        expected_total = max(0, root._report_count(source_totals.get(source_position)))
        if expected_total > 0 and source_active[source_position] == 0 and (source_completed[source_position] >= expected_total):
            dashboard.finish_source(source_position, failed=bool(source_failed_seen[source_position]))

    def _run_serial_items(items: list[root._AllMethodGlobalWorkItem], *, dashboard_tracking: bool=True) -> None:
        for item in items:
            progress_label = root.format_task_counter('Running', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')
            _mark_item_started(item, dashboard_tracking=dashboard_tracking)
            _emit_status(f'{progress_label}: {item.variant.slug} [{item.source_file_name}]', color=root.typer.colors.CYAN)

            def _variant_progress(message: str) -> None:
                if progress_callback is None:
                    return
                if dashboard is None:
                    if root._is_structured_progress_message(message):
                        root._notify_progress_callback(progress_callback, message)
                        return
                    root._notify_progress_callback(progress_callback, f'{progress_label}: {item.variant.slug} [{item.source_file_name}] | {message}')
                    return
                if root._is_structured_progress_message(message):
                    root._notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                root._notify_progress_callback(progress_callback, dashboard.render())
            row = root._run_all_method_prediction_once(gold_spans_path=item.gold_spans_path, source_file=item.source_file, variant=item.variant, config_index=item.global_dispatch_index, total_variants=max(1, total_planned_config_runs), root_output_dir=item.source_root, scratch_root=item.source_root / '.scratch', processed_output_root=item.source_processed_root, overlap_threshold=overlap_threshold, force_source_match=force_source_match, max_concurrent_split_phases=effective_split_phase_slots, split_phase_gate_dir=split_phase_gate_dir, scheduler_events_dir=scheduler_events_dir, alignment_cache_dir=item.canonical_alignment_cache_dir, prediction_reuse_cache_dir=resolved_prediction_reuse_cache_root, split_worker_cap_per_config=split_worker_cap_per_config, progress_callback=_variant_progress if progress_callback else None)
            row = _annotate_prediction_row(item=item, row=row)
            variant_rows.append(row)
            success = str(row.get('status') or '').strip().lower() == 'ok'
            _mark_item_finished(item, success=success, dashboard_tracking=dashboard_tracking)
            if success:
                if progress_callback is not None:
                    _emit_status(f'Completed {root.format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: {item.variant.slug} [{item.source_file_name}]')
            else:
                _emit_status(f'Failed {root.format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: {row.get('error', 'unknown error')}', color=root.typer.colors.RED)

    def _run_parallel_items(items: list[root._AllMethodGlobalWorkItem], *, dashboard_tracking: bool=True) -> None:
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
        serial_by_limits = (len(items) <= 1 or effective_inflight_pipelines <= 1) and (not force_parallel_timeout)
        if serial_by_limits:
            config_executor_backends_seen.add('serial')
            _run_serial_items(items, dashboard_tracking=dashboard_tracking)
            return
        executor_backend = 'process'
        process_workers_available, process_worker_error = root._probe_all_method_process_pool_executor()
        if process_workers_available:
            picklable, picklable_error = root._probe_all_method_process_worker_picklable()
            if not picklable:
                process_workers_available = False
                process_worker_error = picklable_error
        process_worker_probe_available = bool(process_workers_available)
        process_worker_probe_error = str(process_worker_error).strip() if process_worker_error else None
        if not process_workers_available:
            detail = f' ({process_worker_error})' if isinstance(process_worker_error, str) and process_worker_error else ''
            if require_process_workers:
                raise RuntimeError(f'Process-based config concurrency is required, but runtime probe reported it unavailable{detail}.')
            _emit_status(f'Process-based config concurrency unavailable{detail}; using thread-based config concurrency.', color=root.typer.colors.YELLOW)
            executor_backend = 'thread'
        config_executor_backends_seen.add(str(executor_backend))
        pending_items = list(items)
        futures: dict[root.Any, tuple[root._AllMethodGlobalWorkItem, float]] = {}
        worker_limit = min(effective_inflight_pipelines, max(1, len(items)))
        scheduler_base_target = min(max(1, total_planned_config_runs), effective_split_phase_slots + effective_wing_backlog_target)
        scheduler_smart_enabled = bool(effective_smart_scheduler)
        try:
            executor = root._create_all_method_process_pool_executor(max_workers=worker_limit) if executor_backend == 'process' else root.ThreadPoolExecutor(max_workers=worker_limit)
        except (PermissionError, OSError) as exc:
            if executor_backend == 'process':
                if require_process_workers:
                    raise RuntimeError(f'Process-based config concurrency is required, but process executor startup failed: {exc}') from exc
                _emit_status(f'Process-based config concurrency unavailable ({exc}); using thread-based config concurrency.', color=root.typer.colors.YELLOW)
                executor_backend = 'thread'
                config_executor_backends_seen.add('thread')
                try:
                    executor = root.ThreadPoolExecutor(max_workers=worker_limit)
                except Exception as thread_exc:
                    _emit_status(f'Thread-based config concurrency unavailable ({thread_exc}); running single-config execution.', color=root.typer.colors.YELLOW)
                    config_executor_backends_seen.add('serial')
                    _run_serial_items(items, dashboard_tracking=dashboard_tracking)
                    return
            else:
                _emit_status(f'Thread-based config concurrency unavailable ({exc}); running single-config execution.', color=root.typer.colors.YELLOW)
                config_executor_backends_seen.add('serial')
                _run_serial_items(items, dashboard_tracking=dashboard_tracking)
                return

        def _record_completion(*, item: root._AllMethodGlobalWorkItem, row: dict[str, root.Any]) -> None:
            variant_rows.append(row)
            success = str(row.get('status') or '').strip().lower() == 'ok'
            scheduler_phase_by_config.pop(item.global_dispatch_index, None)
            scheduler_event_offsets.pop(item.global_dispatch_index, None)
            _mark_item_finished(item, success=success, dashboard_tracking=dashboard_tracking)
            if success:
                if progress_callback is not None:
                    _emit_status(f'Completed {root.format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: {item.variant.slug} [{item.source_file_name}]')
            else:
                _emit_status(f'Failed {root.format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: {row.get('error', 'unknown error')}', color=root.typer.colors.RED)

        def _submit_next() -> bool:
            if not pending_items:
                return False
            item = pending_items.pop(0)
            progress_label = root.format_task_counter('Running', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')
            _mark_item_started(item, dashboard_tracking=dashboard_tracking)
            _emit_status(f'{progress_label}: {item.variant.slug} [{item.source_file_name}]', color=root.typer.colors.CYAN)
            try:
                future = executor.submit(root._run_all_method_prediction_once, gold_spans_path=item.gold_spans_path, source_file=item.source_file, variant=item.variant, config_index=item.global_dispatch_index, total_variants=max(1, total_planned_config_runs), root_output_dir=item.source_root, scratch_root=item.source_root / '.scratch', processed_output_root=item.source_processed_root, overlap_threshold=overlap_threshold, force_source_match=force_source_match, max_concurrent_split_phases=effective_split_phase_slots, split_phase_gate_dir=split_phase_gate_dir, scheduler_events_dir=scheduler_events_dir, alignment_cache_dir=item.canonical_alignment_cache_dir, prediction_reuse_cache_dir=resolved_prediction_reuse_cache_root, split_worker_cap_per_config=split_worker_cap_per_config, progress_callback=None)
            except Exception as exc:
                row = root._all_method_failed_row(config_index=item.global_dispatch_index, config_dir_name=root._all_method_config_dir_name(item.global_dispatch_index, item.variant), variant=item.variant, error=f'Failed to submit benchmark config: {exc}')
                _record_completion(item=item, row=_annotate_prediction_row(item=item, row=row))
                return True
            futures[future] = (item, root.time.monotonic())
            scheduler_phase_by_config[item.global_dispatch_index] = 'prep'
            scheduler_event_offsets[item.global_dispatch_index] = 0
            return True

        def _refresh_admission_decision(*, counts: dict[str, int], pending_count: int) -> root._AllMethodSchedulerAdmissionDecision:
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
            decision = root._resolve_all_method_scheduler_admission(counts=counts, pending_count=pending_count, total_variants=max(1, total_planned_config_runs), configured_inflight_pipelines=configured_inflight_pipelines, split_phase_slots=effective_split_phase_slots, wing_backlog_target=effective_wing_backlog_target, max_active_during_eval=max_active_during_eval, adaptive_overcommit_limit=adaptive_overcommit_limit, adaptive_max_guard_target=max(scheduler_base_target, adaptive_max_guard_target), smart_scheduler_enabled=scheduler_smart_enabled, cpu_utilization_pct=scheduler_cpu_utilization_pct_last)
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
            scheduler_admission_active_cap_peak = max(scheduler_admission_active_cap_peak, decision.active_cap)
            scheduler_admission_guard_target_peak = max(scheduler_admission_guard_target_peak, decision.guard_target)
            scheduler_admission_active_cap_current = decision.active_cap
            scheduler_admission_guard_target_current = decision.guard_target
            scheduler_admission_wing_target_current = decision.wing_target
            scheduler_admission_reason_current = decision.reason
            return decision
        try:
            while pending_items or futures:
                active_indices = {item.global_dispatch_index for item, _submitted in futures.values()}
                counts = _tick_scheduler_metrics(active_indices=active_indices, pending_count=len(pending_items))
                if active_indices:
                    try:
                        _poll_scheduler_events(active_indices)
                    except Exception:
                        scheduler_smart_enabled = False
                counts = _compute_scheduler_counts({item.global_dispatch_index for item, _submitted in futures.values()})
                if dashboard_tracking and dashboard is not None:
                    for active_item, _submitted in futures.values():
                        dashboard.set_config_phase(source_index=active_item.source_position, config_index=active_item.config_index, phase=scheduler_phase_by_config.get(active_item.global_dispatch_index, 'prep'))
                admission_decision = _refresh_admission_decision(counts=counts, pending_count=len(pending_items))
                _emit_scheduler_snapshot(counts=counts, pending_count=len(pending_items))
                while len(futures) < worker_limit and pending_items:
                    heavy_plus_wing = counts['heavy_active'] + counts['wing_backlog']
                    if counts['active'] >= admission_decision.active_cap:
                        break
                    if heavy_plus_wing >= admission_decision.guard_target and counts['active'] >= configured_inflight_pipelines:
                        break
                    submitted = _submit_next()
                    if not submitted:
                        break
                    counts = _compute_scheduler_counts({item.global_dispatch_index for item, _submitted in futures.values()})
                    admission_decision = _refresh_admission_decision(counts=counts, pending_count=len(pending_items))
                    _emit_scheduler_snapshot(counts=counts, pending_count=len(pending_items))
                if not futures:
                    if pending_items:
                        root.time.sleep(root.ALL_METHOD_SCHEDULER_POLL_SECONDS)
                    continue
                done, _ = root.wait(list(futures.keys()), timeout=root.ALL_METHOD_SCHEDULER_POLL_SECONDS, return_when=root.FIRST_COMPLETED)
                for done_future in done:
                    item, _submitted = futures.pop(done_future)
                    try:
                        row = done_future.result()
                    except Exception as exc:
                        row = root._all_method_failed_row(config_index=item.global_dispatch_index, config_dir_name=root._all_method_config_dir_name(item.global_dispatch_index, item.variant), variant=item.variant, error=f'Benchmark config worker failed: {exc}')
                    _record_completion(item=item, row=_annotate_prediction_row(item=item, row=row))
                if effective_config_timeout_seconds is None or executor_backend != 'process':
                    continue
                timeout_threshold = float(max(1, effective_config_timeout_seconds))
                now = root.time.monotonic()
                timed_out: list[tuple[root.Any, root._AllMethodGlobalWorkItem, float]] = []
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
                    row = root._all_method_failed_row(config_index=item.global_dispatch_index, config_dir_name=root._all_method_config_dir_name(item.global_dispatch_index, item.variant), variant=item.variant, error=f'Config timed out after {int(timeout_threshold)}s (elapsed {elapsed_seconds:.1f}s).', elapsed_seconds=elapsed_seconds)
                    _record_completion(item=item, row=_annotate_prediction_row(item=item, row=row))
                if futures:
                    requeued = sorted([item for item, _submitted in futures.values()], key=lambda item: item.global_dispatch_index)
                    pending_items = requeued + pending_items
                    futures.clear()
                scheduler_smart_enabled = False
                _emit_status(f'Config timeout reached for {len(timed_out)} run(s); restarting process worker pool.', color=root.typer.colors.YELLOW)
                shutdown_fn = getattr(executor, 'shutdown', None)
                if callable(shutdown_fn):
                    try:
                        shutdown_fn(wait=False, cancel_futures=True)
                    except TypeError:
                        shutdown_fn(wait=False)
                try:
                    executor = root._create_all_method_process_pool_executor(max_workers=worker_limit)
                except (PermissionError, OSError) as exc:
                    if require_process_workers:
                        raise RuntimeError(f'Process-based config concurrency is required, but process pool restart failed after timeout: {exc}') from exc
                    _emit_status(f'Process-based config concurrency unavailable after timeout restart ({exc}); using thread-based config concurrency for remaining configs.', color=root.typer.colors.YELLOW)
                    executor_backend = 'thread'
                    config_executor_backends_seen.add('thread')
                    try:
                        executor = root.ThreadPoolExecutor(max_workers=worker_limit)
                    except Exception as thread_exc:
                        _emit_status(f'Thread-based config concurrency unavailable ({thread_exc}); running remaining configs as single-config execution.', color=root.typer.colors.YELLOW)
                        config_executor_backends_seen.add('serial')
                        _run_serial_items(pending_items, dashboard_tracking=dashboard_tracking)
                        pending_items.clear()
                        futures.clear()
                        break
        finally:
            shutdown_fn = getattr(executor, 'shutdown', None)
            if callable(shutdown_fn):
                try:
                    shutdown_fn(wait=True, cancel_futures=False)
                except TypeError:
                    shutdown_fn(wait=True)
    _run_parallel_items(work_items, dashboard_tracking=True)
    variant_rows = _latest_rows_by_dispatch(variant_rows)
    initial_failed_indices = [root._report_count(row.get('global_dispatch_index', row.get('config_index'))) for row in variant_rows if str(row.get('status') or '').strip().lower() != 'ok']
    retry_passes_executed = 0
    retry_recovered_configs = 0
    if effective_retry_failed_configs > 0 and initial_failed_indices:
        remaining_failed_indices = sorted(set(initial_failed_indices))
        for retry_pass in range(1, effective_retry_failed_configs + 1):
            if not remaining_failed_indices:
                break
            retry_items = [item_by_global_index[index] for index in remaining_failed_indices if index in item_by_global_index]
            if not retry_items:
                break
            retry_passes_executed += 1
            _emit_status(f'Retry pass {retry_pass}/{effective_retry_failed_configs}: rerunning {len(retry_items)} failed config(s).', color=root.typer.colors.YELLOW)
            prior_failed = set(remaining_failed_indices)
            _run_parallel_items(retry_items, dashboard_tracking=False)
            variant_rows = _latest_rows_by_dispatch(variant_rows)
            remaining_failed_indices = sorted({root._report_count(row.get('global_dispatch_index', row.get('config_index'))) for row in variant_rows if str(row.get('status') or '').strip().lower() != 'ok'})
            recovered_this_pass = len(prior_failed - set(remaining_failed_indices))
            retry_recovered_configs += max(0, recovered_this_pass)
            if recovered_this_pass > 0:
                _emit_status(f'Retry pass {retry_pass} recovered {recovered_this_pass} config(s).', color=root.typer.colors.CYAN)
    _tick_scheduler_metrics(active_indices=set(), pending_count=0)
    _emit_scheduler_snapshot(counts=_compute_scheduler_counts(set()), pending_count=0, force_timeseries=True)
    scheduler_utilization_pct = scheduler_busy_seconds / scheduler_capacity_seconds * 100.0 if scheduler_capacity_seconds > 0 else 0.0
    scheduler_avg_wing_backlog = scheduler_wing_area_seconds / scheduler_capacity_seconds if scheduler_capacity_seconds > 0 else 0.0
    scheduler_summary: dict[str, root.Any] = {'mode': 'smart' if bool(effective_smart_scheduler) else 'fixed', 'source_count': max(1, total_targets), 'configured_inflight_pipelines': configured_inflight_pipelines, 'effective_inflight_pipelines': effective_inflight_pipelines, 'split_phase_slots_requested': requested_split_phase_slots, 'split_phase_slots': effective_split_phase_slots, 'split_phase_slot_mode': split_phase_slot_mode, 'split_phase_slot_cap_by_cpu': split_phase_slot_cap_by_cpu, 'split_phase_slot_cap_by_memory': split_phase_slot_cap_by_memory, 'wing_backlog_target': effective_wing_backlog_target, 'split_worker_cap_per_config': split_worker_cap_per_config, 'split_worker_cap_by_cpu': split_worker_guard.get('split_worker_cap_by_cpu'), 'split_worker_cap_by_memory': split_worker_guard.get('split_worker_cap_by_memory'), 'eval_tail_headroom_mode': eval_tail_headroom_mode, 'eval_tail_headroom_configured': configured_eval_tail_headroom, 'eval_tail_headroom_effective': effective_eval_tail_headroom, 'max_active_during_eval': max_active_during_eval, 'adaptive_overcommit_limit': adaptive_overcommit_limit, 'adaptive_max_guard_target': adaptive_max_guard_target, 'source_parallelism_effective': 1, 'cpu_budget_per_source': scheduler_cpu_budget_per_source, 'cpu_budget_total': scheduler_cpu_budget_total, 'max_eval_tail_pipelines': effective_eval_tail_headroom, 'smart_tail_buffer_slots': effective_eval_tail_headroom if bool(effective_smart_scheduler) else 0, 'smart_scheduler_enabled': bool(effective_smart_scheduler), 'config_timeout_seconds': effective_config_timeout_seconds, 'failed_retry_limit': effective_retry_failed_configs, 'retry_passes_executed': retry_passes_executed, 'retry_recovered_configs': retry_recovered_configs, 'heavy_slot_capacity_seconds': scheduler_capacity_seconds, 'heavy_slot_busy_seconds': scheduler_busy_seconds, 'heavy_slot_utilization_pct': scheduler_utilization_pct, 'avg_wing_backlog': scheduler_avg_wing_backlog, 'max_wing_backlog': scheduler_max_wing_backlog, 'idle_gap_seconds': scheduler_idle_gap_seconds, 'max_active_pipelines_observed': scheduler_max_active_pipelines, 'max_eval_active_observed': scheduler_max_eval_active, 'adaptive_admission_adjustments': scheduler_admission_adjustments, 'adaptive_admission_pressure_boosts': scheduler_admission_pressure_boosts, 'adaptive_admission_saturation_clamps': scheduler_admission_saturation_clamps, 'adaptive_admission_cpu_hot_clamps': scheduler_admission_cpu_hot_clamps, 'adaptive_admission_active_cap_peak': scheduler_admission_active_cap_peak, 'adaptive_admission_guard_target_peak': scheduler_admission_guard_target_peak, 'timeseries_path': str(scheduler_timeseries_path), 'timeseries_row_count': scheduler_timeseries_rows_written, 'timeseries_heartbeat_seconds': scheduler_timeseries_heartbeat_seconds, 'snapshot_poll_seconds': root.ALL_METHOD_SCHEDULER_POLL_SECONDS, 'cpu_utilization_source': scheduler_cpu_source, 'cpu_utilization_samples': scheduler_cpu_samples_collected, 'cpu_utilization_pct_high_water': scheduler_cpu_utilization_pct_high_water, 'scheduler_scope': 'global_config_queue'}
    variant_rows = _latest_rows_by_dispatch(variant_rows)
    prediction_success_rows = [dict(row) for row in variant_rows if str(row.get('status') or '').strip().lower() == 'ok']
    failed_rows: list[dict[str, root.Any]] = [dict(row) for row in variant_rows if str(row.get('status') or '').strip().lower() != 'ok']
    successful_rows: list[dict[str, root.Any]] = []
    signature_candidate_rows: list[dict[str, root.Any]] = []
    evaluation_signatures_unique = 0
    evaluation_runs_executed = 0
    evaluation_results_reused_in_run = 0
    evaluation_results_reused_cross_run = 0
    eval_signature_cache_dir = root._resolve_all_method_eval_signature_cache_dir(root_output_dir=root_output_dir, alignment_cache_dir=resolved_canonical_cache_root / '__global__')
    for row in prediction_success_rows:
        source_root_raw = str(row.get('_source_root') or '').strip()
        if not source_root_raw:
            failed_row = dict(row)
            failed_row['status'] = 'failed'
            failed_row['error'] = 'Source root is missing for signature build.'
            failed_row['evaluation_result_source'] = 'failed'
            failed_rows.append(failed_row)
            continue
        prediction_record_path = root._resolve_all_method_prediction_record_path(root_output_dir=root.Path(source_root_raw), row=row)
        if prediction_record_path is None or not prediction_record_path.exists() or (not prediction_record_path.is_file()):
            failed_row = dict(row)
            failed_row['status'] = 'failed'
            failed_row['error'] = 'Prediction record path is missing for signature build.'
            failed_row['evaluation_result_source'] = 'failed'
            failed_rows.append(failed_row)
            continue
        sequence_matcher = str(row.get('benchmark_sequence_matcher') or '').strip() or 'dmp'
        gold_spans_path = root.Path(str(row.get('gold_spans_path') or '').strip())
        try:
            eval_signature = root._build_all_method_eval_signature(gold_spans_path=gold_spans_path, prediction_record_path=prediction_record_path, eval_mode=root.BENCHMARK_EVAL_MODE_CANONICAL_TEXT, sequence_matcher=sequence_matcher)
        except Exception as exc:
            failed_row = dict(row)
            failed_row['status'] = 'failed'
            failed_row['error'] = f'Failed to build evaluation signature: {exc}'
            failed_row['evaluation_result_source'] = 'failed'
            failed_rows.append(failed_row)
            continue
        row['eval_signature'] = eval_signature
        row['benchmark_sequence_matcher'] = sequence_matcher
        signature_candidate_rows.append(row)
    grouped_by_signature = root._group_all_method_rows_by_eval_signature(signature_candidate_rows)
    evaluation_signatures_unique = len(grouped_by_signature)
    grouped_items = sorted(grouped_by_signature.items(), key=lambda item: min((root._report_count(row.get('global_dispatch_index', row.get('config_index'))) for row in item[1])))
    for signature_index, (eval_signature, group_rows) in enumerate(grouped_items, start=1):
        if not group_rows:
            continue
        ordered_group = sorted(group_rows, key=lambda row: root._report_count(row.get('global_dispatch_index', row.get('config_index'))))
        representative_row = ordered_group[0]
        representative_config_dir = str(representative_row.get('config_dir') or '').strip()
        if not representative_config_dir:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row['status'] = 'failed'
                failed_row['error'] = 'Representative config directory is missing.'
                failed_row['evaluation_result_source'] = 'failed'
                failed_rows.append(failed_row)
            continue
        source_root = root.Path(str(representative_row.get('_source_root') or ''))
        source_processed_root = root.Path(str(representative_row.get('_source_processed_root') or ''))
        canonical_alignment_cache_dir = root.Path(str(representative_row.get('_canonical_alignment_cache_dir') or ''))
        representative_eval_output_dir = source_root / representative_config_dir
        representative_processed_output_dir = source_processed_root / representative_config_dir
        representative_prediction_record = root._resolve_all_method_prediction_record_path(root_output_dir=source_root, row=representative_row)
        if representative_prediction_record is None:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row['status'] = 'failed'
                failed_row['error'] = 'Representative prediction record is missing.'
                failed_row['evaluation_result_source'] = 'failed'
                failed_rows.append(failed_row)
            continue
        sequence_matcher = str(representative_row.get('benchmark_sequence_matcher') or '').strip()
        if not sequence_matcher:
            sequence_matcher = 'dmp'
        cache_path = eval_signature_cache_dir / f'{eval_signature}.json'
        cache_entry = root._load_all_method_eval_signature_cache_entry(cache_path=cache_path, expected_signature=eval_signature)
        evaluation_result_source_for_group = 'executed'
        evaluation_summary: dict[str, root.Any]
        if cache_entry is not None:
            cached_report = cache_entry.get('report')
            if not isinstance(cached_report, dict):
                cached_report = {}
            cached_md = str(cache_entry.get('report_md') or '')
            eval_report_json_path, eval_report_md_path = root._materialize_all_method_cached_eval_outputs(eval_output_dir=representative_eval_output_dir, report_payload=cached_report, report_md_text=cached_md)
            metric_bundle = root._benchmark_report_metric_bundle(cached_report)
            evaluation_summary = {'status': 'ok', 'error': '', **metric_bundle, 'timing': root._normalize_timing_payload(cached_report.get('timing')), 'report': cached_report, 'report_md_text': cached_md, 'eval_report_json_path': eval_report_json_path, 'eval_report_md_path': eval_report_md_path, 'duration_seconds': 0.0}
            evaluation_result_source_for_group = 'reused_cross_run'
            evaluation_results_reused_cross_run += len(ordered_group)
        else:
            _emit_status(f'Evaluating signature {signature_index}/{max(1, evaluation_signatures_unique)} (group size {len(ordered_group)}).', color=root.typer.colors.CYAN)
            evaluation_summary = root._run_all_method_evaluate_prediction_record_once(gold_spans_path=root.Path(str(representative_row.get('gold_spans_path') or '')), source_file=root.Path(str(representative_row.get('source_file') or '')), prediction_record_path=representative_prediction_record, eval_output_dir=representative_eval_output_dir, processed_output_dir=representative_processed_output_dir, sequence_matcher=sequence_matcher, epub_extractor=root._row_dimension_str(representative_row, 'epub_extractor'), overlap_threshold=overlap_threshold, force_source_match=force_source_match, alignment_cache_dir=canonical_alignment_cache_dir, progress_callback=None)
            if str(evaluation_summary.get('status') or '').strip().lower() == 'ok':
                evaluation_runs_executed += 1
                if len(ordered_group) > 1:
                    evaluation_results_reused_in_run += len(ordered_group) - 1
                cached_payload = {'schema_version': root.ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION, 'created_at': root.dt.datetime.now().isoformat(timespec='seconds'), 'eval_signature': eval_signature, 'eval_mode': root.BENCHMARK_EVAL_MODE_CANONICAL_TEXT, 'sequence_matcher': sequence_matcher, 'source_file': str(representative_row.get('source_file') or ''), 'gold_spans_path': str(representative_row.get('gold_spans_path') or ''), 'report': evaluation_summary.get('report'), 'report_md': evaluation_summary.get('report_md_text')}
                try:
                    root._write_all_method_eval_signature_cache_entry(cache_path=cache_path, payload=cached_payload)
                except Exception as exc:
                    root.logger.warning('Ignoring eval-signature cache write failure for %s: %s', cache_path, exc)
        if str(evaluation_summary.get('status') or '').strip().lower() != 'ok':
            error_text = str(evaluation_summary.get('error') or 'Evaluation failed.')
            for row in ordered_group:
                failed_row = dict(row)
                failed_row['status'] = 'failed'
                failed_row['error'] = error_text
                failed_row['evaluation_result_source'] = 'failed'
                failed_row['evaluation_representative_config_dir'] = representative_config_dir
                failed_row['eval_signature'] = eval_signature
                failed_rows.append(failed_row)
            continue
        summary_timing = root._normalize_timing_payload(evaluation_summary.get('timing'))
        summary_evaluation_seconds = root._report_optional_metric(summary_timing.get('evaluation_seconds'))
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = root._report_optional_metric(summary_timing.get('total_seconds'))
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = root._report_optional_metric(evaluation_summary.get('duration_seconds'))
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = 0.0
        summary_eval_wall_seconds = max(0.0, root._report_metric(evaluation_summary.get('duration_seconds')))
        summary_report_json_path = root.Path(str(evaluation_summary.get('eval_report_json_path') or ''))
        summary_report_md_path = root.Path(str(evaluation_summary.get('eval_report_md_path') or ''))
        alignment_guardrail_fields = root._all_method_extract_alignment_guardrail_fields(root.cast(dict[str, root.Any] | None, evaluation_summary.get('report')))
        for row in ordered_group:
            result_row = dict(row)
            is_representative = root._report_count(result_row.get('global_dispatch_index', result_row.get('config_index'))) == root._report_count(representative_row.get('global_dispatch_index', representative_row.get('config_index')))
            row_result_source = 'executed'
            if evaluation_result_source_for_group == 'reused_cross_run':
                row_result_source = 'reused_cross_run'
            elif not is_representative:
                row_result_source = 'reused_in_run'
            row_timing = root._normalize_timing_payload(result_row.get('timing'))
            prediction_total_seconds = root._report_optional_metric(row_timing.get('total_seconds'))
            if prediction_total_seconds is None:
                prediction_total_seconds = root._report_optional_metric(result_row.get('duration_seconds'))
            if prediction_total_seconds is None:
                prediction_total_seconds = 0.0
            row_eval_seconds = summary_evaluation_seconds if row_result_source == 'executed' else 0.0
            row_eval_wall = summary_eval_wall_seconds if row_result_source == 'executed' else 0.0
            row_total_seconds = max(0.0, prediction_total_seconds + row_eval_seconds)
            row_timing = root._timing_with_updates(row_timing, evaluation_seconds=row_eval_seconds, total_seconds=row_total_seconds, checkpoints={'all_method_eval_wall_seconds': row_eval_wall, 'all_method_eval_reused_in_run': 1.0 if row_result_source == 'reused_in_run' else 0.0, 'all_method_eval_reused_cross_run': 1.0 if row_result_source == 'reused_cross_run' else 0.0})
            result_row['status'] = 'ok'
            result_row['error'] = ''
            result_row['precision'] = root._report_metric(evaluation_summary.get('precision'))
            result_row['recall'] = root._report_metric(evaluation_summary.get('recall'))
            result_row['f1'] = root._report_metric(evaluation_summary.get('f1'))
            result_row['practical_precision'] = root._report_metric(evaluation_summary.get('practical_precision'))
            result_row['practical_recall'] = root._report_metric(evaluation_summary.get('practical_recall'))
            result_row['practical_f1'] = root._report_metric(evaluation_summary.get('practical_f1'))
            result_row.update(alignment_guardrail_fields)
            result_row['eval_signature'] = eval_signature
            result_row['evaluation_result_source'] = row_result_source
            result_row['evaluation_representative_config_dir'] = representative_config_dir
            result_row['duration_seconds'] = row_total_seconds
            result_row['timing'] = row_timing
            result_row['eval_report_json'] = root._path_for_manifest(source_root, summary_report_json_path)
            result_row['eval_report_md'] = root._path_for_manifest(source_root, summary_report_md_path)
            successful_rows.append(result_row)
    matcher_guardrails = root._all_method_build_matcher_guardrails(successful_rows)
    scheduler_summary['matcher_guardrails'] = matcher_guardrails
    for warning in matcher_guardrails.get('warnings', []):
        _emit_status(f'Matcher guardrail warning: {warning}', color=root.typer.colors.YELLOW)
    source_rows = root._write_all_method_source_reports_from_global_rows(target_variants=target_variants, source_job_plans=source_job_plans, root_output_dir=root_output_dir, processed_output_root=processed_output_root, successful_rows=successful_rows, failed_rows=failed_rows, include_codex_farm_requested=include_codex_farm_requested, include_codex_farm_effective=include_codex_farm_effective, eval_signature_cache_dir=eval_signature_cache_dir, scheduler_summary=scheduler_summary, retry_failed_configs_requested=effective_retry_failed_configs, retry_passes_executed=retry_passes_executed, retry_recovered_configs=retry_recovered_configs)
    successful_source_count = sum((1 for row in source_rows if str(row.get('status', '')).lower() == 'ok'))
    total_completed_config_runs = sum((root._report_count(row.get('variant_count_completed')) for row in source_rows))
    total_successful_config_runs = sum((root._report_count(row.get('variant_count_successful')) for row in source_rows))
    total_failed_config_runs = max(0, total_completed_config_runs - total_successful_config_runs)
    total_evaluation_signatures_unique = sum((root._report_count(row.get('evaluation_signatures_unique')) for row in source_rows))
    total_evaluation_runs_executed = sum((root._report_count(row.get('evaluation_runs_executed')) for row in source_rows))
    total_evaluation_results_reused_in_run = sum((root._report_count(row.get('evaluation_results_reused_in_run')) for row in source_rows))
    total_evaluation_results_reused_cross_run = sum((root._report_count(row.get('evaluation_results_reused_cross_run')) for row in source_rows))
    total_prediction_signatures_unique = sum((root._report_count(row.get('prediction_signatures_unique')) for row in source_rows))
    total_prediction_runs_executed = sum((root._report_count(row.get('prediction_runs_executed')) for row in source_rows))
    total_prediction_results_reused_in_run = sum((root._report_count(row.get('prediction_results_reused_in_run')) for row in source_rows))
    total_prediction_results_reused_cross_run = sum((root._report_count(row.get('prediction_results_reused_cross_run')) for row in source_rows))
    total_split_convert_input_groups = sum((root._report_count(row.get('split_convert_input_groups')) for row in source_rows))
    total_split_convert_reuse_candidates = sum((root._report_count(row.get('split_convert_reuse_candidates')) for row in source_rows))
    total_split_convert_reuse_safe_candidates = sum((root._report_count(row.get('split_convert_reuse_safe_candidates')) for row in source_rows))
    total_split_convert_reuse_blocked = sum((root._report_count(row.get('split_convert_reuse_blocked_by_prediction_variance')) for row in source_rows))
    run_wall_seconds = max(0.0, root.time.monotonic() - run_started)
    source_timing_values: list[tuple[dict[str, root.Any], float]] = []
    config_total_seconds = 0.0
    for row in source_rows:
        timing_summary = row.get('timing_summary')
        if not isinstance(timing_summary, dict):
            continue
        source_seconds = root._report_optional_metric(timing_summary.get('source_wall_seconds'))
        if source_seconds is not None:
            source_timing_values.append((row, source_seconds))
        config_seconds = root._report_optional_metric(timing_summary.get('config_total_seconds'))
        if config_seconds is not None:
            config_total_seconds += config_seconds
    source_total_seconds = sum((seconds for _row, seconds in source_timing_values))
    source_average_seconds = source_total_seconds / len(source_timing_values) if source_timing_values else None
    config_average_seconds = config_total_seconds / total_successful_config_runs if total_successful_config_runs > 0 else None
    slowest_source_row = max(source_timing_values, key=lambda item: item[1])[0] if source_timing_values else None
    slowest_source_seconds = max((seconds for _row, seconds in source_timing_values)) if source_timing_values else None
    slowest_config_name: str | None = None
    slowest_config_seconds: float | None = None
    for row in source_rows:
        timing_summary = row.get('timing_summary')
        if not isinstance(timing_summary, dict):
            continue
        candidate_seconds = root._report_optional_metric(timing_summary.get('slowest_config_seconds'))
        if candidate_seconds is None:
            continue
        candidate_dir = str(timing_summary.get('slowest_config_dir') or '').strip()
        if not candidate_dir:
            continue
        candidate_name = f'{row.get('source_slug', '')}/{candidate_dir}'.strip('/')
        if slowest_config_seconds is None or candidate_seconds > slowest_config_seconds:
            slowest_config_seconds = candidate_seconds
            slowest_config_name = candidate_name
    report_payload: dict[str, root.Any] = {'created_at': root.dt.datetime.now().isoformat(timespec='seconds'), 'eval_mode': root.BENCHMARK_EVAL_MODE_CANONICAL_TEXT, 'matched_target_count': total_targets, 'unmatched_target_count': len(unmatched_targets), 'scheduler_scope': 'global_config_queue', 'source_schedule_strategy': resolved_source_scheduling, 'source_shard_threshold_seconds': resolved_source_shard_threshold_seconds, 'source_shard_max_parts': resolved_source_shard_max_parts, 'source_shard_min_variants': resolved_source_shard_min_variants, 'source_job_count_planned': len(source_job_plans), 'source_schedule_plan': [{'dispatch_index': dispatch_index + 1, 'source_position': plan.source_position + 1, 'source_group_key': plan.source_group_key, 'source_file': str(plan.source_file), 'source_file_name': plan.source_display_name, 'source_slug': plan.source_slug, 'source_shard_index': plan.shard_index + 1, 'source_shard_total': max(1, root._report_count(plan.shard_total)), 'variant_count': len(plan.variants), 'estimated_seconds': plan.estimated_seconds, 'estimate_basis': plan.estimate_basis} for dispatch_index, plan in enumerate(source_job_plans)], 'global_queue_schedule_plan': [{'dispatch_index': item.global_dispatch_index, 'source_position': item.source_position + 1, 'source_group_key': item.source_group_key, 'source_file': str(item.source_file), 'source_file_name': item.source_file_name, 'source_slug': item.source_slug, 'source_shard_index': item.source_shard_index + 1, 'source_shard_total': max(1, root._report_count(item.source_shard_total)), 'source_config_index': item.config_index, 'source_config_total': item.config_total, 'variant_slug': item.variant.slug, 'estimated_seconds': item.source_estimated_seconds, 'estimate_basis': item.source_estimate_basis} for item in work_items], 'source_parallelism_configured': source_parallelism_configured, 'source_parallelism_effective': source_parallelism_effective, 'total_config_runs_planned': total_planned_config_runs, 'total_config_runs_completed': total_completed_config_runs, 'total_config_runs_successful': total_successful_config_runs, 'global_queue_planned_configs': total_planned_config_runs, 'global_queue_completed_configs': total_completed_config_runs, 'global_queue_failed_configs': total_failed_config_runs, 'evaluation_signatures_unique': total_evaluation_signatures_unique, 'evaluation_runs_executed': total_evaluation_runs_executed, 'evaluation_results_reused_in_run': total_evaluation_results_reused_in_run, 'evaluation_results_reused_cross_run': total_evaluation_results_reused_cross_run, 'prediction_signatures_unique': total_prediction_signatures_unique, 'prediction_runs_executed': total_prediction_runs_executed, 'prediction_results_reused_in_run': total_prediction_results_reused_in_run, 'prediction_results_reused_cross_run': total_prediction_results_reused_cross_run, 'split_convert_input_groups': total_split_convert_input_groups, 'split_convert_reuse_candidates': total_split_convert_reuse_candidates, 'split_convert_reuse_safe_candidates': total_split_convert_reuse_safe_candidates, 'split_convert_reuse_blocked_by_prediction_variance': total_split_convert_reuse_blocked, 'prediction_reuse_key_schema_version': root.ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION, 'split_convert_input_key_schema_version': root.ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION, 'successful_source_count': successful_source_count, 'failed_source_count': total_targets - successful_source_count, 'config_timeout_seconds': effective_config_timeout_seconds, 'retry_failed_configs_requested': effective_retry_failed_configs, 'include_codex_farm_requested': include_codex_farm_requested, 'include_codex_farm_effective': include_codex_farm_effective, 'canonical_alignment_cache_root': str(resolved_canonical_cache_root), 'prediction_reuse_cache_root': str(resolved_prediction_reuse_cache_root), 'executor_resolution': {'process_workers_required': bool(require_process_workers), 'process_worker_probe_available': process_worker_probe_available, 'process_worker_probe_error': process_worker_probe_error, 'config_executor_backends_seen': sorted(config_executor_backends_seen)}, 'timing_summary': {'run_wall_seconds': run_wall_seconds, 'source_total_seconds': source_total_seconds, 'source_average_seconds': source_average_seconds, 'config_total_seconds': config_total_seconds, 'config_average_seconds': config_average_seconds, 'slowest_source': str(slowest_source_row.get('source_file', '')) if isinstance(slowest_source_row, dict) else None, 'slowest_source_seconds': slowest_source_seconds, 'slowest_config': slowest_config_name, 'slowest_config_seconds': slowest_config_seconds}, 'scheduler_summary': dict(scheduler_summary), 'sources': source_rows, 'unmatched': [{'gold_spans_path': str(unmatched.gold_spans_path), 'gold_display': unmatched.gold_display, 'reason': unmatched.reason, 'source_hint': unmatched.source_hint} for unmatched in unmatched_targets]}
    history_csv_path = root.history_csv_for_output(processed_output_root / root._DASHBOARD_REFRESH_SENTINEL_DIRNAME)
    root._refresh_dashboard_after_history_write(csv_path=history_csv_path, output_root=resolved_dashboard_output_root, golden_root=golden_root, dashboard_out_dir=root.history_root_for_output(resolved_dashboard_output_root) / 'dashboard' if resolved_dashboard_output_root is not None else None, reason='all-method benchmark global queue batch append')
    report_json_path = root_output_dir / 'all_method_benchmark_multi_source_report.json'
    report_json_path.write_text(root.json.dumps(report_payload, indent=2, sort_keys=True), encoding='utf-8')
    report_md_path = root_output_dir / 'all_method_benchmark_multi_source_report.md'
    report_md_path.write_text(root._render_all_method_multi_source_report_md(report_payload), encoding='utf-8')
    completion_color = root.typer.colors.GREEN if successful_source_count == total_targets and total_successful_config_runs == total_planned_config_runs else root.typer.colors.YELLOW
    _emit_status(f'All method benchmark complete: sources {successful_source_count}/{total_targets}, configs {total_successful_config_runs}/{total_planned_config_runs}.', color=completion_color)
    if progress_callback is None:
        root.typer.secho(f'Report: {report_md_path}', fg=root.typer.colors.CYAN)
    return report_md_path

def _run_all_method_benchmark_multi_source(*, target_variants: list[tuple[root.AllMethodTarget, list[root.AllMethodVariant]]], unmatched_targets: list[root.AllMethodUnmatchedGold], include_codex_farm_requested: bool, include_codex_farm_effective: bool, root_output_dir: root.Path, processed_output_root: root.Path, golden_root: root.Path, overlap_threshold: float, force_source_match: bool, progress_callback: root.Callable[[str], None] | None=None, dashboard: root._AllMethodProgressDashboard | None=None, max_parallel_sources: int | None=None, max_inflight_pipelines: int | None=None, max_concurrent_split_phases: int | None=None, max_eval_tail_pipelines: int | None=None, config_timeout_seconds: int | None=None, retry_failed_configs: int | None=None, scheduler_scope: str | None=None, source_scheduling: str | None=None, source_shard_threshold_seconds: float | None=None, source_shard_max_parts: int | None=None, source_shard_min_variants: int | None=None, wing_backlog_target: int | None=None, smart_scheduler: bool=False, canonical_alignment_cache_root: root.Path | None=None, prediction_reuse_cache_root: root.Path | None=None, dashboard_output_root: root.Path | None=None, require_process_workers: bool=False) -> root.Path:
    root._normalize_all_method_scheduler_scope(scheduler_scope)
    return root._run_all_method_benchmark_global_queue(target_variants=target_variants, unmatched_targets=unmatched_targets, include_codex_farm_requested=include_codex_farm_requested, include_codex_farm_effective=include_codex_farm_effective, root_output_dir=root_output_dir, processed_output_root=processed_output_root, golden_root=golden_root, overlap_threshold=overlap_threshold, force_source_match=force_source_match, progress_callback=progress_callback, dashboard=dashboard, max_parallel_sources=max_parallel_sources, max_inflight_pipelines=max_inflight_pipelines, max_concurrent_split_phases=max_concurrent_split_phases, max_eval_tail_pipelines=max_eval_tail_pipelines, config_timeout_seconds=config_timeout_seconds, retry_failed_configs=retry_failed_configs, source_scheduling=source_scheduling, source_shard_threshold_seconds=source_shard_threshold_seconds, source_shard_max_parts=source_shard_max_parts, source_shard_min_variants=source_shard_min_variants, wing_backlog_target=wing_backlog_target, smart_scheduler=smart_scheduler, canonical_alignment_cache_root=canonical_alignment_cache_root, prediction_reuse_cache_root=prediction_reuse_cache_root, dashboard_output_root=dashboard_output_root, require_process_workers=require_process_workers)

def _run_all_method_benchmark(*, gold_spans_path: root.Path, source_file: root.Path, variants: list[root.AllMethodVariant], include_codex_farm_requested: bool, include_codex_farm_effective: bool, root_output_dir: root.Path, processed_output_root: root.Path, golden_root: root.Path, overlap_threshold: float, force_source_match: bool, progress_callback: root.Callable[[str], None] | None=None, dashboard: root._AllMethodProgressDashboard | None=None, dashboard_source_index: int | None=None, max_inflight_pipelines: int | None=None, max_concurrent_split_phases: int | None=None, max_eval_tail_pipelines: int | None=None, config_timeout_seconds: int | None=None, retry_failed_configs: int | None=None, wing_backlog_target: int | None=None, smart_scheduler: bool=False, refresh_dashboard_after_source: bool=True, source_parallelism_effective: int | None=1, canonical_alignment_cache_dir_override: root.Path | None=None, prediction_reuse_cache_dir_override: root.Path | None=None, dashboard_output_root: root.Path | None=None, require_process_workers: bool=False) -> root.Path:
    source_started = root.time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = root_output_dir / '.scratch'
    scratch_root.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)
    split_phase_gate_dir = root_output_dir / '.split_phase_slots'
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    canonical_alignment_cache_dir = canonical_alignment_cache_dir_override if canonical_alignment_cache_dir_override is not None else root_output_dir / '.cache' / 'canonical_alignment'
    prediction_reuse_cache_dir = prediction_reuse_cache_dir_override.expanduser() if prediction_reuse_cache_dir_override is not None else root._resolve_all_method_prediction_reuse_cache_dir(root_output_dir=root_output_dir)
    scheduler_events_dir = root_output_dir / '.scheduler_events'
    scheduler_timeseries_path = root_output_dir / root.ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    if scheduler_events_dir.exists():
        root.shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    if scheduler_timeseries_path.exists():
        scheduler_timeseries_path.unlink()
    total_variants = len(variants)
    scheduler_runtime = root._resolve_all_method_scheduler_runtime(total_variants=total_variants, max_inflight_pipelines=max_inflight_pipelines, max_concurrent_split_phases=max_concurrent_split_phases, max_eval_tail_pipelines=max_eval_tail_pipelines, wing_backlog_target=wing_backlog_target, smart_scheduler=smart_scheduler, source_parallelism_effective=source_parallelism_effective)
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
    split_worker_cap_per_config, split_worker_guard = root._resolve_all_method_split_worker_cap(split_phase_slots=effective_split_phase_slots, source_parallelism_effective=source_parallelism_effective)
    max_requested_split_workers = max([max(max(1, root._report_count(variant.run_settings.workers)), max(1, root._report_count(variant.run_settings.pdf_split_workers)), max(1, root._report_count(variant.run_settings.epub_split_workers))) for variant in variants], default=1)
    effective_config_timeout_seconds = root._resolve_all_method_config_timeout_seconds(config_timeout_seconds)
    effective_retry_failed_configs = root._resolve_all_method_retry_failed_configs(retry_failed_configs)

    def _emit_status(message: str, *, color: root.typer.colors=root.typer.colors.CYAN) -> None:
        cleaned = str(message or '').strip()
        if not cleaned:
            return
        if progress_callback is not None:
            if root._is_structured_progress_message(cleaned):
                root._notify_progress_callback(progress_callback, cleaned)
                return
            if dashboard is not None:
                dashboard.set_task(cleaned)
                root._notify_progress_callback(progress_callback, dashboard.render())
                return
            root._notify_progress_callback(progress_callback, cleaned)
            return
        root.typer.secho(cleaned, fg=color)
    if split_phase_slot_mode != 'configured':
        _emit_status(f'Resource guard capped split slots to {effective_split_phase_slots} (requested {requested_split_phase_slots}; cpu cap {split_phase_slot_cap_by_cpu}; memory cap {split_phase_slot_cap_by_memory}).', color=root.typer.colors.YELLOW)
    if split_worker_cap_per_config < max_requested_split_workers:
        _emit_status(f'Resource guard capped split workers per active config to {split_worker_cap_per_config} (requested peak {max_requested_split_workers}; split slots {effective_split_phase_slots}).', color=root.typer.colors.YELLOW)
    variant_rows: list[dict[str, root.Any]] = []
    indexed_variants = list(enumerate(variants, start=1))
    scheduler_phase_by_config: dict[int, str] = {}
    scheduler_event_offsets: dict[int, int] = {}
    scheduler_last_tick = root.time.monotonic()
    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_last_snapshot = ''
    scheduler_smart_enabled = bool(effective_smart_scheduler)
    scheduler_timeseries_last_snapshot = ''
    scheduler_timeseries_last_write_monotonic = source_started
    scheduler_timeseries_rows_written = 0
    scheduler_timeseries_heartbeat_seconds = max(root.ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS, root.ALL_METHOD_SCHEDULER_POLL_SECONDS)
    scheduler_cpu_source = 'proc_stat_linux'
    scheduler_cpu_samples_collected = 0
    scheduler_cpu_totals_last: tuple[int, int] | None = None
    scheduler_cpu_utilization_pct_last: float | None = None
    scheduler_cpu_utilization_pct_high_water = 0.0
    scheduler_admission_adjustments = 0
    scheduler_admission_pressure_boosts = 0
    scheduler_admission_saturation_clamps = 0
    scheduler_admission_cpu_hot_clamps = 0
    scheduler_admission_active_cap_peak = configured_inflight_pipelines
    scheduler_admission_guard_target_peak = min(max(1, total_variants), max(1, effective_split_phase_slots + effective_wing_backlog_target))
    scheduler_admission_last_key: tuple[int, int, str] | None = None
    scheduler_admission_active_cap_current = configured_inflight_pipelines
    scheduler_admission_guard_target_current = min(max(1, total_variants), max(1, effective_split_phase_slots + effective_wing_backlog_target))
    scheduler_admission_wing_target_current = effective_wing_backlog_target
    scheduler_admission_reason_current = 'base'
    process_worker_probe_available: bool | None = None
    process_worker_probe_error: str | None = None
    config_executor_backends_seen: set[str] = set()

    def _scheduler_event_path(config_index: int) -> root.Path:
        return scheduler_events_dir / f'config_{config_index:03d}.jsonl'

    def _read_linux_cpu_totals() -> tuple[int, int] | None:
        try:
            with root.Path('/proc/stat').open('r', encoding='utf-8') as handle:
                first_line = handle.readline()
        except OSError:
            return None
        line = str(first_line or '').strip()
        if not line:
            return None
        parts = line.split()
        if not parts or parts[0] != 'cpu':
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
        return (total, idle)

    def _sample_host_cpu_utilization_pct() -> float | None:
        nonlocal scheduler_cpu_source
        nonlocal scheduler_cpu_samples_collected
        nonlocal scheduler_cpu_totals_last
        current = _read_linux_cpu_totals()
        if current is None:
            scheduler_cpu_source = 'unavailable'
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
        return max(0.0, min(100.0, float(busy_delta) / float(total_delta) * 100.0))

    def _scheduler_phase_for_event(event_name: str) -> str | None:
        event = str(event_name or '').strip()
        if event in {'config_started', 'prep_started'}:
            return 'prep'
        if event == 'split_wait_started':
            return 'split_wait'
        if event == 'split_active_started':
            return 'split_active'
        if event in {'split_active_finished', 'post_started'}:
            return 'post'
        if event in {'post_finished', 'evaluate_started'}:
            return 'evaluate'
        if event in {'evaluate_finished', 'config_finished'}:
            return 'done'
        return None

    def _poll_scheduler_events(active_indices: set[int]) -> None:
        for active_index in sorted(active_indices):
            event_path = _scheduler_event_path(active_index)
            if not event_path.exists():
                continue
            offset = max(0, scheduler_event_offsets.get(active_index, 0))
            with event_path.open('r', encoding='utf-8') as handle:
                handle.seek(offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = root.json.loads(line)
                    except root.json.JSONDecodeError:
                        root.logger.warning('Ignoring malformed scheduler event in %s: %s', event_path, line[:160])
                        continue
                    if not isinstance(payload, dict):
                        continue
                    phase = _scheduler_phase_for_event(str(payload.get('event') or ''))
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
            phase = scheduler_phase_by_config.get(active_index, 'prep')
            if phase == 'split_active':
                heavy_active += 1
            elif phase == 'split_wait':
                split_wait += 1
            elif phase == 'post':
                post_active += 1
            elif phase == 'evaluate':
                evaluate_active += 1
            elif phase == 'done':
                continue
            else:
                prep_active += 1
        wing_backlog = split_wait + prep_active
        return {'heavy_active': heavy_active, 'split_wait': split_wait, 'prep_active': prep_active, 'post_active': post_active, 'evaluate_active': evaluate_active, 'wing_backlog': wing_backlog, 'active': len(active_indices)}

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
        now = root.time.monotonic()
        delta = max(0.0, now - scheduler_last_tick)
        counts = _compute_scheduler_counts(active_indices)
        scheduler_capacity_seconds += float(effective_split_phase_slots) * delta
        scheduler_busy_seconds += float(min(effective_split_phase_slots, counts['heavy_active'])) * delta
        if pending_count > 0 and counts['heavy_active'] < effective_split_phase_slots:
            scheduler_idle_gap_seconds += delta
        scheduler_wing_area_seconds += float(counts['wing_backlog']) * delta
        scheduler_max_wing_backlog = max(scheduler_max_wing_backlog, counts['wing_backlog'])
        scheduler_max_active_pipelines = max(scheduler_max_active_pipelines, counts['active'])
        scheduler_max_eval_active = max(scheduler_max_eval_active, counts['evaluate_active'])
        sampled_cpu = _sample_host_cpu_utilization_pct()
        if sampled_cpu is not None:
            scheduler_cpu_utilization_pct_last = sampled_cpu
            scheduler_cpu_utilization_pct_high_water = max(scheduler_cpu_utilization_pct_high_water, sampled_cpu)
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return f'scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} | wing {counts['wing_backlog']} | eval {counts['evaluate_active']} | active {counts['active']} | pending {max(0, pending_count)}'

    def _write_scheduler_timeseries_row(*, counts: dict[str, int], pending_count: int, force: bool=False) -> None:
        nonlocal scheduler_timeseries_last_snapshot
        nonlocal scheduler_timeseries_last_write_monotonic
        nonlocal scheduler_timeseries_rows_written
        pending_safe = max(0, pending_count)
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_safe)
        now_monotonic = root.time.monotonic()
        write_due = force or snapshot != scheduler_timeseries_last_snapshot or now_monotonic - scheduler_timeseries_last_write_monotonic >= scheduler_timeseries_heartbeat_seconds
        if not write_due:
            return
        row = {'timestamp': root.dt.datetime.now(tz=root.dt.timezone.utc).isoformat(timespec='milliseconds'), 'monotonic_seconds': now_monotonic, 'elapsed_seconds': max(0.0, now_monotonic - source_started), 'snapshot': snapshot, 'heavy_active': root._report_count(counts.get('heavy_active')), 'heavy_capacity': root._report_count(effective_split_phase_slots), 'split_wait': root._report_count(counts.get('split_wait')), 'prep_active': root._report_count(counts.get('prep_active')), 'post_active': root._report_count(counts.get('post_active')), 'evaluate_active': root._report_count(counts.get('evaluate_active')), 'wing_backlog': root._report_count(counts.get('wing_backlog')), 'active': root._report_count(counts.get('active')), 'pending': pending_safe, 'cpu_utilization_pct': scheduler_cpu_utilization_pct_last, 'admission_active_cap': scheduler_admission_active_cap_current, 'admission_guard_target': scheduler_admission_guard_target_current, 'admission_wing_target': scheduler_admission_wing_target_current, 'admission_reason': scheduler_admission_reason_current}
        try:
            with scheduler_timeseries_path.open('a', encoding='utf-8') as handle:
                handle.write(root.json.dumps(row, sort_keys=True) + '\n')
        except Exception as exc:
            root.logger.warning('Ignoring scheduler time-series write failure for %s: %s', scheduler_timeseries_path, exc)
            return
        scheduler_timeseries_last_snapshot = snapshot
        scheduler_timeseries_last_write_monotonic = now_monotonic
        scheduler_timeseries_rows_written += 1

    def _emit_scheduler_snapshot(*, counts: dict[str, int], pending_count: int, force_timeseries: bool=False) -> None:
        nonlocal scheduler_last_snapshot
        _write_scheduler_timeseries_row(counts=counts, pending_count=pending_count, force=force_timeseries)
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(counts=counts, pending_count=max(0, pending_count))
        if snapshot == scheduler_last_snapshot:
            return
        scheduler_last_snapshot = snapshot
        _emit_status(snapshot, color=root.typer.colors.BRIGHT_BLACK)

    def _compute_scheduler_metrics_from_event_files(*, source_end_monotonic: float) -> dict[str, float | int] | None:
        rows: list[tuple[float, str, int]] = []
        for event_path in sorted(scheduler_events_dir.glob('config_*.jsonl')):
            try:
                lines = event_path.read_text(encoding='utf-8').splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    payload = root.json.loads(line)
                except root.json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event_name = str(payload.get('event') or '').strip()
                if not event_name:
                    continue
                event_time = root._report_optional_metric(payload.get('monotonic_seconds'))
                event_index = root._report_count(payload.get('config_index'))
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
                if phase == 'split_active':
                    heavy_active += 1
                elif phase == 'split_wait':
                    split_wait += 1
                elif phase == 'post':
                    post_active += 1
                elif phase == 'evaluate':
                    evaluate_active += 1
                elif phase == 'done':
                    continue
                else:
                    prep_active += 1
            wing_backlog = split_wait + prep_active
            active = heavy_active + split_wait + prep_active + post_active + evaluate_active
            return {'heavy_active': heavy_active, 'evaluate_active': evaluate_active, 'wing_backlog': wing_backlog, 'active': active}
        previous_time = rows[0][0]
        for event_time, event_name, event_index in rows:
            delta = max(0.0, event_time - previous_time)
            counts = _counts()
            capacity_seconds += float(effective_split_phase_slots) * delta
            busy_seconds += float(min(effective_split_phase_slots, counts['heavy_active'])) * delta
            if len(started_configs) < total_variants and counts['heavy_active'] < effective_split_phase_slots:
                idle_gap_seconds += delta
            wing_area_seconds += float(counts['wing_backlog']) * delta
            max_wing_backlog = max(max_wing_backlog, counts['wing_backlog'])
            max_active_pipelines = max(max_active_pipelines, counts['active'])
            max_eval_active = max(max_eval_active, counts['evaluate_active'])
            previous_time = event_time
            mapped_phase = _scheduler_phase_for_event(event_name)
            if event_name == 'config_started':
                started_configs.add(event_index)
            if mapped_phase is not None:
                phases[event_index] = mapped_phase
            if event_name == 'config_finished':
                phases[event_index] = 'done'
        tail_delta = max(0.0, source_end_monotonic - previous_time)
        if tail_delta > 0:
            counts = _counts()
            capacity_seconds += float(effective_split_phase_slots) * tail_delta
            busy_seconds += float(min(effective_split_phase_slots, counts['heavy_active'])) * tail_delta
            if len(started_configs) < total_variants and counts['heavy_active'] < effective_split_phase_slots:
                idle_gap_seconds += tail_delta
            wing_area_seconds += float(counts['wing_backlog']) * tail_delta
            max_wing_backlog = max(max_wing_backlog, counts['wing_backlog'])
            max_active_pipelines = max(max_active_pipelines, counts['active'])
            max_eval_active = max(max_eval_active, counts['evaluate_active'])
        return {'heavy_slot_capacity_seconds': capacity_seconds, 'heavy_slot_busy_seconds': busy_seconds, 'idle_gap_seconds': idle_gap_seconds, 'wing_backlog_area_seconds': wing_area_seconds, 'max_wing_backlog': max_wing_backlog, 'max_active_pipelines_observed': max_active_pipelines, 'max_eval_active_observed': max_eval_active}

    def _finalize_scheduler_metrics() -> dict[str, root.Any]:
        event_metrics = _compute_scheduler_metrics_from_event_files(source_end_monotonic=root.time.monotonic())
        capacity_seconds = scheduler_capacity_seconds
        busy_seconds = scheduler_busy_seconds
        idle_gap_seconds = scheduler_idle_gap_seconds
        wing_area_seconds = scheduler_wing_area_seconds
        max_wing_backlog = scheduler_max_wing_backlog
        max_active = scheduler_max_active_pipelines
        max_eval_active = scheduler_max_eval_active
        if isinstance(event_metrics, dict):
            capacity_seconds = root._report_metric(event_metrics.get('heavy_slot_capacity_seconds'))
            busy_seconds = root._report_metric(event_metrics.get('heavy_slot_busy_seconds'))
            idle_gap_seconds = root._report_metric(event_metrics.get('idle_gap_seconds'))
            wing_area_seconds = root._report_metric(event_metrics.get('wing_backlog_area_seconds'))
            max_wing_backlog = max(max_wing_backlog, root._report_count(event_metrics.get('max_wing_backlog')))
            max_active = max(max_active, root._report_count(event_metrics.get('max_active_pipelines_observed')))
            max_eval_active = max(max_eval_active, root._report_count(event_metrics.get('max_eval_active_observed')))
        utilization_pct = busy_seconds / capacity_seconds * 100.0 if capacity_seconds > 0 else 0.0
        avg_wing_backlog = wing_area_seconds / capacity_seconds if capacity_seconds > 0 else 0.0
        return {'mode': 'smart' if scheduler_smart_enabled else 'fixed', 'configured_inflight_pipelines': configured_inflight_pipelines, 'effective_inflight_pipelines': effective_inflight_pipelines, 'split_phase_slots_requested': requested_split_phase_slots, 'split_phase_slots': effective_split_phase_slots, 'split_phase_slot_mode': split_phase_slot_mode, 'split_phase_slot_cap_by_cpu': split_phase_slot_cap_by_cpu, 'split_phase_slot_cap_by_memory': split_phase_slot_cap_by_memory, 'split_worker_cap_per_config': split_worker_cap_per_config, 'split_worker_cap_by_cpu': split_worker_guard.get('split_worker_cap_by_cpu'), 'split_worker_cap_by_memory': split_worker_guard.get('split_worker_cap_by_memory'), 'wing_backlog_target': effective_wing_backlog_target, 'eval_tail_headroom_mode': eval_tail_headroom_mode, 'eval_tail_headroom_configured': configured_eval_tail_headroom, 'eval_tail_headroom_effective': effective_eval_tail_headroom, 'max_active_during_eval': max_active_during_eval, 'adaptive_overcommit_limit': adaptive_overcommit_limit, 'adaptive_max_guard_target': adaptive_max_guard_target, 'source_parallelism_effective': scheduler_source_parallelism, 'cpu_budget_per_source': scheduler_cpu_budget_per_source, 'cpu_budget_total': scheduler_cpu_budget_total, 'max_eval_tail_pipelines': effective_eval_tail_headroom, 'smart_tail_buffer_slots': effective_eval_tail_headroom if bool(effective_smart_scheduler) else 0, 'smart_scheduler_enabled': bool(effective_smart_scheduler), 'heavy_slot_capacity_seconds': capacity_seconds, 'heavy_slot_busy_seconds': busy_seconds, 'heavy_slot_utilization_pct': utilization_pct, 'avg_wing_backlog': avg_wing_backlog, 'max_wing_backlog': max_wing_backlog, 'idle_gap_seconds': idle_gap_seconds, 'max_active_pipelines_observed': max_active, 'max_eval_active_observed': max_eval_active, 'adaptive_admission_adjustments': scheduler_admission_adjustments, 'adaptive_admission_pressure_boosts': scheduler_admission_pressure_boosts, 'adaptive_admission_saturation_clamps': scheduler_admission_saturation_clamps, 'adaptive_admission_cpu_hot_clamps': scheduler_admission_cpu_hot_clamps, 'adaptive_admission_active_cap_peak': scheduler_admission_active_cap_peak, 'adaptive_admission_guard_target_peak': scheduler_admission_guard_target_peak, 'timeseries_path': str(scheduler_timeseries_path), 'timeseries_row_count': scheduler_timeseries_rows_written, 'timeseries_heartbeat_seconds': scheduler_timeseries_heartbeat_seconds, 'snapshot_poll_seconds': root.ALL_METHOD_SCHEDULER_POLL_SECONDS, 'cpu_utilization_source': scheduler_cpu_source, 'cpu_utilization_samples': scheduler_cpu_samples_collected, 'cpu_utilization_pct_high_water': scheduler_cpu_utilization_pct_high_water}

    def _shutdown_parallel_executor(executor: root.Any, *, terminate_workers: bool) -> None:
        if terminate_workers:
            worker_map = getattr(executor, '_processes', None)
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
                        if process.is_alive() and hasattr(process, 'kill'):
                            process.kill()
                    except Exception:
                        continue
        shutdown_fn = getattr(executor, 'shutdown', None)
        if not callable(shutdown_fn):
            return
        try:
            shutdown_fn(wait=not terminate_workers, cancel_futures=terminate_workers)
        except TypeError:
            shutdown_fn(wait=not terminate_workers)
        except Exception:
            return

    def _latest_rows_by_config(rows: list[dict[str, root.Any]]) -> list[dict[str, root.Any]]:
        latest_by_index: dict[int, dict[str, root.Any]] = {}
        for row in rows:
            config_index = root._report_count(row.get('config_index'))
            latest_by_index[config_index] = row
        return [latest_by_index[index] for index in sorted(latest_by_index)]

    def _run_serial_variants(items: list[tuple[int, root.AllMethodVariant]], *, dashboard_tracking: bool=True) -> None:
        for config_index, variant in items:
            progress_label = root.format_task_counter('Running', config_index, max(1, total_variants), noun='config')
            if dashboard_tracking and dashboard is not None and (dashboard_source_index is not None):
                dashboard.start_config(source_index=dashboard_source_index, config_index=config_index, config_total=max(1, total_variants), config_slug=variant.slug)
            _emit_status(f'{progress_label}: {variant.slug}', color=root.typer.colors.CYAN)

            def _variant_progress(message: str) -> None:
                if progress_callback is None:
                    return
                if dashboard is None:
                    if root._is_structured_progress_message(message):
                        root._notify_progress_callback(progress_callback, message)
                        return
                    root._notify_progress_callback(progress_callback, f'{progress_label}: {variant.slug} | {message}')
                    return
                if root._is_structured_progress_message(message):
                    root._notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                root._notify_progress_callback(progress_callback, dashboard.render())
            row = root._run_all_method_prediction_once(gold_spans_path=gold_spans_path, source_file=source_file, variant=variant, config_index=config_index, total_variants=max(1, total_variants), root_output_dir=root_output_dir, scratch_root=scratch_root, processed_output_root=processed_output_root, overlap_threshold=overlap_threshold, force_source_match=force_source_match, max_concurrent_split_phases=effective_split_phase_slots, split_phase_gate_dir=split_phase_gate_dir, scheduler_events_dir=scheduler_events_dir, alignment_cache_dir=canonical_alignment_cache_dir, prediction_reuse_cache_dir=prediction_reuse_cache_dir, split_worker_cap_per_config=split_worker_cap_per_config, progress_callback=_variant_progress if progress_callback else None)
            variant_rows.append(row)
            success = str(row.get('status') or '').strip().lower() == 'ok'
            if dashboard_tracking and dashboard is not None and (dashboard_source_index is not None):
                dashboard.complete_config(source_index=dashboard_source_index, success=success, config_index=config_index)
            if success:
                if progress_callback is not None:
                    _emit_status(f'Completed {root.format_task_counter('', config_index, max(1, total_variants), noun='config')}: {variant.slug}')
            else:
                _emit_status(f'Failed {root.format_task_counter('', config_index, max(1, total_variants), noun='config')}: {row.get('error', 'unknown error')}', color=root.typer.colors.RED)

    def _run_parallel_variants(items: list[tuple[int, root.AllMethodVariant]], *, dashboard_tracking: bool=True) -> None:
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
        serial_by_limits = (len(items) <= 1 or effective_inflight_pipelines <= 1) and (not force_parallel_timeout)
        if serial_by_limits:
            config_executor_backends_seen.add('serial')
            _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
            return
        executor_backend = 'process'
        process_workers_available, process_worker_error = root._probe_all_method_process_pool_executor()
        if process_workers_available:
            picklable, picklable_error = root._probe_all_method_process_worker_picklable()
            if not picklable:
                process_workers_available = False
                process_worker_error = picklable_error
        process_worker_probe_available = bool(process_workers_available)
        process_worker_probe_error = str(process_worker_error).strip() if process_worker_error else None
        if not process_workers_available:
            detail = f' ({process_worker_error})' if isinstance(process_worker_error, str) and process_worker_error else ''
            if require_process_workers:
                raise RuntimeError(f'Process-based config concurrency is required, but runtime probe reported it unavailable{detail}.')
            _emit_status(f'Process-based config concurrency unavailable{detail}; using thread-based config concurrency.', color=root.typer.colors.YELLOW)
            executor_backend = 'thread'
        config_executor_backends_seen.add(str(executor_backend))
        pending_items = list(items)
        futures: dict[root.Any, tuple[int, root.AllMethodVariant, float]] = {}
        worker_limit = min(effective_inflight_pipelines, len(items))
        scheduler_base_target = min(total_variants, effective_split_phase_slots + effective_wing_backlog_target)
        try:
            executor = root._create_all_method_process_pool_executor(max_workers=worker_limit) if executor_backend == 'process' else root.ThreadPoolExecutor(max_workers=worker_limit)
        except (PermissionError, OSError) as exc:
            if executor_backend == 'process':
                if require_process_workers:
                    raise RuntimeError(f'Process-based config concurrency is required, but process executor startup failed: {exc}') from exc
                _emit_status(f'Process-based config concurrency unavailable ({exc}); using thread-based config concurrency.', color=root.typer.colors.YELLOW)
                executor_backend = 'thread'
                config_executor_backends_seen.add('thread')
                try:
                    executor = root.ThreadPoolExecutor(max_workers=worker_limit)
                except Exception as thread_exc:
                    _emit_status(f'Thread-based config concurrency unavailable ({thread_exc}); running single-config execution.', color=root.typer.colors.YELLOW)
                    config_executor_backends_seen.add('serial')
                    _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
                    return
            else:
                _emit_status(f'Thread-based config concurrency unavailable ({exc}); running single-config execution.', color=root.typer.colors.YELLOW)
                config_executor_backends_seen.add('serial')
                _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
                return

        def _record_completion(*, config_index: int, variant: root.AllMethodVariant, row: dict[str, root.Any]) -> None:
            variant_rows.append(row)
            success = str(row.get('status') or '').strip().lower() == 'ok'
            scheduler_phase_by_config.pop(config_index, None)
            scheduler_event_offsets.pop(config_index, None)
            if dashboard_tracking and dashboard is not None and (dashboard_source_index is not None):
                dashboard.complete_config(source_index=dashboard_source_index, success=success, config_index=config_index)
            if success:
                if progress_callback is not None:
                    _emit_status(f'Completed {root.format_task_counter('', config_index, max(1, total_variants), noun='config')}: {variant.slug}')
            else:
                _emit_status(f'Failed {root.format_task_counter('', config_index, max(1, total_variants), noun='config')}: {row.get('error', 'unknown error')}', color=root.typer.colors.RED)

        def _submit_next() -> bool:
            if not pending_items:
                return False
            config_index, variant = pending_items.pop(0)
            progress_label = root.format_task_counter('Running', config_index, max(1, total_variants), noun='config')
            if dashboard_tracking and dashboard is not None and (dashboard_source_index is not None):
                dashboard.start_config(source_index=dashboard_source_index, config_index=config_index, config_total=max(1, total_variants), config_slug=variant.slug)
            _emit_status(f'{progress_label}: {variant.slug}', color=root.typer.colors.CYAN)
            try:
                future = executor.submit(root._run_all_method_prediction_once, gold_spans_path=gold_spans_path, source_file=source_file, variant=variant, config_index=config_index, total_variants=max(1, total_variants), root_output_dir=root_output_dir, scratch_root=scratch_root, processed_output_root=processed_output_root, overlap_threshold=overlap_threshold, force_source_match=force_source_match, max_concurrent_split_phases=effective_split_phase_slots, split_phase_gate_dir=split_phase_gate_dir, scheduler_events_dir=scheduler_events_dir, alignment_cache_dir=canonical_alignment_cache_dir, prediction_reuse_cache_dir=prediction_reuse_cache_dir, split_worker_cap_per_config=split_worker_cap_per_config, progress_callback=None)
            except Exception as exc:
                row = root._all_method_failed_row(config_index=config_index, config_dir_name=root._all_method_config_dir_name(config_index, variant), variant=variant, error=f'Failed to submit benchmark config: {exc}')
                _record_completion(config_index=config_index, variant=variant, row=row)
                return True
            futures[future] = (config_index, variant, root.time.monotonic())
            scheduler_phase_by_config[config_index] = 'prep'
            scheduler_event_offsets[config_index] = 0
            return True

        def _refresh_admission_decision(*, counts: dict[str, int], pending_count: int) -> root._AllMethodSchedulerAdmissionDecision:
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
            decision = root._resolve_all_method_scheduler_admission(counts=counts, pending_count=pending_count, total_variants=max(1, total_variants), configured_inflight_pipelines=configured_inflight_pipelines, split_phase_slots=effective_split_phase_slots, wing_backlog_target=effective_wing_backlog_target, max_active_during_eval=max_active_during_eval, adaptive_overcommit_limit=adaptive_overcommit_limit, adaptive_max_guard_target=max(scheduler_base_target, adaptive_max_guard_target), smart_scheduler_enabled=scheduler_smart_enabled, cpu_utilization_pct=scheduler_cpu_utilization_pct_last)
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
            scheduler_admission_active_cap_peak = max(scheduler_admission_active_cap_peak, decision.active_cap)
            scheduler_admission_guard_target_peak = max(scheduler_admission_guard_target_peak, decision.guard_target)
            scheduler_admission_active_cap_current = decision.active_cap
            scheduler_admission_guard_target_current = decision.guard_target
            scheduler_admission_wing_target_current = decision.wing_target
            scheduler_admission_reason_current = decision.reason
            return decision
        try:
            while pending_items or futures:
                active_indices = {config_index for config_index, _variant, _submitted in futures.values()}
                counts = _tick_scheduler_metrics(active_indices=active_indices, pending_count=len(pending_items))
                if active_indices:
                    try:
                        _poll_scheduler_events(active_indices)
                    except Exception as exc:
                        if scheduler_smart_enabled:
                            scheduler_smart_enabled = False
                            _emit_status(f'Smart scheduler telemetry failed ({exc}); falling back to fixed queue refill.', color=root.typer.colors.YELLOW)
                counts = _compute_scheduler_counts({config_index for config_index, _variant, _submitted in futures.values()})
                if dashboard_tracking and dashboard is not None and (dashboard_source_index is not None):
                    for active_index in sorted(active_indices):
                        dashboard.set_config_phase(source_index=dashboard_source_index, config_index=active_index, phase=scheduler_phase_by_config.get(active_index, 'prep'))
                admission_decision = _refresh_admission_decision(counts=counts, pending_count=len(pending_items))
                _emit_scheduler_snapshot(counts=counts, pending_count=len(pending_items))
                while len(futures) < worker_limit and pending_items:
                    heavy_plus_wing = counts['heavy_active'] + counts['wing_backlog']
                    if counts['active'] >= admission_decision.active_cap:
                        break
                    if heavy_plus_wing >= admission_decision.guard_target and counts['active'] >= configured_inflight_pipelines:
                        break
                    submitted = _submit_next()
                    if not submitted:
                        break
                    counts = _compute_scheduler_counts({config_index for config_index, _variant, _submitted in futures.values()})
                    admission_decision = _refresh_admission_decision(counts=counts, pending_count=len(pending_items))
                    _emit_scheduler_snapshot(counts=counts, pending_count=len(pending_items))
                if not futures:
                    if pending_items:
                        root.time.sleep(root.ALL_METHOD_SCHEDULER_POLL_SECONDS)
                    continue
                done, _ = root.wait(list(futures.keys()), timeout=root.ALL_METHOD_SCHEDULER_POLL_SECONDS, return_when=root.FIRST_COMPLETED)
                for done_future in done:
                    config_index, variant, _submitted = futures.pop(done_future)
                    try:
                        row = done_future.result()
                    except Exception as exc:
                        row = root._all_method_failed_row(config_index=config_index, config_dir_name=root._all_method_config_dir_name(config_index, variant), variant=variant, error=f'Benchmark config worker failed: {exc}')
                    _record_completion(config_index=config_index, variant=variant, row=row)
                if effective_config_timeout_seconds is None or executor_backend != 'process':
                    continue
                timeout_threshold = float(max(1, effective_config_timeout_seconds))
                now = root.time.monotonic()
                timed_out: list[tuple[root.Any, int, root.AllMethodVariant, float]] = []
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
                    row = root._all_method_failed_row(config_index=config_index, config_dir_name=root._all_method_config_dir_name(config_index, variant), variant=variant, error=f'Config timed out after {int(timeout_threshold)}s (elapsed {elapsed_seconds:.1f}s).', elapsed_seconds=elapsed_seconds)
                    _record_completion(config_index=config_index, variant=variant, row=row)
                if futures:
                    requeued = sorted([(config_index, variant) for config_index, variant, _submitted in futures.values()], key=lambda item: item[0])
                    pending_items = requeued + pending_items
                    futures.clear()
                scheduler_smart_enabled = False
                _emit_status(f'Config timeout reached for {len(timed_out)} run(s); restarting process worker pool.', color=root.typer.colors.YELLOW)
                _shutdown_parallel_executor(executor, terminate_workers=True)
                try:
                    executor = root._create_all_method_process_pool_executor(max_workers=worker_limit)
                except (PermissionError, OSError) as exc:
                    if require_process_workers:
                        raise RuntimeError(f'Process-based config concurrency is required, but process pool restart failed after timeout: {exc}') from exc
                    _emit_status(f'Process-based config concurrency unavailable after timeout restart ({exc}); using thread-based config concurrency for remaining configs.', color=root.typer.colors.YELLOW)
                    executor_backend = 'thread'
                    config_executor_backends_seen.add('thread')
                    try:
                        executor = root.ThreadPoolExecutor(max_workers=worker_limit)
                    except Exception as thread_exc:
                        _emit_status(f'Thread-based config concurrency unavailable ({thread_exc}); running remaining configs as single-config execution.', color=root.typer.colors.YELLOW)
                        config_executor_backends_seen.add('serial')
                        _run_serial_variants(pending_items, dashboard_tracking=dashboard_tracking)
                        pending_items.clear()
                        futures.clear()
                        break
        finally:
            _shutdown_parallel_executor(executor, terminate_workers=False)
    _run_parallel_variants(indexed_variants, dashboard_tracking=True)
    variant_rows = _latest_rows_by_config(variant_rows)
    initial_failed_indices = [root._report_count(row.get('config_index')) for row in variant_rows if str(row.get('status') or '').strip().lower() != 'ok']
    retry_passes_executed = 0
    retry_recovered_configs = 0
    if effective_retry_failed_configs > 0 and initial_failed_indices:
        variant_by_index = {config_index: variant for config_index, variant in indexed_variants}
        remaining_failed_indices = sorted(set(initial_failed_indices))
        for retry_pass in range(1, effective_retry_failed_configs + 1):
            if not remaining_failed_indices:
                break
            retry_items = [(config_index, variant_by_index[config_index]) for config_index in remaining_failed_indices if config_index in variant_by_index]
            if not retry_items:
                break
            retry_passes_executed += 1
            _emit_status(f'Retry pass {retry_pass}/{effective_retry_failed_configs}: rerunning {len(retry_items)} failed config(s).', color=root.typer.colors.YELLOW)
            prior_failed = set(remaining_failed_indices)
            _run_parallel_variants(retry_items, dashboard_tracking=False)
            variant_rows = _latest_rows_by_config(variant_rows)
            remaining_failed_indices = sorted({root._report_count(row.get('config_index')) for row in variant_rows if str(row.get('status') or '').strip().lower() != 'ok'})
            recovered_this_pass = len(prior_failed - set(remaining_failed_indices))
            retry_recovered_configs += max(0, recovered_this_pass)
            if recovered_this_pass > 0:
                _emit_status(f'Retry pass {retry_pass} recovered {recovered_this_pass} config(s).', color=root.typer.colors.CYAN)
    _tick_scheduler_metrics(active_indices=set(), pending_count=0)
    _emit_scheduler_snapshot(counts=_compute_scheduler_counts(set()), pending_count=0, force_timeseries=True)
    scheduler_summary = _finalize_scheduler_metrics()
    scheduler_summary['config_timeout_seconds'] = effective_config_timeout_seconds
    scheduler_summary['failed_retry_limit'] = effective_retry_failed_configs
    scheduler_summary['retry_passes_executed'] = retry_passes_executed
    scheduler_summary['retry_recovered_configs'] = retry_recovered_configs
    variant_rows = _latest_rows_by_config(variant_rows)
    prediction_success_rows = [dict(row) for row in variant_rows if str(row.get('status') or '').strip().lower() == 'ok']
    failed_rows: list[dict[str, root.Any]] = [dict(row) for row in variant_rows if str(row.get('status') or '').strip().lower() != 'ok']
    prediction_reuse_summary = root._all_method_prediction_reuse_summary(prediction_success_rows)
    successful_rows: list[dict[str, root.Any]] = []
    signature_candidate_rows: list[dict[str, root.Any]] = []
    evaluation_signatures_unique = 0
    evaluation_runs_executed = 0
    evaluation_results_reused_in_run = 0
    evaluation_results_reused_cross_run = 0
    eval_signature_cache_dir = root._resolve_all_method_eval_signature_cache_dir(root_output_dir=root_output_dir, alignment_cache_dir=canonical_alignment_cache_dir)
    for row in prediction_success_rows:
        prediction_record_path = root._resolve_all_method_prediction_record_path(root_output_dir=root_output_dir, row=row)
        if prediction_record_path is None or not prediction_record_path.exists() or (not prediction_record_path.is_file()):
            failed_row = dict(row)
            failed_row['status'] = 'failed'
            failed_row['error'] = 'Prediction record path is missing for signature build.'
            failed_row['evaluation_result_source'] = 'failed'
            failed_rows.append(failed_row)
            continue
        sequence_matcher = str(row.get('benchmark_sequence_matcher') or '').strip() or 'dmp'
        try:
            eval_signature = root._build_all_method_eval_signature(gold_spans_path=gold_spans_path, prediction_record_path=prediction_record_path, eval_mode=root.BENCHMARK_EVAL_MODE_CANONICAL_TEXT, sequence_matcher=sequence_matcher)
        except Exception as exc:
            failed_row = dict(row)
            failed_row['status'] = 'failed'
            failed_row['error'] = f'Failed to build evaluation signature: {exc}'
            failed_row['evaluation_result_source'] = 'failed'
            failed_rows.append(failed_row)
            continue
        row['eval_signature'] = eval_signature
        row['benchmark_sequence_matcher'] = sequence_matcher
        signature_candidate_rows.append(row)
    grouped_by_signature = root._group_all_method_rows_by_eval_signature(signature_candidate_rows)
    evaluation_signatures_unique = len(grouped_by_signature)
    grouped_items = sorted(grouped_by_signature.items(), key=lambda item: min((root._report_count(row.get('config_index')) for row in item[1])))
    for signature_index, (eval_signature, group_rows) in enumerate(grouped_items, start=1):
        if not group_rows:
            continue
        ordered_group = sorted(group_rows, key=lambda row: root._report_count(row.get('config_index')))
        representative_row = ordered_group[0]
        representative_config_dir = str(representative_row.get('config_dir') or '').strip()
        if not representative_config_dir:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row['status'] = 'failed'
                failed_row['error'] = 'Representative config directory is missing.'
                failed_row['evaluation_result_source'] = 'failed'
                failed_rows.append(failed_row)
            continue
        representative_eval_output_dir = root_output_dir / representative_config_dir
        representative_processed_output_dir = processed_output_root / representative_config_dir
        representative_prediction_record = root._resolve_all_method_prediction_record_path(root_output_dir=root_output_dir, row=representative_row)
        if representative_prediction_record is None:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row['status'] = 'failed'
                failed_row['error'] = 'Representative prediction record is missing.'
                failed_row['evaluation_result_source'] = 'failed'
                failed_rows.append(failed_row)
            continue
        sequence_matcher = str(representative_row.get('benchmark_sequence_matcher') or '').strip()
        if not sequence_matcher:
            sequence_matcher = 'dmp'
        cache_path = eval_signature_cache_dir / f'{eval_signature}.json'
        cache_entry = root._load_all_method_eval_signature_cache_entry(cache_path=cache_path, expected_signature=eval_signature)
        evaluation_result_source_for_group = 'executed'
        evaluation_summary: dict[str, root.Any]
        if cache_entry is not None:
            cached_report = cache_entry.get('report')
            if not isinstance(cached_report, dict):
                cached_report = {}
            cached_md = str(cache_entry.get('report_md') or '')
            eval_report_json_path, eval_report_md_path = root._materialize_all_method_cached_eval_outputs(eval_output_dir=representative_eval_output_dir, report_payload=cached_report, report_md_text=cached_md)
            metric_bundle = root._benchmark_report_metric_bundle(cached_report)
            evaluation_summary = {'status': 'ok', 'error': '', **metric_bundle, 'timing': root._normalize_timing_payload(cached_report.get('timing')), 'report': cached_report, 'report_md_text': cached_md, 'eval_report_json_path': eval_report_json_path, 'eval_report_md_path': eval_report_md_path, 'duration_seconds': 0.0}
            evaluation_result_source_for_group = 'reused_cross_run'
            evaluation_results_reused_cross_run += len(ordered_group)
        else:
            _emit_status(f'Evaluating signature {signature_index}/{max(1, evaluation_signatures_unique)} (group size {len(ordered_group)}).', color=root.typer.colors.CYAN)
            evaluation_summary = root._run_all_method_evaluate_prediction_record_once(gold_spans_path=gold_spans_path, source_file=source_file, prediction_record_path=representative_prediction_record, eval_output_dir=representative_eval_output_dir, processed_output_dir=representative_processed_output_dir, sequence_matcher=sequence_matcher, epub_extractor=root._row_dimension_str(representative_row, 'epub_extractor'), overlap_threshold=overlap_threshold, force_source_match=force_source_match, alignment_cache_dir=canonical_alignment_cache_dir, progress_callback=None)
            if str(evaluation_summary.get('status') or '').strip().lower() == 'ok':
                evaluation_runs_executed += 1
                if len(ordered_group) > 1:
                    evaluation_results_reused_in_run += len(ordered_group) - 1
                cached_payload = {'schema_version': root.ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION, 'created_at': root.dt.datetime.now().isoformat(timespec='seconds'), 'eval_signature': eval_signature, 'eval_mode': root.BENCHMARK_EVAL_MODE_CANONICAL_TEXT, 'sequence_matcher': sequence_matcher, 'source_file': str(source_file), 'gold_spans_path': str(gold_spans_path), 'report': evaluation_summary.get('report'), 'report_md': evaluation_summary.get('report_md_text')}
                try:
                    root._write_all_method_eval_signature_cache_entry(cache_path=cache_path, payload=cached_payload)
                except Exception as exc:
                    root.logger.warning('Ignoring eval-signature cache write failure for %s: %s', cache_path, exc)
        if str(evaluation_summary.get('status') or '').strip().lower() != 'ok':
            error_text = str(evaluation_summary.get('error') or 'Evaluation failed.')
            for row in ordered_group:
                failed_row = dict(row)
                failed_row['status'] = 'failed'
                failed_row['error'] = error_text
                failed_row['evaluation_result_source'] = 'failed'
                failed_row['evaluation_representative_config_dir'] = representative_config_dir
                failed_row['eval_signature'] = eval_signature
                failed_rows.append(failed_row)
            continue
        summary_timing = root._normalize_timing_payload(evaluation_summary.get('timing'))
        summary_evaluation_seconds = root._report_optional_metric(summary_timing.get('evaluation_seconds'))
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = root._report_optional_metric(summary_timing.get('total_seconds'))
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = root._report_optional_metric(evaluation_summary.get('duration_seconds'))
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = 0.0
        summary_eval_wall_seconds = max(0.0, root._report_metric(evaluation_summary.get('duration_seconds')))
        summary_report_json_path = root.Path(str(evaluation_summary.get('eval_report_json_path') or ''))
        summary_report_md_path = root.Path(str(evaluation_summary.get('eval_report_md_path') or ''))
        alignment_guardrail_fields = root._all_method_extract_alignment_guardrail_fields(root.cast(dict[str, root.Any] | None, evaluation_summary.get('report')))
        for row in ordered_group:
            result_row = dict(row)
            is_representative = root._report_count(result_row.get('config_index')) == root._report_count(representative_row.get('config_index'))
            row_result_source = 'executed'
            if evaluation_result_source_for_group == 'reused_cross_run':
                row_result_source = 'reused_cross_run'
            elif not is_representative:
                row_result_source = 'reused_in_run'
            row_timing = root._normalize_timing_payload(result_row.get('timing'))
            prediction_total_seconds = root._report_optional_metric(row_timing.get('total_seconds'))
            if prediction_total_seconds is None:
                prediction_total_seconds = root._report_optional_metric(result_row.get('duration_seconds'))
            if prediction_total_seconds is None:
                prediction_total_seconds = 0.0
            row_eval_seconds = summary_evaluation_seconds if row_result_source == 'executed' else 0.0
            row_eval_wall = summary_eval_wall_seconds if row_result_source == 'executed' else 0.0
            row_total_seconds = max(0.0, prediction_total_seconds + row_eval_seconds)
            row_timing = root._timing_with_updates(row_timing, evaluation_seconds=row_eval_seconds, total_seconds=row_total_seconds, checkpoints={'all_method_eval_wall_seconds': row_eval_wall, 'all_method_eval_reused_in_run': 1.0 if row_result_source == 'reused_in_run' else 0.0, 'all_method_eval_reused_cross_run': 1.0 if row_result_source == 'reused_cross_run' else 0.0})
            result_row['status'] = 'ok'
            result_row['error'] = ''
            result_row['precision'] = root._report_metric(evaluation_summary.get('precision'))
            result_row['recall'] = root._report_metric(evaluation_summary.get('recall'))
            result_row['f1'] = root._report_metric(evaluation_summary.get('f1'))
            result_row['practical_precision'] = root._report_metric(evaluation_summary.get('practical_precision'))
            result_row['practical_recall'] = root._report_metric(evaluation_summary.get('practical_recall'))
            result_row['practical_f1'] = root._report_metric(evaluation_summary.get('practical_f1'))
            result_row.update(alignment_guardrail_fields)
            result_row['eval_signature'] = eval_signature
            result_row['evaluation_result_source'] = row_result_source
            result_row['evaluation_representative_config_dir'] = representative_config_dir
            result_row['duration_seconds'] = row_total_seconds
            result_row['timing'] = row_timing
            result_row['eval_report_json'] = root._path_for_manifest(root_output_dir, summary_report_json_path)
            result_row['eval_report_md'] = root._path_for_manifest(root_output_dir, summary_report_md_path)
            successful_rows.append(result_row)
    failed_rows.sort(key=lambda row: root._report_count(row.get('config_index')))
    successful_rows.sort(key=lambda row: (root._report_metric(row.get('f1')), root._report_metric(row.get('practical_f1')), root._report_metric(row.get('precision')), root._report_metric(row.get('recall'))), reverse=True)
    for rank, row in enumerate(successful_rows, start=1):
        row['rank'] = rank
    matcher_guardrails = root._all_method_build_matcher_guardrails(successful_rows)
    scheduler_summary['matcher_guardrails'] = matcher_guardrails
    for warning in matcher_guardrails.get('warnings', []):
        _emit_status(f'Matcher guardrail warning: {warning}', color=root.typer.colors.YELLOW)
    successful_timing: list[tuple[dict[str, root.Any], float]] = []
    for row in successful_rows:
        row_timing = root._normalize_timing_payload(row.get('timing'))
        row_total_seconds = root._report_optional_metric(row_timing.get('total_seconds'))
        if row_total_seconds is None:
            row_total_seconds = root._report_optional_metric(row.get('duration_seconds'))
        if row_total_seconds is None:
            continue
        row['timing'] = root._timing_with_updates(row_timing, total_seconds=row_total_seconds)
        successful_timing.append((row, row_total_seconds))
    source_wall_seconds = max(0.0, root.time.monotonic() - source_started)
    total_config_seconds = sum((seconds for _row, seconds in successful_timing))
    average_config_seconds = total_config_seconds / len(successful_timing) if successful_timing else None
    median_config_seconds = root._median_metric([seconds for _row, seconds in successful_timing])
    slowest_config_row = max(successful_timing, key=lambda item: item[1])[0] if successful_timing else None
    slowest_config_seconds = max((seconds for _row, seconds in successful_timing)) if successful_timing else None
    winner = successful_rows[0] if successful_rows else None
    final_rows = successful_rows + failed_rows
    report_payload: dict[str, root.Any] = {'created_at': root.dt.datetime.now().isoformat(timespec='seconds'), 'source_file': str(source_file), 'gold_spans_path': str(gold_spans_path), 'eval_mode': root.BENCHMARK_EVAL_MODE_CANONICAL_TEXT, 'scheduler_scope': 'per_source', 'variant_count': total_variants, 'successful_variants': len(successful_rows), 'failed_variants': len(failed_rows), 'evaluation_signatures_unique': evaluation_signatures_unique, 'evaluation_runs_executed': evaluation_runs_executed, 'evaluation_results_reused_in_run': evaluation_results_reused_in_run, 'evaluation_results_reused_cross_run': evaluation_results_reused_cross_run, 'prediction_signatures_unique': root._report_count(prediction_reuse_summary.get('prediction_signatures_unique')), 'prediction_runs_executed': root._report_count(prediction_reuse_summary.get('prediction_runs_executed')), 'prediction_results_reused_in_run': root._report_count(prediction_reuse_summary.get('prediction_results_reused_in_run')), 'prediction_results_reused_cross_run': root._report_count(prediction_reuse_summary.get('prediction_results_reused_cross_run')), 'split_convert_input_groups': root._report_count(prediction_reuse_summary.get('split_convert_input_groups')), 'split_convert_reuse_candidates': root._report_count(prediction_reuse_summary.get('split_convert_reuse_candidates')), 'split_convert_reuse_safe_candidates': root._report_count(prediction_reuse_summary.get('split_convert_reuse_safe_candidates')), 'split_convert_reuse_blocked_by_prediction_variance': root._report_count(prediction_reuse_summary.get('split_convert_reuse_blocked_by_prediction_variance')), 'prediction_reuse_key_schema_version': root.ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION, 'split_convert_input_key_schema_version': root.ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION, 'evaluation_signature_cache_dir': str(eval_signature_cache_dir), 'retry_failed_configs_requested': effective_retry_failed_configs, 'retry_passes_executed': retry_passes_executed, 'retry_recovered_configs': retry_recovered_configs, 'include_codex_farm_requested': include_codex_farm_requested, 'include_codex_farm_effective': include_codex_farm_effective, 'prediction_reuse_cache_dir': str(prediction_reuse_cache_dir), 'executor_resolution': {'process_workers_required': bool(require_process_workers), 'process_worker_probe_available': process_worker_probe_available, 'process_worker_probe_error': process_worker_probe_error, 'config_executor_backends_seen': sorted(config_executor_backends_seen)}, 'timing_summary': {'source_wall_seconds': source_wall_seconds, 'config_total_seconds': total_config_seconds, 'config_average_seconds': average_config_seconds, 'config_median_seconds': median_config_seconds, 'slowest_config_dir': str(slowest_config_row.get('config_dir')) if isinstance(slowest_config_row, dict) else None, 'slowest_config_seconds': slowest_config_seconds}, 'scheduler': scheduler_summary, 'variants': final_rows, 'winner_by_f1': winner}
    report_json_path = root_output_dir / 'all_method_benchmark_report.json'
    report_json_path.write_text(root.json.dumps(report_payload, indent=2, sort_keys=True), encoding='utf-8')
    report_md_path = root_output_dir / 'all_method_benchmark_report.md'
    report_md_path.write_text(root._render_all_method_report_md(report_payload), encoding='utf-8')
    if refresh_dashboard_after_source:
        history_csv_path = root.history_csv_for_output(processed_output_root / root._DASHBOARD_REFRESH_SENTINEL_DIRNAME)
        resolved_dashboard_output_root = dashboard_output_root.expanduser() if dashboard_output_root is not None else None
        root._refresh_dashboard_after_history_write(csv_path=history_csv_path, output_root=resolved_dashboard_output_root, golden_root=golden_root, dashboard_out_dir=root.history_root_for_output(resolved_dashboard_output_root) / 'dashboard' if resolved_dashboard_output_root is not None else None, reason='all-method benchmark source batch append')
    completion_color = root.typer.colors.GREEN if len(failed_rows) == 0 else root.typer.colors.YELLOW
    _emit_status(f'All method benchmark complete: {len(successful_rows)}/{total_variants} configs evaluated successfully.', color=completion_color)
    if progress_callback is None:
        if successful_rows:
            root.typer.secho('Top configurations by strict F1:', fg=root.typer.colors.CYAN)
            for row in successful_rows[:3]:
                root.typer.echo(f'  {row.get('rank')}) {row.get('config_dir')} p={root._report_metric(row.get('precision')):.3f} r={root._report_metric(row.get('recall')):.3f} f1={root._report_metric(row.get('f1')):.3f}')
        root.typer.secho(f'Report: {report_md_path}', fg=root.typer.colors.CYAN)
    return report_md_path
