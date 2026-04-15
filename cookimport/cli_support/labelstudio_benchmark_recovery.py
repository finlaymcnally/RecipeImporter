from __future__ import annotations

from cookimport.cli_support import (
    Any,
    Path,
    _path_for_manifest,
    _write_eval_run_manifest,
    json,
    summarize_knowledge_stage_artifacts,
)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_json_dict_or_none(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def find_interrupted_knowledge_stage_root(pred_run: Path | None) -> Path | None:
    if pred_run is None:
        return None
    candidates = sorted(
        path
        for path in pred_run.glob("raw/llm/*/knowledge")
        if path.exists() and path.is_dir()
    )
    if not candidates:
        return None
    for candidate in candidates:
        if (candidate / "stage_status.json").exists():
            return candidate
    return candidates[0]


def finalize_interrupted_benchmark_run(
    *,
    eval_output_dir: Path,
    source_path: Path,
    source_hash: str | None,
    pred_run: Path | None,
    processed_run_root: Path | None,
    selected_gold: Path,
    selected_eval_mode: str,
    predictions_in_path: Path | None,
    predictions_out_path: Path | None,
    should_upload_predictions: bool,
    write_markdown: bool,
    write_label_studio_tasks: bool,
    phase: str,
) -> None:
    eval_output_dir.mkdir(parents=True, exist_ok=True)

    prediction_timeseries_path = eval_output_dir / "processing_timeseries_prediction.jsonl"
    evaluation_timeseries_path = eval_output_dir / "processing_timeseries_evaluation.jsonl"
    benchmark_status_path = eval_output_dir / "benchmark_status.json"
    partial_summary_path = eval_output_dir / "partial_benchmark_summary.json"

    prediction_artifacts: dict[str, Any] = {}
    if pred_run is not None:
        prediction_artifacts["prediction_run_dir"] = (
            _path_for_manifest(eval_output_dir, pred_run) or str(pred_run)
        )
        stage_predictions_path = pred_run / "semantic_row_predictions.json"
        if stage_predictions_path.exists():
            prediction_artifacts["semantic_row_predictions_json"] = (
                _path_for_manifest(eval_output_dir, stage_predictions_path)
                or str(stage_predictions_path)
            )
        extracted_archive_path = pred_run / "extracted_archive.json"
        if extracted_archive_path.exists():
            prediction_artifacts["extracted_archive_json"] = (
                _path_for_manifest(eval_output_dir, extracted_archive_path)
                or str(extracted_archive_path)
            )
    if prediction_timeseries_path.exists():
        prediction_artifacts["processing_timeseries_prediction_jsonl"] = (
            _path_for_manifest(eval_output_dir, prediction_timeseries_path)
            or prediction_timeseries_path.name
        )
    if evaluation_timeseries_path.exists():
        prediction_artifacts["processing_timeseries_evaluation_jsonl"] = (
            _path_for_manifest(eval_output_dir, evaluation_timeseries_path)
            or evaluation_timeseries_path.name
        )

    knowledge_stage_summary: dict[str, Any] | None = None
    knowledge_stage_root = find_interrupted_knowledge_stage_root(pred_run)
    if knowledge_stage_root is not None:
        try:
            knowledge_stage_summary = summarize_knowledge_stage_artifacts(knowledge_stage_root)
        except Exception:  # noqa: BLE001
            status_payload = _load_json_dict_or_none(knowledge_stage_root / "stage_status.json")
            if isinstance(status_payload, dict):
                pre_kill_failure_counts = status_payload.get("pre_kill_failure_counts")
                if not isinstance(pre_kill_failure_counts, dict):
                    pre_kill_failure_counts = {}
                knowledge_stage_summary = {
                    "stage_state": str(status_payload.get("stage_state") or "").strip() or None,
                    "termination_cause": str(
                        status_payload.get("termination_cause") or ""
                    ).strip()
                    or None,
                    "finalization_completeness": str(
                        status_payload.get("finalization_completeness") or ""
                    ).strip()
                    or None,
                    "artifact_states": dict(status_payload.get("artifact_states") or {}),
                    "pre_kill_failure_counts": pre_kill_failure_counts,
                    "pre_kill_failures_observed": any(
                        int(value) > 0
                        for value in pre_kill_failure_counts.values()
                        if _coerce_int(value) is not None
                    ),
                }

    status_payload = {
        "schema_version": "benchmark_status.v1",
        "status": "interrupted",
        "completed": False,
        "interruption_cause": "operator",
        "phase": str(phase).strip() or "unknown",
        "eval_mode": str(selected_eval_mode).strip() or None,
        "source_path": str(source_path),
        "source_hash": source_hash,
        "prediction_run_dir": prediction_artifacts.get("prediction_run_dir"),
        "processed_run_root": (
            _path_for_manifest(eval_output_dir, processed_run_root)
            if processed_run_root is not None
            else None
        ),
    }
    benchmark_status_path.write_text(
        json.dumps(status_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    partial_summary_payload = {
        "schema_version": "partial_benchmark_summary.v1",
        "status": "interrupted",
        "completed": False,
        "interruption_cause": "operator",
        "phase": str(phase).strip() or "unknown",
        "eval_mode": str(selected_eval_mode).strip() or None,
        "prediction_artifacts": prediction_artifacts,
        "knowledge_stage": knowledge_stage_summary,
    }
    partial_summary_path.write_text(
        json.dumps(partial_summary_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    _write_eval_run_manifest(
        run_root=eval_output_dir,
        run_kind="labelstudio_benchmark",
        source_path=str(source_path),
        source_hash=source_hash,
        importer_name=None,
        run_config={
            "upload": bool(should_upload_predictions),
            "write_markdown": bool(write_markdown),
            "write_label_studio_tasks": bool(write_label_studio_tasks),
            "eval_mode": str(selected_eval_mode).strip() or None,
            "predictions_in_path": (
                str(predictions_in_path) if predictions_in_path is not None else None
            ),
            "predictions_out_path": (
                str(predictions_out_path) if predictions_out_path is not None else None
            ),
        },
        artifacts={
            "benchmark_status_json": benchmark_status_path.name,
            "partial_benchmark_summary_json": partial_summary_path.name,
        },
        notes=(
            "Interrupted benchmark run. "
            f"Phase: {phase}. "
            f"Gold source: {selected_gold}."
        ),
    )
