from __future__ import annotations

import typer

from cookimport.config.runtime_support import serialized_run_setting_default
from cookimport.cli_support import (
    Annotated,
    Any,
    BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
    BENCHMARK_EVAL_MODE_STAGE_BLOCKS,
    BENCHMARK_SINGLE_BOOK_UPLOAD_BUNDLE_TARGET_BYTES,
    BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
    BenchmarkPredictionBundle,
    CODEX_FARM_RECIPE_MODE_EXTRACT,
    Callable,
    DEFAULT_GOLDEN,
    DEFAULT_GOLDEN_BENCHMARK,
    DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO,
    DEFAULT_GOLDEN_SENT_TO_LABELSTUDIO,
    DEFAULT_LABELSTUDIO_BENCHMARK_COMPARISONS,
    DEFAULT_OUTPUT,
    DEFAULT_PRELABEL_TIMEOUT_SECONDS,
    EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV,
    KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
    LINE_ROLE_PIPELINE_ROUTE_V2,
    PRELABEL_GRANULARITY_BLOCK,
    Path,
    PredRunContext,
    PredictionRecord,
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
    REPO_ROOT,
    _BENCHMARK_PROGRESS_CALLBACK,
    _BENCHMARK_SCHEDULER_EVENT_CALLBACK,
    _BENCHMARK_SPLIT_PHASE_GATE_DIR,
    _BENCHMARK_SPLIT_PHASE_SLOTS,
    _BENCHMARK_SPLIT_PHASE_STATUS_LABEL,
    _BENCHMARK_SUPPRESS_DASHBOARD_REFRESH,
    _BENCHMARK_SUPPRESS_OUTPUT_PRUNE,
    _BENCHMARK_SUPPRESS_SPINNER,
    _BENCHMARK_SUPPRESS_SUMMARY,
    _INTERACTIVE_CLI_ACTIVE,
    _append_processing_timeseries_marker,
    _attach_freeform_recipe_count_context,
    _benchmark_eval_profile_min_seconds,
    _benchmark_eval_profile_top_n,
    _build_line_role_regression_gate_payload,
    _build_prediction_bundle_from_import_result,
    _build_prediction_bundle_from_records,
    _build_single_book_split_cache_key,
    _enforce_live_labelstudio_benchmark_codex_guardrails,
    _evaluation_telemetry_checkpoints,
    _evaluation_telemetry_load_seconds,
    _fail,
    _find_single_book_llm_manifest_path,
    _format_processing_time,
    _golden_benchmark_root,
    _infer_importer_name_from_source_path,
    _load_pred_run_recipe_context,
    _load_total_recipes_from_report_path,
    _normalize_atomic_block_splitter,
    _normalize_benchmark_eval_mode,
    _normalize_codex_farm_failure_mode,
    _normalize_codex_farm_recipe_mode,
    _normalize_epub_extractor,
    _normalize_gold_adaptation_mode,
    _normalize_ingredient_missing_unit_policy,
    _normalize_ingredient_packaging_mode,
    _normalize_ingredient_parser_backend,
    _normalize_ingredient_pre_normalize_mode,
    _normalize_ingredient_text_fix_backend,
    _normalize_ingredient_unit_canonicalizer,
    _normalize_line_role_pipeline,
    _normalize_llm_knowledge_pipeline,
    _normalize_llm_recipe_pipeline,
    _normalize_multi_recipe_splitter,
    _normalize_ocr_device,
    _normalize_p6_ovenlike_mode,
    _normalize_p6_temperature_backend,
    _normalize_p6_temperature_unit_backend,
    _normalize_p6_time_backend,
    _normalize_p6_time_total_strategy,
    _normalize_p6_yield_mode,
    _normalize_pdf_column_gap_ratio,
    _normalize_pdf_ocr_policy,
    _normalize_single_book_split_cache_mode,
    _normalize_timing_payload,
    _normalize_unstructured_html_parser_version,
    _normalize_unstructured_preprocess_mode,
    _normalize_web_html_text_extractor,
    _normalize_web_schema_extractor,
    _normalize_web_schema_normalizer,
    _normalize_web_schema_policy,
    _notify_benchmark_scheduler_event,
    _notify_progress_callback,
    _path_for_manifest,
    _prediction_record_source_file_hint,
    _print_codex_decision,
    _print_prelabel_completion_summary,
    _processing_timeseries_history_path,
    _refresh_dashboard_after_history_write,
    _report_optional_metric,
    _require_importer,
    _require_labelstudio_write_consent,
    _resolve_benchmark_gold_and_source,
    _resolve_labelstudio_settings,
    _resolve_line_role_baseline_joined_rows,
    _resolve_line_role_predictions_for_benchmark,
    _run_labelstudio_import_with_status,
    _run_with_progress_status,
    _source_key_from_source_path,
    _temporary_benchmark_sequence_matcher,
    _temporary_epub_extractor,
    _temporary_epub_unstructured_options,
    _timing_with_updates,
    _unwrap_typer_option_default,
    _warm_all_models,
    _write_benchmark_upload_bundle,
    _write_eval_run_manifest,
    apply_bucket1_fixed_behavior_metadata,
    apply_codex_execution_policy_metadata,
    bucket1_fixed_behavior,
    build_line_role_flips_vs_baseline,
    build_line_role_joined_line_rows,
    build_line_role_routing_summary,
    build_line_role_slice_metrics,
    build_run_settings,
    cProfile,
    compute_effective_workers,
    compute_file_hash,
    console,
    dt,
    ensure_canonical_gold_artifacts,
    epub,
    evaluate_predicted_vs_freeform,
    evaluate_stage,
    field,
    format_freeform_eval_report_md,
    generate_pred_run_artifacts,
    history_csv_for_output,
    io,
    json,
    labelstudio_benchmark_compare,
    llm_prompt_artifacts,
    load_gold_freeform_ranges,
    load_predicted_labeled_ranges,
    logger,
    normalize_codex_reasoning_effort,
    normalize_prelabel_granularity,
    pstats,
    re,
    read_prediction_records,
    resolve_codex_execution_policy,
    run_labelstudio_export,
    run_labelstudio_import,
    run_pipelined,
    save_mapping_config,
    shutil,
    summarize_knowledge_stage_artifacts,
    time,
    write_line_role_stable_samples,
    write_prediction_records,
    write_prompt_eval_alignment_doc,
    zipfile,
)

_QUANTITY_TOKEN_RE = re.compile(
    r"(?:(?<!\\w)\\d+(?:[./]\\d+)?(?:st|nd|rd|th)?\\b|\\b(?:half|quarter|third)s?\\b)",
    re.IGNORECASE,
)


def _p95_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, ((len(ordered) * 95 + 99) // 100) - 1)
    return int(ordered[idx])


def _has_multiple_quantity_tokens(text: str) -> bool:
    return len(_QUANTITY_TOKEN_RE.findall(text)) >= 2


def _write_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True)
        for row in rows
    )
    path.write_text(payload + "\n", encoding="utf-8")


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


def _find_interrupted_knowledge_stage_root(pred_run: Path | None) -> Path | None:
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


def _finalize_interrupted_benchmark_run(
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
        stage_predictions_path = pred_run / "stage_block_predictions.json"
        if stage_predictions_path.exists():
            prediction_artifacts["stage_block_predictions_json"] = (
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
    knowledge_stage_root = _find_interrupted_knowledge_stage_root(pred_run)
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


def _prune_benchmark_outputs(
    *,
    eval_output_dir: Path,
    processed_run_root: Path | None,
    suppress_summary: bool,
    suppress_output_prune: bool,
) -> None:
    """Drop transient benchmark artifacts after CSV metrics are persisted."""
    from cookimport.analytics.dashboard_collect import (
        _is_excluded_benchmark_artifact,
        _is_pytest_temp_eval_artifact,
    )

    if suppress_output_prune:
        return
    eval_root = eval_output_dir.expanduser()
    if _is_pytest_temp_eval_artifact(eval_root):
        return
    if not _is_excluded_benchmark_artifact(eval_root):
        return

    candidate_targets: list[Path] = [eval_root]
    if processed_run_root is not None:
        candidate_targets.append(processed_run_root.expanduser())

    targets: list[Path] = []
    seen: set[Path] = set()
    for path in candidate_targets:
        if path in seen:
            continue
        seen.add(path)
        if not path.exists() or not path.is_dir():
            continue
        targets.append(path)
    if not targets:
        return

    removed: list[Path] = []
    failed: list[tuple[Path, str]] = []
    for path in targets:
        try:
            shutil.rmtree(path)
            removed.append(path)
        except OSError as exc:
            failed.append((path, str(exc)))

    if suppress_summary:
        return
    if removed:
        typer.secho(
            "Pruned transient benchmark artifacts after CSV metric append:",
            fg=typer.colors.YELLOW,
        )
        for path in removed:
            typer.secho(f"  - {path}", fg=typer.colors.YELLOW)
    if failed:
        typer.secho(
            "Failed to prune some transient benchmark artifacts:",
            fg=typer.colors.YELLOW,
        )
        for path, reason in failed:
            typer.secho(f"  - {path} ({reason})", fg=typer.colors.YELLOW)


def _benchmark_selective_retry_manifest_summary(
    run_config: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(run_config, dict):
        return {}
    summary_fields = (
        "selective_retry_attempted",
        "selective_retry_recipe_correction_attempts",
        "selective_retry_recipe_correction_recovered",
        "selective_retry_final_recipe_attempts",
        "selective_retry_final_recipe_recovered",
    )
    return {
        field: run_config[field]
        for field in summary_fields
        if field in run_config
    }


def register(app: typer.Typer) -> dict[str, object]:
    @app.command()
    def inspect(
        path: Path = typer.Argument(..., help="Workbook file to inspect."),
        out: Path = typer.Option(DEFAULT_OUTPUT, "--out", help="Output folder."),
        write_mapping: bool = typer.Option(
            False,
            "--write-mapping",
            help="Write a mapping stub alongside staged outputs.",
        ),
    ) -> None:
        """Inspect a single workbook and print layout guesses."""
        if not path.exists():
            _fail(f"Path not found: {path}")
        if not path.is_file():
            _fail("Inspect expects a workbook file.")

        importer = _require_importer(path)
        with console.status(f"[bold cyan]Inspecting {path.name}...[/bold cyan]", spinner="dots"):
            inspection = importer.inspect(path)
        typer.secho(f"Workbook: {path.name}", fg=typer.colors.CYAN)
        for sheet in inspection.sheets:
            layout = sheet.layout or "unknown"
            header_row = sheet.header_row or 0
            confidence = sheet.confidence if sheet.confidence is not None else 0.0
            note = " (low confidence)" if sheet.low_confidence else ""
            typer.echo(f"- {sheet.name}: {layout} header_row={header_row} score={confidence:.2f}{note}")
        if write_mapping and inspection.mapping_stub is not None:
            mapping_path = out / "mappings" / f"{path.stem}.mapping.yaml"
            save_mapping_config(mapping_path, inspection.mapping_stub)
            typer.secho(f"Wrote mapping stub to {mapping_path}", fg=typer.colors.GREEN)

    @app.command("labelstudio-import")
    def labelstudio_import(
        path: Path = typer.Argument(..., help="Cookbook file to import for labeling."),
        output_dir: Path = typer.Option(
            DEFAULT_GOLDEN_SENT_TO_LABELSTUDIO,
            "--output-dir",
            help="Output folder for import/upload run artifacts.",
        ),
        pipeline: str = typer.Option("auto", "--pipeline", help="Importer pipeline name or auto."),
        project_name: str | None = typer.Option(
            None, "--project-name", help="Label Studio project name."
        ),
        segment_blocks: int = typer.Option(
            40,
            "--segment-blocks",
            min=1,
            help="Blocks per task for freeform-spans.",
        ),
        segment_overlap: int = typer.Option(
            5,
            "--segment-overlap",
            min=0,
            help="Overlapping blocks between freeform-spans segments.",
        ),
        segment_focus_blocks: Annotated[
            int | None,
            typer.Option(
                "--segment-focus-blocks",
                min=1,
                help=(
                    "Blocks per freeform task that should receive labels. "
                    "Defaults to segment size when omitted."
                ),
            ),
        ] = None,
        target_task_count: Annotated[
            int | None,
            typer.Option(
                "--target-task-count",
                min=1,
                help=(
                    "Optional freeform target task count; overlap is auto-tuned per file "
                    "to land as close as possible."
                ),
            ),
        ] = None,
        overwrite: bool = typer.Option(
            False, "--overwrite/--resume", help="Overwrite project or resume."
        ),
        label_studio_url: str | None = typer.Option(
            None, "--label-studio-url", help="Label Studio base URL."
        ),
        label_studio_api_key: str | None = typer.Option(
            None, "--label-studio-api-key", help="Label Studio API key."
        ),
        allow_labelstudio_write: bool = typer.Option(
            False,
            "--allow-labelstudio-write/--no-allow-labelstudio-write",
            help="Explicitly allow writing tasks to Label Studio.",
        ),
        limit: int | None = typer.Option(
            None, "--limit", "-n", min=1, help="Limit number of chunks."
        ),
        sample: int | None = typer.Option(
            None, "--sample", min=1, help="Randomly sample N chunks."
        ),
        upload_batch_size: int = typer.Option(
            200,
            "--upload-batch-size",
            min=1,
            help="Maximum number of tasks to send per Label Studio upload request.",
        ),
        prelabel: bool = typer.Option(
            False,
            "--prelabel/--no-prelabel",
            help=(
                "For freeform-spans: ask Codex Exec for first-pass labels and "
                "attach completed annotations before upload."
            ),
        ),
        prelabel_provider: str = typer.Option(
            "codex-farm",
            "--prelabel-provider",
            help="LLM provider backend for prelabeling (currently: codex-farm).",
        ),
        codex_cmd: str | None = typer.Option(
            None,
            "--codex-cmd",
            help=(
                "Command used for Codex Exec prelabel calls. "
                "Defaults to COOKIMPORT_CODEX_CMD, COOKIMPORT_CODEX_FARM_CMD, or `codex-farm`."
            ),
        ),
        codex_model: str | None = typer.Option(
            None,
            "--codex-model",
            help=(
                "Explicit Codex model for prelabel calls. "
                "When omitted, uses COOKIMPORT_CODEX_FARM_MODEL, "
                "COOKIMPORT_CODEX_MODEL, or local defaults."
            ),
        ),
        codex_reasoning_effort: Annotated[
            str | None,
            typer.Option(
                "--codex-thinking-effort",
                "--codex-reasoning-effort",
                help=(
                    "Codex thinking effort for prelabel calls "
                    "(none, minimal, low, medium, high, xhigh). "
                    "Mapped to Codex Exec reasoning-effort overrides."
                ),
            ),
        ] = None,
        prelabel_timeout_seconds: Annotated[
            int,
            typer.Option(
                "--prelabel-timeout-seconds",
                min=1,
                help="Timeout per prelabel provider call.",
            ),
        ] = DEFAULT_PRELABEL_TIMEOUT_SECONDS,
        prelabel_cache_dir: Path | None = typer.Option(
            None,
            "--prelabel-cache-dir",
            help="Optional cache directory for prompt/response snapshots.",
        ),
        prelabel_workers: int = typer.Option(
            15,
            "--prelabel-workers",
            min=1,
            help=(
                "Maximum concurrent freeform prelabel provider calls. "
                "Use 1 to force serialized task labeling."
            ),
        ),
        prelabel_upload_as: str = typer.Option(
            "annotations",
            "--prelabel-upload-as",
            help="Upload prelabels as completed annotations or predictions.",
        ),
        prelabel_granularity: str = typer.Option(
            PRELABEL_GRANULARITY_BLOCK,
            "--prelabel-granularity",
            help=(
                "Freeform prelabel style: block (block based) or span "
                "(actual freeform highlights)."
            ),
        ),
        prelabel_allow_partial: bool = typer.Option(
            False,
            "--prelabel-allow-partial/--no-prelabel-allow-partial",
            help=(
                "Allow upload to continue when some prelabel tasks fail. "
                "Failures are recorded in prelabel report files."
            ),
        ),
        llm_recipe_pipeline: str = typer.Option(
            "off",
            "--llm-recipe-pipeline",
            help=(
                "Recipe codex-farm parsing correction pipeline. "
                f"Values: off or {RECIPE_CODEX_FARM_PIPELINE_SHARD_V1}."
            ),
        ),
        allow_codex: bool = typer.Option(
            False,
            "--allow-codex/--no-allow-codex",
            help="Required when Label Studio import enables Codex-backed recipe parsing.",
        ),
        codex_farm_cmd: str = typer.Option(
            "codex-farm",
            "--codex-farm-cmd",
            help="Executable used for codex-farm calls when LLM recipe pipeline is enabled.",
        ),
        codex_farm_root: Path | None = typer.Option(
            None,
            "--codex-farm-root",
            help="Optional codex-farm pipeline-pack root. Defaults to <repo_root>/llm_pipelines.",
        ),
        codex_farm_workspace_root: Path | None = typer.Option(
            None,
            "--codex-farm-workspace-root",
            help=(
                "Optional workspace root passed to codex-farm. "
                "When omitted, codex-farm pipeline codex_cd_mode decides."
            ),
        ),
        codex_farm_context_blocks: int = typer.Option(
            30,
            "--codex-farm-context-blocks",
            min=0,
            help="Blocks before/after each recipe candidate included in pass-1 codex-farm bundles.",
        ),
        codex_farm_failure_mode: str = typer.Option(
            "fail",
            "--codex-farm-failure-mode",
            help="Behavior when codex-farm setup/invocation fails: fail or fallback.",
        ),
    ) -> None:
        """Create and upload freeform span Label Studio tasks."""
        allow_labelstudio_write = _unwrap_typer_option_default(allow_labelstudio_write)
        output_dir = _unwrap_typer_option_default(output_dir)
        pipeline = _unwrap_typer_option_default(pipeline)
        project_name = _unwrap_typer_option_default(project_name)
        segment_blocks = _unwrap_typer_option_default(segment_blocks)
        segment_overlap = _unwrap_typer_option_default(segment_overlap)
        segment_focus_blocks = _unwrap_typer_option_default(segment_focus_blocks)
        target_task_count = _unwrap_typer_option_default(target_task_count)
        overwrite = _unwrap_typer_option_default(overwrite)
        label_studio_url = _unwrap_typer_option_default(label_studio_url)
        label_studio_api_key = _unwrap_typer_option_default(label_studio_api_key)
        limit = _unwrap_typer_option_default(limit)
        sample = _unwrap_typer_option_default(sample)
        upload_batch_size = _unwrap_typer_option_default(upload_batch_size)
        prelabel = _unwrap_typer_option_default(prelabel)
        prelabel_provider = _unwrap_typer_option_default(prelabel_provider)
        codex_cmd = _unwrap_typer_option_default(codex_cmd)
        codex_model = _unwrap_typer_option_default(codex_model)
        codex_reasoning_effort = _unwrap_typer_option_default(codex_reasoning_effort)
        prelabel_timeout_seconds = _unwrap_typer_option_default(prelabel_timeout_seconds)
        prelabel_cache_dir = _unwrap_typer_option_default(prelabel_cache_dir)
        prelabel_workers = _unwrap_typer_option_default(prelabel_workers)
        prelabel_upload_as = _unwrap_typer_option_default(prelabel_upload_as)
        prelabel_granularity = _unwrap_typer_option_default(prelabel_granularity)
        prelabel_allow_partial = _unwrap_typer_option_default(prelabel_allow_partial)
        llm_recipe_pipeline = _unwrap_typer_option_default(llm_recipe_pipeline)
        allow_codex = _unwrap_typer_option_default(allow_codex)
        codex_farm_cmd = _unwrap_typer_option_default(codex_farm_cmd)
        codex_farm_root = _unwrap_typer_option_default(codex_farm_root)
        codex_farm_workspace_root = _unwrap_typer_option_default(codex_farm_workspace_root)
        codex_farm_context_blocks = _unwrap_typer_option_default(codex_farm_context_blocks)
        codex_farm_failure_mode = _unwrap_typer_option_default(codex_farm_failure_mode)

        normalized_prelabel_upload_as = prelabel_upload_as.strip().lower()
        if normalized_prelabel_upload_as not in {"annotations", "predictions"}:
            _fail(
                "--prelabel-upload-as must be one of: annotations, predictions."
            )
        try:
            normalized_prelabel_granularity = normalize_prelabel_granularity(
                prelabel_granularity
            )
        except ValueError as exc:
            _fail(f"--prelabel-granularity invalid: {exc}")
        try:
            normalized_codex_reasoning_effort = normalize_codex_reasoning_effort(
                codex_reasoning_effort
            )
        except ValueError as exc:
            _fail(f"--codex-thinking-effort invalid: {exc}")
        resolved_segment_focus_blocks = (
            segment_blocks if segment_focus_blocks is None else int(segment_focus_blocks)
        )
        if resolved_segment_focus_blocks > segment_blocks:
            _fail("--segment-focus-blocks must be <= --segment-blocks.")
        selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
        fixed_bucket1_behavior = bucket1_fixed_behavior()
        selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
            codex_farm_failure_mode
        )
        import_codex_execution = resolve_codex_execution_policy(
            "labelstudio_import",
            {
                "llm_recipe_pipeline": selected_llm_recipe_pipeline,
                "prelabel_enabled": bool(prelabel),
                "prelabel_provider": prelabel_provider,
            },
            execution_policy_mode="execute",
            allow_codex=bool(allow_codex),
        )
        if import_codex_execution.blocked:
            codex_surfaces = ", ".join(import_codex_execution.surface.codex_surfaces) or "unknown"
            _fail(
                "labelstudio-import enables Codex-backed surfaces "
                f"({codex_surfaces}) and requires "
                "explicit approval. Re-run with --allow-codex only after explicit "
                "positive user approval."
            )
        _print_codex_decision(import_codex_execution)
        _require_labelstudio_write_consent(allow_labelstudio_write)
        url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)
        import_timeseries_path = _processing_timeseries_history_path(
            root=output_dir,
            scope="labelstudio_import",
            source_name=path.name,
        )
        import_started_at = time.monotonic()
        try:
            result = _run_labelstudio_import_with_status(
                source_name=path.name,
                telemetry_path=import_timeseries_path,
                run_import=lambda update_progress: run_labelstudio_import(
                    path=path,
                    output_dir=output_dir,
                    pipeline=pipeline,
                    project_name=project_name,
                    segment_blocks=segment_blocks,
                    segment_overlap=segment_overlap,
                    segment_focus_blocks=resolved_segment_focus_blocks,
                    target_task_count=target_task_count,
                    overwrite=overwrite,
                    resume=not overwrite,
                    label_studio_url=url,
                    label_studio_api_key=api_key,
                    limit=limit,
                    sample=sample,
                    upload_batch_size=upload_batch_size,
                    progress_callback=update_progress,
                    prelabel=prelabel,
                    prelabel_provider=prelabel_provider,
                    codex_cmd=codex_cmd,
                    codex_model=codex_model,
                    codex_reasoning_effort=normalized_codex_reasoning_effort,
                    prelabel_timeout_seconds=prelabel_timeout_seconds,
                    prelabel_cache_dir=prelabel_cache_dir,
                    prelabel_workers=prelabel_workers,
                    prelabel_upload_as=normalized_prelabel_upload_as,
                    prelabel_granularity=normalized_prelabel_granularity,
                    prelabel_allow_partial=prelabel_allow_partial,
                    prelabel_track_token_usage=True,
                    llm_recipe_pipeline=selected_llm_recipe_pipeline,
                    codex_farm_cmd=codex_farm_cmd,
                    codex_farm_root=codex_farm_root,
                    codex_farm_workspace_root=codex_farm_workspace_root,
                    codex_farm_context_blocks=codex_farm_context_blocks,
                    codex_farm_failure_mode=selected_codex_farm_failure_mode,
                    allow_codex=bool(allow_codex),
                    codex_execution_policy="execute",
                    allow_labelstudio_write=True,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _fail(str(exc))
        processing_time_seconds = max(0.0, time.monotonic() - import_started_at)
        codex_exec_prompt_response_log_path: Path | None = None
        run_root_value = result.get("run_root")
        if run_root_value is not None:
            run_root_path = Path(str(run_root_value))
            codex_exec_prompt_response_log_path = (
                llm_prompt_artifacts.build_codex_farm_prompt_response_log(
                    pred_run=run_root_path,
                    eval_output_dir=run_root_path,
                    repo_root=REPO_ROOT,
                )
            )

        typer.secho(
            f"Label Studio project: {result['project_name']} (id={result['project_id']})",
            fg=typer.colors.GREEN,
        )
        typer.secho(
            f"Tasks created: {result['tasks_total']} (uploaded {result['tasks_uploaded']})",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            f"Processing time: {_format_processing_time(processing_time_seconds)}",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            f"Processing telemetry: {import_timeseries_path}",
            fg=typer.colors.BRIGHT_BLACK,
        )
        if prelabel:
            _print_prelabel_completion_summary(
                prelabel_summary=result.get("prelabel") or {},
                report_path=result.get("prelabel_report_path"),
                inline_annotation_fallback=bool(
                    result.get("prelabel_inline_annotations_fallback")
                ),
            )
        if codex_exec_prompt_response_log_path is not None:
            typer.secho(
                f"Codex Exec prompt artifacts: {codex_exec_prompt_response_log_path.parent}",
                fg=typer.colors.CYAN,
            )
        typer.secho(f"Artifacts saved to: {result['run_root']}", fg=typer.colors.CYAN)
        typer.echo("\nTo export labels:\n")
        typer.echo(
            f'cookimport labelstudio-export --project-name "{result["project_name"]}" '
            f'--label-studio-url {url} --label-studio-api-key $LABEL_STUDIO_API_KEY'
        )

    @app.command("labelstudio-export")
    def labelstudio_export(
        project_name: str = typer.Option(..., "--project-name", help="Label Studio project name."),
        output_dir: Path = typer.Option(
            DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO,
            "--output-dir",
            help="Output folder for exported golden artifacts.",
        ),
        run_dir: Path | None = typer.Option(
            None, "--run-dir", help="Specific labelstudio run directory to export."
        ),
        label_studio_url: str | None = typer.Option(
            None, "--label-studio-url", help="Label Studio base URL."
        ),
        label_studio_api_key: str | None = typer.Option(
            None, "--label-studio-api-key", help="Label Studio API key."
        ),
    ) -> None:
        """Export completed Label Studio annotations into golden-set JSONL artifacts."""
        url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)
        try:
            result = run_labelstudio_export(
                project_name=project_name,
                output_dir=output_dir,
                label_studio_url=url,
                label_studio_api_key=api_key,
                run_dir=run_dir,
            )
        except Exception as exc:  # noqa: BLE001
            _fail(str(exc))

        summary_path = result["summary_path"]
        typer.secho(f"Export complete. Summary: {summary_path}", fg=typer.colors.GREEN)

    @app.command("labelstudio-eval")
    def labelstudio_eval(
        pred_run: Path = typer.Option(
            ..., "--pred-run", help="Label Studio run directory with label_studio_tasks.jsonl."
        ),
        gold_spans: Path = typer.Option(
            ..., "--gold-spans", help="Path to freeform gold JSONL."
        ),
        output_dir: Path = typer.Option(
            ..., "--output-dir", help="Output folder for eval artifacts."
        ),
        overlap_threshold: Annotated[
            float,
            typer.Option(
                "--overlap-threshold",
                min=0.0,
                max=1.0,
                help="Jaccard overlap threshold for matching.",
            ),
        ] = 0.5,
        force_source_match: Annotated[
            bool,
            typer.Option(
                "--force-source-match",
                help=(
                    "Ignore source hash/file identity when matching spans. "
                    "Useful for comparing renamed/truncated source variants."
                ),
            ),
        ] = False,
        llm_recipe_pipeline: Annotated[str | None, typer.Option(
            "--llm-recipe-pipeline",
            help=(
                "Optional run-config override for eval metadata parity. "
                "When omitted, value is inferred from eval-run manifest metadata."
            ),
        )] = None,
        atomic_block_splitter: Annotated[str | None, typer.Option(
            "--atomic-block-splitter",
            help=(
                "Optional run-config override for eval metadata parity. "
                "When omitted, value is inferred from eval-run manifest metadata."
            ),
        )] = None,
        line_role_pipeline: Annotated[str | None, typer.Option(
            "--line-role-pipeline",
            help=(
                "Optional run-config override for eval metadata parity. "
                "When omitted, value is inferred from eval-run manifest metadata."
            ),
        )] = None,
    ) -> None:
        """Evaluate freeform predictions against freeform gold sets."""
        scope = "freeform-spans"
        if not pred_run.exists():
            _fail(f"Predicted run not found: {pred_run}")
        if not gold_spans.exists():
            _fail(f"Gold spans file not found: {gold_spans}")

        output_dir.mkdir(parents=True, exist_ok=True)

        predicted = load_predicted_labeled_ranges(pred_run)
        gold = load_gold_freeform_ranges(gold_spans)
        result = evaluate_predicted_vs_freeform(
            predicted,
            gold,
            overlap_threshold=overlap_threshold,
            force_source_match=force_source_match,
        )
        report = result["report"]

        pred_context = _load_pred_run_recipe_context(pred_run)
        _attach_freeform_recipe_count_context(
            report=report,
            gold_spans_path=gold_spans,
            predicted_recipe_count=pred_context.recipes,
            predicted_recipe_count_source=(
                "prediction_run_context" if pred_context.recipes is not None else None
            ),
        )
        report_md = format_freeform_eval_report_md(report)

        report_json_path = output_dir / "eval_report.json"
        report_json_path.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        report_md_path = output_dir / "eval_report.md"
        report_md_path.write_text(report_md, encoding="utf-8")

        _write_jsonl_rows(output_dir / "missed_gold_spans.jsonl", result["missed_gold"])
        _write_jsonl_rows(
            output_dir / "false_positive_preds.jsonl", result["false_positive_preds"]
        )

        csv_source_file = pred_context.source_file or ""
        csv_history_root = DEFAULT_OUTPUT
        if pred_context.processed_report_path:
            processed_report = Path(pred_context.processed_report_path)
            if (
                processed_report.name.endswith(".excel_import_report.json")
                and len(processed_report.parents) >= 2
            ):
                csv_history_root = processed_report.parents[1]

        from cookimport.analytics.perf_report import append_benchmark_csv, history_path
        csv_history_path = history_path(csv_history_root)
        append_benchmark_csv(
            report,
            csv_history_path,
            run_timestamp=dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            run_dir=str(output_dir),
            eval_scope=scope,
            source_file=csv_source_file,
            importer_name=_infer_importer_name_from_source_path(csv_source_file),
            recipes=pred_context.recipes,
            processed_report_path=pred_context.processed_report_path,
            run_config=pred_context.run_config,
            run_config_hash=pred_context.run_config_hash,
            run_config_summary=pred_context.run_config_summary,
            tokens_input=getattr(pred_context, "tokens_input", None),
            tokens_cached_input=getattr(pred_context, "tokens_cached_input", None),
            tokens_output=getattr(pred_context, "tokens_output", None),
            tokens_reasoning=getattr(pred_context, "tokens_reasoning", None),
            tokens_total=getattr(pred_context, "tokens_total", None),
        )
        _refresh_dashboard_after_history_write(
            csv_path=csv_history_path,
            output_root=csv_history_root,
            golden_root=DEFAULT_GOLDEN,
            reason="labelstudio-eval history append",
        )

        eval_run_config: dict[str, Any] = {
            "scope": scope,
            "overlap_threshold": overlap_threshold,
            "force_source_match": force_source_match,
        }
        pred_run_config = (
            pred_context.run_config if isinstance(pred_context.run_config, dict) else {}
        )
        llm_recipe_pipeline_value = (
            pred_run_config.get("llm_recipe_pipeline")
            if llm_recipe_pipeline is None
            else llm_recipe_pipeline
        )
        atomic_block_splitter_value = (
            pred_run_config.get("atomic_block_splitter")
            if atomic_block_splitter is None
            else atomic_block_splitter
        )
        line_role_pipeline_value = (
            pred_run_config.get("line_role_pipeline")
            if line_role_pipeline is None
            else line_role_pipeline
        )
        resolved_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(
            str(llm_recipe_pipeline_value or "off")
        )
        resolved_atomic_block_splitter = _normalize_atomic_block_splitter(
            str(atomic_block_splitter_value or "off")
        )
        resolved_line_role_pipeline = _normalize_line_role_pipeline(
            str(line_role_pipeline_value or "off")
        )
        eval_run_config["llm_recipe_pipeline"] = resolved_llm_recipe_pipeline
        eval_run_config["atomic_block_splitter"] = resolved_atomic_block_splitter
        eval_run_config["line_role_pipeline"] = resolved_line_role_pipeline
        if pred_context.run_config is not None:
            eval_run_config["prediction_run_config"] = pred_context.run_config
        if pred_context.run_config_hash:
            eval_run_config["prediction_run_config_hash"] = pred_context.run_config_hash
        if pred_context.run_config_summary:
            eval_run_config["prediction_run_config_summary"] = pred_context.run_config_summary

        _write_eval_run_manifest(
            run_root=output_dir,
            run_kind="labelstudio_eval",
            source_path=pred_context.source_file or None,
            source_hash=pred_context.source_hash,
            importer_name=None,
            run_config=eval_run_config,
            artifacts={
                "artifact_root_dir": _path_for_manifest(output_dir, pred_run),
                "gold_spans_jsonl": _path_for_manifest(output_dir, gold_spans),
                "eval_report_json": "eval_report.json",
                "eval_report_md": "eval_report.md",
                "missed_gold_spans_jsonl": "missed_gold_spans.jsonl",
                "false_positive_preds_jsonl": "false_positive_preds.jsonl",
                "history_csv": str(history_csv_for_output(csv_history_root)),
            },
            notes="Evaluation report against exported gold spans.",
        )

        typer.secho(
            f"Evaluation complete. Report: {report_md_path}",
            fg=typer.colors.GREEN,
        )

    @app.command("debug-epub-extract")
    def debug_epub_extract(
        path: Path = typer.Argument(..., help="EPUB file to inspect."),
        out: Path = typer.Option(
            DEFAULT_OUTPUT / "epub-debug",
            "--out",
            help="Output root for debug extraction artifacts.",
        ),
        spine: int = typer.Option(
            0,
            "--spine",
            min=0,
            help="Spine index to extract for variant comparison.",
        ),
        variants: bool = typer.Option(
            False,
            "--variants",
            help=(
                "Run the parser/preprocess variant grid "
                "(v1/v2 x none/br_split_v1) instead of a single variant."
            ),
        ),
        html_parser_version: str = typer.Option(
            "v1",
            "--html-parser-version",
            help="Single-run parser version when --variants is not set (v1 or v2).",
        ),
        preprocess_mode: str = typer.Option(
            "none",
            "--preprocess-mode",
            help=(
                "Single-run preprocess mode when --variants is not set "
                "(none, br_split_v1)."
            ),
        ),
        skip_headers_footers: bool = typer.Option(
            False,
            "--skip-headers-footers/--no-skip-headers-footers",
            help="Pass skip_headers_and_footers into Unstructured partition_html.",
        ),
    ) -> None:
        """Compare unstructured EPUB extraction variants for one spine XHTML document."""
        from cookimport.parsing.block_roles import assign_block_roles
        from cookimport.parsing.epub_postprocess import postprocess_epub_blocks
        from cookimport.parsing.epub_html_normalize import normalize_epub_html_for_unstructured
        from cookimport.parsing import signals
        from cookimport.parsing.unstructured_adapter import (
            UnstructuredHtmlOptions,
            partition_html_to_blocks,
        )

        if not path.exists() or not path.is_file():
            _fail(f"EPUB file not found: {path}")
        if path.suffix.lower() != ".epub":
            _fail(f"Expected an EPUB file, got: {path}")

        selected_parser = _normalize_unstructured_html_parser_version(html_parser_version)
        selected_preprocess = _normalize_unstructured_preprocess_mode(preprocess_mode)

        run_root = out / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        run_root.mkdir(parents=True, exist_ok=True)

        importer = epub.EpubImporter()
        _title, spine_items = importer._read_epub_spine(path)  # noqa: SLF001
        if not spine_items:
            _fail("No spine items found in EPUB.")
        if spine >= len(spine_items):
            _fail(
                f"Spine index out of range: {spine}. "
                f"EPUB has {len(spine_items)} spine entries."
            )

        spine_path = spine_items[spine].path
        with zipfile.ZipFile(path) as zip_handle:
            raw_html = zip_handle.read(spine_path).decode("utf-8", errors="replace")
        (run_root / "raw_spine.xhtml").write_text(raw_html, encoding="utf-8")

        variant_pairs: list[tuple[str, str]]
        if variants:
            variant_pairs = [
                (parser_version, preprocess_variant)
                for preprocess_variant in ("none", "br_split_v1")
                for parser_version in ("v1", "v2")
            ]
        else:
            variant_pairs = [(selected_parser, selected_preprocess)]

        summary_rows: list[dict[str, Any]] = []
        for parser_version, preprocess_variant in variant_pairs:
            variant_slug = f"parser_{parser_version}__preprocess_{preprocess_variant}"
            variant_dir = run_root / variant_slug
            variant_dir.mkdir(parents=True, exist_ok=True)

            normalized_html = normalize_epub_html_for_unstructured(
                raw_html,
                mode=preprocess_variant,
            )
            (variant_dir / "normalized_spine.xhtml").write_text(
                normalized_html,
                encoding="utf-8",
            )

            options = UnstructuredHtmlOptions(
                html_parser_version=parser_version,
                skip_headers_and_footers=skip_headers_footers,
                preprocess_mode=preprocess_variant,
            )
            try:
                blocks, diagnostics = partition_html_to_blocks(
                    normalized_html,
                    spine_index=spine,
                    source_location_id=path.stem,
                    options=options,
                )
            except Exception as exc:  # noqa: BLE001
                (variant_dir / "error.txt").write_text(str(exc), encoding="utf-8")
                summary_rows.append(
                    {
                        "variant": variant_slug,
                        "html_parser_version": parser_version,
                        "preprocess_mode": preprocess_variant,
                        "skip_headers_footers": skip_headers_footers,
                        "error": str(exc),
                        "block_count": 0,
                        "p95_block_length": 0,
                        "blocks_with_multiple_quantities": 0,
                        "ingredient_line_block_count": 0,
                    }
                )
                continue
            blocks = postprocess_epub_blocks(blocks)
            for block in blocks:
                signals.enrich_block(block)
            assign_block_roles(blocks)

            blocks_rows = [
                {
                    "index": index,
                    "text": block.text,
                    "type": str(block.type),
                    "font_weight": block.font_weight,
                    "features": dict(block.features),
                }
                for index, block in enumerate(blocks)
            ]
            _write_jsonl_rows(variant_dir / "blocks.jsonl", blocks_rows)
            _write_jsonl_rows(variant_dir / "unstructured_elements.jsonl", diagnostics)

            block_lengths = [len(block.text) for block in blocks if block.text]
            ingredient_line_count = sum(
                1
                for block in blocks
                if block.features.get("block_role") == "ingredient_line"
            )
            multi_quantity_count = sum(
                1
                for block in blocks
                if _has_multiple_quantity_tokens(block.text)
            )
            summary_rows.append(
                {
                    "variant": variant_slug,
                    "html_parser_version": parser_version,
                    "preprocess_mode": preprocess_variant,
                    "skip_headers_footers": skip_headers_footers,
                    "block_count": len(blocks),
                    "p95_block_length": _p95_int(block_lengths),
                    "blocks_with_multiple_quantities": multi_quantity_count,
                    "ingredient_line_block_count": ingredient_line_count,
                }
            )

        summary_payload = {
            "source_file": str(path),
            "spine_index": spine,
            "spine_path": spine_path,
            "variants": summary_rows,
        }
        (run_root / "summary.json").write_text(
            json.dumps(summary_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        typer.secho(f"Wrote EPUB debug extraction artifacts to: {run_root}", fg=typer.colors.GREEN)
        for row in summary_rows:
            typer.echo(
                " | ".join(
                    [
                        row["variant"],
                        f"blocks={row['block_count']}",
                        f"p95_len={row['p95_block_length']}",
                        f"multi_qty={row['blocks_with_multiple_quantities']}",
                        f"ingredient_line={row['ingredient_line_block_count']}",
                    ]
                )
            )

    @app.command("labelstudio-benchmark")
    def labelstudio_benchmark(
        action: Annotated[str, typer.Argument(
            help="Action: run (default) or compare.",
        )] = "run",
        gold_spans: Annotated[Path | None, typer.Option(
            "--gold-spans",
            help="Path to freeform_span_labels.jsonl (prompts if omitted).",
        )] = None,
        source_file: Annotated[Path | None, typer.Option(
            "--source-file",
            help="Source file to import and benchmark (prompts if omitted).",
        )] = None,
        output_dir: Annotated[Path, typer.Option(
            "--output-dir",
            help="Scratch output root used while generating prediction tasks before co-locating under eval output.",
        )] = DEFAULT_GOLDEN_BENCHMARK,
        processed_output_dir: Annotated[Path, typer.Option(
            "--processed-output-dir",
            help="Output root for staged cookbook outputs generated during benchmark (for upload/review).",
        )] = DEFAULT_OUTPUT,
        eval_output_dir: Annotated[Path | None, typer.Option(
            "--eval-output-dir", help="Output folder for benchmark report artifacts."
        )] = None,
        overlap_threshold: Annotated[float, typer.Option(
            "--overlap-threshold",
            min=0.0,
            max=1.0,
            help="Jaccard overlap threshold for matching.",
        )] = 0.5,
        force_source_match: Annotated[bool, typer.Option(
            "--force-source-match",
            help=(
                "Ignore source hash/file identity when matching spans. "
                "Useful for comparing renamed/truncated source variants."
            ),
        )] = False,
        eval_mode: Annotated[str, typer.Option(
            "--eval-mode",
            help=(
                "Benchmark evaluator mode: stage-blocks (block-index parity required) "
                "or canonical-text (extractor-independent alignment scoring)."
            ),
        )] = BENCHMARK_EVAL_MODE_STAGE_BLOCKS,
        gold_adaptation_mode: Annotated[str, typer.Option(
            "--gold-adaptation-mode",
            help=(
                "Stage-block evaluator only: off keeps strict block index parity; "
                "auto adaptively remaps immutable gold labels when extractor fingerprints drift; "
                "force always applies adaptive remap."
            ),
        )] = "auto",
        gold_adaptation_min_coverage: Annotated[float, typer.Option(
            "--gold-adaptation-min-coverage",
            min=0.0,
            max=1.0,
            help="Stage-block evaluator only: minimum remap coverage required when adaptation runs.",
        )] = 0.7,
        gold_adaptation_max_ambiguous: Annotated[int, typer.Option(
            "--gold-adaptation-max-ambiguous",
            min=0,
            help="Stage-block evaluator only: maximum ambiguous remap assignments allowed.",
        )] = 50,
        sequence_matcher: Annotated[str, typer.Option(
            "--sequence-matcher",
            hidden=True,
            help=(
                "Canonical-text SequenceMatcher mode (dmp only)."
            ),
        )] = "dmp",
        predictions_out: Annotated[Path | None, typer.Option(
            "--predictions-out",
            help=(
                "Optional JSONL artifact path for prediction-stage records. "
                "Useful for rerunning evaluate-only with --predictions-in."
            ),
        )] = None,
        predictions_in: Annotated[Path | None, typer.Option(
            "--predictions-in",
            help=(
                "Optional JSONL prediction-stage record path. "
                "When set, skips prediction generation and runs evaluate-only."
            ),
        )] = None,
        baseline: Annotated[Path | None, typer.Option(
            "--baseline",
            help=(
                "Compare action only: baseline all-method benchmark run directory "
                "(or report JSON path)."
            ),
        )] = None,
        candidate: Annotated[Path | None, typer.Option(
            "--candidate",
            help=(
                "Compare action only: candidate all-method benchmark run directory "
                "(or report JSON path)."
            ),
        )] = None,
        compare_out: Annotated[Path, typer.Option(
            "--compare-out",
            help=(
                "Compare action only: output root for timestamped comparison reports."
            ),
        )] = DEFAULT_LABELSTUDIO_BENCHMARK_COMPARISONS,
        fail_on_regression: Annotated[bool, typer.Option(
            "--fail-on-regression/--no-fail-on-regression",
            help=(
                "Compare action only: return non-zero exit code when comparison verdict is FAIL."
            ),
        )] = False,
        pipeline: Annotated[str, typer.Option("--pipeline", help="Importer pipeline name or auto.")] = "auto",
        project_name: Annotated[str | None, typer.Option(
            "--project-name",
            help="Optional Label Studio project name for prediction import.",
        )] = None,
        allow_labelstudio_write: Annotated[bool, typer.Option(
            "--allow-labelstudio-write/--no-allow-labelstudio-write",
            help=(
                "Explicitly allow uploading prediction tasks to Label Studio. "
                "Ignored when --no-upload is set."
            ),
        )] = False,
        no_upload: Annotated[bool, typer.Option(
            "--no-upload",
            help=(
                "Generate prediction artifacts locally and evaluate without "
                "uploading to Label Studio."
            ),
        )] = False,
        write_markdown: Annotated[bool, typer.Option(
            "--write-markdown/--no-write-markdown",
            help=(
                "Write markdown sidecar artifacts for processed stage outputs "
                "(sections/chunks/tables)."
            ),
        )] = True,
        write_label_studio_tasks: Annotated[bool, typer.Option(
            "--write-labelstudio-tasks/--no-write-labelstudio-tasks",
            help=(
                "Write label_studio_tasks.jsonl in offline prediction runs. "
                "Upload mode always requires task JSONL."
            ),
        )] = True,
        overwrite: Annotated[bool, typer.Option("--overwrite/--resume", help="Overwrite prediction project or resume.")] = False,
        label_studio_url: Annotated[str | None, typer.Option("--label-studio-url", help="Label Studio base URL.")] = None,
        label_studio_api_key: Annotated[str | None, typer.Option("--label-studio-api-key", help="Label Studio API key.")] = None,
        workers: Annotated[int, typer.Option("--workers", min=1, help="Number of parallel worker processes for prediction import.")] = 7,
        pdf_split_workers: Annotated[int, typer.Option("--pdf-split-workers", min=1, help="Max workers used when splitting a PDF prediction import.")] = 7,
        epub_split_workers: Annotated[int, typer.Option("--epub-split-workers", min=1, help="Max workers used when splitting an EPUB prediction import.")] = 7,
        pdf_pages_per_job: Annotated[int, typer.Option("--pdf-pages-per-job", min=1, help="Target page count per PDF split job.")] = 50,
        epub_spine_items_per_job: Annotated[int, typer.Option("--epub-spine-items-per-job", min=1, help="Target spine items per EPUB split job.")] = 10,
        ocr_device: Annotated[str, typer.Option(
            "--ocr-device",
            hidden=True,
            help="OCR device to use (auto, cpu, cuda, mps).",
        )] = "auto",
        pdf_ocr_policy: Annotated[str, typer.Option(
            "--pdf-ocr-policy",
            help="PDF OCR policy: off, auto, or always.",
        )] = "auto",
        ocr_batch_size: Annotated[int, typer.Option(
            "--ocr-batch-size",
            min=1,
            hidden=True,
            help="Number of pages to process per OCR model call.",
        )] = 1,
        pdf_column_gap_ratio: Annotated[float, typer.Option(
            "--pdf-column-gap-ratio",
            min=0.01,
            max=0.95,
            hidden=True,
            help="Minimum horizontal gap ratio used for PDF column-boundary detection.",
        )] = 0.12,
        warm_models: Annotated[bool, typer.Option(
            "--warm-models",
            help="Proactively load heavy models before prediction import.",
        )] = False,
        epub_extractor: Annotated[str, typer.Option(
            "--epub-extractor",
            help=(
                "EPUB extraction engine: unstructured (semantic), beautifulsoup "
                "(BeautifulSoup), markdown (HTML->Markdown), or markitdown (whole-book "
                "EPUB->markdown mode). Markdown extractors are policy-locked off unless "
                f"{EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1."
            ),
        )] = "unstructured",
        epub_unstructured_html_parser_version: Annotated[str, typer.Option(
            "--epub-unstructured-html-parser-version",
            help="Unstructured HTML parser version for EPUB extraction: v1 or v2.",
        )] = "v1",
        epub_unstructured_skip_headers_footers: Annotated[bool, typer.Option(
            "--epub-unstructured-skip-headers-footers/--no-epub-unstructured-skip-headers-footers",
            help="Enable Unstructured skip_headers_and_footers for EPUB HTML partitioning.",
        )] = True,
        epub_unstructured_preprocess_mode: Annotated[str, typer.Option(
            "--epub-unstructured-preprocess-mode",
            help="EPUB HTML preprocess mode before Unstructured partitioning: none, br_split_v1.",
        )] = "br_split_v1",
        epub_title_backtrack_limit: Annotated[int, typer.Option(
            "--epub-title-backtrack-limit",
            min=1,
            hidden=True,
            help="Max EPUB blocks to scan backward while recovering a recipe title.",
        )] = int(serialized_run_setting_default("epub_title_backtrack_limit")),
        epub_anchor_title_backtrack_limit: Annotated[int, typer.Option(
            "--epub-anchor-title-backtrack-limit",
            min=1,
            hidden=True,
            help="Max EPUB blocks to scan backward when a yield or anchor triggers title recovery.",
        )] = int(serialized_run_setting_default("epub_anchor_title_backtrack_limit")),
        epub_ingredient_run_window: Annotated[int, typer.Option(
            "--epub-ingredient-run-window",
            min=1,
            hidden=True,
            help="EPUB heuristic window for nearby ingredient-run detection.",
        )] = int(serialized_run_setting_default("epub_ingredient_run_window")),
        epub_ingredient_header_window: Annotated[int, typer.Option(
            "--epub-ingredient-header-window",
            min=1,
            hidden=True,
            help="EPUB heuristic window for detecting a later ingredient header.",
        )] = int(serialized_run_setting_default("epub_ingredient_header_window")),
        epub_title_max_length: Annotated[int, typer.Option(
            "--epub-title-max-length",
            min=1,
            hidden=True,
            help="Maximum EPUB title-candidate block length.",
        )] = int(serialized_run_setting_default("epub_title_max_length")),
        section_detector_backend: Annotated[str, typer.Option(
            "--section-detector-backend",
            hidden=True,
            help="Section detector backend: shared_v1.",
        )] = "shared_v1",
        multi_recipe_splitter: Annotated[str, typer.Option(
            "--multi-recipe-splitter",
            hidden=True,
            help="Shared multi-recipe splitter backend: off or rules_v1.",
        )] = "rules_v1",
        multi_recipe_trace: Annotated[bool, typer.Option(
            "--multi-recipe-trace/--no-multi-recipe-trace",
            hidden=True,
            help="Write shared multi-recipe splitter trace artifacts.",
        )] = False,
        multi_recipe_min_ingredient_lines: Annotated[int, typer.Option(
            "--multi-recipe-min-ingredient-lines",
            min=0,
            hidden=True,
            help="Minimum ingredient-like lines required on each side of a split boundary.",
        )] = 1,
        multi_recipe_min_instruction_lines: Annotated[int, typer.Option(
            "--multi-recipe-min-instruction-lines",
            min=0,
            hidden=True,
            help="Minimum instruction-like lines required on each side of a split boundary.",
        )] = 1,
        multi_recipe_for_the_guardrail: Annotated[bool, typer.Option(
            "--multi-recipe-for-the-guardrail/--no-multi-recipe-for-the-guardrail",
            hidden=True,
            help="Prevent boundaries on component headers like 'For the sauce'.",
        )] = True,
        instruction_step_segmentation_policy: Annotated[str, typer.Option(
            "--instruction-step-segmentation-policy",
            hidden=True,
            help="Fallback instruction-step segmentation policy: off, auto, or always.",
        )] = "auto",
        instruction_step_segmenter: Annotated[str, typer.Option(
            "--instruction-step-segmenter",
            hidden=True,
            help="Instruction-step fallback segmenter backend: heuristic_v1 or pysbd_v1.",
        )] = "heuristic_v1",
        web_schema_extractor: Annotated[str, typer.Option(
            "--web-schema-extractor",
            help=(
                "Schema extractor backend for HTML/JSON schema sources: "
                "builtin_jsonld, extruct, scrape_schema_recipe, recipe_scrapers, ensemble_v1."
            ),
        )] = "builtin_jsonld",
        web_schema_normalizer: Annotated[str, typer.Option(
            "--web-schema-normalizer",
            help="Schema normalization mode: simple or pyld.",
        )] = "simple",
        web_html_text_extractor: Annotated[str, typer.Option(
            "--web-html-text-extractor",
            help=(
                "Fallback HTML text extractor when schema is absent/disabled: "
                "bs4, trafilatura, readability_lxml, justext, boilerpy3, ensemble_v1."
            ),
        )] = "bs4",
        web_schema_policy: Annotated[str, typer.Option(
            "--web-schema-policy",
            help="Schema policy: prefer_schema, schema_only, or heuristic_only.",
        )] = "prefer_schema",
        web_schema_min_confidence: Annotated[float, typer.Option(
            "--web-schema-min-confidence",
            min=0.0,
            max=1.0,
            help="Minimum schema confidence required before schema candidates are accepted.",
        )] = 0.75,
        web_schema_min_ingredients: Annotated[int, typer.Option(
            "--web-schema-min-ingredients",
            min=0,
            help="Minimum ingredient lines used in schema confidence scoring.",
        )] = 1,
        web_schema_min_instruction_steps: Annotated[int, typer.Option(
            "--web-schema-min-instruction-steps",
            min=0,
            help="Minimum instruction steps used in schema confidence scoring.",
        )] = 1,
        ingredient_text_fix_backend: Annotated[str, typer.Option(
            "--ingredient-text-fix-backend",
            hidden=True,
            help="Ingredient text-fix backend: none or ftfy.",
        )] = "none",
        ingredient_pre_normalize_mode: Annotated[str, typer.Option(
            "--ingredient-pre-normalize-mode",
            hidden=True,
            help="Ingredient pre-normalization mode: aggressive_v1.",
        )] = "aggressive_v1",
        ingredient_packaging_mode: Annotated[str, typer.Option(
            "--ingredient-packaging-mode",
            hidden=True,
            help="Ingredient packaging extraction mode: off or regex_v1.",
        )] = "off",
        ingredient_parser_backend: Annotated[str, typer.Option(
            "--ingredient-parser-backend",
            hidden=True,
            help=(
                "Ingredient parser backend: ingredient_parser_nlp, quantulum3_regex, "
                "or hybrid_nlp_then_quantulum3."
            ),
        )] = "ingredient_parser_nlp",
        ingredient_unit_canonicalizer: Annotated[str, typer.Option(
            "--ingredient-unit-canonicalizer",
            hidden=True,
            help="Ingredient unit canonicalizer: pint.",
        )] = "pint",
        ingredient_missing_unit_policy: Annotated[str, typer.Option(
            "--ingredient-missing-unit-policy",
            hidden=True,
            help="Policy when quantity has no unit: medium, null, or each.",
        )] = "null",
        p6_time_backend: Annotated[str, typer.Option(
            "--p6-time-backend",
            hidden=True,
            help=(
                "Priority 6 time extraction backend: regex_v1, quantulum3_v1, "
                "or hybrid_regex_quantulum3_v1."
            ),
        )] = "regex_v1",
        p6_time_total_strategy: Annotated[str, typer.Option(
            "--p6-time-total-strategy",
            hidden=True,
            help="Priority 6 step-time rollup strategy: sum_all_v1, max_v1, or selective_sum_v1.",
        )] = "sum_all_v1",
        p6_temperature_backend: Annotated[str, typer.Option(
            "--p6-temperature-backend",
            hidden=True,
            help=(
                "Priority 6 temperature extraction backend: regex_v1, quantulum3_v1, "
                "or hybrid_regex_quantulum3_v1."
            ),
        )] = "regex_v1",
        p6_temperature_unit_backend: Annotated[str, typer.Option(
            "--p6-temperature-unit-backend",
            hidden=True,
            help="Priority 6 temperature-unit conversion backend: builtin_v1 or pint_v1.",
        )] = "builtin_v1",
        p6_ovenlike_mode: Annotated[str, typer.Option(
            "--p6-ovenlike-mode",
            hidden=True,
            help="Priority 6 oven-like temperature classifier mode: keywords_v1 or off.",
        )] = "keywords_v1",
        p6_yield_mode: Annotated[str, typer.Option(
            "--p6-yield-mode",
            hidden=True,
            help="Priority 6 yield parser mode: scored_v1.",
        )] = "scored_v1",
        p6_emit_metadata_debug: Annotated[bool, typer.Option(
            "--p6-emit-metadata-debug/--no-p6-emit-metadata-debug",
            hidden=True,
            help="Write optional Priority 6 metadata debug sidecar artifacts.",
        )] = False,
        recipe_scorer_backend: Annotated[str, typer.Option(
            "--recipe-scorer-backend",
            hidden=True,
            help="Recipe-likeness scorer backend (default: heuristic_v1).",
        )] = "heuristic_v1",
        recipe_score_gold_min: Annotated[float, typer.Option(
            "--recipe-score-gold-min",
            min=0.0,
            max=1.0,
            hidden=True,
            help="Minimum recipe-likeness score for gold tier.",
        )] = 0.75,
        recipe_score_silver_min: Annotated[float, typer.Option(
            "--recipe-score-silver-min",
            min=0.0,
            max=1.0,
            hidden=True,
            help="Minimum recipe-likeness score for silver tier.",
        )] = 0.55,
        recipe_score_bronze_min: Annotated[float, typer.Option(
            "--recipe-score-bronze-min",
            min=0.0,
            max=1.0,
            hidden=True,
            help="Minimum recipe-likeness score for bronze tier (below is reject).",
        )] = 0.35,
        recipe_score_min_ingredient_lines: Annotated[int, typer.Option(
            "--recipe-score-min-ingredient-lines",
            min=0,
            hidden=True,
            help="Soft minimum ingredient lines used by scoring/gating.",
        )] = 1,
        recipe_score_min_instruction_lines: Annotated[int, typer.Option(
            "--recipe-score-min-instruction-lines",
            min=0,
            hidden=True,
            help="Soft minimum instruction lines used by scoring/gating.",
        )] = 1,
        llm_recipe_pipeline: Annotated[str, typer.Option(
            "--llm-recipe-pipeline",
            help=(
                "Recipe codex-farm parsing correction pipeline. "
                f"Values: off or {RECIPE_CODEX_FARM_PIPELINE_SHARD_V1}."
            ),
        )] = "off",
        llm_knowledge_pipeline: Annotated[str, typer.Option(
            "--llm-knowledge-pipeline",
            help=f"Optional knowledge LLM pipeline: off or {KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2}.",
        )] = "off",
        recipe_prompt_target_count: Annotated[int, typer.Option(
            "--recipe-prompt-target-count",
            min=1,
            hidden=True,
            help="Internal: preferred recipe shard count for Codex-backed benchmark runs.",
        )] = 5,
        knowledge_prompt_target_count: Annotated[int, typer.Option(
            "--knowledge-prompt-target-count",
            min=1,
            hidden=True,
            help="Internal: preferred knowledge shard count for Codex-backed benchmark runs.",
        )] = 5,
        knowledge_packet_input_char_budget: Annotated[int | None, typer.Option(
            "--knowledge-packet-input-char-budget",
            min=1,
            hidden=True,
            help="Internal: maximum prompt-side character budget per knowledge packet.",
        )] = 18000,
        knowledge_packet_output_char_budget: Annotated[int | None, typer.Option(
            "--knowledge-packet-output-char-budget",
            min=1,
            hidden=True,
            help="Internal: maximum response-side character budget per knowledge packet.",
        )] = 12000,
        knowledge_group_task_max_units: Annotated[int, typer.Option(
            "--knowledge-group-task-max-units",
            min=1,
            hidden=True,
            help="Internal: maximum knowledge-grouping units per task file.",
        )] = int(serialized_run_setting_default("knowledge_group_task_max_units")),
        knowledge_group_task_max_evidence_chars: Annotated[int, typer.Option(
            "--knowledge-group-task-max-evidence-chars",
            min=1,
            hidden=True,
            help="Internal: maximum serialized evidence chars per knowledge-grouping task file.",
        )] = int(
            serialized_run_setting_default("knowledge_group_task_max_evidence_chars")
        ),
        line_role_prompt_target_count: Annotated[int, typer.Option(
            "--line-role-prompt-target-count",
            min=1,
            hidden=True,
            help="Internal: preferred line-role shard count for Codex-backed benchmark runs.",
        )] = 5,
        allow_codex: Annotated[bool, typer.Option(
            "--allow-codex/--no-allow-codex",
            help=(
                "Required when this benchmark run enables Codex-backed recipe, line-role, "
                "or knowledge surfaces."
            ),
        )] = False,
        benchmark_codex_confirmation: str | None = typer.Option(
            None,
            "--benchmark-codex-confirmation",
            help=(
                "Required for live Codex-backed benchmark runs. Set to "
                "I_HAVE_EXPLICIT_USER_CONFIRMATION only after explicit positive user approval."
            ),
        ),
        atomic_block_splitter: Annotated[str, typer.Option(
            "--atomic-block-splitter",
            help=(
                "Optional deterministic mixed-block atomization mode for benchmark "
                "line-role experiments: off or atomic-v1."
            ),
        )] = "off",
        line_role_pipeline: Annotated[str, typer.Option(
            "--line-role-pipeline",
            help=(
                "Optional canonical line-role labeling pipeline for benchmark "
                f"experiments: off or {LINE_ROLE_PIPELINE_ROUTE_V2}."
            ),
        )] = "off",
        line_role_gated: Annotated[bool, typer.Option(
            "--line-role-gated/--no-line-role-gated",
            help=(
                "Enable Milestone-5 regression gates for canonical line-role runs. "
                "Fails the command when gates do not pass."
            ),
        )] = False,
        codex_farm_recipe_mode: Annotated[str, typer.Option(
            "--codex-farm-recipe-mode",
            help=(
                "Codex Exec recipe execution style: extract (default) or benchmark."
            ),
        )] = CODEX_FARM_RECIPE_MODE_EXTRACT,
        codex_farm_cmd: Annotated[str, typer.Option(
            "--codex-farm-cmd",
            help="Executable used for codex-farm calls when LLM recipe pipeline is enabled.",
        )] = "codex-farm",
        codex_farm_model: str | None = typer.Option(
            None,
            "--codex-farm-model",
            help="Optional Codex Exec model override (blank uses pipeline defaults).",
        ),
        codex_farm_reasoning_effort: Annotated[
            str | None,
            typer.Option(
                "--codex-farm-thinking-effort",
                "--codex-farm-reasoning-effort",
                help=(
                    "Codex Exec thinking effort override "
                    "(none, minimal, low, medium, high, xhigh). "
                    "Blank uses pipeline defaults."
                ),
            ),
        ] = None,
        codex_farm_root: Annotated[Path | None, typer.Option(
            "--codex-farm-root",
            help="Optional codex-farm pipeline-pack root. Defaults to <repo_root>/llm_pipelines.",
        )] = None,
        codex_farm_workspace_root: Annotated[Path | None, typer.Option(
            "--codex-farm-workspace-root",
            help=(
                "Optional workspace root passed to codex-farm. "
                "When omitted, codex-farm pipeline codex_cd_mode decides."
            ),
        )] = None,
        codex_farm_pipeline_knowledge: Annotated[str, typer.Option(
            "--codex-farm-pipeline-knowledge",
            hidden=True,
            help="Codex-farm pipeline id for non-recipe finalize.",
        )] = "recipe.knowledge.packet.v1",
        codex_farm_context_blocks: Annotated[int, typer.Option(
            "--codex-farm-context-blocks",
            min=0,
            help="Blocks before/after each recipe candidate included in pass-1 codex-farm bundles.",
        )] = 30,
        codex_farm_knowledge_context_blocks: Annotated[int, typer.Option(
            "--codex-farm-knowledge-context-blocks",
            min=0,
            help="Blocks before/after each non-recipe finalize chunk included as context in packet bundles.",
        )] = int(serialized_run_setting_default("codex_farm_knowledge_context_blocks")),
        codex_farm_failure_mode: Annotated[str, typer.Option(
            "--codex-farm-failure-mode",
            hidden=True,
            help="Behavior when codex-farm setup/invocation fails: fail or fallback.",
        )] = "fail",
        workspace_completion_quiescence_seconds: Annotated[float, typer.Option(
            "--workspace-completion-quiescence-seconds",
            min=0.1,
            hidden=True,
            help="Internal: quiet time required before a completed taskfile worker is treated as done.",
        )] = float(
            serialized_run_setting_default("workspace_completion_quiescence_seconds")
        ),
        completed_termination_grace_seconds: Annotated[float, typer.Option(
            "--completed-termination-grace-seconds",
            min=0.1,
            hidden=True,
            help="Internal: grace window before terminating a finished taskfile worker session.",
        )] = float(
            serialized_run_setting_default("completed_termination_grace_seconds")
        ),
        single_book_split_cache_mode: Annotated[str, typer.Option(
            "--single-book-split-cache-mode",
            help=(
                "Single-book split conversion cache mode: off or auto. "
                "Interactive paired runs use auto by default."
            ),
        )] = "off",
        single_book_split_cache_dir: Annotated[Path | None, typer.Option(
            "--single-book-split-cache-dir",
            help=(
                "Root directory for single-book split cache entries "
                "(JSON conversion payloads keyed by source+split inputs)."
            ),
        )] = None,
        single_book_split_cache_key: Annotated[str | None, typer.Option(
            "--single-book-split-cache-key",
            help="Internal: explicit single-book split cache key.",
            hidden=True,
        )] = None,
        single_book_split_cache_force: Annotated[bool, typer.Option(
            "--single-book-split-cache-force/--no-single-book-split-cache-force",
            help="Force rebuild of single-book split cache entry for this run.",
        )] = False,
        alignment_cache_dir: Annotated[Path | None, typer.Option(
            "--alignment-cache-dir",
            help="Internal: optional canonical alignment cache directory for benchmark runs.",
            hidden=True,
        )] = None,
    ) -> None:
        """Run benchmark eval against freeform gold, with optional upload step."""
        external_progress_callback = _BENCHMARK_PROGRESS_CALLBACK.get()
        suppress_summary = bool(_BENCHMARK_SUPPRESS_SUMMARY.get())
        suppress_spinner = bool(_BENCHMARK_SUPPRESS_SPINNER.get())
        suppress_dashboard_refresh = bool(_BENCHMARK_SUPPRESS_DASHBOARD_REFRESH.get())
        suppress_output_prune = bool(_BENCHMARK_SUPPRESS_OUTPUT_PRUNE.get()) or bool(
            _INTERACTIVE_CLI_ACTIVE.get()
        )
        split_phase_slots = _BENCHMARK_SPLIT_PHASE_SLOTS.get()
        split_phase_gate_dir_raw = _BENCHMARK_SPLIT_PHASE_GATE_DIR.get()
        split_phase_gate_dir = (
            Path(split_phase_gate_dir_raw) if split_phase_gate_dir_raw else None
        )
        split_phase_status_label = _BENCHMARK_SPLIT_PHASE_STATUS_LABEL.get()
        scheduler_event_callback = _BENCHMARK_SCHEDULER_EVENT_CALLBACK.get()

        def _emit_external_progress(message: str) -> None:
            _notify_progress_callback(external_progress_callback, message)

        selected_action = str(action or "run").strip().lower().replace("_", "-")
        if selected_action in {"", "run", "benchmark"}:
            selected_action = "run"
        elif selected_action == "compare":
            selected_action = "compare"
        else:
            _fail(
                f"Invalid labelstudio-benchmark action: {action!r}. "
                "Expected one of: run, compare."
            )

        if selected_action == "compare":
            if baseline is None or candidate is None:
                _fail(
                    "compare action requires both --baseline and --candidate."
                )
            labelstudio_benchmark_compare(
                baseline=baseline,
                candidate=candidate,
                out_dir=compare_out,
                fail_on_regression=bool(fail_on_regression),
            )
            return

        if baseline is not None or candidate is not None:
            _fail(
                "--baseline/--candidate are only valid with `labelstudio-benchmark compare`."
            )

        selected_epub_extractor = _normalize_epub_extractor(epub_extractor)
        selected_html_parser_version = _normalize_unstructured_html_parser_version(
            epub_unstructured_html_parser_version
        )
        selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
            epub_unstructured_preprocess_mode
        )
        selected_skip_headers_footers = bool(epub_unstructured_skip_headers_footers)
        selected_ocr_device = _normalize_ocr_device(ocr_device)
        selected_pdf_ocr_policy = _normalize_pdf_ocr_policy(pdf_ocr_policy)
        selected_pdf_column_gap_ratio = _normalize_pdf_column_gap_ratio(
            pdf_column_gap_ratio
        )
        fixed_bucket1_behavior = bucket1_fixed_behavior()
        selected_section_detector_backend = fixed_bucket1_behavior.section_detector_backend
        selected_multi_recipe_splitter = _normalize_multi_recipe_splitter(
            multi_recipe_splitter
        )
        selected_multi_recipe_trace = fixed_bucket1_behavior.multi_recipe_trace
        selected_multi_recipe_min_ingredient_lines = max(
            0, int(multi_recipe_min_ingredient_lines)
        )
        selected_multi_recipe_min_instruction_lines = max(
            0, int(multi_recipe_min_instruction_lines)
        )
        selected_multi_recipe_for_the_guardrail = bool(
            multi_recipe_for_the_guardrail
        )
        selected_instruction_step_segmentation_policy = (
            fixed_bucket1_behavior.instruction_step_segmentation_policy
        )
        selected_instruction_step_segmenter = (
            fixed_bucket1_behavior.instruction_step_segmenter
        )
        selected_web_schema_extractor = _normalize_web_schema_extractor(
            web_schema_extractor
        )
        selected_web_schema_normalizer = _normalize_web_schema_normalizer(
            web_schema_normalizer
        )
        selected_web_html_text_extractor = _normalize_web_html_text_extractor(
            web_html_text_extractor
        )
        selected_web_schema_policy = _normalize_web_schema_policy(web_schema_policy)
        selected_web_schema_min_confidence = max(
            0.0,
            min(1.0, float(web_schema_min_confidence)),
        )
        selected_web_schema_min_ingredients = max(0, int(web_schema_min_ingredients))
        selected_web_schema_min_instruction_steps = max(
            0,
            int(web_schema_min_instruction_steps),
        )
        selected_ingredient_text_fix_backend = _normalize_ingredient_text_fix_backend(
            ingredient_text_fix_backend
        )
        selected_ingredient_pre_normalize_mode = _normalize_ingredient_pre_normalize_mode(
            ingredient_pre_normalize_mode
        )
        selected_ingredient_packaging_mode = _normalize_ingredient_packaging_mode(
            ingredient_packaging_mode
        )
        selected_ingredient_parser_backend = _normalize_ingredient_parser_backend(
            ingredient_parser_backend
        )
        selected_ingredient_unit_canonicalizer = _normalize_ingredient_unit_canonicalizer(
            ingredient_unit_canonicalizer
        )
        selected_ingredient_missing_unit_policy = _normalize_ingredient_missing_unit_policy(
            ingredient_missing_unit_policy
        )
        selected_p6_time_backend = _normalize_p6_time_backend(p6_time_backend)
        selected_p6_time_total_strategy = _normalize_p6_time_total_strategy(
            p6_time_total_strategy
        )
        selected_p6_temperature_backend = _normalize_p6_temperature_backend(
            p6_temperature_backend
        )
        selected_p6_temperature_unit_backend = _normalize_p6_temperature_unit_backend(
            p6_temperature_unit_backend
        )
        selected_p6_ovenlike_mode = _normalize_p6_ovenlike_mode(p6_ovenlike_mode)
        selected_p6_yield_mode = _normalize_p6_yield_mode(p6_yield_mode)
        selected_p6_emit_metadata_debug = fixed_bucket1_behavior.p6_emit_metadata_debug
        selected_recipe_scorer_backend = (
            str(recipe_scorer_backend or "heuristic_v1").strip() or "heuristic_v1"
        )
        selected_recipe_score_gold_min = max(0.0, min(1.0, float(recipe_score_gold_min)))
        selected_recipe_score_silver_min = max(
            0.0, min(1.0, float(recipe_score_silver_min))
        )
        selected_recipe_score_bronze_min = max(
            0.0, min(1.0, float(recipe_score_bronze_min))
        )
        selected_recipe_score_min_ingredient_lines = max(
            0, int(recipe_score_min_ingredient_lines)
        )
        selected_recipe_score_min_instruction_lines = max(
            0, int(recipe_score_min_instruction_lines)
        )
        selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
        selected_llm_knowledge_pipeline = _normalize_llm_knowledge_pipeline(
            llm_knowledge_pipeline
        )
        selected_atomic_block_splitter = _normalize_atomic_block_splitter(
            atomic_block_splitter
        )
        selected_line_role_pipeline = _normalize_line_role_pipeline(line_role_pipeline)
        selected_codex_farm_recipe_mode = _normalize_codex_farm_recipe_mode(
            codex_farm_recipe_mode
        )
        selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
            codex_farm_failure_mode
        )
        selected_codex_farm_model = (
            str(codex_farm_model or "").strip() or None
        )
        try:
            selected_codex_farm_reasoning_effort = (
                normalize_codex_reasoning_effort(codex_farm_reasoning_effort)
                if codex_farm_reasoning_effort is not None
                else None
            )
        except ValueError as exc:
            _fail(f"--codex-farm-thinking-effort invalid: {exc}")
        selected_codex_farm_pipeline_knowledge = (
            fixed_bucket1_behavior.codex_farm_pipeline_knowledge
        )
        selected_eval_mode = _normalize_benchmark_eval_mode(eval_mode)
        if selected_eval_mode == BENCHMARK_EVAL_MODE_STAGE_BLOCKS:
            # Line-role/atomic paths are canonical-text benchmark features.
            selected_atomic_block_splitter = "off"
            selected_line_role_pipeline = "off"
        benchmark_codex_confirmation = _unwrap_typer_option_default(
            benchmark_codex_confirmation
        )
        benchmark_codex_execution = resolve_codex_execution_policy(
            "labelstudio_benchmark",
            {
                "llm_recipe_pipeline": selected_llm_recipe_pipeline,
                "llm_knowledge_pipeline": selected_llm_knowledge_pipeline,
                "line_role_pipeline": selected_line_role_pipeline,
            },
            execution_policy_mode="execute",
            allow_codex=bool(allow_codex),
        )
        if benchmark_codex_execution.blocked:
            codex_surfaces = (
                ", ".join(benchmark_codex_execution.surface.codex_surfaces) or "unknown"
            )
            _fail(
                "labelstudio-benchmark enables Codex-backed surfaces "
                f"({codex_surfaces}) and requires explicit approval. "
                "Re-run with --allow-codex only after explicit positive user approval."
            )
        _print_codex_decision(benchmark_codex_execution)
        _enforce_live_labelstudio_benchmark_codex_guardrails(
            any_codex_enabled=benchmark_codex_execution.surface.any_codex_enabled,
            benchmark_codex_confirmation=benchmark_codex_confirmation,
        )
        selected_gold_adaptation_mode = _normalize_gold_adaptation_mode(
            gold_adaptation_mode
        )
        selected_gold_adaptation_min_coverage = max(
            0.0,
            min(1.0, float(gold_adaptation_min_coverage)),
        )
        selected_gold_adaptation_max_ambiguous = max(
            0,
            int(gold_adaptation_max_ambiguous),
        )
        selected_sequence_matcher = fixed_bucket1_behavior.benchmark_sequence_matcher
        selected_single_book_split_cache_mode = _normalize_single_book_split_cache_mode(
            single_book_split_cache_mode
        )
        selected_single_book_split_cache_dir = (
            single_book_split_cache_dir.expanduser()
            if single_book_split_cache_dir is not None
            else None
        )
        selected_single_book_split_cache_key = (
            str(single_book_split_cache_key or "").strip() or None
        )
        if selected_single_book_split_cache_mode == "off":
            selected_single_book_split_cache_dir = None
            selected_single_book_split_cache_key = None

        predictions_in_path = predictions_in.expanduser() if predictions_in is not None else None
        predictions_out_path = (
            predictions_out.expanduser() if predictions_out is not None else None
        )
        if predictions_in_path is not None and predictions_out_path is not None:
            _fail("Cannot combine --predictions-in and --predictions-out in one run.")

        prediction_record_input: list[PredictionRecord] = []
        prediction_record_source: Path | None = None
        if predictions_in_path is not None:
            try:
                prediction_record_input = list(read_prediction_records(predictions_in_path))
            except Exception as exc:  # noqa: BLE001
                _fail(f"Unable to load prediction record from {predictions_in_path}: {exc}")
            prediction_record_source = _prediction_record_source_file_hint(
                prediction_record_input
            )

        should_generate_predictions = predictions_in_path is None
        should_upload_predictions = should_generate_predictions and not no_upload
        if not should_generate_predictions:
            selected_single_book_split_cache_mode = "off"
            selected_single_book_split_cache_dir = None
            selected_single_book_split_cache_key = None

        if should_upload_predictions and not write_label_studio_tasks:
            _fail("--no-write-labelstudio-tasks can only be used with --no-upload.")

        url: str | None = None
        api_key: str | None = None
        if should_upload_predictions:
            _require_labelstudio_write_consent(allow_labelstudio_write)
            url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)

        resolved_inputs = _resolve_benchmark_gold_and_source(
            gold_spans=gold_spans,
            source_file=source_file or prediction_record_source,
            output_dir=output_dir,
            allow_cancel=False,
        )
        if resolved_inputs is None:
            _fail("Benchmark cancelled.")
        selected_gold, selected_source = resolved_inputs

        if eval_output_dir is None:
            timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
            eval_output_dir = _golden_benchmark_root() / timestamp
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        # Keep benchmark prediction scratch inside the resolved eval root so one
        # benchmark session does not spill sibling timestamp folders.
        benchmark_prediction_output_dir = eval_output_dir
        if selected_single_book_split_cache_mode != "off":
            if selected_single_book_split_cache_dir is None:
                selected_single_book_split_cache_dir = eval_output_dir / ".split-cache"
            if selected_single_book_split_cache_key is None:
                try:
                    split_cache_source_hash = compute_file_hash(selected_source)
                except Exception:  # noqa: BLE001
                    split_cache_source_hash = None
                split_cache_run_settings = build_run_settings(
                    workers=workers,
                    pdf_split_workers=pdf_split_workers,
                    epub_split_workers=epub_split_workers,
                    pdf_pages_per_job=pdf_pages_per_job,
                    epub_spine_items_per_job=epub_spine_items_per_job,
                    epub_extractor=selected_epub_extractor,
                    epub_unstructured_html_parser_version=selected_html_parser_version,
                    epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
                    epub_unstructured_preprocess_mode=selected_preprocess_mode,
                    epub_title_backtrack_limit=epub_title_backtrack_limit,
                    epub_anchor_title_backtrack_limit=epub_anchor_title_backtrack_limit,
                    epub_ingredient_run_window=epub_ingredient_run_window,
                    epub_ingredient_header_window=epub_ingredient_header_window,
                    epub_title_max_length=epub_title_max_length,
                    ocr_device=selected_ocr_device,
                    pdf_ocr_policy=selected_pdf_ocr_policy,
                    ocr_batch_size=ocr_batch_size,
                    pdf_column_gap_ratio=selected_pdf_column_gap_ratio,
                    warm_models=warm_models,
                    multi_recipe_splitter=selected_multi_recipe_splitter,
                    multi_recipe_min_ingredient_lines=selected_multi_recipe_min_ingredient_lines,
                    multi_recipe_min_instruction_lines=selected_multi_recipe_min_instruction_lines,
                    multi_recipe_for_the_guardrail=selected_multi_recipe_for_the_guardrail,
                    web_schema_extractor=selected_web_schema_extractor,
                    web_schema_normalizer=selected_web_schema_normalizer,
                    web_html_text_extractor=selected_web_html_text_extractor,
                    web_schema_policy=selected_web_schema_policy,
                    web_schema_min_confidence=selected_web_schema_min_confidence,
                    web_schema_min_ingredients=selected_web_schema_min_ingredients,
                    web_schema_min_instruction_steps=selected_web_schema_min_instruction_steps,
                    ingredient_text_fix_backend=selected_ingredient_text_fix_backend,
                    ingredient_pre_normalize_mode=selected_ingredient_pre_normalize_mode,
                    ingredient_packaging_mode=selected_ingredient_packaging_mode,
                    ingredient_parser_backend=selected_ingredient_parser_backend,
                    ingredient_unit_canonicalizer=selected_ingredient_unit_canonicalizer,
                    ingredient_missing_unit_policy=selected_ingredient_missing_unit_policy,
                    p6_time_backend=selected_p6_time_backend,
                    p6_time_total_strategy=selected_p6_time_total_strategy,
                    p6_temperature_backend=selected_p6_temperature_backend,
                    p6_temperature_unit_backend=selected_p6_temperature_unit_backend,
                    p6_ovenlike_mode=selected_p6_ovenlike_mode,
                    p6_yield_mode=selected_p6_yield_mode,
                    recipe_scorer_backend=selected_recipe_scorer_backend,
                    recipe_score_gold_min=selected_recipe_score_gold_min,
                    recipe_score_silver_min=selected_recipe_score_silver_min,
                    recipe_score_bronze_min=selected_recipe_score_bronze_min,
                    recipe_score_min_ingredient_lines=selected_recipe_score_min_ingredient_lines,
                    recipe_score_min_instruction_lines=selected_recipe_score_min_instruction_lines,
                    llm_recipe_pipeline=selected_llm_recipe_pipeline,
                    llm_knowledge_pipeline=selected_llm_knowledge_pipeline,
                    atomic_block_splitter=selected_atomic_block_splitter,
                    line_role_pipeline=selected_line_role_pipeline,
                    knowledge_group_task_max_units=knowledge_group_task_max_units,
                    knowledge_group_task_max_evidence_chars=(
                        knowledge_group_task_max_evidence_chars
                    ),
                    codex_farm_cmd=codex_farm_cmd,
                    codex_farm_model=selected_codex_farm_model,
                    codex_farm_reasoning_effort=selected_codex_farm_reasoning_effort,
                    codex_farm_root=codex_farm_root,
                    codex_farm_workspace_root=codex_farm_workspace_root,
                    codex_farm_context_blocks=codex_farm_context_blocks,
                    codex_farm_knowledge_context_blocks=codex_farm_knowledge_context_blocks,
                    codex_farm_recipe_mode=selected_codex_farm_recipe_mode,
                    codex_farm_failure_mode=selected_codex_farm_failure_mode,
                    workspace_completion_quiescence_seconds=(
                        workspace_completion_quiescence_seconds
                    ),
                    completed_termination_grace_seconds=(
                        completed_termination_grace_seconds
                    ),
                    all_epub=selected_source.suffix.lower() == ".epub",
                    effective_workers=compute_effective_workers(
                        workers=workers,
                        epub_split_workers=epub_split_workers,
                        epub_extractor=selected_epub_extractor,
                        all_epub=selected_source.suffix.lower() == ".epub",
                    ),
                )
                selected_single_book_split_cache_key = _build_single_book_split_cache_key(
                    source_file=selected_source,
                    source_hash=split_cache_source_hash,
                    pipeline=pipeline,
                    run_settings=split_cache_run_settings,
                )

        if warm_models:
            with console.status("[bold cyan]Warming models...[/bold cyan]", spinner="dots"):
                _warm_all_models(ocr_device=selected_ocr_device)

        benchmark_started = time.monotonic()
        import_result: dict[str, Any]
        pred_run: Path | None = None
        pred_context: PredRunContext
        stage_predictions_path: Path
        extracted_archive_path: Path
        prediction_phase_seconds = 0.0
        prewarmed_canonical_paths: dict[str, Path] | None = None
        prediction_records_output: list[PredictionRecord] = []
        pipelined_replay_bundle: BenchmarkPredictionBundle | None = None
        codex_exec_prompt_response_log_path: Path | None = None
        single_book_split_cache_metadata: dict[str, Any] | None = None
        single_book_split_cache_run_config: dict[str, Any] | None = None

        try:
            if should_generate_predictions:
                with _temporary_epub_extractor(selected_epub_extractor):
                    with _temporary_epub_unstructured_options(
                        html_parser_version=selected_html_parser_version,
                        skip_headers_footers=selected_skip_headers_footers,
                        preprocess_mode=selected_preprocess_mode,
                    ):
                        def _run_prediction_generation(
                            callback: Callable[[str], None] | None,
                        ) -> dict[str, Any]:
                            if no_upload:
                                return generate_pred_run_artifacts(
                                    path=selected_source,
                                    output_dir=benchmark_prediction_output_dir,
                                    pipeline=pipeline,
                                    segment_blocks=40,
                                    segment_overlap=5,
                                    limit=None,
                                    sample=None,
                                    workers=workers,
                                    pdf_split_workers=pdf_split_workers,
                                    epub_split_workers=epub_split_workers,
                                    pdf_pages_per_job=pdf_pages_per_job,
                                    epub_spine_items_per_job=epub_spine_items_per_job,
                                    epub_extractor=selected_epub_extractor,
                                    epub_unstructured_html_parser_version=selected_html_parser_version,
                                    epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
                                    epub_unstructured_preprocess_mode=selected_preprocess_mode,
                                    epub_title_backtrack_limit=epub_title_backtrack_limit,
                                    epub_anchor_title_backtrack_limit=(
                                        epub_anchor_title_backtrack_limit
                                    ),
                                    epub_ingredient_run_window=epub_ingredient_run_window,
                                    epub_ingredient_header_window=(
                                        epub_ingredient_header_window
                                    ),
                                    epub_title_max_length=epub_title_max_length,
                                    ocr_device=selected_ocr_device,
                                    pdf_ocr_policy=selected_pdf_ocr_policy,
                                    ocr_batch_size=ocr_batch_size,
                                    pdf_column_gap_ratio=selected_pdf_column_gap_ratio,
                                    warm_models=warm_models,
                                    section_detector_backend=selected_section_detector_backend,
                                    multi_recipe_splitter=selected_multi_recipe_splitter,
                                    multi_recipe_trace=selected_multi_recipe_trace,
                                    multi_recipe_min_ingredient_lines=(
                                        selected_multi_recipe_min_ingredient_lines
                                    ),
                                    multi_recipe_min_instruction_lines=(
                                        selected_multi_recipe_min_instruction_lines
                                    ),
                                    multi_recipe_for_the_guardrail=(
                                        selected_multi_recipe_for_the_guardrail
                                    ),
                                    instruction_step_segmentation_policy=(
                                        selected_instruction_step_segmentation_policy
                                    ),
                                    instruction_step_segmenter=selected_instruction_step_segmenter,
                                    web_schema_extractor=selected_web_schema_extractor,
                                    web_schema_normalizer=selected_web_schema_normalizer,
                                    web_html_text_extractor=selected_web_html_text_extractor,
                                    web_schema_policy=selected_web_schema_policy,
                                    web_schema_min_confidence=selected_web_schema_min_confidence,
                                    web_schema_min_ingredients=selected_web_schema_min_ingredients,
                                    web_schema_min_instruction_steps=selected_web_schema_min_instruction_steps,
                                    ingredient_text_fix_backend=selected_ingredient_text_fix_backend,
                                    ingredient_pre_normalize_mode=selected_ingredient_pre_normalize_mode,
                                    ingredient_packaging_mode=selected_ingredient_packaging_mode,
                                    ingredient_parser_backend=selected_ingredient_parser_backend,
                                    ingredient_unit_canonicalizer=selected_ingredient_unit_canonicalizer,
                                    ingredient_missing_unit_policy=selected_ingredient_missing_unit_policy,
                                    p6_time_backend=selected_p6_time_backend,
                                    p6_time_total_strategy=selected_p6_time_total_strategy,
                                    p6_temperature_backend=selected_p6_temperature_backend,
                                    p6_temperature_unit_backend=selected_p6_temperature_unit_backend,
                                    p6_ovenlike_mode=selected_p6_ovenlike_mode,
                                    p6_yield_mode=selected_p6_yield_mode,
                                    p6_emit_metadata_debug=selected_p6_emit_metadata_debug,
                                    recipe_scorer_backend=selected_recipe_scorer_backend,
                                    recipe_score_gold_min=selected_recipe_score_gold_min,
                                    recipe_score_silver_min=selected_recipe_score_silver_min,
                                    recipe_score_bronze_min=selected_recipe_score_bronze_min,
                                    recipe_score_min_ingredient_lines=selected_recipe_score_min_ingredient_lines,
                                    recipe_score_min_instruction_lines=selected_recipe_score_min_instruction_lines,
                                    llm_recipe_pipeline=selected_llm_recipe_pipeline,
                                    llm_knowledge_pipeline=selected_llm_knowledge_pipeline,
                                    recipe_prompt_target_count=recipe_prompt_target_count,
                                    knowledge_prompt_target_count=knowledge_prompt_target_count,
                                    knowledge_packet_input_char_budget=(
                                        knowledge_packet_input_char_budget
                                    ),
                                    knowledge_packet_output_char_budget=(
                                        knowledge_packet_output_char_budget
                                    ),
                                    knowledge_group_task_max_units=(
                                        knowledge_group_task_max_units
                                    ),
                                    knowledge_group_task_max_evidence_chars=(
                                        knowledge_group_task_max_evidence_chars
                                    ),
                                    atomic_block_splitter=selected_atomic_block_splitter,
                                    line_role_pipeline=selected_line_role_pipeline,
                                    line_role_prompt_target_count=line_role_prompt_target_count,
                                    codex_farm_cmd=codex_farm_cmd,
                                    codex_farm_model=selected_codex_farm_model,
                                    codex_farm_reasoning_effort=selected_codex_farm_reasoning_effort,
                                    codex_farm_root=codex_farm_root,
                                    codex_farm_workspace_root=codex_farm_workspace_root,
                                    codex_farm_pipeline_knowledge=(
                                        selected_codex_farm_pipeline_knowledge
                                    ),
                                    codex_farm_context_blocks=codex_farm_context_blocks,
                                    codex_farm_knowledge_context_blocks=(
                                        codex_farm_knowledge_context_blocks
                                    ),
                                    codex_farm_recipe_mode=selected_codex_farm_recipe_mode,
                                    codex_farm_failure_mode=selected_codex_farm_failure_mode,
                                    workspace_completion_quiescence_seconds=(
                                        workspace_completion_quiescence_seconds
                                    ),
                                    completed_termination_grace_seconds=(
                                        completed_termination_grace_seconds
                                    ),
                                    allow_codex=bool(allow_codex),
                                    codex_execution_policy="execute",
                                    processed_output_root=processed_output_dir,
                                    write_markdown=write_markdown,
                                    write_label_studio_tasks=write_label_studio_tasks,
                                    split_phase_slots=split_phase_slots,
                                    split_phase_gate_dir=split_phase_gate_dir,
                                    split_phase_status_label=split_phase_status_label,
                                    single_book_split_cache_mode=(
                                        selected_single_book_split_cache_mode
                                    ),
                                    single_book_split_cache_dir=(
                                        selected_single_book_split_cache_dir
                                    ),
                                    single_book_split_cache_key=(
                                        selected_single_book_split_cache_key
                                    ),
                                    single_book_split_cache_force=(
                                        single_book_split_cache_force
                                    ),
                                    scheduler_event_callback=scheduler_event_callback,
                                    progress_callback=callback,
                                    run_manifest_kind="bench_pred_run",
                                    run_root_override=eval_output_dir,
                                    mirror_stage_artifacts_into_run_root=False,
                                )
                            return run_labelstudio_import(
                                path=selected_source,
                                output_dir=benchmark_prediction_output_dir,
                                pipeline=pipeline,
                                project_name=project_name,
                                segment_blocks=40,
                                segment_overlap=5,
                                overwrite=overwrite,
                                resume=not overwrite,
                                label_studio_url=url or "",
                                label_studio_api_key=api_key or "",
                                limit=None,
                                sample=None,
                                progress_callback=callback,
                                workers=workers,
                                pdf_split_workers=pdf_split_workers,
                                epub_split_workers=epub_split_workers,
                                pdf_pages_per_job=pdf_pages_per_job,
                                epub_spine_items_per_job=epub_spine_items_per_job,
                                epub_extractor=selected_epub_extractor,
                                epub_unstructured_html_parser_version=selected_html_parser_version,
                                epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
                                epub_unstructured_preprocess_mode=selected_preprocess_mode,
                                epub_title_backtrack_limit=epub_title_backtrack_limit,
                                epub_anchor_title_backtrack_limit=(
                                    epub_anchor_title_backtrack_limit
                                ),
                                epub_ingredient_run_window=epub_ingredient_run_window,
                                epub_ingredient_header_window=epub_ingredient_header_window,
                                epub_title_max_length=epub_title_max_length,
                                ocr_device=selected_ocr_device,
                                pdf_ocr_policy=selected_pdf_ocr_policy,
                                ocr_batch_size=ocr_batch_size,
                                pdf_column_gap_ratio=selected_pdf_column_gap_ratio,
                                warm_models=warm_models,
                                section_detector_backend=selected_section_detector_backend,
                                multi_recipe_splitter=selected_multi_recipe_splitter,
                                multi_recipe_trace=selected_multi_recipe_trace,
                                multi_recipe_min_ingredient_lines=(
                                    selected_multi_recipe_min_ingredient_lines
                                ),
                                multi_recipe_min_instruction_lines=(
                                    selected_multi_recipe_min_instruction_lines
                                ),
                                multi_recipe_for_the_guardrail=(
                                    selected_multi_recipe_for_the_guardrail
                                ),
                                instruction_step_segmentation_policy=(
                                    selected_instruction_step_segmentation_policy
                                ),
                                instruction_step_segmenter=selected_instruction_step_segmenter,
                                web_schema_extractor=selected_web_schema_extractor,
                                web_schema_normalizer=selected_web_schema_normalizer,
                                web_html_text_extractor=selected_web_html_text_extractor,
                                web_schema_policy=selected_web_schema_policy,
                                web_schema_min_confidence=selected_web_schema_min_confidence,
                                web_schema_min_ingredients=selected_web_schema_min_ingredients,
                                web_schema_min_instruction_steps=selected_web_schema_min_instruction_steps,
                                ingredient_text_fix_backend=selected_ingredient_text_fix_backend,
                                ingredient_pre_normalize_mode=selected_ingredient_pre_normalize_mode,
                                ingredient_packaging_mode=selected_ingredient_packaging_mode,
                                ingredient_parser_backend=selected_ingredient_parser_backend,
                                ingredient_unit_canonicalizer=selected_ingredient_unit_canonicalizer,
                                ingredient_missing_unit_policy=selected_ingredient_missing_unit_policy,
                                p6_time_backend=selected_p6_time_backend,
                                p6_time_total_strategy=selected_p6_time_total_strategy,
                                p6_temperature_backend=selected_p6_temperature_backend,
                                p6_temperature_unit_backend=selected_p6_temperature_unit_backend,
                                p6_ovenlike_mode=selected_p6_ovenlike_mode,
                                p6_yield_mode=selected_p6_yield_mode,
                                p6_emit_metadata_debug=selected_p6_emit_metadata_debug,
                                recipe_scorer_backend=selected_recipe_scorer_backend,
                                recipe_score_gold_min=selected_recipe_score_gold_min,
                                recipe_score_silver_min=selected_recipe_score_silver_min,
                                recipe_score_bronze_min=selected_recipe_score_bronze_min,
                                recipe_score_min_ingredient_lines=selected_recipe_score_min_ingredient_lines,
                                recipe_score_min_instruction_lines=selected_recipe_score_min_instruction_lines,
                                llm_recipe_pipeline=selected_llm_recipe_pipeline,
                                llm_knowledge_pipeline=selected_llm_knowledge_pipeline,
                                recipe_prompt_target_count=recipe_prompt_target_count,
                                knowledge_prompt_target_count=knowledge_prompt_target_count,
                                knowledge_packet_input_char_budget=(
                                    knowledge_packet_input_char_budget
                                ),
                                knowledge_packet_output_char_budget=(
                                    knowledge_packet_output_char_budget
                                ),
                                knowledge_group_task_max_units=(
                                    knowledge_group_task_max_units
                                ),
                                knowledge_group_task_max_evidence_chars=(
                                    knowledge_group_task_max_evidence_chars
                                ),
                                atomic_block_splitter=selected_atomic_block_splitter,
                                line_role_pipeline=selected_line_role_pipeline,
                                line_role_prompt_target_count=line_role_prompt_target_count,
                                codex_farm_cmd=codex_farm_cmd,
                                codex_farm_model=selected_codex_farm_model,
                                codex_farm_reasoning_effort=selected_codex_farm_reasoning_effort,
                                codex_farm_root=codex_farm_root,
                                codex_farm_workspace_root=codex_farm_workspace_root,
                                codex_farm_pipeline_knowledge=(
                                    selected_codex_farm_pipeline_knowledge
                                ),
                                codex_farm_context_blocks=codex_farm_context_blocks,
                                codex_farm_knowledge_context_blocks=(
                                    codex_farm_knowledge_context_blocks
                                ),
                                codex_farm_recipe_mode=selected_codex_farm_recipe_mode,
                                codex_farm_failure_mode=selected_codex_farm_failure_mode,
                                workspace_completion_quiescence_seconds=(
                                    workspace_completion_quiescence_seconds
                                ),
                                completed_termination_grace_seconds=(
                                    completed_termination_grace_seconds
                                ),
                                allow_codex=bool(allow_codex),
                                processed_output_root=processed_output_dir,
                                split_phase_slots=split_phase_slots,
                                split_phase_gate_dir=split_phase_gate_dir,
                                split_phase_status_label=split_phase_status_label,
                                single_book_split_cache_mode=(
                                    selected_single_book_split_cache_mode
                                ),
                                single_book_split_cache_dir=(
                                    selected_single_book_split_cache_dir
                                ),
                                single_book_split_cache_key=(
                                    selected_single_book_split_cache_key
                                ),
                                single_book_split_cache_force=(
                                    single_book_split_cache_force
                                ),
                                scheduler_event_callback=scheduler_event_callback,
                                auto_project_name_on_scope_mismatch=True,
                                allow_labelstudio_write=True,
                                run_root_override=eval_output_dir,
                                mirror_stage_artifacts_into_run_root=False,
                            )

                        def _run_prediction_stage_bundle() -> BenchmarkPredictionBundle:
                            prediction_phase_started = time.monotonic()
                            if suppress_spinner:
                                _emit_external_progress(
                                    f"Generating prediction tasks for {selected_source.name}..."
                                )
                                callback = (
                                    _emit_external_progress
                                    if external_progress_callback is not None
                                    else None
                                )
                                stage_import_result = _run_prediction_generation(callback)
                            else:
                                def _run_with_status(
                                    update_progress: Callable[[str], None],
                                ) -> dict[str, Any]:
                                    if external_progress_callback is None:
                                        return _run_prediction_generation(update_progress)

                                    def _combined_progress(message: str) -> None:
                                        update_progress(message)
                                        _emit_external_progress(message)

                                    return _run_prediction_generation(_combined_progress)

                                stage_import_result = _run_with_progress_status(
                                    initial_status=(
                                        f"Generating prediction tasks for {selected_source.name}..."
                                    ),
                                    progress_prefix=f"Benchmark import ({selected_source.name})",
                                    run=_run_with_status,
                                    telemetry_path=(
                                        eval_output_dir
                                        / "processing_timeseries_prediction.jsonl"
                                    ),
                                )
                            stage_prediction_seconds = max(
                                0.0, time.monotonic() - prediction_phase_started
                            )
                            return _build_prediction_bundle_from_import_result(
                                import_result=stage_import_result,
                                prediction_phase_seconds=stage_prediction_seconds,
                            )

                        def _prewarm_evaluation_inputs() -> dict[str, Path] | None:
                            if selected_eval_mode != BENCHMARK_EVAL_MODE_CANONICAL_TEXT:
                                return None
                            canonical_paths = ensure_canonical_gold_artifacts(
                                export_root=selected_gold.parent
                            )
                            return {
                                "canonical_text_path": Path(
                                    canonical_paths["canonical_text_path"]
                                ),
                                "canonical_span_labels_path": Path(
                                    canonical_paths["canonical_span_labels_path"]
                                ),
                            }

                        pipelined_result = run_pipelined(
                            run_prediction_bundle=_run_prediction_stage_bundle,
                            prewarm_evaluation_inputs=_prewarm_evaluation_inputs,
                            selected_source=selected_source,
                            eval_output_dir=eval_output_dir,
                        )
                        prediction_bundle = pipelined_result.prediction_bundle
                        prediction_records_output = pipelined_result.prediction_records
                        prewarmed_canonical_paths = (
                            pipelined_result.prewarmed_canonical_paths
                        )
                        pipelined_replay_bundle = pipelined_result.replay_bundle
            else:
                if predictions_in_path is None:
                    _fail("Prediction record input is required.")
                prediction_bundle = _build_prediction_bundle_from_records(
                    predictions_in=predictions_in_path,
                    prediction_records=prediction_record_input,
                    replay_output_dir=eval_output_dir / ".prediction-record-replay",
                )
                prediction_records_output = list(prediction_record_input)

            import_result = prediction_bundle.import_result
            imported_split_cache_payload = import_result.get("single_book_split_cache")
            if isinstance(imported_split_cache_payload, dict):
                single_book_split_cache_metadata = dict(imported_split_cache_payload)
                _append_processing_timeseries_marker(
                    telemetry_path=(
                        eval_output_dir / "processing_timeseries_prediction.jsonl"
                    ),
                    event="single_book_split_cache",
                    payload={
                        "single_book_split_cache": single_book_split_cache_metadata
                    },
                )

            pred_run = prediction_bundle.pred_run
            pred_context = prediction_bundle.pred_context
            stage_predictions_path = prediction_bundle.stage_predictions_path
            extracted_archive_path = prediction_bundle.extracted_archive_path
            codex_exec_prompt_response_log_path = (
                llm_prompt_artifacts.build_codex_farm_prompt_response_log(
                    pred_run=pred_run,
                    eval_output_dir=eval_output_dir,
                    repo_root=REPO_ROOT,
                )
            )
            prediction_phase_seconds = prediction_bundle.prediction_phase_seconds
            evaluation_stage_predictions_path = stage_predictions_path
            evaluation_extracted_archive_path = extracted_archive_path
            if pipelined_replay_bundle is not None:
                evaluation_stage_predictions_path = (
                    pipelined_replay_bundle.stage_predictions_path
                )
                evaluation_extracted_archive_path = (
                    pipelined_replay_bundle.extracted_archive_path
                )

            if predictions_out_path is not None:
                write_prediction_records(predictions_out_path, prediction_records_output)
        except KeyboardInterrupt:
            _finalize_interrupted_benchmark_run(
                eval_output_dir=eval_output_dir,
                source_path=selected_source,
                source_hash=None,
                pred_run=pred_run,
                processed_run_root=None,
                selected_gold=selected_gold,
                selected_eval_mode=selected_eval_mode,
                predictions_in_path=predictions_in_path,
                predictions_out_path=predictions_out_path,
                should_upload_predictions=should_upload_predictions,
                write_markdown=write_markdown,
                write_label_studio_tasks=write_label_studio_tasks,
                phase="prediction",
            )
            if not suppress_summary:
                typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
            return
        except Exception as exc:  # noqa: BLE001
            if suppress_summary:
                raise
            _fail(str(exc))

        if (
            selected_single_book_split_cache_mode != "off"
            or single_book_split_cache_metadata is not None
        ):
            single_book_split_cache_run_config = {
                "enabled": selected_single_book_split_cache_mode != "off",
                "mode": selected_single_book_split_cache_mode,
                "key": selected_single_book_split_cache_key,
                "dir": (
                    str(selected_single_book_split_cache_dir)
                    if selected_single_book_split_cache_dir is not None
                    else None
                ),
                "force": bool(single_book_split_cache_force),
                "hit": bool(
                    isinstance(single_book_split_cache_metadata, dict)
                    and single_book_split_cache_metadata.get("hit")
                ),
                "source_hash": (
                    str(
                        (single_book_split_cache_metadata or {}).get("source_hash")
                        or ""
                    ).strip()
                    or None
                ),
                "conversion_seconds": _report_optional_metric(
                    (single_book_split_cache_metadata or {}).get("conversion_seconds")
                ),
            }

        prediction_load_seconds: float | None = None
        gold_load_seconds: float | None = None
        eval_profile_min_seconds = _benchmark_eval_profile_min_seconds()
        eval_profile_top_n = _benchmark_eval_profile_top_n()
        eval_profiler: cProfile.Profile | None = None
        if eval_profile_min_seconds is not None:
            eval_profiler = cProfile.Profile()
        evaluation_started = time.monotonic()
        eval_scope = selected_eval_mode
        _notify_benchmark_scheduler_event(
            "evaluate_started",
            eval_mode=selected_eval_mode,
        )
        eval_status_message = (
            f"Evaluating predictions using {selected_eval_mode} scoring..."
        )

        def _evaluate_selected_mode() -> tuple[dict[str, Any], Callable[[dict[str, Any]], str]]:
            with _temporary_benchmark_sequence_matcher(selected_sequence_matcher):
                return evaluate_stage(
                    selected_eval_mode=selected_eval_mode,
                    selected_gold=selected_gold,
                    eval_output_dir=eval_output_dir,
                    stage_predictions_path=evaluation_stage_predictions_path,
                    extracted_archive_path=evaluation_extracted_archive_path,
                    alignment_cache_dir=alignment_cache_dir,
                    prewarmed_canonical_paths=prewarmed_canonical_paths,
                    gold_adaptation_mode=selected_gold_adaptation_mode,
                    gold_adaptation_min_coverage=selected_gold_adaptation_min_coverage,
                    gold_adaptation_max_ambiguous=selected_gold_adaptation_max_ambiguous,
                )

        if eval_profiler is not None:
            eval_profiler.enable()
        try:
            if suppress_spinner:
                _emit_external_progress(eval_status_message)
                eval_result, eval_report_formatter = _evaluate_selected_mode()
            else:
                def _run_eval_with_status(
                    update_progress: Callable[[str], None],
                ) -> tuple[dict[str, Any], Callable[[dict[str, Any]], str]]:
                    if external_progress_callback is None:
                        update_progress(eval_status_message)
                        return _evaluate_selected_mode()

                    def _combined_progress(message: str) -> None:
                        update_progress(message)
                        _emit_external_progress(message)

                    _combined_progress(eval_status_message)
                    return _evaluate_selected_mode()

                eval_result, eval_report_formatter = _run_with_progress_status(
                    initial_status=eval_status_message,
                    progress_prefix=f"Benchmark eval ({selected_source.name})",
                    run=_run_eval_with_status,
                    telemetry_path=(
                        eval_output_dir / "processing_timeseries_evaluation.jsonl"
                    ),
                )
        except KeyboardInterrupt:
            _finalize_interrupted_benchmark_run(
                eval_output_dir=eval_output_dir,
                source_path=selected_source,
                source_hash=pred_context.source_hash,
                pred_run=pred_run,
                processed_run_root=(
                    Path(str(import_result.get("processed_run_root"))).expanduser()
                    if str(import_result.get("processed_run_root") or "").strip()
                    else None
                ),
                selected_gold=selected_gold,
                selected_eval_mode=selected_eval_mode,
                predictions_in_path=predictions_in_path,
                predictions_out_path=predictions_out_path,
                should_upload_predictions=should_upload_predictions,
                write_markdown=write_markdown,
                write_label_studio_tasks=write_label_studio_tasks,
                phase="evaluation",
            )
            if not suppress_summary:
                typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
            return
        finally:
            if eval_profiler is not None:
                eval_profiler.disable()
        evaluate_seconds = max(0.0, time.monotonic() - evaluation_started)
        evaluation_seconds = evaluate_seconds
        report = eval_result["report"]
        eval_profile_pstats_path: Path | None = None
        eval_profile_top_path: Path | None = None
        eval_profile_dump_seconds = 0.0
        eval_profile_captured = False
        if (
            eval_profiler is not None
            and eval_profile_min_seconds is not None
            and evaluate_seconds >= eval_profile_min_seconds
        ):
            profile_dump_started = time.monotonic()
            try:
                eval_profile_pstats_path = eval_output_dir / "eval_profile.pstats"
                eval_profile_top_path = eval_output_dir / "eval_profile_top.txt"
                eval_profiler.dump_stats(str(eval_profile_pstats_path))
                stats_stream = io.StringIO()
                stats = pstats.Stats(eval_profiler, stream=stats_stream)
                stats.sort_stats(pstats.SortKey.CUMULATIVE)
                stats.print_stats(eval_profile_top_n)
                eval_profile_top_path.write_text(stats_stream.getvalue(), encoding="utf-8")
                eval_profile_captured = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unable to write benchmark eval profile artifacts: %s", exc)
                eval_profile_pstats_path = None
                eval_profile_top_path = None
                eval_profile_captured = False
            finally:
                eval_profile_dump_seconds = max(
                    0.0, time.monotonic() - profile_dump_started
                )

        if isinstance(report, dict):
            evaluation_telemetry_payload = report.get("evaluation_telemetry")
            if not isinstance(evaluation_telemetry_payload, dict):
                evaluation_telemetry_payload = {}
                report["evaluation_telemetry"] = evaluation_telemetry_payload
            profiling_payload: dict[str, Any] = {
                "enabled": eval_profile_min_seconds is not None,
                "captured": eval_profile_captured,
            }
            if eval_profile_min_seconds is not None:
                profiling_payload["threshold_seconds"] = float(eval_profile_min_seconds)
            profiling_payload["top_n"] = float(eval_profile_top_n)
            if eval_profile_dump_seconds > 0.0:
                profiling_payload["artifact_write_seconds"] = float(eval_profile_dump_seconds)
            if eval_profile_pstats_path is not None:
                profiling_payload["profile_pstats_path"] = str(eval_profile_pstats_path)
            if eval_profile_top_path is not None:
                profiling_payload["profile_top_path"] = str(eval_profile_top_path)
            evaluation_telemetry_payload["profiling"] = profiling_payload
            artifacts_payload = report.get("artifacts")
            if isinstance(artifacts_payload, dict):
                if eval_profile_pstats_path is not None:
                    artifacts_payload["eval_profile_pstats"] = str(eval_profile_pstats_path)
                if eval_profile_top_path is not None:
                    artifacts_payload["eval_profile_top"] = str(eval_profile_top_path)

        evaluation_telemetry = (
            report.get("evaluation_telemetry")
            if isinstance(report, dict)
            else None
        )
        telemetry_prediction_load, telemetry_gold_load = _evaluation_telemetry_load_seconds(
            evaluation_telemetry
        )
        if telemetry_prediction_load is not None:
            prediction_load_seconds = telemetry_prediction_load
        if telemetry_gold_load is not None:
            gold_load_seconds = telemetry_gold_load
        if prediction_load_seconds is None:
            prediction_load_seconds = 0.0
        if gold_load_seconds is None:
            gold_load_seconds = 0.0
        _notify_benchmark_scheduler_event(
            "evaluate_finished",
            eval_mode=selected_eval_mode,
            evaluate_seconds=evaluate_seconds,
            prediction_load_seconds=prediction_load_seconds,
            gold_load_seconds=gold_load_seconds,
            eval_profile_captured=eval_profile_captured,
            eval_profile_dump_seconds=eval_profile_dump_seconds,
        )

        benchmark_recipes = pred_context.recipes
        benchmark_recipes_source: str | None = (
            "prediction_run_context" if benchmark_recipes is not None else None
        )
        manifest_report_path = pred_context.processed_report_path
        processed_report_path = import_result.get("processed_report_path")
        csv_report_path = manifest_report_path
        if not csv_report_path and processed_report_path is not None:
            csv_report_path = str(processed_report_path)
        if benchmark_recipes is None and processed_report_path is not None:
            benchmark_recipes = _load_total_recipes_from_report_path(processed_report_path)
            if benchmark_recipes is not None:
                benchmark_recipes_source = "processed_report.totalRecipes"
        if benchmark_recipes is not None:
            recipe_counts = report.get("recipe_counts")
            if not isinstance(recipe_counts, dict):
                recipe_counts = {}
            recipe_counts["predicted_recipe_count"] = benchmark_recipes
            recipe_counts["predicted_recipe_count_source"] = benchmark_recipes_source
            report["recipe_counts"] = recipe_counts

        prediction_timing = _normalize_timing_payload(import_result.get("timing"))
        prediction_seconds = _report_optional_metric(
            prediction_timing.get("prediction_seconds")
        )
        if prediction_seconds is None:
            prediction_seconds = _report_optional_metric(prediction_timing.get("total_seconds"))
        if prediction_seconds is None:
            prediction_seconds = prediction_phase_seconds
        prediction_seconds_value = max(0.0, prediction_seconds)
        prediction_checkpoints = {}
        existing_prediction_checkpoints = prediction_timing.get("checkpoints")
        if isinstance(existing_prediction_checkpoints, dict):
            prediction_checkpoints.update(existing_prediction_checkpoints)
        prediction_checkpoints.update(
            {
                "prediction_load_seconds": prediction_load_seconds,
                "gold_load_seconds": gold_load_seconds,
                "evaluate_seconds": evaluate_seconds,
                "evaluate_profile_captured": 1.0 if eval_profile_captured else 0.0,
            }
        )
        if eval_profile_min_seconds is not None:
            prediction_checkpoints["evaluate_profile_threshold_seconds"] = max(
                0.0, float(eval_profile_min_seconds)
            )
        if eval_profile_dump_seconds > 0.0:
            prediction_checkpoints["evaluate_profile_artifact_write_seconds"] = max(
                0.0, eval_profile_dump_seconds
            )
        prediction_checkpoints.update(
            _evaluation_telemetry_checkpoints(evaluation_telemetry)
        )
        benchmark_timing = _timing_with_updates(
            prediction_timing,
            prediction_seconds=prediction_seconds,
            evaluation_seconds=evaluation_seconds,
            checkpoints=prediction_checkpoints,
        )
        report["timing"] = benchmark_timing
        report_json_path = eval_output_dir / "eval_report.json"
        report_md_path = eval_output_dir / "eval_report.md"
        artifact_write_seconds = max(0.0, eval_profile_dump_seconds)
        total_floor_with_artifacts = (
            prediction_seconds_value + max(0.0, evaluation_seconds) + artifact_write_seconds
        )
        benchmark_timing = _timing_with_updates(
            benchmark_timing,
            artifact_write_seconds=artifact_write_seconds,
            total_seconds=max(
                max(0.0, time.monotonic() - benchmark_started),
                total_floor_with_artifacts,
            ),
        )
        report["timing"] = benchmark_timing

        from cookimport.analytics.perf_report import append_benchmark_csv, history_path
        history_append_started = time.monotonic()
        csv_history_path = history_path(processed_output_dir)
        append_benchmark_csv(
            report,
            csv_history_path,
            run_timestamp=dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            run_dir=str(eval_output_dir),
            eval_scope=eval_scope,
            source_file=str(selected_source),
            importer_name=_infer_importer_name_from_source_path(selected_source),
            recipes=benchmark_recipes,
            processed_report_path=csv_report_path,
            run_config=pred_context.run_config,
            run_config_hash=pred_context.run_config_hash,
            run_config_summary=pred_context.run_config_summary,
            tokens_input=getattr(pred_context, "tokens_input", None),
            tokens_cached_input=getattr(pred_context, "tokens_cached_input", None),
            tokens_output=getattr(pred_context, "tokens_output", None),
            tokens_reasoning=getattr(pred_context, "tokens_reasoning", None),
            tokens_total=getattr(pred_context, "tokens_total", None),
            timing=benchmark_timing,
        )
        if not suppress_summary and not suppress_dashboard_refresh:
            _refresh_dashboard_after_history_write(
                csv_path=csv_history_path,
                output_root=processed_output_dir,
                golden_root=DEFAULT_GOLDEN,
                reason="labelstudio-benchmark history append",
            )
        history_append_seconds = max(0.0, time.monotonic() - history_append_started)
        total_floor_with_history = total_floor_with_artifacts + history_append_seconds
        benchmark_timing = _timing_with_updates(
            benchmark_timing,
            history_append_seconds=history_append_seconds,
            total_seconds=max(
                max(0.0, time.monotonic() - benchmark_started),
                total_floor_with_history,
            ),
            checkpoints={"history_csv_append_seconds": history_append_seconds},
        )
        report["timing"] = benchmark_timing
        report_md = eval_report_formatter(report)
        report_json_path.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        if write_markdown:
            report_md_path.write_text(report_md, encoding="utf-8")
        else:
            report_md_path.unlink(missing_ok=True)

        line_role_diagnostics_artifacts: dict[str, Any] = {}
        line_role_gate_payload: dict[str, Any] | None = None
        if (
            selected_eval_mode == BENCHMARK_EVAL_MODE_CANONICAL_TEXT
            and selected_line_role_pipeline != "off"
        ):
            line_role_output_dir = eval_output_dir / "line-role-pipeline"
            line_role_output_dir.mkdir(parents=True, exist_ok=True)
            resolved_line_role_predictions_path = _resolve_line_role_predictions_for_benchmark(
                import_result=import_result,
                pred_run=pred_run,
            )
            local_line_role_predictions_path = (
                line_role_output_dir / "line_role_predictions.jsonl"
            )
            if (
                resolved_line_role_predictions_path is not None
                and resolved_line_role_predictions_path.exists()
                and resolved_line_role_predictions_path.resolve(strict=False)
                != local_line_role_predictions_path.resolve(strict=False)
            ):
                shutil.copy2(
                    resolved_line_role_predictions_path,
                    local_line_role_predictions_path,
                )
            elif (
                resolved_line_role_predictions_path is not None
                and resolved_line_role_predictions_path.exists()
            ):
                local_line_role_predictions_path = resolved_line_role_predictions_path

            joined_line_rows = build_line_role_joined_line_rows(
                report=report,
                eval_output_dir=eval_output_dir,
                line_role_predictions_path=(
                    local_line_role_predictions_path
                    if local_line_role_predictions_path.exists()
                    else None
                ),
            )
            joined_line_table_path = line_role_output_dir / "joined_line_table.jsonl"
            joined_line_table_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in joined_line_rows),
                encoding="utf-8",
            )

            baseline_joined_line_rows, baseline_history_row = _resolve_line_role_baseline_joined_rows(
                history_csv_path=csv_history_path,
                source_key=_source_key_from_source_path(str(selected_source)),
                llm_recipe_pipeline=selected_llm_recipe_pipeline,
            )
            flips_rows = build_line_role_flips_vs_baseline(
                joined_line_rows=joined_line_rows,
                line_role_predictions_path=(
                    local_line_role_predictions_path
                    if local_line_role_predictions_path.exists()
                    else None
                ),
                baseline_joined_line_rows=baseline_joined_line_rows,
            )
            line_role_flips_path = line_role_output_dir / "line_role_flips_vs_baseline.jsonl"
            line_role_flips_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in flips_rows),
                encoding="utf-8",
            )

            slice_metrics_payload = build_line_role_slice_metrics(joined_line_rows)
            slice_metrics_path = line_role_output_dir / "slice_metrics.json"
            slice_metrics_path.write_text(
                json.dumps(slice_metrics_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            routing_summary_payload = build_line_role_routing_summary(joined_line_rows)
            routing_summary_path = line_role_output_dir / "routing_summary.json"
            routing_summary_path.write_text(
                json.dumps(routing_summary_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            prompt_eval_alignment_path = line_role_output_dir / "prompt_eval_alignment.md"
            write_prompt_eval_alignment_doc(
                output_path=prompt_eval_alignment_path,
                llm_recipe_pipeline=selected_llm_recipe_pipeline,
                line_role_pipeline=selected_line_role_pipeline,
                atomic_block_splitter=selected_atomic_block_splitter,
            )

            sample_summary = write_line_role_stable_samples(
                output_dir=line_role_output_dir,
                joined_line_rows=joined_line_rows,
                flips_rows=flips_rows,
            )
            sample_summary_path = line_role_output_dir / "sample_summary.json"
            sample_summary_path.write_text(
                json.dumps(sample_summary, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            line_role_diagnostics_artifacts = {
                "line_role_predictions_jsonl": _path_for_manifest(
                    eval_output_dir,
                    local_line_role_predictions_path
                    if local_line_role_predictions_path.exists()
                    else None,
                ),
                "joined_line_table_jsonl": _path_for_manifest(
                    eval_output_dir,
                    joined_line_table_path,
                ),
                "line_role_flips_vs_baseline_jsonl": _path_for_manifest(
                    eval_output_dir,
                    line_role_flips_path,
                ),
                "slice_metrics_json": _path_for_manifest(
                    eval_output_dir,
                    slice_metrics_path,
                ),
                "routing_summary_json": _path_for_manifest(
                    eval_output_dir,
                    routing_summary_path,
                ),
                "prompt_eval_alignment_md": _path_for_manifest(
                    eval_output_dir,
                    prompt_eval_alignment_path,
                ),
                "sample_summary_json": _path_for_manifest(
                    eval_output_dir,
                    sample_summary_path,
                ),
                "wrong_label_lines_sample_jsonl": _path_for_manifest(
                    eval_output_dir,
                    line_role_output_dir / "wrong_label_lines.sample.jsonl",
                ),
                "correct_label_lines_sample_jsonl": _path_for_manifest(
                    eval_output_dir,
                    line_role_output_dir / "correct_label_lines.sample.jsonl",
                ),
                "aligned_prediction_blocks_sample_jsonl": _path_for_manifest(
                    eval_output_dir,
                    line_role_output_dir / "aligned_prediction_blocks.sample.jsonl",
                ),
                "line_role_flips_vs_baseline_sample_jsonl": _path_for_manifest(
                    eval_output_dir,
                    line_role_output_dir / "line_role_flips_vs_baseline.sample.jsonl",
                ),
            }
            if isinstance(baseline_history_row, dict):
                baseline_run_dir = str(baseline_history_row.get("run_dir") or "").strip()
                if baseline_run_dir:
                    line_role_diagnostics_artifacts["line_role_flips_baseline_run_dir"] = (
                        _path_for_manifest(eval_output_dir, baseline_run_dir) or baseline_run_dir
                    )
                baseline_run_timestamp = str(
                    baseline_history_row.get("run_timestamp") or ""
                ).strip()
                if baseline_run_timestamp:
                    line_role_diagnostics_artifacts[
                        "line_role_flips_baseline_run_timestamp"
                    ] = baseline_run_timestamp

            if line_role_gated:
                line_role_gate_payload = _build_line_role_regression_gate_payload(
                    candidate_report=report,
                    candidate_source_key=_source_key_from_source_path(str(selected_source)),
                    history_csv_path=csv_history_path,
                )
                line_role_gate_json_path = line_role_output_dir / "regression_gates.json"
                line_role_gate_json_path.write_text(
                    json.dumps(line_role_gate_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                gate_lines = [
                    "# Line-Role Regression Gates",
                    "",
                    (
                        "Verdict: "
                        + str(
                            ((line_role_gate_payload.get("overall") or {}).get("verdict"))
                            or "UNKNOWN"
                        )
                    ),
                    "",
                    "| Gate | Status | Reason |",
                    "| --- | --- | --- |",
                ]
                gates_payload = line_role_gate_payload.get("gates")
                if isinstance(gates_payload, list):
                    for gate in gates_payload:
                        if not isinstance(gate, dict):
                            continue
                        gate_name = str(gate.get("name") or "").strip() or "<unknown>"
                        status = "PASS" if bool(gate.get("passed")) else "FAIL"
                        reason = str(gate.get("reason") or "").strip().replace("|", "\\|")
                        gate_lines.append(f"| `{gate_name}` | {status} | {reason} |")
                line_role_gate_md_path = line_role_output_dir / "regression_gates.md"
                line_role_gate_md_path.write_text(
                    "\n".join(gate_lines).rstrip() + "\n",
                    encoding="utf-8",
                )
                line_role_diagnostics_artifacts[
                    "line_role_regression_gates_json"
                ] = _path_for_manifest(
                    eval_output_dir,
                    line_role_gate_json_path,
                )
                line_role_diagnostics_artifacts[
                    "line_role_regression_gates_md"
                ] = _path_for_manifest(
                    eval_output_dir,
                    line_role_gate_md_path,
                )

        benchmark_run_config: dict[str, Any] = apply_bucket1_fixed_behavior_metadata(
            apply_codex_execution_policy_metadata(
                {
            "eval_mode": selected_eval_mode,
            "gold_adaptation_mode": selected_gold_adaptation_mode,
            "gold_adaptation_min_coverage": selected_gold_adaptation_min_coverage,
            "gold_adaptation_max_ambiguous": selected_gold_adaptation_max_ambiguous,
            "sequence_matcher": selected_sequence_matcher,
            "prediction_record_input": (
                str(predictions_in_path) if predictions_in_path is not None else None
            ),
            "prediction_record_output": (
                str(predictions_out_path) if predictions_out_path is not None else None
            ),
            "overlap_threshold": overlap_threshold,
            "force_source_match": force_source_match,
            "upload": should_upload_predictions,
            "write_markdown": bool(write_markdown),
            "write_label_studio_tasks": bool(write_label_studio_tasks),
            "epub_extractor": selected_epub_extractor,
            "epub_unstructured_html_parser_version": selected_html_parser_version,
            "epub_unstructured_skip_headers_footers": selected_skip_headers_footers,
            "epub_unstructured_preprocess_mode": selected_preprocess_mode,
            "ocr_device": selected_ocr_device,
            "pdf_ocr_policy": selected_pdf_ocr_policy,
            "ocr_batch_size": ocr_batch_size,
            "pdf_column_gap_ratio": selected_pdf_column_gap_ratio,
            "multi_recipe_splitter": selected_multi_recipe_splitter,
            "multi_recipe_min_ingredient_lines": selected_multi_recipe_min_ingredient_lines,
            "multi_recipe_min_instruction_lines": selected_multi_recipe_min_instruction_lines,
            "multi_recipe_for_the_guardrail": selected_multi_recipe_for_the_guardrail,
            "web_schema_extractor": selected_web_schema_extractor,
            "web_schema_normalizer": selected_web_schema_normalizer,
            "web_html_text_extractor": selected_web_html_text_extractor,
            "web_schema_policy": selected_web_schema_policy,
            "web_schema_min_confidence": selected_web_schema_min_confidence,
            "web_schema_min_ingredients": selected_web_schema_min_ingredients,
            "web_schema_min_instruction_steps": selected_web_schema_min_instruction_steps,
            "ingredient_text_fix_backend": selected_ingredient_text_fix_backend,
            "ingredient_pre_normalize_mode": selected_ingredient_pre_normalize_mode,
            "ingredient_packaging_mode": selected_ingredient_packaging_mode,
            "ingredient_parser_backend": selected_ingredient_parser_backend,
            "ingredient_unit_canonicalizer": selected_ingredient_unit_canonicalizer,
            "ingredient_missing_unit_policy": selected_ingredient_missing_unit_policy,
            "p6_time_backend": selected_p6_time_backend,
            "p6_time_total_strategy": selected_p6_time_total_strategy,
            "p6_temperature_backend": selected_p6_temperature_backend,
            "p6_temperature_unit_backend": selected_p6_temperature_unit_backend,
            "p6_ovenlike_mode": selected_p6_ovenlike_mode,
            "p6_yield_mode": selected_p6_yield_mode,
            "recipe_scorer_backend": selected_recipe_scorer_backend,
            "recipe_score_gold_min": selected_recipe_score_gold_min,
            "recipe_score_silver_min": selected_recipe_score_silver_min,
            "recipe_score_bronze_min": selected_recipe_score_bronze_min,
            "recipe_score_min_ingredient_lines": selected_recipe_score_min_ingredient_lines,
            "recipe_score_min_instruction_lines": selected_recipe_score_min_instruction_lines,
            "workers": workers,
            "pdf_split_workers": pdf_split_workers,
            "epub_split_workers": epub_split_workers,
            "pdf_pages_per_job": pdf_pages_per_job,
            "epub_spine_items_per_job": epub_spine_items_per_job,
            "warm_models": warm_models,
            "llm_recipe_pipeline": selected_llm_recipe_pipeline,
            "recipe_prompt_target_count": recipe_prompt_target_count,
            "llm_knowledge_pipeline": selected_llm_knowledge_pipeline,
            "knowledge_prompt_target_count": knowledge_prompt_target_count,
            "knowledge_packet_input_char_budget": knowledge_packet_input_char_budget,
            "knowledge_packet_output_char_budget": knowledge_packet_output_char_budget,
            "knowledge_group_task_max_units": knowledge_group_task_max_units,
            "knowledge_group_task_max_evidence_chars": (
                knowledge_group_task_max_evidence_chars
            ),
            "atomic_block_splitter": selected_atomic_block_splitter,
            "line_role_pipeline": selected_line_role_pipeline,
            "line_role_prompt_target_count": line_role_prompt_target_count,
            "line_role_gated": bool(line_role_gated),
            "codex_farm_recipe_mode": selected_codex_farm_recipe_mode,
            "codex_farm_cmd": codex_farm_cmd,
            "codex_farm_context_blocks": codex_farm_context_blocks,
            "codex_farm_knowledge_context_blocks": (
                codex_farm_knowledge_context_blocks
            ),
            "codex_farm_failure_mode": selected_codex_farm_failure_mode,
            "workspace_completion_quiescence_seconds": (
                workspace_completion_quiescence_seconds
            ),
            "completed_termination_grace_seconds": (
                completed_termination_grace_seconds
            ),
            "epub_title_backtrack_limit": epub_title_backtrack_limit,
            "epub_anchor_title_backtrack_limit": epub_anchor_title_backtrack_limit,
            "epub_ingredient_run_window": epub_ingredient_run_window,
            "epub_ingredient_header_window": epub_ingredient_header_window,
            "epub_title_max_length": epub_title_max_length,
            "stage_block_predictions_path": str(stage_predictions_path),
                },
                benchmark_codex_execution,
            )
        )
        if single_book_split_cache_run_config is not None:
            benchmark_run_config["single_book_split_cache"] = (
                single_book_split_cache_run_config
            )
        if codex_farm_root is not None:
            benchmark_run_config["codex_farm_root"] = str(codex_farm_root)
        if selected_codex_farm_model is not None:
            benchmark_run_config["codex_farm_model"] = selected_codex_farm_model
        if selected_codex_farm_reasoning_effort is not None:
            benchmark_run_config["codex_farm_reasoning_effort"] = (
                selected_codex_farm_reasoning_effort
            )
        if codex_farm_workspace_root is not None:
            benchmark_run_config["codex_farm_workspace_root"] = str(
                codex_farm_workspace_root
            )
        if pred_context.run_config is not None:
            benchmark_run_config["prediction_run_config"] = pred_context.run_config
            benchmark_run_config.update(
                _benchmark_selective_retry_manifest_summary(pred_context.run_config)
            )
        if pred_context.run_config_hash:
            benchmark_run_config["prediction_run_config_hash"] = pred_context.run_config_hash
        if pred_context.run_config_summary:
            benchmark_run_config["prediction_run_config_summary"] = pred_context.run_config_summary

        benchmark_artifacts: dict[str, Any] = {
            "artifact_root_dir": _path_for_manifest(eval_output_dir, pred_run),
            "gold_spans_jsonl": _path_for_manifest(eval_output_dir, selected_gold),
            "stage_block_predictions_json": _path_for_manifest(
                eval_output_dir,
                stage_predictions_path,
            ),
            "eval_report_json": "eval_report.json",
            "missed_gold_blocks_jsonl": "missed_gold_blocks.jsonl",
            "wrong_label_blocks_jsonl": "wrong_label_blocks.jsonl",
            "history_csv": str(history_csv_for_output(processed_output_dir)),
            "timing": benchmark_timing,
        }
        if write_markdown:
            benchmark_artifacts["eval_report_md"] = "eval_report.md"
        prediction_timeseries_path = eval_output_dir / "processing_timeseries_prediction.jsonl"
        evaluation_timeseries_path = eval_output_dir / "processing_timeseries_evaluation.jsonl"
        if prediction_timeseries_path.exists():
            benchmark_artifacts["processing_timeseries_prediction_jsonl"] = _path_for_manifest(
                eval_output_dir,
                prediction_timeseries_path,
            )
        if evaluation_timeseries_path.exists():
            benchmark_artifacts["processing_timeseries_evaluation_jsonl"] = _path_for_manifest(
                eval_output_dir,
                evaluation_timeseries_path,
            )
        if (
            evaluation_stage_predictions_path != stage_predictions_path
            or evaluation_extracted_archive_path != extracted_archive_path
        ):
            benchmark_artifacts["evaluation_stage_block_predictions_json"] = _path_for_manifest(
                eval_output_dir,
                evaluation_stage_predictions_path,
            )
            benchmark_artifacts["evaluation_extracted_archive_json"] = _path_for_manifest(
                eval_output_dir,
                evaluation_extracted_archive_path,
            )
        if predictions_in_path is not None:
            benchmark_artifacts["prediction_record_input_jsonl"] = _path_for_manifest(
                eval_output_dir,
                predictions_in_path,
            )
        if predictions_out_path is not None:
            benchmark_artifacts["prediction_record_output_jsonl"] = _path_for_manifest(
                eval_output_dir,
                predictions_out_path,
            )
        if eval_profile_pstats_path is not None and eval_profile_pstats_path.exists():
            benchmark_artifacts["eval_profile_pstats"] = _path_for_manifest(
                eval_output_dir,
                eval_profile_pstats_path,
            )
        if eval_profile_top_path is not None and eval_profile_top_path.exists():
            benchmark_artifacts["eval_profile_top"] = _path_for_manifest(
                eval_output_dir,
                eval_profile_top_path,
            )
        if selected_eval_mode == BENCHMARK_EVAL_MODE_CANONICAL_TEXT:
            gold_export_root = selected_gold.parent
            benchmark_artifacts["gold_export_root"] = _path_for_manifest(
                eval_output_dir,
                gold_export_root,
            )
            for artifact_name in (
                "canonical_text.txt",
                "canonical_span_labels.jsonl",
                "canonical_manifest.json",
            ):
                artifact_path = gold_export_root / artifact_name
                if artifact_path.exists():
                    benchmark_artifacts[
                        artifact_name.replace(".", "_")
                    ] = _path_for_manifest(eval_output_dir, artifact_path)
        if csv_report_path:
            benchmark_artifacts["processed_report_json"] = _path_for_manifest(
                eval_output_dir,
                csv_report_path,
            )
        if codex_exec_prompt_response_log_path is not None:
            benchmark_artifacts[
                "codex_exec_prompt_request_response_txt"
            ] = _path_for_manifest(
                eval_output_dir,
                codex_exec_prompt_response_log_path,
            )
            category_manifest_path = (
                codex_exec_prompt_response_log_path.parent / "prompt_category_logs_manifest.txt"
            )
            if category_manifest_path.exists() and category_manifest_path.is_file():
                benchmark_artifacts[
                    "codex_exec_prompt_category_logs_manifest_txt"
                ] = _path_for_manifest(
                    eval_output_dir,
                    category_manifest_path,
                )
            full_prompt_log_path = (
                codex_exec_prompt_response_log_path.parent / "full_prompt_log.jsonl"
            )
            prompt_type_samples_path = (
                codex_exec_prompt_response_log_path.parent
                / llm_prompt_artifacts.PROMPT_TYPE_SAMPLES_MD_NAME
            )
            activity_trace_summary_jsonl_path = (
                codex_exec_prompt_response_log_path.parent
                / llm_prompt_artifacts.ACTIVITY_TRACE_SUMMARY_JSONL_NAME
            )
            activity_trace_summary_md_path = (
                codex_exec_prompt_response_log_path.parent
                / llm_prompt_artifacts.ACTIVITY_TRACE_SUMMARY_MD_NAME
            )
            if full_prompt_log_path.exists() and full_prompt_log_path.is_file():
                prompt_log_summary_path = (
                    codex_exec_prompt_response_log_path.parent
                    / llm_prompt_artifacts.PROMPT_LOG_SUMMARY_JSON_NAME
                )
                summary_path = llm_prompt_artifacts.write_prompt_log_summary(
                    full_prompt_log_path=full_prompt_log_path,
                    output_path=prompt_log_summary_path,
                )
                prompt_log_summary: dict[str, Any] = {}
                if summary_path is not None and summary_path.exists():
                    try:
                        loaded_summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        loaded_summary = {}
                    if isinstance(loaded_summary, dict):
                        prompt_log_summary = loaded_summary
                by_stage_summary = (
                    prompt_log_summary.get("by_stage")
                    if isinstance(prompt_log_summary.get("by_stage"), dict)
                    else {}
                )
                benchmark_artifacts["full_prompt_log_status"] = "complete"
                benchmark_artifacts["full_prompt_log_rows"] = int(
                    prompt_log_summary.get("full_prompt_log_rows") or 0
                )
                benchmark_artifacts["full_prompt_log_runtime_shard_count"] = int(
                    prompt_log_summary.get("runtime_shard_count") or 0
                )
                benchmark_artifacts["full_prompt_log_runtime_shard_count_status"] = str(
                    prompt_log_summary.get("runtime_shard_count_status") or "missing"
                )
                benchmark_artifacts["full_prompt_log_rows_without_runtime_shard_id"] = int(
                    prompt_log_summary.get("rows_without_runtime_shard_id") or 0
                )
                benchmark_artifacts["full_prompt_log_rows_by_stage"] = {
                    str(stage_key): int((payload or {}).get("row_count") or 0)
                    for stage_key, payload in by_stage_summary.items()
                    if isinstance(payload, dict)
                }
                benchmark_artifacts["full_prompt_log_runtime_shard_count_by_stage"] = {
                    str(stage_key): int((payload or {}).get("runtime_shard_count") or 0)
                    for stage_key, payload in by_stage_summary.items()
                    if isinstance(payload, dict)
                }
                benchmark_artifacts["full_prompt_log_path"] = _path_for_manifest(
                    eval_output_dir,
                    full_prompt_log_path,
                )
                benchmark_artifacts["codex_exec_full_prompt_log_jsonl"] = _path_for_manifest(
                    eval_output_dir,
                    full_prompt_log_path,
                )
                if summary_path is not None and summary_path.exists():
                    benchmark_artifacts["codex_exec_prompt_log_summary_json"] = (
                        _path_for_manifest(
                            eval_output_dir,
                            summary_path,
                        )
                    )
            else:
                benchmark_artifacts["full_prompt_log_status"] = "missing"
                benchmark_artifacts["full_prompt_log_rows"] = 0
                benchmark_artifacts["full_prompt_log_runtime_shard_count"] = 0
                benchmark_artifacts["full_prompt_log_runtime_shard_count_status"] = "missing"
                benchmark_artifacts["full_prompt_log_rows_without_runtime_shard_id"] = 0
                benchmark_artifacts["full_prompt_log_rows_by_stage"] = {}
                benchmark_artifacts["full_prompt_log_runtime_shard_count_by_stage"] = {}
                benchmark_artifacts["full_prompt_log_path"] = None
            if prompt_type_samples_path.exists() and prompt_type_samples_path.is_file():
                benchmark_artifacts[
                    "codex_exec_prompt_type_samples_from_full_prompt_log_md"
                ] = _path_for_manifest(
                    eval_output_dir,
                    prompt_type_samples_path,
                )
            if (
                activity_trace_summary_jsonl_path.exists()
                and activity_trace_summary_jsonl_path.is_file()
            ):
                benchmark_artifacts["codex_exec_activity_trace_summary_jsonl"] = (
                    _path_for_manifest(
                        eval_output_dir,
                        activity_trace_summary_jsonl_path,
                    )
                )
            if (
                activity_trace_summary_md_path.exists()
                and activity_trace_summary_md_path.is_file()
            ):
                benchmark_artifacts["codex_exec_activity_trace_summary_md"] = (
                    _path_for_manifest(
                        eval_output_dir,
                        activity_trace_summary_md_path,
                    )
                )
        processed_run_root_raw = import_result.get("processed_run_root")
        processed_run_root = (
            Path(str(processed_run_root_raw)).expanduser()
            if str(processed_run_root_raw or "").strip()
            else None
        )
        if processed_run_root is not None:
            benchmark_artifacts["processed_output_run_dir"] = _path_for_manifest(
                eval_output_dir,
                processed_run_root,
            )
            benchmark_artifacts["stage_run_dir"] = _path_for_manifest(
                eval_output_dir,
                processed_run_root,
            )
        llm_manifest_path = _find_single_book_llm_manifest_path(pred_run)
        if llm_manifest_path is not None:
            benchmark_llm_manifest = _path_for_manifest(
                eval_output_dir,
                llm_manifest_path,
            )
            if benchmark_llm_manifest is not None:
                benchmark_artifacts["recipe_manifest_json"] = benchmark_llm_manifest
        for artifact_key, artifact_value in line_role_diagnostics_artifacts.items():
            if artifact_value:
                benchmark_artifacts[artifact_key] = artifact_value

        _write_eval_run_manifest(
            run_root=eval_output_dir,
            run_kind="labelstudio_benchmark",
            source_path=str(selected_source),
            source_hash=pred_context.source_hash,
            importer_name=None,
            run_config=benchmark_run_config,
            artifacts=benchmark_artifacts,
            notes=(
                "Benchmark evaluation against freeform gold using "
                f"{selected_eval_mode} scoring. "
                + (
                    "Evaluate-only mode from prediction record."
                    if predictions_in_path is not None
                    else (
                        "Upload disabled."
                        if no_upload
                        else "Prediction tasks uploaded to Label Studio."
                    )
                )
            ),
        )
        if line_role_gated and isinstance(line_role_gate_payload, dict):
            overall_payload = line_role_gate_payload.get("overall")
            verdict = (
                str((overall_payload or {}).get("verdict") or "").strip().upper()
                if isinstance(overall_payload, dict)
                else ""
            )
            if verdict == "FAIL":
                _prune_benchmark_outputs(
                    eval_output_dir=eval_output_dir,
                    processed_run_root=processed_run_root,
                    suppress_summary=suppress_summary,
                    suppress_output_prune=suppress_output_prune,
                )
                _fail(
                    "Line-role regression gates failed. "
                    f"See {eval_output_dir / 'line-role-pipeline' / 'regression_gates.md'}."
                )

        if not suppress_summary:
            typer.secho("Benchmark complete.", fg=typer.colors.GREEN)
            typer.secho(f"Gold spans: {selected_gold}", fg=typer.colors.CYAN)
            typer.secho(f"Benchmark artifact root: {pred_run}", fg=typer.colors.CYAN)
            if processed_run_root is not None:
                typer.secho(f"Processed output: {processed_run_root}", fg=typer.colors.CYAN)
            if selected_eval_mode == BENCHMARK_EVAL_MODE_CANONICAL_TEXT:
                typer.secho(
                    "Overall line accuracy: "
                    f"{float(report.get('overall_line_accuracy') or 0.0):.3f}",
                    fg=typer.colors.CYAN,
                )
            else:
                typer.secho(
                    "Overall block accuracy: "
                    f"{float(report.get('overall_block_accuracy') or 0.0):.3f}",
                    fg=typer.colors.CYAN,
                )
            typer.secho(
                "Macro F1 (excluding OTHER): "
                f"{float(report.get('macro_f1_excluding_other') or 0.0):.3f}",
                fg=typer.colors.CYAN,
            )
            worst_label_payload = report.get("worst_label_recall")
            if isinstance(worst_label_payload, dict):
                worst_label = str(worst_label_payload.get("label") or "").strip()
                worst_recall = float(worst_label_payload.get("recall") or 0.0)
                if worst_label:
                    typer.secho(
                        f"Worst-label recall: {worst_label} {worst_recall:.3f}",
                        fg=typer.colors.YELLOW,
                    )
            typer.secho(f"Report JSON: {report_json_path}", fg=typer.colors.CYAN)
            if write_markdown:
                typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)
            if line_role_diagnostics_artifacts:
                typer.secho(
                    f"Line-role diagnostics: {eval_output_dir / 'line-role-pipeline'}",
                    fg=typer.colors.CYAN,
                )
            if line_role_gated and isinstance(line_role_gate_payload, dict):
                overall_payload = line_role_gate_payload.get("overall")
                gate_verdict = (
                    str((overall_payload or {}).get("verdict") or "UNKNOWN").strip().upper()
                    if isinstance(overall_payload, dict)
                    else "UNKNOWN"
                )
                gate_color = typer.colors.GREEN if gate_verdict == "PASS" else typer.colors.RED
                typer.secho(
                    f"Line-role regression gates: {gate_verdict}",
                    fg=gate_color,
                )
            prediction_timeseries_path = (
                eval_output_dir / "processing_timeseries_prediction.jsonl"
            )
            evaluation_timeseries_path = (
                eval_output_dir / "processing_timeseries_evaluation.jsonl"
            )
            if prediction_timeseries_path.exists():
                typer.secho(
                    f"Prediction telemetry: {prediction_timeseries_path}",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            if evaluation_timeseries_path.exists():
                typer.secho(
                    f"Evaluation telemetry: {evaluation_timeseries_path}",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            recipe_counts = report.get("recipe_counts")
            if isinstance(recipe_counts, dict):
                predicted_recipe_count = _coerce_int(recipe_counts.get("predicted_recipe_count"))
                if predicted_recipe_count is not None:
                    typer.secho(
                        f"Predicted recipes from import: {predicted_recipe_count}",
                        fg=typer.colors.CYAN,
                    )
        _prune_benchmark_outputs(
            eval_output_dir=eval_output_dir,
            processed_run_root=processed_run_root,
            suppress_summary=suppress_summary,
            suppress_output_prune=suppress_output_prune,
        )
        if (
            not suppress_summary
            and not bool(_INTERACTIVE_CLI_ACTIVE.get())
            and eval_output_dir.is_dir()
        ):
            upload_bundle_dir = _write_benchmark_upload_bundle(
                source_root=eval_output_dir,
                output_dir=eval_output_dir / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
                suppress_summary=suppress_summary,
                high_level_only=True,
                target_bundle_size_bytes=BENCHMARK_SINGLE_BOOK_UPLOAD_BUNDLE_TARGET_BYTES,
            )
            if upload_bundle_dir is not None:
                typer.secho(
                    f"External-AI upload bundle: {upload_bundle_dir}",
                    fg=typer.colors.CYAN,
                )

    exports = {
        "inspect": inspect,
        "labelstudio_import": labelstudio_import,
        "labelstudio_export": labelstudio_export,
        "labelstudio_eval": labelstudio_eval,
        "debug_epub_extract": debug_epub_extract,
        "labelstudio_benchmark": labelstudio_benchmark,
        "_prune_benchmark_outputs": _prune_benchmark_outputs,
    }
    globals().update(exports)
    return exports
