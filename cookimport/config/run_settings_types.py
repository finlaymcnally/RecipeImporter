from __future__ import annotations

from enum import Enum
from typing import Any

from cookimport.config.run_settings_contracts import RUN_SETTING_SURFACE_PUBLIC

_UI_REQUIRED_KEYS = ("ui_group", "ui_label", "ui_order")
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
    "epub_title_backtrack_limit",
    "epub_anchor_title_backtrack_limit",
    "epub_ingredient_run_window",
    "epub_ingredient_header_window",
    "epub_title_max_length",
    "pdf_column_gap_ratio",
    "codex_farm_failure_mode",
    "ocr_device",
    "ocr_batch_size",
    "workspace_completion_quiescence_seconds",
    "completed_termination_grace_seconds",
    "codex_exec_style",
    "knowledge_group_task_max_units",
    "knowledge_group_task_max_evidence_chars",
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

LINE_ROLE_PIPELINE_ROUTE_V2 = "codex-line-role-route-v2"
KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2 = "codex-knowledge-candidate-v2"
CODEX_EXEC_STYLE_TASKFILE_V1 = "taskfile-v1"
CODEX_EXEC_STYLE_STRUCTURED_RESUME_V1 = "structured-resume-v1"


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
    codex_line_role_route_v2 = LINE_ROLE_PIPELINE_ROUTE_V2


class LlmKnowledgePipeline(str, Enum):
    off = "off"
    codex_knowledge_candidate_v2 = KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2


class CodexExecStyle(str, Enum):
    taskfile_v1 = CODEX_EXEC_STYLE_TASKFILE_V1
    structured_resume_v1 = CODEX_EXEC_STYLE_STRUCTURED_RESUME_V1


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
        LINE_ROLE_PIPELINE_ROUTE_V2,
    }
    if normalized not in allowed:
        raise ValueError(
            "Invalid line_role_pipeline. Expected one of: "
            f"{LineRolePipeline.off.value}, {LINE_ROLE_PIPELINE_ROUTE_V2}."
        )
    return normalized


def normalize_llm_knowledge_pipeline_value(value: Any) -> str:
    normalized = str(getattr(value, "value", value) or "").strip().lower()
    normalized = normalized or LlmKnowledgePipeline.off.value
    allowed = {
        LlmKnowledgePipeline.off.value,
        KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
    }
    if normalized not in allowed:
        raise ValueError(
            "Invalid llm_knowledge_pipeline. Expected one of: "
            f"{LlmKnowledgePipeline.off.value}, {KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2}."
        )
    return normalized


def normalize_codex_exec_style_value(value: Any) -> str:
    normalized = str(getattr(value, "value", value) or "").strip().lower().replace("_", "-")
    if normalized in {"", "default", "taskfile", "taskfile-v1"}:
        return CODEX_EXEC_STYLE_TASKFILE_V1
    if normalized in {"structured", "structured-resume", "structured-resume-v1"}:
        return CODEX_EXEC_STYLE_STRUCTURED_RESUME_V1
    raise ValueError(
        "Invalid codex_exec_style. Expected one of: "
        f"{CODEX_EXEC_STYLE_TASKFILE_V1}, {CODEX_EXEC_STYLE_STRUCTURED_RESUME_V1}."
    )


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
