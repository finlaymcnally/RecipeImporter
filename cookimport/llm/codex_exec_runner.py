from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .codex_farm_runner import CodexFarmRunnerError, _merge_env

DIRECT_CODEX_EXEC_RUNTIME_MODE_V1 = "direct_codex_exec_v1"


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
    ) -> "CodexExecRunResult":
        """Run one direct structured Codex exec call."""


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

    def telemetry_row(self, *, worker_id: str, shard_id: str) -> dict[str, Any]:
        usage = dict(self.usage or {})
        prompt_text = self._prompt_text()
        response_text = str(self.response_text or "")
        tokens_input = _coerce_nonnegative_int(usage.get("input_tokens"))
        tokens_cached_input = _coerce_nonnegative_int(usage.get("cached_input_tokens"))
        tokens_output = _coerce_nonnegative_int(usage.get("output_tokens"))
        tokens_reasoning = _coerce_nonnegative_int(usage.get("reasoning_tokens"))
        return {
            "worker_id": worker_id,
            "task_id": shard_id,
            "status": "ok" if self.subprocess_exit_code == 0 else "failed",
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
            "codex_event_count": len(self.events),
            "codex_event_types": [
                str(event.get("type") or "").strip()
                for event in self.events
                if str(event.get("type") or "").strip()
            ],
            "turn_failed_message": self.turn_failed_message,
            "output_schema_path": self.output_schema_path,
        }

    def to_payload(self, *, worker_id: str, shard_id: str) -> dict[str, Any]:
        row = self.telemetry_row(worker_id=worker_id, shard_id=shard_id)
        telemetry = {
            "rows": [row],
            "summary": {
                "call_count": 1,
                "tokens_input": row.get("tokens_input"),
                "tokens_cached_input": row.get("tokens_cached_input"),
                "tokens_output": row.get("tokens_output"),
                "tokens_reasoning": row.get("tokens_reasoning"),
                "tokens_total": row.get("tokens_total"),
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
            "telemetry": telemetry,
        }

    def _prompt_text(self) -> str:
        return self.prompt_text


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
    ) -> CodexExecRunResult:
        command = _build_codex_exec_command(
            cmd=self.cmd,
            working_dir=working_dir,
            output_schema_path=output_schema_path,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        try:
            completed = subprocess.run(
                command,
                input=prompt_text,
                text=True,
                capture_output=True,
                check=False,
                cwd=str(working_dir),
                env=_merge_env(env),
                timeout=max(1, int(timeout_seconds)) if timeout_seconds is not None else None,
            )
        except FileNotFoundError as exc:
            binary = command[0] if command else "codex"
            raise CodexFarmRunnerError(
                f"codex command not found: {binary!r}. Install Codex CLI before retrying."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            timeout_display = max(1, int(timeout_seconds or 0)) if timeout_seconds is not None else "unknown"
            raise CodexFarmRunnerError(
                f"codex exec timed out after {timeout_display} seconds."
            ) from exc
        except OSError as exc:
            binary = command[0] if command else "codex"
            raise CodexFarmRunnerError(
                f"Failed to execute codex command {binary!r}: {exc}"
            ) from exc

        events = tuple(_parse_codex_json_events(completed.stdout, completed.stderr))
        response_text = _extract_last_agent_message(events)
        turn_failed_message = _extract_turn_failed_message(events)
        usage = _normalize_usage(_extract_turn_completed_usage(events))
        if completed.returncode != 0:
            detail = turn_failed_message or _summarize_failure_text(completed.stderr, completed.stdout)
            raise CodexFarmRunnerError(
                f"codex exec failed (exit={completed.returncode}): {detail or 'no detail'}"
            )
        if not response_text:
            raise CodexFarmRunnerError(
                "codex exec failed: no last agent message in JSON event stream."
            )
        return CodexExecRunResult(
            command=list(command),
            subprocess_exit_code=int(completed.returncode),
            output_schema_path=str(output_schema_path) if output_schema_path is not None else None,
            prompt_text=prompt_text,
            response_text=response_text,
            turn_failed_message=turn_failed_message,
            events=events,
            usage=usage,
            stderr_text=completed.stderr or None,
            stdout_text=completed.stdout or None,
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


def _parse_codex_json_events(stdout_text: str | None, stderr_text: str | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for stream in (stdout_text or "", stderr_text or ""):
        for raw_line in stream.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events


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
