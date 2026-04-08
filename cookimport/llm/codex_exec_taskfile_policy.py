from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path
from typing import Sequence

from cookimport.config.runtime_support import workspace_allowed_temp_roots

from .codex_exec_types import WorkspaceCommandClassification
from .editable_task_file import TASK_FILE_NAME
from .single_file_worker_commands import (
    RECIPE_STAGE_KEY,
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

_DIRECT_EXEC_INPUT_DIR_NAME = "in"
_DIRECT_EXEC_DEBUG_DIR_NAME = "debug"
_DIRECT_EXEC_HINTS_DIR_NAME = "hints"
_DIRECT_EXEC_LOGS_DIR_NAME = "logs"
_DIRECT_EXEC_SHARDS_DIR_NAME = "shards"
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

_WORKSPACE_ALLOWED_PATH_ROOTS = {
    ".",
    "./",
    TASK_FILE_NAME,
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
_SINGLE_FILE_WORKSPACE_WRAPPER_HELPER_COMMANDS = {
    TASK_SUMMARY_COMMAND,
    TASK_SHOW_UNIT_COMMAND,
    TASK_SHOW_UNANSWERED_COMMAND,
    TASK_TEMPLATE_COMMAND,
    TASK_APPLY_COMMAND,
    TASK_SHOW_CURRENT_COMMAND,
    TASK_SHOW_NEIGHBORS_COMMAND,
    TASK_ANSWER_CURRENT_COMMAND,
    TASK_NEXT_COMMAND,
    TASK_STATUS_COMMAND,
    TASK_DOCTOR_COMMAND,
}
_SINGLE_FILE_WORKSPACE_WRAPPER_STAGE_COMMANDS = {
    TASK_STATUS_COMMAND,
    TASK_DOCTOR_COMMAND,
    TASK_HANDOFF_COMMAND,
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
    "single_file_direct_file_read",
}
_SINGLE_FILE_WORKSPACE_EGREGIOUS_POLICIES = {
    "single_file_task_ad_hoc_transform",
}
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


def classify_taskfile_worker_command(
    command_text: str | None,
    *,
    allow_orientation_commands: bool = True,
    allow_output_paths: bool = True,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
    single_file_worker_policy: bool = False,
    single_file_stage_key: str | None = None,
) -> WorkspaceCommandClassification:
    boundary_violation = detect_taskfile_worker_boundary_violation(
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
            stage_key=single_file_stage_key,
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
        return _classify_taskfile_worker_shell_script(
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
            reason="`pwd` stayed inside the relaxed taskfile command policy",
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
            reason=f"`{executable}` stayed inside the relaxed taskfile command policy",
        )
    return WorkspaceCommandClassification(
        command_text=cleaned_command,
        allowed=True,
        policy="tolerated_workspace_shell_command",
        reason="command stayed inside the relaxed taskfile command policy",
    )


def _classify_single_file_workspace_command(
    *,
    command_text: str | None,
    tokens: Sequence[str],
    stage_key: str | None = None,
) -> WorkspaceCommandClassification | None:
    cleaned_command = str(command_text or "").strip() or None
    if cleaned_command is None:
        return None
    token_list = [
        str(token or "").strip() for token in tokens if str(token or "").strip()
    ]
    module_name = _workspace_watchdog_module(token_list)
    executable = _workspace_watchdog_executable(token_list)
    if executable in _SINGLE_FILE_WORKSPACE_WRAPPER_STAGE_COMMANDS:
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_repo_handoff_command",
            reason=(
                "repo-owned same-session wrapper command stayed on the single-file "
                "worker paved road"
            ),
        )
    if executable in _SINGLE_FILE_WORKSPACE_WRAPPER_HELPER_COMMANDS:
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_repo_helper_command",
            reason=(
                "repo-owned task wrapper command stayed on the single-file worker "
                "paved road"
            ),
        )
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
    cleaned_stage_key = str(stage_key or "").strip()
    if (
        cleaned_stage_key
        in {
            RECIPE_STAGE_KEY,
            "line_role",
            "nonrecipe_classify",
            "knowledge_group",
        }
        and _references_single_file_visible_contract_file(cleaned_command)
    ):
        return WorkspaceCommandClassification(
            command_text=cleaned_command,
            allowed=True,
            policy="single_file_direct_file_read",
            reason=(
                "reading local contract files is part of the direct task-file worker "
                "contract for this stage"
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


def detect_taskfile_worker_boundary_violation(
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
        return _detect_taskfile_worker_boundary_violation_in_text(
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
    return _detect_taskfile_worker_boundary_violation_in_text(
        approximate_shell_body,
        command_text=cleaned_command,
        allow_output_paths=allow_output_paths,
        allowed_absolute_roots=allowed_absolute_roots,
    )


def is_tolerated_taskfile_worker_command(
    command_text: str | None,
    *,
    allowed_absolute_roots: Sequence[str | Path] | None = None,
) -> bool:
    return (
        detect_taskfile_worker_boundary_violation(
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


def _classify_taskfile_worker_shell_script(
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
            reason="orientation commands stayed inside the relaxed taskfile command policy",
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
        reason="command stayed inside the relaxed taskfile command policy",
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


def _detect_taskfile_worker_boundary_violation_in_text(
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


def _detect_taskfile_worker_boundary_violation_in_python_heredoc(
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


def _references_single_file_visible_contract_file(command_text: str | None) -> bool:
    cleaned = str(command_text or "").strip().lower()
    if not cleaned:
        return False
    return bool(
        re.search(r"(^|[^a-z0-9_./-])task\.json($|[^a-z0-9_./-])", cleaned)
        or re.search(r"(^|[^a-z0-9_./-])agents\.md($|[^a-z0-9_./-])", cleaned)
    )


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
            reason=f"`{executable}` is outside the egregious-only taskfile command policy",
        )
    git_subcommand = _workspace_watchdog_git_subcommand(token_list)
    if git_subcommand in _WORKSPACE_EGREGIOUS_GIT_SUBCOMMANDS:
        return WorkspaceCommandClassification(
            command_text=command_text,
            allowed=False,
            policy="forbidden_non_helper_executable",
            reason=f"`git {git_subcommand}` is outside the egregious-only taskfile command policy",
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
