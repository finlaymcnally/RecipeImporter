from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .editable_task_file import (
    TASK_FILE_NAME,
    _load_answer_mapping_file,
    apply_answers_to_task_file,
    inspect_task_file_units,
    load_task_file,
    summarize_task_file,
    write_task_file,
)

TASK_SUMMARY_COMMAND = "task-summary"
TASK_SHOW_UNIT_COMMAND = "task-show-unit"
TASK_SHOW_UNANSWERED_COMMAND = "task-show-unanswered"
TASK_TEMPLATE_COMMAND = "task-template"
TASK_APPLY_COMMAND = "task-apply"
TASK_STATUS_COMMAND = "task-status"
TASK_DOCTOR_COMMAND = "task-doctor"
TASK_HANDOFF_COMMAND = "task-handoff"
TASK_SHOW_CURRENT_COMMAND = "task-show-current"
TASK_SHOW_NEIGHBORS_COMMAND = "task-show-neighbors"
TASK_ANSWER_CURRENT_COMMAND = "task-answer-current"
TASK_NEXT_COMMAND = "task-next"

RECIPE_STAGE_KEY = "recipe_refine"
LINE_ROLE_STAGE_KEY = "line_role"
KNOWLEDGE_CLASSIFY_STAGE_KEY = "nonrecipe_classify"
KNOWLEDGE_GROUP_STAGE_KEY = "knowledge_group"

_ORIGINAL_PATH_ENV = "RECIPEIMPORT_SINGLE_FILE_ORIGINAL_PATH"


@dataclass(frozen=True)
class SingleFileWorkerSurface:
    helper_commands: dict[str, str]
    workflow: tuple[str, ...]
    task_dump_hint: str
    workspace_listing_hint: str
    inline_rewrite_hint: str
    batch_apply_allowed: bool


def build_single_file_worker_surface(*, stage_key: str) -> SingleFileWorkerSurface:
    cleaned_stage_key = str(stage_key or "").strip()
    shared_commands = {
        "summary": TASK_SUMMARY_COMMAND,
        "status": TASK_STATUS_COMMAND,
        "doctor": TASK_DOCTOR_COMMAND,
        "handoff": TASK_HANDOFF_COMMAND,
        "stage_key": cleaned_stage_key,
    }
    if cleaned_stage_key == KNOWLEDGE_CLASSIFY_STAGE_KEY:
        return SingleFileWorkerSurface(
            helper_commands={
                **shared_commands,
                "show_current": TASK_SHOW_CURRENT_COMMAND,
                "show_neighbors": TASK_SHOW_NEIGHBORS_COMMAND,
                "answer_current": f"{TASK_ANSWER_CURRENT_COMMAND} '<answer_json>'",
                "next": TASK_NEXT_COMMAND,
            },
            workflow=(
                TASK_SUMMARY_COMMAND,
                TASK_SHOW_CURRENT_COMMAND,
                TASK_ANSWER_CURRENT_COMMAND,
                f"{TASK_NEXT_COMMAND}/{TASK_HANDOFF_COMMAND}",
            ),
            task_dump_hint=(
                f"Use {TASK_SUMMARY_COMMAND}, {TASK_SHOW_CURRENT_COMMAND}, or "
                f"{TASK_SHOW_NEIGHBORS_COMMAND} instead of dumping task.json."
            ),
            workspace_listing_hint=(
                f"Use {TASK_SUMMARY_COMMAND} instead of broad workspace listing; "
                "task.json is the whole job."
            ),
            inline_rewrite_hint=(
                f"Use {TASK_SHOW_CURRENT_COMMAND} or {TASK_ANSWER_CURRENT_COMMAND} "
                "instead of scripting classification decisions."
            ),
            batch_apply_allowed=False,
        )
    return SingleFileWorkerSurface(
        helper_commands={
            **shared_commands,
            "show_unit": f"{TASK_SHOW_UNIT_COMMAND} <unit_id>",
            "show_unanswered": f"{TASK_SHOW_UNANSWERED_COMMAND} --limit 5",
            "template_answers_file": f"{TASK_TEMPLATE_COMMAND} answers.json",
            "apply_answers_file": f"{TASK_APPLY_COMMAND} answers.json",
        },
        workflow=(
            TASK_SUMMARY_COMMAND,
            TASK_SHOW_UNIT_COMMAND,
            TASK_TEMPLATE_COMMAND,
            TASK_APPLY_COMMAND,
            TASK_HANDOFF_COMMAND,
        ),
        task_dump_hint=(
            f"Use {TASK_SUMMARY_COMMAND} or {TASK_SHOW_UNIT_COMMAND} instead of "
            "dumping task.json."
        ),
        workspace_listing_hint=(
            f"Use {TASK_SUMMARY_COMMAND} instead of broad workspace listing; "
            "task.json is the whole job."
        ),
        inline_rewrite_hint=(
            f"Use {TASK_TEMPLATE_COMMAND} plus {TASK_APPLY_COMMAND} instead of "
            "rewriting task.json with inline python for this stage."
        ),
        batch_apply_allowed=True,
    )


def _task_file_path() -> Path:
    return Path(TASK_FILE_NAME)


def _load_current_task_file() -> dict[str, Any]:
    return load_task_file(_task_file_path())


def _surface_for_payload(payload: Mapping[str, Any]) -> SingleFileWorkerSurface:
    return build_single_file_worker_surface(
        stage_key=str(payload.get("stage_key") or "").strip()
    )


def _normalized_units(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(unit)
        for unit in (payload.get("units") or [])
        if isinstance(unit, Mapping)
    ]


def _unit_id_for_index(unit: Mapping[str, Any], index: int) -> str:
    cleaned = str(unit.get("unit_id") or "").strip()
    return cleaned or f"unit-{index:03d}"


def _unit_answered(unit: Mapping[str, Any]) -> bool:
    answer = unit.get("answer")
    if not isinstance(answer, Mapping):
        return False
    return any(_value_has_content(value) for value in answer.values())


def _value_has_content(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_value_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_value_has_content(item) for item in value)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _first_unanswered_index(payload: Mapping[str, Any]) -> int | None:
    for index, unit in enumerate(_normalized_units(payload)):
        if not _unit_answered(unit):
            return index
    return None


def _current_unit_id(payload: Mapping[str, Any]) -> str | None:
    current_index = _first_unanswered_index(payload)
    if current_index is None:
        return None
    unit = _normalized_units(payload)[current_index]
    return _unit_id_for_index(unit, current_index)


def _show_unit_payload(*, payload: Mapping[str, Any], unit_ids: Sequence[str]) -> dict[str, Any]:
    return inspect_task_file_units(
        payload=payload,
        task_file_path=TASK_FILE_NAME,
        unit_ids=unit_ids,
    )


def _show_current_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    current_unit_id = _current_unit_id(payload)
    if current_unit_id is None:
        return {
            "task_file": TASK_FILE_NAME,
            "stage_key": str(payload.get("stage_key") or ""),
            "status": "all_units_answered",
            "summary": summarize_task_file(payload=payload, task_file_path=TASK_FILE_NAME),
        }
    result = _show_unit_payload(payload=payload, unit_ids=[current_unit_id])
    result["current_unit_id"] = current_unit_id
    return result


def _show_neighbors_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    units = _normalized_units(payload)
    current_index = _first_unanswered_index(payload)
    if current_index is None:
        return {
            "task_file": TASK_FILE_NAME,
            "stage_key": str(payload.get("stage_key") or ""),
            "status": "all_units_answered",
            "summary": summarize_task_file(payload=payload, task_file_path=TASK_FILE_NAME),
        }
    neighbor_indices = [
        index
        for index in range(max(0, current_index - 1), min(len(units), current_index + 2))
    ]
    unit_ids = [_unit_id_for_index(units[index], index) for index in neighbor_indices]
    result = _show_unit_payload(payload=payload, unit_ids=unit_ids)
    result["current_unit_id"] = _unit_id_for_index(units[current_index], current_index)
    result["neighbor_window"] = {
        "start_index": neighbor_indices[0],
        "end_index": neighbor_indices[-1],
    }
    return result


def _template_value_from_example(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _template_value_from_example(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return []
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)) or value is None:
        return None
    return None


def build_answer_template_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    answer_schema = payload.get("answer_schema")
    example_answer = {}
    if isinstance(answer_schema, Mapping):
        examples = answer_schema.get("example_answers")
        if isinstance(examples, list):
            for row in examples:
                if isinstance(row, Mapping):
                    example_answer = dict(row)
                    break
    template_answer = _template_value_from_example(example_answer)
    answers_by_unit_id: dict[str, Any] = {}
    for index, unit in enumerate(_normalized_units(payload)):
        if _unit_answered(unit):
            continue
        unit_id = _unit_id_for_index(unit, index)
        answers_by_unit_id[unit_id] = json.loads(
            json.dumps(template_answer, sort_keys=True)
        )
    return {"answers_by_unit_id": answers_by_unit_id}


def write_answer_template(*, path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    template_payload = build_answer_template_payload(payload)
    path.write_text(
        json.dumps(template_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "template_path": str(path),
        "unit_count": len(template_payload["answers_by_unit_id"]),
        "unit_ids": sorted(template_payload["answers_by_unit_id"]),
    }


def _resolve_handoff_module(stage_key: str) -> str:
    if stage_key == RECIPE_STAGE_KEY:
        return "cookimport.llm.recipe_same_session_handoff"
    if stage_key in {KNOWLEDGE_CLASSIFY_STAGE_KEY, KNOWLEDGE_GROUP_STAGE_KEY}:
        return "cookimport.llm.knowledge_same_session_handoff"
    if stage_key == LINE_ROLE_STAGE_KEY:
        return "cookimport.parsing.canonical_line_roles.same_session_handoff"
    raise SystemExit(f"unsupported single-file stage {stage_key!r}")


def _run_handoff_command(stage_key: str, *args: str) -> int:
    module_name = _resolve_handoff_module(stage_key)
    completed = subprocess.run(
        [sys.executable, "-m", module_name, *args],
        check=False,
    )
    return int(completed.returncode)


def _print_json(payload: Mapping[str, Any]) -> int:
    print(json.dumps(dict(payload), sort_keys=True))
    return 0


def _usage_error(message: str) -> int:
    raise SystemExit(message)


def _apply_current_answer(raw_answer_json: str) -> dict[str, Any]:
    task_file = _load_current_task_file()
    current_unit_id = _current_unit_id(task_file)
    if current_unit_id is None:
        raise SystemExit("all units are already answered")
    try:
        answer_payload = json.loads(raw_answer_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid answer JSON: {exc}") from exc
    if not isinstance(answer_payload, Mapping):
        raise SystemExit("answer JSON must be one object")
    result = apply_answers_to_task_file(
        path=_task_file_path(),
        answers_by_unit_id={current_unit_id: dict(answer_payload)},
    )
    updated_task_file = _load_current_task_file()
    result["answered_unit_id"] = current_unit_id
    result["next_current_unit_id"] = _current_unit_id(updated_task_file)
    return result


def _show_unanswered_payload(payload: Mapping[str, Any], *, limit: int | None) -> dict[str, Any]:
    return inspect_task_file_units(
        payload=payload,
        task_file_path=TASK_FILE_NAME,
        answered=False,
        limit=limit,
    )


def _single_file_workspace_active() -> bool:
    cwd = Path.cwd()
    return (
        (cwd / TASK_FILE_NAME).exists()
        and not (cwd / "assigned_tasks.json").exists()
        and not (cwd / "assigned_shards.json").exists()
    )


def _task_file_stage_key() -> str:
    try:
        payload = _load_current_task_file()
    except Exception:  # noqa: BLE001
        return ""
    return str(payload.get("stage_key") or "").strip()


def _real_executable(name: str) -> str | None:
    env_key = f"RECIPEIMPORT_REAL_EXEC_{name.upper().replace('-', '_')}"
    explicit = str(os.environ.get(env_key) or "").strip()
    if explicit:
        return explicit
    original_path = str(os.environ.get(_ORIGINAL_PATH_ENV) or "").strip()
    if original_path:
        import shutil

        return shutil.which(name, path=original_path)
    return None


def _exec_real_command(name: str, args: Sequence[str]) -> int:
    executable = _real_executable(name)
    if not executable:
        raise SystemExit(f"unable to resolve real executable for {name!r}")
    completed = subprocess.run([executable, *args], check=False)
    return int(completed.returncode)


def _task_path_argument_present(args: Sequence[str]) -> bool:
    for arg in args:
        cleaned = str(arg or "").strip()
        if cleaned in {TASK_FILE_NAME, f"./{TASK_FILE_NAME}"}:
            return True
    return False


def _python_inline_script(args: Sequence[str]) -> str | None:
    if not args:
        return None
    if args[0] == "-c" and len(args) >= 2:
        return str(args[1])
    if args[0] == "-" and len(args) >= 2:
        return str(args[1])
    return None


def _python_module_args(args: Sequence[str]) -> tuple[str, list[str]] | None:
    if len(args) >= 2 and args[0] == "-m":
        return str(args[1]).strip(), [str(arg) for arg in args[2:]]
    return None


def _print_stage_redirect(kind: str) -> int:
    stage_key = _task_file_stage_key()
    surface = build_single_file_worker_surface(stage_key=stage_key)
    if kind == "task-dump":
        print(surface.task_dump_hint, file=sys.stderr)
        return 0
    if kind == "workspace-listing":
        print(surface.workspace_listing_hint, file=sys.stderr)
        return 0
    if kind == "inline-rewrite":
        print(surface.inline_rewrite_hint, file=sys.stderr)
        return 0
    raise SystemExit(f"unknown redirect kind {kind!r}")


def _dispatch_shim(command_name: str, args: Sequence[str]) -> int:
    if not _single_file_workspace_active():
        return _exec_real_command(command_name, args)
    if command_name == "cat" and _task_path_argument_present(args):
        return _print_stage_redirect("task-dump")
    if command_name == "ls":
        return _print_stage_redirect("workspace-listing")
    if command_name in {"python3", "python"}:
        module_args = _python_module_args(args)
        stage_key = _task_file_stage_key()
        if module_args is not None:
            module_name, module_tail = module_args
            if module_name in {
                "cookimport.llm.editable_task_file",
                "cookimport.llm.recipe_same_session_handoff",
                "cookimport.llm.knowledge_same_session_handoff",
                "cookimport.parsing.canonical_line_roles.same_session_handoff",
            }:
                if (
                    stage_key == KNOWLEDGE_CLASSIFY_STAGE_KEY
                    and module_name == "cookimport.llm.editable_task_file"
                    and any(
                        marker in module_tail
                        for marker in (
                            "--apply-answers-file",
                            "--show-unanswered",
                            "--set-answer",
                        )
                    )
                ):
                    return _print_stage_redirect("inline-rewrite")
                return _exec_real_command(command_name, args)
        inline_script = _python_inline_script(args)
        if inline_script and "task.json" in inline_script.lower():
            return _print_stage_redirect("inline-rewrite")
    return _exec_real_command(command_name, args)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        raise SystemExit("expected a task command")
    command_name = str(args.pop(0))
    if command_name == "--shim":
        if not args:
            raise SystemExit("missing shim command name")
        shim_name = str(args.pop(0))
        return _dispatch_shim(shim_name, args)

    task_file = _load_current_task_file()
    stage_key = str(task_file.get("stage_key") or "").strip()
    surface = _surface_for_payload(task_file)

    if command_name == TASK_SUMMARY_COMMAND:
        return _print_json(summarize_task_file(payload=task_file, task_file_path=TASK_FILE_NAME))
    if command_name == TASK_SHOW_UNIT_COMMAND:
        if len(args) != 1:
            return _usage_error("usage: task-show-unit <unit_id>")
        return _print_json(_show_unit_payload(payload=task_file, unit_ids=[args[0]]))
    if command_name == TASK_SHOW_UNANSWERED_COMMAND:
        limit = None
        if args:
            if len(args) == 2 and args[0] == "--limit":
                limit = int(args[1])
            else:
                return _usage_error("usage: task-show-unanswered [--limit N]")
        if not surface.batch_apply_allowed:
            raise SystemExit(
                f"{TASK_SHOW_UNANSWERED_COMMAND} is unavailable for {stage_key}; "
                f"use {TASK_SHOW_CURRENT_COMMAND} instead."
            )
        return _print_json(_show_unanswered_payload(task_file, limit=limit))
    if command_name == TASK_TEMPLATE_COMMAND:
        if len(args) != 1:
            return _usage_error("usage: task-template <answers_path>")
        if not surface.batch_apply_allowed:
            raise SystemExit(
                f"{TASK_TEMPLATE_COMMAND} is unavailable for {stage_key}; "
                f"use {TASK_SHOW_CURRENT_COMMAND} and {TASK_ANSWER_CURRENT_COMMAND} instead."
            )
        return _print_json(write_answer_template(path=Path(args[0]), payload=task_file))
    if command_name == TASK_APPLY_COMMAND:
        if len(args) != 1:
            return _usage_error("usage: task-apply <answers_path>")
        if not surface.batch_apply_allowed:
            raise SystemExit(
                f"{TASK_APPLY_COMMAND} is unavailable for {stage_key}; "
                f"use {TASK_ANSWER_CURRENT_COMMAND} instead."
            )
        answers_by_unit_id = _load_answer_mapping_file(Path(args[0]))
        return _print_json(
            apply_answers_to_task_file(
                path=_task_file_path(),
                answers_by_unit_id=answers_by_unit_id,
            )
        )
    if command_name == TASK_SHOW_CURRENT_COMMAND:
        return _print_json(_show_current_payload(task_file))
    if command_name == TASK_SHOW_NEIGHBORS_COMMAND:
        return _print_json(_show_neighbors_payload(task_file))
    if command_name == TASK_ANSWER_CURRENT_COMMAND:
        if len(args) != 1:
            return _usage_error("usage: task-answer-current '<answer_json>'")
        return _print_json(_apply_current_answer(args[0]))
    if command_name == TASK_NEXT_COMMAND:
        return _print_json(_show_current_payload(_load_current_task_file()))
    if command_name == TASK_STATUS_COMMAND:
        return _run_handoff_command(stage_key, "--status")
    if command_name == TASK_DOCTOR_COMMAND:
        return _run_handoff_command(stage_key, "--doctor")
    if command_name == TASK_HANDOFF_COMMAND:
        return _run_handoff_command(stage_key)

    raise SystemExit(f"unknown task command {command_name!r}")


if __name__ == "__main__":
    raise SystemExit(main())
