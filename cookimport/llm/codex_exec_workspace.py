from __future__ import annotations

import importlib
import hashlib
import json
import shlex
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .codex_farm_runner import _resolve_recipeimport_codex_home
from .codex_exec_types import DirectExecWorkspaceMode
from .editable_task_file import TASK_FILE_SCHEMA_VERSION, load_task_file


def _runner_attr(name: str, default: Any = None) -> Any:
    runner_module = importlib.import_module("cookimport.llm.codex_exec_runner")
    return getattr(runner_module, name, default)


_DIRECT_EXEC_ISOLATION_ROOT_NAME = _runner_attr("_DIRECT_EXEC_ISOLATION_ROOT_NAME")
_DIRECT_EXEC_AGENTS_FILE_NAME = _runner_attr("_DIRECT_EXEC_AGENTS_FILE_NAME")
_DIRECT_EXEC_INPUT_DIR_NAME = _runner_attr("_DIRECT_EXEC_INPUT_DIR_NAME")
_DIRECT_EXEC_DEBUG_DIR_NAME = _runner_attr("_DIRECT_EXEC_DEBUG_DIR_NAME")
_DIRECT_EXEC_HINTS_DIR_NAME = _runner_attr("_DIRECT_EXEC_HINTS_DIR_NAME")
_DIRECT_EXEC_LOGS_DIR_NAME = _runner_attr("_DIRECT_EXEC_LOGS_DIR_NAME")
_DIRECT_EXEC_SHARDS_DIR_NAME = _runner_attr("_DIRECT_EXEC_SHARDS_DIR_NAME")
_DIRECT_EXEC_TASK_FILE_NAME = _runner_attr("_DIRECT_EXEC_TASK_FILE_NAME")
_DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_ASSIGNED_TASKS_FILE_NAME"
)
_DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_ASSIGNED_SHARDS_FILE_NAME"
)
_DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_WORKER_MANIFEST_FILE_NAME"
)
_DIRECT_EXEC_CURRENT_PHASE_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_CURRENT_PHASE_FILE_NAME"
)
_DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_CURRENT_PHASE_BRIEF_FILE_NAME"
)
_DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME"
)
_DIRECT_EXEC_CURRENT_PACKET_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_CURRENT_PACKET_FILE_NAME"
)
_DIRECT_EXEC_CURRENT_HINT_FILE_NAME = _runner_attr("_DIRECT_EXEC_CURRENT_HINT_FILE_NAME")
_DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_CURRENT_RESULT_PATH_FILE_NAME"
)
_DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_PACKET_LEASE_STATUS_FILE_NAME"
)
_DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME = _runner_attr(
    "_DIRECT_EXEC_OUTPUT_CONTRACT_FILE_NAME"
)
_DIRECT_EXEC_EXAMPLES_DIR_NAME = _runner_attr("_DIRECT_EXEC_EXAMPLES_DIR_NAME")
_DIRECT_EXEC_TOOLS_DIR_NAME = _runner_attr("_DIRECT_EXEC_TOOLS_DIR_NAME")
_DIRECT_EXEC_OUTPUT_DIR_NAME = _runner_attr("_DIRECT_EXEC_OUTPUT_DIR_NAME")
_DIRECT_EXEC_SCRATCH_DIR_NAME = _runner_attr("_DIRECT_EXEC_SCRATCH_DIR_NAME")
_DIRECT_EXEC_WORK_DIR_NAME = _runner_attr("_DIRECT_EXEC_WORK_DIR_NAME")
_DIRECT_EXEC_REPAIR_DIR_NAME = _runner_attr("_DIRECT_EXEC_REPAIR_DIR_NAME")
_DIRECT_EXEC_INTERNAL_DIR_NAME = _runner_attr("_DIRECT_EXEC_INTERNAL_DIR_NAME")
_DIRECT_EXEC_HELPER_IMPORTS_ROOT_NAME = _runner_attr(
    "_DIRECT_EXEC_HELPER_IMPORTS_ROOT_NAME"
)
_DIRECT_EXEC_WORKSPACE_MIRRORED_PATH_ENV_KEYS = _runner_attr(
    "_DIRECT_EXEC_WORKSPACE_MIRRORED_PATH_ENV_KEYS",
    (),
)
_SINGLE_FILE_WORKSPACE_ORIGINAL_PATH_ENV = _runner_attr(
    "_SINGLE_FILE_WORKSPACE_ORIGINAL_PATH_ENV"
)
_SINGLE_FILE_WORKSPACE_SHIM_EXECUTABLES = _runner_attr(
    "_SINGLE_FILE_WORKSPACE_SHIM_EXECUTABLES",
    (),
)
TASK_ANSWER_CURRENT_COMMAND = _runner_attr("TASK_ANSWER_CURRENT_COMMAND")
TASK_APPLY_COMMAND = _runner_attr("TASK_APPLY_COMMAND")
TASK_DOCTOR_COMMAND = _runner_attr("TASK_DOCTOR_COMMAND")
TASK_HANDOFF_COMMAND = _runner_attr("TASK_HANDOFF_COMMAND")
TASK_NEXT_COMMAND = _runner_attr("TASK_NEXT_COMMAND")
TASK_SHOW_CURRENT_COMMAND = _runner_attr("TASK_SHOW_CURRENT_COMMAND")
TASK_SHOW_NEIGHBORS_COMMAND = _runner_attr("TASK_SHOW_NEIGHBORS_COMMAND")
TASK_SHOW_UNANSWERED_COMMAND = _runner_attr("TASK_SHOW_UNANSWERED_COMMAND")
TASK_SHOW_UNIT_COMMAND = _runner_attr("TASK_SHOW_UNIT_COMMAND")
TASK_STATUS_COMMAND = _runner_attr("TASK_STATUS_COMMAND")
TASK_SUMMARY_COMMAND = _runner_attr("TASK_SUMMARY_COMMAND")
TASK_TEMPLATE_COMMAND = _runner_attr("TASK_TEMPLATE_COMMAND")


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
    mode: DirectExecWorkspaceMode = "packet",
) -> PreparedDirectExecWorkspace:
    source_root = Path(source_working_dir).resolve()
    uses_single_file_worker_runtime = _runner_attr(
        "_uses_single_file_worker_runtime", None
    )
    store_hidden_task_file_snapshot = _runner_attr(
        "_store_hidden_task_file_snapshot", None
    )
    write_direct_exec_worker_manifest = _runner_attr(
        "_write_direct_exec_worker_manifest", None
    )
    single_file_worker_runtime = bool(
        uses_single_file_worker_runtime is not None
        and uses_single_file_worker_runtime(
            workspace_root=source_root,
            mode=mode,
        )
    )
    if single_file_worker_runtime and callable(store_hidden_task_file_snapshot):
        store_hidden_task_file_snapshot(source_root)
    if callable(write_direct_exec_worker_manifest):
        write_direct_exec_worker_manifest(
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
        "execution_working_dir": str(execution_working_dir)
        if execution_working_dir
        else None,
        "execution_agents_path": str(execution_agents_path)
        if execution_agents_path
        else None,
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
        if execution_working_dir is not None
        and str(execution_working_dir).strip()
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
    current_phase_feedback_path = (
        execution_root / _DIRECT_EXEC_CURRENT_PHASE_FEEDBACK_FILE_NAME
    )
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
    list_workspace_relative_files = _runner_attr(
        "_list_workspace_relative_files", lambda _root: []
    )
    payload["mirrored_input_files"] = list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_INPUT_DIR_NAME
    )
    payload["mirrored_debug_files"] = list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_DEBUG_DIR_NAME
    )
    payload["mirrored_hint_files"] = list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_HINTS_DIR_NAME
    )
    payload["mirrored_example_files"] = list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_EXAMPLES_DIR_NAME
    )
    payload["mirrored_tool_files"] = list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_TOOLS_DIR_NAME
    )
    payload["mirrored_output_files"] = list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_OUTPUT_DIR_NAME
    )
    payload["mirrored_scratch_files"] = list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_SCRATCH_DIR_NAME
    )
    payload["mirrored_work_files"] = list_workspace_relative_files(
        execution_root / _DIRECT_EXEC_WORK_DIR_NAME
    )
    payload["mirrored_repair_files"] = list_workspace_relative_files(
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
        relative = candidate.resolve(strict=False).relative_to(
            source_root.resolve(strict=False)
        )
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


def _rewrite_taskfile_worker_env_paths(
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
    explicit_env = {str(key): str(value) for key, value in (env or {}).items()}
    resolved_codex_home = _resolve_recipeimport_codex_home(explicit_env=explicit_env)
    base_root = (
        Path(resolved_codex_home).expanduser()
        if resolved_codex_home
        else Path.home() / ".codex-recipe"
    )
    return base_root / _DIRECT_EXEC_ISOLATION_ROOT_NAME


def _resolve_direct_exec_helper_imports_root(*, env: Mapping[str, str] | None) -> Path:
    explicit_env = {str(key): str(value) for key, value in (env or {}).items()}
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


def _prepare_taskfile_worker_helper_imports(
    *,
    env: Mapping[str, str],
    execution_working_dir: Path,
) -> Path:
    helper_imports_root = _resolve_direct_exec_helper_imports_root(env=env)
    helper_imports_root.mkdir(parents=True, exist_ok=True)
    helper_session_root = helper_imports_root / execution_working_dir.name
    helper_package_root = helper_session_root / "cookimport"
    if helper_package_root.exists():
        _write_taskfile_worker_helper_bin_scripts(helper_session_root)
        return helper_session_root
    source_package_root = Path(__file__).resolve().parents[1]
    shutil.copytree(
        source_package_root,
        helper_package_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    _write_taskfile_worker_helper_bin_scripts(helper_session_root)
    return helper_session_root


def _write_taskfile_worker_helper_bin_scripts(helper_session_root: Path) -> None:
    bin_root = helper_session_root / "bin"
    bin_root.mkdir(parents=True, exist_ok=True)
    python_executable = shlex.quote(sys.executable)
    task_commands = (
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
        TASK_HANDOFF_COMMAND,
    )
    for command_name in task_commands:
        script_path = bin_root / command_name
        script_path.write_text(
            "#!/bin/sh\n"
            f"exec {python_executable} -m cookimport.llm.single_file_worker_commands "
            f"{shlex.quote(command_name)} \"$@\"\n",
            encoding="utf-8",
        )
        script_path.chmod(0o755)
    for executable_name in _SINGLE_FILE_WORKSPACE_SHIM_EXECUTABLES:
        script_path = bin_root / executable_name
        script_path.write_text(
            "#!/bin/sh\n"
            f"exec {python_executable} -m cookimport.llm.single_file_worker_commands "
            f"--shim {shlex.quote(executable_name)} \"$@\"\n",
            encoding="utf-8",
        )
        script_path.chmod(0o755)


def _prepend_pythonpath(
    *,
    env: Mapping[str, str],
    import_root: Path,
) -> dict[str, str]:
    merged = {str(key): str(value) for key, value in env.items()}
    existing = str(merged.get("PYTHONPATH") or "").strip()
    entries = [str(import_root)]
    if existing:
        entries.extend(entry for entry in existing.split(":") if str(entry).strip())
    merged["PYTHONPATH"] = ":".join(entries)
    return merged


def _prepend_path(
    *,
    env: Mapping[str, str],
    path_entries: Sequence[str | Path],
) -> dict[str, str]:
    merged = {str(key): str(value) for key, value in env.items()}
    existing = str(merged.get("PATH") or "")
    entries = [str(entry) for entry in path_entries if str(entry).strip()]
    if existing:
        entries.append(existing)
    merged["PATH"] = ":".join(entries)
    return merged


def _prepare_single_file_workspace_shim_env(
    *,
    env: Mapping[str, str],
) -> dict[str, str]:
    merged = {str(key): str(value) for key, value in env.items()}
    original_path = str(merged.get("PATH") or "")
    merged[_SINGLE_FILE_WORKSPACE_ORIGINAL_PATH_ENV] = original_path
    for executable_name in _SINGLE_FILE_WORKSPACE_SHIM_EXECUTABLES:
        resolved = shutil.which(executable_name, path=original_path)
        if not resolved:
            continue
        env_key = f"RECIPEIMPORT_REAL_EXEC_{executable_name.upper().replace('-', '_')}"
        merged[env_key] = resolved
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
    single_file_task_file_payload = (
        _single_file_workspace_task_file_payload(workspace_root=source_working_dir)
        if single_file_worker_runtime
        else None
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
                single_file_task_file_payload=single_file_task_file_payload,
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
    (execution_working_dir / _DIRECT_EXEC_LOGS_DIR_NAME).mkdir(
        parents=True, exist_ok=True
    )
    (execution_working_dir / _DIRECT_EXEC_SHARDS_DIR_NAME).mkdir(
        parents=True, exist_ok=True
    )
    agents_path = execution_working_dir / _DIRECT_EXEC_AGENTS_FILE_NAME
    agents_path.write_text(
        _build_direct_exec_agents_text(
            task_label=task_label,
            mode=mode,
            single_file_worker_runtime=single_file_worker_runtime,
            single_file_handoff_command=single_file_handoff_command,
            single_file_task_file_payload=single_file_task_file_payload,
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
            assigned_shards = json.loads(
                assigned_shards_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            assigned_shards = []
        if isinstance(assigned_shards, list):
            return assigned_shards
    return []


def _single_file_workspace_handoff_command(*, workspace_root: Path) -> str | None:
    task_file_payload = _single_file_workspace_task_file_payload(
        workspace_root=workspace_root
    )
    if task_file_payload is None:
        return None
    helper_commands = task_file_payload.get("helper_commands")
    if not isinstance(helper_commands, Mapping):
        return TASK_HANDOFF_COMMAND
    handoff_command = str(helper_commands.get("handoff") or "").strip()
    return handoff_command or TASK_HANDOFF_COMMAND


def _single_file_workspace_task_file_payload(
    *,
    workspace_root: Path,
) -> dict[str, Any] | None:
    task_file_path = workspace_root / _DIRECT_EXEC_TASK_FILE_NAME
    if not task_file_path.exists():
        return None
    try:
        return load_task_file(task_file_path)
    except Exception:  # noqa: BLE001
        return None


def _single_file_helper_command(
    task_file_payload: Mapping[str, Any] | None,
    key: str,
    default: str | None = None,
) -> str | None:
    if not isinstance(task_file_payload, Mapping):
        return default
    helper_commands = task_file_payload.get("helper_commands")
    if not isinstance(helper_commands, Mapping):
        return default
    cleaned = str(helper_commands.get(key) or "").strip()
    return cleaned or default


def _single_file_workspace_local_examples(
    task_file_payload: Mapping[str, Any] | None,
    *,
    single_file_handoff_command: str | None,
) -> list[str]:
    stage_key = (
        str(task_file_payload.get("stage_key") or "").strip()
        if isinstance(task_file_payload, Mapping)
        else ""
    )
    if stage_key in {"line_role", "nonrecipe_classify", "knowledge_group"}:
        return [
            "sed -n '1,120p' task.json",
            single_file_handoff_command or TASK_HANDOFF_COMMAND,
            TASK_STATUS_COMMAND,
            TASK_DOCTOR_COMMAND,
            "cp task.json /tmp/task-backup.json",
        ]
    summary_command = _single_file_helper_command(
        task_file_payload, "summary", TASK_SUMMARY_COMMAND
    )
    examples = [summary_command] if summary_command else []
    show_current_command = _single_file_helper_command(
        task_file_payload, "show_current"
    )
    show_neighbors_command = _single_file_helper_command(
        task_file_payload, "show_neighbors"
    )
    answer_current_command = _single_file_helper_command(
        task_file_payload, "answer_current"
    )
    if show_current_command:
        examples.extend(
            [
                show_current_command,
                show_neighbors_command or TASK_SHOW_NEIGHBORS_COMMAND,
                answer_current_command
                or f"{TASK_ANSWER_CURRENT_COMMAND} '<answer_json>'",
                _single_file_helper_command(task_file_payload, "next", TASK_NEXT_COMMAND)
                or TASK_NEXT_COMMAND,
            ]
        )
    else:
        show_unit_command = _single_file_helper_command(
            task_file_payload, "show_unit", f"{TASK_SHOW_UNIT_COMMAND} <unit_id>"
        )
        show_unanswered_command = _single_file_helper_command(
            task_file_payload,
            "show_unanswered",
            f"{TASK_SHOW_UNANSWERED_COMMAND} --limit 5",
        )
        template_command = _single_file_helper_command(
            task_file_payload,
            "template_answers_file",
            f"{TASK_TEMPLATE_COMMAND} answers.json",
        )
        apply_command = _single_file_helper_command(
            task_file_payload,
            "apply_answers_file",
            f"{TASK_APPLY_COMMAND} answers.json",
        )
        examples.extend(
            [
                show_unit_command,
                show_unanswered_command,
                template_command,
                apply_command,
            ]
        )
    examples.append(single_file_handoff_command or TASK_HANDOFF_COMMAND)
    examples.append("cp task.json /tmp/task-backup.json")
    return [example for example in examples if example]


def _build_direct_exec_agents_text(
    *,
    task_label: str | None,
    mode: DirectExecWorkspaceMode,
    single_file_worker_runtime: bool = False,
    single_file_handoff_command: str | None = None,
    single_file_task_file_payload: Mapping[str, Any] | None = None,
) -> str:
    rendered_task_label = str(task_label or "structured shard task").strip()
    if mode == "taskfile":
        if single_file_worker_runtime:
            stage_key = (
                str(single_file_task_file_payload.get("stage_key") or "").strip()
                if isinstance(single_file_task_file_payload, Mapping)
                else ""
            )
            if stage_key in {"line_role", "nonrecipe_classify", "knowledge_group"}:
                handoff_instruction = (
                    f"run `{single_file_handoff_command}` from the workspace root, then stop.\n"
                    if single_file_handoff_command
                    else "run `task-handoff` from the workspace root, then stop.\n"
                )
                return (
                    "# RecipeImport Direct Codex Worker\n\n"
                    "This directory is an isolated runtime workspace for one RecipeImport "
                    f"{rendered_task_label}.\n\n"
                    "You are not working on the RecipeImport repository itself.\n"
                    "Use only the files inside this directory.\n"
                    "The current working directory is already the workspace root.\n"
                    "This workspace exposes one repo-written task file: `task.json`.\n"
                    "Open `task.json` directly and read the assignment in place.\n"
                    "Edit only `/units/*/answer`, save the same file, and "
                    f"{handoff_instruction}"
                    "`task.json` is the whole job. You do not need hidden repo context, queue files, helper ledgers, or alternate answer files.\n"
                    "`task-status` and `task-doctor` are optional troubleshooting helpers, not the default path.\n"
                    "Ordinary local reads of `task.json` and `AGENTS.md` are allowed.\n"
                    "Do not invent helper ledgers, alternate output files, queue files, or scripted task-file rewrites.\n"
                    "Do not inspect parent directories, repository-wide AGENTS files, project docs, or source code.\n"
                    "Do not run repo-specific commands such as `npm run docs:list` or `git`.\n"
                    "Hard boundaries still apply: stay inside this workspace, keep paths local or in approved temp roots, and avoid repo/network/package-manager commands such as `git`, `curl`, or `npm`.\n"
                    "Do not modify immutable evidence or metadata fields.\n"
                )
            summary_command = _single_file_helper_command(
                single_file_task_file_payload,
                "summary",
                TASK_SUMMARY_COMMAND,
            )
            show_current_command = _single_file_helper_command(
                single_file_task_file_payload, "show_current"
            )
            show_neighbors_command = _single_file_helper_command(
                single_file_task_file_payload,
                "show_neighbors",
                TASK_SHOW_NEIGHBORS_COMMAND,
            )
            answer_current_command = _single_file_helper_command(
                single_file_task_file_payload,
                "answer_current",
                f"{TASK_ANSWER_CURRENT_COMMAND} '<answer_json>'",
            )
            next_command = _single_file_helper_command(
                single_file_task_file_payload, "next", TASK_NEXT_COMMAND
            )
            show_unit_command = _single_file_helper_command(
                single_file_task_file_payload,
                "show_unit",
                f"{TASK_SHOW_UNIT_COMMAND} <unit_id>",
            )
            show_unanswered_command = _single_file_helper_command(
                single_file_task_file_payload,
                "show_unanswered",
                f"{TASK_SHOW_UNANSWERED_COMMAND} --limit 5",
            )
            template_command = _single_file_helper_command(
                single_file_task_file_payload,
                "template_answers_file",
                f"{TASK_TEMPLATE_COMMAND} answers.json",
            )
            apply_command = _single_file_helper_command(
                single_file_task_file_payload,
                "apply_answers_file",
                f"{TASK_APPLY_COMMAND} answers.json",
            )
            handoff_instruction = (
                "run the repo-owned same-session helper command from "
                f"`task.json` (`{single_file_handoff_command}`), then stop.\n"
                if single_file_handoff_command
                else "run the repo-owned same-session helper command named in `task.json`, then stop.\n"
            )
            helper_startup_instruction = (
                f"If you need the current queue position, use `{show_current_command}` "
                f"or `{show_neighbors_command}`.\n"
                f"Record one decision at a time with `{answer_current_command}`, then "
                f"confirm the next actionable unit with `{next_command}`.\n"
                if show_current_command
                else (
                    f"If you need specific unit payloads, use `{show_unit_command}` or "
                    f"`{show_unanswered_command}`.\n"
                    + (
                        f"If you want to apply several answers at once, use `{template_command}` "
                        f"and `{apply_command}` instead of scripting a rewrite.\n"
                    )
                )
            )
            return (
                "# RecipeImport Direct Codex Worker\n\n"
                "This directory is an isolated runtime workspace for one RecipeImport "
                f"{rendered_task_label}.\n\n"
                "You are not working on the RecipeImport repository itself.\n"
                "Use only the files inside this directory.\n"
                "The current working directory is already the workspace root.\n"
                "This workspace exposes one repo-written file: `task.json`.\n"
                f"Start with `{summary_command}`.\n"
                f"{helper_startup_instruction}"
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
