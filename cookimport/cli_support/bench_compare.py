from __future__ import annotations

from . import (
    Any,
    BACK_ACTION,
    BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY,
    BENCHMARK_COMPARE_INGREDIENT_LABEL,
    BENCHMARK_COMPARE_SEA_SOURCE_KEY,
    BENCHMARK_COMPARE_VARIANT_LABEL,
    BENCHMARK_EVAL_MODE_SOURCE_ROWS,
    CODEX_FARM_RECIPE_MODE_BENCHMARK,
    CODEX_FARM_RECIPE_MODE_EXTRACT,
    DEFAULT_INPUT,
    DEFAULT_LABELSTUDIO_BENCHMARK_COMPARISONS,
    LABELSTUDIO_BENCHMARK_COMPARE_SCHEMA_VERSION,
    LINE_ROLE_GATED_INGREDIENT_YIELD_DROP_MIN,
    LINE_ROLE_GATED_METRIC_DELTA_MIN,
    LINE_ROLE_GATED_MIN_INGREDIENT_RECALL,
    LINE_ROLE_GATED_MIN_RECIPE_NOTES_RECALL,
    LINE_ROLE_GATED_MIN_RECIPE_VARIANT_RECALL,
    LINE_ROLE_GATED_OTHER_KNOWLEDGE_DROP_MIN,
    LINE_ROLE_REGRESSION_GATES_SCHEMA_VERSION,
    Path,
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
    _benchmark_report_metric_bundle,
    _fail,
    _format_processing_time,
    _golden_benchmark_root,
    _golden_pulled_from_labelstudio_root,
    _golden_sent_to_labelstudio_root,
    _is_row_benchmark_eval_mode,
    _load_json_dict,
    _normalize_codex_farm_recipe_mode,
    _normalize_llm_recipe_pipeline,
    _print_prelabel_completion_summary,
    _processing_timeseries_history_path,
    _report_count,
    _report_optional_metric,
    build_line_role_joined_line_rows,
    build_stage_call_kwargs_from_run_settings,
    csv,
    dt,
    history_root_for_output,
    json,
    stage_artifact_stem,
    slugify_name,
    typer,
)

def _resolve_labelstudio_benchmark_compare_report_root(
    run_dir: Path,
) -> Path | None:
    candidate = run_dir.expanduser()
    if candidate.is_file():
        if candidate.name == "all_method_benchmark_multi_source_report.json":
            return candidate.parent
        return None
    report_path = candidate / "all_method_benchmark_multi_source_report.json"
    if report_path.exists() and report_path.is_file():
        return candidate
    nested_root = candidate / "all-method-benchmark"
    nested_report = nested_root / "all_method_benchmark_multi_source_report.json"
    if nested_report.exists() and nested_report.is_file():
        return nested_root
    return None


def _resolve_labelstudio_benchmark_compare_input(
    run_dir: Path,
) -> dict[str, Any] | None:
    candidate = run_dir.expanduser()
    if candidate.is_file():
        if candidate.name == "all_method_benchmark_multi_source_report.json":
            return {
                "mode": "all_method_report",
                "report_root": candidate.parent,
            }
        if candidate.name == "eval_report.json":
            return {
                "mode": "single_eval_report",
                "report_root": candidate.parent,
                "eval_report_path": candidate,
            }
        return None

    report_root = _resolve_labelstudio_benchmark_compare_report_root(candidate)
    if report_root is not None:
        return {
            "mode": "all_method_report",
            "report_root": report_root,
        }

    eval_report_path = candidate / "eval_report.json"
    if eval_report_path.exists() and eval_report_path.is_file():
        return {
            "mode": "single_eval_report",
            "report_root": candidate,
            "eval_report_path": eval_report_path,
        }
    return None


def _parse_run_config_summary(summary: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    text = str(summary or "").strip()
    if not text:
        return parsed
    for part in text.split(" | "):
        chunk = part.strip()
        if not chunk or "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        cleaned_key = key.strip()
        if not cleaned_key:
            continue
        parsed[cleaned_key] = value.strip()
    return parsed


def _resolve_artifact_path(base_dir: Path, value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve(strict=False)


def _source_key_from_row(row: dict[str, Any]) -> str:
    source_group_key = str(row.get("source_group_key") or "").strip().lower()
    if source_group_key:
        return source_group_key
    source_slug = str(row.get("source_slug") or "").strip().lower()
    if source_slug:
        return source_slug
    source_file_name = str(row.get("source_file_name") or "").strip()
    if source_file_name:
        return slugify_name(Path(source_file_name).stem)
    source_file = str(row.get("source_file") or "").strip()
    if source_file:
        return slugify_name(Path(source_file).stem)
    return ""


def _index_labelstudio_benchmark_sources(
    report_payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    source_rows = report_payload.get("sources")
    if not isinstance(source_rows, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        source_key = _source_key_from_row(row)
        if source_key:
            indexed[source_key] = row
    return indexed


def _load_source_winner_eval_report(
    *,
    multi_source_report_root: Path,
    source_row: dict[str, Any],
) -> tuple[dict[str, Any], Path] | tuple[None, None]:
    report_json_path_value = str(source_row.get("report_json_path") or "").strip()
    if not report_json_path_value:
        return None, None
    source_report_path = _resolve_artifact_path(
        multi_source_report_root, report_json_path_value
    )
    if source_report_path is None:
        return None, None
    source_report = _load_json_dict(source_report_path)
    if source_report is None:
        return None, None
    winner_payload = source_report.get("winner_by_f1")
    winner = winner_payload if isinstance(winner_payload, dict) else None
    if not isinstance(winner, dict):
        variants = source_report.get("variants")
        if isinstance(variants, list):
            successful_variants = [
                row
                for row in variants
                if isinstance(row, dict)
                and str(row.get("status") or "").strip().lower() == "ok"
            ]
            if successful_variants:
                winner = min(
                    successful_variants,
                    key=lambda row: _report_count(row.get("rank")) or 10**9,
                )
    if not isinstance(winner, dict):
        return None, None
    eval_report_path_value = str(winner.get("eval_report_json") or "").strip()
    if not eval_report_path_value:
        return None, None
    eval_report_path = _resolve_artifact_path(
        source_report_path.parent,
        eval_report_path_value,
    )
    if eval_report_path is None:
        return None, None
    eval_report = _load_json_dict(eval_report_path)
    if eval_report is None:
        return None, None
    return eval_report, eval_report_path


def _label_recall_from_eval_report(eval_report: dict[str, Any], label: str) -> float | None:
    per_label = eval_report.get("per_label")
    if not isinstance(per_label, dict):
        return None
    label_payload = per_label.get(label)
    if not isinstance(label_payload, dict):
        return None
    return _report_optional_metric(label_payload.get("recall"))


def _dir_has_json_files(path: Path | None) -> bool:
    if path is None or not path.exists() or not path.is_dir():
        return False
    return any(file_path.is_file() for file_path in path.glob("*.json"))


def _read_artifact_list_from_manifest(path: Path | None) -> list[Path]:
    if path is None or not path.exists() or not path.is_file():
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return []
    base_dir = path.parent
    paths: list[Path] = []
    for line in raw_text.splitlines():
        value = line.strip()
        if not value:
            continue
        artifact_path = Path(value)
        if not artifact_path.is_absolute():
            artifact_path = base_dir / artifact_path
        paths.append(artifact_path)
    return paths


def _all_artifact_paths_exist(artifacts: list[Path] | None) -> bool:
    if not artifacts:
        return False
    return all(path.exists() and path.is_file() for path in artifacts)


def _has_llm_artifact_evidence(
    *,
    prediction_run_dir: Path,
    prediction_artifacts: dict[str, Any] | None,
) -> bool:
    if isinstance(prediction_artifacts, dict):
        if any(
            bool(prediction_artifacts.get(key))
            for key in (
                "recipe_manifest_json",
                "prompt_inputs_manifest_txt",
                "prompt_outputs_manifest_txt",
            )
        ):
            return True
    llm_root = prediction_run_dir / "raw" / "llm"
    if not llm_root.exists() or not llm_root.is_dir():
        return False
    recipe_stage_dirs = {
        stage_artifact_stem("recipe_refine"),
    }
    for workbook_dir in llm_root.iterdir():
        if not workbook_dir.is_dir():
            continue
        if any((workbook_dir / stage_dir_name).exists() for stage_dir_name in recipe_stage_dirs):
            return True
    return False


def _resolve_codex_farm_mode_and_pipeline(
    *,
    eval_run_config: dict[str, Any],
    summary_tokens: dict[str, str],
    prediction_run_config: dict[str, Any],
    prediction_run_manifest: dict[str, Any] | None,
    prediction_artifacts: dict[str, Any] | None,
    prediction_run_dir: Path,
) -> tuple[str, str, str]:
    pred_manifest_payload = (
        prediction_run_manifest.get("run_config")
        if isinstance(prediction_run_manifest, dict)
        else None
    )
    manifest_mode = (
        pred_manifest_payload.get("codex_farm_recipe_mode")
        if isinstance(pred_manifest_payload, dict)
        else None
    )
    manifest_pipeline = (
        pred_manifest_payload.get("llm_recipe_pipeline")
        if isinstance(pred_manifest_payload, dict)
        else None
    )

    has_mode_metadata = bool(
        prediction_run_config.get("codex_farm_recipe_mode")
        or eval_run_config.get("codex_farm_recipe_mode")
        or manifest_mode
        or summary_tokens.get("codex_farm_recipe_mode")
    )

    artifact_evidence = _has_llm_artifact_evidence(
        prediction_run_dir=prediction_run_dir,
        prediction_artifacts=prediction_artifacts,
    )

    raw_mode = str(
        prediction_run_config.get("codex_farm_recipe_mode")
        or eval_run_config.get("codex_farm_recipe_mode")
        or manifest_mode
        or summary_tokens.get("codex_farm_recipe_mode")
        or ""
    ).strip()
    if not raw_mode:
        if artifact_evidence:
            raw_mode = CODEX_FARM_RECIPE_MODE_BENCHMARK
        else:
            raw_mode = CODEX_FARM_RECIPE_MODE_EXTRACT

    raw_pipeline = str(
        prediction_run_config.get("llm_recipe_pipeline")
        or eval_run_config.get("llm_recipe_pipeline")
        or manifest_pipeline
        or summary_tokens.get("llm_recipe_pipeline")
        or ""
    ).strip()
    if not raw_pipeline:
        if raw_mode == CODEX_FARM_RECIPE_MODE_BENCHMARK:
            raw_pipeline = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
        else:
            raw_pipeline = "off"

    if has_mode_metadata:
        mode_source = "metadata"
    elif artifact_evidence and raw_mode == CODEX_FARM_RECIPE_MODE_BENCHMARK:
        mode_source = "inferred"
    else:
        mode_source = "unknown"

    return (
        _normalize_codex_farm_recipe_mode(raw_mode),
        _normalize_llm_recipe_pipeline(raw_pipeline),
        mode_source,
    )


def _build_source_debug_artifact_status(
    *,
    eval_report_path: Path,
    eval_report: dict[str, Any],
    codex_farm_recipe_mode: str,
    llm_recipe_pipeline: str,
    prediction_run_dir: Path | None = None,
) -> dict[str, Any]:
    eval_dir = eval_report_path.parent
    eval_artifacts = eval_report.get("artifacts")
    if not isinstance(eval_artifacts, dict):
        eval_artifacts = {}
    aligned_path = _resolve_artifact_path(
        eval_dir,
        eval_artifacts.get("aligned_prediction_blocks_jsonl"),
    )
    if aligned_path is None:
        aligned_path = eval_dir / "aligned_prediction_blocks.jsonl"

    checks: list[dict[str, Any]] = [
        {
            "name": "aligned_prediction_blocks_jsonl",
            "present": bool(aligned_path.exists() and aligned_path.is_file()),
            "path": str(aligned_path),
        }
    ]

    normalized_mode = _normalize_codex_farm_recipe_mode(codex_farm_recipe_mode)
    normalized_pipeline = str(llm_recipe_pipeline or "").strip().lower()
    requires_llm_debug = (
        normalized_mode == CODEX_FARM_RECIPE_MODE_BENCHMARK
        and normalized_pipeline != "off"
    )

    if requires_llm_debug:
        candidate_prediction_run_dir = (
            prediction_run_dir
            if isinstance(prediction_run_dir, Path)
            else eval_dir
        )
        prediction_manifest = _load_json_dict(
            candidate_prediction_run_dir / "run_manifest.json"
        )
        prediction_artifacts = (
            prediction_manifest.get("artifacts")
            if isinstance(prediction_manifest, dict)
            else None
        )
        if not isinstance(prediction_artifacts, dict):
            prediction_artifacts = {}
        prompt_inputs_manifest = _resolve_artifact_path(
            candidate_prediction_run_dir,
            prediction_artifacts.get("prompt_inputs_manifest_txt"),
        )
        prompt_outputs_manifest = _resolve_artifact_path(
            candidate_prediction_run_dir,
            prediction_artifacts.get("prompt_outputs_manifest_txt"),
        )
        prompt_input_payloads = _read_artifact_list_from_manifest(
            prompt_inputs_manifest
        )
        prompt_output_payloads = _read_artifact_list_from_manifest(
            prompt_outputs_manifest
        )
        recipe_manifest_path = _resolve_artifact_path(
            candidate_prediction_run_dir,
            prediction_artifacts.get("recipe_manifest_json"),
        )
        recipe_manifest = (
            _load_json_dict(recipe_manifest_path)
            if recipe_manifest_path is not None
            else None
        )
        recipe_paths = (
            recipe_manifest.get("paths")
            if isinstance(recipe_manifest, dict)
            else None
        )
        if not isinstance(recipe_paths, dict):
            recipe_paths = {}
        recipe_phase_input_dir = _resolve_artifact_path(
            recipe_manifest_path.parent
            if recipe_manifest_path is not None
            else candidate_prediction_run_dir,
            recipe_paths.get("recipe_phase_input_dir"),
        )
        recipe_phase_proposals_dir = _resolve_artifact_path(
            recipe_manifest_path.parent
            if recipe_manifest_path is not None
            else candidate_prediction_run_dir,
            recipe_paths.get("recipe_phase_proposals_dir"),
        )
        checks.extend(
            [
                {
                    "name": "prompt_inputs_manifest_txt",
                    "present": bool(
                        prompt_inputs_manifest is not None
                        and prompt_inputs_manifest.exists()
                        and prompt_inputs_manifest.is_file()
                    ),
                    "path": str(prompt_inputs_manifest)
                    if prompt_inputs_manifest is not None
                    else None,
                },
                {
                    "name": "prompt_outputs_manifest_txt",
                    "present": bool(
                        prompt_outputs_manifest is not None
                        and prompt_outputs_manifest.exists()
                        and prompt_outputs_manifest.is_file()
                    ),
                    "path": str(prompt_outputs_manifest)
                    if prompt_outputs_manifest is not None
                    else None,
                },
                {
                    "name": "prompt_request_payloads",
                    "present": _all_artifact_paths_exist(prompt_input_payloads),
                    "path": (
                        str(prompt_inputs_manifest)
                        if prompt_inputs_manifest is not None
                        else None
                    ),
                    "count": len(prompt_input_payloads),
                },
                {
                    "name": "prompt_response_payloads",
                    "present": _all_artifact_paths_exist(prompt_output_payloads),
                    "path": (
                        str(prompt_outputs_manifest)
                        if prompt_outputs_manifest is not None
                        else None
                    ),
                    "count": len(prompt_output_payloads),
                },
                {
                    "name": "recipe_manifest_json",
                    "present": bool(
                        recipe_manifest_path is not None
                        and recipe_manifest_path.exists()
                        and recipe_manifest_path.is_file()
                    ),
                    "path": (
                        str(recipe_manifest_path)
                        if recipe_manifest_path is not None
                        else None
                    ),
                },
                {
                    "name": "recipe_phase_input_json",
                    "present": _dir_has_json_files(recipe_phase_input_dir),
                    "path": (
                        str(recipe_phase_input_dir)
                        if recipe_phase_input_dir is not None
                        else None
                    ),
                },
                {
                    "name": "recipe_phase_proposal_json",
                    "present": _dir_has_json_files(recipe_phase_proposals_dir),
                    "path": (
                        str(recipe_phase_proposals_dir)
                        if recipe_phase_proposals_dir is not None
                        else None
                    ),
                },
            ]
        )

    required_checks = checks if requires_llm_debug else checks[:1]
    missing = [
        str(check.get("name"))
        for check in required_checks
        if not bool(check.get("present"))
    ]
    return {
        "required": requires_llm_debug,
        "checks": checks,
        "required_checks": [str(check.get("name") or "") for check in required_checks],
        "all_present": len(missing) == 0,
        "missing": missing,
    }


def _build_labelstudio_benchmark_source_context(
    *,
    multi_source_report_root: Path,
    source_row: dict[str, Any],
) -> dict[str, Any] | None:
    eval_report, eval_report_path = _load_source_winner_eval_report(
        multi_source_report_root=multi_source_report_root,
        source_row=source_row,
    )
    if eval_report is None or eval_report_path is None:
        return None

    winner_metrics = source_row.get("winner_metrics")
    if not isinstance(winner_metrics, dict):
        winner_metrics = {}
    return _build_labelstudio_benchmark_context_from_eval_report(
        source_key=_source_key_from_row(source_row),
        source_file=str(source_row.get("source_file") or ""),
        winner_metrics=winner_metrics,
        eval_report=eval_report,
        eval_report_path=eval_report_path,
    )


def _infer_source_file_from_eval_report_and_manifest(
    *,
    eval_report: dict[str, Any],
    eval_report_path: Path,
) -> str:
    source_file = str(eval_report.get("source_file") or "").strip()
    if source_file:
        return source_file

    eval_run_manifest = _load_json_dict(eval_report_path.parent / "run_manifest.json")
    if isinstance(eval_run_manifest, dict):
        source_payload = eval_run_manifest.get("source")
        if isinstance(source_payload, dict):
            source_file = str(source_payload.get("path") or "").strip()
            if source_file:
                return source_file
        run_config_payload = eval_run_manifest.get("run_config")
        if isinstance(run_config_payload, dict):
            source_file = str(run_config_payload.get("source_file") or "").strip()
            if source_file:
                return source_file
            prediction_run_config = run_config_payload.get("prediction_run_config")
            if isinstance(prediction_run_config, dict):
                source_file = str(prediction_run_config.get("source_file") or "").strip()
                if source_file:
                    return source_file

    prediction_run_manifest = _load_json_dict(
        eval_report_path.parent / "run_manifest.json"
    )
    if isinstance(prediction_run_manifest, dict):
        source_payload = prediction_run_manifest.get("source")
        if isinstance(source_payload, dict):
            source_file = str(source_payload.get("path") or "").strip()
            if source_file:
                return source_file
        run_config_payload = prediction_run_manifest.get("run_config")
        if isinstance(run_config_payload, dict):
            source_file = str(run_config_payload.get("source_file") or "").strip()
            if source_file:
                return source_file
            prediction_run_config = run_config_payload.get("prediction_run_config")
            if isinstance(prediction_run_config, dict):
                source_file = str(prediction_run_config.get("source_file") or "").strip()
                if source_file:
                    return source_file
    return ""


def _build_labelstudio_benchmark_context_from_eval_report(
    *,
    source_key: str,
    source_file: str,
    winner_metrics: dict[str, Any] | None,
    eval_report: dict[str, Any],
    eval_report_path: Path,
) -> dict[str, Any]:
    summary_tokens = _parse_run_config_summary(
        str((eval_report.get("run_config_summary") or ""))
    )

    eval_run_manifest = _load_json_dict(eval_report_path.parent / "run_manifest.json")
    run_config_payload = (
        eval_run_manifest.get("run_config")
        if isinstance(eval_run_manifest, dict)
        else None
    )
    if not isinstance(run_config_payload, dict):
        run_config_payload = {}
    prediction_run_config = run_config_payload.get("prediction_run_config")
    if not isinstance(prediction_run_config, dict):
        prediction_run_config = {}
    eval_run_artifacts = (
        eval_run_manifest.get("artifacts")
        if isinstance(eval_run_manifest, dict)
        else None
    )
    if not isinstance(eval_run_artifacts, dict):
        eval_run_artifacts = {}
    prediction_run_dir = _resolve_artifact_path(
        eval_report_path.parent,
        eval_run_artifacts.get("artifact_root_dir"),
    )
    prediction_run_dir_is_inferred = prediction_run_dir is None
    if prediction_run_dir is None:
        prediction_run_dir = eval_report_path.parent
    prediction_run_manifest = _load_json_dict(prediction_run_dir / "run_manifest.json")
    prediction_run_artifacts = (
        prediction_run_manifest.get("artifacts")
        if isinstance(prediction_run_manifest, dict)
        else None
    )
    if not isinstance(prediction_run_artifacts, dict):
        prediction_run_artifacts = {}
    codex_farm_recipe_mode, llm_recipe_pipeline, mode_source = (
        _resolve_codex_farm_mode_and_pipeline(
            eval_run_config=run_config_payload,
            summary_tokens=summary_tokens,
            prediction_run_config=prediction_run_config,
            prediction_run_manifest=prediction_run_manifest,
            prediction_artifacts=prediction_run_artifacts,
            prediction_run_dir=prediction_run_dir,
        )
    )

    debug_artifacts = _build_source_debug_artifact_status(
        eval_report_path=eval_report_path,
        eval_report=eval_report,
        codex_farm_recipe_mode=codex_farm_recipe_mode,
        llm_recipe_pipeline=llm_recipe_pipeline,
        prediction_run_dir=prediction_run_dir,
    )
    winner_metric_bundle = _benchmark_report_metric_bundle(
        winner_metrics if isinstance(winner_metrics, dict) else None
    )
    eval_metric_bundle = _benchmark_report_metric_bundle(eval_report)
    overall_line_accuracy = _report_optional_metric(eval_report.get("overall_line_accuracy"))
    if overall_line_accuracy is None:
        overall_line_accuracy = _report_optional_metric(
            eval_metric_bundle.get("strict_accuracy")
        )
    resolved_source_file = str(source_file or "").strip()
    if not resolved_source_file:
        resolved_source_file = _infer_source_file_from_eval_report_and_manifest(
            eval_report=eval_report,
            eval_report_path=eval_report_path,
        )
    return {
        "source_group_key": str(source_key or "").strip(),
        "source_file": resolved_source_file,
        "winner_metrics": {**winner_metric_bundle},
        "overall_line_accuracy": overall_line_accuracy,
        "practical_f1": _report_optional_metric(
            eval_metric_bundle.get("macro_f1_excluding_other")
        ),
        "ingredient_recall": _label_recall_from_eval_report(
            eval_report, BENCHMARK_COMPARE_INGREDIENT_LABEL
        ),
        "variant_recall": _label_recall_from_eval_report(
            eval_report, BENCHMARK_COMPARE_VARIANT_LABEL
        ),
        "codex_farm_mode_source": mode_source,
        "codex_farm_recipe_mode": _normalize_codex_farm_recipe_mode(
            codex_farm_recipe_mode
        ),
        "llm_recipe_pipeline": llm_recipe_pipeline,
        "prediction_run_dir_inferred": bool(prediction_run_dir_is_inferred),
        "eval_report_json_path": str(eval_report_path),
        "debug_artifacts": debug_artifacts,
    }


def _metric_delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return candidate - baseline


def _is_pipeline_off(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"", "off", "none", "null"}


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_key_from_source_path(path_value: str) -> str:
    source_text = str(path_value or "").strip()
    if not source_text:
        return ""
    return slugify_name(Path(source_text).stem)


def _history_timestamp_sort_key(row: dict[str, Any]) -> tuple[str, int]:
    timestamp_text = str(row.get("run_timestamp") or "").strip()
    return (timestamp_text, int(row.get("_history_order") or 0))


def _load_benchmark_history_rows(csv_path: Path) -> list[dict[str, Any]]:
    if not csv_path.exists() or not csv_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for order, row in enumerate(reader):
            if not isinstance(row, dict):
                continue
            if str(row.get("run_category") or "").strip() != "benchmark_eval":
                continue
            materialized = dict(row)
            materialized["_history_order"] = order
            run_config_payload = materialized.get("run_config_json")
            run_config: dict[str, Any] = {}
            if isinstance(run_config_payload, str) and run_config_payload.strip():
                try:
                    parsed = json.loads(run_config_payload)
                except json.JSONDecodeError:
                    parsed = {}
                if isinstance(parsed, dict):
                    run_config = parsed
            materialized["_run_config"] = run_config
            materialized["_source_key"] = _source_key_from_source_path(
                str(materialized.get("file_name") or "")
            )
            rows.append(materialized)
    return rows


def _load_eval_report_from_history_row(row: dict[str, Any]) -> dict[str, Any] | None:
    run_dir_raw = str(row.get("run_dir") or "").strip()
    if not run_dir_raw:
        return None
    report_path = Path(run_dir_raw) / "eval_report.json"
    payload = _load_json_dict(report_path)
    if not isinstance(payload, dict):
        return None
    return payload


def _build_joined_line_rows_for_history_row(
    row: dict[str, Any],
) -> list[dict[str, Any]] | None:
    run_dir_raw = str(row.get("run_dir") or "").strip()
    if not run_dir_raw:
        return None
    eval_output_dir = Path(run_dir_raw)
    report = _load_eval_report_from_history_row(row)
    if not isinstance(report, dict):
        return None
    return build_line_role_joined_line_rows(
        report=report,
        eval_output_dir=eval_output_dir,
        line_role_predictions_path=None,
    )


def _resolve_line_role_baseline_joined_rows(
    *,
    history_csv_path: Path,
    source_key: str,
    llm_recipe_pipeline: str,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    history_rows = _load_benchmark_history_rows(history_csv_path)
    primary_row = _find_latest_history_row(
        history_rows,
        source_key=source_key,
        predicate=lambda row: (
            _is_row_benchmark_eval_mode(row.get("eval_scope"))
            and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
            and str((row.get("_run_config") or {}).get("llm_recipe_pipeline") or "").strip()
            == str(llm_recipe_pipeline or "").strip()
        ),
    )
    fallback_row: dict[str, Any] | None = None
    if primary_row is None and not _is_pipeline_off(llm_recipe_pipeline):
        fallback_row = _find_latest_history_row(
            history_rows,
            source_key=source_key,
            predicate=lambda row: (
                _is_row_benchmark_eval_mode(row.get("eval_scope"))
                and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
                and _is_pipeline_off((row.get("_run_config") or {}).get("llm_recipe_pipeline"))
            ),
        )

    for row in (primary_row, fallback_row):
        if row is None:
            continue
        joined_rows = _build_joined_line_rows_for_history_row(row)
        if joined_rows is not None:
            return joined_rows, row
    return None, None


def _confusion_count(
    *,
    report: dict[str, Any],
    gold_label: str,
    pred_label: str,
) -> int | None:
    confusion = report.get("confusion")
    if not isinstance(confusion, dict):
        return None
    by_gold = confusion.get(gold_label)
    if not isinstance(by_gold, dict):
        return 0
    value = _coerce_int(by_gold.get(pred_label))
    return value if value is not None else 0


def _find_latest_history_row(
    rows: list[dict[str, Any]],
    *,
    source_key: str,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row.get("_source_key") or "") == source_key and predicate(row)
    ]
    if not candidates:
        return None
    candidates.sort(key=_history_timestamp_sort_key, reverse=True)
    return candidates[0]


def _source_available_in_input_root(source_key: str) -> bool:
    if not DEFAULT_INPUT.exists() or not DEFAULT_INPUT.is_dir():
        return False
    for path in DEFAULT_INPUT.iterdir():
        if not path.is_file():
            continue
        if slugify_name(path.stem) == source_key:
            return True
    return False


def _build_line_role_regression_gate_payload(
    *,
    candidate_report: dict[str, Any],
    candidate_source_key: str,
    history_csv_path: Path,
) -> dict[str, Any]:
    history_rows = _load_benchmark_history_rows(history_csv_path)
    gates: list[dict[str, Any]] = []

    def _add_gate(name: str, passed: bool, reason: str) -> None:
        gates.append({"name": name, "passed": bool(passed), "reason": reason})

    if candidate_source_key != BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY:
        _add_gate(
            "foodlab_source_required",
            False,
            (
                "line-role gated mode currently requires source "
                f"{BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY}; got {candidate_source_key or '<unknown>'}."
            ),
        )
    vanilla_foodlab_row = _find_latest_history_row(
        history_rows,
        source_key=BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY,
        predicate=lambda row: (
            _is_pipeline_off((row.get("_run_config") or {}).get("llm_recipe_pipeline"))
            and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
            and _is_row_benchmark_eval_mode(row.get("eval_scope"))
        ),
    )
    codex_foodlab_row = _find_latest_history_row(
        history_rows,
        source_key=BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY,
        predicate=lambda row: (
            _normalize_llm_recipe_pipeline(
                str((row.get("_run_config") or {}).get("llm_recipe_pipeline") or "off")
            )
            == RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
            and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
            and _is_row_benchmark_eval_mode(row.get("eval_scope"))
        ),
    )
    vanilla_foodlab_report = (
        _load_eval_report_from_history_row(vanilla_foodlab_row)
        if vanilla_foodlab_row is not None
        else None
    )
    codex_foodlab_report = (
        _load_eval_report_from_history_row(codex_foodlab_row)
        if codex_foodlab_row is not None
        else None
    )

    candidate_macro = _report_optional_metric(
        candidate_report.get("macro_f1_excluding_other")
    )
    candidate_accuracy = _report_optional_metric(
        candidate_report.get("overall_line_accuracy")
    )
    baseline_macro = (
        _report_optional_metric(vanilla_foodlab_report.get("macro_f1_excluding_other"))
        if isinstance(vanilla_foodlab_report, dict)
        else None
    )
    baseline_accuracy = (
        _report_optional_metric(vanilla_foodlab_report.get("overall_line_accuracy"))
        if isinstance(vanilla_foodlab_report, dict)
        else None
    )
    macro_delta = _metric_delta(candidate_macro, baseline_macro)
    accuracy_delta = _metric_delta(candidate_accuracy, baseline_accuracy)
    if macro_delta is None:
        _add_gate(
            "foodlab_macro_f1_delta_min",
            False,
            "Missing baseline/candidate macro_f1_excluding_other.",
        )
    else:
        _add_gate(
            "foodlab_macro_f1_delta_min",
            macro_delta >= LINE_ROLE_GATED_METRIC_DELTA_MIN,
            (
                f"candidate_minus_baseline={macro_delta:.6f} "
                f"(threshold {LINE_ROLE_GATED_METRIC_DELTA_MIN:.2f})."
            ),
        )
    if accuracy_delta is None:
        _add_gate(
            "foodlab_line_accuracy_delta_min",
            False,
            "Missing baseline/candidate overall_line_accuracy.",
        )
    else:
        _add_gate(
            "foodlab_line_accuracy_delta_min",
            accuracy_delta >= LINE_ROLE_GATED_METRIC_DELTA_MIN,
            (
                f"candidate_minus_baseline={accuracy_delta:.6f} "
                f"(threshold {LINE_ROLE_GATED_METRIC_DELTA_MIN:.2f})."
            ),
        )

    candidate_ingredient_yield = _confusion_count(
        report=candidate_report,
        gold_label="INGREDIENT_LINE",
        pred_label="YIELD_LINE",
    )
    candidate_other_knowledge = _confusion_count(
        report=candidate_report,
        gold_label="OTHER",
        pred_label="KNOWLEDGE",
    )
    confusion_baseline_report = None
    confusion_baseline_source = "missing"
    if isinstance(codex_foodlab_report, dict):
        confusion_baseline_report = codex_foodlab_report
        confusion_baseline_source = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
    elif isinstance(vanilla_foodlab_report, dict):
        confusion_baseline_report = vanilla_foodlab_report
        confusion_baseline_source = "vanilla-off-fallback"
    baseline_ingredient_yield = (
        _confusion_count(
            report=confusion_baseline_report,
            gold_label="INGREDIENT_LINE",
            pred_label="YIELD_LINE",
        )
        if isinstance(confusion_baseline_report, dict)
        else None
    )
    baseline_other_knowledge = (
        _confusion_count(
            report=confusion_baseline_report,
            gold_label="OTHER",
            pred_label="KNOWLEDGE",
        )
        if isinstance(confusion_baseline_report, dict)
        else None
    )

    def _confusion_drop_gate(
        *,
        gate_name: str,
        baseline_value: int | None,
        candidate_value: int | None,
        min_drop_ratio: float,
        baseline_source: str,
    ) -> None:
        if baseline_value is None or candidate_value is None:
            _add_gate(gate_name, False, "Missing baseline/candidate confusion counts.")
            return
        if baseline_value <= 0:
            passed = candidate_value <= 0
            _add_gate(
                gate_name,
                passed,
                (
                    f"Baseline confusion count is 0 ({baseline_source}); "
                    f"candidate={candidate_value}."
                ),
            )
            return
        drop_ratio = (baseline_value - candidate_value) / baseline_value
        _add_gate(
            gate_name,
            drop_ratio >= min_drop_ratio,
            (
                f"baseline_source={baseline_source}, "
                f"baseline={baseline_value}, candidate={candidate_value}, "
                f"drop_ratio={drop_ratio:.6f}, threshold={min_drop_ratio:.2f}."
            ),
        )

    _confusion_drop_gate(
        gate_name="foodlab_ingredient_to_yield_confusion_drop",
        baseline_value=baseline_ingredient_yield,
        candidate_value=candidate_ingredient_yield,
        min_drop_ratio=LINE_ROLE_GATED_INGREDIENT_YIELD_DROP_MIN,
        baseline_source=confusion_baseline_source,
    )
    _confusion_drop_gate(
        gate_name="foodlab_other_to_knowledge_confusion_drop",
        baseline_value=baseline_other_knowledge,
        candidate_value=candidate_other_knowledge,
        min_drop_ratio=LINE_ROLE_GATED_OTHER_KNOWLEDGE_DROP_MIN,
        baseline_source=confusion_baseline_source,
    )

    candidate_notes_recall = _label_recall_from_eval_report(
        candidate_report,
        "RECIPE_NOTES",
    )
    candidate_variant_recall = _label_recall_from_eval_report(
        candidate_report,
        "RECIPE_VARIANT",
    )
    candidate_ingredient_recall = _label_recall_from_eval_report(
        candidate_report,
        "INGREDIENT_LINE",
    )
    for gate_name, recall_value, threshold in (
        (
            "foodlab_recipe_notes_recall_min",
            candidate_notes_recall,
            LINE_ROLE_GATED_MIN_RECIPE_NOTES_RECALL,
        ),
        (
            "foodlab_recipe_variant_recall_min",
            candidate_variant_recall,
            LINE_ROLE_GATED_MIN_RECIPE_VARIANT_RECALL,
        ),
        (
            "foodlab_ingredient_recall_min",
            candidate_ingredient_recall,
            LINE_ROLE_GATED_MIN_INGREDIENT_RECALL,
        ),
    ):
        if recall_value is None:
            _add_gate(gate_name, False, "Missing candidate per-label recall.")
            continue
        _add_gate(
            gate_name,
            recall_value > threshold,
            f"candidate_recall={recall_value:.6f}, threshold>{threshold:.2f}.",
        )

    sea_exists = _source_available_in_input_root(BENCHMARK_COMPARE_SEA_SOURCE_KEY)
    if sea_exists:
        sea_vanilla_row = _find_latest_history_row(
            history_rows,
            source_key=BENCHMARK_COMPARE_SEA_SOURCE_KEY,
            predicate=lambda row: (
                _is_pipeline_off((row.get("_run_config") or {}).get("llm_recipe_pipeline"))
                and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
                and _is_row_benchmark_eval_mode(row.get("eval_scope"))
            ),
        )
        sea_candidate_row = _find_latest_history_row(
            history_rows,
            source_key=BENCHMARK_COMPARE_SEA_SOURCE_KEY,
            predicate=lambda row: (
                not _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
                and _is_row_benchmark_eval_mode(row.get("eval_scope"))
            ),
        )
        sea_vanilla_report = (
            _load_eval_report_from_history_row(sea_vanilla_row)
            if sea_vanilla_row is not None
            else None
        )
        sea_candidate_report = (
            _load_eval_report_from_history_row(sea_candidate_row)
            if sea_candidate_row is not None
            else None
        )
        for metric_name, field in (
            ("sea_macro_f1_no_regression", "macro_f1_excluding_other"),
            ("sea_line_accuracy_no_regression", "overall_line_accuracy"),
        ):
            baseline_value = (
                _report_optional_metric(sea_vanilla_report.get(field))
                if isinstance(sea_vanilla_report, dict)
                else None
            )
            candidate_value = (
                _report_optional_metric(sea_candidate_report.get(field))
                if isinstance(sea_candidate_report, dict)
                else None
            )
            if baseline_value is None or candidate_value is None:
                _add_gate(
                    metric_name,
                    False,
                    "Missing seaandsmokecutdown baseline/candidate metrics in benchmark history.",
                )
                continue
            _add_gate(
                metric_name,
                candidate_value >= baseline_value,
                f"candidate={candidate_value:.6f}, baseline={baseline_value:.6f}.",
            )

    failed_gate_count = sum(1 for gate in gates if not bool(gate.get("passed")))
    return {
        "schema_version": LINE_ROLE_REGRESSION_GATES_SCHEMA_VERSION,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "history_csv": str(history_csv_path),
        "candidate_source_key": candidate_source_key,
        "overall": {
            "verdict": "PASS" if failed_gate_count == 0 else "FAIL",
            "gate_count": len(gates),
            "failed_gate_count": failed_gate_count,
            "passed_gate_count": len(gates) - failed_gate_count,
        },
        "gates": gates,
    }


def _build_labelstudio_benchmark_compare_payload(
    *,
    baseline_report_root: Path,
    candidate_report_root: Path,
) -> dict[str, Any]:
    baseline_report_payload = _load_json_dict(
        baseline_report_root / "all_method_benchmark_multi_source_report.json"
    )
    candidate_report_payload = _load_json_dict(
        candidate_report_root / "all_method_benchmark_multi_source_report.json"
    )
    if baseline_report_payload is None:
        _fail(
            "Baseline all-method benchmark report is missing or invalid: "
            f"{baseline_report_root / 'all_method_benchmark_multi_source_report.json'}"
        )
    if candidate_report_payload is None:
        _fail(
            "Candidate all-method benchmark report is missing or invalid: "
            f"{candidate_report_root / 'all_method_benchmark_multi_source_report.json'}"
        )

    baseline_rows = _index_labelstudio_benchmark_sources(baseline_report_payload)
    candidate_rows = _index_labelstudio_benchmark_sources(candidate_report_payload)
    known_source_keys = sorted(set(baseline_rows) | set(candidate_rows))
    source_comparison: dict[str, dict[str, Any]] = {}
    for source_key in known_source_keys:
        baseline_context = (
            _build_labelstudio_benchmark_source_context(
                multi_source_report_root=baseline_report_root,
                source_row=baseline_rows[source_key],
            )
            if source_key in baseline_rows
            else None
        )
        candidate_context = (
            _build_labelstudio_benchmark_source_context(
                multi_source_report_root=candidate_report_root,
                source_row=candidate_rows[source_key],
            )
            if source_key in candidate_rows
            else None
        )
        baseline_practical_f1 = (
            _report_optional_metric(baseline_context.get("practical_f1"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_practical_f1 = (
            _report_optional_metric(candidate_context.get("practical_f1"))
            if isinstance(candidate_context, dict)
            else None
        )
        baseline_line_accuracy = (
            _report_optional_metric(baseline_context.get("overall_line_accuracy"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_line_accuracy = (
            _report_optional_metric(candidate_context.get("overall_line_accuracy"))
            if isinstance(candidate_context, dict)
            else None
        )
        baseline_ingredient_recall = (
            _report_optional_metric(baseline_context.get("ingredient_recall"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_ingredient_recall = (
            _report_optional_metric(candidate_context.get("ingredient_recall"))
            if isinstance(candidate_context, dict)
            else None
        )
        baseline_variant_recall = (
            _report_optional_metric(baseline_context.get("variant_recall"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_variant_recall = (
            _report_optional_metric(candidate_context.get("variant_recall"))
            if isinstance(candidate_context, dict)
            else None
        )
        source_comparison[source_key] = {
            "baseline": baseline_context,
            "candidate": candidate_context,
            "deltas": {
                "practical_f1": _metric_delta(
                    candidate_practical_f1,
                    baseline_practical_f1,
                ),
                "overall_line_accuracy": _metric_delta(
                    candidate_line_accuracy,
                    baseline_line_accuracy,
                ),
                "ingredient_recall": _metric_delta(
                    candidate_ingredient_recall,
                    baseline_ingredient_recall,
                ),
                "variant_recall": _metric_delta(
                    candidate_variant_recall,
                    baseline_variant_recall,
                ),
            },
        }

    gates: list[dict[str, Any]] = []
    warnings: list[str] = []

    def _add_warning(message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        if text not in warnings:
            warnings.append(text)

    def _add_gate(name: str, passed: bool, reason: str) -> None:
        gates.append({"name": name, "passed": bool(passed), "reason": reason})

    def _add_no_regression_gate(name: str, source_key: str) -> None:
        source_payload = source_comparison.get(source_key)
        if not isinstance(source_payload, dict):
            _add_gate(name, False, f"Missing source row for {source_key}.")
            return
        baseline_context = source_payload.get("baseline")
        candidate_context = source_payload.get("candidate")
        if not isinstance(baseline_context, dict) or not isinstance(candidate_context, dict):
            _add_gate(name, False, f"Missing baseline/candidate context for {source_key}.")
            return
        baseline_value = _report_optional_metric(baseline_context.get("practical_f1"))
        candidate_value = _report_optional_metric(candidate_context.get("practical_f1"))
        if baseline_value is None or candidate_value is None:
            _add_gate(
                name,
                False,
                f"Missing practical_f1 for baseline/candidate ({source_key}).",
            )
            return
        passed = candidate_value >= baseline_value
        _add_gate(
            name,
            passed,
            (
                f"candidate_practical_f1={candidate_value:.6f}, "
                f"baseline_practical_f1={baseline_value:.6f}"
            ),
        )

    _add_no_regression_gate("sea_no_regression", BENCHMARK_COMPARE_SEA_SOURCE_KEY)
    _add_no_regression_gate("foodlab_no_regression", BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY)

    foodlab_payload = source_comparison.get(BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY)
    if not isinstance(foodlab_payload, dict):
        _add_gate(
            "foodlab_ingredient_at_least_baseline",
            False,
            "Missing thefoodlabcutdown source row.",
        )
        _add_gate(
            "foodlab_variant_recall_nonzero",
            False,
            "Missing thefoodlabcutdown source row.",
        )
    else:
        baseline_context = foodlab_payload.get("baseline")
        candidate_context = foodlab_payload.get("candidate")
        baseline_ingredient = (
            _report_optional_metric(baseline_context.get("ingredient_recall"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_ingredient = (
            _report_optional_metric(candidate_context.get("ingredient_recall"))
            if isinstance(candidate_context, dict)
            else None
        )
        if baseline_ingredient is None or candidate_ingredient is None:
            _add_gate(
                "foodlab_ingredient_at_least_baseline",
                False,
                "Missing ingredient recall in baseline/candidate winner eval report.",
            )
        else:
            ingredient_passed = candidate_ingredient >= baseline_ingredient
            _add_gate(
                "foodlab_ingredient_at_least_baseline",
                ingredient_passed,
                (
                    f"candidate_ingredient_recall={candidate_ingredient:.6f}, "
                    f"baseline_ingredient_recall={baseline_ingredient:.6f}"
                ),
            )

        candidate_variant = (
            _report_optional_metric(candidate_context.get("variant_recall"))
            if isinstance(candidate_context, dict)
            else None
        )
        if candidate_variant is None:
            _add_gate(
                "foodlab_variant_recall_nonzero",
                False,
                "Missing candidate RECIPE_VARIANT recall.",
            )
        else:
            variant_passed = candidate_variant > 0.0
            _add_gate(
                "foodlab_variant_recall_nonzero",
                variant_passed,
                f"candidate_variant_recall={candidate_variant:.6f}",
            )

    for source_key, gate_name in (
        (BENCHMARK_COMPARE_SEA_SOURCE_KEY, "sea_debug_artifacts_present"),
        (BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY, "foodlab_debug_artifacts_present"),
    ):
        source_payload = source_comparison.get(source_key)
        if not isinstance(source_payload, dict):
            _add_gate(gate_name, False, f"Missing source row for {source_key}.")
            continue
        candidate_context = source_payload.get("candidate")
        if not isinstance(candidate_context, dict):
            _add_gate(gate_name, False, f"Missing candidate context for {source_key}.")
            continue
        debug_payload = candidate_context.get("debug_artifacts")
        if not isinstance(debug_payload, dict):
            _add_gate(gate_name, False, "Missing candidate debug artifact payload.")
            continue
        mode_source = str(candidate_context.get("codex_farm_mode_source") or "").strip()
        if not mode_source:
            mode_source = "unknown"
        requires_debug = bool(debug_payload.get("required"))
        if mode_source == "inferred" and requires_debug:
            _add_warning(
                (
                    f"Running benchmark-only debug checks for {source_key} using "
                    "inferred benchmark mode from artifacts (metadata missing)."
                )
            )
        elif mode_source == "unknown":
            _add_warning(
                (
                    f"Could not confirm benchmark mode for {source_key}: "
                    "mode metadata is missing and artifact signals are not conclusive."
                )
            )
            if requires_debug:
                _add_warning(
                    f"Skipping benchmark-only debug checks for {source_key}: "
                    "mode could not be determined from metadata or artifacts."
                )
                _add_gate(
                    gate_name,
                    True,
                    (
                        "Not required: "
                        f"mode={candidate_context.get('codex_farm_recipe_mode')}, "
                        f"llm_recipe_pipeline={candidate_context.get('llm_recipe_pipeline')}"
                    ),
                )
                continue
        elif mode_source != "metadata":
            _add_warning(f"Unrecognized mode_source for {source_key}: {mode_source}.")
            _add_gate(
                gate_name,
                False,
                f"Invalid mode source reported for benchmark comparison: {mode_source}.",
            )
            continue

        missing = debug_payload.get("missing")
        if not isinstance(missing, list):
            missing = []
        passed = bool(debug_payload.get("all_present"))
        _add_gate(
            gate_name,
            passed,
            (
                "Required debug artifacts present."
                if passed
                else "Missing required debug artifacts: "
                + ", ".join(str(name) for name in missing)
            ),
        )

    failed_gate_count = sum(1 for gate in gates if not bool(gate.get("passed")))
    passed_gate_count = len(gates) - failed_gate_count
    overall_verdict = "PASS" if failed_gate_count == 0 else "FAIL"

    return {
        "schema_version": LABELSTUDIO_BENCHMARK_COMPARE_SCHEMA_VERSION,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "baseline_report_root": str(baseline_report_root),
        "candidate_report_root": str(candidate_report_root),
        "overall": {
            "verdict": overall_verdict,
            "gate_count": len(gates),
            "passed_gate_count": passed_gate_count,
            "failed_gate_count": failed_gate_count,
        },
        "warnings": warnings,
        "gates": gates,
        "sources": source_comparison,
    }


def _build_labelstudio_benchmark_compare_single_eval_payload(
    *,
    baseline_eval_report_path: Path,
    candidate_eval_report_path: Path,
) -> dict[str, Any]:
    baseline_eval_report = _load_json_dict(baseline_eval_report_path)
    if baseline_eval_report is None:
        _fail(
            "Baseline eval report is missing or invalid: "
            f"{baseline_eval_report_path}"
        )
    candidate_eval_report = _load_json_dict(candidate_eval_report_path)
    if candidate_eval_report is None:
        _fail(
            "Candidate eval report is missing or invalid: "
            f"{candidate_eval_report_path}"
        )

    baseline_source_file = _infer_source_file_from_eval_report_and_manifest(
        eval_report=baseline_eval_report,
        eval_report_path=baseline_eval_report_path,
    )
    candidate_source_file = _infer_source_file_from_eval_report_and_manifest(
        eval_report=candidate_eval_report,
        eval_report_path=candidate_eval_report_path,
    )
    baseline_source_key = _source_key_from_source_path(baseline_source_file)
    candidate_source_key = _source_key_from_source_path(candidate_source_file)
    source_key = (
        baseline_source_key
        or candidate_source_key
        or slugify_name(candidate_eval_report_path.parent.name)
        or "single_source"
    )

    baseline_context = _build_labelstudio_benchmark_context_from_eval_report(
        source_key=source_key,
        source_file=baseline_source_file,
        winner_metrics=None,
        eval_report=baseline_eval_report,
        eval_report_path=baseline_eval_report_path,
    )
    candidate_context = _build_labelstudio_benchmark_context_from_eval_report(
        source_key=source_key,
        source_file=candidate_source_file,
        winner_metrics=None,
        eval_report=candidate_eval_report,
        eval_report_path=candidate_eval_report_path,
    )
    source_comparison: dict[str, dict[str, Any]] = {
        source_key: {
            "baseline": baseline_context,
            "candidate": candidate_context,
            "deltas": {
                "practical_f1": _metric_delta(
                    _report_optional_metric(candidate_context.get("practical_f1")),
                    _report_optional_metric(baseline_context.get("practical_f1")),
                ),
                "overall_line_accuracy": _metric_delta(
                    _report_optional_metric(candidate_context.get("overall_line_accuracy")),
                    _report_optional_metric(baseline_context.get("overall_line_accuracy")),
                ),
                "ingredient_recall": _metric_delta(
                    _report_optional_metric(candidate_context.get("ingredient_recall")),
                    _report_optional_metric(baseline_context.get("ingredient_recall")),
                ),
                "variant_recall": _metric_delta(
                    _report_optional_metric(candidate_context.get("variant_recall")),
                    _report_optional_metric(baseline_context.get("variant_recall")),
                ),
            },
        }
    }

    gates: list[dict[str, Any]] = []
    warnings: list[str] = []

    def _add_warning(message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        if text not in warnings:
            warnings.append(text)

    def _add_gate(name: str, passed: bool, reason: str) -> None:
        gates.append({"name": name, "passed": bool(passed), "reason": reason})

    def _add_no_regression_gate(
        *,
        name: str,
        metric_name: str,
        baseline_value: float | None,
        candidate_value: float | None,
    ) -> None:
        if baseline_value is None or candidate_value is None:
            _add_gate(
                name,
                False,
                f"Missing baseline/candidate {metric_name}.",
            )
            return
        _add_gate(
            name,
            candidate_value >= baseline_value,
            (
                f"candidate_{metric_name}={candidate_value:.6f}, "
                f"baseline_{metric_name}={baseline_value:.6f}"
            ),
        )

    if baseline_source_key and candidate_source_key and baseline_source_key != candidate_source_key:
        _add_gate(
            "source_key_match",
            False,
            (
                "Baseline/candidate source mismatch: "
                f"{baseline_source_key} vs {candidate_source_key}."
            ),
        )
    else:
        _add_gate(
            "source_key_match",
            True,
            (
                f"source_key={source_key}"
                if source_key
                else "Source key unavailable in eval metadata."
            ),
        )

    _add_no_regression_gate(
        name="practical_f1_no_regression",
        metric_name="practical_f1",
        baseline_value=_report_optional_metric(baseline_context.get("practical_f1")),
        candidate_value=_report_optional_metric(candidate_context.get("practical_f1")),
    )
    _add_no_regression_gate(
        name="overall_line_accuracy_no_regression",
        metric_name="overall_line_accuracy",
        baseline_value=_report_optional_metric(
            baseline_context.get("overall_line_accuracy")
        ),
        candidate_value=_report_optional_metric(
            candidate_context.get("overall_line_accuracy")
        ),
    )

    baseline_ingredient = _report_optional_metric(baseline_context.get("ingredient_recall"))
    candidate_ingredient = _report_optional_metric(candidate_context.get("ingredient_recall"))
    if baseline_ingredient is None or candidate_ingredient is None:
        _add_gate(
            "ingredient_recall_at_least_baseline",
            False,
            "Missing ingredient recall in baseline/candidate eval report.",
        )
    else:
        _add_gate(
            "ingredient_recall_at_least_baseline",
            candidate_ingredient >= baseline_ingredient,
            (
                f"candidate_ingredient_recall={candidate_ingredient:.6f}, "
                f"baseline_ingredient_recall={baseline_ingredient:.6f}"
            ),
        )

    candidate_variant = _report_optional_metric(candidate_context.get("variant_recall"))
    if candidate_variant is None:
        _add_gate(
            "variant_recall_nonzero",
            False,
            "Missing candidate RECIPE_VARIANT recall.",
        )
    else:
        _add_gate(
            "variant_recall_nonzero",
            candidate_variant > 0.0,
            f"candidate_variant_recall={candidate_variant:.6f}",
        )

    debug_payload = candidate_context.get("debug_artifacts")
    if not isinstance(debug_payload, dict):
        _add_gate(
            "debug_artifacts_present",
            False,
            "Missing candidate debug artifact payload.",
        )
    else:
        mode_source = str(candidate_context.get("codex_farm_mode_source") or "").strip()
        if not mode_source:
            mode_source = "unknown"
        requires_debug = bool(debug_payload.get("required"))
        skip_required_debug = False
        hard_failure_mode_source = False
        if mode_source == "inferred" and requires_debug:
            _add_warning(
                (
                    f"Running benchmark-only debug checks for {source_key} using "
                    "inferred benchmark mode from artifacts (metadata missing)."
                )
            )
        elif mode_source == "unknown":
            _add_warning(
                (
                    f"Could not confirm benchmark mode for {source_key}: "
                    "mode metadata is missing and artifact signals are not conclusive."
                )
            )
            if requires_debug:
                _add_warning(
                    f"Skipping benchmark-only debug checks for {source_key}: "
                    "mode could not be determined from metadata or artifacts."
                )
                skip_required_debug = True
        elif mode_source != "metadata":
            _add_warning(f"Unrecognized mode_source for {source_key}: {mode_source}.")
            _add_gate(
                "debug_artifacts_present",
                False,
                f"Invalid mode source reported for benchmark comparison: {mode_source}.",
            )
            hard_failure_mode_source = True

        if hard_failure_mode_source:
            pass
        elif skip_required_debug:
            _add_gate(
                "debug_artifacts_present",
                True,
                (
                    "Not required: "
                    f"mode={candidate_context.get('codex_farm_recipe_mode')}, "
                    f"llm_recipe_pipeline={candidate_context.get('llm_recipe_pipeline')}"
                ),
            )
        else:
            missing = debug_payload.get("missing")
            if not isinstance(missing, list):
                missing = []
            passed = bool(debug_payload.get("all_present"))
            _add_gate(
                "debug_artifacts_present",
                passed,
                (
                    "Required debug artifacts present."
                    if passed
                    else "Missing required debug artifacts: "
                    + ", ".join(str(name) for name in missing)
                ),
            )

    failed_gate_count = sum(1 for gate in gates if not bool(gate.get("passed")))
    passed_gate_count = len(gates) - failed_gate_count
    overall_verdict = "PASS" if failed_gate_count == 0 else "FAIL"

    return {
        "schema_version": LABELSTUDIO_BENCHMARK_COMPARE_SCHEMA_VERSION,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "comparison_mode": "single_eval_report",
        "baseline_report_root": str(baseline_eval_report_path.parent),
        "candidate_report_root": str(candidate_eval_report_path.parent),
        "baseline_eval_report_path": str(baseline_eval_report_path),
        "candidate_eval_report_path": str(candidate_eval_report_path),
        "overall": {
            "verdict": overall_verdict,
            "gate_count": len(gates),
            "passed_gate_count": passed_gate_count,
            "failed_gate_count": failed_gate_count,
        },
        "warnings": warnings,
        "gates": gates,
        "sources": source_comparison,
    }


def _format_labelstudio_benchmark_compare_markdown(
    payload: dict[str, Any],
) -> str:
    lines = [
        "# Labelstudio Benchmark Compare",
        "",
        f"- Schema version: {payload.get('schema_version', '')}",
        f"- Created at: {payload.get('created_at', '')}",
        f"- Baseline report root: {payload.get('baseline_report_root', '')}",
        f"- Candidate report root: {payload.get('candidate_report_root', '')}",
    ]
    overall = payload.get("overall")
    warnings = payload.get("warnings")
    if isinstance(overall, dict):
        lines.extend(
            [
                f"- Verdict: {overall.get('verdict', 'UNKNOWN')}",
                (
                    "- Gates passed/total/failed: "
                    f"{_report_count(overall.get('passed_gate_count'))}/"
                    f"{_report_count(overall.get('gate_count'))}"
                    f"/{_report_count(overall.get('failed_gate_count'))}"
                ),
            ]
        )
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {str(warning)}")
    lines.extend(
        [
            "",
            "## Gate Results",
            "",
            "| Gate | Status | Reason |",
            "| --- | --- | --- |",
        ]
    )
    gates = payload.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            gate_name = str(gate.get("name") or "").strip() or "<unknown>"
            status = "PASS" if bool(gate.get("passed")) else "FAIL"
            reason = str(gate.get("reason") or "").strip()
            lines.append(
                f"| `{gate_name}` | {status} | {reason.replace('|', '\\|')} |"
            )
    lines.extend(
        [
            "",
            "## Source Deltas",
            "",
            "| Source | Delta Practical F1 | Delta Line Accuracy | Delta Ingredient Recall | Delta Variant Recall |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    sources = payload.get("sources")
    if isinstance(sources, dict):
        for source_key in sorted(sources.keys()):
            source_payload = sources.get(source_key)
            if not isinstance(source_payload, dict):
                continue
            deltas = source_payload.get("deltas")
            if not isinstance(deltas, dict):
                deltas = {}
            practical_delta = _report_optional_metric(deltas.get("practical_f1"))
            line_delta = _report_optional_metric(deltas.get("overall_line_accuracy"))
            ingredient_delta = _report_optional_metric(deltas.get("ingredient_recall"))
            variant_delta = _report_optional_metric(deltas.get("variant_recall"))
            lines.append(
                "| "
                + source_key
                + " | "
                + (f"{practical_delta:.6f}" if practical_delta is not None else "null")
                + " | "
                + (f"{line_delta:.6f}" if line_delta is not None else "null")
                + " | "
                + (f"{ingredient_delta:.6f}" if ingredient_delta is not None else "null")
                + " | "
                + (f"{variant_delta:.6f}" if variant_delta is not None else "null")
            + " |"
        )

    lines.extend(
        [
            "",
            "## Source Debug Artifact Checks (candidate source only)",
            "",
        ]
    )
    sources = payload.get("sources")
    if isinstance(sources, dict):
        for source_key in sorted(sources.keys()):
            source_payload = sources.get(source_key)
            if not isinstance(source_payload, dict):
                continue
            candidate_payload = source_payload.get("candidate")
            if not isinstance(candidate_payload, dict):
                continue
            debug_payload = candidate_payload.get("debug_artifacts")
            if not isinstance(debug_payload, dict):
                continue
            checks = debug_payload.get("checks")
            if not isinstance(checks, list):
                continue
            lines.append(f"### {source_key}")
            lines.append("")
            lines.append("| Check | Required | Present | Path | Count |")
            lines.append("| --- | --- | --- | --- | --- |")
            for check in checks:
                if not isinstance(check, dict):
                    continue
                check_name = str(check.get("name") or "").strip() or "<unknown>"
                required = (
                    "YES"
                    if check_name in debug_payload.get("required_checks", [])
                    else "NO"
                )
                present = "yes" if bool(check.get("present")) else "no"
                count = str(check.get("count") if check.get("count") is not None else "")
                path = str(check.get("path") or "").strip().replace("|", "\\|")
                lines.append(
                    f"| `{check_name}` | {required} | {present} | {path} | {count} |"
                )
            lines.append("")

    return "\n".join(lines) + "\n"


def _format_labelstudio_benchmark_compare_gates_markdown(
    payload: dict[str, Any],
) -> str:
    lines = [
        "## Gate Results",
        "",
        "| Gate | Status | Reason |",
        "| --- | --- | --- |",
    ]
    gates = payload.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            gate_name = str(gate.get("name") or "").strip() or "<unknown>"
            status = "PASS" if bool(gate.get("passed")) else "FAIL"
            reason = str(gate.get("reason") or "").strip().replace("|", "\\|")
            lines.append(f"| `{gate_name}` | {status} | {reason} |")
    return "\n".join(lines) + "\n"


def labelstudio_benchmark_compare(
    *,
    baseline: Path,
    candidate: Path,
    out_dir: Path = DEFAULT_LABELSTUDIO_BENCHMARK_COMPARISONS,
    fail_on_regression: bool = False,
) -> dict[str, Any]:
    baseline_target = _resolve_labelstudio_benchmark_compare_input(baseline)
    if baseline_target is None:
        _fail(
            "Unable to resolve baseline compare input from: "
            f"{baseline}"
        )
    candidate_target = _resolve_labelstudio_benchmark_compare_input(candidate)
    if candidate_target is None:
        _fail(
            "Unable to resolve candidate compare input from: "
            f"{candidate}"
        )
    baseline_mode = str(baseline_target.get("mode") or "").strip()
    candidate_mode = str(candidate_target.get("mode") or "").strip()
    if baseline_mode != candidate_mode:
        _fail(
            "Compare input mode mismatch: baseline and candidate must both be all-method roots "
            "or both be single eval_report inputs."
        )

    if baseline_mode == "single_eval_report":
        baseline_eval_report_path = baseline_target.get("eval_report_path")
        candidate_eval_report_path = candidate_target.get("eval_report_path")
        if not isinstance(baseline_eval_report_path, Path) or not isinstance(
            candidate_eval_report_path, Path
        ):
            _fail("Compare single-eval mode resolution failed: eval_report paths missing.")
        comparison = _build_labelstudio_benchmark_compare_single_eval_payload(
            baseline_eval_report_path=baseline_eval_report_path,
            candidate_eval_report_path=candidate_eval_report_path,
        )
    else:
        baseline_root = baseline_target.get("report_root")
        candidate_root = candidate_target.get("report_root")
        if not isinstance(baseline_root, Path) or not isinstance(candidate_root, Path):
            _fail("Compare all-method mode resolution failed: report roots missing.")
        comparison = _build_labelstudio_benchmark_compare_payload(
            baseline_report_root=baseline_root,
            candidate_report_root=candidate_root,
        )
    comparison_root = out_dir / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    comparison_root.mkdir(parents=True, exist_ok=True)
    comparison_json_path = comparison_root / "comparison.json"
    comparison_md_path = comparison_root / "comparison.md"
    comparison_json_path.write_text(
        json.dumps(comparison, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    comparison_md_path.write_text(
        _format_labelstudio_benchmark_compare_markdown(comparison),
        encoding="utf-8",
    )
    verdict = str((comparison.get("overall") or {}).get("verdict") or "UNKNOWN").upper()
    typer.secho(
        f"Labelstudio benchmark compare verdict: {verdict}",
        fg=typer.colors.GREEN if verdict == "PASS" else typer.colors.YELLOW,
    )
    warnings = comparison.get("warnings")
    if isinstance(warnings, list) and warnings:
        typer.secho("Warnings:", fg=typer.colors.YELLOW)
        for warning in warnings:
            typer.secho(f"- {str(warning)}", fg=typer.colors.YELLOW)
    typer.echo(_format_labelstudio_benchmark_compare_gates_markdown(comparison).rstrip("\n"))
    typer.secho(f"Report: {comparison_md_path}", fg=typer.colors.CYAN)
    typer.secho(f"JSON: {comparison_json_path}", fg=typer.colors.CYAN)
    if fail_on_regression and verdict == "FAIL":
        raise typer.Exit(1)
    return comparison
