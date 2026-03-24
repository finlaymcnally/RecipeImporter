from __future__ import annotations

from cookimport.bench.qualitysuite.shared import *  # noqa: F401,F403
from cookimport.bench.qualitysuite import planning as _planning
from cookimport.bench.qualitysuite import shared as _shared
from cookimport.bench.qualitysuite import summary as _summary

globals().update(
    {name: getattr(_shared, name) for name in dir(_shared) if not name.startswith("__")}
)
for _module in (_planning, _summary):
    globals().update(
        {name: getattr(_module, name) for name in dir(_module) if not name.startswith("__")}
    )


def _notify_progress(
    progress_callback: ProgressCallback | None,
    message: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(message)


def _running_in_wsl() -> bool:
    if os.getenv("WSL_DISTRO_NAME") or os.getenv("WSL_INTEROP"):
        return True
    try:
        release = str(os.uname().release or "")
    except AttributeError:
        return False
    return "microsoft" in release.lower()

def _safe_system_load_ratio_per_cpu() -> float | None:
    """Best-effort 1m load/cpu ratio; None when unavailable."""
    try:
        load_1m, _load_5m, _load_15m = os.getloadavg()
    except (AttributeError, OSError):
        return None
    cpu_count = _coerce_int(os.cpu_count(), minimum=1)
    if cpu_count <= 0:
        return None
    try:
        ratio = float(load_1m) / float(cpu_count)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not math.isfinite(ratio):
        return None
    return max(0.0, ratio)

def _resolve_experiment_parallelism_cap(
    *,
    requested: int | None,
    total_experiments: int,
) -> tuple[int, str, int, int, str]:
    cpu_count = _coerce_int(os.cpu_count(), minimum=1)
    auto_ceiling, auto_ceiling_source = _resolve_auto_parallel_experiment_ceiling()
    if requested is None:
        auto_cap = max(1, min(total_experiments, cpu_count, auto_ceiling))
        return auto_cap, "auto", cpu_count, auto_ceiling, auto_ceiling_source
    fixed_cap = max(1, min(int(requested), total_experiments))
    return fixed_cap, "fixed", cpu_count, auto_ceiling, auto_ceiling_source

def _resolve_auto_parallel_experiment_ceiling() -> tuple[int, str]:
    cpu_count = _coerce_int(os.cpu_count(), minimum=1)
    env_raw = str(
        os.getenv(_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS_ENV, "") or ""
    ).strip()
    if not env_raw:
        return cpu_count, "cpu_count"
    try:
        env_value = int(env_raw)
    except (TypeError, ValueError):
        return cpu_count, "cpu_count"
    return max(1, env_value), "env"

def _resolve_quality_live_eta_poll_seconds() -> float:
    env_raw = str(os.getenv(_QUALITY_LIVE_ETA_POLL_SECONDS_ENV, "") or "").strip()
    if not env_raw:
        return _QUALITY_LIVE_ETA_POLL_SECONDS_DEFAULT
    try:
        numeric = float(env_raw)
    except (TypeError, ValueError):
        return _QUALITY_LIVE_ETA_POLL_SECONDS_DEFAULT
    return max(2.0, numeric)

def _resolve_quality_experiment_executor_mode(
    *,
    max_parallel_experiments_effective: int,
) -> tuple[str, str]:
    requested_raw = str(
        os.getenv(_QUALITY_EXPERIMENT_EXECUTOR_MODE_ENV, "") or ""
    ).strip().lower()
    requested_mode = (
        requested_raw if requested_raw in _QUALITY_EXPERIMENT_EXECUTOR_MODES else "auto"
    )
    if requested_mode == "thread":
        return "thread", "env"
    if requested_mode == "subprocess":
        return "subprocess", "env"
    if max_parallel_experiments_effective <= 1:
        return "thread", "single_worker"

    import cookimport.cli as cli

    available, error = cli._probe_all_method_process_pool_executor()
    if available:
        return "thread", "process_pool_available"
    detail = str(error or "").strip() or "unknown"
    return "subprocess", f"process_pool_unavailable:{detail}"

def _apply_wsl_quality_safety_guard(
    *,
    experiments: list[_ResolvedExperiment],
    max_parallel_experiments_effective: int,
    cpu_count: int,
) -> tuple[list[_ResolvedExperiment], dict[str, Any]]:
    _ = max_parallel_experiments_effective
    worker_cap = max(
        1,
        min(_QUALITY_WSL_SAFETY_WORKER_CAP, _coerce_int(cpu_count, minimum=1)),
    )
    metadata: dict[str, Any] = {
        "wsl_detected": bool(_running_in_wsl()),
        "wsl_safety_guard_applied": False,
        "wsl_safety_guard_disable_env": _QUALITY_WSL_SAFETY_GUARD_DISABLE_ENV,
        "wsl_safety_guard_reason": "not_wsl",
        "wsl_safety_guard_worker_cap": worker_cap,
        "wsl_safety_guard_adjusted_experiments": 0,
    }
    if not metadata["wsl_detected"]:
        return experiments, metadata

    disable_raw = str(os.getenv(_QUALITY_WSL_SAFETY_GUARD_DISABLE_ENV, "") or "").strip()
    if disable_raw.lower() in {"1", "true", "yes", "on"}:
        metadata["wsl_safety_guard_reason"] = "disabled_by_env"
        return experiments, metadata

    guarded: list[_ResolvedExperiment] = []
    adjusted_experiments = 0
    for experiment in experiments:
        guarded_payload = dict(experiment.run_settings_payload)
        payload_changed = False
        for key in ("workers", "pdf_split_workers", "epub_split_workers"):
            current = _coerce_int(getattr(experiment.run_settings, key), minimum=1)
            capped = min(current, worker_cap)
            if current != capped or guarded_payload.get(key) != capped:
                guarded_payload[key] = capped
                payload_changed = True

        guarded_runtime = dict(experiment.all_method_runtime)
        runtime_changed = False
        for runtime_key, runtime_cap in _QUALITY_WSL_RUNTIME_CAPS.items():
            current = _coerce_int(
                guarded_runtime.get(runtime_key),
                minimum=int(runtime_cap),
            )
            capped = min(current, int(runtime_cap))
            if guarded_runtime.get(runtime_key) != capped:
                guarded_runtime[runtime_key] = capped
                runtime_changed = True

        if bool(guarded_runtime.get("smart_scheduler", True)):
            guarded_runtime["smart_scheduler"] = False
            runtime_changed = True

        guarded_run_settings = (
            RunSettings.from_dict(
                project_run_config_payload(
                    guarded_payload,
                    contract=RUN_SETTING_CONTRACT_FULL,
                ),
                warn_context=(
                    f"quality-run experiment {experiment.id} "
                    "[wsl safety guard]"
                ),
            )
            if payload_changed
            else experiment.run_settings
        )

        if payload_changed or runtime_changed:
            adjusted_experiments += 1

        guarded.append(
            _ResolvedExperiment(
                id=experiment.id,
                run_settings_patch=dict(experiment.run_settings_patch),
                requested_run_settings_payload=dict(
                    experiment.requested_run_settings_payload
                ),
                requested_run_settings=experiment.requested_run_settings,
                run_settings_payload=guarded_payload,
                run_settings=guarded_run_settings,
                all_method_runtime_patch=dict(experiment.all_method_runtime_patch),
                all_method_runtime=guarded_runtime,
            )
        )

    metadata["wsl_safety_guard_adjusted_experiments"] = adjusted_experiments
    metadata["wsl_safety_guard_applied"] = adjusted_experiments > 0
    metadata["wsl_safety_guard_reason"] = (
        "applied" if adjusted_experiments > 0 else "already_within_guard_caps"
    )
    return guarded, metadata

def _desired_experiment_parallel_workers(
    *,
    workers_cap: int,
    load_ratio_per_cpu: float | None,
) -> int:
    """Map host load pressure to a bounded worker target."""
    workers_cap = max(1, int(workers_cap))
    if workers_cap <= 1:
        return 1
    if load_ratio_per_cpu is None:
        return workers_cap
    pressure = max(0.0, float(load_ratio_per_cpu))
    if pressure >= 1.05:
        return 1
    if pressure >= 0.90:
        return max(1, int(math.ceil(workers_cap * 0.25)))
    if pressure >= 0.75:
        return max(1, int(math.ceil(workers_cap * 0.50)))
    if pressure >= 0.55:
        return max(1, int(math.ceil(workers_cap * 0.75)))
    return workers_cap

def _build_live_quality_eta_message(
    *,
    run_root: Path,
    completed_experiments: int,
    total_experiments: int,
    parallel_workers: int,
) -> str | None:
    estimate = estimate_quality_run_eta(run_root / "experiments")
    if estimate.active_experiments <= 0:
        return None
    remaining_experiments = max(0, int(total_experiments) - int(completed_experiments))
    queued_experiments = max(0, remaining_experiments - estimate.active_experiments)
    remaining_seconds = estimate_quality_run_remaining_seconds(
        estimate=estimate,
        total_experiments=total_experiments,
        completed_experiments=completed_experiments,
        parallel_workers=parallel_workers,
    )
    eta_display = format_eta_seconds_short(remaining_seconds)
    return (
        f"Quality suite live task {completed_experiments}/{total_experiments}: "
        f"active_experiments={estimate.active_experiments} "
        f"queued_experiments={queued_experiments} "
        f"work_units={estimate.pending_work_units:.1f} "
        f"eta={eta_display} "
        f"eta_models={estimate.experiments_with_eta}of{estimate.active_experiments}"
    )

def _resolve_quality_runtime_for_environment(
    *,
    experiment_id: str,
    target_variants: list[tuple[Any, list[Any]]],
    all_method_runtime: dict[str, Any],
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    import cookimport.cli as cli

    runtime = dict(all_method_runtime)
    requested_scope = cli._normalize_all_method_scheduler_scope(
        runtime.get("scheduler_scope")
    )
    if requested_scope != cli.ALL_METHOD_SCHEDULER_SCOPE_GLOBAL:
        return runtime

    process_workers_available, process_worker_error = (
        cli._probe_all_method_process_pool_executor()
    )
    if process_workers_available:
        return runtime

    detail = (
        f" ({process_worker_error})"
        if isinstance(process_worker_error, str) and process_worker_error
        else ""
    )
    _target_count = max(1, len(target_variants))
    _parallel_sources = _coerce_int(runtime.get("max_parallel_sources"), minimum=0)
    _parallel_rendered = str(_parallel_sources) if _parallel_sources > 0 else "auto"
    _notify_progress(
        progress_callback,
        (
            f"Quality suite [{experiment_id}] process workers unavailable{detail}; "
            "staying on global scheduler and using thread-backed config workers "
            f"(targets={_target_count}, max_parallel_sources={_parallel_rendered})."
        ),
    )
    return runtime
