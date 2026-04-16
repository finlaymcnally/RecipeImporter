from __future__ import annotations
import base64
import binascii
import hashlib
import json
import os
import re
import shlex
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Protocol
from cookimport.config.runtime_support import resolve_prelabel_cache_dir
from cookimport.llm.codex_farm_runner import (
    CodexFarmRunner,
    SubprocessCodexFarmRunner,
    as_pipeline_run_result_payload,
    ensure_codex_farm_pipelines_exist,
)
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABELS,
    FREEFORM_LABEL_CONTROL_NAME,
    FREEFORM_LABEL_RESULT_TYPE,
    FREEFORM_TEXT_NAME,
    normalize_freeform_label,
)
from . import prelabel_codex as _prelabel_codex_module
from . import prelabel_prompt as _prelabel_prompt_module
_MODEL_CONFIG_LINE_RE = re.compile(r"^\s*model\s*=\s*['\"]([^'\"]+)['\"]\s*$")
_MODEL_REASONING_EFFORT_CONFIG_LINE_RE = re.compile(
    r"^\s*model_reasoning_effort\s*=\s*['\"]([^'\"]+)['\"]\s*$"
)
_CODEX_EXECUTABLES = {"codex", "codex.exe", "codex2", "codex2.exe"}
_CODEX_ALT_EXECUTABLE_RE = re.compile(r"^codex[0-9]+(?:\.exe)?$")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_PRELABEL_CODEX_FARM_PIPELINE_ID = "prelabel.freeform.v1"
_PRELABEL_CODEX_FARM_DEFAULT_CMD = "codex-farm"
_PROMPT_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_FULL_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-full.prompt.md"
_SPAN_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-span.prompt.md"
_PROMPT_TEMPLATE_CACHE: dict[Path, tuple[int, str]] = {}
PRELABEL_GRANULARITY_SPAN = "span"
CODEX_REASONING_EFFORT_VALUES = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
_RATE_LIMIT_MESSAGE_RE = re.compile(
    r"\b429\b|too many requests|rate[ -]?limit(?:ed|ing)?",
    re.IGNORECASE,
)
from .prelabel_codex import (
    LlmProvider,
    CodexFarmProvider as _CodexFarmProviderImpl,
    normalize_prelabel_granularity,
    normalize_codex_reasoning_effort,
    _normalize_codex_error_detail,
    is_rate_limit_message,
    _argv_with_json_events,
    _is_codex_executable,
    _split_command_env_and_argv,
    _extract_config_override_value,
    _extract_model_from_config_override,
    _extract_reasoning_effort_from_config_override,
    _dedupe_paths,
    _codex_home_roots,
    _codex_config_paths,
    _codex_models_cache_paths,
    _codex_auth_paths,
    _decode_jwt_claims,
    _claims_email,
    _claims_plan,
    codex_account_info,
    codex_account_summary,
    _argv_has_model_setting,
    _argv_has_reasoning_effort_setting,
    codex_cmd_with_model,
    codex_cmd_with_reasoning_effort,
    codex_model_from_cmd,
    codex_reasoning_effort_from_cmd,
    default_codex_model,
    default_codex_reasoning_effort,
    default_codex_reasoning_effort_for_model,
    _supported_reasoning_efforts_from_model_row,
    list_codex_models,
    resolve_codex_model,
    _resolve_codex_farm_root,
    _resolve_codex_farm_workspace_root,
    _ensure_prelabel_codex_farm_pipeline,
    _coerce_int,
    _codex_farm_return_code,
    _codex_farm_usage_payload,
    run_codex_farm_json_prompt,
    preflight_codex_model_access as _preflight_codex_model_access_impl,
    default_codex_cmd,
)
from .prelabel_parse import (
    extract_first_json_value,
    parse_span_label_output,
)
from .prelabel_mapping import (
    annotation_labels,
    _extract_task_data,
    _build_row_map,
    _resolve_focus_row_index_set,
    _build_results_for_span_mode,
)
from .prelabel_prompt import (
    _load_prompt_template,
    _render_prompt_template,
    _collapse_row_index_ranges,
    _build_focus_marked_row_lines,
    _extract_valid_rows_from_segment_text,
    _extract_prompt_context_rows,
    _build_prompt,
    _build_prompt_log_entry,
)

_PROMPT_TEMPLATE_CACHE = _prelabel_prompt_module._PROMPT_TEMPLATE_CACHE


class CodexFarmProvider(_CodexFarmProviderImpl):
    def complete(self, prompt: str) -> str:
        _prelabel_codex_module.run_codex_farm_json_prompt = run_codex_farm_json_prompt
        return super().complete(prompt)


def preflight_codex_model_access(*, cmd: str, timeout_s: int) -> None:
    _prelabel_codex_module.run_codex_farm_json_prompt = run_codex_farm_json_prompt
    _preflight_codex_model_access_impl(cmd=cmd, timeout_s=timeout_s)

def prelabel_freeform_task(
    task: dict[str, Any],
    *,
    provider: LlmProvider,
    allowed_labels: set[str] | None = None,
    prelabel_granularity: str = PRELABEL_GRANULARITY_SPAN,
    prompt_log_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Generate one Label Studio annotation from LLM prelabel suggestions."""
    normalized_allowed = {
        normalize_freeform_label(label)
        for label in (allowed_labels or set(FREEFORM_ALLOWED_LABELS))
    }
    normalized_allowed = {
        label for label in normalized_allowed if label in FREEFORM_ALLOWED_LABELS
    }
    if not normalized_allowed:
        raise ValueError("allowed_labels cannot be empty")
    normalized_granularity = normalize_prelabel_granularity(prelabel_granularity)

    segment_id, segment_text, source_blocks = _extract_task_data(task)
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError("task missing data object")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing data.source_map")
    focus_row_indices = _resolve_focus_row_index_set(
        source_map=source_map,
        source_blocks=source_blocks,
    )
    if not focus_row_indices:
        raise ValueError("task source_map has no valid focus row indices")

    row_map = _build_row_map(task)
    if not row_map:
        raise ValueError("task source_map has no valid row offsets")

    _prelabel_prompt_module._FULL_PROMPT_TEMPLATE_PATH = _FULL_PROMPT_TEMPLATE_PATH
    _prelabel_prompt_module._SPAN_PROMPT_TEMPLATE_PATH = _SPAN_PROMPT_TEMPLATE_PATH
    _prelabel_prompt_module._PROMPT_TEMPLATE_CACHE = _PROMPT_TEMPLATE_CACHE
    _prelabel_codex_module.run_codex_farm_json_prompt = run_codex_farm_json_prompt
    prompt = _build_prompt(
        task=task,
        allowed_labels=normalized_allowed,
        prelabel_granularity=normalized_granularity,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    if prompt_log_callback is not None:
        prompt_log_callback(
            _build_prompt_log_entry(
                task=task,
                prompt=prompt,
                prompt_hash=prompt_hash,
                allowed_labels=normalized_allowed,
                prelabel_granularity=normalized_granularity,
                focus_row_indices=focus_row_indices,
                provider=provider,
            )
        )

    raw = provider.complete(prompt)
    payload = extract_first_json_value(raw)
    raw_was_empty_array = isinstance(payload, list) and not payload
    selections = parse_span_label_output(raw)
    generated = _build_results_for_span_mode(
        selections=selections,
        segment_id=segment_id,
        segment_text=segment_text,
        row_map=row_map,
        source_blocks=source_blocks,
        focus_row_indices=focus_row_indices,
        allowed_labels=normalized_allowed,
    )

    if not generated:
        if raw_was_empty_array:
            return {
                "result": [],
                "meta": {
                    "cookimport_prelabel": True,
                    "mode": "empty",
                    "provider": provider.__class__.__name__,
                    "prompt_hash": prompt_hash,
                    "granularity": normalized_granularity,
                },
            }
        return None

    return {
        "result": generated,
        "meta": {
            "cookimport_prelabel": True,
            "mode": "full",
            "provider": provider.__class__.__name__,
            "prompt_hash": prompt_hash,
            "granularity": normalized_granularity,
        },
    }
