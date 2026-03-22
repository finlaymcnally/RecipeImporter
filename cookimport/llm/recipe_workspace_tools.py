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
_PREPARED_DRAFT_MANIFEST_NAME = "_prepared_drafts.json"
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
    current_task_path = workspace_root / "current_task.json"
    if not current_task_path.exists():
        return None
    try:
        payload = json.loads(current_task_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return _coerce_mapping(payload) if isinstance(payload, Mapping) else None


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


def render_recipe_worker_current_task_brief(*, task_row: Mapping[str, Any]) -> str:
    paths = _task_paths(task_row)
    return "\n".join(
        [
            "# Current Recipe Task",
            "",
            render_recipe_worker_task_summary(task_row=task_row),
            "",
            "Fast path:",
            f"- Open `{paths['hint_path']}` first, then `{paths['input_path']}`.",
            f"- Edit the prewritten draft at `{paths['scratch_draft_path']}`.",
            "- Use `python3 tools/recipe_worker.py stamp-status ...` for bulk fragmentary/not_a_recipe cases.",
            f"- Finish with `python3 tools/recipe_worker.py finalize {paths['scratch_draft_path']}` or `finalize-all scratch/`.",
        ]
    )


def render_recipe_worker_feedback_brief(
    *,
    task_rows: Sequence[Mapping[str, Any]],
    current_task_id: str | None = None,
) -> str:
    current_task_row = next(
        (
            row
            for row in task_rows
            if _task_id(row) and _task_id(row) == _sanitize_text(current_task_id)
        ),
        task_rows[0] if task_rows else None,
    )
    current_paths = _task_paths(current_task_row) if current_task_row is not None else {}
    lines = [
        "# Recipe Worker Queue",
        "",
        render_recipe_worker_overview(
            task_rows=task_rows,
            current_task_id=current_task_id,
        ),
        "",
        "Default local loop:",
        "- The repo already prewrote `scratch/` drafts and `scratch/_prepared_drafts.json`.",
        "- Start with the current-task files instead of dumping `assigned_tasks.json` by hand.",
        "- `prepare-all`, `overview`, and `show <task_id>` are fallback/debug tools if the prewritten draft surface is missing or unclear.",
        "- Keep edits local to `scratch/`, then use `finalize` or `finalize-all` to write `out/`.",
    ]
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
) -> Path:
    manifest_path = workspace_root / dest_dir / _PREPARED_DRAFT_MANIFEST_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
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
            manifest_path.write_text(
                json.dumps(
                    {
                        "draft_dir": workspace_relative_path(workspace_root, workspace_root / dest_dir),
                        "draft_paths": [workspace_relative_path(workspace_root, path) for path in written_paths],
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

        def parse_args() -> argparse.Namespace:
            parser = argparse.ArgumentParser(description="Recipe workspace helper")
            subparsers = parser.add_subparsers(dest="command", required=True)

            subparsers.add_parser("overview")
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

            install_parser = subparsers.add_parser("install")
            install_parser.add_argument("json_path")

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
                if args.command == "install":
                    output_path = install_draft(workspace_root, Path(args.json_path))
                    print(workspace_relative_path(workspace_root, output_path))
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
