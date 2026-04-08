from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path
from typing import Mapping, Sequence

from .codex_farm_runner import CodexFarmRunnerError


def build_codex_exec_command(
    *,
    cmd: str,
    working_dir: Path,
    output_schema_path: Path | None,
    model: str | None,
    reasoning_effort: str | None,
    config_overrides: Sequence[str] | None = None,
    sandbox_mode: str = "read-only",
    resume_last: bool = False,
    persist_session: bool = False,
) -> list[str]:
    try:
        tokens = shlex.split(str(cmd).strip())
    except ValueError as exc:
        raise CodexFarmRunnerError(f"Invalid codex exec command: {cmd!r}") from exc
    if not tokens:
        tokens = ["codex", "exec"]
    executable = tokens[0]
    argv = tokens[1:]
    if resume_last:
        if not argv or argv[0] not in {"exec", "e"}:
            argv = ["exec"]
        elif argv and argv[-1] == "-":
            argv = argv[:-1]
        command = [executable, *argv, "resume", "--last", "--json", "--skip-git-repo-check"]
    else:
        if not argv or argv[0] not in {"exec", "e"}:
            argv = ["exec", *argv]
        if argv and argv[-1] == "-":
            argv = argv[:-1]
        command = [executable, *argv]
        command.extend(
            [
                "--json",
                "--skip-git-repo-check",
                "--sandbox",
                str(sandbox_mode or "read-only"),
            ]
        )
        if not persist_session:
            command.append("--ephemeral")
        command.extend(["--cd", str(working_dir)])
        if output_schema_path is not None:
            command.extend(["--output-schema", str(output_schema_path)])
    if model:
        command.extend(["--model", str(model)])
    if reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    for override in config_overrides or ():
        cleaned_override = str(override or "").strip()
        if cleaned_override:
            command.extend(["-c", cleaned_override])
    command.append("-")
    return command


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_taskfile_worker_command_path(
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


def _taskfile_worker_preserved_toolchain_root(
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


def _taskfile_worker_preserved_virtualenv_root(
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


def build_taskfile_worker_fs_cage_command(
    *,
    command: Sequence[str],
    working_dir: Path,
    env: Mapping[str, str],
    unshare_path: str | None,
    resolved_codex_home: str | None = None,
    direct_exec_root: Path | None = None,
    user_home: Path | None = None,
    mktemp_template: str | None = None,
) -> list[str]:
    if not unshare_path:
        raise CodexFarmRunnerError(
            "taskfile filesystem isolation requires `unshare`, but it was not found"
        )

    explicit_env = {str(key): str(value) for key, value in (env or {}).items()}
    codex_home = (
        Path(resolved_codex_home).expanduser().resolve(strict=False)
        if resolved_codex_home
        else (Path.home() / ".codex-recipe").resolve(strict=False)
    )
    workspace_root = Path(working_dir).expanduser().resolve(strict=False)
    direct_exec_root = (
        Path(direct_exec_root).expanduser().resolve(strict=False)
        if direct_exec_root is not None
        else workspace_root.parent
    )
    try:
        workspace_root.relative_to(direct_exec_root)
    except ValueError as exc:
        raise CodexFarmRunnerError(
            "taskfile filesystem isolation expected the execution cwd to live "
            f"under {direct_exec_root}, got {workspace_root}"
        ) from exc

    user_home = (
        Path(user_home).expanduser().resolve(strict=False)
        if user_home is not None
        else Path.home().expanduser().resolve(strict=False)
    )
    resolved_command = [str(token) for token in command]
    resolved_executable_path = _resolve_taskfile_worker_command_path(
        token=resolved_command[0] if resolved_command else "",
        env=explicit_env,
    )
    if resolved_command and resolved_executable_path is not None:
        resolved_command[0] = str(resolved_executable_path)
    preserved_toolchain_root = _taskfile_worker_preserved_toolchain_root(
        executable_path=resolved_executable_path,
        user_home=user_home,
    )
    preserved_virtualenv_root = _taskfile_worker_preserved_virtualenv_root(
        env=explicit_env,
        user_home=user_home,
    )
    quoted_workspace_root = shlex.quote(str(workspace_root))
    quoted_codex_home = shlex.quote(str(codex_home))
    quoted_direct_exec_root = shlex.quote(str(direct_exec_root))
    quoted_user_home = shlex.quote(str(user_home))
    quoted_mktemp_template = shlex.quote(str(mktemp_template or "recipeimport-fs-cage.XXXXXX"))
    shell_lines = [
        "set -eu",
        f"stage_dir=$(mktemp -d {quoted_mktemp_template})",
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
        str(unshare_path),
        # Keep the host network namespace; `codex exec` needs outbound API access.
        "-Urm",
        "bash",
        "-lc",
        shell_script,
        "__recipeimport_workspace_fs_cage__",
        *resolved_command,
    ]
