from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .codex_farm_contracts import RecipeCorrectionShardOutput
from .editable_task_file import (
    TASK_FILE_NAME,
    build_repair_task_file,
    load_task_file,
    validate_edited_task_file,
    write_task_file,
)
from .phase_worker_runtime import ShardManifestEntryV1

RECIPE_SAME_SESSION_HANDOFF_SCHEMA_VERSION = "recipe_same_session_handoff.v1"
RECIPE_SAME_SESSION_STATE_ENV = "RECIPEIMPORT_RECIPE_SAME_SESSION_STATE_PATH"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def initialize_recipe_same_session_state(
    *,
    state_path: Path,
    assignment_id: str,
    worker_id: str,
    task_file: Mapping[str, Any],
    task_records: Sequence[Mapping[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    normalized_task_records = [
        {
            "unit_id": str(record.get("unit_id") or ""),
            "task_id": str(record.get("task_id") or ""),
            "parent_shard_id": str(record.get("parent_shard_id") or ""),
            "result_path": str(record.get("result_path") or ""),
            "manifest_entry": dict(record.get("manifest_entry") or {}),
        }
        for record in task_records
        if isinstance(record, Mapping)
    ]
    payload = {
        "schema_version": RECIPE_SAME_SESSION_HANDOFF_SCHEMA_VERSION,
        "assignment_id": str(assignment_id),
        "worker_id": str(worker_id),
        "current_original_task_file": dict(task_file),
        "task_records": normalized_task_records,
        "current_task_ids": [
            str(record.get("task_id") or "")
            for record in normalized_task_records
            if str(record.get("task_id") or "").strip()
        ],
        "output_dir": str(output_dir),
        "same_session_transition_count": 0,
        "validation_count": 0,
        "same_session_repair_rewrite_count": 0,
        "task_payloads_by_task_id": {},
        "task_validation_errors_by_task_id": {},
        "task_status_by_task_id": {},
        "completed": False,
        "final_status": None,
        "completed_task_count": 0,
        "transition_history": [],
    }
    _write_json(state_path, payload)
    return payload


def _build_task_feedback(
    *,
    validation_errors: list[str],
    error_details: list[dict[str, Any]] | None = None,
    repair_instruction: str,
) -> dict[str, Any]:
    return {
        "error_codes": [str(error).strip() for error in validation_errors if str(error).strip()],
        "error_details": [
            {
                "path": str(detail.get("path") or "/answer"),
                "code": str(detail.get("code") or "validation_error"),
                "message": str(detail.get("message") or "validation failed"),
            }
            for detail in (error_details or [])
            if isinstance(detail, Mapping)
        ],
        "repair_instruction": repair_instruction,
    }


def _append_transition_history(
    *,
    state: dict[str, Any],
    status: str,
    validation_errors: list[str],
    transition_metadata: Mapping[str, Any] | None = None,
) -> None:
    history = list(state.get("transition_history") or [])
    history.append(
        {
            "status": str(status),
            "validation_errors": list(validation_errors),
            "transition_metadata": dict(transition_metadata or {}),
        }
    )
    state["transition_history"] = history


def _task_records_by_task_id(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for record in state.get("task_records") or []:
        if not isinstance(record, Mapping):
            continue
        task_id = str(record.get("task_id") or "").strip()
        if not task_id:
            continue
        output[task_id] = dict(record)
    return output


def _current_task_records(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    task_records_by_task_id = _task_records_by_task_id(state)
    output: list[dict[str, Any]] = []
    for task_id in state.get("current_task_ids") or []:
        task_id_str = str(task_id).strip()
        if task_id_str and task_id_str in task_records_by_task_id:
            output.append(dict(task_records_by_task_id[task_id_str]))
    return output


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _write_recipe_task_payload(
    *,
    output_path: Path,
    payload: Mapping[str, Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _repair_exhausted_result(
    *,
    state: dict[str, Any],
    state_path: Path,
    validation_errors: Sequence[str],
    failed_task_ids: Sequence[str],
) -> dict[str, Any]:
    state["completed"] = False
    state["final_status"] = "repair_exhausted"
    _append_transition_history(
        state=state,
        status="repair_exhausted",
        validation_errors=list(validation_errors),
        transition_metadata={"failed_task_ids": list(failed_task_ids)},
    )
    _write_json(state_path, state)
    return {
        "status": "repair_exhausted",
        "same_session_transition_count": int(
            state.get("same_session_transition_count") or 0
        ),
        "validation_count": int(state.get("validation_count") or 0),
        "same_session_repair_rewrite_count": int(
            state.get("same_session_repair_rewrite_count") or 0
        ),
        "completed": False,
        "final_status": state.get("final_status"),
        "completed_task_count": int(state.get("completed_task_count") or 0),
        "validation_errors": list(validation_errors),
        "transition_metadata": {"failed_task_ids": list(failed_task_ids)},
    }


def _recipe_answer_to_compact_payload(
    *,
    task_record: Mapping[str, Any],
    answer_payload: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_entry = _coerce_dict(task_record.get("manifest_entry"))
    recipe_row = _coerce_dict((_coerce_dict(manifest_entry.get("input_payload")).get("r") or [{}])[0])
    owned_ids = list(manifest_entry.get("owned_ids") or [])
    recipe_id = str(recipe_row.get("rid") or "").strip() or str(owned_ids[0] if owned_ids else task_record.get("task_id") or "")
    canonical_recipe = (
        dict(answer_payload.get("canonical_recipe"))
        if isinstance(answer_payload.get("canonical_recipe"), Mapping)
        else None
    )
    mapping_rows: list[dict[str, Any]] = []
    for mapping_row in answer_payload.get("ingredient_step_mapping") or []:
        if not isinstance(mapping_row, Mapping):
            continue
        ingredient_indexes = [
            int(value)
            for value in (mapping_row.get("ingredient_indexes") or [])
            if str(value).strip()
        ]
        step_indexes = [
            int(value)
            for value in (mapping_row.get("step_indexes") or [])
            if str(value).strip()
        ]
        for ingredient_index in ingredient_indexes:
            mapping_rows.append({"i": ingredient_index, "s": step_indexes})
    return {
        "v": "1",
        "sid": str(task_record.get("task_id") or ""),
        "r": [
            {
                "v": "1",
                "rid": recipe_id,
                "st": str(answer_payload.get("status") or "").strip(),
                "sr": answer_payload.get("status_reason"),
                "cr": (
                    {
                        "t": canonical_recipe.get("title"),
                        "i": list(canonical_recipe.get("ingredients") or []),
                        "s": list(canonical_recipe.get("steps") or []),
                        "d": canonical_recipe.get("description"),
                        "y": canonical_recipe.get("recipe_yield"),
                    }
                    if canonical_recipe is not None
                    else None
                ),
                "m": mapping_rows,
                "mr": answer_payload.get("ingredient_step_mapping_reason"),
                "g": [
                    {"c": "selected", "l": str(tag).strip()}
                    for tag in (answer_payload.get("selected_tags") or [])
                    if str(tag).strip()
                ],
                "w": [
                    str(value).strip()
                    for value in (answer_payload.get("warnings") or [])
                    if str(value).strip()
                ],
            }
        ],
    }


def _evaluate_recipe_response(
    *,
    shard: ShardManifestEntryV1,
    response_payload: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    try:
        shard_output = RecipeCorrectionShardOutput.model_validate(dict(response_payload))
    except Exception as exc:  # noqa: BLE001
        return None, (f"invalid_shard_output:{exc}",), {}, "invalid"
    serialized_payload = shard_output.model_dump(mode="json", by_alias=True)
    expected_ids = [str(value).strip() for value in shard.owned_ids if str(value).strip()]
    actual_ids = [
        str(recipe.recipe_id).strip()
        for recipe in shard_output.recipes
        if str(recipe.recipe_id).strip()
    ]
    validation_errors: list[str] = []
    if str(shard_output.shard_id).strip() != shard.shard_id:
        validation_errors.append("shard_id_mismatch")
    duplicate_ids = sorted(
        {
            recipe_id
            for recipe_id in actual_ids
            if actual_ids.count(recipe_id) > 1
        }
    )
    missing_ids = sorted(set(expected_ids) - set(actual_ids))
    unexpected_ids = sorted(set(actual_ids) - set(expected_ids))
    if duplicate_ids:
        validation_errors.append("duplicate_recipe_ids")
    if missing_ids:
        validation_errors.append("missing_recipe_ids")
    if unexpected_ids:
        validation_errors.append("unexpected_recipe_ids")
    metadata = {
        "owned_recipe_ids": expected_ids,
        "actual_recipe_ids": actual_ids,
        "duplicate_recipe_ids": duplicate_ids,
        "missing_recipe_ids": missing_ids,
        "unexpected_recipe_ids": unexpected_ids,
        "recipe_count": len(actual_ids),
    }
    if validation_errors:
        return None, tuple(validation_errors), metadata, "invalid"
    return serialized_payload, (), metadata, "validated"


def _evaluate_recipe_task_file_answers(
    *,
    original_task_file: Mapping[str, Any],
    edited_task_file_path: Path,
    current_task_records: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, tuple[str, ...]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    task_by_unit_id = {
        str(record.get("unit_id") or ""): dict(record)
        for record in current_task_records
        if str(record.get("unit_id") or "").strip()
    }
    edited_task_file = load_task_file(edited_task_file_path)
    answers_by_unit_id, contract_errors, contract_metadata = validate_edited_task_file(
        original_task_file=original_task_file,
        edited_task_file=edited_task_file,
    )
    payloads_by_task_id: dict[str, dict[str, Any]] = {}
    errors_by_task_id: dict[str, tuple[str, ...]] = {}
    previous_answers_by_unit_id: dict[str, dict[str, Any]] = {}
    feedback_by_unit_id: dict[str, dict[str, Any]] = {}
    if contract_errors:
        feedback = _build_task_feedback(
            validation_errors=list(contract_errors),
            error_details=list(contract_metadata.get("error_details") or []),
            repair_instruction="Restore immutable fields and edit only `/units/*/answer`.",
        )
        for unit_id, record in task_by_unit_id.items():
            task_id = str(record.get("task_id") or "").strip()
            errors_by_task_id[task_id] = tuple(contract_errors)
            previous_answers_by_unit_id[unit_id] = {}
            feedback_by_unit_id[unit_id] = dict(feedback)
        return payloads_by_task_id, errors_by_task_id, previous_answers_by_unit_id, feedback_by_unit_id

    resolved_answers = answers_by_unit_id or {}
    for unit_id, record in task_by_unit_id.items():
        answer_payload = dict(resolved_answers.get(unit_id) or {})
        previous_answers_by_unit_id[unit_id] = dict(answer_payload)
        response_payload = _recipe_answer_to_compact_payload(
            task_record=record,
            answer_payload=answer_payload,
        )
        shard = ShardManifestEntryV1(**dict(record.get("manifest_entry") or {}))
        payload, validation_errors, _validation_metadata, proposal_status = _evaluate_recipe_response(
            shard=shard,
            response_payload=response_payload,
        )
        task_id = str(record.get("task_id") or "").strip()
        if proposal_status == "validated" and payload is not None:
            payloads_by_task_id[task_id] = payload
            continue
        errors_by_task_id[task_id] = tuple(validation_errors)
        feedback_by_unit_id[unit_id] = _build_task_feedback(
            validation_errors=list(validation_errors),
            error_details=[
                {
                    "path": "/answer",
                    "code": str(error).strip() or "validation_error",
                    "message": str(error).strip() or "validation failed",
                }
                for error in validation_errors
            ],
            repair_instruction="Fix the named recipe answer fields and keep ownership exact.",
        )
    return payloads_by_task_id, errors_by_task_id, previous_answers_by_unit_id, feedback_by_unit_id


def advance_recipe_same_session_handoff(
    *,
    workspace_root: Path,
    state_path: Path,
) -> dict[str, Any]:
    state = _load_json_dict(state_path)
    task_file_path = workspace_root / TASK_FILE_NAME
    current_original_task_file = dict(state.get("current_original_task_file") or {})
    current_mode = str(current_original_task_file.get("mode") or "initial").strip()
    current_task_records = _current_task_records(state)
    (
        payloads_by_task_id,
        errors_by_task_id,
        previous_answers_by_unit_id,
        feedback_by_unit_id,
    ) = _evaluate_recipe_task_file_answers(
        original_task_file=current_original_task_file,
        edited_task_file_path=task_file_path,
        current_task_records=current_task_records,
    )

    state["same_session_transition_count"] = int(
        state.get("same_session_transition_count") or 0
    ) + 1
    state["validation_count"] = int(state.get("validation_count") or 0) + 1

    task_payloads_by_task_id = dict(state.get("task_payloads_by_task_id") or {})
    task_validation_errors_by_task_id = {
        str(task_id): list(errors)
        for task_id, errors in dict(state.get("task_validation_errors_by_task_id") or {}).items()
    }
    task_status_by_task_id = {
        str(task_id): dict(status_payload)
        for task_id, status_payload in dict(state.get("task_status_by_task_id") or {}).items()
    }

    for task_id, payload in payloads_by_task_id.items():
        record = _task_records_by_task_id(state).get(task_id) or {}
        result_path = str(record.get("result_path") or "").strip()
        if result_path:
            _write_recipe_task_payload(
                output_path=workspace_root / result_path,
                payload=payload,
            )
        task_payloads_by_task_id[task_id] = dict(payload)
        task_validation_errors_by_task_id[task_id] = []
        task_status_by_task_id[task_id] = {
            "task_status": "validated_after_repair" if current_mode == "repair" else "validated",
            "repair_attempted": current_mode == "repair",
            "repair_status": "repaired" if current_mode == "repair" else "not_needed",
            "validation_errors": [],
        }

    state["task_payloads_by_task_id"] = task_payloads_by_task_id
    state["task_validation_errors_by_task_id"] = task_validation_errors_by_task_id
    state["task_status_by_task_id"] = task_status_by_task_id
    state["completed_task_count"] = len(task_payloads_by_task_id)

    if errors_by_task_id:
        task_records_by_task_id = _task_records_by_task_id(state)
        failed_task_ids = sorted(str(task_id) for task_id in errors_by_task_id.keys())
        failed_unit_ids = [
            str(task_records_by_task_id[task_id].get("unit_id") or "").strip()
            for task_id in failed_task_ids
            if str(task_records_by_task_id.get(task_id, {}).get("unit_id") or "").strip()
        ]
        for task_id in failed_task_ids:
            task_validation_errors_by_task_id[task_id] = list(errors_by_task_id.get(task_id) or [])
            task_status_by_task_id[task_id] = {
                "task_status": "failed_after_repair" if current_mode == "repair" else "invalid",
                "repair_attempted": current_mode == "repair",
                "repair_status": "failed" if current_mode == "repair" else "not_attempted",
                "validation_errors": list(errors_by_task_id.get(task_id) or []),
            }
        validation_errors = sorted(
            {
                str(error).strip()
                for errors in errors_by_task_id.values()
                for error in errors
                if str(error).strip()
            }
        )
        state["task_validation_errors_by_task_id"] = task_validation_errors_by_task_id
        state["task_status_by_task_id"] = task_status_by_task_id
        if current_mode == "repair":
            return _repair_exhausted_result(
                state=state,
                state_path=state_path,
                validation_errors=validation_errors,
                failed_task_ids=failed_task_ids,
            )
        repair_task_file = build_repair_task_file(
            original_task_file=current_original_task_file,
            failed_unit_ids=failed_unit_ids,
            previous_answers_by_unit_id=previous_answers_by_unit_id,
            validation_feedback_by_unit_id=feedback_by_unit_id,
        )
        write_task_file(path=task_file_path, payload=repair_task_file)
        state["current_original_task_file"] = dict(repair_task_file)
        state["current_task_ids"] = failed_task_ids
        state["same_session_repair_rewrite_count"] = int(
            state.get("same_session_repair_rewrite_count") or 0
        ) + 1
        state["task_validation_errors_by_task_id"] = task_validation_errors_by_task_id
        state["task_status_by_task_id"] = task_status_by_task_id
        state["completed"] = False
        state["final_status"] = "repair_required"
        _append_transition_history(
            state=state,
            status="repair_required",
            validation_errors=validation_errors,
            transition_metadata={"failed_task_ids": failed_task_ids},
        )
        _write_json(state_path, state)
        return {
            "status": "repair_required",
            "same_session_transition_count": int(
                state.get("same_session_transition_count") or 0
            ),
            "validation_count": int(state.get("validation_count") or 0),
            "same_session_repair_rewrite_count": int(
                state.get("same_session_repair_rewrite_count") or 0
            ),
            "completed": False,
            "final_status": state.get("final_status"),
            "completed_task_count": int(state.get("completed_task_count") or 0),
            "validation_errors": validation_errors,
            "transition_metadata": {"failed_task_ids": failed_task_ids},
        }

    state["completed"] = True
    state["final_status"] = "completed"
    state["current_task_ids"] = []
    _append_transition_history(
        state=state,
        status="completed",
        validation_errors=[],
        transition_metadata={"completed_task_count": len(task_payloads_by_task_id)},
    )
    _write_json(state_path, state)
    return {
        "status": "completed",
        "same_session_transition_count": int(state.get("same_session_transition_count") or 0),
        "validation_count": int(state.get("validation_count") or 0),
        "same_session_repair_rewrite_count": int(
            state.get("same_session_repair_rewrite_count") or 0
        ),
        "completed": True,
        "final_status": state.get("final_status"),
        "completed_task_count": int(state.get("completed_task_count") or 0),
        "validation_errors": [],
        "transition_metadata": {"completed_task_count": len(task_payloads_by_task_id)},
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and advance one recipe same-session task.json handoff."
    )
    parser.add_argument(
        "--state-path",
        default=os.environ.get(RECIPE_SAME_SESSION_STATE_ENV),
        help=f"Path to the hidden repo-owned handoff state file. Defaults to ${RECIPE_SAME_SESSION_STATE_ENV}.",
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root containing task.json. Defaults to the current directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not str(args.state_path or "").strip():
        raise SystemExit(f"missing --state-path or ${RECIPE_SAME_SESSION_STATE_ENV}")
    result = advance_recipe_same_session_handoff(
        workspace_root=Path(str(args.workspace_root)).expanduser(),
        state_path=Path(str(args.state_path)).expanduser(),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
