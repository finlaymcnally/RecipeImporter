from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

_CODEX_EXECUTABLES = {"codex", "codex.exe", "codex2", "codex2.exe"}
_CODEX_ALT_EXECUTABLE_RE = re.compile(r"^codex[0-9]+(?:\.exe)?$")


def default_codex_exec_cmd() -> str:
    override = str(os.environ.get("COOKIMPORT_CODEX_CMD") or "").strip()
    return override or "codex exec -"


def argv_with_json_events(argv: list[str], *, track_usage: bool) -> list[str]:
    if not track_usage:
        return list(argv)
    if "--json" in argv:
        return list(argv)
    if len(argv) >= 2 and argv[1].lower() in {"exec", "e"}:
        return [argv[0], argv[1], "--json", *argv[2:]]
    return [argv[0], "--json", *argv[1:]]


def is_stdin_tty_error(completed: Any) -> bool:
    detail = f"{getattr(completed, 'stderr', '') or ''}\n{getattr(completed, 'stdout', '') or ''}".lower()
    return "stdin is not a terminal" in detail


def extract_turn_failed_message(completed: Any) -> str | None:
    streams = [
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    ]
    for stream in streams:
        for raw_line in stream.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("type") != "turn.failed":
                continue
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                message = str(
                    error_payload.get("message")
                    or error_payload.get("detail")
                    or ""
                ).strip()
                if message:
                    return message
            elif isinstance(error_payload, str):
                normalized = error_payload.strip()
                if normalized:
                    return normalized
    return None


def normalize_usage(payload: Any) -> dict[str, int] | None:
    if not isinstance(payload, dict):
        return None
    usage: dict[str, int] = {}
    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
        try:
            usage[key] = int(payload.get(key))
        except (TypeError, ValueError):
            usage[key] = 0
    usage["reasoning_tokens"] = _extract_reasoning_tokens(payload)
    return usage


def extract_response_and_usage(completed: Any, *, track_usage: bool) -> tuple[str, dict[str, int] | None]:
    if track_usage:
        response, usage = _extract_json_event_response_and_usage(completed)
        if response:
            return response, usage
    response = str(getattr(completed, "stdout", "") or "").strip()
    if not response:
        return "", None
    return response, None


def run_codex_json_prompt(
    *,
    prompt: str,
    timeout_seconds: int,
    cmd: str | None = None,
    track_usage: bool = False,
    runner: Callable[..., Any] | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    allow_llm = str(os.getenv("COOKIMPORT_ALLOW_LLM", os.getenv("CODEX_ALLOW_LLM", ""))).lower()
    if allow_llm not in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "LLM call blocked by safety kill switch. "
            "Set COOKIMPORT_ALLOW_LLM=1 to enable."
        )

    resolved_cmd = str(cmd or default_codex_exec_cmd()).strip()
    if not resolved_cmd:
        raise ValueError("codex command cannot be empty")
    try:
        argv = shlex.split(resolved_cmd)
    except ValueError as exc:
        raise RuntimeError(f"Unable to parse codex command: {resolved_cmd!r}") from exc
    if not argv:
        raise RuntimeError(f"Unable to parse codex command: {resolved_cmd!r}")

    invoke = runner or subprocess.run
    run_argv = argv_with_json_events(argv, track_usage=track_usage)
    completed = _invoke(
        invoke=invoke,
        argv=run_argv,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
    )
    if (
        getattr(completed, "returncode", 0) != 0
        and is_stdin_tty_error(completed)
        and _is_plain_codex_command(argv)
    ):
        completed = _invoke(
            invoke=invoke,
            argv=argv_with_json_events([argv[0], "exec", "-"], track_usage=track_usage),
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )

    response, usage = extract_response_and_usage(completed, track_usage=track_usage)
    payload: dict[str, Any] = {
        "cmd": resolved_cmd,
        "argv": list(getattr(completed, "args", run_argv) or run_argv),
        "returncode": int(getattr(completed, "returncode", 0) or 0),
        "stdout": str(getattr(completed, "stdout", "") or ""),
        "stderr": str(getattr(completed, "stderr", "") or ""),
        "response": response,
        "usage": usage,
        "turn_failed_message": extract_turn_failed_message(completed),
        "completed": completed,
    }
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                json.dumps(
                    {
                        "cmd": payload["cmd"],
                        "argv": payload["argv"],
                        "returncode": payload["returncode"],
                        "turn_failed_message": payload["turn_failed_message"],
                        "response": payload["response"],
                        "usage": payload["usage"],
                        "stdout": payload["stdout"],
                        "stderr": payload["stderr"],
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
    return payload


def _invoke(
    *,
    invoke: Callable[..., Any],
    argv: list[str],
    prompt: str,
    timeout_seconds: int,
) -> Any:
    return invoke(
        argv,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=max(1, int(timeout_seconds)),
        check=False,
    )


def _extract_json_event_response_and_usage(completed: Any) -> tuple[str, dict[str, int] | None]:
    response = ""
    usage: dict[str, int] | None = None
    streams = [
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    ]
    for stream in streams:
        for raw_line in stream.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            event_type = payload.get("type")
            if event_type == "item.completed":
                item = payload.get("item")
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "agent_message":
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    response = text.strip()
            if event_type == "turn.completed":
                usage = normalize_usage(payload.get("usage"))
    return response, usage


def _extract_reasoning_tokens(payload: dict[str, Any]) -> int:
    def _read_int(mapping: Any, *path: str) -> int | None:
        current: Any = mapping
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        try:
            if current is None:
                return None
            return int(current)
        except (TypeError, ValueError):
            return None

    candidate_paths = (
        ("reasoning_tokens",),
        ("output_tokens_reasoning",),
        ("inference_tokens",),
        ("processing_tokens",),
        ("output_tokens_details", "reasoning_tokens"),
        ("output_tokens_details", "inference_tokens"),
        ("output_tokens_details", "processing_tokens"),
        ("output_token_details", "reasoning_tokens"),
        ("output_token_details", "inference_tokens"),
        ("completion_tokens_details", "reasoning_tokens"),
        ("completion_tokens_details", "inference_tokens"),
    )
    for path in candidate_paths:
        value = _read_int(payload, *path)
        if value is not None:
            return max(0, value)
    return 0


def _is_plain_codex_command(argv: list[str]) -> bool:
    if len(argv) != 1:
        return False
    return _is_codex_executable(argv[0])


def _is_codex_executable(executable: str) -> bool:
    name = Path(executable).name.lower().strip()
    if not name:
        return False
    if name in {"codex-farm", "codex-farm.exe"}:
        return False
    if name in _CODEX_EXECUTABLES:
        return True
    return bool(_CODEX_ALT_EXECUTABLE_RE.match(name))

