from __future__ import annotations

import hashlib
import json
import queue
import shutil
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

import tiktoken

from .codex_farm_runner import (
    CodexFarmRunnerError,
    _merge_env,
    _resolve_recipeimport_codex_home,
)

DIRECT_CODEX_EXEC_RUNTIME_MODE_V1 = "direct_codex_exec_v1"
_DIRECT_EXEC_ISOLATION_ROOT_NAME = "recipeimport-direct-exec-workspaces"
_DIRECT_EXEC_AGENTS_FILE_NAME = "AGENTS.md"
_DIRECT_EXEC_INPUT_DIR_NAME = "in"
_DIRECT_EXEC_DEBUG_DIR_NAME = "debug"
_DIRECT_EXEC_LOGS_DIR_NAME = "logs"
_DIRECT_EXEC_SHARDS_DIR_NAME = "shards"
_DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME = "assigned_shards.json"


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
        workspace_task_label: str | None = None,
        supervision_callback: Callable[
            ["CodexExecLiveSnapshot"], "CodexExecSupervisionDecision | None"
        ]
        | None = None,
    ) -> "CodexExecRunResult":
        """Run one direct structured Codex exec call."""


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
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class CodexExecSupervisionDecision:
    action: str = "continue"
    reason_code: str | None = None
    reason_detail: str | None = None
    retryable: bool = False

    @classmethod
    def terminate(
        cls,
        *,
        reason_code: str,
        reason_detail: str | None = None,
        retryable: bool = False,
    ) -> "CodexExecSupervisionDecision":
        return cls(
            action="terminate",
            reason_code=str(reason_code).strip() or None,
            reason_detail=str(reason_detail).strip() or None,
            retryable=bool(retryable),
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
    supervision_state: str | None = None
    supervision_reason_code: str | None = None
    supervision_reason_detail: str | None = None
    supervision_retryable: bool = False

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
        event_summary = _summarize_codex_events(self.events)
        pathological_flags = _pathological_flags_for_row(
            command_execution_count=event_summary["command_execution_count"],
            reasoning_item_count=event_summary["reasoning_item_count"],
            wrapper_overhead_tokens=wrapper_overhead_tokens,
            visible_input_tokens=visible_input_tokens,
            visible_output_tokens=visible_output_tokens,
        )
        return {
            "worker_id": worker_id,
            "task_id": shard_id,
            "status": "ok" if self.subprocess_exit_code == 0 else "failed",
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
            "reasoning_item_count": event_summary["reasoning_item_count"],
            "reasoning_item_types": event_summary["reasoning_item_types"],
            "pathological_flags": pathological_flags,
            "supervision_state": self.supervision_state,
            "supervision_reason_code": self.supervision_reason_code,
            "supervision_reason_detail": self.supervision_reason_detail,
            "supervision_retryable": self.supervision_retryable,
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
        )
        execution_working_dir = prepared_workspace.execution_working_dir
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
        )
        started_at = datetime.now(timezone.utc)
        completed = _run_codex_exec_subprocess_streaming(
            command=command,
            prompt_text=execution_prompt_text,
            working_dir=execution_working_dir,
            env=process_env,
            timeout_seconds=timeout_seconds,
            supervision_callback=supervision_callback,
        )
        finished_at = datetime.now(timezone.utc)

        events = tuple(completed.events)
        response_text = _extract_last_agent_message(events)
        turn_failed_message = _extract_turn_failed_message(events)
        usage = _normalize_usage(_extract_turn_completed_usage(events))
        if completed.returncode != 0 and completed.termination_decision is None:
            detail = turn_failed_message or _summarize_failure_text(completed.stderr, completed.stdout)
            raise CodexFarmRunnerError(
                f"codex exec failed (exit={completed.returncode}): {detail or 'no detail'}"
            )
        if not response_text and completed.termination_decision is None:
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
            supervision_state=(
                "watchdog_killed" if completed.termination_decision is not None else "completed"
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
    calls: list[dict[str, Any]] = field(default_factory=list)

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
        workspace_task_label: str | None = None,
        supervision_callback: Callable[
            [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
        ]
        | None = None,
    ) -> CodexExecRunResult:
        self.calls.append(
            {
                "prompt_text": prompt_text,
                "input_payload": dict(input_payload or {}),
                "working_dir": str(working_dir),
                "output_schema_path": str(output_schema_path) if output_schema_path is not None else None,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "timeout_seconds": timeout_seconds,
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
) -> PreparedDirectExecWorkspace:
    source_root = Path(source_working_dir).resolve()
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
        "assigned_shards_path": None,
        "mirrored_input_files": [],
        "mirrored_debug_files": [],
    }
    execution_root = (
        Path(execution_working_dir).expanduser()
        if execution_working_dir is not None and str(execution_working_dir).strip()
        else None
    )
    if execution_root is None or not execution_root.exists():
        return payload
    assigned_shards_path = execution_root / _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME
    if assigned_shards_path.exists():
        payload["assigned_shards_path"] = str(assigned_shards_path)
    payload["mirrored_input_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_INPUT_DIR_NAME
    )
    payload["mirrored_debug_files"] = _list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_DEBUG_DIR_NAME
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


def _populate_direct_exec_workspace(
    *,
    source_working_dir: Path,
    execution_working_dir: Path,
    task_label: str | None,
) -> None:
    _copy_if_present(
        source_working_dir / _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME,
        execution_working_dir / _DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_INPUT_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_INPUT_DIR_NAME,
    )
    _copy_tree_if_present(
        source_working_dir / _DIRECT_EXEC_DEBUG_DIR_NAME,
        execution_working_dir / _DIRECT_EXEC_DEBUG_DIR_NAME,
    )
    (execution_working_dir / _DIRECT_EXEC_LOGS_DIR_NAME).mkdir(parents=True, exist_ok=True)
    (execution_working_dir / _DIRECT_EXEC_SHARDS_DIR_NAME).mkdir(parents=True, exist_ok=True)
    agents_path = execution_working_dir / _DIRECT_EXEC_AGENTS_FILE_NAME
    agents_path.write_text(
        _build_direct_exec_agents_text(task_label=task_label),
        encoding="utf-8",
    )


def _copy_if_present(source: Path, destination: Path) -> None:
    if not source.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree_if_present(source: Path, destination: Path) -> None:
    if not source.exists() or not source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        return
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _build_direct_exec_agents_text(*, task_label: str | None) -> str:
    rendered_task_label = str(task_label or "structured shard task").strip()
    return (
        "# RecipeImport Direct Codex Worker\n\n"
        "This directory is an isolated runtime workspace for one RecipeImport "
        f"{rendered_task_label}.\n\n"
        "You are not working on the RecipeImport repository itself.\n"
        "Follow only the user prompt and the files in this directory.\n"
        "Do not inspect parent directories, repository-wide AGENTS files, project docs, or source code.\n"
        "Do not run repo-specific commands such as `npm run docs:list`, `git`, or broad search commands.\n"
        "Do not write or modify files unless the prompt explicitly requires a local scratch file.\n"
        "Prefer reading the local task file directly and returning the required JSON immediately.\n"
        "Return only the final JSON shape requested by the prompt.\n"
    )


def _build_codex_exec_command(
    *,
    cmd: str,
    working_dir: Path,
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
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
    command.extend(["--json", "--ephemeral", "--sandbox", "read-only"])
    command.extend(["--cd", str(working_dir)])
    if output_schema_path is not None:
        command.extend(["--output-schema", str(output_schema_path)])
    if model:
        command.extend(["--model", str(model)])
    if reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    command.append("-")
    return command


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
    supervision_callback: Callable[
        [CodexExecLiveSnapshot], CodexExecSupervisionDecision | None
    ]
    | None,
) -> _StreamedCodexProcessResult:
    started_at = time.perf_counter()
    normalized_timeout = max(1, int(timeout_seconds)) if timeout_seconds is not None else None
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
                )
                decision = supervision_callback(snapshot)
                last_snapshot_at = current_time
                if (
                    isinstance(decision, CodexExecSupervisionDecision)
                    and decision.action == "terminate"
                ):
                    termination_decision = decision
                    _terminate_codex_process(process)

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
) -> CodexExecLiveSnapshot:
    current_time = time.perf_counter()
    live_summary = _summarize_live_codex_events(events)
    return CodexExecLiveSnapshot(
        elapsed_seconds=max(0.0, current_time - started_at),
        last_event_seconds_ago=(
            None if last_event_at is None else max(0.0, current_time - last_event_at)
        ),
        event_count=len(events),
        command_execution_count=live_summary["command_execution_count"],
        reasoning_item_count=live_summary["reasoning_item_count"],
        last_command=live_summary["last_command"],
        last_command_repeat_count=live_summary["last_command_repeat_count"],
        has_final_agent_message=_extract_last_agent_message(list(events)) is not None,
        timeout_seconds=timeout_seconds,
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
    }
    command_executing_shards: set[str] = set()
    reasoning_heavy_shards: set[str] = set()
    invalid_output_shards: set[str] = set()
    missing_output_shards: set[str] = set()
    repaired_shards: set[str] = set()
    preflight_rejected_shards: set[str] = set()
    watchdog_killed_shards: set[str] = set()
    pathological_shards: set[str] = set()
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
        command_execution_count = int(row.get("command_execution_count") or 0)
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
        proposal_status = str(row.get("proposal_status") or "").strip().lower()
        if proposal_status == "invalid":
            summary["invalid_output_tokens_total"] += tokens_total
            if shard_id:
                invalid_output_shards.add(shard_id)
                pathological_shards.add(shard_id)
        if proposal_status == "missing_output" and shard_id:
            missing_output_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if str(row.get("repair_status") or "").strip().lower() == "repaired" and shard_id:
            repaired_shards.add(shard_id)
        supervision_state = str(row.get("supervision_state") or "").strip().lower()
        if supervision_state == "preflight_rejected" and shard_id:
            preflight_rejected_shards.add(shard_id)
            pathological_shards.add(shard_id)
        if supervision_state == "watchdog_killed" and shard_id:
            watchdog_killed_shards.add(shard_id)
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
    summary["missing_output_shard_count"] = len(missing_output_shards)
    summary["repaired_shard_count"] = len(repaired_shards)
    summary["preflight_rejected_shard_count"] = len(preflight_rejected_shards)
    summary["watchdog_killed_shard_count"] = len(watchdog_killed_shards)
    summary["pathological_shard_count"] = len(pathological_shards)
    summary["pathological_flags"] = _summary_pathological_flags(summary)
    return summary


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
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]]
) -> dict[str, Any]:
    command_execution_count = 0
    reasoning_item_count = 0
    command_execution_commands: list[str] = []
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
        "reasoning_item_count": reasoning_item_count,
        "reasoning_item_types": reasoning_item_types,
    }


def _summarize_live_codex_events(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    command_item_ids: set[str] = set()
    command_texts: list[str] = []
    reasoning_item_count = 0
    last_command: str | None = None
    last_command_repeat_count = 0
    for payload in events:
        payload_type = str(payload.get("type") or "").strip()
        if payload_type not in {"item.started", "item.completed"}:
            continue
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "").strip()
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
        "last_command": last_command,
        "last_command_repeat_count": last_command_repeat_count,
    }


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
