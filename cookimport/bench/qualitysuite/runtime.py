from __future__ import annotations

from cookimport.bench.qualitysuite.shared import *  # noqa: F401,F403
from cookimport.bench.qualitysuite.environment import *  # noqa: F401,F403
from cookimport.bench.qualitysuite.persistence import *  # noqa: F401,F403
from cookimport.bench.qualitysuite.planning import *  # noqa: F401,F403
from cookimport.bench.qualitysuite.summary import *  # noqa: F401,F403
from cookimport.bench.qualitysuite.worker_cli import _run_single_experiment_via_subprocess
from cookimport.bench.qualitysuite import environment as _environment
from cookimport.bench.qualitysuite import persistence as _persistence
from cookimport.bench.qualitysuite import planning as _planning
from cookimport.bench.qualitysuite import shared as _shared
from cookimport.bench.qualitysuite import summary as _summary

for _module in (_shared, _environment, _persistence, _planning, _summary):
    globals().update(
        {name: getattr(_module, name) for name in dir(_module) if not name.startswith("__")}
    )


def run_quality_suite(
    suite: QualitySuite,
    out_dir: Path,
    *,
    experiments_file: Path,
    base_run_settings_file: Path | None = None,
    search_strategy: str = "exhaustive",
    race_probe_targets: int = 2,
    race_mid_targets: int = 4,
    race_keep_ratio: float = 0.35,
    race_finalists: int = 64,
    include_deterministic_sweeps_requested: bool = False,
    include_codex_farm_requested: bool = False,
    codex_farm_confirmed: bool = False,
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | None = None,
    max_parallel_experiments: int | None = None,
    require_process_workers: bool = False,
    resume_run_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    search_strategy_clean = str(search_strategy or "exhaustive").strip().lower()
    if search_strategy_clean not in _SUPPORTED_SEARCH_STRATEGIES:
        supported = ", ".join(sorted(_SUPPORTED_SEARCH_STRATEGIES))
        raise ValueError(
            f"Unsupported quality search strategy {search_strategy!r}. Supported: {supported}."
        )
    race_probe_targets = max(1, int(race_probe_targets))
    race_mid_targets = max(race_probe_targets, int(race_mid_targets))
    race_keep_ratio = max(0.01, min(1.0, float(race_keep_ratio)))
    race_finalists = max(1, int(race_finalists))
    if max_parallel_experiments is not None:
        max_parallel_experiments = max(1, int(max_parallel_experiments))
    if include_codex_farm_requested:
        raise ValueError(
            "QualitySuite forbids Codex Farm permutations. "
            "Re-run without include_codex_farm_requested."
        )

    selected_targets = _resolve_selected_targets(suite)
    if not selected_targets:
        raise ValueError("Quality suite selected_target_ids resolved to zero targets.")

    experiment_payload = _load_experiment_file(experiments_file)
    base_settings_payload = _resolve_base_run_settings_payload(
        experiments_file=experiments_file,
        experiment_payload=experiment_payload,
        base_run_settings_file=base_run_settings_file,
    )
    if codex_farm_model is not None:
        base_settings_payload["codex_farm_model"] = str(codex_farm_model).strip() or None
    if codex_farm_reasoning_effort is not None:
        base_settings_payload["codex_farm_reasoning_effort"] = (
            str(codex_farm_reasoning_effort).strip().lower() or None
        )
    all_method_runtime_base = _derive_all_method_runtime_base(base_settings_payload)
    if isinstance(experiment_payload, _ExperimentFileV2):
        all_method_runtime_base.update(dict(experiment_payload.all_method_runtime))
    expanded_experiments = _expand_experiments(experiment_payload)
    resolved_experiments = _resolve_experiments(
        experiments=expanded_experiments,
        base_payload=base_settings_payload,
        all_method_runtime_base=all_method_runtime_base,
    )
    total_experiments = len(resolved_experiments)
    (
        max_parallel_experiments_effective,
        max_parallel_experiments_mode,
        cpu_count,
        auto_parallel_experiment_ceiling,
        auto_parallel_experiment_ceiling_source,
    ) = _resolve_experiment_parallelism_cap(
        requested=max_parallel_experiments,
        total_experiments=total_experiments,
    )
    resolved_experiments, wsl_guard_metadata = _apply_wsl_quality_safety_guard(
        experiments=resolved_experiments,
        max_parallel_experiments_effective=max_parallel_experiments_effective,
        cpu_count=cpu_count,
    )
    live_eta_poll_seconds = _resolve_quality_live_eta_poll_seconds()

    progress_lock = threading.Lock()

    def _thread_safe_progress(message: str) -> None:
        if progress_callback is None:
            return
        with progress_lock:
            progress_callback(message)

    progress_reporter: ProgressCallback | None = (
        _thread_safe_progress if progress_callback is not None else None
    )

    if resume_run_dir is not None:
        run_root = Path(resume_run_dir).expanduser()
        if not run_root.exists() or not run_root.is_dir():
            raise ValueError(
                f"--resume-run-dir must point to an existing quality run directory: {run_root}"
            )
        run_timestamp = (
            _resolve_resume_run_timestamp(run_root=run_root)
            or str(run_root.name or "").strip()
            or dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        )
    else:
        run_timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        run_root = out_dir / run_timestamp
    run_root.mkdir(parents=True, exist_ok=True)
    if resume_run_dir is not None:
        _validate_resume_run_compatibility(
            run_root=run_root,
            experiments=resolved_experiments,
        )
    canonical_alignment_cache_root = _resolve_quality_alignment_cache_root(
        out_dir=out_dir
    )
    prediction_reuse_cache_root = _resolve_quality_prediction_reuse_cache_root(
        out_dir=out_dir
    )

    suite_payload = suite.model_dump()
    suite_payload["target_count_total"] = len(suite.targets)
    suite_payload["target_count_selected"] = len(selected_targets)
    suite_payload["targets"] = [target.model_dump() for target in selected_targets]
    (run_root / "suite_resolved.json").write_text(
        json.dumps(suite_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    resolved_payload = {
        "schema_version": _SUPPORTED_EXPERIMENT_SCHEMA_VERSION,
        "input_schema_version": int(getattr(experiment_payload, "schema_version", 1)),
        "generated_at": run_timestamp,
        "source_file": str(experiments_file),
        "base_run_settings_file": str(base_run_settings_file)
        if base_run_settings_file is not None
        else experiment_payload.base_run_settings_file,
        "canonical_alignment_cache_root": str(canonical_alignment_cache_root),
        "prediction_reuse_cache_root": str(prediction_reuse_cache_root),
        "search_strategy": search_strategy_clean,
        "race": {
            "probe_targets": race_probe_targets,
            "mid_targets": race_mid_targets,
            "keep_ratio": race_keep_ratio,
            "finalists": race_finalists,
        },
        "all_method_runtime_base": dict(all_method_runtime_base),
        "include_deterministic_sweeps_requested": bool(
            include_deterministic_sweeps_requested
        ),
        "include_codex_farm_requested": bool(include_codex_farm_requested),
        "include_codex_farm_confirmed": bool(codex_farm_confirmed),
        "max_parallel_experiments_requested": max_parallel_experiments
        if max_parallel_experiments is not None
        else "auto",
        "max_parallel_experiments_mode": max_parallel_experiments_mode,
        "max_parallel_experiments_effective": max_parallel_experiments_effective,
        "max_parallel_experiments_cpu_count": cpu_count,
        "max_parallel_experiments_adaptive": max_parallel_experiments_mode == "auto",
        "max_parallel_experiments_auto_ceiling": auto_parallel_experiment_ceiling,
        "max_parallel_experiments_auto_ceiling_source": auto_parallel_experiment_ceiling_source,
        "max_parallel_experiments_auto_ceiling_env": _QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS_ENV,
        "quality_live_eta_poll_seconds": live_eta_poll_seconds,
        "quality_live_eta_poll_seconds_env": _QUALITY_LIVE_ETA_POLL_SECONDS_ENV,
        "wsl_detected": bool(wsl_guard_metadata.get("wsl_detected")),
        "wsl_safety_guard_applied": bool(
            wsl_guard_metadata.get("wsl_safety_guard_applied")
        ),
        "wsl_safety_guard_reason": str(
            wsl_guard_metadata.get("wsl_safety_guard_reason") or ""
        ),
        "wsl_safety_guard_worker_cap": wsl_guard_metadata.get(
            "wsl_safety_guard_worker_cap"
        ),
        "wsl_safety_guard_adjusted_experiments": _coerce_int(
            wsl_guard_metadata.get("wsl_safety_guard_adjusted_experiments"),
            minimum=0,
        ),
        "wsl_safety_guard_disable_env": _QUALITY_WSL_SAFETY_GUARD_DISABLE_ENV,
        "resume_requested": bool(resume_run_dir is not None),
        "resume_run_dir": str(run_root) if resume_run_dir is not None else None,
        "experiments": [
            {
                "id": item.id,
                "run_settings_patch": item.run_settings_patch,
                "run_settings": item.run_settings.to_run_config_dict(),
                "run_settings_summary": item.run_settings.summary(),
                "run_settings_hash": item.run_settings.stable_hash(),
                "requested_run_settings": (
                    item.requested_run_settings.to_run_config_dict()
                ),
                "requested_run_settings_summary": item.requested_run_settings.summary(),
                "requested_run_settings_hash": item.requested_run_settings.stable_hash(),
                "all_method_runtime_patch": item.all_method_runtime_patch,
                "all_method_runtime": item.all_method_runtime,
            }
            for item in resolved_experiments
        ],
    }

    import cookimport.cli as cli

    include_codex_effective, _codex_warning = cli._resolve_all_method_codex_choice(
        include_codex_farm_requested
    )
    process_worker_probe_available, process_worker_probe_error = (
        cli._probe_all_method_process_pool_executor()
    )
    experiment_executor_mode, experiment_executor_reason = (
        _resolve_quality_experiment_executor_mode(
            max_parallel_experiments_effective=max_parallel_experiments_effective
        )
    )
    include_markdown_extractors = cli._resolve_all_method_markdown_extractors_choice()
    resolved_payload["include_codex_farm_effective"] = bool(include_codex_effective)
    resolved_payload["include_markdown_extractors_effective"] = bool(
        include_markdown_extractors
    )
    resolved_payload["require_process_workers"] = bool(require_process_workers)
    resolved_payload["process_worker_probe_available"] = bool(
        process_worker_probe_available
    )
    resolved_payload["process_worker_probe_error"] = (
        str(process_worker_probe_error).strip() if process_worker_probe_error else None
    )
    resolved_payload["experiment_executor_mode"] = experiment_executor_mode
    resolved_payload["experiment_executor_reason"] = experiment_executor_reason
    resolved_payload["experiment_executor_mode_env"] = _QUALITY_EXPERIMENT_EXECUTOR_MODE_ENV
    resolved_payload["prediction_reuse_cache_root_env"] = (
        _ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV
    )
    if _codex_warning is not None:
        resolved_payload["include_codex_farm_warning"] = str(_codex_warning)
    (run_root / "experiments_resolved.json").write_text(
        json.dumps(resolved_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    def _run_resolved_experiment(
        *,
        experiment: _ResolvedExperiment,
    ) -> QualityExperimentResult:
        experiment_root = run_root / "experiments" / experiment.id
        experiment_root.mkdir(parents=True, exist_ok=True)
        try:
            return _run_single_experiment(
                experiment_id=experiment.id,
                suite_targets=selected_targets,
                run_root=run_root,
                experiment_root=experiment_root,
                run_settings=experiment.run_settings,
                all_method_runtime=experiment.all_method_runtime,
                include_markdown_extractors=include_markdown_extractors,
                include_codex_farm_requested=include_codex_farm_requested,
                include_codex_effective=include_codex_effective,
                canonical_alignment_cache_root=canonical_alignment_cache_root,
                prediction_reuse_cache_root=prediction_reuse_cache_root,
                search_strategy=search_strategy_clean,
                race_probe_targets=race_probe_targets,
                race_mid_targets=race_mid_targets,
                race_keep_ratio=race_keep_ratio,
                race_finalists=race_finalists,
                include_deterministic_sweeps=include_deterministic_sweeps_requested,
                require_process_workers=bool(require_process_workers),
                progress_callback=progress_reporter,
            )
        except Exception as exc:  # noqa: BLE001
            if require_process_workers:
                raise
            return QualityExperimentResult(
                id=experiment.id,
                status="failed",
                error=str(exc),
                run_settings_hash=experiment.run_settings.stable_hash(),
                run_settings_summary=experiment.run_settings.summary(),
            )

    def _dispatch_resolved_experiment(
        *,
        experiment: _ResolvedExperiment,
    ) -> QualityExperimentResult:
        experiment_root = run_root / "experiments" / experiment.id
        experiment_root.mkdir(parents=True, exist_ok=True)
        if experiment_executor_mode == "subprocess":
            result = _run_single_experiment_via_subprocess(
                experiment=experiment,
                suite_targets=selected_targets,
                run_root=run_root,
                experiment_root=experiment_root,
                include_markdown_extractors=include_markdown_extractors,
                include_codex_farm_requested=include_codex_farm_requested,
                include_codex_effective=include_codex_effective,
                canonical_alignment_cache_root=canonical_alignment_cache_root,
                prediction_reuse_cache_root=prediction_reuse_cache_root,
                search_strategy=search_strategy_clean,
                race_probe_targets=race_probe_targets,
                race_mid_targets=race_mid_targets,
                race_keep_ratio=race_keep_ratio,
                race_finalists=race_finalists,
                include_deterministic_sweeps=include_deterministic_sweeps_requested,
                require_process_workers=bool(require_process_workers),
            )
            if require_process_workers and result.status != "ok":
                detail = str(result.error or "unknown error").strip() or "unknown error"
                raise RuntimeError(
                    "Process-worker-required quality run failed in subprocess executor: "
                    f"{experiment.id}: {detail}"
                )
            return result
        return _run_resolved_experiment(experiment=experiment)

    results_by_index: list[QualityExperimentResult | None] = [None] * total_experiments
    if resume_run_dir is not None:
        for position, experiment in enumerate(resolved_experiments):
            resumed_result = _load_quality_experiment_result_snapshot(
                experiment=experiment,
                run_root=run_root,
            )
            if resumed_result is None:
                continue
            results_by_index[position] = resumed_result

    resumed_completed_count = sum(result is not None for result in results_by_index)
    if resumed_completed_count > 0:
        _notify_progress(
            progress_reporter,
            (
                "Quality suite resume: "
                f"reusing {resumed_completed_count}/{total_experiments} completed tasks "
                f"from {run_root}"
            ),
        )

    def _store_result_and_checkpoint(
        *,
        index: int,
        result: QualityExperimentResult,
    ) -> None:
        position = index - 1
        results_by_index[position] = result
        experiment = resolved_experiments[position]
        experiment_root = run_root / "experiments" / experiment.id
        _write_quality_experiment_result_snapshot(
            experiment_root=experiment_root,
            result=result,
        )
        _write_quality_run_checkpoint(
            run_root=run_root,
            suite=suite,
            run_timestamp=run_timestamp,
            experiments=resolved_experiments,
            results_by_index=results_by_index,
        )

    _write_quality_run_checkpoint(
        run_root=run_root,
        suite=suite,
        run_timestamp=run_timestamp,
        experiments=resolved_experiments,
        results_by_index=results_by_index,
    )

    if max_parallel_experiments_effective <= 1:
        completed = resumed_completed_count
        for index, experiment in enumerate(resolved_experiments, start=1):
            position = index - 1
            if results_by_index[position] is not None:
                _notify_progress(
                    progress_reporter,
                    (
                        f"{format_task_counter('Quality suite resume', index, total_experiments, noun='task')}: "
                        f"{experiment.id}"
                    ),
                )
                continue
            _notify_progress(
                progress_reporter,
                (
                    f"{format_task_counter('Quality suite', index, total_experiments, noun='task')}: "
                    f"{experiment.id}"
                ),
            )
            result = _dispatch_resolved_experiment(
                experiment=experiment,
            )
            completed += 1
            _store_result_and_checkpoint(index=index, result=result)
            _notify_progress(
                progress_reporter,
                (
                    f"{format_task_counter('Quality suite complete', completed, total_experiments, noun='task')}: "
                    f"{result.id}"
                ),
            )
    else:
        _notify_progress(
            progress_reporter,
            (
                "Quality suite parallel dispatch: "
                f"mode={max_parallel_experiments_mode} "
                f"executor={experiment_executor_mode} "
                f"workers_cap={max_parallel_experiments_effective} "
                f"tasks={total_experiments}"
            ),
        )
        with ThreadPoolExecutor(
            max_workers=max_parallel_experiments_effective,
            thread_name_prefix="quality-exp",
        ) as executor:
            future_to_index: dict[Any, int] = {}
            pending_entries = [
                (index, experiment)
                for index, experiment in enumerate(resolved_experiments, start=1)
                if results_by_index[index - 1] is None
            ]
            next_pending_index = 0
            if max_parallel_experiments_mode == "auto":
                initial_load_ratio = _safe_system_load_ratio_per_cpu()
                dynamic_worker_target = _desired_experiment_parallel_workers(
                    workers_cap=max_parallel_experiments_effective,
                    load_ratio_per_cpu=initial_load_ratio,
                )
            else:
                dynamic_worker_target = max_parallel_experiments_effective
            last_announced_worker_target: int | None = None
            completed = resumed_completed_count
            next_live_eta_update = time.monotonic() + live_eta_poll_seconds
            last_live_eta_message = ""

            while next_pending_index < len(pending_entries) or future_to_index:
                if max_parallel_experiments_mode == "auto":
                    load_ratio = _safe_system_load_ratio_per_cpu()
                    desired_target = _desired_experiment_parallel_workers(
                        workers_cap=max_parallel_experiments_effective,
                        load_ratio_per_cpu=load_ratio,
                    )
                    ramp_step = max(
                        1,
                        int(math.ceil(max_parallel_experiments_effective * 0.25)),
                    )
                    if desired_target > dynamic_worker_target:
                        dynamic_worker_target = min(
                            desired_target,
                            dynamic_worker_target + ramp_step,
                        )
                    else:
                        dynamic_worker_target = desired_target
                else:
                    load_ratio = None
                    dynamic_worker_target = max_parallel_experiments_effective

                if dynamic_worker_target != last_announced_worker_target:
                    load_display = (
                        f"{load_ratio:.2f}" if load_ratio is not None else "n/a"
                    )
                    _notify_progress(
                        progress_reporter,
                        (
                            "Quality suite worker target: "
                            f"{dynamic_worker_target}/{max_parallel_experiments_effective} "
                            f"(mode={max_parallel_experiments_mode}, "
                            f"load_per_cpu={load_display})"
                        ),
                    )
                    last_announced_worker_target = dynamic_worker_target

                if progress_reporter is not None and live_eta_poll_seconds > 0:
                    now_monotonic = time.monotonic()
                    if now_monotonic >= next_live_eta_update:
                        live_eta_message = _build_live_quality_eta_message(
                            run_root=run_root,
                            completed_experiments=completed,
                            total_experiments=total_experiments,
                            parallel_workers=dynamic_worker_target,
                        )
                        if (
                            live_eta_message is not None
                            and live_eta_message != last_live_eta_message
                        ):
                            _notify_progress(progress_reporter, live_eta_message)
                            last_live_eta_message = live_eta_message
                        next_live_eta_update = now_monotonic + live_eta_poll_seconds

                while (
                    next_pending_index < len(pending_entries)
                    and len(future_to_index) < dynamic_worker_target
                ):
                    index, experiment = pending_entries[next_pending_index]
                    next_pending_index += 1
                    _notify_progress(
                        progress_reporter,
                        (
                            f"{format_task_counter('Quality suite', index, total_experiments, noun='task')}: "
                            f"{experiment.id}"
                        ),
                    )
                    future = executor.submit(
                        _dispatch_resolved_experiment,
                        experiment=experiment,
                    )
                    future_to_index[future] = index

                if not future_to_index:
                    continue

                done, _pending = wait(
                    set(future_to_index),
                    timeout=0.5,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    continue
                for future in done:
                    index = future_to_index.pop(future)
                    completed += 1
                    position = index - 1
                    experiment = resolved_experiments[position]
                    try:
                        result = future.result()
                    except Exception as exc:  # pragma: no cover - defensive fallback
                        if require_process_workers:
                            raise
                        result = QualityExperimentResult(
                            id=experiment.id,
                            status="failed",
                            error=str(exc),
                            run_settings_hash=experiment.run_settings.stable_hash(),
                            run_settings_summary=experiment.run_settings.summary(),
                        )
                    _store_result_and_checkpoint(index=index, result=result)
                    _notify_progress(
                        progress_reporter,
                        (
                            f"{format_task_counter('Quality suite complete', completed, total_experiments, noun='task')}: "
                            f"{result.id}"
                        ),
                    )

    results = [result for result in results_by_index if result is not None]

    summary_payload = _build_summary_payload(
        suite=suite,
        run_timestamp=run_timestamp,
        experiments=resolved_experiments,
        results=results,
    )
    summary_payload["require_process_workers"] = bool(require_process_workers)
    summary_payload["process_worker_probe_available"] = bool(
        process_worker_probe_available
    )
    summary_payload["process_worker_probe_error"] = (
        str(process_worker_probe_error).strip() if process_worker_probe_error else None
    )
    summary_payload["prediction_reuse_cache_root"] = str(prediction_reuse_cache_root)
    summary_payload["prediction_reuse_cache_root_env"] = (
        _ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV
    )
    summary_payload["codex_execution_policy"] = codex_execution_policy_metadata(
        resolve_codex_execution_policy(
            "bench_quality_run",
            {},
            include_codex_farm_requested=include_codex_farm_requested,
            explicit_confirmation_granted=codex_farm_confirmed,
        )
    )
    _write_quality_run_checkpoint(
        run_root=run_root,
        suite=suite,
        run_timestamp=run_timestamp,
        experiments=resolved_experiments,
        results_by_index=results_by_index,
    )
    (run_root / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_root / "report.md").write_text(
        _format_quality_run_report(summary_payload),
        encoding="utf-8",
    )
    return run_root

def _notify_progress(
    progress_callback: ProgressCallback | None,
    message: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(message)

def _resolve_selected_targets(suite: QualitySuite) -> list[Any]:
    by_id = {target.target_id: target for target in suite.targets}
    selected_targets = []
    for target_id in suite.selected_target_ids:
        if target_id not in by_id:
            continue
        selected_targets.append(by_id[target_id])
    return selected_targets

def _resolve_quality_alignment_cache_root(*, out_dir: Path) -> Path:
    env_override = str(
        os.getenv(_ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV, "") or ""
    ).strip()
    if env_override:
        return Path(env_override).expanduser()
    return out_dir.expanduser().parent / ".cache" / "canonical_alignment"

def _resolve_quality_prediction_reuse_cache_root(*, out_dir: Path) -> Path:
    env_override = str(
        os.getenv(_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV, "") or ""
    ).strip()
    if env_override:
        return Path(env_override).expanduser()
    return out_dir.expanduser().parent / ".cache" / "prediction_reuse"

def _target_difficulty_score(target: Any) -> float:
    canonical_chars = float(_coerce_int(getattr(target, "canonical_text_chars", 0)))
    label_count = float(_coerce_int(getattr(target, "label_count", 0)))
    gold_rows = float(_coerce_int(getattr(target, "gold_span_rows", 0)))
    return (label_count * 8.0) + (gold_rows * 3.0) + (canonical_chars / 8000.0)

def _target_source_extension(target: Any) -> str:
    explicit_extension = str(getattr(target, "source_extension", "") or "").strip().lower()
    if explicit_extension:
        if explicit_extension in {"__none__", "none", "null"}:
            return ""
        if not explicit_extension.startswith("."):
            explicit_extension = f".{explicit_extension}"
        if explicit_extension == ".":
            return ""
        return explicit_extension
    source_path = Path(str(getattr(target, "source_file", "")))
    return source_path.suffix.lower()

def _target_format_counts(targets: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for target in targets:
        extension = _target_source_extension(target) or _SOURCE_EXTENSION_NONE
        counts[extension] = counts.get(extension, 0) + 1
    return {key: counts[key] for key in sorted(counts)}

def _select_probe_targets(
    *,
    suite_targets: list[Any],
    max_targets: int,
) -> list[Any]:
    if len(suite_targets) <= max_targets:
        return list(suite_targets)

    by_extension: dict[str, list[Any]] = {}
    for target in suite_targets:
        extension = _target_source_extension(target) or "__none__"
        by_extension.setdefault(extension, []).append(target)

    selected: list[Any] = []
    selected_ids: set[str] = set()
    for extension in sorted(by_extension):
        rows = sorted(
            by_extension[extension],
            key=lambda row: (
                -_target_difficulty_score(row),
                str(getattr(row, "target_id", "")),
            ),
        )
        if not rows:
            continue
        candidate = rows[0]
        candidate_id = str(getattr(candidate, "target_id", ""))
        if candidate_id in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate_id)

    if len(selected) > max_targets:
        selected = sorted(
            selected,
            key=lambda row: (
                -_target_difficulty_score(row),
                str(getattr(row, "target_id", "")),
            ),
        )[:max_targets]
        selected_ids = {str(getattr(row, "target_id", "")) for row in selected}

    if len(selected) < max_targets:
        remaining = [
            row
            for row in sorted(
                suite_targets,
                key=lambda row: (
                    -_target_difficulty_score(row),
                    str(getattr(row, "target_id", "")),
                ),
            )
            if str(getattr(row, "target_id", "")) not in selected_ids
        ]
        selected.extend(remaining[: max(0, max_targets - len(selected))])

    return selected

def _select_mid_targets(
    *,
    suite_targets: list[Any],
    probe_targets: list[Any],
    max_targets: int,
) -> list[Any]:
    if len(suite_targets) <= max_targets:
        return list(suite_targets)
    selected: list[Any] = []
    selected_ids: set[str] = set()
    for target in probe_targets:
        target_id = str(getattr(target, "target_id", ""))
        if target_id in selected_ids:
            continue
        selected.append(target)
        selected_ids.add(target_id)

    remaining = [
        row
        for row in sorted(
            suite_targets,
            key=lambda row: (
                -_target_difficulty_score(row),
                str(getattr(row, "target_id", "")),
            ),
        )
        if str(getattr(row, "target_id", "")) not in selected_ids
    ]
    selected.extend(remaining[: max(0, max_targets - len(selected))])
    return selected[:max_targets]

def _target_ids(targets: list[Any]) -> list[str]:
    return [str(getattr(target, "target_id", "")) for target in targets]

def _build_target_variants_for_targets(
    *,
    suite_targets: list[Any],
    run_settings: RunSettings,
    include_codex_farm: bool,
    include_markdown_extractors: bool,
    include_deterministic_sweeps: bool,
    allowed_run_settings_hashes: set[str] | None = None,
) -> tuple[list[tuple[Any, list[Any]]], int, int]:
    import cookimport.cli as cli

    all_method_targets: list[cli.AllMethodTarget] = []
    for target in suite_targets:
        source_file = resolve_repo_path(str(target.source_file), repo_root=REPO_ROOT)
        gold_spans_path = resolve_repo_path(
            str(target.gold_spans_path),
            repo_root=REPO_ROOT,
        )
        all_method_targets.append(
            cli.AllMethodTarget(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display=str(getattr(target, "target_id", source_file.name)),
            )
        )

    target_variants = cli._build_all_method_target_variants(
        targets=all_method_targets,
        base_settings=run_settings,
        include_codex_farm=include_codex_farm,
        include_markdown_extractors=include_markdown_extractors,
        include_deterministic_sweeps=include_deterministic_sweeps,
    )
    total_variants_unfiltered = sum(len(rows) for _target, rows in target_variants)
    if not allowed_run_settings_hashes:
        return target_variants, total_variants_unfiltered, total_variants_unfiltered

    filtered_target_variants: list[tuple[Any, list[Any]]] = []
    for target, variants in target_variants:
        filtered_variants = [
            variant
            for variant in variants
            if variant.run_settings.stable_hash() in allowed_run_settings_hashes
        ]
        if not filtered_variants:
            filtered_variants = list(variants)
        filtered_target_variants.append((target, filtered_variants))
    total_variants_filtered = sum(len(rows) for _target, rows in filtered_target_variants)
    return (
        filtered_target_variants,
        total_variants_unfiltered,
        total_variants_filtered,
    )

def _run_all_method_for_round(
    *,
    experiment_id: str,
    target_variants: list[tuple[Any, list[Any]]],
    root_output_dir: Path,
    all_method_runtime: dict[str, Any],
    include_codex_farm_requested: bool,
    include_codex_effective: bool,
    canonical_alignment_cache_root: Path,
    prediction_reuse_cache_root: Path,
    require_process_workers: bool,
    progress_callback: ProgressCallback | None,
) -> Path:
    import cookimport.cli as cli

    runtime_effective = _resolve_quality_runtime_for_environment(
        experiment_id=experiment_id,
        target_variants=target_variants,
        all_method_runtime=all_method_runtime,
        progress_callback=progress_callback,
    )
    processed_output_root = root_output_dir / "processed_output"
    processed_output_root.mkdir(parents=True, exist_ok=True)
    return cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=include_codex_farm_requested,
        include_codex_farm_effective=include_codex_effective,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        max_parallel_sources=runtime_effective.get("max_parallel_sources"),
        max_inflight_pipelines=runtime_effective.get("max_inflight_pipelines"),
        max_concurrent_split_phases=runtime_effective.get(
            "max_concurrent_split_phases"
        ),
        max_eval_tail_pipelines=runtime_effective.get("max_eval_tail_pipelines"),
        config_timeout_seconds=runtime_effective.get("config_timeout_seconds"),
        retry_failed_configs=runtime_effective.get("retry_failed_configs"),
        scheduler_scope=runtime_effective.get(
            "scheduler_scope",
            cli.ALL_METHOD_SCHEDULER_SCOPE_GLOBAL,
        ),
        source_scheduling=runtime_effective.get("source_scheduling"),
        source_shard_threshold_seconds=runtime_effective.get(
            "source_shard_threshold_seconds"
        ),
        source_shard_max_parts=runtime_effective.get("source_shard_max_parts"),
        source_shard_min_variants=runtime_effective.get("source_shard_min_variants"),
        wing_backlog_target=runtime_effective.get("wing_backlog_target"),
        smart_scheduler=bool(runtime_effective.get("smart_scheduler", True)),
        canonical_alignment_cache_root=canonical_alignment_cache_root,
        prediction_reuse_cache_root=prediction_reuse_cache_root,
        require_process_workers=bool(require_process_workers),
    )

def _rank_run_settings_hashes_from_multi_source_report(
    *,
    experiment_root: Path,
    report_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    source_rows = report_payload.get("sources")
    if not isinstance(source_rows, list):
        return []

    per_hash: dict[str, dict[str, dict[str, float | str | None]]] = {}
    for source_row in source_rows:
        if not isinstance(source_row, dict):
            continue
        source_group_key = str(source_row.get("source_group_key") or "").strip()
        if not source_group_key:
            source_group_key = str(source_row.get("source_file_name") or "").strip()
        if not source_group_key:
            source_group_key = str(source_row.get("source_file") or "").strip()
        if not source_group_key:
            continue

        for report_path in _candidate_report_json_paths(source_row):
            per_source_report = _load_source_report(
                experiment_root=experiment_root,
                report_json_path=report_path,
            )
            if per_source_report is None:
                continue
            variants = per_source_report.get("variants")
            if not isinstance(variants, list):
                continue
            for variant_row in variants:
                if not isinstance(variant_row, dict):
                    continue
                status = str(variant_row.get("status") or "").strip().lower()
                if status != "ok":
                    continue
                run_settings_hash = str(variant_row.get("run_config_hash") or "").strip()
                if not run_settings_hash:
                    continue
                practical_f1 = _coerce_float(variant_row.get("practical_f1"))
                strict_f1 = _coerce_float(variant_row.get("f1"))
                duration_seconds = _coerce_float(variant_row.get("duration_seconds"))
                if practical_f1 is None or strict_f1 is None:
                    continue
                source_map = per_hash.setdefault(run_settings_hash, {})
                existing = source_map.get(source_group_key)
                if existing is None:
                    source_map[source_group_key] = {
                        "practical_f1": practical_f1,
                        "strict_f1": strict_f1,
                        "duration_seconds": duration_seconds,
                        "run_config_summary": str(
                            variant_row.get("run_config_summary") or ""
                        ).strip()
                        or None,
                    }
                    continue
                existing_practical = _coerce_float(existing.get("practical_f1"))
                existing_strict = _coerce_float(existing.get("strict_f1"))
                existing_duration = _coerce_float(existing.get("duration_seconds"))
                replace = False
                if existing_practical is None or practical_f1 > existing_practical:
                    replace = True
                elif (
                    existing_practical is not None
                    and practical_f1 == existing_practical
                    and (
                        existing_strict is None
                        or strict_f1 > existing_strict
                        or (
                            strict_f1 == existing_strict
                            and (
                                existing_duration is None
                                or (
                                    duration_seconds is not None
                                    and duration_seconds < existing_duration
                                )
                            )
                        )
                    )
                ):
                    replace = True
                if replace:
                    source_map[source_group_key] = {
                        "practical_f1": practical_f1,
                        "strict_f1": strict_f1,
                        "duration_seconds": duration_seconds,
                        "run_config_summary": str(
                            variant_row.get("run_config_summary") or ""
                        ).strip()
                        or None,
                    }

    ranked_rows: list[dict[str, Any]] = []
    for run_settings_hash, source_map in per_hash.items():
        practical_values: list[float] = []
        strict_values: list[float] = []
        duration_values: list[float] = []
        run_config_summary: str | None = None
        for row in source_map.values():
            practical = _coerce_float(row.get("practical_f1"))
            strict = _coerce_float(row.get("strict_f1"))
            duration = _coerce_float(row.get("duration_seconds"))
            if practical is None or strict is None:
                continue
            practical_values.append(practical)
            strict_values.append(strict)
            if duration is not None:
                duration_values.append(duration)
            if run_config_summary is None:
                run_config_summary = str(row.get("run_config_summary") or "").strip() or None
        if not practical_values or not strict_values:
            continue
        ranked_rows.append(
            {
                "run_settings_hash": run_settings_hash,
                "run_config_summary": run_config_summary,
                "coverage_sources": len(source_map),
                "mean_practical_f1": float(statistics.mean(practical_values)),
                "mean_strict_f1": float(statistics.mean(strict_values)),
                "median_duration_seconds": float(statistics.median(duration_values))
                if duration_values
                else None,
            }
        )

    ranked_rows.sort(
        key=lambda row: (
            -float(row.get("mean_practical_f1") or 0.0),
            -float(row.get("mean_strict_f1") or 0.0),
            -int(row.get("coverage_sources") or 0),
            float(row.get("median_duration_seconds") or 0.0),
            str(row.get("run_settings_hash") or ""),
        )
    )
    for index, row in enumerate(ranked_rows, start=1):
        row["rank"] = index
    return ranked_rows

def _compute_keep_count(*, total: int, keep_ratio: float, minimum: int) -> int:
    if total <= 0:
        return 0
    ratio_count = int(math.ceil(float(total) * float(keep_ratio)))
    return max(1, min(total, max(minimum, ratio_count)))

def _run_single_experiment(
    *,
    experiment_id: str,
    suite_targets: list[Any],
    run_root: Path,
    experiment_root: Path,
    run_settings: RunSettings,
    all_method_runtime: dict[str, Any],
    include_markdown_extractors: bool,
    include_codex_farm_requested: bool,
    include_codex_effective: bool,
    canonical_alignment_cache_root: Path,
    prediction_reuse_cache_root: Path,
    search_strategy: str,
    race_probe_targets: int,
    race_mid_targets: int,
    race_keep_ratio: float,
    race_finalists: int,
    include_deterministic_sweeps: bool,
    require_process_workers: bool,
    progress_callback: ProgressCallback | None,
) -> QualityExperimentResult:
    search_strategy_metadata: dict[str, Any] | None = None
    if search_strategy == "race" and len(suite_targets) > 1:
        all_target_variants, all_variants_unfiltered, all_variants_effective = (
            _build_target_variants_for_targets(
                suite_targets=suite_targets,
                run_settings=run_settings,
                include_codex_farm=include_codex_effective,
                include_markdown_extractors=include_markdown_extractors,
                include_deterministic_sweeps=include_deterministic_sweeps,
                allowed_run_settings_hashes=None,
            )
        )
        if all_variants_effective <= race_finalists:
            _notify_progress(
                progress_callback,
                (
                    f"Quality suite [{experiment_id}] race requested but variants="
                    f"{all_variants_effective} <= finalists={race_finalists}; "
                    "using exhaustive strategy."
                ),
            )
            report_md_path = _run_all_method_for_round(
                experiment_id=experiment_id,
                target_variants=all_target_variants,
                root_output_dir=experiment_root,
                all_method_runtime=all_method_runtime,
                include_codex_farm_requested=include_codex_farm_requested,
                include_codex_effective=include_codex_effective,
                canonical_alignment_cache_root=canonical_alignment_cache_root,
                prediction_reuse_cache_root=prediction_reuse_cache_root,
                require_process_workers=bool(require_process_workers),
                progress_callback=progress_callback,
            )
            search_strategy_metadata = {
                "requested_strategy": "race",
                "effective_strategy": "exhaustive",
                "reason": "race_no_prune_variant_count_le_finalists",
                "race_finalists": race_finalists,
                "target_count": len(suite_targets),
                "variants_unfiltered": all_variants_unfiltered,
                "variants_effective": all_variants_effective,
                "strategy": "exhaustive",
            }
        else:
            probe_targets = _select_probe_targets(
                suite_targets=suite_targets,
                max_targets=min(len(suite_targets), race_probe_targets),
            )
            mid_targets = _select_mid_targets(
                suite_targets=suite_targets,
                probe_targets=probe_targets,
                max_targets=min(len(suite_targets), race_mid_targets),
            )
            race_dir = experiment_root / "race"
            race_dir.mkdir(parents=True, exist_ok=True)
            race_rounds: list[dict[str, Any]] = []
            survivor_hashes: set[str] | None = None

            round_plan: list[tuple[str, list[Any]]] = [("probe", probe_targets)]
            if len(mid_targets) > len(probe_targets):
                round_plan.append(("mid", mid_targets))

            for round_index, (round_name, round_targets) in enumerate(round_plan, start=1):
                round_root = race_dir / f"round_{round_index:02d}_{round_name}"
                round_root.mkdir(parents=True, exist_ok=True)
                if progress_callback is not None:
                    _notify_progress(
                        progress_callback,
                        (
                            f"Quality suite [{experiment_id}] race round {round_index}/{len(round_plan) + 1} "
                            f"({round_name}) targets={len(round_targets)} survivors="
                            f"{len(survivor_hashes) if survivor_hashes else 'all'}"
                        ),
                    )
                target_variants, variants_unfiltered, variants_effective = (
                    _build_target_variants_for_targets(
                        suite_targets=round_targets,
                        run_settings=run_settings,
                        include_codex_farm=include_codex_effective,
                        include_markdown_extractors=include_markdown_extractors,
                        include_deterministic_sweeps=include_deterministic_sweeps,
                        allowed_run_settings_hashes=survivor_hashes,
                    )
                )
                report_md_path = _run_all_method_for_round(
                    experiment_id=experiment_id,
                    target_variants=target_variants,
                    root_output_dir=round_root,
                    all_method_runtime=all_method_runtime,
                    include_codex_farm_requested=include_codex_farm_requested,
                    include_codex_effective=include_codex_effective,
                    canonical_alignment_cache_root=canonical_alignment_cache_root,
                    prediction_reuse_cache_root=prediction_reuse_cache_root,
                    require_process_workers=bool(require_process_workers),
                    progress_callback=progress_callback,
                )
                report_json_path = report_md_path.with_suffix(".json")
                report_payload = _load_json_dict(report_json_path)
                ranked_rows = _rank_run_settings_hashes_from_multi_source_report(
                    experiment_root=round_root,
                    report_payload=report_payload,
                )
                if ranked_rows:
                    if round_name == "probe":
                        keep_count = _compute_keep_count(
                            total=len(ranked_rows),
                            keep_ratio=race_keep_ratio,
                            minimum=max(race_finalists, 1),
                        )
                    else:
                        keep_count = _compute_keep_count(
                            total=len(ranked_rows),
                            keep_ratio=_RACE_KEEP_RATIO_SECONDARY,
                            minimum=max(race_finalists, 1),
                        )
                    survivor_hashes = {
                        str(row.get("run_settings_hash") or "")
                        for row in ranked_rows[:keep_count]
                        if str(row.get("run_settings_hash") or "").strip()
                    }
                race_rounds.append(
                    {
                        "round_index": round_index,
                        "round_name": round_name,
                        "target_ids": _target_ids(round_targets),
                        "variants_unfiltered": variants_unfiltered,
                        "variants_effective": variants_effective,
                        "ranked_count": len(ranked_rows),
                        "survivors_after_round": len(survivor_hashes)
                        if survivor_hashes
                        else 0,
                        "report_json_path": _relative_to_run_root(report_json_path, run_root),
                    }
                )
                if survivor_hashes and len(survivor_hashes) <= race_finalists:
                    break

            final_target_variants, final_unfiltered, final_effective = (
                _build_target_variants_for_targets(
                    suite_targets=suite_targets,
                    run_settings=run_settings,
                    include_codex_farm=include_codex_effective,
                    include_markdown_extractors=include_markdown_extractors,
                    include_deterministic_sweeps=include_deterministic_sweeps,
                    allowed_run_settings_hashes=survivor_hashes,
                )
            )
            if progress_callback is not None:
                _notify_progress(
                    progress_callback,
                    (
                        f"Quality suite [{experiment_id}] race final round targets={len(suite_targets)} "
                        f"variants={final_effective}"
                    ),
                )
            report_md_path = _run_all_method_for_round(
                experiment_id=experiment_id,
                target_variants=final_target_variants,
                root_output_dir=experiment_root,
                all_method_runtime=all_method_runtime,
                include_codex_farm_requested=include_codex_farm_requested,
                include_codex_effective=include_codex_effective,
                canonical_alignment_cache_root=canonical_alignment_cache_root,
                prediction_reuse_cache_root=prediction_reuse_cache_root,
                require_process_workers=bool(require_process_workers),
                progress_callback=progress_callback,
            )
            search_strategy_metadata = {
                "requested_strategy": "race",
                "effective_strategy": "race",
                "reason": None,
                "strategy": "race",
                "probe_targets": race_probe_targets,
                "mid_targets": race_mid_targets,
                "keep_ratio": race_keep_ratio,
                "finalists": race_finalists,
                "variant_counts": {
                    "full_unfiltered": all_variants_unfiltered,
                    "full_effective": all_variants_effective,
                    "final_unfiltered": final_unfiltered,
                    "final_effective": final_effective,
                },
                "rounds": race_rounds,
                "final": {
                    "target_ids": _target_ids(suite_targets),
                    "variants_unfiltered": final_unfiltered,
                    "variants_effective": final_effective,
                    "survivor_hashes_used": sorted(survivor_hashes)
                    if survivor_hashes
                    else [],
                },
            }
    else:
        target_variants, _all_variants_unfiltered, _all_variants_effective = (
            _build_target_variants_for_targets(
                suite_targets=suite_targets,
                run_settings=run_settings,
                include_codex_farm=include_codex_effective,
                include_markdown_extractors=include_markdown_extractors,
                include_deterministic_sweeps=include_deterministic_sweeps,
                allowed_run_settings_hashes=None,
            )
        )
        report_md_path = _run_all_method_for_round(
            experiment_id=experiment_id,
            target_variants=target_variants,
            root_output_dir=experiment_root,
            all_method_runtime=all_method_runtime,
            include_codex_farm_requested=include_codex_farm_requested,
            include_codex_effective=include_codex_effective,
            canonical_alignment_cache_root=canonical_alignment_cache_root,
            prediction_reuse_cache_root=prediction_reuse_cache_root,
            require_process_workers=bool(require_process_workers),
            progress_callback=progress_callback,
        )
    report_json_path = report_md_path.with_suffix(".json")
    report_payload = _load_json_dict(report_json_path)
    if search_strategy_metadata is not None:
        (experiment_root / "search_strategy.json").write_text(
            json.dumps(search_strategy_metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    aggregate_payload = _summarize_experiment_report(
        experiment_root=experiment_root,
        report_payload=report_payload,
    )
    line_role_artifacts = _summarize_line_role_artifacts(
        experiment_root=experiment_root,
        run_root=run_root,
    )

    status = aggregate_payload["status"]
    error = aggregate_payload.get("error")
    return QualityExperimentResult(
        id=experiment_id,
        status=status,
        error=error,
        run_settings_hash=run_settings.stable_hash(),
        run_settings_summary=run_settings.summary(),
        line_role_artifacts=line_role_artifacts,
        strict_precision_macro=aggregate_payload.get("strict_precision_macro"),
        strict_recall_macro=aggregate_payload.get("strict_recall_macro"),
        strict_f1_macro=aggregate_payload.get("strict_f1_macro"),
        practical_precision_macro=aggregate_payload.get("practical_precision_macro"),
        practical_recall_macro=aggregate_payload.get("practical_recall_macro"),
        practical_f1_macro=aggregate_payload.get("practical_f1_macro"),
        source_success_rate=aggregate_payload.get("source_success_rate"),
        sources_planned=aggregate_payload.get("sources_planned", 0),
        sources_successful=aggregate_payload.get("sources_successful", 0),
        configs_planned=aggregate_payload.get("configs_planned", 0),
        configs_completed=aggregate_payload.get("configs_completed", 0),
        configs_successful=aggregate_payload.get("configs_successful", 0),
        evaluation_signatures_unique=aggregate_payload.get(
            "evaluation_signatures_unique",
            0,
        ),
        evaluation_runs_executed=aggregate_payload.get("evaluation_runs_executed", 0),
        evaluation_results_reused_in_run=aggregate_payload.get(
            "evaluation_results_reused_in_run",
            0,
        ),
        evaluation_results_reused_cross_run=aggregate_payload.get(
            "evaluation_results_reused_cross_run",
            0,
        ),
        source_group_count=aggregate_payload.get("source_group_count", 0),
        source_group_with_multiple_shards=aggregate_payload.get(
            "source_group_with_multiple_shards",
            0,
        ),
        report_json_path=_relative_to_run_root(report_json_path, run_root),
        report_md_path=_relative_to_run_root(report_md_path, run_root),
    )
