from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .editable_task_file import TASK_FILE_NAME, load_task_file, summarize_task_file, write_task_file
from .knowledge_stage.task_file_contracts import (
    KnowledgeTaskFileTransition,
    transition_knowledge_classification_task_file,
    transition_knowledge_grouping_task_file,
)
from .repair_recovery_policy import (
    KNOWLEDGE_POLICY_STAGE_KEY,
    taskfile_fresh_session_retry_limit,
    taskfile_same_session_repair_rewrite_limit,
)

KNOWLEDGE_SAME_SESSION_HANDOFF_SCHEMA_VERSION = "knowledge_same_session_handoff.v1"
KNOWLEDGE_SAME_SESSION_STATE_ENV = "RECIPEIMPORT_KNOWLEDGE_SAME_SESSION_STATE_PATH"
_KNOWLEDGE_SAME_SESSION_STATE_FILE_NAME = "knowledge_same_session_state.json"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def initialize_knowledge_same_session_state(
    *,
    state_path: Path,
    assignment_id: str,
    worker_id: str,
    classification_task_file: Mapping[str, Any],
    unit_to_shard_id: Mapping[str, str],
    output_dir: Path,
    knowledge_grouping_enabled: bool = False,
) -> dict[str, Any]:
    payload = {
        "schema_version": KNOWLEDGE_SAME_SESSION_HANDOFF_SCHEMA_VERSION,
        "assignment_id": str(assignment_id),
        "worker_id": str(worker_id),
        "current_stage_key": str(classification_task_file.get("stage_key") or ""),
        "current_original_task_file": dict(classification_task_file),
        "classification_task_file": dict(classification_task_file),
        "classification_answers_by_unit_id": {},
        "grouping_answers_by_unit_id": {},
        "unit_to_shard_id": {
            str(unit_id): str(shard_id)
            for unit_id, shard_id in unit_to_shard_id.items()
        },
        "output_dir": str(output_dir),
        "knowledge_grouping_enabled": bool(knowledge_grouping_enabled),
        "same_session_transition_count": 0,
        "classification_validation_count": 0,
        "grouping_validation_count": 0,
        "same_session_repair_rewrite_count": 0,
        "grouping_transition_count": 0,
        "grouping_unit_count": 0,
        "grouping_batch_count": 0,
        "completed_grouping_batch_count": 0,
        "pending_grouping_unit_batches": [],
        "final_output_shard_count": 0,
        "completed": False,
        "final_status": None,
        "fresh_session_retry_limit": taskfile_fresh_session_retry_limit(
            stage_key=KNOWLEDGE_POLICY_STAGE_KEY
        ),
        "fresh_session_retry_count": 0,
        "fresh_session_retry_status": "not_attempted",
        "fresh_session_retry_history": [],
        "transition_history": [],
    }
    _write_json(state_path, payload)
    return payload


def _append_transition_history(
    *,
    state: dict[str, Any],
    transition: KnowledgeTaskFileTransition,
) -> None:
    history = list(state.get("transition_history") or [])
    history.append(
        {
            "status": transition.status,
            "current_stage_key": transition.current_stage_key,
            "next_stage_key": transition.next_stage_key,
            "validation_errors": list(transition.validation_errors),
            "validation_metadata": dict(transition.validation_metadata),
            "transition_metadata": dict(transition.transition_metadata),
        }
    )
    state["transition_history"] = history


def _record_transition_counters(
    *,
    state: dict[str, Any],
    transition: KnowledgeTaskFileTransition,
) -> None:
    if transition.status == "no_edits_detected":
        return
    state["same_session_transition_count"] = int(
        state.get("same_session_transition_count") or 0
    ) + 1
    if transition.current_stage_key == "nonrecipe_classify":
        state["classification_validation_count"] = int(
            state.get("classification_validation_count") or 0
        ) + 1
    elif transition.current_stage_key == "knowledge_group":
        state["grouping_validation_count"] = int(
            state.get("grouping_validation_count") or 0
        ) + 1
    if transition.status == "repair_required":
        state["same_session_repair_rewrite_count"] = int(
            state.get("same_session_repair_rewrite_count") or 0
        ) + 1
    if transition.status == "advance_to_grouping":
        state["grouping_transition_count"] = int(
            state.get("grouping_transition_count") or 0
        ) + 1


def _same_session_repair_rewrite_count_for_stage(
    *,
    state: Mapping[str, Any],
    stage_key: str,
) -> int:
    return sum(
        1
        for row in (state.get("transition_history") or [])
        if isinstance(row, Mapping)
        and str(row.get("status") or "").strip() == "repair_required"
        and str(row.get("current_stage_key") or "").strip() == str(stage_key or "").strip()
    )


def _knowledge_recommended_command() -> str:
    return "python3 -m cookimport.llm.knowledge_same_session_handoff"


def _default_knowledge_same_session_state_path(*, workspace_root: Path) -> Path:
    return workspace_root / "_repo_control" / _KNOWLEDGE_SAME_SESSION_STATE_FILE_NAME


def _resolve_knowledge_same_session_state_path(
    *,
    workspace_root: Path,
    candidate: str | None,
) -> Path:
    candidate_text = str(candidate or "").strip()
    if candidate_text:
        return Path(candidate_text).expanduser()
    return _default_knowledge_same_session_state_path(workspace_root=workspace_root)


def _current_task_file_or_original(*, workspace_root: Path, state: Mapping[str, Any]) -> dict[str, Any]:
    task_file_path = workspace_root / TASK_FILE_NAME
    if task_file_path.exists():
        return load_task_file(task_file_path)
    return dict(state.get("current_original_task_file") or {})


def describe_knowledge_same_session_status(
    *,
    workspace_root: Path,
    state_path: Path,
) -> dict[str, Any]:
    state = _load_json_dict(state_path)
    task_file = _current_task_file_or_original(workspace_root=workspace_root, state=state)
    task_summary = summarize_task_file(payload=task_file, task_file_path=str(workspace_root / TASK_FILE_NAME))
    unit_to_shard_id = {
        str(unit_id): str(shard_id)
        for unit_id, shard_id in dict(state.get("unit_to_shard_id") or {}).items()
    }
    expected_shard_ids = sorted({shard_id for shard_id in unit_to_shard_id.values() if shard_id})
    output_dir = Path(str(state.get("output_dir") or workspace_root / "out")).expanduser()
    expected_outputs_present = sum(
        1 for shard_id in expected_shard_ids if (output_dir / f"{shard_id}.json").exists()
    )
    current_stage_key = str(state.get("current_stage_key") or task_file.get("stage_key") or "nonrecipe_classify").strip()
    mode = str(task_file.get("mode") or "initial").strip() or "initial"
    grouping_batch = (
        dict(task_file.get("grouping_batch") or {})
        if isinstance(task_file.get("grouping_batch"), Mapping)
        else {}
    )
    if bool(state.get("completed")):
        next_action = "outputs are already complete; stop"
    elif mode == "repair":
        next_action = "fix the named repair units and rerun same_session_handoff"
    elif int(task_summary.get("answered_units") or 0) < int(task_summary.get("total_units") or 0):
        next_action = "fill the remaining answer objects, then run same_session_handoff"
    else:
        next_action = "run same_session_handoff to validate or advance the task file"
    return {
        "stage_key": current_stage_key,
        "mode": mode,
        "answered_units": int(task_summary.get("answered_units") or 0),
        "total_units": int(task_summary.get("total_units") or 0),
        "same_session_completed": bool(state.get("completed")),
        "expected_outputs_present": expected_outputs_present,
        "expected_outputs_total": len(expected_shard_ids),
        "recommended_command": _knowledge_recommended_command(),
        "next_action": next_action,
        "fresh_session_retry_count": int(state.get("fresh_session_retry_count") or 0),
        "fresh_session_retry_limit": int(state.get("fresh_session_retry_limit") or 0),
        "fresh_session_retry_status": str(state.get("fresh_session_retry_status") or "not_attempted"),
        "grouping_batch": grouping_batch,
        "grouping_batch_count": int(state.get("grouping_batch_count") or 0),
        "completed_grouping_batch_count": int(
            state.get("completed_grouping_batch_count") or 0
        ),
    }


def describe_knowledge_same_session_doctor(
    *,
    workspace_root: Path,
    state_path: Path,
) -> dict[str, Any]:
    status = describe_knowledge_same_session_status(
        workspace_root=workspace_root,
        state_path=state_path,
    )
    if bool(status.get("same_session_completed")):
        diagnosis_code = "completed"
        message = "same-session helper already completed this workspace"
    elif str(status.get("mode") or "") == "repair":
        if int(status.get("answered_units") or 0) > 0:
            diagnosis_code = "repair_ready_helper_not_run"
            message = "repair answers are present; rerun the same-session helper"
        else:
            diagnosis_code = "repair_answers_missing"
            message = "repair mode is active but the named units still need corrected answers"
    elif int(status.get("answered_units") or 0) == 0:
        diagnosis_code = "awaiting_answers"
        message = "task.json still has blank answer objects"
    elif int(status.get("expected_outputs_present") or 0) < int(status.get("expected_outputs_total") or 0):
        diagnosis_code = "answers_present_helper_not_run"
        message = "task.json contains edited answers but the same-session helper has not produced final shard outputs yet"
    else:
        diagnosis_code = "ready_for_validation"
        message = "answers are present; run the same-session helper now"
    return {
        "stage_key": str(status.get("stage_key") or "nonrecipe_classify"),
        "mode": str(status.get("mode") or "initial"),
        "diagnosis_code": diagnosis_code,
        "message": message,
        "recommended_command": _knowledge_recommended_command(),
        "same_session_completed": bool(status.get("same_session_completed")),
    }


def _write_final_outputs(*, output_dir: Path, final_outputs: Mapping[str, Mapping[str, Any]]) -> None:
    for shard_id, payload in final_outputs.items():
        _write_json(output_dir / f"{shard_id}.json", payload)


def _repair_exhausted_result(
    *,
    state: Mapping[str, Any],
    transition: KnowledgeTaskFileTransition,
) -> dict[str, Any]:
    return {
        "status": "repair_exhausted",
        "current_stage_key": transition.current_stage_key,
        "next_stage_key": transition.next_stage_key,
        "same_session_transition_count": int(state.get("same_session_transition_count") or 0),
        "classification_validation_count": int(
            state.get("classification_validation_count") or 0
        ),
        "grouping_validation_count": int(state.get("grouping_validation_count") or 0),
        "same_session_repair_rewrite_count": int(
            state.get("same_session_repair_rewrite_count") or 0
        ),
        "grouping_transition_count": int(state.get("grouping_transition_count") or 0),
        "completed": False,
        "final_status": state.get("final_status"),
        "final_output_shard_count": int(state.get("final_output_shard_count") or 0),
        "validation_errors": list(transition.validation_errors),
        "validation_metadata": dict(transition.validation_metadata),
        "transition_metadata": dict(transition.transition_metadata),
    }


def advance_knowledge_same_session_handoff(
    *,
    workspace_root: Path,
    state_path: Path,
) -> dict[str, Any]:
    state = _load_json_dict(state_path)
    task_file_path = workspace_root / TASK_FILE_NAME
    edited_task_file = load_task_file(task_file_path)
    current_stage_key = str(state.get("current_stage_key") or "").strip()
    current_original_task_file = dict(state.get("current_original_task_file") or {})
    unit_to_shard_id = {
        str(unit_id): str(shard_id)
        for unit_id, shard_id in dict(state.get("unit_to_shard_id") or {}).items()
    }

    if current_stage_key == "nonrecipe_classify":
        transition = transition_knowledge_classification_task_file(
            original_task_file=current_original_task_file,
            edited_task_file=edited_task_file,
            unit_to_shard_id=unit_to_shard_id,
            knowledge_grouping_enabled=bool(
                state.get("knowledge_grouping_enabled", False)
            ),
            classification_task_file=dict(state.get("classification_task_file") or {}),
            existing_classification_answers_by_unit_id=dict(
                state.get("classification_answers_by_unit_id") or {}
            ),
        )
    elif current_stage_key == "knowledge_group":
        transition = transition_knowledge_grouping_task_file(
            original_task_file=current_original_task_file,
            edited_task_file=edited_task_file,
            classification_task_file=dict(state.get("classification_task_file") or {}),
            classification_answers_by_unit_id=dict(
                state.get("classification_answers_by_unit_id") or {}
            ),
            grouping_answers_by_unit_id=dict(state.get("grouping_answers_by_unit_id") or {}),
            unit_to_shard_id=unit_to_shard_id,
            pending_grouping_unit_batches=list(
                state.get("pending_grouping_unit_batches") or []
            ),
        )
    else:
        raise ValueError(f"unsupported current stage key {current_stage_key!r}")

    _record_transition_counters(state=state, transition=transition)
    _append_transition_history(state=state, transition=transition)

    if transition.current_stage_key == "nonrecipe_classify" and transition.validated_answers_by_unit_id:
        state["classification_answers_by_unit_id"] = dict(
            transition.validated_answers_by_unit_id
        )
    if transition.current_stage_key == "knowledge_group" and transition.validated_answers_by_unit_id:
        existing_grouping_answers = {
            str(unit_id): dict(answer)
            for unit_id, answer in dict(state.get("grouping_answers_by_unit_id") or {}).items()
            if str(unit_id).strip()
        }
        existing_grouping_answers.update(dict(transition.validated_answers_by_unit_id))
        state["grouping_answers_by_unit_id"] = existing_grouping_answers

    current_mode = str(current_original_task_file.get("mode") or "initial").strip() or "initial"
    if transition.status == "repair_required" and current_mode == "repair":
        repair_rewrite_limit = taskfile_same_session_repair_rewrite_limit(
            stage_key=KNOWLEDGE_POLICY_STAGE_KEY,
            semantic_step_key=transition.current_stage_key,
        )
        current_stage_repair_rewrite_count = _same_session_repair_rewrite_count_for_stage(
            state=state,
            stage_key=transition.current_stage_key,
        )
        if current_stage_repair_rewrite_count > repair_rewrite_limit:
            state["same_session_repair_rewrite_count"] = max(
                0,
                int(state.get("same_session_repair_rewrite_count") or 0) - 1,
            )
            state["completed"] = False
            state["final_status"] = "repair_exhausted"
            _write_json(state_path, state)
            return _repair_exhausted_result(state=state, transition=transition)

    if transition.next_task_file is not None:
        write_task_file(path=task_file_path, payload=transition.next_task_file)
        state["current_original_task_file"] = dict(transition.next_task_file)
        state["current_stage_key"] = str(
            transition.next_stage_key or transition.current_stage_key
        )
    if transition.status == "advance_to_grouping":
        if transition.current_stage_key == "nonrecipe_classify":
            state["grouping_unit_count"] = int(
                transition.transition_metadata.get("grouping_unit_count") or 0
            )
            state["grouping_batch_count"] = int(
                transition.transition_metadata.get("grouping_batch_count") or 0
            )
            state["completed_grouping_batch_count"] = 0
        elif transition.current_stage_key == "knowledge_group":
            state["completed_grouping_batch_count"] = int(
                state.get("completed_grouping_batch_count") or 0
            ) + 1
        state["pending_grouping_unit_batches"] = [
            [
                str(unit_id).strip()
                for unit_id in batch_unit_ids
                if str(unit_id).strip()
            ]
            for batch_unit_ids in (
                transition.transition_metadata.get("pending_grouping_unit_batches") or []
            )
            if batch_unit_ids
        ]
    if transition.final_outputs is not None:
        output_dir = Path(str(state.get("output_dir") or "")).expanduser()
        _write_final_outputs(output_dir=output_dir, final_outputs=transition.final_outputs)
        state["completed"] = True
        state["final_status"] = transition.status
        state["final_output_shard_count"] = len(transition.final_outputs)
        if transition.current_stage_key == "knowledge_group":
            state["completed_grouping_batch_count"] = int(
                state.get("grouping_batch_count") or state.get("completed_grouping_batch_count") or 0
            ) or 1
        state["pending_grouping_unit_batches"] = []

    _write_json(state_path, state)
    return {
        "status": transition.status,
        "current_stage_key": transition.current_stage_key,
        "next_stage_key": transition.next_stage_key,
        "same_session_transition_count": int(state.get("same_session_transition_count") or 0),
        "classification_validation_count": int(
            state.get("classification_validation_count") or 0
        ),
        "grouping_validation_count": int(state.get("grouping_validation_count") or 0),
        "same_session_repair_rewrite_count": int(
            state.get("same_session_repair_rewrite_count") or 0
        ),
        "grouping_transition_count": int(state.get("grouping_transition_count") or 0),
        "completed": bool(state.get("completed")),
        "final_status": state.get("final_status"),
        "final_output_shard_count": int(state.get("final_output_shard_count") or 0),
        "validation_errors": list(transition.validation_errors),
        "validation_metadata": dict(transition.validation_metadata),
        "transition_metadata": dict(transition.transition_metadata),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and advance one knowledge same-session task.json handoff."
    )
    parser.add_argument(
        "--state-path",
        default=os.environ.get(KNOWLEDGE_SAME_SESSION_STATE_ENV),
        help=f"Path to the hidden repo-owned handoff state file. Defaults to ${KNOWLEDGE_SAME_SESSION_STATE_ENV}.",
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root containing task.json. Defaults to the current directory.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print a read-only workspace status summary.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Print a read-only workspace diagnosis.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    workspace_root = Path(str(args.workspace_root)).expanduser()
    state_path = _resolve_knowledge_same_session_state_path(
        workspace_root=workspace_root,
        candidate=args.state_path,
    )
    if not state_path.exists():
        raise SystemExit(
            "missing same-session state file; expected "
            f"{state_path} or set --state-path / ${KNOWLEDGE_SAME_SESSION_STATE_ENV}"
        )
    if args.status and args.doctor:
        raise SystemExit("use either --status or --doctor, not both")
    if args.status:
        result = describe_knowledge_same_session_status(
            workspace_root=workspace_root,
            state_path=state_path,
        )
    elif args.doctor:
        result = describe_knowledge_same_session_doctor(
            workspace_root=workspace_root,
            state_path=state_path,
        )
    else:
        result = advance_knowledge_same_session_handoff(
            workspace_root=workspace_root,
            state_path=state_path,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
