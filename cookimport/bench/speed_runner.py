"""Speed-suite execution for import and benchmark runtime scenarios."""

from __future__ import annotations

import datetime as dt
import contextlib
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import io
import json
import os
import statistics
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from cookimport.bench.speed_suite import SpeedSuite, SpeedTarget, resolve_repo_path
from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_adapters import (
    build_benchmark_call_kwargs_from_run_settings,
    build_stage_call_kwargs_from_run_settings,
)
from cookimport.core.progress_messages import format_task_counter
from cookimport.paths import REPO_ROOT
from cookimport.runs import RunManifest, RunSource, write_run_manifest


class SpeedScenario(str, Enum):
    STAGE_IMPORT = "stage_import"
    BENCHMARK_CANONICAL_LEGACY = "benchmark_canonical_legacy"
    BENCHMARK_CANONICAL_PIPELINED = "benchmark_canonical_pipelined"
    BENCHMARK_ALL_METHOD_MULTI_SOURCE = "benchmark_all_method_multi_source"


SPEED_SUITE_ALL_MATCHED_TARGET_ID = "__all_matched__"
_SPEED_SUITE_ALL_MATCHED_TARGET_DIR = "_all_matched"
_SPEED_SAMPLE_RESULT_FILENAME = "speed_sample_result.json"
_SPEED_RUN_CHECKPOINT_FILENAME = "checkpoint.json"
_SPEED_RUN_PARTIAL_SUMMARY_FILENAME = "summary.partial.json"
_SPEED_RUN_PARTIAL_REPORT_FILENAME = "report.partial.md"
_SPEED_RUN_PARTIAL_SAMPLES_FILENAME = "samples.partial.jsonl"
_SPEED_AUTO_MAX_PARALLEL_TASKS = 4


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class _SpeedTask:
    index: int
    total: int
    scenario: SpeedScenario
    target: SpeedTarget | None
    phase: str
    phase_index: int


def run_speed_suite(
    suite: SpeedSuite,
    out_dir: Path,
    *,
    scenarios: list[SpeedScenario],
    warmups: int,
    repeats: int,
    max_targets: int | None = None,
    max_parallel_tasks: int | None = None,
    require_process_workers: bool = False,
    resume_run_dir: Path | None = None,
    run_settings: RunSettings,
    include_codex_farm_requested: bool = False,
    codex_farm_confirmed: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    if warmups < 0:
        raise ValueError("warmups must be >= 0")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if not scenarios:
        raise ValueError("At least one scenario is required.")
    if include_codex_farm_requested and not codex_farm_confirmed:
        raise ValueError(
            "SpeedSuite Codex Farm permutations require explicit positive user "
            "confirmation. Set codex_farm_confirmed=True only after user approval."
        )

    selected_targets = list(suite.targets)
    if max_targets is not None:
        selected_targets = selected_targets[: max(0, max_targets)]
    if not selected_targets:
        raise ValueError("No speed targets selected for this run.")

    run_started = dt.datetime.now()
    if resume_run_dir is not None:
        run_root = Path(resume_run_dir).expanduser()
        if not run_root.exists() or not run_root.is_dir():
            raise ValueError(
                f"--resume-run-dir must point to an existing speed run directory: {run_root}"
            )
        run_timestamp = _resolve_speed_resume_run_timestamp(run_root=run_root) or (
            str(run_root.name or "").strip() or run_started.strftime("%Y-%m-%d_%H.%M.%S")
        )
    else:
        run_timestamp = run_started.strftime("%Y-%m-%d_%H.%M.%S")
        run_root = out_dir / run_timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    suite_payload = suite.model_dump()
    suite_payload["targets"] = [target.model_dump() for target in selected_targets]
    suite_payload["target_count_selected"] = len(selected_targets)
    suite_payload["target_count_total"] = len(suite.targets)
    (run_root / "suite_resolved.json").write_text(
        json.dumps(suite_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tasks = _build_speed_tasks(
        selected_targets=selected_targets,
        scenarios=scenarios,
        warmups=warmups,
        repeats=repeats,
    )
    total_tasks = len(tasks)
    if total_tasks <= 0:
        raise ValueError("No speed tasks resolved for this run.")

    parallel_tasks_effective, parallel_tasks_mode, cpu_count = (
        _resolve_speed_parallel_tasks_cap(
            requested=max_parallel_tasks,
            total_tasks=total_tasks,
        )
    )
    process_worker_probe_available, process_worker_probe_error = (
        _probe_process_worker_availability()
    )

    run_config_payload = {
        "suite_name": suite.name,
        "suite_generated_at": str(suite.generated_at),
        "target_ids": [str(target.target_id) for target in selected_targets],
        "scenarios": [scenario.value for scenario in scenarios],
        "warmups": int(warmups),
        "repeats": int(repeats),
        "max_targets": max_targets,
        "run_settings_hash": run_settings.stable_hash(),
        "require_process_workers": bool(require_process_workers),
        "include_codex_farm_requested": bool(include_codex_farm_requested),
        "include_codex_farm_confirmed": bool(codex_farm_confirmed),
    }
    if resume_run_dir is not None:
        _validate_speed_resume_compatibility(
            run_root=run_root,
            run_config=run_config_payload,
        )

    progress_lock = threading.Lock()

    def _notify(message: str) -> None:
        if progress_callback is None:
            return
        with progress_lock:
            progress_callback(message)

    sample_rows_by_index: list[dict[str, Any] | None] = [None] * total_tasks
    if resume_run_dir is not None:
        for task in tasks:
            resumed_row = _load_speed_task_snapshot(run_root=run_root, task=task)
            if resumed_row is None:
                continue
            sample_rows_by_index[task.index - 1] = resumed_row
    resumed_completed_count = sum(row is not None for row in sample_rows_by_index)
    if resumed_completed_count > 0:
        _notify(
            "Speed suite resume: "
            f"reusing {resumed_completed_count}/{total_tasks} completed tasks from {run_root}"
        )

    def _ordered_sample_rows() -> list[dict[str, Any]]:
        return [row for row in sample_rows_by_index if row is not None]

    def _write_checkpoint(status: str) -> None:
        rows = _ordered_sample_rows()
        _write_samples_jsonl(run_root / _SPEED_RUN_PARTIAL_SAMPLES_FILENAME, rows)
        partial_summary = _build_summary_payload(
            suite=suite,
            selected_targets=selected_targets,
            scenarios=scenarios,
            warmups=warmups,
            repeats=repeats,
            run_timestamp=run_timestamp,
            run_settings=run_settings,
            include_codex_farm_requested=include_codex_farm_requested,
            codex_farm_confirmed=codex_farm_confirmed,
            sample_rows=rows,
            parallel_tasks_requested=max_parallel_tasks,
            parallel_tasks_effective=parallel_tasks_effective,
            parallel_tasks_mode=parallel_tasks_mode,
            parallel_tasks_cpu_count=cpu_count,
            require_process_workers=bool(require_process_workers),
            process_worker_probe_available=process_worker_probe_available,
            process_worker_probe_error=process_worker_probe_error,
            resume_requested=bool(resume_run_dir is not None),
        )
        (run_root / _SPEED_RUN_PARTIAL_SUMMARY_FILENAME).write_text(
            json.dumps(partial_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (run_root / _SPEED_RUN_PARTIAL_REPORT_FILENAME).write_text(
            _format_speed_run_report(partial_summary),
            encoding="utf-8",
        )
        completed_indices = [
            index + 1
            for index, row in enumerate(sample_rows_by_index)
            if row is not None
        ]
        pending_indices = [
            index + 1
            for index, row in enumerate(sample_rows_by_index)
            if row is None
        ]
        checkpoint_payload = {
            "schema_version": 1,
            "updated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
            "run_timestamp": run_timestamp,
            "status": str(status),
            "task_count_total": total_tasks,
            "task_count_completed": len(completed_indices),
            "completed_task_indices": completed_indices,
            "pending_task_indices": pending_indices,
            "sample_result_filename": _SPEED_SAMPLE_RESULT_FILENAME,
            "partial_samples_path": _SPEED_RUN_PARTIAL_SAMPLES_FILENAME,
            "partial_summary_path": _SPEED_RUN_PARTIAL_SUMMARY_FILENAME,
            "partial_report_path": _SPEED_RUN_PARTIAL_REPORT_FILENAME,
            "parallel_tasks_mode": parallel_tasks_mode,
            "parallel_tasks_requested": (
                max_parallel_tasks if max_parallel_tasks is not None else "auto"
            ),
            "parallel_tasks_effective": parallel_tasks_effective,
            "require_process_workers": bool(require_process_workers),
            "process_worker_probe_available": process_worker_probe_available,
            "process_worker_probe_error": process_worker_probe_error,
            "run_config": run_config_payload,
        }
        (run_root / _SPEED_RUN_CHECKPOINT_FILENAME).write_text(
            json.dumps(checkpoint_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _run_task(task: _SpeedTask) -> dict[str, Any]:
        sample_dir = _speed_task_sample_dir(run_root=run_root, task=task)
        sample_dir.mkdir(parents=True, exist_ok=True)
        target = task.target
        target_id = (
            SPEED_SUITE_ALL_MATCHED_TARGET_ID if target is None else str(target.target_id)
        )
        source_file_for_row = None if target is None else target.source_file
        gold_spans_for_row = None if target is None else target.gold_spans_path
        target_source = (
            None
            if target is None
            else resolve_repo_path(target.source_file, repo_root=REPO_ROOT)
        )
        target_gold = (
            None
            if target is None
            else resolve_repo_path(target.gold_spans_path, repo_root=REPO_ROOT)
        )

        sample_started = time.monotonic()
        if task.scenario == SpeedScenario.STAGE_IMPORT:
            if target_source is None:
                raise ValueError("stage_import scenario requires a concrete target.")
            metrics = _run_stage_import_sample(
                source_file=target_source,
                sample_dir=sample_dir,
                run_settings=run_settings,
                require_process_workers=bool(require_process_workers),
            )
        elif task.scenario == SpeedScenario.BENCHMARK_CANONICAL_LEGACY:
            if target_source is None or target_gold is None:
                raise ValueError(
                    "benchmark_canonical_legacy scenario requires a concrete target."
                )
            metrics = _run_benchmark_sample(
                source_file=target_source,
                gold_spans_path=target_gold,
                sample_dir=sample_dir,
                execution_mode="legacy",
                run_settings=run_settings,
            )
        elif task.scenario == SpeedScenario.BENCHMARK_CANONICAL_PIPELINED:
            if target_source is None or target_gold is None:
                raise ValueError(
                    "benchmark_canonical_pipelined scenario requires a concrete target."
                )
            metrics = _run_benchmark_sample(
                source_file=target_source,
                gold_spans_path=target_gold,
                sample_dir=sample_dir,
                execution_mode="pipelined",
                run_settings=run_settings,
            )
        elif task.scenario == SpeedScenario.BENCHMARK_ALL_METHOD_MULTI_SOURCE:
            metrics = _run_all_method_multi_source_sample(
                targets=selected_targets,
                sample_dir=sample_dir,
                run_settings=run_settings,
                include_codex_farm_requested=include_codex_farm_requested,
                require_process_workers=bool(require_process_workers),
            )
        else:
            raise ValueError(f"Unsupported speed scenario: {task.scenario}")

        wall_seconds = max(0.0, time.monotonic() - sample_started)
        timing_payload = metrics.pop("timing", {})
        row = {
            "target_id": target_id,
            "source_file": source_file_for_row,
            "gold_spans_path": gold_spans_for_row,
            "scenario": task.scenario.value,
            "phase": task.phase,
            "phase_index": task.phase_index,
            "wall_seconds": float(wall_seconds),
            "timing": timing_payload,
            "metrics": metrics,
            "sample_dir": _relative_to_run_root(sample_dir, run_root),
            "task_index": task.index,
        }
        snapshot_path = sample_dir / _SPEED_SAMPLE_RESULT_FILENAME
        snapshot_path.write_text(
            json.dumps(row, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return row

    _write_checkpoint("in_progress")
    completed_count = resumed_completed_count
    pending_tasks = [task for task in tasks if sample_rows_by_index[task.index - 1] is None]
    failure_exc: BaseException | None = None
    try:
        if parallel_tasks_effective <= 1:
            for task in tasks:
                task_prefix = format_task_counter(
                    "Speed suite",
                    task.index,
                    task.total,
                    noun="task",
                )
                if sample_rows_by_index[task.index - 1] is not None:
                    _notify(
                        f"{task_prefix} [{_speed_task_target_id(task)}] {task.scenario.value} "
                        f"{task.phase} {task.phase_index} (resumed)"
                    )
                    continue
                _notify(
                    f"{task_prefix} [{_speed_task_target_id(task)}] {task.scenario.value} "
                    f"{task.phase} {task.phase_index}..."
                )
                row = _run_task(task)
                sample_rows_by_index[task.index - 1] = row
                completed_count += 1
                _write_checkpoint("in_progress")
                _notify(
                    f"{format_task_counter('Speed suite complete', completed_count, total_tasks, noun='task')} "
                    f"[{_speed_task_target_id(task)}] {task.scenario.value} {task.phase} {task.phase_index}"
                )
        else:
            executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
                max_workers=parallel_tasks_effective,
                thread_name_prefix="speed-task",
            )
            future_to_task: dict[Future[dict[str, Any]], _SpeedTask] = {}
            next_pending = 0
            try:
                while next_pending < len(pending_tasks) or future_to_task:
                    while (
                        next_pending < len(pending_tasks)
                        and len(future_to_task) < parallel_tasks_effective
                    ):
                        task = pending_tasks[next_pending]
                        next_pending += 1
                        _notify(
                            f"{format_task_counter('Speed suite', task.index, task.total, noun='task')} "
                            f"[{_speed_task_target_id(task)}] {task.scenario.value} {task.phase} {task.phase_index}..."
                        )
                        future = executor.submit(_run_task, task)
                        future_to_task[future] = task

                    if not future_to_task:
                        continue

                    done, _pending = wait(
                        set(future_to_task),
                        timeout=0.5,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    for future in done:
                        task = future_to_task.pop(future)
                        row = future.result()
                        sample_rows_by_index[task.index - 1] = row
                        completed_count += 1
                        _write_checkpoint("in_progress")
                        _notify(
                            f"{format_task_counter('Speed suite complete', completed_count, total_tasks, noun='task')} "
                            f"[{_speed_task_target_id(task)}] {task.scenario.value} {task.phase} {task.phase_index}"
                        )
            except BaseException:
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
                    executor = None
                raise
            finally:
                if executor is not None:
                    executor.shutdown(wait=True, cancel_futures=False)
    except BaseException as exc:  # noqa: BLE001
        failure_exc = exc
        _write_checkpoint("in_progress")
    if failure_exc is not None:
        raise failure_exc

    sample_rows = _ordered_sample_rows()
    _write_samples_jsonl(run_root / "samples.jsonl", sample_rows)
    summary_payload = _build_summary_payload(
        suite=suite,
        selected_targets=selected_targets,
        scenarios=scenarios,
        warmups=warmups,
        repeats=repeats,
        run_timestamp=run_timestamp,
        run_settings=run_settings,
        include_codex_farm_requested=include_codex_farm_requested,
        codex_farm_confirmed=codex_farm_confirmed,
        sample_rows=sample_rows,
        parallel_tasks_requested=max_parallel_tasks,
        parallel_tasks_effective=parallel_tasks_effective,
        parallel_tasks_mode=parallel_tasks_mode,
        parallel_tasks_cpu_count=cpu_count,
        require_process_workers=bool(require_process_workers),
        process_worker_probe_available=process_worker_probe_available,
        process_worker_probe_error=process_worker_probe_error,
        resume_requested=bool(resume_run_dir is not None),
    )
    (run_root / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_root / "report.md").write_text(
        _format_speed_run_report(summary_payload),
        encoding="utf-8",
    )
    _write_checkpoint("complete")

    manifest = RunManifest(
        run_kind="bench_speed_suite",
        run_id=run_timestamp,
        created_at=run_started.isoformat(timespec="seconds"),
        source=RunSource(path=suite.name),
        run_config={
            "warmups": int(warmups),
            "repeats": int(repeats),
            "max_targets": max_targets,
            "scenarios": [scenario.value for scenario in scenarios],
            "max_parallel_tasks_requested": (
                max_parallel_tasks if max_parallel_tasks is not None else "auto"
            ),
            "max_parallel_tasks_mode": parallel_tasks_mode,
            "max_parallel_tasks_effective": parallel_tasks_effective,
            "require_process_workers": bool(require_process_workers),
            "process_worker_probe_available": process_worker_probe_available,
            "process_worker_probe_error": process_worker_probe_error,
            "resume_requested": bool(resume_run_dir is not None),
            "resume_run_dir": str(run_root) if resume_run_dir is not None else None,
            "sequence_matcher": run_settings.benchmark_sequence_matcher,
            "run_settings": run_settings.to_run_config_dict(),
            "run_settings_summary": run_settings.summary(),
            "run_settings_hash": run_settings.stable_hash(),
            "include_codex_farm_requested": bool(include_codex_farm_requested),
            "include_codex_farm_confirmed": bool(codex_farm_confirmed),
        },
        artifacts={
            "suite_resolved_json": "suite_resolved.json",
            "checkpoint_json": _SPEED_RUN_CHECKPOINT_FILENAME,
            "samples_jsonl": "samples.jsonl",
            "samples_partial_jsonl": _SPEED_RUN_PARTIAL_SAMPLES_FILENAME,
            "summary_json": "summary.json",
            "summary_partial_json": _SPEED_RUN_PARTIAL_SUMMARY_FILENAME,
            "report_md": "report.md",
            "report_partial_md": _SPEED_RUN_PARTIAL_REPORT_FILENAME,
        },
        notes="Deterministic speed regression suite run.",
    )
    write_run_manifest(run_root, manifest)
    return run_root


def load_speed_run_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists() or not summary_path.is_file():
        raise FileNotFoundError(f"Missing speed run summary: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid speed run summary payload: {summary_path}")
    return payload


def parse_speed_scenarios(raw_value: str) -> list[SpeedScenario]:
    tokens = [token.strip() for token in raw_value.split(",")]
    selected: list[SpeedScenario] = []
    seen: set[SpeedScenario] = set()
    for token in tokens:
        if not token:
            continue
        try:
            scenario = SpeedScenario(token)
        except ValueError as exc:
            allowed = ", ".join(s.value for s in SpeedScenario)
            raise ValueError(
                f"Invalid speed scenario: {token!r}. Allowed values: {allowed}"
            ) from exc
        if scenario in seen:
            continue
        seen.add(scenario)
        selected.append(scenario)
    if not selected:
        raise ValueError("No speed scenarios selected.")
    return selected


def _scenario_runs_once_per_suite(scenario: SpeedScenario) -> bool:
    return scenario == SpeedScenario.BENCHMARK_ALL_METHOD_MULTI_SOURCE


def _iter_sample_phases(*, warmups: int, repeats: int) -> Iterable[tuple[str, int]]:
    for index in range(1, warmups + 1):
        yield ("warmup", index)
    for index in range(1, repeats + 1):
        yield ("repeat", index)


def _coerce_int(value: Any, *, minimum: int = 0) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = minimum
    return max(minimum, numeric)


def _probe_process_worker_availability() -> tuple[bool | None, str | None]:
    try:
        import cookimport.cli as cli
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip()
        if detail:
            return None, f"{type(exc).__name__}: {detail}"
        return None, type(exc).__name__
    try:
        available, error = cli._probe_all_method_process_pool_executor()
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip()
        if detail:
            return None, f"{type(exc).__name__}: {detail}"
        return None, type(exc).__name__
    return bool(available), str(error).strip() if error else None


def _resolve_speed_parallel_tasks_cap(
    *,
    requested: int | None,
    total_tasks: int,
) -> tuple[int, str, int]:
    cpu_count = _coerce_int(os.cpu_count(), minimum=1)
    if requested is None:
        auto_cap = max(1, min(total_tasks, cpu_count, _SPEED_AUTO_MAX_PARALLEL_TASKS))
        return auto_cap, "auto", cpu_count
    fixed_cap = max(1, min(int(requested), total_tasks))
    return fixed_cap, "fixed", cpu_count


def _build_speed_tasks(
    *,
    selected_targets: list[SpeedTarget],
    scenarios: list[SpeedScenario],
    warmups: int,
    repeats: int,
) -> list[_SpeedTask]:
    scenario_work_items: list[tuple[SpeedScenario, SpeedTarget | None]] = []
    for scenario in scenarios:
        if _scenario_runs_once_per_suite(scenario):
            scenario_work_items.append((scenario, None))
            continue
        for target in selected_targets:
            scenario_work_items.append((scenario, target))

    total = len(scenario_work_items) * (warmups + repeats)
    tasks: list[_SpeedTask] = []
    current = 0
    for scenario, scenario_target in scenario_work_items:
        for phase, phase_index in _iter_sample_phases(warmups=warmups, repeats=repeats):
            current += 1
            tasks.append(
                _SpeedTask(
                    index=current,
                    total=total,
                    scenario=scenario,
                    target=scenario_target,
                    phase=phase,
                    phase_index=phase_index,
                )
            )
    return tasks


def _speed_task_target_id(task: _SpeedTask) -> str:
    if task.target is None:
        return SPEED_SUITE_ALL_MATCHED_TARGET_ID
    return str(task.target.target_id)


def _speed_task_sample_dir(*, run_root: Path, task: _SpeedTask) -> Path:
    return (
        run_root
        / "scenario_runs"
        / (
            _SPEED_SUITE_ALL_MATCHED_TARGET_DIR
            if task.target is None
            else str(task.target.target_id)
        )
        / task.scenario.value
        / f"{task.phase}_{task.phase_index:02d}"
    )


def _load_speed_task_snapshot(*, run_root: Path, task: _SpeedTask) -> dict[str, Any] | None:
    snapshot_path = _speed_task_sample_dir(run_root=run_root, task=task) / _SPEED_SAMPLE_RESULT_FILENAME
    if not snapshot_path.exists() or not snapshot_path.is_file():
        return None
    try:
        payload = _load_json_dict(snapshot_path)
    except Exception:  # noqa: BLE001
        return None
    payload_target_id = str(payload.get("target_id") or "").strip()
    if payload_target_id != _speed_task_target_id(task):
        return None
    payload_scenario = str(payload.get("scenario") or "").strip()
    if payload_scenario != task.scenario.value:
        return None
    payload_phase = str(payload.get("phase") or "").strip()
    if payload_phase != task.phase:
        return None
    payload_phase_index = _coerce_int(payload.get("phase_index"), minimum=0)
    if payload_phase_index != task.phase_index:
        return None
    payload.setdefault("task_index", task.index)
    return payload


def _validate_speed_resume_compatibility(
    *,
    run_root: Path,
    run_config: dict[str, Any],
) -> None:
    checkpoint_path = run_root / _SPEED_RUN_CHECKPOINT_FILENAME
    if not checkpoint_path.exists() or not checkpoint_path.is_file():
        return
    payload = _load_json_dict(checkpoint_path)
    existing_config_raw = payload.get("run_config")
    if not isinstance(existing_config_raw, dict):
        return
    existing_config = {
        "suite_name": str(existing_config_raw.get("suite_name") or ""),
        "suite_generated_at": str(existing_config_raw.get("suite_generated_at") or ""),
        "target_ids": [
            str(item)
            for item in (existing_config_raw.get("target_ids") or [])
            if str(item).strip()
        ],
        "scenarios": [
            str(item)
            for item in (existing_config_raw.get("scenarios") or [])
            if str(item).strip()
        ],
        "warmups": _coerce_int(existing_config_raw.get("warmups"), minimum=0),
        "repeats": _coerce_int(existing_config_raw.get("repeats"), minimum=1),
        "max_targets": existing_config_raw.get("max_targets"),
        "run_settings_hash": str(existing_config_raw.get("run_settings_hash") or ""),
        "include_codex_farm_requested": bool(
            existing_config_raw.get("include_codex_farm_requested")
        ),
        "include_codex_farm_confirmed": bool(
            existing_config_raw.get("include_codex_farm_confirmed")
        ),
    }
    expected_config = {
        "suite_name": str(run_config.get("suite_name") or ""),
        "suite_generated_at": str(run_config.get("suite_generated_at") or ""),
        "target_ids": [str(item) for item in (run_config.get("target_ids") or [])],
        "scenarios": [str(item) for item in (run_config.get("scenarios") or [])],
        "warmups": _coerce_int(run_config.get("warmups"), minimum=0),
        "repeats": _coerce_int(run_config.get("repeats"), minimum=1),
        "max_targets": run_config.get("max_targets"),
        "run_settings_hash": str(run_config.get("run_settings_hash") or ""),
        "include_codex_farm_requested": bool(run_config.get("include_codex_farm_requested")),
        "include_codex_farm_confirmed": bool(run_config.get("include_codex_farm_confirmed")),
    }
    if existing_config != expected_config:
        raise ValueError(
            "Resume run directory settings do not match requested speed suite run. "
            "Use matching arguments or start a new run directory."
        )


def _resolve_speed_resume_run_timestamp(*, run_root: Path) -> str | None:
    checkpoint_path = run_root / _SPEED_RUN_CHECKPOINT_FILENAME
    if checkpoint_path.exists() and checkpoint_path.is_file():
        try:
            checkpoint_payload = _load_json_dict(checkpoint_path)
        except Exception:  # noqa: BLE001
            checkpoint_payload = {}
        run_timestamp = str(checkpoint_payload.get("run_timestamp") or "").strip()
        if run_timestamp:
            return run_timestamp
    partial_summary_path = run_root / _SPEED_RUN_PARTIAL_SUMMARY_FILENAME
    if partial_summary_path.exists() and partial_summary_path.is_file():
        try:
            summary_payload = _load_json_dict(partial_summary_path)
        except Exception:  # noqa: BLE001
            summary_payload = {}
        run_timestamp = str(summary_payload.get("run_timestamp") or "").strip()
        if run_timestamp:
            return run_timestamp
    summary_path = run_root / "summary.json"
    if summary_path.exists() and summary_path.is_file():
        try:
            summary_payload = _load_json_dict(summary_path)
        except Exception:  # noqa: BLE001
            summary_payload = {}
        run_timestamp = str(summary_payload.get("run_timestamp") or "").strip()
        if run_timestamp:
            return run_timestamp
    return None


def _run_stage_import_sample(
    *,
    source_file: Path,
    sample_dir: Path,
    run_settings: RunSettings,
    require_process_workers: bool,
) -> dict[str, Any]:
    import cookimport.cli as cli

    stage_output_root = sample_dir / "stage_output"
    stage_output_root.mkdir(parents=True, exist_ok=True)
    stage_kwargs = build_stage_call_kwargs_from_run_settings(
        run_settings,
        out=stage_output_root,
        mapping=None,
        overrides=None,
        limit=None,
        write_markdown=False,
    )
    with _suppress_cli_output():
        stage_run_root = cli.stage(
            path=source_file,
            require_process_workers=bool(require_process_workers),
            **stage_kwargs,
        )
    report_path = _select_stage_report_path(stage_run_root)
    report_payload = _load_json_dict(report_path) if report_path is not None else {}
    timing_payload = _extract_timing_payload(report_payload)
    return {
        "total_seconds": _coerce_float(timing_payload.get("total_seconds")),
        "parsing_seconds": _coerce_float(timing_payload.get("parsing_seconds")),
        "writing_seconds": _coerce_float(timing_payload.get("writing_seconds")),
        "ocr_seconds": _coerce_float(timing_payload.get("ocr_seconds")),
        "stage_run_root": _path_for_payload(stage_run_root),
        "report_path": _path_for_payload(report_path),
        "timing": timing_payload,
    }


def _run_benchmark_sample(
    *,
    source_file: Path,
    gold_spans_path: Path,
    sample_dir: Path,
    execution_mode: str,
    run_settings: RunSettings,
) -> dict[str, Any]:
    import cookimport.cli as cli

    prediction_output_dir = sample_dir / "prediction_output"
    processed_output_dir = sample_dir / "processed_output"
    eval_output_dir = sample_dir / "eval_output"
    prediction_output_dir.mkdir(parents=True, exist_ok=True)
    processed_output_dir.mkdir(parents=True, exist_ok=True)
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    benchmark_kwargs = build_benchmark_call_kwargs_from_run_settings(
        run_settings,
        output_dir=prediction_output_dir,
        processed_output_dir=processed_output_dir,
        eval_output_dir=eval_output_dir,
        eval_mode="canonical-text",
        execution_mode=execution_mode,
        no_upload=True,
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    with _suppress_cli_output():
        with cli._benchmark_progress_overrides(
            progress_callback=None,
            suppress_summary=True,
            suppress_spinner=True,
            suppress_output_prune=True,
        ):
            cli.labelstudio_benchmark(
                gold_spans=gold_spans_path,
                source_file=source_file,
                **benchmark_kwargs,
            )

    eval_report_path = eval_output_dir / "eval_report.json"
    if not eval_report_path.exists() or not eval_report_path.is_file():
        raise FileNotFoundError(f"Missing eval report: {eval_report_path}")
    report_payload = _load_json_dict(eval_report_path)
    timing_payload = _extract_timing_payload(report_payload)
    return {
        "total_seconds": _coerce_float(timing_payload.get("total_seconds")),
        "prediction_seconds": _coerce_float(timing_payload.get("prediction_seconds")),
        "evaluation_seconds": _coerce_float(timing_payload.get("evaluation_seconds")),
        "parsing_seconds": _coerce_float(timing_payload.get("parsing_seconds")),
        "writing_seconds": _coerce_float(timing_payload.get("writing_seconds")),
        "eval_output_dir": _path_for_payload(eval_output_dir),
        "eval_report_path": _path_for_payload(eval_report_path),
        "timing": timing_payload,
    }


def _run_all_method_multi_source_sample(
    *,
    targets: list[SpeedTarget],
    sample_dir: Path,
    run_settings: RunSettings,
    include_codex_farm_requested: bool,
    require_process_workers: bool,
) -> dict[str, Any]:
    import cookimport.cli as cli

    if not targets:
        raise ValueError("All-method speed scenario requires at least one target.")

    resolved_targets: list[cli.AllMethodTarget] = []
    for target in targets:
        source_file = resolve_repo_path(target.source_file, repo_root=REPO_ROOT)
        gold_spans_path = resolve_repo_path(target.gold_spans_path, repo_root=REPO_ROOT)
        resolved_targets.append(
            cli.AllMethodTarget(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display=target.target_id,
            )
        )

    include_codex_effective, _codex_warning = cli._resolve_all_method_codex_choice(
        include_codex_farm_requested
    )
    target_variants = cli._build_all_method_target_variants(
        targets=resolved_targets,
        base_settings=run_settings,
        include_codex_farm=include_codex_effective,
        include_markdown_extractors=False,
    )

    eval_output_dir = sample_dir / "eval_output"
    processed_output_dir = sample_dir / "processed_output"
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    processed_output_dir.mkdir(parents=True, exist_ok=True)
    all_method_root = eval_output_dir / "all-method-benchmark"
    all_method_processed_root = processed_output_dir / "all-method-benchmark"

    with _suppress_cli_output():
        with cli._benchmark_progress_overrides(
            progress_callback=None,
            suppress_summary=True,
            suppress_spinner=True,
            suppress_output_prune=True,
        ):
            report_md_path = cli._run_all_method_benchmark_multi_source(
                target_variants=target_variants,
                unmatched_targets=[],
                include_codex_farm_requested=include_codex_farm_requested,
                include_codex_farm_effective=include_codex_effective,
                root_output_dir=all_method_root,
                processed_output_root=all_method_processed_root,
                overlap_threshold=0.5,
                force_source_match=False,
                scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_GLOBAL,
                require_process_workers=bool(require_process_workers),
            )

    report_json_path = report_md_path.with_suffix(".json")
    if not report_json_path.exists() or not report_json_path.is_file():
        raise FileNotFoundError(f"Missing all-method report: {report_json_path}")

    report_payload = _load_json_dict(report_json_path)
    executor_resolution_raw = report_payload.get("executor_resolution")
    executor_resolution = (
        dict(executor_resolution_raw) if isinstance(executor_resolution_raw, dict) else {}
    )
    timing_payload_raw = report_payload.get("timing_summary")
    timing_payload = (
        dict(timing_payload_raw) if isinstance(timing_payload_raw, dict) else {}
    )
    total_seconds = _coerce_float(timing_payload.get("run_wall_seconds"))
    if total_seconds is None:
        total_seconds = _coerce_float(timing_payload.get("source_total_seconds"))

    return {
        "total_seconds": total_seconds,
        "source_total_seconds": _coerce_float(timing_payload.get("source_total_seconds")),
        "config_total_seconds": _coerce_float(timing_payload.get("config_total_seconds")),
        "source_schedule_strategy": str(
            report_payload.get("source_schedule_strategy") or ""
        ),
        "source_job_count_planned": _coerce_float(
            report_payload.get("source_job_count_planned")
        ),
        "source_parallelism_effective": _coerce_float(
            report_payload.get("source_parallelism_effective")
        ),
        "matched_target_count": _coerce_float(report_payload.get("matched_target_count")),
        "successful_source_count": _coerce_float(
            report_payload.get("successful_source_count")
        ),
        "executor_resolution": executor_resolution,
        "eval_output_dir": _path_for_payload(all_method_root),
        "report_json_path": _path_for_payload(report_json_path),
        "timing": timing_payload,
    }


def _select_stage_report_path(stage_run_root: Path) -> Path | None:
    report_paths = sorted(stage_run_root.glob("*.excel_import_report.json"))
    if not report_paths:
        return None
    return report_paths[0]


def _build_summary_payload(
    *,
    suite: SpeedSuite,
    selected_targets: list[SpeedTarget],
    scenarios: list[SpeedScenario],
    warmups: int,
    repeats: int,
    run_timestamp: str,
    run_settings: RunSettings,
    include_codex_farm_requested: bool,
    codex_farm_confirmed: bool,
    sample_rows: list[dict[str, Any]],
    parallel_tasks_requested: int | None = None,
    parallel_tasks_effective: int = 1,
    parallel_tasks_mode: str = "fixed",
    parallel_tasks_cpu_count: int | None = None,
    require_process_workers: bool = False,
    process_worker_probe_available: bool | None = None,
    process_worker_probe_error: str | None = None,
    resume_requested: bool = False,
) -> dict[str, Any]:
    repeat_rows = [row for row in sample_rows if row.get("phase") == "repeat"]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in repeat_rows:
        key = (str(row.get("target_id") or ""), str(row.get("scenario") or ""))
        grouped.setdefault(key, []).append(row)

    summary_rows: list[dict[str, Any]] = []
    for (target_id, scenario), rows in sorted(grouped.items()):
        first = rows[0]
        row_payload = {
            "target_id": target_id,
            "scenario": scenario,
            "source_file": first.get("source_file"),
            "gold_spans_path": first.get("gold_spans_path"),
            "repeat_count": len(rows),
            "warmup_count": warmups,
            "median_wall_seconds": _median_float(
                _collect_metric(rows, container="root", key="wall_seconds")
            ),
            "median_total_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="total_seconds")
            ),
            "median_prediction_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="prediction_seconds")
            ),
            "median_evaluation_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="evaluation_seconds")
            ),
            "median_parsing_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="parsing_seconds")
            ),
            "median_writing_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="writing_seconds")
            ),
            "median_ocr_seconds": _median_float(
                _collect_metric(rows, container="metrics", key="ocr_seconds")
            ),
        }
        summary_rows.append(row_payload)

    scenario_rollups: list[dict[str, Any]] = []
    for scenario in scenarios:
        rows_for_scenario = [
            row for row in summary_rows if row.get("scenario") == scenario.value
        ]
        medians = [
            _coerce_float(row.get("median_total_seconds"))
            for row in rows_for_scenario
            if _coerce_float(row.get("median_total_seconds")) is not None
        ]
        scenario_rollups.append(
            {
                "scenario": scenario.value,
                "target_count": len(rows_for_scenario),
                "median_total_seconds_across_targets": _median_float(medians),
            }
        )

    run_settings_payload = run_settings.to_run_config_dict()
    return {
        "schema_version": 1,
        "run_timestamp": run_timestamp,
        "suite_name": suite.name,
        "suite_generated_at": suite.generated_at,
        "target_count_selected": len(selected_targets),
        "target_count_total": len(suite.targets),
        "scenario_count": len(scenarios),
        "scenarios": [scenario.value for scenario in scenarios],
        "warmups": int(warmups),
        "repeats": int(repeats),
        "sequence_matcher": run_settings.benchmark_sequence_matcher,
        "run_settings": run_settings_payload,
        "run_settings_summary": run_settings.summary(),
        "run_settings_hash": run_settings.stable_hash(),
        "include_codex_farm_requested": bool(include_codex_farm_requested),
        "include_codex_farm_confirmed": bool(codex_farm_confirmed),
        "max_parallel_tasks_requested": (
            parallel_tasks_requested if parallel_tasks_requested is not None else "auto"
        ),
        "max_parallel_tasks_effective": int(max(1, parallel_tasks_effective)),
        "max_parallel_tasks_mode": str(parallel_tasks_mode or "fixed"),
        "max_parallel_tasks_cpu_count": (
            int(parallel_tasks_cpu_count)
            if parallel_tasks_cpu_count is not None
            else _coerce_int(os.cpu_count(), minimum=1)
        ),
        "require_process_workers": bool(require_process_workers),
        "process_worker_probe_available": process_worker_probe_available,
        "process_worker_probe_error": (
            str(process_worker_probe_error).strip()
            if process_worker_probe_error
            else None
        ),
        "resume_requested": bool(resume_requested),
        "sample_count": len(sample_rows),
        "summary_rows": summary_rows,
        "scenario_rollups": scenario_rollups,
    }


def _format_speed_run_report(summary_payload: dict[str, Any]) -> str:
    lines = [
        "# Speed Suite Report",
        "",
        f"- Run timestamp: {summary_payload.get('run_timestamp')}",
        f"- Suite: {summary_payload.get('suite_name')}",
        f"- Scenarios: {', '.join(summary_payload.get('scenarios') or [])}",
        f"- Targets: {summary_payload.get('target_count_selected')}",
        f"- Warmups: {summary_payload.get('warmups')}",
        f"- Repeats: {summary_payload.get('repeats')}",
        "- Parallel tasks: "
        f"{summary_payload.get('max_parallel_tasks_effective')} "
        f"(mode={summary_payload.get('max_parallel_tasks_mode')}, "
        f"requested={summary_payload.get('max_parallel_tasks_requested')})",
        (
            "- Process workers required: "
            f"{summary_payload.get('require_process_workers')} "
            f"(probe_available={summary_payload.get('process_worker_probe_available')}, "
            f"probe_error={summary_payload.get('process_worker_probe_error')})"
        ),
        f"- Resume requested: {summary_payload.get('resume_requested')}",
        f"- Sequence matcher: {summary_payload.get('sequence_matcher')}",
        f"- Run settings hash: {summary_payload.get('run_settings_hash')}",
        "",
        "## Scenario Rollups",
        "",
    ]
    for rollup in summary_payload.get("scenario_rollups", []):
        scenario = str(rollup.get("scenario") or "")
        median_total = _coerce_float(rollup.get("median_total_seconds_across_targets"))
        rendered = (
            f"{median_total:.3f}s"
            if median_total is not None
            else "n/a"
        )
        lines.append(
            f"- `{scenario}` median total across targets: {rendered} "
            f"(targets={int(rollup.get('target_count') or 0)})"
        )

    lines.extend(["", "## Per Target", ""])
    for row in summary_payload.get("summary_rows", []):
        lines.append(
            "- "
            f"{row.get('target_id')} | {row.get('scenario')} | "
            f"median_total={_render_seconds(row.get('median_total_seconds'))} | "
            f"median_wall={_render_seconds(row.get('median_wall_seconds'))}"
        )
    lines.append("")
    return "\n".join(lines)


def _write_samples_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [json.dumps(row, sort_keys=True) for row in rows]
    payload = "\n".join(lines).rstrip()
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def _collect_metric(
    rows: list[dict[str, Any]],
    *,
    container: str,
    key: str,
) -> list[float]:
    values: list[float] = []
    for row in rows:
        if container == "root":
            value = row.get(key)
        else:
            value = (row.get(container) or {}).get(key)
        numeric = _coerce_float(value)
        if numeric is not None:
            values.append(numeric)
    return values


def _extract_timing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    timing = payload.get("timing")
    if isinstance(timing, dict):
        return dict(timing)
    return {}


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return 0.0
    return numeric


def _median_float(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _render_seconds(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.3f}s"


def _relative_to_run_root(path: Path, run_root: Path) -> str:
    try:
        return str(path.relative_to(run_root))
    except ValueError:
        return str(path)


def _path_for_payload(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


@contextlib.contextmanager
def _suppress_cli_output() -> Iterable[None]:
    with contextlib.redirect_stdout(io.StringIO()):
        with contextlib.redirect_stderr(io.StringIO()):
            yield
