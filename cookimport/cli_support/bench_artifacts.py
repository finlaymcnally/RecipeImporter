from __future__ import annotations

import importlib
import sys

from .bench_all_method import _report_optional_metric
from .bench_single_book import (
    _extract_codex_farm_runtime_from_llm_manifest,
    _extract_codex_farm_token_usage_from_llm_manifest,
    _extract_line_role_token_usage_from_manifest,
    _resolve_single_book_reasoning_effort,
    _single_book_text_or_none,
    _sum_token_usage,
)
from .stage import _path_for_manifest, _write_eval_run_manifest

runtime = sys.modules["cookimport.cli_support.bench"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)


def _all_method_support_module():
    return importlib.import_module("cookimport.cli_support.bench_all_method")


def _benchmark_selective_retry_manifest_summary(run_config: dict[str, Any] | None):
    labelstudio_commands = importlib.import_module("cookimport.cli_commands.labelstudio")
    return getattr(
        labelstudio_commands,
        "_benchmark_selective_retry_manifest_summary",
    )(run_config)


def _normalize_timing_payload(payload: Any) -> dict[str, Any]:
    return _all_method_support_module()._normalize_timing_payload(payload)


def _timing_with_updates(*args, **kwargs):
    return _all_method_support_module()._timing_with_updates(*args, **kwargs)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PredRunContext:
    recipes: int | None
    processed_report_path: str
    semantic_row_predictions_path: str
    extracted_archive_path: str
    source_file: str
    source_hash: str | None
    run_config: dict[str, Any] | None
    run_config_hash: str | None
    run_config_summary: str | None
    tokens_input: int | None
    tokens_cached_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_total: int | None


@dataclass(frozen=True)
class BenchmarkPredictionBundle:
    import_result: dict[str, Any]
    pred_run: Path
    pred_context: PredRunContext
    stage_predictions_path: Path
    extracted_archive_path: Path
    prediction_phase_seconds: float


@dataclass(frozen=True)
class BenchmarkPredictionStageResult:
    prediction_bundle: BenchmarkPredictionBundle
    prediction_records: list[PredictionRecord]
    codex_exec_prompt_response_log_path: Path | None
    single_book_split_cache_metadata: dict[str, Any] | None


def _load_pred_run_recipe_context(
    pred_run: Path,
) -> PredRunContext:
    """Return recipe/report/source/run-config context for a prediction run."""
    manifest_path = pred_run / "manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            semantic_row_predictions_path="",
            extracted_archive_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            tokens_input=None,
            tokens_cached_input=None,
            tokens_output=None,
            tokens_reasoning=None,
            tokens_total=None,
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            semantic_row_predictions_path="",
            extracted_archive_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            tokens_input=None,
            tokens_cached_input=None,
            tokens_output=None,
            tokens_reasoning=None,
            tokens_total=None,
        )
    if not isinstance(payload, dict):
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            semantic_row_predictions_path="",
            extracted_archive_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            tokens_input=None,
            tokens_cached_input=None,
            tokens_output=None,
            tokens_reasoning=None,
            tokens_total=None,
        )

    source_file = str(payload.get("source_file") or "")
    source_hash = str(payload.get("source_hash") or "").strip() or None
    processed_report_path = str(payload.get("processed_report_path") or "")
    semantic_row_predictions_path = str(payload.get("semantic_row_predictions_path") or "")
    extracted_archive_path = str(payload.get("extracted_archive_path") or "")
    run_config = payload.get("run_config")
    if not isinstance(run_config, dict):
        run_config = None
    run_config_hash = str(payload.get("run_config_hash") or "").strip() or None
    run_config_summary = str(payload.get("run_config_summary") or "").strip() or None
    llm_codex_farm_payload = payload.get("llm_codex_farm")
    tokens_input = None
    tokens_cached_input = None
    tokens_output = None
    tokens_reasoning = None
    tokens_total = None
    codex_farm_tokens = (None, None, None, None, None)
    if isinstance(llm_codex_farm_payload, dict):
        codex_farm_tokens = _extract_codex_farm_token_usage_from_llm_manifest(
            llm_codex_farm_payload
        )
    line_role_tokens = _extract_line_role_token_usage_from_manifest(payload)
    (
        tokens_input,
        tokens_cached_input,
        tokens_output,
        tokens_reasoning,
        tokens_total,
    ) = _sum_token_usage(codex_farm_tokens, line_role_tokens)
    if isinstance(run_config, dict) and isinstance(llm_codex_farm_payload, dict):
        merged_run_config = dict(run_config)
        run_config_updated = False
        codex_cmd = _single_book_text_or_none(merged_run_config.get("codex_farm_cmd"))
        existing_model = _single_book_text_or_none(
            merged_run_config.get("codex_farm_model")
        ) or _single_book_text_or_none(merged_run_config.get("codex_model"))
        inferred_model, inferred_reasoning_effort = _extract_codex_farm_runtime_from_llm_manifest(
            llm_codex_farm_payload
        )
        resolved_model = existing_model or _single_book_text_or_none(inferred_model)
        if resolved_model is not None and not _single_book_text_or_none(
            merged_run_config.get("codex_farm_model")
        ):
            merged_run_config["codex_farm_model"] = resolved_model
            run_config_updated = True

        resolved_reasoning_effort = _resolve_single_book_reasoning_effort(
            merged_run_config.get("codex_farm_reasoning_effort")
            or merged_run_config.get("codex_reasoning_effort"),
            codex_cmd=codex_cmd,
            codex_model=resolved_model,
        )
        if resolved_reasoning_effort is None:
            resolved_reasoning_effort = _resolve_single_book_reasoning_effort(
                inferred_reasoning_effort,
                codex_cmd=codex_cmd,
                codex_model=resolved_model,
            )
        if (
            resolved_reasoning_effort is not None
            and _single_book_text_or_none(
                merged_run_config.get("codex_farm_reasoning_effort")
            )
            != resolved_reasoning_effort
        ):
            merged_run_config["codex_farm_reasoning_effort"] = resolved_reasoning_effort
            run_config_updated = True

        if run_config_updated:
            run_config = merged_run_config
            # Recompute against enriched payload when benchmark CSV append persists this context.
            run_config_hash = None
            run_config_summary = None

    recipes: int | None
    try:
        recipes = int(payload.get("recipe_count"))
    except (TypeError, ValueError):
        recipes = None

    if recipes is None and processed_report_path:
        recipes = _load_total_recipes_from_report_path(processed_report_path)

    return PredRunContext(
        recipes=recipes,
        processed_report_path=processed_report_path,
        semantic_row_predictions_path=semantic_row_predictions_path,
        extracted_archive_path=extracted_archive_path,
        source_file=source_file,
        source_hash=source_hash,
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        tokens_input=tokens_input,
        tokens_cached_input=tokens_cached_input,
        tokens_output=tokens_output,
        tokens_reasoning=tokens_reasoning,
        tokens_total=tokens_total,
    )


def _resolve_stage_predictions_for_benchmark(
    *,
    import_result: dict[str, Any],
    pred_context: PredRunContext,
    pred_run: Path,
) -> Path:
    stage_predictions_candidates: list[Path] = []
    for value in (
        import_result.get("semantic_row_predictions_path"),
        pred_context.semantic_row_predictions_path,
    ):
        if not value:
            continue
        stage_predictions_candidates.append(Path(str(value)))

    for candidate in stage_predictions_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    _fail(
        "This prediction run is missing canonical semantic row predictions "
        "(semantic_row_predictions_path). Re-run benchmark after updating."
    )
    return pred_run / "semantic_row_predictions.json"


def _resolve_extracted_archive_for_benchmark(
    *,
    import_result: dict[str, Any],
    pred_context: PredRunContext,
    pred_run: Path,
) -> Path:
    archive_candidates: list[Path] = []
    for value in (
        import_result.get("extracted_archive_path"),
        pred_context.extracted_archive_path,
    ):
        if not value:
            continue
        archive_candidates.append(Path(str(value)))

    for candidate in archive_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    _fail(
        "This prediction run is missing canonical extracted archive evidence "
        "(extracted_archive_path). Re-run benchmark after updating."
    )
    return pred_run / "extracted_archive.json"


def _resolve_line_role_predictions_for_benchmark(
    *,
    import_result: dict[str, Any],
    pred_run: Path,
) -> Path | None:
    candidates: list[Path] = []
    for value in (
        import_result.get("line_role_pipeline_semantic_predictions_path"),
        import_result.get("line_role_pipeline_line_role_predictions_path"),
        pred_run / "line-role-pipeline" / "semantic_line_role_predictions.jsonl",
        pred_run / "line-role-pipeline" / "line_role_predictions.jsonl",
    ):
        if not value:
            continue
        candidates.append(Path(str(value)))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


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


def _load_jsonl_dict_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _build_prediction_bundle_from_import_result(
    *,
    import_result: dict[str, Any],
    prediction_phase_seconds: float,
) -> BenchmarkPredictionBundle:
    pred_run = Path(import_result["run_root"]).expanduser()
    if not pred_run.exists() or not pred_run.is_dir():
        _fail(f"Prediction artifact directory not found: {pred_run}")
    pred_context = _load_pred_run_recipe_context(pred_run)
    default_stage_predictions_path = _resolve_stage_predictions_for_benchmark(
        import_result=import_result,
        pred_context=pred_context,
        pred_run=pred_run,
    )
    default_extracted_archive_path = _resolve_extracted_archive_for_benchmark(
        import_result=import_result,
        pred_context=pred_context,
        pred_run=pred_run,
    )
    return BenchmarkPredictionBundle(
        import_result=import_result,
        pred_run=pred_run,
        pred_context=pred_context,
        stage_predictions_path=default_stage_predictions_path,
        extracted_archive_path=default_extracted_archive_path,
        prediction_phase_seconds=max(0.0, prediction_phase_seconds),
    )


def _run_offline_benchmark_prediction_stage(
    *,
    prediction_generation_kwargs: dict[str, Any],
    eval_output_dir: Path,
    predictions_out_path: Path | None,
    suppress_spinner: bool = True,
    external_progress_callback: Callable[[str], None] | None = None,
) -> BenchmarkPredictionStageResult:
    prediction_generation_kwargs = dict(prediction_generation_kwargs)
    prediction_generation_kwargs.setdefault("run_root_override", eval_output_dir)
    prediction_generation_kwargs.setdefault("mirror_stage_artifacts_into_run_root", False)
    selected_source = Path(prediction_generation_kwargs["path"]).expanduser()
    selected_epub_extractor = str(
        prediction_generation_kwargs.get("epub_extractor") or "unstructured"
    ).strip().lower() or "unstructured"
    selected_html_parser_version = str(
        prediction_generation_kwargs.get(
            "epub_unstructured_html_parser_version"
        )
        or "v1"
    ).strip().lower() or "v1"
    selected_skip_headers_footers = bool(
        prediction_generation_kwargs.get("epub_unstructured_skip_headers_footers", True)
    )
    selected_preprocess_mode = str(
        prediction_generation_kwargs.get("epub_unstructured_preprocess_mode")
        or "br_split_v1"
    ).strip().lower() or "br_split_v1"
    write_markdown = bool(prediction_generation_kwargs.get("write_markdown"))
    write_label_studio_tasks = bool(
        prediction_generation_kwargs.get("write_label_studio_tasks")
    )
    should_upload_predictions = False
    line_role_pipeline = str(
        prediction_generation_kwargs.get("line_role_pipeline") or "off"
    ).strip().lower()

    with _temporary_epub_extractor(selected_epub_extractor):
        with _temporary_epub_unstructured_options(
            html_parser_version=selected_html_parser_version,
            skip_headers_footers=selected_skip_headers_footers,
            preprocess_mode=selected_preprocess_mode,
        ):
            prediction_phase_started = time.monotonic()
            if suppress_spinner:
                if external_progress_callback is not None:
                    external_progress_callback(
                        f"Generating prediction tasks for {selected_source.name}..."
                    )
                import_result = generate_pred_run_artifacts(**prediction_generation_kwargs)
            else:
                def _run_with_status(
                    update_progress: Callable[[str], None],
                ) -> dict[str, Any]:
                    if external_progress_callback is None:
                        return generate_pred_run_artifacts(**prediction_generation_kwargs)

                    def _combined_progress(message: str) -> None:
                        update_progress(message)
                        external_progress_callback(message)

                    generation_kwargs = dict(prediction_generation_kwargs)
                    generation_kwargs["progress_callback"] = _combined_progress
                    return generate_pred_run_artifacts(**generation_kwargs)

                import_result = _run_with_progress_status(
                    initial_status=(
                        f"Generating prediction tasks for {selected_source.name}..."
                    ),
                    progress_prefix=f"Benchmark import ({selected_source.name})",
                    run=_run_with_status,
                    telemetry_path=(
                        eval_output_dir / "processing_timeseries_prediction.jsonl"
                    ),
                )
            prediction_phase_seconds = max(
                0.0, time.monotonic() - prediction_phase_started
            )

    prediction_bundle = _build_prediction_bundle_from_import_result(
        import_result=import_result,
        prediction_phase_seconds=prediction_phase_seconds,
    )
    prediction_records = list(
        predict_stage(
            bundle=prediction_bundle,
            selected_source=selected_source,
        )
    )
    if predictions_out_path is not None:
        write_prediction_records(predictions_out_path, prediction_records)

    pred_run = prediction_bundle.pred_run
    pred_context = prediction_bundle.pred_context
    prediction_timing = _normalize_timing_payload(import_result.get("timing"))
    prediction_seconds = _report_optional_metric(
        prediction_timing.get("prediction_seconds")
    )
    if prediction_seconds is None:
        prediction_seconds = _report_optional_metric(
            prediction_timing.get("total_seconds")
        )
    if prediction_seconds is None:
        prediction_seconds = prediction_phase_seconds
    prediction_seconds = max(0.0, float(prediction_seconds))
    benchmark_timing = _timing_with_updates(
        prediction_timing,
        prediction_seconds=prediction_seconds,
        evaluation_seconds=0.0,
        total_seconds=max(
            prediction_seconds,
            max(0.0, time.monotonic() - prediction_phase_started),
        ),
    )

    prediction_stage_run_config: dict[str, Any] = {
        "prediction_record_output": (
            str(predictions_out_path) if predictions_out_path is not None else None
        ),
        "upload": should_upload_predictions,
        "write_markdown": write_markdown,
        "write_label_studio_tasks": write_label_studio_tasks,
    }
    single_book_split_cache_metadata = import_result.get(
        "single_book_split_cache"
    )
    if isinstance(single_book_split_cache_metadata, dict):
        prediction_stage_run_config["single_book_split_cache"] = dict(
            single_book_split_cache_metadata
        )
    if pred_context.run_config is not None:
        prediction_stage_run_config["prediction_run_config"] = pred_context.run_config
        prediction_stage_run_config.update(
            _benchmark_selective_retry_manifest_summary(pred_context.run_config)
        )
    if pred_context.run_config_hash:
        prediction_stage_run_config["prediction_run_config_hash"] = (
            pred_context.run_config_hash
        )
    if pred_context.run_config_summary:
        prediction_stage_run_config["prediction_run_config_summary"] = (
            pred_context.run_config_summary
        )

    prediction_stage_artifacts: dict[str, Any] = {
        "artifact_root_dir": _path_for_manifest(eval_output_dir, pred_run),
        "semantic_row_predictions_json": _path_for_manifest(
            eval_output_dir,
            prediction_bundle.stage_predictions_path,
        ),
        "extracted_archive_json": _path_for_manifest(
            eval_output_dir,
            prediction_bundle.extracted_archive_path,
        ),
        "timing": benchmark_timing,
    }
    prediction_timeseries_path = eval_output_dir / "processing_timeseries_prediction.jsonl"
    if prediction_timeseries_path.exists():
        prediction_stage_artifacts["processing_timeseries_prediction_jsonl"] = (
            _path_for_manifest(eval_output_dir, prediction_timeseries_path)
        )
    if predictions_out_path is not None:
        prediction_stage_artifacts["prediction_record_output_jsonl"] = _path_for_manifest(
            eval_output_dir,
            predictions_out_path,
        )
    processed_report_path = import_result.get("processed_report_path")
    if processed_report_path:
        prediction_stage_artifacts["processed_report_json"] = _path_for_manifest(
            eval_output_dir,
            processed_report_path,
        )
    processed_run_root_raw = import_result.get("processed_run_root")
    processed_run_root = (
        Path(str(processed_run_root_raw)).expanduser()
        if str(processed_run_root_raw or "").strip()
        else None
    )
    if processed_run_root is not None:
        prediction_stage_artifacts["processed_output_run_dir"] = _path_for_manifest(
            eval_output_dir,
            processed_run_root,
        )
        prediction_stage_artifacts["stage_run_dir"] = _path_for_manifest(
            eval_output_dir,
            processed_run_root,
        )

    _write_eval_run_manifest(
        run_root=eval_output_dir,
        run_kind="labelstudio_benchmark_prediction_stage",
        source_path=str(selected_source),
        source_hash=pred_context.source_hash,
        importer_name=None,
        run_config=prediction_stage_run_config,
        artifacts=prediction_stage_artifacts,
        notes=(
            "Offline benchmark prediction-stage artifacts for all-method reuse. "
            "No evaluation was run by this helper."
        ),
    )
    codex_exec_prompt_response_log_path = (
        llm_prompt_artifacts.build_codex_farm_prompt_response_log(
            pred_run=pred_run,
            eval_output_dir=eval_output_dir,
            repo_root=REPO_ROOT,
        )
    )
    return BenchmarkPredictionStageResult(
        prediction_bundle=prediction_bundle,
        prediction_records=prediction_records,
        codex_exec_prompt_response_log_path=codex_exec_prompt_response_log_path,
        single_book_split_cache_metadata=(
            dict(single_book_split_cache_metadata)
            if isinstance(single_book_split_cache_metadata, dict)
            else None
        ),
    )


_BENCHMARK_PREDICTION_RECORD_STAGE_KIND = "semantic-row.v1"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _prediction_record_meta_from_bundle(
    *,
    bundle: BenchmarkPredictionBundle,
    selected_source: Path,
    workbook_slug: str | None,
) -> dict[str, Any]:
    timing_payload = bundle.import_result.get("timing")
    if not isinstance(timing_payload, dict):
        timing_payload = {}
    predict_meta: dict[str, Any] = {
        "source_file": str(selected_source),
        "source_hash": bundle.pred_context.source_hash,
        "processed_run_root": _json_safe(bundle.import_result.get("processed_run_root")),
        "processed_report_path": _json_safe(
            bundle.import_result.get("processed_report_path")
        ),
        "run_config": _json_safe(bundle.pred_context.run_config),
        "run_config_hash": bundle.pred_context.run_config_hash,
        "run_config_summary": bundle.pred_context.run_config_summary,
        "recipes": bundle.pred_context.recipes,
        "timing": _json_safe(timing_payload),
        "workbook_slug": str(workbook_slug or "").strip() or None,
    }
    # Keep JSON payload compact and stable by dropping null-valued metadata keys.
    return {
        key: value for key, value in predict_meta.items() if value is not None
    }


def _load_stage_block_prediction_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to read semantic row predictions from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Stage block predictions payload at {path} is not a JSON object.")
    return payload


def _load_extracted_archive_blocks(path: Path) -> dict[int, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to read extracted archive from {path}: {exc}") from exc

    records: list[dict[str, Any]]
    if isinstance(payload, list):
        records = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        blocks_payload = payload.get("blocks")
        if isinstance(blocks_payload, list):
            records = [row for row in blocks_payload if isinstance(row, dict)]
        else:
            records = []
    else:
        records = []

    indexed: dict[int, dict[str, Any]] = {}
    for fallback_index, row in enumerate(records):
        raw_index = row.get("index")
        block_index = _coerce_int(raw_index)
        if block_index is None:
            block_index = _coerce_int(row.get("block_index"))
        if block_index is None:
            block_index = fallback_index
        location = row.get("location")
        if not isinstance(location, dict):
            location = {}
        features = location.get("features")
        if not isinstance(features, dict):
            features = {}
        indexed[int(block_index)] = {
            "text": str(row.get("text") or ""),
            "features": dict(features),
        }
    return indexed


def predict_stage(
    *,
    bundle: BenchmarkPredictionBundle,
    selected_source: Path,
) -> Iterator[PredictionRecord]:
    stage_payload = _load_stage_block_prediction_payload(bundle.stage_predictions_path)
    raw_row_labels = stage_payload.get("row_labels")
    if not isinstance(raw_row_labels, dict):
        raise ValueError(
            "Semantic row predictions payload is missing row_labels map."
        )
    row_labels: dict[int, str] = {}
    for raw_index, raw_label in raw_row_labels.items():
        row_index = _coerce_int(raw_index)
        if row_index is None or row_index < 0:
            continue
        normalized_label = str(raw_label or "").strip() or "OTHER"
        row_labels[row_index] = normalized_label

    extracted_blocks = _load_extracted_archive_blocks(bundle.extracted_archive_path)
    all_indices = sorted(set(row_labels) | set(extracted_blocks))
    source_identifier = bundle.pred_context.source_hash or str(selected_source)
    workbook_slug = str(stage_payload.get("workbook_slug") or "").strip()
    predict_meta = _prediction_record_meta_from_bundle(
        bundle=bundle,
        selected_source=selected_source,
        workbook_slug=workbook_slug,
    )
    for row_index in all_indices:
        block_payload = extracted_blocks.get(row_index, {})
        prediction_payload: dict[str, Any] = {
            "schema_kind": _BENCHMARK_PREDICTION_RECORD_STAGE_KIND,
            "row_index": int(row_index),
            "pred_label": row_labels.get(row_index, "OTHER"),
            "row_text": str(block_payload.get("text") or ""),
            "row_features": dict(block_payload.get("features") or {}),
        }
        yield make_prediction_record(
            example_id=f"labelstudio-benchmark:{source_identifier}:row:{row_index}",
            example_index=int(row_index),
            prediction=prediction_payload,
            predict_meta=predict_meta,
        )


def _prediction_record_stage_row(
    record: PredictionRecord,
) -> tuple[int, str, str, dict[str, Any]] | None:
    schema_kind = str(record.prediction.get("schema_kind") or "").strip()
    if schema_kind and schema_kind != _BENCHMARK_PREDICTION_RECORD_STAGE_KIND:
        return None
    if "row_index" not in record.prediction and "block_index" not in record.prediction:
        return None

    row_index = _coerce_int(
        record.prediction.get("row_index", record.prediction.get("block_index"))
    )
    if row_index is None or row_index < 0:
        raise ValueError(
            f"Prediction record {record.example_id} has invalid row_index."
        )
    pred_label = str(record.prediction.get("pred_label") or "").strip() or "OTHER"
    row_text = str(
        record.prediction.get("row_text", record.prediction.get("block_text")) or ""
    )
    row_features_payload = record.prediction.get(
        "row_features", record.prediction.get("block_features")
    )
    if not isinstance(row_features_payload, dict):
        row_features_payload = {}
    return row_index, pred_label, row_text, dict(row_features_payload)


def _build_prediction_bundle_from_stage_records(
    *,
    prediction_records: list[PredictionRecord],
    replay_output_dir: Path,
    require_contiguous: bool = True,
) -> BenchmarkPredictionBundle:
    if not prediction_records:
        raise ValueError("Prediction record file is empty.")

    seen_example_ids: set[str] = set()
    seen_example_indices: set[int] = set()
    block_rows: dict[int, dict[str, Any]] = {}
    first_meta: dict[str, Any] = {}
    for record in prediction_records:
        if record.example_id in seen_example_ids:
            raise ValueError(
                f"Prediction record file contains duplicate example_id: {record.example_id}"
            )
        if record.example_index in seen_example_indices:
            raise ValueError(
                "Prediction record file contains duplicate example_index: "
                f"{record.example_index}"
            )
        seen_example_ids.add(record.example_id)
        seen_example_indices.add(record.example_index)
        stage_row = _prediction_record_stage_row(record)
        if stage_row is None:
            raise ValueError(
                "Prediction record file contains unsupported record payload. "
                "Expected per-row semantic records."
            )
        row_index, pred_label, row_text, row_features = stage_row
        if int(record.example_index) != int(row_index):
            raise ValueError(
                "Prediction record example_index does not match row_index for "
                f"{record.example_id}."
            )
        if row_index in block_rows:
            raise ValueError(
                f"Prediction record file contains duplicate row_index: {row_index}"
            )
        block_rows[row_index] = {
            "pred_label": pred_label,
            "row_text": row_text,
            "row_features": row_features,
        }
        if not first_meta:
            first_meta = dict(record.predict_meta)

    if not block_rows:
        raise ValueError("Prediction record file contains no semantic-row records.")

    ordered_indices = sorted(block_rows)
    expected_indices = list(ordered_indices)
    if require_contiguous:
        max_row_index = ordered_indices[-1]
        expected_indices = list(range(max_row_index + 1))
        missing_indices = [
            row_index for row_index in expected_indices if row_index not in block_rows
        ]
        if missing_indices:
            missing_preview = ",".join(str(value) for value in missing_indices[:10])
            raise ValueError(
                "Prediction record row indices are not contiguous from 0. "
                f"Missing: {missing_preview}"
            )

    source_file = str(first_meta.get("source_file") or "")
    source_hash = str(first_meta.get("source_hash") or "").strip() or "unknown"
    workbook_slug = str(first_meta.get("workbook_slug") or "").strip()
    label_rows: dict[str, list[int]] = {}
    stage_labels: dict[str, str] = {}
    extracted_rows: list[dict[str, Any]] = []
    for row_index in expected_indices:
        row = block_rows[row_index]
        pred_label = str(row.get("pred_label") or "OTHER").strip() or "OTHER"
        stage_labels[str(row_index)] = pred_label
        label_rows.setdefault(pred_label, []).append(row_index)
        extracted_rows.append(
            {
                "index": row_index,
                "text": str(row.get("row_text") or ""),
                "location": {
                    "features": dict(row.get("row_features") or {}),
                },
            }
        )

    replay_output_dir.mkdir(parents=True, exist_ok=True)
    stage_predictions_path = replay_output_dir / "semantic_row_predictions.from_records.json"
    extracted_archive_path = replay_output_dir / "extracted_archive.from_records.json"
    stage_payload: dict[str, Any] = {
        "schema_version": "semantic_row_predictions.v1",
        "source_file": source_file,
        "source_hash": source_hash,
        "workbook_slug": workbook_slug,
        "row_count": len(expected_indices),
        "row_labels": stage_labels,
        "label_rows": label_rows,
        "conflicts": [],
        "notes": ["Reconstructed from per-example prediction records."],
    }
    stage_predictions_path.write_text(
        json.dumps(stage_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    extracted_archive_path.write_text(
        json.dumps(extracted_rows, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    pred_run = replay_output_dir
    run_config_payload = first_meta.get("run_config")
    run_config = run_config_payload if isinstance(run_config_payload, dict) else None
    timing_payload = first_meta.get("timing")
    if not isinstance(timing_payload, dict):
        timing_payload = {}
    import_result: dict[str, Any] = {
        "run_root": str(pred_run),
        "semantic_row_predictions_path": str(stage_predictions_path),
        "processed_report_path": str(first_meta.get("processed_report_path") or ""),
        "processed_run_root": str(first_meta.get("processed_run_root") or ""),
        "timing": timing_payload,
    }
    prediction_phase_seconds = _report_optional_metric(
        import_result["timing"].get("prediction_seconds")
    )
    if prediction_phase_seconds is None:
        prediction_phase_seconds = _report_optional_metric(
            import_result["timing"].get("total_seconds")
        )
    if prediction_phase_seconds is None:
        prediction_phase_seconds = 0.0

    pred_context = PredRunContext(
        recipes=_coerce_int(first_meta.get("recipes")),
        processed_report_path=str(first_meta.get("processed_report_path") or ""),
        semantic_row_predictions_path=str(stage_predictions_path),
        extracted_archive_path=str(extracted_archive_path),
        source_file=source_file,
        source_hash=source_hash if source_hash != "unknown" else None,
        run_config=run_config,
        run_config_hash=str(first_meta.get("run_config_hash") or "").strip() or None,
        run_config_summary=str(first_meta.get("run_config_summary") or "").strip() or None,
        tokens_input=None,
        tokens_cached_input=None,
        tokens_output=None,
        tokens_reasoning=None,
        tokens_total=None,
    )
    return BenchmarkPredictionBundle(
        import_result=import_result,
        pred_run=pred_run,
        pred_context=pred_context,
        stage_predictions_path=stage_predictions_path,
        extracted_archive_path=extracted_archive_path,
        prediction_phase_seconds=max(0.0, prediction_phase_seconds),
    )


def _build_prediction_bundle_from_records(
    *,
    predictions_in: Path,
    prediction_records: list[PredictionRecord],
    replay_output_dir: Path,
) -> BenchmarkPredictionBundle:
    if not prediction_records:
        raise ValueError(f"Prediction record file is empty: {predictions_in}")

    stage_record_candidates: list[PredictionRecord] = []
    for record in prediction_records:
        stage_row = _prediction_record_stage_row(record)
        if stage_row is not None:
            stage_record_candidates.append(record)

    if len(stage_record_candidates) != len(prediction_records):
        raise ValueError(
            "Prediction record file contains unsupported payload(s). "
            "Only per-row semantic records are accepted."
        )
    return _build_prediction_bundle_from_stage_records(
        prediction_records=stage_record_candidates,
        replay_output_dir=replay_output_dir,
    )


def _prediction_record_source_file_hint(
    records: list[PredictionRecord],
) -> Path | None:
    for record in records:
        source_hint = str(record.predict_meta.get("source_file") or "").strip()
        if not source_hint:
            continue
        source_candidate = Path(source_hint)
        if source_candidate.exists() and source_candidate.is_file():
            return source_candidate
    return None


@dataclass(frozen=True)
class PipelinedPredictionResult:
    prediction_bundle: BenchmarkPredictionBundle
    prediction_records: list[PredictionRecord]
    prewarmed_canonical_paths: dict[str, Path] | None
    replay_bundle: BenchmarkPredictionBundle | None


def run_pipelined(
    *,
    run_prediction_bundle: Callable[[], BenchmarkPredictionBundle],
    prewarm_evaluation_inputs: Callable[[], dict[str, Path] | None],
    selected_source: Path,
    eval_output_dir: Path,
    queue_size: int = 64,
) -> PipelinedPredictionResult:
    record_queue: queue.Queue[PredictionRecord | object] = queue.Queue(
        maxsize=max(1, int(queue_size))
    )
    prediction_bundle_queue: queue.Queue[BenchmarkPredictionBundle] = queue.Queue(
        maxsize=1
    )
    prewarm_queue: queue.Queue[dict[str, Path] | None] = queue.Queue(maxsize=1)
    consumer_queue: queue.Queue[
        tuple[list[PredictionRecord], BenchmarkPredictionBundle | None]
    ] = queue.Queue(maxsize=1)
    error_queue: queue.Queue[BaseException] = queue.Queue(maxsize=1)
    producer_done = threading.Event()
    stop_event = threading.Event()
    end_of_stream = object()

    def _publish_error(exc: BaseException) -> None:
        if error_queue.empty():
            error_queue.put(exc)
        stop_event.set()

    def _queue_put(target_queue: queue.Queue[Any], payload: Any) -> bool:
        while True:
            if stop_event.is_set():
                return False
            try:
                target_queue.put(payload, timeout=0.1)
                return True
            except queue.Full:
                continue

    def _producer() -> None:
        try:
            prediction_bundle = run_prediction_bundle()
            if not _queue_put(prediction_bundle_queue, prediction_bundle):
                return
            for record in predict_stage(
                bundle=prediction_bundle,
                selected_source=selected_source,
            ):
                if not _queue_put(record_queue, record):
                    return
        except BaseException as exc:  # noqa: BLE001
            _publish_error(exc)
        finally:
            producer_done.set()
            _queue_put(record_queue, end_of_stream)

    def _prewarm() -> None:
        try:
            prewarmed_canonical_paths = prewarm_evaluation_inputs()
            _queue_put(prewarm_queue, prewarmed_canonical_paths)
        except BaseException as exc:  # noqa: BLE001
            _publish_error(exc)

    def _consumer() -> None:
        try:
            prediction_records: list[PredictionRecord] = []
            reached_end_of_stream = False
            while not reached_end_of_stream:
                if stop_event.is_set() and producer_done.is_set() and record_queue.empty():
                    break
                try:
                    next_item = record_queue.get(timeout=0.1)
                except queue.Empty:
                    if producer_done.is_set():
                        break
                    continue
                if next_item is end_of_stream:
                    reached_end_of_stream = True
                    continue
                if not isinstance(next_item, PredictionRecord):
                    raise RuntimeError(
                        "Benchmark prediction pipeline produced an invalid record."
                    )
                if _prediction_record_stage_row(next_item) is None:
                    raise ValueError(
                        "Pipelined benchmark received unsupported prediction record payload."
                    )
                prediction_records.append(next_item)

            replay_bundle: BenchmarkPredictionBundle | None = None
            if prediction_records:
                replay_bundle = _build_prediction_bundle_from_stage_records(
                    prediction_records=prediction_records,
                    replay_output_dir=(
                        eval_output_dir / ".prediction-record-replay" / "pipelined"
                    ),
                    require_contiguous=False,
                )
            _queue_put(consumer_queue, (prediction_records, replay_bundle))
        except BaseException as exc:  # noqa: BLE001
            _publish_error(exc)

    producer_thread = threading.Thread(
        target=_producer,
        name="benchmark-prediction-stage",
        daemon=True,
    )
    prewarm_thread = threading.Thread(
        target=_prewarm,
        name="benchmark-eval-prewarm",
        daemon=True,
    )
    consumer_thread = threading.Thread(
        target=_consumer,
        name="benchmark-eval-consumer",
        daemon=True,
    )

    producer_thread.start()
    consumer_thread.start()
    prewarm_thread.start()
    producer_thread.join()
    consumer_thread.join()
    prewarm_thread.join()

    if not error_queue.empty():
        raise error_queue.get()
    if prediction_bundle_queue.empty():
        raise RuntimeError(
            "Pipelined benchmark prediction stage produced no output."
        )
    if prewarm_queue.empty():
        raise RuntimeError("Pipelined benchmark prewarm stage produced no output.")
    if consumer_queue.empty():
        raise RuntimeError(
            "Pipelined benchmark evaluation consumer produced no output."
        )
    prediction_bundle = prediction_bundle_queue.get()
    prewarmed_canonical_paths = prewarm_queue.get()
    prediction_records, replay_bundle = consumer_queue.get()
    return PipelinedPredictionResult(
        prediction_bundle=prediction_bundle,
        prediction_records=prediction_records,
        prewarmed_canonical_paths=prewarmed_canonical_paths,
        replay_bundle=replay_bundle,
    )


def evaluate_stage(
    *,
    selected_eval_mode: str,
    selected_gold: Path,
    eval_output_dir: Path,
    stage_predictions_path: Path,
    extracted_archive_path: Path,
    alignment_cache_dir: Path | None,
    prewarmed_canonical_paths: dict[str, Path] | None,
    gold_adaptation_mode: str,
    gold_adaptation_min_coverage: float,
    gold_adaptation_max_ambiguous: int,
) -> tuple[dict[str, Any], Callable[[dict[str, Any]], str]]:
    gold_export_root = selected_gold.parent
    eval_result_local = evaluate_source_rows(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=eval_output_dir,
    )
    return eval_result_local, format_source_row_eval_report_md
