from __future__ import annotations

from pathlib import Path
from typing import Any


_DEPRECATION_MESSAGE = (
    "Direct local `codex exec` runtime paths were removed. "
    "Use codex-farm-backed adapters instead."
)


def default_codex_exec_cmd() -> str:
    raise RuntimeError(_DEPRECATION_MESSAGE)


def argv_with_json_events(argv: list[str], *, track_usage: bool) -> list[str]:
    del track_usage
    return list(argv)


def run_codex_json_prompt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise RuntimeError(_DEPRECATION_MESSAGE)


def is_stdin_tty_error(completed: Any) -> bool:
    del completed
    return False


def extract_turn_failed_message(completed: Any) -> str | None:
    del completed
    return None


def normalize_usage(payload: Any) -> dict[str, int] | None:
    del payload
    return None


def extract_response_and_usage(
    completed: Any,
    *,
    track_usage: bool,
) -> tuple[str, dict[str, int] | None]:
    del completed, track_usage
    return "", None


def _is_plain_codex_command(argv: list[str]) -> bool:
    return len(argv) == 1 and _is_codex_executable(argv[0])


def _is_codex_executable(executable: str) -> bool:
    name = Path(executable).name.lower().strip()
    if not name:
        return False
    if name in {"codex-farm", "codex-farm.exe"}:
        return False
    return name.startswith("codex")
