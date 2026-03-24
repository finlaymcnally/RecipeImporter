from __future__ import annotations

import cProfile
import csv
import datetime as dt
import functools
import hashlib
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
    KNOWLEDGE_CODEX_PIPELINE_SHARD_V1,
    LINE_ROLE_PIPELINE_SHARD_V1,
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
    NONRECIPE_REVIEW_EXCLUSIONS_FILE_NAME,
    NONRECIPE_REVIEW_STATUS_FILE_NAME,
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

app = typer.Typer(add_completion=False, invoke_without_command=True)
bench_app = typer.Typer(name="bench", help="Offline benchmark suite tools.")
compare_control_app = typer.Typer(
    name="compare-control",
    help="Backend Compare & Control analytics for CLI and agent workflows.",
)
app.add_typer(bench_app)
app.add_typer(compare_control_app, name="compare-control")

from cookimport.epubdebug.cli import epub_app  # noqa: E402
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
app.add_typer(epub_app, name="epub")
console = Console()
logger = logging.getLogger(__name__)


def _sync_cli_command_module_globals() -> None:
    from cookimport import cli as compat_cli
    from cookimport.cli_commands import (
        analytics as analytics_commands,
        bench as bench_commands,
        compare_control as compare_control_commands,
        interactive as interactive_commands,
        labelstudio as labelstudio_commands,
        stage as stage_commands,
    )

    runtime_globals = globals()
    skipped_runtime_state = {
        "_LIVE_STATUS_SLOT_ACTIVE",
    }
    for name, value in compat_cli.__dict__.items():
        if name.startswith("__"):
            continue
        if name in skipped_runtime_state:
            continue
        runtime_globals[name] = value

    modules = (
        analytics_commands,
        bench_commands,
        compare_control_commands,
        interactive_commands,
        labelstudio_commands,
        stage_commands,
    )
    for module in modules:
        for name, value in module.__dict__.items():
            if name.startswith("__"):
                continue
            if hasattr(compat_cli, name):
                setattr(module, name, getattr(compat_cli, name))


def _rebuild_cli_apps_from_command_packages() -> None:
    from cookimport.cli_commands import (
        analytics as analytics_commands,
        bench as bench_commands,
        compare_control as compare_control_commands,
        interactive as interactive_commands,
        labelstudio as labelstudio_commands,
        stage as stage_commands,
    )

    global app, bench_app, compare_control_app

    root_app = typer.Typer(add_completion=False, invoke_without_command=True)
    bench_group = typer.Typer(name="bench", help="Offline benchmark suite tools.")
    compare_group = typer.Typer(
        name="compare-control",
        help="Backend Compare & Control analytics for CLI and agent workflows.",
    )
    root_app.add_typer(bench_group)
    root_app.add_typer(compare_group, name="compare-control")
    root_app.add_typer(epub_app, name="epub")

    _sync_cli_command_module_globals()
    interactive_exports = interactive_commands.register_callback(root_app)
    stage_exports = stage_commands.register(root_app)
    labelstudio_exports = labelstudio_commands.register(root_app)
    analytics_exports = analytics_commands.register(root_app)
    bench_exports = bench_commands.register(bench_group)
    compare_control_exports = compare_control_commands.register(compare_group)

    def _compat_export(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            _sync_cli_command_module_globals()
            return fn(*args, **kwargs)

        return _wrapped

    for export_group in (
        interactive_exports,
        stage_exports,
        labelstudio_exports,
        analytics_exports,
        bench_exports,
        compare_control_exports,
    ):
        for name, value in export_group.items():
            if callable(value):
                globals()[name] = _compat_export(value)
            else:
                globals()[name] = value

    app = root_app
    bench_app = bench_group
    compare_control_app = compare_group

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
BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES = (
    "upload_bundle_overview.md",
    "upload_bundle_index.json",
    "upload_bundle_payload.jsonl",
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


def _refresh_dashboard_after_history_write(
    *,
    csv_path: Path,
    output_root: Path | None = None,
    golden_root: Path = DEFAULT_GOLDEN,
    dashboard_out_dir: Path | None = None,
    reason: str | None = None,
) -> None:
    resolved_csv_path = csv_path.expanduser()
    if not resolved_csv_path.exists():
        return
    resolved_output_root = output_root.expanduser() if output_root is not None else None
    resolved_dashboard_out_dir = (
        dashboard_out_dir.expanduser()
        if dashboard_out_dir is not None
        else (resolved_csv_path.parent / "dashboard")
    )
    if resolved_output_root is None:
        resolved_output_root = _infer_output_root_from_history_csv(resolved_csv_path)
    reason_suffix = f" ({reason})" if reason else ""
    if resolved_output_root is None:
        logger.warning(
            "Dashboard refresh skipped%s: unable to infer output root for %s",
            reason_suffix,
            resolved_csv_path,
        )
        return
    try:
        stats_dashboard(
            output_root=resolved_output_root,
            golden_root=golden_root,
            out_dir=resolved_dashboard_out_dir,
            open_browser=False,
            since_days=None,
            scan_reports=False,
            scan_benchmark_reports=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dashboard refresh failed%s: %s", reason_suffix, exc)


def _menu_option_count(choices: list[Any]) -> int:
    return sum(
        1
        for raw_choice in choices
        if not isinstance(QuestionaryChoice.build(raw_choice), QuestionarySeparator)
    )


def _menu_shortcut_bindings(choices: list[Any]) -> dict[str, Any]:
    selectable_choices: list[QuestionaryChoice] = []
    for raw_choice in choices:
        built_choice = QuestionaryChoice.build(raw_choice)
        if isinstance(built_choice, QuestionarySeparator) or built_choice.disabled:
            continue
        selectable_choices.append(built_choice)

    available_shortcuts = list(_MENU_SHORTCUT_KEYS)
    bindings: dict[str, Any] = {}

    # Respect explicit shortcuts first.
    for built_choice in selectable_choices:
        shortcut_key = built_choice.shortcut_key
        if isinstance(shortcut_key, str) and shortcut_key:
            if shortcut_key in available_shortcuts:
                available_shortcuts.remove(shortcut_key)
            bindings[shortcut_key] = built_choice.value

    # Mirror Questionary's auto-assignment order for remaining choices.
    for built_choice in selectable_choices:
        shortcut_key = built_choice.shortcut_key
        if isinstance(shortcut_key, str):
            continue
        if shortcut_key is False:
            continue
        if not available_shortcuts:
            break
        assigned = available_shortcuts.pop(0)
        bindings[assigned] = built_choice.value

    return bindings


def _menu_select(
    message: str,
    *,
    choices: list[Any],
    menu_help: str | None = None,
    **kwargs: Any,
) -> Any:
    """Select helper with Escape support for one-level menu back navigation."""
    option_count = _menu_option_count(choices)
    use_shortcuts = option_count <= len(_MENU_SHORTCUT_KEYS)
    shortcut_bindings = _menu_shortcut_bindings(choices) if use_shortcuts else {}
    if menu_help:
        typer.secho(menu_help, fg=typer.colors.BRIGHT_BLACK)
    question = questionary.select(
        message,
        choices=choices,
        instruction=(
            "(Type number shortcut to select, Enter to select, Esc to go back)"
            if use_shortcuts
            else "(Enter to select, Esc to go back)"
        ),
        use_shortcuts=use_shortcuts,
        **kwargs,
    )

    @question.application.key_bindings.add(Keys.Escape, eager=True)
    def _go_back(event: Any) -> None:
        event.app.exit(result=BACK_ACTION)

    if use_shortcuts:
        for key, value in shortcut_bindings.items():
            if key not in "0123456789":
                continue

            def _register_numeric_shortcut(shortcut: str, selected_value: Any) -> None:
                @question.application.key_bindings.add(shortcut, eager=True)
                def _select_by_shortcut(event: Any) -> None:
                    event.app.exit(result=selected_value)

            _register_numeric_shortcut(key, value)

    return question.ask()


def _ask_with_escape_back(question: Any, *, back_result: Any = None) -> Any:
    """Ask a Questionary prompt and map Escape to a caller-defined back result."""
    application = getattr(question, "application", None)
    if application is not None:
        escape_bindings = KeyBindings()

        @escape_bindings.add(Keys.Escape, eager=True)
        def _go_back(event: Any) -> None:
            event.app.exit(result=back_result)

        existing_bindings = getattr(application, "key_bindings", None)
        if existing_bindings is None:
            application.key_bindings = escape_bindings
        else:
            application.key_bindings = merge_key_bindings(
                [escape_bindings, existing_bindings]
            )
    return question.ask()


def _prompt_text(
    message: str,
    *,
    default: str = "",
    instruction: str | None = None,
    **kwargs: Any,
) -> str | None:
    question = questionary.text(
        message,
        default=default,
        instruction=instruction,
        **kwargs,
    )
    return _ask_with_escape_back(question, back_result=None)


def _prompt_password(
    message: str,
    *,
    default: str = "",
    **kwargs: Any,
) -> str | None:
    question = questionary.password(
        message,
        default=default,
        **kwargs,
    )
    return _ask_with_escape_back(question, back_result=None)


def _prompt_confirm(
    message: str,
    *,
    default: bool = True,
    instruction: str | None = None,
    **kwargs: Any,
) -> bool | None:
    question = questionary.confirm(
        message,
        default=default,
        instruction=instruction,
        **kwargs,
    )
    return _ask_with_escape_back(question, back_result=None)


def _prompt_freeform_segment_settings(
    *,
    segment_blocks_default: int,
    segment_overlap_default: int,
    segment_focus_blocks_default: int,
    target_task_count_default: int | None,
) -> tuple[int, int, int, int | None] | None:
    """Prompt freeform segment settings with one-level Escape back navigation.

    Escape behavior:
    - focus -> overlap
    - overlap -> segment size
    - target task count -> focus
    - segment size -> cancel (caller decides prior-level navigation)
    """
    segment_blocks = max(1, int(segment_blocks_default))
    segment_overlap = max(0, int(segment_overlap_default))
    segment_focus_blocks = max(
        1,
        min(int(segment_focus_blocks_default), segment_blocks),
    )
    target_task_count = (
        None if target_task_count_default is None else int(target_task_count_default)
    )

    step = "segment_blocks"
    while True:
        if step == "segment_blocks":
            segment_blocks_raw = _prompt_text(
                "Freeform segment size (blocks per task):",
                default=str(segment_blocks),
            )
            if segment_blocks_raw is None:
                return None
            try:
                parsed_segment_blocks = int(segment_blocks_raw.strip())
            except ValueError:
                typer.secho("Segment size must be an integer >= 1.", fg=typer.colors.RED)
                continue
            if parsed_segment_blocks < 1:
                typer.secho("Segment size must be >= 1.", fg=typer.colors.RED)
                continue
            segment_blocks = parsed_segment_blocks
            if segment_focus_blocks > segment_blocks:
                segment_focus_blocks = segment_blocks
            step = "segment_overlap"
            continue

        if step == "segment_overlap":
            segment_overlap_raw = _prompt_text(
                "Freeform overlap (blocks):",
                default=str(segment_overlap),
            )
            if segment_overlap_raw is None:
                step = "segment_blocks"
                continue
            try:
                parsed_segment_overlap = int(segment_overlap_raw.strip())
            except ValueError:
                typer.secho("Segment overlap must be an integer >= 0.", fg=typer.colors.RED)
                continue
            if parsed_segment_overlap < 0:
                typer.secho("Segment overlap must be >= 0.", fg=typer.colors.RED)
                continue
            segment_overlap = parsed_segment_overlap
            step = "segment_focus_blocks"
            continue

        if step == "segment_focus_blocks":
            segment_focus_blocks_raw = _prompt_text(
                "Freeform focus size (blocks to label per task):",
                default=str(segment_focus_blocks),
            )
            if segment_focus_blocks_raw is None:
                step = "segment_overlap"
                continue
            try:
                parsed_focus_blocks = int(segment_focus_blocks_raw.strip())
            except ValueError:
                typer.secho("Focus size must be an integer >= 1.", fg=typer.colors.RED)
                continue
            if parsed_focus_blocks < 1:
                typer.secho("Focus size must be >= 1.", fg=typer.colors.RED)
                continue
            if parsed_focus_blocks > segment_blocks:
                typer.secho("Focus size must be <= segment size.", fg=typer.colors.RED)
                continue
            segment_focus_blocks = parsed_focus_blocks
            step = "target_task_count"
            continue

        target_task_count_raw = _prompt_text(
            "Target task count (optional, blank to disable):",
            default="" if target_task_count is None else str(target_task_count),
        )
        if target_task_count_raw is None:
            step = "segment_focus_blocks"
            continue

        target_task_count = None
        target_task_count_text = target_task_count_raw.strip()
        if target_task_count_text:
            try:
                parsed_target_task_count = int(target_task_count_text)
            except ValueError:
                typer.secho(
                    "Target task count must be an integer >= 1.",
                    fg=typer.colors.RED,
                )
                continue
            if parsed_target_task_count < 1:
                typer.secho("Target task count must be >= 1.", fg=typer.colors.RED)
                continue
            target_task_count = parsed_target_task_count

        return (
            segment_blocks,
            segment_overlap,
            segment_focus_blocks,
            target_task_count,
        )


def _load_settings() -> Dict[str, Any]:
    """Load user settings from config file."""
    source_parallel_default = _all_method_default_parallel_sources_from_cpu()
    defaults = {
        "workers": 7,
        "pdf_split_workers": 7,
        "epub_split_workers": 7,
        ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY: source_parallel_default,
        ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY: ALL_METHOD_SCHEDULER_SCOPE_DEFAULT,
        ALL_METHOD_MAX_INFLIGHT_SETTING_KEY: ALL_METHOD_MAX_INFLIGHT_DEFAULT,
        ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY: ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
        ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY: ALL_METHOD_MAX_EVAL_TAIL_DEFAULT,
        ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY: ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT,
        ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY: ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT,
        ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY: ALL_METHOD_SOURCE_SCHEDULING_DEFAULT,
        ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY: (
            ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
        ),
        ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY: (
            ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
        ),
        ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY: (
            ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
        ),
        ALL_METHOD_SMART_SCHEDULER_SETTING_KEY: True,
        "epub_extractor": "unstructured",
        "epub_unstructured_html_parser_version": "v1",
        "epub_unstructured_skip_headers_footers": True,
        "epub_unstructured_preprocess_mode": "br_split_v1",
        "web_schema_extractor": "builtin_jsonld",
        "web_schema_normalizer": "simple",
        "web_html_text_extractor": "bs4",
        "web_schema_policy": "prefer_schema",
        "web_schema_min_confidence": 0.75,
        "web_schema_min_ingredients": 2,
        "web_schema_min_instruction_steps": 1,
        "llm_recipe_pipeline": "off",
        "llm_knowledge_pipeline": "off",
        "line_role_pipeline": "off",
        "atomic_block_splitter": "off",
        "pdf_ocr_policy": "auto",
        "codex_farm_cmd": "codex-farm",
        "codex_farm_root": None,
        "codex_farm_workspace_root": None,
        "codex_farm_model": None,
        "codex_farm_reasoning_effort": None,
        "codex_farm_context_blocks": 30,
        "codex_farm_knowledge_context_blocks": 0,
        "label_studio_url": "",
        "label_studio_api_key": "",
        "ocr_device": "auto",
        "ocr_batch_size": 1,
        "pdf_pages_per_job": 50,
        "epub_spine_items_per_job": 10,
        "warm_models": False,
        "output_dir": str(DEFAULT_INTERACTIVE_OUTPUT),
    }
    if not DEFAULT_CONFIG_PATH.exists():
        defaults[ALL_METHOD_WING_BACKLOG_SETTING_KEY] = defaults[
            ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        defaults[ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = defaults[
            ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
    try:
        with open(DEFAULT_CONFIG_PATH, "r") as f:
            loaded = json.load(f)
    except Exception:
        defaults[ALL_METHOD_WING_BACKLOG_SETTING_KEY] = defaults[
            ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        defaults[ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = defaults[
            ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        return defaults
    if isinstance(loaded, dict):
        merged = {**defaults, **loaded}
        if ALL_METHOD_WING_BACKLOG_SETTING_KEY not in loaded:
            merged[ALL_METHOD_WING_BACKLOG_SETTING_KEY] = _resolve_positive_int_setting(
                merged,
                key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
            )
        if ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY not in loaded:
            merged[ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = _resolve_positive_int_setting(
                merged,
                key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
            )
        merged[ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY] = (
            _normalize_all_method_scheduler_scope(
                merged.get(ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY)
            )
        )
        return merged
    return defaults


def _run_settings_payload_from_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    return project_run_config_payload(
        settings,
        contract=RUN_SETTING_CONTRACT_FULL,
    )


def _save_settings(settings: Dict[str, Any]) -> None:
    """Save user settings to config file."""
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _coerce_non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _coerce_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _coerce_float_between(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def _display_optional_setting(value: Any, *, empty_label: str) -> str:
    cleaned = str(value or "").strip()
    return cleaned or empty_label


def _coerce_bool_setting(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_positive_int_setting(
    settings: Dict[str, Any],
    *,
    key: str,
    fallback: int,
) -> int:
    parsed = _coerce_positive_int(settings.get(key))
    if parsed is None:
        return fallback
    return parsed


def _resolve_non_negative_int_setting(
    settings: Dict[str, Any],
    *,
    key: str,
    fallback: int,
) -> int:
    parsed = _coerce_non_negative_int(settings.get(key))
    if parsed is None:
        return fallback
    return parsed


def _resolve_positive_float_setting(
    settings: Dict[str, Any],
    *,
    key: str,
    fallback: float,
) -> float:
    parsed = _coerce_positive_float(settings.get(key))
    if parsed is None:
        return fallback
    return parsed


def _normalize_all_method_source_scheduling(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {
        ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY,
        ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
    }:
        return normalized
    return ALL_METHOD_SOURCE_SCHEDULING_DEFAULT


def _normalize_all_method_scheduler_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized == ALL_METHOD_SCHEDULER_SCOPE_GLOBAL:
        return normalized
    return ALL_METHOD_SCHEDULER_SCOPE_DEFAULT


def _resolve_interactive_labelstudio_settings(
    settings: Dict[str, Any],
) -> tuple[str, str] | None:
    """Resolve Label Studio creds for interactive flows, persisting prompted values.

    Returns None when the user cancels an interactive prompt.
    """
    env_url = os.getenv("LABEL_STUDIO_URL")
    env_api_key = os.getenv("LABEL_STUDIO_API_KEY")
    stored_url = str(settings.get("label_studio_url", "") or "").strip()
    stored_api_key = str(settings.get("label_studio_api_key", "") or "").strip()

    label_studio_url = env_url or stored_url
    label_studio_api_key = env_api_key or stored_api_key

    if not label_studio_url:
        label_studio_url = _prompt_text(
            "Label Studio URL:",
            default=stored_url or "http://localhost:8080",
        )
        if label_studio_url is None:
            return None
    if not label_studio_api_key:
        label_studio_api_key = _prompt_password(
            "Label Studio API key:",
        )
        if label_studio_api_key is None:
            return None

    url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)

    changed = False
    if not env_url and url != stored_url:
        settings["label_studio_url"] = url
        changed = True
    if not env_api_key and api_key != stored_api_key:
        settings["label_studio_api_key"] = api_key
        changed = True
    if changed:
        _save_settings(settings)

    if not env_url and not env_api_key:
        preflight_error = _preflight_labelstudio_credentials(url, api_key)
        if preflight_error and _is_labelstudio_credential_error(preflight_error):
            typer.secho(
                "Saved Label Studio credentials were rejected. Please enter updated values.",
                fg=typer.colors.YELLOW,
            )
            refreshed_url = _prompt_text(
                "Label Studio URL:",
                default=url,
            )
            refreshed_api_key = _prompt_password(
                "Label Studio API key:",
            )
            if refreshed_url is None or refreshed_api_key is None:
                return None
            url, api_key = _resolve_labelstudio_settings(refreshed_url, refreshed_api_key)
            settings["label_studio_url"] = url
            settings["label_studio_api_key"] = api_key
            _save_settings(settings)
            retry_error = _preflight_labelstudio_credentials(url, api_key)
            if retry_error and _is_labelstudio_credential_error(retry_error):
                _fail(f"Updated Label Studio credentials were rejected: {retry_error}")

    return url, api_key


def _preflight_labelstudio_credentials(url: str, api_key: str) -> str | None:
    """Best-effort interactive credential probe; returns error text on failure."""
    try:
        client = LabelStudioClient(url, api_key)
        client.list_projects()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def _is_labelstudio_credential_error(error_text: str) -> bool:
    normalized = error_text.lower()
    return (
        "api error 401" in normalized
        or "api error 403" in normalized
        or "api error 404" in normalized
    )


def _list_importable_files(folder: Path) -> list[Path]:
    """List files in a folder that have a valid importer."""
    if not folder.exists():
        return []
    files = []
    for f in folder.glob("*"):
        if f.is_file() and not f.name.startswith("."):
            _, score = registry.best_importer_for_path(f)
            if score > 0:
                files.append(f)
    return sorted(files)


def _all_method_default_parallel_sources_from_cpu() -> int:
    cpu_total = max(1, int(os.cpu_count() or 1))
    baseline = 2 if cpu_total >= 4 else 1
    cpu_scaled = max(baseline, cpu_total // 4)
    return max(1, min(ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT, cpu_scaled))


def _coerce_configured_epub_extractor(value: Any) -> str:
    normalized = normalize_epub_extractor_name(value or "unstructured")
    if normalized == "auto":
        return "unstructured"
    if normalized not in EPUB_EXTRACTOR_CANONICAL_SET:
        return "unstructured"
    if is_policy_locked_epub_extractor_name(normalized):
        return "unstructured"
    return normalized


def _settings_menu(current_settings: Dict[str, Any]) -> None:
    """Run the settings configuration menu."""
    while True:
        enabled_epub_extractors = epub_extractor_enabled_choices()
        enabled_epub_extractors_display = "/".join(enabled_epub_extractors)
        current_epub_extractor = _coerce_configured_epub_extractor(
            current_settings.get("epub_extractor", "unstructured")
        )
        current_settings["epub_extractor"] = current_epub_extractor
        current_pdf_ocr_policy = str(
            current_settings.get("pdf_ocr_policy", "auto") or "auto"
        ).strip().lower()
        if current_pdf_ocr_policy not in {"off", "auto", "always"}:
            current_pdf_ocr_policy = "auto"
        current_recipe_pipeline = str(
            current_settings.get("llm_recipe_pipeline", "off") or "off"
        ).strip().lower()
        if current_recipe_pipeline not in RECIPE_CODEX_FARM_ALLOWED_PIPELINES:
            current_recipe_pipeline = "off"
        current_knowledge_pipeline = str(
            current_settings.get("llm_knowledge_pipeline", "off") or "off"
        ).strip().lower()
        if current_knowledge_pipeline not in {"off", KNOWLEDGE_CODEX_PIPELINE_SHARD_V1}:
            current_knowledge_pipeline = "off"
        current_web_schema_extractor = str(
            current_settings.get("web_schema_extractor", "builtin_jsonld")
            or "builtin_jsonld"
        ).strip().lower().replace("-", "_")
        if current_web_schema_extractor not in {
            "builtin_jsonld",
            "extruct",
            "scrape_schema_recipe",
            "recipe_scrapers",
            "ensemble_v1",
        }:
            current_web_schema_extractor = "builtin_jsonld"
        current_web_schema_normalizer = str(
            current_settings.get("web_schema_normalizer", "simple") or "simple"
        ).strip().lower().replace("-", "_")
        if current_web_schema_normalizer not in {"simple", "pyld"}:
            current_web_schema_normalizer = "simple"
        current_web_html_text_extractor = str(
            current_settings.get("web_html_text_extractor", "bs4") or "bs4"
        ).strip().lower().replace("-", "_")
        if current_web_html_text_extractor not in {
            "bs4",
            "trafilatura",
            "readability_lxml",
            "justext",
            "boilerpy3",
            "ensemble_v1",
        }:
            current_web_html_text_extractor = "bs4"
        current_web_schema_policy = str(
            current_settings.get("web_schema_policy", "prefer_schema")
            or "prefer_schema"
        ).strip().lower().replace("-", "_")
        if current_web_schema_policy not in ALL_METHOD_WEBSCHEMA_POLICIES:
            current_web_schema_policy = "prefer_schema"
        current_codex_cmd = _display_optional_setting(
            current_settings.get("codex_farm_cmd"),
            empty_label="codex-farm",
        )
        current_codex_root = _display_optional_setting(
            current_settings.get("codex_farm_root"),
            empty_label="<auto>",
        )
        current_codex_workspace_root = _display_optional_setting(
            current_settings.get("codex_farm_workspace_root"),
            empty_label="<auto>",
        )
        current_codex_model = _display_optional_setting(
            current_settings.get("codex_farm_model"),
            empty_label="<pipeline default>",
        )
        current_codex_reasoning_effort = _display_optional_setting(
            current_settings.get("codex_farm_reasoning_effort"),
            empty_label="<pipeline default>",
        )
        current_label_studio_url = _display_optional_setting(
            current_settings.get("label_studio_url"),
            empty_label="<unset>",
        )
        current_label_studio_api_key_status = (
            "set"
            if str(current_settings.get("label_studio_api_key") or "").strip()
            else "unset"
        )

        # Refresh values in display
        choice = _menu_select(
            "Settings Configuration",
            menu_help=(
                "Tune defaults used by stage/benchmark jobs. "
                "These settings are saved to cookimport.json."
            ),
            choices=[
                questionary.Choice(
                    f"Workers: {current_settings.get('workers', 4)} - max parallel file jobs",
                    value="workers",
                ),
                questionary.Choice(
                    f"PDF Split Workers: {current_settings.get('pdf_split_workers', 7)} - max PDF shard jobs",
                    value="pdf_split_workers",
                ),
                questionary.Choice(
                    f"EPUB Split Workers: {current_settings.get('epub_split_workers', 7)} - max EPUB shard jobs",
                    value="epub_split_workers",
                ),
                questionary.Choice(
                    (
                        "All-Method Parallel Sources: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY, fallback=_all_method_default_parallel_sources_from_cpu())} "
                        "- max matched sources run in parallel"
                    ),
                    value=ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Scheduler Scope: "
                        f"{_normalize_all_method_scheduler_scope(current_settings.get(ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY))} "
                        "- global mega queue or per-source schedulers"
                    ),
                    value=ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Source Scheduling: "
                        f"{_normalize_all_method_source_scheduling(current_settings.get(ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY))} "
                        "- discovery or tail_pair (heavy/light interleave)"
                    ),
                    value=ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Source Shard Threshold (s): "
                        f"{_resolve_positive_float_setting(current_settings, key=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY, fallback=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT):.1f} "
                        "- shard only when source estimate reaches this runtime"
                    ),
                    value=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Source Shard Max Parts: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY, fallback=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT)} "
                        "- max workload shards per source"
                    ),
                    value=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Source Shard Min Variants: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY, fallback=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT)} "
                        "- minimum variants required before sharding"
                    ),
                    value=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Inflight Pipelines: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_INFLIGHT_SETTING_KEY, fallback=ALL_METHOD_MAX_INFLIGHT_DEFAULT)} "
                        "- max all-method configs run in parallel"
                    ),
                    value=ALL_METHOD_MAX_INFLIGHT_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Split Slots: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY, fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT)} "
                        "- max split-heavy all-method configs"
                    ),
                    value=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Eval Tail Cap: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY, fallback=_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY, fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT))} "
                        "- smart-mode extra pipelines when configs are in evaluate phase"
                    ),
                    value=ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Config Timeout (s): "
                        f"{_resolve_non_negative_int_setting(current_settings, key=ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY, fallback=ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT)} "
                        "- 0 disables timeout for a single config run"
                    ),
                    value=ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Failed Retries: "
                        f"{_resolve_non_negative_int_setting(current_settings, key=ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY, fallback=ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT)} "
                        "- retry only failed configs after first pass"
                    ),
                    value=ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Wing Backlog: "
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_WING_BACKLOG_SETTING_KEY, fallback=_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY, fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT))} "
                        "- smart scheduler runway before split-heavy slots"
                    ),
                    value=ALL_METHOD_WING_BACKLOG_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        "All-Method Smart Scheduler: "
                        f"{'On' if _coerce_bool_setting(current_settings.get(ALL_METHOD_SMART_SCHEDULER_SETTING_KEY), default=True) else 'Off'} "
                        "- phase-aware queue admission"
                    ),
                    value=ALL_METHOD_SMART_SCHEDULER_SETTING_KEY,
                ),
                questionary.Choice(
                    (
                        f"EPUB Extractor: {current_epub_extractor} - "
                        f"{enabled_epub_extractors_display}"
                    ),
                    value="epub_extractor",
                ),
                questionary.Choice(
                    (
                        "Unstructured HTML Parser: "
                        f"{current_settings.get('epub_unstructured_html_parser_version', 'v1')} - v1/v2"
                    ),
                    value="epub_unstructured_html_parser_version",
                ),
                questionary.Choice(
                    (
                        "Unstructured Skip Headers/Footers: "
                        f"{'Yes' if current_settings.get('epub_unstructured_skip_headers_footers', True) else 'No'}"
                    ),
                    value="epub_unstructured_skip_headers_footers",
                ),
                questionary.Choice(
                    (
                        "Unstructured EPUB Preprocess: "
                        f"{current_settings.get('epub_unstructured_preprocess_mode', 'br_split_v1')} - none/br_split_v1"
                    ),
                    value="epub_unstructured_preprocess_mode",
                ),
                questionary.Choice(
                    (
                        f"PDF OCR Policy: {current_pdf_ocr_policy} - "
                        "off/auto/always"
                    ),
                    value="pdf_ocr_policy",
                ),
                questionary.Choice(
                    (
                        "Web Schema Extractor: "
                        f"{current_web_schema_extractor}"
                    ),
                    value="web_schema_extractor",
                ),
                questionary.Choice(
                    (
                        "Web Schema Normalizer: "
                        f"{current_web_schema_normalizer}"
                    ),
                    value="web_schema_normalizer",
                ),
                questionary.Choice(
                    (
                        "Web HTML Text Extractor: "
                        f"{current_web_html_text_extractor}"
                    ),
                    value="web_html_text_extractor",
                ),
                questionary.Choice(
                    (
                        "Web Schema Policy: "
                        f"{current_web_schema_policy}"
                    ),
                    value="web_schema_policy",
                ),
                questionary.Choice(
                    (
                        "Web Schema Min Confidence: "
                        f"{float(current_settings.get('web_schema_min_confidence', 0.75)):.2f}"
                    ),
                    value="web_schema_min_confidence",
                ),
                questionary.Choice(
                    (
                        "Web Schema Min Ingredients: "
                        f"{current_settings.get('web_schema_min_ingredients', 2)}"
                    ),
                    value="web_schema_min_ingredients",
                ),
                questionary.Choice(
                    (
                        "Web Schema Min Instruction Steps: "
                        f"{current_settings.get('web_schema_min_instruction_steps', 1)}"
                    ),
                    value="web_schema_min_instruction_steps",
                ),
                questionary.Choice(
                    (
                        "Recipe Pipeline Default: "
                        f"{current_recipe_pipeline}"
                    ),
                    value="llm_recipe_pipeline",
                ),
                questionary.Choice(
                    (
                        "Knowledge Pipeline Default: "
                        f"{current_knowledge_pipeline}"
                    ),
                    value="llm_knowledge_pipeline",
                ),
                questionary.Choice(
                    f"Codex Farm Command: {current_codex_cmd}",
                    value="codex_farm_cmd",
                ),
                questionary.Choice(
                    f"Codex Farm Root: {current_codex_root}",
                    value="codex_farm_root",
                ),
                questionary.Choice(
                    f"Codex Farm Workspace Root: {current_codex_workspace_root}",
                    value="codex_farm_workspace_root",
                ),
                questionary.Choice(
                    f"Codex Farm Model Default: {current_codex_model}",
                    value="codex_farm_model",
                ),
                questionary.Choice(
                    (
                        "Codex Farm Reasoning Default: "
                        f"{current_codex_reasoning_effort}"
                    ),
                    value="codex_farm_reasoning_effort",
                ),
                questionary.Choice(
                    (
                        "Codex Farm Context Blocks: "
                        f"{current_settings.get('codex_farm_context_blocks', 30)}"
                    ),
                    value="codex_farm_context_blocks",
                ),
                questionary.Choice(
                    (
                        "Codex Farm Knowledge Context Blocks: "
                        f"{current_settings.get('codex_farm_knowledge_context_blocks', 0)}"
                    ),
                    value="codex_farm_knowledge_context_blocks",
                ),
                questionary.Choice(
                    f"Output Folder: {current_settings.get('output_dir', str(DEFAULT_INTERACTIVE_OUTPUT))} - stage artifacts",
                    value="output_dir",
                ),
                questionary.Choice(
                    f"PDF Pages/Job: {current_settings.get('pdf_pages_per_job', 50)} - split size per PDF task",
                    value="pdf_pages_per_job",
                ),
                questionary.Choice(
                    f"EPUB Spine Items/Job: {current_settings.get('epub_spine_items_per_job', 10)} - split size per EPUB task",
                    value="epub_spine_items_per_job",
                ),
                questionary.Choice(
                    f"Warm Models: {'Yes' if current_settings.get('warm_models', False) else 'No'} - preload heavy models",
                    value="warm_models",
                ),
                questionary.Choice(
                    f"Label Studio URL: {current_label_studio_url}",
                    value="label_studio_url",
                ),
                questionary.Choice(
                    f"Label Studio API Key: {current_label_studio_api_key_status}",
                    value="label_studio_api_key",
                ),
                questionary.Separator(),
                questionary.Choice("Back to Main Menu - return without changing anything", value="back"),
            ]
        )
        
        if choice in {"back", BACK_ACTION} or choice is None:
            break
            
        if choice == "workers":
            val = _prompt_text(
                "Enter number of workers:",
                default=str(current_settings.get("workers", 7)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["workers"] = int(val)
                _save_settings(current_settings)

        elif choice == "pdf_split_workers":
            val = _prompt_text(
                "Enter PDF split workers:",
                default=str(current_settings.get("pdf_split_workers", 7)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["pdf_split_workers"] = int(val)
                _save_settings(current_settings)

        elif choice == "epub_split_workers":
            val = _prompt_text(
                "Enter EPUB split workers:",
                default=str(current_settings.get("epub_split_workers", 7)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["epub_split_workers"] = int(val)
                _save_settings(current_settings)

        elif choice == ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method max parallel sources:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY,
                        fallback=_all_method_default_parallel_sources_from_cpu(),
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY:
            current_scope = _normalize_all_method_scheduler_scope(
                current_settings.get(ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY)
            )
            val = _menu_select(
                "Select all-method scheduler scope:",
                choices=[
                    questionary.Choice(
                        "global - one global config queue across all matched sources",
                        value=ALL_METHOD_SCHEDULER_SCOPE_GLOBAL,
                    ),
                ],
                default=current_scope,
                menu_help=(
                    "global shares split slots and eval-signature dedupe across the full "
                    "all-matched run."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings[ALL_METHOD_SCHEDULER_SCOPE_SETTING_KEY] = (
                    _normalize_all_method_scheduler_scope(val)
                )
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY:
            current_strategy = _normalize_all_method_source_scheduling(
                current_settings.get(ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY)
            )
            val = _menu_select(
                "Select all-method source scheduling strategy:",
                choices=[
                    questionary.Choice(
                        "tail_pair - interleave heavy/light planned jobs",
                        value=ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
                    ),
                    questionary.Choice(
                        "discovery - source discovery order",
                        value=ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY,
                    ),
                ],
                default=current_strategy,
                menu_help=(
                    "tail_pair starts heavy jobs earlier and alternates with lighter jobs "
                    "to reduce one-source endgame tails."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings[ALL_METHOD_SOURCE_SCHEDULING_SETTING_KEY] = (
                    _normalize_all_method_source_scheduling(val)
                )
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY:
            val = _prompt_text(
                "Enter source-sharding threshold in estimated seconds:",
                default=(
                    f"{_resolve_positive_float_setting(current_settings, key=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY, fallback=ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT):.1f}"
                ),
            )
            parsed = _coerce_positive_float(val)
            if parsed is not None:
                current_settings[ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY:
            val = _prompt_text(
                "Enter maximum shard parts per source:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY,
                        fallback=ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_SOURCE_SHARD_MAX_PARTS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY:
            val = _prompt_text(
                "Enter minimum variants required to allow source sharding:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY,
                        fallback=ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_MAX_INFLIGHT_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method max inflight pipelines:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_MAX_INFLIGHT_SETTING_KEY,
                        fallback=ALL_METHOD_MAX_INFLIGHT_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_INFLIGHT_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method max split-phase slots:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                        fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method max eval-tail pipelines (smart mode):",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY,
                        fallback=_resolve_positive_int_setting(
                            current_settings,
                            key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                            fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
                        ),
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method per-config timeout seconds (0 disables timeout):",
                default=str(
                    _resolve_non_negative_int_setting(
                        current_settings,
                        key=ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY,
                        fallback=ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_non_negative_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method failed-config retry count (0 disables retries):",
                default=str(
                    _resolve_non_negative_int_setting(
                        current_settings,
                        key=ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY,
                        fallback=ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_non_negative_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_WING_BACKLOG_SETTING_KEY:
            val = _prompt_text(
                "Enter all-method wing backlog target:",
                default=str(
                    _resolve_positive_int_setting(
                        current_settings,
                        key=ALL_METHOD_WING_BACKLOG_SETTING_KEY,
                        fallback=_resolve_positive_int_setting(
                            current_settings,
                            key=ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY,
                            fallback=ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
                        ),
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_WING_BACKLOG_SETTING_KEY] = parsed
                _save_settings(current_settings)

        elif choice == ALL_METHOD_SMART_SCHEDULER_SETTING_KEY:
            current_value = _coerce_bool_setting(
                current_settings.get(ALL_METHOD_SMART_SCHEDULER_SETTING_KEY),
                default=True,
            )
            val = _prompt_confirm(
                "Enable smart phase-aware all-method scheduler?",
                default=current_value,
            )
            if val is not None:
                current_settings[ALL_METHOD_SMART_SCHEDULER_SETTING_KEY] = bool(val)
                _save_settings(current_settings)

        elif choice == "epub_extractor":
            val = _menu_select(
                "Select EPUB extraction engine:",
                choices=list(enabled_epub_extractors),
                default=current_epub_extractor,
                menu_help=(
                    "Unstructured uses semantic HTML partitioning for richer block extraction. "
                    "BeautifulSoup uses tag-based parsing. "
                    f"Markdown extractors are policy-locked off unless {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_extractor"] = val
                _save_settings(current_settings)

        elif choice == "epub_unstructured_html_parser_version":
            val = _menu_select(
                "Select Unstructured HTML parser version:",
                choices=["v1", "v2"],
                default=current_settings.get(
                    "epub_unstructured_html_parser_version",
                    "v1",
                ),
                menu_help=(
                    "Choose Unstructured partition_html parser version for EPUB extraction."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_unstructured_html_parser_version"] = val
                _save_settings(current_settings)

        elif choice == "epub_unstructured_skip_headers_footers":
            val = _prompt_confirm(
                "Skip headers/footers in Unstructured HTML partitioning?",
                default=bool(
                    current_settings.get(
                        "epub_unstructured_skip_headers_footers",
                        True,
                    )
                ),
            )
            if val is not None:
                current_settings["epub_unstructured_skip_headers_footers"] = bool(val)
                _save_settings(current_settings)

        elif choice == "epub_unstructured_preprocess_mode":
            val = _menu_select(
                "Select EPUB HTML preprocess mode before Unstructured:",
                choices=["none", "br_split_v1"],
                default=current_settings.get(
                    "epub_unstructured_preprocess_mode",
                    "br_split_v1",
                ),
                menu_help=(
                    "none keeps raw HTML; br_split_v1 splits BR-separated paragraphs "
                    "into block tags."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_unstructured_preprocess_mode"] = val
                _save_settings(current_settings)

        elif choice == "pdf_ocr_policy":
            val = _menu_select(
                "Select PDF OCR policy:",
                choices=[
                    questionary.Choice("off - never run OCR", value="off"),
                    questionary.Choice(
                        "auto - OCR only when text extraction needs it",
                        value="auto",
                    ),
                    questionary.Choice("always - force OCR for PDFs", value="always"),
                ],
                default=current_pdf_ocr_policy,
                menu_help=(
                    "Choose how PDF imports decide between native text extraction "
                    "and OCR."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["pdf_ocr_policy"] = _normalize_pdf_ocr_policy(str(val))
                _save_settings(current_settings)

        elif choice == "web_schema_extractor":
            val = _menu_select(
                "Select web schema extractor:",
                choices=[
                    "builtin_jsonld",
                    "extruct",
                    "scrape_schema_recipe",
                    "recipe_scrapers",
                    "ensemble_v1",
                ],
                default=current_web_schema_extractor,
                menu_help="Choose the structured-data extractor for webschema imports.",
            )
            if val and val != BACK_ACTION:
                current_settings["web_schema_extractor"] = _normalize_web_schema_extractor(
                    str(val)
                )
                _save_settings(current_settings)

        elif choice == "web_schema_normalizer":
            val = _menu_select(
                "Select web schema normalizer:",
                choices=["simple", "pyld"],
                default=current_web_schema_normalizer,
                menu_help="Choose schema normalization before mapping.",
            )
            if val and val != BACK_ACTION:
                current_settings["web_schema_normalizer"] = (
                    _normalize_web_schema_normalizer(str(val))
                )
                _save_settings(current_settings)

        elif choice == "web_html_text_extractor":
            val = _menu_select(
                "Select web HTML text extractor:",
                choices=[
                    "bs4",
                    "trafilatura",
                    "readability_lxml",
                    "justext",
                    "boilerpy3",
                    "ensemble_v1",
                ],
                default=current_web_html_text_extractor,
                menu_help="Choose the fallback text extractor when schema data is missing.",
            )
            if val and val != BACK_ACTION:
                current_settings["web_html_text_extractor"] = (
                    _normalize_web_html_text_extractor(str(val))
                )
                _save_settings(current_settings)

        elif choice == "web_schema_policy":
            val = _menu_select(
                "Select web schema policy:",
                choices=list(ALL_METHOD_WEBSCHEMA_POLICIES),
                default=current_web_schema_policy,
                menu_help=(
                    "prefer_schema uses schema first, schema_only disables heuristic "
                    "fallback, heuristic_only skips schema data."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["web_schema_policy"] = _normalize_web_schema_policy(
                    str(val)
                )
                _save_settings(current_settings)

        elif choice == "web_schema_min_confidence":
            val = _prompt_text(
                "Enter web schema minimum confidence (0.0 to 1.0):",
                default=str(current_settings.get("web_schema_min_confidence", 0.75)),
            )
            parsed = _coerce_float_between(val, minimum=0.0, maximum=1.0)
            if parsed is not None:
                current_settings["web_schema_min_confidence"] = parsed
                _save_settings(current_settings)

        elif choice == "web_schema_min_ingredients":
            val = _prompt_text(
                "Enter minimum ingredient lines for web schema acceptance:",
                default=str(current_settings.get("web_schema_min_ingredients", 2)),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings["web_schema_min_ingredients"] = parsed
                _save_settings(current_settings)

        elif choice == "web_schema_min_instruction_steps":
            val = _prompt_text(
                "Enter minimum instruction steps for web schema acceptance:",
                default=str(current_settings.get("web_schema_min_instruction_steps", 1)),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings["web_schema_min_instruction_steps"] = parsed
                _save_settings(current_settings)

        elif choice == "llm_recipe_pipeline":
            val = _menu_select(
                "Select default recipe pipeline for interactive runs:",
                choices=[
                    questionary.Choice(
                        "off - default to deterministic/vanilla top-tier",
                        value="off",
                    ),
                    questionary.Choice(
                        f"{RECIPE_CODEX_FARM_PIPELINE_SHARD_V1} - default to CodexFarm top-tier",
                        value=RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
                    ),
                ],
                default=current_recipe_pipeline,
                menu_help=(
                    "This sets the default choice shown by the per-run interactive "
                    "top-tier picker."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["llm_recipe_pipeline"] = _normalize_llm_recipe_pipeline(
                    str(val)
                )
                _save_settings(current_settings)

        elif choice == "llm_knowledge_pipeline":
            val = _menu_select(
                "Select default knowledge pipeline for interactive runs:",
                choices=[
                    questionary.Choice("off", value="off"),
                    questionary.Choice(
                        KNOWLEDGE_CODEX_PIPELINE_SHARD_V1,
                        value=KNOWLEDGE_CODEX_PIPELINE_SHARD_V1,
                    ),
                ],
                default=current_knowledge_pipeline,
                menu_help=(
                    "This becomes the default knowledge-harvest choice when the "
                    "interactive benchmark flow asks for per-run Codex surfaces."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["llm_knowledge_pipeline"] = (
                    _normalize_llm_knowledge_pipeline(str(val))
                )
                _save_settings(current_settings)

        elif choice == "codex_farm_cmd":
            val = _prompt_text(
                "Enter Codex Farm command:",
                default=current_codex_cmd,
            )
            if val is not None:
                current_settings["codex_farm_cmd"] = str(val).strip() or "codex-farm"
                _save_settings(current_settings)

        elif choice == "codex_farm_root":
            val = _prompt_text(
                "Enter Codex Farm root path (blank to use repo default):",
                default=str(current_settings.get("codex_farm_root") or ""),
            )
            if val is not None:
                current_settings["codex_farm_root"] = str(val).strip() or None
                _save_settings(current_settings)

        elif choice == "codex_farm_workspace_root":
            val = _prompt_text(
                "Enter Codex Farm workspace root (blank to use pipeline default):",
                default=str(current_settings.get("codex_farm_workspace_root") or ""),
            )
            if val is not None:
                current_settings["codex_farm_workspace_root"] = str(val).strip() or None
                _save_settings(current_settings)

        elif choice == "codex_farm_model":
            val = _prompt_text(
                "Enter Codex Farm model default (blank for pipeline default):",
                default=str(current_settings.get("codex_farm_model") or ""),
            )
            if val is not None:
                current_settings["codex_farm_model"] = str(val).strip() or None
                _save_settings(current_settings)

        elif choice == "codex_farm_reasoning_effort":
            reasoning_choices, reasoning_default = build_codex_farm_reasoning_effort_choices(
                selected_model=str(current_settings.get("codex_farm_model") or "").strip() or None,
                selected_effort=current_settings.get("codex_farm_reasoning_effort"),
                supported_efforts_by_model={},
                include_minimal=True,
            )
            reasoning_choices = [
                questionary.Choice("Pipeline default", value="__default__"),
                *[
                    choice
                    for choice in reasoning_choices
                    if str(choice.value) != "__default__"
                ],
            ]
            val = _menu_select(
                "Select Codex Farm reasoning default:",
                choices=reasoning_choices,
                default=reasoning_default,
                menu_help=(
                    "Choose the saved default reasoning effort for Codex-backed runs. "
                    "Pipeline default leaves the pack default in control."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["codex_farm_reasoning_effort"] = (
                    None if str(val) == "__default__" else str(val)
                )
                _save_settings(current_settings)

        elif choice == "codex_farm_context_blocks":
            val = _prompt_text(
                "Enter Codex Farm context blocks:",
                default=str(current_settings.get("codex_farm_context_blocks", 30)),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings["codex_farm_context_blocks"] = parsed
                _save_settings(current_settings)

        elif choice == "codex_farm_knowledge_context_blocks":
            val = _prompt_text(
                "Enter Codex Farm knowledge context blocks:",
                default=str(
                    current_settings.get("codex_farm_knowledge_context_blocks", 1)
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings["codex_farm_knowledge_context_blocks"] = parsed
                _save_settings(current_settings)

        elif choice == "output_dir":
            val = _prompt_text(
                "Enter output folder for interactive runs:",
                default=str(current_settings.get("output_dir", str(DEFAULT_INTERACTIVE_OUTPUT))),
            )
            if val:
                current_settings["output_dir"] = str(Path(val).expanduser())
                _save_settings(current_settings)

        elif choice == "pdf_pages_per_job":
            val = _prompt_text(
                "Enter PDF pages per job:",
                default=str(current_settings.get("pdf_pages_per_job", 50)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["pdf_pages_per_job"] = int(val)
                _save_settings(current_settings)

        elif choice == "epub_spine_items_per_job":
            val = _prompt_text(
                "Enter EPUB spine items per job:",
                default=str(current_settings.get("epub_spine_items_per_job", 10)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["epub_spine_items_per_job"] = int(val)
                _save_settings(current_settings)

        elif choice == "warm_models":
            val = _prompt_confirm(
                "Warm models on start?",
                default=current_settings.get("warm_models", False),
            )
            if val is not None:
                current_settings["warm_models"] = val
                _save_settings(current_settings)

        elif choice == "label_studio_url":
            val = _prompt_text(
                "Enter Label Studio URL (blank clears saved value):",
                default=str(current_settings.get("label_studio_url") or ""),
            )
            if val is not None:
                current_settings["label_studio_url"] = str(val).strip()
                _save_settings(current_settings)

        elif choice == "label_studio_api_key":
            val = _prompt_password(
                "Enter Label Studio API key (blank keeps current, __clear__ clears):",
                default="",
            )
            if val is not None:
                cleaned = str(val).strip()
                if cleaned == "__clear__":
                    current_settings["label_studio_api_key"] = ""
                    _save_settings(current_settings)
                elif cleaned:
                    current_settings["label_studio_api_key"] = cleaned
                    _save_settings(current_settings)


def _interactive_all_method_benchmark(
    *,
    selected_benchmark_settings: RunSettings,
    benchmark_eval_output: Path,
    processed_output_root: Path,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    scheduler_scope: str | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool | None = None,
) -> None:
    scope_choice = _menu_select(
        "Select all method benchmark scope:",
        menu_help=(
            "Choose one gold/source pair (current behavior) or fan out "
            "across all freeform gold exports that match importable data/input files."
        ),
        choices=[
            questionary.Choice("Single golden set", value="single"),
            questionary.Choice(
                "All golden sets with matching input files",
                value="all_matched",
            ),
        ],
    )
    if scope_choice in {None, BACK_ACTION}:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return

    scope_all_matched = scope_choice == "all_matched"
    if scope_all_matched:
        targets, unmatched_targets = _resolve_all_method_targets(DEFAULT_GOLDEN)
        if not targets:
            typer.secho(
                "No matched golden sets were found in data/input. Nothing to benchmark.",
                fg=typer.colors.YELLOW,
            )
            if unmatched_targets:
                typer.secho(
                    f"Skipped golden sets: {len(unmatched_targets)}",
                    fg=typer.colors.YELLOW,
                )
                for unmatched in unmatched_targets[:5]:
                    source_hint_text = unmatched.source_hint or "none"
                    typer.echo(
                        f"  - {unmatched.gold_display}: {unmatched.reason} "
                        f"(source hint: {source_hint_text})"
                    )
                if len(unmatched_targets) > 5:
                    typer.echo(
                        f"  - ... {len(unmatched_targets) - 5} additional skipped golden sets"
                    )
            return
    else:
        resolved_inputs = _resolve_benchmark_gold_and_source(
            gold_spans=None,
            source_file=None,
            output_dir=DEFAULT_GOLDEN,
            allow_cancel=True,
        )
        if resolved_inputs is None:
            return
        selected_gold, selected_source = resolved_inputs
        targets = [
            AllMethodTarget(
                gold_spans_path=selected_gold,
                source_file=selected_source,
                source_file_name=selected_source.name,
                gold_display=_display_gold_export_path(selected_gold, DEFAULT_GOLDEN),
            )
        ]
        unmatched_targets = []

    include_markdown_extractors = _resolve_all_method_markdown_extractors_choice()
    include_deterministic_sweeps = _prompt_confirm(
        (
            "Try deterministic option sweeps too? (section detector, multi-recipe splitting, "
            "ingredient missing-unit policy, instruction step segmentation, time/temp/yield)"
        ),
        default=True,
    )
    if include_deterministic_sweeps is None:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return
    if include_deterministic_sweeps:
        missing: list[str] = []
        if not _all_method_optional_module_available("pysbd"):
            missing.append("pysbd (instruction step segmenter)")
        if not _all_method_optional_module_available("quantulum3"):
            missing.append("quantulum3 (time/temp backends)")
        if not _all_method_optional_module_available("pint"):
            missing.append("pint (temperature units)")
        if missing:
            typer.secho(
                "Deterministic sweeps note: optional deps missing, some variants will be skipped: "
                + ", ".join(missing),
                fg=typer.colors.BRIGHT_BLACK,
            )
    base_target_variants = _build_all_method_target_variants(
        targets=targets,
        base_settings=selected_benchmark_settings,
        include_codex_farm=False,
        include_markdown_extractors=include_markdown_extractors,
        include_deterministic_sweeps=bool(include_deterministic_sweeps),
    )
    total_base_runs = sum(len(variants) for _target, variants in base_target_variants)
    if total_base_runs <= 0:
        typer.secho("No benchmark variants were generated for this selection.", fg=typer.colors.YELLOW)
        return

    if include_markdown_extractors:
        typer.secho(
            (
                "All method includes markdown + markitdown extractor variants "
                f"(enabled via {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 and "
                f"{ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1)."
            ),
            fg=typer.colors.YELLOW,
        )
    else:
        if markdown_epub_extractors_enabled():
            typer.secho(
                (
                    "All method excludes markdown + markitdown extractor variants by default. "
                    f"Set {ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1 to include them."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )
        else:
            typer.secho(
                (
                    "Markdown + markitdown extractors are policy-locked off. "
                    f"Set {EPUB_EXTRACTOR_ENABLE_MARKDOWN_ENV}=1 to temporarily re-enable "
                    "them, then set "
                    f"{ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV}=1 to include them in all method."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )

    if scope_all_matched:
        typer.secho(
            f"Matched golden sets: {len(targets)}",
            fg=typer.colors.CYAN,
        )
        skipped_color = typer.colors.YELLOW if unmatched_targets else typer.colors.BRIGHT_BLACK
        typer.secho(
            f"Skipped golden sets: {len(unmatched_targets)}",
            fg=skipped_color,
        )
        typer.secho(
            (
                "All method benchmark will run "
                f"{total_base_runs} configurations across {len(targets)} matched golden sets "
                "(Codex Farm excluded)."
            ),
            fg=typer.colors.CYAN,
        )
        if unmatched_targets:
            typer.secho("Skipped golden set samples:", fg=typer.colors.BRIGHT_BLACK)
            for unmatched in unmatched_targets[:5]:
                source_hint_text = unmatched.source_hint or "none"
                typer.echo(
                    f"  - {unmatched.gold_display}: {unmatched.reason} "
                    f"(source hint: {source_hint_text})"
                )
            if len(unmatched_targets) > 5:
                typer.echo(
                    f"  - ... {len(unmatched_targets) - 5} additional skipped golden sets"
                )
    else:
        selected_source = targets[0].source_file
        typer.secho(
            f"All method benchmark will run {total_base_runs} configurations (Codex Farm excluded).",
            fg=typer.colors.CYAN,
        )
        if selected_source.suffix.lower() == ".epub":
            typer.secho(
                (
                    "Dimensions: epub_extractor + unstructured parser/skip_headers/preprocess, "
                    "plus deterministic option sweeps when enabled."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )
        else:
            typer.secho(
                "Dimensions: non-EPUB source uses global benchmark run settings (plus sweeps when enabled).",
                fg=typer.colors.BRIGHT_BLACK,
            )
    typer.secho(
        "CodexFarm process selection is available for all-method runs.",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.secho(
        "All method benchmark uses canonical-text eval mode (extractor-independent).",
        fg=typer.colors.BRIGHT_BLACK,
    )

    all_method_codex_defaults_payload = {
        key: value
        for key, value in selected_benchmark_settings.model_dump(
            mode="json", exclude_none=True
        ).items()
        if key in RunSettings.model_fields
    }
    all_method_codex_defaults_payload.update(
        {
            "llm_recipe_pipeline": RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
            "line_role_pipeline": LINE_ROLE_PIPELINE_SHARD_V1,
            "llm_knowledge_pipeline": KNOWLEDGE_CODEX_PIPELINE_SHARD_V1,
            "atomic_block_splitter": str(
                all_method_codex_defaults_payload.get("atomic_block_splitter") or "off"
            ),
        }
    )
    all_method_codex_settings = choose_interactive_codex_surfaces(
        selected_settings=RunSettings.from_dict(
            all_method_codex_defaults_payload,
            warn_context="interactive all-method codex defaults",
        ),
        back_action=BACK_ACTION,
        surface_options=("recipe", "line_role", "knowledge"),
        prompt_text=_prompt_text,
    )
    if all_method_codex_settings is None:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return
    include_codex_requested = _all_method_settings_enable_any_codex(
        all_method_codex_settings
    )
    include_codex_effective, codex_warning = _resolve_all_method_codex_choice(
        include_codex_requested
    )
    if codex_warning:
        typer.secho(codex_warning, fg=typer.colors.YELLOW)

    benchmark_settings_for_variants = selected_benchmark_settings
    if include_codex_effective:
        _ensure_codex_farm_cmd_available(selected_benchmark_settings.codex_farm_cmd)
        all_method_codex_settings = choose_codex_ai_settings(
            selected_settings=all_method_codex_settings,
            menu_select=_menu_select,
            back_action=BACK_ACTION,
        )
        if all_method_codex_settings is None:
            typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
            return
        benchmark_settings_for_variants = all_method_codex_settings

    selected_target_variants = _build_all_method_target_variants(
        targets=targets,
        base_settings=benchmark_settings_for_variants,
        include_codex_farm=include_codex_effective,
        codex_variant_settings=(
            benchmark_settings_for_variants if include_codex_effective else None
        ),
        include_markdown_extractors=include_markdown_extractors,
        include_deterministic_sweeps=bool(include_deterministic_sweeps),
    )
    total_selected_runs = sum(
        len(variants) for _target, variants in selected_target_variants
    )
    if total_selected_runs <= 0:
        typer.secho("No benchmark variants were generated for this selection.", fg=typer.colors.YELLOW)
        return
    total_sources_selected = max(1, len(selected_target_variants))
    source_parallelism_default = min(
        _all_method_default_parallel_sources_from_cpu(),
        total_sources_selected,
    )
    requested_source_parallelism = _report_count(max_parallel_sources)
    source_parallelism_configured = (
        requested_source_parallelism
        if requested_source_parallelism > 0
        else source_parallelism_default
    )
    source_parallelism_effective = _resolve_all_method_source_parallelism(
        total_sources=total_sources_selected,
        requested=max_parallel_sources,
    )
    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=total_selected_runs,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=source_parallelism_effective,
    )
    resolved_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    resolved_split_phase_slots = scheduler_runtime.split_phase_slots
    resolved_wing_backlog_target = scheduler_runtime.wing_backlog_target
    resolved_eval_tail_headroom_configured = (
        scheduler_runtime.eval_tail_headroom_configured
    )
    resolved_eval_tail_headroom_effective = (
        scheduler_runtime.eval_tail_headroom_effective
    )
    resolved_eval_tail_mode = scheduler_runtime.eval_tail_headroom_mode
    resolved_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    resolved_max_active_during_eval = scheduler_runtime.max_active_during_eval
    resolved_effective_inflight_pipelines = (
        scheduler_runtime.effective_inflight_pipelines
    )
    resolved_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    resolved_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    resolved_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )
    resolved_scheduler_scope = _normalize_all_method_scheduler_scope(scheduler_scope)
    resolved_source_scheduling = _normalize_all_method_source_scheduling(
        source_scheduling
    )
    resolved_source_shard_threshold_seconds = (
        _coerce_positive_float(source_shard_threshold_seconds)
        or ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
    )
    resolved_source_shard_max_parts = (
        _coerce_positive_int(source_shard_max_parts)
        or ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
    )
    resolved_source_shard_min_variants = (
        _coerce_positive_int(source_shard_min_variants)
        or ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
    )
    timeout_display = (
        f"{resolved_config_timeout_seconds}s"
        if resolved_config_timeout_seconds is not None
        else "off"
    )
    scheduler_mode = "smart" if resolved_smart_scheduler else "fixed"
    typer.secho(
        (
            "Scheduler: "
            f"scope={resolved_scheduler_scope}, "
            f"source parallel={source_parallelism_effective} "
            f"(configured {source_parallelism_configured}, "
            f"default {_all_method_default_parallel_sources_from_cpu()}), "
            f"source scheduling={resolved_source_scheduling}, "
            "source sharding threshold/max_parts/min_variants="
            f"{resolved_source_shard_threshold_seconds:.1f}/"
            f"{resolved_source_shard_max_parts}/"
            f"{resolved_source_shard_min_variants}, "
            f"mode={scheduler_mode}, "
            f"configured inflight={resolved_inflight_pipelines} "
            f"(default {ALL_METHOD_MAX_INFLIGHT_DEFAULT}), "
            f"effective inflight={resolved_effective_inflight_pipelines}, "
            f"split slots={resolved_split_phase_slots} "
            f"(default {ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT}), "
            f"eval headroom ({resolved_eval_tail_mode}) configured/effective="
            f"{resolved_eval_tail_headroom_configured}/"
            f"{resolved_eval_tail_headroom_effective}, "
            f"max active during eval={resolved_max_active_during_eval}, "
            f"cpu budget/source={resolved_cpu_budget_per_source}, "
            f"config timeout={timeout_display} "
            f"(default {ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT}s), "
            f"failed retries={resolved_retry_failed_configs} "
            f"(default {ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT}), "
            f"wing backlog={resolved_wing_backlog_target} "
            "(default split slots)"
        ),
        fg=typer.colors.BRIGHT_BLACK,
    )

    if scope_all_matched:
        proceed_prompt = (
            f"Proceed with {total_selected_runs} benchmark runs across "
            f"{len(targets)} matched golden sets?"
        )
    else:
        proceed_prompt = f"Proceed with {total_selected_runs} benchmark runs?"
    proceed = _prompt_confirm(
        proceed_prompt,
        default=False,
    )
    if proceed is not True:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return

    all_method_root = benchmark_eval_output / "all-method-benchmark"
    all_method_processed_root = (
        processed_output_root
        / benchmark_eval_output.name
        / "all-method-benchmark"
    )
    all_method_canonical_cache_root = _resolve_all_method_canonical_alignment_cache_root(
        root_output_dir=all_method_root
    )
    typer.secho(
        (
            "All method canonical alignment cache root: "
            f"{all_method_canonical_cache_root}"
        ),
        fg=typer.colors.BRIGHT_BLACK,
    )

    status_initial = "Running all method benchmark..."
    status_prefix = "All method benchmark"

    if scope_all_matched:
        dashboard = _AllMethodProgressDashboard.from_target_variants(
            selected_target_variants
        )
        report_md_path = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
            telemetry_path=all_method_root / PROCESSING_TIMESERIES_FILENAME,
            run=lambda update_progress: _run_all_method_benchmark_multi_source(
                target_variants=selected_target_variants,
                unmatched_targets=unmatched_targets,
                include_codex_farm_requested=include_codex_requested,
                include_codex_farm_effective=include_codex_effective,
                root_output_dir=all_method_root,
                processed_output_root=all_method_processed_root,
                overlap_threshold=0.5,
                force_source_match=False,
                progress_callback=update_progress,
                dashboard=dashboard,
                max_parallel_sources=max_parallel_sources,
                max_inflight_pipelines=resolved_inflight_pipelines,
                max_concurrent_split_phases=resolved_split_phase_slots,
                max_eval_tail_pipelines=max_eval_tail_pipelines,
                config_timeout_seconds=resolved_config_timeout_seconds,
                retry_failed_configs=resolved_retry_failed_configs,
                source_scheduling=resolved_source_scheduling,
                source_shard_threshold_seconds=resolved_source_shard_threshold_seconds,
                source_shard_max_parts=resolved_source_shard_max_parts,
                source_shard_min_variants=resolved_source_shard_min_variants,
                wing_backlog_target=resolved_wing_backlog_target,
                smart_scheduler=resolved_smart_scheduler,
                scheduler_scope=resolved_scheduler_scope,
                canonical_alignment_cache_root=all_method_canonical_cache_root,
                dashboard_output_root=processed_output_root,
            ),
        )
        typer.secho(
            f"All method benchmark summary report: {report_md_path}",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            f"All method processing telemetry: {all_method_root / PROCESSING_TIMESERIES_FILENAME}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    else:
        single_target = targets[0]
        single_variants = selected_target_variants[0][1]
        single_root = all_method_root / slugify_name(single_target.source_file.stem)
        single_processed_root = all_method_processed_root / slugify_name(
            single_target.source_file.stem
        )
        dashboard = _AllMethodProgressDashboard.from_target_variants(
            [(single_target, single_variants)]
        )

        def _run_single_source(update_progress: Callable[[str], None]) -> Path:
            dashboard.start_source(0)
            dashboard.set_task(f"Running source 1/1: {single_target.source_file_name}")
            update_progress(dashboard.render())
            try:
                report_path = _run_all_method_benchmark(
                    gold_spans_path=single_target.gold_spans_path,
                    source_file=single_target.source_file,
                    variants=single_variants,
                    include_codex_farm_requested=include_codex_requested,
                    include_codex_farm_effective=include_codex_effective,
                    root_output_dir=single_root,
                    processed_output_root=single_processed_root,
                    overlap_threshold=0.5,
                    force_source_match=False,
                    progress_callback=update_progress,
                    dashboard=dashboard,
                    dashboard_source_index=0,
                    max_inflight_pipelines=resolved_inflight_pipelines,
                    max_concurrent_split_phases=resolved_split_phase_slots,
                    max_eval_tail_pipelines=max_eval_tail_pipelines,
                    config_timeout_seconds=resolved_config_timeout_seconds,
                    retry_failed_configs=resolved_retry_failed_configs,
                    wing_backlog_target=resolved_wing_backlog_target,
                    smart_scheduler=resolved_smart_scheduler,
                    source_parallelism_effective=source_parallelism_effective,
                    canonical_alignment_cache_dir_override=(
                        all_method_canonical_cache_root
                        / slugify_name(single_target.source_file.stem)
                    ),
                    dashboard_output_root=processed_output_root,
                )
            except Exception:
                dashboard.finish_source(0, failed=True)
                dashboard.set_task("Source failed.")
                update_progress(dashboard.render())
                raise
            dashboard.finish_source(0, failed=False)
            dashboard.set_task("Source complete.")
            update_progress(dashboard.render())
            return report_path

        report_md_path = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
            telemetry_path=single_root / PROCESSING_TIMESERIES_FILENAME,
            run=_run_single_source,
        )
        typer.secho(f"All method benchmark report: {report_md_path}", fg=typer.colors.CYAN)
        typer.secho(
            f"All method processing telemetry: {single_root / PROCESSING_TIMESERIES_FILENAME}",
            fg=typer.colors.BRIGHT_BLACK,
        )

    typer.secho(
        f"All method processed outputs: {all_method_processed_root}",
        fg=typer.colors.CYAN,
    )


def _interactive_single_profile_all_matched_benchmark(
    *,
    selected_benchmark_settings: RunSettings,
    benchmark_eval_output: Path,
    processed_output_root: Path,
    write_markdown: bool,
    write_label_studio_tasks: bool,
    allow_subset_selection: bool = False,
) -> bool:
    """Run one benchmark profile across matched gold/source pairs."""

    def _friendly_single_profile_failure_reason(reason: object) -> str:
        text = str(reason or "").strip()
        if not text or "stderr_summary=" not in text:
            return text
        pipeline_match = re.search(r"codex-farm failed for (\S+)", text)
        pipeline_id = (
            str(pipeline_match.group(1)).strip() if pipeline_match is not None else None
        )
        summary = text.split("stderr_summary=", 1)[1].strip()
        if summary.endswith(")"):
            summary = summary[:-1].rstrip()
        if pipeline_id:
            return f"codex-farm {pipeline_id}: {summary}"
        return summary

    all_targets, unmatched_targets = _resolve_all_method_targets(DEFAULT_GOLDEN)
    if not all_targets:
        typer.secho(
            "No matched golden sets were found in data/input. Nothing to benchmark.",
            fg=typer.colors.YELLOW,
        )
        if unmatched_targets:
            typer.secho(
                f"Skipped golden sets: {len(unmatched_targets)}",
                fg=typer.colors.YELLOW,
            )
            for unmatched in unmatched_targets[:5]:
                source_hint_text = unmatched.source_hint or "none"
                typer.echo(
                    f"  - {unmatched.gold_display}: {unmatched.reason} "
                    f"(source hint: {source_hint_text})"
                )
            if len(unmatched_targets) > 5:
                typer.echo(
                    f"  - ... {len(unmatched_targets) - 5} additional skipped golden sets"
                )
        return False

    targets = list(all_targets)
    if allow_subset_selection and len(targets) > 1:
        selected_indices: set[int] = set()
        while True:
            selected_count = len(selected_indices)
            choices: list[Any] = [
                questionary.Choice("Run all matched books", value="__run_all__"),
            ]
            if selected_count > 0:
                choices.append(
                    questionary.Choice(
                        f"Run selected books ({selected_count})",
                        value="__run_selected__",
                    )
                )
            for index, target in enumerate(targets, start=1):
                target_index = index - 1
                marker = "x" if target_index in selected_indices else " "
                choices.append(
                    questionary.Choice(
                        f"[{marker}] {index:02d}) {_display_benchmark_target_name(gold_display=target.gold_display, source_file_name=target.source_file_name)}",
                        value=target_index,
                    )
                )

            selection = _menu_select(
                "Choose matched books for this single-profile benchmark:",
                menu_help=(
                    "Toggle book rows, then choose run selected books. "
                    "Or run all matched books directly."
                ),
                choices=choices,
            )
            if selection in {None, BACK_ACTION}:
                typer.secho("Single-profile benchmark cancelled.", fg=typer.colors.YELLOW)
                return False
            if selection == "__run_all__":
                break
            if selection == "__run_selected__":
                targets = [targets[i] for i in sorted(selected_indices)]
                break
            if not isinstance(selection, int):
                continue
            if selection < 0 or selection >= len(targets):
                continue
            if selection in selected_indices:
                selected_indices.remove(selection)
            else:
                selected_indices.add(selection)

    if not targets:
        typer.secho("No books selected. Single-profile benchmark cancelled.", fg=typer.colors.YELLOW)
        return False

    variants = _interactive_single_book_variants(selected_benchmark_settings)
    if not variants:
        typer.secho("No single-profile benchmark variants were planned.", fg=typer.colors.YELLOW)
        return False
    runs_per_target = len(variants)
    total_planned_runs = len(targets) * runs_per_target
    variant_labels = ", ".join(slug for slug, _settings in variants)

    typer.secho(
        f"Matched golden sets: {len(all_targets)}",
        fg=typer.colors.CYAN,
    )
    if allow_subset_selection:
        typer.secho(f"Selected matched books: {len(targets)}", fg=typer.colors.CYAN)
    typer.secho(
        f"Single-profile benchmark variants per book: {variant_labels}",
        fg=typer.colors.CYAN,
    )
    if runs_per_target > 1:
        typer.secho(
            "Codex selected: each book will run vanilla first, then codexfarm.",
            fg=typer.colors.BRIGHT_BLACK,
        )
    skipped_color = typer.colors.YELLOW if unmatched_targets else typer.colors.BRIGHT_BLACK
    typer.secho(
        f"Skipped golden sets: {len(unmatched_targets)}",
        fg=skipped_color,
    )
    scope_label = (
        "selected matched books"
        if allow_subset_selection
        else "matched golden sets"
    )
    typer.secho(
        (
            "Single-profile benchmark will run "
            f"{total_planned_runs} configurations across {len(targets)} {scope_label}."
        ),
        fg=typer.colors.CYAN,
    )
    if unmatched_targets:
        typer.secho("Skipped golden set samples:", fg=typer.colors.BRIGHT_BLACK)
        for unmatched in unmatched_targets[:5]:
            source_hint_text = unmatched.source_hint or "none"
            typer.echo(
                f"  - {unmatched.gold_display}: {unmatched.reason} "
                f"(source hint: {source_hint_text})"
            )
        if len(unmatched_targets) > 5:
            typer.echo(
                f"  - ... {len(unmatched_targets) - 5} additional skipped golden sets"
            )

    proceed = _prompt_confirm(
        (
            f"Proceed with {total_planned_runs} benchmark runs across "
            f"{len(targets)} {scope_label}?"
        ),
        default=False,
    )
    if proceed is not True:
        typer.secho("Single-profile benchmark cancelled.", fg=typer.colors.YELLOW)
        return False

    single_profile_root = benchmark_eval_output / "single-profile-benchmark"
    single_profile_processed_root = (
        processed_output_root
        / benchmark_eval_output.name
        / "single-profile-benchmark"
    )

    variant_call_defaults: dict[str, dict[str, Any]] = {}
    for variant_slug, variant_settings in variants:
        variant_call_defaults[variant_slug] = build_benchmark_call_kwargs_from_run_settings(
            variant_settings,
            output_dir=_golden_benchmark_root(),
            eval_output_dir=single_profile_root,
            eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
            no_upload=True,
            write_markdown=write_markdown,
            write_label_studio_tasks=write_label_studio_tasks,
        )
        variant_call_defaults[variant_slug]["allow_codex"] = codex_surfaces_enabled(
            variant_settings.to_run_config_dict()
        )

    failures: list[tuple[AllMethodTarget, str]] = []
    total_targets = len(targets)
    parallel_books_cap = 3
    worker_scale_numerator = 8
    worker_scale_denominator = 10
    max_parallel_targets = (
        min(parallel_books_cap, total_targets) if total_targets > 1 else 1
    )
    split_phase_slots: int | None = None
    split_phase_gate_dir: Path | None = None
    scaled_worker_overrides: dict[str, int] = {}
    status_initial = "Running single-profile benchmark..."
    status_prefix = "Single-profile benchmark"
    single_profile_dashboard: _SingleProfileProgressDashboard | None = None
    dashboard_emit_lock = threading.RLock()

    def _scale_parallel_workers(raw_value: Any) -> int:
        try:
            baseline = max(1, int(raw_value))
        except (TypeError, ValueError):
            baseline = 1
        return max(
            1, (baseline * worker_scale_numerator) // worker_scale_denominator
        )

    if max_parallel_targets > 1:
        split_phase_slots = 1
        split_phase_gate_dir = single_profile_root / ".split_phase_slots"
        split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
        single_profile_dashboard = _SingleProfileProgressDashboard(
            rows=[
                _SingleProfileBookDashboardRow(
                    source_name=target.source_file_name,
                    total_configs=max(1, runs_per_target),
                )
                for target in targets
            ],
            total_planned_configs=max(1, total_planned_runs),
        )
        scheduler_variant_slug = variants[0][0]
        scheduler_kwargs = variant_call_defaults.get(scheduler_variant_slug, {})
        for key in ("workers", "pdf_split_workers", "epub_split_workers"):
            scaled_worker_overrides[key] = _scale_parallel_workers(scheduler_kwargs.get(key))
        typer.secho(
            (
                "Single-profile scheduler: "
                f"parallel books={max_parallel_targets}, "
                "per-book worker scaling=80%, "
                "split conversion slots=1."
            ),
            fg=typer.colors.BRIGHT_BLACK,
        )

    def _emit_single_profile_dashboard(
        update_progress: Callable[[str], None] | None,
        *,
        task_message: str | None = None,
    ) -> None:
        if update_progress is None or single_profile_dashboard is None:
            return
        with dashboard_emit_lock:
            update_progress(single_profile_dashboard.render())

    def _run_single_profile_target(
        index: int,
        target: AllMethodTarget,
        update_progress: Callable[[str], None] | None = None,
    ) -> tuple[AllMethodTarget, str | None, Path | None, Path | None]:
        target_slug = f"{index:02d}_{slugify_name(target.source_file.stem)}"
        target_eval_output = single_profile_root / target_slug
        target_processed_output = single_profile_processed_root / target_slug
        source_index = index - 1
        variant_eval_outputs: dict[str, Path] = {}
        variant_errors: list[str] = []
        source_file_for_comparison: str | None = None
        if single_profile_dashboard is not None:
            single_profile_dashboard.start_source(source_index)
            _emit_single_profile_dashboard(
                update_progress,
                task_message=(
                    f"{format_task_counter('Running', index, max(1, total_targets), noun='book')}: "
                    f"{target.source_file_name}"
                ),
            )

        def _finish_source_progress(*, failed: bool, status: str) -> None:
            if single_profile_dashboard is None:
                return
            single_profile_dashboard.finish_source(source_index, failed=failed)
            _emit_single_profile_dashboard(update_progress, task_message=status)

        for variant_index, (variant_slug, _variant_settings) in enumerate(
            variants, start=1
        ):
            variant_kwargs = dict(variant_call_defaults.get(variant_slug, {}))
            variant_eval_output = (
                target_eval_output / variant_slug
                if runs_per_target > 1
                else target_eval_output
            )
            variant_processed_output = (
                target_processed_output / variant_slug
                if runs_per_target > 1
                else target_processed_output
            )
            variant_kwargs.update(
                {
                    "gold_spans": target.gold_spans_path,
                    "source_file": target.source_file,
                    "eval_output_dir": variant_eval_output,
                    "processed_output_dir": variant_processed_output,
                }
            )
            if scaled_worker_overrides:
                variant_kwargs.update(scaled_worker_overrides)
            if single_profile_dashboard is not None:
                single_profile_dashboard.start_config(
                    source_index=source_index,
                    config_index=variant_index,
                    config_total=max(1, runs_per_target),
                    config_slug=variant_slug,
                )
                _emit_single_profile_dashboard(
                    update_progress,
                    task_message=(
                        f"{format_task_counter('Running', variant_index, max(1, runs_per_target), noun='variant')} "
                        f"({variant_slug}) | book {index}/{max(1, total_targets)}: {target.source_file_name}"
                    ),
                )
            split_status_label = None
            if split_phase_slots is not None:
                split_status_label = (
                    f"Single-profile split gate {index}/{total_targets}: "
                    f"{target.source_file_name}"
                )
                if runs_per_target > 1:
                    split_status_label = (
                        f"Single-profile split gate {index}/{total_targets} "
                        f"variant {variant_index}/{runs_per_target} "
                        f"({variant_slug}): {target.source_file_name}"
                    )

            def _variant_progress(message: str) -> None:
                cleaned = str(message or "").strip()
                if not cleaned:
                    return
                if single_profile_dashboard is not None:
                    single_profile_dashboard.ingest_progress(
                        source_index=source_index,
                        message=cleaned,
                    )
                _emit_single_profile_dashboard(
                    update_progress,
                )

            try:
                with _benchmark_split_phase_overrides(
                    split_phase_slots=split_phase_slots,
                    split_phase_gate_dir=split_phase_gate_dir,
                    split_phase_status_label=split_status_label,
                ):
                    with _benchmark_progress_overrides(
                        progress_callback=(
                            _variant_progress if single_profile_dashboard is not None else None
                        ),
                        suppress_summary=single_profile_dashboard is not None,
                        suppress_spinner=single_profile_dashboard is not None,
                        suppress_dashboard_refresh=single_profile_dashboard is not None,
                        live_status_slots=(
                            None
                            if single_profile_dashboard is not None
                            else (2 if max_parallel_targets > 1 else None)
                        ),
                    ):
                        labelstudio_benchmark(**variant_kwargs)
                variant_eval_outputs[variant_slug] = variant_eval_output
                source_file = _load_single_book_source_path(variant_eval_output)
                if source_file and not source_file_for_comparison:
                    source_file_for_comparison = source_file
                if single_profile_dashboard is not None:
                    single_profile_dashboard.complete_config(
                        source_index=source_index,
                        success=True,
                        config_index=variant_index,
                    )
                    _emit_single_profile_dashboard(
                        update_progress,
                        task_message=(
                            f"Completed {format_task_counter('', variant_index, max(1, runs_per_target), noun='variant')} "
                            f"({variant_slug}) | book {index}/{max(1, total_targets)}: {target.source_file_name}"
                        ),
                    )
            except typer.Exit as exc:
                exit_code = int(getattr(exc, "exit_code", 1))
                variant_errors.append(f"{variant_slug}=exit code {exit_code}")
                if single_profile_dashboard is not None:
                    single_profile_dashboard.complete_config(
                        source_index=source_index,
                        success=False,
                        config_index=variant_index,
                    )
                    _emit_single_profile_dashboard(
                        update_progress,
                        task_message=(
                            f"Failed {format_task_counter('', variant_index, max(1, runs_per_target), noun='variant')} "
                            f"({variant_slug}) | book {index}/{max(1, total_targets)}: "
                            f"{target.source_file_name} (exit code {exit_code})"
                        ),
                    )
            except Exception as exc:  # noqa: BLE001
                formatted_error = _friendly_single_profile_failure_reason(exc)
                variant_errors.append(f"{variant_slug}={formatted_error}")
                if single_profile_dashboard is not None:
                    single_profile_dashboard.complete_config(
                        source_index=source_index,
                        success=False,
                        config_index=variant_index,
                    )
                    _emit_single_profile_dashboard(
                        update_progress,
                        task_message=(
                            f"Failed {format_task_counter('', variant_index, max(1, runs_per_target), noun='variant')} "
                            f"({variant_slug}) | book {index}/{max(1, total_targets)}: "
                            f"{target.source_file_name} ({formatted_error})"
                        ),
                    )

        comparison_json_path: Path | None = None
        if (
            runs_per_target > 1
            and "vanilla" in variant_eval_outputs
            and "codexfarm" in variant_eval_outputs
        ):
            comparison_paths = _write_single_book_comparison_artifacts(
                run_timestamp=benchmark_eval_output.name,
                session_root=target_eval_output,
                source_file=source_file_for_comparison or str(target.source_file),
                codex_eval_output_dir=variant_eval_outputs["codexfarm"],
                vanilla_eval_output_dir=variant_eval_outputs["vanilla"],
                write_markdown=write_markdown,
                write_starter_pack=False,
            )
            if comparison_paths is not None:
                comparison_json_path = comparison_paths[0]

        try:
            upload_bundle_dir = _write_benchmark_upload_bundle(
                source_root=target_eval_output,
                output_dir=target_eval_output / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
                suppress_summary=False,
            )
        except typer.Exit as exc:
            exit_code = int(getattr(exc, "exit_code", 1))
            reason = "; ".join(variant_errors) if variant_errors else ""
            failure_reason = reason.strip()
            if failure_reason:
                failure_reason += "; "
            failure_reason += f"upload bundle exit code {exit_code}"
            _finish_source_progress(
                failed=True,
                status=(
                    f"Failed {format_task_counter('', index, max(1, total_targets), noun='book')}: "
                    f"{target.source_file_name}"
                ),
            )
            return target, failure_reason, None, comparison_json_path
        except Exception as exc:  # noqa: BLE001
            reason = "; ".join(variant_errors) if variant_errors else ""
            failure_reason = reason.strip()
            if failure_reason:
                failure_reason += "; "
            failure_reason += f"upload bundle error: {exc}"
            _finish_source_progress(
                failed=True,
                status=(
                    f"Failed {format_task_counter('', index, max(1, total_targets), noun='book')}: "
                    f"{target.source_file_name}"
                ),
            )
            return target, failure_reason, None, comparison_json_path

        failure_reason = "; ".join(variant_errors) if variant_errors else None
        _finish_source_progress(
            failed=failure_reason is not None,
            status=(
                f"{'Failed' if failure_reason is not None else 'Completed'} "
                f"{format_task_counter('', index, max(1, total_targets), noun='book')}: "
                f"{target.source_file_name}"
            ),
        )
        return target, failure_reason, upload_bundle_dir, comparison_json_path

    target_index_pairs = list(enumerate(targets, start=1))
    for index, target in target_index_pairs:
        typer.secho(
            (
                f"Single-profile benchmark {index}/{total_targets}: "
                f"{target.source_file_name}"
                f"{' (vanilla + codexfarm)' if runs_per_target > 1 else ''}"
            ),
            fg=typer.colors.CYAN,
        )

    if max_parallel_targets == 1:
        completed_results = [
            _run_single_profile_target(index, target)
            for index, target in target_index_pairs
        ]
    else:
        def _run_parallel_targets_with_shared_status(
            update_progress: Callable[[str], None],
        ) -> list[tuple[AllMethodTarget, str | None, Path | None, Path | None]]:
            _emit_single_profile_dashboard(
                update_progress,
                task_message=(
                    f"Queued {format_task_counter('', 0, max(1, total_targets), noun='book')}"
                ),
            )
            completed: list[
                tuple[AllMethodTarget, str | None, Path | None, Path | None]
            ] = []
            with ThreadPoolExecutor(max_workers=max_parallel_targets) as executor:
                futures = [
                    executor.submit(
                        _run_single_profile_target,
                        index,
                        target,
                        update_progress,
                    )
                    for index, target in target_index_pairs
                ]
                for future in as_completed(futures):
                    completed.append(future.result())
            return completed

        completed_results = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
            telemetry_path=single_profile_root / PROCESSING_TIMESERIES_FILENAME,
            run=_run_parallel_targets_with_shared_status,
        )

    for target, failure_reason, upload_bundle_dir, comparison_json_path in completed_results:
        if upload_bundle_dir is not None:
            typer.secho(
                f"External-AI upload bundle: {upload_bundle_dir}",
                fg=typer.colors.CYAN,
            )
        if comparison_json_path is not None:
            typer.secho(
                f"Codex-vs-vanilla comparison: {comparison_json_path}",
                fg=typer.colors.CYAN,
            )
        if failure_reason is None:
            continue
        failures.append((target, failure_reason))
        typer.secho(
            (
                f"Single-profile benchmark failed for "
                f"{target.source_file_name}: {failure_reason}; continuing."
            ),
            fg=typer.colors.YELLOW,
        )

    if total_targets > 1:
        group_upload_bundle_dir = _write_benchmark_upload_bundle(
            source_root=single_profile_root,
            output_dir=single_profile_root / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
            suppress_summary=False,
            high_level_only=True,
            target_bundle_size_bytes=BENCHMARK_GROUP_UPLOAD_BUNDLE_TARGET_BYTES,
        )
        if group_upload_bundle_dir is not None:
            typer.secho(
                f"External-AI group upload bundle: {group_upload_bundle_dir}",
                fg=typer.colors.CYAN,
            )
            _start_benchmark_bundle_oracle_upload_background(
                bundle_dir=group_upload_bundle_dir,
                scope="single_profile_group",
            )

    if single_profile_dashboard is not None:
        history_csv_path = history_csv_for_output(
            single_profile_processed_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
        )
        _refresh_dashboard_after_history_write(
            csv_path=history_csv_path,
            output_root=processed_output_root,
            dashboard_out_dir=history_root_for_output(processed_output_root) / "dashboard",
            reason="single-profile benchmark variant batch append",
        )

    succeeded = total_targets - len(failures)
    summary_color = typer.colors.GREEN if not failures else typer.colors.YELLOW
    typer.secho(
        (
            "Single-profile all-matched benchmark complete: "
            f"{succeeded}/{total_targets} succeeded."
        ),
        fg=summary_color,
    )
    typer.secho(
        f"Single-profile benchmark outputs: {single_profile_root}",
        fg=typer.colors.CYAN,
    )
    typer.secho(
        f"Single-profile processed outputs: {single_profile_processed_root}",
        fg=typer.colors.CYAN,
    )
    if failures:
        typer.secho("Failed golden set samples:", fg=typer.colors.YELLOW)
        for failed_target, reason in failures[:5]:
            typer.echo(
                f"  - {failed_target.gold_display}: {reason} "
                f"(source: {failed_target.source_file_name})"
            )
        if len(failures) > 5:
            typer.echo(f"  - ... {len(failures) - 5} additional failures")
    return True


def _interactive_single_book_variants(
    selected_benchmark_settings: RunSettings,
) -> list[tuple[str, RunSettings]]:
    run_config = project_run_config_payload(
        selected_benchmark_settings.to_run_config_dict(),
        contract=RUN_SETTING_CONTRACT_FULL,
    )
    current_pipeline = str(run_config.get("llm_recipe_pipeline") or "off").strip().lower()
    if current_pipeline != "off":
        baseline_payload = _all_method_apply_baseline_contract(run_config)
        shared_atomic_block_splitter = _normalize_atomic_block_splitter(
            str(
                run_config.get("atomic_block_splitter")
                or baseline_payload.get("atomic_block_splitter")
                or "off"
            )
        )
        baseline_payload["atomic_block_splitter"] = shared_atomic_block_splitter
        codex_payload = _all_method_apply_codex_contract_from_baseline(
            baseline_payload
        )
        codex_payload["llm_recipe_pipeline"] = current_pipeline
        codex_payload["atomic_block_splitter"] = shared_atomic_block_splitter
        return [
            (
                "vanilla",
                RunSettings.from_dict(
                    baseline_payload,
                    warn_context="interactive benchmark vanilla variant",
                ),
            ),
            (
                "codexfarm",
                RunSettings.from_dict(
                    codex_payload,
                    warn_context="interactive benchmark codexfarm variant",
                ),
            ),
        ]
    return [
        (
            _single_book_variant_slug(selected_benchmark_settings),
            selected_benchmark_settings,
        )
    ]


def _single_book_variant_slug(settings: RunSettings) -> str:
    run_config = settings.to_run_config_dict()
    recipe_pipeline = str(run_config.get("llm_recipe_pipeline") or "off").strip().lower()
    line_role_pipeline = str(run_config.get("line_role_pipeline") or "off").strip().lower()
    if recipe_pipeline == "off" and line_role_pipeline in {"off", "deterministic-v1", "deterministic"}:
        return "vanilla"
    if recipe_pipeline == "off":
        return "line_role_only"
    if line_role_pipeline == "off":
        return "recipe_only"
    return "full_stack"


def _all_method_apply_baseline_contract(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return apply_benchmark_baseline_contract(payload)


def _all_method_apply_codex_contract_from_baseline(
    baseline_payload: dict[str, Any],
) -> dict[str, Any]:
    return apply_benchmark_codex_contract_from_baseline(baseline_payload)


def _all_method_apply_selected_codex_contract_from_baseline(
    baseline_payload: dict[str, Any],
    *,
    codex_variant_settings: RunSettings,
) -> dict[str, Any]:
    codex_payload = dict(baseline_payload)
    codex_config = codex_variant_settings.to_run_config_dict()
    for key in (
        "llm_recipe_pipeline",
        "llm_knowledge_pipeline",
        "line_role_pipeline",
        "atomic_block_splitter",
        "codex_farm_model",
        "codex_farm_reasoning_effort",
    ):
        if key in codex_config:
            codex_payload[key] = codex_config[key]
    return codex_payload


INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK = "single_book"
INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS = "selected_matched_books"
INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS = "all_matched_books"


def _all_method_codex_surface_slug_parts(
    codex_variant_settings: RunSettings,
) -> list[str]:
    parts: list[str] = []
    recipe_pipeline = codex_variant_settings.llm_recipe_pipeline.value
    if recipe_pipeline != "off":
        parts.append(f"llm_recipe_{_all_method_variant_token(recipe_pipeline)}")
    if codex_variant_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_SHARD_V1:
        parts.append(
            f"line_role_{_all_method_variant_token(codex_variant_settings.line_role_pipeline.value)}"
        )
    knowledge_pipeline = codex_variant_settings.llm_knowledge_pipeline.value
    if knowledge_pipeline != "off":
        parts.append(
            f"llm_knowledge_{_all_method_variant_token(knowledge_pipeline)}"
        )
    return parts


def _all_method_settings_enable_any_codex(
    codex_variant_settings: RunSettings | None,
) -> bool:
    if codex_variant_settings is None:
        return False
    return any(
        (
            codex_variant_settings.llm_recipe_pipeline.value != "off",
            codex_variant_settings.line_role_pipeline.value == LINE_ROLE_PIPELINE_SHARD_V1,
            codex_variant_settings.llm_knowledge_pipeline.value != "off",
        )
    )


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_single_book_eval_metrics(
    eval_output_dir: Path,
) -> dict[str, float | None] | None:
    eval_report = _load_json_dict(eval_output_dir / "eval_report.json")
    if eval_report is None:
        return None
    return _single_book_eval_metrics_from_report(eval_report)


def _single_book_eval_metrics_from_report(
    eval_report: dict[str, Any],
) -> dict[str, float | None]:
    return {
        metric_name: _benchmark_report_metric_value(eval_report, metric_name)
        for metric_name, _display_name in SINGLE_BOOK_COMPARISON_METRICS
    }


def _build_single_book_per_label_breakdown(
    *,
    run_timestamp: str,
    eval_reports: Iterable[dict[str, Any] | None],
) -> dict[str, Any] | None:
    by_label: dict[str, dict[str, Any]] = {}
    eval_count = 0
    for eval_report in eval_reports:
        if not isinstance(eval_report, dict):
            continue
        per_label_payload = eval_report.get("per_label")
        if not isinstance(per_label_payload, dict) or not per_label_payload:
            continue
        eval_count += 1
        for label_name, label_metrics_payload in per_label_payload.items():
            if not isinstance(label_metrics_payload, dict):
                continue
            label = str(label_name or "").strip()
            if not label:
                continue
            aggregate = by_label.setdefault(
                label,
                {
                    "label": label,
                    "gold_total": 0.0,
                    "pred_total": 0.0,
                    "tp_from_recall": 0.0,
                    "tp_from_precision": 0.0,
                    "has_gold": False,
                    "has_pred": False,
                },
            )
            gold_total = _report_optional_metric(label_metrics_payload.get("gold_total"))
            pred_total = _report_optional_metric(label_metrics_payload.get("pred_total"))
            recall = _report_optional_metric(label_metrics_payload.get("recall"))
            precision = _report_optional_metric(label_metrics_payload.get("precision"))

            if gold_total is not None:
                aggregate["gold_total"] += gold_total
                aggregate["has_gold"] = True
                if recall is not None:
                    aggregate["tp_from_recall"] += recall * gold_total
            if pred_total is not None:
                aggregate["pred_total"] += pred_total
                aggregate["has_pred"] = True
                if precision is not None:
                    aggregate["tp_from_precision"] += precision * pred_total

    if not by_label:
        return None

    rows: list[dict[str, Any]] = []
    for label in sorted(by_label):
        aggregate = by_label[label]
        gold_total = aggregate["gold_total"] if aggregate["has_gold"] else None
        pred_total = aggregate["pred_total"] if aggregate["has_pred"] else None
        tp: float | None = None
        if aggregate["has_gold"] and aggregate["has_pred"]:
            tp = (aggregate["tp_from_recall"] + aggregate["tp_from_precision"]) / 2.0
        elif aggregate["has_gold"]:
            tp = aggregate["tp_from_recall"]
        elif aggregate["has_pred"]:
            tp = aggregate["tp_from_precision"]

        precision: float | None = None
        if pred_total is not None:
            precision = tp / pred_total if pred_total > 0 and tp is not None else 0.0
        recall: float | None = None
        if gold_total is not None:
            recall = tp / gold_total if gold_total > 0 and tp is not None else 0.0

        def _count_value(raw_value: float | None) -> int | float | None:
            if raw_value is None:
                return None
            rounded = round(raw_value)
            if abs(raw_value - rounded) <= 1e-9:
                return int(rounded)
            return raw_value

        rows.append(
            {
                "label": label,
                "precision": precision,
                "recall": recall,
                "gold_total": _count_value(gold_total),
                "pred_total": _count_value(pred_total),
            }
        )

    return {
        "schema_version": SINGLE_BOOK_PER_LABEL_BREAKDOWN_SCHEMA_VERSION,
        "run_timestamp": run_timestamp,
        "eval_count": eval_count,
        "rows": rows,
    }


def _single_book_display_metric_value(
    metrics: dict[str, Any] | None,
    metric_name: str,
) -> float | None:
    if not isinstance(metrics, dict):
        return None
    if metric_name == "strict_accuracy":
        for key in (
            "strict_accuracy",
            "overall_line_accuracy",
            "overall_block_accuracy",
            "accuracy",
        ):
            value = _report_optional_metric(metrics.get(key))
            if value is not None:
                return value
        precision = _report_optional_metric(metrics.get("precision"))
        recall = _report_optional_metric(metrics.get("recall"))
        f1 = _report_optional_metric(metrics.get("f1"))
        equal_pr = (
            precision is not None
            and recall is not None
            and abs(precision - recall) <= 1e-9
        )
        equal_rf = (
            recall is not None
            and f1 is not None
            and abs(recall - f1) <= 1e-9
        )
        equal_pf = (
            precision is not None
            and f1 is not None
            and abs(precision - f1) <= 1e-9
        )
        if equal_pr and equal_rf and equal_pf:
            return precision
        return None
    if metric_name == "macro_f1_excluding_other":
        return _report_optional_metric(metrics.get("macro_f1_excluding_other"))
    return _report_optional_metric(metrics.get(metric_name))


def _benchmark_report_metric_value(
    metrics: dict[str, Any] | None,
    metric_name: str,
) -> float | None:
    return _single_book_display_metric_value(metrics, metric_name)


def _benchmark_report_metric_bundle(
    metrics: dict[str, Any] | None,
) -> dict[str, float]:
    metrics_payload = metrics or {}
    strict_accuracy_raw = _benchmark_report_metric_value(metrics, "strict_accuracy")
    macro_f1_raw = _benchmark_report_metric_value(metrics, "macro_f1_excluding_other")
    has_explicit_strict_metric = any(
        _report_optional_metric(metrics_payload.get(key)) is not None
        for key in (
            "strict_accuracy",
            "overall_line_accuracy",
            "overall_block_accuracy",
            "accuracy",
        )
    )

    if has_explicit_strict_metric and strict_accuracy_raw is not None:
        precision = strict_accuracy_raw
        recall = strict_accuracy_raw
        f1 = strict_accuracy_raw
    else:
        precision = _report_metric(_report_optional_metric(metrics_payload.get("precision")))
        recall = _report_metric(_report_optional_metric(metrics_payload.get("recall")))
        f1_raw = _report_optional_metric(metrics_payload.get("f1"))
        if f1_raw is None and (precision + recall) > 0:
            f1_raw = (2.0 * precision * recall) / (precision + recall)
        f1 = _report_metric(f1_raw)
        strict_accuracy_raw = f1_raw

    has_explicit_macro_metric = (
        _report_optional_metric(metrics_payload.get("macro_f1_excluding_other"))
        is not None
    )
    if has_explicit_macro_metric and macro_f1_raw is not None:
        practical_precision = macro_f1_raw
        practical_recall = macro_f1_raw
        practical_f1 = macro_f1_raw
    else:
        practical_precision = _report_metric(_report_optional_metric(metrics_payload.get("practical_precision")))
        practical_recall = _report_metric(_report_optional_metric(metrics_payload.get("practical_recall")))
        practical_f1_raw = _report_optional_metric(metrics_payload.get("practical_f1"))
        if practical_f1_raw is None and (practical_precision + practical_recall) > 0:
            practical_f1_raw = (
                2.0 * practical_precision * practical_recall
            ) / (practical_precision + practical_recall)
        practical_f1 = _report_metric(practical_f1_raw)
        macro_f1_raw = practical_f1_raw

    strict_accuracy = _report_metric(strict_accuracy_raw)
    macro_f1 = _report_metric(macro_f1_raw)
    return {
        "strict_accuracy": strict_accuracy,
        "macro_f1_excluding_other": macro_f1,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "practical_precision": practical_precision,
        "practical_recall": practical_recall,
        "practical_f1": practical_f1,
    }


def _load_single_book_source_path(eval_output_dir: Path) -> str | None:
    manifest_payload = _load_json_dict(eval_output_dir / "run_manifest.json")
    if not isinstance(manifest_payload, dict):
        return None
    source_payload = manifest_payload.get("source")
    if not isinstance(source_payload, dict):
        return None
    source_path = str(source_payload.get("path") or "").strip()
    return source_path or None


def _load_single_book_split_cache_metadata(
    eval_output_dir: Path,
) -> dict[str, Any] | None:
    manifest_payload = _load_json_dict(eval_output_dir / "run_manifest.json")
    if not isinstance(manifest_payload, dict):
        return None
    run_config_payload = manifest_payload.get("run_config")
    if not isinstance(run_config_payload, dict):
        return None
    split_cache_payload = run_config_payload.get("single_book_split_cache")
    if isinstance(split_cache_payload, dict):
        return dict(split_cache_payload)
    return None


def _single_book_text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _resolve_single_book_reasoning_effort(
    effort: str | None,
    *,
    codex_cmd: str | None,
    codex_model: str | None = None,
) -> str | None:
    normalized_effort = _single_book_text_or_none(effort)
    if normalized_effort is None:
        return default_codex_reasoning_effort_for_model(
            codex_model,
            cmd=codex_cmd,
        )
    if normalized_effort.lower() in {"<default>", "default"}:
        return default_codex_reasoning_effort(
            cmd=codex_cmd
        ) or default_codex_reasoning_effort_for_model(
            codex_model,
            cmd=codex_cmd,
        )
    try:
        return normalize_codex_reasoning_effort(normalized_effort)
    except ValueError:
        return normalized_effort


def _find_single_book_llm_manifest_path(
    prediction_run_dir: Path,
) -> Path | None:
    prediction_manifest = _load_json_dict(prediction_run_dir / "run_manifest.json")
    if isinstance(prediction_manifest, dict):
        prediction_artifacts = prediction_manifest.get("artifacts")
        if isinstance(prediction_artifacts, dict):
            candidate = _resolve_artifact_path(
                prediction_run_dir,
                prediction_artifacts.get("recipe_manifest_json"),
            )
            if candidate is not None and candidate.exists() and candidate.is_file():
                return candidate

    raw_llm_root = prediction_run_dir / "raw" / "llm"
    if not raw_llm_root.exists() or not raw_llm_root.is_dir():
        return None
    for run_dir in sorted(raw_llm_root.iterdir(), key=lambda path: path.name):
        if not run_dir.is_dir():
            continue
        candidate = run_dir / RECIPE_MANIFEST_FILE_NAME
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _extract_codex_farm_runtime_from_llm_manifest(
    llm_manifest: dict[str, Any],
) -> tuple[str | None, str | None]:
    model = _single_book_text_or_none(llm_manifest.get("codex_farm_model"))
    reasoning_effort = _single_book_text_or_none(
        llm_manifest.get("codex_farm_reasoning_effort")
    )

    process_runs = llm_manifest.get("process_runs")
    if not isinstance(process_runs, dict):
        return model, reasoning_effort

    for pass_payload in process_runs.values():
        if not isinstance(pass_payload, dict):
            continue

        process_payload = pass_payload.get("process_payload")
        if isinstance(process_payload, dict):
            if model is None:
                model = _single_book_text_or_none(process_payload.get("codex_model"))
            if reasoning_effort is None:
                reasoning_effort = _single_book_text_or_none(
                    process_payload.get("codex_reasoning_effort")
                )

        if reasoning_effort is None:
            telemetry_report = pass_payload.get("telemetry_report")
            insights = (
                telemetry_report.get("insights")
                if isinstance(telemetry_report, dict)
                else None
            )
            breakdown_rows = (
                insights.get("model_reasoning_breakdown")
                if isinstance(insights, dict)
                else None
            )
            if isinstance(breakdown_rows, list):
                for row in breakdown_rows:
                    if not isinstance(row, dict):
                        continue
                    if model is None:
                        model = _single_book_text_or_none(row.get("model"))
                    candidate_reasoning = _single_book_text_or_none(
                        row.get("reasoning_effort")
                    )
                    if candidate_reasoning is not None:
                        reasoning_effort = candidate_reasoning
                        break

        if model is not None and reasoning_effort is not None:
            break

    return model, reasoning_effort


def _single_book_nonnegative_int_or_none(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = int(float(text))
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _extract_codex_farm_token_usage_from_process_run_payload(
    pass_payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    token_keys = (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    )
    process_payload = (
        pass_payload.get("process_payload")
        if isinstance(pass_payload.get("process_payload"), dict)
        else None
    )
    telemetry_payload = (
        process_payload.get("telemetry")
        if isinstance(process_payload, dict)
        and isinstance(process_payload.get("telemetry"), dict)
        else None
    )
    if telemetry_payload is None and isinstance(pass_payload.get("telemetry"), dict):
        telemetry_payload = pass_payload.get("telemetry")
    telemetry_rows = (
        telemetry_payload.get("rows")
        if isinstance(telemetry_payload, dict)
        and isinstance(telemetry_payload.get("rows"), list)
        else None
    )

    totals: dict[str, int | None] = {key: None for key in token_keys}
    if isinstance(telemetry_rows, list):
        for row in telemetry_rows:
            if not isinstance(row, dict):
                continue
            for key in token_keys:
                value = _single_book_nonnegative_int_or_none(row.get(key))
                if value is None:
                    continue
                current = totals.get(key)
                totals[key] = value if current is None else current + value

    telemetry_report = None
    if isinstance(process_payload, dict) and isinstance(
        process_payload.get("telemetry_report"), dict
    ):
        telemetry_report = process_payload.get("telemetry_report")
    elif isinstance(pass_payload.get("telemetry_report"), dict):
        telemetry_report = pass_payload.get("telemetry_report")
    summary_payload = (
        telemetry_report.get("summary")
        if isinstance(telemetry_report, dict)
        and isinstance(telemetry_report.get("summary"), dict)
        else None
    )
    if isinstance(summary_payload, dict):
        summary_value_map = {
            "tokens_input": summary_payload.get("tokens_input"),
            "tokens_cached_input": summary_payload.get("tokens_cached_input"),
            "tokens_output": summary_payload.get("tokens_output"),
            "tokens_reasoning": (
                summary_payload.get("tokens_reasoning")
                if summary_payload.get("tokens_reasoning") is not None
                else summary_payload.get("tokens_reasoning_total")
            ),
            "tokens_total": summary_payload.get("tokens_total"),
        }
        for key, raw_value in summary_value_map.items():
            if totals.get(key) is not None:
                continue
            parsed_value = _single_book_nonnegative_int_or_none(raw_value)
            if parsed_value is not None:
                totals[key] = parsed_value

    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _extract_codex_farm_token_usage_from_llm_manifest(
    llm_manifest: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    process_runs = llm_manifest.get("process_runs")
    if not isinstance(process_runs, dict):
        return _extract_codex_farm_token_usage_from_process_run_payload(llm_manifest)

    token_keys = (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    )
    totals: dict[str, int | None] = {key: None for key in token_keys}
    for pass_name in sorted(process_runs):
        pass_payload = process_runs.get(pass_name)
        if not isinstance(pass_payload, dict):
            continue
        (
            pass_tokens_input,
            pass_tokens_cached_input,
            pass_tokens_output,
            pass_tokens_reasoning,
            pass_tokens_total,
        ) = _extract_codex_farm_token_usage_from_process_run_payload(pass_payload)
        for key, value in (
            ("tokens_input", pass_tokens_input),
            ("tokens_cached_input", pass_tokens_cached_input),
            ("tokens_output", pass_tokens_output),
            ("tokens_reasoning", pass_tokens_reasoning),
            ("tokens_total", pass_tokens_total),
        ):
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    knowledge_payload = llm_manifest.get("knowledge")
    knowledge_tokens = (None, None, None, None, None)
    if isinstance(knowledge_payload, dict):
        process_run_payload = knowledge_payload.get("process_run")
        if isinstance(process_run_payload, dict):
            knowledge_tokens = _extract_codex_farm_token_usage_from_process_run_payload(
                process_run_payload
            )
        if all(value is None for value in knowledge_tokens):
            knowledge_tokens = _extract_codex_farm_token_usage_from_process_run_payload(
                knowledge_payload
            )
    for key, value in zip(token_keys, knowledge_tokens):
        if value is None:
            continue
        current = totals.get(key)
        totals[key] = value if current is None else current + value
    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _append_single_book_summary_payload(
    summary: dict[str, Any],
    summaries: list[dict[str, Any]],
    seen: set[int],
) -> None:
    summary_id = id(summary)
    if summary_id in seen:
        return
    seen.add(summary_id)
    summaries.append(summary)


def _collect_single_book_summary_payloads(
    payload: Any,
    summaries: list[dict[str, Any]],
    seen: set[int],
) -> None:
    if isinstance(payload, dict):
        summary = payload.get("summary")
        if isinstance(summary, dict):
            _append_single_book_summary_payload(summary, summaries, seen)
        telemetry_report = payload.get("telemetry_report")
        if isinstance(telemetry_report, dict):
            nested_summary = telemetry_report.get("summary")
            if isinstance(nested_summary, dict):
                _append_single_book_summary_payload(nested_summary, summaries, seen)
        for value in payload.values():
            _collect_single_book_summary_payloads(value, summaries, seen)
    elif isinstance(payload, list):
        for value in payload:
            _collect_single_book_summary_payloads(value, summaries, seen)


def _single_book_token_usage_from_summary_payloads(
    summaries: list[dict[str, Any]],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    token_keys = (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    )
    totals: dict[str, int | None] = {key: None for key in token_keys}
    for summary in summaries:
        for key in token_keys:
            raw_value = summary.get(key)
            if key == "tokens_reasoning" and raw_value is None:
                raw_value = summary.get("tokens_reasoning_total")
            value = _single_book_nonnegative_int_or_none(raw_value)
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _single_book_line_role_summaries_from_attempts(
    telemetry_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    batches = telemetry_payload.get("batches")
    if not isinstance(batches, list):
        return summaries
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        attempts = batch.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            process_run = attempt.get("process_run")
            if isinstance(process_run, dict):
                process_payload = process_run.get("process_payload")
                if isinstance(process_payload, dict):
                    telemetry_report = process_payload.get("telemetry_report")
                    if (
                        isinstance(telemetry_report, dict)
                        and isinstance(telemetry_report.get("summary"), dict)
                    ):
                        summaries.append(telemetry_report.get("summary"))
                        continue
                telemetry_report = process_run.get("telemetry_report")
                if (
                    isinstance(telemetry_report, dict)
                    and isinstance(telemetry_report.get("summary"), dict)
                ):
                    summaries.append(telemetry_report.get("summary"))
                    continue
            telemetry_report = attempt.get("telemetry_report")
            if (
                isinstance(telemetry_report, dict)
                and isinstance(telemetry_report.get("summary"), dict)
            ):
                summaries.append(telemetry_report.get("summary"))
    return summaries


def _extract_line_role_token_usage_from_manifest(
    payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    for telemetry_path in _line_role_telemetry_candidate_paths(payload):
        telemetry_payload = _load_json_dict(telemetry_path)
        if not isinstance(telemetry_payload, dict):
            continue
        summary = telemetry_payload.get("summary")
        direct_tokens = (
            _single_book_nonnegative_int_or_none(summary.get("tokens_input"))
            if isinstance(summary, dict)
            else None,
            _single_book_nonnegative_int_or_none(summary.get("tokens_cached_input"))
            if isinstance(summary, dict)
            else None,
            _single_book_nonnegative_int_or_none(summary.get("tokens_output"))
            if isinstance(summary, dict)
            else None,
            _single_book_nonnegative_int_or_none(summary.get("tokens_reasoning"))
            if isinstance(summary, dict)
            else None,
            _single_book_nonnegative_int_or_none(summary.get("tokens_total"))
            if isinstance(summary, dict)
            else None,
        )
        nested_summaries = _single_book_line_role_summaries_from_attempts(
            telemetry_payload
        )
        fallback_tokens = _single_book_token_usage_from_summary_payloads(
            nested_summaries
        )
        summary_looks_incomplete = False
        if isinstance(summary, dict):
            direct_has_positive_usage = any(
                value is not None and value > 0 for value in direct_tokens
            )
            attempts_without_usage = _single_book_nonnegative_int_or_none(
                summary.get("attempts_without_usage")
            )
            visible_input_tokens = _single_book_nonnegative_int_or_none(
                summary.get("visible_input_tokens")
            )
            visible_output_tokens = _single_book_nonnegative_int_or_none(
                summary.get("visible_output_tokens")
            )
            command_execution_count_total = _single_book_nonnegative_int_or_none(
                summary.get("command_execution_count_total")
            )
            summary_looks_incomplete = bool(
                (attempts_without_usage is not None and attempts_without_usage > 0)
                or (
                    not direct_has_positive_usage
                    and any(
                        value is not None and value > 0
                        for value in (
                            visible_input_tokens,
                            visible_output_tokens,
                            command_execution_count_total,
                        )
                    )
                )
            )
        if summary_looks_incomplete:
            return (None, None, None, None, None)
        resolved_tokens = tuple(
            direct if direct is not None else fallback
            for direct, fallback in zip(direct_tokens, fallback_tokens)
        )
        if any(value is not None for value in resolved_tokens):
            return resolved_tokens
    return (None, None, None, None, None)


def _line_role_telemetry_candidate_paths(payload: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _append_candidate(raw_path: Any) -> None:
        text = str(raw_path or "").strip()
        if not text:
            return
        candidate = Path(text)
        if candidate in seen:
            return
        seen.add(candidate)
        candidates.append(candidate)

    _append_candidate(payload.get("line_role_pipeline_telemetry_path"))
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        _append_candidate(artifacts.get("line_role_pipeline_telemetry_json"))
    for root_key in ("processed_run_root", "stage_run_root"):
        root_value = str(payload.get(root_key) or "").strip()
        if not root_value:
            continue
        _append_candidate(Path(root_value) / "line-role-pipeline" / "telemetry_summary.json")
    return [candidate for candidate in candidates if candidate.is_file()]


def _sum_token_usage(
    *token_sets: tuple[int | None, int | None, int | None, int | None, int | None],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    keys = (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    )
    totals: dict[str, int | None] = {key: None for key in keys}
    for token_values in token_sets:
        for key, value in zip(keys, token_values):
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _load_single_book_codex_farm_runtime(
    eval_output_dir: Path,
) -> dict[str, Any] | None:
    manifest_payload = _load_json_dict(eval_output_dir / "run_manifest.json")
    if not isinstance(manifest_payload, dict):
        return None

    run_config_payload = manifest_payload.get("run_config")
    if not isinstance(run_config_payload, dict):
        run_config_payload = {}

    codex_cmd = _single_book_text_or_none(run_config_payload.get("codex_farm_cmd"))
    codex_model = _single_book_text_or_none(
        run_config_payload.get("codex_farm_model")
    ) or _single_book_text_or_none(run_config_payload.get("codex_model"))
    codex_reasoning_effort = _resolve_single_book_reasoning_effort(
        run_config_payload.get("codex_farm_reasoning_effort")
        or run_config_payload.get("codex_reasoning_effort"),
        codex_cmd=codex_cmd,
        codex_model=codex_model,
    )

    artifacts_payload = manifest_payload.get("artifacts")
    prediction_run_dir: Path | None = None
    if isinstance(artifacts_payload, dict):
        prediction_run_dir = _resolve_artifact_path(
            eval_output_dir,
            artifacts_payload.get("artifact_root_dir"),
        )
    if prediction_run_dir is None:
        prediction_run_dir = eval_output_dir

    llm_manifest = None
    if prediction_run_dir.exists() and prediction_run_dir.is_dir():
        llm_manifest_path = _find_single_book_llm_manifest_path(prediction_run_dir)
        if llm_manifest_path is not None:
            llm_manifest = _load_json_dict(llm_manifest_path)
    if isinstance(llm_manifest, dict):
        inferred_model, inferred_reasoning_effort = (
            _extract_codex_farm_runtime_from_llm_manifest(llm_manifest)
        )
        if codex_model is None:
            codex_model = inferred_model
        if codex_reasoning_effort is None:
            codex_reasoning_effort = _resolve_single_book_reasoning_effort(
                inferred_reasoning_effort,
                codex_cmd=codex_cmd,
                codex_model=codex_model,
            )

    if codex_model is None and codex_reasoning_effort is None:
        return None
    return {
        "codex_model": codex_model,
        "codex_reasoning_effort": codex_reasoning_effort,
    }


def _resolve_single_book_split_cache_root(
    *,
    session_root: Path,
    split_cache_dir: Path | None,
) -> Path:
    if split_cache_dir is not None:
        return split_cache_dir.expanduser()
    env_override = str(os.getenv(SINGLE_BOOK_SPLIT_CACHE_ROOT_ENV, "") or "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return session_root / ".split-cache"


def _single_book_split_cache_summary(
    *,
    vanilla_metadata: dict[str, Any] | None,
    codex_metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    variant_rows: dict[str, dict[str, Any]] = {}
    for variant_slug, payload in (
        ("vanilla", vanilla_metadata),
        ("codexfarm", codex_metadata),
    ):
        if not isinstance(payload, dict):
            continue
        variant_rows[variant_slug] = {
            "enabled": bool(payload.get("enabled")),
            "mode": str(payload.get("mode") or "").strip() or "off",
            "key": str(payload.get("key") or "").strip() or None,
            "hit": bool(payload.get("hit")),
            "force": bool(payload.get("force")),
            "source_hash": str(payload.get("source_hash") or "").strip() or None,
            "conversion_seconds": _report_optional_metric(
                payload.get("conversion_seconds")
            ),
        }
    if not variant_rows:
        return None
    shared_key: str | None = None
    if "vanilla" in variant_rows and "codexfarm" in variant_rows:
        vanilla_key = str(variant_rows["vanilla"].get("key") or "").strip()
        codex_key = str(variant_rows["codexfarm"].get("key") or "").strip()
        if vanilla_key and vanilla_key == codex_key:
            shared_key = vanilla_key
    return {
        "schema_version": SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION,
        "shared_key": shared_key,
        "variants": variant_rows,
    }


def _single_book_metric_deltas(
    *,
    codex_metrics: dict[str, float | None],
    vanilla_metrics: dict[str, float | None],
) -> dict[str, float | None]:
    deltas: dict[str, float | None] = {}
    for metric_name, _display_name in SINGLE_BOOK_COMPARISON_METRICS:
        codex_value = _benchmark_report_metric_value(codex_metrics, metric_name)
        vanilla_value = _benchmark_report_metric_value(vanilla_metrics, metric_name)
        if codex_value is None or vanilla_value is None:
            deltas[metric_name] = None
        else:
            deltas[metric_name] = codex_value - vanilla_value
    return deltas


def _single_book_optional_delta(
    candidate: float | int | None,
    baseline: float | int | None,
) -> float | None:
    if candidate is None or baseline is None:
        return None
    return float(candidate) - float(baseline)


def _single_book_eval_segmentation_summary(
    eval_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(eval_report, dict):
        return {
            "available": False,
            "unavailable_reason": "eval_report_unavailable",
            "boundary_f1": None,
            "boundary_false_positive_count": None,
            "boundary_missed_count": None,
            "error_taxonomy_bucket_counts": {},
        }
    segmentation_payload = eval_report.get("segmentation")
    if not isinstance(segmentation_payload, dict):
        return {
            "available": False,
            "unavailable_reason": "segmentation_not_present_in_eval_report",
            "boundary_f1": None,
            "boundary_false_positive_count": None,
            "boundary_missed_count": None,
            "error_taxonomy_bucket_counts": {},
        }
    boundaries_payload = segmentation_payload.get("boundaries")
    overall_micro = (
        boundaries_payload.get("overall_micro")
        if isinstance(boundaries_payload, dict)
        else None
    )
    boundary_f1 = (
        _report_optional_metric(overall_micro.get("f1"))
        if isinstance(overall_micro, dict)
        else None
    )
    boundary_false_positive_count = (
        _single_book_nonnegative_int_or_none(overall_micro.get("fp"))
        if isinstance(overall_micro, dict)
        else None
    )
    boundary_missed_count = (
        _single_book_nonnegative_int_or_none(overall_micro.get("fn"))
        if isinstance(overall_micro, dict)
        else None
    )
    taxonomy_payload = segmentation_payload.get("error_taxonomy")
    bucket_counts_payload = (
        taxonomy_payload.get("bucket_counts")
        if isinstance(taxonomy_payload, dict)
        else None
    )
    bucket_counts: dict[str, int] = {}
    if isinstance(bucket_counts_payload, dict):
        for key, value in sorted(bucket_counts_payload.items()):
            name = str(key or "").strip()
            parsed = _single_book_nonnegative_int_or_none(value)
            if not name or parsed is None:
                continue
            bucket_counts[name] = parsed
    available = (
        boundary_f1 is not None
        or boundary_false_positive_count is not None
        or boundary_missed_count is not None
        or bool(bucket_counts)
    )
    if available:
        unavailable_reason: str | None = None
    else:
        unavailable_reason = "segmentation_metrics_missing"
    return {
        "available": bool(available),
        "unavailable_reason": unavailable_reason,
        "boundary_f1": boundary_f1,
        "boundary_false_positive_count": boundary_false_positive_count,
        "boundary_missed_count": boundary_missed_count,
        "error_taxonomy_bucket_counts": bucket_counts,
    }


def _single_book_eval_gold_adaptation_summary(
    eval_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(eval_report, dict):
        return {
            "applied": False,
            "mode": "off",
            "coverage_ratio": None,
            "ambiguous_gold_blocks": None,
            "unresolved_gold_blocks": None,
            "confidence_counts": {},
            "unavailable_reason": "eval_report_unavailable",
        }
    diagnostics_payload = eval_report.get("diagnostics")
    adaptation_payload = (
        diagnostics_payload.get("gold_adaptation")
        if isinstance(diagnostics_payload, dict)
        else None
    )
    if not isinstance(adaptation_payload, dict):
        return {
            "applied": False,
            "mode": "off",
            "coverage_ratio": None,
            "ambiguous_gold_blocks": None,
            "unresolved_gold_blocks": None,
            "confidence_counts": {},
            "unavailable_reason": "gold_adaptation_not_present_in_eval_report",
        }
    confidence_counts_payload = adaptation_payload.get("confidence_counts")
    confidence_counts: dict[str, int] = {}
    if isinstance(confidence_counts_payload, dict):
        for key, value in sorted(confidence_counts_payload.items()):
            name = str(key or "").strip()
            parsed = _single_book_nonnegative_int_or_none(value)
            if not name or parsed is None:
                continue
            confidence_counts[name] = parsed
    return {
        "applied": True,
        "mode": str(adaptation_payload.get("mode") or "auto").strip() or "auto",
        "coverage_ratio": _report_optional_metric(adaptation_payload.get("coverage_ratio")),
        "ambiguous_gold_blocks": _single_book_nonnegative_int_or_none(
            adaptation_payload.get("ambiguous_gold_blocks")
        ),
        "unresolved_gold_blocks": _single_book_nonnegative_int_or_none(
            adaptation_payload.get("unresolved_gold_blocks")
        ),
        "confidence_counts": confidence_counts,
        "unavailable_reason": None,
    }


def _build_single_book_variant_diagnostics(
    *,
    codex_eval_report: dict[str, Any] | None,
    vanilla_eval_report: dict[str, Any] | None,
) -> dict[str, Any]:
    variant_rows: dict[str, dict[str, Any]] = {}
    for variant_slug, eval_report in (
        ("vanilla", vanilla_eval_report),
        ("codexfarm", codex_eval_report),
    ):
        strict_accuracy = _benchmark_report_metric_value(
            eval_report if isinstance(eval_report, dict) else None,
            "strict_accuracy",
        )
        macro_f1 = _benchmark_report_metric_value(
            eval_report if isinstance(eval_report, dict) else None,
            "macro_f1_excluding_other",
        )
        classification_error_rate = (
            max(0.0, 1.0 - strict_accuracy) if strict_accuracy is not None else None
        )
        practical_error_rate = (
            max(0.0, 1.0 - macro_f1) if macro_f1 is not None else None
        )
        segmentation_summary = _single_book_eval_segmentation_summary(eval_report)
        boundary_f1 = _report_optional_metric(segmentation_summary.get("boundary_f1"))
        segmentation_boundary_error_rate = (
            max(0.0, 1.0 - boundary_f1) if boundary_f1 is not None else None
        )
        adaptation_summary = _single_book_eval_gold_adaptation_summary(eval_report)
        variant_rows[variant_slug] = {
            "strict_accuracy": strict_accuracy,
            "macro_f1_excluding_other": macro_f1,
            "classification_error_rate": classification_error_rate,
            "practical_error_rate": practical_error_rate,
            "segmentation": segmentation_summary,
            "segmentation_boundary_error_rate": segmentation_boundary_error_rate,
            "gold_adaptation": adaptation_summary,
        }

    codex_row = variant_rows.get("codexfarm") or {}
    vanilla_row = variant_rows.get("vanilla") or {}
    codex_seg = codex_row.get("segmentation")
    vanilla_seg = vanilla_row.get("segmentation")
    codex_adaptation = codex_row.get("gold_adaptation")
    vanilla_adaptation = vanilla_row.get("gold_adaptation")
    codex_confidence_counts = (
        codex_adaptation.get("confidence_counts")
        if isinstance(codex_adaptation, dict)
        and isinstance(codex_adaptation.get("confidence_counts"), dict)
        else {}
    )
    vanilla_confidence_counts = (
        vanilla_adaptation.get("confidence_counts")
        if isinstance(vanilla_adaptation, dict)
        and isinstance(vanilla_adaptation.get("confidence_counts"), dict)
        else {}
    )

    confidence_count_deltas: dict[str, int] = {}
    confidence_count_keys = sorted(
        set(str(key) for key in codex_confidence_counts.keys())
        | set(str(key) for key in vanilla_confidence_counts.keys())
    )
    for key in confidence_count_keys:
        codex_value = _single_book_nonnegative_int_or_none(
            codex_confidence_counts.get(key)
        )
        vanilla_value = _single_book_nonnegative_int_or_none(
            vanilla_confidence_counts.get(key)
        )
        if codex_value is None or vanilla_value is None:
            continue
        confidence_count_deltas[key] = codex_value - vanilla_value

    deltas: dict[str, Any] = {
        "classification_error_rate_delta": _single_book_optional_delta(
            codex_row.get("classification_error_rate"),
            vanilla_row.get("classification_error_rate"),
        ),
        "practical_error_rate_delta": _single_book_optional_delta(
            codex_row.get("practical_error_rate"),
            vanilla_row.get("practical_error_rate"),
        ),
        "segmentation_boundary_error_rate_delta": _single_book_optional_delta(
            codex_row.get("segmentation_boundary_error_rate"),
            vanilla_row.get("segmentation_boundary_error_rate"),
        ),
        "segmentation_boundary_f1_delta": _single_book_optional_delta(
            (
                codex_seg.get("boundary_f1")
                if isinstance(codex_seg, dict)
                else None
            ),
            (
                vanilla_seg.get("boundary_f1")
                if isinstance(vanilla_seg, dict)
                else None
            ),
        ),
        "gold_adaptation_coverage_ratio_delta": _single_book_optional_delta(
            (
                codex_adaptation.get("coverage_ratio")
                if isinstance(codex_adaptation, dict)
                else None
            ),
            (
                vanilla_adaptation.get("coverage_ratio")
                if isinstance(vanilla_adaptation, dict)
                else None
            ),
        ),
        "gold_adaptation_ambiguous_delta": _single_book_optional_delta(
            (
                codex_adaptation.get("ambiguous_gold_blocks")
                if isinstance(codex_adaptation, dict)
                else None
            ),
            (
                vanilla_adaptation.get("ambiguous_gold_blocks")
                if isinstance(vanilla_adaptation, dict)
                else None
            ),
        ),
        "gold_adaptation_unresolved_delta": _single_book_optional_delta(
            (
                codex_adaptation.get("unresolved_gold_blocks")
                if isinstance(codex_adaptation, dict)
                else None
            ),
            (
                vanilla_adaptation.get("unresolved_gold_blocks")
                if isinstance(vanilla_adaptation, dict)
                else None
            ),
        ),
        "gold_adaptation_confidence_count_deltas": confidence_count_deltas,
    }

    abs_classification_delta = (
        abs(float(deltas["classification_error_rate_delta"]))
        if deltas["classification_error_rate_delta"] is not None
        else None
    )
    abs_segmentation_delta = (
        abs(float(deltas["segmentation_boundary_error_rate_delta"]))
        if deltas["segmentation_boundary_error_rate_delta"] is not None
        else None
    )
    likely_driver = "insufficient_data"
    rationale = (
        "Segmentation boundary metrics were not available in one or both variant eval reports."
    )
    if abs_classification_delta is not None and abs_segmentation_delta is not None:
        if abs_classification_delta <= 1e-6 and abs_segmentation_delta <= 1e-6:
            likely_driver = "no_material_change"
            rationale = (
                "Both classification and segmentation error-rate deltas were near zero."
            )
        elif abs_segmentation_delta >= max(0.005, abs_classification_delta * 1.25):
            likely_driver = "segmentation_driven"
            rationale = (
                "Segmentation boundary error-rate delta dominated classification error-rate delta."
            )
        elif abs_classification_delta >= max(0.005, abs_segmentation_delta * 1.25):
            likely_driver = "classification_driven"
            rationale = (
                "Classification error-rate delta dominated segmentation boundary error-rate delta."
            )
        else:
            likely_driver = "mixed"
            rationale = (
                "Classification and segmentation deltas were both present and comparable in magnitude."
            )
    elif abs_classification_delta is not None:
        likely_driver = "classification_signal_only"
        rationale = (
            "Only classification deltas were available; segmentation deltas were unavailable."
        )
    elif abs_segmentation_delta is not None:
        likely_driver = "segmentation_signal_only"
        rationale = (
            "Only segmentation deltas were available; classification deltas were unavailable."
        )

    return {
        "schema_version": "single_book_variant_diagnostics.v1",
        "variants": variant_rows,
        "deltas": deltas,
        "likely_driver": likely_driver,
        "likely_driver_rationale": rationale,
    }


def _format_single_book_comparison_markdown(
    payload: dict[str, Any],
) -> str:
    run_timestamp = str(payload.get("run_timestamp") or "").strip() or "unknown"
    source_file = str(payload.get("source_file") or "").strip() or "unknown"

    variants_payload = payload.get("variants")
    if isinstance(variants_payload, dict):
        codex_dir = str(
            ((variants_payload.get("codexfarm") or {}).get("eval_output_dir"))
            or ""
        ).strip()
        vanilla_dir = str(
            ((variants_payload.get("vanilla") or {}).get("eval_output_dir"))
            or ""
        ).strip()
    else:
        codex_dir = ""
        vanilla_dir = ""

    metrics_payload = payload.get("metrics")
    if isinstance(metrics_payload, dict):
        codex_metrics = metrics_payload.get("codexfarm")
        vanilla_metrics = metrics_payload.get("vanilla")
    else:
        codex_metrics = None
        vanilla_metrics = None

    deltas_payload = payload.get("deltas")
    if isinstance(deltas_payload, dict):
        delta_metrics = deltas_payload.get("codex_minus_vanilla")
    else:
        delta_metrics = None
    metadata_payload = payload.get("metadata")
    split_cache_payload = None
    codex_runtime_payload = None
    per_label_breakdown_payload = None
    variant_diagnostics_payload = None
    if isinstance(metadata_payload, dict):
        split_cache_payload = metadata_payload.get("single_book_split_cache")
        codex_runtime_payload = metadata_payload.get("codex_farm_runtime")
        per_label_breakdown_payload = metadata_payload.get("per_label_breakdown")
        variant_diagnostics_payload = metadata_payload.get("variant_diagnostics")

    codex_model = ""
    codex_reasoning_effort = ""
    if isinstance(codex_runtime_payload, dict):
        codex_model = (
            str(codex_runtime_payload.get("codex_model") or "").strip()
        )
        codex_reasoning_effort = (
            str(codex_runtime_payload.get("codex_reasoning_effort") or "").strip()
        )

    metric_rows: list[tuple[str, str, str, str]] = []
    for metric_name, display_name in SINGLE_BOOK_COMPARISON_METRICS:
        codex_value = _benchmark_report_metric_value(
            codex_metrics if isinstance(codex_metrics, dict) else None,
            metric_name,
        )
        vanilla_value = _benchmark_report_metric_value(
            vanilla_metrics if isinstance(vanilla_metrics, dict) else None,
            metric_name,
        )
        delta_value = _benchmark_report_metric_value(
            delta_metrics if isinstance(delta_metrics, dict) else None,
            metric_name,
        )
        if delta_value is None and codex_value is not None and vanilla_value is not None:
            delta_value = codex_value - vanilla_value
        metric_rows.append(
            (
                f"`{display_name}`",
                f"{codex_value:.6f}" if codex_value is not None else "null",
                f"{vanilla_value:.6f}" if vanilla_value is not None else "null",
                f"{delta_value:.6f}" if delta_value is not None else "null",
            )
        )

    metric_col_width = max(len("Metric"), *(len(row[0]) for row in metric_rows))
    codex_col_width = max(len("CodexFarm"), *(len(row[1]) for row in metric_rows))
    vanilla_col_width = max(len("Vanilla"), *(len(row[2]) for row in metric_rows))
    delta_col_width = max(
        len("Codex - Vanilla"),
        *(len(row[3]) for row in metric_rows),
    )
    lines: list[str] = [
        "# CodexFarm vs Vanilla Comparison",
        "",
        f"- Schema version: {SINGLE_BOOK_COMPARISON_SCHEMA_VERSION}",
        f"- Run timestamp: {run_timestamp}",
        f"- Source file: {source_file}",
        f"- Codex model: {codex_model or 'unknown'}",
        f"- Codex reasoning effort: {codex_reasoning_effort or 'unknown'}",
        f"- Codex eval directory: {codex_dir or 'unknown'}",
        f"- Vanilla eval directory: {vanilla_dir or 'unknown'}",
        "",
        (
            f"| {'Metric':<{metric_col_width}}"
            f" | {'CodexFarm':>{codex_col_width}}"
            f" | {'Vanilla':>{vanilla_col_width}}"
            f" | {'Codex - Vanilla':>{delta_col_width}} |"
        ),
        (
            f"| {'-' * max(metric_col_width, 3)}"
            f" | {'-' * (max(codex_col_width, 3) - 1) + ':'}"
            f" | {'-' * (max(vanilla_col_width, 3) - 1) + ':'}"
            f" | {'-' * (max(delta_col_width, 3) - 1) + ':'} |"
        ),
    ]
    for metric_text, codex_text, vanilla_text, delta_text in metric_rows:
        lines.append(
            f"| {metric_text:<{metric_col_width}}"
            f" | {codex_text:>{codex_col_width}}"
            f" | {vanilla_text:>{vanilla_col_width}}"
            f" | {delta_text:>{delta_col_width}} |"
        )
    if isinstance(variant_diagnostics_payload, dict):
        likely_driver = (
            str(variant_diagnostics_payload.get("likely_driver") or "").strip()
            or "unknown"
        )
        rationale = (
            str(variant_diagnostics_payload.get("likely_driver_rationale") or "").strip()
            or "No rationale provided."
        )
        deltas_payload = variant_diagnostics_payload.get("deltas")
        delta_rows = deltas_payload if isinstance(deltas_payload, dict) else {}

        def _format_optional_number(value: Any, *, digits: int = 6) -> str:
            number = _report_optional_metric(value)
            if number is None:
                return "null"
            return f"{number:.{digits}f}"

        lines.extend(
            [
                "",
                "## Delta Attribution",
                "",
                f"- Likely dominant driver: `{likely_driver}`",
                f"- Rationale: {rationale}",
                "- Deltas (`codex - vanilla`): "
                f"classification_error_rate={_format_optional_number(delta_rows.get('classification_error_rate_delta'))}, "
                f"segmentation_boundary_error_rate={_format_optional_number(delta_rows.get('segmentation_boundary_error_rate_delta'))}, "
                f"gold_adaptation_coverage_ratio={_format_optional_number(delta_rows.get('gold_adaptation_coverage_ratio_delta'))}",
            ]
        )
        confidence_deltas = delta_rows.get("gold_adaptation_confidence_count_deltas")
        if isinstance(confidence_deltas, dict) and confidence_deltas:
            confidence_summary = ", ".join(
                f"{str(key)}={int(value)}"
                for key, value in sorted(confidence_deltas.items())
            )
            lines.append(
                "- Gold adaptation confidence deltas (`codex - vanilla`): "
                + confidence_summary
            )

        variant_rows = (
            variant_diagnostics_payload.get("variants")
            if isinstance(variant_diagnostics_payload.get("variants"), dict)
            else {}
        )
        for variant_slug in ("vanilla", "codexfarm"):
            row = variant_rows.get(variant_slug)
            if not isinstance(row, dict):
                continue
            segmentation_payload = (
                row.get("segmentation")
                if isinstance(row.get("segmentation"), dict)
                else {}
            )
            adaptation_payload = (
                row.get("gold_adaptation")
                if isinstance(row.get("gold_adaptation"), dict)
                else {}
            )
            confidence_counts = (
                adaptation_payload.get("confidence_counts")
                if isinstance(adaptation_payload.get("confidence_counts"), dict)
                else {}
            )
            if confidence_counts:
                confidence_summary = ", ".join(
                    f"{str(key)}={int(value)}"
                    for key, value in sorted(confidence_counts.items())
                )
            else:
                confidence_summary = "none"
            lines.append(
                f"- {variant_slug}: "
                f"classification_error_rate={_format_optional_number(row.get('classification_error_rate'))}, "
                f"segmentation_boundary_error_rate={_format_optional_number(row.get('segmentation_boundary_error_rate'))}, "
                f"segmentation_boundary_f1={_format_optional_number(segmentation_payload.get('boundary_f1'))}, "
                f"gold_adaptation_coverage_ratio={_format_optional_number(adaptation_payload.get('coverage_ratio'))}, "
                f"gold_adaptation_mode={str(adaptation_payload.get('mode') or 'off')}, "
                f"gold_adaptation_confidence={confidence_summary}"
            )
    if isinstance(per_label_breakdown_payload, dict):
        rows_payload = per_label_breakdown_payload.get("rows")
        if isinstance(rows_payload, list):
            per_label_rows: list[tuple[str, str, str, str, str]] = []
            for row_payload in rows_payload:
                if not isinstance(row_payload, dict):
                    continue
                label = str(row_payload.get("label") or "").strip()
                if not label:
                    continue
                precision = _report_optional_metric(row_payload.get("precision"))
                recall = _report_optional_metric(row_payload.get("recall"))
                gold_total = _report_optional_metric(row_payload.get("gold_total"))
                pred_total = _report_optional_metric(row_payload.get("pred_total"))

                def _format_count(value: float | None) -> str:
                    if value is None:
                        return "null"
                    rounded = round(value)
                    if abs(value - rounded) <= 1e-9:
                        return str(int(rounded))
                    return f"{value:.4f}"

                per_label_rows.append(
                    (
                        label,
                        f"{precision:.4f}" if precision is not None else "null",
                        f"{recall:.4f}" if recall is not None else "null",
                        _format_count(gold_total),
                        _format_count(pred_total),
                    )
                )
            if per_label_rows:
                eval_count = _coerce_non_negative_int(
                    per_label_breakdown_payload.get("eval_count")
                )
                run_label = (
                    str(per_label_breakdown_payload.get("run_timestamp") or "").strip()
                    or run_timestamp
                )
                eval_count_text = (
                    f"{eval_count} eval{'s' if eval_count != 1 else ''}"
                    if eval_count is not None
                    else "unknown evals"
                )
                label_col_width = max(
                    len("Label"),
                    *(len(row[0]) for row in per_label_rows),
                )
                precision_col_width = max(
                    len("Precision"),
                    *(len(row[1]) for row in per_label_rows),
                )
                recall_col_width = max(
                    len("Recall"),
                    *(len(row[2]) for row in per_label_rows),
                )
                gold_col_width = max(len("Gold"), *(len(row[3]) for row in per_label_rows))
                pred_col_width = max(len("Pred"), *(len(row[4]) for row in per_label_rows))
                lines.extend(
                    [
                        "",
                        f"## Per-Label Breakdown ({run_label}, {eval_count_text})",
                        "",
                        "Per label: precision answers false alarms, recall answers misses. Values aggregate all benchmark records with the latest run timestamp.",
                        (
                            f"| {'Label':<{label_col_width}}"
                            f" | {'Precision':>{precision_col_width}}"
                            f" | {'Recall':>{recall_col_width}}"
                            f" | {'Gold':>{gold_col_width}}"
                            f" | {'Pred':>{pred_col_width}} |"
                        ),
                        (
                            f"| {'-' * max(label_col_width, 3)}"
                            f" | {'-' * (max(precision_col_width, 3) - 1) + ':'}"
                            f" | {'-' * (max(recall_col_width, 3) - 1) + ':'}"
                            f" | {'-' * (max(gold_col_width, 3) - 1) + ':'}"
                            f" | {'-' * (max(pred_col_width, 3) - 1) + ':'} |"
                        ),
                    ]
                )
                for (
                    label_text,
                    precision_text,
                    recall_text,
                    gold_text,
                    pred_text,
                ) in per_label_rows:
                    lines.append(
                        f"| {label_text:<{label_col_width}}"
                        f" | {precision_text:>{precision_col_width}}"
                        f" | {recall_text:>{recall_col_width}}"
                        f" | {gold_text:>{gold_col_width}}"
                        f" | {pred_text:>{pred_col_width}} |"
                    )

    if isinstance(split_cache_payload, dict):
        shared_key = str(split_cache_payload.get("shared_key") or "").strip()
        variant_payload = split_cache_payload.get("variants")
        lines.extend(
            [
                "",
                "## Shared Split Cache",
                "",
                f"- Schema version: {split_cache_payload.get('schema_version') or 'unknown'}",
                f"- Shared key: {shared_key or 'unknown'}",
            ]
        )
        if isinstance(variant_payload, dict):
            for variant_slug in ("vanilla", "codexfarm"):
                row = variant_payload.get(variant_slug)
                if not isinstance(row, dict):
                    continue
                mode = str(row.get("mode") or "").strip() or "off"
                hit_text = "yes" if bool(row.get("hit")) else "no"
                conversion_seconds = _report_optional_metric(row.get("conversion_seconds"))
                conversion_text = (
                    f"{conversion_seconds:.3f}s"
                    if conversion_seconds is not None
                    else "unknown"
                )
                lines.append(
                    f"- {variant_slug}: mode={mode} cache_hit={hit_text} conversion={conversion_text}"
                )

    return "\n".join(lines) + "\n"


def _write_single_book_comparison_artifacts(
    *,
    run_timestamp: str,
    session_root: Path,
    source_file: str | None,
    codex_eval_output_dir: Path,
    vanilla_eval_output_dir: Path,
    split_cache_metadata: dict[str, Any] | None = None,
    write_markdown: bool = True,
    write_starter_pack: bool = False,
) -> tuple[Path, Path | None] | None:
    codex_eval_report = _load_json_dict(codex_eval_output_dir / "eval_report.json")
    vanilla_eval_report = _load_json_dict(vanilla_eval_output_dir / "eval_report.json")
    if codex_eval_report is None or vanilla_eval_report is None:
        return None
    codex_metrics = _single_book_eval_metrics_from_report(codex_eval_report)
    vanilla_metrics = _single_book_eval_metrics_from_report(vanilla_eval_report)

    comparison_payload = {
        "schema_version": SINGLE_BOOK_COMPARISON_SCHEMA_VERSION,
        "run_timestamp": run_timestamp,
        "source_file": source_file,
        "variants": {
            "codexfarm": {"eval_output_dir": str(codex_eval_output_dir)},
            "vanilla": {"eval_output_dir": str(vanilla_eval_output_dir)},
        },
        "metrics": {
            "codexfarm": codex_metrics,
            "vanilla": vanilla_metrics,
        },
        "deltas": {
            "codex_minus_vanilla": _single_book_metric_deltas(
                codex_metrics=codex_metrics,
                vanilla_metrics=vanilla_metrics,
            )
        },
    }
    metadata_payload: dict[str, Any] = {}
    codex_runtime_payload = _load_single_book_codex_farm_runtime(codex_eval_output_dir)
    if isinstance(codex_runtime_payload, dict):
        metadata_payload["codex_farm_runtime"] = codex_runtime_payload
    per_label_breakdown = _build_single_book_per_label_breakdown(
        run_timestamp=run_timestamp,
        eval_reports=(vanilla_eval_report, codex_eval_report),
    )
    variant_diagnostics = _build_single_book_variant_diagnostics(
        codex_eval_report=codex_eval_report,
        vanilla_eval_report=vanilla_eval_report,
    )
    metadata_payload["variant_diagnostics"] = variant_diagnostics
    if isinstance(per_label_breakdown, dict):
        metadata_payload["per_label_breakdown"] = per_label_breakdown
    if isinstance(split_cache_metadata, dict):
        metadata_payload["single_book_split_cache"] = split_cache_metadata
    if write_starter_pack:
        starter_pack_dir = _write_single_book_starter_pack(session_root=session_root)
        if starter_pack_dir is not None:
            metadata_payload["starter_pack_v1"] = {
                "path": str(starter_pack_dir),
                "relative_path": "starter_pack_v1",
                "manifest_file": "starter_pack_v1/10_process_manifest.json",
            }
            flattened_summary_path = session_root / "benchmark_summary.md"
            if flattened_summary_path.is_file():
                metadata_payload["flattened_summary"] = {
                    "path": str(flattened_summary_path),
                    "relative_path": "benchmark_summary.md",
                }
    if metadata_payload:
        comparison_payload["metadata"] = metadata_payload
    comparison_json_path = session_root / "codex_vs_vanilla_comparison.json"
    comparison_md_path = session_root / "codex_vs_vanilla_comparison.md"
    comparison_json_path.write_text(
        json.dumps(comparison_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if write_markdown:
        comparison_md_path.write_text(
            _format_single_book_comparison_markdown(comparison_payload),
            encoding="utf-8",
        )
    else:
        comparison_md_path.unlink(missing_ok=True)
        comparison_md_path = None
    return comparison_json_path, comparison_md_path


def _write_single_book_starter_pack(*, session_root: Path) -> Path | None:
    build_starter_pack_for_existing_runs = None

    try:
        from scripts.benchmark_cutdown_for_external_ai import (
            build_starter_pack_for_existing_runs,
        )
    except Exception as import_exc:  # noqa: BLE001
        script_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "benchmark_cutdown_for_external_ai.py"
        )
        try:
            module_spec = importlib.util.spec_from_file_location(
                "cookimport_benchmark_cutdown_for_external_ai",
                script_path,
            )
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError(f"unable to load module spec from {script_path}")
            module = importlib.util.module_from_spec(module_spec)
            module_name = str(module_spec.name or "cookimport_benchmark_cutdown_for_external_ai")
            # Ensure dataclass/type introspection inside the helper script can
            # resolve its module namespace during exec_module().
            sys.modules[module_name] = module
            try:
                module_spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            build_starter_pack_for_existing_runs = getattr(
                module,
                "build_starter_pack_for_existing_runs",
            )
        except Exception as fallback_exc:  # noqa: BLE001
            typer.secho(
                (
                    "Skipped single-book starter pack: unable to load helper "
                    f"({import_exc}; fallback failed: {fallback_exc})."
                ),
                fg=typer.colors.YELLOW,
            )
            return None

    if build_starter_pack_for_existing_runs is None:
        typer.secho(
            "Skipped single-book starter pack: helper loader unavailable.",
            fg=typer.colors.YELLOW,
        )
        return None

    try:
        build_starter_pack_for_existing_runs(
            input_dir=session_root,
            output_dir=session_root,
            write_flattened_summary=True,
        )
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Skipped single-book starter pack generation: {exc}",
            fg=typer.colors.YELLOW,
        )
        return None

    starter_pack_dir = session_root / "starter_pack_v1"
    if not starter_pack_dir.is_dir():
        typer.secho(
            "Skipped single-book starter pack generation: starter_pack_v1 missing after export.",
            fg=typer.colors.YELLOW,
        )
        return None
    return starter_pack_dir


def _write_benchmark_upload_bundle(
    *,
    source_root: Path,
    output_dir: Path,
    suppress_summary: bool,
    high_level_only: bool = False,
    target_bundle_size_bytes: int | None = None,
) -> Path | None:
    build_upload_bundle_for_existing_output = None

    try:
        from scripts.benchmark_cutdown_for_external_ai import (
            build_upload_bundle_for_existing_output,
        )
    except Exception as import_exc:  # noqa: BLE001
        script_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "benchmark_cutdown_for_external_ai.py"
        )
        try:
            module_spec = importlib.util.spec_from_file_location(
                "cookimport_benchmark_cutdown_for_external_ai",
                script_path,
            )
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError(f"unable to load module spec from {script_path}")
            module = importlib.util.module_from_spec(module_spec)
            module_name = str(module_spec.name or "cookimport_benchmark_cutdown_for_external_ai")
            sys.modules[module_name] = module
            try:
                module_spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            build_upload_bundle_for_existing_output = getattr(
                module,
                "build_upload_bundle_for_existing_output",
            )
        except Exception as fallback_exc:  # noqa: BLE001
            if not suppress_summary:
                typer.secho(
                    (
                        "Skipped benchmark upload bundle generation: unable to load helper "
                        f"({import_exc}; fallback failed: {fallback_exc})."
                    ),
                    fg=typer.colors.YELLOW,
                )
            return None

    if build_upload_bundle_for_existing_output is None:
        if not suppress_summary:
            typer.secho(
                "Skipped benchmark upload bundle generation: helper loader unavailable.",
                fg=typer.colors.YELLOW,
            )
        return None

    try:
        build_upload_bundle_for_existing_output(
            source_dir=source_root,
            output_dir=output_dir,
            overwrite=True,
            prune_output_dir=False,
            high_level_only=high_level_only,
            target_bundle_size_bytes=target_bundle_size_bytes,
        )
    except Exception as exc:  # noqa: BLE001
        if not suppress_summary:
            typer.secho(
                f"Skipped benchmark upload bundle generation: {exc}",
                fg=typer.colors.YELLOW,
            )
        return None

    if not output_dir.is_dir():
        if not suppress_summary:
            typer.secho(
                "Skipped benchmark upload bundle generation: bundle folder missing after export.",
                fg=typer.colors.YELLOW,
            )
        return None

    output_files = {
        path.name for path in output_dir.iterdir() if path.is_file()
    }
    if output_files != set(BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES):
        if not suppress_summary:
            typer.secho(
                (
                    "Skipped benchmark upload bundle generation: unexpected bundle file set "
                    f"({sorted(output_files)})."
                ),
                fg=typer.colors.YELLOW,
            )
        return None
    return output_dir


def _oracle_upload_output_excerpt(result: OracleUploadResult, *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for block in (result.stdout, result.stderr):
        if not block:
            continue
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if line:
                lines.append(line)
    if len(lines) <= limit:
        return lines
    return lines[-limit:]


def _print_oracle_upload_summary(
    *,
    target: OracleBenchmarkBundleTarget,
    result: OracleUploadResult,
    success_color: str,
) -> None:
    typer.secho(f"Oracle benchmark bundle: {target.bundle_dir}", fg=typer.colors.CYAN)
    if result.review_profile:
        profile_label = result.review_profile_display_name or result.review_profile
        typer.secho(f"Oracle review profile: {profile_label}", fg=typer.colors.CYAN)
    typer.secho(f"Oracle mode: {result.mode}", fg=typer.colors.CYAN)
    if result.oracle_version:
        typer.secho(f"Oracle version: {result.oracle_version}", fg=typer.colors.BRIGHT_BLACK)
    if result.status:
        typer.secho(
            f"Oracle status: {result.status}"
            + (f" ({result.status_reason})" if result.status_reason else ""),
            fg=success_color,
        )
    if result.reattach_command:
        typer.secho(f"Reattach: {result.reattach_command}", fg=typer.colors.BRIGHT_BLACK)
    if result.conversation_url:
        typer.secho(f"Conversation: {result.conversation_url}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(
        f"Oracle command: {shlex.join(result.command)}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    excerpt = _oracle_upload_output_excerpt(result)
    if excerpt:
        typer.secho("Oracle output:", fg=success_color)
        for line in excerpt:
            typer.echo(f"  {line}")


def _print_oracle_followup_summary(
    *,
    target: OracleBenchmarkBundleTarget,
    source_run: str,
    result: OracleUploadResult,
    workspace: OracleFollowupWorkspace,
    success_color: str,
) -> None:
    typer.secho(f"Oracle benchmark bundle: {target.bundle_dir}", fg=typer.colors.CYAN)
    typer.secho(f"Oracle follow-up source run: {source_run}", fg=typer.colors.CYAN)
    if result.status:
        typer.secho(
            f"Oracle follow-up status: {result.status}"
            + (f" ({result.status_reason})" if result.status_reason else ""),
            fg=success_color,
        )
    if result.reattach_command:
        typer.secho(f"Reattach: {result.reattach_command}", fg=typer.colors.BRIGHT_BLACK)
    if result.conversation_url:
        typer.secho(f"Conversation: {result.conversation_url}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Follow-up launch dir: {workspace.launch_dir}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Codex handoff: {workspace.handoff_path}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Follow-up request: {workspace.request_json_path}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Follow-up packet: {workspace.followup_packet_dir}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Turn-2 prompt: {workspace.prompt_path}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(
        f"Oracle command: {shlex.join(result.command)}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    excerpt = _oracle_upload_output_excerpt(result)
    if excerpt:
        typer.secho("Oracle output:", fg=success_color)
        for line in excerpt:
            typer.echo(f"  {line}")


def _print_background_oracle_upload_summary(
    *,
    target: OracleBenchmarkBundleTarget,
    launch: OracleBackgroundUploadLaunch,
) -> None:
    profile_label = launch.review_profile_display_name or launch.review_profile or "Oracle"
    typer.secho(
        f"{profile_label} Oracle benchmark upload started in background for {target.scope}.",
        fg=typer.colors.GREEN,
    )
    typer.secho(f"Oracle benchmark bundle: {target.bundle_dir}", fg=typer.colors.CYAN)
    if launch.review_profile:
        typer.secho(f"Oracle review profile: {profile_label}", fg=typer.colors.CYAN)
    typer.secho(f"Oracle mode: {launch.mode}", fg=typer.colors.CYAN)
    typer.secho(
        "Oracle browser launcher: auto (visible with display, xvfb otherwise)",
        fg=typer.colors.BRIGHT_BLACK,
    )
    if launch.browser_profile_dir is not None:
        typer.secho(
            f"Oracle browser profile: {launch.browser_profile_dir}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.oracle_version:
        typer.secho(f"Oracle version: {launch.oracle_version}", fg=typer.colors.BRIGHT_BLACK)
    if launch.status:
        typer.secho(
            f"Oracle status: {launch.status}"
            + (f" ({launch.status_reason})" if launch.status_reason else ""),
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.reattach_command:
        typer.secho(
            f"Reattach: {launch.reattach_command}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.conversation_url:
        typer.secho(
            f"Conversation: {launch.conversation_url}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.note:
        transport_message = launch.note.strip()
        typer.secho(
            transport_message,
            fg=typer.colors.BRIGHT_BLACK,
        )
    typer.secho(f"Oracle PID: {launch.pid}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(
        f"Oracle response/log: {launch.log_path}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.secho(
        f"Watch live: tail -f {launch.log_path}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    if launch.auto_followup_status_path is not None:
        typer.secho(
            f"Oracle auto-follow-up status: {launch.auto_followup_status_path}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.auto_followup_log_path is not None:
        typer.secho(
            f"Oracle auto-follow-up log: {launch.auto_followup_log_path}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    typer.secho(
        "When Oracle finishes, open that log file to read the response. If follow-up data is requested, turn 2 will launch automatically.",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.secho(
        f"Retry manually: cookimport bench oracle-upload {target.bundle_dir}",
        fg=typer.colors.BRIGHT_BLACK,
    )


def _start_background_oracle_followup_worker(
    *,
    target: OracleBenchmarkBundleTarget,
    launch: OracleBackgroundUploadLaunch,
    model: str | None,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> OracleBackgroundUploadLaunch:
    source_launch_dir = launch.launch_dir
    status_path = source_launch_dir / ORACLE_AUTO_FOLLOWUP_STATUS_NAME
    log_path = source_launch_dir / ORACLE_AUTO_FOLLOWUP_LOG_NAME
    explicit_model = str(model or "").strip() or None
    status_model = explicit_model or str(launch.model or "").strip() or None
    status_path.write_text(
        json.dumps(
            {
                "status": "pending",
                "status_reason": "Background worker has not started yet.",
                "updated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
                "bundle_dir": str(target.bundle_dir),
                "source_run": source_launch_dir.name,
                "model": status_model,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "cookimport.cli",
        "bench",
        "oracle-autofollowup-worker",
        str(target.bundle_dir),
        "--from-run",
        source_launch_dir.name,
    ]
    if explicit_model is not None:
        command.extend(["--model", explicit_model])
    with log_path.open("w", encoding="utf-8") as log_handle:
        worker = popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(Path.cwd()),
            start_new_session=True,
        )
    return replace(
        launch,
        auto_followup_worker_pid=int(worker.pid),
        auto_followup_log_path=log_path,
        auto_followup_status_path=status_path,
    )


def _start_benchmark_bundle_oracle_upload_background(
    *,
    bundle_dir: Path,
    scope: str,
    mode: str = "browser",
    model: str | None = None,
    review_profile: str = "all",
) -> None:
    try:
        target = resolve_oracle_benchmark_bundle(bundle_dir)
        target = replace(target, scope=scope)
        profiles = resolve_oracle_benchmark_review_profiles(review_profile)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Oracle benchmark upload not started for {bundle_dir}: {exc}",
            fg=typer.colors.YELLOW,
        )
        typer.secho(
            f"Retry manually: cookimport bench oracle-upload {bundle_dir}",
            fg=typer.colors.BRIGHT_BLACK,
        )
        return

    for profile in profiles:
        try:
            launch = start_oracle_benchmark_upload_background(
                target=target,
                mode=mode,
                model=model,
                review_profile=profile.profile_id,
            )
        except Exception as exc:  # noqa: BLE001
            typer.secho(
                f"Oracle {profile.profile_id} upload not started for {bundle_dir}: {exc}",
                fg=typer.colors.YELLOW,
            )
            typer.secho(
                f"Retry manually: cookimport bench oracle-upload {bundle_dir} --profile {profile.profile_id}",
                fg=typer.colors.BRIGHT_BLACK,
            )
            continue
        if launch.mode == "browser":
            try:
                launch = _start_background_oracle_followup_worker(
                    target=target,
                    launch=launch,
                    model=model,
                )
            except Exception as exc:  # noqa: BLE001
                typer.secho(
                    f"Oracle auto-follow-up worker not started for {bundle_dir}: {exc}",
                    fg=typer.colors.YELLOW,
                )
                typer.secho(
                    (
                        "Retry manually after turn 1 finishes: "
                        f"cookimport bench oracle-followup {bundle_dir} --from-run {launch.launch_dir.name}"
                    ),
                    fg=typer.colors.BRIGHT_BLACK,
                )
        _print_background_oracle_upload_summary(target=target, launch=launch)


def _maybe_upload_benchmark_bundle_to_oracle(
    *,
    bundle_dir: Path,
    scope: str,
    mode: str = "browser",
    model: str | None = None,
    review_profile: str = "all",
) -> None:
    try:
        target = resolve_oracle_benchmark_bundle(bundle_dir)
        target = replace(target, scope=scope)
        profiles = resolve_oracle_benchmark_review_profiles(review_profile)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Oracle benchmark upload skipped for {bundle_dir}: {exc}",
            fg=typer.colors.YELLOW,
        )
        typer.secho(
            f"Retry manually: cookimport bench oracle-upload {bundle_dir}",
            fg=typer.colors.BRIGHT_BLACK,
        )
        return

    had_failure = False
    for profile in profiles:
        try:
            result = run_oracle_benchmark_upload(
                target=target,
                mode=mode,
                model=model,
                review_profile=profile.profile_id,
            )
        except Exception as exc:  # noqa: BLE001
            typer.secho(
                f"Oracle {profile.profile_id} upload skipped for {bundle_dir}: {exc}",
                fg=typer.colors.YELLOW,
            )
            had_failure = True
            typer.secho(
                f"Retry manually: cookimport bench oracle-upload {bundle_dir} --profile {profile.profile_id}",
                fg=typer.colors.BRIGHT_BLACK,
            )
            continue

        status_color = typer.colors.GREEN if result.success else typer.colors.YELLOW
        typer.secho(
            (
                f"Oracle {profile.profile_id} upload "
                f"{'completed' if result.success else 'failed'} "
                f"for {target.scope}."
            ),
            fg=status_color,
        )
        _print_oracle_upload_summary(
            target=target,
            result=result,
            success_color=status_color,
        )
        if not result.success:
            had_failure = True
            typer.secho(
                f"Retry manually: cookimport bench oracle-upload {bundle_dir} --profile {profile.profile_id}",
                fg=typer.colors.BRIGHT_BLACK,
            )
            if result.reattach_command:
                typer.secho(
                    f"Reattach directly: {result.reattach_command}",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            else:
                typer.secho(
                    "If the Oracle session detached, inspect it with `oracle status --hours 72`.",
                    fg=typer.colors.BRIGHT_BLACK,
                )
def _write_single_book_summary_markdown(
    *,
    run_timestamp: str,
    session_root: Path,
    variant_results: dict[str, dict[str, Any]],
    comparison_json_path: Path | None,
) -> Path:
    lines: list[str] = [
        "# Single Book Benchmark Summary",
        "",
        f"- Run timestamp: {run_timestamp}",
        "",
        "## Variant Results",
        "",
    ]
    variant_order: list[str] = []
    for preferred_slug in ("vanilla", "codexfarm"):
        if preferred_slug in variant_results:
            variant_order.append(preferred_slug)
    variant_order.extend(
        sorted(
            slug for slug in variant_results.keys() if slug not in {"vanilla", "codexfarm"}
        )
    )
    for variant_slug in variant_order:
        row = variant_results.get(variant_slug)
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "unknown").strip().lower() or "unknown"
        eval_output_dir_raw = row.get("eval_output_dir")
        eval_output_dir = (
            Path(str(eval_output_dir_raw)) if eval_output_dir_raw is not None else None
        )
        eval_report_json = (
            eval_output_dir / "eval_report.json"
            if eval_output_dir is not None
            else None
        )
        relative_eval_report_json = (
            eval_report_json.relative_to(session_root)
            if eval_report_json is not None
            and eval_report_json.is_absolute()
            and str(eval_report_json).startswith(str(session_root))
            else eval_report_json
        )
        metrics = (
            _load_single_book_eval_metrics(eval_output_dir)
            if eval_output_dir is not None and status == "ok"
            else None
        )
        lines.append(f"### `{variant_slug}`")
        lines.append("")
        lines.append(f"- Status: `{status}`")
        if relative_eval_report_json is not None:
            lines.append(f"- Eval report JSON: `{relative_eval_report_json}`")
        if isinstance(metrics, dict):
            for metric_name, _display_name in SINGLE_BOOK_COMPARISON_METRICS:
                metric_value = _benchmark_report_metric_value(metrics, metric_name)
                metric_text = (
                    f"{metric_value:.6f}" if metric_value is not None else "null"
                )
                lines.append(f"- `{metric_name}`: `{metric_text}`")
        else:
            error_text = str(row.get("error") or "").strip()
            if error_text:
                lines.append(f"- Error: `{error_text}`")
        lines.append("")

    if comparison_json_path is not None and comparison_json_path.exists():
        comparison_payload = _load_json_dict(comparison_json_path)
        if isinstance(comparison_payload, dict):
            lines.extend(
                [
                    "## Codex vs Vanilla",
                    "",
                    f"- Comparison JSON: `{comparison_json_path.name}`",
                    "",
                ]
            )
            comparison_md_lines = (
                _format_single_book_comparison_markdown(comparison_payload)
                .strip()
                .splitlines()
            )
            if comparison_md_lines and comparison_md_lines[0].startswith("# "):
                comparison_md_lines = comparison_md_lines[1:]
            while comparison_md_lines and not comparison_md_lines[0].strip():
                comparison_md_lines = comparison_md_lines[1:]
            lines.extend(comparison_md_lines)
            lines.append("")

    summary_md_path = session_root / "single_book_summary.md"
    summary_md_path.parent.mkdir(parents=True, exist_ok=True)
    summary_md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summary_md_path


def _interactive_single_book_benchmark(
    *,
    selected_benchmark_settings: RunSettings,
    benchmark_eval_output: Path,
    processed_output_root: Path,
    write_markdown: bool = False,
    write_label_studio_tasks: bool = False,
    write_starter_pack: bool = False,
    single_book_split_cache_mode: str = "auto",
    single_book_split_cache_dir: Path | None = None,
    single_book_split_cache_force: bool = False,
) -> bool:
    variants = _interactive_single_book_variants(selected_benchmark_settings)
    if not variants:
        typer.secho("No single-book benchmark variants were planned.", fg=typer.colors.YELLOW)
        return False

    selected_gold: Path | None = None
    selected_source: Path | None = None
    if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        resolved_inputs = _resolve_benchmark_gold_and_source(
            gold_spans=None,
            source_file=None,
            output_dir=DEFAULT_GOLDEN,
            allow_cancel=True,
        )
        if resolved_inputs is None:
            typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
            return False
        selected_gold, selected_source = resolved_inputs

    session_root = benchmark_eval_output / "single-book-benchmark"
    session_processed_root = (
        processed_output_root / benchmark_eval_output.name / "single-book-benchmark"
    )
    if selected_source is not None:
        source_slug = slugify_name(selected_source.stem) or "source"
        session_root = session_root / source_slug
        session_processed_root = session_processed_root / source_slug

    typer.secho(
        f"Single-book benchmark variants: {', '.join(slug for slug, _ in variants)}",
        fg=typer.colors.CYAN,
    )

    selected_split_cache_mode = _normalize_single_book_split_cache_mode(
        single_book_split_cache_mode
    )
    split_cache_key: str | None = None
    split_cache_root: Path | None = None
    split_cache_source_hash: str | None = None
    if len(variants) > 1 and selected_split_cache_mode != "off":
        split_cache_root = _resolve_single_book_split_cache_root(
            session_root=session_root,
            split_cache_dir=single_book_split_cache_dir,
        )
        key_source_path = (
            selected_source
            if selected_source is not None
            else session_root / "__single_book_split_cache_source__"
        )
        try:
            split_cache_source_hash = (
                compute_file_hash(key_source_path)
                if key_source_path.exists() and key_source_path.is_file()
                else None
            )
        except Exception:  # noqa: BLE001
            split_cache_source_hash = None
        split_cache_key = _build_single_book_split_cache_key(
            source_file=key_source_path,
            source_hash=split_cache_source_hash,
            pipeline="auto",
            run_settings=variants[0][1],
        )
        typer.secho(
            (
                "Single-book split cache enabled: "
                f"mode={selected_split_cache_mode} key={split_cache_key[:12]}..."
            ),
            fg=typer.colors.BRIGHT_BLACK,
        )

    variant_results: dict[str, dict[str, Any]] = {}
    for index, (variant_slug, variant_settings) in enumerate(variants, start=1):
        variant_eval_output = session_root / variant_slug
        variant_processed_output = session_processed_root / variant_slug
        typer.secho(
            f"Single-book benchmark {index}/{len(variants)}: {variant_slug}",
            fg=typer.colors.CYAN,
        )
        variant_kwargs = build_benchmark_call_kwargs_from_run_settings(
            variant_settings,
            output_dir=_golden_benchmark_root(),
            eval_output_dir=variant_eval_output,
            processed_output_dir=variant_processed_output,
            eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
            no_upload=True,
            # Single-offline keeps per-variant runs JSON-first and writes one
            # consolidated markdown summary at the session root.
            write_markdown=False,
            write_label_studio_tasks=write_label_studio_tasks,
        )
        variant_kwargs["allow_codex"] = codex_surfaces_enabled(
            variant_settings.to_run_config_dict()
        )
        if selected_gold is not None:
            variant_kwargs["gold_spans"] = selected_gold
        if selected_source is not None:
            variant_kwargs["source_file"] = selected_source
        if split_cache_root is not None and split_cache_key:
            variant_kwargs.update(
                {
                    "single_book_split_cache_mode": selected_split_cache_mode,
                    "single_book_split_cache_dir": split_cache_root,
                    "single_book_split_cache_key": split_cache_key,
                    "single_book_split_cache_force": bool(
                        single_book_split_cache_force and index == 1
                    ),
                }
            )
        try:
            with _benchmark_progress_overrides(
                suppress_dashboard_refresh=True,
                suppress_output_prune=True,
            ):
                labelstudio_benchmark(**variant_kwargs)
            source_file = _load_single_book_source_path(variant_eval_output)
            split_cache_metadata = _load_single_book_split_cache_metadata(
                variant_eval_output
            )
            variant_results[variant_slug] = {
                "status": "ok",
                "settings": variant_settings,
                "eval_output_dir": variant_eval_output,
                "processed_output_dir": variant_processed_output,
                "source_file": source_file,
                "single_book_split_cache": split_cache_metadata,
            }
        except typer.Exit as exc:
            exit_code = int(getattr(exc, "exit_code", 1))
            variant_results[variant_slug] = {
                "status": "failed",
                "settings": variant_settings,
                "eval_output_dir": variant_eval_output,
                "processed_output_dir": variant_processed_output,
                "error": f"exit code {exit_code}",
            }
            typer.secho(
                (
                    f"Single-book {variant_slug} failed "
                    f"(exit code {exit_code}); continuing."
                ),
                fg=typer.colors.YELLOW,
            )
        except Exception as exc:  # noqa: BLE001
            variant_results[variant_slug] = {
                "status": "failed",
                "settings": variant_settings,
                "eval_output_dir": variant_eval_output,
                "processed_output_dir": variant_processed_output,
                "error": str(exc),
            }
            typer.secho(
                f"Single-book {variant_slug} failed: {exc}; continuing.",
                fg=typer.colors.YELLOW,
            )

    succeeded = sum(
        1 for payload in variant_results.values() if payload.get("status") == "ok"
    )
    summary_color = typer.colors.GREEN if succeeded == len(variants) else typer.colors.YELLOW
    typer.secho(
        (
            "Single-book benchmark complete: "
            f"{succeeded}/{len(variants)} variant runs succeeded."
        ),
        fg=summary_color,
    )
    typer.secho(
        f"Single-book benchmark outputs: {session_root}",
        fg=typer.colors.CYAN,
    )
    typer.secho(
        f"Single-book processed outputs: {session_processed_root}",
        fg=typer.colors.CYAN,
    )

    comparison_written = False
    comparison_json_path: Path | None = None
    codex_result = variant_results.get("codexfarm")
    vanilla_result = variant_results.get("vanilla")
    if (
        isinstance(codex_result, dict)
        and isinstance(vanilla_result, dict)
        and codex_result.get("status") == "ok"
        and vanilla_result.get("status") == "ok"
    ):
        source_file = (
            str(codex_result.get("source_file") or "").strip()
            or str(vanilla_result.get("source_file") or "").strip()
            or None
        )
        comparison_paths = _write_single_book_comparison_artifacts(
            run_timestamp=benchmark_eval_output.name,
            session_root=session_root,
            source_file=source_file,
            codex_eval_output_dir=Path(str(codex_result["eval_output_dir"])),
            vanilla_eval_output_dir=Path(str(vanilla_result["eval_output_dir"])),
            split_cache_metadata=_single_book_split_cache_summary(
                vanilla_metadata=cast(
                    dict[str, Any] | None,
                    vanilla_result.get("single_book_split_cache"),
                ),
                codex_metadata=cast(
                    dict[str, Any] | None,
                    codex_result.get("single_book_split_cache"),
                ),
            ),
            write_markdown=False,
            write_starter_pack=write_starter_pack,
        )
        if comparison_paths is not None:
            comparison_written = True
            comparison_json_path, _comparison_md_path = comparison_paths
            typer.secho(
                f"Comparison JSON: {comparison_json_path}",
                fg=typer.colors.CYAN,
            )
            starter_pack_dir = session_root / "starter_pack_v1"
            if starter_pack_dir.is_dir():
                typer.secho(f"Starter pack: {starter_pack_dir}", fg=typer.colors.CYAN)
            flattened_summary_path = session_root / "benchmark_summary.md"
            if flattened_summary_path.is_file():
                typer.secho(
                    f"Flattened summary: {flattened_summary_path}",
                    fg=typer.colors.CYAN,
                )

    if (
        not comparison_written
        and isinstance(codex_result, dict)
        and isinstance(vanilla_result, dict)
    ):
        typer.secho(
            (
                "Skipped codex-vs-vanilla comparison artifact: "
                "both codexfarm and vanilla variant runs must succeed."
            ),
            fg=typer.colors.YELLOW,
        )

    if write_markdown:
        summary_md_path = _write_single_book_summary_markdown(
            run_timestamp=benchmark_eval_output.name,
            session_root=session_root,
            variant_results=variant_results,
            comparison_json_path=comparison_json_path,
        )
        typer.secho(f"Summary report: {summary_md_path}", fg=typer.colors.CYAN)

    upload_bundle_dir: Path | None = None
    if succeeded > 0:
        upload_bundle_dir = _write_benchmark_upload_bundle(
            source_root=session_root,
            output_dir=session_root / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
            suppress_summary=False,
            high_level_only=True,
            target_bundle_size_bytes=BENCHMARK_SINGLE_BOOK_UPLOAD_BUNDLE_TARGET_BYTES,
        )
        if upload_bundle_dir is not None:
            typer.secho(
                f"External-AI upload bundle: {upload_bundle_dir}",
                fg=typer.colors.CYAN,
            )
            _start_benchmark_bundle_oracle_upload_background(
                bundle_dir=upload_bundle_dir,
                scope="single_book",
            )

    history_csv_path = history_csv_for_output(
        session_processed_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    _refresh_dashboard_after_history_write(
        csv_path=history_csv_path,
        output_root=processed_output_root,
        dashboard_out_dir=history_root_for_output(processed_output_root) / "dashboard",
        reason="single-book benchmark variant batch append",
    )

    if len(variants) == 1:
        return succeeded == 1
    return succeeded > 0


def _resolve_labelstudio_benchmark_compare_report_root(
    run_dir: Path,
) -> Path | None:
    candidate = run_dir.expanduser()
    if candidate.is_file():
        if candidate.name == "all_method_benchmark_multi_source_report.json":
            return candidate.parent
        return None
    report_path = candidate / "all_method_benchmark_multi_source_report.json"
    if report_path.exists() and report_path.is_file():
        return candidate
    nested_root = candidate / "all-method-benchmark"
    nested_report = nested_root / "all_method_benchmark_multi_source_report.json"
    if nested_report.exists() and nested_report.is_file():
        return nested_root
    return None


def _resolve_labelstudio_benchmark_compare_input(
    run_dir: Path,
) -> dict[str, Any] | None:
    candidate = run_dir.expanduser()
    if candidate.is_file():
        if candidate.name == "all_method_benchmark_multi_source_report.json":
            return {
                "mode": "all_method_report",
                "report_root": candidate.parent,
            }
        if candidate.name == "eval_report.json":
            return {
                "mode": "single_eval_report",
                "report_root": candidate.parent,
                "eval_report_path": candidate,
            }
        return None

    report_root = _resolve_labelstudio_benchmark_compare_report_root(candidate)
    if report_root is not None:
        return {
            "mode": "all_method_report",
            "report_root": report_root,
        }

    eval_report_path = candidate / "eval_report.json"
    if eval_report_path.exists() and eval_report_path.is_file():
        return {
            "mode": "single_eval_report",
            "report_root": candidate,
            "eval_report_path": eval_report_path,
        }
    return None


def _parse_run_config_summary(summary: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    text = str(summary or "").strip()
    if not text:
        return parsed
    for part in text.split(" | "):
        chunk = part.strip()
        if not chunk or "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        cleaned_key = key.strip()
        if not cleaned_key:
            continue
        parsed[cleaned_key] = value.strip()
    return parsed


def _resolve_artifact_path(base_dir: Path, value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve(strict=False)


def _source_key_from_row(row: dict[str, Any]) -> str:
    source_group_key = str(row.get("source_group_key") or "").strip().lower()
    if source_group_key:
        return source_group_key
    source_slug = str(row.get("source_slug") or "").strip().lower()
    if source_slug:
        return source_slug
    source_file_name = str(row.get("source_file_name") or "").strip()
    if source_file_name:
        return slugify_name(Path(source_file_name).stem)
    source_file = str(row.get("source_file") or "").strip()
    if source_file:
        return slugify_name(Path(source_file).stem)
    return ""


def _index_labelstudio_benchmark_sources(
    report_payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    source_rows = report_payload.get("sources")
    if not isinstance(source_rows, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        source_key = _source_key_from_row(row)
        if source_key:
            indexed[source_key] = row
    return indexed


def _load_source_winner_eval_report(
    *,
    multi_source_report_root: Path,
    source_row: dict[str, Any],
) -> tuple[dict[str, Any], Path] | tuple[None, None]:
    report_json_path_value = str(source_row.get("report_json_path") or "").strip()
    if not report_json_path_value:
        return None, None
    source_report_path = _resolve_artifact_path(
        multi_source_report_root, report_json_path_value
    )
    if source_report_path is None:
        return None, None
    source_report = _load_json_dict(source_report_path)
    if source_report is None:
        return None, None
    winner_payload = source_report.get("winner_by_f1")
    winner = winner_payload if isinstance(winner_payload, dict) else None
    if not isinstance(winner, dict):
        variants = source_report.get("variants")
        if isinstance(variants, list):
            successful_variants = [
                row
                for row in variants
                if isinstance(row, dict)
                and str(row.get("status") or "").strip().lower() == "ok"
            ]
            if successful_variants:
                winner = min(
                    successful_variants,
                    key=lambda row: _report_count(row.get("rank")) or 10**9,
                )
    if not isinstance(winner, dict):
        return None, None
    eval_report_path_value = str(winner.get("eval_report_json") or "").strip()
    if not eval_report_path_value:
        return None, None
    eval_report_path = _resolve_artifact_path(
        source_report_path.parent,
        eval_report_path_value,
    )
    if eval_report_path is None:
        return None, None
    eval_report = _load_json_dict(eval_report_path)
    if eval_report is None:
        return None, None
    return eval_report, eval_report_path


def _label_recall_from_eval_report(eval_report: dict[str, Any], label: str) -> float | None:
    per_label = eval_report.get("per_label")
    if not isinstance(per_label, dict):
        return None
    label_payload = per_label.get(label)
    if not isinstance(label_payload, dict):
        return None
    return _report_optional_metric(label_payload.get("recall"))


def _dir_has_json_files(path: Path | None) -> bool:
    if path is None or not path.exists() or not path.is_dir():
        return False
    return any(file_path.is_file() for file_path in path.glob("*.json"))


def _read_artifact_list_from_manifest(path: Path | None) -> list[Path]:
    if path is None or not path.exists() or not path.is_file():
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return []
    base_dir = path.parent
    paths: list[Path] = []
    for line in raw_text.splitlines():
        value = line.strip()
        if not value:
            continue
        artifact_path = Path(value)
        if not artifact_path.is_absolute():
            artifact_path = base_dir / artifact_path
        paths.append(artifact_path)
    return paths


def _all_artifact_paths_exist(artifacts: list[Path] | None) -> bool:
    if not artifacts:
        return False
    return all(path.exists() and path.is_file() for path in artifacts)


def _has_llm_artifact_evidence(
    *,
    prediction_run_dir: Path,
    prediction_artifacts: dict[str, Any] | None,
) -> bool:
    if isinstance(prediction_artifacts, dict):
        if any(
            bool(prediction_artifacts.get(key))
            for key in (
                "recipe_manifest_json",
                "prompt_inputs_manifest_txt",
                "prompt_outputs_manifest_txt",
            )
        ):
            return True
    llm_root = prediction_run_dir / "raw" / "llm"
    if not llm_root.exists() or not llm_root.is_dir():
        return False
    recipe_stage_dirs = {
        stage_artifact_stem("recipe_llm_correct_and_link"),
    }
    for workbook_dir in llm_root.iterdir():
        if not workbook_dir.is_dir():
            continue
        if any((workbook_dir / stage_dir_name).exists() for stage_dir_name in recipe_stage_dirs):
            return True
    return False


def _resolve_codex_farm_mode_and_pipeline(
    *,
    eval_run_config: dict[str, Any],
    summary_tokens: dict[str, str],
    prediction_run_config: dict[str, Any],
    prediction_run_manifest: dict[str, Any] | None,
    prediction_artifacts: dict[str, Any] | None,
    prediction_run_dir: Path,
) -> tuple[str, str, str]:
    pred_manifest_payload = (
        prediction_run_manifest.get("run_config")
        if isinstance(prediction_run_manifest, dict)
        else None
    )
    manifest_mode = (
        pred_manifest_payload.get("codex_farm_recipe_mode")
        if isinstance(pred_manifest_payload, dict)
        else None
    )
    manifest_pipeline = (
        pred_manifest_payload.get("llm_recipe_pipeline")
        if isinstance(pred_manifest_payload, dict)
        else None
    )

    has_mode_metadata = bool(
        prediction_run_config.get("codex_farm_recipe_mode")
        or eval_run_config.get("codex_farm_recipe_mode")
        or manifest_mode
        or summary_tokens.get("codex_farm_recipe_mode")
    )

    artifact_evidence = _has_llm_artifact_evidence(
        prediction_run_dir=prediction_run_dir,
        prediction_artifacts=prediction_artifacts,
    )

    raw_mode = str(
        prediction_run_config.get("codex_farm_recipe_mode")
        or eval_run_config.get("codex_farm_recipe_mode")
        or manifest_mode
        or summary_tokens.get("codex_farm_recipe_mode")
        or ""
    ).strip()
    if not raw_mode:
        if artifact_evidence:
            raw_mode = CODEX_FARM_RECIPE_MODE_BENCHMARK
        else:
            raw_mode = CODEX_FARM_RECIPE_MODE_EXTRACT

    raw_pipeline = str(
        prediction_run_config.get("llm_recipe_pipeline")
        or eval_run_config.get("llm_recipe_pipeline")
        or manifest_pipeline
        or summary_tokens.get("llm_recipe_pipeline")
        or ""
    ).strip()
    if not raw_pipeline:
        if raw_mode == CODEX_FARM_RECIPE_MODE_BENCHMARK:
            raw_pipeline = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
        else:
            raw_pipeline = "off"

    if has_mode_metadata:
        mode_source = "metadata"
    elif artifact_evidence and raw_mode == CODEX_FARM_RECIPE_MODE_BENCHMARK:
        mode_source = "inferred"
    else:
        mode_source = "unknown"

    return (
        _normalize_codex_farm_recipe_mode(raw_mode),
        _normalize_llm_recipe_pipeline(raw_pipeline),
        mode_source,
    )


def _build_source_debug_artifact_status(
    *,
    eval_report_path: Path,
    eval_report: dict[str, Any],
    codex_farm_recipe_mode: str,
    llm_recipe_pipeline: str,
    prediction_run_dir: Path | None = None,
) -> dict[str, Any]:
    eval_dir = eval_report_path.parent
    eval_artifacts = eval_report.get("artifacts")
    if not isinstance(eval_artifacts, dict):
        eval_artifacts = {}
    aligned_path = _resolve_artifact_path(
        eval_dir,
        eval_artifacts.get("aligned_prediction_blocks_jsonl"),
    )
    if aligned_path is None:
        aligned_path = eval_dir / "aligned_prediction_blocks.jsonl"

    checks: list[dict[str, Any]] = [
        {
            "name": "aligned_prediction_blocks_jsonl",
            "present": bool(aligned_path.exists() and aligned_path.is_file()),
            "path": str(aligned_path),
        }
    ]

    normalized_mode = _normalize_codex_farm_recipe_mode(codex_farm_recipe_mode)
    normalized_pipeline = str(llm_recipe_pipeline or "").strip().lower()
    requires_llm_debug = (
        normalized_mode == CODEX_FARM_RECIPE_MODE_BENCHMARK
        and normalized_pipeline != "off"
    )

    if requires_llm_debug:
        candidate_prediction_run_dir = (
            prediction_run_dir
            if isinstance(prediction_run_dir, Path)
            else eval_dir
        )
        prediction_manifest = _load_json_dict(
            candidate_prediction_run_dir / "run_manifest.json"
        )
        prediction_artifacts = (
            prediction_manifest.get("artifacts")
            if isinstance(prediction_manifest, dict)
            else None
        )
        if not isinstance(prediction_artifacts, dict):
            prediction_artifacts = {}
        prompt_inputs_manifest = _resolve_artifact_path(
            candidate_prediction_run_dir,
            prediction_artifacts.get("prompt_inputs_manifest_txt"),
        )
        prompt_outputs_manifest = _resolve_artifact_path(
            candidate_prediction_run_dir,
            prediction_artifacts.get("prompt_outputs_manifest_txt"),
        )
        prompt_input_payloads = _read_artifact_list_from_manifest(
            prompt_inputs_manifest
        )
        prompt_output_payloads = _read_artifact_list_from_manifest(
            prompt_outputs_manifest
        )
        recipe_manifest_path = _resolve_artifact_path(
            candidate_prediction_run_dir,
            prediction_artifacts.get("recipe_manifest_json"),
        )
        recipe_manifest = (
            _load_json_dict(recipe_manifest_path)
            if recipe_manifest_path is not None
            else None
        )
        recipe_paths = (
            recipe_manifest.get("paths")
            if isinstance(recipe_manifest, dict)
            else None
        )
        if not isinstance(recipe_paths, dict):
            recipe_paths = {}
        recipe_phase_input_dir = _resolve_artifact_path(
            recipe_manifest_path.parent
            if recipe_manifest_path is not None
            else candidate_prediction_run_dir,
            recipe_paths.get("recipe_phase_input_dir"),
        )
        recipe_phase_proposals_dir = _resolve_artifact_path(
            recipe_manifest_path.parent
            if recipe_manifest_path is not None
            else candidate_prediction_run_dir,
            recipe_paths.get("recipe_phase_proposals_dir"),
        )
        checks.extend(
            [
                {
                    "name": "prompt_inputs_manifest_txt",
                    "present": bool(
                        prompt_inputs_manifest is not None
                        and prompt_inputs_manifest.exists()
                        and prompt_inputs_manifest.is_file()
                    ),
                    "path": str(prompt_inputs_manifest)
                    if prompt_inputs_manifest is not None
                    else None,
                },
                {
                    "name": "prompt_outputs_manifest_txt",
                    "present": bool(
                        prompt_outputs_manifest is not None
                        and prompt_outputs_manifest.exists()
                        and prompt_outputs_manifest.is_file()
                    ),
                    "path": str(prompt_outputs_manifest)
                    if prompt_outputs_manifest is not None
                    else None,
                },
                {
                    "name": "prompt_request_payloads",
                    "present": _all_artifact_paths_exist(prompt_input_payloads),
                    "path": (
                        str(prompt_inputs_manifest)
                        if prompt_inputs_manifest is not None
                        else None
                    ),
                    "count": len(prompt_input_payloads),
                },
                {
                    "name": "prompt_response_payloads",
                    "present": _all_artifact_paths_exist(prompt_output_payloads),
                    "path": (
                        str(prompt_outputs_manifest)
                        if prompt_outputs_manifest is not None
                        else None
                    ),
                    "count": len(prompt_output_payloads),
                },
                {
                    "name": "recipe_manifest_json",
                    "present": bool(
                        recipe_manifest_path is not None
                        and recipe_manifest_path.exists()
                        and recipe_manifest_path.is_file()
                    ),
                    "path": (
                        str(recipe_manifest_path)
                        if recipe_manifest_path is not None
                        else None
                    ),
                },
                {
                    "name": "recipe_phase_input_json",
                    "present": _dir_has_json_files(recipe_phase_input_dir),
                    "path": (
                        str(recipe_phase_input_dir)
                        if recipe_phase_input_dir is not None
                        else None
                    ),
                },
                {
                    "name": "recipe_phase_proposal_json",
                    "present": _dir_has_json_files(recipe_phase_proposals_dir),
                    "path": (
                        str(recipe_phase_proposals_dir)
                        if recipe_phase_proposals_dir is not None
                        else None
                    ),
                },
            ]
        )

    required_checks = checks if requires_llm_debug else checks[:1]
    missing = [
        str(check.get("name"))
        for check in required_checks
        if not bool(check.get("present"))
    ]
    return {
        "required": requires_llm_debug,
        "checks": checks,
        "required_checks": [str(check.get("name") or "") for check in required_checks],
        "all_present": len(missing) == 0,
        "missing": missing,
    }


def _build_labelstudio_benchmark_source_context(
    *,
    multi_source_report_root: Path,
    source_row: dict[str, Any],
) -> dict[str, Any] | None:
    eval_report, eval_report_path = _load_source_winner_eval_report(
        multi_source_report_root=multi_source_report_root,
        source_row=source_row,
    )
    if eval_report is None or eval_report_path is None:
        return None

    winner_metrics = source_row.get("winner_metrics")
    if not isinstance(winner_metrics, dict):
        winner_metrics = {}
    return _build_labelstudio_benchmark_context_from_eval_report(
        source_key=_source_key_from_row(source_row),
        source_file=str(source_row.get("source_file") or ""),
        winner_metrics=winner_metrics,
        eval_report=eval_report,
        eval_report_path=eval_report_path,
    )


def _infer_source_file_from_eval_report_and_manifest(
    *,
    eval_report: dict[str, Any],
    eval_report_path: Path,
) -> str:
    source_file = str(eval_report.get("source_file") or "").strip()
    if source_file:
        return source_file

    eval_run_manifest = _load_json_dict(eval_report_path.parent / "run_manifest.json")
    if isinstance(eval_run_manifest, dict):
        source_payload = eval_run_manifest.get("source")
        if isinstance(source_payload, dict):
            source_file = str(source_payload.get("path") or "").strip()
            if source_file:
                return source_file
        run_config_payload = eval_run_manifest.get("run_config")
        if isinstance(run_config_payload, dict):
            source_file = str(run_config_payload.get("source_file") or "").strip()
            if source_file:
                return source_file
            prediction_run_config = run_config_payload.get("prediction_run_config")
            if isinstance(prediction_run_config, dict):
                source_file = str(prediction_run_config.get("source_file") or "").strip()
                if source_file:
                    return source_file

    prediction_run_manifest = _load_json_dict(
        eval_report_path.parent / "run_manifest.json"
    )
    if isinstance(prediction_run_manifest, dict):
        source_payload = prediction_run_manifest.get("source")
        if isinstance(source_payload, dict):
            source_file = str(source_payload.get("path") or "").strip()
            if source_file:
                return source_file
        run_config_payload = prediction_run_manifest.get("run_config")
        if isinstance(run_config_payload, dict):
            source_file = str(run_config_payload.get("source_file") or "").strip()
            if source_file:
                return source_file
            prediction_run_config = run_config_payload.get("prediction_run_config")
            if isinstance(prediction_run_config, dict):
                source_file = str(prediction_run_config.get("source_file") or "").strip()
                if source_file:
                    return source_file
    return ""


def _build_labelstudio_benchmark_context_from_eval_report(
    *,
    source_key: str,
    source_file: str,
    winner_metrics: dict[str, Any] | None,
    eval_report: dict[str, Any],
    eval_report_path: Path,
) -> dict[str, Any]:
    summary_tokens = _parse_run_config_summary(
        str((eval_report.get("run_config_summary") or ""))
    )

    eval_run_manifest = _load_json_dict(eval_report_path.parent / "run_manifest.json")
    run_config_payload = (
        eval_run_manifest.get("run_config")
        if isinstance(eval_run_manifest, dict)
        else None
    )
    if not isinstance(run_config_payload, dict):
        run_config_payload = {}
    prediction_run_config = run_config_payload.get("prediction_run_config")
    if not isinstance(prediction_run_config, dict):
        prediction_run_config = {}
    eval_run_artifacts = (
        eval_run_manifest.get("artifacts")
        if isinstance(eval_run_manifest, dict)
        else None
    )
    if not isinstance(eval_run_artifacts, dict):
        eval_run_artifacts = {}
    prediction_run_dir = _resolve_artifact_path(
        eval_report_path.parent,
        eval_run_artifacts.get("artifact_root_dir"),
    )
    prediction_run_dir_is_inferred = prediction_run_dir is None
    if prediction_run_dir is None:
        prediction_run_dir = eval_report_path.parent
    prediction_run_manifest = _load_json_dict(prediction_run_dir / "run_manifest.json")
    prediction_run_artifacts = (
        prediction_run_manifest.get("artifacts")
        if isinstance(prediction_run_manifest, dict)
        else None
    )
    if not isinstance(prediction_run_artifacts, dict):
        prediction_run_artifacts = {}
    codex_farm_recipe_mode, llm_recipe_pipeline, mode_source = (
        _resolve_codex_farm_mode_and_pipeline(
            eval_run_config=run_config_payload,
            summary_tokens=summary_tokens,
            prediction_run_config=prediction_run_config,
            prediction_run_manifest=prediction_run_manifest,
            prediction_artifacts=prediction_run_artifacts,
            prediction_run_dir=prediction_run_dir,
        )
    )

    debug_artifacts = _build_source_debug_artifact_status(
        eval_report_path=eval_report_path,
        eval_report=eval_report,
        codex_farm_recipe_mode=codex_farm_recipe_mode,
        llm_recipe_pipeline=llm_recipe_pipeline,
        prediction_run_dir=prediction_run_dir,
    )
    winner_metric_bundle = _benchmark_report_metric_bundle(
        winner_metrics if isinstance(winner_metrics, dict) else None
    )
    eval_metric_bundle = _benchmark_report_metric_bundle(eval_report)
    overall_line_accuracy = _report_optional_metric(eval_report.get("overall_line_accuracy"))
    if overall_line_accuracy is None:
        overall_line_accuracy = _report_optional_metric(
            eval_metric_bundle.get("strict_accuracy")
        )
    resolved_source_file = str(source_file or "").strip()
    if not resolved_source_file:
        resolved_source_file = _infer_source_file_from_eval_report_and_manifest(
            eval_report=eval_report,
            eval_report_path=eval_report_path,
        )
    return {
        "source_group_key": str(source_key or "").strip(),
        "source_file": resolved_source_file,
        "winner_metrics": {**winner_metric_bundle},
        "overall_line_accuracy": overall_line_accuracy,
        "practical_f1": _report_optional_metric(
            eval_metric_bundle.get("macro_f1_excluding_other")
        ),
        "ingredient_recall": _label_recall_from_eval_report(
            eval_report, BENCHMARK_COMPARE_INGREDIENT_LABEL
        ),
        "variant_recall": _label_recall_from_eval_report(
            eval_report, BENCHMARK_COMPARE_VARIANT_LABEL
        ),
        "codex_farm_mode_source": mode_source,
        "codex_farm_recipe_mode": _normalize_codex_farm_recipe_mode(
            codex_farm_recipe_mode
        ),
        "llm_recipe_pipeline": llm_recipe_pipeline,
        "prediction_run_dir_inferred": bool(prediction_run_dir_is_inferred),
        "eval_report_json_path": str(eval_report_path),
        "debug_artifacts": debug_artifacts,
    }


def _metric_delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return candidate - baseline


def _is_pipeline_off(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"", "off", "none", "null"}


def _source_key_from_source_path(path_value: str) -> str:
    source_text = str(path_value or "").strip()
    if not source_text:
        return ""
    return slugify_name(Path(source_text).stem)


def _history_timestamp_sort_key(row: dict[str, Any]) -> tuple[str, int]:
    timestamp_text = str(row.get("run_timestamp") or "").strip()
    return (timestamp_text, int(row.get("_history_order") or 0))


def _load_benchmark_history_rows(csv_path: Path) -> list[dict[str, Any]]:
    if not csv_path.exists() or not csv_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for order, row in enumerate(reader):
            if not isinstance(row, dict):
                continue
            if str(row.get("run_category") or "").strip() != "benchmark_eval":
                continue
            materialized = dict(row)
            materialized["_history_order"] = order
            run_config_payload = materialized.get("run_config_json")
            run_config: dict[str, Any] = {}
            if isinstance(run_config_payload, str) and run_config_payload.strip():
                try:
                    parsed = json.loads(run_config_payload)
                except json.JSONDecodeError:
                    parsed = {}
                if isinstance(parsed, dict):
                    run_config = parsed
            materialized["_run_config"] = run_config
            materialized["_source_key"] = _source_key_from_source_path(
                str(materialized.get("file_name") or "")
            )
            rows.append(materialized)
    return rows


def _load_eval_report_from_history_row(row: dict[str, Any]) -> dict[str, Any] | None:
    run_dir_raw = str(row.get("run_dir") or "").strip()
    if not run_dir_raw:
        return None
    report_path = Path(run_dir_raw) / "eval_report.json"
    payload = _load_json_dict(report_path)
    if not isinstance(payload, dict):
        return None
    return payload


def _build_joined_line_rows_for_history_row(
    row: dict[str, Any],
) -> list[dict[str, Any]] | None:
    run_dir_raw = str(row.get("run_dir") or "").strip()
    if not run_dir_raw:
        return None
    eval_output_dir = Path(run_dir_raw)
    report = _load_eval_report_from_history_row(row)
    if not isinstance(report, dict):
        return None
    return build_line_role_joined_line_rows(
        report=report,
        eval_output_dir=eval_output_dir,
        line_role_predictions_path=None,
    )


def _resolve_line_role_baseline_joined_rows(
    *,
    history_csv_path: Path,
    source_key: str,
    llm_recipe_pipeline: str,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    history_rows = _load_benchmark_history_rows(history_csv_path)
    primary_row = _find_latest_history_row(
        history_rows,
        source_key=source_key,
        predicate=lambda row: (
            str(row.get("eval_scope") or "").strip() == BENCHMARK_EVAL_MODE_CANONICAL_TEXT
            and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
            and str((row.get("_run_config") or {}).get("llm_recipe_pipeline") or "").strip()
            == str(llm_recipe_pipeline or "").strip()
        ),
    )
    fallback_row: dict[str, Any] | None = None
    if primary_row is None and not _is_pipeline_off(llm_recipe_pipeline):
        fallback_row = _find_latest_history_row(
            history_rows,
            source_key=source_key,
            predicate=lambda row: (
                str(row.get("eval_scope") or "").strip()
                == BENCHMARK_EVAL_MODE_CANONICAL_TEXT
                and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
                and _is_pipeline_off((row.get("_run_config") or {}).get("llm_recipe_pipeline"))
            ),
        )

    for row in (primary_row, fallback_row):
        if row is None:
            continue
        joined_rows = _build_joined_line_rows_for_history_row(row)
        if joined_rows is not None:
            return joined_rows, row
    return None, None


def _confusion_count(
    *,
    report: dict[str, Any],
    gold_label: str,
    pred_label: str,
) -> int | None:
    confusion = report.get("confusion")
    if not isinstance(confusion, dict):
        return None
    by_gold = confusion.get(gold_label)
    if not isinstance(by_gold, dict):
        return 0
    value = _coerce_int(by_gold.get(pred_label))
    return value if value is not None else 0


def _find_latest_history_row(
    rows: list[dict[str, Any]],
    *,
    source_key: str,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row.get("_source_key") or "") == source_key and predicate(row)
    ]
    if not candidates:
        return None
    candidates.sort(key=_history_timestamp_sort_key, reverse=True)
    return candidates[0]


def _source_available_in_input_root(source_key: str) -> bool:
    if not DEFAULT_INPUT.exists() or not DEFAULT_INPUT.is_dir():
        return False
    for path in DEFAULT_INPUT.iterdir():
        if not path.is_file():
            continue
        if slugify_name(path.stem) == source_key:
            return True
    return False


def _build_line_role_regression_gate_payload(
    *,
    candidate_report: dict[str, Any],
    candidate_source_key: str,
    history_csv_path: Path,
) -> dict[str, Any]:
    history_rows = _load_benchmark_history_rows(history_csv_path)
    gates: list[dict[str, Any]] = []

    def _add_gate(name: str, passed: bool, reason: str) -> None:
        gates.append({"name": name, "passed": bool(passed), "reason": reason})

    if candidate_source_key != BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY:
        _add_gate(
            "foodlab_source_required",
            False,
            (
                "line-role gated mode currently requires source "
                f"{BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY}; got {candidate_source_key or '<unknown>'}."
            ),
        )
    vanilla_foodlab_row = _find_latest_history_row(
        history_rows,
        source_key=BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY,
        predicate=lambda row: (
            _is_pipeline_off((row.get("_run_config") or {}).get("llm_recipe_pipeline"))
            and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
            and str(row.get("eval_scope") or "").strip() == BENCHMARK_EVAL_MODE_CANONICAL_TEXT
        ),
    )
    codex_foodlab_row = _find_latest_history_row(
        history_rows,
        source_key=BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY,
        predicate=lambda row: (
            _normalize_llm_recipe_pipeline(
                str((row.get("_run_config") or {}).get("llm_recipe_pipeline") or "off")
            )
            == RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
            and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
            and str(row.get("eval_scope") or "").strip() == BENCHMARK_EVAL_MODE_CANONICAL_TEXT
        ),
    )
    vanilla_foodlab_report = (
        _load_eval_report_from_history_row(vanilla_foodlab_row)
        if vanilla_foodlab_row is not None
        else None
    )
    codex_foodlab_report = (
        _load_eval_report_from_history_row(codex_foodlab_row)
        if codex_foodlab_row is not None
        else None
    )

    candidate_macro = _report_optional_metric(
        candidate_report.get("macro_f1_excluding_other")
    )
    candidate_accuracy = _report_optional_metric(
        candidate_report.get("overall_line_accuracy")
    )
    baseline_macro = (
        _report_optional_metric(vanilla_foodlab_report.get("macro_f1_excluding_other"))
        if isinstance(vanilla_foodlab_report, dict)
        else None
    )
    baseline_accuracy = (
        _report_optional_metric(vanilla_foodlab_report.get("overall_line_accuracy"))
        if isinstance(vanilla_foodlab_report, dict)
        else None
    )
    macro_delta = _metric_delta(candidate_macro, baseline_macro)
    accuracy_delta = _metric_delta(candidate_accuracy, baseline_accuracy)
    if macro_delta is None:
        _add_gate(
            "foodlab_macro_f1_delta_min",
            False,
            "Missing baseline/candidate macro_f1_excluding_other.",
        )
    else:
        _add_gate(
            "foodlab_macro_f1_delta_min",
            macro_delta >= LINE_ROLE_GATED_METRIC_DELTA_MIN,
            (
                f"candidate_minus_baseline={macro_delta:.6f} "
                f"(threshold {LINE_ROLE_GATED_METRIC_DELTA_MIN:.2f})."
            ),
        )
    if accuracy_delta is None:
        _add_gate(
            "foodlab_line_accuracy_delta_min",
            False,
            "Missing baseline/candidate overall_line_accuracy.",
        )
    else:
        _add_gate(
            "foodlab_line_accuracy_delta_min",
            accuracy_delta >= LINE_ROLE_GATED_METRIC_DELTA_MIN,
            (
                f"candidate_minus_baseline={accuracy_delta:.6f} "
                f"(threshold {LINE_ROLE_GATED_METRIC_DELTA_MIN:.2f})."
            ),
        )

    candidate_ingredient_yield = _confusion_count(
        report=candidate_report,
        gold_label="INGREDIENT_LINE",
        pred_label="YIELD_LINE",
    )
    candidate_other_knowledge = _confusion_count(
        report=candidate_report,
        gold_label="OTHER",
        pred_label="KNOWLEDGE",
    )
    confusion_baseline_report = None
    confusion_baseline_source = "missing"
    if isinstance(codex_foodlab_report, dict):
        confusion_baseline_report = codex_foodlab_report
        confusion_baseline_source = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
    elif isinstance(vanilla_foodlab_report, dict):
        confusion_baseline_report = vanilla_foodlab_report
        confusion_baseline_source = "vanilla-off-fallback"
    baseline_ingredient_yield = (
        _confusion_count(
            report=confusion_baseline_report,
            gold_label="INGREDIENT_LINE",
            pred_label="YIELD_LINE",
        )
        if isinstance(confusion_baseline_report, dict)
        else None
    )
    baseline_other_knowledge = (
        _confusion_count(
            report=confusion_baseline_report,
            gold_label="OTHER",
            pred_label="KNOWLEDGE",
        )
        if isinstance(confusion_baseline_report, dict)
        else None
    )

    def _confusion_drop_gate(
        *,
        gate_name: str,
        baseline_value: int | None,
        candidate_value: int | None,
        min_drop_ratio: float,
        baseline_source: str,
    ) -> None:
        if baseline_value is None or candidate_value is None:
            _add_gate(gate_name, False, "Missing baseline/candidate confusion counts.")
            return
        if baseline_value <= 0:
            passed = candidate_value <= 0
            _add_gate(
                gate_name,
                passed,
                (
                    f"Baseline confusion count is 0 ({baseline_source}); "
                    f"candidate={candidate_value}."
                ),
            )
            return
        drop_ratio = (baseline_value - candidate_value) / baseline_value
        _add_gate(
            gate_name,
            drop_ratio >= min_drop_ratio,
            (
                f"baseline_source={baseline_source}, "
                f"baseline={baseline_value}, candidate={candidate_value}, "
                f"drop_ratio={drop_ratio:.6f}, threshold={min_drop_ratio:.2f}."
            ),
        )

    _confusion_drop_gate(
        gate_name="foodlab_ingredient_to_yield_confusion_drop",
        baseline_value=baseline_ingredient_yield,
        candidate_value=candidate_ingredient_yield,
        min_drop_ratio=LINE_ROLE_GATED_INGREDIENT_YIELD_DROP_MIN,
        baseline_source=confusion_baseline_source,
    )
    _confusion_drop_gate(
        gate_name="foodlab_other_to_knowledge_confusion_drop",
        baseline_value=baseline_other_knowledge,
        candidate_value=candidate_other_knowledge,
        min_drop_ratio=LINE_ROLE_GATED_OTHER_KNOWLEDGE_DROP_MIN,
        baseline_source=confusion_baseline_source,
    )

    candidate_notes_recall = _label_recall_from_eval_report(
        candidate_report,
        "RECIPE_NOTES",
    )
    candidate_variant_recall = _label_recall_from_eval_report(
        candidate_report,
        "RECIPE_VARIANT",
    )
    candidate_ingredient_recall = _label_recall_from_eval_report(
        candidate_report,
        "INGREDIENT_LINE",
    )
    for gate_name, recall_value, threshold in (
        (
            "foodlab_recipe_notes_recall_min",
            candidate_notes_recall,
            LINE_ROLE_GATED_MIN_RECIPE_NOTES_RECALL,
        ),
        (
            "foodlab_recipe_variant_recall_min",
            candidate_variant_recall,
            LINE_ROLE_GATED_MIN_RECIPE_VARIANT_RECALL,
        ),
        (
            "foodlab_ingredient_recall_min",
            candidate_ingredient_recall,
            LINE_ROLE_GATED_MIN_INGREDIENT_RECALL,
        ),
    ):
        if recall_value is None:
            _add_gate(gate_name, False, "Missing candidate per-label recall.")
            continue
        _add_gate(
            gate_name,
            recall_value > threshold,
            f"candidate_recall={recall_value:.6f}, threshold>{threshold:.2f}.",
        )

    sea_exists = _source_available_in_input_root(BENCHMARK_COMPARE_SEA_SOURCE_KEY)
    if sea_exists:
        sea_vanilla_row = _find_latest_history_row(
            history_rows,
            source_key=BENCHMARK_COMPARE_SEA_SOURCE_KEY,
            predicate=lambda row: (
                _is_pipeline_off((row.get("_run_config") or {}).get("llm_recipe_pipeline"))
                and _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
                and str(row.get("eval_scope") or "").strip()
                == BENCHMARK_EVAL_MODE_CANONICAL_TEXT
            ),
        )
        sea_candidate_row = _find_latest_history_row(
            history_rows,
            source_key=BENCHMARK_COMPARE_SEA_SOURCE_KEY,
            predicate=lambda row: (
                not _is_pipeline_off((row.get("_run_config") or {}).get("line_role_pipeline"))
                and str(row.get("eval_scope") or "").strip()
                == BENCHMARK_EVAL_MODE_CANONICAL_TEXT
            ),
        )
        sea_vanilla_report = (
            _load_eval_report_from_history_row(sea_vanilla_row)
            if sea_vanilla_row is not None
            else None
        )
        sea_candidate_report = (
            _load_eval_report_from_history_row(sea_candidate_row)
            if sea_candidate_row is not None
            else None
        )
        for metric_name, field in (
            ("sea_macro_f1_no_regression", "macro_f1_excluding_other"),
            ("sea_line_accuracy_no_regression", "overall_line_accuracy"),
        ):
            baseline_value = (
                _report_optional_metric(sea_vanilla_report.get(field))
                if isinstance(sea_vanilla_report, dict)
                else None
            )
            candidate_value = (
                _report_optional_metric(sea_candidate_report.get(field))
                if isinstance(sea_candidate_report, dict)
                else None
            )
            if baseline_value is None or candidate_value is None:
                _add_gate(
                    metric_name,
                    False,
                    "Missing seaandsmokecutdown baseline/candidate metrics in benchmark history.",
                )
                continue
            _add_gate(
                metric_name,
                candidate_value >= baseline_value,
                f"candidate={candidate_value:.6f}, baseline={baseline_value:.6f}.",
            )

    failed_gate_count = sum(1 for gate in gates if not bool(gate.get("passed")))
    return {
        "schema_version": LINE_ROLE_REGRESSION_GATES_SCHEMA_VERSION,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "history_csv": str(history_csv_path),
        "candidate_source_key": candidate_source_key,
        "overall": {
            "verdict": "PASS" if failed_gate_count == 0 else "FAIL",
            "gate_count": len(gates),
            "failed_gate_count": failed_gate_count,
            "passed_gate_count": len(gates) - failed_gate_count,
        },
        "gates": gates,
    }


def _build_labelstudio_benchmark_compare_payload(
    *,
    baseline_report_root: Path,
    candidate_report_root: Path,
) -> dict[str, Any]:
    baseline_report_payload = _load_json_dict(
        baseline_report_root / "all_method_benchmark_multi_source_report.json"
    )
    candidate_report_payload = _load_json_dict(
        candidate_report_root / "all_method_benchmark_multi_source_report.json"
    )
    if baseline_report_payload is None:
        _fail(
            "Baseline all-method benchmark report is missing or invalid: "
            f"{baseline_report_root / 'all_method_benchmark_multi_source_report.json'}"
        )
    if candidate_report_payload is None:
        _fail(
            "Candidate all-method benchmark report is missing or invalid: "
            f"{candidate_report_root / 'all_method_benchmark_multi_source_report.json'}"
        )

    baseline_rows = _index_labelstudio_benchmark_sources(baseline_report_payload)
    candidate_rows = _index_labelstudio_benchmark_sources(candidate_report_payload)
    known_source_keys = sorted(set(baseline_rows) | set(candidate_rows))
    source_comparison: dict[str, dict[str, Any]] = {}
    for source_key in known_source_keys:
        baseline_context = (
            _build_labelstudio_benchmark_source_context(
                multi_source_report_root=baseline_report_root,
                source_row=baseline_rows[source_key],
            )
            if source_key in baseline_rows
            else None
        )
        candidate_context = (
            _build_labelstudio_benchmark_source_context(
                multi_source_report_root=candidate_report_root,
                source_row=candidate_rows[source_key],
            )
            if source_key in candidate_rows
            else None
        )
        baseline_practical_f1 = (
            _report_optional_metric(baseline_context.get("practical_f1"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_practical_f1 = (
            _report_optional_metric(candidate_context.get("practical_f1"))
            if isinstance(candidate_context, dict)
            else None
        )
        baseline_line_accuracy = (
            _report_optional_metric(baseline_context.get("overall_line_accuracy"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_line_accuracy = (
            _report_optional_metric(candidate_context.get("overall_line_accuracy"))
            if isinstance(candidate_context, dict)
            else None
        )
        baseline_ingredient_recall = (
            _report_optional_metric(baseline_context.get("ingredient_recall"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_ingredient_recall = (
            _report_optional_metric(candidate_context.get("ingredient_recall"))
            if isinstance(candidate_context, dict)
            else None
        )
        baseline_variant_recall = (
            _report_optional_metric(baseline_context.get("variant_recall"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_variant_recall = (
            _report_optional_metric(candidate_context.get("variant_recall"))
            if isinstance(candidate_context, dict)
            else None
        )
        source_comparison[source_key] = {
            "baseline": baseline_context,
            "candidate": candidate_context,
            "deltas": {
                "practical_f1": _metric_delta(
                    candidate_practical_f1,
                    baseline_practical_f1,
                ),
                "overall_line_accuracy": _metric_delta(
                    candidate_line_accuracy,
                    baseline_line_accuracy,
                ),
                "ingredient_recall": _metric_delta(
                    candidate_ingredient_recall,
                    baseline_ingredient_recall,
                ),
                "variant_recall": _metric_delta(
                    candidate_variant_recall,
                    baseline_variant_recall,
                ),
            },
        }

    gates: list[dict[str, Any]] = []
    warnings: list[str] = []

    def _add_warning(message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        if text not in warnings:
            warnings.append(text)

    def _add_gate(name: str, passed: bool, reason: str) -> None:
        gates.append({"name": name, "passed": bool(passed), "reason": reason})

    def _add_no_regression_gate(name: str, source_key: str) -> None:
        source_payload = source_comparison.get(source_key)
        if not isinstance(source_payload, dict):
            _add_gate(name, False, f"Missing source row for {source_key}.")
            return
        baseline_context = source_payload.get("baseline")
        candidate_context = source_payload.get("candidate")
        if not isinstance(baseline_context, dict) or not isinstance(candidate_context, dict):
            _add_gate(name, False, f"Missing baseline/candidate context for {source_key}.")
            return
        baseline_value = _report_optional_metric(baseline_context.get("practical_f1"))
        candidate_value = _report_optional_metric(candidate_context.get("practical_f1"))
        if baseline_value is None or candidate_value is None:
            _add_gate(
                name,
                False,
                f"Missing practical_f1 for baseline/candidate ({source_key}).",
            )
            return
        passed = candidate_value >= baseline_value
        _add_gate(
            name,
            passed,
            (
                f"candidate_practical_f1={candidate_value:.6f}, "
                f"baseline_practical_f1={baseline_value:.6f}"
            ),
        )

    _add_no_regression_gate("sea_no_regression", BENCHMARK_COMPARE_SEA_SOURCE_KEY)
    _add_no_regression_gate("foodlab_no_regression", BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY)

    foodlab_payload = source_comparison.get(BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY)
    if not isinstance(foodlab_payload, dict):
        _add_gate(
            "foodlab_ingredient_at_least_baseline",
            False,
            "Missing thefoodlabcutdown source row.",
        )
        _add_gate(
            "foodlab_variant_recall_nonzero",
            False,
            "Missing thefoodlabcutdown source row.",
        )
    else:
        baseline_context = foodlab_payload.get("baseline")
        candidate_context = foodlab_payload.get("candidate")
        baseline_ingredient = (
            _report_optional_metric(baseline_context.get("ingredient_recall"))
            if isinstance(baseline_context, dict)
            else None
        )
        candidate_ingredient = (
            _report_optional_metric(candidate_context.get("ingredient_recall"))
            if isinstance(candidate_context, dict)
            else None
        )
        if baseline_ingredient is None or candidate_ingredient is None:
            _add_gate(
                "foodlab_ingredient_at_least_baseline",
                False,
                "Missing ingredient recall in baseline/candidate winner eval report.",
            )
        else:
            ingredient_passed = candidate_ingredient >= baseline_ingredient
            _add_gate(
                "foodlab_ingredient_at_least_baseline",
                ingredient_passed,
                (
                    f"candidate_ingredient_recall={candidate_ingredient:.6f}, "
                    f"baseline_ingredient_recall={baseline_ingredient:.6f}"
                ),
            )

        candidate_variant = (
            _report_optional_metric(candidate_context.get("variant_recall"))
            if isinstance(candidate_context, dict)
            else None
        )
        if candidate_variant is None:
            _add_gate(
                "foodlab_variant_recall_nonzero",
                False,
                "Missing candidate RECIPE_VARIANT recall.",
            )
        else:
            variant_passed = candidate_variant > 0.0
            _add_gate(
                "foodlab_variant_recall_nonzero",
                variant_passed,
                f"candidate_variant_recall={candidate_variant:.6f}",
            )

    for source_key, gate_name in (
        (BENCHMARK_COMPARE_SEA_SOURCE_KEY, "sea_debug_artifacts_present"),
        (BENCHMARK_COMPARE_FOODLAB_SOURCE_KEY, "foodlab_debug_artifacts_present"),
    ):
        source_payload = source_comparison.get(source_key)
        if not isinstance(source_payload, dict):
            _add_gate(gate_name, False, f"Missing source row for {source_key}.")
            continue
        candidate_context = source_payload.get("candidate")
        if not isinstance(candidate_context, dict):
            _add_gate(gate_name, False, f"Missing candidate context for {source_key}.")
            continue
        debug_payload = candidate_context.get("debug_artifacts")
        if not isinstance(debug_payload, dict):
            _add_gate(gate_name, False, "Missing candidate debug artifact payload.")
            continue
        mode_source = str(candidate_context.get("codex_farm_mode_source") or "").strip()
        if not mode_source:
            mode_source = "unknown"
        requires_debug = bool(debug_payload.get("required"))
        if mode_source == "inferred" and requires_debug:
            _add_warning(
                (
                    f"Running benchmark-only debug checks for {source_key} using "
                    "inferred benchmark mode from artifacts (metadata missing)."
                )
            )
        elif mode_source == "unknown":
            _add_warning(
                (
                    f"Could not confirm benchmark mode for {source_key}: "
                    "mode metadata is missing and artifact signals are not conclusive."
                )
            )
            if requires_debug:
                _add_warning(
                    f"Skipping benchmark-only debug checks for {source_key}: "
                    "mode could not be determined from metadata or artifacts."
                )
                _add_gate(
                    gate_name,
                    True,
                    (
                        "Not required: "
                        f"mode={candidate_context.get('codex_farm_recipe_mode')}, "
                        f"llm_recipe_pipeline={candidate_context.get('llm_recipe_pipeline')}"
                    ),
                )
                continue
        elif mode_source != "metadata":
            _add_warning(f"Unrecognized mode_source for {source_key}: {mode_source}.")
            _add_gate(
                gate_name,
                False,
                f"Invalid mode source reported for benchmark comparison: {mode_source}.",
            )
            continue

        missing = debug_payload.get("missing")
        if not isinstance(missing, list):
            missing = []
        passed = bool(debug_payload.get("all_present"))
        _add_gate(
            gate_name,
            passed,
            (
                "Required debug artifacts present."
                if passed
                else "Missing required debug artifacts: "
                + ", ".join(str(name) for name in missing)
            ),
        )

    failed_gate_count = sum(1 for gate in gates if not bool(gate.get("passed")))
    passed_gate_count = len(gates) - failed_gate_count
    overall_verdict = "PASS" if failed_gate_count == 0 else "FAIL"

    return {
        "schema_version": LABELSTUDIO_BENCHMARK_COMPARE_SCHEMA_VERSION,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "baseline_report_root": str(baseline_report_root),
        "candidate_report_root": str(candidate_report_root),
        "overall": {
            "verdict": overall_verdict,
            "gate_count": len(gates),
            "passed_gate_count": passed_gate_count,
            "failed_gate_count": failed_gate_count,
        },
        "warnings": warnings,
        "gates": gates,
        "sources": source_comparison,
    }


def _build_labelstudio_benchmark_compare_single_eval_payload(
    *,
    baseline_eval_report_path: Path,
    candidate_eval_report_path: Path,
) -> dict[str, Any]:
    baseline_eval_report = _load_json_dict(baseline_eval_report_path)
    if baseline_eval_report is None:
        _fail(
            "Baseline eval report is missing or invalid: "
            f"{baseline_eval_report_path}"
        )
    candidate_eval_report = _load_json_dict(candidate_eval_report_path)
    if candidate_eval_report is None:
        _fail(
            "Candidate eval report is missing or invalid: "
            f"{candidate_eval_report_path}"
        )

    baseline_source_file = _infer_source_file_from_eval_report_and_manifest(
        eval_report=baseline_eval_report,
        eval_report_path=baseline_eval_report_path,
    )
    candidate_source_file = _infer_source_file_from_eval_report_and_manifest(
        eval_report=candidate_eval_report,
        eval_report_path=candidate_eval_report_path,
    )
    baseline_source_key = _source_key_from_source_path(baseline_source_file)
    candidate_source_key = _source_key_from_source_path(candidate_source_file)
    source_key = (
        baseline_source_key
        or candidate_source_key
        or slugify_name(candidate_eval_report_path.parent.name)
        or "single_source"
    )

    baseline_context = _build_labelstudio_benchmark_context_from_eval_report(
        source_key=source_key,
        source_file=baseline_source_file,
        winner_metrics=None,
        eval_report=baseline_eval_report,
        eval_report_path=baseline_eval_report_path,
    )
    candidate_context = _build_labelstudio_benchmark_context_from_eval_report(
        source_key=source_key,
        source_file=candidate_source_file,
        winner_metrics=None,
        eval_report=candidate_eval_report,
        eval_report_path=candidate_eval_report_path,
    )
    source_comparison: dict[str, dict[str, Any]] = {
        source_key: {
            "baseline": baseline_context,
            "candidate": candidate_context,
            "deltas": {
                "practical_f1": _metric_delta(
                    _report_optional_metric(candidate_context.get("practical_f1")),
                    _report_optional_metric(baseline_context.get("practical_f1")),
                ),
                "overall_line_accuracy": _metric_delta(
                    _report_optional_metric(candidate_context.get("overall_line_accuracy")),
                    _report_optional_metric(baseline_context.get("overall_line_accuracy")),
                ),
                "ingredient_recall": _metric_delta(
                    _report_optional_metric(candidate_context.get("ingredient_recall")),
                    _report_optional_metric(baseline_context.get("ingredient_recall")),
                ),
                "variant_recall": _metric_delta(
                    _report_optional_metric(candidate_context.get("variant_recall")),
                    _report_optional_metric(baseline_context.get("variant_recall")),
                ),
            },
        }
    }

    gates: list[dict[str, Any]] = []
    warnings: list[str] = []

    def _add_warning(message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        if text not in warnings:
            warnings.append(text)

    def _add_gate(name: str, passed: bool, reason: str) -> None:
        gates.append({"name": name, "passed": bool(passed), "reason": reason})

    def _add_no_regression_gate(
        *,
        name: str,
        metric_name: str,
        baseline_value: float | None,
        candidate_value: float | None,
    ) -> None:
        if baseline_value is None or candidate_value is None:
            _add_gate(
                name,
                False,
                f"Missing baseline/candidate {metric_name}.",
            )
            return
        _add_gate(
            name,
            candidate_value >= baseline_value,
            (
                f"candidate_{metric_name}={candidate_value:.6f}, "
                f"baseline_{metric_name}={baseline_value:.6f}"
            ),
        )

    if baseline_source_key and candidate_source_key and baseline_source_key != candidate_source_key:
        _add_gate(
            "source_key_match",
            False,
            (
                "Baseline/candidate source mismatch: "
                f"{baseline_source_key} vs {candidate_source_key}."
            ),
        )
    else:
        _add_gate(
            "source_key_match",
            True,
            (
                f"source_key={source_key}"
                if source_key
                else "Source key unavailable in eval metadata."
            ),
        )

    _add_no_regression_gate(
        name="practical_f1_no_regression",
        metric_name="practical_f1",
        baseline_value=_report_optional_metric(baseline_context.get("practical_f1")),
        candidate_value=_report_optional_metric(candidate_context.get("practical_f1")),
    )
    _add_no_regression_gate(
        name="overall_line_accuracy_no_regression",
        metric_name="overall_line_accuracy",
        baseline_value=_report_optional_metric(
            baseline_context.get("overall_line_accuracy")
        ),
        candidate_value=_report_optional_metric(
            candidate_context.get("overall_line_accuracy")
        ),
    )

    baseline_ingredient = _report_optional_metric(baseline_context.get("ingredient_recall"))
    candidate_ingredient = _report_optional_metric(candidate_context.get("ingredient_recall"))
    if baseline_ingredient is None or candidate_ingredient is None:
        _add_gate(
            "ingredient_recall_at_least_baseline",
            False,
            "Missing ingredient recall in baseline/candidate eval report.",
        )
    else:
        _add_gate(
            "ingredient_recall_at_least_baseline",
            candidate_ingredient >= baseline_ingredient,
            (
                f"candidate_ingredient_recall={candidate_ingredient:.6f}, "
                f"baseline_ingredient_recall={baseline_ingredient:.6f}"
            ),
        )

    candidate_variant = _report_optional_metric(candidate_context.get("variant_recall"))
    if candidate_variant is None:
        _add_gate(
            "variant_recall_nonzero",
            False,
            "Missing candidate RECIPE_VARIANT recall.",
        )
    else:
        _add_gate(
            "variant_recall_nonzero",
            candidate_variant > 0.0,
            f"candidate_variant_recall={candidate_variant:.6f}",
        )

    debug_payload = candidate_context.get("debug_artifacts")
    if not isinstance(debug_payload, dict):
        _add_gate(
            "debug_artifacts_present",
            False,
            "Missing candidate debug artifact payload.",
        )
    else:
        mode_source = str(candidate_context.get("codex_farm_mode_source") or "").strip()
        if not mode_source:
            mode_source = "unknown"
        requires_debug = bool(debug_payload.get("required"))
        skip_required_debug = False
        hard_failure_mode_source = False
        if mode_source == "inferred" and requires_debug:
            _add_warning(
                (
                    f"Running benchmark-only debug checks for {source_key} using "
                    "inferred benchmark mode from artifacts (metadata missing)."
                )
            )
        elif mode_source == "unknown":
            _add_warning(
                (
                    f"Could not confirm benchmark mode for {source_key}: "
                    "mode metadata is missing and artifact signals are not conclusive."
                )
            )
            if requires_debug:
                _add_warning(
                    f"Skipping benchmark-only debug checks for {source_key}: "
                    "mode could not be determined from metadata or artifacts."
                )
                skip_required_debug = True
        elif mode_source != "metadata":
            _add_warning(f"Unrecognized mode_source for {source_key}: {mode_source}.")
            _add_gate(
                "debug_artifacts_present",
                False,
                f"Invalid mode source reported for benchmark comparison: {mode_source}.",
            )
            hard_failure_mode_source = True

        if hard_failure_mode_source:
            pass
        elif skip_required_debug:
            _add_gate(
                "debug_artifacts_present",
                True,
                (
                    "Not required: "
                    f"mode={candidate_context.get('codex_farm_recipe_mode')}, "
                    f"llm_recipe_pipeline={candidate_context.get('llm_recipe_pipeline')}"
                ),
            )
        else:
            missing = debug_payload.get("missing")
            if not isinstance(missing, list):
                missing = []
            passed = bool(debug_payload.get("all_present"))
            _add_gate(
                "debug_artifacts_present",
                passed,
                (
                    "Required debug artifacts present."
                    if passed
                    else "Missing required debug artifacts: "
                    + ", ".join(str(name) for name in missing)
                ),
            )

    failed_gate_count = sum(1 for gate in gates if not bool(gate.get("passed")))
    passed_gate_count = len(gates) - failed_gate_count
    overall_verdict = "PASS" if failed_gate_count == 0 else "FAIL"

    return {
        "schema_version": LABELSTUDIO_BENCHMARK_COMPARE_SCHEMA_VERSION,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "comparison_mode": "single_eval_report",
        "baseline_report_root": str(baseline_eval_report_path.parent),
        "candidate_report_root": str(candidate_eval_report_path.parent),
        "baseline_eval_report_path": str(baseline_eval_report_path),
        "candidate_eval_report_path": str(candidate_eval_report_path),
        "overall": {
            "verdict": overall_verdict,
            "gate_count": len(gates),
            "passed_gate_count": passed_gate_count,
            "failed_gate_count": failed_gate_count,
        },
        "warnings": warnings,
        "gates": gates,
        "sources": source_comparison,
    }


def _format_labelstudio_benchmark_compare_markdown(
    payload: dict[str, Any],
) -> str:
    lines = [
        "# Labelstudio Benchmark Compare",
        "",
        f"- Schema version: {payload.get('schema_version', '')}",
        f"- Created at: {payload.get('created_at', '')}",
        f"- Baseline report root: {payload.get('baseline_report_root', '')}",
        f"- Candidate report root: {payload.get('candidate_report_root', '')}",
    ]
    overall = payload.get("overall")
    warnings = payload.get("warnings")
    if isinstance(overall, dict):
        lines.extend(
            [
                f"- Verdict: {overall.get('verdict', 'UNKNOWN')}",
                (
                    "- Gates passed/total/failed: "
                    f"{_report_count(overall.get('passed_gate_count'))}/"
                    f"{_report_count(overall.get('gate_count'))}"
                    f"/{_report_count(overall.get('failed_gate_count'))}"
                ),
            ]
        )
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {str(warning)}")
    lines.extend(
        [
            "",
            "## Gate Results",
            "",
            "| Gate | Status | Reason |",
            "| --- | --- | --- |",
        ]
    )
    gates = payload.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            gate_name = str(gate.get("name") or "").strip() or "<unknown>"
            status = "PASS" if bool(gate.get("passed")) else "FAIL"
            reason = str(gate.get("reason") or "").strip()
            lines.append(
                f"| `{gate_name}` | {status} | {reason.replace('|', '\\|')} |"
            )
    lines.extend(
        [
            "",
            "## Source Deltas",
            "",
            "| Source | Delta Practical F1 | Delta Line Accuracy | Delta Ingredient Recall | Delta Variant Recall |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    sources = payload.get("sources")
    if isinstance(sources, dict):
        for source_key in sorted(sources.keys()):
            source_payload = sources.get(source_key)
            if not isinstance(source_payload, dict):
                continue
            deltas = source_payload.get("deltas")
            if not isinstance(deltas, dict):
                deltas = {}
            practical_delta = _report_optional_metric(deltas.get("practical_f1"))
            line_delta = _report_optional_metric(deltas.get("overall_line_accuracy"))
            ingredient_delta = _report_optional_metric(deltas.get("ingredient_recall"))
            variant_delta = _report_optional_metric(deltas.get("variant_recall"))
            lines.append(
                "| "
                + source_key
                + " | "
                + (f"{practical_delta:.6f}" if practical_delta is not None else "null")
                + " | "
                + (f"{line_delta:.6f}" if line_delta is not None else "null")
                + " | "
                + (f"{ingredient_delta:.6f}" if ingredient_delta is not None else "null")
                + " | "
                + (f"{variant_delta:.6f}" if variant_delta is not None else "null")
            + " |"
        )

    lines.extend(
        [
            "",
            "## Source Debug Artifact Checks (candidate source only)",
            "",
        ]
    )
    sources = payload.get("sources")
    if isinstance(sources, dict):
        for source_key in sorted(sources.keys()):
            source_payload = sources.get(source_key)
            if not isinstance(source_payload, dict):
                continue
            candidate_payload = source_payload.get("candidate")
            if not isinstance(candidate_payload, dict):
                continue
            debug_payload = candidate_payload.get("debug_artifacts")
            if not isinstance(debug_payload, dict):
                continue
            checks = debug_payload.get("checks")
            if not isinstance(checks, list):
                continue
            lines.append(f"### {source_key}")
            lines.append("")
            lines.append("| Check | Required | Present | Path | Count |")
            lines.append("| --- | --- | --- | --- | --- |")
            for check in checks:
                if not isinstance(check, dict):
                    continue
                check_name = str(check.get("name") or "").strip() or "<unknown>"
                required = (
                    "YES"
                    if check_name in debug_payload.get("required_checks", [])
                    else "NO"
                )
                present = "yes" if bool(check.get("present")) else "no"
                count = str(check.get("count") if check.get("count") is not None else "")
                path = str(check.get("path") or "").strip().replace("|", "\\|")
                lines.append(
                    f"| `{check_name}` | {required} | {present} | {path} | {count} |"
                )
            lines.append("")

    return "\n".join(lines) + "\n"


def _format_labelstudio_benchmark_compare_gates_markdown(
    payload: dict[str, Any],
) -> str:
    lines = [
        "## Gate Results",
        "",
        "| Gate | Status | Reason |",
        "| --- | --- | --- |",
    ]
    gates = payload.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            gate_name = str(gate.get("name") or "").strip() or "<unknown>"
            status = "PASS" if bool(gate.get("passed")) else "FAIL"
            reason = str(gate.get("reason") or "").strip().replace("|", "\\|")
            lines.append(f"| `{gate_name}` | {status} | {reason} |")
    return "\n".join(lines) + "\n"


def labelstudio_benchmark_compare(
    *,
    baseline: Path,
    candidate: Path,
    out_dir: Path = DEFAULT_LABELSTUDIO_BENCHMARK_COMPARISONS,
    fail_on_regression: bool = False,
) -> dict[str, Any]:
    baseline_target = _resolve_labelstudio_benchmark_compare_input(baseline)
    if baseline_target is None:
        _fail(
            "Unable to resolve baseline compare input from: "
            f"{baseline}"
        )
    candidate_target = _resolve_labelstudio_benchmark_compare_input(candidate)
    if candidate_target is None:
        _fail(
            "Unable to resolve candidate compare input from: "
            f"{candidate}"
        )
    baseline_mode = str(baseline_target.get("mode") or "").strip()
    candidate_mode = str(candidate_target.get("mode") or "").strip()
    if baseline_mode != candidate_mode:
        _fail(
            "Compare input mode mismatch: baseline and candidate must both be all-method roots "
            "or both be single eval_report inputs."
        )

    if baseline_mode == "single_eval_report":
        baseline_eval_report_path = baseline_target.get("eval_report_path")
        candidate_eval_report_path = candidate_target.get("eval_report_path")
        if not isinstance(baseline_eval_report_path, Path) or not isinstance(
            candidate_eval_report_path, Path
        ):
            _fail("Compare single-eval mode resolution failed: eval_report paths missing.")
        comparison = _build_labelstudio_benchmark_compare_single_eval_payload(
            baseline_eval_report_path=baseline_eval_report_path,
            candidate_eval_report_path=candidate_eval_report_path,
        )
    else:
        baseline_root = baseline_target.get("report_root")
        candidate_root = candidate_target.get("report_root")
        if not isinstance(baseline_root, Path) or not isinstance(candidate_root, Path):
            _fail("Compare all-method mode resolution failed: report roots missing.")
        comparison = _build_labelstudio_benchmark_compare_payload(
            baseline_report_root=baseline_root,
            candidate_report_root=candidate_root,
        )
    comparison_root = out_dir / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    comparison_root.mkdir(parents=True, exist_ok=True)
    comparison_json_path = comparison_root / "comparison.json"
    comparison_md_path = comparison_root / "comparison.md"
    comparison_json_path.write_text(
        json.dumps(comparison, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    comparison_md_path.write_text(
        _format_labelstudio_benchmark_compare_markdown(comparison),
        encoding="utf-8",
    )
    verdict = str((comparison.get("overall") or {}).get("verdict") or "UNKNOWN").upper()
    typer.secho(
        f"Labelstudio benchmark compare verdict: {verdict}",
        fg=typer.colors.GREEN if verdict == "PASS" else typer.colors.YELLOW,
    )
    warnings = comparison.get("warnings")
    if isinstance(warnings, list) and warnings:
        typer.secho("Warnings:", fg=typer.colors.YELLOW)
        for warning in warnings:
            typer.secho(f"- {str(warning)}", fg=typer.colors.YELLOW)
    typer.echo(_format_labelstudio_benchmark_compare_gates_markdown(comparison).rstrip("\n"))
    typer.secho(f"Report: {comparison_md_path}", fg=typer.colors.CYAN)
    typer.secho(f"JSON: {comparison_json_path}", fg=typer.colors.CYAN)
    if fail_on_regression and verdict == "FAIL":
        raise typer.Exit(1)
    return comparison


def _interactive_mode(*, limit: int | None = None) -> None:
    """Run the interactive guided flow."""
    typer.secho("\n  Recipe Import Tool\n", fg=typer.colors.CYAN, bold=True)

    input_folder = DEFAULT_INPUT
    settings = _load_settings()

    while True:
        output_folder = Path(str(settings.get("output_dir") or DEFAULT_INTERACTIVE_OUTPUT)).expanduser()
        # Scan for importable files first to know what context to show
        importable_files = _list_importable_files(input_folder)
        choices = []
        if importable_files:
            choices.append(
                questionary.Choice(
                    "Stage: Convert files from data/input into cookbook outputs",
                    value="import",
                )
            )
            choices.append(
                questionary.Choice(
                    "Label Studio upload: Create labeling tasks (uploads)",
                    value="labelstudio",
                )
            )
        choices.append(
            questionary.Choice(
                "Label Studio export: Export completed labels into golden artifacts",
                value="labelstudio_export",
            )
        )
        choices.append(
            questionary.Choice(
                "Evaluate vs freeform gold: Generate predictions and compare to your labels",
                value="labelstudio_benchmark",
            )
        )
        choices.append(
            questionary.Choice(
                "Dashboard: Build lifetime stats dashboard HTML",
                value="generate_dashboard",
            )
        )
        choices.append(
            questionary.Choice(
                "Settings: Change saved interactive defaults",
                value="settings",
            )
        )
        choices.append(questionary.Choice("Exit: Close the tool", value="exit"))

        action = _menu_select(
            "What would you like to do?",
            choices=choices,
            menu_help=(
                "Pick a workflow. Stage converts files into cookbook outputs. Label Studio upload "
                "creates annotation tasks. Export pulls completed labels into golden artifacts. "
                "Evaluate runs predictions and compares them against freeform gold. Dashboard "
                "builds a static lifetime summary."
            ),
        )

        if action == BACK_ACTION:
            continue

        if action is None or action == "exit":
            raise typer.Exit(0)

        if action == "generate_dashboard":
            typer.secho(
                f"Generating dashboard from {output_folder}...",
                fg=typer.colors.CYAN,
            )
            stats_dashboard(
                output_root=output_folder,
                golden_root=DEFAULT_GOLDEN,
                out_dir=history_root_for_output(output_folder) / "dashboard",
                open_browser=False,
                since_days=None,
                scan_reports=False,
            )
            continue

        if action == "settings":
            _settings_menu(settings)
            continue

        elif action == "import":
            if not importable_files:
                # Should be unreachable given the check above, but safe to keep
                typer.secho(
                    f"\nNo supported files found in {input_folder}",
                    fg=typer.colors.YELLOW,
                )
                input("Press Enter to continue...")
                continue

            typer.secho(f"\nFound {len(importable_files)} importable file(s) in {input_folder}", fg=typer.colors.GREEN)

            selection = _menu_select(
                "Which file(s) would you like to import?",
                menu_help=(
                    "Import All processes every supported file in data/input. "
                    "Choosing one file runs conversion only for that file."
                ),
                choices=[
                    questionary.Choice(
                        "Import all: Process every supported file",
                        value="all",
                    ),
                    *[questionary.Choice(f.name, value=f) for f in importable_files]
                ]
            )

            if selection in {None, BACK_ACTION}:
                continue

            typer.echo()

            global_run_settings = RunSettings.from_dict(
                _run_settings_payload_from_settings(settings),
                warn_context="interactive global settings",
            )
            selected_run_settings = choose_run_settings(
                global_defaults=global_run_settings,
                output_dir=output_folder,
                menu_select=_menu_select,
                back_action=BACK_ACTION,
                prompt_confirm=_prompt_confirm,
                prompt_text=_prompt_text,
                prompt_codex_ai_settings=True,
                prompt_recipe_pipeline_menu=True,
                interactive_codex_surface_options=("recipe", "knowledge"),
            )
            if selected_run_settings is None:
                typer.secho("Import cancelled.", fg=typer.colors.YELLOW)
                continue

            typer.secho(
                f"Run settings hash: {selected_run_settings.short_hash()}",
                fg=typer.colors.CYAN,
            )

            # Apply EPUB settings via env vars (read at call time by epub.py).
            os.environ["C3IMP_EPUB_EXTRACTOR"] = selected_run_settings.epub_extractor.value
            _set_epub_unstructured_env(
                html_parser_version=selected_run_settings.epub_unstructured_html_parser_version.value,
                skip_headers_footers=selected_run_settings.epub_unstructured_skip_headers_footers,
                preprocess_mode=selected_run_settings.epub_unstructured_preprocess_mode.value,
            )

            common_args = build_stage_call_kwargs_from_run_settings(
                selected_run_settings,
                out=output_folder,
                mapping=None,
                overrides=None,
                limit=limit,
                write_markdown=True,
            )
            common_args["allow_codex"] = codex_surfaces_enabled(
                selected_run_settings.to_run_config_dict()
            )

            if selection == "all":
                run_folder = stage(path=input_folder, **common_args)
            else:
                run_folder = stage(path=selection, **common_args)

            typer.secho(f"\nOutputs written to: {run_folder}", fg=typer.colors.CYAN)
            continue

        elif action == "labelstudio":
            if not importable_files:
                typer.secho(
                    f"\nNo supported files found in {input_folder}",
                    fg=typer.colors.YELLOW,
                )
                input("Press Enter to continue...")
                continue

            file_choices = [
                questionary.Choice(f.name, value=f) for f in importable_files
            ]
            selected_file = _menu_select(
                "Select a file to import into Label Studio:",
                choices=file_choices,
                menu_help="Pick the source file to turn into Label Studio tasks.",
            )

            if selected_file in {None, BACK_ACTION}:
                continue

            project_name = _prompt_text(
                "Project name (leave blank to auto-name):",
                default="",
            )
            if project_name is None:
                continue
            if project_name is not None:
                project_name = project_name.strip() or None

            # Label Studio import is freeform-only.
            segment_blocks = 40
            segment_overlap = 5
            segment_focus_blocks = 40
            target_task_count: int | None = None
            prelabel = False
            prelabel_provider = "codex-farm"
            prelabel_timeout_seconds = DEFAULT_PRELABEL_TIMEOUT_SECONDS
            prelabel_cache_dir: Path | None = None
            prelabel_workers = 15
            prelabel_upload_as = "annotations"
            prelabel_granularity = PRELABEL_GRANULARITY_BLOCK
            prelabel_allow_partial = False
            codex_cmd: str | None = None
            codex_model: str | None = None
            codex_reasoning_effort: str | None = None
            prelabel_track_token_usage = True

            freeform_segment_settings = _prompt_freeform_segment_settings(
                segment_blocks_default=segment_blocks,
                segment_overlap_default=segment_overlap,
                segment_focus_blocks_default=segment_focus_blocks,
                target_task_count_default=target_task_count,
            )
            if freeform_segment_settings is None:
                continue
            (
                segment_blocks,
                segment_overlap,
                segment_focus_blocks,
                target_task_count,
            ) = freeform_segment_settings
            prelabel_mode = _menu_select(
                "AI prelabel mode before upload:",
                menu_help=(
                    "Choose strict vs allow-partial behavior for AI prelabels. "
                    "Predictions mode is an advanced/debug option."
                ),
                choices=[
                    questionary.Choice(
                        "off - upload tasks without AI prelabels",
                        value=(False, "annotations", False),
                    ),
                    questionary.Choice(
                        "strict annotations (recommended) - fail upload if any prelabel task fails",
                        value=(True, "annotations", False),
                    ),
                    questionary.Choice(
                        "allow-partial annotations - continue upload and record failures",
                        value=(True, "annotations", True),
                    ),
                    questionary.Choice(
                        "strict predictions (advanced) - upload AI output as predictions",
                        value=(True, "predictions", False),
                    ),
                    questionary.Choice(
                        "allow-partial predictions (advanced) - predictions + partial failures",
                        value=(True, "predictions", True),
                    ),
                ],
            )
            if prelabel_mode in {None, BACK_ACTION}:
                continue
            prelabel, prelabel_upload_as, prelabel_allow_partial = prelabel_mode
            if prelabel:
                prelabel_granularity_choice = _menu_select(
                    "AI prelabel labeling style:",
                    menu_help=(
                        "Choose between real freeform span highlighting and "
                        "the older one-label-per-block behavior."
                    ),
                    choices=[
                        questionary.Choice(
                            "actual freeform - allow sub-block span highlights",
                            value=PRELABEL_GRANULARITY_SPAN,
                        ),
                        questionary.Choice(
                            "block based - one label per block",
                            value=PRELABEL_GRANULARITY_BLOCK,
                        ),
                    ],
                )
                if prelabel_granularity_choice in {None, BACK_ACTION}:
                    continue
                prelabel_granularity = str(prelabel_granularity_choice)
                codex_cmd = default_codex_cmd()
                resolved_account = codex_account_summary(codex_cmd)
                if resolved_account:
                    typer.secho(
                        f"Prelabel account: {resolved_account}",
                        fg=typer.colors.CYAN,
                    )
                else:
                    typer.secho(
                        "Prelabel account: unavailable for selected command.",
                        fg=typer.colors.YELLOW,
                    )

                detected_model = default_codex_model(cmd=codex_cmd)
                detected_label = detected_model or "pipeline/default model"
                discovered_models = list_codex_models(cmd=codex_cmd)
                supported_efforts_by_model: dict[str, tuple[str, ...]] = {}
                model_choices: list[QuestionaryChoice] = [
                    questionary.Choice(
                        f"use Codex default ({detected_label})",
                        value="__default__",
                    )
                ]
                seen_model_ids: set[str] = set()
                for entry in discovered_models:
                    model_id = str(entry.get("slug") or "").strip()
                    if not model_id or model_id in seen_model_ids:
                        continue
                    description = str(entry.get("description") or "").strip()
                    label = model_id if not description else f"{model_id} - {description}"
                    model_choices.append(questionary.Choice(label, value=model_id))
                    raw_supported_efforts = entry.get("supported_reasoning_efforts")
                    if isinstance(raw_supported_efforts, list):
                        normalized_supported_efforts: list[str] = []
                        for raw_effort in raw_supported_efforts:
                            if not isinstance(raw_effort, str):
                                continue
                            try:
                                normalized_effort = normalize_codex_reasoning_effort(
                                    raw_effort
                                )
                            except ValueError:
                                continue
                            if (
                                normalized_effort
                                and normalized_effort
                                not in normalized_supported_efforts
                            ):
                                normalized_supported_efforts.append(normalized_effort)
                        if normalized_supported_efforts:
                            supported_efforts_by_model[model_id] = tuple(
                                normalized_supported_efforts
                            )
                    seen_model_ids.add(model_id)
                if not seen_model_ids:
                    model_choices.append(
                        questionary.Choice("gpt-5.3-codex", value="gpt-5.3-codex")
                    )
                model_choices.append(
                    questionary.Choice("custom model id...", value="__custom__")
                )
                model_choice = _menu_select(
                    "Codex model for AI prelabeling:",
                    menu_help=(
                        "Pick a model explicitly for this run, or leave it on the "
                        "pipeline/default model."
                    ),
                    choices=model_choices,
                )
                if model_choice in {None, BACK_ACTION}:
                    continue
                if model_choice == "__custom__":
                    custom_default = detected_model or ""
                    custom_model = _prompt_text(
                        "Codex model id:",
                        default=custom_default,
                    )
                    if custom_model is None:
                        continue
                    codex_model = custom_model.strip() or None
                elif model_choice == "__default__":
                    codex_model = None
                else:
                    codex_model = str(model_choice)

                selected_model = (codex_model or detected_model or "").strip()
                allowed_efforts = [
                    effort
                    for effort in CODEX_REASONING_EFFORT_VALUES
                    if effort != "minimal"
                ]
                model_supported_efforts = (
                    supported_efforts_by_model.get(selected_model)
                    if selected_model
                    else None
                )
                if model_supported_efforts:
                    supported_set = set(model_supported_efforts)
                    allowed_efforts = [
                        effort for effort in allowed_efforts if effort in supported_set
                    ]

                detected_effort = codex_reasoning_effort_from_cmd(
                    codex_cmd
                ) or default_codex_reasoning_effort(cmd=codex_cmd)
                detected_effort_label = detected_effort or "config default"
                effort_description = {
                    "none": "disable extra reasoning",
                    "minimal": "lightest reasoning",
                    "low": "low reasoning budget",
                    "medium": "balanced reasoning",
                    "high": "deeper reasoning",
                    "xhigh": "maximum reasoning",
                }
                effort_choices: list[QuestionaryChoice] = []
                if detected_effort is None or detected_effort in allowed_efforts:
                    effort_choices.append(
                        questionary.Choice(
                            f"use Codex default ({detected_effort_label})",
                            value="__default_effort__",
                        )
                    )
                else:
                    typer.secho(
                        (
                            f"Codex default thinking effort '{detected_effort}' "
                            "is incompatible with this model/workflow."
                        ),
                        fg=typer.colors.YELLOW,
                    )
                for effort in allowed_efforts:
                    detail = effort_description.get(effort, "")
                    label = effort if not detail else f"{effort} - {detail}"
                    effort_choices.append(
                        questionary.Choice(label, value=effort)
                    )
                if not effort_choices:
                    typer.secho(
                        "No compatible Codex thinking effort options are available.",
                        fg=typer.colors.RED,
                    )
                    continue
                effort_choice = _menu_select(
                    "Codex thinking effort for AI prelabeling:",
                    menu_help=(
                        "Pick a reasoning effort for this run "
                        "(Codex config: model_reasoning_effort). "
                        "Minimal is hidden due Codex tool requirements."
                    ),
                    choices=effort_choices,
                )
                if effort_choice in {None, BACK_ACTION}:
                    continue
                if effort_choice == "__default_effort__":
                    codex_reasoning_effort = None
                else:
                    codex_reasoning_effort = str(effort_choice)

            # Interactive flow always recreates the project if it exists.
            overwrite = True

            resolved_creds = _resolve_interactive_labelstudio_settings(settings)
            if resolved_creds is None:
                continue
            url, api_key = resolved_creds
            interactive_import_timeseries_path = _processing_timeseries_history_path(
                root=_golden_sent_to_labelstudio_root(),
                scope="labelstudio_import",
                source_name=selected_file.name,
            )

            import_started_at = time.monotonic()
            try:
                result = _run_labelstudio_import_with_status(
                    source_name=selected_file.name,
                    telemetry_path=interactive_import_timeseries_path,
                    run_import=lambda update_progress: run_labelstudio_import(
                        path=selected_file,
                        output_dir=_golden_sent_to_labelstudio_root(),
                        pipeline="auto",
                        project_name=project_name,
                        segment_blocks=segment_blocks,
                        segment_overlap=segment_overlap,
                        segment_focus_blocks=segment_focus_blocks,
                        target_task_count=target_task_count,
                        overwrite=overwrite,
                        resume=False,
                        label_studio_url=url,
                        label_studio_api_key=api_key,
                        limit=None,
                        sample=None,
                        progress_callback=update_progress,
                        prelabel=prelabel,
                        prelabel_provider=prelabel_provider,
                        codex_cmd=codex_cmd,
                        codex_model=codex_model,
                        codex_reasoning_effort=codex_reasoning_effort,
                        prelabel_timeout_seconds=prelabel_timeout_seconds,
                        prelabel_cache_dir=prelabel_cache_dir,
                        prelabel_workers=prelabel_workers,
                        prelabel_upload_as=prelabel_upload_as,
                        prelabel_granularity=prelabel_granularity,
                        prelabel_allow_partial=prelabel_allow_partial,
                        prelabel_track_token_usage=prelabel_track_token_usage,
                        allow_labelstudio_write=True,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                _fail(str(exc))
            processing_time_seconds = max(0.0, time.monotonic() - import_started_at)

            typer.secho(
                f"Label Studio project: {result['project_name']} (id={result['project_id']})",
                fg=typer.colors.GREEN,
            )
            typer.secho(
                f"Tasks created: {result['tasks_total']} (uploaded {result['tasks_uploaded']})",
                fg=typer.colors.CYAN,
            )
            typer.secho(
                f"Processing time: {_format_processing_time(processing_time_seconds)}",
                fg=typer.colors.CYAN,
            )
            typer.secho(
                f"Processing telemetry: {interactive_import_timeseries_path}",
                fg=typer.colors.BRIGHT_BLACK,
            )
            if prelabel:
                _print_prelabel_completion_summary(
                    prelabel_summary=result.get("prelabel") or {},
                    report_path=result.get("prelabel_report_path"),
                    inline_annotation_fallback=bool(
                        result.get("prelabel_inline_annotations_fallback")
                    ),
                )
            typer.secho(f"Artifacts saved to: {result['run_root']}", fg=typer.colors.CYAN)
            continue

        elif action == "labelstudio_export":
            target_output_dir = _golden_pulled_from_labelstudio_root()

            resolved_creds = _resolve_interactive_labelstudio_settings(settings)
            if resolved_creds is None:
                continue
            url, api_key = resolved_creds
            project_name, detected_scope = _select_export_project(
                label_studio_url=url,
                label_studio_api_key=api_key,
            )
            if not project_name:
                continue
            if detected_scope:
                typer.secho(
                    f"Detected project type: {detected_scope}",
                    fg=typer.colors.BRIGHT_BLACK,
                )

            try:
                result = run_labelstudio_export(
                    project_name=project_name,
                    output_dir=target_output_dir,
                    label_studio_url=url,
                    label_studio_api_key=api_key,
                    run_dir=None,
                )
            except Exception as exc:  # noqa: BLE001
                _fail(str(exc))

            typer.secho(
                f"Export complete. Summary: {result['summary_path']}",
                fg=typer.colors.GREEN,
            )
            continue

        elif action == "labelstudio_benchmark":
            benchmark_eval_output = (
                _golden_benchmark_root()
                / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
            )

            benchmark_mode = _menu_select(
                "How would you like to evaluate?",
                menu_help=(
                    "All modes are offline (no upload).\n"
                    "Single book runs one local prediction + eval vs freeform gold.\n"
                    "Selected matched books lets you pick specific books.\n"
                    "All matched books repeats that same config across each matched golden set."
                ),
                choices=[
                    questionary.Choice(
                        "Single Book: One local prediction + eval vs freeform gold",
                        value=INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK,
                    ),
                    questionary.Choice(
                        "Selected Matched Books: Pick which matched books to run",
                        value=INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS,
                    ),
                    questionary.Choice(
                        "All Matched Books: Repeat one config for every matched golden set",
                        value=INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS,
                    ),
                ],
            )
            if benchmark_mode in {None, BACK_ACTION}:
                continue

            benchmark_defaults_payload = {
                key: value
                for key, value in settings.items()
                if key in RunSettings.model_fields
            }
            benchmark_defaults = RunSettings.from_dict(
                benchmark_defaults_payload,
                warn_context="interactive benchmark global settings",
            )
            selected_benchmark_settings = choose_run_settings(
                global_defaults=benchmark_defaults,
                output_dir=output_folder,
                menu_select=_menu_select,
                back_action=BACK_ACTION,
                prompt_confirm=_prompt_confirm,
                prompt_text=_prompt_text,
                prompt_codex_ai_settings=True,
                prompt_recipe_pipeline_menu=True,
                prompt_benchmark_llm_surface_toggles=True,
            )
            if selected_benchmark_settings is None:
                typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
                continue

            typer.secho(
                f"Run settings hash: {selected_benchmark_settings.short_hash()}",
                fg=typer.colors.CYAN,
            )

            benchmark_write_markdown = _coerce_bool_setting(
                os.getenv(COOKIMPORT_BENCH_WRITE_MARKDOWN_ENV),
                default=True,
            )
            benchmark_write_labelstudio_tasks = _coerce_bool_setting(
                os.getenv(COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS_ENV),
                default=False,
            )
            benchmark_write_single_book_starter_pack = _coerce_bool_setting(
                os.getenv(COOKIMPORT_BENCH_SINGLE_BOOK_WRITE_STARTER_PACK_ENV),
                default=False,
            )

            if benchmark_mode == INTERACTIVE_BENCHMARK_MODE_SINGLE_BOOK:
                _interactive_single_book_benchmark(
                    selected_benchmark_settings=selected_benchmark_settings,
                    benchmark_eval_output=benchmark_eval_output,
                    processed_output_root=output_folder,
                    write_markdown=benchmark_write_markdown,
                    write_label_studio_tasks=benchmark_write_labelstudio_tasks,
                    write_starter_pack=benchmark_write_single_book_starter_pack,
                )
            elif benchmark_mode in {
                INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS,
                INTERACTIVE_BENCHMARK_MODE_ALL_MATCHED_BOOKS,
            }:
                _interactive_single_profile_all_matched_benchmark(
                    selected_benchmark_settings=selected_benchmark_settings,
                    benchmark_eval_output=benchmark_eval_output,
                    processed_output_root=output_folder,
                    write_markdown=benchmark_write_markdown,
                    write_label_studio_tasks=benchmark_write_labelstudio_tasks,
                    allow_subset_selection=(
                        benchmark_mode
                        == INTERACTIVE_BENCHMARK_MODE_SELECTED_MATCHED_BOOKS
                    ),
                )
            continue


@app.callback()
def main(ctx: typer.Context) -> None:
    """Recipe Import - Convert source files to schema.org Recipe JSON and cookbook3 outputs."""
    if ctx.invoked_subcommand is None:
        limit_value = os.getenv("C3IMP_LIMIT")
        limit = None
        if limit_value:
            try:
                limit = int(limit_value)
            except ValueError:
                limit = None
        interactive_mode_token = _INTERACTIVE_CLI_ACTIVE.set(True)
        try:
            _interactive_mode(limit=limit)
        finally:
            _INTERACTIVE_CLI_ACTIVE.reset(interactive_mode_token)


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
            f"Expected one of: off, {KNOWLEDGE_CODEX_PIPELINE_SHARD_V1}."
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


def _normalize_single_book_split_cache_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "off", "none", "disabled", "false", "0"}:
        return "off"
    if normalized in {"auto", "on", "enabled", "true", "1"}:
        return "auto"
    _fail(
        f"Invalid single-book split-cache mode: {value!r}. "
        "Expected one of: off, auto."
    )
    return "off"


def _normalize_codex_farm_recipe_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "extract", "default"}:
        return CODEX_FARM_RECIPE_MODE_EXTRACT
    if normalized in {"benchmark", "line-labels", "line-label"}:
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
            f"Expected one of: off, {LINE_ROLE_PIPELINE_SHARD_V1}."
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


def _extract_progress_counter(message: str) -> tuple[int, int] | None:
    """Extract the right-most X/Y counter from a status message."""
    trimmed = message.strip()
    if not trimmed:
        return None

    # All-method dashboard snapshots include many counters; prefer the top-line
    # overall config counter so ETA tracks completed configs.
    first_line = trimmed.splitlines()[0].strip()
    if first_line.lower().startswith("overall source "):
        first_line_matches = list(_STATUS_COUNTER_PATTERN.finditer(first_line))
        for match in reversed(first_line_matches):
            try:
                current = int(match.group(1))
                total = int(match.group(2))
            except (TypeError, ValueError):
                continue
            if total <= 0:
                continue
            return max(0, min(current, total)), total

    matches = list(_STATUS_COUNTER_PATTERN.finditer(trimmed))
    for match in reversed(matches):
        try:
            current = int(match.group(1))
            total = int(match.group(2))
        except (TypeError, ValueError):
            continue
        if total <= 0:
            continue
        return max(0, min(current, total)), total
    return None


_PROGRESS_STAGE_COUNTER_SUFFIX_RE = re.compile(
    r"\s+(?:task|item|config|phase)\s+\d+/\d+\s*$",
    re.IGNORECASE,
)


def _extract_progress_stage_label(message: str) -> str | None:
    """Extract a stable stage label from a progress message."""
    trimmed = str(message or "").strip()
    if not trimmed:
        return None
    first_line = trimmed.splitlines()[0].strip()
    if not first_line:
        return None
    if first_line.lower().startswith("overall source "):
        return first_line
    base = first_line.split("|", 1)[0].strip()
    if not base:
        return None
    base = _PROGRESS_STAGE_COUNTER_SUFFIX_RE.sub("", base).strip()
    return base or None


def _is_structured_progress_message(message: str) -> bool:
    cleaned = str(message or "").strip()
    return (
        parse_worker_activity(cleaned) is not None
        or parse_stage_progress(cleaned) is not None
    )


def _extract_active_tasks(message: str) -> list[str] | None:
    match = _STATUS_ACTIVE_TASKS_RE.search(str(message or ""))
    if match is None:
        return None
    raw = str(match.group(1)).strip()
    if not raw:
        return []
    values = [item.strip() for item in raw.split(",")]
    return [value for value in values if value]


def _extract_running_workers(message: str) -> int | None:
    match = _STATUS_RUNNING_WORKERS_RE.search(str(message or ""))
    if match is None:
        return None
    try:
        return max(0, int(match.group(1)))
    except (TypeError, ValueError):
        return None


def _humanize_codex_pipeline_stage_label(pipeline_id: str) -> str:
    normalized = str(pipeline_id or "").strip()
    lowered = normalized.lower()
    if not normalized:
        return "codex stage"
    if "recipe.correction" in lowered or "recipe_correction" in lowered or "correction" in lowered:
        return "recipe correction"
    if "knowledge" in lowered:
        return "non-recipe knowledge review"
    if "tags" in lowered:
        return "tag suggestions"
    return normalized


def _summarize_codex_progress_message(message: str) -> tuple[str, str | None]:
    trimmed = str(message or "").strip()
    match = _STATUS_CODEX_FARM_PIPELINE_PREFIX_RE.match(trimmed)
    if match is None:
        return trimmed, None

    raw_pipeline = str(match.group("pipeline") or "").strip()
    pipeline_id = raw_pipeline[:-1] if raw_pipeline.endswith(":") else raw_pipeline
    stage_label = _humanize_codex_pipeline_stage_label(pipeline_id)
    counter = _extract_progress_counter(trimmed)
    running = _extract_running_workers(trimmed)

    if counter is not None:
        current, total = counter
        parts = [
            f"codex-farm {stage_label}",
            f"task {current}/{total}",
        ]
        if running is not None and running > 0:
            parts.append(f"running {running}")
        return " | ".join(parts), stage_label

    suffix = trimmed[match.end() :].strip()
    if suffix.startswith(":"):
        suffix = suffix[1:].strip()
    if suffix:
        return f"codex-farm {stage_label}: {suffix}", stage_label
    return f"codex-farm {stage_label}", stage_label


def _format_seconds_per_task(seconds_per_task: float) -> str:
    formatted = f"{max(0.0, seconds_per_task):.1f}".rstrip("0").rstrip(".")
    return f"{formatted}s/task"


def _looks_like_all_method_dashboard_snapshot(message: str) -> bool:
    trimmed = str(message or "").strip()
    return bool(trimmed and trimmed.startswith("overall source ") and "\nqueue:" in trimmed)


def _extract_all_method_dashboard_metrics(message: str) -> dict[str, int]:
    trimmed = str(message or "").strip()
    if not _looks_like_all_method_dashboard_snapshot(trimmed):
        return {}
    for raw_line in trimmed.splitlines():
        line = raw_line.strip().lower()
        if not line.startswith("task:"):
            continue
        payload = line.split(":", 1)[1].strip()
        metrics: dict[str, int] = {}
        for part in payload.split("|"):
            segment = part.strip()
            if not segment:
                continue
            match = re.search(r"\b(active|pending|eval|wing)\s+(\d+)\b", segment)
            if match is None:
                continue
            key = match.group(1)
            value = max(0, int(match.group(2)))
            metrics[key] = value
        return metrics
    return {}


def _recent_rate_average_seconds_per_task(
    samples: deque[tuple[float, int]],
) -> float | None:
    if not samples:
        return None

    max_steps = max(1, len(_STATUS_ETA_RECENT_STEP_WEIGHTS))
    # Build a most-recent-first list of per-step durations from sampled deltas.
    recent_step_seconds: list[float] = []
    most_recent_step_seconds: float | None = None
    for elapsed_seconds, completed_units in reversed(samples):
        elapsed_value = float(elapsed_seconds)
        units_value = int(completed_units)
        if elapsed_value <= 0 or units_value <= 0:
            continue
        per_step_seconds = elapsed_value / float(units_value)
        if per_step_seconds <= 0:
            continue
        if most_recent_step_seconds is None:
            most_recent_step_seconds = per_step_seconds
        remaining_slots = max_steps - len(recent_step_seconds)
        if remaining_slots <= 0:
            break
        recent_step_seconds.extend([per_step_seconds] * min(remaining_slots, units_value))

    if not recent_step_seconds:
        return None

    weighted_total = 0.0
    weight_sum = 0.0
    for index, per_step_seconds in enumerate(recent_step_seconds):
        weight = float(_STATUS_ETA_RECENT_STEP_WEIGHTS[index])
        if weight <= 0:
            continue
        weighted_total += per_step_seconds * weight
        weight_sum += weight
    weighted_average = (
        weighted_total / weight_sum
        if weight_sum > 0
        else sum(recent_step_seconds) / float(len(recent_step_seconds))
    )
    if most_recent_step_seconds is None:
        return weighted_average
    if len(recent_step_seconds) <= 1:
        return most_recent_step_seconds
    blend = max(0.0, min(1.0, float(_STATUS_ETA_RECENT_INSTANT_BLEND)))
    if blend <= 0.0:
        return weighted_average
    if blend >= 1.0:
        return most_recent_step_seconds
    return (
        most_recent_step_seconds * blend
        + weighted_average * (1.0 - blend)
    )


def _parallel_bootstrap_eta_seconds(
    *,
    avg_seconds_per_task: float,
    remaining: int,
    parallelism: int | None,
) -> int:
    safe_remaining = max(0, int(remaining))
    if safe_remaining <= 0:
        return 0
    effective_parallelism = max(1, int(parallelism or 1))
    if effective_parallelism <= 1:
        return max(0, int(round(avg_seconds_per_task * safe_remaining)))
    remaining_waves = math.ceil(safe_remaining / float(effective_parallelism))
    return max(0, int(round(avg_seconds_per_task * remaining_waves)))


def _format_status_progress_message(
    message: str,
    *,
    elapsed_seconds: int,
    elapsed_threshold_seconds: int = _STATUS_ELAPSED_THRESHOLD_SECONDS,
    eta_seconds: int | None = None,
    avg_seconds_per_task: float | None = None,
) -> str:
    """Append ETA/throughput and elapsed time for long-running phases."""
    trimmed = message.strip()
    if not trimmed:
        return ""
    suffix_parts: list[str] = []
    if eta_seconds is not None:
        suffix_parts.append(f"eta {_format_processing_time(float(eta_seconds))}")
        if avg_seconds_per_task is not None and avg_seconds_per_task > 0:
            suffix_parts.append(f"avg {_format_seconds_per_task(avg_seconds_per_task)}")
    if elapsed_seconds >= max(0, elapsed_threshold_seconds):
        suffix_parts.append(f"{elapsed_seconds}s")
    if not suffix_parts:
        return trimmed
    suffix = f"({', '.join(suffix_parts)})"
    if "\n" not in trimmed:
        return f"{trimmed} {suffix}"
    lines = trimmed.splitlines()
    if not lines:
        return f"{trimmed} {suffix}"
    lines[0] = f"{lines[0]} {suffix}"
    return "\n".join(lines)


def _read_status_env_flag(name: str) -> str:
    return str(os.getenv(name, "") or "").strip().lower()


def _plain_progress_override_requested() -> bool | None:
    value = _read_status_env_flag(_STATUS_PLAIN_PROGRESS_ENV)
    if value in _STATUS_ENV_TRUE_VALUES:
        return True
    if value in _STATUS_ENV_FALSE_VALUES:
        return False
    return None


def _is_agent_execution_environment() -> bool:
    if _read_status_env_flag("CODEX_CI") in _STATUS_ENV_TRUE_VALUES:
        return True
    for key in _STATUS_AGENT_HINT_ENV_KEYS:
        if key == "CODEX_CI":
            continue
        if str(os.getenv(key, "") or "").strip():
            return True
    return False


def _should_default_plain_progress_for_agent() -> bool:
    # Agent PTY polling tends to duplicate spinner frames into noisy logs.
    return _is_agent_execution_environment()


def _enforce_live_labelstudio_benchmark_codex_guardrails(
    *,
    any_codex_enabled: bool,
    benchmark_codex_confirmation: str | None,
) -> None:
    if not any_codex_enabled:
        return
    if _INTERACTIVE_CLI_ACTIVE.get():
        return
    if _is_agent_execution_environment():
        _fail(
            "labelstudio-benchmark with live Codex-backed surfaces is blocked in "
            "agent-run environments. Use prompt preview or a fake-codex-farm rehearsal "
            "for zero-token validation, or have a human run the live benchmark manually "
            "outside the agent environment."
        )
    if (
        str(benchmark_codex_confirmation or "").strip()
        != BENCH_CODEX_FARM_CONFIRMATION_TOKEN
    ):
        _fail(
            "labelstudio-benchmark with live Codex-backed surfaces requires explicit "
            "positive user confirmation. Re-run with --benchmark-codex-confirmation "
            f"{BENCH_CODEX_FARM_CONFIRMATION_TOKEN} only after the user has explicitly "
            "approved this benchmark."
        )


def _enforce_live_bench_speed_codex_guardrails(*, include_codex_farm: bool) -> None:
    if not include_codex_farm:
        return
    if _is_agent_execution_environment():
        _fail(
            "bench speed-run with --include-codex-farm is blocked in agent-run "
            "environments. Have a human run the live Codex benchmark manually outside "
            "the agent environment after explicit user approval."
        )


def _normalize_live_status_slots(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = _LIVE_STATUS_SLOT_MAX_DEFAULT
    if normalized < 1:
        return _LIVE_STATUS_SLOT_MAX_DEFAULT
    return min(_LIVE_STATUS_SLOT_MAX_HARD_CAP, normalized)


def _read_live_status_slots_from_env() -> int:
    raw_value = _read_status_env_flag(_STATUS_LIVE_SLOTS_ENV)
    if raw_value == "":
        return _LIVE_STATUS_SLOT_MAX_DEFAULT
    return _normalize_live_status_slots(raw_value)


def _effective_live_status_slots() -> int:
    override = _BENCHMARK_LIVE_STATUS_SLOTS.get()
    if override is not None:
        return _normalize_live_status_slots(override)
    return _read_live_status_slots_from_env()


@contextmanager
def _acquire_live_status_slot(slot_limit: int) -> Iterable[bool]:
    global _LIVE_STATUS_SLOT_ACTIVE
    normalized_limit = _normalize_live_status_slots(slot_limit)
    acquired = False
    with _LIVE_STATUS_SLOT_LOCK:
        if _LIVE_STATUS_SLOT_ACTIVE < normalized_limit:
            _LIVE_STATUS_SLOT_ACTIVE += 1
            acquired = True
    try:
        yield acquired
    finally:
        if not acquired:
            return
        with _LIVE_STATUS_SLOT_LOCK:
            _LIVE_STATUS_SLOT_ACTIVE = max(0, _LIVE_STATUS_SLOT_ACTIVE - 1)


def _resolve_live_status_console(*, live_status_slots: int) -> Any:
    if live_status_slots <= 1:
        return console
    if not isinstance(console, Console):
        return console
    width_value = getattr(console, "width", None)
    width = width_value if isinstance(width_value, int) and width_value > 0 else None
    return Console(
        file=getattr(console, "file", None),
        force_terminal=bool(console.is_terminal),
        color_system=console.color_system,
        width=width,
        soft_wrap=bool(getattr(console, "soft_wrap", False)),
        markup=bool(getattr(console, "_markup", True)),
    )


def _format_processing_time(elapsed_seconds: float) -> str:
    total_seconds = max(0, int(round(elapsed_seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _read_linux_cpu_totals() -> tuple[int, int] | None:
    try:
        with Path("/proc/stat").open("r", encoding="utf-8") as handle:
            first_line = handle.readline()
    except OSError:
        return None
    line = str(first_line or "").strip()
    if not line:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    values: list[int] = []
    for token in parts[1:]:
        try:
            values.append(int(token))
        except ValueError:
            return None
    if len(values) < 4:
        return None
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


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
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
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


def _processing_timeseries_history_path(
    *,
    root: Path,
    scope: str,
    source_name: str | None = None,
) -> Path:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    scope_slug = slugify_name(scope) or "processing"
    source_slug = (
        slugify_name(Path(source_name).stem)
        if source_name is not None and str(source_name).strip()
        else ""
    )
    base_name = f"{timestamp}__{scope_slug}"
    if source_slug:
        base_name = f"{base_name}__{source_slug}"
    telemetry_dir = root / ".history" / "processing_timeseries"
    candidate = telemetry_dir / f"{base_name}.jsonl"
    if not candidate.exists():
        return candidate
    suffix = 1
    while True:
        candidate = telemetry_dir / f"{base_name}__{suffix}.jsonl"
        if not candidate.exists():
            return candidate
        suffix += 1


def _append_processing_timeseries_marker(
    *,
    telemetry_path: Path,
    event: str,
    payload: dict[str, Any],
) -> None:
    event_name = str(event or "").strip()
    if not event_name:
        return
    row = {
        "event": event_name,
        "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(
            timespec="milliseconds"
        ),
    }
    row.update(payload)
    try:
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        with telemetry_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_safe(row), sort_keys=True) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Ignoring processing time-series marker write failure for %s: %s",
            telemetry_path,
            exc,
        )


def _run_with_progress_status(
    *,
    initial_status: str,
    progress_prefix: str,
    run: Callable[[Callable[[str], None]], _StatusReturn],
    elapsed_threshold_seconds: int = _STATUS_ELAPSED_THRESHOLD_SECONDS,
    tick_seconds: float = _STATUS_TICK_SECONDS,
    telemetry_path: Path | None = None,
    telemetry_heartbeat_seconds: float = PROCESSING_TIMESERIES_HEARTBEAT_SECONDS,
    force_live_status: bool | None = None,
) -> _StatusReturn:
    status_started_at = time.monotonic()
    live_status_slots = _effective_live_status_slots()
    supports_live_status = (
        bool(force_live_status)
        if force_live_status is not None
        else bool(console.is_terminal and not console.is_dumb_terminal)
    )
    if force_live_status is None:
        plain_override = _plain_progress_override_requested()
        if plain_override is True:
            supports_live_status = False
        elif plain_override is None and _should_default_plain_progress_for_agent():
            supports_live_status = False
    latest_message = ""
    latest_message_started = time.monotonic()
    latest_counter: tuple[int, int] | None = None
    latest_running_workers: int | None = None
    latest_worker_total: int | None = None
    latest_active_tasks: list[str] | None = None
    latest_codex_stage_label: str | None = None
    latest_stage_label: str | None = None
    latest_work_unit_label: str | None = None
    latest_stage_detail_lines: list[str] = []
    latest_worker_running: int | None = None
    latest_worker_completed: int | None = None
    latest_worker_failed: int | None = None
    latest_followup_running: int | None = None
    latest_followup_completed: int | None = None
    latest_followup_total: int | None = None
    latest_followup_label: str | None = None
    latest_artifact_counts: dict[str, int] = {}
    latest_last_activity_at: str | None = None
    status_dashboard = ProgressDashboardCore()
    worker_dashboard_adapter = ProgressCallbackAdapter(status_dashboard)
    status_dashboard.set_status_line(str(initial_status).strip() or str(progress_prefix).strip())
    rate_total: int | None = None
    rate_last_current: int | None = None
    rate_last_progress_at: float | None = None
    rate_sampled_seconds = 0.0
    rate_sampled_units = 0
    rate_recent_samples: deque[tuple[float, int]] = deque(
        maxlen=_STATUS_RATE_RECENT_WINDOW
    )
    all_method_metrics: dict[str, int] = {}
    state_lock = threading.Lock()
    stop_event = threading.Event()
    _PROGRESS_BLUE_STYLE = "blue"
    _PROGRESS_BLUE_ANSI = "\x1b[34m"
    _PROGRESS_ANSI_RESET = "\x1b[0m"
    timeseries_writer: _ProcessingTimeseriesWriter | None = None
    if telemetry_path is not None:
        telemetry_file = Path(telemetry_path).expanduser()
        if telemetry_file.exists():
            telemetry_file.unlink()
        timeseries_writer = _ProcessingTimeseriesWriter(
            path=telemetry_file,
            heartbeat_seconds=max(0.05, float(telemetry_heartbeat_seconds)),
        )

    _WORKER_PANEL_LABEL_RE = re.compile(
        r"^\s*(?:active\s+tasks|active\s+workers)\b",
        re.IGNORECASE,
    )
    _WORKER_PREFIX_RE = re.compile(
        r"^worker\s+\d+\s*:",
        re.IGNORECASE,
    )
    _ACTIVE_TASKS_RE = re.compile(
        r"\bactive\s*\[([^]]*)\]",
        re.IGNORECASE,
    )
    _CODEX_FARM_PIPELINE_PREFIX_RE = re.compile(
        r"^codex-farm\s+(?P<pipeline>\S+)",
        re.IGNORECASE,
    )
    _RUNNING_WORKERS_RE = re.compile(
        r"\brunning\s+(\d+)\b",
        re.IGNORECASE,
    )
    _CODEX_ERROR_COUNT_RE = re.compile(
        r"\berrors?\s+(\d+)\b",
        re.IGNORECASE,
    )
    _CODEX_FARM_PROGRESS_LINE_RE = re.compile(
        r"^codex-farm\s+",
        re.IGNORECASE,
    )

    def _extract_active_tasks(message: str) -> list[str] | None:
        match = _ACTIVE_TASKS_RE.search(str(message or ""))
        if match is None:
            return None
        raw = str(match.group(1)).strip()
        if not raw:
            return []
        values = [item.strip() for item in raw.split(",")]
        cleaned = [value for value in values if value]
        return cleaned[:max(1, 8)]

    def _extract_running_workers(message: str) -> int | None:
        match = _RUNNING_WORKERS_RE.search(str(message or ""))
        if match is None:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _humanize_codex_pipeline_stage_label(pipeline_id: str) -> str:
        normalized = str(pipeline_id or "").strip()
        lowered = normalized.lower()
        if not normalized:
            return "codex stage"
        if "recipe.correction" in lowered or "recipe_correction" in lowered or "correction" in lowered:
            return "recipe correction"
        if "knowledge" in lowered:
            return "non-recipe knowledge review"
        if "tags" in lowered:
            return "tag suggestions"
        return normalized

    def _summarize_codex_progress_message(message: str) -> tuple[str, str | None]:
        trimmed = str(message or "").strip()
        match = _CODEX_FARM_PIPELINE_PREFIX_RE.match(trimmed)
        if match is None:
            return trimmed, None

        raw_pipeline = str(match.group("pipeline") or "").strip()
        pipeline_id = raw_pipeline[:-1] if raw_pipeline.endswith(":") else raw_pipeline
        stage_label = _humanize_codex_pipeline_stage_label(pipeline_id)
        counter = _extract_progress_counter(trimmed)
        running = _extract_running_workers(trimmed)
        error_match = _CODEX_ERROR_COUNT_RE.search(trimmed)
        errors = int(error_match.group(1)) if error_match is not None else 0

        if counter is not None:
            current, total = counter
            parts = [
                f"codex-farm {stage_label}",
                f"task {current}/{total}",
            ]
            if running is not None and running > 0:
                parts.append(f"running {running}")
            if errors > 0:
                parts.append(f"errors {errors}")
            return " | ".join(parts), stage_label

        suffix = trimmed[match.end() :].strip()
        if suffix.startswith(":"):
            suffix = suffix[1:].strip()
        if suffix:
            return f"codex-farm {stage_label}: {suffix}", stage_label
        return f"codex-farm {stage_label}", stage_label

    def _render_artifact_counts_line(artifact_counts: Mapping[str, Any] | None) -> str | None:
        if not isinstance(artifact_counts, Mapping):
            return None
        parts: list[str] = []
        for key, value in sorted(artifact_counts.items()):
            cleaned_key = str(key or "").strip()
            try:
                cleaned_value = max(0, int(value))
            except (TypeError, ValueError):
                continue
            if not cleaned_key:
                continue
            parts.append(f"{cleaned_key.replace('_', ' ')} {cleaned_value}")
        if not parts:
            return None
        return "artifacts: " + " | ".join(parts)

    def _render_worker_summary_line(
        *,
        worker_running: int | None,
        worker_completed: int | None,
        worker_failed: int | None,
        worker_total: int | None,
    ) -> str | None:
        summary_parts: list[str] = []
        for label, value in (
            ("running", worker_running),
            ("completed", worker_completed),
            ("failed", worker_failed),
        ):
            if value is None:
                continue
            summary_parts.append(f"{max(0, int(value))} {label}")
        if worker_total is not None:
            summary_parts.append(f"{max(0, int(worker_total))} total")
        if not summary_parts:
            return None
        return "workers: " + ", ".join(summary_parts)

    def _render_followup_summary_line(
        *,
        followup_label: str | None,
        followup_running: int | None,
        followup_completed: int | None,
        followup_total: int | None,
    ) -> str | None:
        cleaned_label = str(followup_label or "").strip() or "follow-up"
        summary_parts: list[str] = [cleaned_label]
        if followup_completed is not None and followup_total is not None:
            summary_parts.append(
                f"{max(0, int(followup_completed))}/{max(0, int(followup_total))}"
            )
        if followup_running is not None:
            summary_parts.append(f"running {max(0, int(followup_running))}")
        if len(summary_parts) == 1 and cleaned_label == "follow-up":
            return None
        return "repo follow-up: " + " | ".join(summary_parts)

    def _inject_worker_summary_lines(snapshot: str) -> str:
        with state_lock:
            running_workers = latest_running_workers
            worker_total = latest_worker_total
            active_tasks = (
                None if latest_active_tasks is None else list(latest_active_tasks)
            )
            work_unit_label = (
                str(latest_work_unit_label).strip()
                if latest_work_unit_label is not None
                else ""
            )
            codex_stage_label = (
                str(latest_codex_stage_label).strip()
                if latest_codex_stage_label is not None
                else ""
            )
            stage_label = (
                codex_stage_label
                or (
                    str(latest_stage_label).strip()
                    if latest_stage_label is not None
                    else ""
                )
            )
            detail_lines = list(latest_stage_detail_lines)
            worker_running = latest_worker_running
            worker_completed = latest_worker_completed
            worker_failed = latest_worker_failed
            followup_running = latest_followup_running
            followup_completed = latest_followup_completed
            followup_total = latest_followup_total
            followup_label = latest_followup_label
            artifact_counts = dict(latest_artifact_counts)
            task_counter = latest_counter
        if (
            running_workers is None
            and worker_total is None
            and active_tasks is None
            and not stage_label
            and not work_unit_label
            and not detail_lines
            and worker_running is None
            and worker_completed is None
            and worker_failed is None
            and followup_running is None
            and followup_completed is None
            and followup_total is None
            and not followup_label
            and not artifact_counts
            and task_counter is None
        ):
            return snapshot

        lines = [line.strip() for line in str(snapshot or "").splitlines() if line.strip()]
        if not lines:
            return ""

        if (
            running_workers is None
            and worker_total is None
            and active_tasks is None
            and not detail_lines
            and worker_running is None
            and worker_completed is None
            and worker_failed is None
            and followup_running is None
            and followup_completed is None
            and followup_total is None
            and not followup_label
            and not artifact_counts
            and task_counter is None
        ):
            return "\n".join(lines)

        if stage_label and not any(
            line.lower().startswith("stage:")
            for line in lines
        ):
            lines.insert(1, f"stage: {stage_label}")

        progress_lines: list[str] = []
        if task_counter is not None and not any(
            line.lower().startswith("progress:")
            for line in lines
        ):
            counter_current, counter_total = task_counter
            counter_label = work_unit_label or "task"
            progress_percent = 0
            if counter_total > 0:
                progress_percent = int(
                    round((float(counter_current) / float(counter_total)) * 100.0)
                )
            progress_lines.append(
                f"progress: {counter_label} {counter_current}/{counter_total} ({progress_percent}%)"
            )
            remaining_tasks = max(0, int(counter_total) - int(counter_current))
            if remaining_tasks > 0:
                remaining_label = (work_unit_label or "task").replace("_", " ")
                progress_lines.append(f"remaining {remaining_label}s: {remaining_tasks}")
        if progress_lines:
            insert_at = 2 if len(lines) > 1 and lines[1].lower().startswith("stage:") else 1
            for progress_line in reversed(progress_lines):
                lines.insert(insert_at, progress_line)

        summary_lines = [
            line
            for line in (
                _render_worker_summary_line(
                    worker_running=worker_running,
                    worker_completed=worker_completed,
                    worker_failed=worker_failed,
                    worker_total=worker_total,
                ),
                _render_followup_summary_line(
                    followup_label=followup_label,
                    followup_running=followup_running,
                    followup_completed=followup_completed,
                    followup_total=followup_total,
                ),
                _render_artifact_counts_line(artifact_counts),
            )
            if line
        ]
        if summary_lines or detail_lines:
            insert_at = 1 if lines else 0
            if len(lines) > 1 and lines[1].lower().startswith("stage:"):
                insert_at = 2
                if len(lines) > 2 and lines[2].lower().startswith("progress:"):
                    insert_at = 3
                    if len(lines) > 3 and lines[3].lower().startswith("remaining "):
                        insert_at = 4
            inserted_lines = [*summary_lines, *detail_lines]
            for detail_line in reversed(inserted_lines):
                if detail_line and detail_line not in lines:
                    lines.insert(insert_at, detail_line)

        if (
            running_workers is None
            and worker_total is None
            and active_tasks is None
            and worker_running is None
            and worker_completed is None
            and worker_failed is None
        ):
            return "\n".join(lines)

        if any(
            _WORKER_PANEL_LABEL_RE.search(line)
            or _WORKER_PREFIX_RE.match(line)
            for line in lines
        ):
            return "\n".join(lines)

        typed_running_slots = (
            max(0, int(worker_running)) if worker_running is not None else None
        )
        running_slots = (
            typed_running_slots
            if typed_running_slots is not None
            else max(0, int(running_workers))
            if running_workers is not None
            else 0
        )
        configured_slots = max(0, int(worker_total)) if worker_total is not None else 0
        completed_slots = max(0, int(worker_completed or 0))
        failed_slots = max(0, int(worker_failed or 0))
        display_slots = max(
            8,
            configured_slots,
            len(active_tasks or []),
            max(0, int(running_workers or 0)),
            running_slots + completed_slots + failed_slots,
        )
        if running_slots <= 0:
            if running_workers is None and worker_total is None:
                running_slots = display_slots
            else:
                running_slots = 0
        else:
            running_slots = max(running_slots, 1)
        if (
            running_slots <= 0
            and completed_slots <= 0
            and failed_slots <= 0
            and configured_slots <= 0
            and not (active_tasks or [])
        ):
            return "\n".join(lines)

        worker_lines: list[str] = []
        slot_statuses: list[str] = []
        if active_tasks is not None:
            task_count = len(active_tasks)
            tasks_left: int | None = None
            if task_counter is not None:
                counter_current, counter_total = task_counter
                tasks_left = max(0, int(counter_total) - int(counter_current))
            if task_count > 0:
                active_tasks_label = (
                    f"active tasks ({task_count}"
                    + (f"/{running_slots}" if running_slots else "")
                )
                if tasks_left is not None:
                    active_tasks_label += f", {tasks_left} left"
                active_tasks_label += ")"
                worker_lines.append(
                    active_tasks_label
                )
            slot_statuses.extend(
                str(task).strip() or "[unknown task]"
                for task in active_tasks[:running_slots]
            )
            if len(slot_statuses) < running_slots:
                slot_statuses.extend(
                    ["processing (unresolved)"] * (running_slots - len(slot_statuses))
                )
        else:
            worker_lines.append(f"active workers: {running_slots}")
        slot_statuses.extend(["running"] * max(0, running_slots - len(slot_statuses)))
        slot_statuses.extend(["done"] * completed_slots)
        slot_statuses.extend(["failed"] * failed_slots)
        target_slots = max(display_slots, len(slot_statuses))
        if len(slot_statuses) < target_slots:
            slot_statuses.extend(["idle"] * (target_slots - len(slot_statuses)))
        active_slots = running_slots
        if not worker_lines:
            worker_lines.append(f"active workers: {active_slots}")
        if configured_slots > 0 and configured_slots != active_slots:
            worker_lines.append(f"configured workers: {configured_slots}")
        for index, status in enumerate(slot_statuses[:target_slots], start=1):
            worker_lines.append(f"worker {index:02d}: {status}")

        if running_slots <= 0 and not worker_lines:
            return "\n".join(lines)
        if running_slots <= 0 and worker_lines == ["active workers: 0"]:
            return "\n".join(lines)

        if not worker_lines:
            return "\n".join(lines)

        insert_at = len(lines)
        for index, line in enumerate(lines):
            if line.lower().startswith("task:"):
                insert_at = index + 1
                break
        merged = lines[:insert_at] + worker_lines + lines[insert_at:]
        return "\n".join(merged)

    def _format_boxed_progress(snapshot: str) -> str:
        def _wrap_panel_text(value: str, max_chars: int) -> list[str]:
            text = str(value or "")
            if max_chars <= 0:
                return [""]
            if not text:
                return [""]
            wrapped = textwrap.wrap(
                text,
                width=max_chars,
                break_long_words=True,
                break_on_hyphens=False,
                drop_whitespace=False,
                replace_whitespace=False,
            )
            if wrapped:
                return wrapped
            if len(text) <= max_chars:
                return [text]
            return [text[:max_chars]]

        def _truncate_panel_text(value: str, max_chars: int) -> str:
            text = str(value or "")
            if max_chars <= 0:
                return ""
            if len(text) <= max_chars:
                return text
            if max_chars <= 3:
                return text[:max_chars]
            # Preserve trailing timing details (eta/avg/elapsed suffix) when long
            # status lines are clamped to terminal width.
            if text.endswith(")"):
                eta_start = text.rfind(" (eta ")
                suffix_start = eta_start + 1 if eta_start >= 0 else -1
                if suffix_start <= 0:
                    generic_suffix = text.rfind(" (")
                    if generic_suffix >= 0 and (len(text) - generic_suffix) <= 32:
                        suffix_start = generic_suffix + 1
                if suffix_start > 0:
                    suffix = text[suffix_start:]
                    suffix_budget = max_chars - 3
                    if suffix_budget > 0 and suffix:
                        if len(suffix) >= suffix_budget:
                            return "..." + suffix[-suffix_budget:]
                        prefix_budget = max_chars - len(suffix) - 3
                        if prefix_budget > 0:
                            return text[:prefix_budget] + "..." + suffix
            return text[: max_chars - 3] + "..."

        lines = [
            line.rstrip()
            for line in str(snapshot or "").splitlines()
            if line.strip()
        ]
        if not lines:
            return ""

        max_panel_width = 132
        terminal_width = getattr(console, "width", None)
        if isinstance(terminal_width, int) and terminal_width > 0:
            # Keep room for the spinner glyph + padding prefix Rich adds.
            max_panel_width = min(max_panel_width, max(28, terminal_width - 6))

        width = max(len(line) for line in lines)
        title = (progress_prefix or initial_status).strip() or "Progress"
        width = max(width, len(title))
        width = max(1, min(width, max_panel_width))
        wrapped_lines: list[str] = []
        for line in lines:
            wrapped_lines.extend(_wrap_panel_text(line, width))
        if not wrapped_lines:
            wrapped_lines = [""]
        header = f"| {_truncate_panel_text(title, width).center(width)} |"
        top_bottom = "+" + "-" * (width + 2) + "+"
        divider = "+" + "-" * (width + 2) + "+"
        body_lines = [
            f"| {_truncate_panel_text(line, width).ljust(width)} |"
            for line in wrapped_lines
        ]
        return "\n".join([top_bottom, header, divider, *body_lines, top_bottom])

    def _build_status_line(now: float | None = None) -> str:
        current = now if now is not None else time.monotonic()
        with state_lock:
            message = latest_message
            started_at = latest_message_started
            counter = latest_counter
            tracked_total = rate_total
            last_progress_at = rate_last_progress_at
            sampled_seconds = rate_sampled_seconds
            sampled_units = rate_sampled_units
            recent_avg = _recent_rate_average_seconds_per_task(rate_recent_samples)
            dashboard_metrics = dict(all_method_metrics)
            running_workers_hint = latest_running_workers
            worker_total_hint = latest_worker_total
            active_tasks_hint = (
                None if latest_active_tasks is None else list(latest_active_tasks)
            )
        if not message:
            base = str(initial_status).strip() or str(progress_prefix).strip()
        else:
            elapsed = max(0, int(current - started_at))
            eta_seconds: int | None = None
            avg_seconds_per_task: float | None = None
            if (
                counter is not None
                and tracked_total is not None
                and counter[1] == tracked_total
            ):
                counter_current, counter_total = counter
                remaining = max(0, counter_total - counter_current)
                if recent_avg is not None:
                    avg_seconds_per_task = recent_avg
                elif sampled_units > 0 and sampled_seconds > 0:
                    avg_seconds_per_task = sampled_seconds / sampled_units
                elif counter_current > 0:
                    bootstrap_elapsed = max(0.0, current - status_started_at)
                    if bootstrap_elapsed >= _STATUS_ETA_BOOTSTRAP_MIN_SECONDS:
                        avg_seconds_per_task = bootstrap_elapsed / float(counter_current)
                if (
                    remaining > 0
                    and avg_seconds_per_task is not None
                    and avg_seconds_per_task > 0
                ):
                    active_parallelism = max(
                        0,
                        int(running_workers_hint or 0),
                        len(active_tasks_hint or []),
                    )
                    configured_parallelism = max(0, int(worker_total_hint or 0))
                    bootstrap_parallelism = active_parallelism or configured_parallelism or 1
                    if recent_avg is None and not (sampled_units > 0 and sampled_seconds > 0):
                        eta_seconds = _parallel_bootstrap_eta_seconds(
                            avg_seconds_per_task=avg_seconds_per_task,
                            remaining=remaining,
                            parallelism=bootstrap_parallelism,
                        )
                    else:
                        eta_seconds = int(round(avg_seconds_per_task * remaining))
                    active_hint = max(0, int(dashboard_metrics.get("active") or 0))
                    eval_hint = max(0, int(dashboard_metrics.get("eval") or 0))
                    if (
                        active_hint > 0
                        and eval_hint > 0
                        and last_progress_at is not None
                    ):
                        stalled_seconds = max(0.0, current - last_progress_at)
                        if stalled_seconds >= max(
                            _STATUS_ALL_METHOD_STALL_MIN_SECONDS,
                            avg_seconds_per_task * _STATUS_ALL_METHOD_STALL_MULTIPLIER,
                        ):
                            stalled_floor = stalled_seconds / float(active_hint)
                            if stalled_floor > avg_seconds_per_task:
                                eta_seconds = max(
                                    eta_seconds,
                                    int(round(stalled_floor * remaining)),
                                )
            decorated = _format_status_progress_message(
                message,
                elapsed_seconds=elapsed,
                elapsed_threshold_seconds=elapsed_threshold_seconds,
                eta_seconds=eta_seconds,
                avg_seconds_per_task=avg_seconds_per_task,
            )
            return f"{progress_prefix}: {decorated}".strip()
        return str(initial_status).strip() or str(progress_prefix).strip()

    def render_plain(now: float | None = None) -> str:
        status_dashboard.set_status_line(_build_status_line(now))
        return _inject_worker_summary_lines(status_dashboard.render())

    def render(now: float | None = None) -> str:
        snapshot = render_plain(now)
        if not snapshot:
            return ""
        escaped = rich_escape(snapshot)
        return (
            f"[{_PROGRESS_BLUE_STYLE}]"
            f"{_format_boxed_progress(escaped)}"
            f"[/{_PROGRESS_BLUE_STYLE}]"
        )

    def _emit_timeseries(
        *,
        event: str,
        force: bool = False,
        now: float | None = None,
    ) -> None:
        if timeseries_writer is None:
            return
        current = now if now is not None else time.monotonic()
        with state_lock:
            message = latest_message
            started_at = latest_message_started
            counter = latest_counter
            running_workers_hint = latest_running_workers
            worker_total_hint = latest_worker_total
            stage_label = latest_stage_label
            work_unit_label = latest_work_unit_label
            detail_lines = list(latest_stage_detail_lines)
            worker_running_hint = latest_worker_running
            worker_completed_hint = latest_worker_completed
            worker_failed_hint = latest_worker_failed
            followup_running_hint = latest_followup_running
            followup_completed_hint = latest_followup_completed
            followup_total_hint = latest_followup_total
            followup_label_hint = latest_followup_label
            artifact_counts_hint = dict(latest_artifact_counts)
            last_activity_at_hint = latest_last_activity_at
            active_tasks_hint = (
                None if latest_active_tasks is None else list(latest_active_tasks)
            )
        worker_total, worker_statuses = worker_dashboard_adapter.snapshot_workers()
        elapsed_seconds = max(0.0, current - started_at)
        message_value = str(message or initial_status).strip() or str(initial_status).strip()
        counter_current: int | None = None
        counter_total: int | None = None
        if counter is not None:
            counter_current = max(0, int(counter[0]))
            counter_total = max(0, int(counter[1]))
        worker_active = sum(
            1
            for status in worker_statuses.values()
            if str(status).strip().lower() not in {"", "idle", "done", "skipped"}
        )
        if worker_total <= 0 and worker_total_hint is not None:
            worker_total = max(0, int(worker_total_hint))
        if worker_total <= 0 and running_workers_hint is not None:
            worker_total = max(0, int(running_workers_hint))
        if worker_active <= 0 and running_workers_hint is not None:
            worker_active = max(0, int(running_workers_hint))
        snapshot = message_value
        if counter_current is not None and counter_total is not None:
            snapshot = f"{snapshot} | task {counter_current}/{counter_total}"
        if worker_total > 0:
            snapshot = f"{snapshot} | workers {worker_total}"
        timeseries_writer.write_row(
            snapshot=snapshot,
            force=force,
            payload={
                "event": str(event or "").strip() or "update",
                "progress_prefix": progress_prefix,
                "message": message_value,
                "elapsed_seconds": elapsed_seconds,
                "stage_label": str(stage_label or "").strip() or None,
                "work_unit_label": str(work_unit_label or "").strip() or None,
                "task_current": counter_current,
                "task_total": counter_total,
                "worker_total": max(0, int(worker_total)),
                "worker_active": max(0, int(worker_active)),
                "worker_running": (
                    max(0, int(worker_running_hint))
                    if worker_running_hint is not None
                    else None
                ),
                "worker_completed": (
                    max(0, int(worker_completed_hint))
                    if worker_completed_hint is not None
                    else None
                ),
                "worker_failed": (
                    max(0, int(worker_failed_hint))
                    if worker_failed_hint is not None
                    else None
                ),
                "followup_running": (
                    max(0, int(followup_running_hint))
                    if followup_running_hint is not None
                    else None
                ),
                "followup_completed": (
                    max(0, int(followup_completed_hint))
                    if followup_completed_hint is not None
                    else None
                ),
                "followup_total": (
                    max(0, int(followup_total_hint))
                    if followup_total_hint is not None
                    else None
                ),
                "followup_label": str(followup_label_hint or "").strip() or None,
                "artifact_counts": artifact_counts_hint or None,
                "last_activity_at": str(last_activity_at_hint or "").strip() or None,
                "active_tasks": list(active_tasks_hint or []),
                "detail_lines": detail_lines,
                "worker_activity": {
                    str(key): str(value)
                    for key, value in sorted(worker_statuses.items())
                },
            },
        )

    last_plain_snapshot = ""

    def _update_progress_common(msg: str) -> tuple[bool, float]:
        nonlocal latest_message, latest_message_started
        nonlocal latest_counter, rate_total, rate_last_current, rate_last_progress_at
        nonlocal rate_sampled_seconds, rate_sampled_units
        nonlocal rate_recent_samples, all_method_metrics
        nonlocal latest_running_workers, latest_worker_total, latest_active_tasks
        nonlocal latest_codex_stage_label, latest_stage_label, latest_stage_detail_lines
        nonlocal latest_work_unit_label
        nonlocal latest_worker_running, latest_worker_completed, latest_worker_failed
        nonlocal latest_followup_running, latest_followup_completed, latest_followup_total
        nonlocal latest_followup_label, latest_artifact_counts, latest_last_activity_at
        now = time.monotonic()
        cleaned = msg.strip()
        is_worker_activity = parse_worker_activity(cleaned) is not None
        stage_progress = (
            None if is_worker_activity else parse_stage_progress(cleaned)
        )
        stage_detail_lines: list[str] | None = None
        structured_counter: tuple[int, int] | None = None
        structured_running_workers: int | None = None
        structured_worker_total: int | None = None
        structured_active_tasks: list[str] | None = None
        structured_work_unit_label: str | None = None
        structured_worker_running: int | None = None
        structured_worker_completed: int | None = None
        structured_worker_failed: int | None = None
        structured_followup_running: int | None = None
        structured_followup_completed: int | None = None
        structured_followup_total: int | None = None
        structured_followup_label: str | None = None
        structured_artifact_counts: dict[str, int] | None = None
        structured_last_activity_at: str | None = None
        current_stage_label: str | None = None
        stage_changed = False
        if stage_progress is not None:
            cleaned = str(stage_progress.get("message") or "").strip() or cleaned
            structured_work_unit_label = (
                str(stage_progress.get("work_unit_label") or "").strip() or None
            )
            task_current = stage_progress.get("task_current")
            task_total = stage_progress.get("task_total")
            if task_current is not None and task_total is not None:
                structured_counter = (int(task_current), int(task_total))
            running_hint = stage_progress.get("running_workers")
            if running_hint is not None:
                structured_running_workers = max(0, int(running_hint))
            worker_total_hint = stage_progress.get("worker_total")
            if worker_total_hint is not None:
                structured_worker_total = max(0, int(worker_total_hint))
            worker_running_hint = stage_progress.get("worker_running")
            if worker_running_hint is not None:
                structured_worker_running = max(0, int(worker_running_hint))
            worker_completed_hint = stage_progress.get("worker_completed")
            if worker_completed_hint is not None:
                structured_worker_completed = max(0, int(worker_completed_hint))
            worker_failed_hint = stage_progress.get("worker_failed")
            if worker_failed_hint is not None:
                structured_worker_failed = max(0, int(worker_failed_hint))
            followup_running_hint = stage_progress.get("followup_running")
            if followup_running_hint is not None:
                structured_followup_running = max(0, int(followup_running_hint))
            followup_completed_hint = stage_progress.get("followup_completed")
            if followup_completed_hint is not None:
                structured_followup_completed = max(0, int(followup_completed_hint))
            followup_total_hint = stage_progress.get("followup_total")
            if followup_total_hint is not None:
                structured_followup_total = max(0, int(followup_total_hint))
            structured_followup_label = (
                str(stage_progress.get("followup_label") or "").strip() or None
            )
            artifact_counts_hint = stage_progress.get("artifact_counts")
            if isinstance(artifact_counts_hint, dict):
                structured_artifact_counts = {
                    str(key).strip(): max(0, int(value))
                    for key, value in artifact_counts_hint.items()
                    if str(key).strip()
                }
            structured_last_activity_at = (
                str(stage_progress.get("last_activity_at") or "").strip() or None
            )
            active_tasks_hint = stage_progress.get("active_tasks")
            if isinstance(active_tasks_hint, list):
                structured_active_tasks = [
                    str(value).strip()
                    for value in active_tasks_hint
                    if str(value).strip()
                ]
            detail_hint = stage_progress.get("detail_lines")
            if isinstance(detail_hint, list):
                stage_detail_lines = [
                    str(value).strip()
                    for value in detail_hint
                    if str(value).strip()
                ]
            current_stage_label = (
                str(stage_progress.get("stage_label") or "").strip()
                or _extract_progress_stage_label(cleaned)
            )
        counter = None
        generic_counter = (
            structured_counter
            if structured_counter is not None
            else _extract_progress_counter(cleaned)
            if not is_worker_activity
            else None
        )
        generic_running_workers = (
            structured_running_workers
            if structured_running_workers is not None
            else _extract_running_workers(cleaned)
            if generic_counter is not None
            else None
        )
        is_codex_progress = (
            stage_progress is None
            and _CODEX_FARM_PROGRESS_LINE_RE.search(cleaned) is not None
        )
        if is_codex_progress:
            running_workers = _extract_running_workers(cleaned)
            active_tasks = _extract_active_tasks(cleaned)
            codex_stage_label: str | None
            if running_workers is not None:
                latest_running_workers = running_workers
            if active_tasks is not None:
                latest_active_tasks = active_tasks
            else:
                latest_active_tasks = None
            summarized, codex_stage_label = _summarize_codex_progress_message(cleaned)
            cleaned = summarized
            current_stage_label = codex_stage_label or _extract_progress_stage_label(cleaned)
            if current_stage_label != latest_stage_label:
                latest_worker_total = None
                latest_work_unit_label = None
                latest_stage_detail_lines = []
                latest_worker_running = None
                latest_worker_completed = None
                latest_worker_failed = None
                latest_followup_running = None
                latest_followup_completed = None
                latest_followup_total = None
                latest_followup_label = None
                latest_artifact_counts = {}
                latest_last_activity_at = None
            latest_stage_label = current_stage_label
            latest_codex_stage_label = codex_stage_label
            if current_stage_label == latest_stage_label:
                latest_running_workers = running_workers
        elif not is_worker_activity:
            current_stage_label = current_stage_label or _extract_progress_stage_label(cleaned)
            stage_changed = current_stage_label != latest_stage_label
            if stage_changed:
                latest_running_workers = None
                latest_worker_total = None
                latest_active_tasks = None
                latest_work_unit_label = None
                latest_stage_detail_lines = []
                latest_worker_running = None
                latest_worker_completed = None
                latest_worker_failed = None
                latest_followup_running = None
                latest_followup_completed = None
                latest_followup_total = None
                latest_followup_label = None
                latest_artifact_counts = {}
                latest_last_activity_at = None
            if generic_running_workers is not None:
                latest_running_workers = generic_running_workers
            elif stage_progress is not None:
                latest_running_workers = None
            if structured_worker_total is not None:
                latest_worker_total = structured_worker_total
            elif stage_progress is not None:
                latest_worker_total = None
            if structured_active_tasks is not None:
                latest_active_tasks = structured_active_tasks
            elif stage_progress is not None:
                latest_active_tasks = None
            if stage_progress is not None:
                latest_work_unit_label = structured_work_unit_label
                latest_worker_running = (
                    structured_worker_running
                    if structured_worker_running is not None
                    else structured_running_workers
                )
                latest_worker_completed = structured_worker_completed
                latest_worker_failed = structured_worker_failed
                latest_followup_running = structured_followup_running
                latest_followup_completed = structured_followup_completed
                latest_followup_total = structured_followup_total
                latest_followup_label = structured_followup_label
                latest_artifact_counts = dict(structured_artifact_counts or {})
                latest_last_activity_at = structured_last_activity_at
            elif stage_changed:
                latest_active_tasks = None
            if stage_detail_lines is not None:
                latest_stage_detail_lines = stage_detail_lines
            elif stage_progress is not None:
                latest_stage_detail_lines = []
            elif stage_changed:
                latest_stage_detail_lines = []
            latest_codex_stage_label = None
            latest_stage_label = current_stage_label
        # Route every callback through the shared adapter so callback+worker
        # activity both update the same dashboard state machine.
        changed = worker_dashboard_adapter.ingest_callback_message(cleaned)
        with state_lock:
            if not is_worker_activity:
                counter = (
                    structured_counter
                    if structured_counter is not None
                    else _extract_progress_counter(cleaned)
                )
                message_changed = cleaned != latest_message
                counter_changed = counter != latest_counter
                if message_changed or counter_changed:
                    changed = True
                if message_changed:
                    latest_message_started = now
                latest_message = cleaned
                latest_counter = counter
                if message_changed:
                    all_method_metrics = _extract_all_method_dashboard_metrics(cleaned)
                if counter is not None:
                    counter_current, counter_total = counter
                    should_reset = (
                        stage_changed
                        or rate_total is None
                        or rate_last_current is None
                        or rate_last_progress_at is None
                        or counter_total != rate_total
                        or counter_current < rate_last_current
                    )
                    if should_reset:
                        changed = True
                        rate_total = counter_total
                        rate_last_current = counter_current
                        rate_last_progress_at = now
                        rate_sampled_seconds = 0.0
                        rate_sampled_units = 0
                        rate_recent_samples.clear()
                    else:
                        delta = counter_current - rate_last_current
                        if delta > 0:
                            elapsed_since_progress = max(0.0, now - rate_last_progress_at)
                            if elapsed_since_progress > 0:
                                rate_sampled_seconds += elapsed_since_progress
                                rate_sampled_units += delta
                                rate_recent_samples.append((elapsed_since_progress, delta))
                            rate_last_current = counter_current
                            rate_last_progress_at = now
        status_dashboard.set_status_line(_build_status_line(now))
        return changed, now

    def _run_plain() -> _StatusReturn:
        nonlocal last_plain_snapshot
        console_file = getattr(console, "file", None)
        plain_tty = bool(
            console.is_terminal
            and not console.is_dumb_terminal
            and hasattr(console_file, "isatty")
            and console_file.isatty()
        )
        initial_snapshot = render_plain()

        def _snapshot_to_single_line(snapshot: str) -> str:
            parts = [line.strip() for line in snapshot.splitlines() if line.strip()]
            if not parts:
                return ""
            return " | ".join(parts)

        def _render_plain_snapshot(snapshot: str) -> None:
            nonlocal last_plain_snapshot
            line = _snapshot_to_single_line(snapshot)
            if not line:
                return
            with state_lock:
                if line == last_plain_snapshot:
                    return
                last_plain_snapshot = line
            if plain_tty:
                assert console_file is not None
                console_file.write(
                    f"\r\u001b[2K{_PROGRESS_BLUE_ANSI}{line}{_PROGRESS_ANSI_RESET}"
                )
                console_file.flush()
            else:
                typer.secho(line, fg=typer.colors.BLUE)

        if initial_snapshot:
            _render_plain_snapshot(initial_snapshot)
        _emit_timeseries(event="started", force=True)

        def tick() -> None:
            while True:
                with state_lock:
                    message_snapshot = latest_message
                    worker_snapshot = worker_dashboard_adapter.snapshot_workers()[0]
                interval = float(tick_seconds)
                if (
                    (worker_snapshot > 0 or "\n" in (message_snapshot or ""))
                    and interval >= 0.5
                ):
                    interval = max(interval, 5.0)
                if stop_event.wait(max(0.05, interval)):
                    return
                now = time.monotonic()
                snapshot = render_plain(now)
                _render_plain_snapshot(snapshot)

        ticker = threading.Thread(
            target=tick,
            name="cli-status-progress-ticker",
            daemon=True,
        )
        ticker.start()

        def update_progress(msg: str) -> None:
            nonlocal last_plain_snapshot
            changed, now = _update_progress_common(msg)
            if not changed:
                return
            snapshot = render_plain(now)
            _render_plain_snapshot(snapshot)
            _emit_timeseries(event="update", now=now)

        try:
            return run(update_progress)
        finally:
            stop_event.set()
            ticker.join(timeout=max(0.2, float(tick_seconds) * 2))
            if plain_tty:
                assert console_file is not None
                console_file.write("\n")
                console_file.flush()
            _emit_timeseries(event="finished", force=True)

    if not supports_live_status:
        return _run_plain()

    with _acquire_live_status_slot(live_status_slots) as live_slot_acquired:
        if not live_slot_acquired:
            return _run_plain()
        status_console = _resolve_live_status_console(
            live_status_slots=live_status_slots
        )
        live_spinner = (
            "bouncingBar"
            if "benchmark" in str(progress_prefix).strip().lower()
            else "dots"
        )
        with status_console.status(
            render(),
            spinner=live_spinner,
            spinner_style=_PROGRESS_BLUE_STYLE,
            refresh_per_second=4.0,
        ) as status:
            _emit_timeseries(event="started", force=True)

            def tick() -> None:
                while True:
                    with state_lock:
                        message_snapshot = latest_message
                        worker_snapshot = worker_dashboard_adapter.snapshot_workers()[0]
                    interval = float(tick_seconds)
                    if (
                        (worker_snapshot > 0 or "\n" in (message_snapshot or ""))
                        and interval >= 0.5
                    ):
                        interval = max(interval, 5.0)
                    if stop_event.wait(max(0.05, interval)):
                        return
                    now = time.monotonic()
                    status.update(render(now))
                    _emit_timeseries(event="tick", now=now)

            ticker = threading.Thread(
                target=tick,
                name="cli-status-progress-ticker",
                daemon=True,
            )
            ticker.start()

            def update_progress(msg: str) -> None:
                changed, now = _update_progress_common(msg)
                if not changed:
                    return
                status.update(render(now))
                _emit_timeseries(event="update", now=now)

            try:
                return run(update_progress)
            finally:
                stop_event.set()
                ticker.join(timeout=max(0.2, float(tick_seconds) * 2))
                _emit_timeseries(event="finished", force=True)


@contextmanager
def _benchmark_progress_overrides(
    *,
    progress_callback: Callable[[str], None] | None = None,
    suppress_summary: bool = False,
    suppress_spinner: bool = False,
    suppress_dashboard_refresh: bool = False,
    suppress_output_prune: bool = False,
    live_status_slots: int | None = None,
) -> Iterable[None]:
    progress_token = _BENCHMARK_PROGRESS_CALLBACK.set(progress_callback)
    summary_token = _BENCHMARK_SUPPRESS_SUMMARY.set(bool(suppress_summary))
    spinner_token = _BENCHMARK_SUPPRESS_SPINNER.set(bool(suppress_spinner))
    dashboard_refresh_token = _BENCHMARK_SUPPRESS_DASHBOARD_REFRESH.set(
        bool(suppress_dashboard_refresh)
    )
    output_prune_token = _BENCHMARK_SUPPRESS_OUTPUT_PRUNE.set(
        bool(suppress_output_prune)
    )
    live_slots_token = _BENCHMARK_LIVE_STATUS_SLOTS.set(
        _normalize_live_status_slots(live_status_slots)
        if live_status_slots is not None
        else None
    )
    try:
        yield
    finally:
        _BENCHMARK_PROGRESS_CALLBACK.reset(progress_token)
        _BENCHMARK_SUPPRESS_SUMMARY.reset(summary_token)
        _BENCHMARK_SUPPRESS_SPINNER.reset(spinner_token)
        _BENCHMARK_SUPPRESS_DASHBOARD_REFRESH.reset(dashboard_refresh_token)
        _BENCHMARK_SUPPRESS_OUTPUT_PRUNE.reset(output_prune_token)
        _BENCHMARK_LIVE_STATUS_SLOTS.reset(live_slots_token)


@contextmanager
def _benchmark_split_phase_overrides(
    *,
    split_phase_slots: int | None = None,
    split_phase_gate_dir: Path | None = None,
    split_phase_status_label: str | None = None,
) -> Iterable[None]:
    slots_token = _BENCHMARK_SPLIT_PHASE_SLOTS.set(split_phase_slots)
    gate_dir_token = _BENCHMARK_SPLIT_PHASE_GATE_DIR.set(
        str(split_phase_gate_dir) if split_phase_gate_dir is not None else None
    )
    label_token = _BENCHMARK_SPLIT_PHASE_STATUS_LABEL.set(
        str(split_phase_status_label or "").strip() or None
    )
    try:
        yield
    finally:
        _BENCHMARK_SPLIT_PHASE_SLOTS.reset(slots_token)
        _BENCHMARK_SPLIT_PHASE_GATE_DIR.reset(gate_dir_token)
        _BENCHMARK_SPLIT_PHASE_STATUS_LABEL.reset(label_token)


@contextmanager
def _benchmark_scheduler_event_overrides(
    *,
    scheduler_event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Iterable[None]:
    callback_token = _BENCHMARK_SCHEDULER_EVENT_CALLBACK.set(
        scheduler_event_callback
    )
    try:
        yield
    finally:
        _BENCHMARK_SCHEDULER_EVENT_CALLBACK.reset(callback_token)


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


@dataclass(frozen=True)
class PredRunContext:
    recipes: int | None
    processed_report_path: str
    stage_block_predictions_path: str
    extracted_archive_path: str
    source_file: str
    source_hash: str | None
    run_config: dict[str, Any] | None
    run_config_hash: str | None
    run_config_summary: str | None
    tokens_input: int | None
    tokens_cached_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_total: int | None


@dataclass(frozen=True)
class BenchmarkPredictionBundle:
    import_result: dict[str, Any]
    pred_run: Path
    pred_context: PredRunContext
    stage_predictions_path: Path
    extracted_archive_path: Path
    prediction_phase_seconds: float


@dataclass(frozen=True)
class BenchmarkPredictionStageResult:
    prediction_bundle: BenchmarkPredictionBundle
    prediction_records: list[PredictionRecord]
    codexfarm_prompt_response_log_path: Path | None
    single_book_split_cache_metadata: dict[str, Any] | None


@dataclass(frozen=True)
class AllMethodTarget:
    gold_spans_path: Path
    source_file: Path
    source_file_name: str
    gold_display: str


@dataclass(frozen=True)
class AllMethodUnmatchedGold:
    gold_spans_path: Path
    reason: str
    source_hint: str | None
    gold_display: str


@dataclass(frozen=True)
class AllMethodVariant:
    slug: str
    run_settings: RunSettings
    dimensions: dict[str, Any]


@dataclass(frozen=True)
class _AllMethodSourceEstimate:
    estimated_seconds: float
    estimate_basis: str
    canonical_text_chars: int
    variant_count: int


@dataclass(frozen=True)
class _AllMethodSourceJobPlan:
    source_position: int
    source_group_key: str
    source_display_name: str
    source_slug: str
    source_file: Path
    gold_spans_path: Path
    variants: list[AllMethodVariant]
    shard_index: int
    shard_total: int
    estimated_seconds: float
    estimate_basis: str


@dataclass(frozen=True)
class _AllMethodGlobalWorkItem:
    global_dispatch_index: int
    source_position: int
    source_group_key: str
    source_slug: str
    source_file: Path
    source_file_name: str
    gold_spans_path: Path
    source_root: Path
    source_processed_root: Path
    canonical_alignment_cache_dir: Path
    config_index: int
    config_total: int
    source_shard_index: int
    source_shard_total: int
    source_estimated_seconds: float
    source_estimate_basis: str
    variant: AllMethodVariant


def _canonical_text_chars_for_all_method_target(target: AllMethodTarget) -> int:
    canonical_text_path = target.gold_spans_path.parent / "canonical_text.txt"
    if not canonical_text_path.exists() or not canonical_text_path.is_file():
        return 0
    try:
        return max(0, int(canonical_text_path.stat().st_size))
    except OSError:
        return 0


def _load_prior_all_method_source_runtime_seconds(
    *,
    prior_report_root: Path | None,
    target: AllMethodTarget,
) -> tuple[float | None, int | None]:
    if prior_report_root is None:
        return None, None
    report_path = prior_report_root / "all_method_benchmark_multi_source_report.json"
    if not report_path.exists() or not report_path.is_file():
        return None, None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None, None
    if not isinstance(payload, dict):
        return None, None
    source_rows = payload.get("sources")
    if not isinstance(source_rows, list):
        return None, None
    source_path = str(target.source_file)
    source_name = target.source_file_name
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        row_source_path = str(row.get("source_file") or "").strip()
        row_source_name = str(row.get("source_file_name") or "").strip()
        if row_source_path != source_path and row_source_name != source_name:
            continue
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        source_seconds = _report_optional_metric(
            timing_summary.get("source_wall_seconds")
        )
        if source_seconds is None or source_seconds <= 0:
            continue
        prior_variants = _report_count(row.get("variant_count_completed"))
        return source_seconds, (prior_variants if prior_variants > 0 else None)
    return None, None


def _estimate_all_method_source_cost(
    *,
    target: AllMethodTarget,
    variants: list[AllMethodVariant],
    prior_report_root: Path | None = None,
) -> _AllMethodSourceEstimate:
    variant_count = max(0, len(variants))
    canonical_text_chars = _canonical_text_chars_for_all_method_target(target)
    heuristic_seconds = max(
        1.0,
        (float(max(1, variant_count)) * 25.0) + (float(canonical_text_chars) / 1200.0),
    )
    prior_seconds, prior_variant_count = _load_prior_all_method_source_runtime_seconds(
        prior_report_root=prior_report_root,
        target=target,
    )
    if prior_seconds is not None:
        scale = 1.0
        if prior_variant_count is not None and prior_variant_count > 0 and variant_count > 0:
            scale = max(0.25, float(variant_count) / float(prior_variant_count))
        estimated = max(1.0, float(prior_seconds) * scale)
        basis = "prior_source_wall_seconds"
        if canonical_text_chars > 0:
            basis += "+canonical_text_chars"
        return _AllMethodSourceEstimate(
            estimated_seconds=estimated,
            estimate_basis=basis,
            canonical_text_chars=canonical_text_chars,
            variant_count=variant_count,
        )

    basis = "heuristic_variants"
    if canonical_text_chars > 0:
        basis += "+canonical_text_chars"
    return _AllMethodSourceEstimate(
        estimated_seconds=heuristic_seconds,
        estimate_basis=basis,
        canonical_text_chars=canonical_text_chars,
        variant_count=variant_count,
    )


def _split_all_method_source_variants(
    *,
    target: AllMethodTarget,
    variants: list[AllMethodVariant],
    estimate: _AllMethodSourceEstimate,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
) -> list[list[AllMethodVariant]]:
    _ = target
    if not variants:
        return [[]]
    total_variants = len(variants)
    threshold = max(1.0, float(shard_threshold_seconds))
    max_parts = max(1, _report_count(shard_max_parts))
    min_variants = max(1, _report_count(shard_min_variants))
    if max_parts <= 1:
        return [list(variants)]
    if total_variants < min_variants:
        return [list(variants)]
    if estimate.estimated_seconds < threshold:
        return [list(variants)]

    max_parts_by_variants = total_variants // min_variants
    if max_parts_by_variants < 2:
        return [list(variants)]
    shard_total = min(max_parts, max_parts_by_variants)
    if shard_total < 2:
        return [list(variants)]

    shards: list[list[AllMethodVariant]] = []
    base_size = total_variants // shard_total
    remainder = total_variants % shard_total
    cursor = 0
    for shard_index in range(shard_total):
        shard_size = base_size + (1 if shard_index < remainder else 0)
        next_cursor = cursor + shard_size
        shards.append(list(variants[cursor:next_cursor]))
        cursor = next_cursor
    if len(shards) <= 1:
        return [list(variants)]
    return shards


def _tail_pair_all_method_source_jobs(
    plans: list[_AllMethodSourceJobPlan],
) -> list[_AllMethodSourceJobPlan]:
    if len(plans) <= 2:
        return list(plans)
    ranked = sorted(
        plans,
        key=lambda plan: (
            -plan.estimated_seconds,
            plan.source_position,
            plan.shard_index,
            plan.source_slug,
        ),
    )
    left = 0
    right = len(ranked) - 1
    paired: list[_AllMethodSourceJobPlan] = []
    while left <= right:
        paired.append(ranked[left])
        left += 1
        if left <= right:
            paired.append(ranked[right])
            right -= 1
    return paired


def _plan_all_method_source_jobs(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    scheduling_strategy: str,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
) -> list[_AllMethodSourceJobPlan]:
    resolved_strategy = _normalize_all_method_source_scheduling(scheduling_strategy)
    resolved_shard_threshold_seconds = max(1.0, float(shard_threshold_seconds))
    resolved_shard_max_parts = max(1, _report_count(shard_max_parts))
    resolved_shard_min_variants = max(1, _report_count(shard_min_variants))

    slug_counts: dict[str, int] = {}
    plans: list[_AllMethodSourceJobPlan] = []
    for source_position, (target, variants) in enumerate(target_variants):
        estimate = _estimate_all_method_source_cost(
            target=target,
            variants=variants,
        )
        source_slug_base = slugify_name(target.source_file.stem)
        source_slug_count = slug_counts.get(source_slug_base, 0) + 1
        slug_counts[source_slug_base] = source_slug_count
        source_group_slug = (
            source_slug_base
            if source_slug_count == 1
            else f"{source_slug_base}__{source_slug_count:02d}"
        )
        shard_variants = _split_all_method_source_variants(
            target=target,
            variants=variants,
            estimate=estimate,
            shard_threshold_seconds=resolved_shard_threshold_seconds,
            shard_max_parts=resolved_shard_max_parts,
            shard_min_variants=resolved_shard_min_variants,
        )
        shard_total = max(1, len(shard_variants))
        for shard_index, shard in enumerate(shard_variants):
            shard_slug = (
                source_group_slug
                if shard_total == 1
                else (
                    f"{source_group_slug}__part_{shard_index + 1:02d}_of_{shard_total:02d}"
                )
            )
            shard_weight = (
                float(len(shard)) / float(len(variants))
                if variants
                else (1.0 / float(shard_total))
            )
            shard_estimated_seconds = max(
                1.0,
                float(estimate.estimated_seconds) * max(0.05, shard_weight),
            )
            plans.append(
                _AllMethodSourceJobPlan(
                    source_position=source_position,
                    source_group_key=source_group_slug,
                    source_display_name=target.source_file_name,
                    source_slug=shard_slug,
                    source_file=target.source_file,
                    gold_spans_path=target.gold_spans_path,
                    variants=list(shard),
                    shard_index=shard_index,
                    shard_total=shard_total,
                    estimated_seconds=shard_estimated_seconds,
                    estimate_basis=estimate.estimate_basis,
                )
            )

    if resolved_strategy == ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR:
        return _tail_pair_all_method_source_jobs(plans)
    return list(plans)


def _plan_all_method_global_work_items(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    scheduling_strategy: str,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
    root_output_dir: Path,
    processed_output_root: Path,
    canonical_alignment_cache_root: Path,
) -> list[_AllMethodGlobalWorkItem]:
    source_job_plans = _plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy=scheduling_strategy,
        shard_threshold_seconds=shard_threshold_seconds,
        shard_max_parts=shard_max_parts,
        shard_min_variants=shard_min_variants,
    )
    source_target_by_position: dict[int, AllMethodTarget] = {
        source_position: target
        for source_position, (target, _variants) in enumerate(target_variants)
    }
    source_config_totals: dict[int, int] = {
        source_position: len(variants)
        for source_position, (_target, variants) in enumerate(target_variants)
    }
    source_next_config_index: dict[int, int] = defaultdict(int)
    resolved_cache_root = canonical_alignment_cache_root.expanduser()

    work_items: list[_AllMethodGlobalWorkItem] = []
    global_dispatch_index = 0
    for plan in source_job_plans:
        source_target = source_target_by_position[plan.source_position]
        source_root = root_output_dir / plan.source_group_key
        source_processed_root = processed_output_root / plan.source_group_key
        canonical_alignment_cache_dir = resolved_cache_root / plan.source_group_key
        source_config_total = max(
            0,
            _report_count(source_config_totals.get(plan.source_position)),
        )
        for variant in plan.variants:
            global_dispatch_index += 1
            source_config_index = source_next_config_index[plan.source_position] + 1
            source_next_config_index[plan.source_position] = source_config_index
            work_items.append(
                _AllMethodGlobalWorkItem(
                    global_dispatch_index=global_dispatch_index,
                    source_position=plan.source_position,
                    source_group_key=plan.source_group_key,
                    source_slug=plan.source_slug,
                    source_file=plan.source_file,
                    source_file_name=source_target.source_file_name,
                    gold_spans_path=plan.gold_spans_path,
                    source_root=source_root,
                    source_processed_root=source_processed_root,
                    canonical_alignment_cache_dir=canonical_alignment_cache_dir,
                    config_index=source_config_index,
                    config_total=source_config_total,
                    source_shard_index=plan.shard_index,
                    source_shard_total=plan.shard_total,
                    source_estimated_seconds=plan.estimated_seconds,
                    source_estimate_basis=plan.estimate_basis,
                    variant=variant,
                )
            )
    return work_items


@dataclass
class _AllMethodSourceDashboardRow:
    source_name: str
    total_configs: int
    status: str = "pending"
    completed_configs: int = 0
    successful_configs: int = 0
    failed_configs: int = 0


@dataclass
class _AllMethodProgressDashboard:
    rows: list[_AllMethodSourceDashboardRow]
    total_planned_configs: int
    current_source_index: int | None = None
    current_config_index: int = 0
    current_config_total: int = 0
    current_config_slug: str = ""
    _core: ProgressDashboardCore = field(default_factory=ProgressDashboardCore, repr=False, compare=False)
    active_config_slugs_by_source: dict[int, dict[int, str]] = field(default_factory=dict)
    active_config_phases_by_source: dict[int, dict[int, str]] = field(default_factory=dict)
    task_message: str = ""
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    @classmethod
    def from_target_variants(
        cls,
        target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    ) -> "_AllMethodProgressDashboard":
        rows = [
            _AllMethodSourceDashboardRow(
                source_name=target.source_file_name,
                total_configs=max(0, len(variants)),
            )
            for target, variants in target_variants
        ]
        total_planned_configs = sum(row.total_configs for row in rows)
        return cls(rows=rows, total_planned_configs=total_planned_configs)

    def _completed_sources(self) -> int:
        return sum(1 for row in self.rows if row.status in {"done", "failed"})

    def _completed_configs(self) -> int:
        return sum(max(0, row.completed_configs) for row in self.rows)

    def _running_source_indices(self) -> list[int]:
        return [
            index
            for index, row in enumerate(self.rows)
            if str(row.status).strip().lower() == "running"
        ]

    def _set_focus_source_state(self, source_index: int | None) -> None:
        if source_index is None or source_index < 0 or source_index >= len(self.rows):
            self.current_source_index = None
            self.current_config_index = 0
            self.current_config_total = 0
            self.current_config_slug = ""
            return
        row = self.rows[source_index]
        self.current_source_index = source_index
        self.current_config_total = max(0, row.total_configs)
        active_for_source = self.active_config_slugs_by_source.get(source_index, {})
        if active_for_source:
            active_index = min(active_for_source)
            self.current_config_index = active_index
            self.current_config_slug = active_for_source.get(active_index, "")
            return
        if row.completed_configs >= row.total_configs:
            self.current_config_index = 0
            self.current_config_slug = ""
            return
        self.current_config_index = min(
            max(0, row.total_configs),
            max(1, row.completed_configs + 1),
        )
        self.current_config_slug = ""

    def start_source(self, source_index: int) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.status = "running"
            self.active_config_slugs_by_source.setdefault(source_index, {})
            self.active_config_phases_by_source.setdefault(source_index, {})
            self._set_focus_source_state(source_index)

    def finish_source(self, source_index: int, *, failed: bool = False) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.status = "failed" if failed else "done"
            self.active_config_slugs_by_source.pop(source_index, None)
            self.active_config_phases_by_source.pop(source_index, None)
            if self.current_source_index == source_index:
                running_indices = self._running_source_indices()
                if running_indices:
                    self._set_focus_source_state(running_indices[0])
                else:
                    self._set_focus_source_state(None)

    def start_config(
        self,
        *,
        source_index: int,
        config_index: int,
        config_total: int,
        config_slug: str,
    ) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            self.current_source_index = source_index
            self.current_config_index = max(0, config_index)
            self.current_config_total = max(0, config_total)
            self.current_config_slug = str(config_slug or "").strip()
            if self.current_config_index > 0:
                active_for_source = self.active_config_slugs_by_source.setdefault(
                    source_index,
                    {},
                )
                active_for_source[self.current_config_index] = self.current_config_slug
                phase_for_source = self.active_config_phases_by_source.setdefault(
                    source_index,
                    {},
                )
                phase_for_source[self.current_config_index] = "prep"
            row = self.rows[source_index]
            row.status = "running"

    def complete_config(
        self,
        *,
        source_index: int,
        success: bool,
        config_index: int | None = None,
    ) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.completed_configs = min(
                row.total_configs,
                max(0, row.completed_configs + 1),
            )
            if success:
                row.successful_configs = min(
                    row.total_configs,
                    max(0, row.successful_configs + 1),
                )
            else:
                row.failed_configs = min(
                    row.total_configs,
                    max(0, row.failed_configs + 1),
                )
            active_for_source = self.active_config_slugs_by_source.setdefault(
                source_index,
                {},
            )
            phase_for_source = self.active_config_phases_by_source.setdefault(
                source_index,
                {},
            )
            if config_index is not None:
                safe_index = max(0, config_index)
                active_for_source.pop(safe_index, None)
                phase_for_source.pop(safe_index, None)
            if not active_for_source:
                self.active_config_slugs_by_source.pop(source_index, None)
                self.active_config_phases_by_source.pop(source_index, None)
            if self.current_source_index == source_index:
                self._set_focus_source_state(source_index)

    @staticmethod
    def _normalize_config_phase(phase: str) -> str:
        normalized = str(phase or "").strip().lower()
        if normalized in {"split_wait", "split wait"}:
            return "split_wait"
        if normalized in {"split_active", "split active"}:
            return "split_active"
        if normalized in {"prep", "post", "evaluate"}:
            return normalized
        return "prep"

    @staticmethod
    def _format_config_phase_label(phase: str) -> str:
        normalized = _AllMethodProgressDashboard._normalize_config_phase(phase)
        if normalized == "split_wait":
            return "split wait"
        if normalized == "split_active":
            return "split active"
        return normalized

    def set_config_phase(
        self,
        *,
        source_index: int,
        config_index: int,
        phase: str,
    ) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            safe_index = max(0, config_index)
            if safe_index <= 0:
                return
            active_for_source = self.active_config_slugs_by_source.get(source_index, {})
            if safe_index not in active_for_source:
                return
            phase_for_source = self.active_config_phases_by_source.setdefault(
                source_index,
                {},
            )
            phase_for_source[safe_index] = self._normalize_config_phase(phase)

    def set_task(self, message: str) -> None:
        with self._lock:
            cleaned = str(message or "").strip().replace("\n", " ")
            self.task_message = cleaned

    def _iter_queue_rows(self) -> Iterable[_AllMethodSourceDashboardRow]:
        if len(self.rows) <= 10:
            for row in self.rows:
                yield row
            return
        if self.current_source_index is None:
            visible_indices = set(range(0, 6))
        else:
            start = max(0, self.current_source_index - 2)
            end = min(len(self.rows), start + 6)
            visible_indices = set(range(start, end))
        visible_indices.update({len(self.rows) - 2, len(self.rows) - 1})
        for index, row in enumerate(self.rows):
            if index in visible_indices:
                yield row

    def _queue_rows(self) -> list[ProgressQueueRow]:
        marker_by_status = {
            "pending": "[ ]",
            "running": "[>]",
            "done": "[x]",
            "failed": "[!]",
        }
        rows = list(self.rows) if len(self.rows) <= 10 else list(self._iter_queue_rows())
        queue_rows = [
            ProgressQueueRow(
                marker=marker_by_status.get(row.status, "[ ]"),
                name=str(row.source_name),
                completed=max(0, row.completed_configs),
                total=max(0, row.total_configs),
                ok=max(0, row.successful_configs),
                fail=max(0, row.failed_configs),
            )
            for row in rows
        ]
        if len(self.rows) > 10:
            rendered_ids = {id(row) for row in rows}
            hidden_count = sum(1 for row in self.rows if id(row) not in rendered_ids)
            if hidden_count > 0:
                queue_rows.append(
                    ProgressQueueRow(
                        marker="...",
                        name=f"{hidden_count} additional sources hidden",
                        completed=0,
                        total=0,
                        ok=0,
                        fail=0,
                    )
                )
        return queue_rows

    def render(self) -> str:
        with self._lock:
            source_total = len(self.rows)
            source_done = self._completed_sources()
            config_done = self._completed_configs()
            detail_lines: list[str] = []
            active_source_count = len(self._running_source_indices())
            if active_source_count > 0:
                detail_lines.append(f"active sources: {active_source_count}")

            if (
                self.current_source_index is not None
                and 0 <= self.current_source_index < len(self.rows)
            ):
                current_row = self.rows[self.current_source_index]
                detail_lines.append(
                    (
                        "current source: "
                        f"{current_row.source_name} "
                        f"({current_row.completed_configs} of {current_row.total_configs} configs; "
                        f"ok {current_row.successful_configs}, fail {current_row.failed_configs})"
                    )
                )
            if self.current_config_total > 0 and self.current_source_index is not None:
                phase_items = self.active_config_phases_by_source.get(
                    self.current_source_index,
                    {},
                )
                active_items = sorted(
                    self.active_config_slugs_by_source.get(
                        self.current_source_index,
                        {},
                    ).items()
                )
                if active_items:
                    if len(active_items) == 1:
                        active_index, active_slug = active_items[0]
                        slug = active_slug or "<pending>"
                        detail_lines.append(
                            (
                                f"current config {active_index}/{self.current_config_total}: "
                                f"{slug}"
                            )
                        )
                    else:
                        first_active = active_items[0][0]
                        last_active = active_items[-1][0]
                        detail_lines.append(
                            f"current configs {first_active}-{last_active}/"
                            f"{self.current_config_total} ({len(active_items)} active)"
                        )
                        detail_lines.append("active config workers:")
                        for active_index, active_slug in active_items:
                            phase = self._format_config_phase_label(
                                phase_items.get(active_index, "prep")
                            )
                            slug = active_slug or "<pending>"
                            if len(slug) > 120:
                                slug = f"{slug[:117]}..."
                            detail_lines.append(
                                f"  config {active_index:02d}: {phase} | {slug}"
                            )
                elif 0 <= self.current_source_index < len(self.rows):
                    current_row = self.rows[self.current_source_index]
                    if current_row.completed_configs < current_row.total_configs:
                        queued_index = min(
                            current_row.total_configs,
                            max(1, current_row.completed_configs + 1),
                        )
                        detail_lines.append(
                            f"current config {queued_index}/{self.current_config_total}: <queued>"
                        )
            status_line = (
                "overall "
                f"source {source_done}/{source_total} | "
                f"config {config_done}/{max(0, self.total_planned_configs)}"
            )
            self._core.set_status_line(status_line)
            self._core.set_extra_lines(detail_lines)
            self._core.set_task(self.task_message)
            self._core.set_queue_rows(self._queue_rows())
            return self._core.render()


@dataclass
class _SingleProfileBookDashboardRow:
    source_name: str
    total_configs: int
    status: str = "pending"
    completed_configs: int = 0
    successful_configs: int = 0
    failed_configs: int = 0
    current_variant_index: int = 0
    current_variant_total: int = 0
    current_variant_slug: str = ""
    current_stage_label: str = ""
    current_message: str = ""
    work_unit_label: str = ""
    current_counter: tuple[int, int] | None = None
    worker_total: int = 0
    worker_statuses: dict[int, str] = field(default_factory=dict)
    worker_running: int = 0
    worker_completed: int = 0
    worker_failed: int = 0
    followup_running: int = 0
    followup_completed: int = 0
    followup_total: int = 0
    followup_label: str = ""
    phase_started_at: float | None = None
    rate_total: int | None = None
    rate_last_current: int | None = None
    rate_last_progress_at: float | None = None
    rate_sampled_seconds: float = 0.0
    rate_sampled_units: int = 0
    rate_recent_samples: deque[tuple[float, int]] = field(
        default_factory=lambda: deque(maxlen=_STATUS_RATE_RECENT_WINDOW),
        repr=False,
        compare=False,
    )

    @property
    def short_name(self) -> str:
        stem = Path(self.source_name).stem.strip()
        return stem or self.source_name


@dataclass
class _SingleProfileProgressDashboard:
    rows: list[_SingleProfileBookDashboardRow]
    total_planned_configs: int
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def _completed_sources(self) -> int:
        return sum(1 for row in self.rows if row.status in {"done", "failed"})

    def _completed_configs(self) -> int:
        return sum(max(0, row.completed_configs) for row in self.rows)

    @staticmethod
    def _truncate_cell(value: str, width: int) -> str:
        text = str(value or "").strip()
        if width <= 0:
            return ""
        if len(text) <= width:
            return text.ljust(width)
        if width <= 3:
            return text[:width]
        return f"{text[: max(1, width - 3)]}...".ljust(width)

    def _book_column_width(self, book_count: int) -> int:
        if book_count <= 0:
            return 12
        max_table_width = 118
        label_width = 7
        overhead = label_width + (3 * book_count) + 2
        available = max(8, max_table_width - overhead)
        return max(8, min(24, available // max(1, book_count)))

    def _render_grid_row(
        self,
        label: str,
        cells: Sequence[str],
        *,
        label_width: int,
        col_width: int,
    ) -> str:
        rendered_cells = [
            self._truncate_cell(cell, col_width)
            for cell in cells
        ]
        return (
            f"{str(label or '').strip()[:label_width].ljust(label_width)} | "
            + " | ".join(rendered_cells)
        ).rstrip()

    @staticmethod
    def _compact_work_unit_label(label: str) -> str:
        cleaned = str(label or "").strip().lower()
        if not cleaned:
            return "t"
        if "packet" in cleaned:
            return "pkt"
        if "recipe" in cleaned and "task" in cleaned:
            return "rt"
        if "task" in cleaned:
            return "t"
        letters = "".join(ch for ch in cleaned if ch.isalpha())
        if not letters:
            return "t"
        return letters[: min(3, len(letters))]

    @staticmethod
    def _estimate_eta_seconds(row: _SingleProfileBookDashboardRow, now: float) -> int | None:
        counter = row.current_counter
        if counter is None:
            return None
        current, total = counter
        remaining = max(0, total - current)
        if remaining <= 0:
            return 0
        avg_seconds_per_task = _recent_rate_average_seconds_per_task(
            row.rate_recent_samples
        )
        if avg_seconds_per_task is None and row.rate_sampled_units > 0 and row.rate_sampled_seconds > 0:
            avg_seconds_per_task = row.rate_sampled_seconds / float(row.rate_sampled_units)
        if (
            avg_seconds_per_task is None
            and current > 0
            and row.phase_started_at is not None
        ):
            bootstrap_elapsed = max(0.0, now - row.phase_started_at)
            if bootstrap_elapsed >= _STATUS_ETA_BOOTSTRAP_MIN_SECONDS:
                avg_seconds_per_task = bootstrap_elapsed / float(current)
        if avg_seconds_per_task is None or avg_seconds_per_task <= 0:
            return None
        if row.rate_sampled_units <= 0 or row.rate_sampled_seconds <= 0:
            bootstrap_parallelism = max(
                1,
                len(row.worker_statuses),
                row.worker_total,
            )
            return _parallel_bootstrap_eta_seconds(
                avg_seconds_per_task=avg_seconds_per_task,
                remaining=remaining,
                parallelism=bootstrap_parallelism,
            )
        return max(0, int(round(avg_seconds_per_task * remaining)))

    def start_source(self, source_index: int) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            self.rows[source_index].status = "running"

    def finish_source(self, source_index: int, *, failed: bool = False) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.status = "failed" if failed else "done"
            row.current_stage_label = "failed" if failed else "done"
            row.current_message = row.current_stage_label
            row.work_unit_label = ""
            row.current_counter = None
            row.worker_total = 0
            row.worker_statuses = {}
            row.worker_running = 0
            row.worker_completed = 0
            row.worker_failed = 0
            row.followup_running = 0
            row.followup_completed = 0
            row.followup_total = 0
            row.followup_label = ""

    def start_config(
        self,
        *,
        source_index: int,
        config_index: int,
        config_total: int,
        config_slug: str,
    ) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.status = "running"
            row.current_variant_index = max(0, config_index)
            row.current_variant_total = max(0, config_total)
            row.current_variant_slug = str(config_slug or "").strip()
            row.current_stage_label = "queued"
            row.current_message = row.current_variant_slug or "queued"
            row.work_unit_label = ""
            row.current_counter = None
            row.worker_total = 0
            row.worker_statuses = {}
            row.worker_running = 0
            row.worker_completed = 0
            row.worker_failed = 0
            row.followup_running = 0
            row.followup_completed = 0
            row.followup_total = 0
            row.followup_label = ""
            row.phase_started_at = time.monotonic()
            row.rate_total = None
            row.rate_last_current = None
            row.rate_last_progress_at = None
            row.rate_sampled_seconds = 0.0
            row.rate_sampled_units = 0
            row.rate_recent_samples.clear()

    def complete_config(
        self,
        *,
        source_index: int,
        success: bool,
        config_index: int | None = None,
    ) -> None:
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            row.completed_configs = min(
                row.total_configs,
                max(0, row.completed_configs + 1),
            )
            if success:
                row.successful_configs = min(
                    row.total_configs,
                    max(0, row.successful_configs + 1),
                )
            else:
                row.failed_configs = min(
                    row.total_configs,
                    max(0, row.failed_configs + 1),
                )
            if config_index is not None and row.current_variant_index == max(0, config_index):
                row.current_counter = None
                row.worker_total = 0
                row.worker_statuses = {}
                row.worker_running = 0
                row.worker_completed = 0
                row.worker_failed = 0
                row.followup_running = 0
                row.followup_completed = 0
                row.followup_total = 0
                row.followup_label = ""
                row.current_stage_label = "done" if success else "failed"
                row.current_message = row.current_stage_label

    def ingest_progress(
        self,
        *,
        source_index: int,
        message: str,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned:
            return
        with self._lock:
            if source_index < 0 or source_index >= len(self.rows):
                return
            row = self.rows[source_index]
            payload = parse_worker_activity(cleaned)
            stage_progress = None if payload is not None else parse_stage_progress(cleaned)
            now = time.monotonic()
            if payload is not None:
                payload_type = str(payload.get("type") or "").strip().lower()
                if payload_type == "reset":
                    row.worker_total = 0
                    row.worker_statuses = {}
                    row.worker_running = 0
                    row.worker_completed = 0
                    row.worker_failed = 0
                    return
                if payload_type == "activity":
                    worker_total = max(1, int(payload.get("worker_total", 1)))
                    worker_index = max(1, int(payload.get("worker_index", 1)))
                    status = str(payload.get("status") or "").strip()
                    row.worker_total = worker_total
                    row.worker_statuses[worker_index] = status or "processing"
                    row.worker_running = max(
                        row.worker_running,
                        sum(
                            1
                            for value in row.worker_statuses.values()
                            if str(value).strip().lower() not in {"", "idle", "done", "failed", "skipped"}
                        ),
                    )
                    return

            structured_counter: tuple[int, int] | None = None
            if stage_progress is not None:
                cleaned = str(stage_progress.get("message") or "").strip() or cleaned
                row.work_unit_label = str(stage_progress.get("work_unit_label") or "").strip()
                task_current = stage_progress.get("task_current")
                task_total = stage_progress.get("task_total")
                if task_current is not None and task_total is not None:
                    structured_counter = (int(task_current), int(task_total))

            row.status = "running"
            row.current_message = cleaned
            row.phase_started_at = row.phase_started_at or now

            counter = (
                structured_counter
                if structured_counter is not None
                else _extract_progress_counter(cleaned)
            )
            if counter is None:
                row.current_counter = None
                row.rate_total = None
                row.rate_last_current = None
                row.rate_last_progress_at = None
                row.rate_sampled_seconds = 0.0
                row.rate_sampled_units = 0
                row.rate_recent_samples.clear()
            else:
                current_value, total_value = counter
                should_reset = (
                    row.rate_total is None
                    or row.rate_last_current is None
                    or row.rate_last_progress_at is None
                    or total_value != row.rate_total
                    or current_value < row.rate_last_current
                )
                if should_reset:
                    row.rate_total = total_value
                    row.rate_last_current = current_value
                    row.rate_last_progress_at = now
                    row.rate_sampled_seconds = 0.0
                    row.rate_sampled_units = 0
                    row.rate_recent_samples.clear()
                else:
                    delta = current_value - row.rate_last_current
                    if delta > 0:
                        elapsed_since_progress = max(0.0, now - row.rate_last_progress_at)
                        if elapsed_since_progress > 0:
                            row.rate_sampled_seconds += elapsed_since_progress
                            row.rate_sampled_units += delta
                            row.rate_recent_samples.append((elapsed_since_progress, delta))
                        row.rate_last_current = current_value
                        row.rate_last_progress_at = now
                row.current_counter = counter

            if stage_progress is not None:
                stage_label = (
                    str(stage_progress.get("stage_label") or "").strip()
                    or _extract_progress_stage_label(cleaned)
                    or "running"
                )
                previous_stage_label = row.current_stage_label
                active_tasks = stage_progress.get("active_tasks")
                running_workers = stage_progress.get("running_workers")
                worker_total_hint = stage_progress.get("worker_total")
                worker_running_hint = stage_progress.get("worker_running")
                worker_completed_hint = stage_progress.get("worker_completed")
                worker_failed_hint = stage_progress.get("worker_failed")
                followup_running_hint = stage_progress.get("followup_running")
                followup_completed_hint = stage_progress.get("followup_completed")
                followup_total_hint = stage_progress.get("followup_total")
                followup_label_hint = stage_progress.get("followup_label")
                row.current_stage_label = stage_label
                row.worker_statuses = {}
                running_slots = (
                    max(0, int(worker_running_hint))
                    if worker_running_hint is not None
                    else max(0, int(running_workers))
                    if running_workers is not None
                    else 0
                )
                completed_slots = max(0, int(worker_completed_hint or 0))
                failed_slots = max(0, int(worker_failed_hint or 0))
                if isinstance(active_tasks, list):
                    for worker_index, task in enumerate(active_tasks, start=1):
                        task_text = str(task).strip()
                        if task_text:
                            row.worker_statuses[worker_index] = task_text
                while len(row.worker_statuses) < running_slots:
                    row.worker_statuses[len(row.worker_statuses) + 1] = "running"
                for _ in range(completed_slots):
                    row.worker_statuses[len(row.worker_statuses) + 1] = "done"
                for _ in range(failed_slots):
                    row.worker_statuses[len(row.worker_statuses) + 1] = "failed"
                worker_total = max(0, len(row.worker_statuses))
                if worker_total_hint is not None:
                    worker_total = max(worker_total, max(0, int(worker_total_hint)))
                row.worker_total = worker_total
                row.worker_running = running_slots
                row.worker_completed = completed_slots
                row.worker_failed = failed_slots
                row.followup_running = max(0, int(followup_running_hint or 0))
                row.followup_completed = max(0, int(followup_completed_hint or 0))
                row.followup_total = max(0, int(followup_total_hint or 0))
                row.followup_label = str(followup_label_hint or "").strip()
                if stage_label != previous_stage_label:
                    row.rate_total = None
                    row.rate_last_current = None
                    row.rate_last_progress_at = None
                    row.rate_sampled_seconds = 0.0
                    row.rate_sampled_units = 0
                    row.rate_recent_samples.clear()
                return

            if cleaned.lower().startswith("codex-farm "):
                summary, stage_label = _summarize_codex_progress_message(cleaned)
                row.current_message = summary
                row.current_stage_label = stage_label or "codex-farm"
                row.work_unit_label = ""
                active_tasks = _extract_active_tasks(cleaned)
                running_workers = _extract_running_workers(cleaned)
                if active_tasks is not None:
                    row.worker_statuses = {
                        worker_index: task
                        for worker_index, task in enumerate(active_tasks, start=1)
                    }
                else:
                    row.worker_statuses = {}
                worker_total = len(row.worker_statuses)
                if running_workers is not None:
                    worker_total = max(worker_total, running_workers)
                row.worker_total = max(0, worker_total)
                row.worker_running = max(0, int(running_workers or 0))
                row.worker_completed = 0
                row.worker_failed = 0
                row.followup_running = 0
                row.followup_completed = 0
                row.followup_total = 0
                row.followup_label = ""
                return

            stage_text = cleaned.split("|", 1)[0].strip()
            if counter is not None and stage_text:
                stage_text = stage_text.rsplit(" task ", 1)[0].strip()
            row.current_stage_label = stage_text or "running"
            row.work_unit_label = ""
            running_workers = _extract_running_workers(cleaned)
            row.worker_total = max(0, running_workers or 0)
            row.worker_statuses = {}
            row.worker_running = max(0, int(running_workers or 0))
            row.worker_completed = 0
            row.worker_failed = 0
            row.followup_running = 0
            row.followup_completed = 0
            row.followup_total = 0
            row.followup_label = ""

    def render(self) -> str:
        with self._lock:
            source_total = len(self.rows)
            source_done = self._completed_sources()
            config_done = self._completed_configs()
            lines = [
                (
                    "overall "
                    f"source {source_done}/{source_total} | "
                    f"config {config_done}/{max(0, self.total_planned_configs)}"
                )
            ]
            if not self.rows:
                return "\n".join(lines)

            col_width = self._book_column_width(len(self.rows))
            label_width = 7
            now = time.monotonic()
            lines.append("books:")
            lines.append(
                self._render_grid_row(
                    "book",
                    [row.short_name for row in self.rows],
                    label_width=label_width,
                    col_width=col_width,
                )
            )
            lines.append(
                self._render_grid_row(
                    "state",
                    [
                        (
                            "queued"
                            if row.status == "pending"
                            else ("failed" if row.status == "failed" else row.current_stage_label or row.status)
                        )
                        for row in self.rows
                    ],
                    label_width=label_width,
                    col_width=col_width,
                )
            )
            lines.append(
                self._render_grid_row(
                    "prog",
                    [
                        (
                            f"{self._compact_work_unit_label(row.work_unit_label)}{counter[0]}/{counter[1]} v{row.completed_configs}/{row.total_configs}"
                            if (counter := row.current_counter) is not None
                            else f"v{row.completed_configs}/{row.total_configs} ok{row.successful_configs} f{row.failed_configs}"
                        )
                        for row in self.rows
                    ],
                    label_width=label_width,
                    col_width=col_width,
                )
            )
            lines.append(
                self._render_grid_row(
                    "eta",
                    [
                        (
                            "--"
                            if row.status != "running"
                            else (
                                _format_processing_time(float(eta_seconds))
                                if (eta_seconds := self._estimate_eta_seconds(row, now)) is not None
                                else "--"
                            )
                        )
                        for row in self.rows
                    ],
                    label_width=label_width,
                    col_width=col_width,
                )
            )
            if any(
                row.followup_running > 0
                or row.followup_total > 0
                or row.followup_completed > 0
                or row.followup_label
                for row in self.rows
            ):
                lines.append(
                    self._render_grid_row(
                        "repo",
                        [
                            (
                                " | ".join(
                                    [
                                        item
                                        for item in (
                                            str(row.followup_label or "").strip() or "follow-up",
                                            (
                                                f"{row.followup_completed}/{row.followup_total}"
                                                if row.followup_total > 0
                                                else None
                                            ),
                                            (
                                                f"run {row.followup_running}"
                                                if row.followup_running > 0
                                                else None
                                            ),
                                        )
                                        if item
                                    ]
                                )
                                if (
                                    row.followup_running > 0
                                    or row.followup_total > 0
                                    or row.followup_completed > 0
                                    or row.followup_label
                                )
                                else "--"
                            )
                            for row in self.rows
                        ],
                        label_width=label_width,
                        col_width=col_width,
                    )
                )

            max_worker_rows = max(
                [
                    max(0, row.worker_total, len(row.worker_statuses))
                    for row in self.rows
                ],
                default=0,
            )
            for worker_index in range(1, max_worker_rows + 1):
                worker_cells = []
                for row in self.rows:
                    worker_text = str(row.worker_statuses.get(worker_index) or "").strip()
                    if not worker_text and worker_index <= row.worker_total:
                        worker_text = "busy"
                    worker_cells.append(worker_text or "--")
                lines.append(
                    self._render_grid_row(
                        f"w{worker_index:02d}",
                        worker_cells,
                        label_width=label_width,
                        col_width=col_width,
                    )
                )
            return "\n".join(lines)


def _load_pred_run_recipe_context(
    pred_run: Path,
) -> PredRunContext:
    """Return recipe/report/source/run-config context for a prediction run."""
    manifest_path = pred_run / "manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            stage_block_predictions_path="",
            extracted_archive_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            tokens_input=None,
            tokens_cached_input=None,
            tokens_output=None,
            tokens_reasoning=None,
            tokens_total=None,
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            stage_block_predictions_path="",
            extracted_archive_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            tokens_input=None,
            tokens_cached_input=None,
            tokens_output=None,
            tokens_reasoning=None,
            tokens_total=None,
        )
    if not isinstance(payload, dict):
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            stage_block_predictions_path="",
            extracted_archive_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
            tokens_input=None,
            tokens_cached_input=None,
            tokens_output=None,
            tokens_reasoning=None,
            tokens_total=None,
        )

    source_file = str(payload.get("source_file") or "")
    source_hash = str(payload.get("source_hash") or "").strip() or None
    processed_report_path = str(payload.get("processed_report_path") or "")
    stage_block_predictions_path = str(payload.get("stage_block_predictions_path") or "")
    extracted_archive_path = str(payload.get("extracted_archive_path") or "")
    run_config = payload.get("run_config")
    if not isinstance(run_config, dict):
        run_config = None
    run_config_hash = str(payload.get("run_config_hash") or "").strip() or None
    run_config_summary = str(payload.get("run_config_summary") or "").strip() or None
    llm_codex_farm_payload = payload.get("llm_codex_farm")
    tokens_input = None
    tokens_cached_input = None
    tokens_output = None
    tokens_reasoning = None
    tokens_total = None
    codex_farm_tokens = (None, None, None, None, None)
    if isinstance(llm_codex_farm_payload, dict):
        codex_farm_tokens = _extract_codex_farm_token_usage_from_llm_manifest(
            llm_codex_farm_payload
        )
    line_role_tokens = _extract_line_role_token_usage_from_manifest(payload)
    (
        tokens_input,
        tokens_cached_input,
        tokens_output,
        tokens_reasoning,
        tokens_total,
    ) = _sum_token_usage(codex_farm_tokens, line_role_tokens)
    if isinstance(run_config, dict) and isinstance(llm_codex_farm_payload, dict):
        merged_run_config = dict(run_config)
        run_config_updated = False
        codex_cmd = _single_book_text_or_none(merged_run_config.get("codex_farm_cmd"))
        existing_model = _single_book_text_or_none(
            merged_run_config.get("codex_farm_model")
        ) or _single_book_text_or_none(merged_run_config.get("codex_model"))
        inferred_model, inferred_reasoning_effort = _extract_codex_farm_runtime_from_llm_manifest(
            llm_codex_farm_payload
        )
        resolved_model = existing_model or _single_book_text_or_none(inferred_model)
        if resolved_model is not None and not _single_book_text_or_none(
            merged_run_config.get("codex_farm_model")
        ):
            merged_run_config["codex_farm_model"] = resolved_model
            run_config_updated = True

        resolved_reasoning_effort = _resolve_single_book_reasoning_effort(
            merged_run_config.get("codex_farm_reasoning_effort")
            or merged_run_config.get("codex_reasoning_effort"),
            codex_cmd=codex_cmd,
            codex_model=resolved_model,
        )
        if resolved_reasoning_effort is None:
            resolved_reasoning_effort = _resolve_single_book_reasoning_effort(
                inferred_reasoning_effort,
                codex_cmd=codex_cmd,
                codex_model=resolved_model,
            )
        if (
            resolved_reasoning_effort is not None
            and _single_book_text_or_none(
                merged_run_config.get("codex_farm_reasoning_effort")
            )
            != resolved_reasoning_effort
        ):
            merged_run_config["codex_farm_reasoning_effort"] = resolved_reasoning_effort
            run_config_updated = True

        if run_config_updated:
            run_config = merged_run_config
            # Recompute against enriched payload when benchmark CSV append persists this context.
            run_config_hash = None
            run_config_summary = None

    recipes: int | None
    try:
        recipes = int(payload.get("recipe_count"))
    except (TypeError, ValueError):
        recipes = None

    if recipes is None and processed_report_path:
        recipes = _load_total_recipes_from_report_path(processed_report_path)

    return PredRunContext(
        recipes=recipes,
        processed_report_path=processed_report_path,
        stage_block_predictions_path=stage_block_predictions_path,
        extracted_archive_path=extracted_archive_path,
        source_file=source_file,
        source_hash=source_hash,
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        tokens_input=tokens_input,
        tokens_cached_input=tokens_cached_input,
        tokens_output=tokens_output,
        tokens_reasoning=tokens_reasoning,
        tokens_total=tokens_total,
    )


def _resolve_stage_predictions_for_benchmark(
    *,
    import_result: dict[str, Any],
    pred_context: PredRunContext,
    pred_run: Path,
) -> Path:
    stage_predictions_candidates: list[Path] = []
    for value in (
        import_result.get("stage_block_predictions_path"),
        pred_context.stage_block_predictions_path,
    ):
        if not value:
            continue
        stage_predictions_candidates.append(Path(str(value)))

    for candidate in stage_predictions_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    _fail(
        "This prediction run is missing canonical stage block predictions "
        "(stage_block_predictions_path). Re-run benchmark after updating."
    )
    return pred_run / "stage_block_predictions.json"


def _resolve_extracted_archive_for_benchmark(
    *,
    import_result: dict[str, Any],
    pred_context: PredRunContext,
    pred_run: Path,
) -> Path:
    archive_candidates: list[Path] = []
    for value in (
        import_result.get("extracted_archive_path"),
        pred_context.extracted_archive_path,
    ):
        if not value:
            continue
        archive_candidates.append(Path(str(value)))

    for candidate in archive_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    _fail(
        "This prediction run is missing canonical extracted archive evidence "
        "(extracted_archive_path). Re-run benchmark after updating."
    )
    return pred_run / "extracted_archive.json"


def _resolve_line_role_predictions_for_benchmark(
    *,
    import_result: dict[str, Any],
    pred_run: Path,
) -> Path | None:
    candidates: list[Path] = []
    for value in (
        import_result.get("line_role_pipeline_line_role_predictions_path"),
        pred_run / "line-role-pipeline" / "line_role_predictions.jsonl",
    ):
        if not value:
            continue
        candidates.append(Path(str(value)))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _load_json_object_or_none(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_jsonl_dict_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _build_prediction_bundle_from_import_result(
    *,
    import_result: dict[str, Any],
    prediction_phase_seconds: float,
) -> BenchmarkPredictionBundle:
    pred_run = Path(import_result["run_root"]).expanduser()
    if not pred_run.exists() or not pred_run.is_dir():
        _fail(f"Prediction artifact directory not found: {pred_run}")
    pred_context = _load_pred_run_recipe_context(pred_run)
    default_stage_predictions_path = _resolve_stage_predictions_for_benchmark(
        import_result=import_result,
        pred_context=pred_context,
        pred_run=pred_run,
    )
    default_extracted_archive_path = _resolve_extracted_archive_for_benchmark(
        import_result=import_result,
        pred_context=pred_context,
        pred_run=pred_run,
    )
    return BenchmarkPredictionBundle(
        import_result=import_result,
        pred_run=pred_run,
        pred_context=pred_context,
        stage_predictions_path=default_stage_predictions_path,
        extracted_archive_path=default_extracted_archive_path,
        prediction_phase_seconds=max(0.0, prediction_phase_seconds),
    )


def _run_offline_benchmark_prediction_stage(
    *,
    prediction_generation_kwargs: dict[str, Any],
    eval_output_dir: Path,
    predictions_out_path: Path | None,
    suppress_spinner: bool = True,
    external_progress_callback: Callable[[str], None] | None = None,
) -> BenchmarkPredictionStageResult:
    prediction_generation_kwargs = dict(prediction_generation_kwargs)
    prediction_generation_kwargs.setdefault("run_root_override", eval_output_dir)
    prediction_generation_kwargs.setdefault("mirror_stage_artifacts_into_run_root", False)
    selected_source = Path(prediction_generation_kwargs["path"]).expanduser()
    selected_epub_extractor = str(
        prediction_generation_kwargs.get("epub_extractor") or "unstructured"
    ).strip().lower() or "unstructured"
    selected_html_parser_version = str(
        prediction_generation_kwargs.get(
            "epub_unstructured_html_parser_version"
        )
        or "v1"
    ).strip().lower() or "v1"
    selected_skip_headers_footers = bool(
        prediction_generation_kwargs.get("epub_unstructured_skip_headers_footers", True)
    )
    selected_preprocess_mode = str(
        prediction_generation_kwargs.get("epub_unstructured_preprocess_mode")
        or "br_split_v1"
    ).strip().lower() or "br_split_v1"
    write_markdown = bool(prediction_generation_kwargs.get("write_markdown"))
    write_label_studio_tasks = bool(
        prediction_generation_kwargs.get("write_label_studio_tasks")
    )
    should_upload_predictions = False
    line_role_pipeline = str(
        prediction_generation_kwargs.get("line_role_pipeline") or "off"
    ).strip().lower()

    with _temporary_epub_extractor(selected_epub_extractor):
        with _temporary_epub_unstructured_options(
            html_parser_version=selected_html_parser_version,
            skip_headers_footers=selected_skip_headers_footers,
            preprocess_mode=selected_preprocess_mode,
        ):
            prediction_phase_started = time.monotonic()
            if suppress_spinner:
                if external_progress_callback is not None:
                    external_progress_callback(
                        f"Generating prediction tasks for {selected_source.name}..."
                    )
                import_result = generate_pred_run_artifacts(**prediction_generation_kwargs)
            else:
                def _run_with_status(
                    update_progress: Callable[[str], None],
                ) -> dict[str, Any]:
                    if external_progress_callback is None:
                        return generate_pred_run_artifacts(**prediction_generation_kwargs)

                    def _combined_progress(message: str) -> None:
                        update_progress(message)
                        external_progress_callback(message)

                    generation_kwargs = dict(prediction_generation_kwargs)
                    generation_kwargs["progress_callback"] = _combined_progress
                    return generate_pred_run_artifacts(**generation_kwargs)

                import_result = _run_with_progress_status(
                    initial_status=(
                        f"Generating prediction tasks for {selected_source.name}..."
                    ),
                    progress_prefix=f"Benchmark import ({selected_source.name})",
                    run=_run_with_status,
                    telemetry_path=(
                        eval_output_dir / "processing_timeseries_prediction.jsonl"
                    ),
                )
            prediction_phase_seconds = max(
                0.0, time.monotonic() - prediction_phase_started
            )

    prediction_bundle = _build_prediction_bundle_from_import_result(
        import_result=import_result,
        prediction_phase_seconds=prediction_phase_seconds,
    )
    prediction_records = list(
        predict_stage(
            bundle=prediction_bundle,
            selected_source=selected_source,
        )
    )
    if predictions_out_path is not None:
        write_prediction_records(predictions_out_path, prediction_records)

    pred_run = prediction_bundle.pred_run
    pred_context = prediction_bundle.pred_context
    prediction_timing = _normalize_timing_payload(import_result.get("timing"))
    prediction_seconds = _report_optional_metric(
        prediction_timing.get("prediction_seconds")
    )
    if prediction_seconds is None:
        prediction_seconds = _report_optional_metric(
            prediction_timing.get("total_seconds")
        )
    if prediction_seconds is None:
        prediction_seconds = prediction_phase_seconds
    prediction_seconds = max(0.0, float(prediction_seconds))
    benchmark_timing = _timing_with_updates(
        prediction_timing,
        prediction_seconds=prediction_seconds,
        evaluation_seconds=0.0,
        total_seconds=max(
            prediction_seconds,
            max(0.0, time.monotonic() - prediction_phase_started),
        ),
    )

    prediction_stage_run_config: dict[str, Any] = {
        "prediction_record_output": (
            str(predictions_out_path) if predictions_out_path is not None else None
        ),
        "upload": should_upload_predictions,
        "write_markdown": write_markdown,
        "write_label_studio_tasks": write_label_studio_tasks,
    }
    single_book_split_cache_metadata = import_result.get(
        "single_book_split_cache"
    )
    if isinstance(single_book_split_cache_metadata, dict):
        prediction_stage_run_config["single_book_split_cache"] = dict(
            single_book_split_cache_metadata
        )
    if pred_context.run_config is not None:
        prediction_stage_run_config["prediction_run_config"] = pred_context.run_config
        prediction_stage_run_config.update(
            _benchmark_selective_retry_manifest_summary(pred_context.run_config)
        )
    if pred_context.run_config_hash:
        prediction_stage_run_config["prediction_run_config_hash"] = (
            pred_context.run_config_hash
        )
    if pred_context.run_config_summary:
        prediction_stage_run_config["prediction_run_config_summary"] = (
            pred_context.run_config_summary
        )

    prediction_stage_artifacts: dict[str, Any] = {
        "artifact_root_dir": _path_for_manifest(eval_output_dir, pred_run),
        "stage_block_predictions_json": _path_for_manifest(
            eval_output_dir,
            prediction_bundle.stage_predictions_path,
        ),
        "extracted_archive_json": _path_for_manifest(
            eval_output_dir,
            prediction_bundle.extracted_archive_path,
        ),
        "timing": benchmark_timing,
    }
    prediction_timeseries_path = eval_output_dir / "processing_timeseries_prediction.jsonl"
    if prediction_timeseries_path.exists():
        prediction_stage_artifacts["processing_timeseries_prediction_jsonl"] = (
            _path_for_manifest(eval_output_dir, prediction_timeseries_path)
        )
    if predictions_out_path is not None:
        prediction_stage_artifacts["prediction_record_output_jsonl"] = _path_for_manifest(
            eval_output_dir,
            predictions_out_path,
        )
    processed_report_path = import_result.get("processed_report_path")
    if processed_report_path:
        prediction_stage_artifacts["processed_report_json"] = _path_for_manifest(
            eval_output_dir,
            processed_report_path,
        )
    processed_run_root_raw = import_result.get("processed_run_root")
    processed_run_root = (
        Path(str(processed_run_root_raw)).expanduser()
        if str(processed_run_root_raw or "").strip()
        else None
    )
    if processed_run_root is not None:
        prediction_stage_artifacts["processed_output_run_dir"] = _path_for_manifest(
            eval_output_dir,
            processed_run_root,
        )
        prediction_stage_artifacts["stage_run_dir"] = _path_for_manifest(
            eval_output_dir,
            processed_run_root,
        )

    _write_eval_run_manifest(
        run_root=eval_output_dir,
        run_kind="labelstudio_benchmark_prediction_stage",
        source_path=str(selected_source),
        source_hash=pred_context.source_hash,
        importer_name=None,
        run_config=prediction_stage_run_config,
        artifacts=prediction_stage_artifacts,
        notes=(
            "Offline benchmark prediction-stage artifacts for all-method reuse. "
            "No evaluation was run by this helper."
        ),
    )
    codexfarm_prompt_response_log_path = (
        llm_prompt_artifacts.build_codex_farm_prompt_response_log(
            pred_run=pred_run,
            eval_output_dir=eval_output_dir,
            repo_root=REPO_ROOT,
        )
    )
    return BenchmarkPredictionStageResult(
        prediction_bundle=prediction_bundle,
        prediction_records=prediction_records,
        codexfarm_prompt_response_log_path=codexfarm_prompt_response_log_path,
        single_book_split_cache_metadata=(
            dict(single_book_split_cache_metadata)
            if isinstance(single_book_split_cache_metadata, dict)
            else None
        ),
    )


_BENCHMARK_PREDICTION_RECORD_STAGE_KIND = "stage-block.v1"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _prediction_record_meta_from_bundle(
    *,
    bundle: BenchmarkPredictionBundle,
    selected_source: Path,
    workbook_slug: str | None,
) -> dict[str, Any]:
    timing_payload = bundle.import_result.get("timing")
    if not isinstance(timing_payload, dict):
        timing_payload = {}
    predict_meta: dict[str, Any] = {
        "source_file": str(selected_source),
        "source_hash": bundle.pred_context.source_hash,
        "processed_run_root": _json_safe(bundle.import_result.get("processed_run_root")),
        "processed_report_path": _json_safe(
            bundle.import_result.get("processed_report_path")
        ),
        "run_config": _json_safe(bundle.pred_context.run_config),
        "run_config_hash": bundle.pred_context.run_config_hash,
        "run_config_summary": bundle.pred_context.run_config_summary,
        "recipes": bundle.pred_context.recipes,
        "timing": _json_safe(timing_payload),
        "workbook_slug": str(workbook_slug or "").strip() or None,
    }
    # Keep JSON payload compact and stable by dropping null-valued metadata keys.
    return {
        key: value for key, value in predict_meta.items() if value is not None
    }


def _load_stage_block_prediction_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to read stage block predictions from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Stage block predictions payload at {path} is not a JSON object.")
    return payload


def _load_extracted_archive_blocks(path: Path) -> dict[int, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to read extracted archive from {path}: {exc}") from exc

    records: list[dict[str, Any]]
    if isinstance(payload, list):
        records = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        blocks_payload = payload.get("blocks")
        if isinstance(blocks_payload, list):
            records = [row for row in blocks_payload if isinstance(row, dict)]
        else:
            records = []
    else:
        records = []

    indexed: dict[int, dict[str, Any]] = {}
    for fallback_index, row in enumerate(records):
        raw_index = row.get("index")
        block_index = _coerce_int(raw_index)
        if block_index is None:
            block_index = _coerce_int(row.get("block_index"))
        if block_index is None:
            block_index = fallback_index
        location = row.get("location")
        if not isinstance(location, dict):
            location = {}
        features = location.get("features")
        if not isinstance(features, dict):
            features = {}
        indexed[int(block_index)] = {
            "text": str(row.get("text") or ""),
            "features": dict(features),
        }
    return indexed


def predict_stage(
    *,
    bundle: BenchmarkPredictionBundle,
    selected_source: Path,
) -> Iterator[PredictionRecord]:
    stage_payload = _load_stage_block_prediction_payload(bundle.stage_predictions_path)
    raw_block_labels = stage_payload.get("block_labels")
    if not isinstance(raw_block_labels, dict):
        raise ValueError(
            "Stage block predictions payload is missing block_labels map."
        )
    block_labels: dict[int, str] = {}
    for raw_index, raw_label in raw_block_labels.items():
        block_index = _coerce_int(raw_index)
        if block_index is None or block_index < 0:
            continue
        normalized_label = str(raw_label or "").strip() or "OTHER"
        block_labels[block_index] = normalized_label

    extracted_blocks = _load_extracted_archive_blocks(bundle.extracted_archive_path)
    all_indices = sorted(set(block_labels) | set(extracted_blocks))
    source_identifier = bundle.pred_context.source_hash or str(selected_source)
    workbook_slug = str(stage_payload.get("workbook_slug") or "").strip()
    predict_meta = _prediction_record_meta_from_bundle(
        bundle=bundle,
        selected_source=selected_source,
        workbook_slug=workbook_slug,
    )
    for block_index in all_indices:
        block_payload = extracted_blocks.get(block_index, {})
        prediction_payload: dict[str, Any] = {
            "schema_kind": _BENCHMARK_PREDICTION_RECORD_STAGE_KIND,
            "block_index": int(block_index),
            "pred_label": block_labels.get(block_index, "OTHER"),
            "block_text": str(block_payload.get("text") or ""),
            "block_features": dict(block_payload.get("features") or {}),
        }
        yield make_prediction_record(
            example_id=f"labelstudio-benchmark:{source_identifier}:block:{block_index}",
            example_index=int(block_index),
            prediction=prediction_payload,
            predict_meta=predict_meta,
        )


def _prediction_record_stage_row(
    record: PredictionRecord,
) -> tuple[int, str, str, dict[str, Any]] | None:
    schema_kind = str(record.prediction.get("schema_kind") or "").strip()
    if schema_kind and schema_kind != _BENCHMARK_PREDICTION_RECORD_STAGE_KIND:
        return None
    if "block_index" not in record.prediction:
        return None

    block_index = _coerce_int(record.prediction.get("block_index"))
    if block_index is None or block_index < 0:
        raise ValueError(
            f"Prediction record {record.example_id} has invalid block_index."
        )
    pred_label = str(record.prediction.get("pred_label") or "").strip() or "OTHER"
    block_text = str(record.prediction.get("block_text") or "")
    block_features_payload = record.prediction.get("block_features")
    if not isinstance(block_features_payload, dict):
        block_features_payload = {}
    return block_index, pred_label, block_text, dict(block_features_payload)


def _build_prediction_bundle_from_stage_records(
    *,
    prediction_records: list[PredictionRecord],
    replay_output_dir: Path,
    require_contiguous: bool = True,
) -> BenchmarkPredictionBundle:
    if not prediction_records:
        raise ValueError("Prediction record file is empty.")

    seen_example_ids: set[str] = set()
    seen_example_indices: set[int] = set()
    block_rows: dict[int, dict[str, Any]] = {}
    first_meta: dict[str, Any] = {}
    for record in prediction_records:
        if record.example_id in seen_example_ids:
            raise ValueError(
                f"Prediction record file contains duplicate example_id: {record.example_id}"
            )
        if record.example_index in seen_example_indices:
            raise ValueError(
                "Prediction record file contains duplicate example_index: "
                f"{record.example_index}"
            )
        seen_example_ids.add(record.example_id)
        seen_example_indices.add(record.example_index)
        stage_row = _prediction_record_stage_row(record)
        if stage_row is None:
            raise ValueError(
                "Prediction record file contains unsupported record payload. "
                "Expected per-block stage records."
            )
        block_index, pred_label, block_text, block_features = stage_row
        if int(record.example_index) != int(block_index):
            raise ValueError(
                "Prediction record example_index does not match block_index for "
                f"{record.example_id}."
            )
        if block_index in block_rows:
            raise ValueError(
                f"Prediction record file contains duplicate block_index: {block_index}"
            )
        block_rows[block_index] = {
            "pred_label": pred_label,
            "block_text": block_text,
            "block_features": block_features,
        }
        if not first_meta:
            first_meta = dict(record.predict_meta)

    if not block_rows:
        raise ValueError("Prediction record file contains no stage-block records.")

    ordered_indices = sorted(block_rows)
    expected_indices = list(ordered_indices)
    if require_contiguous:
        max_block_index = ordered_indices[-1]
        expected_indices = list(range(max_block_index + 1))
        missing_indices = [
            block_index for block_index in expected_indices if block_index not in block_rows
        ]
        if missing_indices:
            missing_preview = ",".join(str(value) for value in missing_indices[:10])
            raise ValueError(
                "Prediction record block indices are not contiguous from 0. "
                f"Missing: {missing_preview}"
            )

    source_file = str(first_meta.get("source_file") or "")
    source_hash = str(first_meta.get("source_hash") or "").strip() or "unknown"
    workbook_slug = str(first_meta.get("workbook_slug") or "").strip()
    label_blocks: dict[str, list[int]] = {}
    stage_labels: dict[str, str] = {}
    extracted_rows: list[dict[str, Any]] = []
    for block_index in expected_indices:
        row = block_rows[block_index]
        pred_label = str(row.get("pred_label") or "OTHER").strip() or "OTHER"
        stage_labels[str(block_index)] = pred_label
        label_blocks.setdefault(pred_label, []).append(block_index)
        extracted_rows.append(
            {
                "index": block_index,
                "text": str(row.get("block_text") or ""),
                "location": {
                    "features": dict(row.get("block_features") or {}),
                },
            }
        )

    replay_output_dir.mkdir(parents=True, exist_ok=True)
    stage_predictions_path = replay_output_dir / "stage_block_predictions.from_records.json"
    extracted_archive_path = replay_output_dir / "extracted_archive.from_records.json"
    stage_payload: dict[str, Any] = {
        "schema_version": "stage_block_predictions.v1",
        "source_file": source_file,
        "source_hash": source_hash,
        "workbook_slug": workbook_slug,
        "block_labels": stage_labels,
        "label_blocks": label_blocks,
        "conflicts": [],
        "notes": ["Reconstructed from per-example prediction records."],
    }
    contiguous_indices = expected_indices == list(range(len(expected_indices)))
    if contiguous_indices:
        stage_payload["block_count"] = len(expected_indices)
    stage_predictions_path.write_text(
        json.dumps(stage_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    extracted_archive_path.write_text(
        json.dumps(extracted_rows, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    pred_run = replay_output_dir
    run_config_payload = first_meta.get("run_config")
    run_config = run_config_payload if isinstance(run_config_payload, dict) else None
    timing_payload = first_meta.get("timing")
    if not isinstance(timing_payload, dict):
        timing_payload = {}
    import_result: dict[str, Any] = {
        "run_root": str(pred_run),
        "stage_block_predictions_path": str(stage_predictions_path),
        "processed_report_path": str(first_meta.get("processed_report_path") or ""),
        "processed_run_root": str(first_meta.get("processed_run_root") or ""),
        "timing": timing_payload,
    }
    prediction_phase_seconds = _report_optional_metric(
        import_result["timing"].get("prediction_seconds")
    )
    if prediction_phase_seconds is None:
        prediction_phase_seconds = _report_optional_metric(
            import_result["timing"].get("total_seconds")
        )
    if prediction_phase_seconds is None:
        prediction_phase_seconds = 0.0

    pred_context = PredRunContext(
        recipes=_coerce_int(first_meta.get("recipes")),
        processed_report_path=str(first_meta.get("processed_report_path") or ""),
        stage_block_predictions_path=str(stage_predictions_path),
        extracted_archive_path=str(extracted_archive_path),
        source_file=source_file,
        source_hash=source_hash if source_hash != "unknown" else None,
        run_config=run_config,
        run_config_hash=str(first_meta.get("run_config_hash") or "").strip() or None,
        run_config_summary=str(first_meta.get("run_config_summary") or "").strip() or None,
        tokens_input=None,
        tokens_cached_input=None,
        tokens_output=None,
        tokens_reasoning=None,
        tokens_total=None,
    )
    return BenchmarkPredictionBundle(
        import_result=import_result,
        pred_run=pred_run,
        pred_context=pred_context,
        stage_predictions_path=stage_predictions_path,
        extracted_archive_path=extracted_archive_path,
        prediction_phase_seconds=max(0.0, prediction_phase_seconds),
    )


def _build_prediction_bundle_from_records(
    *,
    predictions_in: Path,
    prediction_records: list[PredictionRecord],
    replay_output_dir: Path,
) -> BenchmarkPredictionBundle:
    if not prediction_records:
        raise ValueError(f"Prediction record file is empty: {predictions_in}")

    stage_record_candidates: list[PredictionRecord] = []
    for record in prediction_records:
        stage_row = _prediction_record_stage_row(record)
        if stage_row is not None:
            stage_record_candidates.append(record)

    if len(stage_record_candidates) != len(prediction_records):
        raise ValueError(
            "Prediction record file contains unsupported payload(s). "
            "Only per-block stage records are accepted."
        )
    return _build_prediction_bundle_from_stage_records(
        prediction_records=stage_record_candidates,
        replay_output_dir=replay_output_dir,
    )


def _prediction_record_source_file_hint(
    records: list[PredictionRecord],
) -> Path | None:
    for record in records:
        source_hint = str(record.predict_meta.get("source_file") or "").strip()
        if not source_hint:
            continue
        source_candidate = Path(source_hint)
        if source_candidate.exists() and source_candidate.is_file():
            return source_candidate
    return None


@dataclass(frozen=True)
class PipelinedPredictionResult:
    prediction_bundle: BenchmarkPredictionBundle
    prediction_records: list[PredictionRecord]
    prewarmed_canonical_paths: dict[str, Path] | None
    replay_bundle: BenchmarkPredictionBundle | None


def run_pipelined(
    *,
    run_prediction_bundle: Callable[[], BenchmarkPredictionBundle],
    prewarm_evaluation_inputs: Callable[[], dict[str, Path] | None],
    selected_source: Path,
    eval_output_dir: Path,
    queue_size: int = 64,
) -> PipelinedPredictionResult:
    record_queue: queue.Queue[PredictionRecord | object] = queue.Queue(
        maxsize=max(1, int(queue_size))
    )
    prediction_bundle_queue: queue.Queue[BenchmarkPredictionBundle] = queue.Queue(
        maxsize=1
    )
    prewarm_queue: queue.Queue[dict[str, Path] | None] = queue.Queue(maxsize=1)
    consumer_queue: queue.Queue[
        tuple[list[PredictionRecord], BenchmarkPredictionBundle | None]
    ] = queue.Queue(maxsize=1)
    error_queue: queue.Queue[BaseException] = queue.Queue(maxsize=1)
    producer_done = threading.Event()
    stop_event = threading.Event()
    end_of_stream = object()

    def _publish_error(exc: BaseException) -> None:
        if error_queue.empty():
            error_queue.put(exc)
        stop_event.set()

    def _queue_put(target_queue: queue.Queue[Any], payload: Any) -> bool:
        while True:
            if stop_event.is_set():
                return False
            try:
                target_queue.put(payload, timeout=0.1)
                return True
            except queue.Full:
                continue

    def _producer() -> None:
        try:
            prediction_bundle = run_prediction_bundle()
            if not _queue_put(prediction_bundle_queue, prediction_bundle):
                return
            for record in predict_stage(
                bundle=prediction_bundle,
                selected_source=selected_source,
            ):
                if not _queue_put(record_queue, record):
                    return
        except BaseException as exc:  # noqa: BLE001
            _publish_error(exc)
        finally:
            producer_done.set()
            _queue_put(record_queue, end_of_stream)

    def _prewarm() -> None:
        try:
            prewarmed_canonical_paths = prewarm_evaluation_inputs()
            _queue_put(prewarm_queue, prewarmed_canonical_paths)
        except BaseException as exc:  # noqa: BLE001
            _publish_error(exc)

    def _consumer() -> None:
        try:
            prediction_records: list[PredictionRecord] = []
            reached_end_of_stream = False
            while not reached_end_of_stream:
                if stop_event.is_set() and producer_done.is_set() and record_queue.empty():
                    break
                try:
                    next_item = record_queue.get(timeout=0.1)
                except queue.Empty:
                    if producer_done.is_set():
                        break
                    continue
                if next_item is end_of_stream:
                    reached_end_of_stream = True
                    continue
                if not isinstance(next_item, PredictionRecord):
                    raise RuntimeError(
                        "Benchmark prediction pipeline produced an invalid record."
                    )
                if _prediction_record_stage_row(next_item) is None:
                    raise ValueError(
                        "Pipelined benchmark received unsupported prediction record payload."
                    )
                prediction_records.append(next_item)

            replay_bundle: BenchmarkPredictionBundle | None = None
            if prediction_records:
                replay_bundle = _build_prediction_bundle_from_stage_records(
                    prediction_records=prediction_records,
                    replay_output_dir=(
                        eval_output_dir / ".prediction-record-replay" / "pipelined"
                    ),
                    require_contiguous=False,
                )
            _queue_put(consumer_queue, (prediction_records, replay_bundle))
        except BaseException as exc:  # noqa: BLE001
            _publish_error(exc)

    producer_thread = threading.Thread(
        target=_producer,
        name="benchmark-prediction-stage",
        daemon=True,
    )
    prewarm_thread = threading.Thread(
        target=_prewarm,
        name="benchmark-eval-prewarm",
        daemon=True,
    )
    consumer_thread = threading.Thread(
        target=_consumer,
        name="benchmark-eval-consumer",
        daemon=True,
    )

    producer_thread.start()
    consumer_thread.start()
    prewarm_thread.start()
    producer_thread.join()
    consumer_thread.join()
    prewarm_thread.join()

    if not error_queue.empty():
        raise error_queue.get()
    if prediction_bundle_queue.empty():
        raise RuntimeError(
            "Pipelined benchmark prediction stage produced no output."
        )
    if prewarm_queue.empty():
        raise RuntimeError("Pipelined benchmark prewarm stage produced no output.")
    if consumer_queue.empty():
        raise RuntimeError(
            "Pipelined benchmark evaluation consumer produced no output."
        )
    prediction_bundle = prediction_bundle_queue.get()
    prewarmed_canonical_paths = prewarm_queue.get()
    prediction_records, replay_bundle = consumer_queue.get()
    return PipelinedPredictionResult(
        prediction_bundle=prediction_bundle,
        prediction_records=prediction_records,
        prewarmed_canonical_paths=prewarmed_canonical_paths,
        replay_bundle=replay_bundle,
    )


def evaluate_stage(
    *,
    selected_eval_mode: str,
    selected_gold: Path,
    eval_output_dir: Path,
    stage_predictions_path: Path,
    extracted_archive_path: Path,
    alignment_cache_dir: Path | None,
    prewarmed_canonical_paths: dict[str, Path] | None,
    gold_adaptation_mode: str,
    gold_adaptation_min_coverage: float,
    gold_adaptation_max_ambiguous: int,
) -> tuple[dict[str, Any], Callable[[dict[str, Any]], str]]:
    if selected_eval_mode == BENCHMARK_EVAL_MODE_CANONICAL_TEXT:
        gold_export_root = selected_gold.parent
        eval_result_local = evaluate_canonical_text(
            gold_export_root=gold_export_root,
            stage_predictions_json=stage_predictions_path,
            extracted_blocks_json=extracted_archive_path,
            out_dir=eval_output_dir,
            alignment_cache_dir=alignment_cache_dir,
            canonical_paths=prewarmed_canonical_paths,
        )
        return eval_result_local, format_canonical_eval_report_md
    eval_result_local = evaluate_stage_blocks(
        gold_freeform_jsonl=selected_gold,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=eval_output_dir,
        gold_adaptation_mode=gold_adaptation_mode,
        gold_adaptation_min_coverage=gold_adaptation_min_coverage,
        gold_adaptation_max_ambiguous=gold_adaptation_max_ambiguous,
    )
    return eval_result_local, format_stage_block_eval_report_md


def _prune_empty_dirs(start: Path, *, stop_exclusive: Path | None = None) -> None:
    """Best-effort cleanup of empty directories after moving benchmark artifacts."""
    current = start
    while True:
        if stop_exclusive is not None and current == stop_exclusive:
            break
        try:
            current.rmdir()
        except OSError:
            break
        if current.parent == current:
            break
        current = current.parent


def _display_gold_export_path(path: Path, output_dir: Path) -> str:
    # Keep interactive gold selection readable: prefer the book folder name
    # over the full pulled-from-labelstudio relative path.
    if path.parent.name == "exports" and path.parent.parent.name:
        return path.parent.parent.name
    for root in (output_dir, DEFAULT_GOLDEN):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _display_benchmark_target_name(
    *,
    gold_display: str | None,
    source_file_name: str | None,
) -> str:
    concise_gold_display = str(gold_display or "").strip()
    if concise_gold_display:
        return concise_gold_display
    source_name = str(source_file_name or "").strip()
    if source_name:
        return Path(source_name).stem or source_name
    return "benchmark-target"


def _display_prediction_run_path(path: Path, output_dir: Path) -> str:
    for root in (output_dir, DEFAULT_GOLDEN):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _resolve_all_method_targets(
    output_dir: Path,
) -> tuple[list[AllMethodTarget], list[AllMethodUnmatchedGold]]:
    from cookimport.bench.speed_suite import (
        match_gold_exports_to_inputs,
        resolve_repo_path,
    )

    candidates = _discover_freeform_gold_exports(output_dir)
    matched_rows, unmatched_rows = match_gold_exports_to_inputs(
        candidates,
        input_root=DEFAULT_INPUT,
        gold_root=output_dir,
        importable_files=_list_importable_files(DEFAULT_INPUT),
    )

    matched_targets = [
        AllMethodTarget(
            gold_spans_path=resolve_repo_path(
                row.gold_spans_path, repo_root=REPO_ROOT
            ),
            source_file=resolve_repo_path(row.source_file, repo_root=REPO_ROOT),
            source_file_name=Path(row.source_file).name,
            gold_display=_display_gold_export_path(
                resolve_repo_path(row.gold_spans_path, repo_root=REPO_ROOT),
                output_dir,
            ),
        )
        for row in matched_rows
    ]

    unmatched_targets: list[AllMethodUnmatchedGold] = []
    for row in unmatched_rows:
        gold_spans_raw = str(row.get("gold_spans_path") or "").strip()
        if not gold_spans_raw:
            continue
        gold_spans_path = resolve_repo_path(gold_spans_raw, repo_root=REPO_ROOT)
        source_hint_raw = row.get("source_hint")
        source_hint = (
            str(source_hint_raw).strip() if source_hint_raw is not None else None
        )
        if source_hint == "":
            source_hint = None
        unmatched_targets.append(
            AllMethodUnmatchedGold(
                gold_spans_path=gold_spans_path,
                reason=str(row.get("reason") or "Unmatched gold export."),
                source_hint=source_hint,
                gold_display=str(
                    row.get("gold_display")
                    or _display_gold_export_path(gold_spans_path, output_dir)
                ),
            )
        )

    return matched_targets, unmatched_targets


def _resolve_benchmark_gold_and_source(
    *,
    gold_spans: Path | None,
    source_file: Path | None,
    output_dir: Path,
    allow_cancel: bool = False,
) -> tuple[Path, Path] | None:
    def _abort(message: str) -> tuple[Path, Path] | None:
        if allow_cancel:
            typer.secho(message, fg=typer.colors.YELLOW)
            return None
        _fail(message)
        return None

    selected_gold = gold_spans
    if selected_gold is None:
        candidates = _discover_freeform_gold_exports(output_dir)
        if not candidates:
            return _abort(
                "No freeform gold exports found. Run `cookimport labelstudio-export` first."
            )
        selected_gold = _menu_select(
            "Select a freeform gold export:",
            menu_help=(
                "Choose the labeled freeform export to benchmark against. "
                "Newest exports are listed first."
            ),
            choices=[
                questionary.Choice(
                    _display_gold_export_path(path, output_dir),
                    value=path,
                )
                for path in candidates[:30]
            ],
        )
        if selected_gold in {None, BACK_ACTION}:
            return _abort("Benchmark cancelled.")
    if isinstance(selected_gold, str):
        selected_gold = Path(selected_gold)
    if not isinstance(selected_gold, Path):
        return _abort("Benchmark cancelled.")
    if not selected_gold.exists():
        return _abort(f"Gold spans file not found: {selected_gold}")

    selected_source = source_file
    inferred_source = None
    if selected_source is None:
        inferred_source = _infer_source_file_from_freeform_gold(selected_gold)
    if selected_source is None and inferred_source is not None:
        selected_source = inferred_source
    if selected_source is None:
        importable_files = _list_importable_files(DEFAULT_INPUT)
        if importable_files:
            source_choice = _menu_select(
                "Select source file to benchmark:",
                menu_help=(
                    "Choose the source file used to generate prediction tasks "
                    "for comparison to the selected gold export."
                ),
                choices=[
                    *[questionary.Choice(path.name, value=path) for path in importable_files],
                    questionary.Choice("Enter a custom path", value="custom"),
                ],
            )
            if source_choice in {None, BACK_ACTION}:
                return _abort("Benchmark cancelled.")
            if source_choice == "custom":
                source_path = _prompt_text("Enter source file path:")
                if not source_path:
                    return _abort("Benchmark cancelled.")
                selected_source = Path(source_path)
            else:
                selected_source = source_choice
        else:
            source_path = _prompt_text("Enter source file path:")
            if not source_path:
                return _abort("Benchmark cancelled.")
            selected_source = Path(source_path)
    if not selected_source.exists() or not selected_source.is_file():
        return _abort(f"Source file not found: {selected_source}")
    try:
        _require_importer(selected_source)
    except typer.Exit:
        if allow_cancel:
            return None
        raise

    return selected_gold, selected_source


def _all_method_variant_token(value: str | bool) -> str:
    if isinstance(value, bool):
        raw_value = "true" if value else "false"
    else:
        raw_value = str(value).strip().lower()
    token = raw_value.replace("-", "_")
    token = re.sub(r"[^a-z0-9_]+", "_", token)
    token = token.strip("_")
    return token or "na"


def _all_method_is_schema_like_json_source(source_file: Path) -> bool:
    try:
        if not source_file.exists() or not source_file.is_file():
            return False
        with source_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return False

    if isinstance(payload, dict):
        recipes = payload.get("recipes")
        if isinstance(recipes, list) and recipes:
            recipe_like = 0
            for item in recipes:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("@type") or "").lower()
                if "recipe" in item_type:
                    recipe_like += 1
            if recipe_like > 0:
                return False

    return bool(collect_schemaorg_recipe_objects(payload))


def _all_method_optional_module_available(module_name: str) -> bool:
    try:
        import importlib

        importlib.import_module(module_name)
        return True
    except Exception:  # noqa: BLE001
        return False


def _build_all_method_sweep_payloads(
    *,
    base_payload: dict[str, Any],
    include_deterministic_sweeps: bool,
) -> list[tuple[str, dict[str, Any]]]:
    """Return (sweep_tag, payload) rows for all-method benchmark runs.

    Strategy: baseline + one-at-a-time sweeps + one combined "all_upgrades" payload.
    This exercises new deterministic knobs without a factorial explosion.
    """

    def _normalized(value: Any, default: str) -> str:
        cleaned = str(value if value is not None else default).strip().lower()
        return cleaned or default

    rows: list[tuple[str, dict[str, Any]]] = [("base", dict(base_payload))]
    if not include_deterministic_sweeps:
        return rows

    pysbd_ok = _all_method_optional_module_available("pysbd")
    quantulum_ok = _all_method_optional_module_available("quantulum3")
    pint_ok = _all_method_optional_module_available("pint")

    def add_one_at_a_time(
        *,
        key: str,
        values: Iterable[str],
        default: str,
        require: bool = True,
    ) -> None:
        if not require:
            return
        base_value = _normalized(base_payload.get(key), default)
        for value in values:
            normalized = _normalized(value, default)
            if normalized == base_value:
                continue
            payload = dict(base_payload)
            payload[key] = normalized
            rows.append((f"{key}={normalized}", payload))

    # Priority 2–6 deterministic knobs (non-LLM).
    add_one_at_a_time(
        key="multi_recipe_splitter",
        values=("off", "rules_v1"),
        default="rules_v1",
    )
    add_one_at_a_time(
        key="ingredient_missing_unit_policy",
        values=("null", "medium", "each"),
        default="null",
    )
    add_one_at_a_time(
        key="p6_yield_mode",
        values=("scored_v1",),
        default="scored_v1",
    )
    add_one_at_a_time(
        key="p6_time_backend",
        values=("regex_v1", "quantulum3_v1", "hybrid_regex_quantulum3_v1"),
        default="regex_v1",
        require=quantulum_ok,
    )
    add_one_at_a_time(
        key="p6_temperature_backend",
        values=("regex_v1", "quantulum3_v1", "hybrid_regex_quantulum3_v1"),
        default="regex_v1",
        require=quantulum_ok,
    )
    add_one_at_a_time(
        key="p6_temperature_unit_backend",
        values=("builtin_v1", "pint_v1"),
        default="builtin_v1",
        require=pint_ok,
    )

    upgrades: dict[str, str] = {
        "multi_recipe_splitter": "rules_v1",
        "ingredient_missing_unit_policy": "each",
        "p6_yield_mode": "scored_v1",
    }
    if quantulum_ok:
        upgrades["p6_time_backend"] = "hybrid_regex_quantulum3_v1"
        upgrades["p6_temperature_backend"] = "hybrid_regex_quantulum3_v1"
    if pint_ok:
        upgrades["p6_temperature_unit_backend"] = "pint_v1"

    combined = dict(base_payload)
    combined.update(upgrades)
    if combined != base_payload:
        rows.append(("all_upgrades", combined))

    return rows


def _build_all_method_variants(
    *,
    base_settings: RunSettings,
    source_file: Path,
    include_codex_farm: bool,
    codex_variant_settings: RunSettings | None = None,
    include_markdown_extractors: bool = False,
    include_deterministic_sweeps: bool = False,
) -> list[AllMethodVariant]:
    base_payload = _all_method_apply_baseline_contract(
        base_settings.to_run_config_dict()
    )
    variants: list[AllMethodVariant] = []
    source_ext = source_file.suffix.lower()

    webschema_source = source_ext in {".html", ".htm", ".jsonld"} or (
        source_ext == ".json" and _all_method_is_schema_like_json_source(source_file)
    )

    sweep_payloads = _build_all_method_sweep_payloads(
        base_payload=dict(base_payload),
        include_deterministic_sweeps=include_deterministic_sweeps,
    )
    dedupe_hashes: set[str] = set()

    def add_variant(
        *,
        slug: str,
        payload: dict[str, Any],
        dimensions: dict[str, Any],
        sweep_tag: str,
        apply_baseline_contract: bool = False,
    ) -> None:
        normalized_payload = (
            _all_method_apply_baseline_contract(payload)
            if apply_baseline_contract
            else dict(payload)
        )
        run_settings_payload = {
            key: value
            for key, value in normalized_payload.items()
            if key in RunSettings.model_fields
        }
        run_settings = RunSettings.from_dict(
            run_settings_payload,
            warn_context="all-method variant",
        )
        stable_hash = run_settings.stable_hash()
        if stable_hash in dedupe_hashes:
            return
        dedupe_hashes.add(stable_hash)
        if sweep_tag != "base":
            dimensions = dict(dimensions)
            dimensions["deterministic_sweep"] = sweep_tag
        variants.append(
            AllMethodVariant(
                slug=slug,
                run_settings=run_settings,
                dimensions=dimensions,
            )
        )
        if include_codex_farm:
            current_llm = str(
                normalized_payload.get("llm_recipe_pipeline") or "off"
            ).strip().lower()
            if current_llm == "off":
                if codex_variant_settings is None:
                    codex_payload = _all_method_apply_codex_contract_from_baseline(
                        normalized_payload
                    )
                    codex_slug_parts = [
                        "llm_recipe_"
                        + _all_method_variant_token(
                            RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
                        )
                    ]
                    codex_dimensions = dict(dimensions)
                    codex_dimensions["llm_recipe_pipeline"] = (
                        RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
                    )
                    codex_dimensions["line_role_pipeline"] = LINE_ROLE_PIPELINE_SHARD_V1
                    codex_dimensions["llm_knowledge_pipeline"] = (
                        KNOWLEDGE_CODEX_PIPELINE_SHARD_V1
                    )
                    codex_dimensions["atomic_block_splitter"] = str(
                        codex_payload.get("atomic_block_splitter") or "off"
                    )
                else:
                    codex_slug_parts = _all_method_codex_surface_slug_parts(
                        codex_variant_settings
                    )
                    if not codex_slug_parts:
                        return
                    codex_payload = _all_method_apply_selected_codex_contract_from_baseline(
                        normalized_payload,
                        codex_variant_settings=codex_variant_settings,
                    )
                    codex_dimensions = dict(dimensions)
                    if codex_variant_settings.llm_recipe_pipeline.value != "off":
                        codex_dimensions["llm_recipe_pipeline"] = (
                            codex_variant_settings.llm_recipe_pipeline.value
                        )
                    if (
                        codex_variant_settings.line_role_pipeline.value
                        == LINE_ROLE_PIPELINE_SHARD_V1
                    ):
                        codex_dimensions["line_role_pipeline"] = (
                            codex_variant_settings.line_role_pipeline.value
                        )
                    if codex_variant_settings.llm_knowledge_pipeline.value != "off":
                        codex_dimensions["llm_knowledge_pipeline"] = (
                            codex_variant_settings.llm_knowledge_pipeline.value
                        )
                    codex_dimensions["atomic_block_splitter"] = (
                        codex_variant_settings.atomic_block_splitter.value
                    )
                add_variant(
                    slug=f"{slug}__{'__'.join(codex_slug_parts)}",
                    payload=codex_payload,
                    dimensions=codex_dimensions,
                    sweep_tag=sweep_tag,
                    apply_baseline_contract=False,
                )

    def base_dimensions(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "multi_recipe_splitter": str(payload.get("multi_recipe_splitter", "rules_v1")),
            "ingredient_missing_unit_policy": str(payload.get("ingredient_missing_unit_policy", "null")),
            "p6_time_backend": str(payload.get("p6_time_backend", "regex_v1")),
            "p6_temperature_backend": str(payload.get("p6_temperature_backend", "regex_v1")),
            "p6_temperature_unit_backend": str(
                payload.get("p6_temperature_unit_backend", "builtin_v1")
            ),
            "p6_yield_mode": str(payload.get("p6_yield_mode", "scored_v1")),
            "pdf_ocr_policy": str(payload.get("pdf_ocr_policy", "auto")),
            "pdf_column_gap_ratio": float(payload.get("pdf_column_gap_ratio", 0.12)),
        }

    if source_ext != ".epub" and not webschema_source:
        for sweep_tag, payload in sweep_payloads:
            suffix = "" if sweep_tag == "base" else f"__det_{_all_method_variant_token(sweep_tag)}"
            multi_recipe = str(payload.get("multi_recipe_splitter") or "rules_v1").strip().lower()
            multi_recipe_suffix = (
                ""
                if multi_recipe in {"", "rules_v1"}
                else f"__multi_recipe_{_all_method_variant_token(multi_recipe)}"
            )
            add_variant(
                slug=(
                    f"source_{_all_method_variant_token(source_ext.lstrip('.') or 'unknown')}"
                    f"{multi_recipe_suffix}"
                    f"{suffix}"
                ),
                payload=payload,
                sweep_tag=sweep_tag,
                dimensions={
                    "source_extension": source_ext or "none",
                    **base_dimensions(payload),
                },
            )
        return variants

    if webschema_source:
        for sweep_tag, payload in sweep_payloads:
            suffix = "" if sweep_tag == "base" else f"__det_{_all_method_variant_token(sweep_tag)}"
            for schema_policy in ALL_METHOD_WEBSCHEMA_POLICIES:
                next_payload = dict(payload)
                next_payload["web_schema_policy"] = schema_policy
                add_variant(
                    slug=(
                        f"source_{_all_method_variant_token(source_ext.lstrip('.') or 'unknown')}"
                        f"__webschema_policy_{_all_method_variant_token(schema_policy)}"
                        f"{suffix}"
                    ),
                    payload=next_payload,
                    sweep_tag=sweep_tag,
                    dimensions={
                        "source_extension": source_ext or "none",
                        "web_schema_policy": schema_policy,
                        **base_dimensions(next_payload),
                    },
                )
        return variants

    extractors = ALL_METHOD_EPUB_EXTRACTORS_DEFAULT
    if include_markdown_extractors:
        extractors = (
            *ALL_METHOD_EPUB_EXTRACTORS_DEFAULT,
            *ALL_METHOD_EPUB_EXTRACTORS_MARKDOWN_OPTIONAL,
        )

    for sweep_tag, payload in sweep_payloads:
        suffix = "" if sweep_tag == "base" else f"__det_{_all_method_variant_token(sweep_tag)}"
        for extractor in extractors:
            if extractor == "unstructured":
                for parser_version, skip_headers_footers, preprocess_mode in product(
                    ALL_METHOD_UNSTRUCTURED_HTML_PARSER_VERSIONS,
                    ALL_METHOD_UNSTRUCTURED_SKIP_HEADERS_FOOTERS,
                    ALL_METHOD_UNSTRUCTURED_PREPROCESS_MODES,
                ):
                    next_payload = dict(payload)
                    next_payload.update(
                        {
                            "epub_extractor": extractor,
                            "epub_unstructured_html_parser_version": parser_version,
                            "epub_unstructured_skip_headers_footers": skip_headers_footers,
                            "epub_unstructured_preprocess_mode": preprocess_mode,
                        }
                    )
                    add_variant(
                        slug=(
                            f"extractor_{_all_method_variant_token(extractor)}"
                            f"__parser_{_all_method_variant_token(parser_version)}"
                            f"__skiphf_{_all_method_variant_token(skip_headers_footers)}"
                            f"__pre_{_all_method_variant_token(preprocess_mode)}"
                            f"{suffix}"
                        ),
                        payload=next_payload,
                        sweep_tag=sweep_tag,
                        dimensions={
                            "epub_extractor": extractor,
                            "epub_unstructured_html_parser_version": parser_version,
                            "epub_unstructured_skip_headers_footers": skip_headers_footers,
                            "epub_unstructured_preprocess_mode": preprocess_mode,
                            **base_dimensions(next_payload),
                        },
                    )
                continue

            next_payload = dict(payload)
            next_payload["epub_extractor"] = extractor
            add_variant(
                slug=f"extractor_{_all_method_variant_token(extractor)}{suffix}",
                payload=next_payload,
                sweep_tag=sweep_tag,
                dimensions={
                    "epub_extractor": extractor,
                    **base_dimensions(next_payload),
                },
            )

    return variants


def _build_all_method_target_variants(
    *,
    targets: list[AllMethodTarget],
    base_settings: RunSettings,
    include_codex_farm: bool,
    codex_variant_settings: RunSettings | None = None,
    include_markdown_extractors: bool = False,
    include_deterministic_sweeps: bool = False,
) -> list[tuple[AllMethodTarget, list[AllMethodVariant]]]:
    return [
        (
            target,
            _build_all_method_variants(
                base_settings=base_settings,
                source_file=target.source_file,
                include_codex_farm=include_codex_farm,
                codex_variant_settings=codex_variant_settings,
                include_markdown_extractors=include_markdown_extractors,
                include_deterministic_sweeps=include_deterministic_sweeps,
            ),
        )
        for target in targets
    ]


def _resolve_all_method_codex_choice(include_codex_farm: bool) -> tuple[bool, str | None]:
    if not include_codex_farm:
        return False, None
    return True, None


def _normalize_compare_control_path_prefix(value: str | Path | None) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if text == "/":
        return text
    return text.rstrip("/")


def _qualitysuite_compare_control_prefixes_for_path(path: Path) -> list[str]:
    candidate = Path(path).expanduser()
    try:
        candidate = candidate.resolve()
    except OSError:
        candidate = candidate

    prefixes: list[str] = []
    seen: set[str] = set()

    def _add(raw_value: str | Path | None) -> None:
        normalized = _normalize_compare_control_path_prefix(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        prefixes.append(normalized)

    _add(candidate)
    try:
        _add(candidate.relative_to(REPO_ROOT))
    except ValueError:
        pass
    return prefixes


def _qualitysuite_compare_control_filters_for_prefixes(
    prefixes: list[str],
) -> dict[str, Any]:
    clauses = [
        {"operator": "starts_with", "value": value}
        for value in prefixes
        if str(value or "").strip()
    ]
    filters: dict[str, Any] = {
        "quick_filters": {
            "official_full_golden_only": False,
            "exclude_ai_tests": False,
        },
    }
    if clauses:
        filters["column_filter_global_mode"] = "and"
        filters["column_filters"] = {
            "artifact_dir": {
                "mode": "or",
                "clauses": clauses,
            }
        }
    return filters


def _write_qualitysuite_agent_bridge_readme(
    *,
    bundle_dir: Path,
    index_file: Path,
    requests_file: Path,
    output_root: Path,
    golden_root: Path,
    scope_count: int,
    request_count: int,
) -> None:
    output_root_quoted = shlex.quote(str(output_root))
    golden_root_quoted = shlex.quote(str(golden_root))
    requests_file_quoted = shlex.quote(requests_file.name)
    lines = [
        "# Agent Compare-Control Bridge",
        "",
        "This folder links QualitySuite outputs to Compare & Control insights for AI-agent loops.",
        "",
        f"- Index: `{index_file.name}`",
        f"- Ready requests (JSONL): `{requests_file.name}`",
        f"- Scopes: `{scope_count}`",
        f"- Prepared agent requests: `{request_count}`",
        "",
        "Recommended agent flow:",
        "1. Read `qualitysuite_compare_control_index.json` and pick one scope/outcome insight file.",
        "2. If you need deeper drill-down, run the prepared JSONL requests through `compare-control agent`.",
        "3. Map responses back using each request `meta` payload (`scope_id`, `outcome_field`, `label`).",
        "",
    ]
    if request_count > 0:
        lines.extend(
            [
                "Run the prepared requests:",
                "```bash",
                (
                    "cookimport compare-control agent "
                    f"--output-root {output_root_quoted} "
                    f"--golden-root {golden_root_quoted} \\"
                ),
                f"  < {requests_file_quoted} > agent_responses.jsonl",
                "```",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No follow-up requests were generated. You can still run direct insights manually:",
                "```bash",
                (
                    "cookimport compare-control run --action insights "
                    f"--output-root {output_root_quoted} "
                    f"--golden-root {golden_root_quoted} "
                    "--outcome-field strict_accuracy"
                ),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            (
                "Tip: Requests include `meta` tags (`scope_id`, `outcome_field`, `label`) "
                "so agents can route responses back to the right QualitySuite scope."
            ),
            "",
        ]
    )
    (bundle_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_qualitysuite_agent_bridge_bundle(
    *,
    bundle_dir: Path,
    bundle_type: str,
    scopes: list[dict[str, Any]],
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
    extra_index: dict[str, Any] | None = None,
) -> tuple[Path | None, str | None]:
    from cookimport.analytics import compare_control_engine as engine

    try:
        records = engine.load_dashboard_records(
            output_root=output_root,
            golden_root=golden_root,
            since_days=since_days,
            scan_reports=False,
            scan_benchmark_reports=False,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"Unable to load compare-control records: {exc}"

    bundle_dir.mkdir(parents=True, exist_ok=True)
    index_payload: dict[str, Any] = {
        "schema_version": QUALITYSUITE_AGENT_BRIDGE_SCHEMA_VERSION,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
        "bundle_type": bundle_type,
        "output_root": str(output_root),
        "golden_root": str(golden_root),
        "since_days": since_days,
        "records_loaded": len(records),
        "outcome_fields": list(QUALITYSUITE_AGENT_BRIDGE_OUTCOME_FIELDS),
        "scopes": [],
    }
    if isinstance(extra_index, dict) and extra_index:
        index_payload.update(extra_index)

    request_rows: list[dict[str, Any]] = []

    for scope in scopes:
        scope_id = str(scope.get("scope_id") or "").strip()
        scope_label = str(scope.get("scope_label") or scope_id).strip() or scope_id
        if not scope_id:
            continue
        prefixes = [
            _normalize_compare_control_path_prefix(value)
            for value in (scope.get("path_prefixes") or [])
        ]
        prefixes = [value for value in prefixes if value]
        scope_entry: dict[str, Any] = {
            "scope_id": scope_id,
            "scope_label": scope_label,
            "path_prefixes": prefixes,
            "insights": [],
        }
        if isinstance(scope.get("metadata"), dict):
            scope_entry["metadata"] = dict(scope["metadata"])

        for outcome_field in QUALITYSUITE_AGENT_BRIDGE_OUTCOME_FIELDS:
            query = {
                "outcome_field": outcome_field,
                "filters": _qualitysuite_compare_control_filters_for_prefixes(prefixes),
            }
            file_name = f"{scope_id}__{outcome_field}.json"
            insight_path = bundle_dir / file_name
            try:
                insight_payload = engine.generate_insights(records, query)
                wrapped = engine.success_payload(insight_payload)
                insight_path.write_text(
                    json.dumps(wrapped, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

                candidate_rows = int(insight_payload.get("candidate_rows") or 0)
                compare_field = str(insight_payload.get("compare_field") or "")
                highlights = insight_payload.get("highlights")
                highlight_count = len(highlights) if isinstance(highlights, list) else 0
                scope_entry["insights"].append(
                    {
                        "outcome_field": outcome_field,
                        "file": file_name,
                        "candidate_rows": candidate_rows,
                        "compare_field": compare_field,
                        "highlight_count": highlight_count,
                    }
                )

                suggested_queries = insight_payload.get("suggested_queries")
                if isinstance(suggested_queries, list):
                    for query_index, item in enumerate(suggested_queries, start=1):
                        if not isinstance(item, dict):
                            continue
                        action = str(item.get("action") or "").strip().lower()
                        payload = item.get("payload")
                        if not action or not isinstance(payload, dict):
                            continue
                        request_rows.append(
                            {
                                "id": f"{scope_id}-{outcome_field}-{query_index}",
                                "action": action,
                                "payload": payload,
                                "meta": {
                                    "scope_id": scope_id,
                                    "outcome_field": outcome_field,
                                    "label": str(item.get("label") or "").strip(),
                                },
                            }
                        )
            except Exception as exc:  # noqa: BLE001
                error_payload = engine.error_payload(
                    "qualitysuite_agent_bridge_insight_failed",
                    "Unable to generate insights for scope/outcome.",
                    {
                        "scope_id": scope_id,
                        "outcome_field": outcome_field,
                        "error": str(exc),
                    },
                )
                insight_path.write_text(
                    json.dumps(error_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                scope_entry["insights"].append(
                    {
                        "outcome_field": outcome_field,
                        "file": file_name,
                        "error": str(exc),
                    }
                )

        index_payload["scopes"].append(scope_entry)

    requests_file = bundle_dir / "agent_requests.jsonl"
    if request_rows:
        requests_file.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in request_rows) + "\n",
            encoding="utf-8",
        )
    else:
        requests_file.write_text("", encoding="utf-8")
    index_payload["agent_request_count"] = len(request_rows)
    index_payload["agent_requests_jsonl"] = requests_file.name
    index_file_name = "qualitysuite_compare_control_index.json"
    index_payload["agent_handoff"] = {
        "recommended_entrypoint": index_file_name,
        "recommended_flow": [
            "read_index",
            "inspect_scope_insights",
            "run_agent_requests_jsonl",
        ],
    }

    index_file = bundle_dir / index_file_name
    index_file.write_text(
        json.dumps(index_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_qualitysuite_agent_bridge_readme(
        bundle_dir=bundle_dir,
        index_file=index_file,
        requests_file=requests_file,
        output_root=output_root,
        golden_root=golden_root,
        scope_count=len(index_payload["scopes"]),
        request_count=len(request_rows),
    )
    return bundle_dir, None


def _write_qualitysuite_agent_bridge_bundle_for_run(
    *,
    run_root: Path,
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
) -> tuple[Path | None, str | None]:
    summary_payload: dict[str, Any] = {}
    summary_path = run_root / "summary.json"
    if summary_path.exists():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary_payload = loaded
        except Exception:
            summary_payload = {}

    scopes: list[dict[str, Any]] = [
        {
            "scope_id": "run_overall",
            "scope_label": "Quality run overall",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(run_root),
            "metadata": {
                "run_root": str(run_root),
            },
        }
    ]
    experiments = summary_payload.get("experiments")
    if isinstance(experiments, list):
        for row in experiments:
            if not isinstance(row, dict):
                continue
            experiment_id = str(row.get("id") or "").strip()
            if not experiment_id:
                continue
            experiment_root = run_root / "experiments" / experiment_id
            target_path = experiment_root if experiment_root.exists() else run_root
            scopes.append(
                {
                    "scope_id": f"experiment_{experiment_id}",
                    "scope_label": f"Experiment {experiment_id}",
                    "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                        target_path
                    ),
                    "metadata": {
                        "experiment_id": experiment_id,
                        "status": str(row.get("status") or ""),
                        "run_settings_hash": str(row.get("run_settings_hash") or ""),
                    },
                }
            )

    return _write_qualitysuite_agent_bridge_bundle(
        bundle_dir=run_root / QUALITYSUITE_AGENT_BRIDGE_DIR_NAME,
        bundle_type="quality_run",
        scopes=scopes,
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        extra_index={
            "quality_run_dir": str(run_root),
            "quality_summary_path": str(summary_path),
        },
    )


def _resolve_quality_compare_scope_path(run_dir: Path, experiment_id: str) -> Path:
    experiment_clean = str(experiment_id or "").strip()
    if not experiment_clean:
        return run_dir
    experiment_root = run_dir / "experiments" / experiment_clean
    if experiment_root.exists() and experiment_root.is_dir():
        return experiment_root
    return run_dir


def _write_qualitysuite_agent_bridge_bundle_for_compare(
    *,
    comparison_root: Path,
    comparison_payload: dict[str, Any],
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
) -> tuple[Path | None, str | None]:
    baseline_run_dir = Path(
        str(comparison_payload.get("baseline_run_dir") or "").strip()
    ).expanduser()
    candidate_run_dir = Path(
        str(comparison_payload.get("candidate_run_dir") or "").strip()
    ).expanduser()
    baseline_experiment_id = str(
        comparison_payload.get("baseline_experiment_id") or ""
    ).strip()
    candidate_experiment_id = str(
        comparison_payload.get("candidate_experiment_id") or ""
    ).strip()

    baseline_scope_path = _resolve_quality_compare_scope_path(
        baseline_run_dir,
        baseline_experiment_id,
    )
    candidate_scope_path = _resolve_quality_compare_scope_path(
        candidate_run_dir,
        candidate_experiment_id,
    )

    scopes: list[dict[str, Any]] = [
        {
            "scope_id": "baseline",
            "scope_label": f"Baseline ({baseline_experiment_id or 'auto'})",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                baseline_scope_path
            ),
            "metadata": {
                "run_dir": str(baseline_run_dir),
                "experiment_id": baseline_experiment_id,
            },
        },
        {
            "scope_id": "candidate",
            "scope_label": f"Candidate ({candidate_experiment_id or 'auto'})",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                candidate_scope_path
            ),
            "metadata": {
                "run_dir": str(candidate_run_dir),
                "experiment_id": candidate_experiment_id,
            },
        },
    ]

    return _write_qualitysuite_agent_bridge_bundle(
        bundle_dir=comparison_root / QUALITYSUITE_AGENT_BRIDGE_DIR_NAME,
        bundle_type="quality_compare",
        scopes=scopes,
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        extra_index={
            "comparison_root": str(comparison_root),
            "comparison_verdict": str(
                (comparison_payload.get("overall") or {}).get("verdict") or ""
            ).upper(),
            "baseline_run_dir": str(baseline_run_dir),
            "candidate_run_dir": str(candidate_run_dir),
            "baseline_experiment_id": baseline_experiment_id,
            "candidate_experiment_id": candidate_experiment_id,
        },
    )


def _resolve_qualitysuite_codex_farm_confirmation(
    *,
    include_codex_farm: bool,
    confirmation: str | None,
) -> bool:
    decision = resolve_codex_command_decision(
        "bench_quality_run",
        {},
        include_codex_farm_requested=include_codex_farm,
        explicit_confirmation_granted=(
            str(confirmation or "").strip() == QUALITY_RUN_CODEX_FARM_CONFIRMATION_TOKEN
        ),
    )
    if decision.allowed:
        return decision.explicit_activation_granted
    _fail(
        "bench quality-run with --include-codex-farm requires explicit positive user "
        "confirmation. Re-run with "
        f"--qualitysuite-codex-farm-confirmation "
        f"{QUALITY_RUN_CODEX_FARM_CONFIRMATION_TOKEN} "
        "only after the user has explicitly approved Codex Farm usage."
    )
    return False


def _resolve_speedsuite_codex_farm_confirmation(
    *,
    include_codex_farm: bool,
    confirmation: str | None,
) -> bool:
    decision = resolve_codex_command_decision(
        "bench_speed_run",
        {},
        include_codex_farm_requested=include_codex_farm,
        explicit_confirmation_granted=(
            str(confirmation or "").strip() == SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN
        ),
    )
    if decision.allowed:
        return decision.explicit_activation_granted
    _fail(
        "bench speed-run with --include-codex-farm requires explicit positive user "
        "confirmation. Re-run with "
        f"--speedsuite-codex-farm-confirmation "
        f"{SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN} "
        "only after the user has explicitly approved Codex Farm usage."
    )
    return False


def _print_codex_decision(decision: Any) -> None:
    if bool(_BENCHMARK_SUPPRESS_SUMMARY.get()):
        return
    summary = (
        format_codex_execution_policy_summary(decision)
        if hasattr(decision, "requested_mode")
        else format_codex_command_summary(decision)
    )
    surface = getattr(decision, "surface", None)
    codex_requested = bool(getattr(decision, "codex_requested", False))
    color = (
        typer.colors.CYAN
        if (
            surface is not None
            and (
                bool(getattr(surface, "any_codex_enabled", False))
                or codex_requested
            )
        )
        else typer.colors.BRIGHT_BLACK
    )
    typer.secho(summary, fg=color)


def _resolve_all_method_markdown_extractors_choice() -> bool:
    requested = os.getenv(ALL_METHOD_INCLUDE_MARKDOWN_EXTRACTORS_ENV, "").strip() == "1"
    return requested and markdown_epub_extractors_enabled()


def _report_metric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _report_optional_metric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median_metric(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _row_dimension_str(
    row: dict[str, Any],
    key: str,
) -> str | None:
    dimensions = row.get("dimensions")
    if not isinstance(dimensions, dict):
        return None
    value = dimensions.get(key)
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_timing_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key in (
        "total_seconds",
        "prediction_seconds",
        "evaluation_seconds",
        "artifact_write_seconds",
        "history_append_seconds",
        "parsing_seconds",
        "writing_seconds",
        "ocr_seconds",
    ):
        numeric = _report_optional_metric(payload.get(key))
        if numeric is None:
            continue
        normalized[key] = max(0.0, numeric)
    checkpoints: dict[str, float] = {}
    raw_checkpoints = payload.get("checkpoints")
    if isinstance(raw_checkpoints, dict):
        for raw_key, raw_value in raw_checkpoints.items():
            numeric = _report_optional_metric(raw_value)
            if numeric is None:
                continue
            checkpoints[str(raw_key)] = max(0.0, numeric)
    normalized["checkpoints"] = checkpoints
    return normalized


def _timing_with_updates(
    base: Any,
    *,
    checkpoints: dict[str, float] | None = None,
    **updates: float | None,
) -> dict[str, Any]:
    normalized = _normalize_timing_payload(base)
    normalized_checkpoints = normalized.get("checkpoints")
    if not isinstance(normalized_checkpoints, dict):
        normalized_checkpoints = {}
    if checkpoints:
        for key, value in checkpoints.items():
            numeric = _report_optional_metric(value)
            if numeric is None:
                continue
            normalized_checkpoints[str(key)] = max(0.0, numeric)
    normalized["checkpoints"] = normalized_checkpoints
    for key, value in updates.items():
        numeric = _report_optional_metric(value)
        if numeric is None:
            continue
        normalized[key] = max(0.0, numeric)
    return normalized


def _evaluation_telemetry_load_seconds(
    evaluation_telemetry: Any,
) -> tuple[float | None, float | None]:
    if not isinstance(evaluation_telemetry, dict):
        return None, None
    subphases = evaluation_telemetry.get("subphases")
    if not isinstance(subphases, dict):
        return None, None
    prediction_load = _report_optional_metric(subphases.get("load_prediction_seconds"))
    gold_load = _report_optional_metric(subphases.get("load_gold_seconds"))
    return prediction_load, gold_load


def _evaluation_telemetry_checkpoints(
    evaluation_telemetry: Any,
) -> dict[str, float]:
    checkpoints: dict[str, float] = {}
    if not isinstance(evaluation_telemetry, dict):
        return checkpoints

    total_seconds = _report_optional_metric(evaluation_telemetry.get("total_seconds"))
    if total_seconds is not None:
        checkpoints["evaluate_total_seconds"] = max(0.0, total_seconds)

    def _collect_block(block_key: str, prefix: str) -> None:
        raw_block = evaluation_telemetry.get(block_key)
        if not isinstance(raw_block, dict):
            return
        for raw_key, raw_value in raw_block.items():
            numeric = _report_optional_metric(raw_value)
            if numeric is None:
                continue
            key_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", str(raw_key).strip()).strip("_")
            if not key_suffix:
                continue
            checkpoint_key = f"{prefix}_{key_suffix}".lower()
            checkpoints[checkpoint_key] = max(0.0, numeric)

    _collect_block("subphases", "evaluate")
    _collect_block("resources", "evaluate_resource")
    _collect_block("work_units", "evaluate_work")
    return checkpoints


def _benchmark_eval_profile_min_seconds() -> float | None:
    raw_value = str(os.getenv(BENCHMARK_EVAL_PROFILE_MIN_SECONDS_ENV) or "").strip()
    if not raw_value:
        return None
    try:
        parsed = float(raw_value)
    except ValueError:
        logger.warning(
            "Ignoring invalid %s=%r (expected float seconds).",
            BENCHMARK_EVAL_PROFILE_MIN_SECONDS_ENV,
            raw_value,
        )
        return None
    if parsed <= 0.0:
        return None
    return parsed


def _benchmark_eval_profile_top_n() -> int:
    raw_value = str(os.getenv(BENCHMARK_EVAL_PROFILE_TOP_N_ENV) or "").strip()
    if not raw_value:
        return 60
    try:
        parsed = int(raw_value)
    except ValueError:
        logger.warning(
            "Ignoring invalid %s=%r (expected positive integer).",
            BENCHMARK_EVAL_PROFILE_TOP_N_ENV,
            raw_value,
        )
        return 60
    return max(1, parsed)


def _report_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _system_total_memory_bytes() -> int | None:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        page_size = 0
        page_count = 0
    total = page_size * page_count
    if total > 0:
        return total

    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            for line in meminfo_path.read_text(encoding="utf-8").splitlines():
                if not line.startswith("MemTotal:"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                kib = int(parts[1])
                if kib > 0:
                    return kib * 1024
        except (OSError, ValueError):
            return None
    return None


def _resolve_all_method_split_worker_cap(
    *,
    split_phase_slots: int,
    source_parallelism_effective: int | None = None,
) -> tuple[int, dict[str, Any]]:
    slots = max(1, _report_count(split_phase_slots))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1

    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    split_worker_cap_by_cpu = max(1, cpu_budget_per_source // slots)

    memory_total_bytes = _system_total_memory_bytes()
    split_worker_cap_by_memory: int | None = None
    memory_budget_per_source_bytes: int | None = None
    if memory_total_bytes is not None and memory_total_bytes > 0:
        reserve_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES,
            int(memory_total_bytes * ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO),
        )
        usable_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            memory_total_bytes - reserve_bytes,
        )
        memory_budget_per_source_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            usable_bytes // source_parallelism,
        )
        workers_by_memory_per_source = max(
            1,
            memory_budget_per_source_bytes
            // ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
        )
        split_worker_cap_by_memory = max(1, workers_by_memory_per_source // slots)

    split_worker_cap = split_worker_cap_by_cpu
    if split_worker_cap_by_memory is not None:
        split_worker_cap = min(split_worker_cap, split_worker_cap_by_memory)

    return split_worker_cap, {
        "cpu_total": cpu_total,
        "cpu_budget_per_source": cpu_budget_per_source,
        "memory_total_bytes": memory_total_bytes,
        "memory_budget_per_source_bytes": memory_budget_per_source_bytes,
        "split_worker_cap_by_cpu": split_worker_cap_by_cpu,
        "split_worker_cap_by_memory": split_worker_cap_by_memory,
        "split_worker_cap_per_config": split_worker_cap,
    }


def _resolve_all_method_split_phase_slot_cap(
    *,
    requested_split_slots: int,
    source_parallelism_effective: int | None = None,
) -> tuple[int, dict[str, Any]]:
    requested = max(1, _report_count(requested_split_slots))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1

    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    slot_cap_by_cpu = max(1, cpu_budget_per_source)

    memory_total_bytes = _system_total_memory_bytes()
    slot_cap_by_memory: int | None = None
    memory_budget_per_source_bytes: int | None = None
    if memory_total_bytes is not None and memory_total_bytes > 0:
        reserve_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES,
            int(memory_total_bytes * ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO),
        )
        usable_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            memory_total_bytes - reserve_bytes,
        )
        memory_budget_per_source_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            usable_bytes // source_parallelism,
        )
        slot_cap_by_memory = max(
            1,
            memory_budget_per_source_bytes
            // ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
        )

    effective_slots = min(requested, slot_cap_by_cpu)
    if slot_cap_by_memory is not None:
        effective_slots = min(effective_slots, slot_cap_by_memory)
    effective_slots = max(1, effective_slots)
    cap_mode = "resource_guard" if effective_slots < requested else "configured"

    return effective_slots, {
        "requested_split_phase_slots": requested,
        "effective_split_phase_slots": effective_slots,
        "split_phase_slot_mode": cap_mode,
        "split_phase_slot_cap_by_cpu": slot_cap_by_cpu,
        "split_phase_slot_cap_by_memory": slot_cap_by_memory,
        "cpu_total": cpu_total,
        "cpu_budget_per_source": cpu_budget_per_source,
        "memory_total_bytes": memory_total_bytes,
        "memory_budget_per_source_bytes": memory_budget_per_source_bytes,
    }


def _resolve_all_method_scheduler_admission(
    *,
    counts: dict[str, int],
    pending_count: int,
    total_variants: int,
    configured_inflight_pipelines: int,
    split_phase_slots: int,
    wing_backlog_target: int,
    max_active_during_eval: int,
    adaptive_overcommit_limit: int,
    adaptive_max_guard_target: int,
    smart_scheduler_enabled: bool,
    cpu_utilization_pct: float | None = None,
) -> _AllMethodSchedulerAdmissionDecision:
    total = max(1, _report_count(total_variants))
    split_slots = max(1, _report_count(split_phase_slots))
    configured_inflight = max(1, min(total, _report_count(configured_inflight_pipelines)))
    wing_target_base = max(1, _report_count(wing_backlog_target))
    max_active_eval = max(configured_inflight, min(total, _report_count(max_active_during_eval)))
    overcommit_cap = max(0, _report_count(adaptive_overcommit_limit))
    guard_cap = max(
        split_slots + wing_target_base,
        min(total, _report_count(adaptive_max_guard_target)),
    )
    guard_base = min(total, split_slots + wing_target_base)
    pending = max(0, _report_count(pending_count))
    evaluate_active = max(0, _report_count(counts.get("evaluate_active")))
    split_wait = max(0, _report_count(counts.get("split_wait")))
    heavy_active = max(0, _report_count(counts.get("heavy_active")))
    prep_active = max(0, _report_count(counts.get("prep_active")))
    wing_backlog = max(0, _report_count(counts.get("wing_backlog")))
    eval_tail_open = evaluate_active > 0 and pending > 0
    cpu_hot = (
        cpu_utilization_pct is not None
        and float(cpu_utilization_pct) >= ALL_METHOD_ADAPTIVE_CPU_HOT_PCT
    )

    active_cap = max_active_eval if eval_tail_open and smart_scheduler_enabled else configured_inflight
    guard_target = guard_base
    wing_target = wing_target_base
    reason = "base"
    pressure_boost = 0
    saturation_clamp = False
    cpu_hot_clamp = False

    if not smart_scheduler_enabled:
        return _AllMethodSchedulerAdmissionDecision(
            active_cap=max(1, min(total, active_cap)),
            guard_target=max(1, min(total, guard_target)),
            wing_target=max(1, min(total, wing_target)),
            reason=reason,
            pressure_boost=pressure_boost,
            saturation_clamp=saturation_clamp,
            cpu_hot_clamp=cpu_hot_clamp,
        )

    heavy_gap = max(0, split_slots - heavy_active)
    backlog_starved = pending > 0 and (
        heavy_gap > 0 or (split_wait == 0 and prep_active < split_slots)
    )
    if backlog_starved and not cpu_hot:
        available_overcommit = 0
        if eval_tail_open:
            available_overcommit = max(
                0,
                min(overcommit_cap, max_active_eval - active_cap),
            )
        pressure_boost = min(available_overcommit, max(1, heavy_gap))
        if pressure_boost > 0:
            active_cap += pressure_boost
        wing_boost = max(1, heavy_gap)
        wing_target = min(total, wing_target_base + wing_boost)
        guard_target = min(
            guard_cap,
            split_slots + wing_target + pressure_boost,
        )
        reason = "pressure_boost"

    saturated_backlog_threshold = max(
        wing_target_base + split_slots,
        wing_target_base * ALL_METHOD_ADAPTIVE_SATURATION_BACKLOG_MULTIPLIER,
    )
    if wing_backlog >= saturated_backlog_threshold and heavy_active >= split_slots:
        saturation_clamp = True
        wing_target = wing_target_base
        guard_target = guard_base
        active_cap = min(active_cap, max_active_eval if eval_tail_open else configured_inflight)
        reason = "saturation_clamp"

    if cpu_hot and active_cap > configured_inflight:
        cpu_hot_clamp = True
        active_cap = max(configured_inflight, active_cap - 1)
        reason = "cpu_hot_clamp"

    return _AllMethodSchedulerAdmissionDecision(
        active_cap=max(1, min(total, active_cap)),
        guard_target=max(1, min(total, guard_target)),
        wing_target=max(1, min(total, wing_target)),
        reason=reason,
        pressure_boost=max(0, pressure_boost),
        saturation_clamp=saturation_clamp,
        cpu_hot_clamp=cpu_hot_clamp,
    )


def _resolve_all_method_source_parallelism(
    *,
    total_sources: int,
    requested: int | None = None,
) -> int:
    total = max(1, _report_count(total_sources))
    default_parallel_sources = min(
        _all_method_default_parallel_sources_from_cpu(),
        total,
    )
    requested_parallel_sources = _report_count(requested)
    if requested_parallel_sources <= 0:
        return default_parallel_sources
    cpu_cap = max(1, _report_count(os.cpu_count()))
    return max(1, min(requested_parallel_sources, total, cpu_cap))


def _probe_all_method_process_pool_executor() -> tuple[bool, str | None]:
    """Return whether process-based config workers are usable in this runtime."""
    try:
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(int, 1)
            future.result(timeout=5)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip()
        if detail:
            return False, f"{type(exc).__name__}: {detail}"
        return False, type(exc).__name__
    return True, None


def _probe_all_method_process_worker_picklable() -> tuple[bool, str | None]:
    """Ensure the benchmark config worker can be pickled when process pooling is active."""
    try:
        pickle.dumps(_run_all_method_prediction_once)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip()
        if detail:
            return False, f"{type(exc).__name__}: {detail}"
        return False, type(exc).__name__
    return True, None


def _resolve_all_method_scheduler_limits(
    *,
    total_variants: int,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
) -> tuple[int, int]:
    total = max(1, _report_count(total_variants))

    inflight_default = min(ALL_METHOD_MAX_INFLIGHT_DEFAULT, total)
    if max_inflight_pipelines is None:
        inflight = inflight_default
    else:
        requested_inflight = _report_count(max_inflight_pipelines)
        if requested_inflight <= 0:
            inflight = inflight_default
        else:
            inflight = max(1, min(requested_inflight, total))

    split_default = min(ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT, inflight)
    if max_concurrent_split_phases is None:
        split_slots = split_default
    else:
        requested_split_slots = _report_count(max_concurrent_split_phases)
        if requested_split_slots <= 0:
            split_slots = split_default
        else:
            split_slots = max(1, min(requested_split_slots, inflight))

    return inflight, split_slots


@dataclass(frozen=True)
class _AllMethodSchedulerRuntime:
    configured_inflight_pipelines: int
    split_phase_slots_requested: int
    split_phase_slots: int
    split_phase_slot_mode: str
    split_phase_slot_cap_by_cpu: int
    split_phase_slot_cap_by_memory: int | None
    wing_backlog_target: int
    eval_tail_headroom_configured: int
    eval_tail_headroom_effective: int
    eval_tail_headroom_mode: str
    smart_scheduler_enabled: bool
    max_active_during_eval: int
    effective_inflight_pipelines: int
    adaptive_overcommit_limit: int
    adaptive_max_guard_target: int
    source_parallelism_effective: int
    cpu_budget_per_source: int
    cpu_budget_total: int


@dataclass(frozen=True)
class _AllMethodSchedulerAdmissionDecision:
    active_cap: int
    guard_target: int
    wing_target: int
    reason: str
    pressure_boost: int
    saturation_clamp: bool
    cpu_hot_clamp: bool


def _resolve_all_method_config_timeout_seconds(
    config_timeout_seconds: int | None,
) -> int | None:
    if config_timeout_seconds is None:
        return ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT
    parsed = _coerce_non_negative_int(config_timeout_seconds)
    if parsed is None:
        return ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT
    if parsed == 0:
        return None
    return parsed


def _resolve_all_method_retry_failed_configs(retry_failed_configs: int | None) -> int:
    if retry_failed_configs is None:
        return ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT
    parsed = _coerce_non_negative_int(retry_failed_configs)
    if parsed is None:
        return ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT
    return parsed


def _resolve_all_method_scheduler_runtime(
    *,
    total_variants: int,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool | None = None,
    source_parallelism_effective: int | None = None,
) -> _AllMethodSchedulerRuntime:
    inflight, split_slots_requested = _resolve_all_method_scheduler_limits(
        total_variants=total_variants,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
    )
    total = max(1, _report_count(total_variants))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1
    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    split_slots, split_slot_guard = _resolve_all_method_split_phase_slot_cap(
        requested_split_slots=split_slots_requested,
        source_parallelism_effective=source_parallelism,
    )
    wing_default = max(1, split_slots)
    wing_target_requested = _report_count(wing_backlog_target)
    wing_target = wing_target_requested if wing_target_requested > 0 else wing_default
    wing_target = max(1, min(total, wing_target))

    eval_tail_requested = _report_count(max_eval_tail_pipelines)
    eval_tail_mode = "configured" if eval_tail_requested > 0 else "auto"
    if eval_tail_requested > 0:
        eval_tail_configured = max(0, eval_tail_requested)
    else:
        eval_tail_configured = max(0, cpu_budget_per_source - inflight)

    # Eval-tail headroom is bounded to per-source CPU budget and available variants.
    eval_tail_effective = max(
        0,
        min(
            eval_tail_configured,
            cpu_budget_per_source,
            max(0, total - inflight),
        ),
    )
    smart_enabled = (
        True if smart_scheduler is None else _coerce_bool_setting(smart_scheduler, default=True)
    )

    max_active_during_eval = inflight
    if smart_enabled:
        max_active_during_eval = min(total, inflight + eval_tail_effective)
    adaptive_overcommit_limit = max(
        0,
        min(split_slots, max(0, max_active_during_eval - inflight)),
    )
    adaptive_max_guard_target = min(
        total,
        split_slots + wing_target + adaptive_overcommit_limit,
    )

    return _AllMethodSchedulerRuntime(
        configured_inflight_pipelines=inflight,
        split_phase_slots_requested=split_slots_requested,
        split_phase_slots=split_slots,
        split_phase_slot_mode=str(split_slot_guard.get("split_phase_slot_mode") or "configured"),
        split_phase_slot_cap_by_cpu=_report_count(
            split_slot_guard.get("split_phase_slot_cap_by_cpu")
        ),
        split_phase_slot_cap_by_memory=(
            _report_count(split_slot_guard.get("split_phase_slot_cap_by_memory"))
            if split_slot_guard.get("split_phase_slot_cap_by_memory") is not None
            else None
        ),
        wing_backlog_target=wing_target,
        eval_tail_headroom_configured=eval_tail_configured,
        eval_tail_headroom_effective=eval_tail_effective,
        eval_tail_headroom_mode=eval_tail_mode,
        smart_scheduler_enabled=smart_enabled,
        max_active_during_eval=max_active_during_eval,
        effective_inflight_pipelines=max_active_during_eval if smart_enabled else inflight,
        adaptive_overcommit_limit=adaptive_overcommit_limit,
        adaptive_max_guard_target=adaptive_max_guard_target,
        source_parallelism_effective=source_parallelism,
        cpu_budget_per_source=cpu_budget_per_source,
        cpu_budget_total=cpu_budget_total,
    )


def _all_method_extract_alignment_guardrail_fields(
    report_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    report = report_payload if isinstance(report_payload, dict) else {}
    return {
        "alignment_cache_enabled": bool(report.get("alignment_cache_enabled")),
        "alignment_cache_hit": bool(report.get("alignment_cache_hit")),
        "alignment_cache_load_seconds": _report_metric(report.get("alignment_cache_load_seconds")),
        "alignment_cache_write_seconds": _report_metric(report.get("alignment_cache_write_seconds")),
        "alignment_sequence_matcher_impl": str(report.get("alignment_sequence_matcher_impl") or ""),
        "alignment_sequence_matcher_mode": str(report.get("alignment_sequence_matcher_mode") or ""),
        "alignment_sequence_matcher_requested_mode": str(
            report.get("alignment_sequence_matcher_requested_mode") or ""
        ),
        "alignment_sequence_matcher_forced_mode": str(
            report.get("alignment_sequence_matcher_forced_mode") or ""
        ),
    }


def _all_method_build_matcher_guardrails(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    executed_rows = [
        row
        for row in rows
        if str(row.get("status") or "").strip().lower() == "ok"
        and str(row.get("evaluation_result_source") or "").strip().lower() == "executed"
    ]
    eval_wall_sum = 0.0
    prediction_wall_sum = 0.0
    cache_enabled_count = 0
    cache_hit_count = 0
    matcher_mode_counts: dict[str, int] = {}

    for row in executed_rows:
        timing = _normalize_timing_payload(row.get("timing"))
        checkpoints = timing.get("checkpoints")
        if not isinstance(checkpoints, dict):
            checkpoints = {}
        eval_wall_sum += max(
            0.0,
            _report_metric(checkpoints.get("all_method_eval_wall_seconds")),
        )
        prediction_wall_sum += max(
            0.0,
            _report_metric(checkpoints.get("all_method_prediction_wall_seconds")),
        )
        cache_enabled = bool(row.get("alignment_cache_enabled"))
        if cache_enabled:
            cache_enabled_count += 1
            if bool(row.get("alignment_cache_hit")):
                cache_hit_count += 1
        matcher_mode = str(row.get("alignment_sequence_matcher_mode") or "").strip()
        if matcher_mode:
            matcher_mode_counts[matcher_mode] = matcher_mode_counts.get(matcher_mode, 0) + 1

    eval_to_prediction_ratio = (
        (eval_wall_sum / prediction_wall_sum) if prediction_wall_sum > 0 else 0.0
    )
    cache_hit_rate = (
        (float(cache_hit_count) / float(cache_enabled_count))
        if cache_enabled_count > 0
        else 1.0
    )
    warnings: list[str] = []
    if eval_to_prediction_ratio > ALL_METHOD_MATCHER_GUARDRAIL_EVAL_RATIO_WARN:
        warnings.append(
            "Eval wall share exceeded guardrail: "
            f"{eval_to_prediction_ratio:.3f} > {ALL_METHOD_MATCHER_GUARDRAIL_EVAL_RATIO_WARN:.3f}"
        )
    if cache_enabled_count > 0 and cache_hit_rate < ALL_METHOD_MATCHER_GUARDRAIL_CACHE_HIT_WARN:
        warnings.append(
            "Canonical alignment cache hit-rate dropped below guardrail: "
            f"{cache_hit_rate:.3f} < {ALL_METHOD_MATCHER_GUARDRAIL_CACHE_HIT_WARN:.3f}"
        )
    if matcher_mode_counts and not any(
        mode == "dmp" for mode in matcher_mode_counts
    ):
        warnings.append("Matcher guardrail expected dmp mode for canonical alignment.")

    return {
        "executed_evaluation_rows": len(executed_rows),
        "eval_wall_seconds_sum": eval_wall_sum,
        "prediction_wall_seconds_sum": prediction_wall_sum,
        "eval_to_prediction_wall_ratio": eval_to_prediction_ratio,
        "cache_enabled_count": cache_enabled_count,
        "cache_hit_count": cache_hit_count,
        "cache_hit_rate": cache_hit_rate,
        "matcher_mode_counts": matcher_mode_counts,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _all_method_config_dir_name(config_index: int, variant: AllMethodVariant) -> str:
    config_hash = variant.run_settings.short_hash()
    return f"config_{config_index:03d}_{config_hash}_{variant.slug}"


def _all_method_failed_row(
    *,
    config_index: int,
    config_dir_name: str,
    variant: AllMethodVariant,
    error: str,
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    row = {
        "config_index": config_index,
        "config_dir": config_dir_name,
        "slug": variant.slug,
        "status": "failed",
        "error": str(error),
        "run_config_hash": "",
        "run_config_summary": "",
        "dimensions": dict(variant.dimensions),
    }
    numeric_elapsed = _report_optional_metric(elapsed_seconds)
    if numeric_elapsed is not None:
        row["timing"] = _timing_with_updates(
            {},
            total_seconds=max(0.0, numeric_elapsed),
        )
    return row


def _stable_json_sha256(payload: Any) -> str:
    canonical = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _all_method_prediction_reuse_key_payload(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> dict[str, Any]:
    return {
        "schema_version": ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "prediction_identity": build_all_method_prediction_identity_payload(
            run_settings
        ),
    }


def _all_method_split_convert_input_key_payload(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> dict[str, Any]:
    run_config = run_settings.to_run_config_dict()
    selected_inputs = {
        key: run_config.get(key)
        for key in ALL_METHOD_SPLIT_CONVERT_INPUT_FIELDS
        if key in run_config
    }
    return {
        "schema_version": ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "inputs": selected_inputs,
    }


def _build_all_method_prediction_reuse_key(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _all_method_prediction_reuse_key_payload(
            source_file=source_file,
            run_settings=run_settings,
        )
    )


def _build_all_method_split_convert_input_key(
    *,
    source_file: Path,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _all_method_split_convert_input_key_payload(
            source_file=source_file,
            run_settings=run_settings,
        )
    )


def _single_book_split_cache_key_payload(
    *,
    source_file: Path,
    source_hash: str | None,
    pipeline: str | None,
    run_settings: RunSettings,
) -> dict[str, Any]:
    run_config = run_settings.to_run_config_dict()
    selected_inputs = {
        key: run_config.get(key)
        for key in SINGLE_BOOK_SPLIT_CONVERT_INPUT_FIELDS
        if key in run_config
    }
    normalized_pipeline = str(pipeline or "auto").strip().lower()
    return {
        "schema_version": SINGLE_BOOK_SPLIT_CACHE_KEY_SCHEMA_VERSION,
        "source_file": str(source_file),
        "source_hash": str(source_hash or "").strip() or None,
        "pipeline": normalized_pipeline or "auto",
        "inputs": selected_inputs,
    }


def _build_single_book_split_cache_key(
    *,
    source_file: Path,
    source_hash: str | None,
    pipeline: str | None,
    run_settings: RunSettings,
) -> str:
    return _stable_json_sha256(
        _single_book_split_cache_key_payload(
            source_file=source_file,
            source_hash=source_hash,
            pipeline=pipeline,
            run_settings=run_settings,
        )
    )


def _single_book_split_cache_entry_path(
    *,
    cache_root: Path,
    split_cache_key: str,
) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(split_cache_key or "").strip())
    if not safe_key:
        safe_key = "unknown"
    return cache_root / f"{safe_key}.json"


def _single_book_split_cache_lock_path(
    cache_path: Path,
) -> Path:
    return cache_path.with_suffix(
        f"{cache_path.suffix}{SINGLE_BOOK_SPLIT_CACHE_LOCK_SUFFIX}"
    )


def _load_single_book_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if (
        str(payload.get("schema_version") or "").strip()
        != SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION
    ):
        return None
    cached_key = str(payload.get("single_book_split_cache_key") or "").strip()
    if cached_key != str(expected_key or "").strip():
        return None
    conversion_payload = payload.get("conversion_result")
    if not isinstance(conversion_payload, dict):
        return None
    return payload


def _write_single_book_split_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _acquire_single_book_split_cache_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                    sort_keys=True,
                )
            )
    except Exception:  # noqa: BLE001
        try:
            lock_path.unlink()
        except OSError:
            pass
        return False
    return True


def _release_single_book_split_cache_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return


def _wait_for_single_book_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
    lock_path: Path,
    wait_seconds: float = SINGLE_BOOK_SPLIT_CACHE_WAIT_SECONDS,
    poll_seconds: float = SINGLE_BOOK_SPLIT_CACHE_POLL_SECONDS,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = _load_single_book_split_cache_entry(
            cache_path=cache_path,
            expected_key=expected_key,
        )
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return _load_single_book_split_cache_entry(
        cache_path=cache_path,
        expected_key=expected_key,
    )


def _all_method_prediction_reuse_cache_entry_path(
    *,
    cache_dir: Path,
    prediction_reuse_key: str,
) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(prediction_reuse_key or "").strip())
    if not safe_key:
        safe_key = "unknown"
    return cache_dir / f"{safe_key}.json"


def _load_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if (
        str(payload.get("schema_version") or "").strip()
        != ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION
    ):
        return None
    cached_key = str(payload.get("prediction_reuse_key") or "").strip()
    if cached_key != str(expected_key):
        return None
    config_dir = str(payload.get("config_dir") or "").strip()
    source_eval_output_dir = str(payload.get("source_eval_output_dir") or "").strip()
    if not config_dir and not source_eval_output_dir:
        return None
    return payload


def _write_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _acquire_all_method_prediction_reuse_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                    sort_keys=True,
                )
            )
    except Exception:  # noqa: BLE001
        try:
            lock_path.unlink()
        except OSError:
            pass
        return False
    return True


def _release_all_method_prediction_reuse_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return


def _wait_for_all_method_prediction_reuse_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
    lock_path: Path,
    wait_seconds: float = ALL_METHOD_PREDICTION_REUSE_WAIT_SECONDS,
    poll_seconds: float = ALL_METHOD_PREDICTION_REUSE_POLL_SECONDS,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = _load_all_method_prediction_reuse_cache_entry(
            cache_path=cache_path,
            expected_key=expected_key,
        )
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return _load_all_method_prediction_reuse_cache_entry(
        cache_path=cache_path,
        expected_key=expected_key,
    )


def _path_is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:  # noqa: BLE001
        return False


def _copytree_with_hardlink_fallback(
    *,
    source_dir: Path,
    target_dir: Path,
) -> None:
    try:
        shutil.copytree(source_dir, target_dir, copy_function=os.link)
    except Exception:  # noqa: BLE001
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)


def _copy_all_method_prediction_artifacts_for_reuse(
    *,
    source_config_dir: str,
    target_config_dir: str,
    root_output_dir: Path,
    scratch_root: Path,
    processed_output_root: Path,
    source_eval_output_dir: Path | None = None,
    source_scratch_output_dir: Path | None = None,
    source_processed_output_dir: Path | None = None,
) -> float | None:
    source_dir = str(source_config_dir or "").strip()
    target_dir = str(target_config_dir or "").strip()
    if not target_dir:
        return None
    if source_dir and source_dir == target_dir and source_eval_output_dir is None:
        return None

    if source_eval_output_dir is not None:
        resolved_source_eval_output_dir = Path(source_eval_output_dir).expanduser()
    else:
        if not source_dir:
            return None
        resolved_source_eval_output_dir = root_output_dir / source_dir
    target_eval_output_dir = root_output_dir / target_dir
    if resolved_source_eval_output_dir.resolve(
        strict=False
    ) == target_eval_output_dir.resolve(strict=False):
        return None
    source_prediction_records = resolved_source_eval_output_dir / "prediction-records.jsonl"
    if (
        not resolved_source_eval_output_dir.exists()
        or not resolved_source_eval_output_dir.is_dir()
        or not source_prediction_records.exists()
        or not source_prediction_records.is_file()
    ):
        return None

    if source_scratch_output_dir is not None:
        source_scratch_dir = Path(source_scratch_output_dir).expanduser()
    elif source_dir:
        source_scratch_dir = scratch_root / source_dir
    else:
        source_scratch_dir = Path("__missing_prediction_reuse_scratch__")
    target_scratch_dir = scratch_root / target_dir
    if source_processed_output_dir is not None:
        source_processed_dir = Path(source_processed_output_dir).expanduser()
    elif source_dir:
        source_processed_dir = processed_output_root / source_dir
    else:
        source_processed_dir = Path("__missing_prediction_reuse_processed__")
    target_processed_dir = processed_output_root / target_dir

    def _reset_tree(target_dir_path: Path) -> None:
        if target_dir_path.exists():
            shutil.rmtree(target_dir_path)

    copy_started = time.monotonic()
    _reset_tree(target_eval_output_dir)
    _reset_tree(target_scratch_dir)
    _reset_tree(target_processed_dir)
    _copytree_with_hardlink_fallback(
        source_dir=resolved_source_eval_output_dir,
        target_dir=target_eval_output_dir,
    )
    if source_scratch_dir.exists() and source_scratch_dir.is_dir():
        _copytree_with_hardlink_fallback(
            source_dir=source_scratch_dir,
            target_dir=target_scratch_dir,
        )
    if source_processed_dir.exists() and source_processed_dir.is_dir():
        _copytree_with_hardlink_fallback(
            source_dir=source_processed_dir,
            target_dir=target_processed_dir,
        )
    return max(0.0, time.monotonic() - copy_started)


def _all_method_eval_signature_prediction_rows(
    *,
    prediction_record_path: Path,
) -> list[dict[str, Any]]:
    prediction_records = list(read_prediction_records(prediction_record_path))
    if not prediction_records:
        raise ValueError(f"Prediction record file is empty: {prediction_record_path}")
    signature_rows: list[dict[str, Any]] = []
    for record in prediction_records:
        signature_rows.append(
            {
                "example_index": int(record.example_index),
                "prediction": _json_safe(record.prediction),
            }
        )
    signature_rows.sort(
        key=lambda row: (
            int(row.get("example_index", 0)),
            _stable_json_sha256(row.get("prediction", {})),
        )
    )
    return signature_rows


def _all_method_gold_fingerprint(gold_spans_path: Path) -> dict[str, Any]:
    fingerprint: dict[str, Any] = {"gold_spans_path": str(gold_spans_path)}
    if gold_spans_path.exists() and gold_spans_path.is_file():
        try:
            fingerprint["gold_spans_sha256"] = compute_file_hash(gold_spans_path)
        except Exception:  # noqa: BLE001
            fingerprint["gold_spans_sha256"] = None

    gold_export_root = gold_spans_path.parent
    for artifact_name in (
        "canonical_text.txt",
        "canonical_span_labels.jsonl",
        "canonical_manifest.json",
    ):
        artifact_path = gold_export_root / artifact_name
        if not artifact_path.exists() or not artifact_path.is_file():
            continue
        key = f"{artifact_name.replace('.', '_')}_sha256"
        try:
            fingerprint[key] = compute_file_hash(artifact_path)
        except Exception:  # noqa: BLE001
            fingerprint[key] = None
    return fingerprint


def _build_all_method_eval_signature(
    *,
    gold_spans_path: Path,
    prediction_record_path: Path,
    eval_mode: str,
    sequence_matcher: str,
    schema_version: str = ALL_METHOD_EVAL_SIGNATURE_SCHEMA_VERSION,
) -> str:
    signature_payload = {
        "schema_version": str(schema_version or ALL_METHOD_EVAL_SIGNATURE_SCHEMA_VERSION),
        "eval_mode": str(eval_mode or BENCHMARK_EVAL_MODE_CANONICAL_TEXT),
        "sequence_matcher": str(sequence_matcher or "dmp"),
        "gold_fingerprint": _all_method_gold_fingerprint(gold_spans_path),
        "prediction_rows": _all_method_eval_signature_prediction_rows(
            prediction_record_path=prediction_record_path
        ),
    }
    return _stable_json_sha256(signature_payload)


def _group_all_method_rows_by_eval_signature(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        eval_signature = str(row.get("eval_signature") or "").strip()
        if not eval_signature:
            continue
        grouped_rows[eval_signature].append(row)
    for eval_signature in list(grouped_rows):
        grouped_rows[eval_signature].sort(
            key=lambda row: _report_count(row.get("config_index"))
        )
    return dict(grouped_rows)


def _all_method_prediction_reuse_summary(
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    successful_rows = [
        row
        for row in rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    prediction_signatures_unique = len(
        {
            str(row.get("prediction_reuse_key") or "").strip()
            for row in successful_rows
            if str(row.get("prediction_reuse_key") or "").strip()
        }
    )
    prediction_runs_executed = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower() == "executed"
    )
    prediction_results_reused_in_run = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower()
        == "reused_in_run"
    )
    prediction_results_reused_cross_run = sum(
        1
        for row in successful_rows
        if str(row.get("prediction_result_source") or "").strip().lower()
        == "reused_cross_run"
    )

    split_convert_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in successful_rows:
        split_key = str(row.get("prediction_split_convert_input_key") or "").strip()
        if not split_key:
            continue
        split_convert_groups[split_key].append(row)
    split_convert_input_groups = len(split_convert_groups)
    split_convert_reuse_candidates = sum(
        max(0, len(group_rows) - 1) for group_rows in split_convert_groups.values()
    )
    split_convert_reuse_safe_candidates = 0
    split_convert_reuse_blocked_by_prediction_variance = 0
    for group_rows in split_convert_groups.values():
        if len(group_rows) <= 1:
            continue
        candidate_count = len(group_rows) - 1
        prediction_keys = {
            str(row.get("prediction_reuse_key") or "").strip()
            for row in group_rows
            if str(row.get("prediction_reuse_key") or "").strip()
        }
        if len(prediction_keys) <= 1:
            split_convert_reuse_safe_candidates += candidate_count
        else:
            split_convert_reuse_blocked_by_prediction_variance += candidate_count

    return {
        "prediction_signatures_unique": prediction_signatures_unique,
        "prediction_runs_executed": prediction_runs_executed,
        "prediction_results_reused_in_run": prediction_results_reused_in_run,
        "prediction_results_reused_cross_run": prediction_results_reused_cross_run,
        "split_convert_input_groups": split_convert_input_groups,
        "split_convert_reuse_candidates": split_convert_reuse_candidates,
        "split_convert_reuse_safe_candidates": split_convert_reuse_safe_candidates,
        "split_convert_reuse_blocked_by_prediction_variance": (
            split_convert_reuse_blocked_by_prediction_variance
        ),
    }


def _resolve_all_method_eval_signature_cache_dir(
    *,
    root_output_dir: Path,
    alignment_cache_dir: Path | None,
) -> Path:
    if alignment_cache_dir is None:
        return root_output_dir / ".cache" / "eval_signature_results"

    resolved_alignment_dir = alignment_cache_dir.expanduser()
    if resolved_alignment_dir.name == "canonical_alignment":
        return resolved_alignment_dir.parent / "eval_signature_results"
    if resolved_alignment_dir.parent.name == "canonical_alignment":
        return (
            resolved_alignment_dir.parent.parent
            / "eval_signature_results"
            / resolved_alignment_dir.name
        )
    return resolved_alignment_dir.parent / "eval_signature_results"


def _resolve_all_method_prediction_reuse_cache_dir(*, root_output_dir: Path) -> Path:
    env_override = str(
        os.getenv(ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV, "") or ""
    ).strip()
    if env_override:
        return Path(env_override).expanduser()
    return root_output_dir / ".prediction_reuse_cache"


def _load_all_method_eval_signature_cache_entry(
    *,
    cache_path: Path,
    expected_signature: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    schema_version = str(payload.get("schema_version") or "").strip()
    if schema_version != ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION:
        return None
    cached_signature = str(payload.get("eval_signature") or "").strip()
    if cached_signature != str(expected_signature):
        return None
    report_payload = payload.get("report")
    if not isinstance(report_payload, dict):
        return None
    return payload


def _write_all_method_eval_signature_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _materialize_all_method_cached_eval_outputs(
    *,
    eval_output_dir: Path,
    report_payload: dict[str, Any],
    report_md_text: str | None,
) -> tuple[Path, Path]:
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = eval_output_dir / "eval_report.json"
    report_md_path = eval_output_dir / "eval_report.md"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    rendered_md = str(report_md_text or "").strip()
    if not rendered_md:
        rendered_md = (
            "# Benchmark Eval Report (Cached)\n\n"
            "Evaluation report reused from all-method signature cache."
        )
    report_md_path.write_text(rendered_md, encoding="utf-8")
    return report_json_path, report_md_path


def _resolve_all_method_prediction_record_path(
    *,
    root_output_dir: Path,
    row: dict[str, Any],
) -> Path | None:
    raw_value = str(row.get("prediction_record_jsonl") or "").strip()
    if not raw_value:
        return None
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = root_output_dir / candidate
    return candidate


def _run_all_method_prediction_once(
    *,
    gold_spans_path: Path,
    source_file: Path,
    variant: AllMethodVariant,
    config_index: int,
    total_variants: int,
    root_output_dir: Path,
    scratch_root: Path,
    processed_output_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    max_concurrent_split_phases: int,
    split_phase_gate_dir: Path,
    scheduler_events_dir: Path,
    alignment_cache_dir: Path | None,
    prediction_reuse_cache_dir: Path | None = None,
    split_worker_cap_per_config: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    config_started = time.monotonic()
    config_dir_name = _all_method_config_dir_name(config_index, variant)
    eval_output_dir = root_output_dir / config_dir_name
    scratch_output_dir = scratch_root / config_dir_name
    processed_output_dir = processed_output_root / config_dir_name
    prediction_record_path = eval_output_dir / "prediction-records.jsonl"
    prediction_reuse_key = _build_all_method_prediction_reuse_key(
        source_file=source_file,
        run_settings=variant.run_settings,
    )
    prediction_split_convert_input_key = _build_all_method_split_convert_input_key(
        source_file=source_file,
        run_settings=variant.run_settings,
    )
    prediction_result_source = "executed"
    prediction_reuse_scope = "executed"
    prediction_representative_config_dir = config_dir_name
    reused_prediction = False

    split_slots = max(1, _report_count(max_concurrent_split_phases))
    split_status_label = format_task_counter(
        "Config",
        config_index,
        max(1, _report_count(total_variants)),
        noun="config",
    )
    source_slug = slugify_name(source_file.stem)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    scheduler_event_path = scheduler_events_dir / f"config_{config_index:03d}.jsonl"
    if scheduler_event_path.exists():
        scheduler_event_path.unlink()

    def _emit_scheduler_event(
        event_name: str,
        **payload: Any,
    ) -> None:
        event = str(event_name or "").strip()
        if not event:
            return
        row = {
            "event": event,
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": time.monotonic(),
            "config_index": config_index,
            "config_slug": variant.slug,
            "config_dir": config_dir_name,
            "source_slug": source_slug,
        }
        row.update(payload)
        try:
            with scheduler_event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring scheduler event write failure for %s: %s",
                scheduler_event_path,
                exc,
            )

    def _scheduler_event_callback(payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        event_name = str(payload.get("event") or "").strip()
        if not event_name:
            return
        event_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"event", "config_index", "config_slug", "source_slug"}
        }
        _emit_scheduler_event(event_name, **event_payload)

    def _discard_progress(_message: str) -> None:
        return

    def _prediction_failed_row(error: str, *, elapsed_seconds: float) -> dict[str, Any]:
        row = _all_method_failed_row(
            config_index=config_index,
            config_dir_name=config_dir_name,
            variant=variant,
            error=error,
            elapsed_seconds=elapsed_seconds,
        )
        row["prediction_result_source"] = "failed"
        row["prediction_reuse_scope"] = "failed"
        row["prediction_representative_config_dir"] = config_dir_name
        row["prediction_reuse_key"] = prediction_reuse_key
        row["prediction_split_convert_input_key"] = prediction_split_convert_input_key
        return row

    def _reset_target_prediction_dirs() -> None:
        if eval_output_dir.exists():
            shutil.rmtree(eval_output_dir)
        if scratch_output_dir.exists():
            shutil.rmtree(scratch_output_dir)
        if processed_output_dir.exists():
            shutil.rmtree(processed_output_dir)

    benchmark_progress_callback = progress_callback or _discard_progress
    _emit_scheduler_event("config_started")

    requested_workers = max(1, _report_count(variant.run_settings.workers))
    requested_pdf_split_workers = max(1, _report_count(variant.run_settings.pdf_split_workers))
    requested_epub_split_workers = max(1, _report_count(variant.run_settings.epub_split_workers))
    effective_split_worker_cap = (
        max(1, _report_count(split_worker_cap_per_config))
        if split_worker_cap_per_config is not None
        else None
    )
    effective_workers = requested_workers
    effective_pdf_split_workers = requested_pdf_split_workers
    effective_epub_split_workers = requested_epub_split_workers
    if effective_split_worker_cap is not None:
        effective_workers = min(effective_workers, effective_split_worker_cap)
        effective_pdf_split_workers = min(
            effective_pdf_split_workers,
            effective_split_worker_cap,
        )
        effective_epub_split_workers = min(
            effective_epub_split_workers,
            effective_split_worker_cap,
        )

    prediction_reuse_cache_dir = (
        prediction_reuse_cache_dir
        if prediction_reuse_cache_dir is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    ).expanduser()
    prediction_reuse_cache_path = _all_method_prediction_reuse_cache_entry_path(
        cache_dir=prediction_reuse_cache_dir,
        prediction_reuse_key=prediction_reuse_key,
    )
    prediction_reuse_lock_path = prediction_reuse_cache_path.with_suffix(
        f"{prediction_reuse_cache_path.suffix}{ALL_METHOD_PREDICTION_REUSE_LOCK_SUFFIX}"
    )
    lock_acquired = False

    def _execute_prediction_run() -> str | None:
        _reset_target_prediction_dirs()
        try:
            with _benchmark_split_phase_overrides(
                split_phase_slots=split_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                split_phase_status_label=split_status_label,
            ):
                with _benchmark_progress_overrides(
                    progress_callback=benchmark_progress_callback,
                    suppress_summary=True,
                    suppress_spinner=True,
                    suppress_output_prune=True,
                ):
                    with _benchmark_scheduler_event_overrides(
                        scheduler_event_callback=_scheduler_event_callback
                    ):
                        benchmark_kwargs = build_benchmark_call_kwargs_from_run_settings(
                            variant.run_settings,
                            output_dir=scratch_output_dir,
                            processed_output_dir=processed_output_dir,
                            eval_output_dir=eval_output_dir,
                            eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                            no_upload=True,
                            write_markdown=False,
                            write_label_studio_tasks=False,
                        )
                        benchmark_kwargs["allow_codex"] = codex_surfaces_enabled(
                            variant.run_settings.to_run_config_dict()
                        )
                        benchmark_kwargs.update(
                            {
                                "source_file": source_file,
                                "workers": effective_workers,
                                "pdf_split_workers": effective_pdf_split_workers,
                                "epub_split_workers": effective_epub_split_workers,
                            }
                        )
                        prediction_generation_kwargs = {
                            "path": benchmark_kwargs["source_file"],
                            "output_dir": benchmark_kwargs["output_dir"],
                            "pipeline": benchmark_kwargs.get("pipeline", "auto"),
                            "segment_blocks": 40,
                            "segment_overlap": 5,
                            "limit": None,
                            "sample": None,
                            "workers": benchmark_kwargs["workers"],
                            "pdf_split_workers": benchmark_kwargs["pdf_split_workers"],
                            "epub_split_workers": benchmark_kwargs["epub_split_workers"],
                            "pdf_pages_per_job": benchmark_kwargs["pdf_pages_per_job"],
                            "epub_spine_items_per_job": benchmark_kwargs[
                                "epub_spine_items_per_job"
                            ],
                            "epub_extractor": benchmark_kwargs["epub_extractor"],
                            "epub_unstructured_html_parser_version": benchmark_kwargs[
                                "epub_unstructured_html_parser_version"
                            ],
                            "epub_unstructured_skip_headers_footers": benchmark_kwargs[
                                "epub_unstructured_skip_headers_footers"
                            ],
                            "epub_unstructured_preprocess_mode": benchmark_kwargs[
                                "epub_unstructured_preprocess_mode"
                            ],
                            "ocr_device": benchmark_kwargs["ocr_device"],
                            "pdf_ocr_policy": benchmark_kwargs["pdf_ocr_policy"],
                            "ocr_batch_size": benchmark_kwargs["ocr_batch_size"],
                            "pdf_column_gap_ratio": benchmark_kwargs[
                                "pdf_column_gap_ratio"
                            ],
                            "warm_models": benchmark_kwargs["warm_models"],
                            "section_detector_backend": benchmark_kwargs[
                                "section_detector_backend"
                            ],
                            "multi_recipe_splitter": benchmark_kwargs[
                                "multi_recipe_splitter"
                            ],
                            "multi_recipe_trace": benchmark_kwargs["multi_recipe_trace"],
                            "multi_recipe_min_ingredient_lines": benchmark_kwargs[
                                "multi_recipe_min_ingredient_lines"
                            ],
                            "multi_recipe_min_instruction_lines": benchmark_kwargs[
                                "multi_recipe_min_instruction_lines"
                            ],
                            "multi_recipe_for_the_guardrail": benchmark_kwargs[
                                "multi_recipe_for_the_guardrail"
                            ],
                            "instruction_step_segmentation_policy": benchmark_kwargs[
                                "instruction_step_segmentation_policy"
                            ],
                            "instruction_step_segmenter": benchmark_kwargs[
                                "instruction_step_segmenter"
                            ],
                            "web_schema_extractor": benchmark_kwargs[
                                "web_schema_extractor"
                            ],
                            "web_schema_normalizer": benchmark_kwargs[
                                "web_schema_normalizer"
                            ],
                            "web_html_text_extractor": benchmark_kwargs[
                                "web_html_text_extractor"
                            ],
                            "web_schema_policy": benchmark_kwargs["web_schema_policy"],
                            "web_schema_min_confidence": benchmark_kwargs[
                                "web_schema_min_confidence"
                            ],
                            "web_schema_min_ingredients": benchmark_kwargs[
                                "web_schema_min_ingredients"
                            ],
                            "web_schema_min_instruction_steps": benchmark_kwargs[
                                "web_schema_min_instruction_steps"
                            ],
                            "ingredient_text_fix_backend": benchmark_kwargs[
                                "ingredient_text_fix_backend"
                            ],
                            "ingredient_pre_normalize_mode": benchmark_kwargs[
                                "ingredient_pre_normalize_mode"
                            ],
                            "ingredient_packaging_mode": benchmark_kwargs[
                                "ingredient_packaging_mode"
                            ],
                            "ingredient_parser_backend": benchmark_kwargs[
                                "ingredient_parser_backend"
                            ],
                            "ingredient_unit_canonicalizer": benchmark_kwargs[
                                "ingredient_unit_canonicalizer"
                            ],
                            "ingredient_missing_unit_policy": benchmark_kwargs[
                                "ingredient_missing_unit_policy"
                            ],
                            "p6_time_backend": benchmark_kwargs["p6_time_backend"],
                            "p6_time_total_strategy": benchmark_kwargs[
                                "p6_time_total_strategy"
                            ],
                            "p6_temperature_backend": benchmark_kwargs[
                                "p6_temperature_backend"
                            ],
                            "p6_temperature_unit_backend": benchmark_kwargs[
                                "p6_temperature_unit_backend"
                            ],
                            "p6_ovenlike_mode": benchmark_kwargs["p6_ovenlike_mode"],
                            "p6_yield_mode": benchmark_kwargs["p6_yield_mode"],
                            "p6_emit_metadata_debug": benchmark_kwargs[
                                "p6_emit_metadata_debug"
                            ],
                            "recipe_scorer_backend": benchmark_kwargs[
                                "recipe_scorer_backend"
                            ],
                            "recipe_score_gold_min": benchmark_kwargs[
                                "recipe_score_gold_min"
                            ],
                            "recipe_score_silver_min": benchmark_kwargs[
                                "recipe_score_silver_min"
                            ],
                            "recipe_score_bronze_min": benchmark_kwargs[
                                "recipe_score_bronze_min"
                            ],
                            "recipe_score_min_ingredient_lines": benchmark_kwargs[
                                "recipe_score_min_ingredient_lines"
                            ],
                            "recipe_score_min_instruction_lines": benchmark_kwargs[
                                "recipe_score_min_instruction_lines"
                            ],
                            "llm_recipe_pipeline": benchmark_kwargs[
                                "llm_recipe_pipeline"
                            ],
                            "llm_knowledge_pipeline": benchmark_kwargs[
                                "llm_knowledge_pipeline"
                            ],
                            "atomic_block_splitter": benchmark_kwargs[
                                "atomic_block_splitter"
                            ],
                            "line_role_pipeline": benchmark_kwargs["line_role_pipeline"],
                            "codex_farm_cmd": benchmark_kwargs["codex_farm_cmd"],
                            "codex_farm_model": benchmark_kwargs.get("codex_farm_model"),
                            "codex_farm_reasoning_effort": benchmark_kwargs.get(
                                "codex_farm_reasoning_effort"
                            ),
                            "codex_farm_root": benchmark_kwargs.get("codex_farm_root"),
                            "codex_farm_workspace_root": benchmark_kwargs.get(
                                "codex_farm_workspace_root"
                            ),
                            "codex_farm_pipeline_knowledge": benchmark_kwargs[
                                "codex_farm_pipeline_knowledge"
                            ],
                            "codex_farm_context_blocks": benchmark_kwargs[
                                "codex_farm_context_blocks"
                            ],
                            "codex_farm_knowledge_context_blocks": benchmark_kwargs[
                                "codex_farm_knowledge_context_blocks"
                            ],
                            "codex_farm_recipe_mode": benchmark_kwargs[
                                "codex_farm_recipe_mode"
                            ],
                            "codex_farm_failure_mode": benchmark_kwargs[
                                "codex_farm_failure_mode"
                            ],
                            "allow_codex": benchmark_kwargs["allow_codex"],
                            "codex_execution_policy": "execute",
                            "processed_output_root": benchmark_kwargs[
                                "processed_output_dir"
                            ],
                            "write_markdown": benchmark_kwargs["write_markdown"],
                            "write_label_studio_tasks": benchmark_kwargs[
                                "write_label_studio_tasks"
                            ],
                            "scheduler_event_callback": _scheduler_event_callback,
                            "progress_callback": benchmark_progress_callback,
                            "run_manifest_kind": "bench_pred_run",
                        }
                        _run_offline_benchmark_prediction_stage(
                            prediction_generation_kwargs=prediction_generation_kwargs,
                            eval_output_dir=eval_output_dir,
                            predictions_out_path=prediction_record_path,
                            suppress_spinner=True,
                            external_progress_callback=benchmark_progress_callback,
                        )
        except Exception as exc:  # noqa: BLE001
            return str(exc)
        return None

    def _try_materialize_reused_prediction(
        cache_entry: dict[str, Any] | None,
    ) -> bool:
        nonlocal prediction_result_source
        nonlocal prediction_reuse_scope
        nonlocal prediction_representative_config_dir
        nonlocal reused_prediction
        if not isinstance(cache_entry, dict):
            return False
        source_config_dir = str(cache_entry.get("config_dir") or "").strip()
        source_eval_output_dir: Path | None = None
        source_scratch_output_dir: Path | None = None
        source_processed_output_dir: Path | None = None
        source_eval_raw = str(cache_entry.get("source_eval_output_dir") or "").strip()
        source_scratch_raw = str(
            cache_entry.get("source_scratch_output_dir") or ""
        ).strip()
        source_processed_raw = str(
            cache_entry.get("source_processed_output_dir") or ""
        ).strip()
        if source_eval_raw:
            source_eval_output_dir = Path(source_eval_raw).expanduser()
        if source_scratch_raw:
            source_scratch_output_dir = Path(source_scratch_raw).expanduser()
        if source_processed_raw:
            source_processed_output_dir = Path(source_processed_raw).expanduser()
        if not source_config_dir and source_eval_output_dir is None:
            return False
        if source_config_dir == config_dir_name:
            if source_eval_output_dir is None:
                return False
            if source_eval_output_dir.resolve(strict=False) == eval_output_dir.resolve(
                strict=False
            ):
                return False
        copy_seconds = _copy_all_method_prediction_artifacts_for_reuse(
            source_config_dir=source_config_dir,
            target_config_dir=config_dir_name,
            root_output_dir=root_output_dir,
            scratch_root=scratch_root,
            processed_output_root=processed_output_root,
            source_eval_output_dir=source_eval_output_dir,
            source_scratch_output_dir=source_scratch_output_dir,
            source_processed_output_dir=source_processed_output_dir,
        )
        if copy_seconds is None:
            return False
        reuse_scope = "in_run"
        if source_eval_output_dir is not None and not _path_is_within_root(
            source_eval_output_dir,
            root_output_dir,
        ):
            reuse_scope = "cross_run"
        prediction_result_source = (
            "reused_cross_run" if reuse_scope == "cross_run" else "reused_in_run"
        )
        prediction_reuse_scope = reuse_scope
        prediction_representative_config_dir = (
            source_config_dir
            or (str(source_eval_output_dir) if source_eval_output_dir is not None else "")
            or config_dir_name
        )
        reused_prediction = True
        _emit_scheduler_event(
            (
                "prediction_reused_cross_run"
                if prediction_result_source == "reused_cross_run"
                else "prediction_reused_in_run"
            ),
            source_config_dir=source_config_dir,
            reuse_copy_seconds=copy_seconds,
            prediction_result_source=prediction_result_source,
            prediction_reuse_scope=prediction_reuse_scope,
        )
        return True

    try:
        cache_entry = _load_all_method_prediction_reuse_cache_entry(
            cache_path=prediction_reuse_cache_path,
            expected_key=prediction_reuse_key,
        )
        if not _try_materialize_reused_prediction(cache_entry):
            lock_acquired = _acquire_all_method_prediction_reuse_lock(
                prediction_reuse_lock_path
            )
            if lock_acquired:
                cache_entry = _load_all_method_prediction_reuse_cache_entry(
                    cache_path=prediction_reuse_cache_path,
                    expected_key=prediction_reuse_key,
                )
                if not _try_materialize_reused_prediction(cache_entry):
                    run_error = _execute_prediction_run()
                    if run_error is not None:
                        _emit_scheduler_event(
                            "config_finished",
                            status="failed",
                            error=run_error,
                        )
                        return _prediction_failed_row(
                            run_error,
                            elapsed_seconds=max(0.0, time.monotonic() - config_started),
                        )
            else:
                waited_entry = _wait_for_all_method_prediction_reuse_cache_entry(
                    cache_path=prediction_reuse_cache_path,
                    expected_key=prediction_reuse_key,
                    lock_path=prediction_reuse_lock_path,
                )
                if not _try_materialize_reused_prediction(waited_entry):
                    run_error = _execute_prediction_run()
                    if run_error is not None:
                        _emit_scheduler_event(
                            "config_finished",
                            status="failed",
                            error=run_error,
                        )
                        return _prediction_failed_row(
                            run_error,
                            elapsed_seconds=max(0.0, time.monotonic() - config_started),
                        )
    finally:
        if lock_acquired:
            _release_all_method_prediction_reuse_lock(prediction_reuse_lock_path)

    if prediction_result_source == "executed":
        cache_payload = {
            "schema_version": ALL_METHOD_PREDICTION_REUSE_CACHE_SCHEMA_VERSION,
            "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "prediction_reuse_key": prediction_reuse_key,
            "prediction_split_convert_input_key": prediction_split_convert_input_key,
            "source_file": str(source_file),
            "config_index": config_index,
            "config_dir": config_dir_name,
            "source_eval_output_dir": str(eval_output_dir),
            "source_scratch_output_dir": str(scratch_output_dir),
            "source_processed_output_dir": str(processed_output_dir),
        }
        try:
            _write_all_method_prediction_reuse_cache_entry(
                cache_path=prediction_reuse_cache_path,
                payload=cache_payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring all-method prediction reuse cache write failure for %s: %s",
                prediction_reuse_cache_path,
                exc,
            )

    if not prediction_record_path.exists():
        missing_error = f"Missing prediction-records.jsonl in {eval_output_dir}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=missing_error,
        )
        return _prediction_failed_row(
            missing_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )
    try:
        prediction_records = list(read_prediction_records(prediction_record_path))
    except Exception as exc:  # noqa: BLE001
        parse_error = f"Failed to parse prediction records for {config_dir_name}: {exc}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=parse_error,
        )
        return _prediction_failed_row(
            parse_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )
    if not prediction_records:
        empty_error = f"Prediction records are empty for {config_dir_name}"
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=empty_error,
        )
        return _prediction_failed_row(
            empty_error,
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )

    config_wall_seconds = max(0.0, time.monotonic() - config_started)
    report_timing: dict[str, Any] = {}
    run_manifest_path = eval_output_dir / "run_manifest.json"
    if run_manifest_path.exists() and run_manifest_path.is_file():
        try:
            run_manifest_payload = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            run_manifest_payload = {}
        if isinstance(run_manifest_payload, dict):
            artifacts_payload = run_manifest_payload.get("artifacts")
            if isinstance(artifacts_payload, dict):
                report_timing = _normalize_timing_payload(artifacts_payload.get("timing"))

    # Test doubles sometimes write timing only via eval_report.json.
    if not report_timing:
        report_json_path = eval_output_dir / "eval_report.json"
        if report_json_path.exists() and report_json_path.is_file():
            try:
                report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                report_payload = {}
            if isinstance(report_payload, dict):
                report_timing = _normalize_timing_payload(report_payload.get("timing"))

    prediction_phase_seconds = _report_optional_metric(
        report_timing.get("prediction_seconds")
    )
    report_total_seconds = _report_optional_metric(report_timing.get("total_seconds"))
    if reused_prediction:
        prediction_phase_seconds = 0.0
        report_total_seconds = config_wall_seconds
    if prediction_phase_seconds is None and report_total_seconds is not None:
        prediction_phase_seconds = report_total_seconds
    if prediction_phase_seconds is None:
        prediction_phase_seconds = config_wall_seconds
    prediction_checkpoints: dict[str, float] = {
        "all_method_prediction_wall_seconds": config_wall_seconds,
        "all_method_config_wall_seconds": config_wall_seconds,
        "all_method_prediction_reused_in_run": 1.0 if reused_prediction else 0.0,
    }
    if reused_prediction:
        prediction_checkpoints["all_method_prediction_reuse_copy_seconds"] = (
            config_wall_seconds
        )
    config_timing = _timing_with_updates(
        report_timing,
        prediction_seconds=prediction_phase_seconds,
        evaluation_seconds=0.0,
        total_seconds=(
            report_total_seconds if report_total_seconds is not None else config_wall_seconds
        ),
        checkpoints=prediction_checkpoints,
    )

    pred_context = _load_pred_run_recipe_context(eval_output_dir)
    row = {
        "config_index": config_index,
        "config_dir": config_dir_name,
        "slug": variant.slug,
        "status": "ok",
        "error": "",
        "run_config_hash": pred_context.run_config_hash or variant.run_settings.stable_hash(),
        "run_config_summary": pred_context.run_config_summary
        or variant.run_settings.summary(),
        "prediction_record_jsonl": _path_for_manifest(
            root_output_dir,
            prediction_record_path,
        ),
        "benchmark_sequence_matcher": variant.run_settings.benchmark_sequence_matcher,
        "duration_seconds": config_wall_seconds,
        "timing": config_timing,
        "dimensions": dict(variant.dimensions),
        "prediction_result_source": prediction_result_source,
        "prediction_reuse_scope": prediction_reuse_scope,
        "prediction_representative_config_dir": prediction_representative_config_dir,
        "prediction_reuse_key": prediction_reuse_key,
        "prediction_split_convert_input_key": prediction_split_convert_input_key,
    }
    _emit_scheduler_event(
        "config_finished",
        status="ok",
        duration_seconds=config_wall_seconds,
        prediction_result_source=prediction_result_source,
    )
    return row


def _run_all_method_evaluate_prediction_record_once(
    *,
    gold_spans_path: Path,
    source_file: Path,
    prediction_record_path: Path,
    eval_output_dir: Path,
    processed_output_dir: Path,
    sequence_matcher: str,
    epub_extractor: str | None,
    overlap_threshold: float,
    force_source_match: bool,
    alignment_cache_dir: Path | None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    evaluation_started = time.monotonic()

    def _discard_progress(_message: str) -> None:
        return

    benchmark_progress_callback = progress_callback or _discard_progress
    scratch_output_dir = eval_output_dir / ".scratch-eval-only"
    if scratch_output_dir.exists():
        shutil.rmtree(scratch_output_dir)
    for artifact_name in ("eval_report.json", "eval_report.md"):
        artifact_path = eval_output_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()

    fail_message_token = _LAST_FAIL_MESSAGE.set(None)
    try:
        with _benchmark_progress_overrides(
            progress_callback=benchmark_progress_callback,
            suppress_summary=True,
            suppress_spinner=True,
            suppress_output_prune=True,
        ):
            labelstudio_benchmark(
                gold_spans=gold_spans_path,
                source_file=source_file,
                output_dir=scratch_output_dir,
                processed_output_dir=processed_output_dir,
                eval_output_dir=eval_output_dir,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
                epub_extractor=(epub_extractor or "unstructured"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                no_upload=True,
                predictions_in=prediction_record_path,
                alignment_cache_dir=alignment_cache_dir,
            )
    except typer.Exit as exc:
        exit_code = getattr(exc, "exit_code", 1)
        failure_message = _LAST_FAIL_MESSAGE.get()
        error_message = (
            failure_message
            if failure_message
            else f"labelstudio_benchmark exited with code {exit_code}"
        )
        return {
            "status": "failed",
            "error": error_message,
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error": str(exc),
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    finally:
        _LAST_FAIL_MESSAGE.reset(fail_message_token)

    report_json_path = eval_output_dir / "eval_report.json"
    if not report_json_path.exists() or not report_json_path.is_file():
        return {
            "status": "failed",
            "error": f"Missing eval_report.json in {eval_output_dir}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    try:
        report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error": f"Failed to parse eval report in {eval_output_dir}: {exc}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }
    if not isinstance(report_payload, dict):
        return {
            "status": "failed",
            "error": f"Eval report payload is invalid in {eval_output_dir}",
            "duration_seconds": max(0.0, time.monotonic() - evaluation_started),
        }

    evaluation_wall_seconds = max(0.0, time.monotonic() - evaluation_started)
    report_timing = _normalize_timing_payload(report_payload.get("timing"))
    report_total_seconds = _report_optional_metric(report_timing.get("total_seconds"))
    normalized_timing = _timing_with_updates(
        report_timing,
        total_seconds=(
            report_total_seconds
            if report_total_seconds is not None
            else evaluation_wall_seconds
        ),
        checkpoints={"all_method_eval_wall_seconds": evaluation_wall_seconds},
    )
    report_payload["timing"] = normalized_timing
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = eval_output_dir / "eval_report.md"
    report_md_text = (
        report_md_path.read_text(encoding="utf-8")
        if report_md_path.exists() and report_md_path.is_file()
        else ""
    )
    metric_bundle = _benchmark_report_metric_bundle(report_payload)
    return {
        "status": "ok",
        "error": "",
        **metric_bundle,
        "timing": normalized_timing,
        "report": report_payload,
        "report_md_text": report_md_text,
        "eval_report_json_path": report_json_path,
        "eval_report_md_path": report_md_path,
        "duration_seconds": evaluation_wall_seconds,
    }


def _render_all_method_report_md(report_payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "# All Method Benchmark Report",
        "",
        f"- Created at: {report_payload.get('created_at', '')}",
        f"- Source file: {report_payload.get('source_file', '')}",
        f"- Gold spans: {report_payload.get('gold_spans_path', '')}",
        f"- Eval mode: {report_payload.get('eval_mode', BENCHMARK_EVAL_MODE_CANONICAL_TEXT)}",
        f"- Scheduler scope: {report_payload.get('scheduler_scope', 'per_source')}",
        f"- Total configurations: {report_payload.get('variant_count', 0)}",
        f"- Successful configurations: {report_payload.get('successful_variants', 0)}",
        f"- Failed configurations: {report_payload.get('failed_variants', 0)}",
        (
            "- Evaluation signatures unique / runs executed: "
            f"{_report_count(report_payload.get('evaluation_signatures_unique'))}/"
            f"{_report_count(report_payload.get('evaluation_runs_executed'))}"
        ),
        (
            "- Evaluation results reused in-run/cross-run: "
            f"{_report_count(report_payload.get('evaluation_results_reused_in_run'))}/"
            f"{_report_count(report_payload.get('evaluation_results_reused_cross_run'))}"
        ),
        (
            "- Prediction signatures unique / runs executed / reused in-run/cross-run: "
            f"{_report_count(report_payload.get('prediction_signatures_unique'))}/"
            f"{_report_count(report_payload.get('prediction_runs_executed'))}/"
            f"{_report_count(report_payload.get('prediction_results_reused_in_run'))}/"
            f"{_report_count(report_payload.get('prediction_results_reused_cross_run'))}"
        ),
        (
            "- Split/convert input groups / reuse candidates / safe / blocked: "
            f"{_report_count(report_payload.get('split_convert_input_groups'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_candidates'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_safe_candidates'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_blocked_by_prediction_variance'))}"
        ),
        (
            "- Failed-config retries requested/executed/recovered: "
            f"{_report_count(report_payload.get('retry_failed_configs_requested'))}/"
            f"{_report_count(report_payload.get('retry_passes_executed'))}/"
            f"{_report_count(report_payload.get('retry_recovered_configs'))}"
        ),
        (
            "- Codex Farm permutations requested/effective: "
            f"{report_payload.get('include_codex_farm_requested', False)}/"
            f"{report_payload.get('include_codex_farm_effective', False)}"
        ),
        "",
    ]

    winner = report_payload.get("winner_by_f1")
    if isinstance(winner, dict) and winner:
        lines.extend(
            [
                "## Winner",
                "",
                (
                    f"- {winner.get('config_dir', '')} "
                    f"(precision={_report_metric(winner.get('precision')):.3f}, "
                    f"recall={_report_metric(winner.get('recall')):.3f}, "
                    f"f1={_report_metric(winner.get('f1')):.3f})"
                ),
                "",
            ]
        )

    timing_summary = report_payload.get("timing_summary")
    if isinstance(timing_summary, dict):
        lines.extend(
            [
                "## Timing Summary",
                "",
                (
                    "- Source wall time: "
                    f"{_report_metric(timing_summary.get('source_wall_seconds')):.2f}s"
                ),
                (
                    "- Total successful config runtime: "
                    f"{_report_metric(timing_summary.get('config_total_seconds')):.2f}s"
                ),
            ]
        )
        average_seconds = _report_optional_metric(
            timing_summary.get("config_average_seconds")
        )
        if average_seconds is not None:
            lines.append(f"- Average config runtime: {average_seconds:.2f}s")
        median_seconds = _report_optional_metric(
            timing_summary.get("config_median_seconds")
        )
        if median_seconds is not None:
            lines.append(f"- Median config runtime: {median_seconds:.2f}s")
        slowest_config = str(timing_summary.get("slowest_config_dir") or "").strip()
        slowest_seconds = _report_optional_metric(
            timing_summary.get("slowest_config_seconds")
        )
        if slowest_config and slowest_seconds is not None:
            lines.append(
                f"- Slowest config: {slowest_config} ({slowest_seconds:.2f}s)"
        )
        lines.append("")

    scheduler = report_payload.get("scheduler")
    if isinstance(scheduler, dict):
        lines.extend(
            [
                "## Scheduler Summary",
                "",
                (
                    "- Scheduler mode: "
                    f"{scheduler.get('mode', 'fixed')} "
                    f"(smart enabled={bool(scheduler.get('smart_scheduler_enabled', False))})"
                ),
                (
                    "- Inflight configured/effective: "
                    f"{_report_count(scheduler.get('configured_inflight_pipelines'))}/"
                    f"{_report_count(scheduler.get('effective_inflight_pipelines'))}"
                ),
                (
                    "- Split slots / wing target: "
                    f"{_report_count(scheduler.get('split_phase_slots'))}/"
                    f"{_report_count(scheduler.get('wing_backlog_target'))}"
                ),
                (
                    "- Eval-tail headroom mode configured/effective: "
                    f"{scheduler.get('eval_tail_headroom_mode', 'auto')} "
                    f"{_report_count(scheduler.get('eval_tail_headroom_configured'))}/"
                    f"{_report_count(scheduler.get('eval_tail_headroom_effective'))}"
                ),
                (
                    "- Max active during eval / effective inflight: "
                    f"{_report_count(scheduler.get('max_active_during_eval'))}/"
                    f"{_report_count(scheduler.get('effective_inflight_pipelines'))}"
                ),
                (
                    "- Split worker cap per active config (cpu/memory): "
                    f"{_report_count(scheduler.get('split_worker_cap_per_config'))}/"
                    f"{_report_count(scheduler.get('split_worker_cap_by_cpu'))}/"
                    f"{_report_count(scheduler.get('split_worker_cap_by_memory'))}"
                ),
                (
                    "- Config timeout / retry limit: "
                    f"{('off' if scheduler.get('config_timeout_seconds') is None else str(_report_count(scheduler.get('config_timeout_seconds'))) + 's')}/"
                    f"{_report_count(scheduler.get('failed_retry_limit'))}"
                ),
                (
                    "- Retry passes executed / recovered configs: "
                    f"{_report_count(scheduler.get('retry_passes_executed'))}/"
                    f"{_report_count(scheduler.get('retry_recovered_configs'))}"
                ),
                (
                    "- Heavy slot utilization: "
                    f"{_report_metric(scheduler.get('heavy_slot_utilization_pct')):.1f}% "
                    f"(busy { _report_metric(scheduler.get('heavy_slot_busy_seconds')):.2f}s / "
                    f"capacity {_report_metric(scheduler.get('heavy_slot_capacity_seconds')):.2f}s)"
                ),
                (
                    "- Wing backlog avg/max: "
                    f"{_report_metric(scheduler.get('avg_wing_backlog')):.2f}/"
                    f"{_report_count(scheduler.get('max_wing_backlog'))}"
                ),
                (
                    "- Heavy idle gap while pending: "
                    f"{_report_metric(scheduler.get('idle_gap_seconds')):.2f}s"
                ),
                (
                    "- Max active/eval pipelines observed: "
                    f"{_report_count(scheduler.get('max_active_pipelines_observed'))}/"
                    f"{_report_count(scheduler.get('max_eval_active_observed'))}"
                ),
                "",
            ]
        )
        timeseries_path = str(scheduler.get("timeseries_path") or "").strip()
        if timeseries_path:
            lines.extend(
                [
                    (
                        "- Scheduler time-series: "
                        f"{timeseries_path} "
                        f"({ _report_count(scheduler.get('timeseries_row_count')) } rows, "
                        f"poll { _report_metric(scheduler.get('snapshot_poll_seconds')):.2f}s, "
                        f"heartbeat { _report_metric(scheduler.get('timeseries_heartbeat_seconds')):.2f}s)"
                    ),
                    (
                        "- CPU utilization samples/source: "
                        f"{ _report_count(scheduler.get('cpu_utilization_samples')) }/"
                        f"{scheduler.get('cpu_utilization_source', 'unavailable')}"
                    ),
                    "",
                ]
            )

    lines.extend(
        [
            "## Ranked Configurations",
            "",
        ]
    )

    variants = report_payload.get("variants")
    if not isinstance(variants, list) or not variants:
        lines.append("- No variant results were recorded.")
        lines.append("")
        return "\n".join(lines)

    for row in variants:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        config_dir = str(row.get("config_dir") or "").strip() or "<unknown>"
        if status != "ok":
            lines.append(f"- {config_dir}: FAILED ({row.get('error', 'unknown error')})")
            continue
        rank_value = row.get("rank")
        rank_prefix = f"{rank_value}. " if rank_value is not None else ""
        eval_source = str(row.get("evaluation_result_source") or "").strip()
        row_timing = _normalize_timing_payload(row.get("timing"))
        row_seconds = _report_optional_metric(row_timing.get("total_seconds"))
        timing_suffix = f", time={row_seconds:.2f}s" if row_seconds is not None else ""
        eval_source_suffix = f", eval_source={eval_source}" if eval_source else ""
        lines.append(
            (
                f"- {rank_prefix}{config_dir} "
                f"(precision={_report_metric(row.get('precision')):.3f}, "
                f"recall={_report_metric(row.get('recall')):.3f}, "
                f"f1={_report_metric(row.get('f1')):.3f}, "
                f"practical_f1={_report_metric(row.get('practical_f1')):.3f}"
                f"{timing_suffix}{eval_source_suffix}) "
                f"[hash={row.get('run_config_hash', '')}]"
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_all_method_multi_source_report_md(report_payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "# All Method Benchmark Multi-Source Report",
        "",
        f"- Created at: {report_payload.get('created_at', '')}",
        f"- Eval mode: {report_payload.get('eval_mode', BENCHMARK_EVAL_MODE_CANONICAL_TEXT)}",
        f"- Scheduler scope: {report_payload.get('scheduler_scope', 'per_source')}",
        f"- Matched targets: {report_payload.get('matched_target_count', 0)}",
        f"- Unmatched targets: {report_payload.get('unmatched_target_count', 0)}",
        (
            "- Source parallelism configured/effective: "
            f"{_report_count(report_payload.get('source_parallelism_configured'))}/"
            f"{_report_count(report_payload.get('source_parallelism_effective'))}"
        ),
        (
            "- Source scheduling strategy: "
            f"{report_payload.get('source_schedule_strategy', ALL_METHOD_SOURCE_SCHEDULING_DISCOVERY)}"
        ),
        (
            "- Planned source jobs: "
            f"{_report_count(report_payload.get('source_job_count_planned'))}"
        ),
        (
            "- Source sharding threshold/max-parts/min-variants: "
            f"{_report_metric(report_payload.get('source_shard_threshold_seconds')):.1f}/"
            f"{_report_count(report_payload.get('source_shard_max_parts'))}/"
            f"{_report_count(report_payload.get('source_shard_min_variants'))}"
        ),
        f"- Planned config runs: {report_payload.get('total_config_runs_planned', 0)}",
        f"- Completed config runs: {report_payload.get('total_config_runs_completed', 0)}",
        f"- Successful config runs: {report_payload.get('total_config_runs_successful', 0)}",
        (
            "- Global queue planned/completed/failed configs: "
            f"{_report_count(report_payload.get('global_queue_planned_configs'))}/"
            f"{_report_count(report_payload.get('global_queue_completed_configs'))}/"
            f"{_report_count(report_payload.get('global_queue_failed_configs'))}"
        ),
        (
            "- Evaluation signatures unique / runs executed: "
            f"{_report_count(report_payload.get('evaluation_signatures_unique'))}/"
            f"{_report_count(report_payload.get('evaluation_runs_executed'))}"
        ),
        (
            "- Evaluation results reused in-run/cross-run: "
            f"{_report_count(report_payload.get('evaluation_results_reused_in_run'))}/"
            f"{_report_count(report_payload.get('evaluation_results_reused_cross_run'))}"
        ),
        (
            "- Prediction signatures unique / runs executed / reused in-run/cross-run: "
            f"{_report_count(report_payload.get('prediction_signatures_unique'))}/"
            f"{_report_count(report_payload.get('prediction_runs_executed'))}/"
            f"{_report_count(report_payload.get('prediction_results_reused_in_run'))}/"
            f"{_report_count(report_payload.get('prediction_results_reused_cross_run'))}"
        ),
        (
            "- Split/convert input groups / reuse candidates / safe / blocked: "
            f"{_report_count(report_payload.get('split_convert_input_groups'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_candidates'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_safe_candidates'))}/"
            f"{_report_count(report_payload.get('split_convert_reuse_blocked_by_prediction_variance'))}"
        ),
        (
            "- Config timeout / failed-config retry limit: "
            f"{('off' if report_payload.get('config_timeout_seconds') is None else str(_report_count(report_payload.get('config_timeout_seconds'))) + 's')}/"
            f"{_report_count(report_payload.get('retry_failed_configs_requested'))}"
        ),
    ]
    cache_root = str(report_payload.get("canonical_alignment_cache_root") or "").strip()
    if cache_root:
        lines.append(f"- Canonical alignment cache root: {cache_root}")

    timing_summary = report_payload.get("timing_summary")
    if isinstance(timing_summary, dict):
        lines.extend(
            [
                (
                    "- Run wall time: "
                    f"{_report_metric(timing_summary.get('run_wall_seconds')):.2f}s"
                ),
                (
                    "- Sum source wall times: "
                    f"{_report_metric(timing_summary.get('source_total_seconds')):.2f}s"
                ),
            ]
        )
        source_average = _report_optional_metric(
            timing_summary.get("source_average_seconds")
        )
        if source_average is not None:
            lines.append(f"- Average source runtime: {source_average:.2f}s")
        config_average = _report_optional_metric(
            timing_summary.get("config_average_seconds")
        )
        if config_average is not None:
            lines.append(f"- Average config runtime: {config_average:.2f}s")
        slowest_source_name = str(timing_summary.get("slowest_source") or "").strip()
        slowest_source_seconds = _report_optional_metric(
            timing_summary.get("slowest_source_seconds")
        )
        if slowest_source_name and slowest_source_seconds is not None:
            lines.append(
                f"- Slowest source: {slowest_source_name} ({slowest_source_seconds:.2f}s)"
            )
        slowest_config_name = str(timing_summary.get("slowest_config") or "").strip()
        slowest_config_seconds = _report_optional_metric(
            timing_summary.get("slowest_config_seconds")
        )
        if slowest_config_name and slowest_config_seconds is not None:
            lines.append(
                f"- Slowest config: {slowest_config_name} ({slowest_config_seconds:.2f}s)"
            )
    scheduler_summary = report_payload.get("scheduler_summary")
    if isinstance(scheduler_summary, dict):
        lines.extend(
            [
                (
                    "- Scheduler mode: "
                    f"{scheduler_summary.get('mode', 'fixed')} "
                    f"(sources { _report_count(scheduler_summary.get('source_count'))})"
                ),
                (
                    "- Scheduler effective inflight / split slots / wing target: "
                    f"{_report_count(scheduler_summary.get('effective_inflight_pipelines'))}/"
                    f"{_report_count(scheduler_summary.get('split_phase_slots'))}/"
                    f"{_report_count(scheduler_summary.get('wing_backlog_target'))}"
                ),
                (
                    "- Scheduler eval-tail headroom mode configured/effective: "
                    f"{scheduler_summary.get('eval_tail_headroom_mode', 'auto')} "
                    f"{_report_count(scheduler_summary.get('eval_tail_headroom_configured'))}/"
                    f"{_report_count(scheduler_summary.get('eval_tail_headroom_effective'))}"
                ),
                (
                    "- Scheduler max active during eval: "
                    f"{_report_count(scheduler_summary.get('max_active_during_eval'))}"
                ),
                (
                    "- Scheduler split worker cap per active config (cpu/memory): "
                    f"{_report_count(scheduler_summary.get('split_worker_cap_per_config'))}/"
                    f"{_report_count(scheduler_summary.get('split_worker_cap_by_cpu'))}/"
                    f"{_report_count(scheduler_summary.get('split_worker_cap_by_memory'))}"
                ),
                (
                    "- Scheduler heavy utilization: "
                    f"{_report_metric(scheduler_summary.get('heavy_slot_utilization_pct')):.1f}% "
                    f"(busy {_report_metric(scheduler_summary.get('heavy_slot_busy_seconds')):.2f}s / "
                    f"capacity {_report_metric(scheduler_summary.get('heavy_slot_capacity_seconds')):.2f}s)"
                ),
                (
                    "- Scheduler wing avg/max: "
                    f"{_report_metric(scheduler_summary.get('avg_wing_backlog')):.2f}/"
                    f"{_report_count(scheduler_summary.get('max_wing_backlog'))}"
                ),
                (
                    "- Scheduler heavy idle gap while pending: "
                    f"{_report_metric(scheduler_summary.get('idle_gap_seconds')):.2f}s"
                ),
                (
                    "- Scheduler max active/eval pipelines observed: "
                    f"{_report_count(scheduler_summary.get('max_active_pipelines_observed'))}/"
                    f"{_report_count(scheduler_summary.get('max_eval_active_observed'))}"
                ),
                (
                    "- Scheduler timeout / retry limit: "
                    f"{('off' if scheduler_summary.get('config_timeout_seconds') is None else str(_report_count(scheduler_summary.get('config_timeout_seconds'))) + 's')}/"
                    f"{_report_count(scheduler_summary.get('failed_retry_limit'))}"
                ),
            ]
        )
    lines.extend(
        [
        "",
        "## Per-Source Results",
        "",
        ]
    )

    source_rows = report_payload.get("sources")
    if not isinstance(source_rows, list) or not source_rows:
        lines.extend(["- No source runs were recorded.", ""])
    else:
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().lower()
            source_file = str(row.get("source_file") or "").strip() or "<unknown>"
            if status != "ok":
                lines.append(
                    f"- {source_file}: FAILED ({row.get('error', 'unknown error')})"
                )
                continue
            winner_metrics = row.get("winner_metrics")
            precision = _report_metric(
                winner_metrics.get("precision")
                if isinstance(winner_metrics, dict)
                else None
            )
            recall = _report_metric(
                winner_metrics.get("recall")
                if isinstance(winner_metrics, dict)
                else None
            )
            f1 = _report_metric(
                winner_metrics.get("f1")
                if isinstance(winner_metrics, dict)
                else None
            )
            source_timing = row.get("timing_summary")
            source_timing_suffix = ""
            if isinstance(source_timing, dict):
                source_seconds = _report_optional_metric(
                    source_timing.get("source_wall_seconds")
                )
                slowest_config = str(source_timing.get("slowest_config_dir") or "").strip()
                slowest_seconds = _report_optional_metric(
                    source_timing.get("slowest_config_seconds")
                )
                if source_seconds is not None:
                    source_timing_suffix += f", runtime={source_seconds:.2f}s"
                if slowest_config and slowest_seconds is not None:
                    source_timing_suffix += (
                        f", slowest={slowest_config} ({slowest_seconds:.2f}s)"
                    )
            shard_total = max(1, _report_count(row.get("source_shard_total")))
            if shard_total > 1:
                source_timing_suffix += f", shards={shard_total}"
            lines.append(
                (
                    f"- {source_file}: ok "
                    f"(winner precision={precision:.3f}, "
                    f"recall={recall:.3f}, f1={f1:.3f}{source_timing_suffix}) "
                    f"[report={row.get('report_path', '')}]"
                )
            )
        lines.append("")

    lines.extend(["## Unmatched Gold Exports", ""])
    unmatched_rows = report_payload.get("unmatched")
    if not isinstance(unmatched_rows, list) or not unmatched_rows:
        lines.extend(["- None", ""])
    else:
        for row in unmatched_rows:
            if not isinstance(row, dict):
                continue
            source_hint_text = str(row.get("source_hint") or "none")
            lines.append(
                (
                    f"- {row.get('gold_display', row.get('gold_spans_path', ''))}: "
                    f"{row.get('reason', '')} (source hint: {source_hint_text})"
                )
            )
        lines.append("")

    return "\n".join(lines)


def _write_all_method_source_reports_from_global_rows(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    source_job_plans: list[_AllMethodSourceJobPlan],
    root_output_dir: Path,
    processed_output_root: Path,
    successful_rows: list[dict[str, Any]],
    failed_rows: list[dict[str, Any]],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    eval_signature_cache_dir: Path,
    scheduler_summary: dict[str, Any],
    retry_failed_configs_requested: int,
    retry_passes_executed: int,
    retry_recovered_configs: int,
) -> list[dict[str, Any]]:
    grouped_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in successful_rows + failed_rows:
        grouped_rows[_report_count(row.get("source_position"))].append(dict(row))

    source_plans_by_position: dict[int, list[_AllMethodSourceJobPlan]] = defaultdict(list)
    for plan in source_job_plans:
        source_plans_by_position[plan.source_position].append(plan)

    source_rows: list[dict[str, Any]] = []
    for source_position, (target, variants) in enumerate(target_variants):
        plan_rows = sorted(
            source_plans_by_position.get(source_position, []),
            key=lambda plan: (plan.shard_index, plan.source_slug),
        )
        source_group_key = (
            plan_rows[0].source_group_key
            if plan_rows
            else slugify_name(target.source_file.stem)
        )
        source_rows_for_position = sorted(
            grouped_rows.get(source_position, []),
            key=lambda row: _report_count(
                row.get("source_config_index", row.get("config_index"))
            ),
        )
        cleaned_rows: list[dict[str, Any]] = []
        for row in source_rows_for_position:
            cleaned = {
                key: value
                for key, value in row.items()
                if not str(key).startswith("_")
            }
            cleaned_rows.append(cleaned)

        successful_source_rows = [
            row
            for row in cleaned_rows
            if str(row.get("status") or "").strip().lower() == "ok"
        ]
        failed_source_rows = [
            row
            for row in cleaned_rows
            if str(row.get("status") or "").strip().lower() != "ok"
        ]
        successful_source_rows.sort(
            key=lambda row: (
                _report_metric(row.get("f1")),
                _report_metric(row.get("practical_f1")),
                _report_metric(row.get("precision")),
                _report_metric(row.get("recall")),
            ),
            reverse=True,
        )
        for rank, row in enumerate(successful_source_rows, start=1):
            row["rank"] = rank
        final_rows = successful_source_rows + failed_source_rows

        evaluation_signatures_unique = len(
            {
                str(row.get("eval_signature") or "").strip()
                for row in successful_source_rows
                if str(row.get("eval_signature") or "").strip()
            }
        )
        evaluation_runs_executed = sum(
            1
            for row in successful_source_rows
            if str(row.get("evaluation_result_source") or "").strip().lower()
            == "executed"
        )
        evaluation_results_reused_in_run = sum(
            1
            for row in successful_source_rows
            if str(row.get("evaluation_result_source") or "").strip().lower()
            == "reused_in_run"
        )
        evaluation_results_reused_cross_run = sum(
            1
            for row in successful_source_rows
            if str(row.get("evaluation_result_source") or "").strip().lower()
            == "reused_cross_run"
        )
        prediction_reuse_summary = _all_method_prediction_reuse_summary(
            successful_source_rows
        )

        successful_timing: list[tuple[dict[str, Any], float]] = []
        for row in successful_source_rows:
            row_timing = _normalize_timing_payload(row.get("timing"))
            row_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
            if row_total_seconds is None:
                row_total_seconds = _report_optional_metric(row.get("duration_seconds"))
            if row_total_seconds is None:
                continue
            row["timing"] = _timing_with_updates(row_timing, total_seconds=row_total_seconds)
            successful_timing.append((row, row_total_seconds))

        total_config_seconds = sum(seconds for _row, seconds in successful_timing)
        average_config_seconds = (
            total_config_seconds / len(successful_timing) if successful_timing else None
        )
        median_config_seconds = _median_metric(
            [seconds for _row, seconds in successful_timing]
        )
        slowest_config_row = (
            max(successful_timing, key=lambda item: item[1])[0]
            if successful_timing
            else None
        )
        slowest_config_seconds = (
            max(seconds for _row, seconds in successful_timing)
            if successful_timing
            else None
        )

        source_wall_seconds = _report_metric(
            sum(
                _report_optional_metric(
                    _normalize_timing_payload(row.get("timing")).get(
                        "all_method_prediction_wall_seconds"
                    )
                )
                or 0.0
                for row in final_rows
            )
        )
        if source_wall_seconds <= 0.0:
            source_wall_seconds = total_config_seconds

        winner = successful_source_rows[0] if successful_source_rows else None
        report_payload: dict[str, Any] = {
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "source_file": str(target.source_file),
            "gold_spans_path": str(target.gold_spans_path),
            "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
            "variant_count": len(variants),
            "successful_variants": len(successful_source_rows),
            "failed_variants": len(failed_source_rows),
            "evaluation_signatures_unique": evaluation_signatures_unique,
            "evaluation_runs_executed": evaluation_runs_executed,
            "evaluation_results_reused_in_run": evaluation_results_reused_in_run,
            "evaluation_results_reused_cross_run": evaluation_results_reused_cross_run,
            "prediction_signatures_unique": _report_count(
                prediction_reuse_summary.get("prediction_signatures_unique")
            ),
            "prediction_runs_executed": _report_count(
                prediction_reuse_summary.get("prediction_runs_executed")
            ),
            "prediction_results_reused_in_run": _report_count(
                prediction_reuse_summary.get("prediction_results_reused_in_run")
            ),
            "prediction_results_reused_cross_run": _report_count(
                prediction_reuse_summary.get("prediction_results_reused_cross_run")
            ),
            "split_convert_input_groups": _report_count(
                prediction_reuse_summary.get("split_convert_input_groups")
            ),
            "split_convert_reuse_candidates": _report_count(
                prediction_reuse_summary.get("split_convert_reuse_candidates")
            ),
            "split_convert_reuse_safe_candidates": _report_count(
                prediction_reuse_summary.get("split_convert_reuse_safe_candidates")
            ),
            "split_convert_reuse_blocked_by_prediction_variance": _report_count(
                prediction_reuse_summary.get(
                    "split_convert_reuse_blocked_by_prediction_variance"
                )
            ),
            "prediction_reuse_key_schema_version": (
                ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION
            ),
            "split_convert_input_key_schema_version": (
                ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION
            ),
            "evaluation_signature_cache_dir": str(eval_signature_cache_dir),
            "retry_failed_configs_requested": retry_failed_configs_requested,
            "retry_passes_executed": retry_passes_executed,
            "retry_recovered_configs": retry_recovered_configs,
            "include_codex_farm_requested": include_codex_farm_requested,
            "include_codex_farm_effective": include_codex_farm_effective,
            "timing_summary": {
                "source_wall_seconds": source_wall_seconds,
                "config_total_seconds": total_config_seconds,
                "config_average_seconds": average_config_seconds,
                "config_median_seconds": median_config_seconds,
                "slowest_config_dir": (
                    str(slowest_config_row.get("config_dir"))
                    if isinstance(slowest_config_row, dict)
                    else None
                ),
                "slowest_config_seconds": slowest_config_seconds,
            },
            "scheduler": dict(scheduler_summary),
            "variants": final_rows,
            "winner_by_f1": winner,
            "scheduler_scope": "global_config_queue",
        }

        source_root = root_output_dir / source_group_key
        source_root.mkdir(parents=True, exist_ok=True)
        report_json_path = source_root / "all_method_benchmark_report.json"
        report_json_path.write_text(
            json.dumps(report_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        report_md_path = source_root / "all_method_benchmark_report.md"
        report_md_path.write_text(
            _render_all_method_report_md(report_payload),
            encoding="utf-8",
        )

        source_shard_payload = [
            {
                "status": "ok",
                "source_slug": plan.source_slug,
                "source_shard_index": plan.shard_index + 1,
                "source_shard_total": max(1, _report_count(plan.shard_total)),
                "source_estimated_seconds": plan.estimated_seconds,
                "source_estimate_basis": plan.estimate_basis,
                "variant_count_planned": len(plan.variants),
                "variant_count_completed": len(
                    [
                        row
                        for row in cleaned_rows
                        if _report_count(row.get("source_shard_index"))
                        == (plan.shard_index + 1)
                    ]
                ),
                "variant_count_successful": len(
                    [
                        row
                        for row in successful_source_rows
                        if _report_count(row.get("source_shard_index"))
                        == (plan.shard_index + 1)
                    ]
                ),
                "evaluation_signatures_unique": len(
                    {
                        str(row.get("eval_signature") or "").strip()
                        for row in successful_source_rows
                        if _report_count(row.get("source_shard_index"))
                        == (plan.shard_index + 1)
                        and str(row.get("eval_signature") or "").strip()
                    }
                ),
                "evaluation_runs_executed": sum(
                    1
                    for row in successful_source_rows
                    if _report_count(row.get("source_shard_index"))
                    == (plan.shard_index + 1)
                    and str(row.get("evaluation_result_source") or "").strip().lower()
                    == "executed"
                ),
                "evaluation_results_reused_in_run": sum(
                    1
                    for row in successful_source_rows
                    if _report_count(row.get("source_shard_index"))
                    == (plan.shard_index + 1)
                    and str(row.get("evaluation_result_source") or "").strip().lower()
                    == "reused_in_run"
                ),
                "evaluation_results_reused_cross_run": sum(
                    1
                    for row in successful_source_rows
                    if _report_count(row.get("source_shard_index"))
                    == (plan.shard_index + 1)
                    and str(row.get("evaluation_result_source") or "").strip().lower()
                    == "reused_cross_run"
                ),
                "report_path": _path_for_manifest(root_output_dir, report_md_path) or "",
                "report_json_path": _path_for_manifest(root_output_dir, report_json_path)
                or "",
                "error": "",
                "timing_summary": {},
            }
            for plan in plan_rows
        ]
        error_messages = [
            str(row.get("error") or "").strip() for row in failed_source_rows if str(row.get("error") or "").strip()
        ]
        winner_metrics = {}
        if isinstance(winner, dict):
            winner_metrics = {
                "precision": _report_metric(winner.get("precision")),
                "recall": _report_metric(winner.get("recall")),
                "f1": _report_metric(winner.get("f1")),
            }
        source_rows.append(
            {
                "status": "ok" if not failed_source_rows else "failed",
                "source_position": source_position,
                "source_group_key": source_group_key,
                "source_shard_index": 1,
                "source_shard_total": max(1, len(plan_rows)),
                "source_estimated_seconds": _report_metric(
                    sum(float(plan.estimated_seconds) for plan in plan_rows)
                ),
                "source_estimate_basis": (
                    "+".join(
                        sorted(
                            {
                                str(plan.estimate_basis).strip()
                                for plan in plan_rows
                                if str(plan.estimate_basis).strip()
                            }
                        )
                    )
                    or "unknown"
                ),
                "source_file": str(target.source_file),
                "source_file_name": target.source_file_name,
                "gold_spans_path": str(target.gold_spans_path),
                "gold_display": target.gold_display,
                "source_slug": source_group_key,
                "report_path": _path_for_manifest(root_output_dir, report_md_path) or "",
                "report_json_path": _path_for_manifest(root_output_dir, report_json_path)
                or "",
                "report_paths": [_path_for_manifest(root_output_dir, report_md_path) or ""],
                "report_json_paths": [
                    _path_for_manifest(root_output_dir, report_json_path) or ""
                ],
                "variant_count_planned": len(variants),
                "variant_count_completed": len(cleaned_rows),
                "variant_count_successful": len(successful_source_rows),
                "evaluation_signatures_unique": evaluation_signatures_unique,
                "evaluation_runs_executed": evaluation_runs_executed,
                "evaluation_results_reused_in_run": evaluation_results_reused_in_run,
                "evaluation_results_reused_cross_run": evaluation_results_reused_cross_run,
                "prediction_signatures_unique": _report_count(
                    prediction_reuse_summary.get("prediction_signatures_unique")
                ),
                "prediction_runs_executed": _report_count(
                    prediction_reuse_summary.get("prediction_runs_executed")
                ),
                "prediction_results_reused_in_run": _report_count(
                    prediction_reuse_summary.get("prediction_results_reused_in_run")
                ),
                "prediction_results_reused_cross_run": _report_count(
                    prediction_reuse_summary.get("prediction_results_reused_cross_run")
                ),
                "split_convert_input_groups": _report_count(
                    prediction_reuse_summary.get("split_convert_input_groups")
                ),
                "split_convert_reuse_candidates": _report_count(
                    prediction_reuse_summary.get("split_convert_reuse_candidates")
                ),
                "split_convert_reuse_safe_candidates": _report_count(
                    prediction_reuse_summary.get("split_convert_reuse_safe_candidates")
                ),
                "split_convert_reuse_blocked_by_prediction_variance": _report_count(
                    prediction_reuse_summary.get(
                        "split_convert_reuse_blocked_by_prediction_variance"
                    )
                ),
                "winner_metrics": winner_metrics,
                "timing_summary": dict(report_payload.get("timing_summary") or {}),
                "scheduler": dict(scheduler_summary),
                "source_shards": source_shard_payload,
                "error": " | ".join(error_messages),
            }
        )
    _ = processed_output_root
    return source_rows


def _run_all_method_benchmark_global_queue(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    unmatched_targets: list[AllMethodUnmatchedGold],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    canonical_alignment_cache_root: Path | None = None,
    prediction_reuse_cache_root: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    run_started = time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)

    effective_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    effective_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )
    resolved_source_scheduling = _normalize_all_method_source_scheduling(
        source_scheduling
    )
    resolved_source_shard_threshold_seconds = (
        _coerce_positive_float(source_shard_threshold_seconds)
        or ALL_METHOD_SOURCE_SHARD_THRESHOLD_SECONDS_DEFAULT
    )
    resolved_source_shard_max_parts = (
        _coerce_positive_int(source_shard_max_parts)
        or ALL_METHOD_SOURCE_SHARD_MAX_PARTS_DEFAULT
    )
    resolved_source_shard_min_variants = (
        _coerce_positive_int(source_shard_min_variants)
        or ALL_METHOD_SOURCE_SHARD_MIN_VARIANTS_DEFAULT
    )
    resolved_canonical_cache_root = (
        canonical_alignment_cache_root.expanduser()
        if canonical_alignment_cache_root is not None
        else _resolve_all_method_canonical_alignment_cache_root(
            root_output_dir=root_output_dir
        )
    )
    resolved_prediction_reuse_cache_root = (
        prediction_reuse_cache_root.expanduser()
        if prediction_reuse_cache_root is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    )
    resolved_dashboard_output_root = (
        dashboard_output_root.expanduser()
        if dashboard_output_root is not None
        else None
    )

    total_targets = len(target_variants)
    source_job_plans = _plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy=resolved_source_scheduling,
        shard_threshold_seconds=resolved_source_shard_threshold_seconds,
        shard_max_parts=resolved_source_shard_max_parts,
        shard_min_variants=resolved_source_shard_min_variants,
    )
    work_items = _plan_all_method_global_work_items(
        target_variants=target_variants,
        scheduling_strategy=resolved_source_scheduling,
        shard_threshold_seconds=resolved_source_shard_threshold_seconds,
        shard_max_parts=resolved_source_shard_max_parts,
        shard_min_variants=resolved_source_shard_min_variants,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        canonical_alignment_cache_root=resolved_canonical_cache_root,
    )
    total_planned_config_runs = len(work_items)
    source_parallelism_default = min(
        _all_method_default_parallel_sources_from_cpu(),
        max(1, total_targets),
    )
    requested_source_parallelism = _report_count(max_parallel_sources)
    source_parallelism_configured = (
        requested_source_parallelism
        if requested_source_parallelism > 0
        else source_parallelism_default
    )
    source_parallelism_effective = _resolve_all_method_source_parallelism(
        total_sources=max(1, total_targets),
        requested=max_parallel_sources,
    )

    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=max(1, total_planned_config_runs),
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=1,
    )
    configured_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    requested_split_phase_slots = scheduler_runtime.split_phase_slots_requested
    effective_split_phase_slots = scheduler_runtime.split_phase_slots
    split_phase_slot_mode = scheduler_runtime.split_phase_slot_mode
    split_phase_slot_cap_by_cpu = scheduler_runtime.split_phase_slot_cap_by_cpu
    split_phase_slot_cap_by_memory = scheduler_runtime.split_phase_slot_cap_by_memory
    effective_wing_backlog_target = scheduler_runtime.wing_backlog_target
    configured_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_configured
    effective_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_effective
    eval_tail_headroom_mode = scheduler_runtime.eval_tail_headroom_mode
    effective_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    max_active_during_eval = scheduler_runtime.max_active_during_eval
    effective_inflight_pipelines = scheduler_runtime.effective_inflight_pipelines
    adaptive_overcommit_limit = scheduler_runtime.adaptive_overcommit_limit
    adaptive_max_guard_target = scheduler_runtime.adaptive_max_guard_target
    scheduler_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    scheduler_cpu_budget_total = scheduler_runtime.cpu_budget_total
    split_worker_cap_per_config, split_worker_guard = _resolve_all_method_split_worker_cap(
        split_phase_slots=effective_split_phase_slots,
        source_parallelism_effective=1,
    )

    max_requested_split_workers = max(
        [
            max(
                max(1, _report_count(item.variant.run_settings.workers)),
                max(1, _report_count(item.variant.run_settings.pdf_split_workers)),
                max(1, _report_count(item.variant.run_settings.epub_split_workers)),
            )
            for item in work_items
        ],
        default=1,
    )

    split_phase_gate_dir = root_output_dir / ".split_phase_slots"
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    scheduler_events_dir = root_output_dir / ".scheduler_events"
    scheduler_timeseries_path = root_output_dir / ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    if scheduler_events_dir.exists():
        shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    if scheduler_timeseries_path.exists():
        scheduler_timeseries_path.unlink()

    status_lock = threading.RLock()
    source_totals: dict[int, int] = {
        source_position: len(variants)
        for source_position, (_target, variants) in enumerate(target_variants)
    }
    source_active: dict[int, int] = defaultdict(int)
    source_completed: dict[int, int] = defaultdict(int)
    source_failed_seen: dict[int, bool] = defaultdict(bool)

    def _emit_status(
        message: str,
        *,
        color: typer.colors = typer.colors.CYAN,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned:
            return
        with status_lock:
            if progress_callback is not None:
                if dashboard is not None:
                    dashboard.set_task(cleaned)
                    _notify_progress_callback(progress_callback, dashboard.render())
                else:
                    _notify_progress_callback(progress_callback, cleaned)
                return
            typer.secho(cleaned, fg=color)

    if split_phase_slot_mode != "configured":
        _emit_status(
            (
                "Resource guard capped split slots to "
                f"{effective_split_phase_slots} "
                f"(requested {requested_split_phase_slots}; "
                f"cpu cap {split_phase_slot_cap_by_cpu}; "
                f"memory cap {split_phase_slot_cap_by_memory})."
            ),
            color=typer.colors.YELLOW,
        )

    if split_worker_cap_per_config < max_requested_split_workers:
        _emit_status(
            (
                "Resource guard capped split workers per active config to "
                f"{split_worker_cap_per_config} "
                f"(requested peak {max_requested_split_workers}; "
                f"split slots {effective_split_phase_slots})."
            ),
            color=typer.colors.YELLOW,
        )

    scheduler_phase_by_config: dict[int, str] = {}
    scheduler_event_offsets: dict[int, int] = {}
    scheduler_last_tick = time.monotonic()
    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_last_snapshot = ""
    scheduler_timeseries_last_snapshot = ""
    scheduler_timeseries_last_write_monotonic = run_started
    scheduler_timeseries_rows_written = 0
    scheduler_timeseries_heartbeat_seconds = max(
        ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS,
        ALL_METHOD_SCHEDULER_POLL_SECONDS,
    )
    scheduler_cpu_source = "proc_stat_linux"
    scheduler_cpu_samples_collected = 0
    scheduler_cpu_totals_last: tuple[int, int] | None = None
    scheduler_cpu_utilization_pct_last: float | None = None
    scheduler_cpu_utilization_pct_high_water = 0.0
    scheduler_admission_adjustments = 0
    scheduler_admission_pressure_boosts = 0
    scheduler_admission_saturation_clamps = 0
    scheduler_admission_cpu_hot_clamps = 0
    scheduler_admission_active_cap_peak = configured_inflight_pipelines
    scheduler_admission_guard_target_peak = min(
        max(1, total_planned_config_runs),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_last_key: tuple[int, int, str] | None = None
    scheduler_admission_active_cap_current = configured_inflight_pipelines
    scheduler_admission_guard_target_current = min(
        max(1, total_planned_config_runs),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_wing_target_current = effective_wing_backlog_target
    scheduler_admission_reason_current = "base"
    process_worker_probe_available: bool | None = None
    process_worker_probe_error: str | None = None
    config_executor_backends_seen: set[str] = set()

    def _scheduler_event_path(config_index: int) -> Path:
        return scheduler_events_dir / f"config_{config_index:03d}.jsonl"

    def _read_linux_cpu_totals() -> tuple[int, int] | None:
        try:
            with Path("/proc/stat").open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return None
        line = str(first_line or "").strip()
        if not line:
            return None
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        values: list[int] = []
        for token in parts[1:]:
            try:
                values.append(int(token))
            except ValueError:
                return None
        if len(values) < 4:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle

    def _sample_host_cpu_utilization_pct() -> float | None:
        nonlocal scheduler_cpu_source
        nonlocal scheduler_cpu_samples_collected
        nonlocal scheduler_cpu_totals_last

        current = _read_linux_cpu_totals()
        if current is None:
            scheduler_cpu_source = "unavailable"
            scheduler_cpu_totals_last = None
            return None
        previous = scheduler_cpu_totals_last
        scheduler_cpu_totals_last = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        busy_delta = max(0, total_delta - max(0, idle_delta))
        scheduler_cpu_samples_collected += 1
        return max(0.0, min(100.0, (float(busy_delta) / float(total_delta)) * 100.0))

    def _scheduler_phase_for_event(event_name: str) -> str | None:
        event = str(event_name or "").strip()
        if event in {"config_started", "prep_started"}:
            return "prep"
        if event == "split_wait_started":
            return "split_wait"
        if event == "split_active_started":
            return "split_active"
        if event in {"split_active_finished", "post_started"}:
            return "post"
        if event in {"post_finished", "evaluate_started"}:
            return "evaluate"
        if event in {"evaluate_finished", "config_finished"}:
            return "done"
        return None

    def _poll_scheduler_events(active_indices: set[int]) -> None:
        for active_index in sorted(active_indices):
            event_path = _scheduler_event_path(active_index)
            if not event_path.exists():
                continue
            offset = max(0, scheduler_event_offsets.get(active_index, 0))
            with event_path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    phase = _scheduler_phase_for_event(str(payload.get("event") or ""))
                    if phase is not None:
                        scheduler_phase_by_config[active_index] = phase
                scheduler_event_offsets[active_index] = handle.tell()

    def _compute_scheduler_counts(active_indices: set[int]) -> dict[str, int]:
        heavy_active = 0
        split_wait = 0
        prep_active = 0
        post_active = 0
        evaluate_active = 0
        for active_index in active_indices:
            phase = scheduler_phase_by_config.get(active_index, "prep")
            if phase == "split_active":
                heavy_active += 1
            elif phase == "split_wait":
                split_wait += 1
            elif phase == "post":
                post_active += 1
            elif phase == "evaluate":
                evaluate_active += 1
            elif phase == "done":
                continue
            else:
                prep_active += 1
        wing_backlog = split_wait + prep_active
        return {
            "heavy_active": heavy_active,
            "split_wait": split_wait,
            "prep_active": prep_active,
            "post_active": post_active,
            "evaluate_active": evaluate_active,
            "wing_backlog": wing_backlog,
            "active": len(active_indices),
        }

    def _tick_scheduler_metrics(*, active_indices: set[int], pending_count: int) -> dict[str, int]:
        nonlocal scheduler_last_tick
        nonlocal scheduler_capacity_seconds
        nonlocal scheduler_busy_seconds
        nonlocal scheduler_idle_gap_seconds
        nonlocal scheduler_wing_area_seconds
        nonlocal scheduler_max_wing_backlog
        nonlocal scheduler_max_active_pipelines
        nonlocal scheduler_max_eval_active
        nonlocal scheduler_cpu_utilization_pct_last
        nonlocal scheduler_cpu_utilization_pct_high_water

        now = time.monotonic()
        delta = max(0.0, now - scheduler_last_tick)
        counts = _compute_scheduler_counts(active_indices)
        scheduler_capacity_seconds += float(effective_split_phase_slots) * delta
        scheduler_busy_seconds += float(
            min(effective_split_phase_slots, counts["heavy_active"])
        ) * delta
        if pending_count > 0 and counts["heavy_active"] < effective_split_phase_slots:
            scheduler_idle_gap_seconds += delta
        scheduler_wing_area_seconds += float(counts["wing_backlog"]) * delta
        scheduler_max_wing_backlog = max(scheduler_max_wing_backlog, counts["wing_backlog"])
        scheduler_max_active_pipelines = max(
            scheduler_max_active_pipelines,
            counts["active"],
        )
        scheduler_max_eval_active = max(
            scheduler_max_eval_active,
            counts["evaluate_active"],
        )
        sampled_cpu = _sample_host_cpu_utilization_pct()
        if sampled_cpu is not None:
            scheduler_cpu_utilization_pct_last = sampled_cpu
            scheduler_cpu_utilization_pct_high_water = max(
                scheduler_cpu_utilization_pct_high_water,
                sampled_cpu,
            )
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return (
            f"scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} "
            f"| wing {counts['wing_backlog']} "
            f"| eval {counts['evaluate_active']} "
            f"| active {counts['active']} | pending {max(0, pending_count)}"
        )

    def _write_scheduler_timeseries_row(
        *,
        counts: dict[str, int],
        pending_count: int,
        force: bool = False,
    ) -> None:
        nonlocal scheduler_timeseries_last_snapshot
        nonlocal scheduler_timeseries_last_write_monotonic
        nonlocal scheduler_timeseries_rows_written

        pending_safe = max(0, pending_count)
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_safe)
        now_monotonic = time.monotonic()
        write_due = (
            force
            or snapshot != scheduler_timeseries_last_snapshot
            or (
                now_monotonic - scheduler_timeseries_last_write_monotonic
                >= scheduler_timeseries_heartbeat_seconds
            )
        )
        if not write_due:
            return
        row = {
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": now_monotonic,
            "elapsed_seconds": max(0.0, now_monotonic - run_started),
            "snapshot": snapshot,
            "heavy_active": _report_count(counts.get("heavy_active")),
            "heavy_capacity": _report_count(effective_split_phase_slots),
            "split_wait": _report_count(counts.get("split_wait")),
            "prep_active": _report_count(counts.get("prep_active")),
            "post_active": _report_count(counts.get("post_active")),
            "evaluate_active": _report_count(counts.get("evaluate_active")),
            "wing_backlog": _report_count(counts.get("wing_backlog")),
            "active": _report_count(counts.get("active")),
            "pending": pending_safe,
            "cpu_utilization_pct": scheduler_cpu_utilization_pct_last,
            "admission_active_cap": scheduler_admission_active_cap_current,
            "admission_guard_target": scheduler_admission_guard_target_current,
            "admission_wing_target": scheduler_admission_wing_target_current,
            "admission_reason": scheduler_admission_reason_current,
        }
        try:
            with scheduler_timeseries_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception:
            return
        scheduler_timeseries_last_snapshot = snapshot
        scheduler_timeseries_last_write_monotonic = now_monotonic
        scheduler_timeseries_rows_written += 1

    def _emit_scheduler_snapshot(
        *,
        counts: dict[str, int],
        pending_count: int,
        force_timeseries: bool = False,
    ) -> None:
        nonlocal scheduler_last_snapshot
        _write_scheduler_timeseries_row(
            counts=counts,
            pending_count=pending_count,
            force=force_timeseries,
        )
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(
            counts=counts,
            pending_count=max(0, pending_count),
        )
        if snapshot == scheduler_last_snapshot:
            return
        scheduler_last_snapshot = snapshot
        _emit_status(snapshot, color=typer.colors.BRIGHT_BLACK)

    item_by_global_index: dict[int, _AllMethodGlobalWorkItem] = {
        item.global_dispatch_index: item for item in work_items
    }
    variant_rows: list[dict[str, Any]] = []

    def _annotate_prediction_row(
        *,
        item: _AllMethodGlobalWorkItem,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(row)
        payload["global_dispatch_index"] = item.global_dispatch_index
        payload["source_position"] = item.source_position
        payload["source_group_key"] = item.source_group_key
        payload["source_slug"] = item.source_group_key
        payload["source_file"] = str(item.source_file)
        payload["source_file_name"] = item.source_file_name
        payload["gold_spans_path"] = str(item.gold_spans_path)
        payload["source_config_index"] = item.config_index
        payload["source_config_total"] = item.config_total
        payload["source_shard_index"] = item.source_shard_index + 1
        payload["source_shard_total"] = max(1, _report_count(item.source_shard_total))
        payload["source_estimated_seconds"] = item.source_estimated_seconds
        payload["source_estimate_basis"] = item.source_estimate_basis
        payload["_source_root"] = str(item.source_root)
        payload["_source_processed_root"] = str(item.source_processed_root)
        payload["_canonical_alignment_cache_dir"] = str(item.canonical_alignment_cache_dir)
        return payload

    def _latest_rows_by_dispatch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_by_index: dict[int, dict[str, Any]] = {}
        for row in rows:
            dispatch_index = _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            )
            latest_by_index[dispatch_index] = row
        return [latest_by_index[index] for index in sorted(latest_by_index)]

    def _mark_item_started(item: _AllMethodGlobalWorkItem, *, dashboard_tracking: bool) -> None:
        if not dashboard_tracking or dashboard is None:
            return
        source_position = item.source_position
        if source_active[source_position] <= 0:
            dashboard.start_source(source_position)
        source_active[source_position] += 1
        dashboard.start_config(
            source_index=source_position,
            config_index=item.config_index,
            config_total=max(1, item.config_total),
            config_slug=item.variant.slug,
        )

    def _mark_item_finished(
        item: _AllMethodGlobalWorkItem,
        *,
        success: bool,
        dashboard_tracking: bool,
    ) -> None:
        source_position = item.source_position
        source_active[source_position] = max(0, source_active[source_position] - 1)
        source_completed[source_position] += 1
        if not success:
            source_failed_seen[source_position] = True
        if not dashboard_tracking or dashboard is None:
            return
        dashboard.complete_config(
            source_index=source_position,
            success=success,
            config_index=item.config_index,
        )
        expected_total = max(0, _report_count(source_totals.get(source_position)))
        if (
            expected_total > 0
            and source_active[source_position] == 0
            and source_completed[source_position] >= expected_total
        ):
            dashboard.finish_source(
                source_position,
                failed=bool(source_failed_seen[source_position]),
            )

    def _run_serial_items(
        items: list[_AllMethodGlobalWorkItem],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        for item in items:
            progress_label = format_task_counter(
                "Running",
                item.global_dispatch_index,
                max(1, total_planned_config_runs),
                noun="config",
            )
            _mark_item_started(item, dashboard_tracking=dashboard_tracking)
            _emit_status(
                f"{progress_label}: {item.variant.slug} [{item.source_file_name}]",
                color=typer.colors.CYAN,
            )

            def _variant_progress(message: str) -> None:
                if progress_callback is None:
                    return
                if dashboard is None:
                    if _is_structured_progress_message(message):
                        _notify_progress_callback(progress_callback, message)
                        return
                    _notify_progress_callback(
                        progress_callback,
                        f"{progress_label}: {item.variant.slug} [{item.source_file_name}] | {message}",
                    )
                    return
                if _is_structured_progress_message(message):
                    _notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                _notify_progress_callback(progress_callback, dashboard.render())

            row = _run_all_method_prediction_once(
                gold_spans_path=item.gold_spans_path,
                source_file=item.source_file,
                variant=item.variant,
                config_index=item.global_dispatch_index,
                total_variants=max(1, total_planned_config_runs),
                root_output_dir=item.source_root,
                scratch_root=item.source_root / ".scratch",
                processed_output_root=item.source_processed_root,
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                max_concurrent_split_phases=effective_split_phase_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                scheduler_events_dir=scheduler_events_dir,
                alignment_cache_dir=item.canonical_alignment_cache_dir,
                prediction_reuse_cache_dir=resolved_prediction_reuse_cache_root,
                split_worker_cap_per_config=split_worker_cap_per_config,
                progress_callback=_variant_progress if progress_callback else None,
            )
            row = _annotate_prediction_row(item=item, row=row)
            variant_rows.append(row)

            success = str(row.get("status") or "").strip().lower() == "ok"
            _mark_item_finished(
                item,
                success=success,
                dashboard_tracking=dashboard_tracking,
            )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                            f"{item.variant.slug} [{item.source_file_name}]"
                        )
                    )
            else:
                _emit_status(
                    (
                        "Failed "
                        f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

    def _run_parallel_items(
        items: list[_AllMethodGlobalWorkItem],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        nonlocal process_worker_probe_available
        nonlocal process_worker_probe_error
        nonlocal scheduler_admission_adjustments
        nonlocal scheduler_admission_pressure_boosts
        nonlocal scheduler_admission_saturation_clamps
        nonlocal scheduler_admission_cpu_hot_clamps
        nonlocal scheduler_admission_active_cap_peak
        nonlocal scheduler_admission_guard_target_peak
        nonlocal scheduler_admission_last_key
        nonlocal scheduler_admission_active_cap_current
        nonlocal scheduler_admission_guard_target_current
        nonlocal scheduler_admission_wing_target_current
        nonlocal scheduler_admission_reason_current

        force_parallel_timeout = effective_config_timeout_seconds is not None
        serial_by_limits = (
            len(items) <= 1 or effective_inflight_pipelines <= 1
        ) and not force_parallel_timeout
        if serial_by_limits:
            config_executor_backends_seen.add("serial")
            _run_serial_items(items, dashboard_tracking=dashboard_tracking)
            return
        executor_backend = "process"
        process_workers_available, process_worker_error = (
            _probe_all_method_process_pool_executor()
        )
        if process_workers_available:
            picklable, picklable_error = _probe_all_method_process_worker_picklable()
            if not picklable:
                process_workers_available = False
                process_worker_error = picklable_error
        process_worker_probe_available = bool(process_workers_available)
        process_worker_probe_error = (
            str(process_worker_error).strip() if process_worker_error else None
        )
        if not process_workers_available:
            detail = (
                f" ({process_worker_error})"
                if isinstance(process_worker_error, str) and process_worker_error
                else ""
            )
            if require_process_workers:
                raise RuntimeError(
                    "Process-based config concurrency is required, but runtime probe "
                    f"reported it unavailable{detail}."
                )
            _emit_status(
                (
                    "Process-based config concurrency unavailable"
                    f"{detail}; using thread-based config concurrency."
                ),
                color=typer.colors.YELLOW,
            )
            executor_backend = "thread"
        config_executor_backends_seen.add(str(executor_backend))

        pending_items = list(items)
        futures: dict[Any, tuple[_AllMethodGlobalWorkItem, float]] = {}
        worker_limit = min(effective_inflight_pipelines, max(1, len(items)))
        scheduler_base_target = min(
            max(1, total_planned_config_runs),
            effective_split_phase_slots + effective_wing_backlog_target,
        )
        scheduler_smart_enabled = bool(effective_smart_scheduler)

        try:
            executor = (
                ProcessPoolExecutor(max_workers=worker_limit)
                if executor_backend == "process"
                else ThreadPoolExecutor(max_workers=worker_limit)
            )
        except (PermissionError, OSError) as exc:
            if executor_backend == "process":
                if require_process_workers:
                    raise RuntimeError(
                        "Process-based config concurrency is required, but process "
                        f"executor startup failed: {exc}"
                    ) from exc
                _emit_status(
                    (
                        "Process-based config concurrency unavailable "
                        f"({exc}); using thread-based config concurrency."
                    ),
                    color=typer.colors.YELLOW,
                )
                executor_backend = "thread"
                config_executor_backends_seen.add("thread")
                try:
                    executor = ThreadPoolExecutor(max_workers=worker_limit)
                except Exception as thread_exc:  # noqa: BLE001
                    _emit_status(
                        (
                            "Thread-based config concurrency unavailable "
                            f"({thread_exc}); running single-config execution."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    config_executor_backends_seen.add("serial")
                    _run_serial_items(items, dashboard_tracking=dashboard_tracking)
                    return
            else:
                _emit_status(
                    (
                        "Thread-based config concurrency unavailable "
                        f"({exc}); running single-config execution."
                    ),
                    color=typer.colors.YELLOW,
                )
                config_executor_backends_seen.add("serial")
                _run_serial_items(items, dashboard_tracking=dashboard_tracking)
                return

        def _record_completion(
            *,
            item: _AllMethodGlobalWorkItem,
            row: dict[str, Any],
        ) -> None:
            variant_rows.append(row)
            success = str(row.get("status") or "").strip().lower() == "ok"
            scheduler_phase_by_config.pop(item.global_dispatch_index, None)
            scheduler_event_offsets.pop(item.global_dispatch_index, None)
            _mark_item_finished(item, success=success, dashboard_tracking=dashboard_tracking)
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                            f"{item.variant.slug} [{item.source_file_name}]"
                        )
                    )
            else:
                _emit_status(
                    (
                        "Failed "
                        f"{format_task_counter('', item.global_dispatch_index, max(1, total_planned_config_runs), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

        def _submit_next() -> bool:
            if not pending_items:
                return False
            item = pending_items.pop(0)
            progress_label = format_task_counter(
                "Running",
                item.global_dispatch_index,
                max(1, total_planned_config_runs),
                noun="config",
            )
            _mark_item_started(item, dashboard_tracking=dashboard_tracking)
            _emit_status(
                f"{progress_label}: {item.variant.slug} [{item.source_file_name}]",
                color=typer.colors.CYAN,
            )

            try:
                future = executor.submit(
                    _run_all_method_prediction_once,
                    gold_spans_path=item.gold_spans_path,
                    source_file=item.source_file,
                    variant=item.variant,
                    config_index=item.global_dispatch_index,
                    total_variants=max(1, total_planned_config_runs),
                    root_output_dir=item.source_root,
                    scratch_root=item.source_root / ".scratch",
                    processed_output_root=item.source_processed_root,
                    overlap_threshold=overlap_threshold,
                    force_source_match=force_source_match,
                    max_concurrent_split_phases=effective_split_phase_slots,
                    split_phase_gate_dir=split_phase_gate_dir,
                    scheduler_events_dir=scheduler_events_dir,
                    alignment_cache_dir=item.canonical_alignment_cache_dir,
                    prediction_reuse_cache_dir=resolved_prediction_reuse_cache_root,
                    split_worker_cap_per_config=split_worker_cap_per_config,
                    progress_callback=None,
                )
            except Exception as exc:  # noqa: BLE001
                row = _all_method_failed_row(
                    config_index=item.global_dispatch_index,
                    config_dir_name=_all_method_config_dir_name(
                        item.global_dispatch_index,
                        item.variant,
                    ),
                    variant=item.variant,
                    error=f"Failed to submit benchmark config: {exc}",
                )
                _record_completion(item=item, row=_annotate_prediction_row(item=item, row=row))
                return True

            futures[future] = (item, time.monotonic())
            scheduler_phase_by_config[item.global_dispatch_index] = "prep"
            scheduler_event_offsets[item.global_dispatch_index] = 0
            return True

        def _refresh_admission_decision(
            *,
            counts: dict[str, int],
            pending_count: int,
        ) -> _AllMethodSchedulerAdmissionDecision:
            nonlocal scheduler_admission_adjustments
            nonlocal scheduler_admission_pressure_boosts
            nonlocal scheduler_admission_saturation_clamps
            nonlocal scheduler_admission_cpu_hot_clamps
            nonlocal scheduler_admission_active_cap_peak
            nonlocal scheduler_admission_guard_target_peak
            nonlocal scheduler_admission_last_key
            nonlocal scheduler_admission_active_cap_current
            nonlocal scheduler_admission_guard_target_current
            nonlocal scheduler_admission_wing_target_current
            nonlocal scheduler_admission_reason_current

            decision = _resolve_all_method_scheduler_admission(
                counts=counts,
                pending_count=pending_count,
                total_variants=max(1, total_planned_config_runs),
                configured_inflight_pipelines=configured_inflight_pipelines,
                split_phase_slots=effective_split_phase_slots,
                wing_backlog_target=effective_wing_backlog_target,
                max_active_during_eval=max_active_during_eval,
                adaptive_overcommit_limit=adaptive_overcommit_limit,
                adaptive_max_guard_target=max(
                    scheduler_base_target,
                    adaptive_max_guard_target,
                ),
                smart_scheduler_enabled=scheduler_smart_enabled,
                cpu_utilization_pct=scheduler_cpu_utilization_pct_last,
            )
            decision_key = (decision.active_cap, decision.guard_target, decision.reason)
            if scheduler_admission_last_key is None:
                scheduler_admission_last_key = decision_key
            elif decision_key != scheduler_admission_last_key:
                scheduler_admission_adjustments += 1
                scheduler_admission_last_key = decision_key
                if decision.pressure_boost > 0:
                    scheduler_admission_pressure_boosts += 1
                if decision.saturation_clamp:
                    scheduler_admission_saturation_clamps += 1
                if decision.cpu_hot_clamp:
                    scheduler_admission_cpu_hot_clamps += 1
            scheduler_admission_active_cap_peak = max(
                scheduler_admission_active_cap_peak,
                decision.active_cap,
            )
            scheduler_admission_guard_target_peak = max(
                scheduler_admission_guard_target_peak,
                decision.guard_target,
            )
            scheduler_admission_active_cap_current = decision.active_cap
            scheduler_admission_guard_target_current = decision.guard_target
            scheduler_admission_wing_target_current = decision.wing_target
            scheduler_admission_reason_current = decision.reason
            return decision

        try:
            while pending_items or futures:
                active_indices = {
                    item.global_dispatch_index
                    for item, _submitted in futures.values()
                }
                counts = _tick_scheduler_metrics(
                    active_indices=active_indices,
                    pending_count=len(pending_items),
                )
                if active_indices:
                    try:
                        _poll_scheduler_events(active_indices)
                    except Exception:
                        scheduler_smart_enabled = False
                counts = _compute_scheduler_counts(
                    {
                        item.global_dispatch_index
                        for item, _submitted in futures.values()
                    }
                )
                if dashboard_tracking and dashboard is not None:
                    for active_item, _submitted in futures.values():
                        dashboard.set_config_phase(
                            source_index=active_item.source_position,
                            config_index=active_item.config_index,
                            phase=scheduler_phase_by_config.get(
                                active_item.global_dispatch_index,
                                "prep",
                            ),
                        )
                admission_decision = _refresh_admission_decision(
                    counts=counts,
                    pending_count=len(pending_items),
                )
                _emit_scheduler_snapshot(
                    counts=counts,
                    pending_count=len(pending_items),
                )

                while len(futures) < worker_limit and pending_items:
                    heavy_plus_wing = counts["heavy_active"] + counts["wing_backlog"]
                    if counts["active"] >= admission_decision.active_cap:
                        break
                    if (
                        heavy_plus_wing >= admission_decision.guard_target
                        and counts["active"] >= configured_inflight_pipelines
                    ):
                        break
                    submitted = _submit_next()
                    if not submitted:
                        break
                    counts = _compute_scheduler_counts(
                        {
                            item.global_dispatch_index
                            for item, _submitted in futures.values()
                        }
                    )
                    admission_decision = _refresh_admission_decision(
                        counts=counts,
                        pending_count=len(pending_items),
                    )
                    _emit_scheduler_snapshot(
                        counts=counts,
                        pending_count=len(pending_items),
                    )

                if not futures:
                    if pending_items:
                        time.sleep(ALL_METHOD_SCHEDULER_POLL_SECONDS)
                    continue

                done, _ = wait(
                    list(futures.keys()),
                    timeout=ALL_METHOD_SCHEDULER_POLL_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                for done_future in done:
                    item, _submitted = futures.pop(done_future)
                    try:
                        row = done_future.result()
                    except Exception as exc:  # noqa: BLE001
                        row = _all_method_failed_row(
                            config_index=item.global_dispatch_index,
                            config_dir_name=_all_method_config_dir_name(
                                item.global_dispatch_index,
                                item.variant,
                            ),
                            variant=item.variant,
                            error=f"Benchmark config worker failed: {exc}",
                        )
                    _record_completion(
                        item=item,
                        row=_annotate_prediction_row(item=item, row=row),
                    )

                if (
                    effective_config_timeout_seconds is None
                    or executor_backend != "process"
                ):
                    continue
                timeout_threshold = float(max(1, effective_config_timeout_seconds))
                now = time.monotonic()
                timed_out: list[tuple[Any, _AllMethodGlobalWorkItem, float]] = []
                for future, (item, submitted_at) in list(futures.items()):
                    elapsed_seconds = max(0.0, now - submitted_at)
                    if elapsed_seconds < timeout_threshold:
                        continue
                    timed_out.append((future, item, elapsed_seconds))
                if not timed_out:
                    continue

                timed_out.sort(key=lambda item: item[1].global_dispatch_index)
                for timed_out_future, item, elapsed_seconds in timed_out:
                    futures.pop(timed_out_future, None)
                    row = _all_method_failed_row(
                        config_index=item.global_dispatch_index,
                        config_dir_name=_all_method_config_dir_name(
                            item.global_dispatch_index,
                            item.variant,
                        ),
                        variant=item.variant,
                        error=(
                            f"Config timed out after {int(timeout_threshold)}s "
                            f"(elapsed {elapsed_seconds:.1f}s)."
                        ),
                        elapsed_seconds=elapsed_seconds,
                    )
                    _record_completion(
                        item=item,
                        row=_annotate_prediction_row(item=item, row=row),
                    )

                if futures:
                    requeued = sorted(
                        [item for item, _submitted in futures.values()],
                        key=lambda item: item.global_dispatch_index,
                    )
                    pending_items = requeued + pending_items
                    futures.clear()
                scheduler_smart_enabled = False
                _emit_status(
                    (
                        "Config timeout reached for "
                        f"{len(timed_out)} run(s); restarting process worker pool."
                    ),
                    color=typer.colors.YELLOW,
                )
                shutdown_fn = getattr(executor, "shutdown", None)
                if callable(shutdown_fn):
                    try:
                        shutdown_fn(wait=False, cancel_futures=True)
                    except TypeError:
                        shutdown_fn(wait=False)
                try:
                    executor = ProcessPoolExecutor(max_workers=worker_limit)
                except (PermissionError, OSError) as exc:
                    if require_process_workers:
                        raise RuntimeError(
                            "Process-based config concurrency is required, but process "
                            f"pool restart failed after timeout: {exc}"
                        ) from exc
                    _emit_status(
                        (
                            "Process-based config concurrency unavailable after timeout "
                            f"restart ({exc}); using thread-based config concurrency for remaining configs."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    executor_backend = "thread"
                    config_executor_backends_seen.add("thread")
                    try:
                        executor = ThreadPoolExecutor(max_workers=worker_limit)
                    except Exception as thread_exc:  # noqa: BLE001
                        _emit_status(
                            (
                                "Thread-based config concurrency unavailable "
                                f"({thread_exc}); running remaining configs as single-config execution."
                            ),
                            color=typer.colors.YELLOW,
                        )
                        config_executor_backends_seen.add("serial")
                        _run_serial_items(
                            pending_items,
                            dashboard_tracking=dashboard_tracking,
                        )
                        pending_items.clear()
                        futures.clear()
                        break
        finally:
            shutdown_fn = getattr(executor, "shutdown", None)
            if callable(shutdown_fn):
                try:
                    shutdown_fn(wait=True, cancel_futures=False)
                except TypeError:
                    shutdown_fn(wait=True)

    _run_parallel_items(work_items, dashboard_tracking=True)
    variant_rows = _latest_rows_by_dispatch(variant_rows)
    initial_failed_indices = [
        _report_count(
            row.get("global_dispatch_index", row.get("config_index"))
        )
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    retry_passes_executed = 0
    retry_recovered_configs = 0
    if effective_retry_failed_configs > 0 and initial_failed_indices:
        remaining_failed_indices = sorted(set(initial_failed_indices))
        for retry_pass in range(1, effective_retry_failed_configs + 1):
            if not remaining_failed_indices:
                break
            retry_items = [
                item_by_global_index[index]
                for index in remaining_failed_indices
                if index in item_by_global_index
            ]
            if not retry_items:
                break
            retry_passes_executed += 1
            _emit_status(
                (
                    f"Retry pass {retry_pass}/{effective_retry_failed_configs}: "
                    f"rerunning {len(retry_items)} failed config(s)."
                ),
                color=typer.colors.YELLOW,
            )
            prior_failed = set(remaining_failed_indices)
            _run_parallel_items(retry_items, dashboard_tracking=False)
            variant_rows = _latest_rows_by_dispatch(variant_rows)
            remaining_failed_indices = sorted(
                {
                    _report_count(
                        row.get("global_dispatch_index", row.get("config_index"))
                    )
                    for row in variant_rows
                    if str(row.get("status") or "").strip().lower() != "ok"
                }
            )
            recovered_this_pass = len(prior_failed - set(remaining_failed_indices))
            retry_recovered_configs += max(0, recovered_this_pass)
            if recovered_this_pass > 0:
                _emit_status(
                    (
                        f"Retry pass {retry_pass} recovered "
                        f"{recovered_this_pass} config(s)."
                    ),
                    color=typer.colors.CYAN,
                )

    _tick_scheduler_metrics(active_indices=set(), pending_count=0)
    _emit_scheduler_snapshot(
        counts=_compute_scheduler_counts(set()),
        pending_count=0,
        force_timeseries=True,
    )

    scheduler_utilization_pct = (
        (scheduler_busy_seconds / scheduler_capacity_seconds) * 100.0
        if scheduler_capacity_seconds > 0
        else 0.0
    )
    scheduler_avg_wing_backlog = (
        scheduler_wing_area_seconds / scheduler_capacity_seconds
        if scheduler_capacity_seconds > 0
        else 0.0
    )
    scheduler_summary: dict[str, Any] = {
        "mode": "smart" if bool(effective_smart_scheduler) else "fixed",
        "source_count": max(1, total_targets),
        "configured_inflight_pipelines": configured_inflight_pipelines,
        "effective_inflight_pipelines": effective_inflight_pipelines,
        "split_phase_slots_requested": requested_split_phase_slots,
        "split_phase_slots": effective_split_phase_slots,
        "split_phase_slot_mode": split_phase_slot_mode,
        "split_phase_slot_cap_by_cpu": split_phase_slot_cap_by_cpu,
        "split_phase_slot_cap_by_memory": split_phase_slot_cap_by_memory,
        "wing_backlog_target": effective_wing_backlog_target,
        "split_worker_cap_per_config": split_worker_cap_per_config,
        "split_worker_cap_by_cpu": split_worker_guard.get("split_worker_cap_by_cpu"),
        "split_worker_cap_by_memory": split_worker_guard.get("split_worker_cap_by_memory"),
        "eval_tail_headroom_mode": eval_tail_headroom_mode,
        "eval_tail_headroom_configured": configured_eval_tail_headroom,
        "eval_tail_headroom_effective": effective_eval_tail_headroom,
        "max_active_during_eval": max_active_during_eval,
        "adaptive_overcommit_limit": adaptive_overcommit_limit,
        "adaptive_max_guard_target": adaptive_max_guard_target,
        "source_parallelism_effective": 1,
        "cpu_budget_per_source": scheduler_cpu_budget_per_source,
        "cpu_budget_total": scheduler_cpu_budget_total,
        "max_eval_tail_pipelines": effective_eval_tail_headroom,
        "smart_tail_buffer_slots": (
            effective_eval_tail_headroom if bool(effective_smart_scheduler) else 0
        ),
        "smart_scheduler_enabled": bool(effective_smart_scheduler),
        "config_timeout_seconds": effective_config_timeout_seconds,
        "failed_retry_limit": effective_retry_failed_configs,
        "retry_passes_executed": retry_passes_executed,
        "retry_recovered_configs": retry_recovered_configs,
        "heavy_slot_capacity_seconds": scheduler_capacity_seconds,
        "heavy_slot_busy_seconds": scheduler_busy_seconds,
        "heavy_slot_utilization_pct": scheduler_utilization_pct,
        "avg_wing_backlog": scheduler_avg_wing_backlog,
        "max_wing_backlog": scheduler_max_wing_backlog,
        "idle_gap_seconds": scheduler_idle_gap_seconds,
        "max_active_pipelines_observed": scheduler_max_active_pipelines,
        "max_eval_active_observed": scheduler_max_eval_active,
        "adaptive_admission_adjustments": scheduler_admission_adjustments,
        "adaptive_admission_pressure_boosts": scheduler_admission_pressure_boosts,
        "adaptive_admission_saturation_clamps": scheduler_admission_saturation_clamps,
        "adaptive_admission_cpu_hot_clamps": scheduler_admission_cpu_hot_clamps,
        "adaptive_admission_active_cap_peak": scheduler_admission_active_cap_peak,
        "adaptive_admission_guard_target_peak": scheduler_admission_guard_target_peak,
        "timeseries_path": str(scheduler_timeseries_path),
        "timeseries_row_count": scheduler_timeseries_rows_written,
        "timeseries_heartbeat_seconds": scheduler_timeseries_heartbeat_seconds,
        "snapshot_poll_seconds": ALL_METHOD_SCHEDULER_POLL_SECONDS,
        "cpu_utilization_source": scheduler_cpu_source,
        "cpu_utilization_samples": scheduler_cpu_samples_collected,
        "cpu_utilization_pct_high_water": scheduler_cpu_utilization_pct_high_water,
        "scheduler_scope": "global_config_queue",
    }

    variant_rows = _latest_rows_by_dispatch(variant_rows)
    prediction_success_rows = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    failed_rows: list[dict[str, Any]] = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    successful_rows: list[dict[str, Any]] = []
    signature_candidate_rows: list[dict[str, Any]] = []
    evaluation_signatures_unique = 0
    evaluation_runs_executed = 0
    evaluation_results_reused_in_run = 0
    evaluation_results_reused_cross_run = 0
    eval_signature_cache_dir = _resolve_all_method_eval_signature_cache_dir(
        root_output_dir=root_output_dir,
        alignment_cache_dir=resolved_canonical_cache_root / "__global__",
    )

    for row in prediction_success_rows:
        source_root_raw = str(row.get("_source_root") or "").strip()
        if not source_root_raw:
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Source root is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        prediction_record_path = _resolve_all_method_prediction_record_path(
            root_output_dir=Path(source_root_raw),
            row=row,
        )
        if (
            prediction_record_path is None
            or not prediction_record_path.exists()
            or not prediction_record_path.is_file()
        ):
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Prediction record path is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        sequence_matcher = str(row.get("benchmark_sequence_matcher") or "").strip() or "dmp"
        gold_spans_path = Path(str(row.get("gold_spans_path") or "").strip())
        try:
            eval_signature = _build_all_method_eval_signature(
                gold_spans_path=gold_spans_path,
                prediction_record_path=prediction_record_path,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
            )
        except Exception as exc:  # noqa: BLE001
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = f"Failed to build evaluation signature: {exc}"
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        row["eval_signature"] = eval_signature
        row["benchmark_sequence_matcher"] = sequence_matcher
        signature_candidate_rows.append(row)

    grouped_by_signature = _group_all_method_rows_by_eval_signature(signature_candidate_rows)
    evaluation_signatures_unique = len(grouped_by_signature)
    grouped_items = sorted(
        grouped_by_signature.items(),
        key=lambda item: min(
            _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            )
            for row in item[1]
        ),
    )
    for signature_index, (eval_signature, group_rows) in enumerate(grouped_items, start=1):
        if not group_rows:
            continue
        ordered_group = sorted(
            group_rows,
            key=lambda row: _report_count(
                row.get("global_dispatch_index", row.get("config_index"))
            ),
        )
        representative_row = ordered_group[0]
        representative_config_dir = str(representative_row.get("config_dir") or "").strip()
        if not representative_config_dir:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative config directory is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue

        source_root = Path(str(representative_row.get("_source_root") or ""))
        source_processed_root = Path(
            str(representative_row.get("_source_processed_root") or "")
        )
        canonical_alignment_cache_dir = Path(
            str(representative_row.get("_canonical_alignment_cache_dir") or "")
        )
        representative_eval_output_dir = source_root / representative_config_dir
        representative_processed_output_dir = source_processed_root / representative_config_dir
        representative_prediction_record = _resolve_all_method_prediction_record_path(
            root_output_dir=source_root,
            row=representative_row,
        )
        if representative_prediction_record is None:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative prediction record is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        sequence_matcher = str(representative_row.get("benchmark_sequence_matcher") or "").strip()
        if not sequence_matcher:
            sequence_matcher = "dmp"

        cache_path = eval_signature_cache_dir / f"{eval_signature}.json"
        cache_entry = _load_all_method_eval_signature_cache_entry(
            cache_path=cache_path,
            expected_signature=eval_signature,
        )
        evaluation_result_source_for_group = "executed"
        evaluation_summary: dict[str, Any]
        if cache_entry is not None:
            cached_report = cache_entry.get("report")
            if not isinstance(cached_report, dict):
                cached_report = {}
            cached_md = str(cache_entry.get("report_md") or "")
            eval_report_json_path, eval_report_md_path = (
                _materialize_all_method_cached_eval_outputs(
                    eval_output_dir=representative_eval_output_dir,
                    report_payload=cached_report,
                    report_md_text=cached_md,
                )
            )
            metric_bundle = _benchmark_report_metric_bundle(cached_report)
            evaluation_summary = {
                "status": "ok",
                "error": "",
                **metric_bundle,
                "timing": _normalize_timing_payload(cached_report.get("timing")),
                "report": cached_report,
                "report_md_text": cached_md,
                "eval_report_json_path": eval_report_json_path,
                "eval_report_md_path": eval_report_md_path,
                "duration_seconds": 0.0,
            }
            evaluation_result_source_for_group = "reused_cross_run"
            evaluation_results_reused_cross_run += len(ordered_group)
        else:
            _emit_status(
                (
                    "Evaluating signature "
                    f"{signature_index}/{max(1, evaluation_signatures_unique)} "
                    f"(group size {len(ordered_group)})."
                ),
                color=typer.colors.CYAN,
            )
            evaluation_summary = _run_all_method_evaluate_prediction_record_once(
                gold_spans_path=Path(str(representative_row.get("gold_spans_path") or "")),
                source_file=Path(str(representative_row.get("source_file") or "")),
                prediction_record_path=representative_prediction_record,
                eval_output_dir=representative_eval_output_dir,
                processed_output_dir=representative_processed_output_dir,
                sequence_matcher=sequence_matcher,
                epub_extractor=_row_dimension_str(representative_row, "epub_extractor"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                alignment_cache_dir=canonical_alignment_cache_dir,
                progress_callback=None,
            )
            if str(evaluation_summary.get("status") or "").strip().lower() == "ok":
                evaluation_runs_executed += 1
                if len(ordered_group) > 1:
                    evaluation_results_reused_in_run += len(ordered_group) - 1
                cached_payload = {
                    "schema_version": ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION,
                    "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "eval_signature": eval_signature,
                    "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                    "sequence_matcher": sequence_matcher,
                    "source_file": str(representative_row.get("source_file") or ""),
                    "gold_spans_path": str(representative_row.get("gold_spans_path") or ""),
                    "report": evaluation_summary.get("report"),
                    "report_md": evaluation_summary.get("report_md_text"),
                }
                try:
                    _write_all_method_eval_signature_cache_entry(
                        cache_path=cache_path,
                        payload=cached_payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Ignoring eval-signature cache write failure for %s: %s",
                        cache_path,
                        exc,
                    )

        if str(evaluation_summary.get("status") or "").strip().lower() != "ok":
            error_text = str(evaluation_summary.get("error") or "Evaluation failed.")
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = error_text
                failed_row["evaluation_result_source"] = "failed"
                failed_row["evaluation_representative_config_dir"] = representative_config_dir
                failed_row["eval_signature"] = eval_signature
                failed_rows.append(failed_row)
            continue

        summary_timing = _normalize_timing_payload(evaluation_summary.get("timing"))
        summary_evaluation_seconds = _report_optional_metric(
            summary_timing.get("evaluation_seconds")
        )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                summary_timing.get("total_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                evaluation_summary.get("duration_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = 0.0
        summary_eval_wall_seconds = max(
            0.0,
            _report_metric(evaluation_summary.get("duration_seconds")),
        )
        summary_report_json_path = Path(str(evaluation_summary.get("eval_report_json_path") or ""))
        summary_report_md_path = Path(str(evaluation_summary.get("eval_report_md_path") or ""))
        alignment_guardrail_fields = _all_method_extract_alignment_guardrail_fields(
            cast(dict[str, Any] | None, evaluation_summary.get("report"))
        )

        for row in ordered_group:
            result_row = dict(row)
            is_representative = (
                _report_count(
                    result_row.get("global_dispatch_index", result_row.get("config_index"))
                )
                == _report_count(
                    representative_row.get(
                        "global_dispatch_index",
                        representative_row.get("config_index"),
                    )
                )
            )
            row_result_source = "executed"
            if evaluation_result_source_for_group == "reused_cross_run":
                row_result_source = "reused_cross_run"
            elif not is_representative:
                row_result_source = "reused_in_run"

            row_timing = _normalize_timing_payload(result_row.get("timing"))
            prediction_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
            if prediction_total_seconds is None:
                prediction_total_seconds = _report_optional_metric(
                    result_row.get("duration_seconds")
                )
            if prediction_total_seconds is None:
                prediction_total_seconds = 0.0
            row_eval_seconds = summary_evaluation_seconds if row_result_source == "executed" else 0.0
            row_eval_wall = summary_eval_wall_seconds if row_result_source == "executed" else 0.0
            row_total_seconds = max(0.0, prediction_total_seconds + row_eval_seconds)
            row_timing = _timing_with_updates(
                row_timing,
                evaluation_seconds=row_eval_seconds,
                total_seconds=row_total_seconds,
                checkpoints={
                    "all_method_eval_wall_seconds": row_eval_wall,
                    "all_method_eval_reused_in_run": (
                        1.0 if row_result_source == "reused_in_run" else 0.0
                    ),
                    "all_method_eval_reused_cross_run": (
                        1.0 if row_result_source == "reused_cross_run" else 0.0
                    ),
                },
            )

            result_row["status"] = "ok"
            result_row["error"] = ""
            result_row["precision"] = _report_metric(evaluation_summary.get("precision"))
            result_row["recall"] = _report_metric(evaluation_summary.get("recall"))
            result_row["f1"] = _report_metric(evaluation_summary.get("f1"))
            result_row["practical_precision"] = _report_metric(
                evaluation_summary.get("practical_precision")
            )
            result_row["practical_recall"] = _report_metric(
                evaluation_summary.get("practical_recall")
            )
            result_row["practical_f1"] = _report_metric(evaluation_summary.get("practical_f1"))
            result_row.update(alignment_guardrail_fields)
            result_row["eval_signature"] = eval_signature
            result_row["evaluation_result_source"] = row_result_source
            result_row["evaluation_representative_config_dir"] = representative_config_dir
            result_row["duration_seconds"] = row_total_seconds
            result_row["timing"] = row_timing
            result_row["eval_report_json"] = _path_for_manifest(
                source_root,
                summary_report_json_path,
            )
            result_row["eval_report_md"] = _path_for_manifest(
                source_root,
                summary_report_md_path,
            )
            successful_rows.append(result_row)

    matcher_guardrails = _all_method_build_matcher_guardrails(successful_rows)
    scheduler_summary["matcher_guardrails"] = matcher_guardrails
    for warning in matcher_guardrails.get("warnings", []):
        _emit_status(f"Matcher guardrail warning: {warning}", color=typer.colors.YELLOW)

    source_rows = _write_all_method_source_reports_from_global_rows(
        target_variants=target_variants,
        source_job_plans=source_job_plans,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        successful_rows=successful_rows,
        failed_rows=failed_rows,
        include_codex_farm_requested=include_codex_farm_requested,
        include_codex_farm_effective=include_codex_farm_effective,
        eval_signature_cache_dir=eval_signature_cache_dir,
        scheduler_summary=scheduler_summary,
        retry_failed_configs_requested=effective_retry_failed_configs,
        retry_passes_executed=retry_passes_executed,
        retry_recovered_configs=retry_recovered_configs,
    )

    successful_source_count = sum(
        1 for row in source_rows if str(row.get("status", "")).lower() == "ok"
    )
    total_completed_config_runs = sum(
        _report_count(row.get("variant_count_completed")) for row in source_rows
    )
    total_successful_config_runs = sum(
        _report_count(row.get("variant_count_successful")) for row in source_rows
    )
    total_failed_config_runs = max(
        0,
        total_completed_config_runs - total_successful_config_runs,
    )
    total_evaluation_signatures_unique = sum(
        _report_count(row.get("evaluation_signatures_unique")) for row in source_rows
    )
    total_evaluation_runs_executed = sum(
        _report_count(row.get("evaluation_runs_executed")) for row in source_rows
    )
    total_evaluation_results_reused_in_run = sum(
        _report_count(row.get("evaluation_results_reused_in_run"))
        for row in source_rows
    )
    total_evaluation_results_reused_cross_run = sum(
        _report_count(row.get("evaluation_results_reused_cross_run"))
        for row in source_rows
    )
    total_prediction_signatures_unique = sum(
        _report_count(row.get("prediction_signatures_unique")) for row in source_rows
    )
    total_prediction_runs_executed = sum(
        _report_count(row.get("prediction_runs_executed")) for row in source_rows
    )
    total_prediction_results_reused_in_run = sum(
        _report_count(row.get("prediction_results_reused_in_run"))
        for row in source_rows
    )
    total_prediction_results_reused_cross_run = sum(
        _report_count(row.get("prediction_results_reused_cross_run"))
        for row in source_rows
    )
    total_split_convert_input_groups = sum(
        _report_count(row.get("split_convert_input_groups")) for row in source_rows
    )
    total_split_convert_reuse_candidates = sum(
        _report_count(row.get("split_convert_reuse_candidates")) for row in source_rows
    )
    total_split_convert_reuse_safe_candidates = sum(
        _report_count(row.get("split_convert_reuse_safe_candidates"))
        for row in source_rows
    )
    total_split_convert_reuse_blocked = sum(
        _report_count(row.get("split_convert_reuse_blocked_by_prediction_variance"))
        for row in source_rows
    )
    run_wall_seconds = max(0.0, time.monotonic() - run_started)

    source_timing_values: list[tuple[dict[str, Any], float]] = []
    config_total_seconds = 0.0
    for row in source_rows:
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        source_seconds = _report_optional_metric(
            timing_summary.get("source_wall_seconds")
        )
        if source_seconds is not None:
            source_timing_values.append((row, source_seconds))
        config_seconds = _report_optional_metric(
            timing_summary.get("config_total_seconds")
        )
        if config_seconds is not None:
            config_total_seconds += config_seconds
    source_total_seconds = sum(seconds for _row, seconds in source_timing_values)
    source_average_seconds = (
        source_total_seconds / len(source_timing_values) if source_timing_values else None
    )
    config_average_seconds = (
        config_total_seconds / total_successful_config_runs
        if total_successful_config_runs > 0
        else None
    )
    slowest_source_row = (
        max(source_timing_values, key=lambda item: item[1])[0]
        if source_timing_values
        else None
    )
    slowest_source_seconds = (
        max(seconds for _row, seconds in source_timing_values)
        if source_timing_values
        else None
    )
    slowest_config_name: str | None = None
    slowest_config_seconds: float | None = None
    for row in source_rows:
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        candidate_seconds = _report_optional_metric(
            timing_summary.get("slowest_config_seconds")
        )
        if candidate_seconds is None:
            continue
        candidate_dir = str(timing_summary.get("slowest_config_dir") or "").strip()
        if not candidate_dir:
            continue
        candidate_name = f"{row.get('source_slug', '')}/{candidate_dir}".strip("/")
        if slowest_config_seconds is None or candidate_seconds > slowest_config_seconds:
            slowest_config_seconds = candidate_seconds
            slowest_config_name = candidate_name

    report_payload: dict[str, Any] = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        "matched_target_count": total_targets,
        "unmatched_target_count": len(unmatched_targets),
        "scheduler_scope": "global_config_queue",
        "source_schedule_strategy": resolved_source_scheduling,
        "source_shard_threshold_seconds": resolved_source_shard_threshold_seconds,
        "source_shard_max_parts": resolved_source_shard_max_parts,
        "source_shard_min_variants": resolved_source_shard_min_variants,
        "source_job_count_planned": len(source_job_plans),
        "source_schedule_plan": [
            {
                "dispatch_index": dispatch_index + 1,
                "source_position": plan.source_position + 1,
                "source_group_key": plan.source_group_key,
                "source_file": str(plan.source_file),
                "source_file_name": plan.source_display_name,
                "source_slug": plan.source_slug,
                "source_shard_index": plan.shard_index + 1,
                "source_shard_total": max(1, _report_count(plan.shard_total)),
                "variant_count": len(plan.variants),
                "estimated_seconds": plan.estimated_seconds,
                "estimate_basis": plan.estimate_basis,
            }
            for dispatch_index, plan in enumerate(source_job_plans)
        ],
        "global_queue_schedule_plan": [
            {
                "dispatch_index": item.global_dispatch_index,
                "source_position": item.source_position + 1,
                "source_group_key": item.source_group_key,
                "source_file": str(item.source_file),
                "source_file_name": item.source_file_name,
                "source_slug": item.source_slug,
                "source_shard_index": item.source_shard_index + 1,
                "source_shard_total": max(1, _report_count(item.source_shard_total)),
                "source_config_index": item.config_index,
                "source_config_total": item.config_total,
                "variant_slug": item.variant.slug,
                "estimated_seconds": item.source_estimated_seconds,
                "estimate_basis": item.source_estimate_basis,
            }
            for item in work_items
        ],
        "source_parallelism_configured": source_parallelism_configured,
        "source_parallelism_effective": source_parallelism_effective,
        "total_config_runs_planned": total_planned_config_runs,
        "total_config_runs_completed": total_completed_config_runs,
        "total_config_runs_successful": total_successful_config_runs,
        "global_queue_planned_configs": total_planned_config_runs,
        "global_queue_completed_configs": total_completed_config_runs,
        "global_queue_failed_configs": total_failed_config_runs,
        "evaluation_signatures_unique": total_evaluation_signatures_unique,
        "evaluation_runs_executed": total_evaluation_runs_executed,
        "evaluation_results_reused_in_run": total_evaluation_results_reused_in_run,
        "evaluation_results_reused_cross_run": total_evaluation_results_reused_cross_run,
        "prediction_signatures_unique": total_prediction_signatures_unique,
        "prediction_runs_executed": total_prediction_runs_executed,
        "prediction_results_reused_in_run": total_prediction_results_reused_in_run,
        "prediction_results_reused_cross_run": total_prediction_results_reused_cross_run,
        "split_convert_input_groups": total_split_convert_input_groups,
        "split_convert_reuse_candidates": total_split_convert_reuse_candidates,
        "split_convert_reuse_safe_candidates": total_split_convert_reuse_safe_candidates,
        "split_convert_reuse_blocked_by_prediction_variance": total_split_convert_reuse_blocked,
        "prediction_reuse_key_schema_version": (
            ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION
        ),
        "split_convert_input_key_schema_version": (
            ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION
        ),
        "successful_source_count": successful_source_count,
        "failed_source_count": total_targets - successful_source_count,
        "config_timeout_seconds": effective_config_timeout_seconds,
        "retry_failed_configs_requested": effective_retry_failed_configs,
        "include_codex_farm_requested": include_codex_farm_requested,
        "include_codex_farm_effective": include_codex_farm_effective,
        "canonical_alignment_cache_root": str(resolved_canonical_cache_root),
        "prediction_reuse_cache_root": str(resolved_prediction_reuse_cache_root),
        "executor_resolution": {
            "process_workers_required": bool(require_process_workers),
            "process_worker_probe_available": process_worker_probe_available,
            "process_worker_probe_error": process_worker_probe_error,
            "config_executor_backends_seen": sorted(config_executor_backends_seen),
        },
        "timing_summary": {
            "run_wall_seconds": run_wall_seconds,
            "source_total_seconds": source_total_seconds,
            "source_average_seconds": source_average_seconds,
            "config_total_seconds": config_total_seconds,
            "config_average_seconds": config_average_seconds,
            "slowest_source": (
                str(slowest_source_row.get("source_file", ""))
                if isinstance(slowest_source_row, dict)
                else None
            ),
            "slowest_source_seconds": slowest_source_seconds,
            "slowest_config": slowest_config_name,
            "slowest_config_seconds": slowest_config_seconds,
        },
        "scheduler_summary": dict(scheduler_summary),
        "sources": source_rows,
        "unmatched": [
            {
                "gold_spans_path": str(unmatched.gold_spans_path),
                "gold_display": unmatched.gold_display,
                "reason": unmatched.reason,
                "source_hint": unmatched.source_hint,
            }
            for unmatched in unmatched_targets
        ],
    }

    history_csv_path = history_csv_for_output(
        processed_output_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    _refresh_dashboard_after_history_write(
        csv_path=history_csv_path,
        output_root=resolved_dashboard_output_root,
        dashboard_out_dir=(
            history_root_for_output(resolved_dashboard_output_root) / "dashboard"
            if resolved_dashboard_output_root is not None
            else None
        ),
        reason="all-method benchmark global queue batch append",
    )

    report_json_path = root_output_dir / "all_method_benchmark_multi_source_report.json"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
    report_md_path.write_text(
        _render_all_method_multi_source_report_md(report_payload),
        encoding="utf-8",
    )

    completion_color = (
        typer.colors.GREEN
        if successful_source_count == total_targets
        and total_successful_config_runs == total_planned_config_runs
        else typer.colors.YELLOW
    )
    _emit_status(
        (
            "All method benchmark complete: "
            f"sources {successful_source_count}/{total_targets}, "
            f"configs {total_successful_config_runs}/{total_planned_config_runs}."
        ),
        color=completion_color,
    )
    if progress_callback is None:
        typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)
    return report_md_path


def _run_all_method_benchmark_multi_source(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    unmatched_targets: list[AllMethodUnmatchedGold],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    max_parallel_sources: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    scheduler_scope: str | None = None,
    source_scheduling: str | None = None,
    source_shard_threshold_seconds: float | None = None,
    source_shard_max_parts: int | None = None,
    source_shard_min_variants: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    canonical_alignment_cache_root: Path | None = None,
    prediction_reuse_cache_root: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    _normalize_all_method_scheduler_scope(scheduler_scope)
    return _run_all_method_benchmark_global_queue(
        target_variants=target_variants,
        unmatched_targets=unmatched_targets,
        include_codex_farm_requested=include_codex_farm_requested,
        include_codex_farm_effective=include_codex_farm_effective,
        root_output_dir=root_output_dir,
        processed_output_root=processed_output_root,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
        progress_callback=progress_callback,
        dashboard=dashboard,
        max_parallel_sources=max_parallel_sources,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        config_timeout_seconds=config_timeout_seconds,
        retry_failed_configs=retry_failed_configs,
        source_scheduling=source_scheduling,
        source_shard_threshold_seconds=source_shard_threshold_seconds,
        source_shard_max_parts=source_shard_max_parts,
        source_shard_min_variants=source_shard_min_variants,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        canonical_alignment_cache_root=canonical_alignment_cache_root,
        prediction_reuse_cache_root=prediction_reuse_cache_root,
        dashboard_output_root=dashboard_output_root,
        require_process_workers=require_process_workers,
    )


def _run_all_method_benchmark(
    *,
    gold_spans_path: Path,
    source_file: Path,
    variants: list[AllMethodVariant],
    include_codex_farm_requested: bool,
    include_codex_farm_effective: bool,
    root_output_dir: Path,
    processed_output_root: Path,
    overlap_threshold: float,
    force_source_match: bool,
    progress_callback: Callable[[str], None] | None = None,
    dashboard: _AllMethodProgressDashboard | None = None,
    dashboard_source_index: int | None = None,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    config_timeout_seconds: int | None = None,
    retry_failed_configs: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
    refresh_dashboard_after_source: bool = True,
    source_parallelism_effective: int | None = 1,
    canonical_alignment_cache_dir_override: Path | None = None,
    prediction_reuse_cache_dir_override: Path | None = None,
    dashboard_output_root: Path | None = None,
    require_process_workers: bool = False,
) -> Path:
    source_started = time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = root_output_dir / ".scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)
    split_phase_gate_dir = root_output_dir / ".split_phase_slots"
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    canonical_alignment_cache_dir = (
        canonical_alignment_cache_dir_override
        if canonical_alignment_cache_dir_override is not None
        else (root_output_dir / ".cache" / "canonical_alignment")
    )
    prediction_reuse_cache_dir = (
        prediction_reuse_cache_dir_override.expanduser()
        if prediction_reuse_cache_dir_override is not None
        else _resolve_all_method_prediction_reuse_cache_dir(
            root_output_dir=root_output_dir
        )
    )
    scheduler_events_dir = root_output_dir / ".scheduler_events"
    scheduler_timeseries_path = root_output_dir / ALL_METHOD_SCHEDULER_TIMESERIES_FILENAME
    if scheduler_events_dir.exists():
        shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)
    if scheduler_timeseries_path.exists():
        scheduler_timeseries_path.unlink()

    total_variants = len(variants)
    scheduler_runtime = _resolve_all_method_scheduler_runtime(
        total_variants=total_variants,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
        max_eval_tail_pipelines=max_eval_tail_pipelines,
        wing_backlog_target=wing_backlog_target,
        smart_scheduler=smart_scheduler,
        source_parallelism_effective=source_parallelism_effective,
    )
    configured_inflight_pipelines = scheduler_runtime.configured_inflight_pipelines
    requested_split_phase_slots = scheduler_runtime.split_phase_slots_requested
    effective_split_phase_slots = scheduler_runtime.split_phase_slots
    split_phase_slot_mode = scheduler_runtime.split_phase_slot_mode
    split_phase_slot_cap_by_cpu = scheduler_runtime.split_phase_slot_cap_by_cpu
    split_phase_slot_cap_by_memory = scheduler_runtime.split_phase_slot_cap_by_memory
    effective_wing_backlog_target = scheduler_runtime.wing_backlog_target
    configured_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_configured
    effective_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_effective
    eval_tail_headroom_mode = scheduler_runtime.eval_tail_headroom_mode
    effective_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    max_active_during_eval = scheduler_runtime.max_active_during_eval
    effective_inflight_pipelines = scheduler_runtime.effective_inflight_pipelines
    adaptive_overcommit_limit = scheduler_runtime.adaptive_overcommit_limit
    adaptive_max_guard_target = scheduler_runtime.adaptive_max_guard_target
    scheduler_source_parallelism = scheduler_runtime.source_parallelism_effective
    scheduler_cpu_budget_per_source = scheduler_runtime.cpu_budget_per_source
    scheduler_cpu_budget_total = scheduler_runtime.cpu_budget_total
    split_worker_cap_per_config, split_worker_guard = _resolve_all_method_split_worker_cap(
        split_phase_slots=effective_split_phase_slots,
        source_parallelism_effective=source_parallelism_effective,
    )
    max_requested_split_workers = max(
        [
            max(
                max(1, _report_count(variant.run_settings.workers)),
                max(1, _report_count(variant.run_settings.pdf_split_workers)),
                max(1, _report_count(variant.run_settings.epub_split_workers)),
            )
            for variant in variants
        ],
        default=1,
    )
    effective_config_timeout_seconds = _resolve_all_method_config_timeout_seconds(
        config_timeout_seconds
    )
    effective_retry_failed_configs = _resolve_all_method_retry_failed_configs(
        retry_failed_configs
    )

    def _emit_status(
        message: str,
        *,
        color: typer.colors = typer.colors.CYAN,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned:
            return
        if progress_callback is not None:
            if _is_structured_progress_message(cleaned):
                _notify_progress_callback(progress_callback, cleaned)
                return
            if dashboard is not None:
                dashboard.set_task(cleaned)
                _notify_progress_callback(progress_callback, dashboard.render())
                return
            _notify_progress_callback(progress_callback, cleaned)
            return
        typer.secho(cleaned, fg=color)

    if split_phase_slot_mode != "configured":
        _emit_status(
            (
                "Resource guard capped split slots to "
                f"{effective_split_phase_slots} "
                f"(requested {requested_split_phase_slots}; "
                f"cpu cap {split_phase_slot_cap_by_cpu}; "
                f"memory cap {split_phase_slot_cap_by_memory})."
            ),
            color=typer.colors.YELLOW,
        )

    if split_worker_cap_per_config < max_requested_split_workers:
        _emit_status(
            (
                "Resource guard capped split workers per active config to "
                f"{split_worker_cap_per_config} "
                f"(requested peak {max_requested_split_workers}; "
                f"split slots {effective_split_phase_slots})."
            ),
            color=typer.colors.YELLOW,
        )

    variant_rows: list[dict[str, Any]] = []
    indexed_variants = list(enumerate(variants, start=1))
    scheduler_phase_by_config: dict[int, str] = {}
    scheduler_event_offsets: dict[int, int] = {}
    scheduler_last_tick = time.monotonic()
    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_last_snapshot = ""
    scheduler_smart_enabled = bool(effective_smart_scheduler)
    scheduler_timeseries_last_snapshot = ""
    scheduler_timeseries_last_write_monotonic = source_started
    scheduler_timeseries_rows_written = 0
    scheduler_timeseries_heartbeat_seconds = max(
        ALL_METHOD_SCHEDULER_TIMESERIES_HEARTBEAT_SECONDS,
        ALL_METHOD_SCHEDULER_POLL_SECONDS,
    )
    scheduler_cpu_source = "proc_stat_linux"
    scheduler_cpu_samples_collected = 0
    scheduler_cpu_totals_last: tuple[int, int] | None = None
    scheduler_cpu_utilization_pct_last: float | None = None
    scheduler_cpu_utilization_pct_high_water = 0.0
    scheduler_admission_adjustments = 0
    scheduler_admission_pressure_boosts = 0
    scheduler_admission_saturation_clamps = 0
    scheduler_admission_cpu_hot_clamps = 0
    scheduler_admission_active_cap_peak = configured_inflight_pipelines
    scheduler_admission_guard_target_peak = min(
        max(1, total_variants),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_last_key: tuple[int, int, str] | None = None
    scheduler_admission_active_cap_current = configured_inflight_pipelines
    scheduler_admission_guard_target_current = min(
        max(1, total_variants),
        max(1, effective_split_phase_slots + effective_wing_backlog_target),
    )
    scheduler_admission_wing_target_current = effective_wing_backlog_target
    scheduler_admission_reason_current = "base"
    process_worker_probe_available: bool | None = None
    process_worker_probe_error: str | None = None
    config_executor_backends_seen: set[str] = set()

    def _scheduler_event_path(config_index: int) -> Path:
        return scheduler_events_dir / f"config_{config_index:03d}.jsonl"

    def _read_linux_cpu_totals() -> tuple[int, int] | None:
        try:
            with Path("/proc/stat").open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except OSError:
            return None
        line = str(first_line or "").strip()
        if not line:
            return None
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        values: list[int] = []
        for token in parts[1:]:
            try:
                values.append(int(token))
            except ValueError:
                return None
        if len(values) < 4:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle

    def _sample_host_cpu_utilization_pct() -> float | None:
        nonlocal scheduler_cpu_source
        nonlocal scheduler_cpu_samples_collected
        nonlocal scheduler_cpu_totals_last

        current = _read_linux_cpu_totals()
        if current is None:
            scheduler_cpu_source = "unavailable"
            scheduler_cpu_totals_last = None
            return None
        previous = scheduler_cpu_totals_last
        scheduler_cpu_totals_last = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        busy_delta = max(0, total_delta - max(0, idle_delta))
        scheduler_cpu_samples_collected += 1
        return max(0.0, min(100.0, (float(busy_delta) / float(total_delta)) * 100.0))

    def _scheduler_phase_for_event(event_name: str) -> str | None:
        event = str(event_name or "").strip()
        if event in {"config_started", "prep_started"}:
            return "prep"
        if event == "split_wait_started":
            return "split_wait"
        if event == "split_active_started":
            return "split_active"
        if event in {"split_active_finished", "post_started"}:
            return "post"
        if event in {"post_finished", "evaluate_started"}:
            return "evaluate"
        if event in {"evaluate_finished", "config_finished"}:
            return "done"
        return None

    def _poll_scheduler_events(active_indices: set[int]) -> None:
        for active_index in sorted(active_indices):
            event_path = _scheduler_event_path(active_index)
            if not event_path.exists():
                continue
            offset = max(0, scheduler_event_offsets.get(active_index, 0))
            with event_path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Ignoring malformed scheduler event in %s: %s",
                            event_path,
                            line[:160],
                        )
                        continue
                    if not isinstance(payload, dict):
                        continue
                    phase = _scheduler_phase_for_event(str(payload.get("event") or ""))
                    if phase is not None:
                        scheduler_phase_by_config[active_index] = phase
                scheduler_event_offsets[active_index] = handle.tell()

    def _compute_scheduler_counts(active_indices: set[int]) -> dict[str, int]:
        heavy_active = 0
        split_wait = 0
        prep_active = 0
        post_active = 0
        evaluate_active = 0
        for active_index in active_indices:
            phase = scheduler_phase_by_config.get(active_index, "prep")
            if phase == "split_active":
                heavy_active += 1
            elif phase == "split_wait":
                split_wait += 1
            elif phase == "post":
                post_active += 1
            elif phase == "evaluate":
                evaluate_active += 1
            elif phase == "done":
                continue
            else:
                prep_active += 1
        wing_backlog = split_wait + prep_active
        return {
            "heavy_active": heavy_active,
            "split_wait": split_wait,
            "prep_active": prep_active,
            "post_active": post_active,
            "evaluate_active": evaluate_active,
            "wing_backlog": wing_backlog,
            "active": len(active_indices),
        }

    def _tick_scheduler_metrics(*, active_indices: set[int], pending_count: int) -> dict[str, int]:
        nonlocal scheduler_last_tick
        nonlocal scheduler_capacity_seconds
        nonlocal scheduler_busy_seconds
        nonlocal scheduler_idle_gap_seconds
        nonlocal scheduler_wing_area_seconds
        nonlocal scheduler_max_wing_backlog
        nonlocal scheduler_max_active_pipelines
        nonlocal scheduler_max_eval_active
        nonlocal scheduler_cpu_utilization_pct_last
        nonlocal scheduler_cpu_utilization_pct_high_water

        now = time.monotonic()
        delta = max(0.0, now - scheduler_last_tick)
        counts = _compute_scheduler_counts(active_indices)
        scheduler_capacity_seconds += float(effective_split_phase_slots) * delta
        scheduler_busy_seconds += float(
            min(effective_split_phase_slots, counts["heavy_active"])
        ) * delta
        if pending_count > 0 and counts["heavy_active"] < effective_split_phase_slots:
            scheduler_idle_gap_seconds += delta
        scheduler_wing_area_seconds += float(counts["wing_backlog"]) * delta
        scheduler_max_wing_backlog = max(
            scheduler_max_wing_backlog,
            counts["wing_backlog"],
        )
        scheduler_max_active_pipelines = max(
            scheduler_max_active_pipelines,
            counts["active"],
        )
        scheduler_max_eval_active = max(
            scheduler_max_eval_active,
            counts["evaluate_active"],
        )
        sampled_cpu = _sample_host_cpu_utilization_pct()
        if sampled_cpu is not None:
            scheduler_cpu_utilization_pct_last = sampled_cpu
            scheduler_cpu_utilization_pct_high_water = max(
                scheduler_cpu_utilization_pct_high_water,
                sampled_cpu,
            )
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return (
            f"scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} "
            f"| wing {counts['wing_backlog']} "
            f"| eval {counts['evaluate_active']} "
            f"| active {counts['active']} | pending {max(0, pending_count)}"
        )

    def _write_scheduler_timeseries_row(
        *,
        counts: dict[str, int],
        pending_count: int,
        force: bool = False,
    ) -> None:
        nonlocal scheduler_timeseries_last_snapshot
        nonlocal scheduler_timeseries_last_write_monotonic
        nonlocal scheduler_timeseries_rows_written

        pending_safe = max(0, pending_count)
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_safe)
        now_monotonic = time.monotonic()
        write_due = (
            force
            or snapshot != scheduler_timeseries_last_snapshot
            or (
                now_monotonic - scheduler_timeseries_last_write_monotonic
                >= scheduler_timeseries_heartbeat_seconds
            )
        )
        if not write_due:
            return
        row = {
            "timestamp": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "monotonic_seconds": now_monotonic,
            "elapsed_seconds": max(0.0, now_monotonic - source_started),
            "snapshot": snapshot,
            "heavy_active": _report_count(counts.get("heavy_active")),
            "heavy_capacity": _report_count(effective_split_phase_slots),
            "split_wait": _report_count(counts.get("split_wait")),
            "prep_active": _report_count(counts.get("prep_active")),
            "post_active": _report_count(counts.get("post_active")),
            "evaluate_active": _report_count(counts.get("evaluate_active")),
            "wing_backlog": _report_count(counts.get("wing_backlog")),
            "active": _report_count(counts.get("active")),
            "pending": pending_safe,
            "cpu_utilization_pct": scheduler_cpu_utilization_pct_last,
            "admission_active_cap": scheduler_admission_active_cap_current,
            "admission_guard_target": scheduler_admission_guard_target_current,
            "admission_wing_target": scheduler_admission_wing_target_current,
            "admission_reason": scheduler_admission_reason_current,
        }
        try:
            with scheduler_timeseries_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Ignoring scheduler time-series write failure for %s: %s",
                scheduler_timeseries_path,
                exc,
            )
            return
        scheduler_timeseries_last_snapshot = snapshot
        scheduler_timeseries_last_write_monotonic = now_monotonic
        scheduler_timeseries_rows_written += 1

    def _emit_scheduler_snapshot(
        *,
        counts: dict[str, int],
        pending_count: int,
        force_timeseries: bool = False,
    ) -> None:
        nonlocal scheduler_last_snapshot
        _write_scheduler_timeseries_row(
            counts=counts,
            pending_count=pending_count,
            force=force_timeseries,
        )
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(
            counts=counts,
            pending_count=max(0, pending_count),
        )
        if snapshot == scheduler_last_snapshot:
            return
        scheduler_last_snapshot = snapshot
        _emit_status(snapshot, color=typer.colors.BRIGHT_BLACK)

    def _compute_scheduler_metrics_from_event_files(
        *,
        source_end_monotonic: float,
    ) -> dict[str, float | int] | None:
        rows: list[tuple[float, str, int]] = []
        for event_path in sorted(scheduler_events_dir.glob("config_*.jsonl")):
            try:
                lines = event_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event_name = str(payload.get("event") or "").strip()
                if not event_name:
                    continue
                event_time = _report_optional_metric(payload.get("monotonic_seconds"))
                event_index = _report_count(payload.get("config_index"))
                if event_time is None or event_index <= 0:
                    continue
                rows.append((event_time, event_name, event_index))
        if not rows:
            return None

        rows.sort(key=lambda item: item[0])
        phases: dict[int, str] = {}
        started_configs: set[int] = set()
        capacity_seconds = 0.0
        busy_seconds = 0.0
        idle_gap_seconds = 0.0
        wing_area_seconds = 0.0
        max_wing_backlog = 0
        max_active_pipelines = 0
        max_eval_active = 0

        def _counts() -> dict[str, int]:
            heavy_active = 0
            split_wait = 0
            prep_active = 0
            post_active = 0
            evaluate_active = 0
            for phase in phases.values():
                if phase == "split_active":
                    heavy_active += 1
                elif phase == "split_wait":
                    split_wait += 1
                elif phase == "post":
                    post_active += 1
                elif phase == "evaluate":
                    evaluate_active += 1
                elif phase == "done":
                    continue
                else:
                    prep_active += 1
            wing_backlog = split_wait + prep_active
            active = (
                heavy_active
                + split_wait
                + prep_active
                + post_active
                + evaluate_active
            )
            return {
                "heavy_active": heavy_active,
                "evaluate_active": evaluate_active,
                "wing_backlog": wing_backlog,
                "active": active,
            }

        previous_time = rows[0][0]
        for event_time, event_name, event_index in rows:
            delta = max(0.0, event_time - previous_time)
            counts = _counts()
            capacity_seconds += float(effective_split_phase_slots) * delta
            busy_seconds += float(
                min(effective_split_phase_slots, counts["heavy_active"])
            ) * delta
            if (
                len(started_configs) < total_variants
                and counts["heavy_active"] < effective_split_phase_slots
            ):
                idle_gap_seconds += delta
            wing_area_seconds += float(counts["wing_backlog"]) * delta
            max_wing_backlog = max(max_wing_backlog, counts["wing_backlog"])
            max_active_pipelines = max(max_active_pipelines, counts["active"])
            max_eval_active = max(max_eval_active, counts["evaluate_active"])
            previous_time = event_time

            mapped_phase = _scheduler_phase_for_event(event_name)
            if event_name == "config_started":
                started_configs.add(event_index)
            if mapped_phase is not None:
                phases[event_index] = mapped_phase
            if event_name == "config_finished":
                phases[event_index] = "done"

        tail_delta = max(0.0, source_end_monotonic - previous_time)
        if tail_delta > 0:
            counts = _counts()
            capacity_seconds += float(effective_split_phase_slots) * tail_delta
            busy_seconds += float(
                min(effective_split_phase_slots, counts["heavy_active"])
            ) * tail_delta
            if (
                len(started_configs) < total_variants
                and counts["heavy_active"] < effective_split_phase_slots
            ):
                idle_gap_seconds += tail_delta
            wing_area_seconds += float(counts["wing_backlog"]) * tail_delta
            max_wing_backlog = max(max_wing_backlog, counts["wing_backlog"])
            max_active_pipelines = max(max_active_pipelines, counts["active"])
            max_eval_active = max(max_eval_active, counts["evaluate_active"])

        return {
            "heavy_slot_capacity_seconds": capacity_seconds,
            "heavy_slot_busy_seconds": busy_seconds,
            "idle_gap_seconds": idle_gap_seconds,
            "wing_backlog_area_seconds": wing_area_seconds,
            "max_wing_backlog": max_wing_backlog,
            "max_active_pipelines_observed": max_active_pipelines,
            "max_eval_active_observed": max_eval_active,
        }

    def _finalize_scheduler_metrics() -> dict[str, Any]:
        event_metrics = _compute_scheduler_metrics_from_event_files(
            source_end_monotonic=time.monotonic()
        )
        capacity_seconds = scheduler_capacity_seconds
        busy_seconds = scheduler_busy_seconds
        idle_gap_seconds = scheduler_idle_gap_seconds
        wing_area_seconds = scheduler_wing_area_seconds
        max_wing_backlog = scheduler_max_wing_backlog
        max_active = scheduler_max_active_pipelines
        max_eval_active = scheduler_max_eval_active
        if isinstance(event_metrics, dict):
            capacity_seconds = _report_metric(
                event_metrics.get("heavy_slot_capacity_seconds")
            )
            busy_seconds = _report_metric(event_metrics.get("heavy_slot_busy_seconds"))
            idle_gap_seconds = _report_metric(event_metrics.get("idle_gap_seconds"))
            wing_area_seconds = _report_metric(event_metrics.get("wing_backlog_area_seconds"))
            max_wing_backlog = max(
                max_wing_backlog,
                _report_count(event_metrics.get("max_wing_backlog")),
            )
            max_active = max(
                max_active,
                _report_count(event_metrics.get("max_active_pipelines_observed")),
            )
            max_eval_active = max(
                max_eval_active,
                _report_count(event_metrics.get("max_eval_active_observed")),
            )
        utilization_pct = (
            (busy_seconds / capacity_seconds) * 100.0
            if capacity_seconds > 0
            else 0.0
        )
        avg_wing_backlog = (
            wing_area_seconds / capacity_seconds
            if capacity_seconds > 0
            else 0.0
        )
        return {
            "mode": "smart" if scheduler_smart_enabled else "fixed",
            "configured_inflight_pipelines": configured_inflight_pipelines,
            "effective_inflight_pipelines": effective_inflight_pipelines,
            "split_phase_slots_requested": requested_split_phase_slots,
            "split_phase_slots": effective_split_phase_slots,
            "split_phase_slot_mode": split_phase_slot_mode,
            "split_phase_slot_cap_by_cpu": split_phase_slot_cap_by_cpu,
            "split_phase_slot_cap_by_memory": split_phase_slot_cap_by_memory,
            "split_worker_cap_per_config": split_worker_cap_per_config,
            "split_worker_cap_by_cpu": split_worker_guard.get("split_worker_cap_by_cpu"),
            "split_worker_cap_by_memory": split_worker_guard.get(
                "split_worker_cap_by_memory"
            ),
            "wing_backlog_target": effective_wing_backlog_target,
            "eval_tail_headroom_mode": eval_tail_headroom_mode,
            "eval_tail_headroom_configured": configured_eval_tail_headroom,
            "eval_tail_headroom_effective": effective_eval_tail_headroom,
            "max_active_during_eval": max_active_during_eval,
            "adaptive_overcommit_limit": adaptive_overcommit_limit,
            "adaptive_max_guard_target": adaptive_max_guard_target,
            "source_parallelism_effective": scheduler_source_parallelism,
            "cpu_budget_per_source": scheduler_cpu_budget_per_source,
            "cpu_budget_total": scheduler_cpu_budget_total,
            "max_eval_tail_pipelines": effective_eval_tail_headroom,
            "smart_tail_buffer_slots": (
                effective_eval_tail_headroom if bool(effective_smart_scheduler) else 0
            ),
            "smart_scheduler_enabled": bool(effective_smart_scheduler),
            "heavy_slot_capacity_seconds": capacity_seconds,
            "heavy_slot_busy_seconds": busy_seconds,
            "heavy_slot_utilization_pct": utilization_pct,
            "avg_wing_backlog": avg_wing_backlog,
            "max_wing_backlog": max_wing_backlog,
            "idle_gap_seconds": idle_gap_seconds,
            "max_active_pipelines_observed": max_active,
            "max_eval_active_observed": max_eval_active,
            "adaptive_admission_adjustments": scheduler_admission_adjustments,
            "adaptive_admission_pressure_boosts": scheduler_admission_pressure_boosts,
            "adaptive_admission_saturation_clamps": scheduler_admission_saturation_clamps,
            "adaptive_admission_cpu_hot_clamps": scheduler_admission_cpu_hot_clamps,
            "adaptive_admission_active_cap_peak": scheduler_admission_active_cap_peak,
            "adaptive_admission_guard_target_peak": scheduler_admission_guard_target_peak,
            "timeseries_path": str(scheduler_timeseries_path),
            "timeseries_row_count": scheduler_timeseries_rows_written,
            "timeseries_heartbeat_seconds": scheduler_timeseries_heartbeat_seconds,
            "snapshot_poll_seconds": ALL_METHOD_SCHEDULER_POLL_SECONDS,
            "cpu_utilization_source": scheduler_cpu_source,
            "cpu_utilization_samples": scheduler_cpu_samples_collected,
            "cpu_utilization_pct_high_water": scheduler_cpu_utilization_pct_high_water,
        }

    def _shutdown_parallel_executor(
        executor: Any,
        *,
        terminate_workers: bool,
    ) -> None:
        if terminate_workers:
            worker_map = getattr(executor, "_processes", None)
            if isinstance(worker_map, dict):
                for process in list(worker_map.values()):
                    if process is None:
                        continue
                    try:
                        if process.is_alive():
                            process.terminate()
                    except Exception:
                        continue
                for process in list(worker_map.values()):
                    if process is None:
                        continue
                    try:
                        process.join(timeout=1.0)
                        if process.is_alive() and hasattr(process, "kill"):
                            process.kill()
                    except Exception:
                        continue
        shutdown_fn = getattr(executor, "shutdown", None)
        if not callable(shutdown_fn):
            return
        try:
            shutdown_fn(wait=not terminate_workers, cancel_futures=terminate_workers)
        except TypeError:
            shutdown_fn(wait=not terminate_workers)
        except Exception:
            return

    def _latest_rows_by_config(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_by_index: dict[int, dict[str, Any]] = {}
        for row in rows:
            config_index = _report_count(row.get("config_index"))
            latest_by_index[config_index] = row
        return [latest_by_index[index] for index in sorted(latest_by_index)]

    def _run_serial_variants(
        items: list[tuple[int, AllMethodVariant]],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        for config_index, variant in items:
            progress_label = format_task_counter(
                "Running",
                config_index,
                max(1, total_variants),
                noun="config",
            )
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.start_config(
                    source_index=dashboard_source_index,
                    config_index=config_index,
                    config_total=max(1, total_variants),
                    config_slug=variant.slug,
                )
            _emit_status(f"{progress_label}: {variant.slug}", color=typer.colors.CYAN)

            def _variant_progress(message: str) -> None:
                if progress_callback is None:
                    return
                if dashboard is None:
                    if _is_structured_progress_message(message):
                        _notify_progress_callback(progress_callback, message)
                        return
                    _notify_progress_callback(
                        progress_callback,
                        f"{progress_label}: {variant.slug} | {message}",
                    )
                    return
                if _is_structured_progress_message(message):
                    _notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                _notify_progress_callback(progress_callback, dashboard.render())

            row = _run_all_method_prediction_once(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                variant=variant,
                config_index=config_index,
                total_variants=max(1, total_variants),
                root_output_dir=root_output_dir,
                scratch_root=scratch_root,
                processed_output_root=processed_output_root,
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                max_concurrent_split_phases=effective_split_phase_slots,
                split_phase_gate_dir=split_phase_gate_dir,
                scheduler_events_dir=scheduler_events_dir,
                alignment_cache_dir=canonical_alignment_cache_dir,
                prediction_reuse_cache_dir=prediction_reuse_cache_dir,
                split_worker_cap_per_config=split_worker_cap_per_config,
                progress_callback=_variant_progress if progress_callback else None,
            )
            variant_rows.append(row)

            success = str(row.get("status") or "").strip().lower() == "ok"
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.complete_config(
                    source_index=dashboard_source_index,
                    success=success,
                    config_index=config_index,
                )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        f"Completed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: {variant.slug}"
                    )
            else:
                _emit_status(
                    (
                        f"Failed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

    def _run_parallel_variants(
        items: list[tuple[int, AllMethodVariant]],
        *,
        dashboard_tracking: bool = True,
    ) -> None:
        nonlocal process_worker_probe_available
        nonlocal process_worker_probe_error
        nonlocal scheduler_smart_enabled
        nonlocal scheduler_admission_adjustments
        nonlocal scheduler_admission_pressure_boosts
        nonlocal scheduler_admission_saturation_clamps
        nonlocal scheduler_admission_cpu_hot_clamps
        nonlocal scheduler_admission_active_cap_peak
        nonlocal scheduler_admission_guard_target_peak
        nonlocal scheduler_admission_last_key
        nonlocal scheduler_admission_active_cap_current
        nonlocal scheduler_admission_guard_target_current
        nonlocal scheduler_admission_wing_target_current
        nonlocal scheduler_admission_reason_current
        force_parallel_timeout = effective_config_timeout_seconds is not None
        serial_by_limits = (
            len(items) <= 1 or effective_inflight_pipelines <= 1
        ) and not force_parallel_timeout
        if serial_by_limits:
            config_executor_backends_seen.add("serial")
            _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
            return
        executor_backend = "process"
        process_workers_available, process_worker_error = (
            _probe_all_method_process_pool_executor()
        )
        if process_workers_available:
            picklable, picklable_error = _probe_all_method_process_worker_picklable()
            if not picklable:
                process_workers_available = False
                process_worker_error = picklable_error
        process_worker_probe_available = bool(process_workers_available)
        process_worker_probe_error = (
            str(process_worker_error).strip() if process_worker_error else None
        )
        if not process_workers_available:
            detail = (
                f" ({process_worker_error})"
                if isinstance(process_worker_error, str) and process_worker_error
                else ""
            )
            if require_process_workers:
                raise RuntimeError(
                    "Process-based config concurrency is required, but runtime probe "
                    f"reported it unavailable{detail}."
                )
            _emit_status(
                (
                    "Process-based config concurrency unavailable"
                    f"{detail}; using thread-based config concurrency."
                ),
                color=typer.colors.YELLOW,
            )
            executor_backend = "thread"
        config_executor_backends_seen.add(str(executor_backend))

        pending_items = list(items)
        futures: dict[Any, tuple[int, AllMethodVariant, float]] = {}
        worker_limit = min(effective_inflight_pipelines, len(items))
        scheduler_base_target = min(
            total_variants,
            effective_split_phase_slots + effective_wing_backlog_target,
        )

        try:
            executor = (
                ProcessPoolExecutor(max_workers=worker_limit)
                if executor_backend == "process"
                else ThreadPoolExecutor(max_workers=worker_limit)
            )
        except (PermissionError, OSError) as exc:
            if executor_backend == "process":
                if require_process_workers:
                    raise RuntimeError(
                        "Process-based config concurrency is required, but process "
                        f"executor startup failed: {exc}"
                    ) from exc
                _emit_status(
                    (
                        "Process-based config concurrency unavailable "
                        f"({exc}); using thread-based config concurrency."
                    ),
                    color=typer.colors.YELLOW,
                )
                executor_backend = "thread"
                config_executor_backends_seen.add("thread")
                try:
                    executor = ThreadPoolExecutor(max_workers=worker_limit)
                except Exception as thread_exc:  # noqa: BLE001
                    _emit_status(
                        (
                            "Thread-based config concurrency unavailable "
                            f"({thread_exc}); running single-config execution."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    config_executor_backends_seen.add("serial")
                    _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
                    return
            else:
                _emit_status(
                    (
                        "Thread-based config concurrency unavailable "
                        f"({exc}); running single-config execution."
                    ),
                    color=typer.colors.YELLOW,
                )
                config_executor_backends_seen.add("serial")
                _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
                return

        def _record_completion(
            *,
            config_index: int,
            variant: AllMethodVariant,
            row: dict[str, Any],
        ) -> None:
            variant_rows.append(row)
            success = str(row.get("status") or "").strip().lower() == "ok"
            scheduler_phase_by_config.pop(config_index, None)
            scheduler_event_offsets.pop(config_index, None)
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.complete_config(
                    source_index=dashboard_source_index,
                    success=success,
                    config_index=config_index,
                )
            if success:
                if progress_callback is not None:
                    _emit_status(
                        (
                            "Completed "
                            f"{format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                            f"{variant.slug}"
                        )
                    )
            else:
                _emit_status(
                    (
                        f"Failed {format_task_counter('', config_index, max(1, total_variants), noun='config')}: "
                        f"{row.get('error', 'unknown error')}"
                    ),
                    color=typer.colors.RED,
                )

        def _submit_next() -> bool:
            if not pending_items:
                return False
            config_index, variant = pending_items.pop(0)
            progress_label = format_task_counter(
                "Running",
                config_index,
                max(1, total_variants),
                noun="config",
            )
            if (
                dashboard_tracking
                and dashboard is not None
                and dashboard_source_index is not None
            ):
                dashboard.start_config(
                    source_index=dashboard_source_index,
                    config_index=config_index,
                    config_total=max(1, total_variants),
                    config_slug=variant.slug,
                )
            _emit_status(f"{progress_label}: {variant.slug}", color=typer.colors.CYAN)

            try:
                future = executor.submit(
                    _run_all_method_prediction_once,
                    gold_spans_path=gold_spans_path,
                    source_file=source_file,
                    variant=variant,
                    config_index=config_index,
                    total_variants=max(1, total_variants),
                    root_output_dir=root_output_dir,
                    scratch_root=scratch_root,
                    processed_output_root=processed_output_root,
                    overlap_threshold=overlap_threshold,
                    force_source_match=force_source_match,
                    max_concurrent_split_phases=effective_split_phase_slots,
                    split_phase_gate_dir=split_phase_gate_dir,
                    scheduler_events_dir=scheduler_events_dir,
                    alignment_cache_dir=canonical_alignment_cache_dir,
                    prediction_reuse_cache_dir=prediction_reuse_cache_dir,
                    split_worker_cap_per_config=split_worker_cap_per_config,
                    progress_callback=None,
                )
            except Exception as exc:  # noqa: BLE001
                row = _all_method_failed_row(
                    config_index=config_index,
                    config_dir_name=_all_method_config_dir_name(config_index, variant),
                    variant=variant,
                    error=f"Failed to submit benchmark config: {exc}",
                )
                _record_completion(
                    config_index=config_index,
                    variant=variant,
                    row=row,
                )
                return True

            futures[future] = (config_index, variant, time.monotonic())
            scheduler_phase_by_config[config_index] = "prep"
            scheduler_event_offsets[config_index] = 0
            return True

        def _refresh_admission_decision(
            *,
            counts: dict[str, int],
            pending_count: int,
        ) -> _AllMethodSchedulerAdmissionDecision:
            nonlocal scheduler_admission_adjustments
            nonlocal scheduler_admission_pressure_boosts
            nonlocal scheduler_admission_saturation_clamps
            nonlocal scheduler_admission_cpu_hot_clamps
            nonlocal scheduler_admission_active_cap_peak
            nonlocal scheduler_admission_guard_target_peak
            nonlocal scheduler_admission_last_key
            nonlocal scheduler_admission_active_cap_current
            nonlocal scheduler_admission_guard_target_current
            nonlocal scheduler_admission_wing_target_current
            nonlocal scheduler_admission_reason_current

            decision = _resolve_all_method_scheduler_admission(
                counts=counts,
                pending_count=pending_count,
                total_variants=max(1, total_variants),
                configured_inflight_pipelines=configured_inflight_pipelines,
                split_phase_slots=effective_split_phase_slots,
                wing_backlog_target=effective_wing_backlog_target,
                max_active_during_eval=max_active_during_eval,
                adaptive_overcommit_limit=adaptive_overcommit_limit,
                adaptive_max_guard_target=max(
                    scheduler_base_target,
                    adaptive_max_guard_target,
                ),
                smart_scheduler_enabled=scheduler_smart_enabled,
                cpu_utilization_pct=scheduler_cpu_utilization_pct_last,
            )
            decision_key = (decision.active_cap, decision.guard_target, decision.reason)
            if scheduler_admission_last_key is None:
                scheduler_admission_last_key = decision_key
            elif decision_key != scheduler_admission_last_key:
                scheduler_admission_adjustments += 1
                scheduler_admission_last_key = decision_key
                if decision.pressure_boost > 0:
                    scheduler_admission_pressure_boosts += 1
                if decision.saturation_clamp:
                    scheduler_admission_saturation_clamps += 1
                if decision.cpu_hot_clamp:
                    scheduler_admission_cpu_hot_clamps += 1
            scheduler_admission_active_cap_peak = max(
                scheduler_admission_active_cap_peak,
                decision.active_cap,
            )
            scheduler_admission_guard_target_peak = max(
                scheduler_admission_guard_target_peak,
                decision.guard_target,
            )
            scheduler_admission_active_cap_current = decision.active_cap
            scheduler_admission_guard_target_current = decision.guard_target
            scheduler_admission_wing_target_current = decision.wing_target
            scheduler_admission_reason_current = decision.reason
            return decision

        try:
            while pending_items or futures:
                active_indices = {
                    config_index for config_index, _variant, _submitted in futures.values()
                }
                counts = _tick_scheduler_metrics(
                    active_indices=active_indices,
                    pending_count=len(pending_items),
                )
                if active_indices:
                    try:
                        _poll_scheduler_events(active_indices)
                    except Exception as exc:  # noqa: BLE001
                        if scheduler_smart_enabled:
                            scheduler_smart_enabled = False
                            _emit_status(
                                (
                                    "Smart scheduler telemetry failed "
                                    f"({exc}); falling back to fixed queue refill."
                                ),
                                color=typer.colors.YELLOW,
                            )
                counts = _compute_scheduler_counts(
                    {
                        config_index
                        for config_index, _variant, _submitted in futures.values()
                    }
                )
                if (
                    dashboard_tracking
                    and dashboard is not None
                    and dashboard_source_index is not None
                ):
                    for active_index in sorted(active_indices):
                        dashboard.set_config_phase(
                            source_index=dashboard_source_index,
                            config_index=active_index,
                            phase=scheduler_phase_by_config.get(active_index, "prep"),
                        )
                admission_decision = _refresh_admission_decision(
                    counts=counts,
                    pending_count=len(pending_items),
                )
                _emit_scheduler_snapshot(
                    counts=counts,
                    pending_count=len(pending_items),
                )

                while len(futures) < worker_limit and pending_items:
                    heavy_plus_wing = counts["heavy_active"] + counts["wing_backlog"]
                    if counts["active"] >= admission_decision.active_cap:
                        break
                    if (
                        heavy_plus_wing >= admission_decision.guard_target
                        and counts["active"] >= configured_inflight_pipelines
                    ):
                        break
                    submitted = _submit_next()
                    if not submitted:
                        break
                    counts = _compute_scheduler_counts(
                        {
                            config_index
                            for config_index, _variant, _submitted in futures.values()
                        }
                    )
                    admission_decision = _refresh_admission_decision(
                        counts=counts,
                        pending_count=len(pending_items),
                    )
                    _emit_scheduler_snapshot(
                        counts=counts,
                        pending_count=len(pending_items),
                    )

                if not futures:
                    if pending_items:
                        time.sleep(ALL_METHOD_SCHEDULER_POLL_SECONDS)
                    continue

                done, _ = wait(
                    list(futures.keys()),
                    timeout=ALL_METHOD_SCHEDULER_POLL_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                for done_future in done:
                    config_index, variant, _submitted = futures.pop(done_future)
                    try:
                        row = done_future.result()
                    except Exception as exc:  # noqa: BLE001
                        row = _all_method_failed_row(
                            config_index=config_index,
                            config_dir_name=_all_method_config_dir_name(config_index, variant),
                            variant=variant,
                            error=f"Benchmark config worker failed: {exc}",
                        )
                    _record_completion(
                        config_index=config_index,
                        variant=variant,
                        row=row,
                    )

                if (
                    effective_config_timeout_seconds is None
                    or executor_backend != "process"
                ):
                    continue
                timeout_threshold = float(max(1, effective_config_timeout_seconds))
                now = time.monotonic()
                timed_out: list[tuple[Any, int, AllMethodVariant, float]] = []
                for future, (config_index, variant, submitted_at) in list(futures.items()):
                    elapsed_seconds = max(0.0, now - submitted_at)
                    if elapsed_seconds < timeout_threshold:
                        continue
                    timed_out.append((future, config_index, variant, elapsed_seconds))
                if not timed_out:
                    continue

                timed_out.sort(key=lambda item: item[1])
                for timed_out_future, config_index, variant, elapsed_seconds in timed_out:
                    futures.pop(timed_out_future, None)
                    row = _all_method_failed_row(
                        config_index=config_index,
                        config_dir_name=_all_method_config_dir_name(config_index, variant),
                        variant=variant,
                        error=(
                            f"Config timed out after {int(timeout_threshold)}s "
                            f"(elapsed {elapsed_seconds:.1f}s)."
                        ),
                        elapsed_seconds=elapsed_seconds,
                    )
                    _record_completion(
                        config_index=config_index,
                        variant=variant,
                        row=row,
                    )

                if futures:
                    requeued = sorted(
                        [
                            (config_index, variant)
                            for config_index, variant, _submitted in futures.values()
                        ],
                        key=lambda item: item[0],
                    )
                    pending_items = requeued + pending_items
                    futures.clear()
                scheduler_smart_enabled = False
                _emit_status(
                    (
                        "Config timeout reached for "
                        f"{len(timed_out)} run(s); restarting process worker pool."
                    ),
                    color=typer.colors.YELLOW,
                )
                _shutdown_parallel_executor(executor, terminate_workers=True)
                try:
                    executor = ProcessPoolExecutor(max_workers=worker_limit)
                except (PermissionError, OSError) as exc:
                    if require_process_workers:
                        raise RuntimeError(
                            "Process-based config concurrency is required, but process "
                            f"pool restart failed after timeout: {exc}"
                        ) from exc
                    _emit_status(
                        (
                            "Process-based config concurrency unavailable after timeout "
                            f"restart ({exc}); using thread-based config concurrency for remaining configs."
                        ),
                        color=typer.colors.YELLOW,
                    )
                    executor_backend = "thread"
                    config_executor_backends_seen.add("thread")
                    try:
                        executor = ThreadPoolExecutor(max_workers=worker_limit)
                    except Exception as thread_exc:  # noqa: BLE001
                        _emit_status(
                            (
                                "Thread-based config concurrency unavailable "
                                f"({thread_exc}); running remaining configs as single-config execution."
                            ),
                            color=typer.colors.YELLOW,
                        )
                        config_executor_backends_seen.add("serial")
                        _run_serial_variants(
                            pending_items,
                            dashboard_tracking=dashboard_tracking,
                        )
                        pending_items.clear()
                        futures.clear()
                        break
        finally:
            _shutdown_parallel_executor(executor, terminate_workers=False)

    _run_parallel_variants(indexed_variants, dashboard_tracking=True)
    variant_rows = _latest_rows_by_config(variant_rows)
    initial_failed_indices = [
        _report_count(row.get("config_index"))
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    retry_passes_executed = 0
    retry_recovered_configs = 0
    if effective_retry_failed_configs > 0 and initial_failed_indices:
        variant_by_index = {config_index: variant for config_index, variant in indexed_variants}
        remaining_failed_indices = sorted(set(initial_failed_indices))
        for retry_pass in range(1, effective_retry_failed_configs + 1):
            if not remaining_failed_indices:
                break
            retry_items = [
                (config_index, variant_by_index[config_index])
                for config_index in remaining_failed_indices
                if config_index in variant_by_index
            ]
            if not retry_items:
                break
            retry_passes_executed += 1
            _emit_status(
                (
                    f"Retry pass {retry_pass}/{effective_retry_failed_configs}: "
                    f"rerunning {len(retry_items)} failed config(s)."
                ),
                color=typer.colors.YELLOW,
            )
            prior_failed = set(remaining_failed_indices)
            _run_parallel_variants(retry_items, dashboard_tracking=False)
            variant_rows = _latest_rows_by_config(variant_rows)
            remaining_failed_indices = sorted(
                {
                    _report_count(row.get("config_index"))
                    for row in variant_rows
                    if str(row.get("status") or "").strip().lower() != "ok"
                }
            )
            recovered_this_pass = len(prior_failed - set(remaining_failed_indices))
            retry_recovered_configs += max(0, recovered_this_pass)
            if recovered_this_pass > 0:
                _emit_status(
                    (
                        f"Retry pass {retry_pass} recovered "
                        f"{recovered_this_pass} config(s)."
                    ),
                    color=typer.colors.CYAN,
                )
    _tick_scheduler_metrics(active_indices=set(), pending_count=0)
    _emit_scheduler_snapshot(
        counts=_compute_scheduler_counts(set()),
        pending_count=0,
        force_timeseries=True,
    )
    scheduler_summary = _finalize_scheduler_metrics()
    scheduler_summary["config_timeout_seconds"] = effective_config_timeout_seconds
    scheduler_summary["failed_retry_limit"] = effective_retry_failed_configs
    scheduler_summary["retry_passes_executed"] = retry_passes_executed
    scheduler_summary["retry_recovered_configs"] = retry_recovered_configs

    variant_rows = _latest_rows_by_config(variant_rows)
    prediction_success_rows = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() == "ok"
    ]
    failed_rows: list[dict[str, Any]] = [
        dict(row)
        for row in variant_rows
        if str(row.get("status") or "").strip().lower() != "ok"
    ]
    prediction_reuse_summary = _all_method_prediction_reuse_summary(
        prediction_success_rows
    )

    successful_rows: list[dict[str, Any]] = []
    signature_candidate_rows: list[dict[str, Any]] = []
    evaluation_signatures_unique = 0
    evaluation_runs_executed = 0
    evaluation_results_reused_in_run = 0
    evaluation_results_reused_cross_run = 0
    eval_signature_cache_dir = _resolve_all_method_eval_signature_cache_dir(
        root_output_dir=root_output_dir,
        alignment_cache_dir=canonical_alignment_cache_dir,
    )

    for row in prediction_success_rows:
        prediction_record_path = _resolve_all_method_prediction_record_path(
            root_output_dir=root_output_dir,
            row=row,
        )
        if (
            prediction_record_path is None
            or not prediction_record_path.exists()
            or not prediction_record_path.is_file()
        ):
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = "Prediction record path is missing for signature build."
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        sequence_matcher = str(row.get("benchmark_sequence_matcher") or "").strip() or "dmp"
        try:
            eval_signature = _build_all_method_eval_signature(
                gold_spans_path=gold_spans_path,
                prediction_record_path=prediction_record_path,
                eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                sequence_matcher=sequence_matcher,
            )
        except Exception as exc:  # noqa: BLE001
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = f"Failed to build evaluation signature: {exc}"
            failed_row["evaluation_result_source"] = "failed"
            failed_rows.append(failed_row)
            continue
        row["eval_signature"] = eval_signature
        row["benchmark_sequence_matcher"] = sequence_matcher
        signature_candidate_rows.append(row)

    grouped_by_signature = _group_all_method_rows_by_eval_signature(signature_candidate_rows)
    evaluation_signatures_unique = len(grouped_by_signature)
    grouped_items = sorted(
        grouped_by_signature.items(),
        key=lambda item: min(_report_count(row.get("config_index")) for row in item[1]),
    )
    for signature_index, (eval_signature, group_rows) in enumerate(grouped_items, start=1):
        if not group_rows:
            continue
        ordered_group = sorted(
            group_rows,
            key=lambda row: _report_count(row.get("config_index")),
        )
        representative_row = ordered_group[0]
        representative_config_dir = str(representative_row.get("config_dir") or "").strip()
        if not representative_config_dir:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative config directory is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        representative_eval_output_dir = root_output_dir / representative_config_dir
        representative_processed_output_dir = processed_output_root / representative_config_dir
        representative_prediction_record = _resolve_all_method_prediction_record_path(
            root_output_dir=root_output_dir,
            row=representative_row,
        )
        if representative_prediction_record is None:
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = "Representative prediction record is missing."
                failed_row["evaluation_result_source"] = "failed"
                failed_rows.append(failed_row)
            continue
        sequence_matcher = str(representative_row.get("benchmark_sequence_matcher") or "").strip()
        if not sequence_matcher:
            sequence_matcher = "dmp"

        cache_path = eval_signature_cache_dir / f"{eval_signature}.json"
        cache_entry = _load_all_method_eval_signature_cache_entry(
            cache_path=cache_path,
            expected_signature=eval_signature,
        )

        evaluation_result_source_for_group = "executed"
        evaluation_summary: dict[str, Any]
        if cache_entry is not None:
            cached_report = cache_entry.get("report")
            if not isinstance(cached_report, dict):
                cached_report = {}
            cached_md = str(cache_entry.get("report_md") or "")
            eval_report_json_path, eval_report_md_path = (
                _materialize_all_method_cached_eval_outputs(
                    eval_output_dir=representative_eval_output_dir,
                    report_payload=cached_report,
                    report_md_text=cached_md,
                )
            )
            metric_bundle = _benchmark_report_metric_bundle(cached_report)
            evaluation_summary = {
                "status": "ok",
                "error": "",
                **metric_bundle,
                "timing": _normalize_timing_payload(cached_report.get("timing")),
                "report": cached_report,
                "report_md_text": cached_md,
                "eval_report_json_path": eval_report_json_path,
                "eval_report_md_path": eval_report_md_path,
                "duration_seconds": 0.0,
            }
            evaluation_result_source_for_group = "reused_cross_run"
            evaluation_results_reused_cross_run += len(ordered_group)
        else:
            _emit_status(
                (
                    "Evaluating signature "
                    f"{signature_index}/{max(1, evaluation_signatures_unique)} "
                    f"(group size {len(ordered_group)})."
                ),
                color=typer.colors.CYAN,
            )
            evaluation_summary = _run_all_method_evaluate_prediction_record_once(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                prediction_record_path=representative_prediction_record,
                eval_output_dir=representative_eval_output_dir,
                processed_output_dir=representative_processed_output_dir,
                sequence_matcher=sequence_matcher,
                epub_extractor=_row_dimension_str(representative_row, "epub_extractor"),
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                alignment_cache_dir=canonical_alignment_cache_dir,
                progress_callback=None,
            )
            if str(evaluation_summary.get("status") or "").strip().lower() == "ok":
                evaluation_runs_executed += 1
                if len(ordered_group) > 1:
                    evaluation_results_reused_in_run += len(ordered_group) - 1
                cached_payload = {
                    "schema_version": ALL_METHOD_EVAL_SIGNATURE_RESULT_CACHE_SCHEMA_VERSION,
                    "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "eval_signature": eval_signature,
                    "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                    "sequence_matcher": sequence_matcher,
                    "source_file": str(source_file),
                    "gold_spans_path": str(gold_spans_path),
                    "report": evaluation_summary.get("report"),
                    "report_md": evaluation_summary.get("report_md_text"),
                }
                try:
                    _write_all_method_eval_signature_cache_entry(
                        cache_path=cache_path,
                        payload=cached_payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Ignoring eval-signature cache write failure for %s: %s",
                        cache_path,
                        exc,
                    )

        if str(evaluation_summary.get("status") or "").strip().lower() != "ok":
            error_text = str(evaluation_summary.get("error") or "Evaluation failed.")
            for row in ordered_group:
                failed_row = dict(row)
                failed_row["status"] = "failed"
                failed_row["error"] = error_text
                failed_row["evaluation_result_source"] = "failed"
                failed_row["evaluation_representative_config_dir"] = representative_config_dir
                failed_row["eval_signature"] = eval_signature
                failed_rows.append(failed_row)
            continue

        summary_timing = _normalize_timing_payload(evaluation_summary.get("timing"))
        summary_evaluation_seconds = _report_optional_metric(
            summary_timing.get("evaluation_seconds")
        )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                summary_timing.get("total_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = _report_optional_metric(
                evaluation_summary.get("duration_seconds")
            )
        if summary_evaluation_seconds is None:
            summary_evaluation_seconds = 0.0

        summary_eval_wall_seconds = max(
            0.0,
            _report_metric(evaluation_summary.get("duration_seconds")),
        )
        summary_report_json_path = Path(str(evaluation_summary.get("eval_report_json_path") or ""))
        summary_report_md_path = Path(str(evaluation_summary.get("eval_report_md_path") or ""))
        alignment_guardrail_fields = _all_method_extract_alignment_guardrail_fields(
            cast(dict[str, Any] | None, evaluation_summary.get("report"))
        )

        for row in ordered_group:
            result_row = dict(row)
            is_representative = (
                _report_count(result_row.get("config_index"))
                == _report_count(representative_row.get("config_index"))
            )
            row_result_source = "executed"
            if evaluation_result_source_for_group == "reused_cross_run":
                row_result_source = "reused_cross_run"
            elif not is_representative:
                row_result_source = "reused_in_run"

            row_timing = _normalize_timing_payload(result_row.get("timing"))
            prediction_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
            if prediction_total_seconds is None:
                prediction_total_seconds = _report_optional_metric(
                    result_row.get("duration_seconds")
                )
            if prediction_total_seconds is None:
                prediction_total_seconds = 0.0

            row_eval_seconds = summary_evaluation_seconds if row_result_source == "executed" else 0.0
            row_eval_wall = summary_eval_wall_seconds if row_result_source == "executed" else 0.0
            row_total_seconds = max(0.0, prediction_total_seconds + row_eval_seconds)
            row_timing = _timing_with_updates(
                row_timing,
                evaluation_seconds=row_eval_seconds,
                total_seconds=row_total_seconds,
                checkpoints={
                    "all_method_eval_wall_seconds": row_eval_wall,
                    "all_method_eval_reused_in_run": (
                        1.0 if row_result_source == "reused_in_run" else 0.0
                    ),
                    "all_method_eval_reused_cross_run": (
                        1.0 if row_result_source == "reused_cross_run" else 0.0
                    ),
                },
            )

            result_row["status"] = "ok"
            result_row["error"] = ""
            result_row["precision"] = _report_metric(evaluation_summary.get("precision"))
            result_row["recall"] = _report_metric(evaluation_summary.get("recall"))
            result_row["f1"] = _report_metric(evaluation_summary.get("f1"))
            result_row["practical_precision"] = _report_metric(
                evaluation_summary.get("practical_precision")
            )
            result_row["practical_recall"] = _report_metric(
                evaluation_summary.get("practical_recall")
            )
            result_row["practical_f1"] = _report_metric(evaluation_summary.get("practical_f1"))
            result_row.update(alignment_guardrail_fields)
            result_row["eval_signature"] = eval_signature
            result_row["evaluation_result_source"] = row_result_source
            result_row["evaluation_representative_config_dir"] = representative_config_dir
            result_row["duration_seconds"] = row_total_seconds
            result_row["timing"] = row_timing
            result_row["eval_report_json"] = _path_for_manifest(
                root_output_dir,
                summary_report_json_path,
            )
            result_row["eval_report_md"] = _path_for_manifest(
                root_output_dir,
                summary_report_md_path,
            )
            successful_rows.append(result_row)

    failed_rows.sort(key=lambda row: _report_count(row.get("config_index")))
    successful_rows.sort(
        key=lambda row: (
            _report_metric(row.get("f1")),
            _report_metric(row.get("practical_f1")),
            _report_metric(row.get("precision")),
            _report_metric(row.get("recall")),
        ),
        reverse=True,
    )
    for rank, row in enumerate(successful_rows, start=1):
        row["rank"] = rank

    matcher_guardrails = _all_method_build_matcher_guardrails(successful_rows)
    scheduler_summary["matcher_guardrails"] = matcher_guardrails
    for warning in matcher_guardrails.get("warnings", []):
        _emit_status(f"Matcher guardrail warning: {warning}", color=typer.colors.YELLOW)

    successful_timing: list[tuple[dict[str, Any], float]] = []
    for row in successful_rows:
        row_timing = _normalize_timing_payload(row.get("timing"))
        row_total_seconds = _report_optional_metric(row_timing.get("total_seconds"))
        if row_total_seconds is None:
            row_total_seconds = _report_optional_metric(row.get("duration_seconds"))
        if row_total_seconds is None:
            continue
        row["timing"] = _timing_with_updates(
            row_timing,
            total_seconds=row_total_seconds,
        )
        successful_timing.append((row, row_total_seconds))

    source_wall_seconds = max(0.0, time.monotonic() - source_started)
    total_config_seconds = sum(seconds for _row, seconds in successful_timing)
    average_config_seconds = (
        total_config_seconds / len(successful_timing) if successful_timing else None
    )
    median_config_seconds = _median_metric(
        [seconds for _row, seconds in successful_timing]
    )
    slowest_config_row = (
        max(successful_timing, key=lambda item: item[1])[0] if successful_timing else None
    )
    slowest_config_seconds = (
        max(seconds for _row, seconds in successful_timing) if successful_timing else None
    )

    winner = successful_rows[0] if successful_rows else None
    final_rows = successful_rows + failed_rows

    report_payload: dict[str, Any] = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_file": str(source_file),
        "gold_spans_path": str(gold_spans_path),
        "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        "scheduler_scope": "per_source",
        "variant_count": total_variants,
        "successful_variants": len(successful_rows),
        "failed_variants": len(failed_rows),
        "evaluation_signatures_unique": evaluation_signatures_unique,
        "evaluation_runs_executed": evaluation_runs_executed,
        "evaluation_results_reused_in_run": evaluation_results_reused_in_run,
        "evaluation_results_reused_cross_run": evaluation_results_reused_cross_run,
        "prediction_signatures_unique": _report_count(
            prediction_reuse_summary.get("prediction_signatures_unique")
        ),
        "prediction_runs_executed": _report_count(
            prediction_reuse_summary.get("prediction_runs_executed")
        ),
        "prediction_results_reused_in_run": _report_count(
            prediction_reuse_summary.get("prediction_results_reused_in_run")
        ),
        "prediction_results_reused_cross_run": _report_count(
            prediction_reuse_summary.get("prediction_results_reused_cross_run")
        ),
        "split_convert_input_groups": _report_count(
            prediction_reuse_summary.get("split_convert_input_groups")
        ),
        "split_convert_reuse_candidates": _report_count(
            prediction_reuse_summary.get("split_convert_reuse_candidates")
        ),
        "split_convert_reuse_safe_candidates": _report_count(
            prediction_reuse_summary.get("split_convert_reuse_safe_candidates")
        ),
        "split_convert_reuse_blocked_by_prediction_variance": _report_count(
            prediction_reuse_summary.get(
                "split_convert_reuse_blocked_by_prediction_variance"
            )
        ),
        "prediction_reuse_key_schema_version": (
            ALL_METHOD_PREDICTION_REUSE_KEY_SCHEMA_VERSION
        ),
        "split_convert_input_key_schema_version": (
            ALL_METHOD_SPLIT_CONVERT_INPUT_KEY_SCHEMA_VERSION
        ),
        "evaluation_signature_cache_dir": str(eval_signature_cache_dir),
        "retry_failed_configs_requested": effective_retry_failed_configs,
        "retry_passes_executed": retry_passes_executed,
        "retry_recovered_configs": retry_recovered_configs,
        "include_codex_farm_requested": include_codex_farm_requested,
        "include_codex_farm_effective": include_codex_farm_effective,
        "prediction_reuse_cache_dir": str(prediction_reuse_cache_dir),
        "executor_resolution": {
            "process_workers_required": bool(require_process_workers),
            "process_worker_probe_available": process_worker_probe_available,
            "process_worker_probe_error": process_worker_probe_error,
            "config_executor_backends_seen": sorted(config_executor_backends_seen),
        },
        "timing_summary": {
            "source_wall_seconds": source_wall_seconds,
            "config_total_seconds": total_config_seconds,
            "config_average_seconds": average_config_seconds,
            "config_median_seconds": median_config_seconds,
            "slowest_config_dir": (
                str(slowest_config_row.get("config_dir"))
                if isinstance(slowest_config_row, dict)
                else None
            ),
            "slowest_config_seconds": slowest_config_seconds,
        },
        "scheduler": scheduler_summary,
        "variants": final_rows,
        "winner_by_f1": winner,
    }

    report_json_path = root_output_dir / "all_method_benchmark_report.json"
    report_json_path.write_text(
        json.dumps(report_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_md_path = root_output_dir / "all_method_benchmark_report.md"
    report_md_path.write_text(
        _render_all_method_report_md(report_payload),
        encoding="utf-8",
    )

    if refresh_dashboard_after_source:
        history_csv_path = history_csv_for_output(
            processed_output_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
        )
        resolved_dashboard_output_root = (
            dashboard_output_root.expanduser()
            if dashboard_output_root is not None
            else None
        )
        _refresh_dashboard_after_history_write(
            csv_path=history_csv_path,
            output_root=resolved_dashboard_output_root,
            dashboard_out_dir=(
                history_root_for_output(resolved_dashboard_output_root) / "dashboard"
                if resolved_dashboard_output_root is not None
                else None
            ),
            reason="all-method benchmark source batch append",
        )

    completion_color = (
        typer.colors.GREEN if len(failed_rows) == 0 else typer.colors.YELLOW
    )
    _emit_status(
        (
            "All method benchmark complete: "
            f"{len(successful_rows)}/{total_variants} configs evaluated successfully."
        ),
        color=completion_color,
    )
    if progress_callback is None:
        if successful_rows:
            typer.secho("Top configurations by strict F1:", fg=typer.colors.CYAN)
            for row in successful_rows[:3]:
                typer.echo(
                    (
                        f"  {row.get('rank')}) {row.get('config_dir')} "
                        f"p={_report_metric(row.get('precision')):.3f} "
                        f"r={_report_metric(row.get('recall')):.3f} "
                        f"f1={_report_metric(row.get('f1')):.3f}"
                    )
                )
        typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)
    return report_md_path


def _path_for_manifest(run_root: Path, path_like: Path | str | None) -> str | None:
    if path_like is None:
        return None
    candidate = Path(path_like)
    try:
        return str(candidate.relative_to(run_root))
    except ValueError:
        return str(candidate)


def _write_stage_observability_best_effort(
    *,
    run_root: Path,
    run_kind: str,
    run_dt: dt.datetime,
    run_config: dict[str, Any] | None,
) -> Path | None:
    try:
        report = build_stage_observability_report(
            run_root=run_root,
            run_kind=run_kind,
            created_at=run_dt.isoformat(timespec="seconds"),
            run_config=run_config,
        )
        return write_stage_observability_report(run_root=run_root, report=report)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Warning: failed to write stage_observability.json in {run_root}: {exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        logger.warning("Failed to write stage_observability.json in %s: %s", run_root, exc)
        return None


def _load_stage_observability_payload(run_root: Path) -> dict[str, Any]:
    path = run_root / "stage_observability.json"
    if not path.exists():
        return {}
    try:
        report = load_stage_observability_report(path)
    except Exception:  # noqa: BLE001
        return {}
    return report.model_dump(exclude_none=True)


def _write_run_manifest_best_effort(run_root: Path, manifest: RunManifest) -> None:
    try:
        write_run_manifest(run_root, manifest)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Warning: failed to write run_manifest.json in {run_root}: {exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        logger.warning("Failed to write run_manifest.json in %s: %s", run_root, exc)


def _write_stage_run_manifest(
    *,
    run_root: Path,
    output_root: Path,
    requested_path: Path,
    run_dt: dt.datetime,
    run_config: dict[str, Any],
) -> None:
    report_paths = sorted(run_root.glob("*.excel_import_report.json"))
    importer_name: str | None = None
    if report_paths:
        try:
            report_payload = json.loads(report_paths[0].read_text(encoding="utf-8"))
            if isinstance(report_payload, dict):
                importer_name = str(report_payload.get("importerName") or "").strip() or None
        except (OSError, json.JSONDecodeError):
            importer_name = None

    source_hash: str | None = None
    if requested_path.is_file():
        try:
            source_hash = compute_file_hash(requested_path)
        except Exception as exc:  # noqa: BLE001
            typer.secho(
                f"Warning: failed to compute source hash for run manifest: {exc}",
                fg=typer.colors.YELLOW,
                err=True,
            )

    artifacts: dict[str, Any] = {}
    if report_paths:
        artifacts["reports"] = [path.name for path in report_paths]
    for path_name, artifact_key in (
        (NONRECIPE_SEED_ROUTING_FILE_NAME, "nonrecipe_seed_routing_json"),
        (NONRECIPE_REVIEW_EXCLUSIONS_FILE_NAME, "nonrecipe_review_exclusions_jsonl"),
        (NONRECIPE_AUTHORITY_FILE_NAME, "nonrecipe_authority_json"),
        (NONRECIPE_REVIEW_STATUS_FILE_NAME, "nonrecipe_review_status_json"),
    ):
        target = run_root / path_name
        if target.exists():
            artifacts[artifact_key] = path_name
    for path_key, artifact_key in (
        ("label_det", "label_det_dir"),
        ("label_llm_correct", "label_llm_correct_dir"),
        ("group_recipe_spans", "group_recipe_spans_dir"),
        ("intermediate drafts", "intermediate_drafts_dir"),
        ("final drafts", "final_drafts_dir"),
        ("chunks", "chunks_dir"),
        ("knowledge", "knowledge_dir"),
        (".bench", "bench_dir"),
        ("raw", "raw_dir"),
    ):
        target = run_root / path_key
        if target.exists():
            artifacts[artifact_key] = path_key
    bench_prediction_paths = sorted(
        run_root.glob(".bench/**/stage_block_predictions.json")
    )
    if bench_prediction_paths:
        artifacts["stage_block_predictions"] = [
            str(path.relative_to(run_root))
            for path in bench_prediction_paths
        ]
    knowledge_index = run_root / "knowledge" / "knowledge_index.json"
    if knowledge_index.exists():
        artifacts["knowledge_index"] = str(knowledge_index.relative_to(run_root))
    processing_timeseries = run_root / PROCESSING_TIMESERIES_FILENAME
    if processing_timeseries.exists():
        artifacts["processing_timeseries_jsonl"] = str(
            processing_timeseries.relative_to(run_root)
        )
    stage_observability_json = run_root / "stage_observability.json"
    if stage_observability_json.exists():
        artifacts["stage_observability_json"] = str(
            stage_observability_json.relative_to(run_root)
        )
    run_summary_json = run_root / "run_summary.json"
    if run_summary_json.exists():
        artifacts["run_summary_json"] = str(run_summary_json.relative_to(run_root))
    run_summary_md = run_root / "run_summary.md"
    if run_summary_md.exists():
        artifacts["run_summary_md"] = str(run_summary_md.relative_to(run_root))
    stage_worker_resolution = run_root / "stage_worker_resolution.json"
    if stage_worker_resolution.exists():
        artifacts["stage_worker_resolution_json"] = str(
            stage_worker_resolution.relative_to(run_root)
        )
    prompt_artifacts_dir = run_root / "prompts"
    if prompt_artifacts_dir.exists() and prompt_artifacts_dir.is_dir():
        artifacts["prompts_dir"] = str(prompt_artifacts_dir.relative_to(run_root))
        prompt_request_response_path = (
            prompt_artifacts_dir / "prompt_request_response_log.txt"
        )
        if prompt_request_response_path.exists() and prompt_request_response_path.is_file():
            artifacts["prompt_request_response_txt"] = str(
                prompt_request_response_path.relative_to(run_root)
            )
        category_manifest_path = (
            prompt_artifacts_dir / "prompt_category_logs_manifest.txt"
        )
        if category_manifest_path.exists() and category_manifest_path.is_file():
            artifacts["prompt_category_logs_manifest_txt"] = str(
                category_manifest_path.relative_to(run_root)
            )
        full_prompt_log_path = prompt_artifacts_dir / "full_prompt_log.jsonl"
        if full_prompt_log_path.exists() and full_prompt_log_path.is_file():
            artifacts["full_prompt_log_jsonl"] = str(
                full_prompt_log_path.relative_to(run_root)
            )
        prompt_log_summary_path = (
            prompt_artifacts_dir / llm_prompt_artifacts.PROMPT_LOG_SUMMARY_JSON_NAME
        )
        if prompt_log_summary_path.exists() and prompt_log_summary_path.is_file():
            artifacts["prompt_log_summary_json"] = str(
                prompt_log_summary_path.relative_to(run_root)
            )
        prompt_type_samples_path = (
            prompt_artifacts_dir
            / llm_prompt_artifacts.PROMPT_TYPE_SAMPLES_MD_NAME
        )
        if prompt_type_samples_path.exists() and prompt_type_samples_path.is_file():
            artifacts["prompt_type_samples_from_full_prompt_log_md"] = str(
                prompt_type_samples_path.relative_to(run_root)
            )
        thinking_trace_summary_jsonl_path = (
            prompt_artifacts_dir
            / llm_prompt_artifacts.THINKING_TRACE_SUMMARY_JSONL_NAME
        )
        if (
            thinking_trace_summary_jsonl_path.exists()
            and thinking_trace_summary_jsonl_path.is_file()
        ):
            artifacts["thinking_trace_summary_jsonl"] = str(
                thinking_trace_summary_jsonl_path.relative_to(run_root)
            )
        thinking_trace_summary_md_path = (
            prompt_artifacts_dir
            / llm_prompt_artifacts.THINKING_TRACE_SUMMARY_MD_NAME
        )
        if (
            thinking_trace_summary_md_path.exists()
            and thinking_trace_summary_md_path.is_file()
        ):
            artifacts["thinking_trace_summary_md"] = str(
                thinking_trace_summary_md_path.relative_to(run_root)
            )
    history_csv = history_csv_for_output(output_root)
    if history_csv.exists():
        artifacts["history_csv"] = str(history_csv)

    manifest = RunManifest(
        run_kind="stage",
        run_id=run_root.name,
        created_at=run_dt.isoformat(timespec="seconds"),
        source=RunSource(
            path=str(requested_path),
            source_hash=source_hash,
            importer_name=importer_name,
        ),
        run_config=run_config,
        artifacts=artifacts,
        notes="Stage run outputs for cookbook import.",
    )
    _write_run_manifest_best_effort(run_root, manifest)


def _write_knowledge_index_best_effort(run_root: Path) -> None:
    knowledge_root = run_root / "knowledge"
    if not knowledge_root.exists():
        return
    workbooks: dict[str, dict[str, Any]] = {}
    total_snippets = 0
    for workbook_dir in sorted(path for path in knowledge_root.iterdir() if path.is_dir()):
        snippets_path = workbook_dir / "snippets.jsonl"
        preview_path = workbook_dir / "knowledge.md"
        if not snippets_path.exists() and not preview_path.exists():
            continue
        snippets_count = 0
        if snippets_path.exists():
            snippets_count = sum(
                1 for line in snippets_path.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        total_snippets += snippets_count
        workbook_slug = workbook_dir.name
        workbooks[workbook_slug] = {
            "snippets": snippets_count,
            "snippets_path": str(snippets_path.relative_to(run_root)) if snippets_path.exists() else None,
            "preview_path": str(preview_path.relative_to(run_root)) if preview_path.exists() else None,
        }
    if not workbooks:
        return
    index_path = knowledge_root / "knowledge_index.json"
    index_payload = {
        "version": 1,
        "total_snippets": total_snippets,
        "workbooks": workbooks,
    }
    try:
        index_path.write_text(
            json.dumps(index_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write knowledge_index.json in %s: %s", knowledge_root, exc)


def _write_eval_run_manifest(
    *,
    run_root: Path,
    run_kind: str,
    source_path: str | None,
    source_hash: str | None,
    importer_name: str | None,
    run_config: dict[str, Any],
    artifacts: dict[str, Any],
    notes: str | None = None,
) -> None:
    try:
        write_eval_run_manifest(
            run_root=run_root,
            run_kind=run_kind,
            source_path=source_path,
            source_hash=source_hash,
            importer_name=importer_name,
            run_config=run_config,
            artifacts=artifacts,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Warning: failed to write run_manifest.json in {run_root}: {exc}",
            fg=typer.colors.YELLOW,
            err=True,
        )
        logger.warning("Failed to write run_manifest.json in %s: %s", run_root, exc)


def _finalize_interrupted_benchmark_run(
    *,
    eval_output_dir: Path,
    source_path: Path | None,
    source_hash: str | None,
    pred_run: Path | None,
    processed_run_root: Path | None,
    selected_gold: Path | None,
    selected_eval_mode: str | None,
    predictions_in_path: Path | None,
    predictions_out_path: Path | None,
    should_upload_predictions: bool,
    write_markdown: bool,
    write_label_studio_tasks: bool,
    phase: str,
) -> None:
    interrupted_at = dt.datetime.now().isoformat(timespec="seconds")
    resolved_pred_run = next(
        (
            candidate
            for candidate in (
                pred_run,
                eval_output_dir,
                eval_output_dir / "prediction-run",
            )
            if candidate is not None and candidate.exists()
        ),
        pred_run,
    )
    prompt_budget_summary_path: Path | None = None
    if resolved_pred_run is not None:
        manifest_path = resolved_pred_run / "manifest.json"
        if manifest_path.exists() and manifest_path.is_file():
            try:
                manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                manifest_payload = None
            if isinstance(manifest_payload, dict):
                prompt_budget_summary = build_prediction_run_prompt_budget_summary(
                    manifest_payload,
                    resolved_pred_run,
                )
                if (
                    isinstance(prompt_budget_summary.get("by_stage"), dict)
                    and prompt_budget_summary["by_stage"]
                ):
                    prompt_budget_summary_path = (
                        write_prediction_run_prompt_budget_summary(
                            eval_output_dir,
                            prompt_budget_summary,
                        )
                    )
    knowledge_stage_summaries: list[dict[str, Any]] = []
    if resolved_pred_run is not None:
        raw_llm_root = resolved_pred_run / "raw" / "llm"
        if raw_llm_root.exists() and raw_llm_root.is_dir():
            for workbook_dir in sorted(path for path in raw_llm_root.iterdir() if path.is_dir()):
                knowledge_stage_dir = workbook_dir / stage_artifact_stem(
                    "nonrecipe_knowledge_review"
                )
                if not knowledge_stage_dir.exists() or not knowledge_stage_dir.is_dir():
                    continue
                knowledge_summary = summarize_knowledge_stage_artifacts(knowledge_stage_dir)
                knowledge_summary["workbook_slug"] = workbook_dir.name
                knowledge_summary["stage_dir"] = _path_for_manifest(
                    eval_output_dir,
                    knowledge_stage_dir,
                )
                knowledge_summary["status_artifact"] = _path_for_manifest(
                    eval_output_dir,
                    knowledge_stage_dir / KNOWLEDGE_STAGE_STATUS_FILE_NAME,
                )
                knowledge_stage_summaries.append(knowledge_summary)
    status_payload = {
        "schema_version": 1,
        "status": "interrupted",
        "completed": False,
        "interruption_cause": "operator",
        "finalization_completeness": "interrupted_before_completion",
        "interrupted_at": interrupted_at,
        "phase": str(phase or "").strip() or None,
        "source_file": str(source_path) if source_path is not None else None,
        "source_hash": str(source_hash or "").strip() or None,
    }
    benchmark_status_path = eval_output_dir / "benchmark_status.json"
    benchmark_status_path.write_text(
        json.dumps(status_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    partial_summary_payload = {
        "schema_version": 1,
        "status": "interrupted",
        "interruption_cause": "operator",
        "finalization_completeness": "interrupted_before_completion",
        "summary": (
            "Benchmark interrupted before completion. Inspect the preserved prediction "
            "artifacts and telemetry under this run root."
        ),
        "phase": str(phase or "").strip() or None,
        "prediction_artifacts": {
            "prediction_run_dir": _path_for_manifest(eval_output_dir, resolved_pred_run),
            "processed_output_run_dir": _path_for_manifest(
                eval_output_dir,
                processed_run_root,
            ),
            "gold_spans_jsonl": _path_for_manifest(eval_output_dir, selected_gold),
            "processing_timeseries_prediction_jsonl": _path_for_manifest(
                eval_output_dir,
                eval_output_dir / "processing_timeseries_prediction.jsonl",
            ),
            "processing_timeseries_evaluation_jsonl": _path_for_manifest(
                eval_output_dir,
                eval_output_dir / "processing_timeseries_evaluation.jsonl",
            ),
            "prompt_budget_summary_json": _path_for_manifest(
                eval_output_dir,
                prompt_budget_summary_path,
            ),
        },
    }
    if len(knowledge_stage_summaries) == 1:
        partial_summary_payload["knowledge_stage"] = knowledge_stage_summaries[0]
    elif knowledge_stage_summaries:
        partial_summary_payload["knowledge_stages"] = knowledge_stage_summaries
    partial_summary_path = eval_output_dir / "partial_benchmark_summary.json"
    partial_summary_path.write_text(
        json.dumps(partial_summary_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifacts = {
        "benchmark_status_json": _path_for_manifest(eval_output_dir, benchmark_status_path),
        "partial_benchmark_summary_json": _path_for_manifest(
            eval_output_dir,
            partial_summary_path,
        ),
        "artifact_root_dir": _path_for_manifest(eval_output_dir, resolved_pred_run),
        "gold_spans_jsonl": _path_for_manifest(eval_output_dir, selected_gold),
    }
    prediction_timeseries_path = eval_output_dir / "processing_timeseries_prediction.jsonl"
    evaluation_timeseries_path = eval_output_dir / "processing_timeseries_evaluation.jsonl"
    if prediction_timeseries_path.exists():
        artifacts["processing_timeseries_prediction_jsonl"] = _path_for_manifest(
            eval_output_dir,
            prediction_timeseries_path,
        )
    if evaluation_timeseries_path.exists():
        artifacts["processing_timeseries_evaluation_jsonl"] = _path_for_manifest(
            eval_output_dir,
            evaluation_timeseries_path,
        )
    if prompt_budget_summary_path is not None and prompt_budget_summary_path.exists():
        artifacts["prompt_budget_summary_json"] = _path_for_manifest(
            eval_output_dir,
            prompt_budget_summary_path,
        )
        artifacts["actual_costs_json"] = _path_for_manifest(
            eval_output_dir,
            prompt_budget_summary_path,
        )
    _write_eval_run_manifest(
        run_root=eval_output_dir,
        run_kind="labelstudio_benchmark",
        source_path=str(source_path) if source_path is not None else None,
        source_hash=str(source_hash or "").strip() or None,
        importer_name=_infer_importer_name_from_source_path(source_path),
        run_config={
            "status": "interrupted",
            "completed": False,
            "phase": str(phase or "").strip() or None,
            "eval_mode": str(selected_eval_mode or "").strip() or None,
            "prediction_record_input": (
                str(predictions_in_path) if predictions_in_path is not None else None
            ),
            "prediction_record_output": (
                str(predictions_out_path) if predictions_out_path is not None else None
            ),
            "upload": bool(should_upload_predictions),
            "write_markdown": bool(write_markdown),
            "write_label_studio_tasks": bool(write_label_studio_tasks),
        },
        artifacts=artifacts,
        notes=(
            "Benchmark interrupted before completion. This manifest points to the "
            "preserved partial artifacts for inspection."
        ),
    )


def _require_importer(path: Path):
    importer, score = registry.best_importer_for_path(path)
    if importer is None or score <= 0:
        _fail("No importer available for this path.")
    return importer


def _infer_importer_name_from_source_path(source: str | Path | None) -> str | None:
    if source is None:
        return None
    try:
        suffix = Path(str(source)).suffix.lower()
    except Exception:
        return None
    if suffix == ".epub":
        return "epub"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".doc", ".docx", ".txt", ".md", ".rtf"}:
        return "text"
    if suffix in {".html", ".htm"}:
        return "web"
    return None


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if path.is_file() and not path.name.startswith("."):
            yield path


def _resolve_mapping_path(workbook: Path, out: Path, override: Path | None) -> Path | None:
    if override is not None:
        return override
    sidecar_yaml = workbook.with_suffix(".mapping.yaml")
    sidecar_json = workbook.with_suffix(".mapping.json")
    if sidecar_yaml.exists():
        return sidecar_yaml
    if sidecar_json.exists():
        return sidecar_json
    staged = out / "mappings" / f"{workbook.stem}.mapping.yaml"
    if staged.exists():
        return staged
    return None


def _resolve_overrides_path(workbook: Path, out: Path, override: Path | None) -> Path | None:
    if override is not None:
        return override
    sidecar_yaml = workbook.with_suffix(".overrides.yaml")
    sidecar_json = workbook.with_suffix(".overrides.json")
    if sidecar_yaml.exists():
        return sidecar_yaml
    if sidecar_json.exists():
        return sidecar_json
    staged = out / "overrides" / f"{workbook.stem}.overrides.yaml"
    if staged.exists():
        return staged
    return None


def _merge_raw_artifacts(
    out: Path,
    workbook_slug: str,
    job_results: list[dict[str, Any]],
    *,
    output_stats: OutputStats | None = None,
) -> None:
    job_parts_root = out / ".job_parts" / workbook_slug
    if not job_parts_root.exists():
        return

    for job in job_results:
        job_index = int(job.get("job_index", 0))
        job_raw_root = job_parts_root / f"job_{job_index}" / "raw"
        if not job_raw_root.exists():
            continue
        for raw_path in job_raw_root.rglob("*"):
            if raw_path.is_dir():
                continue
            relative = raw_path.relative_to(job_raw_root)
            target = out / "raw" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = _prefix_collision(target, job_index)
            shutil.move(str(raw_path), str(target))
            if output_stats is not None:
                output_stats.record_path(OUTPUT_STATS_CATEGORY_RAW, target)

    shutil.rmtree(job_parts_root, ignore_errors=True)
    job_parts_parent = out / ".job_parts"
    try:
        if job_parts_parent.exists() and not any(job_parts_parent.iterdir()):
            job_parts_parent.rmdir()
    except OSError:
        pass


def _prefix_collision(path: Path, job_index: int) -> Path:
    prefix = f"job_{job_index}_"
    candidate = path.with_name(f"{prefix}{path.name}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{prefix}{counter}_{path.name}")
        counter += 1
    return candidate


def _write_error_report(
    out: Path,
    file_path: Path,
    run_dt: dt.datetime,
    errors: list[str],
    *,
    importer_name: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
) -> None:
    report = ConversionReport(
        errors=errors,
        sourceFile=str(file_path),
        importerName=importer_name,
        runTimestamp=run_dt.isoformat(timespec="seconds"),
        runConfig=dict(run_config) if run_config is not None else None,
        runConfigHash=run_config_hash,
        runConfigSummary=run_config_summary,
    )
    write_report(report, out, file_path.stem)


def _job_range_start(job: dict[str, Any]) -> int:
    start_page = job.get("start_page")
    if start_page is not None:
        return int(start_page)
    start_spine = job.get("start_spine")
    if start_spine is not None:
        return int(start_spine)
    return 0


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_non_negative_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _collect_stage_run_report_payloads(run_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for report_path in sorted(run_root.glob("*.excel_import_report.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        payloads.append((report_path, payload))
    return payloads


def _build_stage_run_summary_payload(
    *,
    run_root: Path,
    requested_path: Path,
    run_config: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    reports = _collect_stage_run_report_payloads(run_root)
    stage_observability_payload = _load_stage_observability_payload(run_root)
    observed_stages_raw = stage_observability_payload.get("stages")
    observed_stages = (
        observed_stages_raw if isinstance(observed_stages_raw, list) else []
    )

    totals: dict[str, int] = {
        "recipes": 0,
        "standalone_blocks": 0,
    }
    durations: dict[str, float] = {
        "total_seconds": 0.0,
        "parsing_seconds": 0.0,
        "writing_seconds": 0.0,
        "ocr_seconds": 0.0,
    }

    books: list[dict[str, Any]] = []
    for report_path, payload in reports:
        source_file = str(payload.get("sourceFile") or "").strip()
        book_slug = report_path.name.removesuffix(".excel_import_report.json")
        source_name = Path(source_file).name if source_file else f"{book_slug}"
        timing = payload.get("timing") if isinstance(payload.get("timing"), dict) else {}
        row = {
            "book_slug": book_slug,
            "source_file": source_file or None,
            "book_name": source_name,
            "importer": payload.get("importerName"),
            "recipes": _coerce_int(payload.get("totalRecipes")) or 0,
            "standalone_blocks": _coerce_int(payload.get("totalStandaloneBlocks")) or 0,
            "total_seconds": _coerce_non_negative_float(timing.get("total_seconds"))
            or 0.0,
            "parsing_seconds": _coerce_non_negative_float(
                timing.get("parsing_seconds")
            )
            or 0.0,
            "writing_seconds": _coerce_non_negative_float(
                timing.get("writing_seconds")
            )
            or 0.0,
            "ocr_seconds": _coerce_non_negative_float(timing.get("ocr_seconds")) or 0.0,
            "report_file": report_path.name,
        }
        books.append(row)
        totals["recipes"] += row["recipes"]
        totals["standalone_blocks"] += row["standalone_blocks"]
        durations["total_seconds"] += row["total_seconds"]
        durations["parsing_seconds"] += row["parsing_seconds"]
        durations["writing_seconds"] += row["writing_seconds"]
        durations["ocr_seconds"] += row["ocr_seconds"]

    codex_recipe = str(run_config.get("llm_recipe_pipeline", "off")).strip().lower()
    codex_knowledge = str(run_config.get("llm_knowledge_pipeline", "off")).strip().lower()
    codex_decision = {
        "context": run_config.get("codex_decision_context"),
        "mode": run_config.get("codex_decision_mode"),
        "allowed": run_config.get("codex_decision_allowed"),
        "explicit_activation_required": run_config.get(
            "codex_decision_explicit_activation_required"
        ),
        "explicit_activation_granted": run_config.get(
            "codex_decision_explicit_activation_granted"
        ),
        "codex_enabled": run_config.get("codex_decision_codex_enabled"),
        "codex_surfaces": run_config.get("codex_decision_codex_surfaces"),
        "deterministic_surfaces": run_config.get(
            "codex_decision_deterministic_surfaces"
        ),
        "summary": run_config.get("codex_decision_summary"),
        "ai_assistance_profile": run_config.get("ai_assistance_profile"),
    }

    return {
        "run_dir": run_root.name,
        "run_root": str(run_root),
        "requested_path": str(requested_path),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "book_count": len(books),
        "error_count": len(errors),
        "observed_stages": observed_stages,
        "books": books,
        "totals": {
            **totals,
            "files_with_reports": len(books),
            "errors": len(errors),
            **durations,
        },
        "major_settings": {
            **project_run_config_payload(run_config, include_internal=False),
            "effective_workers": run_config.get("effective_workers"),
        },
        "codex_farm": {
            "recipe_pipeline": codex_recipe,
            "knowledge_pipeline": codex_knowledge,
            "recipe_enabled": codex_recipe != "off",
            "knowledge_enabled": codex_knowledge != "off",
            "model": run_config.get("codex_farm_model"),
            "reasoning_effort": run_config.get("codex_farm_reasoning_effort"),
        },
        "codex_decision": codex_decision,
    }


def _write_stage_run_summary(
    *,
    run_root: Path,
    requested_path: Path,
    run_config: dict[str, Any],
    errors: list[str],
    write_markdown: bool = True,
) -> dict[str, Any] | None:
    payload = _build_stage_run_summary_payload(
        run_root=run_root,
        requested_path=requested_path,
        run_config=run_config,
        errors=errors,
    )

    run_summary_json = run_root / "run_summary.json"
    run_summary_md = run_root / "run_summary.md"

    try:
        run_summary_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Failed to write %s", run_summary_json)

    def _fmt_s(seconds: float | None) -> str:
        if seconds is None:
            return "n/a"
        return f"{seconds:.2f}s"

    totals = payload.get("totals", {})
    major_settings = payload.get("major_settings", {})
    codex = payload.get("codex_farm", {})
    codex_decision = payload.get("codex_decision", {})
    if write_markdown:
        md_lines = [
            f"# Stage run summary",
            f"Run: {payload.get('run_dir')}",
            f"Requested: {payload.get('requested_path')}",
            "",
            "## Observed stages",
        ]
        if payload.get("observed_stages"):
            for stage in payload.get("observed_stages", []):
                md_lines.append(
                    "- {label} (`{key}`)".format(
                        label=stage.get("stage_label") or stage.get("stage_key") or "Stage",
                        key=stage.get("stage_key") or "stage",
                    )
                )
        else:
            md_lines.append("- none")

        md_lines.extend(
            [
                "",
            "## Books",
            ]
        )
        if payload.get("books"):
            for book in payload.get("books", []):
                md_lines.append(
                    "- {name}: {recipes} recipes, {standalone_blocks} standalone blocks".format(
                        name=book.get("book_name") or book.get("book_slug") or "unknown",
                        recipes=book.get("recipes", 0),
                        standalone_blocks=book.get("standalone_blocks", 0),
                    )
                )
        else:
            md_lines.append("- none")

        md_lines.extend(
            [
                "",
                "## Major settings",
                f"- Codex decision: {codex_decision.get('summary') or 'n/a'}",
                f"- Codex-farm recipe pipeline: {codex.get('recipe_pipeline')}",
                f"- Codex-farm knowledge pipeline: {codex.get('knowledge_pipeline')}",
                f"- workers: {major_settings.get('workers')}",
                f"- effective_workers: {major_settings.get('effective_workers')}",
                f"- epub_extractor: {major_settings.get('epub_extractor')}",
                "",
                "## Topline metrics",
                "- total recipes: {recipes}".format(recipes=totals.get("recipes", 0)),
                "- total standalone blocks: {standalone_blocks}".format(
                    standalone_blocks=totals.get("standalone_blocks", 0)
                ),
                "- timing total/parsing/writing/ocr: {total}/{parsing}/{writing}/{ocr}".format(
                    total=_fmt_s(totals.get("total_seconds")),
                    parsing=_fmt_s(totals.get("parsing_seconds")),
                    writing=_fmt_s(totals.get("writing_seconds")),
                    ocr=_fmt_s(totals.get("ocr_seconds")),
                ),
                "",
                f"## Files",
                f"- reports: {payload.get('totals', {}).get('files_with_reports', 0)}",
                f"- errors: {payload.get('error_count', 0)}",
            ]
        )

        try:
            run_summary_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        except OSError:
            logger.warning("Failed to write %s", run_summary_md)
            return payload
    else:
        run_summary_md.unlink(missing_ok=True)

    return payload


def _print_stage_summary(payload: dict[str, Any], *, write_markdown: bool = True) -> None:
    books = payload.get("books")
    if not isinstance(books, list):
        return
    if books:
        book_names = [
            str(book.get("book_name") or book.get("book_slug") or "unknown")
            for book in books
        ]
    else:
        book_names = []

    totals = payload.get("totals", {})
    codex = payload.get("codex_farm", {})
    major_settings = payload.get("major_settings", {})
    observed_stages = payload.get("observed_stages")
    observed_stage_labels = []
    if isinstance(observed_stages, list):
        observed_stage_labels = [
            str(stage.get("stage_label") or stage.get("stage_key") or "Stage")
            for stage in observed_stages
            if isinstance(stage, dict)
        ]
    run_root = str(payload.get("run_root") or "").strip()
    run_summary_name = "run_summary.md" if write_markdown else "run_summary.json"
    run_summary_path = (
        str(Path(run_root) / run_summary_name)
        if run_root
        else f"{payload.get('run_dir')}/{run_summary_name}"
    )

    typer.secho("\nQuick run summary:", fg=typer.colors.CYAN)
    typer.echo(f"  Books ({len(book_names)}): {', '.join(book_names) if book_names else 'none'}")
    typer.echo(
        "  Observed stages: "
        + (", ".join(observed_stage_labels) if observed_stage_labels else "none")
    )
    typer.echo(
        "  Codex-farm (recipe/knowledge): {recipe}/{knowledge}".format(
            recipe=codex.get("recipe_pipeline", "off"),
            knowledge=codex.get("knowledge_pipeline", "off"),
        )
    )
    typer.echo(
        "  Settings: workers={workers} effective_workers={effective_workers} "
        "epub_extractor={epub_extractor}".format(
            workers=major_settings.get("workers"),
            effective_workers=major_settings.get("effective_workers"),
            epub_extractor=major_settings.get("epub_extractor"),
        )
    )
    typer.echo(
        "  Totals: recipes={recipes} standalone_blocks={standalone_blocks}".format(
            recipes=totals.get("recipes", 0),
            standalone_blocks=totals.get("standalone_blocks", 0),
        )
    )
    typer.echo(f"  Timing: total={totals.get('total_seconds', 0.0):.2f}s")
    typer.echo(f"  Run summary file: {run_summary_path}")


def _offset_mapping_int(payload: dict[str, Any], key: str, offset: int) -> None:
    value = _coerce_int(payload.get(key))
    if value is None:
        return
    payload[key] = value + offset


def _offset_location_fields(location: dict[str, Any], offset: int) -> None:
    for key in (
        "start_block",
        "end_block",
        "block_index",
        "startBlock",
        "endBlock",
        "blockIndex",
        "tip_block_index",
        "tipBlockIndex",
    ):
        _offset_mapping_int(location, key, offset)


def _offset_result_block_indices(result: ConversionResult, offset: int) -> None:
    if offset <= 0:
        return
    result.source_blocks = offset_source_blocks(result.source_blocks, offset)
    result.source_support = offset_source_support(result.source_support, offset)
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        location = provenance.get("location")
        if isinstance(location, dict):
            _offset_location_fields(location, offset)

    for block in result.non_recipe_blocks:
        if not isinstance(block, dict):
            continue
        _offset_mapping_int(block, "index", offset)
        location = block.get("location")
        if isinstance(location, dict):
            _offset_location_fields(location, offset)


def _load_split_job_full_blocks(job_raw_root: Path) -> list[dict[str, Any]]:
    full_text_paths = sorted(job_raw_root.glob("**/full_text.json"))
    for full_text_path in full_text_paths:
        try:
            payload = json.loads(full_text_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        blocks = payload.get("blocks")
        if not isinstance(blocks, list):
            continue
        return [dict(block) for block in blocks if isinstance(block, dict)]
    return []


def _build_split_full_blocks(
    *,
    out: Path,
    workbook_slug: str,
    ordered_jobs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, int], dict[int, int]]:
    merged: list[dict[str, Any]] = []
    job_offsets: dict[int, int] = {}
    job_block_counts: dict[int, int] = {}
    running_offset = 0

    for job in ordered_jobs:
        job_index = int(job.get("job_index", 0))
        job_offsets[job_index] = running_offset
        job_raw_root = out / ".job_parts" / workbook_slug / f"job_{job_index}" / "raw"
        blocks = _load_split_job_full_blocks(job_raw_root)
        adjusted_count = 0
        for fallback_index, block in enumerate(blocks):
            index = _coerce_int(block.get("index"))
            if index is None:
                index = fallback_index
            adjusted_block = dict(block)
            adjusted_index = index + running_offset
            adjusted_block["index"] = adjusted_index
            adjusted_block["block_id"] = f"b{adjusted_index}"
            merged.append(adjusted_block)
            adjusted_count += 1
        job_block_counts[job_index] = adjusted_count
        running_offset += adjusted_count

    merged.sort(key=lambda block: int(_coerce_int(block.get("index")) or 0))
    return merged, job_offsets, job_block_counts


def _merge_source_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    importer_name: str | None = None,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    write_markdown: bool = True,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    workbook_slug = slugify_name(file_path.stem)
    merge_stats = TimingStats()
    merge_start = time.monotonic()
    output_stats = OutputStats(out)

    def _report_status(message: str) -> None:
        if status_callback is None:
            return
        try:
            status_callback(message)
        except Exception:
            return

    ordered_jobs = sorted(job_results, key=_job_range_start)
    run_settings = RunSettings.from_dict(
        project_run_config_payload(run_config, contract=RUN_SETTING_CONTRACT_FULL),
        warn_context="source-job merge run config",
    )
    merged_full_blocks, job_offsets, _job_block_counts = _build_split_full_blocks(
        out=out,
        workbook_slug=workbook_slug,
        ordered_jobs=ordered_jobs,
    )
    for job in ordered_jobs:
        result = job.get("result")
        if result is None:
            continue
        offset = job_offsets.get(int(job.get("job_index", 0)), 0)
        _offset_result_block_indices(result, offset)

    phase_labels = [
        "Merging source-job payloads...",
        "Building authoritative stage outputs...",
        "Merging raw artifacts...",
        "Writing report...",
        "Merge done",
    ]
    phase_total = len(phase_labels)
    phase_current = 0

    def _report_phase(label: str) -> None:
        nonlocal phase_current
        phase_current += 1
        _report_status(
            format_phase_counter("merge", phase_current, phase_total, label=label)
        )

    _report_phase("Merging source-job payloads...")
    merged_source_blocks: list[Any] = []
    merged_source_support: list[Any] = []
    warnings: list[str] = []
    epub_backends: set[str] = set()

    for job in ordered_jobs:
        result = job.get("result")
        if result is None:
            continue
        merged_source_blocks.extend(result.source_blocks)
        merged_source_support.extend(result.source_support)
        if result.report and result.report.warnings:
            warnings.extend(result.report.warnings)
        if result.report and result.report.errors:
            for error in result.report.errors:
                warnings.append(f"Job {job.get('job_index')}: {error}")
        if result.report and result.report.epub_backend:
            epub_backends.add(str(result.report.epub_backend))

    resolved_importer_name = str(
        importer_name
        or ordered_jobs[0].get("importer_name")
        or ""
    ).strip()
    if not resolved_importer_name:
        detected_importer, detected_score = registry.best_importer_for_path(file_path)
        if detected_importer is not None and detected_score > 0:
            resolved_importer_name = str(detected_importer.name or "").strip()
    if not resolved_importer_name:
        raise ValueError(f"Could not determine importer for {file_path.name}.")
    file_hash = compute_file_hash(file_path)
    if merged_full_blocks:
        merged_full_text_path = (
            out / "raw" / resolved_importer_name / file_hash / "full_text.json"
        )
        merged_full_text_path.parent.mkdir(parents=True, exist_ok=True)
        merged_full_text_path.write_text(
            json.dumps(
                {
                    "blocks": merged_full_blocks,
                    "block_count": len(merged_full_blocks),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        output_stats.record_path(OUTPUT_STATS_CATEGORY_RAW, merged_full_text_path)

    report = ConversionReport(
        warnings=warnings,
        importerName=resolved_importer_name,
        runConfig=dict(run_config) if run_config is not None else None,
        runConfigHash=run_config_hash,
        runConfigSummary=run_config_summary,
    )
    if resolved_importer_name == "epub" and epub_backends:
        report.epub_backend = sorted(epub_backends)[0]
        if len(epub_backends) > 1:
            report.warnings.append(
                "epub_backend_inconsistent_across_split_jobs: "
                + ", ".join(sorted(epub_backends))
            )
    resolved_source_blocks = normalize_source_blocks(merged_full_blocks)
    if not resolved_source_blocks:
        resolved_source_blocks = normalize_source_blocks(merged_source_blocks)

    merged_result = ConversionResult(
        recipes=[],
        source_blocks=resolved_source_blocks,
        source_support=list(merged_source_support),
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=report,
        workbook=file_path.stem,
        workbook_path=str(file_path),
    )

    _report_phase("Building authoritative stage outputs...")
    session = execute_stage_import_session_from_result(
        result=merged_result,
        source_file=file_path,
        run_root=out,
        run_dt=run_dt,
        importer_name=resolved_importer_name,
        run_settings=run_settings,
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        mapping_config=mapping_config,
        write_markdown=write_markdown,
        progress_callback=_report_status,
        timing_stats=merge_stats,
        full_blocks=merged_full_blocks or None,
        write_raw_artifacts_enabled=False,
        output_stats=output_stats,
        recipe_limit=limit,
        recipe_limit_label=limit,
    )
    merged_result = session.conversion_result
    report = merged_result.report

    merge_stats.parsing_seconds = sum(
        float(job.get("timing", {}).get("parsing_seconds", 0.0)) for job in job_results
    )
    merge_stats.ocr_seconds = sum(
        float(job.get("timing", {}).get("ocr_seconds", 0.0)) for job in job_results
    )
    merge_overhead = max(0.0, time.monotonic() - merge_start - merge_stats.writing_seconds)
    merge_stats.checkpoints["merge_seconds"] = merge_overhead
    merge_stats.total_seconds = (
        merge_stats.parsing_seconds + merge_stats.writing_seconds + merge_overhead
    )

    _report_phase("Merging raw artifacts...")
    _merge_raw_artifacts(
        out,
        workbook_slug,
        job_results,
        output_stats=output_stats,
    )
    if output_stats.file_counts:
        report.output_stats = output_stats.to_report()
    report.timing = merge_stats.to_dict()
    _report_phase("Writing report...")
    write_report(report, out, file_path.stem)
    _report_phase("Merge done")

    return {
        "file": file_path.name,
        "status": "success",
        "recipes": len(merged_result.recipes),
        "duration": merge_stats.total_seconds,
    }
