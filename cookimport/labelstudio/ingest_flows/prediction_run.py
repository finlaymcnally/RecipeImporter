from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from cookimport.config.codex_decision import (
    apply_bucket1_fixed_behavior_metadata,
    apply_codex_execution_policy_metadata,
    bucket1_fixed_behavior,
    resolve_codex_execution_policy,
)
from cookimport.config.runtime_support import serialized_run_setting_default
from cookimport.config.run_settings import (
    KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
    build_run_settings,
    compute_effective_workers,
    normalize_llm_knowledge_pipeline_value,
)
from cookimport.config.run_settings_contracts import summarize_run_config_payload
from cookimport.core.executor_fallback import (
    resolve_process_thread_executor,
    shutdown_executor,
)
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.progress_messages import (
    format_worker_activity,
    format_worker_activity_reset,
)
from cookimport.core.reporting import compute_file_hash
from cookimport.labelstudio.archive import (
    build_extracted_archive,
    prepare_extracted_archive,
    prepared_archive_payload,
    prepared_archive_text,
)
from cookimport.labelstudio.freeform_tasks import (
    build_freeform_span_tasks,
    compute_freeform_task_coverage,
    resolve_segment_overlap_for_target,
    sample_freeform_tasks,
)
from cookimport.labelstudio.ingest_flows.artifacts import (
    _llm_selective_retry_run_config_summary,
    _path_for_manifest,
    _write_authoritative_line_role_artifacts,
    _write_manifest_best_effort,
    _write_processed_outputs,
)
from cookimport.labelstudio.ingest_flows.normalize import (
    _coerce_bool,
    _normalize_codex_farm_failure_mode,
    _normalize_codex_farm_recipe_mode,
    _normalize_epub_extractor,
    _normalize_llm_recipe_pipeline,
    _normalize_unstructured_html_parser_version,
    _normalize_unstructured_preprocess_mode,
)
from cookimport.labelstudio.ingest_flows.split_cache import (
    SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION,
    _acquire_single_book_split_cache_lock,
    _acquire_split_phase_slot,
    _load_single_book_split_cache_entry,
    _normalize_single_book_split_cache_mode,
    _normalize_split_phase_slots,
    _release_single_book_split_cache_lock,
    _single_book_split_cache_entry_path,
    _single_book_split_cache_lock_path,
    _wait_for_single_book_split_cache_entry,
    _write_single_book_split_cache_entry,
)
from cookimport.labelstudio.ingest_flows.split_merge import (
    _merge_parallel_results,
    _parallel_convert_worker,
)
from cookimport.labelstudio.ingest_support import (
    _build_line_role_candidates_from_archive,
    _build_prelabel_provider,
    _format_prelabel_prompt_log_entry_markdown,
    _notify_progress_callback,
    _notify_scheduler_event_callback,
    _safe_float,
    _slugify_name,
    _task_id_value,
    _task_progress_message,
    _temporary_epub_runtime_env,
    _timing_payload,
    _write_processed_report_timing_best_effort,
)
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    build_freeform_label_config,
)
from cookimport.labelstudio.prelabel import (
    PRELABEL_GRANULARITY_BLOCK,
    annotation_labels,
    codex_account_summary,
    codex_reasoning_effort_from_cmd,
    default_codex_cmd,
    default_codex_reasoning_effort,
    is_rate_limit_message,
    normalize_codex_reasoning_effort,
    normalize_prelabel_granularity,
    preflight_codex_model_access,
    prelabel_freeform_task,
    resolve_codex_model,
)
from cookimport.llm.codex_farm_knowledge_orchestrator import (
    run_codex_farm_nonrecipe_finalize,
)
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.llm.prompt_budget import (
    build_prediction_run_prompt_budget_summary,
    write_prediction_run_prompt_budget_summary,
)
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks
from cookimport.parsing.label_source_of_truth import (
    LabelFirstStageResult,
    build_label_first_stage_result,
)
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate
from cookimport.parsing.tables import ExtractedTable
from cookimport.plugins import registry
from cookimport.paths import resolve_book_cache_root
from cookimport.runs import (
    RECIPE_MANIFEST_FILE_NAME,
    RunManifest,
    RunSource,
    build_stage_observability_report,
    stage_artifact_stem,
    write_stage_observability_report,
)
from cookimport.staging.book_cache import (
    CONVERSION_CACHE_SCHEMA_VERSION,
    acquire_entry_lock,
    build_conversion_cache_key,
    conversion_cache_entry_path,
    entry_lock_path,
    load_json_dict_or_none,
    release_entry_lock,
    wait_for_entry,
    write_json_atomic,
)
from cookimport.staging.import_session import (
    execute_stage_import_session_from_recipe_boundary_result,
    execute_stage_import_session_from_result,
    load_deterministic_prep_bundle,
    load_recipe_boundary_result_from_deterministic_prep_bundle,
)
from cookimport.staging.job_planning import JobSpec, plan_source_job
from cookimport.staging.nonrecipe_stage import (
    NonRecipeStageResult,
    build_nonrecipe_authority_contract,
    build_nonrecipe_stage_result,
)
from cookimport.staging.recipe_ownership import build_recipe_ownership_result


def _build_prediction_nonrecipe_stage_result(
    *,
    result: ConversionResult,
    authoritative_label_result: LabelFirstStageResult,
    notify: Callable[[str], None],
) -> NonRecipeStageResult | None:
    try:
        recipe_ownership_result = build_recipe_ownership_result(
            full_blocks=authoritative_label_result.archive_blocks,
            recipe_spans=authoritative_label_result.recipe_spans,
            recipes=result.recipes,
            ownership_mode="recipe_boundary",
        )
        return build_nonrecipe_stage_result(
            full_blocks=authoritative_label_result.archive_blocks,
            final_block_labels=authoritative_label_result.block_labels,
            recipe_ownership_result=recipe_ownership_result,
        )
    except ValueError as exc:
        if result.report is None:
            result.report = ConversionReport()
        result.report.warnings.append(
            "Skipping strict non-recipe prediction-run staging because the "
            f"label-first bundle was not non-recipe-clean: {exc}"
        )
        notify("Skipping strict non-recipe staging for prediction artifacts.")
        return None


def generate_pred_run_artifacts(
    *,
    path: Path,
    output_dir: Path,
    pipeline: str = "auto",
    segment_blocks: int = 40,
    segment_overlap: int = 5,
    segment_focus_blocks: int | None = None,
    target_task_count: int | None = None,
    limit: int | None = None,
    sample: int | None = None,
    workers: int = 1,
    pdf_split_workers: int = 1,
    epub_split_workers: int = 1,
    pdf_pages_per_job: int = 50,
    epub_spine_items_per_job: int = 10,
    epub_extractor: str | None = None,
    epub_unstructured_html_parser_version: str | None = None,
    epub_unstructured_skip_headers_footers: bool | str | None = None,
    epub_unstructured_preprocess_mode: str | None = None,
    epub_title_backtrack_limit: int = int(
        serialized_run_setting_default("epub_title_backtrack_limit")
    ),
    epub_anchor_title_backtrack_limit: int = int(
        serialized_run_setting_default("epub_anchor_title_backtrack_limit")
    ),
    epub_ingredient_run_window: int = int(
        serialized_run_setting_default("epub_ingredient_run_window")
    ),
    epub_ingredient_header_window: int = int(
        serialized_run_setting_default("epub_ingredient_header_window")
    ),
    epub_title_max_length: int = int(
        serialized_run_setting_default("epub_title_max_length")
    ),
    ocr_device: str = "auto",
    pdf_ocr_policy: str = "auto",
    ocr_batch_size: int = 1,
    pdf_column_gap_ratio: float = 0.12,
    warm_models: bool = False,
    section_detector_backend: str = "shared_v1",
    multi_recipe_splitter: str = "rules_v1",
    multi_recipe_trace: bool = False,
    multi_recipe_min_ingredient_lines: int = 1,
    multi_recipe_min_instruction_lines: int = 1,
    multi_recipe_for_the_guardrail: bool = True,
    instruction_step_segmentation_policy: str = "auto",
    instruction_step_segmenter: str = "heuristic_v1",
    web_schema_extractor: str = "builtin_jsonld",
    web_schema_normalizer: str = "simple",
    web_html_text_extractor: str = "bs4",
    web_schema_policy: str = "prefer_schema",
    web_schema_min_confidence: float = 0.75,
    web_schema_min_ingredients: int = 2,
    web_schema_min_instruction_steps: int = 1,
    ingredient_text_fix_backend: str = "none",
    ingredient_pre_normalize_mode: str = "aggressive_v1",
    ingredient_packaging_mode: str = "off",
    ingredient_parser_backend: str = "ingredient_parser_nlp",
    ingredient_unit_canonicalizer: str = "pint",
    ingredient_missing_unit_policy: str = "null",
    p6_time_backend: str = "regex_v1",
    p6_time_total_strategy: str = "sum_all_v1",
    p6_temperature_backend: str = "regex_v1",
    p6_temperature_unit_backend: str = "builtin_v1",
    p6_ovenlike_mode: str = "keywords_v1",
    p6_yield_mode: str = "scored_v1",
    p6_emit_metadata_debug: bool = False,
    recipe_scorer_backend: str = "heuristic_v1",
    recipe_score_gold_min: float = 0.75,
    recipe_score_silver_min: float = 0.55,
    recipe_score_bronze_min: float = 0.35,
    recipe_score_min_ingredient_lines: int = 1,
    recipe_score_min_instruction_lines: int = 1,
    llm_recipe_pipeline: str = "off",
    llm_knowledge_pipeline: str = "off",
    recipe_prompt_target_count: int = 5,
    knowledge_prompt_target_count: int = 5,
    knowledge_packet_input_char_budget: int | None = 18000,
    knowledge_packet_output_char_budget: int | None = 12000,
    knowledge_group_task_max_units: int = int(
        serialized_run_setting_default("knowledge_group_task_max_units")
    ),
    knowledge_group_task_max_evidence_chars: int = int(
        serialized_run_setting_default("knowledge_group_task_max_evidence_chars")
    ),
    line_role_codex_exec_style: str = str(
        serialized_run_setting_default("line_role_codex_exec_style")
    ),
    knowledge_codex_exec_style: str = str(
        serialized_run_setting_default("knowledge_codex_exec_style")
    ),
    atomic_block_splitter: str = "off",
    line_role_pipeline: str = "off",
    line_role_prompt_target_count: int = 5,
    codex_farm_cmd: str = "codex-farm",
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | None = None,
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_pipeline_knowledge: str = "recipe.knowledge.packet.v1",
    codex_farm_context_blocks: int = 30,
    codex_farm_knowledge_context_blocks: int = int(
        serialized_run_setting_default("codex_farm_knowledge_context_blocks")
    ),
    codex_farm_recipe_mode: str = "extract",
    codex_farm_failure_mode: str = "fail",
    workspace_completion_quiescence_seconds: float = float(
        serialized_run_setting_default("workspace_completion_quiescence_seconds")
    ),
    completed_termination_grace_seconds: float = float(
        serialized_run_setting_default("completed_termination_grace_seconds")
    ),
    processed_output_root: Path | None = None,
    write_markdown: bool = True,
    write_label_studio_tasks: bool = True,
    split_phase_slots: int | None = None,
    split_phase_gate_dir: Path | str | None = None,
    split_phase_status_label: str | None = None,
    book_cache_root: Path | str | None = None,
    single_book_split_cache_mode: str = "off",
    single_book_split_cache_dir: Path | str | None = None,
    single_book_split_cache_key: str | None = None,
    single_book_split_cache_force: bool = False,
    deterministic_prep_manifest_path: Path | str | None = None,
    prelabel: bool = False,
    prelabel_provider: str = "codex-farm",
    codex_cmd: str | None = None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
    prelabel_timeout_seconds: int = 600,
    prelabel_cache_dir: Path | None = None,
    prelabel_workers: int = 15,
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
    prelabel_allow_partial: bool = False,
    prelabel_track_token_usage: bool = True,
    allow_codex: bool = False,
    codex_execution_policy: str = "execute",
    codex_command_context: str = "labelstudio_benchmark",
    benchmark_variant: str | None = None,
    scheduler_event_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    run_manifest_kind: str = "bench_pred_run",
    run_root_override: Path | str | None = None,
    mirror_stage_artifacts_into_run_root: bool = True,
) -> dict[str, Any]:
    """Generate benchmark/import artifacts offline (no Label Studio credentials needed).

    Performs extraction, conversion, task generation and writes all artifacts to disk.
    Returns metadata dict with run_root, tasks_total, manifest_path, etc.
    """
    def _notify(message: str) -> None:
        _notify_progress_callback(progress_callback, message)

    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    normalized_prelabel_granularity = normalize_prelabel_granularity(prelabel_granularity)
    normalized_prelabel_provider = str(prelabel_provider or "").strip().lower()
    normalized_prelabel_provider = normalized_prelabel_provider.replace("_", "-")
    if normalized_prelabel_provider in {"", "off"}:
        normalized_prelabel_provider = "codex-farm"
    if normalized_prelabel_provider != "codex-farm":
        raise ValueError("prelabel_provider must be 'codex-farm'")

    run_dt = dt.datetime.now()
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    book_slug = _slugify_name(path.stem)
    if run_root_override is None:
        run_root = output_dir / timestamp / "labelstudio" / book_slug
    else:
        run_root = Path(run_root_override).expanduser()
    run_root.mkdir(parents=True, exist_ok=True)
    run_started = time.monotonic()
    _notify_scheduler_event_callback(
        scheduler_event_callback,
        event="prep_started",
        source_file=str(path),
        run_root=str(run_root),
    )
    conversion_seconds = 0.0
    split_wait_seconds = 0.0
    split_convert_seconds = 0.0
    processed_output_write_seconds = 0.0
    task_build_seconds = 0.0
    artifact_write_seconds = 0.0

    if pipeline == "auto":
        importer, score = registry.best_importer_for_path(path)
    else:
        importer = registry.get_importer(pipeline)
        score = 1.0 if importer else 0.0
    if importer is None or score <= 0:
        raise RuntimeError("No importer available for this path.")

    selected_epub_extractor = _normalize_epub_extractor(
        str(epub_extractor or os.environ.get("C3IMP_EPUB_EXTRACTOR", "unstructured"))
    )

    selected_html_parser_version = _normalize_unstructured_html_parser_version(
        str(
            epub_unstructured_html_parser_version
            or os.environ.get("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION", "v1")
        )
    )
    selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
        str(
            epub_unstructured_preprocess_mode
            or os.environ.get("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE", "br_split_v1")
        )
    )
    selected_skip_headers_footers = _coerce_bool(
        (
            epub_unstructured_skip_headers_footers
            if epub_unstructured_skip_headers_footers is not None
            else os.environ.get("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS")
        ),
        default=False,
    )
    selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
    selected_llm_knowledge_pipeline = normalize_llm_knowledge_pipeline_value(
        llm_knowledge_pipeline
    )
    if selected_llm_knowledge_pipeline not in {"off", KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2}:
        raise ValueError(
            "Invalid llm_knowledge_pipeline. Expected one of: off, "
            f"{KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2}."
        )
    fixed_bucket1_behavior = bucket1_fixed_behavior()
    selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
        codex_farm_failure_mode
    )
    selected_codex_farm_recipe_mode = _normalize_codex_farm_recipe_mode(
        codex_farm_recipe_mode
    )
    selected_codex_farm_pipeline_knowledge = (
        fixed_bucket1_behavior.codex_farm_pipeline_knowledge
    )
    selected_codex_farm_knowledge_context_blocks = max(
        0,
        int(codex_farm_knowledge_context_blocks),
    )
    run_settings = build_run_settings(
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
        ocr_device=ocr_device,
        pdf_ocr_policy=pdf_ocr_policy,
        ocr_batch_size=ocr_batch_size,
        pdf_column_gap_ratio=pdf_column_gap_ratio,
        warm_models=warm_models,
        multi_recipe_splitter=multi_recipe_splitter,
        multi_recipe_min_ingredient_lines=multi_recipe_min_ingredient_lines,
        multi_recipe_min_instruction_lines=multi_recipe_min_instruction_lines,
        multi_recipe_for_the_guardrail=multi_recipe_for_the_guardrail,
        web_schema_extractor=web_schema_extractor,
        web_schema_normalizer=web_schema_normalizer,
        web_html_text_extractor=web_html_text_extractor,
        web_schema_policy=web_schema_policy,
        web_schema_min_confidence=web_schema_min_confidence,
        web_schema_min_ingredients=web_schema_min_ingredients,
        web_schema_min_instruction_steps=web_schema_min_instruction_steps,
        ingredient_text_fix_backend=ingredient_text_fix_backend,
        ingredient_pre_normalize_mode=ingredient_pre_normalize_mode,
        ingredient_packaging_mode=ingredient_packaging_mode,
        ingredient_parser_backend=ingredient_parser_backend,
        ingredient_unit_canonicalizer=ingredient_unit_canonicalizer,
        ingredient_missing_unit_policy=ingredient_missing_unit_policy,
        p6_time_backend=p6_time_backend,
        p6_time_total_strategy=p6_time_total_strategy,
        p6_temperature_backend=p6_temperature_backend,
        p6_temperature_unit_backend=p6_temperature_unit_backend,
        p6_ovenlike_mode=p6_ovenlike_mode,
        p6_yield_mode=p6_yield_mode,
        recipe_scorer_backend=recipe_scorer_backend,
        recipe_score_gold_min=recipe_score_gold_min,
        recipe_score_silver_min=recipe_score_silver_min,
        recipe_score_bronze_min=recipe_score_bronze_min,
        recipe_score_min_ingredient_lines=recipe_score_min_ingredient_lines,
        recipe_score_min_instruction_lines=recipe_score_min_instruction_lines,
        llm_recipe_pipeline=selected_llm_recipe_pipeline,
        llm_knowledge_pipeline=selected_llm_knowledge_pipeline,
        recipe_prompt_target_count=recipe_prompt_target_count,
        knowledge_prompt_target_count=knowledge_prompt_target_count,
        knowledge_packet_input_char_budget=knowledge_packet_input_char_budget,
        knowledge_packet_output_char_budget=knowledge_packet_output_char_budget,
        knowledge_group_task_max_units=knowledge_group_task_max_units,
        knowledge_group_task_max_evidence_chars=knowledge_group_task_max_evidence_chars,
        atomic_block_splitter=atomic_block_splitter,
        line_role_pipeline=line_role_pipeline,
        line_role_codex_exec_style=line_role_codex_exec_style,
        line_role_prompt_target_count=line_role_prompt_target_count,
        knowledge_codex_exec_style=knowledge_codex_exec_style,
        codex_farm_cmd=codex_farm_cmd,
        codex_farm_model=codex_farm_model,
        codex_farm_reasoning_effort=codex_farm_reasoning_effort,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        codex_farm_context_blocks=codex_farm_context_blocks,
        codex_farm_knowledge_context_blocks=selected_codex_farm_knowledge_context_blocks,
        codex_farm_recipe_mode=selected_codex_farm_recipe_mode,
        codex_farm_failure_mode=selected_codex_farm_failure_mode,
        workspace_completion_quiescence_seconds=(
            workspace_completion_quiescence_seconds
        ),
        completed_termination_grace_seconds=(
            completed_termination_grace_seconds
        ),
        all_epub=path.suffix.lower() == ".epub",
        effective_workers=compute_effective_workers(
            workers=workers,
            epub_split_workers=epub_split_workers,
            epub_extractor=selected_epub_extractor,
            all_epub=path.suffix.lower() == ".epub",
        ),
    )
    codex_decision_payload = {
        **run_settings.to_run_config_dict(),
        "prelabel_enabled": bool(prelabel),
        "prelabel_provider": normalized_prelabel_provider,
    }
    codex_execution = resolve_codex_execution_policy(
        codex_command_context,
        codex_decision_payload,
        execution_policy_mode=codex_execution_policy,
        allow_codex=bool(allow_codex),
        benchmark_variant=benchmark_variant,
    )
    if codex_execution.blocked:
        raise RuntimeError(
            f"{codex_command_context} requires allow_codex=True when Codex-backed "
            "surfaces are enabled."
        )
    worker_run_config = run_settings.to_run_config_dict()
    run_config = apply_bucket1_fixed_behavior_metadata(
        apply_codex_execution_policy_metadata(worker_run_config, codex_execution)
    )
    run_config["prelabel_enabled"] = bool(prelabel)
    run_config["prelabel_provider"] = (
        normalized_prelabel_provider if prelabel else None
    )
    run_config["epub_extractor_requested"] = selected_epub_extractor
    run_config["epub_extractor_effective"] = selected_epub_extractor
    run_config["write_markdown"] = bool(write_markdown)
    run_config["write_label_studio_tasks"] = bool(write_label_studio_tasks)
    run_config_hash = hashlib.sha256(
        json.dumps(
            run_config,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    summary_contract = "product"
    if run_manifest_kind == "labelstudio_import":
        summary_contract = "operator"
    run_config_summary = summarize_run_config_payload(
        run_config,
        contract=summary_contract,
    )
    run_mapping: MappingConfig | None = None
    if path.suffix.lower() == ".pdf":
        run_mapping = MappingConfig(
            ocr_device=run_settings.ocr_device.value,
            ocr_batch_size=run_settings.ocr_batch_size,
        )
    file_hash = compute_file_hash(path)
    resolved_book_cache_root = resolve_book_cache_root(book_cache_root)
    deterministic_prep_bundle = (
        load_deterministic_prep_bundle(deterministic_prep_manifest_path)
        if deterministic_prep_manifest_path is not None
        else None
    )
    prep_bundle_boundary_result = None
    deterministic_prep_bundle_summary: dict[str, Any] | None = None
    if deterministic_prep_bundle is not None:
        if deterministic_prep_bundle.source_file != path.expanduser():
            raise ValueError(
                "Deterministic prep bundle source mismatch: "
                f"{deterministic_prep_bundle.source_file} != {path}"
            )
        if deterministic_prep_bundle.source_hash != file_hash:
            raise ValueError(
                "Deterministic prep bundle source hash mismatch for "
                f"{path}: {deterministic_prep_bundle.source_hash} != {file_hash}"
            )
        deterministic_prep_bundle_summary = {
            "enabled": True,
            "prep_key": deterministic_prep_bundle.prep_key,
            "manifest_path": str(deterministic_prep_bundle.manifest_path),
            "artifact_root": str(deterministic_prep_bundle.artifact_root),
            "processed_run_root": str(deterministic_prep_bundle.processed_run_root),
            "cache_hit": bool(deterministic_prep_bundle.cache_hit),
            "timing": dict(deterministic_prep_bundle.timing),
        }
    shared_conversion_cache_key = build_conversion_cache_key(
        source_file=path,
        source_hash=file_hash,
        pipeline=pipeline,
        run_settings=run_settings,
    )
    shared_conversion_cache_path = conversion_cache_entry_path(
        book_cache_root=resolved_book_cache_root,
        source_hash=file_hash,
        conversion_key=shared_conversion_cache_key,
    )
    shared_conversion_cache_lock_path = entry_lock_path(shared_conversion_cache_path)
    shared_conversion_cache_lock_acquired = False
    shared_conversion_cache_hit = False
    shared_conversion_cache_payload: dict[str, Any] | None = None

    def _load_shared_conversion_cache_payload() -> dict[str, Any] | None:
        payload = load_json_dict_or_none(shared_conversion_cache_path)
        if not isinstance(payload, dict):
            return None
        if (
            str(payload.get("schema_version") or "").strip()
            != CONVERSION_CACHE_SCHEMA_VERSION
        ):
            return None
        if (
            str(payload.get("conversion_cache_key") or "").strip()
            != shared_conversion_cache_key
        ):
            return None
        if not isinstance(payload.get("conversion_result"), dict):
            return None
        return payload

    if deterministic_prep_bundle is None:
        cached_payload = _load_shared_conversion_cache_payload()
        if cached_payload is None:
            shared_conversion_cache_lock_acquired = acquire_entry_lock(
                shared_conversion_cache_lock_path
            )
            if shared_conversion_cache_lock_acquired:
                cached_payload = _load_shared_conversion_cache_payload()
            else:
                cached_payload = wait_for_entry(
                    load_entry=_load_shared_conversion_cache_payload,
                    lock_path=shared_conversion_cache_lock_path,
                )
        if cached_payload is not None:
            try:
                result = ConversionResult.model_validate(
                    cached_payload.get("conversion_result")
                )
            except Exception:  # noqa: BLE001
                cached_payload = None
            else:
                shared_conversion_cache_hit = True
                shared_conversion_cache_payload = cached_payload
                conversion_seconds = max(
                    0.0,
                    _safe_float(cached_payload.get("conversion_seconds")) or 0.0,
                )
                split_wait_seconds = max(
                    0.0,
                    _safe_float(cached_payload.get("split_wait_seconds")) or 0.0,
                )
                split_convert_seconds = max(
                    0.0,
                    _safe_float(cached_payload.get("split_convert_seconds")) or 0.0,
                )
                _notify("Reusing shared book-cache conversion payload.")
                _notify_scheduler_event_callback(
                    scheduler_event_callback,
                    event="book_cache_conversion_reused",
                    conversion_cache_key=shared_conversion_cache_key,
                )
        if shared_conversion_cache_lock_acquired:
            release_entry_lock(shared_conversion_cache_lock_path)
            shared_conversion_cache_lock_acquired = False
    selected_single_book_split_cache_mode = _normalize_single_book_split_cache_mode(
        single_book_split_cache_mode
    )
    selected_single_book_split_cache_key = (
        str(single_book_split_cache_key or "").strip() or None
    )
    selected_single_book_split_cache_dir = (
        Path(single_book_split_cache_dir).expanduser()
        if single_book_split_cache_dir is not None
        else None
    )
    single_book_split_cache_enabled = (
        selected_single_book_split_cache_mode != "off"
        and selected_single_book_split_cache_dir is not None
        and selected_single_book_split_cache_key is not None
    )
    single_book_split_cache_hit = False
    single_book_split_cache_entry_path: Path | None = None
    single_book_split_cache_lock_path: Path | None = None
    single_book_split_cache_lock_acquired = False
    single_book_split_cache_payload: dict[str, Any] | None = None
    if not shared_conversion_cache_hit and single_book_split_cache_enabled:
        single_book_split_cache_entry_path = _single_book_split_cache_entry_path(
            cache_root=selected_single_book_split_cache_dir,
            split_cache_key=selected_single_book_split_cache_key or "",
        )
        single_book_split_cache_lock_path = _single_book_split_cache_lock_path(
            single_book_split_cache_entry_path
        )
        if not single_book_split_cache_force:
            cached_payload = _load_single_book_split_cache_entry(
                cache_path=single_book_split_cache_entry_path,
                expected_key=selected_single_book_split_cache_key or "",
            )
            if cached_payload is None and single_book_split_cache_lock_path is not None:
                single_book_split_cache_lock_acquired = (
                    _acquire_single_book_split_cache_lock(
                        single_book_split_cache_lock_path
                    )
                )
                if single_book_split_cache_lock_acquired:
                    cached_payload = _load_single_book_split_cache_entry(
                        cache_path=single_book_split_cache_entry_path,
                        expected_key=selected_single_book_split_cache_key or "",
                    )
                else:
                    cached_payload = _wait_for_single_book_split_cache_entry(
                        cache_path=single_book_split_cache_entry_path,
                        expected_key=selected_single_book_split_cache_key or "",
                        lock_path=single_book_split_cache_lock_path,
                    )
            if cached_payload is not None:
                try:
                    result = ConversionResult.model_validate(
                        cached_payload.get("conversion_result")
                    )
                except Exception:  # noqa: BLE001
                    cached_payload = None
                else:
                    single_book_split_cache_hit = True
                    single_book_split_cache_payload = cached_payload
                    conversion_seconds = max(
                        0.0,
                        _safe_float(cached_payload.get("conversion_seconds")) or 0.0,
                    )
                    split_wait_seconds = max(
                        0.0,
                        _safe_float(cached_payload.get("split_wait_seconds")) or 0.0,
                    )
                    split_convert_seconds = max(
                        0.0,
                        _safe_float(cached_payload.get("split_convert_seconds")) or 0.0,
                    )
                    _notify("Reusing single-book split cache conversion payload.")
                    if single_book_split_cache_lock_acquired:
                        _release_single_book_split_cache_lock(
                            single_book_split_cache_lock_path
                        )
                        single_book_split_cache_lock_acquired = False

    if deterministic_prep_bundle is not None:
        prep_bundle_boundary_result = (
            load_recipe_boundary_result_from_deterministic_prep_bundle(
                deterministic_prep_bundle
            )
        )
        result = prep_bundle_boundary_result.conversion_result
        conversion_seconds = max(
            0.0,
            _safe_float(deterministic_prep_bundle.timing.get("conversion_seconds"))
            or conversion_seconds,
        )
        _notify("Reusing deterministic prep bundle conversion payload.")
        _notify_scheduler_event_callback(
            scheduler_event_callback,
            event="prep_bundle_reused",
            prep_key=deterministic_prep_bundle.prep_key,
        )
    elif not shared_conversion_cache_hit and not single_book_split_cache_hit:
        conversion_started = time.monotonic()
        try:
            with _temporary_epub_runtime_env(
                extractor=selected_epub_extractor,
                html_parser_version=selected_html_parser_version,
                skip_headers_footers=selected_skip_headers_footers,
                preprocess_mode=selected_preprocess_mode,
            ):
                job_specs = plan_source_job(
                    path,
                    pdf_split_workers=pdf_split_workers,
                    epub_split_workers=epub_split_workers,
                    pdf_pages_per_job=pdf_pages_per_job,
                    epub_spine_items_per_job=epub_spine_items_per_job,
                    epub_extractor=selected_epub_extractor,
                )
                if len(job_specs) == 1:
                    result = importer.convert(
                        path,
                        run_mapping,
                        progress_callback=_notify,
                        run_settings=run_settings,
                    )
                else:
                    split_slot_context = nullcontext()
                    normalized_split_slots = _normalize_split_phase_slots(split_phase_slots)
                    if normalized_split_slots is not None:
                        split_slot_context = _acquire_split_phase_slot(
                            slots=normalized_split_slots,
                            gate_dir=split_phase_gate_dir,
                            notify=progress_callback,
                            status_label=split_phase_status_label,
                        )

                    _notify_scheduler_event_callback(
                        scheduler_event_callback,
                        event="split_wait_started",
                        split_job_count=len(job_specs),
                        split_slots=normalized_split_slots,
                    )
                    split_wait_started = time.monotonic()
                    with split_slot_context:
                        split_wait_seconds = max(0.0, time.monotonic() - split_wait_started)
                        _notify_scheduler_event_callback(
                            scheduler_event_callback,
                            event="split_wait_finished",
                            split_wait_seconds=split_wait_seconds,
                        )
                        split_convert_started = time.monotonic()
                        _notify_scheduler_event_callback(
                            scheduler_event_callback,
                            event="split_active_started",
                            split_job_count=len(job_specs),
                        )
                        effective_workers = max(1, workers)
                        if path.suffix.lower() == ".epub":
                            effective_workers = max(effective_workers, epub_split_workers)
                        if path.suffix.lower() == ".pdf":
                            effective_workers = max(effective_workers, pdf_split_workers)
                        max_workers = min(effective_workers, len(job_specs))

                        def _split_progress_status(current: int) -> str:
                            status = _task_progress_message(
                                "Running split conversion...",
                                current,
                                len(job_specs),
                            )
                            if max_workers > 1:
                                return f"{status} (workers={max_workers})"
                            return status

                        _notify(_split_progress_status(0))
                        job_results: list[dict[str, Any]] = []
                        job_errors: list[str] = []

                        def _run_job_serial(spec: JobSpec) -> None:
                            importer_name, job_result = _parallel_convert_worker(
                                path,
                                pipeline,
                                run_mapping,
                                run_config=worker_run_config,
                                start_page=spec.start_page,
                                end_page=spec.end_page,
                                start_spine=spec.start_spine,
                                end_spine=spec.end_spine,
                            )
                            job_results.append(
                                {
                                    **spec.to_payload(),
                                    "result": job_result,
                                    "importer_name": importer_name,
                                }
                            )

                        def _split_worker_status(spec: JobSpec) -> str:
                            job_number = spec.job_index + 1
                            base = f"job {job_number}/{len(job_specs)}"
                            start_page = spec.start_page
                            end_page = spec.end_page
                            if start_page is not None and end_page is not None:
                                try:
                                    start = int(start_page) + 1
                                    end = max(start, int(end_page))
                                except (TypeError, ValueError):
                                    return base
                                return f"{base} pages {start}-{end}"
                            start_spine = spec.start_spine
                            end_spine = spec.end_spine
                            if start_spine is not None and end_spine is not None:
                                try:
                                    start = int(start_spine) + 1
                                    end = max(start, int(end_spine))
                                except (TypeError, ValueError):
                                    return base
                                return f"{base} spine {start}-{end}"
                            return base

                        def _run_parallel_split_jobs(executor: Any) -> None:
                            if max_workers > 1:
                                _notify(format_worker_activity_reset())
                            pending_specs = list(job_specs)
                            futures: dict[Any, tuple[int, JobSpec]] = {}

                            def _submit(spec: JobSpec, worker_slot: int) -> None:
                                future = executor.submit(
                                    _parallel_convert_worker,
                                    path,
                                    pipeline,
                                    run_mapping,
                                    run_config=worker_run_config,
                                    start_page=spec.start_page,
                                    end_page=spec.end_page,
                                    start_spine=spec.start_spine,
                                    end_spine=spec.end_spine,
                                )
                                futures[future] = (worker_slot, spec)
                                if max_workers > 1:
                                    _notify(
                                        format_worker_activity(
                                            worker_slot,
                                            max_workers,
                                            _split_worker_status(spec),
                                        )
                                    )

                            for worker_slot in range(1, max_workers + 1):
                                if not pending_specs:
                                    break
                                _submit(pending_specs.pop(0), worker_slot)

                            completed = 0
                            while futures:
                                future = next(as_completed(list(futures.keys())))
                                worker_slot, spec = futures.pop(future)
                                try:
                                    importer_name, job_result = future.result()
                                except Exception as exc:
                                    job_errors.append(
                                        f"job {spec.job_index}: {exc}"
                                    )
                                else:
                                    job_results.append(
                                        {
                                            **spec.to_payload(),
                                            "result": job_result,
                                            "importer_name": importer_name,
                                        }
                                    )
                                    completed += 1
                                    _notify(_split_progress_status(completed))
                                if pending_specs:
                                    _submit(pending_specs.pop(0), worker_slot)
                                elif max_workers > 1:
                                    _notify(
                                        format_worker_activity(
                                            worker_slot,
                                            max_workers,
                                            "idle",
                                        )
                                    )

                        def _run_serial_split_jobs() -> None:
                            for spec in job_specs:
                                try:
                                    _run_job_serial(spec)
                                except Exception as exc:  # noqa: BLE001
                                    job_errors.append(
                                        f"job {spec.job_index}: {exc}"
                                    )
                                _notify(_split_progress_status(len(job_results)))
                        try:
                            executor_resolution = resolve_process_thread_executor(
                                max_workers=max_workers,
                                process_unavailable_message=lambda exc: (
                                    "Process-based worker concurrency unavailable "
                                    f"({exc}); using thread-based worker concurrency."
                                ),
                                thread_unavailable_message=lambda exc: (
                                    "Thread-based worker concurrency unavailable "
                                    f"({exc}); running split jobs serially."
                                ),
                            )
                            for message in executor_resolution.messages:
                                _notify(message)
                            if executor_resolution.executor is None:
                                _run_serial_split_jobs()
                            else:
                                executor = executor_resolution.executor
                                try:
                                    _run_parallel_split_jobs(executor)
                                finally:
                                    shutdown_executor(executor, wait=True, cancel_futures=False)
                        finally:
                            if max_workers > 1:
                                _notify(format_worker_activity_reset())

                        if job_errors:
                            raise RuntimeError("Split conversion failed: " + "; ".join(job_errors))
                        if not job_results:
                            raise RuntimeError("Split conversion produced no results.")

                        importer_name = str(job_results[0].get("importer_name") or importer.name)
                        result = _merge_parallel_results(path, importer_name, job_results)
                        _notify("Merged split job results.")
                        split_convert_seconds = max(0.0, time.monotonic() - split_convert_started)
                        _notify_scheduler_event_callback(
                            scheduler_event_callback,
                            event="split_active_finished",
                            split_active_seconds=split_convert_seconds,
                        )
            conversion_seconds = max(0.0, time.monotonic() - conversion_started)

            if not shared_conversion_cache_hit:
                if not shared_conversion_cache_lock_acquired:
                    shared_conversion_cache_lock_acquired = acquire_entry_lock(
                        shared_conversion_cache_lock_path
                    )
                if shared_conversion_cache_lock_acquired:
                    cache_write_payload = {
                        "schema_version": CONVERSION_CACHE_SCHEMA_VERSION,
                        "conversion_cache_key": shared_conversion_cache_key,
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                        "source_file": str(path),
                        "source_hash": file_hash,
                        "book_cache_root": str(resolved_book_cache_root),
                        "run_config_hash": run_config_hash,
                        "run_config_summary": run_config_summary,
                        "conversion_seconds": conversion_seconds,
                        "split_wait_seconds": split_wait_seconds,
                        "split_convert_seconds": split_convert_seconds,
                        "conversion_result": result.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                    }
                    write_json_atomic(shared_conversion_cache_path, cache_write_payload)
                    shared_conversion_cache_payload = cache_write_payload

            if (
                single_book_split_cache_enabled
                and single_book_split_cache_entry_path is not None
                and selected_single_book_split_cache_key is not None
            ):
                if (
                    not single_book_split_cache_lock_acquired
                    and single_book_split_cache_lock_path is not None
                ):
                    single_book_split_cache_lock_acquired = (
                        _acquire_single_book_split_cache_lock(
                            single_book_split_cache_lock_path
                        )
                    )
                if single_book_split_cache_lock_acquired:
                    cache_write_payload = {
                        "schema_version": SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION,
                        "single_book_split_cache_key": selected_single_book_split_cache_key,
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                        "source_file": str(path),
                        "run_config_hash": run_config_hash,
                        "run_config_summary": run_config_summary,
                        "conversion_seconds": conversion_seconds,
                        "split_wait_seconds": split_wait_seconds,
                        "split_convert_seconds": split_convert_seconds,
                        "conversion_result": result.model_dump(
                            mode="json",
                            by_alias=True,
                        ),
                    }
                    _write_single_book_split_cache_entry(
                        cache_path=single_book_split_cache_entry_path,
                        payload=cache_write_payload,
                    )
                    single_book_split_cache_payload = cache_write_payload
        finally:
            if shared_conversion_cache_lock_acquired:
                release_entry_lock(shared_conversion_cache_lock_path)
                shared_conversion_cache_lock_acquired = False
            if (
                single_book_split_cache_lock_acquired
                and single_book_split_cache_lock_path is not None
            ):
                _release_single_book_split_cache_lock(
                    single_book_split_cache_lock_path
                )
                single_book_split_cache_lock_acquired = False
    elif shared_conversion_cache_payload is not None:
        conversion_seconds = max(
            0.0,
            _safe_float(shared_conversion_cache_payload.get("conversion_seconds"))
            or conversion_seconds,
        )
    elif single_book_split_cache_payload is not None:
        conversion_seconds = max(
            0.0,
            _safe_float(single_book_split_cache_payload.get("conversion_seconds"))
            or conversion_seconds,
        )
    _notify_scheduler_event_callback(
        scheduler_event_callback,
        event="prep_finished",
        conversion_seconds=conversion_seconds,
        split_wait_seconds=split_wait_seconds,
    )

    _notify("Computing source file hash...")
    _notify("Building extracted archive...")
    prepared_archive = prepare_extracted_archive(
        result=result,
        raw_artifacts=result.raw_artifacts,
        source_file=path.name,
        source_hash=file_hash,
        archive_builder=build_extracted_archive,
    )
    archive = list(prepared_archive.blocks)
    book_id = result.workbook or path.stem
    authoritative_label_result: LabelFirstStageResult | None = None
    nonrecipe_stage_result: NonRecipeStageResult | None = None
    authority_contract = None
    if prep_bundle_boundary_result is not None:
        authoritative_label_result = prep_bundle_boundary_result.label_first_result
        result = prep_bundle_boundary_result.conversion_result
    elif processed_output_root is None:
        authoritative_label_result = build_label_first_stage_result(
            conversion_result=result,
            source_file=path,
            importer_name=importer.name,
            run_settings=run_settings,
            artifact_root=run_root,
            live_llm_allowed=bool(allow_codex),
            progress_callback=_notify,
        )
        result = authoritative_label_result.updated_conversion_result
        nonrecipe_stage_result = _build_prediction_nonrecipe_stage_result(
            result=result,
            authoritative_label_result=authoritative_label_result,
            notify=_notify,
        )
        if nonrecipe_stage_result is not None:
            authority_contract = build_nonrecipe_authority_contract(
                full_blocks=authoritative_label_result.archive_blocks,
                stage_result=nonrecipe_stage_result,
            )
    line_role_artifacts: dict[str, Path] | None = None
    line_role_recipe_projection_summary: dict[str, Any] | None = None
    archive_payload_rows: list[dict[str, Any]] | None = None
    line_role_candidates: list[AtomicLineCandidate] = []
    if run_settings.line_role_pipeline.value != "off":
        archive_payload_rows = prepared_archive_payload(prepared_archive)
        line_role_candidates = _build_line_role_candidates_from_archive(
            archive_payload=archive_payload_rows,
            result=result,
            atomic_block_splitter=run_settings.atomic_block_splitter.value,
        )
    llm_report: dict[str, Any] = {"enabled": False, "pipeline": "off"}
    _notify_scheduler_event_callback(
        scheduler_event_callback,
        event="post_started",
    )
    processed_run_root: Path | None = None
    processed_report_path: Path | None = None
    stage_block_predictions_source_path: Path | None = None

    if processed_output_root is None and run_settings.llm_recipe_pipeline.value != "off":
        _notify("Running codex-farm recipe pipeline...")
        try:
            llm_apply = run_codex_farm_recipe_pipeline(
                conversion_result=result,
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=book_slug,
                progress_callback=_notify,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                warning = (
                    "LLM recipe pipeline failed; falling back to deterministic outputs: "
                    f"{exc}"
                )
                if result.report is None:
                    result.report = ConversionReport()
                result.report.warnings.append(warning)
                llm_report = {
                    "enabled": True,
                    "pipeline": run_settings.llm_recipe_pipeline.value,
                    "fallbackApplied": True,
                    "fatalError": str(exc),
                }
            else:
                raise
        else:
            result = llm_apply.updated_conversion_result
            llm_report = dict(llm_apply.llm_report)
    if result.report is None:
        result.report = ConversionReport()
    result.report.llm_codex_farm = llm_report

    if processed_output_root is None:
        if nonrecipe_stage_result is not None:
            authority_contract = build_nonrecipe_authority_contract(
                full_blocks=authoritative_label_result.archive_blocks,
                stage_result=nonrecipe_stage_result,
            )
        if (
            run_settings.llm_knowledge_pipeline.value == "off"
            and authority_contract is not None
            and authority_contract.late_output_blocks
        ):
            result.chunks = chunks_from_non_recipe_blocks(
                authority_contract.late_output_blocks
            )
        else:
            result.chunks = []

    if processed_output_root is None and run_settings.llm_knowledge_pipeline.value != "off":
        _notify("Running codex-farm non-recipe finalize...")
        try:
            knowledge_apply = run_codex_farm_nonrecipe_finalize(
                conversion_result=result,
                nonrecipe_stage_result=(
                    nonrecipe_stage_result
                    if nonrecipe_stage_result is not None
                    else _build_prediction_nonrecipe_stage_result(
                        result=result,
                        authoritative_label_result=authoritative_label_result,
                        notify=_notify,
                    )
                ),
                recipe_ownership_result=build_recipe_ownership_result(
                    full_blocks=(
                        authoritative_label_result.archive_blocks
                        if authoritative_label_result is not None
                        else []
                    ),
                    recipe_spans=(
                        authoritative_label_result.recipe_spans
                        if authoritative_label_result is not None
                        else []
                    ),
                    recipes=result.recipes,
                    ownership_mode="recipe_boundary_with_explicit_divestment",
                ),
                run_settings=run_settings,
                run_root=run_root,
                workbook_slug=book_slug,
                progress_callback=_notify,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                warning = (
                    "LLM non-recipe finalize failed; continuing without knowledge artifacts: "
                    f"{exc}"
                )
                result.report.warnings.append(warning)
                llm_report["knowledge"] = {
                    "enabled": True,
                    "pipeline": run_settings.llm_knowledge_pipeline.value,
                    "fallbackApplied": True,
                    "fatalError": str(exc),
                }
            else:
                raise
        else:
            llm_report["knowledge"] = dict(knowledge_apply.llm_report)
            nonrecipe_stage_result = knowledge_apply.refined_stage_result
        result.report.llm_codex_farm = llm_report

    if processed_output_root is None and nonrecipe_stage_result is not None:
        authority_contract = build_nonrecipe_authority_contract(
            full_blocks=authoritative_label_result.archive_blocks,
            stage_result=nonrecipe_stage_result,
        )
        if (
            run_settings.llm_knowledge_pipeline.value == "off"
            and authority_contract.late_output_blocks
        ):
            result.chunks = chunks_from_non_recipe_blocks(
                authority_contract.late_output_blocks
            )
        else:
            result.chunks = []

    if processed_output_root is not None:
        _notify("Writing processed cookbook outputs...")
        _notify("Writing authoritative stage-backed outputs...")
        processed_output_started = time.monotonic()
        processed_run_root = processed_output_root / timestamp
        processed_run_root.mkdir(parents=True, exist_ok=True)
        stage_session_kwargs = {
            "source_file": path,
            "run_root": processed_run_root,
            "run_dt": run_dt,
            "importer_name": importer.name,
            "run_settings": run_settings,
            "run_config": run_config,
            "run_config_hash": run_config_hash,
            "run_config_summary": run_config_summary,
            "mapping_config": run_mapping,
            "write_markdown": write_markdown,
            "progress_callback": _notify,
            "count_diagnostics_path": (
                processed_run_root / f"{path.stem}.report_totals_mismatch_diagnostics.json"
            ),
        }
        if prep_bundle_boundary_result is not None:
            stage_session = execute_stage_import_session_from_recipe_boundary_result(
                recipe_boundary_result=prep_bundle_boundary_result,
                **stage_session_kwargs,
            )
        else:
            stage_session = execute_stage_import_session_from_result(
                result=result,
                **stage_session_kwargs,
            )
        result = stage_session.conversion_result
        authoritative_label_result = stage_session.label_first_result
        nonrecipe_stage_result = stage_session.nonrecipe_stage_result
        llm_report = dict(stage_session.llm_report)
        result.report.llm_codex_farm = llm_report
        processed_report_path = stage_session.report_path
        stage_block_predictions_source_path = (
            stage_session.stage_block_predictions_path
            if stage_session.stage_block_predictions_path.exists()
            else None
        )
        processed_output_write_seconds = max(
            0.0, time.monotonic() - processed_output_started
        )
        _notify("Authoritative stage-backed outputs complete.")

    if authoritative_label_result is not None:
        _notify("Reusing authoritative line labels...")
        (
            line_role_artifacts,
            line_role_recipe_projection_summary,
        ) = _write_authoritative_line_role_artifacts(
            run_root=run_root,
            source_file=path.name,
            source_hash=file_hash,
            workbook_slug=path.stem,
            label_first_result=authoritative_label_result,
            nonrecipe_stage_result=nonrecipe_stage_result,
        )

    run_config.update(_llm_selective_retry_run_config_summary(llm_report))
    run_config_hash = hashlib.sha256(
        json.dumps(
            run_config,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    run_config_summary = summarize_run_config_payload(
        run_config,
        contract=summary_contract,
    )

    task_build_started = time.monotonic()

    tasks: list[dict[str, Any]] = []
    task_ids: list[str] = []
    coverage_payload: dict[str, Any]
    segment_ids: list[str] | None = None
    prelabel_report_path: Path | None = None
    prelabel_errors_path: Path | None = None
    prelabel_prompt_log_path: Path | None = None
    prelabel_summary: dict[str, Any] | None = None
    resolved_segment_focus_blocks: int | None = None
    effective_segment_overlap: int | None = None

    if not archive:
        raise RuntimeError("No extracted blocks available for freeform labeling.")
    if segment_focus_blocks is None:
        resolved_segment_focus_blocks = segment_blocks
    else:
        resolved_segment_focus_blocks = int(segment_focus_blocks)
    if resolved_segment_focus_blocks < 1:
        raise ValueError("segment_focus_blocks must be >= 1")
    if resolved_segment_focus_blocks > segment_blocks:
        raise ValueError("segment_focus_blocks must be <= segment_blocks")
    focus_overlap_floor = max(0, segment_blocks - resolved_segment_focus_blocks)
    effective_segment_overlap = resolve_segment_overlap_for_target(
        total_blocks=len(archive),
        segment_blocks=segment_blocks,
        requested_overlap=segment_overlap,
        target_task_count=target_task_count,
        segment_focus_blocks=resolved_segment_focus_blocks,
    )
    if effective_segment_overlap != segment_overlap:
        reasons: list[str] = []
        if target_task_count is not None:
            reasons.append(f"target tasks {target_task_count}")
        if segment_overlap < focus_overlap_floor:
            reasons.append(
                "focus coverage "
                f"(segment {segment_blocks}, focus {resolved_segment_focus_blocks})"
            )
        if reasons:
            reason_suffix = f", {', '.join(reasons)}"
        else:
            reason_suffix = ""
        _notify(
            "Adjusted freeform overlap to "
            f"{effective_segment_overlap} "
            f"(requested {segment_overlap}{reason_suffix})."
        )
    _notify("Building freeform span tasks...")
    tasks_all = build_freeform_span_tasks(
        archive=archive,
        source_hash=file_hash,
        source_file=path.name,
        book_id=book_id,
        segment_blocks=segment_blocks,
        segment_overlap=effective_segment_overlap,
        segment_focus_blocks=resolved_segment_focus_blocks,
    )
    if not tasks_all:
        raise RuntimeError("No freeform span tasks generated for labeling.")
    coverage_payload = compute_freeform_task_coverage(archive, tasks_all)
    if coverage_payload["extracted_chars"] == 0:
        raise RuntimeError(
            "No text extracted; this may be a scanned document that requires OCR."
        )
    _notify("Sampling freeform span tasks...")
    tasks = sample_freeform_tasks(tasks_all, limit=limit, sample=sample)
    if not tasks:
        raise RuntimeError(
            "No freeform span tasks generated after limit/sample filters."
        )
    if prelabel:
        total_prelabel_tasks = len(tasks)
        _notify(
            _task_progress_message(
                "Running freeform prelabeling...",
                0,
                total_prelabel_tasks,
            )
        )
        provider_cache_dir = prelabel_cache_dir or (run_root / "prelabel_cache")
        provider = _build_prelabel_provider(
            prelabel_provider=normalized_prelabel_provider,
            codex_cmd=codex_cmd,
            codex_model=codex_model,
            codex_reasoning_effort=codex_reasoning_effort,
            codex_farm_root=codex_farm_root,
            codex_farm_workspace_root=codex_farm_workspace_root,
            prelabel_timeout_seconds=prelabel_timeout_seconds,
            prelabel_cache_dir=provider_cache_dir,
            prelabel_track_token_usage=prelabel_track_token_usage,
        )
        provider_cmd = str(
            getattr(provider, "cmd", (codex_cmd or default_codex_cmd()).strip())
        )
        _notify("Checking freeform prelabel model access...")
        preflight_codex_model_access(
            cmd=provider_cmd,
            timeout_s=max(1, int(prelabel_timeout_seconds)),
            model=getattr(provider, "model", None),
            reasoning_effort=getattr(provider, "reasoning_effort", None),
            codex_farm_root=getattr(provider, "codex_farm_root", None),
            codex_farm_workspace_root=getattr(
                provider,
                "codex_farm_workspace_root",
                None,
            ),
        )
        provider_model = getattr(
            provider,
            "model",
            resolve_codex_model(codex_model, cmd=provider_cmd),
        )
        provider_reasoning_effort = getattr(provider, "reasoning_effort", None)
        if provider_reasoning_effort is None:
            provider_reasoning_effort = codex_reasoning_effort_from_cmd(provider_cmd)
        if provider_reasoning_effort is None:
            provider_reasoning_effort = normalize_codex_reasoning_effort(
                codex_reasoning_effort
            )
        if provider_reasoning_effort is None:
            provider_reasoning_effort = default_codex_reasoning_effort(
                cmd=provider_cmd
            )
        provider_account = codex_account_summary(provider_cmd)
        prelabel_prompt_log_path = run_root / "prelabel_prompt_log.md"
        prelabel_prompt_log_path.write_text(
            "\n".join(
                [
                    "# Prelabel Prompt Log",
                    "",
                    f"- Generated at (UTC): {dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec='seconds')}",
                    "- One section per Codex prompt call.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        prelabel_prompt_log_count = 0
        prelabel_errors: list[dict[str, Any]] = []
        prelabel_label_counts: dict[str, int] = {}
        prelabel_success = 0
        rate_limit_stop_event = threading.Event()
        rate_limit_warning_emitted = False
        rate_limit_skip_reason = (
            "Skipped after prior HTTP 429 rate-limit failure from another task."
        )
        effective_prelabel_workers = min(
            total_prelabel_tasks,
            max(1, int(prelabel_workers)),
        )

        def _prelabel_progress_status(current: int) -> str:
            status = _task_progress_message(
                "Running freeform prelabeling...",
                current,
                total_prelabel_tasks,
            )
            if effective_prelabel_workers > 1:
                return f"{status} (workers={effective_prelabel_workers})"
            return status

        def _prelabel_worker_status_label(task_index: int, segment_id: str) -> str:
            segment_summary = segment_id.strip() or "<unknown>"
            segment_parts = segment_summary.rsplit(":", 2)
            if (
                len(segment_parts) == 3
                and segment_parts[1].isdigit()
                and segment_parts[2].isdigit()
            ):
                segment_summary = f"blocks {segment_parts[1]}-{segment_parts[2]}"
            if len(segment_summary) > 72:
                segment_summary = f"{segment_summary[:69]}..."
            return f"task {task_index}/{total_prelabel_tasks} {segment_summary}"

        worker_slot_by_thread: dict[int, int] = {}
        worker_slot_lock = threading.Lock()
        next_worker_slot = 1

        def _resolve_worker_slot() -> int:
            nonlocal next_worker_slot
            thread_id = threading.get_ident()
            with worker_slot_lock:
                existing = worker_slot_by_thread.get(thread_id)
                if existing is not None:
                    return existing
                slot = min(next_worker_slot, effective_prelabel_workers)
                worker_slot_by_thread[thread_id] = slot
                next_worker_slot += 1
                return slot

        def _emit_rate_limit_warning() -> None:
            nonlocal rate_limit_warning_emitted
            if rate_limit_warning_emitted:
                return
            _notify(
                "WARNING: freeform prelabel rate limit (HTTP 429) detected; "
                "halting additional prelabel task requests."
            )
            rate_limit_warning_emitted = True

        def _rate_limit_skip_result(
            *,
            task_index: int,
            task_payload: dict[str, Any],
            segment_id: str | None = None,
        ) -> dict[str, Any]:
            resolved_segment_id = segment_id or (
                _task_id_value(task_payload) or "<unknown>"
            )
            return {
                "task_index": task_index,
                "segment_id": resolved_segment_id,
                "annotation": None,
                "error": rate_limit_skip_reason,
                "prompt_entries": [],
                "task": task_payload,
                "rate_limit": False,
                "rate_limit_skipped": True,
            }

        if effective_prelabel_workers > 1:
            _notify(format_worker_activity_reset())
        _notify(_prelabel_progress_status(0))

        def _run_prelabel_task(
            *,
            task_index: int,
            task_payload: dict[str, Any],
        ) -> dict[str, Any]:
            segment_id = _task_id_value(task_payload) or "<unknown>"
            if rate_limit_stop_event.is_set():
                return _rate_limit_skip_result(
                    task_index=task_index,
                    task_payload=task_payload,
                    segment_id=segment_id,
                )
            prompt_entries: list[dict[str, Any]] = []
            worker_slot: int | None = None
            if effective_prelabel_workers > 1:
                worker_slot = _resolve_worker_slot()
                _notify(
                    format_worker_activity(
                        worker_slot,
                        effective_prelabel_workers,
                        _prelabel_worker_status_label(task_index, segment_id),
                    )
                )

            def _collect_prompt_log(entry: dict[str, Any]) -> None:
                prompt_entries.append(dict(entry))

            try:
                try:
                    annotation = prelabel_freeform_task(
                        task_payload,
                        provider=provider,
                        allowed_labels=set(FREEFORM_ALLOWED_LABELS),
                        prelabel_granularity=normalized_prelabel_granularity,
                        prompt_log_callback=_collect_prompt_log,
                    )
                except Exception as exc:  # noqa: BLE001
                    error_message = str(exc)
                    rate_limited = is_rate_limit_message(error_message)
                    if rate_limited:
                        rate_limit_stop_event.set()
                    return {
                        "task_index": task_index,
                        "segment_id": segment_id,
                        "annotation": None,
                        "error": error_message,
                        "prompt_entries": prompt_entries,
                        "task": task_payload,
                        "rate_limit": rate_limited,
                        "rate_limit_skipped": False,
                    }
                if annotation is None:
                    return {
                        "task_index": task_index,
                        "segment_id": segment_id,
                        "annotation": None,
                        "error": "No valid labels produced by provider output.",
                        "prompt_entries": prompt_entries,
                        "task": task_payload,
                        "rate_limit": False,
                        "rate_limit_skipped": False,
                    }
                return {
                    "task_index": task_index,
                    "segment_id": segment_id,
                    "annotation": annotation,
                    "error": None,
                    "prompt_entries": prompt_entries,
                    "task": task_payload,
                    "rate_limit": False,
                    "rate_limit_skipped": False,
                }
            finally:
                if worker_slot is not None:
                    _notify(
                        format_worker_activity(
                            worker_slot,
                            effective_prelabel_workers,
                            "idle",
                        )
                    )

        task_results: list[dict[str, Any]] = []
        if effective_prelabel_workers == 1:
            for task_index, task in enumerate(tasks, start=1):
                row = _run_prelabel_task(task_index=task_index, task_payload=task)
                task_results.append(row)
                if bool(row.get("rate_limit")):
                    _emit_rate_limit_warning()
                _notify(_prelabel_progress_status(task_index))
        else:
            with ThreadPoolExecutor(max_workers=effective_prelabel_workers) as executor:
                futures = {
                    executor.submit(
                        _run_prelabel_task,
                        task_index=task_index,
                        task_payload=task,
                    ): (task_index, task)
                    for task_index, task in enumerate(tasks, start=1)
                }
                completed_tasks = 0
                for future in as_completed(futures):
                    task_index, task = futures[future]
                    try:
                        row = future.result()
                    except Exception as exc:  # noqa: BLE001
                        error_message = str(exc)
                        rate_limited = is_rate_limit_message(error_message)
                        if rate_limited:
                            rate_limit_stop_event.set()
                        row = {
                            "task_index": task_index,
                            "segment_id": _task_id_value(task)
                            or "<unknown>",
                            "annotation": None,
                            "error": error_message,
                            "prompt_entries": [],
                            "task": task,
                            "rate_limit": rate_limited,
                            "rate_limit_skipped": False,
                        }
                    task_results.append(row)
                    if bool(row.get("rate_limit")):
                        _emit_rate_limit_warning()
                    completed_tasks += 1
                    _notify(_prelabel_progress_status(completed_tasks))
        if effective_prelabel_workers > 1:
            _notify(format_worker_activity_reset())

        task_results.sort(key=lambda row: int(row.get("task_index") or 0))

        for row in task_results:
            prompt_entries = row.get("prompt_entries")
            if not isinstance(prompt_entries, list):
                continue
            for entry in prompt_entries:
                if not isinstance(entry, dict):
                    continue
                payload = dict(entry)
                payload.setdefault("segment_id", row.get("segment_id") or "<unknown>")
                payload["task_index"] = row.get("task_index")
                payload["task_total"] = total_prelabel_tasks
                payload["logged_at"] = dt.datetime.now(
                    tz=dt.timezone.utc
                ).isoformat(timespec="seconds")
                payload["codex_cmd"] = provider_cmd
                payload["codex_model"] = provider_model
                payload["codex_reasoning_effort"] = provider_reasoning_effort
                payload["codex_farm_cmd"] = provider_cmd
                payload["codex_farm_model"] = provider_model
                payload["codex_farm_reasoning_effort"] = provider_reasoning_effort
                payload["codex_account"] = provider_account
                with prelabel_prompt_log_path.open("a", encoding="utf-8") as handle:
                    handle.write(_format_prelabel_prompt_log_entry_markdown(payload))
                prelabel_prompt_log_count += 1

        rate_limit_failure_count = 0
        rate_limit_skipped_count = 0
        for row in task_results:
            segment_id = str(row.get("segment_id") or "<unknown>")
            error = row.get("error")
            if error:
                error_payload: dict[str, Any] = {
                    "segment_id": segment_id,
                    "reason": str(error),
                }
                if bool(row.get("rate_limit")):
                    error_payload["rate_limit"] = True
                    rate_limit_failure_count += 1
                if bool(row.get("rate_limit_skipped")):
                    error_payload["rate_limit_skipped"] = True
                    rate_limit_skipped_count += 1
                prelabel_errors.append(error_payload)
                continue
            annotation = row.get("annotation")
            if not isinstance(annotation, dict):
                prelabel_errors.append(
                    {
                        "segment_id": segment_id,
                        "reason": "No valid labels produced by provider output.",
                    }
                )
                continue
            task_payload = row.get("task")
            prelabel_success += 1
            if isinstance(task_payload, dict):
                annotation_result = annotation.get("result")
                if isinstance(annotation_result, list) and annotation_result:
                    task_payload["annotations"] = [annotation]
            for label in sorted(annotation_labels(annotation)):
                prelabel_label_counts[label] = prelabel_label_counts.get(label, 0) + 1

        prelabel_errors_path = run_root / "prelabel_errors.jsonl"
        if prelabel_errors:
            prelabel_errors_path.write_text(
                "\n".join(
                    json.dumps(row, sort_keys=True) for row in prelabel_errors
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            prelabel_errors_path.write_text("", encoding="utf-8")
        provider_usage = None
        usage_summary = getattr(provider, "usage_summary", None)
        if callable(usage_summary):
            provider_usage = usage_summary()

        prelabel_summary = {
            "enabled": True,
            "provider": normalized_prelabel_provider,
            "codex_backend": "codex-exec",
            "codex_farm_pipeline_id": "prelabel.freeform.v1",
            "granularity": normalized_prelabel_granularity,
            "codex_cmd": provider_cmd,
            "codex_model": provider_model,
            "codex_reasoning_effort": provider_reasoning_effort,
            "codex_farm_cmd": provider_cmd,
            "codex_farm_model": provider_model,
            "codex_farm_reasoning_effort": provider_reasoning_effort,
            "codex_account": provider_account,
            "cache_dir": str(provider_cache_dir),
            "workers": effective_prelabel_workers,
            "task_count": len(tasks),
            "success_count": prelabel_success,
            "failure_count": len(prelabel_errors),
            "rate_limit_stop_triggered": bool(rate_limit_stop_event.is_set()),
            "rate_limit_failure_count": rate_limit_failure_count,
            "rate_limit_skipped_count": rate_limit_skipped_count,
            "allow_partial": bool(prelabel_allow_partial),
            "token_usage_enabled": bool(prelabel_track_token_usage),
            "token_usage": provider_usage if prelabel_track_token_usage else None,
            "label_counts": prelabel_label_counts,
            "errors_path": str(prelabel_errors_path),
            "prompt_log_path": str(prelabel_prompt_log_path),
            "prompt_log_count": prelabel_prompt_log_count,
        }
        prelabel_report_path = run_root / "prelabel_report.json"
        prelabel_report_path.write_text(
            json.dumps(prelabel_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        if rate_limit_stop_event.is_set() and not prelabel_allow_partial:
            raise RuntimeError(
                "Prelabeling stopped after HTTP 429 rate-limit response. "
                "No additional prelabel task calls were sent after the first 429. "
                "Re-run later, or use --prelabel-allow-partial to continue upload "
                "with recorded prelabel failures."
            )
        if prelabel_errors and not prelabel_allow_partial:
            raise RuntimeError(
                "Prelabeling failed for one or more tasks. "
                "Re-run with prelabel_allow_partial=True "
                "(CLI: --prelabel-allow-partial) to continue "
                "while recording failures."
            )

    label_config = build_freeform_label_config()
    segment_ids = [task.get("data", {}).get("segment_id") for task in tasks if task]
    task_ids = [segment_id for segment_id in segment_ids if segment_id]
    task_build_seconds = max(0.0, time.monotonic() - task_build_started)

    _notify("Writing prediction run artifacts...")
    artifact_write_started = time.monotonic()
    archive_path = run_root / "extracted_archive.json"
    stage_archive_source: Path | None = None
    if processed_run_root is not None:
        stage_archive_candidates = sorted(processed_run_root.glob("raw/**/full_text.json"))
        if len(stage_archive_candidates) == 1:
            stage_archive_source = stage_archive_candidates[0]
    if stage_archive_source is not None:
        if mirror_stage_artifacts_into_run_root:
            shutil.copy2(stage_archive_source, archive_path)
        else:
            archive_path = stage_archive_source
    else:
        archive_payload = prepared_archive_payload(prepared_archive)
        archive_path.write_text(
            json.dumps(archive_payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    (run_root / "extracted_text.txt").write_text(
        prepared_archive_text(prepared_archive) + "\n", encoding="utf-8"
    )

    tasks_path: Path | None = None
    tasks_jsonl_status = "written" if write_label_studio_tasks else "skipped_by_config"
    if write_label_studio_tasks:
        tasks_path = run_root / "label_studio_tasks.jsonl"
        tasks_path.write_text(
            "\n".join(json.dumps(task) for task in tasks) + "\n", encoding="utf-8"
        )

    coverage_path = run_root / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            coverage_payload,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    local_stage_block_predictions_path: Path | None = None
    if (
        stage_block_predictions_source_path is not None
        and stage_block_predictions_source_path.exists()
    ):
        if mirror_stage_artifacts_into_run_root:
            local_stage_block_predictions_path = run_root / "stage_block_predictions.json"
            shutil.copy2(
                stage_block_predictions_source_path,
                local_stage_block_predictions_path,
            )
        else:
            local_stage_block_predictions_path = stage_block_predictions_source_path
    scored_stage_block_predictions_path = local_stage_block_predictions_path
    scored_extracted_archive_path = archive_path
    if isinstance(line_role_artifacts, dict):
        line_role_stage_path = line_role_artifacts.get("stage_block_predictions_path")
        line_role_archive_path = line_role_artifacts.get("extracted_archive_path")
        if (
            isinstance(line_role_stage_path, Path)
            and line_role_stage_path.exists()
            and isinstance(line_role_archive_path, Path)
            and line_role_archive_path.exists()
        ):
            scored_stage_block_predictions_path = line_role_stage_path
            scored_extracted_archive_path = line_role_archive_path
        else:
            _notify(
                "Line-role projection artifacts were incomplete; scoring pointers will use "
                "stage-backed artifacts."
            )
    artifact_write_seconds = max(0.0, time.monotonic() - artifact_write_started)

    result_timing_payload = (
        result.report.timing if result.report and isinstance(result.report.timing, dict) else {}
    )
    parsing_seconds = _safe_float(result_timing_payload.get("parsing_seconds"))
    if parsing_seconds is None:
        parsing_seconds = _safe_float(result_timing_payload.get("parsingSeconds"))
    if parsing_seconds is None:
        parsing_seconds = conversion_seconds
    writing_seconds = _safe_float(result_timing_payload.get("writing_seconds"))
    if writing_seconds is None:
        writing_seconds = _safe_float(result_timing_payload.get("writingSeconds"))
    if writing_seconds is None:
        writing_seconds = processed_output_write_seconds
    ocr_seconds = _safe_float(result_timing_payload.get("ocr_seconds"))
    if ocr_seconds is None:
        ocr_seconds = _safe_float(result_timing_payload.get("ocrSeconds"))

    checkpoints: dict[str, float] = {
        "conversion_seconds": conversion_seconds,
        "task_build_seconds": task_build_seconds,
        "artifact_write_seconds": artifact_write_seconds,
    }
    if split_wait_seconds > 0:
        checkpoints["split_wait_seconds"] = split_wait_seconds
    if split_convert_seconds > 0:
        checkpoints["split_convert_seconds"] = split_convert_seconds
    if processed_output_write_seconds > 0:
        checkpoints["processed_output_write_seconds"] = processed_output_write_seconds

    prediction_total_seconds = max(0.0, time.monotonic() - run_started)
    timing_payload = _timing_payload(
        total_seconds=prediction_total_seconds,
        prediction_seconds=prediction_total_seconds,
        parsing_seconds=parsing_seconds,
        writing_seconds=writing_seconds,
        ocr_seconds=ocr_seconds,
        artifact_write_seconds=artifact_write_seconds,
        checkpoints=checkpoints,
    )
    _write_processed_report_timing_best_effort(
        processed_report_path=processed_report_path,
        timing=timing_payload,
        notify=_notify,
    )
    single_book_split_cache_summary: dict[str, Any] | None = None
    if single_book_split_cache_enabled or single_book_split_cache_payload is not None:
        single_book_split_cache_summary = {
            "enabled": bool(single_book_split_cache_enabled),
            "mode": selected_single_book_split_cache_mode,
            "key": selected_single_book_split_cache_key,
            "dir": (
                str(selected_single_book_split_cache_dir)
                if selected_single_book_split_cache_dir is not None
                else None
            ),
            "force": bool(single_book_split_cache_force),
            "hit": bool(single_book_split_cache_hit),
            "entry_path": (
                str(single_book_split_cache_entry_path)
                if single_book_split_cache_entry_path is not None
                else None
            ),
            "source_hash": file_hash,
            "conversion_seconds": conversion_seconds,
            "split_wait_seconds": split_wait_seconds,
            "split_convert_seconds": split_convert_seconds,
            "created_at": (
                str((single_book_split_cache_payload or {}).get("created_at") or "").strip()
                or None
            ),
        }
    book_cache_summary: dict[str, Any] = {
        "root": str(resolved_book_cache_root),
        "source_hash": file_hash,
        "conversion": {
            "key": shared_conversion_cache_key,
            "entry_path": str(shared_conversion_cache_path),
            "hit": bool(shared_conversion_cache_hit),
            "created_at": (
                str((shared_conversion_cache_payload or {}).get("created_at") or "").strip()
                or None
            ),
            "conversion_seconds": conversion_seconds,
            "split_wait_seconds": split_wait_seconds,
            "split_convert_seconds": split_convert_seconds,
        },
    }
    if deterministic_prep_bundle_summary is not None:
        deterministic_prep_bundle_summary["processed_output_write_seconds"] = (
            processed_output_write_seconds
        )
        book_cache_summary["deterministic_prep"] = deterministic_prep_bundle_summary

    manifest = {
        "pipeline": importer.name,
        "importer_name": importer.name,
        "source_file": str(path),
        "source_hash": file_hash,
        "book_id": book_id,
        "recipe_count": len(result.recipes),
        "run_timestamp": run_dt.isoformat(timespec="seconds"),
        "run_config": run_config,
        "run_config_hash": run_config_hash,
        "run_config_summary": run_config_summary,
        "llm_codex_farm": llm_report,
        "processed_run_root": (
            str(processed_run_root) if processed_run_root is not None else None
        ),
        "stage_run_root": (
            str(processed_run_root) if processed_run_root is not None else None
        ),
        "processed_report_path": (
            str(processed_report_path) if processed_report_path is not None else None
        ),
        "stage_block_predictions_path": (
            str(scored_stage_block_predictions_path)
            if scored_stage_block_predictions_path is not None
            else None
        ),
        "extracted_archive_path": str(scored_extracted_archive_path),
        "line_role_pipeline_line_role_predictions_path": (
            str(line_role_artifacts["line_role_predictions_path"])
            if isinstance(line_role_artifacts, dict)
            and line_role_artifacts.get("line_role_predictions_path") is not None
            else None
        ),
        "line_role_pipeline_semantic_predictions_path": (
            str(line_role_artifacts["semantic_line_role_predictions_path"])
            if isinstance(line_role_artifacts, dict)
            and line_role_artifacts.get("semantic_line_role_predictions_path") is not None
            else None
        ),
        "line_role_pipeline_telemetry_path": (
            str(line_role_artifacts["telemetry_summary_path"])
            if isinstance(line_role_artifacts, dict)
            and line_role_artifacts.get("telemetry_summary_path") is not None
            else None
        ),
        "line_role_pipeline_projected_spans_path": (
            str(line_role_artifacts["projected_spans_path"])
            if isinstance(line_role_artifacts, dict)
            and line_role_artifacts.get("projected_spans_path") is not None
            else None
        ),
        "line_role_pipeline_recipe_projection": line_role_recipe_projection_summary,
        "task_scope": "freeform-spans",
        "segment_blocks": segment_blocks,
        "segment_focus_blocks": resolved_segment_focus_blocks,
        "segment_overlap": effective_segment_overlap,
        "segment_overlap_requested": segment_overlap,
        "segment_overlap_effective": effective_segment_overlap,
        "target_task_count": target_task_count,
        "write_markdown": bool(write_markdown),
        "write_label_studio_tasks": bool(write_label_studio_tasks),
        "tasks_jsonl_status": tasks_jsonl_status,
        "tasks_jsonl_path": str(tasks_path) if tasks_path is not None else None,
        "timing": timing_payload,
        "task_count": len(tasks),
        "task_ids": task_ids,
        "segment_ids": segment_ids,
        "coverage": coverage_payload,
        "prelabel": prelabel_summary,
        "prelabel_report_path": (
            str(prelabel_report_path) if prelabel_report_path is not None else None
        ),
        "prelabel_errors_path": (
            str(prelabel_errors_path) if prelabel_errors_path is not None else None
        ),
        "prelabel_prompt_log_path": (
            str(prelabel_prompt_log_path) if prelabel_prompt_log_path is not None else None
        ),
    }
    manifest["book_cache"] = book_cache_summary
    if single_book_split_cache_summary is not None:
        manifest["single_book_split_cache"] = single_book_split_cache_summary
    if deterministic_prep_bundle_summary is not None:
        manifest["deterministic_prep_bundle"] = deterministic_prep_bundle_summary

    prompt_budget_summary_path: Path | None = None
    prompt_budget_summary = build_prediction_run_prompt_budget_summary(
        manifest,
        run_root,
    )
    if isinstance(prompt_budget_summary.get("by_stage"), dict) and prompt_budget_summary["by_stage"]:
        prompt_budget_summary_path = write_prediction_run_prompt_budget_summary(
            run_root,
            prompt_budget_summary,
        )
        manifest["prompt_budget_summary_path"] = str(prompt_budget_summary_path)

    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    run_manifest_artifacts: dict[str, Any] = {
        "tasks_jsonl_status": tasks_jsonl_status,
        "prediction_manifest_json": "manifest.json",
        "coverage_json": "coverage.json",
        "extracted_archive_json": _path_for_manifest(
            run_root, scored_extracted_archive_path
        ),
        "extracted_text": "extracted_text.txt",
    }
    tasks_manifest_path = _path_for_manifest(run_root, tasks_path)
    if tasks_manifest_path:
        run_manifest_artifacts["tasks_jsonl"] = tasks_manifest_path
    if prelabel_report_path is not None:
        run_manifest_artifacts["prelabel_report_json"] = _path_for_manifest(
            run_root, prelabel_report_path
        )
    if prelabel_errors_path is not None:
        run_manifest_artifacts["prelabel_errors_jsonl"] = _path_for_manifest(
            run_root, prelabel_errors_path
        )
    if prelabel_prompt_log_path is not None:
        run_manifest_artifacts["prelabel_prompt_log_md"] = _path_for_manifest(
            run_root, prelabel_prompt_log_path
        )
    processed_run_path = _path_for_manifest(run_root, processed_run_root)
    if processed_run_path:
        run_manifest_artifacts["processed_output_run_dir"] = processed_run_path
        run_manifest_artifacts["stage_run_dir"] = processed_run_path
    processed_report_manifest_path = _path_for_manifest(run_root, processed_report_path)
    if processed_report_manifest_path:
        run_manifest_artifacts["processed_report_json"] = processed_report_manifest_path
    local_stage_predictions_manifest_path = _path_for_manifest(
        run_root,
        scored_stage_block_predictions_path,
    )
    if local_stage_predictions_manifest_path:
        run_manifest_artifacts[
            "stage_block_predictions_json"
        ] = local_stage_predictions_manifest_path
    if isinstance(line_role_artifacts, dict):
        line_role_predictions_manifest_path = _path_for_manifest(
            run_root,
            line_role_artifacts.get("line_role_predictions_path"),
        )
        if line_role_predictions_manifest_path:
            run_manifest_artifacts[
                "line_role_pipeline_line_role_predictions_jsonl"
            ] = line_role_predictions_manifest_path
        line_role_telemetry_manifest_path = _path_for_manifest(
            run_root,
            line_role_artifacts.get("telemetry_summary_path"),
        )
        if line_role_telemetry_manifest_path:
            run_manifest_artifacts[
                "line_role_pipeline_telemetry_json"
            ] = line_role_telemetry_manifest_path
        line_role_spans_manifest_path = _path_for_manifest(
            run_root,
            line_role_artifacts.get("projected_spans_path"),
        )
        if line_role_spans_manifest_path:
            run_manifest_artifacts[
                "line_role_pipeline_projected_spans_jsonl"
            ] = line_role_spans_manifest_path
    if line_role_recipe_projection_summary is not None:
        run_manifest_artifacts[
            "line_role_pipeline_recipe_projection"
        ] = dict(line_role_recipe_projection_summary)
    if prompt_budget_summary_path is not None:
        run_manifest_artifacts["prompt_budget_summary_json"] = _path_for_manifest(
            run_root,
            prompt_budget_summary_path,
        )
        run_manifest_artifacts["actual_costs_json"] = _path_for_manifest(
            run_root,
            prompt_budget_summary_path,
        )
    run_manifest_artifacts["timing"] = timing_payload
    llm_manifest_candidates = [
        run_root / "raw" / "llm" / _slugify_name(path.stem) / RECIPE_MANIFEST_FILE_NAME,
    ]
    if processed_run_root is not None:
        llm_manifest_candidates.append(
            processed_run_root
            / "raw"
            / "llm"
            / _slugify_name(path.stem)
            / RECIPE_MANIFEST_FILE_NAME
        )
    llm_manifest_path = next(
        (candidate for candidate in llm_manifest_candidates if candidate.exists()),
        llm_manifest_candidates[0],
    )
    if llm_manifest_path.exists():
        recipe_guardrail_report_manifest_path = _path_for_manifest(
            run_root,
            llm_manifest_path.parent / "guardrail_report.json",
        )
        if recipe_guardrail_report_manifest_path:
            run_manifest_artifacts[
                "recipe_codex_guardrail_report_json"
            ] = recipe_guardrail_report_manifest_path
        recipe_guardrail_rows_manifest_path = _path_for_manifest(
            run_root,
            llm_manifest_path.parent / "guardrail_rows.jsonl",
        )
        if recipe_guardrail_rows_manifest_path:
            run_manifest_artifacts[
                "recipe_codex_guardrail_rows_jsonl"
            ] = recipe_guardrail_rows_manifest_path
        llm_run_dir = llm_manifest_path.parent
        prompt_inputs_manifest_path = run_root / "prompt_inputs_manifest.txt"
        prompt_outputs_manifest_path = run_root / "prompt_outputs_manifest.txt"
        prompt_input_dirs = (
            llm_run_dir / "recipe_phase_runtime" / "inputs",
        )
        prompt_output_dirs = (
            llm_run_dir / "recipe_phase_runtime" / "proposals",
        )

        def _build_prompt_manifest(
            source_dirs: tuple[Path, ...], target_path: Path
        ) -> str | None:
            prompt_paths: list[str] = []
            for source_dir in source_dirs:
                if not source_dir.exists():
                    continue
                for prompt_file in sorted(source_dir.glob("*.json"), key=lambda p: p.name):
                    rel_path = _path_for_manifest(run_root, prompt_file)
                    if rel_path is not None:
                        prompt_paths.append(rel_path)
            target_path.write_text("\n".join(prompt_paths) + ("\n" if prompt_paths else ""), encoding="utf-8")
            return _path_for_manifest(run_root, target_path)

        prompt_inputs_manifest = _build_prompt_manifest(
            source_dirs=prompt_input_dirs,
            target_path=prompt_inputs_manifest_path,
        )
        prompt_outputs_manifest = _build_prompt_manifest(
            source_dirs=prompt_output_dirs,
            target_path=prompt_outputs_manifest_path,
        )
        if prompt_inputs_manifest is not None:
            run_manifest_artifacts[
                "prompt_inputs_manifest_txt"
            ] = prompt_inputs_manifest
        if prompt_outputs_manifest is not None:
            run_manifest_artifacts[
                "prompt_outputs_manifest_txt"
            ] = prompt_outputs_manifest
        run_manifest_artifacts["recipe_manifest_json"] = _path_for_manifest(
            run_root,
            llm_manifest_path,
        )

    stage_observability_report = build_stage_observability_report(
        run_root=run_root,
        run_kind=run_manifest_kind,
        created_at=run_dt.isoformat(timespec="seconds"),
        run_config=run_config,
        artifact_scan_root=processed_run_root,
    )
    stage_observability_path = write_stage_observability_report(
        run_root=run_root,
        report=stage_observability_report,
    )
    run_manifest_artifacts["stage_observability_json"] = _path_for_manifest(
        run_root,
        stage_observability_path,
    )

    run_manifest_run_config = dict(run_config)
    run_manifest_run_config["book_cache"] = book_cache_summary
    if single_book_split_cache_summary is not None:
        run_manifest_run_config["single_book_split_cache"] = (
            single_book_split_cache_summary
        )
    if deterministic_prep_bundle_summary is not None:
        run_manifest_run_config["deterministic_prep_bundle"] = (
            deterministic_prep_bundle_summary
        )

    run_manifest_payload = RunManifest(
        run_kind=run_manifest_kind,
        run_id=run_root.name,
        created_at=run_dt.isoformat(timespec="seconds"),
        source=RunSource(
            path=str(path),
            source_hash=file_hash,
            importer_name=importer.name,
        ),
        run_config=run_manifest_run_config,
        artifacts=run_manifest_artifacts,
    )
    _write_manifest_best_effort(run_root, run_manifest_payload, notify=_notify)
    _notify("Prediction run artifacts complete.")
    _notify_scheduler_event_callback(
        scheduler_event_callback,
        event="post_finished",
        prediction_total_seconds=prediction_total_seconds,
        task_count=len(tasks),
    )

    return {
        "run_root": run_root,
        "processed_run_root": processed_run_root,
        "stage_run_root": processed_run_root,
        "extracted_archive_path": scored_extracted_archive_path,
        "processed_report_path": processed_report_path,
        "stage_block_predictions_path": scored_stage_block_predictions_path,
        "line_role_pipeline_line_role_predictions_path": (
            line_role_artifacts.get("line_role_predictions_path")
            if isinstance(line_role_artifacts, dict)
            else None
        ),
        "line_role_pipeline_semantic_predictions_path": (
            line_role_artifacts.get("semantic_line_role_predictions_path")
            if isinstance(line_role_artifacts, dict)
            else None
        ),
        "line_role_pipeline_projected_spans_path": (
            line_role_artifacts.get("projected_spans_path")
            if isinstance(line_role_artifacts, dict)
            else None
        ),
        "prompt_budget_summary_path": prompt_budget_summary_path,
        "line_role_pipeline_recipe_projection": line_role_recipe_projection_summary,
        "tasks_total": len(tasks),
        "tasks_jsonl_path": tasks_path,
        "tasks_jsonl_status": tasks_jsonl_status,
        "manifest_path": manifest_path,
        "tasks": tasks,
        "task_ids": task_ids,
        "segment_ids": segment_ids,
        "coverage": coverage_payload,
        "prelabel": prelabel_summary,
        "prelabel_report_path": prelabel_report_path,
        "prelabel_errors_path": prelabel_errors_path,
        "prelabel_prompt_log_path": prelabel_prompt_log_path,
        "label_config": label_config,
        "importer_name": importer.name,
        "run_config": run_config,
        "run_config_hash": run_config_hash,
        "run_config_summary": run_config_summary,
        "book_cache": book_cache_summary,
        "single_book_split_cache": single_book_split_cache_summary,
        "deterministic_prep_bundle": deterministic_prep_bundle_summary,
        "llm_codex_farm": llm_report,
        "book_id": book_id,
        "file_hash": file_hash,
        "conversion_result": result.model_dump(mode="json", by_alias=True),
        "segment_focus_blocks": resolved_segment_focus_blocks,
        "segment_overlap_requested": segment_overlap,
        "segment_overlap_effective": effective_segment_overlap,
        "target_task_count": target_task_count,
        "timing": timing_payload,
    }
