from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cookimport.bench.sequence_matcher_select import supported_sequence_matcher_modes
from cookimport.epub_extractor_names import (
    EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV,
    EPUB_EXTRACTOR_CANONICAL_SET,
    epub_extractor_enabled_choices,
    is_policy_locked_epub_extractor_name,
    normalize_epub_extractor_name,
)
from cookimport.config.run_settings_contracts import (
    RUN_SETTING_CONTRACT_BENCHMARK_LAB,
    RUN_SETTING_CONTRACT_OPERATOR,
    RUN_SETTING_CONTRACT_PRODUCT,
    RUN_SETTING_SURFACE_INTERNAL,
    RUN_SETTING_SURFACE_PUBLIC,
    configure_run_setting_contracts,
    project_run_config_payload,
    run_setting_surface,
    summarize_run_config_payload,
)
from cookimport.staging.job_planning import (
    compute_effective_workers_for_sources as compute_effective_workers,
)

logger = logging.getLogger(__name__)
from .run_settings_types import (
    AtomicBlockSplitter,
    BUCKET2_INTERNAL_ONLY_RUN_SETTING_NAMES,
    CodexExecStyle,
    CodexFarmFailureMode,
    CodexFarmRecipeMode,
    CodexReasoningEffort,
    CODEX_EXEC_STYLE_INLINE_JSON_V1,
    CODEX_EXEC_STYLE_TASKFILE_V1,
    EpubExtractor,
    IngredientMissingUnitPolicy,
    IngredientPackagingMode,
    IngredientParserBackend,
    IngredientPreNormalizeMode,
    IngredientTextFixBackend,
    IngredientUnitCanonicalizer,
    InstructionStepSegmentationPolicy,
    InstructionStepSegmenter,
    KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
    LINE_ROLE_PIPELINE_ROUTE_V2,
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
    RECIPE_CODEX_FARM_ALLOWED_PIPELINES,
    RECIPE_CODEX_FARM_EXECUTION_PIPELINES,
    RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR,
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
    SectionDetectorBackend,
    UnstructuredHtmlParserVersion,
    UnstructuredPreprocessMode,
    WebHtmlTextExtractor,
    WebSchemaExtractor,
    WebSchemaNormalizer,
    WebSchemaPolicy,
    _bucket1_fixed_behavior,
    _ui_meta,
    normalize_line_role_pipeline_value,
    normalize_codex_exec_style_value,
    normalize_llm_knowledge_pipeline_value,
    normalize_llm_recipe_pipeline_value,
)


def resolve_codex_exec_style_value(value: Any) -> str:
    return normalize_codex_exec_style_value(value)


class RunSettings(BaseModel):
    """Canonical per-run pipeline settings used by UI + reports + analytics."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    workers: int = Field(
        default=7,
        ge=1,
        le=128,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="Workers",
            order=10,
            description="Max parallel worker processes for this run.",
            step=1,
            minimum=1,
            maximum=128,
        ),
    )
    pdf_split_workers: int = Field(
        default=7,
        ge=1,
        le=128,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="PDF Split Workers",
            order=20,
            description="Max workers used while splitting one PDF run.",
            step=1,
            minimum=1,
            maximum=128,
        ),
    )
    epub_split_workers: int = Field(
        default=7,
        ge=1,
        le=128,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="EPUB Split Workers",
            order=30,
            description="Max workers used while splitting one EPUB run.",
            step=1,
            minimum=1,
            maximum=128,
        ),
    )
    pdf_pages_per_job: int = Field(
        default=50,
        ge=1,
        le=2000,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="PDF Pages / Job",
            order=40,
            description="Target page count per split PDF worker job.",
            step=5,
            minimum=1,
            maximum=2000,
        ),
    )
    epub_spine_items_per_job: int = Field(
        default=10,
        ge=1,
        le=2000,
        json_schema_extra=_ui_meta(
            group="Workers",
            label="EPUB Spine Items / Job",
            order=50,
            description="Target spine-item count per split EPUB worker job.",
            step=1,
            minimum=1,
            maximum=2000,
        ),
    )
    epub_extractor: EpubExtractor = Field(
        default=EpubExtractor.unstructured,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="EPUB Extractor",
            order=60,
            description=(
                "EPUB extraction engine (default choices: unstructured, beautifulsoup). "
                "Markdown extractors are policy-locked off unless "
                f"{EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1."
            ),
        ),
    )
    epub_unstructured_html_parser_version: UnstructuredHtmlParserVersion = Field(
        default=UnstructuredHtmlParserVersion.v1,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Unstructured HTML Parser",
            order=62,
            description="Unstructured HTML parser version used for EPUB extraction.",
        ),
    )
    epub_unstructured_skip_headers_footers: bool = Field(
        default=True,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Unstructured Skip Headers/Footers",
            order=63,
            description="Enable Unstructured header/footer skipping for EPUB HTML partitioning.",
        ),
    )
    epub_unstructured_preprocess_mode: UnstructuredPreprocessMode = Field(
        default=UnstructuredPreprocessMode.br_split_v1,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Unstructured EPUB Preprocess",
            order=64,
            description="EPUB HTML preprocessing mode before Unstructured partitioning.",
        ),
    )
    epub_title_backtrack_limit: int = Field(
        default=20,
        ge=1,
        le=200,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="EPUB Title Backtrack Limit",
            order=65,
            description="Maximum blocks to scan backward when recovering a likely EPUB recipe title.",
            step=1,
            minimum=1,
            maximum=200,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    epub_anchor_title_backtrack_limit: int = Field(
        default=8,
        ge=1,
        le=200,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="EPUB Anchor Title Backtrack Limit",
            order=65,
            description="Backtrack limit used when a yield or ingredient anchor triggers EPUB title recovery.",
            step=1,
            minimum=1,
            maximum=200,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    epub_ingredient_run_window: int = Field(
        default=8,
        ge=1,
        le=200,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="EPUB Ingredient Run Window",
            order=65,
            description="Forward scan window used by EPUB title/anchor heuristics when checking for nearby ingredient runs.",
            step=1,
            minimum=1,
            maximum=200,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    epub_ingredient_header_window: int = Field(
        default=12,
        ge=1,
        le=200,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="EPUB Ingredient Header Window",
            order=65,
            description="Forward scan window used by EPUB title heuristics when looking for a later ingredient header.",
            step=1,
            minimum=1,
            maximum=200,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    epub_title_max_length: int = Field(
        default=80,
        ge=1,
        le=400,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="EPUB Title Max Length",
            order=65,
            description="Maximum characters for a block to qualify as an EPUB title candidate or short fallback heading.",
            step=1,
            minimum=1,
            maximum=400,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    multi_recipe_splitter: MultiRecipeSplitter = Field(
        default=MultiRecipeSplitter.rules_v1,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Multi-recipe Splitter",
            order=67,
            description=(
                "Candidate splitter backend for merged multi-recipe spans "
                "(off or shared deterministic rules_v1)."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    multi_recipe_min_ingredient_lines: int = Field(
        default=1,
        ge=0,
        le=100,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Multi-recipe Min Ingredients",
            order=69,
            description="Minimum ingredient-like lines required on each side of a split boundary.",
            step=1,
            minimum=0,
            maximum=100,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    multi_recipe_min_instruction_lines: int = Field(
        default=1,
        ge=0,
        le=100,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Multi-recipe Min Instructions",
            order=70,
            description="Minimum instruction-like lines required on each side of a split boundary.",
            step=1,
            minimum=0,
            maximum=100,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    multi_recipe_for_the_guardrail: bool = Field(
        default=True,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Multi-recipe For-the Guardrail",
            order=71,
            description=(
                "Prevent boundaries on component subsection headers "
                "(for example 'For the sauce')."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    web_schema_extractor: WebSchemaExtractor = Field(
        default=WebSchemaExtractor.builtin_jsonld,
        json_schema_extra=_ui_meta(
            group="WebSchema",
            label="Web Schema Extractor",
            order=66,
            description=(
                "Schema extraction backend for local HTML/JSON schema inputs "
                "(builtin_jsonld, extruct, scrape_schema_recipe, recipe_scrapers, ensemble_v1)."
            ),
        ),
    )
    web_schema_normalizer: WebSchemaNormalizer = Field(
        default=WebSchemaNormalizer.simple,
        json_schema_extra=_ui_meta(
            group="WebSchema",
            label="Web Schema Normalizer",
            order=67,
            description="Schema normalization mode before mapping (simple or pyld).",
        ),
    )
    web_html_text_extractor: WebHtmlTextExtractor = Field(
        default=WebHtmlTextExtractor.bs4,
        json_schema_extra=_ui_meta(
            group="WebSchema",
            label="Web HTML Text Extractor",
            order=68,
            description=(
                "Fallback HTML text extractor for schema-poor pages "
                "(bs4, trafilatura, readability_lxml, justext, boilerpy3, ensemble_v1)."
            ),
        ),
    )
    web_schema_policy: WebSchemaPolicy = Field(
        default=WebSchemaPolicy.prefer_schema,
        json_schema_extra=_ui_meta(
            group="WebSchema",
            label="Web Schema Policy",
            order=69,
            description=(
                "Schema lane policy: prefer_schema, schema_only, or heuristic_only."
            ),
        ),
    )
    web_schema_min_confidence: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        json_schema_extra=_ui_meta(
            group="WebSchema",
            label="Web Schema Min Confidence",
            order=70,
            description="Minimum schema confidence required before schema candidate acceptance.",
        ),
    )
    web_schema_min_ingredients: int = Field(
        default=2,
        ge=0,
        le=100,
        json_schema_extra=_ui_meta(
            group="WebSchema",
            label="Web Schema Min Ingredients",
            order=71,
            description="Minimum ingredient lines used by schema confidence gating.",
            step=1,
            minimum=0,
            maximum=100,
        ),
    )
    web_schema_min_instruction_steps: int = Field(
        default=1,
        ge=0,
        le=100,
        json_schema_extra=_ui_meta(
            group="WebSchema",
            label="Web Schema Min Steps",
            order=72,
            description="Minimum instruction steps used by schema confidence gating.",
            step=1,
            minimum=0,
            maximum=100,
        ),
    )
    ingredient_text_fix_backend: IngredientTextFixBackend = Field(
        default=IngredientTextFixBackend.none,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Ingredient Text Fix Backend",
            order=67,
            description=(
                "Optional text cleanup backend before ingredient parsing "
                "(none or ftfy)."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    ingredient_pre_normalize_mode: IngredientPreNormalizeMode = Field(
        default=IngredientPreNormalizeMode.aggressive_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Ingredient Pre-normalize Mode",
            order=68,
            description=(
                "Ingredient pre-parse normalization mode (aggressive_v1)."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    ingredient_packaging_mode: IngredientPackagingMode = Field(
        default=IngredientPackagingMode.off,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Ingredient Packaging Mode",
            order=69,
            description=(
                "Packaging extraction mode for patterns like "
                "'1 (14-ounce) can tomatoes'."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    ingredient_parser_backend: IngredientParserBackend = Field(
        default=IngredientParserBackend.ingredient_parser_nlp,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Ingredient Parser Backend",
            order=70,
            description=(
                "Ingredient parser backend: ingredient_parser_nlp, "
                "quantulum3_regex, or hybrid_nlp_then_quantulum3."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    ingredient_unit_canonicalizer: IngredientUnitCanonicalizer = Field(
        default=IngredientUnitCanonicalizer.pint,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Ingredient Unit Canonicalizer",
            order=71,
            description=(
                "Unit canonicalization mode (pint) applied after parsing."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    ingredient_missing_unit_policy: IngredientMissingUnitPolicy = Field(
        default=IngredientMissingUnitPolicy.null,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Ingredient Missing Unit Policy",
            order=72,
            description=(
                "Policy when quantity exists but unit is missing: "
                "medium, null, or each."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    p6_time_backend: P6TimeBackend = Field(
        default=P6TimeBackend.regex_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Time Backend",
            order=73,
            description=(
                "Priority 6 instruction-time extractor backend "
                "(regex_v1, quantulum3_v1, hybrid_regex_quantulum3_v1)."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    p6_time_total_strategy: P6TimeTotalStrategy = Field(
        default=P6TimeTotalStrategy.sum_all_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Time Strategy",
            order=74,
            description=(
                "Priority 6 step time rollup strategy "
                "(sum_all_v1, max_v1, selective_sum_v1)."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    p6_temperature_backend: P6TemperatureBackend = Field(
        default=P6TemperatureBackend.regex_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Temperature Backend",
            order=75,
            description=(
                "Priority 6 temperature extractor backend "
                "(regex_v1, quantulum3_v1, hybrid_regex_quantulum3_v1)."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    p6_temperature_unit_backend: P6TemperatureUnitBackend = Field(
        default=P6TemperatureUnitBackend.builtin_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Temperature Unit Backend",
            order=76,
            description="Priority 6 temperature unit conversion backend (builtin_v1 or pint_v1).",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    p6_ovenlike_mode: P6OvenlikeMode = Field(
        default=P6OvenlikeMode.keywords_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Ovenlike Mode",
            order=77,
            description="Priority 6 oven-like temperature classifier mode (keywords_v1 or off).",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    p6_yield_mode: P6YieldMode = Field(
        default=P6YieldMode.scored_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Yield Mode",
            order=78,
            description="Priority 6 yield parser mode (scored_v1).",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    recipe_scorer_backend: str = Field(
        default="heuristic_v1",
        json_schema_extra=_ui_meta(
            group="Scoring",
            label="Recipe Scorer Backend",
            order=74,
            description="Recipe-likeness scorer backend. Default and supported backend is heuristic_v1.",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    recipe_score_gold_min: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        json_schema_extra=_ui_meta(
            group="Scoring",
            label="Recipe Score Gold Min",
            order=75,
            description="Minimum recipe-likeness score for gold tier.",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    recipe_score_silver_min: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        json_schema_extra=_ui_meta(
            group="Scoring",
            label="Recipe Score Silver Min",
            order=76,
            description="Minimum recipe-likeness score for silver tier.",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    recipe_score_bronze_min: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        json_schema_extra=_ui_meta(
            group="Scoring",
            label="Recipe Score Bronze Min",
            order=77,
            description="Minimum recipe-likeness score for bronze tier (below is reject).",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    recipe_score_min_ingredient_lines: int = Field(
        default=1,
        ge=0,
        le=100,
        json_schema_extra=_ui_meta(
            group="Scoring",
            label="Min Ingredient Lines",
            order=78,
            description="Soft minimum ingredient lines used by scorer/gate behavior.",
            step=1,
            minimum=0,
            maximum=100,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    recipe_score_min_instruction_lines: int = Field(
        default=1,
        ge=0,
        le=100,
        json_schema_extra=_ui_meta(
            group="Scoring",
            label="Min Instruction Lines",
            order=79,
            description="Soft minimum instruction lines used by scorer/gate behavior.",
            step=1,
            minimum=0,
            maximum=100,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    ocr_device: OcrDevice = Field(
        default=OcrDevice.auto,
        json_schema_extra=_ui_meta(
            group="OCR",
            label="OCR Device",
            order=80,
            description="OCR device selection for PDF processing.",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    pdf_ocr_policy: PdfOcrPolicy = Field(
        default=PdfOcrPolicy.auto,
        json_schema_extra=_ui_meta(
            group="OCR",
            label="PDF OCR Policy",
            order=85,
            description=(
                "PDF OCR policy: auto (detect scanned pages), "
                "off (never OCR), always (force OCR when available)."
            ),
        ),
    )
    ocr_batch_size: int = Field(
        default=1,
        ge=1,
        le=256,
        json_schema_extra=_ui_meta(
            group="OCR",
            label="OCR Batch Size",
            order=90,
            description="Number of pages per OCR model batch.",
            step=1,
            minimum=1,
            maximum=256,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    pdf_column_gap_ratio: float = Field(
        default=0.12,
        ge=0.01,
        le=0.95,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="PDF Column Gap Ratio",
            order=72,
            description=(
                "Minimum horizontal gap ratio used for PDF column-boundary detection. "
                "Higher values reduce multi-column splits."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    warm_models: bool = Field(
        default=False,
        json_schema_extra=_ui_meta(
            group="Advanced",
            label="Warm Models",
            order=100,
            description="Preload heavy OCR/parsing models before processing.",
        ),
    )
    llm_recipe_pipeline: LlmRecipePipeline = Field(
        default=LlmRecipePipeline.off,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Recipe LLM Pipeline",
            order=110,
            description=(
                "Recipe codex-farm parsing correction. Off keeps deterministic behavior."
            ),
        ),
    )
    recipe_prompt_target_count: int | None = Field(
        default=5,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Recipe Shard Count",
            order=110,
            description=(
                "Preferred recipe worker-session count when explicit recipe worker count is unset."
            ),
            step=1,
            minimum=1,
            maximum=256,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    recipe_worker_count: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Recipe Worker Count",
            order=110,
            description="Optional bounded worker-count override for shard-v1 recipe runtime.",
            step=1,
            minimum=1,
            maximum=256,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    recipe_shard_max_turns: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Recipe Shard Max Turns",
            order=110,
            description="Optional max-turn cap per recipe shard for shard-v1 runtime.",
            step=1,
            minimum=1,
            maximum=128,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    atomic_block_splitter: AtomicBlockSplitter = Field(
        default=AtomicBlockSplitter.off,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Atomic Block Splitter",
            order=111,
            description=(
                "Optional block atomization mode used by benchmark-native line-role "
                "experiments."
            ),
        ),
    )
    line_role_pipeline: LineRolePipeline = Field(
        default=LineRolePipeline.off,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Line Role Pipeline",
            order=112,
            description=(
                "Canonical line-role labeling path used for benchmark-native "
                "experiments. Off keeps the fully vanilla label-first output."
            ),
        ),
    )
    line_role_codex_exec_style: CodexExecStyle = Field(
        default=CodexExecStyle.inline_json_v1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Line Role Codex Exec Style",
            order=113,
            description=(
                "Transport style for Codex-backed block labelling. "
                "Inline JSON is the default thin path; taskfile keeps the editable "
                "task.json contract for comparison or debugging."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    line_role_prompt_target_count: int | None = Field(
        default=5,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Line Role Shard Count",
            order=112,
            description=(
                "Direct shard-count override for shard-v1 line-role runtime. "
                "When set, the planner partitions the ordered line list into this many shards."
            ),
            step=1,
            minimum=1,
            maximum=256,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    line_role_worker_count: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Line Role Worker Count",
            order=112,
            description="Optional bounded worker-count override for shard-v1 line-role runtime.",
            step=1,
            minimum=1,
            maximum=256,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    line_role_shard_target_lines: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Line Role Shard Target",
            order=112,
            description="Optional target lines per shard for shard-v1 line-role runtime.",
            step=1,
            minimum=1,
            maximum=20000,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    line_role_shard_max_turns: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Line Role Shard Max Turns",
            order=112,
            description="Optional max-turn cap per line-role shard for shard-v1 runtime.",
            step=1,
            minimum=1,
            maximum=128,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    llm_knowledge_pipeline: LlmKnowledgePipeline = Field(
        default=LlmKnowledgePipeline.off,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge LLM Pipeline",
            order=115,
            description=(
                "Optional non-recipe finalize pipeline. "
                "Off keeps the fully vanilla nonrecipe authority."
            ),
        ),
    )
    knowledge_codex_exec_style: CodexExecStyle = Field(
        default=CodexExecStyle.inline_json_v1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Codex Exec Style",
            order=116,
            description=(
                "Transport style for Codex-backed non-recipe finalize. "
                "Inline JSON is the default thin path; taskfile keeps the editable "
                "task.json contract for comparison or debugging."
            ),
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    knowledge_prompt_target_count: int | None = Field(
        default=5,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Shard Count",
            order=115,
            description=(
                "Direct shard-count override for shard-v1 knowledge runtime. "
                "When set, the planner partitions the ordered knowledge chunks into this many shards."
            ),
            step=1,
            minimum=1,
            maximum=256,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    knowledge_packet_input_char_budget: int | None = Field(
        default=18000,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Packet Input Budget",
            order=115,
            description=(
                "Approximate max characters for one leased knowledge packet input. "
                "The planner splits before runtime when a shard would exceed this budget."
            ),
            step=500,
            minimum=1,
            maximum=200000,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    knowledge_packet_output_char_budget: int | None = Field(
        default=6000,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Packet Output Budget",
            order=115,
            description=(
                "Approximate max characters for one leased knowledge packet result. "
                "The planner splits before runtime when the worst-case packet output would exceed this budget."
            ),
            step=250,
            minimum=1,
            maximum=100000,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    knowledge_group_task_max_units: int = Field(
        default=40,
        ge=1,
        le=500,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Group Task Max Units",
            order=115,
            description="Maximum accepted knowledge rows grouped in one same-session grouping batch.",
            step=1,
            minimum=1,
            maximum=500,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    knowledge_group_task_max_evidence_chars: int = Field(
        default=12000,
        ge=1,
        le=500000,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Group Task Max Evidence",
            order=115,
            description="Approximate evidence-character cap for one knowledge grouping batch.",
            step=250,
            minimum=1,
            maximum=500000,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    knowledge_worker_count: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Worker Count",
            order=115,
            description="Optional bounded worker-count override for shard-v1 knowledge runtime.",
            step=1,
            minimum=1,
            maximum=256,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    knowledge_shard_max_turns: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Shard Max Turns",
            order=115,
            description="Optional max-turn cap per knowledge shard for shard-v1 runtime.",
            step=1,
            minimum=1,
            maximum=128,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    codex_farm_recipe_mode: CodexFarmRecipeMode = Field(
        default=CodexFarmRecipeMode.extract,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Recipe Mode",
            order=116,
            description=(
                "Codex-farm recipe execution style. extract keeps the existing "
                "three-pass extraction behavior; benchmark requests benchmark-native "
                "line-label behavior."
            ),
        ),
    )
    codex_farm_cmd: str = Field(
        default="codex-farm",
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Command",
            order=120,
            description="Executable used when running codex-farm subprocesses.",
        ),
    )
    codex_farm_model: str | None = Field(
        default=None,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Model",
            order=122,
            description="Optional codex-farm model override. Blank uses pipeline defaults.",
        ),
    )
    codex_farm_reasoning_effort: CodexReasoningEffort | None = Field(
        default=None,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Reasoning Effort",
            order=123,
            description=(
                "Optional codex-farm reasoning effort override "
                "(none, minimal, low, medium, high, xhigh). Blank uses pipeline defaults."
            ),
        ),
    )
    codex_farm_root: str | None = Field(
        default=None,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Root",
            order=130,
            description="Optional pipeline-pack root for codex-farm. Blank uses repo_root/llm_pipelines.",
        ),
    )
    codex_farm_workspace_root: str | None = Field(
        default=None,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Workspace Root",
            order=135,
            description=(
                "Optional workspace root passed to codex-farm so Codex `--cd` is fixed. "
                "Blank lets pipeline codex_cd_mode decide."
            ),
        ),
    )
    codex_farm_context_blocks: int = Field(
        default=30,
        ge=0,
        le=500,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Context Blocks",
            order=143,
            description="Blocks before/after a candidate included in pass-1 bundles.",
            step=1,
            minimum=0,
            maximum=500,
        ),
    )
    codex_farm_knowledge_context_blocks: int = Field(
        default=0,
        ge=0,
        le=500,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Knowledge Context Blocks",
            order=144,
            description="Blocks before/after a knowledge chunk included as context in pass-4 bundles.",
            step=1,
            minimum=0,
            maximum=500,
        ),
    )
    codex_farm_failure_mode: CodexFarmFailureMode = Field(
        default=CodexFarmFailureMode.fail,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Failure Mode",
            order=150,
            description="Fail the run on codex-farm setup errors or fallback to deterministic outputs.",
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    workspace_completion_quiescence_seconds: float = Field(
        default=15.0,
        ge=0.1,
        le=600.0,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Workspace Completion Quiescence",
            order=151,
            description="Seconds a taskfile worker may stay quietly complete before repo code terminates the session cleanly.",
            step=1,
            minimum=0.1,
            maximum=600.0,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    completed_termination_grace_seconds: float = Field(
        default=15.0,
        ge=0.1,
        le=600.0,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Completed Termination Grace",
            order=152,
            description="Seconds the direct Codex runner waits before force-terminating a session already marked completed.",
            step=1,
            minimum=0.1,
            maximum=600.0,
            surface=RUN_SETTING_SURFACE_INTERNAL,
        ),
    )
    # Derived from workload shape; not directly edited in the run settings UI.
    effective_workers: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra={
            "ui_hidden": True,
            "run_setting_surface": RUN_SETTING_SURFACE_INTERNAL,
        },
    )
    mapping_path: str | None = Field(
        default=None,
        json_schema_extra={
            "ui_hidden": True,
            "run_setting_surface": RUN_SETTING_SURFACE_INTERNAL,
        },
    )
    overrides_path: str | None = Field(
        default=None,
        json_schema_extra={
            "ui_hidden": True,
            "run_setting_surface": RUN_SETTING_SURFACE_INTERNAL,
        },
    )

    @field_validator("epub_extractor", mode="before")
    @classmethod
    def _normalize_epub_extractor(cls, value: Any) -> Any:
        if value is None:
            return value
        normalized = normalize_epub_extractor_name(value)
        if normalized in EPUB_EXTRACTOR_CANONICAL_SET:
            if is_policy_locked_epub_extractor_name(normalized):
                logger.warning(
                    "Forcing epub_extractor=unstructured because %r is policy-locked off. "
                    "Set %s=1 to temporarily re-enable markdown extractors.",
                    normalized,
                    EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV,
                )
                return EpubExtractor.unstructured.value
            return normalized
        return value

    @field_validator("codex_farm_model", mode="before")
    @classmethod
    def _normalize_codex_farm_model(cls, value: Any) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None

    @field_validator("codex_farm_reasoning_effort", mode="before")
    @classmethod
    def _normalize_codex_farm_reasoning_effort(cls, value: Any) -> CodexReasoningEffort | None:
        if value is None:
            return None
        if isinstance(value, CodexReasoningEffort):
            return value
        if isinstance(value, Enum):
            candidate = str(value.value).strip().lower()
        else:
            candidate = str(value).strip().lower()
        if not candidate:
            return None
        try:
            return CodexReasoningEffort(candidate)
        except ValueError as exc:
            allowed = ", ".join(member.value for member in CodexReasoningEffort)
            raise ValueError(
                "codex farm reasoning effort must be one of: "
                f"{allowed}"
            ) from exc

    @field_validator("codex_farm_recipe_mode", mode="before")
    @classmethod
    def _normalize_codex_farm_recipe_mode(cls, value: Any) -> str | CodexFarmRecipeMode:
        normalized = str(value or "").strip().lower().replace("_", "-")
        if normalized in {"", "extract"}:
            return CodexFarmRecipeMode.extract.value
        if normalized == "benchmark":
            return CodexFarmRecipeMode.benchmark.value
        raise ValueError(
            "Invalid codex_farm_recipe_mode. Expected one of: extract, benchmark."
        )

    @field_validator("llm_recipe_pipeline", mode="before")
    @classmethod
    def _normalize_llm_recipe_pipeline(
        cls,
        value: Any,
    ) -> str | LlmRecipePipeline:
        return normalize_llm_recipe_pipeline_value(value)

    @field_validator("line_role_pipeline", mode="before")
    @classmethod
    def _normalize_line_role_pipeline(
        cls,
        value: Any,
    ) -> str | LineRolePipeline:
        return normalize_line_role_pipeline_value(value)

    @field_validator("llm_knowledge_pipeline", mode="before")
    @classmethod
    def _normalize_llm_knowledge_pipeline(
        cls,
        value: Any,
    ) -> str | LlmKnowledgePipeline:
        return normalize_llm_knowledge_pipeline_value(value)

    @field_validator("line_role_codex_exec_style", mode="before")
    @classmethod
    def _normalize_line_role_codex_exec_style(
        cls,
        value: Any,
    ) -> str | CodexExecStyle:
        return normalize_codex_exec_style_value(value)

    @field_validator("knowledge_codex_exec_style", mode="before")
    @classmethod
    def _normalize_knowledge_codex_exec_style(
        cls,
        value: Any,
    ) -> str | CodexExecStyle:
        return normalize_codex_exec_style_value(value)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        warn_context: str = "run settings",
    ) -> "RunSettings":
        if payload is None:
            return cls()
        data = dict(payload)
        unknown = tuple(sorted(set(data) - set(cls.model_fields)))
        if unknown:
            raise ValueError(
                f"Unknown {warn_context} keys: {', '.join(unknown)}"
            )
        llm_recipe_pipeline_raw = data.get("llm_recipe_pipeline")
        if llm_recipe_pipeline_raw is not None:
            try:
                data["llm_recipe_pipeline"] = normalize_llm_recipe_pipeline_value(
                    llm_recipe_pipeline_raw
                )
            except ValueError as exc:
                raise ValueError(
                    "Invalid llm_recipe_pipeline in "
                    f"{warn_context}. Expected one of: "
                    + ", ".join(RECIPE_CODEX_FARM_ALLOWED_PIPELINES)
                ) from exc
        if "line_role_pipeline" in data:
            data["line_role_pipeline"] = normalize_line_role_pipeline_value(
                data.get("line_role_pipeline")
            )
        if "llm_knowledge_pipeline" in data:
            data["llm_knowledge_pipeline"] = normalize_llm_knowledge_pipeline_value(
                data.get("llm_knowledge_pipeline")
            )
        if "line_role_codex_exec_style" in data:
            data["line_role_codex_exec_style"] = normalize_codex_exec_style_value(
                data.get("line_role_codex_exec_style")
            )
        if "knowledge_codex_exec_style" in data:
            data["knowledge_codex_exec_style"] = normalize_codex_exec_style_value(
                data.get("knowledge_codex_exec_style")
            )
        return cls.model_validate(data)

    def resolved_line_role_codex_exec_style(self) -> str:
        return resolve_codex_exec_style_value(self.line_role_codex_exec_style)

    def resolved_knowledge_codex_exec_style(self) -> str:
        return resolve_codex_exec_style_value(self.knowledge_codex_exec_style)

    def to_run_config_dict(self) -> dict[str, object]:
        from cookimport.config.codex_decision import (
            apply_bucket1_fixed_behavior_metadata,
        )

        payload = self.model_dump(mode="json", exclude_none=True)
        if (
            payload.get("llm_recipe_pipeline") == LlmRecipePipeline.off.value
            and payload.get("llm_knowledge_pipeline") == LlmKnowledgePipeline.off.value
        ):
            payload.pop("codex_farm_model", None)
            payload.pop("codex_farm_reasoning_effort", None)
        return apply_bucket1_fixed_behavior_metadata(payload)

    def to_public_run_config_dict(self) -> dict[str, object]:
        return self.to_product_run_config_dict()

    def to_product_run_config_dict(self) -> dict[str, object]:
        return project_run_config_payload(
            self.to_run_config_dict(),
            contract=RUN_SETTING_CONTRACT_PRODUCT,
        )

    def to_operator_run_config_dict(self) -> dict[str, object]:
        return project_run_config_payload(
            self.to_run_config_dict(),
            contract=RUN_SETTING_CONTRACT_OPERATOR,
        )

    def to_benchmark_lab_run_config_dict(self) -> dict[str, object]:
        return project_run_config_payload(
            self.to_run_config_dict(),
            contract=RUN_SETTING_CONTRACT_BENCHMARK_LAB,
        )

    def summary(
        self,
        *,
        include_internal: bool = False,
        contract: str | None = None,
    ) -> str:
        return summarize_run_config_payload(
            self.to_run_config_dict(),
            include_internal=include_internal,
            contract=contract,
        )

    def stable_hash(self) -> str:
        canonical_json = json.dumps(
            self.to_run_config_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def short_hash(self, length: int = 12) -> str:
        return self.stable_hash()[:length]

    @property
    def section_detector_backend(self) -> SectionDetectorBackend:
        return SectionDetectorBackend(
            _bucket1_fixed_behavior().section_detector_backend
        )

    @property
    def instruction_step_segmentation_policy(
        self,
    ) -> InstructionStepSegmentationPolicy:
        return InstructionStepSegmentationPolicy(
            _bucket1_fixed_behavior().instruction_step_segmentation_policy
        )

    @property
    def instruction_step_segmenter(self) -> InstructionStepSegmenter:
        return InstructionStepSegmenter(
            _bucket1_fixed_behavior().instruction_step_segmenter
        )

    @property
    def benchmark_sequence_matcher(self) -> str:
        return _bucket1_fixed_behavior().benchmark_sequence_matcher

    @property
    def multi_recipe_trace(self) -> bool:
        return _bucket1_fixed_behavior().multi_recipe_trace

    @property
    def p6_emit_metadata_debug(self) -> bool:
        return _bucket1_fixed_behavior().p6_emit_metadata_debug

    @property
    def codex_farm_pipeline_knowledge(self) -> str:
        return _bucket1_fixed_behavior().codex_farm_pipeline_knowledge


configure_run_setting_contracts(
    ordered_field_names=tuple(RunSettings.model_fields),
    surface_by_field_name={
        field_name: str(
            dict(field.json_schema_extra or {}).get(
                "run_setting_surface",
                RUN_SETTING_SURFACE_PUBLIC,
            )
        )
        for field_name, field in RunSettings.model_fields.items()
    },
)


from .run_settings_builders import build_run_settings
from .run_settings_ui import RunSettingUiSpec, run_settings_ui_specs
