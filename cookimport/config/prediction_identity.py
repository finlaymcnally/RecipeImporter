from __future__ import annotations

from typing import Any

from cookimport.config.codex_decision import BUCKET1_FIXED_BEHAVIOR_VERSION
from cookimport.config.run_settings import RunSettings

ALL_METHOD_PREDICTION_IDENTITY_FIELDS = (
    "bucket1_fixed_behavior_version",
    "epub_extractor",
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "multi_recipe_splitter",
    "multi_recipe_min_ingredient_lines",
    "multi_recipe_min_instruction_lines",
    "multi_recipe_for_the_guardrail",
    "atomic_block_splitter",
    "line_role_pipeline",
    "line_role_codex_exec_style",
    "web_schema_extractor",
    "web_schema_normalizer",
    "web_html_text_extractor",
    "web_schema_policy",
    "web_schema_min_confidence",
    "web_schema_min_ingredients",
    "web_schema_min_instruction_steps",
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
    "pdf_ocr_policy",
    "ocr_batch_size",
    "pdf_column_gap_ratio",
    "llm_recipe_pipeline",
    "recipe_codex_exec_style",
    "codex_farm_recipe_mode",
    "codex_farm_model",
    "codex_farm_reasoning_effort",
    "codex_farm_context_blocks",
    "codex_farm_failure_mode",
    "llm_knowledge_pipeline",
    "knowledge_codex_exec_style",
    "codex_farm_knowledge_context_blocks",
)

LINE_ROLE_CACHE_IDENTITY_FIELDS = (
    "line_role_pipeline",
    "line_role_codex_exec_style",
)


def _project_run_config_fields(
    settings: RunSettings,
    *,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    run_config = settings.to_run_config_dict()
    run_config["bucket1_fixed_behavior_version"] = BUCKET1_FIXED_BEHAVIOR_VERSION
    return {
        field_name: run_config[field_name]
        for field_name in fields
        if field_name in run_config
    }


def build_all_method_prediction_identity_payload(
    settings: RunSettings,
) -> dict[str, Any]:
    return _project_run_config_fields(
        settings,
        fields=ALL_METHOD_PREDICTION_IDENTITY_FIELDS,
    )


def build_line_role_cache_identity_payload(settings: RunSettings) -> dict[str, Any]:
    return _project_run_config_fields(
        settings,
        fields=LINE_ROLE_CACHE_IDENTITY_FIELDS,
    )
