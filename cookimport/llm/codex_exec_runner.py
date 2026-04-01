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
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence

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
from .knowledge_tag_catalog import empty_grounding_payload, normalize_knowledge_tag_key
from .recipe_same_session_handoff import (
    RECIPE_SAME_SESSION_STATE_ENV,
    advance_recipe_same_session_handoff,
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
DirectExecWorkspaceMode = Literal["structured_json", "workspace_worker"]
_WORKSPACE_ALLOWED_PATH_ROOTS = {
    ".",
    "./",
    _DIRECT_EXEC_TASK_FILE_NAME,
    _DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME,
    _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME,
    _DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME,
    _DIRECT_EXEC_CURRENT_PHASE_FILE_NAME,
    _DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME,
    _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME,
    _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME,
    _DIRECT_EXEC_CURRENT_HINT_FILE_NAME,
    _DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME,
    _DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME,
    _DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME,
    _DIRECT_EXEC_INPUT_DIR_NAME,
    _DIRECT_EXEC_DEBUG_DIR_NAME,
    _DIRECT_EXEC_EXAMPLES_DIR_NAME,
    _DIRECT_EXEC_TOOLS_DIR_NAME,
    _DIRECT_EXEC_HINTS_DIR_NAME,
    _DIRECT_EXEC_LOGS_DIR_NAME,
    _DIRECT_EXEC_OUTPUT_DIR_NAME,
    _DIRECT_EXEC_SCRATCH_DIR_NAME,
    _DIRECT_EXEC_WORK_DIR_NAME,
    _DIRECT_EXEC_REPAIR_DIR_NAME,
    _DIRECT_EXEC_SHARDS_DIR_NAME,
}
_WORKSPACE_ALLOWED_NULL_SINKS = {
    "/dev/null",
}
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
_WORKSPACE_COMMAND_LOOP_MAX_COMMAND_COUNT = 300
_WORKSPACE_COMMAND_LOOP_MAX_REPEAT_COUNT = 20
_SINGLE_FILE_WORKSPACE_HELPER_MODULES = {
    "cookimport.llm.editable_task_file",
    "cookimport.llm.recipe_same_session_handoff",
    "cookimport.llm.knowledge_same_session_handoff",
    "cookimport.parsing.canonical_line_roles.same_session_handoff",
}
_SINGLE_FILE_WORKSPACE_STAGE_HELPER_MODULES = {
    "cookimport.llm.recipe_same_session_handoff",
    "cookimport.llm.knowledge_same_session_handoff",
    "cookimport.parsing.canonical_line_roles.same_session_handoff",
}
_SINGLE_FILE_WORKSPACE_INLINE_PROGRAM_EXECUTABLES = {
    "jq",
    "node",
    "perl",
    "python",
    "python3",
    "ruby",
}
_SINGLE_FILE_WORKSPACE_ALLOWED_POLICIES = {
    "single_file_repo_helper_command",
    "single_file_repo_handoff_command",
    "single_file_temp_helper_command",
}
_SINGLE_FILE_WORKSPACE_EGREGIOUS_POLICIES = {
    "single_file_task_ad_hoc_transform",
}
# These are the clearly egregious off-contract tools for long-lived workspace
# workers. Local interpreters and read-only inspection commands stay allowed.
_WORKSPACE_EGREGIOUS_BOUNDARY_EXECUTABLES = {
    "apt",
    "apt-get",
    "brew",
    "cargo",
    "curl",
    "docker",
    "kubectl",
    "npm",
    "npx",
    "pip",
    "pip3",
    "scp",
    "ssh",
    "sudo",
    "wget",
}
_WORKSPACE_EGREGIOUS_GIT_SUBCOMMANDS = {
    "am",
    "apply",
    "checkout",
    "cherry-pick",
    "clean",
    "clone",
    "commit",
    "fetch",
    "merge",
    "pull",
    "push",
    "rebase",
    "reset",
    "restore",
    "stash",
    "switch",
}
FinalAgentMessageState = Literal["absent", "informational", "malformed", "json_object"]


class CodexExecRunner(Protocol):
    def run_structured_prompt(
        self,
        *,
        prompt_text: str,
        input_payload: Mapping[str, Any] | None,
        working_dir: Path,
        env: Mapping[str, str],
        output_schema_path: Path | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: int | None = None,
        completed_termination_grace_seconds: float | None = None,
        workspace_task_label: str | None = None,
        supervision_callback: Callable[
            ["CodexExecLiveSnapshot"], "CodexExecSupervisionDecision | None"
        ]
        | None = None,
    ) -> "CodexExecRunResult":
        """Run one direct structured Codex exec call."""

    def run_workspace_worker(
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
            ["CodexExecLiveSnapshot"], "CodexExecSupervisionDecision | None"
        ]
        | None = None,
    ) -> "CodexExecRunResult":
        """Run one long-lived Codex worker session against local workspace files."""


@dataclass(frozen=True)
class CodexExecLiveSnapshot:
    elapsed_seconds: float
    last_event_seconds_ago: float | None
    event_count: int
    command_execution_count: int
    reasoning_item_count: int
    last_command: str | None
    last_command_repeat_count: int
    has_final_agent_message: bool
    agent_message_count: int = 0
    turn_completed_count: int = 0
    timeout_seconds: int | None = None
    final_agent_message_state: FinalAgentMessageState = "absent"
    final_agent_message_reason: str | None = None
    source_working_dir: str | None = None
    execution_working_dir: str | None = None
    live_activity_summary: str | None = None


@dataclass(frozen=True)
class CodexExecSupervisionDecision:
    action: str = "continue"
    reason_code: str | None = None
    reason_detail: str | None = None
    retryable: bool = False
    supervision_state: str = "watchdog_killed"

    @classmethod
    def terminate(
        cls,
        *,
        reason_code: str,
        reason_detail: str | None = None,
        retryable: bool = False,
        supervision_state: str = "watchdog_killed",
    ) -> "CodexExecSupervisionDecision":
        return cls(
            action="terminate",
            reason_code=str(reason_code).strip() or None,
            reason_detail=str(reason_detail).strip() or None,
            retryable=bool(retryable),
            supervision_state=str(supervision_state or "watchdog_killed").strip()
            or "watchdog_killed",
        )


@dataclass(frozen=True)
class FinalAgentMessageAssessment:
    state: FinalAgentMessageState
    reason: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class WorkspaceCommandClassification:
    command_text: str | None
    allowed: bool
    policy: str
    reason: str | None = None


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
    workspace_mode: DirectExecWorkspaceMode = "structured_json"
    supervision_state: str | None = None
    supervision_reason_code: str | None = None
    supervision_reason_detail: str | None = None
    supervision_retryable: bool = False

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
                if self.workspace_mode == "workspace_worker" and self.execution_working_dir
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

    def run_structured_prompt(
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
            workspace_mode="structured_json",
            sandbox_mode="read-only",
            require_final_message=True,
            sync_output_paths=(),
        )

    def run_workspace_worker(
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
            workspace_mode="workspace_worker",
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
    ) -> CodexExecRunResult:
        process_env = _merge_env(env)
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
        if workspace_mode == "workspace_worker" and single_file_worker_runtime:
            _sync_direct_exec_runtime_control_paths_to_execution(
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
                relative_paths=(_DIRECT_EXEC_INTERNAL_DIR_NAME,),
            )
            process_env = _rewrite_workspace_worker_env_paths(
                env=process_env,
                source_working_dir=working_dir,
                execution_working_dir=execution_working_dir,
            )
        if workspace_mode == "workspace_worker":
            helper_import_root = _prepare_workspace_worker_helper_imports(
                env=process_env,
                execution_working_dir=execution_working_dir,
            )
            process_env = _prepend_pythonpath(
                env=process_env,
                import_root=helper_import_root,
            )
        execution_prompt_text = rewrite_direct_exec_prompt_paths(
            prompt_text=prompt_text,
            source_working_dir=working_dir,
            execution_working_dir=execution_working_dir,
        )
        command = _build_codex_exec_command(
            cmd=self.cmd,
            working_dir=execution_working_dir,
            output_schema_path=output_schema_path,
            model=model,
            reasoning_effort=reasoning_effort,
            sandbox_mode=sandbox_mode,
        )
        subprocess_command = (
            _build_workspace_worker_fs_cage_command(
                command=command,
                working_dir=execution_working_dir,
                env=process_env,
            )
            if workspace_mode == "workspace_worker"
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
                    if workspace_mode == "workspace_worker"
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
        if workspace_mode == "workspace_worker" and not single_file_worker_runtime:
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

    def _build_workspace_task_unit_answer(
        self,
        *,
        stage_key: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        if stage_key == "recipe_refine":
            hint_payload = dict(evidence.get("hint") or {})
            legacy_input = {
                "sid": str(evidence.get("recipe_id") or "task"),
                "r": [
                    {
                        "rid": str(evidence.get("recipe_id") or "recipe"),
                        "h": {
                            "n": hint_payload.get("title"),
                            "i": list(hint_payload.get("ingredients") or []),
                            "s": list(hint_payload.get("steps") or []),
                        },
                        "txt": str(evidence.get("source_text") or ""),
                        "ev": list(evidence.get("source_rows") or []),
                    }
                ],
            }
            legacy_output = self.output_builder(legacy_input)
            recipe_row: dict[str, Any] = {}
            if isinstance(legacy_output, Mapping):
                recipe_rows = legacy_output.get("r")
                if isinstance(recipe_rows, list) and recipe_rows and isinstance(recipe_rows[0], Mapping):
                    recipe_row = dict(recipe_rows[0])
                else:
                    recipe_row = dict(legacy_output)
            canonical_recipe = recipe_row.get("cr")
            mapping_rows = recipe_row.get("m")
            return {
                "status": str(recipe_row.get("st") or "repaired"),
                "status_reason": recipe_row.get("sr"),
                "canonical_recipe": (
                    {
                        "title": canonical_recipe.get("t"),
                        "ingredients": list(canonical_recipe.get("i") or []),
                        "steps": list(canonical_recipe.get("s") or []),
                        "description": canonical_recipe.get("d"),
                        "recipe_yield": canonical_recipe.get("y"),
                    }
                    if isinstance(canonical_recipe, Mapping)
                    else None
                ),
                "ingredient_step_mapping": [
                    {
                        "ingredient_indexes": [int(mapping_row.get("i"))],
                        "step_indexes": [
                            int(value) for value in (mapping_row.get("s") or [])
                        ],
                    }
                    for mapping_row in (mapping_rows or [])
                    if isinstance(mapping_row, Mapping) and mapping_row.get("i") is not None
                ],
                "ingredient_step_mapping_reason": recipe_row.get("mr"),
                "selected_tags": [
                    str(tag_row.get("l") or "").strip()
                    for tag_row in (recipe_row.get("g") or [])
                    if isinstance(tag_row, Mapping) and str(tag_row.get("l") or "").strip()
                ],
                "warnings": [
                    str(value).strip()
                    for value in (recipe_row.get("w") or [])
                    if str(value).strip()
                ],
            }
        if stage_key in {"nonrecipe_finalize", "nonrecipe_classify"}:
            block_index = int(evidence.get("block_index") or 0)
            legacy_input = {
                "packet_id": str(evidence.get("block_id") or f"block-{block_index}"),
                "blocks": [
                    {
                        "block_index": block_index,
                        "text": str(evidence.get("text") or ""),
                    }
                ],
            }
            legacy_output = self.output_builder(legacy_input)
            decision_row: dict[str, Any] = {}
            if isinstance(legacy_output, Mapping):
                for row in legacy_output.get("block_decisions") or []:
                    if (
                        isinstance(row, Mapping)
                        and row.get("block_index") is not None
                        and int(row.get("block_index")) == block_index
                    ):
                        decision_row = dict(row)
                        break
            category = str(decision_row.get("category") or "knowledge")
            reviewer_category = str(
                decision_row.get("reviewer_category")
                or ("knowledge" if category == "knowledge" else "other")
            ).strip() or ("knowledge" if category == "knowledge" else "other")
            if stage_key == "nonrecipe_classify":
                retrieval_concept = None
                grounding_payload = empty_grounding_payload()
                if category == "knowledge":
                    retrieval_concept = str(
                        decision_row.get("retrieval_concept") or evidence.get("text") or ""
                    ).strip() or None
                    grounding_row = (
                        dict(decision_row.get("grounding") or {})
                        if isinstance(decision_row.get("grounding"), Mapping)
                        else {}
                    )
                    candidate_tag_keys = [
                        str(value).strip()
                        for value in (evidence.get("candidate_tag_keys") or [])
                        if str(value).strip()
                    ]
                    if grounding_row:
                        grounding_payload = {
                            "tag_keys": [
                                str(value).strip()
                                for value in (grounding_row.get("tag_keys") or [])
                                if str(value).strip()
                            ],
                            "category_keys": [
                                str(value).strip()
                                for value in (grounding_row.get("category_keys") or [])
                                if str(value).strip()
                            ],
                            "proposed_tags": [
                                {
                                    "key": str(tag.get("key") or "").strip(),
                                    "display_name": str(tag.get("display_name") or "").strip(),
                                    "category_key": str(tag.get("category_key") or "").strip(),
                                }
                                for tag in (grounding_row.get("proposed_tags") or [])
                                if isinstance(tag, Mapping)
                            ],
                        }
                    elif candidate_tag_keys:
                        grounding_payload = {
                            "tag_keys": candidate_tag_keys[:1],
                            "category_keys": [],
                            "proposed_tags": [],
                        }
                    else:
                        proposed_key = normalize_knowledge_tag_key(
                            " ".join(str(evidence.get("text") or "").split()[:4])
                        ) or f"knowledge-{block_index}"
                        grounding_payload = {
                            "tag_keys": [],
                            "category_keys": ["techniques"],
                            "proposed_tags": [
                                {
                                    "key": proposed_key,
                                    "display_name": (
                                        retrieval_concept[:48].strip()
                                        if retrieval_concept is not None
                                        else f"Knowledge {block_index}"
                                    ),
                                    "category_key": "techniques",
                                }
                            ],
                        }
                return {
                    "category": category,
                    "reviewer_category": reviewer_category,
                    "retrieval_concept": retrieval_concept,
                    "grounding": grounding_payload,
                }
            group_key = None
            topic_label = None
            if category == "knowledge" and isinstance(legacy_output, Mapping):
                for group in legacy_output.get("idea_groups") or []:
                    if not isinstance(group, Mapping):
                        continue
                    block_indices = [int(value) for value in (group.get("block_indices") or [])]
                    if block_index in block_indices:
                        group_key = str(group.get("group_id") or "").strip() or None
                        topic_label = str(group.get("topic_label") or "").strip() or None
                        break
            return {
                "category": category,
                "group_key": group_key,
                "topic_label": topic_label,
            }
        if stage_key == "knowledge_group":
            block_index = int(evidence.get("block_index") or 0)
            legacy_input = {
                "packet_id": str(evidence.get("block_id") or f"block-{block_index}"),
                "blocks": [
                    {
                        "block_index": block_index,
                        "text": str(evidence.get("text") or ""),
                    }
                ],
            }
            legacy_output = self.output_builder(legacy_input)
            group_key = None
            topic_label = None
            if isinstance(legacy_output, Mapping):
                for group in legacy_output.get("idea_groups") or []:
                    if not isinstance(group, Mapping):
                        continue
                    block_indices = [int(value) for value in (group.get("block_indices") or [])]
                    if block_index in block_indices:
                        group_key = str(group.get("group_id") or "").strip() or None
                        topic_label = str(group.get("topic_label") or "").strip() or None
                        break
            return {
                "group_key": group_key,
                "topic_label": topic_label,
            }
        if stage_key == "line_role":
            atomic_index = int(evidence.get("atomic_index") or 0)
            legacy_output = self.output_builder(
                {"rows": [[atomic_index, str(evidence.get("text") or "")]]}
            )
            row_payload: dict[str, Any] = {}
            if isinstance(legacy_output, Mapping):
                for row in legacy_output.get("rows") or []:
                    if (
                        isinstance(row, Mapping)
                        and row.get("atomic_index") is not None
                        and int(row.get("atomic_index")) == atomic_index
                    ):
                        row_payload = dict(row)
                        break
            return {
                "label": str(row_payload.get("label") or "NONRECIPE_CANDIDATE"),
                "exclusion_reason": row_payload.get("exclusion_reason"),
            }
        return {}

    def run_structured_prompt(
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
    ) -> CodexExecRunResult:
        self.calls.append(
            {
                "mode": "structured_prompt",
                "prompt_text": prompt_text,
                "input_payload": dict(input_payload or {}),
                "working_dir": str(working_dir),
                "output_schema_path": str(output_schema_path) if output_schema_path is not None else None,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "timeout_seconds": timeout_seconds,
                "completed_termination_grace_seconds": completed_termination_grace_seconds,
                "workspace_task_label": workspace_task_label,
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
                workspace_mode="structured_json",
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
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
            prompt_text=prompt_text,
            response_text=response_text,
            turn_failed_message=None,
            events=events,
            usage=usage,
            stdout_text="\n".join(json.dumps(event) for event in events) + "\n",
            source_working_dir=str(working_dir),
            execution_working_dir=str(working_dir),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="structured_json",
            supervision_state="completed",
        )

    def run_workspace_worker(
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
            mode="workspace_worker",
        )
        execution_working_dir = prepared_workspace.execution_working_dir
        execution_prompt_text = rewrite_direct_exec_prompt_paths(
            prompt_text=prompt_text,
            source_working_dir=working_dir,
            execution_working_dir=execution_working_dir,
        )
        self.calls.append(
            {
                "mode": "workspace_worker",
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
                workspace_mode="workspace_worker",
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
            workspace_mode="workspace_worker",
            supervision_state="completed",
        )


@dataclass(frozen=True)
class PreparedDirectExecWorkspace:
    source_working_dir: Path
    execution_working_dir: Path
    agents_path: Path


def prepare_direct_exec_workspace(
    *,
    source_working_dir: Path,
    env: Mapping[str, str] | None,
    task_label: str | None = None,
    mode: DirectExecWorkspaceMode = "structured_json",
) -> PreparedDirectExecWorkspace:
    source_root = Path(source_working_dir).resolve()
    single_file_worker_runtime = _uses_single_file_worker_runtime(
        workspace_root=source_root,
        mode=mode,
    )
    if single_file_worker_runtime:
        _store_hidden_task_file_snapshot(source_root)
    _write_direct_exec_worker_manifest(
        workspace_root=source_root,
        task_label=task_label,
        mode=mode,
    )
    execution_root_base = _resolve_direct_exec_isolation_root(env=env)
    execution_root_base.mkdir(parents=True, exist_ok=True)
    execution_root = _build_unique_execution_workspace_path(
        source_working_dir=source_root,
        execution_root_base=execution_root_base,
    )
    execution_root.mkdir(parents=True, exist_ok=False)
    _populate_direct_exec_workspace(
        source_working_dir=source_root,
        execution_working_dir=execution_root,
        task_label=task_label,
        mode=mode,
        single_file_worker_runtime=single_file_worker_runtime,
    )
    return PreparedDirectExecWorkspace(
        source_working_dir=source_root,
        execution_working_dir=execution_root,
        agents_path=execution_root / _DIRECT_EXEC_AGENTS_FILE_NAME,
    )


def build_direct_exec_workspace_manifest(
    *,
    source_working_dir: str | Path | None,
    execution_working_dir: str | Path | None,
    execution_agents_path: str | Path | None,
) -> dict[str, Any]:
    payload = {
        "source_working_dir": str(source_working_dir) if source_working_dir else None,
        "execution_working_dir": str(execution_working_dir) if execution_working_dir else None,
        "execution_agents_path": str(execution_agents_path) if execution_agents_path else None,
        "task_file_path": None,
        "assigned_tasks_path": None,
        "assigned_shards_path": None,
        "worker_manifest_path": None,
        "current_phase_path": None,
        "current_phase_brief_path": None,
        "current_phase_feedback_path": None,
        "output_contract_path": None,
        "examples_dir": None,
        "tools_dir": None,
        "current_packet_path": None,
        "current_hint_path": None,
        "current_result_path_path": None,
        "packet_lease_status_path": None,
        "scratch_dir": None,
        "work_dir": None,
        "repair_dir": None,
        "mirrored_input_files": [],
        "mirrored_debug_files": [],
        "mirrored_hint_files": [],
        "mirrored_example_files": [],
        "mirrored_tool_files": [],
        "mirrored_output_files": [],
        "mirrored_scratch_files": [],
        "mirrored_work_files": [],
        "mirrored_repair_files": [],
    }
    execution_root = (
        Path(execution_working_dir).expanduser()
        if execution_working_dir is not None and str(execution_working_dir).strip()
        else None
    )
    if execution_root is None or not execution_root.exists():
        return payload
    task_file_path = execution_root / _DIRECT_EXEC_TASK_FILE_NAME
    if task_file_path.exists():
        payload["task_file_path"] = str(task_file_path)
    assigned_tasks_path = execution_root / _DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME
    if assigned_tasks_path.exists():
        payload["assigned_tasks_path"] = str(assigned_tasks_path)
    assigned_shards_path = execution_root / _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME
    if assigned_shards_path.exists():
        payload["assigned_shards_path"] = str(assigned_shards_path)
    worker_manifest_path = execution_root / _DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME
    if worker_manifest_path.exists():
        payload["worker_manifest_path"] = str(worker_manifest_path)
    current_phase_path = execution_root / _DIRECT_EXEC_CURRENT_PHASE_FILE_NAME
    if current_phase_path.exists():
        payload["current_phase_path"] = str(current_phase_path)
    current_phase_brief_path = execution_root / _DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME
    if current_phase_brief_path.exists():
        payload["current_phase_brief_path"] = str(current_phase_brief_path)
    current_phase_feedback_path = execution_root / _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME
    if current_phase_feedback_path.exists():
        payload["current_phase_feedback_path"] = str(current_phase_feedback_path)
    output_contract_path = execution_root / _DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME
    if output_contract_path.exists():
        payload["output_contract_path"] = str(output_contract_path)
    examples_dir = execution_root / _DIRECT_EXEC_EXAMPLES_DIR_NAME
    if examples_dir.exists() and examples_dir.is_dir():
        payload["examples_dir"] = str(examples_dir)
    tools_dir = execution_root / _DIRECT_EXEC_TOOLS_DIR_NAME
    if tools_dir.exists() and tools_dir.is_dir():
        payload["tools_dir"] = str(tools_dir)
    current_packet_path = execution_root / _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME
    if current_packet_path.exists():
        payload["current_packet_path"] = str(current_packet_path)
    current_hint_path = execution_root / _DIRECT_EXEC_CURRENT_HINT_FILE_NAME
    if current_hint_path.exists():
        payload["current_hint_path"] = str(current_hint_path)
    current_result_path = execution_root / _DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME
    if current_result_path.exists():
        payload["current_result_path_path"] = str(current_result_path)
    packet_lease_status_path = execution_root / _DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME
    if packet_lease_status_path.exists():
        payload["packet_lease_status_path"] = str(packet_lease_status_path)
    scratch_dir = execution_root / _DIRECT_EXEC_SCRATCH_DIR_NAME
    if scratch_dir.exists() and scratch_dir.is_dir():
        payload["scratch_dir"] = str(scratch_dir)
    work_dir = execution_root / _DIRECT_EXEC_WORK_DIR_NAME
    if work_dir.exists() and work_dir.is_dir():
        payload["work_dir"] = str(work_dir)
    repair_dir = execution_root / _DIRECT_EXEC_REPAIR_DIR_NAME
    if repair_dir.exists() and repair_dir.is_dir():
        payload["repair_dir"] = str(repair_dir)
    payload["mirrored_input_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_INPUT_DIR_NAME
    )
    payload["mirrored_debug_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_DEBUG_DIR_NAME
    )
    payload["mirrored_hint_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_HINTS_DIR_NAME
    )
    payload["mirrored_example_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_EXAMPLES_DIR_NAME
    )
    payload["mirrored_tool_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_TOOLS_DIR_NAME
    )
    payload["mirrored_output_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_OUTPUT_DIR_NAME
    )
    payload["mirrored_scratch_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_SCRATCH_DIR_NAME
    )
    payload["mirrored_work_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_WORK_DIR_NAME
    )
    payload["mirrored_repair_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_REPAIR_DIR_NAME
    )
    return payload


def rewrite_direct_exec_prompt_paths(
    *,
    prompt_text: str,
    source_working_dir: Path,
    execution_working_dir: Path,
) -> str:
    rendered = str(prompt_text or "")
    source_text = str(Path(source_working_dir).resolve())
    execution_text = str(Path(execution_working_dir).resolve())
    if not source_text or source_text == execution_text:
        return rendered
    return rendered.replace(source_text, execution_text)


def _remap_workspace_path(
    *,
    raw_path: str,
    source_root: Path,
    execution_root: Path,
) -> str:
    candidate = Path(str(raw_path or "").strip()).expanduser()
    if not candidate.is_absolute():
        return str(raw_path)
    try:
        relative = candidate.resolve(strict=False).relative_to(source_root.resolve(strict=False))
    except ValueError:
        return str(raw_path)
    return str((execution_root / relative).resolve(strict=False))


def _rewrite_workspace_path_values(
    value: Any,
    *,
    source_root: Path,
    execution_root: Path,
) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _rewrite_workspace_path_values(
                nested_value,
                source_root=source_root,
                execution_root=execution_root,
            )
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_workspace_path_values(
                item,
                source_root=source_root,
                execution_root=execution_root,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _rewrite_workspace_path_values(
                item,
                source_root=source_root,
                execution_root=execution_root,
            )
            for item in value
        )
    if isinstance(value, str):
        return _remap_workspace_path(
            raw_path=value,
            source_root=source_root,
            execution_root=execution_root,
        )
    return value


def _rewrite_workspace_runtime_control_tree_paths(
    *,
    tree_root: Path,
    source_root: Path,
    execution_root: Path,
) -> None:
    if not tree_root.exists() or not tree_root.is_dir():
        return
    for path in tree_root.rglob("*"):
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rewritten = _rewrite_workspace_path_values(
            payload,
            source_root=source_root,
            execution_root=execution_root,
        )
        path.write_text(
            json.dumps(rewritten, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _rewrite_workspace_worker_env_paths(
    *,
    env: Mapping[str, str],
    source_working_dir: Path,
    execution_working_dir: Path,
) -> dict[str, str]:
    rewritten = {str(key): str(value) for key, value in env.items()}
    source_root = Path(source_working_dir).resolve(strict=False)
    execution_root = Path(execution_working_dir).resolve(strict=False)
    for key in _DIRECT_EXEC_WORKSPACE_MIRRORED_PATH_ENV_KEYS:
        raw_value = str(rewritten.get(key) or "").strip()
        if not raw_value:
            continue
        rewritten[key] = _remap_workspace_path(
            raw_path=raw_value,
            source_root=source_root,
            execution_root=execution_root,
        )
    return rewritten


def _resolve_direct_exec_isolation_root(*, env: Mapping[str, str] | None) -> Path:
    explicit_env = {
        str(key): str(value)
        for key, value in (env or {}).items()
    }
    resolved_codex_home = _resolve_recipeimport_codex_home(explicit_env=explicit_env)
    base_root = (
        Path(resolved_codex_home).expanduser()
        if resolved_codex_home
        else Path.home() / ".codex-recipe"
    )
    return base_root / _DIRECT_EXEC_ISOLATION_ROOT_NAME


def _resolve_direct_exec_helper_imports_root(*, env: Mapping[str, str] | None) -> Path:
    explicit_env = {
        str(key): str(value)
        for key, value in (env or {}).items()
    }
    resolved_codex_home = _resolve_recipeimport_codex_home(explicit_env=explicit_env)
    base_root = (
        Path(resolved_codex_home).expanduser()
        if resolved_codex_home
        else Path.home() / ".codex-recipe"
    )
    return base_root / _DIRECT_EXEC_HELPER_IMPORTS_ROOT_NAME


def _build_unique_execution_workspace_path(
    *,
    source_working_dir: Path,
    execution_root_base: Path,
) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H.%M.%S")
    source_name = _sanitize_direct_exec_workspace_component(
        source_working_dir.name or "worker"
    )
    path_digest = hashlib.sha1(str(source_working_dir).encode("utf-8")).hexdigest()[:8]
    token = uuid.uuid4().hex[:8]
    return execution_root_base / f"{timestamp}-{source_name}-{path_digest}-{token}"


def _sanitize_direct_exec_workspace_component(value: str) -> str:
    cleaned = []
    for character in str(value or ""):
        if character.isalnum() or character in {"-", "_"}:
            cleaned.append(character)
        else:
            cleaned.append("-")
    rendered = "".join(cleaned).strip("-_")
    return rendered or "worker"


def _prepare_workspace_worker_helper_imports(
    *,
    env: Mapping[str, str],
    execution_working_dir: Path,
) -> Path:
    helper_imports_root = _resolve_direct_exec_helper_imports_root(env=env)
    helper_imports_root.mkdir(parents=True, exist_ok=True)
    helper_session_root = helper_imports_root / execution_working_dir.name
    helper_package_root = helper_session_root / "cookimport"
    if helper_package_root.exists():
        return helper_session_root
    source_package_root = Path(__file__).resolve().parents[1]
    shutil.copytree(
        source_package_root,
        helper_package_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    return helper_session_root


def _prepend_pythonpath(
    *,
    env: Mapping[str, str],
    import_root: Path,
) -> dict[str, str]:
    merged = {str(key): str(value) for key, value in env.items()}
    existing = str(merged.get("PYTHONPATH") or "").strip()
    entries = [str(import_root)]
    if existing:
        entries.extend(
            entry
            for entry in existing.split(":")
            if str(entry).strip()
        )
    merged["PYTHONPATH"] = ":".join(entries)
    return merged


def _populate_direct_exec_workspace(
    *,
    source_working_dir: Path,
    execution_working_dir: Path,
    task_label: str | None,
    mode: DirectExecWorkspaceMode,
    single_file_worker_runtime: bool = False,
) -> None:
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_TASK_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_TASK_FILE_NAME,
    )
    single_file_handoff_command = (
        _single_file_workspace_handoff_command(workspace_root=source_working_dir)
        if single_file_worker_runtime
        else None
    )
    if single_file_worker_runtime:
        agents_path = execution_working_dir / _DIRECT_EXEC_AGENTS_FILE_NAME
        agents_path.write_text(
            _build_direct_exec_agents_text(
                task_label=task_label,
                mode=mode,
                single_file_worker_runtime=single_file_worker_runtime,
                single_file_handoff_command=single_file_handoff_command,
            ),
            encoding="utf-8",
        )
        return
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_CURRENT_PHASE_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_CURRENT_PHASE_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_CURRENT_PACKET_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_CURRENT_HINT_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_CURRENT_HINT_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME,
    )
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_INPUT_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_INPUT_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_DEBUG_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_DEBUG_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_EXAMPLES_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_EXAMPLES_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_TOOLS_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_TOOLS_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_HINTS_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_HINTS_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_OUTPUT_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_OUTPUT_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_SCRATCH_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_SCRATCH_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_WORK_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_WORK_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_REPAIR_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_REPAIR_DIR_NAME,
    )
    (execution_working_dir / _DIRECT_EXEC_LOGS_DIR_NAME).mkdir(parents=True, exist_ok=True)
    (execution_working_dir / _DIRECT_EXEC_SHARDS_DIR_NAME).mkdir(parents=True, exist_ok=True)
    agents_path = execution_working_dir / _DIRECT_EXEC_AGENTS_FILE_NAME
    agents_path.write_text(
        _build_direct_exec_agents_text(
            task_label=task_label,
            mode=mode,
            single_file_worker_runtime=single_file_worker_runtime,
            single_file_handoff_command=single_file_handoff_command,
        ),
        encoding="utf-8",
    )


def _copy_if_present(source: Path, destination: Path) -> None:
    if not source.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree_if_present(source: Path, destination: Path) -> None:
    if not source.exists() or not source.is_dir():
        return
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _read_workspace_manifest_rows(*, execution_working_dir: Path) -> list[Any]:
    task_file_path = execution_working_dir / _DIRECT_EXEC_TASK_FILE_NAME
    if task_file_path.exists():
        try:
            task_file_payload = load_task_file(task_file_path)
        except Exception:  # noqa: BLE001
            task_file_payload = {}
        units_payload = task_file_payload.get("units")
        if isinstance(units_payload, list):
            return units_payload
    assigned_tasks_path = execution_working_dir / _DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME
    if assigned_tasks_path.exists():
        try:
            assigned_tasks = json.loads(assigned_tasks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            assigned_tasks = []
        if isinstance(assigned_tasks, list):
            return assigned_tasks
    assigned_shards_path = execution_working_dir / _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME
    if assigned_shards_path.exists():
        try:
            assigned_shards = json.loads(assigned_shards_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            assigned_shards = []
        if isinstance(assigned_shards, list):
            return assigned_shards
    return []


def _single_file_workspace_handoff_command(*, workspace_root: Path) -> str | None:
    task_file_path = workspace_root / _DIRECT_EXEC_TASK_FILE_NAME
    if not task_file_path.exists():
        return None
    try:
        task_file_payload = load_task_file(task_file_path)
    except Exception:  # noqa: BLE001
        return None
    helper_commands = task_file_payload.get("helper_commands")
    if not isinstance(helper_commands, Mapping):
        return None
    handoff_command = str(helper_commands.get("handoff") or "").strip()
    return handoff_command or None


def _build_direct_exec_agents_text(
    *,
    task_label: str | None,
    mode: DirectExecWorkspaceMode,
    single_file_worker_runtime: bool = False,
    single_file_handoff_command: str | None = None,
) -> str:
    rendered_task_label = str(task_label or "structured shard task").strip()
    if mode == "workspace_worker":
        if single_file_worker_runtime:
            handoff_instruction = (
                "run the repo-owned same-session helper command from "
                f"`task.json` (`{single_file_handoff_command}`), then stop.\n"
                if single_file_handoff_command
                else "run the repo-owned same-session helper command named in `task.json`, then stop.\n"
            )
            return (
                "# RecipeImport Direct Codex Worker\n\n"
                "This directory is an isolated runtime workspace for one RecipeImport "
                f"{rendered_task_label}.\n\n"
                "You are not working on the RecipeImport repository itself.\n"
                "Use only the files inside this directory.\n"
                "The current working directory is already the workspace root.\n"
                "This workspace exposes one repo-written file: `task.json`.\n"
                "Start with `python3 -m cookimport.llm.editable_task_file --summary`.\n"
                "If you need specific unit payloads, use `python3 -m cookimport.llm.editable_task_file --show-unit <unit_id>` or `python3 -m cookimport.llm.editable_task_file --show-unanswered --limit 5`.\n"
                "If you want to apply several answers at once, use `python3 -m cookimport.llm.editable_task_file --apply-answers-file answers.json` instead of scripting a rewrite.\n"
                "Then edit only `/units/*/answer`, save the same file, and "
                f"{handoff_instruction}"
                "`task.json` is the whole job. You do not need to discover extra control state, hidden files, or repo context before editing it.\n"
                "Treat everything outside `task.json` as immutable infrastructure, not task context.\n"
                "If you briefly reread part of `task.json` or make a small local false start, just correct course and continue; deterministic validation happens after you save.\n"
                "Do not invent helper ledgers, alternate output files, queue files, or repair sidecars.\n"
                "Do not dump the whole task file with `cat` or `sed`, do not use `ls` or `find` just to orient yourself, and do not write ad hoc inline Python, Node, or heredoc rewrites against `task.json`.\n"
                "Do not inspect parent directories, repository-wide AGENTS files, project docs, or source code.\n"
                "Do not run repo-specific commands such as `npm run docs:list` or `git`.\n"
                "Do not reach for shell on the happy path. If a tiny local temp helper is truly necessary, keep it grounded on `task.json` and local temp files only.\n"
                "Hard boundaries still apply: stay inside this workspace, keep paths local or in approved temp roots, and avoid repo/network/package-manager commands such as `git`, `curl`, or `npm`.\n"
                "Do not modify immutable evidence or metadata fields.\n"
            )
        return (
            "# RecipeImport Direct Codex Worker\n\n"
            "This directory is an isolated runtime workspace for one RecipeImport "
            f"{rendered_task_label}.\n\n"
            "You are not working on the RecipeImport repository itself.\n"
            "Use only the files inside this directory.\n"
            "The current working directory is already the workspace root.\n"
            "If `task.json` exists, start with `python3 -m cookimport.llm.editable_task_file --summary`, inspect only the units you need with `--show-unit <unit_id>` or `--show-unanswered --limit 5`, edit only its answer fields in place, save the same file, and stop.\n"
            "If `task.json` is absent, fall back to the repo-written file named in `worker_manifest.json`.\n"
            "When `OUTPUT_CONTRACT.md` or `examples/` exists, treat those repo-written files as the authoritative output-shape reference.\n"
            "When `tools/` exists, prefer its repo-written helper CLI or scripts before inventing ad hoc local transforms.\n"
            "Prefer reading the local task file directly instead of opening helper manifests or inventories just to orient yourself.\n"
            "When the repo gives you only `task.json`, that file already contains the evidence, hints, and editable answer slots you need.\n"
            "Use `scratch/` or short-lived local temp files such as `/tmp` or `/var/tmp` for bounded helper files.\n"
            "Do not inspect parent directories, repository-wide AGENTS files, project docs, or source code.\n"
            "Do not run repo-specific commands such as `npm run docs:list` or `git`.\n"
            "Prefer opening the named files directly instead of exploring the workspace or dumping whole manifests just to orient yourself.\n"
            "The happy path is file-first: open the named files directly and write only the approved stable output paths.\n"
            "Do not reach for shell on the happy path. If a tiny local helper is truly necessary, keep it narrowly grounded on prompt-named files and avoid inventing schedulers or control files.\n"
            "The watchdog is boundary-based: stay inside this workspace, keep every visible path local or in approved temp roots, and avoid repo/network/package-manager commands such as `git`, `curl`, or `npm`.\n"
            "Do not inspect parent directories or the repository, and do not leave this workspace.\n"
            "Do not modify immutable input files unless the prompt explicitly allows it.\n"
            "When the workspace offers repo-written helpers, start with the smallest prompt-named helper surface first and treat broader recovery helpers as fallback, not routine startup.\n"
        )
    return (
        "# RecipeImport Direct Codex Worker\n\n"
        "This directory is an isolated runtime workspace for one RecipeImport "
        f"{rendered_task_label}.\n\n"
        "You are not working on the RecipeImport repository itself.\n"
        "Follow only the user prompt and the files in this directory.\n"
        "Do not inspect parent directories, repository-wide AGENTS files, project docs, or source code.\n"
        "Do not run repo-specific commands such as `npm run docs:list`, `git`, or broad search commands.\n"
        "Assume any authoritative task data needed for the answer is already present in the prompt unless it explicitly tells you otherwise.\n"
        "Do not inspect local files or run discovery commands just to orient yourself.\n"
        "Do not write or modify files unless the prompt explicitly requires a local scratch file.\n"
        "Return only the final JSON shape requested by the prompt.\n"
    )


def _sync_direct_exec_workspace_paths(
    *,
    source_working_dir: Path,
    execution_working_dir: Path,
    relative_paths: Sequence[str],
) -> None:
    source_root = Path(source_working_dir).resolve()
    execution_root = Path(execution_working_dir).resolve()
    for relative_path in relative_paths:
        cleaned = str(relative_path or "").strip()
        if not cleaned:
            continue
        source_path = source_root / cleaned
        execution_path = execution_root / cleaned
        if execution_path.is_dir():
            source_path.mkdir(parents=True, exist_ok=True)
            shutil.copytree(execution_path, source_path, dirs_exist_ok=True)
            if cleaned == _DIRECT_EXEC_INTERNAL_DIR_NAME:
                _rewrite_workspace_runtime_control_tree_paths(
                    tree_root=source_path,
                    source_root=execution_root,
                    execution_root=source_root,
                )
        elif execution_path.is_file():
            source_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(execution_path, source_path)


def _sync_direct_exec_runtime_control_paths_to_execution(
    *,
    source_working_dir: Path,
    execution_working_dir: Path,
    relative_paths: Sequence[str],
) -> None:
    source_root = Path(source_working_dir).resolve()
    execution_root = Path(execution_working_dir).resolve()
    for relative_path in relative_paths:
        cleaned = str(relative_path or "").strip()
        if not cleaned:
            continue
        source_path = source_root / cleaned
        execution_path = execution_root / cleaned
        if source_path.is_dir():
            execution_path.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_path, execution_path, dirs_exist_ok=True)
            if cleaned == _DIRECT_EXEC_INTERNAL_DIR_NAME:
                _rewrite_workspace_runtime_control_tree_paths(
                    tree_root=execution_path,
                    source_root=source_root,
                    execution_root=execution_root,
                )
            continue
        if source_path.is_file():
            execution_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, execution_path)
            continue
        if execution_path.is_dir():
            shutil.rmtree(execution_path)
        elif execution_path.exists():
            execution_path.unlink()


def _looks_like_editable_task_file_payload(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    schema_version = str(value.get("schema_version") or "").strip()
    if schema_version == TASK_FILE_SCHEMA_VERSION:
        return True
    return (
        schema_version in {"knowledge_block_classify.v1", "knowledge_group_only.v1"}
        and isinstance(value.get("units"), list)
        and isinstance(value.get("editable_json_pointers"), list)
    )


def _build_codex_exec_command(
    *,
    cmd: str,
    working_dir: Path,
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    sandbox_mode: str = "read-only",
) -> list[str]:
    try:
        tokens = shlex.split(str(cmd).strip())
    except ValueError as exc:
        raise CodexFarmRunnerError(f"Invalid codex exec command: {cmd!r}") from exc
    if not tokens:
        tokens = ["codex", "exec"]
    executable = tokens[0]
    argv = tokens[1:]
    if not argv or argv[0] not in {"exec", "e"}:
        argv = ["exec", *argv]
    if argv and argv[-1] == "-":
        argv = argv[:-1]
    command = [executable, *argv]
    command.extend(
        [
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            str(sandbox_mode or "read-only"),
        ]
    )
    command.extend(["--cd", str(working_dir)])
    if output_schema_path is not None:
        command.extend(["--output-schema", str(output_schema_path)])
    if model:
        command.extend(["--model", str(model)])
    if reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    command.append("-")
    return command


@lru_cache(maxsize=1)
def _workspace_worker_fs_cage_unshare_path() -> str | None:
    resolved = shutil.which("unshare")
    if not resolved:
        return None
    return str(Path(resolved).expanduser())


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_workspace_worker_command_path(
    *,
    token: str,
    env: Mapping[str, str],
) -> Path | None:
    cleaned = str(token or "").strip()
    if not cleaned:
        return None
    candidate = Path(cleaned).expanduser()
    if candidate.is_absolute():
        return candidate
    resolved = shutil.which(cleaned, path=str(env.get("PATH") or ""))
    if not resolved:
        return None
    return Path(resolved).expanduser()


def _workspace_worker_preserved_toolchain_root(
    *,
    executable_path: Path | None,
    user_home: Path,
) -> Path | None:
    if executable_path is None:
        return None
    resolved_executable = executable_path.resolve(strict=False)
    candidate = executable_path.parent
    while _path_is_within(candidate, user_home) and candidate != user_home:
        if _path_is_within(resolved_executable, candidate):
            return candidate
        candidate = candidate.parent
    if _path_is_within(resolved_executable.parent, user_home):
        return resolved_executable.parent
    if _path_is_within(executable_path.parent, user_home):
        return executable_path.parent
    return None


def _workspace_worker_preserved_virtualenv_root(
    *,
    env: Mapping[str, str],
    user_home: Path,
) -> Path | None:
    explicit_virtual_env = str(env.get("VIRTUAL_ENV") or "").strip()
    if explicit_virtual_env:
        candidate = Path(explicit_virtual_env).expanduser().resolve(strict=False)
        if _path_is_within(candidate, user_home):
            return candidate
    current_python = Path(sys.executable).expanduser().resolve(strict=False)
    if current_python.parent.name == "bin":
        candidate = current_python.parent.parent
        if _path_is_within(candidate, user_home):
            return candidate
    return None


def _build_workspace_worker_fs_cage_command(
    *,
    command: Sequence[str],
    working_dir: Path,
    env: Mapping[str, str],
) -> list[str]:
    unshare_path = _workspace_worker_fs_cage_unshare_path()
    if not unshare_path:
        raise CodexFarmRunnerError(
            "workspace-worker filesystem isolation requires `unshare`, but it was not found"
        )

    explicit_env = {str(key): str(value) for key, value in (env or {}).items()}
    resolved_codex_home = _resolve_recipeimport_codex_home(explicit_env=explicit_env)
    codex_home = (
        Path(resolved_codex_home).expanduser().resolve(strict=False)
        if resolved_codex_home
        else (Path.home() / ".codex-recipe").resolve(strict=False)
    )
    workspace_root = Path(working_dir).expanduser().resolve(strict=False)
    direct_exec_root = _resolve_direct_exec_isolation_root(env=explicit_env).resolve(strict=False)
    try:
        workspace_root.relative_to(direct_exec_root)
    except ValueError as exc:
        raise CodexFarmRunnerError(
            "workspace-worker filesystem isolation expected the execution cwd to live "
            f"under {direct_exec_root}, got {workspace_root}"
        ) from exc

    user_home = Path.home().expanduser().resolve(strict=False)
    resolved_command = [str(token) for token in command]
    resolved_executable_path = _resolve_workspace_worker_command_path(
        token=resolved_command[0] if resolved_command else "",
        env=explicit_env,
    )
    if resolved_command and resolved_executable_path is not None:
        resolved_command[0] = str(resolved_executable_path)
    preserved_toolchain_root = _workspace_worker_preserved_toolchain_root(
        executable_path=resolved_executable_path,
        user_home=user_home,
    )
    preserved_virtualenv_root = _workspace_worker_preserved_virtualenv_root(
        env=explicit_env,
        user_home=user_home,
    )
    quoted_workspace_root = shlex.quote(str(workspace_root))
    quoted_codex_home = shlex.quote(str(codex_home))
    quoted_direct_exec_root = shlex.quote(str(direct_exec_root))
    quoted_user_home = shlex.quote(str(user_home))
    mktemp_template = shlex.quote(workspace_fs_cage_mktemp_template(env=explicit_env))
    shell_lines = [
        "set -eu",
        f"stage_dir=$(mktemp -d {mktemp_template})",
        "cleanup() {",
        '  umount "$stage_dir/ws" >/dev/null 2>&1 || true',
        '  umount "$stage_dir/codex" >/dev/null 2>&1 || true',
    ]
    if preserved_toolchain_root is not None:
        shell_lines.append('  umount "$stage_dir/toolchain" >/dev/null 2>&1 || true')
    if preserved_virtualenv_root is not None:
        shell_lines.append('  umount "$stage_dir/venv" >/dev/null 2>&1 || true')
    shell_lines.extend(
        [
            '  rm -rf "$stage_dir"',
            "}",
            "trap cleanup EXIT",
            'mkdir -p "$stage_dir/ws" "$stage_dir/codex"',
            f'mount --bind {quoted_workspace_root} "$stage_dir/ws"',
            f'mount --bind {quoted_codex_home} "$stage_dir/codex"',
        ]
    )
    if preserved_toolchain_root is not None:
        quoted_toolchain_root = shlex.quote(str(preserved_toolchain_root))
        shell_lines.extend(
            [
                'mkdir -p "$stage_dir/toolchain"',
                f'mount --bind {quoted_toolchain_root} "$stage_dir/toolchain"',
            ]
        )
    if preserved_virtualenv_root is not None:
        quoted_virtualenv_root = shlex.quote(str(preserved_virtualenv_root))
        shell_lines.extend(
            [
                'mkdir -p "$stage_dir/venv"',
                f'mount --bind {quoted_virtualenv_root} "$stage_dir/venv"',
            ]
        )
    shell_lines.extend(
        [
            "mount --make-rprivate /",
            f"mount -t tmpfs tmpfs {quoted_user_home}",
            f"mkdir -p {quoted_codex_home}",
            f'mount --bind "$stage_dir/codex" {quoted_codex_home}',
        ]
    )
    if preserved_toolchain_root is not None:
        shell_lines.extend(
            [
                f"mkdir -p {quoted_toolchain_root}",
                f'mount --bind "$stage_dir/toolchain" {quoted_toolchain_root}',
            ]
        )
    if preserved_virtualenv_root is not None:
        shell_lines.extend(
            [
                f"mkdir -p {quoted_virtualenv_root}",
                f'mount --bind "$stage_dir/venv" {quoted_virtualenv_root}',
            ]
        )
    shell_lines.extend(
        [
            f"mkdir -p {quoted_direct_exec_root}",
            f"mount -t tmpfs tmpfs {quoted_direct_exec_root}",
            f"mkdir -p {quoted_workspace_root}",
            f'mount --bind "$stage_dir/ws" {quoted_workspace_root}',
            'umount "$stage_dir/ws"',
            'umount "$stage_dir/codex"',
        ]
    )
    if preserved_toolchain_root is not None:
        shell_lines.append('umount "$stage_dir/toolchain"')
    if preserved_virtualenv_root is not None:
        shell_lines.append('umount "$stage_dir/venv"')
    shell_lines.extend(
        [
            'rmdir "$stage_dir/ws" "$stage_dir/codex"',
            'rmdir "$stage_dir/toolchain" 2>/dev/null || true',
            'rmdir "$stage_dir/venv" 2>/dev/null || true',
            f"export HOME={quoted_workspace_root}",
            f"export CODEX_HOME={quoted_codex_home}",
            '"$@"',
        ]
    )
    shell_script = "\n".join(shell_lines)
    return [
        unshare_path,
        # Keep the host network namespace; `codex exec` needs outbound API access.
        "-Urm",
        "bash",
        "-lc",
        shell_script,
        "__recipeimport_workspace_fs_cage__",
        *resolved_command,
    ]


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
    if workspace_mode != "workspace_worker" or not sync_output_paths:
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
                        workspace_mode == "workspace_worker"
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
        live_activity_summary=_summarize_live_activity(
            events=events,
            workspace_mode=workspace_mode,
        ),
    )


def summarize_direct_telemetry_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary = {
        "call_count": len(rows),
        "duration_total_ms": 0,
        "tokens_input": 0,
        "tokens_cached_input": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
        "tokens_total": 0,
        "visible_input_tokens": 0,
        "visible_output_tokens": 0,
        "wrapper_overhead_tokens": 0,
        "command_execution_count_total": 0,
        "reasoning_item_count_total": 0,
        "command_execution_tokens_total": 0,
        "reasoning_heavy_tokens_total": 0,
        "invalid_output_tokens_total": 0,
        "workspace_worker_row_count": 0,
        "workspace_worker_session_count": 0,
        "structured_followup_call_count": 0,
        "structured_followup_tokens_total": 0,
        "command_policy_counts": {},
        "watchdog_recovered_shard_count": 0,
    }
    prompt_input_mode_counts: dict[str, int] = {}
    command_executing_shards: set[str] = set()
    reasoning_heavy_shards: set[str] = set()
    invalid_output_shards: set[str] = set()
    no_final_output_shards: set[str] = set()
    missing_output_shards: set[str] = set()
    repaired_shards: set[str] = set()
    preflight_rejected_shards: set[str] = set()
    watchdog_killed_shards: set[str] = set()
    watchdog_recovered_shards: set[str] = set()
    pathological_shards: set[str] = set()
    token_usage_available_call_count = 0
    token_usage_missing_call_count = 0
    for row in rows:
        summary["duration_total_ms"] += int(row.get("duration_ms") or 0)
        summary["tokens_input"] += int(row.get("tokens_input") or 0)
        summary["tokens_cached_input"] += int(row.get("tokens_cached_input") or 0)
        summary["tokens_output"] += int(row.get("tokens_output") or 0)
        summary["tokens_reasoning"] += int(row.get("tokens_reasoning") or 0)
        summary["tokens_total"] += int(row.get("tokens_total") or 0)
        summary["visible_input_tokens"] += int(row.get("visible_input_tokens") or 0)
        summary["visible_output_tokens"] += int(row.get("visible_output_tokens") or 0)
        summary["wrapper_overhead_tokens"] += int(row.get("wrapper_overhead_tokens") or 0)
        shard_id = str(row.get("task_id") or "").strip()
        tokens_total = int(row.get("tokens_total") or 0)
        prompt_input_mode = str(row.get("prompt_input_mode") or "path").strip().lower() or "path"
        prompt_input_mode_counts[prompt_input_mode] = (
            int(prompt_input_mode_counts.get(prompt_input_mode) or 0) + 1
        )
        if _row_has_any_token_usage(row):
            token_usage_available_call_count += 1
        elif _row_looks_like_missing_token_usage(row):
            token_usage_missing_call_count += 1
        if prompt_input_mode == "workspace_worker":
            summary["workspace_worker_row_count"] += 1
            if bool(row.get("worker_session_primary_row")):
                summary["workspace_worker_session_count"] += 1
        if prompt_input_mode in {
            "inline_watchdog_retry",
            "inline_retry",
            "inline_repair",
            "inline_snippet_repair",
        }:
            summary["structured_followup_call_count"] += 1
            summary["structured_followup_tokens_total"] += tokens_total
        command_execution_count = int(row.get("command_execution_count") or 0)
        command_policy_counts = row.get("command_execution_policy_counts")
        if isinstance(command_policy_counts, Mapping):
            aggregate = dict(summary.get("command_policy_counts") or {})
            for key, value in command_policy_counts.items():
                policy = str(key or "").strip()
                if not policy:
                    continue
                aggregate[policy] = int(aggregate.get(policy) or 0) + int(value or 0)
            summary["command_policy_counts"] = aggregate
        reasoning_item_count = int(row.get("reasoning_item_count") or 0)
        summary["command_execution_count_total"] += command_execution_count
        summary["reasoning_item_count_total"] += reasoning_item_count
        if command_execution_count > 0:
            summary["command_execution_tokens_total"] += tokens_total
            if shard_id:
                command_executing_shards.add(shard_id)
                pathological_shards.add(shard_id)
        if reasoning_item_count > 0 or int(row.get("tokens_reasoning") or 0) > 0:
            summary["reasoning_heavy_tokens_total"] += tokens_total
            if shard_id:
                reasoning_heavy_shards.add(shard_id)
                pathological_shards.add(shard_id)
        proposal_status = str(
            row.get("final_proposal_status") or row.get("proposal_status") or ""
        ).strip().lower()
        if proposal_status == "invalid":
            summary["invalid_output_tokens_total"] += tokens_total
            if shard_id:
                invalid_output_shards.add(shard_id)
                pathological_shards.add(shard_id)
        if proposal_status == "no_final_output" and shard_id:
            no_final_output_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if proposal_status == "missing_output" and shard_id:
            missing_output_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if str(row.get("repair_status") or "").strip().lower() == "repaired" and shard_id:
            repaired_shards.add(shard_id)
        effective_supervision_state = str(
            row.get("final_supervision_state") or row.get("supervision_state") or ""
        ).strip().lower()
        raw_supervision_state = str(
            row.get("raw_supervision_state") or row.get("supervision_state") or ""
        ).strip().lower()
        if effective_supervision_state == "preflight_rejected" and shard_id:
            preflight_rejected_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if effective_supervision_state == "watchdog_killed" and shard_id:
            watchdog_killed_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if (
            raw_supervision_state == "watchdog_killed"
            and effective_supervision_state != "watchdog_killed"
            and shard_id
        ):
            watchdog_recovered_shards.add(shard_id)
            pathological_shards.add(shard_id)
    summary["cost_breakdown"] = {
        "visible_input_tokens": summary["visible_input_tokens"],
        "cached_input_tokens": summary["tokens_cached_input"],
        "visible_output_tokens": summary["visible_output_tokens"],
        "wrapper_overhead_tokens": summary["wrapper_overhead_tokens"],
        "reasoning_tokens": summary["tokens_reasoning"],
        "billed_total_tokens": summary["tokens_total"],
    }
    summary["command_executing_shard_count"] = len(command_executing_shards)
    summary["reasoning_heavy_shard_count"] = len(reasoning_heavy_shards)
    summary["invalid_output_shard_count"] = len(invalid_output_shards)
    summary["no_final_output_shard_count"] = len(no_final_output_shards)
    summary["missing_output_shard_count"] = len(missing_output_shards)
    summary["repaired_shard_count"] = len(repaired_shards)
    summary["preflight_rejected_shard_count"] = len(preflight_rejected_shards)
    summary["watchdog_killed_shard_count"] = len(watchdog_killed_shards)
    summary["watchdog_recovered_shard_count"] = len(watchdog_recovered_shards)
    summary["pathological_shard_count"] = len(pathological_shards)
    summary["command_policy_counts"] = dict(
        sorted(dict(summary.get("command_policy_counts") or {}).items())
    )
    summary["prompt_input_mode_counts"] = dict(sorted(prompt_input_mode_counts.items()))
    token_usage_status = _token_usage_status_from_counts(
        available_call_count=token_usage_available_call_count,
        missing_call_count=token_usage_missing_call_count,
    )
    if token_usage_status is not None:
        summary["token_usage_status"] = token_usage_status
        summary["token_usage_available_call_count"] = token_usage_available_call_count
        summary["token_usage_missing_call_count"] = token_usage_missing_call_count
        if token_usage_status != "complete":
            for key in (
                "tokens_input",
                "tokens_cached_input",
                "tokens_output",
                "tokens_reasoning",
                "tokens_total",
                "wrapper_overhead_tokens",
                "command_execution_tokens_total",
                "reasoning_heavy_tokens_total",
                "invalid_output_tokens_total",
                "structured_followup_tokens_total",
            ):
                summary[key] = None
            summary["cost_breakdown"] = {
                "visible_input_tokens": summary["visible_input_tokens"],
                "cached_input_tokens": None,
                "visible_output_tokens": summary["visible_output_tokens"],
                "wrapper_overhead_tokens": None,
                "reasoning_tokens": None,
                "billed_total_tokens": None,
            }
    summary["pathological_flags"] = _summary_pathological_flags(summary)
    return summary


def _row_has_any_token_usage(row: Mapping[str, Any]) -> bool:
    for field in (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    ):
        value = _coerce_nonnegative_int(row.get(field))
        if value is not None and value > 0:
            return True
    return False


def _row_looks_like_missing_token_usage(row: Mapping[str, Any]) -> bool:
    if _row_has_any_token_usage(row):
        return False
    return any(
        value not in (None, "", 0, False)
        for value in (
            _coerce_nonnegative_int(row.get("duration_ms")),
            _coerce_nonnegative_int(row.get("visible_input_tokens")),
            _coerce_nonnegative_int(row.get("visible_output_tokens")),
            _coerce_nonnegative_int(row.get("codex_event_count")),
            _coerce_nonnegative_int(row.get("command_execution_count")),
            _coerce_nonnegative_int(row.get("reasoning_item_count")),
            row.get("started_at_utc"),
            row.get("finished_at_utc"),
            row.get("prompt_text"),
            row.get("output_payload_present"),
            row.get("prompt_input_mode"),
        )
    )


def _token_usage_status_from_counts(
    *,
    available_call_count: int,
    missing_call_count: int,
) -> str | None:
    if missing_call_count > 0:
        return "partial" if available_call_count > 0 else "unavailable"
    if available_call_count > 0:
        return "complete"
    return None


def _token_usage_status_from_direct_rows(rows: Sequence[Mapping[str, Any]]) -> str | None:
    available_call_count = 0
    missing_call_count = 0
    for row in rows:
        if _row_has_any_token_usage(row):
            available_call_count += 1
        elif _row_looks_like_missing_token_usage(row):
            missing_call_count += 1
    return _token_usage_status_from_counts(
        available_call_count=available_call_count,
        missing_call_count=missing_call_count,
    )


def _parse_codex_json_events(stdout_text: str | None, stderr_text: str | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for stream in (stdout_text or "", stderr_text or ""):
        for raw_line in stream.splitlines():
            payload = _parse_codex_json_line(raw_line)
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _parse_codex_json_line(line: str | None) -> dict[str, Any] | None:
    rendered = str(line or "").strip()
    if not rendered or not rendered.startswith("{"):
        return None
    try:
        payload = json.loads(rendered)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_last_agent_message(events: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str | None:
    response: str | None = None
    for payload in events:
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        text = str(item.get("text") or "").strip()
        if text:
            response = text
    return response


def assess_final_agent_message(
    message_text: str | None,
    *,
    workspace_mode: DirectExecWorkspaceMode = "structured_json",
) -> FinalAgentMessageAssessment:
    cleaned = str(message_text or "").strip()
    if not cleaned:
        return FinalAgentMessageAssessment(state="absent", text=None)
    if workspace_mode == "workspace_worker" and not cleaned.startswith("{"):
        return FinalAgentMessageAssessment(
            state="informational",
            reason="workspace worker final message is informational only",
            text=cleaned,
        )
    if not cleaned.startswith("{"):
        return FinalAgentMessageAssessment(
            state="malformed",
            reason="final agent message did not start with `{`",
            text=cleaned,
        )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return FinalAgentMessageAssessment(
            state="malformed",
            reason=f"final agent message was not valid JSON: {exc.msg}",
            text=cleaned,
        )
    if not isinstance(payload, dict):
        return FinalAgentMessageAssessment(
            state="malformed",
            reason="final agent message was valid JSON but not a JSON object",
            text=cleaned,
        )
    return FinalAgentMessageAssessment(
        state="json_object",
        reason=None,
        text=cleaned,
    )


def _extract_turn_completed_usage(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]]
) -> Mapping[str, Any] | None:
    usage_payload: Mapping[str, Any] | None = None
    for payload in events:
        if payload.get("type") == "turn.completed" and isinstance(payload.get("usage"), Mapping):
            usage_payload = payload.get("usage")
    return usage_payload


def _normalize_usage(payload: Mapping[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(payload, Mapping):
        return None
    return {
        "input_tokens": max(0, int(payload.get("input_tokens") or 0)),
        "cached_input_tokens": max(0, int(payload.get("cached_input_tokens") or 0)),
        "output_tokens": max(0, int(payload.get("output_tokens") or 0)),
        "reasoning_tokens": max(
            0,
            int(
                payload.get("reasoning_tokens")
                or payload.get("output_tokens_reasoning")
                or 0
            ),
        ),
    }


def _usage_missing_or_zero(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return True
    return all(
        int(payload.get(field) or 0) <= 0
        for field in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
        )
    )


def _extract_usage_from_text_streams(
    stdout_text: str | None,
    stderr_text: str | None,
) -> dict[str, int] | None:
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    total_pattern = re.compile(r"\btotal=\s*(\d[\d,]*)\b", re.IGNORECASE)
    input_pattern = re.compile(r"\binput=\s*(\d[\d,]*)\b", re.IGNORECASE)
    output_pattern = re.compile(r"\boutput=\s*(\d[\d,]*)\b", re.IGNORECASE)
    reasoning_pattern = re.compile(r"\breasoning\s+(\d[\d,]*)\b", re.IGNORECASE)
    cached_paren_pattern = re.compile(r"\(\+\s*(\d[\d,]*)\s+cached\)", re.IGNORECASE)
    cached_named_pattern = re.compile(r"\bcached(?:_input)?=\s*(\d[\d,]*)\b", re.IGNORECASE)
    for stream in (stdout_text or "", stderr_text or ""):
        for raw_line in reversed(stream.splitlines()):
            cleaned_line = ansi_escape.sub("", raw_line).strip()
            if "Token usage:" not in cleaned_line:
                continue
            input_match = input_pattern.search(cleaned_line)
            output_match = output_pattern.search(cleaned_line)
            if input_match is None or output_match is None:
                continue
            cached_match = cached_paren_pattern.search(cleaned_line) or cached_named_pattern.search(
                cleaned_line
            )
            reasoning_match = reasoning_pattern.search(cleaned_line)
            usage = {
                "input_tokens": int(input_match.group(1).replace(",", "")),
                "cached_input_tokens": int(cached_match.group(1).replace(",", ""))
                if cached_match is not None
                else 0,
                "output_tokens": int(output_match.group(1).replace(",", "")),
                "reasoning_tokens": int(reasoning_match.group(1).replace(",", ""))
                if reasoning_match is not None
                else 0,
            }
            total_match = total_pattern.search(cleaned_line)
            if total_match is not None:
                observed_total = int(total_match.group(1).replace(",", ""))
                component_total = (
                    usage["input_tokens"]
                    + usage["cached_input_tokens"]
                    + usage["output_tokens"]
                    + usage["reasoning_tokens"]
                )
                if observed_total <= 0 and component_total <= 0:
                    continue
            if _usage_missing_or_zero(usage):
                continue
            return usage
    return None


def _extract_turn_failed_message(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]]
) -> str | None:
    for payload in events:
        if payload.get("type") != "turn.failed":
            continue
        error_payload = payload.get("error")
        if isinstance(error_payload, Mapping):
            message = str(
                error_payload.get("message") or error_payload.get("detail") or ""
            ).strip()
            if message:
                return message
        if isinstance(error_payload, str):
            cleaned = error_payload.strip()
            if cleaned:
                return cleaned
    return None


def _summarize_failure_text(stderr_text: str | None, stdout_text: str | None) -> str | None:
    for text in (stderr_text, stdout_text):
        cleaned = str(text or "").strip()
        if cleaned:
            first_line = cleaned.splitlines()[0].strip()
            if first_line:
                return first_line
    return None


def _coerce_nonnegative_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _sum_ints(*values: int | None) -> int | None:
    total = 0
    seen = False
    for value in values:
        if value is None:
            continue
        total += int(value)
        seen = True
    return total if seen else None


def _summarize_codex_events(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    command_execution_count = 0
    reasoning_item_count = 0
    command_execution_commands: list[str] = []
    command_execution_policy_counts: dict[str, int] = {}
    command_execution_policy_by_command: list[dict[str, Any]] = []
    reasoning_item_types: list[str] = []
    seen_commands: set[str] = set()
    seen_reasoning_types: set[str] = set()
    for payload in events:
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type == "command_execution":
            command_execution_count += 1
            command_text = str(item.get("command") or "").strip()
            if command_text and command_text not in seen_commands:
                seen_commands.add(command_text)
                command_execution_commands.append(command_text)
                verdict = classify_workspace_worker_command(
                    command_text,
                    allowed_absolute_roots=allowed_absolute_roots,
                )
                command_execution_policy_counts[verdict.policy] = (
                    int(command_execution_policy_counts.get(verdict.policy) or 0) + 1
                )
                command_execution_policy_by_command.append(
                    {
                        "command": command_text,
                        "allowed": verdict.allowed,
                        "policy": verdict.policy,
                        "reason": verdict.reason,
                    }
                )
            continue
        if item_type == "reasoning":
            reasoning_item_count += 1
            outer_type = str(payload.get("type") or "").strip()
            if outer_type and outer_type not in seen_reasoning_types:
                seen_reasoning_types.add(outer_type)
                reasoning_item_types.append(outer_type)
    return {
        "command_execution_count": command_execution_count,
        "command_execution_commands": command_execution_commands,
        "command_execution_policy_counts": dict(sorted(command_execution_policy_counts.items())),
        "command_execution_policy_by_command": command_execution_policy_by_command,
        "reasoning_item_count": reasoning_item_count,
        "reasoning_item_types": reasoning_item_types,
    }


def _summarize_live_codex_events(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    command_item_ids: set[str] = set()
    command_texts: list[str] = []
    reasoning_item_count = 0
    agent_message_count = 0
    turn_completed_count = 0
    last_command: str | None = None
    last_command_repeat_count = 0
    for payload in events:
        payload_type = str(payload.get("type") or "").strip()
        if payload_type == "turn.completed":
            turn_completed_count += 1
            continue
        if payload_type not in {"item.started", "item.completed"}:
            continue
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "").strip()
        if payload_type == "item.completed" and item_type == "agent_message":
            agent_message_count += 1
            continue
        if item_type == "command_execution":
            item_id = str(item.get("id") or "").strip()
            if item_id:
                command_item_ids.add(item_id)
            command_text = str(item.get("command") or "").strip()
            if command_text:
                command_texts.append(command_text)
                if command_text == last_command:
                    last_command_repeat_count += 1
                else:
                    last_command = command_text
                    last_command_repeat_count = 1
            continue
        if payload_type == "item.completed" and item_type == "reasoning":
            reasoning_item_count += 1
    return {
        "command_execution_count": (
            len(command_item_ids) if command_item_ids else len(command_texts)
        ),
        "reasoning_item_count": reasoning_item_count,
        "agent_message_count": agent_message_count,
        "turn_completed_count": turn_completed_count,
        "last_command": last_command,
        "last_command_repeat_count": last_command_repeat_count,
    }


def _live_activity_excerpt(
    value: Any,
    *,
    max_words: int = 10,
    max_chars: int = 96,
) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    words = cleaned.split(" ")
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(".,;:") + "..."
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned or None


def _summarize_live_item_activity(
    *,
    payload_type: str,
    item: Mapping[str, Any],
    workspace_mode: DirectExecWorkspaceMode,
) -> str | None:
    item_type = str(item.get("type") or "").strip()
    if not item_type:
        return None
    if item_type == "command_execution":
        command_excerpt = _live_activity_excerpt(item.get("command"))
        if command_excerpt is None:
            return "Running command" if payload_type == "item.started" else "Ran command"
        if payload_type == "item.started":
            return f"Running `{command_excerpt}`"
        return f"Ran `{command_excerpt}`"
    if item_type == "agent_message":
        text_excerpt = _live_activity_excerpt(item.get("text"))
        if text_excerpt is None:
            return "Agent message" if payload_type == "item.completed" else None
        if workspace_mode == "workspace_worker" and text_excerpt.startswith("{"):
            return None
        return f"Message: {text_excerpt}"
    if item_type == "reasoning":
        reasoning_excerpt = (
            _live_activity_excerpt(item.get("summary_text"))
            or _live_activity_excerpt(item.get("summary"))
            or _live_activity_excerpt(item.get("text"))
            or _live_activity_excerpt(item.get("delta"))
            or _live_activity_excerpt(item.get("content"))
        )
        if reasoning_excerpt is not None:
            return f"Reasoning: {reasoning_excerpt}"
        return "Reasoning"
    if item_type == "file_change":
        changes = item.get("changes")
        if isinstance(changes, list) and changes:
            first_change = changes[0] if isinstance(changes[0], Mapping) else None
            path_excerpt = (
                _live_activity_excerpt(first_change.get("path")) if first_change else None
            )
            if path_excerpt is not None:
                return f"Updated {path_excerpt}"
        return "Updated files"
    descriptor = (
        _live_activity_excerpt(item.get("text"))
        or _live_activity_excerpt(item.get("summary"))
        or _live_activity_excerpt(item.get("delta"))
        or _live_activity_excerpt(item.get("content"))
        or _live_activity_excerpt(item.get("query"))
        or _live_activity_excerpt(item.get("path"))
        or _live_activity_excerpt(item.get("url"))
        or _live_activity_excerpt(item.get("title"))
    )
    verb = "Working on" if payload_type == "item.started" else "Completed"
    if descriptor is not None:
        return f"{verb} `{item_type}`: {descriptor}"
    return f"{verb} `{item_type}`"


def _summarize_live_activity(
    *,
    events: Sequence[Mapping[str, Any]],
    workspace_mode: DirectExecWorkspaceMode,
) -> str | None:
    lifecycle_fallback: str | None = None
    for payload in reversed(list(events)):
        payload_type = str(payload.get("type") or "").strip()
        if not payload_type:
            continue
        if "reasoning_summary" in payload_type or payload_type.startswith("response.reasoning"):
            excerpt = (
                _live_activity_excerpt(payload.get("summary_text"))
                or _live_activity_excerpt(payload.get("summary"))
                or _live_activity_excerpt(payload.get("text"))
                or _live_activity_excerpt(payload.get("delta"))
                or _live_activity_excerpt(payload.get("content"))
            )
            if excerpt is not None:
                return f"Reasoning summary: {excerpt}"
            continue
        if payload_type in {"thread.started", "thread.completed", "turn.completed", "turn.failed"}:
            if lifecycle_fallback is None:
                if payload_type == "thread.started":
                    lifecycle_fallback = "Session started"
                elif payload_type == "thread.completed":
                    lifecycle_fallback = "Session completed"
                elif payload_type == "turn.completed":
                    lifecycle_fallback = "Turn completed"
                elif payload_type == "turn.failed":
                    error_payload = payload.get("error")
                    error_excerpt = None
                    if isinstance(error_payload, Mapping):
                        error_excerpt = _live_activity_excerpt(
                            error_payload.get("message") or error_payload.get("detail")
                        )
                    else:
                        error_excerpt = _live_activity_excerpt(error_payload)
                    lifecycle_fallback = (
                        f"Turn failed: {error_excerpt}"
                        if error_excerpt is not None
                        else "Turn failed"
                    )
            continue
        if payload_type not in {"item.started", "item.completed"}:
            continue
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        summary = _summarize_live_item_activity(
            payload_type=payload_type,
            item=item,
            workspace_mode=workspace_mode,
        )
        if summary is not None:
            return summary
    return lifecycle_fallback


def _pathological_flags_for_row(
    *,
    command_execution_count: int,
    reasoning_item_count: int,
    wrapper_overhead_tokens: int,
    visible_input_tokens: int,
    visible_output_tokens: int,
) -> list[str]:
    flags: list[str] = []
    if command_execution_count > 0:
        flags.append("command_execution_detected")
    if reasoning_item_count > 0:
        flags.append("reasoning_items_detected")
    visible_total = max(0, int(visible_input_tokens) + int(visible_output_tokens))
    if wrapper_overhead_tokens > visible_total and wrapper_overhead_tokens > 0:
        flags.append("wrapper_overhead_dominant")
    return flags


def _summary_pathological_flags(summary: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    if int(summary.get("preflight_rejected_shard_count") or 0) > 0:
        flags.append("preflight_rejections_detected")
    if int(summary.get("watchdog_killed_shard_count") or 0) > 0:
        flags.append("watchdog_kills_detected")
    if int(summary.get("command_executing_shard_count") or 0) > 0:
        flags.append("command_execution_detected")
    if int(summary.get("reasoning_heavy_shard_count") or 0) > 0:
        flags.append("reasoning_heavy_detected")
    if int(summary.get("invalid_output_shard_count") or 0) > 0:
        flags.append("invalid_output_detected")
    tokens_total = int(summary.get("tokens_total") or 0)
    invalid_tokens_total = int(summary.get("invalid_output_tokens_total") or 0)
    if tokens_total > 0 and invalid_tokens_total * 2 >= tokens_total:
        flags.append("majority_invalid_output_spend")
    return flags


def format_watchdog_command_reason_detail(
    *,
    stage_label: str,
    last_command: str | None,
) -> str:
    base = f"{stage_label} attempted tool use"
    cleaned_command = str(last_command or "").strip()
    if not cleaned_command:
        return base
    if len(cleaned_command) > 160:
        cleaned_command = cleaned_command[:157].rstrip() + "..."
    return f"{base}: {cleaned_command}"


def should_terminate_workspace_command_loop(
    *,
    snapshot: CodexExecLiveSnapshot,
    max_command_count: int = _WORKSPACE_COMMAND_LOOP_MAX_COMMAND_COUNT,
    max_repeat_count: int = _WORKSPACE_COMMAND_LOOP_MAX_REPEAT_COUNT,
    recent_output_progress: bool = False,
    completed_output_count: int = 0,
) -> bool:
    if int(snapshot.command_execution_count or 0) <= 0:
        return False
    if snapshot.has_final_agent_message:
        return False
    progress_command_bonus = min(
        180,
        max(0, int(completed_output_count or 0)) * 20 + (80 if recent_output_progress else 0),
    )
    progress_repeat_bonus = min(
        12,
        max(0, int(completed_output_count or 0)) + (6 if recent_output_progress else 0),
    )
    effective_max_command_count = max(1, int(max_command_count)) + progress_command_bonus
    effective_max_repeat_count = max(1, int(max_repeat_count)) + progress_repeat_bonus
    if int(snapshot.command_execution_count or 0) >= effective_max_command_count:
        return True
    return int(snapshot.last_command_repeat_count or 0) >= effective_max_repeat_count


def _write_direct_exec_worker_manifest(
    *,
    workspace_root: Path,
    task_label: str | None,
    mode: DirectExecWorkspaceMode,
) -> None:
    rendered_task_label = str(task_label or "structured shard task").strip()
    has_task_file = (workspace_root / _DIRECT_EXEC_TASK_FILE_NAME).exists()
    single_file_handoff_command = (
        _single_file_workspace_handoff_command(workspace_root=workspace_root)
        if has_task_file
        else None
    )
    single_file_worker_runtime = _uses_single_file_worker_runtime(
        workspace_root=workspace_root,
        mode=mode,
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
                        "Treat `task.json` as the editable worker contract when present: start with the repo-owned summary helper, inspect only the units you need, then edit answer fields in place and run the repo-owned same-session helper named in `task.json`."
                        if single_file_handoff_command is None
                        else f"Treat `task.json` as the editable worker contract when present: start with the repo-owned summary helper, inspect only the units you need, then edit answer fields in place and run `{single_file_handoff_command}`."
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
            "repo-owned editable-task and same-session helpers. Bounded local temp "
            "helpers are tolerated, but raw task-file dumps, broad orientation shell, "
            "and ad hoc inline rewrites are warning-or-kill drift."
        ),
        "workspace_local_shell_examples": (
            [
                "python3 -m cookimport.llm.editable_task_file --summary",
                "python3 -m cookimport.llm.editable_task_file --show-unit <unit_id>",
                "python3 -m cookimport.llm.editable_task_file --show-unanswered --limit 5",
                "python3 -m cookimport.llm.editable_task_file --apply-answers-file answers.json",
                (
                    single_file_handoff_command
                    or "<repo helper from task.json helper_commands.handoff>"
                ),
                "cp task.json /tmp/task-backup.json",
            ]
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
    return mode == "workspace_worker" and (workspace_root / _DIRECT_EXEC_TASK_FILE_NAME).exists()


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

def format_watchdog_command_loop_reason_detail(
    *,
    stage_label: str,
    snapshot: CodexExecLiveSnapshot,
) -> str:
    base = (
        f"{stage_label} spent too many shell commands without reaching final output"
    )
    cleaned_command = str(snapshot.last_command or "").strip()
    parts = [base, f"command_count={int(snapshot.command_execution_count or 0)}"]
    if int(snapshot.last_command_repeat_count or 0) > 0:
        parts.append(f"last_command_repeat_count={int(snapshot.last_command_repeat_count or 0)}")
    if cleaned_command:
        if len(cleaned_command) > 160:
            cleaned_command = cleaned_command[:157].rstrip() + "..."
        parts.append(f"last_command={cleaned_command}")
    return "; ".join(parts)


def classify_workspace_worker_command(
    command_text: str | None,
    *,
    allow_orientation_commands: bool = True,
    allow_output_paths: bool = True,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
    single_file_worker_policy: bool = False,
) -> WorkspaceCommandClassification:
    boundary_violation = detect_workspace_worker_boundary_violation(
        command_text,
        allow_output_paths=allow_output_paths,
        allowed_absolute_roots=allowed_absolute_roots,
    )
    if boundary_violation is not None:
        return boundary_violation
    inner_tokens = _command_tokens_for_watchdog(command_text)
    cleaned_command = str(command_text or "").strip() or None
    if single_file_worker_policy:
        single_file_verdict = _classify_single_file_workspace_command(
            command_text=cleaned_command,
            tokens=inner_tokens,
        )
        if single_file_verdict is not None:
            return single_file_verdict
    egregious_verdict = _workspace_egregious_command_verdict(
        command_text=cleaned_command,
        tokens=inner_tokens,
    )
    if egregious_verdict is not None:
        return egregious_verdict
    shell_body = _extract_workspace_shell_body(command_text)
    if shell_body is not None:
        return _classify_workspace_worker_shell_script(
            shell_body=shell_body,
            command_text=cleaned_command,
            allow_orientation_commands=allow_orientation_commands,
        )
    if not inner_tokens:
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="unclassified_workspace_shell_command",
            reason=(
                "command could not be parsed confidently, but no workspace boundary "
                "violation was detected"
            ),
        )
    executable = _workspace_watchdog_executable(inner_tokens)
    if not executable:
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="unclassified_workspace_shell_command",
            reason=(
                "command could not be classified precisely, but no workspace boundary "
                "violation was detected"
            ),
        )
    if not allow_orientation_commands and executable in {"pwd", "ls", "find", "tree"}:
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=False,
            policy="forbidden_orientation_command",
            reason="orientation commands are not allowed for this workspace policy",
        )
    if executable == "pwd" and len(inner_tokens) == 1 and allow_orientation_commands:
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="tolerated_orientation_command",
            reason="`pwd` stayed inside the relaxed workspace-worker command policy",
        )
    if executable in {"ls", "find", "tree"} and allow_orientation_commands:
        for argument in inner_tokens[1:]:
            normalized_argument = _normalize_visible_workspace_path_token(argument)
            if normalized_argument is None:
                continue
            path_verdict = _classify_workspace_path_argument(
                normalized_argument,
                allow_output_paths=allow_output_paths,
                allowed_absolute_roots=allowed_absolute_roots,
            )
            if not path_verdict.allowed:
                return WorkspaceCommandClassification(
                    command_text=cleaned_command,
                    allowed=False,
                    policy=path_verdict.policy,
                    reason=path_verdict.reason,
                )
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="tolerated_orientation_command",
            reason=f"`{executable}` stayed inside the relaxed workspace-worker command policy",
        )
    return WorkspaceCommandClassification(
        command_text=cleaned_command,
        allowed=True,
        policy="tolerated_workspace_shell_command",
        reason="command stayed inside the relaxed workspace-worker command policy",
    )


def _classify_single_file_workspace_command(
    *,
    command_text: str | None,
    tokens: Sequence[str],
) -> WorkspaceCommandClassification | None:
    cleaned_command = str(command_text or "").strip() or None
    if cleaned_command is None:
        return None
    token_list = [
        str(token or "").strip() for token in tokens if str(token or "").strip()
    ]
    module_name = _workspace_watchdog_module(token_list)
    if module_name in _SINGLE_FILE_WORKSPACE_HELPER_MODULES:
        if module_name in _SINGLE_FILE_WORKSPACE_STAGE_HELPER_MODULES:
            return WorkspaceCommandClassification(
                command_text=cleaned_command,
                allowed=True,
                policy="single_file_repo_handoff_command",
                reason=(
                    "repo-owned same-session helper command stayed on the single-file "
                    "worker paved road"
                ),
            )
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_repo_helper_command",
            reason=(
                "repo-owned editable-task helper command stayed on the single-file "
                "worker paved road"
            ),
        )
    if _looks_like_single_file_temp_helper_command(token_list):
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_temp_helper_command",
            reason=(
                "single-file worker used a bounded local temp helper instead of "
                "rewriting repo-owned control files"
            ),
        )
    shell_body = _extract_workspace_shell_body(cleaned_command)
    executable = _workspace_watchdog_executable(token_list)
    if _looks_like_single_file_task_transform(
        command_text=cleaned_command,
        shell_body=shell_body,
        executable=executable,
    ):
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_task_ad_hoc_transform",
            reason=(
                "single-file workers must not use ad hoc inline programs or shell "
                "rewrites against `task.json`; edit the file directly or use the "
                "repo-owned apply helpers"
            ),
        )
    if executable in {"pwd", "ls", "find", "tree"}:
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_orientation_command",
            reason=(
                "single-file workers should start from repo-owned task helpers rather "
                "than broad shell orientation commands"
            ),
        )
    if _references_single_file_task_file(cleaned_command):
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_task_file_shell_read",
            reason=(
                "single-file workers should inspect `task.json` with repo-owned "
                "summary or narrow-read helpers instead of raw shell reads"
            ),
        )
    if shell_body is not None and _looks_like_workspace_shell_script(shell_body):
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_shell_script_command",
            reason=(
                "single-file workers should not invent shell scripts when the repo "
                "already provides helper-first task inspection and handoff commands"
            ),
        )
    if executable:
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_discouraged_shell_command",
            reason=(
                "single-file workers should stay on the helper-first task-file path "
                "instead of generic shell commands"
            ),
        )
    return None


def is_single_file_workspace_command_drift_policy(policy: str | None) -> bool:
    cleaned = str(policy or "").strip()
    return cleaned.startswith("single_file_") and cleaned not in _SINGLE_FILE_WORKSPACE_ALLOWED_POLICIES


def is_single_file_workspace_command_egregious(policy: str | None) -> bool:
    return str(policy or "").strip() in _SINGLE_FILE_WORKSPACE_EGREGIOUS_POLICIES


def detect_workspace_worker_boundary_violation(
    command_text: str | None,
    *,
    allow_output_paths: bool = True,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
) -> WorkspaceCommandClassification | None:
    cleaned_command = str(command_text or "").strip() or None
    if cleaned_command is None:
        return None
    shell_body = _extract_workspace_shell_body(command_text)
    if shell_body is not None:
        return _detect_workspace_worker_boundary_violation_in_text(
            shell_body,
            command_text=cleaned_command,
            allow_output_paths=allow_output_paths,
            allowed_absolute_roots=allowed_absolute_roots,
        )

    inner_tokens = _command_tokens_for_watchdog(command_text)
    if inner_tokens:
        return _workspace_egregious_command_verdict(
            command_text=cleaned_command,
            tokens=inner_tokens,
        )

    approximate_shell_body = _approximate_workspace_shell_body(command_text)
    if approximate_shell_body is None:
        return None
    return _detect_workspace_worker_boundary_violation_in_text(
        approximate_shell_body,
        command_text=cleaned_command,
        allow_output_paths=allow_output_paths,
        allowed_absolute_roots=allowed_absolute_roots,
    )


def is_tolerated_workspace_worker_command(
    command_text: str | None,
    *,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
) -> bool:
    return (
        detect_workspace_worker_boundary_violation(
            command_text,
            allowed_absolute_roots=allowed_absolute_roots,
        )
        is None
    )


def _extract_workspace_shell_body(command_text: str | None) -> str | None:
    cleaned = str(command_text or "").strip()
    if not cleaned:
        return None
    try:
        outer_tokens = shlex.split(cleaned)
    except ValueError:
        return None
    if not outer_tokens:
        return None
    executable = Path(outer_tokens[0]).name.lower()
    if executable in {"bash", "sh", "zsh"} and len(outer_tokens) >= 3:
        shell_flag = outer_tokens[1]
        if shell_flag in {"-lc", "-c"}:
            if len(outer_tokens) == 3:
                return str(outer_tokens[2] or "").strip() or None
            return (
                " ".join(
                    str(token or "").strip()
                    for token in outer_tokens[2:]
                    if str(token or "").strip()
                )
                or None
            )
    return None


def _command_tokens_for_watchdog(command_text: str | None) -> list[str]:
    cleaned = str(command_text or "").strip()
    if not cleaned:
        return []
    try:
        outer_tokens = shlex.split(cleaned)
    except ValueError:
        return []
    if not outer_tokens:
        return []
    executable = Path(outer_tokens[0]).name.lower()
    if executable in {"bash", "sh", "zsh"} and len(outer_tokens) >= 3:
        shell_flag = outer_tokens[1]
        if shell_flag in {"-lc", "-c"}:
            if len(outer_tokens) == 3:
                try:
                    return shlex.split(str(outer_tokens[2] or "").strip())
                except ValueError:
                    return []
            return [str(token or "").strip() for token in outer_tokens[2:] if str(token or "").strip()]
    return outer_tokens


def _approximate_workspace_shell_body(command_text: str | None) -> str | None:
    cleaned = str(command_text or "").strip()
    if not cleaned:
        return None
    match = re.match(
        r"^(?:\S+/)?(?:bash|sh|zsh)\s+-l?c\s+(?P<body>.+)$",
        cleaned,
        re.DOTALL,
    )
    if match is None:
        return cleaned
    body = str(match.group("body") or "").strip()
    if len(body) >= 2 and body[0] == body[-1] and body[0] in {"'", '"'}:
        body = body[1:-1]
    return body or None


def _classify_workspace_worker_shell_script(
    *,
    shell_body: str,
    command_text: str | None,
    allow_orientation_commands: bool,
) -> WorkspaceCommandClassification:
    executables = _workspace_shell_executables(shell_body)
    if not allow_orientation_commands and any(
        executable in {"pwd", "ls", "find", "tree"} for executable in executables
    ):
        return WorkspaceCommandClassification(
            command_text=command_text,
            allowed=False,
            policy="forbidden_orientation_command",
            reason="orientation commands are not allowed for this workspace policy",
        )
    if executables and all(
        executable in {"pwd", "ls", "find", "tree"} for executable in executables
    ):
        return WorkspaceCommandClassification(
            command_text=command_text,
            allowed=True,
            policy="tolerated_orientation_command",
            reason="orientation commands stayed inside the relaxed workspace-worker command policy",
        )
    if _looks_like_workspace_shell_script(shell_body):
        return WorkspaceCommandClassification(
            command_text=command_text,
            allowed=True,
            policy="shell_script_workspace_local",
            reason="command used a bounded local shell script shape inside the workspace",
        )
    return WorkspaceCommandClassification(
        command_text=command_text,
        allowed=True,
        policy="tolerated_workspace_shell_command",
        reason="command stayed inside the relaxed workspace-worker command policy",
    )

def _workspace_shell_executables(shell_body: str) -> list[str]:
    shell_keywords = {
        "case",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "function",
        "if",
        "in",
        "then",
        "while",
    }
    executables: list[str] = []
    for match in re.finditer(
        r"(?:^|[;\n|&()]\s*)(?:env\s+)?(?P<exe>[A-Za-z0-9_./-]+)",
        shell_body,
        re.MULTILINE,
    ):
        executable = Path(str(match.group("exe") or "").strip()).name.lower()
        if not executable or executable in shell_keywords:
            continue
        executables.append(executable)
    return executables


def _looks_like_workspace_shell_script(shell_body: str) -> bool:
    if "\n" in shell_body:
        return True
    return any(
        marker in shell_body
        for marker in ("&&", "||", "<<", "| while ", "| for ", "; do", "; then")
    ) or bool(
        re.search(r"\b(?:for|while|if|case)\b", shell_body)
    )


def _detect_workspace_worker_boundary_violation_in_text(
    shell_text: str,
    *,
    command_text: str | None,
    allow_output_paths: bool,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
) -> WorkspaceCommandClassification | None:
    stripped_text = re.sub(r"^\s*#![^\n]*(?:\n|$)", "", shell_text, flags=re.MULTILINE)
    for line in stripped_text.splitlines():
        try:
            tokens = shlex.split(line)
        except ValueError:
            tokens = []
        verdict = _workspace_egregious_command_verdict(
            command_text=command_text,
            tokens=tokens,
        )
        if verdict is not None:
            return verdict
    verdict = _workspace_egregious_command_verdict(
        command_text=command_text,
        tokens=_command_tokens_for_watchdog(command_text),
    )
    if verdict is not None:
        return verdict
    return None


def _detect_workspace_worker_boundary_violation_in_python_heredoc(
    shell_text: str,
    *,
    command_text: str | None,
    allow_output_paths: bool,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
) -> tuple[bool, WorkspaceCommandClassification | None]:
    python_body = _extract_workspace_python_heredoc_body(shell_text)
    if python_body is None:
        return False, None
    try:
        syntax_tree = ast.parse(python_body)
    except SyntaxError:
        return (
            True,
            WorkspaceCommandClassification(
                command_text=command_text,
                allowed=False,
                policy="forbidden_unparseable_python_heredoc",
                reason=(
                    "inline python heredoc could not be parsed, so workspace path "
                    "safety could not be proven"
                ),
            ),
        )
    for literal in _workspace_python_string_literals(syntax_tree):
        if not _python_literal_looks_like_workspace_path(literal):
            continue
        path_verdict = _classify_workspace_path_argument(
            literal,
            allow_output_paths=allow_output_paths,
            allowed_absolute_roots=allowed_absolute_roots,
        )
        if not path_verdict.allowed:
            return (
                True,
                WorkspaceCommandClassification(
                    command_text=command_text,
                    allowed=False,
                    policy=path_verdict.policy,
                    reason=path_verdict.reason,
                ),
            )
    return True, None


def _extract_workspace_python_heredoc_body(shell_text: str) -> str | None:
    match = re.match(
        r"^\s*(?:env\s+)?python3?\s+-\s*<<(?P<quote>['\"]?)(?P<marker>[A-Za-z_][A-Za-z0-9_]*)"
        r"(?P=quote)\s*\n(?P<body>.*)\n(?P=marker)\s*$",
        str(shell_text or "").strip(),
        re.DOTALL,
    )
    if match is None:
        return None
    return str(match.group("body") or "")


def _workspace_python_string_literals(syntax_tree: ast.AST) -> tuple[str, ...]:
    literals: list[str] = []
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literal = str(node.value or "").strip()
            if literal:
                literals.append(literal)
    return tuple(literals)


def _python_literal_looks_like_workspace_path(value: str) -> bool:
    cleaned = str(value or "").strip()
    if not cleaned:
        return False
    if cleaned in _WORKSPACE_ALLOWED_NULL_SINKS or cleaned in _WORKSPACE_ALLOWED_PATH_ROOTS:
        return True
    if cleaned.startswith(("~", "/", "./", "../")):
        return True
    if any(character.isspace() for character in cleaned):
        return False
    if "/" in cleaned:
        return True
    return cleaned.endswith(
        (
            ".json",
            ".jsonl",
            ".md",
            ".txt",
            ".csv",
            ".tsv",
            ".yaml",
            ".yml",
            ".py",
        )
    )


def _workspace_watchdog_executable(inner_tokens: Sequence[str]) -> str | None:
    if not inner_tokens:
        return None
    executable = Path(str(inner_tokens[0] or "").strip()).name.lower()
    if executable != "env":
        return executable or None
    for token in inner_tokens[1:]:
        cleaned = str(token or "").strip()
        if not cleaned or cleaned.startswith("-"):
            continue
        if "=" in cleaned and "/" not in cleaned and not cleaned.startswith((".", "/")):
            continue
        return Path(cleaned).name.lower() or None
    return executable


def _workspace_watchdog_module(tokens: Sequence[str]) -> str | None:
    token_list = [
        str(token or "").strip() for token in tokens if str(token or "").strip()
    ]
    if not token_list:
        return None
    start_index = 0
    if _workspace_watchdog_executable(token_list) == "env":
        start_index = 1
        while start_index < len(token_list):
            current = token_list[start_index]
            if not current or current.startswith("-"):
                start_index += 1
                continue
            if "=" in current and "/" not in current and not current.startswith((".", "/")):
                start_index += 1
                continue
            break
    for index in range(start_index, len(token_list)):
        token = token_list[index]
        if token == "-m" and index + 1 < len(token_list):
            return str(token_list[index + 1] or "").strip() or None
        if token.startswith("-m") and len(token) > 2:
            return str(token[2:] or "").strip() or None
    return None


def _workspace_watchdog_git_subcommand(tokens: Sequence[str]) -> str | None:
    if not tokens:
        return None
    executable = _workspace_watchdog_executable(tokens)
    if executable != "git":
        return None
    for token in tokens[1:]:
        cleaned = str(token or "").strip().lower()
        if not cleaned or cleaned.startswith("-"):
            continue
        return cleaned
    return None


def _looks_like_single_file_temp_helper_command(tokens: Sequence[str]) -> bool:
    token_list = [str(token or "").strip() for token in tokens if str(token or "").strip()]
    executable = _workspace_watchdog_executable(token_list)
    if executable not in {"cp", "mv"}:
        return False
    path_arguments = [
        token
        for token in token_list[1:]
        if token and not token.startswith("-")
    ]
    if len(path_arguments) != 2:
        return False
    source, destination = path_arguments
    if source not in {TASK_FILE_NAME, f"./{TASK_FILE_NAME}"}:
        return False
    return _is_tolerated_workspace_temp_path(destination)


def _references_single_file_task_file(command_text: str | None) -> bool:
    cleaned = str(command_text or "").strip().lower()
    if not cleaned:
        return False
    return bool(re.search(r"(^|[^a-z0-9_./-])task\.json($|[^a-z0-9_./-])", cleaned))


def _looks_like_single_file_task_transform(
    *,
    command_text: str | None,
    shell_body: str | None,
    executable: str | None,
) -> bool:
    cleaned_command = str(command_text or "").strip()
    if not cleaned_command:
        return False
    lowered_command = cleaned_command.lower()
    lowered_body = str(shell_body or "").lower()
    if executable in _SINGLE_FILE_WORKSPACE_INLINE_PROGRAM_EXECUTABLES:
        return True
    if executable == "cat" and "<<" in lowered_command:
        return True
    write_markers = (
        "> task.json",
        ">> task.json",
        "task.json >",
        "write_text('task.json'",
        'write_text("task.json"',
        "writefilesync('task.json'",
        'writefilesync("task.json"',
        "copyfile('task.json'",
        'copyfile("task.json"',
        "rename('task.json'",
        'rename("task.json"',
    )
    if any(marker in lowered_command for marker in write_markers):
        return True
    if _references_single_file_task_file(lowered_command) and (
        "<<" in lowered_body or "write_text(" in lowered_body or "writefilesync(" in lowered_body
    ):
        return True
    return False


def _workspace_egregious_command_verdict(
    *,
    command_text: str | None,
    tokens: Sequence[str] | None,
) -> WorkspaceCommandClassification | None:
    command_text = str(command_text or "").strip() or None
    if command_text is None:
        return None
    token_list = [str(token or "").strip() for token in (tokens or ()) if str(token or "").strip()]
    executable = _workspace_watchdog_executable(token_list)
    if executable in _WORKSPACE_EGREGIOUS_BOUNDARY_EXECUTABLES:
        return WorkspaceCommandClassification(
            command_text=command_text,
            allowed=False,
            policy="forbidden_non_helper_executable",
            reason=f"`{executable}` is outside the egregious-only workspace-worker command policy",
        )
    git_subcommand = _workspace_watchdog_git_subcommand(token_list)
    if git_subcommand in _WORKSPACE_EGREGIOUS_GIT_SUBCOMMANDS:
        return WorkspaceCommandClassification(
            command_text=command_text,
            allowed=False,
            policy="forbidden_non_helper_executable",
            reason=f"`git {git_subcommand}` is outside the egregious-only workspace-worker command policy",
        )
    return None


def _normalize_visible_workspace_path_token(token: str) -> str | None:
    cleaned = str(token or "").strip()
    if not cleaned:
        return None
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    if not cleaned:
        return None
    if cleaned in {"<", "<<", "<<<", ">", ">>", "1>", "1>>", "2>", "2>>", "|", "||", "&&"}:
        return None
    for prefix in ("1>>", "2>>", "1>", "2>", ">>", ">", "<<<", "<<", "<"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    if not cleaned:
        return None
    if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    if not cleaned or not _token_looks_like_workspace_path(cleaned):
        return None
    return cleaned


def _is_tolerated_workspace_temp_path(token: str) -> bool:
    cleaned = str(token or "").strip()
    if not cleaned:
        return False
    allowed_temp_roots = workspace_allowed_temp_roots()
    return any(
        cleaned == root or cleaned.startswith(f"{root}/")
        for root in allowed_temp_roots
    )


def _strip_allowed_workspace_temp_paths(shell_text: str) -> str:
    if not shell_text:
        return shell_text
    allowed_temp_roots = workspace_allowed_temp_roots()
    root_pattern = "|".join(
        re.escape(root)
        for root in sorted(allowed_temp_roots, key=len, reverse=True)
    )
    return re.sub(
        rf"(^|[\s\"'])(?P<path>(?:{root_pattern})(?:/[^\s\"']*)?)",
        lambda match: f"{match.group(1)}__WORKSPACE_TEMP_PATH__",
        shell_text,
        flags=re.MULTILINE,
    )


def _strip_allowed_workspace_execution_root_paths(
    shell_text: str,
    *,
    allow_output_paths: bool,
    allowed_absolute_roots: Sequence[str | Path] | None,
) -> tuple[str, WorkspaceCommandClassification | None]:
    if not shell_text:
        return shell_text, None
    if not allowed_absolute_roots:
        return shell_text, None

    verdict: WorkspaceCommandClassification | None = None

    def _replace(match: re.Match[str]) -> str:
        nonlocal verdict
        path_token = str(match.group("path") or "").strip()
        normalized_argument = _normalize_visible_workspace_path_token(path_token)
        if normalized_argument is None:
            return match.group(0)
        path_verdict = _classify_workspace_path_argument(
            normalized_argument,
            allow_output_paths=allow_output_paths,
            allowed_absolute_roots=allowed_absolute_roots,
        )
        if path_verdict.allowed:
            return f"{match.group(1)}__WORKSPACE_EXECUTION_ROOT_PATH__"
        if verdict is None:
            verdict = path_verdict
        return match.group(0)

    scrubbed_text = re.sub(
        r"(^|[\s\"'])(?P<path>/(?!/|dev/null(?:$|[\s\"']))[^\s\"']*)",
        _replace,
        shell_text,
        flags=re.MULTILINE,
    )
    return scrubbed_text, verdict


def _normalize_allowed_workspace_roots(
    allowed_absolute_roots: Sequence[str | Path] | None,
) -> tuple[Path, ...]:
    normalized_roots: list[Path] = []
    seen: set[str] = set()
    for root in allowed_absolute_roots or ():
        cleaned = str(root or "").strip()
        if not cleaned:
            continue
        try:
            normalized_root = Path(cleaned).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if not normalized_root.is_absolute():
            continue
        normalized_key = normalized_root.as_posix()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        normalized_roots.append(normalized_root)
    return tuple(sorted(normalized_roots, key=lambda path: len(path.parts), reverse=True))


def _workspace_relative_path_under_allowed_roots(
    path: Path,
    *,
    allowed_absolute_roots: Sequence[str | Path] | None,
) -> Path | None:
    for root in _normalize_allowed_workspace_roots(allowed_absolute_roots):
        try:
            return path.relative_to(root)
        except ValueError:
            continue
    return None


def _token_looks_like_workspace_path(token: str) -> bool:
    cleaned = str(token or "").strip()
    if not cleaned or cleaned.startswith("-"):
        return False
    if cleaned in _WORKSPACE_ALLOWED_PATH_ROOTS:
        return True
    if cleaned.startswith(("./", "../", "/", "~")):
        return True
    if "/" in cleaned:
        return True
    return cleaned.endswith(
        (".json", ".jsonl", ".md", ".txt", ".csv", ".tsv", ".yaml", ".yml")
    )


def _classify_workspace_path_argument(
    token: str,
    *,
    allow_output_paths: bool = True,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
) -> WorkspaceCommandClassification:
    cleaned = str(token or "").strip()
    if not cleaned:
        return WorkspaceCommandClassification(
            command_text=cleaned or None,
            allowed=False,
            policy="forbidden_empty_path_argument",
            reason="empty path arguments are outside the bounded workspace policy",
        )
    if cleaned in _WORKSPACE_ALLOWED_NULL_SINKS:
        return WorkspaceCommandClassification(
            command_text=cleaned,
            allowed=True,
            policy="tolerated_workspace_local_path",
            reason="null sink stayed inside the bounded local workspace surface",
        )
    if _is_tolerated_workspace_temp_path(cleaned):
        return WorkspaceCommandClassification(
            command_text=cleaned,
            allowed=True,
            policy="tolerated_workspace_temp_path",
            reason="local temp-root helper path stayed inside the relaxed workspace policy",
        )
    if cleaned.startswith("~"):
        return WorkspaceCommandClassification(
            command_text=cleaned,
            allowed=False,
            policy="forbidden_absolute_path",
            reason="workspace shell commands must stay on relative local paths",
        )
    if cleaned.startswith("/"):
        try:
            absolute_path = Path(cleaned).resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            absolute_path = Path(cleaned)
        relative_allowed_path = _workspace_relative_path_under_allowed_roots(
            absolute_path,
            allowed_absolute_roots=allowed_absolute_roots,
        )
        if relative_allowed_path is None:
            return WorkspaceCommandClassification(
                command_text=cleaned,
                allowed=False,
                policy="forbidden_absolute_path",
                reason="workspace shell commands must stay on relative local paths",
            )
        normalized_text = relative_allowed_path.as_posix()
        if not allow_output_paths and (
            normalized_text == _DIRECT_EXEC_OUTPUT_DIR_NAME
            or normalized_text.startswith(f"{_DIRECT_EXEC_OUTPUT_DIR_NAME}/")
        ):
            return WorkspaceCommandClassification(
                command_text=cleaned,
                allowed=False,
                policy="forbidden_output_path",
                reason="this workspace policy does not allow helper commands against `out/`",
            )
        return WorkspaceCommandClassification(
            command_text=cleaned,
            allowed=True,
            policy="tolerated_workspace_execution_root_path",
            reason="absolute path stayed inside the assigned workspace execution root",
        )
    normalized = cleaned[2:] if cleaned.startswith("./") else cleaned
    if not normalized:
        return WorkspaceCommandClassification(
            command_text=cleaned,
            allowed=False,
            policy="forbidden_empty_path_argument",
            reason="empty path arguments are outside the bounded workspace policy",
        )
    path = Path(normalized)
    if path.is_absolute():
        return WorkspaceCommandClassification(
            command_text=cleaned,
            allowed=False,
            policy="forbidden_absolute_path",
            reason="workspace shell commands must stay on relative local paths",
        )
    if ".." in path.parts:
        return WorkspaceCommandClassification(
            command_text=cleaned,
            allowed=False,
            policy="forbidden_parent_traversal_path",
            reason="parent-directory traversal is outside the bounded workspace policy",
        )
    normalized_text = path.as_posix()
    if not allow_output_paths and (
        normalized_text == _DIRECT_EXEC_OUTPUT_DIR_NAME
        or normalized_text.startswith(f"{_DIRECT_EXEC_OUTPUT_DIR_NAME}/")
    ):
        return WorkspaceCommandClassification(
            command_text=cleaned,
            allowed=False,
            policy="forbidden_output_path",
            reason="this workspace policy does not allow helper commands against `out/`",
        )
    return WorkspaceCommandClassification(
        command_text=cleaned,
        allowed=True,
        policy="tolerated_workspace_local_path",
        reason="path stayed inside the bounded local workspace surface",
    )


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
