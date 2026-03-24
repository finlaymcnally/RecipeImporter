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

def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload
