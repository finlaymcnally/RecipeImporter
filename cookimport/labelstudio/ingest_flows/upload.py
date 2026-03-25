from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Callable

from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.ingest_flows.artifacts import (
    _path_for_manifest,
    _write_manifest_best_effort,
)
from cookimport.labelstudio.ingest_flows.normalize import (
    _normalize_prelabel_upload_as,
)
from cookimport.labelstudio.ingest_flows.prediction_run import generate_pred_run_artifacts
from cookimport.labelstudio.ingest_support import (
    _annotations_to_predictions,
    _dedupe_project_name,
    _find_latest_manifest,
    _load_task_ids_from_jsonl,
    _notify_progress_callback,
    _resolve_project_name,
    _strip_task_annotations,
    _task_annotation_pairs_for_upload,
    _task_id_key,
    _task_id_value,
)
from cookimport.labelstudio.prelabel import PRELABEL_GRANULARITY_BLOCK
from cookimport.runs import RunManifest, RunSource


def run_labelstudio_import(
    *,
    path: Path,
    output_dir: Path,
    pipeline: str,
    project_name: str | None,
    segment_blocks: int = 40,
    segment_overlap: int = 5,
    segment_focus_blocks: int | None = None,
    target_task_count: int | None = None,
    overwrite: bool,
    resume: bool,
    label_studio_url: str,
    label_studio_api_key: str,
    limit: int | None,
    sample: int | None,
    progress_callback: Callable[[str], None] | None = None,
    workers: int = 1,
    pdf_split_workers: int = 1,
    epub_split_workers: int = 1,
    pdf_pages_per_job: int = 50,
    epub_spine_items_per_job: int = 10,
    epub_extractor: str | None = None,
    epub_unstructured_html_parser_version: str | None = None,
    epub_unstructured_skip_headers_footers: bool | str | None = None,
    epub_unstructured_preprocess_mode: str | None = None,
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
    line_role_prompt_target_count: int = 5,
    codex_farm_cmd: str = "codex-farm",
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | None = None,
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_pipeline_knowledge: str = "recipe.knowledge.packet.v1",
    codex_farm_context_blocks: int = 30,
    codex_farm_knowledge_context_blocks: int = 2,
    codex_farm_recipe_mode: str = "extract",
    codex_farm_failure_mode: str = "fail",
    codex_execution_policy: str = "execute",
    processed_output_root: Path | None = None,
    split_phase_slots: int | None = None,
    split_phase_gate_dir: Path | str | None = None,
    split_phase_status_label: str | None = None,
    single_book_split_cache_mode: str = "off",
    single_book_split_cache_dir: Path | str | None = None,
    single_book_split_cache_key: str | None = None,
    single_book_split_cache_force: bool = False,
    prelabel: bool = False,
    prelabel_provider: str = "codex-farm",
    codex_cmd: str | None = None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
    prelabel_timeout_seconds: int = 600,
    prelabel_cache_dir: Path | None = None,
    prelabel_workers: int = 15,
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
    prelabel_upload_as: str = "annotations",
    prelabel_allow_partial: bool = False,
    prelabel_track_token_usage: bool = True,
    scheduler_event_callback: Callable[[dict[str, Any]], None] | None = None,
    auto_project_name_on_scope_mismatch: bool = False,
    allow_codex: bool = False,
    allow_labelstudio_write: bool = False,
    run_root_override: Path | str | None = None,
    mirror_stage_artifacts_into_run_root: bool = True,
) -> dict[str, Any]:
    def _notify(message: str) -> None:
        _notify_progress_callback(progress_callback, message)

    if not allow_labelstudio_write:
        raise RuntimeError(
            "Label Studio write blocked. Re-run with explicit upload consent "
            "(allow_labelstudio_write=True)."
        )

    # Generate all artifacts offline first
    pred = generate_pred_run_artifacts(
        path=path,
        output_dir=output_dir,
        pipeline=pipeline,
        segment_blocks=segment_blocks,
        segment_overlap=segment_overlap,
        segment_focus_blocks=segment_focus_blocks,
        target_task_count=target_task_count,
        limit=limit,
        sample=sample,
        workers=workers,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        epub_extractor=epub_extractor,
        epub_unstructured_html_parser_version=epub_unstructured_html_parser_version,
        epub_unstructured_skip_headers_footers=epub_unstructured_skip_headers_footers,
        epub_unstructured_preprocess_mode=epub_unstructured_preprocess_mode,
        ocr_device=ocr_device,
        pdf_ocr_policy=pdf_ocr_policy,
        ocr_batch_size=ocr_batch_size,
        pdf_column_gap_ratio=pdf_column_gap_ratio,
        warm_models=warm_models,
        section_detector_backend=section_detector_backend,
        multi_recipe_splitter=multi_recipe_splitter,
        multi_recipe_trace=multi_recipe_trace,
        multi_recipe_min_ingredient_lines=multi_recipe_min_ingredient_lines,
        multi_recipe_min_instruction_lines=multi_recipe_min_instruction_lines,
        multi_recipe_for_the_guardrail=multi_recipe_for_the_guardrail,
        instruction_step_segmentation_policy=instruction_step_segmentation_policy,
        instruction_step_segmenter=instruction_step_segmenter,
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
        p6_emit_metadata_debug=p6_emit_metadata_debug,
        recipe_scorer_backend=recipe_scorer_backend,
        recipe_score_gold_min=recipe_score_gold_min,
        recipe_score_silver_min=recipe_score_silver_min,
        recipe_score_bronze_min=recipe_score_bronze_min,
        recipe_score_min_ingredient_lines=recipe_score_min_ingredient_lines,
        recipe_score_min_instruction_lines=recipe_score_min_instruction_lines,
        llm_recipe_pipeline=llm_recipe_pipeline,
        llm_knowledge_pipeline=llm_knowledge_pipeline,
        recipe_prompt_target_count=recipe_prompt_target_count,
        knowledge_prompt_target_count=knowledge_prompt_target_count,
        line_role_prompt_target_count=line_role_prompt_target_count,
        codex_farm_cmd=codex_farm_cmd,
        codex_farm_model=codex_farm_model,
        codex_farm_reasoning_effort=codex_farm_reasoning_effort,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        codex_farm_pipeline_knowledge=codex_farm_pipeline_knowledge,
        codex_farm_context_blocks=codex_farm_context_blocks,
        codex_farm_knowledge_context_blocks=codex_farm_knowledge_context_blocks,
        codex_farm_recipe_mode=codex_farm_recipe_mode,
        codex_farm_failure_mode=codex_farm_failure_mode,
        codex_execution_policy=codex_execution_policy,
        processed_output_root=processed_output_root,
        split_phase_slots=split_phase_slots,
        split_phase_gate_dir=split_phase_gate_dir,
        split_phase_status_label=split_phase_status_label,
        single_book_split_cache_mode=single_book_split_cache_mode,
        single_book_split_cache_dir=single_book_split_cache_dir,
        single_book_split_cache_key=single_book_split_cache_key,
        single_book_split_cache_force=single_book_split_cache_force,
        prelabel=prelabel,
        prelabel_provider=prelabel_provider,
        codex_cmd=codex_cmd,
        codex_model=codex_model,
        codex_reasoning_effort=codex_reasoning_effort,
        prelabel_timeout_seconds=prelabel_timeout_seconds,
        prelabel_cache_dir=prelabel_cache_dir,
        prelabel_workers=prelabel_workers,
        prelabel_granularity=prelabel_granularity,
        prelabel_allow_partial=prelabel_allow_partial,
        prelabel_track_token_usage=prelabel_track_token_usage,
        allow_codex=allow_codex,
        codex_command_context="labelstudio_import",
        scheduler_event_callback=scheduler_event_callback,
        progress_callback=_notify,
        run_manifest_kind="labelstudio_import",
        run_root_override=run_root_override,
        mirror_stage_artifacts_into_run_root=mirror_stage_artifacts_into_run_root,
    )

    run_root = pred["run_root"]
    tasks = pred["tasks"]
    label_config = pred["label_config"]
    upload_as = _normalize_prelabel_upload_as(prelabel_upload_as)

    # Label Studio upload
    client = LabelStudioClient(label_studio_url, label_studio_api_key)
    _notify("Resolving Label Studio project...")
    project_title = _resolve_project_name(path, project_name, client)

    existing_project = client.find_project_by_title(project_title)
    if overwrite and existing_project:
        client.delete_project(existing_project["id"])
        existing_project = None

    had_existing_project = existing_project is not None
    project = existing_project
    if project is None:
        project = client.create_project(
            project_title,
            label_config,
            description="Cookbook benchmarking project (auto-generated)",
        )

    project_id = project.get("id")
    if project_id is None:
        raise RuntimeError("Label Studio project creation failed (missing id).")

    supported_scope = "freeform-spans"
    existing_task_ids: set[str] = set()
    resume_source: str | None = None
    if resume and not overwrite and had_existing_project:
        _notify("Checking resume metadata for existing tasks...")
        manifest_path = _find_latest_manifest(output_dir, project_title)
        if manifest_path and manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            resume_scope = str(payload.get("task_scope") or supported_scope)
            if resume_scope != supported_scope:
                if auto_project_name_on_scope_mismatch and project_name is None:
                    _notify(
                        f"Existing project uses task_scope={resume_scope}; "
                        f"creating a new project for task_scope={supported_scope}."
                    )
                    existing_titles = {
                        str(candidate.get("title", ""))
                        for candidate in client.list_projects()
                        if isinstance(candidate, dict) and candidate.get("title")
                    }
                    project_title = _dedupe_project_name(project_title, existing_titles)
                    project = client.create_project(
                        project_title,
                        label_config,
                        description="Cookbook benchmarking project (auto-generated)",
                    )
                    project_id = project.get("id")
                    if project_id is None:
                        raise RuntimeError("Label Studio project creation failed (missing id).")
                    had_existing_project = False
                else:
                    raise RuntimeError(
                        f"Existing project uses task_scope={resume_scope}; "
                        "use a freeform-spans project or a new project name."
                    )
            else:
                resume_source = str(manifest_path)
                existing_task_ids = set(
                    payload.get("segment_ids")
                    or payload.get("task_ids")
                    or []
                )
                tasks_path = manifest_path.parent / "label_studio_tasks.jsonl"
                if not existing_task_ids and tasks_path.exists():
                    existing_task_ids = _load_task_ids_from_jsonl(tasks_path, _task_id_key())

    upload_tasks: list[dict[str, Any]] = []
    for task in tasks:
        task_id = _task_id_value(task)
        if task_id and task_id in existing_task_ids:
            continue
        if prelabel and upload_as == "predictions":
            upload_tasks.append(_annotations_to_predictions(task))
        else:
            upload_tasks.append(task)

    batch_size = 200
    uploaded_count = 0
    inline_annotation_fallback = False
    inline_annotation_fallback_error: str | None = None
    post_import_annotation_pairs: list[tuple[str, dict[str, Any]]] = []
    post_import_annotations_created = 0
    post_import_annotation_errors: list[str] = []
    if upload_tasks:
        total_batches = (len(upload_tasks) + batch_size - 1) // batch_size
        _notify(f"Uploading {len(upload_tasks)} task(s) in {total_batches} batch(es)...")
    else:
        _notify("No new tasks to upload (resume skipped existing tasks).")
    for start in range(0, len(upload_tasks), batch_size):
        batch = upload_tasks[start : start + batch_size]
        if not batch:
            continue
        use_inline_annotations = (
            prelabel
            and upload_as == "annotations"
        )
        if use_inline_annotations:
            if inline_annotation_fallback:
                client.import_tasks(
                    project_id,
                    [_strip_task_annotations(task) for task in batch],
                )
                post_import_annotation_pairs.extend(
                    _task_annotation_pairs_for_upload(batch)
                )
            else:
                try:
                    client.import_tasks(project_id, batch)
                except Exception as exc:  # noqa: BLE001
                    inline_annotation_fallback = True
                    inline_annotation_fallback_error = str(exc)
                    _notify(
                        "Inline annotation import failed; retrying with "
                        "task-only upload and post-import annotation creation."
                    )
                    client.import_tasks(
                        project_id,
                        [_strip_task_annotations(task) for task in batch],
                    )
                    post_import_annotation_pairs.extend(
                        _task_annotation_pairs_for_upload(batch)
                    )
        else:
            client.import_tasks(project_id, batch)
        uploaded_count += len(batch)
        _notify(f"Uploaded {uploaded_count}/{len(upload_tasks)} task(s).")

    if inline_annotation_fallback and post_import_annotation_pairs:
        _notify("Resolving task IDs for post-import annotation creation...")
        remote_tasks = client.list_project_tasks(project_id)
        remote_task_ids: dict[str, int] = {}
        for remote_task in remote_tasks:
            if not isinstance(remote_task, dict):
                continue
            task_id = _task_id_value(remote_task)
            if not task_id:
                continue
            remote_id = remote_task.get("id")
            try:
                remote_task_ids[task_id] = int(remote_id)
            except (TypeError, ValueError):
                continue

        _notify(
            f"Creating {len(post_import_annotation_pairs)} annotation(s) "
            "through Label Studio API..."
        )
        for task_id_value, annotation in post_import_annotation_pairs:
            labelstudio_task_id = remote_task_ids.get(task_id_value)
            if labelstudio_task_id is None:
                post_import_annotation_errors.append(
                    f"task id lookup failed for {task_id_value}"
                )
                continue
            try:
                client.create_annotation(labelstudio_task_id, annotation)
                post_import_annotations_created += 1
            except Exception as exc:  # noqa: BLE001
                post_import_annotation_errors.append(
                    f"task {task_id_value}: {exc}"
                )

        if post_import_annotation_errors:
            if prelabel_allow_partial:
                _notify(
                    "Warning: some post-import annotations failed and were skipped."
                )
            else:
                joined = "; ".join(post_import_annotation_errors[:8])
                raise RuntimeError(
                    "Post-import annotation creation failed: "
                    + joined
                )

    # Update manifest with LS-specific fields
    manifest_path = pred["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "project_name": project_title,
        "project_id": project_id,
        "uploaded_task_count": uploaded_count,
        "resume_source": resume_source,
        "label_studio_url": label_studio_url,
        "prelabel_enabled": bool(prelabel),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_inline_annotations_fallback_error": inline_annotation_fallback_error,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_error_count": len(post_import_annotation_errors),
    })
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    project_path = run_root / "project.json"
    project_path.write_text(
        json.dumps(project, indent=2, sort_keys=True), encoding="utf-8"
    )
    run_config_payload = pred.get("run_config")
    if not isinstance(run_config_payload, dict):
        run_config_payload = {}
    run_manifest_artifacts: dict[str, Any] = {
        "tasks_jsonl": "label_studio_tasks.jsonl",
        "prediction_manifest_json": "manifest.json",
        "coverage_json": "coverage.json",
        "extracted_archive_json": "extracted_archive.json",
        "extracted_text": "extracted_text.txt",
        "project_json": "project.json",
        "label_studio_project_name": project_title,
        "label_studio_project_id": project_id,
        "uploaded_task_count": uploaded_count,
        "prelabel_enabled": bool(prelabel),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_error_count": len(post_import_annotation_errors),
    }
    prelabel_report_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_report_path"),
    )
    if prelabel_report_manifest_path:
        run_manifest_artifacts["prelabel_report_json"] = prelabel_report_manifest_path
    prelabel_errors_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_errors_path"),
    )
    if prelabel_errors_manifest_path:
        run_manifest_artifacts["prelabel_errors_jsonl"] = prelabel_errors_manifest_path
    prelabel_prompt_log_manifest_path = _path_for_manifest(
        run_root,
        pred.get("prelabel_prompt_log_path"),
    )
    if prelabel_prompt_log_manifest_path:
        run_manifest_artifacts["prelabel_prompt_log_md"] = (
            prelabel_prompt_log_manifest_path
        )
    processed_run_manifest_path = _path_for_manifest(run_root, pred.get("processed_run_root"))
    if processed_run_manifest_path:
        run_manifest_artifacts["processed_output_run_dir"] = processed_run_manifest_path
    processed_report_manifest_path = _path_for_manifest(
        run_root,
        pred.get("processed_report_path"),
    )
    if processed_report_manifest_path:
        run_manifest_artifacts["processed_report_json"] = processed_report_manifest_path
    line_role_predictions_manifest_path = _path_for_manifest(
        run_root,
        pred.get("line_role_pipeline_line_role_predictions_path"),
    )
    if line_role_predictions_manifest_path:
        run_manifest_artifacts[
            "line_role_pipeline_line_role_predictions_jsonl"
        ] = line_role_predictions_manifest_path
    line_role_spans_manifest_path = _path_for_manifest(
        run_root,
        pred.get("line_role_pipeline_projected_spans_path"),
    )
    if line_role_spans_manifest_path:
        run_manifest_artifacts[
            "line_role_pipeline_projected_spans_jsonl"
        ] = line_role_spans_manifest_path
    if isinstance(pred.get("line_role_pipeline_recipe_projection"), dict):
        run_manifest_artifacts[
            "line_role_pipeline_recipe_projection"
        ] = dict(pred["line_role_pipeline_recipe_projection"])
    prediction_timing = pred.get("timing")
    if isinstance(prediction_timing, dict):
        run_manifest_artifacts["timing"] = dict(prediction_timing)

    run_manifest_payload = RunManifest(
        run_kind="labelstudio_import",
        run_id=run_root.name,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        source=RunSource(
            path=str(path),
            source_hash=str(pred.get("file_hash") or "") or None,
            importer_name=str(pred.get("importer_name") or "") or None,
        ),
        run_config=run_config_payload,
        artifacts=run_manifest_artifacts,
        notes="Label Studio import run with upload metadata.",
    )
    _write_manifest_best_effort(run_root, run_manifest_payload, notify=_notify)
    _notify("Label Studio import artifacts complete.")

    return {
        "project": project,
        "project_name": project_title,
        "project_id": project_id,
        "run_root": run_root,
        "processed_run_root": pred["processed_run_root"],
        "extracted_archive_path": pred.get("extracted_archive_path"),
        "stage_block_predictions_path": pred.get("stage_block_predictions_path"),
        "processed_report_path": pred["processed_report_path"],
        "line_role_pipeline_line_role_predictions_path": pred.get(
            "line_role_pipeline_line_role_predictions_path"
        ),
        "line_role_pipeline_projected_spans_path": pred.get(
            "line_role_pipeline_projected_spans_path"
        ),
        "line_role_pipeline_recipe_projection": pred.get(
            "line_role_pipeline_recipe_projection"
        ),
        "run_config": pred.get("run_config"),
        "run_config_hash": pred.get("run_config_hash"),
        "run_config_summary": pred.get("run_config_summary"),
        "timing": pred.get("timing"),
        "prelabel": pred.get("prelabel"),
        "prelabel_report_path": pred.get("prelabel_report_path"),
        "prelabel_errors_path": pred.get("prelabel_errors_path"),
        "prelabel_prompt_log_path": pred.get("prelabel_prompt_log_path"),
        "prelabel_upload_as": upload_as if prelabel else None,
        "prelabel_inline_annotations_fallback": inline_annotation_fallback,
        "prelabel_post_import_annotations_created": post_import_annotations_created,
        "prelabel_post_import_annotation_errors": post_import_annotation_errors,
        "tasks_total": pred["tasks_total"],
        "tasks_uploaded": uploaded_count,
        "manifest_path": manifest_path,
    }
