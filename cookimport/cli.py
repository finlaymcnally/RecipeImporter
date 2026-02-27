from __future__ import annotations

import cProfile
import datetime as dt
import hashlib
import io
import json
import logging
import multiprocessing
import os
import pstats
import queue
import re
import shutil
import threading
import time
import zipfile
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Iterable, Iterator, Dict, Any, Annotated, Callable, TypeVar, cast

import questionary
import typer
from typer.models import OptionInfo
from prompt_toolkit.key_binding.key_bindings import KeyBindings, merge_key_bindings
from prompt_toolkit.keys import Keys
from questionary.prompts.common import Choice as QuestionaryChoice, Separator as QuestionarySeparator
from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.text import Text

from cookimport.cli_ui.run_settings_flow import choose_run_settings
from cookimport.config.last_run_store import save_last_run_settings
from cookimport.config.run_settings import (
    RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR,
    RunSettings,
    build_run_settings,
    compute_effective_workers,
)
from cookimport.epub_extractor_names import (
    EPUB_EXTRACTOR_CANONICAL_SET,
    epub_extractor_choices_for_help,
    normalize_epub_extractor_name,
)
from cookimport.core.mapping_io import load_mapping_config, save_mapping_config
from cookimport.core.models import ConversionReport, ConversionResult, MappingConfig
from cookimport.core.progress_messages import (
    format_phase_counter,
    format_task_counter,
    parse_worker_activity,
)
from cookimport.core.overrides_io import load_parsing_overrides
from cookimport.core.reporting import compute_file_hash, enrich_report_with_stats
from cookimport.core.slug import slugify_name
from cookimport.core.timing import TimingStats, measure
from cookimport.bench.eval_canonical_text import (
    evaluate_canonical_text,
    format_canonical_eval_report_md,
)
from cookimport.bench.eval_stage_blocks import (
    evaluate_stage_blocks,
    format_stage_block_eval_report_md,
)
from cookimport.bench.prediction_records import (
    PredictionRecord,
    make_prediction_record,
    read_prediction_records,
    write_prediction_records,
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
    list_codex_models,
    normalize_codex_reasoning_effort,
    normalize_prelabel_granularity,
)
from cookimport.llm.codex_farm_knowledge_orchestrator import run_codex_farm_knowledge_harvest
from cookimport.llm.codex_farm_orchestrator import run_codex_farm_recipe_pipeline
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.plugins import registry
from cookimport.plugins import excel, text, epub, pdf, recipesage, paprika  # noqa: F401
from cookimport.runs import RunManifest, RunSource, write_run_manifest
from cookimport.parsing.chunks import chunks_from_non_recipe_blocks, chunks_from_topic_candidates
from cookimport.parsing.tables import ExtractedTable, extract_and_annotate_tables
from cookimport.parsing.tips import partition_tip_candidates
from cookimport.staging.pdf_jobs import (
    plan_job_ranges,
    plan_pdf_page_ranges,
    reassign_recipe_ids,
)
from cookimport.staging.writer import (
    OutputStats,
    write_chunk_outputs,
    write_draft_outputs,
    write_intermediate_outputs,
    write_report,
    write_section_outputs,
    write_stage_block_predictions,
    write_table_outputs,
    write_tip_outputs,
    write_topic_candidate_outputs,
)

app = typer.Typer(add_completion=False, invoke_without_command=True)
bench_app = typer.Typer(name="bench", help="Offline benchmark suite tools.")
app.add_typer(bench_app)

from cookimport.tagging.cli import tag_catalog_app, tag_recipes_app  # noqa: E402
from cookimport.tagging.orchestrator import run_stage_tagging_pass  # noqa: E402
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
app.add_typer(tag_catalog_app)
app.add_typer(tag_recipes_app)
app.add_typer(epub_app, name="epub")
console = Console()
logger = logging.getLogger(__name__)

DEFAULT_INPUT = INPUT_ROOT
DEFAULT_OUTPUT = OUTPUT_ROOT
DEFAULT_INTERACTIVE_OUTPUT = DEFAULT_OUTPUT
DEFAULT_GOLDEN = GOLDEN_ROOT
DEFAULT_GOLDEN_SENT_TO_LABELSTUDIO = GOLDEN_SENT_TO_LABELSTUDIO_ROOT
DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO = GOLDEN_PULLED_FROM_LABELSTUDIO_ROOT
DEFAULT_GOLDEN_BENCHMARK = GOLDEN_BENCHMARK_ROOT
DEFAULT_HISTORY = HISTORY_ROOT
DEFAULT_BENCH_SUITES = DEFAULT_GOLDEN / "bench" / "suites"
DEFAULT_BENCH_RUNS = DEFAULT_GOLDEN / "bench" / "runs"
DEFAULT_CONFIG_PATH = REPO_ROOT / "cookimport.json"
BACK_ACTION = "__back__"
DEFAULT_PRELABEL_TIMEOUT_SECONDS = 300
KNOWN_LABELSTUDIO_TASK_SCOPES = {"pipeline", "canonical-blocks", "freeform-spans"}
SUPPORTED_LABELSTUDIO_TASK_SCOPES = {"freeform-spans"}
ALL_METHOD_CODEX_FARM_UNLOCK_ENV = "COOKIMPORT_ALLOW_CODEX_FARM"
ALL_METHOD_EPUB_EXTRACTORS = (
    "unstructured",
    "beautifulsoup",
    "markdown",
    "markitdown",
)
ALL_METHOD_UNSTRUCTURED_HTML_PARSER_VERSIONS = ("v1", "v2")
ALL_METHOD_UNSTRUCTURED_SKIP_HEADERS_FOOTERS = (False, True)
ALL_METHOD_UNSTRUCTURED_PREPROCESS_MODES = ("none", "br_split_v1", "semantic_v1")
ALL_METHOD_MAX_INFLIGHT_DEFAULT = 4
ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT = 4
ALL_METHOD_MAX_EVAL_TAIL_DEFAULT = 4
ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT = 900
ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT = 1
ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT = 2
ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO = 0.35
ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES = 768 * 1024 * 1024
ALL_METHOD_MAX_INFLIGHT_SETTING_KEY = "all_method_max_inflight_pipelines"
ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY = "all_method_max_split_phase_slots"
ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY = "all_method_max_eval_tail_pipelines"
ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY = "all_method_config_timeout_seconds"
ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY = "all_method_retry_failed_configs"
ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY = "all_method_max_parallel_sources"
ALL_METHOD_WING_BACKLOG_SETTING_KEY = "all_method_wing_backlog_target"
ALL_METHOD_SMART_SCHEDULER_SETTING_KEY = "all_method_smart_scheduler"
ALL_METHOD_SCHEDULER_POLL_SECONDS = 0.15
BENCHMARK_EVAL_MODE_STAGE_BLOCKS = "stage-blocks"
BENCHMARK_EVAL_MODE_CANONICAL_TEXT = "canonical-text"
BENCHMARK_EXECUTION_MODE_LEGACY = "legacy"
BENCHMARK_EXECUTION_MODE_PIPELINED = "pipelined"
BENCHMARK_EXECUTION_MODE_PREDICT_ONLY = "predict-only"
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
_STATUS_COUNTER_PATTERN = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
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


def _golden_sent_to_labelstudio_root() -> Path:
    return DEFAULT_GOLDEN / "sent-to-labelstudio"


def _golden_pulled_from_labelstudio_root() -> Path:
    return DEFAULT_GOLDEN / "pulled-from-labelstudio"


def _golden_benchmark_root() -> Path:
    return DEFAULT_GOLDEN / "benchmark-vs-golden"


def _infer_output_root_from_history_csv(csv_path: Path) -> Path | None:
    if csv_path.name != "performance_history.csv":
        return None
    if csv_path.parent.name != ".history":
        return None
    return csv_path.parent.parent / _DASHBOARD_REFRESH_SENTINEL_DIRNAME


def _refresh_dashboard_after_history_write(
    *,
    csv_path: Path,
    output_root: Path | None = None,
    golden_root: Path = DEFAULT_GOLDEN,
    reason: str | None = None,
) -> None:
    resolved_csv_path = csv_path.expanduser()
    if not resolved_csv_path.exists():
        return
    resolved_output_root = output_root.expanduser() if output_root is not None else None
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
            out_dir=resolved_csv_path.parent / "dashboard",
            open_browser=False,
            since_days=None,
            scan_reports=False,
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
    defaults = {
        "workers": 7,
        "pdf_split_workers": 7,
        "epub_split_workers": 7,
        ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY: ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT,
        ALL_METHOD_MAX_INFLIGHT_SETTING_KEY: ALL_METHOD_MAX_INFLIGHT_DEFAULT,
        ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY: ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
        ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY: ALL_METHOD_MAX_EVAL_TAIL_DEFAULT,
        ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY: ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT,
        ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY: ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT,
        ALL_METHOD_SMART_SCHEDULER_SETTING_KEY: True,
        "epub_extractor": "unstructured",
        "epub_unstructured_html_parser_version": "v1",
        "epub_unstructured_skip_headers_footers": False,
        "epub_unstructured_preprocess_mode": "br_split_v1",
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
        return defaults
    try:
        with open(DEFAULT_CONFIG_PATH, "r") as f:
            loaded = json.load(f)
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
                return merged
            return defaults
    except Exception:
        defaults[ALL_METHOD_WING_BACKLOG_SETTING_KEY] = defaults[
            ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        defaults[ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY] = defaults[
            ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY
        ]
        return defaults


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


def _settings_menu(current_settings: Dict[str, Any]) -> None:
    """Run the settings configuration menu."""
    while True:
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
                        f"{_resolve_positive_int_setting(current_settings, key=ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY, fallback=ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT)} "
                        "- max matched sources run in parallel"
                    ),
                    value=ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY,
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
                    f"EPUB Extractor: {current_settings.get('epub_extractor', 'unstructured')} - unstructured/beautifulsoup/markdown/markitdown",
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
                        f"{'Yes' if current_settings.get('epub_unstructured_skip_headers_footers', False) else 'No'}"
                    ),
                    value="epub_unstructured_skip_headers_footers",
                ),
                questionary.Choice(
                    (
                        "Unstructured EPUB Preprocess: "
                        f"{current_settings.get('epub_unstructured_preprocess_mode', 'br_split_v1')} - none/br_split_v1/semantic_v1"
                    ),
                    value="epub_unstructured_preprocess_mode",
                ),
                questionary.Choice(
                    f"OCR Device: {current_settings.get('ocr_device', 'auto')} - auto/cpu/cuda/mps",
                    value="ocr_device",
                ),
                questionary.Choice(
                    f"OCR Batch Size: {current_settings.get('ocr_batch_size', 1)} - pages per OCR call",
                    value="ocr_batch_size",
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
                        fallback=ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT,
                    )
                ),
            )
            parsed = _coerce_positive_int(val)
            if parsed is not None:
                current_settings[ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY] = parsed
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
                choices=["unstructured", "beautifulsoup", "markdown", "markitdown"],
                default=current_settings.get("epub_extractor", "unstructured"),
                menu_help=(
                    "Unstructured uses semantic HTML partitioning for richer block extraction. "
                    "BeautifulSoup uses tag-based parsing. Markdown converts spine HTML into markdown first. "
                    "MarkItDown is retained as a whole-book markdown mode."
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
                        False,
                    )
                ),
            )
            if val is not None:
                current_settings["epub_unstructured_skip_headers_footers"] = bool(val)
                _save_settings(current_settings)

        elif choice == "epub_unstructured_preprocess_mode":
            val = _menu_select(
                "Select EPUB HTML preprocess mode before Unstructured:",
                choices=["none", "br_split_v1", "semantic_v1"],
                default=current_settings.get(
                    "epub_unstructured_preprocess_mode",
                    "br_split_v1",
                ),
                menu_help=(
                    "none keeps raw HTML; br_split_v1 splits BR-separated paragraphs "
                    "into block tags; semantic_v1 currently aliases br_split_v1."
                ),
            )
            if val and val != BACK_ACTION:
                current_settings["epub_unstructured_preprocess_mode"] = val
                _save_settings(current_settings)

        elif choice == "ocr_device":
            val = _menu_select(
                "Select OCR Device:",
                choices=["auto", "cpu", "cuda", "mps"],
                default=current_settings.get("ocr_device", "auto"),
                menu_help="Choose OCR hardware. Use auto unless you need to force a device.",
            )
            if val and val != BACK_ACTION:
                current_settings["ocr_device"] = val
                _save_settings(current_settings)
                
        elif choice == "ocr_batch_size":
            val = _prompt_text(
                "Enter OCR batch size:",
                default=str(current_settings.get("ocr_batch_size", 1)),
            )
            if val and val.isdigit() and int(val) > 0:
                current_settings["ocr_batch_size"] = int(val)
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

    base_target_variants = _build_all_method_target_variants(
        targets=targets,
        base_settings=selected_benchmark_settings,
        include_codex_farm=False,
    )
    total_base_runs = sum(len(variants) for _target, variants in base_target_variants)
    if total_base_runs <= 0:
        typer.secho("No benchmark variants were generated for this selection.", fg=typer.colors.YELLOW)
        return

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
                    "Dimensions: epub_extractor, plus parser/skip_headers/preprocess "
                    "for unstructured variants."
                ),
                fg=typer.colors.BRIGHT_BLACK,
            )
        else:
            typer.secho(
                "Dimensions: non-EPUB source uses one configuration (global benchmark run settings).",
                fg=typer.colors.BRIGHT_BLACK,
            )
    typer.secho(
        (
            "With Codex Farm included: "
            f"{total_base_runs} configurations (currently unchanged while recipe codex-farm "
            "parsing is policy-locked OFF)."
        ),
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.secho(
        "All method benchmark uses canonical-text eval mode (extractor-independent).",
        fg=typer.colors.BRIGHT_BLACK,
    )

    include_codex_prompt = _prompt_confirm(
        "Include Codex Farm permutations?",
        default=False,
    )
    if include_codex_prompt is None:
        typer.secho("All method benchmark cancelled.", fg=typer.colors.YELLOW)
        return
    include_codex_requested = bool(include_codex_prompt)
    include_codex_effective, codex_warning = _resolve_all_method_codex_choice(
        include_codex_requested
    )
    if codex_warning:
        typer.secho(codex_warning, fg=typer.colors.YELLOW)

    selected_target_variants = _build_all_method_target_variants(
        targets=targets,
        base_settings=selected_benchmark_settings,
        include_codex_farm=include_codex_effective,
    )
    total_selected_runs = sum(
        len(variants) for _target, variants in selected_target_variants
    )
    if total_selected_runs <= 0:
        typer.secho("No benchmark variants were generated for this selection.", fg=typer.colors.YELLOW)
        return
    total_sources_selected = max(1, len(selected_target_variants))
    source_parallelism_default = min(
        ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT,
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
    timeout_display = (
        f"{resolved_config_timeout_seconds}s"
        if resolved_config_timeout_seconds is not None
        else "off"
    )
    scheduler_mode = "smart" if resolved_smart_scheduler else "fixed"
    typer.secho(
        (
            "Scheduler: "
            f"source parallel={source_parallelism_effective} "
            f"(configured {source_parallelism_configured}, "
            f"default {ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT}), "
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

    status_initial = "Running all method benchmark..."
    status_prefix = "All method benchmark"

    if scope_all_matched:
        dashboard = _AllMethodProgressDashboard.from_target_variants(
            selected_target_variants
        )
        report_md_path = _run_with_progress_status(
            initial_status=status_initial,
            progress_prefix=status_prefix,
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
                wing_backlog_target=resolved_wing_backlog_target,
                smart_scheduler=resolved_smart_scheduler,
            ),
        )
        typer.secho(
            f"All method benchmark summary report: {report_md_path}",
            fg=typer.colors.CYAN,
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
            run=_run_single_source,
        )
        typer.secho(f"All method benchmark report: {report_md_path}", fg=typer.colors.CYAN)

    typer.secho(
        f"All method processed outputs: {all_method_processed_root}",
        fg=typer.colors.CYAN,
    )


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
                    "Stage files from data/input - produce cookbook outputs",
                    value="import",
                )
            )
            choices.append(
                questionary.Choice(
                    "Label Studio: create labeling tasks (uploads)",
                    value="labelstudio",
                )
            )
        choices.append(
            questionary.Choice(
                "Label Studio: export completed labels to golden artifacts",
                value="labelstudio_export",
            )
        )
        choices.append(
            questionary.Choice(
                "Generate predictions + evaluate vs freeform gold",
                value="labelstudio_benchmark",
            )
        )
        choices.append(
            questionary.Choice(
                "Generate dashboard - build lifetime stats dashboard HTML",
                value="generate_dashboard",
            )
        )
        choices.append(
            questionary.Choice(
                "Settings - tune worker/OCR/output defaults",
                value="settings",
            )
        )
        choices.append(questionary.Choice("Exit - close the tool", value="exit"))

        action = _menu_select(
            "What would you like to do?",
            choices=choices,
            menu_help=(
                "Choose a workflow. Stage produces cookbook outputs, Label Studio task "
                "creation uploads annotation tasks, export pulls completed labels, "
                "and evaluate compares predictions against gold. "
                "Dashboard builds a static lifetime summary."
            ),
        )

        if action == BACK_ACTION:
            continue

        if action is None or action == "exit":
            raise typer.Exit(0)

        if action == "generate_dashboard":
            open_dashboard = _prompt_confirm(
                "Open dashboard in your browser after generation?",
                default=True,
            )
            if open_dashboard is None:
                continue
            typer.secho(
                f"Generating dashboard from {output_folder}...",
                fg=typer.colors.CYAN,
            )
            stats_dashboard(
                output_root=output_folder,
                golden_root=DEFAULT_GOLDEN,
                out_dir=history_root_for_output(output_folder) / "dashboard",
                open_browser=bool(open_dashboard),
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
                    questionary.Choice("Import All - process every supported file", value="all"),
                    *[questionary.Choice(f.name, value=f) for f in importable_files]
                ]
            )

            if selection in {None, BACK_ACTION}:
                continue

            typer.echo()

            global_run_settings = RunSettings.from_dict(
                settings,
                warn_context="interactive global settings",
            )
            selected_run_settings = choose_run_settings(
                kind="import",
                global_defaults=global_run_settings,
                output_dir=output_folder,
                menu_select=_menu_select,
                back_action=BACK_ACTION,
            )
            if selected_run_settings is None:
                typer.secho("Import cancelled.", fg=typer.colors.YELLOW)
                continue

            typer.secho(
                "Run settings: "
                f"{selected_run_settings.summary()} "
                f"(hash {selected_run_settings.short_hash()})",
                fg=typer.colors.CYAN,
            )

            # Apply EPUB settings via env vars (read at call time by epub.py).
            os.environ["C3IMP_EPUB_EXTRACTOR"] = selected_run_settings.epub_extractor.value
            _set_epub_unstructured_env(
                html_parser_version=selected_run_settings.epub_unstructured_html_parser_version.value,
                skip_headers_footers=selected_run_settings.epub_unstructured_skip_headers_footers,
                preprocess_mode=selected_run_settings.epub_unstructured_preprocess_mode.value,
            )

            common_args = {
                "out": output_folder,
                "mapping": None,
                "overrides": None,
                "limit": limit,
                "workers": selected_run_settings.workers,
                "pdf_split_workers": selected_run_settings.pdf_split_workers,
                "epub_split_workers": selected_run_settings.epub_split_workers,
                "epub_extractor": selected_run_settings.epub_extractor.value,
                "epub_unstructured_html_parser_version": (
                    selected_run_settings.epub_unstructured_html_parser_version.value
                ),
                "epub_unstructured_skip_headers_footers": (
                    selected_run_settings.epub_unstructured_skip_headers_footers
                ),
                "epub_unstructured_preprocess_mode": (
                    selected_run_settings.epub_unstructured_preprocess_mode.value
                ),
                "table_extraction": selected_run_settings.table_extraction.value,
                "ocr_device": selected_run_settings.ocr_device.value,
                "ocr_batch_size": selected_run_settings.ocr_batch_size,
                "pdf_pages_per_job": selected_run_settings.pdf_pages_per_job,
                "epub_spine_items_per_job": selected_run_settings.epub_spine_items_per_job,
                "warm_models": selected_run_settings.warm_models,
                "llm_recipe_pipeline": selected_run_settings.llm_recipe_pipeline.value,
                "llm_knowledge_pipeline": selected_run_settings.llm_knowledge_pipeline.value,
                "llm_tags_pipeline": selected_run_settings.llm_tags_pipeline.value,
                "codex_farm_cmd": selected_run_settings.codex_farm_cmd,
                "codex_farm_root": selected_run_settings.codex_farm_root,
                "codex_farm_workspace_root": selected_run_settings.codex_farm_workspace_root,
                "codex_farm_pipeline_pass1": selected_run_settings.codex_farm_pipeline_pass1,
                "codex_farm_pipeline_pass2": selected_run_settings.codex_farm_pipeline_pass2,
                "codex_farm_pipeline_pass3": selected_run_settings.codex_farm_pipeline_pass3,
                "codex_farm_pipeline_pass4_knowledge": (
                    selected_run_settings.codex_farm_pipeline_pass4_knowledge
                ),
                "codex_farm_pipeline_pass5_tags": (
                    selected_run_settings.codex_farm_pipeline_pass5_tags
                ),
                "codex_farm_context_blocks": selected_run_settings.codex_farm_context_blocks,
                "codex_farm_knowledge_context_blocks": (
                    selected_run_settings.codex_farm_knowledge_context_blocks
                ),
                "tag_catalog_json": selected_run_settings.tag_catalog_json,
                "codex_farm_failure_mode": selected_run_settings.codex_farm_failure_mode.value,
            }

            if selection == "all":
                run_folder = stage(path=input_folder, **common_args)
            else:
                run_folder = stage(path=selection, **common_args)

            save_last_run_settings("import", output_folder, selected_run_settings)
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
            prelabel_provider = "codex-cli"
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
                detected_label = detected_model or "Codex CLI default"
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
                        "Codex CLI default."
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
                        "Minimal is hidden due Codex tool compatibility."
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

            import_started_at = time.monotonic()
            try:
                result = _run_labelstudio_import_with_status(
                    source_name=selected_file.name,
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
                    "Single offline mode runs one local prediction + eval against freeform gold "
                    "without Label Studio upload. All method benchmark runs many offline "
                    "permutations with one summary report."
                ),
                choices=[
                    questionary.Choice(
                        "Generate predictions + evaluate (offline, no upload)",
                        value="single_offline",
                    ),
                    questionary.Choice(
                        "All method benchmark (offline, no upload)",
                        value="all_method",
                    ),
                ],
            )
            if benchmark_mode in {None, BACK_ACTION}:
                continue

            benchmark_defaults = RunSettings.from_dict(
                settings,
                warn_context="interactive benchmark global settings",
            )
            if benchmark_mode == "single_offline":
                selected_benchmark_settings = choose_run_settings(
                    kind="benchmark",
                    global_defaults=benchmark_defaults,
                    output_dir=output_folder,
                    menu_select=_menu_select,
                    back_action=BACK_ACTION,
                )
                if selected_benchmark_settings is None:
                    typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
                    continue

                typer.secho(
                    "Run settings: "
                    f"{selected_benchmark_settings.summary()} "
                    f"(hash {selected_benchmark_settings.short_hash()})",
                    fg=typer.colors.CYAN,
                )

                benchmark_kwargs = dict(
                    output_dir=_golden_benchmark_root(),
                    eval_output_dir=benchmark_eval_output,
                    eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                    epub_extractor=selected_benchmark_settings.epub_extractor.value,
                    epub_unstructured_html_parser_version=(
                        selected_benchmark_settings.epub_unstructured_html_parser_version.value
                    ),
                    epub_unstructured_skip_headers_footers=(
                        selected_benchmark_settings.epub_unstructured_skip_headers_footers
                    ),
                    epub_unstructured_preprocess_mode=(
                        selected_benchmark_settings.epub_unstructured_preprocess_mode.value
                    ),
                    ocr_device=selected_benchmark_settings.ocr_device.value,
                    ocr_batch_size=selected_benchmark_settings.ocr_batch_size,
                    warm_models=selected_benchmark_settings.warm_models,
                    workers=selected_benchmark_settings.workers,
                    pdf_split_workers=selected_benchmark_settings.pdf_split_workers,
                    epub_split_workers=selected_benchmark_settings.epub_split_workers,
                    pdf_pages_per_job=selected_benchmark_settings.pdf_pages_per_job,
                    epub_spine_items_per_job=selected_benchmark_settings.epub_spine_items_per_job,
                    llm_recipe_pipeline=selected_benchmark_settings.llm_recipe_pipeline.value,
                    codex_farm_cmd=selected_benchmark_settings.codex_farm_cmd,
                    codex_farm_root=selected_benchmark_settings.codex_farm_root,
                    codex_farm_workspace_root=selected_benchmark_settings.codex_farm_workspace_root,
                    codex_farm_pipeline_pass1=selected_benchmark_settings.codex_farm_pipeline_pass1,
                    codex_farm_pipeline_pass2=selected_benchmark_settings.codex_farm_pipeline_pass2,
                    codex_farm_pipeline_pass3=selected_benchmark_settings.codex_farm_pipeline_pass3,
                    codex_farm_context_blocks=selected_benchmark_settings.codex_farm_context_blocks,
                    codex_farm_failure_mode=selected_benchmark_settings.codex_farm_failure_mode.value,
                )

                labelstudio_benchmark(
                    **benchmark_kwargs,
                    no_upload=True,
                )
                save_last_run_settings(
                    "benchmark", output_folder, selected_benchmark_settings
                )
            else:
                all_method_max_parallel_sources = _coerce_positive_int(
                    settings.get(ALL_METHOD_MAX_PARALLEL_SOURCES_SETTING_KEY)
                )
                all_method_max_inflight = _coerce_positive_int(
                    settings.get(ALL_METHOD_MAX_INFLIGHT_SETTING_KEY)
                )
                all_method_max_split_slots = _coerce_positive_int(
                    settings.get(ALL_METHOD_MAX_SPLIT_SLOTS_SETTING_KEY)
                )
                all_method_max_eval_tail = _coerce_positive_int(
                    settings.get(ALL_METHOD_MAX_EVAL_TAIL_SETTING_KEY)
                )
                all_method_config_timeout_seconds = _coerce_non_negative_int(
                    settings.get(ALL_METHOD_CONFIG_TIMEOUT_SETTING_KEY)
                )
                all_method_retry_failed_configs = _coerce_non_negative_int(
                    settings.get(ALL_METHOD_RETRY_FAILED_CONFIGS_SETTING_KEY)
                )
                all_method_wing_backlog = _coerce_positive_int(
                    settings.get(ALL_METHOD_WING_BACKLOG_SETTING_KEY)
                )
                all_method_smart_scheduler = _coerce_bool_setting(
                    settings.get(ALL_METHOD_SMART_SCHEDULER_SETTING_KEY),
                    default=True,
                )
                _interactive_all_method_benchmark(
                    selected_benchmark_settings=benchmark_defaults,
                    benchmark_eval_output=benchmark_eval_output,
                    processed_output_root=output_folder,
                    max_parallel_sources=all_method_max_parallel_sources,
                    max_inflight_pipelines=all_method_max_inflight,
                    max_concurrent_split_phases=all_method_max_split_slots,
                    max_eval_tail_pipelines=all_method_max_eval_tail,
                    config_timeout_seconds=all_method_config_timeout_seconds,
                    retry_failed_configs=all_method_retry_failed_configs,
                    wing_backlog_target=all_method_wing_backlog,
                    smart_scheduler=all_method_smart_scheduler,
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
        _interactive_mode(limit=limit)


def _fail(message: str) -> None:
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
    if normalized not in {"none", "br_split_v1", "semantic_v1"}:
        _fail(
            f"Invalid EPUB Unstructured preprocess mode: {value!r}. "
            "Expected one of: none, br_split_v1, semantic_v1."
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


def _normalize_table_extraction(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"off", "on"}:
        _fail(
            f"Invalid table extraction mode: {value!r}. "
            "Expected one of: off, on."
        )
    return normalized


def _normalize_llm_recipe_pipeline(value: str) -> str:
    normalized = value.strip().lower()
    if normalized != "off":
        _fail(
            f"Invalid LLM recipe pipeline: {value!r}. "
            f"{RECIPE_CODEX_FARM_PIPELINE_POLICY_ERROR}"
        )
    return normalized


def _normalize_llm_knowledge_pipeline(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"off", "codex-farm-knowledge-v1"}:
        _fail(
            f"Invalid LLM knowledge pipeline: {value!r}. "
            "Expected one of: off, codex-farm-knowledge-v1."
        )
    return normalized


def _normalize_llm_tags_pipeline(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"off", "codex-farm-tags-v1"}:
        _fail(
            f"Invalid LLM tags pipeline: {value!r}. "
            "Expected one of: off, codex-farm-tags-v1."
        )
    return normalized


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


def _normalize_benchmark_execution_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"legacy", "sequential", "default"}:
        return BENCHMARK_EXECUTION_MODE_LEGACY
    if normalized in {"pipelined", "pipeline"}:
        return BENCHMARK_EXECUTION_MODE_PIPELINED
    if normalized in {"predict-only", "predictions-only", "predict"}:
        return BENCHMARK_EXECUTION_MODE_PREDICT_ONLY
    _fail(
        f"Invalid benchmark execution mode: {value!r}. "
        "Expected one of: legacy, pipelined, predict-only."
    )
    return BENCHMARK_EXECUTION_MODE_LEGACY


def _parse_csv_labels(value: str) -> set[str]:
    labels = {item.strip().upper() for item in value.split(",") if item.strip()}
    if not labels:
        _fail("At least one label is required (example: YIELD_LINE,TIME_LINE).")
    return labels


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
            # Backward compatibility with older freeform projects.
            "NOTES",
            "VARIANT",
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


def _format_seconds_per_task(seconds_per_task: float) -> str:
    formatted = f"{max(0.0, seconds_per_task):.1f}".rstrip("0").rstrip(".")
    return f"{formatted}s/task"


def _looks_like_all_method_dashboard_snapshot(message: str) -> bool:
    trimmed = str(message or "").strip()
    return bool(trimmed and trimmed.startswith("overall source ") and "\nqueue:" in trimmed)


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


def _format_processing_time(elapsed_seconds: float) -> str:
    total_seconds = max(0, int(round(elapsed_seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _run_with_progress_status(
    *,
    initial_status: str,
    progress_prefix: str,
    run: Callable[[Callable[[str], None]], _StatusReturn],
    elapsed_threshold_seconds: int = _STATUS_ELAPSED_THRESHOLD_SECONDS,
    tick_seconds: float = _STATUS_TICK_SECONDS,
) -> _StatusReturn:
    latest_message = ""
    latest_message_started = time.monotonic()
    latest_counter: tuple[int, int] | None = None
    rate_total: int | None = None
    rate_last_current: int | None = None
    rate_last_progress_at: float | None = None
    rate_sampled_seconds = 0.0
    rate_sampled_units = 0
    worker_total = 0
    worker_activity: dict[int, str] = {}
    state_lock = threading.Lock()
    stop_event = threading.Event()

    def render(now: float | None = None) -> str:
        current = now if now is not None else time.monotonic()
        with state_lock:
            message = latest_message
            started_at = latest_message_started
            counter = latest_counter
            tracked_total = rate_total
            sampled_seconds = rate_sampled_seconds
            sampled_units = rate_sampled_units
            workers = worker_total
            worker_statuses = {
                worker_index: status
                for worker_index, status in worker_activity.items()
            }
        if not message:
            base = f"[bold cyan]{rich_escape(initial_status)}[/bold cyan]"
        else:
            elapsed = max(0, int(current - started_at))
            eta_seconds: int | None = None
            avg_seconds_per_task: float | None = None
            if (
                counter is not None
                and tracked_total is not None
                and sampled_units > 0
                and sampled_seconds > 0
                and counter[1] == tracked_total
            ):
                counter_current, counter_total = counter
                remaining = max(0, counter_total - counter_current)
                avg_seconds_per_task = sampled_seconds / sampled_units
                if remaining > 0 and avg_seconds_per_task > 0:
                    eta_seconds = int(round(avg_seconds_per_task * remaining))
            decorated = _format_status_progress_message(
                message,
                elapsed_seconds=elapsed,
                elapsed_threshold_seconds=elapsed_threshold_seconds,
                eta_seconds=eta_seconds,
                avg_seconds_per_task=avg_seconds_per_task,
            )
            base = (
                f"[bold cyan]{rich_escape(progress_prefix)}: "
                f"{rich_escape(decorated)}[/bold cyan]"
            )
        if workers <= 0:
            return base
        worker_lines = [base]
        for worker_index in range(1, workers + 1):
            worker_status = worker_statuses.get(worker_index, "idle").strip() or "idle"
            if len(worker_status) > 120:
                worker_status = f"{worker_status[:117]}..."
            worker_lines.append(
                f"[cyan]  worker {worker_index:02d}: {rich_escape(worker_status)}[/cyan]"
            )
        return "\n".join(worker_lines)

    with console.status(render(), spinner="dots") as status:

        def tick() -> None:
            while not stop_event.wait(max(0.05, tick_seconds)):
                status.update(render())

        ticker = threading.Thread(
            target=tick,
            name="cli-status-progress-ticker",
            daemon=True,
        )
        ticker.start()

        def update_progress(msg: str) -> None:
            nonlocal latest_message, latest_message_started
            nonlocal latest_counter, rate_total, rate_last_current, rate_last_progress_at
            nonlocal rate_sampled_seconds, rate_sampled_units
            nonlocal worker_total, worker_activity
            now = time.monotonic()
            cleaned = msg.strip()
            worker_payload = parse_worker_activity(cleaned)
            counter = None
            with state_lock:
                if worker_payload is not None:
                    payload_type = worker_payload.get("type")
                    if payload_type == "reset":
                        worker_total = 0
                        worker_activity = {}
                    elif payload_type == "activity":
                        total = int(worker_payload.get("worker_total") or 1)
                        worker_index = int(worker_payload.get("worker_index") or 1)
                        worker_status_text = str(
                            worker_payload.get("status") or ""
                        ).strip()
                        if total != worker_total:
                            worker_total = total
                            worker_activity = {
                                idx: value
                                for idx, value in worker_activity.items()
                                if idx <= total
                            }
                        worker_activity[worker_index] = worker_status_text
                else:
                    counter = _extract_progress_counter(cleaned)
                    latest_message = cleaned
                    latest_message_started = now
                    latest_counter = counter
                    if counter is not None:
                        counter_current, counter_total = counter
                        should_reset = (
                            rate_total is None
                            or rate_last_current is None
                            or rate_last_progress_at is None
                            or counter_total != rate_total
                            or counter_current < rate_last_current
                        )
                        if should_reset:
                            rate_total = counter_total
                            rate_last_current = counter_current
                            rate_last_progress_at = now
                            rate_sampled_seconds = 0.0
                            rate_sampled_units = 0
                        else:
                            delta = counter_current - rate_last_current
                            if delta > 0:
                                elapsed_since_progress = max(
                                    0.0, now - rate_last_progress_at
                                )
                                if elapsed_since_progress > 0:
                                    rate_sampled_seconds += elapsed_since_progress
                                    rate_sampled_units += delta
                                rate_last_current = counter_current
                                rate_last_progress_at = now
            status.update(render(now))

        try:
            return run(update_progress)
        finally:
            stop_event.set()
            ticker.join(timeout=max(0.2, tick_seconds * 2))


@contextmanager
def _benchmark_progress_overrides(
    *,
    progress_callback: Callable[[str], None] | None = None,
    suppress_summary: bool = False,
    suppress_spinner: bool = False,
) -> Iterable[None]:
    progress_token = _BENCHMARK_PROGRESS_CALLBACK.set(progress_callback)
    summary_token = _BENCHMARK_SUPPRESS_SUMMARY.set(bool(suppress_summary))
    spinner_token = _BENCHMARK_SUPPRESS_SPINNER.set(bool(suppress_spinner))
    try:
        yield
    finally:
        _BENCHMARK_PROGRESS_CALLBACK.reset(progress_token)
        _BENCHMARK_SUPPRESS_SUMMARY.reset(summary_token)
        _BENCHMARK_SUPPRESS_SPINNER.reset(spinner_token)


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
) -> dict[str, Any]:
    return _run_with_progress_status(
        initial_status=f"Running Label Studio import for {source_name}...",
        progress_prefix=f"Label Studio import ({source_name})",
        run=run_import,
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


def _co_locate_prediction_run_for_benchmark(pred_run: Path, eval_output_dir: Path) -> Path:
    """Move benchmark prediction artifacts under the eval run directory."""
    if not pred_run.exists() or not pred_run.is_dir():
        _fail(f"Prediction run directory not found: {pred_run}")
    original_parent = pred_run.parent
    stop_exclusive = pred_run.parents[2] if len(pred_run.parents) > 2 else None
    target = eval_output_dir / "prediction-run"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pred_run), str(target))
    _prune_empty_dirs(original_parent, stop_exclusive=stop_exclusive)
    return target


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
    source_file: str
    source_hash: str | None
    run_config: dict[str, Any] | None
    run_config_hash: str | None
    run_config_summary: str | None


@dataclass(frozen=True)
class BenchmarkPredictionBundle:
    import_result: dict[str, Any]
    pred_run: Path
    pred_context: PredRunContext
    stage_predictions_path: Path
    extracted_archive_path: Path
    prediction_phase_seconds: float


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
            if len(cleaned) > 180:
                cleaned = f"{cleaned[:177]}..."
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
            active_source_count = len(self._running_source_indices())
            if active_source_count > 0:
                lines.append(f"active sources: {active_source_count}")

            if (
                self.current_source_index is not None
                and 0 <= self.current_source_index < len(self.rows)
            ):
                current_row = self.rows[self.current_source_index]
                lines.append(
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
                        lines.append(
                            (
                                f"current config {active_index}/{self.current_config_total}: "
                                f"{slug}"
                            )
                        )
                    else:
                        first_active = active_items[0][0]
                        last_active = active_items[-1][0]
                        lines.append(
                            (
                                f"current configs {first_active}-{last_active}/"
                                f"{self.current_config_total} ({len(active_items)} active)"
                            )
                        )
                        lines.append("active config workers:")
                        for active_index, active_slug in active_items:
                            phase = self._format_config_phase_label(
                                phase_items.get(active_index, "prep")
                            )
                            slug = active_slug or "<pending>"
                            if len(slug) > 120:
                                slug = f"{slug[:117]}..."
                            lines.append(
                                f"  config {active_index:02d}: {phase} | {slug}"
                            )
                elif 0 <= self.current_source_index < len(self.rows):
                    current_row = self.rows[self.current_source_index]
                    if current_row.completed_configs < current_row.total_configs:
                        queued_index = min(
                            current_row.total_configs,
                            max(1, current_row.completed_configs + 1),
                        )
                        lines.append(
                            f"current config {queued_index}/{self.current_config_total}: <queued>"
                        )
            lines.append("queue:")

            if len(self.rows) <= 10:
                for row in self.rows:
                    marker = {
                        "pending": "[ ]",
                        "running": "[>]",
                        "done": "[x]",
                        "failed": "[!]",
                    }.get(row.status, "[ ]")
                    lines.append(
                        (
                            f"  {marker} {row.source_name} - "
                            f"{row.completed_configs} of {row.total_configs} "
                            f"(ok {row.successful_configs}, fail {row.failed_configs})"
                        )
                    )
            else:
                visible_rows = list(self._iter_queue_rows())
                rendered_ids = {id(row) for row in visible_rows}
                for row in visible_rows:
                    marker = {
                        "pending": "[ ]",
                        "running": "[>]",
                        "done": "[x]",
                        "failed": "[!]",
                    }.get(row.status, "[ ]")
                    lines.append(
                        (
                            f"  {marker} {row.source_name} - "
                            f"{row.completed_configs} of {row.total_configs} "
                            f"(ok {row.successful_configs}, fail {row.failed_configs})"
                        )
                    )
                hidden_count = sum(1 for row in self.rows if id(row) not in rendered_ids)
                if hidden_count > 0:
                    lines.append(f"  ... {hidden_count} additional sources hidden")

            if self.task_message:
                lines.append(f"task: {self.task_message}")

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
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            stage_block_predictions_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
        )
    if not isinstance(payload, dict):
        return PredRunContext(
            recipes=None,
            processed_report_path="",
            stage_block_predictions_path="",
            source_file="",
            source_hash=None,
            run_config=None,
            run_config_hash=None,
            run_config_summary=None,
        )

    source_file = str(payload.get("source_file") or "")
    source_hash = str(payload.get("source_hash") or "").strip() or None
    processed_report_path = str(payload.get("processed_report_path") or "")
    stage_block_predictions_path = str(payload.get("stage_block_predictions_path") or "")
    if not stage_block_predictions_path:
        stage_block_predictions_path = str(
            payload.get("processed_stage_block_predictions_path") or ""
        )
    run_config = payload.get("run_config")
    if not isinstance(run_config, dict):
        run_config = None
    run_config_hash = str(payload.get("run_config_hash") or "").strip() or None
    run_config_summary = str(payload.get("run_config_summary") or "").strip() or None

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
        source_file=source_file,
        source_hash=source_hash,
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
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
        import_result.get("processed_stage_block_predictions_path"),
        pred_context.stage_block_predictions_path,
        pred_run / "stage_block_predictions.json",
    ):
        if not value:
            continue
        stage_predictions_candidates.append(Path(str(value)))

    for candidate in stage_predictions_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    _fail(
        "This prediction run is missing stage block predictions. "
        "Re-run benchmark after updating."
    )
    return pred_run / "stage_block_predictions.json"


def _build_prediction_bundle_from_import_result(
    *,
    import_result: dict[str, Any],
    eval_output_dir: Path,
    prediction_phase_seconds: float,
) -> BenchmarkPredictionBundle:
    pred_run = _co_locate_prediction_run_for_benchmark(
        Path(import_result["run_root"]),
        eval_output_dir,
    )
    pred_context = _load_pred_run_recipe_context(pred_run)
    stage_predictions_path = _resolve_stage_predictions_for_benchmark(
        import_result=import_result,
        pred_context=pred_context,
        pred_run=pred_run,
    )

    extracted_archive_path = pred_run / "extracted_archive.json"
    if not extracted_archive_path.exists() or not extracted_archive_path.is_file():
        _fail(f"Prediction run is missing extracted_archive.json: {pred_run}")

    return BenchmarkPredictionBundle(
        import_result=import_result,
        pred_run=pred_run,
        pred_context=pred_context,
        stage_predictions_path=stage_predictions_path,
        extracted_archive_path=extracted_archive_path,
        prediction_phase_seconds=max(0.0, prediction_phase_seconds),
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
        "pred_run_dir": str(bundle.pred_run),
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


def _prediction_record_path_value(
    *,
    record: PredictionRecord,
    field_name: str,
) -> Path:
    raw_value = record.prediction.get(field_name)
    path_value = Path(str(raw_value or ""))
    if not str(raw_value or "").strip():
        _fail(f"Prediction record is missing required path field: {field_name}")
    if not path_value.exists() or not path_value.is_file():
        _fail(
            f"Prediction record path for {field_name} does not exist: {path_value}"
        )
    return path_value


def _prediction_record_is_legacy_pointer(record: PredictionRecord) -> bool:
    required_fields = (
        "stage_block_predictions_path",
        "extracted_archive_path",
    )
    for field_name in required_fields:
        if not str(record.prediction.get(field_name) or "").strip():
            return False
    return True


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


def _build_prediction_bundle_from_legacy_record(
    *,
    record: PredictionRecord,
    predictions_in: Path | None = None,
) -> BenchmarkPredictionBundle:
    _ = predictions_in
    stage_predictions_path = _prediction_record_path_value(
        record=record,
        field_name="stage_block_predictions_path",
    )
    extracted_archive_path = _prediction_record_path_value(
        record=record,
        field_name="extracted_archive_path",
    )

    pred_run_value = str(record.prediction.get("pred_run_dir") or "").strip()
    pred_run = Path(pred_run_value) if pred_run_value else extracted_archive_path.parent
    if not pred_run.exists() or not pred_run.is_dir():
        pred_run = extracted_archive_path.parent

    predict_meta = record.predict_meta
    run_config_payload = predict_meta.get("run_config")
    run_config = run_config_payload if isinstance(run_config_payload, dict) else None
    timing_payload = predict_meta.get("timing")
    import_result: dict[str, Any] = {
        "run_root": str(pred_run),
        "stage_block_predictions_path": str(stage_predictions_path),
        "processed_report_path": str(predict_meta.get("processed_report_path") or ""),
        "processed_run_root": str(predict_meta.get("processed_run_root") or ""),
        "timing": timing_payload if isinstance(timing_payload, dict) else {},
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
        recipes=_coerce_int(predict_meta.get("recipes")),
        processed_report_path=str(predict_meta.get("processed_report_path") or ""),
        stage_block_predictions_path=str(stage_predictions_path),
        source_file=str(predict_meta.get("source_file") or ""),
        source_hash=str(predict_meta.get("source_hash") or "").strip() or None,
        run_config=run_config,
        run_config_hash=str(predict_meta.get("run_config_hash") or "").strip() or None,
        run_config_summary=str(predict_meta.get("run_config_summary") or "").strip()
        or None,
    )

    return BenchmarkPredictionBundle(
        import_result=import_result,
        pred_run=pred_run,
        pred_context=pred_context,
        stage_predictions_path=stage_predictions_path,
        extracted_archive_path=extracted_archive_path,
        prediction_phase_seconds=max(0.0, prediction_phase_seconds),
    )


def _build_prediction_bundle_from_stage_records(
    *,
    prediction_records: list[PredictionRecord],
    replay_output_dir: Path,
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
        "block_count": len(expected_indices),
        "block_labels": stage_labels,
        "label_blocks": label_blocks,
        "conflicts": [],
        "notes": ["Reconstructed from per-example prediction records."],
    }
    stage_predictions_path.write_text(
        json.dumps(stage_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    extracted_archive_path.write_text(
        json.dumps(extracted_rows, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    pred_run_value = str(first_meta.get("pred_run_dir") or "").strip()
    pred_run = Path(pred_run_value) if pred_run_value else replay_output_dir
    if not pred_run.exists() or not pred_run.is_dir():
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
        source_file=source_file,
        source_hash=source_hash if source_hash != "unknown" else None,
        run_config=run_config,
        run_config_hash=str(first_meta.get("run_config_hash") or "").strip() or None,
        run_config_summary=str(first_meta.get("run_config_summary") or "").strip() or None,
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

    legacy_record_candidates = [
        record
        for record in prediction_records
        if _prediction_record_is_legacy_pointer(record)
    ]
    stage_record_candidates: list[PredictionRecord] = []
    for record in prediction_records:
        stage_row = _prediction_record_stage_row(record)
        if stage_row is not None:
            stage_record_candidates.append(record)

    if legacy_record_candidates and stage_record_candidates:
        raise ValueError(
            "Prediction record file mixes legacy run-pointer and per-block records."
        )
    if legacy_record_candidates:
        if len(prediction_records) != 1:
            raise ValueError(
                "Legacy prediction record input must contain exactly one record."
            )
        return _build_prediction_bundle_from_legacy_record(
            record=legacy_record_candidates[0],
            predictions_in=predictions_in,
        )
    if len(stage_record_candidates) != len(prediction_records):
        raise ValueError(
            "Prediction record file contains unsupported record payload(s)."
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


def run_legacy(
    *,
    run_prediction_bundle: Callable[[], BenchmarkPredictionBundle],
    selected_source: Path,
) -> tuple[BenchmarkPredictionBundle, list[PredictionRecord]]:
    prediction_bundle = run_prediction_bundle()
    prediction_records = list(
        predict_stage(
            bundle=prediction_bundle,
            selected_source=selected_source,
        )
    )
    return prediction_bundle, prediction_records


def run_pipelined(
    *,
    run_prediction_bundle: Callable[[], BenchmarkPredictionBundle],
    prewarm_evaluation_inputs: Callable[[], dict[str, Path] | None],
    selected_source: Path,
    queue_size: int = 64,
) -> tuple[BenchmarkPredictionBundle, list[PredictionRecord], dict[str, Path] | None]:
    record_queue: queue.Queue[PredictionRecord | object] = queue.Queue(
        maxsize=max(1, int(queue_size))
    )
    result_queue: queue.Queue[BenchmarkPredictionBundle] = queue.Queue(maxsize=1)
    error_queue: queue.Queue[BaseException] = queue.Queue(maxsize=1)
    end_of_stream = object()

    def _producer() -> None:
        try:
            prediction_bundle = run_prediction_bundle()
            result_queue.put(prediction_bundle)
            for record in predict_stage(
                bundle=prediction_bundle,
                selected_source=selected_source,
            ):
                record_queue.put(record)
            record_queue.put(end_of_stream)
        except BaseException as exc:  # noqa: BLE001
            error_queue.put(exc)
            record_queue.put(end_of_stream)

    producer_thread = threading.Thread(
        target=_producer,
        name="benchmark-prediction-stage",
        daemon=True,
    )
    producer_thread.start()
    prewarmed_canonical_paths: dict[str, Path] | None = None
    prewarm_error: BaseException | None = None
    try:
        prewarmed_canonical_paths = prewarm_evaluation_inputs()
    except BaseException as exc:  # noqa: BLE001
        prewarm_error = exc

    prediction_records: list[PredictionRecord] = []
    reached_end_of_stream = False
    while not reached_end_of_stream:
        try:
            next_item = record_queue.get(timeout=0.1)
        except queue.Empty:
            if not producer_thread.is_alive() and not error_queue.empty():
                break
            continue
        if next_item is end_of_stream:
            reached_end_of_stream = True
            continue
        if isinstance(next_item, PredictionRecord):
            prediction_records.append(next_item)
            continue
        raise RuntimeError("Benchmark prediction pipeline produced an invalid record.")

    producer_thread.join()
    if prewarm_error is not None:
        raise prewarm_error
    if not error_queue.empty():
        raise error_queue.get()
    if result_queue.empty():
        raise RuntimeError(
            "Pipelined benchmark prediction stage produced no output."
        )
    prediction_bundle = result_queue.get()
    return prediction_bundle, prediction_records, prewarmed_canonical_paths


def evaluate_stage(
    *,
    selected_eval_mode: str,
    selected_gold: Path,
    eval_output_dir: Path,
    stage_predictions_path: Path,
    extracted_archive_path: Path,
    alignment_cache_dir: Path | None,
    prewarmed_canonical_paths: dict[str, Path] | None,
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
    )
    return eval_result_local, format_stage_block_eval_report_md


def _sum_bench_recipe_count(run_root: Path) -> int | None:
    total = 0
    found_any = False
    for manifest_path in run_root.glob("per_item/*/pred_run/manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, dict):
            continue

        recipe_count: int | None
        try:
            recipe_count = int(payload.get("recipe_count"))
        except (TypeError, ValueError):
            recipe_count = None

        if recipe_count is None:
            processed_report_path = payload.get("processed_report_path")
            recipe_count = _load_total_recipes_from_report_path(processed_report_path)

        if recipe_count is None:
            continue
        total += recipe_count
        found_any = True

    return total if found_any else None


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
    for root in (output_dir, DEFAULT_GOLDEN):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


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
    candidates = _discover_freeform_gold_exports(output_dir)
    importable_by_name = {
        path.name: path
        for path in _list_importable_files(DEFAULT_INPUT)
    }

    matched_targets: list[AllMethodTarget] = []
    unmatched_targets: list[AllMethodUnmatchedGold] = []

    for gold_spans_path in candidates:
        gold_display = _display_gold_export_path(gold_spans_path, output_dir)
        if not gold_spans_path.exists() or not gold_spans_path.is_file():
            unmatched_targets.append(
                AllMethodUnmatchedGold(
                    gold_spans_path=gold_spans_path,
                    reason="Gold spans file is missing.",
                    source_hint=None,
                    gold_display=gold_display,
                )
            )
            continue

        source_hint = _load_source_hint_from_gold_export(gold_spans_path)
        if source_hint is None:
            unmatched_targets.append(
                AllMethodUnmatchedGold(
                    gold_spans_path=gold_spans_path,
                    reason=(
                        "Missing source hint in manifest, freeform_span_labels.jsonl, "
                        "and freeform_segment_manifest.jsonl."
                    ),
                    source_hint=None,
                    gold_display=gold_display,
                )
            )
            continue

        source_file = importable_by_name.get(source_hint)
        if source_file is None:
            unmatched_targets.append(
                AllMethodUnmatchedGold(
                    gold_spans_path=gold_spans_path,
                    reason=f"No importable file named `{source_hint}` in {DEFAULT_INPUT}.",
                    source_hint=source_hint,
                    gold_display=gold_display,
                )
            )
            continue

        matched_targets.append(
            AllMethodTarget(
                gold_spans_path=gold_spans_path,
                source_file=source_file,
                source_file_name=source_file.name,
                gold_display=gold_display,
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
    if not selected_gold.exists():
        return _abort(f"Gold spans file not found: {selected_gold}")

    selected_source = source_file
    inferred_source = None
    if selected_source is None:
        inferred_source = _infer_source_file_from_freeform_gold(selected_gold)
    if selected_source is None and inferred_source is not None:
        use_inferred = _prompt_confirm(
            f"Use inferred source file `{inferred_source}`?",
            default=True,
        )
        if use_inferred is None:
            return _abort("Benchmark cancelled.")
        if use_inferred:
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


def _build_all_method_variants(
    *,
    base_settings: RunSettings,
    source_file: Path,
    include_codex_farm: bool,
) -> list[AllMethodVariant]:
    _ = include_codex_farm  # Reserved for future policy unlock.
    base_payload = base_settings.to_run_config_dict()
    variants: list[AllMethodVariant] = []
    source_ext = source_file.suffix.lower()

    if source_ext != ".epub":
        run_settings = RunSettings.from_dict(
            dict(base_payload),
            warn_context="all-method variant",
        )
        variants.append(
            AllMethodVariant(
                slug=f"source_{_all_method_variant_token(source_ext.lstrip('.') or 'unknown')}",
                run_settings=run_settings,
                dimensions={
                    "source_extension": source_ext or "none",
                },
            )
        )
        return variants

    dedupe_hashes: set[str] = set()
    for extractor in ALL_METHOD_EPUB_EXTRACTORS:
        if extractor == "unstructured":
            for parser_version, skip_headers_footers, preprocess_mode in product(
                ALL_METHOD_UNSTRUCTURED_HTML_PARSER_VERSIONS,
                ALL_METHOD_UNSTRUCTURED_SKIP_HEADERS_FOOTERS,
                ALL_METHOD_UNSTRUCTURED_PREPROCESS_MODES,
            ):
                payload = dict(base_payload)
                payload.update(
                    {
                        "epub_extractor": extractor,
                        "epub_unstructured_html_parser_version": parser_version,
                        "epub_unstructured_skip_headers_footers": skip_headers_footers,
                        "epub_unstructured_preprocess_mode": preprocess_mode,
                    }
                )
                run_settings = RunSettings.from_dict(
                    payload,
                    warn_context="all-method variant",
                )
                stable_hash = run_settings.stable_hash()
                if stable_hash in dedupe_hashes:
                    continue
                dedupe_hashes.add(stable_hash)
                variants.append(
                    AllMethodVariant(
                        slug=(
                            f"extractor_{_all_method_variant_token(extractor)}"
                            f"__parser_{_all_method_variant_token(parser_version)}"
                            f"__skiphf_{_all_method_variant_token(skip_headers_footers)}"
                            f"__pre_{_all_method_variant_token(preprocess_mode)}"
                        ),
                        run_settings=run_settings,
                        dimensions={
                            "epub_extractor": extractor,
                            "epub_unstructured_html_parser_version": parser_version,
                            "epub_unstructured_skip_headers_footers": skip_headers_footers,
                            "epub_unstructured_preprocess_mode": preprocess_mode,
                        },
                    )
                )
            continue

        payload = dict(base_payload)
        payload["epub_extractor"] = extractor
        run_settings = RunSettings.from_dict(
            payload,
            warn_context="all-method variant",
        )
        stable_hash = run_settings.stable_hash()
        if stable_hash in dedupe_hashes:
            continue
        dedupe_hashes.add(stable_hash)
        variants.append(
            AllMethodVariant(
                slug=f"extractor_{_all_method_variant_token(extractor)}",
                run_settings=run_settings,
                dimensions={
                    "epub_extractor": extractor,
                },
            )
        )

    return variants


def _build_all_method_target_variants(
    *,
    targets: list[AllMethodTarget],
    base_settings: RunSettings,
    include_codex_farm: bool,
) -> list[tuple[AllMethodTarget, list[AllMethodVariant]]]:
    return [
        (
            target,
            _build_all_method_variants(
                base_settings=base_settings,
                source_file=target.source_file,
                include_codex_farm=include_codex_farm,
            ),
        )
        for target in targets
    ]


def _resolve_all_method_codex_choice(include_codex_farm: bool) -> tuple[bool, str | None]:
    if not include_codex_farm:
        return False, None
    if os.getenv(ALL_METHOD_CODEX_FARM_UNLOCK_ENV, "").strip() != "1":
        return (
            False,
            "Codex Farm is policy-locked off; "
            f"set {ALL_METHOD_CODEX_FARM_UNLOCK_ENV}=1 once policy unlocks. "
            "Continuing without Codex Farm permutations.",
        )
    return (
        False,
        "Codex Farm was requested, but recipe codex-farm parsing remains policy-locked OFF. "
        "Continuing without Codex Farm permutations.",
    )


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


def _resolve_all_method_source_parallelism(
    *,
    total_sources: int,
    requested: int | None = None,
) -> int:
    total = max(1, _report_count(total_sources))
    default_parallel_sources = min(ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT, total)
    requested_parallel_sources = _report_count(requested)
    if requested_parallel_sources <= 0:
        return default_parallel_sources
    return max(1, min(requested_parallel_sources, total))


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
    split_phase_slots: int
    wing_backlog_target: int
    eval_tail_headroom_configured: int
    eval_tail_headroom_effective: int
    eval_tail_headroom_mode: str
    smart_scheduler_enabled: bool
    max_active_during_eval: int
    effective_inflight_pipelines: int
    source_parallelism_effective: int
    cpu_budget_per_source: int
    cpu_budget_total: int


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
    inflight, split_slots = _resolve_all_method_scheduler_limits(
        total_variants=total_variants,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
    )
    total = max(1, _report_count(total_variants))
    wing_default = max(1, split_slots)
    wing_target_requested = _report_count(wing_backlog_target)
    wing_target = wing_target_requested if wing_target_requested > 0 else wing_default
    wing_target = max(1, wing_target)

    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1
    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)

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

    return _AllMethodSchedulerRuntime(
        configured_inflight_pipelines=inflight,
        split_phase_slots=split_slots,
        wing_backlog_target=wing_target,
        eval_tail_headroom_configured=eval_tail_configured,
        eval_tail_headroom_effective=eval_tail_effective,
        eval_tail_headroom_mode=eval_tail_mode,
        smart_scheduler_enabled=smart_enabled,
        max_active_during_eval=max_active_during_eval,
        effective_inflight_pipelines=max_active_during_eval if smart_enabled else inflight,
        source_parallelism_effective=source_parallelism,
        cpu_budget_per_source=cpu_budget_per_source,
        cpu_budget_total=cpu_budget_total,
    )


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


def _run_all_method_config_once(
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
    split_worker_cap_per_config: int | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    config_started = time.monotonic()
    config_dir_name = _all_method_config_dir_name(config_index, variant)
    eval_output_dir = root_output_dir / config_dir_name
    scratch_output_dir = scratch_root / config_dir_name
    processed_output_dir = processed_output_root / config_dir_name
    if eval_output_dir.exists():
        shutil.rmtree(eval_output_dir)
    if scratch_output_dir.exists():
        shutil.rmtree(scratch_output_dir)

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
            ):
                with _benchmark_scheduler_event_overrides(
                    scheduler_event_callback=_scheduler_event_callback
                ):
                    labelstudio_benchmark(
                        gold_spans=gold_spans_path,
                        source_file=source_file,
                        output_dir=scratch_output_dir,
                        processed_output_dir=processed_output_dir,
                        eval_output_dir=eval_output_dir,
                        eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
                        overlap_threshold=overlap_threshold,
                        force_source_match=force_source_match,
                        no_upload=True,
                        workers=effective_workers,
                        pdf_split_workers=effective_pdf_split_workers,
                        epub_split_workers=effective_epub_split_workers,
                        pdf_pages_per_job=variant.run_settings.pdf_pages_per_job,
                        epub_spine_items_per_job=variant.run_settings.epub_spine_items_per_job,
                        ocr_device=variant.run_settings.ocr_device.value,
                        ocr_batch_size=variant.run_settings.ocr_batch_size,
                        warm_models=variant.run_settings.warm_models,
                        epub_extractor=variant.run_settings.epub_extractor.value,
                        epub_unstructured_html_parser_version=(
                            variant.run_settings.epub_unstructured_html_parser_version.value
                        ),
                        epub_unstructured_skip_headers_footers=(
                            variant.run_settings.epub_unstructured_skip_headers_footers
                        ),
                        epub_unstructured_preprocess_mode=(
                            variant.run_settings.epub_unstructured_preprocess_mode.value
                        ),
                        llm_recipe_pipeline=variant.run_settings.llm_recipe_pipeline.value,
                        codex_farm_cmd=variant.run_settings.codex_farm_cmd,
                        codex_farm_root=variant.run_settings.codex_farm_root,
                        codex_farm_workspace_root=variant.run_settings.codex_farm_workspace_root,
                        codex_farm_pipeline_pass1=variant.run_settings.codex_farm_pipeline_pass1,
                        codex_farm_pipeline_pass2=variant.run_settings.codex_farm_pipeline_pass2,
                        codex_farm_pipeline_pass3=variant.run_settings.codex_farm_pipeline_pass3,
                        codex_farm_context_blocks=variant.run_settings.codex_farm_context_blocks,
                        codex_farm_failure_mode=variant.run_settings.codex_farm_failure_mode.value,
                        alignment_cache_dir=alignment_cache_dir,
                    )
    except Exception as exc:  # noqa: BLE001
        _emit_scheduler_event("config_finished", status="failed", error=str(exc))
        return _all_method_failed_row(
            config_index=config_index,
            config_dir_name=config_dir_name,
            variant=variant,
            error=str(exc),
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )

    report_json_path = eval_output_dir / "eval_report.json"
    if not report_json_path.exists():
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=f"Missing eval_report.json in {eval_output_dir}",
        )
        return _all_method_failed_row(
            config_index=config_index,
            config_dir_name=config_dir_name,
            variant=variant,
            error=f"Missing eval_report.json in {eval_output_dir}",
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )

    try:
        report = json.loads(report_json_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _emit_scheduler_event(
            "config_finished",
            status="failed",
            error=f"Failed to parse eval report for {config_dir_name}: {exc}",
        )
        return _all_method_failed_row(
            config_index=config_index,
            config_dir_name=config_dir_name,
            variant=variant,
            error=f"Failed to parse eval report for {config_dir_name}: {exc}",
            elapsed_seconds=max(0.0, time.monotonic() - config_started),
        )

    config_wall_seconds = max(0.0, time.monotonic() - config_started)
    report_timing = _normalize_timing_payload(report.get("timing"))
    report_total_seconds = _report_optional_metric(report_timing.get("total_seconds"))
    config_timing = _timing_with_updates(
        report_timing,
        total_seconds=(
            report_total_seconds if report_total_seconds is not None else config_wall_seconds
        ),
        checkpoints={"all_method_config_wall_seconds": config_wall_seconds},
    )

    pred_context = _load_pred_run_recipe_context(eval_output_dir / "prediction-run")
    row = {
        "config_index": config_index,
        "config_dir": config_dir_name,
        "slug": variant.slug,
        "status": "ok",
        "error": "",
        "run_config_hash": pred_context.run_config_hash or variant.run_settings.stable_hash(),
        "run_config_summary": pred_context.run_config_summary
        or variant.run_settings.summary(),
        "precision": _report_metric(report.get("precision")),
        "recall": _report_metric(report.get("recall")),
        "f1": _report_metric(report.get("f1")),
        "practical_precision": _report_metric(report.get("practical_precision")),
        "practical_recall": _report_metric(report.get("practical_recall")),
        "practical_f1": _report_metric(report.get("practical_f1")),
        "eval_report_json": _path_for_manifest(root_output_dir, report_json_path),
        "eval_report_md": _path_for_manifest(
            root_output_dir,
            eval_output_dir / "eval_report.md",
        ),
        "duration_seconds": config_wall_seconds,
        "timing": config_timing,
        "dimensions": dict(variant.dimensions),
    }
    _emit_scheduler_event(
        "config_finished",
        status="ok",
        duration_seconds=config_wall_seconds,
    )
    return row


def _render_all_method_report_md(report_payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "# All Method Benchmark Report",
        "",
        f"- Created at: {report_payload.get('created_at', '')}",
        f"- Source file: {report_payload.get('source_file', '')}",
        f"- Gold spans: {report_payload.get('gold_spans_path', '')}",
        f"- Eval mode: {report_payload.get('eval_mode', BENCHMARK_EVAL_MODE_CANONICAL_TEXT)}",
        f"- Total configurations: {report_payload.get('variant_count', 0)}",
        f"- Successful configurations: {report_payload.get('successful_variants', 0)}",
        f"- Failed configurations: {report_payload.get('failed_variants', 0)}",
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
        row_timing = _normalize_timing_payload(row.get("timing"))
        row_seconds = _report_optional_metric(row_timing.get("total_seconds"))
        timing_suffix = f", time={row_seconds:.2f}s" if row_seconds is not None else ""
        lines.append(
            (
                f"- {rank_prefix}{config_dir} "
                f"(precision={_report_metric(row.get('precision')):.3f}, "
                f"recall={_report_metric(row.get('recall')):.3f}, "
                f"f1={_report_metric(row.get('f1')):.3f}, "
                f"practical_f1={_report_metric(row.get('practical_f1')):.3f}"
                f"{timing_suffix}) "
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
        f"- Matched targets: {report_payload.get('matched_target_count', 0)}",
        f"- Unmatched targets: {report_payload.get('unmatched_target_count', 0)}",
        (
            "- Source parallelism configured/effective: "
            f"{_report_count(report_payload.get('source_parallelism_configured'))}/"
            f"{_report_count(report_payload.get('source_parallelism_effective'))}"
        ),
        f"- Planned config runs: {report_payload.get('total_config_runs_planned', 0)}",
        f"- Completed config runs: {report_payload.get('total_config_runs_completed', 0)}",
        f"- Successful config runs: {report_payload.get('total_config_runs_successful', 0)}",
        (
            "- Config timeout / failed-config retry limit: "
            f"{('off' if report_payload.get('config_timeout_seconds') is None else str(_report_count(report_payload.get('config_timeout_seconds'))) + 's')}/"
            f"{_report_count(report_payload.get('retry_failed_configs_requested'))}"
        ),
    ]

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
    wing_backlog_target: int | None = None,
    smart_scheduler: bool = False,
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

    total_targets = len(target_variants)
    total_planned_config_runs = sum(len(variants) for _target, variants in target_variants)
    source_parallelism_default = min(
        ALL_METHOD_MAX_PARALLEL_SOURCES_DEFAULT,
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
    refresh_dashboard_after_source = source_parallelism_effective <= 1

    slug_counts: dict[str, int] = {}
    source_jobs: list[dict[str, Any]] = []
    for source_position, (target, variants) in enumerate(target_variants):
        source_slug_base = slugify_name(target.source_file.stem)
        source_slug_count = slug_counts.get(source_slug_base, 0) + 1
        slug_counts[source_slug_base] = source_slug_count
        source_slug = (
            source_slug_base
            if source_slug_count == 1
            else f"{source_slug_base}__{source_slug_count:02d}"
        )
        source_jobs.append(
            {
                "source_position": source_position,
                "source_index": source_position + 1,
                "target": target,
                "variants": variants,
                "source_slug": source_slug,
                "source_root": root_output_dir / source_slug,
                "source_processed_root": processed_output_root / source_slug,
            }
        )

    source_rows: list[dict[str, Any] | None] = [None] * len(source_jobs)
    status_lock = threading.RLock()

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

    def _failed_source_row(
        *,
        target: AllMethodTarget,
        source_slug: str,
        variants: list[AllMethodVariant],
        error: str,
    ) -> dict[str, Any]:
        return {
            "status": "failed",
            "source_file": str(target.source_file),
            "source_file_name": target.source_file_name,
            "gold_spans_path": str(target.gold_spans_path),
            "gold_display": target.gold_display,
            "source_slug": source_slug,
            "report_path": "",
            "report_json_path": "",
            "variant_count_planned": len(variants),
            "variant_count_completed": 0,
            "variant_count_successful": 0,
            "winner_metrics": {},
            "timing_summary": {},
            "scheduler": {},
            "error": error,
        }

    def _run_source_job(job: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        source_position = int(job["source_position"])
        source_index = int(job["source_index"])
        target = cast(AllMethodTarget, job["target"])
        variants = cast(list[AllMethodVariant], job["variants"])
        source_slug = str(job["source_slug"])
        source_root = cast(Path, job["source_root"])
        source_processed_root = cast(Path, job["source_processed_root"])

        progress_label = format_task_counter(
            "Running",
            source_index,
            max(1, total_targets),
            noun="source",
        )
        if dashboard is not None:
            dashboard.start_source(source_position)
        _emit_status(f"{progress_label}: {target.source_file_name}")

        if not variants:
            if dashboard is not None:
                dashboard.finish_source(source_position, failed=True)
            _emit_status(
                (
                    "Failed "
                    f"{format_task_counter('', source_index, max(1, total_targets), noun='source')}: "
                    "No benchmark variants generated for this source."
                ),
                color=typer.colors.RED,
            )
            return (
                source_position,
                _failed_source_row(
                    target=target,
                    source_slug=source_slug,
                    variants=variants,
                    error="No benchmark variants generated for this source.",
                ),
            )

        def _source_progress(message: str) -> None:
            if progress_callback is None:
                return
            with status_lock:
                if parse_worker_activity(message) is not None:
                    _notify_progress_callback(progress_callback, message)
                    return
                if _looks_like_all_method_dashboard_snapshot(message):
                    # Always render from shared dashboard state so outer queue rows
                    # stay stable even if an inbound snapshot is stale/partial.
                    if dashboard is not None:
                        _notify_progress_callback(progress_callback, dashboard.render())
                    else:
                        _notify_progress_callback(progress_callback, message)
                    return
                if dashboard is not None:
                    dashboard.set_task(message)
                    _notify_progress_callback(progress_callback, dashboard.render())
                    return
                _notify_progress_callback(progress_callback, message)

        try:
            report_md_path = _run_all_method_benchmark(
                gold_spans_path=target.gold_spans_path,
                source_file=target.source_file,
                variants=variants,
                include_codex_farm_requested=include_codex_farm_requested,
                include_codex_farm_effective=include_codex_farm_effective,
                root_output_dir=source_root,
                processed_output_root=source_processed_root,
                overlap_threshold=overlap_threshold,
                force_source_match=force_source_match,
                progress_callback=_source_progress if progress_callback else None,
                dashboard=dashboard,
                dashboard_source_index=source_position if dashboard is not None else None,
                max_inflight_pipelines=max_inflight_pipelines,
                max_concurrent_split_phases=max_concurrent_split_phases,
                max_eval_tail_pipelines=max_eval_tail_pipelines,
                config_timeout_seconds=effective_config_timeout_seconds,
                retry_failed_configs=effective_retry_failed_configs,
                wing_backlog_target=wing_backlog_target,
                smart_scheduler=smart_scheduler,
                refresh_dashboard_after_source=refresh_dashboard_after_source,
                source_parallelism_effective=source_parallelism_effective,
            )
            report_json_path = report_md_path.with_suffix(".json")
            report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
            if not isinstance(report_payload, dict):
                raise ValueError("Invalid all-method report payload.")

            winner = report_payload.get("winner_by_f1")
            winner_metrics = {
                "precision": _report_metric(
                    winner.get("precision") if isinstance(winner, dict) else None
                ),
                "recall": _report_metric(
                    winner.get("recall") if isinstance(winner, dict) else None
                ),
                "f1": _report_metric(
                    winner.get("f1") if isinstance(winner, dict) else None
                ),
            }
            successful_variants = _report_count(report_payload.get("successful_variants"))
            failed_variants = _report_count(report_payload.get("failed_variants"))
            source_timing_summary = report_payload.get("timing_summary")
            normalized_source_timing = (
                dict(source_timing_summary)
                if isinstance(source_timing_summary, dict)
                else {}
            )
            source_scheduler_summary = report_payload.get("scheduler")
            normalized_source_scheduler = (
                dict(source_scheduler_summary)
                if isinstance(source_scheduler_summary, dict)
                else {}
            )

            row = {
                "status": "ok",
                "source_file": str(target.source_file),
                "source_file_name": target.source_file_name,
                "gold_spans_path": str(target.gold_spans_path),
                "gold_display": target.gold_display,
                "source_slug": source_slug,
                "report_path": _path_for_manifest(root_output_dir, report_md_path) or "",
                "report_json_path": (
                    _path_for_manifest(root_output_dir, report_json_path) or ""
                ),
                "variant_count_planned": len(variants),
                "variant_count_completed": successful_variants + failed_variants,
                "variant_count_successful": successful_variants,
                "winner_metrics": winner_metrics,
                "timing_summary": normalized_source_timing,
                "scheduler": normalized_source_scheduler,
                "error": "",
            }
            if dashboard is not None:
                dashboard.finish_source(source_position, failed=False)
            _emit_status(
                (
                    "Completed "
                    f"{format_task_counter('', source_index, max(1, total_targets), noun='source')}: "
                    f"{target.source_file_name}"
                ),
                color=typer.colors.CYAN,
            )
            return source_position, row
        except Exception as exc:  # noqa: BLE001
            if dashboard is not None:
                dashboard.finish_source(source_position, failed=True)
            _emit_status(
                (
                    "Failed "
                    f"{format_task_counter('', source_index, max(1, total_targets), noun='source')}: {exc}"
                ),
                color=typer.colors.RED,
            )
            return (
                source_position,
                _failed_source_row(
                    target=target,
                    source_slug=source_slug,
                    variants=variants,
                    error=str(exc),
                ),
            )

    if source_jobs:
        if source_parallelism_effective <= 1:
            for job in source_jobs:
                source_position, row = _run_source_job(job)
                source_rows[source_position] = row
        else:
            try:
                source_executor = ThreadPoolExecutor(max_workers=source_parallelism_effective)
            except (PermissionError, OSError) as exc:
                _emit_status(
                    (
                        "Source parallel executor unavailable "
                        f"({exc}); falling back to serial source mode."
                    ),
                    color=typer.colors.YELLOW,
                )
                source_parallelism_effective = 1
                for job in source_jobs:
                    source_position, row = _run_source_job(job)
                    source_rows[source_position] = row
            else:
                pending_jobs = list(source_jobs)
                futures: dict[Any, dict[str, Any]] = {}
                with source_executor:
                    while pending_jobs or futures:
                        while pending_jobs and len(futures) < source_parallelism_effective:
                            next_job = pending_jobs.pop(0)
                            try:
                                future = source_executor.submit(_run_source_job, next_job)
                            except Exception as exc:  # noqa: BLE001
                                source_position = int(next_job["source_position"])
                                target = cast(AllMethodTarget, next_job["target"])
                                variants = cast(list[AllMethodVariant], next_job["variants"])
                                source_slug = str(next_job["source_slug"])
                                _emit_status(
                                    (
                                        "Failed "
                                        f"{format_task_counter('', source_position + 1, max(1, total_targets), noun='source')}: "
                                        f"Failed to submit source worker: {exc}"
                                    ),
                                    color=typer.colors.RED,
                                )
                                source_rows[source_position] = _failed_source_row(
                                    target=target,
                                    source_slug=source_slug,
                                    variants=variants,
                                    error=f"Failed to submit source worker: {exc}",
                                )
                                if dashboard is not None:
                                    dashboard.finish_source(source_position, failed=True)
                                continue
                            futures[future] = next_job

                        if not futures:
                            continue

                        done, _ = wait(
                            list(futures.keys()),
                            return_when=FIRST_COMPLETED,
                        )
                        for done_future in done:
                            submitted_job = futures.pop(done_future)
                            try:
                                source_position, row = done_future.result()
                            except Exception as exc:  # noqa: BLE001
                                source_position = int(submitted_job["source_position"])
                                target = cast(AllMethodTarget, submitted_job["target"])
                                variants = cast(list[AllMethodVariant], submitted_job["variants"])
                                source_slug = str(submitted_job["source_slug"])
                                _emit_status(
                                    (
                                        "Failed "
                                        f"{format_task_counter('', source_position + 1, max(1, total_targets), noun='source')}: "
                                        f"Source worker failed: {exc}"
                                    ),
                                    color=typer.colors.RED,
                                )
                                row = _failed_source_row(
                                    target=target,
                                    source_slug=source_slug,
                                    variants=variants,
                                    error=f"Source worker failed: {exc}",
                                )
                                if dashboard is not None:
                                    dashboard.finish_source(source_position, failed=True)
                            source_rows[source_position] = row

    ordered_source_rows: list[dict[str, Any]] = []
    for source_position, row in enumerate(source_rows):
        if isinstance(row, dict):
            ordered_source_rows.append(row)
            continue
        fallback_job = source_jobs[source_position]
        fallback_target = cast(AllMethodTarget, fallback_job["target"])
        fallback_variants = cast(list[AllMethodVariant], fallback_job["variants"])
        ordered_source_rows.append(
            _failed_source_row(
                target=fallback_target,
                source_slug=str(fallback_job["source_slug"]),
                variants=fallback_variants,
                error="Source run did not produce a result.",
            )
        )
    source_rows = ordered_source_rows

    successful_source_count = sum(
        1 for row in source_rows if str(row.get("status", "")).lower() == "ok"
    )
    total_completed_config_runs = sum(
        _report_count(row.get("variant_count_completed")) for row in source_rows
    )
    total_successful_config_runs = sum(
        _report_count(row.get("variant_count_successful")) for row in source_rows
    )
    run_wall_seconds = max(0.0, time.monotonic() - run_started)

    source_timing_values: list[tuple[dict[str, Any], float]] = []
    config_total_seconds = 0.0
    for row in source_rows:
        if str(row.get("status", "")).lower() != "ok":
            continue
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

    scheduler_capacity_seconds = 0.0
    scheduler_busy_seconds = 0.0
    scheduler_idle_gap_seconds = 0.0
    scheduler_wing_area_seconds = 0.0
    scheduler_wing_seconds_weight = 0.0
    scheduler_max_wing_backlog = 0
    scheduler_max_active_pipelines = 0
    scheduler_max_eval_active = 0
    scheduler_wing_backlog_target = 0
    scheduler_split_slots = 0
    scheduler_split_worker_cap = 0
    scheduler_split_worker_cap_by_cpu = 0
    scheduler_split_worker_cap_by_memory = 0
    scheduler_smart_tail_buffer = 0
    scheduler_eval_tail_headroom_configured = 0
    scheduler_eval_tail_headroom_effective = 0
    scheduler_max_active_during_eval = 0
    scheduler_source_parallelism_effective = 0
    scheduler_cpu_budget_per_source = 0
    scheduler_cpu_budget_total = 0
    scheduler_effective_inflight = 0
    scheduler_sources = 0
    scheduler_modes: set[str] = set()
    scheduler_eval_tail_modes: set[str] = set()
    for row in source_rows:
        if str(row.get("status", "")).lower() != "ok":
            continue
        scheduler = row.get("scheduler")
        if not isinstance(scheduler, dict):
            continue
        scheduler_sources += 1
        scheduler_modes.add(str(scheduler.get("mode") or "fixed"))
        scheduler_split_slots = max(
            scheduler_split_slots,
            _report_count(scheduler.get("split_phase_slots")),
        )
        scheduler_wing_backlog_target = max(
            scheduler_wing_backlog_target,
            _report_count(scheduler.get("wing_backlog_target")),
        )
        scheduler_split_worker_cap = max(
            scheduler_split_worker_cap,
            _report_count(scheduler.get("split_worker_cap_per_config")),
        )
        scheduler_split_worker_cap_by_cpu = max(
            scheduler_split_worker_cap_by_cpu,
            _report_count(scheduler.get("split_worker_cap_by_cpu")),
        )
        scheduler_split_worker_cap_by_memory = max(
            scheduler_split_worker_cap_by_memory,
            _report_count(scheduler.get("split_worker_cap_by_memory")),
        )
        scheduler_smart_tail_buffer = max(
            scheduler_smart_tail_buffer,
            _report_count(scheduler.get("smart_tail_buffer_slots")),
        )
        scheduler_eval_tail_modes.add(
            str(scheduler.get("eval_tail_headroom_mode") or "auto")
        )
        scheduler_eval_tail_headroom_configured = max(
            scheduler_eval_tail_headroom_configured,
            _report_count(
                scheduler.get(
                    "eval_tail_headroom_configured",
                    scheduler.get("max_eval_tail_pipelines"),
                )
            ),
        )
        scheduler_eval_tail_headroom_effective = max(
            scheduler_eval_tail_headroom_effective,
            _report_count(
                scheduler.get(
                    "eval_tail_headroom_effective",
                    scheduler.get("max_eval_tail_pipelines"),
                )
            ),
        )
        scheduler_max_active_during_eval = max(
            scheduler_max_active_during_eval,
            _report_count(
                scheduler.get(
                    "max_active_during_eval",
                    scheduler.get("effective_inflight_pipelines"),
                )
            ),
        )
        scheduler_source_parallelism_effective = max(
            scheduler_source_parallelism_effective,
            _report_count(scheduler.get("source_parallelism_effective")),
        )
        scheduler_cpu_budget_per_source = max(
            scheduler_cpu_budget_per_source,
            _report_count(scheduler.get("cpu_budget_per_source")),
        )
        scheduler_cpu_budget_total = max(
            scheduler_cpu_budget_total,
            _report_count(scheduler.get("cpu_budget_total")),
        )
        scheduler_effective_inflight = max(
            scheduler_effective_inflight,
            _report_count(scheduler.get("effective_inflight_pipelines")),
        )
        capacity_seconds = _report_metric(scheduler.get("heavy_slot_capacity_seconds"))
        busy_seconds = _report_metric(scheduler.get("heavy_slot_busy_seconds"))
        idle_gap_seconds = _report_metric(scheduler.get("idle_gap_seconds"))
        avg_wing = _report_metric(scheduler.get("avg_wing_backlog"))
        max_wing = _report_count(scheduler.get("max_wing_backlog"))
        max_active = _report_count(scheduler.get("max_active_pipelines_observed"))
        max_eval_active = _report_count(scheduler.get("max_eval_active_observed"))
        scheduler_capacity_seconds += capacity_seconds
        scheduler_busy_seconds += busy_seconds
        scheduler_idle_gap_seconds += idle_gap_seconds
        scheduler_wing_area_seconds += avg_wing * capacity_seconds
        scheduler_wing_seconds_weight += capacity_seconds
        scheduler_max_wing_backlog = max(scheduler_max_wing_backlog, max_wing)
        scheduler_max_active_pipelines = max(
            scheduler_max_active_pipelines,
            max_active,
        )
        scheduler_max_eval_active = max(
            scheduler_max_eval_active,
            max_eval_active,
        )
    scheduler_utilization_pct = (
        (scheduler_busy_seconds / scheduler_capacity_seconds) * 100.0
        if scheduler_capacity_seconds > 0
        else 0.0
    )
    scheduler_avg_wing_backlog = (
        scheduler_wing_area_seconds / scheduler_wing_seconds_weight
        if scheduler_wing_seconds_weight > 0
        else 0.0
    )

    report_payload: dict[str, Any] = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "eval_mode": BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
        "matched_target_count": total_targets,
        "unmatched_target_count": len(unmatched_targets),
        "source_parallelism_configured": source_parallelism_configured,
        "source_parallelism_effective": source_parallelism_effective,
        "total_config_runs_planned": total_planned_config_runs,
        "total_config_runs_completed": total_completed_config_runs,
        "total_config_runs_successful": total_successful_config_runs,
        "successful_source_count": successful_source_count,
        "failed_source_count": total_targets - successful_source_count,
        "config_timeout_seconds": effective_config_timeout_seconds,
        "retry_failed_configs_requested": effective_retry_failed_configs,
        "include_codex_farm_requested": include_codex_farm_requested,
        "include_codex_farm_effective": include_codex_farm_effective,
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
        "scheduler_summary": {
            "mode": (
                "mixed"
                if len(scheduler_modes) > 1
                else (next(iter(scheduler_modes)) if scheduler_modes else "fixed")
            ),
            "source_count": scheduler_sources,
            "effective_inflight_pipelines": scheduler_effective_inflight,
            "split_phase_slots": scheduler_split_slots,
            "wing_backlog_target": scheduler_wing_backlog_target,
            "split_worker_cap_per_config": scheduler_split_worker_cap,
            "split_worker_cap_by_cpu": scheduler_split_worker_cap_by_cpu,
            "split_worker_cap_by_memory": scheduler_split_worker_cap_by_memory,
            "eval_tail_headroom_mode": (
                "mixed"
                if len(scheduler_eval_tail_modes) > 1
                else (
                    next(iter(scheduler_eval_tail_modes))
                    if scheduler_eval_tail_modes
                    else "auto"
                )
            ),
            "eval_tail_headroom_configured": scheduler_eval_tail_headroom_configured,
            "eval_tail_headroom_effective": scheduler_eval_tail_headroom_effective,
            "max_active_during_eval": scheduler_max_active_during_eval,
            "source_parallelism_effective": scheduler_source_parallelism_effective,
            "cpu_budget_per_source": scheduler_cpu_budget_per_source,
            "cpu_budget_total": scheduler_cpu_budget_total,
            "max_eval_tail_pipelines": scheduler_eval_tail_headroom_effective,
            "smart_tail_buffer_slots": scheduler_smart_tail_buffer,
            "config_timeout_seconds": effective_config_timeout_seconds,
            "failed_retry_limit": effective_retry_failed_configs,
            "heavy_slot_capacity_seconds": scheduler_capacity_seconds,
            "heavy_slot_busy_seconds": scheduler_busy_seconds,
            "heavy_slot_utilization_pct": scheduler_utilization_pct,
            "avg_wing_backlog": scheduler_avg_wing_backlog,
            "max_wing_backlog": scheduler_max_wing_backlog,
            "idle_gap_seconds": scheduler_idle_gap_seconds,
            "max_active_pipelines_observed": scheduler_max_active_pipelines,
            "max_eval_active_observed": scheduler_max_eval_active,
        },
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

    if not refresh_dashboard_after_source:
        history_csv_path = history_csv_for_output(
            processed_output_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
        )
        _refresh_dashboard_after_history_write(
            csv_path=history_csv_path,
            reason="all-method benchmark multi-source batch append",
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
) -> Path:
    source_started = time.monotonic()
    root_output_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = root_output_dir / ".scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    processed_output_root.mkdir(parents=True, exist_ok=True)
    split_phase_gate_dir = root_output_dir / ".split_phase_slots"
    split_phase_gate_dir.mkdir(parents=True, exist_ok=True)
    canonical_alignment_cache_dir = root_output_dir / ".cache" / "canonical_alignment"
    scheduler_events_dir = root_output_dir / ".scheduler_events"
    if scheduler_events_dir.exists():
        shutil.rmtree(scheduler_events_dir)
    scheduler_events_dir.mkdir(parents=True, exist_ok=True)

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
    effective_split_phase_slots = scheduler_runtime.split_phase_slots
    effective_wing_backlog_target = scheduler_runtime.wing_backlog_target
    configured_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_configured
    effective_eval_tail_headroom = scheduler_runtime.eval_tail_headroom_effective
    eval_tail_headroom_mode = scheduler_runtime.eval_tail_headroom_mode
    effective_smart_scheduler = scheduler_runtime.smart_scheduler_enabled
    max_active_during_eval = scheduler_runtime.max_active_during_eval
    effective_inflight_pipelines = scheduler_runtime.effective_inflight_pipelines
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
            if parse_worker_activity(cleaned) is not None:
                _notify_progress_callback(progress_callback, cleaned)
                return
            if dashboard is not None:
                dashboard.set_task(cleaned)
                _notify_progress_callback(progress_callback, dashboard.render())
                return
            _notify_progress_callback(progress_callback, cleaned)
            return
        typer.secho(cleaned, fg=color)

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

    def _scheduler_event_path(config_index: int) -> Path:
        return scheduler_events_dir / f"config_{config_index:03d}.jsonl"

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
        scheduler_last_tick = now
        return counts

    def _scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> str:
        return (
            f"scheduler heavy {counts['heavy_active']}/{effective_split_phase_slots} "
            f"| wing {counts['wing_backlog']} "
            f"| eval {counts['evaluate_active']} "
            f"| active {counts['active']} | pending {max(0, pending_count)}"
        )

    def _emit_scheduler_snapshot(*, counts: dict[str, int], pending_count: int) -> None:
        nonlocal scheduler_last_snapshot
        if progress_callback is None:
            return
        snapshot = _scheduler_snapshot(counts=counts, pending_count=pending_count)
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
            "split_phase_slots": effective_split_phase_slots,
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
            "source_parallelism_effective": scheduler_source_parallelism,
            "cpu_budget_per_source": scheduler_cpu_budget_per_source,
            "cpu_budget_total": scheduler_cpu_budget_total,
            # Legacy aliases retained for downstream compatibility.
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
                    if parse_worker_activity(message) is not None:
                        _notify_progress_callback(progress_callback, message)
                        return
                    _notify_progress_callback(
                        progress_callback,
                        f"{progress_label}: {variant.slug} | {message}",
                    )
                    return
                if parse_worker_activity(message) is not None:
                    _notify_progress_callback(progress_callback, message)
                    return
                dashboard.set_task(message)
                _notify_progress_callback(progress_callback, dashboard.render())

            row = _run_all_method_config_once(
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
        nonlocal scheduler_smart_enabled
        force_parallel_timeout = effective_config_timeout_seconds is not None
        if (len(items) <= 1 or effective_inflight_pipelines <= 1) and not force_parallel_timeout:
            _run_serial_variants(items, dashboard_tracking=dashboard_tracking)
            return

        pending_items = list(items)
        futures: dict[Any, tuple[int, AllMethodVariant, float]] = {}
        worker_limit = min(effective_inflight_pipelines, len(items))
        scheduler_base_target = min(
            total_variants,
            effective_split_phase_slots + effective_wing_backlog_target,
        )

        try:
            executor = ProcessPoolExecutor(max_workers=worker_limit)
        except (PermissionError, OSError) as exc:
            _emit_status(
                f"Parallel executor unavailable ({exc}); falling back to serial mode.",
                color=typer.colors.YELLOW,
            )
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
                    _run_all_method_config_once,
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
                _emit_scheduler_snapshot(
                    counts=counts,
                    pending_count=len(pending_items),
                )

                while len(futures) < worker_limit and pending_items:
                    if scheduler_smart_enabled:
                        heavy_plus_wing = counts["heavy_active"] + counts["wing_backlog"]
                        eval_tail_admission_open = (
                            counts["evaluate_active"] > 0 and len(pending_items) > 0
                        )
                        smart_active_cap = (
                            max_active_during_eval
                            if eval_tail_admission_open
                            else configured_inflight_pipelines
                        )
                        smart_active_cap = max(1, min(total_variants, smart_active_cap))
                        guard_target = scheduler_base_target
                        if eval_tail_admission_open:
                            guard_target = min(
                                scheduler_base_target,
                                max_active_during_eval,
                            )
                        if counts["active"] >= smart_active_cap:
                            break
                        if (
                            heavy_plus_wing >= guard_target
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

                if effective_config_timeout_seconds is None:
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
                        f"{len(timed_out)} run(s); restarting worker pool."
                    ),
                    color=typer.colors.YELLOW,
                )
                _shutdown_parallel_executor(executor, terminate_workers=True)
                try:
                    executor = ProcessPoolExecutor(max_workers=worker_limit)
                except (PermissionError, OSError) as exc:
                    _emit_status(
                        (
                            "Parallel executor unavailable after timeout restart "
                            f"({exc}); continuing in serial mode for remaining configs."
                        ),
                        color=typer.colors.YELLOW,
                    )
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
    scheduler_summary = _finalize_scheduler_metrics()
    scheduler_summary["config_timeout_seconds"] = effective_config_timeout_seconds
    scheduler_summary["failed_retry_limit"] = effective_retry_failed_configs
    scheduler_summary["retry_passes_executed"] = retry_passes_executed
    scheduler_summary["retry_recovered_configs"] = retry_recovered_configs

    successful_rows = [row for row in variant_rows if row.get("status") == "ok"]
    failed_rows = [row for row in variant_rows if row.get("status") != "ok"]
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
        "variant_count": total_variants,
        "successful_variants": len(successful_rows),
        "failed_variants": len(failed_rows),
        "retry_failed_configs_requested": effective_retry_failed_configs,
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
        _refresh_dashboard_after_history_write(
            csv_path=history_csv_path,
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
    for path_key, artifact_key in (
        ("intermediate drafts", "intermediate_drafts_dir"),
        ("final drafts", "final_drafts_dir"),
        ("tips", "tips_dir"),
        ("chunks", "chunks_dir"),
        ("knowledge", "knowledge_dir"),
        (".bench", "bench_dir"),
        ("tags", "tags_dir"),
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
    tags_index = run_root / "tags" / "tags_index.json"
    if tags_index.exists():
        artifacts["tags_index"] = str(tags_index.relative_to(run_root))
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
    manifest = RunManifest(
        run_kind=run_kind,
        run_id=run_root.name,
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        source=RunSource(
            path=source_path,
            source_hash=source_hash,
            importer_name=importer_name,
        ),
        run_config=run_config,
        artifacts=artifacts,
        notes=notes,
    )
    _write_run_manifest_best_effort(run_root, manifest)


def _require_importer(path: Path):
    importer, score = registry.best_importer_for_path(path)
    if importer is None or score <= 0:
        _fail("No importer available for this path.")
    return importer


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


@dataclass(frozen=True)
class JobSpec:
    file_path: Path
    job_index: int
    job_count: int
    start_page: int | None = None
    end_page: int | None = None
    start_spine: int | None = None
    end_spine: int | None = None

    @property
    def is_split(self) -> bool:
        return self.split_kind is not None

    @property
    def split_kind(self) -> str | None:
        if self.start_page is not None or self.end_page is not None:
            return "pdf"
        if self.start_spine is not None or self.end_spine is not None:
            return "epub"
        return None

    @property
    def display_name(self) -> str:
        if not self.is_split:
            return self.file_path.name
        if self.split_kind == "epub":
            start = (self.start_spine or 0) + 1
            end = self.end_spine or start
            return f"{self.file_path.name} [spine {start}-{end}]"
        start = (self.start_page or 0) + 1
        end = self.end_page or start
        return f"{self.file_path.name} [pages {start}-{end}]"


def _resolve_pdf_page_count(path: Path) -> int | None:
    importer = registry.get_importer("pdf")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    page_count = inspection.sheets[0].page_count
    if page_count is None:
        return None
    try:
        return int(page_count)
    except (TypeError, ValueError):
        return None


def _resolve_epub_spine_count(path: Path) -> int | None:
    importer = registry.get_importer("epub")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    spine_count = inspection.sheets[0].spine_count
    if spine_count is None:
        return None
    try:
        return int(spine_count)
    except (TypeError, ValueError):
        return None


def _plan_jobs(
    files: list[Path],
    *,
    workers: int,
    pdf_pages_per_job: int,
    epub_spine_items_per_job: int,
    pdf_split_workers: int,
    epub_split_workers: int,
    epub_extractor: str = "unstructured",
    epub_extractor_by_file: dict[Path, str] | None = None,
) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    for file_path in files:
        selected_epub_extractor = str(
            (epub_extractor_by_file or {}).get(file_path, epub_extractor)
        ).strip().lower()
        if (
            pdf_split_workers > 1
            and file_path.suffix.lower() == ".pdf"
            and pdf_pages_per_job > 0
        ):
            page_count = _resolve_pdf_page_count(file_path)
            if page_count:
                ranges = plan_pdf_page_ranges(
                    page_count,
                    pdf_split_workers,
                    pdf_pages_per_job,
                )
                if len(ranges) > 1:
                    for idx, (start, end) in enumerate(ranges):
                        jobs.append(
                            JobSpec(
                                file_path=file_path,
                                job_index=idx,
                                job_count=len(ranges),
                                start_page=start,
                                end_page=end,
                            )
                        )
                    continue
        if (
            epub_split_workers > 1
            and file_path.suffix.lower() == ".epub"
            and selected_epub_extractor != "markitdown"
            and epub_spine_items_per_job > 0
        ):
            spine_count = _resolve_epub_spine_count(file_path)
            if spine_count:
                ranges = plan_job_ranges(
                    spine_count,
                    epub_split_workers,
                    epub_spine_items_per_job,
                )
                if len(ranges) > 1:
                    for idx, (start, end) in enumerate(ranges):
                        jobs.append(
                            JobSpec(
                                file_path=file_path,
                                job_index=idx,
                                job_count=len(ranges),
                                start_spine=start,
                                end_spine=end,
                            )
                        )
                    continue
        jobs.append(JobSpec(file_path=file_path, job_index=0, job_count=1))
    return jobs


def _merge_raw_artifacts(out: Path, workbook_slug: str, job_results: list[dict[str, Any]]) -> None:
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
    for recipe in result.recipes:
        provenance = recipe.provenance if isinstance(recipe.provenance, dict) else {}
        location = provenance.get("location")
        if isinstance(location, dict):
            _offset_location_fields(location, offset)

    for tip in result.tip_candidates:
        provenance = tip.provenance if isinstance(tip.provenance, dict) else {}
        location = provenance.get("location")
        if isinstance(location, dict):
            _offset_location_fields(location, offset)

    for topic in result.topic_candidates:
        provenance = topic.provenance if isinstance(topic.provenance, dict) else {}
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
            adjusted_block["index"] = index + running_offset
            merged.append(adjusted_block)
            adjusted_count += 1
        job_block_counts[job_index] = adjusted_count
        running_offset += adjusted_count

    merged.sort(key=lambda block: int(_coerce_int(block.get("index")) or 0))
    return merged, job_offsets, job_block_counts


def _merge_split_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    importer_name: str,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    write_markdown: bool = True,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    workbook_slug = slugify_name(file_path.stem)
    merge_stats = TimingStats()
    merge_start = time.monotonic()

    def _report_status(message: str) -> None:
        if status_callback is None:
            return
        try:
            status_callback(message)
        except Exception:
            return

    ordered_jobs = sorted(job_results, key=_job_range_start)
    run_settings = RunSettings.from_dict(run_config, warn_context="split merge run config")
    llm_enabled = run_settings.llm_recipe_pipeline.value != "off"
    knowledge_enabled = run_settings.llm_knowledge_pipeline.value != "off"
    table_extraction_enabled = run_settings.table_extraction.value == "on"
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

    should_write_chunks = False
    for job in ordered_jobs:
        result = job.get("result")
        if result is None:
            continue
        if result.non_recipe_blocks or result.topic_candidates:
            should_write_chunks = True
            break

    phase_labels = [
        "Merging job payloads...",
        "Reassigning recipe IDs...",
    ]
    if llm_enabled:
        phase_labels.append("Running codex-farm recipe pipeline...")
    if table_extraction_enabled:
        phase_labels.append("Extracting tables...")
    phase_labels.append("Building chunks...")
    if knowledge_enabled:
        phase_labels.append("Running codex-farm knowledge harvest...")
    phase_labels.extend(
        [
            "Writing merged outputs...",
            "Writing intermediate drafts...",
            "Writing final drafts...",
            "Writing sections...",
            "Writing tips...",
            "Writing topic candidates...",
            "Writing stage block predictions...",
        ]
    )
    if table_extraction_enabled:
        phase_labels.append("Writing tables...")
    if should_write_chunks:
        phase_labels.append("Writing chunks...")
    phase_labels.extend(
        [
            "Writing report...",
            "Merging raw artifacts...",
            "Merge done",
        ]
    )
    phase_total = len(phase_labels)
    phase_current = 0

    def _report_phase(label: str) -> None:
        nonlocal phase_current
        phase_current += 1
        _report_status(
            format_phase_counter("merge", phase_current, phase_total, label=label)
        )

    _report_phase("Merging job payloads...")
    merged_recipes: list[Any] = []
    merged_tip_candidates: list[Any] = []
    merged_topic_candidates: list[Any] = []
    merged_non_recipe_blocks: list[Any] = []
    warnings: list[str] = []
    epub_backends: set[str] = set()
    standalone_block_total = 0
    standalone_topic_block_total = 0

    for job in ordered_jobs:
        result = job.get("result")
        if result is None:
            continue
        merged_recipes.extend(result.recipes)
        merged_tip_candidates.extend(result.tip_candidates)
        merged_topic_candidates.extend(result.topic_candidates)
        merged_non_recipe_blocks.extend(result.non_recipe_blocks)
        if result.report and result.report.warnings:
            warnings.extend(result.report.warnings)
        if result.report and result.report.errors:
            for error in result.report.errors:
                warnings.append(f"Job {job.get('job_index')}: {error}")
        if result.report and result.report.epub_backend:
            epub_backends.add(str(result.report.epub_backend))
        if result.report:
            standalone_block_total += result.report.total_standalone_blocks
            standalone_topic_block_total += result.report.total_standalone_topic_blocks

    _report_phase("Reassigning recipe IDs...")
    file_hash = compute_file_hash(file_path)
    if merged_full_blocks:
        merged_full_text_path = out / "raw" / importer_name / file_hash / "full_text.json"
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
    sorted_recipes, _ = reassign_recipe_ids(
        merged_recipes,
        merged_tip_candidates,
        file_hash=file_hash,
        importer_name=importer_name,
    )
    tips, _, _ = partition_tip_candidates(merged_tip_candidates)

    report = ConversionReport(
        warnings=warnings,
        importerName=importer_name,
        runConfig=dict(run_config) if run_config is not None else None,
        runConfigHash=run_config_hash,
        runConfigSummary=run_config_summary,
    )
    if importer_name == "epub" and epub_backends:
        report.epub_backend = sorted(epub_backends)[0]
        if len(epub_backends) > 1:
            report.warnings.append(
                "epub_backend_inconsistent_across_split_jobs: "
                + ", ".join(sorted(epub_backends))
            )
    merged_result = ConversionResult(
        recipes=sorted_recipes,
        tips=tips,
        tip_candidates=merged_tip_candidates,
        topic_candidates=merged_topic_candidates,
        non_recipe_blocks=merged_non_recipe_blocks,
        raw_artifacts=[],
        report=report,
        workbook=file_path.stem,
        workbook_path=str(file_path),
    )
    llm_schema_overrides: dict[str, dict[str, Any]] | None = None
    llm_draft_overrides: dict[str, dict[str, Any]] | None = None
    llm_report: dict[str, Any] = {"enabled": False, "pipeline": "off"}

    from cookimport.cli_worker import apply_result_limits
    apply_result_limits(merged_result, limit, limit, limit_label=limit)
    report.total_topic_candidates = len(merged_result.topic_candidates)
    report.total_standalone_blocks = standalone_block_total
    report.total_standalone_topic_blocks = standalone_topic_block_total
    if standalone_block_total:
        standalone_coverage = standalone_topic_block_total / standalone_block_total
        report.standalone_topic_coverage = standalone_coverage
        if standalone_coverage < 0.9 and not any(
            warning.startswith("Standalone topic coverage low:") for warning in warnings
        ):
            report.warnings.append(
                "Standalone topic coverage low: "
                f"{standalone_topic_block_total} of {standalone_block_total} blocks "
                f"represented ({standalone_coverage:.0%})."
            )

    if llm_enabled:
        _report_phase("Running codex-farm recipe pipeline...")
        try:
            llm_apply = run_codex_farm_recipe_pipeline(
                conversion_result=merged_result,
                run_settings=run_settings,
                run_root=out,
                workbook_slug=workbook_slug,
                full_blocks=merged_full_blocks or None,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                warning = (
                    "LLM recipe pipeline failed; falling back to deterministic outputs: "
                    f"{exc}"
                )
                report.warnings.append(warning)
                llm_report = {
                    "enabled": True,
                    "pipeline": run_settings.llm_recipe_pipeline.value,
                    "fallbackApplied": True,
                    "fatalError": str(exc),
                }
            else:
                raise
        else:
            merged_result = llm_apply.updated_conversion_result
            llm_schema_overrides = llm_apply.intermediate_overrides_by_recipe_id
            llm_draft_overrides = llm_apply.final_overrides_by_recipe_id
            llm_report = dict(llm_apply.llm_report)

    report = merged_result.report
    report.llm_codex_farm = llm_report

    parsing_overrides = (
        mapping_config.parsing_overrides if mapping_config and mapping_config.parsing_overrides else None
    )
    extracted_tables: list[ExtractedTable] = []
    if table_extraction_enabled:
        _report_phase("Extracting tables...")
        extracted_tables = extract_and_annotate_tables(
            merged_result.non_recipe_blocks,
            source_hash=file_hash,
        )
    _report_phase("Building chunks...")
    if merged_result.non_recipe_blocks:
        merged_result.chunks = chunks_from_non_recipe_blocks(
            merged_result.non_recipe_blocks,
            overrides=parsing_overrides,
        )
    elif merged_result.topic_candidates:
        merged_result.chunks = chunks_from_topic_candidates(
            merged_result.topic_candidates,
            overrides=parsing_overrides,
        )
    if run_settings.llm_knowledge_pipeline.value != "off":
        _report_phase("Running codex-farm knowledge harvest...")
        try:
            knowledge_apply = run_codex_farm_knowledge_harvest(
                conversion_result=merged_result,
                run_settings=run_settings,
                run_root=out,
                workbook_slug=workbook_slug,
                overrides=parsing_overrides,
                full_blocks=merged_full_blocks or None,
            )
        except CodexFarmRunnerError as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                warning = (
                    "LLM knowledge harvest failed; continuing without knowledge artifacts: "
                    f"{exc}"
                )
                report.warnings.append(warning)
                llm_report["knowledge"] = {
                    "enabled": True,
                    "pipeline": run_settings.llm_knowledge_pipeline.value,
                    "fallbackApplied": True,
                    "fatalError": str(exc),
                }
            else:
                raise
        else:
            llm_report["knowledge"] = dict(knowledge_apply.llm_report)
        report.llm_codex_farm = llm_report

    report.run_timestamp = run_dt.isoformat(timespec="seconds")
    enrich_report_with_stats(report, merged_result, file_path)

    output_stats = OutputStats(out)
    _report_phase("Writing merged outputs...")
    with measure(merge_stats, "writing"):
        intermediate_dir = out / "intermediate drafts" / workbook_slug
        final_dir = out / "final drafts" / workbook_slug
        tips_dir = out / "tips" / workbook_slug

        _report_phase("Writing intermediate drafts...")
        with measure(merge_stats, "write_intermediate_seconds"):
            write_intermediate_outputs(
                merged_result,
                intermediate_dir,
                output_stats=output_stats,
                schemaorg_overrides_by_recipe_id=llm_schema_overrides,
            )
        _report_phase("Writing final drafts...")
        with measure(merge_stats, "write_final_seconds"):
            write_draft_outputs(
                merged_result,
                final_dir,
                output_stats=output_stats,
                draft_overrides_by_recipe_id=llm_draft_overrides,
            )
        _report_phase("Writing sections...")
        with measure(merge_stats, "write_sections_seconds"):
            write_section_outputs(
                out,
                workbook_slug,
                merged_result.recipes,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        _report_phase("Writing tips...")
        with measure(merge_stats, "write_tips_seconds"):
            write_tip_outputs(
                merged_result,
                tips_dir,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        _report_phase("Writing topic candidates...")
        with measure(merge_stats, "write_topic_candidates_seconds"):
            write_topic_candidate_outputs(
                merged_result,
                tips_dir,
                output_stats=output_stats,
                write_markdown=write_markdown,
            )
        if table_extraction_enabled:
            _report_phase("Writing tables...")
            with measure(merge_stats, "write_tables_seconds"):
                write_table_outputs(
                    out,
                    workbook_slug,
                    extracted_tables,
                    source_file=file_path.name,
                    output_stats=output_stats,
                    write_markdown=write_markdown,
                )

        if should_write_chunks:
            _report_phase("Writing chunks...")
            if merged_result.chunks:
                chunks_dir = out / "chunks" / workbook_slug
                with measure(merge_stats, "write_chunks_seconds"):
                    write_chunk_outputs(
                        merged_result.chunks,
                        chunks_dir,
                        output_stats=output_stats,
                        write_markdown=write_markdown,
                    )

        _report_phase("Writing stage block predictions...")
        with measure(merge_stats, "write_stage_block_predictions_seconds"):
            write_stage_block_predictions(
                results=merged_result,
                run_root=out,
                workbook_slug=workbook_slug,
                source_file=str(file_path),
                archive_blocks=merged_full_blocks,
                knowledge_snippets_path=out / "knowledge" / workbook_slug / "snippets.jsonl",
                output_stats=output_stats,
            )

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

    if output_stats.file_counts:
        report.output_stats = output_stats.to_report()
    report.timing = merge_stats.to_dict()
    _report_phase("Writing report...")
    write_report(report, out, file_path.stem)

    _report_phase("Merging raw artifacts...")
    _merge_raw_artifacts(out, workbook_slug, job_results)
    _report_phase("Merge done")

    return {
        "file": file_path.name,
        "status": "success",
        "recipes": len(merged_result.recipes),
        "tips": len(merged_result.tips),
        "duration": merge_stats.total_seconds,
    }


def _merge_pdf_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    write_markdown: bool = True,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return _merge_split_jobs(
        file_path,
        job_results,
        out,
        mapping_config,
        limit,
        run_dt,
        importer_name="pdf",
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        write_markdown=write_markdown,
        status_callback=status_callback,
    )


def _merge_epub_jobs(
    file_path: Path,
    job_results: list[dict[str, Any]],
    out: Path,
    mapping_config: MappingConfig | None,
    limit: int | None,
    run_dt: dt.datetime,
    run_config: dict[str, Any] | None = None,
    run_config_hash: str | None = None,
    run_config_summary: str | None = None,
    write_markdown: bool = True,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return _merge_split_jobs(
        file_path,
        job_results,
        out,
        mapping_config,
        limit,
        run_dt,
        importer_name="epub",
        run_config=run_config,
        run_config_hash=run_config_hash,
        run_config_summary=run_config_summary,
        write_markdown=write_markdown,
        status_callback=status_callback,
    )


@app.command()
def stage(
    path: Path = typer.Argument(..., help="File or folder containing source files."),
    out: Path = typer.Option(DEFAULT_OUTPUT, "--out", help="Output folder."),
    mapping: Path | None = typer.Option(None, "--mapping", help="Mapping file path."),
    overrides: Path | None = typer.Option(
        None,
        "--overrides",
        help="Parsing overrides file path.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        min=1,
        help="Limit output to the first N recipes and N tips per file.",
    ),
    ocr_device: str = typer.Option(
        "auto",
        "--ocr-device",
        help="OCR device to use (auto, cpu, cuda, mps).",
    ),
    ocr_batch_size: int = typer.Option(
        1,
        "--ocr-batch-size",
        min=1,
        help="Number of pages to process per OCR model call.",
    ),
    pdf_pages_per_job: int = typer.Option(
        50,
        "--pdf-pages-per-job",
        min=1,
        help="Target page count per PDF job when splitting large PDFs.",
    ),
    epub_spine_items_per_job: int = typer.Option(
        10,
        "--epub-spine-items-per-job",
        min=1,
        help="Target spine items per EPUB job when splitting large EPUBs.",
    ),
    warm_models: bool = typer.Option(
        False,
        "--warm-models",
        help="Proactively load heavy models before processing.",
    ),
    workers: int = typer.Option(
        7,
        "--workers",
        "-w",
        min=1,
        help="Number of parallel worker processes.",
    ),
    pdf_split_workers: int = typer.Option(
        7,
        "--pdf-split-workers",
        min=1,
        help="Max workers used to split a single PDF into jobs.",
    ),
    epub_split_workers: int = typer.Option(
        7,
        "--epub-split-workers",
        min=1,
        help="Max workers used to split a single EPUB into jobs.",
    ),
    write_markdown: bool = typer.Option(
        True,
        "--write-markdown/--no-write-markdown",
        help="Write markdown sidecar artifacts (sections/tips/topic/chunks/tables).",
    ),
    epub_extractor: str = typer.Option(
        "unstructured",
        "--epub-extractor",
        help=(
            "EPUB extraction engine: unstructured (semantic), beautifulsoup "
            "(BeautifulSoup), markdown (HTML->Markdown), or markitdown (whole-book "
            "EPUB->markdown mode)."
        ),
    ),
    epub_unstructured_html_parser_version: str = typer.Option(
        "v1",
        "--epub-unstructured-html-parser-version",
        help="Unstructured HTML parser version for EPUB extraction: v1 or v2.",
    ),
    epub_unstructured_skip_headers_footers: bool = typer.Option(
        False,
        "--epub-unstructured-skip-headers-footers/--no-epub-unstructured-skip-headers-footers",
        help="Enable Unstructured skip_headers_and_footers for EPUB HTML partitioning.",
    ),
    epub_unstructured_preprocess_mode: str = typer.Option(
        "br_split_v1",
        "--epub-unstructured-preprocess-mode",
        help="EPUB HTML preprocess mode before Unstructured partitioning: none, br_split_v1, semantic_v1.",
    ),
    table_extraction: str = typer.Option(
        "off",
        "--table-extraction",
        help="Deterministic table extraction mode: off or on.",
    ),
    llm_recipe_pipeline: str = typer.Option(
        "off",
        "--llm-recipe-pipeline",
        help=(
            "Recipe codex-farm parsing correction pipeline. "
            "Policy-locked OFF for now; must remain off until benchmark quality improves."
        ),
    ),
    llm_knowledge_pipeline: str = typer.Option(
        "off",
        "--llm-knowledge-pipeline",
        help="Optional knowledge LLM pipeline: off or codex-farm-knowledge-v1.",
    ),
    llm_tags_pipeline: str = typer.Option(
        "off",
        "--llm-tags-pipeline",
        help="Optional tags LLM pipeline: off or codex-farm-tags-v1.",
    ),
    codex_farm_cmd: str = typer.Option(
        "codex-farm",
        "--codex-farm-cmd",
        help="Executable used for codex-farm calls when LLM recipe pipeline is enabled.",
    ),
    codex_farm_root: Path | None = typer.Option(
        None,
        "--codex-farm-root",
        help="Optional codex-farm pipeline-pack root. Defaults to <repo_root>/llm_pipelines.",
    ),
    codex_farm_workspace_root: Path | None = typer.Option(
        None,
        "--codex-farm-workspace-root",
        help=(
            "Optional workspace root passed to codex-farm. "
            "When omitted, codex-farm pipeline codex_cd_mode decides."
        ),
    ),
    codex_farm_pipeline_pass1: str = typer.Option(
        "recipe.chunking.v1",
        "--codex-farm-pipeline-pass1",
        help="Pass-1 codex-farm pipeline id (recipe boundary refinement).",
    ),
    codex_farm_pipeline_pass2: str = typer.Option(
        "recipe.schemaorg.v1",
        "--codex-farm-pipeline-pass2",
        help="Pass-2 codex-farm pipeline id (schema.org extraction).",
    ),
    codex_farm_pipeline_pass3: str = typer.Option(
        "recipe.final.v1",
        "--codex-farm-pipeline-pass3",
        help="Pass-3 codex-farm pipeline id (final draft generation).",
    ),
    codex_farm_pipeline_pass4_knowledge: str = typer.Option(
        "recipe.knowledge.v1",
        "--codex-farm-pipeline-pass4-knowledge",
        help="Pass-4 codex-farm pipeline id (non-recipe knowledge harvesting).",
    ),
    codex_farm_pipeline_pass5_tags: str = typer.Option(
        "recipe.tags.v1",
        "--codex-farm-pipeline-pass5-tags",
        help="Pass-5 codex-farm pipeline id (tag suggestions).",
    ),
    codex_farm_context_blocks: int = typer.Option(
        30,
        "--codex-farm-context-blocks",
        min=0,
        help="Blocks before/after each recipe candidate included in pass-1 codex-farm bundles.",
    ),
    codex_farm_knowledge_context_blocks: int = typer.Option(
        12,
        "--codex-farm-knowledge-context-blocks",
        min=0,
        help="Blocks before/after each non-recipe chunk included as context in pass-4 bundles.",
    ),
    tag_catalog_json: Path = typer.Option(
        Path("data/tagging/tag_catalog.json"),
        "--tag-catalog-json",
        help="Tag catalog snapshot used when --llm-tags-pipeline is enabled.",
    ),
    codex_farm_failure_mode: str = typer.Option(
        "fail",
        "--codex-farm-failure-mode",
        help="Behavior when codex-farm setup/invocation fails: fail or fallback.",
    ),
) -> Path:
    """Stage recipes from a source file or folder.

    Outputs are organized as:
      {out}/{timestamp}/intermediate drafts/{filename}/  - schema.org Recipe JSON
      {out}/{timestamp}/final drafts/{filename}/         - cookbook3 format
      {out}/{timestamp}/tips/{filename}/                 - Tip/knowledge snippets
      {out}/{timestamp}/<workbook>.excel_import_report.json - Conversion report
    """
    out = _unwrap_typer_option_default(out)
    mapping = _unwrap_typer_option_default(mapping)
    overrides = _unwrap_typer_option_default(overrides)
    limit = _unwrap_typer_option_default(limit)
    ocr_device = _unwrap_typer_option_default(ocr_device)
    ocr_batch_size = _unwrap_typer_option_default(ocr_batch_size)
    pdf_pages_per_job = _unwrap_typer_option_default(pdf_pages_per_job)
    epub_spine_items_per_job = _unwrap_typer_option_default(epub_spine_items_per_job)
    warm_models = _unwrap_typer_option_default(warm_models)
    workers = _unwrap_typer_option_default(workers)
    pdf_split_workers = _unwrap_typer_option_default(pdf_split_workers)
    epub_split_workers = _unwrap_typer_option_default(epub_split_workers)
    write_markdown = _unwrap_typer_option_default(write_markdown)
    epub_extractor = _unwrap_typer_option_default(epub_extractor)
    epub_unstructured_html_parser_version = _unwrap_typer_option_default(
        epub_unstructured_html_parser_version
    )
    epub_unstructured_skip_headers_footers = _unwrap_typer_option_default(
        epub_unstructured_skip_headers_footers
    )
    epub_unstructured_preprocess_mode = _unwrap_typer_option_default(
        epub_unstructured_preprocess_mode
    )
    table_extraction = _unwrap_typer_option_default(table_extraction)
    llm_recipe_pipeline = _unwrap_typer_option_default(llm_recipe_pipeline)
    llm_knowledge_pipeline = _unwrap_typer_option_default(llm_knowledge_pipeline)
    llm_tags_pipeline = _unwrap_typer_option_default(llm_tags_pipeline)
    codex_farm_cmd = _unwrap_typer_option_default(codex_farm_cmd)
    codex_farm_root = _unwrap_typer_option_default(codex_farm_root)
    codex_farm_workspace_root = _unwrap_typer_option_default(codex_farm_workspace_root)
    codex_farm_pipeline_pass1 = _unwrap_typer_option_default(codex_farm_pipeline_pass1)
    codex_farm_pipeline_pass2 = _unwrap_typer_option_default(codex_farm_pipeline_pass2)
    codex_farm_pipeline_pass3 = _unwrap_typer_option_default(codex_farm_pipeline_pass3)
    codex_farm_pipeline_pass4_knowledge = _unwrap_typer_option_default(
        codex_farm_pipeline_pass4_knowledge
    )
    codex_farm_pipeline_pass5_tags = _unwrap_typer_option_default(
        codex_farm_pipeline_pass5_tags
    )
    codex_farm_context_blocks = _unwrap_typer_option_default(codex_farm_context_blocks)
    codex_farm_knowledge_context_blocks = _unwrap_typer_option_default(
        codex_farm_knowledge_context_blocks
    )
    tag_catalog_json = _unwrap_typer_option_default(tag_catalog_json)
    codex_farm_failure_mode = _unwrap_typer_option_default(codex_farm_failure_mode)

    selected_epub_extractor = _normalize_epub_extractor(epub_extractor)
    selected_html_parser_version = _normalize_unstructured_html_parser_version(
        epub_unstructured_html_parser_version
    )
    selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
        epub_unstructured_preprocess_mode
    )
    selected_skip_headers_footers = bool(epub_unstructured_skip_headers_footers)
    selected_ocr_device = _normalize_ocr_device(ocr_device)
    selected_table_extraction = _normalize_table_extraction(table_extraction)
    selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
    selected_llm_knowledge_pipeline = _normalize_llm_knowledge_pipeline(llm_knowledge_pipeline)
    selected_llm_tags_pipeline = _normalize_llm_tags_pipeline(llm_tags_pipeline)
    selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
        codex_farm_failure_mode
    )
    selected_codex_farm_pipeline_pass1 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass1,
        option="--codex-farm-pipeline-pass1",
    )
    selected_codex_farm_pipeline_pass2 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass2,
        option="--codex-farm-pipeline-pass2",
    )
    selected_codex_farm_pipeline_pass3 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass3,
        option="--codex-farm-pipeline-pass3",
    )
    selected_codex_farm_pipeline_pass4_knowledge = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass4_knowledge,
        option="--codex-farm-pipeline-pass4-knowledge",
    )
    selected_codex_farm_pipeline_pass5_tags = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass5_tags,
        option="--codex-farm-pipeline-pass5-tags",
    )
    selected_tag_catalog_json = Path(tag_catalog_json).expanduser()

    # Apply EPUB unstructured runtime options for this run.
    # Extractor choice is passed explicitly into worker calls.
    _set_epub_unstructured_env(
        html_parser_version=selected_html_parser_version,
        skip_headers_footers=selected_skip_headers_footers,
        preprocess_mode=selected_preprocess_mode,
    )

    if not path.exists():
        _fail(f"Path not found: {path}")
    if mapping is not None and not mapping.exists():
        _fail(f"Mapping file not found: {mapping}")
    if overrides is not None and not overrides.exists():
        _fail(f"Overrides file not found: {overrides}")
    if (
        selected_llm_tags_pipeline != "off"
        and not selected_tag_catalog_json.exists()
    ):
        _fail(
            "Tag catalog JSON not found for --llm-tags-pipeline: "
            f"{selected_tag_catalog_json}"
        )

    if warm_models:
        with console.status("[bold cyan]Warming models...[/bold cyan]", spinner="dots"):
            _warm_all_models(ocr_device=selected_ocr_device)

    # Create timestamped output folder for this run
    run_dt = dt.datetime.now()
    timestamp = run_dt.strftime("%Y-%m-%d_%H.%M.%S")
    output_root = out
    out = output_root / timestamp
    out.mkdir(parents=True, exist_ok=True)

    files_to_process = list(_iter_files(path))

    if not files_to_process:
        typer.secho("No files found to process.", fg=typer.colors.YELLOW)
        return out

    mapping_override: MappingConfig | None = None
    if mapping is not None:
        mapping_override = load_mapping_config(mapping)
    
    # Resolve mapping config once for parallel runs if provided
    # or use it as a template for overrides
    base_mapping = mapping_override or MappingConfig()
    base_mapping.ocr_device = selected_ocr_device
    base_mapping.ocr_batch_size = ocr_batch_size
    if overrides is not None:
        base_mapping.parsing_overrides = load_parsing_overrides(overrides)

    imported = 0
    errors: list[str] = []
    effective_epub_extractors: dict[Path, str] = {
        file_path: selected_epub_extractor
        for file_path in files_to_process
        if file_path.suffix.lower() == ".epub"
    }

    all_epub = all(f.suffix.lower() == ".epub" for f in files_to_process)
    run_settings = build_run_settings(
        workers=workers,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        epub_extractor=selected_epub_extractor,
        epub_unstructured_html_parser_version=selected_html_parser_version,
        epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
        epub_unstructured_preprocess_mode=selected_preprocess_mode,
        ocr_device=selected_ocr_device,
        ocr_batch_size=ocr_batch_size,
        warm_models=warm_models,
        table_extraction=selected_table_extraction,
        llm_recipe_pipeline=selected_llm_recipe_pipeline,
        llm_knowledge_pipeline=selected_llm_knowledge_pipeline,
        llm_tags_pipeline=selected_llm_tags_pipeline,
        codex_farm_cmd=codex_farm_cmd,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        codex_farm_pipeline_pass1=selected_codex_farm_pipeline_pass1,
        codex_farm_pipeline_pass2=selected_codex_farm_pipeline_pass2,
        codex_farm_pipeline_pass3=selected_codex_farm_pipeline_pass3,
        codex_farm_pipeline_pass4_knowledge=selected_codex_farm_pipeline_pass4_knowledge,
        codex_farm_pipeline_pass5_tags=selected_codex_farm_pipeline_pass5_tags,
        codex_farm_context_blocks=codex_farm_context_blocks,
        codex_farm_knowledge_context_blocks=codex_farm_knowledge_context_blocks,
        tag_catalog_json=selected_tag_catalog_json,
        codex_farm_failure_mode=selected_codex_farm_failure_mode,
        mapping_path=mapping,
        overrides_path=overrides,
        all_epub=all_epub,
        effective_workers=compute_effective_workers(
            workers=workers,
            epub_split_workers=epub_split_workers,
            epub_extractor=selected_epub_extractor,
            all_epub=all_epub,
        ),
    )
    effective_workers = run_settings.effective_workers or workers
    run_config = run_settings.to_run_config_dict()
    run_config["epub_extractor_requested"] = selected_epub_extractor
    run_config["epub_extractor_effective"] = selected_epub_extractor
    run_config["write_markdown"] = bool(write_markdown)

    def _stable_run_config_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _render_run_config_summary(payload: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in sorted(payload):
            value = payload[key]
            rendered = "true" if value is True else "false" if value is False else str(value)
            parts.append(f"{key}={rendered}")
        return " | ".join(parts)

    def _run_config_for_file(file_path: Path) -> dict[str, Any]:
        if file_path.suffix.lower() != ".epub":
            return dict(run_config)
        payload = dict(run_config)
        payload["epub_extractor_effective"] = effective_epub_extractors.get(
            file_path,
            selected_epub_extractor,
        )
        return payload

    run_config_hash = _stable_run_config_hash(run_config)
    run_config_summary = _render_run_config_summary(run_config)

    from concurrent.futures import ProcessPoolExecutor, as_completed
    from cookimport.cli_worker import stage_one_file, stage_pdf_job, stage_epub_job
    progress_queue = None
    try:
        manager = multiprocessing.Manager()
        progress_queue = manager.Queue()
    except Exception:
        progress_queue = None
    
    # UI State
    worker_status: Dict[str, Dict[str, Any]] = {}
    worker_lock = threading.Lock()
    
    job_specs = _plan_jobs(
        files_to_process,
        workers=workers,
        pdf_pages_per_job=pdf_pages_per_job,
        epub_spine_items_per_job=epub_spine_items_per_job,
        pdf_split_workers=pdf_split_workers,
        epub_split_workers=epub_split_workers,
        epub_extractor=selected_epub_extractor,
        epub_extractor_by_file=effective_epub_extractors,
    )
    total_jobs = len(job_specs)
    expected_jobs: dict[Path, int] = {}
    for job in job_specs:
        if job.is_split and job.file_path not in expected_jobs:
            expected_jobs[job.file_path] = job.job_count

    progress_bar = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TextColumn("{task.completed}/{task.total}"),
    )
    overall_task = progress_bar.add_task("Total Progress", total=total_jobs)

    worker_render_cache: Text | None = None
    worker_render_last = 0.0

    def _set_worker_status(
        worker_label: str,
        filename: str,
        status: str,
        *,
        updated_at: float | None = None,
    ) -> None:
        nonlocal worker_render_cache, worker_render_last
        if updated_at is None:
            updated_at = time.time()
        with worker_lock:
            worker_status[str(worker_label)] = {
                "file": str(filename),
                "status": str(status),
                "updated_at": float(updated_at),
            }
        worker_render_cache = None
        worker_render_last = 0.0

    def _format_worker_lines() -> Text:
        nonlocal worker_render_cache, worker_render_last
        now = time.time()
        if worker_render_cache is not None and (now - worker_render_last) < 5:
            return worker_render_cache

        with worker_lock:
            items = list(worker_status.items())

        if not items:
            worker_render_cache = Text("Waiting for worker updates...")
            worker_render_last = now
            return worker_render_cache

        task = progress_bar.tasks[0] if progress_bar.tasks else None
        run_complete = bool(task and task.completed >= task.total)

        lines = []
        for worker_label, entry in sorted(items, key=lambda item: item[0]):
            age_seconds = max(0, int(now - entry["updated_at"]))
            age_label = "just now" if age_seconds < 1 else f"{age_seconds}s ago"
            status = entry["status"]
            if not run_complete and status in {"Done", "skipped"}:
                status = "Idle"
            lines.append(
                f"{worker_label}: {entry['file']} - {status} ({age_label})"
            )
        worker_render_cache = Text("\n".join(lines))
        worker_render_last = now
        return worker_render_cache

    class WorkerDashboard:
        def __rich__(self) -> Group:
            return Group(
                Panel(progress_bar),
                Panel(_format_worker_lines(), title="Workers (updated every 5s)"),
            )

    # Background thread to consume queue
    stop_event = threading.Event()
    queue_thread = None
    if progress_queue is not None:
        def process_queue():
            while not stop_event.is_set():
                try:
                    # Non-blocking get with short timeout
                    try:
                        record = progress_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    
                    if isinstance(record, (tuple, list)) and len(record) == 4:
                        worker_label, filename, status, updated_at = record
                    elif isinstance(record, (tuple, list)) and len(record) == 2:
                        filename, status = record
                        worker_label = "worker"
                        updated_at = time.time()
                    else:
                        continue

                    _set_worker_status(
                        str(worker_label),
                        str(filename),
                        str(status),
                        updated_at=float(updated_at),
                    )
                except Exception:
                    pass

        queue_thread = threading.Thread(target=process_queue, daemon=True)
        queue_thread.start()

    typer.secho(
        f"Processing {len(files_to_process)} file(s) as {total_jobs} job(s) using {effective_workers} workers...",
        fg=typer.colors.CYAN,
    )

    job_results_by_file: dict[Path, list[dict[str, Any]]] = defaultdict(list)

    def _run_config_hash_for_file(file_path: Path) -> str:
        return _stable_run_config_hash(_run_config_for_file(file_path))

    def _run_config_summary_for_file(file_path: Path) -> str:
        return _render_run_config_summary(_run_config_for_file(file_path))

    def handle_job_result(job: JobSpec, res: dict[str, Any], live: Live) -> None:
        nonlocal imported
        job_run_config = _run_config_for_file(job.file_path)
        job_run_config_hash = _run_config_hash_for_file(job.file_path)
        job_run_config_summary = _run_config_summary_for_file(job.file_path)

        if job.is_split:
            job_results_by_file[job.file_path].append(res)
            if res.get("status") == "error":
                live.console.print(
                    f"[red]✘ Error {job.file_path.name} job {job.job_index}: {res.get('reason')}[/red]"
                )

            expected_count = expected_jobs.get(job.file_path, job.job_count)
            if len(job_results_by_file[job.file_path]) == expected_count:
                results = job_results_by_file.pop(job.file_path)
                failed = [r for r in results if r.get("status") != "success"]
                if failed:
                    reasons = [
                        f"job {r.get('job_index')}: {r.get('reason')}"
                        for r in failed
                    ]
                    if not reasons:
                        reasons = ["job failure"]
                    message = "; ".join(reasons)
                    errors.append(f"{job.file_path.name}: {message}")
                    _set_worker_status(
                        "MainProcess",
                        job.file_path.name,
                        "Merge skipped (job errors)",
                    )
                    live.console.print(
                        f"[red]✘ Error {job.file_path.name}: {message}[/red]"
                    )
                    _write_error_report(
                        out,
                        job.file_path,
                        run_dt,
                        reasons,
                        importer_name=job.split_kind,
                        run_config=job_run_config,
                        run_config_hash=job_run_config_hash,
                        run_config_summary=job_run_config_summary,
                    )
                else:
                    _set_worker_status(
                        "MainProcess",
                        job.file_path.name,
                        f"Merging {expected_count} job(s)...",
                    )
                    live.console.print(
                        f"Merging {expected_count} jobs for {job.file_path.name}..."
                    )
                    try:
                        def _main_merge_status(message: str) -> None:
                            _set_worker_status(
                                "MainProcess",
                                job.file_path.name,
                                message,
                            )

                        if job.split_kind == "epub":
                            merged = _merge_epub_jobs(
                                job.file_path,
                                results,
                                out,
                                base_mapping,
                                limit,
                                run_dt,
                                job_run_config,
                                job_run_config_hash,
                                job_run_config_summary,
                                write_markdown=write_markdown,
                                status_callback=_main_merge_status,
                            )
                        else:
                            merged = _merge_pdf_jobs(
                                job.file_path,
                                results,
                                out,
                                base_mapping,
                                limit,
                                run_dt,
                                job_run_config,
                                job_run_config_hash,
                                job_run_config_summary,
                                write_markdown=write_markdown,
                                status_callback=_main_merge_status,
                            )
                        imported += 1
                        _set_worker_status(
                            "MainProcess",
                            job.file_path.name,
                            f"Merge done ({merged['duration']:.2f}s)",
                        )
                        live.console.print(
                            f"[green]✔ {merged['file']}: {merged['recipes']} recipes, "
                            f"{merged['tips']} tips (merge {merged['duration']:.2f}s)[/green]"
                        )
                    except Exception as exc:
                        errors.append(f"{job.file_path.name}: {exc}")
                        _set_worker_status(
                            "MainProcess",
                            job.file_path.name,
                            "Merge error",
                        )
                        live.console.print(
                            f"[red]✘ Error {job.file_path.name}: {exc}[/red]"
                        )
                        _write_error_report(
                            out,
                            job.file_path,
                            run_dt,
                            [str(exc)],
                            importer_name=job.split_kind,
                            run_config=job_run_config,
                            run_config_hash=job_run_config_hash,
                            run_config_summary=job_run_config_summary,
                        )
        else:
            if res["status"] == "success":
                imported += 1
                live.console.print(
                    f"[green]✔ {res['file']}: {res['recipes']} recipes, {res['tips']} tips ({res['duration']:.2f}s)[/green]"
                )
            elif res["status"] == "skipped":
                live.console.print(
                    f"[yellow]⚠ Skipping {res['file']}: {res['reason']}[/yellow]"
                )
            else:
                errors.append(f"{res['file']}: {res['reason']}")
                live.console.print(
                    f"[red]✘ Error {res['file']}: {res['reason']}[/red]"
                )

    dashboard = WorkerDashboard()
    with Live(dashboard, refresh_per_second=10) as live:
        try:
            with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                futures: dict[Any, JobSpec] = {}
                for job in job_specs:
                    job_run_config = _run_config_for_file(job.file_path)
                    job_run_config_hash = _run_config_hash_for_file(job.file_path)
                    job_run_config_summary = _run_config_summary_for_file(job.file_path)
                    job_epub_extractor = effective_epub_extractors.get(job.file_path)
                    if job.is_split:
                        if job.split_kind == "epub":
                            futures[
                                executor.submit(
                                    stage_epub_job,
                                    job.file_path,
                                    out,
                                    base_mapping,
                                    run_dt,
                                    job.start_spine,
                                    job.end_spine,
                                    job.job_index,
                                    job.job_count,
                                    progress_queue,
                                    job.display_name,
                                    job_epub_extractor,
                                    job_run_config,
                                    job_run_config_hash,
                                    job_run_config_summary,
                                )
                            ] = job
                        else:
                            futures[
                                executor.submit(
                                    stage_pdf_job,
                                    job.file_path,
                                    out,
                                    base_mapping,
                                    run_dt,
                                    job.start_page,
                                    job.end_page,
                                    job.job_index,
                                    job.job_count,
                                    progress_queue,
                                    job.display_name,
                                    job_run_config,
                                    job_run_config_hash,
                                    job_run_config_summary,
                                )
                            ] = job
                    else:
                        futures[
                            executor.submit(
                                stage_one_file,
                                job.file_path,
                                out,
                                base_mapping,
                                limit,
                                run_dt,
                                progress_queue,
                                job.display_name,
                                job_epub_extractor,
                                job_run_config,
                                job_run_config_hash,
                                job_run_config_summary,
                                write_markdown,
                            )
                        ] = job

                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        res = future.result()
                    except Exception as exc:
                        res = {
                            "file": job.file_path.name,
                            "status": "error",
                            "reason": str(exc),
                            "job_index": job.job_index,
                            "job_count": job.job_count,
                            "start_page": job.start_page,
                            "end_page": job.end_page,
                            "start_spine": job.start_spine,
                            "end_spine": job.end_spine,
                        }

                    progress_bar.update(overall_task, advance=1)
                    handle_job_result(job, res, live)
        except PermissionError:
            live.console.print(
                "[yellow]⚠ Multiprocessing unavailable; running jobs serially.[/yellow]"
            )
            for job in job_specs:
                job_run_config = _run_config_for_file(job.file_path)
                job_run_config_hash = _run_config_hash_for_file(job.file_path)
                job_run_config_summary = _run_config_summary_for_file(job.file_path)
                job_epub_extractor = effective_epub_extractors.get(job.file_path)
                if job.is_split:
                    if job.split_kind == "epub":
                        res = stage_epub_job(
                            job.file_path,
                            out,
                            base_mapping,
                            run_dt,
                            job.start_spine,
                            job.end_spine,
                            job.job_index,
                            job.job_count,
                            progress_queue,
                            job.display_name,
                            job_epub_extractor,
                            job_run_config,
                            job_run_config_hash,
                            job_run_config_summary,
                        )
                    else:
                        res = stage_pdf_job(
                            job.file_path,
                            out,
                            base_mapping,
                            run_dt,
                            job.start_page,
                            job.end_page,
                            job.job_index,
                            job.job_count,
                            progress_queue,
                            job.display_name,
                            job_run_config,
                            job_run_config_hash,
                            job_run_config_summary,
                        )
                else:
                    res = stage_one_file(
                        job.file_path,
                        out,
                        base_mapping,
                        limit,
                        run_dt,
                        progress_queue,
                        job.display_name,
                        job_epub_extractor,
                        job_run_config,
                        job_run_config_hash,
                        job_run_config_summary,
                        write_markdown,
                    )
                progress_bar.update(overall_task, advance=1)
                handle_job_result(job, res, live)

    stop_event.set()
    if queue_thread is not None:
        queue_thread.join()

    typer.secho(f"\nStaged {imported} file(s).", fg=typer.colors.GREEN)
    if errors:
        typer.secho("Errors encountered:", fg=typer.colors.YELLOW)
        for message in errors:
            typer.secho(f"- {message}", fg=typer.colors.YELLOW)

    try:
        from cookimport.analytics.perf_report import (
            append_history_csv,
            build_perf_summary,
            format_summary_line,
            history_path,
        )

        summary = build_perf_summary(out)
        if summary.rows:
            typer.secho("\nPerformance summary:", fg=typer.colors.CYAN)
            typer.echo(f"Run: {out}")
            for row in summary.rows:
                typer.echo(format_summary_line(row))

            if summary.total_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.total_outliers)
                typer.secho(
                    f"Outliers (total time > 3x median): {outlier_names}",
                    fg=typer.colors.YELLOW,
                )
            if summary.parsing_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.parsing_outliers)
                typer.secho(
                    f"Outliers (parsing time > 3x median): {outlier_names}",
                    fg=typer.colors.YELLOW,
                )
            if summary.writing_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.writing_outliers)
                typer.secho(
                    f"Outliers (writing time > 3x median): {outlier_names}",
                    fg=typer.colors.YELLOW,
                )
            if summary.per_unit_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.per_unit_outliers)
                typer.secho(
                    f"Outliers (per-unit > 3x median): {outlier_names}",
                    fg=typer.colors.YELLOW,
                )
            if summary.per_recipe_outliers:
                outlier_names = ", ".join(row.file_name for row in summary.per_recipe_outliers)
                typer.secho(
                    "Outliers (per-recipe > 3x median, recipe-heavy only): " + outlier_names,
                    fg=typer.colors.YELLOW,
                )
            if summary.knowledge_heavy:
                heavy_names = ", ".join(row.file_name for row in summary.knowledge_heavy)
                typer.secho(
                    "Knowledge-heavy runs (topic candidates dominate): " + heavy_names,
                    fg=typer.colors.CYAN,
                )

            csv_history_path = history_path(output_root)
            append_history_csv(summary.rows, csv_history_path)
            _refresh_dashboard_after_history_write(
                csv_path=csv_history_path,
                output_root=output_root,
                reason="stage history append",
            )
    except Exception as exc:
        logger.warning("Performance summary skipped: %s", exc)

    _write_knowledge_index_best_effort(out)

    if run_settings.llm_tags_pipeline.value != "off":
        typer.secho("\nRunning codex-farm tags pass...", fg=typer.colors.CYAN)
        try:
            tags_result = run_stage_tagging_pass(
                run_root=out,
                run_settings=run_settings,
                status_callback=lambda message: typer.secho(
                    message, fg=typer.colors.BRIGHT_BLACK
                ),
            )
        except (CodexFarmRunnerError, FileNotFoundError, ValueError) as exc:
            if run_settings.codex_farm_failure_mode.value == "fallback":
                warning = (
                    "LLM tags pass failed; continuing without tag artifacts: "
                    f"{exc}"
                )
                typer.secho(warning, fg=typer.colors.YELLOW)
                logger.warning(warning)
            else:
                raise
        else:
            if tags_result.tags_index_path is not None:
                typer.secho(
                    f"Tags pass complete: {tags_result.tags_index_path}",
                    fg=typer.colors.GREEN,
                )

    _write_stage_run_manifest(
        run_root=out,
        output_root=output_root,
        requested_path=path,
        run_dt=run_dt,
        run_config=run_config,
    )

    return out

    typer.secho(f"\nStaged {imported} file(s).", fg=typer.colors.GREEN)
    if errors:
        typer.secho("Errors encountered:", fg=typer.colors.YELLOW)
        for message in errors:
            typer.secho(f"- {message}", fg=typer.colors.YELLOW)

    return out


@app.command("perf-report")
def perf_report(
    run_dir: Path | None = typer.Option(
        None,
        "--run-dir",
        help="Run folder to summarize (defaults to latest under --out-dir).",
    ),
    out_dir: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--out-dir",
        help="Root output folder used to locate runs and history CSV.",
    ),
    write_csv: bool = typer.Option(
        True,
        "--write-csv/--no-csv",
        help="Append results to the performance history CSV.",
    ),
) -> None:
    """Summarize per-file performance metrics for a run."""
    from cookimport.analytics.perf_report import (
        append_history_csv,
        build_perf_summary,
        format_summary_line,
        history_path,
        resolve_run_dir,
    )

    resolved = resolve_run_dir(run_dir, out_dir)
    if resolved is None or not resolved.exists():
        _fail(f"No run folder found under {out_dir}.")

    summary = build_perf_summary(resolved)
    if not summary.rows:
        _fail(f"No conversion reports found in {resolved}.")

    typer.secho(f"Performance summary for {resolved}", fg=typer.colors.CYAN)
    for row in summary.rows:
        typer.echo(format_summary_line(row))

    if summary.total_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.total_outliers)
        typer.secho(
            f"Outliers (total time > 3x median): {outlier_names}",
            fg=typer.colors.YELLOW,
        )
    if summary.parsing_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.parsing_outliers)
        typer.secho(
            f"Outliers (parsing time > 3x median): {outlier_names}",
            fg=typer.colors.YELLOW,
        )
    if summary.writing_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.writing_outliers)
        typer.secho(
            f"Outliers (writing time > 3x median): {outlier_names}",
            fg=typer.colors.YELLOW,
        )
    if summary.per_unit_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.per_unit_outliers)
        typer.secho(
            f"Outliers (per-unit > 3x median): {outlier_names}",
            fg=typer.colors.YELLOW,
        )
    if summary.per_recipe_outliers:
        outlier_names = ", ".join(row.file_name for row in summary.per_recipe_outliers)
        typer.secho(
            "Outliers (per-recipe > 3x median, recipe-heavy only): " + outlier_names,
            fg=typer.colors.YELLOW,
        )
    if summary.knowledge_heavy:
        heavy_names = ", ".join(row.file_name for row in summary.knowledge_heavy)
        typer.secho(
            "Knowledge-heavy runs (topic candidates dominate): " + heavy_names,
            fg=typer.colors.CYAN,
        )

    if write_csv:
        csv_history_path = history_path(out_dir)
        append_history_csv(summary.rows, csv_history_path)
        _refresh_dashboard_after_history_write(
            csv_path=csv_history_path,
            output_root=out_dir,
            reason="perf-report history append",
        )


@app.command("stats-dashboard")
def stats_dashboard(
    output_root: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--output-root",
        help="Root output folder for staged imports.",
    ),
    golden_root: Path = typer.Option(
        DEFAULT_GOLDEN,
        "--golden-root",
        help="Root folder for golden-set / benchmark data.",
    ),
    out_dir: Path = typer.Option(
        DEFAULT_HISTORY / "dashboard",
        "--out-dir",
        help="Directory where the dashboard will be written.",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open the generated dashboard in the default browser.",
    ),
    since_days: int | None = typer.Option(
        None,
        "--since-days",
        help="Only include runs from the last N days.",
    ),
    scan_reports: bool = typer.Option(
        False,
        "--scan-reports",
        help="Force scanning individual *.excel_import_report.json files.",
    ),
) -> None:
    """Generate a static lifetime-stats dashboard (HTML)."""
    from cookimport.analytics.dashboard_collect import collect_dashboard_data
    from cookimport.analytics.dashboard_render import render_dashboard

    data = collect_dashboard_data(
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        scan_reports=scan_reports,
    )

    html_path = render_dashboard(out_dir, data)

    if data.collector_warnings:
        typer.secho(
            f"Collector warnings ({len(data.collector_warnings)}):",
            fg=typer.colors.YELLOW,
        )
        for w in data.collector_warnings[:10]:
            typer.secho(f"  - {w}", fg=typer.colors.YELLOW)

    typer.secho(f"Wrote dashboard to {out_dir}", fg=typer.colors.GREEN)
    typer.echo(f"Open this file in your browser:\n  {html_path}")

    if open_browser:
        import webbrowser
        webbrowser.open(html_path.as_uri())


@app.command("benchmark-csv-backfill")
def benchmark_csv_backfill(
    out_dir: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--out-dir",
        help="Output root used to resolve the default history CSV path.",
    ),
    history_csv: Path | None = typer.Option(
        None,
        "--history-csv",
        help="Explicit performance_history.csv path (overrides --out-dir).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be patched without writing to disk.",
    ),
) -> None:
    """One-off patch for older benchmark CSV rows missing manifest-backed fields."""
    from cookimport.analytics.perf_report import (
        backfill_benchmark_history_csv,
        history_path,
    )

    csv_path = history_csv or history_path(out_dir)
    if not csv_path.exists():
        _fail(f"History CSV not found: {csv_path}")

    summary = backfill_benchmark_history_csv(csv_path, write=not dry_run)

    if dry_run:
        typer.secho(f"Dry run complete: {csv_path}", fg=typer.colors.CYAN)
    else:
        typer.secho(f"Backfill complete: {csv_path}", fg=typer.colors.GREEN)
    typer.echo(f"Benchmark rows scanned: {summary.benchmark_rows}")
    typer.echo(f"Rows updated: {summary.rows_updated}")
    typer.echo(f"Recipes filled: {summary.recipes_filled}")
    typer.echo(f"Report paths filled: {summary.report_paths_filled}")
    typer.echo(f"Source file fields filled: {summary.source_files_filled}")
    typer.echo(f"Rows still missing recipes: {summary.rows_still_missing_recipes}")

    if dry_run and summary.rows_updated > 0:
        typer.secho("Re-run without --dry-run to persist these patches.", fg=typer.colors.YELLOW)
    if not dry_run and summary.rows_updated > 0:
        default_history_csv = history_path(out_dir)
        refresh_output_root: Path | None = out_dir
        try:
            if csv_path.resolve() != default_history_csv.resolve():
                refresh_output_root = None
        except OSError:
            if csv_path != default_history_csv:
                refresh_output_root = None
        _refresh_dashboard_after_history_write(
            csv_path=csv_path,
            output_root=refresh_output_root,
            reason="benchmark-csv-backfill write",
        )


@app.command()
def inspect(
    path: Path = typer.Argument(..., help="Workbook file to inspect."),
    out: Path = typer.Option(DEFAULT_OUTPUT, "--out", help="Output folder."),
    write_mapping: bool = typer.Option(
        False,
        "--write-mapping",
        help="Write a mapping stub alongside staged outputs.",
    ),
) -> None:
    """Inspect a single workbook and print layout guesses."""
    if not path.exists():
        _fail(f"Path not found: {path}")
    if not path.is_file():
        _fail("Inspect expects a workbook file.")

    importer = _require_importer(path)
    with console.status(f"[bold cyan]Inspecting {path.name}...[/bold cyan]", spinner="dots"):
        inspection = importer.inspect(path)
    typer.secho(f"Workbook: {path.name}", fg=typer.colors.CYAN)
    for sheet in inspection.sheets:
        layout = sheet.layout or "unknown"
        header_row = sheet.header_row or 0
        confidence = sheet.confidence if sheet.confidence is not None else 0.0
        note = " (low confidence)" if sheet.low_confidence else ""
        typer.echo(f"- {sheet.name}: {layout} header_row={header_row} score={confidence:.2f}{note}")
    if write_mapping and inspection.mapping_stub is not None:
        mapping_path = out / "mappings" / f"{path.stem}.mapping.yaml"
        save_mapping_config(mapping_path, inspection.mapping_stub)
        typer.secho(f"Wrote mapping stub to {mapping_path}", fg=typer.colors.GREEN)


@app.command("labelstudio-import")
def labelstudio_import(
    path: Path = typer.Argument(..., help="Cookbook file to import for labeling."),
    output_dir: Path = typer.Option(
        DEFAULT_GOLDEN_SENT_TO_LABELSTUDIO,
        "--output-dir",
        help="Output folder for import/upload run artifacts.",
    ),
    pipeline: str = typer.Option("auto", "--pipeline", help="Importer pipeline name or auto."),
    project_name: str | None = typer.Option(
        None, "--project-name", help="Label Studio project name."
    ),
    segment_blocks: int = typer.Option(
        40,
        "--segment-blocks",
        min=1,
        help="Blocks per task for freeform-spans.",
    ),
    segment_overlap: int = typer.Option(
        5,
        "--segment-overlap",
        min=0,
        help="Overlapping blocks between freeform-spans segments.",
    ),
    segment_focus_blocks: Annotated[
        int | None,
        typer.Option(
            "--segment-focus-blocks",
            min=1,
            help=(
                "Blocks per freeform task that should receive labels. "
                "Defaults to segment size when omitted."
            ),
        ),
    ] = None,
    target_task_count: Annotated[
        int | None,
        typer.Option(
            "--target-task-count",
            min=1,
            help=(
                "Optional freeform target task count; overlap is auto-tuned per file "
                "to land as close as possible."
            ),
        ),
    ] = None,
    overwrite: bool = typer.Option(
        False, "--overwrite/--resume", help="Overwrite project or resume."
    ),
    label_studio_url: str | None = typer.Option(
        None, "--label-studio-url", help="Label Studio base URL."
    ),
    label_studio_api_key: str | None = typer.Option(
        None, "--label-studio-api-key", help="Label Studio API key."
    ),
    allow_labelstudio_write: bool = typer.Option(
        False,
        "--allow-labelstudio-write/--no-allow-labelstudio-write",
        help="Explicitly allow writing tasks to Label Studio.",
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-n", min=1, help="Limit number of chunks."
    ),
    sample: int | None = typer.Option(
        None, "--sample", min=1, help="Randomly sample N chunks."
    ),
    prelabel: bool = typer.Option(
        False,
        "--prelabel/--no-prelabel",
        help=(
            "For freeform-spans: ask local Codex CLI for first-pass labels and "
            "attach completed annotations before upload."
        ),
    ),
    prelabel_provider: str = typer.Option(
        "codex-cli",
        "--prelabel-provider",
        help="LLM provider backend for prelabeling (currently: codex-cli).",
    ),
    codex_cmd: str | None = typer.Option(
        None,
        "--codex-cmd",
        help=(
            "Command used for Codex CLI prelabel calls. "
            "Defaults to COOKIMPORT_CODEX_CMD or `codex exec -`."
        ),
    ),
    codex_model: str | None = typer.Option(
        None,
        "--codex-model",
        help=(
            "Explicit Codex model for prelabel calls. "
            "When omitted, uses COOKIMPORT_CODEX_MODEL or your Codex CLI default model."
        ),
    ),
    codex_reasoning_effort: Annotated[
        str | None,
        typer.Option(
            "--codex-thinking-effort",
            "--codex-reasoning-effort",
            help=(
                "Codex thinking effort for prelabel calls "
                "(none, minimal, low, medium, high, xhigh). "
                "Mapped to model_reasoning_effort."
            ),
        ),
    ] = None,
    prelabel_timeout_seconds: Annotated[
        int,
        typer.Option(
            "--prelabel-timeout-seconds",
            min=1,
            help="Timeout per prelabel provider call.",
        ),
    ] = DEFAULT_PRELABEL_TIMEOUT_SECONDS,
    prelabel_cache_dir: Path | None = typer.Option(
        None,
        "--prelabel-cache-dir",
        help="Optional cache directory for prompt/response snapshots.",
    ),
    prelabel_workers: int = typer.Option(
        15,
        "--prelabel-workers",
        min=1,
        help=(
            "Maximum concurrent freeform prelabel provider calls. "
            "Use 1 to force serialized task labeling."
        ),
    ),
    prelabel_upload_as: str = typer.Option(
        "annotations",
        "--prelabel-upload-as",
        help="Upload prelabels as completed annotations or predictions.",
    ),
    prelabel_granularity: str = typer.Option(
        PRELABEL_GRANULARITY_BLOCK,
        "--prelabel-granularity",
        help=(
            "Freeform prelabel style: block (block based) or span "
            "(actual freeform highlights)."
        ),
    ),
    prelabel_allow_partial: bool = typer.Option(
        False,
        "--prelabel-allow-partial/--no-prelabel-allow-partial",
        help=(
            "Allow upload to continue when some prelabel tasks fail. "
            "Failures are recorded in prelabel report files."
        ),
    ),
    llm_recipe_pipeline: str = typer.Option(
        "off",
        "--llm-recipe-pipeline",
        help=(
            "Recipe codex-farm parsing correction pipeline. "
            "Policy-locked OFF for now; must remain off until benchmark quality improves."
        ),
    ),
    codex_farm_cmd: str = typer.Option(
        "codex-farm",
        "--codex-farm-cmd",
        help="Executable used for codex-farm calls when LLM recipe pipeline is enabled.",
    ),
    codex_farm_root: Path | None = typer.Option(
        None,
        "--codex-farm-root",
        help="Optional codex-farm pipeline-pack root. Defaults to <repo_root>/llm_pipelines.",
    ),
    codex_farm_workspace_root: Path | None = typer.Option(
        None,
        "--codex-farm-workspace-root",
        help=(
            "Optional workspace root passed to codex-farm. "
            "When omitted, codex-farm pipeline codex_cd_mode decides."
        ),
    ),
    codex_farm_pipeline_pass1: str = typer.Option(
        "recipe.chunking.v1",
        "--codex-farm-pipeline-pass1",
        help="Pass-1 codex-farm pipeline id (recipe boundary refinement).",
    ),
    codex_farm_pipeline_pass2: str = typer.Option(
        "recipe.schemaorg.v1",
        "--codex-farm-pipeline-pass2",
        help="Pass-2 codex-farm pipeline id (schema.org extraction).",
    ),
    codex_farm_pipeline_pass3: str = typer.Option(
        "recipe.final.v1",
        "--codex-farm-pipeline-pass3",
        help="Pass-3 codex-farm pipeline id (final draft generation).",
    ),
    codex_farm_context_blocks: int = typer.Option(
        30,
        "--codex-farm-context-blocks",
        min=0,
        help="Blocks before/after each recipe candidate included in pass-1 codex-farm bundles.",
    ),
    codex_farm_failure_mode: str = typer.Option(
        "fail",
        "--codex-farm-failure-mode",
        help="Behavior when codex-farm setup/invocation fails: fail or fallback.",
    ),
) -> None:
    """Create and upload freeform span Label Studio tasks."""
    allow_labelstudio_write = _unwrap_typer_option_default(allow_labelstudio_write)
    output_dir = _unwrap_typer_option_default(output_dir)
    pipeline = _unwrap_typer_option_default(pipeline)
    project_name = _unwrap_typer_option_default(project_name)
    segment_blocks = _unwrap_typer_option_default(segment_blocks)
    segment_overlap = _unwrap_typer_option_default(segment_overlap)
    segment_focus_blocks = _unwrap_typer_option_default(segment_focus_blocks)
    target_task_count = _unwrap_typer_option_default(target_task_count)
    overwrite = _unwrap_typer_option_default(overwrite)
    label_studio_url = _unwrap_typer_option_default(label_studio_url)
    label_studio_api_key = _unwrap_typer_option_default(label_studio_api_key)
    limit = _unwrap_typer_option_default(limit)
    sample = _unwrap_typer_option_default(sample)
    prelabel = _unwrap_typer_option_default(prelabel)
    prelabel_provider = _unwrap_typer_option_default(prelabel_provider)
    codex_cmd = _unwrap_typer_option_default(codex_cmd)
    codex_model = _unwrap_typer_option_default(codex_model)
    codex_reasoning_effort = _unwrap_typer_option_default(codex_reasoning_effort)
    prelabel_timeout_seconds = _unwrap_typer_option_default(prelabel_timeout_seconds)
    prelabel_cache_dir = _unwrap_typer_option_default(prelabel_cache_dir)
    prelabel_workers = _unwrap_typer_option_default(prelabel_workers)
    prelabel_upload_as = _unwrap_typer_option_default(prelabel_upload_as)
    prelabel_granularity = _unwrap_typer_option_default(prelabel_granularity)
    prelabel_allow_partial = _unwrap_typer_option_default(prelabel_allow_partial)
    llm_recipe_pipeline = _unwrap_typer_option_default(llm_recipe_pipeline)
    codex_farm_cmd = _unwrap_typer_option_default(codex_farm_cmd)
    codex_farm_root = _unwrap_typer_option_default(codex_farm_root)
    codex_farm_workspace_root = _unwrap_typer_option_default(codex_farm_workspace_root)
    codex_farm_pipeline_pass1 = _unwrap_typer_option_default(codex_farm_pipeline_pass1)
    codex_farm_pipeline_pass2 = _unwrap_typer_option_default(codex_farm_pipeline_pass2)
    codex_farm_pipeline_pass3 = _unwrap_typer_option_default(codex_farm_pipeline_pass3)
    codex_farm_context_blocks = _unwrap_typer_option_default(codex_farm_context_blocks)
    codex_farm_failure_mode = _unwrap_typer_option_default(codex_farm_failure_mode)

    _require_labelstudio_write_consent(allow_labelstudio_write)
    normalized_prelabel_upload_as = prelabel_upload_as.strip().lower()
    if normalized_prelabel_upload_as not in {"annotations", "predictions"}:
        _fail(
            "--prelabel-upload-as must be one of: annotations, predictions."
        )
    try:
        normalized_prelabel_granularity = normalize_prelabel_granularity(
            prelabel_granularity
        )
    except ValueError as exc:
        _fail(f"--prelabel-granularity invalid: {exc}")
    try:
        normalized_codex_reasoning_effort = normalize_codex_reasoning_effort(
            codex_reasoning_effort
        )
    except ValueError as exc:
        _fail(f"--codex-thinking-effort invalid: {exc}")
    resolved_segment_focus_blocks = (
        segment_blocks if segment_focus_blocks is None else int(segment_focus_blocks)
    )
    if resolved_segment_focus_blocks > segment_blocks:
        _fail("--segment-focus-blocks must be <= --segment-blocks.")
    selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
    selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
        codex_farm_failure_mode
    )
    selected_codex_farm_pipeline_pass1 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass1,
        option="--codex-farm-pipeline-pass1",
    )
    selected_codex_farm_pipeline_pass2 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass2,
        option="--codex-farm-pipeline-pass2",
    )
    selected_codex_farm_pipeline_pass3 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass3,
        option="--codex-farm-pipeline-pass3",
    )
    url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)
    import_started_at = time.monotonic()
    try:
        result = _run_labelstudio_import_with_status(
            source_name=path.name,
            run_import=lambda update_progress: run_labelstudio_import(
                path=path,
                output_dir=output_dir,
                pipeline=pipeline,
                project_name=project_name,
                segment_blocks=segment_blocks,
                segment_overlap=segment_overlap,
                segment_focus_blocks=resolved_segment_focus_blocks,
                target_task_count=target_task_count,
                overwrite=overwrite,
                resume=not overwrite,
                label_studio_url=url,
                label_studio_api_key=api_key,
                limit=limit,
                sample=sample,
                progress_callback=update_progress,
                prelabel=prelabel,
                prelabel_provider=prelabel_provider,
                codex_cmd=codex_cmd,
                codex_model=codex_model,
                codex_reasoning_effort=normalized_codex_reasoning_effort,
                prelabel_timeout_seconds=prelabel_timeout_seconds,
                prelabel_cache_dir=prelabel_cache_dir,
                prelabel_workers=prelabel_workers,
                prelabel_upload_as=normalized_prelabel_upload_as,
                prelabel_granularity=normalized_prelabel_granularity,
                prelabel_allow_partial=prelabel_allow_partial,
                prelabel_track_token_usage=True,
                llm_recipe_pipeline=selected_llm_recipe_pipeline,
                codex_farm_cmd=codex_farm_cmd,
                codex_farm_root=codex_farm_root,
                codex_farm_workspace_root=codex_farm_workspace_root,
                codex_farm_pipeline_pass1=selected_codex_farm_pipeline_pass1,
                codex_farm_pipeline_pass2=selected_codex_farm_pipeline_pass2,
                codex_farm_pipeline_pass3=selected_codex_farm_pipeline_pass3,
                codex_farm_context_blocks=codex_farm_context_blocks,
                codex_farm_failure_mode=selected_codex_farm_failure_mode,
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
    if prelabel:
        _print_prelabel_completion_summary(
            prelabel_summary=result.get("prelabel") or {},
            report_path=result.get("prelabel_report_path"),
            inline_annotation_fallback=bool(
                result.get("prelabel_inline_annotations_fallback")
            ),
        )
    typer.secho(f"Artifacts saved to: {result['run_root']}", fg=typer.colors.CYAN)
    typer.echo("\nTo export labels:\n")
    typer.echo(
        f'cookimport labelstudio-export --project-name "{result["project_name"]}" '
        f'--label-studio-url {url} --label-studio-api-key $LABEL_STUDIO_API_KEY'
    )


@app.command("labelstudio-export")
def labelstudio_export(
    project_name: str = typer.Option(..., "--project-name", help="Label Studio project name."),
    output_dir: Path = typer.Option(
        DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO,
        "--output-dir",
        help="Output folder for exported golden artifacts.",
    ),
    run_dir: Path | None = typer.Option(
        None, "--run-dir", help="Specific labelstudio run directory to export."
    ),
    label_studio_url: str | None = typer.Option(
        None, "--label-studio-url", help="Label Studio base URL."
    ),
    label_studio_api_key: str | None = typer.Option(
        None, "--label-studio-api-key", help="Label Studio API key."
    ),
) -> None:
    """Export completed Label Studio annotations into golden-set JSONL artifacts."""
    url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)
    try:
        result = run_labelstudio_export(
            project_name=project_name,
            output_dir=output_dir,
            label_studio_url=url,
            label_studio_api_key=api_key,
            run_dir=run_dir,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    summary_path = result["summary_path"]
    typer.secho(f"Export complete. Summary: {summary_path}", fg=typer.colors.GREEN)


@app.command("labelstudio-eval")
def labelstudio_eval(
    pred_run: Path = typer.Option(
        ..., "--pred-run", help="Label Studio run directory with label_studio_tasks.jsonl."
    ),
    gold_spans: Path = typer.Option(
        ..., "--gold-spans", help="Path to freeform gold JSONL."
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir", help="Output folder for eval artifacts."
    ),
    overlap_threshold: Annotated[
        float,
        typer.Option(
            "--overlap-threshold",
            min=0.0,
            max=1.0,
            help="Jaccard overlap threshold for matching.",
        ),
    ] = 0.5,
    force_source_match: Annotated[
        bool,
        typer.Option(
            "--force-source-match",
            help=(
                "Ignore source hash/file identity when matching spans. "
                "Useful for comparing renamed/truncated source variants."
            ),
        ),
    ] = False,
) -> None:
    """Evaluate freeform predictions against freeform gold sets."""
    scope = "freeform-spans"
    if not pred_run.exists():
        _fail(f"Predicted run not found: {pred_run}")
    if not gold_spans.exists():
        _fail(f"Gold spans file not found: {gold_spans}")

    output_dir.mkdir(parents=True, exist_ok=True)

    predicted = load_predicted_labeled_ranges(pred_run)
    gold = load_gold_freeform_ranges(gold_spans)
    result = evaluate_predicted_vs_freeform(
        predicted,
        gold,
        overlap_threshold=overlap_threshold,
        force_source_match=force_source_match,
    )
    report = result["report"]

    pred_context = _load_pred_run_recipe_context(pred_run)
    _attach_freeform_recipe_count_context(
        report=report,
        gold_spans_path=gold_spans,
        predicted_recipe_count=pred_context.recipes,
        predicted_recipe_count_source=(
            "prediction_run_context" if pred_context.recipes is not None else None
        ),
    )
    report_md = format_freeform_eval_report_md(report)

    report_json_path = output_dir / "eval_report.json"
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    report_md_path = output_dir / "eval_report.md"
    report_md_path.write_text(report_md, encoding="utf-8")

    _write_jsonl_rows(output_dir / "missed_gold_spans.jsonl", result["missed_gold"])
    _write_jsonl_rows(
        output_dir / "false_positive_preds.jsonl", result["false_positive_preds"]
    )

    csv_source_file = pred_context.source_file or ""
    csv_history_root = DEFAULT_OUTPUT
    if pred_context.processed_report_path:
        processed_report = Path(pred_context.processed_report_path)
        if (
            processed_report.name.endswith(".excel_import_report.json")
            and len(processed_report.parents) >= 2
        ):
            csv_history_root = processed_report.parents[1]

    from cookimport.analytics.perf_report import append_benchmark_csv, history_path
    csv_history_path = history_path(csv_history_root)
    append_benchmark_csv(
        report,
        csv_history_path,
        run_timestamp=dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        run_dir=str(output_dir),
        eval_scope=scope,
        source_file=csv_source_file,
        recipes=pred_context.recipes,
        processed_report_path=pred_context.processed_report_path,
        run_config=pred_context.run_config,
        run_config_hash=pred_context.run_config_hash,
        run_config_summary=pred_context.run_config_summary,
    )
    _refresh_dashboard_after_history_write(
        csv_path=csv_history_path,
        output_root=csv_history_root,
        reason="labelstudio-eval history append",
    )

    eval_run_config: dict[str, Any] = {
        "scope": scope,
        "overlap_threshold": overlap_threshold,
        "force_source_match": force_source_match,
    }
    if pred_context.run_config is not None:
        eval_run_config["prediction_run_config"] = pred_context.run_config
    if pred_context.run_config_hash:
        eval_run_config["prediction_run_config_hash"] = pred_context.run_config_hash
    if pred_context.run_config_summary:
        eval_run_config["prediction_run_config_summary"] = pred_context.run_config_summary

    _write_eval_run_manifest(
        run_root=output_dir,
        run_kind="labelstudio_eval",
        source_path=pred_context.source_file or None,
        source_hash=pred_context.source_hash,
        importer_name=None,
        run_config=eval_run_config,
        artifacts={
            "pred_run_dir": _path_for_manifest(output_dir, pred_run),
            "gold_spans_jsonl": _path_for_manifest(output_dir, gold_spans),
            "eval_report_json": "eval_report.json",
            "eval_report_md": "eval_report.md",
            "missed_gold_spans_jsonl": "missed_gold_spans.jsonl",
            "false_positive_preds_jsonl": "false_positive_preds.jsonl",
            "history_csv": str(history_csv_for_output(csv_history_root)),
        },
        notes="Evaluation report against exported gold spans.",
    )

    typer.secho(
        f"Evaluation complete. Report: {report_md_path}",
        fg=typer.colors.GREEN,
    )


_QUANTITY_TOKEN_RE = re.compile(
    r"(?<!\w)(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?)\s*"
    r"(?:cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lb|lbs|pounds?|"
    r"g|kg|ml|l)\b",
    flags=re.IGNORECASE,
)


def _p95_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, ((len(ordered) * 95 + 99) // 100) - 1)
    return int(ordered[idx])


def _has_multiple_quantity_tokens(text: str) -> bool:
    return len(_QUANTITY_TOKEN_RE.findall(text)) >= 2


def _write_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True)
        for row in rows
    )
    path.write_text(payload + "\n", encoding="utf-8")


@app.command("debug-epub-extract")
def debug_epub_extract(
    path: Path = typer.Argument(..., help="EPUB file to inspect."),
    out: Path = typer.Option(
        DEFAULT_OUTPUT / "epub-debug",
        "--out",
        help="Output root for debug extraction artifacts.",
    ),
    spine: int = typer.Option(
        0,
        "--spine",
        min=0,
        help="Spine index to extract for variant comparison.",
    ),
    variants: bool = typer.Option(
        False,
        "--variants",
        help=(
            "Run the parser/preprocess variant grid "
            "(v1/v2 x none/br_split_v1) instead of a single variant."
        ),
    ),
    html_parser_version: str = typer.Option(
        "v1",
        "--html-parser-version",
        help="Single-run parser version when --variants is not set (v1 or v2).",
    ),
    preprocess_mode: str = typer.Option(
        "none",
        "--preprocess-mode",
        help=(
            "Single-run preprocess mode when --variants is not set "
            "(none, br_split_v1, semantic_v1)."
        ),
    ),
    skip_headers_footers: bool = typer.Option(
        False,
        "--skip-headers-footers/--no-skip-headers-footers",
        help="Pass skip_headers_and_footers into Unstructured partition_html.",
    ),
) -> None:
    """Compare unstructured EPUB extraction variants for one spine XHTML document."""
    from cookimport.parsing.block_roles import assign_block_roles
    from cookimport.parsing.epub_postprocess import postprocess_epub_blocks
    from cookimport.parsing.epub_html_normalize import normalize_epub_html_for_unstructured
    from cookimport.parsing import signals
    from cookimport.parsing.unstructured_adapter import (
        UnstructuredHtmlOptions,
        partition_html_to_blocks,
    )

    if not path.exists() or not path.is_file():
        _fail(f"EPUB file not found: {path}")
    if path.suffix.lower() != ".epub":
        _fail(f"Expected an EPUB file, got: {path}")

    selected_parser = _normalize_unstructured_html_parser_version(html_parser_version)
    selected_preprocess = _normalize_unstructured_preprocess_mode(preprocess_mode)

    run_root = out / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    run_root.mkdir(parents=True, exist_ok=True)

    importer = epub.EpubImporter()
    _title, spine_items = importer._read_epub_spine(path)  # noqa: SLF001
    if not spine_items:
        _fail("No spine items found in EPUB.")
    if spine >= len(spine_items):
        _fail(
            f"Spine index out of range: {spine}. "
            f"EPUB has {len(spine_items)} spine entries."
        )

    spine_path = spine_items[spine].path
    with zipfile.ZipFile(path) as zip_handle:
        raw_html = zip_handle.read(spine_path).decode("utf-8", errors="replace")
    (run_root / "raw_spine.xhtml").write_text(raw_html, encoding="utf-8")

    variant_pairs: list[tuple[str, str]]
    if variants:
        variant_pairs = [
            (parser_version, preprocess_variant)
            for preprocess_variant in ("none", "br_split_v1")
            for parser_version in ("v1", "v2")
        ]
    else:
        variant_pairs = [(selected_parser, selected_preprocess)]

    summary_rows: list[dict[str, Any]] = []
    for parser_version, preprocess_variant in variant_pairs:
        variant_slug = f"parser_{parser_version}__preprocess_{preprocess_variant}"
        variant_dir = run_root / variant_slug
        variant_dir.mkdir(parents=True, exist_ok=True)

        normalized_html = normalize_epub_html_for_unstructured(
            raw_html,
            mode=preprocess_variant,
        )
        (variant_dir / "normalized_spine.xhtml").write_text(
            normalized_html,
            encoding="utf-8",
        )

        options = UnstructuredHtmlOptions(
            html_parser_version=parser_version,
            skip_headers_and_footers=skip_headers_footers,
            preprocess_mode=preprocess_variant,
        )
        try:
            blocks, diagnostics = partition_html_to_blocks(
                normalized_html,
                spine_index=spine,
                source_location_id=path.stem,
                options=options,
            )
        except Exception as exc:  # noqa: BLE001
            (variant_dir / "error.txt").write_text(str(exc), encoding="utf-8")
            summary_rows.append(
                {
                    "variant": variant_slug,
                    "html_parser_version": parser_version,
                    "preprocess_mode": preprocess_variant,
                    "skip_headers_footers": skip_headers_footers,
                    "error": str(exc),
                    "block_count": 0,
                    "p95_block_length": 0,
                    "blocks_with_multiple_quantities": 0,
                    "ingredient_line_block_count": 0,
                }
            )
            continue
        blocks = postprocess_epub_blocks(blocks)
        for block in blocks:
            signals.enrich_block(block)
        assign_block_roles(blocks)

        blocks_rows = [
            {
                "index": index,
                "text": block.text,
                "type": str(block.type),
                "font_weight": block.font_weight,
                "features": dict(block.features),
            }
            for index, block in enumerate(blocks)
        ]
        _write_jsonl_rows(variant_dir / "blocks.jsonl", blocks_rows)
        _write_jsonl_rows(variant_dir / "unstructured_elements.jsonl", diagnostics)

        block_lengths = [len(block.text) for block in blocks if block.text]
        ingredient_line_count = sum(
            1
            for block in blocks
            if block.features.get("block_role") == "ingredient_line"
        )
        multi_quantity_count = sum(
            1
            for block in blocks
            if _has_multiple_quantity_tokens(block.text)
        )
        summary_rows.append(
            {
                "variant": variant_slug,
                "html_parser_version": parser_version,
                "preprocess_mode": preprocess_variant,
                "skip_headers_footers": skip_headers_footers,
                "block_count": len(blocks),
                "p95_block_length": _p95_int(block_lengths),
                "blocks_with_multiple_quantities": multi_quantity_count,
                "ingredient_line_block_count": ingredient_line_count,
            }
        )

    summary_payload = {
        "source_file": str(path),
        "spine_index": spine,
        "spine_path": spine_path,
        "variants": summary_rows,
    }
    (run_root / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    typer.secho(f"Wrote EPUB debug extraction artifacts to: {run_root}", fg=typer.colors.GREEN)
    for row in summary_rows:
        typer.echo(
            " | ".join(
                [
                    row["variant"],
                    f"blocks={row['block_count']}",
                    f"p95_len={row['p95_block_length']}",
                    f"multi_qty={row['blocks_with_multiple_quantities']}",
                    f"ingredient_line={row['ingredient_line_block_count']}",
                ]
            )
        )


@app.command("labelstudio-benchmark")
def labelstudio_benchmark(
    gold_spans: Annotated[Path | None, typer.Option(
        "--gold-spans",
        help="Path to freeform_span_labels.jsonl (prompts if omitted).",
    )] = None,
    source_file: Annotated[Path | None, typer.Option(
        "--source-file",
        help="Source file to import and benchmark (prompts if omitted).",
    )] = None,
    output_dir: Annotated[Path, typer.Option(
        "--output-dir",
        help="Scratch output root used while generating prediction tasks before co-locating under eval output.",
    )] = DEFAULT_GOLDEN_BENCHMARK,
    processed_output_dir: Annotated[Path, typer.Option(
        "--processed-output-dir",
        help="Output root for staged cookbook outputs generated during benchmark (for upload/review).",
    )] = DEFAULT_OUTPUT,
    eval_output_dir: Annotated[Path | None, typer.Option(
        "--eval-output-dir", help="Output folder for benchmark report artifacts."
    )] = None,
    overlap_threshold: Annotated[float, typer.Option(
        "--overlap-threshold",
        min=0.0,
        max=1.0,
        help="Jaccard overlap threshold for matching.",
    )] = 0.5,
    force_source_match: Annotated[bool, typer.Option(
        "--force-source-match",
        help=(
            "Ignore source hash/file identity when matching spans. "
            "Useful for comparing renamed/truncated source variants."
        ),
    )] = False,
    eval_mode: Annotated[str, typer.Option(
        "--eval-mode",
        help=(
            "Benchmark evaluator mode: stage-blocks (block-index parity required) "
            "or canonical-text (extractor-independent alignment scoring)."
        ),
    )] = BENCHMARK_EVAL_MODE_STAGE_BLOCKS,
    execution_mode: Annotated[str, typer.Option(
        "--execution-mode",
        help=(
            "Benchmark execution mode: legacy (sequential predict->evaluate) "
            "or pipelined (bounded record producer/consumer with eval prewarm overlap), "
            "or predict-only (write prediction artifacts and skip evaluation)."
        ),
    )] = BENCHMARK_EXECUTION_MODE_LEGACY,
    predictions_out: Annotated[Path | None, typer.Option(
        "--predictions-out",
        help=(
            "Optional JSONL artifact path for prediction-stage records. "
            "Useful for rerunning evaluate-only with --predictions-in."
        ),
    )] = None,
    predictions_in: Annotated[Path | None, typer.Option(
        "--predictions-in",
        help=(
            "Optional JSONL prediction-stage record path. "
            "When set, skips prediction generation and runs evaluate-only."
        ),
    )] = None,
    pipeline: Annotated[str, typer.Option("--pipeline", help="Importer pipeline name or auto.")] = "auto",
    project_name: Annotated[str | None, typer.Option(
        "--project-name",
        help="Optional Label Studio project name for prediction import.",
    )] = None,
    allow_labelstudio_write: Annotated[bool, typer.Option(
        "--allow-labelstudio-write/--no-allow-labelstudio-write",
        help=(
            "Explicitly allow uploading prediction tasks to Label Studio. "
            "Ignored when --no-upload is set."
        ),
    )] = False,
    no_upload: Annotated[bool, typer.Option(
        "--no-upload",
        help=(
            "Generate prediction artifacts locally and evaluate without "
            "uploading to Label Studio."
        ),
    )] = False,
    write_markdown: Annotated[bool, typer.Option(
        "--write-markdown/--no-write-markdown",
        help=(
            "Write markdown sidecar artifacts for processed stage outputs "
            "(sections/tips/topic/chunks/tables)."
        ),
    )] = True,
    write_label_studio_tasks: Annotated[bool, typer.Option(
        "--write-labelstudio-tasks/--no-write-labelstudio-tasks",
        help=(
            "Write label_studio_tasks.jsonl in offline prediction runs. "
            "Upload mode always requires task JSONL."
        ),
    )] = True,
    overwrite: Annotated[bool, typer.Option("--overwrite/--resume", help="Overwrite prediction project or resume.")] = False,
    label_studio_url: Annotated[str | None, typer.Option("--label-studio-url", help="Label Studio base URL.")] = None,
    label_studio_api_key: Annotated[str | None, typer.Option("--label-studio-api-key", help="Label Studio API key.")] = None,
    workers: Annotated[int, typer.Option("--workers", min=1, help="Number of parallel worker processes for prediction import.")] = 7,
    pdf_split_workers: Annotated[int, typer.Option("--pdf-split-workers", min=1, help="Max workers used when splitting a PDF prediction import.")] = 7,
    epub_split_workers: Annotated[int, typer.Option("--epub-split-workers", min=1, help="Max workers used when splitting an EPUB prediction import.")] = 7,
    pdf_pages_per_job: Annotated[int, typer.Option("--pdf-pages-per-job", min=1, help="Target page count per PDF split job.")] = 50,
    epub_spine_items_per_job: Annotated[int, typer.Option("--epub-spine-items-per-job", min=1, help="Target spine items per EPUB split job.")] = 10,
    ocr_device: Annotated[str, typer.Option(
        "--ocr-device",
        help="OCR device to use (auto, cpu, cuda, mps).",
    )] = "auto",
    ocr_batch_size: Annotated[int, typer.Option(
        "--ocr-batch-size",
        min=1,
        help="Number of pages to process per OCR model call.",
    )] = 1,
    warm_models: Annotated[bool, typer.Option(
        "--warm-models",
        help="Proactively load heavy models before prediction import.",
    )] = False,
    epub_extractor: Annotated[str, typer.Option(
        "--epub-extractor",
        help=(
            "EPUB extraction engine: unstructured (semantic), beautifulsoup "
            "(BeautifulSoup), markdown (HTML->Markdown), or markitdown (whole-book "
            "EPUB->markdown mode)."
        ),
    )] = "unstructured",
    epub_unstructured_html_parser_version: Annotated[str, typer.Option(
        "--epub-unstructured-html-parser-version",
        help="Unstructured HTML parser version for EPUB extraction: v1 or v2.",
    )] = "v1",
    epub_unstructured_skip_headers_footers: Annotated[bool, typer.Option(
        "--epub-unstructured-skip-headers-footers/--no-epub-unstructured-skip-headers-footers",
        help="Enable Unstructured skip_headers_and_footers for EPUB HTML partitioning.",
    )] = False,
    epub_unstructured_preprocess_mode: Annotated[str, typer.Option(
        "--epub-unstructured-preprocess-mode",
        help="EPUB HTML preprocess mode before Unstructured partitioning: none, br_split_v1, semantic_v1.",
    )] = "br_split_v1",
    llm_recipe_pipeline: Annotated[str, typer.Option(
        "--llm-recipe-pipeline",
        help=(
            "Recipe codex-farm parsing correction pipeline. "
            "Policy-locked OFF for now; must remain off until benchmark quality improves."
        ),
    )] = "off",
    codex_farm_cmd: Annotated[str, typer.Option(
        "--codex-farm-cmd",
        help="Executable used for codex-farm calls when LLM recipe pipeline is enabled.",
    )] = "codex-farm",
    codex_farm_root: Annotated[Path | None, typer.Option(
        "--codex-farm-root",
        help="Optional codex-farm pipeline-pack root. Defaults to <repo_root>/llm_pipelines.",
    )] = None,
    codex_farm_workspace_root: Annotated[Path | None, typer.Option(
        "--codex-farm-workspace-root",
        help=(
            "Optional workspace root passed to codex-farm. "
            "When omitted, codex-farm pipeline codex_cd_mode decides."
        ),
    )] = None,
    codex_farm_pipeline_pass1: Annotated[str, typer.Option(
        "--codex-farm-pipeline-pass1",
        help="Pass-1 codex-farm pipeline id (recipe boundary refinement).",
    )] = "recipe.chunking.v1",
    codex_farm_pipeline_pass2: Annotated[str, typer.Option(
        "--codex-farm-pipeline-pass2",
        help="Pass-2 codex-farm pipeline id (schema.org extraction).",
    )] = "recipe.schemaorg.v1",
    codex_farm_pipeline_pass3: Annotated[str, typer.Option(
        "--codex-farm-pipeline-pass3",
        help="Pass-3 codex-farm pipeline id (final draft generation).",
    )] = "recipe.final.v1",
    codex_farm_context_blocks: Annotated[int, typer.Option(
        "--codex-farm-context-blocks",
        min=0,
        help="Blocks before/after each recipe candidate included in pass-1 codex-farm bundles.",
    )] = 30,
    codex_farm_failure_mode: Annotated[str, typer.Option(
        "--codex-farm-failure-mode",
        help="Behavior when codex-farm setup/invocation fails: fail or fallback.",
    )] = "fail",
    alignment_cache_dir: Annotated[Path | None, typer.Option(
        "--alignment-cache-dir",
        help="Internal: optional canonical alignment cache directory for benchmark runs.",
        hidden=True,
    )] = None,
) -> None:
    """Run benchmark eval against freeform gold, with optional upload step."""
    external_progress_callback = _BENCHMARK_PROGRESS_CALLBACK.get()
    suppress_summary = bool(_BENCHMARK_SUPPRESS_SUMMARY.get())
    suppress_spinner = bool(_BENCHMARK_SUPPRESS_SPINNER.get())
    split_phase_slots = _BENCHMARK_SPLIT_PHASE_SLOTS.get()
    split_phase_gate_dir_raw = _BENCHMARK_SPLIT_PHASE_GATE_DIR.get()
    split_phase_gate_dir = (
        Path(split_phase_gate_dir_raw) if split_phase_gate_dir_raw else None
    )
    split_phase_status_label = _BENCHMARK_SPLIT_PHASE_STATUS_LABEL.get()
    scheduler_event_callback = _BENCHMARK_SCHEDULER_EVENT_CALLBACK.get()

    def _emit_external_progress(message: str) -> None:
        _notify_progress_callback(external_progress_callback, message)

    selected_epub_extractor = _normalize_epub_extractor(epub_extractor)
    selected_html_parser_version = _normalize_unstructured_html_parser_version(
        epub_unstructured_html_parser_version
    )
    selected_preprocess_mode = _normalize_unstructured_preprocess_mode(
        epub_unstructured_preprocess_mode
    )
    selected_skip_headers_footers = bool(epub_unstructured_skip_headers_footers)
    selected_ocr_device = _normalize_ocr_device(ocr_device)
    selected_llm_recipe_pipeline = _normalize_llm_recipe_pipeline(llm_recipe_pipeline)
    selected_codex_farm_failure_mode = _normalize_codex_farm_failure_mode(
        codex_farm_failure_mode
    )
    selected_codex_farm_pipeline_pass1 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass1,
        option="--codex-farm-pipeline-pass1",
    )
    selected_codex_farm_pipeline_pass2 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass2,
        option="--codex-farm-pipeline-pass2",
    )
    selected_codex_farm_pipeline_pass3 = _normalize_codex_farm_pipeline_id(
        codex_farm_pipeline_pass3,
        option="--codex-farm-pipeline-pass3",
    )
    selected_eval_mode = _normalize_benchmark_eval_mode(eval_mode)
    selected_execution_mode = _normalize_benchmark_execution_mode(execution_mode)

    predictions_in_path = predictions_in.expanduser() if predictions_in is not None else None
    predictions_out_path = (
        predictions_out.expanduser() if predictions_out is not None else None
    )
    if predictions_in_path is not None and predictions_out_path is not None:
        _fail("Cannot combine --predictions-in and --predictions-out in one run.")
    if (
        selected_execution_mode == BENCHMARK_EXECUTION_MODE_PREDICT_ONLY
        and predictions_in_path is not None
    ):
        _fail("--execution-mode predict-only cannot be combined with --predictions-in.")

    prediction_record_input: list[PredictionRecord] = []
    prediction_record_source: Path | None = None
    if predictions_in_path is not None:
        try:
            prediction_record_input = list(read_prediction_records(predictions_in_path))
        except Exception as exc:  # noqa: BLE001
            _fail(f"Unable to load prediction record from {predictions_in_path}: {exc}")
        prediction_record_source = _prediction_record_source_file_hint(
            prediction_record_input
        )

    should_generate_predictions = predictions_in_path is None
    should_upload_predictions = should_generate_predictions and not no_upload
    should_run_evaluation = selected_execution_mode != BENCHMARK_EXECUTION_MODE_PREDICT_ONLY

    if should_upload_predictions and not write_label_studio_tasks:
        _fail("--no-write-labelstudio-tasks can only be used with --no-upload.")

    url: str | None = None
    api_key: str | None = None
    if should_upload_predictions:
        _require_labelstudio_write_consent(allow_labelstudio_write)
        url, api_key = _resolve_labelstudio_settings(label_studio_url, label_studio_api_key)

    resolved_inputs = _resolve_benchmark_gold_and_source(
        gold_spans=gold_spans,
        source_file=source_file or prediction_record_source,
        output_dir=output_dir,
        allow_cancel=False,
    )
    if resolved_inputs is None:
        _fail("Benchmark cancelled.")
    selected_gold, selected_source = resolved_inputs

    if eval_output_dir is None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        eval_output_dir = _golden_benchmark_root() / timestamp
    eval_output_dir.mkdir(parents=True, exist_ok=True)

    if warm_models:
        with console.status("[bold cyan]Warming models...[/bold cyan]", spinner="dots"):
            _warm_all_models(ocr_device=selected_ocr_device)

    benchmark_started = time.monotonic()
    import_result: dict[str, Any]
    pred_run: Path
    pred_context: PredRunContext
    stage_predictions_path: Path
    extracted_archive_path: Path
    prediction_phase_seconds = 0.0
    prewarmed_canonical_paths: dict[str, Path] | None = None
    prediction_records_output: list[PredictionRecord] = []

    try:
        if should_generate_predictions:
            with _temporary_epub_extractor(selected_epub_extractor):
                with _temporary_epub_unstructured_options(
                    html_parser_version=selected_html_parser_version,
                    skip_headers_footers=selected_skip_headers_footers,
                    preprocess_mode=selected_preprocess_mode,
                ):
                    def _run_prediction_generation(
                        callback: Callable[[str], None] | None,
                    ) -> dict[str, Any]:
                        if no_upload:
                            return generate_pred_run_artifacts(
                                path=selected_source,
                                output_dir=output_dir,
                                pipeline=pipeline,
                                segment_blocks=40,
                                segment_overlap=5,
                                limit=None,
                                sample=None,
                                workers=workers,
                                pdf_split_workers=pdf_split_workers,
                                epub_split_workers=epub_split_workers,
                                pdf_pages_per_job=pdf_pages_per_job,
                                epub_spine_items_per_job=epub_spine_items_per_job,
                                epub_extractor=selected_epub_extractor,
                                epub_unstructured_html_parser_version=selected_html_parser_version,
                                epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
                                epub_unstructured_preprocess_mode=selected_preprocess_mode,
                                ocr_device=selected_ocr_device,
                                ocr_batch_size=ocr_batch_size,
                                warm_models=warm_models,
                                llm_recipe_pipeline=selected_llm_recipe_pipeline,
                                codex_farm_cmd=codex_farm_cmd,
                                codex_farm_root=codex_farm_root,
                                codex_farm_workspace_root=codex_farm_workspace_root,
                                codex_farm_pipeline_pass1=selected_codex_farm_pipeline_pass1,
                                codex_farm_pipeline_pass2=selected_codex_farm_pipeline_pass2,
                                codex_farm_pipeline_pass3=selected_codex_farm_pipeline_pass3,
                                codex_farm_context_blocks=codex_farm_context_blocks,
                                codex_farm_failure_mode=selected_codex_farm_failure_mode,
                                processed_output_root=processed_output_dir,
                                write_markdown=write_markdown,
                                write_label_studio_tasks=write_label_studio_tasks,
                                split_phase_slots=split_phase_slots,
                                split_phase_gate_dir=split_phase_gate_dir,
                                split_phase_status_label=split_phase_status_label,
                                scheduler_event_callback=scheduler_event_callback,
                                progress_callback=callback,
                                run_manifest_kind="bench_pred_run",
                            )
                        return run_labelstudio_import(
                            path=selected_source,
                            output_dir=output_dir,
                            pipeline=pipeline,
                            project_name=project_name,
                            segment_blocks=40,
                            segment_overlap=5,
                            overwrite=overwrite,
                            resume=not overwrite,
                            label_studio_url=url or "",
                            label_studio_api_key=api_key or "",
                            limit=None,
                            sample=None,
                            progress_callback=callback,
                            workers=workers,
                            pdf_split_workers=pdf_split_workers,
                            epub_split_workers=epub_split_workers,
                            pdf_pages_per_job=pdf_pages_per_job,
                            epub_spine_items_per_job=epub_spine_items_per_job,
                            epub_extractor=selected_epub_extractor,
                            epub_unstructured_html_parser_version=selected_html_parser_version,
                            epub_unstructured_skip_headers_footers=selected_skip_headers_footers,
                            epub_unstructured_preprocess_mode=selected_preprocess_mode,
                            ocr_device=selected_ocr_device,
                            ocr_batch_size=ocr_batch_size,
                            warm_models=warm_models,
                            llm_recipe_pipeline=selected_llm_recipe_pipeline,
                            codex_farm_cmd=codex_farm_cmd,
                            codex_farm_root=codex_farm_root,
                            codex_farm_workspace_root=codex_farm_workspace_root,
                            codex_farm_pipeline_pass1=selected_codex_farm_pipeline_pass1,
                            codex_farm_pipeline_pass2=selected_codex_farm_pipeline_pass2,
                            codex_farm_pipeline_pass3=selected_codex_farm_pipeline_pass3,
                            codex_farm_context_blocks=codex_farm_context_blocks,
                            codex_farm_failure_mode=selected_codex_farm_failure_mode,
                            processed_output_root=processed_output_dir,
                            split_phase_slots=split_phase_slots,
                            split_phase_gate_dir=split_phase_gate_dir,
                            split_phase_status_label=split_phase_status_label,
                            scheduler_event_callback=scheduler_event_callback,
                            auto_project_name_on_scope_mismatch=True,
                            allow_labelstudio_write=True,
                        )

                    def _run_prediction_stage_bundle() -> BenchmarkPredictionBundle:
                        prediction_phase_started = time.monotonic()
                        if suppress_spinner:
                            _emit_external_progress(
                                f"Generating prediction tasks for {selected_source.name}..."
                            )
                            callback = (
                                _emit_external_progress
                                if external_progress_callback is not None
                                else None
                            )
                            stage_import_result = _run_prediction_generation(callback)
                        else:
                            def _run_with_status(
                                update_progress: Callable[[str], None],
                            ) -> dict[str, Any]:
                                if external_progress_callback is None:
                                    return _run_prediction_generation(update_progress)

                                def _combined_progress(message: str) -> None:
                                    update_progress(message)
                                    _emit_external_progress(message)

                                return _run_prediction_generation(_combined_progress)

                            stage_import_result = _run_with_progress_status(
                                initial_status=(
                                    f"Generating prediction tasks for {selected_source.name}..."
                                ),
                                progress_prefix=f"Benchmark import ({selected_source.name})",
                                run=_run_with_status,
                            )
                        stage_prediction_seconds = max(
                            0.0, time.monotonic() - prediction_phase_started
                        )
                        return _build_prediction_bundle_from_import_result(
                            import_result=stage_import_result,
                            eval_output_dir=eval_output_dir,
                            prediction_phase_seconds=stage_prediction_seconds,
                        )

                    def _prewarm_evaluation_inputs() -> dict[str, Path] | None:
                        if selected_eval_mode != BENCHMARK_EVAL_MODE_CANONICAL_TEXT:
                            return None
                        canonical_paths = ensure_canonical_gold_artifacts(
                            export_root=selected_gold.parent
                        )
                        return {
                            "canonical_text_path": Path(
                                canonical_paths["canonical_text_path"]
                            ),
                            "canonical_span_labels_path": Path(
                                canonical_paths["canonical_span_labels_path"]
                            ),
                        }

                    if (
                        selected_execution_mode == BENCHMARK_EXECUTION_MODE_PIPELINED
                        and should_run_evaluation
                    ):
                        (
                            prediction_bundle,
                            prediction_records_output,
                            prewarmed_canonical_paths,
                        ) = run_pipelined(
                            run_prediction_bundle=_run_prediction_stage_bundle,
                            prewarm_evaluation_inputs=_prewarm_evaluation_inputs,
                            selected_source=selected_source,
                        )
                    else:
                        prediction_bundle, prediction_records_output = run_legacy(
                            run_prediction_bundle=_run_prediction_stage_bundle,
                            selected_source=selected_source,
                        )
        else:
            if predictions_in_path is None:
                _fail("Prediction record input is required.")
            prediction_bundle = _build_prediction_bundle_from_records(
                predictions_in=predictions_in_path,
                prediction_records=prediction_record_input,
                replay_output_dir=eval_output_dir / ".prediction-record-replay",
            )
            prediction_records_output = list(prediction_record_input)

        import_result = prediction_bundle.import_result
        pred_run = prediction_bundle.pred_run
        pred_context = prediction_bundle.pred_context
        stage_predictions_path = prediction_bundle.stage_predictions_path
        extracted_archive_path = prediction_bundle.extracted_archive_path
        prediction_phase_seconds = prediction_bundle.prediction_phase_seconds

        if predictions_out_path is not None:
            write_prediction_records(predictions_out_path, prediction_records_output)
    except Exception as exc:  # noqa: BLE001
        if suppress_summary:
            raise
        _fail(str(exc))

    if not should_run_evaluation:
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
                max(0.0, time.monotonic() - benchmark_started),
            ),
        )
        predict_only_run_config: dict[str, Any] = {
            "eval_mode": selected_eval_mode,
            "execution_mode": selected_execution_mode,
            "predict_only": True,
            "prediction_record_output": (
                str(predictions_out_path) if predictions_out_path is not None else None
            ),
            "upload": should_upload_predictions,
            "write_markdown": bool(write_markdown),
            "write_label_studio_tasks": bool(write_label_studio_tasks),
            "epub_extractor": selected_epub_extractor,
            "epub_unstructured_html_parser_version": selected_html_parser_version,
            "epub_unstructured_skip_headers_footers": selected_skip_headers_footers,
            "epub_unstructured_preprocess_mode": selected_preprocess_mode,
            "ocr_device": selected_ocr_device,
            "ocr_batch_size": ocr_batch_size,
            "workers": workers,
            "pdf_split_workers": pdf_split_workers,
            "epub_split_workers": epub_split_workers,
            "pdf_pages_per_job": pdf_pages_per_job,
            "epub_spine_items_per_job": epub_spine_items_per_job,
            "warm_models": warm_models,
            "llm_recipe_pipeline": selected_llm_recipe_pipeline,
            "codex_farm_cmd": codex_farm_cmd,
            "codex_farm_pipeline_pass1": selected_codex_farm_pipeline_pass1,
            "codex_farm_pipeline_pass2": selected_codex_farm_pipeline_pass2,
            "codex_farm_pipeline_pass3": selected_codex_farm_pipeline_pass3,
            "codex_farm_context_blocks": codex_farm_context_blocks,
            "codex_farm_failure_mode": selected_codex_farm_failure_mode,
            "stage_block_predictions_path": str(stage_predictions_path),
        }
        if codex_farm_root is not None:
            predict_only_run_config["codex_farm_root"] = str(codex_farm_root)
        if codex_farm_workspace_root is not None:
            predict_only_run_config["codex_farm_workspace_root"] = str(
                codex_farm_workspace_root
            )
        if pred_context.run_config is not None:
            predict_only_run_config["prediction_run_config"] = pred_context.run_config
        if pred_context.run_config_hash:
            predict_only_run_config["prediction_run_config_hash"] = (
                pred_context.run_config_hash
            )
        if pred_context.run_config_summary:
            predict_only_run_config["prediction_run_config_summary"] = (
                pred_context.run_config_summary
            )

        predict_only_artifacts: dict[str, Any] = {
            "pred_run_dir": _path_for_manifest(eval_output_dir, pred_run),
            "gold_spans_jsonl": _path_for_manifest(eval_output_dir, selected_gold),
            "stage_block_predictions_json": _path_for_manifest(
                eval_output_dir,
                stage_predictions_path,
            ),
            "timing": benchmark_timing,
        }
        if predictions_out_path is not None:
            predict_only_artifacts["prediction_record_output_jsonl"] = _path_for_manifest(
                eval_output_dir,
                predictions_out_path,
            )
        processed_report_path = import_result.get("processed_report_path")
        if processed_report_path:
            predict_only_artifacts["processed_report_json"] = _path_for_manifest(
                eval_output_dir,
                processed_report_path,
            )
        processed_run_root = import_result.get("processed_run_root")
        if processed_run_root:
            predict_only_artifacts["processed_output_run_dir"] = _path_for_manifest(
                eval_output_dir,
                processed_run_root,
            )

        _write_eval_run_manifest(
            run_root=eval_output_dir,
            run_kind="labelstudio_benchmark",
            source_path=str(selected_source),
            source_hash=pred_context.source_hash,
            importer_name=None,
            run_config=predict_only_run_config,
            artifacts=predict_only_artifacts,
            notes=(
                "Prediction stage complete; evaluation skipped "
                "(execution_mode=predict-only)."
            ),
        )
        if not suppress_summary:
            typer.secho(
                "Prediction stage complete; evaluation skipped (--execution-mode predict-only).",
                fg=typer.colors.CYAN,
            )
            typer.secho(f"Manifest: {eval_output_dir / 'run_manifest.json'}", fg=typer.colors.CYAN)
            if predictions_out_path is not None:
                typer.secho(
                    f"Prediction record: {predictions_out_path}",
                    fg=typer.colors.BRIGHT_BLACK,
                )
        return

    prediction_load_seconds: float | None = None
    gold_load_seconds: float | None = None
    eval_profile_min_seconds = _benchmark_eval_profile_min_seconds()
    eval_profile_top_n = _benchmark_eval_profile_top_n()
    eval_profiler: cProfile.Profile | None = None
    if eval_profile_min_seconds is not None:
        eval_profiler = cProfile.Profile()
    evaluation_started = time.monotonic()
    eval_scope = selected_eval_mode
    _notify_benchmark_scheduler_event(
        "evaluate_started",
        eval_mode=selected_eval_mode,
    )
    eval_status_message = (
        f"Evaluating predictions using {selected_eval_mode} scoring..."
    )

    def _evaluate_selected_mode() -> tuple[dict[str, Any], Callable[[dict[str, Any]], str]]:
        return evaluate_stage(
            selected_eval_mode=selected_eval_mode,
            selected_gold=selected_gold,
            eval_output_dir=eval_output_dir,
            stage_predictions_path=stage_predictions_path,
            extracted_archive_path=extracted_archive_path,
            alignment_cache_dir=alignment_cache_dir,
            prewarmed_canonical_paths=prewarmed_canonical_paths,
        )

    if eval_profiler is not None:
        eval_profiler.enable()
    try:
        if suppress_spinner:
            _emit_external_progress(eval_status_message)
            eval_result, eval_report_formatter = _evaluate_selected_mode()
        else:
            def _run_eval_with_status(
                update_progress: Callable[[str], None],
            ) -> tuple[dict[str, Any], Callable[[dict[str, Any]], str]]:
                if external_progress_callback is None:
                    update_progress(eval_status_message)
                    return _evaluate_selected_mode()

                def _combined_progress(message: str) -> None:
                    update_progress(message)
                    _emit_external_progress(message)

                _combined_progress(eval_status_message)
                return _evaluate_selected_mode()

            eval_result, eval_report_formatter = _run_with_progress_status(
                initial_status=eval_status_message,
                progress_prefix=f"Benchmark eval ({selected_source.name})",
                run=_run_eval_with_status,
            )
    finally:
        if eval_profiler is not None:
            eval_profiler.disable()
    evaluate_seconds = max(0.0, time.monotonic() - evaluation_started)
    evaluation_seconds = evaluate_seconds
    report = eval_result["report"]
    eval_profile_pstats_path: Path | None = None
    eval_profile_top_path: Path | None = None
    eval_profile_dump_seconds = 0.0
    eval_profile_captured = False
    if (
        eval_profiler is not None
        and eval_profile_min_seconds is not None
        and evaluate_seconds >= eval_profile_min_seconds
    ):
        profile_dump_started = time.monotonic()
        try:
            eval_profile_pstats_path = eval_output_dir / "eval_profile.pstats"
            eval_profile_top_path = eval_output_dir / "eval_profile_top.txt"
            eval_profiler.dump_stats(str(eval_profile_pstats_path))
            stats_stream = io.StringIO()
            stats = pstats.Stats(eval_profiler, stream=stats_stream)
            stats.sort_stats(pstats.SortKey.CUMULATIVE)
            stats.print_stats(eval_profile_top_n)
            eval_profile_top_path.write_text(stats_stream.getvalue(), encoding="utf-8")
            eval_profile_captured = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to write benchmark eval profile artifacts: %s", exc)
            eval_profile_pstats_path = None
            eval_profile_top_path = None
            eval_profile_captured = False
        finally:
            eval_profile_dump_seconds = max(
                0.0, time.monotonic() - profile_dump_started
            )

    if isinstance(report, dict):
        evaluation_telemetry_payload = report.get("evaluation_telemetry")
        if not isinstance(evaluation_telemetry_payload, dict):
            evaluation_telemetry_payload = {}
            report["evaluation_telemetry"] = evaluation_telemetry_payload
        profiling_payload: dict[str, Any] = {
            "enabled": eval_profile_min_seconds is not None,
            "captured": eval_profile_captured,
        }
        if eval_profile_min_seconds is not None:
            profiling_payload["threshold_seconds"] = float(eval_profile_min_seconds)
        profiling_payload["top_n"] = float(eval_profile_top_n)
        if eval_profile_dump_seconds > 0.0:
            profiling_payload["artifact_write_seconds"] = float(eval_profile_dump_seconds)
        if eval_profile_pstats_path is not None:
            profiling_payload["profile_pstats_path"] = str(eval_profile_pstats_path)
        if eval_profile_top_path is not None:
            profiling_payload["profile_top_path"] = str(eval_profile_top_path)
        evaluation_telemetry_payload["profiling"] = profiling_payload
        artifacts_payload = report.get("artifacts")
        if isinstance(artifacts_payload, dict):
            if eval_profile_pstats_path is not None:
                artifacts_payload["eval_profile_pstats"] = str(eval_profile_pstats_path)
            if eval_profile_top_path is not None:
                artifacts_payload["eval_profile_top"] = str(eval_profile_top_path)

    evaluation_telemetry = (
        report.get("evaluation_telemetry")
        if isinstance(report, dict)
        else None
    )
    telemetry_prediction_load, telemetry_gold_load = _evaluation_telemetry_load_seconds(
        evaluation_telemetry
    )
    if telemetry_prediction_load is not None:
        prediction_load_seconds = telemetry_prediction_load
    if telemetry_gold_load is not None:
        gold_load_seconds = telemetry_gold_load
    if prediction_load_seconds is None:
        prediction_load_seconds = 0.0
    if gold_load_seconds is None:
        gold_load_seconds = 0.0
    _notify_benchmark_scheduler_event(
        "evaluate_finished",
        eval_mode=selected_eval_mode,
        evaluate_seconds=evaluate_seconds,
        prediction_load_seconds=prediction_load_seconds,
        gold_load_seconds=gold_load_seconds,
        eval_profile_captured=eval_profile_captured,
        eval_profile_dump_seconds=eval_profile_dump_seconds,
    )

    benchmark_recipes = pred_context.recipes
    benchmark_recipes_source: str | None = (
        "prediction_run_context" if benchmark_recipes is not None else None
    )
    manifest_report_path = pred_context.processed_report_path
    processed_report_path = import_result.get("processed_report_path")
    csv_report_path = manifest_report_path
    if not csv_report_path and processed_report_path is not None:
        csv_report_path = str(processed_report_path)
    if benchmark_recipes is None and processed_report_path is not None:
        benchmark_recipes = _load_total_recipes_from_report_path(processed_report_path)
        if benchmark_recipes is not None:
            benchmark_recipes_source = "processed_report.totalRecipes"
    if benchmark_recipes is not None:
        recipe_counts = report.get("recipe_counts")
        if not isinstance(recipe_counts, dict):
            recipe_counts = {}
        recipe_counts["predicted_recipe_count"] = benchmark_recipes
        recipe_counts["predicted_recipe_count_source"] = benchmark_recipes_source
        report["recipe_counts"] = recipe_counts

    prediction_timing = _normalize_timing_payload(import_result.get("timing"))
    prediction_seconds = _report_optional_metric(
        prediction_timing.get("prediction_seconds")
    )
    if prediction_seconds is None:
        prediction_seconds = _report_optional_metric(prediction_timing.get("total_seconds"))
    if prediction_seconds is None:
        prediction_seconds = prediction_phase_seconds
    prediction_seconds_value = max(0.0, prediction_seconds)
    prediction_checkpoints = {}
    existing_prediction_checkpoints = prediction_timing.get("checkpoints")
    if isinstance(existing_prediction_checkpoints, dict):
        prediction_checkpoints.update(existing_prediction_checkpoints)
    prediction_checkpoints.update(
        {
            "prediction_load_seconds": prediction_load_seconds,
            "gold_load_seconds": gold_load_seconds,
            "evaluate_seconds": evaluate_seconds,
            "evaluate_profile_captured": 1.0 if eval_profile_captured else 0.0,
        }
    )
    if eval_profile_min_seconds is not None:
        prediction_checkpoints["evaluate_profile_threshold_seconds"] = max(
            0.0, float(eval_profile_min_seconds)
        )
    if eval_profile_dump_seconds > 0.0:
        prediction_checkpoints["evaluate_profile_artifact_write_seconds"] = max(
            0.0, eval_profile_dump_seconds
        )
    prediction_checkpoints.update(
        _evaluation_telemetry_checkpoints(evaluation_telemetry)
    )
    benchmark_timing = _timing_with_updates(
        prediction_timing,
        prediction_seconds=prediction_seconds,
        evaluation_seconds=evaluation_seconds,
        checkpoints=prediction_checkpoints,
    )
    report["timing"] = benchmark_timing
    report_json_path = eval_output_dir / "eval_report.json"
    report_md_path = eval_output_dir / "eval_report.md"
    artifact_write_seconds = max(0.0, eval_profile_dump_seconds)
    total_floor_with_artifacts = (
        prediction_seconds_value + max(0.0, evaluation_seconds) + artifact_write_seconds
    )
    benchmark_timing = _timing_with_updates(
        benchmark_timing,
        artifact_write_seconds=artifact_write_seconds,
        total_seconds=max(
            max(0.0, time.monotonic() - benchmark_started),
            total_floor_with_artifacts,
        ),
    )
    report["timing"] = benchmark_timing

    from cookimport.analytics.perf_report import append_benchmark_csv, history_path
    history_append_started = time.monotonic()
    csv_history_path = history_path(processed_output_dir)
    append_benchmark_csv(
        report,
        csv_history_path,
        run_timestamp=dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        run_dir=str(eval_output_dir),
        eval_scope=eval_scope,
        source_file=str(selected_source),
        recipes=benchmark_recipes,
        processed_report_path=csv_report_path,
        run_config=pred_context.run_config,
        run_config_hash=pred_context.run_config_hash,
        run_config_summary=pred_context.run_config_summary,
        timing=benchmark_timing,
    )
    if not suppress_summary:
        _refresh_dashboard_after_history_write(
            csv_path=csv_history_path,
            output_root=processed_output_dir,
            reason="labelstudio-benchmark history append",
        )
    history_append_seconds = max(0.0, time.monotonic() - history_append_started)
    total_floor_with_history = total_floor_with_artifacts + history_append_seconds
    benchmark_timing = _timing_with_updates(
        benchmark_timing,
        history_append_seconds=history_append_seconds,
        total_seconds=max(
            max(0.0, time.monotonic() - benchmark_started),
            total_floor_with_history,
        ),
        checkpoints={"history_csv_append_seconds": history_append_seconds},
    )
    report["timing"] = benchmark_timing
    report_md = eval_report_formatter(report)
    report_json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    report_md_path.write_text(report_md, encoding="utf-8")

    benchmark_run_config: dict[str, Any] = {
        "eval_mode": selected_eval_mode,
        "execution_mode": selected_execution_mode,
        "predict_only": False,
        "prediction_record_input": (
            str(predictions_in_path) if predictions_in_path is not None else None
        ),
        "prediction_record_output": (
            str(predictions_out_path) if predictions_out_path is not None else None
        ),
        "overlap_threshold": overlap_threshold,
        "force_source_match": force_source_match,
        "upload": should_upload_predictions,
        "write_markdown": bool(write_markdown),
        "write_label_studio_tasks": bool(write_label_studio_tasks),
        "epub_extractor": selected_epub_extractor,
        "epub_unstructured_html_parser_version": selected_html_parser_version,
        "epub_unstructured_skip_headers_footers": selected_skip_headers_footers,
        "epub_unstructured_preprocess_mode": selected_preprocess_mode,
        "ocr_device": selected_ocr_device,
        "ocr_batch_size": ocr_batch_size,
        "workers": workers,
        "pdf_split_workers": pdf_split_workers,
        "epub_split_workers": epub_split_workers,
        "pdf_pages_per_job": pdf_pages_per_job,
        "epub_spine_items_per_job": epub_spine_items_per_job,
        "warm_models": warm_models,
        "llm_recipe_pipeline": selected_llm_recipe_pipeline,
        "codex_farm_cmd": codex_farm_cmd,
        "codex_farm_pipeline_pass1": selected_codex_farm_pipeline_pass1,
        "codex_farm_pipeline_pass2": selected_codex_farm_pipeline_pass2,
        "codex_farm_pipeline_pass3": selected_codex_farm_pipeline_pass3,
        "codex_farm_context_blocks": codex_farm_context_blocks,
        "codex_farm_failure_mode": selected_codex_farm_failure_mode,
        "stage_block_predictions_path": str(stage_predictions_path),
    }
    if codex_farm_root is not None:
        benchmark_run_config["codex_farm_root"] = str(codex_farm_root)
    if codex_farm_workspace_root is not None:
        benchmark_run_config["codex_farm_workspace_root"] = str(
            codex_farm_workspace_root
        )
    if pred_context.run_config is not None:
        benchmark_run_config["prediction_run_config"] = pred_context.run_config
    if pred_context.run_config_hash:
        benchmark_run_config["prediction_run_config_hash"] = pred_context.run_config_hash
    if pred_context.run_config_summary:
        benchmark_run_config["prediction_run_config_summary"] = pred_context.run_config_summary

    benchmark_artifacts: dict[str, Any] = {
        "pred_run_dir": _path_for_manifest(eval_output_dir, pred_run),
        "gold_spans_jsonl": _path_for_manifest(eval_output_dir, selected_gold),
        "stage_block_predictions_json": _path_for_manifest(
            eval_output_dir,
            stage_predictions_path,
        ),
        "eval_report_json": "eval_report.json",
        "eval_report_md": "eval_report.md",
        "missed_gold_blocks_jsonl": "missed_gold_blocks.jsonl",
        "wrong_label_blocks_jsonl": "wrong_label_blocks.jsonl",
        "missed_gold_spans_jsonl": "missed_gold_spans.jsonl",
        "false_positive_preds_jsonl": "false_positive_preds.jsonl",
        "history_csv": str(history_csv_for_output(processed_output_dir)),
        "timing": benchmark_timing,
    }
    if predictions_in_path is not None:
        benchmark_artifacts["prediction_record_input_jsonl"] = _path_for_manifest(
            eval_output_dir,
            predictions_in_path,
        )
    if predictions_out_path is not None:
        benchmark_artifacts["prediction_record_output_jsonl"] = _path_for_manifest(
            eval_output_dir,
            predictions_out_path,
        )
    if eval_profile_pstats_path is not None and eval_profile_pstats_path.exists():
        benchmark_artifacts["eval_profile_pstats"] = _path_for_manifest(
            eval_output_dir,
            eval_profile_pstats_path,
        )
    if eval_profile_top_path is not None and eval_profile_top_path.exists():
        benchmark_artifacts["eval_profile_top"] = _path_for_manifest(
            eval_output_dir,
            eval_profile_top_path,
        )
    if selected_eval_mode == BENCHMARK_EVAL_MODE_CANONICAL_TEXT:
        gold_export_root = selected_gold.parent
        benchmark_artifacts["gold_export_root"] = _path_for_manifest(
            eval_output_dir,
            gold_export_root,
        )
        for artifact_name in (
            "canonical_text.txt",
            "canonical_span_labels.jsonl",
            "canonical_manifest.json",
        ):
            artifact_path = gold_export_root / artifact_name
            if artifact_path.exists():
                benchmark_artifacts[
                    artifact_name.replace(".", "_")
                ] = _path_for_manifest(eval_output_dir, artifact_path)
    if csv_report_path:
        benchmark_artifacts["processed_report_json"] = _path_for_manifest(
            eval_output_dir,
            csv_report_path,
        )
    processed_run_root = import_result.get("processed_run_root")
    if processed_run_root:
        benchmark_artifacts["processed_output_run_dir"] = _path_for_manifest(
            eval_output_dir,
            processed_run_root,
        )

    _write_eval_run_manifest(
        run_root=eval_output_dir,
        run_kind="labelstudio_benchmark",
        source_path=str(selected_source),
        source_hash=pred_context.source_hash,
        importer_name=None,
        run_config=benchmark_run_config,
        artifacts=benchmark_artifacts,
        notes=(
            "Benchmark evaluation against freeform gold using "
            f"{selected_eval_mode} scoring. "
            + (
                "Evaluate-only mode from prediction record."
                if predictions_in_path is not None
                else (
                    "Upload disabled."
                    if no_upload
                    else "Prediction tasks uploaded to Label Studio."
                )
            )
        ),
    )

    if not suppress_summary:
        typer.secho("Benchmark complete.", fg=typer.colors.GREEN)
        typer.secho(f"Gold spans: {selected_gold}", fg=typer.colors.CYAN)
        typer.secho(f"Prediction run: {pred_run}", fg=typer.colors.CYAN)
        if processed_run_root:
            typer.secho(f"Processed output: {processed_run_root}", fg=typer.colors.CYAN)
        if selected_eval_mode == BENCHMARK_EVAL_MODE_CANONICAL_TEXT:
            typer.secho(
                "Overall line accuracy: "
                f"{float(report.get('overall_line_accuracy') or 0.0):.3f}",
                fg=typer.colors.CYAN,
            )
        else:
            typer.secho(
                "Overall block accuracy: "
                f"{float(report.get('overall_block_accuracy') or 0.0):.3f}",
                fg=typer.colors.CYAN,
            )
        typer.secho(
            "Macro F1 (excluding OTHER): "
            f"{float(report.get('macro_f1_excluding_other') or 0.0):.3f}",
            fg=typer.colors.CYAN,
        )
        worst_label_payload = report.get("worst_label_recall")
        if isinstance(worst_label_payload, dict):
            worst_label = str(worst_label_payload.get("label") or "").strip()
            worst_recall = float(worst_label_payload.get("recall") or 0.0)
            if worst_label:
                typer.secho(
                    f"Worst-label recall: {worst_label} {worst_recall:.3f}",
                    fg=typer.colors.YELLOW,
                )
        typer.secho(f"Report: {report_md_path}", fg=typer.colors.CYAN)
        recipe_counts = report.get("recipe_counts")
        if isinstance(recipe_counts, dict):
            predicted_recipe_count = _coerce_int(recipe_counts.get("predicted_recipe_count"))
            if predicted_recipe_count is not None:
                typer.secho(
                    f"Predicted recipes from import: {predicted_recipe_count}",
                    fg=typer.colors.CYAN,
                )


@bench_app.command("validate")
def bench_validate(
    suite: Path = typer.Option(
        ..., "--suite", help="Path to bench suite JSON file."
    ),
) -> None:
    """Validate a bench suite manifest (check source files and gold dirs exist)."""
    from cookimport.bench.suite import load_suite, validate_suite

    try:
        s = load_suite(suite)
    except Exception as exc:  # noqa: BLE001
        _fail(f"Failed to load suite: {exc}")

    errors = validate_suite(s, REPO_ROOT)
    if errors:
        typer.secho("Validation errors:", fg=typer.colors.RED)
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho(
        f"Suite '{s.name}' is valid ({len(s.items)} item(s)).",
        fg=typer.colors.GREEN,
    )


@bench_app.command("eval-stage")
def bench_eval_stage(
    gold_spans: Path = typer.Option(
        ...,
        "--gold-spans",
        help="Path to exported freeform_span_labels.jsonl gold file.",
    ),
    stage_run: Path = typer.Option(
        ...,
        "--stage-run",
        help="Path to a stage run directory (for example data/output/<timestamp>).",
    ),
    workbook_slug: str | None = typer.Option(
        None,
        "--workbook-slug",
        help="Workbook folder name under .bench (required when stage run contains multiple workbooks).",
    ),
    extracted_archive: Path | None = typer.Option(
        None,
        "--extracted-archive",
        help="Optional extracted archive JSON path. Defaults to stage run raw/**/full_text.json when unique.",
    ),
    out_dir: Path | None = typer.Option(
        None,
        "--out-dir",
        help="Output directory for eval artifacts. Defaults to data/golden/benchmark/<timestamp>/.",
    ),
) -> None:
    if not gold_spans.exists() or not gold_spans.is_file():
        _fail(f"Gold spans file not found: {gold_spans}")
    if not stage_run.exists() or not stage_run.is_dir():
        _fail(f"Stage run folder not found: {stage_run}")

    stage_prediction_files = sorted(
        stage_run.glob(".bench/*/stage_block_predictions.json")
    )
    if not stage_prediction_files:
        _fail(
            "No stage block prediction manifests found under "
            f"{stage_run / '.bench'}."
        )

    stage_predictions_path: Path
    if workbook_slug:
        stage_predictions_path = (
            stage_run / ".bench" / workbook_slug / "stage_block_predictions.json"
        )
        if not stage_predictions_path.exists():
            _fail(
                "Stage block predictions not found for workbook "
                f"{workbook_slug}: {stage_predictions_path}"
            )
    elif len(stage_prediction_files) == 1:
        stage_predictions_path = stage_prediction_files[0]
    else:
        choices = ", ".join(path.parent.name for path in stage_prediction_files)
        _fail(
            "Stage run contains multiple workbooks. "
            f"Pass --workbook-slug. Choices: {choices}"
        )

    extracted_archive_path = extracted_archive
    if extracted_archive_path is None:
        candidates = sorted(stage_run.glob("raw/**/full_text.json"))
        if len(candidates) == 1:
            extracted_archive_path = candidates[0]
        else:
            _fail(
                "Could not auto-resolve extracted archive. "
                "Pass --extracted-archive explicitly."
            )
    if not extracted_archive_path.exists() or not extracted_archive_path.is_file():
        _fail(f"Extracted archive not found: {extracted_archive_path}")

    if out_dir is None:
        out_dir = _golden_benchmark_root() / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = evaluate_stage_blocks(
            gold_freeform_jsonl=gold_spans,
            stage_predictions_json=stage_predictions_path,
            extracted_blocks_json=extracted_archive_path,
            out_dir=out_dir,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    report = result.get("report") if isinstance(result, dict) else {}
    typer.secho("Stage evaluation complete.", fg=typer.colors.GREEN)
    typer.secho(f"Stage predictions: {stage_predictions_path}", fg=typer.colors.CYAN)
    typer.secho(f"Report: {out_dir / 'eval_report.md'}", fg=typer.colors.CYAN)
    typer.secho(
        "Overall block accuracy: "
        f"{float((report or {}).get('overall_block_accuracy') or 0.0):.3f}",
        fg=typer.colors.CYAN,
    )
    typer.secho(
        "Macro F1 (excluding OTHER): "
        f"{float((report or {}).get('macro_f1_excluding_other') or 0.0):.3f}",
        fg=typer.colors.CYAN,
    )


@bench_app.command("run")
def bench_run(
    suite: Path = typer.Option(
        ..., "--suite", help="Path to bench suite JSON file."
    ),
    out_dir: Path = typer.Option(
        DEFAULT_BENCH_RUNS,
        "--out-dir",
        help="Output directory for bench runs.",
    ),
    baseline: Path | None = typer.Option(
        None, "--baseline", help="Previous run directory to compute deltas against."
    ),
    config_path: Path | None = typer.Option(
        None, "--config", help="Knob config JSON file."
    ),
) -> None:
    """Run the offline benchmark suite: generate predictions, evaluate, report."""
    from cookimport.bench.packet import build_iteration_packet
    from cookimport.bench.runner import run_suite
    from cookimport.bench.suite import load_suite, validate_suite

    try:
        s = load_suite(suite)
    except Exception as exc:  # noqa: BLE001
        _fail(f"Failed to load suite: {exc}")

    errors = validate_suite(s, REPO_ROOT)
    if errors:
        typer.secho("Suite validation errors:", fg=typer.colors.RED)
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED)
        raise typer.Exit(1)

    config: dict | None = None
    if config_path and config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))

    try:
        run_root, agg_metrics = _run_with_progress_status(
            initial_status="Running bench suite...",
            progress_prefix="Bench",
            run=lambda update_progress: run_suite(
                s,
                out_dir,
                repo_root=REPO_ROOT,
                config=config,
                baseline_run_dir=baseline,
                progress_callback=update_progress,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    # Build iteration packet
    build_iteration_packet(run_root, baseline_run_dir=baseline)
    bench_recipe_total = _sum_bench_recipe_count(run_root)

    from cookimport.analytics.perf_report import append_benchmark_csv, history_path
    csv_history_path = history_path(DEFAULT_OUTPUT)
    append_benchmark_csv(
        agg_metrics,
        csv_history_path,
        run_timestamp=run_root.name,
        run_dir=str(run_root),
        eval_scope="bench-suite",
        source_file=s.name,
        recipes=bench_recipe_total,
        run_config=config,
    )
    _refresh_dashboard_after_history_write(
        csv_path=csv_history_path,
        output_root=DEFAULT_OUTPUT,
        reason="bench run history append",
    )

    typer.secho("Bench suite complete.", fg=typer.colors.GREEN)
    typer.secho(f"Report: {run_root / 'report.md'}", fg=typer.colors.CYAN)
    typer.secho(f"Metrics: {run_root / 'metrics.json'}", fg=typer.colors.CYAN)
    typer.secho(f"Packet: {run_root / 'iteration_packet'}", fg=typer.colors.CYAN)


@bench_app.command("sweep")
def bench_sweep(
    suite: Path = typer.Option(
        ..., "--suite", help="Path to bench suite JSON file."
    ),
    out_dir: Path = typer.Option(
        DEFAULT_BENCH_RUNS,
        "--out-dir",
        help="Output directory for sweep runs.",
    ),
    budget: int = typer.Option(
        25, "--budget", min=1, help="Max number of sweep configurations to try."
    ),
    seed: int = typer.Option(42, "--seed", help="Random seed for sweep."),
    objective: str = typer.Option(
        "coverage", "--objective", help="Optimization objective (coverage or precision)."
    ),
) -> None:
    """Run a parameter sweep over the bench suite."""
    from cookimport.bench.suite import load_suite, validate_suite
    from cookimport.bench.sweep import run_sweep

    try:
        s = load_suite(suite)
    except Exception as exc:  # noqa: BLE001
        _fail(f"Failed to load suite: {exc}")

    errors = validate_suite(s, REPO_ROOT)
    if errors:
        typer.secho("Suite validation errors:", fg=typer.colors.RED)
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        sweep_root = _run_with_progress_status(
            initial_status="Running parameter sweep...",
            progress_prefix="Sweep",
            run=lambda update_progress: run_sweep(
                s,
                out_dir,
                repo_root=REPO_ROOT,
                budget=budget,
                seed=seed,
                objective=objective,
                progress_callback=update_progress,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    typer.secho("Sweep complete.", fg=typer.colors.GREEN)
    typer.secho(f"Results: {sweep_root}", fg=typer.colors.CYAN)


@bench_app.command("knobs")
def bench_knobs() -> None:
    """List all tunable knobs and their defaults."""
    from cookimport.bench.knobs import list_knobs

    knobs = list_knobs()
    if not knobs:
        typer.echo("No tunable knobs registered.")
        return
    for knob in knobs:
        bounds = f" bounds={knob.bounds}" if knob.bounds else ""
        choices = f" choices={list(knob.choices)}" if knob.choices else ""
        typer.echo(
            f"  {knob.name} ({knob.kind}) default={knob.default}{bounds}{choices}"
        )
        if knob.description:
            typer.secho(f"    {knob.description}", fg=typer.colors.BRIGHT_BLACK)


if __name__ == "__main__":
    app()
