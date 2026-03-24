from __future__ import annotations

import importlib
import json
import logging
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import format_stage_progress
from cookimport.core.models import ConversionResult, ParsingOverrides
from cookimport.parsing.label_source_of_truth import RecipeSpan
from cookimport.runs import (
    KNOWLEDGE_MANIFEST_FILE_NAME,
    stage_artifact_stem,
)
from cookimport.staging.nonrecipe_stage import (
    NonRecipeStageResult,
    refine_nonrecipe_stage_result,
)
from cookimport.staging.writer import (
    NONRECIPE_AUTHORITY_FILE_NAME,
    NONRECIPE_REVIEW_STATUS_FILE_NAME,
    NONRECIPE_SEED_ROUTING_FILE_NAME,
)

from ..codex_farm_ids import sanitize_for_filename
from ..codex_farm_knowledge_ingest import (
    classify_knowledge_validation_failure,
    extract_promotable_knowledge_bundle,
    normalize_knowledge_worker_payload,
    read_validated_knowledge_outputs_from_proposals,
    validate_knowledge_shard_output,
)
from ..codex_farm_knowledge_models import (
    ALLOWED_KNOWLEDGE_FINAL_CATEGORIES,
    ALLOWED_KNOWLEDGE_REASON_CODES,
    ALLOWED_KNOWLEDGE_REVIEWER_CATEGORIES,
)
from ..codex_farm_knowledge_jobs import (
    build_knowledge_jobs,
)
from ..codex_farm_knowledge_writer import KnowledgeWriteReport, write_knowledge_artifacts
from ..codex_exec_runner import (
    DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
    CodexExecLiveSnapshot,
    CodexExecRunResult,
    CodexExecRunner,
    CodexExecSupervisionDecision,
    SubprocessCodexExecRunner,
    assess_final_agent_message,
    classify_workspace_worker_command,
    detect_workspace_worker_boundary_violation,
    format_watchdog_command_reason_detail,
    format_watchdog_command_loop_reason_detail,
    should_terminate_workspace_command_loop,
    summarize_direct_telemetry_rows,
)
from ..codex_farm_runner import (
    CodexFarmRunnerError,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)
from ..knowledge_workspace_tools import (
    build_current_batch_payload,
    build_workspace_inventory_task_row,
    check_workspace_draft,
    current_task_draft_path,
    resolve_current_task_row,
    scaffold_task_payload,
    write_current_batch_and_task_sidecars,
    write_current_task_sidecars,
    write_current_task_scaffold,
    write_knowledge_workspace_sidecars,
)
from ..knowledge_prompt_builder import build_knowledge_direct_prompt
from ..phase_worker_runtime import (
    PhaseManifestV1,
    ShardManifestEntryV1,
    ShardProposalV1,
    TaskManifestEntryV1,
    WorkerAssignmentV1,
    WorkerExecutionReportV1,
    resolve_phase_worker_count,
)
from ..worker_hint_sidecars import preview_text, write_worker_hint_markdown

from .reporting import (
    _aggregate_worker_runner_payload,
    _build_knowledge_review_rollup,
    _build_review_summary,
    _derive_knowledge_authority_mode,
    _derive_knowledge_review_status,
    _load_json_dict,
    _runtime_artifact_paths,
    _summarize_direct_rows,
    _summarize_knowledge_workspace_relaunches,
    _write_json,
    _write_jsonl,
    _write_knowledge_runtime_summary_artifacts,
    _write_optional_text,
)

logger = logging.getLogger(__name__)

COMPACT_KNOWLEDGE_PIPELINE_ID = "recipe.knowledge.compact.v1"
DEFAULT_KNOWLEDGE_PIPELINE_ID = COMPACT_KNOWLEDGE_PIPELINE_ID
_KNOWLEDGE_RETRY_MAX_CHUNKS_PER_SHARD = 1
_KNOWLEDGE_RETRY_MAX_CHARS_PER_SHARD = 6000
_KNOWLEDGE_PATHOLOGICAL_WHITESPACE_RUN = 4096
_KNOWLEDGE_PATHOLOGICAL_CHARS_PER_RETURNED_ROW = 12000
_STRICT_JSON_WATCHDOG_POLICY = "strict_json_no_tools_v1"
_KNOWLEDGE_COHORT_WATCHDOG_MIN_COMPLETED_SHARDS = 3
_KNOWLEDGE_COHORT_WATCHDOG_MIN_ELAPSED_MS = 1_000
_KNOWLEDGE_COHORT_WATCHDOG_MEDIAN_FACTOR = 4.0
_KNOWLEDGE_COHORT_WATCHDOG_MAX_EXAMPLES = 2
_KNOWLEDGE_WATCHDOG_RETRY_SILENCE_TIMEOUT_SECONDS = 90
_KNOWLEDGE_WATCHDOG_RETRY_TIMEOUT_SECONDS = 300
_KNOWLEDGE_WORKSPACE_OUTPUT_STABLE_PASSES = 2
_KNOWLEDGE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS = 2.0
_KNOWLEDGE_WORKSPACE_PROGRESS_GRACE_COMMANDS = 24
_KNOWLEDGE_WORKSPACE_PREMATURE_EXIT_MAX_RELAUNCHES = 2
_KNOWLEDGE_TASK_STATUS_FILE_NAME = "task_status.jsonl"
_KNOWLEDGE_STAGE_STATUS_FILE_NAME = "stage_status.json"
_KNOWLEDGE_TASK_STATUS_SCHEMA_VERSION = "knowledge_task_status.v1"
_KNOWLEDGE_STAGE_STATUS_SCHEMA_VERSION = "knowledge_stage_status.v1"
_KNOWLEDGE_SCRATCH_DIR_NAME = "scratch"
_KNOWLEDGE_POISONED_WORKER_MIN_FAILURES = 2
_KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_ATTEMPTS = 3
_KNOWLEDGE_FOLLOWUP_CIRCUIT_BREAKER_MIN_SUCCESS_RATE = 0.25
_KNOWLEDGE_DETERMINISTIC_BYPASS_WORKER_ID = "deterministic-bypass"
_KNOWLEDGE_REPAIRABLE_NEAR_MISS_ERRORS = frozenset(
    {
        "response_json_invalid",
        "response_not_json_object",
        "schema_invalid",
        "missing_owned_chunk_results",
        "unexpected_chunk_results",
        "chunk_result_order_mismatch",
    }
)

for _module_name in ("planning", "promotion", "recovery", "runtime"):
    _module = importlib.import_module(f"{__package__}.{_module_name}")
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )

