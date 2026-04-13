from __future__ import annotations

from pathlib import Path
from typing import Any

from cookimport.config.run_settings import RunSettings

_STAGE_OPERATOR_FIELDS = (
    "workers",
    "pdf_split_workers",
    "epub_split_workers",
    "epub_extractor",
    "pdf_ocr_policy",
    "pdf_pages_per_job",
    "epub_spine_items_per_job",
    "warm_models",
    "llm_recipe_pipeline",
    "llm_knowledge_pipeline",
    "codex_farm_cmd",
    "codex_farm_root",
    "codex_farm_workspace_root",
    "codex_farm_context_blocks",
    "codex_farm_knowledge_context_blocks",
)
_STAGE_BENCHMARK_LAB_FIELDS = (
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "web_schema_extractor",
    "web_schema_normalizer",
    "web_html_text_extractor",
    "web_schema_policy",
    "web_schema_min_confidence",
    "web_schema_min_ingredients",
    "web_schema_min_instruction_steps",
)
_STAGE_INTERNAL_FIELDS = (
    "recipe_prompt_target_count",
    "recipe_codex_exec_style",
    "knowledge_prompt_target_count",
    "line_role_codex_exec_style",
    "knowledge_codex_exec_style",
    "knowledge_inline_repair_transcript_mode",
    "knowledge_packet_input_char_budget",
    "knowledge_packet_output_char_budget",
    "knowledge_group_task_max_units",
    "knowledge_group_task_max_evidence_chars",
    "workspace_completion_quiescence_seconds",
    "completed_termination_grace_seconds",
    "epub_title_backtrack_limit",
    "epub_anchor_title_backtrack_limit",
    "epub_ingredient_run_window",
    "epub_ingredient_header_window",
    "epub_title_max_length",
    "multi_recipe_splitter",
    "multi_recipe_min_ingredient_lines",
    "multi_recipe_min_instruction_lines",
    "multi_recipe_for_the_guardrail",
    "ingredient_text_fix_backend",
    "ingredient_pre_normalize_mode",
    "ingredient_packaging_mode",
    "ingredient_parser_backend",
    "ingredient_unit_canonicalizer",
    "ingredient_missing_unit_policy",
    "p6_time_backend",
    "p6_time_total_strategy",
    "p6_temperature_backend",
    "p6_temperature_unit_backend",
    "p6_ovenlike_mode",
    "p6_yield_mode",
    "recipe_scorer_backend",
    "recipe_score_gold_min",
    "recipe_score_silver_min",
    "recipe_score_bronze_min",
    "recipe_score_min_ingredient_lines",
    "recipe_score_min_instruction_lines",
    "ocr_device",
    "ocr_batch_size",
    "pdf_column_gap_ratio",
    "codex_farm_failure_mode",
)
_STAGE_FIXED_BEHAVIOR_FIELDS = (
    "section_detector_backend",
    "instruction_step_segmentation_policy",
    "instruction_step_segmenter",
    "multi_recipe_trace",
    "p6_emit_metadata_debug",
    "codex_farm_pipeline_knowledge",
)
_BENCHMARK_OPERATOR_FIELDS = (
    "workers",
    "pdf_split_workers",
    "epub_split_workers",
    "epub_extractor",
    "pdf_ocr_policy",
    "pdf_pages_per_job",
    "epub_spine_items_per_job",
    "warm_models",
    "llm_recipe_pipeline",
    "llm_knowledge_pipeline",
    "codex_farm_cmd",
    "codex_farm_root",
    "codex_farm_workspace_root",
    "codex_farm_context_blocks",
    "codex_farm_knowledge_context_blocks",
)
_BENCHMARK_LAB_FIELDS = (
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "web_schema_extractor",
    "web_schema_normalizer",
    "web_html_text_extractor",
    "web_schema_policy",
    "web_schema_min_confidence",
    "web_schema_min_ingredients",
    "web_schema_min_instruction_steps",
    "atomic_block_splitter",
    "line_role_pipeline",
    "codex_farm_recipe_mode",
    "codex_farm_model",
    "codex_farm_reasoning_effort",
)
_BENCHMARK_INTERNAL_FIELDS = _STAGE_INTERNAL_FIELDS + (
    "line_role_prompt_target_count",
)
_BENCHMARK_FIXED_BEHAVIOR_FIELDS = _STAGE_FIXED_BEHAVIOR_FIELDS + (
    "benchmark_sequence_matcher",
)


def _serialized_setting_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _build_run_settings_slice(
    settings: RunSettings,
    field_names: tuple[str, ...],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field_name in field_names:
        value = _serialized_setting_value(getattr(settings, field_name))
        if value is None:
            continue
        payload[field_name] = value
    return payload


def build_stage_call_kwargs_from_run_settings(
    settings: RunSettings,
    *,
    out: Path,
    mapping: Path | None,
    overrides: Path | None,
    limit: int | None,
    write_markdown: bool,
) -> dict[str, Any]:
    """Map canonical RunSettings to the stage runtime contract."""
    payload: dict[str, Any] = {
        "out": out,
        "mapping": mapping,
        "overrides": overrides,
        "limit": limit,
        "write_markdown": bool(write_markdown),
    }
    for field_group in (
        _STAGE_OPERATOR_FIELDS,
        _STAGE_BENCHMARK_LAB_FIELDS,
        _STAGE_INTERNAL_FIELDS,
        _STAGE_FIXED_BEHAVIOR_FIELDS,
    ):
        payload.update(_build_run_settings_slice(settings, field_group))
    return payload


def build_benchmark_call_kwargs_from_run_settings(
    settings: RunSettings,
    *,
    output_dir: Path,
    eval_output_dir: Path,
    eval_mode: str,
    no_upload: bool,
    write_markdown: bool,
    write_label_studio_tasks: bool,
    processed_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Map canonical RunSettings to the labelstudio-benchmark runtime contract."""
    payload: dict[str, Any] = {
        "output_dir": output_dir,
        "eval_output_dir": eval_output_dir,
        "eval_mode": eval_mode,
        "no_upload": bool(no_upload),
        "write_markdown": bool(write_markdown),
        "write_label_studio_tasks": bool(write_label_studio_tasks),
    }
    for field_group in (
        _BENCHMARK_OPERATOR_FIELDS,
        _BENCHMARK_LAB_FIELDS,
        _BENCHMARK_INTERNAL_FIELDS,
        _BENCHMARK_FIXED_BEHAVIOR_FIELDS,
    ):
        payload.update(_build_run_settings_slice(settings, field_group))
    payload["sequence_matcher"] = payload.pop("benchmark_sequence_matcher")
    if processed_output_dir is not None:
        payload["processed_output_dir"] = processed_output_dir
    return payload
