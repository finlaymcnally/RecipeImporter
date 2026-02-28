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

_UNKNOWN_KEY_WARNINGS: set[tuple[str, ...]] = set()
_UI_REQUIRED_KEYS = ("ui_group", "ui_label", "ui_order")
_SUMMARY_ORDER = (
    "epub_extractor",
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "table_extraction",
    "section_detector_backend",
    "instruction_step_segmentation_policy",
    "instruction_step_segmenter",
    "multi_recipe_splitter",
    "multi_recipe_trace",
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
    "p6_emit_metadata_debug",
    "benchmark_sequence_matcher",
    "recipe_scorer_backend",
    "recipe_score_gold_min",
    "recipe_score_silver_min",
    "recipe_score_bronze_min",
    "recipe_score_min_ingredient_lines",
    "recipe_score_min_instruction_lines",
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
    "llm_knowledge_pipeline",
    "llm_tags_pipeline",
    "codex_farm_cmd",
    "codex_farm_model",
    "codex_farm_reasoning_effort",
    "codex_farm_pipeline_pass1",
    "codex_farm_pipeline_pass2",
    "codex_farm_pipeline_pass3",
    "codex_farm_pipeline_pass4_knowledge",
    "codex_farm_pipeline_pass5_tags",
    "codex_farm_context_blocks",
    "codex_farm_knowledge_context_blocks",
    "codex_farm_failure_mode",
    "tag_catalog_json",
    "mapping_path",
    "overrides_path",
)

RECIPE_CODEX_FARM_UNLOCK_ENV = "COOKIMPORT_ALLOW_CODEX_FARM"

RECIPE_CODEX_FARM_PIPELINE_POLICY = (
    "Recipe codex-farm parsing correction supports 'off' and 'codex-farm-3pass-v1'."
)

RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR = (
    f"{RECIPE_CODEX_FARM_PIPELINE_POLICY} Expected 'off' or 'codex-farm-3pass-v1'."
)


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


class TableExtraction(str, Enum):
    off = "off"
    on = "on"


class SectionDetectorBackend(str, Enum):
    legacy = "legacy"
    shared_v1 = "shared_v1"


class InstructionStepSegmentationPolicy(str, Enum):
    off = "off"
    auto = "auto"
    always = "always"


class InstructionStepSegmenter(str, Enum):
    heuristic_v1 = "heuristic_v1"
    pysbd_v1 = "pysbd_v1"


class MultiRecipeSplitter(str, Enum):
    legacy = "legacy"
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
    legacy = "legacy"
    aggressive_v1 = "aggressive_v1"


class IngredientPackagingMode(str, Enum):
    off = "off"
    regex_v1 = "regex_v1"


class IngredientParserBackend(str, Enum):
    ingredient_parser_nlp = "ingredient_parser_nlp"
    quantulum3_regex = "quantulum3_regex"
    hybrid_nlp_then_quantulum3 = "hybrid_nlp_then_quantulum3"


class IngredientUnitCanonicalizer(str, Enum):
    legacy = "legacy"
    pint = "pint"


class IngredientMissingUnitPolicy(str, Enum):
    legacy_medium = "legacy_medium"
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
    legacy_v1 = "legacy_v1"
    scored_v1 = "scored_v1"


class LlmRecipePipeline(str, Enum):
    off = "off"
    codex_farm_3pass_v1 = "codex-farm-3pass-v1"


class LlmKnowledgePipeline(str, Enum):
    off = "off"
    codex_farm_knowledge_v1 = "codex-farm-knowledge-v1"


class LlmTagsPipeline(str, Enum):
    off = "off"
    codex_farm_tags_v1 = "codex-farm-tags-v1"


class CodexFarmFailureMode(str, Enum):
    fail = "fail"
    fallback = "fallback"


class CodexReasoningEffort(str, Enum):
    none = "none"
    minimal = "minimal"
    low = "low"
    medium = "medium"
    high = "high"
    xhigh = "xhigh"


def _ui_meta(
    *,
    group: str,
    label: str,
    order: int,
    description: str,
    step: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "ui_group": group,
        "ui_label": label,
        "ui_order": order,
        "ui_description": description,
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
        default=False,
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
    table_extraction: TableExtraction = Field(
        default=TableExtraction.off,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Table Extraction",
            order=65,
            description=(
                "Detect and export non-recipe tables (tables.jsonl/tables.md) and keep "
                "table rows together during knowledge chunking."
            ),
        ),
    )
    section_detector_backend: SectionDetectorBackend = Field(
        default=SectionDetectorBackend.legacy,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Section Detector Backend",
            order=66,
            description=(
                "Section detector backend used by importers and section-aware staging "
                "contracts. legacy keeps current behavior; shared_v1 enables shared "
                "deterministic detection."
            ),
        ),
    )
    multi_recipe_splitter: MultiRecipeSplitter = Field(
        default=MultiRecipeSplitter.legacy,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Multi-recipe Splitter",
            order=67,
            description=(
                "Candidate splitter backend for merged multi-recipe spans. "
                "legacy keeps importer-local behavior; rules_v1 uses shared deterministic splitting."
            ),
        ),
    )
    multi_recipe_trace: bool = Field(
        default=False,
        json_schema_extra=_ui_meta(
            group="Extraction",
            label="Multi-recipe Trace",
            order=68,
            description="Write shared splitter trace artifacts when multi-recipe splitting runs.",
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
    instruction_step_segmentation_policy: InstructionStepSegmentationPolicy = Field(
        default=InstructionStepSegmentationPolicy.auto,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Instruction Segmentation Policy",
            order=65,
            description=(
                "Fallback instruction-step segmentation policy: off, auto, or always."
            ),
        ),
    )
    instruction_step_segmenter: InstructionStepSegmenter = Field(
        default=InstructionStepSegmenter.heuristic_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Instruction Segmenter",
            order=66,
            description=(
                "Deterministic fallback segmenter backend: heuristic_v1 or pysbd_v1."
            ),
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
        ),
    )
    ingredient_pre_normalize_mode: IngredientPreNormalizeMode = Field(
        default=IngredientPreNormalizeMode.legacy,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Ingredient Pre-normalize Mode",
            order=68,
            description=(
                "Ingredient pre-parse normalization mode "
                "(legacy or aggressive_v1)."
            ),
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
        ),
    )
    ingredient_unit_canonicalizer: IngredientUnitCanonicalizer = Field(
        default=IngredientUnitCanonicalizer.legacy,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="Ingredient Unit Canonicalizer",
            order=71,
            description=(
                "Unit canonicalization mode (legacy or pint) applied after parsing."
            ),
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
                "legacy_medium, null, or each."
            ),
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
        ),
    )
    p6_temperature_unit_backend: P6TemperatureUnitBackend = Field(
        default=P6TemperatureUnitBackend.builtin_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Temperature Unit Backend",
            order=76,
            description="Priority 6 temperature unit conversion backend (builtin_v1 or pint_v1).",
        ),
    )
    p6_ovenlike_mode: P6OvenlikeMode = Field(
        default=P6OvenlikeMode.keywords_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Ovenlike Mode",
            order=77,
            description="Priority 6 oven-like temperature classifier mode (keywords_v1 or off).",
        ),
    )
    p6_yield_mode: P6YieldMode = Field(
        default=P6YieldMode.legacy_v1,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Yield Mode",
            order=78,
            description="Priority 6 yield parser mode (legacy_v1 passthrough or scored_v1).",
        ),
    )
    p6_emit_metadata_debug: bool = Field(
        default=False,
        json_schema_extra=_ui_meta(
            group="Parsing",
            label="P6 Emit Metadata Debug",
            order=79,
            description="Write optional Priority 6 debug metadata sidecar artifacts.",
        ),
    )
    benchmark_sequence_matcher: str = Field(
        default="dmp",
        json_schema_extra=_ui_meta(
            group="Benchmark",
            label="Sequence Matcher",
            order=73,
            description=(
                "Canonical-text matcher mode for benchmark/eval runs (dmp only)."
            ),
        ),
    )
    recipe_scorer_backend: str = Field(
        default="heuristic_v1",
        json_schema_extra=_ui_meta(
            group="Scoring",
            label="Recipe Scorer Backend",
            order=74,
            description="Recipe-likeness scorer backend. Default and supported backend is heuristic_v1.",
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
        ),
    )
    ocr_device: OcrDevice = Field(
        default=OcrDevice.auto,
        json_schema_extra=_ui_meta(
            group="OCR",
            label="OCR Device",
            order=80,
            description="OCR device selection for PDF processing.",
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
                "Recipe codex-farm parsing correction."
            ),
        ),
    )
    llm_knowledge_pipeline: LlmKnowledgePipeline = Field(
        default=LlmKnowledgePipeline.off,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Knowledge LLM Pipeline",
            order=115,
            description=(
                "Optional non-recipe knowledge harvesting pipeline. "
                "Off keeps deterministic behavior."
            ),
        ),
    )
    llm_tags_pipeline: LlmTagsPipeline = Field(
        default=LlmTagsPipeline.off,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Tags LLM Pipeline",
            order=116,
            description=(
                "Optional pass-5 tag suggestion pipeline over staged final drafts. "
                "Off keeps deterministic behavior."
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
    codex_farm_pipeline_pass1: str = Field(
        default="recipe.chunking.v1",
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Pass1 Pipeline",
            order=136,
            description="codex-farm pipeline id used for recipe boundary refinement (pass1).",
        ),
    )
    codex_farm_pipeline_pass2: str = Field(
        default="recipe.schemaorg.v1",
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Pass2 Pipeline",
            order=137,
            description="codex-farm pipeline id used for schema.org extraction (pass2).",
        ),
    )
    codex_farm_pipeline_pass3: str = Field(
        default="recipe.final.v1",
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Pass3 Pipeline",
            order=138,
            description="codex-farm pipeline id used for final draft generation (pass3).",
        ),
    )
    codex_farm_pipeline_pass4_knowledge: str = Field(
        default="recipe.knowledge.v1",
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Pass4 Knowledge Pipeline",
            order=139,
            description="codex-farm pipeline id used for knowledge harvesting (pass4).",
        ),
    )
    codex_farm_pipeline_pass5_tags: str = Field(
        default="recipe.tags.v1",
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Pass5 Tags Pipeline",
            order=140,
            description="codex-farm pipeline id used for tag suggestions (pass5).",
        ),
    )
    codex_farm_context_blocks: int = Field(
        default=30,
        ge=0,
        le=500,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Context Blocks",
            order=141,
            description="Blocks before/after a candidate included in pass-1 bundles.",
            step=1,
            minimum=0,
            maximum=500,
        ),
    )
    codex_farm_knowledge_context_blocks: int = Field(
        default=12,
        ge=0,
        le=500,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Knowledge Context Blocks",
            order=142,
            description="Blocks before/after a knowledge chunk included as context in pass-4 bundles.",
            step=1,
            minimum=0,
            maximum=500,
        ),
    )
    tag_catalog_json: str = Field(
        default="data/tagging/tag_catalog.json",
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Tag Catalog JSON",
            order=143,
            description=(
                "Tag catalog snapshot path used by pass-5 tag suggestions when llm_tags_pipeline is enabled."
            ),
        ),
    )
    codex_farm_failure_mode: CodexFarmFailureMode = Field(
        default=CodexFarmFailureMode.fail,
        json_schema_extra=_ui_meta(
            group="LLM",
            label="Codex Farm Failure Mode",
            order=150,
            description="Fail the run on codex-farm setup errors or fallback to deterministic outputs.",
        ),
    )
    # Derived from workload shape; not directly edited in the run settings UI.
    effective_workers: int | None = Field(
        default=None,
        ge=1,
        json_schema_extra={"ui_hidden": True},
    )
    mapping_path: str | None = Field(default=None, json_schema_extra={"ui_hidden": True})
    overrides_path: str | None = Field(default=None, json_schema_extra={"ui_hidden": True})

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

    @field_validator("benchmark_sequence_matcher", mode="before")
    @classmethod
    def _normalize_benchmark_sequence_matcher(cls, value: Any) -> str:
        normalized = str(value or "dmp").strip().lower()
        supported = supported_sequence_matcher_modes()
        if normalized not in supported:
            raise ValueError(
                "Invalid benchmark sequence matcher mode "
                f"{value!r}. Supported: {', '.join(supported)}."
            )
        return normalized

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
        if unknown and unknown not in _UNKNOWN_KEY_WARNINGS:
            logger.warning(
                "Ignoring unknown %s keys: %s",
                warn_context,
                ", ".join(unknown),
            )
            _UNKNOWN_KEY_WARNINGS.add(unknown)
        llm_recipe_pipeline_raw = data.get("llm_recipe_pipeline")
        if llm_recipe_pipeline_raw is not None:
            if isinstance(llm_recipe_pipeline_raw, Enum):
                normalized_recipe_pipeline = str(llm_recipe_pipeline_raw.value).strip().lower()
            else:
                normalized_recipe_pipeline = str(llm_recipe_pipeline_raw).strip().lower()
            if normalized_recipe_pipeline == LlmRecipePipeline.off.value:
                pass
            elif normalized_recipe_pipeline == LlmRecipePipeline.codex_farm_3pass_v1.value:
                pass
            else:
                logger.warning(
                    "Forcing llm_recipe_pipeline=off in %s because recipe codex-farm parsing "
                    "correction only supports: off, codex-farm-3pass-v1. Ignoring value %r.",
                    warn_context,
                    llm_recipe_pipeline_raw,
                )
                data["llm_recipe_pipeline"] = LlmRecipePipeline.off.value
        epub_extractor_raw = data.get("epub_extractor")
        if epub_extractor_raw is not None:
            if isinstance(epub_extractor_raw, Enum):
                normalized_epub_extractor = normalize_epub_extractor_name(
                    str(epub_extractor_raw.value).strip().lower()
                )
            else:
                normalized_epub_extractor = normalize_epub_extractor_name(
                    str(epub_extractor_raw).strip().lower()
                )
            if normalized_epub_extractor == "auto":
                logger.warning(
                    "Forcing epub_extractor=unstructured in %s because auto extractor mode "
                    "was removed. Ignoring value %r.",
                    warn_context,
                    epub_extractor_raw,
                )
                data["epub_extractor"] = EpubExtractor.unstructured.value
            elif normalized_epub_extractor == "legacy":
                logger.warning(
                    "Migrating epub_extractor=legacy to beautifulsoup in %s.",
                    warn_context,
                )
                data["epub_extractor"] = EpubExtractor.beautifulsoup.value
            elif is_policy_locked_epub_extractor_name(normalized_epub_extractor):
                logger.warning(
                    "Forcing epub_extractor=unstructured in %s because %r is policy-locked off. "
                    "Set %s=1 to temporarily re-enable markdown extractors.",
                    warn_context,
                    normalized_epub_extractor,
                    EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV,
                )
                data["epub_extractor"] = EpubExtractor.unstructured.value
            elif normalized_epub_extractor == "beautifulsoup":
                data["epub_extractor"] = EpubExtractor.beautifulsoup.value
        return cls.model_validate(data)

    def to_run_config_dict(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", exclude_none=True)
        if (
            payload.get("llm_recipe_pipeline") == LlmRecipePipeline.off.value
            and payload.get("llm_knowledge_pipeline") == LlmKnowledgePipeline.off.value
            and payload.get("llm_tags_pipeline") == LlmTagsPipeline.off.value
        ):
            payload.pop("codex_farm_model", None)
            payload.pop("codex_farm_reasoning_effort", None)
        return payload

    def summary(self) -> str:
        payload = self.to_run_config_dict()
        parts: list[str] = []
        for key in _SUMMARY_ORDER:
            if key not in payload:
                continue
            value = payload[key]
            if key.endswith("_path"):
                value = Path(str(value)).name
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = str(value)
            parts.append(f"{key}={rendered}")
        return " | ".join(parts)

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


def run_settings_ui_specs() -> list[RunSettingUiSpec]:
    specs: list[RunSettingUiSpec] = []
    for field_name, field in RunSettings.model_fields.items():
        extra = dict(field.json_schema_extra or {})
        if extra.get("ui_hidden"):
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
                choices = (
                    LlmRecipePipeline.off.value,
                    LlmRecipePipeline.codex_farm_3pass_v1.value,
                )
            elif field_name == "epub_extractor":
                choices = epub_extractor_enabled_choices()
            if allows_none:
                none_label = (
                    "pipeline default"
                    if str(extra.get("ui_group", "")) == "LLM"
                    else "default"
                )
                choices = (none_label, *choices)
        elif field_name == "benchmark_sequence_matcher":
            value_kind = "enum"
            choices = tuple(str(mode) for mode in supported_sequence_matcher_modes())

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
    epub_unstructured_skip_headers_footers: bool = False,
    epub_unstructured_preprocess_mode: (
        str | UnstructuredPreprocessMode
    ) = UnstructuredPreprocessMode.br_split_v1,
    ocr_device: str | OcrDevice,
    ocr_batch_size: int,
    warm_models: bool,
    table_extraction: str | TableExtraction = TableExtraction.off,
    section_detector_backend: (
        str | SectionDetectorBackend
    ) = SectionDetectorBackend.legacy,
    multi_recipe_splitter: str | MultiRecipeSplitter = MultiRecipeSplitter.legacy,
    multi_recipe_trace: bool = False,
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
    instruction_step_segmentation_policy: (
        str | InstructionStepSegmentationPolicy
    ) = InstructionStepSegmentationPolicy.auto,
    instruction_step_segmenter: (
        str | InstructionStepSegmenter
    ) = InstructionStepSegmenter.heuristic_v1,
    ingredient_text_fix_backend: (
        str | IngredientTextFixBackend
    ) = IngredientTextFixBackend.none,
    ingredient_pre_normalize_mode: (
        str | IngredientPreNormalizeMode
    ) = IngredientPreNormalizeMode.legacy,
    ingredient_packaging_mode: (
        str | IngredientPackagingMode
    ) = IngredientPackagingMode.off,
    ingredient_parser_backend: (
        str | IngredientParserBackend
    ) = IngredientParserBackend.ingredient_parser_nlp,
    ingredient_unit_canonicalizer: (
        str | IngredientUnitCanonicalizer
    ) = IngredientUnitCanonicalizer.legacy,
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
    p6_yield_mode: str | P6YieldMode = P6YieldMode.legacy_v1,
    p6_emit_metadata_debug: bool = False,
    benchmark_sequence_matcher: str = "dmp",
    recipe_scorer_backend: str = "heuristic_v1",
    recipe_score_gold_min: float = 0.75,
    recipe_score_silver_min: float = 0.55,
    recipe_score_bronze_min: float = 0.35,
    recipe_score_min_ingredient_lines: int = 1,
    recipe_score_min_instruction_lines: int = 1,
    llm_recipe_pipeline: str | LlmRecipePipeline = LlmRecipePipeline.off,
    llm_knowledge_pipeline: str | LlmKnowledgePipeline = LlmKnowledgePipeline.off,
    llm_tags_pipeline: str | LlmTagsPipeline = LlmTagsPipeline.off,
    codex_farm_cmd: str = "codex-farm",
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | CodexReasoningEffort | None = None,
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    codex_farm_pipeline_pass1: str = "recipe.chunking.v1",
    codex_farm_pipeline_pass2: str = "recipe.schemaorg.v1",
    codex_farm_pipeline_pass3: str = "recipe.final.v1",
    codex_farm_pipeline_pass4_knowledge: str = "recipe.knowledge.v1",
    codex_farm_pipeline_pass5_tags: str = "recipe.tags.v1",
    codex_farm_context_blocks: int = 30,
    codex_farm_knowledge_context_blocks: int = 12,
    tag_catalog_json: Path | str = "data/tagging/tag_catalog.json",
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
            "ocr_batch_size": ocr_batch_size,
            "warm_models": bool(warm_models),
            "table_extraction": _normalized_value(table_extraction),
            "section_detector_backend": _normalized_value(section_detector_backend),
            "multi_recipe_splitter": _normalized_value(multi_recipe_splitter),
            "multi_recipe_trace": bool(multi_recipe_trace),
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
            "instruction_step_segmentation_policy": _normalized_value(
                instruction_step_segmentation_policy
            ),
            "instruction_step_segmenter": _normalized_value(
                instruction_step_segmenter
            ),
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
            "p6_emit_metadata_debug": bool(p6_emit_metadata_debug),
            "benchmark_sequence_matcher": str(benchmark_sequence_matcher or "dmp")
            .strip()
            .lower(),
            "recipe_scorer_backend": str(recipe_scorer_backend or "heuristic_v1").strip()
            or "heuristic_v1",
            "recipe_score_gold_min": float(recipe_score_gold_min),
            "recipe_score_silver_min": float(recipe_score_silver_min),
            "recipe_score_bronze_min": float(recipe_score_bronze_min),
            "recipe_score_min_ingredient_lines": int(recipe_score_min_ingredient_lines),
            "recipe_score_min_instruction_lines": int(recipe_score_min_instruction_lines),
            "llm_recipe_pipeline": _normalized_value(llm_recipe_pipeline),
            "llm_knowledge_pipeline": _normalized_value(llm_knowledge_pipeline),
            "llm_tags_pipeline": _normalized_value(llm_tags_pipeline),
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
            "codex_farm_pipeline_pass1": (
                str(codex_farm_pipeline_pass1).strip() or "recipe.chunking.v1"
            ),
            "codex_farm_pipeline_pass2": (
                str(codex_farm_pipeline_pass2).strip() or "recipe.schemaorg.v1"
            ),
            "codex_farm_pipeline_pass3": (
                str(codex_farm_pipeline_pass3).strip() or "recipe.final.v1"
            ),
            "codex_farm_pipeline_pass4_knowledge": (
                str(codex_farm_pipeline_pass4_knowledge).strip()
                or "recipe.knowledge.v1"
            ),
            "codex_farm_pipeline_pass5_tags": (
                str(codex_farm_pipeline_pass5_tags).strip() or "recipe.tags.v1"
            ),
            "codex_farm_context_blocks": int(codex_farm_context_blocks),
            "codex_farm_knowledge_context_blocks": int(codex_farm_knowledge_context_blocks),
            "tag_catalog_json": (
                str(tag_catalog_json).strip() or "data/tagging/tag_catalog.json"
            ),
            "codex_farm_failure_mode": _normalized_value(codex_farm_failure_mode),
            "effective_workers": resolved_effective_workers,
            "mapping_path": str(mapping_path) if mapping_path is not None else None,
            "overrides_path": str(overrides_path) if overrides_path is not None else None,
        }
    )
