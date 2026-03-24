"""Public QualitySuite compatibility facade.

`cookimport.bench.qualitysuite/` owns the active runtime implementation.
This module keeps the historical import surface and monkeypatch hooks that
tests and subprocess worker entrypoints still use.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from cookimport.bench.quality_suite import QualitySuite
from cookimport.bench.qualitysuite import environment as _environment
from cookimport.bench.qualitysuite import runtime as _runtime
from cookimport.bench.qualitysuite import worker_cli as _worker_cli
from cookimport.bench.qualitysuite.environment import (
    _resolve_quality_experiment_executor_mode,
    _running_in_wsl,
)
from cookimport.bench.qualitysuite.runtime import (
    _resolve_quality_alignment_cache_root,
    _resolve_quality_prediction_reuse_cache_root,
    _run_single_experiment,
)
from cookimport.bench.qualitysuite.summary import (
    QualityExperimentResult,
    load_quality_run_summary,
)
from cookimport.bench.qualitysuite.worker_cli import (
    _run_experiment_worker_request,
    _run_single_experiment_via_subprocess,
)


ProgressCallback = Callable[[str], None]


def _sync_qualitysuite_runtime_compat() -> None:
    # Tests still patch helper names on this historical module. Before each run,
    # mirror the current compatibility hooks into the real implementation modules.
    _runtime._running_in_wsl = _running_in_wsl
    _runtime._resolve_quality_experiment_executor_mode = (
        _resolve_quality_experiment_executor_mode
    )
    _runtime._run_single_experiment = _run_single_experiment
    _runtime._run_single_experiment_via_subprocess = (
        _run_single_experiment_via_subprocess
    )
    _worker_cli._run_single_experiment = _run_single_experiment
    _environment._running_in_wsl = _running_in_wsl
    _environment._resolve_quality_experiment_executor_mode = (
        _resolve_quality_experiment_executor_mode
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
    _sync_qualitysuite_runtime_compat()
    return _runtime.run_quality_suite(
        suite,
        out_dir,
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        search_strategy=search_strategy,
        race_probe_targets=race_probe_targets,
        race_mid_targets=race_mid_targets,
        race_keep_ratio=race_keep_ratio,
        race_finalists=race_finalists,
        include_deterministic_sweeps_requested=include_deterministic_sweeps_requested,
        include_codex_farm_requested=include_codex_farm_requested,
        codex_farm_confirmed=codex_farm_confirmed,
        codex_farm_model=codex_farm_model,
        codex_farm_reasoning_effort=codex_farm_reasoning_effort,
        max_parallel_experiments=max_parallel_experiments,
        require_process_workers=require_process_workers,
        resume_run_dir=resume_run_dir,
        progress_callback=progress_callback,
    )


def _main(argv: list[str] | None = None) -> int:
    return _worker_cli._main(argv)


if __name__ == "__main__":
    raise SystemExit(_main())
