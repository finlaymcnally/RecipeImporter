"""Quality-suite execution for deterministic all-method quality experiments."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import datetime as dt
import json
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cookimport.bench.quality_eta import (
    estimate_quality_run_eta,
    estimate_quality_run_remaining_seconds,
    format_eta_seconds_short,
)
from cookimport.bench.quality_suite import QualitySuite
from cookimport.bench.speed_suite import resolve_repo_path
from cookimport.config.codex_decision import (
    apply_benchmark_baseline_contract,
    classify_codex_surfaces,
    codex_execution_policy_metadata,
    resolve_codex_execution_policy,
)
from cookimport.config.run_settings import (
    RUN_SETTING_CONTRACT_FULL,
    RunSettings,
    project_run_config_payload,
)
from cookimport.core.progress_messages import format_task_counter
from cookimport.paths import REPO_ROOT

_EXPERIMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SUPPORTED_EXPERIMENT_SCHEMA_VERSION = 2
_SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS = {1, 2}
_SUPPORTED_SEARCH_STRATEGIES = {"exhaustive", "race"}
_ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV = "COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT"
_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV = (
    "COOKIMPORT_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT"
)
_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS_ENV = (
    "COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS"
)
_QUALITY_LIVE_ETA_POLL_SECONDS_ENV = "COOKIMPORT_QUALITY_LIVE_ETA_POLL_SECONDS"
_QUALITY_LIVE_ETA_POLL_SECONDS_DEFAULT = 15.0
_QUALITY_EXPERIMENT_EXECUTOR_MODE_ENV = "COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE"
_QUALITY_EXPERIMENT_EXECUTOR_MODES = {"auto", "thread", "subprocess"}
_QUALITY_WSL_SAFETY_GUARD_DISABLE_ENV = "COOKIMPORT_QUALITY_WSL_DISABLE_SAFETY_GUARD"
_QUALITY_WSL_SAFETY_WORKER_CAP = 2
_QUALITY_WSL_RUNTIME_CAPS = {
    "max_parallel_sources": 1,
    "max_inflight_pipelines": 2,
    "max_concurrent_split_phases": 1,
    "max_eval_tail_pipelines": 2,
    "wing_backlog_target": 1,
}
_QUALITY_EXPERIMENT_WORKER_REQUEST_ARG = "--experiment-worker-request"
_QUALITY_EXPERIMENT_WORKER_REQUEST_FILENAME = "_experiment_worker_request.json"
_QUALITY_EXPERIMENT_WORKER_RESULT_FILENAME = "_experiment_worker_result.json"
_QUALITY_EXPERIMENT_RESULT_FILENAME = "quality_experiment_result.json"
_QUALITY_RUN_CHECKPOINT_FILENAME = "checkpoint.json"
_QUALITY_RUN_PARTIAL_SUMMARY_FILENAME = "summary.partial.json"
_QUALITY_RUN_PARTIAL_REPORT_FILENAME = "report.partial.md"
_SOURCE_EXTENSION_NONE = "__none__"
_ALL_METHOD_RUNTIME_ALLOWED_KEYS = {
    "max_parallel_sources",
    "max_inflight_pipelines",
    "max_concurrent_split_phases",
    "max_eval_tail_pipelines",
    "config_timeout_seconds",
    "retry_failed_configs",
    "scheduler_scope",
    "source_scheduling",
    "source_shard_threshold_seconds",
    "source_shard_max_parts",
    "source_shard_min_variants",
    "wing_backlog_target",
    "smart_scheduler",
}
_RACE_KEEP_RATIO_SECONDARY = 0.5
_RUN_SETTINGS_PATCH_COMPAT_KEYS = {
    "section_detector_backend",
    "instruction_step_segmentation_policy",
    "instruction_step_segmenter",
    "benchmark_sequence_matcher",
    "multi_recipe_trace",
    "p6_emit_metadata_debug",
    "codex_farm_pipeline_pass4_knowledge",
    "codex_farm_pipeline_pass5_tags",
}


ProgressCallback = Callable[[str], None]


class QualityExperiment(BaseModel):
    """One quality experiment definition row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    run_settings_patch: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("id is required")
        if not _EXPERIMENT_ID_PATTERN.match(cleaned):
            raise ValueError(
                "id must be slug-safe: lowercase letters, digits, '_' or '-'"
            )
        return cleaned


class QualityExperimentV2(QualityExperiment):
    """Schema-v2 experiment row with optional all-method runtime knob patching."""

    all_method_runtime_patch: dict[str, Any] = Field(default_factory=dict)


class QualityLever(BaseModel):
    """Schema-v2 lever: a toggleable patch that becomes its own experiment."""

    model_config = ConfigDict(extra="forbid")

    id: str
    enabled: bool = True
    run_settings_patch: dict[str, Any] = Field(default_factory=dict)
    all_method_runtime_patch: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("id is required")
        if not _EXPERIMENT_ID_PATTERN.match(cleaned):
            raise ValueError(
                "id must be slug-safe: lowercase letters, digits, '_' or '-'"
            )
        return cleaned


class QualityExperimentResult(BaseModel):
    """Normalized experiment result row used by quality summaries and compare."""

    id: str
    status: str
    error: str | None = None
    run_settings_hash: str | None = None
    run_settings_summary: str | None = None
    # Optional: when line-role pipeline artifacts exist under the experiment root,
    # capture a tiny, human-friendly summary plus file pointers.
    line_role_artifacts: dict[str, Any] | None = None
    strict_precision_macro: float | None = None
    strict_recall_macro: float | None = None
    strict_f1_macro: float | None = None
    practical_precision_macro: float | None = None
    practical_recall_macro: float | None = None
    practical_f1_macro: float | None = None
    source_success_rate: float | None = None
    sources_planned: int = 0
    sources_successful: int = 0
    configs_planned: int = 0
    configs_completed: int = 0
    configs_successful: int = 0
    evaluation_signatures_unique: int = 0
    evaluation_runs_executed: int = 0
    evaluation_results_reused_in_run: int = 0
    evaluation_results_reused_cross_run: int = 0
    source_group_count: int = 0
    source_group_with_multiple_shards: int = 0
    report_json_path: str | None = None
    report_md_path: str | None = None


class _ExperimentFileV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    base_run_settings_file: str | None = None
    experiments: list[QualityExperiment]

    @model_validator(mode="after")
    def _validate_payload(self) -> "_ExperimentFileV1":
        seen_ids: set[str] = set()
        for experiment in self.experiments:
            if experiment.id in seen_ids:
                raise ValueError(f"Duplicate experiment id: {experiment.id}")
            seen_ids.add(experiment.id)
            _validate_patch_keys(
                experiment_id=experiment.id,
                patch=experiment.run_settings_patch,
            )
        if not self.experiments:
            raise ValueError("At least one experiment is required.")
        return self


class _ExperimentFileV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 2
    base_run_settings_file: str | None = None
    include_baseline: bool = True
    baseline_id: str = "baseline"
    include_all_on: bool = False
    all_on_id: str = "all_on"
    all_method_runtime: dict[str, Any] = Field(default_factory=dict)
    experiments: list[QualityExperimentV2] = Field(default_factory=list)
    levers: list[QualityLever] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_payload(self) -> "_ExperimentFileV2":
        for key in ("baseline_id", "all_on_id"):
            value = str(getattr(self, key) or "").strip()
            if not value:
                raise ValueError(f"{key} is required")
            if not _EXPERIMENT_ID_PATTERN.match(value):
                raise ValueError(
                    f"{key} must be slug-safe: lowercase letters, digits, '_' or '-'"
                )

        if self.all_method_runtime:
            _validate_all_method_runtime_patch_keys(
                context_id="all_method_runtime",
                patch=self.all_method_runtime,
            )

        for experiment in self.experiments:
            _validate_patch_keys(
                experiment_id=experiment.id,
                patch=experiment.run_settings_patch,
            )
            if experiment.all_method_runtime_patch:
                _validate_all_method_runtime_patch_keys(
                    context_id=f"experiment '{experiment.id}'",
                    patch=experiment.all_method_runtime_patch,
                )

        for lever in self.levers:
            _validate_patch_keys(
                experiment_id=lever.id,
                patch=lever.run_settings_patch,
            )
            if lever.all_method_runtime_patch:
                _validate_all_method_runtime_patch_keys(
                    context_id=f"lever '{lever.id}'",
                    patch=lever.all_method_runtime_patch,
                )

        if not self.experiments and not self.levers and not self.include_baseline:
            raise ValueError(
                "Schema v2 experiments file must include at least one of: "
                "experiments[], levers[], or include_baseline=true."
            )
        return self


@dataclass(frozen=True)
class _ResolvedExperiment:
    id: str
    run_settings_patch: dict[str, Any]
    requested_run_settings_payload: dict[str, Any]
    requested_run_settings: RunSettings
    run_settings_payload: dict[str, Any]
    run_settings: RunSettings
    all_method_runtime_patch: dict[str, Any]
    all_method_runtime: dict[str, Any]


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


def _truncate_subprocess_text(value: str, *, max_chars: int = 600) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _run_single_experiment_via_subprocess(
    *,
    experiment: _ResolvedExperiment,
    suite_targets: list[Any],
    run_root: Path,
    experiment_root: Path,
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
) -> QualityExperimentResult:
    request_path = experiment_root / _QUALITY_EXPERIMENT_WORKER_REQUEST_FILENAME
    result_path = experiment_root / _QUALITY_EXPERIMENT_WORKER_RESULT_FILENAME
    payload = {
        "experiment_id": experiment.id,
        "suite_targets": [
            target.model_dump() if hasattr(target, "model_dump") else dict(target)
            for target in suite_targets
        ],
        "run_root": str(run_root),
        "experiment_root": str(experiment_root),
        "run_settings_payload": experiment.run_settings.to_run_config_dict(),
        "all_method_runtime": dict(experiment.all_method_runtime),
        "include_markdown_extractors": bool(include_markdown_extractors),
        "include_codex_farm_requested": bool(include_codex_farm_requested),
        "include_codex_effective": bool(include_codex_effective),
        "canonical_alignment_cache_root": str(canonical_alignment_cache_root),
        "prediction_reuse_cache_root": str(prediction_reuse_cache_root),
        "search_strategy": str(search_strategy or "exhaustive"),
        "race_probe_targets": int(race_probe_targets),
        "race_mid_targets": int(race_mid_targets),
        "race_keep_ratio": float(race_keep_ratio),
        "race_finalists": int(race_finalists),
        "include_deterministic_sweeps": bool(include_deterministic_sweeps),
        "require_process_workers": bool(require_process_workers),
        "result_path": str(result_path),
    }
    request_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-m",
        "cookimport.bench.quality_runner",
        _QUALITY_EXPERIMENT_WORKER_REQUEST_ARG,
        str(request_path),
    ]
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    parsed_result: QualityExperimentResult | None = None
    if result_path.exists():
        try:
            parsed_result = QualityExperimentResult.model_validate(
                _load_json_dict(result_path)
            )
        except Exception as exc:  # noqa: BLE001
            parsed_result = QualityExperimentResult(
                id=experiment.id,
                status="failed",
                error=f"Invalid subprocess worker result payload: {exc}",
                run_settings_hash=experiment.run_settings.stable_hash(),
                run_settings_summary=experiment.run_settings.summary(),
            )

    if completed.returncode == 0 and parsed_result is not None:
        return parsed_result

    stdout_tail = _truncate_subprocess_text(str(completed.stdout or ""))
    stderr_tail = _truncate_subprocess_text(str(completed.stderr or ""))
    error_parts = [
        f"Subprocess experiment worker exited non-zero ({completed.returncode})."
    ]
    if stderr_tail:
        error_parts.append(f"stderr: {stderr_tail}")
    if stdout_tail:
        error_parts.append(f"stdout: {stdout_tail}")
    if parsed_result is not None and parsed_result.error:
        error_parts.append(f"worker_error: {parsed_result.error}")
    error_message = " ".join(error_parts).strip()
    return QualityExperimentResult(
        id=experiment.id,
        status="failed",
        error=error_message,
        run_settings_hash=experiment.run_settings.stable_hash(),
        run_settings_summary=experiment.run_settings.summary(),
    )


def _run_experiment_worker_request(request_path: Path) -> int:
    from cookimport.bench.quality_suite import QualityTarget

    payload = _load_json_dict(request_path)
    experiment_id = str(payload.get("experiment_id") or "").strip() or "unknown"
    result_path_raw = str(payload.get("result_path") or "").strip()
    result_path = Path(result_path_raw) if result_path_raw else None
    if result_path is None:
        raise ValueError("Experiment worker payload is missing result_path.")
    result_path.parent.mkdir(parents=True, exist_ok=True)

    run_settings_payload_raw = payload.get("run_settings_payload")
    run_settings_payload = (
        dict(run_settings_payload_raw)
        if isinstance(run_settings_payload_raw, dict)
        else {}
    )
    run_settings = RunSettings.from_dict(
        project_run_config_payload(
            run_settings_payload,
            contract=RUN_SETTING_CONTRACT_FULL,
        ),
        warn_context="quality experiment worker run settings",
    )
    suite_targets_raw = payload.get("suite_targets")
    suite_targets = (
        [
            QualityTarget.model_validate(item)
            for item in suite_targets_raw
            if isinstance(item, dict)
        ]
        if isinstance(suite_targets_raw, list)
        else []
    )
    all_method_runtime_raw = payload.get("all_method_runtime")
    all_method_runtime = (
        dict(all_method_runtime_raw)
        if isinstance(all_method_runtime_raw, dict)
        else {}
    )
    run_root = Path(str(payload.get("run_root") or ""))
    experiment_root = Path(str(payload.get("experiment_root") or ""))
    canonical_alignment_cache_root = Path(
        str(payload.get("canonical_alignment_cache_root") or "")
    )
    prediction_reuse_cache_root = Path(
        str(payload.get("prediction_reuse_cache_root") or "")
    )

    exit_code = 0
    try:
        result = _run_single_experiment(
            experiment_id=experiment_id,
            suite_targets=suite_targets,
            run_root=run_root,
            experiment_root=experiment_root,
            run_settings=run_settings,
            all_method_runtime=all_method_runtime,
            include_markdown_extractors=bool(payload.get("include_markdown_extractors")),
            include_codex_farm_requested=bool(payload.get("include_codex_farm_requested")),
            include_codex_effective=bool(payload.get("include_codex_effective")),
            canonical_alignment_cache_root=canonical_alignment_cache_root,
            prediction_reuse_cache_root=prediction_reuse_cache_root,
            search_strategy=str(payload.get("search_strategy") or "exhaustive"),
            race_probe_targets=_coerce_int(payload.get("race_probe_targets"), minimum=1),
            race_mid_targets=_coerce_int(payload.get("race_mid_targets"), minimum=1),
            race_keep_ratio=max(
                0.01,
                min(1.0, _coerce_float(payload.get("race_keep_ratio")) or 0.35),
            ),
            race_finalists=_coerce_int(payload.get("race_finalists"), minimum=1),
            include_deterministic_sweeps=bool(
                payload.get("include_deterministic_sweeps")
            ),
            require_process_workers=bool(payload.get("require_process_workers")),
            progress_callback=None,
        )
    except Exception as exc:  # noqa: BLE001
        exit_code = 1
        result = QualityExperimentResult(
            id=experiment_id,
            status="failed",
            error=str(exc),
            run_settings_hash=run_settings.stable_hash(),
            run_settings_summary=run_settings.summary(),
        )

    result_path.write_text(
        json.dumps(result.model_dump(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return exit_code


def _quality_experiment_result_snapshot_path(*, experiment_root: Path) -> Path:
    return experiment_root / _QUALITY_EXPERIMENT_RESULT_FILENAME


def _write_quality_experiment_result_snapshot(
    *,
    experiment_root: Path,
    result: QualityExperimentResult,
) -> None:
    snapshot_path = _quality_experiment_result_snapshot_path(
        experiment_root=experiment_root
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_quality_experiment_result_snapshot(
    *,
    experiment: _ResolvedExperiment,
    run_root: Path,
) -> QualityExperimentResult | None:
    experiment_root = run_root / "experiments" / experiment.id
    candidate_paths = [
        _quality_experiment_result_snapshot_path(experiment_root=experiment_root),
        experiment_root / _QUALITY_EXPERIMENT_WORKER_RESULT_FILENAME,
    ]
    parsed_result: QualityExperimentResult | None = None
    used_path: Path | None = None
    for candidate_path in candidate_paths:
        if not candidate_path.exists() or not candidate_path.is_file():
            continue
        try:
            parsed_result = QualityExperimentResult.model_validate(
                _load_json_dict(candidate_path)
            )
            used_path = candidate_path
            break
        except Exception:  # noqa: BLE001
            continue
    if parsed_result is None:
        return None

    result_id = str(parsed_result.id or "").strip()
    if result_id != experiment.id:
        return None

    expected_hash = experiment.run_settings.stable_hash()
    expected_summary = experiment.run_settings.summary()
    result_hash = str(parsed_result.run_settings_hash or "").strip()
    if result_hash and result_hash != expected_hash:
        return None
    if not result_hash or not str(parsed_result.run_settings_summary or "").strip():
        parsed_result = parsed_result.model_copy(
            update={
                "run_settings_hash": expected_hash,
                "run_settings_summary": expected_summary,
            }
        )

    canonical_path = _quality_experiment_result_snapshot_path(
        experiment_root=experiment_root
    )
    if used_path is not None and used_path != canonical_path:
        _write_quality_experiment_result_snapshot(
            experiment_root=experiment_root,
            result=parsed_result,
        )
    return parsed_result


def _resolved_experiment_identity_rows(
    experiments: list[_ResolvedExperiment],
) -> list[dict[str, str]]:
    return [
        {
            "id": experiment.id,
            "run_settings_hash": experiment.run_settings.stable_hash(),
        }
        for experiment in experiments
    ]


def _resolved_payload_identity_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows_raw = payload.get("experiments")
    if not isinstance(rows_raw, list):
        return []
    rows: list[dict[str, str]] = []
    for row in rows_raw:
        if not isinstance(row, dict):
            continue
        experiment_id = str(row.get("id") or "").strip()
        run_settings_hash = str(row.get("run_settings_hash") or "").strip()
        if not experiment_id:
            continue
        rows.append(
            {
                "id": experiment_id,
                "run_settings_hash": run_settings_hash,
            }
        )
    return rows


def _validate_resume_run_compatibility(
    *,
    run_root: Path,
    experiments: list[_ResolvedExperiment],
) -> None:
    resolved_path = run_root / "experiments_resolved.json"
    if not resolved_path.exists() or not resolved_path.is_file():
        return
    try:
        existing_payload = _load_json_dict(resolved_path)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"Failed to parse existing resume metadata: {resolved_path}: {exc}"
        ) from exc
    existing_rows = _resolved_payload_identity_rows(existing_payload)
    if not existing_rows:
        return
    expected_rows = _resolved_experiment_identity_rows(experiments)
    if existing_rows != expected_rows:
        raise ValueError(
            "Resume run directory experiment layout does not match requested "
            "suite/experiments. Use a fresh out directory or matching "
            "--resume-run-dir."
        )


def _resolve_resume_run_timestamp(*, run_root: Path) -> str | None:
    resolved_path = run_root / "experiments_resolved.json"
    if not resolved_path.exists() or not resolved_path.is_file():
        return None
    try:
        payload = _load_json_dict(resolved_path)
    except Exception:
        return None
    generated_at = str(payload.get("generated_at") or "").strip()
    return generated_at or None


def _write_quality_run_checkpoint(
    *,
    run_root: Path,
    suite: QualitySuite,
    run_timestamp: str,
    experiments: list[_ResolvedExperiment],
    results_by_index: list[QualityExperimentResult | None],
) -> None:
    completed_results = [result for result in results_by_index if result is not None]
    summary_payload = _build_summary_payload(
        suite=suite,
        run_timestamp=run_timestamp,
        experiments=experiments,
        results=completed_results,
    )
    completed_ids = [row.id for row in completed_results]
    pending_ids = [
        experiment.id
        for position, experiment in enumerate(experiments)
        if results_by_index[position] is None
    ]
    status = "complete" if not pending_ids else "in_progress"
    checkpoint_payload = {
        "schema_version": 1,
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
        "run_timestamp": run_timestamp,
        "status": status,
        "experiment_count_total": len(experiments),
        "experiment_count_completed": len(completed_results),
        "completed_experiment_ids": completed_ids,
        "pending_experiment_ids": pending_ids,
        "experiment_result_filename": _QUALITY_EXPERIMENT_RESULT_FILENAME,
        "partial_summary_path": _QUALITY_RUN_PARTIAL_SUMMARY_FILENAME,
        "partial_report_path": _QUALITY_RUN_PARTIAL_REPORT_FILENAME,
    }
    (run_root / _QUALITY_RUN_CHECKPOINT_FILENAME).write_text(
        json.dumps(checkpoint_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_root / _QUALITY_RUN_PARTIAL_SUMMARY_FILENAME).write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_root / _QUALITY_RUN_PARTIAL_REPORT_FILENAME).write_text(
        _format_quality_run_report(summary_payload),
        encoding="utf-8",
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


def load_quality_run_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists() or not summary_path.is_file():
        raise FileNotFoundError(f"Missing quality run summary: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid quality run summary payload: {summary_path}")
    return payload


def _notify_progress(
    progress_callback: ProgressCallback | None,
    message: str,
) -> None:
    if progress_callback is None:
        return
    progress_callback(message)


def _load_experiment_file(path: Path) -> _ExperimentFileV1 | _ExperimentFileV2:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to read experiments file: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Experiments file must contain a JSON object.")
    schema_version = payload.get("schema_version", 1)
    try:
        schema_version_int = int(schema_version)
    except (TypeError, ValueError):
        raise ValueError("schema_version must be an integer.") from None
    if schema_version_int not in _SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS:
        supported = ", ".join(str(v) for v in sorted(_SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS))
        raise ValueError(
            f"Unsupported schema_version {schema_version_int}. Supported: {supported}."
        )
    if schema_version_int == 1:
        return _ExperimentFileV1.model_validate(payload)
    return _ExperimentFileV2.model_validate(payload)


def _resolve_base_run_settings_payload(
    *,
    experiments_file: Path,
    experiment_payload: _ExperimentFileV1 | _ExperimentFileV2,
    base_run_settings_file: Path | None,
) -> dict[str, Any]:
    if base_run_settings_file is not None:
        return _read_json_object(
            base_run_settings_file,
            context="--base-run-settings-file",
        )

    embedded_path = str(experiment_payload.base_run_settings_file or "").strip()
    if embedded_path:
        embedded_candidate = Path(embedded_path)
        if not embedded_candidate.is_absolute():
            embedded_candidate = (experiments_file.parent / embedded_candidate).resolve()
        return _read_json_object(
            embedded_candidate,
            context="experiments.base_run_settings_file",
        )

    default_config = REPO_ROOT / "cookimport.json"
    if not default_config.exists() or not default_config.is_file():
        return {}
    return _read_json_object(default_config, context="cookimport.json")


def _read_json_object(path: Path, *, context: str) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise ValueError(f"{context} not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to parse {context}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{context} must contain a JSON object.")
    return dict(payload)


def _derive_all_method_runtime_base(base_payload: dict[str, Any]) -> dict[str, Any]:
    """Map cookimport.json-style all_method_* keys into all-method runtime kwargs."""
    mapped: dict[str, Any] = {"smart_scheduler": True}
    mapping = {
        "all_method_max_parallel_sources": "max_parallel_sources",
        "all_method_max_inflight_pipelines": "max_inflight_pipelines",
        "all_method_max_split_phase_slots": "max_concurrent_split_phases",
        "all_method_max_eval_tail_pipelines": "max_eval_tail_pipelines",
        "all_method_config_timeout_seconds": "config_timeout_seconds",
        "all_method_retry_failed_configs": "retry_failed_configs",
        "all_method_scheduler_scope": "scheduler_scope",
        "all_method_source_scheduling": "source_scheduling",
        "all_method_source_shard_threshold_seconds": "source_shard_threshold_seconds",
        "all_method_source_shard_max_parts": "source_shard_max_parts",
        "all_method_source_shard_min_variants": "source_shard_min_variants",
        "all_method_wing_backlog_target": "wing_backlog_target",
        "all_method_smart_scheduler": "smart_scheduler",
    }
    for src_key, dst_key in mapping.items():
        if src_key not in base_payload:
            continue
        mapped[dst_key] = base_payload.get(src_key)
    return mapped


def _validate_all_method_runtime_patch_keys(*, context_id: str, patch: dict[str, Any]) -> None:
    unknown_keys = sorted(set(patch) - _ALL_METHOD_RUNTIME_ALLOWED_KEYS)
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ValueError(
            f"{context_id} has unknown all_method_runtime_patch key(s): {joined}"
        )


def _merge_patches_strict(
    *,
    patches: list[tuple[str, dict[str, Any]]],
    kind: str,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    seen: dict[str, tuple[str, Any]] = {}
    for patch_id, patch in patches:
        for key, value in patch.items():
            if key in seen:
                prior_id, prior_value = seen[key]
                if prior_value != value:
                    raise ValueError(
                        f"Conflicting {kind} key {key!r}: {prior_id}={prior_value!r} vs {patch_id}={value!r}"
                    )
                continue
            seen[key] = (patch_id, value)
            merged[key] = value
    return merged


def _validate_qualitysuite_requested_settings_disallow_codex_farm(
    *,
    experiment_id: str,
    payload: dict[str, Any],
) -> None:
    surface = classify_codex_surfaces(payload)
    disallowed_surfaces = [
        name
        for enabled, name in (
            (surface.recipe_codex_enabled, "recipe"),
            (surface.knowledge_codex_enabled, "knowledge"),
            (surface.tags_codex_enabled, "tags"),
        )
        if enabled
    ]
    if disallowed_surfaces:
        joined = ", ".join(disallowed_surfaces)
        raise ValueError(
            "QualitySuite forbids Codex Farm-enabled requested settings. "
            f"Experiment '{experiment_id}' enabled: {joined}."
        )


def _expand_experiments(
    payload: _ExperimentFileV1 | _ExperimentFileV2,
) -> list[QualityExperimentV2]:
    if isinstance(payload, _ExperimentFileV1):
        return [
            QualityExperimentV2(
                id=exp.id,
                run_settings_patch=dict(exp.run_settings_patch),
                all_method_runtime_patch={},
            )
            for exp in payload.experiments
        ]

    experiments: list[QualityExperimentV2] = []
    if payload.include_baseline:
        experiments.append(QualityExperimentV2(id=payload.baseline_id))

    experiments.extend(payload.experiments)

    enabled_levers = [lever for lever in payload.levers if lever.enabled]
    for lever in enabled_levers:
        experiments.append(
            QualityExperimentV2(
                id=lever.id,
                run_settings_patch=dict(lever.run_settings_patch),
                all_method_runtime_patch=dict(lever.all_method_runtime_patch),
            )
        )

    if payload.include_all_on:
        if not enabled_levers:
            raise ValueError("include_all_on=true requires at least one enabled lever.")
        run_settings_patch = _merge_patches_strict(
            patches=[
                (lever.id, dict(lever.run_settings_patch))
                for lever in enabled_levers
                if lever.run_settings_patch
            ],
            kind="run_settings_patch",
        )
        runtime_patch = _merge_patches_strict(
            patches=[
                (lever.id, dict(lever.all_method_runtime_patch))
                for lever in enabled_levers
                if lever.all_method_runtime_patch
            ],
            kind="all_method_runtime_patch",
        )
        experiments.append(
            QualityExperimentV2(
                id=payload.all_on_id,
                run_settings_patch=run_settings_patch,
                all_method_runtime_patch=runtime_patch,
            )
        )

    seen_ids: set[str] = set()
    duplicates: list[str] = []
    for exp in experiments:
        if exp.id in seen_ids:
            duplicates.append(exp.id)
            continue
        seen_ids.add(exp.id)
    if duplicates:
        joined = ", ".join(sorted(set(duplicates)))
        raise ValueError(f"Duplicate experiment id(s) after lever expansion: {joined}")

    if not experiments:
        raise ValueError("No experiments were generated from this experiments file.")
    return experiments


def _resolve_experiments(
    *,
    experiments: list[QualityExperimentV2],
    base_payload: dict[str, Any],
    all_method_runtime_base: dict[str, Any],
) -> list[_ResolvedExperiment]:
    benchmark_base_payload = apply_benchmark_baseline_contract(base_payload)
    resolved: list[_ResolvedExperiment] = []
    for experiment in experiments:
        requested_payload = dict(base_payload)
        requested_payload.update(dict(experiment.run_settings_patch))
        # Reject Codex-enabled requests before benchmark baseline coercion can mask them.
        _validate_qualitysuite_requested_settings_disallow_codex_farm(
            experiment_id=experiment.id,
            payload=requested_payload,
        )
        merged_payload = dict(benchmark_base_payload)
        merged_payload.update(dict(experiment.run_settings_patch))
        requested_run_settings = RunSettings.from_dict(
            project_run_config_payload(
                merged_payload,
                contract=RUN_SETTING_CONTRACT_FULL,
            ),
            warn_context=f"quality-run experiment {experiment.id}",
        )
        requested_run_settings_payload = requested_run_settings.to_run_config_dict()
        run_settings_payload = dict(requested_run_settings_payload)
        run_settings = RunSettings.from_dict(
            project_run_config_payload(
                run_settings_payload,
                contract=RUN_SETTING_CONTRACT_FULL,
            ),
            warn_context=f"quality-run experiment {experiment.id} benchmark baseline",
        )
        runtime_payload = dict(all_method_runtime_base)
        runtime_payload.update(dict(experiment.all_method_runtime_patch))
        resolved.append(
            _ResolvedExperiment(
                id=experiment.id,
                run_settings_patch=dict(experiment.run_settings_patch),
                requested_run_settings_payload=requested_run_settings_payload,
                requested_run_settings=requested_run_settings,
                run_settings_payload=run_settings_payload,
                run_settings=run_settings,
                all_method_runtime_patch=dict(experiment.all_method_runtime_patch),
                all_method_runtime=runtime_payload,
            )
        )
    return resolved


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


def _summarize_experiment_report(
    *,
    experiment_root: Path,
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    source_groups = _aggregate_source_groups(
        experiment_root=experiment_root,
        report_payload=report_payload,
    )
    strict_precision_values = [
        row["strict_precision"]
        for row in source_groups
        if row["status"] == "ok" and row["strict_precision"] is not None
    ]
    strict_recall_values = [
        row["strict_recall"]
        for row in source_groups
        if row["status"] == "ok" and row["strict_recall"] is not None
    ]
    strict_f1_values = [
        row["strict_f1"]
        for row in source_groups
        if row["status"] == "ok" and row["strict_f1"] is not None
    ]
    practical_precision_values = [
        row["practical_precision"]
        for row in source_groups
        if row["status"] == "ok" and row["practical_precision"] is not None
    ]
    practical_recall_values = [
        row["practical_recall"]
        for row in source_groups
        if row["status"] == "ok" and row["practical_recall"] is not None
    ]
    practical_f1_values = [
        row["practical_f1"]
        for row in source_groups
        if row["status"] == "ok" and row["practical_f1"] is not None
    ]

    sources_planned = _coerce_int(report_payload.get("matched_target_count"))
    if sources_planned <= 0:
        sources_planned = len(source_groups)
    sources_successful = sum(1 for row in source_groups if row["status"] == "ok")
    source_success_rate = (
        float(sources_successful) / float(sources_planned)
        if sources_planned > 0
        else None
    )

    configs_planned = _coerce_int(report_payload.get("total_config_runs_planned"))
    configs_completed = _coerce_int(report_payload.get("total_config_runs_completed"))
    configs_successful = _coerce_int(report_payload.get("total_config_runs_successful"))

    failed_groups = [row for row in source_groups if row["status"] != "ok"]
    status = "ok"
    error = None
    if sources_planned <= 0 or sources_successful <= 0:
        status = "incomplete"
        error = "No successful source groups were evaluated."
    elif failed_groups:
        status = "incomplete"
        error = f"{len(failed_groups)} source group(s) failed."
    elif configs_planned > 0 and configs_successful < configs_planned:
        status = "incomplete"
        error = (
            f"Config success is incomplete ({configs_successful}/{configs_planned})."
        )

    return {
        "status": status,
        "error": error,
        "strict_precision_macro": _mean_or_none(strict_precision_values),
        "strict_recall_macro": _mean_or_none(strict_recall_values),
        "strict_f1_macro": _mean_or_none(strict_f1_values),
        "practical_precision_macro": _mean_or_none(practical_precision_values),
        "practical_recall_macro": _mean_or_none(practical_recall_values),
        "practical_f1_macro": _mean_or_none(practical_f1_values),
        "source_success_rate": source_success_rate,
        "sources_planned": sources_planned,
        "sources_successful": sources_successful,
        "configs_planned": configs_planned,
        "configs_completed": configs_completed,
        "configs_successful": configs_successful,
        "evaluation_signatures_unique": _coerce_int(
            report_payload.get("evaluation_signatures_unique")
        ),
        "evaluation_runs_executed": _coerce_int(
            report_payload.get("evaluation_runs_executed")
        ),
        "evaluation_results_reused_in_run": _coerce_int(
            report_payload.get("evaluation_results_reused_in_run")
        ),
        "evaluation_results_reused_cross_run": _coerce_int(
            report_payload.get("evaluation_results_reused_cross_run")
        ),
        "source_group_count": len(source_groups),
        "source_group_with_multiple_shards": sum(
            1 for row in source_groups if row["shard_count"] > 1
        ),
    }


def _aggregate_source_groups(
    *,
    experiment_root: Path,
    report_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    source_rows = report_payload.get("sources")
    if not isinstance(source_rows, list):
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        source_group_key = str(row.get("source_group_key") or "").strip()
        if not source_group_key:
            source_group_key = str(row.get("source_file_name") or "").strip()
        if not source_group_key:
            source_group_key = str(row.get("source_file") or "").strip()
        if not source_group_key:
            continue
        grouped.setdefault(source_group_key, []).append(row)

    aggregated: list[dict[str, Any]] = []
    for source_group_key, rows in sorted(grouped.items()):
        shard_candidates: list[tuple[float, dict[str, Any], str | None]] = []
        row_status = "ok"
        row_errors: list[str] = []
        max_shard_total = 1

        for row in rows:
            status = str(row.get("status") or "").strip().lower()
            if status != "ok":
                row_status = "failed"
                error_text = str(row.get("error") or "").strip()
                if error_text:
                    row_errors.append(error_text)
            max_shard_total = max(max_shard_total, _coerce_int(row.get("source_shard_total"), minimum=1))
            for report_json_path in _candidate_report_json_paths(row):
                report_payload_for_source = _load_source_report(
                    experiment_root=experiment_root,
                    report_json_path=report_json_path,
                )
                if report_payload_for_source is None:
                    continue
                winner = report_payload_for_source.get("winner_by_f1")
                if not isinstance(winner, dict):
                    continue
                strict_f1 = _coerce_float(winner.get("f1"))
                if strict_f1 is None:
                    continue
                shard_candidates.append((strict_f1, winner, report_json_path))

        chosen_winner: dict[str, Any] | None = None
        if shard_candidates:
            shard_candidates.sort(key=lambda row: row[0], reverse=True)
            chosen_winner = shard_candidates[0][1]
            max_shard_total = max(max_shard_total, len(shard_candidates))
        else:
            fallback_row = rows[0]
            winner_metrics = fallback_row.get("winner_metrics")
            if isinstance(winner_metrics, dict):
                chosen_winner = dict(winner_metrics)

        strict_precision = _coerce_float(
            chosen_winner.get("precision") if isinstance(chosen_winner, dict) else None
        )
        strict_recall = _coerce_float(
            chosen_winner.get("recall") if isinstance(chosen_winner, dict) else None
        )
        strict_f1 = _coerce_float(
            chosen_winner.get("f1") if isinstance(chosen_winner, dict) else None
        )
        practical_precision = _coerce_float(
            chosen_winner.get("practical_precision")
            if isinstance(chosen_winner, dict)
            else None
        )
        practical_recall = _coerce_float(
            chosen_winner.get("practical_recall")
            if isinstance(chosen_winner, dict)
            else None
        )
        practical_f1 = _coerce_float(
            chosen_winner.get("practical_f1")
            if isinstance(chosen_winner, dict)
            else None
        )

        aggregated.append(
            {
                "source_group_key": source_group_key,
                "status": row_status,
                "error": " | ".join(row_errors) if row_errors else None,
                "strict_precision": strict_precision,
                "strict_recall": strict_recall,
                "strict_f1": strict_f1,
                "practical_precision": practical_precision,
                "practical_recall": practical_recall,
                "practical_f1": practical_f1,
                "shard_count": max_shard_total,
            }
        )

    return aggregated


def _candidate_report_json_paths(row: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    list_payload = row.get("report_json_paths")
    if isinstance(list_payload, list):
        for item in list_payload:
            rendered = str(item or "").strip()
            if rendered:
                paths.append(rendered)
    single_payload = str(row.get("report_json_path") or "").strip()
    if single_payload:
        paths.append(single_payload)

    deduped: list[str] = []
    seen: set[str] = set()
    for path_value in paths:
        if path_value in seen:
            continue
        seen.add(path_value)
        deduped.append(path_value)
    return deduped


def _load_source_report(
    *,
    experiment_root: Path,
    report_json_path: str,
) -> dict[str, Any] | None:
    candidate = Path(report_json_path)
    if not candidate.is_absolute():
        candidate = experiment_root / candidate
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _build_summary_payload(
    *,
    suite: QualitySuite,
    run_timestamp: str,
    experiments: list[_ResolvedExperiment],
    results: list[QualityExperimentResult],
) -> dict[str, Any]:
    result_rows = [result.model_dump(mode="json") for result in results]
    selected_targets = _resolve_selected_targets(suite)
    format_counts = _target_format_counts(list(suite.targets))
    selected_format_counts = _target_format_counts(selected_targets)
    run_settings_by_id = {
        experiment.id: {
            "run_settings": experiment.run_settings.to_run_config_dict(),
            "run_settings_summary": experiment.run_settings.summary(),
            "run_settings_hash": experiment.run_settings.stable_hash(),
            "requested_run_settings": (
                experiment.requested_run_settings.to_run_config_dict()
            ),
            "requested_run_settings_summary": (
                experiment.requested_run_settings.summary()
            ),
            "requested_run_settings_hash": (
                experiment.requested_run_settings.stable_hash()
            ),
        }
        for experiment in experiments
    }

    return {
        "schema_version": 1,
        "run_timestamp": run_timestamp,
        "suite_name": suite.name,
        "suite_generated_at": suite.generated_at,
        "selection_algorithm_version": str(suite.selection.get("algorithm_version") or ""),
        "target_count_total": len(suite.targets),
        "target_count_selected": len(selected_targets),
        "format_counts": format_counts,
        "selected_format_counts": selected_format_counts,
        "experiment_count": len(results),
        "successful_experiments": sum(1 for row in results if row.status == "ok"),
        "incomplete_experiments": sum(1 for row in results if row.status == "incomplete"),
        "failed_experiments": sum(1 for row in results if row.status == "failed"),
        "experiments": result_rows,
        "run_settings_by_experiment": run_settings_by_id,
    }


def _format_quality_run_report(summary_payload: dict[str, Any]) -> str:
    def _render_format_counts(value: Any) -> str:
        if not isinstance(value, dict) or not value:
            return "n/a"
        rendered_parts = []
        for key in sorted(value):
            rendered_parts.append(f"{key}={value[key]}")
        return ", ".join(rendered_parts)

    lines = [
        "# Quality Suite Report",
        "",
        f"- Run timestamp: {summary_payload.get('run_timestamp')}",
        f"- Suite: {summary_payload.get('suite_name')}",
        f"- Targets selected: {summary_payload.get('target_count_selected')}",
        f"- Selected formats: {_render_format_counts(summary_payload.get('selected_format_counts'))}",
        f"- Matched formats: {_render_format_counts(summary_payload.get('format_counts'))}",
        f"- Experiments: {summary_payload.get('experiment_count')}",
        f"- Successful: {summary_payload.get('successful_experiments')}",
        f"- Incomplete: {summary_payload.get('incomplete_experiments')}",
        f"- Failed: {summary_payload.get('failed_experiments')}",
        "- Codex decision: "
        f"{((summary_payload.get('codex_execution_policy') or {}).get('codex_execution_summary') or 'n/a')}",
        "",
        "## Experiments",
        "",
    ]
    for row in summary_payload.get("experiments", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            "- "
            f"{row.get('id')} | status={row.get('status')} | "
            f"strict_f1_macro={_render_metric(row.get('strict_f1_macro'))} | "
            f"practical_f1_macro={_render_metric(row.get('practical_f1_macro'))} | "
            f"source_success_rate={_render_metric(row.get('source_success_rate'))} | "
            f"settings_hash={row.get('run_settings_hash') or 'n/a'}"
        )
        report_md_path = str(row.get("report_md_path") or "").strip()
        report_json_path = str(row.get("report_json_path") or "").strip()
        if report_md_path or report_json_path:
            report_bits = []
            if report_md_path:
                report_bits.append(f"md={report_md_path}")
            if report_json_path:
                report_bits.append(f"json={report_json_path}")
            lines.append(f"  report: {', '.join(report_bits)}")
        error_text = str(row.get("error") or "").strip()
        if error_text:
            lines.append(f"  error: {error_text}")
        artifacts = row.get("line_role_artifacts")
        if isinstance(artifacts, dict):
            eval_dir_count = _coerce_int(artifacts.get("line_role_eval_dir_count"))
            lines.append(f"  line-role: eval_dirs={eval_dir_count}")
            gate_counts = artifacts.get("gate_verdict_counts")
            if isinstance(gate_counts, dict) and gate_counts:
                rendered = ", ".join(f"{k}={gate_counts[k]}" for k in sorted(gate_counts))
                lines.append(f"  line-role gates: {rendered}")
            examples = artifacts.get("examples")
            if isinstance(examples, list) and examples:
                example = examples[0] if isinstance(examples[0], dict) else None
                if isinstance(example, dict):
                    line_role_dir = str(example.get("line_role_dir") or "").strip()
                    if line_role_dir:
                        lines.append(f"  line-role sample: {line_role_dir}")
                    joined = str(example.get("joined_line_table_jsonl") or "").strip()
                    flips = str(example.get("line_role_flips_vs_baseline_jsonl") or "").strip()
                    slice_path = str(example.get("slice_metrics_json") or "").strip()
                    kb_path = str(example.get("knowledge_budget_json") or "").strip()
                    gates_path = str(example.get("regression_gates_json") or "").strip()
                    if joined or flips or slice_path or kb_path or gates_path:
                        artifact_bits = []
                        if joined:
                            artifact_bits.append(f"joined={joined}")
                        if flips:
                            artifact_bits.append(f"flips={flips}")
                        if slice_path:
                            artifact_bits.append(f"slices={slice_path}")
                        if kb_path:
                            artifact_bits.append(f"knowledge={kb_path}")
                        if gates_path:
                            artifact_bits.append(f"gates={gates_path}")
                        lines.append(f"  line-role artifacts (sample): {', '.join(artifact_bits)}")
                    slice_summary = example.get("slice_metrics_summary")
                    if isinstance(slice_summary, dict) and slice_summary:
                        # Keep report short: just show line counts for each slice.
                        slice_counts = ", ".join(
                            f"{name}={_coerce_int((slice_summary.get(name) or {}).get('line_count'))}"
                            for name in sorted(slice_summary)
                        )
                        lines.append(f"  line-role slices (sample): {slice_counts}")
                    kb = example.get("knowledge_budget_summary")
                    if isinstance(kb, dict) and kb:
                        total = _coerce_int(kb.get("knowledge_pred_total"))
                        inside = _coerce_int(kb.get("knowledge_pred_inside_recipe"))
                        outside = _coerce_int(kb.get("knowledge_pred_outside_recipe"))
                        lines.append(
                            f"  knowledge (sample): total={total}, inside_recipe={inside}, outside_recipe={outside}"
                        )
    lines.append("")
    return "\n".join(lines)


def _validate_patch_keys(*, experiment_id: str, patch: dict[str, Any]) -> None:
    known_fields = set(RunSettings.model_fields) | _RUN_SETTINGS_PATCH_COMPAT_KEYS
    unknown_keys = sorted(set(patch) - known_fields)
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ValueError(
            f"Experiment '{experiment_id}' has unknown run_settings_patch key(s): {joined}"
        )


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _relative_to_run_root(path: Path, run_root: Path) -> str:
    try:
        return str(path.relative_to(run_root))
    except ValueError:
        return str(path)


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.mean(values))


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, numeric)


def _coerce_int(value: Any, *, minimum: int = 0) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, numeric)


def _render_metric(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.4f}"


def _load_json_object_or_none(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _summarize_line_role_artifacts(
    *,
    experiment_root: Path,
    run_root: Path,
    max_examples: int = 8,
) -> dict[str, Any] | None:
    """Best-effort detector for line-role pipeline artifacts under an experiment root.

    This must never raise: QualitySuite should still complete/report even when the
    line-role pipeline was not enabled or artifacts are partially missing.
    """
    if max_examples < 1:
        max_examples = 1

    # In labelstudio-benchmark runs these artifacts live under:
    # <eval_output_dir>/line-role-pipeline/<artifact>
    slice_metric_paths = list(
        experiment_root.glob("**/line-role-pipeline/slice_metrics.json")
    )
    if not slice_metric_paths:
        return None

    line_role_dirs = sorted({path.parent for path in slice_metric_paths}, key=str)
    example_dirs = line_role_dirs[: max_examples]

    def _rel(path: Path) -> str:
        return _relative_to_run_root(path, run_root)

    examples: list[dict[str, Any]] = []
    gate_verdict_counts: dict[str, int] = {}
    for line_role_dir in example_dirs:
        joined_path = line_role_dir / "joined_line_table.jsonl"
        flips_path = line_role_dir / "line_role_flips_vs_baseline.jsonl"
        slice_path = line_role_dir / "slice_metrics.json"
        knowledge_path = line_role_dir / "knowledge_budget.json"
        gates_path = line_role_dir / "regression_gates.json"

        slice_payload = _load_json_object_or_none(slice_path) or {}
        knowledge_payload = _load_json_object_or_none(knowledge_path) or {}
        pass4_merge_summary_payload = _load_json_object_or_none(pass4_merge_summary_path) or {}
        gates_payload = _load_json_object_or_none(gates_path) or {}

        gates_verdict = str(
            ((gates_payload.get("overall") or {}).get("verdict")) or ""
        ).strip().upper()
        if gates_verdict:
            gate_verdict_counts[gates_verdict] = gate_verdict_counts.get(gates_verdict, 0) + 1

        slices_summary: dict[str, Any] = {}
        slices_payload = slice_payload.get("slices")
        if isinstance(slices_payload, dict):
            for slice_name in sorted(slices_payload):
                slice_row = slices_payload.get(slice_name)
                if not isinstance(slice_row, dict):
                    continue
                slices_summary[str(slice_name)] = {
                    "line_count": _coerce_int(slice_row.get("line_count")),
                    "overall_line_accuracy": _coerce_float(
                        slice_row.get("overall_line_accuracy")
                    ),
                    "macro_f1_excluding_other": _coerce_float(
                        slice_row.get("macro_f1_excluding_other")
                    ),
                }

        examples.append(
            {
                "line_role_dir": _rel(line_role_dir),
                "joined_line_table_jsonl": _rel(joined_path) if joined_path.exists() else None,
                "line_role_flips_vs_baseline_jsonl": _rel(flips_path) if flips_path.exists() else None,
                "slice_metrics_json": _rel(slice_path) if slice_path.exists() else None,
                "knowledge_budget_json": _rel(knowledge_path) if knowledge_path.exists() else None,
                "regression_gates_json": _rel(gates_path) if gates_path.exists() else None,
                "regression_gates_verdict": gates_verdict or None,
                "slice_metrics_summary": slices_summary,
                "knowledge_budget_summary": {
                    "knowledge_pred_total": _coerce_int(knowledge_payload.get("knowledge_pred_total")),
                    "knowledge_pred_inside_recipe": _coerce_int(
                        knowledge_payload.get("knowledge_pred_inside_recipe")
                    ),
                    "knowledge_pred_outside_recipe": _coerce_int(
                        knowledge_payload.get("knowledge_pred_outside_recipe")
                    ),
                    "knowledge_inside_ratio": _coerce_float(
                        knowledge_payload.get("knowledge_inside_ratio")
                    ),
                }
                if knowledge_payload
                else {},
                "pass4_merge_summary": pass4_merge_summary_payload,
            }
        )

    return {
        "schema_version": "quality_line_role_artifacts.v1",
        "line_role_eval_dir_count": len(line_role_dirs),
        "examples": examples,
        "gate_verdict_counts": dict(sorted(gate_verdict_counts.items())),
    }


def _build_worker_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cookimport.bench.quality_runner",
        add_help=True,
    )
    parser.add_argument(
        _QUALITY_EXPERIMENT_WORKER_REQUEST_ARG,
        dest="experiment_worker_request",
        type=str,
        default="",
        help="Internal worker mode: run one experiment from a request JSON file.",
    )
    return parser


def _main(argv: list[str] | None = None) -> int:
    parser = _build_worker_cli_parser()
    args = parser.parse_args(argv)
    request_path_raw = str(getattr(args, "experiment_worker_request", "") or "").strip()
    if not request_path_raw:
        parser.error(
            f"{_QUALITY_EXPERIMENT_WORKER_REQUEST_ARG} is required when invoking this module directly."
        )
    return _run_experiment_worker_request(Path(request_path_raw).expanduser())


if __name__ == "__main__":
    raise SystemExit(_main())
