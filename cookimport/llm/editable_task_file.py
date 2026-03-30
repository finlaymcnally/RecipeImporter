from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .task_file_guardrails import render_task_file_text

TASK_FILE_NAME = "task.json"
TASK_FILE_SCHEMA_VERSION = "editable_task_file.v1"


def write_task_file(*, path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_task_file_text(payload), encoding="utf-8")


def load_task_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{TASK_FILE_NAME} must contain one JSON object")
    return dict(payload)


def build_task_file(
    *,
    stage_key: str,
    assignment_id: str,
    worker_id: str,
    units: Sequence[Mapping[str, Any]],
    mode: str = "initial",
    schema_version: str = TASK_FILE_SCHEMA_VERSION,
) -> dict[str, Any]:
    normalized_units = [dict(unit) for unit in units if isinstance(unit, Mapping)]
    return {
        "schema_version": str(schema_version),
        "stage_key": str(stage_key),
        "assignment_id": str(assignment_id),
        "worker_id": str(worker_id),
        "mode": str(mode),
        "editable_json_pointers": [
            f"/units/{index}/answer" for index in range(len(normalized_units))
        ],
        "units": normalized_units,
    }


def validate_edited_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
    expected_schema_version: str | None = None,
) -> tuple[dict[str, dict[str, Any]] | None, tuple[str, ...], dict[str, Any]]:
    errors: list[str] = []
    error_details: list[dict[str, str]] = []
    original = dict(original_task_file)
    edited = dict(edited_task_file)
    schema_version = (
        str(expected_schema_version).strip()
        if expected_schema_version is not None
        else TASK_FILE_SCHEMA_VERSION
    )

    if str(original.get("schema_version") or "").strip() != schema_version:
        errors.append("invalid_original_schema_version")
    if str(edited.get("schema_version") or "").strip() != schema_version:
        errors.append("invalid_edited_schema_version")

    immutable_top_level_keys = {
        str(key) for key in original.keys() if str(key) != "units"
    }
    immutable_top_level_keys.update(
        {
            "schema_version",
            "stage_key",
            "assignment_id",
            "worker_id",
            "mode",
            "editable_json_pointers",
        }
    )
    for key in sorted(immutable_top_level_keys):
        if original.get(key) != edited.get(key):
            path = f"/{key}"
            errors.append("immutable_field_changed")
            error_details.append(
                {
                    "path": path,
                    "code": "immutable_field_changed",
                    "message": f"{path} must not change",
                }
            )
    extra_top_level_keys = sorted(
        str(key) for key in edited.keys() if str(key) not in original and str(key) != "units"
    )
    for key in extra_top_level_keys:
        path = f"/{key}"
        errors.append("immutable_field_changed")
        error_details.append(
            {
                "path": path,
                "code": "immutable_field_changed",
                "message": f"{path} must not be added",
            }
        )

    original_units = original.get("units")
    edited_units = edited.get("units")
    if not isinstance(original_units, list) or not isinstance(edited_units, list):
        if not isinstance(original_units, list):
            errors.append("original_units_not_list")
        if not isinstance(edited_units, list):
            errors.append("edited_units_not_list")
        return None, tuple(dict.fromkeys(errors)), {"error_details": error_details}
    if len(original_units) != len(edited_units):
        errors.append("unit_count_changed")
        error_details.append(
            {
                "path": "/units",
                "code": "unit_count_changed",
                "message": "units length must remain unchanged",
            }
        )
        return None, tuple(dict.fromkeys(errors)), {"error_details": error_details}

    answers_by_unit_id: dict[str, dict[str, Any]] = {}
    for index, (original_unit, edited_unit) in enumerate(zip(original_units, edited_units, strict=True)):
        if not isinstance(original_unit, Mapping) or not isinstance(edited_unit, Mapping):
            errors.append("unit_not_object")
            error_details.append(
                {
                    "path": f"/units/{index}",
                    "code": "unit_not_object",
                    "message": "every unit must remain a JSON object",
                }
            )
            continue
        original_unit_dict = dict(original_unit)
        edited_unit_dict = dict(edited_unit)
        unit_path = f"/units/{index}"
        for key, original_value in original_unit_dict.items():
            if key == "answer":
                continue
            if edited_unit_dict.get(key) != original_value:
                path = f"{unit_path}/{key}"
                errors.append("immutable_field_changed")
                error_details.append(
                    {
                        "path": path,
                        "code": "immutable_field_changed",
                        "message": f"{path} must not change",
                    }
                )
        extra_keys = sorted(
            str(key) for key in edited_unit_dict.keys() if key not in original_unit_dict
        )
        for key in extra_keys:
            path = f"{unit_path}/{key}"
            errors.append("immutable_field_changed")
            error_details.append(
                {
                    "path": path,
                    "code": "immutable_field_changed",
                    "message": f"{path} must not be added",
                }
            )
        unit_id = str(original_unit_dict.get("unit_id") or "").strip() or f"unit-{index:03d}"
        answer_payload = edited_unit_dict.get("answer")
        answers_by_unit_id[unit_id] = (
            dict(answer_payload) if isinstance(answer_payload, Mapping) else {}
        )

    metadata = {
        "error_details": error_details,
        "unit_count": len(original_units),
        "changed_unit_count": sum(
            1
            for original_unit, edited_unit in zip(original_units, edited_units, strict=True)
            if isinstance(original_unit, Mapping)
            and isinstance(edited_unit, Mapping)
            and dict(original_unit).get("answer") != dict(edited_unit).get("answer")
        ),
    }
    if errors:
        return None, tuple(dict.fromkeys(errors)), metadata
    return answers_by_unit_id, (), metadata


def build_repair_task_file(
    *,
    original_task_file: Mapping[str, Any],
    failed_unit_ids: Sequence[str],
    previous_answers_by_unit_id: Mapping[str, Mapping[str, Any]],
    validation_feedback_by_unit_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    failed_unit_id_set = {
        str(unit_id).strip() for unit_id in failed_unit_ids if str(unit_id).strip()
    }
    units: list[dict[str, Any]] = []
    for unit in original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_id = str(unit_dict.get("unit_id") or "").strip()
        if unit_id not in failed_unit_id_set:
            continue
        previous_answer = previous_answers_by_unit_id.get(unit_id) or {}
        validation_feedback = validation_feedback_by_unit_id.get(unit_id) or {}
        units.append(
            {
                **unit_dict,
                "answer": dict(previous_answer),
                "previous_answer": dict(previous_answer),
                "validation_feedback": dict(validation_feedback),
            }
        )
    return build_task_file(
        stage_key=str(original_task_file.get("stage_key") or ""),
        assignment_id=str(original_task_file.get("assignment_id") or ""),
        worker_id=str(original_task_file.get("worker_id") or ""),
        mode="repair",
        units=units,
        schema_version=str(original_task_file.get("schema_version") or TASK_FILE_SCHEMA_VERSION),
    )
