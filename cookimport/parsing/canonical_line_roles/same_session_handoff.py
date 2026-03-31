from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.llm.editable_task_file import (
    TASK_FILE_NAME,
    build_repair_task_file,
    load_task_file,
    validate_edited_task_file,
    write_task_file,
)

LINE_ROLE_SAME_SESSION_HANDOFF_SCHEMA_VERSION = "line_role_same_session_handoff.v1"
LINE_ROLE_SAME_SESSION_STATE_ENV = "RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def initialize_line_role_same_session_state(
    *,
    state_path: Path,
    assignment_id: str,
    worker_id: str,
    task_file: Mapping[str, Any],
    unit_to_shard_id: Mapping[str, str],
    shards: Sequence[Mapping[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    payload = {
        "schema_version": LINE_ROLE_SAME_SESSION_HANDOFF_SCHEMA_VERSION,
        "assignment_id": str(assignment_id),
        "worker_id": str(worker_id),
        "current_original_task_file": dict(task_file),
        "unit_to_shard_id": {
            str(unit_id): str(shard_id)
            for unit_id, shard_id in unit_to_shard_id.items()
        },
        "shards": [dict(shard) for shard in shards if isinstance(shard, Mapping)],
        "output_dir": str(output_dir),
        "same_session_transition_count": 0,
        "validation_count": 0,
        "same_session_repair_rewrite_count": 0,
        "shard_status_by_shard_id": {},
        "completed": False,
        "final_status": None,
        "completed_shard_count": 0,
        "transition_history": [],
    }
    _write_json(state_path, payload)
    return payload


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


def _answers_from_task_file(task_file: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    answers: dict[str, dict[str, Any]] = {}
    for index, unit in enumerate(task_file.get("units") or []):
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip() or f"unit-{index:03d}"
        answer_payload = unit.get("answer")
        answers[unit_id] = dict(answer_payload) if isinstance(answer_payload, Mapping) else {}
    return answers


def _build_line_role_feedback(
    *,
    validation_errors: list[str],
    error_details: Sequence[Mapping[str, Any]] | None = None,
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
        "repair_instruction": (
            "Fix the named line-role answers, keep immutable evidence unchanged, "
            "and use only allowed exclusion_reason codes."
        ),
    }


def _repair_exhausted_result(
    *,
    state: dict[str, Any],
    state_path: Path,
    shard_status_by_shard_id: Mapping[str, Mapping[str, Any]],
    validation_errors: Sequence[str],
    failed_shard_ids: Sequence[str],
) -> dict[str, Any]:
    state["shard_status_by_shard_id"] = {
        str(shard_id): dict(status_payload)
        for shard_id, status_payload in shard_status_by_shard_id.items()
    }
    state["completed"] = False
    state["final_status"] = "repair_exhausted"
    _append_transition_history(
        state=state,
        status="repair_exhausted",
        validation_errors=list(validation_errors),
        transition_metadata={"failed_shard_ids": list(failed_shard_ids)},
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
        "completed_shard_count": int(state.get("completed_shard_count") or 0),
        "validation_errors": list(validation_errors),
        "transition_metadata": {"failed_shard_ids": list(failed_shard_ids)},
    }


def advance_line_role_same_session_handoff(
    *,
    workspace_root: Path,
    state_path: Path,
) -> dict[str, Any]:
    from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1

    from . import runtime as line_role_runtime
    from . import validation as line_role_validation

    state = _load_json_dict(state_path)
    task_file_path = workspace_root / TASK_FILE_NAME
    edited_task_file = load_task_file(task_file_path)
    current_original_task_file = dict(state.get("current_original_task_file") or {})
    unit_to_shard_id = {
        str(unit_id): str(shard_id)
        for unit_id, shard_id in dict(state.get("unit_to_shard_id") or {}).items()
    }
    shard_records = [
        dict(record) for record in (state.get("shards") or []) if isinstance(record, Mapping)
    ]
    shard_by_id = {
        str(record.get("shard_id") or "").strip(): ShardManifestEntryV1(**record)
        for record in shard_records
        if str(record.get("shard_id") or "").strip()
    }
    current_mode = str(current_original_task_file.get("mode") or "initial").strip()

    answers_by_unit_id, contract_errors, contract_metadata = validate_edited_task_file(
        original_task_file=current_original_task_file,
        edited_task_file=edited_task_file,
        allow_immutable_field_changes=True,
    )
    previous_answers_by_unit_id = _answers_from_task_file(edited_task_file)
    shard_status_by_shard_id = {
        str(shard_id): dict(payload)
        for shard_id, payload in dict(state.get("shard_status_by_shard_id") or {}).items()
    }

    state["same_session_transition_count"] = int(
        state.get("same_session_transition_count") or 0
    ) + 1
    state["validation_count"] = int(state.get("validation_count") or 0) + 1

    if contract_errors:
        validation_errors = list(contract_errors)
        feedback = _build_line_role_feedback(
            validation_errors=validation_errors,
            error_details=contract_metadata.get("error_details") if isinstance(contract_metadata, Mapping) else None,
        )
        failed_unit_ids = [
            str(unit.get("unit_id") or "").strip()
            for unit in current_original_task_file.get("units") or []
            if isinstance(unit, Mapping) and str(unit.get("unit_id") or "").strip()
        ]
        validation_feedback_by_unit_id = {
            unit_id: dict(feedback)
            for unit_id in failed_unit_ids
        }
        for shard_id in unit_to_shard_id.values():
            shard_status_by_shard_id[shard_id] = {
                "repair_attempted": current_mode == "repair",
                "repair_status": "failed" if current_mode == "repair" else "not_attempted",
                "validation_errors": validation_errors,
            }
        if current_mode == "repair":
            return _repair_exhausted_result(
                state=state,
                state_path=state_path,
                shard_status_by_shard_id=shard_status_by_shard_id,
                validation_errors=validation_errors,
                failed_shard_ids=sorted(set(unit_to_shard_id.values())),
            )
        repair_task_file = build_repair_task_file(
            original_task_file=current_original_task_file,
            failed_unit_ids=failed_unit_ids,
            previous_answers_by_unit_id=previous_answers_by_unit_id,
            validation_feedback_by_unit_id=validation_feedback_by_unit_id,
        )
        write_task_file(path=task_file_path, payload=repair_task_file)
        state["current_original_task_file"] = dict(repair_task_file)
        state["same_session_repair_rewrite_count"] = int(
            state.get("same_session_repair_rewrite_count") or 0
        ) + 1
        state["shard_status_by_shard_id"] = shard_status_by_shard_id
        state["completed"] = False
        state["final_status"] = "repair_required"
        _append_transition_history(
            state=state,
            status="repair_required",
            validation_errors=validation_errors,
            transition_metadata={"contract_errors": validation_errors},
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
            "completed_shard_count": int(state.get("completed_shard_count") or 0),
            "validation_errors": validation_errors,
            "transition_metadata": {"contract_errors": validation_errors},
        }

    answers_by_unit_id = dict(answers_by_unit_id or {})
    shard_rows: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    previous_feedback_by_unit_id: dict[str, dict[str, Any]] = {}
    failed_shard_ids: list[str] = []
    failed_validation_errors: list[str] = []
    for unit in current_original_task_file.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        shard_id = str(unit_to_shard_id.get(unit_id) or "").strip()
        if not shard_id:
            continue
        evidence = dict(unit.get("evidence") or {})
        answer = dict(answers_by_unit_id.get(unit_id) or {})
        shard_rows.setdefault(shard_id, []).append(
            (int(evidence.get("atomic_index") or 0), answer)
        )

    for shard_id, rows in sorted(shard_rows.items()):
        shard = shard_by_id.get(shard_id)
        if shard is None:
            continue
        payload = {
            "rows": [
                {
                    **{
                        "atomic_index": atomic_index,
                        "label": str(answer.get("label") or ""),
                    },
                    **(
                        {"exclusion_reason": answer.get("exclusion_reason")}
                        if answer.get("exclusion_reason") is not None
                        else {}
                    ),
                }
                for atomic_index, answer in sorted(rows, key=lambda row: row[0])
            ]
        }
        (
            _payload_candidate,
            validation_errors,
            validation_metadata,
            _proposal_status,
        ) = line_role_validation._evaluate_line_role_response_with_pathology_guard(
            shard=shard,
            response_text=json.dumps(payload, sort_keys=True),
            validator=line_role_validation._validate_line_role_shard_proposal,
            deterministic_baseline_by_atomic_index={},
        )
        resolved_payload, row_resolution_metadata = line_role_validation._build_line_role_row_resolution(
            shard=shard,
            validation_metadata=validation_metadata,
        )
        if resolved_payload is not None:
            line_role_runtime._write_runtime_json(
                workspace_root / "out" / f"{shard_id}.json",
                resolved_payload,
            )
            shard_status_by_shard_id[shard_id] = {
                "repair_attempted": current_mode == "repair",
                "repair_status": "repaired" if current_mode == "repair" else "not_needed",
                "validation_errors": [],
                "row_resolution_metadata": dict(row_resolution_metadata),
            }
            continue
        failed_shard_ids.append(shard_id)
        failed_validation_errors.extend(str(error).strip() for error in validation_errors if str(error).strip())
        feedback = _build_line_role_feedback(validation_errors=list(validation_errors))
        for unit_id, mapped_shard_id in unit_to_shard_id.items():
            if mapped_shard_id == shard_id:
                previous_feedback_by_unit_id[unit_id] = dict(feedback)
        shard_status_by_shard_id[shard_id] = {
            "repair_attempted": current_mode == "repair",
            "repair_status": "failed" if current_mode == "repair" else "not_attempted",
            "validation_errors": list(validation_errors),
            "row_resolution_metadata": dict(row_resolution_metadata),
        }

    if failed_shard_ids:
        failed_unit_ids = [
            unit_id
            for unit_id, shard_id in unit_to_shard_id.items()
            if shard_id in set(failed_shard_ids)
        ]
        validation_errors = sorted({error for error in failed_validation_errors if error})
        if current_mode == "repair":
            return _repair_exhausted_result(
                state=state,
                state_path=state_path,
                shard_status_by_shard_id=shard_status_by_shard_id,
                validation_errors=validation_errors,
                failed_shard_ids=failed_shard_ids,
            )
        repair_task_file = build_repair_task_file(
            original_task_file=current_original_task_file,
            failed_unit_ids=failed_unit_ids,
            previous_answers_by_unit_id=previous_answers_by_unit_id,
            validation_feedback_by_unit_id=previous_feedback_by_unit_id,
        )
        write_task_file(path=task_file_path, payload=repair_task_file)
        state["current_original_task_file"] = dict(repair_task_file)
        state["same_session_repair_rewrite_count"] = int(
            state.get("same_session_repair_rewrite_count") or 0
        ) + 1
        state["shard_status_by_shard_id"] = shard_status_by_shard_id
        state["completed"] = False
        state["final_status"] = "repair_required"
        _append_transition_history(
            state=state,
            status="repair_required",
            validation_errors=validation_errors,
            transition_metadata={"failed_shard_ids": failed_shard_ids},
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
            "completed_shard_count": int(state.get("completed_shard_count") or 0),
            "validation_errors": validation_errors,
            "transition_metadata": {"failed_shard_ids": failed_shard_ids},
        }

    state["shard_status_by_shard_id"] = shard_status_by_shard_id
    state["completed"] = True
    state["final_status"] = "completed"
    state["completed_shard_count"] = sum(
        1
        for payload in shard_status_by_shard_id.values()
        if str((payload or {}).get("repair_status") or "").strip() in {"not_needed", "repaired"}
    )
    _append_transition_history(
        state=state,
        status="completed",
        validation_errors=[],
        transition_metadata={"completed_shard_count": int(state.get("completed_shard_count") or 0)},
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
        "completed_shard_count": int(state.get("completed_shard_count") or 0),
        "validation_errors": [],
        "transition_metadata": {
            "completed_shard_count": int(state.get("completed_shard_count") or 0)
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and advance one canonical line-role same-session task.json handoff."
    )
    parser.add_argument(
        "--state-path",
        default=os.environ.get(LINE_ROLE_SAME_SESSION_STATE_ENV),
        help=f"Path to the hidden repo-owned handoff state file. Defaults to ${LINE_ROLE_SAME_SESSION_STATE_ENV}.",
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
        raise SystemExit(f"missing --state-path or ${LINE_ROLE_SAME_SESSION_STATE_ENV}")
    result = advance_line_role_same_session_handoff(
        workspace_root=Path(str(args.workspace_root)).expanduser(),
        state_path=Path(str(args.state_path)).expanduser(),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
