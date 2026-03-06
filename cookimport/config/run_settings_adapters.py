from __future__ import annotations

from pathlib import Path
from typing import Any

from cookimport.config.run_settings import RunSettings


def build_stage_call_kwargs_from_run_settings(
    settings: RunSettings,
    *,
    out: Path,
    mapping: Path | None,
    overrides: Path | None,
    limit: int | None,
    write_markdown: bool,
) -> dict[str, Any]:
    """Map canonical RunSettings to kwargs accepted by cli.stage(...)."""
    return {
        "out": out,
        "mapping": mapping,
        "overrides": overrides,
        "limit": limit,
        "workers": settings.workers,
        "pdf_split_workers": settings.pdf_split_workers,
        "epub_split_workers": settings.epub_split_workers,
        "epub_extractor": settings.epub_extractor.value,
        "epub_unstructured_html_parser_version": (
            settings.epub_unstructured_html_parser_version.value
        ),
        "epub_unstructured_skip_headers_footers": (
            settings.epub_unstructured_skip_headers_footers
        ),
        "epub_unstructured_preprocess_mode": (
            settings.epub_unstructured_preprocess_mode.value
        ),
        "table_extraction": settings.table_extraction.value,
        "section_detector_backend": settings.section_detector_backend.value,
        "instruction_step_segmentation_policy": (
            settings.instruction_step_segmentation_policy.value
        ),
        "instruction_step_segmenter": settings.instruction_step_segmenter.value,
        "multi_recipe_splitter": settings.multi_recipe_splitter.value,
        "multi_recipe_trace": settings.multi_recipe_trace,
        "multi_recipe_min_ingredient_lines": (
            settings.multi_recipe_min_ingredient_lines
        ),
        "multi_recipe_min_instruction_lines": (
            settings.multi_recipe_min_instruction_lines
        ),
        "multi_recipe_for_the_guardrail": settings.multi_recipe_for_the_guardrail,
        "web_schema_extractor": settings.web_schema_extractor.value,
        "web_schema_normalizer": settings.web_schema_normalizer.value,
        "web_html_text_extractor": settings.web_html_text_extractor.value,
        "web_schema_policy": settings.web_schema_policy.value,
        "web_schema_min_confidence": settings.web_schema_min_confidence,
        "web_schema_min_ingredients": settings.web_schema_min_ingredients,
        "web_schema_min_instruction_steps": settings.web_schema_min_instruction_steps,
        "ingredient_text_fix_backend": settings.ingredient_text_fix_backend.value,
        "ingredient_pre_normalize_mode": settings.ingredient_pre_normalize_mode.value,
        "ingredient_packaging_mode": settings.ingredient_packaging_mode.value,
        "ingredient_parser_backend": settings.ingredient_parser_backend.value,
        "ingredient_unit_canonicalizer": settings.ingredient_unit_canonicalizer.value,
        "ingredient_missing_unit_policy": settings.ingredient_missing_unit_policy.value,
        "p6_time_backend": settings.p6_time_backend.value,
        "p6_time_total_strategy": settings.p6_time_total_strategy.value,
        "p6_temperature_backend": settings.p6_temperature_backend.value,
        "p6_temperature_unit_backend": settings.p6_temperature_unit_backend.value,
        "p6_ovenlike_mode": settings.p6_ovenlike_mode.value,
        "p6_yield_mode": settings.p6_yield_mode.value,
        "p6_emit_metadata_debug": settings.p6_emit_metadata_debug,
        "recipe_scorer_backend": settings.recipe_scorer_backend,
        "recipe_score_gold_min": settings.recipe_score_gold_min,
        "recipe_score_silver_min": settings.recipe_score_silver_min,
        "recipe_score_bronze_min": settings.recipe_score_bronze_min,
        "recipe_score_min_ingredient_lines": settings.recipe_score_min_ingredient_lines,
        "recipe_score_min_instruction_lines": settings.recipe_score_min_instruction_lines,
        "ocr_device": settings.ocr_device.value,
        "pdf_ocr_policy": settings.pdf_ocr_policy.value,
        "ocr_batch_size": settings.ocr_batch_size,
        "pdf_column_gap_ratio": settings.pdf_column_gap_ratio,
        "pdf_pages_per_job": settings.pdf_pages_per_job,
        "epub_spine_items_per_job": settings.epub_spine_items_per_job,
        "warm_models": settings.warm_models,
        "write_markdown": bool(write_markdown),
        "llm_recipe_pipeline": settings.llm_recipe_pipeline.value,
        "llm_knowledge_pipeline": settings.llm_knowledge_pipeline.value,
        "llm_tags_pipeline": settings.llm_tags_pipeline.value,
        "codex_farm_cmd": settings.codex_farm_cmd,
        "codex_farm_root": settings.codex_farm_root,
        "codex_farm_workspace_root": settings.codex_farm_workspace_root,
        "codex_farm_pass1_pattern_hints_enabled": (
            settings.codex_farm_pass1_pattern_hints_enabled
        ),
        "codex_farm_pipeline_pass1": settings.codex_farm_pipeline_pass1,
        "codex_farm_pipeline_pass2": settings.codex_farm_pipeline_pass2,
        "codex_farm_pipeline_pass3": settings.codex_farm_pipeline_pass3,
        "codex_farm_pass3_skip_pass2_ok": settings.codex_farm_pass3_skip_pass2_ok,
        "codex_farm_pipeline_pass4_knowledge": (
            settings.codex_farm_pipeline_pass4_knowledge
        ),
        "codex_farm_pipeline_pass5_tags": settings.codex_farm_pipeline_pass5_tags,
        "codex_farm_context_blocks": settings.codex_farm_context_blocks,
        "codex_farm_knowledge_context_blocks": (
            settings.codex_farm_knowledge_context_blocks
        ),
        "tag_catalog_json": settings.tag_catalog_json,
        "codex_farm_failure_mode": settings.codex_farm_failure_mode.value,
    }


def build_benchmark_call_kwargs_from_run_settings(
    settings: RunSettings,
    *,
    output_dir: Path,
    eval_output_dir: Path,
    eval_mode: str,
    execution_mode: str,
    no_upload: bool,
    write_markdown: bool,
    write_label_studio_tasks: bool,
    sequence_matcher_override: str | None = None,
    processed_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Map canonical RunSettings to kwargs accepted by cli.labelstudio_benchmark(...)."""
    selected_sequence_matcher = (
        str(sequence_matcher_override).strip().lower()
        if sequence_matcher_override is not None
        else settings.benchmark_sequence_matcher
    )
    payload: dict[str, Any] = {
        "output_dir": output_dir,
        "eval_output_dir": eval_output_dir,
        "eval_mode": eval_mode,
        "execution_mode": execution_mode,
        "sequence_matcher": selected_sequence_matcher,
        "no_upload": bool(no_upload),
        "write_markdown": bool(write_markdown),
        "write_label_studio_tasks": bool(write_label_studio_tasks),
        "epub_extractor": settings.epub_extractor.value,
        "epub_unstructured_html_parser_version": (
            settings.epub_unstructured_html_parser_version.value
        ),
        "epub_unstructured_skip_headers_footers": (
            settings.epub_unstructured_skip_headers_footers
        ),
        "epub_unstructured_preprocess_mode": (
            settings.epub_unstructured_preprocess_mode.value
        ),
        "section_detector_backend": settings.section_detector_backend.value,
        "instruction_step_segmentation_policy": (
            settings.instruction_step_segmentation_policy.value
        ),
        "instruction_step_segmenter": settings.instruction_step_segmenter.value,
        "multi_recipe_splitter": settings.multi_recipe_splitter.value,
        "multi_recipe_trace": settings.multi_recipe_trace,
        "multi_recipe_min_ingredient_lines": (
            settings.multi_recipe_min_ingredient_lines
        ),
        "multi_recipe_min_instruction_lines": (
            settings.multi_recipe_min_instruction_lines
        ),
        "multi_recipe_for_the_guardrail": settings.multi_recipe_for_the_guardrail,
        "web_schema_extractor": settings.web_schema_extractor.value,
        "web_schema_normalizer": settings.web_schema_normalizer.value,
        "web_html_text_extractor": settings.web_html_text_extractor.value,
        "web_schema_policy": settings.web_schema_policy.value,
        "web_schema_min_confidence": settings.web_schema_min_confidence,
        "web_schema_min_ingredients": settings.web_schema_min_ingredients,
        "web_schema_min_instruction_steps": settings.web_schema_min_instruction_steps,
        "ingredient_text_fix_backend": settings.ingredient_text_fix_backend.value,
        "ingredient_pre_normalize_mode": settings.ingredient_pre_normalize_mode.value,
        "ingredient_packaging_mode": settings.ingredient_packaging_mode.value,
        "ingredient_parser_backend": settings.ingredient_parser_backend.value,
        "ingredient_unit_canonicalizer": settings.ingredient_unit_canonicalizer.value,
        "ingredient_missing_unit_policy": settings.ingredient_missing_unit_policy.value,
        "p6_time_backend": settings.p6_time_backend.value,
        "p6_time_total_strategy": settings.p6_time_total_strategy.value,
        "p6_temperature_backend": settings.p6_temperature_backend.value,
        "p6_temperature_unit_backend": settings.p6_temperature_unit_backend.value,
        "p6_ovenlike_mode": settings.p6_ovenlike_mode.value,
        "p6_yield_mode": settings.p6_yield_mode.value,
        "p6_emit_metadata_debug": settings.p6_emit_metadata_debug,
        "ocr_device": settings.ocr_device.value,
        "pdf_ocr_policy": settings.pdf_ocr_policy.value,
        "ocr_batch_size": settings.ocr_batch_size,
        "pdf_column_gap_ratio": settings.pdf_column_gap_ratio,
        "recipe_scorer_backend": settings.recipe_scorer_backend,
        "recipe_score_gold_min": settings.recipe_score_gold_min,
        "recipe_score_silver_min": settings.recipe_score_silver_min,
        "recipe_score_bronze_min": settings.recipe_score_bronze_min,
        "recipe_score_min_ingredient_lines": settings.recipe_score_min_ingredient_lines,
        "recipe_score_min_instruction_lines": settings.recipe_score_min_instruction_lines,
        "warm_models": settings.warm_models,
        "workers": settings.workers,
        "pdf_split_workers": settings.pdf_split_workers,
        "epub_split_workers": settings.epub_split_workers,
        "pdf_pages_per_job": settings.pdf_pages_per_job,
        "epub_spine_items_per_job": settings.epub_spine_items_per_job,
        "llm_recipe_pipeline": settings.llm_recipe_pipeline.value,
        "atomic_block_splitter": settings.atomic_block_splitter.value,
        "line_role_pipeline": settings.line_role_pipeline.value,
        "line_role_guardrail_mode": settings.line_role_guardrail_mode.value,
        "codex_farm_recipe_mode": settings.codex_farm_recipe_mode.value,
        "codex_farm_cmd": settings.codex_farm_cmd,
        "codex_farm_model": settings.codex_farm_model,
        "codex_farm_root": settings.codex_farm_root,
        "codex_farm_workspace_root": settings.codex_farm_workspace_root,
        "codex_farm_pass1_pattern_hints_enabled": (
            settings.codex_farm_pass1_pattern_hints_enabled
        ),
        "codex_farm_pipeline_pass1": settings.codex_farm_pipeline_pass1,
        "codex_farm_pipeline_pass2": settings.codex_farm_pipeline_pass2,
        "codex_farm_pipeline_pass3": settings.codex_farm_pipeline_pass3,
        "codex_farm_pass3_skip_pass2_ok": settings.codex_farm_pass3_skip_pass2_ok,
        "codex_farm_context_blocks": settings.codex_farm_context_blocks,
        "codex_farm_failure_mode": settings.codex_farm_failure_mode.value,
    }
    if settings.codex_farm_reasoning_effort is not None:
        payload["codex_farm_reasoning_effort"] = (
            settings.codex_farm_reasoning_effort.value
        )
    if processed_output_dir is not None:
        payload["processed_output_dir"] = processed_output_dir
    return payload
