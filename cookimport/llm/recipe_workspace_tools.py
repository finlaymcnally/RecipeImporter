from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Any, Mapping, Sequence

_TOP_LEVEL_KEYS = frozenset({"v", "sid", "r"})
_RESULT_KEYS = frozenset({"v", "rid", "st", "sr", "cr", "m", "mr", "g", "w"})
_CANONICAL_KEYS = frozenset({"t", "i", "s", "d", "y"})
_MAPPING_KEYS = frozenset({"i", "s"})
_TAG_KEYS = frozenset({"c", "l", "f"})
_VALID_STATUSES = frozenset({"repaired", "fragmentary", "not_a_recipe"})
_PLACEHOLDER_MARKER = "__EDIT_ME__"
_CURRENT_TASK_FILE_NAME = "current_task.json"
_CURRENT_TASK_BRIEF_FILE_NAME = "CURRENT_TASK.md"
_CURRENT_TASK_FEEDBACK_FILE_NAME = "CURRENT_TASK_FEEDBACK.md"
_SHARD_PACKET_FILE_NAME = "SHARD_PACKET.md"
_PREPARED_DRAFT_MANIFEST_NAME = "_prepared_drafts.json"
_NO_CURRENT_TASK_ACTIVE_TEXT = "No current task is active. The queue is complete."
_ACTIVE_ASSIGNMENT_TEXT = (
    "This worker assignment stays active until the repo rewrites `current_task.json` "
    "or says the queue is complete."
)
_NO_REPO_WRITTEN_FEEDBACK_TEXT = "No repo-written validation feedback exists yet for this task."
_VALIDATION_STATUS_OK_TEXT = "Validation status: OK."
_VALIDATION_STATUS_FAILED_TEXT = "Validation status: FAILED."
_INSTALL_CURRENT_READY_TEXT = (
    "You may run `python3 tools/recipe_worker.py install-current` to write the final result path."
)
_REOPEN_AFTER_INSTALL_TEXT = (
    "After `install-current`, re-open `CURRENT_TASK.md`, `current_task.json`, and "
    "`CURRENT_TASK_FEEDBACK.md`."
)
_CONTINUE_IMMEDIATELY_TEXT = (
    "If another task becomes active, continue with that task immediately. Do not ask "
    "for permission to continue while later tasks remain."
)
_LEGACY_KEY_SUGGESTIONS = {
    "bundle_version": "v",
    "shard_id": "sid",
    "results": "r",
    "recipes": "r",
    "recipe_id": "rid",
    "repair_status": "st",
    "status_reason": "sr",
    "canonical_recipe": "cr",
    "ingredient_step_mapping": "m",
    "ingredient_step_mapping_reason": "mr",
    "selected_tags": "g",
    "warnings": "w",
    "not_a_recipe": "st=not_a_recipe",
    "fragmentary": "st=fragmentary",
    "notes": "sr or w",
    "title": "cr.t",
    "ingredients": "cr.i",
    "steps": "cr.s",
    "description": "cr.d",
    "recipeYield": "cr.y",
    "recipe_yield": "cr.y",
    "category": "c",
    "label": "l",
    "confidence": "f",
}


def _coerce_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sanitize_text(value: Any) -> str:
    return str(value or "").strip()


def _sanitize_text_list(values: Any) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    return [text for text in (_sanitize_text(value) for value in values) if text]


def _task_metadata(task_row: Mapping[str, Any]) -> dict[str, Any]:
    return _coerce_mapping(task_row.get("metadata"))


def _task_id(task_row: Mapping[str, Any]) -> str:
    return _sanitize_text(task_row.get("task_id"))


def _task_paths(task_row: Mapping[str, Any]) -> dict[str, str]:
    task_id = _task_id(task_row)
    metadata = _task_metadata(task_row)
    return {
        "input_path": _sanitize_text(metadata.get("input_path")) or f"in/{task_id}.json",
        "hint_path": _sanitize_text(metadata.get("hint_path")) or f"hints/{task_id}.md",
        "result_path": _sanitize_text(metadata.get("result_path")) or f"out/{task_id}.json",
        "scratch_draft_path": _sanitize_text(metadata.get("scratch_draft_path"))
        or f"scratch/{task_id}.json",
    }


def recipe_worker_task_paths(task_row: Mapping[str, Any]) -> dict[str, str]:
    return _task_paths(task_row)


def _owned_recipe_ids(task_row: Mapping[str, Any]) -> list[str]:
    owned_ids = _sanitize_text_list(task_row.get("owned_ids"))
    if owned_ids:
        return owned_ids
    input_payload = _coerce_mapping(task_row.get("input_payload"))
    return _sanitize_text_list(input_payload.get("ids"))


def _recipe_input_rows(task_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    input_payload = _coerce_mapping(task_row.get("input_payload"))
    rows = input_payload.get("r")
    if not isinstance(rows, list):
        return []
    return [_coerce_mapping(row) for row in rows if isinstance(row, Mapping)]


def _placeholder(label: str) -> str:
    return f"{_PLACEHOLDER_MARKER}_{label}"


def load_recipe_worker_task_rows(*, workspace_root: Path) -> list[dict[str, Any]]:
    assigned_tasks_path = workspace_root / "assigned_tasks.json"
    if not assigned_tasks_path.exists():
        return []
    try:
        payload = json.loads(assigned_tasks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [_coerce_mapping(row) for row in payload if isinstance(row, Mapping)]


def load_current_recipe_worker_task(*, workspace_root: Path) -> dict[str, Any] | None:
    current_task_path = workspace_root / _CURRENT_TASK_FILE_NAME
    if not current_task_path.exists():
        return None
    try:
        payload = json.loads(current_task_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return _coerce_mapping(payload) if isinstance(payload, Mapping) else None


def resolve_current_recipe_worker_task(*, workspace_root: Path) -> dict[str, Any]:
    task_row = load_current_recipe_worker_task(workspace_root=workspace_root)
    if task_row is None:
        raise ValueError("no current task is active in this workspace")
    return task_row


def render_recipe_worker_overview(
    *,
    task_rows: Sequence[Mapping[str, Any]],
    current_task_id: str | None = None,
) -> str:
    lines = ["Recipe worker task overview:"]
    if not task_rows:
        lines.append("- no assigned tasks found")
        return "\n".join(lines)
    for index, task_row in enumerate(task_rows, start=1):
        task_id = _task_id(task_row)
        recipe_ids = ", ".join(_owned_recipe_ids(task_row)) or "[none]"
        paths = _task_paths(task_row)
        current_marker = " current" if task_id and task_id == _sanitize_text(current_task_id) else ""
        lines.append(
            f"- {index}. {task_id}{current_marker} | recipes: {recipe_ids} | "
            f"hint: {paths['hint_path']} | input: {paths['input_path']} | output: {paths['result_path']}"
        )
    return "\n".join(lines)


def render_recipe_worker_task_summary(*, task_row: Mapping[str, Any]) -> str:
    task_id = _task_id(task_row)
    task_kind = _sanitize_text(task_row.get("task_kind")) or "[unknown]"
    parent_shard_id = _sanitize_text(task_row.get("parent_shard_id")) or "[unknown]"
    recipe_ids = _owned_recipe_ids(task_row)
    paths = _task_paths(task_row)
    input_rows = _recipe_input_rows(task_row)
    lines = [
        f"task_id: {task_id}",
        f"task_kind: {task_kind}",
        f"parent_shard_id: {parent_shard_id}",
        f"owned_recipe_ids: {', '.join(recipe_ids) if recipe_ids else '[none]'}",
        f"hint_path: {paths['hint_path']}",
        f"input_path: {paths['input_path']}",
        f"scratch_draft_path: {paths['scratch_draft_path']}",
        f"result_path: {paths['result_path']}",
    ]
    if input_rows:
        lines.append("recipe candidates:")
        for row in input_rows:
            hint = _coerce_mapping(row.get("h"))
            title_hint = _sanitize_text(hint.get("n")) or "[no title hint]"
            ingredient_count = len(_sanitize_text_list(hint.get("i")))
            step_count = len(_sanitize_text_list(hint.get("s")))
            lines.append(
                f"- { _sanitize_text(row.get('rid')) or '[unknown]' }: "
                f"title={title_hint!r} ingredients={ingredient_count} steps={step_count}"
            )
    return "\n".join(lines)


def _task_position(
    *,
    task_rows: Sequence[Mapping[str, Any]],
    current_task_id: str | None,
) -> tuple[int | None, int | None, str | None]:
    rows = [row for row in task_rows if _task_id(row)]
    if not rows:
        return None, None, None
    current_id = _sanitize_text(current_task_id)
    for index, row in enumerate(rows, start=1):
        if _task_id(row) != current_id:
            continue
        next_task_id = _task_id(rows[index]) if index < len(rows) else None
        return index, len(rows), next_task_id
    return None, len(rows), _task_id(rows[0])


def _current_task_contract_quick_reference() -> list[str]:
    return [
        "Compact contract quick reference:",
        "- Top level keys: `v`, `sid`, `r`.",
        "- Per-recipe keys: `v`, `rid`, `st`, `sr`, `cr`, `m`, `mr`, `g`, `w`.",
        "- `st=repaired`: `cr` must be a canonical recipe object.",
        "- `st=fragmentary`: set `cr` to null and use `mr=not_applicable_fragmentary`.",
        "- `st=not_a_recipe`: set `cr` to null and use `mr=not_applicable_not_a_recipe`.",
        "- Tiny examples: repaired -> `{\"st\":\"repaired\",\"cr\":{...},\"m\":[],\"mr\":\"not_needed_single_step\"}`; fragmentary -> `{\"st\":\"fragmentary\",\"cr\":null,\"mr\":\"not_applicable_fragmentary\"}`; not_a_recipe -> `{\"st\":\"not_a_recipe\",\"cr\":null,\"mr\":\"not_applicable_not_a_recipe\"}`.",
        "- Legacy keys are invalid here: `results`, `recipes`, `recipe_id`, `repair_status`, `canonical_recipe`, `notes`.",
    ]


def _task_candidate_packet_lines(*, task_row: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for row in _recipe_input_rows(task_row):
        recipe_id = _sanitize_text(row.get("rid")) or "[unknown]"
        hint = _coerce_mapping(row.get("h"))
        title = _sanitize_text(hint.get("n")) or "[no title hint]"
        ingredients = _sanitize_text_list(hint.get("i"))
        steps = _sanitize_text_list(hint.get("s"))
        preview_ingredients = "; ".join(ingredients[:2]) or "[none]"
        preview_steps = "; ".join(steps[:2]) or "[none]"
        lines.append(
            f"- `{recipe_id}` title={title!r} | ingredients={len(ingredients)} [{preview_ingredients}] | "
            f"steps={len(steps)} [{preview_steps}]"
        )
    return lines or ["- no candidate rows available"]


def render_recipe_worker_shard_packet(
    *,
    task_rows: Sequence[Mapping[str, Any]],
    current_task_id: str | None = None,
) -> str:
    rows = [row for row in task_rows if _task_id(row)]
    current_id = _sanitize_text(current_task_id)
    current_task_row = next(
        (row for row in rows if _task_id(row) == current_id),
        rows[0] if rows else None,
    )
    lines: list[str] = [
        "# Recipe Shard Packet",
        "",
        "Read this file first. It is the authoritative packed shard summary for the normal recipe worker path.",
        "The default loop is: read this packet, edit the current draft, run `check-current`, run `install-current`, then re-open the current-task sidecars if another task becomes active.",
        "Open raw `hints/*.md`, `in/*.json`, `OUTPUT_CONTRACT.md`, `examples/*.json`, or `tools/recipe_worker.py` only if this packet and the current-task sidecars are still insufficient.",
        "",
        (
            f"current_task_id: {_task_id(current_task_row)}"
            if current_task_row is not None
            else "current_task_id: [none]"
        ),
        f"task_count: {len(rows)}",
        "",
        *_current_task_contract_quick_reference(),
        "",
        "Status guide:",
        "- Use `repaired` only when you can restate a real recipe from the owned source.",
        "- Use `fragmentary` when recipe evidence exists but the owned text is too incomplete to normalize safely.",
        "- Use `not_a_recipe` when the owned text is not a recipe at all.",
        "",
        "Shard queue:",
    ]
    if not rows:
        lines.append("- no assigned tasks found")
        return "\n".join(lines)
    for index, task_row in enumerate(rows, start=1):
        paths = _task_paths(task_row)
        marker = " current" if _task_id(task_row) == _task_id(current_task_row or {}) else ""
        lines.extend(
            [
                f"- {index}. {_task_id(task_row)}{marker}",
                f"  draft: `{paths['scratch_draft_path']}`",
                f"  output: `{paths['result_path']}`",
                f"  hint fallback: `{paths['hint_path']}`",
                f"  input fallback: `{paths['input_path']}`",
                f"  owned_recipe_ids: {', '.join(_owned_recipe_ids(task_row)) or '[none]'}",
                "  candidate summary:",
                *[f"  {line}" for line in _task_candidate_packet_lines(task_row=task_row)],
            ]
        )
    return "\n".join(lines)


def render_recipe_worker_current_task_brief(
    *,
    task_row: Mapping[str, Any] | None,
    task_rows: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    rows = list(task_rows or ())
    if task_row is None:
        return "\n".join(
            [
                "# Current Recipe Task",
                "",
                "No current task is active in this workspace.",
                "Every assigned recipe task already has a repo-accepted output.",
            ]
        )
    paths = _task_paths(task_row)
    current_task_id = _task_id(task_row)
    task_sequence, task_total, next_task_id = _task_position(
        task_rows=rows or [task_row],
        current_task_id=current_task_id,
    )
    lines = [
        "# Current Recipe Task",
        "",
        render_recipe_worker_task_summary(task_row=task_row),
        (
            f"queue_position: {task_sequence}/{task_total}"
            if task_sequence is not None and task_total is not None
            else "queue_position: unknown"
        ),
        (
            f"next_task_id: {next_task_id}"
            if next_task_id
            else "next_task_id: [none]"
        ),
        "",
        _ACTIVE_ASSIGNMENT_TEXT,
        "",
        "Recommended loop:",
        f"- Edit the prewritten draft at `{paths['scratch_draft_path']}` first.",
        f"- Open `{paths['hint_path']}` only if the brief or draft is still unclear.",
        f"- Open `{paths['input_path']}` only if the draft and hint still leave something unresolved.",
        "- Run `python3 tools/recipe_worker.py check-current` after editing the current draft.",
        "- Run `python3 tools/recipe_worker.py install-current` only after `check-current` says OK.",
        f"- For obvious terminal cases, use `python3 tools/recipe_worker.py stamp-status fragmentary \"<reason>\" {paths['scratch_draft_path']}` or the same command with `not_a_recipe`.",
        "- After `install-current`, re-open the current-task sidecars and keep going if another task is active.",
        "",
        *_current_task_contract_quick_reference(),
        "",
        "Fallback only:",
        "- `OUTPUT_CONTRACT.md`, `examples/*.json`, and `tools/recipe_worker.py` are fallback/debug references, not the normal first read.",
        "- `python3 tools/recipe_worker.py prepare-all --dest-dir scratch/` and `finalize-all scratch/` stay available for recovery or bulk cleanup, not as the default queue loop.",
    ]
    return "\n".join(lines)


def render_recipe_worker_feedback_brief(
    *,
    task_rows: Sequence[Mapping[str, Any]],
    current_task_id: str | None = None,
    validation_state: str = "pending",
    validation_errors: Sequence[str] | None = None,
    current_draft_path: str | None = None,
) -> str:
    rows = list(task_rows)
    current_task_row = next(
        (
            row
            for row in rows
            if _task_id(row) and _task_id(row) == _sanitize_text(current_task_id)
        ),
        None,
    )
    current_paths = _task_paths(current_task_row) if current_task_row is not None else {}
    lines: list[str] = [
        "# Recipe Worker Queue",
        "",
        render_recipe_worker_overview(
            task_rows=rows,
            current_task_id=current_task_id,
        ),
        "",
    ]
    normalized_state = _sanitize_text(validation_state) or "pending"
    if current_task_row is None:
        lines.extend(
            [
                _NO_CURRENT_TASK_ACTIVE_TEXT,
                "Every assigned recipe task that the repo accepted has already been validated.",
            ]
        )
        return "\n".join(lines)
    display_draft_path = _sanitize_text(current_draft_path) or current_paths.get("scratch_draft_path") or "[unknown]"
    if normalized_state == "ok":
        lines.extend(
            [
                _VALIDATION_STATUS_OK_TEXT,
                f"Draft path: `{display_draft_path}`",
                f"Install target: `{current_paths.get('result_path') or '[unknown]'}`",
                _INSTALL_CURRENT_READY_TEXT,
                _REOPEN_AFTER_INSTALL_TEXT,
                _CONTINUE_IMMEDIATELY_TEXT,
            ]
        )
    elif normalized_state == "failed":
        rendered_errors = [
            f"- `{str(error).strip()}`"
            for error in (validation_errors or ())
            if str(error).strip()
        ]
        lines.extend(
            [
                _VALIDATION_STATUS_FAILED_TEXT,
                f"Draft path: `{display_draft_path}`",
                "",
                "Validator errors:",
                *(rendered_errors or ["- `unknown_validation_failure`"]),
                "",
                "How to fix it:",
                "- Edit the current draft, then re-run `python3 tools/recipe_worker.py check-current`.",
                "- Open the hint path first if the brief is insufficient.",
                "- Open the input path only if the brief and hint still leave something unresolved.",
            ]
        )
    else:
        lines.extend(
            [
                _NO_REPO_WRITTEN_FEEDBACK_TEXT,
                f"Current draft path: `{display_draft_path}`",
                "Default local loop:",
                "- The repo already prewrote `scratch/` drafts and `scratch/_prepared_drafts.json`.",
                "- Start with `CURRENT_TASK.md`, `current_task.json`, and `CURRENT_TASK_FEEDBACK.md` instead of dumping `assigned_tasks.json`.",
                "- Edit only the current draft, then run `python3 tools/recipe_worker.py check-current` and `install-current`.",
                "- `prepare-all`, `finalize-all`, `OUTPUT_CONTRACT.md`, `examples/*.json`, and `tools/recipe_worker.py` are fallback/debug surfaces, not the default first move.",
            ]
        )
    if current_paths:
        lines.extend(
            [
                "",
                "Current task files:",
                f"- hint: `{current_paths['hint_path']}`",
                f"- input: `{current_paths['input_path']}`",
                f"- draft: `{current_paths['scratch_draft_path']}`",
                f"- output: `{current_paths['result_path']}`",
            ]
        )
    return "\n".join(lines)


def current_recipe_worker_draft_path(
    *,
    workspace_root: Path,
    task_row: Mapping[str, Any] | None = None,
) -> Path:
    row = task_row if task_row is not None else resolve_current_recipe_worker_task(workspace_root=workspace_root)
    return workspace_root / _task_paths(row)["scratch_draft_path"]


def _find_recipe_worker_task_row(
    *,
    task_rows: Sequence[Mapping[str, Any]],
    task_id: str | None,
) -> dict[str, Any] | None:
    normalized_task_id = _sanitize_text(task_id)
    return next(
        (dict(row) for row in task_rows if _task_id(row) and _task_id(row) == normalized_task_id),
        None,
    )


def _next_pending_recipe_worker_task(
    *,
    workspace_root: Path,
    task_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    for row in task_rows:
        result_path = workspace_root / _task_paths(row)["result_path"]
        if not result_path.exists():
            return dict(row)
    return None


def write_recipe_worker_current_task_sidecars(
    *,
    workspace_root: Path,
    task_rows: Sequence[Mapping[str, Any]],
    current_task_id: str | None = None,
    validation_state: str = "pending",
    validation_errors: Sequence[str] | None = None,
    current_draft_path: str | None = None,
) -> None:
    workspace_root = Path(workspace_root)
    rows = [dict(row) for row in task_rows if _task_id(row)]
    current_task_row = _find_recipe_worker_task_row(
        task_rows=rows,
        task_id=current_task_id,
    )
    if current_task_row is None:
        current_task_row = _next_pending_recipe_worker_task(
            workspace_root=workspace_root,
            task_rows=rows,
        )
    current_task_path = workspace_root / _CURRENT_TASK_FILE_NAME
    if current_task_row is None:
        if current_task_path.exists():
            current_task_path.unlink()
    else:
        current_task_path.write_text(
            json.dumps(current_task_row, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (workspace_root / _CURRENT_TASK_BRIEF_FILE_NAME).write_text(
        render_recipe_worker_current_task_brief(
            task_row=current_task_row,
            task_rows=rows,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace_root / _CURRENT_TASK_FEEDBACK_FILE_NAME).write_text(
        render_recipe_worker_feedback_brief(
            task_rows=rows,
            current_task_id=_task_id(current_task_row or {}),
            validation_state=validation_state,
            validation_errors=validation_errors,
            current_draft_path=current_draft_path,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace_root / _SHARD_PACKET_FILE_NAME).write_text(
        render_recipe_worker_shard_packet(
            task_rows=rows,
            current_task_id=_task_id(current_task_row or {}),
        )
        + "\n",
        encoding="utf-8",
    )


def build_recipe_worker_scaffold(*, task_row: Mapping[str, Any]) -> dict[str, Any]:
    task_id = _task_id(task_row)
    recipe_rows = _recipe_input_rows(task_row)
    owned_ids = _owned_recipe_ids(task_row)
    rows: list[dict[str, Any]] = []
    if recipe_rows:
        for recipe_row in recipe_rows:
            recipe_id = _sanitize_text(recipe_row.get("rid"))
            hint = _coerce_mapping(recipe_row.get("h"))
            title = _sanitize_text(hint.get("n")) or _placeholder("TITLE")
            ingredients = _sanitize_text_list(hint.get("i")) or [_placeholder("INGREDIENT")]
            steps = _sanitize_text_list(hint.get("s")) or [_placeholder("STEP")]
            rows.append(
                {
                    "v": "1",
                    "rid": recipe_id,
                    "st": "repaired",
                    "sr": None,
                    "cr": {
                        "t": title,
                        "i": ingredients,
                        "s": steps,
                        "d": None,
                        "y": None,
                    },
                    "m": [],
                    "mr": None,
                    "g": [],
                    "w": [],
                }
            )
    else:
        for recipe_id in owned_ids:
            rows.append(
                {
                    "v": "1",
                    "rid": recipe_id,
                    "st": "fragmentary",
                    "sr": _placeholder("STATUS_REASON"),
                    "cr": None,
                    "m": [],
                    "mr": "not_applicable_fragmentary",
                    "g": [],
                    "w": [],
                }
            )
    return {
        "v": "1",
        "sid": task_id,
        "r": rows,
    }


def _compact_key_errors(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in sorted(str(name) for name in payload.keys() if str(name) not in _TOP_LEVEL_KEYS):
        suggestion = _LEGACY_KEY_SUGGESTIONS.get(key)
        if suggestion:
            errors.append(f"root legacy key `{key}` is invalid; use `{suggestion}`")
        else:
            errors.append(f"root unexpected key `{key}` is not permitted")
    rows = payload.get("r")
    if isinstance(rows, list):
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            for key in sorted(str(name) for name in row.keys() if str(name) not in _RESULT_KEYS):
                suggestion = _LEGACY_KEY_SUGGESTIONS.get(key)
                if suggestion:
                    errors.append(
                        f"r[{row_index}] legacy key `{key}` is invalid; use `{suggestion}`"
                    )
                else:
                    errors.append(f"r[{row_index}] unexpected key `{key}` is not permitted")
            canonical_recipe = row.get("cr")
            if isinstance(canonical_recipe, Mapping):
                for key in sorted(
                    str(name) for name in canonical_recipe.keys() if str(name) not in _CANONICAL_KEYS
                ):
                    errors.append(f"r[{row_index}].cr unexpected key `{key}` is not permitted")
            mapping_rows = row.get("m")
            if isinstance(mapping_rows, list):
                for mapping_index, mapping_row in enumerate(mapping_rows):
                    if not isinstance(mapping_row, Mapping):
                        continue
                    for key in sorted(
                        str(name) for name in mapping_row.keys() if str(name) not in _MAPPING_KEYS
                    ):
                        errors.append(
                            f"r[{row_index}].m[{mapping_index}] unexpected key `{key}` is not permitted"
                        )
            tag_rows = row.get("g")
            if isinstance(tag_rows, list):
                for tag_index, tag_row in enumerate(tag_rows):
                    if not isinstance(tag_row, Mapping):
                        continue
                    for key in sorted(
                        str(name) for name in tag_row.keys() if str(name) not in _TAG_KEYS
                    ):
                        errors.append(
                            f"r[{row_index}].g[{tag_index}] unexpected key `{key}` is not permitted"
                        )
    return errors


def _find_placeholder_strings(value: Any, *, path: str = "root") -> list[str]:
    if isinstance(value, str):
        return [f"{path} contains unfinished scaffold placeholder"] if _PLACEHOLDER_MARKER in value else []
    if isinstance(value, Mapping):
        errors: list[str] = []
        for key, nested_value in value.items():
            errors.extend(_find_placeholder_strings(nested_value, path=f"{path}.{key}"))
        return errors
    if isinstance(value, list):
        errors: list[str] = []
        for index, nested_value in enumerate(value):
            errors.extend(_find_placeholder_strings(nested_value, path=f"{path}[{index}]"))
        return errors
    return []


def validate_recipe_worker_draft(
    *,
    task_row: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    payload_dict = _coerce_mapping(payload)
    task_id = _task_id(task_row)
    expected_ids = _owned_recipe_ids(task_row)
    errors.extend(_compact_key_errors(payload_dict))
    if payload_dict.get("v") != "1":
        errors.append("root `v` must equal `1`")
    if payload_dict.get("sid") != task_id:
        errors.append(f"root `sid` must equal `{task_id}` exactly")
    rows = payload_dict.get("r")
    if not isinstance(rows, list):
        errors.append("root `r` must be a list")
        return errors
    actual_ids: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"r[{index}] must be a JSON object")
            continue
        row_dict = _coerce_mapping(row)
        for key in sorted(_RESULT_KEYS - set(str(name) for name in row_dict.keys())):
            errors.append(f"r[{index}] missing required key `{key}`")
        if row_dict.get("v") != "1":
            errors.append(f"r[{index}].v must equal `1`")
        recipe_id = _sanitize_text(row_dict.get("rid"))
        if not recipe_id:
            errors.append(f"r[{index}].rid must be a non-empty string")
        actual_ids.append(recipe_id)
        status = _sanitize_text(row_dict.get("st"))
        if status not in _VALID_STATUSES:
            errors.append(f"r[{index}].st must be one of repaired, fragmentary, not_a_recipe")
        canonical_recipe = row_dict.get("cr")
        if status == "repaired":
            if not isinstance(canonical_recipe, Mapping):
                errors.append(f"r[{index}].cr must be a JSON object when st=repaired")
            else:
                canonical_dict = _coerce_mapping(canonical_recipe)
                for key in sorted(_CANONICAL_KEYS - set(str(name) for name in canonical_dict.keys())):
                    errors.append(f"r[{index}].cr missing required key `{key}`")
                title = _sanitize_text(canonical_dict.get("t"))
                if not title:
                    errors.append(f"r[{index}].cr.t must be a non-empty string")
                if not _sanitize_text_list(canonical_dict.get("i")):
                    errors.append(f"r[{index}].cr.i must contain at least one non-empty ingredient")
                if not _sanitize_text_list(canonical_dict.get("s")):
                    errors.append(f"r[{index}].cr.s must contain at least one non-empty step")
        elif canonical_recipe is not None:
            errors.append(f"r[{index}].cr must be null when st={status}")
        if status in {"fragmentary", "not_a_recipe"} and not _sanitize_text(row_dict.get("sr")):
            errors.append(f"r[{index}].sr must explain the judgment when st={status}")
        if not isinstance(row_dict.get("m"), list):
            errors.append(f"r[{index}].m must be a list")
        if not isinstance(row_dict.get("g"), list):
            errors.append(f"r[{index}].g must be a list")
        if not isinstance(row_dict.get("w"), list):
            errors.append(f"r[{index}].w must be a list")
    missing_ids = sorted(set(expected_ids) - set(actual_ids))
    unexpected_ids = sorted(set(actual_ids) - set(expected_ids))
    duplicate_ids = sorted({recipe_id for recipe_id in actual_ids if actual_ids.count(recipe_id) > 1})
    if missing_ids:
        errors.append("missing owned recipe ids: " + ", ".join(missing_ids))
    if unexpected_ids:
        errors.append("unexpected recipe ids: " + ", ".join(unexpected_ids))
    if duplicate_ids:
        errors.append("duplicate recipe ids: " + ", ".join(duplicate_ids))
    errors.extend(_find_placeholder_strings(payload_dict))
    return errors


def _workspace_relative_path(*, workspace_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root))
    except ValueError:
        return str(path)


def _status_mapping_reason(status: str) -> str:
    normalized_status = _sanitize_text(status)
    if normalized_status == "fragmentary":
        return "not_applicable_fragmentary"
    if normalized_status == "not_a_recipe":
        return "not_applicable_not_a_recipe"
    raise ValueError(f"unsupported bulk status `{status}`")


def _write_prepared_recipe_worker_manifest(
    *,
    workspace_root: Path,
    dest_dir: Path,
    written_paths: Sequence[Path],
    task_rows: Sequence[Mapping[str, Any]],
) -> Path:
    manifest_path = workspace_root / dest_dir / _PREPARED_DRAFT_MANIFEST_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    current_task = load_current_recipe_worker_task(workspace_root=workspace_root)
    manifest_path.write_text(
        json.dumps(
            {
                "draft_dir": _workspace_relative_path(
                    workspace_root=workspace_root,
                    path=workspace_root / dest_dir,
                ),
                "draft_paths": [
                    _workspace_relative_path(workspace_root=workspace_root, path=path)
                    for path in written_paths
                ],
                "current_task_id": _task_id(current_task or {}),
                "task_packets": [
                    {
                        "task_id": _task_id(task_row),
                        "draft_path": _task_paths(task_row)["scratch_draft_path"],
                        "result_path": _task_paths(task_row)["result_path"],
                        "hint_path": _task_paths(task_row)["hint_path"],
                        "input_path": _task_paths(task_row)["input_path"],
                        "owned_recipe_ids": _owned_recipe_ids(task_row),
                        "candidate_summaries": _task_candidate_packet_lines(task_row=task_row),
                    }
                    for task_row in task_rows
                    if _task_id(task_row)
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _validated_recipe_worker_draft(
    *,
    workspace_root: Path,
    draft_path: Path,
    task_rows: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(draft_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("draft payload must be a JSON object")
    normalized_payload = _coerce_mapping(payload)
    task_id = _sanitize_text(normalized_payload.get("sid"))
    rows = list(task_rows) if task_rows is not None else load_recipe_worker_task_rows(workspace_root=workspace_root)
    task_row = next((row for row in rows if _task_id(row) == task_id), None)
    if task_row is None:
        raise ValueError(f"unknown task id `{task_id}`")
    errors = validate_recipe_worker_draft(task_row=task_row, payload=normalized_payload)
    if errors:
        raise ValueError("\n".join(errors))
    return _coerce_mapping(task_row), normalized_payload


def prepare_recipe_worker_drafts(
    *,
    workspace_root: Path,
    dest_dir: Path,
    task_rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[Path]:
    if dest_dir.is_absolute():
        raise ValueError("dest_dir must stay relative to the workspace root")
    rows = list(task_rows) if task_rows is not None else load_recipe_worker_task_rows(workspace_root=workspace_root)
    written_paths: list[Path] = []
    for task_row in rows:
        task_id = _task_id(task_row)
        if not task_id:
            continue
        draft_path = workspace_root / dest_dir / f"{task_id}.json"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(
            json.dumps(build_recipe_worker_scaffold(task_row=task_row), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written_paths.append(draft_path)
    _write_prepared_recipe_worker_manifest(
        workspace_root=workspace_root,
        dest_dir=dest_dir,
        written_paths=written_paths,
        task_rows=rows,
    )
    return written_paths


def stamp_recipe_worker_drafts(
    *,
    workspace_root: Path,
    draft_paths: Sequence[Path],
    status: str,
    status_reason: str,
    warnings: Sequence[str] | None = None,
) -> list[Path]:
    normalized_status = _sanitize_text(status)
    if normalized_status not in {"fragmentary", "not_a_recipe"}:
        raise ValueError("status must be `fragmentary` or `not_a_recipe`")
    normalized_reason = _sanitize_text(status_reason)
    if not normalized_reason:
        raise ValueError("status_reason must be a non-empty string")
    normalized_warnings = _sanitize_text_list(list(warnings or ()))
    task_rows = load_recipe_worker_task_rows(workspace_root=workspace_root)
    rows_by_task_id = {_task_id(row): _coerce_mapping(row) for row in task_rows if _task_id(row)}
    errors: list[str] = []
    stamped_paths: list[Path] = []
    for draft_path in draft_paths:
        try:
            payload = json.loads(draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(
                f"{_workspace_relative_path(workspace_root=workspace_root, path=draft_path)}: {exc}"
            )
            continue
        if not isinstance(payload, Mapping):
            errors.append(
                f"{_workspace_relative_path(workspace_root=workspace_root, path=draft_path)}: draft payload must be a JSON object"
            )
            continue
        task_id = _sanitize_text(payload.get("sid")) or draft_path.stem
        task_row = rows_by_task_id.get(task_id)
        if task_row is None:
            errors.append(
                f"{_workspace_relative_path(workspace_root=workspace_root, path=draft_path)}: unknown task id `{task_id}`"
            )
            continue
        stamped_payload = {
            "v": "1",
            "sid": task_id,
            "r": [
                {
                    "v": "1",
                    "rid": recipe_id,
                    "st": normalized_status,
                    "sr": normalized_reason,
                    "cr": None,
                    "m": [],
                    "mr": _status_mapping_reason(normalized_status),
                    "g": [],
                    "w": list(normalized_warnings),
                }
                for recipe_id in _owned_recipe_ids(task_row)
            ],
        }
        draft_path.write_text(
            json.dumps(stamped_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        stamped_paths.append(draft_path)
    if errors:
        raise ValueError("\n".join(errors))
    return stamped_paths


def finalize_recipe_worker_drafts(
    *,
    workspace_root: Path,
    draft_paths: Sequence[Path],
) -> list[Path]:
    task_rows = load_recipe_worker_task_rows(workspace_root=workspace_root)
    planned_writes: list[tuple[Path, dict[str, Any]]] = []
    errors: list[str] = []
    for draft_path in draft_paths:
        try:
            task_row, payload = _validated_recipe_worker_draft(
                workspace_root=workspace_root,
                draft_path=draft_path,
                task_rows=task_rows,
            )
        except ValueError as exc:
            draft_label = _workspace_relative_path(workspace_root=workspace_root, path=draft_path)
            errors.extend(f"{draft_label}: {line}" for line in str(exc).splitlines() if line.strip())
            continue
        result_path_text = _task_paths(task_row)["result_path"]
        result_path = Path(result_path_text)
        if result_path.is_absolute():
            errors.append(
                f"{_workspace_relative_path(workspace_root=workspace_root, path=draft_path)}: "
                "result_path must stay relative to the workspace root"
            )
            continue
        planned_writes.append((workspace_root / result_path, payload))
    if errors:
        raise ValueError("\n".join(errors))
    written_paths: list[Path] = []
    for output_path, payload in planned_writes:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written_paths.append(output_path)
    return written_paths


def install_recipe_worker_draft(
    *,
    workspace_root: Path,
    draft_path: Path,
) -> Path:
    return finalize_recipe_worker_drafts(
        workspace_root=workspace_root,
        draft_paths=[draft_path],
    )[0]


def check_current_recipe_worker_draft(
    *,
    workspace_root: Path,
    draft_path: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    workspace_root = Path(workspace_root)
    task_rows = load_recipe_worker_task_rows(workspace_root=workspace_root)
    task_row = resolve_current_recipe_worker_task(workspace_root=workspace_root)
    resolved_draft_path = (
        Path(draft_path)
        if draft_path is not None
        else current_recipe_worker_draft_path(
            workspace_root=workspace_root,
            task_row=task_row,
        )
    )
    if not resolved_draft_path.is_absolute():
        resolved_draft_path = workspace_root / resolved_draft_path
    try:
        payload = json.loads(resolved_draft_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("draft payload must be a JSON object")
        validation_errors = validate_recipe_worker_draft(
            task_row=task_row,
            payload=_coerce_mapping(payload),
        )
        if validation_errors:
            raise ValueError("\n".join(validation_errors))
    except Exception as exc:  # noqa: BLE001
        write_recipe_worker_current_task_sidecars(
            workspace_root=workspace_root,
            task_rows=task_rows,
            current_task_id=_task_id(task_row),
            validation_state="failed",
            validation_errors=str(exc).splitlines(),
            current_draft_path=_workspace_relative_path(
                workspace_root=workspace_root,
                path=resolved_draft_path,
            ),
        )
        raise
    write_recipe_worker_current_task_sidecars(
        workspace_root=workspace_root,
        task_rows=task_rows,
        current_task_id=_task_id(task_row),
        validation_state="ok",
        current_draft_path=_workspace_relative_path(
            workspace_root=workspace_root,
            path=resolved_draft_path,
        ),
    )
    return dict(task_row), resolved_draft_path


def install_current_recipe_worker_draft(
    *,
    workspace_root: Path,
    draft_path: Path | None = None,
) -> tuple[Path, Path, str | None]:
    workspace_root = Path(workspace_root)
    task_row, resolved_draft_path = check_current_recipe_worker_draft(
        workspace_root=workspace_root,
        draft_path=draft_path,
    )
    output_path = install_recipe_worker_draft(
        workspace_root=workspace_root,
        draft_path=resolved_draft_path,
    )
    task_rows = load_recipe_worker_task_rows(workspace_root=workspace_root)
    next_task_row = _next_pending_recipe_worker_task(
        workspace_root=workspace_root,
        task_rows=task_rows,
    )
    write_recipe_worker_current_task_sidecars(
        workspace_root=workspace_root,
        task_rows=task_rows,
        current_task_id=_task_id(next_task_row or {}),
        validation_state="pending",
    )
    draft_paths = [
        workspace_root / _task_paths(row)["scratch_draft_path"]
        for row in task_rows
        if (workspace_root / _task_paths(row)["scratch_draft_path"]).exists()
    ]
    if draft_paths:
        _write_prepared_recipe_worker_manifest(
            workspace_root=workspace_root,
            dest_dir=Path("scratch"),
            written_paths=draft_paths,
            task_rows=task_rows,
        )
    return resolved_draft_path, output_path, _task_id(next_task_row or {})


def render_recipe_worker_cli_script() -> str:
    return dedent(
        """\
        #!/usr/bin/env python3
        from __future__ import annotations

        import argparse
        import json
        import sys
        from pathlib import Path
        from typing import Any

        TOP_LEVEL_KEYS = frozenset({"v", "sid", "r"})
        RESULT_KEYS = frozenset({"v", "rid", "st", "sr", "cr", "m", "mr", "g", "w"})
        CANONICAL_KEYS = frozenset({"t", "i", "s", "d", "y"})
        MAPPING_KEYS = frozenset({"i", "s"})
        TAG_KEYS = frozenset({"c", "l", "f"})
        VALID_STATUSES = frozenset({"repaired", "fragmentary", "not_a_recipe"})
        PLACEHOLDER_MARKER = "__EDIT_ME__"
        NO_CURRENT_TASK_ACTIVE_TEXT = "No current task is active. The queue is complete."
        ACTIVE_ASSIGNMENT_TEXT = (
            "This worker assignment stays active until the repo rewrites `current_task.json` "
            "or says the queue is complete."
        )
        NO_REPO_WRITTEN_FEEDBACK_TEXT = "No repo-written validation feedback exists yet for this task."
        VALIDATION_STATUS_OK_TEXT = "Validation status: OK."
        VALIDATION_STATUS_FAILED_TEXT = "Validation status: FAILED."
        INSTALL_CURRENT_READY_TEXT = (
            "You may run `python3 tools/recipe_worker.py install-current` to write the final result path."
        )
        REOPEN_AFTER_INSTALL_TEXT = (
            "After `install-current`, re-open `CURRENT_TASK.md`, `current_task.json`, and "
            "`CURRENT_TASK_FEEDBACK.md`."
        )
        CONTINUE_IMMEDIATELY_TEXT = (
            "If another task becomes active, continue with that task immediately. Do not ask "
            "for permission to continue while later tasks remain."
        )
        LEGACY_KEY_SUGGESTIONS = {
            "bundle_version": "v",
            "shard_id": "sid",
            "results": "r",
            "recipes": "r",
            "recipe_id": "rid",
            "repair_status": "st",
            "status_reason": "sr",
            "canonical_recipe": "cr",
            "ingredient_step_mapping": "m",
            "ingredient_step_mapping_reason": "mr",
            "selected_tags": "g",
            "warnings": "w",
            "not_a_recipe": "st=not_a_recipe",
            "fragmentary": "st=fragmentary",
            "notes": "sr or w",
            "title": "cr.t",
            "ingredients": "cr.i",
            "steps": "cr.s",
            "description": "cr.d",
            "recipeYield": "cr.y",
            "recipe_yield": "cr.y",
            "category": "c",
            "label": "l",
            "confidence": "f",
        }

        def coerce_mapping(value: Any) -> dict[str, Any]:
            return dict(value) if isinstance(value, dict) else {}

        def sanitize_text(value: Any) -> str:
            return str(value or "").strip()

        def sanitize_text_list(values: Any) -> list[str]:
            if not isinstance(values, list):
                return []
            return [text for text in (sanitize_text(value) for value in values) if text]

        def task_id(task_row: dict[str, Any]) -> str:
            return sanitize_text(task_row.get("task_id"))

        def task_metadata(task_row: dict[str, Any]) -> dict[str, Any]:
            value = task_row.get("metadata")
            return dict(value) if isinstance(value, dict) else {}

        def task_paths(task_row: dict[str, Any]) -> dict[str, str]:
            row_task_id = task_id(task_row)
            metadata = task_metadata(task_row)
            return {
                "input_path": sanitize_text(metadata.get("input_path")) or f"in/{row_task_id}.json",
                "hint_path": sanitize_text(metadata.get("hint_path")) or f"hints/{row_task_id}.md",
                "result_path": sanitize_text(metadata.get("result_path")) or f"out/{row_task_id}.json",
                "scratch_draft_path": sanitize_text(metadata.get("scratch_draft_path"))
                or f"scratch/{row_task_id}.json",
            }

        def owned_recipe_ids(task_row: dict[str, Any]) -> list[str]:
            owned_ids = sanitize_text_list(task_row.get("owned_ids"))
            if owned_ids:
                return owned_ids
            input_payload = coerce_mapping(task_row.get("input_payload"))
            return sanitize_text_list(input_payload.get("ids"))

        def recipe_input_rows(task_row: dict[str, Any]) -> list[dict[str, Any]]:
            input_payload = coerce_mapping(task_row.get("input_payload"))
            rows = input_payload.get("r")
            if not isinstance(rows, list):
                return []
            return [dict(row) for row in rows if isinstance(row, dict)]

        def placeholder(label: str) -> str:
            return f"{PLACEHOLDER_MARKER}_{label}"

        def load_task_rows(workspace_root: Path) -> list[dict[str, Any]]:
            path = workspace_root / "assigned_tasks.json"
            if not path.exists():
                return []
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []
            if not isinstance(payload, list):
                return []
            return [dict(row) for row in payload if isinstance(row, dict)]

        def load_current_task(workspace_root: Path) -> dict[str, Any] | None:
            path = workspace_root / "current_task.json"
            if not path.exists():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
            return dict(payload) if isinstance(payload, dict) else None

        def task_position(task_rows: list[dict[str, Any]], current_task_id: str | None) -> tuple[int | None, int | None, str | None]:
            rows = [row for row in task_rows if task_id(row)]
            if not rows:
                return None, None, None
            current_id = sanitize_text(current_task_id)
            for index, row in enumerate(rows, start=1):
                if task_id(row) != current_id:
                    continue
                next_task_id = task_id(rows[index]) if index < len(rows) else None
                return index, len(rows), next_task_id
            return None, len(rows), task_id(rows[0])

        def render_contract_quick_reference() -> list[str]:
            return [
                "Compact contract quick reference:",
                "- Top level keys: `v`, `sid`, `r`.",
                "- Per-recipe keys: `v`, `rid`, `st`, `sr`, `cr`, `m`, `mr`, `g`, `w`.",
                "- `st=repaired`: `cr` must be a canonical recipe object.",
                "- `st=fragmentary`: set `cr` to null and use `mr=not_applicable_fragmentary`.",
                "- `st=not_a_recipe`: set `cr` to null and use `mr=not_applicable_not_a_recipe`.",
                "- Tiny examples: repaired -> `{\\\"st\\\":\\\"repaired\\\",\\\"cr\\\":{...},\\\"m\\\":[],\\\"mr\\\":\\\"not_needed_single_step\\\"}`; fragmentary -> `{\\\"st\\\":\\\"fragmentary\\\",\\\"cr\\\":null,\\\"mr\\\":\\\"not_applicable_fragmentary\\\"}`; not_a_recipe -> `{\\\"st\\\":\\\"not_a_recipe\\\",\\\"cr\\\":null,\\\"mr\\\":\\\"not_applicable_not_a_recipe\\\"}`.",
                "- Legacy keys are invalid here: `results`, `recipes`, `recipe_id`, `repair_status`, `canonical_recipe`, `notes`.",
            ]

        def find_task(task_rows: list[dict[str, Any]], task_value: str | None) -> dict[str, Any]:
            if task_value:
                for row in task_rows:
                    if task_id(row) == task_value:
                        return row
                raise ValueError(f"unknown task id `{task_value}`")
            current_task = load_current_task(Path.cwd())
            if current_task is not None:
                return current_task
            if task_rows:
                return task_rows[0]
            raise ValueError("no assigned tasks found")

        def current_task_required(workspace_root: Path) -> dict[str, Any]:
            current_task = load_current_task(workspace_root)
            if current_task is None:
                raise ValueError("no current task is active in this workspace")
            return current_task

        def current_task_draft_path(task_row: dict[str, Any]) -> Path:
            return Path(task_paths(task_row)["scratch_draft_path"])

        def next_task_row(task_rows: list[dict[str, Any]], current_task_id: str | None) -> dict[str, Any] | None:
            rows = [row for row in task_rows if task_id(row)]
            if not rows:
                return None
            current_id = sanitize_text(current_task_id)
            if not current_id:
                return rows[0]
            for index, row in enumerate(rows):
                if task_id(row) != current_id:
                    continue
                if index + 1 < len(rows):
                    return rows[index + 1]
                return None
            return rows[0]

        def next_pending_task_row(workspace_root: Path, task_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
            for row in task_rows:
                result_path = workspace_root / task_paths(row)["result_path"]
                if not result_path.exists():
                    return row
            return None

        def render_overview(task_rows: list[dict[str, Any]], current_task_id: str | None) -> str:
            lines = ["Recipe worker task overview:"]
            if not task_rows:
                lines.append("- no assigned tasks found")
                return "\\n".join(lines)
            for index, row in enumerate(task_rows, start=1):
                row_task_id = task_id(row)
                paths = task_paths(row)
                recipe_ids = ", ".join(owned_recipe_ids(row)) or "[none]"
                current_marker = " current" if row_task_id and row_task_id == sanitize_text(current_task_id) else ""
                lines.append(
                    f"- {index}. {row_task_id}{current_marker} | recipes: {recipe_ids} | "
                    f"hint: {paths['hint_path']} | input: {paths['input_path']} | output: {paths['result_path']}"
                )
            return "\\n".join(lines)

        def render_current_brief(task_row: dict[str, Any] | None, task_rows: list[dict[str, Any]]) -> str:
            if task_row is None:
                return "\\n".join(
                    [
                        "# Current Recipe Task",
                        "",
                        "No current task is active in this workspace.",
                        "Every assigned recipe task already has a repo-accepted output.",
                    ]
                )
            paths = task_paths(task_row)
            sequence, total, next_task = task_position(task_rows, task_id(task_row))
            lines = [
                "# Current Recipe Task",
                "",
                f"task_id: {task_id(task_row)}",
                f"task_kind: {sanitize_text(task_row.get('task_kind')) or '[unknown]'}",
                f"parent_shard_id: {sanitize_text(task_row.get('parent_shard_id')) or '[unknown]'}",
                f"owned_recipe_ids: {', '.join(owned_recipe_ids(task_row)) or '[none]'}",
                f"hint_path: {paths['hint_path']}",
                f"input_path: {paths['input_path']}",
                f"scratch_draft_path: {paths['scratch_draft_path']}",
                f"result_path: {paths['result_path']}",
                (
                    f"queue_position: {sequence}/{total}"
                    if sequence is not None and total is not None
                    else "queue_position: unknown"
                ),
                f"next_task_id: {next_task or '[none]'}",
            ]
            recipe_rows = recipe_input_rows(task_row)
            if recipe_rows:
                lines.append("recipe candidates:")
                for row in recipe_rows:
                    hint = coerce_mapping(row.get("h"))
                    lines.append(
                        f"- {sanitize_text(row.get('rid')) or '[unknown]'}: "
                        f"title={sanitize_text(hint.get('n')) or '[no title hint]'} "
                        f"ingredients={len(sanitize_text_list(hint.get('i')))} "
                        f"steps={len(sanitize_text_list(hint.get('s')))}"
                    )
            lines.extend(
                [
                    "",
                    ACTIVE_ASSIGNMENT_TEXT,
                    "",
                    "Recommended loop:",
                    f"- Edit the prewritten draft at `{paths['scratch_draft_path']}` first.",
                    f"- Open `{paths['hint_path']}` only if the brief or draft is still unclear.",
                    f"- Open `{paths['input_path']}` only if the draft and hint still leave something unresolved.",
                    "- Run `python3 tools/recipe_worker.py check-current` after editing the current draft.",
                    "- Run `python3 tools/recipe_worker.py install-current` only after `check-current` says OK.",
                    f"- For obvious terminal cases, use `python3 tools/recipe_worker.py stamp-status fragmentary \\\"<reason>\\\" {paths['scratch_draft_path']}` or the same command with `not_a_recipe`.",
                    "- After `install-current`, re-open the current-task sidecars and keep going if another task is active.",
                    "",
                    *render_contract_quick_reference(),
                    "",
                    "Fallback only:",
                    "- `OUTPUT_CONTRACT.md`, `examples/*.json`, and `tools/recipe_worker.py` are fallback/debug references, not the normal first read.",
                    "- `prepare-all --dest-dir scratch/` and `finalize-all scratch/` stay available for recovery or bulk cleanup, not as the default queue loop.",
                ]
            )
            return "\\n".join(lines)

        def render_feedback(
            task_rows: list[dict[str, Any]],
            current_task_id: str | None,
            *,
            validation_state: str = "pending",
            validation_errors: list[str] | None = None,
            current_draft_path: str | None = None,
        ) -> str:
            current_task = next(
                (
                    row
                    for row in task_rows
                    if task_id(row) and task_id(row) == sanitize_text(current_task_id)
                ),
                None,
            )
            lines = [
                "# Recipe Worker Queue",
                "",
                render_overview(task_rows, current_task_id),
                "",
            ]
            if current_task is None:
                lines.extend(
                    [
                        NO_CURRENT_TASK_ACTIVE_TEXT,
                        "Every assigned recipe task that the repo accepted has already been validated.",
                    ]
                )
                return "\\n".join(lines)
            paths = task_paths(current_task)
            display_draft_path = sanitize_text(current_draft_path) or paths["scratch_draft_path"]
            normalized_state = sanitize_text(validation_state) or "pending"
            if normalized_state == "ok":
                lines.extend(
                    [
                        VALIDATION_STATUS_OK_TEXT,
                        f"Draft path: `{display_draft_path}`",
                        f"Install target: `{paths['result_path']}`",
                        INSTALL_CURRENT_READY_TEXT,
                        REOPEN_AFTER_INSTALL_TEXT,
                        CONTINUE_IMMEDIATELY_TEXT,
                    ]
                )
            elif normalized_state == "failed":
                rendered_errors = [
                    f"- `{sanitize_text(error)}`"
                    for error in (validation_errors or [])
                    if sanitize_text(error)
                ]
                lines.extend(
                    [
                        VALIDATION_STATUS_FAILED_TEXT,
                        f"Draft path: `{display_draft_path}`",
                        "",
                        "Validator errors:",
                        *(rendered_errors or ["- `unknown_validation_failure`"]),
                        "",
                        "How to fix it:",
                        "- Edit the current draft, then re-run `python3 tools/recipe_worker.py check-current`.",
                        "- Open the hint path first if the brief is insufficient.",
                        "- Open the input path only if the brief and hint still leave something unresolved.",
                    ]
                )
            else:
                lines.extend(
                    [
                        NO_REPO_WRITTEN_FEEDBACK_TEXT,
                        f"Current draft path: `{display_draft_path}`",
                        "Default local loop:",
                        "- The repo already prewrote `scratch/` drafts and `scratch/_prepared_drafts.json`.",
                        "- Start with `CURRENT_TASK.md`, `current_task.json`, and `CURRENT_TASK_FEEDBACK.md` instead of dumping `assigned_tasks.json`.",
                        "- Edit only the current draft, then run `python3 tools/recipe_worker.py check-current` and `install-current`.",
                        "- `prepare-all`, `finalize-all`, `OUTPUT_CONTRACT.md`, `examples/*.json`, and `tools/recipe_worker.py` are fallback/debug surfaces, not the default first move.",
                    ]
                )
            lines.extend(
                [
                    "",
                    "Current task files:",
                    f"- hint: `{paths['hint_path']}`",
                    f"- input: `{paths['input_path']}`",
                    f"- draft: `{paths['scratch_draft_path']}`",
                    f"- output: `{paths['result_path']}`",
                ]
            )
            return "\\n".join(lines)

        def render_show(task_row: dict[str, Any]) -> str:
            lines = [
                f"task_id: {task_id(task_row)}",
                f"task_kind: {sanitize_text(task_row.get('task_kind')) or '[unknown]'}",
                f"parent_shard_id: {sanitize_text(task_row.get('parent_shard_id')) or '[unknown]'}",
                f"owned_recipe_ids: {', '.join(owned_recipe_ids(task_row)) or '[none]'}",
            ]
            paths = task_paths(task_row)
            lines.extend(
                [
                    f"hint_path: {paths['hint_path']}",
                    f"input_path: {paths['input_path']}",
                    f"scratch_draft_path: {paths['scratch_draft_path']}",
                    f"result_path: {paths['result_path']}",
                ]
            )
            for row in recipe_input_rows(task_row):
                hint = coerce_mapping(row.get("h"))
                lines.append(
                    f"- {sanitize_text(row.get('rid')) or '[unknown]'}: "
                    f"title={sanitize_text(hint.get('n')) or '[no title hint]'} "
                    f"ingredients={len(sanitize_text_list(hint.get('i')))} "
                    f"steps={len(sanitize_text_list(hint.get('s')))}"
                )
            return "\\n".join(lines)

        def build_scaffold(task_row: dict[str, Any]) -> dict[str, Any]:
            rows = []
            recipe_rows = recipe_input_rows(task_row)
            owned_ids = owned_recipe_ids(task_row)
            if recipe_rows:
                for recipe_row in recipe_rows:
                    hint = coerce_mapping(recipe_row.get("h"))
                    rows.append(
                        {
                            "v": "1",
                            "rid": sanitize_text(recipe_row.get("rid")),
                            "st": "repaired",
                            "sr": None,
                            "cr": {
                                "t": sanitize_text(hint.get("n")) or placeholder("TITLE"),
                                "i": sanitize_text_list(hint.get("i")) or [placeholder("INGREDIENT")],
                                "s": sanitize_text_list(hint.get("s")) or [placeholder("STEP")],
                                "d": None,
                                "y": None,
                            },
                            "m": [],
                            "mr": None,
                            "g": [],
                            "w": [],
                        }
                    )
            else:
                for recipe_id_value in owned_ids:
                    rows.append(
                        {
                            "v": "1",
                            "rid": recipe_id_value,
                            "st": "fragmentary",
                            "sr": placeholder("STATUS_REASON"),
                            "cr": None,
                            "m": [],
                            "mr": "not_applicable_fragmentary",
                            "g": [],
                            "w": [],
                        }
                    )
            return {"v": "1", "sid": task_id(task_row), "r": rows}

        def compact_key_errors(payload: dict[str, Any]) -> list[str]:
            errors: list[str] = []
            for key in sorted(str(name) for name in payload.keys() if str(name) not in TOP_LEVEL_KEYS):
                suggestion = LEGACY_KEY_SUGGESTIONS.get(key)
                errors.append(
                    f"root legacy key `{key}` is invalid; use `{suggestion}`"
                    if suggestion
                    else f"root unexpected key `{key}` is not permitted"
                )
            rows = payload.get("r")
            if isinstance(rows, list):
                for row_index, row in enumerate(rows):
                    if not isinstance(row, dict):
                        continue
                    for key in sorted(str(name) for name in row.keys() if str(name) not in RESULT_KEYS):
                        suggestion = LEGACY_KEY_SUGGESTIONS.get(key)
                        errors.append(
                            f"r[{row_index}] legacy key `{key}` is invalid; use `{suggestion}`"
                            if suggestion
                            else f"r[{row_index}] unexpected key `{key}` is not permitted"
                        )
                    canonical_recipe = row.get("cr")
                    if isinstance(canonical_recipe, dict):
                        for key in sorted(str(name) for name in canonical_recipe.keys() if str(name) not in CANONICAL_KEYS):
                            errors.append(f"r[{row_index}].cr unexpected key `{key}` is not permitted")
                    mapping_rows = row.get("m")
                    if isinstance(mapping_rows, list):
                        for mapping_index, mapping_row in enumerate(mapping_rows):
                            if not isinstance(mapping_row, dict):
                                continue
                            for key in sorted(str(name) for name in mapping_row.keys() if str(name) not in MAPPING_KEYS):
                                errors.append(f"r[{row_index}].m[{mapping_index}] unexpected key `{key}` is not permitted")
                    tag_rows = row.get("g")
                    if isinstance(tag_rows, list):
                        for tag_index, tag_row in enumerate(tag_rows):
                            if not isinstance(tag_row, dict):
                                continue
                            for key in sorted(str(name) for name in tag_row.keys() if str(name) not in TAG_KEYS):
                                errors.append(f"r[{row_index}].g[{tag_index}] unexpected key `{key}` is not permitted")
            return errors

        def placeholder_errors(value: Any, path: str = "root") -> list[str]:
            if isinstance(value, str):
                return [f"{path} contains unfinished scaffold placeholder"] if PLACEHOLDER_MARKER in value else []
            if isinstance(value, dict):
                errors: list[str] = []
                for key, nested_value in value.items():
                    errors.extend(placeholder_errors(nested_value, f"{path}.{key}"))
                return errors
            if isinstance(value, list):
                errors: list[str] = []
                for index, nested_value in enumerate(value):
                    errors.extend(placeholder_errors(nested_value, f"{path}[{index}]"))
                return errors
            return []

        def validate_draft(task_row: dict[str, Any], payload: dict[str, Any]) -> list[str]:
            errors: list[str] = []
            expected_ids = owned_recipe_ids(task_row)
            errors.extend(compact_key_errors(payload))
            if payload.get("v") != "1":
                errors.append("root `v` must equal `1`")
            if payload.get("sid") != task_id(task_row):
                errors.append(f"root `sid` must equal `{task_id(task_row)}` exactly")
            rows = payload.get("r")
            if not isinstance(rows, list):
                errors.append("root `r` must be a list")
                return errors
            actual_ids: list[str] = []
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    errors.append(f"r[{index}] must be a JSON object")
                    continue
                for key in sorted(RESULT_KEYS - set(str(name) for name in row.keys())):
                    errors.append(f"r[{index}] missing required key `{key}`")
                if row.get("v") != "1":
                    errors.append(f"r[{index}].v must equal `1`")
                recipe_id_value = sanitize_text(row.get("rid"))
                if not recipe_id_value:
                    errors.append(f"r[{index}].rid must be a non-empty string")
                actual_ids.append(recipe_id_value)
                status = sanitize_text(row.get("st"))
                if status not in VALID_STATUSES:
                    errors.append(f"r[{index}].st must be one of repaired, fragmentary, not_a_recipe")
                canonical_recipe = row.get("cr")
                if status == "repaired":
                    if not isinstance(canonical_recipe, dict):
                        errors.append(f"r[{index}].cr must be a JSON object when st=repaired")
                    else:
                        for key in sorted(CANONICAL_KEYS - set(str(name) for name in canonical_recipe.keys())):
                            errors.append(f"r[{index}].cr missing required key `{key}`")
                        if not sanitize_text(canonical_recipe.get("t")):
                            errors.append(f"r[{index}].cr.t must be a non-empty string")
                        if not sanitize_text_list(canonical_recipe.get("i")):
                            errors.append(f"r[{index}].cr.i must contain at least one non-empty ingredient")
                        if not sanitize_text_list(canonical_recipe.get("s")):
                            errors.append(f"r[{index}].cr.s must contain at least one non-empty step")
                elif canonical_recipe is not None:
                    errors.append(f"r[{index}].cr must be null when st={status}")
                if status in {"fragmentary", "not_a_recipe"} and not sanitize_text(row.get("sr")):
                    errors.append(f"r[{index}].sr must explain the judgment when st={status}")
                if not isinstance(row.get("m"), list):
                    errors.append(f"r[{index}].m must be a list")
                if not isinstance(row.get("g"), list):
                    errors.append(f"r[{index}].g must be a list")
                if not isinstance(row.get("w"), list):
                    errors.append(f"r[{index}].w must be a list")
            missing_ids = sorted(set(expected_ids) - set(actual_ids))
            unexpected_ids = sorted(set(actual_ids) - set(expected_ids))
            duplicate_ids = sorted({recipe_id_value for recipe_id_value in actual_ids if actual_ids.count(recipe_id_value) > 1})
            if missing_ids:
                errors.append("missing owned recipe ids: " + ", ".join(missing_ids))
            if unexpected_ids:
                errors.append("unexpected recipe ids: " + ", ".join(unexpected_ids))
            if duplicate_ids:
                errors.append("duplicate recipe ids: " + ", ".join(duplicate_ids))
            errors.extend(placeholder_errors(payload))
            return errors

        def install_draft(workspace_root: Path, draft_path: Path) -> Path:
            return install_drafts(workspace_root, [draft_path])[0]

        def workspace_relative_path(workspace_root: Path, path: Path) -> str:
            try:
                return str(path.relative_to(workspace_root))
            except ValueError:
                return str(path)

        def status_mapping_reason(status: str) -> str:
            normalized_status = sanitize_text(status)
            if normalized_status == "fragmentary":
                return "not_applicable_fragmentary"
            if normalized_status == "not_a_recipe":
                return "not_applicable_not_a_recipe"
            raise ValueError(f"unsupported bulk status `{status}`")

        def write_prepared_manifest(workspace_root: Path, dest_dir: Path, written_paths: list[Path]) -> Path:
            manifest_path = workspace_root / dest_dir / "_prepared_drafts.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            current_task = load_current_task(workspace_root)
            manifest_path.write_text(
                json.dumps(
                    {
                        "draft_dir": workspace_relative_path(workspace_root, workspace_root / dest_dir),
                        "draft_paths": [workspace_relative_path(workspace_root, path) for path in written_paths],
                        "current_task_id": task_id(current_task or {}),
                        "task_packets": [
                            {
                                "task_id": task_id(row),
                                "draft_path": task_paths(row)["scratch_draft_path"],
                                "result_path": task_paths(row)["result_path"],
                                "hint_path": task_paths(row)["hint_path"],
                                "input_path": task_paths(row)["input_path"],
                                "owned_recipe_ids": owned_recipe_ids(row),
                            }
                            for row in load_task_rows(workspace_root)
                            if task_id(row)
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                ) + "\\n",
                encoding="utf-8",
            )
            return manifest_path

        def prepare_drafts(workspace_root: Path, dest_dir: Path, task_rows: list[dict[str, Any]] | None = None) -> list[Path]:
            if dest_dir.is_absolute():
                raise ValueError("dest_dir must stay relative to the workspace root")
            rows = list(task_rows) if task_rows is not None else load_task_rows(workspace_root)
            written_paths = []
            for row in rows:
                row_task_id = task_id(row)
                if not row_task_id:
                    continue
                draft_path = workspace_root / dest_dir / f"{row_task_id}.json"
                draft_path.parent.mkdir(parents=True, exist_ok=True)
                draft_path.write_text(
                    json.dumps(build_scaffold(row), indent=2, sort_keys=True) + "\\n",
                    encoding="utf-8",
                )
                written_paths.append(draft_path)
            write_prepared_manifest(workspace_root, dest_dir, written_paths)
            return written_paths

        def stamp_drafts(
            workspace_root: Path,
            draft_paths: list[Path],
            *,
            status: str,
            status_reason: str,
            warnings: list[str] | None = None,
        ) -> list[Path]:
            normalized_status = sanitize_text(status)
            if normalized_status not in {"fragmentary", "not_a_recipe"}:
                raise ValueError("status must be `fragmentary` or `not_a_recipe`")
            normalized_reason = sanitize_text(status_reason)
            if not normalized_reason:
                raise ValueError("status_reason must be a non-empty string")
            normalized_warnings = sanitize_text_list(list(warnings or []))
            task_rows = load_task_rows(workspace_root)
            rows_by_task_id = {task_id(row): row for row in task_rows if task_id(row)}
            errors = []
            stamped_paths = []
            for draft_path in draft_paths:
                try:
                    payload = json.loads(draft_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"{workspace_relative_path(workspace_root, draft_path)}: {exc}")
                    continue
                if not isinstance(payload, dict):
                    errors.append(
                        f"{workspace_relative_path(workspace_root, draft_path)}: draft payload must be a JSON object"
                    )
                    continue
                row_task_id = sanitize_text(payload.get("sid")) or draft_path.stem
                row = rows_by_task_id.get(row_task_id)
                if row is None:
                    errors.append(
                        f"{workspace_relative_path(workspace_root, draft_path)}: unknown task id `{row_task_id}`"
                    )
                    continue
                stamped_payload = {
                    "v": "1",
                    "sid": row_task_id,
                    "r": [
                        {
                            "v": "1",
                            "rid": recipe_id_value,
                            "st": normalized_status,
                            "sr": normalized_reason,
                            "cr": None,
                            "m": [],
                            "mr": status_mapping_reason(normalized_status),
                            "g": [],
                            "w": list(normalized_warnings),
                        }
                        for recipe_id_value in owned_recipe_ids(row)
                    ],
                }
                draft_path.write_text(
                    json.dumps(stamped_payload, indent=2, sort_keys=True) + "\\n",
                    encoding="utf-8",
                )
                stamped_paths.append(draft_path)
            if errors:
                raise ValueError("\\n".join(errors))
            return stamped_paths

        def install_drafts(workspace_root: Path, draft_paths: list[Path]) -> list[Path]:
            task_rows = load_task_rows(workspace_root)
            planned_writes = []
            errors = []
            for draft_path in draft_paths:
                payload = json.loads(draft_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    errors.append(
                        f"{workspace_relative_path(workspace_root, draft_path)}: draft payload must be a JSON object"
                    )
                    continue
                row = next(
                    (task_row for task_row in task_rows if task_id(task_row) == sanitize_text(payload.get("sid"))),
                    None,
                )
                if row is None:
                    errors.append(
                        f"{workspace_relative_path(workspace_root, draft_path)}: unknown task id `{sanitize_text(payload.get('sid'))}`"
                    )
                    continue
                draft_errors = validate_draft(row, payload)
                if draft_errors:
                    errors.extend(
                        f"{workspace_relative_path(workspace_root, draft_path)}: {error}"
                        for error in draft_errors
                    )
                    continue
                output_rel = Path(task_paths(row)["result_path"])
                if output_rel.is_absolute():
                    errors.append(
                        f"{workspace_relative_path(workspace_root, draft_path)}: result_path must stay relative to the workspace root"
                    )
                    continue
                planned_writes.append((workspace_root / output_rel, payload))
            if errors:
                raise ValueError("\\n".join(errors))
            written_paths = []
            for output_path, payload in planned_writes:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\\n",
                    encoding="utf-8",
                )
                written_paths.append(output_path)
            return written_paths

        def write_current_task_sidecars(
            workspace_root: Path,
            task_rows: list[dict[str, Any]],
            current_task_id: str | None,
            *,
            validation_state: str = "pending",
            validation_errors: list[str] | None = None,
            current_draft_path: str | None = None,
        ) -> dict[str, Any] | None:
            current_task = next(
                (
                    row
                    for row in task_rows
                    if task_id(row) and task_id(row) == sanitize_text(current_task_id)
                ),
                None,
            )
            if current_task is None:
                current_task = next_pending_task_row(workspace_root, task_rows)
            current_task_path = workspace_root / "current_task.json"
            if current_task is None:
                if current_task_path.exists():
                    current_task_path.unlink()
            else:
                current_task_path.write_text(
                    json.dumps(current_task, indent=2, sort_keys=True) + "\\n",
                    encoding="utf-8",
                )
            (workspace_root / "CURRENT_TASK.md").write_text(
                render_current_brief(current_task, task_rows) + "\\n",
                encoding="utf-8",
            )
            (workspace_root / "CURRENT_TASK_FEEDBACK.md").write_text(
                render_feedback(
                    task_rows,
                    task_id(current_task or {}),
                    validation_state=validation_state,
                    validation_errors=validation_errors,
                    current_draft_path=current_draft_path,
                )
                + "\\n",
                encoding="utf-8",
            )
            return current_task

        def checked_current_result(
            workspace_root: Path,
            json_path: str | None,
        ) -> tuple[Path, dict[str, Any], dict[str, Any], list[str]]:
            row = current_task_required(workspace_root)
            draft_path = Path(json_path) if json_path else current_task_draft_path(row)
            if not draft_path.is_absolute():
                draft_path = workspace_root / draft_path
            payload = json.loads(draft_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("draft payload must be a JSON object")
            if sanitize_text(payload.get("sid")) and sanitize_text(payload.get("sid")) != task_id(row):
                raise ValueError(
                    f"draft sid {sanitize_text(payload.get('sid'))!r} does not match current task {task_id(row)!r}"
                )
            errors = validate_draft(row, payload)
            return draft_path, row, payload, errors

        def parse_args() -> argparse.Namespace:
            parser = argparse.ArgumentParser(description="Recipe workspace helper")
            subparsers = parser.add_subparsers(dest="command", required=True)

            subparsers.add_parser("overview")
            subparsers.add_parser("current")
            subparsers.add_parser("next")
            show_parser = subparsers.add_parser("show")
            show_parser.add_argument("task_id", nargs="?")

            scaffold_parser = subparsers.add_parser("scaffold")
            scaffold_parser.add_argument("task_id", nargs="?")
            scaffold_parser.add_argument("--dest")

            prepare_parser = subparsers.add_parser("prepare")
            prepare_parser.add_argument("task_id", nargs="?")
            prepare_parser.add_argument("--dest")

            prepare_all_parser = subparsers.add_parser("prepare-all")
            prepare_all_parser.add_argument("--dest-dir", default="scratch")

            stamp_parser = subparsers.add_parser("stamp-status")
            stamp_parser.add_argument("status", choices=["fragmentary", "not_a_recipe"])
            stamp_parser.add_argument("reason")
            stamp_parser.add_argument("draft_paths", nargs="+")

            check_parser = subparsers.add_parser("check")
            check_parser.add_argument("json_path")
            check_parser.add_argument("--verbose", action="store_true")

            check_current_parser = subparsers.add_parser("check-current")
            check_current_parser.add_argument("json_path", nargs="?")

            install_parser = subparsers.add_parser("install")
            install_parser.add_argument("json_path")

            install_current_parser = subparsers.add_parser("install-current")
            install_current_parser.add_argument("json_path", nargs="?")

            finalize_parser = subparsers.add_parser("finalize")
            finalize_parser.add_argument("json_path")

            finalize_all_parser = subparsers.add_parser("finalize-all")
            finalize_all_parser.add_argument("draft_dir")

            return parser.parse_args()

        def main() -> int:
            args = parse_args()
            workspace_root = Path.cwd()
            task_rows = load_task_rows(workspace_root)
            current_task = load_current_task(workspace_root)
            current_task_id = task_id(current_task) if current_task else None
            try:
                if args.command == "overview":
                    print(render_overview(task_rows, current_task_id))
                    return 0
                if args.command == "current":
                    current_path = workspace_root / "CURRENT_TASK.md"
                    if current_path.exists():
                        sys.stdout.write(current_path.read_text(encoding="utf-8"))
                    else:
                        sys.stdout.write(render_current_brief(current_task, task_rows) + "\\n")
                    return 0
                if args.command == "next":
                    row = next_task_row(task_rows, current_task_id)
                    if row is None:
                        print("No later task is queued after the current task.")
                    else:
                        print(task_id(row))
                    return 0
                if args.command == "show":
                    print(render_show(find_task(task_rows, args.task_id)))
                    return 0
                if args.command == "scaffold":
                    payload = build_scaffold(find_task(task_rows, args.task_id))
                    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\\n"
                    if args.dest:
                        destination = Path(args.dest)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_text(rendered, encoding="utf-8")
                        print(destination)
                    else:
                        sys.stdout.write(rendered)
                    return 0
                if args.command == "prepare":
                    payload = build_scaffold(find_task(task_rows, args.task_id))
                    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\\n"
                    if args.dest:
                        destination = Path(args.dest)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_text(rendered, encoding="utf-8")
                        print(destination)
                    else:
                        sys.stdout.write(rendered)
                    return 0
                if args.command == "prepare-all":
                    written_paths = prepare_drafts(
                        workspace_root,
                        Path(args.dest_dir),
                        task_rows=task_rows,
                    )
                    task_word = "draft" if len(written_paths) == 1 else "drafts"
                    manifest_path = workspace_root / Path(args.dest_dir) / "_prepared_drafts.json"
                    print(
                        f"prepared {len(written_paths)} {task_word} under "
                        f"{workspace_relative_path(workspace_root, (workspace_root / Path(args.dest_dir)).resolve())} "
                        f"(manifest {workspace_relative_path(workspace_root, manifest_path)})"
                    )
                    return 0
                if args.command == "stamp-status":
                    stamped_paths = stamp_drafts(
                        workspace_root,
                        [Path(value) for value in args.draft_paths],
                        status=args.status,
                        status_reason=args.reason,
                    )
                    draft_word = "draft" if len(stamped_paths) == 1 else "drafts"
                    print(f"updated {len(stamped_paths)} {draft_word} to {args.status}")
                    return 0
                if args.command == "check":
                    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("draft payload must be a JSON object")
                    row = find_task(task_rows, sanitize_text(payload.get("sid")))
                    errors = validate_draft(row, payload)
                    if errors:
                        raise ValueError("\\n".join(errors))
                    if args.verbose:
                        print(
                            json.dumps(
                                {
                                    "status": "ok",
                                    "task_id": task_id(row),
                                    "result_path": task_paths(row)["result_path"],
                                },
                                indent=2,
                                sort_keys=True,
                            )
                        )
                    else:
                        print(f"OK {task_id(row)}")
                    return 0
                if args.command == "check-current":
                    draft_path, row, _payload, errors = checked_current_result(
                        workspace_root,
                        args.json_path,
                    )
                    display_path = (
                        draft_path.relative_to(workspace_root)
                        if draft_path.is_relative_to(workspace_root)
                        else draft_path
                    )
                    if errors:
                        write_current_task_sidecars(
                            workspace_root,
                            task_rows,
                            task_id(row),
                            validation_state="failed",
                            validation_errors=errors,
                            current_draft_path=str(display_path),
                        )
                        raise ValueError("\\n".join(errors))
                    write_current_task_sidecars(
                        workspace_root,
                        task_rows,
                        task_id(row),
                        validation_state="ok",
                        current_draft_path=str(display_path),
                    )
                    print(f"OK {task_id(row)}")
                    return 0
                if args.command == "install":
                    output_path = install_draft(workspace_root, Path(args.json_path))
                    print(workspace_relative_path(workspace_root, output_path))
                    return 0
                if args.command == "install-current":
                    draft_path, row, _payload, errors = checked_current_result(
                        workspace_root,
                        args.json_path,
                    )
                    display_path = (
                        draft_path.relative_to(workspace_root)
                        if draft_path.is_relative_to(workspace_root)
                        else draft_path
                    )
                    if errors:
                        write_current_task_sidecars(
                            workspace_root,
                            task_rows,
                            task_id(row),
                            validation_state="failed",
                            validation_errors=errors,
                            current_draft_path=str(display_path),
                        )
                        raise ValueError("\\n".join(errors))
                    output_path = install_draft(workspace_root, draft_path)
                    next_row = write_current_task_sidecars(
                        workspace_root,
                        task_rows,
                        None,
                        validation_state="pending",
                    )
                    prepared_paths = [
                        workspace_root / task_paths(task_row)["scratch_draft_path"]
                        for task_row in task_rows
                        if (workspace_root / task_paths(task_row)["scratch_draft_path"]).exists()
                    ]
                    if prepared_paths:
                        write_prepared_manifest(workspace_root, Path("scratch"), prepared_paths)
                    print(
                        f"installed {workspace_relative_path(workspace_root, draft_path)} -> "
                        f"{workspace_relative_path(workspace_root, output_path)}"
                    )
                    if next_row is None:
                        print("Queue complete. No current task is active.")
                    else:
                        print(REOPEN_AFTER_INSTALL_TEXT)
                        print(CONTINUE_IMMEDIATELY_TEXT)
                    return 0
                if args.command == "finalize":
                    output_path = install_draft(workspace_root, Path(args.json_path))
                    print(workspace_relative_path(workspace_root, output_path))
                    return 0
                if args.command == "finalize-all":
                    draft_dir = Path(args.draft_dir)
                    if draft_dir.is_absolute():
                        raise ValueError("draft_dir must stay relative to the workspace root")
                    draft_paths = [
                        workspace_root / draft_dir / f"{task_id(row)}.json"
                        for row in task_rows
                        if task_id(row)
                    ]
                    written_paths = install_drafts(workspace_root, draft_paths)
                    task_word = "task output" if len(written_paths) == 1 else "task outputs"
                    print(
                        f"installed {len(written_paths)} {task_word} from "
                        f"{workspace_relative_path(workspace_root, (workspace_root / draft_dir).resolve())}"
                    )
                    return 0
            except Exception as exc:  # noqa: BLE001
                print(str(exc), file=sys.stderr)
                return 1
            return 1

        if __name__ == "__main__":
            raise SystemExit(main())
        """
    )
