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

logger = logging.getLogger(__name__)
_UI_REQUIRED_KEYS = ("ui_group", "ui_label", "ui_order")
RUN_SETTING_SURFACE_PUBLIC = "public"
RUN_SETTING_SURFACE_INTERNAL = "internal"
RUN_SETTING_CONTRACT_FULL = "full"
RUN_SETTING_CONTRACT_PRODUCT = "product"
RUN_SETTING_CONTRACT_OPERATOR = "operator"
RUN_SETTING_CONTRACT_BENCHMARK_LAB = "benchmark_lab"
RUN_SETTING_CONTRACT_INTERNAL = "internal"
_RUN_SETTING_CONTRACT_ALIASES = {
    "public": RUN_SETTING_CONTRACT_PRODUCT,
}
BENCHMARK_LAB_RUN_SETTING_NAMES = (
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "web_schema_normalizer",
    "web_html_text_extractor",
    "web_schema_min_confidence",
    "web_schema_min_ingredients",
    "web_schema_min_instruction_steps",
    "atomic_block_splitter",
    "line_role_pipeline",
    "codex_farm_recipe_mode",
    "codex_farm_model",
    "codex_farm_reasoning_effort",
)
BUCKET2_INTERNAL_ONLY_RUN_SETTING_NAMES = (
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
    "pdf_column_gap_ratio",
    "codex_farm_failure_mode",
    "ocr_device",
    "ocr_batch_size",
)
_SUMMARY_ORDER = (
    "epub_extractor",
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "multi_recipe_splitter",
    "multi_recipe_min_ingredient_lines",
    "multi_recipe_min_instruction_lines",
    "multi_recipe_for_the_guardrail",
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
    "pdf_column_gap_ratio",
    "pdf_ocr_policy",
    "ocr_device",
    "ocr_batch_size",
    "workers",
    "effective_workers",
    "pdf_split_workers",
    "epub_split_workers",
    "pdf_pages_per_job",
    "epub_spine_items_per_job",
    "warm_models",
    "llm_recipe_pipeline",
    "recipe_prompt_target_count",
    "recipe_worker_count",
    "recipe_shard_target_recipes",
    "recipe_shard_max_turns",
    "atomic_block_splitter",
    "line_role_pipeline",
    "line_role_prompt_target_count",
    "line_role_worker_count",
    "line_role_shard_target_lines",
    "line_role_shard_max_turns",
    "llm_knowledge_pipeline",
    "knowledge_prompt_target_count",
    "knowledge_worker_count",
    "knowledge_shard_target_chunks",
    "knowledge_shard_max_turns",
    "codex_farm_recipe_mode",
    "codex_farm_cmd",
    "codex_farm_model",
    "codex_farm_reasoning_effort",
    "codex_farm_context_blocks",
    "codex_farm_knowledge_context_blocks",
    "codex_farm_failure_mode",
    "mapping_path",
    "overrides_path",
)

RECIPE_CODEX_FARM_PIPELINE_SHARD_V1 = "codex-recipe-shard-v1"
RECIPE_CODEX_FARM_ALLOWED_PIPELINES = (
    "off",
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
)
RECIPE_CODEX_FARM_EXECUTION_PIPELINES = tuple(
    value for value in RECIPE_CODEX_FARM_ALLOWED_PIPELINES if value != "off"
)

RECIPE_CODEX_FARM_PIPELINE_POLICY = (
    "Recipe codex-farm parsing correction supports "
    f"'off' and {RECIPE_CODEX_FARM_PIPELINE_SHARD_V1!r}."
)

RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR = (
    f"{RECIPE_CODEX_FARM_PIPELINE_POLICY} Expected one of: "
    + ", ".join(repr(value) for value in RECIPE_CODEX_FARM_ALLOWED_PIPELINES)
    + "."
)

LINE_ROLE_PIPELINE_SHARD_V1 = "codex-line-role-shard-v1"
KNOWLEDGE_CODEX_PIPELINE_SHARD_V1 = "codex-knowledge-shard-v1"


class EpubExtractor(str, Enum):
    unstructured = "unstructured"
    beautifulsoup = "beautifulsoup"
    markdown = "markdown"
    markitdown = "markitdown"


class UnstructuredHtmlParserVersion(str, Enum):
    v1 = "v1"
    v2 = "v2"


class UnstructuredPreprocessMode(str, Enum):
    none = "none"
    br_split_v1 = "br_split_v1"
    semantic_v1 = "semantic_v1"


class OcrDevice(str, Enum):
    auto = "auto"
    cpu = "cpu"
    cuda = "cuda"
    mps = "mps"


class PdfOcrPolicy(str, Enum):
    auto = "auto"
    off = "off"
    always = "always"


class SectionDetectorBackend(str, Enum):
    shared_v1 = "shared_v1"


class InstructionStepSegmentationPolicy(str, Enum):
    off = "off"
    auto = "auto"
    always = "always"


class InstructionStepSegmenter(str, Enum):
    heuristic_v1 = "heuristic_v1"
    pysbd_v1 = "pysbd_v1"


class MultiRecipeSplitter(str, Enum):
    off = "off"
    rules_v1 = "rules_v1"


class WebSchemaExtractor(str, Enum):
    builtin_jsonld = "builtin_jsonld"
    extruct = "extruct"
    scrape_schema_recipe = "scrape_schema_recipe"
    recipe_scrapers = "recipe_scrapers"
    ensemble_v1 = "ensemble_v1"


class WebSchemaNormalizer(str, Enum):
    simple = "simple"
    pyld = "pyld"


class WebHtmlTextExtractor(str, Enum):
    bs4 = "bs4"
    trafilatura = "trafilatura"
    readability_lxml = "readability_lxml"
    justext = "justext"
    boilerpy3 = "boilerpy3"
    ensemble_v1 = "ensemble_v1"


class WebSchemaPolicy(str, Enum):
    prefer_schema = "prefer_schema"
    schema_only = "schema_only"
    heuristic_only = "heuristic_only"


class IngredientTextFixBackend(str, Enum):
    none = "none"
    ftfy = "ftfy"


class IngredientPreNormalizeMode(str, Enum):
    aggressive_v1 = "aggressive_v1"


class IngredientPackagingMode(str, Enum):
    off = "off"
    regex_v1 = "regex_v1"


class IngredientParserBackend(str, Enum):
    ingredient_parser_nlp = "ingredient_parser_nlp"
    quantulum3_regex = "quantulum3_regex"
    hybrid_nlp_then_quantulum3 = "hybrid_nlp_then_quantulum3"


class IngredientUnitCanonicalizer(str, Enum):
    pint = "pint"


class IngredientMissingUnitPolicy(str, Enum):
    medium = "medium"
    null = "null"
    each = "each"


class P6TimeBackend(str, Enum):
    regex_v1 = "regex_v1"
    quantulum3_v1 = "quantulum3_v1"
    hybrid_regex_quantulum3_v1 = "hybrid_regex_quantulum3_v1"


class P6TimeTotalStrategy(str, Enum):
    sum_all_v1 = "sum_all_v1"
    max_v1 = "max_v1"
    selective_sum_v1 = "selective_sum_v1"


class P6TemperatureBackend(str, Enum):
    regex_v1 = "regex_v1"
    quantulum3_v1 = "quantulum3_v1"
    hybrid_regex_quantulum3_v1 = "hybrid_regex_quantulum3_v1"


class P6TemperatureUnitBackend(str, Enum):
    builtin_v1 = "builtin_v1"
    pint_v1 = "pint_v1"


class P6OvenlikeMode(str, Enum):
    keywords_v1 = "keywords_v1"
    off = "off"


class P6YieldMode(str, Enum):
    scored_v1 = "scored_v1"


class LlmRecipePipeline(str, Enum):
    off = "off"
    codex_recipe_shard_v1 = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1


class AtomicBlockSplitter(str, Enum):
    off = "off"
    atomic_v1 = "atomic-v1"


class LineRolePipeline(str, Enum):
    off = "off"
    codex_line_role_shard_v1 = LINE_ROLE_PIPELINE_SHARD_V1


class LlmKnowledgePipeline(str, Enum):
    off = "off"
    codex_knowledge_shard_v1 = KNOWLEDGE_CODEX_PIPELINE_SHARD_V1


class CodexFarmFailureMode(str, Enum):
    fail = "fail"
    fallback = "fallback"


class CodexFarmRecipeMode(str, Enum):
    extract = "extract"
    benchmark = "benchmark"


class CodexReasoningEffort(str, Enum):
    none = "none"
    minimal = "minimal"
    low = "low"
    medium = "medium"
    high = "high"
    xhigh = "xhigh"


def normalize_llm_recipe_pipeline_value(value: Any) -> str:
    normalized = str(getattr(value, "value", value) or "").strip().lower()
    normalized = normalized or LlmRecipePipeline.off.value
    if normalized not in RECIPE_CODEX_FARM_ALLOWED_PIPELINES:
        raise ValueError(RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR)
    return normalized


def normalize_line_role_pipeline_value(value: Any) -> str:
    normalized = str(getattr(value, "value", value) or "").strip().lower().replace("_", "-")
    if normalized in {"", "off", "none", "default"}:
        return LineRolePipeline.off.value
    allowed = {
        LineRolePipeline.off.value,
        LINE_ROLE_PIPELINE_SHARD_V1,
    }
    if normalized not in allowed:
        raise ValueError(
            "Invalid line_role_pipeline. Expected one of: "
            f"{LineRolePipeline.off.value}, {LINE_ROLE_PIPELINE_SHARD_V1}."
        )
    return normalized


def normalize_llm_knowledge_pipeline_value(value: Any) -> str:
    normalized = str(getattr(value, "value", value) or "").strip().lower()
    normalized = normalized or LlmKnowledgePipeline.off.value
    allowed = {
        LlmKnowledgePipeline.off.value,
        KNOWLEDGE_CODEX_PIPELINE_SHARD_V1,
    }
    if normalized not in allowed:
        raise ValueError(
            "Invalid llm_knowledge_pipeline. Expected one of: "
            f"{LlmKnowledgePipeline.off.value}, {KNOWLEDGE_CODEX_PIPELINE_SHARD_V1}."
        )
    return normalized


def _bucket1_fixed_behavior():
    from cookimport.config.codex_decision import bucket1_fixed_behavior

    return bucket1_fixed_behavior()


def _ui_meta(
    *,
    group: str,
    label: str,
    order: int,
    description: str,
    surface: str = RUN_SETTING_SURFACE_PUBLIC,
    step: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "ui_group": group,
        "ui_label": label,
        "ui_order": order,
        "ui_description": description,
        "run_setting_surface": surface,
    }
    if step is not None:
        meta["ui_step"] = step
    if minimum is not None:
        meta["ui_min"] = minimum
    if maximum is not None:
        meta["ui_max"] = maximum
    return meta


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
        default=UnstructuredPreprocessMode.semantic_v1,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Unstructured EPUB Preprocess",
            order=64,
            description="EPUB HTML preprocessing mode before Unstructured partitioning.",
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
                "Preferred recipe worker-session count when explicit recipe worker count is unset. "
                "The default recipe runtime now writes one candidate-owned shard per recipe unless "
                "`recipe_shard_target_recipes` explicitly opts back into bundling."
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
    recipe_shard_target_recipes: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Recipe Shard Target",
            order=110,
            description=(
                "Optional legacy opt-out from single-candidate recipe shards. "
                "Set this only when you intentionally want multi-recipe bundling."
            ),
            step=1,
            minimum=1,
            maximum=1024,
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
                "Optional non-recipe knowledge review pipeline. "
                "Off keeps the fully vanilla nonrecipe authority."
            ),
        ),
    )
    knowledge_prompt_target_count: int | None = Field(
        default=5,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Review Shard Count",
            order=115,
            description=(
                "Direct shard-count override for shard-v1 knowledge runtime. "
                "When set, the planner partitions ordered non-recipe chunks into this many shards."
            ),
            step=1,
            minimum=1,
            maximum=256,
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
    knowledge_shard_target_chunks: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge Shard Target",
            order=115,
            description="Optional target chunks per shard for shard-v1 knowledge runtime.",
            step=1,
            minimum=1,
            maximum=4096,
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
        if normalized in {"", "extract", "default"}:
            return CodexFarmRecipeMode.extract.value
        if normalized in {"benchmark", "line-label", "line-labels"}:
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
        return cls.model_validate(data)

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


@dataclass(frozen=True)
class RunSettingUiSpec:
    name: str
    label: str
    group: str
    order: int
    description: str
    value_kind: Literal["enum", "bool", "int", "string"]
    choices: tuple[str, ...] = ()
    allows_none: bool = False
    step: int = 1
    minimum: int | None = None
    maximum: int | None = None


def _unwrap_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if len(args) == 1:
        return args[0]
    return annotation


def _annotation_allows_none(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is None:
        return False
    return any(arg is type(None) for arg in get_args(annotation))


def _value_kind_for_annotation(annotation: Any) -> Literal["enum", "bool", "int", "string"]:
    unwrapped = _unwrap_optional(annotation)
    if isinstance(unwrapped, type) and issubclass(unwrapped, Enum):
        return "enum"
    if unwrapped is bool:
        return "bool"
    if unwrapped is int:
        return "int"
    return "string"


def run_settings_ui_specs(*, include_internal: bool = False) -> list[RunSettingUiSpec]:
    specs: list[RunSettingUiSpec] = []
    for field_name, field in RunSettings.model_fields.items():
        extra = dict(field.json_schema_extra or {})
        if extra.get("ui_hidden"):
            continue
        if (
            not include_internal
            and run_setting_surface(field_name) != RUN_SETTING_SURFACE_PUBLIC
        ):
            continue
        for key in _UI_REQUIRED_KEYS:
            if key not in extra:
                raise ValueError(f"RunSettings.{field_name} missing UI metadata key: {key}")

        value_kind = _value_kind_for_annotation(field.annotation)
        allows_none = _annotation_allows_none(field.annotation)
        choices: tuple[str, ...] = ()
        annotation = _unwrap_optional(field.annotation)
        if value_kind == "enum" and isinstance(annotation, type) and issubclass(annotation, Enum):
            choices = tuple(str(member.value) for member in annotation)
            if field_name == "llm_recipe_pipeline":
                choices = tuple(str(member.value) for member in LlmRecipePipeline)
            elif field_name == "epub_extractor":
                choices = epub_extractor_enabled_choices()
            if allows_none:
                none_label = (
                    "pipeline default"
                    if str(extra.get("ui_group", "")) == "LLM"
                    else "default"
                )
                choices = (none_label, *choices)
        specs.append(
            RunSettingUiSpec(
                name=field_name,
                label=str(extra["ui_label"]),
                group=str(extra["ui_group"]),
                order=int(extra["ui_order"]),
                description=str(extra.get("ui_description", "")).strip(),
                value_kind=value_kind,
                choices=choices,
                allows_none=allows_none,
                step=int(extra.get("ui_step", 1)),
                minimum=(
                    int(extra["ui_min"])
                    if extra.get("ui_min") is not None
                    else None
                ),
                maximum=(
                    int(extra["ui_max"])
                    if extra.get("ui_max") is not None
                    else None
                ),
            )
        )
    specs.sort(key=lambda spec: (spec.group, spec.order, spec.name))
    return specs


def _normalized_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value).strip().lower()
    return str(value).strip().lower()


def run_setting_surface(field_name: str) -> str:
    field = RunSettings.model_fields[field_name]
    extra = dict(field.json_schema_extra or {})
    surface = str(
        extra.get("run_setting_surface", RUN_SETTING_SURFACE_PUBLIC)
    ).strip().lower()
    if surface == RUN_SETTING_SURFACE_INTERNAL:
        return RUN_SETTING_SURFACE_INTERNAL
    return RUN_SETTING_SURFACE_PUBLIC


def public_run_setting_names() -> tuple[str, ...]:
    return tuple(
        name
        for name in RunSettings.model_fields
        if run_setting_surface(name) == RUN_SETTING_SURFACE_PUBLIC
    )


def internal_run_setting_names() -> tuple[str, ...]:
    return tuple(
        name
        for name in RunSettings.model_fields
        if run_setting_surface(name) == RUN_SETTING_SURFACE_INTERNAL
    )


def product_run_setting_names() -> tuple[str, ...]:
    return public_run_setting_names()


def benchmark_lab_run_setting_names() -> tuple[str, ...]:
    public_names = set(public_run_setting_names())
    return tuple(
        name for name in BENCHMARK_LAB_RUN_SETTING_NAMES if name in public_names
    )


def ordinary_operator_run_setting_names() -> tuple[str, ...]:
    benchmark_lab_names = set(benchmark_lab_run_setting_names())
    return tuple(
        name for name in public_run_setting_names() if name not in benchmark_lab_names
    )


def _normalize_run_setting_contract(
    *,
    include_internal: bool | None,
    contract: str | None,
) -> str:
    if contract is None:
        return (
            RUN_SETTING_CONTRACT_FULL
            if include_internal
            else RUN_SETTING_CONTRACT_PRODUCT
        )
    normalized = str(contract).strip().lower()
    normalized = _RUN_SETTING_CONTRACT_ALIASES.get(normalized, normalized)
    allowed = {
        RUN_SETTING_CONTRACT_FULL,
        RUN_SETTING_CONTRACT_PRODUCT,
        RUN_SETTING_CONTRACT_OPERATOR,
        RUN_SETTING_CONTRACT_BENCHMARK_LAB,
        RUN_SETTING_CONTRACT_INTERNAL,
    }
    if normalized not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ValueError(
            f"Unknown run-setting contract {contract!r}. Expected one of: {allowed_list}."
        )
    return normalized


def _run_setting_names_for_contract(contract: str) -> tuple[str, ...]:
    if contract == RUN_SETTING_CONTRACT_FULL:
        return tuple(RunSettings.model_fields)
    if contract == RUN_SETTING_CONTRACT_PRODUCT:
        return product_run_setting_names()
    if contract == RUN_SETTING_CONTRACT_OPERATOR:
        return ordinary_operator_run_setting_names()
    if contract == RUN_SETTING_CONTRACT_BENCHMARK_LAB:
        return benchmark_lab_run_setting_names()
    if contract == RUN_SETTING_CONTRACT_INTERNAL:
        return internal_run_setting_names()
    raise ValueError(f"Unhandled run-setting contract: {contract}")


def project_run_config_payload(
    payload: Mapping[str, Any] | None,
    *,
    include_internal: bool | None = True,
    contract: str | None = None,
) -> dict[str, Any]:
    if payload is None:
        return {}
    normalized_contract = _normalize_run_setting_contract(
        include_internal=include_internal,
        contract=contract,
    )
    allowed_names = set(_run_setting_names_for_contract(normalized_contract))
    return {
        name: payload[name]
        for name in RunSettings.model_fields
        if name in allowed_names and name in payload
    }


def summarize_run_config_payload(
    payload: Mapping[str, Any] | None,
    *,
    include_internal: bool = False,
    contract: str | None = None,
) -> str:
    projected = project_run_config_payload(
        payload,
        include_internal=include_internal,
        contract=contract,
    )
    ordered_names = [
        name
        for name in _SUMMARY_ORDER
        if name in projected
    ]
    remaining_names = [name for name in projected if name not in ordered_names]
    parts: list[str] = []
    for key in (*ordered_names, *remaining_names):
        value = projected[key]
        if key.endswith("_path"):
            value = Path(str(value)).name
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " | ".join(parts)


def compute_effective_workers(
    *,
    workers: int,
    epub_split_workers: int,
    epub_extractor: str | EpubExtractor = EpubExtractor.unstructured,
    file_paths: Sequence[Path] | None = None,
    all_epub: bool | None = None,
) -> int:
    effective_all_epub = bool(all_epub)
    if all_epub is None and file_paths is not None:
        effective_all_epub = bool(file_paths) and all(
            path.suffix.lower() == ".epub" for path in file_paths
        )
    selected_extractor = _normalized_value(epub_extractor)
    if (
        effective_all_epub
        and selected_extractor != EpubExtractor.markitdown.value
        and epub_split_workers > workers
    ):
        return epub_split_workers
    return workers


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
    ) = UnstructuredPreprocessMode.semantic_v1,
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
    atomic_block_splitter: str | AtomicBlockSplitter = AtomicBlockSplitter.off,
    line_role_pipeline: str | LineRolePipeline = LineRolePipeline.off,
    llm_knowledge_pipeline: str | LlmKnowledgePipeline = LlmKnowledgePipeline.off,
    codex_farm_recipe_mode: str | CodexFarmRecipeMode = CodexFarmRecipeMode.extract,
    codex_farm_cmd: str = "codex-farm",
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | CodexReasoningEffort | None = None,
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_context_blocks: int = 30,
    codex_farm_knowledge_context_blocks: int = 0,
    codex_farm_failure_mode: str | CodexFarmFailureMode = CodexFarmFailureMode.fail,
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
            "atomic_block_splitter": _normalized_value(atomic_block_splitter),
            "line_role_pipeline": _normalized_value(line_role_pipeline),
            "llm_knowledge_pipeline": _normalized_value(llm_knowledge_pipeline),
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
            "effective_workers": resolved_effective_workers,
            "mapping_path": str(mapping_path) if mapping_path is not None else None,
            "overrides_path": str(overrides_path) if overrides_path is not None else None,
        }
    )
