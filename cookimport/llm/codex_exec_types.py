from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol

from .codex_exec_policy import CodexExecPolicySpec

DirectExecWorkerContract = Literal["packet", "taskfile"]
DirectExecWorkspaceMode = DirectExecWorkerContract
FinalAgentMessageState = Literal["absent", "informational", "malformed", "json_object"]


class CodexExecRunner(Protocol):
    def run_packet_worker(
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
        resume_last: bool = False,
        persist_session: bool = False,
        prepared_execution_working_dir: Path | None = None,
        policy_spec: CodexExecPolicySpec | None = None,
    ) -> "CodexExecRunResult":
        """Run one non-interactive packet worker call."""

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
            ["CodexExecLiveSnapshot"], "CodexExecSupervisionDecision | None"
        ]
        | None = None,
        policy_spec: CodexExecPolicySpec | None = None,
    ) -> "CodexExecRunResult":
        """Run one long-lived taskfile worker session against local workspace files."""


@dataclass(frozen=True)
class CodexExecRecentCommandCompletion:
    command: str
    exit_code: int | None = None
    status: str | None = None
    python_module: str | None = None
    parsed_output: dict[str, Any] | None = None
    reported_completed: bool = False
    reported_final_status: str | None = None


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
    final_agent_message_text: str | None = None
    source_working_dir: str | None = None
    execution_working_dir: str | None = None
    live_activity_summary: str | None = None
    last_completed_command: CodexExecRecentCommandCompletion | None = None
    last_completed_stage_helper_command: CodexExecRecentCommandCompletion | None = None


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
