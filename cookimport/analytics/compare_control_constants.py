from __future__ import annotations

import re


COMPARE_CONTROL_DEFAULT_OUTCOME_FIELD = "strict_accuracy"
ANALYSIS_FIELD_LABEL_OVERRIDES = {
    "source_file_basename": "Book",
    "run_config.single_book_split_cache.conversion_seconds": "Conversion seconds",
    "conversion_seconds_per_recipe": "Conversion seconds per recipe",
    "all_token_use_per_recipe": "Token use per recipe",
}
COMPARE_CONTROL_OUTCOME_PREFERRED = (
    "strict_accuracy",
    "macro_f1_excluding_other",
    "precision",
    "recall",
    "f1",
    "practical_f1",
    "supported_practical_f1",
    "conversion_seconds_per_recipe",
    "all_token_use_per_recipe",
)
ANALYSIS_FIELD_PREFERRED = (
    "source_label",
    "source_file_basename",
    "importer_name",
    "ai_model",
    "ai_effort",
    "ai_assistance_profile",
    "run_config.llm_recipe_pipeline",
    "run_config.epub_extractor",
    "run_config.epub_extractor_effective",
    "run_config.epub_unstructured_preprocess_mode",
    "run_config.epub_unstructured_skip_headers_footers",
    "run_config.codex_farm_reasoning_effort",
    "run_config.codex_farm_model",
)
PREVIOUS_RUNS_DEFAULT_COLUMNS = (
    "run_timestamp",
    "strict_accuracy",
    "macro_f1_excluding_other",
    "gold_total",
    "gold_matched",
    "recipes",
    "all_token_use",
    "source_label",
    "importer_name",
    "ai_model",
    "ai_effort",
    "ai_assistance_profile",
)
COMPARE_CONTROL_FIELD_SKIP = {
    "artifact_dir",
    "artifact_dir_basename",
    "run_dir",
    "report_path",
    "run_config_summary",
    "run_config_hash",
    "per_label_json",
    "per_label",
}
COMPARE_CONTROL_SECONDARY_METRIC_PREFERRED = (
    "benchmark_total_seconds",
    "benchmark_prediction_seconds",
    "benchmark_evaluation_seconds",
    "all_token_use",
    "tokens_total",
    "tokens_input",
    "tokens_output",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "benchmark_cost_usd",
    "run_cost_usd",
)
COMPARE_CONTROL_SECONDARY_FIELD_PATTERN = re.compile(
    r"(token|runtime|second|latency|cost|usd|price)", re.IGNORECASE
)
COMPARE_CONTROL_SECONDARY_MAX_FIELDS = 4
COMPARE_CONTROL_WARNING_ROW_COVERAGE_MIN = 0.6
COMPARE_CONTROL_WARNING_STRATA_COVERAGE_MIN = 0.6
COMPARE_CONTROL_WARNING_MIN_ROWS = 20
COMPARE_CONTROL_WARNING_MIN_STRATA = 3
COMPARE_CONTROL_VIEW_MODES = {"discover", "raw", "controlled"}
COMPARE_CONTROL_DISCOVERY_DEFAULT_MAX_CARDS = 10
COMPARE_CONTROL_DISCOVERY_MAX_CARDS = 40
COMPARE_CONTROL_DISCOVERY_PREFER_FIELD_BOOST = 1.25
COMPARE_CONTROL_DISCOVERY_DEMOTE_FACTOR = 0.2
INSIGHTS_COMPARE_FIELD_PREFERRED = (
    "ai_model",
    "ai_effort",
    "ai_assistance_profile",
    "run_config.llm_recipe_pipeline",
    "run_config.line_role_pipeline",
    "run_config.atomic_block_splitter",
    "run_config.epub_extractor",
    "importer_name",
    "source_label",
)
INSIGHTS_HOLD_FIELD_PREFERRED = (
    "source_label",
    "importer_name",
)
INSIGHTS_PROCESS_FIELDS = (
    "run_config.llm_recipe_pipeline",
    "run_config.line_role_pipeline",
    "run_config.atomic_block_splitter",
    "run_config.epub_extractor",
    "run_config.epub_unstructured_preprocess_mode",
    "run_config.codex_farm_reasoning_effort",
)
INSIGHTS_DISCOVERY_NOISE_PATTERN = re.compile(
    r"(path|hash|summary|manifest|report|artifact_dir|run_dir|json)",
    re.IGNORECASE,
)
COLUMN_FILTER_OPERATORS = {
    "contains",
    "not_contains",
    "eq",
    "neq",
    "starts_with",
    "ends_with",
    "gt",
    "gte",
    "lt",
    "lte",
    "regex",
    "is_empty",
    "not_empty",
}
UNARY_FILTER_OPERATORS = {"is_empty", "not_empty"}
