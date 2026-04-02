from __future__ import annotations
import functools
import json
from pathlib import Path
from typing import Any, Mapping
import tiktoken
from cookimport.llm.codex_exec_runner import summarize_direct_telemetry_rows
from cookimport.llm.fake_codex_farm_runner import build_structural_pipeline_output
from cookimport.llm.shard_survivability import evaluate_stage_survivability
from cookimport.runs.stage_names import canonical_stage_key, stage_label
from cookimport.runs.stage_observability import (
    build_knowledge_stage_summary,
    build_line_role_stage_summary as build_stage_observability_line_role_summary,
    build_recipe_stage_summary,
)
_TOKEN_KEYS = (
    "tokens_input",
    "tokens_cached_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_total",
)
_BREAKDOWN_KEYS = (
    "visible_input_tokens",
    "visible_output_tokens",
    "wrapper_overhead_tokens",
)
_PATHOLOGY_KEYS = (
    "preflight_rejected_shard_count",
    "watchdog_killed_shard_count",
    "watchdog_recovered_shard_count",
    "command_execution_count_total",
    "command_executing_shard_count",
    "command_execution_tokens_total",
    "reasoning_item_count_total",
    "reasoning_heavy_shard_count",
    "reasoning_heavy_tokens_total",
    "invalid_output_shard_count",
    "invalid_output_tokens_total",
    "repaired_shard_count",
    "pathological_shard_count",
)
_STATUS_COUNT_KEYS = (
    "validated_shard_count",
    "invalid_shard_count",
    "no_final_output_shard_count",
    "missing_output_shard_count",
)
_EXECUTION_MODE_COUNT_KEYS = (
    "taskfile_session_count",
    "structured_followup_call_count",
    "structured_followup_tokens_total",
)
_PREVIEW_STAGE_LABELS = {
    "recipe_refine": stage_label("recipe_refine"),
    "nonrecipe_finalize": stage_label("nonrecipe_finalize"),
    "line_role": stage_label("line_role"),
}
_SURFACE_CONFIG_BY_KEY = {
    "recipe": {
        "prompt_target_key": "recipe_prompt_target_count",
        "worker_key": "recipe_worker_count",
    },
    "knowledge": {
        "prompt_target_key": "knowledge_prompt_target_count",
        "worker_key": "knowledge_worker_count",
    },
    "line_role": {
        "prompt_target_key": "line_role_prompt_target_count",
        "worker_key": "line_role_worker_count",
    },
}

from .prompt_budget_runtime import (
    _normalize_prompt_budget_stage_key,
    build_prediction_run_prompt_budget_summary,
    write_prediction_run_prompt_budget_summary,
    _build_codex_farm_stage_summary,
    _execution_mode_summary_from_telemetry_rows,
    _candidate_stage_root_paths,
    _attach_knowledge_stage_observability,
    _attach_recipe_stage_observability,
    _extract_telemetry_rows,
    _build_line_role_stage_summary,
    _prediction_run_config,
    _surface_key_for_stage,
    _stage_requested_counts,
    _extract_runtime_worker_and_shard_counts,
    _common_int_value,
    _extract_stage_shard_status_counts,
    _pathological_flags_from_summary_payload,
    _build_stage_run_count_summary,
    _iter_line_role_telemetry_paths,
    _extract_summary_payload,
    _collect_atomic_summary_payloads,
    _extract_call_count,
    _extract_duration_total_ms,
    _extract_duration_total_ms_from_rows,
    _collect_telemetry_rows_from_worker_children,
    _collect_summary_payloads,
    _collect_line_role_attempt_summaries,
    _preferred_summary_payloads,
    _looks_like_summary_payload,
    _summary_payload_score,
    _aggregate_token_totals_from_summaries,
    _aggregate_breakdown_totals_from_summaries,
    _aggregate_call_count_from_summaries,
    _aggregate_duration_total_ms_from_summaries,
    _summary_has_any_token_usage,
    _summary_has_any_token_fields,
    _summary_looks_like_missing_token_usage,
    _nonnegative_int,
    _nonnegative_float,
    _sum_optional_ints,
    _rows_for_stage,
)
from .prompt_budget_preview import (
    build_prompt_preview_budget_summary,
    write_prompt_preview_budget_summary,
    _build_structural_stage_estimate,
    _build_preview_stage_survivability,
    _count_structural_input_tokens,
    _count_structural_output_tokens,
    _count_tokens,
    _count_tokens_cached,
    _chunk_tokenization_text,
    _encoding_for_model,
    _tokenizer_name_for_model,
    _build_prompt_preview_budget_warnings,
    _render_prompt_preview_budget_summary_md,
)
