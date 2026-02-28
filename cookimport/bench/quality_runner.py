"""Quality-suite execution for deterministic all-method quality experiments."""

from __future__ import annotations

import datetime as dt
import json
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
_SUPPORTED_EXPERIMENT_SCHEMA_VERSION = 1


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


class _ExperimentFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = _SUPPORTED_EXPERIMENT_SCHEMA_VERSION
    base_run_settings_file: str | None = None
    experiments: list[QualityExperiment]

    @model_validator(mode="after")
    def _validate_payload(self) -> "_ExperimentFile":
        if int(self.schema_version) != _SUPPORTED_EXPERIMENT_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported schema_version. "
                f"Expected {_SUPPORTED_EXPERIMENT_SCHEMA_VERSION}."
            )
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


@dataclass(frozen=True)
class _ResolvedExperiment:
    id: str
    run_settings_patch: dict[str, Any]
    run_settings_payload: dict[str, Any]
    run_settings: RunSettings


def run_quality_suite(
    suite: QualitySuite,
    out_dir: Path,
    *,
    experiments_file: Path,
    base_run_settings_file: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    selected_targets = _resolve_selected_targets(suite)
    if not selected_targets:
        raise ValueError("Quality suite selected_target_ids resolved to zero targets.")

    experiment_payload = _load_experiment_file(experiments_file)
    base_settings_payload = _resolve_base_run_settings_payload(
        experiments_file=experiments_file,
        experiment_payload=experiment_payload,
        base_run_settings_file=base_run_settings_file,
    )
    resolved_experiments = _resolve_experiments(
        experiments=experiment_payload.experiments,
        base_payload=base_settings_payload,
    )

    run_started = dt.datetime.now()
    run_timestamp = run_started.strftime("%Y-%m-%d_%H.%M.%S")
    run_root = out_dir / run_timestamp
    run_root.mkdir(parents=True, exist_ok=True)

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
        "generated_at": run_timestamp,
        "source_file": str(experiments_file),
        "base_run_settings_file": str(base_run_settings_file)
        if base_run_settings_file is not None
        else experiment_payload.base_run_settings_file,
        "experiments": [
            {
                "id": item.id,
                "run_settings_patch": item.run_settings_patch,
                "run_settings": item.run_settings.to_run_config_dict(),
                "run_settings_summary": item.run_settings.summary(),
                "run_settings_hash": item.run_settings.stable_hash(),
            }
            for item in resolved_experiments
        ],
    }
    (run_root / "experiments_resolved.json").write_text(
        json.dumps(resolved_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    import cookimport.cli as cli

    include_codex_effective, _codex_warning = cli._resolve_all_method_codex_choice(False)
    include_markdown_extractors = cli._resolve_all_method_markdown_extractors_choice()

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
                include_markdown_extractors=include_markdown_extractors,
                include_codex_effective=include_codex_effective,
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


def _load_experiment_file(path: Path) -> _ExperimentFile:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to read experiments file: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Experiments file must contain a JSON object.")
    return _ExperimentFile.model_validate(payload)


def _resolve_base_run_settings_payload(
    *,
    experiments_file: Path,
    experiment_payload: _ExperimentFile,
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


def _resolve_experiments(
    *,
    experiments: list[QualityExperiment],
    base_payload: dict[str, Any],
) -> list[_ResolvedExperiment]:
    resolved: list[_ResolvedExperiment] = []
    for experiment in experiments:
        merged_payload = dict(base_payload)
        merged_payload.update(dict(experiment.run_settings_patch))
        run_settings = RunSettings.from_dict(
            merged_payload,
            warn_context=f"quality-run experiment {experiment.id}",
        )
        resolved.append(
            _ResolvedExperiment(
                id=experiment.id,
                run_settings_patch=dict(experiment.run_settings_patch),
                run_settings_payload=merged_payload,
                run_settings=run_settings,
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


def _run_single_experiment(
    *,
    experiment_id: str,
    suite_targets: list[Any],
    run_root: Path,
    experiment_root: Path,
    run_settings: RunSettings,
    include_markdown_extractors: bool,
    include_codex_effective: bool,
) -> QualityExperimentResult:
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
                gold_display=target.target_id,
            )
        )

    target_variants = cli._build_all_method_target_variants(
        targets=all_method_targets,
        base_settings=run_settings,
        include_codex_farm=False,
        include_markdown_extractors=include_markdown_extractors,
    )

    processed_output_root = experiment_root / "processed_output"
    processed_output_root.mkdir(parents=True, exist_ok=True)
    report_md_path = cli._run_all_method_benchmark_multi_source(
        target_variants=target_variants,
        unmatched_targets=[],
        include_codex_farm_requested=False,
        include_codex_farm_effective=include_codex_effective,
        root_output_dir=experiment_root,
        processed_output_root=processed_output_root,
        overlap_threshold=0.5,
        force_source_match=False,
        scheduler_scope=cli.ALL_METHOD_SCHEDULER_SCOPE_GLOBAL,
    )
    report_json_path = report_md_path.with_suffix(".json")
    report_payload = _load_json_dict(report_json_path)
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
