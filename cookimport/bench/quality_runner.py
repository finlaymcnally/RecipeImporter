"""Quality-suite execution for deterministic all-method quality experiments."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cookimport.bench.quality_suite import QualitySuite
from cookimport.bench.speed_suite import resolve_repo_path
from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import format_task_counter
from cookimport.paths import REPO_ROOT

_EXPERIMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SUPPORTED_EXPERIMENT_SCHEMA_VERSION = 2
_SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS = {1, 2}
_SUPPORTED_SEARCH_STRATEGIES = {"exhaustive", "race"}
_ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV = "COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT"
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
    run_settings_payload: dict[str, Any]
    run_settings: RunSettings
    all_method_runtime_patch: dict[str, Any]
    all_method_runtime: dict[str, Any]


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
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | None = None,
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

    run_started = dt.datetime.now()
    run_timestamp = run_started.strftime("%Y-%m-%d_%H.%M.%S")
    run_root = out_dir / run_timestamp
    run_root.mkdir(parents=True, exist_ok=True)
    canonical_alignment_cache_root = _resolve_quality_alignment_cache_root(
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
        "experiments": [
            {
                "id": item.id,
                "run_settings_patch": item.run_settings_patch,
                "run_settings": item.run_settings.to_run_config_dict(),
                "run_settings_summary": item.run_settings.summary(),
                "run_settings_hash": item.run_settings.stable_hash(),
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
    include_markdown_extractors = cli._resolve_all_method_markdown_extractors_choice()
    resolved_payload["include_codex_farm_effective"] = bool(include_codex_effective)
    resolved_payload["include_markdown_extractors_effective"] = bool(
        include_markdown_extractors
    )
    if _codex_warning is not None:
        resolved_payload["include_codex_farm_warning"] = str(_codex_warning)
    (run_root / "experiments_resolved.json").write_text(
        json.dumps(resolved_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    total_experiments = len(resolved_experiments)
    results: list[QualityExperimentResult] = []

    for index, experiment in enumerate(resolved_experiments, start=1):
        _notify_progress(
            progress_callback,
            (
                f"{format_task_counter('Quality suite', index, total_experiments, noun='task')}: "
                f"{experiment.id}"
            ),
        )
        experiment_root = run_root / "experiments" / experiment.id
        experiment_root.mkdir(parents=True, exist_ok=True)
        try:
            result = _run_single_experiment(
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
                search_strategy=search_strategy_clean,
                race_probe_targets=race_probe_targets,
                race_mid_targets=race_mid_targets,
                race_keep_ratio=race_keep_ratio,
                race_finalists=race_finalists,
                include_deterministic_sweeps=include_deterministic_sweeps_requested,
                progress_callback=progress_callback,
            )
        except Exception as exc:  # noqa: BLE001
            result = QualityExperimentResult(
                id=experiment.id,
                status="failed",
                error=str(exc),
                run_settings_hash=experiment.run_settings.stable_hash(),
                run_settings_summary=experiment.run_settings.summary(),
            )
        results.append(result)

    summary_payload = _build_summary_payload(
        suite=suite,
        run_timestamp=run_timestamp,
        experiments=resolved_experiments,
        results=results,
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
    resolved: list[_ResolvedExperiment] = []
    for experiment in experiments:
        merged_payload = dict(base_payload)
        merged_payload.update(dict(experiment.run_settings_patch))
        run_settings = RunSettings.from_dict(
            merged_payload,
            warn_context=f"quality-run experiment {experiment.id}",
        )
        runtime_payload = dict(all_method_runtime_base)
        runtime_payload.update(dict(experiment.all_method_runtime_patch))
        resolved.append(
            _ResolvedExperiment(
                id=experiment.id,
                run_settings_patch=dict(experiment.run_settings_patch),
                run_settings_payload=merged_payload,
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


def _target_difficulty_score(target: Any) -> float:
    canonical_chars = float(_coerce_int(getattr(target, "canonical_text_chars", 0)))
    label_count = float(_coerce_int(getattr(target, "label_count", 0)))
    gold_rows = float(_coerce_int(getattr(target, "gold_span_rows", 0)))
    return (label_count * 8.0) + (gold_rows * 3.0) + (canonical_chars / 8000.0)


def _target_source_extension(target: Any) -> str:
    source_path = Path(str(getattr(target, "source_file", "")))
    return source_path.suffix.lower()


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
    search_strategy: str,
    race_probe_targets: int,
    race_mid_targets: int,
    race_keep_ratio: float,
    race_finalists: int,
    include_deterministic_sweeps: bool,
    progress_callback: ProgressCallback | None,
) -> QualityExperimentResult:
    race_metadata: dict[str, Any] | None = None
    if search_strategy == "race" and len(suite_targets) > 1:
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
            progress_callback=progress_callback,
        )
        race_metadata = {
            "strategy": "race",
            "probe_targets": race_probe_targets,
            "mid_targets": race_mid_targets,
            "keep_ratio": race_keep_ratio,
            "finalists": race_finalists,
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
            progress_callback=progress_callback,
        )
    report_json_path = report_md_path.with_suffix(".json")
    report_payload = _load_json_dict(report_json_path)
    if race_metadata is not None:
        (experiment_root / "search_strategy.json").write_text(
            json.dumps(race_metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    aggregate_payload = _summarize_experiment_report(
        experiment_root=experiment_root,
        report_payload=report_payload,
    )

    status = aggregate_payload["status"]
    error = aggregate_payload.get("error")
    return QualityExperimentResult(
        id=experiment_id,
        status=status,
        error=error,
        run_settings_hash=run_settings.stable_hash(),
        run_settings_summary=run_settings.summary(),
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
    run_settings_by_id = {
        experiment.id: {
            "run_settings": experiment.run_settings.to_run_config_dict(),
            "run_settings_summary": experiment.run_settings.summary(),
            "run_settings_hash": experiment.run_settings.stable_hash(),
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
        "target_count_selected": len(suite.selected_target_ids),
        "experiment_count": len(results),
        "successful_experiments": sum(1 for row in results if row.status == "ok"),
        "incomplete_experiments": sum(1 for row in results if row.status == "incomplete"),
        "failed_experiments": sum(1 for row in results if row.status == "failed"),
        "experiments": result_rows,
        "run_settings_by_experiment": run_settings_by_id,
    }


def _format_quality_run_report(summary_payload: dict[str, Any]) -> str:
    lines = [
        "# Quality Suite Report",
        "",
        f"- Run timestamp: {summary_payload.get('run_timestamp')}",
        f"- Suite: {summary_payload.get('suite_name')}",
        f"- Targets selected: {summary_payload.get('target_count_selected')}",
        f"- Experiments: {summary_payload.get('experiment_count')}",
        f"- Successful: {summary_payload.get('successful_experiments')}",
        f"- Incomplete: {summary_payload.get('incomplete_experiments')}",
        f"- Failed: {summary_payload.get('failed_experiments')}",
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
        error_text = str(row.get("error") or "").strip()
        if error_text:
            lines.append(f"  error: {error_text}")
    lines.append("")
    return "\n".join(lines)


def _validate_patch_keys(*, experiment_id: str, patch: dict[str, Any]) -> None:
    known_fields = set(RunSettings.model_fields)
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
