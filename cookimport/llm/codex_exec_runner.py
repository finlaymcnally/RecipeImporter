from __future__ import annotations

import ast
import hashlib
import json
import queue
import re
import shutil
import shlex
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import tiktoken

from cookimport.config.runtime_support import (
    resolve_completed_termination_grace_seconds,
    workspace_allowed_temp_roots,
    workspace_fs_cage_mktemp_template,
)
from .codex_farm_runner import (
    CodexFarmRunnerError,
    _merge_env,
    _resolve_recipeimport_codex_home,
)
from .editable_task_file import (
    TASK_FILE_NAME,
    TASK_FILE_SCHEMA_VERSION,
    load_task_file,
    write_task_file,
)
from .knowledge_same_session_handoff import (
    KNOWLEDGE_SAME_SESSION_STATE_ENV,
    advance_knowledge_same_session_handoff,
)
from .codex_exec_telemetry import (
    _coerce_nonnegative_int,
    _extract_last_agent_message,
    _extract_turn_completed_usage,
    _extract_turn_failed_message,
    _extract_usage_from_text_streams,
    _normalize_usage,
    _parse_codex_json_events,
    _parse_codex_json_line,
    _pathological_flags_for_row,
    _row_has_any_token_usage,
    _row_looks_like_missing_token_usage,
    _summarize_codex_events,
    _summarize_failure_text,
    _summarize_live_activity,
    _summarize_live_codex_events,
    _summary_pathological_flags,
    _sum_ints,
    _token_usage_status_from_direct_rows,
    _usage_missing_or_zero,
    assess_final_agent_message,
    format_watchdog_command_reason_detail,
    format_watchdog_command_loop_reason_detail,
    should_terminate_workspace_command_loop,
    summarize_direct_telemetry_rows,
)
from . import codex_exec_command_builder as _command_builder_module
from .recipe_same_session_handoff import (
    RECIPE_SAME_SESSION_STATE_ENV,
    advance_recipe_same_session_handoff,
)
from .single_file_worker_commands import (
    TASK_ANSWER_CURRENT_COMMAND,
    TASK_APPLY_COMMAND,
    TASK_DOCTOR_COMMAND,
    TASK_HANDOFF_COMMAND,
    TASK_NEXT_COMMAND,
    TASK_SHOW_CURRENT_COMMAND,
    TASK_SHOW_NEIGHBORS_COMMAND,
    TASK_SHOW_UNANSWERED_COMMAND,
    TASK_SHOW_UNIT_COMMAND,
    TASK_STATUS_COMMAND,
    TASK_SUMMARY_COMMAND,
    TASK_TEMPLATE_COMMAND,
)
from .codex_exec_types import (
    CodexExecLiveSnapshot,
    CodexExecRecentCommandCompletion,
    CodexExecRunner,
    CodexExecSupervisionDecision,
    DirectExecWorkerContract,
    DirectExecWorkspaceMode,
    FinalAgentMessageAssessment,
    FinalAgentMessageState,
    WorkspaceCommandClassification,
)

DIRECT_CODEX_EXEC_RUNTIME_MODE_V1 = "direct_codex_exec_v1"
_DIRECT_EXEC_ISOLATION_ROOT_NAME = "recipeimport-direct-exec-workspaces"
_DIRECT_EXEC_AGENTS_FILE_NAME = "AGENTS.md"
_DIRECT_EXEC_INPUT_DIR_NAME = "in"
_DIRECT_EXEC_DEBUG_DIR_NAME = "debug"
_DIRECT_EXEC_HINTS_DIR_NAME = "hints"
_DIRECT_EXEC_LOGS_DIR_NAME = "logs"
_DIRECT_EXEC_SHARDS_DIR_NAME = "shards"
_DIRECT_EXEC_TASK_FILE_NAME = TASK_FILE_NAME
_DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME = "assigned_tasks.json"
_DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME = "assigned_shards.json"
_DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME = "worker_manifest.json"
_DIRECT_EXEC_CURRENT_PHASE_FILE_NAME = "current_phase.json"
_DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME = "CURRENT_PHASE.md"
_DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME = "CURRENT_PHASE_FEEDBACK.md"
_DIRECT_EXEC_CURRENT_PACKET_FILE_NAME = "current_packet.json"
_DIRECT_EXEC_CURRENT_HINT_FILE_NAME = "current_hint.md"
_DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME = "current_result_path.txt"
_DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME = "packet_lease_status.json"
_DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME = "OUTPUT_CONTRACT.md"
_DIRECT_EXEC_EXAMPLES_DIR_NAME = "examples"
_DIRECT_EXEC_TOOLS_DIR_NAME = "tools"
_DIRECT_EXEC_OUTPUT_DIR_NAME = "out"
_DIRECT_EXEC_SCRATCH_DIR_NAME = "scratch"
_DIRECT_EXEC_WORK_DIR_NAME = "work"
_DIRECT_EXEC_REPAIR_DIR_NAME = "repair"
_DIRECT_EXEC_INTERNAL_DIR_NAME = "_repo_control"
_DIRECT_EXEC_ORIGINAL_TASK_FILE_NAME = "original_task.json"
_DIRECT_EXEC_HELPER_IMPORTS_ROOT_NAME = "recipeimport-helper-imports"
_DIRECT_EXEC_RUNTIME_CONTROL_PATHS = (
    _DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME,
    _DIRECT_EXEC_CURRENT_PHASE_FILE_NAME,
    _DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME,
    _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME,
    _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME,
    _DIRECT_EXEC_CURRENT_HINT_FILE_NAME,
    _DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME,
    _DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME,
    _DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME,
)
_DIRECT_EXEC_WORKSPACE_MIRRORED_PATH_ENV_KEYS = (
    KNOWLEDGE_SAME_SESSION_STATE_ENV,
    RECIPE_SAME_SESSION_STATE_ENV,
    "RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH",
)
_SINGLE_FILE_WORKSPACE_SHIM_EXECUTABLES = (
    "cat",
    "ls",
    "python3",
    "python",
)
_SINGLE_FILE_WORKSPACE_ORIGINAL_PATH_ENV = "RECIPEIMPORT_SINGLE_FILE_ORIGINAL_PATH"
from .codex_exec_workspace import (
    PreparedDirectExecWorkspace,
    _prepare_single_file_workspace_shim_env,
    _prepare_taskfile_worker_helper_imports,
    _prepend_path,
    _prepend_pythonpath,
    _read_workspace_manifest_rows,
    _resolve_direct_exec_isolation_root,
    _rewrite_taskfile_worker_env_paths,
    _single_file_workspace_handoff_command,
    _single_file_workspace_local_examples,
    _single_file_workspace_task_file_payload,
    _sync_direct_exec_runtime_control_paths_to_execution,
    _sync_direct_exec_workspace_paths,
    build_direct_exec_workspace_manifest,
    prepare_direct_exec_workspace,
    rewrite_direct_exec_prompt_paths,
)
from .codex_exec_taskfile_policy import (
    _WORKSPACE_COMMAND_LOOP_MAX_COMMAND_COUNT,
    _WORKSPACE_COMMAND_LOOP_MAX_REPEAT_COUNT,
    _SINGLE_FILE_WORKSPACE_STAGE_HELPER_MODULES,
    _command_tokens_for_watchdog,
    classify_taskfile_worker_command,
    detect_taskfile_worker_boundary_violation,
    is_single_file_workspace_command_drift_policy,
    is_single_file_workspace_command_egregious,
    is_tolerated_taskfile_worker_command,
)
@dataclass(frozen=True)
class CodexExecRunResult:
    command: list[str]
    subprocess_exit_code: int
    output_schema_path: str | None
    prompt_text: str
    response_text: str | None
    turn_failed_message: str | None
    events: tuple[dict[str, Any], ...] = ()
    usage: dict[str, int] | None = None
    stderr_text: str | None = None
    stdout_text: str | None = None
    source_working_dir: str | None = None
    execution_working_dir: str | None = None
    execution_agents_path: str | None = None
    duration_ms: int | None = None
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    workspace_mode: DirectExecWorkerContract = "packet"
    supervision_state: str | None = None
    supervision_reason_code: str | None = None
    supervision_reason_detail: str | None = None
    supervision_retryable: bool = False

    @property
    def worker_contract(self) -> DirectExecWorkerContract:
        return self.workspace_mode

    def completed_successfully(self) -> bool:
        if self.subprocess_exit_code == 0:
            return True
        return str(self.supervision_state or "").strip().lower() == "completed"

    def telemetry_row(self, *, worker_id: str, shard_id: str) -> dict[str, Any]:
        usage = dict(self.usage or {})
        prompt_text = self._prompt_text()
        response_text = str(self.response_text or "")
        tokens_input = _coerce_nonnegative_int(usage.get("input_tokens"))
        tokens_cached_input = _coerce_nonnegative_int(usage.get("cached_input_tokens"))
        tokens_output = _coerce_nonnegative_int(usage.get("output_tokens"))
        tokens_reasoning = _coerce_nonnegative_int(usage.get("reasoning_tokens"))
        model_name = _model_name_from_command(self.command)
        visible_input_tokens = _count_tokens(prompt_text, model_name=model_name)
        visible_output_tokens = _count_tokens(response_text, model_name=model_name)
        wrapper_overhead_tokens = max(
            int(_sum_ints(tokens_input, tokens_output, tokens_reasoning) or 0)
            - visible_input_tokens
            - visible_output_tokens,
            0,
        )
        event_summary = _summarize_codex_events(
            self.events,
            allowed_absolute_roots=(
                [self.execution_working_dir]
                if self.workspace_mode == "taskfile" and self.execution_working_dir
                else None
            ),
        )
        pathological_flags = _pathological_flags_for_row(
            command_execution_count=event_summary["command_execution_count"],
            reasoning_item_count=event_summary["reasoning_item_count"],
            wrapper_overhead_tokens=wrapper_overhead_tokens,
            visible_input_tokens=visible_input_tokens,
            visible_output_tokens=visible_output_tokens,
        )
        command_policy_counts = dict(event_summary["command_execution_policy_counts"])
        command_policy_by_command = [dict(row) for row in event_summary["command_execution_policy_by_command"]]
        final_agent_message = assess_final_agent_message(
            self.response_text,
            workspace_mode=self.workspace_mode,
        )
        return {
            "worker_id": worker_id,
            "task_id": shard_id,
            "status": "ok" if self.completed_successfully() else "failed",
            "duration_ms": _coerce_nonnegative_int(self.duration_ms),
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "prompt_text": prompt_text,
            "prompt_chars": len(prompt_text),
            "output_payload_present": bool(response_text.strip()),
            "output_preview": response_text[:500] if response_text else None,
            "output_preview_chars": len(response_text),
            "tokens_input": tokens_input,
            "tokens_cached_input": tokens_cached_input,
            "tokens_output": tokens_output,
            "tokens_reasoning": tokens_reasoning,
            "tokens_total": _sum_ints(
                tokens_input,
                tokens_cached_input,
                tokens_output,
                tokens_reasoning,
            ),
            "visible_input_tokens": visible_input_tokens,
            "visible_output_tokens": visible_output_tokens,
            "wrapper_overhead_tokens": wrapper_overhead_tokens,
            "cost_breakdown": {
                "visible_input_tokens": visible_input_tokens,
                "cached_input_tokens": tokens_cached_input,
                "visible_output_tokens": visible_output_tokens,
                "wrapper_overhead_tokens": wrapper_overhead_tokens,
                "reasoning_tokens": tokens_reasoning,
                "billed_total_tokens": _sum_ints(
                    tokens_input,
                    tokens_cached_input,
                    tokens_output,
                    tokens_reasoning,
                ),
            },
            "codex_event_count": len(self.events),
            "codex_event_types": [
                str(event.get("type") or "").strip()
                for event in self.events
                if str(event.get("type") or "").strip()
            ],
            "command_execution_count": event_summary["command_execution_count"],
            "command_execution_commands": event_summary["command_execution_commands"],
            "command_execution_policy_counts": command_policy_counts,
            "command_execution_policy_by_command": command_policy_by_command,
            "reasoning_item_count": event_summary["reasoning_item_count"],
            "reasoning_item_types": event_summary["reasoning_item_types"],
            "pathological_flags": pathological_flags,
            "supervision_state": self.supervision_state,
            "supervision_reason_code": self.supervision_reason_code,
            "supervision_reason_detail": self.supervision_reason_detail,
            "supervision_retryable": self.supervision_retryable,
            "final_agent_message_state": final_agent_message.state,
            "final_agent_message_reason": final_agent_message.reason,
            "turn_failed_message": self.turn_failed_message,
            "output_schema_path": self.output_schema_path,
            "source_working_dir": self.source_working_dir,
            "execution_working_dir": self.execution_working_dir,
            "execution_agents_path": self.execution_agents_path,
        }

    def to_payload(self, *, worker_id: str, shard_id: str) -> dict[str, Any]:
        row = self.telemetry_row(worker_id=worker_id, shard_id=shard_id)
        telemetry = {
            "rows": [row],
            "summary": {
                "call_count": 1,
                "duration_ms": row.get("duration_ms"),
                "tokens_input": row.get("tokens_input"),
                "tokens_cached_input": row.get("tokens_cached_input"),
                "tokens_output": row.get("tokens_output"),
                "tokens_reasoning": row.get("tokens_reasoning"),
                "tokens_total": row.get("tokens_total"),
                "visible_input_tokens": row.get("visible_input_tokens"),
                "visible_output_tokens": row.get("visible_output_tokens"),
                "wrapper_overhead_tokens": row.get("wrapper_overhead_tokens"),
                "codex_event_count_total": row.get("codex_event_count"),
            },
        }
        token_usage_status = _token_usage_status_from_direct_rows([row])
        if token_usage_status is not None:
            telemetry_summary = dict(telemetry["summary"])
            telemetry_summary["token_usage_status"] = token_usage_status
            telemetry_summary["token_usage_available_call_count"] = (
                1 if _row_has_any_token_usage(row) else 0
            )
            telemetry_summary["token_usage_missing_call_count"] = (
                1 if _row_looks_like_missing_token_usage(row) else 0
            )
            if token_usage_status != "complete":
                for key in (
                    "tokens_input",
                    "tokens_cached_input",
                    "tokens_output",
                    "tokens_reasoning",
                    "tokens_total",
                    "wrapper_overhead_tokens",
                ):
                    telemetry_summary[key] = None
            telemetry["summary"] = telemetry_summary
        return {
            "runner_kind": "codex_exec_direct",
            "runtime_mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
            "subprocess_exit_code": self.subprocess_exit_code,
            "output_schema_path": self.output_schema_path,
            "command": list(self.command),
            "response_text": self.response_text,
            "turn_failed_message": self.turn_failed_message,
            "source_working_dir": self.source_working_dir,
            "execution_working_dir": self.execution_working_dir,
            "execution_agents_path": self.execution_agents_path,
            "duration_ms": _coerce_nonnegative_int(self.duration_ms),
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "supervision_state": self.supervision_state,
            "supervision_reason_code": self.supervision_reason_code,
            "supervision_reason_detail": self.supervision_reason_detail,
            "supervision_retryable": self.supervision_retryable,
            "workspace_manifest": self.workspace_manifest(),
            "telemetry": telemetry,
        }

    def _prompt_text(self) -> str:
        return self.prompt_text

    def workspace_manifest(self) -> dict[str, Any]:
        return build_direct_exec_workspace_manifest(
            source_working_dir=self.source_working_dir,
            execution_working_dir=self.execution_working_dir,
            execution_agents_path=self.execution_agents_path,
        )


@dataclass(frozen=True)
class SubprocessCodexExecRunner:
    cmd: str = "codex exec"

    def run_packet_worker(
        self,
        *,
        prompt_text: str,
        input_payload: Mapping[str, Any] | None,  # noqa: ARG002 - protocol parity
        working_dir: Path,
        env: Mapping[str, str],
        output_schema_path: Path | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: int | None = None,
        completed_termination_grace_seconds: float | None = None,
        workspace_task_label: str | None = None,
        supervision_callback: Callable[
            [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
        ]
        | None = None,
        resume_last: bool = False,
        persist_session: bool = False,
        prepared_execution_working_dir: Path | None = None,
    ) -> CodexExecRunResult:
        return self._run_prompt_in_prepared_workspace(
            prompt_text=prompt_text,
            working_dir=working_dir,
            env=env,
            output_schema_path=output_schema_path,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            completed_termination_grace_seconds=completed_termination_grace_seconds,
            workspace_task_label=workspace_task_label,
            supervision_callback=supervision_callback,
            workspace_mode="packet",
            sandbox_mode="read-only",
            require_final_message=True,
            sync_output_paths=(),
            resume_last=resume_last,
            persist_session=persist_session,
            prepared_execution_working_dir=prepared_execution_working_dir,
        )

    def run_taskfile_worker(
        self,
        *,
        prompt_text: str,
        working_dir: Path,
        env: Mapping[str, str],
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: int | None = None,
        completed_termination_grace_seconds: float | None = None,
        workspace_task_label: str | None = None,
        supervision_callback: Callable[
            [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
        ]
        | None = None,
    ) -> CodexExecRunResult:
        return self._run_prompt_in_prepared_workspace(
            prompt_text=prompt_text,
            working_dir=working_dir,
            env=env,
            output_schema_path=None,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            completed_termination_grace_seconds=completed_termination_grace_seconds,
            workspace_task_label=workspace_task_label,
            supervision_callback=supervision_callback,
            workspace_mode="taskfile",
            sandbox_mode="workspace-write",
            require_final_message=False,
            sync_output_paths=(
                _DIRECT_EXEC_TASK_FILE_NAME,
                _DIRECT_EXEC_INTERNAL_DIR_NAME,
                _DIRECT_EXEC_CURRENT_PHASE_FILE_NAME,
                _DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME,
                _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME,
                _DIRECT_EXEC_INPUT_DIR_NAME,
                _DIRECT_EXEC_OUTPUT_DIR_NAME,
                _DIRECT_EXEC_SCRATCH_DIR_NAME,
                _DIRECT_EXEC_WORK_DIR_NAME,
                _DIRECT_EXEC_REPAIR_DIR_NAME,
            ),
            resume_last=False,
            persist_session=False,
            prepared_execution_working_dir=None,
        )

    def _run_prompt_in_prepared_workspace(
        self,
        *,
        prompt_text: str,
        working_dir: Path,
        env: Mapping[str, str],
        output_schema_path: Path | None,
        model: str | None,
        reasoning_effort: str | None,
        timeout_seconds: int | None,
        completed_termination_grace_seconds: float | None,
        workspace_task_label: str | None,
        supervision_callback: Callable[
            [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
        ]
        | None,
        workspace_mode: DirectExecWorkspaceMode,
        sandbox_mode: str,
        require_final_message: bool,
        sync_output_paths: Sequence[str],
        resume_last: bool,
        persist_session: bool,
        prepared_execution_working_dir: Path | None,
    ) -> CodexExecRunResult:
        process_env = _merge_env(env)
        if resume_last:
            if prepared_execution_working_dir is None:
                raise CodexFarmRunnerError(
                    "Inline JSON requires a previously prepared execution workspace."
                )
            execution_working_dir = Path(prepared_execution_working_dir).resolve(strict=False)
            if not execution_working_dir.exists():
                raise CodexFarmRunnerError(
                    "Inline JSON execution workspace is missing: "
                    f"{execution_working_dir}"
                )
            prepared_workspace = PreparedDirectExecWorkspace(
                source_working_dir=Path(working_dir).resolve(),
                execution_working_dir=execution_working_dir,
                agents_path=execution_working_dir / _DIRECT_EXEC_AGENTS_FILE_NAME,
            )
        else:
            prepared_workspace = prepare_direct_exec_workspace(
                source_working_dir=working_dir,
                env=process_env,
                task_label=workspace_task_label,
                mode=workspace_mode,
            )
        execution_working_dir = prepared_workspace.execution_working_dir
        single_file_worker_runtime = _uses_single_file_worker_runtime(
            workspace_root=working_dir,
            mode=workspace_mode,
        )
        if workspace_mode == "taskfile" and single_file_worker_runtime:
            _sync_direct_exec_runtime_control_paths_to_execution(
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
                relative_paths=(_DIRECT_EXEC_INTERNAL_DIR_NAME,),
            )
            process_env = _rewrite_taskfile_worker_env_paths(
                env=process_env,
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
            )
        if workspace_mode == "taskfile":
            helper_import_root = _prepare_taskfile_worker_helper_imports(
                env=process_env,
                execution_working_dir=execution_working_dir,
            )
            process_env = _prepare_single_file_workspace_shim_env(env=process_env)
            process_env = _prepend_pythonpath(
                env=process_env,
                import_root=helper_import_root,
            )
            process_env = _prepend_path(
                env=process_env,
                path_entries=(helper_import_root / "bin",),
            )
        execution_prompt_text = rewrite_direct_exec_prompt_paths(
            prompt_text=prompt_text,
            source_working_dir=working_dir,
            execution_working_dir=execution_working_dir,
        )
        command = _build_codex_exec_command(
            cmd=self.cmd,
            working_dir=execution_working_dir,
            output_schema_path=None if resume_last else output_schema_path,
            model=model,
            reasoning_effort=reasoning_effort,
            sandbox_mode=sandbox_mode,
            resume_last=resume_last,
            persist_session=persist_session,
        )
        subprocess_command = (
            _build_taskfile_worker_fs_cage_command(
                command=command,
                working_dir=execution_working_dir,
                env=process_env,
            )
            if workspace_mode == "taskfile"
            else command
        )
        started_at = datetime.now(timezone.utc)
        completed = _run_codex_exec_subprocess_streaming(
            command=subprocess_command,
            prompt_text=execution_prompt_text,
            working_dir=execution_working_dir,
            env=process_env,
            timeout_seconds=timeout_seconds,
            completed_termination_grace_seconds=completed_termination_grace_seconds,
            workspace_mode=workspace_mode,
            supervision_callback=_wrap_workspace_supervision_callback(
                supervision_callback=supervision_callback,
                workspace_mode=workspace_mode,
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
                sync_output_paths=sync_output_paths,
                sync_source_paths=(
                    _DIRECT_EXEC_RUNTIME_CONTROL_PATHS
                    if workspace_mode == "taskfile"
                    and not single_file_worker_runtime
                    else ()
                ),
            ),
        )
        finished_at = datetime.now(timezone.utc)
        _sync_direct_exec_workspace_paths(
            source_working_dir=working_dir,
            execution_working_dir=execution_working_dir,
            relative_paths=sync_output_paths,
        )
        if workspace_mode == "taskfile" and not single_file_worker_runtime:
            _sync_direct_exec_workspace_paths(
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
                relative_paths=_DIRECT_EXEC_RUNTIME_CONTROL_PATHS,
            )

        events = tuple(completed.events)
        response_text = _extract_last_agent_message(events)
        turn_failed_message = _extract_turn_failed_message(events)
        usage = _normalize_usage(_extract_turn_completed_usage(events))
        if _usage_missing_or_zero(usage):
            usage = _extract_usage_from_text_streams(completed.stdout, completed.stderr)
        if completed.returncode != 0 and completed.termination_decision is None:
            detail = turn_failed_message or _summarize_failure_text(completed.stderr, completed.stdout)
            raise CodexFarmRunnerError(
                f"codex exec failed (exit={completed.returncode}): {detail or 'no detail'}"
            )
        if require_final_message and not response_text and completed.termination_decision is None:
            raise CodexFarmRunnerError(
                "codex exec failed: no last agent message in JSON event stream."
            )
        return CodexExecRunResult(
            command=list(command),
            subprocess_exit_code=int(completed.returncode),
            output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
            prompt_text=execution_prompt_text,
            response_text=response_text,
            turn_failed_message=turn_failed_message,
            events=events,
            usage=usage,
            stderr_text=completed.stderr or None,
            stdout_text=completed.stdout or None,
            source_working_dir=str(working_dir),
            execution_working_dir=str(execution_working_dir),
            execution_agents_path=str(prepared_workspace.agents_path),
            duration_ms=completed.duration_ms,
            started_at_utc=_format_utc_timestamp(started_at),
            finished_at_utc=_format_utc_timestamp(finished_at),
            workspace_mode=workspace_mode,
            supervision_state=(
                completed.termination_decision.supervision_state
                if completed.termination_decision is not None
                else "completed"
            ),
            supervision_reason_code=(
                completed.termination_decision.reason_code
                if completed.termination_decision is not None
                else None
            ),
            supervision_reason_detail=(
                completed.termination_decision.reason_detail
                if completed.termination_decision is not None
                else None
            ),
            supervision_retryable=bool(
                completed.termination_decision.retryable
                if completed.termination_decision is not None
                else False
            ),
        )


@dataclass
class FakeCodexExecRunner:
    output_builder: Callable[[Mapping[str, Any] | None], dict[str, Any]]
    workspace_final_message_text: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def _write_workspace_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _build_knowledge_leased_packet_result(
        *,
        packet_payload: Mapping[str, Any],
        output_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        packet_kind = str(packet_payload.get("packet_kind") or "").strip()
        task_id = str(packet_payload.get("task_id") or "").strip()
        shard_id = str(packet_payload.get("shard_id") or "").strip()
        rows = packet_payload.get("rows")
        if not isinstance(rows, list):
            rows = []

        if (
            str(output_payload.get("packet_kind") or "").strip() == packet_kind
            and str(output_payload.get("task_id") or "").strip() == task_id
            and str(output_payload.get("shard_id") or "").strip() == shard_id
            and isinstance(output_payload.get("rows"), list)
        ):
            normalized_rows: list[dict[str, Any]] = []
            for row in output_payload.get("rows") or []:
                if not isinstance(row, Mapping) or row.get("block_index") is None:
                    continue
                normalized_row = {"block_index": int(row.get("block_index"))}
                if packet_kind == "pass1":
                    normalized_row["category"] = str(row.get("category") or "").strip()
                else:
                    normalized_row["group_key"] = str(
                        row.get("group_key") or row.get("group_id") or ""
                    ).strip()
                    normalized_row["topic_label"] = str(row.get("topic_label") or "").strip()
                normalized_rows.append(normalized_row)
            return {
                "v": str(output_payload.get("v") or "1"),
                "task_id": task_id,
                "packet_kind": packet_kind,
                "shard_id": shard_id,
                "rows": normalized_rows,
            }

        if packet_kind == "pass1":
            decision_by_block_index = {
                int(row.get("block_index")): str(row.get("category") or "").strip()
                for row in (output_payload.get("block_decisions") or [])
                if isinstance(row, Mapping) and row.get("block_index") is not None
            }
            default_category = "knowledge" if not decision_by_block_index else "other"
            return {
                "v": "1",
                "task_id": task_id,
                "packet_kind": "pass1",
                "shard_id": shard_id,
                "rows": [
                    {
                        "block_index": int(row.get("block_index")),
                        "category": decision_by_block_index.get(
                            int(row.get("block_index")),
                            default_category,
                        )
                        or default_category,
                    }
                    for row in rows
                    if isinstance(row, Mapping) and row.get("block_index") is not None
                ],
            }

        group_by_block_index: dict[int, dict[str, str]] = {}
        fallback_group_key = None
        fallback_topic_label = None
        for group in output_payload.get("idea_groups") or []:
            if not isinstance(group, Mapping):
                continue
            group_key = str(group.get("group_key") or group.get("group_id") or "").strip()
            topic_label = str(group.get("topic_label") or "").strip()
            if not group_key or not topic_label:
                continue
            if fallback_group_key is None:
                fallback_group_key = group_key
                fallback_topic_label = topic_label
            for block_index in group.get("block_indices") or []:
                try:
                    normalized_block_index = int(block_index)
                except (TypeError, ValueError):
                    continue
                group_by_block_index[normalized_block_index] = {
                    "group_key": group_key,
                    "topic_label": topic_label,
                }
        fallback_group_key = fallback_group_key or "group-01"
        fallback_topic_label = fallback_topic_label or "Fake knowledge group"
        return {
            "v": "1",
            "task_id": task_id,
            "packet_kind": "pass2",
            "shard_id": shard_id,
            "rows": [
                {
                    "block_index": int(row.get("block_index")),
                    "group_key": (
                        group_by_block_index.get(int(row.get("block_index")), {}).get(
                            "group_key"
                        )
                        or fallback_group_key
                    ),
                    "topic_label": (
                        group_by_block_index.get(int(row.get("block_index")), {}).get(
                            "topic_label"
                        )
                        or fallback_topic_label
                    ),
                }
                for row in rows
                if isinstance(row, Mapping) and row.get("block_index") is not None
            ],
        }

    @classmethod
    def _build_leased_packet_result(
        cls,
        *,
        packet_payload: Mapping[str, Any],
        output_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        packet_kind = str(packet_payload.get("packet_kind") or "").strip()
        if packet_kind in {"pass1", "pass2"}:
            return cls._build_knowledge_leased_packet_result(
                packet_payload=packet_payload,
                output_payload=output_payload,
            )
        return dict(output_payload)

    def _build_workspace_task_file_result(
        self,
        *,
        task_file_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            direct_result = self.output_builder(dict(task_file_payload))
        except Exception:  # noqa: BLE001
            direct_result = {}
        if _looks_like_editable_task_file_payload(direct_result):
            return dict(direct_result)
        edited = dict(task_file_payload)
        units_payload = edited.get("units")
        if not isinstance(units_payload, list):
            return edited
        stage_key = str(task_file_payload.get("stage_key") or "").strip()
        if stage_key == "line_role":
            line_role_rows = []
            for unit in units_payload:
                if not isinstance(unit, Mapping):
                    continue
                evidence = dict(unit.get("evidence") or {})
                line_role_rows.append(
                    [
                        int(evidence.get("atomic_index") or 0),
                        str(evidence.get("text") or ""),
                    ]
                )
            try:
                line_role_result = self.output_builder(
                    {
                        "stage_key": "line_role",
                        "rows": line_role_rows,
                    }
                )
            except Exception:  # noqa: BLE001
                line_role_result = {}
            if isinstance(line_role_result, Mapping) and isinstance(
                line_role_result.get("rows"), list
            ):
                answer_by_atomic_index: dict[int, dict[str, Any]] = {}
                for row in line_role_result.get("rows") or []:
                    if not isinstance(row, Mapping):
                        continue
                    label = str(row.get("label") or "").strip()
                    if not label:
                        continue
                    atomic_index = int(row.get("atomic_index") or 0)
                    answer_payload: dict[str, Any] = {"label": label}
                    exclusion_reason = str(row.get("exclusion_reason") or "").strip()
                    if exclusion_reason:
                        answer_payload["exclusion_reason"] = exclusion_reason
                    answer_by_atomic_index[atomic_index] = answer_payload
                if answer_by_atomic_index and len(answer_by_atomic_index) >= len(
                    line_role_rows
                ):
                    edited_units = []
                    for unit in units_payload:
                        if not isinstance(unit, Mapping):
                            continue
                        unit_dict = dict(unit)
                        evidence = dict(unit_dict.get("evidence") or {})
                        atomic_index = int(evidence.get("atomic_index") or 0)
                        unit_dict["answer"] = dict(
                            answer_by_atomic_index.get(atomic_index) or {}
                        )
                        edited_units.append(unit_dict)
                    edited["units"] = edited_units
                    return edited
        edited_units: list[dict[str, Any]] = []
        for unit in units_payload:
            if not isinstance(unit, Mapping):
                continue
            unit_dict = dict(unit)
            evidence = dict(unit_dict.get("evidence") or {})
            unit_dict["answer"] = self._build_workspace_task_unit_answer(
                stage_key=stage_key,
                evidence=evidence,
            )
            edited_units.append(unit_dict)
        edited["units"] = edited_units
        return edited

    @staticmethod
    def _build_recipe_task_answer_request(
        *,
        stage_key: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        hint_payload = dict(evidence.get("hint") or {})
        return {
            "stage_key": stage_key,
            "recipe_id": str(evidence.get("recipe_id") or "recipe"),
            "hint": {
                "title": hint_payload.get("title"),
                "ingredients": list(hint_payload.get("ingredients") or []),
                "steps": list(hint_payload.get("steps") or []),
            },
            "source_text": str(evidence.get("source_text") or ""),
            "source_rows": list(evidence.get("source_rows") or []),
        }

    @staticmethod
    def _normalize_recipe_task_answer_payload(
        payload: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(payload, Mapping):
            return None
        required_keys = {
            "status",
            "canonical_recipe",
            "ingredient_step_mapping",
            "ingredient_step_mapping_reason",
            "divested_block_indices",
            "selected_tags",
            "warnings",
        }
        if not required_keys.issubset(payload.keys()):
            return None
        return dict(payload)

    def _build_workspace_task_unit_answer(
        self,
        *,
        stage_key: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        if stage_key == "recipe_refine":
            direct_output: Mapping[str, Any] | None = None
            try:
                direct_output = self.output_builder(
                    self._build_recipe_task_answer_request(
                        stage_key=stage_key,
                        evidence=evidence,
                    )
                )
            except Exception:  # noqa: BLE001
                direct_output = None
            normalized_output = self._normalize_recipe_task_answer_payload(direct_output)
            return normalized_output or {}
        if stage_key in {"nonrecipe_finalize", "nonrecipe_classify"}:
            block_index = int(evidence.get("block_index") or 0)
            direct_output = self.output_builder(
                {
                    "stage_key": stage_key,
                    "block_id": str(evidence.get("block_id") or f"block-{block_index}"),
                    "block_index": block_index,
                    "text": str(evidence.get("text") or ""),
                    "candidate_tag_keys": [
                        str(value).strip()
                        for value in (evidence.get("candidate_tag_keys") or [])
                        if str(value).strip()
                    ],
                }
            )
            return dict(direct_output) if isinstance(direct_output, Mapping) else {}
        if stage_key == "knowledge_group":
            block_index = int(evidence.get("block_index") or 0)
            direct_output = self.output_builder(
                {
                    "stage_key": stage_key,
                    "block_id": str(evidence.get("block_id") or f"block-{block_index}"),
                    "block_index": block_index,
                    "text": str(evidence.get("text") or ""),
                }
            )
            return dict(direct_output) if isinstance(direct_output, Mapping) else {}
        if stage_key == "line_role":
            atomic_index = int(evidence.get("atomic_index") or 0)
            direct_output = self.output_builder(
                {
                    "stage_key": stage_key,
                    "atomic_index": atomic_index,
                    "text": str(evidence.get("text") or ""),
                }
            )
            if not isinstance(direct_output, Mapping):
                return {}
            if "label" in direct_output:
                return dict(direct_output)
            rows_payload = direct_output.get("rows")
            if isinstance(rows_payload, list):
                matching_row: Mapping[str, Any] | None = None
                for row in rows_payload:
                    if not isinstance(row, Mapping):
                        continue
                    if int(row.get("atomic_index") or -1) == atomic_index:
                        matching_row = row
                        break
                if matching_row is None and len(rows_payload) == 1 and isinstance(
                    rows_payload[0], Mapping
                ):
                    matching_row = rows_payload[0]
                if matching_row is not None:
                    answer_payload: dict[str, Any] = {}
                    label = str(matching_row.get("label") or "").strip()
                    if label:
                        answer_payload["label"] = label
                    exclusion_reason = str(
                        matching_row.get("exclusion_reason") or ""
                    ).strip()
                    if exclusion_reason:
                        answer_payload["exclusion_reason"] = exclusion_reason
                    return answer_payload
            return {}
        return {}

    def run_packet_worker(
        self,
        *,
        prompt_text: str,
        input_payload: Mapping[str, Any] | None,
        working_dir: Path,
        env: Mapping[str, str],  # noqa: ARG002 - protocol parity
        output_schema_path: Path | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: int | None = None,  # noqa: ARG002 - protocol parity
        completed_termination_grace_seconds: float | None = None,  # noqa: ARG002 - protocol parity
        workspace_task_label: str | None = None,
        supervision_callback: Callable[
            [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
        ]
        | None = None,
        resume_last: bool = False,
        persist_session: bool = False,
        prepared_execution_working_dir: Path | None = None,
    ) -> CodexExecRunResult:
        execution_working_dir = (
            Path(prepared_execution_working_dir).resolve(strict=False)
            if prepared_execution_working_dir is not None
            else Path(working_dir).resolve(strict=False)
        )
        self.calls.append(
            {
                "mode": "structured_prompt_resume" if resume_last else "structured_prompt",
                "prompt_text": prompt_text,
                "input_payload": dict(input_payload or {}),
                "working_dir": str(working_dir),
                "execution_working_dir": str(execution_working_dir),
                "output_schema_path": str(output_schema_path) if output_schema_path is not None else None,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "timeout_seconds": timeout_seconds,
                "completed_termination_grace_seconds": completed_termination_grace_seconds,
                "workspace_task_label": workspace_task_label,
                "resume_last": bool(resume_last),
                "persist_session": bool(persist_session),
            }
        )
        payload = self.output_builder(input_payload)
        response_text = json.dumps(payload, indent=2, sort_keys=True)
        usage = {
            "input_tokens": max(1, len(prompt_text) // 4),
            "cached_input_tokens": 0,
            "output_tokens": max(1, len(response_text) // 4),
            "reasoning_tokens": 0,
        }
        events = (
            {"type": "thread.started"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": response_text},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": usage["input_tokens"],
                    "cached_input_tokens": usage["cached_input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "reasoning_tokens": usage["reasoning_tokens"],
                },
            },
        )
        if supervision_callback is not None:
            final_agent_message = assess_final_agent_message(
                response_text,
                workspace_mode="packet",
            )
            supervision_callback(
                CodexExecLiveSnapshot(
                    elapsed_seconds=0.0,
                    last_event_seconds_ago=0.0,
                    event_count=len(events),
                    command_execution_count=0,
                    reasoning_item_count=0,
                    last_command=None,
                    last_command_repeat_count=0,
                    has_final_agent_message=True,
                    timeout_seconds=timeout_seconds,
                    final_agent_message_state=final_agent_message.state,
                    final_agent_message_reason=final_agent_message.reason,
                    source_working_dir=str(working_dir),
                    execution_working_dir=str(working_dir),
                )
            )
        return CodexExecRunResult(
            command=(
                ["codex", "exec", "resume", "--last"]
                if resume_last
                else ["codex", "exec"]
            ),
            subprocess_exit_code=0,
            output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
            prompt_text=prompt_text,
            response_text=response_text,
            turn_failed_message=None,
            events=events,
            usage=usage,
            stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
            source_working_dir=str(working_dir),
            execution_working_dir=str(execution_working_dir),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="packet",
            supervision_state="completed",
        )

    def run_taskfile_worker(
        self,
        *,
        prompt_text: str,
        working_dir: Path,
        env: Mapping[str, str],
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: int | None = None,
        completed_termination_grace_seconds: float | None = None,  # noqa: ARG002 - protocol parity
        workspace_task_label: str | None = None,
        supervision_callback: Callable[
            [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
        ]
        | None = None,
    ) -> CodexExecRunResult:
        process_env = _merge_env(env)
        prepared_workspace = prepare_direct_exec_workspace(
            source_working_dir=working_dir,
            env=process_env,
            task_label=workspace_task_label,
            mode="taskfile",
        )
        execution_working_dir = prepared_workspace.execution_working_dir
        execution_prompt_text = rewrite_direct_exec_prompt_paths(
            prompt_text=prompt_text,
            source_working_dir=working_dir,
            execution_working_dir=execution_working_dir,
        )
        self.calls.append(
            {
                "mode": "taskfile",
                "prompt_text": execution_prompt_text,
                "input_payload": None,
                "working_dir": str(working_dir),
                "execution_working_dir": str(execution_working_dir),
                "output_schema_path": None,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "timeout_seconds": timeout_seconds,
                "completed_termination_grace_seconds": completed_termination_grace_seconds,
                "workspace_task_label": workspace_task_label,
            }
        )
        out_dir = execution_working_dir / _DIRECT_EXEC_OUTPUT_DIR_NAME
        out_dir.mkdir(parents=True, exist_ok=True)
        assigned_task_rows = _read_workspace_manifest_rows(
            execution_working_dir=execution_working_dir,
        )
        task_file_path = execution_working_dir / _DIRECT_EXEC_TASK_FILE_NAME
        if task_file_path.exists():
            edited_task_file_payload = self._build_workspace_task_file_result(
                task_file_payload=load_task_file(task_file_path),
            )
            write_task_file(path=task_file_path, payload=edited_task_file_payload)
            same_session_handlers = [
                (
                    str(process_env.get(KNOWLEDGE_SAME_SESSION_STATE_ENV) or "").strip(),
                    advance_knowledge_same_session_handoff,
                    {"repair_required", "advance_to_grouping"},
                ),
                (
                    str(process_env.get(RECIPE_SAME_SESSION_STATE_ENV) or "").strip(),
                    advance_recipe_same_session_handoff,
                    {"repair_required"},
                ),
            ]
            line_role_state_path = str(
                process_env.get("RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH") or ""
            ).strip()
            if line_role_state_path:
                from cookimport.parsing.canonical_line_roles.same_session_handoff import (
                    advance_line_role_same_session_handoff,
                )

                same_session_handlers.append(
                    (
                        line_role_state_path,
                        advance_line_role_same_session_handoff,
                        {"repair_required"},
                    )
                )
            for state_path, advance_handler, continue_statuses in same_session_handlers:
                transition_guard = 0
                while state_path and transition_guard < 8:
                    transition_guard += 1
                    transition_result = advance_handler(
                        workspace_root=execution_working_dir,
                        state_path=Path(state_path),
                    )
                    transition_status = str(transition_result.get("status") or "").strip()
                    if transition_status not in continue_statuses:
                        break
                    next_task_file_payload = load_task_file(task_file_path)
                    edited_task_file_payload = self._build_workspace_task_file_result(
                        task_file_payload=next_task_file_payload,
                    )
                    write_task_file(path=task_file_path, payload=edited_task_file_payload)
                if state_path:
                    break
        elif (execution_working_dir / _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME).exists():
            lease_iterations = 0
            while lease_iterations < 256:
                lease_iterations += 1
                current_packet_path = execution_working_dir / _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME
                if not current_packet_path.exists():
                    break
                try:
                    input_payload = json.loads(current_packet_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    break
                if not isinstance(input_payload, Mapping):
                    break
                result_path_path = execution_working_dir / _DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME
                if not result_path_path.exists():
                    break
                relative_result_path = str(
                    result_path_path.read_text(encoding="utf-8")
                ).strip()
                if not relative_result_path:
                    break
                output_payload = self._build_leased_packet_result(
                    packet_payload=input_payload,
                    output_payload=self.output_builder(input_payload),
                )
                output_path = execution_working_dir / relative_result_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(output_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                _sync_direct_exec_workspace_paths(
                    source_working_dir=working_dir,
                    execution_working_dir=execution_working_dir,
                    relative_paths=(
                        _DIRECT_EXEC_SCRATCH_DIR_NAME,
                        _DIRECT_EXEC_OUTPUT_DIR_NAME,
                    ),
                )
                if supervision_callback is not None:
                    supervision_callback(
                        CodexExecLiveSnapshot(
                            elapsed_seconds=0.0,
                            last_event_seconds_ago=0.0,
                            event_count=0,
                            command_execution_count=0,
                            reasoning_item_count=0,
                            last_command=None,
                            last_command_repeat_count=0,
                            has_final_agent_message=False,
                            timeout_seconds=timeout_seconds,
                            source_working_dir=str(working_dir),
                            execution_working_dir=str(execution_working_dir),
                        )
                    )
                    _sync_direct_exec_runtime_control_paths_to_execution(
                        source_working_dir=working_dir,
                        execution_working_dir=execution_working_dir,
                        relative_paths=_DIRECT_EXEC_RUNTIME_CONTROL_PATHS,
                    )
                    _sync_direct_exec_workspace_paths(
                        source_working_dir=working_dir,
                        execution_working_dir=execution_working_dir,
                        relative_paths=(
                            _DIRECT_EXEC_SCRATCH_DIR_NAME,
                            _DIRECT_EXEC_OUTPUT_DIR_NAME,
                        ),
                    )
        else:
            for shard_row in assigned_task_rows:
                if not isinstance(shard_row, Mapping):
                    continue
                unit_id = str(
                    shard_row.get("task_id")
                    or shard_row.get("shard_id")
                    or ""
                ).strip()
                if not unit_id:
                    continue
                metadata = shard_row.get("metadata")
                metadata_payload = dict(metadata) if isinstance(metadata, Mapping) else {}
                input_relpath = str(metadata_payload.get("input_path") or "").strip()
                if not input_relpath:
                    input_relpath = f"{_DIRECT_EXEC_INPUT_DIR_NAME}/{unit_id}.json"
                input_path = execution_working_dir / input_relpath
                if not input_path.exists():
                    continue
                try:
                    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                output_payload = self.output_builder(input_payload)
                output_relpath = str(metadata_payload.get("result_path") or "").strip()
                if not output_relpath:
                    output_relpath = f"{_DIRECT_EXEC_OUTPUT_DIR_NAME}/{unit_id}.json"
                output_path = execution_working_dir / output_relpath
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(output_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
        _sync_direct_exec_workspace_paths(
            source_working_dir=working_dir,
            execution_working_dir=execution_working_dir,
            relative_paths=(
                _DIRECT_EXEC_TASK_FILE_NAME,
                _DIRECT_EXEC_INPUT_DIR_NAME,
                _DIRECT_EXEC_OUTPUT_DIR_NAME,
                _DIRECT_EXEC_SCRATCH_DIR_NAME,
                _DIRECT_EXEC_WORK_DIR_NAME,
                _DIRECT_EXEC_REPAIR_DIR_NAME,
            ),
        )
        response_text = (
            str(self.workspace_final_message_text)
            if self.workspace_final_message_text is not None
            else json.dumps({"status": "worker_completed"}, indent=2, sort_keys=True)
        )
        usage = {
            "input_tokens": max(1, len(execution_prompt_text) // 4),
            "cached_input_tokens": 0,
            "output_tokens": max(1, len(response_text) // 4),
            "reasoning_tokens": 0,
        }
        events = (
            {"type": "thread.started"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": response_text},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": usage["input_tokens"],
                    "cached_input_tokens": usage["cached_input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "reasoning_tokens": usage["reasoning_tokens"],
                },
            },
        )
        if supervision_callback is not None:
            final_agent_message = assess_final_agent_message(
                response_text,
                workspace_mode="taskfile",
            )
            supervision_callback(
                CodexExecLiveSnapshot(
                    elapsed_seconds=0.0,
                    last_event_seconds_ago=0.0,
                    event_count=len(events),
                    command_execution_count=0,
                    reasoning_item_count=0,
                    last_command=None,
                    last_command_repeat_count=0,
                    has_final_agent_message=True,
                    timeout_seconds=timeout_seconds,
                    final_agent_message_state=final_agent_message.state,
                    final_agent_message_reason=final_agent_message.reason,
                )
            )
        return CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text=execution_prompt_text,
            response_text=response_text,
            turn_failed_message=None,
            events=events,
            usage=usage,
            stderr_text=None,
            stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
            source_working_dir=str(working_dir),
            execution_working_dir=str(execution_working_dir),
            execution_agents_path=str(prepared_workspace.agents_path),
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="taskfile",
            supervision_state="completed",
        )


def _looks_like_editable_task_file_payload(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    schema_version = str(value.get("schema_version") or "").strip()
    if schema_version == TASK_FILE_SCHEMA_VERSION:
        return True
    answer_schema = value.get("answer_schema")
    return (
        schema_version in {"knowledge_block_classify.v1", "knowledge_group_only.v1"}
        and isinstance(value.get("units"), list)
        and isinstance(answer_schema, Mapping)
        and bool(str(answer_schema.get("editable_pointer_pattern") or "").strip())
    )


def _build_codex_exec_command(
    *,
    cmd: str,
    working_dir: Path,
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    sandbox_mode: str = "read-only",
    resume_last: bool = False,
    persist_session: bool = False,
) -> list[str]:
    return _command_builder_module.build_codex_exec_command(
        cmd=cmd,
        working_dir=working_dir,
        output_schema_path=output_schema_path,
        model=model,
        reasoning_effort=reasoning_effort,
        sandbox_mode=sandbox_mode,
        resume_last=resume_last,
        persist_session=persist_session,
    )


@lru_cache(maxsize=1)
def _taskfile_worker_fs_cage_unshare_path() -> str | None:
    resolved = shutil.which("unshare")
    if not resolved:
        return None
    return str(Path(resolved).expanduser())


def _build_taskfile_worker_fs_cage_command(
    *,
    command: Sequence[str],
    working_dir: Path,
    env: Mapping[str, str],
) -> list[str]:
    explicit_env = {str(key): str(value) for key, value in (env or {}).items()}
    return _command_builder_module.build_taskfile_worker_fs_cage_command(
        command=command,
        working_dir=working_dir,
        env=env,
        unshare_path=_taskfile_worker_fs_cage_unshare_path(),
        resolved_codex_home=_resolve_recipeimport_codex_home(explicit_env=explicit_env),
        direct_exec_root=_resolve_direct_exec_isolation_root(env=explicit_env),
        user_home=Path.home().expanduser().resolve(strict=False),
        mktemp_template=workspace_fs_cage_mktemp_template(env=explicit_env),
    )


def _wrap_workspace_supervision_callback(
    *,
    supervision_callback: Callable[
        [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
    ]
    | None,
    workspace_mode: DirectExecWorkspaceMode,
    source_working_dir: Path,
    execution_working_dir: Path,
    sync_output_paths: Sequence[str],
    sync_source_paths: Sequence[str],
) -> Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None] | None:
    if supervision_callback is None:
        return None
    if workspace_mode != "taskfile" or not sync_output_paths:
        return supervision_callback

    def _wrapped(snapshot: CodexExecLiveSnapshot) -> CodexExecSupervisionDecision | None:
        _sync_direct_exec_workspace_paths(
            source_working_dir=source_working_dir,
            execution_working_dir=execution_working_dir,
            relative_paths=sync_output_paths,
        )
        callback_snapshot = replace(
            snapshot,
            source_working_dir=str(source_working_dir),
            execution_working_dir=str(execution_working_dir),
        )
        decision = supervision_callback(callback_snapshot)
        if sync_source_paths:
            _sync_direct_exec_runtime_control_paths_to_execution(
                source_working_dir=source_working_dir,
                execution_working_dir=execution_working_dir,
                relative_paths=sync_source_paths,
            )
        return decision

    return _wrapped


def _format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class _StreamedCodexProcessResult:
    returncode: int
    stdout: str
    stderr: str
    events: tuple[dict[str, Any], ...]
    termination_decision: CodexExecSupervisionDecision | None
    duration_ms: int


def _run_codex_exec_subprocess_streaming(
    *,
    command: Sequence[str],
    prompt_text: str,
    working_dir: Path,
    env: Mapping[str, str],
    timeout_seconds: int | None,
    completed_termination_grace_seconds: float | None,
    workspace_mode: DirectExecWorkspaceMode,
    supervision_callback: Callable[
        [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
    ]
    | None,
) -> _StreamedCodexProcessResult:
    started_at = time.perf_counter()
    normalized_timeout = max(1, int(timeout_seconds)) if timeout_seconds is not None else None
    normalized_completed_grace = resolve_completed_termination_grace_seconds(
        {
            "completed_termination_grace_seconds": completed_termination_grace_seconds
        }
        if completed_termination_grace_seconds is not None
        else None
    )
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(working_dir),
            env=dict(env),
            bufsize=1,
        )
    except FileNotFoundError as exc:
        binary = command[0] if command else "codex"
        raise CodexFarmRunnerError(
            f"codex command not found: {binary!r}. Install Codex CLI before retrying."
        ) from exc
    except OSError as exc:
        binary = command[0] if command else "codex"
        raise CodexFarmRunnerError(
            f"Failed to execute codex command {binary!r}: {exc}"
        ) from exc

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    process.stdin.write(prompt_text)
    process.stdin.close()

    stream_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    events: list[dict[str, Any]] = []
    closed_streams: set[str] = set()
    last_event_at: float | None = None
    last_snapshot_at = started_at
    termination_decision: CodexExecSupervisionDecision | None = None
    graceful_termination_deadline: float | None = None

    reader_threads = [
        threading.Thread(
            target=_read_codex_stream_lines,
            args=(process.stdout, "stdout", stream_queue),
            daemon=True,
        ),
        threading.Thread(
            target=_read_codex_stream_lines,
            args=(process.stderr, "stderr", stream_queue),
            daemon=True,
        ),
    ]
    for thread in reader_threads:
        thread.start()

    while True:
        current_time = time.perf_counter()
        if normalized_timeout is not None and current_time - started_at > normalized_timeout:
            _terminate_codex_process(process)
            raise CodexFarmRunnerError(
                f"codex exec timed out after {normalized_timeout} seconds."
            )

        saw_update = False
        try:
            stream_name, line = stream_queue.get(timeout=0.1)
            saw_update = True
        except queue.Empty:
            stream_name = ""
            line = None

        if stream_name:
            if line is None:
                closed_streams.add(stream_name)
            else:
                if stream_name == "stdout":
                    stdout_chunks.append(line)
                else:
                    stderr_chunks.append(line)
                parsed_event = _parse_codex_json_line(line)
                if parsed_event is not None:
                    events.append(parsed_event)
                    last_event_at = time.perf_counter()

        if supervision_callback is not None and termination_decision is None:
            current_time = time.perf_counter()
            if saw_update or current_time - last_snapshot_at >= 0.25:
                snapshot = _build_codex_exec_live_snapshot(
                    events=events,
                    started_at=started_at,
                    last_event_at=last_event_at,
                    timeout_seconds=normalized_timeout,
                    workspace_mode=workspace_mode,
                )
                decision = supervision_callback(snapshot)
                last_snapshot_at = current_time
                if (
                    isinstance(decision, CodexExecSupervisionDecision)
                    and decision.action == "terminate"
                ):
                    termination_decision = decision
                    normalized_supervision_state = str(
                        decision.supervision_state or ""
                    ).strip().lower()
                    if (
                        workspace_mode == "taskfile"
                        and normalized_supervision_state.startswith("completed")
                    ):
                        graceful_termination_deadline = (
                            current_time + normalized_completed_grace
                        )
                    else:
                        _terminate_codex_process(process)

        if (
            graceful_termination_deadline is not None
            and process.poll() is None
            and current_time >= graceful_termination_deadline
        ):
            _terminate_codex_process(process)
            graceful_termination_deadline = None

        if (
            process.poll() is not None
            and {"stdout", "stderr"}.issubset(closed_streams)
            and stream_queue.empty()
        ):
            break

    for thread in reader_threads:
        thread.join(timeout=0.2)

    return _StreamedCodexProcessResult(
        returncode=int(process.returncode or 0),
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        events=tuple(events),
        termination_decision=termination_decision,
        duration_ms=int(round((time.perf_counter() - started_at) * 1000.0)),
    )


def _read_codex_stream_lines(
    stream: Any,
    stream_name: str,
    stream_queue: queue.Queue[tuple[str, str | None]],
) -> None:
    try:
        for line in iter(stream.readline, ""):
            stream_queue.put((stream_name, line))
    finally:
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass
        stream_queue.put((stream_name, None))


def _terminate_codex_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    deadline = time.perf_counter() + 1.0
    while process.poll() is None and time.perf_counter() < deadline:
        time.sleep(0.05)
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            return


def _build_codex_exec_live_snapshot(
    *,
    events: Sequence[Mapping[str, Any]],
    started_at: float,
    last_event_at: float | None,
    timeout_seconds: int | None,
    workspace_mode: DirectExecWorkspaceMode,
) -> CodexExecLiveSnapshot:
    current_time = time.perf_counter()
    live_summary = _summarize_live_codex_events(events)
    final_agent_message = assess_final_agent_message(
        _extract_last_agent_message(list(events)),
        workspace_mode=workspace_mode,
    )
    return CodexExecLiveSnapshot(
        elapsed_seconds=max(0.0, current_time - started_at),
        last_event_seconds_ago=(
            None if last_event_at is None else max(0.0, current_time - last_event_at)
        ),
        event_count=len(events),
        command_execution_count=live_summary["command_execution_count"],
        reasoning_item_count=live_summary["reasoning_item_count"],
        agent_message_count=live_summary["agent_message_count"],
        turn_completed_count=live_summary["turn_completed_count"],
        last_command=live_summary["last_command"],
        last_command_repeat_count=live_summary["last_command_repeat_count"],
        has_final_agent_message=final_agent_message.state != "absent",
        timeout_seconds=timeout_seconds,
        final_agent_message_state=final_agent_message.state,
        final_agent_message_reason=final_agent_message.reason,
        final_agent_message_text=final_agent_message.text,
        live_activity_summary=_summarize_live_activity(
            events=events,
            workspace_mode=workspace_mode,
        ),
        last_completed_command=live_summary["last_completed_command"],
        last_completed_stage_helper_command=live_summary["last_completed_stage_helper_command"],
    )


def _write_direct_exec_worker_manifest(
    *,
    workspace_root: Path,
    task_label: str | None,
    mode: DirectExecWorkspaceMode,
) -> None:
    rendered_task_label = str(task_label or "structured shard task").strip()
    has_task_file = (workspace_root / _DIRECT_EXEC_TASK_FILE_NAME).exists()
    single_file_worker_runtime = _uses_single_file_worker_runtime(
        workspace_root=workspace_root,
        mode=mode,
    )
    single_file_handoff_command = (
        _single_file_workspace_handoff_command(workspace_root=workspace_root)
        if has_task_file
        else None
    )
    single_file_task_file_payload = (
        _single_file_workspace_task_file_payload(workspace_root=workspace_root)
        if single_file_worker_runtime
        else None
    )
    has_assigned_tasks = (
        workspace_root / _DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME
    ).exists()
    has_assigned_shards = (
        workspace_root / _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME
    ).exists()
    has_packet_leasing = (workspace_root / _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME).exists()
    has_current_phase = (
        not has_packet_leasing
        and (workspace_root / _DIRECT_EXEC_CURRENT_PHASE_FILE_NAME).exists()
    )
    mirrored_tool_files = _list_workspace_relative_files(
        workspace_root / _DIRECT_EXEC_TOOLS_DIR_NAME
    )
    has_scratch_dir = (workspace_root / _DIRECT_EXEC_SCRATCH_DIR_NAME).exists()
    has_work_dir = (workspace_root / _DIRECT_EXEC_WORK_DIR_NAME).exists()
    has_repair_dir = (workspace_root / _DIRECT_EXEC_REPAIR_DIR_NAME).exists()
    if single_file_worker_runtime:
        entry_files = [_DIRECT_EXEC_TASK_FILE_NAME]
    else:
        entry_files = [_DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME]
        if has_task_file:
            entry_files.append(_DIRECT_EXEC_TASK_FILE_NAME)
        if has_assigned_tasks:
            entry_files.append(_DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME)
        if has_assigned_shards:
            entry_files.append(_DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME)
    payload = {
        "version": 1,
        "task_label": rendered_task_label,
        "workspace_mode": mode,
        "single_file_worker_runtime": single_file_worker_runtime,
        "workspace_root": str(workspace_root),
        "entry_files": entry_files,
        "task_file": _DIRECT_EXEC_TASK_FILE_NAME if has_task_file else None,
        "assigned_tasks_file": (
            None
            if single_file_worker_runtime
            else _DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME
            if has_assigned_tasks
            else None
        ),
        "assigned_shards_file": (
            None
            if single_file_worker_runtime
            else _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME
            if has_assigned_shards
            else None
        ),
        "current_phase_file": (
            _DIRECT_EXEC_CURRENT_PHASE_FILE_NAME if has_current_phase else None
        ),
        "current_phase_brief_file": (
            _DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME
            if has_current_phase
            and (workspace_root / _DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME).exists()
            else None
        ),
        "current_phase_feedback_file": (
            _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME
            if has_current_phase
            and (workspace_root / _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME).exists()
            else None
        ),
        "output_contract_file": (
            None
            if single_file_worker_runtime
            else _DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME
            if (workspace_root / _DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME).exists()
            else None
        ),
        "examples_dir": (
            None
            if single_file_worker_runtime
            else _DIRECT_EXEC_EXAMPLES_DIR_NAME
            if (workspace_root / _DIRECT_EXEC_EXAMPLES_DIR_NAME).exists()
            else None
        ),
        "tools_dir": (
            None
            if single_file_worker_runtime
            else _DIRECT_EXEC_TOOLS_DIR_NAME
            if (workspace_root / _DIRECT_EXEC_TOOLS_DIR_NAME).exists()
            else None
        ),
        "current_packet_file": (
            _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME if has_packet_leasing else None
        ),
        "current_hint_file": (
            _DIRECT_EXEC_CURRENT_HINT_FILE_NAME if has_packet_leasing else None
        ),
        "current_result_path_file": (
            _DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME if has_packet_leasing else None
        ),
        "packet_lease_status_file": (
            _DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME if has_packet_leasing else None
        ),
        "input_dir": None if single_file_worker_runtime else _DIRECT_EXEC_INPUT_DIR_NAME,
        "debug_dir": None if single_file_worker_runtime else _DIRECT_EXEC_DEBUG_DIR_NAME,
        "hints_dir": None if single_file_worker_runtime else _DIRECT_EXEC_HINTS_DIR_NAME,
        "output_dir": None if single_file_worker_runtime else _DIRECT_EXEC_OUTPUT_DIR_NAME,
        "scratch_dir": (
            None
            if single_file_worker_runtime
            else _DIRECT_EXEC_SCRATCH_DIR_NAME
            if has_scratch_dir
            else None
        ),
        "work_dir": (
            None
            if single_file_worker_runtime
            else _DIRECT_EXEC_WORK_DIR_NAME
            if has_work_dir
            else None
        ),
        "repair_dir": (
            None
            if single_file_worker_runtime
            else _DIRECT_EXEC_REPAIR_DIR_NAME
            if has_repair_dir
            else None
        ),
        "notes": [
            note
            for note in [
                "The current working directory is already the workspace root.",
                "Open named workspace files directly; do not dump whole inventories just to orient yourself.",
                (
                    (
                        "Treat `task.json` as the editable worker contract when present: open it directly, edit answer fields in place, and then run `task-handoff`; `task-status` and `task-doctor` are troubleshooting helpers."
                        if str(single_file_task_file_payload.get("stage_key") or "").strip()
                        in {"line_role", "nonrecipe_classify", "knowledge_group"}
                        else (
                            "Treat `task.json` as the editable worker contract when present: start with the repo-owned summary helper, inspect only the units you need, then edit answer fields in place and run the repo-owned same-session helper named in `task.json`."
                            if single_file_handoff_command is None
                            else f"Treat `task.json` as the editable worker contract when present: start with the repo-owned summary helper, inspect only the units you need, then edit answer fields in place and run `{single_file_handoff_command}`."
                        )
                    )
                    if has_task_file
                    else None
                ),
                (
                    "Repo-owned bookkeeping stays outside the visible task-file workspace."
                    if single_file_worker_runtime
                    else None
                ),
                (
                    "Treat `assigned_tasks.json` as the immutable ordered ownership reference."
                    if has_assigned_tasks
                    else "Treat `assigned_shards.json` as the immutable ordered ownership reference when present."
                )
                if not single_file_worker_runtime
                else None,
                (
                    "Use `work/`, `repair/`, or short-lived local temp roots such as `/tmp` for helper work, and the approved `out/` path for final results."
                    if has_work_dir or has_repair_dir
                    else "Use short-lived local temp roots such as `/tmp` for helper work, and the approved result paths for final outputs."
                ),
            ]
            if note is not None
        ],
        "workspace_shell_policy": (
            "Allow ordinary local shell use inside this workspace, including bounded "
            "`python`/`python3`/`node` transforms plus short-lived helper files in "
            "local temp roots such as `/tmp`. Block non-temp visible path escapes and "
            "obvious repo/network/package-manager tools."
        )
        if not single_file_worker_runtime
        else (
            "The happy path is direct in-place editing of `task.json` plus the "
            "repo-owned same-session helper. Local reads of `task.json` and "
            "`AGENTS.md` are allowed; ad hoc task rewrites and boundary escapes are "
            "still off-contract."
        ),
        "workspace_local_shell_examples": (
            _single_file_workspace_local_examples(
                single_file_task_file_payload,
                single_file_handoff_command=single_file_handoff_command,
            )
            if single_file_worker_runtime
            else (
            [
                (
                    "sed -n '1,120p' assigned_tasks.json"
                    if has_assigned_tasks
                    else "sed -n '1,120p' assigned_shards.json"
                ),
                (
                    "sed -n '1,80p' hints/<task_id>.md"
                    if has_assigned_tasks
                    else "sed -n '1,80p' hints/<shard_id>.md"
                ),
            ]
            + (
                [
                    "python3 tools/line_role_worker.py overview",
                ]
                if "line_role_worker.py" in mirrored_tool_files
                else [
                    "python3 -c \"from pathlib import Path; Path('out/task-001.json').write_text(Path('in/task-001.json').read_text())\"",
                    "cat <<'EOF' > /tmp/local-helper.json",
                ]
            )
        )),
        "workspace_commands_forbidden": [
            "repo/network/package-manager commands such as git, curl, wget, ssh, or package managers",
            "non-temp absolute paths outside approved local temp roots",
            "parent-directory traversal",
        ],
        "mirrored_input_files": _list_workspace_relative_files(
            workspace_root / _DIRECT_EXEC_INPUT_DIR_NAME
        ),
        "mirrored_debug_files": _list_workspace_relative_files(
            workspace_root / _DIRECT_EXEC_DEBUG_DIR_NAME
        ),
        "mirrored_hint_files": _list_workspace_relative_files(
            workspace_root / _DIRECT_EXEC_HINTS_DIR_NAME
        ),
        "mirrored_example_files": _list_workspace_relative_files(
            workspace_root / _DIRECT_EXEC_EXAMPLES_DIR_NAME
        ),
        "mirrored_tool_files": mirrored_tool_files,
        "mirrored_output_files": _list_workspace_relative_files(
            workspace_root / _DIRECT_EXEC_OUTPUT_DIR_NAME
        ),
        "mirrored_scratch_files": _list_workspace_relative_files(
            workspace_root / _DIRECT_EXEC_SCRATCH_DIR_NAME
        ),
        "mirrored_work_files": _list_workspace_relative_files(
            workspace_root / _DIRECT_EXEC_WORK_DIR_NAME
        ),
        "mirrored_repair_files": _list_workspace_relative_files(
            workspace_root / _DIRECT_EXEC_REPAIR_DIR_NAME
        ),
    }
    (workspace_root / _DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _uses_single_file_worker_runtime(
    *,
    workspace_root: Path,
    mode: DirectExecWorkspaceMode,
) -> bool:
    return mode == "taskfile" and (workspace_root / _DIRECT_EXEC_TASK_FILE_NAME).exists()


def _store_hidden_task_file_snapshot(workspace_root: Path) -> None:
    task_file_path = workspace_root / _DIRECT_EXEC_TASK_FILE_NAME
    if not task_file_path.exists():
        return
    snapshot_path = (
        workspace_root
        / _DIRECT_EXEC_INTERNAL_DIR_NAME
        / _DIRECT_EXEC_ORIGINAL_TASK_FILE_NAME
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(task_file_path, snapshot_path)


def _model_name_from_command(command: Sequence[str]) -> str:
    tokens = list(command)
    for index, value in enumerate(tokens):
        if value == "--model" and index + 1 < len(tokens):
            return str(tokens[index + 1] or "").strip()
    return ""


def _count_tokens(text: str, *, model_name: str) -> int:
    if not text:
        return 0
    if len(text) <= 100_000:
        return _count_tokens_cached(model_name, text)
    total = 0
    for index in range(0, len(text), 50_000):
        total += _count_tokens_cached(model_name, text[index : index + 50_000])
    return total


def _list_workspace_relative_files(root: Path) -> list[str]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )


@lru_cache(maxsize=None)
def _count_tokens_cached(model_name: str, text: str) -> int:
    return len(_encoding_for_model(model_name).encode(text))


@lru_cache(maxsize=None)
def _encoding_for_model(model_name: str):
    normalized_model = str(model_name or "").strip()
    if normalized_model:
        try:
            return tiktoken.encoding_for_model(normalized_model)
        except KeyError:
            pass
    return tiktoken.get_encoding("o200k_base")
