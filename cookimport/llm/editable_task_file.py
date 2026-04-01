from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from .task_file_guardrails import render_task_file_text

TASK_FILE_NAME = "task.json"
TASK_FILE_SCHEMA_VERSION = "editable_task_file.v1"
SUMMARY_POINTER_SAMPLE_LIMIT = 10
SUMMARY_UNIT_ID_SAMPLE_LIMIT = 10


def _normalized_units(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(unit)
        for unit in (payload.get("units") or [])
        if isinstance(unit, Mapping)
    ]


def _unit_id_for_index(unit: Mapping[str, Any], index: int) -> str:
    return str(unit.get("unit_id") or "").strip() or f"unit-{index:03d}"


def _unit_has_answer(unit: Mapping[str, Any]) -> bool:
    return _payload_has_meaningful_content(unit.get("answer"))


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned_rows: list[str] = []
    for row in value:
        cleaned = str(row or "").strip()
        if cleaned:
            cleaned_rows.append(cleaned)
    return cleaned_rows


def _summarize_review_contract(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    review_contract = payload.get("review_contract")
    if not isinstance(review_contract, Mapping):
        return None
    decision_policy = _normalized_string_list(review_contract.get("decision_policy"))
    anti_patterns = _normalized_string_list(review_contract.get("anti_patterns"))
    worker_role = str(review_contract.get("worker_role") or "").strip() or None
    primary_question = str(review_contract.get("primary_question") or "").strip() or None
    mode = str(review_contract.get("mode") or "").strip() or None
    summary = {
        "mode": mode,
        "worker_role": worker_role,
        "primary_question": primary_question,
        "decision_policy": decision_policy[:4],
        "decision_policy_truncated": len(decision_policy) > 4,
        "anti_patterns": anti_patterns[:4],
        "anti_patterns_truncated": len(anti_patterns) > 4,
    }
    if not any(summary.values()):
        return None
    return summary


def _summarize_grouping_batch(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    grouping_batch = payload.get("grouping_batch")
    if not isinstance(grouping_batch, Mapping):
        return None
    shard_ids = _normalized_string_list(grouping_batch.get("shard_ids"))
    summary = {
        "current_batch_index": int(grouping_batch.get("current_batch_index") or 0),
        "total_batches": int(grouping_batch.get("total_batches") or 0),
        "unit_count": int(grouping_batch.get("unit_count") or 0),
        "total_grouping_unit_count": int(
            grouping_batch.get("total_grouping_unit_count") or 0
        ),
        "remaining_batches_after_this": int(
            grouping_batch.get("remaining_batches_after_this") or 0
        ),
        "estimated_evidence_chars": int(
            grouping_batch.get("estimated_evidence_chars") or 0
        ),
        "shard_ids": shard_ids[:5],
        "shard_ids_truncated": len(shard_ids) > 5,
    }
    if not any(value for key, value in summary.items() if key != "shard_ids_truncated"):
        return None
    return summary


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
    helper_commands: Mapping[str, Any] | None = None,
    workflow: Sequence[str] | None = None,
    next_action: str | None = None,
    answer_schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_units = [dict(unit) for unit in units if isinstance(unit, Mapping)]
    payload = {
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
    if isinstance(helper_commands, Mapping):
        payload["helper_commands"] = dict(helper_commands)
    if workflow is not None:
        payload["workflow"] = [
            str(step).strip() for step in workflow if str(step).strip()
        ]
    if next_action is not None:
        payload["next_action"] = str(next_action)
    if isinstance(answer_schema, Mapping):
        payload["answer_schema"] = dict(answer_schema)
    return payload


def summarize_task_file(
    *,
    payload: Mapping[str, Any],
    task_file_path: str | None = None,
) -> dict[str, Any]:
    units = _normalized_units(payload)
    unanswered_unit_ids: list[str] = []
    answered_unit_ids: list[str] = []
    for index, unit in enumerate(units):
        unit_id = _unit_id_for_index(unit, index)
        if _unit_has_answer(unit):
            answered_unit_ids.append(unit_id)
        else:
            unanswered_unit_ids.append(unit_id)
    editable_pointers = [
        str(pointer)
        for pointer in (payload.get("editable_json_pointers") or [])
        if str(pointer).strip()
    ]
    sampled_unanswered_unit_ids = unanswered_unit_ids[:SUMMARY_UNIT_ID_SAMPLE_LIMIT]
    workflow = [
        str(step).strip()
        for step in (payload.get("workflow") or [])
        if str(step).strip()
    ]
    answer_schema = payload.get("answer_schema")
    answer_schema_summary = _summarize_answer_schema(answer_schema)
    current_unit_summary = _summarize_current_unit(payload)
    return {
        "task_file": str(task_file_path or TASK_FILE_NAME),
        "schema_version": str(payload.get("schema_version") or ""),
        "stage_key": str(payload.get("stage_key") or ""),
        "assignment_id": str(payload.get("assignment_id") or ""),
        "worker_id": str(payload.get("worker_id") or ""),
        "mode": str(payload.get("mode") or ""),
        "answered_units": len(answered_unit_ids),
        "total_units": len(units),
        "unanswered_unit_count": len(unanswered_unit_ids),
        "unanswered_unit_ids": sampled_unanswered_unit_ids,
        "unanswered_unit_ids_truncated": (
            len(unanswered_unit_ids) > SUMMARY_UNIT_ID_SAMPLE_LIMIT
        ),
        "editable_pointer_count": len(editable_pointers),
        "editable_json_pointers_sample": editable_pointers[:SUMMARY_POINTER_SAMPLE_LIMIT],
        "editable_json_pointers_truncated": (
            len(editable_pointers) > SUMMARY_POINTER_SAMPLE_LIMIT
        ),
        "helper_commands": dict(payload.get("helper_commands") or {})
        if isinstance(payload.get("helper_commands"), Mapping)
        else {},
        "workflow": workflow,
        "next_action": str(payload.get("next_action") or "").strip() or None,
        "answer_schema_summary": answer_schema_summary,
        "review_contract": _summarize_review_contract(payload),
        "grouping_batch": _summarize_grouping_batch(payload),
        **current_unit_summary,
    }


def build_worker_task_brief(
    *,
    payload: Mapping[str, Any],
    task_file_path: str | None = None,
) -> dict[str, Any]:
    units = _normalized_units(payload)
    answered_units = 0
    for unit in units:
        if _unit_has_answer(unit):
            answered_units += 1
    total_units = len(units)
    remaining_units = max(total_units - answered_units, 0)
    workflow = [
        str(step).strip()
        for step in (payload.get("workflow") or [])
        if str(step).strip()
    ]
    answer_schema_summary = _summarize_answer_schema(payload.get("answer_schema"))
    current_unit_summary = _summarize_current_unit(payload)
    grouping_batch = _summarize_grouping_batch(payload)
    brief: dict[str, Any] = {
        "task_file": str(task_file_path or TASK_FILE_NAME),
        "stage_key": str(payload.get("stage_key") or ""),
        "mode": str(payload.get("mode") or ""),
        "answered_units": answered_units,
        "total_units": total_units,
        "remaining_units": remaining_units,
    }
    if workflow:
        brief["workflow"] = workflow
    next_action = str(payload.get("next_action") or "").strip()
    if next_action:
        brief["next_action"] = next_action
    if isinstance(answer_schema_summary, Mapping):
        required_keys = _normalized_string_list(answer_schema_summary.get("required_keys"))
        optional_keys = _normalized_string_list(answer_schema_summary.get("optional_keys"))
        if required_keys:
            brief["required_answer_keys"] = required_keys
        if optional_keys:
            brief["optional_answer_keys"] = optional_keys
    if current_unit_summary:
        brief.update(current_unit_summary)
    if isinstance(grouping_batch, Mapping):
        compact_grouping_batch = {
            "current_batch_index": int(grouping_batch.get("current_batch_index") or 0),
            "total_batches": int(grouping_batch.get("total_batches") or 0),
            "unit_count": int(grouping_batch.get("unit_count") or 0),
            "remaining_batches_after_this": int(
                grouping_batch.get("remaining_batches_after_this") or 0
            ),
        }
        if any(compact_grouping_batch.values()):
            brief["grouping_batch"] = compact_grouping_batch
    return brief


def inspect_task_file_units(
    *,
    payload: Mapping[str, Any],
    task_file_path: str | None = None,
    unit_ids: Sequence[str] | None = None,
    answered: bool | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    units = _normalized_units(payload)
    indexed_units = [
        (_unit_id_for_index(unit, index), deepcopy(unit))
        for index, unit in enumerate(units)
    ]
    by_unit_id = {unit_id: unit for unit_id, unit in indexed_units}
    normalized_unit_ids = [
        str(unit_id).strip()
        for unit_id in (unit_ids or [])
        if str(unit_id).strip()
    ]
    safe_offset = max(int(offset), 0)
    safe_limit = None if limit is None else max(int(limit), 0)

    if normalized_unit_ids:
        selected_pairs = [
            (unit_id, deepcopy(by_unit_id[unit_id]))
            for unit_id in normalized_unit_ids
            if unit_id in by_unit_id
        ]
        missing_unit_ids = [
            unit_id for unit_id in normalized_unit_ids if unit_id not in by_unit_id
        ]
        if answered is not None:
            selected_pairs = [
                (unit_id, unit)
                for unit_id, unit in selected_pairs
                if _unit_has_answer(unit) is answered
            ]
    else:
        selected_pairs = [
            (unit_id, deepcopy(unit))
            for unit_id, unit in indexed_units
            if answered is None or _unit_has_answer(unit) is answered
        ]
        missing_unit_ids = []

    matching_unit_count = len(selected_pairs)
    if safe_offset:
        selected_pairs = selected_pairs[safe_offset:]
    if safe_limit is not None:
        selected_pairs = selected_pairs[:safe_limit]

    return {
        "task_file": str(task_file_path or TASK_FILE_NAME),
        "schema_version": str(payload.get("schema_version") or ""),
        "stage_key": str(payload.get("stage_key") or ""),
        "assignment_id": str(payload.get("assignment_id") or ""),
        "worker_id": str(payload.get("worker_id") or ""),
        "mode": str(payload.get("mode") or ""),
        "total_units": len(units),
        "matching_unit_count": matching_unit_count,
        "returned_unit_count": len(selected_pairs),
        "offset": safe_offset,
        "limit": safe_limit,
        "answered_filter": answered,
        "requested_unit_ids": normalized_unit_ids,
        "returned_unit_ids": [unit_id for unit_id, _ in selected_pairs],
        "missing_unit_ids": missing_unit_ids,
        "units": [unit for _, unit in selected_pairs],
    }


def apply_answers_to_task_file(
    *,
    path: Path,
    answers_by_unit_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    task_file = load_task_file(path)
    normalized_answers = {
        str(unit_id).strip(): dict(answer_payload)
        for unit_id, answer_payload in answers_by_unit_id.items()
        if str(unit_id).strip() and isinstance(answer_payload, Mapping)
    }
    applied_unit_ids: list[str] = []
    skipped_unit_ids: list[str] = []
    known_unit_ids: set[str] = set()
    changed = False
    for index, unit in enumerate(task_file.get("units") or []):
        if not isinstance(unit, Mapping):
            continue
        unit_dict = dict(unit)
        unit_id = str(unit_dict.get("unit_id") or "").strip() or f"unit-{index:03d}"
        known_unit_ids.add(unit_id)
        if unit_id not in normalized_answers:
            continue
        next_answer = dict(normalized_answers[unit_id])
        if unit_dict.get("answer") != next_answer:
            unit_dict["answer"] = next_answer
            task_file["units"][index] = unit_dict
            changed = True
        applied_unit_ids.append(unit_id)
    for unit_id in sorted(normalized_answers):
        if unit_id not in known_unit_ids:
            skipped_unit_ids.append(unit_id)
    if changed:
        write_task_file(path=path, payload=task_file)
    return {
        "task_file": str(path),
        "applied_unit_ids": applied_unit_ids,
        "skipped_unit_ids": skipped_unit_ids,
        "applied_count": len(applied_unit_ids),
        "skipped_count": len(skipped_unit_ids),
        "changed": changed,
    }


def _payload_has_meaningful_content(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_payload_has_meaningful_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_payload_has_meaningful_content(item) for item in value)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def validate_edited_task_file(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file: Mapping[str, Any],
    expected_schema_version: str | None = None,
    allow_immutable_field_changes: bool = False,
) -> tuple[dict[str, dict[str, Any]] | None, tuple[str, ...], dict[str, Any]]:
    errors: list[str] = []
    error_details: list[dict[str, str]] = []
    ignored_error_details: list[dict[str, str]] = []
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
            detail = {
                "path": path,
                "code": "immutable_field_changed",
                "message": f"{path} must not change",
            }
            if allow_immutable_field_changes:
                ignored_error_details.append(detail)
            else:
                errors.append("immutable_field_changed")
                error_details.append(detail)
    extra_top_level_keys = sorted(
        str(key) for key in edited.keys() if str(key) not in original and str(key) != "units"
    )
    for key in extra_top_level_keys:
        path = f"/{key}"
        detail = {
            "path": path,
            "code": "immutable_field_changed",
            "message": f"{path} must not be added",
        }
        if allow_immutable_field_changes:
            ignored_error_details.append(detail)
        else:
            errors.append("immutable_field_changed")
            error_details.append(detail)

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
                detail = {
                    "path": path,
                    "code": "immutable_field_changed",
                    "message": f"{path} must not change",
                }
                if allow_immutable_field_changes:
                    ignored_error_details.append(detail)
                else:
                    errors.append("immutable_field_changed")
                    error_details.append(detail)
        extra_keys = sorted(
            str(key) for key in edited_unit_dict.keys() if key not in original_unit_dict
        )
        for key in extra_keys:
            path = f"{unit_path}/{key}"
            detail = {
                "path": path,
                "code": "immutable_field_changed",
                "message": f"{path} must not be added",
            }
            if allow_immutable_field_changes:
                ignored_error_details.append(detail)
            else:
                errors.append("immutable_field_changed")
                error_details.append(detail)
        unit_id = str(original_unit_dict.get("unit_id") or "").strip() or f"unit-{index:03d}"
        answer_payload = edited_unit_dict.get("answer")
        answers_by_unit_id[unit_id] = (
            dict(answer_payload) if isinstance(answer_payload, Mapping) else {}
        )

    metadata = {
        "error_details": error_details,
        "ignored_error_details": ignored_error_details,
        "immutable_field_drift_ignored": bool(ignored_error_details),
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
    repair_task_file = build_task_file(
        stage_key=str(original_task_file.get("stage_key") or ""),
        assignment_id=str(original_task_file.get("assignment_id") or ""),
        worker_id=str(original_task_file.get("worker_id") or ""),
        mode="repair",
        units=units,
        schema_version=str(original_task_file.get("schema_version") or TASK_FILE_SCHEMA_VERSION),
        helper_commands=(
            dict(original_task_file.get("helper_commands") or {})
            if isinstance(original_task_file.get("helper_commands"), Mapping)
            else None
        ),
        workflow=list(original_task_file.get("workflow") or []),
        next_action=(
            str(original_task_file.get("next_action") or "")
            if str(original_task_file.get("next_action") or "").strip()
            else None
        ),
        answer_schema=(
            dict(original_task_file.get("answer_schema") or {})
            if isinstance(original_task_file.get("answer_schema"), Mapping)
            else None
        ),
    )
    for key, value in original_task_file.items():
        normalized_key = str(key)
        if normalized_key == "units" or normalized_key in repair_task_file:
            continue
        repair_task_file[normalized_key] = deepcopy(value)
    return repair_task_file


def _summarize_answer_schema(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    required_keys = _normalized_string_list(value.get("required_keys"))
    optional_keys = _normalized_string_list(value.get("optional_keys"))
    allowed_values = value.get("allowed_values")
    example_answers = value.get("example_answers")
    summary = {
        "required_keys": required_keys,
        "optional_keys": optional_keys,
        "allowed_value_keys": (
            sorted(str(key) for key in allowed_values.keys())
            if isinstance(allowed_values, Mapping)
            else []
        ),
        "example_answer_count": (
            len([row for row in example_answers if isinstance(row, Mapping)])
            if isinstance(example_answers, list)
            else 0
        ),
    }
    if not any(summary.values()):
        return None
    return summary


def _summarize_current_unit(payload: Mapping[str, Any]) -> dict[str, Any]:
    helper_commands = payload.get("helper_commands")
    if not isinstance(helper_commands, Mapping) or "show_current" not in helper_commands:
        return {}
    units = _normalized_units(payload)
    for index, unit in enumerate(units):
        if _unit_has_answer(unit):
            continue
        return {
            "current_unit_id": _unit_id_for_index(unit, index),
            "current_unit_position": index + 1,
            "current_unit_remaining_count": len(units) - index,
        }
    return {
        "current_unit_id": None,
        "current_unit_position": None,
        "current_unit_remaining_count": 0,
    }


def _parse_answer_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid answer JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("answer JSON must be one object")
    return dict(payload)


def _load_answer_mapping_file(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping):
        nested_mapping = payload.get("answers_by_unit_id")
        if isinstance(nested_mapping, Mapping):
            return {
                str(unit_id).strip(): dict(answer_payload)
                for unit_id, answer_payload in nested_mapping.items()
                if str(unit_id).strip() and isinstance(answer_payload, Mapping)
            }
        direct_mapping = {
            str(unit_id).strip(): dict(answer_payload)
            for unit_id, answer_payload in payload.items()
            if str(unit_id).strip() and isinstance(answer_payload, Mapping)
        }
        if direct_mapping:
            return direct_mapping
    if isinstance(payload, list):
        output: dict[str, dict[str, Any]] = {}
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            unit_id = str(row.get("unit_id") or "").strip()
            answer_payload = row.get("answer")
            if unit_id and isinstance(answer_payload, Mapping):
                output[unit_id] = dict(answer_payload)
        if output:
            return output
    raise ValueError("answer mapping file must be {unit_id: answer}, {answers_by_unit_id: ...}, or a list of {unit_id, answer}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize or apply answers to one editable task.json file."
    )
    parser.add_argument(
        "--task-file",
        default=TASK_FILE_NAME,
        help="Path to task.json. Defaults to ./task.json.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact JSON summary of the task file. This is the default action.",
    )
    parser.add_argument(
        "--show-unit",
        action="append",
        metavar="UNIT_ID",
        help="Print one specific unit payload by unit_id. May be repeated.",
    )
    parser.add_argument(
        "--show-unanswered",
        action="store_true",
        help="Print unanswered unit payloads instead of the summary.",
    )
    parser.add_argument(
        "--show-answered",
        action="store_true",
        help="Print answered unit payloads instead of the summary.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of units to return for --show-unit/--show-unanswered/--show-answered.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip this many matching units before returning rows for the show-unit modes.",
    )
    parser.add_argument(
        "--set-answer",
        action="append",
        nargs=2,
        metavar=("UNIT_ID", "ANSWER_JSON"),
        help="Apply one answer object to one unit_id.",
    )
    parser.add_argument(
        "--apply-answers-file",
        help="Apply answers from a JSON file keyed by unit_id or from a list of {unit_id, answer} rows.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    task_file_path = Path(str(args.task_file)).expanduser()
    set_answer_rows = list(args.set_answer or [])
    show_unit_ids = list(args.show_unit or [])
    if args.apply_answers_file and set_answer_rows:
        raise SystemExit("use either --apply-answers-file or --set-answer, not both")
    if args.show_answered and args.show_unanswered:
        raise SystemExit("use at most one of --show-answered or --show-unanswered")
    if (args.apply_answers_file or set_answer_rows) and (
        show_unit_ids or args.show_answered or args.show_unanswered
    ):
        raise SystemExit("show-unit modes cannot be combined with answer-apply modes")
    if args.apply_answers_file or set_answer_rows:
        answers_by_unit_id: dict[str, dict[str, Any]] = {}
        if args.apply_answers_file:
            answers_by_unit_id = _load_answer_mapping_file(
                Path(str(args.apply_answers_file)).expanduser()
            )
        else:
            for unit_id, answer_json in set_answer_rows:
                answers_by_unit_id[str(unit_id).strip()] = _parse_answer_payload(answer_json)
        result = apply_answers_to_task_file(
            path=task_file_path,
            answers_by_unit_id=answers_by_unit_id,
        )
    else:
        task_file = load_task_file(task_file_path)
        if show_unit_ids or args.show_answered or args.show_unanswered:
            answered_filter = True if args.show_answered else False if args.show_unanswered else None
            result = inspect_task_file_units(
                payload=task_file,
                task_file_path=str(task_file_path),
                unit_ids=show_unit_ids,
                answered=answered_filter,
                offset=args.offset,
                limit=args.limit,
            )
        else:
            result = summarize_task_file(payload=task_file, task_file_path=str(task_file_path))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
