from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from cookimport.staging.job_planning import (
    compute_effective_workers_for_sources as compute_effective_workers,
)

from .run_settings import (
    AtomicBlockSplitter,
    CodexFarmFailureMode,
    CodexFarmRecipeMode,
    CodexReasoningEffort,
    EpubExtractor,
    IngredientMissingUnitPolicy,
    IngredientPackagingMode,
    IngredientParserBackend,
    IngredientPreNormalizeMode,
    IngredientTextFixBackend,
    IngredientUnitCanonicalizer,
    LineRolePipeline,
    LlmKnowledgePipeline,
    LlmRecipePipeline,
    MultiRecipeSplitter,
    OcrDevice,
    P6OvenlikeMode,
    P6TemperatureBackend,
    P6TemperatureUnitBackend,
    P6TimeBackend,
    P6TimeTotalStrategy,
    P6YieldMode,
    PdfOcrPolicy,
    RunSettings,
    UnstructuredHtmlParserVersion,
    UnstructuredPreprocessMode,
    WebHtmlTextExtractor,
    WebSchemaExtractor,
    WebSchemaNormalizer,
    WebSchemaPolicy,
)

def _normalized_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value).strip().lower()
    return str(value).strip().lower()


def build_run_settings(
    *,
    workers: int,
    pdf_split_workers: int,
    epub_split_workers: int,
    pdf_pages_per_job: int,
    epub_spine_items_per_job: int,
    epub_extractor: str | EpubExtractor,
    epub_unstructured_html_parser_version: (
        str | UnstructuredHtmlParserVersion
    ) = UnstructuredHtmlParserVersion.v1,
    epub_unstructured_skip_headers_footers: bool = True,
    epub_unstructured_preprocess_mode: (
        str | UnstructuredPreprocessMode
    ) = UnstructuredPreprocessMode.br_split_v1,
    epub_title_backtrack_limit: int = 20,
    epub_anchor_title_backtrack_limit: int = 8,
    epub_ingredient_run_window: int = 8,
    epub_ingredient_header_window: int = 12,
    epub_title_max_length: int = 80,
    ocr_device: str | OcrDevice,
    pdf_ocr_policy: str | PdfOcrPolicy = PdfOcrPolicy.auto,
    ocr_batch_size: int,
    pdf_column_gap_ratio: float = 0.12,
    warm_models: bool,
    multi_recipe_splitter: str | MultiRecipeSplitter = MultiRecipeSplitter.rules_v1,
    multi_recipe_min_ingredient_lines: int = 1,
    multi_recipe_min_instruction_lines: int = 1,
    multi_recipe_for_the_guardrail: bool = True,
    web_schema_extractor: str | WebSchemaExtractor = WebSchemaExtractor.builtin_jsonld,
    web_schema_normalizer: str | WebSchemaNormalizer = WebSchemaNormalizer.simple,
    web_html_text_extractor: str | WebHtmlTextExtractor = WebHtmlTextExtractor.bs4,
    web_schema_policy: str | WebSchemaPolicy = WebSchemaPolicy.prefer_schema,
    web_schema_min_confidence: float = 0.75,
    web_schema_min_ingredients: int = 2,
    web_schema_min_instruction_steps: int = 1,
    ingredient_text_fix_backend: (
        str | IngredientTextFixBackend
    ) = IngredientTextFixBackend.none,
    ingredient_pre_normalize_mode: (
        str | IngredientPreNormalizeMode
    ) = IngredientPreNormalizeMode.aggressive_v1,
    ingredient_packaging_mode: (
        str | IngredientPackagingMode
    ) = IngredientPackagingMode.off,
    ingredient_parser_backend: (
        str | IngredientParserBackend
    ) = IngredientParserBackend.ingredient_parser_nlp,
    ingredient_unit_canonicalizer: (
        str | IngredientUnitCanonicalizer
    ) = IngredientUnitCanonicalizer.pint,
    ingredient_missing_unit_policy: (
        str | IngredientMissingUnitPolicy
    ) = IngredientMissingUnitPolicy.null,
    p6_time_backend: str | P6TimeBackend = P6TimeBackend.regex_v1,
    p6_time_total_strategy: (
        str | P6TimeTotalStrategy
    ) = P6TimeTotalStrategy.sum_all_v1,
    p6_temperature_backend: (
        str | P6TemperatureBackend
    ) = P6TemperatureBackend.regex_v1,
    p6_temperature_unit_backend: (
        str | P6TemperatureUnitBackend
    ) = P6TemperatureUnitBackend.builtin_v1,
    p6_ovenlike_mode: str | P6OvenlikeMode = P6OvenlikeMode.keywords_v1,
    p6_yield_mode: str | P6YieldMode = P6YieldMode.scored_v1,
    recipe_scorer_backend: str = "heuristic_v1",
    recipe_score_gold_min: float = 0.75,
    recipe_score_silver_min: float = 0.55,
    recipe_score_bronze_min: float = 0.35,
    recipe_score_min_ingredient_lines: int = 1,
    recipe_score_min_instruction_lines: int = 1,
    llm_recipe_pipeline: str | LlmRecipePipeline = LlmRecipePipeline.off,
    recipe_prompt_target_count: int | None = 5,
    recipe_codex_exec_style: str = "inline-json-v1",
    atomic_block_splitter: str | AtomicBlockSplitter = AtomicBlockSplitter.off,
    line_role_pipeline: str | LineRolePipeline = LineRolePipeline.off,
    line_role_codex_exec_style: str = "inline-json-v1",
    line_role_prompt_target_count: int | None = 5,
    llm_knowledge_pipeline: str | LlmKnowledgePipeline = LlmKnowledgePipeline.off,
    knowledge_codex_exec_style: str = "inline-json-v1",
    knowledge_prompt_target_count: int | None = 5,
    knowledge_packet_input_char_budget: int | None = 18000,
    knowledge_packet_output_char_budget: int | None = 6000,
    knowledge_grouping_enabled: bool = False,
    knowledge_group_task_max_units: int = 40,
    knowledge_group_task_max_evidence_chars: int = 12000,
    codex_farm_recipe_mode: str | CodexFarmRecipeMode = CodexFarmRecipeMode.extract,
    codex_farm_cmd: str = "codex-farm",
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | CodexReasoningEffort | None = None,
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_context_blocks: int = 30,
    codex_farm_knowledge_context_blocks: int = 0,
    codex_farm_failure_mode: str | CodexFarmFailureMode = CodexFarmFailureMode.fail,
    workspace_completion_quiescence_seconds: float = 15.0,
    completed_termination_grace_seconds: float = 15.0,
    mapping_path: Path | None = None,
    overrides_path: Path | None = None,
    file_paths: Sequence[Path] | None = None,
    all_epub: bool | None = None,
    effective_workers: int | None = None,
) -> RunSettings:
    resolved_effective_workers = effective_workers
    if resolved_effective_workers is None:
        resolved_effective_workers = compute_effective_workers(
            workers=workers,
            epub_split_workers=epub_split_workers,
            epub_extractor=epub_extractor,
            file_paths=file_paths,
            all_epub=all_epub,
        )
    resolved_line_role_codex_exec_style = _normalized_value(
        line_role_codex_exec_style
    )
    resolved_recipe_codex_exec_style = _normalized_value(recipe_codex_exec_style)
    resolved_knowledge_codex_exec_style = _normalized_value(
        knowledge_codex_exec_style
    )
    return RunSettings.model_validate(
        {
            "workers": workers,
            "pdf_split_workers": pdf_split_workers,
            "epub_split_workers": epub_split_workers,
            "pdf_pages_per_job": pdf_pages_per_job,
            "epub_spine_items_per_job": epub_spine_items_per_job,
            "epub_extractor": _normalized_value(epub_extractor),
            "epub_unstructured_html_parser_version": _normalized_value(
                epub_unstructured_html_parser_version
            ),
            "epub_unstructured_skip_headers_footers": bool(
                epub_unstructured_skip_headers_footers
            ),
            "epub_unstructured_preprocess_mode": _normalized_value(
                epub_unstructured_preprocess_mode
            ),
            "epub_title_backtrack_limit": int(epub_title_backtrack_limit),
            "epub_anchor_title_backtrack_limit": int(epub_anchor_title_backtrack_limit),
            "epub_ingredient_run_window": int(epub_ingredient_run_window),
            "epub_ingredient_header_window": int(epub_ingredient_header_window),
            "epub_title_max_length": int(epub_title_max_length),
            "ocr_device": _normalized_value(ocr_device),
            "pdf_ocr_policy": _normalized_value(pdf_ocr_policy),
            "ocr_batch_size": ocr_batch_size,
            "pdf_column_gap_ratio": float(pdf_column_gap_ratio),
            "warm_models": bool(warm_models),
            "multi_recipe_splitter": _normalized_value(multi_recipe_splitter),
            "multi_recipe_min_ingredient_lines": int(multi_recipe_min_ingredient_lines),
            "multi_recipe_min_instruction_lines": int(multi_recipe_min_instruction_lines),
            "multi_recipe_for_the_guardrail": bool(multi_recipe_for_the_guardrail),
            "web_schema_extractor": _normalized_value(web_schema_extractor),
            "web_schema_normalizer": _normalized_value(web_schema_normalizer),
            "web_html_text_extractor": _normalized_value(web_html_text_extractor),
            "web_schema_policy": _normalized_value(web_schema_policy),
            "web_schema_min_confidence": float(web_schema_min_confidence),
            "web_schema_min_ingredients": int(web_schema_min_ingredients),
            "web_schema_min_instruction_steps": int(web_schema_min_instruction_steps),
            "ingredient_text_fix_backend": _normalized_value(
                ingredient_text_fix_backend
            ),
            "ingredient_pre_normalize_mode": _normalized_value(
                ingredient_pre_normalize_mode
            ),
            "ingredient_packaging_mode": _normalized_value(
                ingredient_packaging_mode
            ),
            "ingredient_parser_backend": _normalized_value(
                ingredient_parser_backend
            ),
            "ingredient_unit_canonicalizer": _normalized_value(
                ingredient_unit_canonicalizer
            ),
            "ingredient_missing_unit_policy": _normalized_value(
                ingredient_missing_unit_policy
            ),
            "p6_time_backend": _normalized_value(p6_time_backend),
            "p6_time_total_strategy": _normalized_value(p6_time_total_strategy),
            "p6_temperature_backend": _normalized_value(p6_temperature_backend),
            "p6_temperature_unit_backend": _normalized_value(
                p6_temperature_unit_backend
            ),
            "p6_ovenlike_mode": _normalized_value(p6_ovenlike_mode),
            "p6_yield_mode": _normalized_value(p6_yield_mode),
            "recipe_scorer_backend": str(recipe_scorer_backend or "heuristic_v1").strip()
            or "heuristic_v1",
            "recipe_score_gold_min": float(recipe_score_gold_min),
            "recipe_score_silver_min": float(recipe_score_silver_min),
            "recipe_score_bronze_min": float(recipe_score_bronze_min),
            "recipe_score_min_ingredient_lines": int(recipe_score_min_ingredient_lines),
            "recipe_score_min_instruction_lines": int(recipe_score_min_instruction_lines),
            "llm_recipe_pipeline": _normalized_value(llm_recipe_pipeline),
            "recipe_prompt_target_count": (
                int(recipe_prompt_target_count)
                if recipe_prompt_target_count is not None
                else None
            ),
            "recipe_codex_exec_style": resolved_recipe_codex_exec_style,
            "atomic_block_splitter": _normalized_value(atomic_block_splitter),
            "line_role_pipeline": _normalized_value(line_role_pipeline),
            "line_role_codex_exec_style": resolved_line_role_codex_exec_style,
            "line_role_prompt_target_count": (
                int(line_role_prompt_target_count)
                if line_role_prompt_target_count is not None
                else None
            ),
            "llm_knowledge_pipeline": _normalized_value(llm_knowledge_pipeline),
            "knowledge_codex_exec_style": resolved_knowledge_codex_exec_style,
            "knowledge_prompt_target_count": (
                int(knowledge_prompt_target_count)
                if knowledge_prompt_target_count is not None
                else None
            ),
            "knowledge_packet_input_char_budget": (
                int(knowledge_packet_input_char_budget)
                if knowledge_packet_input_char_budget is not None
                else None
            ),
            "knowledge_packet_output_char_budget": (
                int(knowledge_packet_output_char_budget)
                if knowledge_packet_output_char_budget is not None
                else None
            ),
            "knowledge_grouping_enabled": bool(knowledge_grouping_enabled),
            "knowledge_group_task_max_units": int(knowledge_group_task_max_units),
            "knowledge_group_task_max_evidence_chars": int(
                knowledge_group_task_max_evidence_chars
            ),
            "codex_farm_recipe_mode": _normalized_value(codex_farm_recipe_mode),
            "codex_farm_cmd": str(codex_farm_cmd).strip() or "codex-farm",
            "codex_farm_model": (
                str(codex_farm_model).strip()
                if codex_farm_model is not None and str(codex_farm_model).strip()
                else None
            ),
            "codex_farm_reasoning_effort": (
                _normalized_value(codex_farm_reasoning_effort)
                if codex_farm_reasoning_effort is not None
                and str(codex_farm_reasoning_effort).strip()
                else None
            ),
            "codex_farm_root": (
                str(codex_farm_root) if codex_farm_root is not None else None
            ),
            "codex_farm_workspace_root": (
                str(codex_farm_workspace_root)
                if codex_farm_workspace_root is not None
                else None
            ),
            "codex_farm_context_blocks": int(codex_farm_context_blocks),
            "codex_farm_knowledge_context_blocks": int(codex_farm_knowledge_context_blocks),
            "codex_farm_failure_mode": _normalized_value(codex_farm_failure_mode),
            "workspace_completion_quiescence_seconds": float(
                workspace_completion_quiescence_seconds
            ),
            "completed_termination_grace_seconds": float(
                completed_termination_grace_seconds
            ),
            "effective_workers": resolved_effective_workers,
            "mapping_path": str(mapping_path) if mapping_path is not None else None,
            "overrides_path": str(overrides_path) if overrides_path is not None else None,
        }
    )
