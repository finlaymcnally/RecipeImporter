from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

_TOP_LEVEL_KEYS = frozenset({"v", "sid", "r"})
_RESULT_KEYS = frozenset({"v", "rid", "st", "sr", "cr", "m", "mr", "db", "g", "w"})
_CANONICAL_KEYS = frozenset({"t", "i", "s", "d", "y"})
_MAPPING_KEYS = frozenset({"i", "s"})
_TAG_KEYS = frozenset({"c", "l", "f"})
_VALID_STATUSES = frozenset({"repaired", "fragmentary", "not_a_recipe"})
_PLACEHOLDER_MARKER = "__EDIT_ME__"
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
    "divested_block_indices": "db",
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


def _default_empty_mapping_reason(*, ingredients: Sequence[str], steps: Sequence[str]) -> str:
    if len(ingredients) <= 1 and len(steps) <= 1:
        return "not_needed_single_step"
    return "unclear_alignment"


def _scaffold_status_reason(*, task_row: Mapping[str, Any], recipe_id: str) -> str:
    if _recipe_input_rows(task_row):
        return "insufficient_source_detail"
    if recipe_id:
        return "missing_candidate_packet"
    return "missing_recipe_id"


def _build_recipe_worker_scaffold_row(
    *,
    task_row: Mapping[str, Any],
    recipe_id: str,
    recipe_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    hint = _coerce_mapping((recipe_row or {}).get("h"))
    title = _sanitize_text(hint.get("n"))
    ingredients = _sanitize_text_list(hint.get("i"))
    steps = _sanitize_text_list(hint.get("s"))
    if title and ingredients and steps:
        return {
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
            "mr": _default_empty_mapping_reason(
                ingredients=ingredients,
                steps=steps,
            ),
            "db": [],
            "g": [],
            "w": [],
        }
    return {
        "v": "1",
        "rid": recipe_id,
        "st": "fragmentary",
        "sr": _scaffold_status_reason(task_row=task_row, recipe_id=recipe_id),
        "cr": None,
        "m": [],
        "mr": "not_applicable_fragmentary",
        "db": [],
        "g": [],
        "w": [],
    }


def build_recipe_worker_scaffold(*, task_row: Mapping[str, Any]) -> dict[str, Any]:
    task_id = _task_id(task_row)
    recipe_rows = _recipe_input_rows(task_row)
    owned_ids = _owned_recipe_ids(task_row)
    recipe_rows_by_id = {
        _sanitize_text(recipe_row.get("rid")): recipe_row
        for recipe_row in recipe_rows
        if _sanitize_text(recipe_row.get("rid"))
    }
    scaffold_ids = owned_ids or [
        _sanitize_text(recipe_row.get("rid"))
        for recipe_row in recipe_rows
        if _sanitize_text(recipe_row.get("rid"))
    ]
    rows: list[dict[str, Any]] = []
    for index, recipe_id in enumerate(scaffold_ids):
        if not recipe_id:
            continue
        recipe_row = recipe_rows_by_id.get(recipe_id)
        if recipe_row is None and index < len(recipe_rows):
            recipe_row = recipe_rows[index]
        rows.append(
            _build_recipe_worker_scaffold_row(
                task_row=task_row,
                recipe_id=recipe_id,
                recipe_row=recipe_row,
            )
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
                ingredients = _sanitize_text_list(canonical_dict.get("i"))
                if not ingredients:
                    errors.append(f"r[{index}].cr.i must contain at least one non-empty ingredient")
                steps = _sanitize_text_list(canonical_dict.get("s"))
                if not steps:
                    errors.append(f"r[{index}].cr.s must contain at least one non-empty step")
                mapping_reason = _sanitize_text(row_dict.get("mr"))
                mapping_rows = row_dict.get("m")
                if (
                    isinstance(mapping_rows, list)
                    and not mapping_rows
                    and not mapping_reason
                    and (len(ingredients) >= 2 or len(steps) >= 2)
                ):
                    errors.append(
                        f"r[{index}].mr must explain an empty mapping when st=repaired "
                        "and cr has 2+ non-empty ingredients or 2+ non-empty steps"
                    )
        elif canonical_recipe is not None:
            errors.append(f"r[{index}].cr must be null when st={status}")
        if status in {"fragmentary", "not_a_recipe"} and not _sanitize_text(row_dict.get("sr")):
            errors.append(f"r[{index}].sr must explain the judgment when st={status}")
        if not isinstance(row_dict.get("m"), list):
            errors.append(f"r[{index}].m must be a list")
        if not isinstance(row_dict.get("db"), list):
            errors.append(f"r[{index}].db must be a list")
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
