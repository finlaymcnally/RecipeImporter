from __future__ import annotations

import cProfile
import csv
import datetime as dt
import functools
import hashlib
import importlib
import importlib.util
import io
import json
import logging
import math
import multiprocessing
import os
import pickle
import pstats
import queue
import re
import shutil
import shlex
import subprocess
import sys
import threading
import time
import textwrap
import zipfile
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from itertools import product
from pathlib import Path
from typing import Iterable, Iterator, Dict, Any, Annotated, Callable, Mapping, TypeVar, cast

import questionary
import typer
from typer.models import OptionInfo
from prompt_toolkit.key_binding.key_bindings import KeyBindings, merge_key_bindings
from prompt_toolkit.keys import Keys
from questionary.prompts.common import Choice as QuestionaryChoice, Separator as QuestionarySeparator
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from cookimport.cli_ui.run_settings_flow import (
    build_codex_farm_reasoning_effort_choices,
    choose_codex_ai_settings,
    choose_interactive_codex_surfaces,
    choose_run_settings,
    supported_codex_farm_efforts_by_model,
)
from cookimport.config.codex_decision import (
    apply_benchmark_baseline_contract,
    apply_benchmark_codex_contract_from_baseline,
    apply_bucket1_fixed_behavior_metadata,
    apply_codex_decision_metadata,
    apply_codex_execution_policy_metadata,
    bucket1_fixed_behavior,
    codex_surfaces_enabled,
    format_codex_command_summary,
    format_codex_execution_policy_summary,
    resolve_codex_command_decision,
    resolve_codex_execution_policy,
)
from cookimport.config.last_run_store import (
    save_qualitysuite_winner_run_settings,
)
from cookimport.config.run_settings_contracts import (
    RUN_SETTING_CONTRACT_FULL,
    project_run_config_payload,
    summarize_run_config_payload,
)
from cookimport.config.run_settings import (
    KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2,
    LINE_ROLE_PIPELINE_ROUTE_V2,
    RECIPE_CODEX_FARM_ALLOWED_PIPELINES,
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
    RunSettings,
    build_run_settings,
    compute_effective_workers,
    normalize_line_role_pipeline_value,
    normalize_llm_knowledge_pipeline_value,
    normalize_llm_recipe_pipeline_value,
)
from cookimport.config.run_settings_adapters import (
    build_benchmark_call_kwargs_from_run_settings,
    build_stage_call_kwargs_from_run_settings,
)
from cookimport.config.prediction_identity import (
    build_all_method_prediction_identity_payload,
)
from cookimport.epub_extractor_names import (
    EPUB_EXTRACTOR_CANONICAL_SET,
    EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV,
    epub_extractor_enabled_choices,
    epub_extractor_choices_for_help,
    is_policy_locked_epub_extractor_name,
    markdown_epub_extractors_enabled,
    normalize_epub_extractor_name,
)
from cookimport.core.mapping_io import load_mapping_config, save_mapping_config
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.progress_messages import (
    format_phase_counter,
    format_task_counter,
    parse_stage_progress,
    parse_worker_activity,
)
from cookimport.core.progress_dashboard import (
    ProgressCallbackAdapter,
    ProgressDashboardCore,
    ProgressQueueRow,
)
from cookimport.core.executor_fallback import (
    create_sync_manager,
    resolve_process_thread_executor,
    shutdown_executor,
)
from cookimport.core.overrides_io import load_parsing_overrides
from cookimport.core.reporting import compute_file_hash, enrich_report_with_stats
from cookimport.core.slug import slugify_name
from cookimport.core.source_model import (
    normalize_source_blocks,
    offset_source_blocks,
    offset_source_support,
)
from cookimport.core.timing import TimingStats, measure
from cookimport.bench.eval_canonical_text import (
    evaluate_canonical_text,
    format_canonical_eval_report_md,
)
from cookimport.bench.eval_stage_blocks import (
    evaluate_stage_blocks,
    format_stage_block_eval_report_md,
)
from cookimport.bench.sequence_matcher_select import (
    SEQUENCE_MATCHER_ENV,
    reset_sequence_matcher_selection_cache,
    supported_sequence_matcher_modes,
)
from cookimport.bench.prediction_records import (
    PredictionRecord,
    make_prediction_record,
    read_prediction_records,
    write_prediction_records,
)
from cookimport.bench.cutdown_export import (
    build_line_role_joined_line_rows,
    write_line_role_stable_samples,
    write_prompt_eval_alignment_doc,
)
from cookimport.bench.oracle_upload import (
    OracleBackgroundUploadLaunch,
    OracleBenchmarkBundleTarget,
    OracleUploadResult,
    resolve_oracle_benchmark_bundle,
    resolve_oracle_benchmark_review_profiles,
    run_oracle_benchmark_upload,
    start_oracle_benchmark_upload_background,
)
from cookimport.bench.oracle_followup import (
    ORACLE_AUTO_FOLLOWUP_LOG_NAME,
    ORACLE_AUTO_FOLLOWUP_STATUS_NAME,
    OracleFollowupWorkspace,
    run_oracle_benchmark_followup,
    run_oracle_benchmark_followup_background_worker,
)
from cookimport.bench.pairwise_flips import build_line_role_flips_vs_baseline
from cookimport.bench.slice_metrics import (
    build_line_role_routing_summary,
    build_line_role_slice_metrics,
)
from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.export import run_labelstudio_export
from cookimport.labelstudio.ingest import (
    generate_pred_run_artifacts,
    run_labelstudio_import,
)
from cookimport.labelstudio.canonical_gold import ensure_canonical_gold_artifacts
from cookimport.labelstudio.eval_freeform import (
    attach_recipe_count_diagnostics,
    evaluate_predicted_vs_freeform,
    format_freeform_eval_report_md,
    load_gold_freeform_ranges,
    load_predicted_labeled_ranges,
)
from cookimport.labelstudio.prelabel import (
    CODEX_REASONING_EFFORT_VALUES,
    PRELABEL_GRANULARITY_BLOCK,
    PRELABEL_GRANULARITY_SPAN,
    codex_account_summary,
    codex_reasoning_effort_from_cmd,
    default_codex_cmd,
    default_codex_model,
    default_codex_reasoning_effort,
    default_codex_reasoning_effort_for_model,
    list_codex_models,
    normalize_codex_reasoning_effort,
    normalize_prelabel_granularity,
)
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_nonrecipe_knowledge_review
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.llm.prompt_budget import (
    build_prediction_run_prompt_budget_summary,
    write_prediction_run_prompt_budget_summary,
)
from cookimport.llm import prompt_artifacts as llm_prompt_artifacts
from cookimport.parsing.schemaorg_ingest import collect_schemaorg_recipe_objects
from cookimport.plugins import registry
from cookimport.plugins import (
    excel,
    text,
    epub,
    pdf,
    recipesage,
    paprika,
    webschema,
)  # noqa: F401
from cookimport.runs import (
    KNOWLEDGE_STAGE_STATUS_FILE_NAME,
    RECIPE_MANIFEST_FILE_NAME,
    RunManifest,
    RunSource,
    build_stage_observability_report,
    load_stage_observability_report,
    stage_artifact_stem,
    summarize_knowledge_stage_artifacts,
    write_eval_run_manifest,
    write_run_manifest,
    write_stage_observability_report,
)
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks
from cookimport.parsing.tables import ExtractedTable, extract_and_annotate_tables
from cookimport.staging.import_session import execute_stage_import_session_from_result
from cookimport.staging.job_planning import (
    JobSpec,
    plan_source_jobs,
)
from cookimport.staging.writer import (
    NONRECIPE_AUTHORITY_FILE_NAME,
    NONRECIPE_CANDIDATE_STATUS_FILE_NAME,
    NONRECIPE_EXCLUSIONS_FILE_NAME,
    NONRECIPE_SEED_ROUTING_FILE_NAME,
    OutputStats,
    write_chunk_outputs,
    write_draft_outputs,
    write_intermediate_outputs,
    write_report,
    write_section_outputs,
    write_stage_block_predictions,
    write_table_outputs,
)

from cookimport.paths import (
    GOLDEN_BENCHMARK_ROOT,
    GOLDEN_PULLED_FROM_LABELSTUDIO_ROOT,
    GOLDEN_ROOT,
    GOLDEN_SENT_TO_LABELSTUDIO_ROOT,
    HISTORY_ROOT,
    INPUT_ROOT,
    OUTPUT_ROOT,
    REPO_ROOT,
    history_csv_for_output,
    history_root_for_output,
)
console = Console()
logger = logging.getLogger(__name__)


DEFAULT_INPUT = INPUT_ROOT
DEFAULT_OUTPUT = OUTPUT_ROOT
DEFAULT_INTERACTIVE_OUTPUT = DEFAULT_OUTPUT
DEFAULT_GOLDEN = GOLDEN_ROOT
DEFAULT_GOLDEN_SENT_TO_LABELSTUDIO = GOLDEN_SENT_TO_LABELSTUDIO_ROOT
DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO = GOLDEN_PULLED_FROM_LABELSTUDIO_ROOT
DEFAULT_GOLDEN_BENCHMARK = GOLDEN_BENCHMARK_ROOT
DEFAULT_LABELSTUDIO_BENCHMARK_COMPARISONS = DEFAULT_GOLDEN_BENCHMARK / "comparisons"
DEFAULT_HISTORY = HISTORY_ROOT
DEFAULT_BENCH_SPEED_ROOT = DEFAULT_GOLDEN / "bench" / "speed"
DEFAULT_BENCH_SPEED_SUITES = DEFAULT_BENCH_SPEED_ROOT / "suites"
DEFAULT_BENCH_SPEED_RUNS = DEFAULT_BENCH_SPEED_ROOT / "runs"
DEFAULT_BENCH_SPEED_COMPARISONS = DEFAULT_BENCH_SPEED_ROOT / "comparisons"
DEFAULT_BENCH_QUALITY_ROOT = DEFAULT_GOLDEN / "bench" / "quality"
DEFAULT_BENCH_QUALITY_SUITES = DEFAULT_BENCH_QUALITY_ROOT / "suites"
DEFAULT_BENCH_QUALITY_RUNS = DEFAULT_BENCH_QUALITY_ROOT / "runs"
DEFAULT_BENCH_QUALITY_COMPARISONS = DEFAULT_BENCH_QUALITY_ROOT / "comparisons"
DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_SERIES = (
    DEFAULT_BENCH_QUALITY_ROOT / "lightweight_series"
)
DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_PROFILE = (
    DEFAULT_BENCH_QUALITY_ROOT
    / "lightweight_profiles"
    / "2026-03-02_00.36.30_qualitysuite-lightweight-main-effects-qualityfirst-pruned-v1.json"
)
DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_EXPERIMENTS = (
    DEFAULT_BENCH_QUALITY_ROOT
    / "experiments"
    / "2026-03-02_00.36.30_qualitysuite-top-tier-tournament-full-candidates-qualityfirst-pruned.json"
)
DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_THRESHOLDS = (
    DEFAULT_BENCH_QUALITY_ROOT
    / "thresholds"
    / "2026-02-28_16.24.30_qualitysuite-top-tier-gates-fast-nosweeps.json"
)
DEFAULT_CONFIG_PATH = REPO_ROOT / "cookimport.json"
BACK_ACTION = "__back__"
DEFAULT_PRELABEL_TIMEOUT_SECONDS = 600
KNOWN_LABELSTUDIO_TASK_SCOPES = {"pipeline", "canonical-blocks", "freeform-spans"}
SUPPORTED_LABELSTUDIO_TASK_SCOPES = {"freeform-spans"}
BENCH_CODEX_FARM_CONFIRMATION_TOKEN = "I_HAVE_EXPLICIT_USER_CONFIRMATION"
QUALITY_RUN_CODEX_FARM_CONFIRMATION_TOKEN = BENCH_CODEX_FARM_CONFIRMATION_TOKEN
SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN = BENCH_CODEX_FARM_CONFIRMATION_TOKEN
QUALITYSUITE_AGENT_BRIDGE_DIR_NAME = "agent_compare_control"
QUALITYSUITE_AGENT_BRIDGE_SCHEMA_VERSION = "qualitysuite_compare_control_bridge.v1"
QUALITYSUITE_AGENT_BRIDGE_OUTCOME_FIELDS: tuple[str, ...] = (
    "strict_accuracy",
    "macro_f1_excluding_other",
)
SINGLE_BOOK_COMPARISON_SCHEMA_VERSION = "codex_vs_vanilla_comparison.v2"
SINGLE_BOOK_COMPARISON_METRICS: tuple[tuple[str, str], ...] = (
    ("strict_accuracy", "strict_accuracy"),
    ("macro_f1_excluding_other", "macro_f1_excluding_other"),
)
SINGLE_BOOK_PER_LABEL_BREAKDOWN_SCHEMA_VERSION = "single_book_per_label_breakdown.v1"
SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION = "single_book_split_cache.v1"
SINGLE_BOOK_SPLIT_CACHE_KEY_SCHEMA_VERSION = "single_book_split_cache_key.v1"
SINGLE_BOOK_SPLIT_CACHE_ROOT_ENV = "COOKIMPORT_SINGLE_BOOK_SPLIT_CACHE_ROOT"
SINGLE_BOOK_SPLIT_CACHE_WAIT_SECONDS = 120.0
SINGLE_BOOK_SPLIT_CACHE_POLL_SECONDS = 0.25
SINGLE_BOOK_SPLIT_CACHE_LOCK_SUFFIX = ".lock"
BENCHMARK_UPLOAD_BUNDLE_DIR_NAME = "upload_bundle_v1"
BENCHMARK_SINGLE_BOOK_UPLOAD_BUNDLE_TARGET_BYTES = 30 * 1024 * 1024
BENCHMARK_GROUP_UPLOAD_BUNDLE_TARGET_BYTES = 30 * 1024 * 1024
BENCHMARK_UPLOAD_BUNDLE_REVIEW_DIR_NAMES = (
    "quality",
    "token",
)
BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES = (
    "overview.md",
    "index.json",
    "payload.json",
)
LABELSTUDIO_BENCHMARK_COMPARE_SCHEMA_VERSION = "labelstudio_benchmark_compare.v1"
CODEX_FARM_RECIPE_MODE_EXTRACT = "extract"
CODEX_FARM_RECIPE_MODE_BENCHMARK = "benchmark"
CODEX_FARM_BENCHMARK_MODE_ENV = "COOKIMPORT_CODEX_FARM_RECIPE_MODE"
BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY = "thefoodlabcutdown"
BENCHMARK_COMPARE_SEA_SOURCE_KEY = "seaandsmokecutdown"
BENCHMARK_COMPARE_INGREDIENT_LABEL = "INGREDIENT_LINE"
BENCHMARK_COMPARE_VARIANT_LABEL = "RECIPE_VARIANT"
LINE_ROLE_REGRESSION_GATES_SCHEMA_VERSION = "line_role_regression_gates.v1"
LINE_ROLE_GATED_METRIC_DELTA_MIN = 0.05
LINE_ROLE_GATED_INGREDIENT_YIELD_DROP_MIN = 0.40
LINE_ROLE_GATED_OTHER_KNOWLEDGE_DROP_MIN = 0.30
LINE_ROLE_GATED_MIN_RECIPE_NOTES_RECALL = 0.40
LINE_ROLE_GATED_MIN_RECIPE_VARIANT_RECALL = 0.40
LINE_ROLE_GATED_MIN_INGREDIENT_RECALL = 0.35
QUALITY_LIGHTWEIGHT_SERIES_DISABLED_MESSAGE = (
    "bench quality-lightweight-series is disabled. "
    "Tournament/lightweight-series workflows were retired due to extreme "
    "runtime and disk usage. Use `bench quality-run` + `bench quality-compare` "
    "for quality iteration."
)
ALL_METHOD_EPUB_EXTRACTORS_DEFAULT = (
    "unstructured",
    "beautifulsoup",
)
ALL_METHOD_EPUB_EXTRACTORS_MARKDOWN_OPTIONAL = (
    "markdown",
    "markitdown",
)
ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV = (
    "COOKIMPORT_ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS"
)
ALL_METHOD_UNSTRUCTURED_HTML_PARSER_VERSIONS = ("v1", "v2")
ALL_METHOD_UNSTRUCTURED_SKIP_HEADERS_FOOTERS = (False, True)
ALL_METHOD_UNSTRUCTURED_PREPROCESS_MODES = ("none", "br_split_v1")
ALL_METHOD_WEBSCHEMA_POLICIES = ("prefer_schema", "schema_only", "heuristic_only")
ALL_METHOD_MAX_INFLIGHT_DEFAULT = 4
ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT = 4
ALL_METHOD_MAX_EVAL_TAIL_DEFAULT = 4
ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT = 600
ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT = 1
ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT = 4
ALL_METHOD_SCHEDULER_SCOPE_GLOBAL = "global"
ALL_METHOD_SCHEDULER_SCOPE_DEFAULT = ALL_METHOD_SCHEDULER_SCOPE_GLOBAL
ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY = "discovery"
ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR = "tail_pair"
ALL_METHOD_SOURCE_SCHEDULING_DEFAULT = ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR
ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT = 1200.0
ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT = 3
ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT = 6
ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO = 0.35
ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES = 768 * 1024 * 1024
ALL_METHOD_MAX_INFLIGHT_SETTING_KEY = "all_method_max_inflight_pipelines"
ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY = "all_method_max_split_phase_slots"
ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY = "all_method_max_eval_tail_pipelines"
ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY = "all_method_config_timeout_seconds"
ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY = "all_method_retry_failed_configs"
ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY = "all_method_max_parallel_sources"
ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY = "all_method_scheduler_scope"
ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY = "all_method_source_scheduling"
ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY = (
    "all_method_source_shard_threshold_seconds"
)
ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY = "all_method_source_shard_max_parts"
ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY = "all_method_source_shard_min_variants"
ALL_METHOD_WING_BACKLOG_SETTING_KEY = "all_method_wing_backlog_target"
ALL_METHOD_SMART_SCHEDULER_SETTING_KEY = "all_method_smart_scheduler"
ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV = "COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT"
ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV = (
    "COOKIMPORT_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT"
)
ALL_METHOD_EVAL_SIGNATURE_SCHEMA_VERSION = "all_method_eval_signature.v1"
ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION = (
    "all_method_eval_signature_result.v1"
)
ALL_METHOD_SCHEDULER_POLL_SECONDS = 0.15
ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS = 1.0
ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME = "scheduler_timeseries.jsonl"
ALL_METHOD_ADAPTIVE_CPU_HOT_PCT = 95.0
ALL_METHOD_ADAPTIVE_SATURATION_BACKLOG_MULTIPLIER = 2
ALL_METHOD_MATCHER_GUARDRAIL_EVAL_RATIO_WARN = 0.10
ALL_METHOD_MATCHER_GUARDRAIL_CACHE_HIT_WARN = 0.50
ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION = "all_method_prediction_reuse.v2"
ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION = "all_method_split_convert_input.v1"
ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION = (
    "all_method_prediction_reuse_cache_entry.v1"
)
ALL_METHOD_PREDICTION_REUSE_WAIT_SECONDS = 120.0
ALL_METHOD_PREDICTION_REUSE_POLL_SECONDS = 0.25
ALL_METHOD_PREDICTION_REUSE_LOCK_SUFFIX = ".lock"
ALL_METHOD_SPLIT_CONVERT_INPUT_FIELDS = (
    "bucket1_fixed_behavior_version",
    "epub_extractor",
    "epub_unstructured_html_parser_version",
    "epub_unstructured_skip_headers_footers",
    "epub_unstructured_preprocess_mode",
    "ocr_device",
    "pdf_ocr_policy",
    "ocr_batch_size",
    "pdf_column_gap_ratio",
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
    "llm_recipe_pipeline",
    "codex_farm_context_blocks",
    "codex_farm_failure_mode",
)
SINGLE_BOOK_SPLIT_CONVERT_INPUT_EXCLUDED_FIELDS = (
    "llm_recipe_pipeline",
    "codex_farm_cmd",
    "codex_farm_context_blocks",
    "codex_farm_failure_mode",
)
SINGLE_BOOK_SPLIT_CONVERT_INPUT_FIELDS = tuple(
    field_name
    for field_name in ALL_METHOD_SPLIT_CONVERT_INPUT_FIELDS
    if field_name not in SINGLE_BOOK_SPLIT_CONVERT_INPUT_EXCLUDED_FIELDS
)
PROCESSING_TIMESERIES_HEARTBEAT_SECONDS = 1.0
PROCESSING_TIMESERIES_FILENAME = "processing_timeseries.jsonl"
BENCHMARK_EVAL_MODE_STAGE_BLOCKS = "stage-blocks"
BENCHMARK_EVAL_MODE_CANONICAL_TEXT = "canonical-text"
COOKIMPORT_BENCH_WRITE_MARKDOWN_ENV = "COOKIMPORT_BENCH_WRITE_MARKDOWN"
COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS_ENV = (
    "COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS"
)
COOKIMPORT_BENCH_SINGLE_BOOK_WRITE_STARTER_PACK_ENV = (
    "COOKIMPORT_BENCH_SINGLE_BOOK_WRITE_STARTER_PACK"
)
BENCHMARK_SEQUENCE_MATCHER_DISPLAY_NAMES: dict[str, str] = {
    "dmp": "DMP",
}
OUTPUT_STATS_CATEGORY_RAW = "rawArtifacts"
BENCHMARK_EVAL_PROFILE_MIN_SECONDS_ENV = "COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS"
BENCHMARK_EVAL_PROFILE_TOP_N_ENV = "COOKIMPORT_BENCHMARK_EVAL_PROFILE_TOP_N"
_MENU_SHORTCUT_KEYS = (
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "s",
    "t",
    "u",
    "v",
    "w",
    "x",
    "y",
    "z",
)

_STATUS_ELAPSED_THRESHOLD_SECONDS = 10
_STATUS_TICK_SECONDS = 1.0
_STATUS_ETA_RECENT_STEP_WEIGHTS: tuple[float, ...] = (0.30, 0.20, 0.20, 0.20, 0.10)
_STATUS_ETA_RECENT_INSTANT_BLEND = 0.50
_STATUS_RATE_RECENT_WINDOW = max(12, len(_STATUS_ETA_RECENT_STEP_WEIGHTS))
_STATUS_ETA_BOOTSTRAP_MIN_SECONDS = 1.0
_STATUS_ALL_METHOD_STALL_MIN_SECONDS = 1.0
_STATUS_ALL_METHOD_STALL_MULTIPLIER = 2.0
_STATUS_PLAIN_PROGRESS_ENV = "COOKIMPORT_PLAIN_PROGRESS"
_STATUS_LIVE_SLOTS_ENV = "COOKIMPORT_LIVE_STATUS_SLOTS"
_STATUS_ENV_TRUE_VALUES = {"1", "true", "yes", "on"}
_STATUS_ENV_FALSE_VALUES = {"0", "false", "no", "off"}
_STATUS_AGENT_HINT_ENV_KEYS = (
    "CODEX_CI",
    "CODEX_THREAD_ID",
    "CLAUDE_CODE_SSE_PORT",
)
_STATUS_COUNTER_PATTERN = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
_STATUS_ACTIVE_TASKS_RE = re.compile(
    r"\bactive\s*\[([^]]*)\]",
    re.IGNORECASE,
)
_STATUS_CODEX_FARM_PIPELINE_PREFIX_RE = re.compile(
    r"^codex-farm\s+(?P<pipeline>\S+)",
    re.IGNORECASE,
)
_STATUS_RUNNING_WORKERS_RE = re.compile(
    r"\brunning\s+(\d+)\b",
    re.IGNORECASE,
)
_StatusReturn = TypeVar("_StatusReturn")
_DASHBOARD_REFRESH_SENTINEL_DIRNAME = "__dashboard_refresh__"

_BENCHMARK_PROGRESS_CALLBACK: ContextVar[Callable[[str], None] | None] = ContextVar(
    "_BENCHMARK_PROGRESS_CALLBACK",
    default=None,
)
_BENCHMARK_SUPPRESS_SUMMARY: ContextVar[bool] = ContextVar(
    "_BENCHMARK_SUPPRESS_SUMMARY",
    default=False,
)
_BENCHMARK_SUPPRESS_SPINNER: ContextVar[bool] = ContextVar(
    "_BENCHMARK_SUPPRESS_SPINNER",
    default=False,
)
_BENCHMARK_SUPPRESS_DASHBOARD_REFRESH: ContextVar[bool] = ContextVar(
    "_BENCHMARK_SUPPRESS_DASHBOARD_REFRESH",
    default=False,
)
_BENCHMARK_SUPPRESS_OUTPUT_PRUNE: ContextVar[bool] = ContextVar(
    "_BENCHMARK_SUPPRESS_OUTPUT_PRUNE",
    default=False,
)
_BENCHMARK_LIVE_STATUS_SLOTS: ContextVar[int | None] = ContextVar(
    "_BENCHMARK_LIVE_STATUS_SLOTS",
    default=None,
)
_INTERACTIVE_CLI_ACTIVE: ContextVar[bool] = ContextVar(
    "_INTERACTIVE_CLI_ACTIVE",
    default=False,
)
_BENCHMARK_SPLIT_PHASE_SLOTS: ContextVar[int | None] = ContextVar(
    "_BENCHMARK_SPLIT_PHASE_SLOTS",
    default=None,
)
_BENCHMARK_SPLIT_PHASE_GATE_DIR: ContextVar[str | None] = ContextVar(
    "_BENCHMARK_SPLIT_PHASE_GATE_DIR",
    default=None,
)
_BENCHMARK_SPLIT_PHASE_STATUS_LABEL: ContextVar[str | None] = ContextVar(
    "_BENCHMARK_SPLIT_PHASE_STATUS_LABEL",
    default=None,
)
_BENCHMARK_SCHEDULER_EVENT_CALLBACK: ContextVar[
    Callable[[dict[str, Any]], None] | None
] = ContextVar(
    "_BENCHMARK_SCHEDULER_EVENT_CALLBACK",
    default=None,
)
_LAST_FAIL_MESSAGE: ContextVar[str | None] = ContextVar(
    "_LAST_FAIL_MESSAGE",
    default=None,
)
_LIVE_STATUS_SLOT_LOCK = threading.Lock()
_LIVE_STATUS_SLOT_ACTIVE = 0
_LIVE_STATUS_SLOT_MAX_DEFAULT = 1
_LIVE_STATUS_SLOT_MAX_HARD_CAP = 8


def _golden_sent_to_labelstudio_root() -> Path:
    return DEFAULT_GOLDEN / "sent-to-labelstudio"


def _golden_pulled_from_labelstudio_root() -> Path:
    return DEFAULT_GOLDEN / "pulled-from-labelstudio"


def _golden_benchmark_root() -> Path:
    return DEFAULT_GOLDEN / "benchmark-vs-golden"


def _resolve_all_method_canonical_alignment_cache_root(
    *,
    root_output_dir: Path,
) -> Path:
    env_override = str(
        os.getenv(ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV, "") or ""
    ).strip()
    if env_override:
        return Path(env_override).expanduser()
    resolved_root = root_output_dir.expanduser()
    if resolved_root.name == "all-method-benchmark":
        return resolved_root.parent.parent / ".cache" / "canonical_alignment"
    if resolved_root.parent.name == "all-method-benchmark":
        return resolved_root.parent.parent.parent / ".cache" / "canonical_alignment"
    return resolved_root.parent / ".cache" / "canonical_alignment"


def _infer_output_root_from_history_csv(csv_path: Path) -> Path | None:
    if csv_path.name != "performance_history.csv":
        return None
    if csv_path.parent.name != ".history":
        return None
    try:
        if csv_path.parent.resolve(strict=False) == HISTORY_ROOT.resolve(strict=False):
            return Path(DEFAULT_OUTPUT)
    except OSError:
        pass
    return csv_path.parent.parent / _DASHBOARD_REFRESH_SENTINEL_DIRNAME


from .dashboard import _refresh_dashboard_after_history_write
from .interactive import (
    _ask_with_escape_back,
    _menu_option_count,
    _menu_select,
    _menu_shortcut_bindings,
    _prompt_confirm,
    _prompt_freeform_segment_settings,
    _prompt_password,
    _prompt_text,
)
from .settings import (
    _all_method_default_parallel_sources_from_cpu,
    _coerce_bool_setting,
    _coerce_configured_epub_extractor,
    _coerce_float_between,
    _coerce_non_negative_int,
    _coerce_positive_float,
    _coerce_positive_int,
    _display_optional_setting,
    _is_labelstudio_credential_error,
    _list_importable_files,
    _load_settings,
    _normalize_all_method_scheduler_scope,
    _normalize_all_method_source_scheduling,
    _preflight_labelstudio_credentials,
    _resolve_interactive_labelstudio_settings,
    _resolve_non_negative_int_setting,
    _resolve_positive_float_setting,
    _resolve_positive_int_setting,
    _run_settings_payload_from_settings,
    _save_settings,
)


def _fail(message: str) -> None:
    _LAST_FAIL_MESSAGE.set(message)
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(1)


def _format_token_usage_line(prefix: str, usage: dict[str, Any]) -> str:
    return (
        f"{prefix}: "
        f"input={usage.get('input_tokens', 0)} "
        f"cached_input={usage.get('cached_input_tokens', 0)} "
        f"output={usage.get('output_tokens', 0)} "
        f"reasoning={usage.get('reasoning_tokens', 0)} "
        f"calls_with_usage={usage.get('calls_with_usage', 0)}"
    )


def _print_token_usage_summary(
    *,
    prefix: str,
    usage: Any,
    enabled: bool,
) -> None:
    if not enabled:
        return
    if isinstance(usage, dict):
        typer.secho(
            _format_token_usage_line(prefix, usage),
            fg=typer.colors.CYAN,
        )
        return
    typer.secho(
        f"{prefix}: unavailable (Codex did not emit usage totals)",
        fg=typer.colors.YELLOW,
    )


def _coerce_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _print_prelabel_completion_summary(
    *,
    prelabel_summary: Any,
    report_path: Any,
    inline_annotation_fallback: bool = False,
) -> None:
    usage_payload: Any = None
    usage_enabled = True
    failure_count = 0
    success_count = 0
    task_count = 0
    allow_partial = False
    errors_path: str | None = None
    if isinstance(prelabel_summary, dict):
        command_label = prelabel_summary.get("codex_cmd")
        if command_label:
            typer.secho(f"Prelabel command: {command_label}", fg=typer.colors.CYAN)
        account_label = prelabel_summary.get("codex_account")
        if account_label:
            typer.secho(f"Prelabel account: {account_label}", fg=typer.colors.CYAN)
        model_label = prelabel_summary.get("codex_model")
        if model_label:
            typer.secho(f"Prelabel model: {model_label}", fg=typer.colors.CYAN)
        reasoning_label = prelabel_summary.get("codex_reasoning_effort")
        if reasoning_label:
            typer.secho(
                f"Prelabel thinking effort: {reasoning_label}",
                fg=typer.colors.CYAN,
            )
        granularity_label = prelabel_summary.get("granularity")
        if granularity_label:
            typer.secho(
                f"Prelabel style: {granularity_label}",
                fg=typer.colors.CYAN,
            )
        workers_label = prelabel_summary.get("workers")
        if workers_label:
            typer.secho(
                f"Prelabel workers: {workers_label}",
                fg=typer.colors.CYAN,
            )
        usage_payload = prelabel_summary.get("token_usage")
        usage_enabled = bool(
            prelabel_summary.get(
                "token_usage_enabled",
                True,
            )
        )
        failure_count = _coerce_non_negative_int(prelabel_summary.get("failure_count"))
        success_count = _coerce_non_negative_int(prelabel_summary.get("success_count"))
        task_count = _coerce_non_negative_int(prelabel_summary.get("task_count"))
        allow_partial = bool(prelabel_summary.get("allow_partial"))
        raw_errors_path = prelabel_summary.get("errors_path")
        if isinstance(raw_errors_path, str) and raw_errors_path.strip():
            errors_path = raw_errors_path.strip()
    _print_token_usage_summary(
        prefix="Prelabel token usage",
        usage=usage_payload,
        enabled=usage_enabled,
    )
    if report_path:
        typer.secho(
            f"Prelabel report: {report_path}",
            fg=typer.colors.CYAN,
        )
    if failure_count > 0:
        total_count = task_count or (success_count + failure_count)
        if total_count > 0:
            typer.secho(
                (
                    "PRELABEL ERRORS: "
                    f"{failure_count}/{total_count} tasks failed "
                    f"({success_count} succeeded)."
                ),
                fg=typer.colors.RED,
                bold=True,
            )
        else:
            typer.secho(
                f"PRELABEL ERRORS: {failure_count} task(s) failed.",
                fg=typer.colors.RED,
                bold=True,
            )
        if allow_partial:
            typer.secho(
                "Upload continued because allow-partial mode is enabled.",
                fg=typer.colors.YELLOW,
            )
            typer.secho(
                "For fail-fast behavior, use --no-prelabel-allow-partial.",
                fg=typer.colors.YELLOW,
            )
        if errors_path:
            typer.secho(f"Prelabel errors: {errors_path}", fg=typer.colors.RED)
    if inline_annotation_fallback:
        typer.secho(
            "Inline annotation upload fallback was used "
            "(uploaded tasks first, then created annotations).",
            fg=typer.colors.YELLOW,
        )


def _unwrap_typer_option_default(value: Any) -> Any:
    if isinstance(value, OptionInfo):
        return value.default
    return value


def _normalize_epub_extractor(value: str) -> str:
    normalized = normalize_epub_extractor_name(value)
    if normalized not in EPUB_EXTRACTOR_CANONICAL_SET:
        _fail(
            f"Invalid EPUB extractor: {value!r}. "
            f"Expected one of: {epub_extractor_choices_for_help()}."
        )
    if is_policy_locked_epub_extractor_name(normalized):
        _fail(
            f"EPUB extractor {normalized!r} is policy-locked off for now "
            f"(set {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 to temporarily re-enable)."
        )
    return normalized


def _normalize_unstructured_html_parser_version(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"v1", "v2"}:
        _fail(
            f"Invalid EPUB Unstructured HTML parser version: {value!r}. "
            "Expected one of: v1, v2."
        )
    return normalized


def _normalize_unstructured_preprocess_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"none", "br_split_v1"}:
        _fail(
            f"Invalid EPUB Unstructured preprocess mode: {value!r}. "
            "Expected one of: none, br_split_v1."
        )
    return normalized


def _normalize_ocr_device(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"auto", "cpu", "cuda", "mps"}:
        _fail(
            f"Invalid OCR device: {value!r}. "
            "Expected one of: auto, cpu, cuda, mps."
        )
    return normalized


def _normalize_pdf_ocr_policy(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"off", "auto", "always"}:
        return normalized
    _fail(
        f"Invalid PDF OCR policy: {value!r}. "
        "Expected one of: off, auto, always."
    )
    return "auto"


def _normalize_pdf_column_gap_ratio(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        _fail(
            f"Invalid PDF column gap ratio: {value!r}. Expected a numeric value."
        )
        return 0.12
    if numeric < 0.01 or numeric > 0.95:
        _fail(
            "Invalid PDF column gap ratio. Expected a value between 0.01 and 0.95."
        )
    return numeric

def _normalize_section_detector_backend(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized == "shared_v1":
        return normalized
    _fail(
        f"Invalid section detector backend: {value!r}. "
        "Expected: shared_v1."
    )
    return "shared_v1"


def _normalize_multi_recipe_splitter(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"off", "rules_v1"}:
        return normalized
    _fail(
        f"Invalid multi-recipe splitter backend: {value!r}. "
        "Expected one of: off, rules_v1."
    )
    return "rules_v1"


def _normalize_instruction_step_segmentation_policy(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"off", "auto", "always"}:
        return normalized
    _fail(
        f"Invalid instruction step segmentation policy: {value!r}. "
        "Expected one of: off, auto, always."
    )
    return "auto"


def _normalize_instruction_step_segmenter(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"heuristic_v1", "pysbd_v1"}:
        return normalized
    _fail(
        f"Invalid instruction step segmenter: {value!r}. "
        "Expected one of: heuristic_v1, pysbd_v1."
    )
    return "heuristic_v1"


def _normalize_web_schema_extractor(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    allowed = {
        "builtin_jsonld",
        "extruct",
        "scrape_schema_recipe",
        "recipe_scrapers",
        "ensemble_v1",
    }
    if normalized in allowed:
        return normalized
    _fail(
        f"Invalid web schema extractor: {value!r}. "
        "Expected one of: builtin_jsonld, extruct, scrape_schema_recipe, recipe_scrapers, ensemble_v1."
    )
    return "builtin_jsonld"


def _normalize_web_schema_normalizer(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"simple", "pyld"}:
        return normalized
    _fail(
        f"Invalid web schema normalizer: {value!r}. "
        "Expected one of: simple, pyld."
    )
    return "simple"


def _normalize_web_html_text_extractor(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    allowed = {
        "bs4",
        "trafilatura",
        "readability_lxml",
        "justext",
        "boilerpy3",
        "ensemble_v1",
    }
    if normalized in allowed:
        return normalized
    _fail(
        f"Invalid web HTML text extractor: {value!r}. "
        "Expected one of: bs4, trafilatura, readability_lxml, justext, boilerpy3, ensemble_v1."
    )
    return "bs4"


def _normalize_web_schema_policy(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"prefer_schema", "schema_only", "heuristic_only"}:
        return normalized
    _fail(
        f"Invalid web schema policy: {value!r}. "
        "Expected one of: prefer_schema, schema_only, heuristic_only."
    )
    return "prefer_schema"


def _normalize_ingredient_text_fix_backend(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"none", "ftfy"}:
        return normalized
    _fail(
        f"Invalid ingredient text fix backend: {value!r}. "
        "Expected one of: none, ftfy."
    )
    return "none"


def _normalize_ingredient_pre_normalize_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized == "aggressive_v1":
        return normalized
    _fail(
        f"Invalid ingredient pre-normalize mode: {value!r}. "
        "Expected: aggressive_v1."
    )
    return "aggressive_v1"


def _normalize_ingredient_packaging_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"off", "regex_v1"}:
        return normalized
    _fail(
        f"Invalid ingredient packaging mode: {value!r}. "
        "Expected one of: off, regex_v1."
    )
    return "off"


def _normalize_ingredient_parser_backend(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {
        "ingredient_parser_nlp",
        "quantulum3_regex",
        "hybrid_nlp_then_quantulum3",
    }:
        return normalized
    _fail(
        f"Invalid ingredient parser backend: {value!r}. "
        "Expected one of: ingredient_parser_nlp, quantulum3_regex, hybrid_nlp_then_quantulum3."
    )
    return "ingredient_parser_nlp"


def _normalize_ingredient_unit_canonicalizer(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized == "pint":
        return normalized
    _fail(
        f"Invalid ingredient unit canonicalizer: {value!r}. "
        "Expected: pint."
    )
    return "pint"


def _normalize_ingredient_missing_unit_policy(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"medium", "null", "each"}:
        return normalized
    _fail(
        f"Invalid ingredient missing unit policy: {value!r}. "
        "Expected one of: medium, null, each."
    )
    return "null"


def _normalize_p6_time_backend(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"regex_v1", "quantulum3_v1", "hybrid_regex_quantulum3_v1"}:
        return normalized
    _fail(
        f"Invalid Priority 6 time backend: {value!r}. "
        "Expected one of: regex_v1, quantulum3_v1, hybrid_regex_quantulum3_v1."
    )
    return "regex_v1"


def _normalize_p6_time_total_strategy(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"sum_all_v1", "max_v1", "selective_sum_v1"}:
        return normalized
    _fail(
        f"Invalid Priority 6 time total strategy: {value!r}. "
        "Expected one of: sum_all_v1, max_v1, selective_sum_v1."
    )
    return "sum_all_v1"


def _normalize_p6_temperature_backend(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"regex_v1", "quantulum3_v1", "hybrid_regex_quantulum3_v1"}:
        return normalized
    _fail(
        f"Invalid Priority 6 temperature backend: {value!r}. "
        "Expected one of: regex_v1, quantulum3_v1, hybrid_regex_quantulum3_v1."
    )
    return "regex_v1"


def _normalize_p6_temperature_unit_backend(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"builtin_v1", "pint_v1"}:
        return normalized
    _fail(
        f"Invalid Priority 6 temperature unit backend: {value!r}. "
        "Expected one of: builtin_v1, pint_v1."
    )
    return "builtin_v1"


def _normalize_p6_ovenlike_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"keywords_v1", "off"}:
        return normalized
    _fail(
        f"Invalid Priority 6 ovenlike mode: {value!r}. "
        "Expected one of: keywords_v1, off."
    )
    return "keywords_v1"


def _normalize_p6_yield_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized == "scored_v1":
        return normalized
    _fail(
        f"Invalid Priority 6 yield mode: {value!r}. "
        "Expected: scored_v1."
    )
    return "scored_v1"


def _normalize_llm_recipe_pipeline(value: str) -> str:
    try:
        return normalize_llm_recipe_pipeline_value(value)
    except ValueError:
        _fail(
            f"Invalid LLM recipe pipeline: {value!r}. "
            "Expected one of: "
            + ", ".join(RECIPE_CODEX_FARM_ALLOWED_PIPELINES)
            + "."
        )
        return "off"


def _ensure_codex_farm_cmd_available(cmd: str) -> None:
    cleaned = str(cmd or "codex-farm").strip()
    if not cleaned:
        cleaned = "codex-farm"
    try:
        binary = shlex.split(cleaned)[0]
    except ValueError:
        binary = cleaned.split()[0] if cleaned.split() else "codex-farm"
    if not shutil.which(binary):
        _fail(
            f"Codex Farm command not found: {cleaned!r}. "
            "Install `codex-farm` (for example from ../shared/CodexFarm) "
            "or set --codex-farm-cmd to an absolute path."
        )


def _normalize_llm_knowledge_pipeline(value: str) -> str:
    try:
        return normalize_llm_knowledge_pipeline_value(value)
    except ValueError:
        _fail(
            f"Invalid LLM knowledge pipeline: {value!r}. "
            f"Expected one of: off, {KNOWLEDGE_CODEX_PIPELINE_CANDIDATE_V2}."
        )
        return "off"


def _normalize_codex_farm_failure_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"fail", "fallback"}:
        _fail(
            f"Invalid codex-farm failure mode: {value!r}. "
            "Expected one of: fail, fallback."
        )
    return normalized


def _normalize_codex_farm_pipeline_id(value: str, *, option: str) -> str:
    normalized = value.strip()
    if not normalized:
        _fail(f"{option} must be a non-empty pipeline id.")
    return normalized


def _normalize_benchmark_eval_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {
        "stage-block",
        "stage-blocks",
        "stage",
    }:
        return BENCHMARK_EVAL_MODE_STAGE_BLOCKS
    if normalized in {
        "canonical",
        "canonical-text",
    }:
        return BENCHMARK_EVAL_MODE_CANONICAL_TEXT
    _fail(
        f"Invalid benchmark eval mode: {value!r}. "
        "Expected one of: stage-blocks, canonical-text."
    )
    return BENCHMARK_EVAL_MODE_STAGE_BLOCKS


def _normalize_gold_adaptation_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "off", "none", "disabled", "false", "0"}:
        return "off"
    if normalized in {"auto", "on", "enabled", "true", "1"}:
        return "auto"
    if normalized in {"force", "forced"}:
        return "force"
    _fail(
        f"Invalid gold adaptation mode: {value!r}. "
        "Expected one of: off, auto, force."
    )
    return "off"




def _normalize_codex_farm_recipe_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "extract"}:
        return CODEX_FARM_RECIPE_MODE_EXTRACT
    if normalized == "benchmark":
        return CODEX_FARM_RECIPE_MODE_BENCHMARK
    _fail(
        f"Invalid codex-farm recipe mode: {value!r}. "
        "Expected one of: extract, benchmark."
    )
    return CODEX_FARM_RECIPE_MODE_EXTRACT


def _normalize_atomic_block_splitter(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "off", "none", "default"}:
        return "off"
    if normalized in {"atomic-v1", "atomic"}:
        return "atomic-v1"
    _fail(
        f"Invalid atomic block splitter: {value!r}. "
        "Expected one of: off, atomic-v1."
    )
    return "off"


def _normalize_line_role_pipeline(value: str) -> str:
    try:
        return normalize_line_role_pipeline_value(value)
    except ValueError:
        _fail(
            f"Invalid line role pipeline: {value!r}. "
            f"Expected one of: off, {LINE_ROLE_PIPELINE_ROUTE_V2}."
        )
        return "off"


def _benchmark_sequence_matcher_modes() -> tuple[str, ...]:
    return tuple(str(mode) for mode in supported_sequence_matcher_modes())


def _benchmark_sequence_matcher_display_name(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    return BENCHMARK_SEQUENCE_MATCHER_DISPLAY_NAMES.get(normalized, normalized or "dmp")


def _normalize_benchmark_sequence_matcher_mode(value: str) -> str:
    normalized = str(value or "dmp").strip().lower()
    supported = _benchmark_sequence_matcher_modes()
    if normalized in supported:
        return normalized
    _fail(
        f"Invalid benchmark sequence matcher mode: {value!r}. "
        f"Expected one of: {', '.join(supported)}."
    )
    return "dmp"


def _parse_csv_labels(value: str) -> set[str]:
    labels = {item.strip().upper() for item in value.split(",") if item.strip()}
    if not labels:
        _fail("At least one label is required (example: YIELD_LINE,TIME_LINE).")
    return labels


def _parse_quality_discover_formats(value: str | None) -> list[str] | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_value.split(","):
        cleaned = str(item or "").strip().lower()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned}"
        if cleaned == ".":
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    if not normalized:
        _fail(
            "Invalid --formats value. Expected comma-separated extensions like .pdf,.epub."
        )
    return normalized


@contextmanager
def _temporary_epub_extractor(value: str) -> Iterable[None]:
    previous = os.environ.get("C3IMP_EPUB_EXTRACTOR")
    os.environ["C3IMP_EPUB_EXTRACTOR"] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("C3IMP_EPUB_EXTRACTOR", None)
        else:
            os.environ["C3IMP_EPUB_EXTRACTOR"] = previous


@contextmanager
def _temporary_benchmark_sequence_matcher(mode: str) -> Iterable[None]:
    previous = os.environ.get(SEQUENCE_MATCHER_ENV)
    normalized_mode = _normalize_benchmark_sequence_matcher_mode(mode)
    os.environ[SEQUENCE_MATCHER_ENV] = normalized_mode
    reset_sequence_matcher_selection_cache()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(SEQUENCE_MATCHER_ENV, None)
        else:
            os.environ[SEQUENCE_MATCHER_ENV] = previous
        reset_sequence_matcher_selection_cache()


def _set_epub_unstructured_env(
    *,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> None:
    os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = html_parser_version
    os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = (
        "true" if skip_headers_footers else "false"
    )
    os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = preprocess_mode


@contextmanager
def _temporary_epub_unstructured_options(
    *,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> Iterable[None]:
    previous_parser = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION")
    previous_skip = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS")
    previous_preprocess = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE")
    _set_epub_unstructured_env(
        html_parser_version=html_parser_version,
        skip_headers_footers=skip_headers_footers,
        preprocess_mode=preprocess_mode,
    )
    try:
        yield
    finally:
        if previous_parser is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = previous_parser
        if previous_skip is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = previous_skip
        if previous_preprocess is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = previous_preprocess


def _warm_all_models(ocr_device: str = "auto") -> None:
    """Proactively load heavy models into memory."""
    from cookimport.ocr.doctr_engine import warm_ocr_model
    from cookimport.parsing.spacy_support import warm_spacy_model
    from cookimport.parsing.ingredients import warm_ingredient_parser

    # Warm SpaCy
    warm_spacy_model()
    # Warm Ingredient Parser
    warm_ingredient_parser()
    # Warm OCR
    try:
        warm_ocr_model(device=ocr_device)
    except Exception as e:
        logger.warning(f"Failed to warm OCR model: {e}")


def _resolve_labelstudio_settings(
    label_studio_url: str | None,
    label_studio_api_key: str | None,
) -> tuple[str, str]:
    url = label_studio_url or os.getenv("LABEL_STUDIO_URL")
    api_key = label_studio_api_key or os.getenv("LABEL_STUDIO_API_KEY")
    if not url:
        _fail("Label Studio URL missing. Use --label-studio-url or LABEL_STUDIO_URL.")
    if not api_key:
        _fail("Label Studio API key missing. Use --label-studio-api-key or LABEL_STUDIO_API_KEY.")
    return url, api_key


def _prompt_manual_project_name() -> str | None:
    project_name_raw = _prompt_text(
        "Label Studio project name to export:",
        default="",
    )
    if project_name_raw is None:
        return None
    project_name = project_name_raw.strip()
    if not project_name:
        typer.secho("Project name is required for export.", fg=typer.colors.RED)
        return None
    return project_name


def _discover_manifest_project_scopes(*roots: Path) -> dict[str, str]:
    """Best-effort map of project title -> task scope from local manifest history."""
    latest_by_project: dict[str, tuple[float, str]] = {}
    for root in roots:
        if not root.exists():
            continue
        for manifest_path in root.glob("**/labelstudio/**/manifest.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            project_name = str(payload.get("project_name", "")).strip()
            task_scope = str(payload.get("task_scope", "")).strip()
            if not project_name or not task_scope:
                continue
            try:
                mtime = manifest_path.stat().st_mtime
            except OSError:
                mtime = 0.0
            previous = latest_by_project.get(project_name)
            if previous is None or mtime >= previous[0]:
                latest_by_project[project_name] = (mtime, task_scope)
    return {project_name: scope for project_name, (_mtime, scope) in latest_by_project.items()}


def _infer_scope_from_project_payload(project: dict[str, Any]) -> str | None:
    """Infer task scope from Label Studio project payload when available."""
    explicit_scope = str(project.get("task_scope", "")).strip()
    if explicit_scope in KNOWN_LABELSTUDIO_TASK_SCOPES:
        return explicit_scope

    label_config = str(project.get("label_config", "") or "")
    if not label_config:
        return None

    if any(
        marker in label_config
        for marker in (
            "YIELD_LINE",
            "TIME_LINE",
            "RECIPE_NOTES",
            "RECIPE_VARIANT",
            "KNOWLEDGE",
        )
    ):
        return "freeform-spans"
    if (
        "RECIPE_TITLE" in label_config
        and "INGREDIENT_LINE" in label_config
        and "INSTRUCTION_LINE" in label_config
        and "NARRATIVE" in label_config
        and "VARIANT" not in label_config
        and "RECIPE_VARIANT" not in label_config
    ):
        return "canonical-blocks"
    if "mixed" in label_config and "value_usefulness" in label_config:
        return "pipeline"
    return None


def _select_export_project(
    *,
    label_studio_url: str,
    label_studio_api_key: str,
) -> tuple[str | None, str | None]:
    try:
        client = LabelStudioClient(label_studio_url, label_studio_api_key)
        projects = client.list_projects()
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Could not fetch Label Studio projects ({exc}). Falling back to manual entry.",
            fg=typer.colors.YELLOW,
        )
        return _prompt_manual_project_name(), None

    known_scopes = _discover_manifest_project_scopes(DEFAULT_GOLDEN, DEFAULT_OUTPUT)
    scope_by_title: dict[str, str | None] = {}
    for project in projects:
        if not isinstance(project, dict):
            continue
        title = str(project.get("title", "")).strip()
        if not title:
            continue
        scope_by_title[title] = known_scopes.get(title) or _infer_scope_from_project_payload(project)

    project_titles = sorted(scope_by_title.keys(), key=str.casefold)

    if not project_titles:
        typer.secho(
            "No Label Studio projects found. Enter a project name manually.",
            fg=typer.colors.YELLOW,
        )
        return _prompt_manual_project_name(), None

    selection = _menu_select(
        "Select Label Studio project to export:",
        menu_help="Choose an existing project title (with detected type), or switch to manual entry.",
        choices=[
            questionary.Choice("Type project name manually", value="__manual__"),
            *[
                questionary.Choice(
                    f"{title} [type: {scope_by_title.get(title) or 'unknown'}]",
                    value=title,
                )
                for title in project_titles
            ],
        ],
    )
    if selection in {None, BACK_ACTION}:
        return None, None
    if selection == "__manual__":
        return _prompt_manual_project_name(), None
    selected_project = str(selection)
    return selected_project, scope_by_title.get(selected_project)


def _select_export_project_name(
    *,
    label_studio_url: str,
    label_studio_api_key: str,
) -> str | None:
    project_name, _detected_scope = _select_export_project(
        label_studio_url=label_studio_url,
        label_studio_api_key=label_studio_api_key,
    )
    return project_name


def _require_labelstudio_write_consent(allow_labelstudio_write: bool) -> None:
    if not allow_labelstudio_write:
        _fail(
            "Label Studio uploads are blocked by default. "
            "Re-run with --allow-labelstudio-write to push tasks."
        )




_PROGRESS_STAGE_COUNTER_SUFFIX_RE = re.compile(
    r"\s+(?:task|item|config|phase|row|shard)\s+\d+/\d+\s*$",
    re.IGNORECASE,
)












































@dataclass
class _HostCpuUtilizationSampler:
    source: str = "proc_stat_linux"
    sample_count: int = 0
    _last_totals: tuple[int, int] | None = None

    def sample_percent(self) -> float | None:
        current = _read_linux_cpu_totals()
        if current is None:
            self.source = "unavailable"
            self._last_totals = None
            return None
        previous = self._last_totals
        self._last_totals = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        busy_delta = max(0, total_delta - max(0, idle_delta))
        self.sample_count += 1
        return max(0.0, min(100.0, (float(busy_delta) / float(total_delta)) * 100.0))


def _processing_timeseries_json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _processing_timeseries_json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_processing_timeseries_json_safe(item) for item in value]
    return value


@dataclass
class _ProcessingTimeseriesWriter:
    path: Path
    heartbeat_seconds: float = PROCESSING_TIMESERIES_HEARTBEAT_SECONDS
    cpu_sampler: _HostCpuUtilizationSampler = field(default_factory=_HostCpuUtilizationSampler)
    row_count: int = 0
    _last_snapshot: str = ""
    _last_write_monotonic: float = field(default_factory=time.monotonic)
    _write_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def write_row(
        self,
        *,
        snapshot: str,
        payload: dict[str, Any],
        force: bool = False,
    ) -> None:
        now_monotonic = time.monotonic()
        with self._write_lock:
            write_due = (
                force
                or snapshot != self._last_snapshot
                or (
                    now_monotonic - self._last_write_monotonic
                    >= max(0.05, float(self.heartbeat_seconds))
                )
            )
            if not write_due:
                return
            row = dict(payload)
            row.setdefault(
                "timestamp",
                dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            )
            row.setdefault("monotonic_seconds", now_monotonic)
            row["snapshot"] = snapshot
            row["cpu_utilization_pct"] = self.cpu_sampler.sample_percent()
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            _processing_timeseries_json_safe(row),
                            sort_keys=True,
                        )
                        + "\n"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Ignoring processing time-series write failure for %s: %s",
                    self.path,
                    exc,
                )
                return
            self._last_snapshot = snapshot
            self._last_write_monotonic = now_monotonic
            self.row_count += 1
def _notify_progress_callback(
    progress_callback: Callable[[str], None] | None,
    message: str,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Progress callback raised and was ignored: %s", exc)


def _notify_benchmark_scheduler_event(
    event: str,
    **payload: Any,
) -> None:
    callback = _BENCHMARK_SCHEDULER_EVENT_CALLBACK.get()
    if callback is None:
        return
    event_name = str(event or "").strip()
    if not event_name:
        return
    event_payload: dict[str, Any] = {
        "event": event_name,
        "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
    }
    event_payload.update(payload)
    try:
        callback(event_payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ignoring benchmark scheduler event callback failure: %s", exc)


def _run_labelstudio_import_with_status(
    *,
    source_name: str,
    run_import: Callable[[Callable[[str], None]], dict[str, Any]],
    telemetry_path: Path | None = None,
) -> dict[str, Any]:
    return _run_with_progress_status(
        initial_status=f"Running Label Studio import for {source_name}...",
        progress_prefix=f"Label Studio import ({source_name})",
        run=run_import,
        telemetry_path=telemetry_path,
    )


def _discover_freeform_gold_exports(output_dir: Path) -> list[Path]:
    roots: list[Path] = [output_dir]
    if DEFAULT_OUTPUT not in roots:
        roots.append(DEFAULT_OUTPUT)
    if DEFAULT_GOLDEN not in roots:
        roots.append(DEFAULT_GOLDEN)

    seen: set[Path] = set()
    exports: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("**/exports/freeform_span_labels.jsonl"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            exports.append(path)

    def _sort_key(path: Path) -> tuple[float, str]:
        try:
            mtime = path.stat().st_mtime
        except Exception:  # noqa: BLE001
            mtime = 0.0
        return (mtime, str(path))

    exports.sort(key=_sort_key, reverse=True)
    return exports


def _discover_prediction_runs(output_dir: Path) -> list[Path]:
    roots: list[Path] = [output_dir]
    if DEFAULT_OUTPUT not in roots:
        roots.append(DEFAULT_OUTPUT)
    if DEFAULT_GOLDEN not in roots:
        roots.append(DEFAULT_GOLDEN)

    seen: set[Path] = set()
    runs: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for marker in root.glob("**/label_studio_tasks.jsonl"):
            run_dir = marker.parent
            if not run_dir.exists() or not run_dir.is_dir():
                continue
            resolved = run_dir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            runs.append(run_dir)

    def _sort_key(path: Path) -> tuple[float, str]:
        try:
            mtime = (path / "label_studio_tasks.jsonl").stat().st_mtime
        except Exception:  # noqa: BLE001
            mtime = 0.0
        return (mtime, str(path))

    runs.sort(key=_sort_key, reverse=True)
    return runs


def _load_manifest_source_file(gold_spans_path: Path) -> str | None:
    run_root = gold_spans_path.parent.parent
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(manifest, dict):
        return None
    source_file = str(manifest.get("source_file") or "").strip()
    return source_file or None


def _first_source_file_from_jsonl(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(payload, dict):
                    continue
                source_file = str(payload.get("source_file") or "").strip()
                if source_file:
                    return source_file
    except Exception:  # noqa: BLE001
        return None
    return None


def _source_name_from_hint(source_hint: str | None) -> str | None:
    if source_hint is None:
        return None
    stripped = source_hint.strip()
    if not stripped:
        return None
    source_name = Path(stripped).name.strip()
    return source_name or None


def _load_source_hint_from_gold_export(gold_spans_path: Path) -> str | None:
    source_hint = _source_name_from_hint(_load_manifest_source_file(gold_spans_path))
    if source_hint:
        return source_hint

    source_hint = _source_name_from_hint(_first_source_file_from_jsonl(gold_spans_path))
    if source_hint:
        return source_hint

    segment_manifest_path = gold_spans_path.parent / "freeform_segment_manifest.jsonl"
    return _source_name_from_hint(_first_source_file_from_jsonl(segment_manifest_path))


def _infer_source_file_from_freeform_gold(gold_spans: Path) -> Path | None:
    manifest_source = _load_manifest_source_file(gold_spans)
    if manifest_source:
        candidate = Path(manifest_source)
        if candidate.exists() and candidate.is_file():
            return candidate

    source_name = _load_source_hint_from_gold_export(gold_spans)
    if source_name is None:
        return None
    input_candidate = DEFAULT_INPUT / source_name
    if input_candidate.exists() and input_candidate.is_file():
        return input_candidate
    return None


def _load_total_recipes_from_report_path(
    report_path_value: Path | str | None,
) -> int | None:
    if report_path_value is None:
        return None
    report_path = Path(report_path_value)
    if not report_path.exists() or not report_path.is_file():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    total_recipes = payload.get("totalRecipes")
    try:
        return int(total_recipes)
    except (TypeError, ValueError):
        return None


def _load_gold_recipe_headers_from_summary(gold_spans_path: Path) -> int | None:
    summary_path = gold_spans_path.parent / "summary.json"
    if not summary_path.exists() or not summary_path.is_file():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None

    recipe_counts = payload.get("recipe_counts")
    if isinstance(recipe_counts, dict):
        value = recipe_counts.get("recipe_headers")
        try:
            return int(value)
        except (TypeError, ValueError):
            pass

    counts = payload.get("counts")
    if isinstance(counts, dict):
        value = counts.get("recipe_headers")
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _attach_freeform_recipe_count_context(
    *,
    report: dict[str, Any],
    gold_spans_path: Path,
    predicted_recipe_count: int | None,
    predicted_recipe_count_source: str | None = None,
) -> None:
    gold_recipe_headers = _load_gold_recipe_headers_from_summary(gold_spans_path)
    gold_recipe_headers_source = (
        "gold_summary.recipe_counts.recipe_headers"
        if gold_recipe_headers is not None
        else None
    )
    attach_recipe_count_diagnostics(
        report,
        gold_recipe_headers=gold_recipe_headers,
        gold_recipe_headers_source=gold_recipe_headers_source,
        predicted_recipe_count=predicted_recipe_count,
        predicted_recipe_count_source=predicted_recipe_count_source,
    )





def _load_support_submodule(module_basename: str) -> Any:
    full_name = f"{__name__}.{module_basename}"
    module_path = Path(__file__).with_name(f"{module_basename}.py")
    existing = sys.modules.get(full_name)
    if existing is not None and getattr(existing, "__file__", None) == str(module_path):
        return existing
    module_spec = importlib.util.spec_from_file_location(full_name, module_path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"unable to load cli_support submodule {full_name} from {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[full_name] = module
    module_spec.loader.exec_module(module)
    return module


_progress_module = _load_support_submodule("progress")
for _progress_name in _progress_module.__all__:
    globals()[_progress_name] = getattr(_progress_module, _progress_name)
del _progress_module
del _progress_name

_bench_module = _load_support_submodule("bench")
for _bench_name in _bench_module.__all__:
    globals()[_bench_name] = getattr(_bench_module, _bench_name)
del _bench_module
del _bench_name

_settings_flow_module = _load_support_submodule("settings_flow")
for _settings_flow_name in _settings_flow_module.__all__:
    globals()[_settings_flow_name] = getattr(_settings_flow_module, _settings_flow_name)
del _settings_flow_module
del _settings_flow_name

_interactive_flow_module = _load_support_submodule("interactive_flow")
for _interactive_flow_name in _interactive_flow_module.__all__:
    globals()[_interactive_flow_name] = getattr(_interactive_flow_module, _interactive_flow_name)
del _interactive_flow_module
del _interactive_flow_name


from .bench_compare import (
    _build_source_debug_artifact_status,
    _build_line_role_regression_gate_payload,
    _build_labelstudio_benchmark_compare_payload,
    _build_labelstudio_benchmark_compare_single_eval_payload,
    _format_labelstudio_benchmark_compare_gates_markdown,
    _format_labelstudio_benchmark_compare_markdown,
    _resolve_labelstudio_benchmark_compare_input,
    _resolve_labelstudio_benchmark_compare_report_root,
    _resolve_line_role_baseline_joined_rows,
    _source_key_from_source_path,
    labelstudio_benchmark_compare,
)

from .stage import (
    _build_stage_run_summary_payload,
    _infer_importer_name_from_source_path,
    _iter_files,
    _load_split_job_full_blocks,
    _load_stage_observability_payload,
    _merge_raw_artifacts,
    _merge_source_jobs,
    _offset_result_block_indices,
    _path_for_manifest,
    _print_stage_summary,
    _require_importer,
    _resolve_mapping_path,
    _resolve_overrides_path,
    _write_error_report,
    _write_eval_run_manifest,
    _write_knowledge_index_best_effort,
    _write_run_manifest_best_effort,
    _write_stage_observability_best_effort,
    _write_stage_run_manifest,
    _write_stage_run_summary,
)


__all__ = [name for name in globals() if not name.startswith("__")]
