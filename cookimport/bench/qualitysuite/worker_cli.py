from __future__ import annotations

from cookimport.bench.qualitysuite.shared import *  # noqa: F401,F403
from cookimport.bench.qualitysuite.persistence import _load_quality_experiment_result_snapshot, _quality_experiment_result_snapshot_path, _write_quality_experiment_result_snapshot
from cookimport.bench.qualitysuite.summary import QualityExperimentResult
from cookimport.bench.qualitysuite import persistence as _persistence
from cookimport.bench.qualitysuite import shared as _shared
from cookimport.bench.qualitysuite import summary as _summary

for _module in (_shared, _persistence, _summary):
    globals().update(
        {name: getattr(_module, name) for name in dir(_module) if not name.startswith("__")}
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
        "cookimport.bench.qualitysuite.worker_cli",
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

def _build_worker_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cookimport.bench.qualitysuite.worker_cli",
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
